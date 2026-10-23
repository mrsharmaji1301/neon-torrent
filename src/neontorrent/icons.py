"""Vector icons painted with QPainter on a 24x24 grid - no image assets needed."""
from __future__ import annotations

from math import cos, pi, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)


def _pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _poly(path: QPainterPath, *pts) -> None:
    path.moveTo(*pts[0])
    for pt in pts[1:]:
        path.lineTo(*pt)


def icon_path(name: str) -> tuple[QPainterPath, QPainterPath]:
    """Returns (stroke_path, fill_path) in 24x24 coordinates."""
    s, f = QPainterPath(), QPainterPath()
    if name == "download":
        _poly(s, (12, 4), (12, 16)); _poly(s, (6.5, 10.5), (12, 16), (17.5, 10.5)); _poly(s, (5, 20), (19, 20))
    elif name == "upload":
        _poly(s, (12, 15), (12, 4)); _poly(s, (7, 9), (12, 4), (17, 9)); _poly(s, (4, 14), (4, 19.5), (20, 19.5), (20, 14))
    elif name == "users":
        s.addEllipse(QPointF(9, 8), 3.4, 3.4)
        s.moveTo(2.8, 19.5); s.cubicTo(2.8, 15.5, 5.5, 13.6, 9, 13.6); s.cubicTo(12.5, 13.6, 15.2, 15.5, 15.2, 19.5)
        s.moveTo(15.4, 4.9); s.cubicTo(18.6, 5.2, 18.6, 10.6, 15.4, 10.9)
        s.moveTo(17.2, 13.9); s.cubicTo(19.6, 14.5, 21.2, 16.3, 21.2, 19.5)
    elif name == "gauge":
        s.arcMoveTo(QRectF(3, 5, 18, 18), 200); s.arcTo(QRectF(3, 5, 18, 18), 200, -220)
        _poly(s, (12, 14), (16, 9.5))
        f.addEllipse(QPointF(12, 14), 1.7, 1.7)
    elif name == "gear":
        teeth = 8
        for i in range(teeth * 4 + 1):
            a = (i / (teeth * 4)) * 2 * pi
            r = 9.6 if (i % 4) in (1, 2) else 7.4
            pt = (12 + r * cos(a - pi / 16), 12 + r * sin(a - pi / 16))
            s.moveTo(*pt) if i == 0 else s.lineTo(*pt)
        s.addEllipse(QPointF(12, 12), 3, 3)
    elif name == "link":
        s.moveTo(10, 14); s.lineTo(14, 10)
        s.moveTo(13, 6.5); s.lineTo(14.6, 4.9); s.cubicTo(16.4, 3.1, 19.2, 3.1, 20.4, 4.4)
        s.cubicTo(21.9, 5.9, 21.6, 8.4, 19.6, 10.1); s.lineTo(17.6, 12)
        s.moveTo(11, 17.5); s.lineTo(9.4, 19.1); s.cubicTo(7.6, 20.9, 4.8, 20.9, 3.6, 19.6)
        s.cubicTo(2.1, 18.1, 2.4, 15.6, 4.4, 13.9); s.lineTo(6.4, 12)
    elif name in ("file_plus", "file"):
        _poly(s, (14, 2.5), (6, 2.5), (5, 3.5), (5, 20.5), (6, 21.5), (18, 21.5), (19, 20.5), (19, 7.5), (14, 2.5))
        _poly(s, (14, 2.5), (14, 7.5), (19, 7.5))
        if name == "file_plus":
            _poly(s, (12, 11), (12, 18)); _poly(s, (8.5, 14.5), (15.5, 14.5))
    elif name == "pause":
        f.addRoundedRect(QRectF(6, 4.5, 4, 15), 1.2, 1.2); f.addRoundedRect(QRectF(14, 4.5, 4, 15), 1.2, 1.2)
    elif name == "play":
        f.moveTo(7, 4.2); f.lineTo(20, 12); f.lineTo(7, 19.8); f.closeSubpath()
    elif name == "trash":
        _poly(s, (3.5, 6.5), (20.5, 6.5)); _poly(s, (9, 6.5), (9, 3.5), (15, 3.5), (15, 6.5))
        _poly(s, (5.5, 6.5), (6.8, 20.5), (17.2, 20.5), (18.5, 6.5)); _poly(s, (10, 10.5), (10, 16.5)); _poly(s, (14, 10.5), (14, 16.5))
    elif name == "database":
        s.addEllipse(QRectF(4.5, 3, 15, 5.5))
        _poly(s, (4.5, 5.75), (4.5, 18.25)); _poly(s, (19.5, 5.75), (19.5, 18.25))
        s.moveTo(4.5, 12); s.cubicTo(4.5, 15.6, 19.5, 15.6, 19.5, 12)
        s.moveTo(4.5, 18.25); s.cubicTo(4.5, 21.9, 19.5, 21.9, 19.5, 18.25)
    elif name == "list":
        for y, x2 in ((6, 20), (12, 17), (18, 14)):
            _poly(s, (8.5, y), (x2, y)); f.addEllipse(QPointF(4.5, y), 1.3, 1.3)
    elif name == "search":
        s.addEllipse(QPointF(10.5, 10.5), 6.5, 6.5); _poly(s, (15.3, 15.3), (20.5, 20.5))
    elif name == "dots":
        for x in (5, 12, 19):
            f.addEllipse(QPointF(x, 12), 1.9, 1.9)
    elif name == "min":
        _poly(s, (5, 12), (19, 12))
    elif name == "max":
        s.addRect(QRectF(5.5, 5.5, 13, 13))
    elif name == "restore":
        s.addRect(QRectF(4.5, 8.5, 11, 11)); _poly(s, (8.5, 8.5), (8.5, 4.5), (19.5, 4.5), (19.5, 15.5), (15.5, 15.5))
    elif name == "close":
        _poly(s, (6, 6), (18, 18)); _poly(s, (18, 6), (6, 18))
    elif name == "folder":
        _poly(s, (3, 6), (3, 19), (21, 19), (21, 8.5), (11.5, 8.5), (9.5, 5.5), (3.8, 5.5), (3, 6))
    elif name == "magnet":
        s.moveTo(5, 4); s.lineTo(5, 12); s.cubicTo(5, 21.3, 19, 21.3, 19, 12); s.lineTo(19, 4)
        _poly(s, (5, 8), (9, 8)); _poly(s, (15, 8), (19, 8)); _poly(s, (9, 4), (9, 12)); _poly(s, (15, 4), (15, 12))
        s.moveTo(9, 12); s.cubicTo(9, 16, 15, 16, 15, 12)
    elif name == "refresh":
        s.arcMoveTo(QRectF(4, 4, 16, 16), 60); s.arcTo(QRectF(4, 4, 16, 16), 60, 290)
        _poly(s, (16.5, 2.8), (16.2, 6.6), (20, 7))
    elif name == "info":
        s.addEllipse(QPointF(12, 12), 9, 9); _poly(s, (12, 11), (12, 16.5)); f.addEllipse(QPointF(12, 7.6), 1.2, 1.2)
    elif name == "copy":
        s.addRoundedRect(QRectF(8.5, 8.5, 12, 12), 2, 2); _poly(s, (15.5, 8.5), (15.5, 3.5), (3.5, 3.5), (3.5, 15.5), (8.5, 15.5))
    elif name == "sequence":
        for y in (6, 12, 18):
            _poly(s, (4, y), (14, y))
        _poly(s, (18, 5), (18, 19)); _poly(s, (15.5, 16.5), (18, 19), (20.5, 16.5))
    elif name == "move":
        _poly(s, (3, 6), (3, 19), (21, 19), (21, 8.5), (11.5, 8.5), (9.5, 5.5), (3.8, 5.5), (3, 6))
        _poly(s, (8.5, 14), (15.5, 14)); _poly(s, (13, 11.5), (15.5, 14), (13, 16.5))
    elif name == "shield":
        s.moveTo(12, 2.6); s.lineTo(19.6, 5.6); s.lineTo(19.6, 11.4)
        s.cubicTo(19.6, 16.2, 16.4, 19.6, 12, 21.4); s.cubicTo(7.6, 19.6, 4.4, 16.2, 4.4, 11.4)
        s.lineTo(4.4, 5.6); s.closeSubpath()
        _poly(s, (8.6, 11.8), (11.1, 14.3), (15.6, 9.4))
    elif name == "bolt":
        f.moveTo(13.6, 1.8); f.lineTo(4.6, 13.4); f.lineTo(11.2, 13.4); f.lineTo(9.8, 22.2)
        f.lineTo(19.4, 9.8); f.lineTo(12.6, 9.8); f.closeSubpath()
    elif name == "sliders":
        for y, knob in ((6, 15), (12, 8), (18, 13)):
            _poly(s, (3.5, y), (knob - 2.4, y)); _poly(s, (knob + 2.4, y), (20.5, y))
            s.addEllipse(QPointF(knob, y), 2.4, 2.4)
    elif name == "up":
        _poly(s, (6, 14.5), (12, 8.5), (18, 14.5))
    elif name == "down":
        _poly(s, (6, 9.5), (12, 15.5), (18, 9.5))
    elif name == "top":
        _poly(s, (6, 5), (18, 5)); _poly(s, (6, 16), (12, 10), (18, 16))
    elif name == "bottom":
        _poly(s, (6, 19), (18, 19)); _poly(s, (6, 8), (12, 14), (18, 8))
    elif name == "stop":
        f.addRoundedRect(QRectF(5.5, 5.5, 13, 13), 2.2, 2.2)
    elif name == "skip":
        f.moveTo(5, 5); f.lineTo(14, 12); f.lineTo(5, 19); f.closeSubpath()
        f.addRoundedRect(QRectF(15.5, 5, 3.5, 14), 1, 1)
    elif name == "globe":
        s.addEllipse(QPointF(12, 12), 9, 9); s.addEllipse(QRectF(8, 3, 8, 18))
        _poly(s, (3.4, 9), (20.6, 9)); _poly(s, (3.4, 15), (20.6, 15))
    elif name == "check":
        _poly(s, (5, 12.5), (10, 17.5), (19.5, 7))
    elif name == "power":
        _poly(s, (12, 3), (12, 11)); s.arcMoveTo(QRectF(4, 5, 16, 16), 55); s.arcTo(QRectF(4, 5, 16, 16), 55, -290)
    return s, f


