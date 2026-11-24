"""What is left of the journey's folds (Sonic 2026-10-29: a run of watched parts of one show is one row) after the old
journey page retired (J-RETIRE, Sonic 2026-11-23: "The old journey is done, we only need the new one"):

- the render signature still carries each watched part's show and typed media (`analyzer._stones_fingerprint`): the
  journey page reads them, so a part moved to another show, or a show typed anew, re-draws it;
- the window's fold says its range as the window's rows do (`view_rows.fold_label` / `range_text`);
- `templates/web_app.html` keeps its fold code: the YouTube preview's page (`modules/youtube_downloader/preview.py`).

The old page's own fold (`static_html_generator._journey_folds`, `globalData.folds`, its sidebar) went with it; the
journey page's watched runs are its own (journey v3).
"""
import json
import os

import pytest

from app import analyzer
from app import library_store as ls
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES, migrated, roots

TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "web_app.html")


def _settings(language, **logic):
    settings = {"target_language": language}
    if logic:
        settings["logic"] = logic
    with open(os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False)


def _now_names(store):
    return [os.path.basename(e["physical_path"]) for e in store.schedule()[ls.TIERS["now"][0]]]


def _template():
    with open(TEMPLATE, encoding="utf-8") as f:
        return f.read()


def _function(source, name):
    """The body of the template's `function name(...) { ... }`, by its braces."""
    start = source.index(f"function {name}(")
    i, depth = source.index("{", start), 0
    for j in range(i, len(source)):
        depth += {"{": 1, "}": -1}.get(source[j], 0)
        if depth == 0:
            return source[start:j + 1]
    raise AssertionError(name)


def _library(language, watch, episodes=6, keep=False, media=None):
    """Two shows of `episodes` episodes in NOW, the parts at the indexes `watch` (in the library's order) watched;
    `keep`: *Keep studying watched episodes* on. -> (store, names, counted)."""
    _settings(language)
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


def test_the_fold_says_its_range_as_the_windows_rows_do():
    # why: one way of saying a range, the window's (`view_rows.range_text`) — a fold never invents its own
    assert view_rows.STRINGS["fold_watched"].format(range=view_rows.range_text(None, [1, 2, 3], 3)) == "Ep 1–3 watched"
    assert view_rows.STRINGS["fold_watched"].format(range=view_rows.range_text("book", [5, 6], 2)) == \
        "Parts 5–6 watched"
    assert view_rows.STRINGS["fold_watched"].format(range=view_rows.range_text("youtube", [], 4)) == "4 videos watched"
    assert view_rows.STRINGS["fold_watched"].format(range=view_rows.range_text(None, [1], 3)) == "3 episodes watched"


def test_a_fold_is_re_filed_whole_when_a_parts_check_changes():
    # why (a review find; the YouTube preview's page, web_app.html, keeps this code): un-✓ one part of a fold sitting in Completed — the fold goes back to its place whole (its part
    # still to study again), never a part left under Completed; the last part ✓'d files the whole fold under Completed
    move = _function(_template(), "moveTabToCompletedSection")
    assert "tab.closest('.journey-fold')" in move and ".every(part => completedFiles.has(part.dataset.file))" in move
    assert move.index("tab = fold;") < move.index("if (isCompleted) {")
    first = _template()[_template().index("// Initial Load"):]
    first = first[:first.index("}, 50);")]
    assert first.index("!t.closest('.fold-body')") < first.index("tabs.find(t => !t.closest('#completed-section')) ||"), \
        "nothing open to study: a part in an active fold before anything under Completed"
