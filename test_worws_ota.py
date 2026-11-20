import io
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import worws_ota as ota


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.packets = []
        self.is_connected = True
        send = SimpleNamespace(properties=["write-without-response"],
                               max_write_without_response_size=20)
        receive = SimpleNamespace(properties=["notify"])
        service = SimpleNamespace(get_characteristic={ota.SEND: send, ota.RECEIVE: receive}.get)
        self.services = SimpleNamespace(get_service={ota.SERVICE: service}.get)
        self.link = ota.OtaLink(self)

    async def write_gatt_char(self, characteristic, packet, *, response):
        assert characteristic is self.link.send and response is False
        self.packets.append(packet)
        events = next(self.responses)
        for event in events:
            if event is None:
                self.is_connected = False
                self.link.on_disconnect()
            else:
                self.link.on_notify(self.link.receive, event)


class PackageTests(unittest.TestCase):
    def test_zip_integrity_and_flash_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stock.zip"
            with zipfile.ZipFile(path, "w") as package:
                package.writestr("ARM.bin", b"123456789")
                package.writestr("RES.bin", b"resource")
                package.writestr("DSP.bin", b"dsp")
            digest, images = ota.load_package(path)
            self.assertEqual(list(images), ["RES.bin", "DSP.bin", "ARM.bin"])
            self.assertEqual(ota.firmware_crc(images["ARM.bin"]), 0xD202D277)
            with patch.object(ota, "run_bluetooth") as run, patch("sys.stderr", io.StringIO()):
                result = ota.main(["flash", str(path), "--device",
                                   "8bcfceb0-2163-4eea-a309-1f2eec39eacc"])
            self.assertEqual(result, 1)
            run.assert_not_called()
            with patch.dict(ota.VERIFIED_V48_RECOVERY_PACKAGES, {digest: 0}, clear=True):
                self.assertEqual(ota.recovery_address(digest, images), 0)
            path.write_bytes(path.read_bytes().replace(b"123456789", b"923456781"))
            with self.assertRaises(zipfile.BadZipFile):
                ota.load_package(path)

    def test_rejects_duplicate_or_noncomponent_entries(self):
        for names in (("ARM.bin", "ARM.bin"), ("./ARM.bin",), ("../ARM.bin",)):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.zip"
                with warnings.catch_warnings(), zipfile.ZipFile(path, "w") as package:
                    warnings.simplefilter("ignore", UserWarning)
                    for name in names:
                        package.writestr(name, b"image bytes")
                with self.assertRaises(ota.OtaError):
                    ota.load_package(path)

    def test_device_must_be_a_discovered_recovery_candidate(self):
        candidates = {"recovery-id": (object(), None)}
        self.assertIs(ota.select_device(candidates, "recovery-id"), candidates["recovery-id"][0])
        with self.assertRaises(ota.OtaError):
            ota.select_device(candidates, "unrelated-id")

    def test_unconfirmed_version_does_not_report_success(self):
        with (
            patch("sys.stdin"),
            patch("sys.stdout", io.StringIO()),
            patch("builtins.input", return_value="4.6"),
        ):
            with self.assertRaises(ota.OtaError):
                ota.confirm_version()
        with (
            patch("sys.stdin"),
            patch("sys.stdout", io.StringIO()),
            patch("builtins.input", return_value="v4.8"),
        ):
            self.assertEqual(ota.confirm_version(), 0)


class TransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_components_use_app_packets_and_order(self):
        ok = [b"\0"]
        address = b"\0\0\0\0" + struct.pack("<I", 0x2000)
        final_address = b"\0\0\0\0" + struct.pack("<I", 0x200B)
        client = FakeClient([
            ok, ok, ok, ok, ok,
            ok, [address], ok, ok, [final_address], ok,
            ok, [address], ok, [address], [final_address], [None],
        ])
        for name, data in zip(ota.COMPONENTS, (b"res", b"123456789abc", b"123456789abc")):
            await ota.transfer_component(client.link, name, data, 0x4000, lambda _: None)
        self.assertEqual([packet[0] for packet in client.packets],
                         [11, 22, 27, 28, 20, 11, 12, 14, 16, 16, 20, 0, 1, 3, 5, 5, 9])
        self.assertEqual(client.packets[0], bytes.fromhex("0b 03 00 00 00 00 00 00 00"))
        self.assertEqual(client.packets[2], bytes.fromhex("1b 07 00 00 40 00 00 00 00"))
        self.assertEqual(client.packets[7], bytes.fromhex("0e 07 00 00 20 00 00 00 00"))
        self.assertEqual(client.packets[13], bytes.fromhex("03 07 00 00 20 00 00"))
        self.assertEqual(client.packets[14], bytes.fromhex("05 09 00 00 20 00 00 0b 00") + b"123456789ab")
        self.assertEqual(client.packets[15], bytes.fromhex("05 09 00 0b 20 00 00 01 00") + b"c")
        self.assertEqual(client.packets[16], b"\x09\x0a\0" + client.packets[12][3:])

    async def test_failed_write_never_finalizes(self):
        start_reply = b"\0\0\0\0\0\x20\0\0"
        for reply, message in ((b"\x01", "rejected"), (None, "disconnected"),
                               (b"\0", "short reply"), (b"\0" * 8, "different final address")):
            with self.subTest(reply=reply):
                client = FakeClient([[b"\0"], [start_reply], [b"\0"], [reply]])
                with self.assertRaisesRegex(ota.OtaError, message):
                    await ota.transfer_component(client.link, "ARM.bin", b"arm", None, lambda _: None)
                self.assertEqual([packet[0] for packet in client.packets], [0, 1, 3, 5])

    async def test_wrong_service_and_timeout(self):
        with self.assertRaisesRegex(ota.OtaError, "recovery service"):
            ota.OtaLink(SimpleNamespace(services=SimpleNamespace(get_service={}.get)))
        client = FakeClient([[]])
        with self.assertRaisesRegex(ota.OtaError, "timed out"):
            await client.link.exchange(b"test", "query", timeout=0.001)


if __name__ == "__main__":
    unittest.main()
