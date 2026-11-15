"""Torrent search across every source the user has: results are not filtered by what they are about; whatever
matches the words in any source is listed, with the source and whether NEON trusts it.

Kinds of source:
  archive   Internet Archive (built in, trusted): its search API, the item's .torrent
  torznab   Torznab API (Jackett, Prowlarr and most indexer apps): URL + API key
  rss       a search RSS feed with {query} in its URL
  page      a search page with {query} in its URL: magnet and .torrent links are read from the page text
  browser   opens the search in the user's browser (sites that need a person to pass a check)

The only filter is what a result may lead to: a magnet with a real info-hash or an http(s) .torrent link. Ads,
scripts, pop-ups, programs and any other link on a page are never listed or opened; pages are read as text.
"""
from __future__ import annotations

import re
import secrets
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, quote_plus, urlsplit

from . import web

TORZNAB_NS = "{http://torznab.com/schemas/2015/feed}"
MAX_RESULTS = 200
KINDS = ("archive", "torznab", "rss", "page", "browser")
BUILTIN = [{"id": "archive", "name": "Internet Archive", "kind": "archive", "url": "https://archive.org",
            "key": "", "quickword": "ia", "enabled": True, "builtin": True}]
PROGRAM_HINT = re.compile(r"\.(exe|msi|scr|bat|cmd|ps1|vbs|js|lnk|pif|com|jar|apk)\b|keygen|crack\.|patch\.exe",
                          re.I)


@dataclass
class Result:
    name: str
    source: str
    trusted: bool
    magnet: str = ""
    torrent: str = ""
    size: int = -1
    seeders: int = -1
    leechers: int = -1
    date: str = ""
    page: str = ""                          # the item's page, shown as text, opened only on request
    warning: str = ""

    @property
    def link(self) -> str:
        return self.magnet or self.torrent


@dataclass
class Source:
    id: str
    name: str
    kind: str
    url: str
    key: str = ""
    quickword: str = ""
    enabled: bool = True
    builtin: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> Source:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def sources_from_prefs(prefs: dict) -> list[Source]:
    """Built-in sources first (their switch kept from prefs), then the user's own."""
    saved = {s.get("id"): s for s in prefs.get("search_sources", []) if isinstance(s, dict)}
    out = []
    for builtin in BUILTIN:
        out.append(Source.from_dict({**builtin, "enabled": saved.get(builtin["id"], builtin).get("enabled", True),
                                     "quickword": saved.get(builtin["id"], builtin).get("quickword",
                                                                                        builtin["quickword"])}))
    for data in saved.values():
        if data.get("id") not in {b["id"] for b in BUILTIN} and data.get("kind") in KINDS:
            out.append(Source.from_dict({**data, "builtin": False}))
    return out


def new_source(name: str, kind: str, url: str, key: str = "", quickword: str = "") -> dict:
    if kind not in KINDS[1:]:
        raise ValueError("unknown kind of source")
    web.check_url(url.replace("{query}", "x"))
    if kind in ("rss", "page", "browser") and "{query}" not in url:
        raise ValueError("put {query} in the URL where the search words go")
    return {"id": secrets.token_hex(4), "name": name.strip()[:40] or urlsplit(url).hostname, "kind": kind,
            "url": url.strip(), "key": key.strip(), "quickword": quickword.strip().lower()[:12], "enabled": True}


def split_quickword(text: str, sources: list[Source]) -> tuple[list[Source], str]:
    """"ia ubuntu" -> ([Internet Archive], "ubuntu"); otherwise every enabled source and the whole text."""
    words = text.strip().split(None, 1)
    if len(words) == 2:
        hit = [s for s in sources if s.quickword and s.quickword == words[0].lower()]
        if hit:
            return hit, words[1]
    return [s for s in sources if s.enabled], text.strip()


# ------------------------------------------------------------------ parsing helpers
def _int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return -1


