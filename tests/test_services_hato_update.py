"""hato's own daily update, started by Surasura (`app/services/hato_update.py`, Hato-UP 3.0.18).

What a wrong answer would cost:
  * Surasura replacing hato's files, or asking GitHub itself — hato owns its update: only hato's own commands start;
  * an update started under the learner's open hato or its run, or many a day — the swapper waits on hato's programs,
    and every ask is a download of tens of MB;
  * a dialog or an error for a hato that's absent, old, offline or slow — it must be silent and try tomorrow;
  * Settings saying *up to date* when hato couldn't tell, or *updating* for a hato that already installed it.

hato is a stand-in program file and a fake process starter (the claim is which of hato's commands start, when, and
what is kept): no real hato runs and nothing reaches the network.
"""
import datetime
import json
import os
import subprocess
import sys
import threading

import pytest

from app import tools_entry, updater
from app.services import hato_update as H

DAY = 24 * 3600
NOW = datetime.datetime(2026, 11, 21, 9, 30, tzinfo=datetime.timezone.utc).timestamp()


class _Proc:
    def __init__(self, argv, answers, kw):
        self.argv, self.kw = list(argv), kw
        code, out = answers.get(tuple(argv[1:]), (0, b""))
        self.returncode, self._out = code, out
        self.killed = False

    def communicate(self, timeout=None):
        if isinstance(self._out, BaseException):
            raise self._out
        return self._out, None

    def kill(self):
        self.killed = True


class _Hato(list):
    """The process starter: each start recorded; `answers` {argv after the program: (exit code, stdout)}."""

    def __init__(self, answers=None, refuse=False):
        super().__init__()
        self.answers = answers or {}
        self.refuse = refuse

    def __call__(self, argv, **kw):
        if self.refuse:
            raise OSError("stand-in: Windows refused to start it")
        proc = _Proc(argv, self.answers, kw)
        self.append(proc)
        return proc

    def commands(self):
        return [p.argv[1:] for p in self]


AUTO = ("update", "--auto")
ANSWER = ("update", "--check", "--if-due", "--json")
INSTALL = ("update", "--quiet-install", "--json")


def _line(**fields):
    return (json.dumps(dict({"type": "update", "current": "1.4.2"}, **fields), ensure_ascii=False) + "\n").encode()


def _ready(version="1.5.0", current="1.4.2"):
    """hato's `update --check --json` answer for a release this copy can install, in its full shape (hato
    `commands/update.py`: `Decision.as_dict()` + type + current)."""
    return _line(kind="ready", version=version, reason=None, notes=["Faster finds"], critical=False,
                 page="https://github.com/SonicSandbox/hato/releases/latest",
                 zip_url=f"https://github.com/SonicSandbox/hato/releases/download/v{version}/hato-{version}.zip",
                 size=70254592, current=current)


def _said(kind, version):
    """hato's `update --quiet-install --json` answer (hato 1.4.3, `commands/update.py` `_quiet_install`): `applying`
    once its swapper has the release, else `waiting` (the release staged, or None)."""
    return (json.dumps({"type": kind, "version": version}, ensure_ascii=False) + "\n").encode()


@pytest.fixture
def hato(tmp_path, monkeypatch):
    """A hato installed where its tools entry says (its `cli` a real file), none of its programs running, the update
    check allowed (the suite's gate lifted: every start here is the fake)."""
    folder = tmp_path / "ツール" / "hato"
    folder.mkdir(parents=True)
    cli = folder / ("hato-cli.exe" if sys.platform == "win32" else "hato-cli")
    cli.write_bytes(b"")
    monkeypatch.setattr(tools_entry, "read", lambda tool: {"cli": str(cli), "version": "1.4.2"} if tool == "hato"
                        else None)
    monkeypatch.setattr(updater, "_processes_running", lambda images: {})
    monkeypatch.delenv(H.NO_CHECK_ENV, raising=False)
    return str(cli)


