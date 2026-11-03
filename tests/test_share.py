import http.client
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cryptography.exceptions import InvalidTag  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey  # noqa: E402

from neontorrent import share as S  # noqa: E402

BUILD_TMP = Path(__file__).resolve().parents[2] / "neon-build" / "tmp"     # keep test files off drive C:


CREATED: list[Path] = []


def temp_dir() -> Path:
    CREATED.append(Path(tempfile.mkdtemp(prefix="neon_share_", dir=BUILD_TMP if BUILD_TMP.is_dir() else None)))
    return CREATED[-1]


def tearDownModule() -> None:
    for folder in CREATED:
        shutil.rmtree(folder, ignore_errors=True)


class Phone:
    """Stand-in for the browser page: same protocol as share_web/app.js."""

    def __init__(self, server: S.ShareServer, url: str | None = None, token: bytes | None = None):
        self.server = server
        frag = parse_qs(urlsplit(url or server.url("send")).fragment)
        self.pc_pub = S.b64d(frag["k"][0])
        self.token = token or S.b64d(frag["t"][0])
        self.private = X25519PrivateKey.generate()
        self.pub = self.private.public_key().public_bytes_raw()
        up, down = S.derive_keys(self.private.exchange(X25519PublicKey.from_public_bytes(self.pc_pub)),
                                 self.token, self.pc_pub, self.pub)
        self.channel = S.Channel(up, down, role="phone")
        self.sid, self.counter = "", 0

    def request(self, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers={"Content-Type": "application/octet-stream"})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def hello_body(self) -> bytes:
        sealed = self.channel.seal({"name": "Test phone", "model": "Android"}, 0, b"H" + self.pc_pub + self.pub)
        return json.dumps({"p": S.b64e(self.pub), "d": sealed}).encode()

    def hello(self) -> tuple[int, dict]:
        status, body = self.request("POST", "/api/hello", self.hello_body())
        reply = json.loads(body)
        if status == 200:
            self.sid = reply["s"]
            reply = self.channel.open(reply["d"], reply["c"], f"R{self.sid}:0".encode())
        return status, reply

    def call(self, message: dict, counter: int | None = None) -> tuple[int, dict]:
        self.counter = counter if counter is not None else self.counter + 1
        sealed = self.channel.seal(message, self.counter, f"C{self.sid}:{self.counter}".encode())
        status, body = self.request("POST", "/api/c", json.dumps({"s": self.sid, "c": self.counter,
                                                                  "d": sealed}).encode())
        reply = json.loads(body)
        if status == 200:
            reply = self.channel.open(reply["d"], reply["c"], f"R{self.sid}:{self.counter}".encode())
        return status, reply

    def upload(self, name: str, data: bytes) -> dict:
        _status, begin = self.call({"op": "begin", "name": name, "size": len(data)})
        n, chunks = begin["n"], begin["chunks"]
        reply = {}
        for i in range(chunks):
            sealed = self.channel.seal_chunk(n, i, chunks, data[i * S.CHUNK:(i + 1) * S.CHUNK])
            status, body = self.request("POST", f"/api/up?s={self.sid}&n={n}&i={i}", sealed)
            reply = json.loads(body)
            assert status == 200, reply
        return reply


