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

Only the `type` strings are verified. Of the keys that restrict a feature's
modes, the frontend confirms `hvac_modes` for `climate-hvac-modes`. The others
(`preset_modes`, `fan_modes`, `swing_modes`, `operation_modes`, `modes`,
`options`) are unverified; confirm each against a dashboard saved by the editor
before relying on it.

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
  `_clear_logger_overwrites`). No release supports the beta yet, so the beta
  job may fail.

## MQTT

Checked on 2026.10.4 and 2026.9.4. The beta could not run the integration
tests (see Test tooling).

- `mqtt.async_publish(hass, topic, payload, qos, retain, encoding=None)` sends
  bytes unchanged. `mqtt.async_subscribe(..., encoding=None)` delivers bytes.
  An empty payload with `retain=True` clears a retained topic.
- A subscription on a wildcard receives the retained messages of the broker
  with `retain=True`. A live message forwarded by a broker has `retain=False`.
  Home Assistant drops a second `retain=True` message on the same topic for a
  subscription, so a test must send live updates with `retain=False`.
- `mqtt.async_subscribe_connection_status(hass, callback)` calls
  `callback(connected: bool)`. Use it to republish after a reconnect.
- The birth message is `birth_message` in the MQTT entry's options (or data):
  an absent key is the default (enabled on `homeassistant/status`), `{}` is
  disabled, and a dict needs `topic`, `payload`, `qos`, and `retain`.
- The mqtt discovery flow runs for every matching message, also for a known
  device. Home Assistant then adds a discovery key to the existing entry, which
  calls the entry's update listeners. A listener that reloads must compare the
  data and options first, or the entry reloads on every announce.

## Flows and schemas

- Home Assistant 2026.10 moved from `voluptuous` to `probatio`; 2026.9 still
  uses `voluptuous`. A flow schema must use the library Home Assistant uses.
  `custom_components/roundhouse/compat.py` picks it from `data_entry_flow`.
- `LOVELACE_DATA` is exported from `homeassistant.components.lovelace.const` on
  every checked release. The package-level import is not in `__all__` before
  the beta.
- `async_call_later` runs a plain function in an executor thread. Mark a
  callback that touches the event loop with `@callback`.
