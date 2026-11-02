"""The start gate's *Start over* / *Put back* screens (Fresh library 3.0.1, WP5's window half; the spec §3.3, §6.3–6.5,
P5, P10, P16; `app/qt/start_gate.py`'s `move-*` screens over `first_run.run(move=True)`), and the window's start order
(R2: nothing writes a place a Start over moves before the gate ran).

What a wrong answer would cost a learner:
  * a Start over that runs on a start he didn't ask for (the PC turned off before the restart: P16 asks first);
  * a window opened over a half-moved profile (a rename that couldn't be put back: `stuck` never opens it);
  * a refusal or a wait that leaves him on a screen with no way on (*Not now*, *Try again*, *Quit*);
  * a start that writes into the places being moved before the move ran (the move then fails, or moves new files).

The screens are driven against a stand-in `first_run.run` (its answers as `profile_reset.run` gives them); one start
runs the real move through `gate()` on a real profile (test_profile_reset's), end to end. Every path under the test's
own root.
"""
import os
import time

import pytest

pytest.importorskip("PyQt6")

from app import locks, path_utils, profile_reset
from app.qt import start_gate
from app.services import first_run
from tests.qt.conftest import wait_until


@pytest.fixture(autouse=True)
def _no_mark_of_our_own():
    yield
    while locks._mark:
        locks.release_running()
    profile_reset.cancel_request()


def _st(status="asked", action="start-over"):
    return {"state": first_run.PROFILE_MOVE, "library": os.environ["SURASURA_TEST_ROOT"], "installed": False,
            "create": False, "recorded": True, "source": None, "installs": [], "note": None, "lists": [],
            "journal": {"action": action, "status": status, "path": "X:/profile-move.json"}}


class FakeMove:
    """`first_run.run` as the gate calls it for a move: records `move`, says `on_wait` when told to, answers as told."""

    def __init__(self, *answers, wait=None):
        self.answers = list(answers) or [{"status": "done"}]
        self.calls = []
        self.wait = wait

    def __call__(self, st, progress=None, cancel=None, source=None, fresh=False, restart=False, move=False,
                 on_wait=None):
        self.calls.append(move)
        if self.wait is not None and on_wait is not None:
            on_wait(self.wait)
            deadline = time.monotonic() + 5
            while not cancel.is_set() and time.monotonic() < deadline:
                time.sleep(0.01)
            return {"status": "refused", "reason": "running", "message": None,
                    "move": {"status": "refused", "reason": "running", "words": "Connect is still running"}}
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return {"status": "done" if answer["status"] in ("done", "rolled-back", "undone", "none") else
                answer["status"], "reason": answer.get("reason"), "message": answer.get("words"),
                "move": dict({"reason": None, "words": None, "part": None, "holder": None}, **answer)}


def _ready(monkeypatch):
    """After the move: the start's state is an everyday one (the window opens)."""
    st = {"state": first_run.READY, "library": os.environ["SURASURA_TEST_ROOT"], "installed": False, "create": False,
          "recorded": True, "lists": [], "journal": None}
    monkeypatch.setattr(first_run, "state", lambda: dict(st))


def _shown(g):
    return {b.text() for b in (g.choose_button, g.fresh_button, g.try_button, g.cancel_button, g.quit_button)
            if b.isVisible()}


def test_the_restarts_own_start_runs_the_move_and_the_window_opens(qapp, monkeypatch):
    fake = FakeMove()
    monkeypatch.setattr(first_run, "run", fake)
    _ready(monkeypatch)
    g = start_gate.Gate(qapp, _st(), move=True)
    g.start()
    assert wait_until(lambda: g.ended, 5)
    assert g.result is True and fake.calls == [True]
    assert g.screen != "move-moving", "a quick move shows nothing (its line only past QUIET_SHOW)"


