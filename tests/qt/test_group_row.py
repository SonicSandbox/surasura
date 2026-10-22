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
    assert between.bottom() + 1 == shows[1][0].top()          # wholly above B's show line, its foot on it (AD-5)
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


def test_the_show_lines_stand_where_the_services_show_key_changes_and_a_cache_without_it_has_none():
    """IK-3: which show a file is of is the service's reading (`view_rows._show_key`: its work, else its folder), put on
    each of a group's episodes; the window's show lines read it, never key the shows themselves. A run's episodes carry
    none, and a group from a cache from before (no `show_key`) opens as it did: no show lines."""
    from app.qt import rows
    rs = _shows_rows()
    group = rs["group"]
    assert [e.show_key for e in group.episodes] == [("w", 1)] * 3 + [("w", 2)] * 2
    assert all(e.show_key is None for e in rs["run"].episodes)
    assert rows.show_starts(group) == {0: group.episodes[0].show, 3: group.episodes[3].show}
    cached = group._replace(episodes=tuple(e._replace(show_key=None) for e in group.episodes))
    assert rows.show_starts(cached) == {}
    # one show by the service's reading (one work), whatever else differs between its files: one show, no lines
    one = group._replace(episodes=tuple(e._replace(show_key=("w", 1)) for e in group.episodes))
    assert rows.show_starts(one) == {}


def test_a_closed_rows_line_says_a_dash_new_when_its_count_is_unknown(show_list, monkeypatch):
    """AD-7: a closed Current row whose new words aren't counted yet (no plan, files came in since Generate) reads
    "— new" on its own line, as an episode's and the hero's do; a counted row draws its count."""
    from PyQt6.QtGui import QImage, QPainter
    from app.qt import rows, strings
    rs = _shows_rows()
    lst, _i = show_list([(rows.HERO, rs["one"], ()), (rows.ROW, rs["run"], ())], rs["one"].key)
    d = lst.delegate
    slab = d.slab_of(lst.visualRect(lst.model().index(1, 0)))
    real = rows.TEXT.draw
    for n_new, count in ((None, strings.ROWS_DASH), (44, "44")):
        row = rs["run"]._replace(n_new=n_new, pct=91)
        drawn = []
        monkeypatch.setattr(rows.TEXT, "draw", lambda p, x, y, text, *a, **k: (drawn.append(text),
                                                                                 real(p, x, y, text, *a, **k))[1])
        img = QImage(slab.right() + 1, slab.bottom() + 1, QImage.Format.Format_RGB32)
        img.fill(rows.c("surface"))
        p = QPainter(img)
        try:
            d._paint_current(p, row, slab, False, 1.0, None)
        finally:
            p.end()
            monkeypatch.setattr(rows.TEXT, "draw", real)
        k = drawn.index(" " + strings.ROWS_NEW_WORD)
        assert drawn[k + 1] == count, drawn


# --- row 28 follow-up A: the hand's and the keyboard's episode ---------------------------------------------------- #
def _group_last(show_list, height=None):
    """The group opened as the list's LAST row (a run above it): (list, its place, the group)."""
    from app.qt import rows
    rs = _shows_rows()
    lst, i = show_list([(rows.ROW, rs["run"], ()), (rows.ROW, rs["group"], ())], rs["group"].key)
    if height is not None:
        lst.resize(1100, height)
        _settle()
    return lst, i, rs["group"]


def _settle():
    from PyQt6.QtWidgets import QApplication
    for _ in range(10):
        QApplication.processEvents()


def _keys(lst, *keys):
    from PyQt6.QtTest import QTest
    for k in keys:
        QTest.keyClick(lst, k)
    _settle()


