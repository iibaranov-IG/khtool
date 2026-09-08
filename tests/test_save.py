"""Offline regression tests for --save guidance and command boundaries."""

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


class SaveTests(unittest.TestCase):
    def args(self):
        return types.SimpleNamespace(
            query=False,
            brightness=None,
            delay=None,
            dimm=None,
            level=None,
            mute=False,
            unmute=False,
            expert=None,
            save=True,
        )

    def test_kh80_sends_existing_save_command(self):
        device = Mock(connected=True)
        with patch.object(khtool, "get_product", return_value="KH 80"), patch.object(
            khtool, "send_print"
        ) as send:
            khtool.handle_device(self.args(), device)
        send.assert_called_once_with(device, '{"device":{"save_settings":true}}')

    def test_other_models_do_not_send_save_command(self):
        for product in ("KH 120 II", "KH 150", "KH 150 AES67", "KH 750", "unknown"):
            with self.subTest(product=product):
                output = io.StringIO()
                with patch.object(
                    khtool, "get_product", return_value=product
                ), patch.object(
                    khtool, "get_version", return_value="1_2_0"
                ), patch.object(
                    khtool, "send_print"
                ) as send, contextlib.redirect_stdout(output):
                    khtool.handle_device(self.args(), Mock(connected=True))
                send.assert_not_called()
                self.assertIn("KH 80", output.getvalue())
                self.assertIn("no save command sent", output.getvalue())

    def test_help_only_advertises_kh80_save(self):
        output = io.StringIO()
        with patch.object(
            sys, "argv", ["khtool.py", "--help"]
        ), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit_:
                khtool.main()
        self.assertEqual(exit_.exception.code, 0)
        save_help = output.getvalue().split("performs a save_settings", 1)[1]
        save_help = " ".join(save_help.split("--brightness", 1)[0].split())
        self.assertIn("only for KH 80", save_help)
        self.assertNotIn("KH 150", save_help)
        self.assertNotIn("KH 120", save_help)


if __name__ == "__main__":
    unittest.main()
