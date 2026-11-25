# Almost Universal handheld bench candidate

The physically tested layout is documented below. The [separate visual polish image](../../docs/handheld-native-polish.md#staged-polish-image) uses the same wire contract and stock recovery path.

The DSP starts on **Activities**. The layout candidate uses native LVGL labels in the existing 240 × 320 `nodev` container. Menu tiles use two 103-pixel columns at x 14 and 123 with a six-pixel gutter and a lime focus fill. TV mode reuses the four tile objects as 60-pixel caption slots beginning at y 274. The direction pad moves only to occupied adjacent positions. OK opens a focused screen. Physical Back returns to the parent and restores its focus. Physical Back at Activities and A–D in Menu mode are inactive.

OK on **Watch TV** opens TV mode locally. In TV mode, A–C, the directional pad, OK, channel, volume, mute, hard Back and hard Home emit stock v1 frames with source byte `03`. D returns to Activities at **Watch TV** before any transport call, including when the link is down. The corresponding Home Assistant profile `stock_v48_handheld` supports press bindings to a switch or script for these TV keys. An unassigned command has no action. [Home Assistant wire contract](../dsp-v48/PROTOCOL.md#almost-universal-handheld-staging-contract)

The release guard uses the next different single-key phase-1 report as evidence that entry OK is up. Stock ARM can repeat phase 1 and provides the DSP with no ordinary release report. An immediate second OK in TV mode is suppressed until a different key arrives. Immediate standalone OK after entry needs a verified release signal. Menu action tiles show **Set up in Home Assistant** in this stage. Binding IDs for those tiles and inbound captions, entity state, link status and receipts remain open. The LCD uses the stock font and defers the splash, tile icons, exact title typography and live status line. [Approved design](../../docs/handheld-menu-spec.md) · [Repository preview](../../tools/handheld-menu-preview.html)

## Rebuild offline

Run from the Switchbot workspace root with the Espressif Xtensa toolchain and QEMU. The build requires the exact **LCD CHECK** archive.

```sh
handheld_build=$(mktemp -d)
python3 -B almost-universal/firmware/dsp-v48-native-menu/build.py \
  artifacts/universal-remote/WoRWS-v4.8-DSP-DISPLAY-CHECK.CANDIDATE.zip \
  "$handheld_build/handheld.zip" --handheld-layout --smoke \
  --tool-prefix "$HOME/Library/Arduino15/packages/esp32/tools/esp-x32/2507/bin/xtensa-esp32-elf"
cmp "$handheld_build/handheld.zip" \
  artifacts/universal-remote/WoRWS-v4.8-DSP-ALMOST-UNIVERSAL-LAYOUT.CANDIDATE.zip
```

| Verified item | Value |
| --- | --- |
| Archive SHA-256 | `cb23fbee3d86c9bad4faff06d19bf409f2fd78042ed320ef4fc5256c64775519` |
| Sole member | `DSP.bin`, 458,540 bytes |
| Member SHA-256 | `d1927e626b10d38add48afc73c2ac37359ac7e332ce5906a2d7f5108c80b466e` |
| FreqChip CRC | `f89b28ab` |
| Headroom before original 112-sector DSP erase boundary | 212 bytes |

Relative to **LCD CHECK**, the build changes six bytes across the label and report call sites and the BSS-start word. The extra BSS word holds volatile navigation state. The build uses the stock redraw, flush, ARM, RES, storage layout and On/Off/KATA paths. The Xtensa fixture executes the patched dispatcher and stock child lookup with modeled LVGL styling and action transport. It checks tile geometry, RGB565 focus colors, footer placement, Back focus restoration, the entry guard and the outgoing TV frames. Two builds matched byte for byte. Actual panel rendering, contrast, allocation and delivery require the physical trial.

The earlier text checkpoint remains available via `--handheld`. It has the same input and wire contract and uses a single stock label with a `>` cursor. Its archive is `WoRWS-v4.8-DSP-ALMOST-UNIVERSAL-HANDHELD.OFFLINE.zip`, SHA-256 `074ef125fb46c75d01d315c3f0a163ee94d9e08a2e47fe61a8516523495a9c13`, DSP size 458,048 and FreqChip CRC `c4b211f7`.

## First physical pass

Use normal app-origin updater profile `handheld-layout` for the layout candidate. The preflight verifies the complete v4.8 rollback ZIP, both candidate digests and CRC, and the stock 112-sector geometry. The mocked updater tests cover the full app-origin handoff and transfer. The older `handheld` profile is for the text checkpoint.

1. Start in normal operation and use the checked app-origin handoff with KATA released. Record handoff acknowledgment `01 00 00 00 05`, DSP destination `0x00000000`, and final acknowledgment `00 14 04 00` before ordinary Reset. Check that the LCD shows **Activities**, readable tiles, and the lime focus at Watch TV.
2. Press Right to focus Room controls, then OK. In Room controls, move Right to Climate and press OK. Physical Back should restore Climate focus, then Room controls focus on a second Back. At Activities, Left returns focus to Watch TV.
3. Hold OK to enter Watch TV and release it. Check the four captions over A–D. Expect zero TV frames during entry, hold and release. On the `stock_v48_handheld` Home Assistant profile, bind **Watch TV → A Input** to a disposable action. A fresh A press should produce one `tv / soft_1 / press` and one recorded action. Use a fresh hard Back press to check control `0c` while the mode remains Watch TV.
4. Release the Bluetooth connection while Watch TV is visible and press D. Expect **Activities** with **Watch TV** focused. Reconnection should produce no press report. The action sender keeps no queue. The optional direct listener profile `handheld-tv` can inspect the on-air frames in a separate session from Home Assistant.
