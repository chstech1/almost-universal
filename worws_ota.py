"""Local Bluetooth firmware bench tools for the W4600000 REV V06."""

import argparse
import asyncio
import hashlib
import io
import math
import struct
import sys
import zipfile
from pathlib import Path
from uuid import UUID
from zlib import crc32


RECOVERY_NAME = "WoRws_D"
SWITCHBOT_SERVICE_DATA = ("00000d00-0000-1000-8000-00805f9b34fb",
                         "0000fd3d-0000-1000-8000-00805f9b34fb")
SERVICE = "02f00000-0000-0000-0000-00000000fe00"
SEND = "02f00000-0000-0000-0000-00000000ff01"
RECEIVE = "02f00000-0000-0000-0000-00000000ff02"
NORMAL_SERVICES = ("cba20d00-224d-11e6-9fb8-0002a5d5c51b", SWITCHBOT_SERVICE_DATA[1])
NORMAL_WRITE = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
NORMAL_NOTIFY = "cba20003-224d-11e6-9fb8-0002a5d5c51b"
MANUFACTURER = 0x0969

# The SDK uses a resource-relative write address of zero for the full image.
STOCK_V48_SHA256 = "dac9677e93d4190dccc25498971ad146fee4d8217b6f866138266c088e4ca44e"
VERIFIED_V48_RECOVERY_PACKAGES = {STOCK_V48_SHA256: 0}
EXPERIMENTAL_A_DSP_SHA256 = "fae96b9b43e8917b81f0a56ffcc4a2fa305e0b2d07ecdc2c2422990c6e975fff"
EXPERIMENTAL_LABEL_DSP_SHA256 = "44fad7c5bae85a3370c81794b520246da348d3ce20236c5a3c8b111a977bbca7"
EXPERIMENTAL_DSP_LABELS = {
    EXPERIMENTAL_A_DSP_SHA256: "A-button BLE marker",
    EXPERIMENTAL_LABEL_DSP_SHA256: "Charging → OTA TEST (eight-byte label control)",
}
SETUP_BASES = {1: (0x3000, 0x54000), 12: (0,), 22: (0x100000,)}
COMPONENTS = {
    # Chip query, image setup, erase, data, finalize.
    "RES.bin": (11, 22, 27, 28, 20),
    "DSP.bin": (11, 12, 14, 16, 20),
    "ARM.bin": (0, 1, 3, 5, 9),
}
PAGE_SIZE = 4096
MAX_PACKAGE_SIZE = 16 * 1024 * 1024
MAX_GATT_PAYLOAD = 512 - 3  # The Android SDK requests a 512-byte ATT MTU.
COMMAND_TIMEOUT = 8
FINALIZE_TIMEOUT = 60


class OtaError(Exception):
    pass


def firmware_crc(data):
    # The SDK starts its reflected CRC register at zero.
    return crc32(data, 0xFFFFFFFF)


def load_package(path):
    with path.open("rb") as source:
        archive = source.read(MAX_PACKAGE_SIZE + 1)
    if len(archive) > MAX_PACKAGE_SIZE:
        raise OtaError("Archive exceeds the Universal Remote package size limit")
    digest = hashlib.sha256(archive).hexdigest()
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        members = package.infolist()
        names = {member.filename for member in members}
        if not names or not names <= COMPONENTS.keys() or len(names) != len(members):
            raise OtaError("Expected unique ARM.bin, DSP.bin, or RES.bin entries at the ZIP root")
        if any(member.file_size == 0 for member in members):
            raise OtaError("Firmware entries must contain data")
        if sum(member.file_size for member in members) > MAX_PACKAGE_SIZE:
            raise OtaError("Firmware entries exceed the Universal Remote package size limit")
        images = {name: package.read(name) for name in COMPONENTS if name in names}
    return digest, images


def recovery_address(digest, images):
    if digest not in VERIFIED_V48_RECOVERY_PACKAGES:
        raise OtaError(
            "This package has no verified local v4.8 transfer profile"
        )
    address = VERIFIED_V48_RECOVERY_PACKAGES[digest]
    if "ARM.bin" not in images or ("RES.bin" in images) != (address is not None):
        raise OtaError("Package components do not match the verified recovery profile")
    return address


