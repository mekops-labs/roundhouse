# Latency measurements

Measured on 2026-11-01 by `tools/soak/measure.py`, on one host
running Mosquitto 2 and Home Assistant 2026.10.4 in Podman, with
two device doubles on the broker and the documented ACL applied.

- CPU: AMD Ryzen 9 7940HS w/ Radeon 780M Graphics
- Memory: 15753 MB
- Kernel: 7.2.11-ogc4.1.fc44.x86_64

Each number is the time from the action to the message the device sees, as the
double measures it on the same host. The state rows include the REST call that
makes the change. The save row includes the 2 s wait of the digest. The snapshot
comes from an image URL on the same host; a camera adds the time the camera
needs to produce an image.

| Path | Budget | Samples | p50 | p95 | max | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Entity state change to `state/…` publish | ≤ 200 ms | 200 | 2 ms | 3 ms | 40 ms | within |
| Dashboard save to `views` publish (with the 2 s wait) | ≤ 3 s | 10 | 2.0 s | 2.0 s | 2.0 s | within |
| `cmd` to `result` (an instant service) | ≤ service time + 100 ms | 100 | 41 ms | 42 ms | 43 ms | within |
| Alert with a snapshot to its publish | ≤ 3 s | 20 | 21 ms | 48 ms | 48 ms | within |
| Home Assistant restart to the full retained set | ≤ 30 s | 3 | 6.9 s | 7.0 s | 7.0 s | within |

The reference host in the specification is a small machine such as a Raspberry
Pi; these numbers come from a desktop and show the cost of Roundhouse itself, not
of a small host. Run `mise run measure` on the target host to record its numbers.

## Soak

`tools/soak/soak.py` (QT-4) keeps two device doubles online on a broker with the
documented ACL and drives a workload: changes in Home Assistant and commands from
the devices, dashboard edits (some overflowing), alerts with a snapshot and an
action, and restarts of Home Assistant and of the broker. It fails on a lost
update, an unanswered command, a blocking-call warning, a Roundhouse error in the
log, or a state that disagrees with Home Assistant when it ends.

A compressed run on this host, 25 minutes with a restart of each every 5 to 6
minutes, passed:

| | |
| --- | --- |
| Changes in Home Assistant | 265 |
| Commands from a device | 200 |
| Dashboard edits | 14 (2 overflowing) |
| Alerts with a snapshot, an action, and an acknowledgment | 8 |
| Restarts of Home Assistant and of the broker | 4 and 4 |
| Lost updates, unanswered commands | 0 |
| Blocking-call warnings, Roundhouse errors | 0 |
| State change to publish, steady state | p50 2 ms, p95 3 ms |
| Retained set complete after a broker restart | 1.0 s |
| Retained set complete after a Home Assistant restart | 7.0 s |

The first runs found a real defect: while the broker was away, a failed send
dropped the update, and the reconnect then republished the older value. A send
now records its payload first, and a failed send is retried every 5 seconds and
after a reconnect. An update made while the broker restarts waits for Home
Assistant's own MQTT reconnect and then arrives; the slowest in the run took
9 seconds. The soak counts that as delivered, because the update is never lost.

The specification asks for 24 hours. Run it with `mise run soak -- --minutes
1440`; it writes `report.json` to the soak directory.
