"""DataUpdateCoordinator for the Kinetico Powerline integration."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .protocol import (
    UART_SERVICES,
    DashboardData,
    AuthStatus,
    cmd_auth,
    cmd_auth_pa,
    cmd_handshake,
    cmd_dashboard,
    is_valid_handshake,
    parse_dashboard,
    parse_handshake,
)

_LOGGER = logging.getLogger(__name__)

class KineticoDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Kinetico BLE device."""

    def __init__(self, hass: HomeAssistant, ble_device: BLEDevice) -> None:
        """Initialize."""
        self.ble_device = ble_device
        self.mac = ble_device.address
        self.handshake: HandshakeResponse | None = None
        
        self._client: BleakClient | None = None
        self._uart: dict[str, str] | None = None
        
        # State used during update loops
        self._response_event = asyncio.Event()
        self._last_data: bytearray | None = None
        self._collected_responses: list[bytearray] = []

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    def _notification_handler(self, sender: Any, data: bytearray) -> None:
        """Handle notifications from the BLE device."""
        self._last_data = data
        self._collected_responses.append(data)
        self._response_event.set()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from device."""
        try:
            return await self._fetch_data()
        except BleakError as err:
            raise UpdateFailed(f"BLE Error communicating with device: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error communicating with device: {err}") from err

    async def _fetch_data(self) -> dict[str, Any]:
        """Connect and fetch the dashboard data."""
        # Using a new client per update is safer for BLE stability in HA
        async with BleakClient(self.ble_device, timeout=15.0) as client:
            self._client = client
            if not client.is_connected:
                raise UpdateFailed("Failed to connect to device")

            # Discover UART service
            uart = None
            for svc in UART_SERVICES:
                try:
                    if client.services.get_service(svc["service"]):
                        rx = client.services.get_characteristic(svc["rx_char"])
                        tx = client.services.get_characteristic(svc["tx_char"])
                        if rx and tx:
                            uart = svc
                            break
                except Exception:
                    pass

            if not uart:
                raise UpdateFailed("Device does not support the required UART service")

            self._uart = uart

            # Start notifications
            await client.start_notify(uart["rx_char"], self._notification_handler)
            await asyncio.sleep(0.5)
            
            # --- 1. Handshake ---
            self._collected_responses = []
            self._response_event.clear()
            await client.write_gatt_char(uart["tx_char"], cmd_handshake(), response=False)
            
            try:
                await asyncio.wait_for(self._response_event.wait(), timeout=3.0)
                data = bytes(self._last_data)
                if is_valid_handshake(data):
                    self.handshake = parse_handshake(data, len(data))
            except asyncio.TimeoutError:
                pass
                
            if not self.handshake or not self.handshake.is_valid:
                raise UpdateFailed("Failed to receive a valid handshake from device")
                
            # --- 2. Authentication (if required) ---
            if self.handshake.firmware_version >= 420 and self.handshake.auth_status == AuthStatus.NOT_AUTHENTICATED:
                self._response_event.clear()
                # Use default PIN 1234
                if self.handshake.pin_required:
                    auth_cmd = cmd_auth(counter=self.handshake.connection_counter, pin=1234, fw_420_plus=True)
                else:
                    auth_cmd = cmd_auth_pa(counter=self.handshake.connection_counter, pin=1234)
                    
                await client.write_gatt_char(uart["tx_char"], auth_cmd, response=False)
                
                try:
                    await asyncio.wait_for(self._response_event.wait(), timeout=3.0)
                    data = bytes(self._last_data)
                    if is_valid_handshake(data):
                        auth_hs = parse_handshake(data, len(data))
                        if auth_hs.auth_status != AuthStatus.AUTHENTICATED:
                            raise UpdateFailed("Authentication failed! (Invalid PIN)")
                except asyncio.TimeoutError:
                    raise UpdateFailed("Timeout waiting for authentication response")

            # --- 3. Send Dashboard request ---
            self._collected_responses = []
            self._response_event.clear()
            
            await client.write_gatt_char(uart["tx_char"], cmd_dashboard(), response=False)
            
            dashboard: DashboardData | None = None
            
            # Wait for responses
            for _ in range(5):
                try:
                    await asyncio.wait_for(self._response_event.wait(), timeout=3.0)
                    self._response_event.clear()
                    
                    data = bytes(self._last_data)
                    
                    fw_ver = self.handshake.firmware_version if self.handshake else 0
                    dev_type = self.handshake.device_type if self.handshake else 0
                    
                    parsed = parse_dashboard(data, len(data), fw_ver, dev_type)
                    if parsed and parsed.is_valid:
                        dashboard = parsed
                        break
                        
                except asyncio.TimeoutError:
                    break

            # Disconnect cleanly
            try:
                await client.stop_notify(uart["rx_char"])
            except Exception:
                pass

            if not dashboard:
                raise UpdateFailed("Did not receive dashboard data from device")

            # Return the collected data dictionary
            return {
                "dashboard": dashboard,
                "handshake": self.handshake,
            }
