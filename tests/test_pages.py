import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from neontorrent import transfers  # noqa: E402  (src goes on sys.path first)


def row(progress: float, state: str = "Downloading") -> dict:
    return {"progress": progress, "state": state, "down": 0, "up": 0}


class PageTests(unittest.TestCase):
    def test_every_torrent_is_on_exactly_one_of_downloading_and_completed(self) -> None:
        for r in (row(0.0, "Metadata"), row(0.5, "Stopped"), row(0.99, "Error"), row(1.0, "Seeding"),
                  row(1.0, "Stopped")):
            pages = [key for key, *_ in transfers.PAGES if key != "all" and transfers.page_matches(key, r)]
            self.assertEqual(len(pages), 1, r)
            self.assertTrue(transfers.page_matches("all", r))

    def test_page_counts(self) -> None:
        rows = [row(0.2), row(1.0, "Seeding"), row(1.0, "Stopped")]
        self.assertEqual(transfers.page_counts(rows), {"downloading": 1, "completed": 2, "all": 3})

    def test_page_chips_are_known_status_filters(self) -> None:
        known = {key for key, _label, _color in transfers.STATUS_FILTERS}
        for _key, _label, _color, chips in transfers.PAGES:
            self.assertEqual(chips[0], "all")
            self.assertLessEqual(set(chips), known)


if __name__ == "__main__":
    unittest.main()
