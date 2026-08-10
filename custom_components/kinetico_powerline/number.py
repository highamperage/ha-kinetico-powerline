"""Number platform for Kinetico Powerline."""
from __future__ import annotations

import asyncio
from typing import Any

from bleak import BleakClient

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KineticoDataUpdateCoordinator
from .protocol import cmd_set_salt_level, cmd_set_capacity

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the number platform."""
    coordinator: KineticoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        KineticoSaltLevelNumber(coordinator, entry),
        # Capacity can also be added here
    ])


class KineticoNumberBase(CoordinatorEntity[KineticoDataUpdateCoordinator], NumberEntity):
    """Base class for Kinetico numbers."""

    def __init__(
        self, coordinator: KineticoDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the number."""
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

    async def _async_send_command(self, cmd_bytes: bytes) -> None:
        """Send a command to the device."""
        uart = self.coordinator._uart
        if not uart:
            return

        try:
            async with BleakClient(self.coordinator.ble_device, timeout=10.0) as client:
                await client.write_gatt_char(uart["tx_char"], cmd_bytes, response=False)
                await asyncio.sleep(0.5)
        except Exception as e:
            raise RuntimeError(f"Failed to send command: {e}") from e


class KineticoSaltLevelNumber(KineticoNumberBase):
    """Number entity to set salt level (0-99)."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Salt Level Setting"
        self._attr_unique_id = f"{coordinator.mac}_salt_level_setting"
        self._attr_icon = "mdi:shaker-outline"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 99
        self._attr_native_step = 1

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        if not self.coordinator.data or not self.coordinator.data.get("dashboard"):
            return None
        return self.coordinator.data["dashboard"].salt_sensor

    async def async_set_native_value(self, value: float) -> None:
        """Set the new value."""
        await self._async_send_command(cmd_set_salt_level(int(value)))
        await self.coordinator.async_request_refresh()
