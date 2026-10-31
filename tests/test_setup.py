"""The integration loads and a config entry sets up and unloads."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.roundhouse.const import DOMAIN

from .conftest import make_entry


async def test_integration_is_found(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == DOMAIN


async def test_entry_sets_up_and_unloads(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    entry = make_entry(tender_profile)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.entry_id in hass.data[DOMAIN]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert entry.entry_id not in hass.data[DOMAIN]
