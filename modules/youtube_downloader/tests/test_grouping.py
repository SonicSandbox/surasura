# SPDX-License-Identifier: GPL-3.0-or-later
"""
Exhaustive coverage of plan_buckets — the playlist / same-channel / singleton
grouping rules that decide where each download lands.

Rules:
  - playlist                 -> "<Channel> - <PlaylistTitle> (playlist)" subfolder
  - >= 2 links, same channel -> "<Channel>" subfolder
  - single / mixed singles   -> straight into the Processed root
"""
import os
import unittest

from modules.youtube_downloader import downloader as core

OUT = os.path.join("PROCESSED")


def video(vid, channel):
    return (f"u_{vid}", {"id": vid, "channel": channel})


def playlist(title, channel, via_type=True):
    info = {"title": title, "channel": channel}
    if via_type:
        info["_type"] = "playlist"
    info["entries"] = [1, 2, 3]
    return (f"u_pl_{title}", info)


def folders(buckets):
    """Map basename(folder) -> set(urls); root maps under '<root>'."""
    out = {}
    for urls, target in buckets:
        key = "<root>" if target == OUT else os.path.basename(target.rstrip(os.sep))
        out.setdefault(key, set()).update(urls)
    return out


class TestPlaylistGrouping(unittest.TestCase):
    def test_playlist_folder_name_and_membership(self):
        buckets = core.plan_buckets([playlist("ジャンプ", "WSJ")], OUT)
        self.assertEqual(len(buckets), 1)
        urls, target = buckets[0]
        self.assertEqual(urls, ["u_pl_ジャンプ"])
        self.assertEqual(os.path.basename(target), "WSJ - ジャンプ (playlist)")

    def test_playlist_detected_via_entries_key_only(self):
        # No _type, but an 'entries' list still marks it a playlist.
        buckets = core.plan_buckets([playlist("PL", "Ch", via_type=False)], OUT)
        self.assertTrue(buckets[0][1].endswith("(playlist)"))

    def test_multiple_playlists_each_own_folder(self):
        buckets = core.plan_buckets([playlist("A", "C1"), playlist("B", "C2")], OUT)
        names = sorted(os.path.basename(t) for _, t in buckets)
        self.assertEqual(names, ["C1 - A (playlist)", "C2 - B (playlist)"])

    def test_playlist_folder_name_is_slugged(self):
        buckets = core.plan_buckets([playlist('Bad/Name:?', 'Ch*')], OUT)
        # invalid chars stripped from the folder name
        self.assertNotIn("/", os.path.basename(buckets[0][1]))
        self.assertNotIn(":", os.path.basename(buckets[0][1]))


class TestChannelGrouping(unittest.TestCase):
    def test_two_same_channel_grouped(self):
        f = folders(core.plan_buckets([video("a", "NHK"), video("b", "NHK")], OUT))
        self.assertEqual(f.get("NHK"), {"u_a", "u_b"})
        self.assertNotIn("<root>", f)

    def test_three_same_channel_grouped(self):
        f = folders(core.plan_buckets(
            [video("a", "NHK"), video("b", "NHK"), video("c", "NHK")], OUT))
        self.assertEqual(f.get("NHK"), {"u_a", "u_b", "u_c"})

    def test_single_video_goes_to_root(self):
        f = folders(core.plan_buckets([video("a", "Solo")], OUT))
        self.assertEqual(f.get("<root>"), {"u_a"})
        self.assertNotIn("Solo", f)

    def test_two_singletons_different_channels_both_root(self):
        f = folders(core.plan_buckets([video("a", "C1"), video("b", "C2")], OUT))
        self.assertEqual(f.get("<root>"), {"u_a", "u_b"})
        self.assertEqual(set(f.keys()), {"<root>"})

    def test_mixed_pair_plus_singleton(self):
        f = folders(core.plan_buckets(
            [video("a", "NHK"), video("b", "NHK"), video("c", "Solo")], OUT))
        self.assertEqual(f.get("NHK"), {"u_a", "u_b"})
        self.assertEqual(f.get("<root>"), {"u_c"})

    def test_two_channels_each_with_pair(self):
        f = folders(core.plan_buckets(
            [video("a", "NHK"), video("b", "NHK"), video("c", "TBS"), video("d", "TBS")], OUT))
        self.assertEqual(f.get("NHK"), {"u_a", "u_b"})
        self.assertEqual(f.get("TBS"), {"u_c", "u_d"})
        self.assertNotIn("<root>", f)

    def test_channel_folder_name_slugged(self):
        f = folders(core.plan_buckets([video("a", "Ch/Bad"), video("b", "Ch/Bad")], OUT))
        self.assertIn("ChBad", f)


class TestEverythingAtOnce(unittest.TestCase):
    def test_playlist_channel_pair_and_singleton(self):
        probe = [
            playlist("ジャンプ", "WSJ"),
            video("a", "NHK"), video("b", "NHK"),
            video("c", "Solo"),
        ]
        f = folders(core.plan_buckets(probe, OUT))
        self.assertEqual(f.get("WSJ - ジャンプ (playlist)"), {"u_pl_ジャンプ"})
        self.assertEqual(f.get("NHK"), {"u_a", "u_b"})
        self.assertEqual(f.get("<root>"), {"u_c"})


class TestGroupingEdgeCases(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(core.plan_buckets([], OUT), [])

    def test_none_infos_skipped(self):
        self.assertEqual(core.plan_buckets([("u", None), ("u2", None)], OUT), [])

    def test_none_mixed_with_valid(self):
        f = folders(core.plan_buckets([("bad", None), video("a", "Solo")], OUT))
        self.assertEqual(f.get("<root>"), {"u_a"})

    def test_unknown_channel_singletons(self):
        # Two videos with no channel info both resolve to 'Unknown' -> grouped together.
        probe = [("u_x", {"id": "x"}), ("u_y", {"id": "y"})]
        f = folders(core.plan_buckets(probe, OUT))
        self.assertEqual(f.get("Unknown"), {"u_x", "u_y"})


if __name__ == "__main__":
    unittest.main()
