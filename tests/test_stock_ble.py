"""Exercise the stock GATT central and HA action path with no radio or broker."""

import asyncio
from copy import deepcopy
from struct import pack
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.core import HomeAssistant, callback

from custom_components.ununiversal_remote.menu import SAMPLE_MENU, validate_menu
from custom_components.ununiversal_remote.remote import Remote
from custom_components.ununiversal_remote.stock import (
    A_PRESSED, HANDHELD_SAMPLE, MANUFACTURER, STOCK_HANDHELD_MODE, STOCK_MODE, STOCK_NOTIFY,
    STOCK_SAMPLE, STOCK_SERVICES, STOCK_V1_MODE, STOCK_WRITE, V1_PREFIX, V1_SAMPLE, VERSION_QUERY, StockRemote,
    decode_stock_event, stock_menu,
)

ADDRESS = "AA:BB:CC:DD:EE:FF"
MANUFACTURER_ID = bytes.fromhex("001122334455")
SWITCH = "switch.bench_test"


class StockGatt:
    def __init__(self, *, version=48, with_response=True):
        self.is_connected = True
        self.version = version
        self.writes = []
        self.notifications = None
        self.on_disconnect = None
        self.writer = SimpleNamespace(uuid=STOCK_WRITE, properties=["write" if with_response else "write-without-response"])
        self.receiver = SimpleNamespace(uuid=STOCK_NOTIFY)
        service = SimpleNamespace(get_characteristic={
            STOCK_WRITE: self.writer, STOCK_NOTIFY: self.receiver,
        }.get)
        self.services = SimpleNamespace(get_service={STOCK_SERVICES[0]: service}.get)

    async def start_notify(self, characteristic, callback):
        assert characteristic is self.receiver
        self.notifications = callback
        # A queued notification at subscription time must not run any action.
        self.send(A_PRESSED)

    async def write_gatt_char(self, characteristic, value, *, response):
        assert characteristic is self.writer
        self.writes.append((value, response))
        self.send(A_PRESSED)
        self.send(bytes([1, 0, 0, 0, 0, self.version]) + bytes(14))

    def send(self, value):
        self.notifications(self.receiver, value)

    async def disconnect(self):
        self.is_connected = False
        if self.on_disconnect:
            self.on_disconnect(self)


