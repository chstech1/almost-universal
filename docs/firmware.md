# Firmware research

The V06 spare started on v4.6. After the [U6 capture](hardware-and-dumping.md#completed-v46-capture), the bench used v4.8 for the Bluetooth and display tests. The Android update flow was studied in SwitchBot 9.11.15.13 (build 40000051).

## Stock reference images

Eleven public OTA ZIPs (`09`, `10`, `11`, `12`, `20`, `27`, `40`, `42`, `46`, `47`, `48`) passed ZIP CRC checks and matched repeat downloads by SHA-256. Compare files you obtain from SwitchBot with the [reference hashes](SHA256SUMS). The v4.8 ZIP contains application update members. A complete rollback also depends on the board data and a proven way to restore it. [SwitchBot release catalog](https://www.wohand.com/version/wocaotech/release.json) · [Stock v4.6 ZIP](https://www.wohand.com/version/wocaotech/firmware/WoRWS/WoRWS_freq_app_V46.zip) · [Stock v4.8 ZIP](https://www.wohand.com/version/wocaotech/firmware/WoRWS/WoRWS_freq_app_V48.zip)

| v4.8 member | Size | First-pass findings |
| --- | ---: | --- |
| `ARM.bin` | 209,212 bytes | Thumb image with external IR chip, Bluetooth HID, and recovery references. v4.7's ARM member differs from v4.8 at 11 byte positions. |
| `DSP.bin` | 456,819 bytes | Xtensa image with LVGL display and input code, LittleFS, and key maps and scene storage. v4.6 and v4.8 differ by one byte in a DSP version routine. |
| `RES.bin` | 4,955,264 bytes | Contains resources and an executable Xtensa prefix. Identical across the examined v4.6, v4.7, and v4.8 packages. |

The [Ghidra script](../tools/DecompileRemote.java) exports a function index and provisional pseudocode for a stock member imported as a raw binary. Provide a writable output directory as its first script argument. The initial ARM analysis used file offsets from base zero. Later work identified the ARM application link address as `0x01003000`. DSP and RES-prefix analysis used virtual bases `0x20000000` and `0x20100000`. The U6 capture independently located both members at their physical offsets.

The stock DSP initializes a 240 × 320 LVGL display and registers separate keypad and wheel inputs. The panel commands are consistent with the ST7789 family. The exact controller variant and board behavior still need bench confirmation.

## Bluetooth recovery uploader

The Android updater's FreqChip path schedules `RES`, `DSP`, and `ARM` in that order when present. The app's recovery screen recognizes the `WoRws_D` advertisement and retrieves recovery-package metadata separately from the public release catalog. The prototype follows that documented recovery entry, with transfer behavior modeled from the stock app. [SwitchBot firmware recovery](https://support.switch-bot.com/hc/en-us/articles/25438735905943-How-to-Recover-the-Firmware-of-SwitchBot-Universal-Remote)

The [Python CLI](../worws_ota.py) has three subcommands.

| Command | Behavior |
| --- | --- |
| `inspect PACKAGE` | Validates the archive offline and prints the SHA-256, components, sizes, and FreqChip CRC values. |
| `scan` | Uses Bleak on macOS to list nearby devices advertising `WoRws_D`. Add `--normal` to discover remotes in normal operation. |
| `flash PACKAGE --device UUID` | Development transfer command with explicit device selection and per-command acknowledgment handling. The published profile list is empty, so this command rejects packages before connecting. |

The bench uploader restored stock v4.8 over Bluetooth using the local `RES.bin`, `DSP.bin`, and `ARM.bin`. After reboot, a direct Bluetooth read reported v4.8 and a Down press brought up the normal screen. The bench procedure used neither the SwitchBot app nor its servers. The public CLI still needs the bench-specific transfer and post-reboot checks integrated and tested as a release. [Offline tests](../test_worws_ota.py)

## First custom firmware experiment

The [offline candidate builder](../tools/build_worws_ota_test.py) checks the stock v4.8 DSP digest, replaces its English `Charging` label with the equal-length string `OTA TEST`, then verifies the output ZIP. The archive contains only `DSP.bin`. A byte comparison confirmed that every byte outside the label matches the stock v4.8 DSP image.

```sh
python tools/build_worws_ota_test.py /path/to/WoRWS_freq_app_V48.zip WoRWS-v4.8-DSP-OTA-TEST.CANDIDATE.zip
python worws_ota.py inspect WoRWS-v4.8-DSP-OTA-TEST.CANDIDATE.zip
```

An initial test that sent the modified DSP and stock ARM rebooted with a blank display. A full stock restore brought the screen back. The next test sent the modified DSP together with stock RES and ARM, and the spare rebooted and displayed **OTA TEST** on the charging screen. The cause of the earlier blank screen remains open.

## Replacement ARM prototype

The [V06 ARM source](../firmware/v06/README.md) builds an original menu and BLE application linked against the FR5080 SDK. The Cortex-M3 emulator exercised the GATT service, menu activation, two fresh soft A presses, and disconnect behavior. Home Assistant host tests routed those C-generated presses to a simulated switch. This ARM image has yet to boot on a physical V06. The DSP experiment retained the stock ARM updater. Independent wired recovery still needs bench verification before replacing that updater.
