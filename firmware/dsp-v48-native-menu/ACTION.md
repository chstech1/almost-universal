# Controls A over stock Bluetooth v1

This candidate keeps the Almost Universal splash and native A/D navigation. The standalone splash passed its physical timeout, early A dismissal, hold/release, and post-dismissal navigation trial. This DSP build adds one outbound event for **Controls → A: Action** through stock ARM v4.8. Home A opens Controls locally and Controls D returns to Home locally. The splash-dismissing key, hold, release, and all other keys produce no custom frame. [Verified splash and bench procedure](SPLASH.md)

## Exact pin

| Item | Value |
| --- | --- |
| ZIP | `WoRWS-v4.8-DSP-CONTROLS-A-V1.CANDIDATE.zip`, 252,307 bytes |
| ZIP SHA-256 | `10d28049e790ba732902894bd3b08451b04dc71b5e605753d19ad3da062a1572` |
| Sole member | `DSP.bin`, 458,700 bytes |
| DSP SHA-256 | `e92b954ab40e9f5b2e9f4fb7973ae5d968adcce52d613ddb24e36b98e3c5f663` |
| FreqChip CRC | `31444870` |

The image ends at exclusive U6 offset `0x6ffcc`, with 52 bytes left in the original 112 erase sectors. This variant uses direct windowed calls within the verified Xtensa call range to make room for the relay. The 928 indexed splash bytes, three-second timer, native redraw, app-entry diagnostics, stock ARM and RES are retained. The build adds no persistent settings writes or additional static RAM. The standalone native and splash ZIPs still reproduce at their original hashes.

## Display and wire contract

The stock ten-byte input dispatcher calls the wrapper at `0x2006fa5c` from `0x200050f4`. The wrapper calls the original normalizer. Its gate requires exactly the raw A mask `0x1`, initial phase `1`, zero wheel sample, an active stock `nodev` page and the live Controls label. Stock page registration stores the name pointer `0x20060690` in the page object, and the active-page routine returns that exact pointer. The gate therefore excludes overlay pages even if the old label still exists. The dispatcher still calls the stock idle-reset routine after the wrapper returns.

The accepted branch alone allocates the `0x330`-byte sender frame used to prepare the stock length `0x302` tag-19 payload. It copies report bytes 6–9 verbatim into the v1 timestamp, sets the forwarded length to 11, and zeros the remaining transport padding. Stock ARM sends the notification through its existing normal-mode plaintext BLE path. There is no DSP action queue. Hardware stack headroom and radio delivery for this build remain bench checks. [v1 protocol and stock transport](../dsp-v48/PROTOCOL.md)

| Notification field | Value |
| --- | --- |
| Normal notification characteristic | `cba20003-224d-11e6-9fb8-0002a5d5c51b` |
| Full 14-byte frame shape | `7e 00 00 00 55 52 01 01 02 01 tt tt tt tt` |
| Source and key | Controls `02`, soft A / `soft_1` `01` |
| Timestamp | Four stock report bytes, little-endian. For `0x12345678`, the suffix is `78 56 34 12`. |
| Home Assistant profile | **Stock ARM v4.8 · DSP key reports v1** (`stock_v48_v1`) |
| Binding | **Controls → Shortcut 1 → Toggle switch** for the disposable test switch. Other profile bindings have no source in this candidate. |

## Verification and bench sequence

The Xtensa fixture executes the stock ten-byte dispatcher, actual hook and native UI event path. It verifies two fresh Controls A reports with exact timestamps and zero padding, and rejects splash A, Home A, local D, hold, release, chord, wheel and an inactive page. The independent HiFi3 decoder checked the generated instructions. The icon data matches the physically tested splash byte for byte. The existing software decoder accepted the exact v1 example as `controls / soft_1 / press` in an isolated offline check.

The physical spare entered recovery on this build. The operator saw the red icon and a passive scan matched `WoRws_D`. Ordinary Reset returned to the installed Controls menu. The post-Reset pair of short A taps produced two Home Assistant input events and on → off → on transitions on the disposable switch. The earlier short-tap pair also passed when its event records were inspected. The separate hold → release → retap sequence still produced only one frame over direct Bluetooth. [Physical evidence](../../docs/first-hardware-milestone.md#current-evidence)

1. Use the exact pin with the checked app-origin route. Verify handoff ACK `01 00 00 00 05`, DSP destination zero and CRC ACK `00 14 04 00`.
2. Check the splash still times out to Home. On a separate boot, hold A during the splash. Home should stay visible through hold and release. Tap A again to open **Controls**, where the labels are **A: Action** and **D: Back**.
3. In the versioned stock BLE session, verify that two fresh A taps on the visible Controls screen produce two frames of the shape above. Check that hold, release, D back to Home, splash dismissal and reconnect produce no action. Then correlate the same test with the disposable Home Assistant switch. [Existing software setup](../../docs/stock-arm-ble.md)

To reproduce from the Switchbot workspace root:

```sh
action_build=$(mktemp -d)
python3 -B almost-universal/firmware/dsp-v48-native-menu/build.py \
  artifacts/universal-remote/WoRWS-v4.8-DSP-DISPLAY-CHECK.CANDIDATE.zip \
  "$action_build/controls-a.zip" --action --smoke \
  --tool-prefix "$HOME/Library/Arduino15/packages/esp32/tools/esp-x32/2507/bin/xtensa-esp32-elf"
cmp "$action_build/controls-a.zip" \
  artifacts/universal-remote/WoRWS-v4.8-DSP-CONTROLS-A-V1.CANDIDATE.zip
```
