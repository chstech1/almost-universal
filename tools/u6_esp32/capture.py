import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from zlib import crc32

import serial

CHIP_ID = 0x5E4018
MIB = 1024 * 1024
READS = {"sample": (b"b", 0, 4096), "known": (b"c", 0x6000, 16384), "dump": (b"r", 0, 16 * MIB)}
COMMANDS = {"ready": b"?", "settings": b"g", "id": b"i", "observe": b"v"}
HEADER = re.compile(rb"@U6 ([A-Z_]+) (\d+) (\d+) (\d+) ([0-9a-fA-F]{8})\n\Z")


class FrameParser:
    def __init__(self, on_unframed=None, on_bad_frame=None):
        self.buffer = bytearray()
        self.synchronized = False
        self.on_unframed = on_unframed
        self.on_bad_frame = on_bad_frame

    def feed(self, incoming):
        self.buffer.extend(incoming)
        while (newline := self.buffer.find(b"\n")) >= 0:
            header_length = newline + 1
            match = HEADER.search(self.buffer[:header_length])
            if match is None:
                if self.synchronized and self.on_unframed is None:
                    raise ValueError("Invalid header after stream synchronization")
                if self.on_unframed is not None:
                    self.on_unframed(bytes(self.buffer[:header_length]))
                del self.buffer[:header_length]
                continue

            kind, timestamp, value, length, checksum = match.groups()
            length = int(length)
            if length > 4096:
                raise ValueError(f"Frame length {length} exceeds the protocol limit")
            if len(self.buffer) < header_length + length:
                break

            payload = bytes(self.buffer[header_length:header_length + length])
            del self.buffer[:header_length + length]
            if crc32(payload) != int(checksum, 16):
                if self.on_bad_frame is None:
                    raise ValueError("USB frame CRC mismatch")
                self.on_bad_frame(f"CRC mismatch at 0x{int(value):06X}")
                continue
            self.synchronized = True
            yield kind.decode(), int(timestamp), int(value), payload

        if len(self.buffer) > 4096 + 128:
            if self.on_unframed is None:
                raise ValueError("Unterminated frame")
            # Keep room for a split header while discarding payload whose header was lost.
            self.on_unframed(bytes(self.buffer[:-128]))
            del self.buffer[:-128]


def open_serial(name):
    port = serial.Serial(port=None, baudrate=460800, timeout=0.15, write_timeout=1)
    port.port = name
    port.dtr = port.rts = False
    port.open()
    return port


def record_frame(timeline, kind, timestamp, value, payload):
    record = {"kind": kind, "esp_us": timestamp, "value": value, "length": len(payload)}
    if kind == "LOG":
        record["text"] = payload.decode("utf-8", errors="replace")
        record["hex"] = payload.hex()
    elif kind == "BUS":
        record.update(json.loads(payload))
    if timeline:
        timeline.write(json.dumps(record) + "\n")
    return record


def make_parser(timeline, tolerate_damage):
    def transport_error(detail):
        if timeline:
            timeline.write(json.dumps({"kind": "USB_RECOVERY", "detail": detail}) + "\n")

    return FrameParser(
        on_unframed=(lambda line: transport_error(f"Unframed bytes: {len(line)}")) if tolerate_damage else None,
        on_bad_frame=transport_error if tolerate_damage else None,
    )


def stop_capture(port, parser, timeline):
    port.write(b"x")
    if parser is None:
        return
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        for frame in parser.feed(port.read(4096)):
            record_frame(timeline, *frame)
            if frame[0] in ("ABORT", "DONE", "READ_ERROR", "USB_ERROR", "PASSIVE_DONE", "MONITOR_ERROR"):
                print("ESP32 stopped the capture", flush=True)
                return
    print("Stop sent, ESP32 acknowledgement not received", flush=True)


