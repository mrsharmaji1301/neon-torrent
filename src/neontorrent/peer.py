"""PC to PC file transfer: this PC connects to another PC's NEON File Transfer session with its pair code.

The other PC runs the same ShareServer that phones use; this module is a phone-protocol client in Python, so files and
text are sealed end to end with the same X25519 + ChaCha20-Poly1305 channel (share.py). The pair code is the link the
QR code carries: http://<LAN IP>:<port>/#... on the same network, or https://<name>.trycloudflare.com/#... anywhere.
The key and the one-time token are in the #fragment; the code works once and only until the other PC decides.

Paired devices: every NEON install has an Ed25519 identity key (kept with Windows DPAPI in <data>\\identity.key). Both
sides sign the session's ephemeral keys with it during pairing, so a remembered PC is recognised by its key, not by its
name or address, and the other PC may let it in without the Allow prompt. A new pair code is still needed every time:
the internet address (a quick tunnel) is new for each session and NEON uses no server of its own to find the other PC.
"""
from __future__ import annotations

import ctypes
import http.client
import ipaddress
import json
import secrets
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from . import share as S

ID_HELLO, ID_REPLY = S.ID_HELLO, S.ID_REPLY
MAX_PEERS = 200
TIMEOUT = 30


class PeerError(Exception):
    pass


