# Stock v4.8 DSP menu candidate

The SwitchBot W4600000 REV V06 candidate adds a two-screen color menu to the retail v4.8 DSP's stock **No Devices** page. The exact staged ZIP passed offline checks and the stock app-origin write, then left the physical panel blank with the backlight on. The next trial uses the smaller stock display checkpoint. [Display checkpoint and wake test](../dsp-v48-display-check/README.md)

The stock-ARM approach keeps the code that hosts SwitchBot's KATA + Reset recovery on the spare. A previous full stock v4.8 recovery restored the working screen and normal Bluetooth response. The replacement ARM prototype has its own Home Assistant Bluetooth service, panel driver, companion scanner, and menu receiver. It has no retail recovery service, and a separate wired ARM restore remains unverified. [Stock recovery history](../../docs/firmware.md#bluetooth-recovery-uploader) · [Replacement ARM design](../v06/README.md)

## Menu and controls

| Screen | Soft A | Soft B | Soft C | Soft D |
|---|---|---|---|---|
| Home | **Controls** → Controls | `–` | `–` | `–` |
| Controls | **Action** → Home Assistant binding | `–` | `–` | **Back** → Home |

The four caption centers are at LCD x coordinates 30, 90, 150 and 210. In Home Assistant, choose the v4.8 versioned stock-ARM transport and bind **Controls → A → Press** to a switch action. The remote displays fixed captions and provides local navigation while Bluetooth is disconnected. Home Assistant stores the action binding. Label or layout updates from Home Assistant to the DSP require an inbound transport. [Packet and configuration evidence](PROTOCOL.md)

Each supported single key initial press reports its source screen, control ID, and the stock input timestamp. Ordinary hard keys report while leaving the local screen unchanged. Soft keys marked `–` also report a press and have no local destination. ON, OFF and KATA stay on their stock paths. The wheel uses its stock path and has no menu or Home Assistant binding here. The hook ignores reports for holds, releases, unknown masks and simultaneous keys. The Home Assistant versioned decoder deduplicates an identical press frame during a connection. [Control IDs and wire format](PROTOCOL.md)

## Binary changes and provenance

| DSP member offset | Original path | Candidate behavior |
|---|---|---|
| `0x50f4` | Ten-byte companion report dispatch calls the stock normalizer. | A `call8` to `0x2006faa8` keeps the normalizer call and relays eligible presses through stock DSP→ARM tag 19. The length check, report pointer in `a10`, and following call to `0x20022d94` are intact. |
| `0xf6e0` | Stock LVGL flush callback at `0x2000f724`. | Wrapper at `0x2006fdd8` paints the requested dirty rectangle in the stock draw buffer while `nodev` is active and calls stock flush with the original driver, area, and pixel pointer. |
| `0xf7c4` | Stock LVGL keypad callback at `0x2000f868`. | Wrapper at `0x2006fb4c` keeps the stock driver and sample arguments and requests a refresh on the LVGL timer thread through `0x20012344`. A null display selects the stock default display. |
| `0x1e700` | Startup clears BSS from `0x00183430`. | Extend the existing word-clear loop down by one aligned word to `0x0018342c`, the end of the initialized RAM copy. Two bytes hold the requested and displayed screen. |
| `0x64874` | Initialized RAM page table maps `nodev` to `0x2003146c`. | Wrapper at `0x2006fa50` passes the original event pointer to the stock callback and tracks create, focus, and destroy using event byte `+8`. The page lookup and live object guard restrict custom display and input to `nodev`. |

The exact rebuild changed thirteen stock bytes and appended 1,785 bytes including alignment. The extension runs from `0x2006f874` to exclusive `0x2006ff6c`. It fits in the original 112 erase sectors (`0x00000–0x6ffff`) with 148 bytes to spare. Startup copies the same initialized RAM and instruction RAM ranges and clears one more aligned word of BSS starting at `0x0018342c`. The two menu bytes occupy that word. The linker verified empty added `.data` and `.bss` sections.

The windowed ABI wrappers each use 32-byte frames. The input wrapper and its `0x330` relay frame use `0x350` bytes before stock callees. The stock DSP chunk sender at `0x20004ba4` has the same `0x330` frame and uses the same IPC copy route. The SDK resident sender copies the payload into shared memory or a private queued copy before returning. The deepest menu renderer chain adds `0xf0` bytes across flush, render, label, and fill. The stock stack high-water mark remains unmeasured.

