"""PGM outputs that are not 'level' (pulse etc.) as buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
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
        [
            ProtegusSignOutButton(coordinator),
            *(
                ProtegusPgmButton(coordinator, pid)
                for pid, pgm in coordinator.data["pgms"].items()
                if pgm.get("type") != "level"
            ),
        ]
    )


class ProtegusPgmButton(ProtegusEntity, ButtonEntity):
    def __init__(self, coordinator: ProtegusCoordinator, pgm_id: int) -> None:
        super().__init__(coordinator)
        self._pgm_id = pgm_id
        self._attr_unique_id = f"{coordinator.system_id}_pgm_{pgm_id}_pulse"

    @property
    def name(self) -> str:  # type: ignore[override]
        pgm = self.coordinator.data["pgms"][self._pgm_id]
        return pgm.get("name") or f"PGM {pgm.get('queue_no')}"

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.toggle_pgm(self._pgm_id)
        except ProtegusError as err:
            raise HomeAssistantError(f"Protegus: {err}") from err


class ProtegusSignOutButton(ProtegusEntity, ButtonEntity):
    """Wipes the stored token/login from Home Assistant and asks to sign in again."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "sign_out"
    _attr_icon = "mdi:logout"

    def __init__(self, coordinator: ProtegusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.system_id}_sign_out"

    @property
    def available(self) -> bool:  # signing out must work even when the panel is offline
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_sign_out()
