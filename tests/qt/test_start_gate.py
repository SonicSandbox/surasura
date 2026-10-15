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
    assert _visible_buttons(g) == {start_gate.TRY_AGAIN, start_gate.QUIT}
    g.try_button.click()                                  # still offline: the same refusal, nothing run
    assert wait_until(lambda: len(answers) == 1 and g.try_button.isEnabled())
    assert g.screen == "missing" and fake.calls == [] and not g.ended
    g.try_button.click()                                  # back: the start goes on
    assert wait_until(lambda: g.ended)
    assert g.result is True


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