class CryptoTests(unittest.TestCase):
    def setUp(self) -> None:
        pc, phone = X25519PrivateKey.generate(), X25519PrivateKey.generate()
        self.pc_pub, self.phone_pub = pc.public_key().public_bytes_raw(), phone.public_key().public_bytes_raw()
        token = os.urandom(16)
        pc_keys = S.derive_keys(pc.exchange(phone.public_key()), token, self.pc_pub, self.phone_pub)
        phone_keys = S.derive_keys(phone.exchange(pc.public_key()), token, self.pc_pub, self.phone_pub)
        self.assertEqual(pc_keys, phone_keys)
        self.assertNotEqual(pc_keys[0], pc_keys[1])
        self.pc, self.phone = S.Channel(*pc_keys), S.Channel(*phone_keys, role="phone")

    def test_control_round_trip_and_binding(self) -> None:
        sealed = self.phone.seal({"op": "ping"}, 5, b"C:x:5")
        self.assertEqual(self.pc.open(sealed, 5, b"C:x:5"), {"op": "ping"})
        with self.assertRaises(InvalidTag):
            self.pc.open(sealed, 6, b"C:x:5")              # other counter
        with self.assertRaises(InvalidTag):
            self.pc.open(sealed, 5, b"C:y:5")              # other session
        with self.assertRaises(InvalidTag):
            self.phone.open(sealed, 5, b"C:x:5")           # own message reflected back

    def test_chunk_round_trip_and_tamper(self) -> None:
        data = os.urandom(1000)
        sealed = self.phone.seal_chunk(3, 7, 9, data)
        self.assertEqual(len(sealed), len(data) + S.TAG)
        self.assertEqual(self.pc.open_chunk(3, 7, 9, sealed), data)
        for number, index, chunks in ((4, 7, 9), (3, 8, 9), (3, 7, 8)):   # file, position and count are bound
            with self.assertRaises(InvalidTag):
                self.pc.open_chunk(number, index, chunks, sealed)
        flipped = bytes([sealed[0] ^ 1]) + sealed[1:]
        with self.assertRaises(InvalidTag):
            self.pc.open_chunk(3, 7, 9, flipped)

    def test_wrong_token_gives_other_keys(self) -> None:
        pc, phone = X25519PrivateKey.generate(), X25519PrivateKey.generate()
        a = S.derive_keys(pc.exchange(phone.public_key()), b"1" * 16, b"p" * 32, b"q" * 32)
        b = S.derive_keys(pc.exchange(phone.public_key()), b"2" * 16, b"p" * 32, b"q" * 32)
        self.assertNotEqual(a, b)

    def test_nonces_are_unique_per_kind_file_and_chunk(self) -> None:
        seen = {S.nonce(k, n, i) for k in (1, 2, 3, 4) for n in (0, 1, 2) for i in (0, 1, 1 << 40)}
        self.assertEqual(len(seen), 4 * 3 * 3)
        with self.assertRaises(ValueError):
            S.nonce(3, 1 << 24, 0)

    def test_chunk_math(self) -> None:
        self.assertEqual(S.chunk_count(0), 1)
        self.assertEqual(S.chunk_length(0, 0), 0)
        self.assertEqual(S.chunk_count(S.CHUNK * 2 + 5), 3)
        self.assertEqual(S.chunk_length(S.CHUNK * 2 + 5, 2), 5)


