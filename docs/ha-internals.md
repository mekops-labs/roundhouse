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

## Translations, icons, and images

Checked on 2026.10.4 and 2026.9.4.

- `translation.async_get_cached_translations(hass, lang, category)` without an
  `integration` only returns the integrations in `hass.config.top_level_components`.
  Pass the integration (the domain, or the platform for `entity`) to read one
  whose translations were loaded with `async_get_translations`. Roundhouse looks
  keys up itself: `component.<domain>.entity_component.<device_class|_>.state.<value>`
  and `...state_attributes.<attribute>.state.<value>`; for platform entities
  `component.<platform>.entity.<domain>.<translation_key>.state.<value>`.
- Core does not translate `unavailable` and `unknown`; the frontend does.
  Roundhouse carries its own small table and falls back to English.
- `icon.async_get_icons(hass, "entity_component", [domain])` returns
  `{domain: {"_": {"default": ..., "state": {...}}, "<device_class>": {...}}}`.
- Block detection of file calls is skipped in tests
  (`skip_for_tests=True`), so a test cannot rely on Home Assistant's warning.
  Roundhouse's tests wrap the rasterizer, the dither, and the name-map load and
  fail when they run on the event-loop thread.
- Sensor display precision lives in the entity registry options:
  `entry.options["sensor"]["display_precision"]`.
- The Material Design Icons font and name map are bundled; see
  `custom_components/roundhouse/mdi/README.md` for the pinned version.

## Service calls

Checked on 2026.10.4 and 2026.9.4.

- `hass.services.async_call(domain, service, data, blocking=True)` waits for
  the service. A missing service raises `ServiceNotFound` (a
  `HomeAssistantError`) with the text `Action <domain>.<service> not found.`
- Wrap the call in `asyncio.timeout(10)`: on expiry the call is cancelled and
  the command result is `timeout`.
- A schema error in a service call can surface as a library exception outside
  `HomeAssistantError`; catch `Exception`, log it, and answer with its type
  and message.
- `async_mock_service(hass, domain, service)` registers a recording service in
  tests; register a coroutine with `hass.services.async_register` to simulate a
  slow or failing service.

## Services, devices, and notify

Checked on 2026.10.4 and 2026.9.4.

- `device_registry.async_get_device(identifiers=...)` is deprecated on 2026.10
  and raises in tests; use `async_get_device_by_identifier(identifier,
  config_entry_id)`. The previous release only has the old name, so
  `deviceinfo.find_device` picks the one that exists.
- A service whose `services.yaml` entry has a `target` of `device` receives
  `call.data["device_id"]`: a list of device registry IDs when targeted.
- `hass.services.async_register(..., supports_response=SupportsResponse.OPTIONAL)`
  lets an automation read a result with `response_variable`.
- `NotifyEntityFeature` is in `notify.const` on 2026.10 and in
  `notify.__init__` on 2026.9.
- An integration that registers services in `async_setup` needs a
  `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)`.
- `asyncio.wait({task}, timeout=...)` leaves the task running when it times
  out; a task created with `hass.async_create_task` is awaited by
  `async_block_till_done`, which hides the timeout in a test that calls it.

## Entities and presence

Checked on 2026.10.4, 2026.9.4, and the 2026.11 beta for imports.

- `TrackerEntity.location_name` and `_attr_location_name` are deprecated, with
  removal in 2027.7, and Home Assistant logs a warning for an override.
  `BaseScannerEntity` (2026.10 and later) takes `is_connected`, where `None`
  keeps the state unknown. `ScannerEntity` is not usable: it takes its unique ID
  from a MAC address and registers no device. The previous release only has
  `TrackerEntity`, so `device_tracker.py` defines the entity for whichever exists.
- `BinarySensorDeviceClass` and the tracker classes are re-exported from the
  package on every release but defined in different modules; mypy needs an
  ignore on the package import.
- `freezer.tick(...)` followed by `async_fire_time_changed(hass)` moves both the
  clock and the timers in a test, which is how the grace period is tested.
- A retained message is delivered to a subscription once; deliver the second and
  later ones with `retain=False`, as a broker does for a live update.

## Panel and websocket

Checked on 2026.10.4 and 2026.9.4.

- `panel_custom.async_register_panel(hass, webcomponent_name=..., frontend_url_path=...,
  module_url=..., sidebar_title=..., sidebar_icon=..., require_admin=True)` adds
  a sidebar panel that loads an ES module. The module defines the custom
  element; Home Assistant sets its `hass`, `narrow`, `route`, and `panel`
  properties. Register the files with
  `hass.http.async_register_static_paths([StaticPathConfig(url, dir, cache_headers=False)])`
  and add `?v=<hash>` to the module URL so a browser reloads a changed panel.
- A panel may only be registered when the frontend and the HTTP server exist;
  a headless instance and the tests have neither, so registration is skipped.
  The panel appears in `hass.data["frontend_panels"]`.
- `hass.connection.subscribeMessage(callback, {type: ...})` in the browser
  matches `connection.subscriptions[msg["id"]] = unsubscribe` and
  `connection.send_message(event_message(msg["id"], payload))` on the server.
  Stacked decorators: `require_admin`, then `websocket_command`, then
  `async_response`. A non-admin user gets `unauthorized`.
- `websocket_api.websocket_command` and its siblings are not re-exported with an
  explicit `__all__`; import them from `websocket_api.decorators`, `.const`,
  `.messages`, and `.connection`.
- A command registered in `async_setup` of an integration with no config entry
  does not exist: the integration is not set up until an entry is.
- A websocket test client blocks forever when nothing is sent; wrap
  `receive_json()` in `asyncio.timeout`.
- Node 24 (the current LTS) does not take a directory for `node --test`; pass a
  glob such as `"tests/js/*.test.mjs"`.
