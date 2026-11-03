"""Transfers table: a real model (rows updated in place, no per-second rebuild) + a neon delegate."""
from __future__ import annotations

import html

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QPointF, QRectF, QSortFilterProxyModel, Qt,
                            Signal)
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTableView

from . import theme as T
from .icons import paint_badge, paint_icon

ROW_ROLE = Qt.ItemDataRole.UserRole + 1
SORT_ROLE = Qt.ItemDataRole.UserRole + 2
COLUMNS = ["NAME", "STATUS", "PROGRESS", "SIZE", "↓  SPEED", "↑  SPEED", ""]
COL_NAME, COL_STATUS, COL_PROGRESS, COL_SIZE, COL_DOWN, COL_UP, COL_MENU = range(7)
STATE_ORDER = {"Downloading": 0, "Metadata": 1, "Checking": 2, "Seeding": 3, "Queued": 4, "Paused": 5, "Stopped": 6,
               "Error": 7, "Disk full": 8}
# Status filter chips above the list, in display order: (key, label, palette colour)
STATUS_FILTERS = [("all", "ALL", "cyan"), ("downloading", "DOWNLOADING", "cyan2"), ("seeding", "SEEDING", "green"),
                  ("completed", "COMPLETED", "green"), ("active", "ACTIVE", "magenta"), ("paused", "PAUSED", "yellow"),
                  ("stopped", "STOPPED", "muted"), ("errors", "ERRORS", "red")]


# page key, tab label, colour, the status chips that make sense on that page
PAGES = [("downloading", "DOWNLOADING", "cyan2", ["all", "active", "paused", "stopped", "errors"]),
         ("completed", "COMPLETED", "green", ["all", "seeding", "active", "stopped", "errors"]),
         ("all", "ALL TRANSFERS", "cyan", [key for key, _label, _color in STATUS_FILTERS])]
HIDDEN_ON_PAGE = {"completed": {2, 4}}  # columns that are always 100% / 0 B/s there: PROGRESS, ↓ SPEED


def page_matches(page: str, row: dict) -> bool:
    if page == "downloading":
        return row["progress"] < 1
    if page == "completed":
        return row["progress"] >= 1
    return True


def page_counts(rows: list[dict]) -> dict[str, int]:
    return {key: sum(1 for row in rows if page_matches(key, row)) for key, _label, _color, _chips in PAGES}


def status_matches(key: str, row: dict) -> bool:
    state = row["state"]
    if key == "downloading":
        return row["progress"] < 1 and state in ("Downloading", "Metadata", "Checking", "Queued")
    if key == "seeding":
        return state == "Seeding"
    if key == "completed":
        return row["progress"] >= 1
    if key == "active":
        return row["down"] > 0 or row["up"] > 0
    if key == "paused":
        return state == "Paused"
    if key == "stopped":
        return state == "Stopped"
    if key == "errors":
        return state in ("Error", "Disk full") or bool(row["error"])
    return True


def status_counts(rows: list[dict]) -> dict[str, int]:
    return {key: sum(1 for row in rows if status_matches(key, row)) for key, _label, _color in STATUS_FILTERS}


def guard_badge(guard: dict) -> tuple[str, str] | None:
    """(text, colour key) for the Download Guard line under a torrent's status."""
    if not guard:
        return None
    scan, skipped, level = guard.get("scan", ""), guard.get("skipped", 0), guard.get("level", "")
    if scan == "threat":
        return "☣ THREAT FOUND · seeding stopped", "red"
    if scan == "scanning":
        return "⟳ Guard scanning…", "cyan"
    if skipped:
        return f"⚠ {skipped} risky file{'s' if skipped != 1 else ''} skipped", "yellow"
    if level == "danger":
        return "⚠ dangerous files (not skipped)", "red"
    if scan == "clean":
        return "✓ scanned clean", "green"
    if guard.get("marked"):
        return "✓ marked · SmartScreen-checked", "green"
    if level == "caution":
        return "◆ contains programs", "orange"
    return None


class TorrentModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = index.column()
        if role == ROW_ROLE:
            return row
        if role == SORT_ROLE:
            return {COL_NAME: row["title"].casefold(), COL_STATUS: STATE_ORDER.get(row["state"], 9),
                    COL_PROGRESS: row["progress"], COL_SIZE: row["size"], COL_DOWN: row["down"],
                    COL_UP: row["up"], COL_MENU: row.get("queue", 0)}[col]
        if role == Qt.ItemDataRole.DisplayRole:
            return row["title"] if col == COL_NAME else None
        if role == Qt.ItemDataRole.ToolTipRole and col != COL_MENU:
            lines = [row["name"], f"{row['state']} · {row['progress'] * 100:.1f}%",
                     f"{T.fmt_bytes(row['done'])} of {T.fmt_bytes(row['size'])}"]
            if row["state"] == "Downloading":
                lines.append(f"ETA {T.fmt_eta(row['eta'])}")
            lines.append(f"Seeds {row['seeds']} ({row['list_seeds']}) · Peers {row['peers']} ({row['list_peers']})")
            lines.append(f"Ratio {row['ratio']:.2f} · Uploaded {T.fmt_bytes(row['uploaded'])}")
            lines.append(row["save_path"])
            if row["error"]:
                lines.append("Error: " + row["error"])
            guard = row.get("guard") or {}
            badge = guard_badge(guard)
            if badge:
                lines.append("Download Guard: " + badge[0])
            if guard.get("detail"):
                lines.append(guard["detail"])
            # names come from the torrent file: escape them so Qt never renders them as rich text
            return "<qt>" + "<br>".join(html.escape(line) for line in lines) + "</qt>"
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def update_rows(self, rows: list[dict]) -> None:
        new_keys = [r["key"] for r in rows]
        wanted = set(new_keys)
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
            else:
                self.rows[i] = row
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMNS) - 1))
        if fresh:
            start = len(self.rows)
            self.beginInsertRows(QModelIndex(), start, start + len(fresh) - 1)
            self.rows.extend(fresh)
            self.endInsertRows()


class TorrentFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.status = "all"
        self.page = "all"
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)

    def set_query(self, text: str) -> None:
        self.query = text.strip().casefold()
        self.invalidateFilter()

    def set_status(self, key: str) -> None:
        self.status = key
        self.invalidateFilter()

    def set_page(self, key: str) -> None:
        self.page = key
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        row = self.sourceModel().rows[source_row]
        if not page_matches(self.page, row) or not status_matches(self.status, row):
            return False
        if not self.query:
            return True
        hay = f"{row['title']} {row['name']} {row['state']}".casefold()
        return all(part in hay for part in self.query.split())


