"""The report's Anki backlog label — "Label backlogged Anki words" (Junban_Backlog_Spec WP-B8).

Each word a new card is already waiting for in Anki gets a small card-with-a-star mark beside ✦ ⚖ 文,
the Show menu gains "In Anki" / "Not in Anki", and each episode says "12 new · 5 already in Anki".
The words come from `User Files/<lang>/anki_backlog.json`, which the Anki sync and Generate keep.

What this file holds still:

  * **no Anki, no change** — switched off, or with no backlog file, nothing is injected, so the
    report shows no mark, no filter entry and no count; and the checkbox itself only appears once
    Anki sync is set up (§11.1 item 3);
  * **a presentation setting** — the switch and the backlog file are in the RENDER signature (a sync
    costs one re-render) and never the run signature (a sync never costs a re-analysis, §3 I3);
  * **the mark is invisible to dictionary extensions** and needs no network — a masked inline shape;
  * **the match is Junban's** — Word, Orth or any Forms entry, kana folded, one-character spellings
    only as the row's own word.

There is no JS engine in this suite, so the template is a string contract (test_word_search_button.py).
"""

import json
import os
from unittest.mock import patch

import pytest

from app import analyzer, settings_manager
from app.main import anki_sync_is_set_up
from app.static_html_generator import anki_backlog_keys

_BACKLOG = {"version": 1, "synced_at": "2026-09-23T10:00:00", "decks": ["TheBank"],
            "notes": {"1789711432547": {"word": "辿り着く", "keys": ["辿り着く"], "source": "", "freqsort": 12034},
                      "1789711432548": {"word": "スルリ", "keys": ["スルリ", "するり"], "source": "", "freqsort": None}}}


def _write_backlog(language="ja", data=None):
    folder = os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", language)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "anki_backlog.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data if data is not None else _BACKLOG, f, ensure_ascii=False)
    return path


@pytest.fixture
def web_html(project_root):
    with open(os.path.join(project_root, "templates", "web_app.html"), encoding="utf-8") as f:
        return f.read()


# --- what the generator injects ------------------------------------------------------------------- #
def test_the_backlogs_words_are_injected_when_the_label_is_on():
    _write_backlog()
    assert anki_backlog_keys("ja", {"anki_backlog_on_generate": True}) == ["するり", "スルリ", "辿り着く"]


def test_nothing_is_injected_when_switched_off_or_without_a_backlog():
    """The user without Anki (no file) and the user who turned it off see an unchanged report."""
    assert anki_backlog_keys("ja", {"anki_backlog_on_generate": True}) == []
    _write_backlog()
    assert anki_backlog_keys("ja", {"anki_backlog_on_generate": False}) == []


def test_a_damaged_backlog_file_labels_nothing_rather_than_breaking_the_report():
    path = _write_backlog()
    with open(path, "w", encoding="utf-8") as f:
        f.write("{\"notes\": ")
    assert anki_backlog_keys("ja", {"anki_backlog_on_generate": True}) == []


def test_chinese_backlog_words_are_read_in_the_reports_script():
    """A Traditional 學習 card labels the Simplified 学习 row of a list read as Simplified."""
    _write_backlog("zh", {"version": 1, "notes": {"1": {"word": "學習", "keys": ["學習"]}}})
    assert anki_backlog_keys("zh", {"anki_backlog_on_generate": True, "zh_script": "s"}) == ["学习"]
    assert anki_backlog_keys("zh", {"anki_backlog_on_generate": True}) == ["學習"]


def test_the_rendered_report_carries_the_words(tmp_path):
    """The one global the template reads, injected beside the others."""
    from app import static_html_generator as shg
    out = os.path.join(str(tmp_path), "report.html")
    with patch.object(shg, "PRIORITY_CSV", os.path.join(str(tmp_path), "none.csv")), \
         patch.object(shg, "PROGRESSIVE_CSV", os.path.join(str(tmp_path), "none.csv")), \
         patch.object(shg, "OUTPUT_FILE", out), \
         patch.object(shg, "anki_backlog_keys", return_value=["辿り着く"]):
        shg.generate_static_html(theme="default", open_browser=False)
    with open(out, encoding="utf-8") as f:
        assert 'let globalAnkiBacklog = ["辿り着く"];' in f.read()


# --- a presentation setting: re-render, never re-analyze -------------------------------------------- #
def _signatures():
    args = analyzer.parse_analysis_args(["--language", "ja", "--static"])
    return analyzer.compute_render_signature(args)


