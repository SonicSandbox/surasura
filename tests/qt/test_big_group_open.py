"""A big opened group stays quick under the hand (alpha 9 try, reports 2 and 4, Sonic 2026-11-02: *"Lags and gave me
the spinner when I tried to open up BOM with 1-34 parts watched"*; *"Just tried to move a very large group (BOM) to
Goal. When it was collapsed it was less laggy but when it wasn't collapsed it seemed to freeze for a second"* — his
group is 336 parts).

Three things on the window's thread worked out every part of an opened row: the hit test under each mouse move built
every line's parts and every ✂ seam (each seam's tip walks the rest of the row), every repaint of the row (a toast's
frame, a press's ring) worked out every line's stone and picture, and the lift of an opened row baked its whole height
(13,000 px at 336 parts) into the ghost. Now the hit test and the seam's own outline ask near their line only
(`RowDelegate.parts(..., near=)`), a repaint draws the lines its rect meets (`RowsView.painting`), and an opened row
lifts closed (PROVISIONAL, the lane's lean: it stays closed after a cancel, as after a drop).

What a wrong answer would cost a learner: a click that lands on the wrong part (a stone marked watched instead of a ✂
seam, a ▶ that opens the part above) — so every answer here is the full scan's, point for point; a line left unpainted
or painted wrong; a drag that loses some of the group's parts on the way to Goal. Rows built by `view_rows.build` from
feed rows named as the library names a book's parts, with the fixtures' Japanese titles.
"""
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, QRect                                  # noqa: E402
from PyQt6.QtGui import QImage, QPainter, QRegion                       # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget                       # noqa: E402

from app.qt import rows                                         # noqa: E402
from app.services import view_rows as vr                                # noqa: E402
from app import theme                                                   # noqa: E402
from tests.qt.test_drag import (_stones_sheet, calls, lift, lst_of, move, move_global, press,  # noqa: E402,F401
                                release_global, rows_of, title_point, well_point, world)
from tests.test_view_rows import WORKS, _works, eps, items_of, work     # noqa: E402,F401

BOOKS = ("霧の港", "灯りの番", "嵐の夜")


def _group(parts=300, hero=False):
    """A group (piece 10) of three books, `parts` parts in all: the first book's first 34 watched (one fold, as his
    *1-34 parts watched*), a part of the second watched alone, three of the third watched after its Up next (a fold
    after it) — with a two-episode show before it (unless `hero`: then the group is Up Next) and one after. The top-20
    line runs through the group. -> (view, the group's row)."""
    per = parts // len(BOOKS)
    spec = [] if hero else [("now", 1, 21, eps("星降る街の小さな工房", 1, 2), {})]
    for b, title in enumerate(BOOKS):
        work(30 + b, title, media="book")
        n = per + (parts - per * len(BOOKS) if b == len(BOOKS) - 1 else 0)
        marks = {0: range(34), 1: (5,), 2: (10, 11, 12)}[b]
        spec.append(("now", 30 + b, 10, [f"{title}_{k:03d}.txt" for k in range(1, n + 1)],
                     {k: {"watched": 1} for k in marks}))
    spec.append(("now", 2, 22, eps("雲の上の郵便屋さん", 1, 3), {}))
    pieces = {10: {"id": 10, "title": "灯台守の書", "kind": "group"}, 21: {"id": 21, "title": None, "kind": "run"},
              22: {"id": 22, "title": None, "kind": "run"}}
    view = vr.build(items_of(spec), WORKS, {"mine_line": 20}, pieces=pieces)
    return view, next(r for r in view.rows if r.piece_id == 10)


def _entries(view):
    lines = {}
    for ln in view.lines:
        lines.setdefault(ln.after, []).append(ln)
    return [(rows.HERO if k == 0 else rows.ROW, r, tuple(lines.get(k, ()))) for k, r in enumerate(view.rows)]


def _settle():
    for _ in range(10):
        QApplication.processEvents()


