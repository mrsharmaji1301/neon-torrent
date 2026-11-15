from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from neontorrent import theme  # noqa: E402  (src goes on sys.path first)


class ThemeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_theme = theme.theme_name()

    def tearDown(self) -> None:
        theme.set_theme(self.original_theme)

    def test_every_palette_has_the_same_keys(self) -> None:
        palettes = list(theme.THEMES.values())
        self.assertTrue(palettes, "at least one palette should be defined")
        expected_keys = set(palettes[0])
        for name, palette in theme.THEMES.items():
            with self.subTest(theme=name):
                self.assertEqual(set(palette), expected_keys)

    def test_unknown_theme_falls_back_to_valid_cyberpunk_theme(self) -> None:
        self.assertIn("Cyberpunk", theme.THEMES)
        self.assertEqual(theme.set_theme("not-a-real-theme"), "Cyberpunk")
        self.assertEqual(theme.theme_name(), "Cyberpunk")
        self.assertEqual(set(theme.THEMES[theme.theme_name()]), set(next(iter(theme.THEMES.values()))))

    def test_state_color_is_valid_for_every_known_state(self) -> None:
        self.assertTrue(theme.STATE_COLORS, "at least one state should be defined")
        for state in theme.STATE_COLORS:
            with self.subTest(state=state):
                color = theme.state_color(state)
                self.assertTrue(color.isValid(), f"invalid colour for state {state!r}")


if __name__ == "__main__":
    unittest.main()
