"""Alarm control panel: one entity per Protegus area (partition)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ProtegusConfigEntry
from .const import (
    STATUS_ARMED, STATUS_ARMING, STATUS_DISARMED, STATUS_DISARMED_NOT_READY,
    STATUS_DISARMED_READY, STATUS_DISARMING, STATUS_SLEEP, STATUS_STAY,
)
from .coordinator import ProtegusCoordinator
from .entity import ProtegusEntity

_DISARMED = {STATUS_DISARMED, STATUS_DISARMED_READY, STATUS_DISARMED_NOT_READY}


async def async_setup_entry(
    hass: HomeAssistant, entry: ProtegusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ProtegusAlarm(coordinator, area_id) for area_id in coordinator.data["areas"])


class ProtegusAlarm(ProtegusEntity, AlarmControlPanelEntity):
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = True  # PIN is required for every arm/disarm and never stored

    def __init__(self, coordinator: ProtegusCoordinator, area_id: int) -> None:
        super().__init__(coordinator)
        self._area_id = area_id
        self._attr_unique_id = f"{coordinator.system_id}_area_{area_id}"
        features = AlarmControlPanelEntityFeature.ARM_AWAY
        if not coordinator.data["info"]["no_sleep_stay"]:
            features |= AlarmControlPanelEntityFeature.ARM_HOME | AlarmControlPanelEntityFeature.ARM_NIGHT
        self._attr_supported_features = features

    @property
    def _area(self) -> dict[str, Any]:
        return self.coordinator.data["areas"][self._area_id]

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._area.get("name") or f"Area {self._area.get('queue_no')}"

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        status = self._area.get("status")
        armed = status in (STATUS_ARMED, STATUS_STAY, STATUS_SLEEP)
        # ASSUMPTION: alarm_in_memory while armed == alarm currently triggered
        if armed and self._area.get("alarm_in_memory"):
            return AlarmControlPanelState.TRIGGERED
        if status in _DISARMED:
            return AlarmControlPanelState.DISARMED
        return {
            STATUS_ARMED: AlarmControlPanelState.ARMED_AWAY,
            STATUS_STAY: AlarmControlPanelState.ARMED_HOME,
            STATUS_SLEEP: AlarmControlPanelState.ARMED_NIGHT,
            STATUS_ARMING: AlarmControlPanelState.ARMING,
            STATUS_DISARMING: AlarmControlPanelState.DISARMING,
        }.get(status)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "last_changed_by": self._area.get("last_person_name"),
            "alarm_in_memory": self._area.get("alarm_in_memory"),
            "status_code": self._area.get("status"),
        }

    async def _set(self, new_state: int, code: str | None) -> None:
        # HA's UI asks for the code, but service calls / automations / voice
        # assistants can omit it, so enforce it here for arm AND disarm.
        pin = (code or "").strip()
        if not pin:
            raise ServiceValidationError("Protegus: PIN code is required")
        old_state = int(self._area.get("status") or STATUS_DISARMED)
        result = await self.coordinator.api.set_area_status(
            self._area_id, new_state, old_state, pin
        )
        if result.get("badPin"):
            raise HomeAssistantError("Protegus: wrong PIN")
        if not result.get("success"):
            raise HomeAssistantError(f"Protegus: {result.get('error') or 'command failed'}")
        if result.get("hasFailedzones") or result.get("failedZones"):
            raise HomeAssistantError(f"Protegus: zones not ready: {result.get('failedZones')}")
        # confirmation arrives via socket; poll as a fallback
        await self.coordinator.async_request_refresh()

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._set(STATUS_DISARMED, code)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._set(STATUS_ARMED, code)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self._set(STATUS_STAY, code)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._set(STATUS_SLEEP, code)
