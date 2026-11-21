"""Build a DSP-only fallback-menu candidate from the local stock v4.8 ZIP."""

import argparse
from hashlib import sha256
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent
STOCK_SHA256 = "72ff3017d07537e000925babafc5f27ed1b9c0e0fe9d52cdac819e1b677adb45"
BASE = 0x20000000
EXTENSION = 0x6F874
STOCK_ERASE_END = 0x70000
DISPATCH_CALL = 0x50F4
STOCK_FUNCTIONS = {
    "stock_ipc_send": 0x5E04,
    "stock_flush": 0xF724,
    "stock_keypad": 0xF868,
    "stock_invalidate": 0x12344,
    "stock_normalize": 0x1FEF4,
    "stock_active_page": 0x30168,
    "stock_nodev_event": 0x3146C,
    "memset": 0x3FEB0,
}
RAM = {"menu_state": 0x18342C, "stock_page_manager": 0x1CA330,
       "stock_nodev_object": 0x1CA384}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def compile_c(prefix, source, output):
    run(f"{prefix}-gcc", "-c", "-Os", "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-ffreestanding", "-fno-stack-protector", "-mabi=windowed",
        "-mtext-section-literals", "-mlongcalls", "-o", output, source)


def link(prefix, work, obj, candidate=None):
    testing = candidate is not None
    base = 0x60000000 if testing else BASE
    script = work / "addresses.ld"
    lines = [f"{name} = {addr + (base if testing else 0):#x};"
             for name, addr in RAM.items()]
    if not testing:
        lines.extend(f"{name} = {BASE + addr:#x};" for name, addr in STOCK_FUNCTIONS.items())
    lines.append("SECTIONS {")
    if testing:
        lines.extend(f"  .stub_{name} {base + addr:#x} : {{ *(.stub.{name}) }}"
                     for name, addr in STOCK_FUNCTIONS.items())
        lines.extend([f"  .vectors {base:#x} : {{ *(.vectors) }}",
                      f"  .start {base + 0x400:#x} : {{ *(.start) }}",
                      f"  .dispatch {base + 0x50E8:#x} : {{ *(.dispatch) }}",
                      f"  .process {base + 0x22D94:#x} : {{ *(.process) }}"])
    lines.append(f"  .extension {base + EXTENSION:#x} : {{ *(.literal* .text* .rodata*) }}")
    lines.extend(["  .data : { *(.data* .sdata*) }", "  .bss : { *(.bss* .sbss* COMMON) }",
                  "  ASSERT(SIZEOF(.data) == 0, \"unexpected initialized RAM\")"])
    if not testing:
        lines.append('  ASSERT(SIZEOF(.bss) == 0, "unexpected uninitialized RAM")')
    lines.extend(["  /DISCARD/ : { *(.comment .note* .eh_frame*) }", "}"])
    script.write_text("\n".join(lines))
    inputs = [obj]
    if testing:
        (work / "dispatch.bin").write_bytes(candidate[0x50E8:0x50FC])
        run(f"{prefix}-as", "--no-transform", "-o", "start.o", HERE / "smoke.S", cwd=work)
        compile_c(prefix, HERE / "smoke.c", work / "smoke.o")
        inputs += ["start.o", "smoke.o"]
    elf = work / ("smoke.elf" if testing else "menu.elf")
    run(f"{prefix}-ld", "-EL", "--no-relax", "-T", script, "-o", elf,
        "-e", "_start" if testing else "menu_input", *inputs, cwd=work)
    return elf


def patch_word(image, offset, before, after):
    if struct.unpack_from("<I", image, offset)[0] != before:
        raise ValueError(f"v4.8 word at {offset:#x} changed")
    struct.pack_into("<I", image, offset, after)


def patch(stock, elf, prefix, work):
    symbols = dict((name, int(addr, 16)) for addr, _, name in
                   (line.split() for line in run(f"{prefix}-nm", "--defined-only", elf,
                                                 capture_output=True, text=True).stdout.splitlines()))
    ext = work / "extension.bin"
    run(f"{prefix}-objcopy", "-O", "binary", "-j", ".extension", elf, ext)
    candidate = bytearray(stock)
    if (candidate[DISPATCH_CALL:DISPATCH_CALL + 3] != bytes.fromhex("e5df1a") or
            len(stock) != EXTENSION - 1):
        raise ValueError("Stock input dispatch or DSP length changed")
    origin = ((BASE + DISPATCH_CALL) & ~3) + 4
    displacement = symbols["menu_input"] - origin
    if displacement % 4 or not -0x80000 <= displacement < 0x80000:
        raise ValueError("Input wrapper is out of call8 range")
    instruction = ((displacement // 4 & 0x3FFFF) << 6) | 0x25
    candidate[DISPATCH_CALL:DISPATCH_CALL + 3] = instruction.to_bytes(3, "little")
    for offset, original, replacement in (
        (0xF6E0, "stock_flush", "menu_flush"),
        (0xF7C4, "stock_keypad", "menu_keypad"),
        (0x64874, "stock_nodev_event", "menu_page"),
    ):
        patch_word(candidate, offset, BASE + STOCK_FUNCTIONS[original], symbols[replacement])
    patch_word(candidate, 0x1E700, 0x183430, RAM["menu_state"])
    candidate.extend(b"\xff" + ext.read_bytes())
    if len(candidate) > STOCK_ERASE_END:
        raise ValueError("Build exceeds the stock DSP erase range")
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_v48", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tool-prefix", default="xtensa-esp32-elf")
    parser.add_argument("--smoke", action="store_true", help="test the patched dispatch in QEMU")
    args = parser.parse_args()
    with ZipFile(args.stock_v48) as archive:
        stock = archive.read("DSP.bin")
    if sha256(stock).hexdigest() != STOCK_SHA256:
        parser.error("DSP.bin does not match the stock SwitchBot v4.8 image")

    with TemporaryDirectory() as name:
        work = Path(name)
        obj = work / "menu.o"
        compile_c(args.tool_prefix, HERE / "menu.c", obj)
        elf = link(args.tool_prefix, work, obj)
        candidate = patch(stock, elf, args.tool_prefix, work)
        if args.smoke:
            test = link(args.tool_prefix, work, obj, candidate)
            run("qemu-system-xtensa", "-M", "sim", "-cpu", "de212", "-m", "16M",
                "-display", "none", "-monitor", "none", "-serial", "none", "-semihosting",
                "-device", f"loader,file={test},cpu-num=0", timeout=10)
            print("Xtensa dispatch, input, relay, page and display fixture passed.")

    with ZipFile(args.output, "x") as archive:
        archive.writestr(ZipInfo("DSP.bin"), candidate, compress_type=ZIP_DEFLATED, compresslevel=9)
    print(f"DSP.bin {len(candidate):,} bytes, SHA-256 {sha256(candidate).hexdigest()}")
    print(f"Candidate ZIP {args.output.stat().st_size:,} bytes, SHA-256 {sha256(args.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
