"""The alerts of one device: store, publish, acknowledge, age, and act."""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import alertlogic, cmdhandler, codec, rendering
from .const import (
    DEFAULT_ALERT_MAX_AGE_DAYS,
    DEFAULT_ALERT_MAX_COUNT,
    EVENT_ALERT_ACKNOWLEDGED,
    OPT_ALERT_MAX_AGE_DAYS,
    OPT_ALERT_MAX_COUNT,
    alerts_signal,
    store_key,
)
from .publisher import PayloadTooLargeError

if TYPE_CHECKING:
    from .device import Device

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1
# A snapshot may take this long before the alert goes out without it.
IMAGE_WAIT = 3.0
AGING_INTERVAL = timedelta(minutes=10)


def now() -> float:
    """Return the current Unix time."""
    return dt_util.utcnow().timestamp()


class AlertManager:
    """Hold, publish, and age the alerts of a device."""

    def __init__(self, hass: HomeAssistant, device: Device) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._device = device
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, store_key(device.device_id, "alerts")
        )
        self._alerts: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._jobs: set[asyncio.Task[None]] = set()
        self._unsub: CALLBACK_TYPE | None = None

    @property
    def alerts(self) -> list[dict[str, Any]]:
        """Return the held alerts, oldest first."""
        return list(self._alerts)

    @property
    def unread(self) -> int:
        """Return the number of unread alerts."""
        return alertlogic.unread(self._alerts)

    def get(self, alert_id: str) -> dict[str, Any] | None:
        """Return an alert by ID."""
        return next((a for a in self._alerts if a["id"] == alert_id), None)

    def _image_store(self, alert_id: str) -> Store[dict[str, Any]]:
        return Store(
            self._hass,
            STORE_VERSION,
            store_key(self._device.device_id, f"alert_{alert_id}"),
        )

    def _limits(self) -> tuple[int, float]:
        opts = self._device.entry.options
        return (
            opts.get(OPT_ALERT_MAX_COUNT, DEFAULT_ALERT_MAX_COUNT),
            opts.get(OPT_ALERT_MAX_AGE_DAYS, DEFAULT_ALERT_MAX_AGE_DAYS),
        )

    # --- lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        """Load the stored alerts, drop the expired ones, and publish the rest."""
        stored = await self._store.async_load()
        self._alerts = list((stored or {}).get("alerts", []))
        async with self._lock:
            await self._expire()
        await self.async_publish_all()
        self._unsub = async_track_time_interval(
            self._hass, self._on_aging, AGING_INTERVAL
        )

    @callback
    def async_stop(self) -> None:
        """Stop aging and abandon pending snapshots."""
        if self._unsub:
            self._unsub()
            self._unsub = None
        for job in list(self._jobs):
            job.cancel()

    async def _on_aging(self, _now: datetime) -> None:
        async with self._lock:
            await self._expire()

    async def _save(self) -> None:
        await self._store.async_save({"alerts": self._alerts})
        async_dispatcher_send(self._hass, alerts_signal(self._device.device_id))

    # --- publishing ---------------------------------------------------------

    async def async_publish_all(self) -> None:
        """Publish every held alert with its images (idempotent)."""
        if self._device.error is not None:
            return
        async with self._lock:
            dropped = False
            for alert in self._alerts:
                dropped |= await self._publish_images(alert)
                await self._publish_alert(alert)
            if dropped:
                await self._save()

    async def _publish_alert(self, alert: dict[str, Any]) -> None:
        if self._device.error is not None:
            return
        try:
            await self._device.publisher.async_publish(
                f"alert/{alert['id']}", codec.encode(alertlogic.public(alert))
            )
        except PayloadTooLargeError as err:
            _LOGGER.error("Alert not published: %s", err)

    async def _publish_images(self, alert: dict[str, Any]) -> bool:
        """Publish the stored bitmaps of an alert.

        A bitmap the current profile cannot take is dropped from the alert.
        Return True when the alert changed.
        """
        if self._device.error is not None:
            return False
        if not (alert.get("image") or alert.get("thumb")):
            return False
        stored = await self._image_store(alert["id"]).async_load() or {}
        dropped = False
        for key in ("image", "thumb"):
            size = alert.get(key)
            if not size:
                continue
            data = base64.b64decode(stored.get(key) or "")
            if not self._fits(key, size, data, stored.get("format")):
                _LOGGER.warning(
                    "Alert %s %s dropped: it does not fit the device profile",
                    alert["id"],
                    key,
                )
                alert[key] = None
                await self._device.publisher.async_clear(f"alert/{alert['id']}/{key}")
                dropped = True
                continue
            await self._device.publisher.async_publish(
                f"alert/{alert['id']}/{key}", data
            )
        return dropped

    def _fits(
        self, key: str, size: dict[str, int], data: bytes, fmt: str | None
    ) -> bool:
        """Check a stored bitmap against the format, box, and payload limit."""
        profile = self._device.profile or {}
        try:
            box = profile[f"{key}_box"]
            if fmt is None or fmt != profile["display"]["format"]:
                return False
            width, height = size["width"], size["height"]
            expected = codec.bitmap_length(fmt, width, height)
        except (KeyError, TypeError, codec.ContractError):
            return False
        return (
            width <= box["width"]
            and height <= box["height"]
            and len(data) == expected
            and len(data) <= self._device.publisher.max_payload
        )

    async def _clear(self, alert: dict[str, Any]) -> None:
        for sub in ("", "/image", "/thumb"):
            await self._device.publisher.async_clear(f"alert/{alert['id']}{sub}")
        await self._image_store(alert["id"]).async_remove()

    async def _expire(self) -> None:
        count, days = self._limits()
        kept, dropped = alertlogic.expire(self._alerts, now(), count, days)
        if not dropped:
            return
        self._alerts = kept
        for alert in dropped:
            await self._clear(alert)
        await self._save()

    # --- adding -------------------------------------------------------------

    async def async_add(
        self,
        *,
        title: str,
        message: str,
        severity: str = "event",
        actions: Any = None,
        tag: str | None = None,
        snapshot: asyncio.Future[bytes] | None = None,
    ) -> str:
        """Raise an alert; return its ID. Raises `AlertError` for bad actions.

        `snapshot` is a fetch of the image; several devices may share one.
        """
        parsed = alertlogic.parse_actions(actions)
        alert = alertlogic.new_alert(
            alert_id=alertlogic.new_id(),
            now=now(),
            title=title,
            message=message,
            severity=severity,
            actions=parsed,
            tag=tag,
        )
        async with self._lock:
            for old in alertlogic.same_tag(self._alerts, tag):
                self._alerts = [a for a in self._alerts if a["id"] != old["id"]]
                await self._clear(old)
            self._alerts.append(alert)
            await self._expire()
            await self._save()
        if snapshot is not None:
            job = self._hass.async_create_task(self._image_job(alert["id"], snapshot))
            self._jobs.add(job)
            job.add_done_callback(self._jobs.discard)
            done, _ = await asyncio.wait({job}, timeout=IMAGE_WAIT)
            if done:
                return str(alert["id"])
        async with self._lock:
            # Aging replaces the held records with copies; publish the held one.
            held = self.get(alert["id"])
            if held is not None:
                await self._publish_alert(held)
        return str(alert["id"])

    async def _image_job(self, alert_id: str, snapshot: asyncio.Future[bytes]) -> None:
        fmt = ""
        encoded: dict[str, tuple[bytes, int, int]] = {}
        try:
            fmt, encoded = await self._render_images(snapshot)
        except rendering.ImageFetchError as err:
            _LOGGER.warning("Alert %s sent without an image: %s", alert_id, err)
        except Exception:
            _LOGGER.exception("Alert %s image failed", alert_id)
        async with self._lock:
            alert = self.get(alert_id)
            if alert is None:
                return
            if encoded:
                await self._attach(alert, fmt, encoded)
            await self._publish_alert(alert)

    async def _render_images(
        self, snapshot: asyncio.Future[bytes]
    ) -> tuple[str, dict[str, tuple[bytes, int, int]]]:
        profile = self._device.profile or {}
        # Shielded: stopping this device must not cancel a fetch others share.
        raw = await asyncio.shield(snapshot)
        fmt = profile["display"]["format"]
        limit = self._device.publisher.max_payload
        out: dict[str, tuple[bytes, int, int]] = {}
        for key, box in (
            ("image", profile["image_box"]),
            ("thumb", profile["thumb_box"]),
        ):
            result = await rendering.async_encode_image(
                self._hass, raw, fmt, (box["width"], box["height"]), limit
            )
            if result is None:
                _LOGGER.warning(
                    "Alert %s dropped: it does not fit %d bytes", key, limit
                )
            else:
                out[key] = result
        return fmt, out

    async def _attach(
        self,
        alert: dict[str, Any],
        fmt: str,
        encoded: dict[str, tuple[bytes, int, int]],
    ) -> None:
        stored: dict[str, str] = {"format": fmt}
        for key, (data, width, height) in encoded.items():
            alert[key] = {"width": width, "height": height}
            stored[key] = base64.b64encode(data).decode()
        await self._image_store(alert["id"]).async_save(stored)
        await self._save()
        if await self._publish_images(alert):
            await self._save()

    # --- acknowledging ------------------------------------------------------

    async def async_acknowledge(
        self, alert_id: str | None = None, tag: str | None = None
    ) -> list[str]:
        """Mark matching unread alerts as read; return their IDs."""
        async with self._lock:
            hit = [
                a
                for a in self._alerts
                if not a["read"]
                and (
                    (alert_id and a["id"] == alert_id) or (tag and a.get("tag") == tag)
                )
            ]
            for alert in hit:
                alert["read"] = True
                await self._publish_alert(alert)
                self._hass.bus.async_fire(
                    EVENT_ALERT_ACKNOWLEDGED,
                    {
                        "alert_id": alert["id"],
                        "tag": alert.get("tag"),
                        "device_id": self._device.device_id,
                    },
                )
            if hit:
                await self._save()
        return [a["id"] for a in hit]

    async def async_ack_from_device(self, alert_id: str) -> str:
        """Handle `{ack}` from the device: `ok`, or `denied` for an unknown alert."""
        if self.get(alert_id) is None:
            return "denied"
        await self.async_acknowledge(alert_id=alert_id)
        return "ok"

    # --- actions ------------------------------------------------------------

    async def async_run_action(
        self, alert_id: str, action_id: str, confirmed: bool
    ) -> str:
        """Run a declared action of a held alert; return the command result."""
        alert = self.get(alert_id)
        action = alertlogic.find_action(alert, action_id) if alert else None
        if action is None:
            return "denied"
        if action["confirm"] and not confirmed:
            return "needs_confirmation"
        domain, service, data = alertlogic.service_call(action)
        return await cmdhandler.async_call_service(self._hass, domain, service, data)
