"""Build the local native Home/Controls test from the exact v4.8 display checkpoint."""

import argparse
from hashlib import sha256
from pathlib import Path
from struct import pack, pack_into, unpack_from
from subprocess import run
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from zlib import crc32


HERE = Path(__file__).resolve().parent
BASE = 0x20000000
SIM = 0x60000000
EXTENSION = 0x6F900
SET_TEXT_CALL = 0x3164F
KEY_CALLBACK = 0x3145C
FRESH_CALL = 0xFF35
REPORT_CALL = 0x50F4
BSS_START = 0x1E700
MENU_FONT = 0x001CA068
COMPACT_FONT = 0x20060A70
CHECKPOINT_SHA = "2b67114a10c922ea7b2dccd2ed2173cb21c64d613b795b7bc067e19f2def09ad"
DSP_SHA = "5270a15bc27d6a529c2e062db2d3d2699c1de68fda12562e2393d96bae439a6b"
SPLASH_CALLS = {
    "stock_image_create": 0x1C9F4,
    "stock_image_set_source": 0x1CA30,
    "stock_set_position": 0x10C08,
    "stock_add_flag": 0x36250,
    "stock_clear_flag": 0x362B0,
    "stock_timer_create": 0x3FBE0,
    "stock_timer_repeat": 0x41898,
}
ACTION_CALLS = {"stock_normalize": 0x1FEF4, "stock_ipc_send": 0x5E04,
                "stock_active_page": 0x30168, "memset": 0x3FEB0}
TILE_CALLS = {
    "stock_label_create": 0x1D524,
    "stock_set_position": SPLASH_CALLS["stock_set_position"],
    "stock_set_size": 0x11070,
    "stock_add_flag": SPLASH_CALLS["stock_add_flag"],
    "stock_clear_flag": SPLASH_CALLS["stock_clear_flag"],
    "stock_bg_color": 0x3A1B4,
    "stock_bg_opacity": 0x3A1DC,
    "stock_text_color": 0x3A23C,
    "stock_text_font": 0x3A280,
    "stock_text_align": 0x3A2C0,
    "stock_pad_top": 0x3A0E8,
    "stock_radius": 0x3A164,
}


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def compile_c(prefix, work, name, *, splash=False, action=False, handheld=False, tiles=False):
    flags = ["-DSPLASH"] if splash else []
    if action:
        flags.append("-DACTION")
    if handheld:
        flags.append("-DHANDHELD")
    if tiles:
        flags.append("-DHANDHELD_LAYOUT")
    if tiles in ("polish", "color"):
        flags.append("-DHANDHELD_POLISH")
    if tiles == "color":
        flags.append("-DHANDHELD_COLOR")
    call_model = "-mno-longcalls" if (action or handheld) and name != "smoke" else "-mlongcalls"
    run([f"{prefix}-gcc", "-c", "-Os", "-std=c11", "-Wall", "-Wextra", "-Werror",
         "-ffreestanding", "-fno-stack-protector", "-mabi=windowed", "-mtext-section-literals",
         call_model, *flags, "-o", f"{name}.o", HERE / f"{name}.c"], cwd=work, check=True)


