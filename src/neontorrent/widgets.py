"""Neon building blocks: glowing panels, buttons, stat cards and the custom title bar."""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import theme as T
from .icons import make_icon, paint_icon, paint_logo


def rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


# ------------------------------------------------------------------ background + panels

class NeonBackground(QWidget):
    """Window root: gradient backdrop, ambient light blobs and the outer glow of every NeonPanel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.panels: list[NeonPanel] = []
        self.radius = 14.0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def register(self, panel: "NeonPanel") -> None:
        self.panels.append(panel)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = 0.0 if self.window().isMaximized() else self.radius
        shape = rounded(r, radius)
        p.setClipPath(shape)
        bg = QLinearGradient(r.topLeft(), r.bottomRight())
        bg.setColorAt(0, T.c("bg1"))
        bg.setColorAt(0.55, T.c("bg0"))
        bg.setColorAt(1, T.c("bg1"))
        p.fillRect(r, bg)
        # ambient neon light leaking from the corners
        for center, key, alpha, size in ((QPointF(r.width() * 0.08, 0), "cyan", 38, 0.55),
                                         (QPointF(r.width() * 0.95, r.height() * 0.15), "magenta", 26, 0.45),
                                         (QPointF(r.width() * 0.5, r.height() * 1.05), "cyan2", 22, 0.6)):
            g = QRadialGradient(center, max(r.width(), r.height()) * size)
            g.setColorAt(0, T.c(key, alpha))
            g.setColorAt(1, T.c(key, 0))
            p.fillRect(r, g)
        # glow halos behind panels
        for panel in self.panels:
            seen = panel.visibleRegion().boundingRect()  # partial or empty when scrolled inside a QScrollArea
            if not panel.isVisible() or seen.isEmpty():
                continue
            top_left = panel.mapTo(self, panel.rect().topLeft())
            pr = QRectF(top_left.x(), top_left.y(), panel.width(), panel.height())
            # the halo spills past an edge only where that edge of the panel is actually on screen
            clip = QRectF(seen.translated(top_left)).adjusted(
                -12 if seen.left() <= 0 else 0, -12 if seen.top() <= 0 else 0,
                12 if seen.right() >= panel.width() - 1 else 0, 12 if seen.bottom() >= panel.height() - 1 else 0)
            p.save()
            p.setClipRect(clip, Qt.ClipOperation.IntersectClip)
            color = QColor(panel.glow_color)
            level = panel.glow_strength + panel.hover_level * 0.9
            for spread, alpha in ((9, 10), (6, 18), (3.5, 30), (1.5, 48)):
                color.setAlpha(int(min(255, alpha * level)))
                p.setPen(QPen(color, spread * 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(pr, panel.radius, panel.radius)
            p.restore()
        p.setClipping(False)
        p.setPen(QPen(T.c("cyan", 70), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)


class NeonPanel(QFrame):
    """Rounded translucent panel with a coloured neon border. Glow is drawn by NeonBackground."""

    def __init__(self, glow_key: str = "cyan", strength: float = 1.0, radius: float = 12.0,
                 tint_key: str | None = None, hoverable: bool = False, parent=None):
        super().__init__(parent)
        self.glow_key = glow_key
        self.tint_key = tint_key
        self.glow_strength = strength
        self.radius = radius
        self.hoverable = hoverable
        self._hover = 0.0
        self.anim = QPropertyAnimation(self, b"hover_level", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, hoverable)

    @property
    def glow_color(self) -> QColor:
        return T.c(self.glow_key)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()
        bg = self._background()
        if bg is not None:
            top_left = self.mapTo(bg, self.rect().topLeft())
            bg.update(top_left.x() - 24, top_left.y() - 24, self.width() + 48, self.height() + 48)

    hover_level = Property(float, _get_hover, _set_hover)

    def _background(self):
        w = self.parentWidget()
        while w is not None and not isinstance(w, NeonBackground):
            w = w.parentWidget()
        return w

    def enterEvent(self, event):
        if self.hoverable:
            self.anim.stop(); self.anim.setStartValue(self._hover); self.anim.setEndValue(1.0); self.anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.hoverable:
            self.anim.stop(); self.anim.setStartValue(self._hover); self.anim.setEndValue(0.0); self.anim.start()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        fill = QLinearGradient(r.topLeft(), r.bottomLeft())
        top = T.c("panel_hi", 235)
        bottom = T.c("panel", 225)
        if self.tint_key:
            tint = T.c(self.tint_key)
            top = QColor(
                int(top.red() * 0.8 + tint.red() * 0.2), int(top.green() * 0.8 + tint.green() * 0.2),
                int(top.blue() * 0.8 + tint.blue() * 0.2), 235)
            bottom = QColor(
                int(bottom.red() * 0.88 + tint.red() * 0.12), int(bottom.green() * 0.88 + tint.green() * 0.12),
                int(bottom.blue() * 0.88 + tint.blue() * 0.12), 225)
        fill.setColorAt(0, top)
        fill.setColorAt(1, bottom)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r, self.radius, self.radius)
        border = QLinearGradient(r.topLeft(), r.bottomRight())
        border.setColorAt(0, T.c(self.glow_key, int(150 + 90 * self._hover)))
        border.setColorAt(0.5, T.c(self.glow_key, int(70 + 80 * self._hover)))
        border.setColorAt(1, T.c(self.glow_key, int(120 + 100 * self._hover)))
        p.setPen(QPen(QBrush(border), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self.radius, self.radius)
        # glassy top highlight
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawLine(QPointF(r.left() + self.radius, r.top() + 1.2), QPointF(r.right() - self.radius, r.top() + 1.2))


# ------------------------------------------------------------------ buttons

class GlowButton(QPushButton):
    """Neon button. variant: solid (gradient fill), outline (tinted), ghost (icon-only)."""

    def __init__(self, text: str = "", icon: str = "", color_key: str = "cyan", variant: str = "outline",
                 color2_key: str | None = None, parent=None):
        super().__init__(text, parent)
        self.icon_name = icon
        self.color_key = color_key
        self.color2_key = color2_key
        self.variant = variant
        self.danger_hover = False
        self.icon_size = 20.0
        self._glow = 0.0
        self._press = 0.0
        self.active = False                       # latched "on" state (FLASH MODE): solid fill + pulsing glow
        self._phase = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(60)
        self._pulse_timer.timeout.connect(self._pulse_tick)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setOffset(0, 0)
        self.shadow.setBlurRadius(0)
        self.shadow.setColor(self.accent())
        self.setGraphicsEffect(self.shadow)
        self.anim = QPropertyAnimation(self, b"glow", self)
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.press_anim = QPropertyAnimation(self, b"press", self)
        self.press_anim.setDuration(260)
        self.press_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.pressed.connect(self._on_pressed)
        self.released.connect(self._on_released)
        self.setFont(T.head_font(10.5, QFont.Weight.DemiBold, 1.2))

    def accent(self) -> QColor:
        if self.danger_hover and self._glow > 0.05:
            return T.c("red")
        return T.c(self.color_key)

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.font())
        width = fm.horizontalAdvance(self.text()) + (self.icon_size + 12 if self.icon_name else 0) + 44
        return QSize(int(width), 48)

    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, value: float) -> None:
        self._glow = value
        effective = self._effective_glow()
        color = self.accent()
        color.setAlpha(int(230 * effective))
        self.shadow.setColor(color)
        self.shadow.setBlurRadius(4 + 30 * effective + 10 * self._press)
        self.update()

    def _effective_glow(self) -> float:
        if self.active and self.isEnabled():
            return max(self._glow, 0.55 + 0.45 * abs(1.0 - self._phase))
        return self._glow

    def set_active(self, on: bool) -> None:
        self.active = on
        if on:
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
        self._set_glow(self._glow)

    def _pulse_tick(self) -> None:
        self._phase = (self._phase + 0.06) % 2.0
        self._set_glow(self._glow)

    glow = Property(float, _get_glow, _set_glow)

    def _get_press(self) -> float:
        return self._press

    def _set_press(self, value: float) -> None:
        self._press = value
        self._set_glow(self._glow)

    press = Property(float, _get_press, _set_press)

    def _animate(self, end: float) -> None:
        self.anim.stop()
        self.anim.setStartValue(self._glow)
        self.anim.setEndValue(end)
        self.anim.start()

    def enterEvent(self, event):
        if self.isEnabled():
            self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate(0.0)
        super().leaveEvent(event)

    def changeEvent(self, event):
        if event.type() == event.Type.EnabledChange and not self.isEnabled():
            self._animate(0.0)
        super().changeEvent(event)

    def _on_pressed(self):
        self.press_anim.stop()
        self._set_press(1.0)

    def _on_released(self):
        self.press_anim.stop()
        self.press_anim.setStartValue(1.0)
        self.press_anim.setEndValue(0.0)
        self.press_anim.start()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        enabled = self.isEnabled()
        accent = self.accent()
        g = self._effective_glow() if enabled else 0.0
        variant = "solid" if self.active else self.variant
        inset = 1.0 + 1.2 * self._press
        r = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        radius = 9.0
        if not enabled:
            p.setOpacity(0.38)
        if variant == "solid":
            c2 = T.c(self.color2_key) if self.color2_key else accent.darker(130)
            grad = QLinearGradient(r.topLeft(), r.bottomRight())
            grad.setColorAt(0, accent.lighter(int(108 + 22 * g)))
            grad.setColorAt(1, c2.lighter(int(100 + 18 * g)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(r, radius, radius)
            p.setPen(QPen(QColor(255, 255, 255, int(60 + 120 * g)), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.6, 0.6, -0.6, -0.6), radius, radius)
            # glass sheen on the upper half
            sheen = QLinearGradient(r.topLeft(), QPointF(r.left(), r.center().y()))
            sheen.setColorAt(0, QColor(255, 255, 255, 50))
            sheen.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sheen)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -r.height() / 2), radius - 2, radius - 2)
            dark_text = accent.lightness() > 150 and self.color_key in ("cyan", "yellow", "green")
            fg = QColor("#04111c") if dark_text else QColor("white")
        elif variant == "ghost":
            p.setPen(QPen(T.c("line", int(140 + 115 * g)) if g < 0.05 else QColor(accent.red(), accent.green(), accent.blue(), int(110 + 140 * g)), 1.1))
            p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), int(10 + 40 * g)))
            p.drawRoundedRect(r, radius, radius)
            fg = QColor(accent) if g > 0.05 else T.c("muted").lighter(120)
            if g > 0.05:
                fg = accent.lighter(115)
        else:
            fill = QColor(accent)
            fill.setAlpha(int(26 + 46 * g + 40 * self._press))
            p.setBrush(fill)
            border = QColor(accent)
            border.setAlpha(int(150 + 105 * g))
            p.setPen(QPen(border, 1.3))
            p.drawRoundedRect(r, radius, radius)
            inner = QLinearGradient(r.topLeft(), r.bottomLeft())
            inner.setColorAt(0, QColor(255, 255, 255, int(18 + 22 * g)))
            inner.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(inner)
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -r.height() / 2), radius - 1.5, radius - 1.5)
            fg = accent.lighter(int(100 + 30 * g))
        # content
        text = self.text()
        p.setFont(self.font())
        fm = QFontMetricsF(self.font())
        tw = fm.horizontalAdvance(text) if text else 0.0
        iw = self.icon_size if self.icon_name else 0.0
        gap = 12.0 if (text and self.icon_name) else 0.0
        total = tw + iw + gap
        x = r.center().x() - total / 2
        cy = r.center().y()
        if self.icon_name:
            paint_icon(p, self.icon_name, QRectF(x, cy - iw / 2, iw, iw), fg, 2.0, glow=g > 0.3)
        if text:
            if g > 0.05 and variant != "solid":
                halo = QColor(fg)
                halo.setAlpha(int(70 * g))
                p.setPen(halo)
                p.drawText(QRectF(x + iw + gap, r.top() + 1, tw + 2, r.height()),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            p.setPen(fg)
            p.drawText(QRectF(x + iw + gap, r.top(), tw + 2, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class WindowButton(QPushButton):
    """Minimal title-bar control (minimise / maximise / close)."""

    def __init__(self, icon: str, danger: bool = False, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.danger = danger
        self.setFixedSize(46, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse()
        if hover:
            color = T.c("red", 200) if self.danger else T.c("cyan", 40)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(3, 2, -3, -2), 7, 7)
        fg = QColor("white") if (hover and self.danger) else (T.c("cyan") if hover else T.c("text", 200))
        paint_icon(p, self.icon_name, QRectF(self.width() / 2 - 8, self.height() / 2 - 8, 16, 16), fg, 1.6,
                   glow=hover and not self.danger)


# ------------------------------------------------------------------ text pieces

class BrandTitle(QWidget):
    """"NEON / TORRENT" wordmark with gradient + glow, and the subtitle line underneath."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title_font = T.head_font(25, QFont.Weight.Bold, 3.2)
        self.sub_font = T.head_font(8.6, QFont.Weight.Normal, 3.0)
        self.setMinimumSize(380, 62)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        fm = QFontMetricsF(self.title_font)
        base = fm.ascent() + 2
        x = 0.0
        parts = (("NEON", "cyan", "cyan2", True), (" / ", "magenta", "magenta", True), ("TORRENT", "text", "text", False))
        for text, k1, k2, glow in parts:
            w = fm.horizontalAdvance(text)
            path = QPainterPath()
            path.addText(QPointF(x, base), self.title_font, text)
            grad = QLinearGradient(QPointF(x, 0), QPointF(x + w, base))
            grad.setColorAt(0, T.c(k1))
            grad.setColorAt(1, T.c(k2).lighter(110))
            if glow:
                for width, alpha in ((7, 22), (4, 45), (2, 80)):
                    p.setPen(QPen(T.c(k1, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                  Qt.PenJoinStyle.RoundJoin))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawPath(path)
            x += w
        p.setFont(self.sub_font)
        p.setPen(T.c("muted"))
        p.drawText(QPointF(2, base + 24), "PEER-TO-PEER  ·  CONTROL CENTER")


class StatusDot(QWidget):
    """Pulsing status LED with a glow halo."""

    def __init__(self, size: int = 12, parent=None):
        super().__init__(parent)
        self.color_key = "green"
        self.setFixedSize(size + 10, size + 10)
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(60)

    def set_level(self, level: str) -> None:
        self.color_key = {"ok": "green", "warn": "yellow", "error": "red", "info": "cyan"}.get(level, "green")
        self.update()

    def _tick(self):
        self.phase = (self.phase + 0.06) % 2.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        pulse = abs(1.0 - self.phase)
        halo = QRadialGradient(center, self.width() / 2)
        halo.setColorAt(0, T.c(self.color_key, int(120 + 80 * pulse)))
        halo.setColorAt(1, T.c(self.color_key, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(center, self.width() / 2, self.height() / 2)
        p.setBrush(T.c(self.color_key))
        p.drawEllipse(center, (self.width() - 10) / 2 * 0.62, (self.height() - 10) / 2 * 0.62)


class NeonLineEdit(QLineEdit):
    """Input with a painted leading icon and a focus glow."""

    def __init__(self, icon: str, placeholder: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.setPlaceholderText(placeholder)
        self.setObjectName("neonInput")
        self.setTextMargins(36, 0, 6, 0)
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setOffset(0, 0)
        self.shadow.setBlurRadius(0)
        self.setGraphicsEffect(self.shadow)

    def focusInEvent(self, event):
        self.shadow.setColor(T.c("cyan", 170))
        self.shadow.setBlurRadius(22)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self.shadow.setBlurRadius(0)
        super().focusOutEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        color = T.c("cyan") if self.hasFocus() else T.c("muted")
        s = 18.0
        paint_icon(p, self.icon_name, QRectF(14, self.height() / 2 - s / 2, s, s), color, 1.8)


# ------------------------------------------------------------------ stat card

class Sparkline(QWidget):
    def __init__(self, color_key: str, parent=None):
        super().__init__(parent)
        self.color_key = color_key
        self.values: list[float] = []
        self.setFixedSize(66, 34)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_values(self, values: list[float]) -> None:
        self.values = values[-24:]
        self.update()

    def paintEvent(self, _event):
        if len(self.values) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        top = max(self.values) or 1.0
        n = len(self.values)
        pts = [QPointF(2 + i * (w - 4) / (n - 1), h - 4 - (v / top) * (h - 10)) for i, v in enumerate(self.values)]
        path = QPainterPath(pts[0])
        for a, b in zip(pts, pts[1:]):
            mid = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
        area = QPainterPath(path)
        area.lineTo(pts[-1].x(), h)
        area.lineTo(pts[0].x(), h)
        area.closeSubpath()
        fill = QLinearGradient(QPointF(0, 0), QPointF(0, h))
        fill.setColorAt(0, T.c(self.color_key, 70))
        fill.setColorAt(1, T.c(self.color_key, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(area, fill)
        for width, alpha in ((5, 40), (2, 255)):
            p.setPen(QPen(T.c(self.color_key, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)


class IconRing(QWidget):
    def __init__(self, icon: str, color_key: str, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.color_key = color_key
        self.setFixedSize(60, 60)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(4, 4, self.width() - 8, self.height() - 8)
        g = QRadialGradient(r.center(), r.width() / 2)
        g.setColorAt(0, T.c(self.color_key, 30))
        g.setColorAt(1, T.c(self.color_key, 8))
        p.setBrush(g)
        for width, alpha in ((6, 30), (1.6, 230)):
            p.setPen(QPen(T.c(self.color_key, alpha), width))
            p.drawEllipse(r)
            p.setBrush(Qt.BrushStyle.NoBrush)
        s = r.width() * 0.5
        paint_icon(p, self.icon_name, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s),
                   T.c(self.color_key), 1.9, glow=True)


class StatCard(NeonPanel):
    clicked = Signal()

    def __init__(self, title: str, icon: str, color_key: str, tint: bool = False, spark: bool = True,
                 action_icon: str = "", clickable: bool = False, parent=None):
        super().__init__(glow_key=color_key, strength=0.75, tint_key=color_key if tint else None,
                         hoverable=True, parent=parent)
        self.clickable = clickable
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(100)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 16, 14)
        layout.setSpacing(16)
        self.ring = IconRing(icon, color_key)
        layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addStretch(1)
        self.title = QLabel(title.upper())
        self.title.setObjectName("statTitle")
        self.title.setFont(T.head_font(9, QFont.Weight.Normal, 1.4))
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        self.value.setFont(T.head_font(21, QFont.Weight.DemiBold, 0.6))
        col.addWidget(self.title)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.value)
        self.spark = Sparkline(color_key) if spark else None
        if self.spark:
            row.addWidget(self.spark, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        col.addLayout(row)
        col.addStretch(1)
        layout.addLayout(col, 1)
        self.action = None
        if action_icon:
            self.action = GlowButton("", action_icon, color_key, "ghost")
            self.action.setFixedSize(42, 42)
            self.action.icon_size = 20
            layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignVCenter)

    def mouseReleaseEvent(self, event):
        if self.clickable and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SectionTitle(QWidget):
    def __init__(self, icon: str, text: str, subtitle: str = "", icon_box: bool = False, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.text = text
        self.subtitle = subtitle
        self.icon_box = icon_box
        self.setMinimumHeight(52 if subtitle else 34)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_text(self, text: str) -> None:
        self.text = text
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(T.head_font(13.5, QFont.Weight.DemiBold, 1.6))
        sub = QFontMetricsF(T.font(9.5)).horizontalAdvance(self.subtitle) if self.subtitle else 0
        return QSize(int(max(fm.horizontalAdvance(self.text), sub) + (66 if self.icon_box else 46)),
                     52 if self.subtitle else 34)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        h = self.height()
        if self.icon_box:
            paint_icon(p, self.icon_name, QRectF(0, h / 2 - 18, 36, 36), T.c("cyan"), 1.7, glow=True)
            x = 58.0
        else:
            paint_icon(p, self.icon_name, QRectF(0, h / 2 - 12, 24, 24), T.c("text"), 1.8)
            x = 40.0
        title_font = T.head_font(13.5 if not self.subtitle else 12.5, QFont.Weight.DemiBold, 1.6)
        p.setFont(title_font)
        p.setPen(T.c("text"))
        if self.subtitle:
            p.drawText(QRectF(x, 0, self.width() - x, h / 2 + 2), Qt.AlignmentFlag.AlignBottom, self.text)
            p.setFont(T.font(9.5))
            p.setPen(T.c("muted"))
            p.drawText(QRectF(x, h / 2 + 6, self.width() - x, h / 2), Qt.AlignmentFlag.AlignTop, self.subtitle)
        else:
            p.drawText(QRectF(x, 0, self.width() - x, h), Qt.AlignmentFlag.AlignVCenter, self.text)


class Logo(QWidget):
    def __init__(self, size: int = 58, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event):
        p = QPainter(self)
        paint_logo(p, QRectF(self.rect()), T.c("cyan"), T.c("magenta"))


class VSeparator(QWidget):
    def __init__(self, height: int = 34, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, height)

    def paintEvent(self, _event):
        p = QPainter(self)
        g = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
        g.setColorAt(0, T.c("line", 0)); g.setColorAt(0.5, T.c("line", 255)); g.setColorAt(1, T.c("line", 0))
        p.fillRect(QRectF(self.width() / 2, 0, 1, self.height()), g)


class StatusLine(QWidget):
    """Footer status: LED + 'ENGINE READY · DHT ONLINE · UPLOAD CAP' with coloured segments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments: list[tuple[str, str]] = [("ENGINE STARTING", "muted")]
        self.setMinimumWidth(260)
        self.setMinimumHeight(30)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.f = T.head_font(9.2, QFont.Weight.Normal, 1.0)

    def set_segments(self, segments: list[tuple[str, str]]) -> None:
        self.segments = segments
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.f)
        text = "   ·   ".join(s for s, _ in self.segments)
        return QSize(int(fm.horizontalAdvance(text) + 12), 30)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self.f)
        fm = QFontMetricsF(self.f)
        sep = "   ·   "
        segments = list(self.segments)

        def width_of(items) -> float:
            return sum(fm.horizontalAdvance(s) for s, _ in items) + fm.horizontalAdvance(sep) * (len(items) - 1)

        # never draw past the left edge: drop the least important (leading) segments first
        while len(segments) > 1 and width_of(segments) > self.width() - 8:
            segments.pop(0)
        total = width_of(segments)
        x = self.width() - total - 4
        for i, (text, key) in enumerate(segments):
            if i:
                p.setPen(T.c("muted", 150))
                p.drawText(QPointF(x, self.height() / 2 + fm.ascent() / 2 - 1), sep)
                x += fm.horizontalAdvance(sep)
            p.setPen(T.c(key) if key != "text" else T.c("text", 220))
            p.drawText(QPointF(x, self.height() / 2 + fm.ascent() / 2 - 1), text)
            x += fm.horizontalAdvance(text)


# ------------------------------------------------------------------ status filter chips

class FilterChip(QPushButton):
    """Neon pill with a label and a live count. Glows in its own colour when selected; dims when empty."""

    PAD = 4.0                                   # room around the pill for the glow

    def __init__(self, label: str, color_key: str, parent=None):
        super().__init__(parent)
        self.label = label
        self.color_key = color_key
        self.count = 0
        self._hover = False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(36)
        self._fit()

    def set_count(self, count: int) -> None:
        if count != self.count:
            self.count = count
            self._fit()
            self.update()

    def _badge_width(self) -> float:
        return max(22.0, QFontMetricsF(T.head_font(8, QFont.Weight.Bold, 0.4)).horizontalAdvance(str(self.count)) + 12)

    def _fit(self) -> None:
        label = QFontMetricsF(T.head_font(8.5)).horizontalAdvance(self.label)
        self.setFixedWidth(int(2 * self.PAD + 14 + label + 10 + self._badge_width() + 5))

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
        r = QRectF(self.rect()).adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        pill = rounded(r, r.height() / 2)
        key, on = self.color_key, self.isChecked()
        empty = self.count == 0 and not on
        if on:
            for width, alpha in ((7.0, 28), (4.0, 60)):          # soft outer glow
                p.setPen(QPen(T.c(key, alpha), width))
                p.drawPath(pill)
            fill = QLinearGradient(r.topLeft(), r.bottomLeft())
            fill.setColorAt(0, T.c(key, 85))
            fill.setColorAt(1, T.c(key, 30))
            p.fillPath(pill, fill)
        else:
            p.fillPath(pill, T.c("panel", 170))
        p.setPen(QPen(T.c(key, 255 if on else (190 if self._hover else (55 if empty else 110))), 1.2))
        p.drawPath(pill)

        p.setFont(T.head_font(8.5))
        p.setPen(QColor("white") if on else T.c("muted" if empty else "text", 235 if self._hover else 200))
        text_rect = QRectF(r.left() + 14, r.top(), r.width(), r.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)

        bw = self._badge_width()
        badge = QRectF(r.right() - bw - 4, r.top() + 4, bw, r.height() - 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.c(key, 235 if on else (35 if empty else 95)))
        p.drawRoundedRect(badge, badge.height() / 2, badge.height() / 2)
        p.setFont(T.head_font(8, QFont.Weight.Bold, 0.4))
        p.setPen(T.c("bg0") if on else (T.c("muted") if empty else QColor("white")))
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self.count))


class PageTab(QPushButton):
    """A large text tab with a live count (DOWNLOADING 3); the selected one glows and gets an underline."""

    def __init__(self, label: str, color_key: str, parent=None):
        super().__init__(parent)
        self.label, self.color_key, self.count, self._hover = label, color_key, 0, False
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(40)
        self._fit()

    def set_count(self, count: int) -> None:
        if count != self.count:
            self.count = count
            self._fit()
            self.update()

    def _fit(self) -> None:
        text = QFontMetricsF(T.head_font(11.5, QFont.Weight.DemiBold, 1.6)).horizontalAdvance(self.label)
        number = QFontMetricsF(T.head_font(10, QFont.Weight.Bold)).horizontalAdvance(str(self.count))
        self.setFixedWidth(int(text + number + 34))

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
        on, key = self.isChecked(), self.color_key
        r = QRectF(self.rect()).adjusted(6, 0, -6, -6)
        p.setFont(T.head_font(11.5, QFont.Weight.DemiBold, 1.6))
        p.setPen(T.c(key) if on else T.c("text", 235 if self._hover else 150))
        p.drawText(r, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.label)
        offset = QFontMetricsF(p.font()).horizontalAdvance(self.label) + 10
        p.setFont(T.head_font(10, QFont.Weight.Bold))
        p.setPen(T.c(key, 230) if on else T.c("muted", 220))
        p.drawText(r.adjusted(offset, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   str(self.count))
        if on:
            y = self.height() - 3.0
            for width, alpha in ((7.0, 40), (3.0, 255)):
                p.setPen(QPen(T.c(key, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(8, y), QPointF(self.width() - 8, y))


class FilterBar(QWidget):
    """One row of status chips (or page tabs); exactly one is selected at a time."""
    changed = Signal(str)

    def __init__(self, filters: list[tuple[str, str, str]], parent=None, chip_class=None, spacing: int = 2):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(spacing)
        self.chips: dict[str, FilterChip] = {}
        for key, label, color_key in filters:
            chip = (chip_class or FilterChip)(label, color_key, self)
            chip.clicked.connect(lambda _checked=False, k=key: self.select(k))
            layout.addWidget(chip)
            self.chips[key] = chip
        layout.addStretch(1)
        self.current = filters[0][0]
        self.chips[self.current].setChecked(True)

    def select(self, key: str) -> None:
        if key not in self.chips:
            return
        for k, chip in self.chips.items():
            chip.setChecked(k == key)            # clicking the selected chip again keeps it selected
        if key != self.current:
            self.current = key
            self.changed.emit(key)

    def set_counts(self, counts: dict[str, int]) -> None:
        for key, chip in self.chips.items():
            chip.set_count(counts.get(key, 0))

    def show_only(self, keys: list[str]) -> None:
        """Hide the chips a page has no use for; a hidden selection falls back to the first visible chip."""
        for key, chip in self.chips.items():
            chip.setVisible(key in keys)
        if self.current not in keys:
            self.select(keys[0])


__all__ = [
    "NeonBackground", "NeonPanel", "GlowButton", "WindowButton", "BrandTitle", "StatusDot", "NeonLineEdit",
    "StatCard", "SectionTitle", "Logo", "VSeparator", "StatusLine", "FilterChip", "PageTab", "FilterBar", "make_icon",
    "Signal",
]
