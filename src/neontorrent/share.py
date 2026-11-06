"""File Sharing (C-11): send files between this PC and a phone on the same Wi-Fi.

The phone needs only its browser. While a sharing session is open, a small HTTP server listens on the LAN IPv4
address (random port) and serves the phone page plus a tiny JSON/binary API. Plain HTTP carries only ciphertext:

* The QR code holds the URL plus, in the #fragment (browsers never send it over the network), this PC's ephemeral
  X25519 public key and a one-time pairing token.
* The phone makes its own ephemeral X25519 key. Both sides run HKDF-SHA256 over the shared secret (salt = token)
  and get two 32-byte keys, one per direction.
* Every control message and every file chunk (1 MiB) is sealed with ChaCha20-Poly1305. Nonces are unique per
  direction, file and chunk; the file number, chunk index and chunk count are bound in as associated data, so a
  wrong token, a reordered, truncated or tampered chunk, or a replayed message is rejected.

Internet mode: a Cloudflare quick tunnel (cloudflared, no account) forwards https://<random>.trycloudflare.com to
this server, so the phone can connect from anywhere. Cloudflare only ever sees the same ciphertext. When the phone
turns out to share this PC's public IP, the page moves itself to the LAN address and the transfer stays local.

Nothing here touches Qt: the UI polls ``ShareServer.snapshot()`` and calls the thread-safe methods directly.
"""
from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PROTOCOL = b"NEON-SHARE-1"
FILE_AAD = b"NEON-FILE-1"
CHUNK = 1 << 20                      # plaintext bytes per sealed chunk
TAG = 16                             # Poly1305 tag
MAX_CONTROL = 512 * 1024             # largest control request body
MAX_FILE = 1 << 40                   # 1 TiB: anything larger is a lie
HEARTBEAT_LOST = 8.0                 # seconds without a ping before the phone shows as Disconnected
SESSION_EXPIRY = 600.0               # an approved phone silent this long has to scan again
PENDING_EXPIRY = 120.0               # an unanswered approval request is dropped after this
MAX_PENDING = 3
MAX_HELLO_FAILS = 8                  # wrong-token attempts per IP before it is ignored for this session
MAX_FAIL_IPS = 4096                  # distinct failing IPs remembered; beyond that every new one is refused
MAX_CONNECTIONS = 48                 # concurrent HTTP connections (handler threads); more are dropped
MAX_UPLOADS = 4                      # open uploads per phone
MAX_TEXT = 20_000                    # characters per text message from the phone (fits MAX_CONTROL when sealed)
MAX_INBOX = 200                      # text messages waiting for the UI; the oldest go first
DISK_RESERVE = 64 << 20              # keep this much free on the target drive
PART_SUFFIX = ".neonpart"
WEB_DIR = Path(__file__).resolve().parent / "share_web"
WEB_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
             "/index.html": ("index.html", "text/html; charset=utf-8"),
             "/app.js": ("app.js", "text/javascript; charset=utf-8"),
             "/app.css": ("app.css", "text/css; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src blob:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
CLOUDFLARED = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "cloudflared" / "cloudflared.exe"
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
TRACE_URLS = ("https://1.1.1.1/cdn-cgi/trace", "https://[2606:4700:4700::1111]/cdn-cgi/trace",
              "https://www.cloudflare.com/cdn-cgi/trace")
TUNNEL_PREFIX = "cf:"                # peer key of a request that came through the tunnel: "cf:<public IP>"
PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")]

# nonce kinds: byte 0 of every nonce, so the two directions and the two message types can never collide
K_CTL_UP, K_CTL_DOWN, K_FILE_UP, K_FILE_DOWN = 1, 2, 3, 4


class ShareError(Exception):
    """A request the server refuses; ``status`` is the HTTP status sent back."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ encoding and crypto
def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


_B64 = re.compile(r"[A-Za-z0-9_-]*")


def b64d(text: object) -> bytes:
    if not isinstance(text, str) or not _B64.fullmatch(text):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def nonce(kind: int, number: int, index: int) -> bytes:
    """12-byte nonce: kind (1 byte) | file number (3 bytes) | chunk index or message counter (8 bytes)."""
    if not (0 <= kind < 256 and 0 <= number < 1 << 24 and 0 <= index < 1 << 64):
        raise ValueError("nonce field out of range")
    return bytes([kind]) + number.to_bytes(3, "big") + index.to_bytes(8, "big")


def chunk_aad(direction: bytes, number: int, index: int, chunks: int) -> bytes:
    return FILE_AAD + direction + struct.pack(">IQQ", number, index, chunks)


def chunk_count(size: int) -> int:
    return max(1, math.ceil(size / CHUNK))           # an empty file is one empty chunk


def chunk_length(size: int, index: int) -> int:
    return CHUNK if index < chunk_count(size) - 1 else size - CHUNK * (chunk_count(size) - 1)


def derive_keys(shared: bytes, token: bytes, pc_pub: bytes, phone_pub: bytes) -> tuple[bytes, bytes]:
    """(phone->PC key, PC->phone key) from the X25519 secret; the token is the HKDF salt."""
    if len(shared) != 32 or shared == bytes(32):
        raise ValueError("low-order public key")
    okm = HKDF(algorithm=hashes.SHA256(), length=64, salt=token, info=PROTOCOL + pc_pub + phone_pub).derive(shared)
    return okm[:32], okm[32:]


class Channel:
    """Both directions of one paired session. ``role`` is "pc" here and "phone" in the tests' phone stand-in."""

    def __init__(self, phone_to_pc: bytes, pc_to_phone: bytes, role: str = "pc"):
        up, down = ChaCha20Poly1305(phone_to_pc), ChaCha20Poly1305(pc_to_phone)
        pc = role == "pc"
        self.rx, self.tx = (up, down) if pc else (down, up)
        self.rx_ctl, self.tx_ctl = (K_CTL_UP, K_CTL_DOWN) if pc else (K_CTL_DOWN, K_CTL_UP)
        self.rx_file, self.tx_file = (K_FILE_UP, K_FILE_DOWN) if pc else (K_FILE_DOWN, K_FILE_UP)
        self.rx_dir, self.tx_dir = (b"up", b"dn") if pc else (b"dn", b"up")

    def seal(self, message: dict, counter: int, aad: bytes) -> str:
        data = json.dumps(message, separators=(",", ":")).encode("utf-8")
        return b64e(self.tx.encrypt(nonce(self.tx_ctl, 0, counter), data, aad))

    def open(self, sealed: object, counter: int, aad: bytes) -> dict:
        message = json.loads(self.rx.decrypt(nonce(self.rx_ctl, 0, counter), b64d(sealed), aad))
        if not isinstance(message, dict):
            raise ValueError("control message is not an object")
        return message

    def seal_chunk(self, number: int, index: int, chunks: int, data: bytes) -> bytes:
        return self.tx.encrypt(nonce(self.tx_file, number, index), data, chunk_aad(self.tx_dir, number, index, chunks))

    def open_chunk(self, number: int, index: int, chunks: int, data: bytes) -> bytes:
        return self.rx.decrypt(nonce(self.rx_file, number, index), data, chunk_aad(self.rx_dir, number, index, chunks))


class Pairing:
    """What the QR code carries: an ephemeral X25519 key and a one-time token. Replaced after every decision."""

    def __init__(self):
        self.private = X25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes_raw()
        self.token = secrets.token_bytes(16)
        self.used: set[bytes] = set()                 # phone keys already seen: a replayed hello is refused

    def keys_for(self, phone_pub: bytes) -> tuple[bytes, bytes]:
        shared = self.private.exchange(X25519PublicKey.from_public_bytes(phone_pub))
        return derive_keys(shared, self.token, self.public, phone_pub)


# ------------------------------------------------------------------ names and paths
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
             *(f"COM{i}" for i in "123456789¹²³"), *(f"LPT{i}" for i in "123456789¹²³")}
