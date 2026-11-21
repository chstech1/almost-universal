"""Build a tail-only UART phase tracer from the exact v4.8 stock-operations DSP."""

import argparse
from hashlib import sha256
from pathlib import Path
from struct import pack
from subprocess import TimeoutExpired, run
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from zlib import crc32


HERE = Path(__file__).resolve().parent
XIP = 0x20000000
SIM = 0x60000000
UART = 0x50010000
SIM_UART = 0x60071000
TAIL = 0x6FF2C
LIMIT = 0x70000
SOURCE_ZIP_SHA = "9e2c5dfd15a6376a1d2b16754db5942615dd838d366fdcf23e472b91846407a4"
SOURCE_DSP_SHA = "a2ab84a42622850d866f86ab26825e5eea0fd94a6514d1ce1bafffde05d2645e"

# Call sites, exact instructions, and called entries in the pinned image.
PHASES = (
    ("label", 0x31633, "25efeb", "stock_label_create", 0x1D524),
    ("menu", 0x3164F, "259ff9", "menu_create", 0x2B040),
    ("alloc", 0x2CA41, "257412", "crop_alloc", 0x3F184),
    ("decode", 0x2CA55, "e53bf4", "crop_decode", 0x20E14),
    ("image", 0x2CAA1, "25f5ef", "crop_image", 0x1C9F4),
    ("event", 0x2CAB3, "e5d807", "crop_event", 0x34840),
    ("source", 0x2CABA, "65f7ef", "crop_source", 0x1CA30),
    ("timer", 0x2B112, "e5ac14", "crop_timer", 0x3FBE0),
)
STOCK_SPINS = (
    ("image_oom", 0x36822),   # Stock LVGL object spec-attributes allocation.
    ("event_oom", 0x34870),   # Stock event array reallocation.
    ("timer_oom", 0x3FBED),   # Stock timer list allocation.
    ("palette_oom", 0x3E1CC), # One stock indexed palette allocation path.
)


def require(ok, message):
    if not ok:
        raise SystemExit(message)


def command(prefix, tool, *args, work, **kwargs):
    return run([f"{prefix}-{tool}", *map(str, args)], cwd=work, check=True, **kwargs)


def link(prefix, work, objects, sections, symbols, *, entry):
    script = [f"ENTRY({entry})", *(f"{name} = {value:#x};" for name, value in symbols.items()), "SECTIONS {"]
    script.extend(f"  .{name} {value:#x} : {{ *(.{name}) }}" for name, value in sections)
    script.extend(("  /DISCARD/ : { *(.comment .note* .eh_frame*) }", "}"))
    (work / "layout.ld").write_text("\n".join(script) + "\n")
    command(prefix, "ld", "-EL", "--no-relax", "-T", "layout.ld", "-o", "trace.elf", *objects, work=work)
    listing = command(prefix, "nm", "--defined-only", "trace.elf", work=work,
                      capture_output=True, text=True).stdout.splitlines()
    return {label: int(address, 16) for address, _, label in map(str.split, listing)}


def trace_bytes(prefix, work):
    command(prefix, "objcopy", "--dump-section", ".phase_trace=phase.bin", "trace.elf", work=work)
    return (work / "phase.bin").read_bytes()