def _state():
    with open(H.path(), encoding="utf-8") as f:
        return json.load(f)


# --- what starts ------------------------------------------------------------------------------------------------- #
def test_the_days_update_starts_hatos_own_auto_then_reads_its_answer(hato):
    """hato's own two commands, in order, hidden and below normal priority; Surasura asks GitHub nothing itself."""
    fake = _Hato({ANSWER: (0, _line(kind="none", version="1.4.2"))})
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    assert fake.commands() == [list(AUTO), list(ANSWER)]
    assert all(p.argv[0] == hato for p in fake)
    # --auto prints nothing: no pipe it could fill (and stall on) once Surasura stops waiting; the answer is read
    assert fake[0].kw["stdout"] == subprocess.DEVNULL and fake[1].kw["stdout"] == subprocess.PIPE
    for p in fake:
        assert p.kw["stdin"] == subprocess.DEVNULL and p.kw["stderr"] == subprocess.DEVNULL
        assert p.kw["cwd"] == os.path.dirname(hato)
        if sys.platform == "win32":
            from app.connect import power
            assert p.kw["creationflags"] & power.BELOW_NORMAL_PRIORITY_CLASS
            assert p.kw["creationflags"] & 0x08000000            # CREATE_NO_WINDOW: never a console
    kept = _state()
    assert kept["answer"]["kind"] == "none" and kept["answer"]["version"] == "1.4.2"
    assert H.status("1.4.2") == (H.UP_TO_DATE, None)


def test_once_a_day_then_due_again_and_a_clock_set_back_is_due(hato):
    fake = _Hato({ANSWER: (0, _line(kind="none", version="1.4.2"))})
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    assert H.attempt({}, now=NOW + 3600, popen=fake) == H.NOT_DUE
    assert H.attempt({}, now=NOW + DAY - 1, popen=fake) == H.NOT_DUE
    assert len(fake) == 2                                       # one day: one --auto, one answer
    assert H.attempt({}, now=NOW + DAY, popen=fake) == H.DONE
    assert len(fake) == 4
    assert H.attempt({}, now=NOW - 3600, popen=fake) == H.DONE  # the clock went back: never trusted as "today"


def test_the_attempt_is_claimed_before_hato_starts(hato):
    """A window closed mid-way (or a second window) finds the day's attempt made: the claim is written first."""
    seen = []

    class Watching(_Hato):
        def __call__(self, argv, **kw):
            seen.append(_state().get("tried_at"))
            return super().__call__(argv, **kw)
    H.attempt({}, now=NOW, popen=Watching({ANSWER: (0, _line(kind="none", version="1.4.2"))}))
    assert seen and seen[0] == "2026-11-21T09:30:00Z"


# --- when it waits ------------------------------------------------------------------------------------------------ #
def test_hato_open_waits_and_claims_nothing(hato, monkeypatch):
    """One of hato's programs running from its folder (window, tray, a run, its updater): look again later; the day's
    attempt is not spent, nothing starts. The look asks for hato's four programs in its own folder."""
    asked = []

    def running(images):
        asked.append(sorted(os.path.basename(i) for i in images))
        return {4242: images[0]}
    monkeypatch.setattr(updater, "_processes_running", running)
    fake = _Hato()
    assert H.attempt({}, now=NOW, popen=fake) == H.WAIT
    assert fake == [] and not os.path.exists(H.path())
    ext = ".exe" if sys.platform == "win32" else ""
    assert asked == [sorted(n + ext for n in H.PROGRAMS)]
    monkeypatch.setattr(updater, "_processes_running", lambda images: {})
    assert H.attempt({}, now=NOW + 300, popen=fake) == H.DONE  # hato closed: the next look goes


def test_a_process_list_that_fails_counts_as_open(hato, monkeypatch):
    def broken(images):
        raise OSError("stand-in: the snapshot failed")
    monkeypatch.setattr(updater, "_processes_running", broken)
    fake = _Hato()
    assert H.attempt({}, now=NOW, popen=fake) == H.WAIT and fake == []


