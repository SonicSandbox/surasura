# Flakes: the ledger

A flake is a test whose answer depends on the machine's timing: green alone, red under load. The 3.0.0 release cut
went red four times on four different such tests. Each one is found and fixed at its cause, test or code. A flake can
be a real bug, so none is waved through with a longer timeout, a retry or a skip.

## How to keep them away

- **Wait on a condition, never on the clock.** `wait_until` (tests/qt/conftest.py) or `h.until`
  (tests/services_helpers.py) instead of `time.sleep` and then an assert. A sleep is right only for a window in which
  nothing may happen, or for a clock tick between two writes. `tests/flake_lints.py` lists each of those with its
  reason.
- **Dates relative to the run.** `time.time() + 86400`, never `"2027-01-01"`. The lint fails any date later than
  today written into a test.
- **No parentless Qt helper.** A test's timer is `qt_timer()` (tests/qt/conftest.py); any other Qt object that isn't
  a widget gets a parent. The lint fails a bare `QTimer()` / `QObject()`, and the harness fails a test during which
  Qt warns that one of its objects was used from another thread (tests/harness_guards.py).
- **Read a shared file the way the app does.** Use the same lock the writer holds. On Windows an open reader makes the
  writer's `os.replace` fail.
- **Real concurrency goes in `tests/stress/`.** These tests run many iterations and check only invariants (nothing
  lost, nothing twice), never a timing: `python run_tests.py --stress [N]`.
- **Before READY:** `python run_tests.py --stress-changed` runs every test file the branch changed 20 times, with two
  core shards beside it as load.
- **The same tests everywhere.** GitHub's runner runs the Tk window tests too. Only `SURASURA_SKIP_TK_TESTS=1` skips
  them.

## The ledger

| Test | Cause | Fix | Date | Owner |
| :-- | :-- | :-- | :-- | :-- |
| tests/qt/test_ankiconnect_install_part.py (the cut's shard 1/8, exit 0xC0000005) | **Test.** Parentless test `QTimer()`s in reference cycles were freed by whichever thread's collection ran, a worker's too. That deleted a Qt object off its own thread, and a later event crashed the process. Probe: of 78 such timers, 12 were freed off the main thread, and one plain run in twelve crashed. The app keeps its own parentless relays alive until the GUI thread deletes them (app/qt/bridge.py). | A `qt_timer` fixture that deletes on the main thread, used at all ten places. A lint for parentless Qt helpers and a harness guard for Qt's cross-thread warnings. Before the fix, 19 live parentless timers were left after teardown; after it, 0. | 2026-11-10 | Flake-P |
| modules/youtube_downloader/tests/test_qt_window.py `test_the_apps_quit_keeps_the_rest_for_the_next_start` (a 10 s wait ran out) | **Test.** The test polled the rest's record on the main thread outside its lock. On Windows the open file refused the worker's `os.replace` ("Access is denied"), and the run's record write failed. Under a 30 ms read: red 3/3. The app reads the record only under `_REST_LOCK`. | The test reads under the lock (`_rest`). Under the same probe: green 3/3. Noted for the module's owner: an outside reader (a virus scanner) could refuse the app's replace the same way. | 2026-11-10 | Flake-P |
| tests/test_sources_k5_pool.py `test_a_write_that_fails_cancels_the_parts_not_started_…` (`['1.part'] == []`) | **Test.** The pool's one worker can start the next part between the failure and the cancel. The code keeps its contract: its caller drops every `.part` on a failure (app/sources.py). | #339: the test records what started. `tests/stress/test_stress_k5_pool.py` checks the contract by many rounds. | 2026-11-10 | Minato; checked by Flake-P |
| tests/qt/test_report_window.py `test_fresh_u_a_window_crossing_the_screens_bottom_is_moved_up_onto_it` | **Test.** The 700-row stand-in screen sized the window nearly as tall as itself. Once Windows reported the frame, the window crossed from y=10 and was rightly moved up. | #340: a 1600-row stand-in screen. | 2026-11-10 | Minato; checked by Flake-P |
| tests/test_update_state.py `test_the_update_check_reads_the_failed_version_from_update_state` | **Not a flake.** A fixed 2.5.1 read as older than the 3.0.0 stamp. It is a Tk test that GitHub's runner skipped, so no pull request ran it. | #338: it offers `__version__` + 1. The Tk tests now run on GitHub. | 2026-11-10 | Minato; Flake-P |
| tests/test_no_subs.py (hato's retry dates) | **Test.** The fixed dates 2026-11-09 and 2026-11-10 passed (the cut's base red), and 2027-01-01 was the next one due to pass. | Dates relative to the run (c78e4f57, and this lane for 2027-01-01). The future-date lint. | 2026-11-10 | Kotoba-R / Flake-P |
| tests/test_sources_scan.py `test_a_window_move_during_a_look_lands_within_the_budget` (R6: 56 ms over the 50 ms budget, timed) | **Open.** The timed form only: the longest of hundreds of lock holds. Under study: whether a gc pause falls inside one take-in. | — | 2026-11-10 | Flake-P |
| connect/test_status_record.py `test_stamp_is_equal_…_differs_after_a_need` | **Code.** Connect's status stamp was size + mtime, and two ledger writes in one 15.6 ms tick looked equal. | The wal-index header in the stamp (#286). | 2026-11-05 | Minato-Q |
| connect/test_bs0a1k_stop_at_once.py | **Test.** Timed from the batch's start, so it counted the programs' starts. | Timed from the press (#286). | 2026-11-05 | Minato-Q |
| qt/test_airing_finish.py `…the_mark_undone_then_the_answer_finishes_nothing` | **Test.** The stand-in writer's Undo wrote nothing back. | `MarkWriter` (#286). | 2026-11-05 | Minato-Q |
| qt/test_drag.py `test_a8_a_mark_lets_go_…` | **Code.** The reader's view could reach the window before the writer's word. | A landed mark asks for a fresh view (#286). | 2026-11-05 | Minato-Q |
| qt/test_settings_store.py (a GitHub shard died, exit 127 / 3) | **Open, not reproduced.** It died about 2 ms into a Qt test, with no faulthandler line. Likely the same class as the first row: test_settings_live.py, which runs just before it, left a parentless timer (now fixed). | Exits now say how the shard died (#286). | 2026-11-05 | open |
| koe / junban / youtube `test_…_opens_without_tkinter` (exit 0xC0000005) | **Test.** The child script left its windows to Python's teardown. | Each child ends with `shell.quiet_exit` (#286). | 2026-11-05 | Minato-Q |
| qt/test_settings_connect.py (star.json PermissionError) | **Test.** It read the file just after the writer's rename. | It waits until the file reads (#286). | 2026-11-05 | Minato-Q |
| train 14's late `StoreRefused (I7)` line | **Test.** A fixture finished the wrong writer. | It finishes its own and checks the thread ended (#286). | 2026-11-05 | Minato-Q |
