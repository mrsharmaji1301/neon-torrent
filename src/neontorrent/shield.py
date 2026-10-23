"""Peer Shield.

Malwarebytes (like most web-protection products) blocks connections by IP reputation from a private list,
so no public feed can predict it. The Shield therefore:

* reads Malwarebytes' own web-detection log and learns every IP/domain it blocked for a torrent process,
* widens a lesson to the flagged IP's /24 (or /48), and to the whole network (ASN) once a small
  hosting/VPN network has been flagged repeatedly — big consumer ISPs are never blocked wholesale,
* turns all of that into libtorrent ip_filter rules, so a flagged peer is never contacted again,
* maps every peer to its network and country using the public iptoasn.com dataset.

Everything here is plain Python (no Qt) and is driven from the engine thread.
"""
from __future__ import annotations

import bisect
import gzip
import ipaddress
import json
import os
import pickle
import socket
import threading
import time
import urllib.request
from array import array
from collections import Counter, deque
from pathlib import Path

DB_URLS = {4: "https://iptoasn.com/data/ip2asn-v4.tsv.gz", 6: "https://iptoasn.com/data/ip2asn-v6.tsv.gz"}
DB_MAX_AGE = 7 * 86400
CACHE_VERSION = 1

MB_DETECTIONS = (Path(os.environ.get("ProgramData") or r"C:\ProgramData")
                 / "Malwarebytes" / "MBAMService" / "MwacDetections")
TORRENT_PROCESSES = {
    "neontorrent.exe", "neontorrent-console.exe", "python.exe", "pythonw.exe", "neon-torrent-x64.exe",
    "utorrent.exe", "bittorrent.exe", "qbittorrent.exe", "transmission-qt.exe", "transmission-daemon.exe",
    "deluge.exe", "deluged.exe", "tixati.exe", "biglybt.exe", "vuze.exe", "azureus.exe", "frostwire.exe",
    "picotorrent.exe", "halite.exe", "free download manager.exe", "fdm.exe",
}

SCOPES = ("smart", "ip", "network")
# a network is only blocked wholesale if it is small: hosting/VPN networks are, national ISPs are not
NETWORK_BLOCK_MAX_V4 = 2_000_000
SMART_ESCALATE_AFTER = 2
# CDN / cloud backbones are never blocked wholesale: trackers and web seeds live behind them
PROTECTED_ASNS = {13335, 209242, 16625, 20940, 54113, 15169, 396982, 16509, 14618, 8075, 32934, 2906}

# Pre-contact filter: VPN and datacenter ranges (X4BNet lists_vpn, refreshed daily). Malwarebytes' private list
# flags mostly VPN exits; in this PC's history 11 of 13 flagged peers sat in these ranges and none in the big
# seedbox hosts, which stay allowed so fast seeders are not lost.
DC_FEEDS = {
    "vpn": "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/vpn/ipv4.txt",
    "datacenter": "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output/datacenter/ipv4.txt",
}
DC_EXTRA = ["104.28.0.0/16"]                    # Cloudflare WARP consumer VPN egress
DC_MAX_AGE = 86400
SEEDBOX_ASNS = {24940: "Hetzner", 16276: "OVH", 12876: "Scaleway / Online"}

BLOCKED, ALLOWED = 1, 0                         # libtorrent ip_filter access flags

SOURCE_NAMES = ((1, "tracker"), (2, "DHT"), (4, "PEX"), (8, "LSD"), (16, "resume"), (32, "incoming"))


def _ip(value: str):
    try:
        addr = ipaddress.ip_address(value.strip().strip("[]"))
    except (ValueError, AttributeError):
        return None
    if addr.version == 6 and addr.ipv4_mapped:
        return addr.ipv4_mapped
    return addr


def is_local(addr) -> bool:
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_unspecified


def neighbourhood(addr) -> ipaddress._BaseNetwork:
    return ipaddress.ip_network(f"{addr}/{24 if addr.version == 4 else 48}", strict=False)


