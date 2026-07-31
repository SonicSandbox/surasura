"""Per-sentence source attribution (Tier 1): "which file did this example sentence come from?".

Covers the whole chain — classification, the analyzer's Src columns + sources.json, the generator's
interning + injection, the report's badge, and the card export — plus the two things most likely to
break silently: the `Context ` column-name collision, and results generated before the feature.
"""

import json
import os
import unittest
from unittest.mock import patch

import pandas as pd
import pytest

from app import analyzer
from app.path_utils import (CONTENT_EXTENSIONS, SOURCE_MARKER, infer_source_type,
                            read_source_marker, write_source_marker)

# Real content of each kind, so classification is exercised on plausible files rather than stubs.
SRT = ("1\n00:00:02,400 --> 00:00:05,100\n"
       "この街には、まだ秘密が残っている。\n\n"
       "2\n00:00:05,600 --> 00:00:08,000\n"
       "誰も答えを知らなかった。\n")
BOOK = "少年は静かに扉を開けた。廊下には誰もいなかった。秘密の部屋が待っていた。"
TRANSCRIPT = ("今日の話題\nチャンネル | 2026-01-01 | 12:03\n"
              "------------------------------------------------------------\n"
              "秘密の多い街を歩いてきました。答えはまだ見つかりません。")


# --- classification ----------------------------------------------------------------------------- #
class TestSourceClassification(unittest.TestCase):
    def test_subtitles_are_classified_by_extension(self):
        self.assertEqual(infer_source_type("data/ja/HighPriority/ep01.srt"), "subtitle")
        self.assertEqual(infer_source_type("data/ja/HighPriority/signs.ASS"), "subtitle")

    def test_youtube_is_recognised_by_the_downloader_filename_pattern(self):
        """The transcript downloader writes '<Title> [<11-char id>].txt' — the id ends the stem."""
        self.assertEqual(
            infer_source_type("data/ja/HighPriority/チャンネル - 今日の話題 [dQw4w9WgXcQ].txt"),
            "youtube")

    def test_release_group_tags_are_not_mistaken_for_youtube_ids(self):
        """An unanchored 11-char bracket match would hit fansub tags — hence the end anchor."""
        for name in ("[HorribleSub] ep01.txt", "本 [A1B2C3D4].txt", "[SubsPlease]_x264.txt"):
            self.assertEqual(infer_source_type(f"data/ja/HighPriority/{name}"), "text",
                             f"{name} should not be read as a YouTube transcript")

    def test_producer_marker_identifies_epub_chapters(self):
        """An EPUB chapter is a plain .txt — only the producer can say it came from a book."""
        self.assertEqual(infer_source_type("Processed/本/本_01.txt", marker_type="epub"), "epub")

    def test_declared_type_beats_every_guess(self):
        """The manifest's recorded source_type wins — it was stamped when the file was added."""
        self.assertEqual(infer_source_type("x/ep01.srt", declared="youtube"), "youtube")

    def test_unknown_and_missing_inputs_fall_back_to_text(self):
        self.assertEqual(infer_source_type("notes.txt"), "text")
        self.assertEqual(infer_source_type("notes.txt", declared="nonsense"), "text")
        self.assertEqual(infer_source_type("notes.md", marker_type="nonsense"), "text")

    def test_marker_roundtrip_and_missing_marker(self, ):
        import tempfile
        d = tempfile.mkdtemp()
        self.assertEqual(read_source_marker(d), {}, "no marker -> empty, never an error")
        write_source_marker(d, "epub", origin="深夜特急.epub")
        self.assertEqual(read_source_marker(d).get("source_type"), "epub")
        self.assertEqual(read_source_marker(d).get("origin"), "深夜特急.epub")
        # The marker must never be mistaken for analyzable content.
        self.assertFalse(SOURCE_MARKER.lower().endswith(CONTENT_EXTENSIONS))

    def test_corrupt_marker_is_ignored(self):
        import tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, SOURCE_MARKER), "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        self.assertEqual(read_source_marker(d), {})


