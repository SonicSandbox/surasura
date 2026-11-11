# SPDX-License-Identifier: GPL-3.0-or-later
"""The 順 window and Put Anki back in Qt (W3.4 row 6; `qt_junban.py`, `qt_put_back.py`): every promise it makes before
an Anki write, on the harness's terms (offscreen, a temp root, loopback only).

What a wrong answer would cost, in order:
  * **Reorder pressed on a preview that no longer describes the run** — the Tk window's D1: a click re-stamped a stale
    preview after a change, a language switch, a finished Reorder / Restore or a put-back, so cards moved (or the sort
    number was overwritten) in a way the sentence never said. Each of the four paths is a test below;
  * a write that isn't a `junban` job (it would run beside the automatic re-order), the window's lock outliving it, or
    a wait for another writer that goes on writing after the window closed;
  * Restore / Put back taking Enter as yes, or losing what they name ("This can't be undone", the older question's No);
  * a settings write on open (S16), a key saved that the user never changed, the pair recorded without a deck pick;
  * the GUI thread spending more than 4 ms on a click at 4,000 rows (IK-4).

Engine calls are the existing fakes' way: the planner's real rows over real Japanese words (`test_junban_view`), the
engine's own functions patched where Anki would answer, and one end-to-end run against `FakeCollection`. Never Anki.
"""
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from app.qt import confirm, shell, windows  # noqa: E402
from modules.junban import junban_view as view  # noqa: E402
from modules.junban import first_touch, pairs, put_back_view, qt_junban, qt_put_back, reposition, undo  # noqa: E402
from modules.junban import qt_strings as qs  # noqa: E402
from modules.junban.tests.test_junban_view import real_stats  # noqa: E402
from tests.qt.conftest import _per_test_window_state, qapp, wait_until  # noqa: E402,F401
from tests.qt.test_wiring import problems  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_OK = {"ok": True, "problems": [], "warnings": [], "decks": ["TheBank"]}


@pytest.fixture
def main(qapp):
    services = shell.Services()
    services.settings.set({"enable_junban": True, "junban_deck": "TheBank"})
    services.settings.flush(5)
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    for w in qapp.topLevelWidgets():
        if w is not win:
            w.close()
    win.close()
    services.shutdown(0.5)


@pytest.fixture
def engine(monkeypatch):
    """The engine as Anki would answer it: the planner's real rows; every write recorded."""
    e = SimpleNamespace(runs=[], restores=[], dry=0, gate=None, stats=real_stats(), report={"ok": True,
                        "message": "Moved 6 cards.", "warnings": [], "problems": []}, run_gate=None)

    def dry_run(settings, job=None, unattended=False):
        e.dry += 1
        if e.gate is not None:
            e.gate.wait(10)
        return [], dict(e.stats)

    def run(settings, **kwargs):
        if e.run_gate is not None:
            e.run_gate.wait(10)
        e.runs.append((settings, kwargs))
        if kwargs.get("progress"):
            kwargs["progress"](1, 1)
        return dict(e.report)

    def restore(settings, **kwargs):
        e.restores.append((settings, kwargs))
        return {"ok": True, "message": "Restored 6 cards.", "warnings": [], "problems": []}
    monkeypatch.setattr(reposition, "preflight", lambda settings, probe=None: dict(_OK))
    monkeypatch.setattr(reposition, "dry_run", dry_run)
    monkeypatch.setattr(reposition, "run", run)
    monkeypatch.setattr(reposition, "restore", restore)
    monkeypatch.setattr(view, "context_counts", lambda settings, decks: {"context_review": 17})
    monkeypatch.setattr(view, "session_sync_likely", lambda now=None: False)
    monkeypatch.setattr(first_touch, "has_anything", lambda language: False, raising=False)
    return e


def opened(main):
    win = qt_junban.open(main)
    wait_until(lambda: win._ft is not None)
    return win


def previewed(win):
    win.on_preview()
    assert wait_until(lambda: win.session.stats is not None and not win._working)
    assert wait_until(lambda: win.btn_reorder.isEnabled())
    return win


def settled(win):
    assert wait_until(lambda: not win.is_busy() and win.session.replanning == win.session.replanned)
    return win


def card(window):
    """The confirmation open in `window` (the newest still unanswered)."""
    cards = [c for c in window.findChildren(confirm.Confirm) if c.answer is None]
    return cards[-1] if cards else None


# --- the window ----------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("control", ["deck", "restore"])
def test_a7_the_phase_strips_amber_junban_opens_this_window_at_its_decision_focused_and_washed(main, engine, control,
                                                                                               monkeypatch):
    """a7 (Sonic 2026-10-29: "If yellow i would expect it to let me go somewhere to make a decision that is
    highlighted"): 順's amber opens this window at the control to decide — the deck list (a deck to pick) or the Undo
    (the unfinished reorder) — given the focus and washed once (`motion.wash`, Settings' row wash)."""
    from app.qt import motion
    washed = []
    monkeypatch.setattr(motion, "wash", lambda widget, radius=0.0: washed.append(widget))
    win = opened(main)
    win.activateWindow()
    win.highlight(control)
    want = win.btn_restore if control == "restore" else win.deck_box
    assert win.highlighted == control and washed == [want]
    assert wait_until(lambda: not want.isEnabled() or want.hasFocus() or not win.isActiveWindow())


def test_a7a3_with_all_decks_chosen_the_deck_decision_highlights_this_deck_not_the_greyed_list(main, engine,
                                                                                               monkeypatch):
    """A7A-3: on All decks the deck list is greyed until *This deck* is chosen — that choice is what the press shows."""
    from app.qt import motion
    washed = []
    monkeypatch.setattr(motion, "wash", lambda widget, radius=0.0: washed.append(widget))
    win = opened(main)
    win.controls["scope"] = "all"
    win.highlight("deck")
    assert washed == [win.rb_deck] and win.highlighted == "deck"


def test_it_opens_one_of_a_kind_wired_tipped_and_named(main, engine):
    win = opened(main)
    assert win.windowTitle() == "順番 (Junban) — Surasura" and win.parentWidget() is main
    assert qt_junban.open(main) is win
    found, walked = problems(win)
    assert found == [] and walked >= 25
    # Every §1 control is there (or hidden only for its rule): the markers, the overwrite, Connect's row absent off.
    assert [b.text() for b in win.cb_markers.values()] == ["☆", "⚖︎", "文"]
    assert "FreqSort" in win.cb_freqsort.text() and win.cb_freqsort.property("tone") == "danger"
    assert win.own_tag is None and win.btn_put_back.accessibleName() == qs.JUNBAN_PUT_BACK_NAME


def test_connects_row_shows_with_connect_on(main, engine):
    main.services.settings.set({"connect_enabled": True, "junban_own_tag": "immersion"})
    win = opened(main)
    assert win.own_tag is not None and win.own_tag.text() == "immersion" and win.cb_order_all is not None
    assert problems(win)[0] == []


def test_esc_closes_it_and_releases_its_lock(main, engine):
    from modules.junban import auto
    win = opened(main)
    assert wait_until(lambda: win.lock.holding())
    assert auto.window_open()                              # the automatic re-order and the CLI stand aside
    lock = win.lock
    QTest.keyClick(win, Qt.Key.Key_Escape)
    assert not lock.holding()                              # let go by the close itself, not only when deleted later
    assert windows.opened(main, "junban") is None and main.isVisible()
    assert wait_until(lambda: not auto.window_open())


def test_a_window_destroyed_with_its_parent_lets_go_of_its_lock(main, engine):
    from modules.junban import auto
    win = opened(main)
    assert wait_until(lambda: win.lock.holding())
    lock = win.lock
    win.deleteLater()                                      # never closed: destroyed (the Tk window's D5)
    from PyQt6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert wait_until(lambda: not lock.holding() and not auto.window_open())


@pytest.mark.parametrize("how", ["destroyed", "quit"])
def test_a_destroy_or_the_apps_quit_sets_the_stop_a_waiting_write_reads(main, engine, how):
    # AD6-6 (D5's other half): only the lock was let go; a Reorder waiting for another program's writer could take
    # the lock during the quit and be cut off mid-batch.
    from PyQt6.QtCore import QCoreApplication, QEvent
    door = qt_put_back.open(main)                          # Settings' window, its flow ended (nothing kept)
    assert wait_until(lambda: put_back_view.NOTHING in door.lines.texts())
    door_stop = door.stop
    win = previewed(opened(main))
    engine.run_gate = threading.Event()
    win.on_reorder()
    assert wait_until(lambda: win._stops)
    stop = next(iter(win._stops))
    if how == "destroyed":
        win.deleteLater()
        door.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    else:
        main.closing.emit()                                # the shell's quit, before its windows hide
    assert stop.is_set() and door_stop.is_set()
    engine.run_gate.set()


def test_the_put_back_window_is_wired_and_reads_only(main, engine):
    win = qt_put_back.open(main)
    assert wait_until(lambda: put_back_view.NOTHING in win.lines.texts())
    assert problems(win)[0] == [] and not win.busy()