def link(prefix, work, sections, *, fixture=False, splash=False, action=False, handheld=False, tiles=False):
    entry = "_start" if fixture else "native_menu_create"
    base = SIM if fixture else BASE
    layout = [f"ENTRY({entry})"]
    if not fixture:
        layout.extend(["stock_nodev = 0x001ca384;", "stock_label_class = 0x2004cf10;",
                       "stock_set_text = 0x2001d554;", "stock_get_child = 0x200412a0;"])
        if splash:
            layout.extend([f"{name} = {BASE + offset:#x};" for name, offset in SPLASH_CALLS.items()])
            layout.extend(["stock_group_send = 0x20034f78;", "stock_image_class = 0x2004ce78;",
                           "splash_state = 0x0018342c;"])
        if action or handheld:
            layout.extend(f"{name} = {BASE + offset:#x};" for name, offset in ACTION_CALLS.items())
            layout.extend(["stock_nodev_name = 0x20060690;", "stock_page_manager = 0x001ca330;"])
        if handheld:
            layout.append("handheld_state = 0x0018342c;")
        if tiles:
            layout.append(f"stock_menu_font = {MENU_FONT:#x};")
            layout.extend(f"{name} = {BASE + offset:#x};" for name, offset in TILE_CALLS.items())
        if tiles in ("polish", "color"):
            layout.append(f"stock_compact_font = {COMPACT_FONT:#x};")
    layout.append("SECTIONS {")
    layout.extend(f"  .{name} {SIM + address:#x} : {{ *(.{name}) }}" for name, address in sections)
    sources = ["handheld"] if handheld else ["menu", "splash"] if splash else ["menu"]
    code = " ".join(f"{name}.o(.literal* .text* .rodata*)" for name in sources)
    layout.append(f"  .extension {base + EXTENSION:#x} : {{ {code} }}")
    if fixture:
        layout.append("  .fixture 0x60075000 : { smoke.o(.literal* .text* .rodata*) }")
    layout.extend(["  .data : { *(.data* .sdata*) }", "  .bss : { *(.bss* .sbss* COMMON) }"])
    if not fixture:
        layout.append('  ASSERT(SIZEOF(.data) == 0 && SIZEOF(.bss) == 0, "unexpected menu RAM")')
    layout.extend(["  /DISCARD/ : { *(.comment .note* .eh_frame*) }", "}"])
    (work / "layout.ld").write_text("\n".join(layout))
    objects = [f"{name}.o" for name in sources]
    if fixture:
        objects.extend(["start.o", "smoke.o"])
    run([f"{prefix}-ld", "-EL", "--no-relax", "-T", "layout.ld", "-o", "menu.elf", *objects],
        cwd=work, check=True)
    symbols = run([f"{prefix}-nm", "--defined-only", "menu.elf"], cwd=work, check=True,
                  capture_output=True, text=True).stdout
    return {name: int(address, 16) for address, _, name in (line.split() for line in symbols.splitlines())}


