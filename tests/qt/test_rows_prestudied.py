"""J-STONES (3.0.19; journey v3 SPEC §2.4): the window's stones show what was pre-studied.

Pre-studied is an episode whose words the learner went through before watching it; the journey page marks it (its end
card reached, or a press on its stone) and the library store keeps it (`prestudied_at`). The window gives no press for
it (D5): it only shows it. Where an episode has its own stone (the twelve in play), the stone carries the add — a cool
sheen and a small sparkle at its shoulder — and its tip gains *✧ Pre-studied on 21 Nov*; where it has none (a cut group
of the watched past, or the ore after the twelve), the group or the ore carries the sparkle and its hover names the
episodes. The mark comes through the window's one feed, like everything the window draws (`read_feed`).

The redraw rule (Sonic, 2026-11-22: "it only redraws what is essential"): a mark and its Undo repaint that show's row
alone — its picture drawn once, the add blitted once — never another row, Finished or the Goal strip.

What a wrong answer would cost a learner: an episode they pre-studied that the window doesn't show (or still shows
after an Undo); a whole list repainted at each press; a stone that moves on its string when it gains the add.

On the window's synthetic seed (invented titles; Japanese and Chinese libraries), through the stand-in store.
"""
import pytest

pytest.importorskip("PyQt6")

from app.qt import rows, stones, strings, style  # noqa: E402
from app.services import stone_plan  # noqa: E402
from tests.qt.conftest import wait_until  # noqa: E402
from tests.qt.test_current import _settings, _stones_sheet, current, seeded  # noqa: E402,F401 (fixtures)

STAMP = "2026-11-21T10:00:00.000000Z"          # the store's UTC stamp: 21 Nov, wherever the learner is (UTC-10…+13)
LANGUAGES = ("ja", "zh")


@pytest.fixture
def window(qapp, seeded):
    """The window on a Japanese or a Chinese library (a Chinese one opens with its own settings, as the learner's
    would); the harness's theme and language put back after."""
    def make(language="ja", **kw):
        if language == "zh":
            _settings(target_language="zh", zh_script="s")
        return seeded(language=language, **kw)
    yield make
    style.apply(qapp, "night", "M", "ja")


def _row_with(lst, kind):
    """(entry index, row, plan item) of the first Current row whose string holds an item of `kind`."""
    for i, (k, row, _lines) in enumerate(lst.model().entries):
        if k != rows.ROW:
            continue
        for item in stone_plan.plan_of(row).items:
            if item.kind == kind:
                return i, row, item
    return None


def _blits(monkeypatch):
    """Every picture the sheet blits from now on, by name."""
    drawn = []
    real = stones.Sheet.draw
    monkeypatch.setattr(stones.Sheet, "draw", lambda self, p, at, what: drawn.append(what) or real(self, p, at, what))
    return drawn


