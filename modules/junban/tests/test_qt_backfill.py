# SPDX-License-Identifier: GPL-3.0-or-later
"""Anki Backfill's Qt window (`qt_backfill.py`, W3.4 row 5): the Tk window's promises (inv-backfill-anki Window 1, §4),
kept on the 3.0 line, plus the port's fixes (inv §9: 1 SQLite never on the window's thread, 2 the table says how many
more, 3 a deferred rebuild says it waits, 5 Restore's Enter = No).

What a wrong answer would cost, most costly first: a fill of notes the user never previewed; a restore on a stray Enter;
two Anki writers at once, or a write after the window closed; the command line filling while the window is open; a
window that freezes on SQLite or a 4,000-row table; a dead or untipped control; Tk on the 3.0 line.

Offscreen, one QApplication (the window harness's), a temp test root, loopback only; Anki is the engine's fake
collection behind a patched `urlopen` (never Anki); the databases and the tagger are the engine tests' `_Session`.
"""
import csv
import os
import sqlite3
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from tests.qt.conftest import _per_test_window_state, qapp, wait_until  # noqa: E402,F401  (the window harness)
from tests.qt.test_wiring import problems  # noqa: E402

from app import locks  # noqa: E402
from app.qt import confirm, shell, windows  # noqa: E402
from app.services import jobs  # noqa: E402
from modules.junban import backfill, undo  # noqa: E402
from modules.junban import qt_backfill as Q  # noqa: E402
from modules.junban import qt_strings as S  # noqa: E402
from modules.junban.tests.test_backfill import FIELD, FIRST_NOTE, URL, _fake, _lapis, _Session  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
AT_ONCE_MS = 4 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 50       # W3.5's bound (tests/services_helpers)


@pytest.fixture
def ready():
    """The library's data and a general database are here unless a test says otherwise (the sandbox has none);
    no background build is left over from another test."""
    state = {"data": True, "general": True}
    backfill._PROCESS = None
    backfill._BACKGROUND.clear()
    backfill._FAILED.clear()
    with mock.patch.object(backfill, "data_ready", lambda language="ja": state["data"]), \
            mock.patch.object(backfill, "general_ready", lambda language="ja": state["general"]), \
            mock.patch.object(backfill, "rebuild_tip", lambda language="ja": f"Built for {language}."), \
            mock.patch.object(backfill, "Session", lambda settings: _Session()):
        yield state


class _NoAnki:
    """Anki closed: what every test meets unless it puts the engine's fake collection behind `urlopen` itself — a
    preview a choice starts never reaches whatever listens on this machine's AnkiConnect port."""

    def __call__(self, *args, **kwargs):
        import urllib.error
        raise urllib.error.URLError("Anki is closed in this test")


@pytest.fixture(autouse=True)
def _anki_closed():
    with _patched(_NoAnki()):
        yield


@pytest.fixture
def main(qapp, ready):  # noqa: F811
    services = shell.Services()
    services.settings.set({"junban_url": URL, "junban_backfill_fills": ["patterns"], "junban_chunk_size": 150})
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)
    from PyQt6.QtCore import QThreadPool                # a close-time worker never outlives the test's patches (AD5-9)
    QThreadPool.globalInstance().waitForDone(5000)


def _open(main):
    win = Q.open_window(main)
    assert wait_until(lambda: win.ready is not None)
    return win


def _connected(win, fake):
    with _patched(fake):
        win.refresh_connection()
        assert wait_until(lambda: win.connected and not win.working)


def _previewed(win, fake):
    with _patched(fake):
        win.on_preview()
        assert wait_until(lambda: win.preview_key is not None and not win.working)


def _open_cards(win):
    return [c for c in win.findChildren(confirm.Confirm) if c.answer is None]


def _card(win):
    """The confirmation open in `win` (it opens when the worker that read what to ask has answered)."""
    assert wait_until(lambda: _open_cards(win))
    return _open_cards(win)[-1]


def _anki():
    return _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ", patterns="<div>mine</div>"),
                 _lapis(2, "話が弾む", "はなしがはずむ"))


# --- the door, one window, the wiring --------------------------------------------------------------------------- #
def test_the_door_shows_while_junban_is_on_and_opens_one_window(main):
    door = next(op for op in windows.OPENERS if op.name == "backfill")
    row = windows.launchers(main, main.page_widgets["settings"])    # the base looks for modules on a worker
    assert wait_until(lambda: "junban" in windows._FOUND)
    assert door.module == "junban" and windows.available(door, {}, "ja")
    assert wait_until(lambda: not row.buttons["backfill"].isHidden())
    assert not windows.available(door, {"enable_junban": False}, "ja")
    a = windows.launch(main, door)
    b = windows.launch(main, door)
    assert isinstance(a, Q.BackfillWindow) and a is b and a.windowTitle() == "Anki Backfill — Surasura"


def test_every_control_is_wired_tipped_and_named_in_all_three_windows(main):
    win = _open(main)
    found, walked = problems(win)
    assert found == [] and walked >= 9
    fake = _anki()
    _connected(win, fake)
    _previewed(win, fake)
    win.on_fields(backfill.FILLS[0])
    win.on_get_data()
    fields, data = windows.opened(win, Q.FIELDS_NAME), windows.opened(win, Q.DATA_NAME)
    for w in (fields, data):
        found, walked = problems(w)
        assert found == [] and walked >= 1
    for mark in list(win.help_marks.values()) + [win.details]:
        assert mark.accessibleName() and mark.focusPolicy() == Qt.FocusPolicy.TabFocus


def test_opening_the_window_writes_no_setting(main):
    before = main.services.settings.pending()
    win = _open(main)
    QTest.qWait(50)
    assert main.services.settings.pending() == before and win.choices.fills == ("patterns",)


