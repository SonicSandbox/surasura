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

Qt (3.0's window) gets the same through `QT_QPA_PLATFORM=offscreen`, inherited by child processes too.
`SURASURA_SHOW_TEST_WINDOWS=1` shows the windows again, to watch a GUI test. GitHub's runner shows nothing anyway:
there it does nothing.
"""
import os
import sys

DESKTOP = "SurasuraTests"
_held = []                                  # the desktop's handle, kept for the life of the process


def quiet_windows():
    """Move this thread's windows to the tests' own desktop (Windows), and Qt off-screen. Returns whether the
    desktop was taken; anything that fails leaves the windows where they were, never fails a run."""
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
        desktop = user32.CreateDesktopW(DESKTOP, None, None, 0, 0x10000000, None)    # GENERIC_ALL; opens it if there
        if not desktop or not user32.SetThreadDesktop(desktop):
            return False                    # this thread already has a window: it stays on the user's desktop
    except Exception:
        return False
    _held.append(desktop)
    return True
