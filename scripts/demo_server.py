#!/usr/bin/env python3
"""Non-interactive server for the Mininet demo: waits for clients, sends 2 notifications, prints results."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.server import NotificationServer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=3)
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--wait", type=float, default=15.0)
    args = ap.parse_args()

    server = NotificationServer(udp_port=args.port, ack_timeout=1.0, retry_limit=2)
    server.start()
    try:
        deadline = time.monotonic() + args.wait
        while len(server.clients) < args.clients and time.monotonic() < deadline:
            time.sleep(0.2)
        print(f"[server] {len(server.clients)}/{args.clients} clients registered", flush=True)
        ids = []
        for kind, text in (("NORMAL", "Routine maintenance at 18:00"),
                           ("EMERGENCY", "Fire alarm - evacuate building")):
            ids.append(server.send_notification(kind, text))
            time.sleep(1.0)
        time.sleep(4.0)  # allow ACKs / retries
        for mid in ids:
            server.show_delivery_summary(mid)
        ok = all(server.get_delivery_status(m)["status"] == "acknowledged" for m in ids)
        print("[server] RESULT:", "PASS" if ok else "FAIL", flush=True)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
