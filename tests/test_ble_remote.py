"""Run the HA central against production firmware compiled for the host."""

import asyncio
from copy import deepcopy
import ctypes
from pathlib import Path
from struct import pack
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from bleak.exc import BleakError

from custom_components.ununiversal_remote.ble import BleRemote, activate
from custom_components.ununiversal_remote.menu import validate_menu
from custom_components.ununiversal_remote.protocol import (
    CONTROL, EVENT, SERVICE, STATUS, STATUS_PACKET, compile_menu, status_writes,
)
from custom_components.ununiversal_remote.remote import Remote

SWITCH = "switch.office_lights"
ADDRESS = "AA:BB:CC:DD:EE:FF"
OFFICE = {
    "home": "office",
    "screens": {
        "office": {"title": "Office", "buttons": {
            "soft_1": {"label": "Lights", "effect": {"kind": "switch", "target": SWITCH}},
        }},
    },
}
KeyCallback = ctypes.CFUNCTYPE(None, ctypes.c_uint16, ctypes.c_uint8, ctypes.c_int8)


class FirmwareGatt:
    def __init__(self, library, package):
        self.library = library
        self.is_connected = True
        self.ignore = set()
        self.writes = []
        self.frames = []
        self.notify = None
        assert library.ur_restore(bytes(8), package.data, len(package.data))
        library.keys_reset()
        self.emit = KeyCallback(self._emit)

    def _emit(self, control, kind, steps):
        frame = ctypes.create_string_buffer(8)
        if self.library.ur_input(control, kind, steps, frame):
            self.frames.append(frame.raw)
            if self.notify:
                self.notify(EVENT, frame.raw)

    def sample(self, word, count=1):
        for _ in range(count):
            self.library.keys_sample(word, 0, self.emit)

    async def read_gatt_char(self, uuid):
        assert uuid == STATUS
        result = ctypes.create_string_buffer(14)
        self.library.ur_status(result)
        return result.raw

    async def write_gatt_char(self, uuid, payload, *, response):
        assert uuid == CONTROL and response and len(payload) <= 20
        self.writes.append(payload)
        if payload[0] not in self.ignore and not self.library.ur_write(payload, len(payload)):
            raise BleakError("Firmware rejected GATT write")

    async def start_notify(self, uuid, callback):
        assert uuid == EVENT
        self.notify = callback

    async def disconnect(self):
        self.is_connected = False
        self.library.ur_disconnect()


