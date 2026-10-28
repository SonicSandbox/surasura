"""The bridge and the strings (W2.1 row 4; the window's spec 04 §4.1, 05 §5.12).

What a wrong answer would cost: a service callback that touches a widget from its own thread crashes the window at
random (Qt's widgets live on one thread); snapshots that arrive out of order paint an older state last; a slot's fault
that stops the next listener leaves the bar frozen; a string written inline can never be translated (01 §1.5).
"""
import os
import re
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

from app.qt import bridge
from app.services import jobs as jobs_module
from app.services import status as status_service
from tests.qt.conftest import wait_until

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeService:
    """The services' subscribe shape: callbacks called on whatever thread changes something."""

    def __init__(self):
        self.listeners = []

    def subscribe(self, cb):
        self.listeners.append(cb)

    def tell(self, value):
        for cb in self.listeners:
            cb(value)


def test_a_callback_from_a_plain_thread_reaches_its_slot_on_the_gui_thread(qapp):
    svc = FakeService()
    b = bridge.Bridge(status=svc)
    seen = []
    b.status_changed.connect(lambda snap: seen.append((snap, QThread.currentThread() is qapp.thread())))
    t = threading.Thread(target=svc.tell, args=("snapshot-1",))
    t.start()
    t.join()
    assert seen == []                                 # queued, not called on the service's thread
    assert wait_until(lambda: seen)
    assert seen == [("snapshot-1", True)]


def test_a_hundred_snapshots_arrive_in_order(qapp):
    svc = FakeService()
    b = bridge.Bridge(status=svc)
    seen = []
    b.status_changed.connect(seen.append)
    t = threading.Thread(target=lambda: [svc.tell(i) for i in range(100)])
    t.start()
    t.join()
    assert wait_until(lambda: len(seen) == 100)
    assert seen == list(range(100))


def test_a_slot_that_raises_never_stops_the_next(qapp, qt_errors):
    svc = FakeService()
    b = bridge.Bridge(settings=svc)
    seen = []

    def broken(keys):
        raise RuntimeError("a listener's fault")
    b.settings_written.connect(broken)
    b.settings_written.connect(seen.append)
    svc.tell(["app_theme"])
    assert wait_until(lambda: seen)
    assert seen == [("app_theme",)]
    assert qt_errors and qt_errors[0][0] is RuntimeError


def test_a_callback_after_the_bridge_is_gone_is_dropped(qapp):
    svc = FakeService()
    b = bridge.Bridge(status=svc)
    b.deleteLater()
    from PyQt6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    svc.tell("late")                                  # no raise into the service


def test_a_relays_answer_on_its_way_when_its_window_goes_never_reaches_the_slot(qapp):
    """Alpha 4 (fix2): a worker answered (`relay.call` on its thread: the call queued), then the window holding the
    relay was deleted before the window's loop ran — the slot ran anyway, after its relay and window were gone
    (*Start fresh*'s counts: `relay.deleteLater()` on a deleted relay, a `RuntimeError` out of the slot). The answer
    is the relay's own: it goes with it."""
    from PyQt6.QtCore import QCoreApplication, QEvent, QObject
    holder = QObject()
    relay = bridge.Relay(holder)
    heard = []
    relay.said.connect(heard.append)
    t = threading.Thread(target=relay.call, args=("その後",))
    t.start()
    t.join()
    holder.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(5):
        QApplication.processEvents()
    assert heard == []


def test_a_relay_called_on_the_windows_thread_answers_at_once_and_from_a_worker_in_order(qapp):
    """The relay as before: on the window's own thread the slot runs in the call; from a worker, queued, in order."""
    relay = bridge.Relay(QApplication.instance())
    heard = []
    relay.said.connect(lambda v: heard.append((v, QThread.currentThread() is qapp.thread())))
    relay.call("今")
    assert heard == [("今", True)]
    t = threading.Thread(target=lambda: [relay.call(i) for i in range(50)])
    t.start()
    t.join()
    assert wait_until(lambda: len(heard) == 51)
    assert heard[1:] == [(i, True) for i in range(50)]
    relay.deleteLater()


# Round 8's crash, at its root: a service thread calling a signal's emit kept from an object the GUI thread has
# deleted (or is deleting) is an access violation — no Python error, the whole process ends (the writer's late landing
# on the drag's relay, deleted with its window; 1 run in 20 of test_finished). Raced in a child process, so a
# regression fails this test instead of killing the run: a service thread calls back without pause while the GUI
# thread makes and deletes the object, 600 times, through each road a window hands a service (a `Gate` on a relay of
# its own, a `Relay`, the `Bridge`). It proves the fresh, flag-checked lookup; the gate's lock (an emit and the
# deletion never overlap, as Qt requires) is defence in depth no race here has shown to be needed.
_RACE = r"""
import sys, threading, time
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from app.qt import bridge

app = QApplication([])


class Own(QObject):
    saving = pyqtSignal(bool)


class Svc:
    def __init__(self):
        self.cb = None

    def subscribe(self, cb):
        self.cb = lambda value: cb(value)


stop, current, raised = threading.Event(), [None], []


def service():
    while not stop.is_set():
        cb = current[0]
        if cb is not None:
            try:
                cb(True)
            except Exception as e:                      # a raise into the service is a fault too (it logs one)
                raised.append(repr(e))
        time.sleep(0)                                   # (the GIL let go between calls, as a real service's work does)


threading.Thread(target=service, daemon=True).start()
for i in range(600):
    holder = QObject()
    kind = i % 3
    if kind == 0:
        own = Own(holder)
        own.saving.connect(lambda v: None)
        current[0] = bridge.Gate(own).caller("saving")
    elif kind == 1:
        relay = bridge.Relay(holder)
        relay.said.connect(lambda v: None)
        current[0] = relay.call
    else:
        svc = Svc()
        b = bridge.Bridge(status=svc, parent=holder)
        b.status_changed.connect(lambda v: None)
        current[0] = svc.cb
    time.sleep(0.001)
    holder.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
stop.set()
print("survived", len(raised), raised[:1])
"""


