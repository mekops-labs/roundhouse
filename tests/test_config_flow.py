"""Discovery, setup, and options."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from custom_components.roundhouse.const import DOMAIN

from .conftest import make_entry, vector


def _info(device_id: str, payload: dict[str, Any] | bytes) -> MqttServiceInfo:
    import json

    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return MqttServiceInfo(
        topic=f"roundhouse/{device_id}/announce",
        payload=body,
        qos=1,
        retain=True,
        subscribed_topic="roundhouse/+/announce",
        timestamp=0.0,
    )


async def _discover(hass: HomeAssistant, device_id: str, payload: Any) -> Any:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=_info(device_id, payload)
    )


async def test_user_flow_is_discovery_only(hass: HomeAssistant, mqtt_mock: Any) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "discovery_only"


async def test_discovery_to_entry_asks_only_for_confirmation(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    result = await _discover(hass, "tender01", tender_profile)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["data_schema"] is None

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "device_id": "tender01",
        "model": "tender",
        "profile": tender_profile,
    }
    assert result["result"].unique_id == "tender01"


async def test_two_devices_are_two_entries(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    make_entry(tender_profile, "tender01").add_to_hass(hass)
    result = await _discover(hass, "tender02", tender_profile)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "tender02"


async def test_known_device_does_not_start_a_flow(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    make_entry(tender_profile).add_to_hass(hass)
    result = await _discover(hass, "tender01", tender_profile)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []


async def test_bad_profile_aborts_and_raises_an_issue(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    bad = vector("announce", "unknown-format")["payload"]
    result = await _discover(hass, "tender01", bad)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_profile"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "profile_tender01")
    assert issue is not None
    assert issue.translation_key == "profile_invalid"


async def test_major_mismatch_names_a_repair_issue(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    bad = vector("announce", "major-mismatch")["payload"]
    result = await _discover(hass, "tender01", bad)
    assert result["reason"] == "invalid_profile"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "profile_tender01")
    assert issue is not None
    assert issue.translation_key == "contract_mismatch"


async def test_empty_announce_aborts(hass: HomeAssistant, mqtt_mock: Any) -> None:
    result = await _discover(hass, "tender01", b"")
    assert result["reason"] == "no_announce"


async def test_options_flow_holds_presence_and_alert_limits(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    entry = make_entry(tender_profile, "tender01")
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert set(result["data_schema"].schema) == {
        "presence_grace_hours",
        "alert_max_count",
        "alert_max_age_days",
    }
    defaults = result["data_schema"]({})
    assert (
        defaults["presence_grace_hours"],
        defaults["alert_max_count"],
        defaults["alert_max_age_days"],
    ) == (2, 20, 7)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"presence_grace_hours": 3, "alert_max_count": 10, "alert_max_age_days": 2},
    )
    assert entry.options["presence_grace_hours"] == 3
