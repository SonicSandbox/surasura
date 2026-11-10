"""Test windows open on a desktop of their own, never on the user's: nothing flashes up while a suite runs, and no
test window takes the keyboard from what the user is typing in.

Withdrawn or see-through windows aren't enough on Windows: Tk makes its process the foreground the moment its first
window is drawn, a withdrawn root included, so the user's keystrokes went to an invisible test window. A window on
another desktop (Win32 `CreateDesktop`) is never shown and never takes the foreground, and for Tk it is a normal
window: it maps, has a size and a place, takes focus inside its own app, takes events, grabs and the clipboard.

Each suite's conftest calls `quiet_windows()` as it is imported, before any test (or test module) opens a window: the
pytest process's main thread moves to the desktop, and every Tk window it opens lands there. Two kinds stay on the
user's desktop: a window opened by another thread, and one a test opens in a child process (a child starts on its
parent's first desktop) — such a child script calls `quiet_windows()` itself.

Tk's start is retried when it fails to read one of its own library files (`steady_tk_start`).

Qt (3.0's window) gets the same through `QT_QPA_PLATFORM=offscreen`, inherited by child processes too.
`SURASURA_SHOW_TEST_WINDOWS=1` shows the windows again: to watch a GUI test, or to find the dialog a run that seems
hung is waiting on (it waits there unseen). GitHub's runner shows nothing anyway: the desktop is left alone there.
"""
import os
import re
import sys
import time

DESKTOP = "SurasuraTests"
_held = []                                  # the desktop's handle, kept for the life of the process


# Tk reads its own library files (init.tcl, tk.tcl, ttk's) as it starts. With dozens of test processes starting Tk at
# once (three --all side by side, the core suite in shards) a read now and then fails: "couldn't read file
# .../ttk/notebook.tcl: no such file or directory", "Can't find a usable tk.tcl" — the fault GitHub's runner shows
# too. A window test then failed, or skipped itself as if Tk weren't installed.
_TK_START_GLITCH = re.compile(r"usable (init|tk)\.tcl|couldn't read file|tcl_findLibrary")


def steady_tk_start():
    """Retry a Tk start that failed to read Tk's own files: 3 tries, 0.5 s apart; any other TclError at once."""
    try:
        import tkinter
    except Exception:
        return
    real = tkinter.Tk.__init__
    if getattr(real, "_steady", False):
        return

    def __init__(self, *args, **kwargs):
        for attempt in range(3):
            try:
                return real(self, *args, **kwargs)
            except tkinter.TclError as e:
                if attempt == 2 or not _TK_START_GLITCH.search(str(e)):
                    raise
                time.sleep(0.5)
    __init__._steady = True
    tkinter.Tk.__init__ = __init__


def quiet_windows():
    """Move this thread's windows to the tests' own desktop (Windows), and Qt off-screen; Tk's start steadied. Returns
    whether the desktop was taken; anything that fails leaves the windows where they were, never fails a run."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        steady_tk_start()
    if os.environ.get("SURASURA_SHOW_TEST_WINDOWS") == "1":
        return False
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") == "true" or _held:
        return bool(_held)
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreateDesktopW.restype = wintypes.HANDLE
        user32.CreateDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD,
                                          wintypes.DWORD, ctypes.c_void_p]
        user32.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        desktop = user32.CreateDesktopW(DESKTOP, None, None, 0, 0x10000000, None)    # GENERIC_ALL; opens it if there
        if not desktop:
            return False
        if not user32.SetThreadDesktop(desktop):    # this thread already has a window (or a hook): it stays put
            user32.CloseDesktop(desktop)
            return False
    except Exception:
        return False
    _held.append(desktop)
    return True
