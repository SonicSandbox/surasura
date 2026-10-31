"""An opened row folds its watched runs (a8, Sonic 2026-10-31: "When I open <a long book>, there are so many that I have to
scroll a long time to get where I want, which is the next item … even after opening up, it keeps the ones together …
and you can still expand those too but only after an additional motion"; lean taken: "Yes to both leans").

An opened Current row (or Up Next) lists each run of two or more watched parts of one show as one line — *Parts 1–280
watched*, the journey's fold and words (`view_rows.folds` / `watched_runs` / `fold_label`, the one rule the report's
`_journey_folds` reads too) — so the row opens at Up next, never a long scroll above it. One more click on that line
(or Enter / Space on it) lists its parts after it; another folds them again. Its next part is never folded (Up next
stays a line of its own), a part watched alone stays as it is, a group folds each show's run under its own show line,
and neither the Soon line nor the top-20 line running through a row is ever folded over. PROVISIONAL (the lane's calls,
scenario-tested here): the wording and the tip are the journey's; Up next is never folded (so a show watched to its end
reads *Parts 1–39 watched* and part 40, where the journey says *Parts 1–40*); an audiobook's waiting item is never in a
run; a group folds per show; a fold shown whole goes back to folded when its row closes (or another row opens, however
it opens) and stays shown whole while its run grows or splits; Enter or Space on it folds or shows it, the menu key and
a right-click open its row's ⋯ (a fold has none of its own); a drop on a group's fold lands after its run's last part;
no screen-reader words of its own (an opened row's lines are no accessible items today: its tip is read as the keyboard
lands on it).

What a wrong answer would cost a learner: Up next folded away (he opens the row and can't find what to watch), an
unwatched part hidden inside a fold, two shows' parts under one line, a click on a fold that marks a part or opens a menu,
a mark painted ahead that leaves the run unfolded (or folds the part under his hand into a line that isn't there), or
a fold that moves every other row. Rows built by `view_rows.build` from feed rows named as the library names a book's
chapter parts (`<book>_NN (c-x) <chapter>`), with the fixtures' Japanese titles.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt                                     # noqa: E402
from PyQt6.QtTest import QTest                                          # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget                       # noqa: E402

from app.qt import rows                                                 # noqa: E402
from app.services import view_rows as vr                                # noqa: E402
from tests.test_view_rows import WORKS, _works, eps, items_of, work     # noqa: E402,F401

BOOK = "灯台守の手記"
BOOKS = ("霧の港", "灯りの番", "嵐の夜", "沈んだ船", "古い日誌", "岬の祈り", "冬の便り", "潮の満ち引き", "帰らぬ人", "白い鳥",
         "遠い汽笛", "砂の階段", "最後の灯", "夜明け前", "港の朝")


def book_parts(n):
    """`n` chapter parts of a long book as the library names them: `灯台守の手記_002 (2-1) 霧の港` … (each chapter in 20
    parts), the first its preface."""
    out = [f"{BOOK}_001 (1) 序文.txt"]
    for k in range(2, n + 1):
        c = (k - 2) // 20 + 2
        out.append(f"{BOOK}_{k:03d} ({c}-{(k - 2) % 20 + 1}) {BOOKS[(c - 2) % len(BOOKS)]}.txt")
    return out


def _book(n=300, watched=range(280), lines=20):
    """The book (piece 20) of `n` parts, those at `watched` (0-based) watched, after a show of 2 episodes (piece 21) —
    built by `view_rows.build`, as the reader does. -> (view, its row)."""
    work(5, BOOK, media="book")
    spec = [("now", 1, 21, eps("星降る街の小さな工房", 1, 2), {}),
            ("now", 5, 20, book_parts(n), {k: {"watched": 1} for k in watched})]
    view = vr.build(items_of(spec), WORKS, {"mine_line": lines}, pieces={20: {"id": 20, "title": None, "kind": "run"},
                                                                      21: {"id": 21, "title": None, "kind": "run"}})
    return view, next(r for r in view.rows if r.piece_id == 20)


# --- the rule (Qt-free) -------------------------------------------------------------------------------------------- #
def test_watched_runs_are_runs_of_equal_keys_next_to_each_other_and_none_is_never_in_one():
    """The journey's and the window's one rule: a run ends where the key changes (another show, another tier) or a part
    isn't watched (None)."""
    a, b = ("show", "A"), ("show", "B")
    assert vr.watched_runs([a, a, None, a, b, b, b, None]) == [(0, 1), (3, 3), (4, 6)]
    assert vr.watched_runs([]) == [] and vr.watched_runs([None, None]) == []


