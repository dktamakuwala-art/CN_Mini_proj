#!/usr/bin/env python3
"""Background UDP load: flood.py <ip> <port> <mbps>"""
import socket
import sys
import time

ip, port, mbps = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = b"x" * 1200
interval = len(payload) * 8 / (mbps * 1e6)
nxt = time.perf_counter()
while True:
    try:
        sock.sendto(payload, (ip, port))
    except OSError:
        pass
    nxt += interval
    delay = nxt - time.perf_counter()
    if delay > 0:
        time.sleep(delay)
