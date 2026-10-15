"""The ported windows with the optional modules removed, and without Tk (W3.4 row 1; the RUNBOOK's *prove*: no Tk
imported on the 3.0 line; CLAUDE.md's modularity rule, RD-S10).

What a wrong answer would cost: a door on the Settings tab for a module the build doesn't have (a dead button, or a
crash on click); a ported window that still pulls in `tkinter` (3.0 ships no Tk: G1.2-1); a missing module taking the
core windows down with it.

Each case runs in a child process, offscreen, in its own test root; with `block_modules`, its import system refuses
every `modules.*` import, as a build without the folder would.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("PyQt6")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CHILD = """
import importlib.abc, json, os, sys

class NoModules(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if BLOCK and (name == "modules" or name.startswith("modules.")):
            raise ModuleNotFoundError(f"No module named {name!r} (this build has no modules)")
        return None
sys.meta_path.insert(0, NoModules())

from PyQt6.QtWidgets import QApplication
from app.qt import shell, windows
app = QApplication(["w34-modules-absent"])
services = shell.Services()
win = shell.open_window(app, services)
win.show()
row = windows.launchers(win, win.page_widgets["settings"])   # the Settings tab's doors (the shell's hook: its owner's step)
win.show_tab("settings")
import time
app.processEvents()
deadline = time.monotonic() + 20
def looking():                                       # the doors' modules are looked for on a worker
    return windows._LOOKING or any(op.module and op.module not in windows._FOUND for op in windows.OPENERS)
while looking() and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
doors, opened = {}, {}
for op in windows.OPENERS:
    shown = not row.buttons[op.name].isHidden()
    doors[op.name] = [shown, op.module]
    if shown:
        w = windows.launch(win, op)
        app.processEvents()
        opened[op.name] = w is not None and w.isVisible()
result = {"doors": doors, "opened": opened, "tk": sorted(m for m in sys.modules if "tkinter" in m),
          "bar": win.bar_line.full(), "junban_found": windows.module_present("junban")}
for w in app.topLevelWidgets():
    w.close()
services.shutdown(0.5)
from app.qt import bridge
bridge.wait_for_workers(5000)                        # no pool worker still running Python as the process ends
# Every window deleted now, in Qt's order, while the application lives: left to the interpreter's finalization, a
# window outliving the QApplication crashed the exit now and then (0xC0000005) once rows 2-3's windows were here.
from PyQt6.QtCore import QCoreApplication, QEvent
for w in app.topLevelWidgets():
    w.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
app.processEvents()
sys.stdout.write("\\n" + json.dumps(result) + "\\n")
"""


def _run(tmp_path, block_modules):
    script = f"BLOCK = {block_modules!r}\n" + textwrap.dedent(_CHILD)
    env = dict(os.environ, PYTHONPATH=ROOT, SURASURA_TEST_ROOT=str(tmp_path), QT_QPA_PLATFORM="offscreen",
               SURASURA_FREEZE_MOTION="1", SURASURA_INSTANCE_NAME=f"w34-absent-{os.getpid()}-{block_modules}")
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(tmp_path), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_with_every_module_removed_their_doors_hide_and_the_core_windows_open_without_tk(tmp_path):
    result = _run(tmp_path, block_modules=True)
    for name, (shown, module) in result["doors"].items():
        assert shown == (module is None), (name, module)    # a module's door hides; a core door stays
        if module is None:
            assert result["opened"][name], name
    assert {"frequency-lists", "sentence-dictionary"} <= set(result["opened"])
    assert result["tk"] == [] and result["bar"] == ""
    assert result["junban_found"] is False                  # the witness: the child's build really has no modules


def test_opening_every_window_whose_door_shows_imports_no_tkinter(tmp_path):
    result = _run(tmp_path, block_modules=False)
    assert result["opened"] and all(result["opened"].values())
    assert result["tk"] == []
    assert result["junban_found"] is os.path.isdir(os.path.join(ROOT, "modules", "junban"))
