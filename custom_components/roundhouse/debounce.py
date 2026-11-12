"""A trailing-edge debounce on Home Assistant's clock."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later


class Debounce:
    """Run `action` once, `wait` seconds after the last `trigger`."""

    def __init__(
        self,
        hass: HomeAssistant,
        wait: float,
        action: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Initialize the debounce."""
        self._hass = hass
        self._wait = wait
        self._action = action
        self._cancel: CALLBACK_TYPE | None = None
        self._running: set[asyncio.Task[None]] = set()

    @callback
    def trigger(self) -> None:
        """Start or restart the wait."""
        self.cancel()
        self._cancel = async_call_later(self._hass, self._wait, self._fire)

    @callback
    def cancel(self) -> None:
        """Drop a pending run."""
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    @callback
    def async_stop(self) -> None:
        """Drop a pending run and cancel the runs in progress."""
        self.cancel()
        for task in list(self._running):
            task.cancel()

    @callback
    def _fire(self, _now: datetime) -> None:
        self._cancel = None
        task = self._hass.async_create_task(self._action())
        self._running.add(task)
        task.add_done_callback(self._running.discard)
