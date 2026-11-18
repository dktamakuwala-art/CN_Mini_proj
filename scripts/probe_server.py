#!/usr/bin/env python3
"""Runs on h1 inside Mininet: sends N EMERGENCY notifications, prints one JSON result line."""
import argparse, json, os, statistics, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.server import NotificationServer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=3)
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--delay", type=float, default=0.0,
                    help="Seconds to wait after clients register before sending probes")
    ap.add_argument("--sdn-signal", action="store_true")
    ap.add_argument("--timeout", type=float, default=6.0)
    a = ap.parse_args()

    srv = NotificationServer(udp_port=5000, ack_timeout=1.0, retry_limit=2,
                             sdn_signal=a.sdn_signal)
    srv.start()
    try:
        end = time.monotonic() + 15
        while len(srv.clients) < a.clients and time.monotonic() < end:
            time.sleep(0.2)
        registered = len(srv.clients)
        if a.delay > 0:
            time.sleep(a.delay)
        lat, retries, failed = [], 0, 0
        for i in range(a.n):
            t0 = time.perf_counter()
            mid = srv.send_notification("EMERGENCY", f"probe-{i}")
            while time.perf_counter() - t0 < a.timeout:
                st = srv.get_delivery_status(mid)
                if st["status"] == "acknowledged":
                    lat.append(time.perf_counter() - t0)
                    break
                if st["status"] == "failed":
                    break
                time.sleep(0.005)
            else:
                st = srv.get_delivery_status(mid)
            if st["status"] != "acknowledged":
                failed += 1
            retries += st.get("retries", 0)
            time.sleep(0.5)
        lat.sort()
        p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None
        print(json.dumps({
            "registered": registered, "sent": a.n, "failed": failed,
            "delivery_percent": round(100 * (a.n - failed) / a.n, 1),
            "avg_latency_s": round(statistics.mean(lat), 4) if lat else None,
            "p95_latency_s": round(p95, 4) if p95 is not None else None,
            "retransmissions": retries,
        }), flush=True)
    finally:
        srv.stop()


if __name__ == "__main__":
    main()
