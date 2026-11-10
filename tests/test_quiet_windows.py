"""tests/quiet_windows.py's steadied Tk start: a start that failed to read Tk's own files is tried again; any other
failure is not."""
import tkinter

import pytest

from tests import quiet_windows


def _fake_start(monkeypatch, errors):
    """tkinter.Tk.__init__ replaced by one raising `errors` in turn, then succeeding; the steadied start wraps it."""
    calls = []

    def start(self, *args, **kwargs):
        calls.append(1)
        if len(calls) <= len(errors):
            raise tkinter.TclError(errors[len(calls) - 1])
    monkeypatch.setattr(tkinter.Tk, "__init__", start)          # put back after the test, whatever happens
    monkeypatch.setattr(quiet_windows.time, "sleep", lambda s: None)
    quiet_windows.steady_tk_start()
    return calls


def test_a_start_that_could_not_read_tks_own_file_is_tried_again(monkeypatch):
    calls = _fake_start(monkeypatch, ['couldn\'t read file "C:/Python311/tcl/tk8.6/ttk/notebook.tcl": no such file or '
                                      'directory'])
    tkinter.Tk.__init__(object.__new__(tkinter.Tk))
    assert len(calls) == 2


def test_three_failed_reads_give_up_with_the_last_error(monkeypatch):
    calls = _fake_start(monkeypatch, ["Can't find a usable tk.tcl in the following directories"] * 3)
    with pytest.raises(tkinter.TclError, match="usable tk.tcl"):
        tkinter.Tk.__init__(object.__new__(tkinter.Tk))
    assert len(calls) == 3


def test_any_other_tk_error_is_raised_at_once(monkeypatch):
    calls = _fake_start(monkeypatch, ["no display name and no $DISPLAY environment variable"])
    with pytest.raises(tkinter.TclError, match="no display"):
        tkinter.Tk.__init__(object.__new__(tkinter.Tk))
    assert len(calls) == 1
