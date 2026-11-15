import eventlet

eventlet.monkey_patch()

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, ipv4, udp
from os_ken.ofproto import ofproto_v1_3


class EmergencyController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(EmergencyController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.port_stats = {}
        self.congestion_detected = False
        self.monitor_thread = hub.spawn(self._monitor_loop)

    @staticmethod
    def _classify_traffic(udp_port):
        if udp_port == 5001:
            return "EMERGENCY", 1, 300
        if udp_port == 5002:
            return "NORMAL", 2, 200
        if udp_port == 6000:
            return "BACKGROUND", 0, 50
        return "OTHER", 0, 10

    def add_flow(self, datapath, priority, match, actions):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        instructions = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)
        ]
        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=60,
        )
        datapath.send_msg(flow_mod)

    def _request_port_stats(self, datapath):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    def _monitor_loop(self):
        while True:
            for datapath in list(self.datapaths.values()):
                self._request_port_stats(datapath)
            hub.sleep(2)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        self.datapaths[datapath.id] = datapath
        self.logger.info("Switch connected: %s", datapath.id)

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self._request_port_stats(datapath)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        self.port_stats.setdefault(dpid, {})

        for stat in ev.msg.body:
            port = stat.port_no
            self.port_stats[dpid][port] = stat
            dropped = stat.tx_dropped + stat.rx_dropped
            if dropped > 50:
                self.congestion_detected = True
                self.logger.warning("Congestion detected on switch %s port %s: dropped=%s", dpid, port, dropped)
            elif dropped < 10 and self.congestion_detected:
                self.congestion_detected = False
                self.logger.info("Network congestion cleared on switch %s", dpid)

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

        src = eth.src
        dst = eth.dst
        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port
        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)

        actions = []
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)

        if ip_pkt and udp_pkt and out_port != ofproto.OFPP_FLOOD:
            udp_dst = udp_pkt.dst_port
            traffic_type, queue_id, static_priority = self._classify_traffic(udp_dst)

            if self.congestion_detected and traffic_type == "NORMAL":
                priority = 10
                queue_id = 0
                self.logger.info("Dynamic congestion response: NORMAL traffic demoted to queue %s", queue_id)
            elif self.congestion_detected and traffic_type == "EMERGENCY":
                priority = 500
                queue_id = 1
                self.logger.info("Dynamic congestion response: EMERGENCY traffic prioritized to queue %s", queue_id)
            else:
                priority = static_priority

            match = parser.OFPMatch(
                in_port=in_port,
                eth_dst=dst,
                eth_type=0x0800,
                ip_proto=17,
                udp_dst=udp_dst,
            )

            if queue_id is not None:
                actions.append(parser.OFPActionSetQueue(queue_id))
            actions.append(parser.OFPActionOutput(out_port))
            self.add_flow(datapath, priority, match, actions)
            self.logger.info("%s traffic classified on port %s with queue %s priority %s", traffic_type, udp_dst, queue_id, priority)
        elif out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
            actions = [parser.OFPActionOutput(out_port)]
            self.add_flow(datapath, 10, match, actions)
            self.logger.info("Installed L2 learning flow for %s -> %s on port %s", src, dst, out_port)
        else:
            actions.append(parser.OFPActionOutput(out_port))

        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)