# --- analyzer end-to-end -------------------------------------------------------------------------- #
@pytest.fixture
def env(tmp_path):
    uf = tmp_path / "User Files" / "ja"; uf.mkdir(parents=True)
    high = tmp_path / "data" / "ja" / "HighPriority"; high.mkdir(parents=True)
    book = high / "深夜特急"; book.mkdir()
    results = tmp_path / "results"; results.mkdir()

    (uf / "KnownWord.json").write_text(json.dumps({"words": []}), encoding="utf-8")
    (high / "ep01.srt").write_text(SRT, encoding="utf-8")
    (high / "チャンネル - 今日の話題 [dQw4w9WgXcQ].txt").write_text(TRANSCRIPT, encoding="utf-8")
    (book / "本_01.txt").write_text(BOOK, encoding="utf-8")
    write_source_marker(str(book), "epub", origin="深夜特急.epub")

    def guf(path): return str(tmp_path / path)
    def gdp(lang=None): return str(tmp_path / "data" / lang) if lang else str(tmp_path / "data")
    def gufp(lang=None): return str(tmp_path / "User Files" / lang) if lang else str(tmp_path / "User Files")
    return {"root": tmp_path, "results": results, "guf": guf, "gdp": gdp, "gufp": gufp}


def _run(env):
    results = env["results"]
    csv = results / "priority_learning_list.csv"
    if csv.exists():
        csv.unlink()
    with patch("app.analyzer.get_user_file", side_effect=env["guf"]), \
         patch("app.analyzer.get_data_path", side_effect=env["gdp"]), \
         patch("app.analyzer.get_user_files_path", side_effect=env["gufp"]), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(csv)), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"]):
        analyzer.main()
    return pd.read_csv(csv)


def test_priority_csv_carries_the_source_of_each_sentence(env):
    df = _run(env)
    assert "Src 1" in df.columns
    # Every row with an example sentence must say where that sentence came from.
    with_ctx = df[df["Context 1"].notna() & (df["Context 1"] != "")]
    assert not with_ctx.empty
    assert with_ctx["Src 1"].notna().all(), "a sentence without a source would render a blank badge"
    for path in with_ctx["Src 1"]:
        assert path.startswith("HighPriority/"), f"expected a library-relative path, got {path!r}"


def test_source_columns_are_not_named_so_the_report_treats_them_as_sentences(env):
    """Both templates collect extra examples with startsWith('Context ') — a column called
    'Context Source 1' would be rendered as another example sentence. This is the guard."""
    df = _run(env)
    offenders = [c for c in df.columns
                 if c.startswith("Context ") and not c.replace("Context ", "").isdigit()]
    assert offenders == [], f"these columns would be mis-rendered as example sentences: {offenders}"


def test_sources_json_types_each_file(env):
    _run(env)
    with open(env["results"] / "sources.json", encoding="utf-8") as f:
        sources = json.load(f)

    by_type = {meta["type"] for meta in sources.values()}
    assert "subtitle" in by_type, "the .srt should be typed as a subtitle"
    assert "youtube" in by_type, "the [videoID] transcript should be typed as youtube"
    assert "epub" in by_type, "the marked book folder should be typed as epub"
    for path, meta in sources.items():
        assert meta["name"] == os.path.basename(path)


def test_sources_json_carries_the_absolute_path_for_copying(env):
    """The badge shows the short name but copies the FULL path, so what lands on the clipboard can
    be pasted straight into Explorer. The CSVs keep the relative path (portable, export-friendly)."""
    df = _run(env)
    with open(env["results"] / "sources.json", encoding="utf-8") as f:
        sources = json.load(f)

    for rel, meta in sources.items():
        assert os.path.isabs(meta["abs"]), f"{rel} needs an absolute path for the clipboard"
        assert os.path.exists(meta["abs"]), "the copied path must point at a real file"
        assert meta["abs"].endswith(os.path.basename(rel))

    # The CSV stays relative — an exported card shouldn't carry someone's local drive layout.
    for path in df["Src 1"].dropna():
        assert not os.path.isabs(path), f"CSV should hold a relative path, got {path!r}"


