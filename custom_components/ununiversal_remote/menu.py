"""Validate menus and resolve actions for both preview and live presses."""

from decimal import Decimal
from math import isfinite, isclose
import re

DOMAIN = "ununiversal_remote"
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,31}")
ENTITY = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
SOFT_KEYS = ("soft_1", "soft_2", "soft_3", "soft_4")
# BLE IDs are one-based indices in the firmware input profile. The wheel is 20.
CONTROLS = SOFT_KEYS + (
    "on", "off", "left", "right", "up", "down", "ok", "back", "home",
    "kata", "mute", "volume_up", "volume_down", "channel_up", "channel_down", "wheel",
)
BUTTON_IDS = CONTROLS
EVENT_KINDS = ("press", "release", "hold", "repeat", "turn", "item_activation")
ACTION_TRIGGERS = EVENT_KINDS + ("press_repeat",)
ENTITY_ACTIONS = {
    "light": ("light", "toggle"),
    "switch": ("switch", "toggle"),
    "script": ("script", "turn_on"),
    "scene": ("scene", "turn_on"),
    "fan": ("fan", "toggle"),
    "open_cover": ("cover", "open_cover"),
    "close_cover": ("cover", "close_cover"),
    "stop_cover": ("cover", "stop_cover"),
}
TEMPERATURE_ACTIONS = {
    "heat_up": ("heat", 1),
    "heat_down": ("heat", -1),
    "cool_up": ("cool", 1),
    "cool_down": ("cool", -1),
}

# Soft keys A–C open activities. Soft key D returns from each activity.
SAMPLE_MENU = {
    "home": "home",
    "screens": {
        "home": {
            "title": "Home",
            "buttons": {
                "soft_1": {"label": "TV", "next": "tv"},
                "soft_2": {"label": "Lights", "next": "lights"},
                "soft_3": {"label": "Temp", "next": "temp"},
            },
        },
        "tv": {"title": "TV", "buttons": {"soft_4": {"label": "Back", "next": "home"}}},
        "lights": {"title": "Lights", "buttons": {"soft_4": {"label": "Back", "next": "home"}}},
        "temp": {"title": "Temp", "buttons": {"soft_4": {"label": "Back", "next": "home"}}},
    },
}


def _text(value, field, *, required=False, limit=1024):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{field} must be text up to {limit} characters.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} is required.")
    return value


def _entity(value, domain, field):
    if not isinstance(value, str) or not ENTITY.fullmatch(value) or not value.startswith(f"{domain}."):
        raise ValueError(f"{field} must select a {domain} entity.")
    return value


def _effect(effect, field):
    if not isinstance(effect, dict):
        raise ValueError(f"{field} has an invalid action.")
    kind = _text(effect.get("kind"), f"{field} action")
    if kind in ENTITY_ACTIONS:
        domain, _ = ENTITY_ACTIONS[kind]
        return {"kind": kind, "target": _entity(effect.get("target"), domain, field)}
    if kind in TEMPERATURE_ACTIONS:
        return {"kind": kind}
    if kind == "ir":
        target = _text(effect.get("target"), f"{field} IR command", required=True, limit=32)
        if IDENTIFIER.fullmatch(target):
            return {"kind": kind, "target": target}
        raise ValueError(f"{field} IR command must be an ID such as tv_power_off.")
    raise ValueError(f"{field} has an unknown action.")


