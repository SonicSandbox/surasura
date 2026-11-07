"""Help cards (Sonic 2026-11-06 "Ok do it", into 3.0; spec tracks/window/work/help-cards, HG-1…HG-5, HC-1…HC-5):
the catalog, the card, *Why?* on toasts and on the circles, the tour and its *Try it*, the clip player, the one-time
hints. Logic, light (the spec's §13): looks are Sonic's, by the captures; these tests hold the rules.

What a wrong answer would cost a learner: a ? that opens nothing or the wrong card; a card that names a setting that
isn't there; a *Why?* that loses the toast's Undo (its time running out behind the card); a *Try it* that becomes an
automatic job (a Generate the learner asked for read as one they didn't); a clip decoding on the window's thread (the
window stutters), running while minimised, or holding its frames after the card closed; a hint over an Undo toast, or
two hints in a minute.
"""
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QImage, QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget

from app.qt import help_card, hints as hints_module, strings, toast
from app.services import causes, help_cards
from tests.qt.conftest import wait_until
from tests.qt.test_jobs_bar import world  # noqa: F401  (`world`: the fixture — a window with its duties)

JA = "葬送のフリーレン"


# --- the catalog (Qt-free) ------------------------------------------------------------------------------------------ #
def test_every_card_has_its_words_and_17_cards_make_the_catalog():
    assert len(help_cards.CARDS) == 17 and set(help_cards.BY_ID) == set(strings.HELP_CARDS)
    for card in help_cards.CARDS:
        title, line, _after = strings.HELP_CARDS[card.id]
        assert title and line, card.id
        assert card.area in help_cards.AREAS and card.area in strings.HELP_AREAS
    assert set(strings.HELP_ALSO) <= set(help_cards.BY_ID)


def test_every_settings_target_is_a_real_reveal_target_and_every_try_it_is_a_press_the_window_has():
    from app.qt import settings_catalog as catalog
    for card in help_cards.CARDS:
        if card.settings:
            assert catalog.locate(card.settings) is not None, card.id
        if card.try_it:
            assert card.try_it in help_cards.TRY_IT and card.try_it in strings.HELP_TRY, card.id
    assert set(help_cards.TRY_IT) == set(strings.HELP_TRY) == set(strings.HELP_TRY_MISSING)


def test_the_screen_cards_cover_every_tab_and_settings_sections_have_theirs():
    from app.qt import settings_catalog as catalog
    for tab in ("current", "finished", "needs", "settings"):
        assert help_cards.screen_card(tab) in help_cards.BY_ID
    sections = {s.id for s in catalog.SECTIONS}
    for section, card in help_cards.SECTION_CARD.items():
        assert section in sections and card in help_cards.BY_ID
    assert help_cards.screen_card("settings", "level") == "level"
    assert help_cards.screen_card("settings", "app") == "automation"       # a section with no card of its own
    assert help_cards.screen_card("library") is None                       # a screen with none: All help


def test_without_junban_its_two_cards_leave_all_help_the_tour_and_their_question_marks():
    absent = lambda name: False                                            # noqa: E731
    present = lambda name: True                                            # noqa: E731
    assert not help_cards.available("junban", absent) and not help_cards.available("backfill", absent)
    assert help_cards.available("cards", absent) and not help_cards.available("nope", present)
    every = [i for _a, ids in help_cards.all_help(absent) for i in ids]
    assert "junban" not in every and "backfill" not in every and len(every) == 15
    assert help_cards.tour(absent) == ("automation", "cards", "known", "generate", "arrivals", "stones")
    assert len(help_cards.tour(present)) == 8
    assert help_card.help_mark("junban", None, has_module=absent) is None


