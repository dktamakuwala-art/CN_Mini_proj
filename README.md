# Emergency Notification Network

UDP-based emergency notification application integrated with an OpenFlow 1.3 SDN controller and a Mininet demonstration topology.

## Project structure

- `src/server.py` — UDP notification server, subscriber registry, ACK tracking and retries
- `src/client.py` — UDP subscriber client
- `src/config.py` — shared network and QoS configuration
- `src/controller.py` — OS-Ken OpenFlow 1.3 learning switch with UDP traffic classification and congestion response
- `scripts/mininet_topology.py` — four-host Mininet topology and OVS queues
- `scripts/verify_environment.py` — checks required executables and Python packages
- `scripts/performance_benchmark.py` — local subscriber scalability benchmark
- `tests/` — application reliability tests

Root-level `server.py` and `client.py` are convenience launchers. The implementation lives in `src/`; duplicate backup implementations were removed to avoid running inconsistent versions.

## Requirements

Application:
- Python 3.10+
- `pytest` to run tests

SDN demonstration:
- Mininet
- Open vSwitch
- OS-Ken
- `eventlet`
- `iperf3` and `xterm` are useful for the congestion demonstration

Install Python dependencies in the environment used to run the controller:

```bash
python3 -m pip install os-ken eventlet pytest matplotlib
```

Mininet and Open vSwitch are system packages and should be installed in a supported Linux VM. The Mininet topology is not expected to run natively on macOS.

## Run the application locally

From the project root:

Terminal 1:

```bash
python3 server.py
```

Terminal 2:

```bash
python3 client.py --name Client1
```

Terminal 3:

```bash
python3 client.py --name Client2
```

The default server control address is `0.0.0.0:5000`. Clients use `10.0.0.1` by default. For a local-machine test, pass `--server-ip 127.0.0.1` to each client.

Each client listens on UDP ports 5001 (emergency) and 5002 (normal). When running multiple clients on the same machine, assign unique receive ports using `--emergency-port` and `--normal-port`; clients on separate Mininet hosts can use the defaults.

## Run the reliability tests

From the project root:

```bash
python3 -m pytest -q
```

## Run the SDN demonstration in a Linux VM

The supplied topology uses:
- `h1` — server, `10.0.0.1/24`
- `h2` — subscriber 1, `10.0.0.2/24`
- `h3` — subscriber 2, `10.0.0.3/24`
- `h4` — subscriber 3, `10.0.0.4/24`
- `s1` — OpenFlow 1.3 switch

Start the controller in one terminal:

```bash
osken-manager src/controller.py
```

Start the Mininet topology in another terminal (with the required privileges):

```bash
sudo python3 scripts/mininet_topology.py
```

At the Mininet CLI, start the server and clients in separate hosts:

```text
h1 python3 server.py
h2 python3 client.py --name Client1
h3 python3 client.py --name Client2
h4 python3 client.py --name Client3
```

These commands assume the project directory is available on each Mininet host's shared filesystem and that Python dependencies are installed. In a typical Mininet process, hosts share the filesystem but have separate network namespaces.

## Traffic classification and QoS

The controller classifies UDP destination ports:
- `5001` — emergency, queue 1, highest static flow priority
- `5002` — normal, queue 2
- `6000` — background, queue 0

The topology creates OVS queues on the switch-facing host ports. Under congestion, the controller demotes normal traffic to queue 0 and raises emergency-flow priority. Queue selection only has an effect when the corresponding OVS QoS/queue configuration is present on the egress port.

Congestion detection uses the increase in dropped-packet counters between port-statistics samples rather than the lifetime cumulative drop count. This is a simple demonstration heuristic, not a production congestion-control algorithm.

## Benchmark

Run from the project root:

```bash
python3 scripts/performance_benchmark.py
```

The script writes CSV and PNG results under `results/`. It is a local UDP application benchmark; it does not measure the Mininet/SDN path unless separately adapted to run through that topology.

## Important limitations

- UDP does not guarantee delivery; ACKs and retries provide application-level confirmation, not exactly-once delivery.
- ACK tracking is scoped to the subscriber set captured when a notification is sent. A subscriber that disconnects before acknowledging can cause that notification to remain pending and eventually fail.
- The controller's port-statistics congestion heuristic and queue mapping are intended for the project demonstration. Validate actual OVS queue behavior in the target VM before presenting performance claims.
