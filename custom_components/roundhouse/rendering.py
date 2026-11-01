"""Render entity states, icons, and images for a device.

The Home Assistant side of the pure formatters: translations, the entity
registry, local time, and image fetching.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import icon as icon_helper
from homeassistant.helpers import translation
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import codec, icons, images, stateview, textfmt

# Alert snapshots (the fetch limits).
FETCH_TIMEOUT = 10
FETCH_MAX_BYTES = 5 * 1024 * 1024


class ImageFetchError(RuntimeError):
    """An alert image could not be fetched."""


class Translator:
    """Translate states and attribute values with Home Assistant's translations."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the translator."""
        self._hass = hass
        self._icons: dict[str, dict[str, Any]] = {}
        self._platform_icons: dict[str, dict[str, Any]] = {}

    @property
    def language(self) -> str:
        """Return Home Assistant's configured language."""
        return self._hass.config.language

    async def async_load(self, domains: set[str], platforms: set[str]) -> None:
        """Load the translations and icons of these domains and platforms."""
        lang = self.language
        if domains:
            await translation.async_get_translations(
                self._hass, lang, "entity_component", domains
            )
            self._icons.update(
                await icon_helper.async_get_icons(
                    self._hass, "entity_component", sorted(domains)
                )
            )
        if platforms:
            await translation.async_get_translations(
                self._hass, lang, "entity", platforms
            )
            self._platform_icons.update(
                await icon_helper.async_get_icons(
                    self._hass, "entity", sorted(platforms)
                )
            )

    def _cached(self, category: str, integration: str) -> dict[str, str]:
        return translation.async_get_cached_translations(
            self._hass, self.language, category, integration
        )

    def state(
        self,
        domain: str,
        value: str,
        device_class: str | None = None,
        platform: str | None = None,
        translation_key: str | None = None,
    ) -> str:
        """Translate a state, in the order Home Assistant's frontend uses."""
        if platform and translation_key:
            key = (
                f"component.{platform}.entity.{domain}.{translation_key}.state.{value}"
            )
            found = self._cached("entity", platform).get(key)
            if found:
                return found
        table = self._cached("entity_component", domain)
        for cls in (device_class, "_"):
            if cls is None:
                continue
            found = table.get(
                f"component.{domain}.entity_component.{cls}.state.{value}"
            )
            if found:
                return found
        return value

    def attr(
        self,
        domain: str,
        name: str,
        value: str,
        device_class: str | None = None,
        platform: str | None = None,
        translation_key: str | None = None,
    ) -> str:
        """Translate the value of a state attribute."""
        if platform and translation_key:
            key = (
                f"component.{platform}.entity.{domain}.{translation_key}"
                f".state_attributes.{name}.state.{value}"
            )
            found = self._cached("entity", platform).get(key)
            if found:
                return found
        table = self._cached("entity_component", domain)
        for cls in (device_class, "_"):
            if cls is None:
                continue
            key = (
                f"component.{domain}.entity_component.{cls}"
                f".state_attributes.{name}.state.{value}"
            )
            found = table.get(key)
            if found:
                return found
        return value

    def icon(
        self,
        domain: str,
        state: str | None,
        device_class: str | None,
        platform: str | None,
        translation_key: str | None,
    ) -> str | None:
        """Return the translated, state-dependent icon, if any."""
        if platform and translation_key:
            entry = (
                self._platform_icons.get(platform, {})
                .get(domain, {})
                .get(translation_key)
            )
            if entry:
                return icons.translated_icon({"_": entry}, state, None)
        return icons.translated_icon(self._icons.get(domain), state, device_class)


def _local(value: str, device_class: str) -> str:
    if device_class == "date":
        day = dt_util.parse_date(value)
        return day.isoformat() if day else value
    moment: datetime | None = dt_util.parse_datetime(value)
    if moment is None:
        return value
    return dt_util.as_local(moment).strftime("%Y-%m-%d %H:%M")


