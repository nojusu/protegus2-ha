"""Async client for the (undocumented) Protegus v3 web API.

Reverse engineered from web.protegus.app. Intentionally free of Home Assistant
imports so it can be tested standalone (see scripts/probe.py).
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

REGIONS: dict[str, str] = {
    "eu": "https://web.protegus.app",
    "na": "https://ohi.protegus.app",
    "asia": "https://sin.protegus.app",
}


class ProtegusError(Exception):
    """Generic API error."""


class ProtegusAuthError(ProtegusError):
    """Authentication failed / token rejected."""


class ProtegusConnectionError(ProtegusError):
    """Network problem."""


class ProtegusApi:
    """Thin wrapper around the Protegus REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        region: str,
        device_id: str,
        token: str | None = None,
        email: str | None = None,
        password: str | None = None,
        language: str = "en",
        token_updated: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self.region = region
        self.base_url = REGIONS[region]
        self.device_id = device_id
        self.token = token
        self._email = email
        self._password = password
        self._language = language
        self._token_updated = token_updated
        self.socket_token: str | None = None
        self.socket_port: int | None = None

    # ------------------------------------------------------------------ core
    def _headers(self, auth: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-Home-Region": self.region,
            "X-Device-Id": self.device_id,
        }
        if auth:
            headers["Authorization"] = f"Bearer {self.token or ''}"
            headers["My-Language"] = self._language
        else:
            headers["Accept-Language"] = self._language
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        auth: bool = True,
        raise_on_fail: bool = True,
        _retry: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/v3/api/{path}"
        try:
            async with self._session.request(
                method,
                url,
                json=json,
                params=params,
                headers=self._headers(auth),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (401, 403) and auth:
                    if _retry and self._email and self._password:
                        _LOGGER.debug("Token rejected, logging in again")
                        await self.login(self._email, self._password)
                        return await self._request(
                            method, path, json=json, params=params, auth=auth,
                            raise_on_fail=raise_on_fail, _retry=False,
                        )
                    raise ProtegusAuthError(f"HTTP {resp.status} from {path}")
                try:
                    data = await resp.json(content_type=None)
                except Exception as err:  # noqa: BLE001
                    raise ProtegusError(f"Invalid JSON from {path} (HTTP {resp.status})") from err
        except aiohttp.ClientError as err:
            raise ProtegusConnectionError(str(err)) from err
        except TimeoutError as err:
            raise ProtegusConnectionError("timeout") from err

        if raise_on_fail and isinstance(data, dict) and data.get("success") is False:
            raise ProtegusError(data.get("error") or data.get("message") or f"{path} failed")
        return data

    # ------------------------------------------------------------------ auth
    async def login(self, email: str, password: str) -> dict[str, Any]:
        """Password login. NOTE: untested against a real password account
        (the capture was a Google sign-in) - body shape taken from the web app JS."""
        data = await self._request(
            "POST",
            "login",
            json={"email": email, "password": password, "deviceToken": None},
            auth=False,
            raise_on_fail=False,
        )
        if not data.get("success") or not data.get("token"):
            raise ProtegusAuthError(data.get("error") or data.get("message") or "login failed")
        self._email, self._password = email, password
        await self._store_token(data)
        return data

    async def _store_token(self, data: dict[str, Any]) -> None:
        self.token = data["token"]
        if data.get("socket_token"):
            self.socket_token = data["socket_token"]
        if data.get("socket_port"):
            self.socket_port = int(data["socket_port"])
        if self._token_updated:
            await self._token_updated(self.token)

    async def logout(self) -> None:
        """POST /logout - ends the session on the server (invalidates this token).

        No body is sent (the web app sends none). _retry=False: never log in
        again just to log out.
        """
        await self._request("POST", "logout", raise_on_fail=False, _retry=False)

    def clear_credentials(self) -> None:
        """Forget token, socket credentials and stored login (local sign-out)."""
        self.token = None
        self.socket_token = None
        self.socket_port = None
        self._email = None
        self._password = None

    async def load_profile(self) -> dict[str, Any]:
        """GET /me - validates the token and returns socket credentials."""
        data = await self._request("GET", "me", params={"systemId": "", "areaId": 0})
        if data.get("socket_token"):
            self.socket_token = data["socket_token"]
        if data.get("socket_port"):
            self.socket_port = int(data["socket_port"])
        return data

    # ------------------------------------------------------------------ data
    async def get_systems(self) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", "systems", params={"returnSystemCount": "true", "offsetName": ""}
        )
        return data.get("systems", [])

    async def set_area_status(
        self, area_id: int, new_state: int, old_state: int, pin: str = ""
    ) -> dict[str, Any]:
        """Arm / disarm. Returns the raw response (badPin, failedZones, ...).

        The PIN is sent with every command and the server is told NOT to
        remember it (remember_pin=False)."""
        return await self._request(
            "POST",
            "set-area-status",
            json={
                "area_id": area_id,
                "new_state": new_state,
                "old_state": old_state,
                "pin": pin,
                "remember_pin": False,
            },
            raise_on_fail=False,
        )

    async def toggle_pgm(self, pgm_id: int) -> dict[str, Any]:
        """Toggle a PGM output. The web app sends only {pgmId}."""
        return await self._request("POST", "toggle-pgm", json={"pgmId": pgm_id})
