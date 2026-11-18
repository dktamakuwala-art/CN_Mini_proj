#!/usr/bin/env python3
"""Static vs dynamic-SDN comparison under background congestion.

Run with:  sudo python3 scripts/run_experiment.py [--loads 0 3 6 10] [--n 15]
Starts/stops the controller itself, one clean Mininet network per condition.
Output: results/sdn_vs_static.csv, logs/controller_<mode>_<load>.jsonl
"""
import argparse, csv, json, os, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mininet.net import Mininet
from mininet.node import RemoteController
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet_topology import EmergencyTopology, configure_qos

CONTROLLERS = {"static": "src/controller_static.py", "sdn": "src/controller.py"}
PY = "python3"


def run_condition(mode, load, n):
    log_file = os.path.join(ROOT, "logs", f"controller_{mode}_{load}.jsonl")
    if os.path.exists(log_file):
        os.remove(log_file)
    env = dict(os.environ, SDN_EVENT_LOG=log_file, PYTHONPATH=ROOT)
    ctl_out = open(os.path.join(ROOT, "logs", f"ctl_{mode}_{load}.out"), "w")
    ctl = subprocess.Popen(["osken-manager", CONTROLLERS[mode]], cwd=ROOT, env=env,
                           stdout=ctl_out, stderr=subprocess.STDOUT)
    time.sleep(3)
    net = Mininet(topo=EmergencyTopology(), controller=None, link=TCLink)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    net.start()
    procs = []
    try:
        if mode == "sdn":
            configure_qos(net)          # queues only for the SDN configuration
        time.sleep(2)
        h1, h2, h3, h4 = (net.get(x) for x in ("h1", "h2", "h3", "h4"))
        net.pingAll(timeout=2)

        # Start probe_server on h1 first so clients can register immediately
        cmd = [PY, "-u", "scripts/probe_server.py", "--n", str(n),
               "--delay", "5" if load > 0 else "0"]
        if mode == "sdn":
            cmd.append("--sdn-signal")
        probe_proc = h1.popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(0.5)

        for i, h in enumerate((h2, h3, h4), 1):
            procs.append(h.popen([PY, "-u", "client.py", "--name", f"Client{i}"], cwd=ROOT,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        time.sleep(1.5)
        if load > 0:                    # h3 and h4 both flood h2 -> 2*load into one 10 Mbps port
            for h in (h3, h4):
                procs.append(h.popen([PY, "scripts/flood.py", "10.0.0.2", "6000", str(load)],
                                     cwd=ROOT, stdout=subprocess.DEVNULL))

        out, _ = probe_proc.communicate(timeout=max(60, n * 10))
        line = [l for l in out.splitlines() if l.startswith("{")]
        result = json.loads(line[-1]) if line else {"error": out[-200:]}
        flows = net.get("s1").cmd("ovs-ofctl -O OpenFlow13 dump-flows s1")
        open(os.path.join(ROOT, "logs", f"flows_{mode}_{load}.txt"), "w").write(flows)
        return result
    finally:
        for p in procs:
            p.terminate()
        net.stop()
        ctl.terminate()
        try:
            ctl.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ctl.kill()
        ctl_out.close()
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loads", type=float, nargs="+", default=[0, 3, 6, 10])
    ap.add_argument("--n", type=int, default=15)
    a = ap.parse_args()
    setLogLevel("warning")
    subprocess.call(["mn", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    rows = []
    for load in a.loads:
        for mode in ("static", "sdn"):
            print(f"[run] mode={mode} per-flooder load={load} Mbps", flush=True)
            r = run_condition(mode, load, a.n)
            print("      ", r, flush=True)
            rows.append({"mode": mode, "flood_mbps_each": load,
                         "total_background_mbps": 2 * load, **r})
    path = os.path.join(ROOT, "results", "sdn_vs_static.csv")
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("mode", "flood_mbps_each", "total_background_mbps"), k))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print("wrote", path)


if __name__ == "__main__":
    main()
