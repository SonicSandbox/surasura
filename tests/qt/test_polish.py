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
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import theme
from app.qt import motion, rows, screens, shell, style
from app.services import status as status_service
from app.services import view_rows
from app.services.view_rows import Chip
from tests.qt.conftest import wait_until
from tests.qt.pixels import count, rgb, rgb_array
from tests.qt.test_current import current, grab, part, seeded   # noqa: F401  (seeded is a fixture)
from tests.qt.test_shell import _snap, services, window         # noqa: F401  (window / services are fixtures)


# --- G1 --------------------------------------------------------------------------------------------------------------
def test_an_open_rows_episodes_stand_in_the_shows_columns(seeded):
    """Each episode's % · new, status and ▶ start where its show row's own do, with the same widths. Why: the
    episodes must line up under the show's columns; a shift of even a few pixels reads as a ragged table."""
    seed, win = seeded()
    lst = current(win)
    d = lst.delegate
    i, (kind, row, _l) = next((i, e) for i, e in enumerate(lst.model().entries)
                              if e[0] == rows.ROW and e[1].episodes)
    before = lst.visualRect(lst.model().index(i, 0)).height()
    lst.toggle(lst.model().index(i, 0))
    assert wait_until(lambda: lst.visualRect(lst.model().index(i, 0)).height() > before)
    QApplication.processEvents()

    rect = lst.visualRect(lst.model().index(i, 0))
    h = round(theme.SIZES["row"] * rows.fz())
    show = d.columns(QRect(rect.left(), rect.top(), rect.width(), h))
    show_play = part(lst, i, "play")[0][1]              # the show row's own ▶, as painted (listed before its episodes')
    episodes = d._episode_rows(row, QRect(rect.left(), rect.top() + h, rect.width(), rect.height() - h))
    assert episodes, "an open row with episodes must list them, or this test checks nothing"
    for r, _ep in episodes:
        cols = d._episode_cols(r)
        assert cols["diff"].left() == show["diff"].left()
        assert cols["diff"].width() == show["diff"].width()
        assert cols["stat"].left() == show["stat"].left()
        assert cols["stat"].width() == show["stat"].width()
        assert cols["play"].left() == show_play.left()     # (this test found an episode's rect 1 px short: fixed)
        assert cols["play"].width() == show_play.width()


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
    title_x = rows.RowDelegate.lead(rows.ROW, rect.left())[2]
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
CHIP_TOP = 10                # the chip's rectangle, in logical px
CHIP_H = 28
DPR = 4.0
TOLERANCE = 40               # per-channel colour distance that still counts as "the dot's green"


