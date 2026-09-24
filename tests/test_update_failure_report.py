"""A failed in-app update must say why, and leave a report the user can send.

The packaged app has no console, so an update failure's reason only ever existed in a dialog — and
the failed-download dialog never appeared at all: its callback read `e` after the except block had
ended, when Python has already deleted it, so the UI thread raised NameError and the user saw the
status line quietly return to "Ready". These tests pin the three failure paths (the download,
starting updater.exe, the install itself) and the report behind them: debug/update_report.txt,
appended so no failure is lost, and never able to stop the dialog when it can't be written.

Headless: the dashboard is built with __new__ (no Tk), like tests/test_band_slider_debounce.py,
inside a NON-ASCII install root — users install under Japanese folder names. The reasons are the
real Japanese Windows error messages a user's system produces.
"""
import os
import json
import queue
import types
import pytest
from unittest.mock import MagicMock

from app import __version__
from app import updater
from app import path_utils
from app.update_checker import UpdateInfo


@pytest.fixture
def install_root(tmp_path, monkeypatch):
    """A fake install root with a Japanese name; the updater's paths all resolve inside it."""
    root = tmp_path / "スラスラ ライブラリ"
    internal = root / "_internal"
    os.makedirs(str(internal), exist_ok=True)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(root))
    monkeypatch.setattr(path_utils, "get_base_path", lambda: str(internal))
    return str(root)


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


def _dashboard():
    from app.main import MasterDashboardApp
    app = MasterDashboardApp.__new__(MasterDashboardApp)   # no Tk construction
    app.gui_queue = queue.Queue()
    app.status_var = _Var()
    app.skipped_version = ""
    app.active_processes = []
    app.update_label = None
    app._update_info = UpdateInfo(version="2.3", update_type="app", sha256="ab" * 32,
                                  app_package_url="https://example.invalid/Surasura_app_v2.3.zip")
    app._update_class = "APP"
    app.save_settings = lambda *a, **k: None   # stub the real (heavy) save
    return app


def _drain(app):
    """Run what the worker queued, as the UI thread's check_queue would."""
    while not app.gui_queue.empty():
        app.gui_queue.get_nowait()()


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _download_fails_with(monkeypatch, reason):
    """Arm _do_auto_update so the download fails with `reason`; return the shown dialogs."""
    from app import main

    def _fail(info, progress_cb=None):
        raise updater.UpdateError(reason)

    monkeypatch.setattr(updater, "can_auto_apply", lambda: True)
    monkeypatch.setattr(updater, "prepare_update", _fail)
    monkeypatch.setattr(main, "threading", types.SimpleNamespace(Thread=_NowThread))
    shown = []
    monkeypatch.setattr(main.messagebox, "showerror", lambda title, msg: shown.append(msg))
    return shown


# --- The three failure paths ---------------------------------------------------------------------
def test_failed_download_shows_why_and_names_the_saved_report(install_root, monkeypatch):
    """The regression: the dialog was a lambda over the deleted `e` and never showed."""
    reason = "checksum mismatch — download corrupted or tampered"
    shown = _download_fails_with(monkeypatch, reason)

    app = _dashboard()
    app._do_auto_update(MagicMock())
    _drain(app)

    assert len(shown) == 1
    assert reason in shown[0]
    assert updater.report_path() in shown[0], "the dialog names the file to send"
    text = _read(updater.report_path())
    assert "Stage: download" in text
    assert "To version: 2.3" in text
    assert reason in text
    assert app.status_var.get() == "Ready"


def test_updater_that_will_not_start_is_reported_and_the_app_stays_open(install_root, monkeypatch):
    """updater.exe can be blocked (antivirus, a deleted file): say so, name the report, keep running."""
    from app import main

    def _blocked(marker_path_=None):
        raise OSError("[WinError 5] アクセスが拒否されました。")

    monkeypatch.setattr(updater, "launch_helper", _blocked)
    shown = []
    monkeypatch.setattr(main.messagebox, "showerror", lambda title, msg: shown.append(msg))

    app = _dashboard()
    app.root = MagicMock()
    app._apply_and_restart(os.path.join(install_root, "pending_update.json"))

    assert len(shown) == 1
    assert "アクセスが拒否されました" in shown[0]
    assert updater.report_path() in shown[0]
    text = _read(updater.report_path())
    assert "Stage: start updater" in text
    assert "アクセスが拒否されました" in text
    app.root.destroy.assert_not_called()
    assert app.status_var.get() == "Ready"


