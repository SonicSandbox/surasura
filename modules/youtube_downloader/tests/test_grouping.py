# SPDX-License-Identifier: GPL-3.0-or-later
"""
Exhaustive coverage of plan_buckets — the channel / playlist grouping rules that decide where each download lands.

Rules (3.0.12, Kura-PR2: a channel is a folder, so the library titles a channel's videos as one show; the lead's
lean, PROVISIONAL):
  - a YouTube video, alone or with others -> "YouTube/<Channel>/" beside Processed
  - a YouTube playlist                    -> "YouTube/<Channel>/<PlaylistTitle>/"
  - bilibili.tv (no uploader named)       -> Processed, as before (test_bilibili_tv.py)
What a wrong answer would cost: a single video loose again (the library would read its channel from its record only),
two channels in one folder (one title), a folder Windows can't make (a channel named `CON`), or a download outside
the language folder.
"""
import os
import unittest

from modules.youtube_downloader import downloader as core

ROOT = os.path.abspath(os.path.join("lang"))
OUT = os.path.join(ROOT, "Processed")
YT = os.path.join(ROOT, "YouTube")


def video(vid, channel):
    return (f"u_{vid}", {"id": vid, "channel": channel})


def playlist(title, channel, via_type=True):
    info = {"title": title, "channel": channel}
    if via_type:
        info["_type"] = "playlist"
    info["entries"] = [1, 2, 3]
    return (f"u_pl_{title}", info)


def folders(buckets):
    """Map each target, relative to the YouTube folder ('/'-joined; Processed itself is '<processed>') -> set(urls)."""
    out = {}
    for urls, target in buckets:
        key = "<processed>" if target == OUT else os.path.relpath(target, YT).replace(os.sep, "/")
        out.setdefault(key, set()).update(urls)
    return out


class TestPlaylistGrouping(unittest.TestCase):
    def test_playlist_folder_inside_its_channels(self):
        buckets = core.plan_buckets([playlist("ジャンプ", "WSJ")], OUT)
        self.assertEqual(len(buckets), 1)
        urls, target = buckets[0]
        self.assertEqual(urls, ["u_pl_ジャンプ"])
        self.assertEqual(target, os.path.join(YT, "WSJ", "ジャンプ"))

    def test_playlist_detected_via_entries_key_only(self):
        # No _type, but an 'entries' list still marks it a playlist.
        buckets = core.plan_buckets([playlist("PL", "Ch", via_type=False)], OUT)
        self.assertEqual(buckets[0][1], os.path.join(YT, "Ch", "PL"))

    def test_multiple_playlists_each_own_folder(self):
        f = folders(core.plan_buckets([playlist("A", "C1"), playlist("B", "C2"), playlist("C", "C1")], OUT))
        self.assertEqual(set(f), {"C1/A", "C2/B", "C1/C"})

    def test_playlist_folder_name_is_slugged(self):
        target = core.plan_buckets([playlist('Bad/Name:?', 'Ch*')], OUT)[0][1]
        self.assertEqual(os.path.relpath(target, YT).replace(os.sep, "/"), "Ch/BadName")


class TestChannelGrouping(unittest.TestCase):
    def test_a_single_video_goes_into_its_channels_folder(self):
        f = folders(core.plan_buckets([video("a", "Solo")], OUT))
        self.assertEqual(f, {"Solo": {"u_a"}})

    def test_same_channel_grouped(self):
        f = folders(core.plan_buckets([video("a", "NHK"), video("b", "NHK"), video("c", "NHK")], OUT))
        self.assertEqual(f, {"NHK": {"u_a", "u_b", "u_c"}})

    def test_two_channels_two_folders(self):
        f = folders(core.plan_buckets([video("a", "C1"), video("b", "C2"), video("c", "C1")], OUT))
        self.assertEqual(f, {"C1": {"u_a", "u_c"}, "C2": {"u_b"}})

    def test_channel_folder_name_slugged(self):
        f = folders(core.plan_buckets([video("a", "Ch/Bad"), video("b", "Ch/Bad")], OUT))
        self.assertIn("ChBad", f)

    def test_japanese_and_chinese_channel_names_are_kept(self):
        f = folders(core.plan_buckets([video("a", "ゆる言語学ラジオ"), video("b", "李子柒 Liziqi")], OUT))
        self.assertEqual(set(f), {"ゆる言語学ラジオ", "李子柒 Liziqi"})


class TestFolderNames(unittest.TestCase):
    def test_a_name_windows_keeps_for_a_device_gets_an_underscore(self):
        for name, want in (("CON", "CON_"), ("nul", "nul_"), ("COM1", "COM1_"), ("Lpt9.txt", "Lpt9.txt_"),
                           ("Console", "Console"), ("CONTRA", "CONTRA")):
            self.assertEqual(core.folder_name(name), want, name)

    def test_a_name_of_marks_alone_or_trailing_dots_still_makes_a_folder(self):
        self.assertEqual(core.folder_name('<>:"/\\|?*'), "untitled")
        self.assertEqual(core.folder_name("..."), "untitled")
        self.assertEqual(core.folder_name("ねこ. "), "ねこ")

    def test_a_long_channel_name_is_cut(self):
        self.assertEqual(len(core.folder_name("あ" * 300)), 80)


class TestEverythingAtOnce(unittest.TestCase):
    def test_playlist_channel_pair_and_singleton(self):
        probe = [
            playlist("ジャンプ", "WSJ"),
            video("a", "NHK"), video("b", "NHK"),
            video("c", "Solo"),
        ]
        f = folders(core.plan_buckets(probe, OUT))
        self.assertEqual(f, {"WSJ/ジャンプ": {"u_pl_ジャンプ"}, "NHK": {"u_a", "u_b"}, "Solo": {"u_c"}})

    def test_every_youtube_target_is_inside_the_language_folders_youtube_folder(self):
        probe = [playlist("PL", "Ch"), video("a", "Ch"), video("b", "..")]
        for _urls, target in core.plan_buckets(probe, OUT):
            self.assertTrue(os.path.abspath(target).startswith(YT + os.sep), target)


class TestGroupingEdgeCases(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(core.plan_buckets([], OUT), [])

    def test_none_infos_skipped(self):
        self.assertEqual(core.plan_buckets([("u", None), ("u2", None)], OUT), [])

    def test_none_mixed_with_valid(self):
        f = folders(core.plan_buckets([("bad", None), video("a", "Solo")], OUT))
        self.assertEqual(f, {"Solo": {"u_a"}})

    def test_videos_that_name_no_channel_go_loose_into_the_youtube_folder(self):
        # No channel info: never one "Unknown" folder (the library would make one title of them all); loose in
        # YouTube, each titled by its name. The uploader names the folder when the channel doesn't.
        probe = [("u_x", {"id": "x"}), ("u_y", {"id": "y"}), ("u_z", {"id": "z", "uploader": "ねこ"}),
                 ("u_pl_P", {"_type": "playlist", "title": "P", "entries": [1]})]
        f = folders(core.plan_buckets(probe, OUT))
        self.assertEqual(f, {".": {"u_x", "u_y"}, "ねこ": {"u_z"}, "P": {"u_pl_P"}})


if __name__ == "__main__":
    unittest.main()
