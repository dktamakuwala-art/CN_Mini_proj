#!/usr/bin/env python3
"""Control panel: start controller/network/apps, send alerts, watch topology + client screens.

  sudo python3 scripts/control_panel.py          # full demo (needs Mininet + OVS + os-ken)
  python3 scripts/control_panel.py --sim         # apps only on loopback, no SDN (no root)
"""
import argparse
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
CLIENTS = [("Client1", "h2"), ("Client2", "h3"), ("Client3", "h4")]
SERVER_IP = "10.0.0.1"


def parse_ports(text):
    ports = {}
    for m in re.finditer(r'port\s+"?s1-eth(\d+)"?:\s+rx pkts=(\d+), bytes=(\d+).*?\n\s+tx pkts=(\d+), bytes=(\d+)', text):
        n, rxp, rxb, txp, txb = map(int, m.groups())
        ports[n] = {"rx_pkts": rxp, "rx_bytes": rxb, "tx_pkts": txp, "tx_bytes": txb}
    return ports


def parse_flows(text):
    flows = []
    for line in text.splitlines():
        if " actions=" not in line:
            continue
        head, actions = line.split(" actions=", 1)
        pri = re.search(r"priority=(\d+)", head)
        pk = re.search(r"n_packets=(\d+)", head)
        match = head.split("priority=" + (pri.group(1) if pri else ""), 1)[-1].lstrip(",")
        flows.append({"priority": int(pri.group(1)) if pri else 0,
                      "packets": int(pk.group(1)) if pk else 0,
                      "match": match, "actions": actions.strip()})
    return sorted(flows, key=lambda f: (-f["priority"], -f["packets"]))


def parse_queues(text):
    return [{"port": int(p), "queue": int(q), "bytes": int(b), "pkts": int(k)}
            for p, q, b, k in re.findall(r"port (\d+) queue (\d+): bytes=(\d+), pkts=(\d+)", text)]


