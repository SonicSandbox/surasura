"""The path in the window (Hoshi-S PR 2; Kantan-X's model, EXPERIENCE.md §3 — PROVISIONAL): the Next card above Up Next,
the ✦ panel's *Your path* tab.

What a wrong answer would cost a learner: a card that names the wrong step, or offers to skip the first cards' steps
ahead of order; *Not now* that doesn't go at once; a card shown during setup; a Done tab or rings back in the panel; a
path tab with nothing in it; a press that waits on the disk before the card answers.
"""
import json
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import guide as guide_ui, next_card, strings
from app.services import guide
from app.services import path as P
from tests.qt.conftest import wait_until
from tests.qt.test_jobs_bar import (FakeAutomation, FakeChores, FakeController, FakeUpdates, QuietReader,  # noqa: F401
                                     set_up, world)
from tests.test_services_path import View, Row, Counts, Arrival, facts


@pytest.fixture
def lib_world(qapp):
    """A window with a library (the seed's) and its duties attached (the stand-ins), as the integrated capture builds
    it: the Next card is mounted on Current's page."""
    from app.qt import shell
    from app.services import library_reader
    from app.services.jobs import JobRegistry
    from app.services.status import StatusService
    from tests.fixtures import window_seed
    seed = window_seed.build()
    log = []
    registry = JobRegistry()
    reader = library_reader.LibraryReader(seed.opener, language=seed.language, numbers=seed.numbers,
                                          mining=seed.mining, poll=0.02)
    services = shell.Services(library=reader, registry=registry, status=StatusService(registry, reader=QuietReader()),
                              controller=FakeController(log), updates=FakeUpdates(log),
                              automation=FakeAutomation(log), chores=FakeChores(log))
    set_up(services)
    win = shell.open_window(qapp, services)
    win.resize(1280, 800)
    win.show()
    assert wait_until(lambda: win.duties is not None and win.duties.next_card is not None, 10)
    yield win
    win.close()
    services.shutdown(0.5)


@pytest.fixture
def card(qapp):
    holder = QWidget()
    holder.resize(900, 120)
    c = next_card.NextCard(holder)
    holder.show()
    yield c
    holder.close()


def test_a_chapter_one_card_says_its_step_its_place_and_has_show_me_and_not_now(card):
    got = []
    card.show_me.connect(got.append)
    card.not_now.connect(lambda s: got.append(("later", s)))
    assert card.set_card(("step", "words", 1, 3)) and card.isVisible()
    assert card.eyebrow.text() == strings.NEXT_FIRST.format(n=1, total=3) and card.dots.total == 3
    assert card.title.text() == strings.PATH_STEPS["words"][0]
    assert card.primary.text() == strings.NEXT_SHOW_ME and card.secondary.text() == strings.NEXT_NOT_NOW
    assert card.primary.toolTip() and card.secondary.toolTip()
    card.primary.click()
    card.secondary.click()
    assert got == ["control:journey", ("later", "words")]
    assert card.set_card(("step", "words", 1, 3)) is False                      # the same card: nothing redone (S19)


def test_step_three_offers_anki_miner_or_i_make_my_own_cards(card):
    own = []
    card.own_cards.connect(lambda: own.append(True))
    card.set_card(("step", "cards", 3, 3))
    assert card.primary.text() == strings.NEXT_SET_UP_MINER and card.secondary.text() == strings.NEXT_OWN_CARDS
    card.secondary.click()
    assert own == [True]


def test_the_first_cards_made_card_has_only_ok_and_a_later_step_says_new_for_you(card):
    ok = []
    card.made_ok.connect(lambda: ok.append(True))
    card.set_card(("made",))
    assert card.eyebrow.text() == strings.NEXT_MADE and not card.secondary.isVisibleTo(card)
    assert not card.title.isVisibleTo(card) and card.primary.text() == strings.NEXT_OK
    card.primary.click()
    assert ok == [True]
    card.set_card(("step", "hato", 0, 0))
    assert card.eyebrow.text() == strings.NEXT_READY and not card.dots.isVisibleTo(card)
    assert card.set_card(None) and not card.isVisible()