def test_AD1_a_click_lets_the_keyboards_episode_go_so_enter_closes_the_row_again(show_list):
    """AD-1: ↓ into an episode, then the hand closes and opens the row on its title: Enter closes the row, never the
    remembered episode's ⋯ (a menu from nowhere); ↓ starts again at its first episode. A close and a list reset (a
    language switch) let it go too."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from app.qt import rows
    lst, i, group = _group_last(show_list)
    menus = []
    lst.episode_menu_requested.connect(lambda r, ep, at: menus.append(ep.id))
    lst.setCurrentIndex(lst.model().index(i, 0))
    _keys(lst, Qt.Key.Key_Down, Qt.Key.Key_Down)
    assert lst.ep_key == (group.key, group.episodes[1].id)
    for _ in range(2):                                                 # closed, then opened again, by the hand
        rect = lst.visualRect(lst.model().index(i, 0))
        title = next(pt[1] for pt in lst.delegate.parts(lst.model().entries[i], rect) if pt[0] == "title")
        QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=title.center())
        _settle()
    assert lst.model().open_key == group.key and lst.ep_key is None
    _keys(lst, Qt.Key.Key_Return)
    assert menus == [] and lst.model().open_key is None, "Enter closed the row"
    lst.toggle(lst.model().index(i, 0))
    _keys(lst, Qt.Key.Key_Down)
    assert lst.ep_key == (group.key, group.episodes[0].id), "↓ from the head: its first episode"
    lst.toggle(lst.model().index(i, 0))
    assert lst.ep_key is None, "a close lets it go"
    lst.toggle(lst.model().index(i, 0))
    _keys(lst, Qt.Key.Key_Down)
    assert lst.ep_key is not None
    head = lst.delegate.slab_of(lst.visualRect(lst.model().index(i, 0)))
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.RightButton, pos=head.center())     # on its own row: no new current
    assert lst.ep_key is None and lst.model().open_key == group.key, "any press of the hand lets it go"
    entries = list(lst.model().entries)
    for again in (entries + [(rows.ROW, _shows_rows()["one"], ())],     # a row came: a reset, the group still open
                  [(rows.ROW, _shows_rows()["one"], ())]):             # another language's list
        lst.setCurrentIndex(lst.model().index(i, 0))
        _keys(lst, Qt.Key.Key_Down)
        assert lst.ep_key is not None
        assert lst.set_entries(again) == "reset"
        assert lst.ep_key is None
        lst.set_entries(entries)


def test_AD2_right_on_an_episode_takes_that_episodes_own_button_and_down_lets_it_go(show_list):
    """AD-2: the keyboard on episode 3, → takes episode 3's own *Mine now* and Enter asks for its file alone — never
    the head's (every waiting file) or episode 1's. → then ↓ lets the button go: Enter then opens the next episode's
    ⋯ and asks for nothing. On the head, → takes the head's own."""
    from PyQt6.QtCore import Qt
    lst, i, group = _group_last(show_list)
    asked, menus = [], []
    lst.mine_requested.connect(lambda r, ids: asked.append(tuple(ids)))
    lst.episode_menu_requested.connect(lambda r, ep, at: menus.append(ep.id))
    lst.setCurrentIndex(lst.model().index(i, 0))
    _keys(lst, Qt.Key.Key_Down, Qt.Key.Key_Down, Qt.Key.Key_Down, Qt.Key.Key_Right, Qt.Key.Key_Return)
    assert asked == [(group.episodes[2].id,)]
    _keys(lst, Qt.Key.Key_Right, Qt.Key.Key_Down)
    assert lst.action_focus is None and lst.ep_key == (group.key, group.episodes[3].id)
    _keys(lst, Qt.Key.Key_Return)
    assert asked == [(group.episodes[2].id,)] and menus == [group.episodes[3].id]
    _keys(lst, Qt.Key.Key_Up, Qt.Key.Key_Up, Qt.Key.Key_Up, Qt.Key.Key_Up)
    assert lst.ep_key is None
    _keys(lst, Qt.Key.Key_Right, Qt.Key.Key_Return)
    assert len(asked) == 2 and len(asked[1]) > 1, "the head's own: every waiting file of the group"


def test_AD3_after_a_wheels_scroll_the_hands_episode_is_the_one_under_it(show_list, monkeypatch):
    """AD-3: Qt sends no move after a wheel's scroll: the hover look and ⋯ stayed on the episode that slid away. The
    hand's episode is read again where the cursor is."""
    from PyQt6.QtCore import Qt
    from app.qt import rows
    from tests.qt.test_drag import move
    lst, i, group = _group_last(show_list, height=260)
    rect = lst.visualRect(lst.model().index(i, 0))
    lines = lst.delegate.episode_lines(lst.model().entries[i], rect)
    at = lines[0][0].center()
    assert lst.viewport().rect().contains(at)
    move(lst, at, buttons=Qt.MouseButton.NoButton)
    assert lst.ep_hot == (group.key, lines[0][1].id)
    gpos = lst.viewport().mapToGlobal(at)
    monkeypatch.setattr(rows, "QCursor", type("C", (), {"pos": staticmethod(lambda: gpos)}))
    bar = lst.verticalScrollBar()
    step = lines[1][0].top() - lines[0][0].top()
    assert bar.maximum() - bar.value() >= step
    bar.setValue(bar.value() + step)                                   # the next episode now under the hand
    _settle()
    under = [ep for r, ep in lst.delegate.episode_lines(lst.model().entries[i], lst.visualRect(lst.model().index(i, 0)))
             if r.contains(at)]
    assert under == [lines[1][1]] and lst.ep_hot == (group.key, lines[1][1].id)


