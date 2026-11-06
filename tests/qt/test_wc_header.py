"""Work counts on the header (tabs, the level, New arrivals' inset) (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: a tab switch or a pop that redraws the whole window.

The screen: the window built once for the file (`screen` -> (seed, win, writer)); every test puts back what it changed.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until


@pytest.fixture(scope="module")
def screen(qapp, tmp_path_factory):
    with wc.window_screen(qapp, tmp_path_factory, "header", writer="arrivals") as s:
        yield s
