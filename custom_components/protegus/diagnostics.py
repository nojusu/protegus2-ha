"""Diagnostics download (Settings → Devices & services → Protegus → ⋮ → Download diagnostics).

Secrets and personal data are redacted, so the file is safe to attach to an issue.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import ProtegusConfigEntry
from .const import CONF_DEVICE_ID, CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN

TO_REDACT_ENTRY = {CONF_TOKEN, CONF_EMAIL, CONF_PASSWORD, CONF_DEVICE_ID}
TO_REDACT_DATA = {"last_person_name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ProtegusConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    api = coordinator.api
    data = coordinator.data or {}
    interval = coordinator.update_interval
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
            "options": dict(entry.options),
        },
        "api": {
            "region": api.region,
            "has_token": bool(api.token),
            "has_password_login": bool(entry.data.get(CONF_EMAIL) and entry.data.get(CONF_PASSWORD)),
        },
        "socket": {
            "connected": coordinator.socket_connected,
            "has_credentials": bool(api.socket_token and api.socket_port),
            "port": api.socket_port,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": interval.total_seconds() if interval else None,
        },
        # ids as strings: JSON object keys must be strings
        "data": async_redact_data(
            {
                "info": data.get("info"),
                "areas": {str(k): v for k, v in (data.get("areas") or {}).items()},
                "pgms": {str(k): v for k, v in (data.get("pgms") or {}).items()},
            },
            TO_REDACT_DATA,
        ),
    }
