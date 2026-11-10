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
