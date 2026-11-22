"""The path in the window (Hoshi-S PR 2; Kantan-X's model, EXPERIENCE.md §3 — PROVISIONAL): the Next card above Up Next,
the ✦ panel's *Your path* tab.

What a wrong answer would cost a learner: a card that names the wrong step, or offers to skip the first cards' steps
ahead of order; *Not now* that doesn't go at once; a card shown during setup; a Done tab or rings back in the panel; a
path tab with nothing in it; a press that waits on the disk before the card answers. Mado-EZP (SPEC-r2 §0.2, the four
stages): a step whose press sends the learner up top instead of doing it from the card (Sonic's "confusing"); step ①
opening the journey at its top, not on Up Next's episode, or not ticking; two presses at once from the card and Up Next;
*Show me* that presses or writes anything; an upgrader's ticks lost.
"""
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import next_card, strings
from app.services import guide
from app.services import path as P
from app.services import view_rows
from tests.qt.conftest import wait_until
from tests.qt.test_jobs_bar import (FakeAutomation, FakeChores, FakeController, FakeUpdates, QuietReader,  # noqa: F401
                                     set_up, world)
from tests.test_services_path import View, Row, Counts, facts


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


EP2 = (P.DONE, P.NOW, P.LATER, P.LATER)                # ② First episode to do now
EP3 = (P.DONE, P.DONE, P.NOW, P.LATER)                 # ③ Automate to do now
WORDS = ("words", "Open Ep 3's words ↗", "tip")


def test_a_stage_card_says_its_stage_its_four_stones_its_own_press_show_me_and_not_now(card):
    got = []
    card.act.connect(lambda key, control: got.append((key, control)))
    card.show_me.connect(got.append)
    card.not_now.connect(lambda s: got.append(("later", s)))
    assert card.set_card(("step", "words", EP2), (WORDS,)) and card.isVisible()
    assert card.eyebrow.text() == strings.NEXT_STAGE.format(stage=strings.PATH_STAGES["episode"].upper())
    assert card.stages.states == EP2 and card.stages.isVisibleTo(card)
    assert "First episode: now" in card.stages.accessibleName()                 # the stones, for a screen reader
    assert card.title.text() == strings.PATH_STEPS["words"][0]
    assert card.primary.text() == "Open Ep 3's words ↗" and card.primary.toolTip() == "tip"
    assert card.show_button.text() == strings.NEXT_SHOW_ME and card.secondary.text() == strings.NEXT_NOT_NOW
    assert not card.primary2.isVisibleTo(card) and card.show_button.toolTip() and card.secondary.toolTip()
    card.primary.click()
    card.show_button.click()
    card.secondary.click()
    assert got == [("words", card.primary), "hero:journey", ("later", "words")]
    assert card.set_card(("step", "words", EP2), (WORDS,)) is False             # the same card: nothing redone (S19)
    assert card.set_card(("step", "words", EP2), (("words", "Open Ep 4's words ↗", "tip"),))   # Up Next moved on


def test_watch_carries_both_of_up_nexts_presses(card):
    got = []
    card.act.connect(lambda key, control: got.append((key, control)))
    card.set_card(("step", "watch", EP2), (("watch", "▶ Watch Ep 3", "t1"), ("done", "✓ Done", "t2")))
    assert card.primary.text() == "▶ Watch Ep 3" and card.primary2.isVisibleTo(card)
    assert card.primary2.text() == "✓ Done" and card.primary2.toolTip() == "t2"
    card.primary.click()
    card.primary2.click()
    assert got == [("watch", card.primary), ("done", card.primary2)]


def test_the_cards_step_offers_its_press_i_make_my_own_cards_and_not_now(card):
    own, later, acts = [], [], []
    card.own_cards.connect(lambda: own.append(True))
    card.not_now.connect(later.append)
    card.act.connect(lambda key, _c: acts.append(key))
    card.set_card(("step", "cards", EP3), (("miner",) + strings.PATH_PRESS["miner"],))
    assert card.eyebrow.text() == strings.NEXT_STAGE.format(stage=strings.PATH_STAGES["automate"].upper())
    assert card.primary.text() == strings.PATH_PRESS["miner"][0] and card.secondary.text() == strings.NEXT_OWN_CARDS
    assert card.later.isVisibleTo(card) and card.later.text() == strings.NEXT_NOT_NOW   # no Anki: set it aside
    card.primary.click()
    card.secondary.click()
    card.later.click()
    assert acts == ["miner"] and own == [True] and later == ["cards"]
    card.set_card(("step", "words", EP2), (WORDS,))
    assert not card.later.isVisibleTo(card)


