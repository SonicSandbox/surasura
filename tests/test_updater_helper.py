"""Tests for the standalone update helper (updater_helper.py -> updater.exe).

This is the highest-risk part of the auto-update feature: it swaps program files on disk and
must be perfectly reversible. In a PyInstaller onedir build the app's CODE lives in the
embedded archive inside Surasura.exe (not as loose .py under _internal/app), so the update
unit is the executable itself (a file) PLUS the loose templates/ dir. These tests exercise
that mixed file+dir swap, the per-target sha verification, and rollback.

Surasura's users routinely install into folders whose paths contain Japanese/Chinese
characters, so EVERY test runs against a non-ASCII install path on purpose.
"""
import os
import json
import hashlib
import pytest

import updater_helper


# Realistic-ish contents. The "exe" is opaque bytes with an MZ header (like a real PE); the
# templates carry real Japanese so an encoding bug in copy/rollback would corrupt them visibly.
OLD_EXE = b"MZ\x90\x00" + b"OLD-surasura-executable-bytes-\xe6\x97\xa7" * 8
NEW_EXE = b"MZ\x90\x00" + b"NEW-surasura-executable-bytes-\xe6\x96\xb0" * 8
OLD_TEMPLATE = "<h1>語彙の旅</h1>\n<p>旧テンプレート</p>\n"
NEW_TEMPLATE = "<h1>語彙の旅</h1>\n<p>新しいテンプレート — 完了マーク対応</p>\n"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _wbytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _wtext(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _rbytes(path):
    with open(path, "rb") as f:
        return f.read()


def _rtext(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def install(tmp_path):
    """Fake frozen install under a NON-ASCII path.

      <root>/Surasura.exe                       (the code-bearing exe = a 'file' target)
      <root>/_internal/templates/web_app.html   (loose templates = a 'dir' target)
      <root>/.update_staging/payload/Surasura.exe          (new exe)
      <root>/.update_staging/payload/templates/web_app.html (new templates)
    Marker pre-points at the NEW payload with the exe's expected sha recorded.
    """
    root = tmp_path / "スラスラ ライブラリ"
    exe_dest = root / "Surasura.exe"
    templates_dest = root / "_internal" / "templates"
    _wbytes(str(exe_dest), OLD_EXE)
    _wtext(str(templates_dest / "web_app.html"), OLD_TEMPLATE)

    payload = root / ".update_staging" / "payload"
    _wbytes(str(payload / "Surasura.exe"), NEW_EXE)
    _wtext(str(payload / "templates" / "web_app.html"), NEW_TEMPLATE)

    marker = {
        "target_version": "2.1",
        "from_version": "2.0",
        "app_pid": None,
        "attempt": 0,
        "staging_dir": str(root / ".update_staging"),
        "payload_dir": str(payload),
        "base_dir": str(root / "_internal"),
        "backup_dir": str(root / ".update_backup"),
        "targets": [
            {"name": "Surasura.exe", "kind": "file", "dest": str(exe_dest), "sha256": _sha(NEW_EXE)},
            {"name": "templates", "kind": "dir", "dest": str(templates_dest)},
        ],
        "relaunch_exe": str(root / "does_not_exist.exe"),  # keep _relaunch a no-op
        "result_path": str(root / "last_update_result.json"),
        "wait_timeout": 1,
    }
    return {"root": root, "exe": exe_dest, "templates": templates_dest, "marker": marker}


def test_apply_update_success_swaps_exe_and_templates(install):
    """Happy path: exe (file) and templates (dir) both replaced; backups retained."""
    result = updater_helper.apply_update(install["marker"])

    assert result["status"] == "success"
    assert _rbytes(str(install["exe"])) == NEW_EXE
    assert _rtext(str(install["templates"] / "web_app.html")) == NEW_TEMPLATE
    # Pre-swap bytes preserved in the backup for rollback.
    backup = install["marker"]["backup_dir"]
    assert _rbytes(os.path.join(backup, "Surasura.exe")) == OLD_EXE


def test_apply_update_rolls_back_on_sha_mismatch(install):
    """If the installed exe doesn't match the expected sha, restore EVERYTHING.

    We record a wrong expected sha for the exe; the post-swap verification fails and both the
    exe AND templates must revert to their originals, leaving a working install.
    """
    install["marker"]["targets"][0]["sha256"] = "deadbeef" * 8

    result = updater_helper.apply_update(install["marker"])

    assert result["status"] == "failed"
    assert "verification failed" in result["reason"]
    assert _rbytes(str(install["exe"])) == OLD_EXE
    assert _rtext(str(install["templates"] / "web_app.html")) == OLD_TEMPLATE


def test_apply_update_aborts_if_staged_target_missing(install):
    """A missing staged target aborts BEFORE touching the live install."""
    import shutil
    shutil.rmtree(os.path.join(install["marker"]["payload_dir"], "templates"))

    result = updater_helper.apply_update(install["marker"])

    assert result["status"] == "failed"
    assert "templates" in result["reason"]
    assert _rbytes(str(install["exe"])) == OLD_EXE
    assert _rtext(str(install["templates"] / "web_app.html")) == OLD_TEMPLATE


def test_run_success_end_to_end(install, tmp_path):
    """run(): result written, marker consumed, staging+backup cleaned, exe swapped."""
    marker = install["marker"]
    marker_path = str(tmp_path / "pending_update.json")
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker, f)

    rc = updater_helper.run(marker_path)

    assert rc == 0
    with open(marker["result_path"], "r", encoding="utf-8") as f:
        res = json.load(f)
    assert res["status"] == "success" and res["from"] == "2.0" and res["to"] == "2.1"
    assert not os.path.exists(marker_path)
    assert not os.path.isdir(marker["staging_dir"])
    assert not os.path.isdir(marker["backup_dir"])
    assert _rbytes(str(install["exe"])) == NEW_EXE


def test_run_aborts_without_touching_files_if_app_still_alive(install, tmp_path):
    """If the app hasn't exited, run() must abort BEFORE swapping (no locked-file brick).

    We point app_pid at THIS live test process with a short wait_timeout: wait_for_pid can
    never succeed, so run() must report failure and leave the install completely untouched.
    """
    marker = install["marker"]
    marker["app_pid"] = os.getpid()
    marker["wait_timeout"] = 1
    marker_path = str(tmp_path / "pending_update.json")
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker, f)

    rc = updater_helper.run(marker_path)

    assert rc == 2
    with open(marker["result_path"], "r", encoding="utf-8") as f:
        res = json.load(f)
    assert res["status"] == "failed"
    assert "did not exit" in res["reason"]
    # Install untouched — no swap happened.
    assert _rbytes(str(install["exe"])) == OLD_EXE


def test_apply_update_restores_templates_if_dir_swap_fails(install, monkeypatch):
    """A mid-flight dir-swap failure must still restore EVERY target from backup.

    Regression guard: the exe (target 0) swaps fine, then the templates dir-swap raises. The
    rollback must restore both the exe AND templates from backup — not just the exe — so the
    install is never left with the old exe but missing templates.
    """
    real_swap = updater_helper._swap_one

    def _swap_one(t, payload_dir):
        if t["name"] == "templates":
            # Simulate the dest being removed then the rename failing (the dangerous window).
            import shutil
            if os.path.isdir(t["dest"]):
                shutil.rmtree(t["dest"])
            raise OSError("simulated rename failure during dir swap")
        return real_swap(t, payload_dir)

    monkeypatch.setattr(updater_helper, "_swap_one", _swap_one)

    result = updater_helper.apply_update(install["marker"])

    assert result["status"] == "failed"
    # Both targets restored to their originals.
    assert _rbytes(str(install["exe"])) == OLD_EXE
    assert _rtext(str(install["templates"] / "web_app.html")) == OLD_TEMPLATE


def test_wait_for_pid_none_returns_immediately():
    assert updater_helper.wait_for_pid(None, timeout=5) is True
