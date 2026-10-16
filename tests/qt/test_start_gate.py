"""W3.5 part 3 — the start gate's window (`app/qt/start_gate.py`): before `Services()` opens the library.

What a wrong answer would cost: an everyday start held up by a window or a wait (the gate is on every start); a
refusal that lets the window open anyway (an offline library made empty, a half import used); a Cancel or ✕ that quits
mid-copy; Esc closing the start; a button that does nothing or says nothing. The decisions are `first_run`'s (its own
suite, with the real import); here each screen's buttons are driven against stand-ins for `first_run.run` / `state`,
and one start runs the real import through `gate()` end to end. USERPROFILE / APPDATA / LOCALAPPDATA point into
tmp_path; the library is the test root."""
import os
import threading
import time

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from app import import_2x, path_utils
from app.qt import start_gate
from app.services import first_run
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    for name, sub in (("USERPROFILE", "profile"), ("APPDATA", "Roaming"), ("LOCALAPPDATA", "Local"),
                      ("XDG_DATA_HOME", "Roaming")):
        monkeypatch.setenv(name, str(tmp_path / sub))


def _st(kind, **extra):
    st = {"state": kind, "library": os.path.join(os.environ["SURASURA_TEST_ROOT"], "ライブラリ"), "installed": True,
          "create": False, "recorded": True, "source": None, "installs": [], "note": None, "lists": []}
    st.update(extra)
    return st


class FakeRun:
    """A stand-in for `first_run.run`: records its calls, reports progress, and (with `hold`) works until cancelled."""

    def __init__(self, result=None, hold=False):
        self.calls = []
        self.result = result or {"status": "done", "reason": None, "message": None}
        self.hold = hold
        self.started = threading.Event()

    def __call__(self, st, progress=None, cancel=None, source=None, fresh=False):
        self.calls.append({"state": st["state"], "source": source, "fresh": fresh})
        self.started.set()
        if progress is not None:
            progress("files", 1, 3)
        if self.hold:
            deadline = time.monotonic() + 5
            while not cancel() and time.monotonic() < deadline:
                time.sleep(0.01)
            return {"status": "cancelled", "reason": "cancelled", "message": "stopped"}
        return dict(self.result)


def _gate(qapp, st):
    g = start_gate.Gate(qapp, st)
    g.start()
    return g


def _visible_buttons(g):
    return {b.text() for b in (g.choose_button, g.fresh_button, g.try_button, g.cancel_button, g.quit_button)
            if b.isVisible()}


# --- an everyday start ---------------------------------------------------------------------------------------------

def test_an_everyday_start_returns_at_once_with_no_window(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(first_run, "run", lambda *a, **k: calls.append(a))
    before = set(map(id, qapp.topLevelWidgets()))
    t0 = time.perf_counter()
    assert start_gate.gate(qapp) is True                 # a test root: a source run, ready
    took = time.perf_counter() - t0
    assert took < 0.05, took
    assert calls == [] and set(map(id, qapp.topLevelWidgets())) == before


def test_quiet_work_runs_with_no_window_and_goes_on(qapp, monkeypatch):
    # A new install's library to make, or a GraduatedList to merge: on a worker, no window unless it is refused.
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.READY, create=True))
    assert wait_until(lambda: g.ended)
    assert g.result is True and fake.calls == [{"state": first_run.READY, "source": None, "fresh": False}]
    assert g.screen is None, "never shown"


def test_quiet_work_that_is_refused_shows_why(qapp, monkeypatch):
    message = import_2x.CFA_MESSAGE.format(folder="D:\\ライブラリ", exe="Surasura.exe")
    monkeypatch.setattr(first_run, "run", FakeRun({"status": "blocked", "reason": "access_denied", "message": message}))
    g = _gate(qapp, _st(first_run.READY, create=True))
    assert wait_until(lambda: g.screen == "blocked")
    assert g.isVisible() and not g.ended
    assert g.line.text() == message and g.heading.text() == start_gate.BLOCKED_HEADING
    assert _visible_buttons(g) == {start_gate.TRY_AGAIN, start_gate.QUIT}


