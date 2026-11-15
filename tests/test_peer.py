"""PC to PC transfer (src/neontorrent/peer.py) against a real ShareServer on 127.0.0.1."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from neontorrent import peer as P  # noqa: E402
from neontorrent import share as S  # noqa: E402

TEMP = Path(os.environ.get("TEMP", tempfile.gettempdir()))


class PairCodeTests(unittest.TestCase):
    KEY, TOKEN = S.b64e(bytes(range(32))), S.b64e(bytes(16))

    def test_only_lan_and_quick_tunnel_codes(self) -> None:
        frag = f"#v=1&m=send&k={self.KEY}&t={self.TOKEN}"
        self.assertEqual(P.parse_code(f"http://192.168.1.7:5123/{frag}").host, "192.168.1.7")
        self.assertEqual(P.parse_code(f"  https://abc-def-1.trycloudflare.com/{frag} ").scheme, "https")
        for bad in (f"http://8.8.8.8:80/{frag}", f"https://evil.example.com/{frag}", f"http://127.0.0.1:5000/{frag}",
                    f"http://user:pw@192.168.1.7:5123/{frag}", f"https://x.trycloudflare.com.evil.io/{frag}",
                    f"file:///C:/Windows/{frag}", "http://192.168.1.7:5123/#k=AAAA&t=BBBB", "hello", ""):
            with self.assertRaises(P.PeerError, msg=bad):
                P.parse_code(bad)


class PeerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="neon_peer_", dir=TEMP))
        self.host_id = P.Identity.load(self.root / "host")
        self.client_id = P.Identity.load(self.root / "client")
        self.store = P.PeerStore(self.root / "host")
        self.server = S.ShareServer("127.0.0.1", self.root / "FTP", "HOST-PC", allow_loopback=True,
                                    identity=self.host_id, trusted=self.store.is_trusted)
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def client(self) -> P.PeerClient:
        return P.PeerClient(self.server.url("send"), self.client_id, "CLIENT-PC", allow_loopback=True)

    def test_identity_survives_reload_and_is_protected(self) -> None:
        again = P.Identity.load(self.root / "host")
        self.assertEqual(again.public, self.host_id.public)
        raw = self.host_id.private.private_bytes_raw()
        self.assertNotIn(raw, (self.root / "host" / "identity.key").read_bytes())    # DPAPI, not the clear key

    def test_pair_send_get_text_and_trust(self) -> None:
        c = self.client()
        reply = c.hello()
        self.assertEqual(reply["state"], "pending")
        self.assertEqual(c.remote_id, self.host_id.public)                             # the host proved its key
        phone = self.server.snapshot()["phones"][0]
        self.assertEqual((phone["kind"], phone["name"]), ("pc", "CLIENT-PC"))
        self.assertEqual(S.b64d(phone["peer_id"]), self.client_id.public)
        self.server.decide(phone["sid"], True)
        self.assertEqual(c.ping()["state"], "allowed")
        # client -> host
        source = self.root / "report.bin"
        source.write_bytes(os.urandom(S.CHUNK * 2 + 77))
        seen = []
        saved = c.upload(source, seen.append, lambda: False)
        self.assertEqual((self.root / "FTP" / saved).read_bytes(), source.read_bytes())
        self.assertEqual(seen[-1], source.stat().st_size)
        # host -> client
        offer = self.server.add_offer(source)
        files = c.files()
        self.assertEqual([f["id"] for f in files], [offer.id])
        got = c.download(files[0], self.root / "inbox", lambda _n: None, lambda: False)
        self.assertEqual(got.read_bytes(), source.read_bytes())
        self.assertEqual(list((self.root / "inbox").glob("*" + S.PART_SUFFIX)), [])
        c.send_text("hello from the other PC")
        self.assertEqual([t["text"] for t in self.server.take_texts()], ["hello from the other PC"])
        self.server.send_text("reply from the host\x00")
        self.server.send_text("second")
        self.assertEqual(c.ping()["trev"], 2)
        self.assertEqual([t["text"] for t in c.texts(0)], ["reply from the host", "second"])
        self.assertEqual([t["text"] for t in c.texts(1)], ["second"])
        c.bye()
        self.assertEqual(self.server.outbox, [])                  # dropped with the session: never shown to the next
        with self.assertRaises(S.ShareError):
            self.server.send_text("nobody is connected")
        # remembered: the next session with a fresh code is let in without the Allow prompt
        self.store.remember(self.client_id.public, "CLIENT-PC")
        self.assertEqual(self.client().hello()["state"], "allowed")

    def test_cancelled_download_leaves_no_part_file(self) -> None:
        c = self.client()
        c.hello()
        self.server.decide(self.server.snapshot()["phones"][0]["sid"], True)
        source = self.root / "big.bin"
        source.write_bytes(os.urandom(S.CHUNK * 3))
        offer = self.server.add_offer(source)
        calls = []
        with self.assertRaises(P.PeerError):
            c.download({"id": offer.id, "name": "big.bin"}, self.root / "inbox", calls.append,
                       lambda: len(calls) >= 1)
        self.assertEqual(list((self.root / "inbox").iterdir()), [])

    def test_forged_identity_is_not_trusted(self) -> None:
        self.store.remember(self.client_id.public, "CLIENT-PC")
        c = self.client()
        intruder = P.Identity.load(self.root / "intruder")
        c.identity.sign = intruder.sign                       # claims the trusted key, signs with another one
        self.assertEqual(c.hello()["state"], "pending")
        phone = self.server.snapshot()["phones"][0]
        self.assertEqual((phone["kind"], phone["peer_id"]), ("phone", ""))

    def test_store_rename_forget(self) -> None:
        self.store.remember(self.client_id.public, "Old name")
        key = S.b64e(self.client_id.public)
        self.store.rename(key, "Office PC")
        self.assertEqual(P.PeerStore(self.root / "host").items()[0][1]["name"], "Office PC")
        self.store.forget(key)
        self.assertFalse(P.PeerStore(self.root / "host").is_trusted(self.client_id.public))


if __name__ == "__main__":
    unittest.main()
