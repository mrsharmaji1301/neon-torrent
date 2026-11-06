"""FILE SHARING tab (C-11): QR pairing, network facts, thumbnail grids and progress for PC <-> phone transfers.

The server (share.py) runs in its own threads; this tab polls ``ShareServer.snapshot()`` a few times a second and
calls its thread-safe methods. Thumbnails come from the Windows shell (IShellItemImageFactory) in a worker pool.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import Callable

import segno
from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QPointF, QRectF, QRunnable, QSize,
                            QThreadPool, QTimer, Qt, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QImageReader, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QTextOption)
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from . import share as S
from . import theme as T
from .dialogs import NeonDialog
from .icons import paint_icon
from .widgets import FilterBar, GlowButton, NeonPanel, PageTab, SectionTitle, StatusDot

TILE_W, TILE_H, THUMB = 150, 192, 134
KINDS = {"image": ("jpg jpeg png gif webp heic heif bmp avif tif tiff", "cyan"),
         "video": ("mp4 mov mkv webm avi m4v 3gp ts wmv", "magenta"),
         "audio": ("mp3 m4a wav flac aac ogg opus wma", "green"),
         "archive": ("zip rar 7z tar gz tgz bz2 xz iso", "yellow"),
         "document": ("pdf doc docx xls xlsx ppt pptx txt rtf odt csv md", "blue"),
         "app": ("apk exe msi msix appx", "orange")}
STATUS = {"ready": ("READY TO CONNECT", "info"), "waiting": ("WAITING FOR APPROVAL", "warn"),
          "connected": ("CONNECTED", "ok"), "transferring": ("TRANSFERRING", "info"),
          "lost": ("DISCONNECTED", "error"), "stopped": ("STOPPED", "warn"), "offline": ("NO NETWORK", "error")}


def kind_of(name: str) -> tuple[str, str]:
    ext = Path(name).suffix.lower().lstrip(".")
    for kind, (exts, color) in KINDS.items():
        if ext and ext in exts.split():
            return kind, color
    return "file", "muted"


# ------------------------------------------------------------------ Windows shell thumbnails
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


IID_IShellItemImageFactory = _GUID.from_buffer_copy(uuid.UUID("bcc18b79-ba16-442f-80c4-8a59c30c463b").bytes_le)
SIIGBF_BIGGERSIZEOK, SIIGBF_THUMBNAILONLY = 0x1, 0x8


def shell_thumbnail(path: str, size: int = 256) -> QImage | None:
    """The thumbnail Explorer shows (photo, video first frame, PDF page …), or None if the shell has none."""
    if sys.platform != "win32":
        return None
    ole32, shell32, gdi32 = ctypes.windll.ole32, ctypes.windll.shell32, ctypes.windll.gdi32
    init = ole32.CoInitializeEx(None, 0x2)              # apartment-threaded, as the shell expects
    try:
        factory = ctypes.c_void_p()
        create = shell32.SHCreateItemFromParsingName
        create.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        if create(path, None, ctypes.byref(IID_IShellItemImageFactory), ctypes.byref(factory)) != 0 or not factory:
            return None
        vtable = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0],
                             ctypes.POINTER(ctypes.c_void_p))
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, _SIZE, ctypes.c_int,
                                       ctypes.POINTER(wintypes.HBITMAP))(vtable[3])
        bitmap = wintypes.HBITMAP()
        try:
            hr = get_image(factory, _SIZE(size, size), SIIGBF_BIGGERSIZEOK | SIIGBF_THUMBNAILONLY,
                           ctypes.byref(bitmap))
        finally:
            release(factory)
        if hr != 0 or not bitmap:
            return None
        try:
            image = QImage.fromHBITMAP(bitmap.value)
        finally:
            gdi32.DeleteObject(bitmap)
        if image.isNull():
            return None
        if image.hasAlphaChannel() and image.pixelColor(image.width() // 2, image.height() // 2).alpha() == 0:
            image.reinterpretAsFormat(QImage.Format.Format_RGB32)       # photo thumbnails come with alpha = 0
        return image.copy()
    except (OSError, AttributeError, ValueError):
        return None
    finally:
        if init in (0, 1):
            ole32.CoUninitialize()


def cover(image: QImage, size: int) -> QImage:
    """Centre-crop to a square of ``size`` pixels."""
    scaled = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                          Qt.TransformationMode.SmoothTransformation)
    return scaled.copy((scaled.width() - size) // 2, (scaled.height() - size) // 2, size, size)


class _ThumbSignals(QObject):
    done = Signal(str, QImage, QByteArray)


class _ThumbJob(QRunnable):
    def __init__(self, key: str, path: str, signals: _ThumbSignals):
        super().__init__()
        self.key, self.path, self.signals = key, path, signals

    def run(self) -> None:
        image = shell_thumbnail(self.path)
        if image is None and kind_of(self.path)[0] == "image":
            reader = QImageReader(self.path)
            reader.setAutoTransform(True)
            if reader.size().isValid():
                reader.setScaledSize(reader.size().scaled(QSize(320, 320), Qt.AspectRatioMode.KeepAspectRatioByExpanding))
            image = reader.read() if reader.canRead() else None
        if image is None or image.isNull():
            return
        square = cover(image.convertToFormat(QImage.Format.Format_RGB32), 240)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        cover(square, 160).save(buffer, "JPEG", 72)                   # the phone gets a small preview
        buffer.close()
        self.signals.done.emit(self.key, square, data)


# ------------------------------------------------------------------ widgets
class TopTab(PageTab):
    """Window-level tab (TORRENTS | FILE SHARING): a PageTab without the count."""
    show_count = False
    text_lift = 0        # centred on the title bar, level with CONNECTED and the buttons


class NetToggle(QWidget):
    """Two-way pill, LAN | INTERNET: which address the QR code carries. Click a side (or anywhere) to switch."""
    changed = Signal(str)
    OPTIONS = (("lan", "LAN", "green"), ("internet", "INTERNET", "magenta"))

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.current = current
        self.font_ = T.head_font(7.8, QFont.Weight.Bold, 1.0)
        fm = QFontMetricsF(self.font_)
        self.widths = [fm.horizontalAdvance(label) + 12 for _k, label, _c in self.OPTIONS]
        self.setFixedSize(int(sum(self.widths)) + 4, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("LAN: phones on this Wi-Fi only, nothing goes through the internet.\n"
                        "INTERNET: phones anywhere, through an encrypted Cloudflare tunnel; the QR code "
                        "appears once the tunnel is up.")

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        key = self.OPTIONS[0][0] if event.position().x() < 2 + self.widths[0] else self.OPTIONS[1][0]
        if key != self.current:
            self.current = key
            self.update()
            self.changed.emit(key)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(T.c("line"), 1.2))
        p.setBrush(T.c("panel", 170))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setFont(self.font_)
        x = 2.0
        for (key, label, color), width in zip(self.OPTIONS, self.widths):
            seg = QRectF(x, 3, width, self.height() - 6)
            on = key == self.current
            if on:
                p.setPen(QPen(T.c(color, 200), 1.2))
                p.setBrush(T.c(color, 70))
                p.drawRoundedRect(seg, seg.height() / 2, seg.height() / 2)
            p.setPen(QColor("white") if on else T.c("muted"))
            p.drawText(seg, Qt.AlignmentFlag.AlignCenter, label)
            x += width


class QrView(QWidget):
    clicked = Signal()                                   # a code is shown and was clicked: open the zoom

    def __init__(self, size: int = 225, zoomable: bool = True, parent=None):
        super().__init__(parent)
        self.rows: list[list[int]] = []
        self.message = ""
        self.zoomable = zoomable
        self.mirror: QrView | None = None                # the open zoom window shows the same code
        self.setFixedSize(size, size)

    def set_url(self, url: str) -> None:
        self.rows = [list(row) for row in segno.make(url, error="m").matrix_iter(scale=1, border=3)] if url else []
        self._changed()

    def set_message(self, text: str) -> None:
        self.message = text
        self.rows = []
        self._changed()

    def _changed(self) -> None:
        if self.zoomable:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.rows else Qt.CursorShape.ArrowCursor)
            self.setToolTip("Click to zoom" if self.rows else "")
        if self.mirror is not None:
            self.mirror.rows, self.mirror.message = self.rows, self.message
            self.mirror.update()
        self.update()

    def mousePressEvent(self, event):
        if self.zoomable and self.rows and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if not self.rows:
            p.setPen(QPen(T.c("line"), 1.4, Qt.PenStyle.DashLine))
            p.setBrush(T.c("panel_hi", 140))
            p.drawRoundedRect(r, 14, 14)
            p.setPen(T.c("muted"))
            p.setFont(T.font(9.5))
            p.drawText(r.adjusted(18, 18, -18, -18), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.message)
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))                    # dark modules on white: every phone camera reads it
        p.drawRoundedRect(r, 14, 14)
        n = len(self.rows)
        cell = r.width() / n
        p.setBrush(QColor("#0b1020"))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for y, row in enumerate(self.rows):
            for x, on in enumerate(row):
                if on:
                    p.drawRect(QRectF(r.left() + x * cell, r.top() + y * cell, cell + 0.4, cell + 0.4))


class Bar(QWidget):
    """Thin neon progress bar."""

    def __init__(self, height: int = 8, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.setFixedHeight(height)

    def set_value(self, value: float) -> None:
        value = max(0.0, min(1.0, value))
        if abs(value - self.value) > 0.001:
            self.value = value
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        radius = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.c("track"))
        p.drawRoundedRect(r, radius, radius)
        if self.value > 0:
            fill = QRectF(r.left(), r.top(), max(r.height(), r.width() * self.value), r.height())
            g = QLinearGradient(fill.topLeft(), fill.topRight())
            g.setColorAt(0, T.c("cyan"))
            g.setColorAt(1, T.c("magenta"))
            p.setBrush(g)
            p.drawRoundedRect(fill, radius, radius)


class _CloseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._hover = False

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.c("red", 230) if self._hover else QColor(6, 11, 22, 210))
        p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.setPen(QPen(T.c("text"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c, d = self.width() / 2, 4.2
        p.drawLine(QPointF(c - d, c - d), QPointF(c + d, c + d))
        p.drawLine(QPointF(c + d, c - d), QPointF(c - d, c + d))


class FileTile(QWidget):
    """Thumbnail tile with an X at the top right, a progress bar while moving and a ✓ when done."""
    closed = Signal(str)
    opened = Signal(str)

    def __init__(self, key: str, name: str, size: int, parent=None):
        super().__init__(parent)
        self.key, self.name, self.size = key, name, size
        self.kind, self.color = kind_of(name)
        self.pixmap: QPixmap | None = None
        self.state = "ready"                              # ready / active / done / cancelled / failed
        self.done = 0
        self.note = ""
        self.setFixedSize(TILE_W, TILE_H)
        self.setToolTip(name)
        self.close_btn = _CloseButton(self)
        self.close_btn.move(TILE_W - 8 - 24 - 4, 12)
        self.close_btn.clicked.connect(lambda: self.closed.emit(self.key))

    def set_image(self, image: QImage) -> None:
        self.pixmap = QPixmap.fromImage(image)
        self.update()

    def set_progress(self, state: str, done: int, note: str = "") -> None:
        if (state, done, note) != (self.state, self.done, self.note):
            self.state, self.done, self.note = state, done, note
            self.close_btn.setToolTip("Cancel" if state == "active" else "Remove from the list")
            self.update()

    def mouseDoubleClickEvent(self, event):
        self.opened.emit(self.key)
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        outer = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        border = {"active": T.c("cyan"), "done": T.c("green", 170), "failed": T.c("red", 170),
                  "cancelled": T.c("line")}.get(self.state, T.c("line"))
        p.setPen(QPen(border, 2.0 if self.state == "active" else 1.2))
        p.setBrush(T.c("panel", 235))
        p.drawRoundedRect(outer, 14, 14)
        thumb = QRectF(8, 8, THUMB, THUMB)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 10, 10)
        p.save()
        p.setClipPath(clip)
        if self.pixmap is not None:
            p.drawPixmap(thumb.toRect(), self.pixmap)
            if self.kind == "video":
                c = thumb.center()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(T.c("cyan", 225))
                p.drawEllipse(c, 15, 15)
                tri = QPainterPath()
                tri.moveTo(c.x() - 4.5, c.y() - 7)
                tri.lineTo(c.x() + 7.5, c.y())
                tri.lineTo(c.x() - 4.5, c.y() + 7)
                tri.closeSubpath()
                p.fillPath(tri, T.c("bg0"))
        else:
            g = QLinearGradient(thumb.topLeft(), thumb.bottomRight())
            g.setColorAt(0, T.c("panel_hi"))
            g.setColorAt(1, T.c(self.color, 40))
            p.fillRect(thumb, g)
            box = QRectF(thumb.center().x() - 24, thumb.top() + 30, 48, 48)
            p.setPen(QPen(T.c(self.color, 160), 1.3))
            p.setBrush(T.c(self.color, 30))
            p.drawRoundedRect(box, 10, 10)
            paint_icon(p, {"image": "file", "video": "play", "audio": "file", "archive": "database",
                           "document": "file", "app": "gear"}.get(self.kind, "file"),
                       box.adjusted(11, 11, -11, -11), T.c(self.color), 1.8)
            p.setPen(T.c(self.color))
            p.setFont(T.head_font(10, QFont.Weight.Bold, 1.5))
            ext = Path(self.name).suffix.lstrip(".").upper()[:6] or "FILE"
            p.drawText(QRectF(thumb.left(), box.bottom() + 8, thumb.width(), 20), Qt.AlignmentFlag.AlignCenter, ext)
        if self.state in ("done", "cancelled", "failed"):
            p.fillRect(thumb, QColor(6, 11, 22, 120))
        if self.state == "active" and self.size:
            track = QRectF(thumb.left(), thumb.bottom() - 6, thumb.width(), 6)
            p.fillRect(track, QColor(6, 11, 22, 200))
            g = QLinearGradient(track.topLeft(), track.topRight())
            g.setColorAt(0, T.c("cyan"))
            g.setColorAt(1, T.c("magenta"))
            p.fillRect(QRectF(track.left(), track.top(), track.width() * min(1.0, self.done / self.size), 6), g)
        p.restore()
        if self.state == "done":
            c = thumb.center()
            p.setPen(QPen(T.c("green"), 2))
            p.setBrush(T.c("green", 50))
            p.drawEllipse(c, 18, 18)
            p.setPen(QPen(T.c("green"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            check = QPainterPath()
            check.moveTo(c.x() - 8, c.y())
            check.lineTo(c.x() - 2, c.y() + 6)
            check.lineTo(c.x() + 9, c.y() - 6)
            p.drawPath(check)
        elif self.state == "active" and self.size:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(6, 11, 22, 215))
            label = QRectF(thumb.center().x() - 26, thumb.center().y() - 12, 52, 24)
            p.drawRoundedRect(label, 6, 6)
            p.setPen(T.c("cyan"))
            p.setFont(T.head_font(10.5, QFont.Weight.Bold, 0.5))
            p.drawText(label, Qt.AlignmentFlag.AlignCenter, f"{int(100 * self.done / self.size)}%")
        p.setFont(T.font(9, QFont.Weight.DemiBold))
        p.setPen(T.c("text"))
        text_rect = QRectF(10, thumb.bottom() + 6, TILE_W - 20, 18)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetricsF(p.font()).elidedText(self.name, Qt.TextElideMode.ElideMiddle, text_rect.width()))
        p.setFont(T.font(8))
        status_color = {"active": "cyan", "done": "green", "failed": "red", "cancelled": "orange"}.get(self.state, "muted")
        p.setPen(T.c(status_color))
        line = self.note or T.fmt_bytes(self.size)
        p.drawText(QRectF(10, thumb.bottom() + 24, TILE_W - 20, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetricsF(p.font()).elidedText(line, Qt.TextElideMode.ElideRight, TILE_W - 20))


class TileGrid(QScrollArea):
    """Scrollable grid that re-flows its tiles to the width; optionally accepts dropped files."""
    files_dropped = Signal(list)

    def __init__(self, empty_text: str, accept_drops: bool = False, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.inner = QWidget()
        self.grid = QGridLayout(self.inner)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setWidget(self.inner)
        self.tiles: dict[str, FileTile] = {}
        self.columns = 0
        self.empty = QLabel(empty_text, self.viewport())
        self.empty.setObjectName("muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.setAcceptDrops(accept_drops)

    def add(self, tile: FileTile) -> None:
        self.tiles[tile.key] = tile
        self._reflow(force=True)

    def remove(self, key: str) -> None:
        tile = self.tiles.pop(key, None)
        if tile is not None:
            self.grid.removeWidget(tile)
            tile.deleteLater()
            self._reflow(force=True)

    def _reflow(self, force: bool = False) -> None:
        columns = max(1, (self.viewport().width() - 8) // (TILE_W + 12))
        if columns != self.columns or force:
            self.columns = columns
            for tile in self.tiles.values():
                self.grid.removeWidget(tile)
            for index, tile in enumerate(self.tiles.values()):
                self.grid.addWidget(tile, index // columns, index % columns)
        self.empty.setVisible(not self.tiles)
        self.empty.setGeometry(self.viewport().rect().adjusted(30, 30, -30, -30))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()


class ApproveDialog(NeonDialog):
    def __init__(self, phone: dict, parent=None):
        super().__init__("Allow this phone?", parent)
        self.sid = phone["sid"]
        self.setMinimumWidth(500)
        mac = phone["mac"] or "unknown"
        if phone["mac"] and S.mac_is_private(phone["mac"]):
            mac += " (private, randomized by the phone)"
        text = QLabel(f"Allow “{phone['name']}” to share files with this PC?\n\n"
                      f"Model: {phone['model'] or 'not reported'}\nIP: {phone['ip']}\nMAC: {mac}\n"
                      f"Path: {'INTERNET (Cloudflare tunnel)' if phone.get('path') == 'internet' else 'LAN (this Wi-Fi)'}"
                      "\n\n"
                      "Accept only if this is your phone. It stays trusted until you disconnect it.")
        text.setTextFormat(Qt.TextFormat.PlainText)          # the name and model come from the phone
        text.setWordWrap(True)
        text.setFont(T.font(10.5))
        self.root.addWidget(text)
        row = QHBoxLayout()
        row.addStretch(1)
        deny = GlowButton("DENY", "close", "red", "outline")
        deny.clicked.connect(self.reject)
        allow = GlowButton("ALLOW", "check", "green", "solid")
        allow.clicked.connect(self.accept)
        for b in (deny, allow):
            b.setMinimumWidth(130)
            b.setFixedHeight(44)
            row.addWidget(b)
        self.root.addLayout(row)


class QrZoomDialog(NeonDialog):
    """The pairing code at 500 x 500 with its hint, for phones that struggle with the small one. Follows changes."""

    def __init__(self, source: QrView, hint: str, parent=None):
        super().__init__("QR code", parent)            # its title bar has the X at the top right
        # a popup: any click outside it closes it
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.source = source
        self.view = QrView(500, zoomable=False)
        self.view.rows, self.view.message = source.rows, source.message
        source.mirror = self.view
        self.root.addWidget(self.view, 0, Qt.AlignmentFlag.AlignHCenter)
        self.hint = QLabel(hint)
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setFixedWidth(500)
        self.root.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        row.addStretch(1)
        close = GlowButton("CLOSE", "check", "cyan", "solid", "cyan2")
        close.setMinimumWidth(130)
        close.setFixedHeight(44)
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self.root.addLayout(row)
        self.finished.connect(self._detach)

    def _detach(self, _result: int) -> None:
        if self.source.mirror is self.view:
            self.source.mirror = None


class _TextBody(QTextEdit):
    """A message's text: plain text only (nothing in it is a link or markup), selectable with the mouse and
    keyboard, wrapped anywhere so a long URL cannot widen the panel, and as tall as its text up to MAX_HEIGHT."""
    MAX_HEIGHT = 300

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setAcceptRichText(False)
        self.setPlainText(text)
        self.setFont(T.font(10.5))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                     | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self.setStyleSheet("QTextEdit { background: transparent; }")
        self.document().setDocumentMargin(2)
        self.document().documentLayout().documentSizeChanged.connect(self._fit)

    def _fit(self, *_args) -> None:
        height = int(self.document().size().height()) + 6
        self.setFixedHeight(min(height, self.MAX_HEIGHT))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if height > self.MAX_HEIGHT
                                        else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class TextBubble(QFrame):
    """One text message from the phone: who and when, a one-click COPY at the top right, then the text."""

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.text = entry["text"]
        self.setObjectName("textBubble")
        self.setStyleSheet(f"QFrame#textBubble {{ background: {T.hexc('panel_hi')}; "
                           f"border: 1px solid {T.hexc('line')}; border-radius: 10px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        stamp = time.strftime("%d %b, %H:%M", time.localtime(entry["at"]))
        meta = QLabel(f"{entry.get('name') or 'Phone'}  ·  {stamp}  ·  {len(self.text):,} characters")
        meta.setObjectName("muted")
        meta.setTextFormat(Qt.TextFormat.PlainText)                  # the name comes from the phone
        head.addWidget(meta, 1, Qt.AlignmentFlag.AlignVCenter)
        self.copy_btn = GlowButton("COPY", "copy", "cyan", "outline")
        self.copy_btn.setFixedSize(96, 30)
        self.copy_btn.icon_size = 13
        self.copy_btn.setFont(T.head_font(8.4, QFont.Weight.DemiBold, 1.2))
        self.copy_btn.setToolTip("Copy the whole message to the clipboard")
        self.copy_btn.clicked.connect(self.copy)
        head.addWidget(self.copy_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        lay.addWidget(_TextBody(self.text))

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text)
        self.copy_btn.setText("COPIED")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText("COPY"))


class TextInbox(NeonDialog):
    """The pop-out chat panel with the text the phone sent, newest at the bottom. Stays open beside the window."""
    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__("Text from phone", parent, resizable=True)
        self.setModal(False)
        self.setMinimumSize(440, 340)
        self.resize(540, 580)
        note = QLabel("Text sent from the phone’s TEXT tab. COPY takes a whole message; drag over the text to copy "
                      "a part of it (Ctrl+C).")
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 6, 0)
        self.list.setSpacing(10)
        self.empty = QLabel("Nothing yet. On the phone, open the TEXT tab, paste and press SEND TEXT.")
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list.addStretch(1)                                   # messages sit at the bottom, like a chat
        self.list.addWidget(self.empty)
        self.scroll.setWidget(holder)
        self.root.addWidget(self.scroll, 1)
        row = QHBoxLayout()
        clear = GlowButton("CLEAR", "trash", "purple", "outline")
        clear.setFixedSize(110, 40)
        clear.setToolTip("Remove every message from this panel")
        clear.clicked.connect(self.clear)
        row.addWidget(clear)
        row.addStretch(1)
        close = GlowButton("CLOSE", "check", "cyan", "solid", "cyan2")
        close.setFixedSize(120, 40)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        self.root.addLayout(row)

    def add(self, entry: dict) -> None:
        self.empty.hide()
        self.list.addWidget(TextBubble(entry))
        bar = self.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def clear(self) -> None:
        while self.list.count() > 2:                              # keep the stretch and the empty note
            item = self.list.takeAt(2)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.empty.show()
        self.cleared.emit()


class _Relay(QObject):
    pc_info = Signal(dict)


# ------------------------------------------------------------------ the tab
class ShareTab(QWidget):
    """FILE SHARING page. ``download_dir`` returns the torrent download folder; files land in its FTP subfolder."""

    def __init__(self, download_dir: Callable[[], str], register: Callable[[NeonPanel], None],
                 attention: Callable[[str], None], notify: Callable[[str], None] | None = None, parent=None):
        super().__init__(parent)
        self.download_dir = download_dir
        self.attention = attention
        self.notify = notify or (lambda _text: None)      # a tray message that does not raise the window
        self.texts: list[dict] = []                      # text from the phone, kept until CLEAR or quit
        self.unread_texts = 0
        self.text_inbox: TextInbox | None = None
        self.server: S.ShareServer | None = None
        self.tunnel: S.Tunnel | None = None
        self.pairing_rev = -1
        self.mode = "send"
        self.net_mode = "lan" if T.load_preferences().get("share_net") == "lan" else "internet"
        self.sends: dict[str, dict] = {}                 # tile key -> {"path", "offer"}
        self.received: dict[str, Path] = {}              # tile key -> saved path
        self.prompts: dict[str, ApproveDialog] = {}
        self.prompted: set[str] = set()
        self.speed_samples: list[tuple[float, int]] = []
        self.pc_info: dict = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.thumbs = _ThumbSignals()
        self.thumbs.done.connect(self._on_thumb)
        self.relay = _Relay()
        self.relay.pc_info.connect(self._on_pc_info)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._poll)
        self._build(register)

    # ---------------------------------------------------------- layout
    def _build(self, register: Callable[[NeonPanel], None]) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(16)
        qr_panel = NeonPanel("magenta", 0.7)
        register(qr_panel)
        qr_panel.setFixedWidth(384)
        ql = QVBoxLayout(qr_panel)
        ql.setContentsMargins(22, 16, 22, 18)
        ql.setSpacing(8)
        self.mode_tabs = FilterBar([("send", "TO PHONE", "cyan"), ("recv", "FROM PHONE", "magenta")],
                                   chip_class=TopTab, spacing=4)
        self.mode_tabs.changed.connect(self._on_mode)
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(2)
        tabs_row.addWidget(self.mode_tabs, 1)
        self.net_toggle = NetToggle(self.net_mode)
        self.net_toggle.changed.connect(self._on_net)
        tabs_row.addWidget(self.net_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        ql.addLayout(tabs_row)
        status = QHBoxLayout()
        status.setSpacing(6)
        self.status_dot = StatusDot(10)
        self.status_label = QLabel()
        self.status_label.setFont(T.head_font(10, QFont.Weight.DemiBold, 1.4))
        status.addWidget(self.status_dot)
        status.addWidget(self.status_label)
        status.addStretch(1)
        self.path_badge = QLabel("LAN")                  # which way the phone connects: LAN or INTERNET (tunnel)
        self.path_badge.setFont(T.head_font(8.6, QFont.Weight.Bold, 1.4))
        status.addWidget(self.path_badge)
        ql.addLayout(status)
        self.qr = QrView()
        self.qr.clicked.connect(self._zoom_qr)
        self.zoom: QrZoomDialog | None = None
        self.connected: set[str] = set()                 # phones pending or online at the last poll
        self.zoom_known: set[str] = set()                # ...when the zoom opened; a new one closes it
        ql.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignHCenter)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        ql.addWidget(self.hint)                          # _on_mode fixes its height to the wrapped text
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.new_qr_btn = GlowButton("NEW QR", "refresh", "cyan", "outline")
        self.new_qr_btn.setToolTip("Make a new code; the old one stops working")
        self.new_qr_btn.clicked.connect(self._new_qr)
        self.disconnect_btn = GlowButton("DISCONNECT", "close", "orange", "outline")
        self.disconnect_btn.setToolTip("Forget the phone; it has to scan and be allowed again")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.power_btn = GlowButton("STOP", "power", "red", "outline")
        self.power_btn.setToolTip("Stop sharing: the server closes and nothing on this PC listens any more")
        self.power_btn.clicked.connect(self._toggle_session)
        for b, w in ((self.new_qr_btn, 104), (self.disconnect_btn, 128), (self.power_btn, 84)):
            b.setFixedSize(w, 40)
            b.icon_size = 15
            b.setFont(T.head_font(8.6, QFont.Weight.DemiBold, 1.2))
            buttons.addWidget(b)
        ql.addLayout(buttons)
        left.addWidget(qr_panel)

        net = NeonPanel("cyan", 0.5)
        register(net)
        net.setFixedWidth(384)
        nl = QGridLayout(net)
        nl.setContentsMargins(22, 10, 22, 12)             # compact: the QR panel above needs the height
        nl.setHorizontalSpacing(12)
        nl.setVerticalSpacing(3)
        self.net_values: dict[str, QLabel] = {}
        row = 0
        for header, fields in (("THIS PC", (("pc_ip", "IP"), ("pc_mac", "MAC"), ("pc_wifi", "Wi-Fi"))),
                               ("PHONE", (("ph_name", "Name"), ("ph_model", "Model"), ("ph_ip", "IP"),
                                          ("ph_mac", "MAC")))):
            title = QLabel(header)
            title.setFont(T.head_font(9.5, QFont.Weight.DemiBold, 1.8))
            title.setStyleSheet(f"color: {T.hexc('cyan')};")
            nl.addWidget(title, row, 0, 1, 2)
            row += 1
            for key, label in fields:
                name = QLabel(label)
                name.setObjectName("formLabel")
                value = QLabel("—")
                value.setFont(T.font(9.5))
                value.setWordWrap(True)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                value.setTextFormat(Qt.TextFormat.PlainText)
                nl.addWidget(name, row, 0, Qt.AlignmentFlag.AlignTop)
                nl.addWidget(value, row, 1)
                self.net_values[key] = value
                row += 1
            row += 1
        nl.setColumnStretch(1, 1)
        left.addWidget(net)
        left.addStretch(1)
        root.addLayout(left)

        files = NeonPanel("cyan", 0.55)
        register(files)
        fl = QVBoxLayout(files)
        fl.setContentsMargins(20, 14, 16, 12)
        fl.setSpacing(10)
        head = QHBoxLayout()
        self.files_title = SectionTitle("upload", "FILES TO SEND", "")
        head.addWidget(self.files_title, 1)
        # text from the phone, with the unread count; the chat panel pops out when it is clicked. It lives here, not
        # under the network panel: the left column has no height to spare once a phone is connected
        self.text_btn = GlowButton("TEXT FROM PHONE", "copy", "magenta", "outline")
        self.text_btn.setFixedSize(250, 42)
        self.text_btn.setToolTip("Open the text the phone sent from its TEXT tab")
        self.text_btn.clicked.connect(self.show_texts)
        head.addWidget(self.text_btn)
        self.add_btn = GlowButton("ADD FILES", "file_plus", "cyan", "solid", "cyan2")
        self.add_btn.clicked.connect(self._pick_files)
        self.clear_btn = GlowButton("CLEAR", "trash", "purple", "outline")
        self.clear_btn.clicked.connect(self._clear)
        self.folder_btn = GlowButton("OPEN FOLDER", "folder", "magenta", "outline")
        self.folder_btn.clicked.connect(self._open_folder)
        for b, w in ((self.add_btn, 138), (self.folder_btn, 150), (self.clear_btn, 108)):
            b.setFixedSize(w, 42)
            head.addWidget(b)
        fl.addLayout(head)
        overall = QHBoxLayout()
        overall.setSpacing(12)
        self.overall_label = QLabel()
        self.overall_label.setFont(T.head_font(10, QFont.Weight.DemiBold, 1.0))
        self.overall_bar = Bar(8)
        self.speed_label = QLabel()
        self.speed_label.setObjectName("muted")
        self.speed_label.setMinimumWidth(170)
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        overall.addWidget(self.overall_label)
        overall.addWidget(self.overall_bar, 1)
        overall.addWidget(self.speed_label)
        fl.addLayout(overall)
        self.grids = QStackedWidget()
        self.send_grid = TileGrid("Add files (or drop them here). They appear on the phone under “Get from PC”; "
                                  "it picks what to save.", accept_drops=True)
        self.send_grid.files_dropped.connect(self.add_paths)
        self.recv_grid = TileGrid("Files the phone sends land here, saved in the FTP folder of your download "
                                  "folder.")
        self.grids.addWidget(self.send_grid)
        self.grids.addWidget(self.recv_grid)
        fl.addWidget(self.grids, 1)
        root.addWidget(files, 1)
        self._on_mode("send")
        self._set_status("stopped")
        self.qr.set_message("Sharing is off.\nPress START to show the QR code.")

    # ---------------------------------------------------------- text from the phone
    MAX_TEXTS = 500

    def _add_text(self, entry: dict) -> None:
        self.texts.append(entry)
        del self.texts[:-self.MAX_TEXTS]
        inbox = self.text_inbox
        if inbox is not None and inbox.isVisible():
            inbox.add(entry)
        else:
            if inbox is not None:
                inbox.add(entry)
            self.unread_texts += 1
            self.notify(f"Text from {entry.get('name') or 'the phone'}: open FILE TRANSFER → TEXT FROM PHONE")
        self._show_text_count()

    def _show_text_count(self) -> None:
        if self.unread_texts:
            label = f"TEXT FROM PHONE  ·  {self.unread_texts} NEW"
        elif self.texts:
            label = f"TEXT FROM PHONE  ·  {len(self.texts)}"
        else:
            label = "TEXT FROM PHONE"
        self.text_btn.setText(label)

    def show_texts(self) -> None:
        if self.text_inbox is None:
            self.text_inbox = TextInbox(self.window())
            self.text_inbox.cleared.connect(self._clear_texts)
            for entry in self.texts:
                self.text_inbox.add(entry)
        self.unread_texts = 0
        self._show_text_count()
        self.text_inbox.show()
        self.text_inbox.raise_()
        self.text_inbox.activateWindow()

    def _clear_texts(self) -> None:
        self.texts.clear()
        self.unread_texts = 0
        self._show_text_count()

    # ---------------------------------------------------------- session lifecycle
    def activate(self) -> None:
        """Called when the tab is shown: open a sharing session if none is running."""
        if self.server is None:
            self.start_session()

    def save_dir(self) -> Path:
        return Path(self.download_dir()) / "FTP"

    def start_session(self) -> None:
        ip = S.lan_ipv4()
        if ip is None:
            self._set_status("offline")
            self.qr.set_message("No Wi-Fi or LAN connection found.\nConnect this PC to your home network, "
                                "then press START.")
            self.power_btn.setText("START")
            return
        try:
            self.server = S.ShareServer(ip, self.save_dir())
        except OSError as error:
            self._set_status("offline")
            self.qr.set_message(f"Could not open the sharing server:\n{error.strerror or error}")
            return
        self.server.start()
        self._start_tunnel()
        for key, item in self.sends.items():                   # files picked before a restart stay offered
            offer = self.server.add_offer(item["path"])
            item["offer"] = offer.id if offer else ""
            if offer and item.get("jpeg"):
                self.server.set_offer_thumb(offer.id, item["jpeg"])
        self.pairing_rev = -1
        self.power_btn.setText("STOP")
        self.speed_samples.clear()
        self._fill_pc({"ip": ip})
        threading.Thread(target=lambda: self.relay.pc_info.emit(S.pc_network(ip)), daemon=True,
                         name="neon-share-netinfo").start()
        self.timer.start()
        self._poll()

    def stop_session(self) -> None:
        self.timer.stop()
        for dialog in list(self.prompts.values()):
            dialog.close()
        self.prompts.clear()
        self._stop_tunnel()
        if self.server is not None:
            server, self.server = self.server, None
            server.stop()
        for tile in self.send_grid.tiles.values():
            if tile.state == "active":
                tile.set_progress("ready", 0, "")
        for tile in self.recv_grid.tiles.values():
            if tile.state == "active":
                tile.set_progress("cancelled", tile.done, "Cancelled: sharing stopped")
        self.power_btn.setText("START")
        self._set_status("stopped")
        self.qr.set_message("Sharing is off.\nPress START to show the QR code.")
        self._fill_phone(None)
        self.speed_label.setText("")

    def shutdown(self) -> None:
        self.stop_session()
        if self.text_inbox is not None:
            self.text_inbox.close()
        self.pool.clear()

    def _toggle_session(self) -> None:
        if self.server is None:
            self.start_session()
        else:
            self.stop_session()

    def _new_qr(self) -> None:
        if self.server is not None:
            self.server.rotate()
            if self.net_mode == "internet" and (self.tunnel is None or self.tunnel.error):
                self._stop_tunnel()                      # the internet link failed: NEW QR tries again
                self._start_tunnel()
            self._poll()

    def _on_net(self, mode: str) -> None:
        """LAN | INTERNET toggle: which address the QR code carries. Remembered for the next session."""
        self.net_mode = mode
        self.net_toggle.current = mode
        self.net_toggle.update()
        prefs = T.load_preferences()
        prefs["share_net"] = mode
        T.save_preferences(prefs)
        if self.server is not None:
            self._stop_tunnel()
            self._start_tunnel()                         # starts only in INTERNET mode
            self.pairing_rev = -1
            self._poll()

    def _disconnect(self) -> None:
        if self.server is not None:
            self.server.disconnect()
            self._stop_tunnel()                          # a fresh tunnel URL: the old link is dead too
            self._start_tunnel()
            self._poll()

    def _start_tunnel(self) -> None:
        """Internet mode: a Cloudflare quick tunnel to the LAN server. The QR switches to it once it is up."""
        server = self.server
        if server is None or self.net_mode != "internet":
            return                                       # LAN mode: nothing is exposed to the internet
        server.lan_hop = False                           # chosen by hand: phones stay on the internet path
        self.tunnel = S.Tunnel(server.lan_url().rstrip("/"), T.app_data_dir() / "cloudflared", server.set_tunnel)
        self.tunnel.start()
        self.pairing_rev = -1                            # show "connecting the internet link" at once

    def _stop_tunnel(self) -> None:
        tunnel, self.tunnel = self.tunnel, None
        if tunnel is not None:
            tunnel.stop()
        if self.server is not None:
            self.server.set_tunnel("")

    def _zoom_qr(self) -> None:
        if self.zoom is None:
            self.zoom_known = set(self.connected)
            self.zoom = QrZoomDialog(self.qr, self.hint.text(), self)
            self.zoom.finished.connect(lambda _r: setattr(self, "zoom", None))
            self.zoom.adjustSize()
            self.zoom.move(self.window().frameGeometry().center() - self.zoom.rect().center())
            self.zoom.show()                             # not modal: the code keeps updating behind it
        self.zoom.raise_()
        self.zoom.activateWindow()

    # ---------------------------------------------------------- mode
    def _on_mode(self, mode: str) -> None:
        self.mode = mode
        send = mode == "send"
        self.grids.setCurrentWidget(self.send_grid if send else self.recv_grid)
        self.files_title.icon_name = "upload" if send else "download"
        self.files_title.set_text("FILES TO SEND" if send else "RECEIVED FILES")
        self.add_btn.setVisible(send)
        self.folder_btn.setVisible(not send)
        self.clear_btn.setToolTip("Remove every file from the list (nothing is deleted from disk)")
        self.hint.setText("Scan with the phone camera. On the phone, choose “Get from PC” to save these files."
                          if send else "Scan with the phone camera, choose files on the phone and tap Send. "
                          f"They are saved in {self.save_dir()}.")
        self.hint.ensurePolished()                              # the #muted font size, before measuring
        self.hint.setFixedHeight(self.hint.heightForWidth(340))  # panel 384 - margins 44: the layout cannot squeeze it
        if self.zoom is not None:
            self.zoom.hint.setText(self.hint.text())
        self.pairing_rev = -1                                   # QR carries the mode: redraw it
        if self.server is not None:
            self._poll()
        else:
            self._update_overall([])

    # ---------------------------------------------------------- files to send
    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Files to send to the phone", str(Path.home()))
        self.add_paths(paths)

    def add_paths(self, paths: list[str]) -> None:
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or any(item["path"] == path for item in self.sends.values()):
                continue
            key = f"s{uuid.uuid4().hex[:10]}"
            offer = self.server.add_offer(path) if self.server is not None else None
            try:
                size = path.stat().st_size
            except OSError:
                continue
            self.sends[key] = {"path": path, "offer": offer.id if offer else "", "jpeg": b""}
            tile = FileTile(key, path.name, size)
            tile.set_progress("ready", 0, f"{T.fmt_bytes(size)} · waiting for the phone")
            tile.closed.connect(self._close_send)
            tile.opened.connect(lambda k: self._reveal(self.sends.get(k, {}).get("path")))
            self.send_grid.add(tile)
            self.pool.start(_ThumbJob(key, str(path), self.thumbs))
        if paths and self.mode != "send":
            self.mode_tabs.select("send")
        self._poll()

    def _close_send(self, key: str) -> None:
        item = self.sends.get(key)
        tile = self.send_grid.tiles.get(key)
        if item is None or tile is None:
            return
        if tile.state == "active" and self.server is not None:      # X during a transfer cancels it
            for t in self.server.snapshot()["transfers"]:
                if t["offer_id"] == item["offer"] and t["state"] == "active":
                    self.server.cancel(t["number"])
            tile.set_progress("ready", 0, "Cancelled · still offered")
            return
        if self.server is not None and item["offer"]:
            self.server.remove_offer(item["offer"])
        del self.sends[key]
        self.send_grid.remove(key)
        self._poll()

    def _close_received(self, key: str) -> None:
        tile = self.recv_grid.tiles.get(key)
        if tile is None:
            return
        number = int(key[1:])
        if tile.state == "active" and self.server is not None:
            self.server.cancel(number)
            return
        if self.server is not None:
            self.server.forget(number)
        self.received.pop(key, None)
        self.recv_grid.remove(key)
        self._poll()

    def _clear(self) -> None:
        grid = self.send_grid if self.mode == "send" else self.recv_grid
        for key in list(grid.tiles):
            if grid.tiles[key].state != "active":
                (self._close_send if self.mode == "send" else self._close_received)(key)

    def _open_folder(self) -> None:
        folder = self.save_dir()
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(folder)])

    def _reveal(self, path: Path | None) -> None:
        if path is not None and path.exists():
            subprocess.Popen(["explorer.exe", "/select,", str(path)])          # selects, never opens the file

    def _on_thumb(self, key: str, image: QImage, jpeg: QByteArray) -> None:
        tile = self.send_grid.tiles.get(key) or self.recv_grid.tiles.get(key)
        if tile is not None:
            tile.set_image(image)
        item = self.sends.get(key)
        if item is not None:
            item["jpeg"] = bytes(jpeg)
            if self.server is not None and item["offer"]:
                self.server.set_offer_thumb(item["offer"], item["jpeg"])

    # ---------------------------------------------------------- polling
    def _poll(self) -> None:
        server = self.server
        if server is None:
            return
        snap = server.snapshot()
        for entry in server.take_texts():
            self._add_text(entry)
        tunnel = self.tunnel
        if self.net_mode == "internet" and not snap["tunnel"]:
            # INTERNET: the code appears only once the tunnel is up; a LAN code would strand a phone elsewhere
            error = tunnel.error if tunnel is not None else "the tunnel is not running"
            message = (f"The internet link failed: {error}.\nPress NEW QR to try again, or switch to LAN."
                       if error else "Connecting the internet link…\nThe QR code appears once the tunnel is up.")
            if self.pairing_rev != -2 or self.qr.message != message:
                self.pairing_rev = -2
                self.qr.set_message(message)
        elif snap["pairing_rev"] != self.pairing_rev:
            self.pairing_rev = snap["pairing_rev"]
            self.qr.set_url(server.url(self.mode))
        phones = snap["phones"]
        allowed = next((p for p in phones if p["state"] == "allowed"), None)
        pending = [p for p in phones if p["state"] == "pending"]
        active = [t for t in snap["transfers"] if t["state"] == "active"]
        self.connected = {p["sid"] for p in phones if p["state"] == "pending" or p.get("alive")}
        if self.zoom is not None and self.connected - self.zoom_known:
            self.zoom.close()                            # a phone just connected: the big code has done its job
        if allowed is not None:
            self._set_status("transferring" if active and allowed["alive"] else
                             "connected" if allowed["alive"] else "lost")
        elif pending:
            self._set_status("waiting")
        else:
            self._set_status("ready")
        self._fill_phone(allowed or (pending[0] if pending else None))
        self._set_path(allowed or (pending[0] if pending else None), snap["tunnel"])
        self.disconnect_btn.setEnabled(bool(phones))
        for phone in pending:
            if phone["sid"] not in self.prompted:
                self.prompted.add(phone["sid"])
                self._ask(phone)
        live = {p["sid"] for p in pending}
        for sid, dialog in list(self.prompts.items()):
            if sid not in live:
                dialog.close()
                self.prompts.pop(sid, None)
        self._sync_tiles(snap["transfers"])
        self._update_speed(active)

    def _ask(self, phone: dict) -> None:
        dialog = ApproveDialog(phone, self.window())
        self.prompts[phone["sid"]] = dialog

        def done(result: int, sid=phone["sid"]):
            self.prompts.pop(sid, None)
            if self.server is not None:
                self.server.decide(sid, result == NeonDialog.DialogCode.Accepted)
                self._poll()
        dialog.finished.connect(done)
        self.attention(f"{phone['name']} wants to share files")
        dialog.open()

    def _sync_tiles(self, transfers: list[dict]) -> None:
        by_offer: dict[str, dict] = {}
        for t in transfers:
            if t["direction"] == "down":
                previous = by_offer.get(t["offer_id"])
                if previous is None or t["number"] > previous["number"]:
                    by_offer[t["offer_id"]] = t
                continue
            key = f"r{t['number']}"
            tile = self.recv_grid.tiles.get(key)
            if tile is None:
                if t["state"] != "active":
                    continue                                   # already removed from the list
                tile = FileTile(key, t["name"], t["size"])
                tile.closed.connect(self._close_received)
                tile.opened.connect(lambda k: self._reveal(self.received.get(k)))
                self.recv_grid.add(tile)
            if t["state"] == "done" and key not in self.received and t["path"]:
                self.received[key] = Path(t["path"])
                self.pool.start(_ThumbJob(key, t["path"], self.thumbs))
            note = {"active": f"Receiving · {T.fmt_bytes(t['done'])} of {T.fmt_bytes(t['size'])}",
                    "done": f"Saved · {Path(t['path']).name}" if t["path"] else "Saved",
                    "cancelled": "Cancelled", "failed": "Failed"}[t["state"]]
            tile.set_progress(t["state"], t["done"], note)
        for key, item in self.sends.items():
            tile = self.send_grid.tiles.get(key)
            t = by_offer.get(item["offer"])
            if tile is None:
                continue
            if t is None:
                if tile.state != "ready" or not tile.note:
                    tile.set_progress("ready", 0, f"{T.fmt_bytes(tile.size)} · waiting for the phone")
            elif t["state"] == "active":
                tile.set_progress("active", t["done"], f"Sending · {T.fmt_bytes(t['done'])} of {T.fmt_bytes(t['size'])}")
            elif t["state"] == "done":
                tile.set_progress("done", t["size"], "Sent to the phone")
            elif tile.state == "active":
                tile.set_progress("ready", 0, "Cancelled · still offered")
        self._update_overall(transfers)

    def _update_overall(self, transfers: list[dict]) -> None:
        grid = self.send_grid if self.mode == "send" else self.recv_grid
        tiles = list(grid.tiles.values())
        total = sum(t.size for t in tiles)
        moved = sum(t.size if t.state == "done" else t.done if t.state == "active" else 0 for t in tiles)
        done = sum(t.state == "done" for t in tiles)
        self.overall_label.setText(f"{done}/{len(tiles)}  ·  {T.fmt_bytes(moved)} of {T.fmt_bytes(total)}")
        self.overall_bar.set_value(moved / total if total else 0.0)

    def _update_speed(self, active: list[dict]) -> None:
        now = time.monotonic()
        moved = sum(t["done"] for t in active)
        if not active:
            self.speed_samples.clear()
            self.speed_label.setText("")
            return
        self.speed_samples.append((now, moved))
        while len(self.speed_samples) > 2 and now - self.speed_samples[0][0] > 4:
            self.speed_samples.pop(0)
        (t0, b0), (t1, b1) = self.speed_samples[0], self.speed_samples[-1]
        speed = (b1 - b0) / (t1 - t0) if t1 > t0 and b1 >= b0 else 0
        left = sum(t["size"] - t["done"] for t in active)
        self.speed_label.setText(f"{T.fmt_speed(speed)}  ·  {T.fmt_eta(left / speed) if speed else '—'}")

    # ---------------------------------------------------------- status and network panel
    def _set_status(self, key: str) -> None:
        text, level = STATUS[key]
        self.status_label.setText(text)
        self.status_dot.set_level(level)
        color = {"ok": "green", "warn": "yellow", "error": "red", "info": "cyan"}[level]
        self.status_label.setStyleSheet(f"color: {T.hexc(color)};")
        on = self.server is not None
        self.new_qr_btn.setEnabled(on)
        self.disconnect_btn.setEnabled(on and key in ("waiting", "connected", "transferring", "lost"))

    def _set_path(self, phone: dict | None, tunnel: str) -> None:
        internet = phone["path"] == "internet" if phone else self.net_mode == "internet"
        if phone:
            tip = ("The phone is connected through the internet tunnel (Cloudflare relays only encrypted data)."
                   if internet else "The phone is connected directly over your Wi-Fi.")
        elif tunnel:
            tip = (f"The QR code uses the internet tunnel ({tunnel}). Phones on this Wi-Fi switch to the direct "
                   "LAN connection by themselves.")
        elif self.net_mode == "lan":
            tip = "LAN mode: only phones on this Wi-Fi can connect; nothing goes through the internet."
        else:
            error = self.tunnel.error if self.tunnel else ""
            tip = f"The internet link failed: {error}." if error else "The internet tunnel is connecting…"
        self.path_badge.setText("INTERNET" if internet else "LAN")
        color = T.hexc("magenta" if internet else "green")
        self.path_badge.setStyleSheet(f"color: {color}; border: 1px solid {color}; border-radius: 8px; padding: 2px 8px;")
        self.path_badge.setToolTip(tip)
        self.path_badge.setVisible(self.server is not None)

    def _on_pc_info(self, info: dict) -> None:
        if self.server is not None and info.get("ip") == self.server.host:
            self._fill_pc(info)

    def _fill_pc(self, info: dict) -> None:
        self.pc_info = info
        self.net_values["pc_ip"].setText(f"{info.get('ip', '—')}   (port {self.server.port})" if self.server else "—")
        self.net_values["pc_mac"].setText(info.get("mac") or "…")
        if "wifi" not in info:
            wifi = "…"
        elif not info["wifi"]:
            wifi = f"Wired ({info.get('adapter') or 'Ethernet'})"
        else:
            wifi = info.get("ssid") or "Name hidden by Windows (needs Location access)"
        self.net_values["pc_wifi"].setText(wifi)

    def _fill_phone(self, phone: dict | None) -> None:
        if phone is None:
            for key in ("ph_name", "ph_model", "ph_ip", "ph_mac"):
                self.net_values[key].setText("—")
            return
        mac = phone["mac"] or "not in the ARP table yet"
        if phone["mac"] and S.mac_is_private(phone["mac"]):
            mac += "  (private)"                         # one line: the left column has no height to spare
            self.net_values["ph_mac"].setToolTip("Private MAC: randomized by the phone for this Wi-Fi")
        self.net_values["ph_name"].setText(phone["name"])
        self.net_values["ph_model"].setText(phone["model"] or "not reported by the browser")
        internet = phone.get("path") == "internet"
        self.net_values["ph_ip"].setText(f"{phone['ip']}  (public, via internet)" if internet else phone["ip"])
        self.net_values["ph_mac"].setText("not visible over the internet" if internet else mac)