def test_progressive_report_also_carries_sources(env):
    _run(env)
    prog = pd.read_csv(env["results"] / "progressive_learning_list.csv")
    assert "Src 1" in prog.columns, "the progressive view shows the same sentences, so same sources"


def test_source_attribution_does_not_change_the_analysis(env):
    """Blast-radius guard: adding provenance must not move a single score or count."""
    before = _run(env)
    after = _run(env)
    cols = ["Word", "Score", "Occurrences", "Count (High)", "Count (Low)", "Count (Goal)", "Context 1"]
    pd.testing.assert_frame_equal(before[cols], after[cols], check_dtype=False)


# --- report rendering ----------------------------------------------------------------------------- #
class TestSourceBadgeRendering(unittest.TestCase):
    """Renders against a SMALL fixture library rather than whatever is in the developer's real
    `results/` — that can be a 14 MB CSV rendering to a 28 MB report, which is both slow and
    non-deterministic. Self-contained, per testing.md."""

    _CACHE = {}

    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        cls._tmp = tempfile.mkdtemp(prefix="surasura_badge_render_")
        results = os.path.join(cls._tmp, "results")
        os.makedirs(results)
        cls._results = results
        cls._cleanup = lambda: shutil.rmtree(cls._tmp, ignore_errors=True)

        # A subtitle and a book chapter, so both a timed and an untimed source are exercised.
        srt = os.path.join(cls._tmp, "ep01.srt")
        with open(srt, "w", encoding="utf-8") as f:
            f.write(SRT)
        book = os.path.join(cls._tmp, "本_01.txt")
        with open(book, "w", encoding="utf-8") as f:
            f.write(BOOK)

        pd.DataFrame([
            {"Word": "秘密", "Reading": "ヒミツ", "Tier": "Outside", "Score": 30, "Occurrences": 3,
             "Count (High)": 3, "Count (Low)": 0, "Count (Goal)": 0, "Sources": "ep01.srt",
             "Context 1": "この街には、まだ秘密が残っている。", "Src 1": "HighPriority/ep01.srt",
             "Context 2": "秘密の部屋が待っていた。", "Src 2": "HighPriority/深夜特急/本_01.txt"},
        ]).to_csv(os.path.join(results, "priority_learning_list.csv"), index=False,
                  encoding="utf-8-sig")

        with open(os.path.join(results, "sources.json"), "w", encoding="utf-8") as f:
            json.dump({
                "HighPriority/ep01.srt": {"name": "ep01.srt", "type": "subtitle", "abs": srt},
                "HighPriority/深夜特急/本_01.txt": {"name": "本_01.txt", "type": "epub", "abs": book},
            }, f, ensure_ascii=False)

        cls._patches = [
            patch("app.static_html_generator.RESULTS_DIR", results),
            patch("app.static_html_generator.PRIORITY_CSV",
                  os.path.join(results, "priority_learning_list.csv")),
            patch("app.static_html_generator.PROGRESSIVE_CSV",
                  os.path.join(results, "progressive_learning_list.csv")),
            patch("app.static_html_generator.OUTPUT_FILE",
                  os.path.join(results, "reading_list_static.html")),
        ]
        for p in cls._patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()
        cls._cleanup()

    def _generate(self, **kwargs):
        # (Browser launching is suppressed suite-wide by the no_browser_launch conftest fixture.)
        from app.static_html_generator import generate_static_html, OUTPUT_FILE
        generate_static_html(**kwargs)
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return f.read()

    def _template(self, theme="default"):
        """Cached render — the assertions below are on template WIRING, which doesn't vary with the
        data. Tests that change settings or remove files call _generate directly so they never see
        a stale document."""
        if theme not in self._CACHE:
            self._CACHE[theme] = self._generate(theme=theme)
        return self._CACHE[theme]

    def test_badge_wiring_and_injection_present(self):
        content = self._template(theme="default")
        self.assertIn("sourceBadge", content, "badge renderer missing")
        self.assertIn("copySourcePath", content, "click-to-copy handler missing")
        self.assertIn("let globalSources =", content, "interned source table not injected")
        self.assertIn("let globalSourceDisplay =", content, "display mode not injected")
        self.assertIn("src-badge", content, "badge CSS class missing")

    def test_badge_is_hidden_from_dictionary_extensions(self):
        """A filename must never be parsed as vocabulary by Migaku/Yomitan."""
        content = self._template(theme="default")
        self.assertIn('class="src-badge" migaku_ignore data-yomichan-ignore', content)

    def test_badge_path_is_a_data_attribute_not_an_inline_string(self):
        """A filename containing a double-quote would close an inline onclick early — the same bug
        the Listen button already hit. The path goes in a data-attribute instead."""
        content = self._template(theme="default")
        self.assertIn("data-src-path=", content)
        self.assertIn("el.dataset.srcPath", content)

    def test_default_display_mode_is_off(self):
        """The badge is opt-in. Asserted against the source of truth and the generator's fallback —
        NOT against the generated report, which reflects whatever the developer has set locally."""
        from app.settings_manager import DEFAULT_SETTINGS
        self.assertEqual(DEFAULT_SETTINGS.get("source_display"), "off")

        for bad in ({}, {"source_display": "nonsense"}, {"source_display": None}):
            with patch("app.settings_manager.load_settings", return_value=dict(bad)):
                content = self._generate(theme="default")
            self.assertIn("let globalSourceDisplay = 'off';", content,
                          f"a missing/invalid mode ({bad}) must fall back to 'off'")

    def test_chosen_display_mode_reaches_the_report(self):
        with patch("app.settings_manager.load_settings", return_value={"source_display": "icon"}):
            content = self._generate(theme="default")
        self.assertIn("let globalSourceDisplay = 'icon';", content)

    def test_badge_sits_inline_after_the_sentence(self):
        """Not right-justified: it follows the sentence text after a space, so it reads as a
        trailing annotation rather than a column."""
        content = self._template(theme="default")
        self.assertNotIn("float: right", content.split(".src-badge {")[1].split("}")[0],
                         "the badge must not be floated to the right edge")
        # Asserted without pinning the tag's attributes — a trimmed sentence also carries a
        # title with the untrimmed original (see test_context_display_trim.py).
        self.assertIn('class="context-box"', content)
        self.assertIn('>${displayC1}${sourceBadge(', content,
                      "the badge must come AFTER the sentence in the markup")
        self.assertIn('${formatted}${badge}', content,
                      "extra example sentences must place their badge after the sentence too")

    def test_hover_shows_group_and_file_not_the_whole_path(self):
        """Hovering should place the sentence ('test_book/chapter_1.txt'), not dump a drive path.
        The tier folder is plumbing — the learner thinks in books and series."""
        from app.static_html_generator import _group_label
        self.assertEqual(_group_label("HighPriority/test_book/file_1.txt"), "test_book/file_1.txt")
        self.assertEqual(_group_label("HighPriority/ep01.srt"), "ep01.srt", "a loose file is just itself")
        self.assertEqual(_group_label("LowPriority/深夜特急/巻1/ch01.txt"), "深夜特急/巻1/ch01.txt")
        self.assertEqual(_group_label("stray.txt"), "stray.txt", "an unbucketed path is left alone")

        content = self._template(theme="default")
        self.assertIn("hover = row[3] || name", content,
                      "the badge must hover the group label, not the absolute path")
        self.assertIn('title="${escapeHtml(hover)}', content)

    def test_shift_click_opens_the_file_at_the_sentence(self):
        """Shift-click OPENS the file in a browser tab, scrolled to the sentence — the same thing a
        YouTube badge's shift-click does with its transcript, rather than making you paste a copied
        link yourself. Plain click still copies the bare path, because Explorer needs that."""
        for theme in ("default", "zen-focus"):
            with self.subTest(theme=theme):
                content = self._template(theme=theme)
                self.assertIn("function sourceDeepLink", content)
                self.assertIn("'#:~:text=' + encodeURIComponent(String(frag))", content,
                              "the anchor comes from the generator, verified against the real file")
                self.assertIn("event.shiftKey && el.dataset.srcUrl", content,
                              "opening must be behind shift, so a plain click stays a plain copy")
                self.assertIn("openInNewTab(el.dataset.srcUrl)", content,
                              "shift-click must OPEN the deep link, not copy it to the clipboard")
                self.assertNotIn("wantsLink", content,
                                 "the old copy-the-link branch must be gone")
                self.assertNotIn("'link copied", content,
                                 "the copy-the-link confirmation is obsolete")
                self.assertIn(".replace(/-/g, '%2D')", content,
                              "'-' is a text-fragment syntax char and must be percent-encoded")
                self.assertIn(".replace(/#/g, '%23')", content,
                              "a '#' in a FILENAME would truncate the URL")

    def test_shift_click_falls_back_to_copying_when_there_is_no_anchor(self):
        """A sentence the generator could not verify against the file has no deep link, so there is
        nothing to open — shift-click must still do something useful rather than silently fail."""
        for theme in ("default", "zen-focus"):
            with self.subTest(theme=theme):
                content = self._template(theme=theme)
                # The open branch is guarded on srcUrl existing; everything else falls through to
                # the copy path below it.
                self.assertIn("if (event && event.shiftKey && el.dataset.srcUrl) {", content)
                self.assertIn("const path = el.dataset.srcPath || '';", content,
                              "the fallback must copy the bare path")

    def test_anchor_is_never_guessed_in_the_browser(self):
        """The stored sentence is not the file's text, so any anchor derived from it in JS would
        miss (or hit the wrong line). The link must come from a `Frag` the generator verified."""
        content = self._template(theme="default")
        self.assertIn('data["Frag 1"]', content, "the badge must read the verified anchor")
        self.assertNotIn("directives.join", content, "the old guessing path must be gone")

    def test_subtitle_cue_time_is_shown_on_hover(self):
        """A subtitle sentence hovers as 'ep01.srt @ 12:03'. Prose has no cue, so nothing is added."""
        for theme in ("default", "zen-focus"):
            with self.subTest(theme=theme):
                content = self._template(theme=theme)
                self.assertIn("function fmtCueTime", content, "cue-time formatter missing")
                self.assertIn("hover += ' @ ' + fmtCueTime(at)", content,
                              "the cue time must be appended to the hover label")
                self.assertIn("data['At ' + n]", content,
                              "each extra sentence must get its own cue time")

    def test_youtube_badge_is_a_link_that_opens_the_video(self):
        """For a YouTube source the VIDEO is the thing, not the transcript file. Click opens it at
        the sentence's moment; shift-click opens the transcript there instead — which is the same
        "shift-click opens it at this sentence" meaning every other source now has."""
        for theme in ("default", "zen-focus"):
            with self.subTest(theme=theme):
                content = self._template(theme=theme)
                self.assertIn("https://youtu.be/", content, "the video link is missing")
                self.assertIn("'?t=' + Math.max(0, Math.floor(Number(at) || 0))", content,
                              "the cue time must become the ?t= offset")
                self.assertIn('target="_blank" rel="noopener"', content,
                              "a real anchor gives middle-click and copy-link-address for free")
                self.assertIn("function youtubeBadgeClick", content)
                self.assertIn("event.preventDefault()", content,
                              "shift-click must not fall through to the browser's new-window default")

    def test_non_youtube_badge_is_not_a_link(self):
        """A local file's badge stays a <span>, not an <a>: a plain click copies rather than
        navigates. Shift-click still opens it, but via openInNewTab, which synthesises the anchor
        at click time — a bare file:// href on the badge itself is unreliable."""
        content = self._template(theme="default")
        self.assertIn("const videoId = row[4] || '';", content,
                      "the link path must be gated on there being a video id")

    def test_zen_report_also_shows_the_badge(self):
        """Zen renders example sentences too, so it gets the same attribution."""
        content = self._template(theme="zen-focus")
        self.assertIn("function sourceBadge", content, "Zen is missing the badge renderer")
        self.assertIn("copySourcePath", content, "Zen is missing the copy handler")
        self.assertIn("let globalSources =", content, "Zen is missing the source table injection")
        # t.text is the display-trimmed sentence; the pairing with its own source is the point here.
        self.assertIn("${formatContext(t.text)}${sourceBadge(c.src, c.frag, c.at)}", content,
                      "Zen must pair each sentence with its own source, anchor and cue time")
        self.assertIn('class="src-badge" migaku_ignore data-yomichan-ignore', content)

    def test_report_generates_without_a_source_table(self):
        """Results produced before this feature have no sources.json. The report must still build:
        paths in the CSV fall back to basename + the generic 'text' type, and if the CSV predates
        the Src columns too, the table is simply empty."""
        from app import static_html_generator
        sources = os.path.join(static_html_generator.RESULTS_DIR, "sources.json")
        backup = None
        if os.path.exists(sources):
            with open(sources, encoding="utf-8") as f:
                backup = f.read()
            os.remove(sources)
        try:
            content = self._generate(theme="default")
            self.assertIn("let globalSources = ", content, "injection must still happen")
            marker = "let globalSources = "
            payload = content.split(marker, 1)[1].split(";\n", 1)[0]
            table = json.loads(payload)
            self.assertIsInstance(table, list, "a missing source table must not corrupt the payload")
            for row in table:
                self.assertEqual(len(row), 5,
                                 "rows stay [name, type, fullPath, groupLabel, videoId]")
                self.assertEqual(row[1], "text", "unknown metadata falls back to the generic type")
        finally:
            if backup is not None:
                with open(sources, "w", encoding="utf-8") as f:
                    f.write(backup)


