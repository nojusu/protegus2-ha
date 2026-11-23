"""Connectivity of the alarm panel."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ProtegusConfigEntry
from .coordinator import ProtegusCoordinator
from .entity import ProtegusEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ProtegusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([ProtegusOnline(coordinator), ProtegusRealtime(coordinator)])


class ProtegusOnline(ProtegusEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "online"

    def __init__(self, coordinator: ProtegusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.system_id}_online"

    @property
    def available(self) -> bool:  # stay available while panel is offline
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self.coordinator.data["info"]["online"]


class ProtegusRealtime(ProtegusEntity, BinarySensorEntity):
    """On = realtime (socket.io) push updates work; off = polling only."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "realtime"

    def __init__(self, coordinator: ProtegusCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.system_id}_realtime"

    @property
    def available(self) -> bool:  # independent of the panel and of polling
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.socket_connected
