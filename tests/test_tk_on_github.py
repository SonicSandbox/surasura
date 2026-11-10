"""tests/tk_on_github.py: the Tk window tests run everywhere, GitHub's runner too (3.0.1, tests/FLAKES.md: the 3.0.0
cut's update-state red was a Tk test no pull request had run); a run that asks (SURASURA_SKIP_TK_TESTS=1) skips them.

The samples below start Tk in their own source and are never collected (plain classes and functions without
the test prefix); the tests themselves never spell a Tk start, so they run on the runner too.
"""
import tkinter

import pytest

from tests import tk_on_github


class _WindowInSetUpClass:
    @classmethod
    def setUpClass(cls):
        cls.root = tkinter.Tk()

    def test_title(self):
        pass


class _WindowInBase(_WindowInSetUpClass):
    def test_inherited(self):
        pass


class _NoWindow:
    def test_counts(self):
        assert len("知らせる") == 4


def _window_in_body():
    root = tkinter.Tk()
    root.destroy()


def _window_mocked():
    from unittest.mock import patch
    with patch.object(tkinter, "Tk"):
        pass


class _Item:
    """What skip_tk_tests reads from a pytest item: its class or function, and the markers it is given."""

    def __init__(self, cls=None, function=None):
        self.cls, self.function, self.markers = cls, function, []

    def add_marker(self, marker):
        self.markers.append(marker)


def _items():
    return {
        "setUpClass": _Item(cls=_WindowInSetUpClass),
        "base": _Item(cls=_WindowInBase),
        "body": _Item(function=_window_in_body),
        "no window": _Item(cls=_NoWindow),
        "mocked": _Item(function=_window_mocked),
    }


@pytest.mark.parametrize("github", [None, "true"], ids=["this-desktop", "githubs-runner"])
def test_unasked_nothing_is_skipped_and_tk_starts_as_ever_on_github_too(monkeypatch, github):
    """No SURASURA_SKIP_TK_TESTS: every Tk test runs, here and on GitHub's runner alike — no marker, Tk's start
    untouched by the skip (the same tests everywhere)."""
    monkeypatch.delenv(tk_on_github.SKIP_SWITCH, raising=False)
    if github:
        monkeypatch.setenv("GITHUB_ACTIONS", github)
    else:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(tkinter.Tk, "__init__", tkinter.Tk.__init__)   # restored after, whatever happens
    before = tkinter.Tk.__init__
    items = _items()
    tk_on_github.skip_tk_tests(list(items.values()))
    assert all(not item.markers for item in items.values())
    assert tkinter.Tk.__init__ is before
    assert not tk_on_github.skipping()


def test_asked_every_test_that_starts_tk_is_skipped_up_front_with_the_reason(monkeypatch):
    """A setUpClass, an inherited setUpClass and a test body that start Tk are skipped before any setup runs (a
    setUpClass that failed half-way would leave its state behind); a test with no window, or a mocked Tk, runs."""
    monkeypatch.setenv(tk_on_github.SKIP_SWITCH, "1")
    monkeypatch.setattr(tkinter.Tk, "__init__", tkinter.Tk.__init__)
    items = _items()
    tk_on_github.skip_tk_tests(list(items.values()))
    skipped = {name for name, item in items.items() if item.markers}
    assert skipped == {"setUpClass", "base", "body"}
    for name in skipped:
        (marker,) = items[name].markers
        assert marker.name == "skip"
        assert marker.kwargs["reason"] == tk_on_github.REASON


def test_asked_a_tk_start_the_scan_cannot_see_skips_its_test(monkeypatch):
    """A window started in a fixture or in the code under test skips its test with the same reason; an `except
    Exception` around the start can't swallow the skip."""
    monkeypatch.setenv(tk_on_github.SKIP_SWITCH, "1")
    monkeypatch.setattr(tkinter.Tk, "__init__", tkinter.Tk.__init__)
    tk_on_github.skip_tk_tests([])
    start = tkinter.Tk
    with pytest.raises(pytest.skip.Exception, match="SURASURA_SKIP_TK_TESTS"):
        try:
            start()
        except Exception:
            pytest.fail("the skip was swallowed as an ordinary error")


def test_githubs_runner_steadies_tks_start_as_this_desktop_does(monkeypatch):
    """The runner's Tk read fault is the one loaded local runs show: Tk's own start is tried again there too (never
    the test), so the window tests can run on every pull request."""
    from tests import quiet_windows
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("SURASURA_SHOW_TEST_WINDOWS", "1")          # (the desktop itself is not this test's)
    monkeypatch.setattr(tkinter.Tk, "__init__", lambda self, *a, **k: None)
    quiet_windows.quiet_windows()
    assert getattr(tkinter.Tk.__init__, "_steady", False)
