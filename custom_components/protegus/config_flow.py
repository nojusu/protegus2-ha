"""Config flow: pick region, sign in (password or pasted token), pick system."""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .api import REGIONS, ProtegusApi, ProtegusAuthError, ProtegusError
from .const import (
    CONF_DEVICE_ID, CONF_EMAIL, CONF_PASSWORD, CONF_REGION, CONF_SYSTEM_ID, CONF_TOKEN, DOMAIN,
)


class ProtegusConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._api: ProtegusApi | None = None
        self._systems: list[dict[str, Any]] = []
        self._reauth_entry = None

    def _new_api(self, region: str, **kw: Any) -> ProtegusApi:
        self._data.setdefault(CONF_DEVICE_ID, str(uuid.uuid4()))
        return ProtegusApi(
            async_get_clientsession(self.hass), region, self._data[CONF_DEVICE_ID], **kw
        )

    # ---------------------------------------------------------------- steps
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["password", "token"])

    async def async_step_password(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_REGION] = user_input[CONF_REGION]
            api = self._new_api(user_input[CONF_REGION])
            try:
                await api.login(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
                self._data.update(
                    {CONF_EMAIL: user_input[CONF_EMAIL], CONF_PASSWORD: user_input[CONF_PASSWORD],
                     CONF_TOKEN: api.token}
                )
                return await self._after_auth(api)
            except ProtegusAuthError:
                errors["base"] = "invalid_auth"
            except ProtegusError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REGION, default="eu"): SelectSelector(
                        SelectSelectorConfig(options=list(REGIONS), translation_key="region")
                    ),
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_token(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """For Google/Apple sign-in accounts: paste the Bearer token (lasts ~1 year)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_REGION] = user_input[CONF_REGION]
            # The server binds the token to the X-Device-Id it was issued for,
            # so the user must supply the same id the browser used.
            self._data[CONF_DEVICE_ID] = user_input[CONF_DEVICE_ID].strip()
            token = user_input[CONF_TOKEN].strip().removeprefix("Bearer ").strip()
            api = self._new_api(user_input[CONF_REGION], token=token)
            try:
                await api.load_profile()
                self._data[CONF_TOKEN] = token
                return await self._after_auth(api)
            except ProtegusAuthError:
                errors["base"] = "invalid_auth"
            except ProtegusError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REGION, default="eu"): SelectSelector(
                        SelectSelectorConfig(options=list(REGIONS), translation_key="region")
                    ),
                    vol.Required(CONF_TOKEN): str,
                    vol.Required(
                        CONF_DEVICE_ID,
                        description={"suggested_value": self._data.get(CONF_DEVICE_ID)},
                    ): str,
                }
            ),
            errors=errors,
        )

    async def _after_auth(self, api: ProtegusApi) -> ConfigFlowResult:
        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry, data={**self._reauth_entry.data, **self._data}
            )
        self._api = api
        self._systems = await api.get_systems()
        if not self._systems:
            return self.async_abort(reason="no_systems")
        if len(self._systems) == 1:
            return await self._create(self._systems[0])
        return await self.async_step_system()

    async def async_step_system(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            system = next(s for s in self._systems if str(s["id"]) == user_input[CONF_SYSTEM_ID])
            return await self._create(system)
        options = [{"value": str(s["id"]), "label": s.get("name") or str(s["id"])} for s in self._systems]
        return self.async_show_form(
            step_id="system",
            data_schema=vol.Schema(
                {vol.Required(CONF_SYSTEM_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    async def _create(self, system: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(f"{self._data[CONF_REGION]}_{system['id']}")
        self._abort_if_unique_id_configured()
        self._data[CONF_SYSTEM_ID] = system["id"]
        return self.async_create_entry(title=system.get("name") or f"Protegus {system['id']}", data=self._data)

    # --------------------------------------------------------------- reauth
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        self._data = {CONF_DEVICE_ID: entry_data[CONF_DEVICE_ID], CONF_REGION: entry_data[CONF_REGION]}
        return await self.async_step_user()
