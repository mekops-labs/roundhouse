"""A throwaway Home Assistant and broker in Podman, to try the integration by hand.

All state lives under RIG_DIR (default ~/.cache/roundhouse-dev/rig), outside the
repository. Nothing here is used by the tests or shipped to users.

    rig.py up         start Mosquitto and Home Assistant, wait until it answers
    rig.py onboard    create the owner, the token, and the MQTT integration
    rig.py confirm    accept the discovered device and create its dashboard
    rig.py seed       set demo states and fill the dashboard of a device
    rig.py shot       screenshot the Roundhouse panel
    rig.py logs       print the Home Assistant log, filtered to Roundhouse
    rig.py down       remove both containers (the state stays)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import aiohttp

REPO = Path(__file__).resolve().parents[2]
RIG = Path(os.environ.get("RIG_DIR", Path.home() / ".cache/roundhouse-dev/rig"))
# A second instance (the soak) runs beside the first with another prefix and ports.
PREFIX = os.environ.get("RIG_PREFIX", "rh")
HA_PORT = int(os.environ.get("RIG_HA_PORT", 18123))
MQTT_PORT = int(os.environ.get("RIG_MQTT_PORT", 18830))
HA_NAME, MQTT_NAME = f"{PREFIX}-ha", f"{PREFIX}-mqtt"
# With RIG_ACL=1 the broker needs a login and applies the documented ACL.
ACL = os.environ.get("RIG_ACL") == "1"
# Broker logins; `credentials()` generates their passwords.
BROKER_USERS = ("homeassistant", "tender01", "tender02", "wall01")
BASE = f"http://127.0.0.1:{HA_PORT}"
CLIENT = f"{BASE}/"
HA_IMAGE = "ghcr.io/home-assistant/home-assistant:stable"
MQTT_IMAGE = "docker.io/library/eclipse-mosquitto:2"
NET = f"{PREFIX}dev"
# The Playwright container image and the matching Python package.
PLAYWRIGHT = "1.64.1"
OWNER = {"name": "Rig", "username": "rig"}


def credentials() -> dict[str, str]:
    """Return the rig's passwords, generated once into RIG/credentials.json.

    Keys are the broker users and `owner`, the Home Assistant owner.
    """
    path = RIG / "credentials.json"
    stored = json.loads(path.read_text()) if path.exists() else {}
    wanted = [*BROKER_USERS, "owner"]
    if any(name not in stored for name in wanted):
        for name in wanted:
            stored.setdefault(name, secrets.token_urlsafe(16))
        RIG.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600)
        path.write_text(json.dumps(stored, indent=2) + "\n")
    return {name: str(stored[name]) for name in wanted}


CONFIGURATION = """\
default_config:
homeassistant:
  name: Rig
  latitude: 52.2
  longitude: 21.0
  elevation: 100
  unit_system: metric
  time_zone: Europe/Warsaw
  language: {language}
input_boolean:
  lamp1: {{name: Lamp 1}}
  lamp2: {{name: Lamp 2}}
  lamp3: {{name: Lamp 3}}
  lamp4: {{name: Lamp 4}}
  lamp5: {{name: Lamp 5}}
  lamp6: {{name: Lamp 6}}
input_number:
  level1: {{name: Level 1, min: 0, max: 100, step: 1}}
  level2: {{name: Level 2, min: 0, max: 100, step: 1}}
  level3: {{name: Level 3, min: 0, max: 100, step: 1}}
logger:
  default: info
  logs:
    custom_components.roundhouse: debug
