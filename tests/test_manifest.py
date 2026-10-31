"""The manifest declares what discovery and setup rely on."""

import json
from pathlib import Path

MANIFEST = Path(__file__).parents[1] / "custom_components/roundhouse/manifest.json"


def test_manifest_subscribes_to_announce() -> None:
    assert json.loads(MANIFEST.read_text())["mqtt"] == ["roundhouse/+/announce"]


def test_manifest_depends_on_mqtt_and_lovelace() -> None:
    assert {"mqtt", "lovelace"} <= set(json.loads(MANIFEST.read_text())["dependencies"])
