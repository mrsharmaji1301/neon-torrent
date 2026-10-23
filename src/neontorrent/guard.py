"""Download Guard: file-level safety for whatever a torrent contains.

A torrent client cannot make a malicious file safe, so the Guard works on the things a client *can* control:

* inspect   - before downloading, flag disguised executables (movie.mp4.exe), shortcuts (.lnk/.url),
              right-to-left-override name tricks, executables hidden in media torrents, symlinks, and skip
              them automatically (file priority 0 = never downloaded)
* mark      - stamp finished files with Mark-of-the-Web (Zone.Identifier ZoneId=3) so Windows SmartScreen and
              Office Protected View check them before they run, exactly like browser downloads
* scan      - scan finished downloads with Microsoft Defender when it is the active antivirus, and/or look up
              executables' SHA-256 on VirusTotal (hash only, never the file) when the user supplies an API key
Nothing in the client ever opens or executes a downloaded file.

Plain Python, no Qt; heavy work runs in worker threads started by the engine.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

EXECUTABLE = {".exe", ".msi", ".msp", ".msix", ".msixbundle", ".appx", ".appxbundle", ".bat", ".cmd", ".com",
              ".scr", ".pif", ".cpl", ".dll", ".sys", ".ocx", ".drv", ".efi"}
SCRIPT = {".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".jar", ".py", ".pyw",
          ".sh", ".reg", ".inf", ".application", ".appref-ms", ".gadget", ".msc", ".settingcontent-ms", ".xll",
          ".iqy", ".slk", ".chm", ".diagcab", ".cab"}
SHORTCUT = {".lnk", ".url", ".website", ".scf", ".library-ms", ".searchconnector-ms", ".desktop"}
MACRO_DOC = {".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".pptm", ".potm", ".ppam", ".sldm"}
MEDIA = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".ts", ".m2ts", ".mpg", ".mpeg", ".flv",
         ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".srt", ".ass", ".sub", ".idx", ".vtt",
         ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".nfo", ".txt", ".pdf", ".epub", ".mobi",
         ".azw3", ".cbz", ".cbr", ".djvu", ".doc", ".docx"}
RUNNABLE = EXECUTABLE | SCRIPT | SHORTCUT | MACRO_DOC
# Unicode bidi overrides/isolates and invisible characters used to disguise extensions (e.g. "moc.exe" -> "exe.com")
TRICK_CHARS = re.compile("[\u202a-\u202e\u2066-\u2069\u200b-\u200f\u2028\u2029\ufeff\u180e]")

RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"COM{i}" for i in range(10)} | {
    f"LPT{i}" for i in range(10)}

DANGER, CAUTION, CLEAN = "danger", "caution", "clean"
MOTW = "[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=about:internet\r\nHostUrl=about:internet\r\n"


def _suffixes(name: str) -> list[str]:
    return [s.lower() for s in PurePosixPath(name).suffixes]


def classify(path: str, media_torrent: bool, strict: bool, is_symlink: bool = False) -> tuple[str, str]:
    """(level, reason) for one file inside a torrent. path uses '/' separators."""
    name = path.rsplit("/", 1)[-1]
    if is_symlink:
        return DANGER, "Symbolic link (can point outside the download folder)"
    if TRICK_CHARS.search(path):
        return DANGER, "Hidden Unicode characters that disguise the real file type"
    stripped = name.rstrip(" .")
    if stripped != name:
        return DANGER, "Trailing dots or spaces that hide the real extension"
    if any(part.split(".")[0].upper() in RESERVED for part in path.split("/")):
        return DANGER, "Windows device name (CON, AUX, NUL…): creates an undeletable file"
    suffixes = _suffixes(name)
    ext = suffixes[-1] if suffixes else ""
    if ext in SHORTCUT:
        return DANGER, "Shortcut file (can launch any program)"
    if ext in RUNNABLE:
        earlier = suffixes[:-1]
        if any(s in MEDIA for s in earlier) or re.search(r"\s{3,}\.\w+$", name):
            return DANGER, f"Disguised {ext} (double extension)"
        if media_torrent:
            return DANGER, f"{ext} inside a media torrent (media never needs one)"
        if strict:
            return DANGER, f"{ext} (strict mode: no executables or scripts)"
        if ext in MACRO_DOC:
            return CAUTION, "Office document with macros"
        return CAUTION, f"{ext} — runs code; scanned when finished"
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        return DANGER, "Control characters in the file name"
    return CLEAN, ""


def inspect(files: list[dict], strict: bool) -> dict:
    """files: [{index, path, size, symlink}] (padding files excluded). Returns a verdict for the torrent."""
    total = sum(f["size"] for f in files) or 1
    media_bytes = sum(f["size"] for f in files if (_suffixes(f["path"]) or [""])[-1] in MEDIA)
    runnable = [f for f in files if (_suffixes(f["path"]) or [""])[-1] in RUNNABLE]
    # a "media torrent" is mostly video/audio/books by size and has no installer-sized executable
    media_torrent = media_bytes / total >= 0.8 and not any(f["size"] > 50 * 1024**2 for f in runnable)
    findings = {}
    for f in files:
        level, reason = classify(f["path"], media_torrent, strict, f.get("symlink", False))
        if level != CLEAN:
            findings[f["index"]] = {"level": level, "reason": reason, "path": f["path"]}
    levels = {v["level"] for v in findings.values()}
    verdict = DANGER if DANGER in levels else CAUTION if CAUTION in levels else CLEAN
    return {"level": verdict, "media": media_torrent, "findings": findings,
            "danger": sorted(i for i, v in findings.items() if v["level"] == DANGER),
            "runnable": sorted(i for i, v in findings.items() if v["level"] == CAUTION)}


# ---------------------------------------------------------------------------------------------- finishing

def mark_of_the_web(path: Path) -> bool:
    """Tag a finished file as downloaded from the internet (NTFS Zone.Identifier stream)."""
    try:
        with open(f"{path}:Zone.Identifier", "w", encoding="ascii") as stream:
            stream.write(MOTW)
        return True
    except OSError:
        return False


def has_mark_of_the_web(path: Path) -> bool:
    try:
        with open(f"{path}:Zone.Identifier", "r", encoding="ascii", errors="replace") as stream:
            return "ZoneId=3" in stream.read()
    except OSError:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def antivirus_products() -> list[str]:
    """Antivirus products registered with Windows Security Center."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct | "
             "ForEach-Object { $_.displayName }"],
            capture_output=True, text=True, timeout=20, creationflags=_no_window())
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def defender_cli() -> str | None:
    """MpCmdRun.exe if Microsoft Defender Antivirus is actually running (it is off when another AV is primary)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-MpComputerStatus -ErrorAction Stop).AntivirusEnabled"],
            capture_output=True, text=True, timeout=20, creationflags=_no_window())
        if out.stdout.strip().lower() != "true":
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    platform = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows Defender" / "Platform"
    candidates = sorted(platform.glob("*/MpCmdRun.exe"), reverse=True) if platform.is_dir() else []
    candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe")
    for exe in candidates:
        if exe.is_file():
            return str(exe)
    return None


def defender_scan(cli: str, target: Path) -> tuple[str, str]:
    """("clean"|"threat"|"error", detail). Defender quarantines what it finds by itself (remediation on)."""
    try:
        out = subprocess.run([cli, "-Scan", "-ScanType", "3", "-File", str(target)],
                             capture_output=True, text=True, timeout=3600, creationflags=_no_window())
    except (OSError, subprocess.SubprocessError) as exc:
        return "error", f"Defender scan failed: {exc}"
    text = (out.stdout or "") + (out.stderr or "")
    if out.returncode == 0:
        return "clean", "Microsoft Defender: no threats"
    if out.returncode == 2:
        threats = [line.strip() for line in text.splitlines() if line.strip().lower().startswith("threat")]
        return "threat", "Microsoft Defender: " + ("; ".join(threats[:3]) or "threat found")
    return "error", f"Defender exit code {out.returncode}"


def virustotal_lookup(sha256: str, api_key: str) -> tuple[str, str]:
    """('clean'|'threat'|'unknown'|'error', detail). Sends only the hash."""
    request = urllib.request.Request(f"https://www.virustotal.com/api/v3/files/{sha256}",
                                     headers={"x-apikey": api_key, "User-Agent": "NeonTorrent/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return "unknown", "VirusTotal has never seen this file"
        if exc.code in (401, 403):
            return "error", "VirusTotal API key rejected"
        if exc.code == 429:
            return "error", "VirusTotal rate limit reached"
        return "error", f"VirusTotal HTTP {exc.code}"
    except (OSError, ValueError) as exc:
        return "error", f"VirusTotal unreachable ({exc.__class__.__name__})"
    stats = data.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
    bad = int(stats.get("malicious", 0))
    suspicious = int(stats.get("suspicious", 0))
    engines = sum(int(v) for v in stats.values()) or 1
    if bad >= 3:
        return "threat", f"VirusTotal: {bad}/{engines} engines detect it"
    if bad or suspicious:
        return "clean", f"VirusTotal: {bad} malicious / {suspicious} suspicious of {engines} (likely false positive)"
    return "clean", f"VirusTotal: clean on {engines} engines"


def finish(files: list[Path], runnable: list[Path], root: Path, options: dict) -> dict:
    """Runs in a worker thread when a torrent completes. Never opens or executes the files."""
    result = {"time": int(time.time()), "marked": 0, "scan": "unscanned", "detail": [], "threats": []}
    if options.get("motw", True):
        result["marked"] = sum(mark_of_the_web(path) for path in files if path.is_file())
    statuses = []
    cli = defender_cli() if options.get("scan", True) else None
    if cli:
        status, detail = defender_scan(cli, root)
        statuses.append(status)
        result["detail"].append(detail)
        if status == "threat":
            result["threats"].append(detail)
    key = (options.get("vt_key") or "").strip()
    if key and options.get("scan", True):
        for i, path in enumerate(runnable[:8]):
            if not path.is_file():
                continue
            if i:
                time.sleep(16)                     # free API: 4 lookups per minute
            status, detail = virustotal_lookup(sha256_file(path), key)
            statuses.append(status if status != "unknown" else "clean")
            result["detail"].append(f"{path.name}: {detail}")
            if status == "threat":
                result["threats"].append(f"{path.name}: {detail}")
    if result["threats"]:
        result["scan"] = "threat"
    elif statuses and all(s == "clean" for s in statuses):
        result["scan"] = "clean"
    elif statuses:
        result["scan"] = "partial"
    if not cli and options.get("scan", True):
        av = ", ".join(p for p in antivirus_products() if "defender" not in p.lower()) or "your antivirus"
        result["detail"].append(f"Microsoft Defender is off; files are covered by {av} real-time protection")
    return result
