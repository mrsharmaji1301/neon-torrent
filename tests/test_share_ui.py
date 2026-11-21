"""File Sharing page: every file the phone sends shows on the PC, even ones that arrive whole between two polls."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)

from neontorrent.share_ui import ShareTab  # noqa: E402


def upload(number: int, name: str, path: Path, state: str = "done") -> dict:
    size = path.stat().st_size
    return {"direction": "up", "number": number, "name": name, "size": size, "done": size if state == "done" else 0,
            "state": state, "path": str(path), "offer_id": "", "elapsed": 0.1}


class ReceivedFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="neon_share_ui_"))
        self.tab = ShareTab(lambda: str(self.dir), lambda panel: None, lambda text: None, lambda *a, **k: None)

    def test_small_files_first_seen_done_all_show(self) -> None:
        files = []
        for i, name in enumerate(("Chapter_04.txt", "Chapter_05.txt", "Chapter_06.txt"), start=1):
            path = self.dir / name
            path.write_text("x" * (9000 + i * 1000), encoding="utf-8")
            files.append(upload(i, name, path))
        self.tab.mode = "receive"
        self.tab._sync_tiles(files)                          # one poll after all three already finished
        self.assertEqual(sorted(self.tab.recv_grid.tiles), ["r1", "r2", "r3"])
        self.assertTrue(self.tab.overall_label.text().startswith("3/3"))

    def test_closed_tile_does_not_come_back(self) -> None:
        path = self.dir / "a.txt"
        path.write_text("hello", encoding="utf-8")
        self.tab._sync_tiles([upload(1, "a.txt", path)])
        self.tab._close_received("r1")                       # no server: the next poll no longer lists it
        self.tab._sync_tiles([])
        self.assertNotIn("r1", self.tab.recv_grid.tiles)


if __name__ == "__main__":
    unittest.main()