_FORBIDDEN = set('<>:"/\\|?*')


def safe_name(name: object, limit: int = 150) -> str:
    """A file name from the phone, made safe for Windows: no folders, no control, bidi or reserved characters,
    no reserved device names, no trailing dots or spaces, at most ``limit`` characters."""
    text = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").split("/")[-1]
    text = "".join("_" if ch in _FORBIDDEN else ch for ch in text
                   if unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"))
    text = text.strip().rstrip(". ")
    if not text.strip("."):
        text = "file"
    stem, ext = os.path.splitext(text)
    if text.split(".")[0].strip().upper() in _RESERVED:
        stem, text = "_" + stem, "_" + text
    if len(text) > limit:
        ext = ext if len(ext) <= 16 else ""
        text = stem[:max(1, limit - len(ext))].rstrip(". ") + ext
    return text


def clean_label(value: object, limit: int) -> str:
    """Device name or model typed on the phone, safe to show: one line, printable, bounded."""
    text = "".join(" " if ch.isspace() else ch for ch in str(value or "") if unicodedata.category(ch)[0] != "C"
                   or ch.isspace())
    return " ".join(text.split())[:limit]


# bidirectional overrides and isolates: they can make shown text read differently from what was sent
_BIDI_CONTROLS = set("‪‫‬‭‮⁦⁧⁨⁩")


def clean_text(value: object, limit: int = MAX_TEXT) -> str:
    """Text pasted on the phone, safe to show and copy as plain text: line breaks and tabs kept, other control and
    bidirectional-override characters removed. Raises ShareError when it is not text, empty or too long."""
    if not isinstance(value, str):
        raise ShareError(400, "text must be a string")
    if len(value) > limit:
        raise ShareError(413, f"text is longer than {limit} characters")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in value if ch in "\n\t" or (unicodedata.category(ch) not in ("Cc", "Cs", "Co", "Cn")
                                                          and ch not in _BIDI_CONTROLS))
    if not text.strip():
        raise ShareError(400, "empty text")
    return text


def unique_path(folder: Path, name: str) -> Path:
    """folder/name, or "name (1).ext", "name (2).ext" … if it exists. Always directly inside ``folder``."""
    stem, ext = os.path.splitext(name)
    candidate, n = folder / name, 1
    while candidate.exists():
        candidate, n = folder / f"{stem} ({n}){ext}", n + 1
    if candidate.resolve().parent != folder.resolve():
        raise ShareError(400, "bad file name")
    return candidate


