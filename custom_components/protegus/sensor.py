"""GSM/communication signal level."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ProtegusConfigEntry
from .coordinator import ProtegusCoordinator
from .entity import ProtegusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ProtegusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ProtegusSignal(entry.runtime_data)])


class ProtegusSignal(ProtegusEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "signal_level"
    _attr_icon = "mdi:signal"

    def __init__(self, coordinator: ProtegusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.system_id}_signal"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data["info"].get("signal")
