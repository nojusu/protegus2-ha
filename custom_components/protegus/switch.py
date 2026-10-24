"""PGM outputs of type 'level' as switches."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ProtegusConfigEntry
from .api import ProtegusError
from .coordinator import ProtegusCoordinator
from .entity import ProtegusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ProtegusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ProtegusPgmSwitch(coordinator, pid)
        for pid, pgm in coordinator.data["pgms"].items()
        if pgm.get("type") == "level"
    )


class ProtegusPgmSwitch(ProtegusEntity, SwitchEntity):
    def __init__(self, coordinator: ProtegusCoordinator, pgm_id: int) -> None:
        super().__init__(coordinator)
        self._pgm_id = pgm_id
        self._attr_unique_id = f"{coordinator.system_id}_pgm_{pgm_id}"

    @property
    def _pgm(self) -> dict[str, Any]:
        return self.coordinator.data["pgms"][self._pgm_id]

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._pgm.get("name") or f"PGM {self._pgm.get('queue_no')}"

    @property
    def is_on(self) -> bool:
        return bool(self._pgm.get("on"))

    async def _toggle_to(self, desired: bool) -> None:
        # The API only offers "toggle", so only send it if the state differs.
        if self.is_on == desired:
            return
        try:
            result = await self.coordinator.api.toggle_pgm(self._pgm_id)
        except ProtegusError as err:
            raise HomeAssistantError(f"Protegus: {err}") from err
        new = (result.get("pgm") or {}).get("on")
        if new is not None:
            self._pgm["on"] = new
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._toggle_to(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._toggle_to(False)