def commit_file(part: Path, folder: Path, name: str) -> Path:
    """Move a finished upload to its final, de-duplicated name. os.rename never overwrites on Windows, so a file
    that appears between the check and the move just bumps the number."""
    for _ in range(1000):
        target = unique_path(folder, name)
        try:
            os.rename(part, target)
            return target
        except FileExistsError:
            continue
    raise ShareError(500, "could not pick a free file name")


# ------------------------------------------------------------------ network facts
def is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.version == 4 and any(addr in net for net in PRIVATE_NETS)


def lan_ipv4() -> str | None:
    """This PC's private IPv4 address on the network that carries its default route (Wi-Fi or Ethernet)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.254.254.254", 9))     # UDP connect only picks a route; no packet is sent
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    private = [ip for ip in found if is_private_ip(ip)]
    private.sort(key=lambda ip: ip.startswith("169.254."))      # link-local only as a last resort
    return private[0] if private else None


def mac_for(ip: str) -> str:
    """The MAC address the phone uses on this network, from the ARP table (iphlpapi SendARP)."""
    try:
        dest = struct.unpack("<I", socket.inet_aton(ip))[0]
        buf, size = (ctypes.c_ubyte * 8)(), ctypes.c_ulong(8)
        if ctypes.windll.iphlpapi.SendARP(dest, 0, buf, ctypes.byref(size)) != 0 or size.value != 6:
            return ""
        return "-".join(f"{b:02X}" for b in buf[:6])
    except (OSError, AttributeError, ValueError):
        return ""


def mac_is_private(mac: str) -> bool:
    """Phones use a random "private" MAC per Wi-Fi network; those have the locally-administered bit set."""
    try:
        return bool(int(mac[:2], 16) & 0x02)
    except ValueError:
        return False


def pc_network(ip: str) -> dict:
    """MAC, adapter name and Wi-Fi name (SSID) of the adapter that owns ``ip``. Slow (PowerShell): call it
    from a worker thread. Windows hides the Wi-Fi name from apps without Location access, so it can be ""."""
    info = {"ip": ip, "mac": "", "adapter": "", "wifi": False, "ssid": ""}
    try:
        ipaddress.IPv4Address(ip)                    # only a literal address ever reaches the script
    except ValueError:
        return info
    script = (f"$a = Get-NetIPAddress -AddressFamily IPv4 -IPAddress '{ip}' -ErrorAction SilentlyContinue | "
              "Get-NetAdapter -ErrorAction SilentlyContinue | Select-Object -First 1; $s = ''; "
              "if ($a -and ($a.PhysicalMediaType -match '802\\.11|Wireless' -or "
              "$a.InterfaceDescription -match 'Wi-?Fi|Wireless|WLAN')) { $w = $true; "
              "$l = netsh wlan show interfaces | Select-String '^\\s*SSID\\s*:' | Select-Object -First 1; "
              "if ($l) { $s = ($l.ToString() -split ':', 2)[1].Trim() } } else { $w = $false }; "
              "[pscustomobject]@{mac = $a.MacAddress; adapter = $a.Name; wifi = $w; ssid = $s} | "
              "ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        data = json.loads(out.strip() or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return info
    if isinstance(data, dict):
        info.update(mac=clean_label(data.get("mac"), 32), adapter=clean_label(data.get("adapter"), 80),
                    wifi=bool(data.get("wifi")), ssid=clean_label(data.get("ssid"), 64))
    return info


def public_ips() -> set[str]:
    """This PC's public IPv4 and IPv6 address as Cloudflare sees them (trace endpoint, both address families)."""
    found: set[str] = set()
    for url in TRACE_URLS:
        try:
            with urlopen(Request(url, headers={"User-Agent": "NEON"}), timeout=5) as response:
                text = response.read(4096).decode("ascii", "replace")
        except (OSError, ValueError):
            continue
        for line in text.splitlines():
            if line.startswith("ip="):
                try:
                    found.add(str(ipaddress.ip_address(line[3:].strip())))
                except ValueError:
                    pass
    return found


def same_network(phone_ip: str, pc_ips: set[str]) -> bool:
    """Phone and PC behind the same router: same public IPv4, or the same IPv6 /64."""
    try:
        phone = ipaddress.ip_address(phone_ip)
    except ValueError:
        return False
    for raw in pc_ips:
        pc = ipaddress.ip_address(raw)
        if pc.version != phone.version:
            continue
        if phone == pc or (pc.version == 6 and phone in ipaddress.ip_network(f"{pc}/64", strict=False)):
            return True
    return False


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("r_ops", "w_ops", "o_ops", "r_bytes", "w_bytes", "o_bytes")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("user_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong), ("flags", ctypes.c_uint32),
                ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("processes", ctypes.c_uint32),
                ("affinity", ctypes.c_size_t), ("priority", ctypes.c_uint32), ("scheduling", ctypes.c_uint32)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", _IoCounters), ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


_KILL_JOB: int | None = None


def tie_to_app(process: subprocess.Popen) -> bool:
    """Windows: put a child in a job that the OS closes with NEON, so it dies even if NEON is killed or crashes."""
    global _KILL_JOB
    if os.name != "nt":
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.SetInformationJobObject.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32)
    k32.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    if _KILL_JOB is None:
        job = k32.CreateJobObjectW(None, None)
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000                  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not job or not k32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            return False                             # 9 = JobObjectExtendedLimitInformation
        _KILL_JOB = job                              # kept open for the app's lifetime; the OS closes it at exit
    return bool(k32.AssignProcessToJobObject(_KILL_JOB, int(process._handle)))


