"""The Qt test harness (W2.1; the window's spec 07 §7.1, §7.3; the python-desktop stack pack's harness layer).

- **Offscreen:** `QT_QPA_PLATFORM=offscreen` is set before PyQt6 is imported: the window is built, wired and painted
  into images, and nothing opens on the developer's desktop. (Offscreen has no real fonts: assert properties, and read
  pixels for colours, never text widths.)
- **One QApplication** for the session, with the shell's look; after each test the look is put back (Blue, M) and any
  app-wide filter a test left is removed, so no test inherits another's state (the stack pack: anything held globally
  is per-test).
- **Per-test single instance:** each test gets its own pipe name (`SURASURA_INSTANCE_NAME`); its lock lives under the
  test's own root (the core conftest's `SURASURA_TEST_ROOT`), as does every file the window writes.
- **The freeze switch** (`SURASURA_FREEZE_MOTION=1`): tooltips and every timed look show at once.
- **Exceptions in slots** are caught and fail the test that raised them (PyQt6 would otherwise abort the process).
- The core conftest's network guard covers these tests too (loopback only).

Without PyQt6 (a 2.x checkout) the folder is skipped with its reason — **except on GitHub's runner**, where a missing
PyQt6 means the install step is wrong, and the run fails rather than going green with no window tested.
"""
import importlib.util
import os
import sys
import uuid

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_SCALE_FACTOR", "1")

HAVE_QT = importlib.util.find_spec("PyQt6") is not None
REASON = "PyQt6 is not installed: the 3.0 window's tests run on the 3.0 line (requirements.txt)"

if not HAVE_QT and os.environ.get("GITHUB_ACTIONS") == "true":
    raise RuntimeError("PyQt6 is missing on CI: the window's tests would be skipped and the run would pass untested")


def pytest_collection_modifyitems(config, items):
    if HAVE_QT:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    skip = pytest.mark.skip(reason=REASON)
    for item in items:
        if str(item.fspath).startswith(here):
            item.add_marker(skip)


_errors = []


def _record(kind, value, tb):
    _errors.append((kind, value, tb))


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    from app.qt import style
    app = QApplication.instance() or QApplication(["surasura-tests"])
    sys.excepthook = _record
    style.apply(app, "night", "M", "ja")
    yield app


