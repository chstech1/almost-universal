"""Validate and project Home Assistant-owned handheld menu drafts."""

import asyncio
from functools import cached_property
from hashlib import sha256
import json
import re
from unicodedata import category

from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.components.fan import FanEntityFeature
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.core import CoreState
from homeassistant.helpers.storage import Store

from .menu import DOMAIN, ENTITY, ENTITY_ACTIONS, SOFT_KEYS, TEMPERATURE_ACTIONS, _numeric, temperature_change
from .stock import HANDHELD_KEYS

FORMAT = "almost-universal-menu"
MAX_PAGES = 16
MAX_DRAFT = 32768
MAX_LAYOUT = 8192
FIELD_IDS = ("1", "2", "3", "4")
DEVICE_KEYS = SOFT_KEYS + tuple(key for key in HANDHELD_KEYS if key not in SOFT_KEYS)
ACTION_FEATURES = {
    "open_cover": CoverEntityFeature.OPEN,
    "close_cover": CoverEntityFeature.CLOSE,
    "stop_cover": CoverEntityFeature.STOP,
    "volume_up": MediaPlayerEntityFeature.VOLUME_STEP | MediaPlayerEntityFeature.VOLUME_SET,
    "volume_down": MediaPlayerEntityFeature.VOLUME_STEP | MediaPlayerEntityFeature.VOLUME_SET,
    "mute_toggle": MediaPlayerEntityFeature.VOLUME_MUTE,
}
REMOTE_COMMANDS = ("up", "down", "left", "right", "select", "menu", "home", "play", "pause")
ACTION_SERVICES = {
    **ENTITY_ACTIONS,
    **{f"remote_{key}": ("remote", "send_command") for key in REMOTE_COMMANDS},
    "volume_up": ("media_player", "volume_up"), "volume_down": ("media_player", "volume_down"),
    "mute_toggle": ("media_player", "volume_mute"), "automation": ("automation", "trigger"),
}
FIELD_TYPES = {
    "light_power": ("light", "Light power"),
    "fan_power": ("fan", "Fan power"),
    "fan_speed": ("fan", "Fan speed"),
    "cover_position": ("cover", "Cover position"),
    "cover_state": ("cover", "Cover state"),
    "tv_power": ("media_player", "TV power"),
    "tv_volume": ("media_player", "TV volume"),
    "tv_mute": ("media_player", "TV mute"),
    "tv_input": ("media_player", "TV input"),
    "tv_app": ("media_player", "TV app"),
    "now_playing": ("media_player", "Now playing title"),
    "room_temperature": ("climate", "Measured room temperature"),
    "heat_target": ("climate", "Heat target"),
    "cool_target": ("climate", "Cool target"),
}
ACTION_LABELS = {
    "light": "Toggle light", "switch": "Toggle switch", "fan": "Toggle fan",
    "script": "Run script", "scene": "Activate scene",
    "open_cover": "Open cover", "close_cover": "Close cover", "stop_cover": "Stop cover",
    "heat_up": "Raise heat target", "heat_down": "Lower heat target",
    "cool_up": "Raise cool target", "cool_down": "Lower cool target",
    **{f"remote_{key}": f"Remote · {key.capitalize()}" for key in REMOTE_COMMANDS},
    "volume_up": "Raise volume", "volume_down": "Lower volume", "mute_toggle": "Toggle mute",
    "automation": "Trigger automation · check conditions",
}
ACTION_DOMAINS = {kind: domain for kind, (domain, _) in ACTION_SERVICES.items()} | dict.fromkeys(TEMPERATURE_ACTIONS, "climate")
ENTRY_ACTIONS = {"script": "script", "automation": "automation"}

DEFAULT_DRAFT = {
    "format": FORMAT, "version": 1, "entry": 1, "next_page_id": 5,
    "pages": {
        "1": {"title": "Home", "mode": "menu", "controls": {
            "soft_1": {"label": "TV", "link": 2},
            "soft_2": {"label": "Lights", "link": 3},
            "soft_3": {"label": "Temp", "link": 4},
        }},
        "2": {"title": "TV", "mode": "device", "controls": {"soft_4": {"label": "Back", "back": True}}},
        "3": {"title": "Lights", "mode": "device", "controls": {"soft_4": {"label": "Back", "back": True}}},
        "4": {"title": "Temp", "mode": "device", "controls": {"soft_4": {"label": "Back", "back": True}}},
    },
}


def _record(value, allowed, label):
    if not isinstance(value, dict) or value.keys() - set(allowed):
        raise ValueError(f"{label} has invalid fields.")
    return value


