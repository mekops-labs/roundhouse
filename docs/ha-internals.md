# Home Assistant internals

Checked on Home Assistant 2026.10.4 (stable), 2026.9.4 (previous release), and
2026.11.0b1 (beta). The behavior below was identical on stable and beta, and
the code involved did not change between them except where noted.

## Dashboards (Lovelace)

### Creating a storage dashboard

Lovelace keeps its `DashboardsCollection` in a local variable of its setup
function. It is not in `hass.data`. The only route from an integration is the
websocket command handlers Lovelace registers:

1. Read `hass.data["websocket_api"]["lovelace/dashboards/list"][0]`. It is a
   bound method of `DashboardsCollectionWebSocket`.
2. Read `.__self__.storage_collection`. The create handler is wrapped by
   `require_admin` and `async_response`, so it has no `__self__`; use the
   list handler. Walk `__wrapped__` until an object has `__self__`.
3. Call `await collection.async_create_item({...})` with `url_path`, `title`,
   `icon`, `show_in_sidebar`, and `require_admin`.

Observed results:

- The new item has `id` equal to the `url_path` with `-` replaced by `_`, and
  `mode` `storage`.
- A `url_path` without a hyphen raises `Invalid` ("Url path
  needs to contain a hyphen"). A used path raises `HomeAssistantError`.
- A new dashboard has no stored config. `async_get_info()` returns
  `{"mode": "auto-gen"}` and `async_load()` raises `ConfigNotFound`. Save the
  starter view explicitly with `async_save`.
- `collection.async_delete_item(item["id"])` removes the dashboard from
  `hass.data[LOVELACE_DATA].dashboards`.

This path relies on private structure. Isolate it in one module and cover it
with a test on every Home Assistant channel.

### Loading a dashboard by `url_path`

```python
from homeassistant.components.lovelace import LOVELACE_DATA

dash = hass.data[LOVELACE_DATA].dashboards.get(url_path)  # None: deleted
info = await dash.async_get_info()  # {"mode": "storage", "views": n}
config = await dash.async_load(False)  # raises ConfigNotFound
```

- `mode` `auto-gen` (strategy dashboard, no stored cards): `async_load` raises
  `ConfigNotFound`.
- A YAML dashboard has `mode` `yaml`.

### The `lovelace_updated` event

- Saving a dashboard config fires `lovelace_updated` with `{"url_path": ...}`.
  The default dashboard has `url_path` `None`.
- `async_load` raises `ConfigNotFound` (from `lovelace.const`, same on all
  checked releases) for a dashboard that was created and never saved.
- Deleting a dashboard fires it too. After the event, check that the
  dashboard still exists before loading it.
- The constant `EVENT_LOVELACE_UPDATED` moved from
  `homeassistant.components.lovelace.const` to `homeassistant.const` in the
  beta. Use the string `"lovelace_updated"`.

## Tile card features

Feature `type` strings present in the frontend of stable (20260930.5) and beta
(20261028.1):

| Feature | `type` |
| --- | --- |
| HVAC modes | `climate-hvac-modes` |
| Preset modes | `climate-preset-modes` |
| Fan modes | `climate-fan-modes` |
| Swing modes | `climate-swing-modes`, `climate-swing-horizontal-modes` |
| Target temperature | `target-temperature` |
| Target humidity | `target-humidity` |
| Fan speed | `fan-speed` |
| Fan preset modes | `fan-preset-modes` |
| Water-heater operation modes | `water-heater-operation-modes` |
| Humidifier modes | `humidifier-modes` |
| Humidifier toggle | `humidifier-toggle` |
| Numeric input | `numeric-input` |
| Select options | `select-options` |
| Cover open and close | `cover-open-close` |
| Cover position | `cover-position` |
| Valve open and close | `valve-open-close` |
| Valve position | `valve-position` |
| Light brightness | `light-brightness` |
| Light color temperature | `light-color-temp` |

The frontend reads these keys from a feature's config to restrict its modes:
`hvac_modes`, `preset_modes`, `fan_modes`, `swing_modes`, `operation_modes`,
`modes`, and `options`. Roundhouse maps them as follows; the editor writes
only `hvac_modes` and `style` by default, so a mode list appears only when the
user restricts it:

| Feature | Key |
| --- | --- |
| `climate-hvac-modes` | `hvac_modes` |
| `climate-preset-modes`, `fan-preset-modes` | `preset_modes` |
| `climate-fan-modes` | `fan_modes` |
| `climate-swing-modes` | `swing_modes` |
| `water-heater-operation-modes` | `operation_modes` |
| `humidifier-modes` | `modes` |
| `select-options` | `options` |

The key names are present in the frontend, but the pairing of key and feature
type comes from the documented card options, not from the compiled frontend.

## Translation and icon helpers

Present with identical signatures on stable and beta:

- `homeassistant.helpers.translation.async_get_translations(hass, language,
  category, integrations=None, config_flow=None)`
- `homeassistant.helpers.translation.async_get_cached_translations(hass,
  language, category, integration=None)`
- `homeassistant.helpers.translation.async_translate_state(hass, state, domain,
  platform, translation_key, device_class)`
- `homeassistant.helpers.icon.async_get_icons(hass, category,
  integrations=None)`

## Test tooling

`pytest-homeassistant-custom-component` pins one Home Assistant release per
version. One version cannot test two releases:

- Stable: version 0.13.375 with 2026.10.4.
- Previous release: the resolver picks 0.13.367 with 2026.9.4.
- Beta 2026.11.0b1: version 0.13.375 fails at import (`httpx` alias, then
  `_clear_logger_overwrites`), so the integration tests cannot run. The
  `respx` pytest plugin also imports `httpx` before Home Assistant aliases it;
  run the plain tests with `-p no:homeassistant -p no:respx --noconftest`. No
  plugin release supports the beta yet.

## Test helpers

- `async_fire_time_changed(hass, t)` adds up to 0.5 s of slack to `t`, so a
  timer due in 2 s fires for an advance of 1.5 s. Advance by less than the
  wait minus 0.5 s to assert that nothing fired yet.
- A config entry that depends on `lovelace` sets Lovelace up for real in tests;
  a test that wants a missing dashboard needs no fixture for it.
