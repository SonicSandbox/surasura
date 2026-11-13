"""Mattias's 3.0.6 field report: updating Surasura meant killing every surasura-cli.exe by hand first. The ones left
were `surasura-cli mcp`, which the AI app (Claude Code: one per session) keeps for as long as its session lives —
holding Surasura's `<data name>.Running` mutex (Setup's AppMutex) and its own program file, so Setup waited for ever.

Now the server steps aside as Connect does (`mcp_server.watch_updates`): an update staged, Setup running (its
`<data name>.Setup` mutex) or another build in its program folder ends it — never in the middle of a tool call.

What a wrong answer would cost: an update blocked until the learner hunts processes down (the field report), or the
other way, a server ending mid-call (a practice round half-saved) or ending with no update at all."""
import inspect
import sys
import threading
import time

import pytest

from app.cli import mcp_server


def _reasons(*answers):
    """`why` answering each of `answers` in turn, the last one for good."""
    said = list(answers)

    def why():
        return said.pop(0) if len(said) > 1 else said[0]
    return why


def test_it_ends_once_an_update_is_waiting_and_not_before():
    ended, naps = [], []
    got = mcp_server.watch_updates(why=_reasons(None, None, "an update of Surasura is waiting"),
                                   end=lambda: ended.append(True), calls=mcp_server.Calls(), sleep=naps.append,
                                   every=2.0, wait=0)
    assert got == "an update of Surasura is waiting"
    assert ended == [True] and naps == [2.0, 2.0, 2.0], "it looked three times and ended at the third"


def test_it_never_ends_in_the_middle_of_a_tool_call():
    calls, order = mcp_server.Calls(), []
    inside, leave = threading.Event(), threading.Event()

    def call():
        with calls:
            inside.set()
            leave.wait(5)
            order.append("call done")
    t = threading.Thread(target=call)
    t.start()
    inside.wait(5)
    watcher = threading.Thread(target=mcp_server.watch_updates, kwargs=dict(
        why=lambda: "Surasura's Setup is running", end=lambda: order.append("ended"), calls=calls,
        sleep=lambda s: None, wait=5))
    watcher.start()
    time.sleep(0.2)
    assert order == [], "the call under way is waited for"
    leave.set()
    t.join(5)
    watcher.join(5)
    assert order == ["call done", "ended"]


def test_a_call_that_never_ends_holds_it_only_for_its_wait():
    calls, ended = mcp_server.Calls(), []
    calls.__enter__()                       # a call that never comes back
    started = time.monotonic()
    mcp_server.watch_updates(why=lambda: "x", end=lambda: ended.append(True), calls=calls, sleep=lambda s: None,
                             wait=0.2)
    assert ended == [True] and time.monotonic() - started < 2


def test_what_makes_it_step_aside(monkeypatch):
    from app import build_info, library_store
    monkeypatch.setattr(library_store, "update_staged", lambda **kw: False)
    monkeypatch.setattr(mcp_server, "setup_running", lambda: False)
    monkeypatch.setattr(build_info, "stamp_skew", lambda: None)
    assert mcp_server.must_yield() is None
    monkeypatch.setattr(build_info, "stamp_skew", lambda: {"program": {}, "folder": {}})
    assert "another build" in mcp_server.must_yield()
    monkeypatch.setattr(mcp_server, "setup_running", lambda: True)
    assert "Setup" in mcp_server.must_yield()
    monkeypatch.setattr(library_store, "update_staged", lambda **kw: True)
    assert "update" in mcp_server.must_yield()


def test_a_look_that_fails_is_no_reason(monkeypatch):
    from app import build_info, library_store

    def broken(**_kw):
        raise OSError("no such folder")
    monkeypatch.setattr(library_store, "update_staged", broken)
    monkeypatch.setattr(mcp_server, "setup_running", lambda: False)
    monkeypatch.setattr(build_info, "stamp_skew", lambda: (_ for _ in ()).throw(RuntimeError("bad stamp")))
    assert mcp_server.must_yield() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Setup's mutex is a Windows named mutex")
def test_setup_running_is_setups_own_mutex(monkeypatch):
    from app import build_info, path_utils
    name = f"Surasura-test-{time.monotonic_ns()}"
    monkeypatch.setattr(path_utils, "data_name", lambda: name)
    assert mcp_server.setup_running() is False
    handle = build_info.create_mutex(name + mcp_server.SETUP_SUFFIX)
    try:
        assert mcp_server.setup_running() is True
    finally:
        import ctypes
        ctypes.WinDLL("kernel32").CloseHandle(handle)
    assert mcp_server.setup_running() is False


def test_every_tool_runs_counted_and_keeps_its_signature():
    calls, registered = mcp_server.Calls(), {}

    def tool(**_kw):
        def decorate(fn):
            registered["fn"] = fn
            return fn
        return decorate
    seen = []

    @mcp_server._counted(tool, calls)()
    def a_tool(words: int = 5, role: str = "friend"):
        seen.append(calls.idle(0))          # inside the call: not idle
        return words

    assert list(inspect.signature(registered["fn"]).parameters) == ["words", "role"]
    assert registered["fn"](words=3) == 3 and seen == [False]
    assert calls.idle(0), "after the call: idle"
