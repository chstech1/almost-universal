# Stock ARM v4.8 Home Assistant handoff

This Home Assistant integration uses the spare's normal-mode GATT service. Follow the [DSP contract](../firmware/dsp-v48/PROTOCOL.md) for the candidate on the handheld. The replacement-ARM URM1 editor and MQTT simulator retain their existing menu data. Stock profiles store their bindings separately.

The matched **Almost Universal handheld** profile has its own [package pins, TV A binding test, and rollback](stock-handheld-ha.md).

## Associate the spare

1. In **Settings → Devices & services → The Ununiversal Remote → Configure**, select the profile for the installed DSP candidate. Use **Stock ARM v4.8 · A-marker bench** for the exact ten-byte marker. Use **Stock ARM v4.8 · DSP key reports v1** for the two-screen key-report candidate.
2. Enter the spare's Bluetooth address as shown by **Bluetooth → Advertisement monitor** in Home Assistant. From the same advertisement, enter the first six bytes of the manufacturer data for company ID `2409` (`0x0969`). Enter the bytes as twelve hex digits or as colon-separated pairs. The integration checks both values before connecting.
3. Clear **Enable MQTT simulator transport** for the direct bench test. The integration subscribes through a Home Assistant adapter or an active ESPHome Bluetooth proxy and verifies the response to the stock v4.8 query before accepting any key notifications. [Home Assistant Bluetooth](https://www.home-assistant.io/integrations/bluetooth/) · [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/)

## Configure and test one action

1. Create or select a disposable switch in the test Home Assistant instance. A template switch backed by an input boolean works.
2. Open **Remote Menus**. In the **A-marker bench** profile, select **Home**, set **Action** to **Toggle switch**, choose the disposable switch, and save. In the **DSP key reports v1** profile, open **Controls**, choose **Shortcut 1**, and set the same action. Optional hard-key bindings in that profile use the same picker. Home A and Controls D are reserved for navigation.
3. Record the simulated switch's initial state. In **Developer Tools → Events**, listen for `ununiversal_remote_input` and check that the event's `transport` corresponds to the configured profile. Press A once and confirm one toggle. Hold and release, then reconnect the remote before pressing another key. Confirm the switch stays at its current state. Press A again and confirm it returns to its original state.

The **Home → Controls → Home** sample is a preview in marker mode. The versioned candidate defines that navigation locally. Its Home captions are **Controls / – / – / –**, and its Controls captions are **Action / – / – / Back**. Dashes mark unused slots. The stock profiles support HA-side press bindings and send only the verified version query. The URM1 menu export belongs to the separate replacement-ARM transport.

## Reproduce the simulated check

Run from a Python environment with Home Assistant installed. The stock test substitutes the adapter and GATT device, feeds exact and near-match frames through the integration, and uses an isolated Home Assistant service registry and switch state.

```sh
python -m unittest discover -s tests -p test_stock_ble.py -v
python -m unittest discover -s tests -v
```

The first command covers device association, the version query, rejected stock traffic, reconnect, the saved A binding, v1 deduplication, and hard-key routing. The full suite also exercises the legacy menu and the replacement ARM firmware using a C compiler.

## Stage the integration for deployment

From the repository root, package the complete integration directory. Exclude bytecode created by local tests.

```sh
zip -r /tmp/ununiversal-remote-stock-v48.zip custom_components/ununiversal_remote -x '*/__pycache__/*' '*.pyc'
shasum -a 256 /tmp/ununiversal-remote-stock-v48.zip
```

Project management can stage that archive against an isolated Home Assistant instance first. On the approved target, copy only the integration directory into the existing Home Assistant configuration and retain the existing config entry and storage. Restart Core to load version `0.1.2`, choose the stock profile under **Configure**, and use the disposable-switch procedure before assigning a real device. Keep the prior component directory available for rollback.
