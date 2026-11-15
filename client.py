import socket
import threading
from config import (
    SERVER_IP, SERVER_PORT, BUFFER_SIZE,
    EMERGENCY_PORT, NORMAL_PORT
)

server_address = (SERVER_IP, SERVER_PORT)
running = threading.Event()
running.set()

control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
control_socket.settimeout(5)

emergency_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
normal_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

emergency_socket.bind(("0.0.0.0", EMERGENCY_PORT))
normal_socket.bind(("0.0.0.0", NORMAL_PORT))


def receive_notifications(sock):
    while running.is_set():
        try:
            data, _ = sock.recvfrom(BUFFER_SIZE)
            message = data.decode(errors="replace")

            if message == "SERVER_SHUTDOWN":
                print("\nServer is shutting down.")
                running.clear()
                break

            parts = message.split("|", 2)

            if len(parts) != 3:
                continue

            notification_type, message_id, content = parts

            print("\n==============================")
            print(f" {notification_type} NOTIFICATION")
            print(f" ID: {message_id}")
            print(f" Message: {content}")
            print("==============================")

            control_socket.sendto(
                f"ACK|{client_name}|{message_id}".encode(),
                server_address
            )

            print("Acknowledgement sent.")

        except socket.timeout:
            continue
        except OSError:
            break


client_name = input("Enter your name: ").strip()

if not client_name:
    print("Name cannot be empty.")
    raise SystemExit

control_socket.sendto(
    f"REGISTER|{client_name}".encode(),
    server_address
)

try:
    response, _ = control_socket.recvfrom(BUFFER_SIZE)

    if response.decode() != "REGISTERED":
        print("Registration failed.")
        raise SystemExit

except socket.timeout:
    print("Server did not respond. Check SERVER_IP and try again.")
    raise SystemExit

print(f"\nRegistered successfully as {client_name}.")

threading.Thread(
    target=receive_notifications,
    args=(emergency_socket,),
    daemon=True
).start()

threading.Thread(
    target=receive_notifications,
    args=(normal_socket,),
    daemon=True
).start()

print("Listening for emergency and normal notifications.")
print("Press Ctrl+C to disconnect.")

try:
    while running.is_set():
        threading.Event().wait(1)

except KeyboardInterrupt:
    print("\nDisconnecting...")

finally:
    running.clear()

    try:
        control_socket.sendto(
            f"UNREGISTER|{client_name}".encode(),
            server_address
        )
    except OSError:
        pass

    control_socket.close()
    emergency_socket.close()
    normal_socket.close()

    print("Disconnected.")