# --- bringing a library over ----------------------------------------------------------------------------------------

def test_the_import_shows_its_stage_and_cancel_stops_it_between_files(qapp, monkeypatch):
    fake = FakeRun(hold=True)
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.IMPORT, source="D:\\旧すらすら"))
    assert g.screen == "working" and g.heading.text() == start_gate.BRINGING
    assert _visible_buttons(g) == {start_gate.CANCEL} and g.bar.isVisible()
    assert wait_until(lambda: g.stage.text().startswith(start_gate.STAGES["files"]))
    assert g.stage.text() == start_gate.STAGE_COUNT.format(stage=start_gate.STAGES["files"], done=1, total=3)
    assert g.bar.maximum() == 3 and g.bar.value() == 1
    g.cancel_button.click()
    assert g.stage.text() == start_gate.STOPPING and not g.cancel_button.isEnabled()
    assert wait_until(lambda: g.screen == "unfinished")
    assert not g.ended, "a cancelled import never opens the library"
    assert _visible_buttons(g) == {start_gate.TRY_AGAIN, start_gate.QUIT}


def test_an_import_that_ends_goes_on(qapp, monkeypatch):
    monkeypatch.setattr(first_run, "run", FakeRun())
    g = _gate(qapp, _st(first_run.IMPORT, source="D:\\旧すらすら"))
    assert wait_until(lambda: g.ended)
    assert g.result is True and not g.isVisible()


def test_an_import_that_stops_says_its_sentence(qapp, monkeypatch):
    said = "Your old Surasura is still open. Close it, then try again."
    monkeypatch.setattr(first_run, "run", FakeRun({"status": "refused", "reason": "running", "message": said}))
    g = _gate(qapp, _st(first_run.IMPORT, source="D:\\旧すらすら"))
    assert wait_until(lambda: g.screen == "stopped")
    assert g.line.text() == said and not g.ended


# --- the refusals ---------------------------------------------------------------------------------------------------

def test_an_unfinished_import_is_refused_and_try_again_resumes_it(qapp, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    monkeypatch.setattr(first_run, "state", lambda: _st(first_run.IMPORT_UNFINISHED, source="D:\\旧すらすら"))
    g = _gate(qapp, _st(first_run.IMPORT_UNFINISHED, source="D:\\旧すらすら"))
    assert g.screen == "unfinished" and fake.calls == [], "refused first: nothing runs by itself"
    assert g.heading.text() == start_gate.UNFINISHED_HEADING
    g.try_button.click()
    assert wait_until(lambda: g.ended)
    assert g.result is True and fake.calls == [{"state": first_run.IMPORT_UNFINISHED, "source": None, "fresh": False}]


def test_a_missing_library_is_refused_until_it_is_back(qapp, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    answers = [_st(first_run.LIBRARY_MISSING), _st(first_run.READY)]
    monkeypatch.setattr(first_run, "state", lambda: answers.pop(0))
    g = _gate(qapp, _st(first_run.LIBRARY_MISSING))
    assert g.screen == "missing" and g.st["library"] in g.line.text()
    assert _visible_buttons(g) == {start_gate.TRY_AGAIN, start_gate.NEW_HERE, start_gate.QUIT}
    assert g.try_button.property("kind") == "primary", "Try again leads: the library is likely only away"
    g.try_button.click()                                  # still offline: the same refusal, nothing run
    assert wait_until(lambda: len(answers) == 1 and g.try_button.isEnabled())
    assert g.screen == "missing" and fake.calls == [] and not g.ended
    g.try_button.click()                                  # back: the start goes on
    assert wait_until(lambda: g.ended)
    assert g.result is True


def test_a_library_folder_never_seen_is_made_only_when_the_user_chooses_it(qapp, monkeypatch):
    # AD-2: nothing tells a new install's first start from a library offline: never made by itself.
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.LIBRARY_NEW, create=True))
    assert g.screen == "new" and fake.calls == [], "asked first: nothing runs by itself"
    assert g.heading.text() == start_gate.NEW_HEADING and g.st["library"] in g.line.text()
    # WZ-9 (c), Sonic 2026-10-15: a welcome step — *Start my library here* the main button, the drive / online ask in
    # its tooltip (with Try again's meaning), Try again and Quit kept
    assert g.heading.text() == "Welcome to Surasura"
    assert _visible_buttons(g) == {"Start my library here", start_gate.TRY_AGAIN, start_gate.QUIT}
    assert g.fresh_button.property("kind") == "primary" and g.try_button.property("kind") is None
    tip = g.fresh_button.toolTip()
    assert "Already have a library on a drive or online?" in tip and "Try again" in tip
    g.fresh_button.click()
    assert wait_until(lambda: g.ended)
    assert g.result is True and fake.calls == [{"state": first_run.LIBRARY_NEW, "source": None, "fresh": True}]


