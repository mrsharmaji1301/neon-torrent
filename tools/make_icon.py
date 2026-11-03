"""Write packaging/NeonTorrent.ico (16 to 256 px, PNG entries) from the app's own logo painter.

Run with the project's venv interpreter: .venv\\Scripts\\python.exe tools\\make_icon.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "packaging" / "NeonTorrent.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

    from neontorrent import theme as T
    from neontorrent.icons import paint_logo

    _app = QGuiApplication.instance() or QGuiApplication([])
    images = []
    for size in SIZES:
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pad = size * 0.04
        paint_logo(p, QRectF(pad, pad, size - 2 * pad, size - 2 * pad), T.c("cyan"), T.c("magenta"))
        p.end()
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        images.append((size, bytes(data)))
    # ICO container: header, one directory entry per size, then the PNG payloads
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, png in images:
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    out += b"".join(png for _size, png in images)
    OUT.write_bytes(out)
    print(f"Wrote {OUT} ({len(out) // 1024} KB, sizes {SIZES})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
