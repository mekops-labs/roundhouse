"""The only module that touches Lovelace internals.

Home Assistant keeps its dashboards collection out of `hass.data`, so the
collection is reached through the websocket handler Lovelace registers for it.
See docs/ha-internals.md for the versions this was checked on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.lovelace.const import LOVELACE_DATA, ConfigNotFound
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback

from .debounce import Debounce

# Fired by Lovelace after a dashboard config is saved or deleted. The constant
# moved between Home Assistant releases, so use the string.
EVENT_LOVELACE_UPDATED = "lovelace_updated"

# Wait for further saves before digesting again: the editor saves repeatedly.
UPDATE_WAIT = 2.0

LIST_COMMAND = "lovelace/dashboards/list"

STARTER_CONFIG: dict[str, Any] = {
    "views": [
        {
            "title": "Start",
            "path": "start",
            "cards": [
                {
                    "type": "markdown",
                    "content": (
                        "Build this dashboard for your Roundhouse device. "
                        "The device shows these cards: `tile` (with its "
                        "features), `button`, `thermostat`, `humidifier`, and "
                        "the rows of an `entities` card. Stacks and grids are "
                        "flattened. Other cards, and cards with visibility "
                        "conditions, are skipped. Each view is a page on the "
                        "device."
                    ),
                }
            ],
        }
    ]
}


class LovelaceUnavailableError(RuntimeError):
    """The dashboards collection cannot be reached."""


def _collection(hass: HomeAssistant) -> Any:
    entry = hass.data.get(websocket_api.DOMAIN, {}).get(LIST_COMMAND)
    handler: Callable[..., Any] | None = entry[0] if entry else None
    while handler is not None and not hasattr(handler, "__self__"):
        handler = getattr(handler, "__wrapped__", None)
    collection = getattr(getattr(handler, "__self__", None), "storage_collection", None)
    if collection is None:
        raise LovelaceUnavailableError("Lovelace dashboards collection not found")
    return collection


def dashboard_exists(hass: HomeAssistant, url_path: str) -> bool:
    """Return whether a dashboard with this URL path exists."""
    return url_path in hass.data[LOVELACE_DATA].dashboards


async def async_ensure_dashboard(
    hass: HomeAssistant, url_path: str, title: str
) -> bool:
    """Create the dashboard with a starter view; return True if it was created.

    An existing dashboard is left exactly as it is.
    """
    if dashboard_exists(hass, url_path):
        return False
    await _collection(hass).async_create_item(
        {
            "url_path": url_path,
            "title": title,
            "icon": "mdi:view-dashboard",
            "show_in_sidebar": True,
            "require_admin": False,
        }
    )
    await hass.data[LOVELACE_DATA].dashboards[url_path].async_save(STARTER_CONFIG)
    return True


@dataclass(frozen=True)
class DashboardState:
    """What a dashboard holds right now.

    `kind` is `config` (cards to digest), `strategy` (generated, no cards), or
    `missing` (no such dashboard).
    """

    kind: str
    config: dict[str, Any] | None = None


async def async_load_dashboard(hass: HomeAssistant, url_path: str) -> DashboardState:
    """Load a dashboard's config by URL path."""
    dashboard = hass.data[LOVELACE_DATA].dashboards.get(url_path)
    if dashboard is None:
        return DashboardState("missing")
    try:
        config = await dashboard.async_load(False)
    except ConfigNotFound:
        return DashboardState("strategy")
    return DashboardState("config", config)


@callback
def async_watch(
    hass: HomeAssistant, url_path: str, debounce: Debounce
) -> CALLBACK_TYPE:
    """Trigger `debounce` when the dashboard is saved or deleted."""

    @callback
    def _on_event(event: Event) -> None:
        if event.data.get("url_path") == url_path:
            debounce.trigger()

    return hass.bus.async_listen(EVENT_LOVELACE_UPDATED, _on_event)