def test_a_request_found_on_a_plain_start_is_asked_never_run(qapp, monkeypatch):
    # P16: the restart never came (the PC was turned off): the gate asks
    fake = FakeMove()
    monkeypatch.setattr(first_run, "run", fake)
    _ready(monkeypatch)
    g = start_gate.Gate(qapp, _st(), move=False)
    g.start()
    assert g.screen == "move-ask" and fake.calls == []
    assert g.heading.text() == start_gate.MOVE_ASK_HEADING["start-over"]
    assert _shown(g) == {start_gate.MOVE_NOW["start-over"], start_gate.MOVE_KEEP, start_gate.QUIT}
    assert all(b.toolTip() for b in (g.choose_button, g.fresh_button, g.quit_button))
    profile_reset.request(profile_reset.START_OVER)
    g.fresh_button.click()                                            # *No, keep everything*: the request goes
    assert profile_reset.pending() is None
    assert wait_until(lambda: g.ended, 5) and g.result is True and fake.calls == []


def test_yes_on_a_plain_start_runs_it(qapp, monkeypatch):
    fake = FakeMove()
    monkeypatch.setattr(first_run, "run", fake)
    _ready(monkeypatch)
    profile_reset.request(profile_reset.PUT_BACK, "20261030-154000")
    g = start_gate.Gate(qapp, _st(action="put-back"), move=False)
    g.start()
    assert g.heading.text() == start_gate.MOVE_ASK_HEADING["put-back"]
    g.choose_button.click()                                           # *Put it back now*
    assert wait_until(lambda: g.ended, 5) and fake.calls == [True]


def test_another_program_is_waited_for_said_and_not_now_opens_the_window_as_it_was(qapp, monkeypatch):
    fake = FakeMove(wait=[{"kind": "connect", "pid": 4242}])
    monkeypatch.setattr(first_run, "run", fake)
    _ready(monkeypatch)
    g = start_gate.Gate(qapp, _st(), move=True)
    g.start()
    assert wait_until(lambda: g.screen == "move-waiting", 5)
    assert g.heading.text() == start_gate.MOVE_WAITING.format(who="Connect") and g.bar.isVisible()
    assert _shown(g) == {start_gate.MOVE_NOT_NOW}
    g.fresh_button.click()                                            # *Not now*: the wait ends, nothing moved
    assert wait_until(lambda: g.ended, 5) and g.result is True


@pytest.mark.parametrize("answer, screen", [
    ({"status": "refused", "reason": "update", "words": profile_reset.REFUSED_UPDATE}, "move-didnt"),
    ({"status": "undone", "reason": "held", "words": profile_reset.REFUSED_HELD.format(what="your settings")},
     "move-didnt"),
])
def test_a_move_that_didnt_run_says_why_with_try_again_and_not_now(qapp, monkeypatch, answer, screen):
    fake = FakeMove(answer, {"status": "done"})
    monkeypatch.setattr(first_run, "run", fake)
    _ready(monkeypatch)
    profile_reset.request(profile_reset.START_OVER)
    g = start_gate.Gate(qapp, _st(), move=True)
    g.start()
    assert wait_until(lambda: g.screen == screen, 5)
    assert g.heading.text() == start_gate.MOVE_DIDNT_HEADING["start-over"] and g.line.text() == answer["words"]
    assert _shown(g) == {start_gate.TRY_AGAIN, start_gate.MOVE_NOT_NOW, start_gate.QUIT}
    assert not g.ended
    g.try_button.click()                                              # *Try again*: the move again
    assert wait_until(lambda: g.ended, 5) and fake.calls == [True, True]


def test_an_undone_move_asked_again_writes_its_request_again_first(qapp, monkeypatch):
    fake = FakeMove({"status": "undone", "reason": "held", "words": "held"}, {"status": "done"})
    monkeypatch.setattr(first_run, "run", fake)
    _ready(monkeypatch)
    g = start_gate.Gate(qapp, _st(), move=True)
    g.start()
    assert wait_until(lambda: g.screen == "move-didnt", 5)
    assert profile_reset.pending() is None                            # (undone: the request went with it)
    g.try_button.click()
    assert profile_reset.pending()["action"] == profile_reset.START_OVER
    assert wait_until(lambda: g.ended, 5)


