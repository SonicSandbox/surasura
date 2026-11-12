"""The feature guide in the window (Hoshi-S, Sonic 2026-11-12, part of the launch; spec: the 3.0 planning folder,
`tracks/window/work/feature-guide-2026-11-12/SPEC.md`): the ✦ beside the ?, its glow, its panel and *Show me*.

What a wrong answer would cost a learner: a ✦ that glows after every start (a nag) or never goes out; a panel that
reads files on the window's thread (a stutter as it opens); Esc closing the window instead of the panel; their own
kind of item buried; *Show me* going nowhere, or silently doing nothing.
"""
import json
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from app.qt import guide as guide_ui, motion, strings
from app.services import guide
from tests.qt.conftest import wait_until
from tests.qt.test_jobs_bar import world  # noqa: F401  (`world`: the fixture — a window with its duties)

NOTES = {"version": "3.0.4", "date": "2026-11-12", "items": [
    {"id": "zh-cards", "kind": "new", "text": "エピソードからカードを作れる。", "for": ["miner"],
     "where": "settings:text_size"},
    {"id": "piyo-help", "kind": "new", "text": "Piyo に Surasura のことを聞ける。", "for": ["piyo"],
     "where": "settings:practice_ai"},
    {"id": "faster", "kind": "tweak", "text": "検索が速くなった。", "for": ["everyone"]},
    {"id": "skip-word", "kind": "tweak", "text": "Anki が受け付けない単語はスキップできる。", "for": ["miner"],
     "where": "tab:needs"},
    {"id": "report", "kind": "fix", "text": "報告の画面が短い画面に収まる。", "for": ["everyone"]},
    {"id": "words-split", "kind": "fix", "text": "という の切り方が正しくなった。", "for": ["miner"]}]}


