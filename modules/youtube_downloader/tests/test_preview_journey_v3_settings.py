"""The YouTube preview keeps the old page after journey v3 (J-SET; the settings table's one fact): it still reads `theme`,
`source_display` and `logic.context.max_contexts`, whose choices the journey's page changes.

What a wrong answer would cost: after a press on the new page (Night, Light, Icon + name, Only on hover, All) the
preview painting a look or a badge the learner never chose, or no sentences; or a learner whose settings.json still
says Zen Mode, Midnight, Hidden or File name seeing a different preview than before the update.

Real data: the preview's own page (`generate_preview_html` writing templates/web_app.html) and a real Japanese
transcript through the real tokenizer (`analyze_transcript`).
"""
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from app.services import journey_settings
from modules.youtube_downloader import preview as pv

WORDS = [{"Word": "公園", "Reading": "コウエン", "Score": 30, "Context 1": "公園で猫を見ました。", "Src 1": ""},
         {"Word": "勉強", "Reading": "ベンキョウ", "Score": 20, "Context 1": "今日は新しい言葉を勉強します。", "Src 1": ""}]


def _painted(settings):
    """(the look, the badge) the preview's page is written with for `settings`."""
    out = os.path.join(tempfile.mkdtemp(), "preview.html")
    with patch.object(pv.settings_manager, "load_settings", return_value=settings):
        pv.generate_preview_html([("vid [abc].txt", [dict(w) for w in WORDS])], "ja", out)
    with open(out, encoding="utf-8") as f:
        html = f.read()
    return (re.search(r"let globalTheme = '([^']*)'", html).group(1),
            re.search(r"let globalSourceDisplay = '([^']*)'", html).group(1))


class TestWhatThePreviewPaints(unittest.TestCase):
    def test_every_look_a_learner_may_have_saved_paints_as_before(self):
        """The five old looks, untouched: the preview reads the stored key as it always did."""
        for saved, look in (("Default (Dark)", "default"), ("Dark Flow", "world-class"),
                            ("Midnight (Vibrant)", "midnight-vibrant"), ("Modern Light", "modern-light"),
                            ("Zen Mode", "zen-focus")):
            self.assertEqual(_painted({"theme": saved})[0], look, saved)

    def test_night_and_light_pressed_on_the_page_paint_dark_flow_and_modern_light(self):
        for page, look in (("night", "world-class"), ("light", "modern-light")):
            self.assertEqual(_painted({"theme": journey_settings.stored("theme", page)})[0], look, page)

    def test_every_badge_a_learner_may_have_saved_paints_as_before(self):
        for saved in ("off", "icon", "filename", "full"):
            self.assertEqual(_painted({"source_display": saved})[1], saved)

    def test_where_each_line_is_from_pressed_on_the_page_paints_its_nearest_old_badge(self):
        """Icon is Icon, Icon + name the old Icon + file name, Only on hover hidden (the old page has no hover)."""
        for page, badge in (("icon", "icon"), ("icon_name", "full"), ("hover", "off")):
            self.assertEqual(_painted({"source_display": journey_settings.stored("source_display", page)})[1],
                             badge, page)


JA_TRANSCRIPT = "今日は公園に行きました。公園で猫を見ました。公園はとても広いです。明日も公園に行きます。"


class TestAllSentencesInThePreview(unittest.TestCase):
    def _sentences(self, max_contexts):
        path = os.path.join(tempfile.mkdtemp(), "vid [abc].txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(JA_TRANSCRIPT)
        settings = {"target_language": "ja", "exclude_single": True, "theme": "Dark Flow",
                    "logic": {"context": {"min_chars": 5, "preferred_max_chars": 50, "max_contexts": max_contexts}}}
        lib = ({}, {"min_freq": 0, "weights": {"high": 10, "low": 5, "goal": 2}})
        with patch.object(pv, "load_library_index", return_value=lib), \
             patch.object(pv, "load_library_contexts", return_value=({}, {"公園": ["大きな公園で子供たちが遊んでいます。"]})), \
             patch.object(pv.settings_manager, "load_settings", return_value=settings), \
             patch.object(pv.az, "load_known_words", return_value=(set(), set())), \
             patch.object(pv.az, "load_simple_list", return_value=set()), \
             patch.object(pv.az, "load_ignored_entries", return_value=set()):
            words, _ = pv.analyze_transcript(path, "ja")
        word = next(w for w in words if w["Word"] == "公園")
        return [word[k] for k in word if k.startswith("Context ") and word[k]]

    def test_all_shows_every_sentence_the_video_and_the_library_have(self):
        """0 is All, never "no sentences" (it gave one before): the video's four lines, then the library's."""
        every = self._sentences(0)
        self.assertEqual(len(every), 5)
        self.assertEqual(every[-1], "大きな公園で子供たちが遊んでいます。")
        self.assertEqual(self._sentences(2), every[:2])
        self.assertEqual(len(self._sentences(3)), 3)


if __name__ == "__main__":
    unittest.main()
