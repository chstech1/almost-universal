"""Record bytes from the receive-only DSP_TX connection as JSON lines."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("log", type=Path)
    parser.add_argument("--baud", type=int, choices=(115200, 921600), default=115200)
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    with serial.Serial(port=None, baudrate=args.baud, bytesize=8, parity="N", stopbits=1,
                       xonxoff=False, rtscts=False, dsrdtr=False, timeout=0.2, exclusive=True) as port, \
            args.log.open("x", buffering=1) as log:
        port.port = args.port
        port.dtr = port.rts = False
        port.open()
        print(f"Receive-only capture ready on {args.port} at {args.baud} 8N1", flush=True)
        deadline = monotonic() + args.seconds
        while monotonic() < deadline:
            data = port.read(max(1, min(port.in_waiting, 4096)))
            if data:
                utc = datetime.now(timezone.utc).isoformat()
                log.write(json.dumps({"utc": utc, "hex": data.hex()}) + "\n")
                print(f"{utc} {len(data)} bytes {data[:90]!r}", flush=True)


if __name__ == "__main__":
    main()