def paint_icon(p: QPainter, name: str, rect: QRectF, color: QColor, width: float = 1.9,
               glow: bool = False) -> None:
    stroke, fill = icon_path(name)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.x(), rect.y())
    scale = min(rect.width(), rect.height()) / 24.0
    p.scale(scale, scale)
    if glow:
        halo = QColor(color)
        for w, a in ((width + 5, 30), (width + 2.6, 60)):
            halo.setAlpha(a)
            p.setPen(_pen(halo, w))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(stroke)
            if not fill.isEmpty():
                p.drawPath(fill)
    p.setPen(_pen(color, width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(stroke)
    if not fill.isEmpty():
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPath(fill)
    p.restore()


def make_icon(name: str, color: QColor, size: int = 32) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_icon(p, name, QRectF(2, 2, size - 4, size - 4), color, 2.0)
    p.end()
    return QIcon(pm)


# ------------------------------------------------------------------ logo

def paint_logo(p: QPainter, rect: QRectF, cyan: QColor, magenta: QColor, glow: float = 1.0) -> None:
    """Neon hexagon with an isometric cube inside."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy = rect.center().x(), rect.center().y()
    r = min(rect.width(), rect.height()) / 2 - 3

    def hexagon(radius: float) -> QPainterPath:
        path = QPainterPath()
        for i in range(7):
            a = pi / 180 * (60 * i - 90)
            pt = QPointF(cx + radius * cos(a), cy + radius * sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        return path

    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, cyan)
    grad.setColorAt(1.0, magenta)
    outer = hexagon(r)
    if glow > 0:
        for w, a in ((10, 24), (6, 50), (3.6, 90)):
            col = QColor(cyan); col.setAlpha(int(a * glow))
            halo = QPen(col, w)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(halo)
            p.drawPath(outer)
    pen = QPen(QBrush(grad), 2.6)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(outer)

    # cube: inner hexagon outline + three edges to the centre
    ir = r * 0.56
    inner = hexagon(ir)
    fill = QLinearGradient(QPointF(cx, cy - ir), QPointF(cx, cy + ir))
    a1 = QColor(magenta); a1.setAlpha(60)
    a2 = QColor(cyan); a2.setAlpha(40)
    fill.setColorAt(0, a1)
    fill.setColorAt(1, a2)
    p.setBrush(QBrush(fill))
    pen2 = QPen(QBrush(grad), 2.0)
    pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen2)
    p.drawPath(inner)
    edges = QPainterPath()
    for deg in (90, -30, 210):
        a = pi / 180 * deg
        edges.moveTo(cx, cy)
        edges.lineTo(cx + ir * cos(a), cy + ir * sin(a))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(edges)
    p.restore()


def logo_icon(cyan: QColor, magenta: QColor, size: int = 64) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_logo(p, QRectF(0, 0, size, size), cyan, magenta, glow=0.6)
    p.end()
    return QIcon(pm)


# ------------------------------------------------------------------ file badges

def paint_badge(p: QPainter, rect: QRectF, kind: str) -> None:
    """Coloured file-type badge used in the transfers list."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    cx, cy = rect.center().x(), rect.center().y()
    if kind == "disc":
        g = QRadialGradient(QPointF(cx - w * 0.15, cy - h * 0.2), w * 0.8)
        g.setColorAt(0, QColor("#ff8a4c")); g.setColorAt(1, QColor("#e24d12"))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(g)
        p.drawRoundedRect(rect, w * 0.22, w * 0.22)
        p.setPen(QPen(QColor("white"), w * 0.085)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), w * 0.25, w * 0.25)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("white"))
        for deg in (90, 210, 330):
            a = pi / 180 * deg
            p.drawEllipse(QPointF(cx + w * 0.3 * cos(a), cy - w * 0.3 * sin(a)), w * 0.075, w * 0.075)
    elif kind == "app":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#f5792a"))
        body = QPainterPath()
        body.moveTo(x + w * 0.08, cy + h * 0.02); body.lineTo(cx - w * 0.02, y + h * 0.12)
        body.lineTo(cx + w * 0.06, y + h * 0.2); body.lineTo(x + w * 0.24, cy + h * 0.12); body.closeSubpath()
        p.drawPath(body)
        p.drawEllipse(QPointF(cx + w * 0.08, cy + h * 0.08), w * 0.38, w * 0.33)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(cx + w * 0.1, cy + h * 0.06), w * 0.22, w * 0.19)
        p.setBrush(QColor("#265787"))
        p.drawEllipse(QPointF(cx + w * 0.1, cy + h * 0.06), w * 0.12, w * 0.11)
    elif kind in ("folder", "archive"):
        back = QColor("#5b7fa8") if kind == "folder" else QColor("#7c6bd6")
        front_top = QColor("#9cc3ec") if kind == "folder" else QColor("#b7a8ff")
        front_bot = QColor("#6d95c4") if kind == "folder" else QColor("#806ee0")
        tab = QPainterPath()
        tab.addRoundedRect(QRectF(x + w * 0.04, y + h * 0.16, w * 0.42, h * 0.22), 3, 3)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(back); p.drawPath(tab)
        p.drawRoundedRect(QRectF(x + w * 0.04, y + h * 0.24, w * 0.92, h * 0.62), 4, 4)
        g = QLinearGradient(QPointF(cx, y + h * 0.36), QPointF(cx, y + h * 0.88))
        g.setColorAt(0, front_top); g.setColorAt(1, front_bot)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(x + w * 0.04, y + h * 0.36, w * 0.92, h * 0.52), 4, 4)
        if kind == "archive":
            p.setBrush(QColor(255, 255, 255, 200))
            for i in range(3):
                p.drawRect(QRectF(cx - w * 0.04, y + h * (0.42 + i * 0.13), w * 0.08, h * 0.07))
    else:
        palette = {
            "video": ("#a855f7", "#6d28d9", "play"), "audio": ("#ec4899", "#9d174d", "audio"),
            "image": ("#22c55e", "#15803d", "image"), "doc": ("#38bdf8", "#0369a1", "doc"),
            "magnet": ("#22d3ee", "#0e7490", "magnet"), "file": ("#64748b", "#334155", "doc"),
        }
        top, bottom, glyph = palette.get(kind, palette["file"])
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        g.setColorAt(0, QColor(top)); g.setColorAt(1, QColor(bottom))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(g)
        p.drawRoundedRect(rect.adjusted(w * 0.06, h * 0.02, -w * 0.06, -h * 0.02), w * 0.2, w * 0.2)
        inner = rect.adjusted(w * 0.26, h * 0.24, -w * 0.26, -h * 0.24)
        white = QColor("white")
        if glyph == "play":
            paint_icon(p, "play", inner, white)
        elif glyph == "magnet":
            paint_icon(p, "magnet", inner, white, 2.2)
        elif glyph == "audio":
            p.setBrush(white); p.setPen(QPen(white, w * 0.06))
            p.drawLine(QPointF(cx + w * 0.08, cy + h * 0.14), QPointF(cx + w * 0.08, cy - h * 0.2))
            p.drawLine(QPointF(cx + w * 0.08, cy - h * 0.2), QPointF(cx + w * 0.2, cy - h * 0.12))
            p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(cx, cy + h * 0.15), w * 0.1, w * 0.08)
        elif glyph == "image":
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(white)
            mount = QPainterPath()
            mount.moveTo(inner.left(), inner.bottom()); mount.lineTo(inner.left() + inner.width() * 0.38, inner.top() + inner.height() * 0.35)
            mount.lineTo(inner.left() + inner.width() * 0.62, inner.top() + inner.height() * 0.65)
            mount.lineTo(inner.left() + inner.width() * 0.78, inner.top() + inner.height() * 0.48)
            mount.lineTo(inner.right(), inner.bottom()); mount.closeSubpath()
            p.drawPath(mount); p.drawEllipse(QPointF(inner.right() - 3, inner.top() + 3), 2.4, 2.4)
        else:
            paint_icon(p, "file", inner, white, 2.0)
    p.restore()