def test_the_first_cards_made_card_has_only_ok_and_a_later_step_says_new_for_you(card):
    ok = []
    card.made_ok.connect(lambda: ok.append(True))
    card.set_card(("made",))
    assert card.eyebrow.text() == strings.NEXT_MADE and not card.secondary.isVisibleTo(card)
    assert card.title.text() == strings.NEXT_MADE_WHERE and card.primary.text() == strings.NEXT_OK
    assert not card.show_button.isVisibleTo(card) and not card.stages.isVisibleTo(card)
    card.primary.click()
    assert ok == [True]
    card.set_card(("step", "hato", ()), (("hato",) + strings.PATH_PRESS["hato"],))
    assert card.eyebrow.text() == strings.NEXT_READY and not card.stages.isVisibleTo(card)
    assert card.primary.text() == strings.PATH_PRESS["hato"][0]
    assert not card.show_button.isVisibleTo(card)                               # its press goes to that place itself
    assert card.set_card(None) and not card.isVisible()


def test_the_made_card_always_shows_its_ok_even_after_a_step_with_no_press(card):
    # review (failures lens #1): a step painted with no presses hides the primary; the made card must bring OK back
    card.set_card(("step", "hato", ()), ())
    assert not card.primary.isVisibleTo(card)
    card.set_card(("made",))
    assert card.primary.isVisibleTo(card) and card.primary.text() == strings.NEXT_OK


def test_the_stage_string_is_four_stones_from_the_rows_own_sheet(card, qapp):
    # §0.6 item 1: the stones are `stones.py`'s crystals (never a drawing of its own): done cut, now ringed, later small
    from app.qt import next_card as nc, stones, style
    assert nc.stone_of(P.DONE)[1] == "cut" and nc.stone_of(P.NOW)[4] == "next" and nc.stone_of(P.LATER)[4] == "waiting"
    card.set_card(("step", "words", EP2), (WORDS,))
    dpr = card.stages.devicePixelRatioF() or 1.0
    assert wait_until(lambda: stones.get(dpr, style.current()[1]) is not None, 20)
    sheet = stones.get(dpr, style.current()[1])
    for state in (P.DONE, P.NOW, P.LATER):
        assert nc.stone_of(state) in sheet, state
    assert ("ring", "next") in sheet
    pix = card.stages.grab()                                                    # painted: something there
    assert not pix.toImage().isNull()


# --- in the window ----------------------------------------------------------------------------------------------- #
def _path(f, state=None, later=()):
    return P.path(f, state or {}, later)


def _shown(win, f, state=None):
    win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False), _path(f, state), []))
    return win.duties.next_card


def test_the_card_sits_just_above_up_next_hidden_until_the_path_answers(lib_world):
    win = lib_world
    assert not win.duties.next_card.isVisible()
    page = win.page_widgets["current"]
    box = page.layout().itemAt(0).layout()
    assert box.indexOf(win.duties.next_card) == box.indexOf(page.state_bar) + 1 < box.indexOf(page.list)
    c = _shown(win, facts())
    assert c.card == ("step", "words", EP2) and c.isVisible()


def test_not_now_goes_at_once_and_setup_hides_the_card(lib_world):
    win = lib_world
    c = _shown(win, facts())
    c.secondary.click()                                                          # Not now: gone in the same turn
    assert not c.isVisible() and "words" in win._path_later
    win._guide_got((win._guide_asked, guide.Look("3.0.5", (), False), _path(facts(), later=("words",)), []))
    assert not c.isVisible()                                                     # until the next start
    win.services.setup_open.set()
    try:
        _shown(win, facts())
        assert not c.isVisible()                                                 # never during setup
    finally:
        win.services.setup_open.clear()


