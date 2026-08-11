"""Sensor platform for Kinetico Powerline."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
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
    """Set up the sensor platform."""
    coordinator: KineticoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        KineticoDaysUntilRegenSensor(coordinator, entry),
        KineticoDaysSinceRegenSensor(coordinator, entry),
        KineticoHardnessSensor(coordinator, entry),
        KineticoCapacitySensor(coordinator, entry),
        KineticoSaltSensor(coordinator, entry),
    ])


class KineticoSensorBase(CoordinatorEntity[KineticoDataUpdateCoordinator], SensorEntity):
    """Base class for Kinetico sensors."""

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
        
        # Try to pull better device info from handshake if available
        if coordinator.handshake:
            self._attr_device_info["model"] = coordinator.handshake.device_type.friendly_name()
            self._attr_device_info["sw_version"] = coordinator.handshake.firmware_string


class KineticoDaysUntilRegenSensor(KineticoSensorBase):
    """Days until next regeneration sensor."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Days Until Regeneration"
        self._attr_unique_id = f"{coordinator.mac}_days_until_regen"
        self._attr_native_unit_of_measurement = "d"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("dashboard"):
            return None
        return self.coordinator.data["dashboard"].days_until_regen


class KineticoDaysSinceRegenSensor(KineticoSensorBase):
    """Days since last regeneration sensor."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Days Since Regeneration"
        self._attr_unique_id = f"{coordinator.mac}_days_since_regen"
        self._attr_native_unit_of_measurement = "d"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("dashboard"):
            return None
        return self.coordinator.data["dashboard"].days_since_regen


class KineticoHardnessSensor(KineticoSensorBase):
    """Water hardness sensor."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Water Hardness"
        self._attr_unique_id = f"{coordinator.mac}_hardness"
        self._attr_native_unit_of_measurement = "GPG"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("dashboard"):
            return None
        return self.coordinator.data["dashboard"].hardness_gpg


class KineticoCapacitySensor(KineticoSensorBase):
    """Capacity remaining sensor."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Capacity Remaining"
        self._attr_unique_id = f"{coordinator.mac}_capacity_remaining"
        self._attr_device_class = SensorDeviceClass.WATER
        self._attr_native_unit_of_measurement = "gal"  # Approximation, actually grains

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("dashboard"):
            return None
        return self.coordinator.data["dashboard"].capacity_remaining_gallons


class KineticoSaltSensor(KineticoSensorBase):
    """Salt level sensor."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Salt Level"
        self._attr_unique_id = f"{coordinator.mac}_salt_level"
        self._attr_icon = "mdi:shaker-outline"
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data or not self.coordinator.data.get("dashboard"):
            return None
        return self.coordinator.data["dashboard"].salt_sensor