def test_the_window_opens_without_tkinter(tmp_path):
    # 3.0 ships no Tk (G1.2-1): the window, its view model and the engine it calls import none.
    script = (
        "import sys\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "from app.qt import shell\n"
        "from modules.junban import open_backfill_qt\n"
        "app = QApplication(['w34-backfill'])\n"
        "services = shell.Services()\n"
        "win = shell.open_window(app, services)\n"
        "bf = open_backfill_qt(win)\n"
        "bf.on_get_data()\n"
        "app.processEvents()\n"
        "print('TK', sorted(m for m in sys.modules if 'tkinter' in m), bf.isVisible(), flush=True)\n"
        "bf.close(); win.close(); services.shutdown(0.5)\n"
        "shell.quiet_exit(workers_ms=5000, gone=(win,))\n")    # the app's own quit: the windows deleted and no pool
    #                                                     worker left before Python's teardown (there, 0xC0000005)
    env = dict(os.environ, PYTHONPATH=ROOT, SURASURA_TEST_ROOT=str(tmp_path), QT_QPA_PLATFORM="offscreen",
               SURASURA_FREEZE_MOTION="1", SURASURA_NO_UI_TIMERS="1", SURASURA_NO_ANKI_SYNC="1",
               APPDATA=str(tmp_path / "appdata"), LOCALAPPDATA=str(tmp_path / "local"),
               SURASURA_INSTANCE_NAME=f"w34-bf-{os.getpid()}")
    out = subprocess.run([sys.executable, "-c", script], cwd=str(tmp_path), env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "TK [] True" in out.stdout


# --- the preview is the confirmation ------------------------------------------------------------------------------ #
def test_fill_waits_for_a_preview_of_the_choices_on_screen(main):
    win, fake = _open(main), _anki()
    assert not win.btn_fill.isEnabled()
    _connected(win, fake)
    assert not win.btn_fill.isEnabled()                              # connected, no preview yet
    _previewed(win, fake)
    assert win.btn_fill.isEnabled() and win.model.rowCount() == 3
    assert win.summary.text() == "Fill 1 note · 2 skipped"
    assert win.model.rows[0][0] == "探検" and win.model.rows[0][4] is True
    with _patched(fake):
        win.chk_replace.click()                                     # any choice throws the preview away
        assert not win.btn_fill.isEnabled() and win.preview_key is None and win.model.rowCount() == 0
        assert wait_until(lambda: win.preview_key is not None and not win.working)   # and a new one follows


def test_a_preview_that_lands_after_a_choice_changed_is_never_shown(main):
    win, fake = _open(main), _anki()
    _connected(win, fake)
    with _patched(fake):
        result = backfill.preview(win._engine(), _Session())
    old_key = win.choices.key(win.language)
    win.choices = win.choices.but(cards="new")
    win._show_preview(result, old_key, Q.V.shown(result, win.choices))
    assert win.preview_key is None and win.model.rowCount() == 0 and not win.btn_fill.isEnabled()


def test_another_languages_preview_is_no_confirmation(main):
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh")
    assert win.preview_key is None and not win.btn_fill.isEnabled()
    assert wait_until(lambda: win.ready is not None and win.ready.language == "zh")


def test_a_choice_with_anki_gone_still_throws_the_preview_away(main):
    # Mutant Q8's witness: with no new preview to replace it (Anki closed meanwhile), a choice must still clear the
    # table — the rows on screen are the confirmation, and they no longer describe what a fill would write.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    win._on_connection({"ok": False, "error": "refused"}, [])
    win.chk_replace.click()
    assert win.model.rowCount() == 0 and win.summary.text() == "" and win.preview_key is None
    assert not win.btn_fill.isEnabled()


def test_a_choice_saves_only_its_own_key(main):
    win, fake = _open(main), _anki()
    _connected(win, fake)
    with mock.patch.object(main.services.settings, "set", wraps=main.services.settings.set) as saved:
        win.radios["new"].click()
    assert saved.call_args_list[0].args[0] == {"junban_backfill_cards": "new"}
    win.deck_box.setCurrentIndex(0)
    with mock.patch.object(main.services.settings, "set", wraps=main.services.settings.set) as saved:
        win.checks["sentence"].click()
    assert saved.call_args_list[0].args[0] == {"junban_backfill_fills": ["patterns", "sentence"]}


# --- Fill ----------------------------------------------------------------------------------------------------------- #
def test_fill_asks_once_its_default_the_action_and_writes_only_what_was_previewed_and_unchanged(main):
    win, fake = _open(main), _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "囲む", "かこむ"))
    with mock.patch.dict(FIELD, {"囲む": FIELD["囲む"]}):
        _connected(win, fake)
        _previewed(win, fake)
        assert len(win.preview["edits"]) == 2
        fake.notes[FIRST_NOTE + 1]["fields"]["Patterns"]["value"] = "<div>typed by hand</div>"
        with _patched(fake):
            win.btn_fill.click()
            card = _card(win)
            assert card.title.text() == "Fill 2 notes in Anki?" and card.default is card.yes
            QTest.keyClick(card, Qt.Key.Key_Return)                     # Enter = Fill (the preview showed it)
            assert wait_until(lambda: not win.working and fake.note_writes)
    assert fake.note_writes == [(FIRST_NOTE, {"Patterns": FIELD["探検"]})]
    assert fake.notes[FIRST_NOTE + 1]["fields"]["Patterns"]["value"] == "<div>typed by hand</div>"
    assert "1 changed since the preview" in win.status.text()
    assert undo.load("ja", kind="backfill")["complete"] is True      # journal, snapshot, then the write
    assert win.preview_key is None and not win.btn_fill.isEnabled()  # what was on screen is history now
    done = [j for j in main.services.registry.snapshot() if j.kind == "backfill"]
    assert done and done[-1].label == S.BF_JOB_FILL and done[-1].state == jobs.DONE


def test_cancel_on_the_fill_question_writes_nothing(main):
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    with _patched(fake):
        win.btn_fill.click()
        QTest.keyClick(_card(win), Qt.Key.Key_Escape)
        QTest.qWait(100)
    assert fake.note_writes == [] and not win.working and win.btn_fill.isEnabled()


def test_a_yes_fills_only_the_preview_it_was_asked_about(main):
    # Mutant Q1's witness: the question names one preview's notes; if another preview took its place while it was open
    # (same choices, other notes), the yes fills nothing — the user never saw those.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    with _patched(fake):
        win.btn_fill.click()
        card = _card(win)
        other = dict(win.preview, edits={FIRST_NOTE + 2: {"Patterns": {"before": "", "after": FIELD["探検"]}}})
        win.preview = other                                          # a newer preview of the same choices
        card.yes.click()
        QTest.qWait(200)
    assert fake.note_writes == [] and win.job is None and not win.working


def test_an_unfinished_fill_blocks_the_next_and_says_why(main):
    win, fake = _open(main), _fake(_lapis(0, "探検", "たんけん"), refuse_note_writes="collection is not available")
    _connected(win, fake)
    for _ in range(2):
        _previewed(win, fake)
        with _patched(fake):
            win.btn_fill.click()
            _card(win).yes.click()
            assert wait_until(lambda: not win.working and win.job is None)
    assert "Restore first" in win.status.text()


def test_replace_reaches_the_engine_and_overwrites(main):
    win, fake = _open(main), _fake(_lapis(0, "探検", "たんけん", patterns="<div>old</div>"))
    _connected(win, fake)
    with _patched(fake):
        win.chk_replace.click()
        assert wait_until(lambda: win.preview_key is not None and not win.working)
    assert win._engine()["junban_backfill_replace"] is True and win.btn_fill.isEnabled()
    assert win.preview["edits"][FIRST_NOTE]["Patterns"]["before"] == "<div>old</div>"


