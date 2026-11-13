"""Runtime of one configured device."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import codec, issues, layout
from .alertmanager import AlertManager
from .cmdhandler import CommandHandler
from .const import (
    CONF_DEVICE_ID,
    CONF_PROFILE,
    STALE_SETTLE_SECONDS,
    status_signal,
    views_signal,
)
from .presencemanager import PresenceManager
from .publisher import PayloadTooLargeError, Publisher
from .statesync import StateSync
from .viewsync import ViewSync

_LOGGER = logging.getLogger(__name__)
DEFAULT_MAX_PAYLOAD = 65536


class Device:
    """Own the profile state and the retained topics of one device."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the device runtime."""
        self._hass = hass
        self.entry = entry
        self.device_id: str = entry.data[CONF_DEVICE_ID]
        self.profile: dict[str, Any] | None = entry.data.get(CONF_PROFILE)
        self.error: str | None = None
        self.views_payload: dict[str, Any] | None = None
        max_payload = (
            (self.profile or {})
            .get("limits", {})
            .get("max_payload", DEFAULT_MAX_PAYLOAD)
        )
        self.publisher = Publisher(hass, self.device_id, max_payload)
        self._unsubs: list[CALLBACK_TYPE] = []
        self.views = ViewSync(hass, self)
        self.states = StateSync(hass, self)
        self.commands = CommandHandler(hass, self)
        self.alerts = AlertManager(hass, self)
        self.presence = PresenceManager(hass, self)
        self.status: dict[str, Any] | None = None
        self.card_icons: dict[str, str] = {}
        self._was_connected = True

    async def async_start(self) -> None:
        """Subscribe, publish `meta`, and clear stale retained topics."""
        self._unsubs.append(
            await mqtt.async_subscribe(
                self._hass,
                f"roundhouse/{self.device_id}/announce",
                self._on_announce,
                qos=1,
                encoding=None,
            )
        )
        await self.presence.async_start()
        for name, handler in (
            ("availability", self._on_availability),
            ("status", self._on_status),
        ):
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass,
                    f"roundhouse/{self.device_id}/{name}",
                    handler,
                    qos=1,
                    encoding=None,
                )
            )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self._hass,
                f"roundhouse/{self.device_id}/cmd",
                self._on_cmd,
                qos=1,
                encoding=None,
            )
        )
        self._unsubs.append(
            mqtt.async_subscribe_connection_status(self._hass, self._on_connection)
        )
        issues.check_mqtt_birth(self._hass)
        await self.views.async_start()
        await self.alerts.async_start()
        self.entry.async_create_background_task(
            self._hass, self._async_clean_stale(), f"roundhouse stale {self.device_id}"
        )

    @callback
    def async_stop(self) -> None:
        """Unsubscribe."""
        self.views.async_stop()
        self.states.async_stop()
        self.alerts.async_stop()
        self.presence.async_stop()
        self.publisher.async_stop()
        while self._unsubs:
            self._unsubs.pop()()

    def set_views(
        self, payload: dict[str, Any], icon_overrides: dict[str, str] | None = None
    ) -> None:
        """Set the `views` payload the next publish sends."""
        self.views_payload = payload
        self.card_icons = icon_overrides or {}
        async_dispatcher_send(self._hass, views_signal(self.device_id))

    def tiles_for(self, entity_id: str) -> list[dict[str, Any]]:
        """Return the published tiles that show an entity."""
        if self.error is not None or not self.views_payload:
            return []
        return [
            t
            for v in self.views_payload["views"]
            for t in v["tiles"]
            if t["entity_id"] == entity_id
        ]

    def tracked_entities(self) -> frozenset[str]:
        if self.error is not None or not self.views_payload:
            return frozenset()
        return frozenset(
            t["entity_id"] for v in self.views_payload["views"] for t in v["tiles"]
        )

    def _meta(self) -> bytes:
        views_hash = (
            layout.definition_hash(self.views_payload) if self.views_payload else ""
        )
        return codec.encode(
            {
                "contract": f"{codec.SUPPORTED_MAJOR}.0",
                "language": self._hass.config.language,
                "views_hash": views_hash,
            }
        )

    async def async_publish_all(self) -> None:
        """Publish everything this device should hold.

        With a bad profile or a contract mismatch only `meta` is published.
        """
        if self.error is None and self.views_payload is not None:
            try:
                await self.publisher.async_publish(
                    "views", codec.encode(self.views_payload)
                )
            except PayloadTooLargeError as err:
                _LOGGER.error("View definition not published: %s", err)
        await self.states.async_sync(self.tracked_entities(), self.card_icons)
        if self.error is None:
            await self.alerts.async_publish_all()
        await self.publisher.async_publish("meta", self._meta())
        if self.error is not None:
            await self.publisher.async_clear_all_except(frozenset({"meta"}))

    async def _async_clean_stale(self) -> None:
        await self.publisher.async_clear_stale(STALE_SETTLE_SECONDS)

    @callback
    def _on_connection(self, connected: bool) -> None:
        if connected and not self._was_connected:
            self.entry.async_create_background_task(
                self._hass, self._async_resync(), f"roundhouse resync {self.device_id}"
            )
        self._was_connected = connected

    async def _async_resync(self) -> None:
        issues.check_mqtt_birth(self._hass)
        await self.publisher.async_resync()

    async def _on_availability(self, msg: mqtt.ReceiveMessage) -> None:
        if not isinstance(msg.payload, bytes):
            return
        try:
            value = codec.decode("availability", msg.payload)
        except codec.ContractError as err:
            _LOGGER.debug("Ignoring availability of %s: %s", self.device_id, err)
            return
        await self.presence.async_on_availability(value)

    async def _on_status(self, msg: mqtt.ReceiveMessage) -> None:
        if not isinstance(msg.payload, bytes) or not msg.payload:
            return
        try:
            self.status = codec.decode("status", msg.payload)
        except codec.ContractError as err:
            _LOGGER.debug("Ignoring status of %s: %s", self.device_id, err)
            return
        async_dispatcher_send(self._hass, status_signal(self.device_id))

    async def _on_cmd(self, msg: mqtt.ReceiveMessage) -> None:
        if isinstance(msg.payload, bytes):
            await self.commands.async_handle(msg.payload)

    async def _on_announce(self, msg: mqtt.ReceiveMessage) -> None:
        payload = msg.payload
        if not isinstance(payload, bytes) or not payload:
            return
        try:
            profile = codec.decode("announce", payload)
        except codec.ContractError as err:
            await self._on_bad_profile(err, payload)
            return
        recovered = self.error is not None
        self.error = None
        issues.clear_profile_issue(self._hass, self.device_id)
        if recovered and profile == self.profile:
            await self.views.async_refresh()
        if profile != self.profile:
            _LOGGER.debug("Profile of %s changed", self.device_id)
            self._hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_PROFILE: profile}
            )

    async def _on_bad_profile(self, err: codec.ContractError, payload: bytes) -> None:
        detail = err.detail
        if err.code == "major_mismatch":
            try:
                peer = json.loads(payload).get("contract")
            except ValueError:
                peer = None
            detail = f"device {peer}, Roundhouse {codec.SUPPORTED_MAJOR}.x"
        _LOGGER.warning("Device %s: %s", self.device_id, err)
        self.error = err.code
        issues.raise_profile_issue(self._hass, self.device_id, err.code, detail)
        await self.async_publish_all()