@pytest.fixture
def opened(qapp):
    """A painted list of its own (no store) holding `view`'s rows, shown offscreen, the row `key` opened and — with
    `whole` — its first fold shown whole (every one of its parts a line)."""
    made = []

    def make(view, key, whole=False, size=(1100, 900)):
        host = QWidget()
        host.resize(*size)
        lst = rows.RowsView("Current", parent=host)
        lst.resize(*size)
        host.show()
        lst.set_entries(_entries(view))
        i = next(n for n, e in enumerate(lst.model().entries) if e[1].key == key)
        lst.toggle(lst.model().index(i, 0))
        _settle()
        if whole:
            fold = next(item for _r, item in lst.delegate.episode_lines(lst.model().entries[i], _rect(lst, i))
                        if isinstance(item, vr.Fold))
            lst.toggle_fold(fold)
            _settle()
        assert lst.model().open_key == key
        made.append(host)
        return lst, i
    yield make
    for host in made:
        host.close()


def _rect(lst, i):
    return lst.visualRect(lst.model().index(i, 0))


def _full_part_at(lst, pos, kept):
    """The hit test as it was: every part of the row under `pos` worked out (`parts` with no `near`) — the oracle.
    `kept`: each row's parts as laid out at this scroll (worked out once: the full scan is the slow thing)."""
    idx = lst.indexAt(pos)
    if not idx.isValid():
        return idx.row(), None
    entries = lst.model().entries
    n = idx.row()
    if n > 0 and entries[n - 1][2]:
        if ("lines", n - 1) not in kept:
            kept["lines", n - 1] = lst.delegate._line_parts(entries[n - 1][2], _rect(lst, n - 1))
        for part in kept["lines", n - 1]:
            if part[1].contains(pos):
                return n - 1, part
    if n not in kept:
        kept[n] = lst.delegate.parts(entries[n], _rect(lst, n))
    return n, next((part for part in kept[n] if part[1].contains(pos)), None)


def _points(lst, i):
    """Points to ask over the viewport: in and around every part of the opened row on screen (each corner, its centre,
    a pixel outside each edge — where a part reaching past its own line would be lost), and a grid over the rest."""
    view = lst.viewport().rect()
    out = set()
    for _name, r, _tip, _payload in lst.delegate.parts(lst.model().entries[i], _rect(lst, i)):
        if not r.intersects(view):
            continue
        for x in (r.left() - 1, r.left(), r.center().x(), r.right(), r.right() + 1):
            for y in (r.top() - 1, r.top(), r.center().y(), r.bottom(), r.bottom() + 1):
                out.add((x, y))
    for y in range(0, view.height(), 9):
        for x in range(0, view.width(), 71):
            out.add((x, y))
    return [QPoint(x, y) for x, y in sorted(out) if view.contains(QPoint(x, y))]


