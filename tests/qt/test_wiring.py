"""The wiring check (W2.1 row 5; the window's spec 07 §7.1; the stack pack's harness layer: "the one to build first").

What a wrong answer would cost: a control built, styled, laid out and connected to nothing — the defect a demo can't
show and a person finds in ten seconds (hato: three reported, five found once the walk widened from QPushButton to
QAbstractButton). So the walk takes every QAbstractButton and every QAction in the window, shown or not, and asks
of each: is it connected, does it carry a tooltip (D17: every button and toggle), and if it has no words, does it name
itself first and to a screen reader (R4-1, 05 §5.9)? Later steps' screens join the walk by living in the window.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QAbstractButton, QCheckBox, QPushButton, QToolButton

from app.qt import shell


def _connected(obj):
    if isinstance(obj, QAbstractButton):
        if isinstance(obj, QToolButton) and (obj.menu() is not None or obj.defaultAction() is not None):
            return True
        signals = (obj.clicked, obj.toggled, obj.pressed, obj.released)
    else:
        if obj.menu() is not None:
            return True
        signals = (obj.triggered, obj.toggled)
    return any(obj.receivers(sig) > 0 for sig in signals)


def problems(window):
    """Every control in `window` that is unwired, untipped or unnamed, in words."""
    found = []
    controls = window.findChildren(QAbstractButton) + window.findChildren(QAction)
    for c in controls:
        label = c.text().strip() or c.objectName() or type(c).__name__
        if not _connected(c):
            found.append(f"{label}: connected to nothing")
        tip = " ".join((c.toolTip() or "").split())                 # whitespace collapsed (the stack pack)
        if isinstance(c, QAbstractButton):                          # (an action's tooltip is its text, a menu's line)
            if not tip:
                found.append(f"{label}: no tooltip")
            name = c.accessibleName().strip()
            if not c.text().strip():
                if not name:
                    found.append(f"{label}: no words and no accessible name")
                elif not tip.lower().startswith(name.lower()):
                    found.append(f"{label}: an icon-only control's tooltip must name it first")
    return found, len(controls)


@pytest.fixture
def window(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)


def test_every_button_and_action_in_the_window_is_wired_tipped_and_named(window):
    found, walked = problems(window)
    assert walked >= 5                                   # the tabs and the bar's chip, hidden ones included
    assert found == []


def test_the_walk_finds_a_dead_button_a_toggle_without_a_tip_and_a_nameless_icon(window):
    # The check's own witnesses — each a different class, so a narrow walk (QPushButton only) would miss two.
    dead = QPushButton("Generate", window.centralWidget())
    dead.setToolTip("Build your list")
    toggle = QCheckBox("Clips", window.centralWidget())
    toggle.toggled.connect(lambda _on: None)
    icon_only = QToolButton(window.centralWidget())
    icon_only.clicked.connect(lambda: None)
    icon_only.setToolTip("Opens the menu")
    action = QAction("Move to top", window)
    window.addAction(action)
    found, _ = problems(window)
    assert "Generate: connected to nothing" in found
    assert "Clips: no tooltip" in found
    assert any("no words and no accessible name" in f for f in found)
    assert "Move to top: connected to nothing" in found
    icon_only.setAccessibleName("More")
    found, _ = problems(window)
    assert any("must name it first" in f for f in found)
    icon_only.setToolTip("More: what else you can do with this item")
    found, _ = problems(window)
    assert not any("must name it first" in f or "no words" in f for f in found)


# --- the guide's rules that a scan can hold (GUI_Design_Guidelines_Qt.md §3, §4) ----------------------------------- #
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The five modal dialogs 05 §5.4 allows are built by later steps; each will be named here as it lands.
MODAL_ALLOWED = set()
_MODAL = re.compile(r"\bQMessageBox\b|\.exec\(\)|\bQProcess\b")


def _module_window_files():
    """Every module's window file — `modules/<name>/qt_*.py` (its `qt_strings.py` among them): W3.4 (IK-3) widens the
    guards to the module windows, the riskiest of the ports."""
    folder = os.path.join(ROOT, "modules")
    if not os.path.isdir(folder):
        return
    for where, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.startswith("qt_") and name.endswith(".py"):
                yield os.path.join(where, name)


def _window_sources():
    for where, dirs, files in os.walk(os.path.join(ROOT, "app", "qt")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(where, name), encoding="utf-8") as f:
                    yield name, f.read()
    for path in _module_window_files():
        with open(path, encoding="utf-8") as f:
            yield os.path.relpath(path, ROOT).replace(os.sep, "/"), f.read()


def test_no_modal_dialog_and_no_qprocess_in_the_window():
    # 05 §5.4: no modal dialogs but five named ones; 04 §4.1: children are started by the Qt-free services, never
    # QProcess. (`app.exec()` — the event loop itself — is shell.main's, and is allowed.)
    found = []
    for name, source in _window_sources():
        for n, line in enumerate(source.splitlines(), 1):
            if _MODAL.search(line) and "app.exec()" not in line and (name, n) not in MODAL_ALLOWED:
                found.append(f"{name}:{n}: {line.strip()}")
    assert found == []


def _string_tables():
    """The app's string table and every module's (`modules/<name>/qt_strings.py`, IK-3)."""
    yield os.path.join(ROOT, "app", "qt", "strings.py")
    for path in _module_window_files():
        if os.path.basename(path) == "qt_strings.py":
            yield path


_FOLDER_NAMES = re.compile(r"HighPriority|LowPriority|GoalContent")


def test_the_window_never_names_the_2x_folders():
    # User-facing words are Current · Soon · Goal · Finished · New arrivals (D17 / D23), never the folder names.
    found = []
    for path in _string_tables():
        with open(path, encoding="utf-8") as f:
            found += [f"{os.path.relpath(path, ROOT)}:{n}" for n, line in enumerate(f, 1) if _FOLDER_NAMES.search(line)]
    assert found == []


def test_the_guards_read_the_module_windows_too(tmp_path, monkeypatch):
    # IK-3's witness: a module window with a modal box, a QProcess and a folder name in its string table is caught —
    # the scans walk `modules/*/qt_*.py`, not only `app/qt`.
    fake = tmp_path / "modules" / "w34probe"
    fake.mkdir(parents=True)
    (fake / "qt_window.py").write_text("box = QMessageBox()\nrunner = QProcess()\n", encoding="utf-8")
    (fake / "qt_strings.py").write_text('DONE = "copied to HighPriority"\n', encoding="utf-8")
    (fake / "engine.py").write_text("x = QMessageBox  # not a window file: never read\n", encoding="utf-8")
    (tmp_path / "app" / "qt").mkdir(parents=True)
    (tmp_path / "app" / "qt" / "strings.py").write_text('OK = "Current"\n', encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", str(tmp_path))
    sources = dict(_window_sources())
    assert set(k for k in sources if k.startswith("modules/")) == {"modules/w34probe/qt_window.py",
                                                                   "modules/w34probe/qt_strings.py"}
    assert any(_MODAL.search(line) for line in sources["modules/w34probe/qt_window.py"].splitlines())
    assert [p for p in _string_tables() if "w34probe" in p]
    with pytest.raises(AssertionError):
        test_the_window_never_names_the_2x_folders()
    with pytest.raises(AssertionError):
        test_no_modal_dialog_and_no_qprocess_in_the_window()


def test_with_the_duties_and_the_update_sheet_open_every_control_is_wired_tipped_and_named(qapp):
    # W3.5: the header's Generate and journey, the bar's update mark, the sheet open while an update waits (its Stop it
    # buttons made as the list comes), Needs you's update cards — each wired, tipped and named, an overlay open.
    from app.services import updates as U
    from tests.qt.test_jobs_bar import World, _offer
    w = World(qapp, logs_folder=os.path.join(os.environ["SURASURA_TEST_ROOT"], "logs"))
    try:
        found, before = problems(w.win)
        assert found == []
        _offer(w)
        w.updates.push(state=U.WAITING, programs=(U.Program(7, "Content Manager", True),
                                                  U.Program("sync", "Anki sync", False)))
        from tests.qt.conftest import wait_until
        assert wait_until(lambda: w.win.duties.update_state.state == U.WAITING)
        w.win.open_update_sheet()
        failure = U.Failure("The automatic update didn't finish.", 0.0, False, "99.0", None)
        w.updates.push(state=U.WAITING, needs_you=(failure,))
        assert wait_until(lambda: w.win.duties.sheet.isVisible() and w.win.duties.cards.cards)
        found, walked = problems(w.win)
        assert walked > before
        assert found == []
    finally:
        w.close()
