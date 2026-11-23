"""Data coordinator + realtime socket.io listener for Protegus."""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from typing import Any

import socketio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ProtegusApi, ProtegusAuthError, ProtegusError
from .const import (
    CONF_EMAIL, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN,
    MAX_SCAN_INTERVAL, MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

AREA_KEYS = (
    "id", "name", "queue_no", "status", "alarm_in_memory", "status_time",
    "last_person_name", "alarm_time", "alarm_type",
)
PGM_KEYS = ("id", "name", "queue_no", "on", "type", "hw_assigned", "enabled", "pulse_time_in_seconds")

# If the socket is down, try a fresh connection (new socket token) at most this often.
SOCKET_RETRY_SECONDS = 300


def scan_interval(entry: ConfigEntry) -> timedelta:
    """Polling interval from the entry options, clamped to a safe range."""
    secs = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    try:
        secs = int(secs)
    except (TypeError, ValueError):
        secs = DEFAULT_SCAN_INTERVAL
    return timedelta(seconds=max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, secs)))


def _pick(src: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: src[k] for k in keys if k in src}


class ProtegusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls /systems and applies pushed socket.io updates."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ProtegusApi, system_id: int) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN,
            update_interval=scan_interval(entry),
        )
        self.api = api
        self.system_id = system_id
        self._sio: socketio.AsyncClient | None = None
        self._socket_enabled = False      # set once setup starts the socket
        self._socket_connected = False
        self._socket_ever_connected = False
        self._socket_restarting = False
        self._socket_last_attempt = 0.0

    @property
    def socket_connected(self) -> bool:
        """True while realtime (push) updates are arriving."""
        return self._socket_connected

    # -------------------------------------------------------------- polling
    async def _async_update_data(self) -> dict[str, Any]:
        if not self.api.token:
            raise ConfigEntryAuthFailed("Signed out")
        try:
            systems = await self.api.get_systems()
        except ProtegusAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ProtegusError as err:
            raise UpdateFailed(str(err)) from err

        system = next((s for s in systems if s.get("id") == self.system_id), None)
        if system is None:
            raise UpdateFailed(f"System {self.system_id} not found in account")

        self._maybe_restart_socket()

        status = system.get("status") or {}
        return {
            "info": {
                "name": system.get("name") or f"Protegus {self.system_id}",
                "hw_type": system.get("hwType"),
                "fw_version": system.get("fw_version"),
                "online": bool(system.get("online")),
                "signal": system.get("signalLevel", status.get("signal_level")),
                "no_sleep_stay": bool(system.get("noSleepStay")),
            },
            "areas": {a["id"]: _pick(a, AREA_KEYS) for a in system.get("areas", [])},
            "pgms": {
                p["id"]: _pick(p, PGM_KEYS)
                for p in system.get("pgms", [])
                if p.get("hw_assigned")
            },
        }

    # -------------------------------------------------------------- socket
    async def async_start_socket(self) -> None:
        """Enable realtime updates and connect (called once from setup)."""
        self._socket_enabled = True
        await self._async_connect_socket()

    async def _async_connect_socket(self) -> None:
        self._socket_last_attempt = time.monotonic()
        if not self.api.socket_token or not self.api.socket_port:
            _LOGGER.warning("No socket credentials, falling back to polling only")
            return
        sio = socketio.AsyncClient(reconnection=True, logger=False, engineio_logger=False)
        sio.on("connect", self._on_connect)
        sio.on("disconnect", self._on_disconnect)
        sio.on("auto-reload-channel", self._on_area)
        sio.on("pgm-channel", self._on_pgm)
        sio.on("system-status-reload", self._on_system)
        sio.on("events-channel", self._on_event)
        self._sio = sio
        host = self.api.base_url
        url = f"{host}:{self.api.socket_port}/?token={self.api.socket_token}"
        try:
            await sio.connect(url, socketio_path="socket.io")
            _LOGGER.debug("Protegus socket.io connected")
        except Exception as err:  # noqa: BLE001
            # the connect URL carries the socket token, so never log it
            msg = str(err).replace(str(self.api.socket_token), "***")
            _LOGGER.warning(
                "Protegus socket.io connect failed (%s: %s); polling only",
                type(err).__name__, msg,
            )

    async def async_sign_out(self) -> None:
        """Log out on the server, remove token / e-mail / password from memory and
        storage, then ask for a new sign-in.

        The server-side logout is best effort: if it fails (offline, token already
        invalid) the credentials are still wiped locally.
        """
        await self.async_stop_socket()
        try:
            await self.api.logout()
        except ProtegusError as err:
            _LOGGER.warning("Protegus server logout failed (%s); credentials removed locally only", err)
        self.api.clear_credentials()
        entry = self.config_entry
        data = {
            k: v for k, v in entry.data.items()
            if k not in (CONF_TOKEN, CONF_EMAIL, CONF_PASSWORD)
        }
        self.hass.config_entries.async_update_entry(entry, data=data)
        entry.async_start_reauth(self.hass)
        self.hass.config_entries.async_schedule_reload(entry.entry_id)

    async def async_stop_socket(self) -> None:
        """Disconnect and stop trying to reconnect (unload / sign-out)."""
        self._socket_enabled = False
        await self._async_disconnect_socket()

    async def _async_disconnect_socket(self) -> None:
        sio, self._sio = self._sio, None
        if sio is not None:
            try:
                await sio.disconnect()
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Protegus socket.io disconnect error: %s", type(err).__name__)
        self._set_socket_connected(False)

    def _maybe_restart_socket(self) -> None:
        """Called on every poll: if the socket is down for a while, start over.

        socket.io's own reconnect reuses the original URL, which carries the
        socket token. If that token changed (e.g. after an automatic re-login)
        or the first connect failed, it would never recover by itself.
        """
        if (
            not self._socket_enabled
            or self._socket_restarting
            or (self._sio is not None and self._sio.connected)
            or time.monotonic() - self._socket_last_attempt < SOCKET_RETRY_SECONDS
        ):
            return
        self._socket_restarting = True
        self.config_entry.async_create_background_task(
            self.hass, self._async_restart_socket(), f"{DOMAIN}_socket_restart"
        )

    async def _async_restart_socket(self) -> None:
        try:
            _LOGGER.debug("Protegus socket.io is down, reconnecting with fresh credentials")
            await self._async_disconnect_socket()
            try:
                await self.api.load_profile()  # refreshes socket_token / socket_port
            except ProtegusError as err:
                _LOGGER.debug("Could not refresh socket credentials: %s", err)
                self._socket_last_attempt = time.monotonic()
                return
            if self._socket_enabled:
                await self._async_connect_socket()
        finally:
            self._socket_restarting = False

    def _set_socket_connected(self, connected: bool) -> None:
        if self._socket_connected != connected:
            self._socket_connected = connected
            self.async_update_listeners()

    async def _on_connect(self) -> None:
        reconnect = self._socket_ever_connected
        self._socket_ever_connected = True
        self._set_socket_connected(True)
        if reconnect:
            # pushes sent while we were disconnected are lost: fetch the state
            _LOGGER.debug("Protegus socket.io reconnected, refreshing state")
            await self.async_request_refresh()

    async def _on_disconnect(self, *args: Any) -> None:
        _LOGGER.debug("Protegus socket.io disconnected")
        self._set_socket_connected(False)

    @staticmethod
    def _decode(payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                return None
        return payload if isinstance(payload, dict) else None

    async def _on_area(self, payload: Any) -> None:
        msg = self._decode(payload)
        if not msg or msg.get("system_id") != self.system_id or not self.data:
            return
        area = self.data["areas"].get(msg.get("id"))
        if area is not None:
            area.update(_pick(msg, AREA_KEYS))
            self.async_set_updated_data(self.data)

    async def _on_pgm(self, payload: Any) -> None:
        msg = self._decode(payload)
        if not msg or msg.get("system_id") != self.system_id or not self.data:
            return
        pgm = self.data["pgms"].get(msg.get("id"))
        if pgm is not None:
            pgm.update(_pick(msg, ("on", "enabled")))
            self.async_set_updated_data(self.data)

    async def _on_system(self, payload: Any) -> None:
        msg = self._decode(payload)
        if not msg or msg.get("system_id") != self.system_id or not self.data:
            return
        info = self.data["info"]
        if "system_status" in msg:
            info["online"] = msg["system_status"] == "online"
        if "signal_level" in msg:
            info["signal"] = msg["signal_level"]
        self.async_set_updated_data(self.data)

    async def _on_event(self, payload: Any) -> None:
        """Events carry no state we need; area/pgm channels already update it."""
        return