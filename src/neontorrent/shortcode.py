"""Short codes for PC to PC: "7-tiger-crystal" instead of the long pair code.

The two PCs meet on the public magic-wormhole mailbox server (a message relay; no account). The PC that shares asks
the server for a free number (the "nameplate"), adds two random words, and shows the code. Both PCs run SPAKE2 with
the whole code as the password: they end up with the same key only if they typed the same code, and the server, which
sees every message, learns neither the code nor the key. The sharing PC then sends its long pair code (the QR link,
with the File Sharing key and one-time token) sealed with that key, and the other PC connects to File Sharing exactly
as with a pasted pair code: files stay end-to-end encrypted and the PC still has to be allowed.

A code works for one attempt: after the first other side shows up, the mailbox is closed whatever happens, so a wrong
guess burns the code instead of allowing more tries. Nothing but SPAKE2 messages and one sealed message ever goes
through the server; files never do.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from typing import Callable

import websocket
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from spake2 import SPAKE2_Symmetric

MAILBOX = "ws://relay.magic-wormhole.io:4000/v1"
APPID = "sharmaji.neon/pair-v1"
WAIT_FOR_PEER = 15 * 60                     # how long a shown code stays usable
STEP_TIMEOUT = 60
CODE = re.compile(r"(\d{1,4})-([a-z]+)-([a-z]+)")

# 256 short, distinct, easy words: two of them give 65,536 codes per number, and every code allows one guess
WORDS = (
    "able acorn actor agent alarm album alien alpha amber angel angle apple april arena armor arrow atlas "
    "atom audio award bacon badge baker bamboo banana banjo baron basil beach beard berry bingo bison blade blaze "
    "bloom board bonus boost brave bread brick bridge brush bubble buddy bugle cable cactus camel camera candy "
    "canoe canyon carbon cargo carrot castle cedar chalk charm cherry chess chili cider cinema circus citrus clay "
    "cliff clock cloud clover cobra cocoa comet copper coral cotton cougar crane crayon cricket crystal curry "
    "dancer delta denim desert diesel dingo dolphin domino donut dragon dream drum eagle earth echo eclipse "
    "elbow ember emerald engine falcon feather fiber fiddle flame flute focus forest fossil fox frost "
    "galaxy garden gecko genie ginger glacier globe gold gopher grape gravity guitar hammer harbor hazel helium "
    "hero hippo honey hornet hotel husky igloo indigo iris island ivory jacket jaguar jelly jewel jungle "
    "kayak kettle kiwi koala ladder lagoon lantern laser lemon lilac lime lion lizard llama lotus lunar magnet mango "
    "maple marble meadow melon meteor mint mirror monkey moose mosaic motor nectar neon nickel nova "
    "oasis ocean olive omega onion opal orbit orchid otter oyster paddle panda papaya parrot peach pebble pepper "
    "piano pickle pilot pixel planet plasma plum polar pony poppy prism puffin pumpkin puzzle quartz quill rabbit "
    "radar radio rainbow raven rocket ruby saddle safari salmon sapphire saturn scarf shadow shark sierra silver "
    "sketch sky snow solar spark spider sprout squid star storm sugar summit sunny swan tango tiger timber toast "
    "topaz torch tulip tundra turtle velvet violet"
).split()
assert len(WORDS) == 256 and len(set(WORDS)) == 256


class ShortCodeError(Exception):
    pass


def normalize(code: str) -> str:
    """"7 Tiger crystal", "7-tiger-crystal " → "7-tiger-crystal"."""
    return "-".join((code or "").strip().lower().replace("_", " ").replace("-", " ").split())


def is_short_code(text: str) -> bool:
    return bool(CODE.fullmatch(normalize(text)))


def _keys(shared: bytes) -> tuple[ChaCha20Poly1305, ChaCha20Poly1305]:
    def derive(label: bytes) -> ChaCha20Poly1305:
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"NEON-SHORTCODE-1|" + label).derive(shared)
        return ChaCha20Poly1305(key)
    return derive(b"pair"), derive(b"done")


def _seal(aead: ChaCha20Poly1305, data: bytes) -> str:
    nonce = os.urandom(12)
    return (nonce + aead.encrypt(nonce, data, APPID.encode())).hex()


def _open(aead: ChaCha20Poly1305, body: str) -> bytes:
    raw = bytes.fromhex(body)
    return aead.decrypt(raw[:12], raw[12:], APPID.encode())


class _Mailbox:
    """The few mailbox-server messages NEON needs: bind, allocate/claim a nameplate, open a mailbox, add, receive."""

    def __init__(self, url: str = MAILBOX):
        try:
            self.ws = websocket.create_connection(url, timeout=STEP_TIMEOUT)
        except (OSError, websocket.WebSocketException) as exc:
            raise ShortCodeError(f"cannot reach the code server ({exc.__class__.__name__})") from None
        self.side = secrets.token_hex(5)
        self.nameplate = ""
        self.mailbox = ""
        self.closed = False
        self._send(type="bind", appid=APPID, side=self.side)

    def _send(self, **message) -> None:
        message["id"] = secrets.token_hex(2)
        try:
            self.ws.send(json.dumps(message))
        except (OSError, websocket.WebSocketException):
            raise ShortCodeError("the code server connection dropped") from None

    def _receive(self, want: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while not self.closed:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ShortCodeError("timed out")
            self.ws.settimeout(min(left, 5))
            try:
                message = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            except (OSError, ValueError, websocket.WebSocketException):
                raise ShortCodeError("the code server connection dropped") from None
            kind = message.get("type")
            if kind == "error":
                raise ShortCodeError(f"code server: {message.get('error', 'error')}")
            if kind == want and (want != "message" or message.get("side") != self.side):
                return message
        raise ShortCodeError("cancelled")

    def allocate(self) -> str:
        self._send(type="allocate")
        self.nameplate = str(self._receive("allocated", STEP_TIMEOUT)["nameplate"])
        return self.nameplate

    def claim(self, nameplate: str) -> None:
        self.nameplate = nameplate
        self._send(type="claim", nameplate=nameplate)
        self.mailbox = self._receive("claimed", STEP_TIMEOUT)["mailbox"]
        self._send(type="open", mailbox=self.mailbox)

    def add(self, phase: str, body: str) -> None:
        self._send(type="add", phase=phase, body=body)

    def message(self, phase: str, timeout: float) -> str:
        while True:
            message = self._receive("message", timeout)
            if message.get("phase") == phase and isinstance(message.get("body"), str):
                return message["body"]

    def close(self, mood: str = "happy") -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.nameplate:
                self._send(type="release", nameplate=self.nameplate)
            if self.mailbox:
                self._send(type="close", mailbox=self.mailbox, mood=mood)
        except ShortCodeError:
            pass
        try:
            self.ws.close()
        except Exception:
            pass


class ShortCodeHost:
    """The sharing PC: get a code, wait for the other PC, hand it the pair code. Runs in its own thread."""

    def __init__(self, pair_code: Callable[[], str], on_code: Callable[[str], None],
                 on_done: Callable[[bool, str], None], url: str = MAILBOX):
        self.pair_code, self.on_code, self.on_done, self.url = pair_code, on_code, on_done, url
        self.box: _Mailbox | None = None
        self.cancelled = False
        threading.Thread(target=self._run, daemon=True, name="neon-shortcode").start()

    def cancel(self) -> None:
        self.cancelled = True
        if self.box is not None:
            self.box.close("lonely")

    def _run(self) -> None:
        mood = "errory"
        try:
            self.box = box = _Mailbox(self.url)
            nameplate = box.allocate()
            box.claim(nameplate)
            code = f"{nameplate}-{secrets.choice(WORDS)}-{secrets.choice(WORDS)}"
            pake = SPAKE2_Symmetric(code.encode(), idSymmetric=APPID.encode())
            box.add("pake", pake.start().hex())
            self.on_code(code)
            other = box.message("pake", WAIT_FOR_PEER)
            try:
                shared = pake.finish(bytes.fromhex(other))
            except Exception:
                raise ShortCodeError("the other PC sent a broken message; get a new code") from None
            sealed_pair, sealed_done = _keys(shared)
            link = ""
            deadline = time.monotonic() + STEP_TIMEOUT
            while not link and time.monotonic() < deadline and not self.cancelled:
                link = self.pair_code()                     # the internet link may still be starting
                if not link:
                    time.sleep(1)
            if not link:
                raise ShortCodeError("File Sharing has no pair code yet (is it started?)")
            box.add("pair", _seal(sealed_pair, link.encode()))
            try:
                if _open(sealed_done, box.message("done", STEP_TIMEOUT)) != b"ok":
                    raise InvalidTag
            except (InvalidTag, ValueError):
                raise ShortCodeError("someone tried a wrong code; the code is now closed") from None
            mood = "happy"
            self.on_done(True, "The other PC has the code. Press ALLOW when it asks to connect.")
        except ShortCodeError as exc:
            if not self.cancelled:
                self.on_done(False, str(exc))
        finally:
            if self.box is not None:
                self.box.close(mood)


def fetch_pair_code(code: str, url: str = MAILBOX) -> str:
    """The connecting PC: turn a short code into the sharing PC's pair code. Raises ShortCodeError."""
    code = normalize(code)
    match = CODE.fullmatch(code)
    if not match:
        raise ShortCodeError("a short code looks like 7-tiger-crystal")
    unknown = [w for w in match.groups()[1:] if w not in WORDS]
    if unknown:
        raise ShortCodeError(f"“{unknown[0]}” is not a code word; check the spelling")
    box = _Mailbox(url)
    mood = "errory"
    try:
        box.claim(match.group(1))
        pake = SPAKE2_Symmetric(code.encode(), idSymmetric=APPID.encode())
        box.add("pake", pake.start().hex())
        try:
            shared = pake.finish(bytes.fromhex(box.message("pake", STEP_TIMEOUT)))
        except ShortCodeError:
            raise ShortCodeError("no PC is waiting with that code (it may have expired)") from None
        except Exception:
            raise ShortCodeError("the other side sent a broken message") from None
        sealed_pair, sealed_done = _keys(shared)
        try:
            link = _open(sealed_pair, box.message("pair", STEP_TIMEOUT)).decode("utf-8")
        except (InvalidTag, ValueError, UnicodeDecodeError):
            box.add("done", "00")                         # tells the sharing PC at once; it closes the code
            raise ShortCodeError("wrong code: ask for a new one (each code allows one try)") from None
        box.add("done", _seal(sealed_done, b"ok"))
        mood = "happy"
        return link
    finally:
        box.close(mood)
