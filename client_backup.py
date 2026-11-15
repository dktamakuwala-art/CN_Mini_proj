import socket
import sys
from config import SERVER_IP, SERVER_PORT, BUFFER_SIZE

client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client.settimeout(5)

client_name = input("Enter client name: ").strip()

if not client_name:
    print("Client name cannot be empty.")
    client.close()
    sys.exit(1)

server_address = (SERVER_IP, SERVER_PORT)

register_message = f"REGISTER|{client_name}"

client.sendto(register_message.encode(), server_address)

try:
    data, server_address = client.recvfrom(BUFFER_SIZE)
except socket.timeout:
    print("Server did not respond to registration.")
    client.close()
    sys.exit(1)

if data.decode() != "REGISTERED":
    print("Registration failed.")
    client.close()
    sys.exit(1)

print(f"\nRegistered as: {client_name}")
print("Waiting for notifications...")


try:
    while True:
        client.settimeout(None)
        data, server_address = client.recvfrom(BUFFER_SIZE)

        message = data.decode(errors="replace")

        if message == "SERVER_SHUTDOWN":
            print("\nServer is shutting down.")
            break

        parts = message.split("|", 2)

        if len(parts) != 3:
            continue

        notification_type, message_id, notification = parts

        if notification_type == "EMERGENCY":
            priority = "HIGH"
        else:
            priority = "LOW"

        print("\n========================================")

        if notification_type == "EMERGENCY":
            print("           !!! EMERGENCY !!!")
        else:
            print("            NORMAL NOTICE")

        print("========================================")
        print(f"Type     : {notification_type}")
        print(f"ID       : {message_id}")
        print(f"Priority : {priority}")
        print(f"Message  : {notification}")
        print("========================================")

        ack = f"ACK|{client_name}|{message_id}"
        client.sendto(ack.encode(), server_address)

except KeyboardInterrupt:
    print("\nDisconnecting...")

finally:
    try:
        unregister = f"UNREGISTER|{client_name}"
        client.sendto(unregister.encode(), server_address)
    except OSError:
        pass

    client.close()