def test_enter_on_the_welcome_step_starts_the_library_and_nowhere_else(qapp, monkeypatch):
    # WZ-9 (c): Enter is *Start my library here* on the welcome step only — on the refusal for a library that isn't
    # there, Enter must never make an empty one (D3: only the user's own click does).
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.LIBRARY_MISSING))
    QTest.keyClick(g, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert fake.calls == [] and not g.ended
    g.finish(False)
    g = _gate(qapp, _st(first_run.LIBRARY_NEW, create=True))
    QTest.keyClick(g, Qt.Key.Key_Return)
    assert wait_until(lambda: g.ended)
    assert g.result is True and fake.calls == [{"state": first_run.LIBRARY_NEW, "source": None, "fresh": True}]


def test_a_missing_library_made_new_is_the_users_explicit_choice(qapp, monkeypatch):
    # AD-7: a library removed on purpose is no longer a dead end.
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.LIBRARY_MISSING))
    assert g.fresh_button.text() == start_gate.NEW_HERE and g.fresh_button.toolTip() == start_gate.MISSING_NEW_TIP
    g.fresh_button.click()
    assert wait_until(lambda: g.ended)
    assert fake.calls == [{"state": first_run.LIBRARY_MISSING, "source": None, "fresh": True}]


def test_a_library_folder_holding_a_program_is_refused_with_what_to_do(qapp, monkeypatch):
    # AD-8: never worked in; moving the program out and Try again gets the user in.
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.HOLDS_PROGRAM))
    assert g.screen == "program" and fake.calls == []
    assert g.heading.text() == start_gate.PROGRAM_HEADING and g.st["library"] in g.line.text()
    assert _visible_buttons(g) == {start_gate.TRY_AGAIN, start_gate.QUIT}


def test_an_unfinished_import_whose_old_folder_is_gone_offers_two_ways_out(qapp, monkeypatch, tmp_path):
    # AD-3 (a): Try again can't fix it; choose where it is now, or start fresh keeping what was copied.
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    st = _st(first_run.IMPORT_UNFINISHED, source="D:\\旧すらすら", lost=True)
    g = _gate(qapp, st)
    assert g.screen == "lost" and fake.calls == [] and "D:\\旧すらすら" in g.line.text()
    assert _visible_buttons(g) == {start_gate.CHOOSE_AGAIN, start_gate.FRESH_KEEP, start_gate.TRY_AGAIN,
                                   start_gate.QUIT}
    moved = str(tmp_path / "移動した 旧すらすら")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: moved))
    monkeypatch.setattr(import_2x, "check_source", lambda folder: {"ok": True, "reason": None, "message": None})
    g.choose_button.click()
    assert wait_until(lambda: g.ended)
    assert fake.calls == [{"state": first_run.IMPORT_UNFINISHED, "source": os.path.normpath(moved), "fresh": False}]

    fake2 = FakeRun()
    monkeypatch.setattr(first_run, "run", fake2)
    g2 = _gate(qapp, st)
    g2.fresh_button.click()
    assert wait_until(lambda: g2.ended)
    assert fake2.calls == [{"state": first_run.IMPORT_UNFINISHED, "source": None, "fresh": True}]