def test_a_long_books_watched_chapters_are_one_fold_and_up_next_stays_a_line_of_its_own():
    """A long book, 300 parts, 280 watched: one fold for parts 1–280 in the journey's words, then Up next (part 281)."""
    _view, row = _book()
    assert row.next_index == 280
    (fold,) = vr.folds(row)
    assert (fold.start, fold.end, fold.label) == (0, 279, "Parts 1–280 watched")
    assert fold.ids == tuple(e.id for e in row.episodes[:280]) and fold.id == ("fold", row.episodes[0].id)
    assert fold.label == vr.fold_label("book", list(range(1, 281)), 280)       # the journey's own words (`_journey_folds`)


def test_the_next_part_is_never_folded_even_when_every_part_is_watched():
    """All 40 watched: Up next is the last part (`next_index`); the 39 before it fold, it stays a line."""
    _view, row = _book(n=40, watched=range(40))
    assert row.next_index == 39
    assert [(f.start, f.end) for f in vr.folds(row)] == [(0, 38)]


def test_a_part_watched_out_of_order_folds_after_up_next_and_a_lone_watched_part_stays_as_it_is():
    """Watched 1–10, 12–20 and 25: Up next is 11 (never folded); 12–20 is a fold of its own; 25 alone stays a part."""
    _view, row = _book(n=30, watched=list(range(10)) + list(range(11, 20)) + [24])
    assert row.next_index == 10
    assert [(f.start, f.end, f.label) for f in vr.folds(row)] == [(0, 9, "Parts 1–10 watched"),
                                                                   (11, 19, "Parts 12–20 watched")]
    _view, row = _book(n=5, watched=[0])                     # one watched part before Up next: no fold
    assert vr.folds(row) == ()


def test_a_fold_never_runs_across_a_break_the_top_20_line_through_the_row():
    """The window's top-20 line running through a row at part k: the run is cut there (its line never folded over)."""
    _view, row = _book(n=30, watched=list(range(10)) + list(range(11, 25)))
    assert [(f.start, f.end) for f in vr.folds(row, breaks=(15,))] == [(0, 9), (11, 14), (15, 24)]


def test_a_group_folds_each_shows_run_in_its_own_words_never_across_two_shows():
    """A group of an anime (Ep) and a light novel (Parts), each fully watched before the group's next file: one fold
    per show, each said as its own show says it (`Episode.media`)."""
    spec = [("now", 1, 10, eps("星降る街の小さな工房", 1, 3), {0: {"watched": 1}, 1: {"watched": 1}, 2: {"watched": 1}}),
            ("now", 3, 10, book_parts(4)[:3], {0: {"watched": 1}, 1: {"watched": 1}}),
            ("now", 2, 10, eps("雲の上の郵便屋さん", 1, 2), {})]
    view = vr.build(items_of(spec), WORKS, {"mine_line": 20}, pieces={10: {"id": 10, "title": None, "kind": "group"}})
    row = view.rows[0]
    assert row.group and row.next_index == 5
    assert [(f.start, f.end, f.label) for f in vr.folds(row)] == [(0, 2, "Ep 1–3 watched"), (3, 4, "Parts 1–2 watched")]


# --- the window ---------------------------------------------------------------------------------------------------- #
@pytest.fixture
def opened(qapp):
    """A painted list of its own (no store) holding `view`'s rows, shown offscreen, the row `key` opened."""
    made = []

    def make(view, key, size=(1100, 900)):
        host = QWidget()
        host.resize(*size)
        lst = rows.RowsView("Current", parent=host)
        lst.resize(*size)
        host.show()
        lst.set_entries(_entries(view))
        i = next(n for n, e in enumerate(lst.model().entries) if e[1].key == key)
        lst.toggle(lst.model().index(i, 0))
        _settle()
        assert lst.model().open_key == key
        made.append(host)
        return lst, i
    yield make
    for host in made:
        host.close()


def _entries(view):
    lines = {}
    for ln in view.lines:
        lines.setdefault(ln.after, []).append(ln)
    return [(rows.HERO if k == 0 else rows.ROW, r, tuple(lines.get(k, ()))) for k, r in enumerate(view.rows)]


def _settle():
    for _ in range(10):
        QApplication.processEvents()


def _lines(lst, i):
    entry = lst.model().entries[i]
    return lst.delegate.episode_lines(entry, lst.visualRect(lst.model().index(i, 0)))


def _click(lst, r):
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r.center())
    _settle()


