"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ProtegusCoordinator


class ProtegusEntity(CoordinatorEntity[ProtegusCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ProtegusCoordinator) -> None:
        super().__init__(coordinator)
        info = coordinator.data["info"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(coordinator.system_id))},
            name=info["name"],
            manufacturer="Protegus",
            model=info.get("hw_type"),
            sw_version=info.get("fw_version"),
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data["info"]["online"]