"""

MOSQUITTO = "listener 1883\nallow_anonymous true\npersistence true\npersistence_location /mosquitto/data/\n"
MOSQUITTO_ACL = (
    "listener 1883\nallow_anonymous false\npassword_file /mosquitto/config/passwd\n"
    "acl_file /mosquitto/config/acl\npersistence true\npersistence_location /mosquitto/data/\n"
)
# The ACL of docs/install.md: each device is a broker user named after its device ID.
ACL_FILE = (
    (REPO / "docs" / "mosquitto-acl.example").read_text()
    if (REPO / "docs" / "mosquitto-acl.example").exists()
    else ""
)


def podman(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["podman", *args], check=check, capture_output=True, text=True
    )


def up(language: str) -> None:
    (RIG / "config").mkdir(parents=True, exist_ok=True)
    (RIG / "mosquitto/config").mkdir(parents=True, exist_ok=True)
    (RIG / "mosquitto/data").mkdir(parents=True, exist_ok=True)
    (RIG / "mosquitto/config/mosquitto.conf").write_text(
        MOSQUITTO_ACL if ACL else MOSQUITTO
    )
    if ACL:
        (RIG / "mosquitto/config/acl").write_text(ACL_FILE)
        passwords = credentials()
        commands = [
            f"mosquitto_passwd -b {'-c ' if i == 0 else ''}/mosquitto/config/passwd {user} {passwords[user]}"
            for i, user in enumerate(BROKER_USERS)
        ]
        podman(
            "run",
            "--rm",
            "--security-opt",
            "label=disable",
            "-v",
            f"{RIG}/mosquitto/config:/mosquitto/config",
            MQTT_IMAGE,
            "sh",
            "-c",
            " && ".join(
                [
                    *commands,
                    "chown 1883:1883 /mosquitto/config/passwd /mosquitto/config/acl",
                    "chmod 0600 /mosquitto/config/passwd",
                ]
            ),
        )
    conf = RIG / "config/configuration.yaml"
    if not conf.exists():
        conf.write_text(CONFIGURATION.format(language=language))
    podman("rm", "-f", HA_NAME, MQTT_NAME, check=False)  # `up` can be run again
    podman("network", "create", NET, check=False)
    podman(
        "run",
        "-d",
        "--name",
        MQTT_NAME,
        "--network",
        NET,
        "-p",
        f"127.0.0.1:{MQTT_PORT}:1883",
        "--security-opt",
        "label=disable",
        "-v",
        f"{RIG}/mosquitto/config:/mosquitto/config",
        "-v",
        f"{RIG}/mosquitto/data:/mosquitto/data",
        MQTT_IMAGE,
        "mosquitto",
        "-c",
        "/mosquitto/config/mosquitto.conf",
    )
    podman(
        "run",
        "-d",
        "--name",
        HA_NAME,
        "--network",
        NET,
        "-p",
        f"127.0.0.1:{HA_PORT}:8123",
        "--security-opt",
        "label=disable",
        "-v",
        f"{RIG}/config:/config",
        "-v",
        f"{REPO}/custom_components/roundhouse:/config/custom_components/roundhouse:ro",
        HA_IMAGE,
    )
    print("waiting for Home Assistant", end="", flush=True)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"{BASE}/api/onboarding", timeout=2).read()
            print(" up")
            return
        except urllib.error.HTTPError:  # a 404 after onboarding still means it answers
            print(" up")
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            print(".", end="", flush=True)
            time.sleep(3)
    sys.exit(f"Home Assistant did not start; see: podman logs {HA_NAME}")


def down() -> None:
    podman("rm", "-f", HA_NAME, MQTT_NAME, check=False)
    print("removed")


def http(
    method: str,
    path: str,
    body: object = None,
    token: str | None = None,
    form: bool = False,
) -> object:
    data = None
    headers = {}
    if body is not None:
        data = (
            urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        )
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as err:
        sys.exit(f"{method} {path}: {err.code} {err.read().decode()[:300]}")
    return json.loads(raw) if raw else None


def tokens() -> dict[str, object]:
    return json.loads((RIG / "tokens.json").read_text())  # type: ignore[no-any-return]


def access() -> str:
    """Return a fresh access token."""
    saved = tokens()
    reply = http(
        "POST",
        "/auth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": saved["refresh_token"],
            "client_id": CLIENT,
        },
        form=True,
    )
    assert isinstance(reply, dict)
    return str(reply["access_token"])


def onboard() -> None:
    """Create the owner and the MQTT integration; safe to run again."""
    try:
        status = http("GET", "/api/onboarding")
    except SystemExit:  # the endpoint is gone once onboarding is complete
        status = []
    assert isinstance(status, list)
    if any(s["step"] == "user" and not s["done"] for s in status):
        reply = http(
            "POST",
            "/api/onboarding/users",
            {
                "client_id": CLIENT,
                "language": "en",
                **OWNER,
                "password": credentials()["owner"],
            },
        )
        assert isinstance(reply, dict)
        auth = http(
            "POST",
            "/auth/token",
            {
                "grant_type": "authorization_code",
                "code": reply["auth_code"],
                "client_id": CLIENT,
            },
            form=True,
        )
        assert isinstance(auth, dict)
        (RIG / "tokens.json").write_text(json.dumps(auth))
    token = access()
    for step, body in (
        ("core_config", {}),
        ("analytics", {}),
        ("integration", {"client_id": CLIENT, "redirect_uri": CLIENT}),
    ):
        if any(s["step"] == step and not s["done"] for s in status):
            http("POST", f"/api/onboarding/{step}", body, token)
    entries = asyncio.run(ws_call([{"type": "config_entries/get", "domain": "mqtt"}]))[
        0
    ]
    if entries.get("result"):
        print("mqtt: already set up")
        return
    flow = http(
        "POST",
        "/api/config/config_entries/flow",
        {"handler": "mqtt", "show_advanced_options": False},
        token,
    )
    assert isinstance(flow, dict)
    if flow.get("type") == "form":
        flow = http(
            "POST",
            f"/api/config/config_entries/flow/{flow['flow_id']}",
            {
                "broker": MQTT_NAME,
                "port": 1883,
                "protocol": "5",
                **(
                    {
                        "username": "homeassistant",
                        "password": credentials()["homeassistant"],
                    }
                    if ACL
                    else {}
                ),
                "other_settings": {
                    "set_ca_cert": "off",
                    "set_client_cert": False,
                    "client_id": "",
                },
            },
            token,
        )
    print("mqtt:", flow.get("type") if isinstance(flow, dict) else flow)


async def ws_call(messages: list[dict[str, object]]) -> list[dict[str, object]]:
    results = []
    async with (
        aiohttp.ClientSession() as session,
        session.ws_connect(f"{BASE}/api/websocket") as ws,
    ):
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": access()})
        assert (await ws.receive_json())["type"] == "auth_ok"
        for i, message in enumerate(messages, 1):
            await ws.send_json({"id": i, **message})
            results.append(await ws.receive_json())
    return results


def seed(slug: str, scenario: str) -> None:
    token = access()
    states = {
        "light.ceiling": (
            "on",
            {
                "friendly_name": "Ceiling",
                "brightness": 204,
                "rgb_color": [255, 180, 80],
            },
        ),
        "light.desk": ("off", {"friendly_name": "Desk lamp"}),
        "switch.pump": ("on", {"friendly_name": "Pump"}),
        "lock.door": ("locked", {"friendly_name": "Front door"}),
        "cover.gate": ("open", {"friendly_name": "Gate", "current_position": 40}),
        "climate.heatpump": (
            "heat",
            {
                "friendly_name": "Heat pump",
                "hvac_action": "heating",
                "current_temperature": 21.5,
                "temperature": 22,
                "hvac_modes": ["heat", "off"],
                "min_temp": 7,
                "max_temp": 30,
            },
        ),
        "sensor.outdoor": (
            "3.456",
            {"friendly_name": "Outdoor", "unit_of_measurement": "°C"},
        ),
        "binary_sensor.motion": (
            "on",
            {"friendly_name": "Hall motion", "device_class": "motion"},
        ),
        "scene.evening": ("unknown", {"friendly_name": "Evening"}),
    }
    for i in range(1, 12):
        states[f"light.extra{i}"] = (
            "on" if i % 2 else "off",
            {"friendly_name": f"Extra {i}"},
        )
    for entity_id, (state, attrs) in states.items():
        http(
            "POST",
            f"/api/states/{entity_id}",
            {"state": state, "attributes": attrs},
            token,
        )
    base = [
        "light.ceiling",
        "light.desk",
        "switch.pump",
        "lock.door",
        "cover.gate",
        "climate.heatpump",
        "sensor.outdoor",
        "binary_sensor.motion",
        "scene.evening",
    ]
    extras = [f"light.extra{i}" for i in range(1, 12)]
    views = {
        "fit": [
            {
                "path": "home",
                "title": "Home",
                "cards": [{"type": "tile", "entity": e} for e in base],
            }
        ],
        "overflow": [
            {
                "path": "home",
                "title": "Home",
                "cards": [{"type": "tile", "entity": e} for e in base[:5]],
            },
            {
                "path": "all",
                "title": "Everything",
                "cards": [{"type": "tile", "entity": e} for e in base + extras],
            },
        ],
    }[scenario]
    result = asyncio.run(
        ws_call(
            [
                {
                    "type": "lovelace/config/save",
                    "url_path": slug,
                    "config": {"views": views},
                }
            ]
        )
    )
    print("save:", result[0].get("success"), result[0].get("error", ""))


def screenshot(
    out: Path, wait: int = 7000, poke: str = "", after: int = 500, device: str = ""
) -> None:
    """Run tools/rig/shot.py in Playwright's container (the host lacks browser libraries)."""
    saved = tokens()
    stored = {
        "access_token": access(),
        "token_type": "Bearer",
        "expires_in": 1800,
        "hassUrl": BASE,
        "clientId": CLIENT,
        "expires": int(time.time() * 1000) + 1_700_000,
        "refresh_token": saved["refresh_token"],
    }
    (RIG / "browser-tokens.json").write_text(json.dumps(stored))
    version = PLAYWRIGHT
    result = podman(
        "run",
        "--rm",
        "--network",
        "host",
        "--security-opt",
        "label=disable",
        "-v",
        f"{RIG}:/rig",
        "-v",
        f"{REPO}/tools/rig:/tools:ro",
        f"mcr.microsoft.com/playwright/python:v{version}-noble",
        "bash",
        "-c",
        f"pip install -q --break-system-packages playwright=={version} 2>&1 | tail -1;"
        f" python3 /tools/shot.py --base {BASE} --out /rig/{out.name}"
        f" --wait {wait} --after {after}"
        + (f" --poke '{poke}'" if poke else "")
        + (f" --device {device}" if device else ""),
        check=False,
    )
    print(result.stdout, result.stderr[-1500:] if result.returncode else "")


