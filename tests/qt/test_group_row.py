"""A group row is hand-made (LM11b G1, RUNBOOK row G1): never a split's first part (`drag.split_first`) and never one of
a title's other parts on *Join with…* (`item_menu.ItemActions.other_parts`) — though its `work_id` is its first show's.

What a wrong answer would cost a learner: a group holding a show's first episodes would light Finished unlit for that
show's later part ("finish the first part first"), or *Join with…* would offer to pour a whole group of other shows into
one show's part. Rows built by `view_rows.build` from hand-made feed rows with the fixtures' Japanese titles.
"""
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from app.qt import drag, item_menu                                     # noqa: E402
from app.services import view_rows as vr                               # noqa: E402
from tests.test_view_rows import WORKS, _works, eps, items_of           # noqa: E402,F401


def _view(group_first=True):
    """星降る街の小さな工房 Ep 1–2 inside a group with 雲の上の郵便屋さん (piece 10), and its Ep 3–4 as a run of its own
    (piece 11) — the group above the run, or below it."""
    group = [("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("now", 2, 10, eps("雲の上の郵便屋さん", 1, 2), {})]
    run = [("now", 1, 11, eps("星降る街の小さな工房", 3, 4), {})]
    items = items_of(group + run if group_first else run + group)
    pieces = {10: {"id": 10, "title": None, "kind": "group"}, 11: {"id": 11, "title": None, "kind": "run"}}
    return vr.build(items, WORKS, {"mine_line": 20}, pieces=pieces)


@pytest.mark.parametrize("group_first", (True, False))
def test_LM11b_G1_a_group_is_never_a_splits_first_part_nor_makes_its_first_shows_part_one(group_first):
    """The group's work_id is its first show's: read as a part, it would make the show's own run look split."""
    view = _view(group_first)
    group = next(r for r in view.rows if r.group)
    run = next(r for r in view.rows if not r.group)
    assert group.work_id == run.work_id == 1
    assert not drag.split_first(view.rows, group) and not drag.split_first(view.rows, run)


def test_LM11b_G1_join_with_never_lists_a_group_and_a_group_lists_no_other_part():
    """*Join with…* joins a title's parts: a group is none of them, and a group offers none."""
    view = _view()
    actions = SimpleNamespace(_view=lambda: view)
    group = next(r for r in view.rows if r.group)
    run = next(r for r in view.rows if not r.group)
    assert item_menu.ItemActions.other_parts(actions, run) == []
    assert item_menu.ItemActions.other_parts(actions, group) == []


def test_LM11b_G1_a_group_moved_to_goal_counts_one_more_title_at_once_with_its_cover_once():
    """`drag.without`'s quick update (the reader's next view says the same): a group is a title of its own even when
    its first show already has a tile in 6+ Months, and its cover goes on the strip once."""
    items = items_of([("now", 1, 10, eps("星降る街の小さな工房", 1, 2), {}), ("now", 2, 10, eps("雲の上の郵便屋さん", 1, 2), {}),
                      ("goal", 1, 11, eps("星降る街の小さな工房", 3, 4), {})])
    pieces = {10: {"id": 10, "title": None, "kind": "group"}, 11: {"id": 11, "title": None, "kind": "run"}}
    view = vr.build(items, WORKS, {"mine_line": 20}, pieces=pieces)
    assert (view.goal.titles, view.goal.covers) == (1, ("星降る街の小さな工房",))
    after = drag.without(view, "p10", "goal")
    assert (after.goal.titles, after.goal.files, after.counts.goal_titles) == (2, 6, 2)
    assert after.goal.covers == ("星降る街の小さな工房",) and after.goal.line == "2 titles · 6 files"
    run = vr.build(items_of([("now", 1, 12, eps("星降る街の小さな工房", 1, 2), {}),
                             ("goal", 1, 11, eps("星降る街の小さな工房", 3, 4), {})]), WORKS, {"mine_line": 20})
    assert drag.without(run, "p12", "goal").goal.titles == 1          # a show's part joins its own title, as before