# --- nothing written on open, only what changed ------------------------------------------------------------------ #
def test_opening_writes_no_setting_and_the_first_deck_is_saved_on_the_first_action(main, engine, monkeypatch):
    main.services.settings.set({"junban_deck": ""})
    main.services.settings.flush(5)
    written = []
    real_set = main.services.settings.set
    monkeypatch.setattr(main.services.settings, "set", lambda changes, **k: written.append(dict(changes))
                        or real_set(changes, **k))
    monkeypatch.setattr(view, "probe_work", lambda settings: ({"ok": True, "version": 6}, ["TheBank", "Kanji"], None))
    win = opened(main)
    win.refresh_connection()
    assert wait_until(lambda: win.deck_box.currentText() == "TheBank")
    assert written == []                                   # shown, never saved by opening (IK-13)
    previewed(win)
    assert written == [{"junban_deck": "TheBank"}]         # the first action saves it, and only it


def test_the_automatic_first_preview_saves_nothing(main, engine, monkeypatch):
    # AD6-3 / IK-81 (S16): with the timers on, as in the app, the opening probe's automatic preview saved the deck it
    # showed. The user's own Preview still saves it.
    main.services.settings.set({"junban_deck": ""})
    main.services.settings.flush(5)
    written = []
    real_set = main.services.settings.set
    monkeypatch.setattr(main.services.settings, "set", lambda changes, **k: written.append(dict(changes))
                        or real_set(changes, **k))
    monkeypatch.setattr(view, "probe_work", lambda settings: ({"ok": True, "version": 6}, ["TheBank", "Kanji"], None))
    win = opened(main)
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    win.refresh_connection()
    assert wait_until(lambda: win.session.stats is not None and not win._working)
    win.list_updated()                                     # a Generate ended: previewed again, by itself
    settled(win)
    assert engine.dry >= 1 and written == []
    win.on_preview()
    assert wait_until(lambda: written == [{"junban_deck": "TheBank"}])


def test_a_change_saves_only_its_key_and_the_pair_only_on_a_deck_pick(main, engine, monkeypatch):
    written = []
    real_set = main.services.settings.set
    monkeypatch.setattr(main.services.settings, "set", lambda changes, **k: written.append(dict(changes))
                        or real_set(changes, **k))
    win = opened(main)
    win.cb_phrases.click()
    assert written == [{"junban_phrases": False}]
    win._decks = ["TheBank", "Kanji"]
    win._offer_decks()
    win.deck_box.setCurrentIndex(1)
    win.deck_box.activated.emit(1)
    assert written[-1] == {"junban_deck": "Kanji", "junban_replan_language": "ja", "junban_replan_deck": "Kanji"}


def test_an_entry_left_as_it_was_keeps_the_preview(main, engine):
    # D3: a focus-out with nothing changed threw the preview away and wrote settings.json.
    win = previewed(opened(main))
    win.tag_name.editingFinished.emit()
    assert win.btn_reorder.isEnabled() and win.session.stats is not None
    win.tag_name.setText("mine")
    win.tag_name.editingFinished.emit()
    assert not win.btn_reorder.isEnabled() and win.session.stats is None


# --- the preview is the confirmation (I5) and the gate fix (D1) ---------------------------------------------------- #
def test_reorder_is_off_until_a_preview_and_the_preview_writes_nothing(main, engine):
    win = opened(main)
    assert not win.btn_reorder.isEnabled()
    win.on_reorder()
    previewed(win)
    assert engine.runs == [] and engine.dry == 1
    sentence = [t for t in win.messages.texts() if t.startswith("Reorder will move")]
    assert sentence and "TheBank" in sentence[0]
    assert win.counts.text().startswith("11 new cards to reorder · 17 in review or learning")
    assert win.model.rowCount() == len(engine.stats["order"])


def test_d1a_a_preview_landing_after_a_change_never_unlocks_reorder(main, engine):
    win = opened(main)
    engine.gate = threading.Event()
    win.on_preview()
    assert wait_until(lambda: engine.dry == 1)
    win.cb_freqsort.click()                               # overwrite the sort number, ticked while it was read
    engine.gate.set()
    assert wait_until(lambda: not win._working)
    assert win.session.stats is None and win.model.rowCount() == 0
    win.toggle_row(0)                                     # a click has nothing to re-stamp
    settled(win)
    assert not win.btn_reorder.isEnabled()
    win.on_reorder()
    assert engine.runs == []


def test_a_change_undone_while_read_still_throws_the_preview_away(main, engine):
    # Haiku H10: the landing must match the generation asked when Preview was pressed. Ticked and unticked while it
    # was read, the key is the same again — but the preview was thrown away, so it never lands.
    win = opened(main)
    engine.gate = threading.Event()
    win.on_preview()
    assert wait_until(lambda: engine.dry == 1)
    win.cb_freqsort.click()
    win.cb_freqsort.click()
    engine.gate.set()
    assert wait_until(lambda: not win._working)
    assert win.session.stats is None and not win.btn_reorder.isEnabled()


def test_pressing_preview_again_throws_the_old_one_and_its_clicks_away_at_once(main, engine):
    # Haiku H9: Preview pressed again kept the old rows (and Reorder's gate on them) while the new one was read, and
    # the old clicked-off cards rode into the new preview.
    win = settled(previewed(opened(main)))
    win.toggle_row(0)
    settled(win)
    assert win.session.deselected
    engine.gate = threading.Event()
    win.on_preview()
    assert win.session.stats is None and not win.session.deselected and win.session.scope is None
    engine.gate.set()
    settled(previewed(win))
    assert not win.session.deselected


def test_a_save_that_failed_is_tried_again_with_the_next_change(main, engine, monkeypatch):
    # Haiku H8: a failed save was recorded as saved, so the next change's save left the failed key out for good.
    written = []
    real_set = main.services.settings.set
    fail = {"once": True}

    def set_(changes, **k):
        if fail.pop("once", False):
            raise OSError("settings.json is held by another program")
        written.append(dict(changes))
        return real_set(changes, **k)
    monkeypatch.setattr(main.services.settings, "set", set_)
    win = opened(main)
    win.cb_phrases.click()
    assert any("settings.json is held" in t for t in win.messages.texts())
    win.cb_list_first.click()                             # (saved as junban_unlisted)
    assert written and written[-1].get("junban_phrases") is False and "junban_unlisted" in written[-1]


def test_a_key_moved_by_another_window_while_read_never_unlocks_reorder(main, engine):
    # The re-plan switch is part of the key but has no control here: another window can save it while the preview is
    # read, with no change in this one to throw the preview away. The landing is checked against the key read when
    # Preview was pressed, so it is dropped (a key read at landing time would let it through, stamped with the new one).
    win = opened(main)
    engine.gate = threading.Event()
    win.on_preview()
    assert wait_until(lambda: engine.dry == 1)
    before = win.key()
    main.services.settings.set({"junban_replan_preview": True})
    assert win.key() != before
    engine.gate.set()
    assert wait_until(lambda: not win._working)
    settled(win)
    assert win.session.stats is None and win.model.rowCount() == 0
    assert not win.btn_reorder.isEnabled()
    win.on_reorder()
    assert engine.runs == []


def test_d1b_a_language_switch_throws_the_preview_away(main, engine):
    win = previewed(opened(main))
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh")
    assert win.session.stats is None and win.model.rowCount() == 0 and not win.btn_reorder.isEnabled()
    win.toggle_row(0)
    settled(win)
    win.on_reorder()
    assert not win.btn_reorder.isEnabled() and engine.runs == []


def test_d1c_after_a_reorder_the_table_is_inert_and_reorder_stays_off(main, engine):
    win = previewed(opened(main))
    win.on_reorder()
    assert wait_until(lambda: engine.runs and not win.busy())
    assert any("Moved 6 cards." == t for t in win.messages.texts())
    assert win.model.rowCount() > 0                        # what was written stays on screen…
    win.toggle_row(0)                                      # …but a click on it re-stamps nothing
    settled(win)
    assert not win.btn_reorder.isEnabled()
    win.on_reorder()
    assert len(engine.runs) == 1


def test_d1c_after_a_restore_reorder_stays_off(main, engine, monkeypatch):
    monkeypatch.setattr(undo, "unfinished", lambda language, kind: None)
    monkeypatch.setattr(undo, "restorable", lambda language, scope: {"written_at": "2026-10-14T10:00:00",
                                                                     "cards": {"1701": 2830}, "scope": ["TheBank"]})
    win = previewed(opened(main))
    win.on_restore()
    assert wait_until(lambda: card(win) is not None)
    card(win).yes.click()
    assert wait_until(lambda: engine.restores and not win.busy())
    win.toggle_row(1)
    settled(win)
    assert not win.btn_reorder.isEnabled() and win.session.stats is None


def test_d1d_after_a_put_back_reorder_stays_off(main, engine, monkeypatch):
    plan_ = {"ok": True, "taken_at": "2026-10-13T21:04:00", "cards_back": 11}
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: dict(plan_))
    monkeypatch.setattr(first_touch, "put_back", lambda settings, **k: {"ok": True, "message": "Anki is put back."})
    win = previewed(opened(main))
    win.on_put_back()
    assert wait_until(lambda: card(win) is not None)
    card(win).yes.click()
    assert wait_until(lambda: not win.is_busy() and "Anki is put back." in win.messages.texts())
    win.toggle_row(0)
    settled(win)
    assert not win.btn_reorder.isEnabled() and win.session.stats is None