def capture(args, command, start, length, *, port=None, timeline=None, parser=None, stop_requested=None):
    live = port is not None
    partial = args.out.with_name(args.out.name + ".part") if args.out else None
    acknowledged = args.mode in ("section", "dump", "range")
    idle_timeout = 60 if live and length else 8
    reading = (bool(length) or args.mode == "observe") and not args.arm
    received = 0
    last_block = None
    digest = sha256()

    with ExitStack() as files:
        if not live:
            port = files.enter_context(open_serial(args.port))
            if args.timeline:
                timeline = files.enter_context(args.timeline.open("x", buffering=1))
            time.sleep(0.35)
        if parser is None:
            parser = make_parser(timeline, acknowledged)
        destination = None
        if args.arm:
            arm_deadline = time.monotonic() + args.arm
            next_probe = time.monotonic()
            streak = 0
            print("Capture armed; waiting for three consecutive correct IDs", flush=True)
        elif command:
            port.write(command)
        idle_deadline = time.monotonic() + idle_timeout
        try:
            while True:
                if stop_requested and stop_requested():
                    if args.mode == "listen":
                        return
                    raise InterruptedError("Capture stopped")
                now = time.monotonic()
                if args.arm and not reading:
                    if now >= arm_deadline:
                        raise TimeoutError("U6 did not return three consecutive correct IDs")
                    if now >= next_probe:
                        port.write(b"i")
                        next_probe = now + 0.5
                incoming = port.read(4096)
                for kind, timestamp, value, payload in parser.feed(incoming):
                    # The ESP32 sends DATA only after a correct ID and waits for
                    # each block's acknowledgement. Recover a lost START from
                    # the CRC-checked first block of the requested range.
                    recovered_start = (kind == "DATA" and acknowledged and reading and destination is None
                                       and value == start and len(payload) == 4096 and length >= 4096)
                    if recovered_start and timeline:
                        timeline.write(json.dumps({"kind": "START", "esp_us": timestamp, "value": start,
                                                   "length": 0, "recovered": True}) + "\n")
                    record = record_frame(timeline, kind, timestamp, value, payload)

                    if kind == "LOG" and (not live or args.mode == "listen"):
                        print(f"[{timestamp / 1_000_000:.6f}] DSP {record['text']!r}", flush=True)
                    if args.mode == "observe":
                        if kind == "PASSIVE_START":
                            print(f"Listening to U6 for {value / 1000:g} seconds", flush=True)
                        elif kind == "BUS":
                            idle_deadline = time.monotonic() + idle_timeout
                            print(f"{value / 1000:5.1f}s  {record['selects']:,} selects, "
                                  f"{record['clocks']:,} clocks while selected, CS={record['cs']}", flush=True)
                        elif kind == "PASSIVE_DONE":
                            reading = False
                            print("Passive U6 observation finished", flush=True)
                            return
                        elif kind in ("READY", "MONITOR_ERROR"):
                            reading = False
                            raise RuntimeError("Passive U6 observation failed")
                    if kind == "READY" and args.mode == "ready":
                        if value != 1:
                            raise RuntimeError("ESP32 booted, but DSP UART initialization failed")
                        print("ESP32 reader ready, DSP UART initialized")
                        return
                    if kind == "SETTINGS" and args.mode == "settings":
                        current = json.loads(payload)
                        print(f"[{timestamp / 1_000_000:.6f}] {json.dumps(current, sort_keys=True)}", flush=True)
                        return current
                    if kind == "ID":
                        print(f"[{timestamp / 1_000_000:.6f}] ID {value:06X}", flush=True)
                        if args.arm and not reading:
                            streak = streak + 1 if value == CHIP_ID else 0
                            if streak == 3:
                                reading = True
                                idle_deadline = time.monotonic() + idle_timeout
                                port.write(command)
                            continue
                        if value != CHIP_ID:
                            reading = False
                            if args.arm and destination is None:
                                streak = 0
                                continue
                            raise RuntimeError("U6 ID did not match 5E4018")
                        if args.mode == "id":
                            return
                    if kind == "START" or recovered_start:
                        if not partial or destination or value != start:
                            raise ValueError("Unexpected flash range")
                        destination = files.enter_context(partial.open("xb"))
                        print(f"Reading {length} bytes from 0x{start:06X}", flush=True)
                        if recovered_start:
                            print("Recovered the start from the first verified block", flush=True)
                    if kind == "READY" and destination:
                        reading = False
                        raise RuntimeError("ESP32 restarted during the capture")
                    if kind == "DATA":
                        if acknowledged and received and value == start + received - 4096:
                            if payload != last_block:
                                raise ValueError("Retransmitted flash block differs from the saved block")
                            port.write(b"a" + (value // 4096).to_bytes(2, "little"))
                            continue
                        if not destination or value != start + received or len(payload) != 4096 or received + len(payload) > length:
                            raise ValueError("Flash data is out of order or outside the requested range")
                        digest.update(payload)
                        destination.write(payload)
                        received += len(payload)
                        if acknowledged:
                            last_block = payload
                            port.write(b"a" + (value // 4096).to_bytes(2, "little"))
                        if received % (256 * 1024) == 0:
                            print(f"Received {received // 1024}/{length // 1024} KiB", flush=True)
                        idle_deadline = time.monotonic() + idle_timeout
                    if kind == "DONE":
                        reading = False
                        if not destination or received != length or value != start + length:
                            raise ValueError("Incomplete flash range")
                        destination.close()
                        os.link(partial, args.out)
                        partial.unlink()
                        print(f"Saved {received} bytes to {args.out}; SHA-256 {digest.hexdigest()}")
                        return
                    if kind in ("READ_ERROR", "BAD_SECTION", "BAD_RANGE", "BAD_SETTING", "ABORT", "USB_ERROR"):
                        reading = False
                        raise RuntimeError(f"{kind} at 0x{value:06X} ({received} bytes captured)")

                if args.mode != "listen" and (not args.arm or reading) and time.monotonic() > idle_deadline:
                    raise TimeoutError("No progress or terminal response from the ESP32")
        finally:
            if reading:
                stop_capture(port, parser if live else None, timeline)


def main():
    cli = argparse.ArgumentParser(description="Capture U6 flash and timestamped DSP UART frames from the ESP32.")
    cli.add_argument("mode", choices=(*COMMANDS, "listen", "section", *READS))
    cli.add_argument("--port", required=True)
    cli.add_argument("--section", type=int, choices=range(16))
    cli.add_argument("--out", type=Path)
    cli.add_argument("--timeline", type=Path)
    cli.add_argument("--arm", type=int, metavar="SECONDS", help="wait for stable U6 identification before reading")
    args = cli.parse_args()

    if args.mode == "section":
        if args.section is None:
            cli.error("section mode needs --section")
        command, start, length = bytes((ord("p"), args.section)), args.section * MIB, MIB
    else:
        command, start, length = READS.get(args.mode, (COMMANDS.get(args.mode), 0, 0))
    if bool(length) != bool(args.out):
        cli.error("--out is required for flash captures and applies only to those modes")
    if args.arm is not None and (args.arm <= 0 or not length):
        cli.error("--arm needs a positive timeout and a flash capture")
    if args.out and (args.out.exists() or args.out.with_name(args.out.name + ".part").exists()):
        cli.error("capture destination already exists")

    try:
        capture(args, command, start, length)
    except (OSError, RuntimeError, ValueError) as error:
        cli.exit(1, f"{error}\n")
    except KeyboardInterrupt:
        cli.exit(130, "Capture interrupted\n")


if __name__ == "__main__":
    main()
