"""Alpha 4's review round on New arrivals (fix-t: A4A-3, A4A-4, A4A-5, IK-6): the tray's picks and its first open at
20,000 arrivals, the numbers across a language switch, and a split title's rows keeping their own keys — real Japanese
and Chinese titles, the tray offscreen from `view_rows.build` and in the window on its seed.

What a wrong answer would cost a learner:
  * Ctrl+A or Esc on a big tray freezing the window for seconds (it was 1.9 s at 20,000, both ways);
  * a first open at 20,000 that shows nothing for a long step, with no sign that it is coming;
  * a Japanese file's *N new* shown on a Chinese arrival after a switch (item ids repeat across libraries);
  * a pick that jumps to another part of a split title when the first part is placed, so the next action moves a
    part nobody picked — or a pick that silently drops.
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import arrivals, strings
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_arrivals import (SERIES, _series_items, open_tray, settle, tray_of, tray_rows,  # noqa: F401
                                    world)

TITLES = {"ja": ("進撃の巨人", "鬼滅の刃", "葬送のフリーレン", "ぼっち・ざ・ろっく！"),
          "zh": ("三体", "活着", "围城", "红楼梦")}


def big_view(n, language="ja"):
    """`n` arrivals, one file each, each its own title (a big library pointed at: everything in New arrivals)."""
    names = TITLES[language]
    items = {k: {"id": k, "tier": "arrivals", "ord": float(k), "work_id": 10_000 + k, "piece_id": None,
                 "rel_path": f"HighPriority/{names[k % 4]}{k}/第01話.srt", "parent_folder": f"{names[k % 4]}{k}",
                 "added_at": "2026-10-20T10:00:00Z"} for k in range(1, n + 1)}
    works = {10_000 + j: {"id": 10_000 + j, "title": f"{names[j % 4]}{j}", "media_type": "anime"}
             for j in range(n + 1)}
    return view_rows.build(items, works, {"arrivals_on": 1}, language=language)


class _Win:
    moves = None
    dock = None


@pytest.fixture
def bare_tray(qapp):
    """A tray on a parent of its own (no window): what the window's thread does with its rows, timed alone."""
    made = []

    def make(view):
        parent = QWidget()
        parent.resize(1200, 900)
        parent.show()
        inset = arrivals.ArrivalsInset(parent)
        inset.show()
        tray = arrivals.ArrivalsTray(parent, inset, _Win())
        tray.set_groups(view.arrival_groups)
        made.append(parent)
        return tray
    yield make
    for parent in made:
        parent.close()
        parent.deleteLater()


def _filled(tray, n):
    assert wait_until(lambda: not getattr(tray, "filling", lambda: False)() and len(tray.keys()) == n, 20)
    for _ in range(5):
        QApplication.processEvents()


def _ms(fn):
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


# --- A4A-3: picks at 20,000 ---------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_ctrl_a_and_letting_the_picks_go_on_20000_arrivals_each_take_one_frame_at_most(bare_tray, language):
    # A4A-3: each pick repainted by a linear search of the rows' keys — 1.9 s on the window's thread at 20,000, for
    # Ctrl+A and again for Esc (and a plain click, every picks action, a drag's start).
    tray = bare_tray(big_view(20_000, language))
    tray.open()
    _filled(tray, 20_000)
    took = _ms(tray.pick_all)
    assert len(tray.picks) == 20_000 and len(tray.picked()) == 20_000
    cleared = _ms(tray.clear_picks)
    assert tray.picks == set()
    keys = tray.keys()
    tray.pick(keys[10])
    ranged = _ms(lambda: tray.pick_range(keys[15_010]))               # Shift+click 15,000 rows down
    assert len(tray.picks) == 15_001
    print(f"20k: Ctrl+A {took:.1f} ms, clear {cleared:.1f} ms, Shift range {ranged:.1f} ms")
    assert took <= 16 and cleared <= 16 and ranged <= 16


def test_a_few_picks_still_repaint_only_their_own_rows(bare_tray):
    # (the one-repaint path is for many rows only: a Ctrl+click on a big tray repaints that row, never the list)
    tray = bare_tray(big_view(2_000))
    tray.open()
    _filled(tray, 2_000)
    asked = []
    real = tray.view.update_key
    tray.view.update_key = lambda key: (asked.append(key), real(key))
    whole = []
    vp = tray.view.viewport()
    real_update = vp.update
    vp.update = lambda *a: (whole.append(a), real_update(*a))
    try:
        k = tray.keys()[3]
        tray.pick(k)
        assert asked == [k] and whole == []
        tray.pick_all()
        assert len(whole) == 1                                        # many: one repaint of what shows
    finally:
        tray.view.update_key = real
        vp.update = real_update


