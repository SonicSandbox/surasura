"""Michi-CK part 1 (Sonic's ruling 1 on Michi-EO's Q-EO2): the *Mine* button's face is a pickaxe alone — the word gone
from the pill, the old ⊞ glyph gone from the button — while its hover and its accessible name still say *Mine* first.
One place: the status kind `mine` (`rows.pill_text`, the painted `rows.icon` "mine").

What a wrong answer would cost a learner:
  * a *Mine* pill still worded (the ruling not taken), or a pickaxe alone that names nothing on hover or to a screen
    reader (the Qt guide: an icon without words names itself first);
  * the old ⊞ glyph kept on the button — not the face the learner was shown;
  * *Mine rest* or *Not timed* losing their words with it (their counts and their ask are words the learner reads).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

from app.qt import rows, strings
from app.services import view_rows
from tests.qt.test_p41_actions import act, action, lst_of, row_with   # noqa: F401  (act: a fixture)

TIP = view_rows.STRINGS["tip_mine_own"].format(line=20)


def _mine():
    return view_rows.Status("mine", view_rows.STRINGS["mine"], TIP, "ink")


def test_a_mine_pill_is_its_icon_alone_in_the_round_pill_and_its_hover_says_mine_first():
    """The pill shows no word: the same round, icon-alone pill as *Waiting*'s (row 38); its hover names it, then why."""
    st = _mine()
    waiting = view_rows.Status("waiting", view_rows.STRINGS["waiting"], view_rows.STRINGS["tip_waiting"], "dim")
    assert rows.pill_text(st) == ""
    assert rows.pill_size(st) == rows.pill_size(waiting)
    assert rows.status_tip(st) == f"{view_rows.STRINGS['mine']}\n{TIP}"


def test_mine_rest_and_not_timed_keep_their_words():
    """Only the button's face changed: *2/5 · Mine rest* is a count the learner reads, *Not timed* asks for him."""
    rest = view_rows.Status("mine_rest", view_rows.STRINGS["mine_rest"].format(k=2, n=5), "", "dim")
    timed = view_rows.Status("waiting", view_rows.STRINGS["not_timed"], "", "dim")
    assert rows.pill_text(rest) == rest.label
    assert rows.pill_text(timed) == timed.label


def _ink(kind, side=52):
    img = QImage(side, side, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    rows.icon(p, kind, QRectF(0, 0, side, side), QColor("white"), width=1.6 * side / 13)
    p.end()
    return lambda u, v: img.pixelColor(round(u * (side - 1)), round(v * (side - 1))).alpha() > 128


def test_the_mine_glyph_is_a_pickaxe_its_handle_rising_from_the_lower_left_into_an_arched_head():
    """The handle runs corner to centre (lower left up); the head, a filled crescent, arches over the upper right from
    tip to tip. The old ⊞'s box edges (its left side, its foot) are bare."""
    inked = _ink("mine")
    assert inked(0.25, 0.75) and inked(0.4, 0.6)            # the handle
    assert inked(0.4, 0.17) and inked(0.83, 0.6)            # the head's two arms
    assert inked(0.68, 0.32)                                # the head's middle, where the handle meets it
    assert not inked(0.18, 0.5) and not inked(0.5, 0.92)    # no box
    assert not inked(0.85, 0.95) and not inked(0.08, 0.08)  # nothing in the far corners


def test_try_again_wears_the_same_pickaxe():
    """*Try again* asks Connect to mine it again: the one Mine glyph (STATUS_ICON), never a second drawing."""
    assert rows.STATUS_ICON["retry"] == rows.STATUS_ICON["mine"] == "mine"


def test_the_mine_button_in_the_window_names_itself_mine_on_hover_and_to_a_screen_reader(act):
    """On the window's seed (Japanese titles): the row's Mine button's tip starts with *Mine*, then why, then its
    click; the row's accessible text says *Mine* and its description how the keyboard presses *Mine this*."""
    _seed, win, _writer = act()
    lst = lst_of(win)
    i = row_with(lst, "mine", None)
    row = lst.model().entries[i][1]
    p = action(lst, i)
    assert p[0] == "mine-this" and p[2].startswith(view_rows.STRINGS["mine"] + "\n" + row.status.tip)
    idx = lst.model().index(i, 0)
    assert view_rows.STRINGS["mine"] in lst.model().data(idx, Qt.ItemDataRole.AccessibleTextRole)
    assert lst.model().data(idx, Qt.ItemDataRole.AccessibleDescriptionRole).endswith(
        strings.ROWS_ACTION_KEY.format(action=strings.ROWS_ACTION_NAMES["mine-this"]))