def test_i_make_my_own_cards_is_kept_and_the_next_look_says_your_first_cards_are_made(lib_world):
    win = lib_world
    _shown(win, facts(journey_opened=True, episodes_done=1))
    win.duties.next_card.secondary.click()
    assert not win.duties.next_card.isVisible()                                  # at once, before the write
    assert wait_until(lambda: guide.read_state().get("own_cards") is True)


# --- the gate (SPEC-r2 §0.11 row 2): every step acts from its own card ------------------------------------------- #
def _up(win):
    # FLAKES (Kantan-MO's #568, GitHub core 3/4): the fixture waits for the duties only; Current's rows come from the
    # library reader a poll later — under load they weren't drawn yet. Up Next is read once they are
    assert wait_until(lambda: win._up_next() is not None, 10), "the seed's Current has an Up Next"
    return win._up_next()


def test_step_ones_press_opens_the_journey_on_up_nexts_episode_and_ticks_once_it_opened(lib_world, monkeypatch):
    from app.qt import shell
    win = lib_world
    asked = []
    monkeypatch.setattr(win.services, "open_journey", lambda *file: asked.append(file) or True)
    c = _shown(win, facts())
    row, ep = _up(win)
    assert c.primary.text() == strings.PATH_PRESS["words"][0].format(ep=ep.label)
    assert "journey" not in (guide.read_state().get("moments") or {})
    c.primary.click()
    assert wait_until(lambda: "journey" in (guide.read_state().get("moments") or {}))
    assert asked == [(shell.journey_file(view_rows.journey_episode(row)),)]      # on that episode, never the top


def test_a_journey_that_lacks_the_episode_still_ticks_and_the_bar_says_why(lib_world, monkeypatch):
    from app.qt import shell
    win = lib_world
    monkeypatch.setattr(win.services, "open_journey", lambda *file: shell.JOURNEY_LACKS)
    c = _shown(win, facts())
    row, _ep = _up(win)
    c.primary.click()
    assert wait_until(lambda: "journey" in (guide.read_state().get("moments") or {}))
    episode = view_rows.journey_episode(row)
    assert wait_until(lambda: win.bar_line.accessibleDescription() ==
                      strings.JOURNEY_NOT_YET.format(ep=episode.label))


def test_with_no_journey_on_disk_the_press_says_so_and_ticks_nothing(lib_world, monkeypatch):
    win = lib_world
    monkeypatch.setattr(win.services, "open_journey", lambda *file: False)
    c = _shown(win, facts())
    c.primary.click()
    assert wait_until(lambda: win.bar_line.accessibleDescription() == strings.JOURNEY_NONE_TIP)
    assert "journey" not in (guide.read_state().get("moments") or {})


def test_the_cards_watch_and_up_nexts_play_are_one_press(lib_world, monkeypatch):
    from app.qt import press as qpress, screens
    win = lib_world
    monkeypatch.setattr(screens, "media_to_open", lambda *a: (None, "not here"))   # (no player opened)
    c = _shown(win, facts(journey_opened=True))
    _row, ep = _up(win)
    assert c.card[1] == "watch" and c.primary.text() == strings.PATH_PRESS["watch"][0].format(ep=ep.label)
    held = qpress.begin(None, ("play", ep.id), win=win)                         # Up Next's ▶ on its way
    assert held is not None
    assert win.path_press("watch", c.primary) is None                           # the card's: nothing started
    qpress.end(held, win)
    p = win.path_press("watch", c.primary)
    assert p is not None                                                        # its own press now …
    assert win.page_widgets["current"]._play(ep) is None                        # … and Up Next's ▶ waits for it
    assert wait_until(lambda: not qpress.live(win, ("play", ep.id)))


def _marking(win, monkeypatch, on):
    """The drag controller's answer to "a Done of this row on its way?" (a stand-in when the test window has none)."""
    if getattr(win, "moves", None) is not None:
        monkeypatch.setattr(win.moves, "marking", lambda key: on)
    else:
        monkeypatch.setattr(win, "moves", SimpleNamespace(marking=lambda key: on, close=lambda: None,
                                                          unwire=lambda: None), raising=False)


