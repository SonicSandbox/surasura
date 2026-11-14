"""Piyo steps aside for an update (Piyo-UP, a tester's 3.0.6 report; based on the approach in #420 by Mattias).

The learner's AI app keeps `surasura-cli mcp` for as long as its session lives — Claude Code one a session, for days —
and the process holds Surasura's `<data name>.Running` mutex (Setup's AppMutex) and its own program file, so an update
waited until the learner ended every surasura-cli.exe by hand. Now it steps aside as Connect does
(`mcp_server.step_aside`): an update staged (`library_store.update_staged`, Connect's own signal), another build in its
program folder, or Setup run by hand ends it — no new call starts, a write under way always finishes.

What a wrong answer would cost: an update blocked until the learner hunts processes down (the report); the other way,
a translation write or a saved round cut part way, a call's answer lost, or a server ending with no update at all.
"""
import os
import subprocess
import sys
import threading
import time

import pytest

from app import build_info, library_store, locks
from app.cli import mcp_server

pytest.importorskip("mcp")
import anyio  # noqa: E402  (mcp's own dependency)
from mcp import Client  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _state():
    state = mcp_server.ServerState()
    state.default_language = lambda: "ja"
    return state


def _text(result):
    return result.content[0].text


def _error(result):
    return result.is_error if hasattr(result, "is_error") else result.isError


def _stage_marker():
    """The updater's marker, as its hand-over writes it (`library_store.update_staged_path`)."""
    path = library_store.update_staged_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{}")
    return path


def _until(test, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not test():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


# --- the look: when it ends, and never before ------------------------------------------------------------------ #
def test_it_ends_once_two_looks_in_a_row_name_the_reason_never_before():
    """Two quiet looks, a reason seen once (a stamp read amid a virus scan), quiet, then an update at two looks in a
    row: it ends there — once."""
    staged = "an update is staged"
    answers = iter([None, None, "another build is in its program folder", None, staged, staged])
    looks, ended, waits = [], [], []

    def why():
        looks.append(time.monotonic())
        return next(answers)
    reason = mcp_server.step_aside(why=why, calls=mcp_server.Calls(), sleep=waits.append,
                                   end=lambda: ended.append(True))
    assert reason == staged
    assert len(looks) == 6 and ended == [True]
    # the first look at once, then one every LOOK_EVERY_S, then a moment for the last answer to reach the AI app
    assert waits == [mcp_server.LOOK_EVERY_S] * 5 + [mcp_server.ANSWER_GRACE_S]


def test_it_still_ends_when_something_on_the_way_out_fails(monkeypatch):
    """A server that refuses every call and keeps the mutex would be the report again: the end is in a finally."""
    def boom():
        raise OSError("the log's disk went away")
    monkeypatch.setattr(mcp_server.contract, "close_log", boom)
    ended = []
    with pytest.raises(OSError):
        mcp_server.step_aside(why=lambda: "an update is staged", calls=mcp_server.Calls(), sleep=lambda s: None,
                              end=lambda: ended.append(True))
    assert ended == [True]


def test_it_never_starts_into_an_update(monkeypatch):
    """A reconnect mid-swap (the line tells the learner to reconnect): the server answers update-staged at once and
    never builds — the program file and the mutex are not held a moment longer than the start."""
    def never(**_kw):
        raise AssertionError("built while an update was staged")
    monkeypatch.setattr(mcp_server, "build", never)
    monkeypatch.setattr(mcp_server.threading, "Thread", lambda **kw: pytest.fail("a watcher started"))
    _stage_marker()
    assert mcp_server.main([]) == mcp_server.contract.EXIT_CODES["update-staged"] == 3


def test_it_lets_go_of_its_running_mark_before_it_ends():
    """*Start over completely* and the updater's listing see a mark as a program alive: it goes before the exit."""
    assert locks.hold_running("mcp")
    seen = []
    mcp_server.step_aside(why=lambda: "an update is staged", calls=mcp_server.Calls(), sleep=lambda s: None,
                          end=lambda: seen.append(bool(locks._mark)))
    assert seen == [False]


def test_an_update_staged_is_connects_own_signal_the_marker_or_the_lock():
    """No second signal: the marker (the hand-over) and the update lock (Update now) are what Connect reads."""
    assert mcp_server.why_step_aside() is None
    path = _stage_marker()
    assert mcp_server.why_step_aside() == "an update is staged"
    os.remove(path)
    assert mcp_server.why_step_aside() is None
    from app.path_utils import release_lock, try_lock
    lock_path = library_store.update_lock_path()
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    held = try_lock(lock_path)
    try:
        assert mcp_server.why_step_aside() == "an update is staged"
    finally:
        release_lock(held)
    assert mcp_server.why_step_aside() is None


def test_another_build_under_it_or_setup_running_is_a_reason(monkeypatch):
    monkeypatch.setattr(build_info, "stamp_skew", lambda: {"program": {"version": "3.0.6"}, "folder": None})
    assert mcp_server.why_step_aside() == "another build is in its program folder"
    monkeypatch.setattr(build_info, "stamp_skew", lambda: None)
    monkeypatch.setattr(mcp_server, "setup_running", lambda: True)
    assert mcp_server.why_step_aside() == "Surasura's Setup is running"


def test_a_look_that_fails_is_no_reason(monkeypatch):
    """A broken look must never end a learner's session for nothing (nor raise in the watching thread)."""
    def boom(**_kw):
        raise OSError("the local data folder is gone")
    monkeypatch.setattr(library_store, "update_staged", boom)
    monkeypatch.setattr(build_info, "stamp_skew", lambda: (_ for _ in ()).throw(ValueError("bad stamp")))
    monkeypatch.setattr(mcp_server, "setup_running", lambda: False)
    assert mcp_server.why_step_aside() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Inno's SetupMutex is a Windows named mutex")
def test_setup_running_sees_setups_named_mutex_and_holds_nothing_of_it(monkeypatch):
    name = f"SurasuraPiyoUpTest{os.getpid()}.Setup"
    monkeypatch.setattr(mcp_server, "setup_mutex_name", lambda: name)
    assert mcp_server.setup_running() is False
    handle = build_info.create_mutex(name)
    assert handle
    assert mcp_server.setup_running() is True
    import ctypes
    ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(handle))
    assert mcp_server.setup_running() is False          # its look kept no handle open: Setup's mutex is Setup's


