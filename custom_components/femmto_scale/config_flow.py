"""Config flow for the Femmto Scale integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ADDRESS,
    CONF_CONNECT_COOLDOWN_SECONDS,
    CONF_LISTEN_DURATION_SECONDS,
    CONF_MIN_WEIGHT_KG,
    CONF_PERIODIC_RETRY_SECONDS,
    CONF_REPEAT_STABLE_SAMPLES,
    CONF_RESET_WEIGHT_KG,
    CONF_STABILITY_DELTA_KG,
    CONF_STABILITY_SAMPLES,
    CONF_STABILITY_WINDOW_SECONDS,
    CONF_STABLE_HOLD_SECONDS,
    DEFAULT_CONNECT_COOLDOWN_SECONDS,
    DEFAULT_LISTEN_DURATION_SECONDS,
    DEFAULT_MIN_WEIGHT_KG,
    DEFAULT_NAME,
    DEFAULT_PERIODIC_RETRY_SECONDS,
    DEFAULT_REPEAT_STABLE_SAMPLES,
    DEFAULT_RESET_WEIGHT_KG,
    DEFAULT_STABILITY_DELTA_KG,
    DEFAULT_STABILITY_SAMPLES,
    DEFAULT_STABILITY_WINDOW_SECONDS,
    DEFAULT_STABLE_HOLD_SECONDS,
    DOMAIN,
)


def _normalize_address(address: str) -> str:
    return address.strip().upper()


def _entry_data(address: str, name: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
    values = values or {}
    return {
        CONF_ADDRESS: address,
        CONF_NAME: name,
        CONF_MIN_WEIGHT_KG: values.get(CONF_MIN_WEIGHT_KG, DEFAULT_MIN_WEIGHT_KG),
        CONF_RESET_WEIGHT_KG: values.get(CONF_RESET_WEIGHT_KG, DEFAULT_RESET_WEIGHT_KG),
        CONF_STABILITY_WINDOW_SECONDS: values.get(CONF_STABILITY_WINDOW_SECONDS, DEFAULT_STABILITY_WINDOW_SECONDS),
        CONF_STABILITY_DELTA_KG: values.get(CONF_STABILITY_DELTA_KG, DEFAULT_STABILITY_DELTA_KG),
        CONF_STABILITY_SAMPLES: values.get(CONF_STABILITY_SAMPLES, DEFAULT_STABILITY_SAMPLES),
        CONF_LISTEN_DURATION_SECONDS: values.get(CONF_LISTEN_DURATION_SECONDS, DEFAULT_LISTEN_DURATION_SECONDS),
        CONF_PERIODIC_RETRY_SECONDS: values.get(CONF_PERIODIC_RETRY_SECONDS, DEFAULT_PERIODIC_RETRY_SECONDS),
        CONF_CONNECT_COOLDOWN_SECONDS: values.get(CONF_CONNECT_COOLDOWN_SECONDS, DEFAULT_CONNECT_COOLDOWN_SECONDS),
        CONF_REPEAT_STABLE_SAMPLES: values.get(CONF_REPEAT_STABLE_SAMPLES, DEFAULT_REPEAT_STABLE_SAMPLES),
        CONF_STABLE_HOLD_SECONDS: values.get(CONF_STABLE_HOLD_SECONDS, DEFAULT_STABLE_HOLD_SECONDS),
    }


class FemmtoScaleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 1

    async def async_step_bluetooth(self, discovery_info: bluetooth.BluetoothServiceInfoBleak) -> FlowResult:
        address = _normalize_address(discovery_info.address)
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._discovered_address = address
        self._discovered_name = discovery_info.name or DEFAULT_NAME
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_name,
                data=_entry_data(self._discovered_address, self._discovered_name),
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovered_name, "address": self._discovered_address},
            data_schema=vol.Schema({}),
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            address = _normalize_address(user_input[CONF_ADDRESS])
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            name = user_input.get(CONF_NAME, DEFAULT_NAME)
            return self.async_create_entry(title=name, data=_entry_data(address, name, user_input))

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default="F8:F2:F0:5A:02:BF"): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Optional(CONF_MIN_WEIGHT_KG, default=DEFAULT_MIN_WEIGHT_KG): vol.Coerce(float),
                vol.Optional(CONF_RESET_WEIGHT_KG, default=DEFAULT_RESET_WEIGHT_KG): vol.Coerce(float),
                vol.Optional(CONF_STABILITY_WINDOW_SECONDS, default=DEFAULT_STABILITY_WINDOW_SECONDS): vol.Coerce(float),
                vol.Optional(CONF_STABILITY_DELTA_KG, default=DEFAULT_STABILITY_DELTA_KG): vol.Coerce(float),
                vol.Optional(CONF_STABILITY_SAMPLES, default=DEFAULT_STABILITY_SAMPLES): vol.Coerce(int),
                vol.Optional(CONF_REPEAT_STABLE_SAMPLES, default=DEFAULT_REPEAT_STABLE_SAMPLES): vol.Coerce(int),
                vol.Optional(CONF_STABLE_HOLD_SECONDS, default=DEFAULT_STABLE_HOLD_SECONDS): vol.Coerce(float),
                vol.Optional(CONF_LISTEN_DURATION_SECONDS, default=DEFAULT_LISTEN_DURATION_SECONDS): vol.Coerce(float),
                vol.Optional(CONF_PERIODIC_RETRY_SECONDS, default=DEFAULT_PERIODIC_RETRY_SECONDS): vol.Coerce(float),
                vol.Optional(CONF_CONNECT_COOLDOWN_SECONDS, default=DEFAULT_CONNECT_COOLDOWN_SECONDS): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors={})