def test_put_back_is_refused_while_the_windows_reorder_runs(main, engine, monkeypatch):
    # Haiku H13: with only Generate's state checked, Put back planned (and asked to write) under a running Reorder.
    planned = []
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: planned.append(language) or {"ok": True})
    win = previewed(opened(main))
    engine.run_gate = threading.Event()
    win.on_reorder()
    assert wait_until(lambda: win.busy())
    win.on_put_back()
    QTest.qWait(200)
    assert planned == [] and card(win) is None and getattr(win, "flow", None) is None
    engine.run_gate.set()
    assert wait_until(lambda: not win.busy())


def test_any_change_throws_away_the_preview_its_clicks_and_ticks(main, engine):
    win = previewed(opened(main))
    win.toggle_row(0)
    settled(win)
    assert win.session.deselected
    win.rb_leverage.click()
    assert win.session.stats is None and not win.session.deselected and win.session.ticked is None
    assert win.match.text() == qs.JUNBAN_MATCH_REFRESH and not win.btn_reorder.isEnabled()


def test_a_click_re_plans_and_reaches_the_run_as_excluded_cards(main, engine):
    win = previewed(opened(main))
    victim = win.model.card_ids[0]
    win.toggle_row(0)
    assert win.model.rows[0][0] == view.DESELECTED_GLYPH   # its own row at once
    settled(win)
    assert win.btn_reorder.isEnabled()                     # still the preview it was, re-planned by the planner
    assert any("you took off your list" in t or "left alone" in t for t in win.messages.texts())
    win.on_reorder()
    assert wait_until(lambda: engine.runs)
    settings, kwargs = engine.runs[0]
    assert settings["junban_exclude_cards"] == [victim] and kwargs["wait"] is None
    assert kwargs["cancel"] is not None and isinstance(kwargs["job"], view.spaced.Job)


def test_a_click_while_the_reorder_runs_changes_nothing(main, engine):
    # The run already carries its list: a click during it must neither mark a row ✗ (it would not be left alone)
    # nor re-plan the table under the write.
    win = previewed(opened(main))
    engine.run_gate = threading.Event()
    win.on_reorder()
    assert wait_until(lambda: win.is_busy())
    before = list(win.model.rows[0])
    replans = win.session.replanning
    win.toggle_row(0)
    assert win.session.deselected == set() and list(win.model.rows[0]) == before
    assert win.session.replanning == replans
    engine.run_gate.set()
    assert wait_until(lambda: engine.runs and not win.busy())
    assert not engine.runs[0][0].get("junban_exclude_cards")


def test_space_on_the_table_does_what_a_click_does(main, engine):
    win = previewed(opened(main))
    win.table.setFocus()
    win.table.setCurrentIndex(win.model.index(2, 0))
    QTest.keyClick(win.table, Qt.Key.Key_Space)
    assert win.model.card_ids[2] in win.session.deselected


# --- the answers, the job, one writer ---------------------------------------------------------------------------- #
def test_unsaved_answers_stop_the_reorder_before_any_write(main, engine, monkeypatch):
    stats = real_stats()
    stats["suggestions"] = [{"word": "おばあさん", "key": "お婆さん", "rank": 10, "answer": None, "via": None}]
    engine.stats = stats
    monkeypatch.setattr(pairs, "record", mock.Mock(side_effect=OSError("disk full")))
    win = previewed(opened(main))
    win.on_reorder()
    assert wait_until(lambda: not win.busy())
    assert engine.runs == []
    assert any("Could not save your answers, so nothing was reordered" in t for t in win.messages.texts())


def test_a_reorder_is_a_junban_job_and_waits_for_the_automatic_one(main, engine):
    win = previewed(opened(main))
    registry = main.services.registry
    release = threading.Event()
    registry.submit("junban", "順 (automatic)", automatic=True, on_quit="wait",
                    start=lambda job: threading.Thread(target=lambda: (release.wait(10), job.finish()),
                                                       daemon=True).start())
    win.on_reorder()
    assert wait_until(lambda: any(j.kind == "junban" and j.label == qs.JUNBAN_LABEL_REORDER and j.state == "waiting"
                                  for j in registry.snapshot()))
    time.sleep(0.1)
    assert engine.runs == [] and not win.btn_reorder.isEnabled() and not win.btn_restore.isEnabled()
    release.set()
    assert wait_until(lambda: engine.runs and not win.busy())


def test_closing_while_the_reorder_waits_writes_nothing(main, engine):
    win = previewed(opened(main))
    registry = main.services.registry
    release = threading.Event()
    registry.submit("backfill", "Backfill", start=lambda job: threading.Thread(
        target=lambda: (release.wait(10), job.finish()), daemon=True).start())
    win.on_reorder()
    assert wait_until(lambda: any(j.label == qs.JUNBAN_LABEL_REORDER and j.state == "waiting"
                                  for j in registry.snapshot()))
    win.close()
    release.set()
    time.sleep(0.3)
    assert engine.runs == []
    mine = [j for j in registry.snapshot() if j.label == qs.JUNBAN_LABEL_REORDER]
    assert mine and mine[-1].cancelled


def test_closing_mid_run_sets_the_stop_its_wait_reads(main, engine):
    win = previewed(opened(main))
    engine.run_gate = threading.Event()
    win.on_reorder()
    assert wait_until(lambda: win._stops)
    stop = next(iter(win._stops))
    win.close()
    assert stop.is_set()
    engine.run_gate.set()


def test_stopping_the_job_from_the_bar_sets_the_stop_its_wait_reads(main, engine):
    # The bar's Stop it reaches the job, not the window: its cancel must set the same stop the engine's wait for
    # another Anki writer reads, or the stop would be shown and ignored.
    win = previewed(opened(main))
    engine.run_gate = threading.Event()
    win.on_reorder()
    assert wait_until(lambda: win._stops)
    stop = next(iter(win._stops))
    job = [j for j in main.services.registry.snapshot() if j.label == qs.JUNBAN_LABEL_REORDER][-1]
    assert job.on_quit == "wait"                          # quitting now waits for the write, never cuts it off
    assert main.services.registry.cancel(job.id)
    assert stop.is_set()
    engine.run_gate.set()
    assert wait_until(lambda: not win.busy())


def test_stopping_a_waiting_reorder_from_the_bar_frees_the_window(main, engine):
    # Stopped before it started, the job never runs its body: the window must still hear an end (nothing written),
    # or it would stay busy with Preview, Reorder and Restore off for good.
    win = previewed(opened(main))
    registry = main.services.registry
    release = threading.Event()
    registry.submit("backfill", "Backfill", start=lambda job: threading.Thread(
        target=lambda: (release.wait(10), job.finish()), daemon=True).start())
    win.on_reorder()
    assert wait_until(lambda: any(j.label == qs.JUNBAN_LABEL_REORDER and j.state == "waiting"
                                  for j in registry.snapshot()))
    job = [j for j in registry.snapshot() if j.label == qs.JUNBAN_LABEL_REORDER][-1]
    assert registry.cancel(job.id)
    assert wait_until(lambda: not win.is_busy())
    assert any(qs.JUNBAN_CANCELLED in t for t in win.messages.texts())
    release.set()
    time.sleep(0.3)
    assert engine.runs == []


def test_the_first_run_of_a_session_says_it_syncs_with_ankiweb_first(main, engine, monkeypatch):
    # IK-11 (Haya): S1's ~2 s sync before the first write — said in the window and the bar, never a freeze.
    from modules.junban import spaced
    monkeypatch.setattr(view, "session_sync_likely", lambda now=None: True)
    win = previewed(opened(main))
    said = []
    real_say = win.say
    monkeypatch.setattr(win, "say", lambda text: (said.append(text), real_say(text)))
    engine.run_gate = threading.Event()
    win.on_reorder()
    assert wait_until(lambda: win.status.text() == qs.JUNBAN_SYNC_FIRST)
    job = [j for j in main.services.registry.snapshot() if j.label == qs.JUNBAN_LABEL_REORDER][-1]
    assert job.progress.step == qs.JUNBAN_SYNC_FIRST
    engine.run_gate.set()
    assert wait_until(lambda: not win.busy())
    # The first position landed: the words went back to Reordering (the sync is over), and the run carried the
    # window's spaced job, ungated (S1 is the engine's, inside the Anki-write lock).
    assert qs.JUNBAN_REORDERING in said[said.index(qs.JUNBAN_SYNC_FIRST) + 1:]
    assert isinstance(engine.runs[-1][1]["job"], spaced.Job)


