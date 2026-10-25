"""Frameless neon dialogs: Settings, Add torrent, torrent Details/Settings, speed limits and the Shield map."""
from __future__ import annotations

import html
import shutil
import sys
import threading
import time
from pathlib import Path

import libtorrent as lt
from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMenu, QPlainTextEdit, QScrollArea, QSizeGrip, QSpinBox, QStackedWidget,
                               QTableView, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout,
                               QWidget)

from . import APP_NAME, APP_VERSION
from . import theme as T
from .engine import DEFAULT_BLOCKED, kind_for, pretty_title
from .shield import MB_DETECTIONS
from .icons import paint_badge, paint_logo
from .widgets import GlowButton, NeonBackground, NeonPanel, WindowButton

KEY_ROLE = Qt.ItemDataRole.UserRole + 10
SORT_ROLE = Qt.ItemDataRole.UserRole + 11
# the project root in a checkout, the package root in the MSIX (tools/make_msix.py copies the file there)
NOTICES_FILE = Path(__file__).resolve().parents[2] / "THIRD-PARTY-NOTICES.md"


class NeonDialog(QDialog):
    def __init__(self, title: str, parent=None, resizable: bool = False):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.bg = NeonBackground(self)
        outer.addWidget(self.bg)
        self.root = QVBoxLayout(self.bg)
        self.root.setContentsMargins(22, 14, 22, 20)
        self.root.setSpacing(14)
        bar = QHBoxLayout()
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("dialogTitle")
        self.title_label.setFont(T.head_font(13, QFont.Weight.DemiBold, 2.2))
        bar.addWidget(self.title_label)
        bar.addStretch(1)
        self.resizable = resizable
        if resizable:
            self.max_btn = WindowButton("max")
            self.max_btn.clicked.connect(self.toggle_maximized)
            bar.addWidget(self.max_btn)
        close = WindowButton("close", danger=True)
        close.clicked.connect(self.reject)
        bar.addWidget(close)
        self.root.addLayout(bar)
        self.grip = None
        if resizable:
            # drag the bottom-right corner (or any edge via the grip) to make the dialog bigger
            self.grip = QSizeGrip(self.bg)
            self.grip.setFixedSize(18, 18)
            self.grip.setToolTip("Drag to resize")

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        if self.resizable:
            self.max_btn.icon_name = "restore" if self.isMaximized() else "max"
            self.max_btn.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.grip is not None:
            self.grip.move(self.bg.width() - self.grip.width() - 4, self.bg.height() - self.grip.height() - 4)
            self.grip.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 56:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.resizable and event.position().y() < 56:
            self.toggle_maximized()
        super().mouseDoubleClickEvent(event)


class RecordModel(QAbstractTableModel):
    """Rows keyed by a stable id, updated in place so sorting and selection survive live refreshes.
    Each row: {"key": str, "cells": [display text], "sort": [sort value]}, plus optional "checked" (bool, for the
    check column) and "colors" ({column: QColor})."""
    check_toggled = Signal(str, bool)

    def __init__(self, headers: list[str], parent=None, check_column: int = -1):
        super().__init__(parent)
        self.headers = headers
        self.check_column = check_column
        self.rows: list[dict] = []

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid() and index.column() == self.check_column:
            base |= Qt.ItemFlag.ItemIsUserCheckable
        return base

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or index.column() != self.check_column or role != Qt.ItemDataRole.CheckStateRole:
            return False
        row = self.rows[index.row()]
        on = Qt.CheckState(value) == Qt.CheckState.Checked
        row["checked"] = on
        self.dataChanged.emit(index, index)
        self.check_toggled.emit(row["key"], on)
        return True

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row["cells"][index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            # file names, tracker URLs and peer clients come from the network: never let Qt render them as rich text
            text = str(row["cells"][index.column()])
            return "<qt>" + html.escape(text) + "</qt>" if text else None
        if role == SORT_ROLE:
            return row["sort"][index.column()]
        if role == KEY_ROLE:
            return row["key"]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == self.check_column:
            return Qt.CheckState.Checked if row.get("checked") else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.ForegroundRole:
            return (row.get("colors") or {}).get(index.column())
        return None

    def update_rows(self, rows: list[dict]) -> None:
        wanted = {r["key"] for r in rows}
        for i in range(len(self.rows) - 1, -1, -1):
            if self.rows[i]["key"] not in wanted:
                self.beginRemoveRows(QModelIndex(), i, i)
                self.rows.pop(i)
                self.endRemoveRows()
        position = {r["key"]: i for i, r in enumerate(self.rows)}
        fresh = []
        for row in rows:
            i = position.get(row["key"])
            if i is None:
                fresh.append(row)
            elif (self.rows[i]["cells"], self.rows[i].get("checked")) != (row["cells"], row.get("checked")):
                self.rows[i] = row
                self.dataChanged.emit(self.index(i, 0), self.index(i, len(self.headers) - 1))
        if fresh:
            start = len(self.rows)
            self.beginInsertRows(QModelIndex(), start, start + len(fresh) - 1)
            self.rows.extend(fresh)
            self.endInsertRows()


class RecordTable(QTableView):
    """Sortable (click a header), resizable (drag a header divider, double-click to fit) and movable columns."""

    def __init__(self, headers: list[str], widths: list[int], sort_column: int = -1,
                 descending: bool = True, check_column: int = -1, parent=None):
        super().__init__(parent)
        self.source = RecordModel(headers, self, check_column)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.source)
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setDynamicSortFilter(True)
        self.setModel(self.proxy)
        self.setObjectName("detailTable")
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setSectionsMovable(True)
        hh.setStretchLastSection(True)
        hh.setHighlightSections(False)
        hh.setMinimumSectionSize(40)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSortIndicatorShown(True)
        hh.setToolTip("Click to sort · drag a divider to resize · double-click a divider to fit · drag to reorder")
        for col, width in enumerate(widths):
            self.setColumnWidth(col, width)
        self.setSortingEnabled(True)
        if sort_column >= 0:
            self.sortByColumn(sort_column, Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)

    def update_rows(self, rows: list[dict]) -> None:
        self.source.update_rows(rows)

    def selected_keys(self) -> list[str]:
        return [i.data(KEY_ROLE) for i in self.selectionModel().selectedRows() if i.data(KEY_ROLE)]

    def current_key(self) -> str:
        index = self.currentIndex()
        return index.data(KEY_ROLE) if index.isValid() else ""


