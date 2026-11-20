# The Ununiversal Remote

**Making the SwitchBot Universal Remote live up to its name.**

We're turning a SwitchBot Universal Remote (W4600000) into a Home Assistant activity remote with editable screens. This repo tracks the teardown, read-only flash backup, Bluetooth uploader, and custom firmware experiments. The goal is to press a real button, let Home Assistant decide what it does on the current screen, and send the next screen or an IR command back to the remote.

![Component side of the opened SwitchBot Universal Remote, showing the battery and V06 main board](images/component-side.jpg)

## Progress as of November 19, 2026

| Workstream | Current result |
| --- | --- |
| Hardware | Confirmed the V06 PCB, FR5086D processor, and Zbit 16 MiB SPI flash on the bench unit. Captured the DSP startup log over a receive-only UART. |
| Firmware dumping | Captured and verified one complete 16 MiB U6 image from the v4.6 spare. Mapped the active DSP, an older DSP image, resources, and the settings filesystem. An independent full read and restoration of U6 are pending. |
| Bluetooth OTA | Restored all three stock v4.8 components over Bluetooth. The spare reported v4.8 and showed its normal screen. The public macOS CLI scans in normal or recovery mode and inspects packages. Its write command still requires a verified transfer profile. |
| Custom DSP | The spare booted and showed `OTA TEST` after receiving the modified DSP with stock v4.8 resources and ARM firmware. |
| Replacement ARM | Built the V06 development image and passed its Cortex-M3 emulator test. Physical boot and wired recovery are unverified. |
| Home Assistant | Added a sidebar menu editor, menu export, MQTT simulator, and Bluetooth central. Host tests show that each fresh soft A press calls the configured switch once. Physical Bluetooth testing is pending. |

## Try the offline tools

Use Python 3.11 or newer. ZIP inspection, the candidate builder, and the uploader's unit tests use the standard library. The dependencies below enable BLE scanning and serial capture.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v test_worws_ota
python worws_ota.py inspect /path/to/WoRWS_freq_app_V48.zip
```

On macOS, run `python worws_ota.py scan --normal` to find a running remote or `python worws_ota.py scan` to find one already in recovery mode. SwitchBot's app recovery clears previously synced devices. [SwitchBot firmware recovery](https://support.switch-bot.com/hc/en-us/articles/25438735905943-How-to-Recover-the-Firmware-of-SwitchBot-Universal-Remote)

## Build menus in Home Assistant

Copy `custom_components/ununiversal_remote` into your Home Assistant config directory under `custom_components` and restart Home Assistant. Add **The Ununiversal Remote** under **Settings → Devices & services → Add integration**, then open **Remote Menus** in the sidebar. The editor includes a sample Activities → TV → AC Control flow and a clickable preview.

Home Assistant can discover the handheld over an existing Bluetooth adapter or active proxy. During first setup, optionally select a switch to bind to soft key A. Bluetooth works independently of MQTT.

For testing over MQTT, configure Home Assistant’s MQTT integration and install `paho-mqtt` in a local Python environment to run the simulator.

```sh
python -m pip install paho-mqtt
python tools/simulate_remote.py mqtt.example.local living_room --username your-user
```

You can also add this repo as a HACS custom repository of type **Integration**. Home Assistant Core 2026.11 is the tested baseline. [Setup, MQTT contract, and testing](docs/remote-design.md) · [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/)

## Explore the project

- [Teardown photos, UART findings, and the complete U6 flash map](docs/hardware-and-dumping.md)
- [Stock image analysis, Bluetooth uploader, and custom firmware experiment](docs/firmware.md)
- [Replacement ARM firmware, build instructions, and emulator test](firmware/v06/README.md)
- [Home Assistant integration, menu preview, and transport](docs/remote-design.md)
- [SHA-256 manifest for the reference downloads](docs/SHA256SUMS)

The repository contains project-authored tools, notes, and bench photos. Vendor ZIPs, modified binaries, device dumps, and raw logs stay local.
