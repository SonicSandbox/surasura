"""S1.3-6 (S1.1): the 2.x -> 3.0 installer hand-off ships in 2.5 SWITCHED OFF.

`update_type: "installer"` with `installer: {asset, sha256, args, min_from}`: download, check the sha256, wait for
Surasura's programs (K75, the same window), refresh the note (K100), start the installer detached (not through
updater.exe), exit. It runs only for a release of 3.0 or later; every 2.x-shaped update.json — app, full, none,
malformed, an unknown type, `installer` below 3.0 — never reaches it.

Releases are local folders read through the update check's override (non-release builds only); the "installer" is a
stub file whose launch is recorded, never run. The dialog is the real dashboard's, its buttons pressed."""
import json
import os
import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

from app import build_info
from app import path_utils
from app import update_checker
from app import updater
from app.update_checker import classify_update

STUB = b"MZ\x90\x00stub-installer-\xe3\x81\x99\xe3\x82\x89" * 8
CURRENT = "2.5.0"


def _release(folder, manifest, installer_bytes=STUB, asset="Surasura-Setup-3.0.0.exe"):
    folder.mkdir(parents=True, exist_ok=True)
    if installer_bytes is not None:
        (folder / asset).write_bytes(installer_bytes)
    (folder / "Surasura_app_v9.zip").write_bytes(b"PK")
    (folder / "update.json").write_text(manifest if isinstance(manifest, str) else json.dumps(manifest),
                                        encoding="utf-8")
    return folder


def _installer_manifest(version="3.0.0", **over):
    import hashlib
    inst = {"asset": "Surasura-Setup-3.0.0.exe", "sha256": hashlib.sha256(STUB).hexdigest(), "args": ["/SILENT"],
            "min_from": "2.5"}
    inst.update(over)
    return {"version": version, "update_type": "installer", "installer": inst, "sha256": "ab" * 32}


TWO_X_SHAPES = {
    "app": {"version": "2.5.1", "update_type": "app", "sha256": "ab" * 32, "runtime_baseline": "2.5"},
    "full": {"version": "2.6.0", "update_type": "full"},
    "missing": None,
    "malformed": "{not json",
    "unknown type": {"version": "2.6.0", "update_type": "delta"},
    "installer below 3.0": _installer_manifest(version="2.9.0"),
    "installer, no installer object": {"version": "3.0.0", "update_type": "installer"},
    "installer, asset not in the release": _installer_manifest(asset="Elsewhere.exe"),
    "installer, no sha256": _installer_manifest(sha256=""),
    "installer, args not a list": _installer_manifest(args="/SILENT"),
    "installer, from a newer 2.x only": _installer_manifest(min_from="2.6"),
}


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root = tmp_path / "スラスラ"
    (root / "_internal").mkdir(parents=True)
    (root / "updater.exe").write_bytes(b"MZ")
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(root))
    monkeypatch.setattr(path_utils, "get_base_path", lambda: str(root / "_internal"))
    monkeypatch.setattr(build_info, "RELEASE_BUILD", False)
    monkeypatch.setattr(updater, "__version__", CURRENT)
    return root


@pytest.fixture
def launches(monkeypatch):
    seen = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: seen.append((args, kw)) or MagicMock())
    return seen


def _info_from(folder, monkeypatch):
    monkeypatch.setenv(update_checker.UPDATE_SOURCE_ENV, str(folder))
    return update_checker.get_update_info()


@pytest.mark.parametrize("shape", sorted(TWO_X_SHAPES))
def test_no_2x_shaped_release_reaches_the_installer_path(shape, frozen, launches, tmp_path, monkeypatch):
    manifest = TWO_X_SHAPES[shape]
    folder = tmp_path / "rel"
    if manifest is None:
        folder.mkdir()
        (folder / "update.json").write_text(json.dumps({"version": "2.6.0"}), encoding="utf-8")
    else:
        _release(folder, manifest)
    info = _info_from(folder, monkeypatch)
    cls = classify_update(CURRENT, info) if info else "NONE"
    assert cls != "INSTALLER"
    if info is not None:
        with pytest.raises(updater.UpdateError):
            updater.prepare_installer(info)
    assert launches == []


def test_an_installer_below_3_0_is_a_manual_download(frozen, tmp_path, monkeypatch):
    info = _info_from(_release(tmp_path / "rel", _installer_manifest(version="2.9.0")), monkeypatch)
    assert classify_update(CURRENT, info) == "FULL"


def test_a_3_0_installer_release_hands_over(frozen, launches, tmp_path, monkeypatch):
    info = _info_from(_release(tmp_path / "rel", _installer_manifest()), monkeypatch)
    assert classify_update(CURRENT, info) == "INSTALLER"
    assert updater.effective_class("INSTALLER", info, can_apply=True) == "INSTALLER"
    staged = updater.prepare_installer(info)
    assert open(staged["path"], "rb").read() == STUB
    assert launches == []                                     # staging launches nothing
    updater.arm_and_launch(staged)
    [(args, kw)] = launches
    assert args == [staged["path"], "/SILENT"]
    assert kw["creationflags"] & 0x00000008                   # detached: it outlives the app
    assert not os.path.exists(updater.marker_path())          # never through updater.exe


