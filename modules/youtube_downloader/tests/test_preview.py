# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tests for the YouTube Preview engine.

Pure helpers (id parsing, threshold, scoring, context selection, manifest entry) are
tested directly. The scorer + report generation get a hermetic end-to-end run with the
REAL tokenizer but mocked library cache / known words / settings (no network, no full run).
"""
import os
import json
import tempfile
import unittest
from unittest.mock import patch

from modules.youtube_downloader import preview as pv


class TestPureHelpers(unittest.TestCase):
    def test_extract_video_id_forms(self):
        self.assertEqual(pv.extract_video_id("https://www.youtube.com/watch?v=iG9CE55wbtY&list=PLx"), "iG9CE55wbtY")
        self.assertEqual(pv.extract_video_id("https://youtu.be/Ks-_Mh1QhMc"), "Ks-_Mh1QhMc")
        self.assertEqual(pv.extract_video_id("https://www.youtube.com/shorts/abcdefghijk"), "abcdefghijk")
        self.assertEqual(pv.extract_video_id("https://www.youtube.com/embed/abcdefghijk"), "abcdefghijk")
        self.assertIsNone(pv.extract_video_id("https://example.com/no-id"))
        self.assertIsNone(pv.extract_video_id(""))

    def test_score_from_counts(self):
        self.assertEqual(pv.score_from_counts(3, 2, 1, {"high": 10, "low": 5, "goal": 2}), 42)
        self.assertEqual(pv.score_from_counts(0, 0, 0, {"high": 10, "low": 5, "goal": 2}), 0)

    def test_passes_threshold_combines_library_and_video(self):
        # The headline case: a word below threshold in the library, pushed over by the video.
        self.assertTrue(pv.passes_threshold(2, 5, 3))     # 2 + 5 >= 3
        self.assertTrue(pv.passes_threshold(3, 0, 3))     # already at threshold
        self.assertFalse(pv.passes_threshold(0, 1, 3))    # 0 + 1 < 3
        self.assertTrue(pv.passes_threshold(0, 1, 0))     # no threshold -> always in

    def test_resolve_min_floor_prefers_new_min_count_field(self):
        # After the min_freq -> density-band migration, runs write 'min_count'; the preview must
        # prefer it, while still reading an older cache's 'min_freq'.
        self.assertEqual(pv.resolve_min_floor({"min_count": 6, "min_freq": 3}), 6)  # new wins
        self.assertEqual(pv.resolve_min_floor({"min_freq": 3}), 3)                   # old fallback
        self.assertEqual(pv.resolve_min_floor({"min_count": 2.5}), 2.5)              # fractional ok
        self.assertEqual(pv.resolve_min_floor({}), 0)                               # neither -> keep all

    def test_pick_contexts_prefers_i_plus_one_then_length_band(self):
        cands = [
            (0, 30, "iplus_in_band"),
            (1, 30, "two_unknowns"),
            (0, 5, "iplus_too_short"),
            (0, 100, "iplus_too_long"),
        ]
        self.assertEqual(pv.pick_contexts(cands, 10, 50, 2), ["iplus_in_band", "iplus_too_short"])

    def test_build_manifest_entry_shape(self):
        e = pv.build_manifest_entry("HighPriority/foo [abc].txt", "foo [abc].txt")
        self.assertEqual(e["physical_path"], "HighPriority/foo [abc].txt")
        self.assertEqual(e["type"], "File")
        self.assertEqual(e["origin_source"], "YouTube Preview")


class TestLibraryIndex(unittest.TestCase):
    def test_missing_cache_returns_none(self):
        with patch.object(pv, "library_index_path", return_value=os.path.join(tempfile.gettempdir(), "nope_xyz.json")):
            words, settings = pv.load_library_index()
            self.assertIsNone(words)
            self.assertFalse(pv.has_library_cache())

    def test_loads_cache(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "library_frequency.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"settings": {"min_freq": 3}, "words": {"猫|ネコ": [10, 8, 2, 0]}}, f)
        with patch.object(pv, "library_index_path", return_value=path):
            words, settings = pv.load_library_index()
            self.assertEqual(words["猫|ネコ"], [10, 8, 2, 0])
            self.assertEqual(settings["min_freq"], 3)
            self.assertTrue(pv.has_library_cache())


class TestVideoGuard(unittest.TestCase):
    def test_video_in_library_by_id(self):
        d = tempfile.mkdtemp()
        hp = os.path.join(d, "HighPriority")
        os.makedirs(hp)
        open(os.path.join(hp, "Some Channel - Some Title [VID12345678].txt"), "w").close()
        with patch.object(pv, "get_data_path", return_value=d):
            self.assertTrue(pv.video_in_library("VID12345678", "ja"))
            self.assertFalse(pv.video_in_library("OTHERID1234", "ja"))
            self.assertFalse(pv.video_in_library("", "ja"))

    def test_a_video_copied_into_the_content_folder_is_in_the_library_as_its_tier_twin_is(self):
        # 3.0's Sources copy every new text into Library/<show>/: the guard finds the id there, as under a tier.
        with tempfile.TemporaryDirectory() as d:
            for top in ("Library", "HighPriority"):
                show = os.path.join(d, top, "ゆる日本語チャンネル")
                os.makedirs(show)
                vid = "LIB12345678" if top == "Library" else "VID12345678"
                open(os.path.join(show, f"ゆる日本語 - 第1回 [{vid}].ja.srt"), "w", encoding="utf-8").close()
            with patch.object(pv, "get_data_path", return_value=d):
                self.assertTrue(pv.video_in_library("LIB12345678", "ja"))
                self.assertTrue(pv.video_in_library("VID12345678", "ja"))
                self.assertFalse(pv.video_in_library("OTHERID1234", "ja"))

    def test_with_no_content_folder_the_guard_answers_as_before(self):
        # A 2.x-shaped library (every tier folder, no Library): found where it was found, nowhere else.
        with tempfile.TemporaryDirectory() as d:
            for top in ("HighPriority", "LowPriority", "GoalContent", "Processed", "Graduated"):
                os.makedirs(os.path.join(d, top))
            open(os.path.join(d, "Graduated", "旅 - 第2回 [GRD12345678].txt"), "w", encoding="utf-8").close()
            os.makedirs(os.path.join(d, "Elsewhere"))                       # a folder no reader lists stays unread
            open(os.path.join(d, "Elsewhere", "旅 - 第3回 [ELS12345678].txt"), "w", encoding="utf-8").close()
            with patch.object(pv, "get_data_path", return_value=d):
                self.assertTrue(pv.video_in_library("GRD12345678", "ja"))
                self.assertFalse(pv.video_in_library("ELS12345678", "ja"))
                self.assertFalse(pv.video_in_library("LIB12345678", "ja"))


# Real Japanese transcript text (no network) for the end-to-end scorer test.
JA_TRANSCRIPT = (
    "今日は新しい言葉を勉強します。"
    "公園で猫を見ました。猫はとても可愛いです。"
    "明日も公園に行きます。"
)


class TestScorerEndToEnd(unittest.TestCase):
    """Real tokenizer; mocked library cache / known words / settings (hermetic)."""

    def _settings(self):
        return {
            "target_language": "ja", "exclude_single": True,
            "words_per_day": 5, "show_words_per_day": True, "theme": "Dark Flow",
            "reinforce_segmentation": False,
            "logic": {"context": {"min_chars": 5, "preferred_max_chars": 50, "max_contexts": 3}},
        }

    def test_analyze_transcript_produces_wellformed_rows(self):
        path = os.path.join(tempfile.mkdtemp(), "vid [abc].txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(JA_TRANSCRIPT)

        # min_freq 0 -> every unknown word is included regardless of the (empty) cache.
        lib = ({}, {"min_freq": 0, "weights": {"high": 10, "low": 5, "goal": 2}})
        with patch.object(pv, "load_library_index", return_value=lib), \
             patch.object(pv, "load_library_contexts", return_value=({}, {})), \
             patch.object(pv.settings_manager, "load_settings", return_value=self._settings()), \
             patch.object(pv.az, "load_known_words", return_value=(set(), set())), \
             patch.object(pv.az, "load_simple_list", return_value=set()), \
             patch.object(pv.az, "load_ignored_entries", return_value=set()):
            words, stats = pv.analyze_transcript(path, "ja")

        self.assertGreater(len(words), 0, "should surface unknown vocab from the transcript")
        self.assertGreater(stats["total"], 0)
        for w in words:
            for key in ("Word", "Reading", "Score", "Occurrences (Global)",
                        "Baseline %", "Current %", "New %", "Known Count", "Total Count"):
                self.assertIn(key, w)
            self.assertIn("Context 1", w)  # every surfaced word has at least one context
        # Sorted by Score descending (library leverage)
        scores = [w["Score"] for w in words]
        self.assertEqual(scores, sorted(scores, reverse=True))
        # Coverage progression is monotonic non-decreasing
        news = [w["New %"] for w in words]
        self.assertEqual(news, sorted(news))

    def _scored(self, text, settings=None):
        path = os.path.join(tempfile.mkdtemp(), "vid [abc].txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        lib = ({}, {"min_freq": 0, "weights": {"high": 10, "low": 5, "goal": 2}})
        with patch.object(pv, "load_library_index", return_value=lib), \
             patch.object(pv, "load_library_contexts", return_value=({}, {})), \
             patch.object(pv.settings_manager, "load_settings", return_value=settings or self._settings()), \
             patch.object(pv.az, "load_known_words", return_value=(set(), {"門", "開ける", "見える"})), \
             patch.object(pv.az, "load_simple_list", return_value=set()), \
             patch.object(pv.az, "load_ignored_entries", return_value=set()):
            return pv.analyze_transcript(path, "ja")

    def test_a_one_character_word_counts_only_where_the_list_can_offer_it(self):
        """The list's rule (analyzer.unoffered): 顔, a one-kanji dictionary word, is a candidate where it stands on its
        own; 昴 (スバル, a name the list never offers), the particles and 年 in 三年 (a count) are not, and count as
        nothing to learn in the video's coverage. With the rule off, every one-character word is a candidate."""
        text = "スバルが門を開けた。スバルの顔が見えた。三年前の顔だ。"
        words, stats = self._scored(text)
        found = {w["Word"] for w in words}
        self.assertIn("顔", found)
        self.assertFalse(found & {"昴", "が", "を", "た", "の", "年"})
        self.assertEqual(stats["learnable"], 1)
        self.assertEqual(words[0]["Baseline %"], round((stats["total"] - 2) / stats["total"] * 100, 2))
        off = dict(self._settings(), exclude_single=False)
        words, _stats = self._scored(text, off)
        self.assertTrue({"昴", "が", "年"} <= {w["Word"] for w in words})

    def test_the_preview_ranks_by_the_lists_own_score_halved_for_a_word_read_through_its_known_word(self):
        # U9 (Patterns_Quality_Spec §6.8): knowing 利用, the list halves 利用者's score, and the library map
        # carries that score (index 5). Recomputed from the counts it would be 30 again and tie 公園 — the
        # preview's "normal priority order" must be the list's own.
        path = os.path.join(tempfile.mkdtemp(), "vid [abc].txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("公園の利用者が増えた。公園の利用者が多い。")
        lib = ({"公園|コウエン": [3, 3, 0, 0, 1, 30, "公園"], "利用者|リヨウシャ": [3, 3, 0, 0, 1, 15, "利用者"]},
               {"min_freq": 0, "weights": {"high": 10, "low": 5, "goal": 2}})
        known = ({("の", "ノ"), ("が", "ガ"), ("増える", "フエル"), ("た", "タ"), ("多い", "オオイ")},
                 {"の", "が", "増える", "た", "多い", "利用"})
        with patch.object(pv, "load_library_index", return_value=lib), \
             patch.object(pv, "load_library_contexts", return_value=({}, {})), \
             patch.object(pv.settings_manager, "load_settings", return_value=self._settings()), \
             patch.object(pv.az, "load_known_words", return_value=known), \
             patch.object(pv.az, "load_simple_list", return_value=set()), \
             patch.object(pv.az, "load_ignored_entries", return_value=set()):
            words, _stats = pv.analyze_transcript(path, "ja")

        scores = {w["Word"]: w["Score"] for w in words}
        self.assertEqual((scores["公園"], scores["利用者"]), (30, 15))
        self.assertLess([w["Word"] for w in words].index("公園"), [w["Word"] for w in words].index("利用者"))

    def test_with_ignore_names_on_the_videos_own_names_are_no_unknowns(self):
        """Settings' Ignore names: the library's names reach the preview through its ignore set
        (load_ignored_entries), and a new video's own names — read as the token store will read the video once it
        is in the library — are ignored too. Off, a name is a word like any other."""
        path = os.path.join(tempfile.mkdtemp(), "vid [abc].txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("須藤は公園に行きました。須藤は猫を見ました。")
        lib = ({}, {"min_freq": 0, "weights": {"high": 10, "low": 5, "goal": 2}})
        seen = {}
        for on in (False, True):
            settings = self._settings()
            settings["logic"] = dict(settings["logic"], ignore_names=on)
            with patch.object(pv, "load_library_index", return_value=lib), \
                 patch.object(pv, "load_library_contexts", return_value=({}, {})), \
                 patch.object(pv.settings_manager, "load_settings", return_value=settings), \
                 patch.object(pv.az, "load_known_words", return_value=(set(), set())), \
                 patch.object(pv.az, "load_simple_list", return_value=set()), \
                 patch.object(pv.az, "load_ignored_entries", return_value=set()):
                words, _stats = pv.analyze_transcript(path, "ja")
            seen[on] = {w["Word"] for w in words}
        self.assertIn("スドウ", seen[False], "off: a name counts like any word")
        self.assertNotIn("スドウ", seen[True], "on: the video's own name is ignored")
        self.assertIn("公園", seen[True])

    def test_threshold_excludes_video_only_words_when_minfreq_set(self):
        path = os.path.join(tempfile.mkdtemp(), "vid [abc].txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(JA_TRANSCRIPT)
        # Empty cache + min_freq 99 -> nothing reaches the threshold -> empty result.
        lib = ({}, {"min_freq": 99, "weights": {"high": 10, "low": 5, "goal": 2}})
        with patch.object(pv, "load_library_index", return_value=lib), \
             patch.object(pv, "load_library_contexts", return_value=({}, {})), \
             patch.object(pv.settings_manager, "load_settings", return_value=self._settings()), \
             patch.object(pv.az, "load_known_words", return_value=(set(), set())), \
             patch.object(pv.az, "load_simple_list", return_value=set()), \
             patch.object(pv.az, "load_ignored_entries", return_value=set()):
            words, stats = pv.analyze_transcript(path, "ja")
        self.assertEqual(words, [])

    def test_library_contexts_fill_additional_sentences(self):
        """A library example sentence must be merged in as an additional context for a word
        that's in the library (so a high-leverage word the video uses once still gets extras)."""
        path = os.path.join(tempfile.mkdtemp(), "vid [abc].txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(JA_TRANSCRIPT)  # contains 公園 (park), which appears twice
        lib = ({}, {"min_freq": 0, "weights": {"high": 10, "low": 5, "goal": 2}})
        library_sentence = "大きな公園で子供たちが遊んでいます。"
        with patch.object(pv, "load_library_index", return_value=lib), \
             patch.object(pv, "load_library_contexts", return_value=({}, {"公園": [library_sentence]})), \
             patch.object(pv.settings_manager, "load_settings", return_value=self._settings()), \
             patch.object(pv.az, "load_known_words", return_value=(set(), set())), \
             patch.object(pv.az, "load_simple_list", return_value=set()), \
             patch.object(pv.az, "load_ignored_entries", return_value=set()):
            words, _ = pv.analyze_transcript(path, "ja")
        target = next((w for w in words if w["Word"] == "公園"), None)
        self.assertIsNotNone(target, "公園 should be surfaced from the transcript")
        ctxs = [target[k] for k in target if k.startswith("Context ")]
        self.assertIn(library_sentence, ctxs, "library sentence should appear as an extra context")
        # The video's own sentence still comes first
        self.assertIn("公園", ctxs[0])

    def test_a_storys_own_kanji_term_is_one_word_in_the_preview(self):
        # A term the library keeps using as one (app/names.py — 焔魄陣, a made-up technique the tagger cuts 焔 + 魄 +
        # 陣) is one word in the library's tables, so the video's copy of it is that word too: one row, its library
        # uses and the video's together, never three single kanji.
        from app import names
        path = os.path.join(tempfile.mkdtemp(), "vid [abc].txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("焔魄陣を放った。焔魄陣が光る。")
        lib = ({"焔魄陣|": [5, 5, 0, 0, 1, 50, "焔魄陣"]}, {"min_freq": 0, "weights": {"high": 10, "low": 5, "goal": 2}})
        names.use_library_tables({"k": {}, "j": {}, "w": {"焔魄陣": [1.0, "焔魄陣", "", "焔魄陣"]}, "stamp": "term"},
                                 pin=True)
        try:
            with patch.object(pv, "load_library_index", return_value=lib), \
                 patch.object(pv, "load_library_contexts", return_value=({}, {})), \
                 patch.object(pv.settings_manager, "load_settings", return_value=self._settings()), \
                 patch.object(pv.az, "load_known_words", return_value=(set(), set())), \
                 patch.object(pv.az, "load_simple_list", return_value=set()), \
                 patch.object(pv.az, "load_ignored_entries", return_value=set()):
                words, _stats = pv.analyze_transcript(path, "ja")
        finally:
            names.forget_library_tables()
        term = next(w for w in words if w["Word"] == "焔魄陣")
        self.assertEqual((term["Reading"], term["Occurrences (Global)"]), ("", 7))

    def test_no_cache_raises(self):
        with patch.object(pv, "load_library_index", return_value=(None, {})):
            with self.assertRaises(pv.PreviewError):
                pv.analyze_transcript("whatever.txt", "ja")


class TestReportGeneration(unittest.TestCase):
    def test_generate_preview_html_injects_data(self):
        words = [{"Word": "猫", "Reading": "ネコ", "Score": 42, "Occurrences (Global)": 11,
                  "Baseline %": 50.0, "Current %": 50.0, "New %": 60.0,
                  "Known Count": 5, "Total Count": 10, "Context 1": "猫を見ました"}]
        out = os.path.join(tempfile.mkdtemp(), "preview.html")
        with patch.object(pv.settings_manager, "load_settings",
                          return_value={"theme": "Dark Flow", "logic": {}, "words_per_day": 5,
                                        "show_words_per_day": True}):
            pv.generate_preview_html([("My Video", words)], "ja", out)
        html = open(out, encoding="utf-8").read()
        self.assertNotIn("let globalData = null;", html)
        self.assertIn("let globalData =", html)
        self.assertIn("globalLanguage = 'ja'", html)
        self.assertIn("猫", html)
        self.assertIn("My Video", html)


class TestCommitToFront(unittest.TestCase):
    def test_commit_copies_and_prepends_manifest(self):
        root = tempfile.mkdtemp()
        data_root = os.path.join(root, "data", "ja")
        uf_root = os.path.join(root, "User Files", "ja")
        os.makedirs(data_root); os.makedirs(uf_root)
        # a transcript to commit
        src = os.path.join(tempfile.mkdtemp(), "Chan - Title [VID].txt")
        open(src, "w", encoding="utf-8").write("body")
        # existing manifest with one NOW item
        manifest_path = os.path.join(uf_root, "master_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"schedule": {"PHASE_1_NOW": [{"physical_path": "HighPriority/old.txt"}]}}, f)

        with patch.object(pv, "get_data_path", return_value=data_root), \
             patch.object(pv, "get_user_files_path", return_value=uf_root):
            added = pv.commit_to_front([src], "ja")

        self.assertEqual(added, ["Chan - Title [VID].txt"])
        # file copied into HighPriority
        self.assertTrue(os.path.isfile(os.path.join(data_root, "HighPriority", "Chan - Title [VID].txt")))
        # prepended to PHASE_1_NOW (front), old entry preserved after it
        manifest = json.load(open(manifest_path, encoding="utf-8"))
        now = manifest["schedule"]["PHASE_1_NOW"]
        self.assertEqual(now[0]["physical_path"], "HighPriority/Chan - Title [VID].txt")
        self.assertEqual(now[1]["physical_path"], "HighPriority/old.txt")

    def test_an_unreadable_order_is_left_alone_and_nothing_is_added(self):
        """The manifest is the single source of truth for the library order. One that can't be read
        (here: saved with a BOM by Notepad; equally a lock or a half-written file) used to be
        treated as empty — and the preview's entries were written OVER the whole order."""
        root = tempfile.mkdtemp()
        data_root = os.path.join(root, "data", "ja")
        uf_root = os.path.join(root, "User Files", "ja")
        os.makedirs(data_root); os.makedirs(uf_root)
        src = os.path.join(tempfile.mkdtemp(), "Chan - Title [VID].txt")
        open(src, "w", encoding="utf-8").write("body")
        manifest_path = os.path.join(uf_root, "master_manifest.json")
        with open(manifest_path, "w", encoding="utf-8-sig") as f:
            json.dump({"schedule": {"PHASE_1_NOW": [{"physical_path": "HighPriority/old.txt"}]}}, f)
        before = open(manifest_path, "rb").read()

        with patch.object(pv, "get_data_path", return_value=data_root), \
             patch.object(pv, "get_user_files_path", return_value=uf_root):
            with self.assertRaises(pv.PreviewError):
                pv.commit_to_front([src], "ja")

        self.assertEqual(open(manifest_path, "rb").read(), before, "the order must be untouched")
        self.assertFalse(os.path.exists(os.path.join(data_root, "HighPriority", "Chan - Title [VID].txt")))


if __name__ == "__main__":
    unittest.main()
