"""Tests for post-update reconciliation and the anti-loop / kill-switch guard.

`consume_result()` is how the app learns, on the next launch, whether an applied update
succeeded, failed, or was interrupted (helper crashed). `effective_class()` is the pure
guard that prevents auto-update loops and honours the settings kill-switch. Both are tested
here without any GUI.
"""
import os
import json
import pytest

from app import updater
from app import path_utils
from app.update_checker import UpdateInfo


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    """Point updater's install-root + _internal at a non-ASCII temp tree."""
    root = tmp_path / "スラスラ"
    internal = root / "_internal"
    os.makedirs(str(internal), exist_ok=True)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(root))
    monkeypatch.setattr(path_utils, "get_base_path", lambda: str(internal))
    return str(root)


# --- consume_result ----------------------------------------------------------
def test_consume_result_none_when_nothing_pending(user_dir):
    assert updater.consume_result() is None


def test_consume_result_reads_and_clears_success(user_dir):
    with open(updater.result_path(), "w", encoding="utf-8") as f:
        json.dump({"status": "success", "from": "2.0", "to": "2.1", "reason": "ok"}, f)
    res = updater.consume_result()
    assert res["status"] == "success"
    assert res["from"] == "2.0" and res["to"] == "2.1"
    # File is consumed so the toast only shows once.
    assert not os.path.exists(updater.result_path())


def test_consume_result_synthesizes_failure_from_leftover_marker(user_dir):
    """Marker left behind with no result = helper crashed mid-run -> report as failed.

    This is the guarantee that a killed/interrupted update never silently retries: the app
    sees a definite failure it can surface and skip.
    """
    with open(updater.marker_path(), "w", encoding="utf-8") as f:
        json.dump({"from_version": "2.0", "target_version": "2.1", "attempt": 1}, f)
    res = updater.consume_result()
    assert res["status"] == "failed"
    assert res["to"] == "2.1"
    # Leftover marker cleared so it can't be interpreted twice.
    assert not os.path.exists(updater.marker_path())


def test_consume_result_prefers_result_over_marker(user_dir):
    with open(updater.result_path(), "w", encoding="utf-8") as f:
        json.dump({"status": "success", "from": "2.0", "to": "2.1"}, f)
    with open(updater.marker_path(), "w", encoding="utf-8") as f:
        json.dump({"from_version": "2.0", "target_version": "2.1"}, f)
    res = updater.consume_result()
    assert res["status"] == "success"


# --- effective_class (kill-switch / anti-loop guard) -------------------------
def _info(version="2.1"):
    return UpdateInfo(version=version, update_type="app", runtime_baseline="2.0",
                      sha256="x", app_package_url="http://x/app.zip")


def test_effective_class_passes_app_when_all_clear():
    assert updater.effective_class("APP", _info(), skipped_version="",
                                   auto_enabled=True, can_apply=True) == "APP"


def test_effective_class_downgrades_when_auto_disabled():
    assert updater.effective_class("APP", _info(), auto_enabled=False, can_apply=True) == "FULL"


def test_effective_class_downgrades_when_cannot_apply():
    # e.g. running from source / no bundled updater.exe.
    assert updater.effective_class("APP", _info(), auto_enabled=True, can_apply=False) == "FULL"


def test_effective_class_downgrades_skipped_or_failed_version():
    # The version already failed/was skipped once -> never auto-offer it again (loop-breaker).
    assert updater.effective_class("APP", _info("2.1"), skipped_version="2.1") == "FULL"


def test_effective_class_leaves_none_and_full_untouched():
    assert updater.effective_class("NONE", None) == "NONE"
    assert updater.effective_class("FULL", _info()) == "FULL"
