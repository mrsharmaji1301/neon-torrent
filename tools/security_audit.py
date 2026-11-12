"""NEON Torrent security self-test. Runs real attack attempts against the client, fully offline (localhost only).

    .venv\\Scripts\\python.exe tools\\security_audit.py

Every check prints PASS/FAIL with evidence. Nothing here contacts the internet, and no file is ever executed.
"""
from __future__ import annotations

import hashlib
import http.server
import os
import sys
import tempfile
import threading
import time
import warnings
from pathlib import Path

warnings.simplefilter("ignore")
ROOT = Path(__file__).resolve().parent.parent
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="neon_audit_")
sys.path.insert(0, str(ROOT / "src"))

import libtorrent as lt  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEventLoop, Qt, QTimer  # noqa: E402

import neontorrent.engine as en  # noqa: E402
import neontorrent.shield as sh  # noqa: E402
from neontorrent import guard as G  # noqa: E402

sh.MB_DETECTIONS = Path(tempfile.mkdtemp())          # isolate from the real antivirus log
en.BOOSTER_TRACKERS = []
RESULTS: list[tuple[str, bool, str]] = []
app = QCoreApplication([])


def check(name: str, ok: bool, evidence: str) -> None:
    RESULTS.append((name, ok, evidence))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {evidence}")


