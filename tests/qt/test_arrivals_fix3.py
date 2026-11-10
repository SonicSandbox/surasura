"""Alpha 4's last round on New arrivals (fix3, the smoothness verifier's findings 6 and 7): one more arrival with the
tray open costs what the arrival needs, never the tray's size; Ctrl+A copies the rows' set; the first open paints its
screen of rows in a turn of its own and puts the rest on under what shows without repainting a row — real Japanese and
Chinese titles, the tray offscreen on a parent of its own, its views from `view_rows.build` with the reader's cache.

What a wrong answer would cost a learner:
  * an episode landing while the tray is open at 20,000 arrivals stalling the window 7–12 ms (27–36 at 60,000) — every
    row laid out again and every row's key read on the window's thread;
  * the tray's rows repainted for rows put on far under the ones on screen (a flicker of work for nothing, S19), and a
    first open whose paint shares a turn with the next rows' work;
  * a picked row losing its pick when the reader moves it (a newer file of the same title).
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import arrivals
from app.services import view_rows
from tests.qt.test_arrivals_a4_fix import _counting_paints, _filled, bare_tray  # noqa: F401

TITLES = {"ja": ("進撃の巨人", "鬼滅の刃", "葬送のフリーレン", "ぼっち・ざ・ろっく！"),
          "zh": ("三体", "活着", "围城", "红楼梦")}


class Library:
    """`n` arrivals, one file each, each its own title, the newest first; views built with the reader's cache, so an
    unchanged row stays the same object between builds (as the reader hands them to the window)."""

    def __init__(self, n, language="ja"):
        names = TITLES[language]
        self.language = language
        self.items = {k: {"id": k, "tier": "arrivals", "ord": float(k), "work_id": 10_000 + k, "piece_id": None,
                          "rel_path": f"HighPriority/{names[k % 4]}{k}/第01話.srt", "parent_folder": f"{names[k % 4]}{k}",
                          "added_at": f"2026-10-{1 + k % 27:02d}T{k % 24:02d}:00:00Z"} for k in range(1, n + 1)}
        self.works = {10_000 + k: {"id": 10_000 + k, "title": f"{names[k % 4]}{k}", "media_type": "anime"}
                      for k in range(1, n + 1)}
        self.cache = view_rows.RowCache()
        self.view = self.build()

    def build(self, changed=None, changed_works=None):
        self.view = view_rows.build(self.items, self.works, {"arrivals_on": 1}, cache=self.cache, changed=changed,
                                    changed_works=changed_works, language=self.language)
        return self.view

    def arrive(self, k, at="2026-10-30T00:00:00Z"):
        """A new title's first file, newer than every other (the top of *New*)."""
        names = TITLES[self.language]
        item_id, wid = 900_000 + k, 990_000 + k
        self.items = dict(self.items)
        self.items[item_id] = dict(self.items[1], id=item_id, work_id=wid, added_at=at, ord=-float(item_id),
                                   rel_path=f"HighPriority/{names[k % 4]}新{k}/第01話.srt",
                                   parent_folder=f"{names[k % 4]}新{k}")
        self.works = dict(self.works)
        self.works[wid] = {"id": wid, "title": f"{names[k % 4]}新{k}", "media_type": "anime"}
        return self.build(changed={item_id}, changed_works={wid})

    def newer(self, item_id, at):
        """A file of the library given a newer stamp: its row moves up in *New*."""
        self.items = dict(self.items)
        self.items[item_id] = dict(self.items[item_id], added_at=at)
        return self.build(changed={item_id}, changed_works={self.items[item_id]["work_id"]})


def _one_arrival_ms(make_tray, n, language):
    lib = Library(n, language)
    tray = make_tray(lib.view)
    tray.open()
    _filled(tray, n)
    took = []
    for k in range(5):
        view = lib.arrive(k)
        t = time.perf_counter()
        tray.set_groups(view.arrival_groups)
        took.append((time.perf_counter() - t) * 1000)
        for _ in range(3):
            QApplication.processEvents()
        assert tray.keys()[0] == view.arrival_groups[0].rows[0].key        # the arrival is the top row
    assert len(tray.keys()) == n + 5
    took.sort()
    return took[2]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_one_arrival_with_the_tray_open_costs_about_the_same_at_20000_arrivals_as_at_2000(bare_tray, language):
    # finding 6: an arrival laid every row of the list out again and read every row's key on the window's thread —
    # 7–12 ms at 20,000 against ~1 at 2,000. A table's insert costs the rows inserted; the keys come from the reader.
    small = _one_arrival_ms(bare_tray, 2_000, language)
    big = _one_arrival_ms(bare_tray, 20_000, language)
    print(f"one arrival, tray open: 2k {small:.2f} ms, 20k {big:.2f} ms (median of 5)")
    assert big <= 3 * small + 2.0, (small, big)