def test_the_row_opens_at_up_next_its_watched_run_one_line_above_it(opened):
    """The long book opened: the fold's line first, Up next right after it, then the 19 parts left — 21 lines, not 300."""
    view, row = _book()
    lst, i = opened(view, row.key)
    items = [item for _r, item in _lines(lst, i)]
    assert isinstance(items[0], vr.Fold) and items[0].label == "Parts 1–280 watched"
    assert items[1] is row.episodes[280] and items[2:] == list(row.episodes[281:])
    assert lst.visualRect(lst.model().index(i, 0)).height() < 30 * 40      # never 300 lines tall


def test_one_more_click_on_the_fold_lists_its_parts_and_another_folds_them_only_its_row_changing_height(opened):
    """The fold's line is one button: a click shows each part after it (the fold's line stays, its chevron down), a
    second folds them again — no ⋯, no Done, no mark; the rows above it keep their heights and places."""
    view, row = _book()
    lst, i = opened(view, row.key)
    model = lst.model()
    above = [lst.visualRect(model.index(k, 0)) for k in range(i)]
    marks = []
    lst.done_requested.connect(lambda *a: marks.append(a))
    lst.episode_menu_requested.connect(lambda *a: marks.append(a))
    fold_r = _lines(lst, i)[0][0]
    _click(lst, fold_r)
    items = [item for _r, item in _lines(lst, i)]
    assert isinstance(items[0], vr.Fold) and lst.fold_open(items[0])
    assert items[1:] == list(row.episodes)                       # every part, in its place, Up next among them
    part = next(p for p in lst.delegate.parts(model.entries[i], lst.visualRect(model.index(i, 0))) if p[0] == "fold")
    assert part[2] == vr.STRINGS["fold_tip_open"]
    _click(lst, fold_r)
    items = [item for _r, item in _lines(lst, i)]
    assert len(items) == 21 and not lst.fold_open(items[0])
    assert marks == []                                           # a fold's click marks nothing and opens no menu
    assert [lst.visualRect(model.index(k, 0)) for k in range(i)] == above


def test_the_keyboard_steps_onto_the_fold_and_enter_or_space_shows_or_folds_it(opened):
    """↓ from the opened row's head lands on the fold's line (its tip said), Enter shows its parts, ↓ goes into them,
    ↑ back, Space folds them again; the menu key on it opens nothing."""
    view, row = _book(n=12, watched=range(10))
    lst, i = opened(view, row.key)
    lst.setFocus()
    lst.setCurrentIndex(lst.model().index(i, 0))
    menus = []
    lst.episode_menu_requested.connect(lambda *a: menus.append(a))
    QTest.keyClick(lst, Qt.Key.Key_Down)
    fold = _lines(lst, i)[0][1]
    assert lst.ep_key == (row.key, fold.id)
    QTest.keyClick(lst, Qt.Key.Key_Return)
    _settle()
    assert lst.fold_open(fold) and len(_lines(lst, i)) == 13
    QTest.keyClick(lst, Qt.Key.Key_Down)
    assert lst.ep_key == (row.key, row.episodes[0].id)
    QTest.keyClick(lst, Qt.Key.Key_Up)
    QTest.keyClick(lst, Qt.Key.Key_Menu)
    QTest.keyClick(lst, Qt.Key.Key_Space)
    _settle()
    assert not lst.fold_open(fold) and len(_lines(lst, i)) == 3 and menus == []


def test_a_part_marked_watched_inside_the_opened_row_joins_its_fold_at_once_and_a_shown_fold_stays_shown(opened):
    """Up next (part 281) marked watched — the view as a painted-ahead mark lays it, or the store's next: the fold
    reads *Parts 1–281 watched* at once and part 282 is Up next, the row still open. Shown whole first, it stays shown
    whole (the learner's choice kept as the run grows)."""
    view, row = _book()
    lst, i = opened(view, row.key)
    later, _row = _book(watched=range(281))
    lst.set_entries(_entries(later))
    _settle()
    items = [item for _r, item in _lines(lst, i)]
    assert lst.model().open_key == row.key
    assert items[0].label == "Parts 1–281 watched" and items[1].id == row.episodes[281].id and len(items) == 20
    _click(lst, _lines(lst, i)[0][0])
    lst.set_entries(_entries(_book(watched=range(282))[0]))
    _settle()
    items = [item for _r, item in _lines(lst, i)]
    assert items[0].label == "Parts 1–282 watched" and lst.fold_open(items[0]) and len(items) == 301


