"""One window per user session and install (W2.1 row 6; the window's spec 05 §5.11; app/qt/single.py).

What a wrong answer would cost: two windows over one library (two writers, two Anki reorders); a second start that
silently opens nothing; a start during the first's close that hands over to a window going away and leaves the user
with none. And the stack pack's harness trap: a single-instance check sharing a name with the developer's real window
passes alone and fails in the full run — every test here has its own name and lock (tests/qt/conftest.py).
"""
import gc
import os
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip("PyQt6")

from app import path_utils
from app.qt import shell, single
from tests.qt.conftest import wait_until

PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "single_probe.py")


def _claim_in_thread(instance, args, result):
    t = threading.Thread(target=lambda: result.append(instance.claim(args, wait=5)), daemon=True)
    t.start()
    return t


def test_the_name_carries_the_user_the_session_and_the_install(monkeypatch):
    monkeypatch.delenv("SURASURA_INSTANCE_NAME", raising=False)
    name = single.instance_name()
    import getpass
    assert name.startswith("surasura-window-")
    assert getpass.getuser().replace(" ", "_") in name
    assert name.endswith(__import__("hashlib").sha256(path_utils.get_local_data_path().encode("utf-8")).hexdigest()[:12])
    monkeypatch.setenv("SURASURA_INSTANCE_NAME", "surasura-test-x")
    assert single.instance_name() == "surasura-test-x"
    assert single.lock_path().startswith(os.environ["SURASURA_TEST_ROOT"])
    assert single._session_id() in os.path.basename(single.lock_path())     # per session, as the name (review A13)


def test_a_second_start_hands_over_and_the_first_comes_forward(qapp):
    # Python's collector runs on every turn of the wait: a handler kept alive only by a Qt connection (a closure in a
    # cycle with its socket) would be collected here and the first would never answer (seen in the full suite).
    services = shell.Services()
    win = shell.open_window(qapp, services)
    first = single.SingleInstance()
    try:
        assert first.claim([]) is True and first.outcome == "first"
        first.activated.connect(win.bring_to_front)
        heard = []
        first.activated.connect(heard.append)
        win.showMinimized()
        second, result = single.SingleInstance(), []
        t = _claim_in_thread(second, ["--from", "a second start"], result)
        assert wait_until(lambda: (gc.collect(), not t.is_alive())[1], 10)
        assert result == [False] and second.outcome == "handed-over"
        assert heard == [["--from", "a second start"]]
        assert not win.isMinimized() and win.isVisible()
    finally:
        first.release()
        win.close()
        services.shutdown(0.5)


def test_a_client_that_never_ends_its_line_is_cut_off(qapp):
    from PyQt6.QtNetwork import QLocalSocket
    first = single.SingleInstance()
    try:
        assert first.claim([])
        sock = QLocalSocket()
        sock.connectToServer(first.name)
        assert sock.waitForConnected(2000)
        sock.write(b"x" * (single.MAX_LINE + 10))
        sock.flush()
        assert wait_until(lambda: sock.state() == QLocalSocket.LocalSocketState.UnconnectedState
                          or not first._clients, 5)
        assert first._clients == [] or all(s.state() != s.LocalSocketState.ConnectedState for s, _ in first._clients)
    finally:
        first.release()


def test_a_left_over_lock_file_with_no_holder_is_taken(qapp):
    open(single.lock_path(), "w").close()                  # a dead first's file: the OS freed its lock
    instance = single.SingleInstance()
    assert instance.claim([], wait=1) is True
    instance.release()


def test_a_start_during_the_firsts_close_becomes_the_first(qapp):
    first = single.SingleInstance()
    assert first.claim([])
    first.stop_listening()                                  # the window is closing: no hand-over to it now
    second, result = single.SingleInstance(), []
    t = _claim_in_thread(second, [], result)
    time.sleep(0.4)
    assert t.is_alive()                                     # it waits for the lock, it doesn't give up or hand over
    first.release()                                         # the first has quit
    assert wait_until(lambda: not t.is_alive(), 10)
    assert result == [True] and second.outcome == "first"
    second.release()