def test_AD4_down_past_the_lists_last_episode_stays_there(show_list):
    """AD-4: the list's last row opened, ↓ on its last episode: no next row — the keyboard stays on that episode,
    never back to the head and round again."""
    from PyQt6.QtCore import Qt
    lst, i, group = _group_last(show_list)
    lst.setCurrentIndex(lst.model().index(i, 0))
    _keys(lst, *[Qt.Key.Key_Down] * len(group.episodes))
    last = (group.key, group.episodes[-1].id)
    assert lst.ep_key == last
    _keys(lst, Qt.Key.Key_Down, Qt.Key.Key_Down)
    assert lst.ep_key == last and lst.currentIndex().row() == i


def test_IK4_the_hand_within_one_episode_repaints_nothing_and_to_the_next_only_those_two_lines(show_list, monkeypatch):
    """S19 (update only what changed): the hand moving within one episode's line repaints nothing; onto the next
    episode, only the two lines whose look changed (the one it left, the one it came to)."""
    from PyQt6.QtCore import QPoint, Qt
    from tests.qt.test_drag import move
    lst, i, group = _group_last(show_list)
    lines = lst.delegate.episode_lines(lst.model().entries[i], lst.visualRect(lst.model().index(i, 0)))
    (r0, ep0), (r1, ep1) = lines[0], lines[1]
    move(lst, r0.center(), buttons=Qt.MouseButton.NoButton)
    _settle()
    vp, updates = lst.viewport(), []
    real_vp, real_row = vp.update, lst.update
    monkeypatch.setattr(vp, "update", lambda *a: (updates.append(("vp",) + a), real_vp(*a))[1])
    monkeypatch.setattr(lst, "update", lambda *a: (updates.append(("row",) + a), real_row(*a))[1])
    for dx, dy in ((40, 0), (80, -3), (-30, 4)):
        move(lst, r0.center() + QPoint(dx, dy), buttons=Qt.MouseButton.NoButton)
    assert updates == [] and lst.ep_hot == (group.key, ep0.id)
    move(lst, r1.center(), buttons=Qt.MouseButton.NoButton)
    assert lst.ep_hot == (group.key, ep1.id)
    assert updates == [("vp", r0), ("vp", r1)]


def test_IK7_a_right_click_on_an_opened_rows_episode_opens_that_episodes_menu_and_on_the_head_the_rows(show_list):
    """IK-7: a right-click on an opened row's episode opens that episode's own ⋯, at the hand (as the menu key does
    for the keyboard's episode); on the head, the row's ⋯ as before."""
    from PyQt6.QtGui import QContextMenuEvent
    lst, i, group = _group_last(show_list)
    eps_, rows_ = [], []
    lst.episode_menu_requested.connect(lambda r, ep, at: eps_.append((r.key, ep.id, at)))
    lst.menu_requested.connect(lambda r, at: rows_.append(r.key))
    rect = lst.visualRect(lst.model().index(i, 0))
    line, ep = lst.delegate.episode_lines(lst.model().entries[i], rect)[3]
    for pos in (line.center(), lst.delegate.slab_of(rect).center()):
        lst.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, lst.viewport().mapToGlobal(pos)))
    assert eps_ == [(group.key, ep.id, lst.viewport().mapToGlobal(line.center()))]
    assert rows_ == [group.key]


@pytest.mark.parametrize("f", (1.0, 1.5))
def test_AD5_the_seams_chip_at_a_show_change_never_covers_the_next_shows_name(show_list, monkeypatch, f):
    """AD-5: the ✂ seam where one show's run ends stands wholly above the next show's line, so its chip (lit under
    the hand) never covers the show's name and its hover takes none of the show line — at the text factor 1.0 and
    1.5."""
    from PyQt6.QtGui import QImage, QPainter
    from app.qt import rows
    monkeypatch.setattr(rows, "fz", lambda: f)
    rs = _shows_rows()
    group = rs["group"]
    lst, i = show_list([(rows.HERO, rs["run"], ()), (rows.ROW, group, ())], group.key)
    shows, eps_, rect, entry = _ordered_under_their_shows(lst, i, group)
    d = lst.delegate
    sr = shows[1][0]
    seam = next(p[1] for p in d.parts(entry, rect) if p[0] == "seam" and p[3] is eps_[3][1])
    assert seam.bottom() < sr.top()
    ground = rows.c("open-row")

    def ink_rows(paint):
        img = QImage(rect.width(), rect.bottom() + 40, QImage.Format.Format_RGB32)
        img.fill(ground)
        p = QPainter(img)
        paint(p)
        p.end()
        return [y for y in range(img.height()) if any(img.pixelColor(x, y) != ground for x in range(0, 400, 2))]
    chip = ink_rows(lambda p: d.paint_seam(p, seam))
    name = ink_rows(lambda p: d._paint_show_line(p, sr, shows[1][1], 1.0))
    assert chip and name and max(chip) < min(name), (max(chip), min(name))
