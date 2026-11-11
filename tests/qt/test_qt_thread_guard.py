"""The harness's Qt thread guard (tests/harness_guards.py, Flake-P 2026-11-10; tests/FLAKES.md): Qt's own warning that
a Qt object was used from a thread other than its own fails the test during which it came, naming the message, the
test and the thread — at once and every time, never as a native crash one run in thirty in whatever test runs then
(the 3.0.0 cut's shard 1/8). Every message still prints as Qt prints it.

A real Qt timer stopped from a worker (Qt: "Timers cannot be stopped from another thread"), in this process and in a
nested pytest run of the helper below.
"""
import os
import subprocess
import sys
import threading

import pytest
from PyQt6.QtCore import QTimer

from tests import harness_guards

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROBE = "SURASURA_QT_THREAD_PROBE"          # set only for the nested run below


def _stopped_from_a_worker(timer):
    t = threading.Thread(target=timer.stop, name="the-worker")
    t.start()
    t.join()


def test_a_qt_object_used_from_another_thread_is_recorded_with_its_test_and_thread(qapp, qt_timer):
    timer = qt_timer()
    timer.start(60000)
    seen = len(harness_guards._QT_WARNINGS)
    _stopped_from_a_worker(timer)
    new = harness_guards._QT_WARNINGS[seen:]
    assert [(w[2], "another thread" in w[0]) for w in new] == [("the-worker", True)], new
    assert "test_a_qt_object_used_from_another_thread_is_recorded" in new[0][1]
    assert harness_guards._claim_qt_warnings() == [f"{new[0][0]!r} during {new[0][1]}, thread 'the-worker'"]
    assert harness_guards._claim_qt_warnings() == [], "claimed once: never charged to the next test"
    timer.stop()


def test_a_message_on_the_main_thread_or_without_a_thread_word_is_no_cross_thread_warning(qapp):
    seen = len(harness_guards._QT_WARNINGS)
    harness_guards._qt_message(None, None, "This plugin does not support propagateSizeHints()")
    assert harness_guards._QT_WARNINGS[seen:] == []


def test_a_real_run_fails_the_test_that_used_a_qt_object_from_another_thread(tmp_path):
    env = dict(os.environ, PYTHONPATH=PROJECT, PYTHONIOENCODING="utf-8")
    env[PROBE] = "1"
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("PYTEST_ADDOPTS", None)
    out = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                          "tests/qt/test_qt_thread_guard.py::test_helper_stops_a_timer_from_a_worker"],
                         cwd=PROJECT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    text = out.stdout.decode("utf-8", "replace")
    assert out.returncode == 1, text
    assert "ERROR at teardown of test_helper_stops_a_timer_from_a_worker" in text, text
    assert "Qt warned of a Qt object used from a thread other than its own" in text and "the-worker" in text, text


@pytest.mark.skipif(not os.environ.get(PROBE), reason="a helper of the nested run above")
def test_helper_stops_a_timer_from_a_worker(qapp):
    timer = QTimer(qapp)                    # (a parent: the lint's rule; the use from a worker is the mistake here)
    timer.start(60000)
    _stopped_from_a_worker(timer)
    timer.deleteLater()


# --- the `qt_timer` fixture (tests/qt/conftest.py): a test's timers deleted on the main thread at its end ----------- #
_MADE = []


def test_the_fixtures_timer_is_a_live_parentless_timer_while_its_test_runs(qt_timer):
    timer = qt_timer()
    timer.start(60000)
    assert isinstance(timer, QTimer) and timer.parent() is None and timer.isActive()
    _MADE.append((timer, threading.get_ident()))


def test_the_fixtures_timer_was_deleted_at_its_tests_end_on_the_main_thread():
    # why: a timer the fixture left to Python is the access violation's cause (FLAKES.md); this runs right after the
    # test above, in the file's order
    from PyQt6 import sip
    if not _MADE:
        pytest.skip("runs after the test above")
    timer, made_on = _MADE.pop()
    assert made_on == threading.main_thread().ident
    assert sip.isdeleted(timer), "the fixture left its timer alive: a worker's collection could delete it"


