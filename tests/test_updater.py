"""Over-the-air updates (src/neontorrent/updater.py) against a fake GitHub API on 127.0.0.1."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from neontorrent import updater as U  # noqa: E402

TEMP = Path(os.environ.get("TEMP", tempfile.gettempdir()))
BUILT_MSI = Path(__file__).resolve().parents[2] / "neon-build" / "msi" / "out" / "NEON-Torrent-Setup.msi"
PAYLOAD = os.urandom(300_000)


class Fake(BaseHTTPRequestHandler):
    release: dict = {}
    body = PAYLOAD

    def log_message(self, *args):
        pass

    def do_GET(self):
        data = json.dumps(self.release).encode() if self.path.startswith("/api") else self.body
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.root = Path(tempfile.mkdtemp(prefix="neon_upd_", dir=TEMP))

    def tearDown(self):
        self.server.shutdown()
        shutil.rmtree(self.root, ignore_errors=True)

    def release(self, tag="v99.0.0", digest=None, **extra):
        Fake.release = {"tag_name": tag, "draft": False, "prerelease": False, "body": "## New\n- things",
                        "assets": [{"name": U.ASSET, "size": len(Fake.body),
                                    "browser_download_url": self.base + "/file.msi",
                                    "digest": "sha256:" + (digest or hashlib.sha256(Fake.body).hexdigest())}],
                        **extra}

    def test_versions(self):
        self.assertTrue(U.newer("3.6.0", "3.5.1"))
        self.assertTrue(U.newer("v3.10", "3.9.9"))
        self.assertFalse(U.newer("3.5.1", "3.5.1"))
        self.assertFalse(U.newer("3.5.0", "3.5.1"))

    def test_latest_reads_the_msi_asset(self):
        self.release()
        info = U.latest(self.base + "/api")
        self.assertEqual((info["version"], info["size"], info["notes"]), ("99.0.0", len(PAYLOAD), "## New\n- things"))
        self.release(prerelease=True)
        self.assertIsNone(U.latest(self.base + "/api"))

    def test_digest_mismatch_is_refused_and_deleted(self):
        self.release(digest="0" * 64)
        info = U.latest(self.base + "/api")
        with self.assertRaises(U.UpdateError):
            U.download(info, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_file_that_is_not_neon_is_refused(self):
        self.release()                                   # right digest, but not an MSI at all
        with self.assertRaises(U.UpdateError):
            U.download(U.latest(self.base + "/api"), self.root)
        self.assertEqual(list(self.root.glob("*.msi")), [])

    @unittest.skipUnless(BUILT_MSI.is_file(), "no built MSI next to the project")
    def test_real_setup_passes_and_progress_is_reported(self):
        Fake.body = BUILT_MSI.read_bytes()
        try:
            upgrade_code, version = U.msi_identity(BUILT_MSI)
            self.assertEqual(upgrade_code.upper(), U.UPGRADE_CODE)
            self.release(tag="v" + version)
            seen = []
            path = U.download(U.latest(self.base + "/api"), self.root, progress=lambda d, t: seen.append((d, t)))
            self.assertEqual(path.read_bytes(), Fake.body)
            self.assertEqual(seen[-1][0], len(Fake.body))
            self.release(tag="v0.0.1")                     # a release whose version does not match the package
            with self.assertRaises(U.UpdateError):
                U.download(U.latest(self.base + "/api"), self.root / "other")
        finally:
            Fake.body = PAYLOAD

    def test_notes_are_shown_once(self):
        U.save_notes(self.root, "9.9.9", "notes")
        self.assertEqual(U.pending_notes(self.root, "9.9.9"), "notes")
        self.assertIsNone(U.pending_notes(self.root, "9.9.9"))


if __name__ == "__main__":
    unittest.main()
