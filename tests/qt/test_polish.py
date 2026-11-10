"""W2.3: the first screens polished to Sonic's G2.3 notes (the planning folder's `tracks/window/notes/G2.3.md`
§ Sonic's notes): the alignment (A1–A4), the rows and chips (R1–R5), the Soon line (L1), the tooltips (T1), Needs you
(N1, N2) and the window's frame (C1–C3). Most rows were written by haiku-code (Haiku writers, one rule each, each test
proved to fail with its mutant in: `research/haiku-code/W2.3/`), read and kept by the builder.
"""
import os
import sys

import numpy as np
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QRect, Qt
from PyQt6.QtGui import QColor, QFocusEvent, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import motion, rows, screens, shell, stones, style
from app.services import status as status_service
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.pixels import count, rgb, rgb_array
from tests.qt.test_current import _stones_sheet, current, grab, part, seeded   # noqa: F401  (fixtures)
from tests.qt.test_shell import _snap, services, window         # noqa: F401  (window / services are fixtures)


# --- G1 --------------------------------------------------------------------------------------------------------------
def test_an_open_rows_episodes_stand_in_the_shows_columns(seeded):
    """Each episode's % · new stands in its show row's own % · new column (the same left, the same width), and its
    status ends where the row's Anki count does — a gap before % · new. Why: the episodes must line up under the
    show's columns; a shift of even a few pixels reads as a ragged table. (W3.1a: the row is one line, its ▶ in the
    hover group over the string's end, so the episode's ▶ stands before its own status instead.)"""
    seed, win = seeded()
    lst = current(win)
    d = lst.delegate
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries)
                              if e[0] == rows.ROW and e[1].episodes and e[1].status.kind == "in_anki")
    before = lst.visualRect(lst.model().index(i, 0)).height()
    lst.toggle(lst.model().index(i, 0))
    assert wait_until(lambda: lst.visualRect(lst.model().index(i, 0)).height() > before)
    QApplication.processEvents()

    rect = lst.visualRect(lst.model().index(i, 0))
    slab = d.slab_of(rect)
    show = d.line_geometry(row, slab, opened=True)
    assert show["stat"].width() > 0, "the row shows its Anki count, or the status check proves nothing"
    episodes = d._episode_rows(row, QRect(rect.left(), slab.bottom() + 1, rect.width(), rect.bottom() - slab.bottom()))
    assert episodes, "an open row with episodes must list them, or this test checks nothing"
    for r, _ep in episodes:
        cols = d._episode_cols(r)
        assert cols["diff"].left() == show["diff"].left()
        assert cols["diff"].width() == show["diff"].width()
        assert cols["stat"].right() == show["stat"].right()     # the status ends where the Anki count does
        assert cols["play"].right() < cols["stat"].left()        # ... and its ▶ stands before it


# --- G2 --------------------------------------------------------------------------------------------------------------
def test_an_open_rows_episode_labels_start_where_the_shows_title_does(seeded):
    """G2.3 A2: opening a row puts each episode's label at the show's title x (the same column), not further left."""
    seed, win = seeded()
    lst = current(win)
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries)
                              if e[0] == rows.ROW and len(e[1].episodes) > 0)
    before = lst.visualRect(lst.model().index(i, 0)).height()
    lst.toggle(lst.model().index(i, 0))
    assert wait_until(lambda: lst.visualRect(lst.model().index(i, 0)).height() > before)
    rect = lst.visualRect(lst.model().index(i, 0))
    title_x = lst.delegate.line_geometry(row, lst.delegate.slab_of(rect))["main"].left()   # W3.1a: the one-line row
    eps = lst.delegate._episode_rows(row, rect)
    assert eps, "an open row with episodes must lay out its episode rects"
    for r, _ep in eps:
        # why: the label's left is what a learner's eye lines up with the title above it
        assert lst.delegate._episode_cols(r)["text_left"] == title_x


