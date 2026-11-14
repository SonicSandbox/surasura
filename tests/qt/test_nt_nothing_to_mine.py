"""Kura-NT, based on Mattias's #454: a part mined with nothing new to make (every word it holds already on a card) reads
*Nothing new to mine* — Connect's side and the statuses: `tests/connect/test_nt_nothing_to_mine.py`; the stone's look:
`tests/test_stone_plan.py`. Here, what the window draws of it: its stone's tip says *nothing new*, never "0 cards in
Anki", through the rows' own delegate on the window's seed (Japanese titles); its pill is drawn as *No cards in Anki*'s,
the quiet outline.

What a wrong answer would cost: a stone that says "0 cards in Anki" beside a pill that says nothing was new to mine.
"""
import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage, QPainter

from app.qt import rows, strings
from app.services import stone_plan, view_rows
from tests.qt.test_p41_actions import act, lst_of  # noqa: F401  (act: a fixture)

NOTHING = view_rows.Status("nothing", view_rows.STRINGS["nothing"], view_rows.STRINGS["tip_nothing"], "faint")


def test_a_stone_mined_with_nothing_new_says_so_in_its_tip_with_no_card_count(act):
    _seed, win, _writer = act()
    lst = lst_of(win)
    i = next(k for k, e in enumerate(lst.model().entries) if e[0] == rows.ROW and len(e[1].episodes) > 1)
    row = lst.model().entries[i][1]
    first = row.episodes[0]._replace(watched=False, cards=0, deleted=True, status=NOTHING)
    row = row._replace(episodes=(first,) + row.episodes[1:], next_index=0)
    parts = lst.delegate._stone_parts(row, stone_plan.plan_of(row), QRect(0, 0, 4000, 40), 20)
    tip = next(p[2] for p in parts if p[3].id == first.id)
    assert strings.ROWS_STONE_STATE["nothing"] in tip and "cards in Anki" not in tip, tip
    assert tip.startswith(first.label)
    assert rows.stone_state(first) == strings.ROWS_STONE_STATE["nothing"], "an opened row's stone says the same"


def _pill(status):
    img = QImage(160, 28, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    rows.paint_pill(p, status, QRect(0, 0, 160, 28))
    p.end()
    return img


def test_its_pill_is_drawn_as_no_cards_in_ankis_quiet_outline(qapp):
    """The same words on both: only the kind differs, so the two images are equal pixel for pixel."""
    said = view_rows.STRINGS["nothing"]
    assert _pill(NOTHING) == _pill(view_rows.Status("deleted", said, "", "faint"))
    assert _pill(NOTHING) != _pill(view_rows.Status("retry", said, "", "faint")), "why: a pill's kind must show"