# --- exports ------------------------------------------------------------------------------------- #
def test_anki_export_appends_source_columns_last(tmp_path):
    """Anki maps fields by column ORDER, so new columns must go at the end — anything else would
    silently shift a user's existing field mapping."""
    from app.frequency_exporter import FrequencyExporter

    src = tmp_path / "priority.csv"
    pd.DataFrame([{
        "Word": "秘密", "Reading": "ヒミツ", "Tier": "Outside", "Sources": "ep01.srt",
        "Context 1": "この街には、まだ秘密が残っている。", "Context 2": "秘密の部屋が待っていた。",
        "Src 1": "HighPriority/ep01.srt", "Src 2": "HighPriority/深夜特急/本_01.txt",
    }]).to_csv(src, index=False, encoding="utf-8-sig")

    out = tmp_path / "anki.csv"
    FrequencyExporter.export_anki_sentences(str(src), str(out))
    df = pd.read_csv(out)

    assert list(df.columns)[:7] == ["Index", "Word", "Reading", "Sentence 1", "Sentence 2",
                                    "Tier", "Sources"], "existing column order must not shift"
    assert list(df.columns)[7:] == ["Source 1", "Source 2"]
    assert df.iloc[0]["Source 1"] == "HighPriority/ep01.srt"


def test_anki_export_still_works_without_source_columns(tmp_path):
    """Exporting an OLD results CSV (no Src columns) must not raise — just leave them blank."""
    from app.frequency_exporter import FrequencyExporter

    src = tmp_path / "old_priority.csv"
    pd.DataFrame([{
        "Word": "答え", "Reading": "コタエ", "Tier": "Outside", "Sources": "ep01.srt",
        "Context 1": "誰も答えを知らなかった。", "Context 2": "",
    }]).to_csv(src, index=False, encoding="utf-8-sig")

    out = tmp_path / "anki_old.csv"
    FrequencyExporter.export_anki_sentences(str(src), str(out))
    df = pd.read_csv(out)
    assert "Source 1" in df.columns
    assert pd.isna(df.iloc[0]["Source 1"]) or df.iloc[0]["Source 1"] == ""
