from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QStandardPaths, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from neontorrent import APP_NAME  # noqa: E402
from neontorrent import theme as T  # noqa: E402

if sys.stderr is None:  # pythonw.exe: no console, so keep errors in a log file
    sys.stderr = open(T.app_data_dir() / "error.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr
from neontorrent.dialogs import (DetailsDialog, FirstRunDialog, NeonDialog, SettingsDialog,  # noqa: E402
                                 ShieldDialog, SpeedLimitsDialog, TorrentOptionsDialog)
from neontorrent.engine import DEFAULT_BLOCKED, TorrentEngine  # noqa: E402
from neontorrent.icons import logo_icon, make_icon  # noqa: E402
from neontorrent.transfers import (HIDDEN_ON_PAGE, PAGES, STATUS_FILTERS, TransfersView,  # noqa: E402
                                   page_counts, page_matches, status_counts)
from neontorrent.widgets import (BrandTitle, FilterBar, GlowButton, Logo, NeonBackground, NeonLineEdit,  # noqa: E402
                                 NeonPanel, PageTab, SectionTitle, StatCard, StatusDot, StatusLine, VSeparator,
                                 WindowButton)

SERVER_NAME = "NeonTorrent-single-instance"
RESIZE_MARGIN = 8


def build_qss() -> str:
    c = T.THEMES[T.theme_name()]
    return f"""
    QWidget {{ color: {c['text']}; }}
    QToolTip {{ color: {c['text']}; background: {c['panel_hi']}; border: 1px solid {c['cyan']};
        border-radius: 6px; padding: 6px 8px; }}
    QLabel#statTitle {{ color: {c['muted']}; }}
    QLabel#statValue {{ color: {c['text']}; }}
    QLabel#formLabel {{ color: {c['muted']}; font-size: 8.5pt; font-weight: 600; }}
    QLabel#muted {{ color: {c['muted']}; font-size: 9pt; }}
    QLabel#dialogTitle {{ color: {c['cyan']}; }}
    QLabel#connection {{ color: {c['green']}; }}
    QLineEdit#neonInput, QLineEdit, QComboBox, QAbstractSpinBox {{
        background: {c['input']}; border: 1px solid {c['line']}; border-radius: 9px;
        padding: 0 12px; min-height: 40px; selection-background-color: {c['cyan2']}; color: {c['text']};
        font-size: 10.5pt; }}
    QLineEdit#neonInput {{ min-height: 50px; border-color: {c['line']}; }}
    QPlainTextEdit#blocklist {{ background: {c['input']}; border: 1px solid {c['line']}; border-radius: 9px;
        padding: 6px 8px; color: {c['text']}; font-family: Consolas; font-size: 9.5pt; }}
    QPlainTextEdit#blocklist:focus {{ border-color: {c['cyan']}; }}
    QTextBrowser#notices {{ background: {c['input']}; border: 1px solid {c['line']}; border-radius: 9px;
        padding: 8px 10px; color: {c['text']}; font-size: 9pt; selection-background-color: {c['cyan2']}; }}
    QAbstractSpinBox QLineEdit, QComboBox QLineEdit {{ min-height: 0; padding: 0; border: none; background: transparent; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 0px; border: none; }}
    QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {{ border-color: {c['cyan2']}; }}
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus {{ border-color: {c['cyan']}; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QComboBox QAbstractItemView {{ background: {c['panel_hi']}; border: 1px solid {c['cyan']};
        selection-background-color: {c['line']}; outline: none; padding: 4px; }}
    QCheckBox {{ spacing: 10px; color: {c['text']}; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {c['line']};
        background: {c['input']}; }}
    QCheckBox::indicator:hover {{ border-color: {c['cyan']}; }}
    QCheckBox::indicator:checked {{ background: {c['cyan']}; border-color: {c['cyan']}; }}
    QTableView#transfers {{ background: transparent; border: none; outline: none;
        selection-background-color: transparent; }}
    QTableView#transfers QHeaderView {{ background: transparent; border: none; }}
    QTableView#transfers QHeaderView::section {{ background: transparent; color: {c['muted']};
        border: none; border-top: 1px solid {c['line']}; border-bottom: 1px solid {c['line']};
        padding-left: 4px; }}
    QTableView#transfers QHeaderView::section:first {{ padding-left: 24px; }}
    QTableView#transfers QHeaderView::section:hover {{ color: {c['cyan']}; }}
    QTableView#detailTable {{ background: {c['input']}; border: 1px solid {c['line']}; border-radius: 8px;
        gridline-color: {c['line']}; selection-background-color: {c['line']}; outline: none; }}
    QTableView#detailTable QHeaderView::section {{ background: {c['panel_hi']}; color: {c['cyan']};
        border: none; border-bottom: 1px solid {c['line']}; padding: 8px; font-weight: 600; font-size: 8.5pt; }}
    QTableView#detailTable::item {{ padding: 4px 8px; border-bottom: 1px solid {c['line']}; }}
    QTableView#detailTable::item:selected {{ background: {c['line']}; color: {c['cyan']}; }}
    QTableView#detailTable QHeaderView::section {{ border-right: 1px solid {c['line']}; }}
    QTableView#detailTable QHeaderView::section:hover {{ color: {c['text']}; background: {c['line']}; }}
    QTableView#detailTable QTableCornerButton::section {{ background: {c['panel_hi']}; border: none; }}
    QSizeGrip {{ background: transparent; }}
    QTabWidget#neonTabs::pane {{ border: 1px solid {c['line']}; border-radius: 10px; top: -1px;
        background: {c['panel']}; padding: 8px; }}
    QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 10px 18px; margin-right: 4px;
        border: 1px solid transparent; border-top-left-radius: 8px; border-top-right-radius: 8px;
        font-weight: 600; font-size: 9pt; }}
    QTabBar::tab:hover {{ color: {c['cyan']}; }}
    QTabBar::tab:selected {{ color: {c['cyan']}; background: {c['panel']}; border-color: {c['line']};
        border-bottom-color: {c['panel']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['cyan']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
    QScrollBar::handle:horizontal {{ background: {c['line']}; border-radius: 3px; min-width: 30px; }}
    QMenu {{ background: {c['panel_hi']}; border: 1px solid {c['cyan']}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 8px 26px 8px 12px; border-radius: 6px; color: {c['text']}; }}
    QMenu::item:selected {{ background: {c['line']}; color: {c['cyan']}; }}
    QMenu::item:disabled {{ color: {c['muted']}; }}
    QMenu::separator {{ height: 1px; background: {c['line']}; margin: 6px 8px; }}
    QMenu::icon {{ padding-left: 8px; }}
    QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
    """


class DragArea(QWidget):
    """Title-bar strip: drag to move, double-click to maximise."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.window().toggle_maximized()
        super().mouseDoubleClickEvent(event)


class ConfirmDialog(NeonDialog):
    def __init__(self, title: str, text: str, ok_text: str, parent=None):
        super().__init__(title, parent)
        self.setMinimumWidth(470)
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)        # may contain torrent names
        label.setWordWrap(True)
        label.setFont(T.font(10.5))
        self.root.addWidget(label)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = GlowButton("CANCEL", "", "muted", "outline")
        cancel.clicked.connect(self.reject)
        ok = GlowButton(ok_text, "database", "red", "outline")
        ok.clicked.connect(self.accept)
        for b in (cancel, ok):
            b.setMinimumWidth(130)
            row.addWidget(b)
        self.root.addLayout(row)


class TorrentWindow(QMainWindow):
    sig_add_uri = Signal(str)
    sig_add_file = Signal(str)
    sig_pause = Signal(list)
    sig_stop = Signal(list)
    sig_stop_all = Signal()
    sig_resume = Signal(list)
    sig_remove = Signal(list)
    sig_delete = Signal(list)
    sig_recheck = Signal(list)
    sig_reannounce = Signal(list)
    sig_sequential = Signal(list, bool)
    sig_copy_magnet = Signal(str)
    sig_file_priority = Signal(str, int, int)
    sig_move = Signal(str, str)
    sig_detail = Signal(str)
    sig_settings = Signal(dict)
    sig_pause_all = Signal()
    sig_resume_all = Signal()
    sig_shutdown = Signal()
    sig_shield_view = Signal(bool)
    sig_shield_block = Signal(str, bool)
    sig_shield_forget = Signal(list)
    sig_shield_clear = Signal()
    sig_flash = Signal(bool)
    sig_options_key = Signal(str)
    sig_torrent_option = Signal(str, str, object)
    sig_skip_check = Signal(list)
    sig_scan_now = Signal(list)

    def __init__(self):
        super().__init__()
        self.prefs = self._load_prefs()
        T.set_theme(self.prefs["theme"])
        self.quitting = False
        self.shutting_down = False
        self.details: DetailsDialog | None = None
        self.shield_dialog: ShieldDialog | None = None
        self.options_dialog: TorrentOptionsDialog | None = None
        self.last = {}
        self.notice_until = 0
        self.notice_segments: list[tuple[str, str]] = []
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(logo_icon(T.c("cyan"), T.c("magenta")))
        self._build_ui()
        self.page_tabs.select(self.prefs.get("page", "all"))
        self._on_page(self.page_tabs.current)
        self.filter_bar.select(self.prefs.get("status_filter", "all"))
        self._build_shortcuts()
        self._build_tray()
        self._apply_theme()
        self._start_engine()
        self.resize(1240, 770)
        self.setMinimumSize(1000, 640)
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self._refresh_status)

    # ------------------------------------------------------------ prefs
    @staticmethod
    def _load_prefs() -> dict:
        prefs = T.load_preferences()
        prefs["theme"] = prefs.get("theme") if prefs.get("theme") in T.THEMES else "Cyberpunk"
        try:
            prefs["upload_kib"] = max(0, int(prefs.get("upload_kib", T.DEFAULT_UPLOAD_KIB)))
        except (TypeError, ValueError):
            prefs["upload_kib"] = T.DEFAULT_UPLOAD_KIB
        prefs["download_dir"] = str(Path(prefs.get("download_dir") or Path.home() / "Downloads").expanduser())
        prefs.setdefault("download_kib", 0)
        prefs.setdefault("listen_port", 6881)
        prefs.setdefault("max_connections", 500)
        prefs.setdefault("close_to_tray", False)
        prefs.setdefault("notify_complete", True)
        prefs.setdefault("blocked_hosts", list(DEFAULT_BLOCKED))
        prefs.setdefault("shield_learn", True)
        prefs.setdefault("shield_scope", "network")
        prefs.setdefault("file_only", True)
        prefs.setdefault("use_dht", False)
        prefs.setdefault("accept_incoming", True)
        prefs.setdefault("shield_avoid_dc", True)
        prefs.setdefault("shield_keep_seedboxes", True)
        for key, value in (("guard_skip", True), ("guard_strict", False), ("guard_motw", True), ("guard_scan", True),
                           ("guard_pause_threat", True), ("guard_vt_key", "")):
            prefs.setdefault(key, value)
        return prefs

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        self.bg = NeonBackground()
        self.bg.setMouseTracking(True)
        self.bg.installEventFilter(self)
        self.setCentralWidget(self.bg)
        root = QVBoxLayout(self.bg)
        root.setContentsMargins(14, 10, 14, 14)
        root.setSpacing(14)

        # --- title bar
        title = DragArea()
        title.setFixedHeight(72)
        tl = QHBoxLayout(title)
        tl.setContentsMargins(8, 4, 0, 0)
        tl.setSpacing(14)
        tl.addWidget(Logo(60))
        tl.addWidget(BrandTitle())
        tl.addStretch(1)
        self.conn_dot = StatusDot(10)
        self.conn_dot.set_level("warn")
        self.conn_label = QLabel("CONNECTING")
        self.conn_label.setObjectName("connection")
        self.conn_label.setFont(T.head_font(9.6, QFont.Weight.DemiBold, 1.4))
        tl.addWidget(self.conn_dot)
        tl.addWidget(self.conn_label)
        tl.addSpacing(6)
        tl.addWidget(VSeparator(40))
        self.flash_btn = GlowButton("FLASH", "bolt", "yellow", "ghost")
        self.flash_btn.setFixedSize(112, 44)
        self.flash_btn.icon_size = 18
        self.flash_btn.setFont(T.head_font(10, QFont.Weight.DemiBold, 2.0))
        self.flash_btn.setToolTip("FLASH MODE (Ctrl+Shift+F): every file source at once for big torrents.\n"
                                  "Turns on read-only DHT, local peer discovery, booster trackers and 1500 "
                                  "connections.\nPeers are still Shield-filtered; DHT directory nodes cannot be, "
                                  "so an antivirus alert is possible.")
        self.flash_btn.clicked.connect(self.toggle_flash)
        tl.addWidget(self.flash_btn)
        self.shield_btn = GlowButton("", "shield", "green", "ghost")
        self.shield_btn.setFixedSize(44, 44)
        self.shield_btn.icon_size = 22
        self.shield_btn.setToolTip("Shield · connection map (Ctrl+M)")
        self.shield_btn.clicked.connect(self.show_shield)
        tl.addWidget(self.shield_btn)
        self.settings_btn = GlowButton("", "gear", "cyan", "ghost")
        self.settings_btn.setFixedSize(44, 44)
        self.settings_btn.icon_size = 22
        self.settings_btn.setToolTip("Preferences (Ctrl+,)")
        self.settings_btn.clicked.connect(self.show_settings)
        tl.addWidget(self.settings_btn)
        tl.addWidget(VSeparator(40))
        controls = QHBoxLayout()
        controls.setSpacing(2)
        self.min_btn = WindowButton("min")
        self.min_btn.clicked.connect(self.showMinimized)
        self.max_btn = WindowButton("max")
        self.max_btn.clicked.connect(self.toggle_maximized)
        self.close_btn = WindowButton("close", danger=True)
        self.close_btn.clicked.connect(self.close)
        for b in (self.min_btn, self.max_btn, self.close_btn):
            controls.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        tl.addLayout(controls)
        tl.setAlignment(controls, Qt.AlignmentFlag.AlignTop)
        root.addWidget(title)

        # --- add torrent
        add = NeonPanel("cyan", 0.8)
        self.bg.register(add)
        add.setFixedHeight(100)
        al = QHBoxLayout(add)
        al.setContentsMargins(24, 0, 16, 0)
        al.setSpacing(16)
        add_title = SectionTitle("file_plus", "ADD TORRENT", "Add a magnet link or choose a .torrent file", True)
        add_title.setMinimumWidth(330)
        al.addWidget(add_title)
        self.uri_input = NeonLineEdit("link", "magnet:?xt=urn:btih:…")
        self.uri_input.returnPressed.connect(self.add_link)
        al.addWidget(self.uri_input, 1)
        self.add_btn = GlowButton("ADD LINK", "link", "cyan", "solid", "cyan2")
        self.add_btn.setFixedSize(158, 52)
        self.add_btn.clicked.connect(self.add_link)
        self.open_btn = GlowButton("OPEN FILE", "file", "magenta", "solid", "purple")
        self.open_btn.setFixedSize(162, 52)
        self.open_btn.clicked.connect(self.open_torrent)
        al.addWidget(self.add_btn)
        al.addWidget(self.open_btn)
        root.addWidget(add)

        # --- stats
        stats = QHBoxLayout()
        stats.setSpacing(16)
        self.down_card = StatCard("Download", "download", "cyan", clickable=True)
        self.up_card = StatCard("Upload", "upload", "magenta", tint=True, clickable=True)
        self.active_card = StatCard("Active", "users", "blue", spark=False)
        self.cap_card = StatCard("Upload limit", "gauge", "blue", spark=False, action_icon="gear")
        self.cap_card.action.setToolTip("Speed limits")
        self.cap_card.action.clicked.connect(self.show_speed_limits)
        for card in (self.down_card, self.up_card):
            card.setToolTip("Click to set speed limits")
            card.clicked.connect(self.show_speed_limits)
        for card in (self.down_card, self.up_card, self.active_card, self.cap_card):
            self.bg.register(card)
            stats.addWidget(card)
        root.addLayout(stats)

        # --- transfers
        transfers = NeonPanel("cyan", 0.55)
        self.bg.register(transfers)
        tl2 = QVBoxLayout(transfers)
        tl2.setContentsMargins(2, 8, 2, 4)
        tl2.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(22, 0, 18, 4)
        # separate pages for what is still downloading, what is finished, and everything
        self.page_tabs = FilterBar([(key, label, color) for key, label, color, _chips in PAGES],
                                   chip_class=PageTab, spacing=14)
        self.page_tabs.changed.connect(self._on_page)
        head.addWidget(self.page_tabs)
        head.addStretch(1)
        self.search = NeonLineEdit("search", "Filter torrents…")
        self.search.setFixedWidth(256)
        self.search.setStyleSheet("QLineEdit#neonInput { min-height: 38px; }")
        self.search.textChanged.connect(self._on_filter)
        head.addWidget(self.search)
        tl2.addLayout(head)
        chips = QHBoxLayout()
        chips.setContentsMargins(16, 0, 18, 0)
        self.filter_bar = FilterBar(STATUS_FILTERS)
        chips.addWidget(self.filter_bar)
        tl2.addLayout(chips)
        self.table = TransfersView()
        self.filter_bar.changed.connect(self._on_status_filter)
        self.table.selectionModel().selectionChanged.connect(self._update_actions)
        self.table.menu_requested.connect(self.show_menu)
        self.table.details_requested.connect(self.show_details)
        self.table.options_requested.connect(self.show_options)
        tl2.addWidget(self.table, 1)
        root.addWidget(transfers, 1)

        # --- footer
        footer = NeonPanel("cyan", 0.45)
        self.bg.register(footer)
        footer.setFixedHeight(74)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 26, 0)
        fl.setSpacing(12)
        self.pause_btn = GlowButton("PAUSE", "pause", "cyan", "outline")
        self.stop_btn = GlowButton("STOP", "stop", "orange", "outline")
        self.resume_btn = GlowButton("RESUME", "play", "green", "outline")
        self.remove_btn = GlowButton("REMOVE", "trash", "purple", "outline")
        self.delete_btn = GlowButton("DELETE DATA", "database", "red", "outline")
        for button, slot, width, tip in (
                (self.pause_btn, self.pause_selected, 128, "Pause: temporary, finishes blocks in flight (Space / Ctrl+P)"),
                (self.stop_btn, self.stop_selected, 116, "Stop: disconnect now, close files, no seeding; "
                                                         "stays stopped after restart (Ctrl+Shift+S)"),
                (self.resume_btn, self.resume_selected, 134, "Resume a paused or stopped torrent (Space / Ctrl+R)"),
                (self.remove_btn, self.remove_selected, 136, "Remove from list, keep files (Del)"),
                (self.delete_btn, self.delete_selected, 160, "Remove and delete downloaded files (Shift+Del)")):
            button.setFixedSize(width, 50)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            fl.addWidget(button)
        fl.addStretch(1)
        self.status_dot = StatusDot(10)
        self.status_line = StatusLine()
        fl.addWidget(self.status_dot)
        fl.addWidget(self.status_line)
        root.addWidget(footer)
        self._update_actions()

    def _build_shortcuts(self):
        def sc(keys, fn, ctx=Qt.ShortcutContext.WindowShortcut):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(ctx)
            s.activated.connect(fn)
        sc("Ctrl+O", self.open_torrent)
        sc("Ctrl+N", lambda: self.uri_input.setFocus())
        sc("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Ctrl+,", self.show_settings)
        sc("Ctrl+M", self.show_shield)
        sc("Ctrl+Shift+F", self.toggle_flash)
        sc("Ctrl+T", lambda: self.show_options(self.table.selected_keys()[0]) if self.table.selected_keys() else None)
        sc("Ctrl+Q", self.quit_app)
        sc("Ctrl+P", self.pause_selected)
        sc("Ctrl+Shift+S", self.stop_selected)
        sc("Ctrl+R", self.resume_selected)
        for number, (key, _label, _color) in enumerate(STATUS_FILTERS, 1):     # Alt+1 … Alt+8: status chips
            sc(f"Alt+{number}", lambda k=key: self.filter_bar.select(k))
        for number, (key, _label, _color, _chips) in enumerate(PAGES, 1):     # Ctrl+1 … Ctrl+3: pages
            sc(f"Ctrl+{number}", lambda k=key: self.page_tabs.select(k))
        table_ctx = Qt.ShortcutContext.WidgetShortcut
        for keys, fn in (("Delete", self.remove_selected), ("Shift+Delete", self.delete_selected),
                         ("Space", self.toggle_selected), ("Return", self.show_details),
                         ("Ctrl+V", self.paste_into_list)):
            s = QShortcut(QKeySequence(keys), self.table)
            s.setContext(table_ctx)
            s.activated.connect(fn)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction("Show NEON Torrent", self.show_window)
        menu.addSeparator()
        menu.addAction("Resume all", lambda: self.sig_resume_all.emit())
        menu.addAction("Pause all", lambda: self.sig_pause_all.emit())
        menu.addAction("Stop all", lambda: self.sig_stop_all.emit())
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _apply_theme(self):
        QApplication.instance().setStyleSheet(build_qss())
        self.setWindowIcon(logo_icon(T.c("cyan"), T.c("magenta")))
        self.tray.setIcon(self.windowIcon())
        for w in self.findChildren(QWidget):
            w.update()
        self.bg.update()
        self._refresh_icons()

    def _refresh_icons(self):
        self.menu_icons = {name: make_icon(name, T.c(color)) for name, color in (
            ("info", "cyan"), ("pause", "cyan"), ("stop", "orange"), ("play", "green"), ("refresh", "orange"), ("magnet", "magenta"),
            ("folder", "cyan"), ("copy", "magenta"), ("move", "blue"), ("trash", "purple"), ("database", "red"),
            ("sequence", "cyan"), ("search", "blue"), ("sliders", "cyan"), ("skip", "yellow"), ("shield", "green"))}

    # ------------------------------------------------------------ engine
    def _start_engine(self):
        self.engine_thread = QThread(self)
        self.engine = TorrentEngine(self.prefs)
        self.engine.moveToThread(self.engine_thread)
        self.engine_thread.started.connect(self.engine.start)
        self.engine.snapshot.connect(self._on_snapshot)
        self.engine.notice.connect(self._on_notice)
        self.engine.finished.connect(self._on_finished)
        self.engine.magnet.connect(self._on_magnet)
        self.engine.threat.connect(self._on_threat)
        # direct: ends the engine thread's event loop from inside it, with no round trip through the GUI thread
        self.engine.stopped.connect(self.engine_thread.quit, Qt.ConnectionType.DirectConnection)
        for sig, slot in ((self.sig_add_uri, self.engine.add_uri), (self.sig_add_file, self.engine.add_file),
                          (self.sig_pause, self.engine.pause), (self.sig_resume, self.engine.resume),
                          (self.sig_stop, self.engine.stop), (self.sig_stop_all, self.engine.stop_all),
                          (self.sig_remove, self.engine.remove), (self.sig_delete, self.engine.delete_data),
                          (self.sig_recheck, self.engine.recheck), (self.sig_reannounce, self.engine.reannounce),
                          (self.sig_sequential, self.engine.set_sequential),
                          (self.sig_copy_magnet, self.engine.copy_magnet),
                          (self.sig_file_priority, self.engine.set_file_priority),
                          (self.sig_move, self.engine.move_storage), (self.sig_detail, self.engine.set_detail_key),
                          (self.sig_settings, self.engine.apply_settings),
                          (self.sig_pause_all, self.engine.pause_all), (self.sig_resume_all, self.engine.resume_all),
                          (self.sig_shutdown, self.engine.shutdown),
                          (self.sig_shield_view, self.engine.set_shield_view),
                          (self.sig_shield_block, self.engine.shield_block),
                          (self.sig_shield_forget, self.engine.shield_forget),
                          (self.sig_shield_clear, self.engine.shield_clear),
                          (self.sig_flash, self.engine.set_flash),
                          (self.sig_options_key, self.engine.set_options_key),
                          (self.sig_torrent_option, self.engine.torrent_option),
                          (self.sig_skip_check, self.engine.skip_check),
                          (self.sig_scan_now, self.engine.scan_now)):
            sig.connect(slot, Qt.ConnectionType.QueuedConnection)
        self.engine_thread.start()

    @Slot(dict)
    def _on_snapshot(self, data: dict):
        self.last = data
        rows = data.get("rows", [])
        self.table.update_rows(rows)
        self.page_tabs.set_counts(page_counts(rows))
        self.filter_bar.set_counts(status_counts([r for r in rows if page_matches(self.page_tabs.current, r)]))
        history = data.get("history", [])
        self.down_card.value.setText(T.fmt_speed(data.get("down", 0)))
        self.down_card.spark.set_values([d for d, _ in history])
        self.up_card.value.setText(T.fmt_speed(data.get("up", 0)))
        self.up_card.spark.set_values([u for _, u in history])
        self.active_card.value.setText(f"{data.get('active', 0):02d}")
        self.active_card.setToolTip(f"{data.get('active', 0)} active · {data.get('peers', 0)} peers connected")
        self.cap_card.value.setText(T.fmt_limit(data.get("upload_kib", 0)).replace("KiB", "KiB"))
        dl = data.get("download_kib", 0)
        self.cap_card.setToolTip(f"Upload cap {T.fmt_limit(data.get('upload_kib', 0))} · "
                                 f"Download cap {T.fmt_limit(dl)} · Port {data.get('port') or '—'}")
        level = data.get("net_level", "warn")
        connected = data.get("listening", False) and level != "error"
        self.conn_label.setText("CONNECTED" if connected else ("OFFLINE" if level == "error" else "CONNECTING"))
        key = "green" if connected else ("red" if level == "error" else "yellow")
        self.conn_label.setStyleSheet(f"color: {T.hexc(key)};")
        self.conn_dot.set_level("ok" if connected else level)
        self.setWindowTitle(f"{APP_NAME} — ↓ {T.fmt_speed(data.get('down', 0))}  ↑ {T.fmt_speed(data.get('up', 0))}")
        self.tray.setToolTip(f"{APP_NAME}\n↓ {T.fmt_speed(data.get('down', 0))}   ↑ {T.fmt_speed(data.get('up', 0))}"
                             f"\n{data.get('active', 0)} active")
        if self.details is not None:
            row = next((r for r in rows if r["key"] == self.details.key), None)
            if row is None:
                self.details.close()
            else:
                self.details.update_row(row)
                self.details.update_detail(data.get("detail"))
        if self.shield_dialog is not None:
            self.shield_dialog.update_data(data)
        if self.options_dialog is not None:
            row = next((r for r in rows if r["key"] == self.options_dialog.key), None)
            if row is None:
                self.options_dialog.close()
            else:
                self.options_dialog.update_row(row)
                self.options_dialog.update_options(data.get("options"))
        if bool(data.get("flash")) != self.flash_btn.active:
            self.flash_btn.set_active(bool(data.get("flash")))
        shield = data.get("shield") or {}
        self.shield_btn.setToolTip(f"Shield · connection map (Ctrl+M)\n{shield.get('refused', 0)} peers refused · "
                                   f"{shield.get('learned_ips', 0)} IPs + {shield.get('networks', 0)} networks "
                                   f"learned\nMalwarebytes log: {shield.get('av', '?')}")
        self._update_actions()
        if not self.notice_timer.isActive():
            self._refresh_status()

    def _refresh_status(self):
        data = self.last
        if not data:
            return
        level = data.get("net_level", "warn")
        net_key = {"ok": "green", "warn": "yellow", "error": "red"}[level]
        net = data.get("network", "DHT CONNECTING").split(" · ")[0].replace("FILE-ONLY NETWORK", "FILE-ONLY")
        shield = data.get("shield") or {}
        segments = [("ENGINE READY", "text"), (net, net_key)]
        if data.get("flash"):
            segments.insert(1, ("⚡ FLASH MODE", "yellow"))
        if shield.get("learn"):
            refused = shield.get("refused", 0)
            segments.append((f"SHIELD{f' · {refused} REFUSED' if refused else ' ON'}", "green"))
        else:
            segments.append(("SHIELD LEARNING OFF", "yellow"))
        segments.append((f"UPLOAD CAP  {T.fmt_limit(data.get('upload_kib', 0))}", "text"))
        if data.get("download_kib"):
            segments.append((f"DOWN CAP  {T.fmt_limit(data['download_kib'])}", "text"))
        self.status_line.set_segments(segments)
        self.status_dot.set_level("ok" if level == "ok" else level)

    @Slot(str, str)
    def _on_notice(self, text: str, level: str):
        key = {"ok": "green", "warn": "yellow", "error": "red", "info": "cyan"}.get(level, "text")
        self.status_line.set_segments([(text, key)])
        self.status_dot.set_level(level if level != "info" else "info")
        self.notice_timer.start(7000 if level == "error" else 4500)

    @Slot(str)
    @Slot(str, str)
    def _on_threat(self, name: str, detail: str):
        if self.tray.isVisible():
            self.tray.showMessage("Threat found — seeding stopped", f"{name}\n{detail}",
                                  QSystemTrayIcon.MessageIcon.Critical, 10000)

    def _on_finished(self, name: str):
        if self.prefs.get("notify_complete", True) and self.tray.isVisible():
            self.tray.showMessage("Download complete", name, self.windowIcon(), 6000)

    @Slot(str)
    def _on_magnet(self, uri: str):
        QGuiApplication.clipboard().setText(uri)
        self._on_notice("MAGNET LINK COPIED", "ok")

    # ------------------------------------------------------------ actions
    def add_link(self):
        value = self.uri_input.text().strip()
        if not value:
            clip = QGuiApplication.clipboard().text().strip()
            if clip.lower().startswith(("magnet:", "http://", "https://")):
                value = clip
            else:
                self.uri_input.setFocus()
                self._on_notice("PASTE A MAGNET LINK OR .TORRENT URL FIRST", "warn")
                return
        for line in value.split():
            self.sig_add_uri.emit(line)
        self.uri_input.clear()

    def open_torrent(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open torrent", self.prefs.get("last_open_dir", str(Path.home())),
                                                "Torrent files (*.torrent);;All files (*)")
        for path in paths:
            self.sig_add_file.emit(path)
        if paths:
            self.prefs["last_open_dir"] = str(Path(paths[0]).parent)
            T.save_preferences(self.prefs)

    def add_any(self, item: str):
        item = item.strip()
        if not item:
            return
        if item.lower().endswith(".torrent") and Path(item).is_file():
            self.sig_add_file.emit(item)
        else:
            self.sig_add_uri.emit(item)

    def paste_into_list(self):
        for line in QGuiApplication.clipboard().text().split():
            if line.lower().startswith(("magnet:", "http://", "https://")):
                self.sig_add_uri.emit(line)

    def _selected_rows(self) -> list[dict]:
        return self.table.selected_rows()

    def stop_selected(self):
        keys = self.table.selected_keys()
        if keys:
            self.sig_stop.emit(keys)

    def pause_selected(self):
        keys = self.table.selected_keys()
        if keys:
            self.sig_pause.emit(keys)

    def resume_selected(self):
        keys = self.table.selected_keys()
        if keys:
            self.sig_resume.emit(keys)

    def toggle_selected(self):
        rows = self._selected_rows()
        if not rows:
            return
        if all(r["state"] in ("Paused", "Stopped", "Queued", "Error") for r in rows):
            self.sig_resume.emit([r["key"] for r in rows])
        else:
            self.sig_pause.emit([r["key"] for r in rows])

    def remove_selected(self):
        keys = self.table.selected_keys()
        if keys:
            self.sig_remove.emit(keys)

    def delete_selected(self):
        rows = self._selected_rows()
        if not rows:
            return
        names = "\n".join(f"  •  {r['title']}" for r in rows[:6]) + ("\n  …" if len(rows) > 6 else "")
        dialog = ConfirmDialog("Delete downloaded data",
                               f"Remove {len(rows)} torrent{'s' if len(rows) > 1 else ''} and permanently "
                               f"delete the downloaded files from disk?\n\n{names}", "DELETE", self)
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            self.sig_delete.emit([r["key"] for r in rows])

    def open_folder(self, key: str | None = None):
        rows = [r for r in self.table.source.rows if r["key"] == key] if key else self._selected_rows()
        if not rows:
            return
        row = rows[0]
        try:
            command = explorer_command(row["save_path"], row["name"])
            if command:
                subprocess.Popen(command, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            self._on_notice(f"CANNOT OPEN FOLDER · {exc}", "error")

    def move_selected(self, key: str | None = None):
        rows = [r for r in self.table.source.rows if r["key"] == key] if key else self._selected_rows()
        if not rows:
            return
        folder = QFileDialog.getExistingDirectory(self.options_dialog or self, "Move data to", rows[0]["save_path"])
        if folder:
            for r in rows:
                self.sig_move.emit(r["key"], folder)

    # ------------------------------------------------------------ flash / speed / per-torrent settings
    def toggle_flash(self):
        on = not self.flash_btn.active
        self.flash_btn.set_active(on)
        self.sig_flash.emit(on)

    def show_speed_limits(self):
        dialog = SpeedLimitsDialog(int(self.prefs.get("download_kib", 0)), int(self.prefs.get("upload_kib", 0)), self)
        dialog.changed.connect(self._apply_speed_limits)
        dialog.exec()

    def _apply_speed_limits(self, down_kib: int, up_kib: int):
        self.prefs["download_kib"] = down_kib
        self.prefs["upload_kib"] = up_kib
        T.save_preferences(self.prefs)
        self.sig_settings.emit(dict(self.prefs))

    def show_options(self, key: str):
        row = next((r for r in self.table.source.rows if r["key"] == key), None)
        if row is None:
            return
        if self.options_dialog is not None:
            self.options_dialog.close()
        self.options_dialog = TorrentOptionsDialog(row, self)
        self.options_dialog.option.connect(self.sig_torrent_option)
        self.options_dialog.action.connect(self._options_action)
        self.options_dialog.finished.connect(self._options_closed)
        self.sig_options_key.emit(key)
        self.options_dialog.show()

    def _options_closed(self, *_):
        self.options_dialog = None
        self.sig_options_key.emit("")

    def _options_action(self, key: str, action: str):
        row = next((r for r in self.table.source.rows if r["key"] == key), None)
        if row is None:
            return
        if action == "toggle_pause":
            if row["state"] in ("Paused", "Stopped", "Queued", "Error"):
                self.sig_resume.emit([key])
            else:
                self.sig_pause.emit([key])
        elif action == "stop":
            self.sig_stop.emit([key])
        elif action == "recheck":
            self.sig_recheck.emit([key])
        elif action == "skip_check":
            self.confirm_skip_check([key])
        elif action == "reannounce":
            self.sig_reannounce.emit([key])
        elif action == "open_folder":
            self.open_folder(key)
        elif action == "move":
            self.move_selected(key)
        elif action == "copy_magnet":
            self.sig_copy_magnet.emit(key)
        elif action == "scan_now":
            self.sig_scan_now.emit([key])
        elif action == "details":
            self._select_key(key)
            self.show_details()

    def _select_key(self, key: str):
        for r in range(self.table.proxy.rowCount()):
            index = self.table.proxy.index(r, 0)
            row = index.data(Qt.ItemDataRole.UserRole + 1)
            if row and row["key"] == key:
                self.table.selectRow(r)
                return

    def confirm_skip_check(self, keys: list):
        if not keys:
            return
        dialog = ConfirmDialog("Skip hash check",
                               "Mark the data on disk as complete without hashing it first?\n\nOnly do this for "
                               "files you know are complete (for example, re-adding a finished download). libtorrent "
                               "still verifies each piece the first time it is uploaded, and if files are missing it "
                               "falls back to a normal download.", "SKIP CHECK", self.options_dialog or self)
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            self.sig_skip_check.emit(list(keys))

    def _update_actions(self, *_):
        rows = self._selected_rows()
        has = bool(rows)
        self.pause_btn.setEnabled(has and any(r["state"] not in ("Paused", "Stopped") for r in rows))
        self.stop_btn.setEnabled(has and any(r["state"] != "Stopped" for r in rows))
        self.resume_btn.setEnabled(has and any(r["state"] in ("Paused", "Stopped", "Queued", "Error") for r in rows))
        self.remove_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)

    def show_menu(self, pos: QPoint):
        rows = self._selected_rows()
        if not rows:
            return
        keys = [r["key"] for r in rows]
        icons = self.menu_icons
        menu = QMenu(self)
        menu.addAction(icons["sliders"], "Torrent settings…", lambda: self.show_options(keys[0])).setEnabled(
            len(rows) == 1)
        menu.addAction(icons["info"], "Details…", self.show_details).setEnabled(len(rows) == 1)
        menu.addSeparator()
        paused = all(r["state"] in ("Paused", "Stopped", "Queued", "Error") for r in rows)
        if paused:
            menu.addAction(icons["play"], "Resume", lambda: self.sig_resume.emit(keys))
        else:
            menu.addAction(icons["pause"], "Pause", lambda: self.sig_pause.emit(keys))
        if not all(r["state"] == "Stopped" for r in rows):
            menu.addAction(icons["stop"], "Stop (close files, no seeding)", lambda: self.sig_stop.emit(keys))
        menu.addAction(icons["refresh"], "Force recheck", lambda: self.sig_recheck.emit(keys))
        menu.addAction(icons["skip"], "Skip hash check…", lambda: self.confirm_skip_check(keys))
        menu.addAction(icons["shield"], "Scan now (Download Guard)", lambda: self.sig_scan_now.emit(keys))
        menu.addAction(icons["search"], "Ask trackers for more peers", lambda: self.sig_reannounce.emit(keys))
        seq = QAction(icons["sequence"], "Sequential download", menu)
        seq.setCheckable(True)
        seq.setChecked(all(r["sequential"] for r in rows))
        seq.toggled.connect(lambda on: self.sig_sequential.emit(keys, on))
        menu.addAction(seq)
        menu.addSeparator()
        menu.addAction(icons["folder"], "Open folder", lambda: self.open_folder(keys[0]))
        menu.addAction(icons["copy"], "Copy magnet link", lambda: self.sig_copy_magnet.emit(keys[0])).setEnabled(
            len(rows) == 1)
        menu.addAction(icons["move"], "Move data…", self.move_selected)
        menu.addSeparator()
        menu.addAction(icons["trash"], "Remove (keep files)", self.remove_selected)
        menu.addAction(icons["database"], "Delete data…", self.delete_selected)
        menu.exec(pos)

    def show_details(self):
        rows = self._selected_rows()
        if not rows:
            return
        if self.details is not None:
            self.details.close()
        self.details = DetailsDialog(rows[0], self)
        self.details.priority_changed.connect(self.sig_file_priority)
        self.details.open_folder.connect(self.open_folder)
        self.details.copy_magnet.connect(self.sig_copy_magnet)
        self.details.finished.connect(self._details_closed)
        self.sig_detail.emit(rows[0]["key"])
        self.details.show()

    def _details_closed(self, *_):
        self.details = None
        self.sig_detail.emit("")

    def show_shield(self):
        if self.shield_dialog is not None:
            self.shield_dialog.raise_()
            self.shield_dialog.activateWindow()
            return
        self.shield_dialog = ShieldDialog(self)
        self.shield_dialog.block.connect(self.sig_shield_block)
        self.shield_dialog.forget.connect(self.sig_shield_forget)
        self.shield_dialog.clear_all.connect(self._confirm_clear_shield)
        self.shield_dialog.open_settings.connect(lambda: self.show_settings("shield"))
        self.shield_dialog.finished.connect(self._shield_closed)
        if self.last:
            self.shield_dialog.update_data(self.last)
        self.sig_shield_view.emit(True)
        self.shield_dialog.show()

    def _shield_closed(self, *_):
        self.shield_dialog = None
        self.sig_shield_view.emit(False)

    def _confirm_clear_shield(self):
        dialog = ConfirmDialog("Clear learned blocks",
                               "Forget every IP, network and tracker the Shield learned from Malwarebytes? "
                               "Old detections will not be re-imported; new ones are still learned.", "CLEAR",
                               self.shield_dialog or self)
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            self.sig_shield_clear.emit()

    def show_settings(self, tab: str = ""):
        dialog = SettingsDialog(dict(self.prefs, _open_tab=tab), self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.prefs.update(values)
        T.save_preferences(self.prefs)
        if T.theme_name() != values["theme"]:
            T.set_theme(values["theme"])
            self._apply_theme()
        self.sig_settings.emit(dict(self.prefs))

    def _on_filter(self, text: str):
        self.table.proxy.set_query(text)
        self.table.viewport().update()

    def _on_page(self, key: str):
        page = next(p for p in PAGES if p[0] == key)
        self.table.proxy.set_page(key)
        self.filter_bar.show_only(page[3])
        for column in range(self.table.model().columnCount()):
            self.table.setColumnHidden(column, column in HIDDEN_ON_PAGE.get(key, set()))
        if self.last:
            rows = self.last.get("rows", [])
            self.filter_bar.set_counts(status_counts([r for r in rows if page_matches(key, r)]))
        self.table.viewport().update()
        if self.prefs.get("page") != key:
            self.prefs["page"] = key
            T.save_preferences(self.prefs)

    def _on_status_filter(self, key: str):
        self.table.proxy.set_status(key)
        self.table.viewport().update()
        if self.prefs.get("status_filter") != key:
            self.prefs["status_filter"] = key
            T.save_preferences(self.prefs)

    # ------------------------------------------------------------ window chrome
    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            self.max_btn.icon_name = "restore" if self.isMaximized() else "max"
            self.max_btn.update()
            self.bg.update()
        super().changeEvent(event)

    def _edges_at(self, pos) -> Qt.Edge:
        if self.isMaximized():
            return Qt.Edge(0)
        x, y, w, h = pos.x(), pos.y(), self.bg.width(), self.bg.height()
        edges = Qt.Edge(0)
        if x <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        if x >= w - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if y <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        if y >= h - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, obj, event):
        if obj is self.bg:
            if event.type() == QEvent.Type.MouseMove:
                edges = self._edges_at(event.position().toPoint())
                cursors = {
                    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
                    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
                    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
                    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
                    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
                    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
                }
                shape = cursors.get(edges)
                if shape is not None:
                    self.bg.setCursor(shape)
                else:
                    self.bg.unsetCursor()
            elif event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                edges = self._edges_at(event.position().toPoint())
                if edges != Qt.Edge(0) and self.windowHandle() is not None:
                    self.windowHandle().startSystemResize(edges)
                    return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md.hasUrls() or (md.hasText() and md.text().strip().lower().startswith(("magnet:", "http"))):
            event.acceptProposedAction()
            self.bg.setStyleSheet("")
            self._on_notice("DROP TO ADD TORRENT", "info")

    def dropEvent(self, event):
        md = event.mimeData()
        if md.hasUrls():
            for url in md.urls():
                if url.isLocalFile():
                    self.add_any(url.toLocalFile())
                else:
                    self.sig_add_uri.emit(url.toString())
        elif md.hasText():
            for line in md.text().split():
                self.add_any(line)
        event.acceptProposedAction()

    # ------------------------------------------------------------ tray / lifecycle
    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        self.quitting = True
        self.close()

    def closeEvent(self, event):
        if not self.quitting and self.prefs.get("close_to_tray") and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "Still running in the tray. Right-click the icon to quit.",
                                  self.windowIcon(), 3000)
            return
        event.ignore()
        if self.shutting_down:
            return
        self.shutting_down = True
        for dialog in (self.details, self.shield_dialog, self.options_dialog):
            if dialog is not None:
                dialog.close()
        # Saving resume data and telling trackers we stopped takes a few seconds. Hide at once and let the engine
        # finish in its own thread: blocking the GUI thread for it made Windows mark the window "Not responding".
        self.hide()
        self.tray.hide()
        app = QApplication.instance()
        if self.engine_thread.isRunning():
            self.engine_thread.finished.connect(app.quit)
            QTimer.singleShot(60000, app.quit)            # resume data needs up to 45 s; never linger longer
            self.sig_shutdown.emit()
        else:
            app.quit()


def explorer_command(save_path: str, name: str) -> list[str] | None:
    """Explorer command that *selects* a downloaded item (never launches it). The name comes from the torrent,
    so it is resolved and must stay inside the save folder; otherwise only the folder itself is opened."""
    explorer = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe")   # absolute: no PATH lookup
    base = Path(save_path).resolve()
    if not base.is_dir():
        return None
    target = (base / name).resolve()
    if target != base and target.is_relative_to(base) and target.exists():
        return [explorer, "/select,", str(target)]
    return [explorer, str(base)]


def send_to_running_instance(args: list[str]) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(400):
        return False
    socket.write(("\n".join(args) if args else "__show__").encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(1000)
    reply = bytes(socket.readAll()) if socket.waitForReadyRead(1500) else b""
    socket.disconnectFromServer()
    if reply != b"closing":
        return True
    # the running copy is quitting and still saving resume data: wait for it to exit, then start normally,
    # instead of handing the links to a window that is about to disappear
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        probe = QLocalSocket()
        probe.connectToServer(SERVER_NAME)
        if not probe.waitForConnected(300):
            return False
        probe.disconnectFromServer()
        time.sleep(0.5)
    return False


def first_run() -> None:
    """Ask for the download folder once, before the engine starts; closing the dialog keeps the default."""
    prefs = T.load_preferences()
    if prefs.get("download_dir"):
        return
    downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    QApplication.instance().setStyleSheet(build_qss())
    dialog = FirstRunDialog(str(Path(downloads or Path.home() / "Downloads") / "NEON"))
    dialog.exec()
    prefs["download_dir"] = dialog.folder.text()
    T.save_preferences(prefs)


def main() -> int:
    if sys.platform == "win32":
        import ctypes  # own taskbar identity/icon instead of grouping with python.exe
        length = ctypes.c_uint32(0)
        # an MSIX install already has its package identity; 15700 = APPMODEL_ERROR_NO_PACKAGE (plain folder)
        if ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(length), None) == 15700:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NeonTorrent.Client")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("NeonTorrent")
    app.setFont(T.font(10))
    args = [a for a in sys.argv[1:] if a.strip()]
    if send_to_running_instance(args):
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # only this Windows user may send links
    server.listen(SERVER_NAME)
    app.setQuitOnLastWindowClosed(False)
    first_run()
    window = TorrentWindow()

    def on_connection():
        sock = server.nextPendingConnection()

        def read():
            if window.shutting_down:
                sock.write(b"closing")    # the new launch waits for this instance to finish saving, then starts
                sock.flush()
                return
            sock.write(b"ok")
            sock.flush()
            payload = bytes(sock.readAll()).decode("utf-8", "replace")
            lines = payload.splitlines()
            commands = {"--pause-all": window.sig_pause_all.emit, "--resume-all": window.sig_resume_all.emit,
                        "--stop-all": window.sig_stop_all.emit}
            if not any(line in commands for line in lines):
                window.show_window()
            for line in lines:
                if line in commands:
                    commands[line]()                 # run.bat --pause-all / --resume-all (same Windows user only)
                elif line != "__show__":
                    window.add_any(line)
        sock.readyRead.connect(read)
    server.newConnection.connect(on_connection)
    window.show()
    for arg in args:
        if not arg.startswith("--"):
            QTimer.singleShot(1500, lambda a=arg: window.add_any(a))
    code = app.exec()
    thread = window.engine_thread
    if thread.isRunning() and not thread.wait(15000):
        os._exit(code)            # engine stuck (e.g. a tracker that never answers) after its 45 s save window
    return code


if __name__ == "__main__":
    raise SystemExit(main())
