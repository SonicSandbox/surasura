"""S1.1-2: nothing automatic writes settings.json — a failed update's note lives in the install's own local folder.

2.4.0 recorded a failed in-app update (`failed_update_version`, the loop-breaker that turns that version into a manual
download) through the dashboard's full save of settings.json. From 2.5 it goes to
`get_local_data_path()/update_state.json`, written atomically; an old key 2.4.0 may leave in settings.json is honoured
(read, never written back) and the dashboard's next save drops it. `skipped_version` stays in settings.json: the
user's own *Skip* click writes it.

The real dashboard on a settings.json in the test root; a Japanese version-free install name is the test root's."""
import json
import os
import tkinter as tk

import pytest

from app import path_utils
from app import settings_manager
from app import updater
from app.update_checker import UpdateInfo


def _settings_path():
    return os.path.join(path_utils.get_user_data_path(), "settings.json")


def _write_settings(extra):
    settings = settings_manager.get_default_settings()
    settings.update(extra)
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)
    with open(_settings_path(), "rb") as f:
        return f.read()


@pytest.fixture
def dashboard():
    from app.main import MasterDashboardApp
    root = tk.Tk()
    root.withdraw()
    app = MasterDashboardApp(root)
    yield app
    try:
        root.destroy()
    except Exception:
        pass


def _failed_result(version="2.5.1"):
    with open(updater.result_path(), "w", encoding="utf-8") as f:
        json.dump({"status": "failed", "from": "2.5.0", "to": version, "reason": "swap failed (rolled back)"}, f)


def test_a_failed_update_is_noted_in_update_state_and_settings_json_is_untouched(dashboard):
    before = _write_settings({"wpd": 17})
    _failed_result("2.5.1")
    dashboard.reconcile_update_result()
    with open(_settings_path(), "rb") as f:
        assert f.read() == before, "settings.json's bytes must not change"
    with open(updater.update_state_path(), encoding="utf-8") as f:
        assert json.load(f)["failed_update_version"] == "2.5.1"
    assert updater.update_state_path().startswith(path_utils.get_local_data_path())
    assert dashboard.failed_update_version == "2.5.1"
    info = UpdateInfo(version="2.5.1", update_type="app", sha256="ab" * 32, app_package_url="x")
    assert updater.effective_class("APP", info, failed_version=updater.failed_version({})) == "FULL"


def test_an_old_key_in_settings_json_is_honoured_and_never_written_back(dashboard):
    before = _write_settings({"failed_update_version": "2.5.0"})
    settings = settings_manager.load_settings()
    assert updater.failed_version(settings) == "2.5.0"
    with open(_settings_path(), "rb") as f:
        assert f.read() == before                                    # read only
    # Kept in update_state.json from then on, so it outlives the key.
    assert updater.failed_version({}) == "2.5.0"


def test_the_dashboard_reads_the_old_key_and_its_next_save_drops_it(dashboard):
    _write_settings({"failed_update_version": "2.5.0", "skipped_version": "2.6.0"})
    dashboard.load_settings()
    assert dashboard.failed_update_version == "2.5.0"
    dashboard.save_settings()                                       # the user changes something
    with open(_settings_path(), encoding="utf-8") as f:
        saved = json.load(f)
    assert "failed_update_version" not in saved
    assert saved["skipped_version"] == "2.6.0"                      # the user's own Skip stays
    assert updater.failed_version(saved) == "2.5.0"


def test_skip_still_writes_settings_json(dashboard):
    _write_settings({})
    dashboard._update_info = UpdateInfo(version="2.6.0")
    dashboard.update_label = None

    class _Dialog:
        def destroy(self):
            pass
    dashboard._skip_update(_Dialog())
    with open(_settings_path(), encoding="utf-8") as f:
        assert json.load(f)["skipped_version"] == "2.6.0"


def test_the_failed_version_is_no_longer_a_setting():
    assert "failed_update_version" not in settings_manager.get_default_settings()


def test_an_unwritable_state_never_raises(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(updater, "update_state_path", lambda: str(blocker / "update_state.json"))
    assert updater.record_failed_version("2.5.1") is False
    assert updater.failed_version({}) == ""


def test_the_update_check_reads_the_failed_version_from_update_state(dashboard, monkeypatch):
    import app.main as main
    updater.record_failed_version("2.5.1")
    info = UpdateInfo(version="2.5.1", update_type="app", sha256="ab" * 32, app_package_url="x")
    monkeypatch.setattr(main, "get_update_info", lambda: info)
    monkeypatch.setattr(updater, "can_auto_apply", lambda info=None: True)
    dashboard._current_settings = {"auto_update_enabled": True, "skipped_version": ""}
    dashboard.check_updates_thread()
    assert dashboard._update_class == "FULL"