def test_an_end_to_end_reorder_snapshots_before_its_first_write(main, monkeypatch, tmp_path):
    # Against the engine's FakeCollection (real words): the saved snapshot exists before the first position lands.
    from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, URL, FakeCollection, _collection, _patched,
                                                      _results)
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "散歩", "図書館", "冒険"])
    seen = []
    fake = FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend",
                                                 "updateNoteFields"),
                          on_write=lambda *a: seen.append(undo.load("ja") is not None))
    monkeypatch.setattr(first_touch, "has_anything", lambda language: False, raising=False)
    main.services.settings.set({"junban_url": URL, "junban_order": "content"})
    with _patched(fake):
        win = previewed(opened(main))
        win.on_reorder()
        assert wait_until(lambda: not win.busy(), timeout=20)
    assert fake.writes and seen and all(seen), win.messages.texts()


# --- Restore and Put back ----------------------------------------------------------------------------------------- #
def test_restore_names_what_it_restores_enter_is_no_and_no_writes_nothing(main, engine, monkeypatch):
    monkeypatch.setattr(undo, "unfinished", lambda language, kind: None)
    monkeypatch.setattr(undo, "restorable", lambda language, scope: {"written_at": "2026-10-14T10:00:00",
                                                                     "cards": {"1701": 2830}, "scope": ["TheBank"]})
    win = opened(main)
    win.on_restore()
    assert wait_until(lambda: card(win) is not None)
    c = card(win)
    assert c.title.text() == qs.JUNBAN_RESTORE_Q and "1 card saved from TheBank on 2026-10-14T10:00:00" in c.body.text()
    assert c.default is c.no                              # Enter = No (🧭 IK-10c)
    QTest.keyClick(c, Qt.Key.Key_Return)
    time.sleep(0.2)
    assert engine.restores == []
    win.on_restore()
    assert wait_until(lambda: card(win) is not None)
    card(win).yes.click()
    assert wait_until(lambda: engine.restores and not win.busy())
    assert engine.restores[0][1]["confirmed"] == "2026-10-14T10:00:00" and engine.restores[0][1]["run"] is None


def test_the_undo_of_a_reorder_that_finished_a_cut_automatic_one_says_it_puts_back_both(main, engine, monkeypatch):
    """Disc-T1 (Sonic 2026-11-12): a Reorder you started took over an automatic one cut short; its Undo puts back both,
    and its own question says so (PROVISIONAL words)."""
    monkeypatch.setattr(undo, "unfinished", lambda language, kind: None)
    monkeypatch.setattr(undo, "restorable", lambda language, scope: {"written_at": "2026-11-12T10:00:00",
                                                                     "cards": {"1701": 2830}, "scope": ["TheBank"],
                                                                     "finished_automatic": True})
    win = opened(main)
    win.on_restore()
    assert wait_until(lambda: card(win) is not None)
    assert card(win).title.text() == qs.JUNBAN_RESTORE_BOTH_Q and "the automatic one" in qs.JUNBAN_RESTORE_BOTH_Q
    card(win).yes.click()
    assert wait_until(lambda: engine.restores and not win.busy())
    assert engine.restores[0][1]["confirmed"] == "2026-11-12T10:00:00"


def test_restore_offers_the_unfinished_automatic_run_first(main, engine, monkeypatch):
    monkeypatch.setattr(undo, "unfinished", lambda language, kind: "run-7")
    monkeypatch.setattr(undo, "describe_run", lambda language, run: "run-7: 12 cards in TheBank")
    win = opened(main)
    win.on_restore()
    assert wait_until(lambda: card(win) is not None)
    assert card(win).title.text() == qs.JUNBAN_RESTORE_RUN_Q
    card(win).yes.click()
    assert wait_until(lambda: engine.restores and not win.busy())
    assert engine.restores[0][1]["run"] == "run-7" and engine.restores[0][1]["confirmed"] is None


def test_restore_with_nothing_saved_says_so(main, engine, monkeypatch):
    monkeypatch.setattr(undo, "unfinished", lambda language, kind: None)
    monkeypatch.setattr(undo, "restorable", lambda language, scope: None)
    win = opened(main)
    win.on_restore()
    assert wait_until(lambda: undo.describe(None) in win.messages.texts())
    assert card(win) is None and engine.restores == []


def test_put_back_asks_with_its_counts_one_way_line_and_the_older_question_defaulting_to_no(main, engine,
                                                                                            monkeypatch):
    plan_ = {"ok": True, "taken_at": "2026-10-13T21:04:00", "cards_back": 11, "fields_unedited": 2,
             "older_suspended": 3, "profile": "User 1"}
    wrote = []
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: dict(plan_))
    monkeypatch.setattr(first_touch, "put_back", lambda settings, **k: wrote.append(k) or {"ok": True,
                                                                                           "message": "Put back."})
    win = opened(main)
    assert wait_until(lambda: win.btn_put_back.isEnabled())
    win.on_put_back()
    assert wait_until(lambda: card(win) is not None)
    main_card = card(win)
    assert put_back_view.ONE_WAY in main_card.body.text() and "11 new cards back" in main_card.body.text()
    assert main_card.default is main_card.no and wrote == []          # the plan read only
    main_card.yes.click()
    assert wait_until(lambda: card(win) is not None and card(win) is not main_card)
    fields_card = card(win)
    assert fields_card.default is fields_card.no
    fields_card.yes.click()
    assert wait_until(lambda: card(win) is not None and card(win) is not fields_card)
    older_card = card(win)
    assert older_card.default is older_card.no
    QTest.keyClick(older_card, Qt.Key.Key_Return)                      # Enter keeps the older changes
    assert wait_until(lambda: wrote and not win.is_busy())
    assert wrote[0]["fields"] is True and wrote[0]["older"] is False and wrote[0]["profile"] == "User 1"
    jobs = [j for j in main.services.registry.snapshot() if j.label == qs.JUNBAN_LABEL_PUT_BACK]
    assert jobs and jobs[-1].kind == "junban"


def test_with_no_older_changes_the_write_never_names_them(main, engine, monkeypatch):
    # Haiku H19: the older question not asked (nothing older to give back) must leave `older` out of the write.
    wrote = []
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: {"ok": True, "cards_back": 3,
                                                                         "profile": "User 1"})
    monkeypatch.setattr(first_touch, "put_back", lambda settings, **k: wrote.append(k) or {"ok": True,
                                                                                           "message": "Put back."})
    win = opened(main)
    assert wait_until(lambda: win.btn_put_back.isEnabled())
    win.on_put_back()
    assert wait_until(lambda: card(win) is not None)
    first = card(win)
    first.yes.click()
    assert wait_until(lambda: wrote and not win.is_busy())
    assert "older" not in wrote[0] and card(win) is None


def test_put_back_answered_no_writes_nothing(main, engine, monkeypatch):
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: {"ok": True, "cards_back": 3})
    put = mock.Mock()
    monkeypatch.setattr(first_touch, "put_back", put)
    win = opened(main)
    assert wait_until(lambda: win.btn_put_back.isEnabled())
    win.on_put_back()
    assert wait_until(lambda: card(win) is not None)
    QTest.keyClick(card(win), Qt.Key.Key_Escape)
    assert wait_until(lambda: qs.PUT_BACK_NOTHING in win.messages.texts())
    assert put.call_count == 0 and not win.is_busy()


def test_settings_put_back_door_is_refused_while_junban_is_busy(main, engine):
    win = previewed(opened(main))
    engine.run_gate = threading.Event()
    win.on_reorder()
    assert wait_until(lambda: win.busy())
    assert qt_put_back.open(main) is None and main.bar_line.full() == qs.JUNBAN_PUT_BACK_REFUSED
    engine.run_gate.set()
    assert wait_until(lambda: not win.busy())


def _settings_put_back(monkeypatch, wrote, gate=None):
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: {"ok": True, "cards_back": 11,
                                                                         "profile": "User 1"})

    def put_back(settings, **k):
        if gate is not None:
            gate.wait(10)
        wrote.append(k)
        return {"ok": True, "message": "Anki is put back."}
    monkeypatch.setattr(first_touch, "put_back", put_back)


def test_a_put_back_through_settings_door_throws_junbans_preview_away(main, engine, monkeypatch):
    # AD6-1 / IK-80 (D1d through the other door): Settings' put-back left 順's preview live, and Reorder then ran
    # under a sentence about the collection as it was before.
    wrote = []
    _settings_put_back(monkeypatch, wrote)
    win = previewed(opened(main))
    door = qt_put_back.open(main)
    assert wait_until(lambda: card(door) is not None)
    card(door).yes.click()
    assert wait_until(lambda: wrote and not door.working)
    assert wait_until(lambda: win.session.stats is None)
    assert not win.btn_reorder.isEnabled()
    win.on_reorder()
    assert engine.runs == []


def test_a_put_back_through_settings_door_closed_mid_write_still_throws_the_preview_away(main, engine, monkeypatch):
    # The Settings window closed while its write runs: the write finishes, and 順 still hears that Anki moved.
    wrote, gate = [], threading.Event()
    _settings_put_back(monkeypatch, wrote, gate)
    win = previewed(opened(main))
    door = qt_put_back.open(main)
    assert wait_until(lambda: card(door) is not None)
    card(door).yes.click()
    assert wait_until(lambda: any(j.label == qs.JUNBAN_LABEL_PUT_BACK and j.state == "running"
                                  for j in main.services.registry.snapshot()))
    door.close()
    gate.set()
    assert wait_until(lambda: wrote)
    assert wait_until(lambda: win.session.stats is None and not win.btn_reorder.isEnabled())


