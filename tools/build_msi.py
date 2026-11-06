"""Build NEON-Torrent-Setup.msi: the app compiled to a native NeonTorrent.exe (Nuitka), packed as a Windows Installer
package (WiX 3.14, packaging/NeonTorrent.wxs).

No Python install, no browser and no script launcher is needed on the PC: Nuitka compiles the code to C and ships
the Qt, libtorrent and cryptography DLLs next to the exe. The installed copy keeps its data in <install dir>\\data
(portable.ini).

Run with the project's venv interpreter:  .venv\\Scripts\\python.exe tools\\build_msi.py [--no-compile]
Tools (all under ..\\neon-build, never drive C:): Nuitka in nuitka-pkgs (pip install --target), Zig is downloaded by
Nuitka into nuitka-cache, WiX binaries in tools\\wix314.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from hashlib import sha1
from pathlib import Path
from xml.sax.saxutils import quoteattr

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_installer import app_version  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BUILD = Path(os.environ.get("NEON_BUILD", str(ROOT.parent / "neon-build")))
NUITKA_OUT, WORK = BUILD / "nuitka", BUILD / "msi"
DIST = NUITKA_OUT / "neon_torrent.dist"
LAYOUT, OUT = WORK / "layout", WORK / "out"
WIX = Path(os.environ.get("NEON_WIX", str(BUILD / "tools" / "wix314")))
PACKAGING = ROOT / "packaging"
GUID_NS = uuid.UUID("7C3E9A51-2B64-4F0D-9E18-6A2D5C4B3F71")     # the MSI UpgradeCode: stable component GUIDs
# per-machine shortcuts live in the all-users Start menu and Public Desktop, which these ICEs treat as user profile
SUPPRESSED_ICES = ("ICE38", "ICE43", "ICE57", "ICE64", "ICE91")


def build_env() -> dict[str, str]:
    env = dict(os.environ)
    tmp = str(BUILD / "tmp")
    env.update(TEMP=tmp, TMP=tmp, PIP_CACHE_DIR=str(BUILD / "pip-cache"), NUITKA_CACHE_DIR=str(BUILD / "nuitka-cache"),
               PYTHONPATH=str(BUILD / "nuitka-pkgs"))
    Path(tmp).mkdir(parents=True, exist_ok=True)
    return env


def compile_app(version: str) -> None:
    command = [
        sys.executable, "-m", "nuitka", "--standalone", "--zig", "--assume-yes-for-downloads",
        f"--output-dir={NUITKA_OUT}", "--output-filename=NeonTorrent.exe", "--windows-console-mode=disable",
        f"--windows-icon-from-ico={PACKAGING / 'NeonTorrent.ico'}", "--enable-plugin=pyside6",
        "--include-package=neontorrent",
        f"--include-data-dir={ROOT / 'src' / 'neontorrent' / 'share_web'}=neontorrent/share_web",
        "--company-name=SharmaJi", "--product-name=NEON Torrent", "--file-description=NEON Torrent",
        f"--file-version={version}", f"--product-version={version}", "--copyright=NEON Torrent", "--remove-output",
        str(ROOT / "src" / "neon_torrent.py"),
    ]
    if subprocess.run(command, cwd=ROOT, env=build_env()).returncode:
        raise SystemExit("Nuitka compile failed (see the output above)")


def make_layout() -> None:
    if not (DIST / "NeonTorrent.exe").exists():
        raise SystemExit(f"{DIST / 'NeonTorrent.exe'} is missing: run without --no-compile first")
    shutil.rmtree(LAYOUT, ignore_errors=True)
    shutil.copytree(DIST, LAYOUT)
    # Nuitka only bundles the VC++ runtime when Visual Studio is installed; the PySide6 wheel ships the same
    # redistributable DLLs, so the MSI runs on a PC without the VC++ Redistributable too
    pyside = Path(sys.prefix) / "Lib" / "site-packages" / "PySide6"
    for pattern in ("msvcp140*.dll", "vcruntime140*.dll", "concrt140.dll"):
        for dll in pyside.glob(pattern):
            if not (LAYOUT / dll.name).exists():
                shutil.copy2(dll, LAYOUT / dll.name)
    for name in ("THIRD-PARTY-NOTICES.md", "README.md"):
        if (ROOT / name).exists():
            shutil.copy2(ROOT / name, LAYOUT / name)
    shutil.copy2(PACKAGING / "NeonTorrent.ico", LAYOUT / "NeonTorrent.ico")
    (LAYOUT / "portable.ini").write_text("[NEON]\ndata=data\n", encoding="utf-8")


def ident(prefix: str, rel: str) -> str:
    return prefix + sha1(rel.lower().encode("utf-8")).hexdigest()[:24]


def write_files_wxs(path: Path) -> int:
    """One component per file (stable GUIDs from the relative path), NeonTorrent.exe as File Id NeonTorrentExe."""
    lines, refs = [], []

    def walk(folder: Path, depth: int) -> None:
        pad = "  " * depth
        for entry in sorted(folder.iterdir(), key=lambda p: (p.is_dir(), p.name.lower())):
            rel = entry.relative_to(LAYOUT).as_posix()
            if entry.is_dir():
                lines.append(f'{pad}<Directory Id="{ident("d", rel)}" Name={quoteattr(entry.name)}>')
                walk(entry, depth + 1)
                lines.append(f"{pad}</Directory>")
                continue
            component = ident("c", rel)
            file_id = "NeonTorrentExe" if rel == "NeonTorrent.exe" else ident("f", rel)
            guid = str(uuid.uuid5(GUID_NS, rel.lower())).upper()
            source = quoteattr("$(var.Layout)\\" + rel.replace("/", "\\"))
            lines.append(f'{pad}<Component Id="{component}" Guid="{{{guid}}}" Win64="yes">'
                         f'<File Id="{file_id}" Source={source} KeyPath="yes" /></Component>')
            refs.append(component)

    walk(LAYOUT, 3)
    text = "\n".join([
        '<?xml version="1.0" encoding="utf-8"?>',
        "<!-- generated by tools/build_msi.py; do not edit -->",
        '<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">',
        "  <Fragment>",
        '    <DirectoryRef Id="INSTALLFOLDER">', *lines, "    </DirectoryRef>",
        '    <ComponentGroup Id="AppFiles">', *(f'      <ComponentRef Id="{c}" />' for c in refs), "    </ComponentGroup>",
        "  </Fragment>",
        "</Wix>", ""])
    path.write_text(text, encoding="utf-8")
    return len(refs)


def write_rtf(source: Path, path: Path) -> None:
    """Plain text as RTF for the installer's scrollable pages: the agreement (packaging/PRIVACY.txt) on
    LicenseAgreementDlg and the update log (packaging/CHANGELOG.txt) on DetectedDlg."""
    text = source.read_text(encoding="utf-8")
    body = "".join(c if ord(c) < 128 else f"\\u{ord(c)}?" for c in
                   text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}"))
    path.write_text("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Segoe UI;}}\\f0\\fs18 " + body.replace("\n", "\\par\n") + "}",
                    encoding="ascii")


def run_wix(version: str) -> Path:
    obj = WORK / "obj"
    obj.mkdir(parents=True, exist_ok=True)
    files_wxs, rtf, changelog = WORK / "files.wxs", WORK / "privacy.rtf", WORK / "changelog.rtf"
    count = write_files_wxs(files_wxs)
    write_rtf(PACKAGING / "PRIVACY.txt", rtf)
    write_rtf(PACKAGING / "CHANGELOG.txt", changelog)
    ext = ["-ext", "WixUtilExtension", "-ext", "WixUIExtension"]
    defines = [f"-dLayout={LAYOUT}", f"-dAppVer={version}", f"-dPackaging={PACKAGING}", f"-dLicenseRtf={rtf}",
               f"-dChangelogRtf={changelog}"]
    steps = [
        [str(WIX / "candle.exe"), "-nologo", "-arch", "x64", *ext, *defines, "-out", f"{obj}\\",
         str(PACKAGING / "NeonTorrent.wxs"), str(files_wxs)],
        [str(WIX / "light.exe"), "-nologo", *ext, "-cultures:en-us", "-loc", str(PACKAGING / "NeonTorrent.en-us.wxl"), "-spdb",
         *(f"-sice:{ice}" for ice in SUPPRESSED_ICES), "-out", str(OUT / "NEON-Torrent-Setup.msi"),
         str(obj / "NeonTorrent.wixobj"), str(obj / "files.wixobj")],
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    for step in steps:
        run = subprocess.run(step, capture_output=True, text=True, env=build_env())
        if run.returncode:
            raise SystemExit(f"{Path(step[0]).name} failed:\n" + "\n".join((run.stdout + run.stderr).splitlines()[-30:]))
    print(f"MSI holds {count} files")
    return OUT / "NEON-Torrent-Setup.msi"


def main() -> int:
    version = app_version()
    if "--no-compile" not in sys.argv:
        compile_app(version)
    make_layout()
    msi = run_wix(version)
    print(f"Built {msi} ({msi.stat().st_size / 2**20:.0f} MB), version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