def test_try_again_on_an_unfinished_import_that_finds_its_folder_gone_shows_the_ways_out(qapp, monkeypatch):
    said = "The folder D:\\旧すらすら isn't there."
    monkeypatch.setattr(first_run, "run", FakeRun({"status": "refused", "reason": "missing", "message": said}))
    monkeypatch.setattr(first_run, "state", lambda: _st(first_run.IMPORT_UNFINISHED, source="D:\\旧すらすら"))
    g = _gate(qapp, _st(first_run.IMPORT_UNFINISHED, source="D:\\旧すらすら"))
    g.try_button.click()
    assert wait_until(lambda: g.screen == "lost")
    assert start_gate.FRESH_KEEP in _visible_buttons(g) and not g.ended


def test_an_import_refused_for_its_folder_offers_start_fresh(qapp, monkeypatch):
    # AD-3 (b): `same_folder` never changes on Try again; the ask screen's Start fresh is the way out.
    said = "Choose a library folder outside your old Surasura folder."
    fake = FakeRun({"status": "refused", "reason": "same_folder", "message": said})
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.IMPORT, source="D:\\Documents"))
    assert wait_until(lambda: g.screen == "ask")
    assert g.line.text() == said and start_gate.FRESH in _visible_buttons(g)
    fake.result = {"status": "done", "reason": None, "message": None}
    g.fresh_button.click()
    assert wait_until(lambda: g.ended)
    assert fake.calls[-1] == {"state": first_run.ASK_FOLDER, "source": None, "fresh": True}


def test_several_2x_installs_are_each_named_and_the_one_picked_is_brought_over(qapp, monkeypatch):
    # AD-1 (D11: several -> the user picks).
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    checked = []
    monkeypatch.setattr(import_2x, "check_source",
                        lambda folder: checked.append(folder) or {"ok": True, "reason": None, "message": None})
    installs = [{"data_root": "C:\\Users\\me\\Downloads\\Surasura 2.5", "version": "2.5.0",
                 "last_run": "2026-10-09T08:00:00"},
                {"data_root": "D:\\すらすら", "version": "2.4.0", "last_run": "2026-10-01T21:00:00"}]
    g = _gate(qapp, _st(first_run.ASK_FOLDER, installs=installs))
    assert g.screen == "ask" and g.line.text() == start_gate.ASK_SEVERAL_LINE
    shown = [b for b in g.pick_buttons if b.isVisible()]
    assert [b.text() for b in shown] == [
        start_gate.INSTALL_LABEL.format(folder=i["data_root"], version=i["version"], when=i["last_run"][:10])
        for i in installs]
    assert g.choose_button.text() == start_gate.CHOOSE_OTHER and fake.calls == []
    found, _count = problems(g)
    assert found == []
    shown[1].click()
    assert wait_until(lambda: g.ended)
    assert checked == ["D:\\すらすら"]
    assert fake.calls == [{"state": first_run.ASK_FOLDER, "source": "D:\\すらすら", "fresh": False}]


def test_an_import_made_into_another_library_is_named_on_the_ask(qapp, monkeypatch):
    # AD-4: asked again, with where the earlier import went.
    monkeypatch.setattr(first_run, "run", FakeRun())
    note = {"to": "C:\\dev\\surasura", "finished": "2026-10-12T10:00:00", "complete": True}
    g = _gate(qapp, _st(first_run.ASK_FOLDER, elsewhere=note,
                        installs=[{"data_root": "D:\\すらすら", "version": "2.5.0", "last_run": "2026-10-05T21:00"}]))
    assert g.line.text() == start_gate.ELSEWHERE_LINE.format(folder="C:\\dev\\surasura", when="2026-10-12")


