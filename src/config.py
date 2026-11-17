# Network configuration
SERVER_HOST = "0.0.0.0"
SERVER_IP = "10.0.0.1"
SERVER_PORT = 5000

EMERGENCY_PORT = 5001
NORMAL_PORT = 5002
BACKGROUND_PORT = 6000

BUFFER_SIZE = 4096
ACK_TIMEOUT = 2.0
MAX_RETRIES = 2
RETRY_INTERVAL = 1.0
MAX_CLIENTS = 200

PORT_PRIORITY_QUEUE = {
    EMERGENCY_PORT: 1,
    NORMAL_PORT: 2,
    BACKGROUND_PORT: 0,
}

TRAFFIC_PRIORITY = {
    "EMERGENCY": "HIGH",
    "NORMAL": "LOW",
    "BACKGROUND": "BACKGROUND",
}

CONGESTION_DROP_THRESHOLD = 50
CONGESTION_CHECK_INTERVAL = 2.0

# App -> SDN in-band signalling (UDP broadcast, intercepted by the switch and
# delivered to the controller as a packet-in; no extra connectivity needed)
SDN_SIGNAL_PORT = 5999
SDN_SIGNAL_ADDR = "10.0.0.255"

# Dynamic SDN thresholds
FLOOD_RATE_THRESHOLD_MBPS = 5.0   # per-port ingress rate treated as flooding
FLOOD_BLOCK_SECONDS = 20          # how long an offending port stays rate-limited
EMERGENCY_HOLD_SECONDS = 10       # fallback expiry for emergency mode
