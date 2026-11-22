"""The window's half of Kyou-SH3 (PROVISIONAL words): an Undo that left cards out because their words have new cards
says how many in the bar; a tidy whose backup didn't read back is one *Needs you* card with *OK* only, and its *OK*
says nothing was deleted. On the window's seed.

What a wrong answer would cost a learner: an Undo that silently brought back fewer cards than the card named, an
*Undo* offered for a tidy that deleted nothing, or an *OK* that says cards stay deleted when none were.
"""
import pytest

pytest.importorskip("PyQt6")

from app.connect import tidy
from app.qt import strings
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

TIDIED = {"id": 4, "cards": 3, "at": "2026-11-21T06:00:00Z", "why": "auto"}
UNSAVED = {"id": 5, "cards": 12, "at": "2026-11-22T06:00:00Z", "why": "auto"}


def test_an_undo_that_left_cards_out_says_how_many(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tidy, "act_undo", lambda settings, lang, tidy_id: {"back": 2, "missing": [], "skipped": [105]})
    _seed, win, _writer, ny = world(connect={"tidied": TIDIED, "needs": [], "gaps": []})
    entry = next(e for e in ny.entries if e.kind == service.TIDIED)
    said = []
    win.say = said.append
    button(ny, entry.key, "undo_tidy").click()
    assert wait_until(lambda: said, 5)
    assert said == [strings.NEEDS_TIDY_BACK.format(n=2) + strings.NEEDS_TIDY_SKIPPED_ONE]


def test_a_tidy_that_deleted_nothing_offers_only_ok_and_ok_says_nothing_was_deleted(world):  # noqa: F811
    _seed, win, _writer, ny = world(connect={"tidy_unsaved": UNSAVED, "needs": [], "gaps": []})
    entry = next(e for e in ny.entries if e.kind == service.TIDIED)
    assert entry.title == service.STRINGS["tidy_unsaved_title"].format(n=12)
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"leave_tidy"}, "nothing to undo"
    said = []
    win.say = said.append
    button(ny, entry.key, "leave_tidy").click()
    assert wait_until(lambda: said, 5)
    assert said == [strings.NEEDS_TIDY_UNSAVED_LEFT]
    assert wait_until(lambda: entry.key in service.read_answered("ja"), 5)
