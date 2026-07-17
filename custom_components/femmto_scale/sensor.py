"""Sensor entities for the Femmto Scale integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from . import FemmtoScaleCoordinator
from .const import CONF_ADDRESS, CONF_NAME, DEFAULT_NAME, DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    """Set up sensor entities."""
    coordinator: FemmtoScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        FemmtoStableWeightSensor(coordinator, entry),
        FemmtoLiveWeightSensor(coordinator, entry),
        FemmtoConnectionSensor(coordinator, entry),
    ])


class FemmtoBaseEntity(SensorEntity):
    """Base Femmto entity."""

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


class FemmtoStableWeightSensor(FemmtoBaseEntity):
    """Stable weight sensor."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: FemmtoScaleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Weight"
        self._attr_unique_id = f"{self.address}_stable_weight"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.reading.stable_weight

    @property
    def extra_state_attributes(self) -> dict:
        r = self.coordinator.reading
        return {
            "last_stable_update": r.last_stable_update.isoformat() if r.last_stable_update else None,
            "raw_packet": r.raw_packet,
            "rssi": r.rssi,
            "packets_received": r.packets_received,
            "measurement_stable": r.measurement_stable,
            "person_on_scale": r.person_on_scale,
            "repeat_count": r.repeat_count,
        }


class FemmtoLiveWeightSensor(FemmtoBaseEntity):
    """Live diagnostic weight sensor."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FemmtoScaleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Live Weight"
        self._attr_unique_id = f"{self.address}_live_weight"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.reading.live_weight

    @property
    def extra_state_attributes(self) -> dict:
        r = self.coordinator.reading
        return {
            "last_update": r.last_update.isoformat() if r.last_update else None,
            "raw_packet": r.raw_packet,
            "rssi": r.rssi,
            "packets_received": r.packets_received,
            "measurement_stable": r.measurement_stable,
            "person_on_scale": r.person_on_scale,
            "repeat_count": r.repeat_count,
        }


class FemmtoConnectionSensor(FemmtoBaseEntity):
    """Connection status diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: FemmtoScaleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = "Connection"
        self._attr_unique_id = f"{self.address}_connection"

    @property
    def native_value(self) -> str:
        return "connected" if self.coordinator.reading.connected else "idle"

    @property
    def extra_state_attributes(self) -> dict:
        r = self.coordinator.reading
        return {
            "rssi": r.rssi,
            "last_connection_attempt": r.last_connection_attempt.isoformat() if r.last_connection_attempt else None,
            "last_connection_error": r.last_connection_error,
            "last_connection_reason": r.last_connection_reason,
            "packets_received": r.packets_received,
        }