class NameTests(unittest.TestCase):
    def test_safe_name(self) -> None:
        cases = {"../../evil.exe": "evil.exe", "..\\..\\Windows\\x.dll": "x.dll", "CON.txt": "_CON.txt",
                 "nul": "_nul", "COM1.tar.gz": "_COM1.tar.gz", "photo\u202egpj.exe": "photogpj.exe",
                 "trailing. . ": "trailing", "": "file", "..": "file", 'a<b>:c|d?.jpg': "a_b__c_d_.jpg",
                 "tab\there.txt": "tabhere.txt", "C:\\Users\\x\\IMG_1.jpg": "IMG_1.jpg"}
        for raw, expected in cases.items():
            self.assertEqual(S.safe_name(raw), expected, raw)
        long = S.safe_name("x" * 400 + ".jpeg")
        self.assertLessEqual(len(long), 150)
        self.assertTrue(long.endswith(".jpeg"))

    def test_unique_path(self) -> None:
        folder = temp_dir()
        (folder / "a.jpg").write_bytes(b"1")
        (folder / "a (1).jpg").write_bytes(b"2")
        self.assertEqual(S.unique_path(folder, "a.jpg").name, "a (2).jpg")
        self.assertEqual(S.unique_path(folder, "b.jpg").name, "b.jpg")

    def test_private_ips(self) -> None:
        for ip in ("192.168.1.5", "10.0.0.2", "172.20.1.1", "169.254.3.4", "::ffff:192.168.0.9"):
            self.assertTrue(S.is_private_ip(ip), ip)
        for ip in ("8.8.8.8", "127.0.0.1", "172.32.0.1", "100.64.0.1", "::1", "junk"):
            self.assertFalse(S.is_private_ip(ip), ip)

    def test_clean_label(self) -> None:
        self.assertEqual(S.clean_label("  My\nPhone\u202e  ", 40), "My Phone")
        self.assertEqual(len(S.clean_label("x" * 100, 40)), 40)


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.save = temp_dir() / "FTP"
        self.server = S.ShareServer("127.0.0.1", self.save, "TEST-PC", allow_loopback=True)
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()

    def paired(self) -> Phone:
        phone = Phone(self.server)
        status, reply = phone.hello()
        self.assertEqual((status, reply["state"]), (200, "pending"))
        self.assertEqual(phone.call({"op": "list"})[1].get("error"), "not allowed on the PC yet")
        self.server.decide(phone.sid, True)
        self.assertEqual(phone.call({"op": "ping", "name": "Renamed"})[1]["state"], "allowed")
        return phone

    def test_wrong_token_is_refused(self) -> None:
        status, reply = Phone(self.server, token=os.urandom(16)).hello()
        self.assertEqual(status, 403)
        self.assertEqual(self.server.snapshot()["phones"], [])

    def test_replayed_hello_and_used_qr_are_refused(self) -> None:
        phone = Phone(self.server)
        self.assertEqual(phone.hello()[0], 200)
        self.assertEqual(phone.request("POST", "/api/hello", phone.hello_body())[0], 403)
        url = self.server.url("send")
        self.server.decide(phone.sid, False)
        self.assertEqual(Phone(self.server, url).hello()[0], 403)          # QR rotated after the decision

    def test_upload_round_trip_dedupe_and_rejections(self) -> None:
        phone = self.paired()
        self.assertEqual(self.server.snapshot()["phones"][0]["name"], "Renamed")
        data = os.urandom(S.CHUNK * 2 + 12345)
        self.assertEqual(phone.upload("../clip.mp4", data)["saved"], "clip.mp4")
        self.assertEqual(phone.upload("clip.mp4", b"")["saved"], "clip (1).mp4")
        self.assertEqual((self.save / "clip.mp4").read_bytes(), data)
        self.assertEqual((self.save / "clip (1).mp4").read_bytes(), b"")
        self.assertEqual(list(self.save.glob("*" + S.PART_SUFFIX)), [])
        # replayed control message
        status, _ = phone.call({"op": "ping"}, counter=phone.counter)
        self.assertEqual(status, 409)
        # tampered and out-of-order chunks
        n, chunks = phone.call({"op": "begin", "name": "x.bin", "size": S.CHUNK + 1})[1].values()
        sealed = bytearray(phone.channel.seal_chunk(n, 0, chunks, os.urandom(S.CHUNK)))
        sealed[10] ^= 1
        self.assertEqual(phone.request("POST", f"/api/up?s={phone.sid}&n={n}&i=0", bytes(sealed))[0], 403)
        later = phone.channel.seal_chunk(n, 1, chunks, b"z")
        self.assertEqual(phone.request("POST", f"/api/up?s={phone.sid}&n={n}&i=1", later)[0], 409)
        # cancel on the PC: the phone gets 410 and the partial file is gone
        self.server.cancel(n)
        good = phone.channel.seal_chunk(n, 0, chunks, os.urandom(S.CHUNK))
        self.assertEqual(phone.request("POST", f"/api/up?s={phone.sid}&n={n}&i=0", good)[0], 410)
        self.assertEqual(list(self.save.glob("*" + S.PART_SUFFIX)), [])

    def test_download_round_trip(self) -> None:
        phone = self.paired()
        source = temp_dir() / "ubuntu-24.04.iso"
        data = os.urandom(S.CHUNK + 777)
        source.write_bytes(data)
        offer = self.server.add_offer(source)
        files = phone.call({"op": "list"})[1]["files"]
        self.assertEqual([(f["id"], f["name"], f["size"]) for f in files], [(offer.id, source.name, len(data))])
        got = phone.call({"op": "get", "id": offer.id})[1]
        out = b""
        for i in range(got["chunks"]):
            status, body = phone.request("GET", f"/api/dl?s={phone.sid}&n={got['n']}&i={i}")
            self.assertEqual(status, 200)
            out += phone.channel.open_chunk(got["n"], i, got["chunks"], body)
        self.assertEqual(out, data)
        self.assertEqual(self.server.snapshot()["transfers"][0]["state"], "done")

    def test_unknown_session_and_static_page(self) -> None:
        phone = Phone(self.server)
        phone.sid = "nope"
        self.assertEqual(phone.call({"op": "ping"})[0], 401)
        status, body = phone.request("GET", "/")
        self.assertIn(status, (200, 404))
        self.assertEqual(phone.request("GET", "/../share.py")[0], 404)


class NetworkGateTests(unittest.TestCase):
    def test_loopback_is_not_a_private_network(self) -> None:
        server = S.ShareServer("127.0.0.1", temp_dir(), "TEST-PC")
        server.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
            conn.request("GET", "/")
            self.assertEqual(conn.getresponse().status, 403)
            conn.close()
        finally:
            server.stop()


TUNNEL = "https://quiet-river-1234.trycloudflare.com"