def test_the_open_heros_episode_labels_start_where_its_title_does(seeded):
    """G2.3 A2: the open hero's episode labels start at the hero's title column, not further left."""
    seed, win = seeded()
    lst = current(win)
    kind, hero, lines = lst.model().entries[0]
    assert kind == rows.HERO
    lst.toggle(lst.model().index(0, 0))
    assert wait_until(lambda: lst.model().open_key == hero.key)
    rect = lst.visualRect(lst.model().index(0, 0))
    g = lst.delegate._hero_geometry(hero, rect, lines)
    eps = lst.delegate._episode_rows(hero, g["eps"], hero=True)
    assert eps, "the open hero must lay out its episode rects"
    for r, _ep in eps:
        assert lst.delegate._episode_cols(r)["text_left"] == g["title"].left()


# --- G3 --------------------------------------------------------------------------------------------------------------
DPR = 4.0


def test_a_rows_string_runs_along_the_rows_midline(seeded):
    """W3.1a (the chips are gone: the mined chip's dot retired for the string that took its place): the string's
    hairline, from the first stone's centre to the last's, sits on the row's midline (± 0.75 px) at 400 %. Why: a
    string above or below the line's middle reads as lifted beside the title and the numbers."""
    seed, win = seeded()
    lst = current(win)
    d = lst.delegate
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries)
                              if e[0] == rows.ROW and len(e[1].episodes) >= 3)
    slab = d.slab_of(lst.visualRect(lst.model().index(i, 0)))
    w, h = slab.width(), slab.height()
    sheet = stones.build(DPR, "M")
    img = QImage(int(w * DPR), int(h * DPR), QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(DPR)
    img.fill(rows.c("surface"))
    p = QPainter(img)
    try:
        d._paint_current(p, row, QRect(0, 0, w, h), False, DPR, sheet, tw=d.title_w(w))
    finally:
        p.end()
    g = d.line_geometry(row, QRect(0, 0, w, h), d.title_w(w))
    arr = rgb_array(img)[:, int(g["gstr"].left() * DPR):int(g["gstr"].right() * DPR)]
    hairline = (np.abs(arr.astype(np.int16) - rgb(theme.ROW_COLOURS["string"])) <= 3).all(axis=2).sum(axis=1)
    hits = np.where(hairline > 8)[0]
    assert len(hits) >= 2, "the string's hairline is not painted at all"
    mid = (hits.min() + hits.max() + 1) / 2.0 / DPR
    assert abs(mid - h / 2.0) <= 0.75, f"hairline midline {mid} vs the row's {h / 2.0}"


# --- G4 --------------------------------------------------------------------------------------------------------------
def test_a_row_number_is_drawn_whole_at_large_text(qapp, seeded, monkeypatch):
    """A five-digit place at Large text is wider than the slot: the drawer must still get its full advance."""
    seed, win = seeded()
    lst = current(win)
    theme_name, _size, language = style.current()
    style.apply(qapp, theme_name, "L", "ja")       # a larger text size, so the number's slot is narrow
    try:
        rect = lst.visualRect(lst.model().index(0, 0))
        row = lst.model().entries[0][1]._replace(index=12345)
        real_draw = rows.TEXT.draw
        calls = []

        def spy(p, x, y_mid, text, role, width, *rest, **kw):
            # measured at the moment of the draw, with the same metrics the drawer's caller uses
            advance = rows.TEXT.metrics(role, dpr=1.0).horizontalAdvance(text)
            drawn = real_draw(p, x, y_mid, text, role, width, *rest, **kw)
            calls.append((text, role, width, advance, drawn))
            return drawn

        monkeypatch.setattr(rows.TEXT, "draw", spy)
        img = QImage(rect.width(), rect.height(), QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        try:
            lst.delegate._paint_number(p, row, QRect(0, 0, rect.width(), rect.height()), 1.0)
        finally:
            p.end()

        assert len(calls) == 1, "the number is drawn exactly once"
        text, role, width, advance, (drawn_w, elided) = calls[0]
        assert text == "12345"
        assert width >= advance, f"drawn in {width}px, but the number needs {advance}px"
        # what the drawer really drew: whole (`elidedText` measures tabular figures wider than `horizontalAdvance`,
        # so a number is drawn with `elide=False`, never cut — the first try at +2 px still cut it: haiku-code G4)
        assert not elided and drawn_w >= advance
    finally:
        style.apply(qapp, theme_name, "M", language)


# --- G5 --------------------------------------------------------------------------------------------------------------
def test_a_key_press_shows_the_focus_ring_and_a_click_on_a_row_takes_it_away(seeded):
    """The ring is for the keyboard only (CSS's :focus-visible). A key press in the list shows it; a mouse press on a
    row hides it again, so a learner who clicks a row sees no ring around the row he picked."""
    seed, win = seeded()
    lst = current(win)
    assert not lst.focus_visible                  # starts hidden: nothing has been pressed yet

    QTest.keyClick(lst, Qt.Key.Key_Down)          # the key press alone must raise the flag (no Tab focus here)
    assert lst.focus_visible

    row = next(n for n, e in enumerate(lst.model().entries)        # a closed row fully on screen to click
               if e[0] == rows.ROW and lst.viewport().rect().contains(
                   lst.visualRect(lst.model().index(n, 0)).center()))
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton,
                     pos=lst.visualRect(lst.model().index(row, 0)).center())   # a click on a row may also open it
    assert not lst.focus_visible                  # the click alone must lower the flag


# --- G6 --------------------------------------------------------------------------------------------------------------
def test_an_open_rows_episodes_stand_on_the_opened_rows_ground_not_a_surface(seeded):
    """G2.3 R1, as W3.1a builds it: an open row (not the hero) has no surface card under its episodes — they stand on
    the opened row's own ground (`open-row`, list-r14m :705, flat), and the surface does not show."""
    seed, win = seeded(size=(1280, 1100))
    lst = current(win)
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries)
                              if e[0] == rows.ROW and len(e[1].episodes) == 8)
    before = lst.visualRect(lst.model().index(i, 0)).height()
    lst.toggle(lst.model().index(i, 0))
    assert wait_until(lambda: lst.visualRect(lst.model().index(i, 0)).height() > before)
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    # No hover: the pointer is not over the row, so the row paints its plain (unhovered) look.
    QApplication.sendEvent(lst.viewport(), QEvent(QEvent.Type.Leave))
    QApplication.processEvents()
    rect = lst.visualRect(lst.model().index(i, 0))
    head = theme.ROW_LINE["gap"] // 2 + lst.delegate._line_h()        # the slab's top, then its one line
    # The episodes' area under the row's head, inset so the rule line and the row's edges stay out of it.
    area = QRect(rect.left(), rect.top() + head, rect.width(), rect.height() - head).adjusted(12, 4, -12, -4)
    arr = rgb_array(lst.viewport().grab(area))
    total = area.width() * area.height()
    c = style.colours()
    # Why: a surface box under the episodes is the old look (the card's ground); it must not come back on a row.
    assert count(arr, theme.ROW_COLOURS["open-row"], 2) > total * 0.5
    assert count(arr, c["surface"], 2) < total * 0.02


