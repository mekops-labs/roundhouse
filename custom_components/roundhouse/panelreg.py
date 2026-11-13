"""Register the editor page in the Home Assistant sidebar."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PANEL_STATIC_URL, PANEL_URL_PATH

_LOGGER = logging.getLogger(__name__)
PANEL_DIR = Path(__file__).parent / "panel"
ENTRY = "panel.js"
_REGISTERED = f"{DOMAIN}_panel_registered"


def _version() -> str:
    """Return a short hash of the panel files, so a browser reloads a changed panel."""
    digest = hashlib.sha256()
    for path in sorted(PANEL_DIR.glob("*.js")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _manifest_version() -> str:
    """Return the version the manifest declares."""
    manifest = json.loads((PANEL_DIR.parent / "manifest.json").read_text())
    return str(manifest["version"])


async def async_register_panel(hass: HomeAssistant) -> bool:
    """Register the admin-only panel once; return whether it is registered.

    Without the frontend and the HTTP server (a headless instance, a test) there
    is nothing to register.
    """
    if hass.data.get(_REGISTERED):
        return True
    if "frontend" not in hass.config.components or getattr(hass, "http", None) is None:
        _LOGGER.debug("No frontend: the editor page is not registered")
        return False
    version = await hass.async_add_executor_job(_version)
    release = await hass.async_add_executor_job(_manifest_version)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_STATIC_URL, str(PANEL_DIR), cache_headers=False)]
    )
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="roundhouse-panel",
        frontend_url_path=PANEL_URL_PATH,
        module_url=f"{PANEL_STATIC_URL}/{ENTRY}?v={version}",
        sidebar_title="Roundhouse",
        sidebar_icon="mdi:view-dashboard",
        require_admin=True,
        config={"version": release},
    )
    hass.data[_REGISTERED] = True
    return True
