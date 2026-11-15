import socket
import threading
from config import (
    SERVER_HOST, SERVER_PORT, BUFFER_SIZE,
    ACK_TIMEOUT, EMERGENCY_PORT, NORMAL_PORT
)

server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server.bind((SERVER_HOST, SERVER_PORT))

clients = {}
notifications = {}
next_notification_id = 1
running = True
lock = threading.Lock()


def show_delivery_status(message_id):
    with lock:
        if message_id not in notifications:
            return

        notification = notifications[message_id]
        acknowledged = notification["acks"]
        expected = set(clients.values())

        print("\nDelivery status")
        print(f"Notification ID: {message_id}")
        print(f"Delivered: {len(acknowledged)}/{len(expected)}")

        for name in sorted(expected):
            status = "RECEIVED" if name in acknowledged else "PENDING"
            print(f"  {name}: {status}")


def receive_messages():
    global running

    while running:
        try:
            data, address = server.recvfrom(BUFFER_SIZE)
        except OSError:
            break

        parts = data.decode(errors="replace").split("|")
        command = parts[0]

        if command == "REGISTER" and len(parts) == 2:
            name = parts[1].strip()

            if not name:
                continue

            with lock:
                clients[address] = name

            print(f"\nClient registered: {name} {address}")
            server.sendto(b"REGISTERED", address)

        elif command == "ACK" and len(parts) == 3:
            name = parts[1]

            try:
                message_id = int(parts[2])
            except ValueError:
                continue

            with lock:
                if message_id in notifications:
                    notifications[message_id]["acks"].add(name)

            print(f"\nACK received from {name} for notification {message_id}")
            show_delivery_status(message_id)

        elif command == "UNREGISTER" and len(parts) == 2:
            name = parts[1]

            with lock:
                for address, registered_name in list(clients.items()):
                    if registered_name == name:
                        del clients[address]
                        break

            print(f"\nClient disconnected: {name}")


def send_notification():
    global next_notification_id

    with lock:
        client_addresses = list(clients.keys())

    if not client_addresses:
        print("\nNo clients are connected.")
        return

    print("\n1. Normal Notification")
    print("2. Emergency Notification")

    choice = input("Choose notification type: ").strip()

    if choice == "1":
        notification_type = "NORMAL"
        priority = "LOW"
        destination_port = NORMAL_PORT

    elif choice == "2":
        notification_type = "EMERGENCY"
        priority = "HIGH"
        destination_port = EMERGENCY_PORT

    else:
        print("Invalid choice.")
        return

    message = input("Enter notification: ").strip()

    if not message:
        print("Notification cannot be empty.")
        return

    with lock:
        message_id = next_notification_id
        next_notification_id += 1

        notifications[message_id] = {
            "type": notification_type,
            "priority": priority,
            "message": message,
            "acks": set()
        }

    packet = f"{notification_type}|{message_id}|{message}"

    print("\n------------------------------")
    print(f"ID       : {message_id}")
    print(f"Type     : {notification_type}")
    print(f"Priority : {priority}")
    print(f"Message  : {message}")
    print(f"UDP Port : {destination_port}")
    print("------------------------------")

    for address in client_addresses:
        try:
            destination = (address[0], destination_port)
            server.sendto(packet.encode(), destination)
        except OSError:
            pass

    print(f"Sent to {len(client_addresses)} client(s).")


def show_clients():
    with lock:
        current_clients = list(clients.items())

    print("\n========== CONNECTED CLIENTS ==========")

    if not current_clients:
        print("No clients connected.")
        return

    for address, name in current_clients:
        print(f"{name} -> {address}")


def show_history():
    with lock:
        history = list(notifications.items())
        current_clients = set(clients.values())

    print("\n========== NOTIFICATION HISTORY ==========")

    if not history:
        print("No notifications sent yet.")
        return

    for message_id, info in history:
        print(f"\nID       : {message_id}")
        print(f"Type     : {info['type']}")
        print(f"Priority : {info['priority']}")
        print(f"Message  : {info['message']}")
        print(f"ACKs     : {len(info['acks'])}/{len(current_clients)}")


def shutdown():
    global running
    running = False

    with lock:
        addresses = list(clients.keys())

    for address in addresses:
        for port in (EMERGENCY_PORT, NORMAL_PORT):
            try:
                server.sendto(
                    b"SERVER_SHUTDOWN",
                    (address[0], port)
                )
            except OSError:
                pass

    server.close()
    print("\nServer stopped.")


def menu():
    while running:
        print("\n========================================")
        print(" Emergency Notification Server")
        print("========================================")
        print("1. Send notification")
        print("2. Show connected clients")
        print("3. Show notification history")
        print("4. Exit")

        choice = input("Choose option: ").strip()

        if choice == "1":
            send_notification()
        elif choice == "2":
            show_clients()
        elif choice == "3":
            show_history()
        elif choice == "4":
            shutdown()
        else:
            print("Invalid choice.")


receiver_thread = threading.Thread(
    target=receive_messages,
    daemon=True
)
receiver_thread.start()

try:
    menu()
except KeyboardInterrupt:
    shutdown()