class SettingsDialog(NeonDialog):
    scanner_status = Signal(str)               # filled in from a worker thread (Defender check takes ~1 s)

    def __init__(self, prefs: dict, parent=None):
        super().__init__("Preferences", parent)
        self.setMinimumWidth(660)
        tabs = QTabWidget()
        tabs.setObjectName("neonTabs")

        def page() -> tuple[QWidget, QFormLayout]:
            widget = QWidget()
            form = QFormLayout(widget)
            form.setContentsMargins(20, 22, 20, 16)
            form.setHorizontalSpacing(22)
            form.setVerticalSpacing(14)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return widget, form

        def add(form: QFormLayout, label: str, widget: QWidget) -> None:
            lab = QLabel(label.upper())
            lab.setObjectName("formLabel")
            form.addRow(lab, widget)

        def note(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setWordWrap(True)
            lab.setObjectName("muted")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return lab

        # --- general
        self.theme = QComboBox()
        self.theme.addItems(list(T.THEMES.keys()))
        self.theme.setCurrentText(prefs.get("theme", "Cyberpunk"))
        folder_box = QWidget()
        fl = QHBoxLayout(folder_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(8)
        self.folder = QLineEdit(prefs["download_dir"])
        self.folder.setReadOnly(True)
        browse = GlowButton("BROWSE", "folder", "cyan", "outline")
        browse.setFixedHeight(40)
        browse.icon_size = 16
        browse.clicked.connect(self._browse)
        fl.addWidget(self.folder, 1)
        fl.addWidget(browse)
        self.tray = QCheckBox("Keep running in the system tray when the window is closed")
        self.tray.setChecked(bool(prefs.get("close_to_tray", False)))
        self.notify = QCheckBox("Show a notification when a download completes")
        self.notify.setChecked(bool(prefs.get("notify_complete", True)))
        general, gf = page()
        add(gf, "Theme", self.theme)
        add(gf, "Download folder", folder_box)
        add(gf, "", self.tray)
        add(gf, "", self.notify)
        gf.addRow("", note("A new folder applies to torrents added from now on. Use “Move data…” in a "
                           "torrent’s menu to relocate existing downloads."))
        tabs.addTab(general, "GENERAL")

        # --- network
        self.up = self._spin(0, 1_000_000, prefs["upload_kib"], " KiB/s", "Unlimited")
        self.down = self._spin(0, 1_000_000, prefs.get("download_kib", 0), " KiB/s", "Unlimited")
        self.port = self._spin(1024, 65535, prefs.get("listen_port", 6881), "", "")
        self.conns = self._spin(20, 5000, prefs.get("max_connections", 500), "", "")
        network, nf = page()
        add(nf, "Upload cap", self.up)
        add(nf, "Download cap", self.down)
        add(nf, "Listen port", self.port)
        add(nf, "Max connections", self.conns)
        tabs.addTab(network, "NETWORK")

        # --- shield
        self.learn = QCheckBox("Learn from Malwarebytes — never contact an IP or tracker it flagged again")
        self.learn.setChecked(bool(prefs.get("shield_learn", True)))
        self.scope = QComboBox()
        for value, text, tip in (
                ("network", "Whole network on first flag (recommended)",
                 "Blocks the flagged IP, its /24, and its whole network on the first flag when that network is "
                 "hosting/VPN-sized (2M IPs or fewer).\nFewest alerts. Big ISPs (Jio, Airtel, BSNL…) are never "
                 "blocked whole, only the flagged /24."),
                ("smart", "Balanced — whole network after 2 flags",
                 "Blocks the flagged IP and its /24. A hosting/VPN network flagged twice is blocked whole."),
                ("ip", "Exact IP only", "Blocks only the exact flagged address: most peers, most repeat alerts.")):
            self.scope.addItem(text, value)
            self.scope.setItemData(self.scope.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
        self.scope.setCurrentIndex(max(0, self.scope.findData(prefs.get("shield_scope", "network"))))
        self.file_only = QCheckBox("File-only network — contact only your torrents’ trackers and peers")
        self.file_only.setToolTip("Turns off DHT, Local Peer Discovery, UPnP / NAT-PMP port mapping and IPv6 "
                                  "listening,\nso the client never talks to nodes unrelated to your downloads.")
        self.file_only.setChecked(bool(prefs.get("file_only", True)))
        self.use_dht = QCheckBox("Still use DHT — more peers for magnets, but talks to many unrelated nodes")
        self.use_dht.setChecked(bool(prefs.get("use_dht", False)))
        self.use_dht.setEnabled(self.file_only.isChecked())
        self.file_only.toggled.connect(self.use_dht.setEnabled)
        self.incoming = QCheckBox("Accept incoming peers (UPnP / NAT-PMP port mapping) — faster, still Shield-filtered")
        self.incoming.setToolTip("Lets peers of your torrents connect to you. They must present one of your "
                                 "torrents' info-hashes\nand pass the same IP filter as outgoing peers.")
        self.incoming.setChecked(bool(prefs.get("accept_incoming", True)))
        self.avoid_dc = QCheckBox("Refuse VPN / datacenter peers before contact (stops most antivirus alerts)")
        self.avoid_dc.setToolTip("Peers inside known VPN and datacenter ranges (X4BNet lists, refreshed daily) are "
                                 "never contacted.\nIn this PC's alert history 11 of 13 flagged peers were in these "
                                 "ranges. Web-seed mirrors stay reachable.")
        self.avoid_dc.setChecked(bool(prefs.get("shield_avoid_dc", True)))
        self.keep_seedboxes = QCheckBox("…but keep seedbox hosts (Hetzner, OVH, Scaleway) — fast seeders")
        self.keep_seedboxes.setChecked(bool(prefs.get("shield_keep_seedboxes", True)))
        self.keep_seedboxes.setEnabled(self.avoid_dc.isChecked())
        self.avoid_dc.toggled.connect(self.keep_seedboxes.setEnabled)
        self.blocked = QPlainTextEdit("\n".join(prefs.get("blocked_hosts", DEFAULT_BLOCKED)))
        self.blocked.setPlaceholderText("One tracker domain, IP, or CIDR range per line")
        self.blocked.setToolTip("Trackers on these domains are never contacted.\n"
                                "Peers and trackers on these IPs/ranges are blocked.\n"
                                "A domain also blocks its subdomains.")
        self.blocked.setFixedHeight(84)
        self.blocked.setObjectName("blocklist")
        av = "found — watching its detections" if MB_DETECTIONS.is_dir() else "not found on this PC"
        exe = Path(sys.executable)
        shield, sf = page()
        add(sf, "Antivirus", self.learn)
        add(sf, "Peers", self.avoid_dc)
        add(sf, "", self.keep_seedboxes)
        sf.addRow("", note(f"Malwarebytes {av}."))
        add(sf, "Learning", self.scope)
        scope_note = note("")
        sync = lambda *_: scope_note.setText(self.scope.currentData(Qt.ItemDataRole.ToolTipRole) or "")  # noqa: E731
        self.scope.currentIndexChanged.connect(sync)
        sync()
        sf.addRow("", scope_note)
        add(sf, "Network", self.file_only)
        add(sf, "", self.use_dht)
        add(sf, "", self.incoming)
        add(sf, "Blocklist", self.blocked)
        sf.addRow("", note("To silence Malwarebytes for this app completely: Malwarebytes → Settings → Allow List → "
                           f"Add → Allow an application to connect to the internet → {exe}"))
        tabs.addTab(shield, "SHIELD")

        # --- safety (Download Guard)
        self.g_skip = QCheckBox("Skip dangerous files automatically (disguised programs, shortcuts, name tricks)")
        self.g_skip.setToolTip("Never downloads: double extensions (movie.mp4.exe), shortcuts (.lnk/.url), names with "
                               "hidden Unicode direction characters,\nprograms or scripts inside media torrents, and "
                               "symbolic links. You can re-enable a file in Details > Files.")
        self.g_skip.setChecked(bool(prefs.get("guard_skip", True)))
        self.g_strict = QCheckBox("Strict — never download any program, script or macro document")
        self.g_strict.setChecked(bool(prefs.get("guard_strict", False)))
        self.g_motw = QCheckBox("Mark finished files as from the internet (SmartScreen checks programs)")
        self.g_motw.setToolTip("Writes Mark-of-the-Web (Zone.Identifier) like a browser does, so Windows SmartScreen "
                               "and Office Protected View\ncheck a program or document before it can run.")
        self.g_motw.setChecked(bool(prefs.get("guard_motw", True)))
        self.g_scan = QCheckBox("Scan finished downloads (Defender when active · VirusTotal with a key)")
        self.g_scan.setChecked(bool(prefs.get("guard_scan", True)))
        self.g_pause = QCheckBox("Stop seeding and alert me when a threat is found")
        self.g_pause.setChecked(bool(prefs.get("guard_pause_threat", True)))
        self.g_vt = QLineEdit(prefs.get("guard_vt_key", ""))
        self.g_vt.setEchoMode(QLineEdit.EchoMode.Password)
        self.g_vt.setPlaceholderText("Optional VirusTotal API key (free account) — only file hashes are sent")
        safety, gf = page()
        add(gf, "Before", self.g_skip)
        add(gf, "", self.g_strict)
        add(gf, "After", self.g_motw)
        add(gf, "", self.g_scan)
        add(gf, "", self.g_pause)
        add(gf, "VirusTotal", self.g_vt)
        self.scanner_note = note("Checking which antivirus can scan downloads on this PC…")
        gf.addRow("", self.scanner_note)
        gf.addRow("", note("NeonTorrent never opens or runs a downloaded file. Pieces are hash-verified against the "
                           "torrent, so what you get is exactly what the uploader published — whether that is safe "
                           "depends on the uploader, which is what these checks are for."))
        tabs.addTab(safety, "SAFETY")
        if prefs.get("_open_tab") == "safety":
            tabs.setCurrentWidget(safety)
        self.scanner_status.connect(self.scanner_note.setText)
        threading.Thread(target=self._check_scanner, daemon=True).start()
        if prefs.get("_open_tab") == "shield":
            tabs.setCurrentWidget(shield)
        self.root.addWidget(tabs)

        buttons = QHBoxLayout()
        about = GlowButton("ABOUT", "info", "muted", "outline")
        about.setMinimumWidth(130)
        about.clicked.connect(lambda: AboutDialog(self).exec())
        buttons.addWidget(about)
        buttons.addStretch(1)
        cancel = GlowButton("CANCEL", "", "muted", "outline")
        cancel.clicked.connect(self.reject)
        save = GlowButton("SAVE", "check", "cyan", "solid", "cyan2")
        save.clicked.connect(self.accept)
        save.setDefault(True)
        for b in (cancel, save):
            b.setMinimumWidth(130)
            buttons.addWidget(b)
        self.root.addLayout(buttons)

    @staticmethod
    def _spin(lo: int, hi: int, value: int, suffix: str, special: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(int(value))
        spin.setSuffix(suffix)
        if special:
            spin.setSpecialValueText(special)
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        spin.setAccelerated(True)
        return spin

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Download folder", self.folder.text())
        if folder:
            self.folder.setText(str(Path(folder)))

    def _check_scanner(self) -> None:
        from . import guard as G
        cli = G.defender_cli()
        products = [p for p in G.antivirus_products() if p]
        others = [p for p in products if "defender" not in p.lower()]
        if cli:
            text = "Scanner: Microsoft Defender is active and will scan every finished download."
        elif others:
            text = (f"Scanner: Microsoft Defender is off because {', '.join(others)} is your antivirus; "
                    f"{others[0]} real-time protection checks files as they are written and run. "
                    "Add a VirusTotal key for a multi-engine check of programs.")
        else:
            text = "Scanner: no active antivirus found. Turn on Microsoft Defender in Windows Security."
        self.scanner_status.emit(text)

    def values(self) -> dict:
        return {
            "theme": self.theme.currentText(), "download_dir": self.folder.text(),
            "upload_kib": self.up.value(), "download_kib": self.down.value(), "listen_port": self.port.value(),
            "max_connections": self.conns.value(), "close_to_tray": self.tray.isChecked(),
            "notify_complete": self.notify.isChecked(),
            "shield_learn": self.learn.isChecked(), "shield_scope": self.scope.currentData(),
            "file_only": self.file_only.isChecked(), "use_dht": self.use_dht.isChecked(),
            "accept_incoming": self.incoming.isChecked(),
            "shield_avoid_dc": self.avoid_dc.isChecked(), "shield_keep_seedboxes": self.keep_seedboxes.isChecked(),
            "guard_skip": self.g_skip.isChecked(), "guard_strict": self.g_strict.isChecked(),
            "guard_motw": self.g_motw.isChecked(), "guard_scan": self.g_scan.isChecked(),
            "guard_pause_threat": self.g_pause.isChecked(), "guard_vt_key": self.g_vt.text().strip(),
            "blocked_hosts": [line.strip() for line in self.blocked.toPlainText().splitlines() if line.strip()],
        }


class LogoMark(QWidget):
    def __init__(self, side: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(side, side)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_logo(p, QRectF(self.rect()), T.c("cyan"), T.c("magenta"))
        p.end()


class AboutDialog(NeonDialog):
    """Version, licence summary and the full third-party notices that ship with the app."""

    def __init__(self, parent=None):
        super().__init__("About", parent, resizable=True)
        self.resize(760, 640)
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(LogoMark(56))
        name = QLabel(APP_NAME.upper())
        name.setFont(T.head_font(18, QFont.Weight.Bold, 3))
        version = QLabel(f"Version {APP_VERSION} · Python {sys.version.split()[0]} · Qt {pyside_version} · "
                         f"libtorrent {lt.__version__.rsplit('.', 1)[0]}")
        version.setObjectName("muted")
        version.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(name)
        titles.addWidget(version)
        head.addLayout(titles, 1)
        self.root.addLayout(head)
        summary = QLabel("NEON Torrent is built on open-source software, each part under its own licence: Qt and "
                         "PySide6 (LGPL-3.0, loaded as separate files you may replace), libtorrent (BSD-3-Clause), "
                         "Boost (BSL-1.0), Python (PSF 2.0), OpenSSL (Apache-2.0), and libffi, bzip2, zlib, expat "
                         "and others (MIT, BSD-style, zlib). The full notices and licence texts follow.")
        summary.setWordWrap(True)
        summary.setObjectName("muted")
        self.root.addWidget(summary)
        self.notices = QTextBrowser()
        self.notices.setObjectName("notices")
        self.notices.setOpenExternalLinks(True)
        self.notices.setPlainText("Loading the notices…")
        self.root.addWidget(self.notices, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = GlowButton("CLOSE", "check", "cyan", "solid", "cyan2")
        close.setMinimumWidth(130)
        close.clicked.connect(self.accept)
        close.setDefault(True)
        buttons.addWidget(close)
        self.root.addLayout(buttons)
        QTimer.singleShot(0, self._load_notices)   # 120 KB of Markdown: show the window first

    def _load_notices(self) -> None:
        try:
            self.notices.setMarkdown(NOTICES_FILE.read_text(encoding="utf-8"))
        except OSError:
            self.notices.setPlainText(f"{NOTICES_FILE.name} is missing from this installation.")


class FirstRunDialog(NeonDialog):
    """Shown once, before the main window, when settings.json has no download folder yet."""

    def __init__(self, default_dir: str, parent=None):
        super().__init__("Setup", parent)
        self.setFixedWidth(600)
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(LogoMark(48))
        name = QLabel(f"WELCOME TO {APP_NAME.upper()}")
        name.setFont(T.head_font(15, QFont.Weight.Bold, 2.4))
        head.addWidget(name, 1)
        self.root.addLayout(head)
        ask = QLabel("WHERE SHOULD DOWNLOADS GO?")
        ask.setObjectName("formLabel")
        self.root.addWidget(ask)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.folder = QLineEdit(default_dir)
        self.folder.setReadOnly(True)
        browse = GlowButton("BROWSE", "folder", "cyan", "outline")
        browse.setFixedHeight(40)
        browse.icon_size = 16
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        self.root.addLayout(row)
        panel = NeonPanel("cyan", 0.6)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(18, 14, 18, 14)
        pl.setSpacing(6)
        mode = QLabel("FILE-ONLY NETWORK IS ON")
        mode.setFont(T.head_font(10, QFont.Weight.DemiBold, 1.6))
        mode.setStyleSheet(f"color: {T.hexc('cyan')};")
        text = QLabel("NEON talks only to your torrents' trackers and peers. DHT and Local Peer Discovery are off, "
                      "so it never contacts nodes unrelated to your downloads, and the Shield filters every peer "
                      "before it connects. Magnets with no trackers may find no peers; you can turn DHT back on, "
                      "and change this folder, in Preferences.")
        text.setWordWrap(True)
        text.setObjectName("muted")
        pl.addWidget(mode)
        pl.addWidget(text)
        self.root.addWidget(panel)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        start = GlowButton("START", "check", "cyan", "solid", "cyan2")
        start.setMinimumWidth(150)
        start.clicked.connect(self.accept)
        start.setDefault(True)
        buttons.addWidget(start)
        self.root.addLayout(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Download folder", self.folder.text())
        if folder:
            self.folder.setText(str(Path(folder)))


class BadgeHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind, self.title, self.sub = "magnet", "", ""
        self.setMinimumHeight(56)

    def set_info(self, kind: str, title: str, sub: str) -> None:
        self.kind, self.title, self.sub = kind, title, sub
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_badge(p, QRectF(0, 4, 48, 48), self.kind)
        p.setFont(T.font(13, QFont.Weight.DemiBold))
        p.setPen(T.c("text"))
        p.drawText(QRectF(66, 2, self.width() - 66, 28), Qt.AlignmentFlag.AlignVCenter, self.title)
        p.setFont(T.font(9.5))
        p.setPen(T.c("muted"))
        p.drawText(QRectF(66, 30, self.width() - 66, 22), Qt.AlignmentFlag.AlignVCenter, self.sub)


# libtorrent file priorities offered in the UI, highest first, with their colour in the Priority column
PRIORITIES = [(7, "High", "magenta"), (4, "Normal", "cyan"), (1, "Low", "yellow"), (0, "Don't download", "muted")]


def priority_name(priority: int) -> str:
    """libtorrent knows 0..7; values other clients leave behind (2, 3, 5, 6) show as the nearest level."""
    return "Don't download" if priority <= 0 else "Low" if priority <= 2 else "Normal" if priority <= 5 else "High"


def display_paths(paths: list[str]) -> list[str]:
    """Windows-style paths without the torrent's own top folder when every file sits in it (the header names it)."""
    split = [p.replace("\\", "/").split("/", 1) for p in paths]
    if len(split) > 1 and all(len(s) == 2 for s in split) and len({s[0] for s in split}) == 1:
        return [s[1].replace("/", "\\") for s in split]
    return [p.replace("/", "\\") for p in paths]


def selection_totals(files) -> tuple[int, int]:
    """(files selected, bytes selected): a file is selected when its priority is above Don't download."""
    chosen = [f for f in files if int(f["priority"]) > 0]
    return len(chosen), sum(int(f["size"]) for f in chosen)


def free_space(path: str) -> int | None:
    """Free bytes on the drive holding path, or its nearest existing parent (the folder may not exist yet)."""
    if not path:
        return None
    target = Path(path)
    for candidate in (target, *target.parents):
        try:
            return shutil.disk_usage(candidate).free
        except OSError:
            continue
    return None


def space_note(free: int | None, need: int, drive: str) -> tuple[str, str]:
    """(text, colour key) for the free-space line of the Add dialog."""
    if free is None:
        return f"CANNOT READ THE FREE SPACE ON {drive}", "yellow"
    if free < need:
        return f"NOT ENOUGH SPACE · {T.fmt_bytes(need)} SELECTED, ONLY {T.fmt_bytes(free)} FREE ON {drive}", "red"
    return f"{T.fmt_bytes(need)} SELECTED · {T.fmt_bytes(free)} FREE ON {drive}", "green"


class FileSelector(QWidget):
    """The files of one torrent: checkbox, Priority column, multi-select right-click → Priority, select all/none and
    the selected total. Used by the Add dialog and by Details → Files."""
    changed = Signal(list)                     # [[file index, priority], ...] the user just changed

    def __init__(self, progress: bool = False, parent=None):
        super().__init__(parent)
        self.progress = progress
        self.files: dict[int, dict] = {}
        self._sent: dict[int, tuple[int, float]] = {}   # recent edits, shown until the engine reports them back
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.b_all = GlowButton("ALL", "check", "cyan", "outline")
        self.b_all.setToolTip("Select every file at Normal priority.\n"
                              "Files Download Guard flagged as dangerous stay off: tick them one by one.")
        self.b_none = GlowButton("NONE", "close", "magenta", "outline")
        self.b_none.setToolTip("Don't download any file")
        for button in (self.b_all, self.b_none):
            button.setFixedHeight(32)
            button.icon_size = 14
            bar.addWidget(button)
        bar.addStretch(1)
        self.total = QLabel()
        self.total.setObjectName("formLabel")
        bar.addWidget(self.total)
        layout.addLayout(bar)
        headers = ["FILE", "SIZE"] + (["PROGRESS"] if progress else []) + ["PRIORITY", "SAFETY"]
        widths = [340, 90] + ([90] if progress else []) + [124, 240]
        self.table = RecordTable(headers, widths, sort_column=0, descending=False, check_column=0)
        self.table.setToolTip("Tick the files to download · select several and right-click to set their priority")
        self.table.source.check_toggled.connect(lambda key, on: self._set([int(key)], 4 if on else 0))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.table, 1)
        self.b_all.clicked.connect(self.select_all)
        self.b_none.clicked.connect(lambda: self._set(list(self.files), 0))

    def set_files(self, files: list[dict]) -> None:
        """files: {"index", "path", "size", "priority", "reason", "danger"} (+ "progress" in Details)."""
        now = time.monotonic()
        self._sent = {i: sent for i, sent in self._sent.items() if now - sent[1] < 3}
        self.files = {}
        for f in files:
            f = dict(f)
            index = int(f["index"])
            if index in self._sent:
                f["priority"] = self._sent[index][0]
            self.files[index] = f
        self._refresh()

    def pairs(self) -> list[list[int]]:
        return [[index, int(f["priority"])] for index, f in self.files.items()]

    def select_all(self) -> None:
        self._set([i for i, f in self.files.items() if int(f["priority"]) <= 0 and not f.get("danger")], 4)

    def _set(self, indices: list[int], priority: int) -> None:
        now = time.monotonic()
        changed = []
        for index in indices:
            f = self.files.get(index)
            if f is None or int(f["priority"]) == priority:
                continue
            f["priority"] = priority
            self._sent[index] = (priority, now)
            changed.append([index, priority])
        if changed:
            self._refresh()
            self.changed.emit(changed)

    def _menu(self, pos) -> None:
        indices = [int(k) for k in self.table.selected_keys() if int(k) in self.files]
        if not indices:
            return
        menu = QMenu(self)
        sub = menu.addMenu(f"Priority ({len(indices)} file{'s' if len(indices) != 1 else ''})")
        current = {priority_name(int(self.files[i]["priority"])) for i in indices}
        for value, name, _color in PRIORITIES:
            action = sub.addAction(name, lambda v=value: self._set(indices, v))
            action.setCheckable(True)
            action.setChecked(current == {name})
        menu.addSeparator()
        menu.addAction("Select all", self.select_all)
        menu.addAction("Select none", lambda: self._set(list(self.files), 0))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _refresh(self) -> None:
        colors = {name: color for _value, name, color in PRIORITIES}
        paths = display_paths([f["path"] for f in self.files.values()])
        rows = []
        for (index, f), path in zip(self.files.items(), paths):
            priority = int(f["priority"])
            name = priority_name(priority)
            reason = f.get("reason") or ""
            cells, sort = [path, T.fmt_bytes(f["size"])], [path.casefold(), int(f["size"])]
            if self.progress:
                cells.append(f"{f.get('progress', 0) * 100:.1f}%")
                sort.append(float(f.get("progress", 0)))
            column = len(cells)
            cells += [name, reason]
            sort += [priority, reason]
            tint = {column: T.c(colors[name])}
            if reason:
                tint[column + 1] = T.c("red") if f.get("danger") else T.c("orange")
            rows.append({"key": str(index), "cells": cells, "sort": sort, "checked": priority > 0, "colors": tint})
        self.table.update_rows(rows)
        count, size = selection_totals(self.files.values())
        self.total.setText(f"{count} OF {len(self.files)} FILES · {T.fmt_bytes(size)}")


class AddTorrentDialog(NeonDialog):
    """Opens for every add: save folder, free space and which files to download at what priority. Nothing downloads
    until DOWNLOAD; CANCEL (or closing the dialog) removes the torrent."""
    confirmed = Signal(str, str, list)         # key, save folder, [[file index, priority], ...]
    cancelled = Signal(str)

    def __init__(self, offer: dict, parent=None):
        super().__init__("Add torrent", parent, resizable=True)
        self.key = offer["key"]
        self.ready = False
        self.answered = False
        self.seen = False                      # the torrent has shown up in the list (main window bookkeeping)
        self.resize(900, 640)
        self.header = BadgeHeader()
        self.root.addWidget(self.header)
        where = QLabel("SAVE TO")
        where.setObjectName("formLabel")
        self.root.addWidget(where)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.folder = QLineEdit(offer.get("save_path", ""))
        self.folder.setReadOnly(True)
        browse = GlowButton("BROWSE", "folder", "cyan", "outline")
        browse.setFixedHeight(40)
        browse.icon_size = 16
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        self.root.addLayout(row)
        self.space = QLabel()
        self.space.setFont(T.head_font(9.5, QFont.Weight.DemiBold, 1.2))
        self.root.addWidget(self.space)

        self.stack = QStackedWidget()
        wait = NeonPanel("cyan", 0.5)
        wl = QVBoxLayout(wait)
        wl.setContentsMargins(24, 24, 24, 24)
        wl.addStretch(1)
        self.wait_title = QLabel("FETCHING THE FILE LIST…")
        self.wait_title.setFont(T.head_font(13, QFont.Weight.DemiBold, 2.2))
        self.wait_title.setStyleSheet(f"color: {T.hexc('cyan')};")
        self.wait_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Only the list of files is downloaded now. Nothing else downloads until you press DOWNLOAD.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wl.addWidget(self.wait_title)
        wl.addWidget(hint)
        wl.addStretch(1)
        self.selector = FileSelector()
        self.selector.changed.connect(self._update_space)
        self.stack.addWidget(wait)
        self.stack.addWidget(self.selector)
        self.root.addWidget(self.stack, 1)
        self._dots = 0
        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(450)
        self._wait_timer.timeout.connect(self._tick_wait)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        b_cancel = GlowButton("CANCEL", "close", "magenta", "outline")
        b_cancel.setToolTip("Remove this torrent. Nothing was downloaded.")
        b_cancel.clicked.connect(self.reject)
        self.b_download = GlowButton("DOWNLOAD", "download", "cyan", "solid", "cyan2")
        self.b_download.setMinimumWidth(170)
        self.b_download.clicked.connect(self._download)
        buttons.addWidget(b_cancel)
        buttons.addWidget(self.b_download)
        buttons.addSpacing(14)                     # keep clear of the resize grip
        self.root.addLayout(buttons)
        self.update_offer(offer)

    def update_offer(self, offer: dict) -> None:
        """Called again when the file list arrives; choices the user already made are kept."""
        name = offer.get("name") or "Magnet link"
        if offer.get("ready") and not self.ready:
            self.ready = True
            files = offer.get("files") or []
            total = sum(int(f["size"]) for f in files)
            multi = len(files) > 1
            self.header.set_info(kind_for(name, multi), pretty_title(name, multi),
                                 f"{len(files)} files · {T.fmt_bytes(total)} · {name}/" if multi
                                 else f"{T.fmt_bytes(total)} · {name}")
            self.selector.set_files(files)
            self.stack.setCurrentIndex(1)
            self._wait_timer.stop()
            self.b_download.setDefault(True)
        elif not self.ready:
            self.header.set_info("magnet", name, "magnet · fetching the file list")
            self.stack.setCurrentIndex(0)
            self._wait_timer.start()
        self._update_space()

    def _tick_wait(self) -> None:
        self._dots = (self._dots + 1) % 4
        self.wait_title.setText("FETCHING THE FILE LIST" + "." * self._dots)

    def _update_space(self, *_):
        folder = self.folder.text()
        count, size = selection_totals(self.selector.files.values())
        drive = Path(folder).drive or folder
        if self.ready:
            text, color = space_note(free_space(folder), size, drive)
        else:
            free = free_space(folder)
            text, color = (f"{T.fmt_bytes(free)} FREE ON {drive}" if free is not None else drive), "muted"
        self.space.setText(text)
        self.space.setStyleSheet(f"color: {T.hexc(color)};")
        self.b_download.setEnabled(self.ready and count > 0)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save to", self.folder.text())
        if folder:
            self.folder.setText(str(Path(folder)))
            self._update_space()

    def _download(self) -> None:
        pairs = self.selector.pairs()
        if self.answered or not self.ready or not any(p for _i, p in pairs):
            return
        self.answered = True
        self.confirmed.emit(self.key, self.folder.text(), pairs)
        self.accept()

    def reject(self) -> None:
        if not self.answered:
            self.answered = True
            self.cancelled.emit(self.key)
        super().reject()

    def dismiss(self) -> None:
        """Close without an answer: the app is quitting (the torrent waits for the next start) or it is gone."""
        self.answered = True
        self.close()


class DetailsDialog(NeonDialog):
    priority_changed = Signal(str, list)       # key, [[file index, priority], ...]
    open_folder = Signal(str)
    copy_magnet = Signal(str)

    def __init__(self, row: dict, parent=None):
        super().__init__("Torrent details", parent, resizable=True)
        self.key = row["key"]
        self.row = row
        self.resize(860, 600)
        self.header = BadgeHeader()
        self.root.addWidget(self.header)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("neonTabs")
        self.root.addWidget(self.tabs, 1)

        general = QWidget()
        grid = QGridLayout(general)
        grid.setContentsMargins(18, 18, 18, 18)
        grid.setHorizontalSpacing(26)
        grid.setVerticalSpacing(12)
        self.info: dict[str, QLabel] = {}
        fields = ["Status", "Progress", "Downloaded", "Size", "Down speed", "Up speed", "ETA", "Ratio",
                  "Uploaded", "Seeds", "Peers", "Pieces", "Save path", "Info hash", "Comment", "Created by"]
        for i, name in enumerate(fields):
            lab = QLabel(name.upper())
            lab.setObjectName("formLabel")
            val = QLabel("—")
            val.setTextFormat(Qt.TextFormat.PlainText)        # values come from the torrent: never rich text
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(name in ("Save path", "Comment"))
            r, cpos = (i // 2, (i % 2) * 2) if i < 12 else (6 + (i - 12), 0)
            grid.addWidget(lab, r, cpos)
            grid.addWidget(val, r, cpos + 1, 1, 1 if i < 12 else 3)
            self.info[name] = val
        grid.setRowStretch(20, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.tabs.addTab(general, "GENERAL")

        # all three: click a header to sort, drag a divider to widen (horizontal scroll appears), drag to reorder
        # same checkbox, Priority column and right-click menu as the Add dialog; changes apply at once
        files_page = QWidget()
        fl = QVBoxLayout(files_page)
        fl.setContentsMargins(10, 10, 10, 6)
        self.files = FileSelector(progress=True)
        self.files.changed.connect(lambda pairs: self.priority_changed.emit(self.key, pairs))
        fl.addWidget(self.files)
        self.tabs.addTab(files_page, "FILES")
        self.peers = RecordTable(["ADDRESS", "CLIENT", "PROGRESS", "↓ SPEED", "↑ SPEED"], [300, 230, 96, 110, 110],
                                 sort_column=3)
        self.tabs.addTab(self.peers, "PEERS")
        self.trackers = RecordTable(["TRACKER", "TIER", "STATUS", "SEEDS"], [430, 70, 300, 90],
                                    sort_column=1, descending=False)
        self.tabs.addTab(self.trackers, "TRACKERS")

        buttons = QHBoxLayout()
        b_open = GlowButton("OPEN FOLDER", "folder", "cyan", "outline")
        b_open.clicked.connect(lambda: self.open_folder.emit(self.key))
        b_mag = GlowButton("COPY MAGNET", "magnet", "magenta", "outline")
        b_mag.clicked.connect(lambda: self.copy_magnet.emit(self.key))
        b_close = GlowButton("CLOSE", "", "cyan", "solid", "cyan2")
        b_close.clicked.connect(self.accept)
        buttons.addWidget(b_open)
        buttons.addWidget(b_mag)
        buttons.addStretch(1)
        buttons.addWidget(b_close)
        buttons.addSpacing(14)                     # keep clear of the resize grip
        self.root.addLayout(buttons)
        self.update_row(row)

    def update_row(self, row: dict) -> None:
        self.row = row
        self.header.set_info(row["kind"], row["title"], row["sub"])
        i = self.info
        i["Status"].setText(row["state"] + (f" — {row['error']}" if row["error"] else ""))
        i["Status"].setStyleSheet(f"color: {T.state_color(row['state']).name()}; font-weight: 600;")
        i["Progress"].setText(f"{row['progress'] * 100:.2f}%")
        i["Downloaded"].setText(T.fmt_bytes(row["done"]))
        i["Size"].setText(T.fmt_bytes(row["size"]))
        i["Down speed"].setText(T.fmt_speed(row["down"]))
        i["Up speed"].setText(T.fmt_speed(row["up"]))
        i["ETA"].setText(T.fmt_eta(row["eta"]) if row["state"] == "Downloading" else "—")
        i["Ratio"].setText(f"{row['ratio']:.3f}")
        i["Uploaded"].setText(T.fmt_bytes(row["uploaded"]))
        i["Seeds"].setText(f"{row['seeds']} connected  ({row['list_seeds']} in swarm)")
        i["Peers"].setText(f"{row['peers']} connected  ({row['list_peers']} in swarm)")
        i["Save path"].setText(row["save_path"])
        i["Info hash"].setText(row["key"])

    def update_detail(self, d: dict) -> None:
        if not d or d.get("key") != self.key:
            return
        self.info["Pieces"].setText(d["pieces"])
        self.info["Comment"].setText(d["comment"] or "—")
        self.info["Created by"].setText(d["creator"] or "—")
        files = d["files"]
        self.files.set_files(files)
        self.peers.update_rows([{
            "key": p["ip"],
            "cells": [p["ip"], p["client"], f"{p['progress'] * 100:.0f}%", T.fmt_speed(p["down"]), T.fmt_speed(p["up"])],
            "sort": [_ip_sort(p["ip"].rsplit(":", 1)[0]), p["client"].casefold(), float(p["progress"]), int(p["down"]),
                     int(p["up"])],
        } for p in d["peers"]])
        self.trackers.update_rows([{
            "key": t["url"],
            "cells": [t["url"], str(t["tier"]), t["status"], str(t["seeds"])],
            "sort": [t["url"].casefold(), int(t["tier"]), t["status"].casefold(), int(t["seeds"] or 0)],
        } for t in d["trackers"]])
        self.tabs.setTabText(1, f"FILES ({len(files)})")
        self.tabs.setTabText(2, f"PEERS ({len(d['peers'])})")
        self.tabs.setTabText(3, f"TRACKERS ({len(d['trackers'])})")


class Chip(NeonPanel):
    """Small stat tile used at the top of the Shield dialog."""

    def __init__(self, title: str, color_key: str):
        super().__init__(color_key, 0.45, radius=10, hoverable=True)
        self.setFixedHeight(68)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(0)
        lab = QLabel(title.upper())
        lab.setObjectName("formLabel")
        self.value = QLabel("—")
        self.value.setFont(T.head_font(15, QFont.Weight.DemiBold, 0.6))
        self.value.setStyleSheet(f"color: {T.hexc(color_key)};")
        lay.addWidget(lab)
        lay.addWidget(self.value)


def _ip_sort(ip: str) -> str:
    """Sortable text for IPv4/IPv6 addresses (QVariant cannot carry 128-bit ints)."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        return f"{addr.version}{int(addr):032x}"
    except ValueError:
        return f"9{ip}"


def _peer_text(ip: str, port: int) -> str:
    return f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"


class ShieldDialog(NeonDialog):
    """Connection map: every live peer with its torrent, network and country; refused peers; learned blocks."""
    block = Signal(str, bool)          # ip, whole network
    forget = Signal(list)
    clear_all = Signal()
    open_settings = Signal()

    def __init__(self, parent=None):
        super().__init__("Shield · connection map", parent, resizable=True)
        self.resize(1180, 700)
        self.setMinimumSize(860, 520)
        chips = QHBoxLayout()
        chips.setSpacing(12)
        self.chips: dict[str, Chip] = {}
        for key, title, color in (("peers", "Live peers", "cyan"), ("networks", "Networks", "blue"),
                                  ("countries", "Countries", "purple"), ("refused", "Refused", "red"),
                                  ("learned", "Learned blocks", "yellow"), ("mode", "Network mode", "green")):
            chip = Chip(title, color)
            self.bg.register(chip)
            self.chips[key] = chip
            chips.addWidget(chip)
        self.root.addLayout(chips)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("neonTabs")
        self.live = RecordTable(["TORRENT", "PEER", "CC", "NETWORK", "CLIENT", "FOUND VIA", "DIR", "↓ SPEED",
                                 "↑ SPEED", "HAS"], [230, 160, 44, 240, 150, 110, 92, 90, 90, 60], sort_column=7)
        self.refused = RecordTable(["TIME", "PEER", "TORRENT", "CC", "NETWORK", "WHY"],
                                   [80, 160, 250, 44, 230, 300], sort_column=0)
        self.learned = RecordTable(["TYPE", "BLOCKED", "NETWORK", "CC", "HITS", "WHEN", "SOURCE"],
                                   [120, 220, 270, 44, 56, 140, 220], sort_column=5)
        self.tabs.addTab(self.live, "LIVE PEERS")
        self.tabs.addTab(self.refused, "REFUSED")
        self.tabs.addTab(self.learned, "LEARNED BLOCKS")
        self.tabs.currentChanged.connect(self._sync_buttons)
        self.root.addWidget(self.tabs, 1)

        self.explainer = QLabel(
            "Every peer connection is bound to one torrent by its info-hash, and every piece is hash-checked before "
            "it is written, so nothing but that file's data is accepted. The Shield decides which peers may be "
            "contacted at all: anything Malwarebytes has flagged (and its neighbours) is never dialled again.  "
            "Tip: click a column header to sort, drag a divider to widen a column, drag the corner to resize.")
        self.explainer.setWordWrap(True)
        self.explainer.setObjectName("muted")
        self.root.addWidget(self.explainer)

        buttons = QHBoxLayout()
        self.b_ip = GlowButton("BLOCK IP", "shield", "red", "outline")
        self.b_net = GlowButton("BLOCK NETWORK", "globe", "magenta", "outline")
        self.b_forget = GlowButton("UNBLOCK", "refresh", "green", "outline")
        self.b_clear = GlowButton("CLEAR LEARNED", "trash", "yellow", "outline")
        self.b_settings = GlowButton("SHIELD SETTINGS", "gear", "cyan", "outline")
        b_close = GlowButton("CLOSE", "", "cyan", "solid", "cyan2")
        self.b_ip.clicked.connect(lambda: self._block(False))
        self.b_net.clicked.connect(lambda: self._block(True))
        self.b_forget.clicked.connect(self._forget)
        self.b_clear.clicked.connect(self.clear_all.emit)
        self.b_settings.clicked.connect(self.open_settings.emit)
        b_close.clicked.connect(self.accept)
        for b in (self.b_ip, self.b_net, self.b_forget, self.b_clear, self.b_settings):
            b.setFixedHeight(44)
            b.icon_size = 17
            buttons.addWidget(b)
        buttons.addStretch(1)
        b_close.setFixedSize(120, 44)
        buttons.addWidget(b_close)
        buttons.addSpacing(14)                     # keep clear of the resize grip
        self.root.addLayout(buttons)
        self._sync_buttons()

    def _sync_buttons(self, *_):
        learned = self.tabs.currentWidget() is self.learned
        self.b_ip.setVisible(not learned)
        self.b_net.setVisible(not learned)
        self.b_forget.setVisible(learned)
        self.b_clear.setVisible(learned)

    def _block(self, network: bool) -> None:
        key = self.tabs.currentWidget().current_key()
        if key:
            self.block.emit(key.split("|")[0], network)

    def _forget(self) -> None:
        keys = self.learned.selected_keys()
        if keys:
            self.forget.emit(keys)

    def update_data(self, data: dict) -> None:
        summary = data.get("shield") or {}
        view = data.get("shield_view") or {}
        peers = view.get("peers", [])
        self.chips["peers"].value.setText(str(len(peers)))
        self.chips["networks"].value.setText(str(len({p["network"] for p in peers if p["network"]})))
        self.chips["countries"].value.setText(str(len({p["cc"] for p in peers if p["cc"]})))
        self.chips["refused"].value.setText(str(summary.get("refused", 0)))
        self.chips["learned"].value.setText(f"{summary.get('learned_ips', 0)} IP · {summary.get('networks', 0)} NET")
        self.chips["learned"].setToolTip(f"Malwarebytes log: {summary.get('av', '?')}\n"
                                         f"Network database: {summary.get('db', '?')}")
        if data.get("flash"):
            mode = "⚡ FLASH"
        elif data.get("file_only"):
            mode = "FILE-ONLY" + (" + DHT" if data.get("dht_on") else "")
        else:
            mode = "OPEN · DHT"
        self.chips["mode"].value.setText(mode)

        live = []
        for p in peers:
            has = 1.01 if p["seed"] else p["progress"]
            cells = [p["torrent"], _peer_text(p["ip"], p["port"]), p["cc"], p["network"] or "—", p["client"],
                     p["source"], p["direction"].upper() + (" · ENC" if p["encrypted"] else ""),
                     T.fmt_speed(p["down"]), T.fmt_speed(p["up"]), "seed" if p["seed"] else f"{p['progress'] * 100:.0f}%"]
            sort = [p["torrent"].casefold(), _ip_sort(p["ip"]), p["cc"], (p["network"] or "~").casefold(),
                    p["client"].casefold(), p["source"], cells[6], int(p["down"]), int(p["up"]), float(has)]
            live.append({"key": f"{p['ip']}|{p['port']}|{p['torrent']}", "cells": cells, "sort": sort})
        self.live.update_rows(live)

        refused = []
        for r in view.get("refused", []):
            cells = [r["time"], _peer_text(r["ip"], r["port"]), r["torrent"], r["cc"], r["network"] or "—", r["reason"]]
            sort = [r["time"], _ip_sort(r["ip"]), r["torrent"].casefold(), r["cc"], (r["network"] or "~").casefold(),
                    r["reason"]]
            refused.append({"key": f"{r['ip']}|{r['port']}|{r['time']}|{r['torrent']}", "cells": cells, "sort": sort})
        self.refused.update_rows(refused)

        learned = []
        for r in view.get("lessons", []):
            seen = r["seen"] if isinstance(r["seen"], int) else -1
            cells = [r["type"], r["value"], r["network"] or "—", r["cc"], str(r["seen"]), r["when"].replace("T", " "),
                     r["origin"]]
            sort = [r["type"], r["value"].casefold(), (r["network"] or "~").casefold(), r["cc"], seen, r["when"],
                    r["origin"]]
            learned.append({"key": r["key"], "cells": cells, "sort": sort})
        self.learned.update_rows(learned)
        self.tabs.setTabText(0, f"LIVE PEERS ({len(peers)})")
        self.tabs.setTabText(1, f"REFUSED ({summary.get('refused', 0)})")
        self.tabs.setTabText(2, f"LEARNED BLOCKS ({len(learned)})")


# ---------------------------------------------------------------------------------------------- live editing helpers

def _limit_spin(maximum: int, value: int, suffix: str, special: str) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, maximum)
    spin.setValue(int(value))
    spin.setSuffix(suffix)
    spin.setSpecialValueText(special)
    spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    spin.setAccelerated(True)
    spin.setKeyboardTracking(False)          # apply when typing finishes, not on every keystroke
    return spin


def _preset_row(spin: QSpinBox, presets: list[tuple[str, int]], color: str) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for text, value in presets:
        b = GlowButton(text, "", color, "outline")
        b.setFont(T.head_font(8.6, QFont.Weight.DemiBold, 0.8))
        b.setFixedHeight(30)
        b.clicked.connect(lambda _=False, v=value: spin.setValue(v))
        lay.addWidget(b)
    lay.addStretch(1)
    return box


def _panel_form(color: str, title: str) -> tuple[NeonPanel, QFormLayout]:
    panel = NeonPanel(color, 0.5)
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(18, 12, 18, 14)
    outer.setSpacing(10)
    head = QLabel(title.upper())
    head.setFont(T.head_font(10.5, QFont.Weight.DemiBold, 1.8))
    head.setStyleSheet(f"color: {T.hexc(color)};")
    outer.addWidget(head)
    form = QFormLayout()
    form.setHorizontalSpacing(16)
    form.setVerticalSpacing(10)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    outer.addLayout(form)
    outer.addStretch(1)                       # keep the content at the top when the row is taller
    return panel, form


def _form_label(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("formLabel")
    return lab


class TorrentOptionsDialog(NeonDialog):
    """Per-torrent settings that apply immediately (no Save button)."""
    option = Signal(str, str, object)          # key, option name, value
    action = Signal(str, str)                  # key, action name

    def __init__(self, row: dict, parent=None):
        super().__init__("Torrent settings", parent, resizable=True)
        self.key = row["key"]
        self.row = row
        self._edited: dict[str, float] = {}
        self._pending: dict[str, object] = {}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._flush)

        # everything above the CLOSE row scrolls, so the dialog fits 768-pixel-high screens
        body = QWidget()
        body.setObjectName("optionsBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(self.root.spacing())
        self.header = BadgeHeader()
        self.header.setCursor(Qt.CursorShape.ArrowCursor)
        content.addWidget(self.header)
        self.info = QLabel("—")
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        self.info.setObjectName("muted")
        content.addWidget(self.info)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        speed, sf = _panel_form("cyan", "Speed")
        self.down = _limit_spin(1_000_000, 0, " KiB/s", "Unlimited")
        self.up = _limit_spin(1_000_000, 0, " KiB/s", "Unlimited")
        self.conns = _limit_spin(5000, 0, "", "Unlimited")
        self.slots = _limit_spin(500, 0, "", "Unlimited")
        sf.addRow(_form_label("Download"), self.down)
        sf.addRow("", _preset_row(self.down, [("∞", 0), ("1 MB/s", 1024), ("5 MB/s", 5120), ("20 MB/s", 20480)], "cyan"))
        sf.addRow(_form_label("Upload"), self.up)
        sf.addRow("", _preset_row(self.up, [("∞", 0), ("24 KiB/s", 24), ("256 KiB/s", 256), ("1 MB/s", 1024)], "magenta"))
        sf.addRow(_form_label("Connections"), self.conns)
        sf.addRow(_form_label("Upload slots"), self.slots)
        note = QLabel("Per-torrent caps work under the global caps (Speed limits).")
        note.setObjectName("muted")
        note.setWordWrap(True)
        sf.addRow("", note)
        grid.addWidget(speed, 0, 0)
        self.bg.register(speed)

        behaviour, bf = _panel_form("purple", "Behaviour")
        self.seq = QCheckBox("Sequential download (in order, for previews)")
        self.firstlast = QCheckBox("Download first and last pieces first")
        self.super = QCheckBox("Super seeding (seeding a rare torrent)")
        self.force = QCheckBox("Force start (ignore the queue limit)")
        self.ratio = QDoubleSpinBox()
        self.ratio.setRange(0, 100)
        self.ratio.setDecimals(2)
        self.ratio.setSingleStep(0.1)
        self.ratio.setSpecialValueText("Never stop")
        self.ratio.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.ratio.setKeyboardTracking(False)
        for box in (self.seq, self.firstlast, self.super, self.force):
            bf.addRow(box)                         # span the whole row so the text is never clipped
        bf.addRow(_form_label("Stop seeding at ratio"), self.ratio)
        grid.addWidget(behaviour, 0, 1)
        self.bg.register(behaviour)
        content.addLayout(grid)

        actions = NeonPanel("green", 0.45)
        self.bg.register(actions)
        al = QGridLayout(actions)
        al.setContentsMargins(16, 14, 16, 14)
        al.setHorizontalSpacing(10)
        al.setVerticalSpacing(10)
        self.b_pause = GlowButton("PAUSE", "pause", "cyan", "outline")
        buttons = [
            (self.b_pause, "toggle_pause"),
            (GlowButton("STOP", "stop", "orange", "outline"), "stop"),
            (GlowButton("FORCE RECHECK", "refresh", "orange", "outline"), "recheck"),
            (GlowButton("SKIP HASH CHECK", "skip", "yellow", "outline"), "skip_check"),
            (GlowButton("REANNOUNCE", "search", "blue", "outline"), "reannounce"),
            (GlowButton("QUEUE UP", "up", "purple", "outline"), "queue_up"),
            (GlowButton("QUEUE DOWN", "down", "purple", "outline"), "queue_down"),
            (GlowButton("TOP", "top", "purple", "outline"), "queue_top"),
            (GlowButton("BOTTOM", "bottom", "purple", "outline"), "queue_bottom"),
            (GlowButton("OPEN FOLDER", "folder", "cyan", "outline"), "open_folder"),
            (GlowButton("MOVE DATA", "move", "blue", "outline"), "move"),
            (GlowButton("COPY MAGNET", "magnet", "magenta", "outline"), "copy_magnet"),
            (GlowButton("DETAILS", "info", "green", "outline"), "details"),
            (GlowButton("SCAN NOW", "shield", "green", "outline"), "scan_now"),
        ]
        tips = {"skip_check": "Treat the data on disk as complete without hashing it first.\n"
                              "libtorrent still verifies each piece the first time it is uploaded.",
                "recheck": "Hash every piece on disk again (fixes corrupted data)."}
        for i, (button, name) in enumerate(buttons):
            button.setFixedHeight(40)
            button.icon_size = 16
            button.setFont(T.head_font(9.2, QFont.Weight.DemiBold, 1.0))
            button.setToolTip(tips.get(name, ""))
            if name.startswith("queue"):
                button.clicked.connect(lambda _=False, n=name: self.option.emit(self.key, "queue", n.split("_")[1]))
            else:
                button.clicked.connect(lambda _=False, n=name: self.action.emit(self.key, n))
            al.addWidget(button, i // 4, i % 4)
        content.addWidget(actions)

        trackers = NeonPanel("blue", 0.4)
        self.bg.register(trackers)
        tl = QHBoxLayout(trackers)
        tl.setContentsMargins(16, 12, 16, 12)
        tl.setSpacing(12)
        self.tracker_box = QPlainTextEdit()
        self.tracker_box.setObjectName("blocklist")
        self.tracker_box.setPlaceholderText("Add trackers: one announce URL per line (blocked ones are skipped)")
        self.tracker_box.setFixedHeight(64)
        add = GlowButton("ADD TRACKERS", "link", "blue", "outline")
        add.setFixedHeight(40)
        add.clicked.connect(self._add_trackers)
        tl.addWidget(self.tracker_box, 1)
        tl.addWidget(add)
        content.addWidget(trackers)
        scroll = QScrollArea()
        scroll.setObjectName("optionsScroll")
        scroll.setStyleSheet("#optionsScroll, #optionsScroll > QWidget, #optionsBody "
                             "{ background: transparent; border: none; }")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.verticalScrollBar().valueChanged.connect(self.bg.update)  # panel glows follow the scroll
        screen = self.screen() or QApplication.primaryScreen()
        room = screen.availableGeometry().height() - 260 if screen else 600
        scroll.setMinimumHeight(max(320, min(body.sizeHint().height(), room)))
        self.root.addWidget(scroll, 1)

        bottom = QHBoxLayout()
        live = QLabel("Changes apply instantly.")
        live.setObjectName("muted")
        bottom.addWidget(live)
        bottom.addStretch(1)
        close = GlowButton("CLOSE", "", "cyan", "solid", "cyan2")
        close.setFixedSize(120, 44)
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        bottom.addSpacing(14)
        self.root.addLayout(bottom)
        # the layout sets the minimum: a fixed smaller one made the speed rows overlap
        hint = self.minimumSizeHint()
        self.resize(max(900, hint.width()), hint.height())

        for name, spin in (("download_limit", self.down), ("upload_limit", self.up),
                           ("max_connections", self.conns), ("max_uploads", self.slots), ("ratio_limit", self.ratio)):
            spin.valueChanged.connect(lambda value, n=name: self._queue(n, value))
        for name, box in (("sequential", self.seq), ("first_last", self.firstlast), ("super_seeding", self.super),
                          ("force_start", self.force)):
            box.toggled.connect(lambda on, n=name: self._send(n, on))
        self.update_row(row)

    # -- outgoing
    def _queue(self, name: str, value) -> None:
        self._edited[name] = time.monotonic()
        self._pending[name] = value
        self._debounce.start()

    def _flush(self) -> None:
        pending, self._pending = self._pending, {}
        for name, value in pending.items():
            self.option.emit(self.key, name, value)

    def _send(self, name: str, value) -> None:
        self._edited[name] = time.monotonic()
        self.option.emit(self.key, name, value)

    def _add_trackers(self) -> None:
        urls = [line.strip() for line in self.tracker_box.toPlainText().splitlines() if line.strip()]
        if urls:
            self.option.emit(self.key, "add_trackers", urls)
            self.tracker_box.clear()

    # -- incoming (live snapshot)
    def update_row(self, row: dict) -> None:
        self.row = row
        self.header.set_info(row["kind"], row["title"], row["sub"])
        paused = row["state"] in ("Paused", "Stopped", "Queued", "Error")
        self.b_pause.setText("RESUME" if paused else "PAUSE")
        self.b_pause.icon_name = "play" if paused else "pause"
        self.b_pause.color_key = "green" if paused else "cyan"
        self.b_pause.update()

    def _settle(self, name: str) -> bool:
        """True if a widget may be refreshed from the engine (user is not editing it right now)."""
        return time.monotonic() - self._edited.get(name, 0) > 2.0 and name not in self._pending

    def update_options(self, o: dict | None) -> None:
        if not o or o.get("key") != self.key:
            return
        for name, widget in (("download_limit", self.down), ("upload_limit", self.up),
                             ("max_connections", self.conns), ("max_uploads", self.slots), ("ratio_limit", self.ratio)):
            if self._settle(name) and not widget.hasFocus() and widget.value() != o[name]:
                widget.blockSignals(True)
                widget.setValue(o[name])
                widget.blockSignals(False)
        for name, box in (("sequential", self.seq), ("first_last", self.firstlast), ("super_seeding", self.super),
                          ("force_start", self.force)):
            if self._settle(name) and box.isChecked() != o[name]:
                box.blockSignals(True)
                box.setChecked(o[name])
                box.blockSignals(False)
        pieces = f"{o['num_pieces']:,}/{o['pieces_total']:,} pieces" if o["has_metadata"] else "waiting for metadata"
        seeding = T.fmt_eta(o["seeding_time"]) if o["seeding_time"] else "—"
        self.info.setText(f"{self.row['state'].upper()}  ·  queue #{o['queue_position'] + 1 if o['queue_position'] >= 0 else '—'}"
                          f"  ·  {o['connections']} connected  ·  {pieces}  ·  {o['trackers']} trackers"
                          f"  ·  active {T.fmt_eta(o['active_time'])}  ·  seeding {seeding}")


class SpeedLimitsDialog(NeonDialog):
    """Global download/upload caps, applied live."""
    changed = Signal(int, int)                 # download KiB/s, upload KiB/s (0 = unlimited)

    def __init__(self, down_kib: int, up_kib: int, parent=None):
        super().__init__("Speed limits", parent)
        self.setMinimumWidth(620)
        panel, form = _panel_form("cyan", "Global caps · all torrents")
        self.bg.register(panel)
        self.down = _limit_spin(1_000_000, down_kib, " KiB/s", "Unlimited")
        self.up = _limit_spin(1_000_000, up_kib, " KiB/s", "Unlimited")
        form.addRow(_form_label("Download"), self.down)
        form.addRow("", _preset_row(self.down, [("∞", 0), ("1 MB/s", 1024), ("5 MB/s", 5120), ("10 MB/s", 10240),
                                                ("50 MB/s", 51200)], "cyan"))
        form.addRow(_form_label("Upload"), self.up)
        form.addRow("", _preset_row(self.up, [("∞", 0), ("24 KiB/s", 24), ("256 KiB/s", 256), ("1 MB/s", 1024),
                                              ("5 MB/s", 5120)], "magenta"))
        tip = QLabel("Peers send fastest to clients that upload back (tit-for-tat). If downloads are slow, a higher "
                     "upload cap is usually the quickest fix. Per-torrent caps: click a torrent's name.")
        tip.setWordWrap(True)
        tip.setObjectName("muted")
        form.addRow("", tip)
        self.root.addWidget(panel)
        bottom = QHBoxLayout()
        live = QLabel("Changes apply instantly.")
        live.setObjectName("muted")
        bottom.addWidget(live)
        bottom.addStretch(1)
        close = GlowButton("CLOSE", "", "cyan", "solid", "cyan2")
        close.setFixedSize(120, 44)
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        self.root.addLayout(bottom)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(lambda: self.changed.emit(self.down.value(), self.up.value()))
        self.down.valueChanged.connect(self._debounce.start)
        self.up.valueChanged.connect(self._debounce.start)


