import argparse
from collections import deque
from contextlib import ExitStack
from pathlib import Path
import os
import select
import shlex
import struct
import sys
import time

from capture import COMMANDS, MIB, READS, capture, make_parser, open_serial, record_frame

SETTINGS = {
    "spi_hz": b"f",
    "spi_mode": b"m",
    "burst_bytes": b"b",
    "read_attempts": b"r",
    "dsp_baud": b"d",
    "ack_timeout_ms": b"t",
    "usb_attempts": b"u",
}
HELP = (
    "settings | set FIELD VALUE | id | observe | sample FILE | known FILE | section INDEX FILE\n"
    "read ADDRESS LENGTH FILE | dump FILE | arm <read command> | stop | quit"
)


class Commands:
    def __init__(self):
        self.lines = deque()
        self.buffer = bytearray()

    def poll(self):
        if not self.lines and select.select([sys.stdin], [], [], 0)[0]:
            data = os.read(sys.stdin.fileno(), 4096)
            if not data:
                return "quit"
            self.buffer.extend(data)
            while (end := self.buffer.find(b"\n")) >= 0:
                self.lines.append(self.buffer[:end].decode().strip())
                del self.buffer[:end + 1]
        return self.lines.popleft() if self.lines else None


def request(line):
    words = shlex.split(line)
    arm = 75 if words and words[0] == "arm" else None
    if arm:
        words.pop(0)
    if not words:
        raise ValueError(HELP)
    mode, *values = words
    start = length = 0
    destination = None

    if mode in COMMANDS and not values:
        command = COMMANDS[mode]
    elif mode == "set" and len(values) == 2 and values[0] in SETTINGS:
        value = int(values[1], 0)
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("Setting value must fit in an unsigned 32-bit integer")
        command = b"k" + SETTINGS[values[0]] + struct.pack("<I", value)
        mode = "settings"
    elif mode in READS and len(values) == 1:
        command, start, length = READS[mode]
        destination = Path(values[0]).expanduser()
    elif mode == "section" and len(values) == 2:
        index = int(values[0], 0)
        if not 0 <= index < 16:
            raise ValueError("Section index must be 0–15")
        command, start, length = bytes((ord("p"), index)), index * MIB, MIB
        destination = Path(values[1]).expanduser()
    elif mode == "read" and len(values) == 3:
        start, length = (int(value, 0) for value in values[:2])
        if start < 0 or length <= 0 or start + length > 16 * MIB or start % 4096 or length % 4096:
            raise ValueError("Read address and length must be 4 KiB aligned and within U6")
        command = b"q" + struct.pack("<II", start, length)
        mode = "range"
        destination = Path(values[2]).expanduser()
    else:
        raise ValueError(HELP)

    if arm and not length:
        raise ValueError("arm requires a flash read")
    if destination:
        if destination.exists() or destination.with_name(destination.name + ".part").exists():
            raise ValueError("Capture destination already exists")
        if not destination.parent.is_dir():
            raise ValueError("Capture directory does not exist")
    return argparse.Namespace(mode=mode, out=destination, arm=arm), command, start, length


def main():
    cli = argparse.ArgumentParser(description="Control the U6 reader over one persistent USB connection.")
    cli.add_argument("--port", required=True)
    cli.add_argument("--timeline", type=Path, required=True)
    cli.add_argument("--resume-timeline", action="store_true",
                     help="open USB without reading, then wait for Enter before resuming the timeline")
    args = cli.parse_args()
    commands = Commands()
    quitting = False

    def stop_requested():
        nonlocal quitting
        line = commands.poll()
        if line in ("stop", "quit"):
            quitting = line == "quit"
            return True
        if line:
            print("Capture active. Use stop before issuing another command.", flush=True)
        return False

    with ExitStack() as session:
        port = session.enter_context(open_serial(args.port))
        if args.resume_timeline:
            print("USB open; waiting for the previous console to close.", flush=True)
            if not sys.stdin.readline():
                return
        timeline = session.enter_context(args.timeline.open("a" if args.resume_timeline else "x", buffering=1))
        parser = make_parser(timeline, True)
        time.sleep(0.35)
        capture(*request("ready"), port=port, timeline=timeline, parser=parser)
        print("Live USB session open. Type help for commands.", flush=True)
        while not quitting:
            line = commands.poll()
            if line == "quit":
                break
            if line == "help":
                print(HELP, flush=True)
            elif line == "stop":
                print("Reader is idle", flush=True)
            elif line:
                try:
                    capture(*request(line), port=port, timeline=timeline, parser=parser,
                            stop_requested=stop_requested)
                except (OSError, RuntimeError, ValueError) as error:
                    print(error, file=sys.stderr, flush=True)
                except KeyboardInterrupt:
                    print("Capture interrupted", file=sys.stderr, flush=True)
            for frame in parser.feed(port.read(4096)):
                record_frame(timeline, *frame)


if __name__ == "__main__":
    main()