def deployment_package(stock_path, dsp_path=None):
    digest, stock = load_package(stock_path)
    if digest != STOCK_V48_SHA256 or set(stock) != COMPONENTS.keys():
        raise OtaError("Expected the original v4.8 ZIP with stock RES, DSP and ARM")
    res_address = recovery_address(digest, stock)
    if dsp_path is None:
        return digest, stock, res_address
    digest, candidate = load_package(dsp_path)
    if digest not in EXPERIMENTAL_DSP_LABELS or set(candidate) != {"DSP.bin"}:
        raise OtaError("Expected a pinned A-button or charging-label archive with only DSP.bin")
    stock_sectors = (len(stock["DSP.bin"]) + PAGE_SIZE - 1) // PAGE_SIZE
    if len(candidate["DSP.bin"]) > stock_sectors * PAGE_SIZE:
        raise OtaError("The candidate exceeds the stock DSP erase range")
    return digest, candidate, None


class OtaLink:
    def __init__(self, client):
        self.client = client
        self.replies = asyncio.Queue()
        service = client.services.get_service(SERVICE)
        self.send = service.get_characteristic(SEND) if service else None
        self.receive = service.get_characteristic(RECEIVE) if service else None
        if (
            self.send is None or self.receive is None
            or "write-without-response" not in self.send.properties
            or "notify" not in self.receive.properties
        ):
            raise OtaError("The FreqChip recovery service is missing or incompatible")
        self.chunk_size = min(self.send.max_write_without_response_size, MAX_GATT_PAYLOAD) - 9
        if self.chunk_size <= 0:
            raise OtaError("The negotiated BLE write size is too small")

    def on_notify(self, _characteristic, data):
        self.replies.put_nowait(bytes(data))

    def on_disconnect(self):
        self.replies.put_nowait(None)

    async def exchange(self, packet, operation, *, timeout=COMMAND_TIMEOUT, reboot=False):
        if not self.client.is_connected:
            raise OtaError(f"{operation}: remote disconnected before the write")
        if not self.replies.empty():
            raise OtaError(f"{operation}: received an unsolicited notification")
        try:
            async with asyncio.timeout(timeout):
                await self.client.write_gatt_char(self.send, packet, response=False)
                reply = await self.replies.get()
                if reboot and reply is not None:
                    check_reply(reply, operation)
                    if await self.replies.get() is not None:
                        raise OtaError(f"{operation}: expected the remote to reboot")
        except TimeoutError as error:
            raise OtaError(f"{operation}: timed out") from error
        if reply is None and not reboot:
            raise OtaError(f"{operation}: remote disconnected before acknowledging")
        return reply


class CheckedOtaLink(OtaLink):
    """Validate acknowledgments and the destinations observed on the V06 spare."""

    def __init__(self, client, report):
        super().__init__(client)
        self.report = report

    async def exchange(self, packet, operation, **kwargs):
        reply = await super().exchange(packet, operation, **kwargs)
        opcode = packet[0]
        if reply is None:
            raise OtaError(f"{operation}: disconnected before final acknowledgment")
        if len(reply) < 4 or reply[1] != opcode:
            raise OtaError(f"{operation}: unexpected reply ({reply.hex(' ')})")
        if opcode in SETUP_BASES:
            check_reply(reply, operation, minimum=8)
            base = struct.unpack_from("<I", reply, 4)[0]
            if base not in SETUP_BASES[opcode]:
                raise OtaError(f"{operation}: unexpected destination 0x{base:08x}")
            self.report(f"{operation}: destination 0x{base:08x}")
        if opcode in (3, 5, 14, 16) and reply[0] == 0 and len(reply) >= 8:
            if struct.unpack_from("<I", packet, 3)[0] != struct.unpack_from("<I", reply, 4)[0]:
                raise OtaError(f"{operation}: acknowledgment address mismatch")
        if opcode in (9, 20):
            if reply != bytes((0, opcode, 4, 0)):
                raise OtaError(f"{operation}: unexpected final acknowledgment ({reply.hex(' ')})")
            self.report(f"{operation}: acknowledged ({reply.hex(' ')})")
        return reply


def check_reply(reply, operation, minimum=1):
    if reply and reply[0] != 0:
        raise OtaError(f"{operation}: remote rejected command ({reply.hex()})")
    if len(reply) < minimum:
        raise OtaError(f"{operation}: short reply ({reply.hex()})")
    return reply


