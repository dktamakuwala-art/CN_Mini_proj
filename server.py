from src.server import NotificationServer


if __name__ == "__main__":
    server = NotificationServer()
    try:
        server.start()
        server.run_menu()
    except KeyboardInterrupt:
        print("\nServer interrupted.")
    finally:
        server.stop()