def patch_call(site, dest):
    delta = dest - ((XIP + site) & ~3) - 4
    require(delta % 4 == 0 and -0x80000 <= delta < 0x80000, f"Invalid marker call at {site:#x}")
    return ((((delta // 4) & 0x3ffff) << 6) | 0x25).to_bytes(3, "little")


def build(prefix, work, reference):
    require(len(reference) == TAIL and sha256(reference).hexdigest() == SOURCE_DSP_SHA,
            "Expected exact stock-operations control DSP")
    for _, offset, old, _, _ in PHASES:
        require(reference[offset:offset + 3] == bytes.fromhex(old), f"Changed call at {offset:#x}")
    command(prefix, "as", "--no-transform", "-o", "trace.o", HERE / "phase_trace.S", work=work)
    symbols = {"uart_base": UART, **{target: XIP + address for _, _, _, target, address in PHASES}}
    linked = link(prefix, work, ("trace.o",), (("phase_trace", XIP + TAIL),), symbols, entry="trace_label")
    trace = trace_bytes(prefix, work)
    require(len(trace) <= LIMIT - TAIL, "Trace exceeded the original erase footprint")
    expected_table = pack("<10I", UART, XIP + TAIL + 8, *(XIP + t[4] for t in PHASES))
    require(trace.startswith(expected_table), "Unexpected linked tracer targets")

    candidate = bytearray(reference)
    for name, offset, _, _, _ in PHASES:
        candidate[offset:offset + 3] = patch_call(offset, linked[f"trace_{name}"])
    candidate.extend(trace)
    return candidate, trace, linked


def fixture_assembly(work, candidate):
    # Reuse the native menu fixture's register-window startup and exception vectors.
    menu_smoke = HERE.parent / "dsp-v48-native-menu" / "smoke.S"
    boot = menu_smoke.read_text().split('.section .registration_literal', 1)[0]
    boot = boot.replace(".word smoke_main", ".word phase_trace_fixture")
    source = [boot, '''
.section .fixture,"ax",@progbits
.global exit_fixture
exit_fixture:
    entry a1, 32
    mov.n a3, a2
    movi.n a2, 1
    simcall

.section .uart_fixture,"aw",@progbits
.global uart_fixture
uart_fixture: .word 0xff, 0, 0, 3, 0, 0x20, 0
''']
    sections = [("vectors", SIM), ("start", SIM + 0x400),
                ("fixture", SIM + 0x75000), ("uart_fixture", SIM_UART)]
    for index, (_, site, _, target, entry) in enumerate(PHASES):
        start = f"site{index}"
        (work / f"{start}.bin").write_bytes(candidate[site:site + 3])
        sections.extend(((start, SIM + site), (target, SIM + entry - 4)))
        source.append(f'''
.section .fixture,"ax",@progbits
.p2align 2
{start}_pointer: .word {start}_instruction
.global {start}
{start}:
    entry a1, 32
    mov.n a10, a2
    mov.n a11, a3
    mov.n a12, a4
    mov.n a13, a5
    l32r a8, {start}_pointer
    jx a8

.section .{start},"ax",@progbits
{start}_instruction:
    .incbin "{start}.bin"
    mov.n a2, a10
    retw.n

.section .{target},"ax",@progbits
{target}_pointer: .word model{index}
.global {target}
{target}:
    entry a1, 32
    l32r a8, {target}_pointer
    jx a8

.section .fixture,"ax",@progbits
model{index}:
    movi.n a10, {index}
    mov.n a11, a2
    mov.n a12, a3
    mov.n a13, a4
    mov.n a14, a5
    call8 fixture_callee
    mov.n a2, a10
    retw.n
''')
    for name, address in STOCK_SPINS:
        spin = candidate[address:address + 3]
        require(spin == bytes.fromhex("06ffff"), f"Expected retail self-loop at {address:#x}")
        (work / f"{name}.bin").write_bytes(spin)
        sections.append((name, SIM + address))
        source.append(f'''
.section .{name},"ax",@progbits
.global {name}
{name}:
    .incbin "{name}.bin"
''')
    (work / "fixture.S").write_text("\n".join(source))
    return sections


def smoke(prefix, work, candidate, original_trace, physical_symbols):
    sections = fixture_assembly(work, candidate)
    sections.append(("phase_trace", SIM + TAIL))
    command(prefix, "as", "--no-transform", "-o", "fixture.o", "fixture.S", work=work)
    command(prefix, "gcc", "-c", "-Os", "-ffreestanding", "-fno-stack-protector", "-mabi=windowed",
            "-mtext-section-literals", "-mlongcalls", "-Wall", "-Wextra", "-Werror", "-o", "mock.o",
            HERE / "phase_trace_smoke.c", work=work)

    # Move the mock's code/data into one non-overlapping fixture section.
    mock = "mock-placed.o"
    command(prefix, "objcopy", "--rename-section", ".text=.fixture",
            "--rename-section", ".rodata=.fixture", "--rename-section", ".bss=.fixture",
            "mock.o", mock, work=work)
    mock_sections = command(prefix, "size", "-A", mock, work=work, capture_output=True, text=True).stdout
    require(not any(line.startswith(".literal") and int(line.split()[1]) for line in mock_sections.splitlines()),
            "Unexpected out-of-line fixture literals")
    linked = link(prefix, work, ("trace.o", "fixture.o", mock), sections, {"uart_base": SIM_UART}, entry="_start")
    actual_trace = trace_bytes(prefix, work)
    table = pack("<10I", SIM_UART, SIM + TAIL + 8, *(SIM + item[4] for item in PHASES))
    require(actual_trace == table + original_trace[len(table):], "Fixture tracer code changed")
    for name, _, _, _, _ in PHASES:
        symbol = f"trace_{name}"
        require(physical_symbols[symbol] - XIP == linked[symbol] - SIM, f"Fixture moved {symbol}")

    launch = ["qemu-system-xtensa", "-M", "sim", "-cpu", "de212", "-m", "16M", "-display", "none",
              "-monitor", "none", "-serial", "none", "-semihosting", "-device", "loader,file=trace.elf,cpu-num=0"]
    for mode in range(8):
        (work / "uart.bin").write_bytes(pack("<7I", 0xff, 0, 0, 3, 0, 0x20, mode))
        command(prefix, "objcopy", "--update-section", ".uart_fixture=uart.bin", "trace.elf", work=work)
        if mode < 4:
            run(launch, cwd=work, check=True, timeout=10)
            continue
        name, address = STOCK_SPINS[mode - 4]
        log = work / f"{name}.log"
        try:
            run([*launch, "-d", "in_asm", "-D", str(log)], cwd=work, check=True, timeout=1)
        except TimeoutExpired:
            require(f"0x{SIM + address:08x}:" in log.read_text(), f"Fixture did not reach {name}")
        else:
            raise SystemExit(f"Fixture returned past {name}")
    print("Xtensa fixture passed: all eight call sites, four arguments and return values, zero crop return,"
          " busy or incompatible UART, and four exact stock no-return branches.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_ops", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tool-prefix", default="xtensa-esp32-elf")
    args = parser.parse_args()
    require(args.output.name.endswith(".OFFLINE.zip"), "Use a new .OFFLINE.zip output path")
    require(sha256(args.stock_ops.read_bytes()).hexdigest() == SOURCE_ZIP_SHA,
            "Expected the exact stock-operations ZIP")
    with ZipFile(args.stock_ops) as archive:
        require(archive.namelist() == ["DSP.bin"], "Expected only DSP.bin")
        reference = archive.read("DSP.bin")
    with TemporaryDirectory(prefix="dsp-phase-trace-") as directory:
        work = Path(directory)
        candidate, trace, symbols = build(args.tool_prefix, work, reference)
        smoke(args.tool_prefix, work, candidate, trace, symbols)
    with ZipFile(args.output, "x") as archive:
        archive.writestr(ZipInfo("DSP.bin"), candidate, compress_type=ZIP_DEFLATED)
    print(f"Trace {len(trace)} bytes, {LIMIT - len(candidate)} bytes free in 112 sectors")
    print(f"DSP.bin {len(candidate)} bytes SHA-256 {sha256(candidate).hexdigest()} CRC {crc32(candidate, 0xffffffff):08x}")
    print(f"ZIP SHA-256 {sha256(args.output.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
