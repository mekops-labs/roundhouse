"""The data behind the preview panel: what each view looks like on the device."""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import const as ws_const
from homeassistant.components.websocket_api import decorators as ws_decorators
from homeassistant.components.websocket_api import messages as ws_messages
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import async_track_state_change_event

from . import layout, rendering
from .compat import vol
from .const import (
    DOMAIN,
    WS_PREVIEW_DEVICES,
    WS_PREVIEW_SUBSCRIBE,
    views_signal,
)
from .device import Device

_LOGGER = logging.getLogger(__name__)


def _devices(hass: HomeAssistant) -> dict[str, Device]:
    return {
        d.device_id: d
        for d in hass.data.get(DOMAIN, {}).values()
        if isinstance(d, Device)
    }


async def build_snapshot(hass: HomeAssistant, device: Device) -> dict[str, Any]:
    """Return everything the panel draws for a device.

    Views include those held back for overflow, which are not published. The
    states are the messages the device receives, and `icons` holds the masks.
    """
    profile = device.profile or {}
    sync = device.views
    digest = sync.last_digest
    published = {v["path"] for v in (device.views_payload or {}).get("views", [])}
    cap = layout.capacity(profile) if profile else 0
    views: list[dict[str, Any]] = []
    entities: dict[str, str | None] = {}
    for view in digest.views if digest else []:
        count = len(view.tiles)
        chosen = layout.choose_layout(profile, count) if profile else None
        views.append(
            {
                "path": view.path,
                "title": view.title,
                "layout": chosen,
                "tiles": [t.as_dict() for t in view.tiles],
                "count": count,
                "capacity": cap,
                "overflow": chosen is None,
                "published": view.path in published,
            }
        )
        for tile in view.tiles:
            entities.setdefault(tile.entity_id, tile.icon)
    states, icons = await render_states(hass, device, entities)
    return {
        "type": "snapshot",
        "device_id": device.device_id,
        "profile": profile,
        "dashboard": sync.dashboard_state,
        "views": views,
        "states": states,
        "icons": icons,
    }


async def render_states(
    hass: HomeAssistant, device: Device, entities: dict[str, str | None]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Render the state message of each entity and the masks of their icons."""
    profile = device.profile or {}
    translator = device.states.translator
    domains, platforms = rendering.entity_domains(hass, set(entities))
    await hass.async_add_executor_job(_warm)
    await translator.async_load(domains, platforms)
    states = {
        entity_id: rendering.render_state(hass, translator, entity_id, card_icon)
        for entity_id, card_icon in entities.items()
    }
    icons: dict[str, str] = {}
    for message in states.values():
        name = message["icon"]
        if name not in icons and profile:
            payload = await rendering.async_icon_payload(hass, name, profile["icon_px"])
            icons[name] = base64.b64encode(payload).decode()
    return states, icons


def _warm() -> None:
    from . import icons

    icons.warm()


class Subscription:
    """One panel watching one device."""

    def __init__(
        self,
        hass: HomeAssistant,
        device: Device,
        send: Callable[[dict[str, Any]], None],
    ) -> None:
        """Initialize the subscription."""
        self._hass = hass
        self._device = device
        self._send = send
        self._unsubs: list[CALLBACK_TYPE] = []
        self._tracked: frozenset[str] = frozenset()
        self._cards: dict[str, str | None] = {}
        self._closed = False
        self._state_unsub: CALLBACK_TYPE | None = None

    async def async_start(self) -> None:
        """Send the first snapshot and follow the device."""
        self._unsubs.append(
            async_dispatcher_connect(
                self._hass, views_signal(self._device.device_id), self._on_views
            )
        )
        await self._push_snapshot()

    @callback
    def async_stop(self) -> None:
        """Stop following."""
        self._closed = True
        while self._unsubs:
            self._unsubs.pop()()

    @callback
    def _on_views(self) -> None:
        self._hass.async_create_task(self._push_snapshot())

    async def _push_snapshot(self) -> None:
        if self._closed:
            return
        snapshot = await build_snapshot(self._hass, self._device)
        if self._closed:
            return
        self._send(snapshot)
        self._track(snapshot)

    def _track(self, snapshot: dict[str, Any]) -> None:
        entities = frozenset(
            t["entity_id"] for v in snapshot["views"] for t in v["tiles"]
        )
        digest = self._device.views.last_digest
        self._cards = {
            t.entity_id: t.icon
            for v in (digest.views if digest else [])
            for t in v.tiles
        }
        if entities == self._tracked:
            return
        self._tracked = entities
        if self._state_unsub is not None:
            self._state_unsub()
            self._unsubs.remove(self._state_unsub)
        self._state_unsub = async_track_state_change_event(
            self._hass, list(entities), self._on_state
        )
        self._unsubs.append(self._state_unsub)

    @callback
    def _on_state(self, event: Event[EventStateChangedData]) -> None:
        self._hass.async_create_task(self._push_state(event.data["entity_id"]))

    async def _push_state(self, entity_id: str) -> None:
        if self._closed or entity_id not in self._tracked:
            return
        states, icons = await render_states(
            self._hass, self._device, {entity_id: self._cards.get(entity_id)}
        )
        if not self._closed:
            self._send(
                {
                    "type": "state",
                    "entity_id": entity_id,
                    "state": states[entity_id],
                    "icons": icons,
                }
            )


@ws_decorators.require_admin
@ws_decorators.websocket_command({vol.Required("type"): WS_PREVIEW_DEVICES})
@callback
def ws_devices(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the devices the panel can preview."""
    connection.send_result(
        msg["id"],
        [
            {
                "device_id": d.device_id,
                "model": d.entry.data["model"],
                "title": d.entry.title,
            }
            for d in _devices(hass).values()
        ],
    )


@ws_decorators.require_admin
@ws_decorators.websocket_command(
    {vol.Required("type"): WS_PREVIEW_SUBSCRIBE, vol.Required("device_id"): str}
)
@ws_decorators.async_response
async def ws_subscribe(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stream the preview of one device: a snapshot after every digest."""
    device = _devices(hass).get(msg["device_id"])
    if device is None:
        connection.send_error(msg["id"], ws_const.ERR_NOT_FOUND, "Unknown device")
        return
    if device.profile is None:
        connection.send_error(msg["id"], ws_const.ERR_NOT_FOUND, "No profile yet")
        return

    def send(payload: dict[str, Any]) -> None:
        connection.send_message(ws_messages.event_message(msg["id"], payload))

    subscription = Subscription(hass, device, send)
    connection.subscriptions[msg["id"]] = subscription.async_stop
    connection.send_result(msg["id"])
    await subscription.async_start()


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the admin-only websocket commands."""
    websocket_api.async_register_command(hass, ws_devices)
    websocket_api.async_register_command(hass, ws_subscribe)