def run(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def crafted_torrent(files: list[dict], name: bytes = b"payload") -> bytes:
    """A .torrent whose file list is attacker-controlled (paths, attributes)."""
    total = sum(f[b"length"] for f in files)
    pieces = b"".join(hashlib.sha1(b"x").digest() for _ in range(max(1, -(-total // 16384))))
    info = {b"name": name, b"piece length": 16384, b"pieces": pieces, b"files": files}
    return lt.bencode({b"announce": b"http://127.0.0.1:1/announce", b"info": info})


def engine(download_dir: str) -> en.TorrentEngine:
    e = en.TorrentEngine({"download_dir": download_dir, "upload_kib": 0, "listen_port": 6801,
                          "accept_incoming": False, "shield_avoid_dc": False})
    original = e._settings
    e._settings = lambda: {**original(), "dht_bootstrap_nodes": "", "enable_dht": False}
    e.offers = {}                                     # what the Add dialog would show, per torrent
    e.select_files.connect(lambda offer: e.offers.__setitem__(offer["key"], offer))
    e.start()
    run(300)
    return e


def confirm(e: en.TorrentEngine, handle, save: str) -> None:
    """Press DOWNLOAD in the Add dialog with the priorities it proposed (Guard skips included)."""
    key = en.handle_key(handle)
    offer = e.offers.get(key, {})
    e.confirm_selection(key, save, [[f["index"], f["priority"]] for f in offer.get("files", [])])
    run(300)


# ------------------------------------------------------------------------------------------------ 1. paths
def test_paths(e: en.TorrentEngine, save: str) -> None:
    files = [
        {b"length": 10, b"path": [b"..", b"..", b"..", b"evil.txt"]},
        {b"length": 10, b"path": [b"C:", b"Windows", b"System32", b"evil.dll"]},
        {b"length": 10, b"path": [b"notes.txt:hidden.exe"]},
        {b"length": 10, b"path": [b"CON"]},
        {b"length": 10, b"path": [b"aux.txt"]},
        {b"length": 10, b"path": [b"sub", b"..", b"..", b"escape.bat"]},
    ]
    e.add_bytes(crafted_torrent(files, b"..\\..\\evilroot"), "audit")
    run(1500)
    handle = next((h for h in e.session.get_torrents() if h.status().has_metadata
                   and h.torrent_file().num_files() == len(files)), None)
    if handle is None:
        check("Path traversal: crafted torrent is handled", False, "torrent was not added")
        return
    key = en.handle_key(handle)
    waiting = list(handle.get_file_priorities())
    paused = bool(handle.status().flags & lt.torrent_flags.paused)
    offered = [f["priority"] for f in e.offers.get(key, {}).get("files", [])]
    check("Nothing is requested before the Add dialog is confirmed (paused, every file Don't download)",
          paused and not any(waiting) and e.meta.get(key, {}).get("select") is True and len(offered) == len(files),
          f"paused={paused}; libtorrent priorities while waiting={waiting}; dialog proposes={offered}")
    confirm(e, handle, save)
    fs = handle.torrent_file().files()
    base = Path(save).resolve()
    paths = [fs.file_path(i) for i in range(fs.num_files())]
    resolved = [(base / p).resolve() for p in paths]
    inside = all(r.is_relative_to(base) for r in resolved)
    no_ads = all(":" not in p for p in paths)
    no_dotdot = all(".." not in Path(p).parts for p in paths)
    priorities = list(handle.get_file_priorities())
    device_safe = priorities[3] == 0 and priorities[4] == 0
    check("Path traversal / absolute paths stay inside the download folder", inside and no_dotdot,
          f"libtorrent mapped them to: {paths}")
    check("Alternate-data-stream names (file.txt:hidden.exe) are neutralised", no_ads, f"{paths[2]}")
    check("Windows device names (CON, AUX) are never written (Guard skips them)", device_safe,
          f"libtorrent keeps {paths[3]!r}, {paths[4]!r}; Guard priorities for them: {priorities[3]}, {priorities[4]}")
    e.remove([en.handle_key(handle)])
    run(300)


# ------------------------------------------------------------------------------------------------ 2. symlinks
def test_symlink(e: en.TorrentEngine, save: str) -> None:
    files = [
        {b"length": 100, b"path": [b"readme.txt"]},
        {b"length": 0, b"path": [b"system"], b"attr": b"l", b"symlink path": [b"..", b"..", b"..", b"..", b"Windows",
                                                                                   b"System32"]},
    ]
    e.add_bytes(crafted_torrent(files, b"linkbomb"), "audit")
    run(1500)
    handle = next((h for h in e.session.get_torrents() if h.status().name == "linkbomb"), None)
    if handle is None:
        check("Symlink torrent handled", False, "not added")
        return
    fs = handle.torrent_file().files()
    target = fs.symlink(1) if fs.file_flags(1) & lt.file_storage.flag_symlink else "(not a symlink)"
    guard = e.meta.get(en.handle_key(handle), {}).get("guard", {})
    flagged = guard.get("findings", {}).get("1", {}).get("level") == "danger"
    check("Symlink pointing outside the download folder is flagged by the Guard", flagged,
          f"libtorrent symlink target: {target!r}; guard: {guard.get('findings', {}).get('1')}")
    key = en.handle_key(handle)
    e.cancel_selection(key)
    run(300)
    gone = key not in {en.handle_key(h) for h in e.session.get_torrents()}
    written = sorted(str(p.relative_to(save)) for p in Path(save).rglob("*") if "linkbomb" in p.parts)
    check("CANCEL in the Add dialog removes the torrent and writes no files", gone and not written and key not in e.meta,
          f"torrent removed={gone}; files written={written or 'none'}")


# ------------------------------------------------------------------------------------------------ 3. disguised files
def test_guard(e: en.TorrentEngine, save: str) -> None:
    rlo = chr(0x202E)
    files = [
        {b"length": 300 * 1024 * 1024, b"path": [b"Movie.2024.mkv"]},
        {b"length": 9000, b"path": [b"Movie.2024.mp4.exe"]},
        {b"length": 900, b"path": [b"Play.lnk"]},
        {b"length": 9000, b"path": [f"subs{rlo}gpj.scr".encode()]},
        {b"length": 9000, b"path": [b"codec_setup.exe"]},
        {b"length": 900, b"path": [b"english.srt"]},
    ]
    e.add_bytes(crafted_torrent(files, b"Movie.2024.1080p"), "audit")
    run(1500)
    handle = next((h for h in e.session.get_torrents() if h.status().name == "Movie.2024.1080p"), None)
    if handle is None:
        check("Disguised-file torrent handled", False, "not added")
        return
    expected_skip = {1, 2, 3, 4}
    offer = e.offers.get(en.handle_key(handle), {}).get("files", [])
    proposed = {f["index"] for f in offer if f["priority"] == 0}
    reasons = all(f["reason"] for f in offer if f["index"] in expected_skip)
    check("The Add dialog proposes Guard-skipped files as Don't download, with the reason",
          proposed == expected_skip and reasons, f"proposed Don't download: {sorted(proposed)}; reasons shown={reasons}")
    confirm(e, handle, save)
    prio = list(handle.get_file_priorities())
    skipped = {i for i, p in enumerate(prio) if p == 0}
    check("Disguised programs in a media torrent are never downloaded (priority 0 before any data)",
          skipped == expected_skip and prio[0] > 0 and prio[5] > 0,
          f"priorities={prio} (0 = skipped): .mp4.exe, .lnk, RTLO .scr, codec .exe skipped; .mkv/.srt kept")
    e.remove([en.handle_key(handle)])
    run(300)


# ------------------------------------------------------------------------------------------------ 4. malformed input
def test_inputs(e: en.TorrentEngine) -> None:
    notes: list[str] = []
    e.notice.connect(lambda text, level: notes.append(text))
    before = len(e.session.get_torrents())
    e.add_bytes(b"d4:infoi-1ee" + os.urandom(64), "audit")
    e.add_bytes(b"\x00" * 1000, "audit")
    e.add_uri("javascript:alert(1)")
    e.add_uri("file:///C:/Windows/System32/calc.exe")
    run(500)
    check("Malformed / hostile input is rejected without crashing", len(e.session.get_torrents()) == before,
          f"notices: {notes[-4:]}")

    big = Path(tempfile.mkdtemp()) / "big.torrent"
    big.write_bytes(b"d" + b"0" * (en.MAX_TORRENT_DOWNLOAD + 10))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), lambda *a: http.server.SimpleHTTPRequestHandler(
        *a, directory=str(big.parent)))
    server.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    notes.clear()
    e.add_uri(f"http://127.0.0.1:{server.server_address[1]}/big.torrent")
    run(4000)
    server.shutdown()
    check("Oversized .torrent download is refused (20 MB cap)", any("too large" in n.lower() for n in notes),
          f"notices: {notes}")


# ------------------------------------------------------------------------------------------------ 5. SSRF via trackers
def test_ssrf(e: en.TorrentEngine, save: str) -> None:
    hits: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    files = [{b"length": 10, b"path": [b"a.txt"]}]
    data = lt.bdecode(crafted_torrent(files, b"ssrf"))
    data[b"announce-list"] = [[f"http://127.0.0.1:{port}/admin/delete?id=1".encode()]]
    e.add_bytes(lt.bencode(data), "audit")
    run(800)
    for h in e.session.get_torrents():
        if h.status().name == "ssrf":
            confirm(e, h, save)                       # started, so it would announce if the URL were allowed
    run(4200)
    server.shutdown()
    check("Tracker URL aimed at a local service (SSRF) is not requested", not any("admin" in h for h in hits),
          f"requests that reached the local service: {hits or 'none'}")
    for h in e.session.get_torrents():
        if h.status().name == "ssrf":
            e.remove([en.handle_key(h)])


# ------------------------------------------------------------------------------------------------ 6. UI injection
def test_ui() -> None:
    import neon_torrent as nt
    from neontorrent.transfers import TorrentModel
    model = TorrentModel()
    evil = '<img src="file:///C:/Windows/win.ini"><a href="x">click</a>'
    row = {"key": "k", "name": evil, "title": evil, "sub": evil, "kind": "file", "state": "Downloading",
           "progress": 0.5, "size": 10, "done": 5, "down": 0, "up": 0, "eta": 1, "peers": 0, "seeds": 0,
           "list_peers": 0, "list_seeds": 0, "ratio": 0.0, "uploaded": 0, "save_path": "C:/x", "added": 0,
           "sequential": False, "error": "", "queue": 0, "guard": {}}
    model.update_rows([row])
    tip = model.data(model.index(0, 1), Qt.ItemDataRole.ToolTipRole)
    check("Torrent names are escaped (no HTML rendering in tooltips)", "<img" not in tip and "&lt;img" in tip,
          f"tooltip starts: {tip[:90]}…")
    from neontorrent.dialogs import RecordModel
    files = RecordModel(["FILE"])
    files.update_rows([{"key": "0", "cells": [evil], "sort": [evil]}])
    tip = files.data(files.index(0, 0), Qt.ItemDataRole.ToolTipRole)
    check("File names in the Add dialog and Details tables are escaped in tooltips",
          "<img" not in tip and "&lt;img" in tip, f"tooltip starts: {tip[:90]}…")
    base = Path(tempfile.mkdtemp())
    (base / "inside.mkv").write_bytes(b"x")
    attempts = {
        "inside file": nt.explorer_command(str(base), "inside.mkv"),
        "traversal to calc.exe": nt.explorer_command(str(base), r"..\..\..\Windows\System32\calc.exe"),
        "quote injection": nt.explorer_command(str(base), 'a" ,C:\\Windows\\System32\\calc.exe "'),
    }
    safe = (attempts["inside file"][1] == "/select," and attempts["traversal to calc.exe"] == [
        attempts["traversal to calc.exe"][0], str(base.resolve())] and attempts["quote injection"][-1] == str(base.resolve()))
    check("Open-folder never launches a file and never leaves the download folder", safe,
          "; ".join(f"{k}: {v[1:]}" for k, v in attempts.items()))
    source = (ROOT / "src" / "neon_torrent.py").read_text(encoding="utf-8")
    check("Single-instance channel accepts only the current Windows user",
          "UserAccessOption" in source, "QLocalServer.SocketOption.UserAccessOption is set before listen()")


# ------------------------------------------------------------------------------------------------ 7. finished download
def test_finish(e: en.TorrentEngine, save: str) -> None:
    data = Path(tempfile.mkdtemp())
    payload = data / "tool_setup.exe"
    payload.write_bytes(b"MZ" + os.urandom(400_000))
    fs = lt.file_storage()
    lt.add_files(fs, str(payload))
    ct = lt.create_torrent(fs)
    lt.set_piece_hashes(ct, str(data))
    tp = data / "tool.torrent"
    tp.write_bytes(lt.bencode(ct.generate()))
    seed = lt.session({"listen_interfaces": "127.0.0.1:6802", "enable_dht": False, "enable_lsd": False,
                       "enable_upnp": False, "enable_natpmp": False})
    sp = lt.add_torrent_params()
    sp.ti = lt.torrent_info(str(tp))
    sp.save_path = str(data)
    seed.add_torrent(sp)
    e.add_file(str(tp))
    run(1200)
    handle = next(h for h in e.session.get_torrents() if h.status().name == "tool_setup.exe")
    confirm(e, handle, save)
    handle.connect_peer(("127.0.0.1", 6802))
    deadline = time.time() + 25
    key = en.handle_key(handle)
    while time.time() < deadline and "scan" not in e.meta.get(key, {}).get("guard", {}):
        run(500)
    got = Path(save) / "tool_setup.exe"
    scan = e.meta.get(key, {}).get("guard", {}).get("scan", {})
    check("Finished download is complete and hash-verified", handle.status().progress == 1.0,
          f"progress={handle.status().progress:.2f}")
    check("Finished files carry Mark-of-the-Web (SmartScreen checks them before they run)",
          G.has_mark_of_the_web(got), f"{got.name}:Zone.Identifier present={G.has_mark_of_the_web(got)}; "
                                      f"guard result: {scan.get('scan')} · {'; '.join(scan.get('detail', []))[:160]}")


def test_trackerless_magnet(e: en.TorrentEngine) -> None:
    """A browser magnet without trackers gets the booster trackers (DHT is off). Nothing is added or contacted: the
    session's add call is replaced for this check."""
    captured = []
    real = e.session.async_add_torrent
    e.session.async_add_torrent = captured.append
    en.BOOSTER_TRACKERS = ["udp://booster-a.invalid:1/announce", "udp://booster-b.invalid:1/announce"]
    try:
        e._queue_add(lt.parse_magnet_uri("magnet:?xt=urn:btih:" + "ab" * 20 + "&dn=example"))
    finally:
        e.session.async_add_torrent = real
        boosters, en.BOOSTER_TRACKERS = en.BOOSTER_TRACKERS, []          # offline again for the other checks
        for key in list(e.pending_names):
            e.pending_names.pop(key, None)
            e.meta.pop(key, None)
    trackers = list(captured[0].trackers) if captured else []
    check("A magnet without trackers is fetched through the public booster trackers when DHT is off",
          trackers == boosters, f"{len(trackers)} trackers given")


def test_magnet_metadata(e: en.TorrentEngine, save: str) -> None:
    """A magnet fetches its file list and then waits, with no file data, for the Add dialog. A local seeder on
    127.0.0.1 with random data stands in for the swarm, so nothing leaves this PC."""
    base = Path(tempfile.mkdtemp(prefix="neon_seed_"))
    (base / "sample.bin").write_bytes(os.urandom(700_000))
    ct = lt.create_torrent(_storage(base / "sample.bin"))
    lt.set_piece_hashes(ct, str(base))
    ti = lt.torrent_info(ct.generate())
    seeder = lt.session({"listen_interfaces": "127.0.0.1:6931", "enable_dht": False, "enable_lsd": False,
                         "enable_upnp": False, "enable_natpmp": False})
    sp = lt.add_torrent_params()
    sp.ti, sp.save_path = ti, str(base)
    sp.flags |= lt.torrent_flags.seed_mode
    seeder.add_torrent(sp)
    key = str(ti.info_hashes().v1)
    e._queue_add(lt.parse_magnet_uri(f"magnet:?xt=urn:btih:{key}&dn=sample"))
    run(800)
    handle = next((h for h in e.session.get_torrents() if en.handle_key(h) == key), None)
    if handle is not None:
        handle.connect_peer(("127.0.0.1", 6931))
    deadline = time.monotonic() + 15
    while handle is not None and time.monotonic() < deadline and not handle.status().has_metadata:
        run(300)
    run(800)
    status = handle.status() if handle is not None else None
    ok = bool(status and status.has_metadata and status.total_wanted_done == 0
              and status.flags & lt.torrent_flags.paused)
    check("A magnet fetches its file list, then waits paused with no file data for the Add dialog", ok,
          f"metadata {bool(status and status.has_metadata)}, "
          f"bytes {status.total_wanted_done if status else '-'}, paused {bool(status and status.flags & lt.torrent_flags.paused)}")
    if handle is not None:
        e.session.remove_torrent(handle)
    del seeder


def _storage(path: Path):
    fs = lt.file_storage()
    fs.add_file(path.name, path.stat().st_size)
    return fs


def test_static() -> None:
    sources = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py")}
    launches = [(name, line.strip()) for name, text in sources.items() for line in text.splitlines()
                if ("subprocess.run(" in line or "Popen(" in line or "startfile" in line or "os.system" in line)
                and not line.strip().startswith("#")]
    dangerous = [(n, l) for name, text in sources.items() for l in text.splitlines()
                 for n in [name] if ("os.system" in l or "startfile" in l or " eval(" in l or "exec(compile" in l)]
    executes_downloads = bool(dangerous)
    risky = launches
    check("Code audit: no os.system / startfile / eval; the only programs launched are Explorer, PowerShell "
          "(antivirus status), Defender and cloudflared (File Sharing internet tunnel)", not executes_downloads,
          "process launches: " + " | ".join(f"{n}: {l[:60]}" for n, l in risky))


def test_share() -> None:
    """File Sharing server (C-11): pairing, encryption, replay, file names and the network gate."""
    import http.client
    import json
    import socket
    from urllib.parse import parse_qs, urlsplit

    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey,
        X25519PublicKey,
    )

    from neontorrent import share as S

    def post(port: int, path: str, body: bytes, host: str = "") -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", path, body=body, headers={"Host": host} if host else {})
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def phone(server: S.ShareServer, token: bytes | None = None):
        frag = parse_qs(urlsplit(server.url("send")).fragment)
        pc_pub, real = S.b64d(frag["k"][0]), S.b64d(frag["t"][0])
        key = X25519PrivateKey.generate()
        pub = key.public_key().public_bytes_raw()
        up, down = S.derive_keys(key.exchange(X25519PublicKey.from_public_bytes(pc_pub)), token or real, pc_pub, pub)
        channel = S.Channel(up, down, role="phone")
        body = json.dumps({"p": S.b64e(pub), "d": channel.seal({"name": "audit"}, 0, b"H" + pc_pub + pub)}).encode()
        return channel, body

    save = Path(tempfile.mkdtemp(prefix="neon_share_audit_"))
    server = S.ShareServer("127.0.0.1", save / "FTP", "AUDIT", allow_loopback=True)
    server.start()
    try:
        _channel, bad = phone(server, token=os.urandom(16))
        status, _ = post(server.port, "/api/hello", bad)
        check("Share: a phone without the QR token cannot pair", status == 403 and not server.phones, f"HTTP {status}")
        channel, body = phone(server)
        status, reply = post(server.port, "/api/hello", body)
        sid = json.loads(reply)["s"]
        replay, _ = post(server.port, "/api/hello", body)
        check("Share: a captured pairing request cannot be replayed", status == 200 and replay == 403,
              f"first HTTP {status}, replay HTTP {replay}")
        sealed = channel.seal({"op": "list"}, 1, f"C{sid}:1".encode())
        status, reply = post(server.port, "/api/c", json.dumps({"s": sid, "c": 1, "d": sealed}).encode())
        listed = channel.open(json.loads(reply)["d"], json.loads(reply)["c"], f"R{sid}:1".encode())
        check("Share: nothing is listed before the PC user presses Allow", listed.get("error", "").startswith("not"),
              str(listed))
        server.decide(sid, True)
        replay, _ = post(server.port, "/api/c", json.dumps({"s": sid, "c": 1, "d": sealed}).encode())
        check("Share: a replayed control message is refused", replay == 409, f"HTTP {replay}")
        sealed = channel.seal({"op": "begin", "name": r"..\..\..\Windows\evil.exe", "size": 3}, 2,
                              f"C{sid}:2".encode())
        _, reply = post(server.port, "/api/c", json.dumps({"s": sid, "c": 2, "d": sealed}).encode())
        begin = channel.open(json.loads(reply)["d"], json.loads(reply)["c"], f"R{sid}:2".encode())
        chunk = bytearray(channel.seal_chunk(begin["n"], 0, 1, b"MZ!"))
        chunk[0] ^= 1
        tampered, _ = post(server.port, f"/api/up?s={sid}&n={begin['n']}&i=0", bytes(chunk))
        chunk[0] ^= 1
        status, reply = post(server.port, f"/api/up?s={sid}&n={begin['n']}&i=0", bytes(chunk))
        saved = save / "FTP" / json.loads(reply).get("saved", "?")
        check("Share: a tampered chunk is rejected; a traversal name is saved inside the FTP folder, tagged MotW",
              tampered == 403 and saved.parent == save / "FTP" and saved.name == "evil.exe"
              and G.has_mark_of_the_web(saved), f"tamper HTTP {tampered}, saved {saved}")

        def text_call(text: object, counter: int) -> dict:
            sealed = channel.seal({"op": "text", "text": text}, counter, f"C{sid}:{counter}".encode())
            _, reply = post(server.port, "/api/c", json.dumps({"s": sid, "c": counter, "d": sealed}).encode())
            return channel.open(json.loads(reply)["d"], json.loads(reply)["c"], f"R{sid}:{counter}".encode())

        text_call("<b>hi</b>‮exe.gpj\x07", 3)
        too_long = text_call("x" * (S.MAX_TEXT + 1), 4).get("error", "")
        got = [t["text"] for t in server.take_texts()]
        check("Share: text from the phone arrives without control or bidi-override characters; oversized is refused",
              got == ["<b>hi</b>exe.gpj"] and "longer than" in too_long, f"{got!r}, {too_long!r}")
        from neontorrent import peer as PR
        frag = f"#v=1&k={S.b64e(os.urandom(32))}&t={S.b64e(os.urandom(16))}"
        refused = []
        for code in (f"http://8.8.8.8:80/{frag}", f"https://evil.example/{frag}", f"http://127.0.0.1:{server.port}/{frag}",
                     f"https://x.trycloudflare.com.evil.io/{frag}", f"file:///C:/Windows/{frag}"):
            try:
                PR.parse_code(code)
            except PR.PeerError:
                refused.append(code)
        check("PC to PC: a pasted pair code can only reach a LAN address or a trycloudflare.com tunnel",
              len(refused) == 5, f"{len(refused)}/5 hostile codes refused")
        ids = Path(tempfile.mkdtemp(prefix="neon_ids_"))
        trusted_id, intruder = PR.Identity.load(ids / "a"), PR.Identity.load(ids / "b")
        store = PR.PeerStore(ids / "host")
        store.remember(trusted_id.public, "Trusted PC")
        host = S.ShareServer("127.0.0.1", save / "FTP2", "HOST", allow_loopback=True,
                             identity=PR.Identity.load(ids / "host"), trusted=store.is_trusted)
        host.start()
        try:
            forged = PR.PeerClient(host.url("send"), trusted_id, "Fake", allow_loopback=True)
            forged.identity.sign = intruder.sign                  # claims the trusted key without its private key
            state = forged.hello()["state"]
            honest = PR.PeerClient(host.url("send"), PR.Identity.load(ids / "a"), "Trusted",
                                   allow_loopback=True).hello()["state"]
        finally:
            host.stop()
        check("PC to PC: a PC claiming a paired key without that key's signature still needs Allow",
              state == "pending" and honest == "allowed", f"forged {state}, real paired PC {honest}")
        rebind, _ = post(server.port, "/api/hello", body, host="evil.example:80")
        check("Share: requests for another host name are refused (DNS rebinding)", rebind == 421, f"HTTP {rebind}")
        server.public_ips = {"203.0.113.5"}
        server.set_tunnel("https://audit-tunnel-0001.trycloudflare.com")
        forged, _ = post(server.port, "/api/hello", body, host="audit-tunnel-0001.trycloudflare.com")
        check("Share: a request posing as tunnel traffic without Cloudflare's client-IP header is refused",
              forged == 403, f"HTTP {forged}")
        hop = server.where("cf:203.0.113.5")["lan"]
        server.lan_hop = False
        stay = server.where("cf:203.0.113.5")["lan"]
        check("Share: INTERNET mode never hands the LAN address to a phone that came through the tunnel",
              bool(hop) and stay == "", f"auto {hop!r}, internet mode {stay!r}")
        server.set_tunnel("")
        stale, _ = post(server.port, "/api/hello", body, host="audit-tunnel-0001.trycloudflare.com")
        check("Share: once the tunnel is stopped its host name is refused", stale == 421, f"HTTP {stale}")

        raw = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        started = time.monotonic()
        raw.sendall(f"POST /api/up?s=nobody&n=1&i=0 HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n"
                    f"Content-Length: {S.CHUNK + S.TAG}\r\n\r\n".encode())      # headers only: the body never comes
        answer = raw.recv(64)
        waited = time.monotonic() - started
        raw.close()
        check("Share: an upload from an unknown session is refused before its 1 MB body is read",
              answer.startswith(b"HTTP/1.1 401") and waited < 3, f"{answer[:12]!r} after {waited:.1f}s")

        idle = [socket.create_connection(("127.0.0.1", server.port), timeout=5) for _ in range(S.MAX_CONNECTIONS)]
        time.sleep(0.5)
        extra = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        extra.sendall(f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n\r\n".encode())
        try:
            dropped = extra.recv(64) == b""
        except OSError:
            dropped = True                          # reset by the server counts as dropped too
        extra.close()
        for s in idle:
            s.close()
        time.sleep(1.0)
        status, _ = post(server.port, "/api/hello", b"{}")
        check(f"Share: a connection flood is capped at {S.MAX_CONNECTIONS}; the server serves again afterwards",
              dropped and status == 403, f"extra dropped {dropped}, then HTTP {status}")
    finally:
        server.stop()
    gate = S.ShareServer("127.0.0.1", save, "AUDIT")
    gate.start()
    try:
        status, _ = post(gate.port, "/api/hello", b"{}")
        check("Share: only private-network (RFC 1918 / link-local) addresses may connect", status == 403,
              f"127.0.0.1 got HTTP {status}")
    finally:
        gate.stop()


def main() -> int:
    save = tempfile.mkdtemp(prefix="neon_dl_")
    e = engine(save)
    try:
        test_paths(e, save)
        test_symlink(e, save)
        test_guard(e, save)
        test_inputs(e)
        test_trackerless_magnet(e)
        test_magnet_metadata(e, save)
        test_ssrf(e, save)
        test_ui()
        test_finish(e, save)
        test_static()
        test_share()
    finally:
        e.shutdown()
    passed = sum(ok for _, ok, _ in RESULTS)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
