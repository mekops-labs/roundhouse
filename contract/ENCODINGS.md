# Encodings

## Pixel formats

A display announces one format in `display.format`.

| Format | Bits per pixel | Meaning |
| --- | --- | --- |
| `gray4` | 4 | 0 is black, 15 is white |
| `rgb565` | 16 | red 5 bits, green 6 bits, blue 5 bits |

Roundhouse refuses a device that announces any other format.

## Bitmap layout

Pixels are in row-major order, top row first, left pixel first.

- **4-bit pixels** (`gray4` images and `mask4` icons): two pixels per byte,
  the left pixel in the high nibble. Each row starts on a byte boundary. An
  odd width leaves the low nibble of the last byte of each row at 0.
  Row length is `ceil(width / 2)` bytes.
- **`mask4`** is an alpha mask: 0 is transparent and 15 is opaque. The device
  tints it: grays on a `gray4` display, the state color on an `rgb565` one.
- **`rgb565`**: 2 bytes per pixel, little-endian. Row length is `2 * width`.

The payload length must equal row length times height. A receiver rejects any
other length.

Pack an 8-bit color with `((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)`.

## Rectangles

A rectangle is `[x, y, width, height]` in pixels, with the origin at the top
left of the display. Width and height are at least 1.

## Closed and open values

Closed sets: `kind` (`toggle`, `activate`, `readonly`), `severity`
(`critical`, `warning`, `event`), and `display.format`.

Open sets, where a receiver ignores a value it does not know: `features`,
control `type`, `power_mode`, and the strings of `result`.

Results defined in 1.0: `ok`, `denied`, `invalid`, `needs_confirmation`,
`timeout`. Any other string is an error message from the service call.

## Tile fields

`domain` is the domain of the entity's detail page. Input helpers share the
page of their base domain: `input_number` is `number`, `input_select` is
`select`, `input_boolean` is `switch`, and `input_button` is `button`.
`kind` is what a tap does: `toggle` for `light`, `switch`, `input_boolean`, and
`fan`; `activate` for `scene`, `script`, `button`, and `input_button`;
`readonly` for every other domain. `controls` is absent when the tile restricts
nothing: the detail page then shows every control the entity supports.

## State message

`state/<entity_id>` carries what a tile and its detail page show.

- `text` is the state text in Home Assistant's language. It starts with a
  capital letter. A missing entity reads as unavailable.
- `on` is true while the tile is active and drawn inverted. Off states are
  `off`, `closed`, `locked`, `idle`, `standby`, `disarmed`, `not_home`,
  `unavailable`, `unknown`, `paused`, `none`, and `stopped`. A `climate` entity
  is active while its action is not `off` or `idle`; an alarm panel while it is
  armed, pending, or triggered; a `lock` while it is unlocked.
- `available` is false for `unavailable` and for an entity that does not exist.
- `icon` is the name of the icon in use. The mask is on `icon/<name>`. A name
  outside the bundled icon font becomes `mdi:help-circle-outline`.
- `color` is `[r, g, b]` while the tile is active, else null: a light's own
  color, or its domain's active color. A `gray4` device ignores it.
- `attributes` holds what the detail page of the domain needs (next section).

## Attributes by domain

Every mode and option is a `{value, label}` pair. Other values are plain.

| Domain | Keys |
| --- | --- |
| `climate` | `current_temperature`, `current_humidity`, `temperature`, `target_temp_low`, `target_temp_high`, `humidity`, `min_temp`, `max_temp`, `target_temp_step`; pairs `hvac_action`, `hvac_mode`, `fan_mode`, `preset_mode`, `swing_mode`; lists of pairs `hvac_modes`, `fan_modes`, `preset_modes`, `swing_modes` |
| `water_heater` | `current_temperature`, `temperature`, `min_temp`, `max_temp`; pair `operation_mode`; list `operation_modes` |
| `humidifier` | `current_humidity`, `humidity`, `min_humidity`, `max_humidity`; pair `mode`; list `modes` |
| `fan` | `percentage`, `percentage_step`; pair `preset_mode`; list `preset_modes` |
| `number` | `value`, `min`, `max`, `step`, `unit`, `mode` |
| `select` | pair `option`; list `options` |
| `cover`, `valve` | `position`, `supports_position` |
| `light` | `brightness` (0-255), `color_temp_kelvin`, `min_color_temp_kelvin`, `max_color_temp_kelvin` |

A key is absent when the entity has no such value.

## Commands

A command on `cmd` has a `req` (1 to 64 characters, unique per request) and
one of three forms: an entity action (`entity_id`, `action`, optional `data`
and `confirmed`), an alert action (`alert`, `action_id`, optional `confirmed`),
or an acknowledgment (`ack`). Roundhouse answers each on `result` with the same
`req`. A repeat of a `req` among the last 32 gets the stored result and no
second action.

