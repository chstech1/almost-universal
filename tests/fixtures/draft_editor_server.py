"""Serve the real draft panel against an isolated HA core over a loopback test bridge."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

import custom_components.ununiversal_remote as integration
from custom_components.ununiversal_remote.menu import DOMAIN
from custom_components.ununiversal_remote.remote import Remote
from custom_components.ununiversal_remote.stock import STOCK_HANDHELD_MODE

INDEX = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Remote Menus offline fixture</title>
<script type="module" src="/ununiversal_remote/panel.js"></script>
<style>body { margin: 0; background: #f2f3f0; }</style>
<almost-universal-panel></almost-universal-panel>
<script type="module">
  await customElements.whenDefined("almost-universal-panel");
  const states = await (await fetch("/fixture/states")).json();
  document.querySelector("almost-universal-panel").hass = {
    states,
    async callWS(message) {
      const response = await fetch("/fixture/ws", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(message),
      });
      const result = await response.json();
      if (result.error) throw new Error(result.message);
      return result;
    },
  };
</script>
"""


async def main():
    with TemporaryDirectory() as root:
        hass = HomeAssistant(root)
        entry = ConfigEntry(
            title="Draft fixture", domain=DOMAIN, version=1, minor_version=1, source="user",
            entry_id="draft_fixture", unique_id=None, discovery_keys=MappingProxyType({}), subentries_data=(),
            data={"remote_id": "draft_fixture"}, options={"ble_mode": STOCK_HANDHELD_MODE, "mqtt_enabled": False},
        )
        remote = Remote(hass, entry)
        await remote.start()
        hass.data[DOMAIN] = remote
        hass.states.async_set("fan.office", "on", {
            "friendly_name": "Office Fan", "percentage": 35, "supported_features": 57,
        })
        hass.states.async_set("climate.office", "heat_cool", {
            "friendly_name": "Office Thermostat", "current_temperature": 66, "min_temp": 50, "max_temp": 90,
            "target_temp_low": 68, "target_temp_high": 72, "target_temp_step": .5,
            "supported_features": 2, "temperature_unit": "°F",
        })
        hass.states.async_set("remote.apple_tv", "on", {"friendly_name": "Apple TV"})
        hass.states.async_set("media_player.avr", "on", {
            "friendly_name": "AV Receiver", "volume_level": .34, "is_volume_muted": False, "supported_features": 1032,
        })
        hass.states.async_set("script.activity_power", "off", {"friendly_name": "Watch TV Power"})
        hass.states.async_set("automation.watch_tv", "on", {"friendly_name": "Start Watch TV"})
        handlers = {name: getattr(integration, name) for name in
                    ("draft_get", "draft_save", "draft_validate", "draft_preview")}
        handlers["get"] = integration.get_menu
        handlers["save"] = integration.save_menu

        async def dispatch(request):
            payload = await request.json()
            command = payload.pop("type").removeprefix(f"{DOMAIN}/")
            response = asyncio.get_running_loop().create_future()
            conn = SimpleNamespace(user=SimpleNamespace(is_admin=True),
                                   send_result=lambda _, data: response.set_result(data),
                                   send_error=lambda _, code, msg: response.set_result({"error": code, "message": msg}))
            handlers[command](hass, conn, {"id": 1, **payload})
            return web.json_response(await asyncio.wait_for(response, 2))

        async def index(_):
            return web.Response(text=INDEX, content_type="text/html")

        async def states(_):
            return web.json_response({
                state.entity_id: {"entity_id": state.entity_id, "state": state.state,
                                  "attributes": dict(state.attributes)}
                for state in hass.states.async_all()
            })

        app = web.Application(client_max_size=65536)
        app.router.add_get("/", index)
        app.router.add_get("/fixture/states", states)
        app.router.add_post("/fixture/ws", dispatch)
        app.router.add_static("/ununiversal_remote/", Path(integration.__file__).parent)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        print(f"http://{runner.addresses[0][0]}:{runner.addresses[0][1]}/", flush=True)
        try:
            with patch.object(type(hass.services), "async_call",
                              new=AsyncMock(side_effect=AssertionError("Preview cannot call services."))):
                await asyncio.Event().wait()
        finally:
            await runner.cleanup()
            await remote.stop()


if __name__ == "__main__":
    asyncio.run(main())