def source_text(bits: int) -> str:
    names = [name for bit, name in SOURCE_NAMES if bits & bit]
    return ", ".join(names) if names else "—"


# ---------------------------------------------------------------------------------------------- network DB

class NetworkDB:
    """IP -> (ASN, country, organisation) from iptoasn.com, cached locally and refreshed weekly."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.ready = False
        self.status = "not loaded"
        # (v4_start, v4_end, v4_asn, v6_start, v6_end, v6_asn) swapped as one tuple so readers never mix versions
        self.tables: tuple = (array("I"), array("I"), array("I"), [], [], array("I"))
        self.names: dict[int, tuple[str, str]] = {}
        self.v4_size: Counter = Counter()
        self._ranges_cache: dict[int, list[tuple[str, str]]] = {}
        self._lookup_cache: dict[str, tuple | None] = {}

    # -- loading
    def start(self, on_ready) -> None:
        threading.Thread(target=self._run, args=(on_ready,), daemon=True, name="networkdb").start()

    def _cache_path(self) -> Path:
        return self.folder / "ip2asn.cache"

    def _run(self, on_ready) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            cache = self._cache_path()
            fresh = cache.exists() and time.time() - cache.stat().st_mtime < DB_MAX_AGE
            if cache.exists() and self._load_cache(cache):
                self._publish(on_ready)
                if fresh:
                    return
            self.status = "downloading network database…"
            data = {v: self._download(url) for v, url in DB_URLS.items()}
            self.status = "parsing network database…"
            self._parse(data[4], data[6])
            self._save_cache(cache)
            self._publish(on_ready)
        except Exception as exc:  # offline or blocked: keep whatever was loaded
            self.status = f"network DB unavailable ({exc.__class__.__name__})" if not self.ready else self.status

    def _publish(self, on_ready) -> None:
        self._ranges_cache.clear()
        self._lookup_cache.clear()
        self.ready = True
        self.status = f"{len(self.tables[0]) + len(self.tables[3]):,} ranges · {len(self.names):,} networks"
        on_ready()

    @staticmethod
    def _download(url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "NeonTorrent/2.0 (+peer shield)"})
        with urllib.request.urlopen(request, timeout=90) as response:
            return gzip.decompress(response.read())

    def _parse(self, v4: bytes, v6: bytes) -> None:
        s4, e4, a4 = array("I"), array("I"), array("I")
        s6, e6, a6 = [], [], array("I")
        names: dict[int, tuple[str, str]] = {}
        size = Counter()
        aton = socket.inet_aton
        for line in v4.decode("utf-8", "replace").splitlines():
            parts = line.split("\t")
            if len(parts) < 5 or parts[2] == "0":
                continue
            start, end, asn = int.from_bytes(aton(parts[0]), "big"), int.from_bytes(aton(parts[1]), "big"), int(parts[2])
            s4.append(start); e4.append(end); a4.append(asn)
            size[asn] += end - start + 1
            names[asn] = (parts[3], parts[4])
        for line in v6.decode("utf-8", "replace").splitlines():
            parts = line.split("\t")
            if len(parts) < 5 or parts[2] == "0":
                continue
            s6.append(int(ipaddress.IPv6Address(parts[0]))); e6.append(int(ipaddress.IPv6Address(parts[1])))
            a6.append(int(parts[2]))
            names.setdefault(int(parts[2]), (parts[3], parts[4]))
        self.names, self.v4_size = names, size
        self.tables = (s4, e4, a4, s6, e6, a6)

    def _save_cache(self, path: Path) -> None:
        s4, e4, a4, s6, e6, a6 = self.tables
        blob = {
            "version": CACHE_VERSION, "v4s": s4.tobytes(), "v4e": e4.tobytes(), "v4a": a4.tobytes(),
            "v6s": b"".join(x.to_bytes(16, "big") for x in s6), "v6e": b"".join(x.to_bytes(16, "big") for x in e6),
            "v6a": a6.tobytes(),
            "names": self.names, "size": dict(self.v4_size),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(blob, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(path)

    def _load_cache(self, path: Path) -> bool:
        try:
            blob = pickle.loads(path.read_bytes())
            if blob.get("version") != CACHE_VERSION:
                return False
            s4, e4, a4, a6 = array("I"), array("I"), array("I"), array("I")
            s4.frombytes(blob["v4s"]); e4.frombytes(blob["v4e"]); a4.frombytes(blob["v4a"]); a6.frombytes(blob["v6a"])
            v6s, v6e = blob["v6s"], blob["v6e"]
            s6 = [int.from_bytes(v6s[i:i + 16], "big") for i in range(0, len(v6s), 16)]
            e6 = [int.from_bytes(v6e[i:i + 16], "big") for i in range(0, len(v6e), 16)]
            self.names, self.v4_size = blob["names"], Counter(blob["size"])
            self.tables = (s4, e4, a4, s6, e6, a6)
            return True
        except Exception:
            return False

    # -- queries
    def lookup(self, ip: str):
        """(asn, country, org) or None."""
        if not self.ready:
            return None
        if ip in self._lookup_cache:
            return self._lookup_cache[ip]
        addr = _ip(ip)
        result = None
        if addr is not None:
            x = int(addr)
            tables = self.tables
            starts, ends, asns = tables[:3] if addr.version == 4 else tables[3:]
            i = bisect.bisect_right(starts, x) - 1
            if i >= 0 and x <= ends[i]:
                asn = asns[i]
                cc, org = self.names.get(asn, ("??", ""))
                result = (asn, cc, org)
        if len(self._lookup_cache) > 50_000:
            self._lookup_cache.clear()
        self._lookup_cache[ip] = result
        return result

    def ranges(self, asn: int) -> list[tuple[str, str]]:
        if asn in self._ranges_cache:
            return self._ranges_cache[asn]
        out = []
        s4, e4, a4, s6, e6, a6 = self.tables
        for i, a in enumerate(a4):
            if a == asn:
                out.append((str(ipaddress.IPv4Address(s4[i])), str(ipaddress.IPv4Address(e4[i]))))
        for i, a in enumerate(a6):
            if a == asn:
                out.append((str(ipaddress.IPv6Address(s6[i])), str(ipaddress.IPv6Address(e6[i]))))
        self._ranges_cache[asn] = out
        return out

    def network_label(self, asn: int) -> str:
        cc, org = self.names.get(asn, ("", ""))
        return f"AS{asn} {org}".strip()


# ---------------------------------------------------------------------------------------------- VPN/datacenter feed

class RangeFeed:
    """Merged IPv4 ranges of VPN and datacenter networks, used to refuse such peers before any contact."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.ready = False
        self.status = "not loaded"
        self.tables: tuple = (array("I"), array("I"))      # (starts, ends), swapped as one tuple
        self._rules: list[tuple[str, str]] = []

    def start(self, on_ready) -> None:
        threading.Thread(target=self._run, args=(on_ready,), daemon=True, name="dcfeed").start()

    def _run(self, on_ready) -> None:
        cache = self.folder / "vpn_dc.cache"
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fresh = cache.exists() and time.time() - cache.stat().st_mtime < DC_MAX_AGE
            if cache.exists() and self._load(cache):
                self._publish(on_ready)
                if fresh:
                    return
            self.status = "downloading VPN/datacenter ranges…"
            intervals = []
            for url in DC_FEEDS.values():
                intervals.extend(self._fetch(url))
            for extra in DC_EXTRA:
                net = ipaddress.ip_network(extra)
                intervals.append((int(net[0]), int(net[-1])))
            self._build(intervals)
            self._save(cache)
            self._publish(on_ready)
        except Exception as exc:
            if not self.ready:
                self.status = f"VPN/datacenter list unavailable ({exc.__class__.__name__})"

    @staticmethod
    def _fetch(url: str) -> list[tuple[int, int]]:
        request = urllib.request.Request(url, headers={"User-Agent": "NeonTorrent/2.0 (+peer shield)"})
        with urllib.request.urlopen(request, timeout=90) as response:
            text = response.read().decode("utf-8", "replace")
        out = []
        for line in text.splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            try:
                net = ipaddress.ip_network(line, strict=False)
            except ValueError:
                continue
            if net.version == 4 and not net.is_private:
                out.append((int(net[0]), int(net[-1])))
        return out

    def _build(self, intervals: list[tuple[int, int]]) -> None:
        intervals.sort()
        starts, ends = array("I"), array("I")
        for a, b in intervals:
            if ends and a <= ends[-1] + 1:
                if b > ends[-1]:
                    ends[-1] = b
            else:
                starts.append(a)
                ends.append(b)
        self.tables = (starts, ends)

    def _save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        starts, ends = self.tables
        tmp.write_bytes(pickle.dumps({"s": starts.tobytes(), "e": ends.tobytes()}))
        tmp.replace(path)

    def _load(self, path: Path) -> bool:
        try:
            blob = pickle.loads(path.read_bytes())
            starts, ends = array("I"), array("I")
            starts.frombytes(blob["s"])
            ends.frombytes(blob["e"])
            self.tables = (starts, ends)
            return len(starts) > 0
        except Exception:
            return False

    def _publish(self, on_ready) -> None:
        starts, ends = self.tables
        self._rules = [(socket.inet_ntoa(a.to_bytes(4, "big")), socket.inet_ntoa(b.to_bytes(4, "big")))
                       for a, b in zip(starts, ends)]
        total = sum(b - a + 1 for a, b in zip(starts, ends))
        self.ready = True
        self.status = f"{len(starts):,} VPN/datacenter ranges · {total / 1e6:.0f}M IPs"
        on_ready()

    def contains(self, addr) -> bool:
        if not self.ready or addr.version != 4:
            return False
        x = int(addr)
        starts, ends = self.tables
        i = bisect.bisect_right(starts, x) - 1
        return i >= 0 and x <= ends[i]

    def rules(self) -> list[tuple[str, str]]:
        return self._rules if self.ready else []


