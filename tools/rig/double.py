"""A device double: announces a panel profile and stays online, as a real device would.

    double.py tender|wall [--id tender01] [--seconds 600]

It publishes the retained announce, availability (with a last will), and status,
and logs every message the integration publishes for it to RIG_DIR/double.log.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import paho.mqtt.client as mqtt

REPO = Path(__file__).resolve().parents[2]
RIG = Path(os.environ.get("RIG_DIR", Path.home() / ".cache/roundhouse-dev/rig"))
PROFILES = {"tender": "tender", "wall": "wall-panel"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=PROFILES)
    parser.add_argument("--id", default=None)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("RIG_MQTT_PORT", 18830))
    )
    parser.add_argument("--password", default=os.environ.get("RIG_DEVICE_PASSWORD"))
    args = parser.parse_args()
    device_id = args.id or ("tender01" if args.profile == "tender" else "wall01")
    path = REPO / f"contract/vectors/v1.0/announce/{PROFILES[args.profile]}.json"
    profile = json.loads(path.read_text())["payload"]
    log = (RIG / "double.log").open("a")

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id=f"double-{device_id}"
    )
    prefix = f"roundhouse/{device_id}"
    if args.password:  # broker login: the user name is the device ID
        client.username_pw_set(device_id, args.password)
    client.will_set(f"{prefix}/availability", "offline", qos=1, retain=True)

    def on_connect(c: mqtt.Client, *_: object) -> None:
        c.subscribe(f"{prefix}/#", qos=1)
        c.publish(f"{prefix}/announce", json.dumps(profile), qos=1, retain=True)
        c.publish(
            f"{prefix}/status",
            json.dumps({"battery": 82, "charging": False, "power_mode": "sleep"}),
            qos=1,
            retain=True,
        )
        c.publish(f"{prefix}/availability", "online", qos=1, retain=True)

    def on_message(_c: mqtt.Client, _u: object, msg: mqtt.MQTTMessage) -> None:
        body = (
            msg.payload[:80]
            if len(msg.payload) < 4000
            else f"<{len(msg.payload)} bytes>"
        )
        log.write(
            f"{time.strftime('%H:%M:%S')} {msg.topic} retain={msg.retain} {body}\n"
        )
        log.flush()

    client.on_connect, client.on_message = on_connect, on_message
    client.connect("127.0.0.1", args.port)
    client.loop_start()
    time.sleep(args.seconds)
    client.publish(
        f"{prefix}/availability", "offline", qos=1, retain=True
    ).wait_for_publish()
    client.loop_stop()


if __name__ == "__main__":
    main()
