"""`app/locks.py` — the named lock every Anki writer takes (E1.4 §H) and the command line reuses (P1.2).

What a wrong answer would cost, in order:
  * two writers in Anki at once — a second process, a second thread or a second install must be told
    `Busy` (or wait), and told who holds it;
  * a lock that outlives its holder — a crashed or killed Surasura must never block the next one: the
    OS releases a dead process's lock;
  * a nested take that waits on itself forever — it raises instead;
  * a wait the user can't stop — closing a window sets `cancel`, and the wait ends;
  * a test that writes the real `%LOCALAPPDATA%` — every lock lives under the test root.

Across processes the holder is a real child Python (`subprocess`), never a mock: the claim is about
the OS lock, and only a second process can prove it.
"""
import os
import statistics
import subprocess
import sys
import threading
import time

import pytest

from app import locks, path_utils

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A child that takes one lock and holds it: `hold` seconds after saying "held", or until its stdin
# closes when `hold` is negative. `install`, when given, is its per-install data folder (a second
# install of Surasura beside the first).
_CHILD = r"""
import json, sys, time
from app import locks, path_utils
name, verb, install, hold = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
if install:
    path_utils.get_local_data_path = lambda: install
try:
    held = locks.take(name, verb)
except locks.Busy as e:
    print("busy " + json.dumps(e.holder), flush=True)
    sys.exit(0)
print("held", flush=True)
if hold < 0:
    sys.stdin.readline()
else:
    time.sleep(hold)
held.release()
print("released", flush=True)
"""


def _child(name, verb="順 reorder", install="", hold=-1.0):
    """Start a child holding `name`; returns once it holds it (or said it couldn't)."""
    process = subprocess.Popen([sys.executable, "-c", _CHILD, name, verb, install, str(hold)],
                               cwd=_ROOT, env=dict(os.environ), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True, encoding="utf-8")
    first = process.stdout.readline().strip()
    return process, first


def _stop(process):
    try:
        process.stdin.close()
    except OSError:
        pass
    process.wait(timeout=10)


@pytest.fixture
def root():
    return os.environ["SURASURA_TEST_ROOT"]


# --- across processes ------------------------------------------------------------------------------ #
def test_a_second_process_is_told_busy_with_the_first_holders_record():
    process, first = _child("anki-writer", "Backfill")
    try:
        assert first == "held"
        with pytest.raises(locks.Busy) as caught:
            locks.take("anki-writer", "順 reorder")
        holder = caught.value.holder
        assert holder["pid"] == process.pid and holder["verb"] == "Backfill"
        assert holder["program"] == "python" and len(holder["started"]) == 19   # local time, to the second
    finally:
        _stop(process)


def test_a_one_second_wait_gets_the_lock_when_the_holder_lets_go_at_0_3_s():
    process, first = _child("anki-writer", "Backfill", hold=0.3)
    try:
        assert first == "held"
        started = time.monotonic()
        with locks.take("anki-writer", "順 reorder", wait=1) as held:
            assert held.waited is True
            assert time.monotonic() - started < 1.0
            assert locks.read_holder("anki-writer")["pid"] == os.getpid()
    finally:
        process.wait(timeout=10)


def test_a_killed_holder_frees_the_lock_within_five_seconds():
    # The OS releases a dead process's lock (Windows after a short delay): a crash never strands it.
    process, first = _child("anki-writer")
    assert first == "held"
    process.kill()
    process.wait(timeout=10)
    started = time.monotonic()
    with locks.take("anki-writer", "順 reorder", wait=5):
        assert time.monotonic() - started < 5
    process.stdin.close()


def test_two_installs_share_the_anki_writer_and_keep_their_own_plain_locks(tmp_path, monkeypatch):
    # One Windows user has one Anki: a second install (another per-install folder) collides on
    # `anki-writer`, and never on a name of its own.
    other, mine = str(tmp_path / "install_a"), str(tmp_path / "install_b")
    monkeypatch.setattr(path_utils, "get_local_data_path", lambda: mine)
    process, first = _child("anki-writer", install=other)
    try:
        assert first == "held"
        with pytest.raises(locks.Busy):
            locks.take("anki-writer", "Backfill")
    finally:
        _stop(process)
    process, first = _child("results", install=other)
    try:
        assert first == "held"
        with locks.take("results", "Generate"):
            pass
    finally:
        _stop(process)
    # The same install collides on the plain name, as it should.
    process, first = _child("results", install=mine)
    try:
        assert first == "held"
        with pytest.raises(locks.Busy):
            locks.take("results", "Generate")
    finally:
        _stop(process)


