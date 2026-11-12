"""PC to PC windows: CONNECT TO PC (this PC joins another PC's File Sharing session with its pair code) and PAIRED
DEVICES (remembered PCs). The network work runs in background threads; results come back through Qt signals."""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem)

from . import peer as P
from . import share as S
from . import theme as T
from .dialogs import NeonDialog
from .share_ui import Bar, TextInbox
from .widgets import GlowButton

POLL_MS = 2000


class _Signals(QObject):
    status = Signal(str, str)              # text, level (info / ok / warn / error)
    connected = Signal(dict)               # the hello reply
    state = Signal(dict)                   # every ping reply
    files = Signal(list)
    texts = Signal(list)
    progress = Signal(str, int, int)       # label, done, total
    finished = Signal(str, str)            # message, level


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class ConnectPCDialog(NeonDialog):
    """This PC as the client: paste the other PC's pair code, then send and get files and text."""

    def __init__(self, identity: P.Identity, peers: P.PeerStore, save_dir: Callable[[], Path], parent=None):
        super().__init__("Connect to PC", parent, resizable=True)
        self.setModal(False)
        self.setMinimumSize(620, 560)
        self.identity, self.peers, self.save_dir = identity, peers, save_dir
        self.client: P.PeerClient | None = None
        self.allowed = False
        self.busy = False
        self.cancel_flag = False
        self.offers: list[dict] = []
        self.rev = -1
        self.text_rev = 0
        self.inbox: TextInbox | None = None
        self.texts: list[dict] = []
        self.sig = _Signals()
        self.sig.status.connect(self._set_status)
        self.sig.connected.connect(self._on_connected)
        self.sig.state.connect(self._on_state)
        self.sig.files.connect(self._on_files)
        self.sig.texts.connect(self._on_texts)
        self.sig.progress.connect(self._on_progress)
        self.sig.finished.connect(self._on_finished)

        intro = QLabel("On the other PC open FILE SHARING, press PAIR CODE and send the code to yourself (e.g. a "
                       "message). Paste it here. Files and text are end-to-end encrypted; over the internet "
                       "Cloudflare only relays sealed bytes.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        self.root.addWidget(intro)
        row = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText("Paste the pair code: http://192.168…/#…  or  https://….trycloudflare.com/#…")
        self.code.returnPressed.connect(self.connect_pc)
        row.addWidget(self.code, 1)
        paste = GlowButton("PASTE", "copy", "cyan", "outline")
        paste.setFixedSize(100, 40)
        paste.clicked.connect(lambda: self.code.setText(QGuiApplication.clipboard().text().strip()))
        row.addWidget(paste)
        self.connect_btn = GlowButton("CONNECT", "link", "cyan", "solid", "cyan2")
        self.connect_btn.setFixedSize(130, 40)
        self.connect_btn.clicked.connect(self.connect_pc)
        row.addWidget(self.connect_btn)
        self.root.addLayout(row)
        self.remember = QCheckBox("Remember this PC (Paired devices): it may connect back without asking")
        self.remember.setChecked(True)
        self.root.addWidget(self.remember)
        self.status = QLabel("Not connected.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)            # names come from the other PC
        self.status.setFont(T.head_font(10, QFont.Weight.DemiBold, 1.0))
        self.root.addWidget(self.status)

        self.files_label = QLabel("Files offered by the other PC")
        self.files_label.setObjectName("formLabel")
        self.root.addWidget(self.files_label)
        self.list = QListWidget()
        self.list.setMinimumHeight(150)
        self.root.addWidget(self.list, 1)
        actions = QHBoxLayout()
        self.get_btn = GlowButton("DOWNLOAD TICKED", "download", "cyan", "outline")
        self.get_btn.clicked.connect(self.download_ticked)
        self.send_btn = GlowButton("SEND FILES", "upload", "magenta", "outline")
        self.send_btn.clicked.connect(self.send_files)
        self.text_btn = GlowButton("TEXT", "copy", "magenta", "outline")
        self.text_btn.clicked.connect(self.show_text)
        for b, w in ((self.get_btn, 190), (self.send_btn, 150), (self.text_btn, 160)):
            b.setFixedSize(w, 42)
            actions.addWidget(b)
        actions.addStretch(1)
        self.root.addLayout(actions)
        prog = QHBoxLayout()
        self.prog_label = QLabel("")
        self.prog_label.setObjectName("muted")
        self.prog_label.setTextFormat(Qt.TextFormat.PlainText)
        self.bar = Bar(8)
        self.cancel_btn = GlowButton("CANCEL", "close", "orange", "outline")
        self.cancel_btn.setFixedSize(110, 36)
        self.cancel_btn.clicked.connect(self._cancel)
        prog.addWidget(self.prog_label)
        prog.addWidget(self.bar, 1)
        prog.addWidget(self.cancel_btn)
        self.root.addLayout(prog)
        bottom = QHBoxLayout()
        self.folder_note = QLabel("")
        self.folder_note.setObjectName("muted")
        bottom.addWidget(self.folder_note, 1)
        self.disconnect_btn = GlowButton("DISCONNECT", "close", "orange", "outline")
        self.disconnect_btn.setFixedSize(150, 40)
        self.disconnect_btn.clicked.connect(self.disconnect)
        bottom.addWidget(self.disconnect_btn)
        self.root.addLayout(bottom)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self._poll)
        self._render()

    # ---------------------------------------------------------- helpers
    def _thread(self, fn: Callable[[], None]) -> None:
        threading.Thread(target=fn, daemon=True, name="neon-peer").start()

    def _set_status(self, text: str, level: str = "info") -> None:
        color = {"ok": "green", "warn": "yellow", "error": "red"}.get(level, "cyan")
        self.status.setStyleSheet(f"color: {T.hexc(color)};")
        self.status.setText(text)

    def _render(self) -> None:
        connected = self.client is not None
        live = connected and self.allowed
        self.code.setEnabled(not connected)
        self.connect_btn.setEnabled(not connected)
        self.remember.setEnabled(not connected)
        for b in (self.get_btn, self.send_btn):
            b.setEnabled(live and not self.busy)
        self.text_btn.setEnabled(live)
        self.cancel_btn.setVisible(self.busy)
        self.disconnect_btn.setEnabled(connected)
        self.folder_note.setText(f"Received files go to {self.save_dir()}" if live else "")

    # ---------------------------------------------------------- connect / poll / disconnect
    def connect_pc(self) -> None:
        if self.client is not None:
            return
        try:
            client = P.PeerClient(self.code.text(), self.identity, socket.gethostname() or "PC")
        except P.PeerError as exc:
            self._set_status(str(exc), "error")
            return
        self.client = client
        self._render()
        self._set_status("Connecting…")

        def run():
            try:
                self.sig.connected.emit(client.hello())
            except P.PeerError as exc:
                self.sig.finished.emit(f"Could not connect: {exc}", "error")
        self._thread(run)

    def _on_connected(self, reply: dict) -> None:
        client = self.client
        if client is None:
            return
        key = P.fingerprint(client.remote_id) if client.remote_id else "not proven"
        if not client.remote_id:
            self._set_status(f"{client.remote_name} did not prove a NEON PC key. Disconnect unless you trust it.",
                             "warn")
        elif reply.get("state") == "allowed":
            self._set_status(f"Connected to {client.remote_name} (PC key {key}).", "ok")
        else:
            self._set_status(f"Waiting for {client.remote_name} to press ALLOW… (PC key {key})", "warn")
        self._on_state(reply)
        self.timer.start()

    def _poll(self) -> None:
        client = self.client
        if client is None:
            return

        def run():
            try:
                reply = client.ping()
                self.sig.state.emit(reply)
                if reply.get("state") == "allowed":
                    if reply.get("rev") != self.rev:
                        self.rev = reply.get("rev")
                        self.sig.files.emit(client.files())
                    if isinstance(reply.get("trev"), int) and reply["trev"] > self.text_rev:
                        texts = client.texts(self.text_rev)
                        if texts:
                            self.text_rev = texts[-1]["n"]
                        self.sig.texts.emit(texts)
            except P.PeerError as exc:
                self.sig.finished.emit(f"Disconnected: {exc}", "error")
        self._thread(run)

    def _on_state(self, reply: dict) -> None:
        client = self.client
        if client is None:
            return
        state = reply.get("state")
        if state == "allowed" and not self.allowed:
            self.allowed = True
            if client.remote_id:
                if self.remember.isChecked():
                    self.peers.remember(client.remote_id, client.remote_name)
                else:
                    self.peers.seen(client.remote_id)
            self._set_status(f"Connected to {client.remote_name}"
                             + (f" (PC key {P.fingerprint(client.remote_id)})." if client.remote_id else "."), "ok")
        elif state == "denied":
            self.sig.finished.emit(f"{client.remote_name} declined this PC.", "error")
        self._render()

    def disconnect(self) -> None:
        client, self.client = self.client, None
        self.timer.stop()
        self.allowed, self.rev, self.text_rev = False, -1, 0
        self.cancel_flag = True
        if client is not None:
            self._thread(client.bye)
        self.list.clear()
        self._set_status("Not connected.")
        self._render()

    def _on_finished(self, message: str, level: str) -> None:
        self.busy = False
        self.cancel_flag = False
        self.prog_label.setText("")
        self.bar.set_value(0)
        if level == "error" and (message.startswith("Could not connect") or message.startswith("Disconnected")
                                 or "declined" in message):
            client, self.client = self.client, None
            self.timer.stop()
            self.allowed = False
            if client is not None and not message.startswith("Disconnected"):
                self._thread(client.bye)
        self._set_status(message, level)
        self._render()

    def closeEvent(self, event):
        self.disconnect()
        if self.inbox is not None:
            self.inbox.close()
        super().closeEvent(event)

    def reject(self):
        self.disconnect()
        super().reject()

    # ---------------------------------------------------------- files
    def _on_files(self, files: list) -> None:
        self.offers = files
        self.list.clear()
        for offer in files:
            name = S.safe_name(offer.get("name"))
            item = QListWidgetItem(f"{name}    ·    {human(offer.get('size') or 0)}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, offer)
            self.list.addItem(item)
        self.files_label.setText(f"Files offered by the other PC ({len(files)})" if files else
                                 "Files offered by the other PC: none yet (they add them under SEND TO PHONE)")

    def _on_progress(self, label: str, done: int, total: int) -> None:
        self.prog_label.setText(f"{label}  {human(done)} / {human(total)}")
        self.bar.set_value(done / total if total else 1.0)

    def _cancel(self) -> None:
        self.cancel_flag = True

    def download_ticked(self) -> None:
        client = self.client
        chosen = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                  if self.list.item(i).checkState() == Qt.CheckState.Checked]
        if client is None or not chosen or self.busy:
            return
        self.busy, self.cancel_flag = True, False
        self._render()
        folder = self.save_dir()

        def run():
            saved = 0
            try:
                for offer in chosen:
                    total = int(offer.get("size") or 0)
                    label = f"↓ {S.safe_name(offer.get('name'))}"
                    client.download(offer, folder, lambda done, t=total, lb=label: self.sig.progress.emit(lb, done, t),
                                    lambda: self.cancel_flag)
                    saved += 1
                self.sig.finished.emit(f"Downloaded {saved} file{'s' if saved != 1 else ''} to {folder}", "ok")
            except P.PeerError as exc:
                self.sig.finished.emit(f"Download stopped after {saved}: {exc}", "warn" if self.cancel_flag else "error")
            except OSError as exc:
                self.sig.finished.emit(f"Download failed: {exc.strerror or exc}", "error")
        self._thread(run)

    def send_files(self) -> None:
        client = self.client
        if client is None or self.busy:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Send files to the other PC")
        if not paths:
            return
        self.busy, self.cancel_flag = True, False
        self._render()

        def run():
            sent = 0
            try:
                for path in paths:
                    p = Path(path)
                    total = p.stat().st_size
                    label = f"↑ {p.name}"
                    client.upload(p, lambda done, t=total, lb=label: self.sig.progress.emit(lb, done, t),
                                  lambda: self.cancel_flag)
                    sent += 1
                self.sig.finished.emit(f"Sent {sent} file{'s' if sent != 1 else ''}.", "ok")
            except P.PeerError as exc:
                self.sig.finished.emit(f"Sending stopped after {sent}: {exc}", "warn" if self.cancel_flag else "error")
            except OSError as exc:
                self.sig.finished.emit(f"Sending failed: {exc.strerror or exc}", "error")
        self._thread(run)

    # ---------------------------------------------------------- text
    def show_text(self) -> None:
        if self.inbox is None:
            self.inbox = TextInbox(self, send=self._send_text, title="Text · other PC")
            for entry in self.texts:
                self.inbox.add(entry)
        self.inbox.show()
        self.inbox.raise_()
        self.inbox.activateWindow()
        self.text_btn.setText("TEXT")

    def _send_text(self, text: str) -> dict:
        client = self.client
        if client is None or not self.allowed:
            raise P.PeerError("not connected")
        clean = S.clean_text(text)
        client.send_text(clean)                     # quick control call; runs on the UI thread by design
        entry = {"text": clean, "at": time.time(), "name": client.remote_name}
        self.texts.append(dict(entry, mine=True))
        return entry

    def _on_texts(self, texts: list) -> None:
        name = self.client.remote_name if self.client else "PC"
        for t in texts:
            entry = {"text": t["text"], "at": t["at"], "name": name}
            self.texts.append(entry)
            if self.inbox is not None:
                self.inbox.add(entry)
        if texts and (self.inbox is None or not self.inbox.isVisible()):
            self.text_btn.setText(f"TEXT · {len(texts)} NEW")


class PairedDevicesDialog(NeonDialog):
    """Remembered PCs: their name, PC key and last connection; rename or forget them."""

    def __init__(self, identity: P.Identity, peers: P.PeerStore, parent=None):
        super().__init__("Paired devices", parent, resizable=True)
        self.peers = peers
        self.setMinimumSize(620, 380)
        mine = QLabel(f"This PC's key: {identity.fingerprint}   (compare it on the other PC when you pair)")
        mine.setFont(T.head_font(10, QFont.Weight.DemiBold, 1.0))
        self.root.addWidget(mine)
        note = QLabel("A paired PC is recognised by its key, not its name or address. It connects without the Allow "
                      "prompt, but still needs a fresh pair code each time: the internet link is new for every "
                      "session and NEON uses no server of its own. Forget a PC to make it ask again.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "PC key", "Last connected"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.root.addWidget(self.table, 1)
        row = QHBoxLayout()
        rename = GlowButton("RENAME", "sliders", "cyan", "outline")
        rename.clicked.connect(self._rename)
        forget = GlowButton("FORGET", "trash", "red", "outline")
        forget.clicked.connect(self._forget)
        close = GlowButton("CLOSE", "check", "cyan", "solid", "cyan2")
        close.clicked.connect(self.accept)
        for b in (rename, forget):
            b.setFixedSize(130, 40)
            row.addWidget(b)
        row.addStretch(1)
        close.setFixedSize(130, 40)
        row.addWidget(close)
        self.root.addLayout(row)
        self._fill()

    def _fill(self) -> None:
        items = self.peers.items()
        self.table.setRowCount(len(items))
        for r, (key, entry) in enumerate(items):
            last = time.strftime("%d %b %Y, %H:%M", time.localtime(entry.get("last", 0))) if entry.get("last") else "—"
            for c, text in enumerate((entry.get("name", "PC"), P.fingerprint(S.b64d(key)), last)):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, key)
                self.table.setItem(r, c, cell)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def _selected(self) -> str:
        row = self.table.currentRow()
        cell = self.table.item(row, 0) if row >= 0 else None
        return cell.data(Qt.ItemDataRole.UserRole) if cell else ""

    def _rename(self) -> None:
        key = self._selected()
        if not key:
            return
        name, ok = QInputDialog.getText(self, "Rename PC", "Name:", text=self.table.item(self.table.currentRow(), 0)
                                        .text())
        if ok and name.strip():
            self.peers.rename(key, name)
            self._fill()

    def _forget(self) -> None:
        key = self._selected()
        if key:
            self.peers.forget(key)
            self._fill()