def test_while_settings_put_back_asks_or_writes_junban_writes_nothing(main, engine, monkeypatch):
    # AD6-1's second path: 順 was not busy while the other door's flow asked, so Reorder queued behind the put-back
    # and ran from the old preview right after it.
    wrote, gate = [], threading.Event()
    _settings_put_back(monkeypatch, wrote, gate)
    win = previewed(opened(main))
    door = qt_put_back.open(main)
    assert wait_until(lambda: card(door) is not None)
    assert wait_until(lambda: not win.btn_reorder.isEnabled())
    win.on_reorder()
    win.on_restore()
    win.on_put_back()
    assert card(win) is None and getattr(win, "flow", None) is None
    card(door).yes.click()
    gate.set()
    assert wait_until(lambda: wrote and not door.working)
    assert engine.runs == [] and engine.restores == []


def test_settings_put_back_door_is_refused_while_junban_generates(main, engine):
    # AD6-14: the Tk door refused while 順 was generating too.
    win = opened(main)
    win.session.generating = True
    assert qt_put_back.open(main) is None and main.bar_line.full() == qs.JUNBAN_PUT_BACK_REFUSED
    win.session.generating = False


def test_pressing_settings_door_again_after_its_flow_ended_starts_it_again(main, engine, monkeypatch):
    # AD6-8: the Tk door made a new window and flow on every press; the Qt one only raised the old window.
    plans = []
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: plans.append(language) or {
        "ok": False, "problems": ["Open Anki first."]})
    door = qt_put_back.open(main)
    assert wait_until(lambda: plans and not door.working)
    again = qt_put_back.open(main)
    assert again is door
    assert wait_until(lambda: len(plans) == 2 and not door.working)
    assert door.lines.texts().count("Open Anki first.") <= 1          # the old lines went with the old flow


def test_pressing_settings_door_while_its_flow_asks_raises_it_with_junban_open(main, engine, monkeypatch):
    # Its own flow is not 順's work: pressed again while it asks, the door raises it — never "順 is working".
    wrote = []
    _settings_put_back(monkeypatch, wrote)
    opened(main)
    door = qt_put_back.open(main)
    assert wait_until(lambda: card(door) is not None)
    first = card(door)
    assert qt_put_back.open(main) is door
    QTest.qWait(50)
    assert card(door) is first and main.bar_line.full() != qs.JUNBAN_PUT_BACK_REFUSED
    QTest.keyClick(first, Qt.Key.Key_Escape)
    assert wait_until(lambda: not door.working) and wrote == []


# --- Generate & preview (§16.9) ------------------------------------------------------------------------------------ #
class FakeController:
    def __init__(self):
        self.requests, self.listeners = [], []

    def on_end(self, callback):
        self.listeners.append(callback)

    def unsubscribe(self, callback):
        self.listeners = [c for c in self.listeners if c != callback]

    def request(self, language, argv=None, label=None, **_):
        self.requests.append((language, argv, label))
        return SimpleNamespace(language=language)

    def end(self, outcome):
        for callback in list(self.listeners):
            callback(None, outcome)


def test_an_out_of_date_list_generates_through_the_controller_then_previews_again(main, engine, monkeypatch):
    controller = FakeController()
    main.services.controller = controller
    answers = [False]
    monkeypatch.setattr(view, "list_current_of", lambda settings, language: answers[-1])
    win = opened(main)
    win.on_preview()
    assert wait_until(lambda: win.btn_preview.text() == qs.JUNBAN_GENERATE_PREVIEW and not win._working)
    assert not win.btn_reorder.isEnabled()
    assert win.messages.texts()[-1].startswith("Your list is out of date")
    win.on_preview()
    assert wait_until(lambda: controller.requests)
    language, argv, label = controller.requests[0]
    assert "--no-open" in argv and argv[0] == "analyzer.py" and label == qs.JUNBAN_LABEL_GENERATE
    assert win.btn_preview.text() == qs.JUNBAN_GENERATING and not win.btn_preview.isEnabled()
    answers.append(True)
    controller.end("dropped")                             # even a run that never started ends the wait (D4)
    assert wait_until(lambda: win.btn_reorder.isEnabled())
    assert engine.dry == 2 and engine.runs == []          # previewed again; never a write


def test_someone_elses_generate_leaves_a_working_preview_alone(main, engine):
    controller = FakeController()
    main.services.controller = controller
    win = previewed(opened(main))
    controller.end("current")
    QTest.qWait(50)
    assert win.btn_reorder.isEnabled() and engine.dry == 1


def test_closing_unsubscribes_from_the_controller(main, engine):
    controller = FakeController()
    main.services.controller = controller
    win = opened(main)
    assert controller.listeners
    win.close()
    assert controller.listeners == []


# --- Backfill, the doors ----------------------------------------------------------------------------------------- #
def test_the_backfill_button_opens_backfills_door_only_when_there_is_one(main, engine, monkeypatch):
    # Row 5 registers the real Backfill door: the window looks it up by name, so a stand-in replaces it
    assert any(op.name == "backfill" for op in windows.OPENERS)
    others = [op for op in windows.OPENERS if op.name != "backfill"]
    monkeypatch.setattr(windows, "OPENERS", others)                   # no Backfill door: no button
    win = opened(main)
    assert win.btn_backfill.isHidden()
    opened_ = []
    monkeypatch.setattr(windows, "OPENERS", others + [
        windows.Opener("backfill", "Backfill", "Fill fields", windows.always, lambda s: opened_.append(s))])
    win._sync()
    assert not win.btn_backfill.isHidden()
    win.btn_backfill.click()
    assert opened_ == [main]


def test_the_doors_follow_the_switch(main, monkeypatch):
    door = next(o for o in windows.OPENERS if o.name == "junban")
    put_back = next(o for o in windows.OPENERS if o.name == "put-back")
    monkeypatch.setattr(windows, "_FOUND", {"junban": False})          # the module looked for and not there: no door
    assert not windows.available(door, {"enable_junban": True}, "ja")
    assert not windows.available(put_back, {"enable_junban": True}, "ja")
    monkeypatch.setattr(windows, "_FOUND", {"junban": True})
    assert windows.available(door, {"enable_junban": True}, "ja")
    assert not windows.available(door, {"enable_junban": False}, "ja")
    assert windows.available(put_back, {"enable_junban": False}, "ja")      # the way back stays


def test_opening_the_windows_imports_no_tkinter(tmp_path):
    code = (
        "import sys\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "from app.qt import shell\n"
        "app = QApplication(['w34-junban'])\n"
        "s = shell.Services(); w = shell.open_window(app, s); w.show()\n"
        "from modules.junban import open_junban_qt, open_put_back_qt\n"
        "j = open_junban_qt(w); p = open_put_back_qt(w); app.processEvents()\n"
        "print([m for m in sys.modules if 'tkinter' in m])\n"
        "for x in app.topLevelWidgets(): x.close()\n"
        "s.shutdown(0.5)\n"
        # The app's own quit: the windows deleted (closed, they were left to Python's teardown — the exit crash's
        # cause, 0xC0000005: 07fbcea, flakes-2026-11-05 #6), the pool and the windows' own reads (junban-*) ended first.
        "shell.quiet_exit(workers_ms=5000, join_s=5, gone=(w,))\n")
    env = dict(os.environ, PYTHONPATH=_ROOT, SURASURA_TEST_ROOT=str(tmp_path), QT_QPA_PLATFORM="offscreen",
               SURASURA_NO_UI_TIMERS="1", SURASURA_INSTANCE_NAME=f"w34-junban-{os.getpid()}")
    out = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "[]"


# --- the table at 4,000 rows (IK-4) ------------------------------------------------------------------------------- #
def test_a_click_at_four_thousand_rows_is_one_rows_change_on_the_gui_thread(main, engine):
    from modules.junban.plan import plan
    cards = [{"card_id": i, "due": i, "type": 0, "queue": 0, "word": f"語{i}", "deck": "TheBank", "note": i + 9000}
             for i in range(4000)]
    rank = {f"語{i}": (i * 7919) % 4000 for i in range(0, 4000, 2)}
    _w, engine.stats = plan(cards, rank)
    engine.stats["decks"] = ["TheBank"]
    win = previewed(opened(main))
    assert win.model.rowCount() == 4000
    resets = []
    win.model.modelReset.connect(lambda: resets.append(1))
    before = win.model.updates
    start = time.perf_counter()
    win.toggle_row(1)                                     # the GUI thread's share: its row, then a worker
    spent = (time.perf_counter() - start) * 1000
    assert win.model.updates == before + 1
    settled(win)
    assert resets == []                                   # the re-plan's answer: dataChanged runs, never a rebuild
    bound = 4.0 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 50.0
    assert spent <= bound, f"a click took {spent:.2f} ms on the GUI thread"


