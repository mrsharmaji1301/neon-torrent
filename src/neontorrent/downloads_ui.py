"""DOWNLOADS (the IDM part) and SEARCH pages, and the dialogs the smart ADD box opens.

Zero pop-ups: nothing here renders a web page. Pages and feeds are read as text in background threads; only file,
magnet and .torrent links come out of them. A browser opens only when the user presses a button that says so.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QSpinBox, QTableWidget, QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget)

from . import downloader as D
from . import search as SR
from . import theme as T
from . import web
from .dialogs import NeonDialog
from .widgets import GlowButton, NeonPanel, SectionTitle

KIND_LABEL = {"magnet": "Magnet", "torrent": "Torrent", "archive": "Archive", "disc": "Disc image", "video": "Video",
              "audio": "Audio", "image": "Image", "document": "Document", "program": "Program ⚠", "other": "Other"}


def human(n: float) -> str:
    if n is None or n < 0:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "—"


def open_in_browser(url: str) -> None:
    """The user's own browser, on an explicit click only. Explorer by its absolute path; http(s) only."""
    web.check_url(url)
    explorer = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe")
    subprocess.Popen([explorer, url])


def show_in_explorer(path: str) -> None:
    explorer = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe")
    subprocess.Popen([explorer, "/select,", path] if Path(path).is_file() else [explorer, path])


def _table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setObjectName("detailTable")
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.setWordWrap(False)
    for column in range(1, len(columns)):              # the name takes the room; the rest fit their text
        table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
    return table


def _cell(text: str, data=None, align_right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)                      # plain text only: names come from websites
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


# ------------------------------------------------------------------ add a file download
class AddDownloadDialog(NeonDialog):
    """A direct file link: name, size, folder and connections before it starts."""

    def __init__(self, probe: web.Probe, folder: str, parent=None):
        super().__init__("Download file", parent)
        self.setMinimumWidth(560)
        self.probe = probe
        info = QLabel(f"{probe.name}\n{human(probe.size)} · {probe.mime or 'unknown type'} · "
                      + ("resumable, split into parts" if probe.ranges and probe.size > 0
                         else "one connection, not resumable"))
        info.setTextFormat(Qt.TextFormat.PlainText)
        info.setWordWrap(True)
        info.setFont(T.font(10.5))
        self.root.addWidget(info)
        if web.link_kind(probe.name) == "program":
            warn = QLabel("This is a program. Run it only if you trust the website; NEON marks it as downloaded from "
                          "the internet, so Windows asks before running it.")
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {T.hexc('yellow')};")
            self.root.addWidget(warn)
        self.name = QLineEdit(probe.name)
        self.root.addWidget(self.name)
        row = QHBoxLayout()
        self.folder = QLineEdit(folder)
        browse = GlowButton("BROWSE", "folder", "cyan", "outline")
        browse.setFixedSize(120, 38)
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        self.root.addLayout(row)
        conn = QHBoxLayout()
        conn.addWidget(QLabel("Connections"))
        self.connections = QSpinBox()
        self.connections.setRange(1, D.MAX_CONNECTIONS)
        self.connections.setValue(D.DEFAULT_CONNECTIONS if probe.ranges else 1)
        self.connections.setEnabled(probe.ranges)
        conn.addWidget(self.connections)
        conn.addStretch(1)
        self.later = QCheckBox("Add paused (start later)")
        conn.addWidget(self.later)
        self.root.addLayout(conn)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = GlowButton("CANCEL", "close", "magenta", "outline")
        cancel.clicked.connect(self.reject)
        ok = GlowButton("DOWNLOAD", "download", "cyan", "solid", "cyan2")
        ok.clicked.connect(self.accept)
        for b in (cancel, ok):
            b.setFixedSize(150, 44)
            buttons.addWidget(b)
        self.root.addLayout(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save to", self.folder.text())
        if folder:
            self.folder.setText(folder)


# ------------------------------------------------------------------ links found on a page
class LinkPickerDialog(NeonDialog):
    """A pasted web page: every file, magnet and .torrent link on it, ticked by the user. Programs start unticked."""

    def __init__(self, links: list[web.Link], page_url: str, parent=None):
        super().__init__("Links on this page", parent, resizable=True)
        self.resize(820, 560)
        note = QLabel(f"{page_url}\nNEON read this page as text: nothing on it ran. Tick what to download.")
        note.setObjectName("muted")
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.table = _table(["Name", "Type", "Link"])
        self.table.setRowCount(len(links))
        for r, link in enumerate(links):
            name = _cell(link.name, link)
            name.setFlags(name.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            name.setCheckState(Qt.CheckState.Unchecked if link.kind == "program" else Qt.CheckState.Checked)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, _cell(KIND_LABEL.get(link.kind, link.kind)))
            self.table.setItem(r, 2, _cell(link.url[:200]))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.root.addWidget(self.table, 1)
        row = QHBoxLayout()
        for label, state in (("ALL", Qt.CheckState.Checked), ("NONE", Qt.CheckState.Unchecked)):
            b = GlowButton(label, "check" if state == Qt.CheckState.Checked else "close", "cyan", "outline")
            b.setFixedSize(100, 38)
            b.clicked.connect(lambda _=False, s=state: self._set_all(s))
            row.addWidget(b)
        row.addStretch(1)
        cancel = GlowButton("CANCEL", "close", "magenta", "outline")
        cancel.clicked.connect(self.reject)
        ok = GlowButton("DOWNLOAD TICKED", "download", "cyan", "solid", "cyan2")
        ok.clicked.connect(self.accept)
        for b, w in ((cancel, 130), (ok, 200)):
            b.setFixedSize(w, 44)
            row.addWidget(b)
        self.root.addLayout(row)

    def _set_all(self, state) -> None:
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(state)

    def chosen(self) -> list[web.Link]:
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.CheckState.Checked]


