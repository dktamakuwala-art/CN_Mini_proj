#!/usr/bin/env python3
"""Create a simple Mininet topology for the emergency network demo."""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.cli import CLI


class EmergencyTopology(Topo):
    def build(self):
        h1 = self.addHost("h1", ip="10.0.0.1/24")
        h2 = self.addHost("h2", ip="10.0.0.2/24")
        h3 = self.addHost("h3", ip="10.0.0.3/24")
        h4 = self.addHost("h4", ip="10.0.0.4/24")
        s1 = self.addSwitch("s1", cls=OVSSwitch, protocols="OpenFlow13")

        self.addLink(h1, s1, cls=TCLink, bw=10, delay="2ms")
        self.addLink(h2, s1, cls=TCLink, bw=10, delay="2ms")
        self.addLink(h3, s1, cls=TCLink, bw=10, delay="2ms")
        self.addLink(h4, s1, cls=TCLink, bw=10, delay="2ms")


def configure_qos(net):
    switch = net.get("s1")
    switch.cmd("ovs-vsctl set Bridge s1 protocols=OpenFlow13")
    switch.cmd(
        "ovs-vsctl -- --id=@q0 create Queue other-config:min-rate=0 other-config:max-rate=1000000 "
        "-- --id=@q1 create Queue other-config:min-rate=8000000 other-config:max-rate=10000000 "
        "-- --id=@q2 create Queue other-config:min-rate=2000000 other-config:max-rate=10000000 "
        "-- --id=@qos create QoS type=linux-htb other-config:max-rate=10000000 queues=0=@q0,1=@q1,2=@q2 "
        "-- set Port s1-eth1 qos=@qos -- set Port s1-eth2 qos=@qos -- set Port s1-eth3 qos=@qos -- set Port s1-eth4 qos=@qos"
    )


def main():
    topo = EmergencyTopology()
    net = Mininet(topo=topo, controller=None, link=TCLink)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    net.start()
    configure_qos(net)
    CLI(net)
    net.stop()


if __name__ == "__main__":
    main()