class Tunnel:
    """A Cloudflare quick tunnel (cloudflared, no account, no config file) in front of the LAN server.
    ``on_ready`` gets the https://*.trycloudflare.com URL from a background thread; failures just leave LAN mode."""

    def __init__(self, target: str, workdir: Path, on_ready: Callable[[str], None], exe: Path = CLOUDFLARED):
        self.target, self.workdir, self.on_ready, self.exe = target, Path(workdir), on_ready, Path(exe)
        self.process: subprocess.Popen | None = None
        self.url = ""
        self.error = ""
        self.stopped = False

    def start(self) -> None:
        if not self.exe.is_file():
            self.error = "cloudflared is not installed"
            return
        try:
            self.workdir.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, HOME=str(self.workdir), USERPROFILE=str(self.workdir))   # nothing lands in C:\Users
            self.process = subprocess.Popen(
                [str(self.exe), "tunnel", "--no-autoupdate", "--url", self.target],
                cwd=self.workdir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            self.error = f"cloudflared did not start: {error.strerror or error}"
            return
        tie_to_app(self.process)                     # no orphaned public tunnel after a crash or a kill
        threading.Thread(target=self._read, args=(self.process,), name="neon-share-tunnel", daemon=True).start()

    def _read(self, process: subprocess.Popen) -> None:
        for raw in iter(process.stdout.readline, b""):             # keep draining, or cloudflared blocks
            if not self.url:
                match = TUNNEL_URL.search(raw.decode("utf-8", "replace"))
                if match and not self.stopped:
                    self.url = match.group(0)
                    self.on_ready(self.url)
        if not self.stopped:
            self.error = "the internet tunnel stopped" if self.url else "the internet tunnel did not start (no internet?)"
            if self.url:
                self.on_ready("")                                  # back to LAN only

    def stop(self) -> None:
        self.stopped = True
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(5)
        except subprocess.TimeoutExpired:
            process.kill()


# ------------------------------------------------------------------ session state
@dataclass
class Phone:
    sid: str
    ip: str
    channel: Channel
    name: str
    model: str
    mac: str = ""
    state: str = "pending"                           # pending / allowed / denied
    created: float = field(default_factory=time.monotonic)
    seen: float = field(default_factory=time.monotonic)
    rx: int = 0                                      # last control counter accepted from the phone
    path: str = "lan"                                # "lan" or "internet" (through the tunnel)
    tx: int = 0                                      # last counter used for a reply
    mode: str = "send"


@dataclass
class Offer:
    """A PC file listed for the phone to download."""
    id: str
    path: Path
    name: str
    size: int
    mime: str
    thumb: bytes = b""


@dataclass
class Transfer:
    number: int
    sid: str
    direction: str                                   # "up" phone->PC, "down" PC->phone
    name: str
    size: int
    chunks: int
    offer_id: str = ""
    path: Path | None = None                         # down: the source; up: the saved file once done
    part: Path | None = None
    handle: object = None
    next_index: int = 0
    done: int = 0
    state: str = "active"                            # active / done / cancelled / failed
    started: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False                      # SO_REUSEADDR on Windows would let another app steal the port
    share: "ShareServer"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request, client_address) -> None:
        """At most MAX_CONNECTIONS handler threads: a flood through the tunnel cannot exhaust the PC."""
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)           # dropped at once, nothing read
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exc_info()[1], OSError):   # resets and timeouts are routine; they would flood error.log
            super().handle_error(request, client_address)