def test_a_mined_chips_dot_is_centred_on_the_chips_midline(seeded):
    # why: the dot once sat 1.5 px above the chip's midline, so it looked lifted beside its number
    seed, win = seeded()
    lst = current(win)
    colours = style.colours()
    dot = rgb(colours["ok"])

    w, h = 60, 40
    img = QImage(int(w * DPR), int(h * DPR), QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(DPR)
    img.fill(QColor(colours["bg"]))
    p = QPainter(img)
    lst.delegate._paint_chip(p, QRect(10, CHIP_TOP, 60, CHIP_H), Chip("3", False, False, True, ""), DPR)
    p.end()

    arr = rgb_array(img)
    mask = np.all(np.abs(arr.astype(np.int16) - dot) <= TOLERANCE, axis=2)
    dot_rows = np.where(mask.any(axis=1))[0]
    assert len(dot_rows) >= 12, "the mined chip's dot is not painted in the ok colour at all"

    dot_mid = (dot_rows.min() + dot_rows.max() + 1) / 2.0 / DPR     # logical px
    chip_mid = CHIP_TOP + CHIP_H / 2.0
    assert abs(dot_mid - chip_mid) <= 0.75, f"dot midline {dot_mid} vs chip midline {chip_mid}"


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
def test_an_open_rows_episodes_stand_on_the_lists_ground_not_a_surface(seeded):
    """G2.3 R1: an open row (not the hero) has no box under its episodes: the list's bg shows, surface does not."""
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
    head = round(theme.SIZES["row"] * rows.fz())
    # The episodes' area under the row's head, inset so the rule line and the row's edges stay out of it.
    area = QRect(rect.left(), rect.top() + head, rect.width(), rect.height() - head).adjusted(12, 4, -12, -4)
    arr = rgb_array(lst.viewport().grab(area))
    total = area.width() * area.height()
    c = style.colours()
    # Why: a surface box under the episodes is the old look (the card's ground); it must not come back on a row.
    assert count(arr, c["bg"], 2) > total * 0.5
    assert count(arr, c["surface"], 2) < total * 0.02


# --- G7 --------------------------------------------------------------------------------------------------------------
def test_needs_you_count_sits_on_a_warn_badge(window):
    # One unseen failure shows the tab with its count on a filled warn pill: a large block of the warn colour
    # (a plain count would paint only a few warn-coloured glyph pixels, far below 100).
    unseen = status_service.Entry("Command line (status): it failed", "t", False)
    window.show_status(_snap(needs_you=(unseen,)))
    tab = window.tab_buttons["needs"]
    assert not tab.isHidden()
    warn = style.colours()["warn"]
    assert count(rgb_array(tab.grab()), warn, 10) >= 100


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
def test_a_needs_you_cards_line_is_in_its_tooltip_after_the_title(seeded):
    # Why: the card stays clean (the line is what's waiting, not what to paint); the tooltip carries it on its own line.
    seed, win = seeded()
    lst = win.page_widgets["needs"].list
    index, need = next((i, p) for i, (k, p, _l) in enumerate(lst.model().entries) if k == rows.NEED)
    assert need.line, "the seed's Needs-you card must carry its line, or this test proves nothing"
    tips = [tip for _name, _rect, tip, _payload in part(lst, index, "title")]
    assert tips == [need.title + "\n" + need.line]


# --- G11 --------------------------------------------------------------------------------------------------------------
def test_the_bars_line_starts_beside_its_dot_with_no_gap_of_its_own(window):
    # why: the dot's widget already holds its glow's room (GLOW on each side), so the line starts GLOW px past the
    # dot's painted edge; a layout gap of its own would push it further out
    window.bar_line.set_full("Couldn't open Ep 1: no video beside it on disk")
    QApplication.processEvents()
    line = window.bar_line.geometry()
    dot = window.bar_dot.geometry()
    assert line.width() > 0 and dot.width() > 0, "the bar is not laid out, so the gap would be meaningless"
    dot_right = dot.center().x() + motion.Spinner.DOT / 2
    gap = line.left() - dot_right
    assert gap <= motion.GLOW + 1


# --- G12 --------------------------------------------------------------------------------------------------------------
def _matches(colour, target, tol=6):
    """Each channel of `colour` is within `tol` of `target` (the box's 1 px border, drawn with antialiasing)."""
    return all(abs(a - b) <= tol for a, b in zip(
        (colour.red(), colour.green(), colour.blue()), (target.red(), target.green(), target.blue())))


def test_the_goal_strip_spans_the_window_and_its_box_sits_an_em_from_each_edge(seeded):
    """Edge to edge: the strip has no side margins of its own, and its box is `edge_room()` px from each edge (±1), so
    the box never reads as a card floating in the page."""
    seed, win = seeded()
    gs = win.page_widgets["current"].goal_strip
    assert gs.width() == gs.parentWidget().width()
    dpr = gs.devicePixelRatioF() or 1.0
    image = gs.grab().toImage()
    row = round(gs.height() * dpr / 2)           # the middle row: through the box, clear of its rounded corners
    line = QColor(style.colours()["line"])
    columns = [x for x in range(image.width()) if _matches(image.pixelColor(x, row), line)]
    assert columns, "no border colour found on the strip's middle row"
    edge = screens.edge_room()
    left = columns[0] / dpr
    right = columns[-1] / dpr
    assert abs(left - edge) <= 1, f"left border at {left} px, expected an em ({edge} px) from the edge"
    assert abs(right - (gs.width() - edge - 1)) <= 1, f"right border at {right} px, expected {gs.width() - edge - 1}"


# --- G13 --------------------------------------------------------------------------------------------------------------
def test_the_soon_line_is_a_quiet_hairline_in_the_separator_colour_with_no_word(seeded):
    """G2.3 L1: the Soon line is a 1 px hairline in the separators' colour (line), with no word, so it reads
    quieter than the dashed top-20 line; the pixel test is on the line's own strip (the row's last strip)."""
    seed, win = seeded()
    lst = current(win)
    i = next(i for i, e in enumerate(lst.model().entries) if any(ln.kind == "soon" for ln in e[2]))
    lst.scrollTo(lst.model().index(i, 0), lst.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    col = style.colours()
    assert col["line"] != col["top20-line"]          # the premise: the two rules differ in colour
    rect, arr = grab(lst, i)
    h = round(15 * rows.fz() + 6)                    # the strip the Soon line is painted in
    strip = arr[rect.height() - h:]
    width = strip.shape[1]
    best = max(count(strip[r:r + 1], col["line"], tolerance=3) for r in range(strip.shape[0]))
    assert best >= 0.6 * width                       # one pixel row of the strip is the hairline
    assert count(strip, col["ink-faint"], tolerance=10) == 0   # no word in the faint ink ...
    assert count(strip, col["ink-dim"], tolerance=10) == 0     # ... nor in the dim ink