def test_a_row_closed_and_opened_again_opens_folded(opened):
    """PROVISIONAL: a fold shown whole goes back to folded when its row closes — each opening starts at Up next."""
    view, row = _book(n=12, watched=range(10))
    lst, i = opened(view, row.key)
    _click(lst, _lines(lst, i)[0][0])
    assert len(_lines(lst, i)) == 13
    lst.toggle(lst.model().index(i, 0))
    lst.toggle(lst.model().index(i, 0))
    _settle()
    assert len(_lines(lst, i)) == 3


def test_a_right_click_on_a_fold_opens_its_rows_menu_never_an_episodes(opened):
    """A fold has no ⋯ of its own: a right-click on its line is the row's (as on the row's head)."""
    view, row = _book(n=12, watched=range(10))
    lst, i = opened(view, row.key)
    got = []
    lst.menu_requested.connect(lambda r, _at: got.append(("row", r.key)))
    lst.episode_menu_requested.connect(lambda r, ep, _at: got.append(("ep", ep)))
    r = _lines(lst, i)[0][0]
    from PyQt6.QtGui import QContextMenuEvent
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, r.center(), lst.viewport().mapToGlobal(r.center()))
    lst.contextMenuEvent(event)
    assert got == [("row", row.key)]


def test_the_folds_line_is_painted_with_its_words(opened, monkeypatch):
    """Its words drawn as the journey says them, dim as a watched part's label."""
    view, row = _book()
    lst, i = opened(view, row.key)
    drawn = []
    real = rows.TEXT.draw
    monkeypatch.setattr(rows.TEXT, "draw", lambda p, x, y, text, *a, **k: (drawn.append(text), real(p, x, y, text, *a,
                                                                                                    **k))[1])
    lst.delegate._sprites["ep"].clear()
    lst.viewport().repaint()
    assert "Parts 1–280 watched" in drawn and row.episodes[0].label not in drawn


def test_the_hand_on_a_groups_fold_is_on_the_fold_whose_last_part_a_drop_lands_after(opened):
    """LM11b G2's drop on an opened group's episode asks `episode_at`: on a fold's line it answers the fold, which
    `item_menu` reads as the run's last part (a drop lands after it, never on a line that is no file)."""
    spec = [("now", 1, 10, eps("星降る街の小さな工房", 1, 3), {0: {"watched": 1}, 1: {"watched": 1}}),
            ("now", 2, 10, eps("雲の上の郵便屋さん", 1, 2), {})]
    view = vr.build(items_of(spec), WORKS, {"mine_line": 20}, pieces={10: {"id": 10, "title": None, "kind": "group"}})
    row = view.rows[0]
    lst, i = opened(view, row.key)
    r, fold = _lines(lst, i)[0]
    assert isinstance(fold, vr.Fold)
    at = lst.delegate.episode_at(lst.model().entries[i], lst.visualRect(lst.model().index(i, 0)), r.center())
    assert at is fold
    assert (fold.start, fold.end) == (0, 1)                     # `item_menu` reads `other.episodes[fold.end]`


# --- the review's findings (reviews/a8-fold-register.md), each pinned ------------------------------------------------ #
def test_the_soon_line_running_through_a_row_cuts_its_run_as_the_journey_does():
    """The journey keys a run by its tier: the window's row cut by the Soon line (`soon_from`) folds each side apart."""
    _view, row = _book(n=30, watched=range(20))
    assert [(f.start, f.end) for f in vr.folds(row._replace(soon_from=12))] == [(0, 11), (12, 19)]


def _three(order):
    """Four rows in `order` of A (2 eps), D (30 eps), B (the book, 60 parts, 40 watched) and C (3 eps), *Keep studying
    watched episodes* on and a top-20 line of 25 — so where the line runs depends on the order. -> (view, B's row)."""
    work(5, BOOK, media="book")
    parts = {"A": ("now", 1, 21, eps("星降る街の小さな工房", 1, 2), {}),
             "B": ("now", 5, 20, book_parts(60), {k: {"watched": 1} for k in range(40)}),
             "D": ("now", 2, 22, eps("雲の上の郵便屋さん", 1, 30), {}),
             "C": ("now", 1, 23, eps("星降る街の小さな工房", 3, 5), {})}
    pieces = {p: {"id": p, "title": None, "kind": "run"} for p in (20, 21, 22, 23)}
    view = vr.build(items_of([parts[k] for k in order]), WORKS, {"mine_line": 25, "keep_watched": 1}, pieces=pieces)
    return view, next(r for r in view.rows if r.piece_id == 20)


