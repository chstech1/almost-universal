"""Build the v4.8 DSP-only stock display checkpoint."""

import argparse
from hashlib import sha256
from pathlib import Path
from struct import pack_into, unpack_from
from subprocess import run
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from zlib import crc32


HERE = Path(__file__).resolve().parent
BASE = 0x20000000
SIM_BASE = 0x60000000
EXTENSION = 0x6F874
UART = 0x50010000
SIM_UART = 0x60070000
RETENTION_WORD = 0x18342C
LABEL = 0x5F6E0
STOCK_SHA = "72ff3017d07537e000925babafc5f27ed1b9c0e0fe9d52cdac819e1b677adb45"
HOOKS = {
    "entry": (0x1FC4B, bytes.fromhex("f02000")),
    "page": (0x3166D, bytes.fromhex("25c404")),
    "flush": (0x0F797, bytes.fromhex("e552f5")),
}
STOCK_CALLEES = {"stock_clear_page_flag": 0x362B0, "stock_report_versions": 0x4CC4}


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def link(prefix, work, source, entry, sections, symbols=(), *, retention=False):
    (work / "layout.ld").write_text("\n".join([
        f"ENTRY({entry})", *[f"{name} = {address:#x};" for name, address in symbols],
        "SECTIONS {", *[f"  .{name} {address:#x} : {{ *(.{name}) }}" for name, address in sections],
        "}",
    ]))
    defines = ["--defsym", "RETENTION=1"] if retention else []
    run([f"{prefix}-as", "--no-transform", *defines, "-o", "code.o", HERE / source], cwd=work, check=True)
    run([f"{prefix}-ld", "-EL", "--no-relax", "-T", "layout.ld", "-o", "code.elf", "code.o"],
        cwd=work, check=True)


def build(prefix, work, stock, *, retention=False):
    sections = [(f"{name}_patch", BASE + offset) for name, (offset, _) in HOOKS.items()]
    sections.append(("extension", BASE + EXTENSION))
    symbols = [(name, BASE + offset) for name, offset in STOCK_CALLEES.items()]
    if retention:
        data_end, = unpack_from("<I", stock, 0x1E6E4)
        bss_start, = unpack_from("<I", stock, 0x1E700)
        require((data_end, bss_start) == (RETENTION_WORD, RETENTION_WORD + 4),
                "Expected one aligned RAM word between stock data and BSS")
        symbols.append(("retention_word", RETENTION_WORD))
    link(prefix, work, "checkpoints.S", "mark_entry", sections, [("uart_base", UART), *symbols],
         retention=retention)
    for name, _ in sections:
        run([f"{prefix}-objcopy", "-O", "binary", "-j", f".{name}", "code.elf", name], cwd=work, check=True)

    candidate = bytearray(stock)
    for name, (offset, original) in HOOKS.items():
        patch = (work / f"{name}_patch").read_bytes()
        instruction = int.from_bytes(patch, "little", signed=True)
        target = ((BASE + offset) & ~3) + 4 + 4 * (instruction >> 6)
        require(candidate[offset:offset + 3] == original and len(patch) == 3
                and instruction & 0x3F == 0x25 and BASE + EXTENSION + 16 <= target < BASE + 0x70000,
                f"Unexpected {name} hook")
        candidate[offset:offset + 3] = patch

    require(unpack_from("<I", stock, 0x5E194)[0] == BASE + LABEL
            and stock[LABEL:LABEL + 9] == b"No device", "Unexpected v4.8 setup label")
    candidate[LABEL:LABEL + 9] = b"WAKE TEST" if retention else b"LCD CHECK"
    extension = (work / "extension").read_bytes()
    uart, *messages = unpack_from("<4I", extension)
    require(uart == UART, "Unexpected UART address")
    stages = b"EPF"
    if retention:
        cookie_address, cookie, retained_message = unpack_from("<3I", extension, 16)
        require(cookie_address == RETENTION_WORD and cookie == 0x57363852, "Unexpected RAM probe literals")
        messages.append(retained_message)
        stages += b"R"
    for message, stage in zip(messages, stages):
        index = message - BASE - EXTENSION
        require(index >= 16 and extension[index:index + 7] == b"\r\nDSP:" + bytes([stage]),
                "Unexpected UART message")
    candidate.extend(b"\xff" + extension)
    require(len(candidate) <= 0x70000, "Candidate crossed the stock 112-sector erase boundary")
    return candidate


def smoke(prefix, work, candidate, *, retention=False):
    entry_offset, _ = HOOKS["entry"]
    (work / "entry.bin").write_bytes(candidate[entry_offset - 3:entry_offset + 6])
    for name in ("page", "flush"):
        offset, _ = HOOKS[name]
        (work / f"{name}.bin").write_bytes(candidate[offset:offset + 5])
    extension = bytearray(candidate[EXTENSION:])
    _, *messages = unpack_from("<4I", extension)
    pack_into("<4I", extension, 0, SIM_UART, *(address + SIM_BASE - BASE for address in messages))
    if retention:
        retained_message, = unpack_from("<I", extension, 24)
        pack_into("<I", extension, 16, SIM_UART + 36)
        pack_into("<I", extension, 24, retained_message + SIM_BASE - BASE)
    (work / "extension.bin").write_bytes(extension)
    sections = [("start", SIM_BASE), ("entry", SIM_BASE + entry_offset - 3),
                ("relocate", SIM_BASE + 0x1E710), ("extension", SIM_BASE + EXTENSION), ("data", SIM_UART)]
    sections.extend((name, SIM_BASE + HOOKS[name][0] - 7) for name in ("page", "flush"))
    sections.extend((name, SIM_BASE + offset - 4) for name, offset in STOCK_CALLEES.items())
    link(prefix, work, "smoke.S", "_start", sections, retention=retention)
    run(["qemu-system-xtensa", "-M", "sim", "-cpu", "de212", "-m", "16M", "-display", "none",
         "-monitor", "none", "-serial", "none", "-semihosting", "-device", "loader,file=code.elf,cpu-num=0"],
        cwd=work, check=True, timeout=10)
    print("Xtensa checkpoint fixture passed")
    if retention:
        print("Xtensa RAM-cookie miss, hit, and corrupted-cookie checks passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tool-prefix", default="xtensa-esp32-elf")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--retention", action="store_true", help="report a pre-relocation RAM cookie")
    args = parser.parse_args()
    prefix = str(Path(args.tool_prefix).expanduser().resolve()) if "/" in args.tool_prefix else args.tool_prefix
    with ZipFile(args.stock) as archive:
        stock = archive.read("DSP.bin")
    require(sha256(stock).hexdigest() == STOCK_SHA and len(stock) == EXTENSION - 1,
            "Expected the exact stock v4.8 DSP.bin")
    with TemporaryDirectory(prefix="display-check-") as temp:
        work = Path(temp)
        candidate = build(prefix, work, stock, retention=args.retention)
        if args.smoke:
            smoke(prefix, work, candidate, retention=args.retention)
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
