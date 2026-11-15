#!/usr/bin/env python3
import csv
import os
import statistics
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.client import EmergencyClient
from src.server import NotificationServer

RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "results")
OUTPUT_PATH = os.path.join(RESULTS_DIR, "scalability_results.csv")
GRAPH_PATH = os.path.join(RESULTS_DIR, "scalability_comparison.png")


def measure_group(subscriber_count: int, server_port: int):
    server = NotificationServer(udp_port=server_port, ack_timeout=0.25, retry_limit=1)
    server.start()
    clients = []
    registration_successes = 0
    all_latencies = []
    total_retransmissions = 0
    failed_notifications = 0
    ack_success_rates = []
    delivery_success_rates = []
    packet_loss_rates = []

    try:
        for i in range(subscriber_count):
            emergency_port = 20000 + (server_port * 2) + i * 2
            normal_port = emergency_port + 1
            client = EmergencyClient(
                f"Client{i}",
                server_ip="127.0.0.1",
                server_port=server_port,
                emergency_port=emergency_port,
                normal_port=normal_port,
            )
            try:
                client.register()
                registration_successes += 1
                client.start()
                clients.append(client)
            except Exception:
                client.stop()
                continue

        registration_percent = (registration_successes / subscriber_count) * 100.0 if subscriber_count else 0.0

        for notification_type in ("NORMAL", "EMERGENCY"):
            send_time = time.perf_counter()
            message_id = server.send_notification(notification_type, f"benchmark-{notification_type}")
            deadline = time.perf_counter() + 4.0
            while time.perf_counter() < deadline:
                server.retry_pending_notifications()
                time.sleep(0.05)
                status = server.get_delivery_status(message_id)
                if status["status"] == "acknowledged":
                    latency = time.perf_counter() - send_time
                    all_latencies.append(latency)
                    ack_rate = (status["acknowledged"] / status["expected"]) * 100.0 if status["expected"] else 0.0
                    ack_success_rates.append(ack_rate)
                    delivery_success_rates.append(ack_rate)
                    packet_loss_rates.append(100.0 - ack_rate)
                    total_retransmissions += status["retries"]
                    break
                if status["status"] == "failed":
                    failed_notifications += 1
                    ack_rate = (status["acknowledged"] / status["expected"]) * 100.0 if status["expected"] else 0.0
                    ack_success_rates.append(ack_rate)
                    delivery_success_rates.append(ack_rate)
                    packet_loss_rates.append(100.0 - ack_rate)
                    total_retransmissions += status["retries"]
                    break
            else:
                failed_notifications += 1
                status = server.get_delivery_status(message_id)
                ack_rate = (status["acknowledged"] / status["expected"]) * 100.0 if status["expected"] else 0.0
                ack_success_rates.append(ack_rate)
                delivery_success_rates.append(ack_rate)
                packet_loss_rates.append(100.0 - ack_rate)
                total_retransmissions += status["retries"]

        avg_latency = statistics.mean(all_latencies) if all_latencies else 0.0
        ordered = sorted(all_latencies)
        p95_latency = ordered[max(0, min(len(ordered) - 1, int(0.95 * len(ordered))))] if ordered else 0.0

        ack_success = statistics.mean(ack_success_rates) if ack_success_rates else 0.0
        delivery_success = statistics.mean(delivery_success_rates) if delivery_success_rates else 0.0
        packet_loss = statistics.mean(packet_loss_rates) if packet_loss_rates else 0.0

        return {
            "subscribers": subscriber_count,
            "registration_success_percent": round(registration_percent, 2),
            "notification_delivery_success_percent": round(delivery_success, 2),
            "ack_success_percent": round(ack_success, 2),
            "average_latency_s": round(avg_latency, 4),
            "p95_latency_s": round(p95_latency, 4),
            "packet_loss_percent": round(packet_loss, 2),
            "retransmissions": total_retransmissions,
            "failed_notifications": failed_notifications,
        }
    finally:
        for client in clients:
            client.stop()
        server.stop()


def plot_results(rows):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        print(f"Matplotlib unavailable: {exc}")
        return

    subscribers = [row["subscribers"] for row in rows]
    registration = [row["registration_success_percent"] for row in rows]
    delivery = [row["notification_delivery_success_percent"] for row in rows]
    ack = [row["ack_success_percent"] for row in rows]
    latency = [row["average_latency_s"] for row in rows]
    packet_loss = [row["packet_loss_percent"] for row in rows]
    retrans = [row["retransmissions"] for row in rows]

    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    axes = axes.flatten()

    axes[0].plot(subscribers, registration, marker="o")
    axes[0].set_title("Registration Success")
    axes[0].set_xlabel("Subscribers")
    axes[0].set_ylabel("%")
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(subscribers, delivery, marker="o", color="tab:green")
    axes[1].set_title("Notification Delivery")
    axes[1].set_xlabel("Subscribers")
    axes[1].set_ylabel("%")
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(subscribers, ack, marker="o", color="tab:purple")
    axes[2].set_title("ACK Success")
    axes[2].set_xlabel("Subscribers")
    axes[2].set_ylabel("%")
    axes[2].grid(True, alpha=0.3)

    axes[3].plot(subscribers, latency, marker="o", color="tab:blue")
    axes[3].set_title("Average Latency")
    axes[3].set_xlabel("Subscribers")
    axes[3].set_ylabel("Seconds")
    axes[3].grid(True, alpha=0.3)

    axes[4].plot(subscribers, packet_loss, marker="o", color="tab:red")
    axes[4].set_title("Packet Loss")
    axes[4].set_xlabel("Subscribers")
    axes[4].set_ylabel("%")
    axes[4].grid(True, alpha=0.3)

    axes[5].plot(subscribers, retrans, marker="o", color="tab:orange")
    axes[5].set_title("Retransmissions")
    axes[5].set_xlabel("Subscribers")
    axes[5].set_ylabel("Count")
    axes[5].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(GRAPH_PATH, dpi=200)
    print(f"Saved graph to {GRAPH_PATH}")


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    targets = [25, 50, 100]
    results = []

    for count in targets:
        try:
            result = measure_group(count, 5100 + count)
            results.append(result)
            print(f"Scale test {count}: {result}")
        except Exception as exc:
            print(f"Scale test {count} failed: {exc}")
            results.append({
                "subscribers": count,
                "registration_success_percent": 0.0,
                "notification_delivery_success_percent": 0.0,
                "ack_success_percent": 0.0,
                "average_latency_s": 0.0,
                "p95_latency_s": 0.0,
                "packet_loss_percent": 100.0,
                "retransmissions": 0,
                "failed_notifications": 1,
            })

    with open(OUTPUT_PATH, "w", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "subscribers",
                "registration_success_percent",
                "notification_delivery_success_percent",
                "ack_success_percent",
                "average_latency_s",
                "p95_latency_s",
                "packet_loss_percent",
                "retransmissions",
                "failed_notifications",
            ],
        )
        writer.writeheader()
        writer.writerows(results)

    print(f"Saved CSV to {OUTPUT_PATH}")
    plot_results(results)


if __name__ == "__main__":
    main()
