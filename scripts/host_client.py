#!/usr/bin/env python3
"""Client process for the control panel. Prints 'EVT {json}' lines instead of terminal banners."""
import json
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.client import EmergencyClient, _parse_args

out_lock = threading.Lock()


def emit(obj):
    with out_lock:
        sys.stdout.write(f"EVT {json.dumps(obj)}\n")
        sys.stdout.flush()


class PanelClient(EmergencyClient):
    def _process_notification(self, message: str):
        try:
            kind, raw_id, content = message.split("|", 2)
            mid = int(raw_id)
        except (ValueError, TypeError):
            return
        with self.lock:
            fresh = mid not in self.seen_messages
            self.seen_messages.add(mid)
        if fresh:
            emit({"kind": "notification", "type": kind, "id": mid,
                  "message": content, "time": time.strftime("%H:%M:%S")})
        self.send_ack(mid)


if __name__ == "__main__":
    args = _parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    client = PanelClient(args.name, args.server_ip, args.server_port,
                         args.emergency_port, args.normal_port)
    try:
        client.register()
        emit({"kind": "registered"})
        client.start()
        while client.running:
            time.sleep(0.3)
        emit({"kind": "server_shutdown"})
    except (KeyboardInterrupt, TimeoutError, RuntimeError) as exc:
        if not isinstance(exc, KeyboardInterrupt):
            emit({"kind": "error", "message": str(exc)})
    finally:
        client.stop()
