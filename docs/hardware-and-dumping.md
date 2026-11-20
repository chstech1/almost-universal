# Hardware and flash capture

The bench unit is a SwitchBot Universal Remote W4600000. Its `REMOTEWITHSCREEN` PCB is marked `REV:V06` and dated `20231229`. The regulatory teardown shows an earlier V05 board. [FCC internal-photo exhibit](https://fccid.io/2AKXB-W4600000/Internal-Photos/Internal-Photos-7109180)

| Location | Identification |
| --- | --- |
| U5 | FreqChip FR5086D. The stock images contain Cortex-M Thumb and little-endian Xtensa code. |
| U6 | Zbit `25VQ128ASIG`, a 128 Mbit (16 MiB) SPI NOR chip. The reader observed JEDEC ID `5E 40 18`. [Zbit SPI NOR specifications](https://www.zbitsemi.com/en/display.php?id=17) |
| Eight-hole header | Silkscreen identifies separate DSP, BLE, and APT UART signals. Bench measurements established ground continuity to the USB-C shell, approximately 3.065 V at the marked supply, and approximately 3.387 V at DSP_TX while awake. |

## Board photos

| Button side | Processor and flash | Serial header |
| --- | --- | --- |
| [![Button side of the V06 board](../images/button-side.jpg)](../images/button-side.jpg) | [![Close-up of the FR5086D processor and Zbit flash](../images/processor-and-flash.jpg)](../images/processor-and-flash.jpg) | [![Board revision and the silk-screened UART header](../images/serial-header.jpg)](../images/serial-header.jpg) |

| End of board | Connector detail | Battery and flex connectors | Test pads |
| --- | --- | --- | --- |
| [![U1 and surrounding components](../images/end-of-board.jpg)](../images/end-of-board.jpg) | [![Close-up of U8 and a two-row footprint](../images/connector-detail.jpg)](../images/connector-detail.jpg) | [![Flex connectors and the edge of the battery pouch](../images/connector-and-battery.jpg)](../images/connector-and-battery.jpg) | [![Labeled test pads and connector footprints](../images/test-pads.jpg)](../images/test-pads.jpg) |

## UART observations

The button-side header has this silkscreen layout with USB-C on the left and the IR end on the right. The square through-hole is at the lower right in this orientation.

```text
GND      DSP_RX   DSP_TX   3V3
APT_TX   APT_RX   BLE_TX   BLE_RX
```

A battery-powered remote yielded these DSP messages after a Down press with a receive-only connection at 115200 baud, 8N1. A separate receive-only capture on BLE_TX yielded four repetitions of `freqchip` followed by binary data after reconnecting the battery. APT and the programming interface remain unverified.

```text
BOOT: start up.
freqchipfreqchipfreqchip
DSP basic function start running.
```

## Reading U6

The [ESP32 sketch](../tools/u6_esp32/u6_esp32.ino) is the current reader. It expects a classic ESP32 with an Arduino-ESP32 3.x core and uses only the flash identification and read commands. It verifies each SPI burst against an overlapping read, then sends 4 KiB blocks with a CRC and acknowledgment over USB for long captures. The host tracks ordering, saves interrupted reads as `.part` files, and prints the SHA-256 once a range completes. It can log DSP UART and passively count U6 bus activity between reads. The earlier [ESP8266 reader](../tools/u6_reader/u6_reader.ino) and [activity probe](../tools/u6_activity/u6_activity.ino) record the first bench approach.

| ESP32 GPIO | Bench signal |
| --- | --- |
| GPIO27 | U6 CS# |
| GPIO18 | U6 SCLK |
| GPIO19 | U6 SO / MISO |
| GPIO23 | U6 SI / MOSI |
| GPIO16 | DSP_TX via receive-only UART |
| GND | Common ground |

These are firmware pin assignments. The in-circuit SPI bus can also be driven by the remote. Check signal levels, power source, and bus ownership on your board before driving the bus. The reader defaults to SPI mode 0 at 100 kHz and USB serial at 460800 baud.

With the reader sketch installed on the ESP32 and the serial port identified, `id` checks the chip and `sample` reads the first 4 KiB. Use distinct filenames for independent captures.

```sh
mkdir -p captures
PORT=/dev/cu.usbserial-EXAMPLE
python tools/u6_esp32/capture.py id --port "$PORT"
python tools/u6_esp32/capture.py sample --port "$PORT" --out captures/sample.bin
python tools/u6_esp32/capture.py dump --port "$PORT" --out captures/u6-read-1.bin --timeline captures/u6-read-1.jsonl
```

Use [`live.py`](../tools/u6_esp32/live.py) to keep one connection open for diagnostics, 1 MiB sections, or 4 KiB-aligned address ranges. Run `python tools/u6_esp32/watch.py captures/u6-read-1.jsonl` from another terminal to follow the example capture without opening a second serial connection.

On the v4.6 spare, a fresh ESP32 read matched the first 2,088,960 bytes of an earlier ESP32 capture. The same comparison against the earlier ESP8266 capture found differences. Some USB frames arrived with unrecognized headers. During the long ESP32 read, the host withheld acknowledgment until a valid retransmission arrived. The underlying serial-link fault is still open. A rollback backup requires two independent, byte-identical 16,777,216-byte reads and a verified restore path. Keep dumps and timelines local because they can contain provisioning and personal configuration.
