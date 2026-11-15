"""The video tools NEON ships in its `media` folder, pinned to official releases and checked by SHA-256:

  yt-dlp.exe   github.com/yt-dlp/yt-dlp           finds a video page's streams and downloads them
  deno.exe     github.com/denoland/deno           the JavaScript runtime yt-dlp needs for YouTube (no permissions)
  ffmpeg.exe   github.com/yt-dlp/FFmpeg-Builds    joins a video stream and its audio into one file (+ its DLLs)

``python tools/media_tools.py`` downloads them into neon-build\\dl\\media (once) and prints the folder. The build and
the development copy of NEON use that folder; Setup installs it as `media` next to NeonTorrent.exe.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import zipfile
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get("NEON_BUILD", str(ROOT.parent / "neon-build")))

YTDLP_VERSION = "2026.10.26"
DENO_VERSION = "2.9.8"
FFMPEG_TAG = "autobuild-2026-11-14-19-15"
FFMPEG_NAME = "ffmpeg-N-128911-gbcbc183264-win64-gpl-shared"
TOOLS = [
    ("yt-dlp.exe", f"https://github.com/yt-dlp/yt-dlp/releases/download/{YTDLP_VERSION}/yt-dlp.exe",
     "f5389d3698ecde4ef06f4e6b1ce0294fe9ac1396228c8990b8d3416d6d177a7d"),
    ("deno.zip", f"https://github.com/denoland/deno/releases/download/v{DENO_VERSION}/deno-x86_64-pc-windows-msvc.zip",
     "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf"),
    ("ffmpeg.zip", f"https://github.com/yt-dlp/FFmpeg-Builds/releases/download/{FFMPEG_TAG}/{FFMPEG_NAME}.zip",
     "57250225de1b061885fd1a4f410ae93970e55a562c5cd8a8a4a0318ee49326b5"),
]
FOLDER = BUILD / "dl" / f"media-{YTDLP_VERSION}-{DENO_VERSION}-{FFMPEG_TAG[10:20]}"


def _fetch(url: str, expected: str) -> bytes:
    with urlopen(url, timeout=300) as response:                       # noqa: S310 (fixed https URLs)
        data = response.read()
    digest = sha256(data).hexdigest()
    if digest != expected:
        raise SystemExit(f"{url} has SHA-256 {digest}, expected {expected}")
    return data


def media_folder() -> Path:
    """The pinned tools, downloaded once into neon-build\\dl; yt-dlp.exe's SHA-256 is checked on every call."""
    done = FOLDER / "yt-dlp.exe"
    if not (done.is_file() and (FOLDER / "deno.exe").is_file() and (FOLDER / "ffmpeg.exe").is_file()):
        shutil.rmtree(FOLDER, ignore_errors=True)
        work = FOLDER.with_name(FOLDER.name + ".part")
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        for name, url, expected in TOOLS:
            data = _fetch(url, expected)
            if name == "yt-dlp.exe":
                (work / name).write_bytes(data)
            elif name == "deno.zip":
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    (work / "deno.exe").write_bytes(archive.read("deno.exe"))
            else:                                      # ffmpeg.exe and the DLLs it loads; not ffplay/ffprobe
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for entry in archive.namelist():
                        leaf = entry.rsplit("/", 1)[-1]
                        if "/bin/" in entry and (leaf == "ffmpeg.exe" or leaf.endswith(".dll")):
                            (work / leaf).write_bytes(archive.read(entry))
                        elif entry.endswith("/LICENSE.txt"):
                            (work / "FFMPEG-LICENSE.txt").write_bytes(archive.read(entry))
        work.rename(FOLDER)
    if sha256(done.read_bytes()).hexdigest() != TOOLS[0][2]:
        shutil.rmtree(FOLDER, ignore_errors=True)
        raise SystemExit("the cached yt-dlp.exe changed; it was deleted, run again")
    return FOLDER


if __name__ == "__main__":
    folder = media_folder()
    total = sum(p.stat().st_size for p in folder.iterdir())
    print(folder, f"{total / 1048576:.0f} MB", file=sys.stdout)