@pytest.fixture(autouse=True)
def _per_test_window_state(request, monkeypatch):
    """Every window test: its own instance name, the freeze switch on, no slot exception left unread; afterwards
    the windows closed, the look back to the defaults, stray app filters gone."""
    if not HAVE_QT:
        yield
        return
    monkeypatch.setenv("SURASURA_INSTANCE_NAME", f"surasura-test-{uuid.uuid4().hex[:12]}")
    monkeypatch.setenv("SURASURA_FREEZE_MOTION", "1")
    app = request.getfixturevalue("qapp")
    from PyQt6.QtCore import QCoreApplication, QEvent
    from app.qt import freeze, style
    freeze.set_frozen(None)
    _errors.clear()
    from app.services import source_looks
    looks, made = source_looks.SourceLooks.__init__, []

    def made_looks(self, *a, **k):                # each window's source-folder looks (SRC W1b), waited for after
        looks(self, *a, **k)
        made.append(self)
    monkeypatch.setattr(source_looks.SourceLooks, "__init__", made_looks)
    before = list(app.children())                 # (some children aren't hashable: compared by identity)
    yield
    qt_bridge = sys.modules.get("app.qt.bridge")
    if qt_bridge is not None and hasattr(qt_bridge, "drop_answers"):
        qt_bridge.drop_answers()                  # before any window goes: an answer on its way lands on nothing (a
        #   window whose close was put off — a move or a job still pending — never ran its own drop)
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    # A closed window's looks end on their own thread once the look under way lets go: one still opening its store
    # after the test's root was gone wrote the run's own local data folder (a later test's guard failed). Waited for
    # here, while the root is still set; an idle one returns at once.
    for one in made:
        one.idle(10)
    # The same for the window's thread-pool workers (`bridge.run_in_worker`): a closed window's Needs you gather still
    # reading its seen file (`needs.seen_path` -> get_local_data_path) in the instant between pytest clearing
    # PYTEST_CURRENT_TEST and the harness setting it again met neither guard and made the run's own local data folder
    # (the next test's guard failed, about one run in four). Waited for as the app's quit waits (its answers dropped:
    # the window is gone), while the root is still set.
    qt_bridge = sys.modules.get("app.qt.bridge")
    if qt_bridge is not None:
        qt_bridge.wait_for_workers(10000)
    # A test's own filters and helpers parented to the app: only objects of classes written in Python (a test's or the
    # window's). Qt parents its own objects to the app as it goes (an input device on the first click, …); deleting
    # one of those corrupts Qt and crashes a later test (seen: a window made 80 tests on died in its constructor).
    for child in [c for c in app.children() if not any(c is b for b in before)]:
        if type(child).__module__.startswith("PyQt6"):
            continue
        try:
            app.removeEventFilter(child)
            child.deleteLater()
        except RuntimeError:
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    stones = sys.modules.get("app.qt.stones")
    if stones is not None:                        # (AD-13) a window that never painted nor went: its hold let go
        for token in list(stones._HELD):
            stones.release(token)
    if style.current()[:2] != ("night", "M"):
        style.apply(app, "night", "M", "ja")
    freeze.set_frozen(None)
    errors = list(_errors)
    _errors.clear()
    if errors and not getattr(request.node, "_qt_errors_expected", False):
        import traceback
        pytest.fail("an exception escaped a Qt slot:\n" + "".join(traceback.format_exception(*errors[0])))


@pytest.fixture
def qt_errors(request):
    """A test that expects a slot to raise reads the errors here (and the harness doesn't fail it for them)."""
    request.node._qt_errors_expected = True
    return _errors


def logos_in(strip, timeout=60.0):
    """The phase strip's logos decoded and painted (`PhaseStrip._load_logos` draws them on a worker): every test that
    reads what the strip paints — its rings' pixels, its `paints` counts, a window's paint events — waits here first.
    On a busy machine (the full run, GitHub's runners) they land late, and their one paint is the strip still opening,
    not the change under test (alpha 3's cut: a setting-paint test and an at-rest ring test both read it). The ceiling
    is generous: it is only ever reached when they never come. -> True once they are in."""
    from PyQt6.QtWidgets import QApplication
    ok = wait_until(lambda: set(strip._pix) >= set(strip.logos), timeout)
    for _ in range(20):                                  # their repaint, done before the caller watches
        QApplication.processEvents()
    return ok


def needs_in(win, timeout=60.0):
    """Needs you's entries worked out for the view the window shows (`NeedsYou` gathers them on a worker): every test
    that watches a window's paint events waits here first. On a busy machine the first answer lands after the window
    opened, and its one paint — the *Needs you* tab shown with its count, the tab bar laid out again under it — is the
    window still opening, not the change under test (alpha 3's cut: two S19 tests saw the tab bar repaint, a4's
    `flake-probe.log`). A window without the controller (no library) has nothing to wait for. -> True once it is in."""
    from PyQt6.QtWidgets import QApplication
    ny = getattr(win, "needs_you", None)
    page = getattr(win, "page_widgets", {}).get("needs")
    if ny is None or page is None:
        return True
    ok = wait_until(lambda: ny.view is not None and ny.view is page.view_model and ny.gathers > 0
                    and not ny._running and not ny._again, timeout)
    for _ in range(20):                                  # its repaint, done before the caller watches
        QApplication.processEvents()
    return ok


def wait_until(predicate, timeout=5.0):
    """Run the event loop until `predicate()` is true (or the time is up). -> its last answer."""
    import time
    from PyQt6.QtWidgets import QApplication
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    QApplication.processEvents()
    return predicate()
