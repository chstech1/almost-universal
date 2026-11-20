# Firmware research

The spare runs v4.6. The static analysis used stock v4.8 and compared its images with v4.6 and v4.7. The Android update flow was studied in SwitchBot 9.11.15.13 (build 40000051).

## Stock reference images

Eleven public OTA ZIPs (`09`, `10`, `11`, `12`, `20`, `27`, `40`, `42`, `46`, `47`, `48`) passed ZIP CRC checks and matched repeat downloads by SHA-256. Compare files you obtain from SwitchBot with the [reference hashes](SHA256SUMS). The v4.8 ZIP contains application update members. A complete rollback also depends on the board data and a proven way to restore it. [SwitchBot release catalog](https://www.wohand.com/version/wocaotech/release.json) · [Stock v4.6 ZIP](https://www.wohand.com/version/wocaotech/firmware/WoRWS/WoRWS_freq_app_V46.zip) · [Stock v4.8 ZIP](https://www.wohand.com/version/wocaotech/firmware/WoRWS/WoRWS_freq_app_V48.zip)

| v4.8 member | Size | First-pass findings |
| --- | ---: | --- |
| `ARM.bin` | 209,212 bytes | Thumb image with external IR chip, Bluetooth HID, and recovery references. v4.7's ARM member differs from v4.8 at 11 byte positions. |
| `DSP.bin` | 456,819 bytes | Xtensa image with LVGL display and input code, LittleFS, and key maps and scene storage. v4.6 and v4.8 differ by one byte in a DSP version routine. |
| `RES.bin` | 4,955,264 bytes | Contains resources and an executable Xtensa prefix. Identical across the examined v4.6, v4.7, and v4.8 packages. |

The [Ghidra script](../tools/DecompileRemote.java) exports a function index and provisional pseudocode for a stock member imported as a raw binary. Provide a writable output directory as its first script argument. The ARM project used file offsets from base zero. DSP and RES-prefix analysis used inferred virtual bases `0x20000000` and `0x20100000`. Physical flash offsets, LCD interface, and a usable FR5086D toolchain remain open.

## Bluetooth recovery uploader

The Android updater's FreqChip path schedules `RES`, `DSP`, and `ARM` in that order when present. The app's recovery screen recognizes the `WoRws_D` advertisement and retrieves recovery-package metadata separately from the public release catalog. The prototype follows that documented recovery entry, with transfer behavior modeled from the stock app. [SwitchBot firmware recovery](https://support.switch-bot.com/hc/en-us/articles/25438735905943-How-to-Recover-the-Firmware-of-SwitchBot-Universal-Remote)

The [Python CLI](../worws_ota.py) has three subcommands.

| Command | Behavior |
| --- | --- |
| `inspect PACKAGE` | Validates the archive offline and prints the SHA-256, components, sizes, and FreqChip CRC values. |
| `scan` | Uses Bleak on macOS to list nearby devices advertising `WoRws_D`. |
| `flash PACKAGE --device UUID` | Prototype transfer with explicit device selection, per-command acknowledgment handling, and post-reboot version confirmation. The verified-package list is empty, so this command rejects every package before connecting. |

The public v4.8 archive passed download integrity checks. The exact app-selected recovery ZIP and its resource parameters still need confirmation. [Offline tests](../test_worws_ota.py) cover archive validation, the pre-connection package check, simulated packet ordering, chunking, and transfer failures. A successful live milestone requires a stock transfer to the spare followed by normal boot, working screen and controls, and v4.8 confirmed in the SwitchBot app.

## First custom firmware experiment

The [offline candidate builder](../tools/build_worws_ota_test.py) checks the stock v4.8 DSP digest, replaces its English `Charging` label with the equal-length string `OTA TEST`, then verifies the output ZIP. The archive contains only `DSP.bin`. A byte comparison confirmed that every byte outside the label matches the stock v4.8 DSP image. Bootloader acceptance, actual display behavior, and recovery after a custom install remain unverified.

```sh
python tools/build_worws_ota_test.py /path/to/WoRWS_freq_app_V48.zip WoRWS-v4.8-DSP-OTA-TEST.CANDIDATE.zip
python worws_ota.py inspect WoRWS-v4.8-DSP-OTA-TEST.CANDIDATE.zip
```

The stock updater normally finishes with an ARM stage, and the SPI captures show data beyond the DSP payload within its last flash sector. Both observations need to be resolved before a DSP-only install. The bench sequence is to verify a complete read and restore path, confirm stock v4.8 recovery over Bluetooth, then evaluate the DSP experiment on the matching stock baseline.
