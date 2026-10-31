"""Shared fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.roundhouse.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_PROFILE,
    CONF_SLUG,
    DOMAIN,
)

VECTORS = Path(__file__).parents[1] / "contract/vectors/v1.0"


def vector(kind: str, name: str) -> dict[str, Any]:
    """Load one contract vector."""
    return json.loads((VECTORS / kind / f"{name}.json").read_text())  # type: ignore[no-any-return]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let HA load custom_components/ in every test."""


@pytest.fixture
def tender_profile() -> dict[str, Any]:
    """The Tender announce payload."""
    return vector("announce", "tender")["payload"]  # type: ignore[no-any-return]


@pytest.fixture
async def lovelace(hass: HomeAssistant) -> None:
    """Set up Lovelace the way a real instance has it."""
    hass.config.components.update(
        {"http", "auth", "onboarding", "websocket_api", "frontend", "api"}
    )
    assert await async_setup_component(hass, "lovelace", {})


def announce(
    hass: HomeAssistant, device_id: str, payload: dict[str, Any] | bytes
) -> None:
    """Deliver a live announce.

    A broker forwards a live message to a subscriber with the retain flag
    clear; Home Assistant drops a second retained message on a topic.
    """
    body = payload if isinstance(payload, bytes) else json.dumps(payload)
    async_fire_mqtt_message(hass, f"roundhouse/{device_id}/announce", body)


def make_entry(
    profile: dict[str, Any], device_id: str = "tender01", slug: str = "tender-panel"
) -> MockConfigEntry:
    """Build a configured entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=device_id,
        data={
            CONF_DEVICE_ID: device_id,
            CONF_MODEL: profile["model"],
            CONF_SLUG: slug,
            CONF_PROFILE: profile,
        },
    )


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow the MQTT client's own periodic timer, which a mocked client leaves."""
    return True
