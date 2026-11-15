"""The update window (UPDATE NOW -> download with progress -> ready -> INSTALL & RESTART) and the window that shows
what changed after NEON was updated."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTextBrowser

from . import APP_VERSION
from . import theme as T
from . import updater as U
from .dialogs import NeonDialog
from .share_ui import Bar
from .widgets import GlowButton


def _notes_view(text: str) -> QTextBrowser:
    view = QTextBrowser()
    view.setObjectName("composeBox")                    # the dark editor style
    view.setOpenLinks(False)                            # release notes are shown, never followed
    view.setOpenExternalLinks(False)
    # images (the banner at the top of release notes) are dropped: nothing is fetched from the web here
    text = "\n".join(line for line in (text or "").splitlines() if not line.lstrip().startswith("!["))
    view.setMarkdown(text.strip() or "No notes for this version.")
    view.setMinimumHeight(220)
    return view


class _Signals(QObject):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)


def _size(n: float) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


class UpdateDialog(NeonDialog):
    """One window for the whole update: what is new, the download, then the install."""

    def __init__(self, info: dict, folder: Path, exe: Path, quit_app: Callable[[], None], parent=None):
        super().__init__("Update available", parent)
        self.setMinimumWidth(620)
        self.info, self.folder, self.exe, self.quit_app = info, Path(folder), Path(exe), quit_app
        self.msi: Path | None = None
        self.cancel = threading.Event()
        self.started = 0.0
        self.sig = _Signals()
        self.sig.progress.connect(self._progress)
        self.sig.done.connect(self._ready)
        self.sig.failed.connect(self._failed)

        head = QLabel(f"NEON Torrent {info['version']} is available. You have {APP_VERSION}.")
        head.setFont(T.head_font(12, QFont.Weight.DemiBold, 1.0))
        self.root.addWidget(head)
        self.root.addWidget(_notes_view(info.get("notes", "")), 1)
        self.status = QLabel(f"Download size {_size(info['size'])}. Your torrents and settings are kept.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.root.addWidget(self.status)
        self.bar = Bar(10)
        self.bar.hide()
        self.root.addWidget(self.bar)
        row = QHBoxLayout()
        self.later = GlowButton("LATER", "close", "muted", "outline")
        self.later.clicked.connect(self.reject)
        row.addWidget(self.later)
        row.addStretch(1)
        self.action = GlowButton("UPDATE NOW", "download", "green", "solid")
        self.action.clicked.connect(self._start)
        for b, w in ((self.later, 130), (self.action, 230)):
            b.setFixedSize(w, 46)
        row.addWidget(self.action)
        self.root.addLayout(row)
        self.finished.connect(lambda _r: self.cancel.set() if self.msi is None else None)

    # ---------------------------------------------------------- download
    def _start(self) -> None:
        self.action.setEnabled(False)
        self.action.setText("DOWNLOADING…")
        self.later.setText("CANCEL")
        self.bar.show()
        self.started = time.monotonic()
        self.cancel.clear()

        def run():
            try:
                path = U.download(self.info, self.folder, self.cancel.is_set, self.sig.progress.emit)
                self.sig.done.emit(str(path))
            except Exception as exc:                                  # shown in the window, never raised
                self.sig.failed.emit(str(exc))
        threading.Thread(target=run, daemon=True, name="neon-update-download").start()

    def _progress(self, done: int, total: int) -> None:
        self.bar.set_value(done / total if total else 0)
        elapsed = max(0.1, time.monotonic() - self.started)
        speed = done / elapsed
        left = (total - done) / speed if speed > 0 else 0
        self.status.setText(f"Downloading… {done * 100 // max(1, total)}%  ·  {_size(done)} of {_size(total)}  ·  "
                            f"{speed / 1024 / 1024:.1f} MB/s  ·  {int(left)} s left")

    def _failed(self, message: str) -> None:
        self.bar.hide()
        self.status.setText(f"The update could not be downloaded: {message}")
        self.status.setStyleSheet(f"color: {T.hexc('red')};")
        self.action.setText("TRY AGAIN")
        self.action.setEnabled(True)
        self.later.setText("LATER")

    # ---------------------------------------------------------- install
    def _ready(self, path: str) -> None:
        self.msi = Path(path)
        self.bar.set_value(1.0)
        self.status.setText("Ready to install: downloaded and checked (GitHub SHA-256, NEON package, version). "
                            "NEON restarts to finish; Windows asks you to confirm the install.")
        self.status.setStyleSheet(f"color: {T.hexc('green')};")
        self.action.setText("INSTALL & RESTART")
        self.action.setEnabled(True)
        self.action.clicked.disconnect()
        self.action.clicked.connect(self._install)
        self.later.setText("LATER")

    def _install(self) -> None:
        U.save_notes(self.folder, self.info["version"], self.info.get("notes", ""))
        U.apply(self.msi, self.exe, self.folder)
        self.accept()
        self.quit_app()


class UpdatedDialog(NeonDialog):
    """Shown once, at the first start after an update: the version and what changed."""

    def __init__(self, notes: str, parent=None):
        super().__init__("NEON updated", parent)
        self.setMinimumWidth(620)
        head = QLabel(f"NEON Torrent is now {APP_VERSION}. Here is what changed:")
        head.setFont(T.head_font(12, QFont.Weight.DemiBold, 1.0))
        self.root.addWidget(head)
        self.root.addWidget(_notes_view(notes), 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = GlowButton("CLOSE", "check", "cyan", "solid", "cyan2")
        close.setFixedSize(140, 44)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self.root.addLayout(row)



