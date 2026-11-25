"""Home Assistant setup and the Remote Menus sidebar API."""

from base64 import b64encode
from pathlib import Path

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import callback
import voluptuous as vol

from .menu import BUTTON_IDS, DOMAIN, EVENT_KINDS, resolve_press
from .menu_draft import DEVICE_KEYS, draft_schema, preview_draft, validate_and_identify, validate_draft
from .protocol import compile_menu
from .remote import Remote
from .stock import STOCK_MODES

PANEL = "remote-menus"
MODULE_URL = "/ununiversal_remote/panel.js"
EDITOR_VERSION = "0.1.6-au"


async def async_setup(hass, config):
    """Register the editor's static module and API once per HA process."""
    directory = Path(__file__).parent
    await hass.http.async_register_static_paths([
        StaticPathConfig(MODULE_URL, str(directory / "panel.js"), False),
        StaticPathConfig("/ununiversal_remote/handheld-draft.js", str(directory / "handheld-draft.js"), False),
        StaticPathConfig("/ununiversal_remote/menu-builder.js", str(directory / "menu-builder.js"), False),
    ])
    for command in (get_menu, save_menu, preview, export_menu, draft_get, draft_save, draft_validate, draft_preview):
        websocket_api.async_register_command(hass, command)
    return True


async def async_setup_entry(hass, entry):
    """Load the saved menu and add the sidebar item."""
    remote = Remote(hass, entry)
    await remote.start()
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL,
        webcomponent_name="almost-universal-panel",
        sidebar_title="Remote Menus",
        sidebar_icon="mdi:remote-tv",
        module_url=f"{MODULE_URL}?v={EDITOR_VERSION}",
        require_admin=True,
    )
    entry.runtime_data = remote
    hass.data[DOMAIN] = remote
    return True


async def async_unload_entry(hass, entry):
    """Remove the editor and detach the runtime from its transports."""
    hass.data.pop(DOMAIN, None)
    await entry.runtime_data.stop()
    frontend.async_remove_panel(hass, PANEL)
    return True


@callback
def _remote(hass, connection, message):
    remote = hass.data.get(DOMAIN)
    if remote is None:
        connection.send_error(message["id"], "not_loaded", "Set up Almost Universal first.")
    return remote


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get"})
@callback
def get_menu(hass, connection, message):
    """Return the current saved configuration to the editor."""
    if remote := _remote(hass, connection, message):
        connection.send_result(message["id"], remote.configuration())


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/export"})
@callback
def export_menu(hass, connection, message):
    """Export the exact saved menu binary and revision used for BLE sync."""
    if (remote := _remote(hass, connection, message)) is None:
        return
    if remote.ble_mode in STOCK_MODES:
        connection.send_error(message["id"], "unsupported", "Stock ARM does not use URM1 exports.")
        return
    try:
        package = compile_menu(remote.menu)
    except ValueError as error:
        connection.send_error(message["id"], "invalid_menu", str(error))
        return
    connection.send_result(message["id"], {
        "revision": package.revision.hex(),
        "package": b64encode(package.data).decode("ascii"),
    })


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/save",
    vol.Required("menu"): dict,
    vol.Required("revision"): int,
    vol.Optional("tv_entry_action"): vol.Any(None, dict),
})
@websocket_api.async_response
async def save_menu(hass, connection, message):
    """Apply a validated menu if the editor's revision is still current."""
    if (remote := _remote(hass, connection, message)) is None:
        return
    try:
        options = {"tv_entry_action": message["tv_entry_action"]} if "tv_entry_action" in message else {}
        await remote.save(message["menu"], message["revision"], **options)
    except ValueError as error:
        connection.send_error(message["id"], "invalid_menu", str(error))
        return
    connection.send_result(message["id"], remote.configuration())


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/preview",
    vol.Required("menu"): dict,
    vol.Required("screen_id"): str,
    vol.Optional("button_id"): vol.In(BUTTON_IDS),
    vol.Optional("event", default="press"): vol.In(EVENT_KINDS),
})
@callback
def preview(hass, connection, message):
    """Render a draft screen or simulate a press with effects returned as data."""
    if (remote := _remote(hass, connection, message)) is None:
        return
    try:
        menu = remote.validate_editor_menu(message["menu"])
        screen_id = message["screen_id"]
        if screen_id not in menu["screens"]:
            raise ValueError("Choose a screen to preview.")
        effect = None
        if button := message.get("button_id"):
            screen_id, effect = resolve_press(menu, screen_id, button, message["event"])
        screen = remote.render(menu, screen_id)
    except ValueError as error:
        connection.send_error(message["id"], "invalid_menu", str(error))
        return
    connection.send_result(message["id"], {"screen": screen, "effect": effect})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/draft_get"})
@websocket_api.async_response
async def draft_get(hass, connection, message):
    if (remote := _remote(hass, connection, message)) is None:
        return
    try:
        saved = await remote.drafts.load()
    except (KeyError, ValueError) as error:
        connection.send_error(message["id"], "invalid_draft", str(error))
        return
    connection.send_result(message["id"], {**saved, "schema": draft_schema(), "sync": "unavailable"})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/draft_save",
    vol.Required("draft"): dict,
    vol.Required("revision"): int,
})
@websocket_api.async_response
async def draft_save(hass, connection, message):
    if (remote := _remote(hass, connection, message)) is None:
        return
    try:
        saved = await remote.drafts.save(message["draft"], message["revision"])
    except ValueError as error:
        connection.send_error(message["id"], "invalid_draft", str(error))
        return
    connection.send_result(message["id"], saved)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/draft_validate",
    vol.Required("draft"): dict,
})
@callback
def draft_validate(hass, connection, message):
    if _remote(hass, connection, message) is None:
        return
    try:
        result = validate_and_identify(message["draft"])
    except ValueError as error:
        connection.send_error(message["id"], "invalid_draft", str(error))
        return
    connection.send_result(message["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/draft_preview",
    vol.Required("draft"): dict,
    vol.Required("page_id"): int,
    vol.Optional("button_id"): vol.In(DEVICE_KEYS),
})
@callback
def draft_preview(hass, connection, message):
    if _remote(hass, connection, message) is None:
        return
    try:
        draft = validate_draft(message["draft"])
        result = preview_draft(draft, message["page_id"], message.get("button_id"),
                               hass.states.get, hass.config.units.temperature_unit)
    except ValueError as error:
        connection.send_error(message["id"], "invalid_draft", str(error))
        return
    connection.send_result(message["id"], result)