def test_a_sha_mismatch_launches_nothing(frozen, launches, tmp_path, monkeypatch):
    info = _info_from(_release(tmp_path / "rel", _installer_manifest(), installer_bytes=STUB + b"!"), monkeypatch)
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.prepare_installer(info)
    assert launches == [] and not os.path.isdir(updater.staging_dir())


def test_a_skipped_or_failed_installer_version_is_guarded_like_an_app_update(frozen, tmp_path, monkeypatch):
    info = _info_from(_release(tmp_path / "rel", _installer_manifest()), monkeypatch)
    assert updater.effective_class("INSTALLER", info, skipped_version="3.0.0") == "NONE"
    assert updater.effective_class("INSTALLER", info, failed_version="3.0.0") == "FULL"
    assert updater.effective_class("INSTALLER", info, auto_enabled=False) == "FULL"


def test_a_source_checkout_never_hands_over(tmp_path, monkeypatch):
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    monkeypatch.setattr(build_info, "RELEASE_BUILD", False)
    monkeypatch.setattr(updater, "__version__", CURRENT)      # only the frozen check is left to refuse it
    info = _info_from(_release(tmp_path / "rel", _installer_manifest()), monkeypatch)
    assert update_checker.installer_ready(CURRENT, info)
    with pytest.raises(updater.UpdateError):
        updater.prepare_installer(info)


# --- the dashboard -----------------------------------------------------------------------------------------------------

@pytest.fixture
def dash(monkeypatch):
    from app.main import MasterDashboardApp
    root = tk.Tk()
    root.withdraw()
    real_destroy = root.destroy
    app = MasterDashboardApp(root)
    app.destroyed = []
    monkeypatch.setattr(root, "destroy", lambda: app.destroyed.append(1))
    monkeypatch.setattr(updater, "_install_images", lambda: [])
    yield app
    if app._update_job is not None:
        app._end_update(app._update_job)
    with updater._DEFERRED_LOCK:
        updater._DEFERRED.clear()
    updater._HOLD.clear()
    real_destroy()


def _dialog_buttons(app):
    for w in app.root.winfo_children():
        if isinstance(w, tk.Toplevel) and w.title() == "Update Available":
            out = []
            def walk(x):
                for c in x.winfo_children():
                    if isinstance(c, ttk.Button):
                        out.append(c)
                    walk(c)
            walk(w)
            return {b.cget("text"): b for b in out}
    return {}


def _pump(app, until, timeout=10.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.root.update()
        if until():
            return True
        time.sleep(0.02)
    return until()


@pytest.mark.parametrize("shape", ["app", "full", "unknown type", "installer below 3.0"])
def test_the_dashboard_never_starts_the_installer_for_a_2x_release(shape, dash, frozen, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(updater, "prepare_installer", lambda *a, **k: called.append(a))
    monkeypatch.setattr(updater, "prepare_update", lambda *a, **k: {"target_version": "x", "targets": []})
    monkeypatch.setattr(updater, "arm_and_launch", lambda staged: None)
    import app.main as main
    monkeypatch.setattr(main.webbrowser, "open", lambda url: None)
    info = _info_from(_release(tmp_path / "rel", TWO_X_SHAPES[shape]), monkeypatch)
    dash._update_info = info
    dash._update_class = updater.effective_class(classify_update(CURRENT, info), info, can_apply=True)
    dash.open_update_dialog()
    buttons = _dialog_buttons(dash)
    if shape == "app":
        assert dash._update_class == "APP"                    # the in-place path really is the one pressed
    (buttons.get("Update now") or buttons["Download"]).invoke()
    _pump(dash, lambda: False, timeout=0.3)
    assert called == []


def test_the_dashboard_hands_over_to_a_3_0_installer_after_the_wait(dash, frozen, launches, tmp_path, monkeypatch):
    info = _info_from(_release(tmp_path / "rel", _installer_manifest()), monkeypatch)
    dash._update_info = info
    dash._update_class = updater.effective_class(classify_update(CURRENT, info), info, can_apply=True)
    assert dash._update_class == "INSTALLER"
    notes = []
    monkeypatch.setattr(dash, "_write_install_note", lambda: notes.append(1))
    dash.open_update_dialog()
    _dialog_buttons(dash)["Update now"].invoke()
    assert _pump(dash, lambda: launches)
    [(args, kw)] = launches
    assert args[1:] == ["/SILENT"] and os.path.basename(args[0]) == "Surasura-Setup-3.0.0.exe"
    assert notes == [1]                                        # the note refreshed before the hand-off (K100)
    assert dash.destroyed == [1]
