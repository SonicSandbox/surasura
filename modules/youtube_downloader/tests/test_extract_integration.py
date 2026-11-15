# SPDX-License-Identifier: GPL-3.0-or-later
"""
End-to-end pipeline tests with yt-dlp fully mocked (no network).

We patch downloader._run_ytdlp so the *real* probe -> plan_buckets -> download ->
clean -> write path runs, but the "yt-dlp" calls instead return canned JSON and
drop canned .info.json + .vtt files. This verifies files are cleaned, named, and
land in the correct grouped folders — the same behaviour proven live, but hermetic.
"""
import os
import json
import types
import tempfile
import unittest
from unittest.mock import patch

from modules.youtube_downloader import downloader as core

VTT_EN = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello there\n\n"
          "00:00:03.000 --> 00:00:05.000\nHello there\n\n"
          "00:00:05.000 --> 00:00:07.000\nwelcome back\n")


def _info(vid, title, channel, subs=None, autos=None, lang=None):
    info = {"id": vid, "title": title, "channel": channel,
            "webpage_url": f"http://{vid}", "upload_date": "20260101", "duration": 60,
            "subtitles": subs if subs is not None else {"en": [{"ext": "vtt"}]},
            "automatic_captions": autos or {}}
    if lang:
        info["language"] = lang
    return info


def make_fake_run(probe_map, info_map, vtt_text=VTT_EN):
    """Return a stand-in for downloader._run_ytdlp covering probe + download calls."""
    def fake(args, timeout=None, **_kw):
        r = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if '-J' in args:                      # probe (flat playlist)
            url = args[-1]
            r.stdout = json.dumps(probe_map.get(url, {}))
            return r
        if '--write-subs' in args:            # download
            tmpdir = os.path.dirname(args[args.index('-o') + 1])
            for u in [a for a in args if a.startswith('http')]:
                info = info_map[u]
                vid = info["id"]
                with open(os.path.join(tmpdir, f"{vid}.info.json"), "w", encoding="utf-8") as f:
                    json.dump(info, f)
                code, _ = core.resolve_caption(info, core.LANGS["English"])
                if code:
                    with open(os.path.join(tmpdir, f"{vid}.{code}.vtt"), "w", encoding="utf-8") as f:
                        f.write(vtt_text)
            return r
        return r
    return fake


class TestDownloadBucket(unittest.TestCase):
    def test_writes_clean_txt_with_channel_prefix(self):
        out = tempfile.mkdtemp(prefix="ytt_")
        info_map = {"http://A": _info("A", "First Talk", "NHK")}
        fake = make_fake_run({}, info_map)
        summary = {"written": 0, "no_transcript": 0, "errors": 0}
        with patch.object(core, "_run_ytdlp", fake):
            core._download_bucket(["http://A"], out, core.LANGS["English"], "English",
                                  keep_ts=False, channel_first=True, log=lambda *_: None,
                                  summary=summary)
        self.assertEqual(summary["written"], 1)
        expected = os.path.join(out, "NHK - First Talk [A].txt")
        self.assertTrue(os.path.isfile(expected), f"missing {expected}")
        content = open(expected, encoding="utf-8").read()
        self.assertIn("Captions: English (manual)", content)
        self.assertIn("Hello there welcome back", content)   # deduped + space-joined

    def test_a_long_name_keeps_its_id_and_never_collides(self):
        """slug() caps a name at 150 characters by cutting its END — which is where the [id] lives,
        and "Channel name first" is on by default. The id is how the app knows the file (duplicate
        check, cue backfill, source badge), and two long titles differing only at the end would get
        one name: the second overwrote the first while both logged [ok]."""
        out = tempfile.mkdtemp(prefix="ytt_")
        channel = "ゆっくり日本語チャンネル・毎日の会話と文化をわかりやすく解説"
        base = "【初心者向け】毎日使える日本語の表現を丁寧に解説します" * 5   # ~185 chars with the channel
        info_map = {"http://A1": _info("AAAAAAAAAA1", base + "その一", channel),
                    "http://A2": _info("AAAAAAAAAA2", base + "その二", channel)}
        summary = {"written": 0, "no_transcript": 0, "errors": 0}
        with patch.object(core, "_run_ytdlp", make_fake_run({}, info_map)):
            core._download_bucket(["http://A1", "http://A2"], out, core.LANGS["English"], "English",
                                  keep_ts=False, channel_first=True, log=lambda *_: None,
                                  summary=summary)
        names = sorted(os.listdir(out))
        txts = [n for n in names if n.endswith(".txt")]
        self.assertEqual(len(txts), 2, names)
        self.assertTrue(txts[0].endswith("[AAAAAAAAAA1].txt") and txts[1].endswith("[AAAAAAAAAA2].txt"))
        self.assertTrue(all(len(n) <= 150 + len(".txt") for n in txts))
        self.assertTrue(txts[0].startswith(channel), "the channel still comes first")

    def test_no_captions_counts_as_no_transcript(self):
        out = tempfile.mkdtemp(prefix="ytt_")
        info_map = {"http://X": _info("X", "No Caps", "Ch", subs={}, autos={"ko": [{"ext": "vtt"}]})}
        summary = {"written": 0, "no_transcript": 0, "errors": 0}
        with patch.object(core, "_run_ytdlp", make_fake_run({}, info_map)):
            core._download_bucket(["http://X"], out, core.LANGS["English"], "English",
                                  keep_ts=False, channel_first=True, log=lambda *_: None,
                                  summary=summary)
        self.assertEqual(summary, {"written": 0, "no_transcript": 1, "errors": 0})
        self.assertEqual([f for f in os.listdir(out) if f.endswith(".txt")], [])

    def test_the_empty_folders_a_bucket_made_go_and_the_ones_there_before_stay(self):
        # (3.0.12, Kura-PR2) a playlist's folder inside its channel's, both made for a bucket that brought nothing:
        # both go (an empty channel folder would be a title of nothing); the YouTube folder that was there stays
        youtube = os.path.join(tempfile.mkdtemp(prefix="ytt_"), "YouTube")
        os.makedirs(youtube)
        target = os.path.join(youtube, "ゆる日本語", "初級の旅")
        info_map = {"http://X": _info("X", "No Caps", "ゆる日本語", subs={}, autos={})}
        summary = {"written": 0, "no_transcript": 0, "errors": 0}
        with patch.object(core, "_run_ytdlp", make_fake_run({}, info_map)):
            core._download_bucket(["http://X"], target, core.LANGS["Japanese"], "Japanese",
                                  keep_ts=False, channel_first=True, log=lambda *_: None, summary=summary)
        self.assertEqual(summary["written"], 0)
        self.assertTrue(os.path.isdir(youtube))
        self.assertEqual(os.listdir(youtube), [])
        os.makedirs(os.path.join(youtube, "ゆる日本語"))           # a channel folder there before: it stays
        with patch.object(core, "_run_ytdlp", make_fake_run({}, info_map)):
            core._download_bucket(["http://X"], target, core.LANGS["Japanese"], "Japanese",
                                  keep_ts=False, channel_first=True, log=lambda *_: None, summary=summary)
        self.assertEqual(os.listdir(youtube), ["ゆる日本語"])
        self.assertEqual(os.listdir(os.path.join(youtube, "ゆる日本語")), [])


