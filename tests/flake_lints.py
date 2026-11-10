"""Three lints that keep the load-only reds away (tests/FLAKES.md), read from the source — never by running it — so each
fails at once, on every run and every machine, never one run in thirty under load. Run by tests/test_flake_lints.py
(the core suite, GitHub's shards included), over every suite's test files and the app's code:

* `parentless_qt_objects`: a Qt object that is no widget (a QTimer, a QObject, …) made with no parent, in a test or in
  the app. Python owns it, and a reference cycle hands its end to whichever thread's collection frees it — a worker's
  too: a Qt object deleted off its own thread crashes the process later (Windows fatal 0xC0000005, the 3.0.0 cut's
  shard 1/8). A test takes `qt_timer()` (tests/qt/conftest.py: deleted on the main thread at its end) or gives one a
  parent; the app keeps its few as `bridge.run_in_worker` keeps its relay.
* `future_dates`: a date written into a test that is later than today (`"2027-01-01"`, `datetime(2027, 1, 1)`,
  `time.mktime((2027, …))`). A test that compares one with the real clock changes its answer the day it passes (the
  3.0.0 cut's base red: hato's retry date 2026-11-09). A date relative to the run (`now + 86400`) never does.
* `sleeps_in_qt_tests`: a `time.sleep` written straight into a Qt test's body (not in a stand-in it hands the code,
  not in a loop bounded by a deadline). A sleep then an assert that something happened is a race the machine's load
  decides: wait on the condition (`wait_until`, `h.until`) instead. The legitimate ones — a window in which nothing
  may happen, a clock tick between two writes — are listed with their reasons.

Each allowlist names a place by (file, the test or function it is in) and says why; a place that no longer needs its
entry fails too, so the lists stay true.
"""
import ast
import datetime
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- where each lint reads ------------------------------------------------------------------------------------------ #

def test_files(root=ROOT):
    """Every suite's test files and conftests (tests/ and modules/*/tests/), as paths from the root, in order. The
    parsing suite (local only) is left to its own guard."""
    out = []
    for top in ["tests"] + sorted(os.path.join("modules", m, "tests") for m in _listdir(os.path.join(root, "modules"))):
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, top)):
            dirnames[:] = sorted(d for d in dirnames if d not in ("__pycache__", "parsing") and not d.startswith("."))
            for name in sorted(filenames):
                if name.endswith(".py") and (name.startswith("test_") or name == "conftest.py"):
                    out.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
    return out


def app_files(root=ROOT):
    """The app's own code (app/ and modules/, their tests left out), as paths from the root, in order."""
    out = []
    for top in ("app", "modules"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, top)):
            dirnames[:] = sorted(d for d in dirnames if d not in ("__pycache__", "tests") and not d.startswith("."))
            out += [os.path.relpath(os.path.join(dirpath, n), root).replace(os.sep, "/")
                    for n in sorted(filenames) if n.endswith(".py")]
    return out


def _listdir(path):
    try:
        return [n for n in os.listdir(path) if os.path.isdir(os.path.join(path, n, "tests"))]
    except OSError:
        return []


_TEXT, _TREE = {}, {}     # (root, path) -> its source / its tree: each file read, and parsed, once a run


def _text(root, path):
    key = (root, path)
    if key not in _TEXT:
        with open(os.path.join(root, path), encoding="utf-8") as f:
            _TEXT[key] = f.read()
    return _TEXT[key]


def _parse(root, path):
    key = (root, path)
    if key not in _TREE:
        _TREE[key] = ast.parse(_text(root, path), filename=path)
    return _TREE[key]


def _owners(tree):
    """{node: the name of the function (or class) it sits in, outermost first, dotted}."""
    out = {}

    def walk(node, owner):
        for child in ast.iter_child_nodes(node):
            name = owner
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{owner}.{child.name}" if owner else child.name
            out[child] = name or "<module>"
            walk(child, name)
    walk(tree, "")
    return out