def test_the_real_setup_name_is_the_iss_setupmutex():
    """packaging/surasura.iss: SetupMutex={#DataName}.Setup — the name looked for must stay that one."""
    with open(os.path.join(PROJECT_ROOT, "packaging", "surasura.iss"), encoding="utf-8-sig") as f:
        iss = f.read()
    assert "SetupMutex={#DataName}" + mcp_server.SETUP_SUFFIX in iss
    assert mcp_server.setup_mutex_name() == "Surasura" + mcp_server.SETUP_SUFFIX


# --- the calls: a write always finishes, a new call is refused, an answer is never lost ------------------------- #
def test_a_write_under_way_always_finishes_a_read_gets_its_wait():
    calls = mcp_server.Calls()
    done = threading.Event()
    left = []
    with calls.call(writes=True):
        t = threading.Thread(target=lambda: (left.append(calls.leave(read_wait=0.05)), done.set()), daemon=True)
        t.start()
        assert not done.wait(0.4)           # past the read wait: a write is never cut
        assert calls.leaving
    assert done.wait(2.0) and left == [True]

    calls = mcp_server.Calls()
    with calls.call(writes=False):
        started = time.monotonic()
        assert calls.leave(read_wait=0.2) is False      # a read still under way: it ends after its wait anyway
        assert time.monotonic() - started >= 0.18


def test_no_call_starts_once_it_steps_aside():
    from mcp.server.mcpserver.exceptions import ToolError
    calls = mcp_server.Calls()
    assert calls.leave(read_wait=0) is True
    with pytest.raises(ToolError) as e:
        with calls.call(writes=False):
            pass
    assert str(e.value) == mcp_server.UPDATING


def test_a_write_under_way_finishes_with_one_line_and_a_new_call_is_refused(monkeypatch):
    """Through the SDK's in-memory client, as the AI app sees it: a round being saved when the update is staged is
    saved and answered whole (plus the one line), a call that comes meanwhile is refused with the line, and the
    process ends only after the write."""
    calls = mcp_server.Calls()
    started, go, ended = threading.Event(), threading.Event(), threading.Event()

    def saving(_state, round_id, lines, notes, language):
        started.set()
        assert go.wait(10)
        return {"saved": round_id}
    monkeypatch.setattr(mcp_server, "save_round", saving)
    server, _ = mcp_server.build(_state(), warm=False, calls=calls)
    aside = threading.Thread(target=mcp_server.step_aside, daemon=True, kwargs=dict(
        why=lambda: started.is_set() and "an update is staged", calls=calls, sleep=lambda s: time.sleep(0.01),
        end=ended.set))
    aside.start()
    out = {}

    async def go_on():
        async with Client(server) as client:
            async def write():
                out["write"] = await client.call_tool("surasura_save_round", {"round_id": "r-0001"})
            async with anyio.create_task_group() as tg:
                tg.start_soon(write)
                await anyio.to_thread.run_sync(lambda: _until(lambda: calls.leaving))
                out["read"] = await client.call_tool("surasura_help_topics", {})
                out["ended_mid_write"] = ended.is_set()
                go.set()
    anyio.run(go_on)
    assert _error(out["read"]) and mcp_server.UPDATING in _text(out["read"])
    assert out["ended_mid_write"] is False
    assert not _error(out["write"])
    import json
    assert json.loads(_text(out["write"])) == {"saved": "r-0001", "updating": mcp_server.UPDATING}
    assert ended.wait(5)


