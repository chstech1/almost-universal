"""Exercise draft storage, validation, and preview with isolated Home Assistant state."""

import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.storage import Store

import custom_components.ununiversal_remote as integration
from custom_components.ununiversal_remote.menu import DOMAIN, SAMPLE_MENU
from custom_components.ununiversal_remote.menu_draft import (
    DEFAULT_DRAFT, MAX_LAYOUT, DraftStore, compose_layout, plan_action, preview_draft, validate_draft,
)
from custom_components.ununiversal_remote.stock import HANDHELD_SAMPLE, STOCK_HANDHELD_MODE


def action(kind, target, label=None):
    return {**({"label": label} if label else {}), "action": {"kind": kind, "target": target}}


def field(kind, target, label):
    return {"kind": kind, "target": target, "label": label}


class DraftValidation(unittest.TestCase):
    def test_canonical_projection_contains_no_binding_and_keeps_layout_digest(self):
        raw = deepcopy(DEFAULT_DRAFT)
        raw["pages"]["2"]["controls"]["soft_1"] = action("script", "script.tv_power", "Power")
        raw["pages"]["2"]["fields"] = {"1": field("tv_power", "media_player.tv", "TV")}
        draft = validate_draft(raw)
        layout = compose_layout(draft)
        projected = json.loads(layout)
        self.assertEqual(projected["pages"]["2"]["controls"]["soft_1"], {"label": "Power", "action": True})
        self.assertEqual(projected["pages"]["2"]["fields"]["1"], {"label": "TV", "kind": "tv_power"})
        self.assertNotIn("next_page_id", projected)
        self.assertNotIn(b"script.", layout)
        self.assertNotIn(b"media_player.", layout)
        raw["pages"]["2"]["controls"]["soft_1"]["action"] = {"kind": "automation", "target": "automation.other"}
        raw["pages"]["2"]["fields"]["1"]["target"] = "media_player.alt_tv"
        raw["pages"] = dict(reversed(list(raw["pages"].items())))
        self.assertEqual(compose_layout(validate_draft(raw)), layout)
        raw["pages"]["2"]["title"] = "Theater"
        self.assertNotEqual(compose_layout(validate_draft(raw)), layout)

    def test_bad_versions_stale_links_slots_and_utf8_are_rejected(self):
        for updates in ({"version": True}, {"version": 2}, {"entry": 9}, {"entry": True}, {"next_page_id": 4},
                        {"extra": "unknown"}, {"pages": {}}, {"pages": {"01": {}}}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_draft({**DEFAULT_DRAFT, **updates})
        for bad in (
            {"title": "é" * 13}, {"title": "bad\nname"}, {"title": "bad\u202Ename"},
            {"controls": {"soft_1": {"label": "Missing", "link": 99}}},
            {"controls": {"soft_1": {"label": "Multiple", "link": 2, "back": True}}},
            {"controls": {"left": {"link": 2}}}, {"controls": {"soft_5": {"label": "Invalid"}}},
            {"controls": {"soft_1": action("automation", "script.wrong", "Power")}},
            {"fields": {"5": field("room_temperature", "climate.home", "Room")}},
            {"fields": {"1": field("cover_position", "fan.office", "Blind")}},
        ):
            raw = deepcopy(DEFAULT_DRAFT)
            raw["pages"]["1"].update(bad)
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_draft(raw)
        for key in ("on", "off", "wheel"):
            raw = deepcopy(DEFAULT_DRAFT)
            raw["pages"]["2"]["controls"][key] = action("script", "script.power")
            with self.assertRaises(ValueError):
                validate_draft(raw)

    def test_projection_size_cap(self):
        page = validate_draft(DEFAULT_DRAFT)["pages"]["2"]
        page["controls"] = {key: action("script", "script.power", "a" * 16)
                            for key in integration.DEVICE_KEYS}
        page["fields"] = {str(i): field("room_temperature", "climate.home", "a" * 16) for i in range(1, 5)}
        raw = {**DEFAULT_DRAFT, "entry": 1, "next_page_id": 17,
               "pages": {str(i): page for i in range(1, 17)}}
        with self.assertRaisesRegex(ValueError, "8 KiB"):
            validate_draft(raw)

    def test_model_keeps_old_activation_on_partial_or_corrupt_transfer(self):
        # A host-side model of the receiver boundary. No production sync handler exists.
        first = validate_draft(DEFAULT_DRAFT)
        updated = deepcopy(first)
        updated["pages"]["2"]["controls"]["soft_1"] = action("script", "script.first_power", "Power")
        updated = validate_draft(updated)
        old_layout, payload = compose_layout(first), compose_layout(updated)

        class Receiver:
            active = (1, old_layout)

            def commit(self, generation, chunks, expected):
                data = b"".join(chunks)
                if (generation <= self.active[0] or len(data) > MAX_LAYOUT
                        or sha256(data).hexdigest() != expected or data != payload):
                    return False
                self.active = generation, data
                return True

        receiver = Receiver()
        digest = sha256(payload).hexdigest()
        self.assertFalse(receiver.commit(2, [payload[:-1]], digest))
        self.assertFalse(receiver.commit(2, [payload[:-2], b"xx"], digest))
        self.assertEqual(receiver.active, (1, old_layout))
        self.assertTrue(receiver.commit(2, [payload[:80], payload[80:]], digest))
        self.assertEqual(receiver.active, (2, payload))
        self.assertFalse(receiver.commit(1, [payload], digest))

        # An action-only edit uses the same bytes and a different activation. One
        # press ID may be processed once in that activation, with no queued replay.
        updated["pages"]["2"]["controls"]["soft_1"]["action"]["target"] = "script.other_power"
        self.assertEqual(compose_layout(updated), payload)
        self.assertTrue(receiver.commit(3, [payload], digest))
        seen, calls = set(), []
        for generation, press_id in ((2, 10), (3, 10), (3, 10), (2, 11)):
            if generation == receiver.active[0] and press_id not in seen:
                seen.add(press_id)
                calls.append(updated["pages"]["2"]["controls"]["soft_1"]["action"]["target"])
        self.assertEqual(calls, ["script.other_power"])


class DraftIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.hass = HomeAssistant(directory.name)
        self.entry = ConfigEntry(
            title="Draft fixture", domain=DOMAIN, version=1, minor_version=1, source="user",
            entry_id="draft_fixture", unique_id=None, discovery_keys=MappingProxyType({}), subentries_data=(),
            data={"remote_id": "draft_fixture"},
            options={"ble_mode": STOCK_HANDHELD_MODE, "mqtt_enabled": False},
        )
        tv = deepcopy(HANDHELD_SAMPLE)
        tv["screens"]["tv"]["buttons"]["volume_up"] = {"effect": {"kind": "script", "target": "script.live_tv"}}
        self.base = {"menu": SAMPLE_MENU, "stock_menus": {STOCK_HANDHELD_MODE: tv}, "revision": 7}
        await Store(self.hass, 1, f"{DOMAIN}.{self.entry.entry_id}").async_save(self.base)
        for obj, name in ((integration.panel_custom, "async_register_panel"),
                          (integration.frontend, "async_remove_panel")):
            mock = patch.object(obj, name, return_value=None)
            mock.start()
            self.addCleanup(mock.stop)
        await integration.async_setup_entry(self.hass, self.entry)
        self.addAsyncCleanup(integration.async_unload_entry, self.hass, self.entry)
        self.remote = self.entry.runtime_data

    async def ws(self, command, user=True, **payload):
        result = asyncio.get_running_loop().create_future()
        conn = SimpleNamespace(user=SimpleNamespace(is_admin=user),
                               send_result=lambda _, data: result.set_result(data),
                               send_error=lambda _, code, reason: result.set_result({"error": code, "message": reason}))
        getattr(integration, command)(self.hass, conn, {"id": 1, **payload})
        return await asyncio.wait_for(result, 1)

    async def test_create_link_preview_validate_save_reopen_and_keep_014_bindings(self):
        first = await self.ws("draft_get")
        self.assertEqual((first["revision"], first["sync"]), (0, "unavailable"))
        draft = first["draft"]
        draft["pages"]["5"] = {"title": "Office fan", "mode": "device", "controls": {
            "soft_1": action("fan", "fan.office", "Toggle"),
            "soft_4": {"label": "Back", "back": True},
        }, "fields": {"1": field("fan_speed", "fan.office", "Speed")}}
        draft["next_page_id"] = 6
        draft["pages"]["1"]["controls"]["soft_4"] = {"label": "Fan", "link": 5}
        self.hass.states.async_set("fan.office", "on", {"percentage": 35, "supported_features": 57})
        with patch.object(type(self.hass.services), "async_call", new_callable=AsyncMock) as call:
            home = await self.ws("draft_preview", draft=draft, page_id=1, button_id="soft_4")
            fan = await self.ws("draft_preview", draft=draft, page_id=5, button_id="soft_1")
            back = await self.ws("draft_preview", draft=draft, page_id=5, button_id="soft_4")
            self.assertEqual((home["link"], fan["fields"]["1"], back["back"]), (5, "35%", True))
            self.assertEqual(fan["action"]["service"], "fan.toggle")
            call.assert_not_awaited()
        imported = await self.ws("draft_validate", draft=json.loads(json.dumps(draft)))
        saved = await self.ws("draft_save", draft=imported["draft"], revision=0)
        reopened = await DraftStore(self.hass, self.entry.entry_id).load()
        self.assertEqual(reopened, saved)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(self.remote.configuration()["revision"], 7)
        self.assertEqual(self.remote.editor_menu["screens"]["tv"]["buttons"]["volume_up"]["effect"]["target"],
                         "script.live_tv")
        self.assertEqual(await self.remote.store.async_load(), self.base)
        with self.assertRaises(Unauthorized):
            await self.ws("draft_get", user=False)

    async def test_bad_or_interrupted_save_leaves_prior_file_and_detects_stale(self):
        store = self.remote.drafts
        original = validate_draft(DEFAULT_DRAFT)
        await store.save(original, 0)
        path = Path(store._store.path)
        stored = path.read_bytes()
        altered = deepcopy(original)
        altered["pages"]["1"]["title"] = "Weekend"
        invalid = {**altered, "entry": 99}
        result = await self.ws("draft_save", draft=invalid, revision=1)
        self.assertEqual(result["error"], "invalid_draft")
        # Simulate Storage swallowing a low-level write failure.
        with patch.object(store._store, "async_save", return_value=None):
            with self.assertRaisesRegex(ValueError, "could not save"):
                await store.save(altered, 1)
        self.assertEqual(path.read_bytes(), stored)
        self.assertEqual((await store.load())["revision"], 1)
        results = await asyncio.gather(store.save(altered, 1), store.save(altered, 1), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, ValueError) for item in results), 1)
        self.assertEqual((await store.load())["revision"], 2)

    async def test_cancelled_client_retains_lock_until_durable_save(self):
        store = self.remote.drafts
        started, proceed = asyncio.Event(), asyncio.Event()
        real_save = store._store.async_save

        async def delayed(data):
            started.set()
            await proceed.wait()
            await real_save(data)

        with patch.object(store._store, "async_save", side_effect=delayed):
            update = asyncio.create_task(store.save(DEFAULT_DRAFT, 0))
            await started.wait()
            update.cancel()
            second = asyncio.create_task(store.save(DEFAULT_DRAFT, 0))
            await asyncio.sleep(0)
            self.assertFalse(second.done())
            proceed.set()
            with self.assertRaises(asyncio.CancelledError):
                await update
            with self.assertRaisesRegex(ValueError, "another tab"):
                await second
        self.assertEqual((await store.load())["revision"], 1)

    async def test_read_only_entities_and_per_button_tv_routing(self):
        raw = deepcopy(DEFAULT_DRAFT)
        raw["pages"]["2"]["controls"].update({
            "left": action("remote_left", "remote.apple_tv"),
            "ok": action("remote_select", "remote.apple_tv"),
            "volume_up": action("volume_up", "media_player.avr"),
            "mute": action("mute_toggle", "media_player.avr"),
            "soft_1": action("script", "script.room_power", "Power"),
            "soft_2": action("automation", "automation.watch_tv", "Watch"),
        })
        raw["pages"]["2"]["fields"] = {
            "1": field("tv_volume", "media_player.avr", "Volume"),
            "2": field("tv_input", "media_player.vizio", "Input"),
            "3": field("now_playing", "media_player.apple_tv", "Playing"),
            "4": field("tv_app", "media_player.vizio", "App"),
        }
        raw["pages"]["3"]["fields"] = {
            "1": field("light_power", "light.office", "Lights"),
            "2": field("cover_position", "cover.office", "Blinds"),
        }
        raw["pages"]["3"]["controls"]["soft_1"] = action("stop_cover", "cover.office", "Stop")
        states = self.hass.states
        states.async_set("remote.apple_tv", "on")
        states.async_set("script.room_power", "off")
        states.async_set("automation.watch_tv", "on")
        states.async_set("media_player.avr", "on", {
            "volume_level": .34, "is_volume_muted": True, "supported_features": 1024 | 8,
        })
        states.async_set("media_player.vizio", "on", {"source": "HDMI 1", "app_name": "WatchFree"})
        states.async_set("media_player.apple_tv", "playing", {
            "media_title": "Example film", "entity_picture": "/api/media_player_proxy/private",
        })
        states.async_set("light.office", "off")
        states.async_set("cover.office", "open", {"current_position": 45, "supported_features": 7})
        draft = validate_draft(raw)
        with patch.object(type(self.hass.services), "async_call", new_callable=AsyncMock) as call:
            observed = await self.ws("draft_preview", draft=draft, page_id=2)
            self.assertEqual(observed["fields"], {"1": "34%", "2": "HDMI 1", "3": "Example film", "4": "WatchFree"})
            self.assertNotIn("entity_picture", json.dumps(observed))
            self.assertNotIn("/api/", json.dumps(observed))
            operations = {
                "left": ("remote.send_command", "remote.apple_tv", {"command": ["left"]}),
                "ok": ("remote.send_command", "remote.apple_tv", {"command": ["select"]}),
                "volume_up": ("media_player.volume_up", "media_player.avr", {}),
                "mute": ("media_player.volume_mute", "media_player.avr", {"is_volume_muted": False}),
                "soft_1": ("script.turn_on", "script.room_power", {}),
                "soft_2": ("automation.trigger", "automation.watch_tv", {"skip_condition": False}),
            }
            for button, expected in operations.items():
                effect = (await self.ws("draft_preview", draft=draft, page_id=2, button_id=button))["action"]
                self.assertEqual((effect["service"], effect["target"], effect["data"]), expected)
            room = await self.ws("draft_preview", draft=draft, page_id=3, button_id="soft_1")
            self.assertEqual(room["fields"], {"1": "Off", "2": "45%"})
            self.assertEqual(room["action"]["status"], "unsupported")
            call.assert_not_awaited()
        states.async_set("media_player.avr", "unavailable")
        states.async_set("cover.office", "closed", {"current_position": 101})
        self.assertIsNone(preview_draft(draft, 3, None, states.get, "°F")["fields"]["2"])
        self.assertEqual(preview_draft(draft, 2, "volume_up", states.get, "°F")["action"]["status"], "unavailable")
        states.async_set("media_player.avr", "on", {"volume_level": .34, "supported_features": 4})
        self.assertEqual(preview_draft(draft, 2, "volume_up", states.get, "°F")["action"]["status"], "preview")
        states.async_set("fan.office", "on", {"supported_features": 32})
        fan = plan_action({"kind": "fan", "target": "fan.office"}, states.get("fan.office"), "°F")
        self.assertEqual(fan["status"], "unsupported")

    async def test_climate_preview_is_read_only_and_existing_effect_waits_for_confirmation(self):
        raw = deepcopy(DEFAULT_DRAFT)
        page = raw["pages"]["4"]
        for key, kind, label in (("soft_1", "heat_up", "Warmer"), ("soft_2", "heat_down", "Cooler"),
                                 ("soft_3", "cool_down", "Lower cool")):
            page["controls"][key] = action(kind, "climate.home", label)
        page["fields"] = {"1": field("room_temperature", "climate.home", "Room"),
                          "2": field("heat_target", "climate.home", "Heat"),
                          "3": field("cool_target", "climate.home", "Cool")}
        draft = validate_draft(raw)
        attrs = {"temperature_unit": "°F", "min_temp": 50, "max_temp": 90, "target_temp_step": .5,
                 "current_temperature": 66, "target_temp_low": 68, "target_temp_high": 70,
                 "supported_features": 2}
        self.hass.states.async_set("climate.home", "heat_cool", attrs)
        with patch.object(type(self.hass.services), "async_call", new_callable=AsyncMock) as call:
            result = await self.ws("draft_preview", draft=draft, page_id=4, button_id="soft_1")
            self.assertEqual(result["fields"], {"1": "66°F", "2": "68°F", "3": "70°F"})
            self.assertEqual(result["action"]["proposed"], 68.5)
            self.assertEqual(result["action"]["data"], {"target_temp_low": 68.5, "target_temp_high": 70})
            lowered = (await self.ws("draft_preview", draft=draft, page_id=4, button_id="soft_2"))["action"]
            self.assertEqual(lowered["proposed"], 67.5)
            self.assertEqual(self.hass.states.get("climate.home").attributes["target_temp_low"], 68)
            call.assert_not_awaited()
        for updated, status in (({**attrs, "supported_features": 0}, "unsupported"),
                                ({**attrs, "temperature_unit": "K"}, "unsupported"),
                                ({**attrs, "target_temp_low": 69.5}, "limit"),
                                ({**attrs, "target_temp_low": 99}, "unavailable")):
            self.hass.states.async_set("climate.home", "heat_cool", updated)
            planned = plan_action(page["controls"]["soft_1"]["action"], self.hass.states.get("climate.home"), "°F")
            self.assertEqual(planned["status"], status)

        # The production legacy executor shares temperature_change and waits on
        # confirmed HA state. Exercise it only against this fake local service.
        self.hass.states.async_set("climate.home", "heat_cool", attrs)
        called = asyncio.Event()

        async def fake_service(*args, **kwargs):
            called.set()

        with patch.object(type(self.hass.services), "async_call", new=AsyncMock(side_effect=fake_service)) as call:
            effect = asyncio.create_task(self.remote._run_effect({"kind": "heat_up", "target": "climate.home"}))
            await asyncio.wait_for(called.wait(), 1)
            call.assert_awaited_once_with("climate", "set_temperature", result["action"]["data"],
                                          target={"entity_id": "climate.home"}, blocking=True)
            self.hass.states.async_set("climate.home", "heat_cool", {**attrs, "current_temperature": 66.5})
            await asyncio.sleep(0)
            self.assertFalse(effect.done())
            self.hass.states.async_set("climate.home", "heat_cool", {**attrs, **result["action"]["data"]})
            await asyncio.wait_for(effect, 1)