def test_the_cards_done_is_up_nexts_done_and_waits_while_one_is_on_its_way(lib_world, monkeypatch):
    win = lib_world
    current = win.page_widgets["current"]
    asked = []
    monkeypatch.setattr(current, "on_done", lambda row, ep: asked.append((row.key, ep)))
    c = _shown(win, facts(journey_opened=True))
    row, ep = _up(win)
    assert c.primary2.text() == strings.PATH_PRESS["done"][0]
    _marking(win, monkeypatch, True)                                            # a Done of the row on its way
    c.primary2.click()
    assert asked == []
    _marking(win, monkeypatch, False)
    c.primary2.click()
    assert asked == [(row.key, ep)]                                             # the one path for a Done (S12)


def test_a_watched_mark_on_its_way_is_what_marking_reads():
    from types import SimpleNamespace
    from app.qt import drag
    t = drag.Ticket("ぼっち・ざ・ろっく！ 3 watched", ("row-1",), (7,))
    t.marks = {7: True}
    moves = SimpleNamespace(tickets=[t])
    assert drag.DragController.marking(moves, "row-1") and not drag.DragController.marking(moves, "row-2")
    t.marks = {7: False}                                                        # an un-watch is no Done
    assert not drag.DragController.marking(moves, "row-1")
    assert not drag.DragController.marking(SimpleNamespace(tickets=[]), "row-1")


@pytest.mark.parametrize("key, target", [
    ("words", "_open_journey"), ("words-any", "_open_journey"), ("mine", "mine_row"), ("miner", "install"),
    ("junban", "_open_junban"), ("junban-again", "_open_junban"), ("backfill", "launch"),
    ("automation", "settings:automation"), ("yours", "settings:level"),
    ("audiobook", "tab:current@audiobook"), ("hato", "settings:hato"), ("piyo", "settings:practice_ai"),
])
def test_every_steps_primary_runs_the_press_it_names(lib_world, monkeypatch, key, target):
    from app.qt import settings_connect, windows
    win = lib_world
    ran = []
    monkeypatch.setattr(win, "_open_journey", lambda **kw: ran.append(("_open_journey", kw.get("episode"))))
    monkeypatch.setattr(win, "_open_junban", lambda *a: ran.append(("_open_junban",)))
    monkeypatch.setattr(win, "guide_show_me", lambda where: ran.append((where,)))
    monkeypatch.setattr(settings_connect, "install_anki_miner", lambda shell: ran.append(("install",)))
    monkeypatch.setattr(windows, "launch", lambda shell, op: ran.append(("launch", op.name)))
    monkeypatch.setattr(win, "_top_to_mine", lambda: ("row", [1]))
    win.mine = type("Mine", (), {"mine_row": lambda self, row, ids: ran.append(("mine_row", row, ids))})()
    if key == "words":
        _up(win)                                    # Current's rows drawn (FLAKES: #568), so the press names Up Next
    win.path_press(key)
    assert ran and ran[0][0] == target, ran
    if key == "words":
        assert ran[0][1] is not None                                            # on Up Next's episode
    if key == "backfill":
        assert ran[0][1] == "backfill"


def test_step_fours_press_is_the_one_entry_point_the_picker_fills(lib_world, monkeypatch):
    # the seam with Mado-EZC (lane 3): the card's and the panel's *Pick your cards* both reach `pick_your_cards`
    win = lib_world
    went = []
    monkeypatch.setattr(win, "pick_your_cards", lambda control=None: went.append(control))
    win.path_press("yours", "button")
    win.path_act("yours")
    assert went == ["button", None]


def test_turn_on_cards_made_for_you_runs_connects_switch_and_tells_the_window(lib_world, monkeypatch):
    from app.qt import settings_connect
    win = lib_world
    asked, told = [], []
    monkeypatch.setattr(settings_connect, "_switch_on", lambda store, log: asked.append(store) or (True, None))
    win.bridge.settings_written.connect(told.append)
    assert win.path_press("cards-on") is not None
    assert wait_until(lambda: told and told[-1] == ("connect_enabled",))
    assert asked == [win.services.settings]


