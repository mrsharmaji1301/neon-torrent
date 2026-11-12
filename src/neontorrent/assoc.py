"""Magnet links and .torrent files: which app Windows opens them with, and making NEON Torrent that app.

Browsers (Chrome, Brave, Edge) hand a clicked magnet: link to Windows, which starts the app registered for the
"magnet" URL protocol. Windows looks for that app in this order:
  1. the user's choice in Settings > Default apps (UrlAssociations\\magnet\\UserChoice, protected by a hash that only
     Windows itself may write),
  2. HKCU\\Software\\Classes\\magnet (per-user registration, which other clients such as uTorrent write),
  3. HKLM\\Software\\Classes\\magnet (the NEON installer's registration, for every user).
make_default() writes level 2 for this user, only when the user asks. When a level-1 choice exists for another app,
only Windows Settings can change it, so open_default_apps() opens NEON's page there instead.
"""
from __future__ import annotations

import ctypes
import os
import winreg
from pathlib import Path

PROG_MAGNET = "NeonTorrent.Magnet"
PROG_TORRENT = "NeonTorrent.Torrent"
REGISTERED_NAME = "NEON Torrent"               # the name under RegisteredApplications (written by the installer)
CLASSES = r"Software\Classes"
URL_CHOICE = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\magnet\UserChoice"
FILE_CHOICE = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.torrent\UserChoice"


def _read(root: int, path: str, name: str = "") -> str:
    try:
        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return ""


def _command(prog_or_scheme: str) -> str:
    """The open command Windows uses for a ProgID or URL scheme (HKCU over HKLM, as HKEY_CLASSES_ROOT merges them)."""
    return _read(winreg.HKEY_CLASSES_ROOT, rf"{prog_or_scheme}\shell\open\command")


def magnet_handler() -> tuple[str, bool]:
    """(the command that opens magnet links now, whether it is locked by a Settings choice)."""
    choice = _read(winreg.HKEY_CURRENT_USER, URL_CHOICE, "ProgId")
    if choice:
        return _command(choice), True
    return _command("magnet"), False


def torrent_handler() -> tuple[str, bool]:
    choice = _read(winreg.HKEY_CURRENT_USER, FILE_CHOICE, "ProgId")
    if choice:
        return _command(choice), True
    return _command(_read(winreg.HKEY_CLASSES_ROOT, ".torrent") or "-"), False


def is_ours(command: str, exe: Path) -> bool:
    """True when the command starts our exe (its full path, either quoted or bare)."""
    text = os.path.normcase(os.path.expandvars(command)).replace("/", "\\")
    return os.path.normcase(str(exe.resolve())) in text


def handler_name(command: str) -> str:
    """A short app name for a command, e.g. "uTorrent" for "C:\\...\\uTorrent.exe" "%1" /SHELLASSOC."""
    text = command.strip()
    exe = text[1:].split('"', 1)[0] if text.startswith('"') else text.split(" ", 1)[0]
    return Path(exe).stem or "another app"


def _write(root: int, path: str, values: dict[str, str]) -> None:
    with winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE) as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def make_default(open_command: str, icon: str, classes: str = CLASSES) -> None:
    """Register NEON Torrent for magnet: links and .torrent files for this Windows user. ``open_command`` must contain
    "%1". ``classes`` is a different key only in tests."""
    hkcu = winreg.HKEY_CURRENT_USER
    _write(hkcu, rf"{classes}\magnet", {"": "URL:Magnet link", "URL Protocol": "", "Content Type":
                                        "application/x-magnet"})
    _write(hkcu, rf"{classes}\magnet\DefaultIcon", {"": icon})
    _write(hkcu, rf"{classes}\magnet\shell", {"": "open"})
    _write(hkcu, rf"{classes}\magnet\shell\open\command", {"": open_command})
    _write(hkcu, rf"{classes}\{PROG_TORRENT}", {"": "Torrent file"})
    _write(hkcu, rf"{classes}\{PROG_TORRENT}\DefaultIcon", {"": icon})
    _write(hkcu, rf"{classes}\{PROG_TORRENT}\shell\open\command", {"": open_command})
    _write(hkcu, rf"{classes}\.torrent", {"": PROG_TORRENT, "Content Type": "application/x-bittorrent"})
    _write(hkcu, rf"{classes}\.torrent\OpenWithProgids", {PROG_TORRENT: ""})
    if classes == CLASSES:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)     # SHCNE_ASSOCCHANGED: Explorer re-reads


def open_default_apps() -> None:
    """Windows Settings > Default apps > NEON Torrent, where the user picks it for magnet links and .torrent files.
    Explorer opens the fixed ms-settings: link (by its absolute path: no PATH lookup)."""
    import subprocess
    from urllib.parse import quote
    explorer = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe")
    subprocess.Popen([explorer, f"ms-settings:defaultapps?registeredAppMachine={quote(REGISTERED_NAME)}"])
