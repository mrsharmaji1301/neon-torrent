"""Smart links, the IDM-style downloader and torrent search, against local servers (no internet needed)."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from neontorrent import downloader as D  # noqa: E402
from neontorrent import search as SR  # noqa: E402
from neontorrent import web  # noqa: E402

TEMP = Path(os.environ.get("TEMP", tempfile.gettempdir()))
DATA = os.urandom(5 * 1024 * 1024 + 123)
HASH = "c9e15763f722f23e98a29decdfae341b98d53056"
NASTY_PAGE = f"""<html><head><meta http-equiv="refresh" content="0;url=http://ads.example/x.exe">
<script>window.open('http://popup.example/win.exe'); document.location='http://ads.example';</script></head>
<body onload="window.open('http://ads.example/a')"><iframe src="http://ads.example/frame"></iframe>
<a href="javascript:alert(1)">Click</a> <a href="http://ads.example/FastDownloader.exe">DOWNLOAD NOW</a>
<a href="/files/ubuntu-24.04.iso.torrent">Ubuntu 24.04 torrent</a>
<a href="magnet:?xt=urn:btih:{HASH}&amp;dn=ubuntu-24.04.iso">Ubuntu magnet</a>
<a href="magnet:?xt=urn:btih:nothash&dn=fake">Fake magnet</a>
<a href="/files/report.pdf">Report</a></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    ranges = True

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head: bool = False):
        if self.path.startswith("/hop/"):
            n = int(self.path.split("/")[2])
            self.send_response(302)
            self.send_header("Location", f"/hop/{n + 1}" if n < 10 else "/file.bin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/to-file":
            self.send_response(302)
            self.send_header("Location", "file:///C:/Windows/win.ini")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/page"):
            body = NASTY_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)
            return
        start, end = 0, len(DATA) - 1
        rng = self.headers.get("Range")
        if rng and self.ranges:
            a, b = rng.split("=")[1].split("-")
            start, end = int(a), int(b) if b else len(DATA) - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(DATA)}")
        else:
            self.send_response(200)
        if self.ranges:
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", 'attachment; filename="data set.bin"')
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        if not head:
            try:
                self.wfile.write(DATA[start:end + 1])
            except OSError:
                pass


class NoRanges(Handler):
    ranges = False


