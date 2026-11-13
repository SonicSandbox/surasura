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
    later = []
    card.not_now.connect(later.append)
    card.set_card(("step", "cards", 3, 3))
    assert card.primary.text() == strings.NEXT_SET_UP_MINER and card.secondary.text() == strings.NEXT_OWN_CARDS
    assert card.later.isVisibleTo(card) and card.later.text() == strings.NEXT_NOT_NOW   # no Anki: set it aside
    card.secondary.click()
    card.later.click()
    assert own == [True] and later == ["cards"]
    card.set_card(("step", "words", 1, 3))
    assert not card.later.isVisibleTo(card)


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
    assert not win.duties.next_card.isVisible()                                  # at once, before the write
    assert wait_until(lambda: guide.read_state().get("own_cards") is True)


def test_the_panel_has_two_tabs_with_a_path_no_done_tab_and_the_path_lists_whats_useful_first(world):
    panel = world.d.guide_panel
    useful = facts(journey_opened=True, episodes_done=1, own_cards=True, video_waiting=True)
    panel.set_look(guide.Look("3.0.5", (), False))
    panel.set_path(_path(useful, {"first_ack": True}))
    assert wait_until(lambda: not panel.building())
    assert panel.tabs.isVisibleTo(panel) and set(panel.tab_buttons) == {"news", "path"}
    assert all(b.toolTip() for b in panel.tab_buttons.values())
    panel.open(tab="path")
    assert wait_until(panel.isVisible) and panel.tab == "path"
    rows = {r.status.step.id: r for r in panel.rows}
    assert not rows["hato"].later and rows["hato"].show_me is not None and rows["hato"].show_me.toolTip()
    assert rows["piyo"].later and rows["piyo"].show_me is None                  # not useful yet: not for now
    panel.close()


# --- Kantan-S2: past steps to try again, steps that can't apply now, and no subtitles (Sonic 2026-11-13) ---------- #
def _open_path(panel, f, state=None):
    panel.set_path(_path(f, state if state is not None else {"first_ack": True}))
    assert wait_until(lambda: not panel.building())
    panel.open(tab="path")
    assert wait_until(panel.isVisible) and panel.tab == "path"
    return {r.status.step.id: r for r in panel.rows}


def _lines_in_sight(widget):
    """Every word-wrapped or plain line a learner sees in `widget` (the ?s' own glyph left out)."""
    from PyQt6.QtWidgets import QLabel
    return [lab.text() for lab in widget.findChildren(QLabel) if lab.isVisibleTo(widget) and lab.text()
            and lab.objectName() != "helpmark"]


def test_the_cards_line_is_behind_its_question_mark_never_in_sight(card):
    from PyQt6.QtCore import Qt
    for got, (title, line) in ((("step", "words", 1, 3), strings.PATH_STEPS["words"]),
                               (("step", "cards", 3, 3), strings.PATH_STEPS["cards"]),
                               (("step", "hato", 0, 0), strings.PATH_STEPS["hato"])):
        card.set_card(got)
        assert card.title.isVisibleTo(card) and card.title.text() == title
        assert card.about.isVisibleTo(card) and card.about.toolTip() == line
        assert card.about.focusPolicy() == Qt.FocusPolicy.TabFocus and card.about.accessibleName()
        assert line not in _lines_in_sight(card)
        assert line in card.accessibleDescription()                             # a screen reader still hears it
    card.set_card(("made",))
    assert card.about.isVisibleTo(card) and card.about.toolTip() == strings.NEXT_MADE_LINE
    assert strings.NEXT_MADE_LINE not in _lines_in_sight(card)


def test_the_cards_question_mark_reveals_its_line_on_a_press_and_on_enter(lib_world):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    win = lib_world
    asked = []
    win.tooltips.request = lambda w, *a, **k: asked.append(w)
    win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False), _path(facts()), []))
    mark = win.duties.next_card.about
    assert mark.isVisible() and mark.toolTip() == strings.PATH_STEPS["words"][1]
    QTest.mouseClick(mark, Qt.MouseButton.LeftButton)
    mark.setFocus()
    QTest.keyClick(mark, Qt.Key.Key_Return)
    QTest.keyClick(mark, Qt.Key.Key_Space)
    assert asked == [mark, mark, mark]
    assert win.duties.next_card.card == ("step", "words", 1, 3)                 # revealing presses nothing else


def test_past_steps_stay_in_the_path_ticked_with_show_me_to_try_again(world):
    went = []
    panel = world.d.guide_panel
    panel.show_me.connect(went.append)
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True))
    for step_id in ("words", "watch", "cards"):                                 # chapter 1 done: each still listed
        r = rows[step_id]
        assert r.status.done and r.tick.text() == strings.PATH_TICK and not r.later
        assert r.show_me is not None and r.show_me.toolTip() == strings.PATH_AGAIN_TIP, step_id
        assert r.accessibleName() == strings.PATH_TICK_NAME.format(title=strings.PATH_STEPS[step_id][0])
    rows["watch"].show_me.click()
    assert went == ["help:current"] and not panel.isVisible()


def test_a_step_that_cant_apply_now_reads_not_for_now_with_when_behind_its_question_mark(world):
    panel = world.d.guide_panel
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True))   # no Anki, book, video
    later = {step_id for step_id, r in rows.items() if r.later}
    assert later == {"junban", "backfill", "audiobook", "hato", "piyo"}
    for step_id in later:
        r = rows[step_id]
        assert r.show_me is None and r.tick.text() == "", step_id               # never a dead end, never a tick
        assert r.about.isVisibleTo(panel) and r.about.toolTip() == strings.PATH_WHEN[step_id]
        assert strings.PATH_WHEN[step_id] in r.accessibleName()
    assert strings.PATH_LATER in _lines_in_sight(panel)                         # one quiet group name above them
    assert strings.PATH_COUNT.format(n=0, total=0) not in _lines_in_sight(panel)   # never "0 OF 0": no count


