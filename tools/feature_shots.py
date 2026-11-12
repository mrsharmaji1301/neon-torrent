"""Render the README pictures of File Sharing, PC to PC, Paired devices and the text panel into
docs/screenshots (the README banner comes from tools/make_installer_art.py).

Everything runs on a throwaway profile under ..\\neon-build\\shots-features with made-up names and private example
addresses (192.168.1.x): no torrent is added, nothing is downloaded, no sharing session or tunnel is opened (the PC to
PC pictures use a server on 127.0.0.1 only) and nothing from the user's own profile or PC appears.
Run with the project's venv interpreter: .venv\\Scripts\\python.exe tools\\feature_shots.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT.parent / "neon-build" / "shots-features"
OUT = ROOT / "docs" / "screenshots"
shutil.rmtree(WORK, ignore_errors=True)
(WORK / "appdata").mkdir(parents=True)
os.environ["APPDATA"] = str(WORK / "appdata")
os.environ["APPDATA_OVERRIDE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import neon_torrent as NT  # noqa: E402
from neontorrent import peer as P  # noqa: E402
from neontorrent import share as S  # noqa: E402
from neontorrent import theme as T  # noqa: E402
from neontorrent.peer_ui import ConnectPCDialog, PairedDevicesDialog  # noqa: E402
from neontorrent.share_ui import ShareTab, TextInbox  # noqa: E402

PHONE = {"name": "Pixel 8", "model": "Android 16 · Chrome", "ip": "192.168.1.42", "mac": "3A-1F-0C-7D-22-9B",
         "path": "lan"}


def save(widget, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    widget.grab().save(str(OUT / name))
    print("Wrote", OUT / name)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(NT.build_qss())
    prefs = T.load_preferences()
    prefs.update(download_dir=str(WORK / "Downloads"), magnet_ask=False)
    T.save_preferences(prefs)
    ShareTab.activate = lambda self: None          # never open a real sharing session or tunnel here

    window = NT.TorrentWindow()
    window.resize(1300, 860)
    window.show()
    window.view_tabs.select("share")
    tab = window.share_tab
    tab.qr.set_url("http://192.168.1.20:52814/#v=1&m=send&k=" + "A" * 43 + "&t=" + "B" * 22)
    tab._fill_pc({"ip": "192.168.1.20", "mac": "5C-60-BA-12-8E-41", "wifi": True, "ssid": "HomeNet-5G"})
    tab.net_values["pc_ip"].setText("192.168.1.20   (port 52814)")         # no server runs for this picture
    tab._fill_phone(PHONE)
    tab._set_status("connected")
    for i, text in enumerate(("Pickup at 6:30 · Gate 4", "https://example.org/tickets/7F3K")):
        tab._add_text({"text": text, "name": "Pixel 8", "at": time.time() - 300 + i * 60})

    # PC to PC: a second NEON on 127.0.0.1 with its own identity, offering one file
    host_id, me = P.Identity.load(WORK / "host"), P.Identity.load(WORK / "me")
    server = S.ShareServer("127.0.0.1", WORK / "FTP", "OFFICE-PC", allow_loopback=True, identity=host_id,
                           trusted=lambda _k: False)
    server.start()
    sample = WORK / "Quarterly-report.pdf"
    sample.write_bytes(os.urandom(2_400_000))
    server.add_offer(sample)
    store = P.PeerStore(WORK / "me")
    store.remember(P.Identity.load(WORK / "laptop").public, "Travel laptop")
    connect = ConnectPCDialog(me, store, lambda: Path(r"D:\Downloads\NEON\FTP"), window)   # shown, never written
    connect.resize(680, 600)
    original = P.PeerClient.__init__
    P.PeerClient.__init__ = lambda self, code, ident, name, model="NEON Torrent on Windows", allow_loopback=False: \
        original(self, code, ident, "HOME-PC", model, True)
    connect.code.setText(server.url("send"))

    def step1():
        save(window, "file-sharing.png")
        connect.show()
        connect.connect_pc()

    def step2():
        server.decide(server.snapshot()["phones"][0]["sid"], True)
        server.send_text("Slides are in the file list. Call me when you have them.")

    def step3():
        save(connect, "connect-to-pc.png")
        paired = PairedDevicesDialog(me, store, window)
        paired.resize(640, 360)
        paired.show()
        QTimer.singleShot(400, lambda: (save(paired, "paired-devices.png"), paired.close()))
        inbox = TextInbox(window, send=lambda text: {"text": text, "at": time.time(), "name": "Pixel 8"})
        for entry in tab.texts:
            inbox.add(entry)
        inbox.add({"text": "On my way. Sending the boarding pass now.", "at": time.time(), "name": "Pixel 8",
                   "mine": True})
        inbox.resize(540, 560)
        inbox.show()
        QTimer.singleShot(700, lambda: (save(inbox, "text-panel.png"), inbox.close()))

    def finish():
        connect.disconnect()
        server.stop()
        window.quitting = True
        window.close()
        QTimer.singleShot(4000, app.quit)

    QTimer.singleShot(2500, step1)
    QTimer.singleShot(4000, step2)
    QTimer.singleShot(8000, step3)
    QTimer.singleShot(10000, finish)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