def test_failed_install_keeps_the_helpers_reason_in_the_report(install_root, monkeypatch):
    """The helper's reason used to be deleted with its result file once the dialog closed."""
    from app import main
    reason = ("swap failed (rolled back): [WinError 32] プロセスはファイルにアクセスできません。"
              "別のプロセスが使用中です。: '" + os.path.join(install_root, "Surasura.exe") + "'")
    with open(updater.result_path(), "w", encoding="utf-8") as f:
        json.dump({"status": "failed", "from": "2.2", "to": "2.3", "reason": reason}, f)
    asked = []
    monkeypatch.setattr(main.messagebox, "askyesno", lambda title, msg: asked.append(msg) or False)

    app = _dashboard()
    app.reconcile_update_result()

    assert len(asked) == 1
    assert updater.report_path() in asked[0]
    assert asked[0].endswith("Open the download page to update manually?"), "the question stays last"
    text = _read(updater.report_path())
    assert "Stage: install" in text
    assert "From version: 2.2" in text
    assert "To version: 2.3" in text
    assert reason in text
    assert app.skipped_version == "2.3", "the loop-breaker still runs"
    assert not os.path.exists(updater.result_path()), "the result is still consumed"


# --- Nothing to report ---------------------------------------------------------------------------
def test_successful_update_writes_no_report(install_root, monkeypatch):
    from app import telemetry
    monkeypatch.setattr(telemetry, "send_update_event", lambda *a, **k: None)
    with open(updater.result_path(), "w", encoding="utf-8") as f:
        json.dump({"status": "success", "from": "2.2", "to": "2.3", "reason": "ok"}, f)

    _dashboard().reconcile_update_result()

    assert not os.path.exists(updater.report_path())


def test_nothing_pending_writes_no_report(install_root):
    _dashboard().reconcile_update_result()
    assert not os.path.exists(updater.report_path())


# --- The report itself ---------------------------------------------------------------------------
def test_report_records_versions_system_and_the_install_folder(install_root):
    path = updater.write_report("download", "<urlopen error timed out>", to_version="2.3")

    assert path == os.path.join(install_root, "debug", "update_report.txt")
    text = _read(path)
    assert f"From version: {__version__}" in text, "defaults to the running version"
    assert "To version: 2.3" in text
    assert "Reason: <urlopen error timed out>" in text
    assert "System: " in text
    assert "Packaged build: no" in text
    assert "updater.exe present: no" in text
    assert f"Install folder: {install_root}" in text, "the Japanese path survives the round trip"


def test_report_appends_so_an_earlier_failure_is_kept(install_root):
    """A helper that never started is reported again ("did not complete") on the next launch;
    appending keeps the first, more useful reason as well."""
    first = updater.write_report("start updater", "[WinError 2] 指定されたファイルが見つかりません。",
                                 to_version="2.3")
    second = updater.write_report("install", "update did not complete", to_version="2.3")

    assert first == second == updater.report_path()
    text = _read(first)
    assert text.index("Stage: start updater") < text.index("Stage: install")
    assert "指定されたファイルが見つかりません" in text


def test_dialog_still_shows_when_the_report_cannot_be_saved(install_root, monkeypatch):
    """A folder the app can't write to must not cost the user the explanation."""
    with open(os.path.join(install_root, "debug"), "w", encoding="utf-8") as f:
        f.write("")                               # a FILE where the debug folder should be
    assert updater.write_report("download", "timed out") is None

    shown = _download_fails_with(monkeypatch, "timed out")
    app = _dashboard()
    app._do_auto_update(MagicMock())
    _drain(app)

    assert len(shown) == 1
    assert "timed out" in shown[0]
    assert "report was saved" not in shown[0]
    assert app.status_var.get() == "Ready"