def test_files_lists_only_what_is_there_and_a_missing_manifest_reads_as_empty(tmp_path):
    (tmp_path / "current.webp").write_bytes(b"RIFF")
    (tmp_path / "circles-1.png").write_bytes(b"x")
    assert help_cards.files("current", str(tmp_path)) == {"clip": str(tmp_path / "current.webp"), "poster": None,
                                                         "stills": []}
    assert help_cards.files("circles", str(tmp_path))["stills"] == [str(tmp_path / "circles-1.png")]
    assert help_cards.files("nope", str(tmp_path)) == {"clip": None, "poster": None, "stills": []}
    assert help_cards.manifest(str(tmp_path)) == {}


# --- the toast's *Why?* ---------------------------------------------------------------------------------------------- #
@pytest.fixture
def host(qapp):
    w = QWidget()
    w.resize(900, 600)
    w.show()
    h = toast.ToastHost(w)
    yield h
    w.close()


def test_a_toast_with_a_cause_has_why_and_one_without_has_none(host):
    asked = []
    host.why_asked = lambda cause, done: asked.append((cause, done))
    host.show(JA)
    assert host.card.why is None or not host.card.why.isVisibleTo(host.card)
    why = causes.Cause("It was the last episode", None, "stones")
    host.show(JA, undo=lambda: None, buttons=[("A", "a", lambda: None), ("B", "b", lambda: None)], why=why)
    shown = [b for b in host.card.buttons if b.isVisibleTo(host.card)]
    assert len(shown) == toast.MAX_BUTTONS                                  # Undo + two: *Why?* is outside the count
    assert host.card.why.isVisibleTo(host.card) and host.card.why.toolTip()
    lay = host.card.layout()
    assert lay.indexOf(host.card.why) == lay.count() - 1                   # the last in the row
    host.card.why.click()
    assert asked and asked[0][0] == why


def test_a_toasts_time_pauses_while_its_card_is_open_and_runs_on_after(host):
    done = []
    host.why_asked = lambda cause, d: done.append(d)
    host.show(JA, undo=lambda: None, why=causes.Cause("x", None, "stones"))
    assert host.life.isActive()
    host.card.why.click()
    assert host.paused and not host.life.isActive() and host.alive          # its Undo is still there
    done[0]()                                                               # the card closed
    assert not host.paused and host.life.isActive()


# --- the card ---------------------------------------------------------------------------------------------------- #
def test_the_main_question_mark_opens_this_screens_card_and_its_foot_holds_the_rest(world):
    world.d.help.click()
    card = world.win._help_card
    assert card.isVisible() and card.card_id == "current"
    assert card.title.text() == strings.HELP_CARDS["current"][0]
    for b in (card.all, card.tour_button, card.guide, card.close_button):
        assert b.isVisibleTo(card) and b.toolTip()
    card.close()
    world.win.show_tab("finished")
    world.d.help.click()
    assert card.isVisible() and card.card_id == "finished"
    card.close()


def test_a_card_opened_by_why_says_its_cause_first_in_the_accent(world):
    why = causes.Cause("You moved something in your library: Anki's order follows", None, "junban")
    card = world.win.open_help("current", cause=why)
    assert card.cause_line.isVisibleTo(card) and card.cause_line.text() == why.line
    assert card.layout().indexOf(card.cause_line) < card.layout().indexOf(card.line)
    card.close()
    card = world.win.open_help("current")
    assert not card.cause_line.isVisibleTo(card)                           # opened by its ?: no cause line
    card.close()