def test_the_tools_keep_their_schemas_and_writes_are_told_from_reads():
    """The counting wrapper keeps each tool's signature and words (the SDK reads the schema through it); the four
    tools that write or ask are the ones whose call `leave` always waits for."""
    seen = []

    class Recording(mcp_server.Calls):
        def call(self, writes):
            seen.append(writes)
            return super().call(writes)
    server, _ = mcp_server.build(_state(), warm=False, calls=Recording())

    async def listing():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            await client.call_tool("surasura_help_topics", {})                     # a read
            await client.call_tool("surasura_undo_translations", {"batch": ""})    # a write (refused: no batch)
            return tools
    tools = {t.name: t for t in anyio.run(listing)}
    start = tools["surasura_practice_start"]
    props = start.input_schema["properties"] if hasattr(start, "input_schema") else start.inputSchema["properties"]
    assert set(props) == {"words", "role", "kind", "source", "language", "again"}
    assert "Start a practice round" in start.description
    assert "Write your translations" in tools["surasura_write_translations"].description
    assert seen == [False, True]
    # the tools counted as writes: by their annotations, as the AI app's listing shows them
    writes = {name for name, t in tools.items() if t.annotations and t.annotations.read_only_hint is False}
    assert writes == {"surasura_save_round", "surasura_send_report", "surasura_write_translations",
                      "surasura_undo_translations",
                      "surasura_listening_round", "surasura_listening_status"}     # a round's own folder (Piyo-LR)


def test_a_str_answer_under_way_ends_with_the_line():
    """Help, diagnose and the cards answer text: the line goes on its own last line, the answer itself whole."""
    calls = mcp_server.Calls()
    registered = {}

    def tool(*_a, **_kw):
        return lambda fn: registered.setdefault("fn", fn)
    wrap = mcp_server._counted(tool, calls)

    @wrap(annotations=None)
    def answer() -> str:
        calls.leaving = True            # the update is staged while it answers
        return "Help topics: …"
    assert registered["fn"]() == "Help topics: …\n" + mcp_server.UPDATING


def test_the_line_never_replaces_a_note_or_breaks_a_json_answer():
    """practice_start's "no list yet" note stays; diagnose and the cards answer JSON text, and it stays JSON."""
    import json
    note = {"words": [], "note": "There is no list yet: run Generate first."}
    assert mcp_server._with_updating(note) == dict(note, updating=mcp_server.UPDATING)
    text = json.dumps({"version": "3.0.7", "logs": ["「第3話」…"]}, ensure_ascii=False, separators=(",", ":"))
    got = json.loads(mcp_server._with_updating(text))
    assert got == {"version": "3.0.7", "logs": ["「第3話」…"], "updating": mcp_server.UPDATING}
    assert mcp_server._with_updating("{not json") == "{not json\n" + mcp_server.UPDATING
    assert mcp_server._with_updating(None) is None


# --- the real process: Setup's AppMutex free once an update is staged ------------------------------------------ #
_CHILD = r"""
import os, sys
from app import build_info
build_info._running = build_info.create_mutex(os.environ["PIYO_UP_MUTEX"])   # as the frozen program holds it
from app.cli.__main__ import main
sys.exit(main(["mcp"]))
"""


def _mutex_there(name):
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenMutexW.restype = wintypes.HANDLE
    k32.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    handle = k32.OpenMutexW(0x00100000, False, name)        # what Inno's AppMutex check opens
    if handle:
        k32.CloseHandle(wintypes.HANDLE(handle))
    return bool(handle)


def _cli_log_says(root, words):
    for folder, _dirs, files in os.walk(root):
        if "cli.log" in files:
            with open(os.path.join(folder, "cli.log"), encoding="utf-8", errors="replace") as f:
                if words in f.read():
                    return True
    return False


@pytest.mark.skipif(sys.platform != "win32", reason="Setup's AppMutex is a Windows named mutex")
def test_a_serving_piyo_lets_go_of_setups_appmutex_once_an_update_is_staged():
    """The report itself, end to end: a real `surasura-cli mcp` process, its stdin held open as the AI app holds it,
    holding the `<data name>.Running` mutex as the frozen program does. Staging an update (the hand-over's marker)
    ends it by itself within a couple of looks, exit 0 — and the mutex Setup waits for is gone."""
    root = os.environ["SURASURA_TEST_ROOT"]
    name = f"SurasuraPiyoUpTest{os.getpid()}.Running"
    env = dict(os.environ, PIYO_UP_MUTEX=name, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, "-c", _CHILD], cwd=PROJECT_ROOT, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        assert _until(lambda: _cli_log_says(root, "mcp: serving on stdio"), timeout=60), "the server never started"
        time.sleep(mcp_server.LOOK_EVERY_S + 0.5)       # a quiet look or two: no update, no exit
        assert proc.poll() is None and _mutex_there(name)
        _stage_marker()
        staged = time.monotonic()
        assert _until(lambda: proc.poll() is not None, timeout=3 * mcp_server.LOOK_EVERY_S + 10), \
            "Piyo still holds Setup's AppMutex with an update staged"
        assert proc.returncode == 0
        assert time.monotonic() - staged < 3 * mcp_server.LOOK_EVERY_S + 5
        assert not _mutex_there(name)
        assert _cli_log_says(root, "mcp: an update is staged, so it ends now")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(10)
        for pipe in (proc.stdin, proc.stdout):
            pipe.close()