def test_slow_quiet_work_shows_that_the_library_is_being_got_ready(qapp, monkeypatch):
    # AD-10: the merge can wait seconds on the known-words lock; a start with nothing on screen looks dead.
    release = threading.Event()

    def slow(st, progress=None, cancel=None, source=None, fresh=False):
        release.wait(5)
        return {"status": "done", "reason": None, "message": None}
    monkeypatch.setattr(first_run, "run", slow)
    monkeypatch.setattr(start_gate, "QUIET_SHOW", 0.05)
    g = _gate(qapp, _st(first_run.READY, lists=["ja"]))
    assert g.screen is None
    assert wait_until(lambda: g.screen == "preparing")
    assert g.isVisible() and g.heading.text() == start_gate.GETTING_READY
    release.set()
    assert wait_until(lambda: g.ended) and g.result is True


def test_the_blocked_screens_try_again_says_no_restart_is_needed(qapp, monkeypatch):
    # AD-12: the CFA sentence ends "restart Surasura"; Try again works once Surasura is allowed.
    message = import_2x.CFA_MESSAGE.format(folder="D:\\ライブラリ", exe="Surasura.exe")
    monkeypatch.setattr(first_run, "run", FakeRun({"status": "blocked", "reason": "access_denied", "message": message}))
    g = _gate(qapp, _st(first_run.READY, create=True))
    assert wait_until(lambda: g.screen == "blocked")
    assert g.try_button.toolTip() == start_gate.BLOCKED_TRY_TIP
    g.show_screen("missing")
    assert g.try_button.toolTip() == start_gate.TRY_AGAIN_TIP


def test_a_quiet_start_that_breaks_never_says_an_import_stopped(qapp, monkeypatch):
    # Haiku safety 4: no import ran, so the import's heading would mislead.
    def broken(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(first_run, "run", broken)
    g = _gate(qapp, _st(first_run.READY, lists=["ja"]))
    assert wait_until(lambda: g.screen == "stopped")
    assert g.heading.text() == start_gate.READY_STOPPED_HEADING and "disk gone" in g.line.text()


def test_quit_quits(qapp, monkeypatch):
    monkeypatch.setattr(first_run, "run", FakeRun())
    g = _gate(qapp, _st(first_run.LIBRARY_MISSING))
    g.quit_button.click()
    assert g.ended and g.result is False


def test_esc_does_nothing_and_the_close_box_is_quit(qapp, monkeypatch):
    monkeypatch.setattr(first_run, "run", FakeRun())
    g = _gate(qapp, _st(first_run.LIBRARY_MISSING))
    QTest.keyClick(g, Qt.Key.Key_Escape)
    g.try_button.setFocus()
    QTest.keyClick(g.try_button, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert g.isVisible() and not g.ended
    g.close()
    assert g.ended and g.result is False


def test_quitting_mid_import_waits_for_the_import_to_stop_first(qapp, monkeypatch):
    fake = FakeRun(hold=True)
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.IMPORT, source="D:\\旧すらすら"))
    assert fake.started.wait(5)
    g.close()                                             # ✕ while it copies
    assert not g.ended and g.quit_after
    assert wait_until(lambda: g.ended)
    assert g.result is False


# --- the folder ask -------------------------------------------------------------------------------------------------

