"""Button entities for Femmto Scale."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from . import FemmtoScaleCoordinator
from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN


async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities) -> None:
    """Set up button entity."""
    coordinator: FemmtoScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FemmtoStartMeasurementButton(coordinator, entry)])


class FemmtoStartMeasurementButton(ButtonEntity):
    """Manual start measurement button."""

    _attr_has_entity_name = True
    _attr_name = "Start Measurement"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: FemmtoScaleCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self.address = entry.data[CONF_ADDRESS]
        self.device_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
        self._attr_unique_id = f"{self.address}_start_measurement"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            name=self.device_name,
            manufacturer="Femmto",
            model="BWS12",
            connections={("bluetooth", self.address)},
        )

    async def async_press(self) -> None:
        """Request an immediate forced BLE connection/listen cycle."""
        self.coordinator.async_request_measurement()
