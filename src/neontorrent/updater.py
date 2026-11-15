"""Over-the-air updates: NEON looks for a newer release on GitHub at random times, downloads it in the background,
checks it, and asks only whether to restart NEON to install it.

Checks before anything is installed:
  * the release is the latest one of github.com/mrsharmaji1301/neon-torrent (HTTPS),
  * the .msi has the SHA-256 that GitHub reports for that release asset,
  * the .msi itself is NEON (its UpgradeCode) and has the version the release claims.
Applying: NEON writes a small PowerShell script into data\\updates and quits. The script waits for NEON to close,
runs Windows Installer on the .msi (Windows shows its own Yes prompt, as NEON installs for all users) and starts the
new NEON.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable

from . import APP_VERSION, web

REPO = "mrsharmaji1301/neon-torrent"
API = os.environ.get("NEON_UPDATE_API") or f"https://api.github.com/repos/{REPO}/releases/latest"   # env: tests only
ASSET = "NEON-Torrent-Setup.msi"
UPGRADE_CODE = "{7C3E9A51-2B64-4F0D-9E18-6A2D5C4B3F71}"
MAX_MSI = 300 * 1024 * 1024
FIRST_CHECK = (2 * 60, 10 * 60)            # seconds after start, chosen at random
EVERY = (5 * 3600, 7 * 3600)               # then this often, at random


def version_tuple(text: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", (text or "").split("-")[0])
    return tuple(int(n) for n in numbers[:4]) or (0,)


def newer(remote: str, local: str = APP_VERSION) -> bool:
    return version_tuple(remote) > version_tuple(local)


class UpdateError(Exception):
    pass


def latest(api: str = API) -> dict | None:
    """{"version", "url", "size", "sha256", "notes"} of the latest release's .msi, or None when there is none."""
    text, _ = web.get_text(api, limit=2 * 1024 * 1024, headers={"Accept": "application/vnd.github+json"})
    try:
        release = json.loads(text)
    except ValueError:
        raise UpdateError("GitHub sent an unexpected answer") from None
    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    version = str(release.get("tag_name", "")).lstrip("vV")
    for asset in release.get("assets") or []:
        if asset.get("name") == ASSET:
            digest = str(asset.get("digest") or "")
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise UpdateError("the release does not say the setup's SHA-256")
            return {"version": version, "url": str(asset.get("browser_download_url", "")),
                    "size": int(asset.get("size") or 0), "sha256": digest[7:].lower(),
                    "notes": str(release.get("body") or "")[:4000]}
    return None


def msi_identity(path: Path) -> tuple[str, str]:
    """(UpgradeCode, ProductVersion) read from the .msi with Windows Installer."""
    import ctypes
    from ctypes import wintypes
    msi = ctypes.windll.msi
    db, view, record = wintypes.HANDLE(), wintypes.HANDLE(), wintypes.HANDLE()
    values = []
    if msi.MsiOpenDatabaseW(str(path), ctypes.c_wchar_p(0), ctypes.byref(db)):     # 0 = read only
        raise UpdateError("the downloaded setup is not a Windows Installer package")
    try:
        for prop in ("UpgradeCode", "ProductVersion"):
            query = f"SELECT `Value` FROM `Property` WHERE `Property`='{prop}'"
            if msi.MsiDatabaseOpenViewW(db, query, ctypes.byref(view)) or msi.MsiViewExecute(view, None):
                raise UpdateError("cannot read the downloaded setup")
            try:
                if msi.MsiViewFetch(view, ctypes.byref(record)):
                    raise UpdateError("the downloaded setup has no " + prop)
                size = wintypes.DWORD(256)
                buf = ctypes.create_unicode_buffer(256)
                msi.MsiRecordGetStringW(record, 1, buf, ctypes.byref(size))
                values.append(buf.value)
                msi.MsiCloseHandle(record)
            finally:
                msi.MsiCloseHandle(view)
    finally:
        msi.MsiCloseHandle(db)
    return values[0], values[1]