def test_not_now_after_a_refusal_keeps_the_request_and_opens_the_window(qapp, monkeypatch):
    fake = FakeMove({"status": "refused", "reason": "update", "words": profile_reset.REFUSED_UPDATE})
    monkeypatch.setattr(first_run, "run", fake)
    profile_reset.request(profile_reset.START_OVER)
    g = start_gate.Gate(qapp, _st(), move=True)
    g.start()
    assert wait_until(lambda: g.screen == "move-didnt", 5)
    g.fresh_button.click()
    assert g.ended and g.result is True
    assert profile_reset.pending()["status"] == profile_reset.ASKED, "asked again at the next start"


def test_a_move_stopped_part_way_was_rolled_back_and_says_so(qapp, monkeypatch):
    fake = FakeMove({"status": "rolled-back", "reason": "stopped"})
    monkeypatch.setattr(first_run, "run", fake)
    _ready(monkeypatch)
    g = start_gate.Gate(qapp, _st(status="moving"), move=False)        # a kill's journal: settled on any start
    g.start()
    assert wait_until(lambda: g.screen == "move-rolled", 5)
    assert g.heading.text() == start_gate.MOVE_ROLLED_HEADING["start-over"]
    assert g.line.text() == start_gate.MOVE_ROLLED_LINE
    g.fresh_button.click()                                            # *Open Surasura*
    assert wait_until(lambda: g.ended, 5) and g.result is True


def test_a_move_that_cant_be_put_back_never_opens_the_window(qapp, monkeypatch):
    words = profile_reset.STUCK.format(what="your settings")
    fake = FakeMove({"status": "stuck", "reason": "stuck", "words": words})
    monkeypatch.setattr(first_run, "run", fake)
    g = start_gate.Gate(qapp, _st(status="moving"), move=False)
    g.start()
    assert wait_until(lambda: g.screen == "move-stuck", 5)
    assert g.line.text() == words and _shown(g) == {start_gate.TRY_AGAIN, start_gate.QUIT}
    g.quit_button.click()
    assert g.ended and g.result is False


def test_a_note_that_cant_be_read_is_set_aside_only_on_the_learners_word(qapp, monkeypatch):
    os.makedirs(path_utils.get_local_data_path(), exist_ok=True)
    with open(profile_reset.journal_path(), "w", encoding="utf-8") as f:
        f.write("{not json")
    _ready(monkeypatch)
    g = start_gate.Gate(qapp, dict(_st(), journal=profile_reset.pending()), move=True)
    g.start()
    assert g.screen == "move-unreadable" and os.path.exists(profile_reset.journal_path())
    assert _shown(g) == {start_gate.MOVE_SET_ASIDE, start_gate.QUIT}
    g.fresh_button.click()
    assert not os.path.exists(profile_reset.journal_path())
    assert [n for n in os.listdir(path_utils.get_local_data_path()) if ".unreadable-" in n]
    assert wait_until(lambda: g.ended, 5) and g.result is True


