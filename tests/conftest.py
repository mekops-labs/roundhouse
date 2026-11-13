"""Shared fixtures."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from custom_components.roundhouse import icons, images
from custom_components.roundhouse.const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_PROFILE,
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


def announce(
    hass: HomeAssistant, device_id: str, payload: dict[str, Any] | bytes
) -> None:
    """Deliver a live announce.

    A broker forwards a live message to a subscriber with the retain flag
    clear; Home Assistant drops a second retained message on a topic.
    """
    body = payload if isinstance(payload, bytes) else json.dumps(payload)
    async_fire_mqtt_message(hass, f"roundhouse/{device_id}/announce", body)


def make_entry(profile: dict[str, Any], device_id: str = "tender01") -> MockConfigEntry:
    """Build a configured entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=device_id,
        title=f"{profile['model'].capitalize()} {device_id}",
        data={
            CONF_DEVICE_ID: device_id,
            CONF_MODEL: profile["model"],
            CONF_PROFILE: profile,
        },
    )


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow the MQTT client's own periodic timer, which a mocked client leaves."""
    return True


def _outside_the_loop(name: str, func: Any, cold: Any = None) -> Any:
    """Wrap `func` so a call on the event loop thread fails the test."""

    def guarded(*args: Any, **kwargs: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return func(*args, **kwargs)
        if cold is None or cold():
            raise AssertionError(f"{name} ran in the event loop")
        return func(*args, **kwargs)

    guarded.__name__ = name
    return guarded


@pytest.fixture(autouse=True)
def no_blocking_calls(
    request: pytest.FixtureRequest,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Fail a test that rasterizes, dithers, or loads icon data in the event loop.

    Home Assistant only reports file I/O in the loop in a real run, so the
    heavy functions are wrapped here. Home Assistant's own report fails the
    test too.
    """
    for module, names in ((icons, ("mask", "warm")), (images, ("encode", "_open"))):
        for name in names:
            monkeypatch.setattr(
                module, name, _outside_the_loop(name, getattr(module, name))
            )
    names = icons._names
    names.cache_clear()  # every test starts cold, so a missing warm-up is caught
    monkeypatch.setattr(
        icons,
        "_names",
        _outside_the_loop(
            "_names", names, cold=lambda: names.cache_info().currsize == 0
        ),
    )
    yield
    hits = [
        r.getMessage()
        for r in caplog.records
        if "Detected blocking call" in r.getMessage()
    ]
    assert not hits, hits
