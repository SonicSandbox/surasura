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
    style.apply(app, "hb", "M", "ja")
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
    before = list(app.children())                 # (some children aren't hashable: compared by identity)
    yield
    for w in app.topLevelWidgets():
        w.close()
        w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
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
    if style.current()[:2] != ("hb", "M"):
        style.apply(app, "hb", "M", "ja")
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
