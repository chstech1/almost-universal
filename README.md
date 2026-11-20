# The Ununiversal Remote

**Making the SwitchBot Universal Remote live up to its name.**

We're turning a SwitchBot Universal Remote (W4600000) into a Home Assistant activity remote with editable screens. This repo tracks the teardown, read-only flash backup, Bluetooth uploader, and custom firmware experiments. The goal is to press a real button, let Home Assistant decide what it does on the current screen, and send the next screen or an IR command back to the remote.

![Component side of the opened SwitchBot Universal Remote, showing the battery and V06 main board](images/component-side.jpg)

## Progress as of November 19, 2026

| Workstream | Current result |
| --- | --- |
| Hardware | Confirmed the V06 PCB, FR5086D processor, and Zbit 16 MiB SPI flash on the bench unit. Captured the DSP startup log over a receive-only UART. |
| Firmware dumping | Built an ESP32 reader with overlapping SPI reads, CRC-checked USB frames, and retries. Captured partial reads from the spare running v4.6. Full backup verification and a restore test are pending. |
| Stock firmware | Checked and fingerprinted eleven vendor OTA ZIPs. First-pass ARM and DSP analysis found IR and Bluetooth code, LVGL menus and input handling, and persistent configuration. |
| Bluetooth uploader | Implemented a macOS CLI for ZIP inspection, recovery-mode discovery, and the proposed stock transfer sequence. Offline tests pass. Live writes are disabled pending verification of the exact recovery package and transfer parameters. |
| Custom firmware | Built a v4.8 DSP-only candidate that changes the English charging label to `OTA TEST`. The candidate passed offline checks. Its acceptance over Bluetooth, boot behavior, and recovery are unverified. |
| Home Assistant | Designed the button events and screen updates for a four-slot menu. Hardware integration and latency measurements are pending. |

## Try the offline tools

Use Python 3.11 or newer. ZIP inspection, the candidate builder, and the uploader's unit tests use the standard library. The dependencies below enable BLE scanning and serial capture.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v test_worws_ota
python worws_ota.py inspect /path/to/WoRWS_freq_app_V48.zip
```

For discovery on macOS, run `python worws_ota.py scan` with the remote already in recovery mode. See SwitchBot's instructions for entering recovery and restoring through its app. App recovery clears previously synced devices. [SwitchBot firmware recovery](https://support.switch-bot.com/hc/en-us/articles/25438735905943-How-to-Recover-the-Firmware-of-SwitchBot-Universal-Remote)

## Explore the project

- [Teardown photos, UART findings, and the U6 flash reader](docs/hardware-and-dumping.md)
- [Stock image analysis, Bluetooth uploader, and custom firmware experiment](docs/firmware.md)
- [Home Assistant activity and screen design](docs/remote-design.md)
- [SHA-256 manifest for the reference downloads](docs/SHA256SUMS)

The repository contains project-authored tools, notes, and bench photos. Vendor ZIPs, modified binaries, device dumps, and raw logs stay local.