def test_a_fill_waits_for_junbans_reorder_in_this_window_and_closing_meanwhile_writes_nothing(main):
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    reorder = main.services.registry.submit("junban", "Reordering", lambda job: None)
    runs = []
    real = backfill.run
    with _patched(fake), mock.patch.object(backfill, "run", lambda *a, **k: runs.append(1) or real(*a, **k)):
        win.btn_fill.click()
        _card(win).yes.click()
        job = win.job
        assert job is not None and job.state == jobs.WAITING
        win.close()
        reorder.finish()
        QTest.qWait(300)
    assert fake.note_writes == [] and job.state == jobs.DONE and job.cancelled
    assert runs == []                         # cancelled while it waited here: never started at all (mutant Q4)


def test_a_fill_that_ends_after_the_window_closed_lets_its_databases_go(main):
    # Mutant Q19's witness: closing while a fill writes leaves the session to the fill's own thread (closing it then
    # would pull the databases from under the write); when the write ends, the session goes with it.
    win, fake = _open(main), _anki()
    closed, gate, writing = [], threading.Event(), threading.Event()

    class Watched(_Session):
        def close(self):
            closed.append(1)
    from modules.junban import ankiconnect
    real = ankiconnect.update_notes

    def slow(*args, **kwargs):                                       # the write under way: past the writer's lock
        writing.set()
        gate.wait(10)
        return real(*args, **kwargs)
    with mock.patch.object(backfill, "Session", lambda settings: Watched()), _patched(fake),             mock.patch.object(ankiconnect, "update_notes", slow):
        _connected(win, fake)
        _previewed(win, fake)
        closed.clear()
        win.btn_fill.click()
        _card(win).yes.click()
        job = win.job
        assert writing.wait(5)
        win.close()
        QTest.qWait(100)
        assert closed == []                                          # the write still holds it
        gate.set()
        assert wait_until(lambda: job.state == jobs.DONE and closed)
    assert fake.note_writes                                          # the write under way finished


def test_closing_mid_wait_for_another_programs_writer_writes_nothing(main):
    from app import anki_connect
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    taken, done = threading.Event(), threading.Event()

    def hold():
        with anki_connect.writer("Backfill"):
            taken.set()
            done.wait(30)
    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert taken.wait(5)
    with _patched(fake):
        win.btn_fill.click()
        _card(win).yes.click()
        assert wait_until(lambda: "Waiting for Backfill" in win.status.text())
        job = win.job
        win.close()
        assert wait_until(lambda: job.state in (jobs.DONE, jobs.FAILED), 10)
    done.set()
    holder.join(5)
    assert fake.note_writes == [] and job.cancelled


# --- Restore -------------------------------------------------------------------------------------------------------- #
def test_restore_with_nothing_filled_asks_nothing(main):
    win = _open(main)
    win.btn_restore.click()
    assert wait_until(lambda: S.BF_NOTHING_FILLED in win.status.text())
    assert not [c for c in win.findChildren(confirm.Confirm) if c.answer is None]


def test_restore_asks_with_cancel_the_default_and_enter_or_esc_put_nothing_back(main):
    win, fake = _open(main), _anki()
    with _patched(fake):
        backfill.run(win._engine(), _Session())
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Escape):
        win.btn_restore.click()
        card = _card(win)
        assert card.title.text() == S.BF_ASK_RESTORE and card.body.text().startswith("1 note filled")
        assert card.default is card.no                              # 🧭 IK-10c: Enter = No
        with _patched(fake):
            QTest.keyClick(card, key)
            QTest.qWait(150)
        assert fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == FIELD["探検"]
    win.btn_restore.click()
    with _patched(fake):
        _card(win).yes.click()
        assert wait_until(lambda: not win.working and fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == "")
    assert "Restored 1 note." in win.status.text()


def test_a_restore_answered_after_a_language_switch_puts_nothing_back(main):
    # Mutant Q13's witness: the question named Japanese's fills; the main window switched to Chinese while it was open
    # (the window was idle, so it followed) — a yes then restores nothing in either language and says to look again.
    win, fake = _open(main), _anki()
    with _patched(fake):
        backfill.run(win._engine(), _Session())
    win.btn_restore.click()
    card = _card(win)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh")
    with _patched(fake), mock.patch.object(backfill, "restore", side_effect=AssertionError("restored")) as restore:
        card.yes.click()
        QTest.qWait(200)
    assert not restore.called and S.BF_LOOK_AGAIN in win.status.text()
    assert fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == FIELD["探検"]


def test_fill_and_restore_called_while_busy_or_without_a_preview_do_nothing(main):
    # Mutants Q16 / Q18's witnesses: the buttons are off then, but the actions guard themselves too (a door or a
    # shortcut may call them).
    win = _open(main)
    win.on_fill()                                                    # no preview: nothing asked, nothing raised
    win.working = True
    win.on_restore()                                                 # a job runs: no plan read, no question
    QTest.qWait(150)
    assert not _open_cards(win) and S.BF_NOTHING_FILLED not in win.status.text()
    win.working = False


def test_restore_names_connects_unfinished_fill_and_puts_back_that_one(main):
    win = _open(main)
    note, card = _lapis(0, "探検", "たんけん", patterns="<div>〜を探検する</div>")
    fake = _fake((note, card))
    run_id = "backfill-20261006-040000-000"
    undo.save([], ["TheBank"], kind="backfill", run_id=run_id,
              fields={note["noteId"]: {"Patterns": {"before": "", "after": "<div>〜を探検する</div>"}}})
    win.btn_restore.click()
    ask = _card(win)
    assert ask.title.text() == S.BF_ASK_RUN and run_id in ask.body.text()
    with _patched(fake):
        ask.yes.click()
        assert wait_until(lambda: not win.working and win.job is None)
    assert fake.notes[note["noteId"]]["fields"]["Patterns"]["value"] == ""
    assert undo.unfinished("ja", "backfill") is None


# --- the window's lock, nothing slow on its thread ----------------------------------------------------------------- #
def test_the_window_holds_backfill_window_while_open_so_the_cli_stands_aside(main):
    win = _open(main)
    assert wait_until(lambda: locks.in_use("backfill-window"))
    win.close()
    assert wait_until(lambda: not locks.in_use("backfill-window"))