def test_a_drop_carrying_the_top_20_line_through_the_opened_row_relays_out_never_resets(opened):
    """R1: the opened row's folds are cut by the top-20 line, so a drop moving that line through it changes its line
    count — still a "relayout" (the rows kept in place, the keyboard and hand on theirs), never a reset."""
    view, row = _three("ADBC")
    lst, _i = opened(view, row.key)
    moved, _row = _three("ACBD")
    assert lst.model().set_entries(_entries(moved)) == "relayout"


def test_the_keyboard_on_up_next_stays_on_its_line_as_it_folds_into_the_run(opened):
    """R2: the keyboard on Up next, then it is marked watched (a mark painted ahead, or the store's next view): it joins
    the fold, and the keyboard is on the fold's line — never thrown back to the row's head."""
    view, row = _book()
    lst, i = opened(view, row.key)
    lst.setFocus()
    lst.setCurrentIndex(lst.model().index(i, 0))
    QTest.keyClick(lst, Qt.Key.Key_Down)
    QTest.keyClick(lst, Qt.Key.Key_Down)
    assert lst.ep_key == (row.key, row.episodes[280].id)
    lst.set_entries(_entries(_book(watched=range(281))[0]))
    _settle()
    assert lst.ep_key == (row.key, _lines(lst, i)[0][1].id)


def test_a_rest_keeps_the_fold_pictures_of_the_rows_it_keeps(opened):
    """R4 (S19): `keep_only` keeps a kept row's fold picture as it keeps its episodes' — never drawn again each rest."""
    view, row = _book()
    lst, _i = opened(view, row.key)
    lst.viewport().repaint()
    folds = lambda: [k for k in lst.delegate._sprites["ep"] if isinstance(k[1][0], tuple) and k[1][0][0] == "fold"]
    assert folds()
    lst.delegate.keep_only(lst.model().entries)
    assert folds()


def test_another_row_opened_any_way_opens_folded(opened):
    """R5: a row opened by ⋯'s join or group (`ItemActions._open`: `open_key` set, `opened` sent — not `toggle`) never
    shows the folds the row before had shown whole."""
    view, row = _book(n=12, watched=range(10))
    lst, i = opened(view, row.key)
    _click(lst, _lines(lst, i)[0][0])
    assert lst.unfolded
    model = lst.model()
    other = model.entries[0][1]
    model.open_key = other.key
    lst.relayout()
    lst.opened.emit(other.key)
    assert lst.unfolded == frozenset()
    model.open_key = row.key                         # back to the book: folded, as every opening
    assert lst.unfolded == frozenset()


def test_the_split_seam_beside_a_fold_line_is_the_seams_not_the_folds(opened):
    """R6: the ✂ seam's band under a fold's line (where its parts' piece would split) answers the seam."""
    view, row = _book(n=12, watched=range(10))
    lst, i = opened(view, row.key)
    entry = lst.model().entries[i]
    seam = next(p for p in lst.delegate.parts(entry, lst.visualRect(lst.model().index(i, 0))) if p[0] == "seam")
    for y in (seam[1].top() + 1, seam[1].bottom() - 1):
        assert lst.part_at(QPoint(seam[1].left() + 20, y))[1][0] == "seam"


def test_the_menu_key_on_a_fold_opens_its_rows_menu_as_a_right_click_does(opened):
    """#4: a fold has no ⋯ of its own — the menu key on it opens the row's, the same as the hand's right-click."""
    view, row = _book(n=12, watched=range(10))
    lst, i = opened(view, row.key)
    lst.setFocus()
    lst.setCurrentIndex(lst.model().index(i, 0))
    got = []
    lst.menu_requested.connect(lambda r, _at: got.append(r.key))
    lst.episode_menu_requested.connect(lambda *a: got.append("episode"))
    QTest.keyClick(lst, Qt.Key.Key_Down)
    QTest.keyClick(lst, Qt.Key.Key_Menu)
    assert got == [row.key]


def test_a_fold_click_measures_its_row_alone_and_a_repaint_after_draws_nothing_afresh(opened, monkeypatch):
    """#6 (S19, touch only what changed): a fold's click works out one new height (its row's) — every other row's is a
    look in the kept list — and once painted, a repaint draws no row or line afresh."""
    view, row = _book()
    lst, i = opened(view, row.key)
    lst.viewport().repaint()
    measured = []
    real = rows.RowDelegate._size_hint
    monkeypatch.setattr(rows.RowDelegate, "_size_hint", lambda self, entry, is_open: (measured.append(entry[1].key),
                                                                                       real(self, entry, is_open))[1])
    _click(lst, _lines(lst, i)[0][0])
    lst.viewport().repaint()
    assert measured == [row.key]
    before = lst.delegate.renders
    lst.viewport().repaint()
    assert lst.delegate.renders == before