# ---------------------------------------------------------------------------------------------- antivirus log

class MalwarebytesWatcher:
    """Reads Malwarebytes' web-protection detections (one JSON file per blocked connection)."""

    def __init__(self, seen: set[str]):
        self.seen = seen
        self.failures: Counter = Counter()

    @property
    def available(self) -> bool:
        return MB_DETECTIONS.is_dir()

    def poll(self) -> list[dict]:
        if not self.available:
            return []
        found = []
        try:
            entries = list(os.scandir(MB_DETECTIONS))
        except OSError:
            return []
        for entry in entries:
            name = entry.name
            if not name.endswith(".json") or name in self.seen:
                continue
            try:
                text = Path(entry.path).read_text(encoding="utf-8", errors="replace")
                data = json.loads(text[text.index("{"):])
            except (OSError, ValueError):
                self.failures[name] += 1          # may still be being written; retry a few times
                if self.failures[name] > 5:
                    self.seen.add(name)
                continue
            self.seen.add(name)
            for threat in data.get("threats", []):
                web = (threat.get("mainTrace") or {}).get("websiteData") or {}
                process = Path(str(web.get("processPath", ""))).name.lower()
                if process not in TORRENT_PROCESSES or not web.get("ip"):
                    continue
                found.append({
                    "ip": str(web.get("ip", "")), "port": int(web.get("port") or 0),
                    "proto": str(web.get("netProtocol", "")), "inbound": bool(web.get("isInbound")),
                    "domain": str(web.get("url", "") or "").strip().lower(), "process": process,
                    "time": str(data.get("detectionDateTime", "")), "file": name,
                })
        return found


