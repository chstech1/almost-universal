"""Wire format shared by the handheld firmware and Bluetooth central."""

from dataclasses import dataclass
from hashlib import sha256
import json
from struct import Struct, pack

from .menu import CONTROLS, EVENT_KINDS, SOFT_KEYS, validate_menu

SERVICE = "13f70001-7e61-4c69-9a28-9d39a8d01001"
CONTROL = "13f70002-7e61-4c69-9a28-9d39a8d01001"
EVENT = "13f70003-7e61-4c69-9a28-9d39a8d01001"
STATUS = "13f70004-7e61-4c69-9a28-9d39a8d01001"
MAX_PACKAGE = 8192
MAX_SCREENS = 64
WRITE_SIZE = 20  # Works at ATT MTU 23 through a proxy or local adapter.
INPUT_PACKET = Struct("<IHBb")
STATUS_PACKET = Struct("<BB8sI")


@dataclass(frozen=True)
class MenuPackage:
    revision: bytes
    data: bytes
    screen_ids: tuple[str, ...]


def _utf8(text, limit, field):
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} must be valid UTF-8.") from error
    if len(data) > limit:
        raise ValueError(f"{field} exceeds the handheld's {limit}-byte limit.")
    return bytes([len(data)]) + data


def compile_menu(menu):
    """Serialize a validated menu and hash it including Home Assistant bindings."""
    menu = validate_menu(menu)
    screens = menu["screens"]
    if len(screens) > MAX_SCREENS:
        raise ValueError(f"The handheld supports up to {MAX_SCREENS} screens.")
    screen_ids = tuple(sorted(screens))
    indices = {screen_id: i for i, screen_id in enumerate(screen_ids, 1)}
    data = bytearray(b"URM1" + pack("<HH", len(screens), indices[menu["home"]]))
    for screen_id in screen_ids:
        screen = screens[screen_id]
        title = screen["title"]
        bindings = screen["buttons"]
        data.extend(_utf8(title, 64, f"{screen_id} title"))
        data.extend(_utf8(screen["text"], 255, f"{title} screen text"))
        for key in SOFT_KEYS:
            data.extend(_utf8(bindings.get(key, {}).get("label", ""), 32, f"{title} {key} label"))
        for key in CONTROLS:
            destination = bindings.get(key, {}).get("next")
            data.extend(pack("<H", indices[destination] if destination else 0))
        if len(data) > MAX_PACKAGE:
            raise ValueError(f"The handheld menu exceeds {MAX_PACKAGE} bytes.")
    canonical = json.dumps(menu, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return MenuPackage(sha256(canonical.encode("utf-8")).digest()[:8], bytes(data), screen_ids)


def decode_event(payload, package):
    """Decode a notification against the active menu's screen and key tables."""
    if len(payload) != INPUT_PACKET.size:
        return None
    source, control, kind, wheel_steps = INPUT_PACKET.unpack(payload)
    if not (1 <= source <= len(package.screen_ids)
            and 1 <= control <= len(CONTROLS) and 1 <= kind <= len(EVENT_KINDS)):
        return None
    button, event = CONTROLS[control - 1], EVENT_KINDS[kind - 1]
    if (button != "wheel" or event != "turn") and wheel_steps:
        return None
    if event == "turn" and (button != "wheel" or wheel_steps == 0):
        return None
    return package.screen_ids[source - 1], button, event, wheel_steps


def status_writes(screen_index, text):
    """Yield offset-based live status writes with whole UTF-8 characters."""
    offset = 0
    segment = bytearray()
    limit = WRITE_SIZE - 6
    for char in text:
        encoded = char.encode("utf-8")
        if offset + len(segment) + len(encoded) > 255:
            break
        if len(segment) + len(encoded) > limit:
            yield pack("<BIB", 5, screen_index, offset) + segment
            offset += len(segment)
            segment.clear()
        segment.extend(encoded)
    yield pack("<BIB", 5, screen_index, offset) + segment
