"""The soak: a scripted workload against Roundhouse, with restarts.

    soak.py --minutes 20          a short run
    soak.py --minutes 1440        the 24-hour soak

Two device doubles (a Tender and a wall panel) stay on a broker that applies the
documented ACL. The workload changes entities from Home Assistant and from the
devices, edits the views, raises alerts, and restarts Home Assistant and
the broker on a schedule. The run fails on any lost update, any unanswered
command, any blocking-call warning, or any state that disagrees with Home
Assistant at the end. The report goes to SOAK_DIR/report.json and report.md.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from typing import Any

import harness
from harness import LAMPS, LEVELS, POOL, Double, Ha, now, stats

DEVICES = [
    ("tender01", "tender"),
    ("wall01", "wall"),
]
STATE_DEADLINE = 6.0
COMMAND_DEADLINE = 15.0
VIEWS_DEADLINE = 8.0
ALERT_DEADLINE = 10.0
RESYNC_DEADLINE = 60.0
# After a restart an update waits for Home Assistant's own MQTT reconnect.
OUTAGE_GRACE = 30.0
OUTAGE_DEADLINE = 25.0


class Soak:
    """The workload, the bookkeeping, and the report."""

    def __init__(self, ha: Ha, doubles: list[Double], seed: int) -> None:
        """Initialize with a seeded random source for a repeatable run."""
        self.ha, self.doubles = ha, doubles
        self.random = random.Random(seed)
        self.failures: list[str] = []
        self.latency: dict[str, list[float]] = {
            k: []
            for k in (
                "state",
                "command",
                "views",
                "alert",
                "ack",
                "ha_resync",
                "broker_resync",
            )
        }
        self.counts: dict[str, int] = {
            k: 0
            for k in (
                "ha_changes",
                "device_commands",
                "view_edits",
                "refused_edits",
                "alerts",
                "acks",
                "ha_restarts",
                "broker_restarts",
                "state_checks",
            )
        }
        self.tiles: dict[str, list[str]] = {d.device_id: POOL[:5] for d in doubles}
        self.held = {d.device_id: False for d in doubles}
        self.grace_until = 0.0

    def fail(self, text: str) -> None:
        """Record a failure."""
        print("FAIL:", text, flush=True)
        self.failures.append(text)

    def state_deadline(self) -> float:
        """The wait for a state update: longer for a short while after a restart."""
        return OUTAGE_DEADLINE if now() < self.grace_until else STATE_DEADLINE

    def published(self, double: Double, entity_id: str) -> bool:
        """Whether the entity is on a published view of the device."""
        return entity_id in self.tiles[double.device_id]

    # --- steps ---------------------------------------------------------------

    def ha_change(self) -> None:
        """Change an entity in Home Assistant; every device showing it must see it."""
        if self.random.random() < 0.6:
            entity = self.random.choice(LAMPS)
            expected_on = self.ha.state(entity)["state"] != "on"
            started = now()
            self.ha.call(
                "input_boolean",
                "turn_on" if expected_on else "turn_off",
                {"entity_id": entity},
            )
            want = "On" if expected_on else "Off"
        else:
            entity = self.random.choice(LEVELS)
            current = self.ha.state(entity)["state"]
            value = self.random.choice(
                [v for v in range(0, 101, 5) if f"{v}.0" != current]
            )
            started = now()
            self.ha.call(
                "input_number", "set_value", {"entity_id": entity, "value": value}
            )
            want = str(value)
        self.counts["ha_changes"] += 1
        for double in self.doubles:
            if self.published(double, entity):
                deadline = self.state_deadline()
                got = double.wait(
                    f"state/{entity}",
                    lambda b, w=want: isinstance(b, dict) and b["text"] == w,
                    started,
                    deadline,
                )
                if got is None:
                    self.fail(
                        f"{double.device_id}: no state/{entity} == {want!r} within {deadline}s"
                    )
                else:
                    self.latency["state"].append(got[0] - started)

    def device_command(self) -> None:
        """A device toggles a lamp; the result comes back and the state follows."""
        double = self.random.choice(self.doubles)
        entities = [e for e in self.tiles[double.device_id] if e in LAMPS]
        if not entities:
            return
        entity = self.random.choice(entities)
        before = self.ha.state(entity)["state"]
        result, took = double.command(
            {"entity_id": entity, "action": "toggle"}, COMMAND_DEADLINE
        )
        self.counts["device_commands"] += 1
        if result is None:
            self.fail(
                f"{double.device_id}: no result for toggle {entity} within {COMMAND_DEADLINE}s"
            )
            return
        self.latency["command"].append(took)
        if result != "ok":
            self.fail(f"{double.device_id}: toggle {entity} answered {result!r}")
            return
        after = self.ha.state(entity)["state"]
        if after == before:
            self.fail(f"toggle {entity} did not change the state ({before})")

    def edit_views(self, overflow: bool = False) -> None:
        """Save new views; a save that fits must reach the device, one that does not must be refused."""
        double = self.random.choice(self.doubles)
        capacity = double.capacity
        size = (
            capacity + self.random.randint(1, 4)
            if overflow
            else self.random.randint(2, capacity)
        )
        chosen = [self.random.choice(POOL) for _ in range(size)]
        if not overflow and chosen == self.tiles[double.device_id]:
            return
        started = now()
        result = self.ha.save_views(
            double.device_id, double.profile, [("home", chosen)]
        )
        if overflow:
            self.counts["refused_edits"] += 1
            if result.get("ok"):
                self.fail(f"{double.device_id}: a save of {size} tiles was accepted")
            time.sleep(4)
            latest = double.latest("views")
            ids = [t["entity_id"] for v in latest["views"] for t in v["tiles"]]
            if ids != self.tiles[double.device_id]:
                self.fail(
                    f"{double.device_id}: a refused save changed the device ({len(ids)} tiles)"
                )
            return
        if not result.get("ok"):
            self.fail(
                f"{double.device_id}: a save of {size} tiles was refused: {result}"
            )
            return
        self.counts["view_edits"] += 1
        got = double.wait(
            "views",
            lambda b: (
                [t["entity_id"] for v in b["views"] for t in v["tiles"]] == chosen
            ),
            started,
            VIEWS_DEADLINE,
        )
        if got is None:
            self.fail(
                f"{double.device_id}: views for {len(chosen)} tiles not published within {VIEWS_DEADLINE}s"
            )
            return
        self.latency["views"].append(got[0] - started)
        self.tiles[double.device_id] = chosen

    def alert(self) -> None:
        """Raise an alert with a snapshot; the device sees it, acknowledges it, sees it read."""
        double = self.random.choice(self.doubles)
        registry = self.ha.ws([{"type": "config/device_registry/list"}])[0]["result"]
        device = next(
            d
            for d in registry
            if ["roundhouse", double.device_id] in [list(i) for i in d["identifiers"]]
        )
        started = now()
        reply = self.ha.call(
            "roundhouse",
            "send_alert",
            {
                "device_id": [device["id"]],
                "title": "Soak",
                "message": "check",
                "severity": "warning",
                "image_url": harness.IMAGE_URL,
                "tag": f"soak-{double.device_id}",
                "actions": [
                    {
                        "id": "on",
                        "label": "Lamp on",
                        "action": "input_boolean.turn_on",
                        "target": {"entity_id": "input_boolean.lamp6"},
                    }
                ],
            },
            response=True,
        )
        alert_id = next(iter(reply["service_response"]["alert_ids"].values()))
        self.counts["alerts"] += 1
        got = double.wait(
            f"alert/{alert_id}",
            lambda b: isinstance(b, dict) and b.get("image") is not None,
            started,
            ALERT_DEADLINE,
        )
        if got is None:
            self.fail(
                f"{double.device_id}: alert {alert_id} with its image not published within {ALERT_DEADLINE}s"
            )
            return
        self.latency["alert"].append(got[0] - started)
        if double.wait(f"alert/{alert_id}/image", lambda b: True, started, 3) is None:
            self.fail(f"{double.device_id}: alert {alert_id} has no image topic")
        result, _ = double.command({"alert": alert_id, "action_id": "on"})
        if result != "ok":
            self.fail(f"{double.device_id}: alert action answered {result!r}")
        acked = now()
        result, _ = double.command({"ack": alert_id})
        read = double.wait(
            f"alert/{alert_id}",
            lambda b: isinstance(b, dict) and b.get("read") is True,
            acked,
            ALERT_DEADLINE,
        )
        self.counts["acks"] += 1
        if result != "ok" or read is None:
            self.fail(
                f"{double.device_id}: acknowledgment of {alert_id} not confirmed ({result!r})"
            )
        else:
            self.latency["ack"].append(read[0] - acked)

    # --- restarts ------------------------------------------------------------

    def resync_complete(self, started: float) -> float | None:
        """Wait until every device has seen meta, views, and every tile's state again."""
        done = 0.0
        for double in self.doubles:
            for suffix in ["meta", "views"] + [
                f"state/{e}" for e in set(self.tiles[double.device_id])
            ]:
                got = double.wait(
                    suffix, lambda b: True, started, RESYNC_DEADLINE - (now() - started)
                )
                if got is None:
                    self.fail(
                        f"{double.device_id}: no {suffix} after the restart within {RESYNC_DEADLINE}s"
                    )
                    return None
                done = max(done, got[0] - started)
        return done

    def restart_ha(self) -> None:
        """Restart Home Assistant; the retained set must come back."""
        started = now()
        subprocess.run(
            ["podman", "restart", harness.rig.HA_NAME], capture_output=True, check=True
        )
        self.counts["ha_restarts"] += 1
        try:
            ready = self.ha.wait_ready()
        except TimeoutError:
            self.fail("Home Assistant did not come back after a restart")
            return
        took = self.resync_complete(started)
        if took is not None:
            self.latency["ha_resync"].append(took)
        self.grace_until = now() + OUTAGE_GRACE
        self.verify_states("after an HA restart", OUTAGE_DEADLINE)
        print(
            f"  HA restart: API in {ready:.1f}s, retained set complete in {took if took is None else round(took, 1)}s",
            flush=True,
        )

    def restart_broker(self) -> None:
        """Restart the broker; the devices reconnect and Home Assistant republishes."""
        started = now()
        subprocess.run(
            ["podman", "restart", harness.rig.MQTT_NAME],
            capture_output=True,
            check=True,
        )
        self.counts["broker_restarts"] += 1
        took = self.resync_complete(started)
        if took is not None:
            self.latency["broker_resync"].append(took)
        for double in self.doubles:
            # A device's availability is write-only under the ACL: ask HA.
            end = now() + 30
            while now() < end and self.ha.presence(double.device_id) != "home":
                time.sleep(1)
            if self.ha.presence(double.device_id) != "home":
                self.fail(f"{double.device_id}: not home after a broker restart")
        # A change after the restart must still arrive.
        self.grace_until = now() + OUTAGE_GRACE
        self.ha_change()
        self.verify_states("after a broker restart", OUTAGE_DEADLINE)
        print(
            f"  broker restart: retained set complete in {took if took is None else round(took, 1)}s",
            flush=True,
        )

    # --- checks --------------------------------------------------------------

    def expected_text(self, entity_id: str) -> str:
        state = self.ha.state(entity_id)["state"]
        if entity_id.startswith("input_boolean"):
            return "On" if state == "on" else "Off"
        return str(int(float(state)))

    def verify_states(self, when: str, settle: float = 3.0) -> None:
        """Every published tile's last state message must agree with Home Assistant.

        Updates that wait for a reconnect get `settle` seconds to arrive.
        """
        end = now() + settle
        while now() < end and not self.consistent():
            time.sleep(1)
        for double in self.doubles:
            if self.held[double.device_id]:
                pass  # the device keeps showing the last good view; its tiles are still published
            for entity in sorted(set(self.tiles[double.device_id])):
                latest = double.latest(f"state/{entity}")
                want = self.expected_text(entity)
                self.counts["state_checks"] += 1
                if not isinstance(latest, dict) or latest["text"] != want:
                    self.fail(
                        f"{double.device_id}: {entity} reads {latest and latest.get('text')!r}, Home Assistant says {want!r} ({when})"
                    )
            if double.latest("meta") is None or double.latest("views") is None:
                self.fail(f"{double.device_id}: meta or views missing ({when})")

    def consistent(self) -> bool:
        """Whether every published tile's last state message agrees with Home Assistant."""
        for double in self.doubles:
            for entity in set(self.tiles[double.device_id]):
                latest = double.latest(f"state/{entity}")
                if not isinstance(latest, dict) or latest["text"] != self.expected_text(
                    entity
                ):
                    return False
        return True

    def log_check(self) -> dict[str, int]:
        """Count blocking-call warnings and Roundhouse errors in the Home Assistant log."""
        text = subprocess.run(
            ["podman", "logs", harness.rig.HA_NAME], capture_output=True, text=True
        ).stdout
        text += subprocess.run(
            ["podman", "logs", harness.rig.HA_NAME], capture_output=True, text=True
        ).stderr
        blocking = sum("Detected blocking call" in line for line in text.splitlines())
        errors = [
            line
            for line in text.splitlines()
            if "ERROR" in line and "roundhouse" in line.lower()
        ]
        for line in errors[:5]:
            print("LOG:", line[:200])
        return {"blocking_calls": blocking, "roundhouse_errors": len(errors)}

    # --- the run -------------------------------------------------------------

    def run(
        self,
        minutes: float,
        interval: float,
        ha_every: float,
        broker_every: float,
        alert_every: float,
    ) -> None:
        """Run the workload for `minutes`."""
        end = now() + minutes * 60
        next_ha, next_broker, next_alert = (
            now() + ha_every * 60,
            now() + broker_every * 60,
            now() + alert_every * 60,
        )
        next_edit, next_overflow, cycle = now() + 60, now() + 150, 0
        while now() < end:
            cycle += 1
            try:
                step = self.random.random()
                (self.ha_change if step < 0.55 else self.device_command)()
                if now() >= next_edit:
                    self.edit_views()
                    next_edit = now() + self.random.uniform(60, 180)
                if now() >= next_overflow:
                    self.edit_views(overflow=True)
                    self.edit_views()  # and back to something that fits
                    next_overflow = now() + self.random.uniform(300, 900)
                if now() >= next_alert:
                    self.alert()
                    next_alert = now() + alert_every * 60
                if now() >= next_ha:
                    next_ha = now() + ha_every * 60
                    self.restart_ha()
                if now() >= next_broker:
                    next_broker = now() + broker_every * 60
                    self.restart_broker()
            except Exception as err:  # a harness error must not hide the run
                self.fail(f"harness error: {type(err).__name__}: {err}")
            if cycle % 20 == 0:
                print(
                    f"[{round(minutes * 60 - (end - now()))}s] cycles={cycle} failures={len(self.failures)} {self.counts}",
                    flush=True,
                )
            time.sleep(interval)

    def report(self, minutes: float) -> dict[str, Any]:
        """Final checks, then the report."""
        self.verify_states("at the end")
        log = self.log_check()
        if log["blocking_calls"]:
            self.fail(
                f"{log['blocking_calls']} blocking-call warning(s) in the Home Assistant log"
            )
        if log["roundhouse_errors"]:
            self.fail(
                f"{log['roundhouse_errors']} Roundhouse error(s) in the Home Assistant log"
            )
        result = {
            "minutes": minutes,
            "passed": not self.failures,
            "failures": self.failures[:50],
            "counts": self.counts,
            "latency_ms": {k: stats(v) for k, v in self.latency.items()},
            "log": log,
            "host": harness.host_description(),
        }
        harness.SOAK_DIR.mkdir(parents=True, exist_ok=True)
        (harness.SOAK_DIR / "report.json").write_text(json.dumps(result, indent=2))
        return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument(
        "--interval", type=float, default=4.0, help="seconds between workload steps"
    )
    parser.add_argument("--ha-restart-every", type=float, default=30, help="minutes")
    parser.add_argument(
        "--broker-restart-every", type=float, default=45, help="minutes"
    )
    parser.add_argument("--alert-every", type=float, default=10, help="minutes")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--keep", action="store_true", help="leave the containers running"
    )
    args = parser.parse_args()
    images = harness.ImageServer()
    ha, doubles = harness.setup(DEVICES)
    soak = Soak(ha, doubles, args.seed)
    soak.verify_states("at the start")
    try:
        soak.run(
            args.minutes,
            args.interval,
            args.ha_restart_every,
            args.broker_restart_every,
            args.alert_every,
        )
        result = soak.report(args.minutes)
    finally:
        for double in doubles:
            double.stop()
        images.stop()
        if not args.keep:
            harness.rig.down()
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("passed", "failures", "counts", "latency_ms", "log")
            },
            indent=2,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