# --- 1. a Qt object that is no widget, made with no parent ---------------------------------------------------------- #
# The Qt classes an app or a test makes as helpers (never a window: a widget with no parent is a window, closed and
# deleted on the main thread by the window harness and by the app's own close).
NON_WIDGET_QT = frozenset({"QTimer", "QObject", "QEventLoop", "QFileSystemWatcher", "QSocketNotifier", "QLocalServer",
                           "QLocalSocket", "QTimeLine", "QPropertyAnimation", "QVariantAnimation",
                           "QSequentialAnimationGroup", "QParallelAnimationGroup", "QThread", "QThreadPool",
                           "QSignalMapper", "QActionGroup", "QButtonGroup", "QShortcut"})
# The app's relays (app/qt/bridge.py) are Qt objects too.
NON_WIDGET_QT |= {"Relay", "_Relay"}

PARENTLESS_ALLOWED = {
    ("tests/qt/conftest.py", "qt_timer.make"):
        "the fixture's own timer: stopped and deleted on the main thread at the test's end (sip.delete)",
    ("app/qt/bridge.py", "run_in_worker"):
        "kept in `_pending` until its answer lands, then deleteLater on the GUI thread (never the pool's last ref)",
    ("app/qt/single.py", "SingleInstance._hand_over"):
        "a local socket, in no cycle: freed by its refcount on the thread that made it, as the function returns",
    ("tests/qt/test_ankiconnect_install_part.py", "test_a_sheet_dropped_unanswered_puts_the_part_back"):
        "the sheet's stand-in card: deleteLater'd by the test itself on the main thread (the card's own end)",
    ("tests/qt/test_bridge.py", "test_a_relays_answer_on_its_way_when_its_window_goes_never_reaches_the_slot"):
        "the relay's holder: deleteLater'd by the test on the main thread (what the test is about)",
    ("tests/qt/test_hud.py", "_run_loop"): "a local event loop run here, freed by its refcount as the function returns",
    ("tests/qt/test_hud.py", "test_the_probe_start_runs_main_and_writes_every_phase"):
        "a local event loop run here, freed by its refcount as the test returns",
    ("tests/qt/test_hud_windows.py", "_run_loop"):
        "a local event loop run here, freed by its refcount as the function returns",
    ("tests/qt/test_single_instance.py", "test_a_client_that_never_ends_its_line_is_cut_off"):
        "a local socket (the outside client), freed by its refcount on the main thread as the test returns",
    ("tests/qt/test_single_instance.py", "test_a_line_nested_past_pythons_limit_still_gets_its_answer"):
        "a local socket (the outside client), freed by its refcount on the main thread as the test returns",
    ("tests/qt/test_single_instance.py", "test_a_first_that_says_hello_but_never_ok_is_not_handed_over_to"):
        "a fake first's server, closed in the test's finally on the main thread (the outside program it stands for)",
}


_BARE_CALL = re.compile(r"\b(?:" + "|".join(sorted(NON_WIDGET_QT)) + r")\(\s*\)")


def _parent_given(call):
    """Whether a constructor call names a parent: any positional argument (a parent, a target, a signal, a
    duration: none of those is parentless by mistake) or `parent=`."""
    return bool(call.args) or any(k.arg == "parent" for k in call.keywords)


