# Install and secure Roundhouse

Roundhouse needs Home Assistant (the current stable release or the one before
it) with the MQTT integration set up and its birth message enabled.

## Install with HACS

1. In HACS, open the menu, choose **Custom repositories**, and add
   `https://github.com/mekops-labs/roundhouse` as an **Integration**.
2. Download **Roundhouse** and restart Home Assistant.
3. Power on a panel. Home Assistant shows **Discovered: Roundhouse** under
   Settings, Devices & services. Confirm it and choose the URL path of the
   panel's dashboard (for example `tender-panel`). Roundhouse creates the
   dashboard with a starter view, or uses the one that exists, and never
   overwrites it.
4. Edit the dashboard. The **Roundhouse** sidebar entry (administrators only)
   shows each view as the panel will draw it.

To install by hand, copy `custom_components/roundhouse` into the `config`
directory of Home Assistant and restart.

## The MQTT birth message

Panels learn that Home Assistant is running from the birth message on
`homeassistant/status`. It is on by default. Roundhouse raises a repair issue
when it is off: open the MQTT integration, choose **Configure**, and enable the
birth message with the topic `homeassistant/status`.

## Per-device broker credentials and the ACL

Roundhouse opens no connection to the broker. Home Assistant's MQTT integration
publishes, and each panel connects on its own. Give every device its own broker
login, with the device ID as the user name, and Home Assistant its own.

Without an ACL, any client that can reach the broker can publish a command for
any panel. The confirmation step of a lock or an alarm action guards against an
accident, not against a forged message: **the broker ACL is the security
control**. Apply `docs/mosquitto-acl.example`:

1. Create the users, one for Home Assistant and one for each panel:

   ```sh
   mosquitto_passwd -c /mosquitto/config/passwd homeassistant
   mosquitto_passwd /mosquitto/config/passwd <device-id>
   ```

2. Point Mosquitto at the files:

   ```
   allow_anonymous false
   password_file /mosquitto/config/passwd
   acl_file /mosquitto/config/acl
   ```

3. Enter the Home Assistant user and password in the MQTT integration, and the
   device's user and password in the panel's settings.

The ACL lets a device publish only its own `announce`, `availability`, `status`,
and `cmd`, and read only what Roundhouse publishes for it. Only Home Assistant
may publish `meta`, `views`, `state`, `icon`, `alert`, and `result`.

Check it: connect as one device and try to publish `cmd` for another device. The
broker must refuse it silently (Mosquitto drops the message). A command that
reaches Roundhouse without passing the ACL is still checked against the views of
its own device, and any other entity is answered `denied`.

## What is not in version 1

- **TLS.** Version 1 uses plain MQTT with a login on the local network. The
  panel firmware cannot yet verify a server certificate, so TLS would add
  encryption without authenticating the broker. Keep the broker off the
  internet, and keep the devices on a trusted network.
- **Credentials over MQTT.** None travels there. A lock or an alarm panel that
  needs a code fails with the service's own error.

## When something is wrong

Roundhouse reports problems as repair issues (Settings, Repairs):

| Issue | Cause | Fix |
| --- | --- | --- |
| Device sent an unusable profile | an unknown pixel format or a broken announce | update the panel firmware |
| Device uses another contract version | the major versions differ | update Roundhouse or the panel |
| The MQTT birth message is disabled | see above | enable it |
| The dashboard is auto-generated | no cards of its own | open it, choose Edit, take control |
| The dashboard was deleted | removed in the UI | create a dashboard with the same URL path |
| View does not fit | more tiles than the densest layout holds | remove as many tiles as the issue states |

The panel keeps the last version of a view that fitted until you fix the
overflow. A view that never fitted is not shown on the panel. Set `custom_components.roundhouse` to `debug` in the Home Assistant
logger to see every command and its result.
