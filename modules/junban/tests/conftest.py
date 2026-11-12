# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared pytest setup for the Junban module tests.

Puts the project root on sys.path so `modules.junban` and `app.*` import cleanly when running
`pytest modules/junban/tests`, and sandboxes every path this module could write to.

Two separate roots have to be redirected, and missing either one means a test run touches the
developer's own machine:

  * `SURASURA_TEST_ROOT` covers `get_data_path` / `get_user_files_path` / `get_user_file`, so a test
    reads a fixture `results/priority_learning_list.csv` instead of the real 14 MB one, and never
    rewrites the real `settings.json` (`testing.md` §5.1).
  * `get_persistent_user_data_path` is NOT covered by that env var — it resolves to %APPDATA% — and
    it is where this module's card snapshots (the only undo that exists for a `due` write) will
    live. Without this patch a snapshot test would drop files into the developer's real profile and,
    worse, a restore test could read a *real* snapshot.

**The rule this depends on:** every junban module must call `get_persistent_user_data_path()` via an
import made INSIDE the function, never a module-level `from app.path_utils import ...`. A name bound
at module import time is not reached by patching `app.path_utils` (`testing.md` §5.2), so the
autouse fixture below would silently do nothing.

Nothing here touches Anki. The module's suite is media-free and network-free by construction: the
transport is exercised against a mocked `urlopen`, never a live collection (spec §18.0 rule 6 —
`The Accelerator` and `Migaku Reference` are read-only, always).
"""
import gc
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from tests.quiet_windows import quiet_windows  # noqa: E402  (the project root is on sys.path just above)
from tests.tk_on_github import skip_tk_tests  # noqa: E402
from tests.network_guard import around_a_test  # noqa: E402
# The guards every suite shares, as the core suite's (tests/harness_guards.py): the real data roots, the gap between
# tests, Tk interpreters freed on the main thread, no child process left running, no real Anki reached.
from tests.harness_guards import (_guard_real_local_data, _guard_anki_port,  # noqa: E402,F401
                                  pytest_collection, pytest_runtest_protocol, pytest_runtest_teardown,
                                  pytest_runtestloop, pytest_sessionfinish, pytest_configure)
# The library store's copy trigger after Connect's writes (L3.3) starts a detached helper: never from a test,
# nor from a command line a test starts (it inherits the switch)
os.environ.setdefault("SURASURA_NO_IDLE_EXPORT", "1")

quiet_windows()                             # test windows open on a desktop of their own: never seen, never typed into


def pytest_collection_modifyitems(items):
    skip_tk_tests(items)                    # GitHub's runner only: the Tk window tests run in the local --all


@pytest.fixture(autouse=True)
def network_guard():
    """Every test stays on this machine, as the core suite's (W2.1 G-3; tests/network_guard.py): a connection or a name
    lookup past loopback is refused as the app meets it offline, and the test fails at its end naming the address —
    the AnkiConnect fakes and the loopback servers stay open. W3.4 carries it here with the module's Qt window."""
    yield from around_a_test()


@pytest.fixture(scope="session", autouse=True)
def _session_test_root(tmp_path_factory):
    """A test root between tests too. The 順 window takes its `junban-window` lock on a thread of its own, and a
    thread started late in one test can run after its test root is gone: with no root at all it built this copy's
    real local data folder (%LOCALAPPDATA%\\SonicSandbox\\Surasura\\<install key>), and the core suite's guard, in its
    own process under `--all`, failed whichever test was running then. Each test's own root (below) still wins.
    Never undone: those threads also outlive the session (they wait up to 2 s for the lock while the process ends),
    and the variable dies with this process."""
    os.environ["SURASURA_TEST_ROOT"] = str(tmp_path_factory.mktemp("session_root"))


@pytest.fixture(autouse=True)
def _isolate_junban_paths(tmp_path, monkeypatch):
    """Point both the data root and the persistent snapshot root at throwaway directories."""
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path))

    persistent = tmp_path / "persistent"
    persistent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.path_utils.get_persistent_user_data_path",
                        lambda: str(persistent), raising=False)
    yield


