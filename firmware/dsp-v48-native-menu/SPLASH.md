# Almost Universal startup splash

The V06 spare displayed the standalone native menu, with A opening Controls and D returning to Home. Pickup alone did not wake it after the display went dark. Stock motion-wake gating is under investigation. The splash candidate uses that stock-rendered navigation path and keeps the standalone ZIP available for comparison. [Physical milestone](../../docs/first-hardware-milestone.md#current-evidence)

On the first creation of the stock setup page per DSP boot, the splash shows the rounded Almost Universal icon and a two-line **ALMOST UNIVERSAL** wordmark. A native LVGL one-shot timer dismisses it after about three seconds. A fresh eligible key dismisses it early and stops at **Home**. A second fresh A press opens **Controls**. The branch used for stock key repeats does not arm the callback. KATA, ON and OFF retain their stock handling. This image provides local navigation and has no Home Assistant action binding.

The spare confirmed the timed transition, early A dismissal through hold and release, and fresh A/D navigation after dismissal. The separate Controls A candidate keeps this splash and adds one versioned Bluetooth action. [Next action build and wire contract](ACTION.md)

## Artwork and memory

The firmware uses a 48 × 76 version of the approved rounded icon with the three warm-white keys and cyan outline, encoded as a 928-byte LVGL indexed image including its four-color palette. The stock font supplies the wordmark. The deep navy is inside the icon tile, and the rest of the screen uses the stock backdrop. The smaller mark drops the full-frame artwork, texture, and original type treatment. Native text and image objects use the stock renderer. [Asset encoder](encode_splash_icon.py)

The image bytes are checked into `splash_icon.inc`, so a firmware rebuild needs only the pinned display-check ZIP and the existing Xtensa tools. To re-encode the asset, pass the approved PNG to `encode_splash_icon.py` with Pillow 12.1.1. It checks the PNG SHA-256 `56a3ac0cab4766aab930a9fc55076a736645a099ea97fea8ca979537a339a2a7` and can emit an enlarged preview of the exact icon using `--preview`. The source size and palette format are asserted by both the firmware build and fixture.

The splash initializer creates one native image and one native LVGL timer. The stock timer constructor at `0x2003fbe0` accepts the callback, period `3000`, and user data. The repeat setter at `0x20041898` sets the count to one. The stock timer scheduler at `0x2003fa48` calls the timeout and releases the timer when its repeat count reaches zero. The early-dismiss path hides the splash image, restores the existing stock icon and sets the Home label without blocking. A pending timeout then sees Home and has no effect. The native page owns the image until teardown. The timeout uses live page objects, so it can safely run after a page has gone away.

The stock first-press call at `0x2000ff35` wraps the original group send and scopes a flag around its synchronous native key callback. The stock repeat call at `0x2000feee` still takes its original route. A separate byte records that the splash has run. Both bytes fit in the aligned RAM word at `0x0018342c`, immediately after initialized data. The existing stock clear loop starts one word earlier. Its end is unchanged. No extra flash region, new persistent settings writes, or changes to ARM, RES, recovery, motion settings, pixel flush, or panel power routines.

On the Controls A image, key-free pickup displayed the splash and produced a fresh stock loader banner and `DSP:E`. The DSP startup clear resets the splash-shown byte on that path. The separate diagnostic tests whether the existing RAM word can distinguish pickup from a deliberate reset before that clear. Returning directly to the menu on pickup remains open. [Physical capture result and retention diagnostic](../dsp-v48-display-check/RETENTION.md)

## Exact app-origin pin

| Item | Value |
| --- | --- |
| Archive | `WoRWS-v4.8-DSP-ALMOST-UNIVERSAL-SPLASH.CANDIDATE.zip`, 252,215 bytes |
| ZIP SHA-256 | `7aabf2744574158f5e26c49c293d16b3a0dce587d533cce2b2690ce8dc58deab` |
| Sole member | `DSP.bin`, 458,676 bytes |
| DSP SHA-256 | `22ae52adf7db48727765681d795d6fd0a4e7363d24dd078a652856b42c906b03` |
| FreqChip CRC | `47b3c685` |

The DSP ends at exclusive U6 offset `0x6ffb4`, with 76 bytes remaining in the original 112 erase sectors. The `DSP:E/P/F` calls survive byte for byte. Two independent builds matched. The Xtensa fixture executes the actual first-press hook, stock group dispatch, native event router and child lookup against modeled native label, image, and timer functions. It checks the 3000 ms period, single timeout, early dismissal, held-key repeat, later fresh navigation, power and KATA filtering, and page recreation after the splash. Panel output, timer timing and motion wake still require a physical trial.

From the Switchbot workspace root, build and compare offline.

```sh
splash_build=$(mktemp -d)
python3 -B almost-universal/firmware/dsp-v48-native-menu/build.py \
  artifacts/universal-remote/WoRWS-v4.8-DSP-DISPLAY-CHECK.CANDIDATE.zip \
  "$splash_build/splash.zip" --splash --smoke \
  --tool-prefix "$HOME/Library/Arduino15/packages/esp32/tools/esp-x32/2507/bin/xtensa-esp32-elf"
cmp "$splash_build/splash.zip" \
  artifacts/universal-remote/WoRWS-v4.8-DSP-ALMOST-UNIVERSAL-SPLASH.CANDIDATE.zip
```

The build without `--splash` still matches the standalone native-menu candidate SHA-256 `450d7aef392d15dd63a5230b96359b45e5a3351996c21156fc551ed0e50ca377`.

## First bench trial

1. Use the checked normal Bluetooth app-origin update. Record handoff ACK `01 00 00 00 05`, DSP destination `0x00000000`, and CRC ACK `00 14 04 00`. Keep the full stock rollback ZIP and the standalone native-menu ZIP available.
2. Start a fresh normal boot with KATA released, and wake without an eligible key if the screen starts asleep. Let the splash expire with no buttons held. Check that the rounded icon and **ALMOST UNIVERSAL** appear, followed by **Home** around three seconds after the splash appeared.
3. Start another normal boot. While the splash is visible, press and hold A. It should go to **Home** and stay there through hold and release. Press A again to open **Controls**, then D to return to **Home**.
4. Open Controls and leave the remote stationary until its screen goes dark. Pick it up without pressing a key. The screen should return directly to a menu view without showing the splash. Compare with Down after another sleep. Record any repeated `DSP:E` with the wake result.
