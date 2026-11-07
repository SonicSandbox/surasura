"""Work counts on the help cards (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work
counts*): what each new press costs the window — the ?, *Why?*, the tour's *Next*, *All help* — counted, never timed.

What a wrong answer would cost a learner: a ? that builds the card again each time (a lag on every press), a *Next*
that lays the whole window out, a *Why?* that remakes the toast's row. The card is a sheet over a scrim (as the one
confirmation is): its opening dims the window — the rule for it is R5, built once, and every later press repaints
only the card.

The screen: the window built once for the file (`screen` -> (seed, win, writer)); every test puts back what it changed.
"""
import pytest

pytest.importorskip("PyQt6")
from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until

from app.services import causes, help_cards


@pytest.fixture(scope="module")
def screen(qapp, tmp_path_factory):
    with wc.window_screen(qapp, tmp_path_factory, "help") as s:
        yield s


@pytest.fixture(autouse=True)
def _at_rest(screen, monkeypatch):
    wc.home(monkeypatch, "help")
    seed, win, writer = screen
    win.show_tab("current")
    wc.rest(200)
    yield
    card = getattr(win, "_help_card", None)
    if card is not None and card.isVisible():
        card.close()
    win.toasts.close()
    wc.quiet(win)


def _press_help(win):
    win.duties.help.click() if win.duties is not None else win.open_help()
    return win._help_card


def test_r5_the_card_opened_again_by_its_question_mark_makes_no_widget(screen):
    seed, win, writer = screen
    card = _press_help(win)
    wc.rest(300)
    card.close()
    wc.rest(200)
    with wc.measure(win, readers=[win.services.library]) as w:
        card = _press_help(win)
        wc.rest(300)
    assert card.isVisible(), w.report()
    assert w.created == 0 and w.deleted == 0, w.report()
    assert w.builds == 0 and w.reads == 0, w.report()                  # a card reads no library


def test_the_tours_next_repaints_only_the_card_and_makes_no_widget(screen):
    seed, win, writer = screen
    card = win.open_tour()
    wc.rest(300)
    card.next.click()                                                    # (every part shown once, unmeasured)
    wc.rest(200)
    card.back.click()
    wc.rest(200)
    with wc.measure(win, readers=[win.services.library]) as w:
        card.next.click()
        wc.rest(200)
    assert card.card_id == help_cards.tour()[1], w.report()
    assert w.created == 0 and w.deleted == 0, w.report()
    pad = wc.rect_in_window(card).adjusted(-64, -64, 64, 64)            # its shadow
    assert w.paints_outside_rect(pad) == [], w.report()
    assert w.builds == 0, w.report()


def test_all_help_is_built_at_its_first_showing_only(screen):
    seed, win, writer = screen
    card = win.open_help("current")
    card.show_all()
    wc.rest(200)
    card.show_card("level")
    wc.rest(200)
    with wc.measure(win, readers=[win.services.library]) as w:
        card.show_all()
        wc.rest(200)
    assert w.created == 0 and w.deleted == 0 and card.builds == 1, w.report()


def test_why_on_a_toast_opens_its_card_and_makes_nothing_the_second_time(screen):
    seed, win, writer = screen
    why = causes.Cause("Surasura opened", None, "known")
    win.toasts.show("順: 5 cards first", undo=lambda: None, why=why)
    wc.rest(200)
    win.toasts.card.why.click()
    wc.rest(300)
    win._help_card.close()
    win.toasts.show("順: 5 cards first", undo=lambda: None, why=why)
    wc.rest(200)
    with wc.measure(win, readers=[win.services.library]) as w:
        win.toasts.card.why.click()
        wc.rest(300)
    assert win._help_card.isVisible() and win._help_card.card_id == "known", w.report()
    assert win.toasts.paused, w.report()                                 # its Undo kept while the card is open
    assert w.created == 0 and w.deleted == 0, w.report()
    win._help_card.close()
    assert wait_until(lambda: not win.toasts.paused)
