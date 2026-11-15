import eventlet

eventlet.monkey_patch()

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, ipv4, udp
from os_ken.ofproto import ofproto_v1_3

from src.config import (
    EMERGENCY_PORT, NORMAL_PORT, BACKGROUND_PORT,
    CONGESTION_DROP_THRESHOLD, CONGESTION_CHECK_INTERVAL,
)


class EmergencyController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.previous_drop_counters = {}
        self.congested_ports = set()
        self.monitor_thread = hub.spawn(self._monitor_loop)

    @staticmethod
    def _classify_traffic(udp_port):
        if udp_port == EMERGENCY_PORT:
            return "EMERGENCY", 1, 300
        if udp_port == NORMAL_PORT:
            return "NORMAL", 2, 200
        if udp_port == BACKGROUND_PORT:
            return "BACKGROUND", 0, 50
        return "OTHER", None, 10

    @property
    def congestion_detected(self):
        return bool(self.congested_ports)

    def add_flow(self, datapath, priority, match, actions):
        parser = datapath.ofproto_parser
        instructions = [parser.OFPInstructionActions(
            datapath.ofproto.OFPIT_APPLY_ACTIONS, actions
        )]
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=60,
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
                                    ofproto.OFPCML_NO_BUFFER)]
        )
        self._request_port_stats(datapath)
        self.logger.info("Switch connected: %s", datapath.id)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        for stat in ev.msg.body:
            port = stat.port_no
            key = (dpid, port)
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

        if ip_pkt and udp_pkt:
            traffic_type, queue_id, base_priority = self._classify_traffic(udp_pkt.dst_port)
            congested = (dpid, out_port) in self.congested_ports
            if congested and traffic_type == "NORMAL":
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
