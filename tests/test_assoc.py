"""Magnet / .torrent registration (src/neontorrent/assoc.py). Writes only to a scratch key under HKCU\\Software\\NEON,
never to the real Software\\Classes, so the user's current magnet handler is left alone."""
from __future__ import annotations

import sys
import unittest
import uuid
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from neontorrent import assoc  # noqa: E402

SCRATCH = rf"Software\NEON\test-classes-{uuid.uuid4().hex[:8]}"


def delete_tree(root: int, path: str) -> None:
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_tree(root, rf"{path}\{child}")
        winreg.DeleteKey(root, path)
    except FileNotFoundError:
        pass


class AssocTests(unittest.TestCase):
    def tearDown(self) -> None:
        delete_tree(winreg.HKEY_CURRENT_USER, SCRATCH)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\NEON")      # only when empty: the test made it
        except OSError:
            pass

    def test_is_ours_and_handler_name(self) -> None:
        exe = Path(r"C:\Program Files\NEON Torrent\NeonTorrent.exe")
        self.assertTrue(assoc.is_ours(r'"C:\PROGRAM FILES\NEON Torrent\NeonTorrent.exe" "%1"', exe))
        self.assertFalse(assoc.is_ours(r'"C:\Users\x\AppData\Roaming\uTorrent\uTorrent.exe" "%1" /SHELLASSOC', exe))
        self.assertFalse(assoc.is_ours("", exe))
        self.assertEqual(assoc.handler_name(r'"C:\Users\x\AppData\Roaming\uTorrent\uTorrent.exe" "%1" /SHELLASSOC'),
                         "uTorrent")
        self.assertEqual(assoc.handler_name(r"C:\qbt\qbittorrent.exe %1"), "qbittorrent")

    def test_make_default_writes_protocol_and_file_type(self) -> None:
        command = r'"E:\Apps\NEON Torrent\NeonTorrent.exe" "%1"'
        assoc.make_default(command, r"E:\Apps\NEON Torrent\NeonTorrent.ico", classes=SCRATCH)
        hkcu = winreg.HKEY_CURRENT_USER
        self.assertEqual(assoc._read(hkcu, rf"{SCRATCH}\magnet\shell\open\command"), command)
        self.assertEqual(assoc._read(hkcu, rf"{SCRATCH}\magnet", "URL Protocol"), "")
        self.assertEqual(assoc._read(hkcu, rf"{SCRATCH}\.torrent"), assoc.PROG_TORRENT)
        self.assertEqual(assoc._read(hkcu, rf"{SCRATCH}\{assoc.PROG_TORRENT}\shell\open\command"), command)

    def test_current_handler_is_readable(self) -> None:
        command, locked = assoc.magnet_handler()                     # whatever this PC has; read-only
        self.assertIsInstance(command, str)
        self.assertIsInstance(locked, bool)


if __name__ == "__main__":
    unittest.main()
