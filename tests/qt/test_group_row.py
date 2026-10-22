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


# --- an opened group's show lines: each show's episodes under its name -------------------------------------------- #
# What a wrong answer would cost a learner: an opened group read "Ep 1, Ep 2, Ep 3, Ep 1, Ep 2" with nothing saying
# where one show ends; and a show line out of step with the lines the list hit-tests would put a click, a drop, the ✂
# seam or the top-20 line on the wrong episode. A run, and a group of one show, look exactly as before.
SHOW_A, SHOW_B = "星降る街の小さな工房", "雲の上の郵便屋さん"


def _shows_rows():
    """{name: Row}: a group of two shows (piece 10: A Ep 1–3, B Ep 1–2), a run of one show (piece 11: 白銀の書庫番
    Ep 1–5, as many episodes as the group) and a group of one show (piece 12: B Ep 3–4) — built by
    `view_rows.build`, as the reader does."""
    spec = [("now", 1, 10, eps(SHOW_A, 1, 3), {}), ("now", 2, 10, eps(SHOW_B, 1, 2), {}),
            ("now", 3, 11, eps("白銀の書庫番", 1, 5), {}), ("now", 2, 12, eps(SHOW_B, 3, 4), {})]
    pieces = {10: {"id": 10, "title": None, "kind": "group"}, 11: {"id": 11, "title": None, "kind": "run"},
              12: {"id": 12, "title": None, "kind": "group"}}
    view = vr.build(items_of(spec), WORKS, {"mine_line": 20}, pieces=pieces)
    by = {r.piece_id: r for r in view.rows}
    return {"group": by[10], "run": by[11], "one": by[12]}


@pytest.fixture
def show_list(qapp):
    """A painted list of its own (no store) holding `entries`, shown offscreen, the row `key` opened."""
    from PyQt6.QtWidgets import QApplication, QWidget
    from app.qt import rows
    made = []

    def make(entries, key):
        host = QWidget()
        host.resize(1100, 1200)
        lst = rows.RowsView("Current", parent=host)
        lst.resize(1100, 1200)
        host.show()
        lst.set_entries(entries)
        i = next(n for n, e in enumerate(entries) if e[1].key == key)
        lst.toggle(lst.model().index(i, 0))
        for _ in range(10):
            QApplication.processEvents()
        assert lst.model().open_key == key
        made.append(host)
        return lst, i
    yield make
    for host in made:
        host.close()


def _ordered_under_their_shows(lst, i, row):
    """The opened row's show lines and episode lines, checked against each other: -> (shows, episode lines, its rect,
    its entry)."""
    entry = lst.model().entries[i]
    rect = lst.visualRect(lst.model().index(i, 0))
    eps_ = lst.delegate.episode_lines(entry, rect)
    shows = lst.delegate.show_lines(entry, rect)
    assert [ep for _r, ep in eps_] == list(row.episodes)                # episodes only, every one, in order
    starts = [k for k, (_r, ep) in enumerate(eps_) if k == 0 or ep.work_id != eps_[k - 1][1].work_id]
    assert [s for _r, s in shows] == [SHOW_A, SHOW_B] and starts == [0, 3]
    for (sr, _s), k in zip(shows, starts):
        assert sr.bottom() + 1 == eps_[k][0].top()                      # right above its show's first episode
        if k:
            assert eps_[k - 1][0].bottom() + 1 == sr.top()              # right under the run before
    return shows, eps_, rect, entry