# --- IK-6: the first open at 20,000 shows at once ------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_first_open_of_20000_arrivals_shows_at_once_with_a_loading_line_and_fills_in_short_steps(bare_tray,
                                                                                                     language):
    # IK-6: the tray's first open made its 20,000 rows in one step (52 ms here, 195 ms at 60k; a laptop 2–3×) with
    # nothing on screen meanwhile. It shows at once with the rows a screen needs, says *Loading…*, and fills in steps.
    tray = bare_tray(big_view(20_000, language))
    first = _ms(tray.open)
    loading = getattr(tray, "loading", None)
    assert loading is not None and loading.isVisible() and loading.text() == strings.TRAY_LOADING
    assert 0 < len(tray.model.keys) < 20_000                          # a screen's rows, the rest to come
    steps = []
    end = time.perf_counter() + 20
    while tray.filling() and time.perf_counter() < end:
        steps.append(_ms(QApplication.processEvents))
    assert not tray.filling() and len(tray.keys()) == 20_000
    assert not loading.isVisible()
    steps.sort()
    median = steps[len(steps) // 2] if steps else 0
    print(f"20k first open: {first:.1f} ms, then {len(steps)} steps, median {median:.1f} ms, longest "
          f"{max(steps or [0]):.1f} ms")
    assert first <= 16
    assert median <= 8                                                # the brief's 4 ms steps (a shared machine)
    shown = [a.key for g in tray.groups for a in g.rows]
    assert tray.keys() == shown                                       # every row, in the view's order


def test_a_view_landing_while_the_tray_fills_is_what_the_filled_tray_shows(bare_tray):
    tray = bare_tray(big_view(20_000))
    tray.open()
    assert tray.filling()
    newer = big_view(19_000)                                          # a placement of 1,000 lands mid-fill
    tray.set_groups(newer.arrival_groups)
    _filled(tray, 19_000)
    assert not tray.filling()
    assert tray.keys() == [a.key for g in newer.arrival_groups for a in g.rows]
    assert tray.model.keys[0] == arrivals.HEAD + "new"
    assert tray.view.indexWidget(tray.model.index(0, 0)) is tray.heads["new"][0]


def test_ctrl_a_while_the_tray_fills_picks_every_arrival_not_only_the_rows_made_so_far(bare_tray):
    tray = bare_tray(big_view(20_000))
    tray.open()
    assert tray.filling()
    tray.pick_all()
    assert len(tray.picks) == 20_000 and len(tray.picked()) == 20_000


def test_a_small_tray_is_whole_in_the_press_and_never_says_loading(bare_tray):
    tray = bare_tray(big_view(12))
    tray.open()
    assert not tray.filling() and len(tray.keys()) == 12
    assert tray.loading.isHidden()


# --- A4A-4: a hand-on waiting on its timer never crosses a language switch ---------------------------------------- #
class _Later:
    def __init__(self):
        self.waiting = []

    def __call__(self, seconds, fn):
        self.waiting.append(fn)

    def run(self):
        held, self.waiting = self.waiting, []
        for fn in held:
            fn()


def _switching_numbers(tmp_path):
    lang, handed, later, now = ["ja"], [], _Later(), [100.0]
    known = tmp_path / "KnownWord.json"
    known.write_text('{"words": ["猫"]}', encoding="utf-8")
    nums = arrivals.ArrivalNumbers(None, lambda: lang[0], on_change=lambda d: handed.append((lang[0], dict(d))),
                                   data_path=str(tmp_path / "d"), known_file=str(known), plan_token=lambda: 1,
                                   run=lambda fn: fn(), later=later, clock=lambda: now[0])
    return nums, lang, handed, later, now


def test_a_japanese_hand_on_waiting_on_its_timer_is_dropped_when_the_window_switches_to_chinese(tmp_path):
    # A4A-4: the 250 ms wait let a ja hand-on go out after a switch, to the zh reader: ja item ids in the zh view
    # (ids repeat across stores, so a zh arrival showed a ja file's *N new*).
    nums, lang, handed, later, now = _switching_numbers(tmp_path)
    ans = {"n_new_top": 7, "plan": "p"}
    nums._answer(101, False, "k", ans, "ja")                          # handed at once
    now[0] += 0.1
    nums._answer(102, False, "k", ans, "ja")                          # within 250 ms: waits for its timer
    assert later.waiting
    lang[0] = "zh"                                                    # the learner switches to Chinese
    now[0] += 0.2
    later.run()                                                       # the timer fires
    assert handed == [("ja", {101: 7})]                               # nothing of Japanese reaches the zh reader
    assert nums.estimates() == {}
    nums._answer(101, False, "k", {"n_new_top": 3, "plan": "p"}, "zh")   # zh's own answer, same id, same signature
    now[0] += 1
    later.run()
    assert handed[-1] == ("zh", {101: 3})                             # zh's alone, never merged with ja's


def test_after_a_switch_a_chinese_arrival_whose_id_a_japanese_file_had_is_still_asked(tmp_path):
    # (the same class: the asks were remembered by item id alone — a zh arrival with an id ja asked was never asked)
    from tests.qt.test_arrivals import FakeWorker
    worker = FakeWorker(n=5)
    nums, lang, handed, later, now = _switching_numbers(tmp_path)
    nums._client = worker
    ja = big_view(3, "ja").arrivals
    zh = big_view(3, "zh").arrivals
    assert {i for a in ja for i in a.item_ids} == {i for a in zh for i in a.item_ids}
    nums.want(ja)
    assert wait_until(lambda: nums.answers == 3, 3)
    lang[0] = "zh"
    nums.want(zh)
    assert wait_until(lambda: len(worker.asked) == 6 and nums.answers == 6, 3)
    now[0] += 1
    later.run()
    assert handed[-1][0] == "zh" and set(handed[-1][1]) == {i for a in zh for i in a.item_ids}


# --- A4A-5: a split title's rows keep their keys -------------------------------------------------------------------- #
def _split_view(language, gone=()):
    items, works = _series_items(language, 1, split=True)
    rows = {r["id"]: dict(r) for r in items if r["id"] not in gone}
    return view_rows.build(rows, {w["id"]: w for w in works}, {"arrivals_on": 1}, language=language)


def _run_keys(view, language):
    series = SERIES[language][0]
    return {a.item_ids: a.key for a in view.arrivals if a.title == series}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_split_titles_other_runs_keep_their_keys_when_one_run_is_placed(language):
    before = _run_keys(_split_view(language), language)
    assert len(before) == 3 and len(set(before.values())) == 3
    first_run = min(before)                                           # part 1's files
    after = _run_keys(_split_view(language, gone=first_run), language)
    assert set(after) == set(before) - {first_run}
    assert all(after[ids] == before[ids] for ids in after)            # parts 2 and 3: the same keys
    assert before[first_run] not in after.values()                    # and part 1's key names nothing now


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_pick_on_part_2_stays_on_part_2_and_part_1s_never_moves_onto_another_part(world, language):
    # A4A-5: the first run of a piece took `p<piece>`, so when it left the next run took that key — a pick on part 1
    # landed on part 2 (moved by the next picks action), and a pick on part 2 silently dropped.
    seed, win, writer = world(language)
    base = max(r["id"] for r in seed.library.items()) + 1
    items, works = _series_items(language, base, split=True)
    seed.library.commit(works=works, items=items, order=True)
    assert wait_until(lambda: sum(len(g.rows) for g in tray_of(win).groups) == 9, 5)
    tray = open_tray(win)
    settle()
    series = SERIES[language][0]
    runs = sorted((r for r in tray_rows(win) if r.arrival.title == series), key=lambda r: r.arrival.item_ids)
    part1, part2 = runs[0], runs[1]
    tray.pick(part1.key)
    tray.pick(part2.key)
    placed = set(part1.arrival.item_ids)
    tray.act(part1.arrival, "goal")                                   # the row's own ⋯ › Goal (picks kept)
    assert wait_until(lambda: not any(placed & set(a.item_ids) for g in tray.groups for a in g.rows), 5)
    settle()
    assert part2.key in tray.keys() and tray.picks == {part2.key}     # part 2's pick where it was, part 1's gone
    [row] = [r for r in tray_rows(win) if r.key == part2.key]
    assert row.arrival.item_ids == part2.arrival.item_ids              # the row still shows part 2
