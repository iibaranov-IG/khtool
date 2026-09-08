"""Offline CLI/interface tests; no pyssc installation or speakers required."""

import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    "khtool_under_test", Path(__file__).resolve().parents[1] / "khtool.py"
)
khtool = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"pyssc": types.ModuleType("pyssc")}), patch(
    "signal.signal"
):
    SPEC.loader.exec_module(khtool)


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        khtool.interface = ""

    def device(self, ip):
        return Mock(ip=ip, connected=True)

    def run_cli(self, devices, *args, cached=True):
        setup = Mock(ssc_devices=devices)
        backend = Mock()
        backend.Ssc_device_setup.return_value = setup
        backend.scan.return_value = setup
        output = io.StringIO()
        with patch.object(khtool, "ssc", backend), patch.object(
            khtool.os.path, "exists", return_value=cached
        ), patch.object(sys, "argv", ["khtool.py", *args]), patch.object(
            khtool, "print_header"
        ), patch.object(khtool, "handle_device"), contextlib.redirect_stdout(
            output
        ), contextlib.redirect_stderr(output):
            try:
                khtool.main()
            except SystemExit as exc:
                return exc.code, output.getvalue(), backend, setup
        return 0, output.getvalue(), backend, setup

    def test_global_address_does_not_need_interface(self):
        device = self.device("2001:db8::1")
        code, _, _, _ = self.run_cli([device], "-q")
        self.assertEqual(code, 0)
        device.connect.assert_called_once_with(interface="")

    def test_unique_local_address_does_not_need_interface(self):
        device = self.device("fd00::1")
        code, _, _, _ = self.run_cli([device], "-q")
        self.assertEqual(code, 0)
        device.connect.assert_called_once_with(interface="")

    def test_explicit_interface_is_not_appended_to_global_address(self):
        device = self.device("2001:db8::1")
        code, _, _, _ = self.run_cli([device], "-i", "en0", "-q")
        self.assertEqual(code, 0)
        device.connect.assert_called_once_with(interface="")

    def test_missing_link_local_scope_stops_before_any_connection(self):
        devices = [self.device("2001:db8::1"), self.device("fe80::2")]
        code, output, _, _ = self.run_cli(devices, "--mute")
        self.assertEqual(code, 2)
        self.assertIn("--interface", output)
        self.assertIn("fe80::2", output)
        for device in devices:
            device.connect.assert_not_called()
            device.send_ssc.assert_not_called()

    def test_named_interface_is_used_for_link_local(self):
        device = self.device("fe80::1")
        code, _, _, _ = self.run_cli([device], "-i", "en0", "-q")
        self.assertEqual(code, 0)
        device.connect.assert_called_once_with(interface="%en0")

    def test_windows_numeric_interface_is_preserved(self):
        device = self.device("fe80::1")
        code, _, _, _ = self.run_cli([device], "-i", "14", "-q")
        self.assertEqual(code, 0)
        device.connect.assert_called_once_with(interface="%14")

    def test_link_local_representations_use_scope(self):
        khtool.interface = "%en0"
        for ip in ("FE80::1", "fe80:0:0:0:0:0:0:1", "fe90::1", "febf::1"):
            with self.subTest(ip=ip):
                self.assertEqual(khtool.get_interface(self.device(ip)), "%en0")

    def test_existing_scope_is_not_duplicated(self):
        for args in ((), ("-i", "en0")):
            with self.subTest(args=args):
                device = self.device("fe80::1%14")
                code, _, _, _ = self.run_cli([device], *args, "-q")
                self.assertEqual(code, 0)
                device.connect.assert_called_once_with(interface="")

    def test_unselected_link_local_device_does_not_require_interface(self):
        devices = [self.device("2001:db8::1"), self.device("fe80::2")]
        code, _, _, _ = self.run_cli(devices, "-t", "0", "-q")
        self.assertEqual(code, 0)
        devices[0].connect.assert_called_once_with(interface="")
        devices[1].connect.assert_not_called()

    def test_scan_does_not_require_or_receive_interface(self):
        for cached in (True, False):
            with self.subTest(cached=cached):
                code, _, backend, setup = self.run_cli(
                    [self.device("fe80::1")], "--scan", cached=cached
                )
                self.assertEqual(code, 0)
                backend.scan.assert_called_once_with(scan_time_seconds=10)
                setup.to_json.assert_called_once_with("khtool.json")
                setup.ssc_devices[0].connect.assert_not_called()

    def test_first_run_discovery_does_not_require_interface(self):
        code, _, backend, _ = self.run_cli([], cached=False)
        self.assertEqual(code, 0)
        backend.scan.assert_called_once_with(scan_time_seconds=10)

    def test_send_uses_same_scope_as_connect(self):
        khtool.interface = "%14"
        device = self.device("fe80::1")
        device.send_ssc.return_value = types.SimpleNamespace(RX="{}\r\n")
        self.assertEqual(khtool.send_command(device, "{}"), "{}")
        device.send_ssc.assert_called_once_with("{}", interface="%14")

    def test_direct_send_without_scope_does_not_send(self):
        device = self.device("fe80::1")
        with self.assertRaisesRegex(ValueError, "--interface"):
            khtool.send_command(device, "{}")
        device.send_ssc.assert_not_called()

    def test_help_describes_scope_and_discovery(self):
        code, output, backend, _ = self.run_cli([], "--help")
        self.assertEqual(code, 0)
        self.assertIn("link-local", output)
        self.assertIn("discovery", output)
        backend.scan.assert_not_called()

    def test_invalid_cached_address_stops_before_any_connection(self):
        devices = [self.device("2001:db8::1"), self.device("not-an-ip")]
        code, _, _, _ = self.run_cli(devices, "-q")
        self.assertEqual(code, 2)
        for device in devices:
            device.connect.assert_not_called()

    def test_empty_existing_zone_is_rejected(self):
        device = self.device("fe80::1%")
        code, output, _, _ = self.run_cli([device], "-i", "14", "-q")
        self.assertEqual(code, 2)
        self.assertIn("empty IPv6 zone", output)
        device.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
