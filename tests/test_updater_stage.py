"""Tests for the in-app staging path (app/updater.py).

Covers checksum verification, package extraction/validation (including path-traversal
defence), the frozen-only guard, and the full prepare_update() pipeline armed from a real zip
served over a file:// URL. Paths are redirected into a non-ASCII temp dir so nothing touches
the real install.

The app package is the correct minimal unit for a onedir freeze: the code-bearing
Surasura.exe plus the loose templates/ dir (app code is NOT loose under _internal/app).
"""
import os
import json
import zipfile
from pathlib import Path
import pytest

from app import updater
from app import path_utils


EXE_BYTES = b"MZ\x90\x00surasura-exe-\xe8\xaa\x9e" * 16
TEMPLATE = "<h1>語彙の旅</h1>\n"


def _make_app_package(zip_path, include_templates=True, include_html=True, include_exe=True):
    """Write a realistic app package: top-level Surasura.exe + templates/ (release layout)."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        if include_exe:
            z.writestr("Surasura.exe", EXE_BYTES)
        if include_templates:
            if include_html:
                z.writestr("templates/web_app.html", TEMPLATE)
                z.writestr("templates/zen_app.html", TEMPLATE)
            else:
                z.writestr("templates/notes.txt", "no html here\n")
    return zip_path


@pytest.fixture
def paths(tmp_path, monkeypatch):
    """Redirect updater's install-root + _internal into a non-ASCII temp tree, frozen=True."""
    root = tmp_path / "スラスラ"
    internal = root / "_internal"
    os.makedirs(str(internal / "templates"), exist_ok=True)
    with open(str(internal / "templates" / "web_app.html"), "w", encoding="utf-8") as f:
        f.write("<h1>old</h1>\n")

    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(root))
    monkeypatch.setattr(path_utils, "get_base_path", lambda: str(internal))
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)  # allow prepare_update's guard
    return {"root": str(root), "internal": str(internal)}


def _file_url(path):
    return Path(os.path.abspath(path)).as_uri()


def test_sha256_file_matches_hashlib(tmp_path):
    import hashlib
    p = tmp_path / "blob.bin"
    data = b"\x00\x01\x02japanese-\xe8\xaa\x9e"
    p.write_bytes(data)
    assert updater.sha256_file(str(p)) == hashlib.sha256(data).hexdigest()


def test_extract_and_validate_accepts_exe_and_templates(paths, tmp_path):
    zpath = str(tmp_path / "pkg.zip")
    _make_app_package(zpath)
    payload = str(tmp_path / "payload")
    assert updater.extract_and_validate(zpath, payload) is True
    assert os.path.isfile(os.path.join(payload, "Surasura.exe"))


def test_extract_and_validate_rejects_missing_exe(paths, tmp_path):
    zpath = str(tmp_path / "pkg.zip")
    _make_app_package(zpath, include_exe=False)
    payload = str(tmp_path / "payload")
    assert updater.extract_and_validate(zpath, payload) is False


def test_extract_and_validate_rejects_missing_html(paths, tmp_path):
    zpath = str(tmp_path / "pkg.zip")
    _make_app_package(zpath, include_html=False)
    payload = str(tmp_path / "payload")
    assert updater.extract_and_validate(zpath, payload) is False


def test_extract_and_validate_blocks_path_traversal(paths, tmp_path):
    zpath = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("../escape.txt", "pwned")
    payload = str(tmp_path / "payload")
    with pytest.raises(updater.UpdateError):
        updater.extract_and_validate(zpath, payload)


def test_download_streams_with_progress(tmp_path):
    src = tmp_path / "src.zip"
    _make_app_package(str(src))
    dest = str(tmp_path / "out.zip")
    seen = []
    updater.download(_file_url(str(src)), dest, progress_cb=lambda d, t: seen.append(d))
    assert os.path.exists(dest)
    assert os.path.getsize(dest) == os.path.getsize(str(src))
    assert seen and seen[-1] == os.path.getsize(str(src))


