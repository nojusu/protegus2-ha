<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/protegus/brand/dark_logo@2x.png">
    <img src="custom_components/protegus/brand/logo@2x.png" alt="Protegus" width="420">
  </picture>
</p>

<h1 align="center">Protegus2 for Home Assistant</h1>

<p align="center">
  <a href="https://hacs.xyz"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg" alt="HACS Custom"></a>
  <img src="https://img.shields.io/badge/version-0.1.4-blue.svg" alt="Version 0.1.4">
  <img src="https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5.svg" alt="Home Assistant 2025.1+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License"></a>
</p>

**Home Assistant integration for Protegus2 alarm systems (unofficial, v0.1.4).**

Reverse-engineered from `web.protegus.app`: Protegus has an API but no public documentation. This project is not affiliated with or endorsed by Protegus. Made using Claude AI.

> ⚠️ **Important.** An alarm system is a security system. This integration relies on an undocumented cloud API that can change without notice. Use it at your own risk and do not make it your only means of control. Always keep the official Protegus app or keypad available.

## Features

- Control alarm areas: arm away, arm home, arm night, disarm.
- PIN code is required for **every** arm/disarm and is never stored.
- PGM outputs as switches and pulse buttons.
- Realtime updates via socket.io, 60 s polling as fallback.
- Diagnostics: system online state and signal level.
- **Sign out** button: ends the server session and wipes the token and login from HA.
- Sign in with e-mail and password, or with a token (Google / Apple accounts).
- Translations: Lithuanian and English.

## Requirements

- Home Assistant **2025.1** or newer (the logo in the integration list appears from 2026.3).
- A Protegus account with at least one system.

## Installation

### HACS (recommended)

1. HACS → three-dot menu → **Custom repositories**.
2. Paste `https://github.com/nojusu/protegus2-ha` into the **Repository** field.
3. Category: **Integration** → **Add**.
4. Find **Protegus** and click **Download**.
5. Restart Home Assistant.
6. **Settings → Devices & services → Add integration → Protegus**.

### Manual

1. Copy `custom_components/protegus` into `<HA config>/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration → Protegus**.

## Configuration

Everything is configured from the Home Assistant UI (config flow). First choose how to sign in.

### Option 1: e-mail and password

The best choice. **Create a separate Protegus user for Home Assistant** and use its password. HA then has its own session, independent of your browser or phone.

### Option 2: token (Google / Apple accounts without a password)

1. Sign in at [web.protegus.app](https://web.protegus.app) in your browser.
2. Press **F12** → **Network** and reload the page (F5).
3. Click any request whose URL is `/v3/api/...` (e.g. `me` or `systems`).
4. Under **Request Headers**, copy:
   - `Authorization: Bearer <token>` (without the word `Bearer`),
   - `X-Device-Id: <ID>`.
5. Paste both into the HA form. **They must come from the same request**, because Protegus binds the token to the device ID.

The token is valid for about 365 days, then HA asks you to sign in again. Treat the token like a password and never share it.

If you use a token from your browser session, signing out in HA (**Sign out**) also ends that browser session. A dedicated account for HA is recommended.

### Region and system

Pick the region your account belongs to: **Europe** (`web.protegus.app`), **North America** (`ohi.protegus.app`) or **Asia** (`sin.protegus.app`). If the account has several systems, pick one. Add the integration again for another system.

## Entities

| Entity | Type | Description |
|---|---|---|
| Area | `alarm_control_panel` | Arm away, arm home, arm night, disarm. Home and night modes appear only if the system supports them. |
| PGM (level type) | `switch` | Turns the output on or off. The command is only sent if the state differs. |
| PGM (pulse) | `button` | Triggers an output pulse. |
| Online | `binary_sensor` (diagnostic) | Whether the alarm panel is connected to Protegus. |
| Signal level | `sensor` (diagnostic) | Connection signal strength. |
| Sign out | `button` (config) | Sign out, see below. |

## PIN code and automations

A PIN code is **required for all** arm and disarm actions. HA does not store it: the code is sent with the command and the server is told not to remember it (`remember_pin: false`). In the alarm card you enter the code every time.

In automations, pass the code with the `code` parameter:

```yaml
action: alarm_control_panel.alarm_arm_away
target:
  entity_id: alarm_control_panel.protegus_area
data:
  code: !secret protegus_pin
```

A call without a PIN is rejected on the HA side. If you keep the PIN in `secrets.yaml`, remember that anyone with access to HA and its backups can read it.

## Sign out

The **Sign out** button (on the device page, in the configuration section):

1. closes the socket connection;
2. calls Protegus `POST /logout`, which ends the session on the server (best effort, it continues if this fails);
3. removes the token, e-mail and password from memory and `.storage`;
4. asks you to sign in again.

The button acts immediately, without a confirmation.

## Security and privacy

- The password and token are stored **in plain text** in the HA config entry (`.storage/core.config_entries`), like in most HA integrations. Protect HA access and your backups.
- The PIN code is never stored (see above).
- The integration only talks to Protegus servers over HTTPS, with no third parties.
- Recommendations: a dedicated Protegus account for HA, do not expose the alarm entity to voice assistants, never publish tokens, HAR files or logs containing secrets (`.gitignore` ignores HAR files).
- The integration does not limit PIN attempts. Protection against guessing depends on the Protegus server.

## Known limitations

- **No zone (sensor) entities.** The Protegus app does not show zones, so the API does not expose them and HA cannot display them.
- Accounts with 2FA are not supported (for now).
- The unofficial API can change at any time and the integration may stop working.

## Troubleshooting

| Problem | What to do |
|---|---|
| **Sign-in failed** with a token | Check that `X-Device-Id` is from the same request as the token. Check the region. The token must be copied completely. If you signed out in the browser, the token is invalid: sign in and copy a new one. |
| **Protegus: wrong PIN** | The server rejected the PIN. Check the code. |
| **Protegus: PIN code is required** | Enter the code in the card or add `code:` in the automation. |
| Entities *unavailable* | Check the **Online** diagnostic entity and that HA has internet access. |
| Asked to sign in after ~a year | The token expired, provide a new one through the HA notification. |

Debug log (remove tokens and codes before sharing it):

```yaml
logger:
  default: warning
  logs:
    custom_components.protegus: debug
```

## Development

You can try the API without Home Assistant:

```bash
pip install aiohttp
python scripts/probe.py --token <JWT> --device-id <X-Device-Id>
```

Layout:

```
custom_components/protegus/   the integration (api.py, coordinator.py, config_flow.py, ...)
scripts/probe.py              API smoke test without HA
```

Report bugs and ideas in [Issues](https://github.com/nojusu/protegus2-ha/issues). Include your HA and integration versions and a log **without tokens, passwords or PIN codes**.

## License and credits

License: [MIT](LICENSE). "Protegus" is a trademark of its owner, this project is not affiliated with it. Logo font: Poppins Bold (SIL Open Font License). Made using Claude AI (Anthropic).