async def setup_component(link, name, size, checksum):
    query, setup, _, _, _ = COMPONENTS[name]
    operation = f"{name} chip query"
    check_reply(await link.exchange(struct.pack("<BHIH", query, 3, 0, 0), operation), operation)
    return await link.exchange(struct.pack("<BHII", setup, 3, size, checksum), f"{name} setup")


async def transfer_component(link, name, data, res_address, report):
    _, _, erase, write, finalize = COMPONENTS[name]
    size = len(data)
    checksum = firmware_crc(data)
    is_res = name == "RES.bin"
    is_arm = name == "ARM.bin"
    operation = f"{name} setup"
    setup_reply = await setup_component(link, name, size, checksum)
    check_reply(setup_reply, operation, minimum=1 if is_res else 8)
    start = res_address if is_res else struct.unpack_from("<I", setup_reply, 4)[0]
    # The ARM and DSP address domains are supplied by the bootloader.
    erase_size = size if is_res else (size + PAGE_SIZE - 1) // PAGE_SIZE * PAGE_SIZE
    if start is None or start < 0 or start + erase_size > 1 << 32:
        raise OtaError(f"{operation}: invalid destination range")

    report(f"{name}: erasing from 0x{start:08x}")
    pages = 1 if is_res else erase_size // PAGE_SIZE
    for page in range(pages):
        address = start + page * PAGE_SIZE
        packet = struct.pack("<BHI", erase, 7, address)
        if not is_arm:
            packet += b"\x00\x00"
        operation = f"{name} erase at 0x{address:08x}"
        check_reply(await link.exchange(packet, operation, timeout=180 if is_res else COMMAND_TIMEOUT),
                    operation)

    report(f"{name}: writing {size:,} bytes")
    next_percent = 10
    for offset in range(0, size, link.chunk_size):
        chunk = data[offset:offset + link.chunk_size]
        address = start + offset
        operation = f"{name} write at 0x{address:08x}"
        packet = struct.pack("<BHIH", write, 9, address, len(chunk)) + chunk
        reply = await link.exchange(packet, operation)
        end = offset + len(chunk)
        final_address_expected = end == size and not is_res
        check_reply(reply, operation, minimum=8 if final_address_expected else 1)
        if final_address_expected and struct.unpack_from("<I", reply, 4)[0] != address:
            raise OtaError(f"{operation}: remote acknowledged a different final address")
        percent = end * 100 // size
        if percent >= next_percent:
            report(f"{name}: {percent}%")
            next_percent = (percent // 10 + 1) * 10

    operation = f"{name} finalize"
    report(f"{name}: finalizing")
    reply = await link.exchange(
        struct.pack("<BHII", finalize, 10, size, checksum),
        operation,
        timeout=FINALIZE_TIMEOUT,
        reboot=is_arm,
    )
    if not is_arm:
        check_reply(reply, operation)


def is_normal_remote(adv):
    for service in SWITCHBOT_SERVICE_DATA:
        data = adv.service_data.get(service, b"")
        # WoRwsParser uses 7 and 39 for pairing and normal advertisements.
        if len(data) >= 3 and (data[0] & 0x7F) in (7, 39):
            return True
    return False


def matches_normal_identity(device, adv, address, manufacturer_id):
    return (device.address.lower() == address
            and adv.manufacturer_data.get(MANUFACTURER, b"")[:6] == manufacturer_id)


async def scan_devices(scan_seconds, normal=False, *, watch_normal=None):
    from bleak import BleakScanner

    found = {}

    def detect(device, adv):
        matches = is_normal_remote(adv) if normal else adv.local_name == RECOVERY_NAME
        if matches or (watch_normal and matches_normal_identity(device, adv, *watch_normal)):
            found[device.address.lower()] = (device, adv)

    try:
        async with asyncio.timeout(scan_seconds + COMMAND_TIMEOUT):
            async with BleakScanner(detection_callback=detect):
                await asyncio.sleep(scan_seconds)
    except TimeoutError as error:
        raise OtaError("Bluetooth scan did not start or stop in time") from error
    return found


def select_device(candidates, address, manufacturer_id):
    if address not in candidates:
        raise OtaError(f"{address} did not advertise as {RECOVERY_NAME}")
    device, adv = candidates[address]
    if adv.local_name != RECOVERY_NAME:
        raise OtaError("The selected device is not in recovery mode")
    observed = adv.manufacturer_data.get(MANUFACTURER, b"")[:6]
    update_mac = manufacturer_id[:5] + bytes(((manufacturer_id[5] + 1) % 256,))
    if observed and observed not in (manufacturer_id, update_mac):
        raise OtaError("Recovery advertisement conflicts with the selected spare")
    return device


async def recovery_session(address, normal_address, manufacturer_id, images, res_address, report):
    if tuple(images) != tuple(COMPONENTS) or res_address != 0:
        raise OtaError("Recovery requires the complete stock RES, DSP and ARM restore")

    from bleak import BleakClient

    candidates = await scan_devices(8, watch_normal=(normal_address, manufacturer_id))
    if normal_address in candidates:
        raise OtaError("The selected spare is still advertising in normal mode")
    device = select_device(candidates, address, manufacturer_id)

    def disconnected(_client):
        if link is not None:
            link.on_disconnect()

    link = None
    async with BleakClient(device, timeout=10, disconnected_callback=disconnected) as client:
        link = CheckedOtaLink(client, report)
        try:
            await asyncio.wait_for(client.start_notify(link.receive, link.on_notify), COMMAND_TIMEOUT)
        except TimeoutError as error:
            raise OtaError("Timed out subscribing to FreqChip recovery replies") from error
        await asyncio.sleep(1)
        # Recovery firmware may erase on the first OTA command. These checks
        # precede the explicit erase packets and are part of the stock restore.
        for name in reversed(images):
            data = images[name]
            await setup_component(link, name, len(data), firmware_crc(data))
        for name, data in images.items():
            await transfer_component(link, name, data, res_address, report)


async def verify_v48(address, manufacturer_id, report):
    from bleak import BleakClient, BleakScanner

    device = await BleakScanner.find_device_by_filter(
        lambda dev, adv: matches_normal_identity(dev, adv, address, manufacturer_id), timeout=25,
    )
    if device is None:
        raise OtaError("The spare's normal-mode UUID and manufacturer ID did not both match")
    async with BleakClient(device, timeout=10) as client:
        service = next((s for uuid in NORMAL_SERVICES if (s := client.services.get_service(uuid))), None)
        writer = service.get_characteristic(NORMAL_WRITE) if service else None
        notifier = service.get_characteristic(NORMAL_NOTIFY) if service else None
        if (writer is None or notifier is None or "notify" not in notifier.properties
                or not {"write", "write-without-response"}.intersection(writer.properties)):
            raise OtaError("Normal-mode command service missing or incompatible")
        replies = asyncio.Queue()
        try:
            await asyncio.wait_for(
                client.start_notify(notifier, lambda _, data: replies.put_nowait(bytes(data))),
                COMMAND_TIMEOUT,
            )
            async with asyncio.timeout(COMMAND_TIMEOUT):
                await client.write_gatt_char(writer, bytes.fromhex("57 00 00 00 02"),
                                             response="write" in writer.properties)
                while True:
                    reply = await replies.get()
                    if len(reply) == 20 and reply[:4] == b"\x01\x00\x00\x00":
                        break
        except TimeoutError as error:
            raise OtaError("Timed out waiting for normal-mode firmware readback") from error
    version = reply[5]
    report(f"Normal-mode ARM reports v{version // 10}.{version % 10} with {reply[4]}% battery")
    if version != 48:
        raise OtaError("Expected normal-mode ARM firmware v4.8")
    return reply


def run_bluetooth(operation, *args, **kwargs):
    try:
        from bleak.exc import BleakError
    except ImportError as error:
        raise OtaError("Install the Bluetooth dependency with python -m pip install -r requirements.txt") from error
    try:
        return asyncio.run(operation(*args, **kwargs))
    except BleakError as error:
        raise OtaError(f"Bluetooth failed: {error}") from error


def manufacturer_id(value):
    try:
        address = bytes.fromhex(value.replace(":", ""))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a six-byte manufacturer identifier") from error
    if len(address) != 6:
        raise argparse.ArgumentTypeError("Expected a six-byte manufacturer identifier")
    return address


def report(message):
    print(message, flush=True)


def report_images(digest, images):
    report(f"Archive SHA-256 {digest}")
    for name, data in images.items():
        report(f"{name:<7} {len(data):>10,} bytes  FreqChip CRC {firmware_crc(data):08x}  "
               f"SHA-256 {hashlib.sha256(data).hexdigest()}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="validate an OTA ZIP offline")
    inspect.add_argument("package", type=Path)
    preflight = commands.add_parser("preflight", help="check pinned deployment images offline")
    preflight.add_argument("package", type=Path, help="original stock v4.8 ZIP")
    preflight.add_argument("--dsp-package", type=Path, help="pinned A-button or charging-label DSP ZIP")
    scan = commands.add_parser("scan", help="list Universal Remote BLE advertisements")
    scan.add_argument("--seconds", type=float, default=8)
    scan.add_argument("--normal", action="store_true", help="list remotes in normal mode")
    status = commands.add_parser("status", help="verify normal-mode identity and read v4.8")
    probe = commands.add_parser("probe-recovery", help="disabled until non-erasing recovery entry is verified")
    stock = commands.add_parser("flash", help="restore all three stock v4.8 images")
    dsp = commands.add_parser("flash-dsp", help="disabled until non-erasing recovery entry is verified")
    for command in (status, probe, stock, dsp):
        command.add_argument("--normal-device", required=True, type=UUID, help="spare's normal-mode UUID")
        command.add_argument("--manufacturer-id", required=True, type=manufacturer_id,
                             help="spare's six-byte manufacturer identifier")
    for command in (probe, stock, dsp):
        command.add_argument("package", type=Path, help="original stock v4.8 ZIP")
        command.add_argument("--device", required=True, type=UUID, help="spare's recovery-mode UUID")
    probe.add_argument("--dsp-package", type=Path, help="pinned A-button or charging-label DSP ZIP")
    dsp.add_argument("--dsp-package", required=True, type=Path, help="pinned A-button or charging-label DSP ZIP")
    args = parser.parse_args(argv)

    try:
        if args.command in ("probe-recovery", "flash-dsp"):
            raise OtaError(
                f"{args.command} is disabled until a non-erasing recovery entry is verified. "
                "Stock recovery can erase external flash on the first OTA command. "
                "Use preflight for offline package checks."
            )
        if args.command == "scan":
            if not math.isfinite(args.seconds) or args.seconds <= 0:
                raise OtaError("Scan duration must be a positive number of seconds")
            found = run_bluetooth(scan_devices, args.seconds, args.normal)
            name = "Universal Remote (normal mode)" if args.normal else RECOVERY_NAME
            for address, (_, adv) in sorted(found.items()):
                print(f"{address}  {name}  {adv.rssi} dBm")
            if not found:
                print(f"No devices found for {name}.")
            return 0
        if args.command == "inspect":
            digest, images = load_package(args.package)
            report_images(digest, images)
            status = "verified" if digest in VERIFIED_V48_RECOVERY_PACKAGES else "unverified"
            report(f"SwitchBot v4.8 recovery package: {status}")
            return 0
        if args.command == "status":
            reply = run_bluetooth(verify_v48, str(args.normal_device), args.manufacturer_id, report)
            lift = {0: "off", 1: "on"}.get(reply[8], "unknown")
            report(f"Raise to Wake {lift} (raw byte 8 = 0x{reply[8]:02x})")
            report(f"Base info {reply.hex(' ')}")
            return 0
        dsp_path = getattr(args, "dsp_package", None)
        digest, images, res_address = deployment_package(args.package, dsp_path)
        if dsp_path is not None:
            report(f"Verified local stock rollback ZIP SHA-256 {STOCK_V48_SHA256}")
            report(f"DSP candidate: {EXPERIMENTAL_DSP_LABELS[digest]}")
            report("Offline validation only. Live DSP-only transfer is disabled.")
        report_images(digest, images)
        if dsp_path is None:
            report("Transfer order: " + ", ".join(images))
        if args.command == "preflight":
            return 0
        if args.device == args.normal_device:
            raise OtaError("The normal and recovery UUIDs must identify distinct advertisements")
        report("Stock restore may erase external flash during recovery setup.")
        run_bluetooth(recovery_session, str(args.device), str(args.normal_device), args.manufacturer_id,
                      images, res_address, report)
        report("Stock transfers acknowledged. Verifying normal-mode reboot.")
        run_bluetooth(verify_v48, str(args.normal_device), args.manufacturer_id, report)
        report("Stock v4.8 Bluetooth reboot verified. Check the display to complete the rehearsal.")
        return 0
    except (OtaError, OSError, EOFError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Update status is unverified.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