def _parts(lst, i):
    entry = lst.model().entries[i]
    return lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0)))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_mark_and_its_undo_repaint_only_that_shows_row_and_blit_the_add_once(window, monkeypatch, language):
    """The page marks an episode in play pre-studied, then its toast's Undo: each time the window's look reads that one
    row, rebuilds that row alone (the model's `changed`), paints its picture once and blits the add once (then not at
    all) — Finished's rows and the Goal strip are the same objects."""
    seed, win = window(language)
    lst = current(win)
    fin, dock = win.page_widgets["finished"].list, win.dock
    lst.viewport().repaint()
    renders = lst.delegate.renders
    i, row, item = _row_with(lst, "stone")
    ep = row.episodes[item.index]
    assert not stone_plan.is_pre(ep)
    fin_entries, goal = fin.model().entries, dock.goal
    seed.library.commit(items=[{"id": ep.id, "prestudied_at": STAMP}])
    assert wait_until(lambda: lst.model().entries[i][1] is not row)
    assert lst.model().changed == [i], "that show's row alone"
    marked = lst.model().entries[i][1]
    assert [e.prestudied for e in marked.episodes if e.id == ep.id] == [STAMP]
    assert [it.pre for it in stone_plan.plan_of(marked).items if it.kind == "stone" and it.index == item.index] == [True]
    drawn = _blits(monkeypatch)
    lst.viewport().repaint()
    assert lst.delegate.renders == renders + 1, "its picture painted once, no other row's"
    pres = [w for w in drawn if w[0] == "pre"]
    assert len(pres) == 1 and pres[0][1:3] == (item.state, item.variant % stones.VARIANTS), pres
    assert fin.model().entries is fin_entries and fin.model().changed == [] and dock.goal is goal
    drawn.clear()
    seed.library.commit(items=[{"id": ep.id, "prestudied_at": None}])            # the toast's Undo
    assert wait_until(lambda: lst.model().entries[i][1] is not marked)
    assert lst.model().changed == [i]
    lst.viewport().repaint()
    assert lst.delegate.renders == renders + 2
    assert [w for w in drawn if w[0] == "pre"] == [], "the add gone with the Undo"
    assert not stone_plan.is_pre(lst.model().entries[i][1].episodes[item.index])


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_pre_studied_episode_draws_no_add_and_its_tip_is_as_before(window, language):
    """A library nobody pre-studied: no add blitted on any row, no *Pre-studied* line in any stone's tip, no group or
    ore hover for it."""
    seed, win = window(language)
    lst = current(win)
    for i, (k, row, _l) in enumerate(lst.model().entries):
        if k != rows.ROW:
            continue
        assert not any(it.pre for it in stone_plan.plan_of(row).items)
        for name, _rect, tip, _payload in _parts(lst, i):
            assert name != "pre" and "Pre-studied" not in (tip or "")


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_stones_tip_says_the_day_it_was_pre_studied(window, language):
    """The stone's tip: its name and state, then *✧ Pre-studied on 21 Nov*, then what a click does (unchanged)."""
    seed, win = window(language)
    lst = current(win)
    i, row, item = _row_with(lst, "stone")
    ep = row.episodes[item.index]
    seed.library.commit(items=[{"id": ep.id, "prestudied_at": STAMP}])
    assert wait_until(lambda: lst.model().entries[i][1] is not row)
    tips = [tip for name, _r, tip, payload in _parts(lst, i) if name == "stone" and payload.id == ep.id]
    assert len(tips) == 1
    lines = tips[0].split("\n")
    assert lines[0].startswith(ep.label) and lines[1] == "✧ Pre-studied on 21 Nov"
    assert lines[-1].startswith("• Click to mark it")


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_episode_past_the_twelve_lights_the_ore_and_its_hover_names_it(window, language):
    """An episode past the twelve in play has no stone of its own: the ore carries the sparkle, and its hover names the
    pre-studied episodes in order; a click there opens the row, as its slab's (the window gives no press: D5)."""
    seed, win = window(language, files=2000)
    lst = current(win)
    found = _row_with(lst, "ore")
    assert found is not None, "the 2,000-file seed has a row longer than its twelve"
    i, row, ore = found
    eps = row.episodes[ore.start:ore.start + 2]
    seed.library.commit(items=[{"id": e.id, "prestudied_at": STAMP} for e in eps])
    assert wait_until(lambda: lst.model().entries[i][1] is not row)
    marked = lst.model().entries[i][1]
    lit = [it for it in stone_plan.plan_of(marked).items if it.kind == "ore"]
    assert [it.pre for it in lit] == [tuple(e.label for e in eps)]
    tips = [tip for name, _r, tip, _p in _parts(lst, i) if name == "pre"]
    assert tips == [strings.ROWS_STONE_PRE_NAMES.format(names=" · ".join(e.label for e in eps))]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_whole_show_pre_studied_lights_every_stone_and_the_string_never_moves(window, language):
    """Every file of a show marked: each stone in play carries the add, the ore names the rest — and the string is laid
    out exactly as before (the add hangs outside each stone's box: nothing moves, the title column neither)."""
    seed, win = window(language, files=2000)
    lst = current(win)
    i, row, _ore = _row_with(lst, "ore")
    before = stone_plan.plan_of(row)
    seed.library.commit(items=[{"id": e.id, "prestudied_at": STAMP} for e in row.episodes])
    assert wait_until(lambda: lst.model().entries[i][1] is not row)
    after = stone_plan.plan_of(lst.model().entries[i][1])
    assert all(it.pre for it in after.items)
    assert [it._replace(pre=False if it.kind == "stone" else ()) for it in after.items] == list(before.items)
    for width in (240, 420, 900):
        assert stone_plan.layout(after, width) == stone_plan.layout(before, width)
    assert stone_plan.tightest(after) == stone_plan.tightest(before)
    assert stone_plan.ahead(after) == stone_plan.ahead(before)


def test_one_card_is_one_card_never_one_cards(window):
    """The plural fix (SPEC §1.1): a stone in Anki with one card says *1 card in Anki*; two say *2 cards*."""
    _seed, win = window()
    lst = current(win)
    _i, row, item = _row_with(lst, "stone")
    ep = row.episodes[item.index]._replace(watched=False, status=None)
    assert rows.stone_state(ep._replace(cards=1)) == strings.ROWS_STONE_STATE_ONE == " · 1 card in Anki"
    assert rows.stone_state(ep._replace(cards=2)) == " · 2 cards in Anki"
    assert rows.stone_state(ep._replace(cards=0)) == strings.ROWS_STONE_STATE["rock"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_work_pre_studied_lights_its_row_alone_and_its_hover_names_them(window, monkeypatch, language):
    """A Finished row draws no string: the sparkle sits at its cover's shoulder, and its hover names the pre-studied
    files. Marking two repaints that Finished row alone (Current's rows are the same objects); an Undo takes it off."""
    seed, win = window(language)
    fin = win.page_widgets["finished"].list
    i, row = next((i, e[1]) for i, e in enumerate(fin.model().entries) if e[0] == rows.FINISHED)
    eps = row.episodes[:2]
    cur_entries = current(win).model().entries
    seed.library.commit(items=[{"id": e.id, "prestudied_at": STAMP} for e in eps])
    assert wait_until(lambda: fin.model().entries[i][1] is not row)
    assert fin.model().changed == [i]
    assert rows.finished_pre(fin.model().entries[i][1]) == tuple(e.label for e in eps)
    tips = [tip for name, _r, tip, _p in _parts(fin, i) if name == "pre"]
    assert tips == [strings.ROWS_STONE_PRE_NAMES.format(names=" · ".join(e.label for e in eps))]
    assert current(win).model().entries is cur_entries, "Current untouched"
    marked = fin.model().entries[i][1]
    seed.library.commit(items=[{"id": e.id, "prestudied_at": None} for e in eps])
    assert wait_until(lambda: fin.model().entries[i][1] is not marked)
    assert fin.model().changed == [i] and rows.finished_pre(fin.model().entries[i][1]) == ()
    assert [name for name, *_ in _parts(fin, i) if name == "pre"] == []
