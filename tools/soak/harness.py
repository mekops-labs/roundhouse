"""Shared pieces of the soak and the measurements: instance, doubles, HA client."""

from __future__ import annotations

import http.server
import io
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SOAK_DIR = Path(os.environ.get("SOAK_DIR", Path.home() / ".cache/roundhouse-dev/soak"))
os.environ.setdefault("RIG_DIR", str(SOAK_DIR))
os.environ.setdefault("RIG_PREFIX", "rhs")
os.environ.setdefault("RIG_HA_PORT", "18124")
os.environ.setdefault("RIG_MQTT_PORT", "18831")
os.environ["RIG_ACL"] = "1"
sys.path.insert(0, str(REPO / "tools" / "rig"))

import paho.mqtt.client as mqtt  # noqa: E402
import rig  # noqa: E402

_REFRESH = rig.access  # the rig's own token refresh, before Ha replaces it

PROFILES = {"tender": "tender", "wall": "wall-panel"}
IMAGE_PORT = 18899
IMAGE_URL = f"http://host.containers.internal:{IMAGE_PORT}/snap.png"
LAMPS = [f"input_boolean.lamp{i}" for i in range(1, 7)]
LEVELS = [f"input_number.level{i}" for i in range(1, 4)]
POOL = LAMPS + LEVELS


def now() -> float:
    return time.perf_counter()


def stats(values: list[float]) -> dict[str, float]:
    """Summarize latencies in milliseconds."""
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "n": len(values),
        "p50": round(statistics.median(ordered) * 1000, 1),
        "p95": round(p95 * 1000, 1),
        "max": round(ordered[-1] * 1000, 1),
    }