def test_surasuras_own_hato_run_waits(hato):
    from app import no_subs
    fake = _Hato()
    with no_subs._find_lock:
        assert no_subs.finding()
        assert H.attempt({}, now=NOW, popen=fake) == H.WAIT
    assert fake == [] and not no_subs.finding()


def test_the_schedulers_turn_waits(hato, monkeypatch):
    """`gentle.hold` names a reason (the window still opening, a busy PC, a heavy job's turn)."""
    from app.services import gentle
    monkeypatch.setattr(gentle, "hold", lambda kind: gentle.BUSY_NOW if kind == H.KIND else None)
    fake = _Hato()
    assert H.attempt({}, now=NOW, popen=fake) == H.WAIT and fake == []


def test_hato_update_is_background_work_for_the_scheduler():
    """Its kind is the scheduler's background: held before the boot and on a busy PC (never for a review in Anki:
    OPEN 30) — never HEAVY (a separate program's download is no CPU job of the window's)."""
    from app.services import gentle
    from app.services.jobs import JobRegistry
    assert H.KIND in gentle.BACKGROUND and H.KIND not in gentle.HEAVY
    g = gentle.Gentle(JobRegistry(), machine=lambda: (False, None), load=type("L", (), {"sample": lambda s: None})(),
                      log=lambda line: None)
    g.attach(watch=False)
    try:
        assert gentle.hold(H.KIND) == gentle.WINDOW_FIRST     # booted first
        g.ready()
        assert gentle.hold(H.KIND) is None
        g.busy = True
        assert gentle.hold(H.KIND) == gentle.BUSY_NOW
    finally:
        g.close()


# --- nothing happens ------------------------------------------------------------------------------------------------ #
def test_no_hato_writes_nothing_and_starts_nothing(hato, monkeypatch):
    fake = _Hato()
    monkeypatch.setattr(tools_entry, "read", lambda tool: None)
    assert H.attempt({}, now=NOW, popen=fake) == H.NO_HATO
    monkeypatch.setattr(tools_entry, "read", lambda tool: {"cli": os.path.join(os.path.dirname(hato), "gone.exe")})
    assert H.attempt({}, now=NOW, popen=fake) == H.NO_HATO     # its `cli` gone (uninstalled)
    monkeypatch.setattr(tools_entry, "read", lambda tool: {"version": "1.4.2"})
    assert H.attempt({}, now=NOW, popen=fake) == H.NO_HATO     # an entry naming no program

    def broken(tool):
        raise OSError("stand-in: the tools folder can't be read")
    monkeypatch.setattr(tools_entry, "read", broken)
    assert H.attempt({}, now=NOW, popen=fake) == H.NO_HATO
    assert fake == [] and not os.path.exists(H.path())


def test_check_for_updates_off_or_the_test_gate_asks_nothing(hato, monkeypatch):
    fake = _Hato()
    assert H.attempt({"update_check_enabled": False}, now=NOW, popen=fake) == H.NOT_ALLOWED
    monkeypatch.setenv(H.NO_CHECK_ENV, "1")
    assert H.attempt({}, now=NOW, popen=fake) == H.NOT_ALLOWED
    assert fake == [] and not os.path.exists(H.path())


def test_an_old_hato_with_no_update_command_is_left_alone(hato):
    """Its usage error (exit 2): no second command, remembered so Settings shows its version alone; next day again."""
    fake = _Hato({AUTO: (2, b"")})
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    assert fake.commands() == [list(AUTO)]
    assert _state().get("unsupported") is True and H.status("1.0.2") == (None, None)


