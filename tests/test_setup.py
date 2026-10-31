"""The integration loads and a config entry sets up and unloads."""

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roundhouse.const import DOMAIN


async def test_integration_is_found(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == DOMAIN


async def test_entry_sets_up_and_unloads(hass: HomeAssistant) -> None:
    from custom_components.roundhouse import async_setup_entry, async_unload_entry

    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await async_setup_entry(hass, entry)
    assert await async_unload_entry(hass, entry)