class TunnelTests(unittest.TestCase):
    """Internet mode, offline: requests are made to look like cloudflared's (Host + CF-Connecting-IP)."""

    def setUp(self) -> None:
        self.server = S.ShareServer("127.0.0.1", temp_dir() / "FTP", "TEST-PC", allow_loopback=True)
        self.server.public_ips = {"203.0.113.5", "2001:db8:1:2::9"}      # no trace lookup in tests
        self.server.set_tunnel(TUNNEL)
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()

    def raw(self, method: str, path: str, headers: dict, body: bytes | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def via_tunnel(self, ip: str) -> dict:
        return {"Host": TUNNEL[8:], "CF-Connecting-IP": ip}

    def test_qr_uses_the_tunnel(self) -> None:
        self.assertTrue(self.server.url("send").startswith(TUNNEL + "/#v=1&m=send&k="))
        self.server.set_tunnel("https://evil.example.com")              # only trycloudflare URLs are taken
        self.assertTrue(self.server.url("send").startswith("http://127.0.0.1:"))

    def test_where_points_to_lan_only_behind_the_same_router(self) -> None:
        lan = self.server.lan_url()
        for ip, expected in (("203.0.113.5", lan), ("2001:db8:1:2:aaaa::1", lan), ("198.51.100.7", ""),
                             ("2001:db8:9::1", "")):
            status, body = self.raw("GET", "/api/where", self.via_tunnel(ip))
            self.assertEqual((status, json.loads(body)["lan"]), (200, expected), ip)
        status, body = self.raw("GET", "/api/where", {"Host": f"127.0.0.1:{self.server.port}"})
        self.assertEqual(json.loads(body)["lan"], "")                  # LAN page: nothing to switch to

    def test_tunnel_host_needs_the_cloudflare_header(self) -> None:
        self.assertEqual(self.raw("GET", "/", {"Host": TUNNEL[8:]})[0], 403)
        self.assertEqual(self.raw("GET", "/", {"Host": "other.trycloudflare.com"})[0], 421)
        self.assertIn(self.raw("GET", "/", self.via_tunnel("203.0.113.5"))[0], (200, 404))

    def test_pairing_through_the_tunnel_with_a_chunked_body(self) -> None:
        phone = Phone(self.server)
        body = phone.hello_body()
        chunked = b"".join(b"%x\r\n%s\r\n" % (len(part), part) for part in (body[:40], body[40:])) + b"0\r\n\r\n"
        status, reply = self.raw("POST", "/api/hello", {**self.via_tunnel("198.51.100.7"),
                                                        "Transfer-Encoding": "chunked"}, chunked)
        self.assertEqual(status, 200, reply)
        info = phone.channel.open(json.loads(reply)["d"], json.loads(reply)["c"], f"R{json.loads(reply)['s']}:0".encode())
        self.assertEqual(info["path"], "internet")
        snap = self.server.snapshot()["phones"][0]
        self.assertEqual((snap["path"], snap["ip"], snap["mac"]), ("internet", "198.51.100.7", ""))
        # the same session is not usable from the LAN side
        phone.sid = json.loads(reply)["s"]
        self.assertEqual(phone.call({"op": "ping"})[0], 401)

    def test_same_network(self) -> None:
        ips = {"203.0.113.5", "2001:db8:1:2::9"}
        self.assertTrue(S.same_network("203.0.113.5", ips))
        self.assertTrue(S.same_network("2001:db8:1:2:ffff::1", ips))
        self.assertFalse(S.same_network("203.0.113.6", ips))
        self.assertFalse(S.same_network("junk", ips))
        self.assertFalse(S.same_network("203.0.113.5", set()))


class TunnelProcessTests(unittest.TestCase):
    def test_url_is_read_from_cloudflared_output(self) -> None:
        import io
        seen = []
        tunnel = S.Tunnel("http://192.168.1.5:5000", temp_dir(), seen.append)
        output = (b"INF Requesting new quick Tunnel on trycloudflare.com...\n"
                  b"INF |  https://quiet-river-1234.trycloudflare.com  |\n"
                  b"INF Registered tunnel connection\n")
        tunnel._read(type("P", (), {"stdout": io.BytesIO(output)})())
        self.assertEqual(seen, [TUNNEL, ""])                           # up, then gone when the output ends
        self.assertEqual(tunnel.url, TUNNEL)

    def test_missing_cloudflared_means_lan_only(self) -> None:
        tunnel = S.Tunnel("http://192.168.1.5:5000", temp_dir(), lambda url: None, exe=Path("Z:/nope.exe"))
        tunnel.start()
        self.assertIsNone(tunnel.process)
        self.assertIn("not installed", tunnel.error)


if __name__ == "__main__":
    unittest.main()
