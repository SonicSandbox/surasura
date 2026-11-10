"""tests/flake_lints.py: the three lints that keep the load-only reds away (tests/FLAKES.md), on this tree and on a
planted mistake each. Read from the source, never run: each fails at once on every machine, never one run in thirty
under load.

What a wrong answer costs: a parentless Qt object freed by a worker's collection crashes a later test natively (the
3.0.0 cut's shard 1/8); a date written in the future turns a test red the day it passes (the cut's base red); a sleep
then an assert loses its race on a loaded machine (four --alls, four different reds).
"""
import datetime
import os
import textwrap

import pytest

from tests import flake_lints as L


def _plant(root, rel, source):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(source))
    return rel


# --- this tree -------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("lint, allow", [(L.parentless_qt_objects, L.PARENTLESS_ALLOWED),
                                         (L.future_dates, L.FUTURE_DATES_ALLOWED),
                                         (L.sleeps_in_qt_tests, L.SLEEPS_ALLOWED)],
                         ids=["parentless-qt-objects", "future-dates", "sleeps-in-qt-tests"])
def test_this_tree_has_nothing_the_allowlist_doesnt_explain_and_no_entry_left_over(lint, allow):
    found = lint()
    assert L.unexplained(found, allow) == [], "fix it (FLAKES.md says how), or list it with its reason"
    assert L.stale(found, allow) == [], "nothing left there to explain: take the entry out"


def test_every_suites_test_files_are_read_and_the_parsing_suite_is_not():
    files = L.test_files()
    assert "tests/qt/test_ankiconnect_install_part.py" in files and "tests/qt/conftest.py" in files
    assert any(f.startswith("modules/") for f in files) == os.path.isdir(os.path.join(L.ROOT, "modules"))
    assert not any(f.startswith("tests/parsing/") for f in files)
    assert "app/qt/bridge.py" in L.app_files() and not any("/tests/" in f for f in L.app_files())


# --- 1. parentless Qt objects ------------------------------------------------------------------------------------- #
def test_a_bare_qtimer_in_a_test_is_found_and_one_with_a_parent_or_the_fixtures_is_not(tmp_path):
    rel = _plant(str(tmp_path), "tests/qt/test_planted.py", """
        from PyQt6.QtCore import QObject, QTimer
        def test_bare(host, qt_timer):
            tick = QTimer()
            helper = QObject()
            ok = QTimer(host)
            fine = QTimer(parent=host)
            also = qt_timer()
            QTimer.singleShot(5, host.close)
    """)
    found = L.parentless_qt_objects(str(tmp_path), [rel])
    assert [(f[1], f[2], f[3]) for f in found] == [("test_bare", 4, "QTimer()"), ("test_bare", 5, "QObject()")]
    assert L.unexplained(found, L.PARENTLESS_ALLOWED) == found


def test_the_apps_relays_count_too(tmp_path):
    rel = _plant(str(tmp_path), "app/qt/planted.py", """
        from app.qt import bridge
        def make():
            return bridge.Relay()
    """)
    assert [f[3] for f in L.parentless_qt_objects(str(tmp_path), [rel])] == ["bridge.Relay()"]


# --- 2. future dates ---------------------------------------------------------------------------------------------- #
def test_a_date_later_than_today_is_found_in_a_string_and_in_each_date_call(tmp_path):
    rel = _plant(str(tmp_path), "tests/test_planted.py", """
        import datetime, time
        def test_dates():
            retry = {"retry_after": "2027-01-01T00:00:00Z", "seen": "2026-11-09"}
            a = datetime.datetime(2027, 3, 1)
            b = time.mktime((2026, 12, 25, 0, 0, 0, 0, 0, -1))
            c = datetime.date(2025, 1, 1)
            d = "not a date: 2026-13-45"
    """)
    found = L.future_dates(str(tmp_path), [rel], today=datetime.date(2026, 11, 10))
    assert [(f[2], f[3]) for f in found] == [(4, "2027-01-01"), (5, "2027-03-01"), (6, "2026-12-25")]
    assert L.future_dates(str(tmp_path), [rel], today=datetime.date(2027, 6, 1)) == [], "past dates never count"


def test_a_date_relative_to_the_run_is_never_found(tmp_path):
    rel = _plant(str(tmp_path), "tests/test_planted.py", """
        import datetime, time
        def test_relative():
            ahead = datetime.datetime.fromtimestamp(time.time() + 86400, datetime.timezone.utc).isoformat()
    """)
    assert L.future_dates(str(tmp_path), [rel]) == []


# --- 3. sleeps in Qt tests ---------------------------------------------------------------------------------------- #
def test_a_sleep_in_a_qt_tests_body_is_found_and_a_stand_ins_or_a_deadline_loops_is_not(tmp_path):
    rel = _plant(str(tmp_path), "tests/qt/test_planted.py", """
        import time
        from PyQt6.QtWidgets import QApplication
        def test_races(win):
            win.start()
            time.sleep(0.3)
            assert win.done

            def slow_stand_in():
                time.sleep(0.2)
            win.work = slow_stand_in
            win.later = lambda: time.sleep(0.1)
            deadline = time.monotonic() + 5
            while not win.done and time.monotonic() < deadline:
                time.sleep(0.01)
            for _ in range(3):
                time.sleep(0.02)

        def helper():
            time.sleep(1)
    """)
    found = L.sleeps_in_qt_tests(str(tmp_path), [rel])
    assert [(f[1], f[2]) for f in found] == [("test_races", 6), ("test_races", 17)]


def test_a_file_without_qt_is_not_read_for_sleeps(tmp_path):
    rel = _plant(str(tmp_path), "tests/test_planted.py", """
        import time
        def test_plain():
            time.sleep(0.3)
    """)
    assert L.sleeps_in_qt_tests(str(tmp_path), [rel]) == []


# --- the allowlists ------------------------------------------------------------------------------------------------ #
def test_an_allowlist_entry_explains_its_place_and_one_with_nothing_left_is_stale():
    found = [("tests/a.py", "test_x", 3, "QTimer()"), ("tests/b.py", "test_y.inner", 9, "QObject()")]
    allow = {("tests/a.py", "test_x"): "why", ("tests/b.py", "test_y"): "why", ("tests/c.py", "test_z"): "why"}
    assert L.unexplained(found, allow) == []
    assert L.stale(found, allow) == [("tests/c.py", "test_z")]
    assert L.unexplained(found, {("tests/a.py", "*"): "why"}) == [found[1]]


def test_every_allowlist_entry_says_why():
    for allow in (L.PARENTLESS_ALLOWED, L.FUTURE_DATES_ALLOWED, L.SLEEPS_ALLOWED):
        assert all(isinstance(why, str) and len(why) > 20 for why in allow.values())