def test_esc_closes_the_card_and_never_the_window(world):
    card = world.win.open_help("level")
    assert card.isVisible()
    QApplication.sendEvent(card, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert wait_until(lambda: not card.isVisible())
    assert world.win.isVisible()


def test_the_card_is_built_once_and_all_help_once(world):
    card = world.win.open_help("current")
    card.close()
    again = world.win.open_help("known")
    assert again is card                                                    # one card a window (R5)
    card.show_all()
    card.show_all()
    assert card.builds == 1
    shown = [b for b in card.all_parts if hasattr(b, "click") and b.isVisibleTo(card)]
    assert len(shown) == len([i for _a, ids in help_cards.all_help() for i in ids])
    shown[0].click()
    assert card.card_id is not None and not any(b.isVisibleTo(card) for b in card.all_parts)
    card.close()


def test_open_its_settings_closes_the_card_and_reveals_its_row(world, monkeypatch):
    asked = []
    monkeypatch.setattr(world.win, "open_setting", lambda target: asked.append(target) or True)
    card = world.win.open_help("cards")
    card.settings.click()
    assert asked == ["connect_enabled"] and not card.isVisible()


def test_the_tour_steps_through_the_cards_that_show_and_ends_at_done(world):
    card = world.win.open_tour()
    ids = help_cards.tour()
    assert card.card_id == ids[0] and card.step.text() == strings.HELP_STEP.format(n=1, total=len(ids))
    assert not card.back.isEnabled() and card.next.text() == strings.HELP_NEXT
    for _ in ids[1:]:
        card.next.click()
    assert card.card_id == ids[-1] and card.next.text() == strings.HELP_DONE and card.tour_foot.isVisibleTo(card)
    card.back.click()
    assert card.card_id == ids[-2]
    card.next.click()
    card.next.click()                                                       # *Done*
    assert not card.isVisible() and card.tour is None                      # nothing remembered


def test_the_strips_question_mark_lists_every_lit_circle_with_its_why(world):
    from app.services import jobs
    why = causes.Cause("Surasura opened", None, "known")
    job = world.services.registry.submit("anki-sync", "Updating known words from Anki", start=lambda j: None,
                                         automatic=True, cause=why)
    strip = world.win.phase
    assert wait_until(lambda: any(c == "anki" for c, _l, _w in strip.causes()))
    world.win.phase_help.click()
    card = world.win._help_card
    lines = [r.text() for r in card.rows if r.isVisibleTo(card)]
    assert lines[0] == strings.HELP_LIT and any(strings.PHASE_NAMES["anki"] in t for t in lines)
    assert any("Why: Surasura opened" in t for t in lines)
    card.close()
    job.finish(ok=True)
    assert wait_until(lambda: not world.services.registry.live("anki-sync")) and jobs.DONE


def test_the_circles_hover_says_why_under_an_automatic_job_and_its_last_line_keeps_it(world):
    why = causes.Cause("Files in your library changed since Surasura last read them", None, "generate")
    job = world.services.registry.record("library-maintain", "Tidying your library", cause=why)
    strip = world.win.phase
    assert wait_until(lambda: "Why: Files in your library" in strip.hover_text("arrivals"))
    job.finish(ok=True)
    assert wait_until(lambda: "Why: " not in strip.hover_text("arrivals")
                      and why.line in strip.hover_text("arrivals"))         # *Last: … · its cause*


def test_try_it_for_generate_is_the_learners_own_request_never_a_quiet_one(world):
    asked = []
    world.services.generate = lambda *a, **k: asked.append(k)
    world.win.page_widgets["current"].view_model = type("V", (), {"rows": (object(),)})()
    assert world.win.help_try_ready("update_journey") is None
    card = world.win.open_help("generate")
    assert card.try_it.isVisibleTo(card) and card.try_it.text() == strings.HELP_TRY["update_journey"][0]
    card.try_it.click()
    assert wait_until(lambda: asked)
    assert not asked[0].get("quiet")
    card.close()


def test_a_try_it_that_cant_run_says_whats_missing_instead(world):
    card = world.win.open_help("cards")
    assert not card.try_it.isVisibleTo(card)
    assert card.missing.isVisibleTo(card) and card.missing.text() == strings.HELP_TRY_MISSING["mine_top"]
    card.close()


# --- the clip player ------------------------------------------------------------------------------------------------- #
class _FakeReader:
    """A WebP reader stand-in: `frames` frames of 40 ms; each read records the thread it ran on."""
    threads = []

    def __init__(self, frames=3):
        self.left = frames

    def canRead(self):
        return self.left > 0

    def read(self):
        _FakeReader.threads.append(threading.get_ident())
        self.left -= 1
        img = QImage(8, 8, QImage.Format.Format_ARGB32)
        img.fill(0)
        return img

    def nextImageDelay(self):
        return 40


def test_no_frame_is_decoded_on_the_windows_thread_and_closing_frees_them(qapp, monkeypatch):
    from app.qt import freeze, motion
    monkeypatch.setattr(freeze, "frozen", lambda: False)
    motion.clock().mode.set_setting("full")
    _FakeReader.threads = []
    stage = QWidget()
    stage.resize(600, 400)
    stage.show()
    player = help_card.ClipPlayer(stage, reader_factory=lambda path, size: _FakeReader())
    player.show()
    player.set_clip("clip.webp", None, JA)
    assert wait_until(lambda: player.decoded >= 2)
    assert _FakeReader.threads and threading.main_thread().ident not in _FakeReader.threads
    player.stop()
    assert player._image is None and not player._ahead and player._reader == {}
    stage.close()


def test_the_clip_stops_while_its_window_is_minimised(qapp, monkeypatch):
    from app.qt import freeze, motion
    monkeypatch.setattr(freeze, "frozen", lambda: False)
    motion.clock().mode.set_setting("full")
    stage = QWidget()
    stage.resize(600, 400)
    stage.show()
    player = help_card.ClipPlayer(stage, reader_factory=lambda path, size: _FakeReader(50))
    player.show()
    player.set_clip("clip.webp", None, JA)
    assert player._wanted()
    monkeypatch.setattr(stage, "isMinimized", lambda: True)
    player._sync()
    assert not player._wanted() and player._anim is None
    stage.close()


def test_an_unreadable_clip_leaves_the_words_and_never_an_error(qapp, monkeypatch, tmp_path):
    from app.qt import freeze, motion
    monkeypatch.setattr(freeze, "frozen", lambda: False)
    motion.clock().mode.set_setting("full")
    bad = tmp_path / "bad.webp"
    bad.write_bytes(b"not a picture")
    stage = QWidget()
    stage.resize(600, 400)
    stage.show()
    player = help_card.ClipPlayer(stage)
    player.show()
    player.set_clip(str(bad), None, JA)
    assert wait_until(lambda: player.clip is None)                         # given up: the words carry it
    assert player.accessibleName() == strings.HELP_CLIP_NAME.format(line=JA)
    stage.close()


# --- the one-time hints (WP6) ------------------------------------------------------------------------------------- #
class _Win:
    def __init__(self, seen=()):
        self.settings = {"hints_seen": list(seen)}
        win = self

        class _S:
            def get(self):
                return win.settings

            def set(self, changes):
                win.settings.update(changes)
        self.services = type("Svc", (), {"settings": _S(), "setup_open": None})()
        self.toasts = type("T", (), {"dragging": False, "alive": False})()
        self.moves = type("M", (), {"reader": type("R", (), {"store_id": lambda self: "lib1"})()})()

    def isMinimized(self):
        return False


def test_a_hint_shows_once_per_library_and_is_recorded_first():
    win = _Win()
    now = [0.0]
    h = hints_module.Hints(win, clock=lambda: now[0])
    shown = []
    assert h.once("first_amber", lambda: shown.append(1))
    assert win.settings["hints_seen"] == ["first_amber:lib1"]
    now[0] = 1000.0
    assert not h.once("first_amber", lambda: shown.append(2)) and shown == [1]


def test_a_hint_waits_while_a_toast_is_up_and_never_two_in_a_minute():
    win = _Win()
    now = [0.0]
    h = hints_module.Hints(win, clock=lambda: now[0])
    shown = []
    win.toasts.alive = True                                     # an Undo toast: never replaced
    assert not h.once("first_amber", lambda: shown.append("amber")) and "first_amber" in h.owed
    win.toasts.alive = False
    assert h.again() and shown == ["amber"]
    assert not h.once("first_card_wait", lambda: shown.append("wait"))      # within the minute: owed
    now[0] = hints_module.GAP_S + 1
    assert h.again() and shown == ["amber", "wait"]


def test_the_star_ask_and_keep_watched_read_the_one_helper():
    from app.qt import star_ask
    win = _Win(seen=["star_ask", 3, None])
    win.hints = hints_module.Hints(win)
    ask = star_ask.StarAsk(win)
    assert ask._seen() and ask._list() == ["star_ask"]          # the odd entries left out, as before
    win.toasts.dragging = True
    assert ask._blocked()


def test_an_hc3_hint_held_back_is_never_shown_after_its_moment_and_never_behind_a_help_card():
    # review #5, #6: a moment that passed while a toast or a card covered the window shows no stale hint later
    win = _Win()
    now = [0.0]
    h = hints_module.Hints(win, clock=lambda: now[0])
    shown = []
    win.toasts.alive = True
    assert not h.once("first_amber", lambda: shown.append("amber"), owe=False) and h.owed == {}
    win.toasts.alive = False
    assert not h.again() and shown == []                       # the amber was answered meanwhile: nothing stale
    win._help_card = type("C", (), {"isVisible": lambda self: True})()
    assert h.blocked()
    del win._help_card
    assert h.once("first_amber", lambda: shown.append("amber"), owe=False) and shown == ["amber"]


def test_the_setup_doors_tour_opens_only_once_setup_has_ended(world):
    # review #1: never on top of the wizard's later pages
    win = world.win
    win.__dict__["_tour_after_setup"] = True
    win.setup_held(True)
    QApplication.processEvents()
    assert getattr(win, "_help_card", None) is None or not win._help_card.isVisible()
    win.setup_held(False)
    assert wait_until(lambda: getattr(win, "_help_card", None) is not None and win._help_card.isVisible())
    assert win._help_card.tour is not None and "_tour_after_setup" not in win.__dict__
    win._help_card.close()


def test_update_my_journey_now_says_already_running_while_a_generate_is_on_its_way(world):
    from app.services import generate as G
    world.win.page_widgets["current"].view_model = type("V", (), {"rows": (object(),)})()
    world.controller.push(state=G.RUNNING, step="Counting words", done=1, total=2)
    assert wait_until(lambda: world.win.help_try_ready("update_journey") == strings.HELP_TRY_BUSY)


def test_play_once_under_reduced_motion_steps_every_frame_and_rests_on_the_last(qapp, monkeypatch):
    # the intent keeper: the clock runs no loop under Reduced, so ▶ (the learner's own press) steps the frames itself
    from app.qt import freeze, motion
    monkeypatch.setattr(freeze, "frozen", lambda: False)
    motion.clock().mode.set_setting("reduced")
    try:
        stage = QWidget()
        stage.resize(600, 400)
        stage.show()
        player = help_card.ClipPlayer(stage, reader_factory=lambda path, size: _FakeReader(3))
        player.show()
        player.set_clip("clip.webp", None, JA)
        assert player.play.isVisibleTo(stage) and player.decoded == 0
        player.play.click()
        assert wait_until(lambda: player.swaps == 3)
        assert wait_until(lambda: not player._once and player.play.isVisibleTo(stage))   # ▶ again: one more play
        assert player._image is not None                                  # resting on its last frame, not the poster
        stage.close()
    finally:
        motion.clock().mode.set_setting("full")


def test_the_circles_question_mark_is_the_strips_own_last_mark_so_the_bars_line_keeps_its_edge(world):
    # train 18's red (test_polish): a ? of its own between the strip and the bar's line pushed the line ~30 px on
    strip, mark = world.win.phase, world.win.phase_help
    assert mark.parentWidget() is strip and strip.rect().contains(mark.geometry())
    assert mark.geometry().left() > strip.rect_of("anki").right()           # after the five circles
    assert strip.circle_at(mark.geometry().center()) is None               # never read as a circle
