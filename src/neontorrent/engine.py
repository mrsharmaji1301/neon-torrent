"""libtorrent session wrapper. Lives in its own QThread; talks to the UI only via signals."""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import libtorrent as lt
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from . import guard as G
from .shield import Shield, source_text
from .theme import app_data_dir, fmt_bytes

# Hosts/IPs flagged by the user's antivirus. Matching trackers are stripped and IPs are filtered.
DEFAULT_BLOCKED = [
    "tracker.tvunderground.org.ru",
    "wegkxfcivgx.ydns.eu",
    "103.188.175.49",
    "46.17.63.157",
]


def parse_blocklist(entries) -> tuple[set[str], list]:
    """Split user entries into host names and IP networks. Accepts hosts, IPs, CIDR ranges, or URLs."""
    hosts, nets = set(), []
    for raw in entries or []:
        entry = str(raw).strip().lower()
        if not entry or entry.startswith("#"):
            continue
        if "://" in entry:
            entry = urlparse(entry).hostname or ""
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            if entry:
                hosts.add(entry.lstrip("*."))
    return hosts, nets

ALERT_MASK = (
    lt.alert.category_t.error_notification
    | lt.alert.category_t.status_notification
    | lt.alert.category_t.storage_notification
    | lt.alert.category_t.ip_block_notification
)
MAX_TORRENT_DOWNLOAD = 20 * 1024 * 1024
SHUTDOWN_SAVE_SECONDS = 45             # quitting waits this long for resume data; the window is gone already
UNLIMITED = 16777215                   # libtorrent's "no limit" for per-torrent connection/upload slots

# FLASH MODE: every file source at once. Peers stay Shield-filtered; booster trackers are long-lived public
# trackers added only while Flash is on (and removed again afterwards).
FLASH_CONNECTIONS = 1500
BOOSTER_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://opentracker.io:6969/announce",
]
USER_AGENT = "NeonTorrent/2.0 libtorrent/" + lt.__version__

DISC_EXT = {".iso", ".img", ".dmg", ".vhd", ".vmdk"}
APP_EXT = {".exe", ".msi", ".appimage", ".deb", ".rpm", ".pkg", ".apk", ".msix"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2", ".zst"}
VIDEO_EXT = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v", ".ts"}
AUDIO_EXT = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".opus"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".psd"}
DOC_EXT = {".pdf", ".epub", ".txt", ".doc", ".docx", ".md", ".mobi"}


def kind_for(name: str, multi: bool) -> str:
    if multi:
        return "folder"
    ext = Path(name).suffix.lower()
    for kind, exts in (("disc", DISC_EXT), ("app", APP_EXT), ("archive", ARCHIVE_EXT), ("video", VIDEO_EXT),
                       ("audio", AUDIO_EXT), ("image", IMAGE_EXT), ("doc", DOC_EXT)):
        if ext in exts:
            return kind
    return "file"


def pretty_title(name: str, multi: bool) -> str:
    stem = name if multi else (Path(name).stem or name)
    title = stem.replace("_", " ").replace("-", " ").replace("+", " ")
    title = " ".join(title.split())
    return title[:1].upper() + title[1:] if title else name


def hash_key(ih) -> str:
    """Stable hex id for a torrent from an info_hash_t (v1 preferred)."""
    try:
        if ih.has_v1():
            return str(ih.v1)
        return str(ih.v2)
    except AttributeError:
        return str(ih)


def _seconds(value) -> int:
    """libtorrent durations arrive as datetime.timedelta in the Python bindings."""
    try:
        return int(value.total_seconds())
    except AttributeError:
        return int(value or 0)


def handle_key(handle) -> str:
    try:
        return hash_key(handle.info_hashes())
    except Exception:
        return str(handle.info_hash())


def proposed_priorities(files: list[dict], findings: dict, skip: bool) -> list[dict]:
    """The Add dialog's starting point: every file Normal (4), except files Download Guard skips (0)."""
    out = []
    for f in files:
        finding = findings.get(str(f["index"])) or {}
        danger = finding.get("level") == G.DANGER
        out.append({"index": f["index"], "path": f["path"], "size": f["size"],
                    "priority": 0 if danger and skip else 4, "reason": finding.get("reason", ""), "danger": danger})
    return out


def priority_vector(num_files: int, pairs, current=None) -> list[int]:
    """Full per-file priority list from the UI's [index, priority] pairs. Unknown indices are dropped and values are
    clamped to libtorrent's 0..7, so a bad message never reaches libtorrent. Files not named keep `current`
    (or 0, Don't download)."""
    out = [int(p) for p in list(current or [])[:num_files]]
    out += [0] * (num_files - len(out))
    for pair in pairs or []:
        try:
            index, priority = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= index < num_files:
            out[index] = max(0, min(7, priority))
    return out