def test_the_cards_step_names_the_press_that_applies_now(lib_world, monkeypatch):
    from app.qt import shell
    win = lib_world
    win._path_way = _path(facts(journey_opened=True, episodes_done=1, miner_found=False))
    assert win._step_presses("cards")[0][0] == "miner"                          # no Anki Miner: set it up first
    win._path_way = _path(facts(journey_opened=True, episodes_done=1, miner_found=True))
    monkeypatch.setattr(win.services.settings, "get", lambda: {"connect_enabled": False})
    assert win._step_presses("cards")[0][0] == "cards-on"                       # the consent itself (EZ2-5)
    monkeypatch.setattr(win.services.settings, "get", lambda: {"connect_enabled": True, "logic": {"automation": False}})
    assert win._step_presses("cards")[0][0] == "automation"                     # D29: never turned on for you
    monkeypatch.setattr(win.services.settings, "get", lambda: {"connect_enabled": True, "logic": {"automation": True}})
    seen = []
    monkeypatch.setattr(win, "_top_to_mine", lambda first=None: seen.append(first) or (
        type("R", (), {"title": "ぼっち・ざ・ろっく！"})(), [1]))
    key, words, _tip = win._step_presses("cards")[0]
    assert key == "mine" and words == strings.PATH_PRESS["mine"][0].format(title="ぼっち・ざ・ろっく！")
    assert seen == [shell.PATH_LABEL_ROWS]                                     # a label's look: the first rows only
    monkeypatch.setattr(win, "_top_to_mine", lambda first=None: None)
    assert win._step_presses("cards")[0][:2] == ("mine-any", strings.PATH_PRESS["mine-any"][0])


@pytest.mark.parametrize("step_id", ["words", "watch", "cards", "junban", "backfill", "yours"])
def test_show_me_only_lights_a_place_and_changes_nothing(lib_world, step_id):
    from app.qt import press as qpress
    win = lib_world
    c = _shown(win, facts())
    before = (json.dumps(win.services.settings.get(), sort_keys=True, default=dict), json.dumps(guide.read_state(), sort_keys=True),
              c.card, c.presses, qpress.presses_of(win).any_live())
    win.path_spot = None
    win.path_show_me(P.BY_ID[step_id].where)
    QApplication.processEvents()
    after = (json.dumps(win.services.settings.get(), sort_keys=True, default=dict), json.dumps(guide.read_state(), sort_keys=True),
             c.card, c.presses, qpress.presses_of(win).any_live())
    assert after == before                                                      # nothing written, nothing pressed
    kind = P.BY_ID[step_id].where.partition(":")[0]
    if kind == "hero":                                                          # lit on Up Next itself
        lst = win.page_widgets["current"].list
        part = lst.hero_part(P.BY_ID[step_id].where.partition(":")[2])
        assert part is not None and win.path_spot is not None
        assert win.path_spot.parentWidget() is lst.viewport() and win.path_spot.geometry().contains(part)
    elif kind == "circle":
        assert win.path_spot is not None and win.path_spot.parentWidget() is win.phase


def test_picking_which_words_get_a_card_in_settings_ticks_make_it_yours(lib_world):
    from app.qt import settings_catalog as catalog
    win = lib_world
    page = win.mount_settings()
    page._saved(catalog.ROW["connect_every_word"], dict(win.services.settings.get()), ["connect_every_word"])
    assert wait_until(lambda: "yours" in (guide.read_state().get("moments") or {}))


def test_the_tours_doors_are_gone(lib_world):
    # EZ2-3 (HG-4 reversed): stage ③ teaches what runs by itself by doing it — no door to the tour remains
    from app.qt import help_card
    from PyQt6.QtWidgets import QAbstractButton
    win = lib_world
    page = win.mount_settings()
    assert not [b for b in page.findChildren(QAbstractButton) if "runs by itself" in b.text()]
    card = help_card.card_for(win)
    assert not hasattr(card, "tour_button")
    assert "_tour_after_setup" not in win.__dict__


# --- the panel: one list (EZ2-1 / EZ2-3) ------------------------------------------------------------------------- #
def _open_path(panel, f, state=None):
    panel.set_path(_path(f, state if state is not None else {"first_ack": True}))
    assert wait_until(lambda: not panel.building())
    panel.open()
    assert wait_until(panel.isVisible)
    return {r.status.step.id: r for r in panel.rows}


