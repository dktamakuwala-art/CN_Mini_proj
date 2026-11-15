import threading
import time

from src.server import NotificationServer


class DummySocket:
    def __init__(self):
        self.sent = []

    def sendto(self, payload, target):
        self.sent.append((payload, target))

    def close(self):
        pass


def test_register_and_ack_tracking():
    server = NotificationServer(udp_port=5000, ack_timeout=0.1, retry_limit=2)
    fake_addr = ("10.0.0.2", 4000)
    server.register_client("Client1", fake_addr)

    assert server.clients["Client1"] == fake_addr
    msg_id = server.send_notification("NORMAL", "hello")
    assert msg_id == 1

    status = server.get_delivery_status(msg_id)
    assert status["status"] in {"pending", "acknowledged", "failed"}
    assert "Client1" in server.notifications[msg_id]["expected_clients"]

    server.process_ack("Client1", msg_id)
    status = server.get_delivery_status(msg_id)
    assert status["acknowledged"] == 1
    assert status["status"] == "acknowledged"


def test_missing_ack_causes_retry_and_failure():
    server = NotificationServer(udp_port=5001, ack_timeout=0.05, retry_limit=1)
    fake_addr = ("10.0.0.3", 4001)
    server.register_client("Client2", fake_addr)

    msg_id = server.send_notification("EMERGENCY", "fire alarm")
    assert msg_id == 1

    deadline = time.time() + 1.0
    while time.time() < deadline:
        server.retry_pending_notifications()
        time.sleep(0.05)
        if server.get_delivery_status(msg_id)["status"] == "failed":
            break

    status = server.get_delivery_status(msg_id)
    assert status["status"] == "failed"
    assert status["retries"] >= 1
