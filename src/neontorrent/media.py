"""Videos from web pages (YouTube and the other sites yt-dlp knows): NEON asks the bundled yt-dlp what a page's
video is, offers its qualities, and downloads the chosen one through the Downloads queue.

Tools (Setup installs them in `media` next to NeonTorrent.exe; a source checkout uses tools/media_tools.py's folder):
  yt-dlp.exe  reads the page and fetches the streams; run with --ignore-config and --no-plugin-dirs, so nothing on
              this PC changes what it does, and the link always comes after "--", so it can never be an option
  deno.exe    the JavaScript runtime yt-dlp runs YouTube's player code in; yt-dlp gives it no permissions
  ffmpeg.exe  joins the video stream and its audio into one file
yt-dlp's cache and Deno's cache live in NEON's data folder. A finished video gets Mark-of-the-Web like every other
download; a "video" that turns out to be a program is deleted.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import web

PROBE_TIMEOUT = 120
# sites whose pages are videos: pasted links to them go straight to the video window
VIDEO_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "vimeo.com", "dailymotion.com", "dai.ly",
               "twitch.tv", "x.com", "twitter.com", "instagram.com", "facebook.com", "fb.watch", "reddit.com",
               "redd.it", "tiktok.com", "soundcloud.com", "bilibili.com", "rumble.com", "odysee.com",
               "streamable.com", "bandcamp.com", "ted.com", "archive.org/details")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class MediaError(Exception):
    pass


@dataclass
class Choice:
    label: str                 # "1080p · MP4", "Audio only · M4A"
    selector: str              # yt-dlp -f
    size: int = -1             # bytes, -1 when the site does not say
    audio_only: bool = False


@dataclass
class VideoInfo:
    url: str                   # the page
    title: str
    duration: float = 0.0
    uploader: str = ""
    site: str = ""
    choices: list[Choice] = field(default_factory=list)


def tools_folder() -> Path | None:
    """The folder with yt-dlp.exe, deno.exe and ffmpeg.exe, or None when NEON was installed without them."""
    from .theme import app_exe
    candidates = [app_exe().parent / "media"]
    build = Path(__file__).resolve().parents[3] / "neon-build" / "dl"
    if build.is_dir():
        candidates += sorted(build.glob("media-*"), reverse=True)
    for folder in candidates:
        if all((folder / name).is_file() for name in ("yt-dlp.exe", "deno.exe", "ffmpeg.exe")):
            return folder
    return None


def is_video_site(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    where = host + parts.path.lower()
    return any(host == h or host.endswith("." + h) or where.startswith(h) or where.startswith("www." + h)
               for h in VIDEO_HOSTS)


def _env(cache: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["DENO_DIR"] = str(cache / "deno")                # Deno's cache with NEON's data, not in the user profile
    env["DENO_NO_UPDATE_CHECK"] = "1"
    env.pop("YTDLP_CONFIG", None)
    return env


def base_command(tools: Path, cache: Path) -> list[str]:
    return [str(tools / "yt-dlp.exe"), "--ignore-config", "--no-plugin-dirs", "--no-playlist",
            # only the bundled Deno (never a node/bun on PATH); YouTube's scripts come inside yt-dlp.exe, never fetched
            "--no-js-runtimes", "--js-runtimes", f"deno:{tools / 'deno.exe'}", "--no-remote-components",
            "--ffmpeg-location", str(tools), "--cache-dir", str(cache / "yt-dlp"), "--no-mtime",
            "--windows-filenames", "--encoding", "utf-8"]


def probe(url: str, cache: Path) -> VideoInfo:
    """The page's video: title and the qualities it comes in (yt-dlp -J). Raises MediaError."""
    url = web.check_url(url)
    tools = tools_folder()
    if tools is None:
        raise MediaError("NEON's video tools are missing (reinstall NEON Torrent to restore them)")
    cache.mkdir(parents=True, exist_ok=True)
    try:
        done = subprocess.run(base_command(tools, cache) + ["-J", "--", url], capture_output=True,
                              timeout=PROBE_TIMEOUT, env=_env(cache), creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise MediaError("the site took too long to answer") from None
    except OSError as exc:
        raise MediaError(f"the video tools did not start: {exc.strerror or exc}") from None
    if done.returncode:
        raise MediaError(error_line(done.stderr.decode("utf-8", "replace")) or "no video found on that page")
    try:
        data = json.loads(done.stdout.decode("utf-8", "replace"))
    except ValueError:
        raise MediaError("the video tools sent an unexpected answer") from None
    return info_from_json(url, data)


def error_line(stderr: str) -> str:
    """yt-dlp's last ERROR line, without its prefix."""
    for line in reversed(stderr.splitlines()):
        if line.startswith("ERROR:"):
            text = line[6:].strip()
            if "] " in text and text.startswith("["):                # "[youtube] <video id>: <message>"
                text = text.split("] ", 1)[1]
                head, sep, rest = text.partition(": ")
                if sep and rest and " " not in head:
                    text = rest
            return text[:300]
    return ""


def _size(fmt: dict) -> int:
    value = fmt.get("filesize") or fmt.get("filesize_approx")
    return int(value) if isinstance(value, (int, float)) and value > 0 else -1


def info_from_json(url: str, data: dict) -> VideoInfo:
    if data.get("_type") == "playlist" and data.get("entries"):
        data = next((e for e in data["entries"] if isinstance(e, dict)), data)
    formats = [f for f in data.get("formats") or [] if isinstance(f, dict)]
    if not formats and data.get("url"):
        formats = [data]
    if not formats:
        raise MediaError("no video found on that page")
    video = [f for f in formats if f.get("vcodec") != "none" and f.get("ext") != "mhtml"]    # unknown codec: a video
    audio = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    def audio_rank(f: dict) -> tuple:                  # plain stereo AAC first: it plays everywhere
        return (f.get("ext") == "m4a", "drc" not in str(f.get("format_id", "")),
                (f.get("audio_channels") or 2) <= 2, f.get("protocol") == "https", f.get("abr") or 0)

    def video_rank(f: dict) -> tuple:                  # one file over https, MP4 (H.264 first), then bitrate
        return (f.get("protocol") in ("https", "http"), f.get("ext") == "mp4",
                str(f.get("vcodec", "")).startswith("avc1"), _size(f) > 0, f.get("tbr") or 0)
    best_audio = max(audio, key=audio_rank, default=None)
    heights = sorted({int(f["height"]) for f in video if isinstance(f.get("height"), (int, float)) and f["height"] > 0},
                     reverse=True)
    choices = []
    for h in heights:
        pick = max((f for f in video if f.get("height") == h), key=video_rank)
        alone = pick.get("acodec") not in (None, "none")
        size = _size(pick)
        if not alone and best_audio is not None:
            size = size + _size(best_audio) if size > 0 and _size(best_audio) > 0 else -1
        fps = pick.get("fps")
        name = next((n for least, n in ((4320, "8K"), (2160, "4K"), (1440, "2K"), (1080, "Full HD"), (720, "HD"))
                     if h >= least), "")
        label = f"{h}p" + (f"{int(fps)}" if isinstance(fps, (int, float)) and fps > 30 else "") + \
            (f" · {name}" if name else "")
        exact = pick["format_id"] if alone or best_audio is None else f"{pick['format_id']}+{best_audio['format_id']}"
        # the exact streams shown here; if the site changed them since (a resume days later), the same height
        choices.append(Choice(label, f"{exact}/bv*[height={h}]+ba/b[height={h}]/bv*[height<={h}]+ba/b", size))
    if not heights:
        choices.append(Choice("Best quality", "bv*+ba/b", -1))
    if best_audio is not None:
        choices.append(Choice("Audio", f"{best_audio['format_id']}/ba[ext=m4a]/ba", _size(best_audio),
                              audio_only=True))
    title = " ".join(str(data.get("title") or "video").split())[:200]
    return VideoInfo(str(data.get("webpage_url") or url), title, float(data.get("duration") or 0),
                     str(data.get("uploader") or data.get("channel") or ""),
                     {"Youtube": "YouTube"}.get(str(data.get("extractor_key") or ""),
                                                str(data.get("extractor_key") or data.get("extractor") or "")),
                     choices)


@dataclass(frozen=True)
class Format:
    ext: str                   # the saved file's extension
    label: str
    audio: bool                # audio only
    copy_first: bool           # try keeping the streams as they are (fast) before converting
    codec: tuple = ()          # ffmpeg arguments when converting
    bitrates: bool = False     # the user picks a bitrate (lossy audio)


X264 = ("-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k")
FORMATS = [
    Format("mp4", "MP4 · plays everywhere", False, True, X264 + ("-movflags", "+faststart")),
    Format("mkv", "MKV", False, True, X264),
    Format("mov", "MOV · Apple", False, True, X264 + ("-movflags", "+faststart")),
    Format("avi", "AVI · old players", False, False, ("-c:v", "libxvid", "-q:v", "4", "-c:a", "libmp3lame",
                                                     "-q:a", "2")),
    Format("mpg", "MPEG · DVD players", False, False, ("-c:v", "mpeg2video", "-q:v", "3", "-c:a", "mp2", "-b:a",
                                                      "224k", "-f", "mpeg")),
    Format("webm", "WEBM", False, True, ("-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1",
                                         "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus", "-b:a",
                                         "128k")),
    Format("flv", "FLV", False, True, X264),
    Format("mp3", "MP3 · audio only", True, False, ("-c:a", "libmp3lame"), bitrates=True),
    Format("m4a", "M4A (AAC) · audio only", True, True, ("-c:a", "aac", "-b:a", "256k")),
    Format("opus", "OPUS · audio only", True, True, ("-c:a", "libopus"), bitrates=True),
    Format("ogg", "OGG (Vorbis) · audio only", True, False, ("-c:a", "libvorbis"), bitrates=True),
    Format("wav", "WAV · audio only, lossless", True, False, ("-c:a", "pcm_s16le")),
    Format("flac", "FLAC · audio only, lossless", True, False, ("-c:a", "flac")),
]
FORMAT = {f.ext: f for f in FORMATS}
BITRATES = [0, 320, 256, 192, 128]           # 0 = the encoder's best variable bitrate


def plan(info: VideoInfo, choice: Choice | None, fmt: Format) -> tuple[str, str]:
    """(yt-dlp -f selector, --merge-output-format) to fetch for this format: streams that already fit it where the
    site has them (no conversion then), otherwise the best ones to convert from."""
    if fmt.audio:
        # the audio stream probe ranked first (plain stereo AAC), not yt-dlp's "best": that can be a stream the
        # site refuses to serve (YouTube's IAMF tracks answer 403)
        audio = next((c.selector for c in info.choices if c.audio_only), "ba[ext=m4a]/ba")
        if fmt.ext == "opus":
            return "ba[acodec=opus][protocol^=http]/" + audio + "/b", "mp4/mkv"
        return audio + "/b", "mp4/mkv"
    selector = choice.selector if choice is not None else "bv*+ba/b"
    if fmt.ext == "webm" and choice is not None:
        h = "".join(ch for ch in choice.label.split("p")[0] if ch.isdigit())
        if h:
            selector = f"bv*[height={h}][ext=webm]+ba[ext=webm]/bv*[height<={h}][ext=webm]+ba[ext=webm]/" + selector
        return selector, "webm/mkv"
    return selector, "mkv" if fmt.ext == "mkv" else "mp4/mkv"


def convert_command(tools: Path, source: Path, target: Path, fmt: Format, kbps: int, copy: bool) -> list[str]:
    """ffmpeg turning the downloaded file into ``fmt``; ``copy`` keeps the streams (fast), else converts them."""
    command = [str(tools / "ffmpeg.exe"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-nostats",
               "-progress", "pipe:1", "-i", str(source), "-map_metadata", "0"]
    if fmt.audio:
        command += ["-vn", "-sn", "-dn"]
        if copy:
            command += ["-c:a", "copy"]
        else:
            command += list(fmt.codec)
            if fmt.bitrates:
                if kbps:
                    command += ["-b:a", f"{kbps}k"]
                elif fmt.ext == "mp3":
                    command += ["-q:a", "0"]
                elif fmt.ext == "ogg":
                    command += ["-q:a", "7"]
                else:
                    command += ["-b:a", "192k"]
    else:
        command += ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
        command += ["-c", "copy"] + (["-movflags", "+faststart"] if fmt.ext in ("mp4", "mov") else []) if copy \
            else list(fmt.codec)
    return command + [str(target)]


def needs_convert(result: Path, fmt: Format) -> bool:
    return result.suffix.lower() != "." + fmt.ext


PROGRESS = "download:NEONPROG %(info.format_id)s %(progress.downloaded_bytes)s %(progress.total_bytes)s " \
           "%(progress.total_bytes_estimate)s"


def download_command(tools: Path, cache: Path, url: str, selector: str, work: Path, rate: int = 0,
                     merge: str = "mp4/mkv") -> list[str]:
    """yt-dlp downloading ``url`` in the chosen quality into ``work`` as video.<ext>, with one progress line per
    update. Joined streams go into ``merge`` (the first container of the list that fits them)."""
    command = base_command(tools, cache) + [
        "-f", selector, "--merge-output-format", merge, "-N", "4", "--newline", "--progress",
        "--progress-template", PROGRESS, "-P", str(work), "-o", "video.%(ext)s", "--continue"]
    if rate > 0:
        command += ["--limit-rate", str(int(rate))]
    return command + ["--", web.check_url(url)]


class ProcessTree:
    """A Windows job object holding yt-dlp and everything it starts (its own child, ffmpeg, Deno): ``kill()`` stops
    them all, and they stop by themselves if NEON goes away (the job closes with NEON's handle)."""

    def __init__(self, process: subprocess.Popen):
        import ctypes
        from ctypes import wintypes
        self.process = process
        self.handle = None
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            return

        class Limits(ctypes.Structure):                    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (64-bit)
            _fields_ = [("a", ctypes.c_int64 * 2), ("flags", wintypes.DWORD), ("pad", ctypes.c_byte * 124)]   # 144 bytes
        limits = Limits()
        limits.flags = 0x2000                                   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(limits), 144)
        if kernel.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(process._handle))):
            self.handle, self.kernel = job, kernel
        else:
            kernel.CloseHandle(wintypes.HANDLE(job))

    def kill(self) -> None:
        from ctypes import wintypes
        if self.handle:
            self.kernel.TerminateJobObject(wintypes.HANDLE(self.handle), 1)
        else:
            self.process.kill()

    def close(self) -> None:
        from ctypes import wintypes
        if self.handle:
            self.kernel.CloseHandle(wintypes.HANDLE(self.handle))      # kills anything still left in the job
            self.handle = None


def parse_progress(line: str) -> tuple[str, int, int] | None:
    """(format id, bytes done, total bytes or -1) from one NEONPROG line."""
    parts = line.strip().split()
    if len(parts) != 5 or parts[0] != "NEONPROG":
        return None

    def number(text: str) -> int:
        try:
            return int(float(text))
        except ValueError:
            return -1
    total = number(parts[3])
    return parts[1], max(0, number(parts[2])), total if total > 0 else number(parts[4])
