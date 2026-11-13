# Latency measurements

Measured on 2026-11-13 by `tools/soak/measure.py`, on one host
running Mosquitto 2 and Home Assistant 2026.11.1 in Podman, with
two device doubles on the broker and the documented ACL applied.

- CPU: AMD Ryzen 9 7940HS w/ Radeon 780M Graphics
- Memory: 15753 MB
- Kernel: 7.2.15-ogc1.1.fc45.x86_64

Each number is the time from the action to the message the device sees, as the
double measures it on the same host. The state rows include the REST call that
makes the change. The snapshot
comes from an image URL on the same host; a camera adds the time the camera
needs to produce an image.

| Path | Budget | Samples | p50 | p95 | max | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Entity state change to `state/…` publish | ≤ 200 ms | 200 | 2 ms | 2 ms | 39 ms | within |
| Done in the editor to `views` publish | ≤ 1 s | 10 | 5 ms | 6 ms | 6 ms | within |
| `cmd` to `result` (an instant service) | ≤ service time + 100 ms | 100 | 41 ms | 42 ms | 42 ms | within |
| Alert with a snapshot to its publish | ≤ 3 s | 20 | 21 ms | 45 ms | 45 ms | within |
| Home Assistant restart to the full retained set | ≤ 30 s | 3 | 7.9 s | 8.1 s | 8.1 s | within |

A reference host is a small machine such as a Raspberry
Pi; these numbers come from a desktop and show the cost of Roundhouse itself, not
of a small host. Run `mise run measure` on the target host to record its numbers.
