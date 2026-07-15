"""The band slider's settings-save is debounced so a drag stays smooth.

A full save_settings (deep-merge + disk write + UI relayout) on every band crossing made the slider
stutter on big libraries / slower machines. These tests pin the debounce contract: rapid changes
collapse to a single pending save, the timer fires exactly one save (with skip_ui=True), and a
mouse-release flushes any pending save immediately so the setting is always persisted.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import MasterDashboardApp


class _FakeRoot:
    """Records after()/after_cancel() so we can drive the debounce without a real Tk event loop."""
    def __init__(self):
        self.scheduled = []      # list of (delay_ms, callback)
        self.cancelled = []
        self._n = 0

    def after(self, ms, cb):
        self._n += 1
        self.scheduled.append((ms, cb))
        return self._n

    def after_cancel(self, id_):
        self.cancelled.append(id_)


def _app():
    app = MasterDashboardApp.__new__(MasterDashboardApp)   # no Tk construction
    app.root = _FakeRoot()
    app._band_save_after = None
    app._saves = []
    app.save_settings = lambda *a, **k: app._saves.append(k)   # stub the real (heavy) save
    return app


def test_rapid_band_changes_collapse_to_one_pending_save():
    app = _app()
    # Simulate a drag crossing three bands quickly.
    app._save_band_debounced()
    app._save_band_debounced()
    app._save_band_debounced()

    assert len(app.root.scheduled) == 3          # rescheduled each time
    assert len(app.root.cancelled) == 2          # cancelled the two earlier timers
    assert app._saves == []                       # nothing written yet — the drag did no disk work

    # Fire the surviving timer -> exactly one save, and it skips the language-UI relayout.
    _delay, cb = app.root.scheduled[-1]
    assert _delay == 250
    cb()
    assert app._saves == [{"skip_ui": True}]


def test_release_flushes_pending_save_immediately():
    app = _app()
    app._save_band_debounced()                    # arm a pending save
    assert app._band_save_after is not None

    app._flush_band_save()                         # mouse-release
    assert app._saves == [{"skip_ui": True}]       # saved right away
    assert app._band_save_after is None            # pending cleared
    assert len(app.root.cancelled) == 1            # the pending timer was cancelled


def test_flush_with_nothing_pending_is_a_noop():
    app = _app()
    app._flush_band_save()
    assert app._saves == []