def test_esc_closes_nothing_on_a_move_screen(qapp, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    monkeypatch.setattr(first_run, "run", FakeMove())
    g = start_gate.Gate(qapp, _st(), move=False)
    g.start()
    QTest.keyClick(g, Qt.Key.Key_Escape)
    assert not g.ended and g.screen == "move-ask"
    g.quit_button.click()


# --- end to end: the real move through `gate()` ----------------------------------------------------------------- #
def test_gate_on_the_restarts_own_start_moves_the_profile_aside_and_a_plain_start_only_asks(qapp, monkeypatch):
    from tests.test_profile_reset import _profile
    _profile()
    settings = path_utils.get_settings_path()
    assert os.path.exists(settings)
    profile_reset.request(profile_reset.START_OVER)
    plain = {}
    real_init = start_gate.Gate.__init__

    def init(self, *a, **kw):
        real_init(self, *a, **kw)
        plain["gate"] = self
    monkeypatch.setattr(start_gate.Gate, "__init__", init)

    def answer_no():                                               # the plain start's question, answered Quit
        g = plain.get("gate")
        if g is not None and g.screen == "move-ask":
            g.quit_button.click()
            return True
        return False
    from PyQt6.QtCore import QTimer
    timer = QTimer()
    timer.timeout.connect(answer_no)
    timer.start(50)
    try:
        assert start_gate.gate(qapp, move=False) is False
    finally:
        timer.stop()
    assert os.path.exists(settings) and profile_reset.pending()["status"] == profile_reset.ASKED   # nothing moved
    assert start_gate.gate(qapp, move=True) is True
    assert not os.path.exists(settings), "set aside before anything opened"
    assert profile_reset.pending() is None
    backups = profile_reset.backups()
    assert backups and backups[0]["kind"] == profile_reset.STARTED_OVER


# --- R2: the window's start order --------------------------------------------------------------------------------- #
def _moving_tree():
    """Every file under a part a Start over moves, with its size and time (what must not change before the gate)."""
    out = {}
    for part in path_utils.profile_parts():
        if part["start_over"] != path_utils.MOVES:
            continue
        top = part["path"]
        if os.path.isfile(top):
            st = os.stat(top)
            out[top] = (st.st_size, st.st_mtime_ns)
        for where, _dirs, names in os.walk(top):
            for n in names:
                p = os.path.join(where, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out[p] = (st.st_size, st.st_mtime_ns)
    return out


def test_the_window_writes_nothing_a_start_over_moves_before_its_gate_ran(qapp, monkeypatch):
    # R2 at the shell's level: the QApplication, the one-window claim and the process setup all come before the
    # gate; none of them may write a place the gate is about to move (`after_gate`: telemetry, only after it)
    from tests.test_profile_reset import _profile
    from app.qt import shell
    _profile()
    profile_reset.request(profile_reset.START_OVER)
    before = _moving_tree()
    assert len(before) > 10, "a profile to move"
    parts_before = {p["path"] for p in path_utils.profile_parts() if p["start_over"] == path_utils.MOVES}
    seen = {}

    def gate(app, move=False):
        seen["tree"] = _moving_tree()
        seen["parts"] = {p["path"] for p in path_utils.profile_parts() if p["start_over"] == path_utils.MOVES}
        seen["move"] = move
        return False                                               # the start ends here: nothing after it runs
    monkeypatch.setattr(start_gate, "gate", gate)
    after = []
    monkeypatch.setenv(shell.MOVE_START, "1")
    assert shell.main(["app_entry.py"], after_gate=lambda: after.append(1)) == 0
    assert seen["move"] is True and after == []
    assert seen["parts"] == parts_before, "no new part appeared before the gate"
    changed = {p for p in set(before) | set(seen["tree"]) if before.get(p) != seen["tree"].get(p)}
    assert changed == set(), f"written before the gate: {sorted(changed)}"


def test_only_a_move_restart_carries_the_move_mark_and_it_is_read_once(monkeypatch):
    # P16: a *Restart now* (text size) must never run a Start over asked earlier
    import subprocess
    import sys
    from app.qt import shell
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append(kw["env"]) or object())
    monkeypatch.delattr(sys, "frozen", raising=False)
    shell.relaunch(["app_entry.py"])
    shell.relaunch(["app_entry.py"], move=True)
    assert shell.MOVE_START not in started[0] and started[1][shell.MOVE_START] == "1"
    assert all(env[shell.RESTARTED] == "1" for env in started)
    monkeypatch.setenv(shell.MOVE_START, "1")
    assert shell.move_mark() is True and shell.MOVE_START not in os.environ
    assert shell.move_mark() is False, "read once"


def test_a_relaunch_that_cant_start_is_named_before_the_window_closes(tmp_path, monkeypatch):
    import sys
    from app.qt import shell
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert shell.relaunch_refused([str(tmp_path / "gone.py")]) == f"{tmp_path / 'gone.py'} isn't there"
    there = tmp_path / "app_entry.py"
    there.write_text("", encoding="utf-8")
    assert shell.relaunch_refused([str(there)]) is None


# --- the review's round (F1, F2, F3) ---------------------------------------------------------------------------- #
class WaitThenMove(FakeMove):
    """The wait ends by itself (the other program closed) and the move then answers `answer`."""

    def __init__(self, answer, pressed):
        super().__init__(answer)
        self.pressed = pressed

    def __call__(self, st, progress=None, cancel=None, source=None, fresh=False, restart=False, move=False,
                 on_wait=None):
        self.calls.append(move)
        on_wait([{"kind": "connect"}])
        assert self.pressed.wait(5)                                    # *Not now* pressed after the wait ended
        answer = self.answers[0]
        return {"status": answer["status"], "reason": None, "message": answer.get("words"), "move": answer}


@pytest.mark.parametrize("answer, screen, opens", [
    ({"status": "stuck", "words": "your settings couldn't be put back"}, "move-stuck", False),
    ({"status": "done"}, None, True),
])
def test_not_now_pressed_after_the_wait_ended_follows_the_moves_own_answer(qapp, monkeypatch, answer, screen, opens):
    # F1 (blocker): the window never opens over a move that ran and got stuck; one that ran goes on as done
    import threading
    pressed = threading.Event()
    monkeypatch.setattr(first_run, "run", WaitThenMove(answer, pressed))
    _ready(monkeypatch)
    g = start_gate.Gate(qapp, _st(), move=True)
    g.start()
    assert wait_until(lambda: g.screen == "move-waiting", 5)
    g.fresh_button.click()                                            # *Not now*, too late: the move already ran
    pressed.set()
    if opens:
        assert wait_until(lambda: g.ended, 5) and g.result is True
    else:
        assert wait_until(lambda: g.screen == screen, 5) and not g.ended
        g.quit_button.click()


def test_closing_the_gate_during_the_wait_ends_the_wait_and_quits(qapp, monkeypatch):
    # F2: ✕ during *Waiting for Connect to close…* is "not now": the wait ends, nothing moves, the program quits
    fake = FakeMove(wait=[{"kind": "connect"}])
    monkeypatch.setattr(first_run, "run", fake)
    g = start_gate.Gate(qapp, _st(), move=True)
    g.start()
    assert wait_until(lambda: g.screen == "move-waiting", 5)
    g.close()
    assert wait_until(lambda: g.ended, 3) and g.result is False


def test_a_mover_that_crashed_over_a_journal_in_flight_never_offers_not_now(qapp, monkeypatch):
    # F3: a crash with renames done (journal "moving"): Try again (recover) or Quit, never the window
    def crash(*_a, **_k):
        raise TypeError("a mover bug")
    monkeypatch.setattr(first_run, "run", crash)
    os.makedirs(path_utils.get_local_data_path(), exist_ok=True)
    profile_reset._write_json(profile_reset.journal_path(), {"action": "start-over", "status": "moving", "moves": []})
    g = start_gate.Gate(qapp, _st(status="moving"), move=True)
    g.start()
    assert wait_until(lambda: g.screen == "move-stuck", 5)
    assert _shown(g) == {start_gate.TRY_AGAIN, start_gate.QUIT}
    g.quit_button.click()
    os.remove(profile_reset.journal_path())


def test_a_frozen_program_whose_own_file_is_gone_is_named_before_the_window_closes(tmp_path, monkeypatch):
    import sys
    from app.qt import shell
    # why: a frozen program has no app_entry.py to check, so its own .exe must be the file that is looked for
    exe = tmp_path / "Surasura.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert shell.relaunch_refused([str(exe)]) == f"{exe} isn't there"
    exe.write_text("", encoding="utf-8")
    assert shell.relaunch_refused([str(exe)]) is None
    # why: an empty executable names no file at all, so the message falls back to "the program"
    monkeypatch.setattr(sys, "executable", "")
    assert shell.relaunch_refused([str(exe)]) == "the program isn't there"