def _scrolled(lst):
    bar = lst.verticalScrollBar()
    for at in (0, bar.maximum() // 3, 2 * bar.maximum() // 3, bar.maximum()):
        bar.setValue(at)
        _settle()
        yield at


@pytest.mark.parametrize("hero", [False, True], ids=["row", "up-next"])
def test_the_hand_over_an_opened_300_part_group_finds_what_every_part_scanned_would_find(opened, hero):
    """Point for point over the whole opened group (a fold shown whole, show lines, the top-20 line through it, its ✂
    seams), scrolled from its head to its end: the hit test asked near the hand answers the full scan's part."""
    view, row = _group(hero=hero)
    lst, i = opened(view, row.key, whole=True)
    assert lst.verticalScrollBar().maximum() > 3 * lst.viewport().height()       # the row runs far past the screen
    entry = lst.model().entries[i]
    assert any(ln.kind == "top" and ln.split for ln in entry[2]) or any(ln.kind == "top" for ln in entry[2]), \
        "the top-20 line runs through the group"
    asked = seams = 0
    for _at in _scrolled(lst):
        kept = {}
        for pos in _points(lst, i):
            idx, part = lst.part_at(pos)
            assert (idx.row(), part) == _full_part_at(lst, pos, kept), (pos, _at)
            asked += 1
            seams += part is not None and part[0] == "seam"
    assert asked > 3000 and seams > 20                                            # the seams' bands were met


def test_the_hand_moving_over_the_group_works_out_its_own_line_never_every_seams_tip(opened, monkeypatch):
    """Each ✂ seam's tip says the rest of the row from it (`_rest_of`, a walk to the row's end): a move over a 300-part
    group worked out 300 of them (O(n²), 5.65 ms a move at 336 parts) and every line's buttons. Now the seams and the
    buttons by the hand's line alone."""
    view, row = _group()
    lst, i = opened(view, row.key, whole=True)
    walked, laid = [], []
    real, real_cols = rows._rest_of, rows.RowDelegate._episode_cols
    monkeypatch.setattr(rows, "_rest_of", lambda r, k: (walked.append(k), real(r, k))[1])
    lines = lst.delegate.episode_lines(lst.model().entries[i], _rect(lst, i))
    monkeypatch.setattr(rows.RowDelegate, "_episode_cols", lambda self, r: (laid.append(r), real_cols(self, r))[1])
    on_screen = [r for r, _item in lines if lst.viewport().rect().contains(r.center())]
    assert len(on_screen) > 10
    for r in on_screen:
        walked.clear()
        laid.clear()
        lst.part_at(r.center())
        assert len(walked) <= 2, len(walked)
        assert len(laid) <= 3, len(laid)                                     # its line's buttons, not every line's


def test_the_seam_under_the_hand_is_outlined_where_the_full_scan_puts_it(opened, monkeypatch):
    """The ✂ seam shown under the hand (`_q8_rect`) is the full scan's rect for every seam of the opened group, and
    works out the seams by its own line alone; a part that starts no seam (the group's first) has none."""
    view, row = _group(parts=120)
    lst, i = opened(view, row.key, whole=True)
    entry = lst.model().entries[i]
    seams = [p for p in lst.delegate.parts(entry, _rect(lst, i)) if p[0] == "seam"]
    assert len(seams) > 100
    walked = []
    real = rows._rest_of
    monkeypatch.setattr(rows, "_rest_of", lambda r, k: (walked.append(k), real(r, k))[1])
    for _name, r, _tip, ep in seams:
        walked.clear()
        assert lst._q8_rect((row.key, ep.id)) == r
        assert len(walked) <= 3                                             # the seams of its line and the two above
    assert lst._q8_rect((row.key, row.episodes[0].id)) is None
    lst.toggle(lst.model().index(i, 0))                                       # closed: no seam at all
    _settle()
    assert lst._q8_rect((row.key, seams[0][3].id)) is None


def _grab(lst, region=None):
    vp = lst.viewport()
    img = QImage(vp.size() * vp.devicePixelRatioF(), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(vp.devicePixelRatioF())
    img.fill(0)
    p = QPainter(img)
    vp.render(p, QPoint(), region if region is not None else QRegion(vp.rect()))
    p.end()
    return img


def test_a_strip_of_the_opened_group_repainted_is_the_full_paints_strip_and_works_out_its_own_lines(opened,
                                                                                                    monkeypatch):
    """A toast's frame or a press's ring repaints a strip: it comes out pixel for pixel as the whole screen painted
    has it there, and works out the few lines it meets — never every line's stone and picture (19 ms a repaint)."""
    view, row = _group()
    lst, i = opened(view, row.key, whole=True)
    lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 2)
    _settle()
    full = _grab(lst)
    made = []
    real = rows.RowDelegate._episode_pictures
    monkeypatch.setattr(rows.RowDelegate, "_episode_pictures",
                        lambda self, *a, **k: (lambda out: (made.append(len(out)), out)[1])(real(self, *a, **k)))
    vp = lst.viewport().rect()
    h = rows.RowDelegate._line_h()
    for top in (vp.height() // 3, vp.height() // 2 + 7):
        strip = QRect(0, top, vp.width(), h)
        made.clear()
        part = _grab(lst, QRegion(strip))
        dpr = lst.viewport().devicePixelRatioF()
        box = QRect(0, round(top * dpr), round(vp.width() * dpr), round(h * dpr))
        assert part.copy(box.translated(0, -box.top())) == full.copy(box)   # (`render` sets the strip at the top)
        assert made and max(made) <= 3, made                          # the lines the strip meets, not ~300


class _MovedAside:
    """A drag's parting as the view and the delegate read it: the opened row (place `opened`) moved by `shift`."""

    def __init__(self, opened, shift):
        self.opened, self.shift, self.src = opened, shift, None

    def offset(self, r):
        return float(self.shift) if r == self.opened else 0.0

    def paint_over(self, lst, event):
        pass


@pytest.mark.parametrize("shift", [60, -45])
def test_a_strip_of_an_opened_group_a_drag_moved_aside_is_painted_as_the_whole_screen_has_it(opened, shift):
    """The adversary's S: while a drag parts the rows the opened group is painted shifted, so a strip's rect must be
    read in the painter's own place — else the auto-scroll's new strip, a turning *Mine now* or a toast's strip over
    the group came out blank."""
    view, row = _group()
    lst, i = opened(view, row.key, whole=True)
    lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 2)
    _settle()
    lst.parting = _MovedAside(i, shift)
    try:
        full = _grab(lst)
        vp = lst.viewport().rect()
        for top in range(100, vp.height() - 100, 37):
            strip = QRect(0, top, vp.width(), 20)
            assert _grab(lst, QRegion(strip)).copy(QRect(0, 0, vp.width(), 20)) == full.copy(strip), top
    finally:
        lst.parting = None


def test_an_opened_row_lifted_closed_near_the_lists_end_keeps_its_place_till_the_hand_travels(world):
    """The adversary's B: an opened row near the list's end, its head near the top — closing it at the lift shrinks
    the list, the scroll clamps and the row drops from under the hand. A release right there moved it (11th → 6th);
    now its slot stays its own till the hand travels, and a release there writes nothing. Once the hand travels, the
    slot follows it as in any drag."""
    seed, win, writer = world()
    lst = lst_of(win)
    entries = lst.model().entries
    cur = [n for n, e in enumerate(entries) if e[0] == rows.ROW]
    i = max(cur[-6:], key=lambda n: len(entries[n][1].episodes))     # a row near the end with the most parts
    lst.toggle(lst.model().index(i, 0))
    _settle()
    bar = lst.verticalScrollBar()
    bar.setValue(bar.value() + _rect(lst, i).top() - 40)               # its head 40 px from the top
    _settle()
    at = title_point(lst, i)
    press(lst, at)
    hand = at + QPoint(0, theme.MOTION["drag-start-px"])
    move(lst, hand)
    d = win.moves.running
    assert d is not None and lst.model().open_key is None
    assert _rect(lst, i).top() > at.y() + 100                          # the row dropped from under the hand
    assert lst.indexAt(hand).row() != i
    gp = lst.viewport().mapToGlobal(hand)
    assert win.moves.target_at(gp) == ("list", d.src)
    assert win.moves.target_at(gp + QPoint(2, 3)) == ("list", d.src)  # a wobble is no travel
    release_global(win, gp + QPoint(2, 3))
    _settle()
    assert calls(writer) == [] and lst.model().open_key is None


def test_the_hand_that_travelled_from_a_closed_rows_lift_leaves_its_slot_to_the_hand(world):
    """After the clamp, the hand's travel hands the slot back to the hand: wherever it then goes, the slot is the row
    under it (`slot_at`), never the row's own place again — even back over the lift's point."""
    seed, win, writer = world()
    lst = lst_of(win)
    entries = lst.model().entries
    cur = [n for n, e in enumerate(entries) if e[0] == rows.ROW]
    i = max(cur[-6:], key=lambda n: len(entries[n][1].episodes))
    lst.toggle(lst.model().index(i, 0))
    _settle()
    bar = lst.verticalScrollBar()
    bar.setValue(bar.value() + _rect(lst, i).top() - 40)
    _settle()
    at = title_point(lst, i)
    press(lst, at)
    hand = at + QPoint(0, theme.MOTION["drag-start-px"])
    move(lst, hand)
    d = win.moves.running
    gp = lst.viewport().mapToGlobal(hand)
    far = gp + QPoint(0, 3 * theme.MOTION["drag-start-px"])
    assert win.moves.target_at(far) == ("list", win.moves.slot_at(hand.y() + 3 * theme.MOTION["drag-start-px"]))
    assert d.home is None
    assert win.moves.target_at(gp) == ("list", win.moves.slot_at(hand.y()))
    assert win.moves.slot_at(hand.y()) != d.src
    win.moves.cancel()


def test_a_rest_right_after_an_opened_row_closed_under_the_hand_joins_nothing(world):
    """The adversary's second B: after the clamp the hand rests over another show's row, inside the lift's home. A hold
    there grouped the lifted row with it (`join`, `how: group`) — a rest that never travelled must do nothing, so no
    hold starts and no outline shows till the hand travels."""
    seed, win, writer = world()
    lst = lst_of(win)
    entries = lst.model().entries
    cur = [n for n, e in enumerate(entries) if e[0] == rows.ROW]
    i = max(cur[-6:], key=lambda n: len(entries[n][1].episodes))
    lst.toggle(lst.model().index(i, 0))
    _settle()
    bar = lst.verticalScrollBar()
    bar.setValue(bar.value() + _rect(lst, i).top() - 100)              # its head 100 px from the top
    _settle()
    at = title_point(lst, i)
    press(lst, at)
    k = theme.MOTION["drag-start-px"]
    move(lst, at + QPoint(0, k))
    d = win.moves.running
    assert d is not None and d.home is not None                       # the close moved the row from under the hand
    hand = next(at + QPoint(0, k + dy) for dy in range(-k + 1, k)
                if win.moves.joins._over(d, lst.viewport().mapToGlobal(at + QPoint(0, k + dy))) is not None)
    gp = lst.viewport().mapToGlobal(hand)
    move_global(win, gp)
    end = time.monotonic() + 0.7                                       # longer than the hold (JOIN_REST_MS)
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.01)
    move_global(win, gp)
    assert win.moves.target_at(gp) == ("list", d.src)
    release_global(win, gp)
    _settle()
    assert calls(writer) == []