def patch_call(candidate, offset, expected, target):
    require(candidate[offset:offset + 3] == bytes.fromhex(expected), f"Unexpected call at {offset:#x}")
    displacement = target - ((BASE + offset) & ~3) - 4
    require(displacement % 4 == 0 and -0x80000 <= displacement < 0x80000, f"Invalid call8 at {offset:#x}")
    instruction = (((displacement // 4) & 0x3FFFF) << 6) | 0x25
    candidate[offset:offset + 3] = instruction.to_bytes(3, "little")


def build(prefix, work, reference, *, splash=False, action=False, handheld=False, tiles=False):
    compile_c(prefix, work, "handheld" if handheld else "menu",
              splash=splash, action=action, handheld=handheld, tiles=tiles)
    if splash:
        compile_c(prefix, work, "splash", splash=True, action=action)
    if tiles:
        require(unpack_from("<I", reference, 0x1847C)[0] == MENU_FONT,
                "Expected the stock nodev label font")
    if tiles in ("polish", "color"):
        require(unpack_from("<I", reference, 0x195DC)[0] == COMPACT_FONT and
                unpack_from("<HH", reference, COMPACT_FONT - BASE + 8) == (16, 3),
                "Expected the stock default font with a 16-pixel line height")
    symbols = link(prefix, work, (), splash=splash, action=action, handheld=handheld, tiles=tiles)
    run([f"{prefix}-objcopy", "-O", "binary", "-j", ".extension", "menu.elf", "extension.bin"],
        cwd=work, check=True)
    extension = (work / "extension.bin").read_bytes()
    require(unpack_from("<I", reference, KEY_CALLBACK)[0] == 0x20040FB0, "Unexpected stock key callback")
    candidate = bytearray(reference)
    patch_call(candidate, SET_TEXT_CALL, "65f0eb", symbols["native_menu_create"])
    if not handheld:
        pack_into("<I", candidate, KEY_CALLBACK, symbols["native_menu_key"])
    if splash:
        patch_call(candidate, FRESH_CALL, "250425", symbols["splash_fresh_group_send"])
    if splash or handheld:
        data_end, = unpack_from("<I", reference, 0x1E6E4)
        bss_start, = unpack_from("<I", reference, BSS_START)
        require((data_end, bss_start) == (0x18342C, 0x183430), "Expected one aligned word before stock BSS")
        pack_into("<I", candidate, BSS_START, data_end)
    if action:
        patch_call(candidate, REPORT_CALL, "e5df1a", symbols["menu_action_report"])
    if handheld:
        patch_call(candidate, REPORT_CALL, "e5df1a", symbols["handheld_report"])
    require(len(candidate) <= EXTENSION and EXTENSION + len(extension) <= 0x70000,
            f"Candidate end {EXTENSION + len(extension):#x} exceeded the DSP erase boundary 0x70000")
    candidate.extend(b"\xff" * (EXTENSION - len(candidate)) + extension)
    return candidate, symbols


def smoke(prefix, work, candidate, symbols, *, splash=False, action=False, handheld=False, tiles=False):
    callback, = unpack_from("<I", candidate, KEY_CALLBACK)
    files = {
        "callback": pack("<I", callback - BASE + SIM),
        "registration": candidate[0x31584:0x31590],
        "label_call": candidate[SET_TEXT_CALL:SET_TEXT_CALL + 3],
        "group_send": candidate[0x34F78:0x34F99],
        "event_dispatch": candidate[0x346FC:0x34814],
        "child_getter": candidate[0x412A0:0x412C1],
    }
    if splash:
        files["fresh_call"] = candidate[FRESH_CALL:FRESH_CALL + 3]
    if action or handheld:
        files["report_dispatch"] = candidate[0x50E8:0x50FC]
    if tiles == "color":
        require(unpack_from("<II", candidate, 0x6228) == (0x9B6E8, 0x9B734),
                "Expected shared stock panel window and byte-writer call targets")
        files["panel_fill"] = candidate[0x6230:0x62B3]
        files["panel_flush_tail"] = candidate[0xF76A:0xF776]
        files["stock_color_default"] = candidate[0x3F514:0x3F5FE]
    for name, data in files.items():
        (work / f"{name}.bin").write_bytes(data)
    defines = ["--defsym", "SPLASH=1"] if splash else []
    if action or handheld:
        defines.extend(["--defsym", "REPORT=1"])
    if tiles:
        defines.extend(["--defsym", "TILES=1"])
    if tiles == "color":
        defines.extend(["--defsym", "COLOR=1"])
    run([f"{prefix}-as", "--no-transform", *defines, "-o", "start.o", HERE / "smoke.S"], cwd=work, check=True)
    compile_c(prefix, work, "smoke", splash=splash, action=action, handheld=handheld, tiles=tiles)
    sections = [
        ("vectors", 0), ("start", 0x400), ("registration_literal", KEY_CALLBACK),
        ("registration", 0x31581), ("label_call", SET_TEXT_CALL - 7),
        ("group_send", 0x34F78), ("child_getter", 0x412A0),
        ("label_setter", 0x1D554), ("event_register", 0x34840),
        ("event_literals", 0x346F0), ("event_dispatch", 0x346FC), ("group_focus", 0x410A8),
        ("event_context", 0xFC7C), ("class_preflight", 0x41010), ("event_bubble", 0x410D0),
        ("bubble_flag", 0x5108),
    ]
    entries = ["native_menu_create"]
    if not handheld:
        entries.append("native_menu_key")
    if splash:
        sections.extend((name, offset) for name, offset in SPLASH_CALLS.items())
        sections.append(("fresh_call", FRESH_CALL - 7))
        entries.append("splash_fresh_group_send")
    if action or handheld:
        sections.extend((name, offset) for name, offset in ACTION_CALLS.items())
        sections.extend([("report_dispatch", 0x50E8), ("stock_reset_idle", 0x22D94)])
        entries.append("handheld_report" if handheld else "menu_action_report")
    if tiles:
        sections.extend(TILE_CALLS.items())
    if tiles == "color":
        sections.extend([("panel_alloc_literals", 0x47B8), ("panel_io_literals", 0x6220),
                         ("panel_fill", 0x6230), ("panel_flush_tail", 0xF76A - 7),
                         ("stock_color_default", 0x3F514)])
    test_symbols = link(prefix, work, sections, fixture=True, splash=splash,
                        action=action, handheld=handheld, tiles=tiles)
    for name in entries:
        require(test_symbols[name] - SIM == symbols[name] - BASE,
                f"Fixture changed the address of {name}")
    run(["qemu-system-xtensa", "-M", "sim", "-cpu", "de212", "-m", "16M", "-display", "none",
         "-monitor", "none", "-serial", "none", "-semihosting", "-device", "loader,file=menu.elf,cpu-num=0"],
        cwd=work, check=True, timeout=10)
    if handheld:
        print("Xtensa handheld native label, local navigation, and v1 packet fixture passed")
    else:
        print("Xtensa native label, key registration, dispatch and child lookup fixture passed")
    if splash:
        print("Xtensa splash one-shot, early dismissal and wake-state fixture passed")
    if action:
        print("Xtensa stock report and Controls A v1 packet fixture passed")
    if tiles == "color":
        print("Xtensa exact stock fill and flush instructions agreed on the palette bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tool-prefix", default="xtensa-esp32-elf")
    parser.add_argument("--smoke", action="store_true")
    variants = parser.add_mutually_exclusive_group()
    variants.add_argument("--splash", action="store_true", help="add the native Almost Universal startup splash")
    variants.add_argument("--action", action="store_true", help="include splash and the Controls A v1 Bluetooth action")
    variants.add_argument("--handheld", action="store_true", help="stage the local cursor and TV mode over stock v4.8")
    variants.add_argument("--handheld-layout", action="store_true", help="add native grid tiles and aligned TV captions")
    variants.add_argument("--handheld-polish", action="store_true", help="stage the spacing and type pass offline")
    variants.add_argument("--handheld-color", action="store_true", help="encode polished colors for stock panel byte order")
    args = parser.parse_args()
    splash = args.splash or args.action
    tiles = False
    if args.handheld_color:
        tiles = "color"
    elif args.handheld_polish:
        tiles = "polish"
    elif args.handheld_layout:
        tiles = "layout"
    handheld = args.handheld or bool(tiles)
    prefix = str(Path(args.tool_prefix).expanduser().resolve()) if "/" in args.tool_prefix else args.tool_prefix
    require(sha256(args.checkpoint.read_bytes()).hexdigest() == CHECKPOINT_SHA, "Expected the exact display checkpoint ZIP")
    with ZipFile(args.checkpoint) as archive:
        reference = archive.read("DSP.bin")
    require(sha256(reference).hexdigest() == DSP_SHA, "Expected the exact display checkpoint DSP.bin")

    with TemporaryDirectory(prefix="native-menu-") as temp:
        work = Path(temp)
        candidate, symbols = build(prefix, work, reference, splash=splash,
                                   action=args.action, handheld=handheld, tiles=tiles)
        if args.smoke:
            smoke(prefix, work, candidate, symbols, splash=splash,
                  action=args.action, handheld=handheld, tiles=tiles)
    with ZipFile(args.output, "x") as archive:
        archive.writestr(ZipInfo("DSP.bin"), candidate, compress_type=ZIP_DEFLATED)
    with ZipFile(args.output) as archive:
        require(archive.namelist() == ["DSP.bin"] and archive.read("DSP.bin") == candidate, "Unexpected ZIP contents")
    print(f"DSP.bin {len(candidate)} bytes, SHA-256 {sha256(candidate).hexdigest()}, "
          f"FreqChip CRC {crc32(candidate, 0xFFFFFFFF):08x}")
    print(f"ZIP SHA-256 {sha256(args.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