def validate_menu(menu):
    """Return a canonical, detached menu or raise a field-specific error."""
    if not isinstance(menu, dict) or not isinstance(screens := menu.get("screens"), dict) or not screens:
        raise ValueError("Add at least one screen.")
    home = menu.get("home")
    if not isinstance(home, str) or home not in screens:
        raise ValueError("Choose an existing home screen.")
    normalized = {}
    for screen_id, screen in screens.items():
        if not isinstance(screen_id, str) or not IDENTIFIER.fullmatch(screen_id) or not isinstance(screen, dict):
            raise ValueError("Each screen needs a unique lowercase ID and a screen definition.")
        title = _text(screen.get("title"), f"Screen {screen_id} title", required=True, limit=64)
        text = _text(screen.get("text", ""), f"{title} screen text")
        climate = screen.get("climate", "")
        if climate != "":
            _entity(climate, "climate", f"{title} thermostat")
        buttons = screen.get("buttons", {})
        if not isinstance(buttons, dict):
            raise ValueError(f"{title} has invalid button bindings.")
        bindings = {}
        for button, binding in buttons.items():
            field = f"{title} · {button}"
            if button not in BUTTON_IDS or not isinstance(binding, dict):
                raise ValueError(f"{field} is outside the four shortcut slots or supported hard keys.")
            clean = {}
            if button in SOFT_KEYS:
                clean["label"] = _text(binding.get("label", ""), f"{field} label", limit=32)
            if destination := binding.get("next", ""):
                if not isinstance(destination, str) or destination not in screens:
                    raise ValueError(f"{field} links to a missing screen.")
                clean["next"] = destination
            if binding.get("effect") is not None:
                clean["effect"] = _effect(binding["effect"], field)
                if (trigger := binding.get("effect_on")) is not None:
                    if trigger not in ACTION_TRIGGERS:
                        raise ValueError(f"{field} has an unknown action trigger.")
                    clean["effect_on"] = trigger
            if button in SOFT_KEYS and not clean["label"]:
                if "next" in clean or "effect" in clean:
                    raise ValueError(f"{field} needs a label for its binding.")
                continue
            if clean:
                bindings[button] = clean
        normalized[screen_id] = {"title": title, "text": text, "climate": climate, "buttons": bindings}
    return {"home": home, "screens": normalized}


def resolve_press(menu, screen_id, button_id, event="press"):
    """Resolve a key against the displayed screen's saved bindings."""
    screen = menu["screens"][screen_id]
    binding = screen["buttons"].get(button_id, {})
    effect = binding.get("effect")
    if effect:
        temperature = effect["kind"] in TEMPERATURE_ACTIONS
        default = "turn" if button_id == "wheel" else "press_repeat" if temperature else "press"
        trigger = binding.get("effect_on", default)
        if event != trigger and not (trigger == "press_repeat" and event in ("press", "repeat")):
            effect = None
        elif temperature:
            effect = {**effect, "target": screen["climate"]}
    return binding.get("next", screen_id), effect


def screen_payload(menu, screen_id, status=""):
    """Render the title, body, and occupied shortcut labels."""
    screen = menu["screens"][screen_id]
    return {
        "screen_id": screen_id,
        "title": screen["title"],
        "text": "\n".join(filter(None, (screen["text"], status))),
        "buttons": {
            key: screen["buttons"][key]["label"]
            for key in SOFT_KEYS
            if key in screen["buttons"]
        },
    }


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def temperature_status(mode, attributes, unit):
    """Show the thermostat values reported by Home Assistant."""
    if mode in (None, "unknown", "unavailable"):
        return "Thermostat unavailable"
    fields = [("Room", "current_temperature")]
    if mode == "heat_cool":
        fields += [("Heat", "target_temp_low"), ("Cool", "target_temp_high")]
    elif mode in ("heat", "cool"):
        fields.append((mode.capitalize(), "temperature"))
    return "\n".join(
        f"{label} {attributes[key]:g}{unit}" for label, key in fields if _numeric(attributes.get(key))
    )


def temperature_change(mode, attrs, kind):
    """Return the service data for one step, or no data at a limit."""
    target_mode, direction = TEMPERATURE_ACTIONS[kind]
    ranged = mode == "heat_cool"
    if not ranged and mode != target_mode:
        raise ValueError(f"Thermostat must be in {target_mode} or heat/cool mode.")
    minimum, maximum = attrs.get("min_temp"), attrs.get("max_temp")
    if not all(map(_numeric, (minimum, maximum))) or minimum > maximum:
        raise ValueError("Thermostat temperature limits are unavailable.")
    step = attrs.get("target_temp_step")
    if not _numeric(step) or step <= 0:
        step = 1
    key = "temperature"
    if ranged:
        key = "target_temp_low" if target_mode == "heat" else "target_temp_high"
        other_key = "target_temp_high" if target_mode == "heat" else "target_temp_low"
        other = attrs.get(other_key)
        if not _numeric(other) or not minimum <= other <= maximum:
            raise ValueError("Thermostat must report both temperature targets.")
        if target_mode == "heat":
            maximum = min(maximum, other - step)
        else:
            minimum = max(minimum, other + step)
    value = attrs.get(key)
    if not _numeric(value):
        raise ValueError("Thermostat temperature target is unavailable.")
    proposed = float(Decimal(str(value)) + direction * Decimal(str(step)))
    proposed = max(minimum, min(maximum, proposed))
    if minimum > maximum or (proposed - value) * direction <= 0 or isclose(proposed, value):
        return {}
    if ranged:
        return {key: proposed, other_key: other}
    return {key: proposed}
