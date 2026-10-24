"""The Protegus integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ProtegusApi, ProtegusAuthError, ProtegusConnectionError, ProtegusError
from .const import (
    CONF_DEVICE_ID, CONF_EMAIL, CONF_PASSWORD, CONF_REGION, CONF_SYSTEM_ID, CONF_TOKEN,
)
from .coordinator import ProtegusCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

type ProtegusConfigEntry = ConfigEntry[ProtegusCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ProtegusConfigEntry) -> bool:
    async def _save_token(token: str) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKEN: token})

    api = ProtegusApi(
        async_get_clientsession(hass),
        region=entry.data[CONF_REGION],
        device_id=entry.data[CONF_DEVICE_ID],
        token=entry.data.get(CONF_TOKEN),
        email=entry.data.get(CONF_EMAIL),
        password=entry.data.get(CONF_PASSWORD),
        token_updated=_save_token,
    )
    if not entry.data.get(CONF_TOKEN) and not (
        entry.data.get(CONF_EMAIL) and entry.data.get(CONF_PASSWORD)
    ):
        raise ConfigEntryAuthFailed("Signed out - please sign in again")

    try:
        await api.load_profile()
    except ProtegusAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except ProtegusConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err
    except ProtegusError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = ProtegusCoordinator(hass, entry, api, entry.data[CONF_SYSTEM_ID])
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start_socket()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ProtegusConfigEntry) -> bool:
    await entry.runtime_data.async_stop_socket()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
