from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtGui import QColor, QFont

DEFAULT_UPLOAD_KIB = 24

# Every palette exposes the same keys so painters never care which theme is active.
THEMES: dict[str, dict[str, str]] = {
    "Cyberpunk": {
        "bg0": "#060b16", "bg1": "#0a1426", "panel": "#0c1a2e", "panel_hi": "#11233b",
        "line": "#1a3550", "track": "#1a2a40", "text": "#eaf4ff", "muted": "#8ea3bd",
        "cyan": "#22d3ee", "cyan2": "#0ea5ff", "magenta": "#e040fb", "purple": "#a855f7",
        "blue": "#38bdf8", "green": "#22e5a0", "yellow": "#ffc83d", "orange": "#ff9f43",
        "red": "#ff4d7d", "input": "#081426",
    },
    "Synthwave": {
        "bg0": "#0d0618", "bg1": "#170a2a", "panel": "#1a0d30", "panel_hi": "#24123f",
        "line": "#3b1d5e", "track": "#2a1844", "text": "#fbefff", "muted": "#b39ac8",
        "cyan": "#2de2e6", "cyan2": "#18a0fb", "magenta": "#ff3cac", "purple": "#b967ff",
        "blue": "#4d9fff", "green": "#3ef0b0", "yellow": "#ffd319", "orange": "#ff901f",
        "red": "#ff4466", "input": "#120824",
    },
    "Dark": {
        "bg0": "#0e1116", "bg1": "#141922", "panel": "#171d27", "panel_hi": "#1e2632",
        "line": "#2c3747", "track": "#242e3c", "text": "#e8edf4", "muted": "#9aa6b6",
        "cyan": "#69baff", "cyan2": "#4c8dff", "magenta": "#a18bff", "purple": "#8f7bff",
        "blue": "#69baff", "green": "#36d6a1", "yellow": "#f3c142", "orange": "#f59e42",
        "red": "#f45678", "input": "#10151d",
    },
    "Solarized": {
        "bg0": "#00212b", "bg1": "#002b36", "panel": "#073642", "panel_hi": "#0b4050",
        "line": "#1d5866", "track": "#0f4553", "text": "#eee8d5", "muted": "#93a1a1",
        "cyan": "#2aa198", "cyan2": "#268bd2", "magenta": "#d33682", "purple": "#6c71c4",
        "blue": "#268bd2", "green": "#859900", "yellow": "#b58900", "orange": "#cb4b16",
        "red": "#dc322f", "input": "#062f3a",
    },
}

_active = "Cyberpunk"


def set_theme(name: str) -> str:
    global _active
    _active = name if name in THEMES else "Cyberpunk"
    return _active


def theme_name() -> str:
    return _active


def c(key: str, alpha: int | None = None) -> QColor:
    """Colour from the active palette, optionally with alpha 0-255."""
    color = QColor(THEMES[_active][key])
    if alpha is not None:
        color.setAlpha(alpha)
    return color


def hexc(key: str) -> str:
    return THEMES[_active][key]


STATE_COLORS = {
    "Downloading": "cyan2", "Seeding": "green", "Paused": "yellow", "Checking": "orange",
    "Queued": "purple", "Error": "red", "Metadata": "cyan", "Completed": "green", "Disk full": "red", "Stopped": "muted",
}


def state_color(state: str) -> QColor:
    return c(STATE_COLORS.get(state, "muted"))


def font(size: float, weight: QFont.Weight = QFont.Weight.Normal, family: str = "Segoe UI",
         spacing: float = 0.0) -> QFont:
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


HEAD_FAMILY = "Bahnschrift"


def head_font(size: float, weight: QFont.Weight = QFont.Weight.DemiBold, spacing: float = 1.2) -> QFont:
    return font(size, weight, HEAD_FAMILY, spacing)


# ---------------------------------------------------------------- storage

def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    root = Path(base) / "NeonTorrent"
    root.mkdir(parents=True, exist_ok=True)
    return root


def load_preferences() -> dict:
    try:
        value = json.loads((app_data_dir() / "settings.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_preferences(prefs: dict) -> None:
    path = app_data_dir() / "settings.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- formatting

def fmt_bytes(value: float) -> str:
    amount = max(0.0, float(value))
    for unit, size in (("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if amount >= size:
            scaled = amount / size
            return f"{scaled:.1f} {unit}" if unit in ("TB", "GB") or scaled < 10 else f"{scaled:.0f} {unit}"
    return f"{int(amount)} B"


def fmt_speed(value: float) -> str:
    amount = max(0.0, float(value))
    if amount >= 1024**2:
        return f"{amount / 1024**2:.1f} MB/s"
    if amount >= 1024:
        return f"{amount / 1024:.0f} KB/s"
    return f"{int(amount)} B/s"


def fmt_eta(seconds: float) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "∞"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 86400}d {s % 86400 // 3600}h"


def fmt_limit(kib: int) -> str:
    return "∞" if kib <= 0 else f"{kib} KiB/s"