def download(info: dict, folder: Path, cancelled: Callable[[], bool] = lambda: False,
             progress: Callable[[int, int], None] = lambda done, total: None) -> Path:
    """The release's .msi, checked: size, SHA-256 from GitHub, NEON's UpgradeCode and the release's version."""
    if not 0 < info["size"] <= MAX_MSI:
        raise UpdateError("the setup has an unexpected size")
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / f"NEON-Torrent-Setup-{info['version']}.msi"
    part = final.with_suffix(".part")
    digest = hashlib.sha256()
    with web.open_url(info["url"], timeout=60) as response, open(part, "wb") as handle:
        total = 0
        while chunk := response.read(256 * 1024):
            if cancelled():
                raise UpdateError("cancelled")
            total += len(chunk)
            if total > info["size"]:
                raise UpdateError("the setup is larger than GitHub said")
            digest.update(chunk)
            handle.write(chunk)
            progress(total, info["size"])
    if total != info["size"] or digest.hexdigest() != info["sha256"]:
        part.unlink(missing_ok=True)
        raise UpdateError("the downloaded setup does not match GitHub's SHA-256; it was deleted")
    upgrade_code, version = msi_identity(part)
    if upgrade_code.upper() != UPGRADE_CODE or version_tuple(version) != version_tuple(info["version"]):
        part.unlink(missing_ok=True)
        raise UpdateError("the downloaded setup is not this NEON release; it was deleted")
    part.replace(final)
    return final


def save_notes(folder: Path, version: str, notes: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"notes-{version}.md").write_text(notes or "", encoding="utf-8")


def pending_notes(folder: Path, version: str = APP_VERSION) -> str | None:
    """Release notes saved before this version was installed, once; None when there are none."""
    path = Path(folder) / f"notes-{version}.md"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)
        for old in Path(folder).glob("NEON-Torrent-Setup-*.msi"):       # the installed setup is not needed now
            old.unlink(missing_ok=True)
    return text


def apply(msi: Path, exe: Path, folder: Path) -> None:
    """Start the hidden helper that installs ``msi`` once this NEON (this process) has quit, then starts ``exe``.
    The caller quits NEON right after this."""
    script = folder / "apply-update.ps1"

    def ps(text: str) -> str:                                             # a PowerShell single-quoted string
        return "'" + str(text).replace("'", "''") + "'"
    script.write_text(
        "$ErrorActionPreference = 'Continue'\n"
        f"Wait-Process -Id {os.getpid()} -Timeout 120 -ErrorAction SilentlyContinue\n"
        f"$msi = {ps(msi)}\n"
        f"$log = {ps(folder / 'install.log')}\n"
        "$arguments = '/i \"' + $msi + '\" /passive /norestart /l*v \"' + $log + '\"'\n"
        "$p = Start-Process -FilePath \"$env:SystemRoot\\System32\\msiexec.exe\" -ArgumentList $arguments -Verb RunAs "
        "-Wait -PassThru\n"
        f"Start-Process -FilePath {ps(exe)}\n", encoding="utf-8")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / \
        "powershell.exe"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    command = [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File",
               str(script)]
    try:
        # out of any job NEON runs in, so a launcher that closes its job with NEON cannot stop the update half-way
        subprocess.Popen(command, creationflags=flags | 0x01000000, close_fds=True)    # CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        subprocess.Popen(command, creationflags=flags, close_fds=True)                 # the job forbids breaking away


class Updater:
    """Looks for a newer release in the background (``on_available(info)`` from a background thread). Downloading and
    installing happen only when the user presses UPDATE NOW and INSTALL & RESTART in the update window."""

    def __init__(self, on_available: Callable[[dict], None], on_latest: Callable[[str], None] = lambda m: None,
                 on_error: Callable[[str], None] = lambda m: None, api: str = API):
        self.on_available, self.on_latest, self.on_error, self.api = on_available, on_latest, on_error, api
        self.busy = threading.Lock()
        self.available: dict | None = None

    @staticmethod
    def next_delay(first: bool) -> float:
        low, high = FIRST_CHECK if first else EVERY
        return random.uniform(low, high)

    def check_now(self, manual: bool = False) -> None:
        threading.Thread(target=self._check, args=(manual,), daemon=True, name="neon-update-check").start()

    def _check(self, manual: bool) -> None:
        if not self.busy.acquire(blocking=False):
            return
        try:
            info = latest(self.api)
            if info is not None and newer(info["version"]):
                self.available = info
                self.on_available(info)
            elif manual:
                self.on_latest(f"NEON {APP_VERSION} is the latest version.")
        except (UpdateError, web.WebError, OSError, ValueError, KeyError) as exc:
            if manual:
                self.on_error(str(exc))
        finally:
            self.busy.release()
