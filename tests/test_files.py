import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from neontorrent import dialogs, engine


def listing(*paths: str) -> list[dict]:
    return [{"index": i, "path": p, "size": 100 * (i + 1)} for i, p in enumerate(paths)]


class ProposalTests(unittest.TestCase):
    def test_guard_danger_is_proposed_as_dont_download_with_its_reason(self) -> None:
        files = listing("Movie/movie.mkv", "Movie/movie.mkv.exe", "Movie/readme.txt")
        findings = {"1": {"level": "danger", "reason": "Disguised .exe"}, "2": {"level": "caution", "reason": "x"}}
        out = engine.proposed_priorities(files, findings, skip=True)
        self.assertEqual([f["priority"] for f in out], [4, 0, 4])
        self.assertEqual(out[1]["reason"], "Disguised .exe")
        self.assertTrue(out[1]["danger"])
        self.assertFalse(out[2]["danger"])

    def test_guard_skip_off_keeps_every_file_normal(self) -> None:
        files = listing("a.exe")
        out = engine.proposed_priorities(files, {"0": {"level": "danger", "reason": "r"}}, skip=False)
        self.assertEqual(out[0]["priority"], 4)
        self.assertEqual(out[0]["reason"], "r")


class PriorityVectorTests(unittest.TestCase):
    def test_unnamed_files_are_not_downloaded(self) -> None:
        self.assertEqual(engine.priority_vector(4, [[0, 7], [2, 1]]), [7, 0, 1, 0])

    def test_current_priorities_are_kept(self) -> None:
        self.assertEqual(engine.priority_vector(3, [[1, 0]], [4, 4, 4]), [4, 0, 4])

    def test_bad_input_never_reaches_libtorrent(self) -> None:
        pairs = [[-1, 7], [9, 7], [1, 99], [2, -5], ["x", 4], [3], None, [0, "4"]]
        self.assertEqual(engine.priority_vector(4, pairs), [4, 7, 0, 0])

    def test_current_list_is_fitted_to_the_file_count(self) -> None:
        self.assertEqual(engine.priority_vector(2, [], [4, 4, 4]), [4, 4])
        self.assertEqual(engine.priority_vector(3, [], [7]), [7, 0, 0])


class DialogHelperTests(unittest.TestCase):
    def test_priority_names(self) -> None:
        names = [dialogs.priority_name(p) for p in range(8)]
        self.assertEqual(names, ["Don't download", "Low", "Low", "Normal", "Normal", "Normal", "High", "High"])
        self.assertEqual({dialogs.priority_name(v) for v, name, _c in dialogs.PRIORITIES},
                         {name for _v, name, _c in dialogs.PRIORITIES})

    def test_selection_totals_count_only_wanted_files(self) -> None:
        files = [{"priority": 7, "size": 10}, {"priority": 0, "size": 99}, {"priority": 1, "size": 5}]
        self.assertEqual(dialogs.selection_totals(files), (2, 15))
        self.assertEqual(dialogs.selection_totals([]), (0, 0))

    def test_free_space_uses_the_nearest_existing_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNotNone(dialogs.free_space(str(Path(tmp) / "not" / "made" / "yet")))
        self.assertIsNone(dialogs.free_space(""))

    def test_space_note(self) -> None:
        self.assertEqual(dialogs.space_note(None, 10, "F:")[1], "yellow")
        text, color = dialogs.space_note(5, 10, "F:")
        self.assertEqual(color, "red")
        self.assertIn("NOT ENOUGH SPACE", text)
        self.assertEqual(dialogs.space_note(10, 10, "F:")[1], "green")

    def test_display_paths_drop_the_shared_top_folder(self) -> None:
        self.assertEqual(dialogs.display_paths(["Show/a.mkv", "Show\\Subs\\a.srt"]), ["a.mkv", "Subs\\a.srt"])
        self.assertEqual(dialogs.display_paths(["Show/a.mkv"]), ["Show\\a.mkv"])
        self.assertEqual(dialogs.display_paths(["A/x", "B/y"]), ["A\\x", "B\\y"])
        self.assertEqual(dialogs.display_paths(["Show/a", "loose.txt"]), ["Show\\a", "loose.txt"])


if __name__ == "__main__":
    unittest.main()
