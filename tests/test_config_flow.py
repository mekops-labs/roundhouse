"""Discovery, setup, and options."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo

from custom_components.roundhouse import lovelace_io
from custom_components.roundhouse.config_flow import unique_slug
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


def test_unique_slug() -> None:
    assert unique_slug("tender-panel", set()) == "tender-panel"
    assert unique_slug("tender-panel", {"tender-panel"}) == "tender-panel-2"
    assert (
        unique_slug("tender-panel", {"tender-panel", "tender-panel-2"})
        == "tender-panel-3"
    )


async def test_user_flow_is_discovery_only(hass: HomeAssistant, mqtt_mock: Any) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "discovery_only"


async def test_discovery_to_entry_and_dashboard(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    result = await _discover(hass, "tender01", tender_profile)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["data_schema"]({})["slug"] == "tender-panel"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"slug": "tender-panel"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["device_id"] == "tender01"
    assert result["data"]["profile"] == tender_profile
    assert result["result"].unique_id == "tender01"

    dash = hass.data[LOVELACE_DATA].dashboards["tender-panel"]
    config = await dash.async_load(False)
    assert config["views"][0]["cards"][0]["type"] == "markdown"
    assert (await dash.async_get_info())["mode"] == "storage"


async def test_invalid_slug_is_refused(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    result = await _discover(hass, "tender01", tender_profile)
    for bad in ("tender", "Tender Panel!", "-x-"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"slug": bad}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"slug": "invalid_slug"}


async def test_second_device_gets_a_suffix(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    first = make_entry(tender_profile, "tender01", "tender-panel")
    first.add_to_hass(hass)
    result = await _discover(hass, "tender02", tender_profile)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"slug": "tender-panel"}
    )
    assert result["data"]["slug"] == "tender-panel-2"
    assert "tender-panel-2" in hass.data[LOVELACE_DATA].dashboards


async def test_existing_dashboard_is_never_overwritten(
    hass: HomeAssistant, mqtt_mock: Any, lovelace: None, tender_profile: dict[str, Any]
) -> None:
    mine = {"views": [{"title": "Mine", "cards": []}]}
    await lovelace_io._collection(hass).async_create_item(
        {
            "url_path": "tender-panel",
            "title": "Mine",
            "show_in_sidebar": True,
            "require_admin": False,
        }
    )
    dash = hass.data[LOVELACE_DATA].dashboards["tender-panel"]
    await dash.async_save(mine)

    result = await _discover(hass, "tender01", tender_profile)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"slug": "tender-panel"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert await dash.async_load(False) == mine


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


async def test_options_flow_offers_snapshot_view_only_with_sleep(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    sleeper = make_entry(tender_profile, "tender01", "tender-panel")
    sleeper.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(sleeper.entry_id)
    assert "snapshot_view" in result["data_schema"].schema
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "snapshot_view": "living",
            "presence_grace_hours": 3,
            "alert_max_count": 10,
            "alert_max_age_days": 2,
        },
    )
    assert sleeper.options["presence_grace_hours"] == 3

    wall = vector("announce", "wall-panel")["payload"]
    mains = make_entry(wall, "wall01", "wallpanel-panel")
    mains.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mains.entry_id)
    assert "snapshot_view" not in result["data_schema"].schema
    defaults = result["data_schema"]({})
    assert (
        defaults["presence_grace_hours"],
        defaults["alert_max_count"],
        defaults["alert_max_age_days"],
    ) == (2, 20, 7)
