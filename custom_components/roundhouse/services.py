"""The `roundhouse` services: send and acknowledge alerts."""

from __future__ import annotations

from typing import Any

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from . import alertlogic
from .compat import vol
from .const import (
    DEFAULT_SEVERITY,
    DOMAIN,
    SERVICE_ACKNOWLEDGE_ALERT,
    SERVICE_SEND_ALERT,
    SEVERITIES,
)
from .device import Device

SEND_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("title"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("severity", default=DEFAULT_SEVERITY): vol.In(SEVERITIES),
        vol.Optional("camera_entity"): cv.entity_id,
        vol.Optional("image_url"): cv.string,
        vol.Optional("actions"): list,
        vol.Optional("tag"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)

ACK_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("alert_id"): cv.string,
        vol.Optional("tag"): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)


def _devices(hass: HomeAssistant, call: ServiceCall, *, required: bool) -> list[Device]:
    """Resolve the targeted Roundhouse devices; all of them when not `required`."""
    runtimes: dict[str, Device] = {
        d.device_id: d
        for d in hass.data.get(DOMAIN, {}).values()
        if isinstance(d, Device)
    }
    ids: list[str] = call.data.get("device_id") or []
    if not ids:
        if required:
            raise ServiceValidationError("Target at least one Roundhouse device")
        return list(runtimes.values())
    registry = dr.async_get(hass)
    found: list[Device] = []
    for registry_id in ids:
        entry = registry.async_get(registry_id)
        roundhouse_id = next(
            (i[1] for i in (entry.identifiers if entry else ()) if i[0] == DOMAIN), None
        )
        if roundhouse_id is None or roundhouse_id not in runtimes:
            raise ServiceValidationError(f"{registry_id} is not a Roundhouse device")
        found.append(runtimes[roundhouse_id])
    return found


async def _send_alert(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    data: dict[str, Any] = dict(call.data)
    devices = _devices(hass, call, required=True)
    try:
        alertlogic.parse_actions(data.get("actions"))
    except alertlogic.AlertError as err:
        raise ServiceValidationError(str(err)) from err
    ids: dict[str, str] = {}
    for device in devices:
        ids[device.device_id] = await device.alerts.async_add(
            title=data["title"],
            message=data["message"],
            severity=data["severity"],
            actions=data.get("actions"),
            tag=data.get("tag"),
            camera_entity=data.get("camera_entity"),
            image_url=data.get("image_url"),
        )
    return {"alert_ids": dict(ids)}


async def _acknowledge(hass: HomeAssistant, call: ServiceCall) -> None:
    if not (call.data.get("alert_id") or call.data.get("tag")):
        raise ServiceValidationError("Give an alert_id or a tag")
    for device in _devices(hass, call, required=False):
        await device.alerts.async_acknowledge(
            alert_id=call.data.get("alert_id"), tag=call.data.get("tag")
        )


def async_register(hass: HomeAssistant) -> None:
    """Register the services once."""

    async def send(call: ServiceCall) -> ServiceResponse:
        return await _send_alert(hass, call)

    async def acknowledge(call: ServiceCall) -> None:
        await _acknowledge(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_ALERT,
        send,
        schema=SEND_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ACKNOWLEDGE_ALERT, acknowledge, schema=ACK_SCHEMA
    )