# --- inside one process ---------------------------------------------------------------------------- #
def test_two_threads_of_one_process_exclude_each_other():
    held = locks.take("anki-writer", "順 reorder")
    answers = {}

    def other():
        try:
            locks.take("anki-writer", "Backfill")
        except locks.Busy as e:
            answers["busy"] = e.holder
        with locks.take("anki-writer", "Backfill", wait=None) as mine:
            answers["got"] = locks.held_here("anki-writer") and mine.waited

    worker = threading.Thread(target=other)
    worker.start()
    time.sleep(0.4)
    assert "got" not in answers and answers["busy"]["verb"] == "順 reorder"
    assert locks.held_here("anki-writer") is True
    held.release()
    worker.join(timeout=5)
    assert answers["got"] is True
    assert locks.held_here("anki-writer") is False


def test_a_nested_take_in_one_thread_raises_and_keeps_the_lock():
    with locks.take("anki-writer", "順 reorder"):
        with pytest.raises(RuntimeError):
            locks.take("anki-writer", "順 reorder", wait=0.5)
        assert locks.held_here("anki-writer")
    assert not locks.held_here("anki-writer")


def test_setting_cancel_stops_a_wait_and_on_wait_is_told_once():
    held = locks.take("anki-writer", "順 reorder")
    cancel, told, answer = threading.Event(), [], {}

    def waiter():
        try:
            locks.take("anki-writer", "Backfill", wait=None, cancel=cancel, on_wait=told.append)
        except locks.Cancelled as e:
            answer["cancelled"] = e.holder

    worker = threading.Thread(target=waiter)
    worker.start()
    time.sleep(0.6)                     # two polls at least: on_wait is still called once
    cancel.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert answer["cancelled"]["verb"] == "順 reorder"
    assert [entry["verb"] for entry in told] == ["順 reorder"]
    assert held.held and locks.read_holder("anki-writer")["verb"] == "順 reorder"   # still the first's
    held.release()


def test_a_wait_that_runs_out_is_busy():
    with locks.take("anki-writer", "順 reorder"):
        result = {}
        worker = threading.Thread(target=lambda: result.update(
            busy=pytest.raises(locks.Busy, locks.take, "anki-writer", "Backfill", wait=0.3)))
        started = time.monotonic()
        worker.start()
        worker.join(timeout=3)
        assert 0.25 <= time.monotonic() - started < 1.5
        assert result["busy"].value.holder["verb"] == "順 reorder"


# --- names, records and where they live ------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["Anki-writer", "anki_writer", "../anki-writer", "", "anki writer",
                                  "順", None])
def test_a_name_outside_lowercase_letters_digits_and_dashes_is_refused(name):
    with pytest.raises(ValueError):
        locks.take(name, "順 reorder")


def test_the_holder_record_is_written_after_the_take_and_gone_after_the_release(root):
    with locks.take("known-words-ja", "Anki sync") as held:
        record = locks.read_holder("known-words-ja")
        assert record["verb"] == "Anki sync" and record["pid"] == os.getpid()
    assert held.held is False
    assert locks.read_holder("known-words-ja") is None
    held.release()                      # twice is harmless


def test_a_record_that_cannot_be_written_never_fails_the_take(monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError("[WinError 5] Access is denied")
    monkeypatch.setattr(locks.os, "replace", refuse)
    with locks.take("anki-writer", "順 reorder"):
        assert locks.held_here("anki-writer")
        assert locks.read_holder("anki-writer") is None
    assert not [name for name in os.listdir(locks.folder("anki-writer")) if name.endswith(".tmp")]


def test_every_lock_lives_under_the_test_root(root):
    # The shared name goes to the per-user folder, a plain one to the per-install folder: both moved.
    assert locks.folder("anki-writer") == os.path.join(path_utils.local_data_root(), "locks")
    assert locks.folder("results") == os.path.join(path_utils.get_local_data_path(), "locks")
    for name in ("anki-writer", "results"):
        with locks.take(name, "Generate"):
            pass
    written = [os.path.join(where, entry) for where, _dirs, files in os.walk(root) for entry in files
               if os.path.basename(where) == "locks"]       # the root also holds the copied samples
    assert all(os.path.commonpath([root, path]) == root for path in written)
    assert sorted(os.path.basename(path) for path in written) == ["anki-writer.lock", "results.lock"]


def test_take_and_release_uncontended_take_under_five_milliseconds():
    times = []
    for _ in range(50):
        started = time.perf_counter()
        locks.take("anki-writer", "順 reorder").release()
        times.append(time.perf_counter() - started)
    assert statistics.median(times) <= 0.005, f"median {statistics.median(times) * 1000:.2f} ms"
