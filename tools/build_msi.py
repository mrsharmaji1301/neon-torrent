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


# cloudflared for File Transfer over the internet, shipped inside Setup so a clean PC needs nothing else. Pinned: the
# official release from github.com/cloudflare/cloudflared, signed by Cloudflare, Inc.; the hash is the release's digest
CLOUDFLARED_VERSION = "2026.10.7"
CLOUDFLARED_SHA256 = "2493dbc168923bb3e59e5e7716f71deced92992eea9acd6e9d74f84ac7751343"
CLOUDFLARED_URL = ("https://github.com/cloudflare/cloudflared/releases/download/"
                   f"{CLOUDFLARED_VERSION}/cloudflared-windows-amd64.exe")


def cloudflared_exe() -> Path:
    """The pinned cloudflared in neon-build\\dl, downloaded once; its SHA-256 is checked on every build."""
    from hashlib import sha256
    from urllib.request import urlopen
    path = BUILD / "dl" / f"cloudflared-{CLOUDFLARED_VERSION}" / "cloudflared.exe"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(CLOUDFLARED_URL, timeout=120) as response:     # noqa: S310 (fixed https URL)
            path.write_bytes(response.read())
    digest = sha256(path.read_bytes()).hexdigest()
    if digest != CLOUDFLARED_SHA256:
        path.unlink()
        raise SystemExit(f"cloudflared {CLOUDFLARED_VERSION} has SHA-256 {digest}, expected {CLOUDFLARED_SHA256}")
    return path


def make_layout() -> None:
    if not (DIST / "NeonTorrent.exe").exists():
        raise SystemExit(f"{DIST / 'NeonTorrent.exe'} is missing: run without --no-compile first")
    shutil.rmtree(LAYOUT, ignore_errors=True)
    shutil.copytree(DIST, LAYOUT)
    (LAYOUT / "cloudflared").mkdir()
    shutil.copy2(cloudflared_exe(), LAYOUT / "cloudflared" / "cloudflared.exe")
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


SETUP_MAGIC = b"NEONMSI1"


def zig_exe() -> Path:
    """The Zig compiler Nuitka downloaded into nuitka-cache (also builds the setup launcher)."""
    found = sorted(BUILD.glob("nuitka-cache/downloads/pip/*/Lib/site-packages/ziglang/zig.exe"))
    if not found:
        raise SystemExit("Zig not found in nuitka-cache: run without --no-compile once")
    return found[-1]


def make_setup_exe(msi: Path, version: str) -> Path:
    """NEON-Torrent-Setup.exe: tools/setup_stub (NEON icon, version info) with the MSI appended. Windows shows every
    .msi with its generic installer icon; this exe is the file users see and double-click."""
    stub_dir, work = ROOT / "tools" / "setup_stub", WORK / "stub"
    work.mkdir(parents=True, exist_ok=True)
    numbers = ",".join((version.split(".") + ["0", "0", "0"])[:4])
    strings = {"CompanyName": "SharmaJi", "FileDescription": "NEON Torrent Setup", "FileVersion": version,
               "ProductName": "NEON Torrent", "ProductVersion": version, "LegalCopyright": "NEON Torrent",
               "OriginalFilename": "NEON-Torrent-Setup.exe",
               "Comments": "Free-to-use BitTorrent client with a built-in File Transfer module. Made by SharmaJi."}
    for source in (PACKAGING / "NeonTorrent.ico", stub_dir / "setup.manifest"):   # zig's rc compiler reads the
        shutil.copy2(source, work / source.name)                                   # resources next to the .rc
    rc = "\n".join([
        '1 ICON "NeonTorrent.ico"',
        '1 24 "setup.manifest"',
        "1 VERSIONINFO",
        f"FILEVERSION {numbers}", f"PRODUCTVERSION {numbers}",
        "FILEFLAGSMASK 0x3f", "FILEFLAGS 0x0", "FILEOS 0x40004", "FILETYPE 0x1", "FILESUBTYPE 0x0",
        "BEGIN", '  BLOCK "StringFileInfo"', "  BEGIN", '    BLOCK "040904B0"', "    BEGIN",
        *(f'      VALUE "{k}", "{v}"' for k, v in strings.items()),
        "    END", "  END", '  BLOCK "VarFileInfo"', "  BEGIN", '    VALUE "Translation", 0x409, 1200', "  END",
        "END", ""])
    (work / "setup.rc").write_text(rc, encoding="utf-8")
    stub = work / "NEON-Torrent-Setup-stub.exe"
    env = build_env()
    env.update(ZIG_GLOBAL_CACHE_DIR=str(BUILD / "zig-cache"), ZIG_LOCAL_CACHE_DIR=str(BUILD / "zig-cache" / "local"))
    run = subprocess.run([str(zig_exe()), "build-exe", str(stub_dir / "stub.c"), str(work / "setup.rc"),
                          "-target", "x86_64-windows-gnu", "-O", "ReleaseSmall", "-lc", "-luser32", "-lkernel32",
                          "--subsystem", "windows", "--name", "NEON-Torrent-Setup-stub", f"-femit-bin={stub}"],
                         cwd=work, env=env, capture_output=True, text=True)
    if run.returncode:
        raise SystemExit("setup launcher build failed:\n" + "\n".join((run.stdout + run.stderr).splitlines()[-30:]))
    setup = OUT / "NEON-Torrent-Setup.exe"
    payload = msi.read_bytes()
    setup.write_bytes(stub.read_bytes() + payload + len(payload).to_bytes(8, "little") + SETUP_MAGIC)
    return setup


def main() -> int:
    version = app_version()
    if "--no-compile" not in sys.argv:
        compile_app(version)
    make_layout()
    msi = run_wix(version)
    print(f"Built {msi} ({msi.stat().st_size / 2**20:.0f} MB), version {version}")
    setup = make_setup_exe(msi, version)
    print(f"Built {setup} ({setup.stat().st_size / 2**20:.0f} MB): the setup to share, with the NEON icon")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
