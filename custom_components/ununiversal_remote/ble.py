"""Connect a configured handheld through Home Assistant's Bluetooth adapters."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import logging
from struct import pack

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.core import callback

from .protocol import (
    CONTROL, EVENT, SERVICE, STATUS, STATUS_PACKET, WRITE_SIZE, MenuPackage, status_writes,
)

LOGGER = logging.getLogger(__name__)


@dataclass(eq=False, frozen=True)
class ActiveMenu:
    """One verified activation on one connection."""

    package: MenuPackage


async def _status(client):
    raw = await client.read_gatt_char(STATUS)
    if len(raw) != STATUS_PACKET.size:
        raise ValueError("Invalid handheld status length")
    version, active, revision, source = STATUS_PACKET.unpack(raw)
    if version != 1 or active not in (0, 1):
        raise ValueError("Unsupported handheld Bluetooth status")
    return active, revision, source


async def _write(client, payload):
    await client.write_gatt_char(CONTROL, payload, response=True)


async def activate(client, package):
    """Transfer a changed package, then verify activation on every connection."""
    _, revision, _ = await _status(client)
    if revision != package.revision:
        await _write(client, b"\x01" + package.revision + pack("<H", len(package.data)))
        chunk = WRITE_SIZE - 3
        for offset in range(0, len(package.data), chunk):
            await _write(client, pack("<BH", 2, offset) + package.data[offset:offset + chunk])
        await _write(client, b"\x03")
        _, revision, _ = await _status(client)
        if revision != package.revision:
            raise ValueError("Handheld did not commit the expected menu revision")
    await _write(client, b"\x04" + package.revision)
    active, revision, source = await _status(client)
    if not active or revision != package.revision or not 1 <= source <= len(package.screen_ids):
        raise ValueError("Handheld did not activate the expected menu revision")
    return source


class BleRemote:
    """Own the GATT connection and drop input from unverified activations."""

    def __init__(self, hass, entry, address, on_event, live_text):
        self.hass = hass
        self.entry = entry
        self.address = address
        self.on_event = on_event
        self.live_text = live_text
        self.package = None
        self.client = None
        self.active = None
        self.wake = asyncio.Event()
        self.events = asyncio.Queue(maxsize=128)
        self.text_reset = False

    def start(self, bluetooth):
        """Observe advertisements on Home Assistant's connectable adapters."""
        self.bluetooth = bluetooth
        self.unsubscribe = bluetooth.async_register_callback(
            self.hass, self._advertised,
            {"address": self.address, "service_uuid": SERVICE, "connectable": True},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        self.tasks = [
            self.entry.async_create_background_task(self.hass, self._run(), "remote BLE connection"),
            self.entry.async_create_background_task(self.hass, self._dispatch_events(), "remote BLE events"),
        ]

    async def stop(self):
        """Disarm and disconnect on integration unload."""
        self.active = None
        self.unsubscribe()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    @callback
    def _advertised(self, service_info, change):
        if self.client is None:
            self.wake.set()

    def set_package(self, package):
        """Disarm synchronously before making a new menu available to BLE."""
        self.active = None
        self.package = package
        self.wake.set()

    def refresh_text(self, *, navigation=False):
        self.text_reset |= navigation
        self.wake.set()

    def is_active(self, activation):
        return activation is self.active and self.client is not None and self.client.is_connected

    def _disconnected(self, client):
        if self.client is client:
            self.active = None
            self.client = None
            self.wake.set()

    def _notification(self, client, payload):
        if self.client is client and (activation := self.active) is not None and not self.events.full():
            self.events.put_nowait((activation, bytes(payload)))

    async def _dispatch_events(self):
        while True:
            activation, payload = await self.events.get()
            try:
                if self.is_active(activation):
                    await self.on_event(activation, payload)
            finally:
                self.events.task_done()

    async def _run(self):
        bluetooth = self.bluetooth
        while True:
            self.wake.clear()
            device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            ) if self.package is not None else None
            if device is None:
                await self.wake.wait()
                continue
            client = None
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache, device, self.address,
                    disconnected_callback=self._disconnected, max_attempts=2,
                    services=[SERVICE],
                )
                self.client = client
                await client.start_notify(
                    EVENT, lambda _, payload, source=client: self._notification(source, payload)
                )
                await self._serve(client)
            except (BleakError, TimeoutError, OSError, ValueError) as error:
                LOGGER.debug("Handheld %s connection or sync failed: %s", self.address, error)
            finally:
                self.active = None
                self.client = None
                if client is not None and client.is_connected:
                    with suppress(BleakError, TimeoutError, OSError):
                        async with asyncio.timeout(5):
                            await client.disconnect()
            await asyncio.sleep(2)

    async def _serve(self, client):
        previous = None
        while self.client is client and client.is_connected:
            self.wake.clear()
            if (package := self.package) is not None:
                if self.text_reset:
                    previous = None
                    self.text_reset = False
                if self.active is None:
                    source = await activate(client, package)
                    if self.client is not client or not client.is_connected:
                        return
                    if self.package is not package:
                        continue
                    self.active = ActiveMenu(package)
                    previous = None
                else:
                    activation = self.active
                    active, revision, source = await _status(client)
                    if not self.is_active(activation):
                        continue
                    if not active or revision != package.revision or not 1 <= source <= len(package.screen_ids):
                        raise ValueError("Handheld status no longer matches the active menu")
                if self.wake.is_set():
                    continue
                text = self.live_text(package.screen_ids[source - 1])
                if text is not None and previous != (source, text):
                    previous = await self._write_live_text(client, source, text)
            await self.wake.wait()

    async def _write_live_text(self, client, source, text):
        activation = self.active
        for payload in status_writes(source, text):
            if not self.is_active(activation) or self.text_reset:
                return None
            try:
                await _write(client, payload)
            except BleakError:
                # The remote can navigate between the status read and a write.
                if not self.is_active(activation):
                    return None
                active, revision, current = await _status(client)
                if active and revision == activation.package.revision and current != source:
                    self.wake.set()
                    return None
                raise
        return source, text