# ------------------------------------------------------------------ DOWNLOADS page
class DownloadsTab(QWidget):
    def __init__(self, manager: D.DownloadManager, register: Callable, parent=None):
        super().__init__(parent)
        self.manager = manager
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        panel = NeonPanel("cyan", 0.55)
        register(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(SectionTitle("download", "DOWNLOADS", "Files from the web, many connections, pause and resume"),
                       1)
        self.buttons = {}
        for key, text, icon, color in (("resume", "RESUME", "play", "green"), ("pause", "PAUSE", "pause", "cyan"),
                                       ("remove", "REMOVE", "trash", "purple"), ("open", "SHOW FILE", "folder",
                                                                                 "magenta")):
            b = GlowButton(text, icon, color, "outline")
            b.setFixedSize(130, 40)
            b.clicked.connect(lambda _=False, k=key: self._act(k))
            head.addWidget(b)
            self.buttons[key] = b
        lay.addLayout(head)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Speed limit"))
        self.limit = QSpinBox()
        self.limit.setRange(0, 1_000_000)
        self.limit.setSuffix(" KB/s")
        self.limit.setSpecialValueText("Unlimited")
        self.limit.valueChanged.connect(lambda v: self.manager.set_limit(v * 1024))
        controls.addWidget(self.limit)
        controls.addSpacing(16)
        controls.addWidget(QLabel("At once"))
        self.active = QSpinBox()
        self.active.setRange(1, 10)
        self.active.setValue(self.manager.max_active)
        self.active.valueChanged.connect(lambda v: setattr(self.manager, "max_active", v))
        controls.addWidget(self.active)
        controls.addSpacing(16)
        self.scheduled = QCheckBox("Start the queue at")
        self.at = QTimeEdit()
        self.at.setDisplayFormat("HH:mm")
        self.scheduled.toggled.connect(self._schedule)
        self.at.timeChanged.connect(lambda _t: self._schedule(self.scheduled.isChecked()))
        controls.addWidget(self.scheduled)
        controls.addWidget(self.at)
        controls.addStretch(1)
        lay.addLayout(controls)
        self.table = _table(["Name", "Size", "Progress", "Speed", "Status"])
        self.table.itemDoubleClicked.connect(lambda _i: self._act("open"))
        lay.addWidget(self.table, 1)
        self.empty = QLabel("Paste any link in ADD on the TORRENTS page: files download here, torrents go to the "
                            "torrent list, and web pages show the files on them.")
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)
        root.addWidget(panel)
        self.timer = QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def _schedule(self, on: bool) -> None:
        if not on:
            self.manager.start_at = 0.0
            return
        now = time.localtime()
        t = self.at.time()
        start = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, t.hour(), t.minute(), 0, 0, 0, -1))
        if start <= time.time():
            start += 24 * 3600
        self.manager.start_at = start

    def _selected(self) -> list[dict]:
        rows = {i.row() for i in self.table.selectedItems()}
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in sorted(rows)]

    def _act(self, key: str) -> None:
        rows = self._selected()
        ids = [r["id"] for r in rows]
        if key == "pause":
            self.manager.pause(ids)
        elif key == "resume":
            self.manager.resume(ids)
        elif key == "remove":
            self.manager.remove(ids)
        elif key == "open" and rows:
            show_in_explorer(rows[0]["path"] or rows[0]["folder"])
        self.refresh()

    def refresh(self) -> None:
        rows = self.manager.snapshot()
        self.empty.setVisible(not rows)
        self.table.setVisible(bool(rows))
        selected = {r["id"] for r in self._selected()}
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            size, done = row["size"], row["done"]
            progress = f"{done / size * 100:.1f}%" if size > 0 else human(done)
            state = {"queued": "Queued", "running": f"Downloading · {row['connections']} conn.", "paused": "Paused",
                     "done": "Done" + (" · program ⚠" if row["warning"] else ""), "failed": f"Failed · {row['error']}",
                     "cancelled": "Cancelled"}.get(row["state"], row["state"])
            cells = [_cell(row["name"], row), _cell(human(size), align_right=True), _cell(progress, align_right=True),
                     _cell(f"{human(row['speed'])}/s" if row["state"] == "running" else "", align_right=True),
                     _cell(state)]
            for c, cell in enumerate(cells):
                self.table.setItem(i, c, cell)
            if row["id"] in selected:
                self.table.selectRow(i)