@pytest.mark.parametrize("f", (1.0, 1.5))
def test_an_opened_group_shows_each_shows_name_above_its_own_episodes_and_its_height_is_their_sum(show_list,
                                                                                                  monkeypatch, f):
    """Two show lines, in order, each above its own episodes; the opened height is exactly the lines laid out (the
    head, 4 px, the episodes and the show lines, the pad, the gap) — at the text factor 1.0 and 1.5."""
    from app import theme
    from app.qt import rows
    monkeypatch.setattr(rows, "fz", lambda: f)
    rs = _shows_rows()
    group = rs["group"]
    assert group.group and [e.show for e in group.episodes] == [SHOW_A] * 3 + [SHOW_B] * 2
    lst, i = show_list([(rows.HERO, rs["one"], ()), (rows.ROW, group, ()), (rows.ROW, rs["run"], ())], group.key)
    shows, eps_, rect, entry = _ordered_under_their_shows(lst, i, group)
    d = lst.delegate
    slab = d.slab_of(rect)
    laid = eps_[-1][0].bottom() + 1 - (slab.bottom() + 1)              # from under the head to the last episode's foot
    assert laid == 4 + 5 * round(theme.SIZES["episode-row"] * f) + 2 * round(rows.rl("show-line") * f)
    assert laid == d._episodes_h(group) and laid > d.stand_h()
    assert rect.height() == d._line_h() + laid + rows.rl("open-pad") + rows.rl("gap")
    for sr, _s in shows:                                               # a show line is no episode: nothing hit there
        assert d.episode_at(entry, rect, sr.center()) is None
        assert sr.height() == round(rows.rl("show-line") * f)
    for r, ep in eps_:
        assert d.episode_at(entry, rect, r.center()) is ep
    run_at = next(n for n, e in enumerate(lst.model().entries) if e[1] is rs["run"])
    lst.toggle(lst.model().index(run_at, 0))           # a run of as many episodes opened next: the group's height,
    assert lst.model().open_key == rs["run"].key        # kept by shape, is never its height (`_shape` counts shows)
    assert lst.visualRect(lst.model().index(run_at, 0)).height() == \
        d._line_h() + 4 + 5 * round(theme.SIZES["episode-row"] * f) + rows.rl("open-pad") + rows.rl("gap")


def test_a_run_and_a_group_of_one_show_open_exactly_as_before(show_list):
    """No show line, and every episode where it always stood: 4 px under the head, one `episode-row` each."""
    from app import theme
    from app.qt import rows
    rs = _shows_rows()
    assert not rs["one"].group                                          # a group of one show reads as its show
    for name in ("run", "one"):
        row = rs[name]
        lst, i = show_list([(rows.HERO, rs["group"], ()), (rows.ROW, row, ())], row.key)
        entry = lst.model().entries[i]
        rect = lst.visualRect(lst.model().index(i, 0))
        d = lst.delegate
        assert rows.show_starts(row) == {} and d.show_lines(entry, rect) == []
        top, h = d.slab_of(rect).bottom() + 1 + 4, round(theme.SIZES["episode-row"] * rows.fz())
        assert [r.top() for r, _ep in d.episode_lines(entry, rect)] == [top + k * h for k in range(len(row.episodes))]
        assert d._episodes_h(row) == 4 + len(row.episodes) * h


def test_the_seam_between_two_shows_sits_above_the_second_shows_line_and_splits_there(show_list):
    """W3.2 Q8: the ✂ seam where one show's run ends is under its last episode, above the next show's line — and a
    seam inside a show still sits between its two episodes; each splits before the episode it names."""
    from app.qt import rows
    rs = _shows_rows()
    group = rs["group"]
    lst, i = show_list([(rows.HERO, rs["run"], ()), (rows.ROW, group, ())], group.key)
    shows, eps_, rect, entry = _ordered_under_their_shows(lst, i, group)
    seams = {p[3].id: p for p in lst.delegate.parts(entry, rect) if p[0] == "seam"}
    assert set(seams) == {ep.id for _r, ep in eps_[1:]}
    between = seams[eps_[3][1].id][1]
    assert between.center().y() in (shows[1][0].top(), shows[1][0].top() - 1)    # on the line between the two shows
    inside = seams[eps_[1][1].id][1]
    assert inside.center().y() in (eps_[1][0].top(), eps_[1][0].top() - 1)
    hit = lst.part_at(between.center())[1]
    assert hit[0] == "seam" and hit[3] is eps_[3][1]
    assert vr.split_piece(group, 3) == (group.piece_id, 3)            # the split goes where B's run starts


