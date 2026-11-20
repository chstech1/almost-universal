# Home Assistant activity remote

Home Assistant owns activities, menu definitions, and button mappings. The handheld renders a screen with optional status text and up to four labels mapped to the physical shortcut keys. It also handles the wheel, hard keys, IR emission, and sleep and wake on the device.

## Button and screen messages

Each button event carries the screen that was visible when the user pressed it. Home Assistant uses the screen and button IDs together, so the same key can change the cooling setpoint in one menu and control receiver volume in another.

```json
{"screen_id":"tv","button_id":"soft_2"}
```

Home Assistant can reply with a screen description. The remote draws it locally and leaves unused button slots blank.

```json
{
  "screen_id": "ac",
  "title": "AC Control",
  "text": "Room 72°F\nHeat 68°F · Cool 74°F",
  "buttons": {"soft_4": "Back"}
}
```

A first activity flow runs **Activities → TV → AC Control**. The TV screen exposes Lights, AC Control, Blinds, and Off. In AC Control, Channel adjusts the heat target and Volume adjusts the cool target. Off on the TV screen runs the shutdown activity and returns to the activity selector. An editable Home Assistant configuration can hold the screen text, navigation, and button actions. Named IR commands such as `tv_power_off` can refer to locally stored codes once the IR path is working.

## Transport and testing

The proposed BLE design uses notifications from the remote and writes back through an active ESPHome Bluetooth proxy. A laptop or ESP32 bridge can prototype the same messages over MQTT. This is a design with example messages. The integration, menu editor, and device-side renderer are pending. [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/) · [Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt/)

The initial latency target is under 150 ms from press to visible menu change for 95% of presses while connected. Measure the first press after sleep separately and check channel and volume repeat behavior. A simulator for the activity flow can validate the Home Assistant mappings while the device recovery and display work continues.
