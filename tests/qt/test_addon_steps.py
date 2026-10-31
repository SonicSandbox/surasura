"""AnkiConnect missing, on screen (alpha 8, Mado-A): `app/qt/addon_steps.py` — *Copy code* and the watch that runs
*Check again* by itself (the wizard's and Settings' own tests drive them in place)."""
import threading

from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from app import ankiconnect_addon as A
from app.qt import addon_steps
from tests.qt.conftest import wait_until


def _button(text, tip, parent):
    b = QPushButton(text, parent)
    b.setToolTip(tip)
    return b


def test_a_second_copy_press_restarts_the_wait_and_the_name_comes_back_once(qapp, monkeypatch):
    monkeypatch.setattr(A, "COPIED_MS", 300)
    said = []
    host = QWidget()
    steps = addon_steps.AddonSteps(lambda text, tip: _button(text, tip, host), "wizsub", said.append, host)
    host.show()
    steps.copy.click()
    assert steps.copy.text() == A.COPIED and QApplication.clipboard().text() == A.CODE
    wait_until(lambda: False, 0.2)
    steps.copy.click()                                    # pressed again before the first wait ends
    wait_until(lambda: False, 0.2)                        # the first wait has ended by now
    assert steps.copy.text() == A.COPIED                  # ... and the second press keeps *Copied*
    assert wait_until(lambda: steps.copy.text() == A.COPY, 1)
    assert said == [A.COPIED_LINE] * 2
    host.close()


def test_the_watch_asks_only_while_armed_and_on_screen_one_look_at_a_time(qapp, monkeypatch):
    monkeypatch.setattr(A, "EVERY", 0.0)
    gate = threading.Event()
    asked, answered = [], []

    def answers(url):
        asked.append((url, threading.current_thread() is threading.main_thread()))
        gate.wait(5)
        return True
    monkeypatch.setattr(A, "answers", answers)
    host = QWidget()
    tick = QTimer()
    watch = addon_steps.Watch(host, tick, lambda: "http://127.0.0.1:8765", lambda: answered.append(1))
    tick.timeout.emit()
    assert asked == []                                    # not armed
    watch.arm(True)
    tick.timeout.emit()
    QApplication.processEvents()
    assert asked == []                                    # armed, but its part isn't on screen
    host.show()
    tick.timeout.emit()
    assert wait_until(lambda: asked == [("http://127.0.0.1:8765", False)])       # on a worker
    tick.timeout.emit()
    tick.timeout.emit()
    assert len(asked) == 1                                # a look out: the ticks wait for it
    gate.set()
    assert wait_until(lambda: answered == [1])
    tick.timeout.emit()
    QApplication.processEvents()
    assert len(asked) == 1 and answered == [1]            # once: the host arms it again if Anki still isn't in
    host.close()


def test_the_watch_waits_every_seconds_between_looks(qapp, monkeypatch):
    monkeypatch.setattr(A, "EVERY", 60.0)
    asked = []
    monkeypatch.setattr(A, "answers", lambda url: asked.append(url) or False)
    host = QWidget()
    host.show()
    tick = QTimer()
    watch = addon_steps.Watch(host, tick, lambda: "u", lambda: None)
    watch.arm(True)                                       # the host has just looked: the first look EVERY s on
    for _ in range(5):
        tick.timeout.emit()
    QApplication.processEvents()
    assert asked == []
    host.close()


def test_the_watch_stops_with_its_part_and_a_shell_without_a_poll_has_none(qapp, monkeypatch):
    monkeypatch.setattr(A, "EVERY", 0.0)
    asked = []
    monkeypatch.setattr(A, "answers", lambda url: asked.append(url) or True)
    host = QWidget()
    host.show()
    tick = QTimer()
    watch = addon_steps.Watch(host, tick, lambda: "u", lambda: None)
    watch.arm(True)
    host.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    tick.timeout.emit()                                   # nothing left listening: no slot runs on a gone part
    QApplication.processEvents()
    assert asked == []
    assert addon_steps.ticker(object()) is None
    assert addon_steps.ticker(type("Shell", (), {"_poll": tick})()) is tick
