import socket
import threading
from config import SERVER_IP, SERVER_PORT, BUFFER_SIZE

server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server.bind((SERVER_IP, SERVER_PORT))

clients = {}
notifications = {}
notification_id = 1

running = True


def receive_messages():

    global running

    while running:

        try:
            data, address = server.recvfrom(BUFFER_SIZE)

            message = data.decode()

            if message.startswith("REGISTER|"):

                parts = message.split("|", 1)

                if len(parts) != 2:
                    continue

                client_name = parts[1]

                clients[address] = client_name

                print(
                    f"\nClient registered: "
                    f"{client_name} {address}"
                )

                server.sendto(
                    b"REGISTERED",
                    address
                )

            elif message.startswith("ACK|"):

                parts = message.split("|")

                if len(parts) != 3:
                    continue

                client_name = parts[1]
                message_id = int(parts[2])

                if message_id in notifications:

                    notifications[message_id]["acks"].add(
                        client_name
                    )

                    print(
                        f"\nACK received from "
                        f"{client_name} "
                        f"for notification "
                        f"{message_id}"
                    )

                    show_delivery_status(message_id)

            elif message.startswith("UNREGISTER|"):

                parts = message.split("|", 1)

                if len(parts) != 2:
                    continue

                client_name = parts[1]

                address_to_remove = None

                for client_address, name in clients.items():

                    if name == client_name:
                        address_to_remove = client_address
                        break

                if address_to_remove:
                    del clients[address_to_remove]

                    print(
                        f"\nClient disconnected: "
                        f"{client_name}"
                    )

        except OSError:

            break


def show_delivery_status(message_id):

    notification = notifications[message_id]

    acknowledged = notification["acks"]

    print(
        f"Delivery status: "
        f"{len(acknowledged)}/"
        f"{len(clients)} clients"
    )

    for client_name in clients.values():

        if client_name in acknowledged:
            print(f"  {client_name} [RECEIVED]")
        else:
            print(f"  {client_name} [PENDING]")


def send_notification():

    global notification_id

    if not clients:

        print("\nNo clients connected.")

        return

    print("\n==============================")
    print("1. Normal Notification")
    print("2. Emergency Notification")
    print("==============================")

    choice = input("Choose notification type: ")

    if choice == "1":

        notification_type = "NORMAL"
        priority = "LOW"

    elif choice == "2":

        notification_type = "EMERGENCY"
        priority = "HIGH"

    else:

        print("Invalid choice.")

        return

    notification = input(
        "Enter notification: "
    )

    current_id = notification_id

    packet = (
        f"{notification_type}|"
        f"{current_id}|"
        f"{notification}"
    )

    notifications[current_id] = {

        "type": notification_type,

        "priority": priority,

        "message": notification,

        "acks": set()
    }

    print("\n==============================")
    print("Sending notification")
    print("==============================")

    print(f"ID       : {current_id}")
    print(f"Type     : {notification_type}")
    print(f"Priority : {priority}")
    print(f"Message  : {notification}")

    for client_address in clients:

        server.sendto(
            packet.encode(),
            client_address
        )

    print(
        f"\nSent to {len(clients)} client(s)"
    )

    notification_id += 1


def show_history():

    if not notifications:

        print("\nNo notifications sent yet.")

        return

    print("\n========== HISTORY ==========")

    for message_id, data in notifications.items():

        print(
            f"\nID       : {message_id}"
        )

        print(
            f"Type     : {data['type']}"
        )

        print(
            f"Priority : {data['priority']}"
        )

        print(
            f"Message  : {data['message']}"
        )

        print(
            f"ACKs     : "
            f"{len(data['acks'])}/"
            f"{len(clients)}"
        )


def show_clients():

    print("\n========== CLIENTS ==========")

    if not clients:

        print("No clients connected.")

        return

    for address, name in clients.items():

        print(
            f"{name} → {address}"
        )


def server_menu():

    while running:

        print("\n")
        print("==============================")
        print(" Emergency Notification System")
        print("==============================")
        print("1. Send notification")
        print("2. Show connected clients")
        print("3. Show notification history")
        print("4. Exit")

        choice = input(
            "Choose option: "
        )

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


def shutdown():

    global running

    running = False

    for address in clients:

        try:

            server.sendto(
                b"SERVER_SHUTDOWN",
                address
            )

        except OSError:

            passr

    server.close()

    print("\nServer stopped.")


receiver_thread = threading.Thread(
    target=receive_messages,
    daemon=True
)

receiver_thread.start()

try:

    server_menu()

except KeyboardInterrupt:

    shutdown()
