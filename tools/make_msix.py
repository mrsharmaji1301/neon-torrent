"""Build the MSIX package: a self-contained app folder, packed into NeonTorrent.msix.

The package carries its own interpreter (pythonw.exe under the app's name, as in tools/make_runtime.py), the standard
library and only the Qt parts the app loads, so users never install or see Python. Microsoft signs the package during
Store certification. For a local install test, --sandbox signs it with a throwaway certificate inside Windows Sandbox,
installs and launches it there, and prints the report; nothing is installed on this PC.

Run with the project's venv interpreter: .venv\\Scripts\\python.exe tools\\make_msix.py [--sandbox]
"""
from __future__ import annotations

import argparse
import compileall
import os
import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
BUILD = Path(os.environ.get("NEON_BUILD", r"F:\neon-build"))
WORK = BUILD / "msix"
LAYOUT, OUT, RESULTS = WORK / "layout", WORK / "out", WORK / "results"
SDK_BIN = BUILD / "tools" / "sdk-buildtools" / "bin" / "10.0.28000.0" / "x64"
SITE = ROOT / ".venv" / "Lib" / "site-packages"

QT_MODULES = ("Core", "Gui", "Widgets", "Network")  # everything src/ imports from PySide6
QT_PLUGINS = ("platforms", "styles", "imageformats", "iconengines")
LIB_SKIP = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "ensurepip", "venv", "__pycache__",
            "turtle.py"}