class Panel:
    def __init__(self, sim, osken):
        self.sim, self.osken = sim, osken
        self.lock = threading.RLock()
        self.tasks = queue.Queue()
        self.stop_evt = threading.Event()
        self.busy, self.error, self.ping = "", "", ""
        self.net, self.net_status = None, "stopped"
        self.ctrl, self.switch = None, False
        self.ctrl_log, self.server_log = deque(maxlen=80), deque(maxlen=80)
        self.server, self.server_state = None, None
        self.send_results = queue.Queue()
        self.clients = {}
        self.flood_proc = None
        self.netstats = {"ports": {}, "rates": {}, "flows": [], "queues": []}
        self._last = None

    # ---------- process plumbing ----------
    def spawn(self, host, argv, stdin=False):
        kw = dict(cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                  universal_newlines=True, bufsize=1)
        if stdin:
            kw["stdin"] = subprocess.PIPE
        if self.net:
            return self.net.get(host).popen(argv, **kw)
        return subprocess.Popen(argv, **kw)

    @staticmethod
    def pump(proc, fn):
        def run():
            for line in proc.stdout:
                try:
                    fn(line.rstrip("\n"))
                except Exception:
                    pass
        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def alive(proc):
        return proc is not None and proc.poll() is None

    # ---------- controller ----------
    def controller_start(self):
        if self.sim:
            raise RuntimeError("Controller is not used in --sim mode.")
        if self.alive(self.ctrl):
            return
        if not self.osken:
            raise RuntimeError("osken-manager not found. Pass --osken /path/to/osken-manager.")
        self.switch = False
        self.ctrl_log.clear()
        env = dict(os.environ, PYTHONPATH=ROOT)
        self.ctrl = subprocess.Popen([self.osken, "src/controller.py"], cwd=ROOT, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     universal_newlines=True, bufsize=1)
        self.pump(self.ctrl, self.on_ctrl)

    def on_ctrl(self, line):
        self.ctrl_log.append(line)
        if "Switch connected" in line:
            self.switch = True

    def controller_stop(self):
        if self.alive(self.ctrl):
            self.ctrl.terminate()
            try:
                self.ctrl.wait(3)
            except subprocess.TimeoutExpired:
                self.ctrl.kill()
        self.switch = False

    # ---------- network (main thread only) ----------
    def network_start(self):
        if self.sim:
            raise RuntimeError("Network is not used in --sim mode.")
        if self.net:
            return
        if not self.alive(self.ctrl):
            raise RuntimeError("Start the controller first.")
        from mininet.net import Mininet
        from mininet.node import RemoteController
        from mininet.link import TCLink
        from mininet.log import setLogLevel
        from mininet_topology import EmergencyTopology, configure_qos
        setLogLevel("warning")
        self.net_status = "starting"
        try:
            net = Mininet(topo=EmergencyTopology(), controller=None, link=TCLink)
            net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
            net.start()
            configure_qos(net)
        except Exception:
            self.net_status = "stopped"
            raise
        self.net, self.net_status, self.ping = net, "up", ""
        threading.Thread(target=self.stats_loop, daemon=True).start()

    def network_stop(self):
        self.apps_stop()
        self.flood_set(False)
        if self.net:
            self.net_status = "stopping"
            net, self.net = self.net, None
            net.stop()
        self.net_status = "stopped"
        self.netstats = {"ports": {}, "rates": {}, "flows": [], "queues": []}

    def ping_all(self):
        if not self.net:
            raise RuntimeError("Network is not running.")
        loss = self.net.pingAll(timeout=1)
        self.ping = f"{loss:.0f}% packet loss"

    def ovs(self, *args):
        try:
            return subprocess.run(["ovs-ofctl", "-O", "OpenFlow13", *args, "s1"], capture_output=True,
                                  text=True, timeout=3).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def stats_loop(self):
        while self.net and not self.stop_evt.is_set():
            now = time.monotonic()
            ports = parse_ports(self.ovs("dump-ports"))
            rates = {}
            if self._last:
                dt = max(now - self._last[0], 0.1)
                for n, p in ports.items():
                    old = self._last[1].get(n)
                    if old:
                        moved = (p["rx_bytes"] + p["tx_bytes"]) - (old["rx_bytes"] + old["tx_bytes"])
                        rates[n] = round(max(moved, 0) * 8 / 1000 / dt, 1)
            self._last = (now, ports)
            self.netstats = {"ports": ports, "rates": rates,
                             "flows": parse_flows(self.ovs("dump-flows"))[:14],
                             "queues": parse_queues(self.ovs("queue-stats"))}
            time.sleep(1)

    def flood_set(self, on):
        if on:
            if not self.net:
                raise RuntimeError("Background load needs the Mininet network.")
            if not self.alive(self.flood_proc):
                self.flood_proc = self.spawn("h4", [sys.executable, "scripts/flood.py", SERVER_IP, "6000", "15"])
        elif self.alive(self.flood_proc):
            self.flood_proc.terminate()
            self.flood_proc = None

    # ---------- apps ----------
    def apps_start(self):
        if not self.sim and not self.net:
            raise RuntimeError("Start the network first.")
        if self.alive(self.server):
            return
        self.server_state = None
        srv_argv = [sys.executable, "-u", "scripts/host_server.py"] + ([] if self.sim else ["--sdn-signal"])
        self.server = self.spawn("h1", srv_argv, stdin=True)
        self.pump(self.server, self.on_server)
        time.sleep(1.5)
        for i, (name, host) in enumerate(CLIENTS, 1):
            argv = [sys.executable, "-u", "scripts/host_client.py", "--name", name]
            if self.sim:
                argv += ["--server-ip", "127.0.0.1", "--emergency-port", str(6000 + i * 10),
                         "--normal-port", str(6001 + i * 10)]
            proc = self.spawn(host, argv)
            c = {"name": name, "host": host, "proc": proc, "events": deque(maxlen=30),
                 "seq": 0, "frozen": False, "status": "starting"}
            self.clients[name] = c
            self.pump(proc, lambda line, c=c: self.on_client(c, line))

    def on_server(self, line):
        if line.startswith("STATE "):
            self.server_state = json.loads(line[6:])
        elif line.startswith("MSG "):
            self.send_results.put(json.loads(line[4:]))
        else:
            self.server_log.append(line)

    def on_client(self, c, line):
        if not line.startswith("EVT "):
            return
        evt = json.loads(line[4:])
        if evt["kind"] == "registered":
            c["status"] = "registered"
        elif evt["kind"] in ("error", "server_shutdown"):
            c["status"] = evt["kind"]
        with self.lock:
            c["seq"] += 1
            evt["seq"] = c["seq"]
            c["events"].append(evt)

    def apps_stop(self):
        for c in self.clients.values():
            if self.alive(c["proc"]):
                if c["frozen"]:
                    os.kill(c["proc"].pid, signal.SIGCONT)
                c["proc"].terminate()
        for c in self.clients.values():
            try:
                c["proc"].wait(3)
            except subprocess.TimeoutExpired:
                c["proc"].kill()
        self.clients.clear()
        if self.alive(self.server):
            try:
                self.server.stdin.close()
                self.server.wait(3)
            except (OSError, subprocess.TimeoutExpired):
                self.server.kill()
        self.server, self.server_state = None, None

    def send(self, kind, message):
        if not self.alive(self.server):
            raise RuntimeError("Start the apps first.")
        message = " ".join(message.split())
        if kind not in ("NORMAL", "EMERGENCY") or not message:
            raise ValueError("Pick a type and enter a message.")
        while not self.send_results.empty():
            self.send_results.get_nowait()
        self.server.stdin.write(f"SEND|{kind}|{message}\n")
        self.server.stdin.flush()
        try:
            res = self.send_results.get(timeout=2)
        except queue.Empty:
            raise RuntimeError("Server did not respond.")
        if not res["ok"]:
            raise RuntimeError(res["error"])

    def freeze(self, name, frozen):
        c = self.clients.get(name)
        if not c or not self.alive(c["proc"]):
            raise RuntimeError("Client is not running.")
        os.kill(c["proc"].pid, signal.SIGSTOP if frozen else signal.SIGCONT)
        c["frozen"] = frozen

    # ---------- snapshot ----------
    def snapshot(self):
        with self.lock:
            clients = [{"name": c["name"], "host": c["host"], "frozen": c["frozen"],
                        "running": self.alive(c["proc"]), "status": c["status"],
                        "events": list(c["events"])} for c in self.clients.values()]
        return {
            "sim": self.sim, "busy": self.busy, "error": self.error, "ping": self.ping,
            "controller": {"running": self.alive(self.ctrl), "switch": self.switch,
                           "log": list(self.ctrl_log)[-25:]},
            "network": {"status": self.net_status},
            "apps": {"running": self.alive(self.server)},
            "server": self.server_state, "server_log": list(self.server_log)[-25:],
            "clients": clients, "net": self.netstats, "flood": self.alive(self.flood_proc),
        }

    # ---------- task runner (Mininet needs one thread) ----------
    def submit(self, label, fn):
        if self.busy:
            raise RuntimeError(f"Busy: {self.busy}")
        self.busy, self.error = label, ""
        self.tasks.put((label, fn))

    def run_forever(self):
        while not self.stop_evt.is_set():
            try:
                label, fn = self.tasks.get(timeout=0.3)
            except queue.Empty:
                continue
            try:
                fn()
            except Exception as exc:
                self.error = str(exc) or exc.__class__.__name__
            finally:
                self.busy = ""

    def shutdown(self):
        self.stop_evt.set()
        for step in (self.apps_stop, self.network_stop, self.controller_stop):
            try:
                step()
            except Exception:
                pass

    # ---------- actions ----------
    def action(self, data):
        a = data.get("action")
        direct = {
            "controller_start": self.controller_start, "controller_stop": self.controller_stop,
            "send": lambda: self.send(str(data.get("type", "")), str(data.get("message", ""))),
            "freeze": lambda: self.freeze(str(data.get("name", "")), True),
            "resume": lambda: self.freeze(str(data.get("name", "")), False),
        }
        queued = {
            "network_start": self.network_start, "network_stop": self.network_stop,
            "ping": self.ping_all, "apps_start": self.apps_start, "apps_stop": self.apps_stop,
            "flood_on": lambda: self.flood_set(True), "flood_off": lambda: self.flood_set(False),
        }
        if a in direct:
            direct[a]()
        elif a in queued:
            self.submit(a, queued[a])
        else:
            raise ValueError("Unknown action.")