def _date(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return value[:10]


def _accept(result: Result) -> Result | None:
    """The one filter: a real magnet or an http(s) .torrent link. Everything else is dropped."""
    if result.magnet and not (result.magnet.lower().startswith("magnet:") and web.BTIH.search(result.magnet)):
        result.magnet = ""
    if result.torrent:
        parts = urlsplit(result.torrent)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            result.torrent = ""
    if not result.link:
        return None
    result.name = " ".join(result.name.split())[:300] or "(no name)"
    if PROGRAM_HINT.search(result.name):
        result.warning = "program"
    return result


def _xml(text: str) -> ET.Element:
    if "<!DOCTYPE" in text[:2000].upper() or "<!ENTITY" in text[:4000].upper():
        raise web.WebError("the feed declares entities; refused")          # no entity tricks in feeds
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise web.WebError(f"not a valid feed ({exc})") from None


# ------------------------------------------------------------------ one source
def search_archive(source: Source, query: str) -> list[Result]:
    q = f'({query}) AND format:("Archive BitTorrent")'
    url = ("https://archive.org/advancedsearch.php?q=" + quote_plus(q) + "&fl[]=identifier&fl[]=title"
           "&fl[]=item_size&fl[]=downloads&fl[]=publicdate&rows=100&output=json&sort[]=downloads+desc")
    import json
    text, _ = web.get_text(url)
    try:
        docs = json.loads(text)["response"]["docs"]
    except (ValueError, KeyError, TypeError):
        raise web.WebError("Internet Archive sent an unexpected answer") from None
    out = []
    for doc in docs:
        ident = str(doc.get("identifier", ""))
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", ident):
            continue
        title = doc.get("title") or ident
        title = title[0] if isinstance(title, list) else title
        out.append(Result(str(title), source.name, True,
                          torrent=f"https://archive.org/download/{ident}/{ident}_archive.torrent",
                          size=_int(doc.get("item_size")), seeders=-1, date=_date(str(doc.get("publicdate", ""))),
                          page=f"https://archive.org/details/{ident}"))
    return out


def parse_feed(text: str, source: Source) -> list[Result]:
    """Torznab and RSS items: title, size, seeders, date, magnet and .torrent links."""
    root = _xml(text)
    out = []
    for item in root.iter("item"):
        attrs = {a.get("name", ""): a.get("value", "") for a in item.iter(f"{TORZNAB_NS}attr")}
        enclosure = item.find("enclosure")
        link = (item.findtext("link") or "").strip()
        magnet = attrs.get("magneturl", "")
        torrent = ""
        if enclosure is not None and enclosure.get("url"):
            url = enclosure.get("url", "")
            if url.lower().startswith("magnet:"):
                magnet = magnet or url
            else:
                torrent = url
        if link.lower().startswith("magnet:"):
            magnet = magnet or link
        elif link and not torrent and (link.lower().split("?")[0].endswith(".torrent") or source.kind == "torznab"):
            torrent = link
        size = _int(attrs.get("size") or item.findtext("size") or (enclosure.get("length") if enclosure is not None
                                                                   else None))
        seeders = _int(attrs.get("seeders"))
        peers = _int(attrs.get("peers"))
        out.append(Result(item.findtext("title") or "", source.name, source.builtin, magnet=magnet, torrent=torrent,
                          size=size, seeders=seeders, leechers=peers - seeders if peers >= 0 and seeders >= 0 else -1,
                          date=_date(item.findtext("pubDate") or ""), page=(item.findtext("comments") or "").strip()))
    return out


def search_source(source: Source, query: str) -> list[Result]:
    if source.kind == "archive":
        raw = search_archive(source, query)
    elif source.kind == "torznab":
        sep = "&" if "?" in source.url else "?"
        url = f"{source.url.rstrip('/')}{sep}t=search&q={quote_plus(query)}" + \
            (f"&apikey={quote(source.key)}" if source.key else "")
        raw = parse_feed(web.get_text(url)[0], source)
    elif source.kind == "rss":
        raw = parse_feed(web.get_text(source.url.replace("{query}", quote_plus(query)))[0], source)
    elif source.kind == "page":
        text, final = web.get_text(source.url.replace("{query}", quote_plus(query)))
        raw = [Result(link.name, source.name, source.builtin,
                      magnet=link.url if link.kind == "magnet" else "",
                      torrent=link.url if link.kind == "torrent" else "")
               for link in web.page_links(text, final) if link.kind in ("magnet", "torrent")]
    else:
        return []
    return [r for r in map(_accept, raw) if r is not None]


def browser_url(source: Source, query: str) -> str:
    return web.check_url(source.url.replace("{query}", quote_plus(query)))


def search_all(sources: list[Source], query: str, on_results, on_done, on_error) -> threading.Event:
    """Ask every source at once, in background threads. ``on_results(list)`` per source as it answers,
    ``on_error(source name, message)``, ``on_done()`` at the end. Returns an Event that cancels the delivery."""
    cancelled = threading.Event()
    live = [s for s in sources if s.kind != "browser"]
    left = [len(live)]
    lock = threading.Lock()

    def run(source: Source) -> None:
        try:
            results = search_source(source, query)[:MAX_RESULTS]
            if not cancelled.is_set():
                on_results(results)
        except (web.WebError, OSError, ValueError) as exc:
            if not cancelled.is_set():
                on_error(source.name, str(exc))
        finally:
            with lock:
                left[0] -= 1
                last = left[0] == 0
            if last and not cancelled.is_set():
                on_done()

    if not live:
        on_done()
    for source in live:
        threading.Thread(target=run, args=(source,), daemon=True, name="neon-search").start()
    return cancelled
