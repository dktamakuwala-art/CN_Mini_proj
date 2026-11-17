import argparse
import socket
import threading
import time

from src.config import (
    SERVER_IP,
    SERVER_PORT,
    BUFFER_SIZE,
    EMERGENCY_PORT,
    NORMAL_PORT,
)


class EmergencyClient:
    def __init__(self, name: str, server_ip: str = SERVER_IP, server_port: int = SERVER_PORT,
                 emergency_port: int = EMERGENCY_PORT, normal_port: int = NORMAL_PORT):
        self.name = name
        self.server_ip = server_ip
        self.server_port = server_port
        self.server_address = (self.server_ip, self.server_port)
        self.running = True
        self.lock = threading.RLock()
        self.seen_messages = set()
        self.emergency_port = emergency_port
        self.normal_port = normal_port

        self.control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.control_socket.settimeout(2.0)

        self.receive_sockets = []
        for port in (self.emergency_port, self.normal_port):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0.5)
            sock.bind(("0.0.0.0", port))
            self.receive_sockets.append((port, sock))

    def register(self, attempts: int = 3):
        payload = f"REGISTER|{self.name}|{self.emergency_port}|{self.normal_port}".encode("utf-8")
        for _ in range(attempts):
            self.control_socket.sendto(payload, self.server_address)
            try:
                response, _ = self.control_socket.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            if response.decode("utf-8", errors="replace") != "REGISTERED":
                raise RuntimeError("Server rejected registration.")
            return
        raise TimeoutError("Server did not respond to registration.")

    def send_ack(self, message_id: int):
        payload = f"ACK|{self.name}|{message_id}".encode("utf-8")
        try:
            self.control_socket.sendto(payload, self.server_address)
        except OSError:
            pass

    def _process_notification(self, message: str):
        try:
            notification_type, message_id_raw, content = message.split("|", 2)
            message_id = int(message_id_raw)
        except (ValueError, TypeError):
            return

        with self.lock:
            if message_id in self.seen_messages:
                self.send_ack(message_id)
                return
            self.seen_messages.add(message_id)

        print("\n==============================")
        print(f" {notification_type} NOTIFICATION")
        print(f" ID: {message_id}")
        print(f" Message: {content}")
        print("==============================")

        self.send_ack(message_id)

    def _listen_for_messages(self, port: int, sock: socket.socket):
        while self.running:
            try:
                data, _ = sock.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break

            message = data.decode("utf-8", errors="replace").strip()
            if not message:
                continue

            if message == "SERVER_SHUTDOWN":
                print("Server is shutting down.")
                self.running = False
                break

            self._process_notification(message)

    def start(self):
        for port, sock in self.receive_sockets:
            worker = threading.Thread(target=self._listen_for_messages, args=(port, sock), daemon=True)
            worker.start()

    def stop(self):
        self.running = False
        try:
            self.control_socket.sendto(f"UNREGISTER|{self.name}".encode("utf-8"), self.server_address)
        except OSError:
            pass
        self.control_socket.close()
        for _, sock in self.receive_sockets:
            try:
                sock.close()
            except OSError:
                pass


def _parse_args():
    parser = argparse.ArgumentParser(description="Emergency notification client")
    parser.add_argument("--name", default="Client1", help="Subscriber name")
    parser.add_argument("--server-ip", default=SERVER_IP, help="Server IP address")
    parser.add_argument("--server-port", type=int, default=SERVER_PORT, help="Server control port")
    parser.add_argument("--emergency-port", type=int, default=EMERGENCY_PORT, help="Client listening port for emergency messages")
    parser.add_argument("--normal-port", type=int, default=NORMAL_PORT, help="Client listening port for normal messages")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    client = EmergencyClient(
        name=args.name,
        server_ip=args.server_ip,
        server_port=args.server_port,
        emergency_port=args.emergency_port,
        normal_port=args.normal_port,
    )
    try:
        client.register()
        print(f"Registered successfully as {client.name}.")
        client.start()
        while client.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nDisconnecting...")
    finally:
        client.stop()
        print("Disconnected.")
