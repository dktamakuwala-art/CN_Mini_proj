from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib.packet import packet, ethernet, ipv4, udp


class EmergencyController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(EmergencyController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}

    def add_flow(self, datapath, priority, match, actions):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        instructions = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS, actions
            )
        ]

        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions
        )
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER,
                ofproto.OFPCML_NO_BUFFER
            )
        ]

        self.add_flow(datapath, 0, match, actions)
        self.logger.info("Switch connected: %s", datapath.id)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return

        src = eth.src
        dst = eth.dst
        dpid = datapath.id

        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][src] = in_port

        out_port = self.mac_to_port[dpid].get(
            dst, ofproto.OFPP_FLOOD
        )

        actions = [parser.OFPActionOutput(out_port)]

        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)

        if ip_pkt and udp_pkt and out_port != ofproto.OFPP_FLOOD:

            if udp_pkt.dst_port == 5001:
                priority = 200
                queue_id = 1
                traffic_type = "EMERGENCY"

            elif udp_pkt.dst_port == 5002:
                priority = 100
                queue_id = 2
                traffic_type = "NORMAL"

            else:
                priority = 10
                queue_id = None
                traffic_type = "OTHER"

            actions = []

            if queue_id is not None:
                actions.append(parser.OFPActionSetQueue(queue_id))

            actions.append(parser.OFPActionOutput(out_port))

            match = parser.OFPMatch(
                in_port=in_port,
                eth_dst=dst,
                eth_type=0x0800,
                ip_proto=17,
                udp_dst=udp_pkt.dst_port
            )

            self.add_flow(datapath, priority, match, actions)

            self.logger.info(
                "%s traffic: UDP port %s, queue %s",
                traffic_type, udp_pkt.dst_port, queue_id
            )

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )

        datapath.send_msg(out)
