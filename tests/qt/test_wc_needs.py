"""Work counts on Needs you (WC, 2026-11-06; the rules in `tests/qt/work_counts.py` and the Qt guide's §3 *Work counts*):
what each press costs the window — paints and where they land, layout passes, widgets made, views built — counted,
never timed. What a wrong answer would cost a learner: answering one card repainting every card.

The screen: test_needs_you's `world` fixture (one window a test: it sets Needs you's reads).
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from tests.qt import work_counts as wc
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import entry_of, rows_of, settle, world   # noqa: F401
from tests.qt.test_drag import _stones_sheet   # noqa: F401  (autouse: the stones drawn before the window opens)