def test_an_opened_row_lifts_closed_and_a_drop_on_goal_moves_every_one_of_its_files(world):
    """Report 4: the lift of an opened row baked its whole height into the ghost (13,000 px, 2 s at 250 %). It lifts
    closed — its ghost and the slot it leaves the closed row's — and a drop on Goal still moves every file of it."""
    seed, win, writer = world()
    lst = lst_of(win)
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and len(e[1].episodes) >= 3)
    row = lst.model().entries[i][1]
    closed_h = _rect(lst, i).height()
    lst.toggle(lst.model().index(i, 0))
    _settle()
    assert lst.model().open_key == row.key and _rect(lst, i).height() > closed_h
    lift(win, i)
    assert lst.model().open_key is None and _rect(lst, i).height() == closed_h
    d = win.moves.running
    assert d.parting.h <= closed_h
    assert win.moves.ghost.height() < 2 * closed_h + 80                       # its shadow round the closed row's
    at = well_point(win, "goal")
    move_global(win, at)
    release_global(win, at)
    op = calls(writer, "move")[0]
    assert op[2]["tier"] == "goal" and sorted(op[1]) == sorted(e.id for e in row.episodes)
    assert row.key not in [r.key for r in rows_of(win)]


def test_an_opened_row_lifted_and_let_go_stays_closed_and_writes_nothing(world):
    """A cancelled lift of an opened row leaves it closed (PROVISIONAL, as after a drop) and the store untouched."""
    seed, win, writer = world()
    lst = lst_of(win)
    i = next(n for n, e in enumerate(lst.model().entries) if e[0] == rows.ROW and len(e[1].episodes) >= 3)
    lst.toggle(lst.model().index(i, 0))
    _settle()
    lift(win, i)
    win.moves.cancel()
    _settle()
    assert lst.model().open_key is None and calls(writer) == []
