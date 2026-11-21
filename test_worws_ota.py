import io
import struct
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import worws_ota as ota

NORMAL_ID = "11111111-1111-4111-8111-111111111111"
RECOVERY_ID = "22222222-2222-4222-8222-222222222222"
MANUFACTURER_ID = bytes.fromhex("020000000010")


def recovery_advertisement(identity=b""):
    return SimpleNamespace(local_name=ota.RECOVERY_NAME,
                           manufacturer_data={ota.MANUFACTURER: identity})


def acknowledgment(opcode, base=None):
    header = bytes((0, opcode, 8 if base is not None else 4, 0))
    return header if base is None else header + struct.pack("<I", base)


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

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def start_notify(self, _characteristic, callback):
        self.link = callback.__self__

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
                                   RECOVERY_ID, "--normal-device", NORMAL_ID,
                                   "--manufacturer-id", MANUFACTURER_ID.hex()])
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

    def test_device_must_match_selected_recovery_identity(self):
        device = object()
        candidates = {RECOVERY_ID: (device, recovery_advertisement())}
        self.assertIs(ota.select_device(candidates, RECOVERY_ID, MANUFACTURER_ID), device)
        with self.assertRaisesRegex(ota.OtaError, "did not advertise"):
            ota.select_device(candidates, NORMAL_ID, MANUFACTURER_ID)
        candidates[RECOVERY_ID] = (device, recovery_advertisement(bytes.fromhex("020000000011")))
        self.assertIs(ota.select_device(candidates, RECOVERY_ID, MANUFACTURER_ID), device)
        candidates[RECOVERY_ID] = (device, recovery_advertisement(b"wrong!"))
        with self.assertRaisesRegex(ota.OtaError, "conflicts"):
            ota.select_device(candidates, RECOVERY_ID, MANUFACTURER_ID)

        normal = SimpleNamespace(address=NORMAL_ID.upper())
        adv = SimpleNamespace(manufacturer_data={ota.MANUFACTURER: MANUFACTURER_ID + b"extra"})
        self.assertTrue(ota.matches_normal_identity(normal, adv, NORMAL_ID, MANUFACTURER_ID))
        self.assertFalse(ota.matches_normal_identity(normal, adv, RECOVERY_ID, MANUFACTURER_ID))
        self.assertFalse(ota.matches_normal_identity(normal, adv, NORMAL_ID, b"wrong!"))

    def test_identifies_normal_remote_from_switchbot_service_data(self):
        for service in ota.SWITCHBOT_SERVICE_DATA:
            for code in (0x07, 0x27, 0xA7):
                self.assertTrue(ota.is_normal_remote(
                    SimpleNamespace(service_data={service: bytes((code, 0x20, 90))})
                ))
            self.assertFalse(ota.is_normal_remote(
                SimpleNamespace(service_data={service: bytes((0x66, 0x20, 90))})
            ))
        self.assertFalse(ota.is_normal_remote(SimpleNamespace(service_data={"other": b"\x27\x20Z"})))

    def test_candidate_is_pinned_dsp_only_within_stock_erase_range(self):
        stock = (ota.STOCK_V48_SHA256, {"RES.bin": b"res", "DSP.bin": b"stock", "ARM.bin": b"arm"})
        for candidate, message in (
            (("other", {"DSP.bin": b"dsp"}), "pinned"),
            ((ota.EXPERIMENTAL_A_DSP_SHA256, {"ARM.bin": b"arm", "DSP.bin": b"dsp"}), "pinned"),
            ((ota.EXPERIMENTAL_LABEL_DSP_SHA256, {"RES.bin": b"res", "DSP.bin": b"dsp"}), "pinned"),
            ((ota.EXPERIMENTAL_A_DSP_SHA256, {"DSP.bin": b"a" * (ota.PAGE_SIZE + 1)}), "erase range"),
        ):
            with self.subTest(message=message), patch.object(ota, "load_package", side_effect=[stock, candidate]):
                with self.assertRaisesRegex(ota.OtaError, message):
                    ota.deployment_package(Path("stock"), Path("candidate"))
        for digest in (ota.EXPERIMENTAL_A_DSP_SHA256, ota.EXPERIMENTAL_LABEL_DSP_SHA256):
            candidate = (digest, {"DSP.bin": b"test"})
            with self.subTest(digest=digest), patch.object(ota, "load_package", side_effect=[stock, candidate]):
                self.assertEqual(ota.deployment_package(Path("stock"), Path("candidate")),
                                 (*candidate, None))

    def test_label_candidate_requires_pinned_stock_rollback_archive(self):
        with patch.object(ota, "load_package", return_value=(
            "other", {"RES.bin": b"res", "DSP.bin": b"stock", "ARM.bin": b"arm"},
        )) as load:
            with self.assertRaisesRegex(ota.OtaError, "original v4.8 ZIP"):
                ota.deployment_package(Path("wrong-stock"), Path("label-control"))
        load.assert_called_once_with(Path("wrong-stock"))

    def test_candidate_preflight_stays_offline_for_both_pins(self):
        for digest, label in (
            (ota.EXPERIMENTAL_A_DSP_SHA256, "A-button BLE marker"),
            (ota.EXPERIMENTAL_LABEL_DSP_SHA256, "Charging → OTA TEST (eight-byte label control)"),
        ):
            candidate = {"DSP.bin": b"dsp"}
            output = io.StringIO()
            with (
                self.subTest(digest=digest),
                patch.object(ota, "deployment_package", return_value=(digest, candidate, None)),
                patch.object(ota, "run_bluetooth") as run,
                patch("sys.stdout", output),
            ):
                result = ota.main(["preflight", "stock.zip", "--dsp-package", "candidate.zip"])
                self.assertEqual(result, 0)
                self.assertIn(label, output.getvalue())
                self.assertIn("Live DSP-only transfer is disabled", output.getvalue())
                run.assert_not_called()

    def test_disabled_recovery_commands_fail_before_package_or_bluetooth(self):
        identity = ["--device", RECOVERY_ID, "--normal-device", NORMAL_ID,
                    "--manufacturer-id", MANUFACTURER_ID.hex()]
        for command, package_args in (
            ("probe-recovery", []),
            ("probe-recovery", ["--dsp-package", "candidate.zip"]),
            ("flash-dsp", ["--dsp-package", "candidate.zip"]),
        ):
            errors = io.StringIO()
            with (
                self.subTest(command=command, package_args=package_args),
                patch.object(ota, "deployment_package") as deploy,
                patch.object(ota, "run_bluetooth") as run,
                patch("sys.stderr", errors),
            ):
                result = ota.main([command, "stock.zip", *package_args, *identity])
                self.assertEqual(result, 1)
                self.assertIn(f"{command} is disabled", errors.getvalue())
                self.assertIn("first OTA command", errors.getvalue())
                deploy.assert_not_called()
                run.assert_not_called()

    def test_stock_cli_requires_post_reboot_readback(self):
        images = {"RES.bin": b"res", "DSP.bin": b"dsp", "ARM.bin": b"arm"}
        with (
            patch.object(ota, "deployment_package", return_value=(ota.STOCK_V48_SHA256, images, 0)),
            patch.object(ota, "run_bluetooth", side_effect=[None, ota.OtaError("No normal readback")]) as run,
            patch("sys.stdout", io.StringIO()),
            patch("sys.stderr", io.StringIO()),
        ):
            result = ota.main(["flash", "stock.zip", "--device", RECOVERY_ID,
                               "--normal-device", NORMAL_ID, "--manufacturer-id", MANUFACTURER_ID.hex()])
        self.assertEqual(result, 1)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [ota.recovery_session, ota.verify_v48])


class TransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_session_rejects_dsp_only_before_importing_bluetooth(self):
        with patch.dict(sys.modules, {"bleak": None}):
            with self.assertRaisesRegex(ota.OtaError, "complete stock"):
                await ota.recovery_session(RECOVERY_ID, NORMAL_ID, MANUFACTURER_ID,
                                           {"DSP.bin": b"dsp"}, None, lambda _: None)

    async def test_stock_session_checks_destinations_before_explicit_erase_packets(self):
        client = FakeClient([[acknowledgment(0)], [acknowledgment(1, 0x3000)],
                             [acknowledgment(11)], [acknowledgment(12, 0)],
                             [acknowledgment(11)], [acknowledgment(22, 0x800000)]])
        targets = {RECOVERY_ID: (object(), recovery_advertisement())}
        images = {"RES.bin": b"res", "DSP.bin": b"dsp", "ARM.bin": b"arm"}
        with (
            patch.dict(sys.modules, {"bleak": SimpleNamespace(BleakClient=lambda *_a, **_k: client)}),
            patch.object(ota, "scan_devices", AsyncMock(return_value=targets)),
            patch.object(ota.asyncio, "sleep", AsyncMock()),
        ):
            with self.assertRaisesRegex(ota.OtaError, "unexpected destination"):
                await ota.recovery_session(RECOVERY_ID, NORMAL_ID, MANUFACTURER_ID, images,
                                           0, lambda _: None)
        self.assertEqual([packet[0] for packet in client.packets], [0, 1, 11, 12, 11, 22])

    async def test_unexpected_destination_stops_before_explicit_erase_packets(self):
        client = FakeClient([[acknowledgment(11)], [acknowledgment(12, 0x80000)]])
        client.link = ota.CheckedOtaLink(client, lambda _: None)
        with self.assertRaisesRegex(ota.OtaError, "unexpected destination"):
            await ota.transfer_component(client.link, "DSP.bin", b"dsp", None, lambda _: None)
        self.assertEqual([packet[0] for packet in client.packets], [11, 12])

    async def test_dsp_stage_requires_matching_finalize_acknowledgment(self):
        for final in (acknowledgment(20), bytes.fromhex("00 14 05 00 00")):
            client = FakeClient([[acknowledgment(11)], [acknowledgment(12, 0)],
                                 [acknowledgment(14, 0)], [acknowledgment(16, 0)], [final]])
            client.link = ota.CheckedOtaLink(client, lambda _: None)
            transfer = ota.transfer_component(client.link, "DSP.bin", b"dsp", None, lambda _: None)
            if final == acknowledgment(20):
                await transfer
            else:
                with self.assertRaisesRegex(ota.OtaError, "unexpected final acknowledgment"):
                    await transfer
            self.assertTrue(client.is_connected)
            self.assertEqual([packet[0] for packet in client.packets], [11, 12, 14, 16, 20])

    async def test_arm_disconnect_without_ack_is_unverified(self):
        client = FakeClient([[None]])
        client.link = ota.CheckedOtaLink(client, lambda _: None)
        with self.assertRaisesRegex(ota.OtaError, "before final acknowledgment"):
            await client.link.exchange(b"\x09", "ARM finalize", reboot=True)

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