def _lines_in_sight(widget):
    """Every word-wrapped or plain line a learner sees in `widget` (the ?s' own glyph left out)."""
    from PyQt6.QtWidgets import QLabel
    return [lab.text() for lab in widget.findChildren(QLabel) if lab.isVisibleTo(widget) and lab.text()
            and lab.objectName() != "helpmark"]


def test_the_panel_is_one_list_your_path_its_stages_now_new_for_you_later_and_done(world):
    panel = world.d.guide_panel
    panel.set_look(guide.Look("3.0.5", (), False))
    f = facts(journey_opened=True, episodes_done=1, own_cards=True, video_waiting=True)
    rows = _open_path(panel, f)
    assert panel.heading.text() == strings.GUIDE_PATH_HEADING and panel.stage_row.isVisibleTo(panel)
    assert panel.stage_row.states == (P.DONE, P.DONE, P.NOW, P.LATER)
    assert not hasattr(panel, "tab_buttons")                                    # no tabs: one list
    sight = _lines_in_sight(panel)
    now = strings.PATH_NOW.format(stage=strings.PATH_STAGES["automate"].upper())
    assert sight.index(now) < sight.index(strings.PATH_LATER) < sight.index(strings.PATH_DONE)
    assert rows["cards"].press is not None and rows["cards"].press.text() == strings.PATH_AGAIN   # done: again
    assert rows["hato"].press.text() == strings.PATH_DO and rows["hato"].press.toolTip()
    assert rows["piyo"].later and rows["piyo"].press is None                    # not useful yet: no press
    panel.close()


def test_make_it_yours_row_presses_only_while_it_opens_level(world, monkeypatch):
    # Sonic 2026-11-20 (hide ④'s press): ④ leads nowhere near *Words to make cards from* (the choice being retired; Only i+1 the
    # off-list cards' trap). The mining model (Kantan-MO) re-points ④'s press to Level, the one knob: its row is to do
    # (the stage reads right) with its ? line and a *Do it* / *Again* — and none if it pointed anywhere else
    panel = world.d.guide_panel
    panel.set_look(guide.Look("3.0.5", (), False))
    # (Mado-LT, 3.0.18: ③ ends with the loop's step, *Tell Surasura from your phone* — read once here, so ③ is done)
    f = facts(journey_opened=True, episodes_done=1, own_cards=True, junban=False, loop_read=True)
    rows = _open_path(panel, f)
    assert panel.stage_row.states == (P.DONE, P.DONE, P.DONE, P.NOW)
    r = rows["yours"]
    assert r.status.useful and not r.later and r.tick.text() == ""               # to do, never "can't apply yet"
    assert P.YOURS_PRESS == "settings:level"
    assert r.press is not None and r.press.text() == strings.PATH_DO and r.about.isVisibleTo(r)   # its line behind ?
    assert r.accessibleDescription() == strings.PATH_STEPS["yours"][1]
    panel.close()
    # the rest row by row: a second open would race the shell's own fresh look (the open asks one on a worker, and its
    # answer replaces the path set here — --stress-changed, run 1 of 20)
    from app.qt.guide import _StepRow

    def row(f2):
        return _StepRow({s.step.id: s for s in P.statuses(f2, {"first_ack": True})}["yours"], lambda _s: None, panel)
    done = row(f._replace(yours_picked=True))                                   # done before: *Again*
    assert done.status.done and done.status.useful and done.press.text() == strings.PATH_AGAIN
    monkeypatch.setattr(P, "YOURS_PRESS", "settings:connect_mine_words")        # never a press to the retired choice
    assert row(f).press is None and row(f._replace(yours_picked=True)).press is None


def test_a_step_rows_do_it_runs_its_own_press_and_closes_the_panel(world):
    went = []
    panel = world.d.guide_panel
    panel.act.connect(went.append)                                              # (the shell's slot runs too: harmless)
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True, video_waiting=True))
    rows["hato"].press.click()
    assert went == ["hato"] and not panel.isVisible()