def test_the_replan_worker_runs_the_newest_request_and_ends_on_stop(main, engine):
    # AD6-2: one long-lived thread per window; requests waiting behind a running one collapse to the newest.
    win = opened(main)
    worker = win._replanner
    gate, ran, landed = threading.Event(), [], []

    def slow():
        gate.wait(5)
        ran.append("first")
        return "first"
    worker.ask(slow, then=landed.append)
    assert wait_until(lambda: worker.queue.empty())               # the first is running
    for n in ("second", "third", "fourth"):
        worker.ask(lambda n=n: ran.append(n) or n, then=landed.append)
    gate.set()
    assert wait_until(lambda: landed == ["first", "fourth"])
    assert ran == ["first", "fourth"]
    win.close()
    worker.thread.join(5)
    assert not worker.thread.is_alive()


# --- "Same word as one on your list?" ------------------------------------------------------------------------------ #
def _stats_with_a_suggestion():
    """おばあさん, not on the list, may be the list's お婆さん: its card carries the suggestion the planner made."""
    from modules.junban.plan import plan
    cards = [{"card_id": 1700 + i, "due": 2830 + i, "type": 0, "queue": 0, "word": w, "deck": "TheBank",
              "note": 2700 + i} for i, w in enumerate(["冒険", "散歩"])]
    cards.append({"card_id": 1799, "due": 2900, "type": 0, "queue": 0, "word": "おばあさん", "deck": "TheBank",
                  "note": 2799, "tier": "rest", "sort": None, "why": "by frequency",
                  "suggestion": ("お婆さん", 0, None, "list #1 · you matched it")})
    _w, stats = plan(cards, {"冒険": 1, "散歩": 2})
    stats["decks"] = ["TheBank"]
    stats["suggestions"] = [{"word": "おばあさん", "key": "お婆さん", "rank": 0, "reading": "おばあさん",
                             "excerpt": "おばあさんが来た", "answer": None, "via": "kana"}]
    return stats


def test_a_tick_re_plans_and_reorder_records_the_answer_before_the_run(main, engine, monkeypatch):
    engine.stats = _stats_with_a_suggestion()
    order = []
    monkeypatch.setattr(pairs, "record", lambda language, answers: order.append(("answers", list(answers))))
    real_run = reposition.run
    monkeypatch.setattr(reposition, "run", lambda settings, **k: order.append("run") or real_run(settings, **k))
    win = previewed(opened(main))
    assert not win.checks_box.isHidden() and win.check_table.rowCount() == 1
    assert win.check_table.item(0, 0).text() == view.CHECK_OFF
    win._tick(0)
    settled(win)
    assert win.check_table.item(0, 0).text() == view.CHECK_ON and win.btn_reorder.isEnabled()
    win.on_reorder()
    assert wait_until(lambda: "run" in order and not win.busy())
    assert order[0] == ("answers", [("おばあさん", "お婆さん", True, "kana")]) and order[1] == "run"


# --- a write that waits says so; a question never outlives its language ------------------------------------------ #
def test_a_reorder_waiting_for_another_writer_says_what_it_waits_for(main, engine):
    win = previewed(opened(main))
    registry = main.services.registry
    release = threading.Event()
    registry.submit("backfill", "Backfill", start=lambda job: threading.Thread(
        target=lambda: (release.wait(10), job.finish()), daemon=True).start())
    win.on_reorder()
    assert wait_until(lambda: win.status.text().startswith(qs.JUNBAN_WAITS.format(reason="")))
    assert "Backfill" in win.status.text()
    release.set()
    assert wait_until(lambda: engine.runs and not win.busy())


def test_a_restore_question_open_at_a_language_switch_is_answered_no(main, engine, monkeypatch):
    monkeypatch.setattr(undo, "unfinished", lambda language, kind: None)
    monkeypatch.setattr(undo, "restorable", lambda language, scope: {"written_at": "2026-10-14T10:00:00",
                                                                     "cards": {"1701": 2830}, "scope": ["TheBank"]})
    win = opened(main)
    win.on_restore()
    assert wait_until(lambda: card(win) is not None)
    asked = card(win)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh")
    assert asked.answer is False and card(win) is None
    time.sleep(0.2)
    assert engine.restores == []


def test_a_put_back_plan_landing_after_a_language_switch_asks_nothing(main, engine, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: gate.wait(10) and {"ok": True,
                                                                                            "cards_back": 3})
    win = opened(main)
    assert wait_until(lambda: win.btn_put_back.isEnabled())
    win.on_put_back()
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh")
    gate.set()
    assert wait_until(lambda: not win.is_busy())
    assert card(win) is None and qs.PUT_BACK_NOTHING in win.messages.texts()


def _put_back_with_follow_ups(monkeypatch, wrote):
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: {
        "ok": True, "taken_at": "2026-10-13T21:04:00", "cards_back": 11, "fields_unedited": 2, "older_suspended": 3,
        "profile": "User 1"})
    monkeypatch.setattr(first_touch, "put_back", lambda settings, **k: wrote.append(k) or {"ok": True,
                                                                                           "message": "Put back."})


@pytest.mark.parametrize("at", ["fields", "older"])
def test_a_language_switch_at_a_follow_up_question_ends_the_put_back_unwritten(main, engine, monkeypatch, at):
    # AD6-4: the switch closed the follow-up question as No, and the flow went on to write the other language's
    # put-back under this window, now showing Chinese.
    wrote = []
    _put_back_with_follow_ups(monkeypatch, wrote)
    win = opened(main)
    assert wait_until(lambda: win.btn_put_back.isEnabled())
    win.on_put_back()
    assert wait_until(lambda: card(win) is not None)
    first = card(win)
    first.yes.click()
    assert wait_until(lambda: card(win) is not None and card(win) is not first)
    if at == "older":
        second = card(win)
        second.yes.click()
        assert wait_until(lambda: card(win) is not None and card(win) is not second)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh")
    assert wait_until(lambda: not win.is_busy())
    QTest.qWait(100)
    assert wrote == [] and card(win) is None and qs.PUT_BACK_NOTHING in win.messages.texts()


@pytest.mark.parametrize("at", ["main", "fields"])
def test_settings_put_back_window_follows_a_language_switch_unwritten(main, engine, monkeypatch, at):
    # AD6-4's second half: Settings' window had no language_changed — its question outlived the switch.
    wrote = []
    _put_back_with_follow_ups(monkeypatch, wrote)
    door = qt_put_back.open(main)
    assert wait_until(lambda: card(door) is not None)
    if at == "fields":
        first = card(door)
        first.yes.click()
        assert wait_until(lambda: card(door) is not None and card(door) is not first)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: door.language == "zh")
    assert wait_until(lambda: card(door) is None and not door.working)
    QTest.qWait(100)
    assert wrote == [] and qs.PUT_BACK_NOTHING in door.lines.texts()


def _job_view(registry, job):
    return next(v for v in registry.snapshot() if v.id == job.id)


@pytest.mark.parametrize("ends, state, cancelled", [
    ("failed", "failed", False),        # a write that failed after the stop was set is a failure, said with its words
    ("closed", "done", True),           # the engine's refusal before any write: that alone is "cancelled"
    ("ok", "done", False),              # every card moved although the stop came: never shown as cancelled
])
def test_a_jobs_end_says_what_happened_whatever_the_stop(main, engine, ends, state, cancelled):
    # AD6-5: any non-ok report with the stop set ended as a cancelled success, and an ok run after a cancel stayed
    # marked cancelled.
    from app import anki_connect
    registry = main.services.registry
    stop, go, told = threading.Event(), threading.Event(), []
    reports = {"failed": {"ok": False, "message": "Could not save the undo snapshot.", "problems": []},
               "closed": {"ok": False, "message": "Junban did not make any changes.", "busy": True,
                          "problems": [anki_connect.CLOSED]},
               "ok": {"ok": True, "message": "Moved 6 cards."}}

    def work(_job):
        go.wait(10)
        return dict(reports[ends])
    job = qt_put_back.run_job(registry, qs.JUNBAN_LABEL_REORDER, work, told.append, stop)
    assert wait_until(lambda: _job_view(registry, job).state == "running")
    registry.cancel(job.id)                              # the bar's Stop (it sets the stop too)
    assert stop.is_set()
    go.set()
    assert wait_until(lambda: told and _job_view(registry, job).state in ("done", "failed"))
    v = _job_view(registry, job)
    assert (v.state, bool(v.cancelled)) == (state, cancelled)
    if ends == "failed":
        assert v.message == "Could not save the undo snapshot."