def test_round8_a_service_calling_back_while_the_gui_thread_deletes_the_object_never_crashes(tmp_path):
    """Red first: a bare emit kept from the object — the drag's relay, Finished's and the search's as they were — died
    of an access violation 5 runs in 5 (the review's mutant, the gate caching its emit, too); through the gate every
    road survives and nothing is raised into the service."""
    import subprocess
    import sys
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=ROOT)
    proc = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _RACE], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-2000:])
    assert proc.stdout.split()[:2] == ["survived", "0"], proc.stdout               # and nothing raised into the service


def test_the_real_registry_and_status_service_reach_the_gui_thread(qapp):
    registry = jobs_module.JobRegistry()
    status = status_service.StatusService(registry)
    b = bridge.Bridge(registry=registry, status=status)
    lines = []
    b.status_changed.connect(lambda snap: lines.append(snap.lines))
    job = registry.record("generate", "Generating")
    assert wait_until(lambda: lines and lines[-1] == ("Generating",))
    job.finish()
    assert wait_until(lambda: lines[-1] == ())


def test_run_in_worker_runs_elsewhere_and_answers_on_the_gui_thread(qapp):
    answers = []
    ran_on = []

    def work(x):
        ran_on.append(threading.current_thread() is threading.main_thread())
        return x * 2
    bridge.run_in_worker(work, 21, then=lambda v: answers.append((v, QThread.currentThread() is qapp.thread())))
    assert wait_until(lambda: answers)
    assert answers == [(42, True)] and ran_on == [False]


def test_run_in_worker_hands_a_failure_back(qapp):
    failures = []

    def work():
        raise OSError("the file is held")
    bridge.run_in_worker(work, failed=lambda info: failures.append(info[0]))
    assert wait_until(lambda: failures)
    assert isinstance(failures[0], OSError)


# --- every user string through strings.py (05 §5.12) ----------------------------------------------------------------- #
_SETTERS = r"(?:setText|setToolTip|setWindowTitle|setAccessibleName|setAccessibleDescription|setPlaceholderText|" \
           r"setStatusTip|setWhatsThis|addItem|addAction|setTitle)"
_WIDGETS = r"(?:QLabel|QPushButton|QToolButton|QCheckBox|QRadioButton|QAction|QMenu|QGroupBox|QLineEdit)"
_LITERAL_CALL = re.compile(rf"\b(?:{_SETTERS}|{_WIDGETS})\(\s*f?[\"'][^\"']*[A-Za-z぀-鿿]")


def user_string_literals(source):
    return [line.strip() for line in source.splitlines() if _LITERAL_CALL.search(line)]


def test_the_string_scan_sees_an_inline_string():
    assert user_string_literals('    b = QPushButton("Generate", self)')
    assert user_string_literals("    w.setToolTip(f'{n} new words')")
    assert not user_string_literals("    b = QPushButton(strings.BAR_LOGS, footer)")
    assert not user_string_literals('    label.setText("")')


def _window_files(root=None):
    """Every window file a string could be written inline in: `app/qt/*.py` but its table, and every module's
    `modules/<name>/qt_*.py` but its `qt_strings.py` (W3.4, IK-3)."""
    root = root or ROOT
    for where, dirs, files in os.walk(os.path.join(root, "app", "qt")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py") and name != "strings.py":
                yield os.path.join(where, name)
    modules = os.path.join(root, "modules")
    for where, dirs, files in os.walk(modules) if os.path.isdir(modules) else ():
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.startswith("qt_") and name.endswith(".py") and name != "qt_strings.py":
                yield os.path.join(where, name)


def test_no_user_string_is_written_inline_under_app_qt():
    found = []
    for path in _window_files():
        with open(path, encoding="utf-8") as f:
            found += [f"{os.path.relpath(path, ROOT)}: {line}" for line in user_string_literals(f.read())]
    assert found == []


def test_the_string_scan_reads_the_module_windows_too(tmp_path):
    # IK-3's witness: a module window's inline string is found; its own table and its engine are not window files.
    fake = tmp_path / "modules" / "w34probe"
    fake.mkdir(parents=True)
    for name in ("qt_window.py", "qt_strings.py", "engine.py"):
        (fake / name).write_text('    b = QPushButton("Download", self)\n', encoding="utf-8")
    (tmp_path / "app" / "qt").mkdir(parents=True)
    files = sorted(os.path.basename(p) for p in _window_files(str(tmp_path)))
    assert files == ["qt_window.py"]


# --- W3.4: the quit waits for the workers (row 6's find: a worker running Python as the process ended crashed it) -- #
def test_waiting_for_the_workers_lets_a_running_task_end_and_drops_its_answer(qapp):
    import time
    answers, ended = [], []

    def slow():
        time.sleep(0.3)
        ended.append(True)
        return "late"
    bridge.run_in_worker(slow, then=answers.append)
    t0 = time.monotonic()
    assert bridge.wait_for_workers(5000) is True
    assert ended == [True] and time.monotonic() - t0 >= 0.25
    QApplication.processEvents()
    assert answers == []                                  # the window is going: its answer is dropped


def test_waiting_for_the_workers_gives_up_at_its_limit(qapp):
    import threading
    gate = threading.Event()
    bridge.run_in_worker(lambda: gate.wait(10))
    try:
        assert bridge.wait_for_workers(50) is False
    finally:
        gate.set()
        assert bridge.wait_for_workers(5000) is True