class ShareServer:
    """One sharing session: the listening socket, the pairing, the phones and the transfers. Thread-safe."""

    def __init__(self, host: str, save_dir: Path, pc_name: str | None = None, allow_loopback: bool = False):
        self.host = host
        self.save_dir = Path(save_dir)
        self.pc_name = clean_label(pc_name or socket.gethostname(), 40) or "PC"
        self.allow_loopback = allow_loopback         # tests only: the real server refuses 127.0.0.1
        self.lock = threading.RLock()
        self.pairing = Pairing()
        self.pairing_rev = 0
        self.phones: dict[str, Phone] = {}
        self.offers: dict[str, Offer] = {}
        self.offers_rev = 0
        self.transfers: dict[int, Transfer] = {}
        self.inbox: list[dict] = []                  # text messages from the phone, until the UI takes them
        self.next_number = 1
        self.fails: dict[str, int] = {}
        self.web = {route: (self._read_web(name), ctype) for route, (name, ctype) in WEB_FILES.items()}
        self.httpd = _HTTPServer((host, 0), _Handler)
        self.httpd.share = self
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.3},
                                       name="neon-share", daemon=True)
        self.closed = False
        self.tunnel_url = ""                         # https://*.trycloudflare.com once the tunnel is up
        self.public_ips: set[str] = set()
        self.lan_hop = True                          # False: a phone that came through the tunnel stays on it

    @staticmethod
    def _read_web(name: str) -> bytes:
        try:
            return (WEB_DIR / name).read_bytes()
        except OSError:
            return b""

    # ---------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self.httpd.shutdown()
        self.httpd.server_close()
        with self.lock:
            for t in self.transfers.values():
                self._cancel(t)
            self.phones.clear()

    def lan_url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def url(self, mode: str) -> str:
        """What the QR code carries: the tunnel URL when it is up (the page hops to LAN by itself), else LAN."""
        with self.lock:
            p = self.pairing
            base = self.tunnel_url + "/" if self.tunnel_url else self.lan_url()
            return f"{base}#v=1&m={'recv' if mode == 'recv' else 'send'}&k={b64e(p.public)}&t={b64e(p.token)}"

    @property
    def tunnel_host(self) -> str:
        return urlsplit(self.tunnel_url).netloc if self.tunnel_url else ""

    def set_tunnel(self, url: str) -> None:
        """Called by Tunnel when cloudflared reports its URL ("" when it went away). Redraws the QR code."""
        with self.lock:
            self.tunnel_url = url if TUNNEL_URL.fullmatch(url or "") else ""
            self.pairing_rev += 1
        if self.tunnel_url and self.lan_hop and not self.public_ips:
            self.public_ips = public_ips()           # only the LAN hop needs it; INTERNET mode skips the lookup

    def where(self, peer: str) -> dict:
        """For a page loaded through the tunnel: the LAN address, but only if the phone is behind the same router."""
        if self.lan_hop and peer.startswith(TUNNEL_PREFIX) and \
                same_network(peer[len(TUNNEL_PREFIX):], self.public_ips):
            return {"lan": self.lan_url()}
        return {"lan": ""}

    def rotate(self) -> None:
        """New key and token for the QR code: the old QR stops working."""
        with self.lock:
            self.pairing = Pairing()
            self.pairing_rev += 1

    # ---------------------------------------------------------- UI side (main thread)
    def snapshot(self) -> dict:
        """Status for the UI, polled a few times a second. Also drops expired phones."""
        now = time.monotonic()
        with self.lock:
            for phone in list(self.phones.values()):
                age = now - phone.seen
                if (phone.state == "pending" and now - phone.created > PENDING_EXPIRY) or \
                        (phone.state == "denied" and age > 30) or \
                        (phone.state == "allowed" and age > SESSION_EXPIRY):
                    self._drop(phone.sid)
            phones = [{"sid": p.sid, "ip": self.shown_ip(p.ip), "mac": p.mac, "name": p.name, "model": p.model, "state": p.state,
                       "alive": now - p.seen < HEARTBEAT_LOST, "mode": p.mode, "path": p.path}
                      for p in self.phones.values()]
            transfers = [{"number": t.number, "direction": t.direction, "name": t.name, "size": t.size,
                          "done": t.done, "state": t.state, "offer_id": t.offer_id,
                          "path": str(t.path) if t.path and t.direction == "up" else "",
                          "elapsed": now - t.started} for t in self.transfers.values()]
            return {"phones": phones, "transfers": transfers, "pairing_rev": self.pairing_rev,
                    "tunnel": self.tunnel_url}

    def take_texts(self) -> list[dict]:
        """Text messages received since the last call, oldest first: {"text", "name", "at"} (at = time.time())."""
        with self.lock:
            texts, self.inbox = self.inbox, []
            return texts

    def decide(self, sid: str, allow: bool) -> None:
        with self.lock:
            phone = self.phones.get(sid)
            if phone is None or phone.state != "pending":
                return
            if allow and any(p.state == "allowed" for p in self.phones.values()):
                allow = False                        # one phone at a time
            phone.state = "allowed" if allow else "denied"
            phone.seen = time.monotonic()
            self.rotate()                            # the token was used: the QR on screen changes

    def disconnect(self) -> None:
        with self.lock:
            for sid in list(self.phones):
                self._drop(sid)
            self.rotate()

    def add_offer(self, path: Path) -> Offer | None:
        try:
            size = path.stat().st_size
        except OSError:
            return None
        if not path.is_file():
            return None
        offer = Offer(b64e(secrets.token_bytes(6)), path, path.name, size,
                      mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        with self.lock:
            self.offers[offer.id] = offer
            self.offers_rev += 1
        return offer

    def set_offer_thumb(self, offer_id: str, jpeg: bytes) -> None:
        with self.lock:
            if offer_id in self.offers and len(jpeg) < 64 * 1024:
                self.offers[offer_id].thumb = jpeg
                self.offers_rev += 1

    def remove_offer(self, offer_id: str) -> None:
        with self.lock:
            if self.offers.pop(offer_id, None) is not None:
                self.offers_rev += 1
            for t in self.transfers.values():
                if t.offer_id == offer_id and t.state == "active":
                    self._cancel(t)

    def cancel(self, number: int) -> None:
        with self.lock:
            t = self.transfers.get(number)
        if t is not None:
            self._cancel(t)

    def forget(self, number: int) -> None:
        """Drop a finished or cancelled transfer from the list (the saved file stays)."""
        with self.lock:
            t = self.transfers.get(number)
            if t is not None and t.state != "active":
                del self.transfers[number]

    # ---------------------------------------------------------- internals
    def _cancel(self, t: Transfer, state: str = "cancelled") -> None:
        with t.lock:
            if t.state != "active":
                return
            t.state = state
            if t.handle is not None:
                try:
                    t.handle.close()
                except OSError:
                    pass
                t.handle = None
            if t.direction == "up" and t.part is not None:
                try:
                    t.part.unlink(missing_ok=True)
                except OSError:
                    pass

    def _drop(self, sid: str) -> None:
        self.phones.pop(sid, None)
        for t in self.transfers.values():
            if t.sid == sid and t.state == "active":
                self._cancel(t)

    def _alloc(self) -> int:
        number = self.next_number
        if number >= 1 << 24:
            raise ShareError(503, "too many files in one session")
        self.next_number += 1
        return number

    def ip_allowed(self, ip: str) -> bool:
        return is_private_ip(ip) or (self.allow_loopback and ip in ("127.0.0.1", "::1"))

    def _phone(self, sid: object, ip: str) -> Phone:
        phone = self.phones.get(sid) if isinstance(sid, str) else None
        if phone is None or phone.ip != ip:
            raise ShareError(401, "unknown session")
        return phone

    def _pc_info(self) -> dict:
        return {"name": self.pc_name, "ip": self.host}

    @staticmethod
    def shown_ip(peer: str) -> str:
        return peer[len(TUNNEL_PREFIX):] if peer.startswith(TUNNEL_PREFIX) else peer

    # ---------------------------------------------------------- API (handler threads)
    def hello(self, ip: str, body: bytes) -> dict:
        with self.lock:
            if self.fails.get(ip, 0) >= MAX_HELLO_FAILS or (ip not in self.fails and len(self.fails) >= MAX_FAIL_IPS):
                raise ShareError(429, "too many failed pairing attempts")
            pairing = self.pairing
        try:
            request = json.loads(body)
            phone_pub = b64d(request["p"])
            if len(phone_pub) != 32:
                raise ValueError("bad key length")
            up, down = pairing.keys_for(phone_pub)
            channel = Channel(up, down)
            info = channel.open(request["d"], 0, b"H" + pairing.public + phone_pub)
        except (InvalidTag, ValueError, KeyError, TypeError):
            with self.lock:
                self.fails[ip] = self.fails.get(ip, 0) + 1
            raise ShareError(403, "pairing failed: scan the QR code again") from None
        internet = ip.startswith(TUNNEL_PREFIX)
        mac = "" if internet or ip == "127.0.0.1" else mac_for(ip)
        with self.lock:
            if pairing is not self.pairing or phone_pub in pairing.used:
                raise ShareError(403, "this QR code was already used: scan the new one")
            if any(p.state == "allowed" for p in self.phones.values()):
                raise ShareError(409, "the PC is already connected to another phone")
            if sum(p.state == "pending" for p in self.phones.values()) >= MAX_PENDING:
                raise ShareError(429, "too many phones waiting")
            pairing.used.add(phone_pub)
            sid = b64e(secrets.token_bytes(16))
            phone = Phone(sid, ip, channel, clean_label(info.get("name"), 40) or "Phone",
                          clean_label(info.get("model"), 60), mac, path="internet" if internet else "lan")
            self.phones[sid] = phone
            phone.tx += 1
            counter = phone.tx
        reply = channel.seal({"state": "pending", "pc": self._pc_info(), "path": phone.path}, counter,
                             f"R{sid}:0".encode())
        return {"s": sid, "c": counter, "d": reply}

    def control(self, ip: str, body: bytes) -> dict:
        try:
            request = json.loads(body)
            sid, counter, sealed = request["s"], request["c"], request["d"]
            if not isinstance(counter, int) or isinstance(counter, bool) or not 0 < counter < 1 << 63:
                raise ValueError("bad counter")
        except (ValueError, KeyError, TypeError):
            raise ShareError(400, "bad request") from None
        with self.lock:
            phone = self._phone(sid, ip)
            if counter <= phone.rx:
                raise ShareError(409, "replayed message")
        try:
            message = phone.channel.open(sealed, counter, f"C{sid}:{counter}".encode())
        except (InvalidTag, ValueError):
            raise ShareError(403, "message failed authentication") from None
        with self.lock:
            if counter <= phone.rx:
                raise ShareError(409, "replayed message")
            phone.rx = counter
            phone.seen = time.monotonic()
        try:
            result = self._op(phone, message)
        except ShareError as error:
            result = {"error": str(error)}
        with self.lock:
            phone.tx += 1
            reply_counter = phone.tx
        return {"c": reply_counter, "d": phone.channel.seal(result, reply_counter, f"R{sid}:{counter}".encode())}

    def _op(self, phone: Phone, message: dict) -> dict:
        op = message.get("op")
        if op == "ping":
            with self.lock:
                name = clean_label(message.get("name"), 40)
                if name:
                    phone.name = name
                if message.get("mode") in ("send", "recv", "text"):
                    phone.mode = message["mode"]
                return {"state": phone.state, "rev": self.offers_rev, "pc": self._pc_info()}
        if op == "bye":
            with self.lock:
                self._drop(phone.sid)
            return {"state": "gone"}
        if phone.state != "allowed":
            raise ShareError(403, "not allowed on the PC yet")
        if op == "list":
            with self.lock:
                return {"files": [{"id": o.id, "name": o.name, "size": o.size, "mime": o.mime,
                                   "thumb": base64.b64encode(o.thumb).decode("ascii") if o.thumb else ""}
                                  for o in self.offers.values()], "rev": self.offers_rev}
        if op == "text":                             # pasted text: arrives sealed like every control message
            text = clean_text(message.get("text"))
            with self.lock:
                self.inbox.append({"text": text, "name": phone.name, "at": time.time()})
                del self.inbox[:-MAX_INBOX]
            return {"ok": True, "chars": len(text)}
        if op == "get":
            return self._begin_download(phone, message)
        if op == "begin":
            return self._begin_upload(phone, message)
        if op in ("cancel", "got"):
            with self.lock:
                t = self.transfers.get(message.get("n")) if isinstance(message.get("n"), int) else None
                if t is None or t.sid != phone.sid:
                    raise ShareError(404, "unknown transfer")
            if op == "cancel":
                self._cancel(t)
            elif t.direction == "down":
                with t.lock:
                    if t.state == "active" and t.done >= t.size:
                        t.state = "done"
                        if t.handle is not None:
                            t.handle.close()
                            t.handle = None
            return {"ok": True}
        raise ShareError(400, "unknown operation")

    def _begin_download(self, phone: Phone, message: dict) -> dict:
        with self.lock:
            offer = self.offers.get(message.get("id")) if isinstance(message.get("id"), str) else None
            if offer is None:
                raise ShareError(404, "file no longer offered")
            try:
                size = offer.path.stat().st_size
            except OSError:
                raise ShareError(404, "file is gone from the PC") from None
            number = self._alloc()
            t = Transfer(number, phone.sid, "down", offer.name, size, chunk_count(size), offer.id, offer.path)
            self.transfers[number] = t
        return {"n": number, "size": size, "chunks": t.chunks, "name": offer.name, "mime": offer.mime}

    def _begin_upload(self, phone: Phone, message: dict) -> dict:
        size = message.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= MAX_FILE:
            raise ShareError(400, "bad size")
        name = safe_name(message.get("name"))
        with self.lock:
            if sum(t.sid == phone.sid and t.direction == "up" and t.state == "active"
                   for t in self.transfers.values()) >= MAX_UPLOADS:
                raise ShareError(429, "too many uploads at once")
            part = self.save_dir / f".{b64e(secrets.token_bytes(9))}{PART_SUFFIX}"
            try:
                self.save_dir.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(self.save_dir).free < size + DISK_RESERVE:
                    raise ShareError(507, "not enough free space on the PC")
                handle = open(part, "xb")
            except OSError:
                raise ShareError(507, "the PC cannot write to its FTP folder") from None
            t = Transfer(self._alloc(), phone.sid, "up", name, size, chunk_count(size), part=part, handle=handle)
            self.transfers[t.number] = t
        return {"n": t.number, "chunks": t.chunks}

    def _transfer(self, query: dict, ip: str, direction: str) -> tuple[Phone, Transfer, int]:
        try:
            sid, number, index = query["s"][0], int(query["n"][0]), int(query["i"][0])
        except (KeyError, ValueError, IndexError):
            raise ShareError(400, "bad request") from None
        with self.lock:
            phone = self._phone(sid, ip)
            if phone.state != "allowed":
                raise ShareError(403, "not allowed")
            t = self.transfers.get(number)
            if t is None or t.sid != sid or t.direction != direction:
                raise ShareError(404, "unknown transfer")
            if t.state == "cancelled":
                raise ShareError(410, "cancelled on the PC")
            if not 0 <= index < t.chunks:
                raise ShareError(400, "bad chunk index")
            phone.seen = time.monotonic()
        return phone, t, index

    def upload_chunk(self, ip: str, query: dict, body: bytes) -> dict:
        phone, t, index = self._transfer(query, ip, "up")
        try:
            data = phone.channel.open_chunk(t.number, index, t.chunks, body)
        except InvalidTag:
            raise ShareError(403, "chunk failed authentication") from None
        if len(data) != chunk_length(t.size, index):
            raise ShareError(400, "wrong chunk length")
        with t.lock:
            if t.state == "cancelled":
                raise ShareError(410, "cancelled on the PC")
            if t.state == "done" or index == t.next_index - 1:
                return {"ok": True, "done": t.state == "done"}      # a retry after a lost reply
            if t.state != "active" or index != t.next_index:
                raise ShareError(409, "chunk out of order")
            try:
                t.handle.write(data)
            except OSError:
                self._fail_locked(t)
                raise ShareError(507, "could not write the file on the PC") from None
            t.next_index += 1
            t.done += len(data)
            if t.next_index < t.chunks:
                return {"ok": True, "done": False}
            t.handle.close()
            t.handle = None
            try:
                t.path = commit_file(t.part, self.save_dir, t.name)
            except (OSError, ShareError):
                self._fail_locked(t)
                raise ShareError(500, "could not save the file on the PC") from None
            t.state = "done"
        from . import guard                          # received files are tagged like downloads (Mark-of-the-Web)
        guard.mark_of_the_web(t.path)
        return {"ok": True, "done": True, "saved": t.path.name}

    @staticmethod
    def _fail_locked(t: Transfer) -> None:
        t.state = "failed"
        if t.handle is not None:
            try:
                t.handle.close()
            except OSError:
                pass
            t.handle = None
        if t.part is not None:
            try:
                t.part.unlink(missing_ok=True)
            except OSError:
                pass

    def download_chunk(self, ip: str, query: dict) -> bytes:
        phone, t, index = self._transfer(query, ip, "down")
        length = chunk_length(t.size, index)
        with t.lock:
            if t.state == "cancelled":
                raise ShareError(410, "cancelled on the PC")
            if t.state not in ("active", "done"):
                raise ShareError(409, "transfer ended")
            try:
                if t.handle is None:
                    t.handle = open(t.path, "rb")
                t.handle.seek(index * CHUNK)
                data = t.handle.read(length)
            except OSError:
                data = b""
            if len(data) != length:
                self._fail_locked(t)
                raise ShareError(409, "the file changed on the PC")
            t.done = max(t.done, index * CHUNK + length)
            if index == t.chunks - 1:
                t.handle.close()
                t.handle = None                      # a retry of any chunk reopens the file
                if t.state == "active":
                    t.state = "done"
        return phone.channel.seal_chunk(t.number, index, t.chunks, data)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "NEON"
    sys_version = ""
    timeout = 30                                     # slow or stalled clients are dropped
    server: _HTTPServer

    def log_message(self, *_args) -> None:
        pass

    def _send(self, status: int, body: bytes, ctype: str = "application/json", extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        if status >= 400:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj: dict) -> None:
        self._send(status, json.dumps(obj, separators=(",", ":")).encode("utf-8"))

    def _gate(self) -> str | None:
        """The peer key ("192.168.1.7", or "cf:<public IP>" through the tunnel), or None after refusing."""
        share, ip, host = self.server.share, self.client_address[0], self.headers.get("Host", "")
        tunnel = share.tunnel_host
        if tunnel and host == tunnel:
            # cloudflared runs on this PC and connects to the LAN address, so tunnel traffic comes from this PC's
            # own IP; nobody else on the network can make a request look like it came through the tunnel
            try:
                public = str(ipaddress.ip_address(self.headers.get("CF-Connecting-IP", "").strip()))
            except ValueError:
                public = ""
            if ip != share.host or not public:
                self._json(403, {"error": "not through the tunnel"})
                return None
            return TUNNEL_PREFIX + public
        if not share.ip_allowed(ip):
            self._json(403, {"error": "only devices on your own network can connect"})
            return None
        if host != f"{share.host}:{share.port}":
            self._json(421, {"error": "wrong host"})                  # DNS-rebinding guard
            return None
        return ip

    def _body(self, limit: int) -> bytes | None:
        """Request body with Content-Length, or chunked (cloudflared may forward that way); None after refusing."""
        if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
            body = bytearray()
            try:
                while True:
                    size = int(self.rfile.readline(64).split(b";")[0].strip(), 16)
                    if size == 0:
                        while self.rfile.readline(1024) not in (b"\r\n", b"\n", b""):
                            pass                                       # trailers
                        return bytes(body)
                    if size < 0 or len(body) + size > limit:
                        break
                    body += self.rfile.read(size)
                    self.rfile.readline(8)
            except ValueError:
                self._json(400, {"error": "bad chunked body"})
                return None
            self._json(413, {"error": "too large"})
            return None
        if self.headers.get("Transfer-Encoding"):
            self._json(501, {"error": "unsupported transfer encoding"})
            return None
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._json(411, {"error": "length required"})
            return None
        if not 0 <= length <= limit:
            self._json(413, {"error": "too large"})
            return None
        return self.rfile.read(length)

    def do_GET(self) -> None:
        peer = self._gate()
        if peer is None:
            return
        share, url = self.server.share, urlsplit(self.path)
        if url.path in share.web:
            body, ctype = share.web[url.path]
            if not body:
                self._json(404, {"error": "phone page missing"})
                return
            self._send(200, body, ctype, {"Content-Security-Policy": CSP, "X-Frame-Options": "DENY"})
        elif url.path == "/api/dl":
            try:
                body = share.download_chunk(peer, parse_qs(url.query))
            except ShareError as error:
                self._json(error.status, {"error": str(error)})
                return
            self._send(200, body, "application/octet-stream")
        elif url.path == "/api/where":
            self._json(200, share.where(peer))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        ip = self._gate()
        if ip is None:
            return
        share, url = self.server.share, urlsplit(self.path)
        if url.path == "/api/up":
            try:                                     # session and transfer first: no 1 MB read for strangers
                share._transfer(parse_qs(url.query), ip, "up")
            except ShareError as error:
                self._json(error.status, {"error": str(error)})
                return
        body = self._body(CHUNK + TAG if url.path == "/api/up" else MAX_CONTROL)
        if body is None:
            return
        try:
            if url.path == "/api/hello":
                self._json(200, share.hello(ip, body))
            elif url.path == "/api/c":
                self._json(200, share.control(ip, body))
            elif url.path == "/api/up":
                self._json(200, share.upload_chunk(ip, parse_qs(url.query), body))
            else:
                self._json(404, {"error": "not found"})
        except ShareError as error:
            self._json(error.status, {"error": str(error)})