# ---------------------------------------------------------------------------------------------- shield

class Shield:
    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / "learned.json"
        self.db = NetworkDB(folder)
        self.feed = RangeFeed(folder)
        self.scope = "network"
        self.learn = True
        self.avoid_dc = True                  # refuse VPN/datacenter peers before any contact
        self.keep_seedboxes = True            # ...except the big seedbox hosts
        self.allow_ips: set[str] = set()      # resolved web-seed (HTTP mirror) addresses
        self.manual_nets: list = []           # from the user's blocklist text
        self.data = self._load()
        self.watcher = MalwarebytesWatcher(set(self.data["seen"]))
        self.refused = deque(maxlen=400)
        self.refused_total = 0
        self.refused_ips: set[str] = set()
        self._explain_cache: dict[str, str | None] = {}

    # -- persistence
    def _load(self) -> dict:
        base = {"ips": {}, "domains": {}, "ignored": [], "manual_asns": {}, "manual_ips": {}, "seen": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base.update({k: data[k] for k in base if k in data})
        except (OSError, ValueError):
            pass
        return base

    def save(self) -> None:
        self.data["seen"] = sorted(self.watcher.seen) if hasattr(self, "watcher") else self.data["seen"]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def configure(self, scope: str, learn: bool, manual_nets: list, avoid_dc: bool = True,
                  keep_seedboxes: bool = True) -> None:
        self.scope = scope if scope in SCOPES else "network"
        self.learn = learn
        self.manual_nets = list(manual_nets)
        self.avoid_dc = avoid_dc
        self.keep_seedboxes = keep_seedboxes
        self._explain_cache.clear()

    def set_allowed(self, ips: set[str]) -> bool:
        """Web-seed mirror addresses that must stay reachable. Returns True if the set changed."""
        if ips == self.allow_ips:
            return False
        self.allow_ips = set(ips)
        self._explain_cache.clear()
        return True

    # -- learning
    def poll_antivirus(self) -> list[str]:
        """Returns human-readable lessons learned since the last poll."""
        if not self.learn:
            return []
        lessons = []
        for det in self.watcher.poll():
            lesson = self._learn(det)
            if lesson:
                lessons.append(lesson)
        if lessons or self.watcher.seen.symmetric_difference(self.data["seen"]):
            self._explain_cache.clear()
            self.save()
        return lessons

    def _learn(self, det: dict) -> str | None:
        addr = _ip(det["ip"])
        if addr is None or is_local(addr):
            return None
        ip = str(addr)
        if ip in self.data["ignored"]:
            return None
        if det["domain"]:
            domain = det["domain"]
            if domain not in self.data["domains"] and domain not in self.data["ignored"]:
                self.data["domains"][domain] = {"time": det["time"], "process": det["process"]}
            # shared web hosting: block the exact address only, never its neighbours
            kind = "host"
        else:
            kind = "peer"
        entry = self.data["ips"].get(ip)
        if entry:
            entry["count"] = entry.get("count", 1) + 1
            entry["last"] = det["time"]
            return None
        self.data["ips"][ip] = {"kind": kind, "port": det["port"], "proto": det["proto"], "first": det["time"],
                                "last": det["time"], "count": 1, "process": det["process"],
                                "domain": det["domain"], "inbound": det["inbound"]}
        what = det["domain"] or ip
        info = self.db.lookup(ip)
        where = f" · {self.db.network_label(info[0])}" if info else ""
        return f"{what}{where}"

    def block_manual(self, ip: str, network: bool) -> str:
        addr = _ip(ip)
        if addr is None:
            return ""
        ip = str(addr)
        if ip in self.data["ignored"]:
            self.data["ignored"].remove(ip)
        info = self.db.lookup(ip)
        if network and info:
            self.data["manual_asns"][str(info[0])] = {"label": self.db.network_label(info[0]), "time": _now()}
            label = self.db.network_label(info[0])
        else:
            self.data["manual_ips"][ip] = {"time": _now()}
            label = ip
        self._explain_cache.clear()
        self.save()
        return label

    def forget(self, keys: list[str]) -> int:
        removed = 0
        for key in keys:
            if key.startswith("AS") and key[2:].isdigit():
                removed += self.data["manual_asns"].pop(key[2:], None) is not None
                continue
            for bucket in ("ips", "domains", "manual_ips"):
                if self.data[bucket].pop(key, None) is not None:
                    removed += 1
                    if bucket != "manual_ips" and key not in self.data["ignored"]:
                        self.data["ignored"].append(key)     # do not re-learn it from old detections
        self._explain_cache.clear()
        self.save()
        return removed

    def clear(self) -> None:
        self.data["ignored"] = sorted(set(self.data["ignored"]) | set(self.data["ips"]) | set(self.data["domains"]))
        for bucket in ("ips", "domains", "manual_asns", "manual_ips"):
            self.data[bucket] = {}
        self._explain_cache.clear()
        self.save()

    # -- rules
    def blocked_domains(self) -> set[str]:
        return set(self.data["domains"]) if self.learn else set()

    def _peer_ips(self) -> list:
        return [_ip(ip) for ip, e in self.data["ips"].items() if e.get("kind") == "peer" and _ip(ip)]

    def blocked_asns(self) -> dict[int, str]:
        """ASN -> reason for networks blocked as a whole."""
        out = {int(asn): "Blocked by you" for asn in self.data["manual_asns"]}
        if not self.learn or not self.db.ready or self.scope == "ip":
            return out
        per_asn: Counter = Counter()
        for addr in self._peer_ips():
            info = self.db.lookup(str(addr))
            if info:
                per_asn[info[0]] += 1
        need = 1 if self.scope == "network" else SMART_ESCALATE_AFTER
        for asn, hits in per_asn.items():
            if asn in PROTECTED_ASNS:
                continue
            if hits >= need and self.db.v4_size.get(asn, 0) <= NETWORK_BLOCK_MAX_V4:
                out.setdefault(asn, f"Network flagged {hits}× by Malwarebytes")
        return out

    def rules(self) -> list[tuple[str, str, int]]:
        """Ordered ip_filter rules (first, last, access); later rules override earlier ones:
        1. VPN/datacenter ranges blocked, 2. seedbox hosts and web-seed mirrors allowed again,
        3. everything flagged by Malwarebytes or blocked by the user blocked (wins over 2)."""
        out: list[tuple[str, str, int]] = []
        if self.avoid_dc and self.feed.ready:
            out.extend((a, b, BLOCKED) for a, b in self.feed.rules())
            if self.keep_seedboxes and self.db.ready:
                for asn in SEEDBOX_ASNS:
                    out.extend((a, b, ALLOWED) for a, b in self.db.ranges(asn))
            out.extend((ip, ip, ALLOWED) for ip in self.allow_ips)
        for net in self.manual_nets:
            out.append((str(net[0]), str(net[-1]), BLOCKED))
        for ip in self.data["manual_ips"]:
            out.append((ip, ip, BLOCKED))
        if self.learn:
            for ip, entry in self.data["ips"].items():
                addr = _ip(ip)
                if addr is None:
                    continue
                out.append((str(addr), str(addr), BLOCKED))
                if entry.get("kind") == "peer" and self.scope != "ip":
                    net = neighbourhood(addr)
                    out.append((str(net[0]), str(net[-1]), BLOCKED))
        if self.db.ready:
            for asn in self.blocked_asns():
                out.extend((a, b, BLOCKED) for a, b in self.db.ranges(asn))
        return out

    def explain(self, ip: str, include_feed: bool = True) -> str | None:
        """Why an address is blocked (None if it is not). include_feed=False for trackers, which live in
        datacenters by nature and are only filtered by what was actually flagged."""
        cache_key = f"{ip}|{int(include_feed)}"
        if cache_key in self._explain_cache:
            return self._explain_cache[cache_key]
        addr = _ip(ip)
        reason = None
        if addr is not None and str(addr) in self.data["manual_ips"]:
            reason = "Blocked by you"
        elif addr is not None and not is_local(addr):
            key = str(addr)
            info = self.db.lookup(key)
            if any(addr in net for net in self.manual_nets if net.version == addr.version):
                reason = "Your blocklist"
            elif self.learn and key in self.data["ips"]:
                entry = self.data["ips"][key]
                reason = f"Flagged by Malwarebytes ({entry.get('domain') or entry.get('proto', '')})"
            elif self.learn and self.scope != "ip" and any(
                    addr in neighbourhood(p) for p in self._peer_ips() if p.version == addr.version):
                reason = "Neighbour of a flagged peer"
            elif info and info[0] in (blocked := self.blocked_asns()):
                reason = f"{blocked[info[0]]}: {self.db.network_label(info[0])}"
            elif (include_feed and self.avoid_dc and key not in self.allow_ips and self.feed.contains(addr)
                  and not (self.keep_seedboxes and info and info[0] in SEEDBOX_ASNS)):
                reason = "VPN / datacenter range (refused before contact)"
        if len(self._explain_cache) > 20_000:
            self._explain_cache.clear()
        self._explain_cache[cache_key] = reason
        return reason

    def record_refused(self, ip: str, port: int, torrent: str) -> None:
        self.refused_total += 1
        self.refused_ips.add(ip)
        info = self.db.lookup(ip)
        self.refused.appendleft({
            "time": time.strftime("%H:%M:%S"), "ip": ip, "port": port, "torrent": torrent,
            "reason": self.explain(ip) or "Blocked", "network": self.db.network_label(info[0]) if info else "",
            "cc": info[1] if info else "",
        })

    # -- reporting
    def lessons(self) -> list[dict]:
        rows = []
        for ip, e in self.data["ips"].items():
            info = self.db.lookup(ip)
            rows.append({"key": ip, "type": "Tracker host" if e.get("kind") == "host" else "Peer",
                         "value": e.get("domain") or ip, "network": self.db.network_label(info[0]) if info else "",
                         "cc": info[1] if info else "", "seen": e.get("count", 1), "when": e.get("last", "")[:16],
                         "origin": f"Malwarebytes · {e.get('process', '')}"})
        for domain, e in self.data["domains"].items():
            rows.append({"key": domain, "type": "Tracker domain", "value": domain, "network": "", "cc": "",
                         "seen": 1, "when": e.get("time", "")[:16], "origin": f"Malwarebytes · {e.get('process', '')}"})
        for asn, reason in self.blocked_asns().items():
            manual = str(asn) in self.data["manual_asns"]
            rows.append({"key": f"AS{asn}", "type": "Whole network", "value": self.db.network_label(asn) or f"AS{asn}",
                         "network": f"{self.db.v4_size.get(asn, 0):,} IPv4 addresses", "cc": self.db.names.get(asn, ("",))[0],
                         "seen": "", "when": "", "origin": "You" if manual else reason})
        for ip, e in self.data["manual_ips"].items():
            info = self.db.lookup(ip)
            rows.append({"key": ip, "type": "IP (manual)", "value": ip,
                         "network": self.db.network_label(info[0]) if info else "", "cc": info[1] if info else "",
                         "seen": "", "when": e.get("time", "")[:16], "origin": "You"})
        return rows

    def summary(self) -> dict:
        return {
            "learn": self.learn, "scope": self.scope, "av": "watching" if self.watcher.available else "not found",
            "learned_ips": len(self.data["ips"]), "learned_domains": len(self.data["domains"]),
            "networks": len(self.blocked_asns()), "refused": self.refused_total,
            "refused_unique": len(self.refused_ips), "db": self.db.status, "db_ready": self.db.ready,
            "avoid_dc": self.avoid_dc, "keep_seedboxes": self.keep_seedboxes, "dc": self.feed.status,
            "dc_ready": self.feed.ready,
        }


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