def test_no_sqlite_is_opened_on_the_windows_thread(main, ready):
    # inv defect 1: data_ready / general_ready / rebuild_tip open SQLite; the window reads them on a worker and keeps
    # the answers. The guard: every sqlite3.connect records its thread; data_ready below really opens one.
    threads, real = [], sqlite3.connect

    def guarded(*args, **kwargs):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(*args, **kwargs)

    def opens(language="ja"):
        sqlite3.connect(":memory:").close()
        return True
    with mock.patch("sqlite3.connect", guarded), mock.patch.object(backfill, "data_ready", opens):
        win, fake = _open(main), _anki()
        _connected(win, fake)
        _previewed(win, fake)
        for _ in range(3):
            win.chk_replace.click()
            assert wait_until(lambda: not win.working)
        main.services.settings.set({"target_language": "zh"})
        assert wait_until(lambda: win.ready is not None and win.ready.language == "zh")
    assert threads and not any(threads)


def test_a_4000_row_preview_says_how_many_more_and_a_tick_stays_at_once(main):
    words = []
    with open(os.path.join(ROOT, "tests", "Test Resources", "ja", "expected_output.csv"), encoding="utf-8-sig") as f:
        words = [row["Word"] for row in csv.DictReader(f) if row.get("Word")]
    rows = [(FIRST_NOTE + i, words[i % len(words)], "Patterns", "fill", FIELD["探検"], "patterns") for i in range(4500)]
    result = {"scope": {"models": {}, "notes": []}, "rows": rows, "by_fill": {"patterns": {"fill": 4500}},
              "edits": {r[0]: {"Patterns": {"before": "", "after": r[4]}} for r in rows}}
    win, fake = _open(main), _anki()
    _connected(win, fake)
    win._show_preview(result, win.choices.key(win.language), Q.V.shown(result, win.choices))
    assert win.model.rowCount() == 4000 and win.more.isVisibleTo(win)
    assert win.more.text().startswith("500 more not shown")
    assert win.btn_fill.isEnabled()
    resets = win.model.resets
    with _patched(fake):
        start = time.perf_counter()
        win.chk_replace.click()                                     # a tick: one reset to empty, never row by row
        ms = (time.perf_counter() - start) * 1000
        assert wait_until(lambda: not win.working)
    assert ms <= AT_ONCE_MS, ms
    assert win.model.resets >= resets + 1 and not win.more.isVisibleTo(win)


# --- パターン data and the library build ------------------------------------------------------------------------- #
class _Process:
    def __init__(self, lines, code=0):
        self.stdout, self.code = iter(lines), code

    def wait(self):
        return self.code


def test_build_and_preview_builds_once_then_previews(main, ready):
    ready["data"] = False
    win, fake = _open(main), _anki()
    _connected(win, fake)
    assert win.btn_preview.text() == S.BF_BUILD_PREVIEW and win.preview_key is None   # never started by itself

    def start(language, reinforce):
        ready["data"] = True
        return _Process(["PROGRESS 25/50", "PROGRESS 50/50", "done"])
    with _patched(fake), mock.patch.object(backfill, "start_rebuild", start):
        win.btn_preview.click()
        assert wait_until(lambda: win.preview_key is not None and not win.working)
    assert win.btn_preview.text() == S.BF_PREVIEW


def test_a_failed_build_says_why(main, ready):
    ready["data"] = False
    win, fake = _open(main), _anki()
    _connected(win, fake)
    with mock.patch.object(backfill, "start_rebuild", lambda language, reinforce: _Process(["no token store"], 1)):
        win.btn_preview.click()
        assert wait_until(lambda: not win.working and "no token store" in win.status.text())
    assert win.preview_key is None


def test_a_rebuild_held_back_by_an_update_says_it_waits(main):
    win = _open(main)
    assert wait_until(lambda: win.btn_rebuild.isVisibleTo(win))
    assert win.btn_rebuild.toolTip() == "Built for ja."                # read on a worker, kept
    with mock.patch.object(backfill, "_update_waiting", lambda: True), \
            mock.patch.object(backfill, "rebuild_in_background", lambda *a, **k: False):
        win.btn_rebuild.click()
        assert wait_until(lambda: S.BF_REBUILD_DEFERRED in win.status.text())
    assert S.BF_REBUILD_FAILED not in win.status.text()


def test_a_finished_background_build_goes_in_at_idle_with_the_session_closed_first(main):
    win, fake = _open(main), _anki()
    order, state = [], {"bg": ("ja", 10, 100)}

    class Watched(_Session):
        def close(self):
            order.append("close")
    with mock.patch.object(backfill, "background", lambda: state["bg"]), \
            mock.patch.object(backfill, "Session", lambda settings: Watched()), \
            mock.patch.object(backfill, "promote", lambda language: order.append(("promote", language)) or True):
        _connected(win, fake)
        _previewed(win, fake)                                        # a session holds the set in use
        win._watch_build()
        assert win.build_line.text() == S.BF_BUILD_LINE_FILES.format(done="10", total="100")
        win.working = True                                           # a job reads the set: not now
        state["bg"] = None
        win._watch_build()
        QTest.qWait(200)                                             # a promote would run on a worker (mutant Q11)
        assert order == [] and win.build_line.text() == ""
        win.working = False
        win._watch_build()
        assert wait_until(lambda: ("promote", "ja") in order and not win.working)
    assert order.index("close") < order.index(("promote", "ja"))


def test_get_data_shows_only_without_a_general_database_and_its_window_opens_once(main, ready):
    ready["general"] = False
    win = _open(main)
    assert win.btn_get_data.isVisibleTo(win)
    win.btn_get_data.click()
    win.btn_get_data.click()
    data = windows.opened(win, Q.DATA_NAME)
    assert data is not None and len([w for w in QApplication.topLevelWidgets()
                                     if isinstance(w, Q.DataWindow) and not w.gone]) == 1
    assert data.buttons["download"].isEnabled() and "32 MB" in data.info.text()
    QTest.keyClick(data, Qt.Key.Key_Escape)
    assert windows.opened(win, Q.DATA_NAME) is None and win.isVisible()


def test_import_closes_the_session_first_then_installs_then_previews(main, ready):
    from modules.junban import patterns_package
    win, fake = _open(main), _anki()
    order = []

    class Watched(_Session):
        def close(self):
            order.append("close")
    with mock.patch.object(backfill, "Session", lambda settings: Watched()):
        _connected(win, fake)
        _previewed(win, fake)
        with mock.patch.object(QFileDialog, "getOpenFileName", lambda *a, **k: ("C:/packages/patterns_ja.zip", "")), \
                mock.patch.object(patterns_package, "install",
                                  lambda path, progress=None: order.append(("install", path)) or ["patterns_ja.db"]), \
                _patched(fake):
            win.on_get_data()
            windows.opened(win, Q.DATA_NAME).buttons["import"].click()
            assert wait_until(lambda: win.preview_key is not None and not win.working and order[-1:] != [])
    assert order[:2] == ["close", ("install", "C:/packages/patterns_ja.zip")]
    assert "Installed: patterns_ja.db." in win.status.text()


