"""Render the MSI installer artwork: packaging/installer-side.bmp (Welcome and Finish pages, 493 x 312) and
packaging/installer-banner.bmp (top banner of the other pages, 493 x 58), in the app's neon style.

WiX shows the side bitmap across the whole dialog with the page text on top of its right part, so only the left
164 px are dark; the rest stays white for readable text.
Run with the project's venv interpreter: .venv\\Scripts\\python.exe tools\\make_installer_art.py
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QGuiApplication, QIcon, QImage, QLinearGradient,  # noqa: E402
                           QPainter, QPainterPath, QPen, QRadialGradient)

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
SKY, MAGENTA, CYAN, MUTED = QColor("#38bdf8"), QColor("#e040fb"), QColor("#22d3ee"), QColor("#8ea3bd")
BG_TOP, BG_BOTTOM = QColor("#060b16"), QColor("#170a2a")
PANEL_W = 164


def head(size: float, weight: QFont.Weight = QFont.Weight.Bold, spacing: float = 0.0) -> QFont:
    font = QFont("Bahnschrift")
    font.setPixelSize(round(size))
    font.setWeight(weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def fit(text: str, width: float, start: float, weight: QFont.Weight, spacing: float) -> QFont:
    size = start
    while size > 8 and QFontMetricsF(head(size, weight, spacing)).horizontalAdvance(text) - spacing > width:
        size -= 0.5
    return head(size, weight, spacing)


def glow_text(p: QPainter, font: QFont, text: str, cx: float, baseline: float, c1: QColor, c2: QColor,
              glow: bool = True) -> None:
    """Text centred on cx, filled with a left-to-right gradient, with a soft neon halo."""
    metrics = QFontMetricsF(font)
    w = metrics.horizontalAdvance(text) - font.letterSpacing()
    x = cx - w / 2
    path = QPainterPath()
    path.addText(QPointF(x, baseline), font, text)
    grad = QLinearGradient(QPointF(x, 0), QPointF(x + w, 0))
    grad.setColorAt(0, c1)
    grad.setColorAt(1, c2)
    if glow:
        for width, alpha in ((9, 18), (6, 30), (3, 55)):
            halo = QLinearGradient(QPointF(x, 0), QPointF(x + w, 0))
            halo.setColorAt(0, QColor(c1.red(), c1.green(), c1.blue(), alpha))
            halo.setColorAt(1, QColor(c2.red(), c2.green(), c2.blue(), alpha))
            p.strokePath(path, QPen(halo, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                    Qt.PenJoinStyle.RoundJoin))
    p.fillPath(path, grad)


def synth_floor(p: QPainter, left: float, right: float, horizon: float, bottom: float) -> None:
    """A retro-futuristic perspective grid under a striped neon sun."""
    cx = (left + right) / 2
    p.save()
    p.setClipRect(QRectF(left, 0, right - left, bottom))
    # sun: magenta-to-sky disc above the horizon, cut by horizontal gaps
    radius = 27
    sun = QLinearGradient(QPointF(0, horizon - radius), QPointF(0, horizon))
    sun.setColorAt(0, QColor(MAGENTA.red(), MAGENTA.green(), MAGENTA.blue(), 235))
    sun.setColorAt(1, QColor(SKY.red(), SKY.green(), SKY.blue(), 200))
    disc = QPainterPath()
    disc.addEllipse(QPointF(cx, horizon), radius, radius)
    above = QPainterPath()
    above.addRect(QRectF(left, horizon - radius - 1, right - left, radius + 1))
    gaps = QPainterPath()
    for i, y in enumerate((horizon - 11, horizon - 6, horizon - 2.5)):
        gaps.addRect(QRectF(left, y, right - left, 1.4 + i * 0.6))
    halo = QRadialGradient(QPointF(cx, horizon), radius * 2.1)
    halo.setColorAt(0, QColor(224, 64, 251, 70))
    halo.setColorAt(1, QColor(224, 64, 251, 0))
    p.fillRect(QRectF(left, horizon - radius * 2.1, right - left, radius * 2.1), halo)
    p.fillPath(disc.intersected(above).subtracted(gaps), sun)
    # floor
    floor = QLinearGradient(QPointF(0, horizon), QPointF(0, bottom))
    floor.setColorAt(0, QColor("#12072a"))
    floor.setColorAt(1, QColor("#05030f"))
    p.fillRect(QRectF(left, horizon, right - left, bottom - horizon), floor)
    p.setPen(QPen(QColor(224, 64, 251, 150), 1.2))
    p.drawLine(QPointF(left, horizon), QPointF(right, horizon))
    for k in range(-9, 10):                                   # lines to the vanishing point
        p.setPen(QPen(QColor(34, 211, 238, 70 if k else 95), 1))
        p.drawLine(QPointF(cx + k * 3, horizon), QPointF(cx + k * 34, bottom))
    for i in range(1, 9):                                     # rows closer together near the horizon
        y = horizon + (bottom - horizon) * (i / 8) ** 1.9
        p.setPen(QPen(QColor(224, 64, 251, 40 + i * 9), 1))
        p.drawLine(QPointF(left, y), QPointF(right, y))
    p.restore()


def neon_edge(p: QPainter, x: float, top: float, bottom: float) -> None:
    grad = QLinearGradient(QPointF(0, top), QPointF(0, bottom))
    grad.setColorAt(0, SKY)
    grad.setColorAt(1, MAGENTA)
    p.fillRect(QRectF(x - 1, top, 2, bottom - top), grad)


def side_panel(icon: QIcon) -> QImage:
    img = QImage(493, 312, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    bg = QLinearGradient(QPointF(0, 0), QPointF(0, 312))
    bg.setColorAt(0, BG_TOP)
    bg.setColorAt(1, BG_BOTTOM)
    p.fillRect(QRectF(0, 0, PANEL_W, 312), bg)
    aura = QRadialGradient(QPointF(PANEL_W / 2, 112), 95)
    aura.setColorAt(0, QColor(56, 189, 248, 38))
    aura.setColorAt(1, QColor(56, 189, 248, 0))
    p.fillRect(QRectF(0, 0, PANEL_W, 240), aura)
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(0, 312, 3):                                # faint scanlines
        p.fillRect(QRectF(0, i, PANEL_W, 1), QColor(255, 255, 255, 6))
    cx = PANEL_W / 2
    p.drawPixmap(round(cx - 22), 22, icon.pixmap(44, 44))
    neon = fit("NEON", PANEL_W - 26, 52, QFont.Weight.Bold, 2.0)
    glow_text(p, neon, "NEON", cx, 122, SKY, MAGENTA)
    torrent = fit("TORRENT", PANEL_W - 30, 26, QFont.Weight.DemiBold, 3.2)
    glow_text(p, torrent, "TORRENT", cx, 150, QColor("white"), QColor("white"), glow=False)
    line = QLinearGradient(QPointF(cx - 46, 0), QPointF(cx + 46, 0))
    line.setColorAt(0, QColor(56, 189, 248, 0))
    line.setColorAt(0.5, CYAN)
    line.setColorAt(1, QColor(224, 64, 251, 0))
    p.fillRect(QRectF(cx - 46, 163, 92, 1.5), line)
    glow_text(p, head(8.5, QFont.Weight.Normal, 2.6), "BUILT BY", cx, 182, MUTED, MUTED, glow=False)
    glow_text(p, head(17, QFont.Weight.Bold, 0.6), "SharmaJi", cx, 202, CYAN, MAGENTA)
    synth_floor(p, 0, PANEL_W, 248, 312)
    neon_edge(p, PANEL_W, 0, 312)
    p.end()
    return img


def banner(icon: QIcon) -> QImage:
    img = QImage(493, 58, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    block = QPainterPath()                                    # dark block with a slanted left edge, right side
    block.moveTo(418, 0)
    block.lineTo(493, 0)
    block.lineTo(493, 58)
    block.lineTo(400, 58)
    block.closeSubpath()
    bg = QLinearGradient(QPointF(400, 0), QPointF(493, 58))
    bg.setColorAt(0, BG_TOP)
    bg.setColorAt(1, BG_BOTTOM)
    p.fillPath(block, bg)
    p.setPen(QPen(QColor(224, 64, 251, 200), 1.5))
    p.drawLine(QPointF(418, 0), QPointF(400, 58))
    p.drawPixmap(436, 10, icon.pixmap(38, 38))
    edge = QLinearGradient(QPointF(0, 0), QPointF(493, 0))
    edge.setColorAt(0, SKY)
    edge.setColorAt(1, MAGENTA)
    p.fillRect(QRectF(0, 56, 493, 2), edge)
    p.end()
    return img


def save_bmp(img: QImage, path: Path) -> None:
    if not img.convertToFormat(QImage.Format.Format_RGB888).save(str(path), "BMP"):
        raise SystemExit(f"Cannot write {path}")
    print(f"Wrote {path} ({path.stat().st_size // 1024} KB)")


def main() -> int:
    app = QGuiApplication([])  # noqa: F841  (fonts and pixmaps need it)
    icon = QIcon(str(PACKAGING / "NeonTorrent.ico"))
    save_bmp(side_panel(icon), PACKAGING / "installer-side.bmp")
    save_bmp(banner(icon), PACKAGING / "installer-banner.bmp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
