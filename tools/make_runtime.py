"""Build runtime\\NeonTorrent.exe.

The app is pure Python, so normally every connection it makes is attributed to the shared python.exe:
Malwarebytes alerts say "Python", and allowing python.exe in an antivirus or firewall would allow every
Python program on the PC. This copies the (Python Software Foundation-signed) interpreter under the app's own
name, with a ._pth file that pins its module path to this project. Windows, the firewall and the antivirus then
see a separate NeonTorrent.exe that can be allowed or blocked on its own.

Run with the project's venv interpreter: .venv\\Scripts\\python.exe tools\\make_runtime.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
EXES = {"NeonTorrent.exe": "pythonw.exe", "NeonTorrent-console.exe": "python.exe"}


def main() -> int:
    base = Path(sys.base_prefix)
    site_packages = ROOT / ".venv" / "Lib" / "site-packages"
    if not (base / "pythonw.exe").exists() or not site_packages.is_dir():
        print(f"Cannot build runtime: base Python at {base} or {site_packages} is missing.")
        return 1
    RUNTIME.mkdir(exist_ok=True)
    dll = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    try:
        for name in ("python3.dll", dll, "vcruntime140.dll", "vcruntime140_1.dll"):
            if (base / name).exists():
                shutil.copy2(base / name, RUNTIME / name)
        paths = [base / "DLLs", base / "Lib", site_packages, ROOT / "src"]
        for exe, source in EXES.items():
            shutil.copy2(base / source, RUNTIME / exe)
            # <exe name>._pth replaces sys.path entirely and runs the interpreter in isolated mode
            (RUNTIME / exe).with_suffix("._pth").write_text("\n".join(str(p) for p in paths) + "\n", encoding="utf-8")
    except PermissionError:
        print("NeonTorrent is running; close it and run setup.bat again to rebuild the runtime.")
        return 1
    print(f"Built {RUNTIME / 'NeonTorrent.exe'} (Python {sys.version.split()[0]} from {base})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