DLL_SKIP = {"_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "py.ico", "pyc.ico"}
JUNK = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyi")
ASSETS = {"Square150x150Logo": (150, 150), "Square44x44Logo": (44, 44), "StoreLogo": (50, 50),
          "Wide310x150Logo": (310, 150)}


def skip(names: set[str]):
    return lambda _dir, entries: [e for e in entries if e in names]


def copy_python() -> None:
    base = Path(sys.base_prefix)
    dll = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    for name in ("python3.dll", dll, "vcruntime140.dll", "vcruntime140_1.dll"):
        if (base / name).exists():
            shutil.copy2(base / name, LAYOUT / name)
    shutil.copy2(base / "pythonw.exe", LAYOUT / "NeonTorrent.exe")
    # relative entries resolve against the ._pth file, so the package works wherever Windows installs it
    (LAYOUT / "NeonTorrent._pth").write_text("DLLs\nLib\nsite-packages\nsrc\n", encoding="utf-8")
    shutil.copytree(base / "DLLs", LAYOUT / "DLLs", ignore=skip(DLL_SKIP))
    shutil.copytree(base / "Lib", LAYOUT / "Lib", ignore=skip(LIB_SKIP))


def copy_site_packages() -> None:
    qt, dest = SITE / "PySide6", LAYOUT / "site-packages" / "PySide6"
    dest.mkdir(parents=True)
    wanted = {f"Qt{m}.pyd" for m in QT_MODULES} | {f"Qt6{m}.dll" for m in QT_MODULES} | {"pyside6.abi3.dll"}
    for f in qt.iterdir():
        runtime = f.name.lower().startswith(("msvcp140", "vcruntime140", "concrt140"))
        if f.is_file() and (f.name in wanted or f.suffix == ".py" or runtime):
            shutil.copy2(f, dest / f.name)
    shutil.copytree(qt / "support", dest / "support", ignore=JUNK)
    for plugin in QT_PLUGINS:
        shutil.copytree(qt / "plugins" / plugin, dest / "plugins" / plugin)
    for pkg in ("shiboken6", "libtorrent"):
        shutil.copytree(SITE / pkg, LAYOUT / "site-packages" / pkg, ignore=JUNK)


def copy_app() -> None:
    (LAYOUT / "src").mkdir()
    shutil.copy2(ROOT / "src" / "neon_torrent.py", LAYOUT / "src" / "neon_torrent.py")
    shutil.copytree(ROOT / "src" / "neontorrent", LAYOUT / "src" / "neontorrent",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.rs", "graphify-out"))
    # licence texts for everything above (tools/make_notices.py); the About dialog shows this file
    shutil.copy2(ROOT / "THIRD-PARTY-NOTICES.md", LAYOUT / "THIRD-PARTY-NOTICES.md")


def render_assets() -> None:
    """Tile and Store logos drawn by the app's own logo painter."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

    from neontorrent import theme as T
    from neontorrent.icons import paint_logo

    _app = QGuiApplication.instance() or QGuiApplication([])
    (LAYOUT / "Assets").mkdir()
    for name, (w, h) in ASSETS.items():
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(w, h) * 0.86
        paint_logo(p, QRectF((w - side) / 2, (h - side) / 2, side, side), T.c("cyan"), T.c("magenta"))
        p.end()
        img.save(str(LAYOUT / "Assets" / f"{name}.png"))


def write_manifest(name: str, publisher: str, publisher_display: str, version: str) -> None:
    text = (ROOT / "packaging" / "AppxManifest.xml").read_text(encoding="utf-8")
    values = {"@NAME@": name, "@PUBLISHER@": publisher, "@PUBLISHER_DISPLAY@": publisher_display, "@VERSION@": version}
    for token, value in values.items():
        text = text.replace(token, escape(value, {'"': "&quot;"}))
    (LAYOUT / "AppxManifest.xml").write_text(text, encoding="utf-8")


def pack() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    msix = OUT / "NeonTorrent.msix"
    run = subprocess.run([str(SDK_BIN / "makeappx.exe"), "pack", "/d", str(LAYOUT), "/p", str(msix), "/o"],
                         capture_output=True, text=True)
    if run.returncode:
        raise SystemExit("makeappx failed:\n" + "\n".join((run.stdout + run.stderr).splitlines()[-25:]))
    return msix


def sandbox_test() -> int:
    """Sign, install and launch the package inside Windows Sandbox, streaming its report."""
    shutil.rmtree(RESULTS, ignore_errors=True)
    RESULTS.mkdir(parents=True)
    shutil.copy2(ROOT / "packaging" / "sandbox_test.ps1", OUT / "sandbox_test.ps1")
    folders = [(OUT, r"C:\msix", True), (SDK_BIN, r"C:\sdk", True), (RESULTS, r"C:\results", False)]
    mapped = "".join(f"<MappedFolder><HostFolder>{h}</HostFolder><SandboxFolder>{s}</SandboxFolder>"
                     f"<ReadOnly>{str(ro).lower()}</ReadOnly></MappedFolder>" for h, s, ro in folders)
    wsb = WORK / "sandbox.wsb"
    wsb.write_text(f"<Configuration><Networking>Disable</Networking><MappedFolders>{mapped}</MappedFolders>"
                   r"<LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
                   r"C:\msix\sandbox_test.ps1</Command></LogonCommand></Configuration>", encoding="utf-8")
    os.startfile(wsb)
    log, seen, start = RESULTS / "sandbox.log", 0, time.time()
    while time.time() - start < 600:
        time.sleep(5)
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else []
        for line in lines[seen:]:
            print(line, flush=True)
        seen = len(lines)
        if lines and lines[-1].endswith(" end"):
            return 0 if any(" RUNNING " in f" {line} " for line in lines) else 1
        if not lines and int(time.time() - start) % 30 < 5:
            print(f"waiting for the sandbox... {int(time.time() - start)} s", flush=True)
    print("Sandbox test timed out after 10 minutes.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="NeonTorrent", help="package identity name (Partner Center gives the Store one)")
    ap.add_argument("--publisher", default="CN=NEON Torrent Test", help="publisher subject (Partner Center: CN=<GUID>)")
    ap.add_argument("--publisher-display", default="NEON")
    ap.add_argument("--version", default="1.0.0.0")
    ap.add_argument("--sandbox", action="store_true", help="install and launch the package in Windows Sandbox")
    args = ap.parse_args()

    started = time.time()
    shutil.rmtree(LAYOUT, ignore_errors=True)
    LAYOUT.mkdir(parents=True)
    copy_python()
    copy_site_packages()
    copy_app()
    render_assets()
    write_manifest(args.name, args.publisher, args.publisher_display, args.version)
    # unchecked-hash .pyc files load without comparing source timestamps, which MSIX installs do not keep
    compileall.compile_dir(LAYOUT, quiet=2, workers=0, stripdir=str(LAYOUT),
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    files = [f for f in LAYOUT.rglob("*") if f.is_file()]
    print(f"Layout: {len(files)} files, {sum(f.stat().st_size for f in files) / 2**20:.0f} MB")
    msix = pack()
    print(f"Built {msix} ({msix.stat().st_size / 2**20:.0f} MB) in {time.time() - started:.0f} s")
    return sandbox_test() if args.sandbox else 0


if __name__ == "__main__":
    raise SystemExit(main())