# ------------------------------------------------------------------ SEARCH page
class _SearchSignals(QObject):
    results = Signal(list)
    error = Signal(str, str)
    done = Signal()


class SourcesDialog(NeonDialog):
    """Search sources: Internet Archive is built in; the user adds any other (Torznab, RSS, page or browser)."""

    def __init__(self, prefs: dict, save: Callable[[dict], None], parent=None):
        super().__init__("Search sources", parent, resizable=True)
        self.resize(820, 560)
        self.prefs, self.save = prefs, save
        note = QLabel("Results from every enabled source are listed together. Sources you add are marked "
                      "“Not verified by NEON”. Quickword: type it before the words to search only that source "
                      "(e.g. “ia ubuntu”).")
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.table = _table(["Name", "Kind", "Quickword", "On"])
        self.root.addWidget(self.table, 1)
        form = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name")
        self.kind = QComboBox()
        for kind, label in (("torznab", "Torznab (Jackett / Prowlarr)"), ("rss", "RSS feed"),
                            ("page", "Search page"), ("browser", "Open in my browser")):
            self.kind.addItem(label, kind)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…/search?q={query}   (Torznab: the API URL)")
        self.key = QLineEdit()
        self.key.setPlaceholderText("API key (Torznab)")
        self.quick = QLineEdit()
        self.quick.setPlaceholderText("Quickword")
        self.quick.setMaximumWidth(110)
        for w, s in ((self.name, 2), (self.kind, 2), (self.url, 5), (self.key, 2), (self.quick, 1)):
            form.addWidget(w, s)
        self.root.addLayout(form)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.root.addWidget(self.status)
        row = QHBoxLayout()
        add = GlowButton("ADD SOURCE", "file_plus", "cyan", "solid", "cyan2")
        add.clicked.connect(self._add)
        toggle = GlowButton("ON / OFF", "power", "green", "outline")
        toggle.clicked.connect(self._toggle)
        remove = GlowButton("REMOVE", "trash", "red", "outline")
        remove.clicked.connect(self._remove)
        close = GlowButton("CLOSE", "check", "cyan", "outline")
        close.clicked.connect(self.accept)
        for b, w in ((add, 160), (toggle, 130), (remove, 120)):
            b.setFixedSize(w, 40)
            row.addWidget(b)
        row.addStretch(1)
        close.setFixedSize(120, 40)
        row.addWidget(close)
        self.root.addLayout(row)
        self._fill()

    def _sources(self) -> list[dict]:
        return [s.__dict__ for s in SR.sources_from_prefs(self.prefs)]

    def _fill(self) -> None:
        sources = SR.sources_from_prefs(self.prefs)
        self.table.setRowCount(len(sources))
        for r, s in enumerate(sources):
            label = s.name + ("  · built in, trusted" if s.builtin else "  · not verified by NEON")
            for c, text in enumerate((label, s.kind, s.quickword, "on" if s.enabled else "off")):
                self.table.setItem(r, c, _cell(text, s.id))

    def _store(self, sources: list[dict]) -> None:
        self.prefs["search_sources"] = [{k: v for k, v in s.items() if k != "extra"} for s in sources]
        self.save(self.prefs)
        self._fill()

    def _add(self) -> None:
        try:
            data = SR.new_source(self.name.text(), self.kind.currentData(), self.url.text(), self.key.text(),
                                 self.quick.text())
        except (ValueError, web.WebError) as exc:
            self.status.setText(str(exc))
            return
        sources = self._sources()
        if data["quickword"] and any(s["quickword"] == data["quickword"] for s in sources):
            self.status.setText("That quickword is taken")
            return
        self._store(sources + [data])
        for w in (self.name, self.url, self.key, self.quick):
            w.clear()
        self.status.setText("Added.")

    def _selected_id(self) -> str:
        row = self.table.currentRow()
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else ""

    def _toggle(self) -> None:
        sid = self._selected_id()
        self._store([{**s, "enabled": not s["enabled"]} if s["id"] == sid else s for s in self._sources()])

    def _remove(self) -> None:
        sid = self._selected_id()
        self._store([s for s in self._sources() if s["id"] != sid or s.get("builtin")])


