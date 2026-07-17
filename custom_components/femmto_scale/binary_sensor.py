"""Binary sensor entities for Femmto Scale."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from . import FemmtoScaleCoordinator
from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    """Set up binary sensor entities."""
    coordinator: FemmtoScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        FemmtoMeasurementStableBinarySensor(coordinator, entry),
        FemmtoPersonOnScaleBinarySensor(coordinator, entry),
    ])


class FemmtoBaseBinarySensor(BinarySensorEntity):
    """Base binary sensor for Femmto."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FemmtoScaleCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self.entry = entry
        self.address = entry.data[CONF_ADDRESS]
        self.device_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            name=self.device_name,
            manufacturer="Femmto",
            model="BWS12",
            connections={("bluetooth", self.address)},
        )
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self.coordinator.async_add_listener(self._handle_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class FemmtoMeasurementStableBinarySensor(FemmtoBaseBinarySensor):
    """Binary sensor that turns on when the integration has accepted a stable measurement."""

    _attr_name = "Measurement Stable"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: FemmtoScaleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self.address}_measurement_stable"

    @property
    def is_on(self) -> bool:
        return self.coordinator.reading.measurement_stable

    @property
    def extra_state_attributes(self) -> dict:
        r = self.coordinator.reading
        return {
            "stable_weight": r.stable_weight,
            "last_stable_update": r.last_stable_update.isoformat() if r.last_stable_update else None,
            "live_weight": r.live_weight,
            "raw_packet": r.raw_packet,
            "repeat_count": r.repeat_count,
        }


class FemmtoPersonOnScaleBinarySensor(FemmtoBaseBinarySensor):
    """Binary sensor that turns on when the live weight is above the configured minimum."""

    _attr_name = "Person On Scale"
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FemmtoScaleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{self.address}_person_on_scale"

    @property
    def is_on(self) -> bool:
        return self.coordinator.reading.person_on_scale

    @property
    def extra_state_attributes(self) -> dict:
        r = self.coordinator.reading
        return {
            "live_weight": r.live_weight,
            "raw_packet": r.raw_packet,
            "last_update": r.last_update.isoformat() if r.last_update else None,
        }
