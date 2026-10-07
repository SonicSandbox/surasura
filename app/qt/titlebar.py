"""Windows' own title bar in the theme's colours (W2.1; the window's spec 01 §1.2 n1, 05 §5.5, §5.11, 06 E24).

Windows 11 (build 22000+) lets an app colour its caption, border and caption text: DWM attributes 35, 34 and 36, one
call each when the window is made and again when the theme changes. Windows 10 refuses them (this PC, build 17763,
measured: E_INVALIDARG), so there the shell makes no call and the bar is Windows' dark one, which Qt asks for from the
colour scheme `style.apply` sets (P-title, W2.1 row 0). Under high contrast Windows' own colours stay (E24). Anywhere
else it is a no-op, never an error.
"""
import sys

from app import theme
from app.qt import applog

DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36
WINDOWS_11 = 22000

_logged = set()


def _log_once(key, msg):
    if key not in _logged:
        _logged.add(key)
        applog.log("title bar", msg)


def colorref(hex_colour):
    """`#rrggbb` -> a Win32 COLORREF (0x00bbggrr)."""
    r, g, b, _a = theme.parse(hex_colour)
    return int(r) | (int(g) << 8) | (int(b) << 16)


def _windows_build():
    try:
        return sys.getwindowsversion().build
    except AttributeError:
        return None


def _high_contrast():
    try:
        import ctypes
        from ctypes import wintypes

        class HIGHCONTRAST(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwFlags", wintypes.DWORD), ("lpszDefaultScheme", wintypes.LPWSTR)]
        hc = HIGHCONTRAST()
        hc.cbSize = ctypes.sizeof(HIGHCONTRAST)
        if ctypes.windll.user32.SystemParametersInfoW(0x0042, hc.cbSize, ctypes.byref(hc), 0):   # SPI_GETHIGHCONTRAST
            return bool(hc.dwFlags & 0x1)                                                     # HCF_HIGHCONTRASTON
    except Exception:
        pass
    return False


def _dwm_set(hwnd, attribute, value):
    import ctypes
    v = ctypes.c_uint(value)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attribute, ctypes.byref(v),
                                                       ctypes.sizeof(v))


# Seams for the tests (no Windows 11 here): what the platform is, and the call itself.
platform = sys.platform
windows_build = _windows_build
high_contrast = _high_contrast
set_attribute = _dwm_set


def apply(window, theme_name):
    """Colour `window`'s title bar for `theme_name` where Windows allows it. -> what happened, in a word:
    "applied" · "windows10" · "high-contrast" · "not-windows" · "failed"."""
    if platform != "win32":
        return "not-windows"
    build = windows_build()
    if build is None or build < WINDOWS_11:
        _log_once("w10", f"Windows build {build} takes no caption colours; the dark bar is Windows' own")
        return "windows10"
    if high_contrast():
        return "high-contrast"
    bar = theme.TITLE_BAR.get(theme_name, theme.TITLE_BAR[theme.DEFAULT_THEME])
    hwnd = int(window.winId())
    results = [set_attribute(hwnd, DWMWA_CAPTION_COLOR, colorref(bar["caption"])),
               set_attribute(hwnd, DWMWA_BORDER_COLOR, colorref(bar["border"])),
               set_attribute(hwnd, DWMWA_TEXT_COLOR, colorref(bar["text"]))]
    if any(r != 0 for r in results):
        _log_once("fail", f"DwmSetWindowAttribute answered {[hex(r & 0xFFFFFFFF) for r in results]}")
        return "failed"
    return "applied"
