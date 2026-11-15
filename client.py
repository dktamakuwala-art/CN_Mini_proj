import socket
import sys
from config import SERVER_IP, SERVER_PORT, BUFFER_SIZE

client = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)

client_name = input(
    "Enter client name: "
)

register_message = (
    f"REGISTER|{client_name}"
)

client.sendto(
    register_message.encode(),
    (SERVER_IP, SERVER_PORT)
)

data, server_address = client.recvfrom(
    BUFFER_SIZE
)

response = data.decode()

if response != "REGISTERED":

    print("Registration failed.")

    client.close()

    sys.exit()

print(
    f"\nRegistered as {client_name}"
)

print(
    "Waiting for notifications..."
)

try:

    while True:

        data, server_address = client.recvfrom(
            BUFFER_SIZE
        )

        message = data.decode()

        if message == "SERVER_SHUTDOWN":

            print(
                "\nServer is shutting down."
            )

            break

        parts = message.split("|", 2)

        if len(parts) != 3:

            continue

        notification_type = parts[0]

        message_id = parts[1]

        notification = parts[2]

        if notification_type == "EMERGENCY":

            priority = "HIGH"

        else:

            priority = "LOW"

        print("\n")
        print("==============================")

        if notification_type == "EMERGENCY":

            print(
                "       !!! EMERGENCY !!!"
            )

        else:

            print(
                "       NORMAL NOTICE"
            )

        print("==============================")

        print(
            f"Type     : {notification_type}"
        )

        print(
            f"ID       : {message_id}"
        )

        print(
            f"Priority : {priority}"
        )

        print(
            f"Message  : {notification}"
        )

        print("==============================")

        ack = (
            f"ACK|"
            f"{client_name}|"
            f"{message_id}"
        )

        client.sendto(
            ack.encode(),
            server_address
        )

except KeyboardInterrupt:

    print(
        "\nDisconnecting..."
    )

finally:

    unregister_message = (
        f"UNREGISTER|{client_name}"
    )

    try:

        client.sendto(
            unregister_message.encode(),
            (SERVER_IP, SERVER_PORT)
        )

    except OSError:

        pass

    client.close()
