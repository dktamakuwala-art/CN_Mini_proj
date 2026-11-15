import socket
import time

import pytest

from src.server import NotificationServer


def free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def server():
    instance = NotificationServer(
        host="127.0.0.1",
        udp_port=free_udp_port(),
        ack_timeout=0.05,
        retry_limit=1,
    )
    yield instance
    instance.stop()


def test_register_send_and_ack_tracking(server):
    client_address = ("127.0.0.1", 40001)
    server.register_client("Client1", client_address)
    message_id = server.send_notification("NORMAL", "hello")

    assert message_id == 1
    status = server.get_delivery_status(message_id)
    assert status["status"] == "pending"
    assert status["expected"] == 1

    assert server.process_ack("Client1", message_id, client_address)
    status = server.get_delivery_status(message_id)
    assert status["acknowledged"] == 1
    assert status["status"] == "acknowledged"


def test_ack_from_unregistered_or_wrong_address_is_rejected(server):
    client_address = ("127.0.0.1", 40002)
    server.register_client("Client1", client_address)
    message_id = server.send_notification("EMERGENCY", "fire alarm")

    assert not server.process_ack("Imposter", message_id, client_address)
    assert not server.process_ack("Client1", message_id, ("127.0.0.1", 49999))
    assert server.get_delivery_status(message_id)["acknowledged"] == 0


def test_missing_ack_causes_retry_then_failure(server):
    server.register_client("Client2", ("127.0.0.1", 40003))
    message_id = server.send_notification("EMERGENCY", "fire alarm")

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        server.retry_pending_notifications()
        if server.get_delivery_status(message_id)["status"] == "failed":
            break
        time.sleep(0.02)

    status = server.get_delivery_status(message_id)
    assert status["status"] == "failed"
    assert status["retries"] == 1


def test_send_without_clients_fails(server):
    with pytest.raises(RuntimeError, match="No registered clients"):
        server.send_notification("NORMAL", "hello")
