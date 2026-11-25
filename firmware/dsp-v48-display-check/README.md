# v4.8 stock display checkpoint

The first two-screen menu write passed DSP CRC after the normal Bluetooth handoff. A plain Reset and Down produced normal ARM v4.8 and the full 78-byte resident DSP loader trace, with a lit backlight and a blank panel. The previous label and A images rendered through the same update route. The loader trace precedes application entry, and the transfer CRC verifies flash readback. [Two-screen trial and review](../dsp-v48/README.md#bench-handoff)

This checkpoint starts from stock v4.8. It leaves the stock page registration, keypad callback, flush pointer, dirty-region rendering, input dispatch and BSS bounds in place. It changes nine English label bytes to show **LCD CHECK. Please add devices via app.** and adds three one-way UART checkpoints. A visible label rules out a failure of the app-origin route or the stock renderer to display this modified DSP with the resources present during this run. Comparing it to the failed menu isolates the menu-only integration, including its global keypad refresh and flush-buffer replacement. This trial cannot distinguish those two hooks or prove the full menu works.

## Exact image

| File | Size | SHA-256 |
| --- | ---: | --- |
| `artifacts/universal-remote/WoRWS-v4.8-DSP-DISPLAY-CHECK.CANDIDATE.zip` | 251,381 bytes | `2b67114a10c922ea7b2dccd2ed2173cb21c64d613b795b7bc067e19f2def09ad` |
| Sole member `DSP.bin` | 456,953 bytes | `5270a15bc27d6a529c2e062db2d3d2699c1de68fda12562e2393d96bae439a6b` |
| Full stock `WoRWS_freq_app_V48.zip` rollback | 2,583,064 bytes | `dac9677e93d4190dccc25498971ad146fee4d8217b6f866138266c088e4ca44e` |

FreqChip CRC is `548023c7`. The image ends at exclusive U6 offset `0x6f8f9` inside the stock 112 erase sectors. The stock prefix differs by sixteen actual bytes across three instructions and the nine-byte label. The appended code starts at `0x2006f874`. It allocates no static RAM and leaves the stock entry pointer, relocation bounds and resource image intact. Page and flush wrappers call through with the two original arguments and emit only after the callee returns. The UART helper reads the line-control and TX status registers once. It queues seven bytes only with 8N1 and an empty TX FIFO. A busy FIFO or incompatible line-control mode skips TX. The helper never waits, changes the UART configuration, or accesses a settings writer. [Checkpoint source](checkpoints.S)

| Signal | Trigger | Capture |
| --- | --- | --- |
| `DSP:E` | App entry at `0x2001fc4b`, before the original relocation call at `0x2001fc4e`. | **115200 8N1**, the bench-verified resident startup rate. |
| `DSP:P` | The stock `nodev` create path returns from its final flag-clear call at `0x2003166d`, after setting and attaching the setup label. | **921600 8N1**, inferred from the stock app's baud enum 11 and SDK `uart_init`. The post-init rate remains unmeasured on the spare. |
| `DSP:F` | The stock first flush has submitted pixels, called `lv_disp_flush_ready` and sent the guarded version report at `0x2000f797`. | **921600 8N1**, same inference. One report per stock guard lifetime. Visible output is a separate check. |

Each marker is preceded by CRLF. Capture the order observed. A flush for an earlier stock page may precede the `nodev` checkpoint. A warm wake can reuse the existing page and first-flush guard. Quiet UART alone leaves the checkpoint unverified, since the sender skips a busy port and the higher rate needs physical confirmation. [Stock UART route and baud evidence](../dsp-v48-uart/README.md#stock-byte-output-route)

## First trial and motion wake

1. Use the pinned archive with the checked normal-service app-origin route. Confirm `01 00 00 00 05`, DSP destination zero and final CRC response `00 14 04 00`. Keep the full stock rollback at hand. Physical KATA recovery can start a bulk erase on its first OTA command.
2. Arm the 115200 listener before a plain recessed Reset with KATA released. Record the 78-byte loader banner and `DSP:E` if emitted. Wake with Down if needed. Record normal ARM v4.8 and whether **LCD CHECK. Please add devices via app.** is visible.
3. Stop the 115200 listener before opening the same adapter at 921600. Repeat the plain Reset with KATA released and Down if needed. Record `DSP:P`, `DSP:F`, and the visible screen. Neither capture needs a battery disconnect or a change to the DSP_TX wiring.
4. Once the label is visible, leave the spare stationary until the screen goes dark. Pick it up or move it without touching any key and record whether the backlight and the label both return. Let it sleep again, then wake using Down as a separate comparison. A motion wake can redraw or expose retained stock pixels without recreating the page or resetting the first-flush guard.

ARM and the motion sensor configuration stay stock. The DSP initialization/resume function at `0x2003395c`, resume call to `0x20024dc8`, redraw timer and native panel power paths are byte-identical to stock. The stock GUI can reach its label and flush paths without this build passing through an input hook. The fixture verifies wrapper behavior independently of a key. Motion-only wake and a visible redraw remain physical acceptance checks.

## Receive-only capture on the bench Mac

Use SwitchBot **DSP_TX** to the ESP8266 board pin marked **TX** and common ground. Hold ESP8266 **EN** low to use its onboard CP2102 receiver. The remote remains on its battery. The target connection uses only DSP_TX and ground. Verify the existing ESP8266 USB path if cables changed. On the documented bench it was `/dev/cu.usbserial-4`.

From the Switchbot workspace root, use the existing environment with pySerial 3.5. Run each command in its own capture pass, with a fresh output file. Wait for `Receive-only capture ready` before Reset. [Capture source](capture.py)

```sh
display_src=almost-universal/firmware/dsp-v48-display-check
display_logs=$(mktemp -d /tmp/switchbot-display-capture.XXXXXX)
esp8266_port=/dev/cu.usbserial-4

tools/esphome-venv/bin/python -B "$display_src/capture.py" "$esp8266_port" \
  "$display_logs/dsp-115200.jsonl" --baud 115200 --seconds 90

tools/esphome-venv/bin/python -B "$display_src/capture.py" "$esp8266_port" \
  "$display_logs/dsp-921600.jsonl" --baud 921600 --seconds 90
```

## Rebuild offline

```sh
display_build=$(mktemp -d)
python3 -B almost-universal/firmware/dsp-v48-display-check/build.py \
  artifacts/universal-remote/WoRWS_freq_app_V48.zip "$display_build/display-check.zip" \
  --tool-prefix "$HOME/Library/Arduino15/packages/esp32/tools/esp-x32/2507/bin/xtensa-esp32-elf" --smoke
cmp "$display_build/display-check.zip" artifacts/universal-remote/WoRWS-v4.8-DSP-DISPLAY-CHECK.CANDIDATE.zip
```

Two builds matched byte for byte. The HiFi3 decoder independently resolved all three calls and both original callees. The Xtensa fixture uses the patched instructions and appended code with only the UART and message addresses mapped into simulator RAM. It checks marker placement around the original call sequence, the two forwarded arguments and nonblocking return on busy or divisor-access states. The capture script passed a mocked transfer at both rates.

The spare verified the DSP CRC, showed **LCD CHECK**, and emitted `DSP:E` after the 78-byte resident banner at 115200. This is the verified baseline for the native Home/Controls candidate. [Next native menu trial](../dsp-v48-native-menu/README.md)

A separately pinned **WAKE TEST** variant reports a volatile RAM cookie at DSP entry. The display checkpoint rebuild is unchanged. [Wake-retention diagnostic and interpretation](RETENTION.md)
## Splash phase trace

The offline phase trace wraps eight existing calls in the exact splash-enabled stock-operations DSP. The normal checkpoints `DSP:E`, `DSP:P`, and `DSP:F` retain their original instructions. Application phase tags use the inferred **921600 8N1** rate. The independently observed loader and app-entry marker use **115200 8N1**. The hardware app-rate receive path remains unverified.

| UART tags | Call boundary |
| --- | --- |
| `~A` / `~a` | Stock setup label creation at `0x20031633` |
| `~B` / `~b` | Relocated native menu initializer at `0x2003164f` |
| `~C` / `~c` | Crop buffer allocation at `0x2002ca41` |
| `~D` / `~d` | Crop decompression at `0x2002ca55` |
| `~E` / `~e` | Native crop image creation at `0x2002caa1` |
| `~F` / `~f` | Attach the crop-owner delete callback at `0x2002cab3` |
| `~G` / `~g` | Attach the indexed source at `0x2002caba` |
| `~H` / `~h` | Native one-shot timer creation at `0x2002b112` |
| `~!` | Zero return from the preceding value-returning call |

Each complete crop produces `C` through `G` with the corresponding lowercase return tags. These stages repeat for all three crops. The initializer returns with `~b` after the timer setup. The original `DSP:P` follows stock page initialization, and the original `DSP:F` follows panel submission and the first guarded version report. The trace can omit tags if the UART stays busy for its 2,040-read bound or line control differs from 8N1. A missing tag is corroborative only once the app-rate capture works.

From the Switchbot workspace root, build and test offline with the same Xtensa toolchain and QEMU used by the combined build.

```sh
phase_build=$(mktemp -d)
python3 -B almost-universal/firmware/dsp-v48-display-check/build_phase_trace.py \
  artifacts/universal-remote/WoRWS-v4.8-DSP-ALMOST-UNIVERSAL-STOCK-OPS-CONTROL.OFFLINE.zip \
  "$phase_build/trace.OFFLINE.zip" \
  --tool-prefix "$HOME/Library/Arduino15/packages/esp32/tools/esp-x32/2507/bin/xtensa-esp32-elf"
cmp "$phase_build/trace.OFFLINE.zip" \
  artifacts/universal-remote/WoRWS-v4.8-DSP-ALMOST-UNIVERSAL-PHASE-TRACE.OFFLINE.zip
```
