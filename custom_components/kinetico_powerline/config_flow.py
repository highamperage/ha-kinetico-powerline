"""Config flow for Kinetico Powerline integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .protocol import DEVICE_NAME_PREFIXES, parse_advertisement

_LOGGER = logging.getLogger(__name__)

class KineticoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Kinetico Powerline."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        # Check if the name matches our prefix
        if not discovery_info.name or not any(
            discovery_info.name.startswith(prefix) for prefix in DEVICE_NAME_PREFIXES
        ):
            return self.async_abort(reason="not_supported")

        self._discovery_info = discovery_info
        
        # Determine device type from name if possible
        name = discovery_info.name
        self.context["title_placeholders"] = {"name": name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name,
                data={
                    CONF_MAC: self._discovery_info.address,
                    CONF_NAME: self._discovery_info.name,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovery_info.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            address = user_input[CONF_MAC]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            
            name = self._discovered_devices.get(address, f"Kinetico Softener ({address})")

            return self.async_create_entry(
                title=name,
                data={
                    CONF_MAC: address,
                    CONF_NAME: name,
                },
            )

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass, False):
            address = discovery_info.address
            if address in current_addresses:
                continue
                
            name = discovery_info.name
            if name and any(name.startswith(p) for p in DEVICE_NAME_PREFIXES):
                self._discovered_devices[address] = name

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MAC): vol.In(self._discovered_devices),
                }
            ),
        )
