#!/usr/bin/env python3
"""Server process for the control panel. Reads 'SEND|TYPE|message' on stdin, prints 'STATE {json}' lines."""
import argparse
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.server import NotificationServer
from src.web_ui import build_state

out_lock = threading.Lock()


def emit(prefix, obj):
    with out_lock:
        sys.stdout.write(f"{prefix} {json.dumps(obj)}\n")
        sys.stdout.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--udp-port", type=int, default=5000)
    args = ap.parse_args()
    server = NotificationServer(udp_port=args.udp_port)
    server.start()
    log, stop = {}, threading.Event()

    def reader():
        for line in sys.stdin:
            parts = line.rstrip("\n").split("|", 2)
            if parts[0] == "SEND" and len(parts) == 3:
                try:
                    mid = server.send_notification(parts[1], parts[2])
                    log[mid] = time.strftime("%H:%M:%S")
                    emit("MSG", {"ok": True, "id": mid})
                except (ValueError, RuntimeError) as exc:
                    emit("MSG", {"ok": False, "error": str(exc)})
        stop.set()

    threading.Thread(target=reader, daemon=True).start()
    try:
        while not stop.wait(0.5):
            emit("STATE", build_state(server, log))
    finally:
        server.stop()


if __name__ == "__main__":
    main()
