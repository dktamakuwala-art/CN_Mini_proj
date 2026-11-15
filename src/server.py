import socket
import threading
import time
from typing import Dict, Tuple, Any

from src.config import (
    SERVER_HOST,
    SERVER_PORT,
    BUFFER_SIZE,
    ACK_TIMEOUT,
    MAX_RETRIES,
    EMERGENCY_PORT,
    NORMAL_PORT,
    BACKGROUND_PORT,
)


class NotificationServer:
    def __init__(self, host=SERVER_HOST, udp_port=SERVER_PORT,
                 ack_timeout=ACK_TIMEOUT, retry_limit=MAX_RETRIES):
        self.host = host
        self.udp_port = udp_port
        self.ack_timeout = float(ack_timeout)
        self.retry_limit = int(retry_limit)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(0.5)
        self.socket.bind((self.host, self.udp_port))

        self.clients: Dict[str, Tuple[str, int]] = {}
        self.client_details: Dict[str, Dict[str, Any]] = {}
        self.notifications: Dict[int, Dict[str, Any]] = {}
        self.next_notification_id = 1
        self.running = True
        self.lock = threading.RLock()
        self.retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self.receiver_thread = threading.Thread(target=self._receive_loop, daemon=True)

    def start(self):
        self.receiver_thread.start()
        self.retry_thread.start()

    def stop(self):
        self.running = False
        self.socket.close()

    def register_client(self, name: str, address: Tuple[str, int], emergency_port: int = EMERGENCY_PORT,
                       normal_port: int = NORMAL_PORT):
        if not name:
            raise ValueError("Client name cannot be empty.")
        with self.lock:
            self.clients[name] = address
            self.client_details[name] = {
                "address": address,
                "ports": {
                    "EMERGENCY": emergency_port,
                    "NORMAL": normal_port,
                },
            }

    def unregister_client(self, name: str):
        with self.lock:
            self.clients.pop(name, None)
            self.client_details.pop(name, None)

    def _notification_type_to_port(self, notification_type: str, client_name: str) -> int:
        normalized = notification_type.upper()
        with self.lock:
            details = self.client_details.get(client_name)
            ports = details.get("ports", {}) if details else {}
            if details and normalized in ports:
                return ports[normalized]
        if normalized == "EMERGENCY":
            return EMERGENCY_PORT
        if normalized == "NORMAL":
            return NORMAL_PORT
        if normalized == "BACKGROUND":
            return BACKGROUND_PORT
        raise ValueError(f"Unsupported notification type: {notification_type}")

    def _build_packet(self, notification_type: str, message_id: int, message: str) -> bytes:
        return f"{notification_type}|{message_id}|{message}".encode("utf-8")

    def _broadcast(self, message_id: int, notification_type: str, message: str):
        with self.lock:
            if not self.clients:
                return
            for client_name, address in list(self.clients.items()):
                destination_port = self._notification_type_to_port(notification_type, client_name)
                try:
                    self.socket.sendto(
                        self._build_packet(notification_type, message_id, message),
                        (address[0], destination_port),
                    )
                except OSError:
                    continue

    def send_notification(self, notification_type: str, message: str):
        notification_type = notification_type.upper()
        if notification_type not in {"NORMAL", "EMERGENCY"}:
            raise ValueError("Only NORMAL and EMERGENCY notifications are valid.")

        with self.lock:
            if not self.clients:
                raise RuntimeError("No registered clients available.")

            message_id = self.next_notification_id
            self.next_notification_id += 1

            self.notifications[message_id] = {
                "type": notification_type,
                "priority": "HIGH" if notification_type == "EMERGENCY" else "LOW",
                "message": message,
                "acks": set(),
                "retries": 0,
                "status": "pending",
                "expected_clients": set(self.clients.keys()),
                "sent_at": time.monotonic(),
            }

        self._broadcast(message_id, notification_type, message)
        return message_id

    def process_ack(self, client_name: str, message_id: int):
        with self.lock:
            notification = self.notifications.get(message_id)
            if notification is None:
                return False

            notification["acks"].add(client_name)
            if len(notification["acks"]) >= len(notification["expected_clients"]):
                notification["status"] = "acknowledged"
            return True

    def get_delivery_status(self, message_id: int):
        with self.lock:
            notification = self.notifications.get(message_id)
            if notification is None:
                return {"message_id": message_id, "status": "not_found"}

            expected = sorted(notification["expected_clients"])
            acked = sorted(notification["acks"])
            missing = sorted(set(expected) - set(acked))
            if notification["status"] == "failed":
                status = "failed"
            elif len(acked) >= len(expected):
                status = "acknowledged"
            else:
                status = "pending"

            return {
                "message_id": message_id,
                "type": notification["type"],
                "priority": notification["priority"],
                "status": status,
                "acknowledged": len(acked),
                "expected": len(expected),
                "missing": missing,
                "retries": notification["retries"],
                "acks": acked,
            }

    def retry_pending_notifications(self):
        now = time.monotonic()
        with self.lock:
            pending = list(self.notifications.items())
            for message_id, notification in pending:
                if notification["status"] in {"acknowledged", "failed"}:
                    continue

                if now - notification["sent_at"] < self.ack_timeout:
                    continue

                if notification["retries"] >= self.retry_limit:
                    notification["status"] = "failed"
                    continue

                notification["retries"] += 1
                notification["sent_at"] = now
                self._broadcast(message_id, notification["type"], notification["message"])

    def _retry_loop(self):
        while self.running:
            self.retry_pending_notifications()
            time.sleep(0.2)

    def _receive_loop(self):
        while self.running:
            try:
                data, address = self.socket.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break

            message = data.decode("utf-8", errors="replace").strip()
            if not message:
                continue

            parts = message.split("|")
            command = parts[0].upper()

            if command == "REGISTER" and len(parts) >= 2:
                name = parts[1].strip()
                if name:
                    emergency_port = EMERGENCY_PORT
                    normal_port = NORMAL_PORT
                    if len(parts) >= 4:
                        try:
                            emergency_port = int(parts[2])
                            normal_port = int(parts[3])
                        except ValueError:
                            emergency_port = EMERGENCY_PORT
                            normal_port = NORMAL_PORT
                    self.register_client(name, address, emergency_port, normal_port)
                    try:
                        self.socket.sendto(b"REGISTERED", address)
                    except OSError:
                        pass
                    print(f"Client registered: {name} -> {address} (ports: emergency={emergency_port}, normal={normal_port})")

            elif command == "ACK" and len(parts) >= 3:
                name = parts[1].strip()
                try:
                    message_id = int(parts[2])
                except ValueError:
                    continue
                self.process_ack(name, message_id)
                print(f"ACK received from {name} for notification {message_id}")

            elif command == "UNREGISTER" and len(parts) >= 2:
                name = parts[1].strip()
                if name:
                    self.unregister_client(name)
                    print(f"Client disconnected: {name}")

    def show_delivery_summary(self, message_id: int):
        status = self.get_delivery_status(message_id)
        print(f"Notification {message_id}: {status['status']} - {status['acknowledged']}/{status['expected']} ACKs")
        if status.get("missing"):
            print(f"Missing: {status['missing']}")

    def show_history(self):
        with self.lock:
            if not self.notifications:
                print("No notifications sent yet.")
                return
            print("Notification history:")
            for message_id, notification in sorted(self.notifications.items()):
                status = self.get_delivery_status(message_id)
                print(
                    f"ID={message_id} TYPE={notification['type']} "
                    f"STATUS={status['status']} ACKS={status['acknowledged']}/{status['expected']} "
                    f"RETRIES={status['retries']}"
                )

    def print_client_table(self):
        with self.lock:
            if not self.clients:
                print("No connected clients.")
                return
            print("Connected clients:")
            for name, address in sorted(self.clients.items()):
                details = self.client_details.get(name, {})
                ports = details.get("ports", {})
                print(f" - {name} -> {address[0]}:{address[1]} (EMERGENCY={ports.get('EMERGENCY', EMERGENCY_PORT)}, NORMAL={ports.get('NORMAL', NORMAL_PORT)})")

    def run_menu(self):
        while self.running:
            print("\n1. Send normal notification")
            print("2. Send emergency notification")
            print("3. Show connected clients")
            print("4. Show notification history")
            print("5. Exit")
            choice = input("Choose option: ").strip()

            if choice == "1":
                message = input("Enter normal notification: ").strip()
                if message:
                    msg_id = self.send_notification("NORMAL", message)
                    print(f"Sent NORMAL notification {msg_id}.")
            elif choice == "2":
                message = input("Enter emergency notification: ").strip()
                if message:
                    msg_id = self.send_notification("EMERGENCY", message)
                    print(f"Sent EMERGENCY notification {msg_id}.")
            elif choice == "3":
                self.print_client_table()
            elif choice == "4":
                self.show_history()
            elif choice == "5":
                self.running = False
                print("Server shutting down...")
                break
            else:
                print("Invalid option.")

        self.stop()


if __name__ == "__main__":
    server = NotificationServer()
    server.start()
    try:
        server.run_menu()
    except KeyboardInterrupt:
        server.running = False
        server.stop()
        print("Server interrupted.")
