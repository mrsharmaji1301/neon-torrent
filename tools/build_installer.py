"""Build NEON-Torrent-Setup.exe: the self-contained app folder (as for the MSIX) packed by Inno Setup.

The installed copy keeps its data in <install dir>\\data (portable.ini), never in %APPDATA%.
Run with the project's venv interpreter: .venv\\Scripts\\python.exe tools\\build_installer.py
"""
from __future__ import annotations

import compileall
import os
import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_msix as base  # noqa: E402  (reuses its layout builders)

ROOT = base.ROOT
WORK = base.BUILD / "installer"
LAYOUT, OUT = WORK / "layout", WORK / "out"
ISCC = Path(os.environ.get("NEON_ISCC", str(base.BUILD / "tools" / "InnoSetup" / "ISCC.exe")))
EXTRA_PACKAGES = ("cryptography", "cffi", "pycparser", "segno")   # File Sharing: encryption and QR codes


def app_version() -> str:
    """APP_VERSION from the package, read as text (no app import): the one place the version is written."""
    text = (ROOT / "src" / "neontorrent" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION = "(\d+(?:\.\d+){0,3})"$', text, re.MULTILINE)
    if not match:
        raise SystemExit("APP_VERSION in src/neontorrent/__init__.py must look like 1.2.3")
    return match.group(1)


def main() -> int:
    base.LAYOUT = LAYOUT
    shutil.rmtree(LAYOUT, ignore_errors=True)
    LAYOUT.mkdir(parents=True)
    base.copy_python()
    base.copy_site_packages()
    site = LAYOUT / "site-packages"
    for pkg in EXTRA_PACKAGES:
        shutil.copytree(base.SITE / pkg, site / pkg, ignore=base.JUNK)
    for pyd in base.SITE.glob("_cffi_backend*.pyd"):
        shutil.copy2(pyd, site / pyd.name)
    base.copy_app()
    for name in ("THIRD-PARTY-NOTICES.md", "README.md"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, LAYOUT / name)
    (LAYOUT / "portable.ini").write_text("[NEON]\ndata=data\n", encoding="utf-8")
    compileall.compile_dir(LAYOUT, quiet=2, workers=0, stripdir=str(LAYOUT),
                           invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    files = [f for f in LAYOUT.rglob("*") if f.is_file()]
    print(f"Layout: {len(files)} files, {sum(f.stat().st_size for f in files) / 2**20:.0f} MB")
    OUT.mkdir(parents=True, exist_ok=True)
    version = app_version()
    run = subprocess.run([str(ISCC), "/Q", f"/DLayout={LAYOUT}", f"/DOutDir={OUT}", f"/DAppVer={version}",
                          str(ROOT / "packaging" / "NeonTorrent.iss")], capture_output=True, text=True)
    if run.returncode:
        raise SystemExit("Inno Setup failed:\n" + "\n".join((run.stdout + run.stderr).splitlines()[-25:]))
    setup = OUT / "NEON-Torrent-Setup.exe"
    print(f"Built {setup} ({setup.stat().st_size / 2**20:.0f} MB), version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
