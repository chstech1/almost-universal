"""Set up a logical remote and its optional Bluetooth address."""

import re

from homeassistant.config_entries import ConfigFlow, OptionsFlowWithReload
from homeassistant.helpers import selector
import voluptuous as vol

from .menu import DOMAIN, IDENTIFIER
from .protocol import SERVICE

BLE_ADDRESS = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}|[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}")


class RemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure the remote from Devices & services."""

    VERSION = 1
    address = ""

    @staticmethod
    def async_get_options_flow(config_entry):
        return RemoteOptions()

    async def async_step_bluetooth(self, discovery_info):
        self.address = discovery_info.address
        await self.async_set_unique_id(self.address)
        self._abort_if_unique_id_configured()
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Add the integration and use its configured remote ID."""
        self._async_abort_entries_match()
        errors = {}
        if user_input is not None:
            remote_id = user_input["remote_id"].strip()
            if IDENTIFIER.fullmatch(remote_id):
                data = {"remote_id": remote_id}
                if target := user_input.get("switch_entity"):
                    data["switch_entity"] = target
                if self.address:
                    data["ble_address"] = self.address
                return self.async_create_entry(
                    title="The Ununiversal Remote", data=data,
                )
            errors["remote_id"] = "invalid_remote_id"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("remote_id", default="living_room"): str,
                vol.Optional("switch_entity"): selector.EntitySelector({"domain": "switch"}),
            }),
            errors=errors,
        )


class RemoteOptions(OptionsFlowWithReload):
    """Enable Bluetooth on an existing remote while keeping its stored menus."""

    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            address = user_input.get("ble_address", "").strip().upper()
            if not address or BLE_ADDRESS.fullmatch(address):
                return self.async_create_entry(data={"ble_address": address})
            errors["ble_address"] = "invalid_address"
        selected = self.config_entry.options.get(
            "ble_address", self.config_entry.data.get("ble_address", "")
        )
        addresses = {"": "Bluetooth off"}
        if "bluetooth" in self.hass.config.components:
            from homeassistant.components import bluetooth

            for device in bluetooth.async_discovered_service_info(self.hass, connectable=True):
                if SERVICE in device.service_uuids:
                    addresses[device.address] = f"{device.name or 'Handheld'} · {device.address}"
        if selected:
            addresses.setdefault(selected, selected)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("ble_address", default=selected): selector.SelectSelector({
                    "options": [{"label": label, "value": address} for address, label in addresses.items()],
                    "custom_value": True,
                    "mode": "dropdown",
                }),
            }),
            errors=errors,
        )
