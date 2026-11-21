"""Stock-ARM v4.8 transport for fixed DSP profiles."""

import asyncio
from collections import deque
from struct import unpack_from

from .ble import ActiveMenu, BleRemote
from .menu import CONTROLS, validate_menu

URM1_MODE = "urm1"
STOCK_MODE = "stock_v48"
STOCK_V1_MODE = "stock_v48_v1"
STOCK_HANDHELD_MODE = "stock_v48_handheld"
STOCK_MODES = (STOCK_MODE, STOCK_V1_MODE, STOCK_HANDHELD_MODE)
STOCK_SERVICES = ("cba20d00-224d-11e6-9fb8-0002a5d5c51b", "0000fd3d-0000-1000-8000-00805f9b34fb")
STOCK_WRITE = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
STOCK_NOTIFY = "cba20003-224d-11e6-9fb8-0002a5d5c51b"
VERSION_QUERY = bytes.fromhex("57 00 00 00 02")
A_PRESSED = bytes.fromhex("7e 00 00 00 55 52 2d 41 2d 31")
MANUFACTURER = 2409
V1_PREFIX = b"\x7e\x00\x00\x00UR\x01\x01"
TV_ENTRY_PREFIX = b"\x7e\x00\x00\x00UR\x01\x02\x03\x00"
RESERVED_CONTROLS = (5, 6, 14)
STOCK_HARD_KEYS = tuple(
    key for index, key in enumerate(CONTROLS, 1)
    if 7 <= index <= 19 and index not in RESERVED_CONTROLS
)
# Watch TV reports remain unchanged. D, power, KATA, and wheel are local or stock.
HANDHELD_CONTROLS = (1, 2, 3, *range(7, 14), *range(15, 20))
HANDHELD_KEYS = tuple(CONTROLS[index - 1] for index in HANDHELD_CONTROLS)
COVER_KEYS = {
    "soft_1": ("open", ("open_cover", "script")),
    "soft_2": ("close", ("close_cover", "script")),
    "soft_3": ("stop", ("stop_cover", "script")),
}
OFFICE_SCREENS = {
    0x05: ("lights", "Lights", {"soft_1": ("toggle", ("light", "switch", "script"))}),
    0x06: ("blinds", "Blinds", COVER_KEYS),
    0x07: ("curtains", "Curtains", COVER_KEYS),
    0x08: ("fan", "Fan", {"soft_1": ("toggle", ("fan", "script"))}),
}
OFFICE_KEYS = {screen: keys for screen, _, keys in OFFICE_SCREENS.values()}
STOCK_SAMPLE = {
    "home": "home",
    "screens": {
        "home": {"title": "Home", "buttons": {"soft_1": {"label": "Controls", "next": "controls"}}},
        "controls": {"title": "Controls", "buttons": {"soft_4": {"label": "Home", "next": "home"}}},
    },
}
V1_SAMPLE = {
    "home": "home",
    "screens": {
        "home": {"title": "Home", "buttons": {
            "soft_1": {"label": "Controls", "next": "controls"},
            "soft_2": {"label": "–"},
            "soft_3": {"label": "–"},
            "soft_4": {"label": "–"},
        }},
        "controls": {"title": "Controls", "buttons": {
            "soft_1": {"label": "Action"},
            "soft_2": {"label": "–"},
            "soft_3": {"label": "–"},
            "soft_4": {"label": "Back", "next": "home"},
        }},
    },
}
HANDHELD_SAMPLE = {
    "home": "activities",
    "screens": {
        "activities": {"title": "Activities"},
        "tv": {"title": "Watch TV", "buttons": {
            key: {"label": caption} for key, caption in zip(CONTROLS, ("Input", "Guide", "Menu", "Back"))
        }},
        "room": {"title": "Room controls"},
        "scenes": {"title": "Scenes"},
        "climate": {"title": "Climate"},
        "covers": {"title": "Covers"},
        **{
            screen: {"title": title, "buttons": {
                **{key: {"label": action.title()} for key, (action, _) in keys.items()},
                "soft_4": {"label": "Back"},
            }}
            for screen, title, keys in OFFICE_SCREENS.values()
        },
    },
}
STOCK_SAMPLES = {STOCK_MODE: STOCK_SAMPLE, STOCK_V1_MODE: V1_SAMPLE, STOCK_HANDHELD_MODE: HANDHELD_SAMPLE}


def stock_bindable(mode, screen):
    """Controls whose press effects can be edited for the selected DSP candidate."""
    if mode == STOCK_MODE:
        return ("soft_1",) if screen == "home" else ()
    if mode == STOCK_HANDHELD_MODE:
        return HANDHELD_KEYS if screen == "tv" else tuple(OFFICE_KEYS.get(screen, ()))
    return (("soft_1",) if screen == "controls" else ()) + STOCK_HARD_KEYS


def stock_button_name(mode, screen, key):
    """Expose Office action names while retaining the menu's physical key slots."""
    if mode == STOCK_HANDHELD_MODE and screen in OFFICE_KEYS:
        return OFFICE_KEYS[screen][key][0]
    return key


