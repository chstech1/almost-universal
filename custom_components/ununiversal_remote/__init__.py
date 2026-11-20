"""Home Assistant setup and the Remote Menus sidebar API."""

from base64 import b64encode
from pathlib import Path

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import callback
import voluptuous as vol

from .menu import BUTTON_IDS, DOMAIN, EVENT_KINDS, resolve_press, validate_menu
from .protocol import compile_menu
from .remote import Remote

PANEL = "remote-menus"
MODULE_URL = "/ununiversal_remote/panel.js"


async def async_setup(hass, config):
    """Register the editor's static module and API once per HA process."""
    panel = Path(__file__).with_name("panel.js")
    await hass.http.async_register_static_paths([StaticPathConfig(MODULE_URL, str(panel), False)])
    for command in (get_menu, save_menu, preview, export_menu):
        websocket_api.async_register_command(hass, command)
    return True


async def async_setup_entry(hass, entry):
    """Load the saved menu and add the sidebar item."""
    remote = Remote(hass, entry)
    await remote.start()
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL,
        webcomponent_name="ununiversal-remote-panel",
        sidebar_title="Remote Menus",
        sidebar_icon="mdi:remote-tv",
        module_url=MODULE_URL,
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
        connection.send_error(message["id"], "not_loaded", "Set up The Ununiversal Remote first.")
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
})
@websocket_api.async_response
async def save_menu(hass, connection, message):
    """Apply a validated menu if the editor's revision is still current."""
    if (remote := _remote(hass, connection, message)) is None:
        return
    try:
        await remote.save(message["menu"], message["revision"])
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
        menu = validate_menu(message["menu"])
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
