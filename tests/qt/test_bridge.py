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


def test_no_user_string_is_written_inline_under_app_qt():
    found = []
    for where, dirs, files in os.walk(os.path.join(ROOT, "app", "qt")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py") and name != "strings.py":
                with open(os.path.join(where, name), encoding="utf-8") as f:
                    found += [f"{name}: {line}" for line in user_string_literals(f.read())]
    assert found == []
