# Stock v4.8 DSP UART checkpoints

The V06 spare produced the same 78-byte resident DSP startup trace on stock v4.8 and on the stock-derived A-button build. The ESP8266 board's CP2102 captured `BOOT: start up.`, three `freqchip` strings, and `DSP basic function start running.` at **115200 8N1**. The A-button run separately verified the working setup screen and one Bluetooth notification per fresh A tap. [Physical milestones](../../docs/first-hardware-milestone.md#current-evidence)

The receive-only connection uses SwitchBot **DSP_TX** to the ESP8266 board pin marked **TX**, with common ground and ESP8266 **EN** held low. On that adapter, the pin marked TX is wired to the CP2102 receiver. The remote uses its own battery. A plain recessed Reset with KATA released, followed by Down to wake the screen, reproduced the trace without a battery disconnect. [V06 board and test points](../../docs/hardware-and-dumping.md)

## Stock byte-output route

- The v4.8 app's printf wrapper at `0x2000f564` uses the formatter at `0x2000f374`. Its output helper at `0x2000f1d4` stores bytes to a supplied buffer, or sends them through `0x0009a7dc` when the buffer is null. The app's byte callback at `0x2001fb94` calls the same target. Both calls load the target from the stock literal at `0x2000f1d0` and pass a zero-extended byte through the windowed `callx8` ABI.
- The FR5080 DSP SDK resident ELF places `uart_putc_noint` at `0x000a27dc` and `uart_init` at `0x000a2654`. Both map to stock call targets with the same `-0x8000` shift seen for two IPC functions. The SDK sender polls line status bit 6 at `0x50010014` until TX is empty, then writes a byte to `0x50010000`. The stock app independently reads the same UART base in its receive routine at `0x2001f8ac`. The SDK sender's wait is unbounded. [DSP SDK revision used for comparison](https://gitee.com/magicedward/fr5080-dsp/tree/775118d34977d4e4c4bc8516bfd0477b69f2d67d)
- The SDK starts the resident UART at 115200 before handing off to the application. The stock app's call at `0x2001fc9f` passes baud enum `0x0b` and the byte callback to `0x0009a654`, the matching `uart_init` target. The SDK defines enum 11 as **921600**. This is the inferred stock application rate. The bench measured the resident trace at 115200. A post-init capture at 921600 remains open.

| Checkpoint | v4.8 stock location and what a marker would establish |
|---|---|
| Application entry | Entry is `0x2001fc48`. A marker at its NOP at `0x2001fc4b` would establish that the loader entered the app before relocation at `0x2001fc4e` and before the stock baud change. |
| Page initialization | A marker after the `0x20033988` call to `0x2003036c` would establish that the page manager returned after display and input setup. The `nodev` page starts at `0x2003146c` and sets its setup label at `0x2003164f`, a more specific future checkpoint. |
| First display flush | The flush callback at `0x2000f724` submits panel window and pixel data and calls `lv_disp_flush_ready` at `0x2000f778`. A marker at the following one-time version-report call at `0x2000f797` would establish completion through the driver, with visible output verified separately. Preserve the original version report and both arguments if instrumenting this call. |

Only the entry marker is implemented. Page and flush checks would need a receiver verified at the application rate. The resident banner establishes loader output. The display and exact A-button Bluetooth notifications establish application behavior independently.

## Offline entry marker

The [entry hook](entry.S) replaces one three-byte NOP with a windowed call and appends 75 bytes including alignment. It checks for the normal 8N1 line-control setting, allows up to 16,384 status reads for an idle FIFO, and writes the seven bytes of `DSP:E\r\n` to the existing UART data register. The SDK's bulk sender uses the same idle check followed by writes within the eight-byte FIFO depth. The marker skips the write if the poll expires or the line-control setting differs. The standard application relocation call and UART initialization run in their original sequence. The marker inherits the loader baud setting and requires no application data or UART configuration writes.

[Build and verification](build.py) checks the stock DSP SHA-256, exact hook target, marker bytes, DSP-only ZIP contents, and the existing `0x70000` erase boundary. The [Xtensa fixture](smoke.S) runs the patched entry prefix and extension against a memory-backed UART and a relocation stub. It checks the final data word on an idle UART, no write on a busy UART or with divisor access enabled, and execution of the original relocation call in each case. The fixture cannot measure baud or model the physical FIFO, pad or reset timing. The marker has never been flashed.

From the repository root, use Python 3.11+, little-endian Xtensa binutils, and QEMU system Xtensa. The local check used Espressif's `esp-x32/2507` toolchain.

```sh
uart_check=$(mktemp -d)
python3 -B firmware/dsp-v48-uart/build.py /path/to/WoRWS_freq_app_V48.zip \
  "$uart_check/WoRWS-v4.8-DSP-UART-ENTRY.OFFLINE.zip" --smoke
```

Pass `--tool-prefix` with the full path ending in `xtensa-esp32-elf` if it is outside `PATH`. The verified DSP member was 456,894 bytes with SHA-256 `104c01608ee6c7bddb611b2429ad7ca456f71eb4ece4c6c1b87cfe1e8f84d9d0` and FreqChip CRC `e6ab8578`. The local ZIP SHA-256 was `af14c561400106caee065d39dc4a1e56ee692d00b826c5ae14636c9dd849c24c`.
