"""The Qt test harness itself (W2.1 row 2; tests/qt/conftest.py).

What a wrong answer would cost: a harness that opens real windows tests the developer's desktop (and floods it); one
that shares a single-instance name between tests passes alone and fails in the full run; one that leaves the last
test's theme or filters on the one QApplication makes the next test's pixels lie.
"""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QGuiApplication

from app.qt import freeze, style

_names = []


def test_the_platform_is_offscreen(qapp):
    assert QGuiApplication.platformName() == "offscreen"
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"


@pytest.mark.parametrize("run", [1, 2])
def test_each_test_has_its_own_single_instance_name(qapp, run):
    name = os.environ["SURASURA_INSTANCE_NAME"]
    assert name.startswith("surasura-test-")
    assert name not in _names
    _names.append(name)


def test_the_freeze_switch_is_on_for_window_tests(qapp):
    assert freeze.frozen()
    freeze.set_frozen(False)
    assert not freeze.frozen()


def test_the_test_root_holds_the_windows_files(qapp):
    from app import path_utils
    assert path_utils.get_local_data_path().startswith(os.environ["SURASURA_TEST_ROOT"])


class _Swallow(QObject):
    def eventFilter(self, obj, event):
        return event.type() == QEvent.Type.KeyPress


def test_a_test_that_changes_the_look_and_leaves_a_filter(qapp):
    # This one leaves Sapphire at L and a key-swallowing filter parented to the app; the next test must see neither.
    style.apply(qapp, "sapphire", "L", "ja")
    qapp.installEventFilter(_Swallow(qapp))
    assert style.current()[:2] == ("sapphire", "L")


def test_the_next_test_gets_the_defaults_back(qapp):
    assert style.current()[:2] == ("hb", "M")
    assert qapp.palette().window().color().name() == "#111419"
    assert not [c for c in qapp.children() if isinstance(c, _Swallow)]


def test_a_slot_that_raises_is_reported_not_fatal(qapp, qt_errors):
    from PyQt6.QtCore import QTimer
    from tests.qt.conftest import wait_until

    def boom():
        raise ValueError("a slot's fault")
    QTimer.singleShot(0, boom)
    assert wait_until(lambda: bool(qt_errors))
    assert qt_errors[0][0] is ValueError