# --- G7 --------------------------------------------------------------------------------------------------------------
def test_needs_you_count_sits_on_the_cracked_amber_stone(window):
    # One unseen failure shows the tab with its count on a stone (W3.2 Q5: the cracked amber stone, ref-extract
    # row 115): a solid block of the stone's dark amber fill (a plain count would paint none of it), the number in warn.
    unseen = status_service.Entry("Command line (status): it failed", "t", False)
    window.show_status(_snap(needs_you=(unseen,)))
    tab = window.tab_buttons["needs"]
    assert not tab.isHidden()
    pixels = rgb_array(tab.grab())
    assert count(pixels, theme.NEEDS_STONE["fill"], 6) >= 60
    assert count(pixels, style.colours()["warn"], 30) >= 5


# --- G8 --------------------------------------------------------------------------------------------------------------
def test_a_tab_whose_count_did_not_change_is_not_set_again(window, monkeypatch):
    # why: a repeated poll with the same unseen count must not relayout or repaint the Needs you tab
    needs = window.tab_buttons["needs"]
    original = needs.set_name
    calls = []

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(needs, "set_name", spy)
    failed = status_service.Entry("Command line (status): it failed", "t", False)
    other = status_service.Entry("Command line (other): it failed", "t", False)

    window.show_status(_snap(needs_you=(failed,)))          # count 0 → 1: set once
    assert len(calls) == 1
    window.show_status(_snap(needs_you=(failed,)))          # same count again: not set
    assert len(calls) == 1
    window.show_status(_snap(needs_you=(failed, other)))    # count 1 → 2: set once more
    assert len(calls) == 2