Results: `ok`, `denied` (the entity is not on the device, the action does not
exist for the domain, or no such alert), `invalid` (a value failed its check),
`needs_confirmation`, `timeout` (the action took longer than 10 s), or the
error text of the action (at most 200 characters). The checks run in this
order: `denied`, `invalid`, `needs_confirmation`, the call.

Entity actions by domain. `data` may only hold the keys listed; any other key
makes the command `invalid`. `confirmed: true` is required for the actions
marked with a dagger.

| Domain | Action and `data` keys |
| --- | --- |
| `light` | `toggle`; `turn_on` (`brightness` 0-255, `color_temp_kelvin` within the entity's range); `turn_off` |
| `switch`, `input_boolean` | `toggle` |
| `fan` | `toggle`; `set_percentage` (`percentage` 0-100); `set_preset_mode` (`preset_mode`) |
| `cover` | `open_cover`, `close_cover`, `stop_cover`; `set_cover_position` (`position` 0-100) |
| `climate` | `set_temperature` (`temperature`, or `target_temp_low` and `target_temp_high`); `set_hvac_mode` (`hvac_mode`); `set_fan_mode` (`fan_mode`); `set_preset_mode` (`preset_mode`); `set_swing_mode` (`swing_mode`); `set_humidity` (`humidity`); `turn_on`; `turn_off` |
| `water_heater` | `set_temperature` (`temperature`); `set_operation_mode` (`operation_mode`); `turn_on`; `turn_off` |
| `humidifier` | `turn_on`; `turn_off`; `set_humidity` (`humidity`); `set_mode` (`mode`) |
| `number`, `input_number` | `set_value` (`value`) |
| `select`, `input_select` | `select_option` (`option`) |
| `valve` | `open_valve`, `close_valve`, `stop_valve`; `set_valve_position` (`position` 0-100) |
| `lock` | `lock`; `unlock`\u2020; `open`\u2020 |
| `alarm_control_panel` | `alarm_arm_home`, `alarm_arm_away`; `alarm_disarm`\u2020 |
| `scene`, `script` | `turn_on` |
| `button`, `input_button` | `press` |

A mode or option must be in the entity's own list and, when the tile carries a
control of that type with `values`, in that list too. A number must lie within
the entity's `min` and `max` (`min_temp` and `max_temp`, `min_humidity` and
`max_humidity`). Every other domain has no actions. A command never carries a
code or any credential.

## Availability, status, and presence

`availability` is the text `online` or `offline`, retained. A device publishes
`online` when it connects and sets `offline` as its last will, so the broker
publishes it when the session ends. `status` carries `battery` (0-100, absent
or null without a battery), `charging` (true, false, or null), and
`power_mode`.

Home Assistant reads presence from `availability` alone. A device is `home`
while it is online. When it goes offline it stays `home` for a grace period
(2 hours by default) and then reads `not_home`, so a device that sleeps with its
radio off between refreshes does not flap. Before the first `availability`
message the state is unknown. A restart of Home Assistant does not restart the
grace period.

## Alerts

`alert/<id>` carries `title`, `message`, `severity`, `time` (Unix seconds),
`read`, `actions`, and `image` and `thumb`. An alert ID is 1 to 32 lowercase
letters and digits. `read` is false until the alert is acknowledged, from the
device or from Home Assistant; Roundhouse then publishes it again with `read`
true. `actions` lists `{id, label, confirm}` only. The device sends an action
as `{req, alert, action_id, confirmed}` and never names a service. A flagged
action (`confirm` true) needs `confirmed: true`, else the result is
`needs_confirmation`.

`image` and `thumb` are `{width, height}` or null. When set, the bitmap is on
`alert/<id>/image` or `alert/<id>/thumb`, in the display format, within the
announced `image_box` or `thumb_box` and the announced `max_payload`. Roundhouse
publishes the bitmaps before the alert that names them, and publishes the alert
again with the images if the snapshot arrives late. An unknown or expired alert
gets the result `denied`, for an action and for an acknowledgment alike.

## Control types

The `controls` list of a tile names the controls of its detail page, in order.
`values`, when present, limits the modes or options to that list.

| `type` | Entity domain |
| --- | --- |
| `hvac_mode`, `preset_mode`, `fan_mode`, `swing_mode`, `target_temperature`, `target_humidity` | `climate` |
| `fan_speed`, `fan_preset_mode` | `fan` |
| `operation_mode` | `water_heater` |
| `humidifier_mode`, `humidifier_toggle` | `humidifier` |
| `number` | `number`, `input_number` |
| `select` | `select`, `input_select` |
| `cover_open_close`, `cover_position` | `cover` |
| `valve_open_close`, `valve_position` | `valve` |
| `light_brightness`, `light_color_temp` | `light` |

## Mode and option pairs

In `state.attributes`, every mode and option is an object
`{"value": "...", "label": "..."}`. A device sends `value` back in a command
and shows `label`.