class TorrentEngine(QObject):
    snapshot = Signal(dict)
    notice = Signal(str, str)          # text, level: info|ok|warn|error
    finished = Signal(str)             # torrent name finished downloading
    magnet = Signal(str)               # magnet uri ready for clipboard
    stopped = Signal()
    _fetched = Signal(bytes, str)      # downloaded .torrent bytes, source url
    _shield_ready = Signal()           # network database finished loading (emitted from a worker thread)
    _seeds_resolved = Signal(list)     # web-seed host addresses resolved (worker thread)
    _guard_done = Signal(str, dict)    # Download Guard finished a torrent (worker thread)
    threat = Signal(str, str)          # torrent name, detail: a scanner found malware
    select_files = Signal(dict)        # a new torrent waits for the Add dialog: key, name, save_path, ready, files

    def __init__(self, prefs: dict):
        super().__init__()
        self.download_dir = prefs["download_dir"]
        self.upload_kib = prefs["upload_kib"]
        self.download_kib = prefs.get("download_kib", 0)
        self.listen_port = prefs.get("listen_port", 6881)
        self.max_connections = prefs.get("max_connections", 500)
        self.session: lt.session | None = None
        self.tick = None
        self.started_at = 0.0
        self.state_dir = app_data_dir() / "session"
        self.detail_key = ""
        self.history = deque([(0, 0)] * 60, maxlen=60)
        self.pending_names: dict[str, str] = {}
        self.resume_pending = 0
        self.last_resume_sweep = 0.0
        self.blocked_hosts, self.blocked_nets = parse_blocklist(prefs.get("blocked_hosts", DEFAULT_BLOCKED))
        self.file_only = bool(prefs.get("file_only", True))
        self.use_dht = bool(prefs.get("use_dht", False))
        self.accept_incoming = bool(prefs.get("accept_incoming", True))
        self.flash = False
        self.shield = Shield(app_data_dir() / "shield")
        self.shield.configure(prefs.get("shield_scope", "network"), bool(prefs.get("shield_learn", True)),
                              self.blocked_nets, bool(prefs.get("shield_avoid_dc", True)),
                              bool(prefs.get("shield_keep_seedboxes", True)))
        self.shield_view = False
        self.options_key = ""
        self._file_counts: dict[str, int] = {}
        self.meta_path = self.state_dir / "meta.json"
        self.meta = self._load_meta()
        self.ticks = 0
        self._seed_hosts: set[str] = set()
        self._banned_seeds: list = []
        self._fetched.connect(self.add_bytes)
        self._shield_ready.connect(self._on_shield_ready)
        self._seeds_resolved.connect(self._on_seeds_resolved)
        self.guard_opts = self._guard_options(prefs)
        self._guard_running: set[str] = set()
        self._disk_warned: dict[str, float] = {}
        self._guard_done.connect(self._on_guard_done)

    # ------------------------------------------------------------ blocklist
    def _is_blocked_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        try:
            ipaddress.ip_address(host)
            # trackers live in datacenters by nature: only what was actually flagged/blocked counts
            return self.shield.explain(host, include_feed=False) is not None
        except ValueError:
            hosts = self.blocked_hosts | self.shield.blocked_domains()
            return any(host == h or host.endswith("." + h) for h in hosts)

    def _filter_params(self, params) -> int:
        trackers = list(params.trackers)
        tiers = list(params.tracker_tiers)
        keep = [i for i, url in enumerate(trackers) if not self._is_blocked_url(url)]
        if len(keep) == len(trackers):
            return 0
        params.trackers = [trackers[i] for i in keep]
        params.tracker_tiers = [tiers[i] for i in keep] if len(tiers) == len(trackers) else []
        return len(trackers) - len(keep)

    def _load_torrent(self, data: bytes):
        """torrent_info with blocked announce URLs removed. The info dict (and hash) stays untouched."""
        meta = lt.bdecode(data)
        if not isinstance(meta, dict) or b"info" not in meta:
            raise ValueError("not a .torrent file")
        removed = 0
        announce = meta.get(b"announce")
        if announce and self._is_blocked_url(announce.decode("utf-8", "replace")):
            del meta[b"announce"]
            removed += 1
        tiers = []
        for tier in meta.get(b"announce-list", []) or []:
            kept = [u for u in tier if not self._is_blocked_url(u.decode("utf-8", "replace"))]
            removed += len(tier) - len(kept)
            if kept:
                tiers.append(kept)
        if b"announce-list" in meta:
            meta[b"announce-list"] = tiers
        return lt.torrent_info(meta), removed

    def _scrub_handle(self, handle) -> int:
        trackers = handle.trackers()
        keep = [t for t in trackers if not self._is_blocked_url(t.get("url", ""))]
        if len(keep) != len(trackers):
            handle.replace_trackers(keep)
        return len(trackers) - len(keep)

    def _apply_ip_filter(self) -> None:
        """VPN/datacenter ranges, your blocklist and everything the Shield learned. libtorrent never contacts
        a blocked address: peers from trackers, PEX, DHT and incoming connections are all checked first."""
        f = lt.ip_filter()
        for first, last, access in self.shield.rules():
            try:
                f.add_rule(first, last, access)
            except (RuntimeError, ValueError):
                continue
        self.session.set_ip_filter(f)

    # ------------------------------------------------------------ web seeds (HTTP mirrors)
    def _resolve_web_seeds(self, handles=None) -> None:
        """Web seeds are HTTP mirrors (often the official ones) and live in datacenters; resolve them so the
        VPN/datacenter pre-filter lets them through."""
        if self.session is None:
            return
        hosts = set()
        for handle in handles if handles is not None else self.session.get_torrents():
            try:
                urls = list(handle.url_seeds()) + list(handle.http_seeds())
            except Exception:
                continue
            for url in urls:
                host = urlparse(url).hostname
                if host and host not in self._seed_hosts:
                    hosts.add(host)
        if hosts:
            self._seed_hosts |= hosts
            threading.Thread(target=self._resolve_hosts, args=(sorted(hosts),), daemon=True).start()

    def _resolve_hosts(self, hosts: list[str]) -> None:
        ips = set()
        for host in hosts:
            try:
                for info in socket.getaddrinfo(host, None):
                    ips.add(info[4][0].split("%")[0])
            except OSError:
                continue
        self._seeds_resolved.emit(sorted(ips))

    @Slot(list)
    def _on_seeds_resolved(self, ips: list) -> None:
        if self.session is None:
            return
        if self.shield.set_allowed(self.shield.allow_ips | set(ips)):
            self._apply_ip_filter()
        # mirrors refused before their address was allowed are added back
        for handle, url in self._banned_seeds:
            try:
                if handle.is_valid():
                    handle.add_url_seed(url)
            except Exception:
                continue
        self._banned_seeds.clear()

    def _scrub_all(self) -> int:
        return sum(self._scrub_handle(h) for h in self.session.get_torrents() if h.is_valid())

    def _poll_shield(self) -> None:
        lessons = self.shield.poll_antivirus()
        if not lessons:
            return
        self._apply_ip_filter()
        if self._scrub_all():
            self._sweep_resume(force=True)
        more = f" (+{len(lessons) - 1} more)" if len(lessons) > 1 else ""
        self.notice.emit(f"SHIELD LEARNED FROM MALWAREBYTES · BLOCKED {lessons[0]}{more}", "warn")

    @Slot()
    def _on_shield_ready(self) -> None:
        if self.session is not None:
            self._apply_ip_filter()

    def _blocked_notice(self, count: int) -> None:
        if count:
            self.notice.emit(f"BLOCKED {count} TRACKER{'S' if count != 1 else ''} FROM YOUR BLOCKLIST", "warn")

    # ------------------------------------------------------------ lifecycle
    @Slot()
    def start(self) -> None:
        try:
            t0, steps = time.monotonic(), []
            Path(self.download_dir).mkdir(parents=True, exist_ok=True)
            self.state_dir.mkdir(parents=True, exist_ok=True)
            steps.append(("folders", time.monotonic()))
            self.session = lt.session(self._settings())
            steps.append(("session", time.monotonic()))
            # learn from past antivirus detections before any torrent can connect
            self.shield.poll_antivirus()
            steps.append(("antivirus", time.monotonic()))
            self._apply_ip_filter()
            steps.append(("ip filter", time.monotonic()))
            self.shield.db.start(self._shield_ready.emit)
            self.shield.feed.start(self._shield_ready.emit)
            self.started_at = time.monotonic()
            self._restore()
            steps.append(("restore", time.monotonic()))
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} INFO engine start: "
                  + ", ".join(f"{name} {end - start:.1f}s" for (name, end), start
                              in zip(steps, [t0] + [e for _n, e in steps])), file=sys.stderr, flush=True)
            self.tick = QTimer(self)
            self.tick.setInterval(1000)
            self.tick.timeout.connect(self._on_tick)
            self.tick.start()
            self._on_tick()
        except Exception as exc:  # engine must report, never crash the UI
            traceback.print_exc()             # error.log under pythonw
            self.notice.emit(f"ENGINE ERROR: {exc}", "error")

    def _settings(self) -> dict:
        port = int(self.listen_port)
        # file-only mode: no DHT/LSD chatter with unrelated nodes, so the only remote hosts contacted are this
        # client's torrents' trackers and (Shield-filtered) peers. Incoming peers are still peers of our torrents:
        # they must present one of our info-hashes and pass the same IP filter.
        flash = self.flash
        dht = flash or self._dht_on()
        incoming = self.accept_incoming or flash
        return {
            "listen_interfaces": f"0.0.0.0:{port},[::]:{port}" if incoming else f"0.0.0.0:{port}",
            "enable_dht": dht,
            # read-only DHT only asks about our own torrents and serves nobody else's lookups
            "dht_read_only": dht and self.file_only,
            "enable_lsd": flash or not self.file_only,
            "enable_upnp": incoming, "enable_natpmp": incoming,
            # trackers are filtered by URL/domain (see _scrub_handle); the IP filter is for peers and mirrors
            "apply_ip_filter_to_trackers": False,
            "alert_queue_size": 4000,
            "upload_rate_limit": max(0, self.upload_kib) * 1024,
            "download_rate_limit": max(0, self.download_kib) * 1024,
            "connections_limit": max(int(self.max_connections), FLASH_CONNECTIONS) if flash else int(self.max_connections),
            # speed: announce to every tracker in every tier (libtorrent stops at the first working tier otherwise)
            "announce_to_all_tiers": True,
            "announce_to_all_trackers": True,
            # do not charge TCP/IP overhead (ACKs of downloads) to the upload cap; with a small cap it would
            # starve our own piece requests and throttle downloads
            "rate_limit_ip_overhead": False,
            "connection_speed": 120 if flash else 50,
            "torrent_connect_boost": 120 if flash else 60,
            "peer_connect_timeout": 10,
            "num_want": 400 if flash else 200,
            "max_peerlist_size": 8000 if flash else 4000,
            "hashing_threads": max(1, min(4, (os.cpu_count() or 2) // 2)),
            "checking_mem_usage": 1024,
            "alert_mask": int(ALERT_MASK),
            # hardening (explicit, in case defaults ever change): no tracker requests to local services,
            # no punycode look-alike tracker domains, verify HTTPS tracker certificates
            "ssrf_mitigation": True,
            "allow_idna": False,
            "validate_https_trackers": True,
            "user_agent": USER_AGENT,
            "stop_tracker_timeout": 2,
            "dht_bootstrap_nodes": "dht.libtorrent.org:25401,router.bittorrent.com:6881,"
                                   "router.utorrent.com:6881,dht.transmissionbt.com:6881",
        }

    @Slot()
    def shutdown(self) -> None:
        if self.tick is not None:
            self.tick.stop()
        if self.session is not None:
            try:
                self.session.pause()
                self.resume_pending = 0
                for handle in self.session.get_torrents():
                    if handle.is_valid() and handle.status().has_metadata:
                        # flush first, so the saved piece list never claims data that is not on disk yet
                        handle.save_resume_data(lt.save_resume_flags_t.save_info_dict
                                                | lt.save_resume_flags_t.flush_disk_cache)
                        self.resume_pending += 1
                    else:
                        self._save_magnet_only(handle)
                # the window is already hidden, so waiting costs the user nothing; big torrents need the time
                deadline = time.monotonic() + SHUTDOWN_SAVE_SECONDS
                while self.resume_pending > 0 and time.monotonic() < deadline:
                    self.session.wait_for_alert(250)
                    self._process_alerts()
            except Exception:
                pass
            self.session = None
        self.stopped.emit()

    # ------------------------------------------------------------ persistence
    def _resume_path(self, key: str) -> Path:
        return self.state_dir / f"{key}.fastresume"

    def _snapshot_session(self) -> None:
        """Once a day, copy the resume files and meta.json to session/backups/<date>; keep the newest three.
        A bad update can then never take the torrent list with it."""
        backups = self.state_dir / "backups"
        today = backups / time.strftime("%Y-%m-%d")
        try:
            if not today.exists():
                files = [p for p in self.state_dir.iterdir()
                         if p.is_file() and p.suffix in (".fastresume", ".magnet", ".json")]
                if files:
                    today.mkdir(parents=True)
                    for path in files:
                        shutil.copy2(path, today / path.name)
            for old in sorted((p for p in backups.iterdir() if p.is_dir()), reverse=True)[3:]:
                shutil.rmtree(old, ignore_errors=True)
        except OSError as exc:
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} WARN session backup failed: {exc}", file=sys.stderr, flush=True)

    def _restore(self) -> None:
        self._snapshot_session()
        restored, lost = 0, []
        keys = {p.stem for p in self.state_dir.glob("*.fastresume")} | {p.stem for p in self.state_dir.glob("*.bak")}
        for key in sorted(keys):
            params = None
            # the previous save (.bak) stands in when the latest file is damaged or missing
            for path in (self._resume_path(key), self.state_dir / f"{key}.bak"):
                try:
                    params = lt.read_resume_data(path.read_bytes())
                    break
                except Exception:
                    continue
            if params is None:
                for path in (self._resume_path(key), self.state_dir / f"{key}.bak"):
                    if path.exists():
                        path.replace(path.with_name(path.name + ".broken"))
                lost.append(self.meta.get(key, {}).get("name") or key[:12])
                continue
            try:
                self._filter_params(params)
                if params.trackers:
                    # use the filtered resume tracker list instead of merging the .torrent's own list back in
                    params.flags |= lt.torrent_flags.override_trackers
                if not params.save_path:
                    params.save_path = self.download_dir
                if self._awaiting(key):
                    self._await_flags(params)              # still waiting for the Add dialog: stays paused
                self.session.async_add_torrent(params)
                restored += 1
            except Exception:
                lost.append(params.name or key[:12])
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} INFO restored {restored} of {len(keys)} saved torrents from "
              f"{self.state_dir}", file=sys.stderr, flush=True)
        if lost:
            self.notice.emit(f"COULD NOT RESTORE {', '.join(lost)} · copies are in session\\backups", "warn")
        for path in sorted(self.state_dir.glob("*.magnet")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                params = lt.parse_magnet_uri(data["uri"])
                self._filter_params(params)
                params.save_path = data.get("save_path") or self.download_dir
                if self._awaiting(path.stem):
                    self._await_flags(params)              # back to fetching the file list only
                elif data.get("paused"):
                    params.flags |= lt.torrent_flags.paused
                    params.flags &= ~lt.torrent_flags.auto_managed
                self.session.async_add_torrent(params)
                restored += 1
            except Exception:
                path.unlink(missing_ok=True)
        # one-time migration from v1 of this app, which only kept magnet links
        legacy = app_data_dir() / "torrents.json"
        if legacy.exists():
            try:
                for uri in json.loads(legacy.read_text(encoding="utf-8")):
                    if isinstance(uri, str) and uri.startswith("magnet:"):
                        params = lt.parse_magnet_uri(uri)
                        self._filter_params(params)
                        params.save_path = self.download_dir
                        self.session.async_add_torrent(params)
                        restored += 1
                legacy.rename(legacy.with_suffix(".json.migrated"))
            except (OSError, ValueError, RuntimeError):
                pass
        if restored:
            self.notice.emit(f"RESTORED {restored} TORRENT{'S' if restored != 1 else ''}", "ok")

    def _save_magnet_only(self, handle) -> None:
        """Torrents without metadata yet cannot produce resume data; keep their magnet."""
        try:
            status = handle.status()
            data = {"uri": lt.make_magnet_uri(handle), "save_path": status.save_path,
                    "paused": bool(status.flags & lt.torrent_flags.paused)
                    and not bool(status.flags & lt.torrent_flags.auto_managed)}
            (self.state_dir / f"{handle_key(handle)}.magnet").write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def _sweep_resume(self, force: bool = False) -> None:
        for handle in self.session.get_torrents():
            try:
                if not handle.is_valid():
                    continue
                if not handle.status().has_metadata:
                    self._save_magnet_only(handle)
                elif force or handle.need_save_resume_data():
                    handle.save_resume_data(lt.save_resume_flags_t.save_info_dict
                                            | lt.save_resume_flags_t.only_if_modified)
            except Exception:
                continue

    def _forget(self, key: str, keep_meta: bool = False) -> None:
        for suffix in (".fastresume", ".bak", ".magnet"):
            (self.state_dir / f"{key}{suffix}").unlink(missing_ok=True)
        if not keep_meta and self.meta.pop(key, None) is not None:
            self._save_meta()

    # ------------------------------------------------------------ alerts
    def _process_alerts(self) -> None:
        if self.session is None:
            return
        for alert in self.session.pop_alerts():
            try:
                self._handle_alert(alert)
            except Exception:
                continue

    def _handle_alert(self, alert) -> None:
        if isinstance(alert, lt.peer_blocked_alert):
            if alert.reason == lt.reason_t.ip_filter:
                endpoint = alert.endpoint if isinstance(alert.endpoint, tuple) else alert.ip
                ip, port = (endpoint[0], endpoint[1]) if isinstance(endpoint, tuple) else (str(endpoint), 0)
                self.shield.record_refused(str(ip), int(port), alert.torrent_name or "incoming")
            return
        if isinstance(alert, lt.add_torrent_alert):
            if alert.error.value():
                name = alert.params.name or "torrent"
                self.notice.emit(f"ADD FAILED · {name}: {alert.error.message()}", "error")
                return
            handle = alert.handle
            key = handle_key(handle)
            # resume data / .torrent may still carry blocked trackers; drop them before any announce sticks
            self._scrub_handle(handle)
            # booster trackers left behind by a Flash session that ended with the app closing
            leftover = self.meta.get("_flash", {}).pop(key, None)
            if leftover and not self.flash:
                self._remove_trackers(handle, set(leftover))
                self._save_meta()
            if self.flash:
                self._boost(handle)
            if handle.status().has_metadata:
                self._guard_inspect(handle)
            self._resolve_web_seeds([handle])
            if key in self.pending_names:
                self.pending_names.pop(key)
                self.notice.emit(f"ADDED · {handle.status().name or 'fetching metadata'}", "ok")
            if handle.status().has_metadata:
                handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
            else:
                self._save_magnet_only(handle)
            if self._awaiting(key):
                self._offer_selection(handle)              # new add, or one still waiting after a restart
        elif isinstance(alert, lt.save_resume_data_alert):
            key = handle_key(alert.handle)
            data = lt.write_resume_data_buf(alert.params)
            path = self._resume_path(key)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            if path.exists():
                path.replace(path.with_suffix(".bak"))     # keep the last good save until the new one is in place
            tmp.replace(path)
            (self.state_dir / f"{key}.magnet").unlink(missing_ok=True)
            self.resume_pending = max(0, self.resume_pending - 1)
        elif isinstance(alert, lt.save_resume_data_failed_alert):
            self.resume_pending = max(0, self.resume_pending - 1)
        elif isinstance(alert, lt.metadata_received_alert):
            handle = alert.handle
            awaiting = self._awaiting(handle_key(handle))
            if awaiting:
                # the file list is in: every file Don't download and paused until the user confirms the Add dialog
                handle.prioritize_files([0] * handle.torrent_file().num_files())
                handle.unset_flags(lt.torrent_flags.auto_managed)
                handle.pause()
                handle.unset_flags(lt.torrent_flags.upload_mode | lt.torrent_flags.stop_when_ready)
            handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
            self._guard_inspect(handle)                # before any file data is requested
            if self.meta.get(handle_key(handle), {}).get("first_last"):
                self._apply_first_last(handle, True)
            self._resolve_web_seeds([handle])
            self.notice.emit(f"METADATA RECEIVED · {handle.status().name}", "info")
            if awaiting:
                self._offer_selection(handle)
        elif isinstance(alert, lt.torrent_finished_alert):
            status = alert.handle.status()
            alert.handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
            # libtorrent also fires "finished" after a recheck of complete data; only announce real downloads
            if status.all_time_download > 0 and time.monotonic() - self.started_at > 5:
                self.finished.emit(status.name)
                self.notice.emit(f"COMPLETED · {status.name}", "ok")
            # a torrent with nothing selected (waiting for its Add dialog) also counts as finished: wait for real data
            done = status.total_wanted > 0 and status.total_wanted_done >= status.total_wanted
            if done and "scan" not in self.meta.get(handle_key(alert.handle), {}).get("guard", {}):
                self._guard_finish(alert.handle)
        elif isinstance(alert, (lt.torrent_error_alert, lt.file_error_alert)):
            self.notice.emit(f"ERROR · {alert.message()}", "error")
        elif isinstance(alert, lt.url_seed_alert):
            message = (alert.error.message() if alert.error.value() else alert.error_message or "").lower()
            if "filter" in message or "banned" in message:
                url = alert.server_url or alert.url
                self._banned_seeds.append((alert.handle, url))
                host = urlparse(url).hostname
                self._seed_hosts.discard(host)
                self._resolve_web_seeds([alert.handle])
        elif isinstance(alert, lt.listen_failed_alert):
            self.notice.emit(f"PORT ERROR · {alert.message()}", "warn")

    # ------------------------------------------------------------ adding
    def _existing_keys(self) -> set[str]:
        return {handle_key(h) for h in self.session.get_torrents()}

    def _queue_add(self, params) -> None:
        key = hash_key(params.info_hashes) if params.ti is None else hash_key(params.ti.info_hashes())
        if key in self._existing_keys():
            if self._awaiting(key):
                self.resume([key])                     # still waiting for its files: bring the Add dialog back
                return
            self.notice.emit("ALREADY IN LIST", "warn")
            return
        self._blocked_notice(self._filter_params(params))
        if params.ti is None and not params.trackers and not self._dht_on():
            self.notice.emit("THIS MAGNET HAS NO TRACKERS · TURN ON DHT IN SHIELD SETTINGS TO FETCH IT", "warn")
        params.save_path = self.download_dir
        # every add waits for the Add dialog (save folder, files, priorities); the free-space check lives there
        self._await_flags(params)
        self._meta_for(key)["select"] = True
        self._save_meta()
        self.pending_names[key] = ""
        self.session.async_add_torrent(params)
        self.notice.emit("FETCHING THE FILE LIST…" if params.ti is None else "CHOOSE FILES TO START", "info")

    # ------------------------------------------------------------ file selection (Add dialog)
    def _awaiting(self, key: str) -> bool:
        """True while a torrent waits for the user to confirm its Add dialog. Nothing downloads until then."""
        return bool(self.meta.get(key, {}).get("select"))

    @staticmethod
    def _await_flags(params) -> None:
        """A .torrent stays paused with every file at Don't download. A magnet fetches its file list only:
        upload_mode requests no piece data and stop_when_ready pauses it once metadata is in."""
        params.flags &= ~lt.torrent_flags.auto_managed
        if params.ti is None:
            params.flags &= ~lt.torrent_flags.paused
            params.flags |= lt.torrent_flags.upload_mode | lt.torrent_flags.stop_when_ready
        else:
            params.flags |= lt.torrent_flags.paused
            params.file_priorities = [0] * params.ti.num_files()

    def _offer_selection(self, handle) -> None:
        """Ask the UI for the Add dialog: first while the file list is fetched (ready False), then with the files.
        Files Download Guard skips are proposed as Don't download, with the reason."""
        key = handle_key(handle)
        status = handle.status()
        files = []
        if status.has_metadata:
            findings = self.meta.get(key, {}).get("guard", {}).get("findings", {})
            files = proposed_priorities(self._guard_files(handle), findings, self.guard_opts["skip"])
        self.select_files.emit({"key": key, "name": status.name or "", "save_path": status.save_path or self.download_dir,
                                "ready": bool(status.has_metadata), "files": files})

    @Slot(str, str, list)
    def confirm_selection(self, key: str, save_path: str, pairs: list) -> None:
        """DOWNLOAD in the Add dialog: apply the save folder and file priorities, then start."""
        for handle in self._handles([key]):
            ti = handle.torrent_file()
            if not self._awaiting(key) or ti is None:
                continue
            priorities = priority_vector(ti.num_files(), pairs)
            if not any(priorities):
                continue
            status = handle.status()
            target = str(Path(save_path)) if save_path and Path(save_path).is_absolute() else self.download_dir
            try:
                Path(target).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.notice.emit(f"CANNOT USE {target} · {exc}", "error")
                self._offer_selection(handle)
                continue
            handle.prioritize_files(priorities)
            if os.path.normcase(os.path.abspath(target)) != os.path.normcase(os.path.abspath(status.save_path)):
                handle.move_storage(target)            # nothing is on disk yet, so this only changes the folder
            fs = ti.files()
            if any(priorities[i] and (Path(target) / fs.file_path(i)).exists() for i in range(fs.num_files())):
                handle.force_recheck()                 # data from an earlier download: verify it, don't fetch again
            meta = self._meta_for(key)
            meta.pop("select", None)
            meta.get("guard", {}).pop("scan", None)        # Mark-of-the-Web and the scan run when the files finish
            if meta.get("first_last"):
                self._apply_first_last(handle, True)
            handle.unset_flags(lt.torrent_flags.upload_mode | lt.torrent_flags.stop_when_ready)
            handle.set_flags(lt.torrent_flags.auto_managed)
            handle.resume()
            self._save_meta()
            handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
            wanted = sum(1 for p in priorities if p)
            self.notice.emit(f"DOWNLOADING · {status.name} · {wanted} FILE{'S' if wanted != 1 else ''}", "ok")
        self._on_tick()

    @Slot(str)
    def cancel_selection(self, key: str) -> None:
        """CANCEL in the Add dialog: drop the torrent. Nothing was requested, so it left no files; files that were
        already in the folder are never touched."""
        for handle in self._handles([key]):
            if not self._awaiting(key):
                continue
            self.session.remove_torrent(handle)
            self._forget(key)
            self.pending_names.pop(key, None)
            self.notice.emit("ADD CANCELLED · NOTHING WAS DOWNLOADED", "info")
        self._on_tick()

    @Slot(str)
    def add_uri(self, uri: str) -> None:
        if self.session is None:
            self.notice.emit("ENGINE IS NOT READY", "error")
            return
        uri = uri.strip().strip('"')
        try:
            low = uri.lower()
            if low.startswith("magnet:"):
                self._queue_add(lt.parse_magnet_uri(uri))
            elif low.startswith(("http://", "https://")):
                self.notice.emit("DOWNLOADING .TORRENT FILE…", "info")
                threading.Thread(target=self._fetch, args=(uri,), daemon=True).start()
            elif len(uri) in (40, 64) and all(ch in "0123456789abcdefABCDEF" for ch in uri):
                self._queue_add(lt.parse_magnet_uri(f"magnet:?xt=urn:btih:{uri}"))
            elif Path(uri).is_file():
                self.add_file(uri)
            else:
                raise ValueError("paste a magnet link, info-hash, or HTTP(S) .torrent URL")
        except Exception as exc:
            self.notice.emit(f"ADD FAILED · {exc}", "error")

    def _fetch(self, url: str) -> None:
        # libtorrent 2.x dropped add_torrent_params.url, so the file is fetched here instead.
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=25) as response:
                data = response.read(MAX_TORRENT_DOWNLOAD + 1)
            if len(data) > MAX_TORRENT_DOWNLOAD:
                raise ValueError("file too large")
            self._fetched.emit(data, url)
        except Exception as exc:
            self.notice.emit(f"DOWNLOAD FAILED · {exc}", "error")

    @Slot(bytes, str)
    def add_bytes(self, data: bytes, source: str) -> None:
        try:
            params = lt.add_torrent_params()
            params.ti, removed = self._load_torrent(data)
            self._blocked_notice(removed)
            self._queue_add(params)
        except Exception as exc:
            self.notice.emit(f"NOT A VALID .TORRENT · {exc}", "error")

    @Slot(str)
    def add_file(self, path: str) -> None:
        if self.session is None:
            self.notice.emit("ENGINE IS NOT READY", "error")
            return
        try:
            params = lt.add_torrent_params()
            params.ti, removed = self._load_torrent(Path(path).read_bytes())
            self._blocked_notice(removed)
            self._queue_add(params)
        except Exception as exc:
            self.notice.emit(f"FILE ERROR · {exc}", "error")

    # ------------------------------------------------------------ actions
    def _handles(self, keys: list[str]):
        if self.session is None:
            return []
        wanted = set(keys)
        return [h for h in self.session.get_torrents() if handle_key(h) in wanted]

    @Slot(list)
    def pause(self, keys: list) -> None:
        """Temporary pause: lets blocks already in flight finish, then idles. Shown as Paused."""
        for handle in self._handles(keys):
            # an auto-managed torrent would be resumed by the queue; take it out first
            handle.unset_flags(lt.torrent_flags.auto_managed)
            handle.pause(lt.torrent_handle.graceful_pause)
            self._meta_for(handle_key(handle)).pop("stopped", None)
            handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
        if keys:
            self._save_meta()
            self._on_tick()

    @Slot(list)
    def stop(self, keys: list) -> None:
        """Full stop: drops every peer at once, writes cached data and closes the files, no seeding.
        Shown as Stopped and stays stopped across restarts until Resume."""
        count = 0
        for handle in self._handles(keys):
            handle.unset_flags(lt.torrent_flags.auto_managed)
            handle.pause()                                   # immediate, not graceful
            handle.flush_cache()                             # data on disk, file handles released
            self._meta_for(handle_key(handle))["stopped"] = True
            handle.save_resume_data(lt.save_resume_flags_t.save_info_dict | lt.save_resume_flags_t.flush_disk_cache)
            count += 1
        if count:
            self._save_meta()
            self.notice.emit(f"STOPPED {count} TORRENT{'S' if count != 1 else ''} · FILES CLOSED, NO SEEDING", "ok")
            self._on_tick()

    @Slot(list)
    def resume(self, keys: list) -> None:
        for handle in self._handles(keys):
            if self._awaiting(handle_key(handle)):
                # still waiting for its file selection: show the Add dialog again instead of downloading
                if not handle.status().has_metadata:
                    handle.unset_flags(lt.torrent_flags.auto_managed)
                    handle.set_flags(lt.torrent_flags.upload_mode | lt.torrent_flags.stop_when_ready)
                    handle.resume()
                self._offer_selection(handle)
                continue
            handle.set_flags(lt.torrent_flags.auto_managed)
            handle.resume()
            self._meta_for(handle_key(handle)).pop("stopped", None)
            handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
        if keys:
            self._save_meta()
            self._on_tick()

    @Slot()
    def stop_all(self) -> None:
        self.stop([handle_key(h) for h in self.session.get_torrents()] if self.session else [])

    @Slot(list)
    def remove(self, keys: list) -> None:
        count = 0
        for handle in self._handles(keys):
            key = handle_key(handle)
            self.session.remove_torrent(handle)
            self._forget(key)
            count += 1
        if count:
            self.notice.emit(f"REMOVED {count} · FILES KEPT", "ok")
            self._on_tick()

    @Slot(list)
    def delete_data(self, keys: list) -> None:
        count = 0
        for handle in self._handles(keys):
            key = handle_key(handle)
            self.session.remove_torrent(handle, lt.session.delete_files)
            self._forget(key)
            count += 1
        if count:
            self.notice.emit(f"REMOVED {count} · DATA DELETED", "ok")
            self._on_tick()

    @Slot(list)
    def recheck(self, keys: list) -> None:
        for handle in self._handles(keys):
            handle.force_recheck()
        self.notice.emit("RECHECKING DATA", "info")

    @Slot(list)
    def reannounce(self, keys: list) -> None:
        for handle in self._handles(keys):
            handle.force_reannounce()
            try:
                handle.force_dht_announce()
            except Exception:
                pass
        self.notice.emit("ANNOUNCED TO TRACKERS + DHT", "info")

    @Slot(list, bool)
    def set_sequential(self, keys: list, on: bool) -> None:
        for handle in self._handles(keys):
            if on:
                handle.set_flags(lt.torrent_flags.sequential_download)
            else:
                handle.unset_flags(lt.torrent_flags.sequential_download)
        self.notice.emit("SEQUENTIAL " + ("ON" if on else "OFF"), "info")

    @Slot(str)
    def copy_magnet(self, key: str) -> None:
        for handle in self._handles([key]):
            self.magnet.emit(lt.make_magnet_uri(handle))

    @Slot(str, list)
    def set_file_priorities(self, key: str, pairs: list) -> None:
        """Details → Files: High / Normal / Low / Don't download in any state; applies at once."""
        for handle in self._handles([key]):
            ti = handle.torrent_file()
            if ti is None:
                continue
            if self._awaiting(key):
                self.notice.emit("CHOOSE FILES IN THE ADD DIALOG FIRST", "warn")
                self._offer_selection(handle)
                continue
            before = list(handle.get_file_priorities())
            priorities = priority_vector(ti.num_files(), pairs, before)
            handle.prioritize_files(priorities)
            if self.meta.get(key, {}).get("first_last"):
                self._apply_first_last(handle, True)    # new file priorities reset piece priorities
            # a file was switched on: Mark-of-the-Web and the scan run again when it finishes
            switched_on = any(p and (i >= len(before) or not before[i]) for i, p in enumerate(priorities))
            if switched_on and self.meta.get(key, {}).get("guard", {}).pop("scan", None) is not None:
                self._save_meta()
            handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
        self._on_tick()

    @Slot(str, str)
    def move_storage(self, key: str, path: str) -> None:
        for handle in self._handles([key]):
            handle.move_storage(path)
        self.notice.emit("MOVING DATA…", "info")

    @Slot(str)
    def set_detail_key(self, key: str) -> None:
        self.detail_key = key
        self._on_tick()

    @Slot()
    def pause_all(self) -> None:
        self.pause([handle_key(h) for h in self.session.get_torrents()] if self.session else [])

    @Slot()
    def resume_all(self) -> None:
        self.resume([handle_key(h) for h in self.session.get_torrents()] if self.session else [])

    # ------------------------------------------------------------ per-torrent metadata (ratio limits, flags)
    def _load_meta(self) -> dict:
        try:
            data = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_meta(self) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.meta_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.meta, indent=1), encoding="utf-8")
            tmp.replace(self.meta_path)
        except OSError:
            pass

    def _meta_for(self, key: str) -> dict:
        return self.meta.setdefault(key, {})

    # ------------------------------------------------------------ flash mode
    def _remove_trackers(self, handle, urls: set) -> None:
        trackers = handle.trackers()
        keep = [t for t in trackers if t.get("url") not in urls]
        if len(keep) != len(trackers):
            handle.replace_trackers(keep)

    def _boost(self, handle) -> None:
        """Add booster trackers the torrent does not have yet, remembering which ones were ours."""
        key = handle_key(handle)
        present = {t.get("url") for t in handle.trackers()}
        added = [url for url in BOOSTER_TRACKERS if url not in present and not self._is_blocked_url(url)]
        for url in added:
            handle.add_tracker({"url": url, "tier": 99})
        if added:
            self.meta.setdefault("_flash", {})[key] = added
        handle.force_reannounce()
        try:
            handle.force_dht_announce()
        except Exception:
            pass

    @Slot(bool)
    def set_flash(self, on: bool) -> None:
        if self.session is None or on == self.flash:
            return
        self.flash = on
        pack = self._settings()
        pack.pop("dht_bootstrap_nodes", None)
        self.session.apply_settings(pack)
        flash_added = self.meta.setdefault("_flash", {})
        for handle in self.session.get_torrents():
            if not handle.is_valid():
                continue
            if on:
                self._boost(handle)
            else:
                urls = flash_added.pop(handle_key(handle), None)
                if urls:
                    self._remove_trackers(handle, set(urls))
        self._save_meta()
        if on:
            self.notice.emit("⚡ FLASH MODE ON · ALL FILE SOURCES · SHIELD STILL FILTERING PEERS", "warn")
        else:
            self._sweep_resume(force=True)
            self.notice.emit("FLASH MODE OFF · BACK TO FILE-ONLY NETWORK", "ok")
        self._on_tick()

    # ------------------------------------------------------------ per-torrent options
    @Slot(str)
    def set_options_key(self, key: str) -> None:
        self.options_key = key
        if key:
            self._on_tick()

    def _apply_first_last(self, handle, on: bool) -> None:
        ti = handle.torrent_file()
        if ti is None:
            return
        fs = ti.files()
        priorities = handle.get_file_priorities()
        for i in range(fs.num_files()):
            size = fs.file_size(i)
            if size == 0 or fs.file_flags(i) & lt.file_storage.flag_pad_file or (
                    i < len(priorities) and priorities[i] == 0):
                continue
            for piece in {ti.map_file(i, 0, 1).piece, ti.map_file(i, size - 1, 1).piece}:
                handle.piece_priority(piece, 7 if on else 4)

    @Slot(str, str, object)
    def torrent_option(self, key: str, name: str, value) -> None:
        handles = self._handles([key])
        if not handles:
            return
        handle = handles[0]
        meta = self._meta_for(key)
        if name == "download_limit":
            handle.set_download_limit(max(0, int(value)) * 1024)
        elif name == "upload_limit":
            handle.set_upload_limit(max(0, int(value)) * 1024)
        elif name == "max_connections":
            handle.set_max_connections(int(value) if int(value) > 0 else -1)
        elif name == "max_uploads":
            handle.set_max_uploads(int(value) if int(value) > 0 else -1)
        elif name == "sequential":
            (handle.set_flags if value else handle.unset_flags)(lt.torrent_flags.sequential_download)
        elif name == "super_seeding":
            (handle.set_flags if value else handle.unset_flags)(lt.torrent_flags.super_seeding)
        elif name == "first_last":
            meta["first_last"] = bool(value)
            self._apply_first_last(handle, bool(value))
        elif name == "ratio_limit":
            meta["ratio_limit"] = max(0.0, float(value))
            meta.pop("ratio_hit", None)
        elif name == "force_start":
            if value:
                handle.unset_flags(lt.torrent_flags.auto_managed)
                handle.resume()
            else:
                handle.set_flags(lt.torrent_flags.auto_managed)
        elif name == "queue":
            {"up": handle.queue_position_up, "down": handle.queue_position_down,
             "top": handle.queue_position_top, "bottom": handle.queue_position_bottom}[str(value)]()
        elif name == "add_trackers":
            present = {t.get("url") for t in handle.trackers()}
            added = 0
            for url in value:
                url = str(url).strip()
                if url and url not in present and not self._is_blocked_url(url):
                    handle.add_tracker({"url": url, "tier": len(present) + added})
                    added += 1
            self.notice.emit(f"ADDED {added} TRACKER{'S' if added != 1 else ''}", "ok" if added else "warn")
            if added:
                handle.force_reannounce()
        else:
            return
        self._save_meta()
        handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
        self._on_tick()

    @Slot(list)
    def skip_check(self, keys: list) -> None:
        """Re-add in seed mode: libtorrent assumes the data is complete and verifies each piece lazily
        when it is first uploaded (a failed piece triggers a normal full recheck)."""
        count = 0
        for handle in self._handles(keys):
            status = handle.status()
            key = handle_key(handle)
            if not status.has_metadata or self._awaiting(key):
                continue
            trackers = handle.trackers()
            params = lt.add_torrent_params()
            params.ti = handle.torrent_file()
            params.save_path = status.save_path
            params.trackers = [t["url"] for t in trackers]
            params.tracker_tiers = [int(t.get("tier", 0)) for t in trackers]
            params.download_limit = handle.download_limit()
            params.upload_limit = handle.upload_limit()
            params.flags = (lt.torrent_flags.seed_mode | lt.torrent_flags.auto_managed | lt.torrent_flags.apply_ip_filter
                            | lt.torrent_flags.update_subscribe | lt.torrent_flags.override_trackers)
            self.session.remove_torrent(handle)          # files stay on disk
            self._forget(key, keep_meta=True)            # same torrent comes straight back: keep its settings
            self.session.async_add_torrent(params)
            count += 1
        if count:
            self.notice.emit(f"HASH CHECK SKIPPED · {count} TORRENT{'S' if count != 1 else ''} SET COMPLETE", "warn")

    def _options(self, handle, status) -> dict:
        key = handle_key(handle)
        meta = self.meta.get(key, {})
        dl, ul = handle.download_limit(), handle.upload_limit()
        conns, uploads = handle.max_connections(), handle.max_uploads()
        flags = status.flags
        return {
            "key": key,
            "download_limit": dl // 1024 if dl > 0 else 0,
            "upload_limit": ul // 1024 if ul > 0 else 0,
            "max_connections": 0 if conns <= 0 or conns >= UNLIMITED else conns,
            "max_uploads": 0 if uploads <= 0 or uploads >= UNLIMITED else uploads,
            "sequential": bool(flags & lt.torrent_flags.sequential_download),
            "super_seeding": bool(flags & lt.torrent_flags.super_seeding),
            "force_start": not bool(flags & lt.torrent_flags.auto_managed) and not bool(flags & lt.torrent_flags.paused),
            "first_last": bool(meta.get("first_last")),
            "ratio_limit": float(meta.get("ratio_limit", 0.0)),
            "queue_position": handle.queue_position(),
            "has_metadata": status.has_metadata,
            "num_pieces": status.num_pieces,
            "pieces_total": handle.torrent_file().num_pieces() if status.has_metadata else 0,
            "trackers": len(handle.trackers()),
            "connections": status.num_peers,
            "connections_limit": status.connections_limit,
            "seeding_time": _seconds(status.seeding_duration),
            "active_time": _seconds(status.active_duration),
        }

    def _enforce_ratio(self, handle, key: str, ratio: float, state: str) -> None:
        meta = self.meta.get(key)
        limit = float(meta.get("ratio_limit", 0)) if meta else 0.0
        if limit <= 0 or state != "Seeding" or ratio < limit or meta.get("ratio_hit"):
            return
        meta["ratio_hit"] = True
        handle.unset_flags(lt.torrent_flags.auto_managed)
        handle.pause(lt.torrent_handle.graceful_pause)
        self._save_meta()
        self.notice.emit(f"RATIO {ratio:.2f} REACHED · SEEDING STOPPED · {handle.status().name}", "ok")

    # ------------------------------------------------------------ disk space
    @staticmethod
    def _disk_message(status) -> str:
        need = max(0, status.total_wanted - status.total_wanted_done)
        try:
            free = shutil.disk_usage(status.save_path).free
        except OSError:
            return "Disk write failed"
        drive = Path(status.save_path).drive or status.save_path
        return f"Disk full ({drive}) — needs {fmt_bytes(need)} more, {fmt_bytes(free)} free. Free space or MOVE DATA."

    def _check_disk(self) -> None:
        """libtorrent switches a torrent to upload-only after a failed disk write (usually a full drive) and only
        retries after 10 minutes. Explain it, warn before it happens, and resume as soon as there is room."""
        now = time.monotonic()
        for handle in self.session.get_torrents():
            if not handle.is_valid():
                continue
            status = handle.status()
            if status.progress >= 1.0 or not status.has_metadata:
                continue
            try:
                free = shutil.disk_usage(status.save_path).free
            except OSError:
                continue
            need = max(0, status.total_wanted - status.total_wanted_done)
            key = handle_key(handle)
            if status.flags & lt.torrent_flags.upload_mode:
                if free > min(need, 1024**3) + 256 * 1024**2:
                    handle.unset_flags(lt.torrent_flags.upload_mode)
                    self._disk_warned.pop(key, None)
                    self.notice.emit(f"DISK SPACE BACK · RESUMING {status.name}", "ok")
                elif now - self._disk_warned.get(key, 0) > 300:
                    self._disk_warned[key] = now
                    self.notice.emit(f"DISK FULL · {status.name} · {fmt_bytes(free)} FREE · USE MOVE DATA", "error")
            elif free < need and now - self._disk_warned.get(key, 0) > 600:
                self._disk_warned[key] = now
                self.notice.emit(f"LOW DISK SPACE · {status.name} NEEDS {fmt_bytes(need)} MORE, "
                                 f"{fmt_bytes(free)} FREE", "warn")

    # ------------------------------------------------------------ download guard
    @staticmethod
    def _guard_options(prefs: dict) -> dict:
        return {"skip": bool(prefs.get("guard_skip", True)), "strict": bool(prefs.get("guard_strict", False)),
                "motw": bool(prefs.get("guard_motw", True)), "scan": bool(prefs.get("guard_scan", True)),
                "vt_key": str(prefs.get("guard_vt_key", "") or ""),
                "pause_threat": bool(prefs.get("guard_pause_threat", True))}

    @staticmethod
    def _guard_files(handle) -> list[dict]:
        ti = handle.torrent_file()
        if ti is None:
            return []
        fs = ti.files()
        out = []
        for i in range(fs.num_files()):
            flags = fs.file_flags(i)
            if flags & lt.file_storage.flag_pad_file:
                continue
            out.append({"index": i, "path": fs.file_path(i).replace("\\", "/"), "size": fs.file_size(i),
                        "symlink": bool(flags & lt.file_storage.flag_symlink)})
        return out

    def _guard_inspect(self, handle, force: bool = False) -> None:
        """Runs once per torrent, as soon as the file list is known and before file data is requested."""
        key = handle_key(handle)
        meta = self._meta_for(key)
        if "guard" in meta and not force:
            return
        files = self._guard_files(handle)
        if not files:
            return
        verdict = G.inspect(files, self.guard_opts["strict"])
        skipped = []
        if self.guard_opts["skip"]:
            for index in verdict["danger"]:
                handle.file_priority(index, 0)
                skipped.append(index)
        meta["guard"] = {"level": verdict["level"], "media": verdict["media"], "skipped": len(skipped),
                         "findings": {str(i): {"level": f["level"], "reason": f["reason"]}
                                      for i, f in verdict["findings"].items()},
                         "runnable": verdict["runnable"]}
        self._save_meta()
        name = handle.status().name
        if skipped:
            self.notice.emit(f"DOWNLOAD GUARD · SKIPPED {len(skipped)} DANGEROUS FILE"
                             f"{'S' if len(skipped) != 1 else ''} · {name}", "warn")
        elif verdict["danger"]:
            self.notice.emit(f"DOWNLOAD GUARD · {len(verdict['danger'])} DANGEROUS FILE(S) IN {name}", "error")

    def _guard_finish(self, handle, manual: bool = False) -> None:
        """Mark-of-the-Web + scans in a worker thread. Never opens or executes the files."""
        if not (self.guard_opts["motw"] or self.guard_opts["scan"]):
            return
        key = handle_key(handle)
        if key in self._guard_running:
            return
        ti = handle.torrent_file()
        if ti is None:
            return
        status = handle.status()
        save = Path(status.save_path)
        fs = ti.files()
        priorities = handle.get_file_priorities()
        guard_meta = self.meta.get(key, {}).get("guard", {})
        runnable_idx = set(guard_meta.get("runnable", []))
        files, runnable = [], []
        for i in range(fs.num_files()):
            if fs.file_flags(i) & lt.file_storage.flag_pad_file or (i < len(priorities) and priorities[i] == 0):
                continue
            path = save / fs.file_path(i)
            files.append(path)
            if i in runnable_idx or Path(fs.file_path(i)).suffix.lower() in G.RUNNABLE:
                runnable.append(path)
        root = save / ti.name() if ti.num_files() > 1 or fs.num_files() > 1 else save / fs.file_path(0)
        self._guard_running.add(key)
        options = dict(self.guard_opts)
        name = status.name
        if manual:
            self.notice.emit(f"DOWNLOAD GUARD · SCANNING {name}…", "info")

        def work():
            try:
                result = G.finish(files, runnable, root, options)
            except Exception as exc:  # never let a scan crash the engine
                result = {"time": int(time.time()), "marked": 0, "scan": "error", "detail": [str(exc)], "threats": []}
            result["name"] = name
            self._guard_done.emit(key, result)

        threading.Thread(target=work, daemon=True, name="guard").start()

    @Slot(str, dict)
    def _on_guard_done(self, key: str, result: dict) -> None:
        self._guard_running.discard(key)
        meta = self._meta_for(key)
        meta.setdefault("guard", {})["scan"] = {k: result[k] for k in ("time", "marked", "scan", "detail", "threats")}
        self._save_meta()
        name = result.get("name", "torrent")
        if result["scan"] == "threat":
            detail = "; ".join(result["threats"])[:300]
            if self.guard_opts["pause_threat"]:
                for handle in self._handles([key]):
                    handle.unset_flags(lt.torrent_flags.auto_managed)
                    handle.pause()
            self.threat.emit(name, detail)
            self.notice.emit(f"☣ THREAT IN {name} · SEEDING STOPPED · {detail[:90]}", "error")
        elif result["scan"] == "clean":
            self.notice.emit(f"DOWNLOAD GUARD · {name} · SCANNED CLEAN · {result['marked']} FILES MARKED", "ok")
        else:
            self.notice.emit(f"DOWNLOAD GUARD · {name} · {result['marked']} FILES MARKED (SMARTSCREEN CHECKS BEFORE RUN)",
                             "ok")
        self._on_tick()

    @Slot(list)
    def scan_now(self, keys: list) -> None:
        for handle in self._handles(keys):
            if handle.status().has_metadata:
                self._guard_finish(handle, manual=True)

    def _guard_summary(self, key: str) -> dict:
        guard_meta = self.meta.get(key, {}).get("guard")
        if not guard_meta:
            return {}
        scan = guard_meta.get("scan") or {}
        return {"level": guard_meta.get("level", ""), "skipped": guard_meta.get("skipped", 0),
                "scan": "scanning" if key in self._guard_running else scan.get("scan", ""),
                "detail": "; ".join(scan.get("detail", []))[:400], "marked": scan.get("marked", 0)}

    # ------------------------------------------------------------ shield actions
    def _dht_on(self) -> bool:
        return self.flash or not self.file_only or self.use_dht

    @Slot(bool)
    def set_shield_view(self, on: bool) -> None:
        self.shield_view = on
        if on:
            self._on_tick()

    @Slot(str, bool)
    def shield_block(self, ip: str, network: bool) -> None:
        label = self.shield.block_manual(ip, network)
        if label and self.session is not None:
            self._apply_ip_filter()
            self.notice.emit(f"SHIELD · BLOCKED {label}", "ok")
            self._on_tick()

    @Slot(list)
    def shield_forget(self, keys: list) -> None:
        removed = self.shield.forget([str(k) for k in keys])
        if removed and self.session is not None:
            self._apply_ip_filter()
            self.notice.emit(f"SHIELD · UNBLOCKED {removed}", "ok")
            self._on_tick()

    @Slot()
    def shield_clear(self) -> None:
        self.shield.clear()
        if self.session is not None:
            self._apply_ip_filter()
        self.notice.emit("SHIELD · LEARNED BLOCKS CLEARED", "ok")
        self._on_tick()

    def _peer_map(self) -> list[dict]:
        rows = []
        db = self.shield.db
        for handle in self.session.get_torrents():
            if not handle.is_valid():
                continue
            name = handle.status().name or handle_key(handle)[:12]
            for p in handle.get_peer_info():
                ip, port = p.ip[0], p.ip[1]
                info = db.lookup(ip)
                try:
                    client = p.client.decode("utf-8", "replace") if isinstance(p.client, bytes) else str(p.client)
                except Exception:
                    client = "?"
                rows.append({
                    "torrent": name, "ip": ip, "port": port, "cc": info[1] if info else "",
                    "network": db.network_label(info[0]) if info else "", "client": client or "—",
                    "down": p.payload_down_speed, "up": p.payload_up_speed, "progress": float(p.progress),
                    "seed": bool(p.flags & lt.peer_info.seed), "source": source_text(p.source),
                    "direction": "out" if p.flags & lt.peer_info.outgoing_connection else "in",
                    "encrypted": bool(p.flags & (lt.peer_info.rc4_encrypted | lt.peer_info.plaintext_encrypted)),
                })
        rows.sort(key=lambda r: (r["torrent"], -r["down"], r["ip"]))
        return rows

    @Slot(dict)
    def apply_settings(self, prefs: dict) -> None:
        self.download_dir = prefs["download_dir"]
        self.upload_kib = prefs["upload_kib"]
        self.download_kib = prefs.get("download_kib", 0)
        self.listen_port = prefs.get("listen_port", 6881)
        self.max_connections = prefs.get("max_connections", 500)
        self.blocked_hosts, self.blocked_nets = parse_blocklist(prefs.get("blocked_hosts", DEFAULT_BLOCKED))
        self.file_only = bool(prefs.get("file_only", True))
        self.use_dht = bool(prefs.get("use_dht", False))
        self.accept_incoming = bool(prefs.get("accept_incoming", True))
        self.guard_opts = self._guard_options(prefs)
        self.shield.configure(prefs.get("shield_scope", "network"), bool(prefs.get("shield_learn", True)),
                              self.blocked_nets, bool(prefs.get("shield_avoid_dc", True)),
                              bool(prefs.get("shield_keep_seedboxes", True)))
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        if self.session is not None:
            pack = self._settings()
            pack.pop("dht_bootstrap_nodes", None)
            self.session.apply_settings(pack)
            self._apply_ip_filter()
            removed = sum(self._scrub_handle(h) for h in self.session.get_torrents() if h.is_valid())
            self._blocked_notice(removed)
            if removed:
                self._sweep_resume(force=True)
        self.notice.emit(f"SETTINGS SAVED · UPLOAD CAP {self.upload_kib or '∞'} KiB/s", "ok")
        self._on_tick()

    # ------------------------------------------------------------ snapshot
    def _on_tick(self) -> None:
        if self.session is None:
            return
        self._process_alerts()
        self.ticks += 1
        if self.ticks % 10 == 0:
            self._check_disk()
        if self.ticks % 2 == 0:
            self._poll_shield()
        now = time.monotonic()
        if now - self.last_resume_sweep > 60:
            self.last_resume_sweep = now
            self._sweep_resume()
        try:
            self.snapshot.emit(self._build_snapshot())
        except Exception as exc:
            self.notice.emit(f"ENGINE STATUS ERROR · {exc}", "error")

    @staticmethod
    def _state(status) -> str:
        flags = status.flags
        paused = bool(flags & lt.torrent_flags.paused)
        auto = bool(flags & lt.torrent_flags.auto_managed)
        if status.errc.value() != 0:
            return "Error"
        st = status.state
        if st in (lt.torrent_status.checking_files, lt.torrent_status.checking_resume_data):
            return "Checking"
        if paused:
            return "Queued" if auto else "Paused"
        if st == lt.torrent_status.downloading_metadata:
            return "Metadata"
        if st in (lt.torrent_status.seeding, lt.torrent_status.finished):
            return "Seeding"
        return "Downloading"

    def _build_snapshot(self) -> dict:
        rows = []
        active = 0
        total_peers = 0
        detail = None
        options = None
        for handle in self.session.get_torrents():
            if not handle.is_valid():
                continue
            status = handle.status()
            key = handle_key(handle)
            state = self._state(status)
            awaiting = self._awaiting(key)
            # a magnet fetching its file list for the Add dialog runs in upload mode too: that is not a full disk
            disk_full = bool(status.flags & lt.torrent_flags.upload_mode) and status.progress < 1.0 and not awaiting
            if disk_full:
                state = "Disk full"
            elif state == "Paused" and self.meta.get(key, {}).get("stopped"):
                state = "Stopped"
            if state in ("Downloading", "Seeding", "Checking", "Metadata"):
                active += 1
            total_peers += status.num_peers
            multi = False
            name = status.name or ""
            ti = handle.torrent_file() if status.has_metadata else None
            real_files = 0
            if ti is not None:
                real_files = self._file_counts.get(key)
                if real_files is None:          # metadata never changes, so count (non-padding) files once
                    tfs = ti.files()
                    real_files = sum(1 for i in range(tfs.num_files())
                                     if not tfs.file_flags(i) & lt.file_storage.flag_pad_file)
                    self._file_counts[key] = real_files
                multi = real_files > 1
            if not name:
                name = key[:12] + "…"
            wanted = max(0, status.total_wanted)
            done = max(0, status.total_wanted_done)
            rate = status.download_payload_rate
            eta = (wanted - done) / rate if rate > 0 and wanted > done else (-1 if wanted > done else 0)
            uploaded = status.all_time_upload
            downloaded = max(status.all_time_download, done)
            ratio = (uploaded / downloaded) if downloaded else 0.0
            self._enforce_ratio(handle, key, ratio, state)
            rows.append({
                "key": key,
                "name": name,
                "title": pretty_title(name, multi) if status.has_metadata else "Fetching metadata…",
                "sub": (f"{real_files} files · {name}/" if multi else name) if ti else "magnet · " + key[:16],
                "kind": kind_for(name, multi) if status.has_metadata else "magnet",
                "state": state,
                "progress": float(status.progress),
                "size": wanted,
                "done": done,
                "down": status.download_payload_rate,
                "up": status.upload_payload_rate,
                "eta": eta,
                "peers": status.num_peers - status.num_seeds,
                "seeds": status.num_seeds,
                "list_peers": status.list_peers,
                "list_seeds": status.list_seeds,
                "ratio": ratio,
                "uploaded": uploaded,
                "save_path": status.save_path,
                "added": status.added_time,
                "sequential": bool(status.flags & lt.torrent_flags.sequential_download),
                "error": status.errc.message() if state == "Error" else (
                    self._disk_message(status) if disk_full else ""),
                "queue": handle.queue_position(),
                "guard": self._guard_summary(key),
                "select": awaiting,
            })
            if key == self.detail_key:
                detail = self._detail(handle, status, ti)
            if key == self.options_key:
                options = self._options(handle, status)
        ss = self.session.status()
        self.history.append((ss.payload_download_rate, ss.payload_upload_rate))
        dht_nodes = int(getattr(ss, "dht_nodes", 0))
        listening = self.session.is_listening()
        if not self._dht_on():
            network, net_level = ("FILE-ONLY NETWORK", "ok") if listening else ("NOT LISTENING · CHECK PORT", "error")
        elif dht_nodes > 0:
            network, net_level = f"DHT ONLINE · {dht_nodes} NODES", "ok"
        elif time.monotonic() - self.started_at > 45:
            network, net_level = "DHT UNREACHABLE · CHECK FIREWALL", "error"
        else:
            network, net_level = "DHT CONNECTING", "warn"
        return {
            "rows": rows,
            "down": ss.payload_download_rate,
            "up": ss.payload_upload_rate,
            "history": list(self.history),
            "active": active,
            "peers": total_peers,
            "dht_nodes": dht_nodes,
            "network": network,
            "net_level": net_level,
            "upload_kib": self.upload_kib,
            "download_kib": self.download_kib,
            "port": self.session.listen_port() if listening else 0,
            "listening": listening,
            "dht_on": self._dht_on(),
            "file_only": self.file_only,
            "flash": self.flash,
            "incoming": self.accept_incoming or self.flash,
            "options": options,
            "detail": detail,
            "shield": self.shield.summary(),
            "shield_view": {"peers": self._peer_map(), "refused": list(self.shield.refused),
                            "lessons": self.shield.lessons()} if self.shield_view else None,
        }

    def _detail(self, handle, status, ti) -> dict:
        files = []
        if ti is not None:
            fs = ti.files()
            progress = handle.file_progress(lt.file_progress_flags_t.piece_granularity)
            priorities = handle.get_file_priorities()
            findings = self.meta.get(handle_key(handle), {}).get("guard", {}).get("findings", {})
            for i in range(fs.num_files()):
                if fs.file_flags(i) & lt.file_storage.flag_pad_file:
                    continue                      # alignment padding, never stored on disk
                size = fs.file_size(i)
                finding = findings.get(str(i), {})
                files.append({
                    "index": i, "path": fs.file_path(i), "size": size,
                    "progress": (progress[i] / size) if size else 1.0,
                    "priority": int(priorities[i]) if i < len(priorities) else 4,
                    "reason": finding.get("reason", ""), "danger": finding.get("level") == G.DANGER,
                })
        peers = []
        for p in handle.get_peer_info():
            try:
                client = p.client.decode("utf-8", "replace") if isinstance(p.client, bytes) else str(p.client)
            except Exception:
                client = "?"
            peers.append({"ip": f"{p.ip[0]}:{p.ip[1]}", "client": client, "progress": float(p.progress),
                          "down": p.down_speed, "up": p.up_speed,
                          "seed": bool(p.flags & lt.peer_info.seed)})
        trackers = []
        for t in handle.trackers():
            message, peers_count, working = "", 0, False
            for ep in t.get("endpoints", []):
                for ih in ep.get("info_hashes", []):
                    message = message or ih.get("message", "")
                    peers_count = max(peers_count, ih.get("scrape_complete", 0) or 0)
                    working = working or (ih.get("fails", 0) == 0 and not ih.get("updating", False)
                                          and bool(ih.get("last_error", None) is None or
                                                   getattr(ih.get("last_error"), "value", lambda: 0)() == 0))
            trackers.append({"url": t.get("url", ""), "tier": t.get("tier", 0),
                             "status": message or ("Working" if working else "Not contacted"),
                             "seeds": peers_count})
        return {
            "key": handle_key(handle),
            "name": status.name,
            "save_path": status.save_path,
            "hash": handle_key(handle),
            "pieces": f"{ti.num_pieces()} × {ti.piece_length() // 1024} KiB" if ti else "—",
            "comment": ti.comment() if ti else "",
            "creator": ti.creator() if ti else "",
            "files": files,
            "peers": peers,
            "trackers": trackers,
            "magnet": lt.make_magnet_uri(handle),
        }
