"""The editor page's side: the views of a device, live state, and saves."""

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

from . import rendering, viewrules
from .compat import vol
from .const import (
    DOMAIN,
    WS_DEVICES,
    WS_EDITOR_RENDER,
    WS_EDITOR_SAVE,
    WS_EDITOR_SUBSCRIBE,
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


def rules() -> dict[str, Any]:
    """Return what the page offers: supported domains and the controls of each."""
    return {
        "domains": sorted(viewrules.SUPPORTED_DOMAINS),
        "controls": {
            domain: [{"type": c.type, "values_attr": c.values_attr} for c in controls]
            for domain, controls in viewrules.CONTROLS.items()
        },
    }


def _icon_overrides(views: list[dict[str, Any]]) -> dict[str, str | None]:
    """Return each tile entity with the icon override of its first tile."""
    entities: dict[str, str | None] = {}
    for view in views:
        for tile in view["tiles"]:
            if entities.get(tile["entity_id"]) is None:
                entities[tile["entity_id"]] = tile.get("icon")
    return entities


async def build_snapshot(hass: HomeAssistant, device: Device) -> dict[str, Any]:
    """Return everything the page draws for a device.

    Views are the stored ones, with the overflow of those the profile cannot
    show. The states are the messages the device receives, and `icons` holds
    the masks.
    """
    sync = device.views
    overflows = {o.path: o for o in sync.overflows}
    views = []
    for view in sync.views:
        over = overflows.get(view["path"])
        views.append(
            {
                **view,
                "overflow": None
                if over is None
                else {
                    "tiles": over.tiles,
                    "capacity": over.capacity,
                    "excess": over.excess,
                    "layout_gone": over.layout_gone,
                },
            }
        )
    states, icons = await render_states(hass, device, _icon_overrides(sync.views))
    return {
        "type": "snapshot",
        "device_id": device.device_id,
        "profile": device.profile,
        "revision": sync.revision,
        "views": views,
        "snapshot": sync.snapshot,
        "rules": rules(),
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
        device_id: str,
        send: Callable[[dict[str, Any]], None],
    ) -> None:
        """Initialize the subscription."""
        self._hass = hass
        self._device_id = device_id
        self._send = send
        self._unsubs: list[CALLBACK_TYPE] = []
        self._tracked: frozenset[str] = frozenset()
        self._cards: dict[str, str | None] = {}
        self._closed = False
        self._state_unsub: CALLBACK_TYPE | None = None
        # Renders finish out of order; only the latest one started is sent.
        self._snapshot_seq = 0
        self._state_seq: dict[str, int] = {}

    def _device(self) -> Device | None:
        """Return the running device; a reload replaces the object."""
        return _devices(self._hass).get(self._device_id)

    async def async_start(self) -> None:
        """Send the first snapshot and follow the device."""
        self._unsubs.append(
            async_dispatcher_connect(
                self._hass, views_signal(self._device_id), self._on_views
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
        device = self._device()
        if self._closed or device is None or device.profile is None:
            return
        self._snapshot_seq += 1
        seq = self._snapshot_seq
        snapshot = await build_snapshot(self._hass, device)
        if self._closed or seq != self._snapshot_seq:
            return
        self._send(snapshot)
        self._track(device, snapshot)

    def _track(self, device: Device, snapshot: dict[str, Any]) -> None:
        self._cards = _icon_overrides(snapshot["views"])
        entities = frozenset(self._cards)
        if entities == self._tracked:
            return
        self._tracked = entities
        self._state_seq = {e: n for e, n in self._state_seq.items() if e in entities}
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
        device = self._device()
        if self._closed or device is None or entity_id not in self._tracked:
            return
        seq = self._state_seq[entity_id] = self._state_seq.get(entity_id, 0) + 1
        states, icons = await render_states(
            self._hass, device, {entity_id: self._cards.get(entity_id)}
        )
        if not self._closed and seq == self._state_seq.get(entity_id):
            self._send(
                {
                    "type": "state",
                    "entity_id": entity_id,
                    "state": states[entity_id],
                    "icons": icons,
                }
            )


def _device_or_error(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> Device | None:
    device = _devices(hass).get(msg["device_id"])
    if device is None:
        connection.send_error(msg["id"], ws_const.ERR_NOT_FOUND, "Unknown device")
        return None
    if device.profile is None:
        connection.send_error(msg["id"], ws_const.ERR_NOT_FOUND, "No profile yet")
        return None
    return device


@ws_decorators.require_admin
@ws_decorators.websocket_command({vol.Required("type"): WS_DEVICES})
@callback
def ws_devices(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """List the devices the page can edit."""
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
    {vol.Required("type"): WS_EDITOR_SUBSCRIBE, vol.Required("device_id"): str}
)
@ws_decorators.async_response
async def ws_subscribe(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Stream one device: a snapshot after every save, profile change, or rename."""
    device = _device_or_error(hass, connection, msg)
    if device is None:
        return

    def send(payload: dict[str, Any]) -> None:
        connection.send_message(ws_messages.event_message(msg["id"], payload))

    subscription = Subscription(hass, device.device_id, send)
    connection.subscriptions[msg["id"]] = subscription.async_stop
    connection.send_result(msg["id"])
    await subscription.async_start()


@ws_decorators.require_admin
@ws_decorators.websocket_command(
    {
        vol.Required("type"): WS_EDITOR_SAVE,
        vol.Required("device_id"): str,
        vol.Required("revision"): int,
        vol.Required("views"): [dict],
        vol.Required("snapshot"): vol.Any(None, str),
    }
)
@ws_decorators.async_response
async def ws_save(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Check and store the views of a device, and publish them."""
    device = _device_or_error(hass, connection, msg)
    if device is None:
        return
    result = await device.views.async_save(
        msg["revision"], msg["views"], msg["snapshot"]
    )
    if result.conflict:
        connection.send_result(
            msg["id"], {"ok": False, "error": "conflict", "revision": result.revision}
        )
    elif result.errors:
        connection.send_result(
            msg["id"],
            {
                "ok": False,
                "error": "invalid",
                "errors": [e.as_dict() for e in result.errors],
            },
        )
    else:
        connection.send_result(
            msg["id"],
            {"ok": True, "revision": result.revision, "views": result.views},
        )


# The most entities one render call takes: a draft cannot hold more tiles.
MAX_RENDER = 64


@ws_decorators.require_admin
@ws_decorators.websocket_command(
    {
        vol.Required("type"): WS_EDITOR_RENDER,
        vol.Required("device_id"): str,
        vol.Required("entities"): {str: vol.Any(None, str)},
    }
)
@ws_decorators.async_response
async def ws_render(
    hass: HomeAssistant, connection: ActiveConnection, msg: dict[str, Any]
) -> None:
    """Render entities as the device would show them, for tiles not saved yet."""
    device = _device_or_error(hass, connection, msg)
    if device is None:
        return
    entities: dict[str, str | None] = msg["entities"]
    if len(entities) > MAX_RENDER:
        connection.send_error(msg["id"], ws_const.ERR_INVALID_FORMAT, "Too many")
        return
    known = {e: i for e, i in entities.items() if viewrules.domain_of(e)}
    states, icons = await render_states(hass, device, known)
    connection.send_result(msg["id"], {"states": states, "icons": icons})


@callback
def async_register_commands(hass: HomeAssistant) -> None:
    """Register the admin-only websocket commands."""
    for command in (ws_devices, ws_subscribe, ws_save, ws_render):
        websocket_api.async_register_command(hass, command)