def test_the_reader_hands_each_group_its_rows_keys_in_order():
    # (what the tray copies instead of reading 20,000 rows' keys on the window's thread)
    for language in ("ja", "zh"):
        lib = Library(50, language)
        view = lib.arrive(1)
        for g in view.arrival_groups:
            assert g.keys == tuple(a.key for a in g.rows) and len(g.keys) == len(g.rows)


def test_a_fill_puts_its_rows_on_under_the_screen_without_repainting_a_row(bare_tray, monkeypatch):
    # finding 7 / S19: the fill's rows land under the rows on screen — nothing the learner sees moved, so no row is
    # drawn again (the old fill put every row on in one insert at the end, which repainted the whole list)
    drawn = _counting_paints(monkeypatch)
    lib = Library(20_000)
    tray = bare_tray(lib.view)
    tray.open()
    QApplication.processEvents()                                      # the screen of rows, painted once
    assert tray.filling() and drawn[0] > 0
    on_screen = drawn[0]
    end = time.perf_counter() + 20
    rows_seen = set()
    while tray.filling() and time.perf_counter() < end:
        QApplication.processEvents()
        rows_seen.add(len(tray.model.keys))
    for _ in range(5):
        QApplication.processEvents()
    assert not tray.filling() and len(tray.keys()) == 20_000
    assert len(rows_seen) > 2                                         # the rows came on in steps, not one insert
    assert drawn[0] == on_screen, drawn[0] - on_screen               # and not one row was drawn again


def test_the_first_open_paints_its_screen_of_rows_in_a_turn_without_the_fills_work(bare_tray):
    # finding 7: the press's paint and the fill's first step shared one turn (21–22 ms); the steps start a frame after
    made = []
    lib = Library(20_000, "zh")
    tray = bare_tray(lib.view)
    real = tray.model.make
    tray.model.make = lambda keys, objs: (made.append(len(keys)), real(keys, objs))[1]
    tray.open()
    assert tray.filling() and made == [arrivals.FIRST_ROWS]           # the press: a screen's rows only
    made.clear()
    QApplication.processEvents()                                      # the turn that paints them
    assert made == [], made
    _filled(tray, 20_000)
    assert sum(made) == 20_000 + 1 - arrivals.FIRST_ROWS             # the rest made after (a head and 20,000 rows)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_picked_row_the_reader_moves_keeps_its_pick_and_a_row_that_leaves_lets_go(bare_tray, language):
    # (the picks now let go by the rows removed, never a set of every row: a row removed and put back elsewhere — a
    # newer file moving its title up — is the same pick)
    lib = Library(30, language)
    tray = bare_tray(lib.view)
    tray.open()
    _filled(tray, 30)
    keys = tray.keys()
    low, other = keys[20], keys[25]
    tray.pick(low)
    tray.pick(other)
    [moved] = [a for a in lib.view.arrivals if a.key == low]
    tray.set_groups(lib.newer(moved.item_ids[0], "2026-10-31T00:00:00Z").arrival_groups)
    assert tray.keys()[0] == low and tray.picks == {low, other}      # moved to the top, still picked
    gone = [a for a in lib.view.arrivals if a.key == other][0]
    lib.items = {k: v for k, v in lib.items.items() if k not in gone.item_ids}
    tray.set_groups(lib.build(changed=set(gone.item_ids)).arrival_groups)
    assert other not in tray.keys() and tray.picks == {low}          # placed: its pick let go


@pytest.mark.parametrize("n", [2_000, 20_000])
def test_ctrl_a_then_an_arrival_keeps_every_pick_and_never_picks_the_heads(bare_tray, n):
    lib = Library(n)
    tray = bare_tray(lib.view)
    tray.open()
    _filled(tray, n)
    tray.pick_all()
    assert len(tray.picks) == n and not any(k.startswith(arrivals.HEAD) for k in tray.picks)
    tray.set_groups(lib.arrive(1).arrival_groups)
    assert len(tray.picks) == n and len(tray.picked()) == n           # the new arrival isn't picked; none let go
