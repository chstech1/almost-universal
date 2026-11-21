"""Component entry lifecycle with real HA tasks/storage and fake radio/actions."""

import asyncio
from contextlib import ExitStack
from copy import deepcopy
from struct import pack
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

import custom_components.ununiversal_remote as integration
from custom_components.ununiversal_remote.menu import DOMAIN, SAMPLE_MENU
from custom_components.ununiversal_remote.remote import Remote
from custom_components.ununiversal_remote.stock import (
    HANDHELD_SAMPLE, MANUFACTURER, STOCK_HANDHELD_MODE, STOCK_NOTIFY, STOCK_SERVICES,
    STOCK_V1_MODE, STOCK_WRITE, V1_PREFIX, V1_SAMPLE, VERSION_QUERY,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
IDENTITY = bytes.fromhex("001122334455")
SWITCH = "switch.offline_bench"
EFFECT = {"kind": "switch", "target": SWITCH}


def press(screen=3, stamp=42):
    return V1_PREFIX + pack("<BBI", screen, 1, stamp)


async def until(predicate, timeout=3.3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class Link:
    def __init__(self, version=48, *, slow_close=False):
        self.is_connected = True
        self.version = version
        self.on_disconnect = None
        self.receiver = SimpleNamespace(uuid=STOCK_NOTIFY)
        self.writer = SimpleNamespace(uuid=STOCK_WRITE, properties=["write"])
        service = {STOCK_NOTIFY: self.receiver, STOCK_WRITE: self.writer}
        self.services = SimpleNamespace(
            get_service={STOCK_SERVICES[0]: SimpleNamespace(get_characteristic=service.get)}.get,
        )
        self.notify = None
        self.queried = asyncio.Event()
        self.close_started = asyncio.Event()
        self.close_gate = asyncio.Event()
        if not slow_close:
            self.close_gate.set()

    async def start_notify(self, char, callback):
        self.notify = callback

    async def write_gatt_char(self, char, data, *, response):
        assert (char, data, response) == (self.writer, VERSION_QUERY, True)
        self.queried.set()
        if self.version is not None:
            self.send(bytes([1, 0, 0, 0, 0, self.version]) + bytes(14))

    def send(self, data):
        self.notify(self.receiver, data)

    def lost(self):
        self.is_connected = False
        self.on_disconnect(self)

    async def disconnect(self):
        self.close_started.set()
        await self.close_gate.wait()
        self.lost()


class TestActionLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.hass = HomeAssistant(temp.name)
        self.links = asyncio.Queue()
        self.subscribers = {}
        self.entry = None
        self.actions = []
        self.action_effect = AsyncMock(side_effect=self.record)
        setup = ExitStack()
        self.addCleanup(setup.close)
        setup.enter_context(patch.object(Remote, "_run_effect", self.action_effect))
        self.no_services = setup.enter_context(patch.object(type(self.hass.services), "async_call",
            new=AsyncMock(side_effect=AssertionError("No HA services in this run"))))
        setup.enter_context(patch("custom_components.ununiversal_remote.remote.async_setup_component", return_value=True))
        setup.enter_context(patch.object(bluetooth, "async_register_callback", side_effect=self.subscribe))
        setup.enter_context(patch.object(bluetooth, "async_last_service_info",
            return_value=SimpleNamespace(address=ADDRESS, manufacturer_data={MANUFACTURER: IDENTITY})))
        setup.enter_context(patch.object(bluetooth, "async_ble_device_from_address", return_value=object()))
        setup.enter_context(patch("custom_components.ununiversal_remote.ble.establish_connection", side_effect=self.connect))
        setup.enter_context(patch.object(integration.panel_custom, "async_register_panel", return_value=None))
        setup.enter_context(patch.object(integration.frontend, "async_remove_panel"))
        tv, fallback = deepcopy(HANDHELD_SAMPLE), deepcopy(V1_SAMPLE)
        tv["screens"]["tv"]["buttons"]["soft_1"]["effect"] = EFFECT
        fallback["screens"]["controls"]["buttons"]["soft_1"]["effect"] = EFFECT
        await Store(self.hass, 1, f"{DOMAIN}.offline").async_save({
            "menu": SAMPLE_MENU, "revision": 4, "stock_menus": {STOCK_HANDHELD_MODE: tv, STOCK_V1_MODE: fallback},
        })
        self.addAsyncCleanup(self.unload)

    async def record(self, effect):
        self.actions.append(effect)

    def subscribe(self, hass, handler, matcher, mode):
        self.assertEqual(matcher["address"], ADDRESS)
        self.subscribers[handler] = matcher
        return lambda: self.subscribers.pop(handler)

    async def connect(self, cls, device, address, *, disconnected_callback, **kwargs):
        self.assertEqual(address, ADDRESS)
        link = await self.links.get()
        link.on_disconnect = disconnected_callback
        return link

    async def setup(self, *links, mode=STOCK_HANDHELD_MODE):
        for link in links:
            self.links.put_nowait(link)
        self.entry = ConfigEntry(title="Offline", domain=DOMAIN, version=1, minor_version=1,
            source="user", entry_id="offline", unique_id=None, discovery_keys=MappingProxyType({}), subentries_data=(),
            data={"remote_id": "offline"}, options={"ble_mode": mode, "ble_address": ADDRESS,
                "stock_manufacturer_id": IDENTITY.hex(), "mqtt_enabled": False})
        self.assertTrue(await integration.async_setup_entry(self.hass, self.entry))
        return self.entry.runtime_data

    async def unload(self):
        if self.entry is not None:
            entry, self.entry = self.entry, None
            self.assertTrue(await integration.async_unload_entry(self.hass, entry))
        self.no_services.assert_not_awaited()

    async def armed(self, remote, link):
        await until(lambda: remote.ble.client is link and remote.ble.active is not None)

    async def drain(self, remote):
        async with asyncio.timeout(1):
            await remote.ble.events.join()
            await remote.effects.join()

    async def test_drop_before_version_reply_recovers_without_waiting_for_handshake_timeout(self):
        incomplete, recovered = Link(version=None), Link()
        remote = await self.setup(incomplete, recovered)
        self.addCleanup(recovered.close_gate.set)
        await until(incomplete.queried.is_set)
        incomplete.send(press())
        incomplete.lost()
        self.assertFalse(remote.configuration()["ble_active"])
        await self.armed(remote, recovered)
        incomplete.send(bytes([1, 0, 0, 0, 0, 48]) + bytes(14))
        incomplete.send(press())
        self.assertEqual(self.actions, [])
        recovered.send(press())
        await self.drain(remote)
        self.assertEqual(self.actions, [EFFECT])

    async def test_unload_waits_for_an_in_progress_disconnect(self):
        old = Link(version=47, slow_close=True)
        remote = await self.setup(old)
        try:
            await until(old.close_started.is_set)
            unload = asyncio.create_task(self.unload())
            # The fake backend has not yet released its connection slot.
            done, _ = await asyncio.wait({unload}, timeout=0.03)
            self.assertFalse(done, "unload returned while the fake radio still held the connection")
        finally:
            old.close_gate.set()
            if "unload" in locals():
                await unload
        self.assertFalse(old.is_connected)
        self.assertFalse(self.subscribers)
        self.assertTrue(all(task.done() for task in [*remote.ble.tasks, remote.worker]))

    async def test_disconnect_during_dispatch_drops_pending_and_accepts_reused_timestamp(self):
        first, second, third = Link(), Link(), Link()
        remote = await self.setup(first, second, third)
        await self.armed(remote, first)
        first.send(press())
        first.send(press())
        await self.drain(remote)
        self.assertEqual(self.actions, [EFFECT])
        async with remote.lock:
            first.send(press(stamp=43))
            await until(remote.ble.events.empty)
            first.lost()
        await self.armed(remote, second)
        first.send(press(stamp=44))
        await self.drain(remote)
        self.assertEqual(self.actions, [EFFECT])
        second.send(press())
        second.send(press())
        await self.drain(remote)
        self.assertEqual(self.actions, [EFFECT, EFFECT])
        second.lost()
        await self.armed(remote, third)
        second.send(press(stamp=44))
        third.send(press())
        await self.drain(remote)
        self.assertEqual(self.actions, [EFFECT, EFFECT, EFFECT])

    async def test_effect_waiting_behind_started_action_is_discarded_on_link_loss(self):
        first, second = Link(), Link()
        remote = await self.setup(first, second)
        await self.armed(remote, first)
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_effect(effect):
            self.actions.append(effect)
            entered.set()
            await release.wait()

        self.action_effect.side_effect = slow_effect
        first.send(press())
        await until(entered.is_set)
        first.send(press(stamp=43))
        await until(lambda: remote.effects.qsize() == 1)
        first.lost()
        release.set()
        await self.armed(remote, second)
        await self.drain(remote)
        self.assertEqual(self.actions, [EFFECT])
        second.send(press(stamp=43))
        await self.drain(remote)
        self.assertEqual(self.actions, [EFFECT, EFFECT])

    async def test_readiness_follows_link_status_before_delayed_disconnect_callback(self):
        link = Link()
        remote = await self.setup(link)
        await self.armed(remote, link)
        self.assertTrue(remote.configuration()["ble_active"])
        link.is_connected = False
        self.assertFalse(remote.configuration()["ble_active"])
        link.send(press())
        await self.drain(remote)
        self.assertEqual(self.actions, [])
        link.lost()

    async def test_reload_cycles_keep_profile_action_and_remove_old_subscribers_and_tasks(self):
        prior = []
        for mode, screen in ((STOCK_HANDHELD_MODE, 3), (STOCK_V1_MODE, 2), (STOCK_HANDHELD_MODE, 3)):
            link = Link()
            remote = await self.setup(link, mode=mode)
            await self.armed(remote, link)
            self.assertEqual(len(self.subscribers), 1)
            for old, frame in prior:
                old.send(frame)
            current = press(screen)
            link.send(current)
            await self.drain(remote)
            self.assertEqual(self.actions, [EFFECT] * (len(prior) + 1))
            prior.append((link, current))
            # A notification can be queued just before teardown.
            link.send(press(screen, stamp=43))
            await self.unload()
            self.assertFalse(link.is_connected)
            self.assertFalse(self.subscribers)
            self.assertTrue(all(task.done() for task in [*remote.ble.tasks, remote.worker]))
            self.assertNotIn(DOMAIN, self.hass.data)
            self.assertEqual(self.actions, [EFFECT] * len(prior))
