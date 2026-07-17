"""Femmto Scale integration."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, Callable

from bleak import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import (
    CONF_ADDRESS,
    CONF_CONNECT_COOLDOWN_SECONDS,
    CONF_LISTEN_DURATION_SECONDS,
    CONF_MIN_WEIGHT_KG,
    CONF_NAME,
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
    NOTIFY_UUID,
    WEIGHT_OFFSET,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor", "button"]


@dataclass
class FemmtoReading:
    """Latest decoded Femmto reading."""

    live_weight: float | None = None
    stable_weight: float | None = None
    raw_packet: str | None = None
    last_update: datetime | None = None
    last_stable_update: datetime | None = None
    last_connection_attempt: datetime | None = None
    last_connection_error: str | None = None
    last_connection_reason: str | None = None
    rssi: int | None = None
    connected: bool = False
    packets_received: int = 0
    measurement_stable: bool = False
    person_on_scale: bool = False
    repeat_count: int = 0


class FemmtoScaleCoordinator:
    """Manage BLE connection, FFB2 notifications and stability detection."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.address: str = entry.data[CONF_ADDRESS].upper()
        self.name: str = entry.data.get(CONF_NAME, DEFAULT_NAME)

        options = {**entry.data, **entry.options}
        self.min_weight_kg = float(options.get(CONF_MIN_WEIGHT_KG, DEFAULT_MIN_WEIGHT_KG))
        self.reset_weight_kg = float(options.get(CONF_RESET_WEIGHT_KG, DEFAULT_RESET_WEIGHT_KG))
        self.stability_window = float(options.get(CONF_STABILITY_WINDOW_SECONDS, DEFAULT_STABILITY_WINDOW_SECONDS))
        self.stability_delta = float(options.get(CONF_STABILITY_DELTA_KG, DEFAULT_STABILITY_DELTA_KG))
        self.stability_samples = int(options.get(CONF_STABILITY_SAMPLES, DEFAULT_STABILITY_SAMPLES))
        self.listen_duration = float(options.get(CONF_LISTEN_DURATION_SECONDS, DEFAULT_LISTEN_DURATION_SECONDS))
        self.periodic_retry = float(options.get(CONF_PERIODIC_RETRY_SECONDS, DEFAULT_PERIODIC_RETRY_SECONDS))
        self.connect_cooldown = float(options.get(CONF_CONNECT_COOLDOWN_SECONDS, DEFAULT_CONNECT_COOLDOWN_SECONDS))
        self.repeat_stable_samples = int(options.get(CONF_REPEAT_STABLE_SAMPLES, DEFAULT_REPEAT_STABLE_SAMPLES))
        self.stable_hold_seconds = float(options.get(CONF_STABLE_HOLD_SECONDS, DEFAULT_STABLE_HOLD_SECONDS))

        self.reading = FemmtoReading()
        self._listeners: list[Callable[[], None]] = []
        self._samples: deque[tuple[datetime, float]] = deque()
        self._connect_task: asyncio.Task | None = None
        self._unsub_bluetooth: CALLBACK_TYPE | None = None
        self._unsub_periodic: CALLBACK_TYPE | None = None
        self._cooldown_unsub: CALLBACK_TYPE | None = None
        self._stable_clear_unsub: CALLBACK_TYPE | None = None
        self._in_cooldown = False
        self._armed_for_next_measurement = True
        self._last_raw_weight: int | None = None
        self._last_raw_packet: str | None = None
        self._repeat_count = 0

    async def async_start(self) -> None:
        """Start bluetooth callbacks and aggressive reconnect attempts."""
        self._unsub_bluetooth = bluetooth.async_register_callback(
            self.hass,
            self._async_discovered_device,
            {"address": self.address},
            BluetoothScanningMode.ACTIVE,
        )
        self._unsub_periodic = async_track_time_interval(
            self.hass,
            self._async_periodic_connect,
            timedelta(seconds=self.periodic_retry),
        )
        # Force a first connection attempt as soon as HA starts or the integration reloads.
        self._schedule_connect("startup forced", force=True)

    async def async_stop(self) -> None:
        """Stop coordinator."""
        for unsub_attr in ("_unsub_bluetooth", "_unsub_periodic", "_cooldown_unsub", "_stable_clear_unsub"):
            unsub = getattr(self, unsub_attr)
            if unsub:
                unsub()
                setattr(self, unsub_attr, None)
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError:
                pass

    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> CALLBACK_TYPE:
        """Add update listener."""
        self._listeners.append(update_callback)

        def remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _async_discovered_device(self, service_info, change) -> None:
        """Handle Bluetooth advertisement callback."""
        self.reading.rssi = service_info.rssi
        self._notify_listeners()
        # Advertisement means the scale is awake. Force connection immediately.
        self._schedule_connect("advertisement forced", force=True)

    @callback
    def _async_periodic_connect(self, _now=None) -> None:
        """Periodic safety net: try to connect even if no fresh discovery callback arrives."""
        self._schedule_connect("periodic forced", force=True)

    @callback
    def async_request_measurement(self) -> None:
        """User-requested connection attempt from button entity."""
        self._schedule_connect("manual button forced", force=True)

    @callback
    def _clear_cooldown(self, _now=None) -> None:
        self._in_cooldown = False
        self._cooldown_unsub = None

    @callback
    def _schedule_connect(self, reason: str, force: bool = False) -> None:
        """Schedule a BLE connection attempt."""
        if not force and self._in_cooldown:
            return
        if self._connect_task and not self._connect_task.done():
            return
        _LOGGER.debug("Scheduling Femmto connection: %s", reason)
        self._connect_task = self.hass.async_create_task(self._async_connect_and_listen(reason))

    async def _async_connect_and_listen(self, reason: str) -> None:
        """Connect and listen to FFB2 notifications."""
        self._in_cooldown = True
        if self._cooldown_unsub:
            self._cooldown_unsub()
        self._cooldown_unsub = async_call_later(self.hass, self.connect_cooldown, self._clear_cooldown)

        self.reading.last_connection_attempt = datetime.now()
        self.reading.last_connection_error = None
        self.reading.last_connection_reason = reason
        self._notify_listeners()

        ble_device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if ble_device is None:
            self.reading.last_connection_error = "BLE device unavailable in HA Bluetooth cache"
            _LOGGER.debug("Femmto %s unavailable for connection (%s)", self.address, reason)
            self._notify_listeners()
            return

        client = None
        packets_at_start = self.reading.packets_received
        try:
            _LOGGER.debug("Connecting to Femmto %s, reason=%s", self.address, reason)
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.name,
                max_attempts=5,
                timeout=15,
            )
            self.reading.connected = True
            self._notify_listeners()

            _LOGGER.debug("Starting FFB2 notifications for %.1fs", self.listen_duration)
            await client.start_notify(NOTIFY_UUID, self._notification_handler)
            await asyncio.sleep(self.listen_duration)
            await client.stop_notify(NOTIFY_UUID)

            received = self.reading.packets_received - packets_at_start
            _LOGGER.debug("Femmto listen finished, packets received=%s", received)

        except asyncio.CancelledError:
            raise
        except (BleakError, asyncio.TimeoutError, OSError) as err:
            self.reading.last_connection_error = str(err)
            _LOGGER.debug("Femmto BLE connection/listen failed: %s", err)
        except Exception as err:  # noqa: BLE001
            self.reading.last_connection_error = str(err)
            _LOGGER.exception("Unexpected Femmto BLE error")
        finally:
            self.reading.connected = False
            self._notify_listeners()
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass

    def _notification_handler(self, _sender: Any, data: bytearray) -> None:
        """Handle FFB2 notification."""
        packet = bytes(data)
        parsed = self._parse_packet(packet)
        if parsed is None:
            _LOGGER.debug("Ignoring invalid Femmto packet: %s", packet.hex("-").upper())
            return

        weight, raw_weight = parsed
        packet_hex = packet.hex("-").upper()

        self.reading.packets_received += 1
        self.reading.live_weight = round(weight, 3)
        self.reading.raw_packet = packet_hex
        self.reading.last_update = datetime.now()
        self.reading.person_on_scale = weight >= self.min_weight_kg

        if raw_weight == self._last_raw_weight and packet_hex == self._last_raw_packet:
            self._repeat_count += 1
        else:
            self._last_raw_weight = raw_weight
            self._last_raw_packet = packet_hex
            self._repeat_count = 1
        self.reading.repeat_count = self._repeat_count

        _LOGGER.debug(
            "Femmto packet=%s weight=%.3f kg repeat_count=%s",
            packet_hex,
            weight,
            self._repeat_count,
        )
        self._process_stability(weight)
        self.hass.loop.call_soon_threadsafe(self._notify_listeners)

    def _parse_packet(self, packet: bytes) -> tuple[float, int] | None:
        """Decode 20-byte Femmto notification."""
        if len(packet) != 20:
            return None
        if packet[0] != 0xAC or packet[1] != 0x17:
            return None
        raw_weight = int.from_bytes(packet[3:6], "big", signed=False)
        weight_kg = (raw_weight - WEIGHT_OFFSET) / 1000
        if weight_kg < -1 or weight_kg > 300:
            return None
        return max(0.0, weight_kg), raw_weight

    @callback
    def _clear_measurement_stable(self, _now=None) -> None:
        """Clear the stable flag after a short hold so it can retrigger for Bodymiscale."""
        self._stable_clear_unsub = None
        if self.reading.measurement_stable:
            self.reading.measurement_stable = False
            self._notify_listeners()

    def _arm_stable_clear_timer(self) -> None:
        """Start or restart stable hold timer."""
        if self._stable_clear_unsub:
            self._stable_clear_unsub()
        self._stable_clear_unsub = async_call_later(
            self.hass, self.stable_hold_seconds, self._clear_measurement_stable
        )

    def _accept_stable_weight(self, stable_weight: float, now: datetime, reason: str) -> None:
        """Accept a stable weight reading."""
        self.reading.measurement_stable = True
        if self._armed_for_next_measurement:
            self.reading.stable_weight = stable_weight
            self.reading.last_stable_update = now
            self._armed_for_next_measurement = False
            _LOGGER.info("Femmto stable weight detected: %.2f kg (%s)", stable_weight, reason)
        self._arm_stable_clear_timer()

    def _process_stability(self, weight: float) -> None:
        """Detect stable measurement with repeated-packet and window heuristics."""
        now = datetime.now()

        if weight <= self.reset_weight_kg:
            self._samples.clear()
            self._armed_for_next_measurement = True
            self.reading.measurement_stable = False
            self.reading.person_on_scale = False
            self._repeat_count = 0
            self._last_raw_weight = None
            self._last_raw_packet = None
            if self._stable_clear_unsub:
                self._stable_clear_unsub()
                self._stable_clear_unsub = None
            return

        if weight < self.min_weight_kg:
            return

        # Fast path based on the real behavior observed in nRF logs: stable values
        # are emitted as exactly repeated full packets for several seconds.
        if self._repeat_count >= self.repeat_stable_samples:
            self._accept_stable_weight(round(weight, 2), now, "repeated packet")
            return

        # Fallback path: variation inside window.
        self._samples.append((now, weight))
        cutoff = now - timedelta(seconds=self.stability_window)
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

        if len(self._samples) < self.stability_samples:
            return

        values = [sample_weight for _, sample_weight in self._samples]
        if max(values) - min(values) <= self.stability_delta:
            stable_weight = round(sum(values) / len(values), 2)
            self._accept_stable_weight(stable_weight, now, "window")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Femmto Scale."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = FemmtoScaleCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Femmto Scale."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: FemmtoScaleCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_stop()
    return unload_ok