def make_handler(panel, page):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _host_ok(self):
            return self.headers.get("Host", "").split(":")[0] in ("localhost", "127.0.0.1")

        def _send(self, code, body, ctype="application/json"):
            body = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden"})
            if self.path == "/":
                self._send(200, page, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._send(200, panel.snapshot())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Panel") != "1":
                return self._send(403, {"error": "forbidden"})
            if self.path != "/api/action":
                return self._send(404, {"error": "not found"})
            try:
                n = min(int(self.headers.get("Content-Length", 0)), 8192)
                panel.action(json.loads(self.rfile.read(n) or b"{}"))
                self._send(200, {"ok": True})
            except (ValueError, RuntimeError) as exc:
                self._send(400, {"error": str(exc)})

    return Handler


def find_osken(explicit):
    if explicit:
        return explicit
    home = os.path.expanduser("~" + os.environ.get("SUDO_USER", ""))
    for cand in (os.path.join(ROOT, ".venv", "bin", "osken-manager"),
                 os.path.join(home, ".local", "bin", "osken-manager")):
        if os.path.exists(cand):
            return cand
    return shutil.which("osken-manager")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--sim", action="store_true", help="apps only on loopback, no Mininet/controller")
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--osken", help="path to osken-manager")
    args = ap.parse_args()
    if not args.sim and os.geteuid() != 0:
        sys.exit("Full mode needs root: sudo python3 scripts/control_panel.py   (or use --sim)")
    page = open(os.path.join(ROOT, "scripts", "panel.html"), "rb").read()
    panel = Panel(args.sim, find_osken(args.osken))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.http_port), make_handler(panel, page))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    print(f"Control panel: http://localhost:{args.http_port}   ({'SIM' if args.sim else 'full'} mode)")
    if not args.sim:
        print(f"osken-manager: {panel.osken or 'NOT FOUND (use --osken)'}")
    try:
        panel.run_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        panel.shutdown()
        httpd.shutdown()


if __name__ == "__main__":
    main()