class TestExtractEndToEnd(unittest.TestCase):
    def test_grouping_into_channel_folders(self):
        # (3.0.12, Kura-PR2) every YouTube video into its channel's folder under YouTube, beside Processed
        out = os.path.join(tempfile.mkdtemp(prefix="ytt_"), "Processed")
        channels = os.path.join(os.path.dirname(out), "YouTube")
        probe_map = {
            "http://A": {"id": "A", "channel": "NHK"},
            "http://B": {"id": "B", "channel": "NHK"},
            "http://C": {"id": "C", "channel": "Solo"},
        }
        info_map = {
            "http://A": _info("A", "Alpha", "NHK"),
            "http://B": _info("B", "Beta", "NHK"),
            "http://C": _info("C", "Gamma", "Solo"),
        }
        with patch.object(core, "_run_ytdlp", make_fake_run(probe_map, info_map)):
            summary = core.extract(["http://A", "http://B", "http://C"], out,
                                   lang="English", channel_first=True, log=lambda *_: None)

        self.assertEqual(summary["written"], 3)
        self.assertTrue(os.path.isfile(os.path.join(channels, "NHK", "NHK - Alpha [A].txt")))
        self.assertTrue(os.path.isfile(os.path.join(channels, "NHK", "NHK - Beta [B].txt")))
        # a single video too: a channel is a folder (the library titles it by the channel)
        self.assertTrue(os.path.isfile(os.path.join(channels, "Solo", "Solo - Gamma [C].txt")))
        self.assertFalse(os.path.exists(out) and os.listdir(out), "nothing loose in Processed")

    def test_channel_first_off_keeps_plain_name(self):
        out = os.path.join(tempfile.mkdtemp(prefix="ytt_"), "Processed")
        probe_map = {"http://A": {"id": "A", "channel": "Solo"}}
        info_map = {"http://A": _info("A", "Alpha", "Solo")}
        with patch.object(core, "_run_ytdlp", make_fake_run(probe_map, info_map)):
            core.extract(["http://A"], out, lang="English", channel_first=False, log=lambda *_: None)
        self.assertTrue(os.path.isfile(os.path.join(os.path.dirname(out), "YouTube", "Solo", "Alpha [A].txt")))

    def test_empty_urls_noop(self):
        out = tempfile.mkdtemp(prefix="ytt_")
        summary = core.extract([], out, log=lambda *_: None)
        self.assertEqual(summary, {"written": 0, "no_transcript": 0, "errors": 0})


if __name__ == "__main__":
    unittest.main()