def test_a_new_backlog_rerenders_the_report_only_while_the_label_is_on():
    settings_manager.save_settings(dict(settings_manager.load_settings(), anki_backlog_on_generate=True))
    before = _signatures()
    _write_backlog()
    assert _signatures() != before, "a sync must re-render, or the report shows the old labels"

    settings_manager.save_settings(dict(settings_manager.load_settings(), anki_backlog_on_generate=False))
    off = _signatures()
    _write_backlog(data=dict(_BACKLOG, synced_at="2026-09-23T11:00:00", decks=["TheBank", "Mining"]))
    assert _signatures() == off, "switched off, the backlog file is nothing to the report"


def test_the_backlog_never_forces_a_reanalysis():
    """§3 I3: a sync — or flipping the label — must never cost a full analysis."""
    from app.path_utils import get_data_path
    folder = get_data_path("ja")
    os.makedirs(os.path.join(folder, "HighPriority"), exist_ok=True)
    with open(os.path.join(folder, "HighPriority", "第01話.txt"), "w", encoding="utf-8") as f:
        f.write("彼は毎日冒険に出かけます。")
    # The first save of a settings.json the sandbox never had changes the signature on its own, so
    # the baseline is taken with the file already written.
    settings_manager.save_settings(dict(settings_manager.load_settings(), anki_backlog_on_generate=True))
    args = analyzer.parse_analysis_args(["--language", "ja", "--static"])
    found = analyzer.resolve_found_files("ja", verbose=False)
    before = analyzer.compute_run_signature("ja", found, args)
    _write_backlog()
    assert analyzer.compute_run_signature("ja", found, args) == before, "a sync"
    settings_manager.save_settings(dict(settings_manager.load_settings(), anki_backlog_on_generate=False))
    assert analyzer.compute_run_signature("ja", found, args) == before, "flipping the label"


# --- the checkbox appears only for someone with Anki ------------------------------------------------ #
def test_the_setting_shows_only_once_anki_decks_are_chosen():
    assert anki_sync_is_set_up({}) is False
    assert anki_sync_is_set_up({"anki_sync_decks": {}}) is False
    assert anki_sync_is_set_up({"anki_sync_decks": {"ja": []}}) is False
    assert anki_sync_is_set_up({"anki_sync_decks": {"zh": ["中文"]}}) is True


# --- the template: a string contract ---------------------------------------------------------------- #
def test_the_mark_is_a_masked_shape_extensions_cannot_read_and_needs_no_network(web_html):
    css = web_html[web_html.index(".marker-anki::before {"):]
    css = css[:css.index("}")]
    assert 'content: "";' in css, "no text in the mark: Yomitan / Migaku must find nothing to read"
    assert "mask:" in css and "url(\"data:image/svg+xml" in css
    assert "http://" not in css.replace("http://www.w3.org/2000/svg", "") and "https://" not in css
    assert ".theme-modern-light .marker-anki::before" in web_html, "legible on the light theme too"


def test_every_card_in_the_backlog_is_marked_and_classed_for_the_filter(web_html):
    card = web_html[web_html.index("function createWordCard(data)"):]
    assert "const inAnki = inAnkiBacklog(data);" in card
    assert "el.classList.add('in-anki')" in card
    assert 'class="priority-marker marker-anki" title="Already in your Anki backlog' in card


def test_the_match_is_junbans_word_orth_forms_kana_folded_one_char_only_as_itself(web_html):
    match = web_html[web_html.index("function inAnkiBacklog(data)"):]
    match = match[:match.index("function ankiBacklogCount")]
    for piece in ("data.Word", "data.Orth", "data.Forms.split('|')", "foldKana(key)",
                  "key.length === 1 && key !== lemma"):
        assert piece in match, piece


def test_the_show_menu_offers_in_anki_only_when_there_is_a_backlog(web_html):
    assert "'anki': 'filter-anki'" in web_html and "'non-anki': 'filter-non-anki'" in web_html
    assert "body.filter-anki .card:not(.in-anki)" in web_html
    assert "body.filter-non-anki .card.in-anki" in web_html
    menu = web_html[web_html.index("function buildSortMenu()"):]
    menu = menu[:menu.index("menu.querySelectorAll")]
    assert "${ANKI_BACKLOG.size ? `<button class=\"sort-menu-item\" data-filter=\"anki\">" in menu


def test_each_episode_counts_the_words_already_in_anki(web_html):
    assert "${fileData.words.length} · ${inAnkiCount}<span class=\"priority-marker marker-anki\"" in web_html, \
        "the sidebar: the count and the mark — words would wrap in its narrow column"
    assert "${words.length} new · ${inAnkiCount} already in Anki" in web_html, "the file header"


def test_without_a_backlog_nothing_changes_in_the_report(web_html):
    """An empty set short-circuits every check — no mark, no count, no menu entry."""
    assert "if (!ANKI_BACKLOG.size || !data) return false;" in web_html
    assert "return ANKI_BACKLOG.size ? (words || []).filter(inAnkiBacklog).length : 0;" in web_html