def stock_action_kinds(mode, screen, key):
    if mode != STOCK_HANDHELD_MODE:
        return ("switch",)
    if screen == "tv":
        return "switch", "script"
    return OFFICE_KEYS.get(screen, {}).get(key, (None, ()))[1]


def stock_menu(draft, mode, *, restore=False):
    """Validate HA bindings against this candidate's fixed firmware layout."""
    menu = validate_menu(draft)
    sample = validate_menu(STOCK_SAMPLES[mode])
    for screen_id, screen in menu["screens"].items():
        available = stock_bindable(mode, screen_id) if screen_id in sample["screens"] else ()
        fix = sample["screens"].get(screen_id, {}).get("buttons", {})
        for key, binding in screen["buttons"].items():
            if effect := binding.get("effect"):
                kinds = stock_action_kinds(mode, screen_id, key)
                if key not in available or effect["kind"] not in kinds or binding.get("effect_on", "press") != "press":
                    if restore:
                        continue
                    raise ValueError("Choose a supported action on a key reported by this firmware.")
                fix.setdefault(key, {})["effect"] = effect
                binding.pop("effect_on", None)
    if restore:
        return sample
    if menu != sample:
        raise ValueError("The Stock ARM DSP has a fixed layout for this profile.")
    return menu


def decode_stock_event(data, mode):
    """Decode a stock transport notification without accepting other stock traffic."""
    if mode == STOCK_MODE:
        return ("home", "soft_1", "press", 0) if data == A_PRESSED else None
    if len(data) != 14 or not data.startswith(V1_PREFIX):
        return None
    screen, control, _ = unpack_from("<BBI", data, 8)
    if mode == STOCK_HANDHELD_MODE:
        if screen == 3 and control in HANDHELD_CONTROLS:
            return "tv", CONTROLS[control - 1], "press", 0
        if screen in OFFICE_SCREENS and 1 <= control <= 3:
            source, _, keys = OFFICE_SCREENS[screen]
            key = CONTROLS[control - 1]
            if key in keys:
                return source, key, "press", 0
        return None
    if mode != STOCK_V1_MODE:
        return None
    if screen not in (1, 2) or not 1 <= control <= 19 or control in RESERVED_CONTROLS:
        return None
    return ("home" if screen == 1 else "controls", CONTROLS[control - 1], "press", 0)


def decode_stock_page_entry(data, mode):
    """Return the stock OK timestamp from the fixed Watch TV entry report."""
    if mode == STOCK_HANDHELD_MODE and len(data) == 14 and data.startswith(TV_ENTRY_PREFIX):
        return unpack_from("<I", data, 10)[0]
    return None


class StockRemote(BleRemote):
    """Connect to the selected stock device and accept its configured DSP reports."""

    services = STOCK_SERVICES

    def __init__(self, hass, entry, address, on_event, live_text, manufacturer_id, mode):
        super().__init__(hass, entry, address, on_event, live_text)
        self.manufacturer_id = manufacturer_id
        self.mode = mode

    def _matcher(self):
        return {"address": self.address, "connectable": True}

    def _find_device(self):
        info = self.bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        if (info is None or info.address.casefold() != self.address.casefold()
                or info.manufacturer_data.get(MANUFACTURER, b"")[:6] != self.manufacturer_id):
            return None
        return super()._find_device()

    async def _session(self, client):
        service = next((found for uuid in STOCK_SERVICES
                        if (found := client.services.get_service(uuid)) is not None), None)
        writer = service.get_characteristic(STOCK_WRITE) if service else None
        receiver = service.get_characteristic(STOCK_NOTIFY) if service else None
        if writer is None or receiver is None:
            raise ValueError("Stock SwitchBot GATT characteristics are missing")
        version = None
        recent = deque(maxlen=128)
        recent_entries = deque(maxlen=128)
        query_sent = False

        def notification(characteristic, value):
            nonlocal version
            if self.client is not client or not client.is_connected:
                return
            data = bytes(value)
            if (query_sent and version is None and len(data) == 20
                    and data[:4] == b"\x01\x00\x00\x00"):
                version = data[5]
                self.wake.set()
            elif self.active is not None:
                if decode_stock_page_entry(data, self.mode) is not None:
                    cache = recent_entries
                elif decode_stock_event(data, self.mode) is not None:
                    cache = recent if self.mode != STOCK_MODE else None
                else:
                    return
                if cache is not None:
                    if data in cache:
                        return
                    cache.append(data)
                self._notification(client, data)

        async with asyncio.timeout(10):
            await client.start_notify(receiver, notification)
            if self.client is not client or not client.is_connected:
                return
            query_sent = True
            await client.write_gatt_char(writer, VERSION_QUERY, response="write" in writer.properties)
            while version is None and self.client is client and client.is_connected:
                self.wake.clear()
                await self.wake.wait()
        if self.client is not client or not client.is_connected:
            return
        if version != 48:
            raise ValueError("Stock ARM version check did not report v4.8")

        while self.client is client and client.is_connected:
            self.wake.clear()
            if self.active is None and self.package is not None:
                self.active = ActiveMenu(self.package)
            await self.wake.wait()
