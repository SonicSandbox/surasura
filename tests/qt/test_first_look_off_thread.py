"""E-L2W: the source-folder looks' module is read on a worker after the first frame, never on the window's thread.

Read in the first frame's step (`ShellWindow._start_looks` → `_open_looks` → `app/services/source_looks.py` →
`app/sources.py`, whose patterns compile at import), it took turns at Python's lock with the numbers' plan read and
held the window's thread 250–310 ms at 2,000 files at level 2 of the sentence table (the smoothness verifier's
window row). Counted, not timed: the window's thread runs no import of that module while it opens; the same looks
are made, on the window's thread, and the first look is asked once the module is in. A test's own looks
(`services.source_looks`) and a module read already are made at once, as before."""
import builtins
import sys
import threading

import pytest

pytest.importorskip("PyQt6")
from app.qt import shell  # noqa: E402
from tests.fixtures import window_seed  # noqa: E402
from tests.qt.conftest import wait_until  # noqa: E402
from tests.qt.test_drag import FakeWriter, _stones_sheet, open_window  # noqa: E402,F401  (the stones' sheet fixture)
from tests.qt.test_window_sources import RecordingLooks  # noqa: E402

LOOKS = "app.services.source_looks"     # (shell.LOOKS_MODULE: spelled here, so the test reads the same before it)


@pytest.fixture
def opened(qapp):
    made = []

    def make():
        seed = window_seed.build()
        win, services = open_window(qapp, seed, FakeWriter(seed.library, apply=False))
        made.append((win, services))
        return win, services
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


@pytest.fixture
def looks_imports(monkeypatch):
    """Each read of the looks' module from now on (an `import` or `importlib.import_module` while it is not in yet):
    whether the reading thread is the window's."""
    import importlib
    calls = []
    real, real_module = builtins.__import__, importlib.import_module

    def spy(name, globals=None, locals=None, fromlist=(), level=0):
        if LOOKS not in sys.modules and (
                name == LOOKS or (name == "app.services" and fromlist and "source_looks" in fromlist)):
            calls.append(threading.current_thread() is threading.main_thread())
        return real(name, globals, locals, fromlist, level)

    def spy_module(name, package=None):
        if name == LOOKS and name not in sys.modules:
            calls.append(threading.current_thread() is threading.main_thread())
        return real_module(name, package)
    monkeypatch.setattr(builtins, "__import__", spy)
    monkeypatch.setattr(importlib, "import_module", spy_module)
    return calls


def _unread(monkeypatch):
    """The looks' module as at the app's start: not read yet (the test process's own copy put back after)."""
    import app.services as services_pkg
    monkeypatch.delitem(sys.modules, LOOKS)
    monkeypatch.delattr(services_pkg, "source_looks")


def _made_here(win, monkeypatch, looks):
    """`_open_looks` recorded: the thread it ran on and whether the module was in by then; `looks` made."""
    runs = []

    def open_looks(writer):
        from app.services.source_looks import SourceLooks  # noqa: F401  (as the real one reads it)
        runs.append((threading.current_thread() is threading.main_thread(), LOOKS in sys.modules))
        win.looks = looks
        return looks
    monkeypatch.setattr(win, "_open_looks", open_looks)
    return runs


def test_the_first_look_reads_its_module_on_a_worker_and_makes_its_looks_on_the_window_thread(opened, monkeypatch,
                                                                                                  looks_imports):
    win, _services = opened()
    looks = RecordingLooks()
    runs = _made_here(win, monkeypatch, looks)
    _unread(monkeypatch)
    win._start_looks()
    assert not any(looks_imports), "the window's thread read the looks' module in the first frame's step"
    wait_until(lambda: runs and looks.asks)
    assert looks_imports and not any(looks_imports)          # read once, on a worker
    assert runs == [(True, True)]                              # the looks made here, the module in by then
    assert looks.asks == [(True, False, win.in_front())]       # the first look after start: a full one, as before


def test_a_module_read_already_or_a_tests_own_looks_are_made_at_once(opened, monkeypatch, looks_imports):
    # the module in (a language switch, a second window): no worker's round trip
    win, _services = opened()
    looks = RecordingLooks()
    runs = _made_here(win, monkeypatch, looks)
    win._start_looks()
    assert runs == [(True, True)] and looks.asks == [(True, False, win.in_front())]
    # a test's own looks (`services.source_looks`), the module not read: made at once too
    win2, services2 = opened()
    looks2 = RecordingLooks()
    services2.source_looks = looks2
    runs2 = _made_here(win2, monkeypatch, looks2)
    _unread(monkeypatch)
    win2._start_looks()
    assert runs2 == [(True, True)] and looks2.asks == [(True, False, win2.in_front())]


def test_no_looks_are_made_once_the_window_began_to_quit_before_the_module_came_in(opened, monkeypatch, looks_imports):
    win, services = opened()
    looks = RecordingLooks()
    runs = _made_here(win, monkeypatch, looks)
    _unread(monkeypatch)
    win._start_looks()
    services.closing.set()                                     # the quit began while the module was being read
    wait_until(lambda: looks_imports)
    wait_until(lambda: LOOKS in sys.modules)
    for _ in range(20):
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
    assert runs == [] and looks.asks == [] and win.looks is None
