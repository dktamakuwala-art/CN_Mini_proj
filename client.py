from src.client import _parse_args, EmergencyClient
import time


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
        print("\\nDisconnecting...")
    finally:
        client.stop()
        print("Disconnected.")