# --- a failure is silent, tried tomorrow ------------------------------------------------------------------------------ #
@pytest.mark.parametrize("answers, refuse", [
    ({ANSWER: (0, _line(kind="none", version=None))}, False),          # offline: hato couldn't tell
    ({ANSWER: (0, _line(kind="none", version=None, reason="rate-limited"))}, False),
    ({ANSWER: (0, b"Traceback (most recent call last):\n")}, False),  # no JSON answer
    ({ANSWER: (1, _line(kind="none", version="1.4.2"))}, False),       # it failed
    ({AUTO: (1, b"")}, False),                                         # staging failed: hato's answer still read
    ({}, True),                                                        # Windows refused to start it
])
def test_no_answer_says_couldnt_check_and_the_day_is_spent(hato, answers, refuse):
    fake = _Hato(answers, refuse=refuse)
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    assert H.status("1.4.2") == (H.NO_CHECK, None)
    assert H.attempt({}, now=NOW + 60, popen=fake) == H.NOT_DUE      # tried again tomorrow, not every look


def test_a_slow_hato_is_left_to_finish_and_never_killed(hato):
    """No answer in UPDATE_WAIT_S: Surasura stops waiting; hato's own download is never cut off."""
    fake = _Hato({AUTO: (0, subprocess.TimeoutExpired("hato-cli", H.UPDATE_WAIT_S))})
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    assert fake.commands() == [list(AUTO)] and not fake[0].killed
    assert H.status("1.4.2") == (H.NO_CHECK, None)


def test_any_failure_starting_hato_is_couldnt_check_never_a_blank_row(hato):
    """Not only OSError: a path Windows can't take (ValueError) still leaves an answer kept (*couldn't check*)."""
    class Odd(_Hato):
        def __call__(self, argv, **kw):
            raise ValueError("stand-in: embedded null character in path")
    assert H.attempt({}, now=NOW, popen=Odd()) == H.DONE
    assert H.status("1.4.2") == (H.NO_CHECK, None)


def test_an_answer_that_never_comes_is_stopped_and_couldnt_check(hato):
    """`--check` only tells: one past ANSWER_WAIT_S is stopped (a pipe nobody reads any more), unlike `--auto`."""
    fake = _Hato({ANSWER: (0, subprocess.TimeoutExpired("hato-cli", H.ANSWER_WAIT_S))})
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    assert fake.commands() == [list(AUTO), list(ANSWER)] and not fake[0].killed and fake[1].killed
    assert H.status("1.4.2") == (H.NO_CHECK, None)


def test_the_quit_begun_starts_nothing_and_claims_nothing(hato):
    fake = _Hato()
    assert H.attempt({}, now=NOW, popen=fake, stopped=lambda: True) == H.WAIT
    assert fake == [] and not os.path.exists(H.path())


def test_a_torn_state_is_due_and_one_held_open_is_not(hato):
    os.makedirs(os.path.dirname(H.path()), exist_ok=True)
    with open(H.path(), "w", encoding="utf-8") as f:
        f.write('{"tried_at": "2026-11-21T0')                         # a write cut off
    fake = _Hato({ANSWER: (0, _line(kind="none", version="1.4.2"))})
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    os.remove(H.path())
    os.makedirs(H.path())                                            # there, but can't be opened as a file
    try:
        assert H.attempt({}, now=NOW + 2 * DAY, popen=fake) == H.NOT_DUE
        assert len(fake) == 2
    finally:
        os.rmdir(H.path())


# --- a release hato has for the learner: installed quietly, or waiting for a press ------------------------------------ #
def test_a_release_waiting_for_a_press_in_hato_is_never_updating(hato):
    """A default hato (no tray, no daily run) stages its update from `--auto`, and nothing of hato installs it without
    *Restart now* in its window. An older hato has no quiet install (its usage error, exit 2): the row says the release
    is ready in hato — never *updating…* for days."""
    fake = _Hato({ANSWER: (0, b'{"type": "progress"}\n' + _ready()), INSTALL: (2, b"")})
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    assert fake.commands() == [list(AUTO), list(ANSWER), list(INSTALL)]
    assert H.status("1.4.2") == (H.READY, "1.5.0")
    assert H.status("1.5.0") == (H.UP_TO_DATE, None)                   # the learner pressed it in hato
    assert H.status("1.5.1") == (H.UP_TO_DATE, None)                   # or went past it
    assert H.attempt({}, now=NOW + H.LOOK_S, popen=fake) == H.NOT_DUE  # asked once a day, not every look


