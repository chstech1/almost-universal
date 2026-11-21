# v4.8 native Home and Controls trial

This DSP-only build starts from the exact **LCD CHECK** image that displayed the stock setup page and emitted `DSP:E` on the V06 spare. It uses the stock icon, label, style, layout, redraw, and panel driver. It exposes two local views on that page to validate navigation and pickup-only wake before restoring outbound v1 key reports. [Physical display checkpoint](../dsp-v48-display-check/README.md)

The separately staged Almost Universal splash uses the same native menu underneath. The standalone candidate remains available for direct comparison. [Splash, exact pin, and bench procedure](SPLASH.md)

The approved Almost Universal design also has a separate `--handheld-layout` build. It uses stock LVGL for a two-column cursor grid and aligned Device-mode captions. [Handheld staging and limits](HANDHELD.md)

| View | Visible labels | Key |
| --- | --- | --- |
| Home | **Home**, **A: Controls** | A opens Controls. |
| Controls | **Controls**, **D: Back** | D returns to Home. |

The labels appear in the stock setup-page content area with the stock icon and theme. Holding A on Controls or D on Home leaves that view in place. The candidate has no Home Assistant action or dynamic captions. Other keys and page callbacks use their existing stock paths.

## Stock hook contract

- The stock page creates an icon and then a label in the container held at `0x001ca38c`. The call at `0x2003164f` passes that label in `a10` and its initial text in `a11` to `lv_label_set_text` at `0x2001d554`. The wrapper at `0x2006f90c` supplies the Home text for the expected stock label class, then uses the real setter. The following stock style, sizing, positioning and page-completion calls are intact. Home initialization follows page creation and requires no key event.
- The stock code at `0x20031584–0x2003158f` already registers event 13 on the stock `nodev` group root with `0x001ca384` as user data. The literal at `0x2003145c` now points to `0x2006f940`. The original callback was an empty windowed function. Stock group dispatch at `0x20034f78` passes a 32-bit key by address to the stock event dispatcher at `0x200346fc`. The latter builds the event with code at `+8`, user data at `+0x0c`, and the key parameter at `+0x10`. The handler checks those fields, both stock root pointers, and the live label class `0x2004cf10` before changing the second child through the same stock label setter. It recognizes native A `0x200` and D `0x1000`.
- The stock text setter owns allocation, invalidation and text layout. The callback does not cache the label pointer or keep separate menu state. When stock retains the objects through sleep, they retain their current text. If stock recreates the setup page, the create path initializes Home again. ARM, RES, motion configuration, BSS, input dispatch, redraw timer, flush pointer and panel power paths remain as in the display checkpoint. No new persistent settings writes.

The fixture executes the actual candidate's register and label-call bytes, the real stock group dispatch and event constructor/router, and the real child lookup. It models callback descriptor allocation, label allocation and invalidation, group focus, and class preflight. It checks Home without input, A → Controls, D → Home, repeated and unrelated keys, a missing child, wrong label class, and page recreation. It does not model the native draw buffer, physical focus, or the wake sensor. [Source](menu.c) · [Xtensa fixture](smoke.S)

## Exact package

| Verified item | Value |
| --- | --- |
| ZIP | `WoRWS-v4.8-DSP-NATIVE-MENU.CANDIDATE.zip`, 251,565 bytes |
| ZIP SHA-256 | `450d7aef392d15dd63a5230b96359b45e5a3351996c21156fc551ed0e50ca377` |
| Sole member | `DSP.bin`, 457,176 bytes |
| DSP SHA-256 | `a0fc583373164eff5771a8783324a4e7d09f000addda5fc43b9feeed0e6b45fd` |
| FreqChip CRC | `ce45f0b3` |

Two builds matched byte for byte. The HiFi3 decoder independently decoded all 53 new instructions and resolved the patched `call8` to the label wrapper. Relative to Display Check, six bytes differ at the two hook sites. Added XIP code starts at `0x2006f900` and the member ends at exclusive U6 offset `0x6f9d8`, inside the stock 112 erase sectors. The linker verifies empty added data and BSS sections. The Display Check E/P/F markers and their calls are preserved byte for byte.

```sh
native_build=$(mktemp -d)
python3 -B ununiversal-remote/firmware/dsp-v48-native-menu/build.py \
  artifacts/universal-remote/WoRWS-v4.8-DSP-DISPLAY-CHECK.CANDIDATE.zip \
  "$native_build/native-menu.zip" --smoke \
  --tool-prefix "$HOME/Library/Arduino15/packages/esp32/tools/esp-x32/2507/bin/xtensa-esp32-elf"
cmp "$native_build/native-menu.zip" artifacts/universal-remote/WoRWS-v4.8-DSP-NATIVE-MENU.CANDIDATE.zip
```

## Bench handoff

1. Pin the exact package for the checked normal-service app-origin route. Require handoff ACK `01 00 00 00 05`, destination `0x00000000`, and CRC ACK `00 14 04 00`.
2. Use an ordinary Reset with KATA released and wake as needed. Record **Home**, then A → **Controls**, then D → **Home**. **LCD CHECK** indicates the prior display path is visible but the candidate's initial text is absent. The existing receive-only capture can distinguish app entry, page completion and stock flush as before. [Capture commands and interpretation](../dsp-v48-display-check/README.md#receive-only-capture-on-the-bench-mac)
3. Open **Controls**, leave the remote stationary until the screen goes dark, then pick it up with no key pressed. Record whether the display and native content return, and whether stock kept Controls or recreated Home. Let it sleep again and compare with a separate Down-button wake. This trial is the physical check of both wake paths. Home Assistant action delivery is outside this image.