class TorrentDelegate(QStyledItemDelegate):
    def __init__(self, view: "TransfersView"):
        super().__init__(view)
        self.view = view
        self.f_title = T.font(11.2, QFont.Weight.DemiBold)
        self.f_sub = T.font(9.2)
        self.f_cell = T.font(10.6)
        self.f_status = T.font(10.6, QFont.Weight.Medium)

    def paint(self, p: QPainter, option, index):
        row = index.data(ROW_ROLE)
        if row is None:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == self.view.hover_row
        col = index.column()
        visual = self.view.horizontalHeader().visualIndex(col)
        last_visual = self.view.model().columnCount() - 1
        # row background
        if selected or hovered:
            bg = T.c("cyan", 26 if selected else 12)
            p.fillRect(r, bg)
        if selected:
            p.setPen(QPen(T.c("cyan", 90), 1))
            p.drawLine(r.topLeft(), r.topRight())
            p.drawLine(r.bottomLeft() - QPointF(0, 1), r.bottomRight() - QPointF(0, 1))
            if visual == 0:
                bar = QRectF(r.left() + 1, r.top() + 10, 3, r.height() - 20)
                glow = QRadialGradient(bar.center(), 18)
                glow.setColorAt(0, T.c("cyan", 120)); glow.setColorAt(1, T.c("cyan", 0))
                p.fillRect(QRectF(r.left(), r.top(), 22, r.height()), glow)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(T.c("cyan"))
                p.drawRoundedRect(bar, 1.5, 1.5)
        else:
            p.setPen(QPen(T.c("line", 150), 1))
            p.drawLine(r.bottomLeft() - QPointF(0, 0.5), r.bottomRight() - QPointF(0, 0.5))
        _ = last_visual
        cy = r.center().y()
        left = r.left() + (24 if visual == 0 else 4)
        if col == COL_NAME:
            badge = QRectF(left, cy - 21, 42, 42)
            paint_badge(p, badge, row["kind"])
            tx = badge.right() + 18
            width = r.right() - tx - 10
            title_hover = self.view.hover_title_row == index.row()
            p.setFont(self.f_title)
            p.setPen(T.c("cyan") if title_hover else T.c("text"))
            fm = QFontMetricsF(self.f_title)
            title = fm.elidedText(row["title"], Qt.TextElideMode.ElideRight, width)
            p.drawText(QRectF(tx, cy - 22, width, 24), Qt.AlignmentFlag.AlignVCenter, title)
            if title_hover:
                underline_y = cy - 22 + 12 + fm.ascent() / 2 + 2
                p.setPen(QPen(T.c("cyan", 200), 1.2))
                p.drawLine(QPointF(tx, underline_y), QPointF(tx + fm.horizontalAdvance(title), underline_y))
            p.setFont(self.f_sub)
            p.setPen(T.c("muted"))
            fs = QFontMetricsF(self.f_sub)
            p.drawText(QRectF(tx, cy + 1, width, 20), Qt.AlignmentFlag.AlignVCenter,
                       fs.elidedText(row["sub"], Qt.TextElideMode.ElideMiddle, width))
        elif col == COL_STATUS:
            color = T.state_color(row["state"])
            badge = guard_badge(row.get("guard") or {})
            shift = -8 if badge else 0
            dot = QPointF(left + 7, cy + shift)
            halo = QRadialGradient(dot, 11)
            halo.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 150))
            halo.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(dot, 11, 11)
            p.setBrush(color)
            p.drawEllipse(dot, 5, 5)
            p.setFont(self.f_status)
            p.setPen(color)
            label = {"Metadata": "Metadata"}.get(row["state"], row["state"])
            if row.get("select") and row["state"] == "Paused":
                label = "Choose files"             # waits for its Add dialog; Resume opens it again
            p.drawText(QRectF(left + 22, r.top() + 2 * shift, r.width() - 30, r.height()),
                       Qt.AlignmentFlag.AlignVCenter, label)
            if badge:
                text, key = badge
                p.setFont(self.f_sub)
                p.setPen(T.c(key))
                fs = QFontMetricsF(self.f_sub)
                p.drawText(QRectF(left, cy + 4, r.width() - 8, 18), Qt.AlignmentFlag.AlignVCenter,
                           fs.elidedText(text, Qt.TextElideMode.ElideRight, r.width() - 10))
        elif col == COL_PROGRESS:
            pct = row["progress"]
            text = f"{pct * 100:.0f}%" if pct < 0.995 or pct >= 1 else "99%"
            size = row["size"]
            sub = f"{T.fmt_bytes(min(row.get('done', 0), size))} / {T.fmt_bytes(size)}" if size else ""
            p.setFont(self.f_cell)
            fm = QFontMetricsF(self.f_cell)
            text_w = 52.0
            bar = QRectF(left, cy - 6 - (7 if sub else 0), max(40.0, r.width() - text_w - 22), 12)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(T.c("track"))
            p.drawRoundedRect(bar, 6, 6)
            if pct > 0:
                fill = QRectF(bar.left(), bar.top(), max(bar.height(), bar.width() * pct), bar.height())
                c1, c2 = self._bar_colors(row["state"])
                for spread, alpha in ((6, 26), (3, 50)):
                    glow = QColor(c2); glow.setAlpha(alpha)
                    p.setBrush(glow)
                    p.drawRoundedRect(fill.adjusted(-spread / 2, -spread / 2, spread / 2, spread / 2),
                                      6 + spread / 2, 6 + spread / 2)
                grad = QLinearGradient(fill.topLeft(), fill.topRight())
                grad.setColorAt(0, c1)
                grad.setColorAt(1, c2)
                p.setBrush(grad)
                p.drawRoundedRect(fill, 6, 6)
                p.setBrush(QColor(255, 255, 255, 55))
                p.drawRoundedRect(QRectF(fill.left() + 3, fill.top() + 2, fill.width() - 6, 2.5), 1.2, 1.2)
            p.setPen(T.c("text"))
            p.drawText(QRectF(bar.right() + 14, bar.center().y() - 12, text_w, 24), Qt.AlignmentFlag.AlignVCenter,
                       text)
            if sub:                                # downloaded / total under the bar
                p.setFont(self.f_sub)
                p.setPen(T.c("muted"))
                fs = QFontMetricsF(self.f_sub)
                p.drawText(QRectF(left, cy + 4, bar.width() + text_w, 18), Qt.AlignmentFlag.AlignVCenter,
                           fs.elidedText(sub, Qt.TextElideMode.ElideRight, bar.width() + text_w))
            _ = fm
        elif col in (COL_SIZE, COL_DOWN, COL_UP):
            if col == COL_SIZE:
                text = T.fmt_bytes(row["size"]) if row["size"] else "—"
                color = T.c("text", 225)
            else:
                value = row["down"] if col == COL_DOWN else row["up"]
                text = T.fmt_speed(value)
                color = T.c("text", 225) if value > 0 else T.c("muted")
            p.setFont(self.f_cell)
            p.setPen(color)
            p.drawText(QRectF(left, r.top(), r.width() - 8, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
            if col == COL_DOWN and row["state"] == "Downloading" and row["down"] > 0:
                p.setFont(self.f_sub)
                p.setPen(T.c("muted"))
                p.drawText(QRectF(left, cy + 9, r.width() - 8, 18), Qt.AlignmentFlag.AlignVCenter,
                           f"ETA {T.fmt_eta(row['eta'])}")
        elif col == COL_MENU:
            over = hovered and self.view.hover_col == COL_MENU
            box = QRectF(r.center().x() - 17, cy - 15, 34, 30)
            if over:
                p.setPen(QPen(T.c("cyan", 160), 1))
                p.setBrush(T.c("cyan", 30))
                p.drawRoundedRect(box, 7, 7)
            paint_icon(p, "dots", QRectF(r.center().x() - 11, cy - 11, 22, 22),
                       T.c("cyan") if over else T.c("text", 200), 1.8, glow=over)
        p.restore()

    @staticmethod
    def _bar_colors(state: str) -> tuple[QColor, QColor]:
        pairs = {
            "Downloading": ("cyan2", "cyan"), "Metadata": ("cyan2", "cyan"), "Seeding": ("green", "green"),
            "Paused": ("yellow", "orange"), "Stopped": ("muted", "muted"), "Checking": ("orange", "yellow"), "Queued": ("purple", "magenta"),
            "Error": ("red", "magenta"), "Disk full": ("red", "orange"),
        }
        a, b = pairs.get(state, ("cyan2", "cyan"))
        c1, c2 = T.c(a), T.c(b)
        if state == "Seeding":
            c1 = c1.darker(115)
        if state == "Paused":
            c1, c2 = T.c("yellow").darker(105), T.c("yellow")
        return c1, c2


class TransfersView(QTableView):
    menu_requested = Signal(object)          # global QPoint
    details_requested = Signal()
    options_requested = Signal(str)          # torrent key: its name was clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover_row = -1
        self.hover_col = -1
        self.hover_title_row = -1
        self.source = TorrentModel(self)
        self.proxy = TorrentFilter(self)
        self.proxy.setSourceModel(self.source)
        self.setModel(self.proxy)
        self.setItemDelegate(TorrentDelegate(self))
        self.setObjectName("transfers")
        self.setShowGrid(False)
        self.setMouseTracking(True)
        self.setFrameShape(QTableView.Shape.NoFrame)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSortingEnabled(True)
        self.sortByColumn(COL_MENU, Qt.SortOrder.AscendingOrder)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        vh = self.verticalHeader()
        vh.setVisible(False)
        vh.setDefaultSectionSize(68)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionsMovable(True)
        hh.setFixedHeight(42)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(COL_MENU, QHeaderView.ResizeMode.Fixed)
        hh.setMinimumSectionSize(60)
        for col, width in ((COL_STATUS, 152), (COL_PROGRESS, 250), (COL_SIZE, 112), (COL_DOWN, 136),
                           (COL_UP, 118), (COL_MENU, 66)):
            self.setColumnWidth(col, width)
        hh.setSortIndicatorShown(False)
        self.empty_text = ("NO TORRENTS YET", "Paste a magnet link, open a .torrent file, or drop one anywhere here.")

    # -------------------------------------------------- selection helpers
    def selected_keys(self) -> list[str]:
        keys = []
        for index in self.selectionModel().selectedRows():
            row = index.data(ROW_ROLE)
            if row:
                keys.append(row["key"])
        return keys

    def selected_rows(self) -> list[dict]:
        return [i.data(ROW_ROLE) for i in self.selectionModel().selectedRows() if i.data(ROW_ROLE)]

    def update_rows(self, rows: list[dict]) -> None:
        self.source.update_rows(rows)
        self.viewport().update()

    # -------------------------------------------------- events
    def _title_hit(self, index, pos) -> bool:
        """True if pos (viewport coordinates) is on the torrent's name text in the NAME column."""
        if not index.isValid() or index.column() != COL_NAME:
            return False
        row = index.data(ROW_ROLE)
        if not row:
            return False
        r = QRectF(self.visualRect(index))
        left = r.left() + (24 if self.horizontalHeader().visualIndex(COL_NAME) == 0 else 4)
        tx = left + 42 + 18
        fm = QFontMetricsF(self.itemDelegate().f_title)
        width = min(fm.horizontalAdvance(row["title"]), r.right() - tx - 10)
        cy = r.center().y()
        return QRectF(tx - 2, cy - 22, width + 4, 24).contains(QPointF(pos))

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        row, col = (index.row(), index.column()) if index.isValid() else (-1, -1)
        title_row = row if self._title_hit(index, pos) else -1
        if (row, col, title_row) != (self.hover_row, self.hover_col, self.hover_title_row):
            self.hover_row, self.hover_col, self.hover_title_row = row, col, title_row
            self.viewport().update()
            pointer = col == COL_MENU or title_row >= 0
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if pointer else Qt.CursorShape.ArrowCursor)
            self.viewport().setToolTip("Click to open this torrent's settings" if title_row >= 0 else "")
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_row = self.hover_col = self.hover_title_row = -1
        self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            self.clearSelection()
        if index.isValid() and index.column() == COL_MENU and event.button() == Qt.MouseButton.LeftButton:
            if not self.selectionModel().isRowSelected(index.row(), QModelIndex()):
                self.selectRow(index.row())
            self.menu_requested.emit(event.globalPosition().toPoint())
            return
        plain = event.modifiers() == Qt.KeyboardModifier.NoModifier
        if (event.button() == Qt.MouseButton.LeftButton and plain
                and self._title_hit(index, event.position().toPoint())):
            self.selectRow(index.row())
            self.options_requested.emit(index.data(ROW_ROLE)["key"])
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.indexAt(event.position().toPoint()).isValid():
            self.details_requested.emit()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            if not self.selectionModel().isRowSelected(index.row(), QModelIndex()):
                self.selectRow(index.row())
            self.menu_requested.emit(event.globalPos())

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.proxy.rowCount() == 0:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = QRectF(self.viewport().rect())
            filtered = self.source.rowCount() > 0
            title = "NO MATCHES" if filtered else self.empty_text[0]
            sub = "Nothing matches the filter." if filtered else self.empty_text[1]
            icon = QRectF(r.center().x() - 26, r.center().y() - 64, 52, 52)
            paint_icon(p, "search" if filtered else "magnet", icon, T.c("cyan", 200), 1.6, glow=True)
            p.setFont(T.head_font(13, QFont.Weight.DemiBold, 2.0))
            p.setPen(T.c("text"))
            p.drawText(QRectF(r.left(), icon.bottom() + 12, r.width(), 26), Qt.AlignmentFlag.AlignHCenter, title)
            p.setFont(T.font(10))
            p.setPen(T.c("muted"))
            p.drawText(QRectF(r.left(), icon.bottom() + 42, r.width(), 24), Qt.AlignmentFlag.AlignHCenter, sub)
