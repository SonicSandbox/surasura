"""The 🎧 before an audiobook's title wherever a title is shown (Kantan-T, Sonic 2026-11-18: an audiobook should show in
Goal too; words PROVISIONAL).

Current's rows and New arrivals' already paint `rows.HEADPHONES` before the title of a title holding an audiobook (a5-2:
`rows.heard_title` / `Row.audio`, its words in the hover). Goal's sheet (its tiles), the search results and the sort
screen showed the bare title. Now every one goes through the same two helpers — `rows.heard_title` (the title as painted)
and `rows.heard_tip` (its hover: the text, then the 🎧's words) — and the models carry the hover the rows do
(`GoalWork.audio` from `view_rows.audio_tip`, the search `Hit.audio` from its row's). Finished's rows are Current's
`Row`s and its painter already reads `heard_title` (held here too).

What a wrong answer costs: an audiobook that vanishes as such once it is in Goal (the learner can't tell a book from
its audiobook there), a hover that differs from place to place, or 🎧 on a title with no audiobook.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QLabel

from app.qt import rows
from app.services import search as search_service
from app.services import view_rows as vr

NEKO = "吾輩は猫である"
SUMMARY = {"title": NEKO, "n": 12, "first": "01.mp3", "last": "12.mp3", "seconds": 33120, "paired": True}


def _parts(tier="goal", work=7):
    return [{"id": i, "tier": tier, "ord": float(i), "rel_path": f"Library/{NEKO}/{NEKO}_0{i}.txt",
             "title": f"{NEKO}_0{i} (1-{i}) 第一章.txt", "source_type": "epub", "availability": "available",
             "work_id": work, "piece_id": 1} for i in (1, 2)]


def _audiobook(tier="goal", work=7):
    return dict(_parts(tier, work)[0], id=3, ord=3.0, rel_path=f"Library/{NEKO}/01.mp3", title=NEKO,
                source_type="audio", availability="waiting", audio=SUMMARY)


WORKS = {7: {"id": 7, "title": NEKO, "media_type": "book"}, 8: {"id": 8, "title": "坊っちゃん", "media_type": "book"}}


def test_a_goal_tile_carries_the_same_hover_as_its_row_in_current():
    """`GoalWork.audio` is `audio_tip` over the title's files in Goal — the very words its row in Current would show;
    a title with no audiobook has none."""
    tiles, _entries = vr.goal_tiles(_parts() + [_audiobook()], WORKS)
    [tile] = tiles
    row = vr._row(0, "now", _parts("now") + [_audiobook("now")], WORKS, {}, {}, set(), set(), 20)
    assert tile.audio and tile.audio == row.audio
    assert tile.audio.splitlines()[0] == f"🎧 With its audiobook 「{NEKO}」"
    plain, _e = vr.goal_tiles(_parts(work=8), WORKS)
    assert plain[0].audio == ""
    assert rows.heard_title(tile) == f"{rows.HEADPHONES}{tile.title}" and rows.heard_title(plain[0]) == plain[0].title


def test_the_one_hover_rule_adds_the_headphones_words_after_any_text():
    a = SimpleNamespace(title=NEKO, audio="🎧 Audio only 「吾輩は猫である」")
    assert rows.heard_tip(a) == f"{NEKO}\n{a.audio}"
    assert rows.heard_tip(a, "Goal · 3 parts") == f"Goal · 3 parts\n{a.audio}"
    assert rows.heard_tip(SimpleNamespace(title=NEKO, audio=""), "x") == "x"
    assert rows.heard_tip(SimpleNamespace(title=NEKO)) == NEKO          # a model from before `audio` (a cache)


def test_the_goal_sheets_tile_paints_the_headphones_and_says_them_on_hover(qapp, monkeypatch):
    from app.qt import goal_sheet
    tiles, _e = vr.goal_tiles(_parts() + [_audiobook()], WORKS)
    drawn = []
    real = rows.TEXT.draw
    monkeypatch.setattr(rows.TEXT, "draw", lambda p, x, y, text, *a, **k: drawn.append(text) or real(p, x, y, text,
                                                                                                         *a, **k))
    sheet = SimpleNamespace(picks=set(), menu=lambda *a: None)
    tile = goal_sheet.Tile(sheet, tiles[0], None)
    tile.apply_size()
    tile.grab()
    assert f"{rows.HEADPHONES}{tiles[0].title}" in drawn
    assert tile.toolTip() == f"{tiles[0].tip}\n{tiles[0].audio}"


def test_search_hits_carry_their_rows_headphones():
    """Current's, New arrivals' and Finished's hits take their row's `audio`; a hit with none stays bare."""
    row = vr._row(1, "now", _parts("now") + [_audiobook("now")], WORKS, {}, {}, set(), set(), 20)
    plain = vr._row(2, "now", _parts("now", 8), WORKS, {}, {}, set(), set(), 20)
    hit = search_service._hit(row.key, "current", row.title, "猫", "ja", "#1 in Current", (1, 2, 3), 7, 1,
                              audio=row.audio)
    assert hit.audio == row.audio and rows.heard_title(hit).startswith(rows.HEADPHONES)
    bare = search_service._hit(plain.key, "current", plain.title, "坊", "ja", "#2 in Current", (1, 2), 8, 1)
    assert bare.audio == "" and rows.heard_title(bare) == plain.title


def test_search_gives_each_hit_its_rows_headphones(monkeypatch):
    """`search()` itself: Current's, New arrivals' and Finished's hits carry their row's `audio` (Goal's are its
    files' own, `_goal_read`)."""
    row = vr._row(1, "now", _parts("now") + [_audiobook("now")], WORKS, {}, {}, set(), set(), 20)
    plain = vr._row(2, "now", _parts("now", 8), WORKS, {}, {}, set(), set(), 20)
    done = vr._row(0, "graduated", _parts("graduated") + [_audiobook("graduated")], WORKS, {}, {}, set(), set(), 20,
                   finished=True)
    arrival = SimpleNamespace(key="a1", work_id=7, piece_id=1, item_ids=(1, 2, 3), title=NEKO, line="", cover_title=NEKO,
                              audio=row.audio)
    view = SimpleNamespace(language="ja", rows=(row, plain), arrivals=(arrival,),
                           finished=(vr.Month("November", (done,)),))
    store = SimpleNamespace(search=lambda query: ({7, 8}, set()))
    monkeypatch.setattr(search_service, "_goal", lambda *a: ((), 0, set()))
    groups = {g.kind: g.hits for g in search_service.search(store, view, "猫")}
    assert [h.audio for h in groups["current"]] == [row.audio, ""]
    assert groups["arrivals"][0].audio == row.audio and groups["finished"][0].audio == done.audio != ""


def test_a_search_hit_paints_the_headphones_before_its_lit_title(qapp):
    from app.qt import search as qsearch
    hit = search_service._hit("w7", "goal", NEKO, "猫", "ja", "Goal · 3 parts", (1, 2, 3), 7, None,
                              audio="🎧 With its audiobook 「吾輩は猫である」")
    widget = qsearch.HitRow(hit)
    widget.resize(420, 44)
    assert widget.toolTip().endswith("\n" + hit.audio)
    widget.grab()                                       # paints: the 🎧 and the lit title, never an error


def test_the_sort_screens_titles_show_the_headphones_and_their_words():
    from app.qt import sort_screen
    label = QLabel()
    a = SimpleNamespace(title=NEKO, audio="🎧 Audio only 「吾輩は猫である」")
    sort_screen._heard(label, a)
    assert label.text() == f"{rows.HEADPHONES}{NEKO}" and label.toolTip() == f"{NEKO}\n{a.audio}"
    sort_screen._heard(label, SimpleNamespace(title="坊っちゃん", audio=""))
    assert label.text() == "坊っちゃん" and label.toolTip() == ""


def test_finished_rows_paint_the_headphones_as_currents_do():
    """Finished's rows are `Row`s built with `finished=True`: the same `audio`, read by the painter's `heard_title`."""
    row = vr._row(0, "graduated", _parts("graduated") + [_audiobook("graduated")], WORKS, {}, {}, set(), set(), 20,
                  finished=True)
    assert row.audio and rows.heard_title(row).startswith(rows.HEADPHONES)