# --- G9 --------------------------------------------------------------------------------------------------------------
@pytest.fixture
def bubble(qapp):
    from app.qt import tooltip
    b = tooltip.Bubble()
    yield b
    # cleanup in a fixture so a failing assertion still closes the widget
    b.close()
    b.deleteLater()


def _blocks(doc):
    block = doc.begin()
    while block.isValid():
        yield block
        block = block.next()


def test_a_tooltips_bullet_line_hangs_under_its_first_word(qapp, bubble):
    # a plain tip with a "• " line is turned into paragraphs: the bullet's line is indented (wrapped words stay
    # under its first word), the first line stays flush at the edge
    bubble.set_text("No video on disk\n• Link one for pictures and audio, or mine the text on its own")
    blocks = list(_blocks(bubble._doc))
    assert len(blocks) == 2
    first, bullet = blocks
    assert first.blockFormat().leftMargin() == 0
    assert first.blockFormat().textIndent() == 0
    assert bullet.text().startswith("•")
    assert bullet.blockFormat().leftMargin() > 0, "the bullet's line must sit in from the edge"
    assert bullet.blockFormat().textIndent() < 0, "the first word hangs out so wrapped words line up under it"


def test_a_tooltip_action_is_on_its_own_line_and_never_in_brackets():
    # the action of a tip, mark or play line starts on a new line as "• "; no "( … )" a line break could cut
    for key, text in view_rows.STRINGS.items():
        if not isinstance(text, str) or not key.startswith(("tip_", "play", "mark_")):
            continue
        assert "(" not in text, f"{key} must not hold a bracket"
        for i in range(len(text)):
            if text.startswith("• ", i):
                assert i > 0 and text[i - 1] == "\n", f"{key}: the bullet must sit right after a newline"


# --- G10 --------------------------------------------------------------------------------------------------------------
def test_a_needs_you_card_says_what_waits_under_its_title(seeded):
    # Why (W3.2 Q5): the painted card's line moved into the card as its own words, under the title, with its buttons:
    # what waits and what each answer does are read before a button is pressed.
    from PyQt6.QtWidgets import QLabel
    from app import path_utils
    os.makedirs(path_utils.get_data_path("ja"), exist_ok=True)
    seed, win = seeded()
    ny = win.needs_you
    ny.data_dir = path_utils.get_data_path("ja")
    n = ny.gathers
    ny.refresh()
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    gone = next(e for e in ny.entries if e.kind == "file-gone")
    assert gone.say, "the seed's Needs-you card must carry its line, or this test proves nothing"
    words = [lab.text() for lab in ny.cards.card(gone.key).findChildren(QLabel)]
    assert words[:2] == [gone.title, gone.say]


# --- G11 --------------------------------------------------------------------------------------------------------------
def test_the_bars_line_starts_at_the_bars_own_edge(window):
    # why (W3.1a): with the pulsing dot gone, the status line opens the bar itself, at the bar's left padding, not
    # after a hole where the dot was — since the phase strip (2026-10-23), the strip opens it there and the line
    # follows it at the bar's own spacing
    window.bar_line.set_full("Couldn't open Ep 1: no video beside it on disk")
    QApplication.processEvents()
    line, row = window.bar_line.geometry(), window.footer.layout()
    assert line.width() > 0, "the bar is not laid out, so its edge would be meaningless"
    assert window.phase.geometry().left() <= row.contentsMargins().left() + 1
    assert line.left() <= window.phase.geometry().right() + 1 + row.spacing() + 1