class Ha:
    """A small Home Assistant client with a cached token."""

    def __init__(self) -> None:
        """Initialize without a token."""
        self._token = ""
        self._until = 0.0
        rig.access = self.token  # type: ignore[assignment]

    def token(self) -> str:
        """Return an access token, refreshed every 20 minutes."""
        if time.time() > self._until:
            self._token = _REFRESH()
            self._until = time.time() + 1200
        return self._token

    def state(self, entity_id: str) -> dict[str, Any]:
        """Return an entity's state object."""
        return rig.http("GET", f"/api/states/{entity_id}", None, self.token())  # type: ignore[return-value]

    def call(
        self, domain: str, service: str, data: dict[str, Any], response: bool = False
    ) -> Any:
        """Call a service."""
        suffix = "?return_response" if response else ""
        return rig.http(
            "POST", f"/api/services/{domain}/{service}{suffix}", data, self.token()
        )

    def ws(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Send websocket commands on a fresh connection."""
        import asyncio

        return asyncio.run(rig.ws_call(messages))  # type: ignore[arg-type,return-value]

    def save_dashboard(self, slug: str, views: list[dict[str, Any]]) -> None:
        """Save a dashboard's config."""
        result = self.ws(
            [
                {
                    "type": "lovelace/config/save",
                    "url_path": slug,
                    "config": {"views": views},
                }
            ]
        )
        assert result[0].get("success"), result

    def wait_ready(self, timeout: float = 240) -> float:
        """Wait until Home Assistant reports it is running; return the time it took."""
        started = now()
        while now() - started < timeout:
            try:
                config = rig.http("GET", "/api/config", None, self.token())
                if isinstance(config, dict) and config.get("state") == "RUNNING":
                    return now() - started
            except (SystemExit, OSError):
                pass
            time.sleep(1)
        raise TimeoutError("Home Assistant did not come back")

    def presence(self, device_id: str) -> str | None:
        """Return the state of a device's presence tracker."""
        states = rig.http("GET", "/api/states", None, self.token())
        for item in states:  # type: ignore[union-attr]
            if item["entity_id"].startswith("device_tracker.") and item[
                "entity_id"
            ].endswith(device_id):
                return str(item["state"])
        return None


class Double:
    """A device double: a broker login, a retained announce, and a record of what it sees."""

    def __init__(self, device_id: str, profile: str) -> None:
        """Initialize the double for a profile name (`tender` or `wall`)."""
        self.device_id = device_id
        self.prefix = f"roundhouse/{device_id}"
        path = REPO / f"contract/vectors/v1.0/announce/{PROFILES[profile]}.json"
        self.profile = json.loads(path.read_text())["payload"]
        self.capacity = len(self.profile["layouts"][-1]["slots"])
        self.cond = threading.Condition()
        self.history: dict[str, list[tuple[float, bytes, bool]]] = {}
        self.connects = 0
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"double-{device_id}"
        )
        self.client.username_pw_set(device_id, rig.credentials()[device_id])
        self.client.will_set(
            f"{self.prefix}/availability", "offline", qos=1, retain=True
        )
        self.client.reconnect_delay_set(1, 5)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self._req = 0

    def _on_connect(self, client: mqtt.Client, *_: object) -> None:
        self.connects += 1
        client.subscribe(f"{self.prefix}/#", qos=1)
        client.publish(
            f"{self.prefix}/announce", json.dumps(self.profile), qos=1, retain=True
        )
        client.publish(
            f"{self.prefix}/status",
            json.dumps(
                {
                    "battery": 80,
                    "charging": False,
                    "power_mode": "sleep"
                    if "sleep" in self.profile["features"]
                    else "active",
                }
            ),
            qos=1,
            retain=True,
        )
        client.publish(f"{self.prefix}/availability", "online", qos=1, retain=True)

    def _on_message(self, _c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        suffix = msg.topic.removeprefix(self.prefix + "/")
        with self.cond:
            self.history.setdefault(suffix, []).append(
                (now(), bytes(msg.payload), msg.retain)
            )
            if len(self.history[suffix]) > 400:
                del self.history[suffix][:200]
            self.cond.notify_all()

    def start(self) -> None:
        """Connect and keep the connection (it reconnects after a broker restart)."""
        self.client.connect("127.0.0.1", rig.MQTT_PORT)
        self.client.loop_start()
        end = now() + 20
        while self.connects == 0 and now() < end:
            time.sleep(0.1)
        if self.connects == 0:
            raise TimeoutError(f"{self.device_id} could not connect")

    def stop(self) -> None:
        """Go offline cleanly."""
        self.client.publish(
            f"{self.prefix}/availability", "offline", qos=1, retain=True
        ).wait_for_publish()
        self.client.loop_stop()

    def wait(
        self, suffix: str, predicate: Any, since: float, timeout: float
    ) -> tuple[float, Any] | None:
        """Wait for a message on `suffix` after `since`; return (arrival time, decoded body)."""
        end = now() + timeout
        with self.cond:
            while True:
                for t, payload, _retain in self.history.get(suffix, []):
                    if t >= since:
                        body = (
                            payload.decode()
                            if suffix in ("availability",)
                            else _decode(payload)
                        )
                        if predicate(body):
                            return t, body
                left = end - now()
                if left <= 0:
                    return None
                self.cond.wait(left)

    def latest(self, suffix: str) -> Any:
        """Return the last decoded message on `suffix`, or None."""
        with self.cond:
            items = self.history.get(suffix, [])
            return _decode(items[-1][1]) if items else None

    def command(
        self, body: dict[str, Any], timeout: float = 15
    ) -> tuple[str | None, float]:
        """Send a command; return (result, seconds to the result)."""
        self._req += 1
        req = f"{self.device_id}-{self._req}-{int(time.time())}"
        started = now()
        self.client.publish(
            f"{self.prefix}/cmd", json.dumps({"req": req, **body}), qos=1
        )
        got = self.wait(
            "result",
            lambda b: isinstance(b, dict) and b.get("req") == req,
            started,
            timeout,
        )
        return (got[1]["result"], got[0] - started) if got else (None, timeout)


def _decode(payload: bytes) -> Any:
    try:
        return json.loads(payload)
    except ValueError:
        return payload


class ImageServer:
    """Serves a small PNG for alert snapshots."""

    def __init__(self) -> None:
        """Start the server on a background thread."""
        from PIL import Image

        buf = io.BytesIO()
        Image.linear_gradient("L").resize((640, 360)).convert("RGB").save(buf, "PNG")
        body = buf.getvalue()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("0.0.0.0", IMAGE_PORT), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        """Stop serving."""
        self.server.shutdown()


def setup(devices: list[tuple[str, str, str]]) -> tuple[Ha, list[Double]]:
    """Start the instance, onboard it, and bring the doubles online and set up.

    `devices` is (device_id, profile name, dashboard slug).
    """
    rig.up("en")
    rig.onboard()
    ha = Ha()
    doubles = [Double(device_id, profile) for device_id, profile, _slug in devices]
    for double in doubles:
        double.start()
    time.sleep(4)
    for device_id, _profile, slug in devices:
        rig.confirm(slug, device_id)
    time.sleep(3)
    started = now()
    for _device_id, _profile, slug in devices:
        ha.save_dashboard(
            slug,
            [
                {
                    "path": "home",
                    "title": "Home",
                    "cards": [{"type": "tile", "entity": e} for e in POOL[:5]],
                }
            ],
        )
    for (
        double
    ) in doubles:  # the first digest waits 2 s; start only once everything is out
        for suffix in ["views"] + [f"state/{e}" for e in POOL[:5]]:
            if double.wait(suffix, lambda b: True, started, 30) is None:
                raise TimeoutError(f"{double.device_id}: no {suffix} after setup")
    return ha, doubles


def host_description() -> dict[str, str]:
    """Describe the machine, for the record."""
    import platform

    cpu = next(
        (
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        ),
        "unknown",
    )
    mem = next(
        (
            int(line.split()[1]) // 1024
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemTotal")
        ),
        0,
    )
    ha_version = subprocess.run(
        [
            "podman",
            "exec",
            rig.HA_NAME,
            "python3",
            "-c",
            "import homeassistant.const as c;print(c.__version__)",
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "cpu": cpu,
        "memory_mb": str(mem),
        "kernel": platform.release(),
        "home_assistant": ha_version,
        "containers": "Podman, Mosquitto 2 and Home Assistant stable on one host",
    }
