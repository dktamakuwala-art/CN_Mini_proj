import eventlet

eventlet.monkey_patch()

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, ipv4, udp
from os_ken.ofproto import ofproto_v1_3

import json
import os
import time

from src.config import (
    EMERGENCY_PORT, NORMAL_PORT, BACKGROUND_PORT, SERVER_PORT,
    CONGESTION_DROP_THRESHOLD, CONGESTION_CHECK_INTERVAL,
    SDN_SIGNAL_PORT, FLOOD_RATE_THRESHOLD_MBPS, FLOOD_BLOCK_SECONDS,
    EMERGENCY_HOLD_SECONDS,
)

EVENT_LOG = os.environ.get("SDN_EVENT_LOG", "logs/controller_events.jsonl")


class EmergencyController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.previous_drop_counters = {}
        self.congested_ports = set()
        self.previous_rx = {}            # (dpid, port) -> (rx_bytes, time)
        self.blocked_ports = {}          # (dpid, port) -> expiry time
        self.emergency_until = 0.0       # emergency mode active while now < this
        self.monitor_thread = hub.spawn(self._monitor_loop)

    @staticmethod
    def _classify_traffic(udp_port):
        if udp_port == EMERGENCY_PORT:
            return "EMERGENCY", 1, 300
        if udp_port == NORMAL_PORT:
            return "NORMAL", 2, 200
        if udp_port == SERVER_PORT:
            return "CONTROL", 1, 250
        if udp_port == BACKGROUND_PORT:
            return "BACKGROUND", 0, 50
        return "OTHER", None, 10

    @property
    def emergency_active(self):
        return time.monotonic() < self.emergency_until

    def log_event(self, event, **fields):
        """Append a timestamped controller decision to a JSONL file (evidence for the report)."""
        record = {"t": round(time.time(), 3), "event": event, **fields}
        self.logger.info("EVENT %s", record)
        try:
            os.makedirs(os.path.dirname(EVENT_LOG) or ".", exist_ok=True)
            with open(EVENT_LOG, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError:
            pass

    def delete_flows(self, datapath, udp_dst):
        parser, ofp = datapath.ofproto_parser, datapath.ofproto
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, command=ofp.OFPFC_DELETE,
            out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
            match=parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=udp_dst),
        ))

    def handle_app_signal(self, datapath, payload):
        """Application -> SDN: the notification server reports emergency start/end."""
        try:
            msg = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        event = msg.get("event")
        if event == "EMERGENCY_START":
            was_active = self.emergency_active
            self.emergency_until = time.monotonic() + EMERGENCY_HOLD_SECONDS
            if not was_active:
                # Re-learn NORMAL/BACKGROUND flows so they are pushed to the low queue now.
                for dp in self.datapaths.values():
                    self.delete_flows(dp, NORMAL_PORT)
                    self.delete_flows(dp, BACKGROUND_PORT)
                self.log_event("EMERGENCY_MODE_ON", id=msg.get("id"),
                               action="demote NORMAL/BACKGROUND to queue 0, flush their flows")
        elif event == "EMERGENCY_END":
            self.emergency_until = 0.0
            for dp in self.datapaths.values():  # restore normal queues
                self.delete_flows(dp, NORMAL_PORT)
                self.delete_flows(dp, BACKGROUND_PORT)
            self.log_event("EMERGENCY_MODE_OFF", id=msg.get("id"))

    def block_port(self, datapath, port, rate):
        """Rate-limit a flooding port: drop its low-priority UDP, keep emergency + control."""
        parser = datapath.ofproto_parser
        ofp = datapath.ofproto
        match = parser.OFPMatch(in_port=port, eth_type=0x0800, ip_proto=17)
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, priority=220, match=match, instructions=[],
            hard_timeout=FLOOD_BLOCK_SECONDS,
        ))
        # Ensure unlearned/expired emergency, control, and SDN signal packets still reach the controller
        for allowed_port in (EMERGENCY_PORT, SERVER_PORT, SDN_SIGNAL_PORT):
            allow_match = parser.OFPMatch(
                in_port=port, eth_type=0x0800, ip_proto=17, udp_dst=allowed_port
            )
            self.add_flow(
                datapath, 225, allow_match,
                [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)],
                idle_timeout=0, hard_timeout=FLOOD_BLOCK_SECONDS,
            )
        self.blocked_ports[(datapath.id, port)] = time.monotonic() + FLOOD_BLOCK_SECONDS
        self.log_event("FLOOD_BLOCKED", dpid=datapath.id, port=port,
                       rate_mbps=round(rate, 2), seconds=FLOOD_BLOCK_SECONDS,
                       action="drop non-emergency UDP from this port (priority 220)")

    @property
    def congestion_detected(self):
        return bool(self.congested_ports)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=60, hard_timeout=0):
        parser = datapath.ofproto_parser
        instructions = [parser.OFPInstructionActions(
            datapath.ofproto.OFPIT_APPLY_ACTIONS, actions
        )]
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
        ))

    def _request_port_stats(self, datapath):
        parser = datapath.ofproto_parser
        datapath.send_msg(parser.OFPPortStatsRequest(
            datapath, 0, datapath.ofproto.OFPP_ANY
        ))

    def _monitor_loop(self):
        while True:
            for datapath in list(self.datapaths.values()):
                self._request_port_stats(datapath)
            hub.sleep(CONGESTION_CHECK_INTERVAL)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.datapaths[datapath.id] = datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        self.add_flow(
            datapath, 0, parser.OFPMatch(),
            [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                    ofproto.OFPCML_NO_BUFFER)],
            idle_timeout=0,
        )
        self._request_port_stats(datapath)
        self.logger.info("Switch connected: %s", datapath.id)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        for stat in ev.msg.body:
            port = stat.port_no
            key = (dpid, port)
            now = time.monotonic()
            prev_rx = self.previous_rx.get(key)
            self.previous_rx[key] = (stat.rx_bytes, now)
            if prev_rx and now > prev_rx[1] and port < 0xffffff00:
                rate = max(0, stat.rx_bytes - prev_rx[0]) * 8 / (now - prev_rx[1]) / 1e6
                if (rate > FLOOD_RATE_THRESHOLD_MBPS
                        and self.blocked_ports.get(key, 0) < now):
                    self.block_port(ev.msg.datapath, port, rate)
            current = stat.tx_dropped + stat.rx_dropped
            previous = self.previous_drop_counters.get(key, current)
            delta = max(0, current - previous)
            self.previous_drop_counters[key] = current
            if delta >= CONGESTION_DROP_THRESHOLD:
                self.congested_ports.add(key)
                self.logger.warning(
                    "Congestion detected on switch %s port %s: %s new drops",
                    dpid, port, delta
                )
            elif delta == 0:
                self.congested_ports.discard(key)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][eth.src] = in_port
        out_port = self.mac_to_port[dpid].get(eth.dst, ofproto.OFPP_FLOOD)

        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)
        actions = []

        if udp_pkt and udp_pkt.dst_port == SDN_SIGNAL_PORT:
            self.handle_app_signal(datapath, pkt.protocols[-1] if isinstance(
                pkt.protocols[-1], (bytes, bytearray)) else b"")
            return  # signalling is consumed by the controller, never forwarded

        if ip_pkt and udp_pkt and out_port != ofproto.OFPP_FLOOD:
            traffic_type, queue_id, base_priority = self._classify_traffic(udp_pkt.dst_port)
            congested = (dpid, out_port) in self.congested_ports
            if traffic_type in ("NORMAL", "BACKGROUND") and (congested or self.emergency_active):
                queue_id = 0
            priority = base_priority

            if queue_id is not None:
                actions.append(parser.OFPActionSetQueue(queue_id))
            actions.append(parser.OFPActionOutput(out_port))

            match = parser.OFPMatch(
                in_port=in_port,
                eth_dst=eth.dst,
                eth_type=0x0800,
                ip_proto=17,
                udp_dst=udp_pkt.dst_port,
            )
            self.add_flow(datapath, priority, match, actions)
            self.logger.info(
                "%s traffic: UDP destination %s, queue %s, flow priority %s",
                traffic_type, udp_pkt.dst_port, queue_id, priority
            )
        else:
            actions.append(parser.OFPActionOutput(out_port))

        datapath.send_msg(parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None,
        ))
