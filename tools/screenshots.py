"""Render Store and website screenshots from the real app.

The app's own window runs against a throwaway profile under F:\\neon-build\\shots and downloads official Ubuntu and
Debian images for a few minutes; then the main window and its dialogs are grabbed at 2x. Nothing appears on screen,
and the user's own profile and running app are untouched. Peer addresses are swapped for documentation addresses
(RFC 5737 / RFC 3849) because the images are published.

Run with the project's venv interpreter: .venv\\Scripts\\python.exe tools\\screenshots.py [--minutes 3]
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = Path(os.environ.get("NEON_BUILD", r"F:\neon-build")) / "shots"
PROFILE, DOWNLOADS, OUT = SHOTS / "appdata", SHOTS / "downloads", SHOTS / "out"
SITE_ASSETS = ROOT / "site" / "assets"
TORRENTS = [  # official images only: nothing third-party in published screenshots
    "https://releases.ubuntu.com/resolute/ubuntu-26.04.1-desktop-amd64.iso.torrent",
    "https://releases.ubuntu.com/resolute/ubuntu-26.04.1-live-server-amd64.iso.torrent",
    "https://cdimage.debian.org/debian-cd/current/amd64/bt-cd/debian-13.7.0-amd64-netinst.iso.torrent",
]
SIZE = (1600, 1000)  # logical window size: 3200x2000 for the Store, scaled to 1280x800 for the site
DOC_NETS = ("192.0.2", "198.51.100", "203.0.113")
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def mask_ip(text: str) -> str:
    """Swap a real peer address for a stable documentation address, keeping the port."""
    candidates = [(text, None)] + ([tuple(text.rsplit(":", 1))] if ":" in text else [])
    for host, port in candidates:
        try:
            ip = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            continue
        h = int(hashlib.sha256(ip.packed).hexdigest(), 16)
        fake = f"{DOC_NETS[h % 3]}.{h % 253 + 1}" if ip.version == 4 else f"2001:db8::{h % 0xffff:x}"
        return fake if port is None else f"{fake}:{port}"
    return text


def masked(value):
    if isinstance(value, dict):
        out = {k: mask_ip(v) if k == "ip" and isinstance(v, str) else masked(v) for k, v in value.items()}
        if "save_path" in out:
            out["save_path"] = r"D:\Downloads"  # not the build folder the screenshots download into
        return out
    if isinstance(value, list):
        return [masked(v) for v in value]
    return value


def new_detections(folder: Path, before: set[str]) -> list[str]:
    """Malwarebytes web-protection blocks logged since the run started."""
    found = []
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        if f.name in before:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            threats = json.loads(text[text.index("{"):]).get("threats", [])
        except (OSError, ValueError):
            found.append(f.name)
            continue
        for threat in threats:  # same layout the Shield's MalwarebytesWatcher reads
            web = (threat.get("mainTrace") or {}).get("websiteData") or {}
            found.append(f"{web.get('ip')}:{web.get('port')} by {Path(str(web.get('processPath', ''))).name}")
    return found


def fresh_profile() -> None:
    real_shield = Path(os.environ.get("APPDATA", "")) / "NeonTorrent" / "shield"
    shutil.rmtree(PROFILE, ignore_errors=True)
    shutil.rmtree(DOWNLOADS, ignore_errors=True)
    data = PROFILE / "NeonTorrent"
    (data / "shield").mkdir(parents=True)
    DOWNLOADS.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for f in real_shield.glob("*"):  # IP-range lists and learned blocks: start as protected as the real app
        if f.is_file():
            shutil.copy2(f, data / "shield" / f.name)
    (data / "settings.json").write_text(json.dumps({"download_dir": str(DOWNLOADS)}), encoding="utf-8")
    os.environ["APPDATA"] = str(PROFILE)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=3.0, help="how long the torrents run before the captures")
    args = ap.parse_args()
    fresh_profile()
    os.environ["QT_SCALE_FACTOR"] = "2"
    sys.path.insert(0, str(ROOT / "src"))
    from PySide6.QtCore import QEvent, QObject, Qt, QTimer
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication, QScrollArea, QSystemTrayIcon, QWidget

    import neon_torrent as app_module
    from neontorrent import dialogs
    from neontorrent import theme as T
    from neontorrent.shield import MB_DETECTIONS

    mb_before = {f.name for f in MB_DETECTIONS.glob("*.json")} if MB_DETECTIONS.is_dir() else set()

    for name in ("show", "setVisible", "showMessage"):  # no second NEON icon in the user's tray
        setattr(QSystemTrayIcon, name, lambda *_a, **_k: None)
    def masking(original):
        return lambda self, data: original(self, masked(data))

    for cls, name in ((dialogs.ShieldDialog, "update_data"), (dialogs.DetailsDialog, "update_detail")):
        setattr(cls, name, masking(getattr(cls, name)))
    on_notice = app_module.TorrentWindow._on_notice
    app_module.TorrentWindow._on_notice = lambda self, text, *a: on_notice(
        self, IPV4.sub(lambda m: mask_ip(m.group()), text), *a)

    class OffScreen(QObject):
        def eventFilter(self, obj, event):  # every window renders, none is shown
            if event.type() == QEvent.Type.Polish and isinstance(obj, QWidget) and obj.isWindow():
                obj.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            return False

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(app_module.APP_NAME)
    app.setOrganizationName("NeonTorrent")
    app.setFont(T.font(10))
    hider = OffScreen()
    app.installEventFilter(hider)
    window = app_module.TorrentWindow()
    window.resize(*SIZE)
    window.show()
    for url in TORRENTS:
        QTimer.singleShot(1500, lambda u=url: window.add_any(u))

    shots: dict[str, QImage] = {}

    def grab(widget) -> QImage:
        img = widget.grab().toImage()
        img.setDevicePixelRatio(1)
        return img

    def over_main(dialog) -> QImage:
        print(f"{type(dialog).__name__}: {dialog.width()}x{dialog.height()}", flush=True)
        base, top = QImage(shots["1-transfers"]), grab(dialog)
        p = QPainter(base)
        p.fillRect(base.rect(), QColor(0, 0, 0, 110))
        p.drawImage((base.width() - top.width()) // 2, (base.height() - top.height()) // 2, top)
        p.end()
        return base

    def subject() -> dict | None:
        rows = window.table.source.rows
        return next((r for r in rows if "desktop" in str(r.get("name", ""))), rows[0] if rows else None)

    def capture_main():
        shots["1-transfers"] = grab(window)
        row = subject()
        if row:
            window._selected_rows = lambda: [row]
            window.show_details()

    def capture_details():
        if window.details is not None:
            shots["2-details"] = over_main(window.details)
            window.details.close()
        window.show_shield()

    def capture_shield():
        if window.shield_dialog is not None:
            shots["3-shield"] = over_main(window.shield_dialog)
            window.shield_dialog.close()
        row = subject()
        if row:
            window.show_options(row["key"])
        scroll = window.options_dialog.findChild(QScrollArea, "optionsScroll") if window.options_dialog else None
        if scroll is not None:  # full height, as on a 1080p screen (the 2x capture screen is only 540 high)
            scroll.setMinimumHeight(scroll.widget().sizeHint().height())
            dialog = window.options_dialog
            dialog.resize(dialog.width(), dialog.minimumSizeHint().height())

    def capture_options():
        if window.options_dialog is not None:
            shots["4-torrent-settings"] = over_main(window.options_dialog)
            window.options_dialog.close()
        dialog = dialogs.SettingsDialog(dict(window.prefs, _open_tab="shield"), window)
        dialog.show()
        QTimer.singleShot(1500, lambda: finish(dialog))

    def finish(settings_dialog):
        shots["5-settings"] = over_main(settings_dialog)
        settings_dialog.close()
        for name, img in shots.items():
            img.save(str(OUT / f"{name}.png"))
        site = {"1-transfers": 1, "3-shield": 2, "2-details": 3, "4-torrent-settings": 4}
        for name, n in site.items():
            if name in shots:
                small = shots[name].scaled(1280, 800, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
                small.save(str(SITE_ASSETS / f"screenshot-{n}.png"))
        print(f"Saved {len(shots)} screenshots to {OUT}", flush=True)
        window.quit_app()

    started = time.time()

    def progress():
        rows = window.table.source.rows
        state = ", ".join(f"{str(r.get('name', '?'))[:28]} {r.get('state', '')}" for r in rows)
        print(f"{time.time() - started:4.0f} s  {len(rows)} torrents  {state}", flush=True)

    ticker = QTimer()
    ticker.timeout.connect(progress)
    ticker.start(30000)
    wait = int(args.minutes * 60000)
    for delay, step in ((wait, capture_main), (wait + 4000, capture_details), (wait + 8000, capture_shield),
                        (wait + 11000, capture_options)):
        QTimer.singleShot(delay, step)
    code = app.exec()
    if window.engine_thread.isRunning():
        window.engine_thread.wait(5000)
    shutil.rmtree(DOWNLOADS, ignore_errors=True)
    blocked = new_detections(MB_DETECTIONS, mb_before)
    print(f"Malwarebytes blocks during the run: {len(blocked)}" + "".join(f"\n  {b}" for b in blocked))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
