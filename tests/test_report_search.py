"""The report's 🔍 Search tab (docs/agent instructions/Report_Search_Spec.md).

Two halves:

* **Engine** — a new `Forms` column on both result CSVs: the inflected forms a word was actually met
  in (食べ, 食べた …). It is what lets a search for 食べた find the 食べる card from real data rather
  than a guessed de-inflection. Measured on the live library when this was written: 342 of 3,704
  priority rows had a surface form that never appeared literally in their own Context 1.
* **Template** — the tab itself, in `templates/web_app.html`. There is no JS engine in this suite
  (node isn't installed), so, as with the other report features, the template is held to string
  contracts, and the two pieces of matching logic that decide results are mirrored in Python below.
  The behaviour was verified end to end in headless Edge against the real 42 MB report.
"""
import csv
import os
import re
import sys
import unicodedata
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import analyzer


# --------------------------------------------------------------------------- #
# Engine: the Forms column
# --------------------------------------------------------------------------- #

def _run_analyzer(root, language, text):
    """Run the real analyzer over one real-text file in a sandbox and return both CSVs' rows."""
    high = root / "data" / language / "HighPriority"
    high.mkdir(parents=True)
    (root / "User Files" / language).mkdir(parents=True)
    results = root / "results"
    results.mkdir()
    (high / "a.txt").write_text(text, encoding="utf-8")

    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(root / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(root / "data" / l) if l else str(root / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(root / "User Files" / l) if l else str(root / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch.object(sys, "argv", ["analyzer.py", "--language", language, "--min-freq", "1"]):
        analyzer.main()

    def rows(name):
        with open(results / name, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    return rows("priority_learning_list.csv"), rows("progressive_learning_list.csv"), results


# One verb met in several inflections, plus the proper-noun pair the Orth tests use.
JA_TEXT = (
    "昨日は寿司を食べた。\n"
    "毎朝パンを食べる。\n"
    "もう晩ご飯を食べている。\n"
    "一緒に食べよう。\n"
    "須藤は鳥取へ行く。\n"
    "須藤がまた来た。\n"
)


@pytest.fixture
def ja_run(tmp_path):
    return _run_analyzer(tmp_path, "ja", JA_TEXT)


def test_forms_column_exists_on_both_lists_right_after_orth(ja_run):
    """Both lists feed the report; the search index reads Forms from whichever row it gets."""
    priority, progressive, _ = ja_run
    for rows in (priority, progressive):
        cols = list(rows[0].keys())
        assert "Forms" in cols
        assert cols.index("Forms") == cols.index("Orth") + 1


def test_forms_lists_an_inflected_surface_seen_in_the_content(ja_run):
    """食べた / 食べて reach the tokenizer as the stem 食べ — that stem must be searchable under 食べる."""
    priority, _, _ = ja_run
    forms = [f for r in priority if r["Word"] == "食べる" for f in r["Forms"].split("|") if f]
    assert "食べ" in forms, f"expected the stem 食べ among {forms!r}"


def test_forms_is_empty_not_nan_for_a_word_seen_only_in_its_own_spelling(ja_run):
    """A blank must be a real empty string in the CSV. The report treats NaN as absent too, but the
    file itself should never say 'nan'."""
    priority, _, _ = ja_run
    assert all(r["Forms"] != "nan" for r in priority)
    assert any(r["Forms"] == "" for r in priority), "most rows have no other form"


def test_forms_matches_between_the_two_lists(ja_run):
    """Same word, same forms, whichever list the search index happens to read it from."""
    priority, progressive, _ = ja_run
    prio = {(r["Word"], r["Reading"]): r["Forms"] for r in priority}
    for r in progressive:
        key = (r["Word"], r["Reading"])
        if key in prio:
            assert r["Forms"] == prio[key]


def test_word_stats_json_does_not_grow_a_surfaces_dump(ja_run):
    """word_stats.json was deliberately slimmed; the Counter is emitted as the CSV column instead."""
    import json
    _, _, results = ja_run
    stats = json.loads((results / "word_stats.json").read_text(encoding="utf-8"))
    assert stats, "the run should write word stats"
    assert all("surfaces" not in v for v in stats.values())
    assert all("orths" in v for v in stats.values()), "existing keys stay as they were"


def test_forms_excludes_the_lemma_and_the_displayed_spelling():
    """Those are already searchable as Word and Orth; repeating them would only add noise."""
    assert analyzer._display_forms("食べる", Counter({"食べる": 5}),
                                   Counter({"食べる": 3, "食べ": 2})) == "食べ"


def test_forms_are_commonest_first_and_capped():
    """The search matches forms as substrings, so the long tail only adds noise and bytes."""
    surfaces = Counter({f"言{'わ' * i}": 100 - i for i in range(1, 12)})
    out = analyzer._display_forms("言う", Counter({"言う": 1}), surfaces).split("|")
    assert len(out) == analyzer.FORMS_LIMIT == 8
    assert out[0] == "言わ" and out[1] == "言わわ", "commonest first"


def test_forms_ignores_blank_surfaces():
    assert analyzer._display_forms("有る", Counter(), Counter({"": 9, "有っ": 1})) == "有っ"
    assert analyzer._display_forms("有る", Counter(), Counter()) == ""
    assert analyzer._display_forms("有る", Counter(), None) == ""


def test_chinese_rows_get_an_empty_forms_column(tmp_path, zh_resources_dir):
    """Jieba's surface IS the dictionary form, so a Chinese word never has another form. Empty is
    correct, not a bug — asserted so nobody 'fixes' it."""
    with open(os.path.join(zh_resources_dir, "context_test.txt"), encoding="utf-8") as f:
        text = f.read()
    priority, _, _ = _run_analyzer(tmp_path, "zh", text)
    assert priority
    assert all(r["Forms"] == "" for r in priority)


def test_forms_is_not_named_like_an_example_sentence():
    """Both templates collect example sentences with startsWith('Context ')."""
    assert not "Forms".startswith("Context ")


def test_engine_revision_was_bumped_for_the_forms_column():
    """A new column changes what a run outputs for unchanged inputs. Without the bump the stored run
    signature still matches and the old report — with no Forms — is served. Pinned exactly so the
    next person to bump it updates this knowingly."""
    assert analyzer.ENGINE_REVISION == 9


# --------------------------------------------------------------------------- #
# Render signature: template changes must re-render
# --------------------------------------------------------------------------- #

def _sig_args():
    return SimpleNamespace(theme="default", zen_limit=0)


def _fake_templates(tmp_path, web_text):
    (tmp_path / "templates").mkdir(exist_ok=True)
    (tmp_path / "templates" / "web_app.html").write_text(web_text, encoding="utf-8")
    (tmp_path / "templates" / "zen_app.html").write_text("<p>禅</p>", encoding="utf-8")
    return lambda rel: str(tmp_path / rel)


def test_render_signature_changes_when_the_template_changes(tmp_path):
    """Before this, a template-only change (like adding this tab) was invisible to both fast paths:
    Generate reopened the old HTML until something else forced a re-render."""
    with patch("app.analyzer.get_resource", side_effect=_fake_templates(tmp_path, "<p>旧版</p>")):
        before = analyzer.compute_render_signature(_sig_args())
    with patch("app.analyzer.get_resource", side_effect=_fake_templates(tmp_path, "<p>新版</p>")):
        after = analyzer.compute_render_signature(_sig_args())
    assert before != after


def test_render_signature_is_stable_when_nothing_changes(tmp_path):
    with patch("app.analyzer.get_resource", side_effect=_fake_templates(tmp_path, "<p>同じ</p>")):
        assert analyzer.compute_render_signature(_sig_args()) == \
               analyzer.compute_render_signature(_sig_args())


def test_an_unreadable_template_never_breaks_the_signature(tmp_path):
    """The signature decides whether to reopen or re-render; it must never raise."""
    with patch("app.analyzer.get_resource", side_effect=lambda rel: str(tmp_path / "missing" / rel)):
        sig = analyzer.compute_render_signature(_sig_args())
    assert "templates-unreadable" in sig


def test_the_template_fingerprint_is_render_only_not_analysis():
    """A template change must re-render, never re-analyze: it is not in the run signature."""
    import inspect
    assert "_template_fingerprint" not in inspect.getsource(analyzer.compute_run_signature)


# --------------------------------------------------------------------------- #
# Template contract (string pins — there is no JS engine in this suite)
# --------------------------------------------------------------------------- #

@pytest.fixture
def web_html(project_root):
    with open(os.path.join(project_root, "templates", "web_app.html"), encoding="utf-8") as f:
        return f.read()


def _rs_css(web_html):
    start = web_html.index("/* --- Report Search")
    return web_html[start:web_html.index("/* --- Priority Filter", start)]


def test_the_tab_button_uses_the_exact_onclick_form_switchmaintab_looks_up(web_html):
    """switchMainTab finds its button with an attribute selector on this exact string; any other
    form throws on null.classList the moment the tab is clicked."""
    assert "onclick=\"switchMainTab('search')\"" in web_html
    assert 'aria-label="Search"' in web_html


def test_the_search_view_has_a_word_list_container(web_html):
    """Card hotkeys target `.view.active .word-list-container` — this is what makes Space / arrows /
    z / v work on search results with no handler changes."""
    view = web_html[web_html.index('<div id="view-search" class="view">'):]
    view = view[:view.index("</div>\n    </div>")]
    assert 'class="word-list-container" id="rs-results"' in view
    assert '<input id="rs-input" type="search"' in view


def test_no_identifier_collides_with_the_online_lookup(web_html):
    """searchWord / isSearch / .btn-search / #hint-search belong to the Nadeshiko button and are
    pinned by tests/test_word_search_button.py."""
    assert web_html.count("function searchWord(") == 1
    assert web_html.count("const isSearch =") == 1
    assert not re.search(r"function (search|isSearch)\w*\(", web_html.replace("function searchWord(", ""))
    for name in re.findall(r"function (rs\w+)\(", web_html):
        assert name.startswith("rs")


def test_the_input_restores_the_caret_the_body_hides(web_html):
    """body{caret-color:transparent} would leave the search box with an invisible caret."""
    css = _rs_css(web_html)
    rule = css[css.index("#rs-input {"):]
    rule = rule[:rule.index("}")]
    assert "caret-color: var(--primary)" in rule
    assert "cursor: text" in rule


def test_search_styles_use_only_theme_variables(web_html):
    """modern-light is a light theme; a hard-coded white would vanish on it."""
    css = _rs_css(web_html)
    assert "#fff" not in css.lower()
    assert "rgba(255" not in css.replace(" ", "")
    assert "var(--surface)" in css and "var(--primary)" in css


def test_the_show_filter_never_hides_a_search_result(web_html):
    assert 'body[class*="filter-"] #view-search .card' in _rs_css(web_html)


def test_slash_opens_search_and_is_not_typed(web_html):
    block = web_html[web_html.index("`/` opens the search tab"):]
    block = block[:block.index("return;")]
    assert "e.key === '/'" in block
    assert "e.preventDefault();" in block
    assert "rsOpen();" in block
    assert "e.target.tagName !== 'INPUT'" in block


def test_slash_is_listed_in_the_hotkey_reference(web_html):
    hint = web_html[web_html.index('<div id="nav-hint">'):web_html.index("</header>")]
    assert "<b>/</b> : Search This Report" in hint


def test_the_ime_owns_enter_and_escape_while_composing(web_html):
    """Enter confirms a Japanese IME conversion. Without this guard it would also run the search and
    blur the box mid-word."""
    assert "if (e.isComposing || e.keyCode === 229) return;" in web_html


def test_the_index_guards_against_nan_fields(web_html):
    """pandas NaN survives decompression as a JS number; escapeHtml(NaN) throws."""
    build = web_html[web_html.index("function rsBuildIndex()"):web_html.index("function rsMark(")]
    assert "typeof row.Word !== 'string'" in build
    assert "typeof row.Forms === 'string'" in build
    assert "typeof k === 'string'" in build


def test_session_ignored_words_are_skipped(web_html):
    run = web_html[web_html.index("function rsRun("):web_html.index("function rsSearchFor(")]
    assert "!ignoredWords.has(e.row.Word)" in run


def test_the_hash_deep_link_is_wired(web_html):
    assert "location.hash.startsWith('#search=')" in web_html
    assert "rsFromHash();" in web_html


def test_generated_report_carries_forms_to_the_browser(tmp_path, monkeypatch):
    """The column must survive the generator's {keys, rows} compression, not just the CSV."""
    import pandas as pd
    from app import static_html_generator

    results = tmp_path / "results"
    results.mkdir()
    rows = [{"Word": "食べる", "Orth": "食べる", "Forms": "食べ|食べよ", "Reading": "タベ",
             "Tier": "Outside", "Score": 20, "Occurrences": 4, "Count (High)": 4,
             "Count (Low)": 0, "Count (Goal)": 0, "Modality": "", "Sources": "a.txt",
             "Context 1": "昨日は寿司を食べた。"}]
    pd.DataFrame(rows).to_csv(results / "priority_learning_list.csv", index=False, encoding="utf-8-sig")
    prog = [dict(r, Sequence=1, **{"Source File": "a.txt", "Occurrences (Global)": 4,
                                   "Occurrences (File)": 4}) for r in rows]
    pd.DataFrame(prog).to_csv(results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")

    out = results / "reading_list_static.html"
    monkeypatch.setattr(static_html_generator, "RESULTS_DIR", str(results))
    monkeypatch.setattr(static_html_generator, "PRIORITY_CSV", str(results / "priority_learning_list.csv"))
    monkeypatch.setattr(static_html_generator, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv"))
    monkeypatch.setattr(static_html_generator, "OUTPUT_FILE", str(out))
    static_html_generator.generate_static_html(theme="default")

    html = out.read_text(encoding="utf-8")
    assert '"Forms"' in html
    assert 'id="view-search"' in html


# --------------------------------------------------------------------------- #
# Python mirror of the two matching rules (precedent: test_context_display_trim.py)
# --------------------------------------------------------------------------- #

def rs_norm(s):
    """Mirror of rsNorm: NFKC, katakana -> hiragana, lower-case."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKC", s).strip()
    s = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)
    return s.lower()


def rs_keep_needle(s):
    """Mirror of rsKeepNeedle."""
    return bool(re.search(r"[㐀-䶿一-鿿々]", s)) or len(s) >= 3


def test_the_mirrors_match_the_template(web_html):
    """If either JS rule changes, this fails until the mirror above is updated with it."""
    assert "s.normalize('NFKC').trim()" in web_html
    assert ".replace(/[\\u30A1-\\u30F6]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0x60))" in web_html
    assert "return /[\\u3400-\\u4DBF\\u4E00-\\u9FFF々]/.test(s) || s.length >= 3;" in web_html


def test_a_hiragana_query_matches_a_katakana_reading_and_back():
    assert rs_norm("たべる") == rs_norm("タベル")
    assert rs_norm("ヤガル") == rs_norm("やがる")


def test_half_and_full_width_normalise_together():
    assert rs_norm("ｶﾞﾝﾊﾞﾙ") == rs_norm("がんばる")
    assert rs_norm("ＳＮＯＷ") == rs_norm("snow")


def test_variant_needles_keep_kanji_stems_and_drop_short_kana():
    """Kana stems like し / さ / で (forms of する / だ) would hit nearly every sentence."""
    assert rs_keep_needle("食べ")
    assert rs_keep_needle("仕方な")
    assert rs_keep_needle("ください")
    for stem in ("し", "さ", "で", "いっ"):
        assert not rs_keep_needle(stem)


def test_primary_is_an_exact_match_not_a_prefix():
    """D3: what the user typed, exactly. 食べ alone does not primary-match 食べる unless 食べ is one
    of that row's real Forms."""
    keys_without_form = {rs_norm(k) for k in ("食べる", "食べる", "タベル")}
    keys_with_form = keys_without_form | {rs_norm("食べ")}
    assert rs_norm("食べ") not in keys_without_form
    assert rs_norm("食べ") in keys_with_form
