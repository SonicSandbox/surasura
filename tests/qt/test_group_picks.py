"""LM11b review fix round (package B): a group's picks and its episodes' places, and a language switch while the store
is busy — RUNBOOK rows H-B5, H-W2, AD-5 and H-T1 (the real switch).

What a wrong answer would cost a learner: an episode picked inside a row he closed would still be grouped or counted
without being seen (H-B5); a pick from the language he left would light a row of the other language's library and
group its shows (AD-5, picks are keyed p<piece id> and each store numbers its pieces from 1); a drag over an opened
group would work out its episode lines on every move of the hand (H-W2); the language left's settle would keep
ticking after the switch (H-T1). Real Japanese and Chinese fixtures only.
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint                                              # noqa: E402

from app.qt import drag, rows, shell                                         # noqa: E402
from tests.qt.conftest import wait_until                                     # noqa: E402
from tests.qt.test_drag import settle, title_point                                        # noqa: E402
from tests.qt.test_item_menu import (ctrl_click, groupable, lst_of, open_row, rows_of, stone_of,  # noqa: E402,F401
                                     world)
from tests.qt.test_shell_library import _ask, _state, _switched_to, opened   # noqa: E402,F401
from tests.test_library_store_support import migrated                       # noqa: E402
from tests.test_services_moves import LockHolder, short_lock_wait           # noqa: E402,F401


def test_LM11b_H_B5_an_episode_picked_in_a_row_is_let_go_when_the_row_closes_and_its_row_repainted(world):
    """H-B5: Ctrl+click on an opened row's stone picks that episode; closing the row (a click on it, or another row
    opened) lets that pick go — never a hidden pick grouped or counted. A row's own pick stays."""
    _seed, win, _writer = world()
    lst = lst_of(win)
    a, b = groupable(win)
    open_row(win, b)
    r, ep = stone_of(lst, b, 1)
    ctrl_click(lst, r.center())
    key = rows_of(win)[b].key
    assert lst.picked_eps == {(key, ep.id)}
    ctrl_click(lst, title_point(lst, a))       # a row's own pick, beside it
    picked_row = rows_of(win)[a].key
    lst.toggle(lst.model().index(b, 0))                                      # the row closes
    settle()
    assert lst.model().open_key is None and lst.picked_eps == set()
    assert picked_row in lst.picked_rows
    open_row(win, b)
    r, ep = stone_of(lst, b, 1)
    ctrl_click(lst, r.center())
    assert lst.picked_eps == {(key, ep.id)}
    other = next(i for i, e in enumerate(lst.model().entries) if i != b and getattr(e[1], "key", None) != key and
                 e[0] == lst.model().entries[b][0])
    lst.toggle(lst.model().index(other, 0))                                  # another row opened: this one closes
    settle()
    assert lst.picked_eps == set()


def test_LM11b_H_W2_episode_at_works_out_an_opened_rows_episode_lines_once_while_its_rect_and_row_stay(world,
                                                                                                    monkeypatch):
    """H-W2 (S19): a drag over an opened group asks `episode_at` on every move of the hand; the row's episode lines are
    worked out once while its rect and row object are the same, and again only when either changes."""
    _seed, win, _writer = world()
    lst = lst_of(win)
    _a, b = groupable(win)
    open_row(win, b)
    delegate = lst.delegate
    built = []
    real = delegate._episode_rows
    monkeypatch.setattr(delegate, "_episode_rows", lambda *a, **k: (built.append(1), real(*a, **k))[1])
    entry = lst.model().entries[b]
    assert entry[0] == rows.ROW
    rect = lst.visualRect(lst.model().index(b, 0))
    r, ep = real(entry[1], delegate._open_area(rect, delegate.slab_of(rect)))[1]     # its second episode's line
    built.clear()
    for dy in range(0, 6):
        assert delegate.episode_at(entry, rect, r.center() + QPoint(0, dy // 3)) is ep
    assert len(built) == 1
    delegate.episode_at(entry, rect.adjusted(0, 0, 0, 40), r.center())       # its rect changed: worked out again
    assert len(built) == 2
    moved = (entry[0], entry[1]._replace(title=entry[1].title + " "), entry[2])
    delegate.episode_at(moved, rect.adjusted(0, 0, 0, 40), r.center())      # another row object: again
    assert len(built) == 3


def test_LM11b_AD5_and_H_T1_a_language_switch_during_a_busy_store_lets_the_picks_go_and_stops_the_old_settle(
        opened, short_lock_wait, monkeypatch):
    """AD-5: the picks are let go when the store and its view are replaced (a language switch) — the next language's
    rows can carry the same keys (each store numbers its pieces from 1). H-T1: the language left's controller, its move
    still waiting for a busy store, stops its settle as the switch lets it go (its writer stopped, the move kept in its
    journal) — never a timer ticking on, never a view of the language left shown after."""
    ja, zh = migrated("ja"), migrated("zh")
    services, win = opened()
    assert wait_until(lambda: _state(win) == "full" and services.writer._thread is not None, 15)
    monkeypatch.setattr(shell, "QUIT_FINISH_WAIT", 1.0)
    closed = []
    real_close = drag.DragController.close

    def close(self):
        real_close(self)
        closed.append((self, self._settle.isActive()))
    monkeypatch.setattr(drag.DragController, "close", close)
    old, old_writer = win.moves, services.writer
    lst = lst_of(win)
    rs = rows_of(win)
    assert lst.pick_row(rs[1]) and lst.pick_row(rs[2])
    holder = LockHolder(ja.db_path)
    try:
        old.nudge(rs[3], -1)                         # the window's order ahead of a busy store, its settle running
        assert old_writer.pending() == 1 and old.expect is not None
        _ask(services, win, "zh")
        assert _switched_to(win, services, "zh", 30)
        assert old_writer.stopped() and old_writer.pending() == 1      # kept in the journal for its next open
    finally:
        holder.release()
    assert [(c[0] is old, c[1]) for c in closed] == [(True, False)]
    assert lst_of(win) is lst and not lst.picked_rows and not lst.picked_eps
    time.sleep(0.3)
    settle(200)
    assert win.page_widgets["current"].view_model.language == "zh"
    ja.close()
    zh.close()