def test_a_failed_download_says_why_and_a_cancelled_picker_does_nothing(main):
    from modules.junban import patterns_package
    win = _open(main)

    def refuse(progress=None, language="ja"):
        raise patterns_package.PackageError("The download didn't match its checksum, so nothing was installed.")
    with mock.patch.object(patterns_package, "get_shared", refuse):
        win.on_download()
        assert wait_until(lambda: not win.working and "checksum" in win.status.text())
    with mock.patch.object(QFileDialog, "getOpenFileName", lambda *a, **k: ("", "")):
        win.on_import()
    assert not win.working


# --- the Fields window -------------------------------------------------------------------------------------------- #
def test_the_fields_window_lists_mapped_first_saves_each_choice_and_previews_again(main):
    win = _open(main)
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    _connected(win, fake)
    _previewed(win, fake)
    assert win.targets["patterns"].text() == "Lapis → Patterns"
    win.targets["patterns"].click()
    fields = windows.opened(win, Q.FIELDS_NAME)
    assert list(fields.field_boxes) == ["Lapis"]
    box = fields.field_boxes["Lapis"]
    with _patched(fake):
        box.setCurrentIndex(0)                                       # — skip —
        box.activated.emit(0)
        assert main.services.settings.get()["junban_backfill_fields"]["patterns"]["Lapis"] == ""
        assert win.targets["patterns"].text() == S.BF_TARGET_CHOOSE
        assert wait_until(lambda: win.preview_key is not None and not win.working)
        pick = fields.language_boxes["Lapis"]
        pick.setCurrentIndex(1)                                      # Chinese
        pick.activated.emit(1)
        assert dict(main.services.settings.get()["junban_backfill_note_languages"]) == {"Lapis": "zh"}
        assert wait_until(lambda: not win.working)
    win.targets["patterns"].click()
    assert windows.opened(win, Q.FIELDS_NAME) is fields              # one at a time, raised
    QTest.keyClick(fields, Qt.Key.Key_Escape)
    assert windows.opened(win, Q.FIELDS_NAME) is None and win.isVisible()


def test_the_fields_button_waits_for_a_preview(main):
    win = _open(main)
    assert not win.targets["patterns"].isEnabled()
    win.on_fields(backfill.FILLS[0])
    assert windows.opened(win, Q.FIELDS_NAME) is None


# --- the language, the small things --------------------------------------------------------------------------------- #
def test_a_language_switch_during_a_fill_waits_for_it(main):
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    gate = threading.Event()
    real = backfill.run

    def slow(*args, **kwargs):
        gate.wait(10)
        return real(*args, **kwargs)
    with _patched(fake), mock.patch.object(backfill, "run", slow):
        win.btn_fill.click()
        _card(win).yes.click()
        main.services.settings.set({"target_language": "zh"})
        QTest.qWait(400)
        assert win.language == "ja"                                  # never cut
        gate.set()
        assert wait_until(lambda: win.language == "zh" and not win.working)
    assert fake.note_writes and main.bar_line.full().startswith("Filled 1 note")


def test_the_help_marks_follow_the_language_and_copy_card_style_copies(main):
    win = _open(main)
    ja = win.help_marks["patterns"].toolTip()
    assert "Particles" in ja and "<b>" in ja
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: "Measure words" in win.help_marks["patterns"].toolTip())
    win.btn_copy.click()
    assert QApplication.clipboard().text().startswith("/* Surasura パターン */")
    assert S.BF_COPIED in win.status.text()


def test_not_connected_says_how_to_fix_it(main):
    win = _open(main)
    with mock.patch("app.anki_connect.probe", lambda url, required=(), timeout=5: {"ok": False, "error": "refused"}):
        win.btn_recheck.click()
        assert wait_until(lambda: not win.working)
    assert win.conn.text() == S.BF_CONN_NO and S.BF_START_ANKI in win.status.text()
    assert not win.btn_fill.isEnabled()