# ------------------------------------------------------------------ DPAPI: the identity key never sits on disk in clear
class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in, blob_out = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), _Blob()
    entropy = b"NEON Torrent identity"
    ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
    blob_ent = _Blob(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    args = ((ctypes.byref(blob_in), "NEON identity", ctypes.byref(blob_ent), None, None, 0x1,
             ctypes.byref(blob_out)) if protect else
            (ctypes.byref(blob_in), None, ctypes.byref(blob_ent), None, None, 0x1, ctypes.byref(blob_out)))
    if not call(*args):                                     # 0x1 = CRYPTPROTECT_UI_FORBIDDEN
        raise OSError(ctypes.GetLastError(), "DPAPI failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


class Identity:
    """This install's long-term Ed25519 key, created on first use and stored DPAPI-protected (this Windows user)."""

    def __init__(self, private: Ed25519PrivateKey):
        self.private = private
        self.public = private.public_key().public_bytes_raw()

    @classmethod
    def load(cls, folder: Path) -> Identity:
        path = Path(folder) / "identity.key"
        if path.is_file():
            try:
                return cls(Ed25519PrivateKey.from_private_bytes(_dpapi(path.read_bytes(), False)))
            except (OSError, ValueError):
                path.replace(path.with_suffix(".key.broken"))   # another user's or a damaged key: start a new one
        identity = cls(Ed25519PrivateKey.generate())
        raw = identity.private.private_bytes_raw()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(_dpapi(raw, True))
        tmp.replace(path)
        return identity

    def sign(self, label: bytes, server_key: bytes, client_key: bytes) -> str:
        return S.b64e(self.private.sign(label + server_key + client_key))

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.public)


def fingerprint(public: bytes) -> str:
    """Short form of an identity key for people to compare, e.g. 3F9A-11C2-7B04."""
    from hashlib import sha256
    digest = sha256(public).hexdigest().upper()[:12]
    return "-".join(digest[i:i + 4] for i in range(0, 12, 4))


verify = S.verify_identity


# ------------------------------------------------------------------ paired devices
class PeerStore:
    """Remembered PCs, in <data>\\peers.json: identity key (base64url) -> name, first and last seen, trust flag."""

    def __init__(self, folder: Path):
        self.path = Path(folder) / "peers.json"
        self.lock = threading.Lock()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.peers: dict[str, dict] = {k: v for k, v in data.items() if isinstance(v, dict)} \
                if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.peers = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.peers, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def is_trusted(self, public: bytes) -> bool:
        with self.lock:
            return bool(self.peers.get(S.b64e(public), {}).get("trusted"))

    def remember(self, public: bytes, name: str, trusted: bool = True) -> None:
        key, now = S.b64e(public), int(time.time())
        with self.lock:
            entry = self.peers.get(key) or {"added": now}
            entry.update(name=S.clean_label(name, 40) or "PC", last=now, trusted=trusted)
            self.peers[key] = entry
            if len(self.peers) > MAX_PEERS:                    # drop the longest-unused
                for old in sorted(self.peers, key=lambda k: self.peers[k].get("last", 0))[:-MAX_PEERS]:
                    del self.peers[old]
            self._save()

    def seen(self, public: bytes) -> None:
        key = S.b64e(public)
        with self.lock:
            if key in self.peers:
                self.peers[key]["last"] = int(time.time())
                self._save()

    def rename(self, key: str, name: str) -> None:
        with self.lock:
            if key in self.peers:
                self.peers[key]["name"] = S.clean_label(name, 40) or self.peers[key]["name"]
                self._save()

    def forget(self, key: str) -> None:
        with self.lock:
            if self.peers.pop(key, None) is not None:
                self._save()

    def items(self) -> list[tuple[str, dict]]:
        with self.lock:
            return sorted(self.peers.items(), key=lambda kv: -kv[1].get("last", 0))


# ------------------------------------------------------------------ pair codes
@dataclass
class PairCode:
    scheme: str
    host: str
    port: int
    server_key: bytes
    token: bytes


def parse_code(code: str, allow_loopback: bool = False) -> PairCode:
    """A pair code is the QR link. Only two kinds are accepted: http to a private LAN address, or https to a
    trycloudflare.com quick tunnel, so a pasted code can never point NEON at another service."""
    text = (code or "").strip()
    try:
        url = urlsplit(text)
        frag = parse_qs(url.fragment)
        server_key, token = S.b64d(frag["k"][0]), S.b64d(frag["t"][0])
        host, port = url.hostname or "", url.port
    except (ValueError, KeyError, IndexError):
        raise PeerError("That is not a NEON pair code. Copy it again from the other PC.") from None
    if len(server_key) != 32 or len(token) != 16 or url.username or url.password:
        raise PeerError("That pair code is damaged. Copy it again from the other PC.")
    if url.scheme == "https" and S.TUNNEL_URL.fullmatch(f"https://{host}") and port in (None, 443):
        return PairCode("https", host, 443, server_key, token)
    if url.scheme == "http" and port:
        try:
            address = str(ipaddress.IPv4Address(host))
            if S.is_private_ip(address) or (allow_loopback and address == "127.0.0.1"):   # loopback: tests only
                return PairCode("http", host, port, server_key, token)
        except ValueError:
            pass
    raise PeerError("Pair codes come from NEON's File Transfer (a LAN address or a trycloudflare.com link).")


# ------------------------------------------------------------------ the client
class PeerClient:
    """One session with another PC. Thread-safe: control calls are serialised, transfers use their own connections."""

    def __init__(self, code: str, identity: Identity, name: str, model: str = "NEON Torrent on Windows",
                 allow_loopback: bool = False):
        self.code = parse_code(code, allow_loopback)
        self.identity, self.name, self.model = identity, name, model
        self.private = X25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes_raw()
        try:
            up, down = S.derive_keys(self.private.exchange(X25519PublicKey.from_public_bytes(self.code.server_key)),
                                     self.code.token, self.code.server_key, self.public)
        except ValueError:
            raise PeerError("That pair code is damaged. Copy it again from the other PC.") from None
        self.channel = S.Channel(up, down, role="phone")
        self.sid, self.counter = "", 0
        self.lock = threading.Lock()
        self.remote_name, self.remote_id = "PC", b""
        self.closed = False

    # -- HTTP
    def _connection(self) -> http.client.HTTPConnection:
        c = self.code
        if c.scheme == "https":
            return http.client.HTTPSConnection(c.host, 443, timeout=TIMEOUT)
        return http.client.HTTPConnection(c.host, c.port, timeout=TIMEOUT)

    def _request(self, method: str, path: str, body: bytes | None = None,
                 conn: http.client.HTTPConnection | None = None) -> tuple[int, bytes]:
        own = conn is None
        conn = conn or self._connection()
        try:
            conn.request(method, path, body=body, headers={"Content-Type": "application/octet-stream"})
            response = conn.getresponse()
            return response.status, response.read()
        except (OSError, http.client.HTTPException) as exc:
            raise PeerError(f"The other PC cannot be reached ({exc.__class__.__name__}).") from None
        finally:
            if own:
                conn.close()

    @staticmethod
    def _error(status: int, body: bytes) -> PeerError:
        try:
            message = json.loads(body).get("error") or f"HTTP {status}"
        except ValueError:
            message = f"HTTP {status}"
        if status == 401:
            message = "The other PC ended this session."
        return PeerError(str(message))

    # -- pairing and control
    def hello(self) -> dict:
        info = {"name": self.name, "model": self.model, "kind": "pc", "id": S.b64e(self.identity.public),
                "sig": self.identity.sign(ID_HELLO, self.code.server_key, self.public)}
        sealed = self.channel.seal(info, 0, b"H" + self.code.server_key + self.public)
        status, body = self._request("POST", "/api/hello", json.dumps({"p": S.b64e(self.public), "d": sealed}).encode())
        if status != 200:
            raise self._error(status, body)
        reply = json.loads(body)
        self.sid = reply["s"]
        try:
            message = self.channel.open(reply["d"], reply["c"], f"R{self.sid}:0".encode())
        except (InvalidTag, ValueError):
            raise PeerError("The other PC's reply failed authentication.") from None
        self.counter = 0
        self._note_pc(message)
        self.remote_id = verify(message.get("id"), message.get("sig"), ID_REPLY, self.code.server_key,
                                self.public) or b""
        return message

    def _note_pc(self, message: dict) -> None:
        pc = message.get("pc")
        if isinstance(pc, dict):
            self.remote_name = S.clean_label(pc.get("name"), 40) or self.remote_name

    def call(self, message: dict) -> dict:
        with self.lock:
            self.counter += 1
            counter = self.counter
            sealed = self.channel.seal(message, counter, f"C{self.sid}:{counter}".encode())
            status, body = self._request("POST", "/api/c", json.dumps({"s": self.sid, "c": counter,
                                                                       "d": sealed}).encode())
        if status != 200:
            raise self._error(status, body)
        reply = json.loads(body)
        try:
            out = self.channel.open(reply["d"], reply["c"], f"R{self.sid}:{counter}".encode())
        except (InvalidTag, ValueError, KeyError):
            raise PeerError("The other PC's reply failed authentication.") from None
        if out.get("error"):
            raise PeerError(str(out["error"]))
        return out

    def ping(self) -> dict:
        reply = self.call({"op": "ping", "name": self.name, "mode": "recv"})
        self._note_pc(reply)
        return reply

    def files(self) -> list[dict]:
        return self.call({"op": "list"}).get("files", [])

    def send_text(self, text: str) -> None:
        self.call({"op": "text", "text": text})

    def texts(self, after: int) -> list[dict]:
        """Text the other PC sent to this session since message number ``after``, cleaned again on this side."""
        out = []
        for entry in self.call({"op": "texts", "after": after}).get("texts", []):
            try:
                out.append({"n": int(entry["n"]), "text": S.clean_text(entry["text"]), "at": float(entry["at"])})
            except (KeyError, TypeError, ValueError, S.ShareError):
                continue
        return out

    def bye(self) -> None:
        if self.sid and not self.closed:
            self.closed = True
            try:
                self.call({"op": "bye"})
            except PeerError:
                pass

    # -- transfers (each on its own keep-alive connection)
    def upload(self, path: Path, progress: Callable[[int], None], cancelled: Callable[[], bool]) -> str:
        path = Path(path)
        size = path.stat().st_size
        begin = self.call({"op": "begin", "name": path.name, "size": size})
        number, chunks = begin["n"], begin["chunks"]
        conn, done, reply = self._connection(), 0, {}
        try:
            with open(path, "rb") as handle:
                for index in range(chunks):
                    if cancelled():
                        self.call({"op": "cancel", "n": number})
                        raise PeerError("cancelled")
                    data = handle.read(S.CHUNK)
                    if len(data) != S.chunk_length(size, index):
                        raise PeerError("the file changed while it was being sent")
                    sealed = self.channel.seal_chunk(number, index, chunks, data)
                    query = urlencode({"s": self.sid, "n": number, "i": index})
                    status, body = self._request("POST", f"/api/up?{query}", sealed, conn)
                    if status != 200:
                        raise self._error(status, body)
                    reply = json.loads(body)
                    done += len(data)
                    progress(done)
        finally:
            conn.close()
        return str(reply.get("saved", path.name))

    def download(self, offer: dict, folder: Path, progress: Callable[[int], None],
                 cancelled: Callable[[], bool]) -> Path:
        begin = self.call({"op": "get", "id": offer["id"]})
        number, size, chunks = begin["n"], begin["size"], begin["chunks"]
        if not isinstance(size, int) or not 0 <= size <= S.MAX_FILE or chunks != S.chunk_count(size):
            raise PeerError("the other PC sent a bad file size")
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        if __import__("shutil").disk_usage(folder).free < size + S.DISK_RESERVE:
            self.call({"op": "cancel", "n": number})
            raise PeerError("not enough free space on this PC")
        name = S.safe_name(begin.get("name") or offer.get("name"))
        part = folder / f".{S.b64e(secrets.token_bytes(9))}{S.PART_SUFFIX}"
        conn, done = self._connection(), 0
        try:
            with open(part, "xb") as handle:
                for index in range(chunks):
                    if cancelled():
                        self.call({"op": "cancel", "n": number})
                        raise PeerError("cancelled")
                    query = urlencode({"s": self.sid, "n": number, "i": index})
                    status, body = self._request("GET", f"/api/dl?{query}", None, conn)
                    if status != 200:
                        raise self._error(status, body)
                    try:
                        data = self.channel.open_chunk(number, index, chunks, body)
                    except InvalidTag:
                        raise PeerError("a part of the file failed authentication") from None
                    if len(data) != S.chunk_length(size, index):
                        raise PeerError("a part of the file has the wrong length")
                    handle.write(data)
                    done += len(data)
                    progress(done)
            self.call({"op": "got", "n": number})
            saved = S.commit_file(part, folder, name)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        finally:
            conn.close()
        from . import guard                                  # tagged like any download (Mark-of-the-Web)
        guard.mark_of_the_web(saved)
        return saved