def test_a_refused_reorder_says_why_on_its_job_not_only_that_nothing_changed(main, engine):
    # Mattias (alpha 3): an unfinished automatic reorder refused every Reorder, and the 順 circle's hover said only
    # "failed 19:30: Junban did not make any changes." — the job's words are now the engine's first problem: why, and
    # what to press. With no problem, its message as before.
    registry = main.services.registry
    why = ("An automatic reorder (reorder-20261029-174900-086-18584) did not finish, and its saved order is the only "
           "way back from it. Press Undo the last reorder first, then reorder again.")
    for report, words in (({"ok": False, "message": "Junban did not make any changes.", "problems": [why],
                            "restore_first": True}, why),
                          ({"ok": False, "message": "Junban did not make any changes.", "problems": []},
                           "Junban did not make any changes.")):
        told = []
        job = qt_put_back.run_job(registry, qs.JUNBAN_LABEL_REORDER, lambda _job, r=report: dict(r), told.append,
                                  threading.Event())
        assert wait_until(lambda: told and _job_view(registry, job).state == "failed")
        assert _job_view(registry, job).message == words
        # refused until the Undo: it ends waiting on you, so the 順 circle's press opens that Undo (phase.FAILED_GO)
        assert _job_view(registry, job).needs == (why if report.get("restore_first") else None)
        assert told[0]["problems"] == report["problems"], "the window's own lines still get the whole report"


@pytest.mark.parametrize("paired, previews", [("ja", False), ("zh", True)])
def test_a_language_switch_previews_by_itself_only_the_new_languages_own_deck(main, engine, monkeypatch, paired,
                                                                                previews):
    # AD6-7: with timers on, as in the app, the switch re-probed and previewed the other language's deck by itself.
    main.services.settings.set({"junban_deck": "TheBank", "junban_replan_language": paired,
                                "junban_replan_deck": "TheBank"})
    monkeypatch.setattr(view, "probe_work", lambda settings: ({"ok": True, "version": 6}, ["TheBank"], None))
    win = settled(previewed(opened(main)))
    win._probed = True
    before = engine.dry
    monkeypatch.delenv("SURASURA_NO_UI_TIMERS")
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh")
    QTest.qWait(300)
    settled(win)
    assert (engine.dry > before) is previews
    if not previews:
        assert win.session.stats is None and not win.btn_reorder.isEnabled()


def test_the_lines_never_share_the_tables_space(main, engine):
    # IK-83: "Reorder will move …" was painted over the table's rows (every clause must stay visible before Reorder):
    # a top-level window's minimum ignores word-wrapped lines' height, so at its smallest the two overlapped.
    from PyQt6.QtCore import QPoint, QRect
    win = previewed(opened(main))
    win._toggle_touch()
    for n in range(3):
        win.messages.add(f"Not on your list: suspend {n + 40} cards in Japanese::Mining, tag them Surasura::later and "
                         "flag them purple; the overwrite of the FreqSort sort number comes with them.", "warning")
    for width in (900, 640):
        win.resize(width, 1)                                   # as small as it lets itself be
        QTest.qWait(50)

        def box(w):
            return QRect(w.mapTo(win, QPoint(0, 0)), w.size())
        table, lines = box(win.table), box(win.messages)
        assert not table.intersects(lines), (width, table, lines)
        assert lines.height() >= win.messages.layout().heightForWidth(lines.width()) - 1


def test_a_replan_that_fails_throws_the_preview_away_and_says_so(main, engine, monkeypatch):
    # AD6-11: a re-plan that raised left a click "still being re-planned" for good — Reorder off with only an
    # unexpected-error line. The sentence on screen is not the run's: the preview goes, and the line says what to do.
    win = settled(previewed(opened(main)))
    monkeypatch.setattr(view, "preview_view", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("planner broke")))
    win.toggle_row(0)
    assert wait_until(lambda: win.session.stats is None)
    assert win.session.replanning == win.session.replanned and not win.btn_reorder.isEnabled()
    assert any(qs.JUNBAN_REPLAN_FAILED.format(why="planner broke") == t for t in win.messages.texts())
    assert win.btn_preview.isEnabled()


def test_a_window_whose_opening_fails_holds_no_lock(main, engine, monkeypatch):
    # AD6-12: the lock's hold started before the controller hook and the first-touch ask; either raising left the
    # unshown window (parented to the main window) holding `junban-window` for the program's life.
    from modules.junban import auto
    monkeypatch.setattr(qt_junban.JunbanWindow, "_ask_first_touch",
                        lambda self: (_ for _ in ()).throw(RuntimeError("first touch broke")))
    with pytest.raises(RuntimeError):
        qt_junban.JunbanWindow(main)
    QTest.qWait(300)
    assert not auto.window_open()


def test_the_reorder_button_names_the_count_its_sentence_moves(main, engine):
    # IK-88 (RUNBOOK IK-10a: "its button names the count"): the button read "Reorder" whatever the preview said.
    win = settled(previewed(opened(main)))
    n = win.session.view.to_write
    assert n > 0 and win.btn_reorder.text() == qs.JUNBAN_REORDER_N.format(n=n, s="" if n == 1 else "s")
    assert f"Reorder will move {n} of" in " ".join(win.messages.texts())
    win.toggle_row(0)                                       # one card left alone: fewer move (one, or more when
    settled(win)                                            # another then lands where it already sits)
    m = win.session.view.to_write
    assert 0 < m < n and win.btn_reorder.text() == qs.JUNBAN_REORDER_N.format(n=m, s="" if m == 1 else "s")
    win.rb_leverage.click()                                 # the preview thrown away: no count to name
    assert win.btn_reorder.text() == qs.JUNBAN_REORDER


def test_a_language_switch_shows_the_deck_recorded_for_the_new_language_unsaved(main, engine):
    # IK-86 (D31: one deck key for both languages): after a switch the window kept the Japanese deck; with a deck the
    # user picked in the Chinese window recorded, it is the one shown — shown, never saved by the switch (S16).
    main.services.settings.set({"junban_deck": "TheBank", "junban_replan_language": "zh",
                                "junban_replan_deck": "中文::Mining"})
    main.services.settings.flush(5)
    win = settled(previewed(opened(main)))
    written = []
    real_set = main.services.settings.set
    main.services.settings.set = lambda changes, **k: written.append(dict(changes)) or real_set(changes, **k)
    try:
        real_set({"target_language": "zh"})
        assert wait_until(lambda: win.language == "zh")
        assert win.controls["deck"] == "中文::Mining" and win.deck_box.currentText() == "中文::Mining"
        assert written == []
        real_set({"target_language": "ja"})              # back: no deck recorded for Japanese — the shown one stays
        assert wait_until(lambda: win.language == "ja")
        assert win.controls["deck"] == "中文::Mining" and written == []
    finally:
        del main.services.settings.set


def test_a_reorder_finishing_after_its_window_closed_says_its_result_in_the_bar(main, engine):
    # IK-90: closing mid-write lets the write finish, but its result reached no one (the window's relay was dropped).
    win = previewed(opened(main))
    engine.run_gate = threading.Event()
    win.on_reorder()
    assert wait_until(lambda: win.busy())
    win.close()
    engine.run_gate.set()
    assert wait_until(lambda: main.bar_line.full() == "Moved 6 cards.")


def test_a_put_back_finishing_after_its_window_closed_says_its_result_in_the_bar(main, engine, monkeypatch):
    wrote, gate = [], threading.Event()
    _settings_put_back(monkeypatch, wrote, gate)
    door = qt_put_back.open(main)
    assert wait_until(lambda: card(door) is not None)
    card(door).yes.click()
    assert wait_until(lambda: any(j.label == qs.JUNBAN_LABEL_PUT_BACK and j.state == "running"
                                  for j in main.services.registry.snapshot()))
    door.close()
    gate.set()
    assert wait_until(lambda: main.bar_line.full() == "Anki is put back.")


@pytest.mark.parametrize("auto_actions", [True, False])
def test_the_touch_ups_say_the_automatic_reorder_applies_them_too_while_it_does(main, engine, auto_actions):
    # IK-91 (HY-6 / P3.3-1, S16): with `junban_auto_actions` on, these boxes also drive every automatic re-order.
    main.services.settings.set({"junban_auto_actions": auto_actions})
    win = opened(main)
    assert (qs.JUNBAN_TOUCH_AUTO_TIP in win.btn_touch.toolTip()) is auto_actions
    assert win.btn_touch.toolTip().startswith(qs.JUNBAN_TOUCH_TIP)


def test_a_window_that_cannot_take_its_lock_says_so(main, engine):
    # AD6-13: another 順 window (another Surasura) holding `junban-window` left this one without it, silently — the
    # automatic re-order no longer stood aside for it.
    from app import locks
    with locks.take("junban-window", "another 順 window", owner=object()):
        win = opened(main)
        assert wait_until(lambda: qs.JUNBAN_LOCK_NOT_HELD in win.messages.texts(), timeout=8)
        assert not win.lock.holding()
    win.close()


def test_the_overwrite_box_is_coloured_as_a_danger(main, engine):
    # AD6-16: `cb_freqsort`'s danger tone had no stylesheet rule, so the overwrite was not visibly dangerous.
    from PyQt6.QtWidgets import QApplication
    win = opened(main)
    assert win.cb_freqsort.property("tone") == "danger"
    assert 'QCheckBox[tone="danger"]' in QApplication.instance().styleSheet()


