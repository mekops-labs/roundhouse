"""Measure the latency budgets on this host and write docs/measurements.md.

    measure.py            run every measurement
    measure.py --quick    fewer samples, for a check of the script itself

Each number is the time from the action in Home Assistant (or on the device) to the
message the device sees on the broker, measured by a device double on the same host.
The state rows include the REST call that makes the change.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import date
from typing import Any

import harness
from harness import LAMPS, POOL, Ha, now, stats
from soak import DEVICES

BUDGETS_MS = {
    "state_to_publish": 200,
    "save_to_views": 3000,
    "command_to_result": 100,
    "alert_with_snapshot": 3000,
    "ha_start_to_resync": 30000,
}


def measure(ha: Ha, doubles: list[harness.Double], quick: bool) -> dict[str, Any]:
    """Run each measurement and return the samples in seconds."""
    n_state, n_save, n_cmd, n_alert, n_restart = (
        (20, 3, 20, 4, 1) if quick else (200, 10, 100, 20, 3)
    )
    out: dict[str, list[float]] = {k: [] for k in BUDGETS_MS}
    extra: dict[str, Any] = {}
    tender = doubles[0]

    # State change to publish.
    for i in range(n_state):
        entity = LAMPS[i % 3]
        turn_on = ha.state(entity)["state"] != "on"
        started = now()
        ha.call(
            "input_boolean", "turn_on" if turn_on else "turn_off", {"entity_id": entity}
        )
        got = tender.wait(
            f"state/{entity}",
            lambda b, w=("On" if turn_on else "Off"): b["text"] == w,
            started,
            5,
        )
        if got:
            out["state_to_publish"].append(got[0] - started)
        time.sleep(0.05)

    # Command to result, with an instant service.
    for _ in range(n_cmd):
        result, took = tender.command({"entity_id": LAMPS[0], "action": "toggle"})
        if result == "ok":
            out["command_to_result"].append(took)
        time.sleep(0.05)

    # Dashboard save to view definition on the device, with the 2 s wait.
    slug = DEVICES[0][2]
    for i in range(n_save):
        chosen = [POOL[(i + j) % len(POOL)] for j in range(3 + i % 5)]
        started = now()
        ha.save_dashboard(
            slug,
            [
                {
                    "path": "home",
                    "title": "Home",
                    "cards": [{"type": "tile", "entity": e} for e in chosen],
                }
            ],
        )
        got = tender.wait(
            "views",
            lambda b, c=chosen: (
                [t["entity_id"] for v in b["views"] for t in v["tiles"]] == c
            ),
            started,
            10,
        )
        if got:
            out["save_to_views"].append(got[0] - started)
        time.sleep(0.5)

    # An alert with a snapshot to its image and alert topics.
    registry = ha.ws([{"type": "config/device_registry/list"}])[0]["result"]
    device = next(
        d
        for d in registry
        if ["roundhouse", tender.device_id] in [list(i) for i in d["identifiers"]]
    )
    for _ in range(n_alert):
        started = now()
        reply = ha.call(
            "roundhouse",
            "send_alert",
            {
                "device_id": [device["id"]],
                "title": "Measure",
                "message": "m",
                "image_url": harness.IMAGE_URL,
            },
            response=True,
        )
        alert_id = next(iter(reply["service_response"]["alert_ids"].values()))
        got = tender.wait(
            f"alert/{alert_id}", lambda b: b.get("image") is not None, started, 10
        )
        if got:
            out["alert_with_snapshot"].append(got[0] - started)
        time.sleep(0.3)

    # Home Assistant start to the full retained set.
    for _ in range(n_restart):
        started = now()
        subprocess.run(
            ["podman", "restart", harness.rig.HA_NAME], capture_output=True, check=True
        )
        ready = ha.wait_ready()
        done = 0.0
        tiles = [e["entity_id"] for e in (tender.latest("views")["views"][0]["tiles"])]
        for suffix in ["meta", "views"] + [f"state/{e}" for e in set(tiles)]:
            got = tender.wait(suffix, lambda b: True, started, 60)
            done = max(done, (got[0] - started) if got else 60)
        out["ha_start_to_resync"].append(done)
        extra.setdefault("api_ready_s", []).append(round(ready, 1))
    return {"samples": out, "extra": extra}


def unit(ms: float) -> str:
    """Format milliseconds."""
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def table(result: dict[str, Any]) -> str:
    """Return the markdown table of results against the budgets."""
    rows = [
        ("Entity state change to `state/…` publish", "state_to_publish", "≤ 200 ms"),
        (
            "Dashboard save to `views` publish (with the 2 s wait)",
            "save_to_views",
            "≤ 3 s",
        ),
        (
            "`cmd` to `result` (an instant service)",
            "command_to_result",
            "≤ service time + 100 ms",
        ),
        ("Alert with a snapshot to its publish", "alert_with_snapshot", "≤ 3 s"),
        (
            "Home Assistant restart to the full retained set",
            "ha_start_to_resync",
            "≤ 30 s",
        ),
    ]
    lines = [
        "| Path | Budget | Samples | p50 | p95 | max | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label, key, budget in rows:
        s = stats(result["samples"][key])
        if not s["n"]:
            lines.append(f"| {label} | {budget} | 0 | - | - | - | no data |")
            continue
        ok = s["max"] <= BUDGETS_MS[key]
        verdict = (
            "within"
            if ok
            else ("p95 within, max over" if s["p95"] <= BUDGETS_MS[key] else "over")
        )
        lines.append(
            f"| {label} | {budget} | {s['n']} | {unit(s['p50'])} | {unit(s['p95'])} | {unit(s['max'])} | {verdict} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--write-docs", action="store_true", help="write docs/measurements.md"
    )
    args = parser.parse_args()
    images = harness.ImageServer()
    ha, doubles = harness.setup(DEVICES)
    try:
        result = measure(ha, doubles, args.quick)
        result["host"] = harness.host_description()
    finally:
        for double in doubles:
            double.stop()
        images.stop()
        harness.rig.down()
    text = table(result)
    print(text)
    (harness.SOAK_DIR / "measure.json").write_text(json.dumps(result, indent=2))
    if args.write_docs:
        host = result["host"]
        doc = f"""# Latency measurements

Measured on {date.today().isoformat()} by `tools/soak/measure.py`, on one host
running Mosquitto 2 and Home Assistant {host["home_assistant"]} in Podman, with
two device doubles on the broker and the documented ACL applied.

- CPU: {host["cpu"]}
- Memory: {host["memory_mb"]} MB
- Kernel: {host["kernel"]}

Each number is the time from the action to the message the device sees, as the
double measures it on the same host. The state rows include the REST call that
makes the change. The save row includes the 2 s wait of the digest. The snapshot
comes from an image URL on the same host; a camera adds the time the camera
needs to produce an image.

{text}

A reference host is a small machine such as a Raspberry
Pi; these numbers come from a desktop and show the cost of Roundhouse itself, not
of a small host. Run `mise run measure` on the target host to record its numbers.
"""
        (harness.REPO / "docs" / "measurements.md").write_text(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