def test_the_cards_line_is_behind_its_question_mark_never_in_sight(card):
    from PyQt6.QtCore import Qt
    for got, (title, line) in ((("step", "words", EP2), strings.PATH_STEPS["words"]),
                               (("step", "cards", EP3), strings.PATH_STEPS["cards"]),
                               (("step", "hato", ()), strings.PATH_STEPS["hato"])):
        card.set_card(got, (("x", "Do it", "tip"),))
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
    _shown(win, facts())
    mark = win.duties.next_card.about
    assert mark.isVisible() and mark.toolTip() == strings.PATH_STEPS["words"][1]
    QTest.mouseClick(mark, Qt.MouseButton.LeftButton)
    mark.setFocus()
    QTest.keyClick(mark, Qt.Key.Key_Return)
    QTest.keyClick(mark, Qt.Key.Key_Space)
    assert asked == [mark, mark, mark]
    assert win.duties.next_card.card == ("step", "words", EP2)                  # revealing presses nothing else


def test_a_step_that_cant_apply_now_reads_not_yet_with_when_behind_its_question_mark(world):
    panel = world.d.guide_panel
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True))   # no Anki, book, video
    later = {step_id for step_id, r in rows.items() if r.later}
    # (④'s applies once cards are made; Mado-LT: the loop's step once Anki synced — no Anki here, so not yet)
    assert later == {"junban", "backfill", "loop", "audiobook", "hato", "piyo"}
    for step_id in later:
        r = rows[step_id]
        assert r.press is None and r.tick.text() == "", step_id                 # never a dead end, never a tick
        assert r.about.isVisibleTo(panel) and r.about.toolTip() == strings.PATH_WHEN[step_id]
        assert strings.PATH_WHEN[step_id] in r.accessibleName()


def test_a_step_done_before_that_cant_apply_now_keeps_its_tick_and_no_press(world):
    panel = world.d.guide_panel
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True, lined_up=True))
    r = rows["audiobook"]                                                       # lined up once; no book in Current now
    assert r.status.done and not r.later and r.tick.text() == strings.PATH_TICK and r.press is None


def test_a_missing_module_is_never_listed_even_as_not_yet(world):
    panel = world.d.guide_panel
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True, junban=False))
    assert not {"junban", "backfill"} & set(rows)


def test_tab_reaches_every_question_mark_in_the_path_in_order(world):
    # (adversary r1 #2) a not-yet row has no press: its ? is its only control, and Tab must reach it
    from app.qt.tooltip import AboutMark
    panel = world.d.guide_panel
    rows = _open_path(panel, facts(journey_opened=True, episodes_done=1, own_cards=True))
    seen = []
    for _ in range(40):
        panel.focusNextPrevChild(True)
        seen.append(QApplication.focusWidget())
    piyo = rows["piyo"].about
    assert piyo in seen and all(r.about in seen for r in rows.values())
    words = rows["words"]
    assert seen.index(words.about) == seen.index(words.press) - 1               # the ? before its row's press
    assert isinstance(piyo, AboutMark)
    panel.close()


def test_the_made_card_says_where_later_steps_wait_in_sight(card):
    # (adversary r1 #3) OK puts the card away for good: where the path lives is a place, said in sight
    card.set_card(("made",))
    assert card.title.isVisibleTo(card) and card.title.text() == strings.NEXT_MADE_WHERE
    assert card.about.toolTip() == strings.NEXT_MADE_LINE


def test_the_audiobooks_press_lands_on_current_and_the_bar_says_the_press(lib_world):
    # (re-check r2 #1) its own press is on the book's ⋯: Current lit, and the bar names the ⋯ entry that does it
    win = lib_world
    assert guide.anchor_ok(P.BY_ID["audiobook"].where)
    win.path_press("audiobook")
    assert wait_until(lambda: win.bar_line.accessibleDescription() == strings.PATH_THEN["audiobook"])


