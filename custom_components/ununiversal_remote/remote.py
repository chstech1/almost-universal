"""Persist menus, route remote input, and execute configured HA actions."""

import asyncio
import json
import logging
from math import isclose
from secrets import token_urlsafe

from homeassistant.components import mqtt
from homeassistant.components.mqtt.util import async_wait_for_mqtt_client
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_setup_component

from .menu import (
    BUTTON_IDS,
    CONTROLS,
    DOMAIN,
    ENTITY_ACTIONS,
    SAMPLE_MENU,
    resolve_press,
    screen_payload,
    temperature_change,
    temperature_status,
    validate_menu,
)
from .menu_draft import DraftStore, validate_entry_action
from .page_entry import PageEntrySession
from .protocol import compile_menu, decode_event
from .stock import (
    STOCK_HANDHELD_MODE, STOCK_MODES, STOCK_SAMPLES, URM1_MODE,
    StockRemote, decode_stock_event, decode_stock_page_entry,
    stock_action_kinds, stock_bindable, stock_button_name, stock_menu,
)

LOGGER = logging.getLogger(__name__)
INPUT_EVENT = f"{DOMAIN}_input"
PAGE_ENTRY_EVENT = f"{DOMAIN}_page_entry"
_UNCHANGED = object()


class Remote:
    """The saved menu and live state of one paired logical remote."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.remote_id = entry.data["remote_id"]
        self.prefix = f"{DOMAIN}/{self.remote_id}"
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.drafts = DraftStore(hass, entry.entry_id)
        self._page_entries = None
        self.tv_entry_action = None
        self.lock = asyncio.Lock()
        self.effects = asyncio.Queue(maxsize=128)
        self.revision = 0
        self.unsubscribers = []
        self.untrack_climate = None
        self.mqtt_connected = False
        self.last_screen = None
        self.ble = None
        self.ble_address = entry.options.get("ble_address", entry.data.get("ble_address", ""))
        self.ble_mode = entry.options.get("ble_mode", URM1_MODE)
        self.mqtt_enabled = self.ble_mode != STOCK_HANDHELD_MODE and entry.options.get("mqtt_enabled", True)

    async def start(self):
        """Restore screens and subscribe when HA has MQTT configured."""
        saved = await self.store.async_load()
        menu = SAMPLE_MENU
        if target := self.entry.data.get("switch_entity"):
            menu = {"home": "home", "screens": {"home": {"title": "Home", "buttons": {
                "soft_1": {"label": "Toggle", "effect": {"kind": "switch", "target": target}},
            }}}}
        self.menu = validate_menu(saved["menu"] if saved else menu)
        stock_menus = saved.get("stock_menus", {}) if saved else {}
        self.stock_menus = {
            mode: stock_menu(stock_menus.get(mode, sample), mode, restore=True)
            for mode, sample in STOCK_SAMPLES.items()
        }
        if saved:
            self.revision = saved["revision"]
            if (action := saved.get("tv_entry_action")) is not None:
                self.tv_entry_action = validate_entry_action(action, "Watch TV · On entry")
        self._show(self.menu["home"])
        self._watch_climate()
        if self.mqtt_enabled and await async_wait_for_mqtt_client(self.hass):
            self.mqtt_connected = mqtt.is_connected(self.hass)
            self.unsubscribers.append(
                mqtt.async_subscribe_connection_status(self.hass, self._connection_changed)
            )
            self.unsubscribers.append(
                await mqtt.async_subscribe(self.hass, f"{self.prefix}/+", self._message)
            )
        self.worker = self.entry.async_create_background_task(
            self.hass, self._run_effects(), f"{DOMAIN} button actions"
        )
        if self.ble_address:
            await self._start_bluetooth(self.ble_address)

    async def _start_bluetooth(self, address):
        if not await async_setup_component(self.hass, "bluetooth", {}):
            LOGGER.error("Home Assistant Bluetooth could not start for remote %s", address)
            return
        from homeassistant.components import bluetooth

        from .ble import BleRemote

        if self.ble_mode in STOCK_MODES:
            identity = bytes.fromhex(self.entry.options["stock_manufacturer_id"])
            self.ble = StockRemote(
                self.hass, self.entry, address, self._ble_event, self._live_text, identity, self.ble_mode
            )
        else:
            self.ble = BleRemote(self.hass, self.entry, address, self._ble_event, self._live_text)
        try:
            self.ble.set_package(compile_menu(self.editor_menu))
        except ValueError as error:
            LOGGER.warning("Edit and save the menu before using Bluetooth: %s", error)
        self.ble.start(bluetooth)

    async def stop(self):
        """Unsubscribe and stop accepting actions before unloading."""
        if self._page_entries is not None:
            self._page_entries.close()
        self.mqtt_connected = False
        for unsubscribe in self.unsubscribers:
            unsubscribe()
        if self.untrack_climate:
            self.untrack_climate()
        if self.ble:
            await self.ble.stop()
        self.worker.cancel()
        await asyncio.gather(self.worker, return_exceptions=True)
        await self.drafts.close()

    @callback
    def _connection_changed(self, connected):
        self.mqtt_connected = connected
        if connected:
            self.entry.async_create_task(self.hass, self._refresh_screen(force=True))

    def configuration(self):
        """Return the menu, concurrency revision, and transport status."""
        stock_keys = {
            name: stock_bindable(self.ble_mode, name) for name in self.editor_menu["screens"]
        } if self.ble_mode in STOCK_MODES else None
        config = {
            "menu": self.editor_menu,
            "revision": self.revision,
            "remote_id": self.remote_id,
            "mqtt_enabled": self.mqtt_enabled,
            "mqtt_connected": self.mqtt_connected,
            "ble_address": self.ble_address,
            "ble_mode": self.ble_mode,
            "ble_active": self.ble is not None and self.ble.is_active(self.ble.active),
            "stock_keys": stock_keys,
            "stock_actions": {
                screen: {key: stock_action_kinds(self.ble_mode, screen, key) for key in keys}
                for screen, keys in stock_keys.items()
            } if self.ble_mode == STOCK_HANDHELD_MODE else None,
        }
        if self.ble_mode == STOCK_HANDHELD_MODE:
            config["tv_entry_action"] = self.tv_entry_action
        return config

    @property
    def editor_menu(self):
        return self.stock_menus[self.ble_mode] if self.ble_mode in STOCK_MODES else self.menu

    def make_page_entry_session(self, activation, draft, generation, layout_sha256):
        """Bind an acknowledged configuration when a matching transport exists."""
        if (self.ble_mode != STOCK_HANDHELD_MODE or self.ble is None
                or activation is None or not self.ble.is_active(activation)):
            return None
        session = PageEntrySession(activation, draft, generation, layout_sha256,
                                   self.ble.is_active, self._run_effect)
        if self._page_entries is not None:
            if (self._page_entries.activation is activation
                    and generation <= self._page_entries.generation):
                raise ValueError("Page entry requires a newer acknowledged generation.")
            self._page_entries.close()
        self._page_entries = session
        return session

    def validate_editor_menu(self, draft):
        if self.ble_mode in STOCK_MODES:
            return stock_menu(draft, self.ble_mode)
        return validate_menu(draft)

    async def save(self, draft, revision, *, tv_entry_action=_UNCHANGED):
        """Write a complete new menu before making it active."""
        stock = self.ble_mode in STOCK_MODES
        menu = self.validate_editor_menu(draft)
        if tv_entry_action is not _UNCHANGED:
            if self.ble_mode != STOCK_HANDHELD_MODE:
                raise ValueError("Watch TV entry actions require the fixed handheld profile.")
            if tv_entry_action is not None:
                tv_entry_action = validate_entry_action(tv_entry_action, "Watch TV · On entry")
        package = compile_menu(menu) if self.ble else None
        async with self.lock:
            if revision != self.revision:
                raise ValueError("The menu was saved in another tab. Reopen the editor to load it.")
            action = self.tv_entry_action if tv_entry_action is _UNCHANGED else tv_entry_action
            if self.ble:
                previous = self.ble.package
                self.ble.set_package(None)
            stock_menus = {**self.stock_menus, self.ble_mode: menu} if stock else self.stock_menus
            try:
                saved = {
                    "menu": self.menu if stock else menu,
                    "stock_menus": stock_menus,
                    "revision": revision + 1,
                }
                if action is not None:
                    saved["tv_entry_action"] = action
                await self.store.async_save(saved)
            except BaseException:
                if self.ble:
                    self.ble.set_package(previous)
                raise
            if stock:
                self.stock_menus = stock_menus
            else:
                self.menu = menu
            self.tv_entry_action = action
            self.revision += 1
            if not stock:
                self._show(self.screen_id if self.screen_id in menu["screens"] else menu["home"])
                self._watch_climate()
            if self.ble:
                self.ble.set_package(package)
            if not stock:
                await self._publish_screen()

    def _show(self, screen_id):
        self.screen_id = screen_id
        self.screen_token = token_urlsafe(8)

    def _watch_climate(self):
        if self.untrack_climate:
            self.untrack_climate()
        entities = {screen["climate"] for screen in self.menu["screens"].values()} - {""}
        self.untrack_climate = (
            async_track_state_change_event(self.hass, entities, self._climate_changed)
            if entities else None
        )

    @callback
    def _climate_changed(self, event):
        if self.ble:
            self.ble.refresh_text()
        if self.menu["screens"][self.screen_id]["climate"] == event.data["entity_id"]:
            self.entry.async_create_task(self.hass, self._refresh_screen())

    async def _refresh_screen(self, *, force=False):
        async with self.lock:
            await self._publish_screen(force=force)

    def render(self, menu, screen_id):
        """Build screen data using confirmed thermostat state."""
        climate = menu["screens"][screen_id]["climate"]
        return screen_payload(menu, screen_id, self._temperature_status(climate) if climate else "")

    def _live_text(self, screen_id):
        climate = self.menu["screens"][screen_id]["climate"]
        return self._temperature_status(climate) if climate else None

    def _temperature_status(self, climate):
        state = self.hass.states.get(climate)
        return temperature_status(
            state.state if state else None,
            state.attributes if state else {},
            self.hass.config.units.temperature_unit,
        )

    async def _publish(self, topic, payload):
        if not self.mqtt_connected:
            return False
        try:
            await mqtt.async_publish(
                self.hass, f"{self.prefix}/{topic}",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                qos=0, retain=False,
            )
        except HomeAssistantError as error:
            LOGGER.warning("Could not publish the remote's %s message: %s", topic, error)
            return False
        return True

    async def _publish_screen(self, *, force=False):
        payload = self.render(self.menu, self.screen_id)
        payload["screen_token"] = self.screen_token
        if (force or payload != self.last_screen) and await self._publish("screen", payload):
            self.last_screen = payload

    async def _message(self, message):
        if message.retain or message.topic not in (f"{self.prefix}/ready", f"{self.prefix}/press"):
            return
        async with self.lock:
            if message.topic.endswith("/ready"):
                await self._publish_screen(force=True)
                return
            if not message.payload or len(message.payload) > 512:
                return
            try:
                press = json.loads(message.payload)
            except (ValueError, UnicodeError, RecursionError):
                return
            if not isinstance(press, dict) or (button := press.get("button_id")) not in BUTTON_IDS:
                return
            if press.get("screen_id") != self.screen_id or press.get("screen_token") != self.screen_token:
                await self._publish_screen(force=True)
                return
            screen_id, effect = resolve_press(self.menu, self.screen_id, button)
            if effect and self.effects.full():
                LOGGER.warning("Remote action queue full. Ignoring press %s on %s", button, self.screen_id)
                return
            if screen_id != self.screen_id:
                self._show(screen_id)
                await self._publish_screen()
            if effect:
                self.effects.put_nowait((effect, None))

    async def _ble_event(self, activation, payload):
        async with self.lock:
            if not self.ble.is_active(activation):
                return
            timestamp = decode_stock_page_entry(payload, self.ble_mode)
            if timestamp is not None:
                self.hass.bus.async_fire(PAGE_ENTRY_EVENT, {
                    "remote_id": self.remote_id,
                    "transport": self.ble_mode,
                    "screen_id": "tv",
                    "kind": "page_entry",
                    "timestamp": timestamp,
                })
                if self.tv_entry_action is not None:
                    if self.effects.full():
                        LOGGER.warning("Remote action queue full. Ignoring Watch TV entry")
                    else:
                        self.effects.put_nowait((self.tv_entry_action, activation))
                return
            stock = self.ble_mode in STOCK_MODES
            event = decode_stock_event(payload, self.ble_mode) if stock else decode_event(payload, activation.package)
            if event is None:
                return
            screen_id, button, kind, steps = event
            self.hass.bus.async_fire(INPUT_EVENT, {
                "remote_id": self.remote_id,
                "transport": self.ble_mode,
                "screen_id": screen_id,
                "button_id": stock_button_name(self.ble_mode, screen_id, button),
                "control_id": CONTROLS.index(button) + 1,
                "kind": kind,
                "wheel_steps": steps,
            })
            destination, effect = resolve_press(self.editor_menu, screen_id, button, kind)
            if not stock and kind == "press" and destination != screen_id:
                self.ble.refresh_text(navigation=True)
            if effect is None:
                return
            if effect["kind"] == "ir":
                LOGGER.warning("Use a Home Assistant script for IR actions from the Bluetooth handheld")
            elif self.effects.full():
                LOGGER.warning("Remote action queue full. Ignoring press %s on %s", button, screen_id)
            else:
                self.effects.put_nowait((effect, activation))

    async def _run_effects(self):
        while True:
            effect, activation = await self.effects.get()
            try:
                if activation is None or self.ble.is_active(activation):
                    await self._run_effect(effect)
            except (HomeAssistantError, ValueError, TimeoutError) as error:
                LOGGER.warning("Remote action %s failed: %s", effect["kind"], str(error) or "timed out")
            finally:
                self.effects.task_done()

    async def _run_effect(self, effect):
        kind, target = effect["kind"], effect["target"]
        if kind == "ir":
            if not await self._publish("ir", {"command_id": target}):
                raise ValueError("MQTT is disconnected.")
            return
        if not target:
            raise ValueError("Select a thermostat in the screen editor.")
        state = self.hass.states.get(target)
        if state is None or state.state in ("unavailable", "unknown"):
            raise ValueError(f"{target} is unavailable.")
        if kind == "automation":
            await self.hass.services.async_call("automation", "trigger", {"skip_condition": False},
                                                target={"entity_id": target}, blocking=True)
            return
        if kind in ENTITY_ACTIONS:
            domain, service = ENTITY_ACTIONS[kind]
            if kind == "script":
                await self.hass.services.async_call(domain, target.split(".", 1)[1], blocking=True)
            else:
                await self.hass.services.async_call(
                    domain, service, target={"entity_id": target}, blocking=True
                )
            return
        if data := temperature_change(state.state, state.attributes, kind):
            await self._set_temperature(target, data)

    async def _set_temperature(self, entity, data):
        """Wait for confirmation before the next queued adjustment reads state."""
        confirmed = self.hass.loop.create_future()

        def matches(state):
            return state is not None and all(
                isinstance(current := state.attributes.get(key), (float, int))
                and isclose(current, requested, abs_tol=0.01)
                for key, requested in data.items()
            )

        @callback
        def updated(event):
            if not confirmed.done() and matches(event.data["new_state"]):
                confirmed.set_result(None)

        unsubscribe = async_track_state_change_event(self.hass, [entity], updated)
        try:
            async with asyncio.timeout(5):
                await self.hass.services.async_call(
                    "climate", "set_temperature", dict(data),
                    target={"entity_id": entity}, blocking=True,
                )
                if not matches(self.hass.states.get(entity)):
                    await confirmed
        finally:
            unsubscribe()