@pytest.fixture
def notes(tmp_path, monkeypatch):
    """The notes in a folder of the test's, this window's version 3.0.4, and the looks counted by thread."""
    folder = tmp_path / "whats_new"
    folder.mkdir()
    (folder / "3.0.4.json").write_text(json.dumps(NOTES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(guide, "folder", lambda: str(folder))
    monkeypatch.setattr(guide, "current_version", lambda: "3.0.4")
    threads = []
    real = guide.look

    def look(*args, **kwargs):
        threads.append(threading.current_thread())
        return real(*args, **kwargs)
    monkeypatch.setattr(guide, "look", look)
    return threads


def _looked(world, notes, n=1):
    world.win._guide_look()
    panel = world.d.guide_panel
    assert wait_until(lambda: len(notes) >= n and panel.look is not None and not panel.building())


def test_the_star_waits_for_a_look_then_sits_just_left_of_the_question_mark_glowing(world, notes):
    g = world.d.guide
    assert g.isHidden()                                                     # nothing read yet: no ✦
    _looked(world, notes)
    assert wait_until(lambda: g.isVisible() and g.glow)
    row = world.win.header.layout()
    assert row.indexOf(g) == row.indexOf(world.d.help) - 1
    assert g.toolTip() == strings.GUIDE_TIP and g.accessibleName() == strings.GUIDE_GLOW_NAME
    assert all(t is not threading.main_thread() for t in notes)            # the files read on a worker


def test_opening_ends_the_glow_at_once_marks_it_seen_and_the_next_start_has_no_glow(world, notes):
    _looked(world, notes)
    g, panel = world.d.guide, world.d.guide_panel
    g.click()
    assert wait_until(panel.isVisible) and not g.glow                       # at once, before any worker answers
    assert wait_until(lambda: guide.read_state().get("seen") == "3.0.4")
    panel.close()
    world.win._guide_look()                                                 # the next start's look
    assert wait_until(lambda: len(notes) >= 3)
    QApplication.processEvents()
    assert not g.glow and g.isVisible()                                     # seen: no glow, still there to read


def test_an_open_with_the_same_answer_builds_nothing_again(world, notes):
    _looked(world, notes)
    panel = world.d.guide_panel
    assert panel.builds == 1
    for _ in range(2):
        count = len(notes)
        world.d.guide.click()
        assert wait_until(lambda: panel.isVisible() and len(notes) > count)
        QApplication.processEvents()
        panel.close()
    assert panel.builds == 1                                                 # the same answer: nothing rebuilt (S19)


def test_each_item_is_one_line_yours_first_and_every_fix_folds_into_one_line(world, notes):
    # Sonic, 2026-11-12: "everything earns its place" — one plain line an item, Show me only on something to try
    world.win.services.settings.set({"connect_enabled": True})
    _looked(world, notes)
    panel = world.d.guide_panel
    world.d.guide.click()
    assert wait_until(panel.isVisible)
    assert panel.heading.text() == strings.GUIDE_HEADING_ONE.format(version="3.0.4")    # one release: no version line
    shown = [c for c in panel.cards if c.isVisibleTo(panel)]
    assert [c.item.id for c in shown] == ["zh-cards", "skip-word", "piyo-help"]          # Connect on: the miner's first
    groups = [w for w in panel.body.findChildren(type(panel.heading)) if w.objectName() == "guidegroup"]
    assert [g.text() for g in groups] == [strings.GUIDE_FOR_YOU]                         # it explains the order, once
    (fold, fixes, _open), = panel.folds                                     # leads nowhere: folded (Kantan-X rule 2)
    assert [c.item.id for c in fixes] == ["words-split", "faster", "report"]
    assert not any(c.isVisibleTo(panel) for c in fixes)
    assert fold.text() == strings.GUIDE_FIXES.format(n=3) and fold.toolTip()
    fold.click()
    assert all(c.isVisibleTo(panel) for c in fixes) and fold.text() == strings.GUIDE_FIXES_OPEN.format(n=3)
    assert all(c.show_me is not None for c in panel.cards if c not in fixes)            # every shown item leads somewhere
    for card in panel.cards:
        assert card.text.text() == card.item.text and card.accessibleName() == card.item.text
        assert (card.show_me is not None) == bool(card.item.where)
        if card.show_me is not None:
            assert card.show_me.toolTip() and card.show_me.accessibleName()
    panel.close()


def test_esc_closes_the_panel_and_never_the_window(world, notes):
    _looked(world, notes)
    world.d.guide.click()
    panel = world.d.guide_panel
    assert wait_until(panel.isVisible)
    QApplication.sendEvent(panel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert wait_until(lambda: not panel.isVisible())
    assert world.win.isVisible()


def test_the_panel_stays_inside_a_short_window_and_scrolls(world, notes):
    _looked(world, notes)
    world.win.resize(1000, 620)                                              # the window's least size
    world.d.guide.click()
    panel = world.d.guide_panel
    assert wait_until(panel.isVisible)
    for entry in panel.folds:
        if not entry[2]:
            entry[0].click()
    parent = panel.parentWidget()
    assert panel.geometry().bottom() <= parent.height() and panel.geometry().right() <= parent.width()
    assert panel.geometry().left() >= 0
    panel.close()


def test_show_me_reveals_a_setting(world, notes, monkeypatch):
    asked = []
    monkeypatch.setattr(world.win, "open_setting", lambda target: asked.append(target))
    _looked(world, notes)
    world.d.guide.click()
    panel = world.d.guide_panel
    assert wait_until(panel.isVisible)
    card = next(c for c in panel.cards if c.item.id == "zh-cards")
    card.show_me.click()
    assert asked == ["text_size"] and not panel.isVisible()                  # a row every learner's Settings shows


def test_show_me_washes_a_control_and_a_tab_with_nothing_in_it_says_so(world, notes, monkeypatch):
    washed = []
    monkeypatch.setattr(motion, "wash", lambda widget, radius=0.0, ms=None: washed.append(widget))
    world.win.guide_show_me("control:report")
    assert washed == [world.win.report_button]              # (recorded: the freeze switch ends a real wash at once)
    assert world.win.tab_buttons["needs"].isHidden()                         # Needs you lists nothing here
    world.win.show_tab("finished")                                           # (show_tab's own fallback is Current)
    before = world.win.current_tab()
    world.win.guide_show_me("tab:needs")
    assert wait_until(lambda: world.win.bar_line.accessibleDescription() == strings.GUIDE_NOT_HERE)
    assert world.win.current_tab() == before                                 # a hidden tab is never opened
    world.win.guide_show_me("tab:finished")
    assert world.win.current_tab() == "finished" and washed[-1] is world.win.tab_buttons["finished"]
    world.win.guide_show_me("control:nope")
    assert len(washed) == 2


def test_the_glow_is_painted_still_with_no_motion_on_the_clock(world, notes):
    _looked(world, notes)
    g = world.d.guide
    assert wait_until(lambda: g.glow)
    QApplication.processEvents()
    before = g.paints
    for _ in range(5):
        QApplication.processEvents()
    assert g.paints == before                                                # nothing repaints it while it rests
    assert not motion.clock()._timer.isActive()                              # and nothing runs on the clock for it


def test_release_name_says_the_version_and_its_day():
    rel = guide.Release("3.0.4", "2026-11-12", ())
    assert guide_ui.release_name(rel) == "Surasura 3.0.4 · 12 Nov"
    assert guide_ui.release_name(guide.Release("3.0.4", "", ())) == "Surasura 3.0.4"


# --- the adversary's round (2026-11-12) ------------------------------------------------------------------------ #
def _open(world):
    world.d.guide.click()
    assert wait_until(world.d.guide_panel.isVisible)
    return world.d.guide_panel


def test_an_open_panel_never_changes_under_the_learner_and_takes_the_newer_answer_once_closed(world, notes):
    older = dict(NOTES, version="3.0.3", date="2026-11-11")
    with open(os.path.join(guide.folder(), "3.0.3.json"), "w", encoding="utf-8") as f:
        json.dump(older, f, ensure_ascii=False)
    guide.write_state({"seen": "3.0.2"})                                    # two updates skipped: both show
    _looked(world, notes)
    panel = _open(world)
    shown = [c.item.version for c in panel.cards]
    assert set(shown) == {"3.0.4", "3.0.3"} and panel.builds == 1
    assert wait_until(lambda: panel._waiting is not None)                  # the seen mark's newer answer, held
    assert guide.read_state().get("seen") == "3.0.4"
    assert [c.item.version for c in panel.cards] == shown and panel.builds == 1     # still what they opened
    panel.close()
    assert wait_until(lambda: panel.builds == 2)                            # the newer answer, once closed
    assert {c.item.version for c in panel.cards} == {"3.0.4"}


def test_the_glow_never_relights_with_the_panel_open_and_an_older_answer_is_dropped(world, notes):
    _looked(world, notes)
    look = world.d.guide_panel.look._replace(glow=True)
    _open(world)
    world.win._guide_got((world.win._guide_asked, look, []))
    assert not world.d.guide.glow                                           # open: never lit again
    world.d.guide_panel.close()
    world.win._guide_got((world.win._guide_asked - 1, look, []))            # an older look, arriving late
    assert not world.d.guide.glow


def test_tab_stays_in_the_panel_and_esc_gives_the_keyboard_back_to_the_star(world, notes):
    _looked(world, notes)
    panel = _open(world)
    seen = set()
    for _ in range(6):
        panel.focusNextPrevChild(True)
        seen.add(QApplication.focusWidget())
    assert all(w is panel.scroll or panel.isAncestorOf(w) for w in seen) and panel.scroll in seen
    QApplication.sendEvent(panel, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert wait_until(lambda: not panel.isVisible())
    assert QApplication.focusWidget() is world.d.guide


def test_a_press_elsewhere_closes_the_panel(world, notes):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent
    _looked(world, notes)
    panel = _open(world)
    target = world.win.tab_buttons["current"]
    at = QPointF(target.rect().center())
    press = QMouseEvent(QEvent.Type.MouseButtonPress, at, target.mapToGlobal(at), Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, press)
    assert wait_until(lambda: not panel.isVisible())


def test_show_me_for_a_settings_row_this_learner_doesnt_have_says_so_and_lights_nothing_else(world, notes):
    world.win.services.settings.set({"connect_enabled": False})
    tab = world.win.current_tab()
    world.win.guide_show_me("settings:connect_trust_timing")                # Connect's row: hidden while it's off
    assert world.win.bar_line.accessibleDescription() == strings.GUIDE_NOT_HERE
    assert world.win.current_tab() == tab


def test_setup_running_is_a_new_pc_and_the_star_doesnt_glow(world, notes):
    world.win.services.setup_open.set()
    try:
        _looked(world, notes)
        QApplication.processEvents()
        assert world.d.guide.isVisible() and not world.d.guide.glow
        assert guide.read_state().get("seen") == "3.0.4"
    finally:
        world.win.services.setup_open.clear()


def test_the_star_keeps_its_room_while_hidden_so_the_header_never_shifts(world, notes):
    assert world.d.guide.isHidden() and world.d.guide.sizePolicy().retainSizeWhenHidden()


def test_a_panel_that_fits_shows_no_scroll_bar_and_folded_lines_are_quiet_and_lead_nowhere(world, notes):
    # the shipped 3.0.4 notes: lines long enough to wrap — a body sized by its unwrapped hints showed a bar here
    shipped = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           guide.FOLDER, "3.0.4.json")
    with open(shipped, encoding="utf-8") as src, open(os.path.join(guide.folder(), "3.0.4.json"), "w",
                                                      encoding="utf-8") as dst:
        dst.write(src.read())
    world.win.services.settings.set({"connect_enabled": True})
    _looked(world, notes)
    panel = _open(world)
    for entry in panel.folds:
        entry[0].click()
    QApplication.processEvents()
    room = panel.parentWidget().height() - panel.geometry().top() - guide_ui.EDGE
    assert panel.height() < room                                            # it fits (1280 × 800) …
    assert panel.scroll.verticalScrollBar().maximum() == 0                  # … so every line in view, no bar
    assert panel.body.height() == panel.scroll.viewport().height()
    for _fold, fixes, _shown in panel.folds:
        assert all(c.objectName() == "guidefix" and c.show_me is None for c in fixes)
    panel.close()


def test_no_slice_of_a_new_answer_passes_4_ms_and_a_newer_answer_cancels_the_rest(world, notes):
    # The lead, 2026-11-12: the 4 ms rule strict. Two releases, the shipped notes (wrapping lines): the body is built one
    # piece a turn — each piece, and the place after the last, under 4 ms on the window's thread.
    import time
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), guide.FOLDER)
    releases = guide.read_notes(here)
    look = guide.Look("3.0.4", tuple(guide.arrange(r, {"everyone", "ja", "miner", "books"}) for r in releases), True)
    panel = world.d.guide_panel
    panel.slices.clear()
    panel.set_look(look)
    assert panel.building() and not panel.cards                             # nothing built in the asking turn
    assert wait_until(lambda: not panel.building())
    assert len(panel.slices) >= len(panel.cards) and max(panel.slices) < 4.0, max(panel.slices)
    t0 = time.perf_counter()
    panel.place()
    assert (time.perf_counter() - t0) * 1000 < 4.0
    built = panel.builds
    panel.set_look(look._replace(releases=look.releases[:1]))               # a newer answer mid-way …
    QApplication.processEvents()
    panel.set_look(look)                                                     # … and another: only the last finishes
    assert wait_until(lambda: not panel.building())
    QApplication.processEvents()
    assert panel.builds == built + 1 and len({c.item.version for c in panel.cards}) == len(look.releases)