def parentless_qt_objects(root=ROOT, files=None):
    """[(file, owner, line, call)] for every non-widget Qt object made with no parent, outside the allowlist."""
    found = []
    for path in files if files is not None else test_files(root) + app_files(root):
        if not _BARE_CALL.search(_text(root, path)):          # (read as text first: parsed only where one may be)
            continue
        tree = _parse(root, path)
        owners = _owners(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and not _parent_given(node):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                if name in NON_WIDGET_QT:
                    found.append((path, owners.get(node, "<module>"), node.lineno, ast.unparse(node)))
    return found


# --- 2. a date later than today, written into a test ---------------------------------------------------------------- #
_DATE = re.compile(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)")
_DATE_CALLS = frozenset({"datetime", "date", "datetime.datetime", "datetime.date", "dt.datetime", "dt.date",
                         "time.mktime", "mktime", "calendar.timegm", "timegm"})

FUTURE_DATES_ALLOWED = {
    ("tests/connect/test_inbox.py", "test_a_look_that_finds_nothing_new_writes_nothing_to_the_ledger"):
        "a stand-in clock's value (ledger._now): only compared with the stamp the test read, never with the real clock",
    ("tests/connect/test_p25m_dismiss.py", "test_dismissing_twice_returns_false_and_keeps_the_first_dismissed_time"):
        "a stand-in clock's value (ledger._now): a rewrite would show it; never compared with the real clock",
    ("tests/connect/test_p25m_mark_seen.py", "test_marking_a_need_seen_twice_changes_nothing_the_second_time"):
        "a stand-in clock's value (ledger._now): a rewrite would show it; never compared with the real clock",
    ("tests/test_flake_lints.py", "*"): "the planted mistakes this lint's own tests read: never compared with a clock",
    ("modules/junban/tests/test_anki_writer_lock.py", "*"):
        "a snapshot's own `written_at`, compared with the one the writer saved (another writer's stamp), never with "
        "the real clock",
}


_DATE_CALL_TEXT = re.compile(r"\b(?:datetime|date|mktime|timegm)\(\(?\s*2\d\d\d\s*,")


def _later(match, today):
    try:
        return datetime.date(*map(int, match.groups())) > today
    except ValueError:
        return False


def _date_of_call(call):
    """The (year, month, day) a date constructor call writes out, or None."""
    args = call.args
    if args and isinstance(args[0], ast.Tuple):
        args = args[0].elts
    values = [a.value for a in args[:3] if isinstance(a, ast.Constant) and isinstance(a.value, int)]
    return tuple(values) if len(values) == 3 and 2000 <= values[0] < 2200 else None


def future_dates(root=ROOT, files=None, today=None):
    """[(file, owner, line, date)] for every date later than `today` written into a test, outside the allowlist."""
    today = today or datetime.date.today()
    found = []
    for path in files if files is not None else test_files(root):
        text = _text(root, path)
        if not (any(_later(m, today) for m in _DATE.finditer(text)) or _DATE_CALL_TEXT.search(text)):
            continue                                          # (read as text first: parsed only where one may be)
        tree = _parse(root, path)
        owners = _owners(tree)
        for node in ast.walk(tree):
            dates = []
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                dates = [tuple(map(int, m.groups())) for m in _DATE.finditer(node.value)]
            elif isinstance(node, ast.Call) and ast.unparse(node.func) in _DATE_CALLS:
                dates = [d for d in (_date_of_call(node),) if d]
            for y, m, d in dates:
                try:
                    when = datetime.date(y, m, d)
                except ValueError:
                    continue
                if when > today:
                    found.append((path, owners.get(node, "<module>"), node.lineno, when.isoformat()))
    return sorted(found, key=lambda f: (f[0], f[2]))


# --- 3. a bare sleep in a Qt test's body ---------------------------------------------------------------------------- #
NEGATIVE = "the window in which nothing may happen: a wait on a condition can't stand in (the right answer is none)"
TICK = "a clock tick between two writes (file times; Windows' 15.6 ms clock): no event marks it"
MEASURED = "the span being measured itself"

SLEEPS_ALLOWED = {
    ("modules/junban/tests/test_qt_junban.py", "test_a_reorder_is_a_junban_job_and_waits_for_the_automatic_one"): NEGATIVE,
    ("modules/junban/tests/test_qt_junban.py", "test_closing_while_the_reorder_waits_writes_nothing"): NEGATIVE,
    ("modules/junban/tests/test_qt_junban.py", "test_stopping_a_waiting_reorder_from_the_bar_frees_the_window"): NEGATIVE,
    ("modules/junban/tests/test_qt_junban.py",
     "test_restore_names_what_it_restores_enter_is_no_and_no_writes_nothing"): NEGATIVE,
    ("modules/junban/tests/test_qt_junban.py",
     "test_a_restore_question_open_at_a_language_switch_is_answered_no"): NEGATIVE,
    ("modules/koe/tests/test_qt_window.py", "test_a_test_answering_after_close_paints_nothing"): NEGATIVE,
    ("modules/youtube_downloader/tests/test_qt_window.py",
     "test_a_fetcher_already_on_the_next_language_is_never_asked"): NEGATIVE,
    ("modules/youtube_downloader/tests/test_qt_window.py",
     "test_with_download_covers_off_nothing_is_asked_and_no_picture_shows"): NEGATIVE,
    ("modules/youtube_downloader/tests/test_qt_window.py", "test_nothing_recorded_starts_nothing"): NEGATIVE,
    ("tests/qt/test_arrivals.py",
     "test_IK_10_answers_are_kept_by_item_plan_and_known_words_and_a_change_asks_again"): TICK,
    ("tests/qt/test_arrivals.py", "test_a_failed_estimate_shows_nothing_and_isnt_asked_again"): NEGATIVE,
    ("tests/qt/test_arrivals.py",
     "test_S2_the_same_answers_again_hand_nothing_on_so_the_reader_builds_nothing"): NEGATIVE,
    ("tests/qt/test_arrivals.py", "test_A4B8_the_reader_names_the_arrivals_on_its_own_thread_asks_each_once_and_"
                                  "same_answers_build_nothing"): NEGATIVE,
    ("tests/qt/test_arrivals_a4_fix.py",
     "test_after_a_switch_a_chinese_arrival_whose_id_a_japanese_file_had_is_still_asked"): NEGATIVE,
    ("tests/qt/test_arrivals_routing.py", "test_with_the_bell_live_an_idle_window_never_looks_every_tenth_of_a_second"):
        "an idle second counted (looks in it at most 2: nothing may happen), and the old poll's own rate beside it",
    ("tests/qt/test_arrivals_routing.py",
     "test_a_drop_the_watch_reports_while_the_store_is_busy_is_synced_once_the_store_frees"): NEGATIVE,
    ("tests/qt/test_bridge.py", "test_a_pool_job_starts_only_while_the_window_rests"): NEGATIVE,
    ("tests/qt/test_covers_mid_session.py",
     "test_titles_that_arrive_before_the_first_frame_are_looked_at_once_it_is_out"): NEGATIVE,
    ("tests/qt/test_covers_view.py", "test_nothing_decodes_while_a_window_waits_for_its_first_frame"): NEGATIVE,
    ("tests/qt/test_covers_wiring.py",
     "test_with_download_covers_off_the_window_paints_its_titles_and_nothing_leaves_the_machine"): NEGATIVE,
    ("tests/qt/test_fresh_sheet.py", "test_an_earlier_openings_late_list_never_lands_in_the_next_one"): NEGATIVE,
    ("tests/qt/test_group_picks.py", "test_LM11b_AD5_and_H_T1_a_language_switch_during_a_busy_store_lets_the_picks_go_"
                                     "and_stops_the_old_settle"): NEGATIVE,
    ("tests/qt/test_hud.py", "test_a_named_span_is_reported"): MEASURED,
    ("tests/qt/test_shell_library.py", "test_no_store_yet_opens_getting_ready_and_never_makes_or_migrates_one"):
        NEGATIVE,
    ("tests/qt/test_shell_library.py",
     "test_a_damaged_or_newer_store_opens_read_only_and_refuses_moves_without_writing_it"): NEGATIVE,
    ("tests/qt/test_shell_library.py", "test_a_move_queued_on_a_busy_store_lands_in_its_own_language_before_the_switch"):
        NEGATIVE,
    ("tests/qt/test_shell_library.py", "test_a_switch_straight_back_never_puts_two_writers_on_one_journal"): NEGATIVE,
    ("tests/qt/test_shell_library.py", "test_a_quit_during_a_switch_leaves_nothing_open_and_keeps_the_journal"):
        "the switch left waiting on the busy move while the quit comes (the quit is the event; nothing to wait for)",
    ("tests/qt/test_shell_library.py", "test_a_stale_switch_running_last_follows_the_language_asked_last"):
        "the stale switch given time to run last, then a wait on the condition",
    ("tests/qt/test_single_instance.py", "test_a_start_during_the_firsts_close_becomes_the_first"): NEGATIVE,
    ("tests/qt/test_single_instance.py", "test_a_start_that_connects_just_as_the_first_closes_becomes_the_first"):
        "the first window's close held open while the second start waits (the release is the event)",
    ("tests/qt/test_window_sources.py", "test_a_watch_turn_that_fails_never_ends_the_watches_for_the_run"):
        "the failed turn's end given time, then the next report and a wait on its scan",
    ("tests/qt/test_window_sources.py", "test_a_watch_report_while_the_window_is_behind_waits_for_its_focus"): NEGATIVE,
    ("tests/qt/test_window_sources.py", "test_B1_S7_a_long_download_is_one_look_at_its_end_never_one_per_burst"):
        "bursts spread inside the quiet spell (the pace is the point), then none may come after the one look",
    ("tests/qt/test_window_sources.py", "test_a_new_watch_is_stored_only_once_the_watches_lock_is_free"): NEGATIVE,
    ("tests/test_library_store_switch.py", "test_journey_checks_asked_together_share_their_syncs"):
        "the first check given a head start so the rest arrive while it runs (no event marks 'running')",
    ("tests/test_library_store_switch.py", "test_a_returning_2_4_0s_big_change_waits_for_the_user"): TICK,
    ("tests/test_services_updates.py", "test_check_for_updates_off_sends_no_request_at_start_or_on_offer_again"):
        NEGATIVE,
    ("tests/test_services_updates.py", "test_begin_reconciles_then_checks_and_reads_both_switches"): NEGATIVE,
    ("tests/test_services_updates.py", "test_the_anki_writer_lock_and_the_windows_own_work_keep_it_waiting"): NEGATIVE,
    ("tests/test_services_updates.py", "test_stop_it_stops_one_child_and_a_wait_only_row_is_only_waited_for"): NEGATIVE,
    ("tests/test_services_updates.py", "test_a_running_connect_is_waited_for_never_stopped_and_stop_all_skips_it"):
        NEGATIVE,
    ("tests/test_services_updates.py", "test_cancel_mid_wait_releases_the_lock_discards_and_starts_what_was_held"):
        NEGATIVE,
    ("tests/test_services_updates.py", "test_two_jobs_with_one_label_are_stopped_one_at_a_time"): NEGATIVE,
    ("tests/test_services_updates.py", "test_a_running_job_is_waited_for_and_stop_it_cancels_it"): NEGATIVE,
}


def _sleep_calls(test):
    """The `time.sleep` calls straight in a test's body: not inside a function, lambda or class it defines (a
    stand-in's pace runs on the code's threads), nor in a `while` loop whose test reads the clock (a wait bounded by a
    deadline: the condition is in the loop)."""
    found, stack = [], [(n, False) for n in test.body]
    while stack:
        node, bounded = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call) and ast.unparse(node.func) in ("time.sleep", "sleep") and not bounded:
            found.append(node)
        inside = bounded or (isinstance(node, ast.While) and re.search(r"monotonic|perf_counter|time\(\)|deadline",
                                                                        ast.unparse(node.test)) is not None)
        stack.extend((child, inside) for child in ast.iter_child_nodes(node))
    return sorted(found, key=lambda call: call.lineno)


def sleeps_in_qt_tests(root=ROOT, files=None):
    """[(file, test, line, call)] for every bare sleep in a Qt test's body (a file that imports PyQt6), outside the
    allowlist."""
    found = []
    for path in files if files is not None else test_files(root):
        source = _text(root, path)
        if "PyQt6" not in source or "sleep(" not in source:
            continue
        for node in ast.walk(_parse(root, path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                found += [(path, node.name, call.lineno, ast.unparse(call)) for call in _sleep_calls(node)]
    return found


# --- the allowlists applied ----------------------------------------------------------------------------------------- #
def _allowed(allow, path, owner):
    return (path, owner) in allow or (path, "*") in allow or (path, owner.split(".")[0]) in allow


def unexplained(found, allow):
    """The finds the allowlist doesn't explain."""
    return [f for f in found if not _allowed(allow, f[0], f[1])]


def stale(found, allow):
    """The allowlist's places with nothing left to explain (fixed or moved): the list stays true."""
    seen = {(f[0], f[1]) for f in found} | {(f[0], "*") for f in found} | {(f[0], f[1].split(".")[0]) for f in found}
    return sorted(k for k in allow if k not in seen)
