"""The manifest declares what discovery and setup rely on."""

import json
from pathlib import Path

MANIFEST = Path(__file__).parents[1] / "custom_components/roundhouse/manifest.json"


def test_manifest_subscribes_to_announce() -> None:
    assert json.loads(MANIFEST.read_text())["mqtt"] == ["roundhouse/+/announce"]


def test_manifest_depends_on_mqtt_and_orders_after_the_frontend() -> None:
    manifest = json.loads(MANIFEST.read_text())
    assert "mqtt" in manifest["dependencies"]
    assert "lovelace" not in manifest["dependencies"]
    assert {"frontend", "http", "panel_custom"} <= set(manifest["after_dependencies"])