def serve(handler) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class WebTests(unittest.TestCase):
    def setUp(self):
        self.server, self.base = serve(Handler)

    def tearDown(self):
        self.server.shutdown()

    def test_classify(self):
        self.assertEqual(web.classify(f"magnet:?xt=urn:btih:{HASH}")[0], "magnet")
        self.assertEqual(web.classify(HASH.upper())[0], "hash")
        self.assertEqual(web.classify("www.example.org/x.iso"), ("url", "https://www.example.org/x.iso"))
        self.assertEqual(web.classify("magnet:?xt=urn:btih:zzz")[0], "unknown")
        self.assertEqual(web.classify("hello there")[0], "unknown")

    def test_probe_file_and_page(self):
        info = web.probe(self.base + "/file.bin")
        self.assertEqual((info.kind, info.name, info.size, info.ranges), ("file", "data set.bin", len(DATA), True))
        self.assertEqual(web.probe(self.base + "/page").kind, "page")

    def test_zero_popups_page_gives_only_files_magnets_and_torrents(self):
        links = web.page_links(NASTY_PAGE, self.base + "/page")
        kinds = {link.kind for link in links}
        urls = " ".join(link.url for link in links)
        self.assertEqual(kinds, {"torrent", "magnet", "document", "program"})
        self.assertNotIn("javascript:", urls)
        self.assertNotIn("frame", urls)
        self.assertNotIn("popup.example", urls)
        self.assertNotIn("nothash", urls)

    def test_redirect_rules(self):
        self.assertEqual(web.probe(self.base + "/hop/6").name, "data set.bin")       # 5 hops are fine
        with self.assertRaises(web.WebError):
            web.probe(self.base + "/hop/1")                                          # 10 are not
        with self.assertRaises(web.WebError):
            web.probe(self.base + "/to-file")
        for bad in ("file:///C:/Windows/win.ini", "ftp://x/y", "http://user:pw@example.org/"):
            with self.assertRaises(web.WebError):
                web.check_url(bad)
        self.assertTrue(web._is_local("192.168.1.5") and web._is_local("localhost") and web._is_local("10.0.0.1"))
        self.assertFalse(web._is_local("93.184.216.34"))


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="neon_dl_", dir=TEMP))
        self.servers = []

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
        shutil.rmtree(self.root, ignore_errors=True)

    def url(self, handler=Handler, path="/file.bin"):
        server, base = serve(handler)
        self.servers.append(server)
        return base + path

    def wait(self, manager, job_id, state, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            row = next(r for r in manager.snapshot() if r["id"] == job_id)
            if row["state"] == state:
                return row
            time.sleep(0.2)
        self.fail(f"not {state}: {row}")

    def test_split_download_matches_and_is_named(self):
        m = D.DownloadManager(self.root / "data")
        job = m.add(self.url(), str(self.root / "out"), connections=6)
        row = self.wait(m, job.id, "done")
        self.assertEqual(Path(row["path"]).read_bytes(), DATA)
        self.assertEqual(Path(row["path"]).name, "data set.bin")
        self.assertEqual(list((self.root / "out").glob("*" + D.PART_SUFFIX)), [])
        job2 = m.add(self.url(), str(self.root / "out"), connections=2)
        self.assertEqual(Path(self.wait(m, job2.id, "done")["path"]).name, "data set (1).bin")   # never overwrites
        m.close()

    def test_pause_restart_and_resume(self):
        m = D.DownloadManager(self.root / "data")
        m.set_limit(600 * 1024)
        job = m.add(self.url(), str(self.root / "out"), connections=4)
        self.wait(m, job.id, "running")
        time.sleep(2.5)
        m.pause([job.id])
        done_before = next(r for r in m.snapshot() if r["id"] == job.id)["done"]
        self.assertGreater(done_before, 0)
        m.close()
        m2 = D.DownloadManager(self.root / "data")                     # as after a restart
        self.assertEqual(next(r for r in m2.snapshot() if r["id"] == job.id)["state"], "paused")
        m2.resume([job.id])
        row = self.wait(m2, job.id, "done")
        self.assertEqual(Path(row["path"]).read_bytes(), DATA)
        m2.close()

    def test_server_without_ranges_uses_one_connection(self):
        m = D.DownloadManager(self.root / "data")
        job = m.add(self.url(NoRanges), str(self.root / "out"), connections=8)
        row = self.wait(m, job.id, "done")
        self.assertEqual(Path(row["path"]).read_bytes(), DATA)
        self.assertFalse(row["ranges"])
        m.close()

    def test_page_link_is_refused_as_a_file(self):
        m = D.DownloadManager(self.root / "data")
        job = m.add(self.url(path="/page"), str(self.root / "out"))
        self.assertIn("web page", self.wait(m, job.id, "failed")["error"])
        m.close()


TORZNAB = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>
<item><title>Debian 13 netinst</title><link>https://idx.example/dl/1.torrent</link><size>700000000</size>
<pubDate>Mon, 10 Nov 2026 10:00:00 +0000</pubDate>
<torznab:attr name="seeders" value="42"/><torznab:attr name="peers" value="50"/>
<torznab:attr name="magneturl" value="magnet:?xt=urn:btih:{HASH}"/></item>
<item><title>Ad: FastDownloader.exe</title><link>javascript:alert(1)</link></item>
<item><title>Some.Tool.keygen.exe</title><enclosure url="https://idx.example/2.torrent" length="10"
 type="application/x-bittorrent"/></item>
</channel></rss>"""


class SearchTests(unittest.TestCase):
    def test_feed_keeps_only_magnets_and_torrents(self):
        src = SR.Source("x", "Indexer", "torznab", "https://idx.example/api")
        results = [r for r in map(SR._accept, SR.parse_feed(TORZNAB, src)) if r]
        self.assertEqual([r.name for r in results], ["Debian 13 netinst", "Some.Tool.keygen.exe"])
        self.assertEqual((results[0].seeders, results[0].leechers, results[0].date), (42, 8, "2026-11-10"))
        self.assertTrue(results[0].magnet.startswith("magnet:"))
        self.assertEqual(results[1].warning, "program")
        self.assertFalse(results[0].trusted)

    def test_entities_are_refused(self):
        with self.assertRaises(web.WebError):
            SR.parse_feed('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss/>', SR.Source("x", "x",
                                                                                                     "rss", "u"))

    def test_quickwords_and_sources(self):
        prefs = {"search_sources": [SR.new_source("Mine", "rss", "https://feed.example/s?q={query}", quickword="mf")]}
        sources = SR.sources_from_prefs(prefs)
        self.assertEqual([s.name for s in sources], ["Internet Archive", "Mine"])
        self.assertTrue(sources[0].trusted if hasattr(sources[0], "trusted") else sources[0].builtin)
        picked, words = SR.split_quickword("mf ubuntu iso", sources)
        self.assertEqual(([s.name for s in picked], words), (["Mine"], "ubuntu iso"))
        picked, words = SR.split_quickword("ubuntu", sources)
        self.assertEqual((len(picked), words), (2, "ubuntu"))
        with self.assertRaises(ValueError):
            SR.new_source("x", "rss", "https://feed.example/no-query")
        with self.assertRaises(web.WebError):
            SR.new_source("x", "page", "file:///C:/x?q={query}")

    def test_page_source_on_a_nasty_page(self):
        server, base = serve(Handler)
        try:
            src = SR.Source("p", "Page", "page", base + "/page?q={query}")
            results = SR.search_source(src, "ubuntu")
            self.assertEqual(sorted(bool(r.magnet) for r in results), [False, True])
            self.assertTrue(all(r.link.startswith(("magnet:", base + "/files/")) for r in results))
            self.assertTrue(all(r.link.endswith(".torrent") or r.magnet for r in results))
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
