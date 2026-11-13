"""Entity states and icons reach the device as retained topics."""

from __future__ import annotations

import json
import sys
import types
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.roundhouse import codec, rendering
from custom_components.roundhouse.const import DOMAIN, STALE_SETTLE_SECONDS

from .conftest import announce, vector
from .helpers import PREFIX, advance, cards, config, save, setup, tiles


def sent(mqtt_mock: Any, topic: str) -> list[bytes]:
    return [
        c.args[1]
        for c in mqtt_mock.async_publish.call_args_list
        if c.args[0] == PREFIX + topic
    ]


def last_state(mqtt_mock: Any, entity_id: str) -> dict[str, Any]:
    return json.loads(sent(mqtt_mock, f"state/{entity_id}")[-1])  # type: ignore[no-any-return]


async def test_states_and_icons_are_published_on_setup(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "off", {"friendly_name": "Lamp"})
    hass.states.async_set(
        "light.l1", "on", {"brightness": 255, "rgb_color": [255, 0, 0]}
    )
    entry = await setup(
        hass, tender_profile, config(("home", cards("light.l0", "light.l1")))
    )
    off, on = last_state(mqtt_mock, "light.l0"), last_state(mqtt_mock, "light.l1")
    assert (off["text"], off["on"], off["icon"]) == ("Off", False, "mdi:lightbulb-off")
    assert (on["text"], on["color"], on["icon"]) == (
        "On · 100%",
        [255, 0, 0],
        "mdi:lightbulb",
    )
    for name in ("mdi_lightbulb-off", "mdi_lightbulb"):
        (mask,) = sent(mqtt_mock, f"icon/{name}")
        px = tender_profile["icon_px"]
        assert len(mask) == px * ((px + 1) // 2)  # mask4, rows padded to bytes
        assert codec.decode_bitmap("mask4", px, px, mask)
    assert hass.data[DOMAIN][entry.entry_id].publisher.owned >= {
        "state/light.l0",
        "state/light.l1",
        "icon/mdi_lightbulb",
        "icon/mdi_lightbulb-off",
    }
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_state_change_is_published_and_an_unchanged_one_is_not(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "off")
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    assert len(sent(mqtt_mock, "state/light.l0")) == 1

    hass.states.async_set("light.l0", "off", {"unrelated": 1})  # same message
    await hass.async_block_till_done()
    assert len(sent(mqtt_mock, "state/light.l0")) == 1

    hass.states.async_set("light.l0", "on", {"brightness": 128})
    await hass.async_block_till_done()
    assert last_state(mqtt_mock, "light.l0")["text"] == "On · 50%"
    assert len(sent(mqtt_mock, "state/light.l0")) == 2


async def test_unused_icons_are_cleared_when_the_state_changes(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "off")
    entry = await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    device = hass.data[DOMAIN][entry.entry_id]
    assert "icon/mdi_lightbulb-off" in device.publisher.owned
    hass.states.async_set("light.l0", "on")
    await hass.async_block_till_done()
    assert "icon/mdi_lightbulb" in device.publisher.owned
    assert "icon/mdi_lightbulb-off" not in device.publisher.owned
    assert (PREFIX + "icon/mdi_lightbulb-off", b"", 1, True) in [
        tuple(c.args[:4]) for c in mqtt_mock.async_publish.call_args_list
    ]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_shared_icon_is_published_once(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    for i in range(3):
        hass.states.async_set(f"light.l{i}", "on")
    await setup(
        hass,
        tender_profile,
        config(("home", cards("light.l0", "light.l1", "light.l2"))),
    )
    assert len(sent(mqtt_mock, "icon/mdi_lightbulb")) == 1
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_removing_a_tile_clears_its_state_and_icon(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    hass.states.async_set("lock.door", "locked")
    entry = await setup(
        hass, tender_profile, config(("home", cards("light.l0", "lock.door")))
    )
    device = hass.data[DOMAIN][entry.entry_id]
    assert {"state/lock.door", "icon/mdi_lock"} <= device.publisher.owned
    await advance(hass, STALE_SETTLE_SECONDS + 1)

    await save(hass, config(("home", cards("light.l0"))))
    assert "state/lock.door" not in device.publisher.owned
    assert "icon/mdi_lock" not in device.publisher.owned
    assert "state/light.l0" in device.publisher.owned


async def test_a_card_icon_overrides_the_entity_icon(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    await setup(
        hass,
        tender_profile,
        config(("home", cards("light.l0", **{"light.l0": "mdi:ceiling-light"}))),
    )
    assert last_state(mqtt_mock, "light.l0")["icon"] == "mdi:ceiling-light"
    assert sent(mqtt_mock, "icon/mdi_ceiling-light")
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_missing_entity_is_published_as_unavailable(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    await setup(hass, tender_profile, config(("home", cards("light.nowhere"))))
    msg = last_state(mqtt_mock, "light.nowhere")
    assert (msg["text"], msg["available"]) == ("Unavailable", False)
    hass.states.async_set("light.nowhere", "on")
    await hass.async_block_till_done()
    assert last_state(mqtt_mock, "light.nowhere")["available"] is True
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_the_polish_language_reaches_the_device(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.config.language = "pl"
    hass.states.async_set("lock.door", "locked")
    await setup(hass, tender_profile, config(("home", cards("lock.door"))))
    assert last_state(mqtt_mock, "lock.door")["text"] == "Zablokowano"
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_meta_only_mode_clears_states_and_icons(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    hass.states.async_set("light.l0", "on")
    entry = await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    device = hass.data[DOMAIN][entry.entry_id]
    assert "state/light.l0" in device.publisher.owned
    announce(hass, "tender01", vector("announce", "major-mismatch")["payload"])
    await hass.async_block_till_done()
    assert device.publisher.owned == {"meta"}
    hass.states.async_set("light.l0", "off")  # nothing is published any more
    await hass.async_block_till_done()
    assert device.publisher.owned == {"meta"}
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_a_reconnect_republishes_states_and_icons(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    from homeassistant.components.mqtt.const import MQTT_CONNECTION_STATE
    from homeassistant.helpers.dispatcher import async_dispatcher_send

    hass.states.async_set("light.l0", "on")
    await setup(hass, tender_profile, config(("home", cards("light.l0"))))
    await advance(hass, STALE_SETTLE_SECONDS + 1)
    mqtt_mock.async_publish.reset_mock()
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, False)
    await hass.async_block_till_done()
    async_dispatcher_send(hass, MQTT_CONNECTION_STATE, True)
    await hass.async_block_till_done(wait_background_tasks=True)
    topics = {c.args[0] for c in mqtt_mock.async_publish.call_args_list}
    assert {PREFIX + "state/light.l0", PREFIX + "icon/mdi_lightbulb"} <= topics


async def test_an_oversized_state_is_dropped_not_fatal(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    profile = json.loads(json.dumps(tender_profile))
    profile["limits"]["max_payload"] = 3000  # the icon mask fits, a fat state does not
    hass.states.async_set(
        "select.s", "a", {"options": [f"option-{i}" for i in range(200)]}
    )
    hass.states.async_set("light.l0", "on")
    entry = await setup(hass, profile, config(("home", cards("select.s", "light.l0"))))
    device = hass.data[DOMAIN][entry.entry_id]
    assert "state/select.s" not in device.publisher.owned
    assert "state/light.l0" in device.publisher.owned
    await advance(hass, STALE_SETTLE_SECONDS + 1)


async def test_entities_in_overflowing_views_are_not_published(
    hass: HomeAssistant, mqtt_mock: Any, tender_profile: dict[str, Any]
) -> None:
    for i in range(18):
        hass.states.async_set(f"light.l{i}", "on")
    await setup(hass, tender_profile, config(("big", tiles(18))))
    assert not [t for t in sent(mqtt_mock, "state/light.l0")]
    await advance(hass, STALE_SETTLE_SECONDS + 1)


# --- images -----------------------------------------------------------------


async def test_fetch_rejects_other_schemes(hass: HomeAssistant) -> None:
    for url in ("file:///etc/passwd", "ftp://host/x", "", "javascript:1"):
        with pytest.raises(rendering.ImageFetchError, match="http or https"):
            await rendering.async_fetch_image(hass, image_url=url)


async def test_fetch_from_a_url(hass: HomeAssistant, aioclient_mock: Any) -> None:
    aioclient_mock.get("http://cam.local/a.png", content=b"PNGDATA")
    assert (
        await rendering.async_fetch_image(hass, image_url="http://cam.local/a.png")
        == b"PNGDATA"
    )


async def test_fetch_enforces_the_size_cap(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    aioclient_mock.get(
        "http://cam.local/big", content=b"x" * (rendering.FETCH_MAX_BYTES + 1)
    )
    with pytest.raises(rendering.ImageFetchError, match="size cap"):
        await rendering.async_fetch_image(hass, image_url="http://cam.local/big")


async def test_fetch_reports_http_and_network_errors(
    hass: HomeAssistant, aioclient_mock: Any
) -> None:
    aioclient_mock.get("http://cam.local/404", status=404)
    with pytest.raises(rendering.ImageFetchError, match="fetch failed"):
        await rendering.async_fetch_image(hass, image_url="http://cam.local/404")
    aioclient_mock.get("http://cam.local/slow", exc=TimeoutError())
    with pytest.raises(rendering.ImageFetchError, match="fetch failed"):
        await rendering.async_fetch_image(hass, image_url="http://cam.local/slow")


async def test_fetch_uses_a_ten_second_timeout(hass: HomeAssistant) -> None:
    assert rendering.FETCH_TIMEOUT == 10
    assert rendering.FETCH_MAX_BYTES == 5 * 1024 * 1024


async def test_fetch_from_a_camera(hass: HomeAssistant) -> None:
    class Image:
        content = b"JPEG"

    async def fake(_hass: Any, entity_id: str) -> Image:
        assert entity_id == "camera.gate"
        return Image()

    async def boom(_hass: Any, entity_id: str) -> Image:
        raise RuntimeError("offline")

    module = types.ModuleType("homeassistant.components.camera")
    module.async_get_image = fake  # type: ignore[attr-defined]
    with patch.dict(sys.modules, {"homeassistant.components.camera": module}):
        assert (
            await rendering.async_fetch_image(hass, camera_entity="camera.gate")
            == b"JPEG"
        )

        class Huge:
            content = b"x" * (rendering.FETCH_MAX_BYTES + 1)

        async def huge(_hass: Any, entity_id: str) -> Huge:
            return Huge()

        module.async_get_image = huge  # type: ignore[attr-defined]
        with pytest.raises(rendering.ImageFetchError, match="size cap"):
            await rendering.async_fetch_image(hass, camera_entity="camera.gate")
        module.async_get_image = boom  # type: ignore[attr-defined]
        with pytest.raises(rendering.ImageFetchError, match=r"camera\.gate"):
            await rendering.async_fetch_image(hass, camera_entity="camera.gate")


async def test_encode_runs_in_the_executor_and_reports_bad_images(
    hass: HomeAssistant,
) -> None:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "blue").save(buf, "PNG")
    result = await rendering.async_encode_image(
        hass, buf.getvalue(), "gray4", (32, 32), 10_000
    )
    assert result is not None and result[1:] == (32, 24)
    assert (
        await rendering.async_encode_image(hass, buf.getvalue(), "rgb565", (32, 32), 10)
        is None
    )
    with pytest.raises(rendering.ImageFetchError, match="undecodable"):
        await rendering.async_encode_image(hass, b"junk", "gray4", (32, 32), 10_000)


async def test_the_wall_panel_gets_masks_at_its_own_icon_size(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    from .conftest import make_entry

    wall = vector("announce", "wall-panel")["payload"]
    hass.states.async_set("light.l0", "on", {"rgb_color": [0, 255, 0]})
    entry = make_entry(wall, "tender01")
    await setup(hass, wall, config(("home", cards("light.l0"))), entry=entry)
    (mask,) = sent(mqtt_mock, "icon/mdi_lightbulb")
    assert len(mask) == 48 * 24  # icon_px 48, two pixels per byte
    assert last_state(mqtt_mock, "light.l0")["color"] == [0, 255, 0]
    await advance(hass, STALE_SETTLE_SECONDS + 1)