# --- a worker's collection never deletes a Qt object of the main thread (tests/harness_guards.py) ----------------- #
def test_a_parentless_qt_object_a_workers_collection_frees_is_deleted_on_the_main_thread_instead(qapp):
    # why: Qt 6.11 says nothing when one is deleted off its thread, and the process crashed later (the cut's shard 1/8)
    import gc
    from PyQt6 import sip
    from PyQt6.QtCore import QObject
    gc.collect()
    orphan = QObject()                                  # Python owns it: no parent
    child = QObject(orphan)                             # deleted with it: tells whether its C++ object is gone
    orphan.me = orphan                                  # a reference cycle: only the collector frees it
    del orphan
    collected = threading.Thread(target=gc.collect, name="worker-gc")
    collected.start()
    collected.join()
    assert not sip.isdeleted(child), "the worker's collection deleted a Qt object of the main thread"
    assert harness_guards._WORKER_GARBAGE, "kept for the main thread"
    gc.collect(0)                                       # a young collection of the main thread's: still alive
    assert not sip.isdeleted(child), "let go before the teardown: it would outlive it (round 2, B1)"
    assert harness_guards._free_worker_garbage() > 0     # (as each test's teardown does)
    assert sip.isdeleted(child) and harness_guards._WORKER_GARBAGE == []


def test_a_main_thread_collection_frees_as_ever(qapp):
    import gc
    from PyQt6 import sip
    from PyQt6.QtCore import QObject
    orphan = QObject()
    child = QObject(orphan)
    orphan.me = orphan
    del orphan
    gc.collect()
    assert sip.isdeleted(child) and harness_guards._WORKER_GARBAGE == []


def test_a_workers_collection_deletes_nothing_and_a_young_main_collection_keeps_it_for_the_teardown(qapp):
    # why: the same hold for a plain cycle (a Tk root's, a test's helpers): kept (its memory never freed on the worker:
    # finalizers still run there, CPython's way), past a young collection of the main thread's (it can't reach them),
    # freed by the teardown's collection on the main thread
    import gc

    class Cycle:
        pass
    a = Cycle()
    a.me = a
    kept = id(a)
    del a
    t = threading.Thread(target=gc.collect, name="worker-gc")
    t.start()
    t.join()
    assert any(id(o) == kept for batch in harness_guards._WORKER_GARBAGE for o in batch), "kept, not freed"
    gc.collect(0)                                       # a young collection on the main thread: still kept
    assert any(id(o) == kept for batch in harness_guards._WORKER_GARBAGE for o in batch)
    assert harness_guards._free_worker_garbage() > 0    # (as each test's teardown does)
    assert harness_guards._WORKER_GARBAGE == []


def test_the_main_threads_own_collection_frees_what_a_worker_found(qapp):
    # why: a test's gc.collect() expects what is unreachable freed (test_shell_library's freed reader went red on
    # GitHub while the hold kept a worker's find until the teardown)
    import gc
    import weakref

    class Cycle:
        pass
    reader = Cycle()                                    # alive, as the old library was at the worker's collection
    a = Cycle()
    a.me, a.reader = a, reader                          # a cycle the worker finds, holding the reader
    del a
    t = threading.Thread(target=gc.collect, name="worker-gc")
    t.start()
    t.join()
    gone = weakref.ref(reader)
    del reader                                          # the test lets go of it: only the worker's find holds it
    gc.collect()
    assert gone() is None and harness_guards._WORKER_GARBAGE == []


# --- a stones build whose answer the teardown dropped is forgotten (tests/qt/conftest.py) ------------------------- #
_KEY = ("flake-p", 1.0, "M")


def test_a_stones_build_under_way_as_a_test_ends(qapp):
    from app.qt import stones
    stones._BUILDING[_KEY] = []                         # started, its answer on its way (dropped at the teardown)


def test_is_forgotten_by_the_next_test_so_its_ask_starts_one_of_its_own():
    # why: the answer never lands, and an ask that joins it starts none (test_shell's S1 test, a loaded pool; FLAKES.md)
    from app.qt import stones
    assert _KEY not in stones._BUILDING