def test_build_marker_targets_exe_and_templates(paths, tmp_path, monkeypatch):
    from app.update_checker import UpdateInfo
    # Stage an exe so build_marker can hash it.
    payload = str(tmp_path / "payload")
    os.makedirs(payload, exist_ok=True)
    with open(os.path.join(payload, "Surasura.exe"), "wb") as f:
        f.write(EXE_BYTES)
    monkeypatch.setattr(updater.sys, "executable", os.path.join(paths["root"], "Surasura.exe"))

    info = UpdateInfo(version="2.1", update_type="app", sha256="x", app_package_url="http://x")
    marker = updater.build_marker(info, payload, 4321)

    assert marker["target_version"] == "2.1"
    assert marker["app_pid"] == 4321
    by_name = {t["name"]: t for t in marker["targets"]}
    exe_t = by_name["Surasura.exe"]
    assert exe_t["kind"] == "file"
    assert exe_t["dest"] == os.path.join(paths["root"], "Surasura.exe")
    assert exe_t["sha256"] == updater.sha256_file(os.path.join(payload, "Surasura.exe"))
    tpl_t = by_name["templates"]
    assert tpl_t["kind"] == "dir"
    assert tpl_t["dest"] == os.path.join(paths["internal"], "templates")


def test_build_marker_includes_release_notes_when_present(paths, tmp_path, monkeypatch):
    """When the app package carries RELEASE_NOTES.md, build_marker adds it as a (non-critical) file
    target next to the exe, so an app update refreshes the bundled notes in place."""
    from app.update_checker import UpdateInfo
    payload = str(tmp_path / "payload")
    os.makedirs(payload, exist_ok=True)
    with open(os.path.join(payload, "Surasura.exe"), "wb") as f:
        f.write(EXE_BYTES)
    with open(os.path.join(payload, "RELEASE_NOTES.md"), "w", encoding="utf-8") as f:
        f.write("# Surasura v2.1 - Release Notes\n")
    monkeypatch.setattr(updater.sys, "executable", os.path.join(paths["root"], "Surasura.exe"))

    info = UpdateInfo(version="2.1", update_type="app", sha256="x", app_package_url="http://x")
    marker = updater.build_marker(info, payload, 4321)
    notes_t = {t["name"]: t for t in marker["targets"]}.get("RELEASE_NOTES.md")
    assert notes_t is not None, "notes target added when the package carries it"
    assert notes_t["kind"] == "file"
    assert notes_t["dest"] == os.path.join(paths["root"], "RELEASE_NOTES.md")
    assert not notes_t.get("sha256"), "notes are non-critical -> no per-file hash"


def test_build_marker_omits_release_notes_when_absent(paths, tmp_path, monkeypatch):
    """Backward compat: an older package without RELEASE_NOTES.md -> no notes target (only exe+templates)."""
    from app.update_checker import UpdateInfo
    payload = str(tmp_path / "payload")
    os.makedirs(payload, exist_ok=True)
    with open(os.path.join(payload, "Surasura.exe"), "wb") as f:
        f.write(EXE_BYTES)
    monkeypatch.setattr(updater.sys, "executable", os.path.join(paths["root"], "Surasura.exe"))
    info = UpdateInfo(version="2.1", update_type="app", sha256="x", app_package_url="http://x")
    marker = updater.build_marker(info, payload, 4321)
    assert "RELEASE_NOTES.md" not in {t["name"] for t in marker["targets"]}


def test_prepare_update_end_to_end_arms_marker(paths, tmp_path):
    from app.update_checker import UpdateInfo
    src = tmp_path / "Surasura_app_v2.1.zip"
    _make_app_package(str(src))
    good_sha = updater.sha256_file(str(src))

    info = UpdateInfo(version="2.1", update_type="app", runtime_baseline="2.0",
                      sha256=good_sha, app_package_url=_file_url(str(src)))
    marker_path = updater.prepare_update(info)

    assert os.path.exists(marker_path)
    with open(marker_path, "r", encoding="utf-8") as f:
        marker = json.load(f)
    assert marker["target_version"] == "2.1"
    assert os.path.isfile(os.path.join(marker["payload_dir"], "Surasura.exe"))


def test_prepare_update_rejects_bad_checksum(paths, tmp_path):
    from app.update_checker import UpdateInfo
    src = tmp_path / "pkg.zip"
    _make_app_package(str(src))
    info = UpdateInfo(version="2.1", update_type="app", sha256="00" * 32,
                      app_package_url=_file_url(str(src)))
    with pytest.raises(updater.UpdateError):
        updater.prepare_update(info)
    assert not os.path.exists(updater.marker_path())
    assert not os.path.isdir(updater.staging_dir())


def test_prepare_update_refuses_when_not_frozen(tmp_path, monkeypatch):
    """Defense in depth: staging must refuse to run in a source checkout."""
    from app.update_checker import UpdateInfo
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    info = UpdateInfo(version="2.1", update_type="app", sha256="x",
                      app_package_url="http://x/app.zip")
    with pytest.raises(updater.UpdateError):
        updater.prepare_update(info)