def entity_context(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Collect what rendering needs to know about an entity."""
    state = hass.states.get(entity_id)
    entry = er.async_get(hass).async_get(entity_id)
    domain = entity_id.split(".", 1)[0]
    attrs = dict(state.attributes) if state else {}
    options: dict[str, Any] = (entry.options.get("sensor") if entry else None) or {}
    return {
        "domain": domain,
        "state": state.state if state else None,
        "attrs": attrs,
        "device_class": attrs.get("device_class")
        or (entry.device_class or entry.original_device_class if entry else None),
        "platform": entry.platform if entry else None,
        "translation_key": entry.translation_key if entry else None,
        "registry_icon": (entry.icon or entry.original_icon) if entry else None,
        "precision": options.get("display_precision"),
    }


def render_state(
    hass: HomeAssistant,
    translator: Translator,
    entity_id: str,
    card_icon: str | None = None,
) -> dict[str, Any]:
    """Return the `state/<entity_id>` payload of an entity."""
    c = entity_context(hass, entity_id)
    domain, state, attrs = c["domain"], c["state"], c["attrs"]
    dc, platform, key = c["device_class"], c["platform"], c["translation_key"]

    def tr(value: str) -> str:
        return translator.state(domain, value, dc, platform, key)

    def tra(name: str, value: str) -> str:
        return translator.attr(domain, name, value, dc, platform, key)

    def label(name: str, value: str) -> str:
        shown = tra(name, value)
        shown = shown if shown != value else tr(value)
        return shown[:1].upper() + shown[1:]

    if state is None:
        text = textfmt.common_word(translator.language, textfmt.STATE_UNAVAILABLE)
    else:
        ctx = textfmt.Ctx(
            language=translator.language,
            tr=tr,
            tra=tra,
            local=_local,
            temperature_unit=hass.config.units.temperature_unit,
            precision=c["precision"],
            unit=attrs.get("unit_of_measurement"),
            device_class=dc,
        )
        text = textfmt.format_state(domain, state, attrs, ctx)

    icon_name = icons.resolve_icon(
        card_icon=card_icon,
        registry_icon=c["registry_icon"],
        attribute_icon=attrs.get("icon"),
        translated=translator.icon(domain, state, dc, platform, key),
        domain=domain,
    )
    features = attrs.get("supported_features", 0)
    return stateview.message(
        domain,
        state,
        attrs,
        features if isinstance(features, int) else 0,
        text,
        icons.effective_name(icon_name),
        label,
    )


def entity_domains(
    hass: HomeAssistant, entity_ids: set[str]
) -> tuple[set[str], set[str]]:
    """Return the domains and the platforms of these entities."""
    registry = er.async_get(hass)
    domains = {e.split(".", 1)[0] for e in entity_ids}
    platforms = set()
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        if entry and entry.translation_key:
            platforms.add(entry.platform)
    return domains, platforms


async def async_icon_payload(hass: HomeAssistant, name: str, size: int) -> bytes:
    """Rasterize an icon to a `mask4` payload, off the event loop."""

    def work() -> bytes:
        return codec.encode_bitmap("mask4", size, size, icons.mask(name, size))

    return await hass.async_add_executor_job(work)


async def async_fetch_image(
    hass: HomeAssistant,
    *,
    camera_entity: str | None = None,
    image_url: str | None = None,
) -> bytes:
    """Fetch an alert snapshot from a camera or a URL."""
    if camera_entity:
        from homeassistant.components import camera

        try:
            image = await camera.async_get_image(hass, camera_entity)
        except Exception as err:
            raise ImageFetchError(f"camera {camera_entity}: {err}") from err
        content = bytes(image.content)
        if len(content) > FETCH_MAX_BYTES:
            raise ImageFetchError("camera image over the size cap")
        return content
    if not image_url or not image_url.lower().startswith(("http://", "https://")):
        raise ImageFetchError("image URL must be http or https")
    import aiohttp

    session = async_get_clientsession(hass)
    try:
        async with session.get(
            image_url, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        ) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                body += chunk
                if len(body) > FETCH_MAX_BYTES:
                    raise ImageFetchError("image over the size cap")
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ImageFetchError(f"fetch failed: {err}") from err
    return bytes(body)


async def async_encode_image(
    hass: HomeAssistant,
    data: bytes,
    fmt: str,
    box: tuple[int, int],
    max_bytes: int,
) -> tuple[bytes, int, int] | None:
    """Scale and encode an image off the event loop; None when it cannot fit."""
    try:
        return await hass.async_add_executor_job(
            images.encode_within, data, fmt, box, max_bytes
        )
    except images.ImageError as err:
        raise ImageFetchError(f"undecodable image: {err}") from err
