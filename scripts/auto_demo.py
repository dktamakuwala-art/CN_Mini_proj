#!/usr/bin/env python3
"""Automated Mininet demo. Run with sudo AFTER starting the controller in another terminal."""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet_topology import EmergencyTopology, configure_qos

PY = "python3"


def main():
    setLogLevel("warning")
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    net = Mininet(topo=EmergencyTopology(), controller=None, link=TCLink)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    net.start()
    try:
        configure_qos(net)
        time.sleep(2)
        h1, h2, h3, h4 = (net.get(h) for h in ("h1", "h2", "h3", "h4"))

        print("== pingAll ==")
        loss = net.pingAll()
        print(f"packet loss: {loss}%")

        procs, logs = [], []
        for i, h in enumerate((h2, h3, h4), 1):
            f = open(os.path.join(ROOT, "logs", f"client{i}.log"), "w")
            logs.append(f)
            procs.append(h.popen([PY, "-u", "client.py", "--name", f"Client{i}"],
                                 cwd=ROOT, stdout=f, stderr=subprocess.STDOUT))
        time.sleep(1)

        print("== server ==")
        out = h1.cmd(f"cd {ROOT} && {PY} -u scripts/demo_server.py --clients 3")
        print(out)

        for p in procs:
            p.terminate()
        for f in logs:
            f.close()
        for i in (1, 2, 3):
            print(f"== client{i}.log ==")
            print(open(os.path.join(ROOT, "logs", f"client{i}.log")).read())

        print("== flow table (priority 300=EMERGENCY, 200=NORMAL) ==")
        print(net.get("s1").cmd("ovs-ofctl -O OpenFlow13 dump-flows s1"))
    finally:
        net.stop()


if __name__ == "__main__":
    main()
