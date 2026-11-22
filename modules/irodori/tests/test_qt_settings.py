# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings › App › Beta · *AI audio for cards without audio* (`qt_settings.py`) on a stand-in page: the switch writes
`enable_irodori` only; off, only the switch shows; on, the two lines and *Install* (or, installed, its size and
*Remove*); every look runs on a worker; *Stop* cancels an install.

What a wrong answer would cost: a download started without the press, a switch that writes another key, the GPU look
(nvidia-smi) on the window's thread, a *Remove* offered for nothing installed."""
import threading

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QWidget

from app.qt import settings_catalog as catalog
from modules.irodori import qt_settings, qt_strings as S, runtime


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _Bridge(QObject):
    settings_written = pyqtSignal(object)


class _Store:
    def __init__(self, values):
        self.values, self.sets = dict(values), []

    def get(self):
        return dict(self.values)

    def set(self, changes, **kw):
        self.sets.append(dict(changes))
        self.values.update(changes)


class _Page(QWidget):
    def __init__(self, values):
        super().__init__()
        self.store, self.bridge, self.shell = _Store(values), _Bridge(), None
        self.slot = QWidget(self)
        QHBoxLayout(self.slot)

    def custom_row(self, row_id):
        assert row_id == "ai_audio"
        return self.slot


def _wait(predicate, timeout=5.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def looked(monkeypatch):
    seen = []
    main = threading.main_thread()

    def gpu(run=None):
        seen.append(threading.current_thread() is not main)
        return None
    monkeypatch.setattr(runtime, "gpu", gpu)
    return seen


def _row(qapp, values):
    page = _Page(values)
    row = qt_settings.attach(page)
    page.show()
    return page, row


def test_the_row_is_in_the_catalog_only_with_the_module():
    row = catalog.ROW["ai_audio"]
    assert row.section == "app" and row.group == "beta" and row.keys == ("enable_irodori",)
    assert row.when({}, "ja", frozenset({"modules.irodori"})) and not row.when({}, "ja", frozenset())


def test_off_shows_only_the_switch_and_nothing_downloads(qapp, looked, monkeypatch):
    monkeypatch.setattr(runtime, "install", lambda **k: pytest.fail("installed without the press"))
    page, row = _row(qapp, {"enable_irodori": False})
    assert _wait(lambda: row.state is not None)
    assert looked == [True]                                         # nvidia-smi on a worker
    assert not row.about.isVisible() and not row.install.isVisible() and not row.remove.isVisible()


def test_ticking_it_writes_its_own_key_and_offers_install_with_size_and_speed(qapp, looked):
    page, row = _row(qapp, {"enable_irodori": False})
    assert _wait(lambda: row.state is not None)
    row.toggle._toggle()
    assert _wait(lambda: page.store.sets == [{"enable_irodori": True}])
    assert row.install.isVisible() and not row.remove.isVisible()
    assert row.line.text() == S.NEEDS_INSTALL.format(gb="5")


def test_fresh_u_its_time_is_said_quietly_in_the_lines_hover_never_on_screen(qapp, looked, installed, monkeypatch):
    # the time a sentence takes (15–34 s on a processor, as measured; a 300-card book about 2–3 hours) is in the
    # install line's hover and in *Make it*'s, never in a visible line or a warning (words PROVISIONAL)
    assert S.TIME_CPU == ("On your processor: about 15–34 seconds a sentence, made in the background. A 300-card "
                          "book takes about 2–3 hours.")
    assert "15–34 seconds" in S.MAKE_TIP and "background" in S.MAKE_TIP
    assert "second" not in S.NEEDS_INSTALL and "second" not in S.INSTALLED and "second" not in S.ABOUT
    page, row = _row(qapp, {"enable_irodori": True})
    assert _wait(lambda: row.state is not None)
    assert row.line.text() == S.INSTALLED.format(gb="4.9", where=S.WHERE_CPU) and row.line.toolTip() == S.TIME_CPU
    assert row.line.property("tone") in (None, "")                   # never a warning's tone
    monkeypatch.setattr(row, "state", ({"installed": False}, "cu128", {"name": "RTX 4070"}))
    row._looked(row.state)
    assert row.line.text() == S.NEEDS_INSTALL.format(gb="8") and "second" not in row.line.text()
    assert row.line.toolTip() == S.TIME_GPU.format(card="RTX 4070")
    # installed, its own backend says the time — never Install's choice of today
    row._looked(({"installed": True, "backend": "cu128", "size_bytes": 8.4e9}, "cpu", {"name": "RTX 4070"}))
    assert row.line.toolTip() == S.TIME_GPU.format(card="RTX 4070")
    row._looked(({"installed": True, "backend": "cpu", "size_bytes": 4.9e9}, "cu128", {"name": "RTX 4070"}))
    assert row.line.toolTip() == S.TIME_CPU


def test_installed_shows_its_size_and_remove(qapp, looked, installed):
    page, row = _row(qapp, {"enable_irodori": True})
    assert _wait(lambda: row.state is not None)
    assert row.line.text() == S.INSTALLED.format(gb="4.9", where=S.WHERE_CPU)
    assert row.remove.isVisible() and not row.install.isVisible()


def test_install_reports_its_steps_and_stop_cancels_it(qapp, looked, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def install(say=None, cancel=None, **k):
        say(3, 6, "PyTorch")
        started.set()
        while not cancel.is_set():
            release.wait(0.01)
        raise runtime.Cancelled()
    monkeypatch.setattr(runtime, "install", install)
    page, row = _row(qapp, {"enable_irodori": True})
    assert _wait(lambda: row.state is not None)
    row.install.click()
    assert started.wait(5)
    assert _wait(lambda: row.line.text() == S.INSTALLING.format(step=3, of=6, what="PyTorch"))
    assert row.stop.isVisible() and not row.install.isVisible()
    row.stop.click()
    assert _wait(lambda: row.installing is None and row.install.isVisible(), 10)
    assert not row.stop.isVisible()


def test_remove_deletes_and_offers_install_again(qapp, looked, installed):
    page, row = _row(qapp, {"enable_irodori": True})
    assert _wait(lambda: row.remove.isVisible())
    row.remove.click()
    assert _wait(lambda: row.install.isVisible())
    assert not runtime.status()["installed"]