# --- G12 --------------------------------------------------------------------------------------------------------------
def _matches(colour, target, tol=6):
    """Each channel of `colour` is within `tol` of `target` (the box's 1 px border, drawn with antialiasing)."""
    return all(abs(a - b) <= tol for a, b in zip(
        (colour.red(), colour.green(), colour.blue()), (target.red(), target.green(), target.blue())))


def test_the_goal_dock_spans_its_page_edge_to_edge(seeded):
    """W3.1a: Goal's dock is part of the bottom band, the page's full width with no side margins of its own (its bar
    keeps the dock's padding inside, `theme.FRAME["dock-pad"]`)."""
    seed, win = seeded()
    dock = win.dock
    assert dock.isVisible() and dock.width() == dock.parentWidget().width()
    bar = dock.bar_rect()
    assert 0 < bar.left() and bar.right() < dock.width()


# --- G13 --------------------------------------------------------------------------------------------------------------
def _over(top, ground):
    r, g, b, a = theme.parse(top)
    gr, gg, gb, _ga = theme.parse(ground)
    return "#%02x%02x%02x" % tuple(round(t * a + u * (1 - a)) for t, u in ((r, gr), (g, gg), (b, gb)))


def test_the_soon_line_is_a_quiet_lit_lip_with_no_word(seeded):
    """G2.3 L1, as W3.1a builds it: the Soon line is the top-20 groove made quieter — its lit lip alone (1 px), no dark
    line and no word — in its own strip, the row's last; so it reads quieter than the top-20 line (groove and lip)."""
    seed, win = seeded()
    lst = current(win)
    i = next(i for i, e in enumerate(lst.model().entries) if any(ln.kind == "soon" for ln in e[2]))
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    QApplication.sendEvent(lst.viewport(), QEvent(QEvent.Type.Leave))     # unlit: not under the hand
    QApplication.processEvents()
    col = style.colours()
    rect, arr = grab(lst, i)
    strip = arr[rect.height() - theme.ROW_LINE["line"]:]                  # the strip the Soon line is painted in
    width = strip.shape[1]
    lip = _over(col["groove-lip"], col["bg"])
    best = max(count(strip[r:r + 1], lip, tolerance=2) for r in range(strip.shape[0]))
    assert best >= 0.9 * width                       # one pixel row of the strip is the lip, across the row
    assert count(strip, col["groove"], tolerance=1) == 0       # no dark groove line: quieter than the top-20 line
    assert count(strip, col["ink-faint"], tolerance=10) == 0   # no word in the faint ink ...
    assert count(strip, col["ink-dim"], tolerance=10) == 0     # ... nor in the dim ink


# --- the builder's own rows (W2.3 round 2) ----------------------------------------------------------------------------
def test_try_screens_shows_the_mark_beside_the_name(qapp, monkeypatch):
    """G2.3 C1: the local build's header showed no logo — the test root is where bundled resources are read, and the
    build's temp root had none. try_screens copies them, so the mark is there and shown."""
    from app.qt import shell as shell_module
    from tests.qt import try_screens
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")          # try_screens pops it: put back after the test
    monkeypatch.setenv("SURASURA_TEST_ROOT", os.environ.get("SURASURA_TEST_ROOT", ""))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)      # prepare_process sets its own: put back after
    monkeypatch.setattr(shell_module, "prepare_process", lambda: None)
    seen = {}
    real_open = shell_module.open_window

    def opened(app, services):
        win = real_open(app, services)
        seen["win"] = win
        return win
    monkeypatch.setattr(shell_module, "open_window", opened)

    def exec_once(_app):
        QApplication.processEvents()
        win = seen["win"]
        seen["icon"] = win.mark._icon is not None and not win.mark.isHidden()
        win.close()
        return 0
    monkeypatch.setattr(QApplication, "exec", exec_once)
    assert try_screens.main(["--files", "0"]) == 0
    assert seen["icon"], "the header's mark must be found and shown in the local build"