def _label(value, limit, label, *, required=True):
    if not isinstance(value, str) or len(value) > limit or any(category(char).startswith("C") for char in value):
        raise ValueError(f"{label} must be plain text up to {limit} UTF-8 bytes.")
    value = value.strip()
    if len(value.encode()) > limit or (required and not value):
        raise ValueError(f"{label} must be 1–{limit} UTF-8 bytes.")
    return value


def _binding(value, kinds, label, *, field=False):
    allowed = ("kind", "label", "target") if field else ("kind", "target")
    _record(value, allowed, label)
    kind, target = value.get("kind"), value.get("target")
    if not isinstance(kind, str) or kind not in kinds:
        raise ValueError(f"{label} has an unknown kind.")
    if (not isinstance(target, str) or len(target) > 128 or not ENTITY.fullmatch(target)
            or not target.startswith(f"{kinds[kind]}.")):
        raise ValueError(f"{label} must select a {kinds[kind]} entity.")
    return {**({"label": _label(value.get("label"), 16, label)} if field else {}),
            "kind": kind, "target": target}


def validate_entry_action(value, label):
    return _binding(value, ENTRY_ACTIONS, label)


def _control(value, key, pages, label):
    _record(value, ("label", "link", "back", "action"), label)
    text = _label(value.get("label", ""), 16, label, required=key in SOFT_KEYS)
    if len(value.keys() - {"label"}) > 1:
        raise ValueError(f"{label} can have one behavior.")
    result = {"label": text} if text else {}
    if "link" in value:
        link = value["link"]
        if type(link) is not int or str(link) not in pages:
            raise ValueError(f"{label} links to a missing page.")
        result["link"] = link
    if "back" in value:
        if value["back"] is not True:
            raise ValueError(f"{label} has an invalid Back binding.")
        result["back"] = True
    if "action" in value:
        result["action"] = _binding(value["action"], ACTION_DOMAINS, label)
    if not result:
        raise ValueError(f"{label} has no label or behavior.")
    return result


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def compose_layout(draft):
    """Compose an already validated draft into the device-only layout."""
    layout = {key: draft[key] for key in ("format", "version", "entry")}
    layout["pages"] = {
        id_: {
            "title": page["title"],
            "mode": page["mode"],
            "controls": {
                key: {**control, "action": True} if "action" in control else control
                for key, control in page["controls"].items()
            },
            "fields": {slot: {key: field[key] for key in ("label", "kind")}
                       for slot, field in page["fields"].items()},
        }
        for id_, page in draft["pages"].items()
    }
    data = _canonical(layout)
    if len(data) > MAX_LAYOUT:
        raise ValueError("The handheld layout exceeds 8 KiB.")
    return data


def validate_draft(draft):
    """Return a detached canonical draft after checking bounds and links."""
    _record(draft, ("format", "version", "entry", "next_page_id", "pages"), "Draft")
    if draft.get("format") != FORMAT or type(draft.get("version")) is not int or draft["version"] != 1:
        raise ValueError("This is not an Almost Universal menu draft v1.")
    pages = draft.get("pages")
    if not isinstance(pages, dict) or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError(f"Add between 1 and {MAX_PAGES} pages.")
    if any(not isinstance(id_, str) or not re.fullmatch(r"[1-9][0-9]{0,2}", id_) or int(id_) > 255 for id_ in pages):
        raise ValueError("Page IDs must be decimal strings from 1 to 255.")
    entry, next_page = draft.get("entry"), draft.get("next_page_id")
    if type(entry) is not int or str(entry) not in pages:
        raise ValueError("Choose an existing entry page.")
    if type(next_page) is not int or not max(map(int, pages)) < next_page <= 256:
        raise ValueError("Draft page counter is invalid.")
    normalized = {}
    fields = {kind: domain for kind, (domain, _) in FIELD_TYPES.items()}
    for id_, page in pages.items():
        name = f"Page {id_}"
        _record(page, ("title", "mode", "controls", "fields", "on_entry"), name)
        title = _label(page.get("title"), 24, f"{name} title")
        mode = page.get("mode")
        if mode not in ("menu", "device"):
            raise ValueError(f"{title} must be a menu or device page.")
        keys = DEVICE_KEYS if mode == "device" else SOFT_KEYS
        controls = _record(page.get("controls", {}), keys, f"{title} controls")
        readouts = _record(page.get("fields", {}), FIELD_IDS, f"{title} readouts")
        normalized[id_] = {
            "title": title, "mode": mode,
            "controls": {key: _control(controls[key], key, pages, f"{title} · {key}")
                         for key in keys if key in controls},
            "fields": {slot: _binding(readouts[slot], fields, f"{title} readout {slot}", field=True)
                       for slot in FIELD_IDS if slot in readouts},
        }
        if "on_entry" in page:
            normalized[id_]["on_entry"] = validate_entry_action(page["on_entry"], f"{title} · On entry")
    result = {"format": FORMAT, "version": 1, "entry": entry, "next_page_id": next_page, "pages": normalized}
    if len(_canonical(result)) > MAX_DRAFT:
        raise ValueError("The saveable draft exceeds 32 KiB.")
    compose_layout(result)
    return result


