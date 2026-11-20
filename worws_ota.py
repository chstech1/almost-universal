"""Stock Bluetooth firmware recovery for the SwitchBot Universal Remote."""

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
SERVICE = "02f00000-0000-0000-0000-00000000fe00"
SEND = "02f00000-0000-0000-0000-00000000ff01"
RECEIVE = "02f00000-0000-0000-0000-00000000ff02"

# Populate only after matching the app's v4.8 recovery package and transfer.
# The value for each SHA-256 is the verified RES start address, or None for
# a package without RES.bin.
VERIFIED_V48_RECOVERY_PACKAGES: dict[str, int | None] = {}
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
            "This SHA-256 has not been verified against the app-selected v4.8 recovery package"
        )
    address = VERIFIED_V48_RECOVERY_PACKAGES[digest]
    if "ARM.bin" not in images or ("RES.bin" in images) != (address is not None):
        raise OtaError("Package components do not match the verified recovery profile")
    return address


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


def check_reply(reply, operation, minimum=1):
    if reply and reply[0] != 0:
        raise OtaError(f"{operation}: remote rejected command ({reply.hex()})")
    if len(reply) < minimum:
        raise OtaError(f"{operation}: short reply ({reply.hex()})")
    return reply


async def transfer_component(link, name, data, res_address, report):
    query, setup, erase, write, finalize = COMPONENTS[name]
    size = len(data)
    checksum = firmware_crc(data)
    is_res = name == "RES.bin"
    is_arm = name == "ARM.bin"

    operation = f"{name} chip query"
    if not await link.exchange(struct.pack("<BHIH", query, 3, 0, 0), operation):
        raise OtaError(f"{operation}: empty reply")

    operation = f"{name} setup"
    setup_reply = await link.exchange(struct.pack("<BHII", setup, 3, size, checksum), operation)
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


async def recovery_devices(scan_seconds):
    from bleak import BleakScanner

    found = {}

    def detect(device, adv):
        if adv.local_name == RECOVERY_NAME:
            found[device.address.lower()] = (device, adv)

    try:
        async with asyncio.timeout(scan_seconds + COMMAND_TIMEOUT):
            async with BleakScanner(detection_callback=detect):
                await asyncio.sleep(scan_seconds)
    except TimeoutError as error:
        raise OtaError("Bluetooth scan did not start or stop in time") from error
    return found


def select_device(candidates, address):
    if address not in candidates:
        raise OtaError(f"{address} did not advertise as {RECOVERY_NAME}")
    return candidates[address][0]


async def flash(address, images, res_address, scan_seconds, report):
    from bleak import BleakClient

    device = select_device(await recovery_devices(scan_seconds), address)

    def disconnected(_client):
        if link is not None:
            link.on_disconnect()

    link = None
    async with BleakClient(device, disconnected_callback=disconnected) as client:
        link = OtaLink(client)
        try:
            await asyncio.wait_for(client.start_notify(link.receive, link.on_notify), COMMAND_TIMEOUT)
        except TimeoutError as error:
            raise OtaError("Timed out subscribing to FreqChip recovery replies") from error
        for name, data in images.items():
            await transfer_component(link, name, data, res_address, report)


def run_bluetooth(operation, *args):
    try:
        from bleak.exc import BleakError
    except ImportError as error:
        raise OtaError("Install the Bluetooth dependency with python -m pip install -r requirements.txt") from error
    try:
        return asyncio.run(operation(*args))
    except BleakError as error:
        raise OtaError(f"Bluetooth failed: {error}") from error


def confirm_version():
    print("Transfer ended and the remote disconnected for reboot.")
    if not sys.stdin.isatty():
        print("Version verification pending. Check that the remote boots and SwitchBot reports v4.8.")
        return 2
    version = input("After the remote boots, enter its version as shown in the SwitchBot app: ")
    if version.strip().lower().removeprefix("v") != "4.8":
        raise OtaError("Firmware v4.8 was not confirmed after transfer")
    print("Stock firmware v4.8 verified in the SwitchBot app.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="validate an OTA ZIP offline")
    inspect.add_argument("package", type=Path)
    scan = commands.add_parser("scan", help="list remotes advertising recovery mode")
    scan.add_argument("--seconds", type=float, default=8)
    upload = commands.add_parser("flash", help="send a verified v4.8 recovery ZIP")
    upload.add_argument("package", type=Path)
    upload.add_argument("--device", required=True, type=UUID, help="UUID printed by scan")
    args = parser.parse_args(argv)

    try:
        if args.command == "scan":
            if not math.isfinite(args.seconds) or args.seconds <= 0:
                raise OtaError("Scan duration must be a positive number of seconds")
            found = run_bluetooth(recovery_devices, args.seconds)
            for address, (_, adv) in sorted(found.items()):
                print(f"{address}  {adv.local_name}  {adv.rssi} dBm")
            if not found:
                print(f"No devices advertising {RECOVERY_NAME}.")
            return 0
        digest, images = load_package(args.package)
        if args.command == "inspect":
            print(f"SHA-256 {digest}")
            for name, data in images.items():
                print(f"{name:<7} {len(data):>10,} bytes  FreqChip CRC {firmware_crc(data):08x}")
            status = "verified" if digest in VERIFIED_V48_RECOVERY_PACKAGES else "unverified"
            print(f"SwitchBot v4.8 recovery package: {status}")
            return 0
        res_address = recovery_address(digest, images)
        run_bluetooth(flash, str(args.device), images, res_address, 8,
                      lambda line: print(line, flush=True))
        return confirm_version()
    except (OtaError, OSError, EOFError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Update status is unverified.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