class SearchTab(QWidget):
    def __init__(self, prefs: Callable[[], dict], save_prefs: Callable[[dict], None], add_link: Callable[[str], None],
                 register: Callable, parent=None):
        super().__init__(parent)
        self.prefs, self.save_prefs, self.add_link = prefs, save_prefs, add_link
        self.sig = _SearchSignals()
        self.sig.results.connect(self._add_results)
        self.sig.error.connect(self._source_error)
        self.sig.done.connect(self._done)
        self.cancel: threading.Event | None = None
        self.results: list[SR.Result] = []
        self.errors: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        panel = NeonPanel("magenta", 0.55)
        register(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(SectionTitle("search", "SEARCH", "Torrents from all your sources · only magnets and .torrent "
                                                       "files, zero pop-ups"), 1)
        sources = GlowButton("SOURCES", "sliders", "magenta", "outline")
        sources.setFixedSize(140, 40)
        sources.clicked.connect(self._sources)
        head.addWidget(sources)
        lay.addLayout(head)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search… (a quickword first searches one source, e.g. “ia ubuntu”)")
        self.query.returnPressed.connect(self.run)
        row.addWidget(self.query, 1)
        go = GlowButton("SEARCH", "search", "cyan", "solid", "cyan2")
        go.setFixedSize(140, 42)
        go.clicked.connect(self.run)
        row.addWidget(go)
        self.browser_btn = GlowButton("IN MY BROWSER", "globe", "magenta", "outline")
        self.browser_btn.setFixedSize(170, 42)
        self.browser_btn.setToolTip("Opens this search in your own browser (outside NEON) on every source of the kind "
                                    "“Open in my browser”. Magnet links you click there come to NEON.")
        self.browser_btn.clicked.connect(self._browser)
        row.addWidget(self.browser_btn)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.table = _table(["Name", "Size", "Seeds", "Date", "Source"])
        self.table.setSortingEnabled(True)
        self.table.itemDoubleClicked.connect(lambda _i: self._download())
        lay.addWidget(self.table, 1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        get = GlowButton("DOWNLOAD", "download", "cyan", "solid", "cyan2")
        get.setFixedSize(170, 44)
        get.clicked.connect(self._download)
        bottom.addWidget(get)
        lay.addLayout(bottom)
        root.addWidget(panel)

    def _sources(self) -> None:
        SourcesDialog(self.prefs(), self.save_prefs, self.window()).exec()

    def _browser(self) -> None:
        sources, words = SR.split_quickword(self.query.text(), SR.sources_from_prefs(self.prefs()))
        targets = [s for s in sources if s.kind == "browser"]
        if not words or not targets:
            self.status.setText("Add a source of the kind “Open in my browser” under SOURCES first.")
            return
        for s in targets:
            open_in_browser(SR.browser_url(s, words))

    def run(self) -> None:
        sources, words = SR.split_quickword(self.query.text(), SR.sources_from_prefs(self.prefs()))
        if not words:
            return
        if self.cancel is not None:
            self.cancel.set()
        self.results, self.errors = [], []
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        live = [s for s in sources if s.kind != "browser"]
        self.status.setText(f"Searching {len(live)} source{'s' if len(live) != 1 else ''}…")
        self.cancel = SR.search_all(sources, words, self.sig.results.emit, self.sig.error.emit, self.sig.done.emit)

    def _add_results(self, results: list) -> None:
        self.table.setSortingEnabled(False)
        for res in results:
            self.results.append(res)
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = res.name + ("   ⚠ program inside" if res.warning else "")
            source = res.source + ("" if res.trusted else " · not verified by NEON")
            size = _cell(human(res.size), align_right=True)
            size.setData(Qt.ItemDataRole.UserRole + 1, res.size)
            seeds = _cell("—" if res.seeders < 0 else str(res.seeders), align_right=True)
            for c, cell in enumerate((_cell(name, res), size, seeds, _cell(res.date), _cell(source))):
                self.table.setItem(r, c, cell)
        self.table.setSortingEnabled(True)
        self.status.setText(f"{len(self.results)} results…")

    def _source_error(self, source: str, message: str) -> None:
        self.errors.append(f"{source}: {message}")

    def _done(self) -> None:
        text = f"{len(self.results)} results."
        if self.errors:
            text += "  Not answering: " + "; ".join(self.errors)[:300]
        self.status.setText(text)

    def _download(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        for r in rows:
            res = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            if res is not None:
                self.add_link(res.link)              # through the torrent engine: Add dialog and Download Guard


# ------------------------------------------------------------------ resolving a pasted link
class Resolver(QObject):
    """Runs ``web.probe`` / ``web.page_links`` off the UI thread for the smart ADD box."""
    resolved = Signal(str, object)         # kind ("torrent" | "file" | "page" | "error"), payload

    def resolve(self, url: str) -> None:
        def run():
            try:
                info = web.probe(url)
                if info.kind == "page":
                    text, final = web.get_text(info.url)
                    self.resolved.emit("page", (final, web.page_links(text, final)))
                else:
                    self.resolved.emit(info.kind, info)
            except web.WebError as exc:
                self.resolved.emit("error", str(exc))
        threading.Thread(target=run, daemon=True, name="neon-resolve").start()