def draft_schema():
    return {
        "max_pages": MAX_PAGES, "max_draft": MAX_DRAFT, "field_ids": FIELD_IDS,
        "device_keys": DEVICE_KEYS, "soft_keys": SOFT_KEYS,
        "actions": {kind: {"domain": ACTION_DOMAINS[kind], "label": label}
                    for kind, label in ACTION_LABELS.items()},
        "entry_actions": tuple(ENTRY_ACTIONS),
        "fields": {kind: {"domain": domain, "label": label} for kind, (domain, label) in FIELD_TYPES.items()},
    }


def _unit(attrs, fallback):
    unit = attrs.get("temperature_unit", fallback)
    return unit if unit in ("°C", "°F") else None


def _supported(state, feature):
    flags = state.attributes.get("supported_features")
    return type(flags) is int and flags >= 0 and bool(flags & feature)


def _available(state):
    return state is not None and state.state not in ("unknown", "unavailable")


def _display_text(value):
    if not isinstance(value, str):
        return None
    # Imported metadata is rendered as text and never interpreted as a URL.
    return " ".join("".join(char for char in value if not category(char).startswith("C")).split())[:48] or None


def field_value(kind, state, fallback_unit):
    """Project only values explicitly requested by the draft."""
    if not _available(state):
        return None
    status, attrs = state.state, state.attributes
    if kind in ("light_power", "fan_power"):
        return {"on": "On", "off": "Off"}.get(status)
    if kind == "tv_power":
        if status in ("on", "playing", "paused", "idle", "buffering"):
            return "On"
        return {"off": "Off", "standby": "Standby"}.get(status)
    if kind == "cover_state":
        return status.capitalize() if status in ("open", "closed", "opening", "closing") else None
    if kind == "tv_mute":
        value = attrs.get("is_volume_muted")
        return ("Muted" if value else "Unmuted") if type(value) is bool else None
    if kind in ("tv_input", "tv_app", "now_playing"):
        if status in ("off", "standby") or (kind == "now_playing" and status not in ("playing", "paused")):
            return None
        attribute = {"tv_input": "source", "tv_app": "app_name", "now_playing": "media_title"}[kind]
        return _display_text(attrs.get(attribute))
    if kind in ("fan_speed", "cover_position", "tv_volume"):
        attr, upper = {"fan_speed": ("percentage", 100), "cover_position": ("current_position", 100),
                       "tv_volume": ("volume_level", 1)}[kind]
        value = attrs.get(attr)
        return f"{value * (100 / upper):g}%" if _numeric(value) and 0 <= value <= upper else None
    attr = "current_temperature"
    if kind in ("heat_target", "cool_target"):
        mode = kind.split("_")[0]
        if status not in (mode, "heat_cool"):
            return None
        attr = "temperature" if status == mode else ("target_temp_low" if mode == "heat" else "target_temp_high")
    unit, value = _unit(attrs, fallback_unit), attrs.get(attr)
    return f"{value:g}{unit}" if unit and _numeric(value) else None


