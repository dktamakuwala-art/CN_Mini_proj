import socket
import threading
import time
from typing import Any

from src.config import (
    SERVER_HOST, SERVER_PORT, BUFFER_SIZE, ACK_TIMEOUT, MAX_RETRIES,
    EMERGENCY_PORT, NORMAL_PORT, BACKGROUND_PORT, MAX_CLIENTS,
)


class NotificationServer:
    def __init__(self, host=SERVER_HOST, udp_port=SERVER_PORT,
                 ack_timeout=ACK_TIMEOUT, retry_limit=MAX_RETRIES):
        if ack_timeout <= 0:
            raise ValueError("ack_timeout must be positive")
        if retry_limit < 0:
            raise ValueError("retry_limit cannot be negative")
        self.host = host
        self.udp_port = udp_port
        self.ack_timeout = float(ack_timeout)
        self.retry_limit = int(retry_limit)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(0.5)
        self.socket.bind((self.host, self.udp_port))
        self.clients: dict[str, tuple[str, int]] = {}
        self.client_details: dict[str, dict[str, Any]] = {}
        self.notifications: dict[int, dict[str, Any]] = {}
        self.next_notification_id = 1
        self.running = False
        self.lock = threading.RLock()
        self.retry_thread = threading.Thread(target=self._retry_loop, daemon=True)
        self.receiver_thread = threading.Thread(target=self._receive_loop, daemon=True)

    def start(self):
        if self.running:
            return
        self.running = True
        self.receiver_thread.start()
        self.retry_thread.start()

    def stop(self):
        if not self.running and self.socket.fileno() == -1:
            return
        self.running = False
        with self.lock:
            clients = list(self.client_details.items())
        for name, details in clients:
            address = details["address"]
            for port in details["ports"].values():
                try:
                    self.socket.sendto(b"SERVER_SHUTDOWN", (address[0], port))
                except OSError:
                    pass
        try:
            self.socket.close()
        except OSError:
            pass
        for thread in (self.receiver_thread, self.retry_thread):
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.0)

    def register_client(self, name: str, address: tuple[str, int],
                        emergency_port: int = EMERGENCY_PORT,
                        normal_port: int = NORMAL_PORT):
        name = name.strip()
        if not name:
            raise ValueError("Client name cannot be empty.")
        for port in (emergency_port, normal_port):
            if not 1 <= int(port) <= 65535:
                raise ValueError("Client listening ports must be between 1 and 65535.")
        with self.lock:
            if name not in self.clients and len(self.clients) >= MAX_CLIENTS:
                raise RuntimeError("Maximum number of clients reached.")
            self.clients[name] = address
            self.client_details[name] = {
                "address": address,
                "ports": {"EMERGENCY": int(emergency_port), "NORMAL": int(normal_port)},
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
            if normalized in ports:
                return ports[normalized]
        defaults = {"EMERGENCY": EMERGENCY_PORT, "NORMAL": NORMAL_PORT,
                    "BACKGROUND": BACKGROUND_PORT}
        if normalized not in defaults:
            raise ValueError(f"Unsupported notification type: {notification_type}")
        return defaults[normalized]

    @staticmethod
    def _build_packet(notification_type: str, message_id: int, message: str) -> bytes:
        return f"{notification_type}|{message_id}|{message}".encode("utf-8")

    def _broadcast(self, message_id: int, notification_type: str, message: str):
        with self.lock:
            recipients = [
                (name, address, self._notification_type_to_port(notification_type, name))
                for name, address in self.clients.items()
                if name in self.notifications[message_id]["expected_clients"]
            ]
        payload = self._build_packet(notification_type, message_id, message)
        for _, address, port in recipients:
            try:
                self.socket.sendto(payload, (address[0], port))
            except OSError:
                continue

    def send_notification(self, notification_type: str, message: str):
        notification_type = notification_type.strip().upper()
        if notification_type not in {"NORMAL", "EMERGENCY"}:
            raise ValueError("Only NORMAL and EMERGENCY notifications are valid.")
        if not message or not message.strip():
            raise ValueError("Notification message cannot be empty.")
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
                "expected_clients": set(self.clients),
                "sent_at": time.monotonic(),
            }
        self._broadcast(message_id, notification_type, message)
        return message_id

    def process_ack(self, client_name: str, message_id: int, address=None):
        with self.lock:
            notification = self.notifications.get(message_id)
            registered_address = self.clients.get(client_name)
            if (notification is None or client_name not in notification["expected_clients"]
                    or registered_address is None
                    or (address is not None and registered_address != address)):
                return False
            notification["acks"].add(client_name)
            if notification["acks"] >= notification["expected_clients"]:
                notification["status"] = "acknowledged"
            return True

    def get_delivery_status(self, message_id: int):
        with self.lock:
            notification = self.notifications.get(message_id)
            if notification is None:
                return {"message_id": message_id, "status": "not_found"}
            expected = notification["expected_clients"]
            acked = notification["acks"]
            status = notification["status"]
            if status != "failed" and acked >= expected:
                status = "acknowledged"
            return {
                "message_id": message_id,
                "type": notification["type"],
                "priority": notification["priority"],
                "status": status,
                "acknowledged": len(acked),
                "expected": len(expected),
                "missing": sorted(expected - acked),
                "retries": notification["retries"],
                "acks": sorted(acked),
            }

    def retry_pending_notifications(self):
        now = time.monotonic()
        with self.lock:
            due = []
            for message_id, notification in self.notifications.items():
                if notification["status"] in {"acknowledged", "failed"}:
                    continue
                if now - notification["sent_at"] < self.ack_timeout:
                    continue
                if notification["retries"] >= self.retry_limit:
                    notification["status"] = "failed"
                    continue
                notification["retries"] += 1
                notification["sent_at"] = now
                due.append((message_id, notification["type"], notification["message"]))
        for message_id, notification_type, message in due:
            self._broadcast(message_id, notification_type, message)

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
                emergency_port, normal_port = EMERGENCY_PORT, NORMAL_PORT
                if len(parts) >= 4:
                    try:
                        emergency_port, normal_port = int(parts[2]), int(parts[3])
                    except ValueError:
                        continue
                try:
                    self.register_client(name, address, emergency_port, normal_port)
                except (ValueError, RuntimeError):
                    continue
                try:
                    self.socket.sendto(b"REGISTERED", address)
                except OSError:
                    pass
                print(f"Client registered: {name} -> {address}")
            elif command == "ACK" and len(parts) == 3:
                name = parts[1].strip()
                try:
                    message_id = int(parts[2])
                except ValueError:
                    continue
                if self.process_ack(name, message_id, address):
                    print(f"ACK received from {name} for notification {message_id}")
            elif command == "UNREGISTER" and len(parts) >= 2:
                name = parts[1].strip()
                self.unregister_client(name)
                print(f"Client disconnected: {name}")

    def show_delivery_summary(self, message_id: int):
        status = self.get_delivery_status(message_id)
        print(f"Notification {message_id}: {status['status']} - {status['acknowledged']}/{status['expected']} ACKs")
        if status.get("missing"):
            print(f"Missing: {status['missing']}")

    def show_history(self):
        with self.lock:
            ids = sorted(self.notifications)
        if not ids:
            print("No notifications sent yet.")
            return
        print("Notification history:")
        for message_id in ids:
            status = self.get_delivery_status(message_id)
            print(f"ID={message_id} TYPE={status['type']} STATUS={status['status']} "
                  f"ACKS={status['acknowledged']}/{status['expected']} RETRIES={status['retries']}")

    def print_client_table(self):
        with self.lock:
            clients = list(self.clients.items())
            details = dict(self.client_details)
        if not clients:
            print("No connected clients.")
            return
        print("Connected clients:")
        for name, address in sorted(clients):
            ports = details[name]["ports"]
            print(f" - {name} -> {address[0]}:{address[1]} "
                  f"(EMERGENCY={ports['EMERGENCY']}, NORMAL={ports['NORMAL']})")

    def run_menu(self):
        while self.running:
            print("\n1. Send normal notification\n2. Send emergency notification"
                  "\n3. Show connected clients\n4. Show notification history\n5. Exit")
            choice = input("Choose option: ").strip()
            if choice in {"1", "2"}:
                message = input("Enter notification: ").strip()
                if message:
                    kind = "NORMAL" if choice == "1" else "EMERGENCY"
                    try:
                        message_id = self.send_notification(kind, message)
                        print(f"Sent {kind} notification {message_id}.")
                    except RuntimeError as exc:
                        print(exc)
            elif choice == "3":
                self.print_client_table()
            elif choice == "4":
                self.show_history()
            elif choice == "5":
                break
            else:
                print("Invalid option.")
        self.stop()


if __name__ == "__main__":
    server = NotificationServer()
    try:
        server.start()
        server.run_menu()
    except KeyboardInterrupt:
        print("\nServer interrupted.")
    finally:
        server.stop()
