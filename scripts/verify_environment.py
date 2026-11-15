#!/usr/bin/env python3
import importlib.util
import shutil
import sys

CHECKS = [
    ("git", "git"),
    ("python3", "python3"),
    ("pip3", "pip3"),
    ("mininet", "mn"),
    ("ovs-vsctl", "ovs-vsctl"),
    ("iperf3", "iperf3"),
    ("xterm", "xterm"),
]

print("Environment verification")
for label, executable in CHECKS:
    found = shutil.which(executable) is not None
    print(f"{label}: {'OK' if found else 'MISSING'}")

modules = ["os_ken", "mininet", "pytest"]
for module in modules:
    spec = importlib.util.find_spec(module)
    print(f"module {module}: {'OK' if spec else 'MISSING'}")

print("Python executable:", sys.executable)