@pytest.fixture(autouse=True)
def _tk_garbage_freed_on_the_main_thread(request):
    """A Tk test's closed windows are collected here, on the main thread, before the next test starts.

    A Tk variable freed by a worker thread's collection costs that thread 1 s (Tk waits for a main loop no test runs,
    then gives up: 'main thread is not in main loop'), and a closed window leaves dozens in reference cycles. Freed by
    the window-lock thread of a later Backfill window, between its take and its release, they kept `backfill-window`
    held in this process for seconds: the next test's `WindowLock.hold` waited its 2 s and was told Busy, by test order.
    Only after a test whose file, or a test class it builds on, uses Tk (a collection is ~40 ms here; after every
    test, a minute a run), and once more as the next class starts: a Tk class's `tearDownClass` runs after its last
    test's collection. A failing test's traceback keeps its window until a later collection."""
    last = _last_test.get("item")
    if last is not None and last[1] and (last[0] is not request.module or last[2] is not request.cls):
        gc.collect()
    yield
    uses_tk = _uses_tk(request)
    _last_test["item"] = (request.module, uses_tk, request.cls)
    if uses_tk:
        gc.collect()


_last_test = {}     # "item": (module, used Tk, class) of the test that ran last


def _uses_tk(request):
    """Does the test's module, or the module of any class its test class builds on (test_replan_row's
    `JunbanGuiTestCase`), hold a tkinter module (`import tkinter as tk`, `from tkinter import ttk`)?"""
    if "tkinter" not in sys.modules:
        return False
    modules = [request.module] + [sys.modules.get(c.__module__) for c in getattr(request.cls, "__mro__", ())]
    return any(isinstance(value, types.ModuleType) and value.__name__.split(".")[0] == "tkinter"
               for module in modules if module is not None for value in vars(module).values())


@pytest.fixture
def anki_writer():
    """The Anki-write lock, held by the test's own thread (E1.4 §W): for the wire tests that call a
    writer (`set_due`, `update_notes`, …) directly. Without it `invoke` refuses every write action,
    as it should — the writers that call them take the lock themselves."""
    from app import anki_connect
    with anki_connect.writer("a wire test") as held:
        yield held


@pytest.fixture(autouse=True)
def _no_ui_timers(monkeypatch):
    """Stop the panel arming its connection-probe timer during tests.

    A pending `after()` whose Tcl command died with the interpreter keeps firing into nothing for the
    rest of the session — `invalid command name ..._probe`. The flag gates the *scheduling*, because
    a guard inside the callback can never run: it is never invoked (`testing.md` §5.4).
    """
    monkeypatch.setenv("SURASURA_NO_UI_TIMERS", "1")


@pytest.fixture(autouse=True)
def _no_real_modals(monkeypatch):
    """No test may open a real dialog.

    A modal with no one to click it makes the suite **hang** rather than fail, and a hang gives no
    clue which test caused it. That risk is live from this package onward: `open_junban` raises a
    messagebox on every failure path, and the reorder confirmation (invariant I5) is a blocking
    `wait_window`.

    Declining is the safe default: a test that trips a confirmation by accident should stop, not go
    on and write to a collection. A test that wants the other answer patches the call itself, which
    overrides this.
    """
    try:
        from tkinter import messagebox
    except Exception:                       # headless / no tkinter — nothing to guard
        return
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)
    try:                                    # the panel's own themed helpers arrive with WP-H
        from modules.junban import gui
    except Exception:
        return
    for name, answer in (("ask", lambda *a, **k: False), ("tell", lambda *a, **k: None)):
        if hasattr(gui, name):
            monkeypatch.setattr(gui, name, answer)


@pytest.fixture
def ja_sentences():
    """Real Japanese sentences from the shared test resources — never dummy ASCII (`testing.md` §1)."""
    path = os.path.join(_ROOT, "tests", "Test Resources", "ja", "context_test.txt")
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]
