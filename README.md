# Emergency Notification Network - UDP Application

## Purpose
This folder contains the UDP application layer for the Emergency Notification Network project.

The application supports:
- Multiple UDP clients/subscribers
- Client registration
- Normal notifications
- Emergency notifications
- Notification IDs
- Emergency/high-priority classification
- Broadcast to all registered clients
- Delivery acknowledgements (ACKs)
- Per-client delivery tracking
- Notification history
- Client unregister/shutdown handling

## Files
- `config.py` - network configuration
- `server.py` - notification server/sender
- `client.py` - subscriber/client

## Current packet format

Registration:
`REGISTER|<client_name>`

Notification:
`<TYPE>|<MESSAGE_ID>|<MESSAGE>`

Examples:
`NORMAL|1|Maintenance at 6 PM`
`EMERGENCY|2|Fire detected in Block A`

ACK:
`ACK|<client_name>|<MESSAGE_ID>`

Unregister:
`UNREGISTER|<client_name>`

Server shutdown:
`SERVER_SHUTDOWN`

## Run locally

Terminal 1:
`python3 server.py`

Terminal 2:
`python3 client.py`

Terminal 3:
`python3 client.py`

Use different names such as Client1, Client2, Client3.

## Important integration point for SDN

Emergency traffic is identified at the application layer by:

`TYPE = EMERGENCY`

and is also represented by:

`Priority = HIGH`

Normal traffic uses:

`TYPE = NORMAL`

and:

`Priority = LOW`

The SDN/controller part of the project can use this application-level distinction when implementing traffic classification and priority forwarding.

## Moving to VM/Mininet

Change `SERVER_IP` in `config.py` to the appropriate server/host IP for the VM/Mininet topology.

The UDP application itself does not require the SDN controller; it simply generates and receives UDP traffic. The SDN layer should be inserted into the network path between the sender and clients.

## Suggested final integration

Server/host
    |
    | UDP
    v
Mininet / SDN switch + controller
    |
    +---- Client 1
    +---- Client 2
    +---- Client 3

Under congestion, the final project should compare emergency and normal traffic using latency and packet-loss measurements.

## Testing checklist

[ ] Register 3 clients
[ ] Send a normal notification
[ ] Send an emergency notification
[ ] Verify all clients receive both
[ ] Verify ACKs are recorded
[ ] Verify notification IDs increment
[ ] Verify client unregister works
[ ] Test through the VM/Mininet network
[ ] Test under congestion
