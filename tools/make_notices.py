"""Build THIRD-PARTY-NOTICES.md from the licence files of everything the app package ships.

Sources are the real licence texts: the base Python's LICENSE.txt and Doc/html/license.html, the installed package
versions, and the verbatim texts in packaging/licenses/ (LGPL-3.0 and GPL-3.0 for Qt and PySide6, libtorrent's
LICENSE from its v2.1.1 tag, and the Boost licence). Run it again whenever Python, PySide6 or libtorrent changes.

Run with the project's venv interpreter: .venv\\Scripts\\python.exe tools\\make_notices.py
"""
from __future__ import annotations

import re
import ssl
import sys
from html.parser import HTMLParser
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSES = ROOT / "packaging" / "licenses"
OUT = ROOT / "THIRD-PARTY-NOTICES.md"
BASE = Path(sys.base_prefix)
TCL_START = "This software is copyrighted by the Regents of the University"  # Tcl/Tk is not shipped


class SectionText(HTMLParser):
    """Plain text of one <section id=...> of the Python docs, keeping <pre> blocks as they are."""

    def __init__(self, section_id: str):
        super().__init__(convert_charrefs=True)
        self.section_id, self.depth, self.pre = section_id, 0, 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            if tag == "section":
                self.depth += 1
            elif tag == "pre":
                self.pre += 1
                self.parts.append("\n\n")
            elif tag in ("p", "h2", "h3", "li"):
                self.parts.append("\n\n")
        elif tag == "section" and dict(attrs).get("id") == self.section_id:
            self.depth = 1

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "section":
            self.depth -= 1
        elif tag == "pre":
            self.pre -= 1
            self.parts.append("\n")

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data if self.pre else re.sub(r"\s+", " ", data))

    def text(self) -> str:
        lines = "".join(self.parts).replace("¶", "").splitlines()
        return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in lines)).strip()


def fenced(text: str) -> str:
    return "```text\n" + text.strip("\n") + "\n```"


def python_license() -> str:
    text = (BASE / "LICENSE.txt").read_text(encoding="utf-8")
    cut = text.find(TCL_START)
    return text[:cut] if cut > 0 else text


def python_incorporated() -> str:
    parser = SectionText("licenses-and-acknowledgements-for-incorporated-software")
    parser.feed((BASE / "Doc" / "html" / "license.html").read_text(encoding="utf-8"))
    return parser.text()


def openssl_in_libtorrent() -> str:
    blob = next((Path(sys.prefix) / "Lib" / "site-packages" / "libtorrent").glob("*.pyd")).read_bytes()
    found = re.search(rb"OpenSSL (\d+\.\d+\.\d+)", blob)
    return found.group(1).decode() if found else "3"


def build() -> str:
    py = ".".join(map(str, sys.version_info[:3]))
    qt, lt = version("PySide6-Essentials"), version("libtorrent")
    py_ssl = ssl.OPENSSL_VERSION.split()[1]
    rows = [
        ("Python (CPython runtime and standard library)", py,
         "PSF License 2.0, plus the licences of the code it includes (below)"),
        ("Qt (Core, Gui, Widgets, Network and their plugins)", qt, "LGPL-3.0"),
        ("PySide6 and Shiboken6 (Qt for Python)", qt, "LGPL-3.0"),
        ("libtorrent-rasterbar and its Python bindings", lt, "BSD-3-Clause; some files zlib or public domain"),
        ("Boost (built into libtorrent)", "", "Boost Software License 1.0"),
        ("OpenSSL (built into libtorrent)", openssl_in_libtorrent(), "Apache-2.0"),
        ("OpenSSL (Python's ssl and hashlib modules)", py_ssl, "Apache-2.0"),
        ("libffi, bzip2, zlib, expat, libmpdec, mimalloc and others in Python", "",
         "MIT, BSD-style and zlib licences (below)"),
        ("xz / liblzma (Python's lzma module)", "", "Public domain"),
        ("SQLite (Python's sqlite3 module)", "", "Public domain"),
        ("Microsoft Visual C++ runtime (vcruntime140, msvcp140 and related DLLs)", "",
         "Microsoft Visual Studio Distributable Code"),
    ]
    table = "\n".join(f"| {name} | {ver} | {lic} |" for name, ver, lic in rows)
    return f"""# Third-party notices

NEON Torrent is built on the open-source software below. Each component keeps its own licence; NEON's own code is
not covered by these licences. This file ships inside the app package and is shown in Preferences → About.

| Component | Version | Licence |
|---|---|---|
{table}

## Qt, PySide6 and Shiboken6 (LGPL-3.0)

NEON uses Qt {qt} and Qt for Python (PySide6, Shiboken6) {qt} from The Qt Company under the GNU Lesser General Public
License version 3. They are unmodified and loaded at run time as separate files (`Qt6*.dll`, `pyside6.abi3.dll`,
`shiboken6.abi3.dll`, the `PySide6` and `shiboken6` Python packages and the Qt plugins), so you may replace them with
your own builds of the same interface: copy NEON's install folder to a folder you can write to, replace those files,
and run `NeonTorrent.exe` from there. NEON's Python code ships as readable `.py` files next to them.

Source code for these exact versions:
- Qt: https://download.qt.io/official_releases/qt/ (version {qt}) and https://code.qt.io/
- PySide6 and Shiboken6: https://download.qt.io/official_releases/QtForPython/ (version {qt}) and
  https://code.qt.io/cgit/pyside/pyside-setup.git/

Qt itself contains third-party code (for example zlib, libpng, libjpeg-turbo, libtiff, libwebp, FreeType, HarfBuzz,
PCRE2 and double-conversion) under permissive licences listed at https://doc.qt.io/qt-6/licenses-used-in-qt.html.

The full LGPL-3.0 text follows, then the GPL-3.0 text that it builds on.

{fenced((LICENSES / "LGPL-3.0.txt").read_text(encoding="utf-8"))}

{fenced((LICENSES / "GPL-3.0.txt").read_text(encoding="utf-8"))}

## libtorrent {lt}

Source: https://github.com/arvidn/libtorrent (tag v{lt}). Its LICENSE file:

{fenced((LICENSES / "libtorrent-2.1.1-LICENSE.txt").read_text(encoding="utf-8"))}

## Boost

{fenced((LICENSES / "BSL-1.0.txt").read_text(encoding="utf-8"))}

## OpenSSL

OpenSSL is licensed under the Apache License 2.0; its full text is part of the Python licence file below.

## Python {py}

NEON runs on its own copy of the Python {py} runtime. Python's licence file (LICENSE.txt), including the conditions
for the Microsoft Visual C++ runtime in this Windows build and the licences of bzip2, libffi and OpenSSL:

{fenced(python_license())}

### Software incorporated into Python

From the Python {py} documentation (Doc/html/license.html):

{fenced(python_incorporated())}

## xz / liblzma and SQLite

liblzma from XZ Utils (used by Python's lzma module) and SQLite (used by Python's sqlite3 module) are in the public
domain.

## Microsoft Visual C++ runtime

`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140*.dll` and `concrt140.dll` are Microsoft Visual C++ Redistributable
files, shipped as Distributable Code under the Microsoft Visual Studio licence terms. The conditions that apply to
them are in the Python licence file above ("Additional Conditions for this Windows binary build").
"""


def main() -> int:
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
