"""Up Next's opened list holds still under a click (Mado-UN, 2026-11-18): a click on a part's % in Up Next's opened
list (a book's parts, a show's episodes) jumped the list back to Up Next's top; a row lower in Current never did.

The cause: Up Next's episode lines had no part over their *% · N new* (a row's episode line has one: its word card,
Hover-W), so the press went on to Qt's own, which starts its delayed auto-scroll — a double-click's time later Qt
scrolled the tall opened card's top back into view. Every press on Current's list now leaves the list where it stands,
and Up Next's episode % is a part as a row's is (hover shows its words, a click keeps them open).

What a wrong answer would cost a learner: the part he clicked slides away under his hand, and he loses his place in a
long book or show — on the one row he is working through.

On the window's seed (invented titles), Japanese and Chinese; Up Next a show (its hato episodes) or a book (Current's
light novel put first). Every signal a click sends from the list is caught here, so nothing plays or writes.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.qt import rows, style
from tests.fixtures import window_seed
from tests.qt.test_current import _settings
from tests.qt.test_drag import FakeWriter, open_window, press, release, settle
from tests.qt.test_item_menu import hover


@pytest.fixture
def up_next(qapp):
    """(language, kind) -> (window, its Current list), Up Next opened and scrolled so its head is above the list's top
    — the place the report was in: lower down a long opened Up Next."""
    made = []

    def make(language, kind):
        if language == "zh":
            _settings(target_language="zh", zh_script="s")
        seed = window_seed.build(language=language)
        win, services = open_window(qapp, seed, FakeWriter(seed.library, apply=False), size=(1280, 560))
        made.append((win, services))
        page = win.page_widgets["current"]
        if kind == "book":                           # Current's light novel as Up Next: a book's parts
            view = page.view_model
            rs = list(view.rows)
            i = next(k for k, r in enumerate(rs) if r.media == "lightnovel")
            rs.insert(0, rs.pop(i))
            win.show_library(view._replace(rows=type(view.rows)(rs)))
            settle()
        lst = page.list
        entry = lst.model().entries[0]
        assert entry[0] == rows.HERO and (entry[1].media == "lightnovel") == (kind == "book")
        lst.toggle(lst.model().index(0, 0))
        settle()
        bar = lst.verticalScrollBar()
        bar.setValue(lst.delegate._hero_head_h() + 4)            # the head just past the top
        settle()
        assert bar.value() > 0 and lst.visualRect(lst.model().index(0, 0)).top() < 0, "Up Next's top is off-screen"
        return win, lst
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)
    style.apply(qapp, "night", "M", "ja")            # the harness puts back theme and size, not the language


def _lines(lst):
    """Up Next's episode lines fully on screen now: [(QRect, Episode)] (a8's folds left out)."""
    vp = lst.viewport().rect()
    entry = lst.model().entries[0]
    return [(r, ep) for r, ep in lst.delegate.episode_lines(entry, lst.visualRect(lst.model().index(0, 0)))
            if vp.contains(r) and isinstance(ep, rows.view_rows.Episode)]


def _caught(lst):
    """Every signal a click on the list sends, disconnected from the window and caught: [(signal name, args)]."""
    got = []
    for name in ("play_requested", "done_requested", "episode_menu_requested", "menu_requested", "words_keep",
                 "mine_requested", "journey_requested", "split_requested", "opened"):
        sig = getattr(lst, name)
        try:
            sig.disconnect()
        except TypeError:
            pass
        sig.connect(lambda *a, n=name: got.append((n, a)))
    return got


def _click_held(lst, at):
    """A click at `at` (the viewport's), then a double-click's time and more — Qt's delayed auto-scroll would run
    there. -> (the scroll bar's value before, after the click at once, after the wait)."""
    bar = lst.verticalScrollBar()
    before = bar.value()
    press(lst, at)
    release(lst, at)
    QApplication.processEvents()
    now = bar.value()
    QTest.qWait(QApplication.doubleClickInterval() + 300)
    QApplication.processEvents()
    assert lst.hasAutoScroll(), "the press gives Qt's auto-scroll back: the keyboard still brings a row into view"
    return before, now, bar.value()


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("kind", ["show", "book"])
def test_a_click_on_a_lower_parts_percent_in_up_next_keeps_the_list_and_the_part_where_they_are(up_next, language,
                                                                                                kind):
    """The report: Up Next opened, scrolled down its list, a click on a part's % — the list jumped to its top. The
    list and the clicked part stay put, Up Next stays open, and the click's own action happens at once: the part's
    word card kept open (a row's episode does the same)."""
    win, lst = up_next(language, kind)
    lines = [(r, ep) for r, ep in _lines(lst) if ep.n_new is not None]
    assert lines, "a part with its % · N new on screen"
    r, ep = lines[-1]                                # the lowest one on screen
    got = _caught(lst)
    diff = lst.delegate._episode_cols(r)["diff"]
    before, now, after = _click_held(lst, diff.center())
    assert (now, after) == (before, before), "the list holds still under the hand"
    assert [(n, a[1].id) for n, a in got if n == "words_keep"] == [("words_keep", ep.id)], \
        "the click keeps the part's word card open, at once"
    assert lst.model().open_key == lst.model().entries[0][1].key, "Up Next stays open"
    entry = lst.model().entries[0]
    assert lst.delegate.episode_at(entry, lst.visualRect(lst.model().index(0, 0)), diff.center()).id == ep.id, \
        "the part clicked is still under the hand"


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("kind", ["show", "book"])
@pytest.mark.parametrize("where", ["label", "stone", "play", "more-ep", "status"])
def test_every_other_place_on_an_up_next_part_holds_the_list_still_too(up_next, language, kind, where):
    """The card's check: ▶, ✓ (the stone: the part's Done), the part's own ⋯, its status — and the bare label between
    them. The label is no part: its press went on to Qt's, the same delayed auto-scroll as the % (red before the fix).
    The four buttons are parts, whose press never reached Qt's: they held still before the fix too, and are kept here
    as the guard that they still do. Each leaves the list where it stands; a part's click still sends its ask at once."""
    win, lst = up_next(language, kind)
    lines = _lines(lst)
    assert lines
    entry = lst.model().entries[0]
    rect = lst.visualRect(lst.model().index(0, 0))
    want = {"stone": "done_requested", "play": "play_requested", "more-ep": "episode_menu_requested"}.get(where)
    at = None
    for r, ep in reversed(lines):                    # the lowest line that has the place asked
        if where == "label":
            at = r.adjusted(rows.EP_LABEL_IN + 4, 0, 0, 0).topLeft() + type(r.topLeft())(0, r.height() // 2)
            break
        hover(lst, r.center())
        found = [pt for pt in lst.delegate.parts(entry, rect, near=r) if pt[0] == where and pt[3] is not None and
                 getattr(pt[3], "id", getattr(getattr(pt[3], "episode", None), "id", None)) == ep.id] if \
            where != "status" else [pt for pt in lst.delegate.parts(entry, rect, near=r)
                                    if r.contains(pt[1].center()) and pt[0] not in
                                    ("stone", "play", "more-ep", rows.NEW_PART, "fold", "seam")]
        if found:
            at = found[0][1].center()
            break
    if at is None:
        pytest.skip(f"no part on screen has {where} in this seed")
    hit = lst.part_at(at)[1]
    if where == "label":
        assert hit is None, "the bare label is no part"
    else:
        assert hit is not None and hit[1] == found[0][1] and hit[0] == found[0][0], "the click lands on that part"
    got = _caught(lst)
    before, now, after = _click_held(lst, at)
    assert (now, after) == (before, before), "the list holds still under the hand"
    assert lst.model().open_key == entry[1].key, "Up Next stays open"
    if want is not None:
        assert [n for n, _a in got if n == want] == [want], "its ask is sent at once"
    for m in QApplication.topLevelWidgets():         # ⋯'s menu, if one opened, closed again
        if m.objectName() in ("rowmenu", "epmenu") and m.isVisible():
            m.close()
