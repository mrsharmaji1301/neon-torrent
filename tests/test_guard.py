from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from neontorrent import guard  # noqa: E402  (src goes on sys.path first)


class ClassifyTests(unittest.TestCase):
    def assert_classification(self, path: str, expected_level: str, **kwargs: object) -> str:
        level, reason = guard.classify(path, **kwargs)
        self.assertEqual(level, expected_level, (path, reason))
        return reason

    def test_clean_file(self) -> None:
        self.assertEqual(guard.classify("docs/readme.txt", media_torrent=False, strict=False), (guard.CLEAN, ""))

    def test_all_executable_and_script_extensions_are_cautioned(self) -> None:
        extensions = sorted(guard.EXECUTABLE | guard.SCRIPT)
        for extension in extensions:
            with self.subTest(extension=extension):
                level, reason = guard.classify("payload" + extension, media_torrent=False, strict=False)
                self.assertEqual(level, guard.CAUTION)
                self.assertIn(extension, reason)

    def test_macro_documents_are_cautioned_with_specific_reason(self) -> None:
        for extension in sorted(guard.MACRO_DOC):
            with self.subTest(extension=extension):
                self.assertEqual(
                    guard.classify("report" + extension, media_torrent=False, strict=False),
                    (guard.CAUTION, "Office document with macros"),
                )

    def test_all_shortcut_extensions_are_dangerous(self) -> None:
        for extension in sorted(guard.SHORTCUT):
            with self.subTest(extension=extension):
                level, reason = guard.classify("open-me" + extension, media_torrent=False, strict=False)
                self.assertEqual(level, guard.DANGER)
                self.assertIn("Shortcut", reason)

    def test_double_extensions_and_suspicious_spacing_are_dangerous(self) -> None:
        for path in ("movie.mp4.exe", "archive.pdf.js", "setup   .exe"):
            with self.subTest(path=path):
                reason = self.assert_classification(path, guard.DANGER, media_torrent=False, strict=False)
                self.assertIn("Disguised", reason)

    def test_hidden_direction_and_invisible_characters_are_dangerous(self) -> None:
        for hidden in (chr(0x202E), chr(0x200B), chr(0x2066)):
            with self.subTest(codepoint=hex(ord(hidden))):
                reason = self.assert_classification(
                    "movie" + hidden + ".mp4.exe", guard.DANGER, media_torrent=False, strict=False
                )
                self.assertIn("Hidden Unicode", reason)

    def test_program_inside_media_torrent_is_dangerous(self) -> None:
        reason = self.assert_classification("tools/installer.exe", guard.DANGER, media_torrent=True, strict=False)
        self.assertIn("inside a media torrent", reason)

    def test_strict_mode_rejects_executables_and_scripts(self) -> None:
        for path in ("installer.exe", "run.ps1", "sheet.xlsm"):
            with self.subTest(path=path):
                self.assert_classification(path, guard.DANGER, media_torrent=False, strict=True)

    def test_windows_device_names_with_and_without_extensions_are_dangerous(self) -> None:
        for path in ("CON", "CON.txt", "folder/NUL", "folder/LPT1.log", "COM9.dat", "conout$.txt"):
            with self.subTest(path=path):
                reason = self.assert_classification(path, guard.DANGER, media_torrent=False, strict=False)
                self.assertIn("Windows device name", reason)

    def test_symlinks_are_dangerous_even_when_target_name_is_clean(self) -> None:
        reason = self.assert_classification(
            "documents/readme.txt", guard.DANGER, media_torrent=False, strict=False, is_symlink=True
        )
        self.assertIn("Symbolic link", reason)

    def test_trailing_dot_or_space_is_dangerous(self) -> None:
        for path in ("report.txt.", "report.txt "):
            with self.subTest(path=path):
                reason = self.assert_classification(path, guard.DANGER, media_torrent=False, strict=False)
                self.assertIn("Trailing dots or spaces", reason)

    def test_control_character_in_filename_is_dangerous(self) -> None:
        reason = self.assert_classification(
            "report" + chr(1) + ".txt", guard.DANGER, media_torrent=False, strict=False
        )
        self.assertIn("Control characters", reason)


class InspectTests(unittest.TestCase):
    @staticmethod
    def item(index: int, path: str, size: int, symlink: bool = False) -> dict[str, object]:
        return {"index": index, "path": path, "size": size, "symlink": symlink}

    def test_clean_torrent_has_empty_findings_and_index_lists(self) -> None:
        # .txt counts as media (books and docs), so a neutral extension keeps this torrent "not media"
        result = guard.inspect([self.item(4, "data.bin", 100)], strict=False)
        self.assertEqual(result, {"level": guard.CLEAN, "media": False, "findings": {}, "danger": [], "runnable": []})

    def test_media_threshold_and_danger_verdict_are_reported(self) -> None:
        files = [self.item(1, "video.mp4", 800), self.item(7, "installer.exe", 200)]
        result = guard.inspect(files, strict=False)
        self.assertTrue(result["media"])
        self.assertEqual(result["level"], guard.DANGER)
        self.assertEqual(result["danger"], [7])
        self.assertEqual(result["runnable"], [])
        self.assertEqual(result["findings"][7]["path"], "installer.exe")
        self.assertEqual(result["findings"][7]["level"], guard.DANGER)

    def test_below_media_threshold_keeps_program_as_caution(self) -> None:
        files = [self.item(0, "video.mp4", 799), self.item(3, "installer.exe", 201)]
        result = guard.inspect(files, strict=False)
        self.assertFalse(result["media"])
        self.assertEqual(result["level"], guard.CAUTION)
        self.assertEqual(result["runnable"], [3])
        self.assertEqual(result["danger"], [])

    def test_large_installer_suppresses_media_torrent_classification(self) -> None:
        mib = 1024 ** 2
        files = [self.item(0, "video.mp4", 540 * mib), self.item(8, "installer.exe", 60 * mib)]
        result = guard.inspect(files, strict=False)
        self.assertFalse(result["media"])
        self.assertEqual(result["level"], guard.CAUTION)
        self.assertEqual(result["runnable"], [8])

    def test_strict_mode_and_symlink_findings_are_dangerous(self) -> None:
        files = [self.item(9, "run.ps1", 1), self.item(2, "readme.txt", 1, symlink=True)]
        result = guard.inspect(files, strict=True)
        self.assertEqual(result["level"], guard.DANGER)
        self.assertEqual(result["danger"], [2, 9])
        self.assertEqual(result["runnable"], [])

    def test_zero_sized_safe_files_do_not_divide_by_zero(self) -> None:
        result = guard.inspect([self.item(5, "notes.txt", 0)], strict=False)
        self.assertFalse(result["media"])
        self.assertEqual(result["level"], guard.CLEAN)


class MarkOfTheWebTests(unittest.TestCase):
    def test_mark_and_detect_mark_on_file_in_test_folder(self) -> None:
        test_folder = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=test_folder) as temporary_folder:
            target = Path(temporary_folder) / "download.txt"
            target.write_bytes(b"safe test fixture")
            self.assertFalse(guard.has_mark_of_the_web(target))
            self.assertTrue(guard.mark_of_the_web(target))
            self.assertTrue(guard.has_mark_of_the_web(target))


if __name__ == "__main__":
    unittest.main()
