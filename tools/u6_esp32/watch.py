import argparse
import json
from pathlib import Path
import time


DSP_MARKERS = (b"BOOT: start up.", b"freqchip", b"DSP basic function start running.")
DSP_OVERLAP = max(map(len, DSP_MARKERS)) - 1


def watch(path, follow=True):
    received = next_progress = dsp_bytes = 0
    start_address = None
    dsp_tail = b""
    next_dsp = time.monotonic() + 5
    last_id = None
    print("SwitchBot live monitor", flush=True)
    print("Following the ESP32 timeline. Times are seconds since the ESP32 booted.", flush=True)
    with path.open() as source:
        while True:
            position = source.tell()
            line = source.readline()
            if not line.endswith("\n"):
                if not follow:
                    return
                source.seek(position)
                if dsp_bytes and time.monotonic() >= next_dsp:
                    print(f"DSP activity  {dsp_bytes:,} bytes received", flush=True)
                    dsp_bytes = 0
                    next_dsp = time.monotonic() + 5
                time.sleep(0.15)
                continue

            record = json.loads(line)
            kind = record["kind"]
            timestamp = record.get("esp_us")
            prefix = f"{timestamp / 1_000_000:9.3f}s  " if timestamp is not None else ""
            value = record.get("value", 0)
            if kind == "READY":
                status = "ESP32 ready. DSP UART initialized." if value else "DSP UART unavailable."
                print(prefix + status, flush=True)
            elif kind == "SETTINGS":
                print(prefix + "ESP32 settings confirmed", flush=True)
            elif kind == "ID" and value != last_id:
                print(prefix + f"U6 chip ID  {value:06X}", flush=True)
                last_id = value
            elif kind == "PASSIVE_START":
                print(prefix + f"Listening to U6 for {value / 1000:g} seconds", flush=True)
            elif kind == "BUS":
                print(prefix + f"U6 activity  {record['selects']:,} selects, "
                      f"{record['clocks']:,} clocks while selected, CS={record['cs']}", flush=True)
            elif kind == "PASSIVE_DONE":
                print(prefix + "Passive U6 observation finished", flush=True)
            elif kind == "MONITOR_ERROR":
                print(prefix + "Passive U6 observation failed", flush=True)
            elif kind == "START":
                start_address = value
                received, next_progress = 0, 64 * 1024
                print(prefix + f"U6 read started at 0x{value:06X}", flush=True)
            elif kind == "DATA" and start_address is not None and value == start_address + received:
                received += record["length"]
                if received >= next_progress:
                    print(prefix + f"U6 read  {received / 1024:,.0f} KiB received", flush=True)
                    next_progress += 64 * 1024
            elif kind == "LOG":
                payload = bytes.fromhex(record["hex"])
                dsp_bytes += len(payload)
                joined = dsp_tail + payload
                for marker in DSP_MARKERS:
                    offset = joined.find(marker)
                    while offset >= 0:
                        if offset + len(marker) > len(dsp_tail):
                            print(prefix + f"DSP  {marker.decode()}", flush=True)
                        offset = joined.find(marker, offset + len(marker))
                dsp_tail = joined[-DSP_OVERLAP:]
            elif kind == "DONE":
                print(prefix + f"U6 read finished  {received:,} bytes received", flush=True)
                start_address = None
            elif kind in ("ABORT", "READ_ERROR", "USB_ERROR", "BAD_RANGE", "BAD_SETTING", "BAD_SECTION"):
                print(prefix + f"Reader reported {kind} at 0x{value:06X}", flush=True)
            elif kind == "USB_RECOVERY":
                print(f"USB recovery  {record['detail']}", flush=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description="Watch the ESP32 capture timeline.")
    cli.add_argument("timeline", type=Path)
    cli.add_argument("--once", action="store_true")
    args = cli.parse_args()
    watch(args.timeline, not args.once)