def plan_action(action, state, fallback_unit):
    """Simulate an action against current state, with no service execution."""
    kind, target = action["kind"], action["target"]
    result = {"label": ACTION_LABELS[kind], "target": target}
    if not _available(state):
        return {**result, "status": "unavailable", "message": "Entity unavailable."}
    if kind in ("fan", "light", "switch") and state.state not in ("on", "off"):
        return {**result, "status": "unavailable", "message": "Current power state is unavailable."}
    feature = ACTION_FEATURES.get(kind)
    if kind == "fan":
        feature = FanEntityFeature.TURN_OFF if state.state == "on" else FanEntityFeature.TURN_ON
    if feature is not None and not _supported(state, feature):
        return {**result, "status": "unsupported", "message": "Entity does not support this action."}
    if kind not in TEMPERATURE_ACTIONS:
        domain, service = ACTION_SERVICES[kind]
        data = {}
        if kind.startswith("remote_"):
            data = {"command": [kind.removeprefix("remote_")]}
        elif kind == "automation":
            data = {"skip_condition": False}
        elif kind == "mute_toggle":
            muted = state.attributes.get("is_volume_muted")
            if type(muted) is not bool:
                return {**result, "status": "unavailable", "message": "Current mute state is unavailable."}
            data = {"is_volume_muted": not muted}
        return {**result, "status": "preview", "service": f"{domain}.{service}", "data": data,
                "message": "Simulated press. No action was sent."}
    attrs = state.attributes
    mode, _ = TEMPERATURE_ACTIONS[kind]
    ranged = state.state == "heat_cool"
    feature = ClimateEntityFeature.TARGET_TEMPERATURE_RANGE if ranged else ClimateEntityFeature.TARGET_TEMPERATURE
    unit = _unit(attrs, fallback_unit)
    if not _supported(state, feature) or not unit or state.state not in (mode, "heat_cool"):
        return {**result, "status": "unsupported", "message": "Thermostat does not support this target in its current mode."}
    key = "temperature" if not ranged else ("target_temp_low" if mode == "heat" else "target_temp_high")
    current, minimum, maximum = attrs.get(key), attrs.get("min_temp"), attrs.get("max_temp")
    try:
        if not all(map(_numeric, (current, minimum, maximum))) or not minimum <= current <= maximum:
            raise ValueError("Thermostat target or limits are unavailable.")
        proposed = temperature_change(state.state, attrs, kind)
    except ValueError as error:
        return {**result, "status": "unavailable", "message": str(error)}
    if not proposed:
        return {**result, "status": "limit", "message": "Target is at its limit."}
    return {**result, "status": "preview", "service": "climate.set_temperature",
            "current": current, "proposed": proposed[key], "unit": unit,
            "data": proposed, "message": f"Would set {mode} from {current:g}{unit} to {proposed[key]:g}{unit}."}


def preview_draft(draft, page_id, button, get_state, unit):
    """Resolve one draft preview press or read its current readouts."""
    if str(page_id) not in draft["pages"]:
        raise ValueError("Choose an existing page to preview.")
    page = draft["pages"][str(page_id)]
    control = page["controls"].get(button, {})
    action = control.get("action")
    link = control.get("link")
    on_entry = draft["pages"][str(link)].get("on_entry") if link is not None and link != page_id else None
    return {
        "page": page_id,
        "link": link,
        "back": control.get("back", button == "back" and not control),
        "action": plan_action(action, get_state(action["target"]), unit) if action else None,
        "entry_action": plan_action(on_entry, get_state(on_entry["target"]), unit) if on_entry else None,
        "fields": {slot: field_value(field["kind"], get_state(field["target"]), unit)
                   for slot, field in page["fields"].items()},
    }


class DraftStore:
    """Keep the draft revision independent of the active menu and BLE."""

    def __init__(self, hass, entry_id):
        self._hass = hass
        self._entry_id = entry_id
        self._lock = asyncio.Lock()
        self._closed = False

    @cached_property
    def _store(self):
        return Store(self._hass, 1, f"{DOMAIN}.{self._entry_id}.draft", private=True, atomic_writes=True)

    async def _load(self):
        saved = await self._store.async_load()
        if saved is None:
            return {"draft": validate_draft(DEFAULT_DRAFT), "revision": 0}
        revision = saved.get("revision") if isinstance(saved, dict) else None
        if type(revision) is not int or revision < 1:
            raise ValueError("The saved draft revision is invalid.")
        return {"draft": validate_draft(saved.get("draft")), "revision": revision}

    async def load(self):
        async with self._lock:
            return await self._load()

    async def save(self, candidate, revision):
        draft = validate_draft(candidate)
        if type(revision) is not int or revision < 0:
            raise ValueError("Draft revision is invalid.")
        async with self._lock:
            if self._closed or self._hass.state is CoreState.stopping:
                raise ValueError("Home Assistant is closing the editor. Reload to resume.")
            previous = await self._load()
            if previous["revision"] != revision:
                raise ValueError("The draft was saved in another tab. Reload the saved draft before editing.")
            updated = {"draft": draft, "revision": revision + 1}
            # Keep our lock until the atomic writer completes even if the client leaves.
            write = asyncio.create_task(self._write(updated))
            try:
                return await asyncio.shield(write)
            except asyncio.CancelledError:
                await write
                raise

    async def _write(self, updated):
        if self._closed or self._hass.state is CoreState.stopping:
            raise ValueError("Home Assistant is closing the editor. Reload to resume.")
        await self._store.async_save(updated)
        # HA Store logs and swallows low-level write errors.
        if await self._load() != updated:
            raise ValueError("Home Assistant could not save this draft. The prior revision is still saved.")
        return updated

    async def close(self):
        self._closed = True
        async with self._lock:
            pass


def validate_and_identify(candidate):
    draft = validate_draft(candidate)
    return {"draft": draft, "layout_sha256": sha256(compose_layout(draft)).hexdigest()}
