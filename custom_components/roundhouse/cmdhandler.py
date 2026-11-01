"""Run the commands a device sends and answer each one."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from . import codec, commands

if TYPE_CHECKING:
    from .device import Device

_LOGGER = logging.getLogger(__name__)

# The service call may take this long before the result is `timeout`.
COMMAND_TIMEOUT = 10.0
# Request IDs remembered per device, to answer a repeat without a second call.
REMEMBERED = 32
# Seconds between two log lines of the same kind.
LOG_INTERVAL = 60.0
MAX_ERROR_LENGTH = 200


class RateLimiter:
    """Allow one event per key each `interval` seconds, counting the rest."""

    def __init__(self, interval: float, clock: Any) -> None:
        """Initialize the limiter with a monotonic `clock`."""
        self._interval = interval
        self._clock = clock
        self._last: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def allow(self, key: str) -> int | None:
        """Return the number of suppressed events if this one may log, else None."""
        now = self._clock()
        last = self._last.get(key)
        if last is not None and now - last < self._interval:
            self._suppressed[key] = self._suppressed.get(key, 0) + 1
            return None
        self._last[key] = now
        return self._suppressed.pop(key, 0)


def short(text: str) -> str:
    """Return an error text that fits a result message."""
    text = " ".join(text.split())
    return text[:MAX_ERROR_LENGTH] if text else "error"


async def async_call_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    data: dict[str, Any],
) -> str:
    """Call a service and wait for it: `ok`, `timeout`, or an error text."""
    try:
        async with asyncio.timeout(COMMAND_TIMEOUT):
            await hass.services.async_call(domain, service, data, blocking=True)
    except TimeoutError:
        return "timeout"
    except HomeAssistantError as err:
        return short(str(err) or type(err).__name__)
    except Exception as err:  # a service schema error or a bug in an integration
        _LOGGER.exception("Command %s.%s failed", domain, service)
        return short(f"{type(err).__name__}: {err}")
    return "ok"


class CommandHandler:
    """Check, run, and answer the commands of one device."""

    def __init__(self, hass: HomeAssistant, device: Device) -> None:
        """Initialize the handler."""
        self._hass = hass
        self._device = device
        self._seen: OrderedDict[str, asyncio.Future[str]] = OrderedDict()
        self._log = RateLimiter(LOG_INTERVAL, hass.loop.time)

    async def async_handle(self, payload: bytes) -> None:
        """Handle one message on the `cmd` topic."""
        try:
            cmd = codec.decode("cmd", payload)
        except codec.ContractError as err:
            await self._answer_malformed(payload, err)
            return
        req = cmd["req"]
        _LOGGER.debug("Command from %s: %s", self._device.device_id, cmd)
        if req in self._seen:
            self._seen.move_to_end(req)
            result = await asyncio.shield(self._seen[req])
            _LOGGER.debug("Repeat of %s on %s: %s", req, self._device.device_id, result)
        else:
            result = await self._run(req, cmd)
        await self._reply(req, result)

    async def _run(self, req: str, cmd: dict[str, Any]) -> str:
        future: asyncio.Future[str] = self._hass.loop.create_future()
        self._seen[req] = future
        self._evict()
        try:
            result = await self._execute(cmd)
        except Exception:
            _LOGGER.exception("Command %s on %s failed", req, self._device.device_id)
            result = "error"
        future.set_result(result)
        _LOGGER.debug("Result of %s on %s: %s", req, self._device.device_id, result)
        return result

    def _evict(self) -> None:
        while len(self._seen) > REMEMBERED:
            oldest, future = next(iter(self._seen.items()))
            if not future.done():
                break
            del self._seen[oldest]

    async def _reply(self, req: str, result: str) -> None:
        await self._device.publisher.async_send_transient(
            "result", codec.encode({"req": req, "result": result})
        )

    async def _answer_malformed(self, payload: bytes, err: codec.ContractError) -> None:
        try:
            req = json.loads(payload).get("req")
        except (ValueError, AttributeError):
            req = None
        self._deny_log(f"malformed command: {err}")
        if isinstance(req, str) and 0 < len(req) <= 64:
            await self._reply(req, "invalid")

    def _deny_log(self, reason: str) -> None:
        suppressed = self._log.allow(reason)
        if suppressed is not None:
            _LOGGER.warning(
                "Refused a command from %s: %s (%d similar suppressed)",
                self._device.device_id,
                reason,
                suppressed,
            )

    async def _execute(self, cmd: dict[str, Any]) -> str:
        if "entity_id" in cmd:
            return await self._execute_entity(cmd)
        alerts = self._device.alerts
        if "alert" in cmd:
            result = await alerts.async_run_action(
                cmd["alert"], cmd["action_id"], cmd["confirmed"]
            )
        else:
            result = await alerts.async_ack_from_device(cmd["ack"])
        if result == "denied":
            self._deny_log("alert command for an unknown alert or action")
        return result

    async def _execute_entity(self, cmd: dict[str, Any]) -> str:
        entity_id: str = cmd["entity_id"]
        tiles = self._device.tiles_for(entity_id)
        if not tiles:
            self._deny_log(f"{entity_id} is not on the device")
            return "denied"
        state = self._hass.states.get(entity_id)
        attrs = dict(state.attributes) if state else {}
        call, error = self._plan(tiles, cmd, attrs)
        if error is not None:
            return error
        assert call is not None
        domain = entity_id.split(".", 1)[0]
        if commands.needs_confirmation(domain, cmd["action"]) and not cmd["confirmed"]:
            return "needs_confirmation"
        return await async_call_service(
            self._hass, call.domain, call.service, call.data
        )

    def _plan(
        self, tiles: list[dict[str, Any]], cmd: dict[str, Any], attrs: dict[str, Any]
    ) -> tuple[commands.Call | None, str | None]:
        """Check the command against each tile that shows the entity."""
        invalid = False
        for tile in tiles:
            try:
                call = commands.build(
                    cmd["entity_id"],
                    cmd["action"],
                    cmd["data"],
                    attrs,
                    tile.get("controls", []),
                )
            except commands.Denied as err:
                self._deny_log(str(err))
                return None, "denied"
            except commands.Invalid as err:
                _LOGGER.debug("Invalid command %s: %s", cmd["req"], err)
                invalid = True
            else:
                return call, None
        return None, "invalid" if invalid else "denied"
