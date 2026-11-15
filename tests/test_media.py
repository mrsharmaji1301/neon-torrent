"""Video pages (yt-dlp): qualities offered, formats, commands. No network: yt-dlp's JSON is built here."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from neontorrent import media  # noqa: E402


def fmt(fid, height=None, vcodec="none", acodec="none", ext="mp4", size=1000, proto="https", **extra):
    return {"format_id": fid, "height": height, "vcodec": vcodec, "acodec": acodec, "ext": ext, "filesize": size,
            "protocol": proto, **extra}


VIDEO = {"title": "Big Buck Bunny", "duration": 635, "uploader": "Blender", "extractor_key": "Youtube",
         "webpage_url": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
         "formats": [fmt("140", acodec="mp4a.40.2", ext="m4a", size=10, abr=128, audio_channels=2),
                     fmt("773", acodec="iamf", ext="m4a", size=20, abr=400, audio_channels=6),
                     fmt("251", acodec="opus", ext="webm", size=9, abr=130),
                     fmt("136", 720, "avc1.4d401f", size=80), fmt("247", 720, "vp9", ext="webm", size=50),
                     fmt("232", 720, "avc1.4d401f", size=None, proto="m3u8_native"),
                     fmt("135", 480, "avc1.4d401e", size=30), fmt("18", 360, "avc1.42001E", "mp4a.40.2", size=25)]}


class MediaTest(unittest.TestCase):
    def test_only_the_resolutions_the_video_has(self):
        info = media.info_from_json("https://youtu.be/aqz-KE-bpKQ", VIDEO)
        labels = [c.label for c in info.choices]
        self.assertEqual(labels, ["720p · HD", "480p", "360p", "Audio"])     # no 1080p, 2K or 4K: the video has none
        self.assertEqual(info.site, "YouTube")

    def test_exact_streams_and_size(self):
        info = media.info_from_json("u", VIDEO)
        hd = info.choices[0]
        self.assertTrue(hd.selector.startswith("136+140/"))                 # https H.264 + stereo AAC, not IAMF
        self.assertEqual(hd.size, 90)
        self.assertTrue(info.choices[2].selector.startswith("18/"))         # 360p already has its audio

    def test_formats_plan(self):
        info = media.info_from_json("u", VIDEO)
        sel, merge = media.plan(info, None, media.FORMAT["mp3"])
        self.assertTrue(sel.startswith("140/"))                             # never yt-dlp's "best" audio (403s)
        sel, merge = media.plan(info, info.choices[0], media.FORMAT["webm"])
        self.assertTrue(sel.startswith("bv*[height=720][ext=webm]+ba[ext=webm]"))
        self.assertEqual(merge, "webm/mkv")
        self.assertEqual(media.plan(info, info.choices[0], media.FORMAT["mkv"])[1], "mkv")
        self.assertEqual(len(media.FORMATS), len(media.FORMAT))

    def test_convert_commands(self):
        tools, src, dst = Path("T"), Path("video.mp4"), Path("converted.mp3")
        mp3 = media.convert_command(tools, src, dst, media.FORMAT["mp3"], 192, copy=False)
        self.assertIn("-vn", mp3)
        self.assertEqual(mp3[mp3.index("-b:a") + 1], "192k")
        self.assertEqual(mp3[-1], str(dst))
        best = media.convert_command(tools, src, dst, media.FORMAT["mp3"], 0, copy=False)
        self.assertIn("-q:a", best)
        mov = media.convert_command(tools, src, Path("c.mov"), media.FORMAT["mov"], 0, copy=True)
        self.assertEqual(mov[mov.index("-c") + 1], "copy")

    def test_link_is_never_an_option(self):
        cmd = media.download_command(Path("T"), Path("C"), "https://youtu.be/x", "18", Path("W"))
        self.assertEqual(cmd[-2:], ["--", "https://youtu.be/x"])
        for flag in ("--ignore-config", "--no-plugin-dirs", "--no-remote-components", "--no-js-runtimes"):
            self.assertIn(flag, cmd)
        with self.assertRaises(Exception):
            media.download_command(Path("T"), Path("C"), "file:///C:/Windows/win.ini", "18", Path("W"))

    def test_progress_and_sites(self):
        self.assertEqual(media.parse_progress("NEONPROG 136 1048576 8388608 NA"), ("136", 1048576, 8388608))
        self.assertEqual(media.parse_progress("NEONPROG 140 10 NA 500"), ("140", 10, 500))
        self.assertIsNone(media.parse_progress("[download] Destination: video.f136.mp4"))
        self.assertTrue(media.is_video_site("https://www.youtube.com/watch?v=x"))
        self.assertTrue(media.is_video_site("https://youtu.be/x"))
        self.assertFalse(media.is_video_site("https://notyoutube.com/x"))
        self.assertFalse(media.is_video_site("https://example.com/video.mp4"))
        self.assertEqual(media.error_line("WARNING: x\nERROR: [youtube] abc: Video unavailable"), "Video unavailable")


if __name__ == "__main__":
    unittest.main()
