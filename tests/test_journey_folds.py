"""The journey folds a run of watched parts into one row (Sonic 2026-10-29: "Keep my rule … fold run of watched into
one row"; his rule of 2026-10-23 kept: a watched part stays in its place on the journey, with its stone, and with no
words while *Keep studying watched episodes* is off).

Two or more watched parts next to each other in the library, of one show or book (its work, else its folder) and one
tier, sitting next to each other in the journey's sidebar, are one fold (`static_html_generator._journey_folds`): each
entry gets `"fold": k` and `globalData.folds[k]` the row's words, *Ep 1–14 watched* — the range as the window's rows say
it (`view_rows.range_text`: episodes, a book's parts, videos). The template draws the fold as one row with the stone; a
click shows each part in its place, a second click folds them again. A single watched part stays as it is.

Rendering only: no word, count, score or order changes. The fold reads each mark's show and typed media, so they are in
the render signature (`analyzer._stones_fingerprint`): a part moved to another show, or a show typed anew, re-draws.

What a wrong answer would cost a learner: two shows' episodes hidden under one row (one of them looks gone), an unwatched
episode folded away among watched ones, or a fold that moves a word or a number on his list.
Japanese and Chinese alike, from a real library store with real stones, under the per-test SURASURA_TEST_ROOT.
"""
import copy
import json
import os
import re
from unittest.mock import patch

import pytest

from app import analyzer
from app import library_store as ls
from app import static_html_generator as gen
from app.services import view_rows
from tests.test_journey_stones import _now_names, _payload, _render, _settings
from tests.test_library_store_support import LANGUAGES, entry, migrated, names, roots, touch, write_manifest
from tests.test_report_journey_stones import _function, _template


def _library(language, watch, episodes=6, keep=False, inline=False, media=None):
    """Two shows of `episodes` episodes in NOW, the parts at the indexes `watch` (in the library's order) watched;
    `keep`: *Keep studying watched episodes* on; `inline`: *Show 'Target Met' inline*. -> (store, names, counted)."""
    _settings(language, **({"inline_completed_files": True} if inline else {}))
    store = migrated(language, shows=2, episodes=episodes, loose=0, tiers=("now",))
    ids, shown = store.ids("now"), _now_names(store)
    if keep:
        store.set_library_options(keep_watched=True)
    if media:
        store.set_media_type(sorted({store.item(i)["work_id"] for i in ids}), media)
    if watch:
        store.set_watched([ids[i] for i in watch])
    counted = shown if keep else [n for i, n in enumerate(shown) if i not in watch]
    return store, shown, counted


def _rerender_in_order(tmp_path, order):
    """The report again with its statistics in the library's order (`_render` writes its Target-met file last, as no
    real run would: the statistics follow the library). -> html."""
    results = tmp_path / "results"
    stats = json.loads((results / "file_statistics.json").read_text(encoding="utf-8"))
    by_name = {s["File"]: s for s in stats}
    (results / "file_statistics.json").write_text(json.dumps([by_name[n] for n in order], ensure_ascii=False),
                                                  encoding="utf-8")
    out = results / "reading_list_static.html"
    with patch.object(gen, "RESULTS_DIR", str(results)),             patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")),             patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")),             patch.object(gen, "OUTPUT_FILE", str(out)):
        gen.generate_static_html(open_browser=False)
    return out.read_text(encoding="utf-8")