def confirm(slug: str, device_id: str | None = None) -> None:
    """Confirm every pending Roundhouse discovery with this dashboard slug."""
    token = access()
    flows = asyncio.run(ws_call([{"type": "config_entries/flow/progress"}]))[0][
        "result"
    ]
    for flow in flows:  # type: ignore[attr-defined,union-attr]
        if flow["handler"] == "roundhouse" and device_id in (
            None,
            flow["context"]["unique_id"],
        ):
            reply = http(
                "POST",
                f"/api/config/config_entries/flow/{flow['flow_id']}",
                {"slug": slug},
                token,
            )
            print(
                flow["context"]["unique_id"],
                "->",
                reply.get("type"),
                reply.get("data", {}).get("slug"),
            )  # type: ignore[union-attr]


def logs() -> None:
    out = podman("logs", HA_NAME).stdout + podman("logs", HA_NAME).stderr
    for line in out.splitlines():
        if "roundhouse" in line.lower() or "ERROR" in line or "WARNING" in line:
            print(line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up").add_argument("--language", default="en")
    sub.add_parser("down")
    sub.add_parser("onboard")
    s = sub.add_parser("seed")
    s.add_argument("--slug", default="tender-panel")
    s.add_argument("--scenario", choices=("fit", "overflow"), default="fit")
    sh = sub.add_parser("shot")
    sh.add_argument("--out", default=str(RIG / "panel.png"))
    sh.add_argument("--poke", default="")
    sh.add_argument("--device", default="")
    sh.add_argument("--after", type=int, default=500)
    sub.add_parser("logs")
    c = sub.add_parser("confirm")
    c.add_argument("--slug", default="tender-panel")
    args = parser.parse_args()
    if args.cmd == "up":
        up(args.language)
    elif args.cmd == "down":
        down()
    elif args.cmd == "onboard":
        onboard()
    elif args.cmd == "seed":
        seed(args.slug, args.scenario)
    elif args.cmd == "shot":
        screenshot(Path(args.out), poke=args.poke, after=args.after, device=args.device)
    elif args.cmd == "confirm":
        confirm(args.slug)
    else:
        logs()


if __name__ == "__main__":
    main()
