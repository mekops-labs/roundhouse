"""Helpers shared by the integration tests: devices with stored views."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.roundhouse import layout
from custom_components.roundhouse.const import CONF_DEVICE_ID, DOMAIN, store_key
from custom_components.roundhouse.device import Device
from custom_components.roundhouse.viewsync import STORE_VERSION, SaveResult

from .conftest import make_entry

PREFIX = "roundhouse/tender01/"


def tiles(n: int, start: int = 0) -> list[dict[str, Any]]:
    """Return `n` light tiles, `light.l<start>` upward."""
    return [{"entity_id": f"light.l{i}"} for i in range(start, start + n)]


def cards(*entities: str, **icons: str) -> list[dict[str, Any]]:
    """Return a tile for each entity, with an icon override where given."""
    return [
        {"entity_id": e, **({"icon": icons[e]} if e in icons else {})} for e in entities
    ]


def config(
    *views: tuple[str, list[dict[str, Any]]], layout: int | None = None
) -> list[dict[str, Any]]:
    """Return views; a layout left out is chosen per profile by `resolve`."""
    return [
        {"path": p, "title": p.title(), "layout": layout, "tiles": t} for p, t in views
    ]


def resolve(
    profile: dict[str, Any], views: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Give each view without a layout the first one that holds its tiles."""
    out = []
    for view in views:
        index = view["layout"]
        if index is None:
            slots = [len(x["slots"]) for x in profile["layouts"]]
            fitting = [i for i, n in enumerate(slots) if n >= len(view["tiles"])]
            index = fitting[0] if fitting else layout.densest(profile)
        out.append({**view, "layout": index})
    return out


async def advance(hass: HomeAssistant, seconds: float) -> None:
    """Move the clock and let the work it starts finish."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done(wait_background_tasks=True)


def the_device(hass: HomeAssistant) -> Device:
    """Return the only set-up device."""
    [device] = [d for d in hass.data[DOMAIN].values() if isinstance(d, Device)]
    return device


async def save(
    hass: HomeAssistant, views: list[dict[str, Any]], snapshot: str | None = None
) -> SaveResult:
    """Save views through the editor's path, on the only device."""
    device = the_device(hass)
    assert device.profile is not None
    result = await device.views.async_save(
        device.views.revision, resolve(device.profile, views), snapshot
    )
    await hass.async_block_till_done()
    return result


def views_publishes(mqtt_mock: Any) -> list[dict[str, Any]]:
    """Return every non-empty `views` payload published so far."""
    return [
        json.loads(c.args[1])
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + "views" and c.args[1]
    ]


async def setup(
    hass: HomeAssistant,
    profile: dict[str, Any],
    views: list[dict[str, Any]] | None,
    *,
    entry: MockConfigEntry | None = None,
) -> MockConfigEntry:
    """Store `views` for the device, then set its entry up.

    With `views` None nothing is stored, so the entry starts with its starter view.
    """
    entry = entry or make_entry(profile)
    if views is not None:
        store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, store_key(entry.data[CONF_DEVICE_ID], "views")
        )
        await store.async_save(
            {"revision": 1, "views": resolve(profile, views), "snapshot": None}
        )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
