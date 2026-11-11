"""Tests that open a real Tk window run everywhere — GitHub's runner too — unless a run asks to skip them.

Until 3.0.1 they were skipped on GitHub's runner (it now and then failed to read Tk's own files: "Can't find a usable
init.tcl ... couldn't read file .../init.tcl: No error"), so a red in one showed first at a release cut's local --all
(3.0.0: the update-state test). That read fault is the one three local --alls side by side show too, and the harness
already steadies it for them (tests/quiet_windows.py `steady_tk_start`: Tk's own start tried again, never the test); it
now does on the runner as well, so every pull request runs the tests the --all runs (tests/FLAKES.md). A run that must
do without a window sets `SURASURA_SKIP_TK_TESTS=1`: every test that starts a Tk window is then skipped with REASON.

Each suite's conftest calls `skip_tk_tests(items)` from its `pytest_collection_modifyitems` hook. Two kinds of
Tk start it can't see: a window opened in a child process (mark the test with `skipif(skipping(), reason=REASON)`),
and one a test module opens as it is imported (collection runs before the hook; those modules already skip
themselves when that start fails).
"""
import inspect
import os
import re

import pytest

REASON = "needs a Tk window; this run was asked to skip them (SURASURA_SKIP_TK_TESTS=1)"
SKIP_SWITCH = "SURASURA_SKIP_TK_TESTS"

# A Tk start in a test's own source: tk.Tk(), tkinter.Tk(), TkinterDnD.Tk(), tkinter.Tcl().
_STARTS_TK = re.compile(r"\b(?:Tk|Tcl)\(")
_SEEN = {}                                  # a class or function -> whether its source starts Tk


def on_github():
    return os.environ.get("GITHUB_ACTIONS") == "true"


def skipping():
    """Whether this run was asked to skip the Tk window tests (never by being on GitHub alone)."""
    return os.environ.get(SKIP_SWITCH) == "1"


def _source_starts_tk(owner):
    """Whether a class's or function's source starts Tk; read once per owner (a class is read once, not once per
    test in it)."""
    if owner not in _SEEN:
        try:
            _SEEN[owner] = bool(_STARTS_TK.search(inspect.getsource(owner)))
        except (TypeError, OSError):        # no source to read (a builtin, a generated test)
            _SEEN[owner] = False
    return _SEEN[owner]


def starts_tk(item):
    """Whether the test's source starts Tk: its whole class (setUpClass and setUp included, and any base class
    that isn't unittest's or object), or the test function itself."""
    cls = getattr(item, "cls", None)
    if cls is not None:
        owners = [c for c in cls.__mro__ if c.__module__ not in ("builtins", "unittest.case")]
    else:
        owners = [getattr(item, "function", None)]
    return any(owner is not None and _source_starts_tk(owner) for owner in owners)


def skip_tk_tests(items):
    """With SURASURA_SKIP_TK_TESTS=1: skip, before any of its setup runs, every test whose source starts Tk; and make
    any other Tk start (in a fixture, or in the code under test) skip its test instead of failing it."""
    if not skipping():
        return
    skip = pytest.mark.skip(reason=REASON)
    for item in items:
        if starts_tk(item):
            item.add_marker(skip)
    try:
        import tkinter
    except Exception:                       # no tkinter at all: nothing starts a window
        return

    def no_window(self, *args, **kwargs):
        pytest.skip(REASON)

    tkinter.Tk.__init__ = no_window