@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_the_footer_is_the_taskbars_height_at_every_text_size(qapp, window, size):
    """G2.3 C3: the footer is 39 px (+ its 1 px line = the taskbar's 40) whatever the text size, never grown with it."""
    theme_name, _size, language = style.current()
    style.apply(qapp, theme_name, size, language)
    try:
        window._apply_sizes()
        QApplication.processEvents()
        assert window.footer.height() == 39
    finally:
        style.apply(qapp, theme_name, "M", language)


def test_studying_first_is_an_arrow_and_words_with_no_pill_under_them(qapp, monkeypatch):
    """G2.3 R3: "↑ Studying its cards first" read badly as words over a pill. The mark is drawn on the row's own
    ground: the pill's colour is never asked for, and the rows just above and below the words stay the ground."""
    asked = []
    real_c = rows.c
    monkeypatch.setattr(rows, "c", lambda name: (asked.append(name), real_c(name))[1])
    image = QImage(400, 60, QImage.Format.Format_RGB32)
    ground = QColor(style.colours()["bg"])
    image.fill(ground)
    p = QPainter(image)
    delegate = rows.RowDelegate.__new__(rows.RowDelegate)      # only its painting helpers, no list behind it
    width = delegate._paint_studying(p, 10, 30, 1.0)
    p.end()
    assert width > 0
    assert "badge-new" not in asked, "the old pill's fill came back under the words"
    half = round(19 * rows.fz()) / 2                            # the old pill: 19 f tall, filled, on the midline
    arr = rgb_array(image)
    for y in (round(30 - half + 1), round(30 + half - 2)):      # just inside its top and bottom edges (D-2)
        band = arr[y:y + 1, 10:10 + width]
        assert count(band, ground.name(), 2) == band.shape[1], f"something drawn {y - 30} px off the midline"


def test_a_click_back_into_the_list_after_using_the_keyboard_repaints_nothing(seeded):
    """S19 (review C-1): after a keyboard visit the ring goes with the focus; a later click back into the list shows no
    ring, so the focus-in and the press repaint no row (only the click's own current-row change could)."""
    seed, win = seeded()
    lst = current(win)
    win.tab_buttons["current"].setFocus(Qt.FocusReason.TabFocusReason)
    for _ in range(5):
        QApplication.processEvents()
    lst.setFocus(Qt.FocusReason.TabFocusReason)                 # by the keyboard: the ring shows
    for _ in range(5):
        QApplication.processEvents()
    assert lst.focus_visible
    win.tab_buttons["current"].setFocus(Qt.FocusReason.TabFocusReason)   # away again: the ring goes, one repaint
    for _ in range(5):
        QApplication.processEvents()
    assert not lst.focus_visible
    before = lst.delegate.paints
    lst.setFocus(Qt.FocusReason.MouseFocusReason)               # back by a click: no ring, nothing to repaint
    for _ in range(5):
        QApplication.processEvents()
    assert lst.hasFocus() and not lst.focus_visible
    assert lst.delegate.paints == before, lst.delegate.paints - before


def test_the_window_losing_focus_keeps_the_keyboards_ring_for_its_return(seeded):
    """A learner using the keyboard who switches to another program and back finds his ring where it was: only
    leaving for another widget forgets the keyboard (CSS's :focus-visible)."""
    seed, win = seeded()
    lst = current(win)
    lst.setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    assert lst.focus_visible
    QApplication.sendEvent(lst, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason))
    assert lst.focus_visible
    QApplication.sendEvent(lst, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.MouseFocusReason))
    assert not lst.focus_visible


def test_a_bullets_wrapped_words_hang_exactly_under_its_first_word(qapp, bubble):
    """Review C-3: the hanging indent is the bullet and its space as the tip's font measures them, so a wrapped line
    starts where the first word does (a fixed 11 px sat 2–4 px off at Medium)."""
    from PyQt6.QtGui import QFontMetricsF
    bubble.set_text("No video on disk\n• Link one for pictures and audio, or mine the text on its own")
    bullet = list(_blocks(bubble._doc))[1]
    expected = round(QFontMetricsF(bubble._doc.defaultFont()).horizontalAdvance("• "))
    assert bullet.blockFormat().leftMargin() == expected
    assert bullet.blockFormat().textIndent() == -expected