# --- the fix round (AD5-1, AD5-3, AD5-5, AD5-6, IK-73) ------------------------------------------------------------- #
def _big_result(n):
    """A synthetic preview of `n` notes with real words: what a big deck's preview hands the window."""
    with open(os.path.join(ROOT, "tests", "Test Resources", "ja", "expected_output.csv"), encoding="utf-8-sig") as f:
        words = [row["Word"] for row in csv.DictReader(f) if row.get("Word")]
    rows = [(FIRST_NOTE + i, words[i % len(words)], "Patterns", "fill" if i % 3 else "has_value", FIELD["探検"],
             "patterns") for i in range(n)]
    return {"scope": {"models": {"Lapis": {"fields": ["Expression", "Patterns"], "count": n,
                                           "mapped": {"patterns": "Patterns"}, "language": "ja"}}, "notes": []},
            "rows": rows, "by_fill": {"patterns": {"fill": n - n // 3, "has_value": n // 3}},
            "edits": {r[0]: {"Patterns": {"before": "", "after": r[4]}} for r in rows if r[3] == "fill"}}


def test_a_20000_row_preview_is_made_on_the_worker_and_no_window_step_takes_long(main):
    # AD5-1: sorting every row and cleaning 4,000 fields' HTML is the worker's; the window only sets the model. Every
    # step the window's thread runs for the preview (the click, each worker line, the job's end) is timed.
    result = _big_result(20000)
    threads, steps = [], []

    def on_thread(fn):
        def run(*args, **kwargs):
            threads.append((fn.__name__, threading.current_thread() is threading.main_thread()))
            return fn(*args, **kwargs)
        run.__name__ = fn.__name__
        return run

    def timed(fn):
        def run(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                steps.append((fn.__name__, (time.perf_counter() - start) * 1000))
        return run
    with mock.patch.object(Q.BackfillWindow, "_said", timed(Q.BackfillWindow._said)), \
            mock.patch.object(Q.BackfillWindow, "_done", timed(Q.BackfillWindow._done)), \
            mock.patch.object(Q.V, "preview_rows", on_thread(Q.V.preview_rows)), \
            mock.patch.object(Q.V, "details", on_thread(Q.V.details)), \
            mock.patch.object(Q.V, "models_of", on_thread(Q.V.models_of)):
        win, fake = _open(main), _anki()
        _connected(win, fake)
        steps.clear()
        with mock.patch.object(backfill, "preview", lambda settings, session, status=None: result):
            start = time.perf_counter()
            win.on_preview()
            steps.append(("on_preview", (time.perf_counter() - start) * 1000))
            assert wait_until(lambda: win.preview_key is not None and not win.working)
        start = time.perf_counter()
        win.table.viewport().repaint()                               # the rows on screen painted once
        steps.append(("paint", (time.perf_counter() - start) * 1000))
    assert win.model.rowCount() == 4000 and win.more.text().startswith("16,000 more not shown")
    assert win.btn_fill.isEnabled() and win.targets["patterns"].text() == "Lapis → Patterns"
    assert {name for name, _gui in threads} >= {"preview_rows", "details", "models_of"}
    assert not any(gui for _name, gui in threads), threads
    worst = max(steps, key=lambda s: s[1])
    assert worst[1] <= AT_ONCE_MS, steps


def test_a_build_that_ends_while_fill_asks_waits_for_the_answer_and_the_yes_still_fills(main):
    # AD5-3: a promote must not take the window busy under an open question: the user's "Fill" would be dropped.
    win, fake = _open(main), _anki()
    promoted, state = [], {"bg": ("ja", 10, 100)}
    with mock.patch.object(backfill, "background", lambda: state["bg"]), \
            mock.patch.object(backfill, "promote", lambda language: promoted.append(language) or True):
        _connected(win, fake)
        _previewed(win, fake)
        win._watch_build()
        win.btn_fill.click()
        ask = _card(win)
        state["bg"] = None
        win._watch_build()                                           # the build ends while the question is open
        QTest.qWait(200)
        assert promoted == [] and not win.working                    # held while the question stands
        with _patched(fake):
            ask.yes.click()
            assert wait_until(lambda: win.job is None and not win.working and promoted == ["ja"])
    assert fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == FIELD["探検"]


def test_while_a_question_is_open_nothing_else_starts_and_the_window_looks_busy(main):
    # AD5-6 / AD5-3: Preview, ⟳ and Restore are off behind the question, and no probe or preview starts under it.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    win.btn_fill.click()
    ask = _card(win)
    assert not win.btn_preview.isEnabled() and not win.btn_recheck.isEnabled() and not win.btn_restore.isEnabled()
    assert not win.btn_fill.isEnabled()
    win.refresh_connection()
    win.on_preview()
    win.on_restore()
    assert not win.working and _open_cards(win) == [ask]
    ask.no.click()
    assert wait_until(lambda: win.btn_preview.isEnabled() and win.btn_restore.isEnabled())


def test_a_fill_yes_the_window_can_no_longer_honour_says_look_again(main):
    # AD5-3: a "yes" dropped because the preview went (here: the language switched under the question) says so.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    win.btn_fill.click()
    ask = _card(win)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh")
    with _patched(fake):
        ask.yes.click()
        QTest.qWait(100)
    assert win.job is None and S.BF_LOOK_AGAIN in win.status.text()
    assert fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == ""


def test_a_question_dropped_by_a_hide_lets_the_held_swap_go_in(main):
    # A question the window's hide drops answers nothing: the window must not stay "asking" for ever.
    win, fake = _open(main), _anki()
    promoted, state = [], {"bg": ("ja", 10, 100)}
    with mock.patch.object(backfill, "background", lambda: state["bg"]), \
            mock.patch.object(backfill, "promote", lambda language: promoted.append(language) or True):
        _connected(win, fake)
        _previewed(win, fake)
        win._watch_build()
        win.btn_fill.click()
        _card(win)
        state["bg"] = None
        win._watch_build()
        win.hide()
        assert wait_until(lambda: promoted == ["ja"] and not win.working)
        win.show()
        assert wait_until(lambda: win.btn_preview.isEnabled())


def test_a_download_counts_its_megabytes_on_its_own_never_in_the_window(main, ready):
    # AD5-5: the download's once-per-MB counter belongs to its worker; two downloads each say their first megabyte.
    from modules.junban import patterns_package
    ready["general"] = False
    win = _open(main)
    lines = []

    def get_shared(progress=None, language="ja"):
        for done in (0, 400_000, 1_200_000):
            progress(done, 3_000_000)
        return ["patterns_general.db"]
    with mock.patch.object(patterns_package, "get_shared", get_shared), \
            mock.patch.object(Q.BackfillWindow, "_status", lambda self, line: lines.append(line)):
        for _ in range(2):
            win.on_download()
            assert wait_until(lambda: not win.working)
    once = [S.BF_SUMMARY_DOWNLOADING_MB.format(mb=0, total=3), S.BF_SUMMARY_DOWNLOADING_MB.format(mb=1, total=3)]
    assert lines == once * 2
    assert "_downloaded_mb" not in vars(win)


def test_a_fill_is_journalled_for_put_back_and_the_window_never_turns_the_automatic_step_on(main):
    # IK-73 / FT-1: after a put-back switched Backfill's automatic step off, the window's choices and Fill leave it
    # off (only the keys the user changed are saved), and the window's fill is journalled like every other.
    from modules.junban import first_touch
    main.services.settings.set({"junban_auto_backfill": False})
    win, fake = _open(main), _anki()
    _connected(win, fake)
    with _patched(fake):
        win.chk_replace.click()
        win.chk_replace.click()
        assert wait_until(lambda: win.preview_key is not None and not win.working)
        win.btn_fill.click()
        _card(win).yes.click()
        assert wait_until(lambda: win.job is None and not win.working)
    assert main.services.settings.get().get("junban_auto_backfill") is False
    assert any(line.get("kind") == "backfill" for line in first_touch.journal("ja"))


# --- the adversary's resume findings (AD5-7, AD5-10, AD5-11) -------------------------------------------------------- #
def test_closing_while_a_queued_fill_waits_starts_nothing_on_the_closed_window(main):
    # AD5-7: the close cancels the queued Fill; its "nothing written" must not wake a preview a choice asked for
    # meanwhile (Anki reads and a new session after the window closed), and the session goes on a worker.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    reorder = main.services.registry.submit("junban", "Reordering", lambda job: None)
    previews, closes = [], []

    class Watched(_Session):
        def close(self):
            closes.append(threading.current_thread() is threading.main_thread())
    real = backfill.preview
    with _patched(fake), mock.patch.object(backfill, "Session", lambda settings: Watched()):
        win.keeper.close()
        win.keeper.get(win._engine())                                # a session the preview made, still open
        win.btn_fill.click()
        _card(win).yes.click()
        assert win.job is not None and win.job.state == jobs.WAITING
        win.preview_wanted = True                                    # a choice made while the fill waited
        with mock.patch.object(backfill, "preview", lambda *a, **k: previews.append(1) or real(*a, **k)):
            win.close()
            QTest.qWait(300)
        reorder.finish()
    assert previews == [] and fake.note_writes == []
    assert closes and not any(closes)                                # never on the window's thread


def test_a_build_that_ends_after_a_language_switch_says_nothing_about_the_new_language(main, ready):
    # AD5-10: a Japanese "Build & preview" ending on a window that now shows Chinese never says Chinese was built.
    win = _open(main)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.language == "zh" and win.ready is not None and win.ready.language == "zh")
    ready["data"] = False
    win.ready = Q.V.read_readiness("zh")                             # Chinese has no library set either
    win._clear_messages()
    win._on_built("ja", True, "", Q.V.Readiness("ja", True, True, "Built for ja."))
    assert win.status.text() == "" and win.ready.language == "zh"


def test_the_data_windows_buttons_are_off_while_backfill_is_busy(main, ready):
    # AD5-11: an install pressed while a job runs would do nothing, silently: the buttons say so by being off.
    ready["general"] = False
    win = _open(main)
    win.on_get_data()
    data = windows.opened(win, Q.DATA_NAME)
    assert data.buttons["import"].isEnabled()
    win._set_working(True)
    assert not data.buttons["download"].isEnabled() and not data.buttons["import"].isEnabled()
    win._set_working(False)
    assert data.buttons["import"].isEnabled()
    assert data.buttons["download"].isEnabled() == bool(Q.patterns_package.shared_for(win.language))


# --- the intent keeper's row 5 file (IK-75, IK-76, IK-78, IK-79) ------------------------------------------------- #
def test_a_fill_waiting_behind_junbans_reorder_says_so_then_says_it_writes(main):
    # IK-75: a Fill queued behind 順's reorder in this process says what it waits for; once it runs, that it writes;
    # at its end only the result stays.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    reorder = main.services.registry.submit("junban", "Reordering", lambda job: None)
    with _patched(fake):
        win.btn_fill.click()
        _card(win).yes.click()
        assert wait_until(lambda: S.BF_JOB_WAITING_FOR.format(what="Reordering") in win.status.text())
        reorder.finish()
        assert wait_until(lambda: win.job is None and not win.working)
    assert S.BF_JOB_WAITING_FOR.format(what="Reordering") not in win.status.text()
    assert S.BF_JOB_RUNNING.format(label=S.BF_JOB_FILL) not in win.status.text()
    assert fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == FIELD["探検"]


def test_a_fill_yes_after_a_fields_edit_under_the_question_says_look_again(main):
    # IK-76 (b): the Fields window is its own window, outside the question's dimmed room: an edit there throws the
    # preview away, and the "yes" that follows says nothing was written.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    win.on_fields(backfill.FILLS[0])
    fields = windows.opened(win, Q.FIELDS_NAME)
    win.btn_fill.click()
    ask = _card(win)
    box = fields.language_boxes["Lapis"]
    box.setCurrentIndex(box.count() - 1)
    box.activated.emit(box.count() - 1)                              # "Language?": the preview goes
    with _patched(fake):
        ask.yes.click()
        QTest.qWait(100)
    assert win.job is None and S.BF_PREVIEW_CHANGED in win.status.text()
    assert fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == ""


def test_nothing_repaints_when_nothing_changed(main):
    # IK-78 (S19): a re-probe that finds the same decks, a build tick with the same line and a sync after nothing
    # changed set no text, tip or name.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    widgets = [win.conn, win.summary, win.build_line, win.btn_preview, win.btn_fill, win.btn_restore,
               win.btn_rebuild] + list(win.checks.values()) + list(win.help_marks.values()) + list(win.targets.values())
    calls = []
    for w in widgets:
        for name in ("setText", "setToolTip", "setAccessibleName"):
            real = getattr(w, name)
            setattr(w, name, lambda *a, _r=real, _n=name: (calls.append(_n), _r(*a)))
    decks = [win.deck_box.itemText(i) for i in range(win.deck_box.count())]
    clears = []
    win.deck_box.clear = lambda: clears.append(1)
    state = {"bg": ("ja", 5, 50)}
    with mock.patch.object(backfill, "background", lambda: state["bg"]):
        win._watch_build()
        calls.clear()
        win._watch_build()                                           # the same tick
        win._sync()
        win._sync()
        win._on_connection({"ok": True, "version": 6}, decks[1:])    # the same decks again
    assert [c for c in calls if c != "setText"] == [] and calls.count("setText") <= 1   # the conn mark's words only
    assert clears == []


def test_the_connection_mark_takes_the_ok_and_bad_colours(main):
    # IK-79: the words carry the state; the colour repeats it, from the theme's tokens.
    from app.qt import style
    sheet = QApplication.instance().styleSheet()
    c = style.colours()
    assert f'QLabel#backfillconnection[state="ok"] {{ color: {c["ok"]}; }}' in sheet
    assert f'QLabel#backfillconnection[state="bad"] {{ color: {c["bad"]}; }}' in sheet
    win, fake = _open(main), _anki()
    _connected(win, fake)
    assert win.conn.property("state") == "ok"
    win._on_connection({"ok": False}, [])
    assert win.conn.property("state") == "bad"


# --- the resume round's mutant survivors' witnesses (row5.md § Resume round) ------------------------------------- #
def test_the_window_lock_is_taken_off_the_windows_thread(main):
    # Haiku H15: the take waits up to two seconds for the command line to let go — never on the window's thread.
    threads = []
    real = Q.V.WindowLock.hold

    def hold(self):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(self)
    with mock.patch.object(Q.V.WindowLock, "hold", hold):
        _open(main)
        assert wait_until(lambda: threads)
    assert threads == [False]


def test_a_readiness_read_for_another_language_is_dropped(main):
    # Haiku H17: a read for Japanese landing after the switch to Chinese never replaces Chinese's.
    win = _open(main)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: win.ready is not None and win.ready.language == "zh")
    zh = win.ready
    win._readiness_read(Q.V.Readiness("ja", True, True, "Built for ja."))
    assert win.ready is zh