def test_up_next_as_a_group_shows_its_show_lines_too(show_list):
    """The hero card opened on a group: the same show lines above each show's episodes, its height their sum."""
    from app.qt import rows
    rs = _shows_rows()
    group = rs["group"]
    lst, i = show_list([(rows.HERO, group, ()), (rows.ROW, rs["run"], ())], group.key)
    shows, eps_, rect, entry = _ordered_under_their_shows(lst, i, group)
    d = lst.delegate
    assert rect.height() == d._hero_head_h() + d._episodes_h(group) + 14 + rows.rl("hero-below")
    assert eps_[-1][0].bottom() + 1 - d._hero_geometry(group, rect)["eps"].top() == d._episodes_h(group)
    assert d.episode_at(entry, rect, shows[1][0].center()) is None
    assert d.episode_at(entry, rect, eps_[3][0].center()) is eps_[3][1]


@pytest.mark.parametrize("dpr", (1.0, 1.5))
def test_the_show_lines_paint_each_name_in_its_line_and_the_top_line_above_it(show_list, monkeypatch, dpr):
    """Painted at the screen ratio 1.0 and 1.5: each show's name drawn inside its own line, in the dim sub-line style,
    with ink there; the top-20 line through the group where B starts is drawn above B's show line, not under it."""
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QImage, QPainter
    from app.qt import rows
    rs = _shows_rows()
    group = rs["group"]
    lst, i = show_list([(rows.HERO, rs["run"], ()), (rows.ROW, group, ())], group.key)
    shows, eps_, rect, entry = _ordered_under_their_shows(lst, i, group)
    d = lst.delegate
    drawn, lined = [], []
    real = rows.TEXT.draw

    def spy(p, x, y_mid, text, role, width, colour, weight=None, align="left", dpr=1.0, elide=True):
        drawn.append((text, role, y_mid + p.transform().dy()))
        return real(p, x, y_mid, text, role, width, colour, weight, align, dpr, elide)
    monkeypatch.setattr(rows.TEXT, "draw", spy)
    monkeypatch.setattr(d, "_paint_line", lambda p, ln, strip, dpr: lined.append(QRect(strip)))
    area = d._open_area(rect, d.slab_of(rect))
    img = QImage(round(rect.width() * dpr), round((rect.bottom() + 1) * dpr), QImage.Format.Format_RGB32)
    img.setDevicePixelRatio(dpr)
    ground = rows.c("open-row")
    img.fill(ground)
    p = QPainter(img)
    top = vr.Line("top", 1, "", 3)                                     # the top-20 line, B's first episode its split
    d._paint_episodes(p, group, area, dpr, lines=(top,))
    p.end()
    for sr, show in shows:
        hits = [(role, y) for text, role, y in drawn if text == show]
        assert len(hits) == 1 and hits[0][0] == "row-sub" and sr.top() < hits[0][1] < sr.bottom()
        ink = sum(img.pixelColor(round(x * dpr), round(y * dpr)) != ground
                  for y in range(sr.top() + 2, sr.bottom() - 1) for x in range(sr.left() + 12, sr.left() + 80))
        assert ink > 20
    assert len(lined) == 1 and lined[0].top() == shows[1][0].top() - 2


def test_the_show_lines_are_kept_pictures_a_repaint_draws_no_name_again(show_list, monkeypatch):
    """Speed (a frame ≤ 8 ms): on screen each show line is painted once into a picture and blitted after, as an
    episode's line is — and the list's rest keeps it while the group is there."""
    from app.qt import rows
    rs = _shows_rows()
    group = rs["group"]
    lst, i = show_list([(rows.HERO, rs["run"], ()), (rows.ROW, group, ())], group.key)
    d = lst.delegate
    lst.viewport().repaint()
    names = []
    real = d._paint_show_line
    monkeypatch.setattr(d, "_paint_show_line", lambda p, r, show, dpr: (names.append(show), real(p, r, show, dpr)))
    d.keep_only(lst.model().entries)
    lst.viewport().repaint()
    assert names == []