class TestFirmwareProtocol(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        build = TemporaryDirectory()
        cls.addClassCleanup(build.cleanup)
        source = Path(__file__).resolve().parents[1] / "firmware" / "v06"
        lib = Path(build.name) / "remote.so"
        subprocess.run(["cc", "-std=c99", "-shared", "-fPIC", "-o", str(lib),
                        str(source / "remote.c"), str(source / "keys.c")], check=True)
        cls.firmware = ctypes.CDLL(str(lib))
        cls.firmware.ur_restore.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t)
        cls.firmware.ur_restore.restype = ctypes.c_bool
        cls.firmware.ur_status.argtypes = (ctypes.c_void_p,)
        cls.firmware.ur_write.argtypes = (ctypes.c_char_p, ctypes.c_size_t)
        cls.firmware.ur_write.restype = ctypes.c_bool
        cls.firmware.ur_input.argtypes = (
            ctypes.c_uint16, ctypes.c_uint8, ctypes.c_int8, ctypes.c_void_p,
        )
        cls.firmware.ur_input.restype = ctypes.c_bool
        cls.firmware.keys_sample.argtypes = (ctypes.c_uint32, ctypes.c_uint8, KeyCallback)

    async def test_revision_checks_detect_silent_gatt_failure(self):
        package = compile_menu(OFFICE)
        client = FirmwareGatt(self.firmware, package)
        for dropped in (3, 4):
            with self.subTest(dropped=dropped):
                self.assertTrue(self.firmware.ur_restore(bytes(8), package.data, len(package.data)))
                client.ignore = {dropped}
                with self.assertRaisesRegex(ValueError, "expected menu revision"):
                    await activate(client, package)

    async def test_status_offsets_use_utf8_byte_lengths(self):
        package = compile_menu(OFFICE)
        client = FirmwareGatt(self.firmware, package)
        home = await activate(client, package)
        value = "Room 72°F\nHeating 68°F"
        writes = list(status_writes(home, value))
        self.assertEqual(b"".join(write[6:] for write in writes).decode(), value)
        self.assertEqual(writes[1][5], len(writes[0][6:]))
        for write in writes:
            write[6:].decode("utf-8")
            await client.write_gatt_char(CONTROL, write, response=True)
        client.writes.clear()
        await activate(client, package)
        self.assertEqual(client.writes, [bytes([4]) + package.revision])

    async def test_soft_a_toggles_office_switch_once_per_fresh_press(self):
        menu = validate_menu(OFFICE)
        package = compile_menu(menu)
        client = FirmwareGatt(self.firmware, package)
        state = SimpleNamespace(state="off")
        states = []

        async def toggle(*args, **kwargs):
            state.state = "on" if state.state == "off" else "off"
            states.append(state.state)

        hass = SimpleNamespace(
            states=Mock(get=Mock(return_value=state)),
            services=Mock(async_call=AsyncMock(side_effect=toggle)),
            bus=Mock(),
        )
        entry = SimpleNamespace(entry_id="test", data={"remote_id": "office"}, options={})
        entry.async_create_background_task = lambda _, coro, name: asyncio.create_task(coro, name=name)
        with patch("custom_components.ununiversal_remote.remote.Store"):
            remote = Remote(hass, entry)
        remote.menu = menu
        remote.ble = BleRemote(hass, entry, ADDRESS, remote._ble_event, lambda screen_id: None)
        remote.ble.set_package(package)
        worker = asyncio.create_task(remote._run_effects())
        bluetooth = Mock(async_ble_device_from_address=Mock(return_value=object()))
        self.addAsyncCleanup(self._stop_worker, worker)
        with patch("custom_components.ununiversal_remote.ble.establish_connection",
                   AsyncMock(return_value=client)):
            remote.ble.start(bluetooth)
            self.addAsyncCleanup(remote.ble.stop)
            for _ in range(20):
                if remote.ble.active:
                    break
                await asyncio.sleep(0)
            self.assertIsNotNone(remote.ble.active)
            bluetooth.async_ble_device_from_address.assert_called_with(hass, ADDRESS, connectable=True)
            self.assertEqual(bluetooth.async_register_callback.call_args.args[2],
                             {"address": ADDRESS, "service_uuid": SERVICE, "connectable": True})
            client.sample(0)      # Baseline
            client.sample(1, 37)  # Press A, hold, repeat
            client.sample(0)      # Release A
            await remote.ble.events.join()
            await remote.effects.join()
            self.assertEqual(states, ["on"])
            self.assertEqual(
                client.frames[:4], [pack("<IHBb", 1, 1, kind, 0) for kind in (1, 3, 4, 2)]
            )
            client.sample(1)      # Another fresh press
            client.sample(0)
            await remote.ble.events.join()
            await remote.effects.join()
            self.assertEqual(states, ["on", "off"])
            self.assertEqual(hass.services.async_call.call_args_list, [
                call("switch", "toggle", target={"entity_id": SWITCH}, blocking=True),
            ] * 2)
            remote.ble._notification(client, client.frames[0])
            remote.ble.set_package(None)  # A received frame queued before save becomes stale.
            await remote.ble.events.join()
            await remote.effects.join()
            self.assertEqual(states, ["on", "off"])

    async def test_press_frame_reports_screen_before_local_navigation(self):
        menu = deepcopy(OFFICE)
        menu["screens"]["office"]["buttons"]["soft_1"]["next"] = "other"
        menu["screens"]["other"] = {"title": "Other"}
        package = compile_menu(menu)
        client = FirmwareGatt(self.firmware, package)
        await activate(client, package)
        client.sample(0)
        client.sample(1)
        self.assertEqual(client.frames, [pack("<IHBb", 1, 1, 1, 0)])
        self.assertEqual(STATUS_PACKET.unpack(await client.read_gatt_char(STATUS))[-1], 2)

    @staticmethod
    async def _stop_worker(worker):
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


class TestMenuExport(unittest.TestCase):
    def test_ha_action_changes_fingerprint_but_not_handheld_blob(self):
        before = compile_menu(OFFICE)
        changed = deepcopy(OFFICE)
        changed["screens"]["office"]["buttons"]["soft_1"]["effect"]["target"] = "switch.test"
        after = compile_menu(changed)
        self.assertEqual(before.data, after.data)
        self.assertNotEqual(before.revision, after.revision)
        self.assertEqual(before.data[:8], b"URM1\x01\x00\x01\x00")

    def test_export_enforces_utf8_byte_limits(self):
        changed = deepcopy(OFFICE)
        changed["screens"]["office"]["buttons"]["soft_1"]["label"] = "温" * 11
        with self.assertRaisesRegex(ValueError, "32-byte"):
            compile_menu(changed)