def test_closing_while_restore_waits_for_another_programs_writer_puts_nothing_back(main):
    # Haiku H19: Restore's wait for another program's writer ends at the close, as Fill's does.
    from app import anki_connect
    win, fake = _open(main), _anki()
    with _patched(fake):
        backfill.run(win._engine(), _Session())
    taken, done = threading.Event(), threading.Event()

    def hold():
        with anki_connect.writer("Backfill"):
            taken.set()
            done.wait(30)
    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    assert taken.wait(5)
    try:
        with _patched(fake):
            win.btn_restore.click()
            _card(win).yes.click()
            assert wait_until(lambda: "Waiting for Backfill" in win.status.text())
            job = win.job
            win.close()
            assert wait_until(lambda: job.state in (jobs.DONE, jobs.FAILED), 10)
    finally:
        done.set()
        holder.join(5)
    assert fake.notes[FIRST_NOTE]["fields"]["Patterns"]["value"] == FIELD["探検"] and job.cancelled


def test_under_an_open_question_no_install_preview_or_second_question_starts(main, ready):
    # Mutants F9 / F11 / F25: the data window's Download, a readiness read that wants a preview, and a second Fill all
    # wait while the Fill question is open.
    from modules.junban import patterns_package
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    win.btn_fill.click()
    ask = _card(win)
    got = []
    with mock.patch.object(patterns_package, "get_shared", lambda **k: got.append(1) or []):
        win.on_download()
        win.preview_wanted = True
        win._readiness_read(win.ready)
        win.on_fill()
        QTest.qWait(100)
    assert got == [] and not win.working and _open_cards(win) == [ask]
    assert win.preview_key is not None and win.btn_fill.isEnabled() is False   # the preview asked about still stands
    ask.no.click()