def test_a_tip_that_starts_with_a_bullet_is_bulleted_too(qapp, bubble):
    """Review C-4: a tip whose first line is a bullet hangs it like any other, rather than showing the raw text."""
    bubble.set_text("• Link a video for pictures and audio")
    first = list(_blocks(bubble._doc))[0]
    assert first.text().startswith("•")
    assert first.blockFormat().leftMargin() > 0 and first.blockFormat().textIndent() < 0


@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_the_header_and_tabs_stand_as_tall_as_the_mocks(qapp, window, size):
    """Side-by-side V-4: the wordmark's line is the mock's (`line-height: 1.05`, not the font's ~1.33) and a tab's
    padding is the mock's 10 / 9 px at every text size; the header was ~5 px and the tab bar ~3 px taller."""
    import math
    from PyQt6.QtGui import QFontMetrics
    theme_name, _size, language = style.current()
    style.apply(qapp, theme_name, size, language)
    try:
        px, _weight = theme.font("wordmark", size)
        assert window.wordmark.sizeHint().height() == math.ceil(px * 1.05)
        tab = window.tab_buttons["current"]
        assert tab.sizeHint().height() == 10 + QFontMetrics(tab.font()).height() + 9 + 2
    finally:
        style.apply(qapp, theme_name, "M", language)


def test_no_video_is_a_struck_camera_and_no_audio_a_struck_speaker(qapp, monkeypatch):
    """Side-by-side: the mock's No video glyph is a camera struck through (`i-novid`), an audio show's a speaker
    (`i-noaud`, its `noIco`); the build drew ⌀ for both. The pill and the on-disk mark ask for the one their show's
    media names."""
    asked = []
    real_icon = rows.icon
    monkeypatch.setattr(rows, "icon", lambda p, kind, *a, **kw: (asked.append(kind), real_icon(p, kind, *a, **kw))[1])
    status = view_rows.Status("no_media", "No audio", "No audio on disk", "warn")
    mark = view_rows.Mark(2, "warn", "No audio on disk for Ep 1, Ep 2")
    image = QImage(200, 40, QImage.Format.Format_RGB32)
    image.fill(QColor(style.colours()["bg"]))
    p = QPainter(image)
    rows.paint_pill(p, status, QRect(4, 8, 120, 24), 1.0, audio=True)
    rows.paint_mark(p, mark, 190, 20, 1.0, audio=True)
    rows.paint_pill(p, status._replace(label="No video"), QRect(4, 8, 120, 24), 1.0)
    rows.paint_mark(p, mark, 190, 20, 1.0)
    p.end()
    assert asked == ["no_audio", "no_audio", "no_media", "no_media"]
    shapes = []
    for kind in ("no_media", "no_audio"):
        img = QImage(32, 32, QImage.Format.Format_RGB32)
        img.fill(QColor("#000000"))
        q = QPainter(img)
        real_icon(q, kind, QRect(0, 0, 32, 32), QColor("#ffffff"))
        q.end()
        shapes.append(rgb_array(img))
    assert (shapes[0] != shapes[1]).any(), "the two glyphs must differ"


def test_a_click_on_a_row_leaves_no_ring_when_the_row_is_painted_again(seeded, monkeypatch):
    """G2.3 R1 as Sonic sees it (review D-1): after the keyboard showed the ring, a click on a row and any later repaint
    of the list (a hover, a scroll) draw no focus ring at all — the flag alone could be right while the paint ignored
    it."""
    seed, win = seeded()
    lst = current(win)
    rings = []
    real_ring = lst.delegate._focus_ring
    monkeypatch.setattr(lst.delegate, "_focus_ring", lambda *a, **kw: (rings.append(1), real_ring(*a, **kw))[1])
    lst.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(lst, Qt.Key.Key_Down)
    lst.viewport().repaint()
    QApplication.processEvents()
    assert rings, "the keyboard's ring must be drawn, or this test proves nothing"
    i = next(n for n, e in enumerate(lst.model().entries)
             if e[0] == rows.ROW and lst.viewport().rect().contains(lst.visualRect(lst.model().index(n, 0)).center()))
    rect = lst.visualRect(lst.model().index(i, 0))
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QApplication.processEvents()
    rings.clear()
    lst.viewport().repaint()                                   # every row on screen painted again
    QApplication.processEvents()
    assert lst.hasFocus()
    assert rings == [], "a click left the focus ring on screen"


