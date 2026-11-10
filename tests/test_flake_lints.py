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
@pytest.mark.parametrize("lint, allow, stale_counts", [(L.parentless_qt_objects, L.PARENTLESS_ALLOWED, True),
                                                       (L.future_dates, L.FUTURE_DATES_ALLOWED, False),
                                                       (L.sleeps_in_qt_tests, L.SLEEPS_ALLOWED, True)],
                         ids=["parentless-qt-objects", "future-dates", "sleeps-in-qt-tests"])
def test_this_tree_has_nothing_the_allowlist_doesnt_explain_and_no_entry_left_over(lint, allow, stale_counts):
    found = lint()
    assert L.unexplained(found, allow) == [], "fix it (FLAKES.md says how), or list it with its reason"
    if stale_counts:                    # (a listed future date that has passed is no fault: never a date bomb itself)
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


def test_the_apps_own_qt_classes_count_too_through_any_base(tmp_path):
    rel = _plant(str(tmp_path), "app/qt/planted.py", """
        from PyQt6.QtCore import QObject
        class Bell(QObject):
            pass
        class LoudBell(Bell):
            pass
        def ring(host):
            return LoudBell(), Bell(host)
    """)
    assert [f[3] for f in L.parentless_qt_objects(str(tmp_path), [rel])] == ["LoudBell()"]


# --- 2. future dates ---------------------------------------------------------------------------------------------- #
def test_a_date_later_than_today_is_found_in_a_string_and_in_each_date_call(tmp_path):
    # the planted dates are made from the run's own day (a planted fixed date would itself pass one day)
    today = datetime.date.today()
    ahead, later, soon, past = (today + datetime.timedelta(days=d) for d in (52, 111, 45, -400))
    rel = _plant(str(tmp_path), "tests/test_planted.py", f"""
        import datetime, time
        def test_dates():
            retry = {{"retry_after": "{ahead.isoformat()}T00:00:00Z", "seen": "{past.isoformat()}"}}
            a = datetime.datetime({later.year}, {later.month}, {later.day})
            b = time.mktime(({soon.year}, {soon.month}, {soon.day}, 0, 0, 0, 0, 0, -1))
            c = datetime.date({past.year}, {past.month}, {past.day})
            d = "not a date: {today.year}-13-45"
    """)
    found = L.future_dates(str(tmp_path), [rel], today=today)
    assert [(f[2], f[3]) for f in found] == [(4, ahead.isoformat()), (5, later.isoformat()), (6, soon.isoformat())]
    assert L.future_dates(str(tmp_path), [rel], today=later) == [], "past dates never count"


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


# --- 4. fixed-time Qt waits ----------------------------------------------------------------------------------------- #
def test_no_test_file_adds_a_fixed_time_qt_wait_and_a_converted_one_lowers_its_count():
    assert L.qwaits_off_record(L.qwaits()) == [], ("(file, now, recorded): a new QTest.qWait — wait on its condition "
                                                   "(wait_until); one converted — lower its count in QWAITS_TO_REVIEW")


def test_a_qwait_is_counted_wherever_it_is_in_the_file(tmp_path):
    rel = _plant(str(tmp_path), "tests/qt/test_planted.py", """
        from PyQt6.QtTest import QTest
        def _rest():
            QTest.qWait(300)
        def test_joins(win):
            _rest()
            QTest.qWait(50)
    """)
    counts = L.qwaits(str(tmp_path), [rel])
    assert counts == {rel: 2}
    assert L.qwaits_off_record(counts, {}, root=str(tmp_path)) == [(rel, 2, 0)]
    assert L.qwaits_off_record(counts, {rel: 2}, root=str(tmp_path)) == []


# --- the allowlists ------------------------------------------------------------------------------------------------ #
def test_an_allowlist_entry_explains_its_place_and_one_with_nothing_left_is_stale():
    found = [("tests/a.py", "test_x", 3, "QTimer()"), ("tests/b.py", "test_y.inner", 9, "QObject()")]
    allow = {("tests/a.py", "test_x"): "why", ("tests/b.py", "test_y"): "why", ("tests/c.py", "test_z"): "why"}
    assert L.unexplained(found, allow) == []
    assert L.stale(found, allow, root=os.path.dirname(os.path.abspath(__file__))) == [], "no such files here"
    assert L.stale(found, {("tests/flake_lints.py", "gone"): "why"}) == [("tests/flake_lints.py", "gone")]
    assert L.unexplained(found, {("tests/a.py", "*"): "why"}) == [found[1]]


def test_every_allowlist_entry_says_why():
    for allow in (L.PARENTLESS_ALLOWED, L.FUTURE_DATES_ALLOWED, L.SLEEPS_ALLOWED):
        assert all(isinstance(why, str) and len(why) > 20 for why in allow.values())