def test_a_fields_edit_under_the_question_starts_no_preview_until_it_is_answered(main):
    # Mutant F10: the Fields window is outside the question's dimmed room; its edit waits to preview.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    win.on_fields(backfill.FILLS[0])
    fields = windows.opened(win, Q.FIELDS_NAME)
    win.btn_fill.click()
    ask = _card(win)
    box = fields.language_boxes["Lapis"]
    with _patched(fake):
        box.setCurrentIndex(0)
        box.activated.emit(0)
        assert not win.working and win.preview_wanted
        ask.no.click()
        assert wait_until(lambda: win.preview_key is not None and not win.working)   # then it follows


def test_a_question_a_hide_dropped_leaves_the_window_usable_when_shown_again(main):
    # Mutant F12: with no build to wake it, the window must still stop waiting for a question a hide dropped.
    win, fake = _open(main), _anki()
    _connected(win, fake)
    _previewed(win, fake)
    win.btn_fill.click()
    _card(win)
    assert not win.btn_preview.isEnabled()
    win.hide()
    win.show()
    assert wait_until(lambda: win.btn_preview.isEnabled() and win.btn_fill.isEnabled())


def test_a_workers_line_after_the_close_paints_nothing(main):
    # Mutant F14: a worker's late line reaches no closed window.
    win = _open(main)
    win._set_text(win.summary, "")
    win.close()
    win.relay.call(("summary", "late"))
    assert win.summary.text() == ""


# --- round 8 row 45: every press reacts at once ------------------------------------------------------------------- #
def test_rebuild_paints_its_arc_before_the_build_is_asked(main, monkeypatch):
    # *Rebuild from my library* showed nothing until the build had been asked (a worker): its arc now turns from the
    # press, painted before the ask is handed over, until the answer says what happens.
    from tests.qt.press_handover import HandOver, arc_turning
    win = _open(main)
    assert wait_until(lambda: win.btn_rebuild.isVisible()) and QTest.qWaitForWindowExposed(win)
    handed = HandOver(monkeypatch, win.btn_rebuild, lambda: arc_turning(win.btn_rebuild))
    with mock.patch.object(backfill, "_update_waiting", lambda: True), \
            mock.patch.object(backfill, "rebuild_in_background", lambda *a, **k: False):
        win.btn_rebuild.click()
        ask = handed.at("rebuild_now")
        assert ask.shown and ask.painted >= 1 and win.btn_rebuild.isEnabled()
        assert wait_until(lambda: S.BF_REBUILD_DEFERRED in win.status.text() and not arc_turning(win.btn_rebuild))


# --- translations: the count and the next step (Piyo-TR) --------------------------------------------------------- #
def test_the_cards_with_no_translation_are_counted_on_a_worker_and_the_prompt_is_copied(main):
    """Connected: the count (Backfill's deck) is read off the window's thread and said with the next step — Piyo, or
    Mattias's add-on; Copy the prompt copies the message for the learner's AI. Backfill itself calls no AI."""
    from app import card_translations
    win = _open(main)
    asked = []

    def count(anki, deck=None, language="ja"):
        asked.append((threading.current_thread() is threading.main_thread(), deck))
        return 12
    with mock.patch.object(card_translations, "count", count):
        _connected(win, _anki())
        assert wait_until(lambda: win.tr_count == 12)
    assert asked == [(False, None)]
    assert win.tr_line.isVisible() and win.tr_line.text() == S.BF_TR_COUNT.format(n=12)
    assert "Piyo" in win.tr_line.text() and "Mattias" in win.tr_line.text()
    win.btn_tr_copy.click()
    assert QApplication.clipboard().text() == S.BF_TR_PROMPT
    assert "surasura_cards_to_translate" in S.BF_TR_PROMPT and S.BF_TR_COPIED in win.status.text()


def test_no_count_none_to_do_or_anki_gone_hides_the_line(main):
    from app import card_translations
    win = _open(main)
    assert not win.tr_line.isVisible() and not win.btn_tr_copy.isVisible(), "unknown until Anki answers"
    with mock.patch.object(card_translations, "count", lambda anki, deck=None, language="ja": 0):
        _connected(win, _anki())
        assert wait_until(lambda: win.tr_count == 0)
    assert not win.tr_line.isVisible()

    def gone(anki, deck=None, language="ja"):
        raise OSError("Anki stopped answering")
    win.tr_count = "unset"
    with mock.patch.object(card_translations, "count", gone):
        _connected(win, _anki())
        assert wait_until(lambda: win.tr_count is None)
    assert not win.btn_tr_copy.isVisible()


def test_the_copied_prompt_names_backfills_deck_and_a_stale_count_is_dropped(main):
    """r1 S8: the line counts Backfill's deck, so the prompt names it (else the AI would do every deck); r1 N12: a
    count read for a deck no longer chosen never shows."""
    from app import card_translations
    win = _open(main)
    win._on_choice(win.choices.but(deck="Mining"))             # the deck picked in the window
    with mock.patch.object(card_translations, "count", lambda anki, deck=None, language="ja": 5):
        _connected(win, _anki())
        assert wait_until(lambda: win.tr_count == 5)
    win.btn_tr_copy.click()
    assert QApplication.clipboard().text() == S.BF_TR_PROMPT_DECK.format(deck='"Mining"')
    assert 'deck "Mining"' in QApplication.clipboard().text()
    win._show_translations(99, "Other deck", win.language)
    assert win.tr_count == 5 and "5 cards" in win.tr_line.text()