def test_a_modifier_key_alone_shows_no_ring(seeded):
    """Review D-6: Ctrl, Shift or Alt held for a Ctrl+wheel or a Shift+click is no keyboard navigation (CSS's
    :focus-visible ignores them); an arrow is."""
    seed, win = seeded()
    lst = current(win)
    lst.setFocus(Qt.FocusReason.MouseFocusReason)
    for key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
        QTest.keyClick(lst, key)
        assert not lst.focus_visible, key
    QTest.keyClick(lst, Qt.Key.Key_Down)
    assert lst.focus_visible


def test_the_finished_tab_is_not_set_again_when_its_count_did_not_change(seeded, monkeypatch):
    """Review D-8 (S19): the Finished tab, like Needs you's, is set again only when its count changed."""
    seed, win = seeded()
    view = win.services.library.view()
    assert view is not None and view.counts.finished > 0, "the seed must finish something, or this proves nothing"
    tab = win.tab_buttons["finished"]
    calls = []
    real = tab.set_name
    monkeypatch.setattr(tab, "set_name", lambda *a, **kw: (calls.append(a), real(*a, **kw))[1])
    win.show_library(view)                                     # the same count again: not set
    assert calls == []
    win.show_library(view._replace(counts=view.counts._replace(finished=view.counts.finished + 1)))
    assert len(calls) == 1                                     # a new count: set once


# --- W3.1a: the one-line row's columns ----------------------------------------------------------------------------------
@pytest.mark.parametrize("width", [1024, 1280])
@pytest.mark.parametrize("size", ["S", "M", "L"])
def test_every_current_rows_title_string_and_numbers_line_up_at_every_size_and_width(qapp, seeded, size, width):
    """W3.1a §1 *Rows*: one title width for every row, so the titles, the strings and the numbers stand in columns
    down the list — at Small, Medium and Large, at 1024 and 1280 wide. Each row is one line (60 × the text size), and
    the string keeps room between the title and the Anki count. Why: a list whose strings start at different places
    reads as a ragged table, and a learner compares rows by their strings."""
    seed, win = seeded(size=(width, 800))
    lst = current(win)
    theme_name, _size, language = style.current()
    style.apply(qapp, theme_name, size, language)
    try:
        d = lst.delegate
        f = rows.fz()
        geos = []
        for i, (kind, row, lines) in enumerate(lst.model().entries):
            if kind != rows.ROW or row.key == lst.model().open_key:
                continue
            rect = lst.visualRect(lst.model().index(i, 0))
            slab = d.slab_of(rect)
            assert slab.height() == round(theme.ROW_LINE["height"] * f)          # one line at every size
            geos.append(d.line_geometry(row, slab))
        assert len(geos) >= 4, "the seed puts several rows in Current, or nothing lines up"
        for name, edge in (("main", "left"), ("main", "width"), ("gstr", "left"), ("diff", "left"), ("diff", "width"),
                           ("stat", "right"), ("art", "left"), ("art", "width")):
            assert len({getattr(g[name], edge)() for g in geos}) == 1, (name, edge, size, width)
        g = geos[0]
        assert g["main"].width() >= round(80 * f)                                # the title's floor
        assert g["art"].right() < g["main"].left() < g["main"].right() < g["gstr"].left()
        assert g["gstr"].right() < g["stat"].left() and g["stat"].left() + g["stat"].width() < g["diff"].left()
        assert g["diff"].right() <= lst.viewport().width()                     # nothing pushed off the row
    finally:
        style.apply(qapp, theme_name, "M", language)
