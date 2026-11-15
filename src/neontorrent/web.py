"""What a pasted link is, and safe HTTP for the downloader and search.

``classify`` sorts any text the user pastes: magnet, info-hash, local .torrent, or http(s) URL. ``probe`` asks the
server about an http(s) URL without downloading it, following redirects with care, and says whether it is a
.torrent, a file to download or a web page. ``page_links`` reads a web page as text only (nothing in it runs) and
lists what can be downloaded from it.

Every request: http and https only, at most MAX_REDIRECTS redirects, never from the internet to this PC or the local
network, and a size cap on anything read into memory.
"""
from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit

from . import APP_VERSION

USER_AGENT = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) NEON-Torrent/{APP_VERSION}"
MAX_REDIRECTS = 5
MAX_PAGE = 4 * 1024 * 1024             # a web page or feed read into memory
MAX_TORRENT = 20 * 1024 * 1024
TIMEOUT = 25
BTIH = re.compile(r"urn:btih:([0-9a-fA-F]{40}|[A-Za-z2-7]{32})(?![0-9A-Za-z])")
HEX_HASH = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")

# what the link picker offers from a page, by extension (lower case, with the dot)
FILE_KINDS = {
    "archive": (".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".xz", ".bz2", ".zst"),
    "disc": (".iso", ".img", ".dmg"),
    "video": (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts"),
    "audio": (".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac"),
    "image": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".tif", ".tiff"),
    "document": (".pdf", ".epub", ".mobi", ".djvu", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt",
                 ".txt", ".csv", ".json"),
    "program": (".exe", ".msi", ".msix", ".appx", ".apk", ".deb", ".rpm", ".appimage", ".bat", ".cmd", ".ps1",
                ".scr", ".jar", ".vbs", ".js", ".lnk", ".pif", ".com", ".reg"),
    "torrent": (".torrent",),
}
EXT_KIND = {ext: kind for kind, exts in FILE_KINDS.items() for ext in exts}


class WebError(Exception):
    pass


# ------------------------------------------------------------------ what was pasted
def classify(text: str) -> tuple[str, str]:
    """("magnet" | "hash" | "file" | "url" | "unknown", cleaned text)."""
    text = (text or "").strip().strip('"').strip("'")
    low = text.lower()
    if low.startswith("magnet:"):
        return ("magnet", text) if BTIH.search(text) else ("unknown", text)
    if HEX_HASH.fullmatch(text):
        return "hash", text.lower()
    if low.startswith(("http://", "https://")):
        return "url", text
    if low.startswith("www."):
        return "url", "https://" + text
    try:
        if Path(text).is_file():
            return "file", text
    except (OSError, ValueError):
        pass
    return "unknown", text


# ------------------------------------------------------------------ addresses
def _is_local(host: str) -> bool:
    """This PC or a private network: localhost, loopback, RFC 1918, link-local, unique-local, CGNAT."""
    host = (host or "").strip("[]").lower()
    if host in ("localhost", "") or host.endswith(".localhost") or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified \
        or ip in ipaddress.ip_network("100.64.0.0/10")


def check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebError("only http and https links can be downloaded")
    if parts.username or parts.password:
        raise WebError("links with a user name or password inside are refused")
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    """At most MAX_REDIRECTS, http(s) only, and an internet address may not send NEON into the local network."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        hops = getattr(req, "neon_hops", 0) + 1
        if hops > MAX_REDIRECTS:
            raise WebError(f"more than {MAX_REDIRECTS} redirects")
        newurl = urljoin(req.full_url, newurl)
        check_url(newurl)
        if not _is_local(urlsplit(req.full_url).hostname or "") and _is_local(urlsplit(newurl).hostname or ""):
            raise WebError("a website tried to redirect to this PC or the local network")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.neon_hops = hops
        return new


_OPENER = urllib.request.build_opener(_Redirects())


def open_url(url: str, method: str = "GET", headers: dict | None = None, timeout: float = TIMEOUT):
    """An http.client response for ``url`` (redirects followed under the rules above). Caller closes it."""
    check_url(url)
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    request.neon_hops = 0
    try:
        return _OPENER.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise WebError(f"the server answered {exc.code} {exc.reason}") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, WebError):
            raise exc.reason from None
        reason = exc.reason if isinstance(exc.reason, str) else exc.reason.__class__.__name__
        raise WebError(f"cannot reach the server ({reason})") from None
    except (OSError, socket.timeout, ValueError) as exc:
        raise WebError(f"cannot reach the server ({exc.__class__.__name__})") from None


def read_capped(response, limit: int) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise WebError(f"larger than {limit // (1024 * 1024)} MB")
    return data


def get_text(url: str, limit: int = MAX_PAGE, headers: dict | None = None) -> tuple[str, str]:
    """(text, final URL) of a page, feed or API answer, decoded with its charset."""
    with open_url(url, headers=headers) as response:
        data = read_capped(response, limit)
        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, "replace"), response.geturl()


# ------------------------------------------------------------------ what an http(s) URL points at
@dataclass
class Probe:
    kind: str                         # "torrent" | "file" | "page"
    url: str                          # after redirects
    name: str
    size: int = -1                    # -1: not reported
    ranges: bool = False              # the server can resume and split
    mime: str = ""


def filename_from(headers: Message, url: str) -> str:
    """The file name the server suggests (Content-Disposition, RFC 6266 filename* first), else the URL path."""
    disposition = headers.get("Content-Disposition", "")
    star = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", disposition, re.I)
    if star:
        try:
            return unquote(star.group(2).strip().strip('"'), encoding=star.group(1) or "utf-8")
        except LookupError:
            pass
    plain = re.search(r'filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)', disposition, re.I)
    if plain:
        return (plain.group(1) or plain.group(2)).strip()
    return unquote(PurePosixPath(urlsplit(url).path).name) or urlsplit(url).hostname or "download"


def probe(url: str) -> Probe:
    """Ask the server what ``url`` is. A HEAD request first; servers that refuse HEAD get a 1-byte ranged GET."""
    response = None
    for method, headers in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
        try:
            response = open_url(url, method=method, headers=headers)
            break
        except WebError:
            if method == "GET":
                raise
    with response:
        status, headers, final = response.status, response.headers, response.geturl()
    mime = (headers.get_content_type() or "").lower()
    name = filename_from(headers, final)
    size, ranges = -1, headers.get("Accept-Ranges", "").lower() == "bytes"
    if status == 206:
        ranges = True
        total = re.search(r"/(\d+)\s*$", headers.get("Content-Range", ""))
        size = int(total.group(1)) if total else -1
    elif headers.get("Content-Length", "").isdigit() and status == 200:
        size = int(headers["Content-Length"])
    ext = PurePosixPath(name.lower()).suffix
    if mime == "application/x-bittorrent" or ext == ".torrent":
        kind = "torrent"
    elif mime in ("text/html", "application/xhtml+xml") and ext not in EXT_KIND:
        kind = "page"
    else:
        kind = "file"
    return Probe(kind, final, name, size, ranges, mime)


# ------------------------------------------------------------------ links on a page
@dataclass
class Link:
    url: str
    name: str
    kind: str                          # magnet | torrent | archive | disc | video | … | program | other
    text: str = ""                     # the link's own text on the page, plain
    extra: dict = field(default_factory=dict)


class _Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []
        self.base = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base" and attrs.get("href"):
            self.base = attrs["href"]
        if tag == "a" and attrs.get("href"):
            self._href, self._text = attrs["href"], []
        for key in ("src", "data-src"):                     # <video src>, <source src>, <audio src>
            if tag in ("video", "audio", "source") and attrs.get(key):
                self.links.append((attrs[key], ""))

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())[:200]))
            self._href = None


def link_kind(url: str) -> str:
    if url.lower().startswith("magnet:"):
        return "magnet"
    return EXT_KIND.get(PurePosixPath(unquote(urlsplit(url).path).lower()).suffix, "other")


def page_links(page: str, page_url: str, include_other: bool = False) -> list[Link]:
    """Downloadable links on a page: magnets (with a valid info-hash), .torrent and file links, deduplicated.
    The page is parsed as text; scripts, frames and styles are never run or fetched."""
    parser = _Anchors()
    try:
        parser.feed(page)
    except Exception:
        pass
    base = urljoin(page_url, parser.base) if parser.base else page_url
    seen, out = set(), []
    for href, text in parser.links:
        href = html.unescape(href.strip())
        if href.lower().startswith("magnet:"):
            if not BTIH.search(href):
                continue
            url = href
            name = unquote((re.search(r"[?&]dn=([^&]+)", href) or [None, ""])[1].replace("+", " ")) or text
        else:
            url = urljoin(base, href)
            if urlsplit(url).scheme not in ("http", "https"):
                continue
            name = unquote(PurePosixPath(urlsplit(url).path).name) or text
        kind = link_kind(url)
        if (kind == "other" and not include_other) or url in seen:
            continue
        seen.add(url)
        out.append(Link(url, name.strip() or url, kind, text))
    return out
