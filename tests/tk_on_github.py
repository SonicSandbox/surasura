"""Tests that open a real Tk window are skipped on GitHub's runner, and only there.

GitHub's hosted Windows runner now and then can't start Tk at all ("Can't find a usable init.tcl ... couldn't
read file .../init.tcl: No error"), a fault inside the runner, and re-running only costs time. So on the runner
(`GITHUB_ACTIONS=true`) every test that starts a Tk window is skipped with REASON. On this desktop nothing changes:
every one of them runs in `python run_tests.py --all`, the gate before every pull request.

Each suite's conftest calls `skip_tk_tests(items)` from its `pytest_collection_modifyitems` hook. Two kinds of
Tk start it can't see: a window opened in a child process (mark the test with `skipif(on_github(), reason=REASON)`),
and one a test module opens as it is imported (collection runs before the hook; those modules already skip
themselves when that start fails).
"""
import inspect
import os
import re

import pytest

REASON = "needs a Tk window; runs in the local --all"

# A Tk start in a test's own source: tk.Tk(), tkinter.Tk(), TkinterDnD.Tk(), tkinter.Tcl().
_STARTS_TK = re.compile(r"\b(?:Tk|Tcl)\(")
_SEEN = {}                                  # a class or function -> whether its source starts Tk


def on_github():
    return os.environ.get("GITHUB_ACTIONS") == "true"


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
    """On GitHub's runner: skip, before any of its setup runs, every test whose source starts Tk; and make any
    other Tk start (in a fixture, or in the code under test) skip its test instead of failing it."""
    if not on_github():
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
