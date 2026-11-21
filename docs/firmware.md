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

The [Python CLI](../worws_ota.py) uses local files and the Mac's Bluetooth radio. Its full stock transfer restored the spare's display. The separately logged bench harness verified two DSP-only candidates using stock app-initiated update entry. [Physical results](first-hardware-milestone.md#current-evidence)

**The first OTA command after KATA + Reset can trigger the remote's own external flash erase.** Static inspection of the stock v4.8 ARM image at `+0x0d6ee` shows a 16 MiB erase request before the dispatcher handles a chip query, destination query, or transfer. The requested range includes U6's display resources. The bench logs do not establish which sectors actually erased or whether the background erase completed. Treat the setup commands sent by `flash` as part of the firmware write. Use advertisement scans and offline `inspect` and `preflight` for identification and file checks.

The stock normal-mode OTA handoff reaches the same recovery service. A fresh boot through the app branch leaves the physical KATA erase flag clear. The first recovery command still persists incomplete-update state. On reset, that state causes a marker write to U6 sector `0xfe000` below RES, followed by another reset. App-origin DSP-only trials rendered the nine-byte setup-label edit and ran the A-button marker with stock ARM v4.8. Those runs establish that enough stock resources remained readable to render the setup screen. No full RES readback was taken.

| Command | Behavior |
| --- | --- |
| `inspect PACKAGE` | Checks ZIP integrity offline and prints archive and member SHA-256 values, sizes, and FreqChip CRCs. |
| `preflight STOCK [--dsp-package CANDIDATE]` | Checks pinned archive hashes, members, and erase geometry offline. For stock, prints the full transfer order. |
| `scan` | Lists nearby `WoRws_D` advertisements without making a Bluetooth connection. Add `--normal` to discover remotes in normal operation. |
| `status` | Matches the normal UUID and manufacturer identifier and reads the firmware version and battery directly. |
| `probe-recovery STOCK [--dsp-package CANDIDATE]` | Disabled before any Bluetooth connection pending verification of a non-erasing recovery entry. |
| `flash STOCK` | Restores stock RES, DSP, and ARM, then verifies the normal-mode ARM version. |
| `flash-dsp STOCK --dsp-package CANDIDATE` | Disabled before any Bluetooth connection for the same reason. Both pinned DSP archives remain available for offline preflight. |

### Offline preflight

Run from this checkout with Python 3.11 or newer and [the BLE dependency](../requirements.txt) installed for live checks. Downloaded images and device identifiers belong in private bench storage. Set these shell variables from the private bench record.

```sh
stock_zip='/absolute/path/to/WoRWS_freq_app_V48.zip'
candidate_zip='/absolute/path/to/WoRWS-v4.8-DSP-A-BLE.CANDIDATE.zip'
normal_id='spare normal-mode CoreBluetooth UUID'
maker_id='spare six-byte manufacturer identifier'
recovery_id='spare recovery-mode CoreBluetooth UUID'
log_dir=$(mktemp -d)
set -o pipefail

python3 -B -m unittest test_worws_ota
python3 -B worws_ota.py preflight "$stock_zip" | tee "$log_dir/01-stock-preflight.log"
python3 -B worws_ota.py preflight "$stock_zip" --dsp-package "$candidate_zip" \
  | tee "$log_dir/02-dsp-preflight.log"
```

The stock ZIP must match SHA-256 `dac9677e93d4190dccc25498971ad146fee4d8217b6f866138266c088e4ca44e`. The staged A ZIP must match `fae96b9b43e8917b81f0a56ffcc4a2fa305e0b2d07ecdc2c2422990c6e975fff`. Its sole member is a 457,630-byte `DSP.bin` with FreqChip CRC `d3927b87`. It fits in the stock DSP's 112 erase sectors.

The offline eight-byte charging-label control is `WoRWS-v4.8-DSP-OTA-TEST.CANDIDATE.zip`. The archive SHA-256 is `44fad7c5bae85a3370c81794b520246da348d3ce20236c5a3c8b111a977bbca7`. Its sole member is a 456,819-byte `DSP.bin` with SHA-256 `67d234da4c7afd1fe72529dfcc2de95c543e44b15adcc42c4e7f372f3c4c8697` and FreqChip CRC `efdb1a3d`. The positive physical run included stock RES and ARM.

### Rehearse the stock rollback

1. With the spare awake in normal mode, run `status`. Check v4.8 and a working display. Begin a transfer above the original updater's 20% low-battery cutoff. Release any other Bluetooth client holding the connection.
2. With the charger disconnected, hold the red Kata button, briefly tap recessed Reset, and keep holding Kata for a few seconds. Confirm the red icon and identify the spare's `WoRws_D` advertisement with `scan`. If nearby remotes make the identity ambiguous, isolate the spare and repeat the transition before writing. Use the observed recovery UUID in the commands below.
3. Run `flash` for the full stock restore. The remote can begin erasing during setup, before the tool's explicit erase packets. The tool checks destinations and transfers RES, DSP, and ARM in that order. The resource destination is physically `0x100000`, with resource-relative write addresses starting at zero.
4. After `flash` reports v4.8 in normal mode, wake the display with Down. Record the resulting screen and whether the menu responds. A Bluetooth version reply alone leaves the display check open. The restore may clear synced profiles, so use the spare and keep its separate backup.

```sh
python3 -B worws_ota.py status --normal-device "$normal_id" --manufacturer-id "$maker_id" \
  2>&1 | tee "$log_dir/03-stock-before.log"
# Complete the manual recovery entry here and check the recovery UUID.
python3 -B worws_ota.py scan 2>&1 | tee "$log_dir/04-recovery-scan.log"
python3 -B worws_ota.py flash "$stock_zip" --device "$recovery_id" \
  --normal-device "$normal_id" --manufacturer-id "$maker_id" \
  2>&1 | tee "$log_dir/05-stock-restore.log"
```

The normal check matches both supplied identifiers. Recovery mode may omit manufacturer data. The tool checks the exact recovery UUID and service, rejects conflicting manufacturer data when present, and aborts if the selected spare still advertises in normal mode. The operator establishes the relationship between the two UUIDs by observing the physical transition.

If the restore logs a successful ARM final acknowledgment and then times out on version readback, wake the spare and run `status` separately. If recovery disconnects during its first command, treat external flash as potentially erased. Record the error, confirm the target and recovery mode, and rerun the full stock restore.

### DSP-only bench history

Both `probe-recovery` and `flash-dsp` now exit with status **1** before opening Bluetooth. `preflight` still checks both exact DSP candidate archives offline. [Offline tests](../test_worws_ota.py)

On November 20, the first DSP-only A trial entered update through KATA + Reset and returned `00 14 04 00`, which verifies the transferred DSP CRC. After manual Reset, the spare answered a normal v4.8 version query and showed a lit backlight with no image. A full stock rollback restored normal v4.8 Bluetooth and a working setup screen.

The app-origin label trial wrote only the DSP with nine changed label bytes. The spare displayed **DSP ready. Please add devices via app.** A passive KATA + Reset check then showed the red recovery icon and the `WoRws_D` advertisement. The later app-origin A trial wrote the same A image used in the first trial and received `00 14 04 00`. The screen worked after Reset and Down, the ARM reported v4.8, and two fresh A presses produced exactly two `7e 00 00 00 55 52 2d 41 2d 31` Bluetooth notifications. Hold and release produced no extras. The later **Controls A v1** build added the native Home/Controls menu, timed splash and a versioned action frame. One of two physical Controls A presses reached Home Assistant and toggled the disposable test switch. Repeatability remains open. [Physical bench record](first-hardware-milestone.md#current-evidence) · [UART startup evidence](../firmware/dsp-v48-uart/README.md)

## First custom firmware experiment

The [offline candidate builder](../tools/build_worws_ota_test.py) checks the stock v4.8 DSP digest, replaces its English `Charging` label with the equal-length string `OTA TEST`, then verifies the output ZIP. The archive contains only `DSP.bin`. A byte comparison confirmed that every byte outside the label matches the stock v4.8 DSP image.

```sh
python tools/build_worws_ota_test.py /path/to/WoRWS_freq_app_V48.zip WoRWS-v4.8-DSP-OTA-TEST.CANDIDATE.zip
python worws_ota.py inspect WoRWS-v4.8-DSP-OTA-TEST.CANDIDATE.zip
```

An initial test that sent the modified DSP and stock ARM rebooted with a blank display. A full stock restore brought the screen back. The next test sent the modified DSP together with stock RES and ARM, and the spare rebooted and displayed **OTA TEST** on the charging screen. The cause of the earlier blank screen remains open.

## Replacement ARM prototype

The bench decision was to start from retail v4.8 and modify the DSP first. This keeps the stock ARM code that owns Bluetooth, normal update entry, and the KATA + Reset recovery service used for the full v4.8 restore. A full restore writes the stock RES, DSP, and ARM in that order and verifies normal v4.8 Bluetooth and a working screen. The app-origin DSP-only path passed physical tests while retaining the stock ARM image. The passive red-icon and advertisement check after the label test verified recovery entry on that build.

The replacement V06 ARM build is a separate FR5080 SDK application with its own Home Assistant BLE service, menu rendering, and input handling. It drives the LCD from the ARM and holds the display DSP in reset. The Cortex-M3 emulator exercised GATT, menu activation, two fresh soft A presses, and disconnect behavior. Home Assistant host tests routed those events to a simulated switch. Porting the retail updater into this image was discussed and remains unimplemented. The replacement image remains offline. Physical boot and an independent wired ARM restore are still unverified. [Replacement ARM source, build and limits](../firmware/v06/README.md)
