"""Data coordinator + realtime socket.io listener for Protegus."""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

import socketio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ProtegusApi, ProtegusAuthError, ProtegusError
from .const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN, DOMAIN, POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)

AREA_KEYS = (
    "id", "name", "queue_no", "status", "alarm_in_memory", "status_time",
    "last_person_name", "alarm_time", "alarm_type",
)
PGM_KEYS = ("id", "name", "queue_no", "on", "type", "hw_assigned", "enabled", "pulse_time_in_seconds")


def _pick(src: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: src[k] for k in keys if k in src}


class ProtegusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls /systems and applies pushed socket.io updates."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ProtegusApi, system_id: int) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN,
            update_interval=timedelta(seconds=POLL_INTERVAL),
        )
        self.api = api
        self.system_id = system_id
        self._sio: socketio.AsyncClient | None = None

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
        if not self.api.socket_token or not self.api.socket_port:
            _LOGGER.warning("No socket credentials, falling back to polling only")
            return
        sio = socketio.AsyncClient(reconnection=True, logger=False, engineio_logger=False)
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
            _LOGGER.warning("Protegus socket.io connect failed (%s); polling only", err)

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
        if self._sio is not None:
            try:
                await self._sio.disconnect()
            finally:
                self._sio = None

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
        info["online"] = msg.get("system_status") == "online"
        if "signal_level" in msg:
            info["signal"] = msg["signal_level"]
        self.async_set_updated_data(self.data)

    async def _on_event(self, payload: Any) -> None:
        """Events carry no state we need; area/pgm channels already update it."""
        return