def test_a_start_that_connects_just_as_the_first_closes_becomes_the_first(qapp):
    # The review's blocking race (A1): the second start's connection is pending when the first stops listening, so it
    # never gets `ok` — it must go on waiting for the lock, not give up and leave the user with no window.
    first = single.SingleInstance()
    assert first.claim([])
    second, result = single.SingleInstance(), []
    t = _claim_in_thread(second, [], result)
    assert wait_until(lambda: bool(first._clients), 5)      # accepted and greeted, its arguments not yet answered
    first.stop_listening()                                  # the window starts closing
    time.sleep(1.0)
    first.release()                                         # ... and quits
    assert wait_until(lambda: not t.is_alive(), 10)
    assert result == [True] and second.outcome == "first"
    second.release()


def test_a_first_that_says_hello_but_never_ok_is_not_handed_over_to(qapp):
    # A fake first: it holds the lock, accepts, says hello, and never answers. A start must not report "handed over"
    # (it would exit and the user would have no window); it waits for the lock and, at its deadline, gives up.
    from PyQt6.QtNetwork import QLocalServer
    held = path_utils.try_lock(single.lock_path())
    server = QLocalServer()
    assert server.listen(os.environ["SURASURA_INSTANCE_NAME"])
    accepted = []

    def accept():
        s = server.nextPendingConnection()
        s.write(b"hello 1\n")
        s.flush()
        accepted.append(s)
    server.newConnection.connect(accept)
    try:
        second, result = single.SingleInstance(), []
        t = threading.Thread(target=lambda: result.append(second.claim([], wait=2)), daemon=True)
        t.start()
        assert wait_until(lambda: not t.is_alive(), 15)
        assert result == [False] and second.outcome == "gave-up" and accepted
    finally:
        server.close()
        path_utils.release_lock(held)


def test_the_first_says_hello_with_its_pid_and_the_second_lets_it_come_forward(qapp, monkeypatch):
    allowed = []
    monkeypatch.setattr(single, "_allow_foreground", lambda pid: allowed.append(pid))
    first = single.SingleInstance()
    try:
        assert first.claim([])
        second, result = single.SingleInstance(), []
        t = _claim_in_thread(second, [], result)
        assert wait_until(lambda: not t.is_alive(), 10)
        assert result == [False] and allowed == [str(os.getpid())]
    finally:
        first.release()


def test_a_line_nested_past_pythons_limit_still_gets_its_answer(qapp):
    from PyQt6.QtNetwork import QLocalSocket
    first = single.SingleInstance()
    heard = []
    first.activated.connect(heard.append)
    try:
        assert first.claim([])
        sock = QLocalSocket()
        sock.connectToServer(first.name)
        assert sock.waitForConnected(2000)
        sock.write(b"[" * 5000 + b"]" * 5000 + b"\n")
        sock.flush()
        got = []

        def read():
            got.append(bytes(sock.readAll()))
            return b"ok\n" in b"".join(got)
        assert wait_until(read, 5)
        assert heard == [[]]
    finally:
        first.release()


def test_a_holder_that_never_listens_makes_a_start_give_up_not_open_a_second_window(qapp):
    held = path_utils.try_lock(single.lock_path())
    try:
        instance = single.SingleInstance()
        t0 = time.monotonic()
        assert instance.claim([], wait=0.5) is False
        assert instance.outcome == "gave-up" and time.monotonic() - t0 < 3
    finally:
        path_utils.release_lock(held)


def _start(env):
    return subprocess.Popen([sys.executable, PROBE], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)


def test_two_starts_at_once_give_one_window(tmp_path):
    """Processes, as a user double-clicking twice: exactly one stays as the first, the other hands over to it."""
    races = int(os.environ.get("SURASURA_SINGLE_RACES", "5"))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outcomes = []
    for i in range(races):
        barrier = tmp_path / f"start{i}"
        barrier.mkdir()
        env = dict(os.environ, PYTHONPATH=root, SURASURA_TEST_ROOT=str(tmp_path / f"race{i}"),
                   SURASURA_INSTANCE_NAME=f"surasura-race-{os.getpid()}-{i}-{time.time_ns()}", HOLD="3",
                   QT_QPA_PLATFORM="offscreen", PROBE_BARRIER=str(barrier), PROBE_PARTIES="2")
        a, b = _start(env), _start(env)
        out = sorted(p.communicate(timeout=60)[0].strip() for p in (a, b))
        outcomes.append(out)
        assert [p.returncode for p in (a, b)] == [0, 0], out
    assert all(o[0] == "first 1" and o[1] == "handed-over" for o in outcomes), outcomes
