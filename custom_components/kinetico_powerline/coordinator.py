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
from bleak_retry_connector import establish_connection

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, SUSPICIOUS_ZERO_THRESHOLD
from .protocol import (
    UART_SERVICES,
    DashboardData,
    AuthStatus,
    cmd_auth,
    cmd_auth_pa,
    cmd_handshake,
    cmd_dashboard,
    is_valid_handshake,
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
        _LOGGER.warning("Received BLE notification from %s: %s", sender, data.hex())
        self._last_data = data
        self._collected_responses.append(data)
        self._response_event.set()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from device."""
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                return await self._fetch_data()
            except BleakError as err:
                if attempt < max_attempts:
                    _LOGGER.info("Retry %d/%d after transient BLE error: %s", attempt, max_attempts, err)
                    await asyncio.sleep(1.5)
                else:
                    raise UpdateFailed(f"BLE Error communicating with device after {max_attempts} attempts: {err}") from err
            except Exception as err:
                raise UpdateFailed(f"Unexpected error communicating with device: {err}") from err

    async def _fetch_data(self) -> dict[str, Any]:
        """Connect and fetch the dashboard data."""
        # Using bleak-retry-connector for reliable connection establishment
        client = await establish_connection(
            client_class=BleakClient,
            device=self.ble_device,
            name=self.mac,
        )
        if not client or not client.is_connected:
            raise UpdateFailed("Failed to connect to device")

        self._client = client

        try:
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
            from .protocol import cmd_advanced_settings, cmd_dashboard, parse_dashboard_packets
            
            # Send Advanced Settings request first (v packet)
            await client.write_gatt_char(uart["tx_char"], cmd_advanced_settings(), response=False)
            
            # Wait briefly for settings response
            try:
                await asyncio.wait_for(self._response_event.wait(), timeout=1.0)
                self._response_event.clear()
            except asyncio.TimeoutError:
                _LOGGER.debug("Timeout waiting for advanced settings response")
            
            # Send Dashboard request (u packets)
            await client.write_gatt_char(uart["tx_char"], cmd_dashboard(), response=False)
            
            # Wait a few seconds to let all packets arrive
            for _ in range(5):
                try:
                    await asyncio.wait_for(self._response_event.wait(), timeout=1.0)
                    self._response_event.clear()
                except asyncio.TimeoutError:
                    break
            
            fw_ver = self.handshake.firmware_version if self.handshake else 0
            dev_type = self.handshake.device_type if self.handshake else 0
            
            dashboard = parse_dashboard_packets(
                [bytes(d) for d in self._collected_responses], 
                fw_ver, 
                dev_type
            )
            
            if dashboard is None or not dashboard.is_valid:
                _LOGGER.warning("Dashboard parse failed or invalid for data")

            # Disconnect cleanly
            try:
                await client.stop_notify(uart["rx_char"])
            except Exception:
                pass

            if not dashboard:
                raise UpdateFailed("Did not receive dashboard data from device")

            # --- Validation Gate ---
            # Check if majority of meaningful independent numeric indicators are zero.
            # This is a known issue where sync briefly returns all/mostly zeros.
            # Capacity and salt represent the same underlying resource, so they
            # combine into a single true/false signal for this test.
            independent_checks = [
                dashboard.days_until_regen == 0,
                dashboard.days_since_regen == 0,
                dashboard.hardness_gpg == 0,
                (dashboard.capacity_remaining_gallons == 0 and dashboard.salt_sensor == 0),
            ]
            zero_count = sum(1 for check in independent_checks if check)

            if zero_count >= SUSPICIOUS_ZERO_THRESHOLD:
                if self.data:
                    _LOGGER.warning(
                        "Suspicious update detected: %d/%d independent checks are zero. "
                        "Preserving last known good state.",
                        zero_count, len(independent_checks)
                    )
                    return self.data
                else:
                    _LOGGER.warning(
                        "Suspicious update detected on initial fetch: %d/%d independent checks are zero. "
                        "Accepting anyway as there is no previous state.",
                        zero_count, len(independent_checks)
                    )

            # Return the collected data dictionary
            return {
                "dashboard": dashboard,
                "handshake": self.handshake,
            }
        finally:
            await client.disconnect()