@pytest.mark.parametrize("said", [_said("waiting", "1.5.0"), _said("waiting", None), _said("applying", "1.4.9"),
                                  b"", b"Traceback (most recent call last):\n"],
                         ids=["waiting", "nothing-staged", "another-release", "silent", "no-json"])
def test_hato_that_installs_nothing_now_says_ready_in_hato(hato, said):
    """hato 1.4.3 waits (its window or a run open, *Update automatically* off, a tray that installs it itself, a version
    turned away, nothing staged), names another release, or gives no answer: ready in hato, never *updating…*."""
    fake = _Hato({ANSWER: (0, _ready()), INSTALL: (0, said)})
    assert H.attempt({}, now=NOW, popen=fake) == H.DONE
    assert H.status("1.4.2") == (H.READY, "1.5.0")


def test_a_quiet_install_says_updating_then_reads_hatos_answer_once_more(hato):
    """hato 1.4.3 installs what it staged (`applying`: its swapper has it, nothing reopens): *updating…* is true now.
    The next look (LOOK_S on) reads hato's answer again — no `--auto`, no install — and the row follows it; the day's
    attempt stays spent."""
    fake = _Hato({ANSWER: (0, _ready()), INSTALL: (0, _said("applying", "1.5.0"))})
    assert H.attempt({}, now=NOW, popen=fake) == H.INSTALLING
    assert H.status("1.4.2", now=NOW + 60) == (H.UPDATING, "1.5.0")
    assert H.status("1.4.2", now=NOW + H.SAID_S) == (H.READY, "1.5.0")    # never *updating…* past SAID_S unread
    fake.answers[ANSWER] = (0, _line(kind="none", version="1.5.0", current="1.5.0"))
    assert H.attempt({}, now=NOW + H.LOOK_S, popen=fake) == H.DONE
    assert fake.commands() == [list(AUTO), list(ANSWER), list(INSTALL), list(ANSWER)]
    assert "installing" not in _state() and _state()["tried_at"] == "2026-11-21T09:30:00Z"
    assert H.status("1.5.0") == (H.UP_TO_DATE, None)
    # hato's entry still naming the hato before it (nothing of hato started since): hato's own answer says which hato
    # runs, so the release it just installed is never read as one this copy can't install
    assert H.status("1.4.2") == (H.UP_TO_DATE, None)
    assert H.attempt({}, now=NOW + 2 * H.LOOK_S, popen=fake) == H.NOT_DUE


def test_the_second_read_waits_while_hato_is_open_and_a_failed_one_is_couldnt_check(hato, monkeypatch):
    fake = _Hato({ANSWER: (0, _ready()), INSTALL: (0, _said("applying", "1.5.0"))})
    assert H.attempt({}, now=NOW, popen=fake) == H.INSTALLING
    monkeypatch.setattr(updater, "_processes_running", lambda images: {4242: images[0]})
    assert H.attempt({}, now=NOW + H.LOOK_S, popen=fake) == H.WAIT and len(fake) == 3
    monkeypatch.setattr(updater, "_processes_running", lambda images: {})
    fake.answers[ANSWER] = (1, b"")
    assert H.attempt({}, now=NOW + 2 * H.LOOK_S, popen=fake) == H.DONE
    assert H.status("1.4.2") == (H.NO_CHECK, None)                     # never *updating…* left behind


def test_check_for_updates_turned_off_after_a_quiet_install_never_leaves_updating(hato):
    """The second read is an update request too: with *Check for updates* off it isn't made — and the row no longer
    says *updating…* for an install nobody looks at again."""
    fake = _Hato({ANSWER: (0, _ready()), INSTALL: (0, _said("applying", "1.5.0"))})
    assert H.attempt({}, now=NOW, popen=fake) == H.INSTALLING
    assert H.attempt({"update_check_enabled": False}, now=NOW + H.LOOK_S, popen=fake) == H.NOT_ALLOWED
    assert len(fake) == 3
    assert H.status("1.4.2", now=NOW + H.SAID_S) == (H.READY, "1.5.0")