class TestStockRemote(unittest.IsolatedAsyncioTestCase):
    async def make_remote(self, mode, clients, *, saved=None, mqtt_enabled=False):
        test_dir = TemporaryDirectory()
        self.addCleanup(test_dir.cleanup)
        hass = HomeAssistant(test_dir.name)
        entry = SimpleNamespace(entry_id="test", data={"remote_id": "test"}, options={
            "ble_mode": mode, "ble_address": ADDRESS, "stock_manufacturer_id": MANUFACTURER_ID.hex(),
            "mqtt_enabled": mqtt_enabled,
        })
        entry.async_create_background_task = lambda _, coro, name: asyncio.create_task(coro, name=name)
        state_changes = []

        @callback
        def toggle(call):
            self.assertEqual(call.data["entity_id"], SWITCH)
            state = "off" if hass.states.get(SWITCH).state == "on" else "on"
            hass.states.async_set(SWITCH, state)
            state_changes.append(state)

        hass.states.async_set(SWITCH, "off")
        hass.services.async_register("switch", "toggle", toggle)
        remote = Remote(hass, entry)
        remote.store = SimpleNamespace(
            async_load=AsyncMock(return_value=saved or {"menu": SAMPLE_MENU, "revision": 4}),
            async_save=AsyncMock(),
        )
        advertisement = SimpleNamespace(address=ADDRESS, manufacturer_data={MANUFACTURER: MANUFACTURER_ID})
        radio = Mock(
            async_last_service_info=Mock(return_value=advertisement),
            async_ble_device_from_address=Mock(return_value=object()),
        )
        remaining = iter(clients)

        async def connect(_, device, address, **kwargs):
            self.assertIs(device, radio.async_ble_device_from_address.return_value)
            self.assertEqual(address, ADDRESS)
            client = next(remaining, None)
            if client is None:
                await asyncio.Event().wait()
            else:
                client.on_disconnect = kwargs["disconnected_callback"]
                return client

        async def bluetooth_start(address):
            from custom_components.ununiversal_remote.protocol import compile_menu

            remote.ble = StockRemote(
                hass, entry, address, remote._ble_event, remote._live_text, MANUFACTURER_ID, mode
            )
            remote.ble.set_package(compile_menu(remote.editor_menu))
            remote.ble.start(radio)

        connect_patch = patch("custom_components.ununiversal_remote.ble.establish_connection", side_effect=connect)
        connect_mock = connect_patch.start()
        self.addCleanup(connect_patch.stop)
        with patch.object(remote, "_start_bluetooth", side_effect=bluetooth_start), patch(
            "custom_components.ununiversal_remote.remote.async_wait_for_mqtt_client",
        ) as mqtt_start:
            await remote.start()
            mqtt_start.assert_not_awaited()
        self.addAsyncCleanup(remote.stop)
        return remote, radio, connect_mock, state_changes

    async def wait_active(self, remote, client):
        async with asyncio.timeout(4):
            while remote.ble.active is None or remote.ble.client is not client:
                await asyncio.sleep(0.01)

    async def drain(self, remote):
        async with asyncio.timeout(2):
            await remote.ble.events.join()
            await remote.effects.join()

    async def test_marker_calls_native_switch_once_and_reconnect_does_not_replay(self):
        first = StockGatt(with_response=False)
        second = StockGatt()
        remote, _, _, states = await self.make_remote(STOCK_MODE, [first, second])
        await self.wait_active(remote, first)
        saved = remote.configuration()
        saved["menu"] = deepcopy(saved["menu"])
        saved["menu"]["screens"]["home"]["buttons"]["soft_1"]["effect"] = {
            "kind": "switch", "target": SWITCH,
        }
        await remote.save(saved["menu"], saved["revision"])
        self.assertEqual(remote.store.async_save.call_args.args[0]["menu"], validate_menu(SAMPLE_MENU))
        await self.wait_active(remote, first)
        version_frame = bytes.fromhex("01 00 00 00 61 30") + bytes(14)
        for unrelated in [version_frame, A_PRESSED[:-1], A_PRESSED + b"\x00",
                          A_PRESSED[:-1] + b"2", V1_PREFIX + pack("<BBI", 1, 1, 44)]:
            first.send(unrelated)
        await self.drain(remote)
        self.assertEqual(states, [])
        first.send(A_PRESSED)
        await self.drain(remote)
        self.assertEqual(states, ["on"])
        first.send(A_PRESSED)  # Arrives before disconnect but has yet to be dispatched.
        await first.disconnect()
        await self.wait_active(remote, second)
        first.send(A_PRESSED)  # Delayed callback on the old physical connection.
        await self.drain(remote)
        self.assertEqual(states, ["on"])
        second.send(A_PRESSED)
        await self.drain(remote)
        self.assertEqual(states, ["on", "off"])
        self.assertEqual(first.writes, [(VERSION_QUERY, False)])
        self.assertEqual(second.writes, [(VERSION_QUERY, True)])

    async def test_versioned_press_routes_per_screen_and_discards_duplicates(self):
        client = StockGatt()
        remote, _, _, changes = await self.make_remote(STOCK_V1_MODE, [client])
        await self.wait_active(remote, client)
        draft = deepcopy(remote.editor_menu)
        for screen, key in (("controls", "soft_1"), ("home", "up")):
            draft["screens"][screen]["buttons"].setdefault(key, {})["effect"] = {
                "kind": "switch", "target": SWITCH,
            }
        await remote.save(draft, 4)
        await self.wait_active(remote, client)
        for screen, control in ((1, 1), (2, 4), (1, 5), (2, 14), (3, 1), (2, 20)):
            client.send(V1_PREFIX + pack("<BBI", screen, control, 8))
        client.send(A_PRESSED)
        await self.drain(remote)
        self.assertEqual(changes, [])
        controls_a = V1_PREFIX + pack("<BBI", 2, 1, 0x12345678)
        self.assertEqual(controls_a.hex(" "), "7e 00 00 00 55 52 01 01 02 01 78 56 34 12")
        client.send(controls_a)
        client.send(V1_PREFIX + pack("<BBI", 1, 9, 12))
        client.send(controls_a)
        await self.drain(remote)
        self.assertEqual(changes, ["on", "off"])
        self.assertEqual(client.writes, [(VERSION_QUERY, True)])

    async def test_wrong_stock_version_never_activates(self):
        client = StockGatt(version=47)
        remote, _, _, states = await self.make_remote(STOCK_MODE, [client])
        async with asyncio.timeout(2):
            while client.is_connected:
                await asyncio.sleep(0.01)
        client.send(A_PRESSED)
        self.assertIsNone(remote.ble.active)
        self.assertEqual(states, [])

    def test_handheld_wire_id_matrix_and_fixed_bindings(self):
        reported = {
            1: "soft_1", 2: "soft_2", 3: "soft_3", 7: "left", 8: "right", 9: "up", 10: "down",
            11: "ok", 12: "back", 13: "home", 15: "mute", 16: "volume_up", 17: "volume_down",
            18: "channel_up", 19: "channel_down",
        }
        for screen in (0, 1, 2, 3, 4, 255):
            for control in range(22):
                frame = V1_PREFIX + pack("<BBI", screen, control, 1)
                expected = ("tv", reported[control], "press", 0) if screen == 3 and control in reported else None
                self.assertEqual(decode_stock_event(frame, STOCK_HANDHELD_MODE), expected, (screen, control))
                if screen == 3:
                    self.assertIsNone(decode_stock_event(frame, STOCK_V1_MODE))
                    self.assertIsNone(decode_stock_event(frame, STOCK_MODE))
        frame = bytes.fromhex("7e 00 00 00 55 52 01 01 03 0c 78 56 34 12")
        self.assertEqual(decode_stock_event(frame, STOCK_HANDHELD_MODE), ("tv", "back", "press", 0))
        for malformed in (frame[:-1], frame + b"\0", frame[:7] + b"\2" + frame[8:], A_PRESSED):
            self.assertIsNone(decode_stock_event(malformed, STOCK_HANDHELD_MODE))
        for screen, key in (("activities", "ok"), ("tv", "soft_4"), ("tv", "on"), ("tv", "wheel")):
            draft = validate_menu(HANDHELD_SAMPLE)
            draft["screens"][screen]["buttons"].setdefault(key, {})["effect"] = {"kind": "switch", "target": SWITCH}
            with self.assertRaises(ValueError):
                stock_menu(draft, STOCK_HANDHELD_MODE)

    async def test_handheld_binds_tv_only_and_keeps_existing_controls_a(self):
        old = validate_menu(V1_SAMPLE)
        old["screens"]["controls"]["buttons"]["soft_1"]["effect"] = {"kind": "switch", "target": SWITCH}
        saved = {"menu": SAMPLE_MENU, "revision": 4, "stock_menus": {STOCK_V1_MODE: old}}
        first, second = StockGatt(), StockGatt()
        remote, _, _, states = await self.make_remote(
            STOCK_HANDHELD_MODE, [first, second], saved=saved, mqtt_enabled=True,
        )
        self.assertFalse(remote.configuration()["mqtt_enabled"])
        events, scripts = [], []

        @callback
        def observe(event):
            events.append(event.data)

        @callback
        def tv_back(call):
            scripts.append(call.service)

        remote.hass.bus.async_listen("ununiversal_remote_input", observe)
        remote.hass.services.async_register("script", "bench_tv_back", tv_back)
        remote.hass.states.async_set("script.bench_tv_back", "off")
        await self.wait_active(remote, first)
        draft = deepcopy(remote.editor_menu)
        keys = draft["screens"]["tv"]["buttons"]
        keys["soft_1"]["effect"] = {"kind": "switch", "target": SWITCH}
        keys["back"] = {"effect": {"kind": "script", "target": "script.bench_tv_back"}}
        await remote.save(draft, 4)
        await self.wait_active(remote, first)
        persisted = remote.store.async_save.call_args.args[0]
        self.assertEqual(persisted["stock_menus"][STOCK_V1_MODE], old)
        self.assertEqual(persisted["stock_menus"][STOCK_HANDHELD_MODE], draft)
        self.assertEqual(persisted["menu"], validate_menu(SAMPLE_MENU))

        tv_a = bytes.fromhex("7e 00 00 00 55 52 01 01 03 01 01 00 00 00")
        for screen, control in ((2, 1), (3, 4), (3, 5), (3, 6), (3, 14), (3, 20), (4, 1)):
            first.send(V1_PREFIX + pack("<BBI", screen, control, 55))
        first.send(tv_a)
        first.send(tv_a)
        first.send(bytes.fromhex("7e 00 00 00 55 52 01 01 03 0c 78 56 34 12"))
        await self.drain(remote)
        await remote.hass.async_block_till_done()
        self.assertEqual(states, ["on"])
        self.assertEqual(scripts, ["bench_tv_back"])
        self.assertEqual([(event["screen_id"], event["button_id"], event["transport"]) for event in events], [
            ("tv", "soft_1", STOCK_HANDHELD_MODE), ("tv", "back", STOCK_HANDHELD_MODE),
        ])
        await first.disconnect()
        await self.wait_active(remote, second)
        first.send(tv_a)
        await self.drain(remote)
        self.assertEqual(states, ["on"])
        second.send(V1_PREFIX + pack("<BBI", 3, 1, 2))
        await self.drain(remote)
        self.assertEqual(states, ["on", "off"])
        self.assertEqual(first.writes, second.writes)
        self.assertEqual(first.writes, [(VERSION_QUERY, True)])

    async def test_watch_tv_entry_uses_only_explicit_deduplicated_reports(self):
        first, second = StockGatt(), StockGatt()
        remote, _, _, _ = await self.make_remote(STOCK_HANDHELD_MODE, [first, second])
        entries, inputs, effects = [], [], []
        remote.hass.bus.async_listen("ununiversal_remote_page_entry", callback(lambda event: entries.append(event.data)))
        remote.hass.bus.async_listen("ununiversal_remote_input", callback(lambda event: inputs.append(event.data)))
        remote.hass.services.async_register("script", "entry_fixture", callback(lambda call: effects.append(call.service)))
        remote.hass.services.async_register("automation", "trigger", callback(lambda call: effects.append(dict(call.data))))
        remote.hass.states.async_set("script.entry_fixture", "off")
        remote.hass.states.async_set("automation.entry_fixture", "on")
        header = bytes.fromhex("7e 00 00 00 55 52 01 02 03 00")

        def report(timestamp):
            return header + pack("<I", timestamp)

        await self.wait_active(remote, first)
        self.assertIsNone(remote.configuration()["tv_entry_action"])
        first.send(report(0))
        first.send(report(0))
        await self.drain(remote)
        await remote.hass.async_block_till_done()
        self.assertEqual([event["timestamp"] for event in entries], [0])
        self.assertEqual(effects, [])

        menu = deepcopy(remote.editor_menu)
        script = {"kind": "script", "target": "script.entry_fixture"}
        with self.assertRaisesRegex(ValueError, "script entity"):
            await remote.save(menu, 4, tv_entry_action={**script, "target": "automation.entry_fixture"})
        remote.store.async_save.assert_not_awaited()
        await remote.save(menu, 4, tv_entry_action=script)
        self.assertEqual(remote.store.async_save.call_args.args[0]["tv_entry_action"], script)
        self.assertEqual(remote.editor_menu, menu)
        await remote.save(menu, 5)
        self.assertEqual(remote.configuration()["tv_entry_action"], script)
        await self.wait_active(remote, first)
        self.assertEqual(effects, [])
        for packet in (report(0), report(1)[:-1], report(1) + bytes(1),
                       header[:8] + bytes([4, 0]) + pack("<I", 1),
                       header[:9] + bytes([1]) + pack("<I", 1),
                       header[:7] + bytes([0x20]) + report(1)[8:],
                       header[:7] + bytes([0x10]) + report(1)[8:]):
            first.send(packet)
        first.send(V1_PREFIX + pack("<BBI", 3, 1, 1))
        first.send(report(1))
        first.send(report(1))
        first.send(report(2))
        await self.drain(remote)
        await remote.hass.async_block_till_done()
        self.assertEqual(effects, ["entry_fixture", "entry_fixture"])
        self.assertEqual([event["timestamp"] for event in entries], [0, 1, 2])
        self.assertEqual([event["button_id"] for event in inputs], ["soft_1"])

        await first.disconnect()
        await self.wait_active(remote, second)
        first.send(report(3))
        await self.drain(remote)
        self.assertEqual(effects, ["entry_fixture", "entry_fixture"])
        automation = {"kind": "automation", "target": "automation.entry_fixture"}
        await remote.save(menu, 6, tv_entry_action=automation)
        await self.wait_active(remote, second)
        second.send(report(3))
        await self.drain(remote)
        self.assertEqual(effects[-1], {"skip_condition": False, "entity_id": "automation.entry_fixture"})
        await remote.save(menu, 7, tv_entry_action=None)
        await self.wait_active(remote, second)
        second.send(report(4))
        await self.drain(remote)
        self.assertEqual(len(effects), 3)
        self.assertEqual(first.writes, second.writes)
        self.assertEqual(first.writes, [(VERSION_QUERY, True)])

    async def test_watch_tv_entry_restores_saved_opt_in(self):
        action = {"kind": "script", "target": "script.entry_fixture"}
        remote, _, _, _ = await self.make_remote(STOCK_HANDHELD_MODE, [], saved={
            "menu": SAMPLE_MENU, "revision": 4, "tv_entry_action": action,
        })
        self.assertEqual(remote.configuration()["tv_entry_action"], action)

    async def test_office_packets_run_only_the_bound_actions_and_keep_the_tv_profile(self):
        old = validate_menu(V1_SAMPLE)
        old["screens"]["controls"]["buttons"]["soft_1"]["effect"] = {"kind": "switch", "target": SWITCH}
        # The previous handheld menu had preview-only room screens and three real TV bindings.
        handheld = {"home": "activities", "screens": {
            "activities": {"title": "Activities"},
            "tv": {"title": "Watch TV", "buttons": {
                "soft_1": {"label": "Input", "effect": {"kind": "switch", "target": SWITCH}},
                **{key: {"effect": {"kind": "script", "target": f"script.test_tv_{key}"}}
                   for key in ("volume_up", "volume_down", "mute")},
            }},
            "room": {"title": "Room controls"},
            "lights": {"title": "Lights"},
            "blinds": {"title": "Blinds"},
        }}
        saved = {"menu": SAMPLE_MENU, "revision": 4, "stock_menus": {
            STOCK_HANDHELD_MODE: handheld, STOCK_V1_MODE: old,
        }}
        client = StockGatt()
        remote, _, _, switch_states = await self.make_remote(
            STOCK_HANDHELD_MODE, [client], saved=saved, mqtt_enabled=True,
        )
        draft = deepcopy(remote.editor_menu)
        config = remote.configuration()
        self.assertFalse(config["mqtt_enabled"])
        self.assertEqual(config["stock_actions"]["blinds"]["soft_3"], ("stop_cover", "script"))
        for key, binding in handheld["screens"]["tv"]["buttons"].items():
            self.assertEqual(draft["screens"]["tv"]["buttons"][key], binding)

        cases = (
            (5, "lights", 1, "toggle", "switch", SWITCH, "toggle"),
            (6, "blinds", 1, "open", "open_cover", "cover.test_blind", "open_cover"),
            (6, "blinds", 2, "close", "close_cover", "cover.test_blind", "close_cover"),
            (6, "blinds", 3, "stop", "stop_cover", "cover.test_blind", "stop_cover"),
            (7, "curtains", 1, "open", "open_cover", "cover.test_curtains", "open_cover"),
            (7, "curtains", 2, "close", "close_cover", "cover.test_curtains", "close_cover"),
            (8, "fan", 1, "toggle", "fan", "fan.test_office", "toggle"),
        )
        calls, events = [], []

        @callback
        def record(call):
            calls.append((call.domain, call.service, call.data["entity_id"]))

        @callback
        def observe(event):
            events.append((event.data["screen_id"], event.data["button_id"], event.data["control_id"]))

        remote.hass.bus.async_listen("ununiversal_remote_input", observe)
        for screen, name, control, _, kind, entity, service in cases:
            domain = entity.split(".")[0]
            draft["screens"][name]["buttons"][f"soft_{control}"]["effect"] = {"kind": kind, "target": entity}
            self.assertIsNone(decode_stock_event(V1_PREFIX + pack("<BBI", screen, control, 1), STOCK_V1_MODE))
            if domain != "switch":
                remote.hass.states.async_set(entity, "on")
                remote.hass.services.async_register(domain, service, record)

        await self.wait_active(remote, client)
        await remote.save(draft, 4)
        await self.wait_active(remote, client)
        persisted = remote.store.async_save.call_args.args[0]
        self.assertEqual(persisted["stock_menus"][STOCK_V1_MODE], old)
        self.assertEqual(persisted["stock_menus"][STOCK_HANDHELD_MODE], draft)
        for screen, _, control, *_ in cases:
            press = V1_PREFIX + pack("<BBI", screen, control, 0x12345678)
            client.send(press)
            client.send(press)
        client.send(V1_PREFIX + pack("<BBI", 7, 3, 0x12345679))  # Unbound optional Stop.
        for screen, control in ((4, 1), (5, 2), (5, 3), (5, 4), (6, 4), (6, 11), (6, 12),
                                (7, 4), (8, 2), (8, 3), (8, 4), (9, 1)):
            client.send(V1_PREFIX + pack("<BBI", screen, control, 0x12345678))
        await self.drain(remote)
        await remote.hass.async_block_till_done()
        self.assertEqual(switch_states, ["on"])
        self.assertEqual(calls, [(entity.split(".")[0], service, entity)
                                 for *_, entity, service in cases if entity != SWITCH])
        self.assertEqual(events, [(name, semantic, control) for _, name, control, semantic, *_ in cases]
                         + [("curtains", "stop", 3)])
        self.assertEqual(client.writes, [(VERSION_QUERY, True)])

    def test_office_bindings_reject_wrong_action_domains_and_local_keys(self):
        for screen, key, kind, target in (
            ("lights", "soft_1", "fan", "fan.test"),
            ("blinds", "soft_1", "close_cover", "cover.test"),
            ("blinds", "soft_3", "stop_cover", "switch.test"),
            ("curtains", "soft_4", "open_cover", "cover.test"),
            ("tv", "volume_up", "open_cover", "cover.test"),
        ):
            with self.subTest(screen=screen, key=key, action=kind):
                draft = validate_menu(HANDHELD_SAMPLE)
                draft["screens"][screen]["buttons"].setdefault(key, {})["effect"] = {"kind": kind, "target": target}
                with self.assertRaises(ValueError):
                    stock_menu(draft, STOCK_HANDHELD_MODE)

    async def test_association_requires_both_address_and_manufacturer_prefix(self):
        remote, radio, _, _ = await self.make_remote(STOCK_MODE, [])
        for address, identifier in [
            (ADDRESS, bytes(6)), ("11:22:33:44:55:66", MANUFACTURER_ID),
        ]:
            radio.async_last_service_info.return_value = SimpleNamespace(
                address=address, manufacturer_data={MANUFACTURER: identifier},
            )
            radio.async_ble_device_from_address.reset_mock()
            self.assertIsNone(remote.ble._find_device())
            radio.async_ble_device_from_address.assert_not_called()

    def test_stock_menu_enforces_milestone_capabilities(self):
        marker = deepcopy(STOCK_SAMPLE)
        marker["screens"]["home"]["buttons"]["soft_1"]["label"] = "Rename"
        with self.assertRaisesRegex(ValueError, "fixed"):
            stock_menu(marker, STOCK_MODE)
        draft = deepcopy(V1_SAMPLE)
        draft["screens"]["home"]["buttons"]["soft_1"]["effect"] = {"kind": "switch", "target": SWITCH}
        with self.assertRaisesRegex(ValueError, "supported"):
            stock_menu(draft, STOCK_V1_MODE)
        draft["screens"]["controls"]["buttons"]["soft_1"] = {
            "label": "Earlier caption", "effect": {"kind": "switch", "target": SWITCH},
        }
        restored = stock_menu(draft, STOCK_V1_MODE, restore=True)
        self.assertNotIn("effect", restored["screens"]["home"]["buttons"]["soft_1"])
        self.assertEqual(restored["screens"]["controls"]["buttons"]["soft_1"], {
            "label": "Action", "effect": {"kind": "switch", "target": SWITCH},
        })
        self.assertIsNone(decode_stock_event(A_PRESSED, STOCK_V1_MODE))
        self.assertIsNone(decode_stock_event(V1_PREFIX + pack("<BBI", 2, 1, 0), STOCK_MODE))

    def test_restore_matches_dsp_captions_and_keeps_saved_bindings(self):
        previous = {
            "home": "home",
            "screens": {
                "home": {"title": "Home", "buttons": {
                    "soft_1": {"label": "Controls", "next": "controls"},
                    "up": {"effect": {"kind": "switch", "target": SWITCH}},
                }},
                "controls": {"title": "Controls", "buttons": {
                    "soft_1": {"label": "Lights", "effect": {"kind": "switch", "target": SWITCH}},
                    "soft_2": {"label": "B"},
                    "soft_3": {"label": "C"},
                    "soft_4": {"label": "Home", "next": "home"},
                }},
            },
        }
        restored = stock_menu(previous, STOCK_V1_MODE, restore=True)
        home = restored["screens"]["home"]["buttons"]
        controls = restored["screens"]["controls"]["buttons"]
        self.assertEqual([home[f"soft_{i}"]["label"] for i in range(1, 5)], ["Controls", "–", "–", "–"])
        self.assertEqual([controls[f"soft_{i}"]["label"] for i in range(1, 5)], ["Action", "–", "–", "Back"])
        self.assertEqual(home["soft_1"]["next"], "controls")
        self.assertEqual(controls["soft_4"]["next"], "home")
        self.assertEqual(controls["soft_1"]["effect"], previous["screens"]["controls"]["buttons"]["soft_1"]["effect"])
        self.assertEqual(home["up"], previous["screens"]["home"]["buttons"]["up"])
        self.assertEqual(stock_menu(restored, STOCK_V1_MODE), restored)