def test_choose_the_old_folder_checks_it_and_brings_it_over(qapp, monkeypatch, tmp_path):
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    chosen = str(tmp_path / "旧すらすら 2.4")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: chosen))
    checks = [{"ok": False, "reason": "running", "message": "Your old Surasura is still open. Close it, then try again."},
              {"ok": True, "reason": None, "message": None}]
    monkeypatch.setattr(import_2x, "check_source", lambda folder: checks.pop(0))
    g = _gate(qapp, _st(first_run.ASK_FOLDER))
    assert g.screen == "ask" and _visible_buttons(g) == {start_gate.CHOOSE, start_gate.FRESH, start_gate.QUIT}
    g.choose_button.click()
    assert wait_until(lambda: g.line.text().startswith("Your old Surasura is still open"))
    assert g.screen == "ask" and fake.calls == []
    g.choose_button.click()
    assert wait_until(lambda: g.ended)
    assert g.result is True and fake.calls == [{"state": first_run.ASK_FOLDER, "source": os.path.normpath(chosen),
                                                "fresh": False}]


def test_a_cancelled_folder_picker_changes_nothing(qapp, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    g = _gate(qapp, _st(first_run.ASK_FOLDER))
    g.choose_button.click()
    QApplication.processEvents()
    assert g.screen == "ask" and fake.calls == [] and g.choose_button.isEnabled()


def test_start_fresh_goes_on_with_an_empty_library(qapp, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.ASK_FOLDER))
    g.fresh_button.click()
    assert wait_until(lambda: g.ended)
    assert g.result is True and fake.calls == [{"state": first_run.ASK_FOLDER, "source": None, "fresh": True}]


# --- every control, and the loop ------------------------------------------------------------------------------------

def test_every_button_is_wired_tipped_and_named(qapp, monkeypatch):
    monkeypatch.setattr(first_run, "run", FakeRun())
    g = _gate(qapp, _st(first_run.ASK_FOLDER))
    found, count = problems(g)
    assert found == [] and count == 5
    for name in ("new", "missing", "lost", "program", "blocked"):
        g.show_screen(name, "…")
        assert problems(g)[0] == [], name


def test_the_gate_runs_until_its_answer_and_leaves_the_loop_as_it_found_it(qapp, monkeypatch):
    monkeypatch.setattr(first_run, "state", lambda: _st(first_run.LIBRARY_MISSING))
    monkeypatch.setattr(first_run, "run", FakeRun())
    keep = qapp.quitOnLastWindowClosed()

    def press_quit():
        gates = [w for w in qapp.topLevelWidgets() if isinstance(w, start_gate.Gate) and w.isVisible()]
        if gates:
            gates[0].quit_button.click()
        else:
            QTimer.singleShot(20, press_quit)
    QTimer.singleShot(20, press_quit)
    assert start_gate.gate(qapp) is False
    assert qapp.quitOnLastWindowClosed() == keep


def test_a_real_2x_install_is_brought_over_through_the_gate(qapp, monkeypatch, tmp_path):
    from tests.test_import_2x import _old_install
    old = _old_install(tmp_path, store=False, languages=("ja",))
    library = os.environ["SURASURA_TEST_ROOT"]
    monkeypatch.setattr(path_utils, "installed_library", lambda: library)
    assert first_run.state()["state"] == first_run.IMPORT
    assert start_gate.gate(qapp) is True
    note = import_2x.read_import_note()
    assert note["complete"] is True and note["from"] == old
    assert os.path.isfile(os.path.join(library, "User Files", "ja", "KnownWord.json"))
    assert start_gate.gate(qapp) is True and not first_run.needs_run(first_run.state())


def test_enter_on_the_welcome_step_presses_the_button_the_keyboard_is_on(qapp, monkeypatch):
    # Tabbed to Quit, Enter quits: it never makes a library the learner didn't ask for.
    fake = FakeRun()
    monkeypatch.setattr(first_run, "run", fake)
    g = _gate(qapp, _st(first_run.LIBRARY_NEW, create=True))
    g.activateWindow()
    g.quit_button.setFocus()
    monkeypatch.setattr(g, "focusWidget", lambda: g.quit_button)
    QTest.keyClick(g, Qt.Key.Key_Return)
    assert wait_until(lambda: g.ended)
    assert g.result is False and fake.calls == []