The custom code writes menu state, keypad samples, draw-buffer pixels, and an outbound IPC packet. It adds no settings writer or inbound command. The keypad wrapper passes through samples containing ON, OFF, or KATA, which occupy bits `0x00380000` of the stock UI key field, and leaves other stock pages untouched. The ZIP has no ARM or RES member and preserves the ARM-hosted KATA + Reset path. The stock OTA handoff still writes its own OTA metadata. [Recovery behavior](../../docs/firmware.md#bluetooth-recovery-uploader)

Local evidence lives under `analysis/universal-remote/v46-custom-fw/` in the Switchbot workspace. Use `input/keys.tsv`, `input/pages.tsv`, `input/evidence.asm`, `display-dsp/display-assembly.txt`, and `arm-res/arm/pseudocode.c` to review the stock key IDs, page registration, renderer, and relay. The stock renderer uses a 240 × 320 RGB565 display and an 80-row draw buffer. The candidate sends high-byte-first RGB565 through that same renderer. Color, panel timing, and screen composition during power transitions still need physical confirmation. [Build source](build.py) · [Firmware source](menu.c)

## Local artifacts

| Artifact under `artifacts/universal-remote/` in the Switchbot workspace | Size | SHA-256 |
|---|---:|---|
| `WoRWS-v4.8-DSP-MENU.CANDIDATE.zip` | 252,202 bytes | `4c210394e449d416adb7515cbdded127280b888d173953099d73b42c3f02b4c3` |
| `DSP.bin` inside the menu ZIP | 458,604 bytes | `c682114cd2541b980ec4b5d49232ef07d906a44984bd0c66f1983fbe3f5ec47d` |
| `WoRWS-v4.8-DSP-A-BLE.CANDIDATE.zip` | 251,343 bytes | `fae96b9b43e8917b81f0a56ffcc4a2fa305e0b2d07ecdc2c2422990c6e975fff` |
| Original `WoRWS_freq_app_V48.zip` | 2,583,064 bytes | `dac9677e93d4190dccc25498971ad146fee4d8217b6f866138266c088e4ca44e` |

The stock ZIP contains `DSP.bin` (456,819 bytes), `ARM.bin` (209,212 bytes), and `RES.bin` (4,955,264 bytes). The stock DSP SHA-256 is `72ff3017d07537e000925babafc5f27ed1b9c0e0fe9d52cdac819e1b677adb45`. The menu candidate's FreqChip CRC is `0cf9bad6`. `worws_ota.py inspect` identifies vendor stock packages by hash. The private app-origin bench harness has a pinned `--profile menu` for this ZIP. Use the verified stock archive for rollback. [Stock package manifest](../../docs/SHA256SUMS)

## Rebuild and verify offline

From the Switchbot workspace root, use Python 3.11, the Espressif `esp-x32/2507` Xtensa little-endian toolchain, and QEMU 11.1.1. Set `--tool-prefix` to your own toolchain location if needed.

```sh
menu_build=$(mktemp -d)
menu_src=ununiversal-remote/firmware/dsp-v48
python3 -B "$menu_src/build.py" artifacts/universal-remote/WoRWS_freq_app_V48.zip \
  "$menu_build/menu.zip" --smoke \
  --tool-prefix "$HOME/Library/Arduino15/packages/esp32/tools/esp-x32/2507/bin/xtensa-esp32-elf"
cmp "$menu_build/menu.zip" artifacts/universal-remote/WoRWS-v4.8-DSP-MENU.CANDIDATE.zip
python3 -B worws_ota.py inspect "$menu_build/menu.zip"
cc -std=c11 -O2 -Wall -Wextra -Werror -fsanitize=address,undefined \
  "$menu_src/menu.c" "$menu_src/smoke.c" -o "$menu_build/preview"
"$menu_build/preview" "$menu_build/home.ppm" "$menu_build/controls.ppm"
```

Two independent builds matched byte for byte. QEMU runs the patched stock dispatch bytes and the compiled menu code linked against stock-service stubs. The fixture verifies invalid input length, all 19 mapped key positions including the three reserved positions, both local transitions, hold/release, chords, wheel-only input, packet bytes and relay padding. The fixture models loss while disconnected and zero replay after reconnect. It also checks dirty-region clipping and the stock keypad and flush arguments on the upgrade path. The native macOS fixture passed AddressSanitizer and UBSan and produced both screen previews from the same renderer. These tests use simulated transport and display output. [Xtensa entry](smoke.S) · [Behavior tests and preview](smoke.c)

## Bench handoff

The first A-marker run entered through KATA + Reset, received a DSP CRC acknowledgment, then showed a blank backlit panel. The full stock restore brought back the display. The later app-origin runs each wrote only the DSP. The first showed **DSP ready**. The second ran the original A-marker image, showed the working setup screen and 78-byte resident DSP startup trace, and delivered two exact BLE markers for two fresh A presses. That retry physically verified XIP execution from the same appended sector the menu uses. [Stock recovery and DSP trial history](../../docs/firmware.md#dsp-only-bench-history)

The menu trial reported the exact app handoff ACK `01 00 00 00 05`, DSP destination zero, and final CRC ACK `00 14 04 00`. After Reset and Down it reproduced the full 78-byte DSP loader trace and normal ARM v4.8 at 95% battery, but the panel stayed blank. CRC and the resident trace leave the app's progress unobserved.

The offline review decoded all 477 appended instructions with the HiFi3 decoder and checked that the page table entry lands in the copied RAM interval. The BSS edit adds one word at the end of the initialized copy, and the stock clear loop stops at its original end. No mismatch surfaced in those checks. The emulator uses a synthetic `nodev` page and stubs for keypad, default-display invalidation, and panel flush. It leaves their real callback timing and pixel-buffer behavior untested. The global keypad hook can queue a full-screen refresh before the first menu draw, and the flush hook replaces the stock pixels for every eligible rectangle. Those are the highest-risk integrations. The failure does not yet identify a specific hook.

The next candidate reinstates the stock driver pointers, refresh path and pixel writes while adding UART checkpoints and the visible **LCD CHECK** label. Resume two-screen navigation and outbound v1 tests after isolating the blank panel. Include independent pickup-only and Down-button wakes after confirmed sleep. [Next candidate and capture plan](../dsp-v48-display-check/README.md) · [Physical milestone](../../docs/first-hardware-milestone.md)
