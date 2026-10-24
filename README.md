# Protegus for Home Assistant (unofficial, v0.1.4)

Reverse-engineered from web.protegus.app. Not affiliated with Protegus.

## Install
1. Copy `custom_components/protegus` into `<HA config>/custom_components/`.
2. Restart HA -> Settings -> Devices & services -> Add integration -> **Protegus**.

## Sign-in
* **E-mail + password** - best: create a separate Protegus user for HA and use its password.
* **Token** - for Google/Apple accounts without a password. Browser DevTools -> Network -> any
  `/v3/api/...` request -> `Authorization: Bearer <token>` **and** the `X-Device-Id` header of the same
  request (Protegus binds the token to that device id, so both are required). Valid ~365 days, then HA asks to re-auth.

## Entities
* `alarm_control_panel` per area: arm away (2), home/stay (3), night/sleep (4), disarm (1). PIN code is required for every arm/disarm; it is sent with the command, the server is told not to remember it (`remember_pin: false`) and HA never stores it.
* `switch` per level-type PGM (toggle only sent if state differs), `button` for pulse PGMs.
* Diagnostic: online (connectivity), signal level.
* `button.<system>_sign_out` (config category): logs out on the Protegus server (`POST /logout`, best effort), removes the token, e-mail and password from Home Assistant (memory and `.storage`), stops the socket and asks you to sign in again. Note: if you pasted a token copied from the web app, logging out invalidates that browser session too.
* Realtime via socket.io (port from `/me`), plus 60 s polling fallback.