"""Binary sensor platform for Kinetico Powerline."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KineticoDataUpdateCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    coordinator: KineticoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        KineticoRegeneratingSensor(coordinator, entry),
        KineticoErrorSensor(coordinator, entry),
    ])


class KineticoBinarySensorBase(CoordinatorEntity[KineticoDataUpdateCoordinator], BinarySensorEntity):
    """Base class for Kinetico binary sensors."""

    def __init__(
        self, coordinator: KineticoDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        
        mac = coordinator.mac
        self._attr_device_info = {
            "identifiers": {(DOMAIN, mac)},
            "name": entry.title,
            "manufacturer": "Chandler Systems Inc.",
            "model": "Kinetico Powerline",
        }
        
        if coordinator.handshake:
            self._attr_device_info["model"] = coordinator.handshake.device_type.friendly_name()
            self._attr_device_info["sw_version"] = coordinator.handshake.firmware_string


class KineticoRegeneratingSensor(KineticoBinarySensorBase):
    """Regenerating status binary sensor."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Regenerating"
        self._attr_unique_id = f"{coordinator.mac}_regenerating"
        self._attr_device_class = BinarySensorDeviceClass.RUNNING
        self._attr_icon = "mdi:water-sync"

    @property
    def is_on(self) -> bool | None:
        """Return true if the device is regenerating."""
        if not self.coordinator.data or not self.coordinator.data.get("dashboard"):
            return None
        return self.coordinator.data["dashboard"].is_regenerating


class KineticoErrorSensor(KineticoBinarySensorBase):
    """Error status binary sensor."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Error Present"
        self._attr_unique_id = f"{coordinator.mac}_error"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        """Return true if there is an error."""
        if not self.coordinator.data or not self.coordinator.data.get("dashboard"):
            return None
        return self.coordinator.data["dashboard"].has_error
