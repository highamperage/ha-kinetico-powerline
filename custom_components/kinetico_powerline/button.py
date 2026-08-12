"""Button platform for Kinetico Powerline."""
from __future__ import annotations

import asyncio
from typing import Any

from bleak import BleakClient

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KineticoDataUpdateCoordinator
from .protocol import cmd_regen_now, cmd_regen_next, cmd_set_time

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    coordinator: KineticoDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        KineticoRegenNowButton(coordinator, entry),
        KineticoSyncTimeButton(coordinator, entry),
    ])


class KineticoButtonBase(CoordinatorEntity[KineticoDataUpdateCoordinator], ButtonEntity):
    """Base class for Kinetico buttons."""

    def __init__(
        self, coordinator: KineticoDataUpdateCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the button."""
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
        # Using the coordinator's stored UART info, we can briefly connect and write
        uart = self.coordinator._uart
        if not uart:
            return

        try:
            async with BleakClient(self.coordinator.ble_device, timeout=10.0) as client:
                await client.write_gatt_char(uart["tx_char"], cmd_bytes, response=False)
                await asyncio.sleep(0.5)
        except Exception as e:
            # Re-raise or handle as appropriate for HA
            raise RuntimeError(f"Failed to send command: {e}") from e


class KineticoRegenNowButton(KineticoButtonBase):
    """Button to trigger immediate regeneration."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Regenerate Now"
        self._attr_unique_id = f"{coordinator.mac}_regen_now"
        self._attr_icon = "mdi:water-sync"

    async def async_press(self) -> None:
        """Press the button."""
        await self._async_send_command(cmd_regen_now())
        # Force a poll to update state
        await self.coordinator.async_request_refresh()


class KineticoRegenNextButton(KineticoButtonBase):
    """Button to schedule regeneration at the next scheduled time."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Regenerate Next Scheduled"
        self._attr_unique_id = f"{coordinator.mac}_regen_next"
        self._attr_icon = "mdi:clock-fast"

    async def async_press(self) -> None:
        """Press the button."""
        await self._async_send_command(cmd_regen_next())


class KineticoSyncTimeButton(KineticoButtonBase):
    """Button to sync device time with Home Assistant time."""
    
    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_name = "Sync Device Time"
        self._attr_unique_id = f"{coordinator.mac}_sync_time"
        self._attr_icon = "mdi:clock-sync"

    async def async_press(self) -> None:
        """Press the button."""
        import datetime
        now = datetime.datetime.now()
        hour = now.hour % 12 or 12
        is_pm = now.hour >= 12
        
        cmd = cmd_set_time(hour, now.minute, now.second, is_pm)
        await self._async_send_command(cmd)
