""""Skip this version" means skip — and can be undone; a failed update is not a skip.

The user pressed Skip this version on 2.3 by accident (2026-09-25). One setting, `skipped_version`, also
marked an in-app update that had FAILED, so the two were handled alike: the next launch still offered
2.3 in the footer, its dialog called it "a larger update", and Download opened the release page — no
way back to the one-click update. Now:

  * a skipped version is not offered at all; a newer release is, in one click;
  * Settings → Data & System shows "v2.3 skipped — Offer again" while the skip still matters, and
    pressing it brings the one-click offer back;
  * a failed version keeps its own mark (`failed_update_version`): offered as a download, and the
    dialog says why.

Headless like tests/test_update_failure_report.py — the dashboard is built with __new__ (no Tk) — except
the Settings button test, which needs one real ttk.Button. Nothing here goes online: the release check
is replaced by an UpdateInfo.
"""
import inspect
import queue
import tkinter as tk
import types
import pytest
from tkinter import ttk
from unittest.mock import MagicMock

from app import __version__
from app import main
from app import update_checker
from app import updater
from app.main import MasterDashboardApp
from app.update_checker import UpdateInfo

try:
    _ROOT = tk.Tk()
    _ROOT.withdraw()
except Exception:   # no display
    _ROOT = None

NEWER = "99.0"      # newer than this build, whatever __version__ says


class _Var:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class _NowThread:
    """Stands in for threading.Thread: runs the worker at start(), on this thread."""
    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        self._target()


def _release(version=NEWER, update_type="app"):
    return UpdateInfo(version=version, update_type=update_type, runtime_baseline="2.0", sha256="ab" * 32,
                      app_package_url=f"https://example.invalid/Surasura_app_v{version}.zip",
                      notes_url="https://example.invalid/releases/latest")


@pytest.fixture
def dashboard(monkeypatch):
    """An installed, packaged dashboard whose release check returns `dashboard.release`, and whose save
    updates the settings snapshot the check reads — as the real save_settings does."""
    # The *_toggle harnesses reload app.main IN PLACE with tkinter and the update checker mocked, and
    # the reload outlives them: in a full run this module's globals hold MagicMocks by the time these
    # tests run. The names this code path reads are pinned back, so the result doesn't depend on order.
    for name, real in (("classify_update", update_checker.classify_update),
                       ("parse_version", update_checker.parse_version), ("tk", tk)):
        monkeypatch.setattr(main, name, real)
    app = MasterDashboardApp.__new__(MasterDashboardApp)   # no Tk construction
    app.gui_queue = queue.Queue()
    app.status_var = _Var()
    app.skipped_version = ""
    app.failed_update_version = ""
    app.btn_offer_skipped = None
    app.update_label = None
    app._update_info = None
    app._update_class = "NONE"
    app._current_settings = {"auto_update_enabled": True, "skipped_version": "", "failed_update_version": ""}
    app.release = _release()

    def save(*_a, **_k):
        app._current_settings.update(skipped_version=app.skipped_version,
                                     failed_update_version=app.failed_update_version)
    app.save_settings = save
    monkeypatch.setattr(main, "get_update_info", lambda *a, **k: app.release)
    monkeypatch.setattr(updater, "can_auto_apply", lambda: True)
    return app


def _offered(app):
    """What the footer offers after a check: the dialog's class, or NONE when nothing lit up."""
    return app._update_class if not app.gui_queue.empty() else "NONE"


def test_a_new_release_is_offered_in_one_click(dashboard):
    # The baseline for the rest: nothing skipped, nothing failed -> "Update now".
    dashboard.check_updates_thread()
    assert _offered(dashboard) == "APP"


def test_skip_this_version_is_not_offered_again_on_the_next_launch(dashboard):
    dialog = MagicMock()
    dashboard._update_info = dashboard.release
    dashboard._skip_update(dialog)
    dialog.destroy.assert_called_once()
    assert dashboard.skipped_version == NEWER

    dashboard.check_updates_thread()                     # the next launch's check
    assert _offered(dashboard) == "NONE", "a skipped version used to come back as a download"


def test_a_release_newer_than_the_skipped_one_is_offered_in_one_click(dashboard):
    dashboard.skipped_version = "98.0"
    dashboard.save_settings()
    dashboard.check_updates_thread()
    assert _offered(dashboard) == "APP"


def test_offer_again_brings_the_skipped_version_back_in_one_click(dashboard, monkeypatch):
    # Settings' button re-checks at once. The release check is the stand-in, so nothing goes online.
    monkeypatch.delenv("SURASURA_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(main, "threading", types.SimpleNamespace(Thread=_NowThread))
    dashboard.skipped_version = NEWER
    dashboard.save_settings()

    dashboard._offer_skipped_again()

    assert dashboard.skipped_version == ""
    assert dashboard._current_settings["skipped_version"] == "", "forgotten in the saved settings too"
    assert _offered(dashboard) == "APP"


def test_a_failed_update_is_still_offered_as_a_download_that_says_why(dashboard):
    # The loop-breaker holds (never retried in place) — and the dialog no longer calls it "a larger update".
    dashboard.failed_update_version = NEWER
    dashboard.save_settings()
    dashboard.check_updates_thread()
    assert _offered(dashboard) == "FULL"
    body = MasterDashboardApp._update_body("FULL", dashboard.release, dashboard.failed_update_version)
    assert f"The in-app update to v{NEWER} didn't finish last time" in body
    assert "larger update" not in body


def test_a_real_full_release_is_still_called_a_larger_update():
    assert "larger update" in MasterDashboardApp._update_body("FULL", _release(update_type="full"))
    assert "quick in-app update" in MasterDashboardApp._update_body("APP", _release())


def test_neither_mark_forces_a_reanalysis():
    # A failed update, or a skip, must not re-analyse the whole library on the next Generate.
    from app import analyzer
    source = inspect.getsource(analyzer.compute_run_signature)
    for key in ("skipped_version", "failed_update_version"):
        assert f'"{key}"' in source, f"{key} must be excluded from the run signature"


@pytest.mark.skipif(_ROOT is None, reason="needs a display")
def test_the_settings_button_is_there_only_while_the_skipped_version_is_newer(dashboard):
    frame = ttk.Frame(_ROOT)
    dashboard._chk_auto_update = ttk.Checkbutton(frame, text="Automatic Updates")
    dashboard._chk_auto_update.pack()
    dashboard.btn_offer_skipped = ttk.Button(frame)
    try:
        dashboard.skipped_version = NEWER
        dashboard._sync_skipped_row()
        assert dashboard.btn_offer_skipped.winfo_manager() == "pack"
        assert dashboard.btn_offer_skipped.cget("text") == f"v{NEWER} skipped — Offer again"
        # Updated to it by hand, or past it, or nothing skipped: nothing to bring back.
        for version in (__version__, "1.0", ""):
            dashboard.skipped_version = version
            dashboard._sync_skipped_row()
            assert dashboard.btn_offer_skipped.winfo_manager() == "", version
    finally:
        frame.destroy()
