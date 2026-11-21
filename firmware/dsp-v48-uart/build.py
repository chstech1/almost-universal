"""Build the stock-derived DSP entry marker for offline inspection."""

import argparse
from hashlib import sha256
from pathlib import Path
from struct import pack, unpack_from
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from zlib import crc32


HERE = Path(__file__).resolve().parent
BASE = 0x20000000
ENTRY = 0x1FC48
HOOK = ENTRY + 3
EXTENSION = 0x6F874
UART = 0x50010000
SIM_BASE = 0x60000000
SIM_UART = 0x60070000
STOCK_SHA = "72ff3017d07537e000925babafc5f27ed1b9c0e0fe9d52cdac819e1b677adb45"
STOCK_ENTRY = bytes.fromhex("364100 f02000 65acfe")


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def build(prefix, work, stock):
    (work / "marker.ld").write_text(f"""
ENTRY(entry_marker)
uart_base = {UART:#x};
SECTIONS {{
  .entry_patch {BASE + HOOK:#x} : {{ *(.entry_patch) }}
  .uart_extension {BASE + EXTENSION:#x} : {{ *(.uart_extension) }}
}}
""")
    run(f"{prefix}-as", "--no-transform", "-o", "entry.o", HERE / "entry.S", cwd=work)
    run(f"{prefix}-ld", "-EL", "--no-relax", "-T", "marker.ld", "-o", "entry.elf",
        "entry.o", cwd=work)
    for section in (".entry_patch", ".uart_extension"):
        run(f"{prefix}-objcopy", "-O", "binary", "-j", section, "entry.elf", section, cwd=work)

    patch = (work / ".entry_patch").read_bytes()
    extension = (work / ".uart_extension").read_bytes()
    instruction = int.from_bytes(patch, "little", signed=True)
    target = ((BASE + HOOK) & ~3) + 4 + 4 * (instruction >> 6)
    require(len(patch) == 3 and instruction & 0x3F == 0x25
            and target == BASE + EXTENSION + 8, "Unexpected entry call encoding")
    uart, message = unpack_from("<II", extension)
    message_offset = message - BASE - EXTENSION
    require(uart == UART and 8 < message_offset < len(extension)
            and extension[message_offset:] == b"DSP:E\r\n", "Unexpected UART literals or marker")
    candidate = stock[:HOOK] + patch + stock[HOOK + 3:] + b"\0" + extension
    require(candidate[:HOOK] == stock[:HOOK] and candidate[HOOK + 3:len(stock)] == stock[HOOK + 3:]
            and len(candidate) <= 0x70000, "Unexpected stock byte changes or erase footprint")
    return candidate


def smoke(prefix, work, candidate):
    (work / "entry.bin").write_bytes(candidate[ENTRY:ENTRY + len(STOCK_ENTRY)])
    message, = unpack_from("<I", candidate, EXTENSION + 4)
    (work / "extension-sim.bin").write_bytes(
        pack("<II", SIM_UART, message + SIM_BASE - BASE) + candidate[EXTENSION + 8:]
    )
    (work / "smoke.ld").write_text(f"""
ENTRY(_start)
SECTIONS {{
  .start {SIM_BASE:#x} : {{ *(.start) }}
  .init_stub {SIM_BASE + 0x1E710:#x} : {{ *(.init_stub) }}
  .app {SIM_BASE + ENTRY:#x} : {{ *(.app) }}
  .uart_extension {SIM_BASE + EXTENSION:#x} : {{ *(.uart_extension) }}
  .data {SIM_UART:#x} : {{ *(.data) }}
}}
""")
    run(f"{prefix}-as", "--no-transform", "-o", "smoke.o", HERE / "smoke.S", cwd=work)
    run(f"{prefix}-ld", "-EL", "--no-relax", "-T", "smoke.ld", "-o", "smoke.elf",
        "smoke.o", cwd=work)
    run("qemu-system-xtensa", "-M", "sim", "-cpu", "de212", "-m", "16M", "-display", "none",
        "-monitor", "none", "-serial", "none", "-semihosting", "-device",
        "loader,file=smoke.elf,cpu-num=0", cwd=work, timeout=10)
    print("Xtensa smoke passed (idle, busy timeout, divisor access, stock init call)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path, help="vendor v4.8 ZIP")
    parser.add_argument("output", type=Path, help="new DSP-only ZIP for offline checks")
    parser.add_argument("--tool-prefix", default="xtensa-esp32-elf")
    parser.add_argument("--smoke", action="store_true", help="run the offline Xtensa fixture")
    args = parser.parse_args()
    prefix = str(Path(args.tool_prefix).expanduser().resolve()) if "/" in args.tool_prefix else args.tool_prefix

    with ZipFile(args.stock) as archive:
        stock = archive.read("DSP.bin")
    require(sha256(stock).hexdigest() == STOCK_SHA and len(stock) == EXTENSION - 1
            and stock[ENTRY:ENTRY + len(STOCK_ENTRY)] == STOCK_ENTRY, "Expected exact stock v4.8 DSP.bin")

    with TemporaryDirectory(prefix="dsp-v48-entry-") as temp:
        work = Path(temp)
        candidate = build(prefix, work, stock)
        if args.smoke:
            smoke(prefix, work, candidate)

    with ZipFile(args.output, "x") as archive:
        archive.writestr(ZipInfo("DSP.bin"), candidate, compress_type=ZIP_DEFLATED)
    with ZipFile(args.output) as archive:
        require(archive.namelist() == ["DSP.bin"] and archive.read("DSP.bin") == candidate,
                "Unexpected ZIP contents")
    print(f"DSP.bin {len(candidate)} bytes, SHA-256 {sha256(candidate).hexdigest()}, "
          f"FreqChip CRC {crc32(candidate, 0xFFFFFFFF):08x}")
    print(f"ZIP SHA-256 {sha256(args.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