def _folds(data, inline=False):
    """[(label, [filenames])] in the sidebar's order."""
    sidebar = data["progressive"]
    if inline:
        done = {e["filename"]: e for e in data["completed_files"]}
        prog = {e["filename"]: e for e in data["progressive"]}
        sidebar = [prog.get(n) or done[n] for n in data["file_order"] if n in prog or n in done]
    out = {}
    for e in sidebar:
        if "fold" in e:
            out.setdefault(e["fold"], []).append(e["filename"])
    return [(data["folds"][k]["label"], files) for k, files in sorted(out.items())]


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_watched_part_alone_stays_as_it_is(language, tmp_path):
    # why: Sonic's rule — a single watched part keeps its own row, its stone, in its place: nothing to fold
    store, shown, counted = _library(language, watch=[1])
    data = _payload(_render(tmp_path, language, counted))
    store.close()
    assert "folds" not in data and not any("fold" in e for e in data["progressive"])
    assert [e["filename"] for e in data["progressive"] if e.get("aside")] == [shown[1]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_watched_parts_next_to_each_other_are_one_row(language, tmp_path):
    store, shown, counted = _library(language, watch=[0, 1])
    data = _payload(_render(tmp_path, language, counted))
    store.close()
    assert _folds(data) == [("Ep 1–2 watched", shown[:2])]
    assert data["folds"][0]["n"] == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_long_run_is_one_row_with_its_range(language, tmp_path):
    # why: the case Mattias met — a show's first 14 episodes watched read as one row, not 14
    store, shown, counted = _library(language, watch=list(range(14)), episodes=16)
    data = _payload(_render(tmp_path, language, counted))
    store.close()
    assert _folds(data) == [("Ep 1–14 watched", shown[:14])]
    # every part keeps its own entry, in its place, with its stone and no words (the option off)
    parts = [e for e in data["progressive"] if "fold" in e]
    assert all(e["aside"] and e["watched"] and e["words"] == [] for e in parts)
    assert [e["filename"] for e in data["progressive"]][:15] == shown[:15]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unwatched_part_breaks_the_run(language, tmp_path):
    # why: an episode still to study is never folded away among watched ones; 1–2 and 4–5 are two rows, and a part
    # left alone after the break (7) stays as it is
    store, shown, counted = _library(language, watch=[0, 1, 3, 4, 6], episodes=8)
    data = _payload(_render(tmp_path, language, counted))
    store.close()
    assert _folds(data) == [("Ep 1–2 watched", shown[0:2]), ("Ep 4–5 watched", shown[3:5])]
    assert "fold" not in next(e for e in data["progressive"] if e["filename"] == shown[6])
    assert "fold" not in next(e for e in data["progressive"] if e["filename"] == shown[2])


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_shows_watched_parts_next_to_each_other_are_never_one_row(language, tmp_path):
    # why: show A's last two episodes and show B's first two are next to each other in the library, all watched — one
    # row for both would hide a whole show under the other's name
    store, shown, counted = _library(language, watch=[4, 5, 6, 7], episodes=6)
    data = _payload(_render(tmp_path, language, counted))
    store.close()
    assert _folds(data) == [("Ep 5–6 watched", shown[4:6]), ("Ep 1–2 watched", shown[6:8])]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_book_split_by_its_chapters_folds_as_parts(language, tmp_path):
    # why: a book's parts are named by their chapters (`extract.part_name`: <book>_07 (3-2) 第一章.txt); the window's
    # rows call a book's range *Parts a–b* (`range_text`), so the fold says what the window says
    _settings(language)
    data_dir, user_files_dir = roots(language)
    book = names(language)[0]
    rels = [f"{ls.FOLDER_OF_TIER['now']}/{book}/{book}_{n:02d} ({c}) {names(language)[n]}.txt"
            for n, c in ((1, "1"), (2, "2"), (3, "2-2"), (4, "3"), (5, "4"), (6, "5"))]
    for rel in rels:
        touch(data_dir, rel, f"{book}\n")
    doc = {"schedule": {p: [] for p in ls.PHASES}}
    doc["schedule"][ls.TIERS["now"][0]] = [entry(rel) for rel in rels]
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    ids, shown = store.ids("now"), _now_names(store)
    store.set_watched(ids[:4])
    data = _payload(_render(tmp_path, language, shown[4:]))
    store.close()
    assert _folds(data) == [("Parts 1–4 watched", shown[:4])]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_typed_as_a_podcast_says_its_numbers(language, tmp_path):
    # why: what the learner typed names the parts (*What is it?*), as the window's rows read it: #1–3
    store, shown, counted = _library(language, watch=[0, 1, 2], media="podcast")
    data = _payload(_render(tmp_path, language, counted))
    store.close()
    assert _folds(data) == [("#1–3 watched", shown[:3])]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("inline", (False, True))
def test_with_keep_studying_on_the_run_folds_and_keeps_its_words(language, inline, tmp_path):
    # why (lean A6H-1, PROVISIONAL): with the option on, watched parts still count — they fold too, and the open row
    # shows each part with its words; a part whose every word is known (Target Met) sits apart unless shown inline,
    # so a fold is only what sits together in the sidebar
    store, shown, counted = _library(language, watch=[0, 1, 2, 3, 4, 5], keep=True)
    data = _payload(_render(tmp_path, language, counted))
    store.close()
    parts = [e for e in data["progressive"] if "fold" in e]
    assert parts and all(e["watched"] and e["words"] and not e.get("aside") for e in parts)
    assert _folds(data, inline) == [("Ep 1–6 watched", shown[:6])]
    assert shown[-1] in [e["filename"] for e in data["completed_files"]], "the Target-met part is the last, unwatched"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_target_met_part_inside_a_run_leaves_the_fold_and_its_range_says_so(language, tmp_path):
    # why: with the option on and *Target Met* at the bottom (the default), a watched part that met its target leaves
    # the run's place; the fold holds what sits together in the sidebar and its range names exactly those (1–2, 4–5),
    # never a part it doesn't hold
    store, shown, counted = _library(language, watch=[0, 1, 2, 3, 4], keep=True, episodes=6)
    met = shown[2]
    data = _payload(_render(tmp_path, language, [n for n in counted if n != met] + [met]))
    store.close()
    assert met in [e["filename"] for e in data["completed_files"]]
    assert _folds(data) == [("Ep 1–2, 4–5 watched", shown[0:2] + shown[3:5])]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_fold_changes_no_word_count_or_order(language, tmp_path):
    # why: rendering only — the report's data with its folds is the report without them, plus the fold keys
    store, shown, counted = _library(language, watch=[0, 1, 2, 4, 5], keep=True)
    folded = _payload(_render(tmp_path, language, counted))
    with patch.object(gen, "_journey_folds", lambda *a, **k: None):
        plain = _payload(_render(tmp_path, language, counted))
    store.close()
    assert folded.get("folds") and "folds" not in plain
    stripped = copy.deepcopy(folded)
    del stripped["folds"]
    for e in stripped["progressive"] + stripped["completed_files"]:
        e.pop("fold", None)
    assert stripped == plain


def test_marks_without_a_show_fold_nothing():
    # why: marks as an older reader gives them (rel, tier, watched, counts) fold nothing: the report as it was
    data = {"progressive": [{"filename": f"x_{n:02d}.srt", "words": []} for n in (1, 2, 3)], "completed_files": []}
    marks = [(f"HighPriority/x/x_{n:02d}.srt", "now", 1, 0) for n in (1, 2, 3)]
    before = copy.deepcopy(data)
    gen._journey_folds(data, [], marks)
    assert data == before
    gen._journey_folds(data, [], ls.UNREAD)
    gen._journey_folds(data, [], None)
    assert data == before


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_show_typed_anew_or_a_part_moved_re_draws_the_journey(language, monkeypatch):
    # why: the fold reads each watched part's show and typed media; neither is a run input, so the render signature
    # carries them — else a learner's *What is it?* would leave the old words on the row until something else re-drew
    store, shown, counted = _library(language, watch=[0, 1])
    data_dir, _u = roots(language)
    before = analyzer._stones_fingerprint(language, ls.read_watched_marks(language, data_dir))
    marks = ls.read_watched_marks(language, data_dir)
    assert [m[4][0] for m in marks[:2]] == ["w", "w"] and marks[0][4] == marks[1][4] and marks[0][5] is None
    store.set_media_type([store.item(store.ids("now")[0])["work_id"]], "podcast")
    after = ls.read_watched_marks(language, data_dir)
    store.close()
    assert after[0][5] == "podcast"
    assert analyzer._stones_fingerprint(language, after) != before


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_template_draws_a_fold_as_one_row_with_the_stone_that_opens_and_folds_again(language, tmp_path):
    # why: the report a learner opens is the template plus the data. No browser in pytest: the drawing is read from
    # the template the report embeds (the real-browser check is recorded in the step's register)
    store, shown, counted = _library(language, watch=[0, 1, 2])
    html = _render(tmp_path, language, counted)
    store.close()
    progressive = _function(html, "renderProgressiveView")
    assert progressive.index("foldWatchedRuns(fileList)") < progressive.index("fileList.filter(isItemCompleted)"), \
        "folded before the browser's ✓ split: a fold goes to Completed only when every part is ✓"
    row = _function(html, "createFoldRow")
    assert "journeyStone({ watched: true })" in row and "globalData.folds[item.fold].label" in row
    assert "createSidebarTab(part)" in row, "each part keeps its own tab, in its place, inside the fold"
    assert "toggleFold(wrap)" in row and "'▾' : '▸'" in _function(html, "toggleFold")
    assert "item.items.every(isItemCompleted)" in _function(html, "isItemCompleted")
    assert "openFoldOf(tabs[i])" in _function(html, "goToNextIncompleteFile"), "a ✓ advancing into a fold opens it"
    assert "tab.closest('.journey-fold')" in _function(html, "moveTabToCompletedSection"), "a part stays in its fold"
    first = html[html.index("// Initial Load"):]
    assert "openFoldOf(firstTab)" in first[:first.index("}, 50);")], "the asked part is shown, its fold opened"
    assert "itemHolds(item, asked)" in first, "the window's asked part found inside a fold, paged sidebar too"
    assert re.search(r"\.journey-fold \.fold-body \{\s*display: none;", html)
    assert re.search(r"\.journey-fold\.open \.fold-body \{\s*display: block;", html)
    tip = re.search(r"let globalFoldTip = (\"[^\"]*\");", html)
    assert tip and json.loads(tip.group(1)) == view_rows.STRINGS["fold_tip"]
    assert _payload(html)["folds"] == [{"label": "Ep 1–3 watched", "n": 3}]


def test_the_fold_says_its_range_as_the_windows_rows_do():
    # why: one way of saying a range, the window's (`view_rows.range_text`) — a fold never invents its own
    assert view_rows.STRINGS["fold_watched"].format(range=view_rows.range_text(None, [1, 2, 3], 3)) == "Ep 1–3 watched"
    assert view_rows.STRINGS["fold_watched"].format(range=view_rows.range_text("book", [5, 6], 2)) == \
        "Parts 5–6 watched"
    assert view_rows.STRINGS["fold_watched"].format(range=view_rows.range_text("youtube", [], 4)) == "4 videos watched"
    assert view_rows.STRINGS["fold_watched"].format(range=view_rows.range_text(None, [1], 3)) == "3 episodes watched"


def _aside(names):
    return {"progressive": [{"filename": n, "watched": True, "aside": True, "words": []} for n in names],
            "completed_files": []}


def test_a_run_never_crosses_a_tier():
    # why: the Soon line (or Goal) parts a show; the journey's row never holds parts of two tiers
    marks = [(f"HighPriority/x/x_{n:02d}.srt", "now" if n < 4 else "soon", 1, 0, "w1", None) for n in range(1, 7)]
    data = _aside([f"x_{n:02d}.srt" for n in range(1, 7)])
    gen._journey_folds(data, [], marks)
    assert [f["label"] for f in data["folds"]] == ["Ep 1–3 watched", "Ep 4–6 watched"]


def test_a_name_two_marks_share_is_never_folded():
    # why (a review find): the report keys a file by its name; show B's unwatched 01.srt and show A's watched 01.srt are
    # one entry — B's, with its words — which a fold would hide under "watched"
    marks = [("HighPriority/A/01.srt", "now", 1, 0, "w1", None), ("HighPriority/A/02.srt", "now", 1, 0, "w1", None),
             ("HighPriority/A/03.srt", "now", 1, 0, "w1", None), ("HighPriority/B/01.srt", "now", 0, 1, "w2", None)]
    data = _aside(["01.srt", "02.srt", "03.srt"])
    data["progressive"][0] = {"filename": "01.srt", "words": ["冒険"]}           # B's counted entry holds the name
    gen._journey_folds(data, [], marks)
    assert "fold" not in data["progressive"][0]
    assert [f["label"] for f in data["folds"]] == ["Ep 2–3 watched"]


def test_a_fold_is_re_filed_whole_when_a_parts_check_changes():
    # why (a review find): un-✓ one part of a fold sitting in Completed — the fold goes back to its place whole (its part
    # still to study again), never a part left under Completed; the last part ✓'d files the whole fold under Completed
    move = _function(_template(), "moveTabToCompletedSection")
    assert "tab.closest('.journey-fold')" in move and ".every(part => completedFiles.has(part.dataset.file))" in move
    assert move.index("tab = fold;") < move.index("if (isCompleted) {")
    first = _template()[_template().index("// Initial Load"):]
    first = first[:first.index("}, 50);")]
    assert first.index("!t.closest('.fold-body')") < first.index("tabs.find(t => !t.closest('#completed-section')) ||"), \
        "nothing open to study: a part in an active fold before anything under Completed"


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unwatched_part_away_from_the_sidebar_still_breaks_the_run(language, tmp_path):
    # why: Ep 3 is not watched but every word of it is known (Target Met, at the bottom): Ep 2 and Ep 4 sit next to each
    # other in the sidebar, yet they are not next to each other in the show — two rows, never "Ep 1–2, 4–5"
    store, shown, counted = _library(language, watch=[0, 1, 3, 4])
    met = shown[2]
    data = _payload(_render(tmp_path, language, [n for n in counted if n != met] + [met]))
    store.close()
    assert met in [e["filename"] for e in data["completed_files"]]
    assert _folds(data) == [("Ep 1–2 watched", shown[0:2]), ("Ep 4–5 watched", shown[3:5])]


@pytest.mark.parametrize("language", LANGUAGES)
def test_with_target_met_shown_inline_a_met_part_stays_in_its_fold(language, tmp_path):
    # why: with *Show 'Target Met' inline* on, a watched part whose words are all known sits in its place, so the run
    # is one row again (the fold follows the sidebar as the setting draws it)
    store, shown, counted = _library(language, watch=[0, 1, 2, 3, 4], keep=True, inline=True)
    met = shown[2]
    _render(tmp_path, language, [n for n in counted if n != met] + [met])
    data = _payload(_rerender_in_order(tmp_path, counted))
    store.close()
    assert _folds(data, inline=True) == [("Ep 1–5 watched", shown[0:5])]
