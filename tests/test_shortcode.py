"""Short codes (src/neontorrent/shortcode.py). The live tests use the public magic-wormhole relay and are skipped when
it cannot be reached."""
from __future__ import annotations

import socket
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from neontorrent import shortcode as SC  # noqa: E402

LINK = "https://abc-def-ghi.trycloudflare.com/#v=1&m=send&k=" + "A" * 43 + "&t=" + "B" * 22


def relay_reachable() -> bool:
    try:
        socket.create_connection(("relay.magic-wormhole.io", 4000), timeout=8).close()
        return True
    except OSError:
        return False


class OfflineTests(unittest.TestCase):
    def test_words_and_format(self) -> None:
        self.assertEqual((len(SC.WORDS), len(set(SC.WORDS))), (256, 256))
        self.assertEqual(SC.normalize("  7 Tiger_CRYSTAL "), "7-tiger-crystal")
        self.assertTrue(SC.is_short_code("12-lion-pixel"))
        for bad in ("", "tiger-crystal", "7-tiger", "x-tiger-crystal", "12345-tiger-crystal", LINK):
            self.assertFalse(SC.is_short_code(bad), bad)

    def test_unknown_word_is_refused_before_any_network(self) -> None:
        with self.assertRaises(SC.ShortCodeError) as ctx:
            SC.fetch_pair_code("7-tiger-xylophone", url="ws://127.0.0.1:9/never")
        self.assertIn("xylophone", str(ctx.exception))

    def test_seal_round_trip_and_tamper(self) -> None:
        pair, done = SC._keys(b"k" * 32)
        sealed = SC._seal(pair, LINK.encode())
        self.assertEqual(SC._open(pair, sealed), LINK.encode())
        with self.assertRaises(Exception):
            SC._open(done, sealed)                                     # the other key cannot open it
        flipped = sealed[:-2] + ("00" if sealed[-2:] != "00" else "11")
        with self.assertRaises(Exception):
            SC._open(pair, flipped)


@unittest.skipUnless(relay_reachable(), "the magic-wormhole relay is not reachable")
class LiveTests(unittest.TestCase):
    def host(self) -> tuple[dict, threading.Event]:
        got, done = {}, threading.Event()

        def on_done(ok: bool, message: str) -> None:
            got["result"] = (ok, message)
            done.set()
        got["host"] = SC.ShortCodeHost(lambda: LINK, lambda code: got.__setitem__("code", code), on_done)
        deadline = time.time() + 30
        while "code" not in got and time.time() < deadline:
            time.sleep(0.2)
        self.assertIn("code", got, "no code from the relay")
        return got, done

    def test_right_code_hands_over_the_pair_code(self) -> None:
        got, done = self.host()
        self.assertEqual(SC.fetch_pair_code(got["code"].upper().replace("-", " ")), LINK)
        self.assertTrue(done.wait(30))
        self.assertTrue(got["result"][0], got["result"])

    def test_wrong_code_is_refused_and_closes_the_code(self) -> None:
        got, done = self.host()
        number, first, second = got["code"].split("-")
        wrong = f"{number}-{first}-{'tiger' if second != 'tiger' else 'lion'}"
        with self.assertRaises(SC.ShortCodeError):
            SC.fetch_pair_code(wrong)
        self.assertTrue(done.wait(30))
        self.assertFalse(got["result"][0])
        with self.assertRaises(SC.ShortCodeError):                       # the real code no longer works either
            SC.fetch_pair_code(got["code"])


if __name__ == "__main__":
    unittest.main()