def test_a_step_done_before_that_cant_apply_now_keeps_its_tick_and_no_show_me(world):
    panel = world.d.guide_panel
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True, lined_up=True))
    r = rows["audiobook"]                                                       # lined up once; no book in Current now
    assert r.status.done and not r.later and r.tick.text() == strings.PATH_TICK and r.show_me is None


def test_a_missing_module_is_never_listed_even_as_not_for_now(world):
    panel = world.d.guide_panel
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True, junban=False))
    assert not {"junban", "backfill"} & set(rows)


def test_no_step_shows_a_line_under_its_title_each_says_it_behind_its_question_mark(world):
    panel = world.d.guide_panel
    every = facts(journey_opened=False, episodes_done=0, video_waiting=True, book_in_current=True)
    rows = _open_path(panel, every, {})
    sight = _lines_in_sight(panel)
    for step_id, r in rows.items():
        title, line = strings.PATH_STEPS[step_id]
        assert r.title.text() == title and line not in sight, step_id
        assert r.about.toolTip() in (line, strings.PATH_WHEN.get(step_id)), step_id


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


# --- the adversary's round 1 ------------------------------------------------------------------------------------- #
def test_every_chapter_one_settings_place_shows_for_a_new_learner(lib_world):
    page = lib_world.mount_settings()
    for step in P.STEPS:
        kind, _sep, name = step.where.partition(":")
        if kind == "settings" and step.chapter == P.FIRST:
            assert page.shows(name), step.id                                     # Show me never dead-ends here


def test_the_card_never_comes_mid_drag_and_ok_goes_at_once(lib_world):
    win = lib_world
    c = win.duties.next_card
    win.toasts.dragging = True
    try:
        win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False), _path(facts()), []))
        assert not c.isVisible() and win._guide_soon.isActive()                 # waits: the rows would jump
    finally:
        win.toasts.dragging = False
    win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False),
                    _path(facts(journey_opened=True, episodes_done=1, own_cards=True)), []))
    assert c.card == ("made",)
    c.primary.click()
    assert not c.isVisible()
    assert wait_until(lambda: guide.read_state().get("first_ack") is True)


def test_a_later_steps_not_now_is_kept_and_no_other_later_card_follows_this_run(lib_world):
    win = lib_world
    c = win.duties.next_card
    useful = facts(journey_opened=True, episodes_done=1, own_cards=True, video_waiting=True, book_in_current=True)
    win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False), _path(useful, {"first_ack": True}), []))
    assert c.card == ("step", "audiobook", 0, 0)
    c.secondary.click()
    assert not c.isVisible() and P.READY in win._path_later
    assert wait_until(lambda: "audiobook" in (guide.read_state().get("not_now") or ()))


def test_a_view_that_moved_asks_a_path_look_and_one_that_didnt_asks_none(lib_world):
    win = lib_world
    view = View((Row("anime", 0),), Counts(0, 0), ())
    win._guide_view_moved(view)
    win._guide_soon.stop()
    win._guide_view_moved(view)
    assert not win._guide_soon.isActive()                                        # the same numbers: nothing (S19)
    win._guide_view_moved(View((Row("anime", 1),), Counts(0, 0), ()))           # a Done
    assert win._guide_soon.isActive()


def test_a_step_rows_show_me_goes_there(world):
    went = []
    panel = world.d.guide_panel
    panel.show_me.connect(went.append)                                          # (the shell's slot runs too: harmless)
    panel.set_path(_path(facts(journey_opened=True, episodes_done=1, own_cards=True, video_waiting=True),
                         {"first_ack": True}))
    assert wait_until(lambda: not panel.building())
    panel.open(tab="path")
    assert wait_until(panel.isVisible)
    hato = next(r for r in panel.rows if r.status is not None and r.status.step.id == "hato")
    hato.show_me.click()
    assert went == ["settings:hato"] and not panel.isVisible()


def test_the_tabs_are_one_stop_and_the_arrows_move_between_them(world):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent
    panel = world.d.guide_panel
    panel.set_path(_path(facts()))
    panel.open(tab="news")
    assert wait_until(panel.isVisible)
    QApplication.sendEvent(panel.tab_buttons["news"], QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right,
                                                                 Qt.KeyboardModifier.NoModifier))
    assert panel.tab == "path"
    # one Tab stop (the guide §3): the checked tab takes Tab; Qt's exclusive group drops the other from the chain once
    # the arrows have moved the focus (its own way), and every tab is made a Tab-focus button, never a click's ring
    policies = {n: b.focusPolicy() for n, b in panel.tab_buttons.items()}
    assert policies["path"] == Qt.FocusPolicy.TabFocus and policies["news"] != Qt.FocusPolicy.StrongFocus, policies
    assert QApplication.focusWidget() is panel.tab_buttons["path"]
    panel.close()


def test_the_journey_really_opening_ticks_step_one(lib_world, monkeypatch):
    win = lib_world
    monkeypatch.setattr(win.services, "open_journey", lambda *file: True)        # the browser asked: it opened
    win._open_journey()
    assert wait_until(lambda: "journey" in (guide.read_state().get("moments") or {}))