def test_keep_looks_again_soon_after_a_quiet_install(monkeypatch):
    outcomes = iter([H.INSTALLING, H.DONE])
    waits = []

    class Stop:
        def is_set(self):
            return len(waits) >= 2

        def wait(self, seconds):
            waits.append(seconds)
    monkeypatch.setattr(H, "attempt", lambda settings, popen=None, stopped=None: next(outcomes))
    H.keep(lambda: {}, Stop())
    assert waits == [H.LOOK_S, H.IDLE_S]


# --- Settings' words ------------------------------------------------------------------------------------------------- #


def test_a_newer_hato_this_copy_cant_install_is_out(hato):
    fake = _Hato({ANSWER: (0, _line(kind="tell", version="1.5.0", reason="unsigned"))})
    H.attempt({}, now=NOW, popen=fake)
    assert H.status("1.4.2") == (H.OUT, "1.5.0")
    assert fake.commands() == [list(AUTO), list(ANSWER)]               # nothing hato could install: no install asked


@pytest.mark.parametrize("state", [
    {},                                                              # never tried
    {"tried_at": "2026-11-21T09:30:00Z"},                            # claimed, hato still at it
    {"tried_at": "2026-11-21T09:30:00Z", "unsupported": True},
    {"tried_at": "2026-11-21T09:30:00Z", "answer": {"kind": "none", "version": None, "reason": "held"}},
])
def test_nothing_to_say(state):
    """Never tried, still at it, an old hato, or a copy another program holds (its holder moves its version)."""
    assert H.status("1.4.2", state) == (None, None)


@pytest.mark.parametrize("latest", [None, "", "1.5.0rc1", "v1.5.0", "１.５.０", "1.5"])
def test_a_newer_one_named_in_no_version_is_couldnt_check_never_up_to_date(latest):
    """hato names a newer release in its one X.Y.Z shape; anything else can't be compared: never read as up to date."""
    for kind in ("ready", "tell"):
        assert H.status("1.4.2", {"answer": {"kind": kind, "version": latest}}) == (H.NO_CHECK, None)


def test_an_installed_version_that_doesnt_read_says_up_to_date_not_updating():
    """The entry naming no version (\"\"): nothing to compare a newer one with; the row then shows *installed* only."""
    assert H.status("", {"answer": {"kind": "ready", "version": "1.5.0"}}) == (H.UP_TO_DATE, None)


# --- the window's thread ---------------------------------------------------------------------------------------------- #
def test_keep_looks_again_soon_while_it_waits_and_ends_at_the_quit(monkeypatch):
    outcomes = iter([H.WAIT, H.NOT_DUE, H.DONE])
    waits = []

    class Stop:
        def __init__(self):
            self.n = 0

        def is_set(self):
            return self.n >= 3

        def wait(self, seconds):
            waits.append(seconds)
            self.n += 1
    asked = []
    monkeypatch.setattr(H, "attempt", lambda settings, popen=None, stopped=None: asked.append(stopped) or next(outcomes))
    stop = Stop()
    H.keep(lambda: {}, stop)
    assert asked and all(s == stop.is_set for s in asked)           # the quit is asked right before hato starts
    assert waits == [H.LOOK_S, H.IDLE_S, H.IDLE_S]


def test_start_runs_on_a_daemon_thread_that_ends_when_told(monkeypatch):
    looked = threading.Event()
    monkeypatch.setattr(H, "attempt", lambda settings, popen=None, stopped=None: looked.set() or H.NOT_DUE)
    stop = threading.Event()
    thread = H.start(lambda: {}, stop)
    assert thread.daemon and looked.wait(5)
    stop.set()
    thread.join(5)
    assert not thread.is_alive()