def test_settings_door_plans_after_the_pending_settings_are_written(main, engine, monkeypatch):
    # IK-87: the door planned from the file while changes were still pending in the settings service.
    order = []
    real_flush = main.services.settings.flush
    monkeypatch.setattr(main.services.settings, "flush", lambda timeout=None: order.append("flush") or
                        real_flush(timeout))
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: order.append("plan") or {
        "ok": False, "problems": ["Open Anki first."]})
    door = qt_put_back.open(main)
    assert wait_until(lambda: "plan" in order and not door.working)
    assert order.index("flush") < order.index("plan")


@pytest.mark.parametrize("changed, reloads", [(["junban_auto_backfill"], True), ([], False)])
def test_a_put_back_that_changed_settings_reloads_the_service(main, engine, monkeypatch, changed, reloads):
    # IK-87: the engine saves its stand-aside with save_keys beside the service; the service's copy (and anything
    # painted from it) stayed stale until its next write.
    reloaded = []
    monkeypatch.setattr(main.services.settings, "reload", lambda: reloaded.append(1))
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: {"ok": True, "cards_back": 3})
    monkeypatch.setattr(first_touch, "put_back", lambda settings, **k: {"ok": True, "message": "Put back.",
                                                                        "settings_changed": list(changed)})
    win = opened(main)
    assert wait_until(lambda: win.btn_put_back.isEnabled())
    win.on_put_back()
    assert wait_until(lambda: card(win) is not None)
    card(win).yes.click()
    assert wait_until(lambda: "Put back." in win.messages.texts())
    QTest.qWait(200)
    assert bool(reloaded) is reloads


def test_a_tick_repaints_only_its_own_row_of_the_same_word_table(main, engine):
    # IK-89 (S19): the "Same word?" table was made again item by item on every tick.
    from modules.junban.plan import plan
    stats = _stats_with_a_suggestion()
    cards = [{"card_id": 1700 + i, "due": 2830 + i, "type": 0, "queue": 0, "word": w, "deck": "TheBank",
              "note": 2700 + i} for i, w in enumerate(["冒険", "散歩"])]
    for n, (word, key) in enumerate((("おばあさん", "お婆さん"), ("おじいさん", "お爺さん"))):
        cards.append({"card_id": 1798 + n, "due": 2900 + n, "type": 0, "queue": 0, "word": word, "deck": "TheBank",
                      "note": 2798 + n, "tier": "rest", "sort": None, "why": "by frequency",
                      "suggestion": (key, n, None, "list #1 · you matched it")})
    _w, stats = plan(cards, {"冒険": 1, "散歩": 2})
    stats["decks"] = ["TheBank"]
    stats["suggestions"] = [{"word": w, "key": k, "rank": n, "reading": w, "excerpt": f"{w}が来た", "answer": None,
                             "via": "kana"} for n, (w, k) in enumerate((("おばあさん", "お婆さん"),
                                                                       ("おじいさん", "お爺さん")))]
    engine.stats = stats
    win = settled(previewed(opened(main)))
    assert win.check_table.rowCount() == 2
    items = [win.check_table.item(r, 1) for r in range(2)]
    win._tick(0)
    settled(win)
    assert win.check_table.item(1, 1) is items[1]                # the other row untouched
    assert win.check_table.item(0, 1) is not items[0]            # the ticked row repainted


def test_settings_window_never_starts_a_second_flow_while_one_asks(main, engine, monkeypatch):
    # Mutant F6: `start` is the one place a flow begins; while one asks or writes, a second never starts (two
    # put-backs of one plan would each ask and each write).
    plans = []
    monkeypatch.setattr(first_touch, "has_anything", lambda language: True)
    monkeypatch.setattr(first_touch, "plan", lambda settings, language: plans.append(1) or {"ok": True,
                                                                                            "cards_back": 3})
    door = qt_put_back.open(main)
    assert wait_until(lambda: card(door) is not None)
    first = door.flow
    door.start()
    QTest.qWait(100)
    assert door.flow is first and len(plans) == 1
    QTest.keyClick(card(door), Qt.Key.Key_Escape)
    assert wait_until(lambda: not door.working)


def test_a_yes_landing_after_the_language_moved_writes_nothing(main, engine, monkeypatch):
    # Mutant F9: the main question's own check — a yes that reaches the flow after the window's language moved (the
    # card closes at the switch; this is the flow's own guard behind it) ends it unwritten.
    wrote = []
    _put_back_with_follow_ups(monkeypatch, wrote)
    door = qt_put_back.open(main)
    assert wait_until(lambda: card(door) is not None)
    flow, plan = door.flow, {"ok": True, "cards_back": 11, "profile": "User 1"}
    door.language = "zh"                                   # moved, as `_switch` sets it
    flow._main(True, plan, {"fields": None, "older": None})
    QTest.qWait(100)
    assert wrote == [] and qs.PUT_BACK_NOTHING in door.lines.texts()
    door.language = "ja"
    QTest.keyClick(card(door), Qt.Key.Key_Escape)


# --- round 8 row 45: every press reacts at once ------------------------------------------------------------------- #
def test_restore_paints_its_arc_before_its_question_is_read_and_is_never_greyed(main, engine, monkeypatch):
    # *Restore…* greyed itself with no words while its question was read (a worker): its arc now turns, painted
    # before the read is handed over, until the question opens.
    from tests.qt.press_handover import Paints, arc_turning
    monkeypatch.setattr(undo, "unfinished", lambda language, kind: None)
    monkeypatch.setattr(undo, "restorable", lambda language, scope: {"written_at": "2026-10-14T10:00:00",
                                                                     "cards": {"1701": 2830}, "scope": ["TheBank"]})
    win = opened(main)
    assert QTest.qWaitForWindowExposed(win)
    win.body_scroll.ensureWidgetVisible(win.btn_restore)  # (scrolled to, as a hand does on a short screen: Fresh-U 3)
    QTest.qWait(20)
    paints, seen, real = Paints(win.btn_restore), [], qt_junban.spawn

    def watched(window, fn, *args, **kw):
        seen.append((getattr(fn, "__name__", ""), arc_turning(win.btn_restore), paints.n, win.btn_restore.isEnabled()))
        return real(window, fn, *args, **kw)
    monkeypatch.setattr(qt_junban, "spawn", watched)
    win.on_restore()
    name, shown, painted, enabled = next(s for s in seen if s[0] == "restore_question")
    assert shown and painted >= 1 and enabled
    assert wait_until(lambda: card(win) is not None) and not arc_turning(win.btn_restore)


def test_show_earlier_paints_its_arc_before_the_planner_has_it_until_the_plan_lands(main, engine, monkeypatch):
    # *Show N earlier* (and its link chip, and a tick) showed nothing until the planner's answer (`_replanned`): its arc
    # now turns from the press, painted before the plan is handed to the planner, until the newest plan lands.
    from tests.qt.press_handover import Paints, arc_turning
    win = opened(main)
    previewed(win)
    win.checks_box.show()
    win.btn_earlier.show()
    assert QTest.qWaitForWindowExposed(win) and wait_until(lambda: win.btn_earlier.isVisible())
    win.body_scroll.ensureWidgetVisible(win.btn_earlier)  # (scrolled to, as a hand does on a short screen: Fresh-U 3)
    QTest.qWait(20)
    monkeypatch.setattr(win.session, "toggle_earlier", lambda: True)
    paints, seen, real = Paints(win.btn_earlier), [], win._replanner.ask

    def watched(work, *args, **kw):
        seen.append((arc_turning(win.btn_earlier), paints.n))
        return real(work, *args, **kw)
    monkeypatch.setattr(win._replanner, "ask", watched)
    win.btn_earlier.click()
    assert seen and seen[0][0] and seen[0][1] >= 1 and win.btn_earlier.isEnabled()
    assert wait_until(lambda: win._replan_press is None and not arc_turning(win.btn_earlier))


def test_fresh_u_on_a_short_screen_the_window_fits_and_its_body_scrolls(main, engine, monkeypatch):
    # Fresh-U row 3: 順 opened 1,330 px tall on a 1080p screen; it now asks for no more than the screen's available
    # height (less its frame) and scrolls inside, every control still in the window (the wiring walk sees them)
    from PyQt6.QtCore import QRect
    monkeypatch.setattr(windows, "screen_area", lambda win: QRect(0, 0, 1280, 380))
    win = opened(main)
    assert win.body_scroll is not None and win.height() <= 380
    assert win.body_scroll.verticalScrollBar().maximum() > 0
    assert win.isAncestorOf(win.btn_reorder) and win.body_scroll.widget().isAncestorOf(win.btn_reorder)
    found, walked = problems(win)
    assert found == [] and walked >= 8
    # the adversary's B1: a wheel over the unfocused deck menu scrolls the body; it never picks (and saves) a deck
    from PyQt6.QtCore import QPoint, QPointF
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication
    win.deck_box.addItems(["TheBank", "Kaishi 1.5k"])
    win.deck_box.clearFocus()
    picked = []
    win.deck_box.activated.connect(picked.append)
    at = win.deck_box.currentIndex()
    e = QWheelEvent(QPointF(5, 5), QPointF(win.deck_box.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120),
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(win.deck_box, e)
    assert win.deck_box.currentIndex() == at and picked == []
    assert win.body_scroll.verticalScrollBar().value() > 0
