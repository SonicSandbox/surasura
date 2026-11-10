"""Surasura 3.0's window, in PyQt6 (the window's spec, `docs/agent instructions/3.0/W1.2-window/`; W2.1 on).

The only place Qt is imported (with `modules/*/qt_*.py`; tests/test_import_guard.py holds it). The window decides
nothing: it calls the Qt-free services (`app/services/`, `app/theme.py`) through `bridge.py` and paints what they say.
"""
import time as _time

IMPORTED_AT = _time.perf_counter()    # where the start's first phase ends: Python and app_entry (hud.Probe's phases)