def test_a_question_marks_line_stays_inside_its_window_even_at_the_windows_top(qapp):
    # (lead's check: Settings' Fill your cards ? at 100 % put its two-line bubble above the page, cut by the window's
    # top) a ?'s bubble keeps to its window: no room above → below the ?, never outside
    from PyQt6.QtCore import QPoint, QRect
    from PyQt6.QtWidgets import QWidget
    from app.qt import tooltip
    host = QWidget()
    host.resize(700, 400)
    tips = tooltip.Tooltips(host)
    host.tooltips = tips
    mark = tooltip.AboutMark(strings.HELP_MARK, host)
    mark.set_about("About Fill your cards", "Adds to your Anki cards how each word is usually used (パターン) and "
                                            "two more sentences from your own content (例文). Restore puts every card back")
    mark.move(300, 6)                                                           # right at the window's top
    host.move(200, 300)                         # room above on the screen, none in the window (the 100 % capture's case)
    host.show()
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        QTest.mouseClick(mark, Qt.MouseButton.LeftButton)                      # a press reveals (the bubble's rules)
        assert wait_until(tips.bubble.isVisible)
        window = QRect(host.mapToGlobal(QPoint(0, 0)), host.size())
        bubble = tips.bubble.geometry()
        assert window.contains(bubble), (window, bubble)
        assert bubble.top() > mark.mapToGlobal(QPoint(0, 0)).y()                # flipped below the ?
    finally:
        tips.hide()
        tips.bubble.deleteLater()
        host.close()


def test_a_title_refits_when_the_text_size_changes_so_its_question_mark_stays_beside_it(card):
    # (adversary r1 #6) the text size changes live: a title held to its old width would wrap its last word
    from PyQt6.QtGui import QFont
    card.set_card(("step", "words", EP2), (WORDS,))
    small = card.title.maximumWidth()
    font = QFont(card.title.font())
    font.setPointSizeF(font.pointSizeF() * 1.6)
    card.title.setFont(font)
    assert card.title.maximumWidth() > small


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
    t0 = time.perf_counter()
    panel.place()
    assert (time.perf_counter() - t0) * 1000 < 4.0


def test_without_a_library_the_panel_is_whats_new_alone(world):
    panel = world.d.guide_panel
    panel.set_look(guide.Look("3.0.5", (), False))
    panel.set_path(None)
    assert wait_until(lambda: not panel.building())
    assert not panel.stage_row.isVisibleTo(panel) and panel.heading.isVisibleTo(panel)
    assert panel.heading.text() != strings.GUIDE_PATH_HEADING and not panel.rows


def test_the_journey_opening_is_kept_as_the_first_steps_moment(world):
    world.win._guide_moment("journey")
    assert wait_until(lambda: "journey" in (guide.read_state().get("moments") or {}))


# --- the adversary's round 1 ------------------------------------------------------------------------------------- #
def test_every_stage_steps_settings_place_shows_for_a_new_learner(lib_world):
    page = lib_world.mount_settings()
    for step in P.STEPS:
        kind, _sep, name = step.where.partition(":")
        if kind == "settings" and step.stage is not None and step.id != "backfill":
            assert page.shows(name), step.id                                     # Show me never dead-ends here


def test_the_card_never_comes_mid_drag_and_ok_goes_at_once(lib_world):
    win = lib_world
    c = win.duties.next_card
    win.toasts.dragging = True
    try:
        _shown(win, facts())
        assert not c.isVisible() and win._guide_soon.isActive()                 # waits: the rows would jump
    finally:
        win.toasts.dragging = False
    _shown(win, facts(journey_opened=True, episodes_done=1, own_cards=True))
    assert c.card == ("made",)
    c.primary.click()
    assert not c.isVisible()
    assert wait_until(lambda: guide.read_state().get("first_ack") is True)


def test_a_later_steps_not_now_is_kept_and_no_other_later_card_follows_this_run(lib_world):
    win = lib_world
    useful = facts(journey_opened=True, episodes_done=1, own_cards=True, video_waiting=True, book_in_current=True,
                   junban=False)
    c = _shown(win, useful, {"first_ack": True})
    assert c.card == ("step", "audiobook", ())
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


def test_the_journey_really_opening_ticks_step_one(lib_world, monkeypatch):
    win = lib_world
    monkeypatch.setattr(win.services, "open_journey", lambda *file: True)        # the browser asked: it opened
    win._open_journey()
    assert wait_until(lambda: "journey" in (guide.read_state().get("moments") or {}))