# --- in the window ----------------------------------------------------------------------------------------------- #
def _path(f, state=None, later=()):
    return P.path(f, state or {}, later)


def test_the_card_sits_just_above_up_next_hidden_until_the_path_answers(lib_world):
    win = lib_world
    assert not win.duties.next_card.isVisible()
    page = win.page_widgets["current"]
    box = page.layout().itemAt(0).layout()
    assert box.indexOf(win.duties.next_card) == box.indexOf(page.state_bar) + 1 < box.indexOf(page.list)
    look = guide.Look("3.0.5", (), False)
    win._guide_got((win._guide_asked, look, _path(facts()), []))
    assert win.duties.next_card.card == ("step", "words", 1, 3) and win.duties.next_card.isVisible()


def test_not_now_goes_at_once_and_setup_hides_the_card(lib_world):
    win = lib_world
    c = win.duties.next_card
    win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False), _path(facts()), []))
    c.secondary.click()                                                          # Not now: gone in the same turn
    assert not c.isVisible() and "words" in win._path_later
    win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False), _path(facts(), later=("words",)), []))
    assert not c.isVisible()                                                     # until the next start
    win.services.setup_open.set()
    try:
        win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False), _path(facts()), []))
        assert not c.isVisible()                                                 # never during setup
    finally:
        win.services.setup_open.clear()


def test_i_make_my_own_cards_is_kept_and_the_next_look_says_your_first_cards_are_made(lib_world):
    win = lib_world
    win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False),
                    _path(facts(journey_opened=True, episodes_done=1)), []))
    win.duties.next_card.secondary.click()
    assert wait_until(lambda: guide.read_state().get("own_cards") is True)


def test_the_panel_has_two_tabs_with_a_path_no_done_tab_and_the_path_lists_only_whats_useful(world):
    panel = world.d.guide_panel
    useful = facts(journey_opened=True, episodes_done=1, own_cards=True, video_waiting=True)
    panel.set_look(guide.Look("3.0.5", (), False))
    panel.set_path(_path(useful, {"first_ack": True}))
    assert wait_until(lambda: not panel.building())
    assert panel.tabs.isVisibleTo(panel) and set(panel.tab_buttons) == {"news", "path"}
    assert all(b.toolTip() for b in panel.tab_buttons.values())
    panel.open(tab="path")
    assert wait_until(panel.isVisible) and panel.tab == "path"
    texts = [r.line.text() for r in panel.rows] + [r.title.text() for r in panel.rows if r.title is not None]
    assert strings.PATH_STEPS["hato"][0] in texts                               # useful now: listed, with Show me
    assert strings.PATH_STEPS["piyo"][0] not in texts                           # not useful yet: not listed
    hato = next(r for r in panel.rows if r.status is not None and r.status.step.id == "hato")
    assert hato.show_me is not None and hato.show_me.toolTip()
    panel.close()


def test_a_path_body_is_built_one_piece_a_turn_under_4_ms(world):
    import time
    panel = world.d.guide_panel
    panel.slices.clear()
    every = facts(junban=True, anki_synced=True, cards_made=True, book_in_current=True, video_waiting=True,
                  episodes_done=3)
    panel.set_path(_path(every))
    assert panel.building()
    assert wait_until(lambda: not panel.building())
    assert max(panel.slices) < 4.0, max(panel.slices)
    panel.show_tab("path")
    t0 = time.perf_counter()
    panel.place()
    assert (time.perf_counter() - t0) * 1000 < 4.0


def test_without_a_library_the_panel_is_whats_new_alone(world):
    panel = world.d.guide_panel
    panel.set_path(None)
    assert not panel.tabs.isVisibleTo(panel) and panel.heading.isVisibleTo(panel)
    panel.show_tab("path")
    assert panel.tab == "news"


def test_the_journey_opening_is_kept_as_the_first_steps_moment(world):
    world.win._guide_moment("journey")
    assert wait_until(lambda: "journey" in (guide.read_state().get("moments") or {}))
