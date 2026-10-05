"""K99 (S1.1): the release's own file list, with sha256, decides what an in-place update swaps.

2.4.0's updater swaps three things it knows (Surasura.exe, _internal/templates, RELEASE_NOTES.md), so a release could
never bring a new program (surasura-cli.exe) or a new file in place. From 2.5 update.json lists every file; the app
stages and checks each, refuses any destination outside an allow-list (the update is then a manual one), creates a new
file's folder before the helper starts, and deletes what a failed swap added (the helper's rollback can't).

A test release here is a local folder (update.json + the app package zip) read through the update check's override,
which only a non-release build honours: nothing is ever published. The swap is the real updater_helper.apply_update;
the install is a temp folder with a Japanese name."""
import json
import os
import subprocess
import sys
import textwrap
import zipfile

import pytest

import package_app
import updater_helper
from app import build_info
from app import path_utils
from app import update_checker
from app import updater
from app.update_checker import UpdateInfo, classify_update

EXE_OLD = b"MZ\x90\x00surasura-2.5.0-\xe8\xaa\x9e" * 16
EXE_NEW = b"MZ\x90\x00surasura-2.5.1-\xe8\xaa\x9e" * 16
DLL_NEW = b"MZ\x90\x00new-library-\xe6\x96\xb0" * 8
TEMPLATE_NEW = "<h1>語彙の旅 2.5.1</h1>\n"
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable          # the install fixture points sys.executable at the fake Surasura.exe


@pytest.fixture
def install(tmp_path, monkeypatch):
    """A frozen install: Surasura.exe (2.5.0), _internal/templates, updater.exe; its paths resolve inside it."""
    root = tmp_path / "スラスラ 本番"
    (root / "_internal" / "templates").mkdir(parents=True)
    (root / "_internal" / "templates" / "web_app.html").write_text("<h1>old</h1>\n", encoding="utf-8")
    (root / "Surasura.exe").write_bytes(EXE_OLD)
    (root / "updater.exe").write_bytes(b"MZ")
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(root))
    monkeypatch.setattr(path_utils, "get_base_path", lambda: str(root / "_internal"))
    monkeypatch.setattr(updater.sys, "executable", str(root / "Surasura.exe"))
    return root


def _test_release(folder, version="2.5.1", extra=True, files_override=None):
    """A test release in a local folder: the app package (2.4.0's layout + a file only the list names) and its
    update.json with `files`. The extra file goes into a sub-folder that doesn't exist yet."""
    folder.mkdir(parents=True, exist_ok=True)
    stage = folder.parent / "stage"
    (stage / "templates").mkdir(parents=True, exist_ok=True)
    (stage / "templates" / "web_app.html").write_text(TEMPLATE_NEW, encoding="utf-8")
    (stage / "Surasura.exe").write_bytes(EXE_NEW)
    (stage / "extra.dll").write_bytes(DLL_NEW)
    pkg = folder / f"Surasura_app_v{version}.zip"
    with zipfile.ZipFile(pkg, "w") as z:
        z.write(stage / "Surasura.exe", "Surasura.exe")
        z.write(stage / "templates" / "web_app.html", "templates/web_app.html")
        if extra:
            z.write(stage / "extra.dll", "extra.dll")
    files = files_override or [
        {"name": "Surasura.exe", "dest": "Surasura.exe", "kind": "file",
         "sha256": updater.sha256_file(str(stage / "Surasura.exe"))},
        {"name": "templates", "dest": "_internal/templates", "kind": "dir",
         "sha256": updater.tree_sha256(str(stage / "templates"))},
    ] + ([{"name": "extra.dll", "dest": "_internal/新しい/lib/extra.dll", "kind": "file",
           "sha256": updater.sha256_file(str(stage / "extra.dll"))}] if extra else [])
    (folder / "update.json").write_text(json.dumps({
        "version": version, "update_type": "app", "runtime_baseline": "2.5", "critical": False,
        "sha256": updater.sha256_file(str(pkg)), "files": files}), encoding="utf-8")
    return folder


@pytest.fixture
def local_release(tmp_path, monkeypatch):
    folder = _test_release(tmp_path / "release")
    monkeypatch.setenv(update_checker.UPDATE_SOURCE_ENV, str(folder))
    monkeypatch.setattr(build_info, "RELEASE_BUILD", False)
    return folder


def _helper_runs_in_process(monkeypatch):
    """launch_helper -> the REAL helper's swap, here and now (no wait on our own PID)."""
    results = []

    def launch(marker_path_=None):
        with open(marker_path_ or updater.marker_path(), "r", encoding="utf-8") as f:
            marker = json.load(f)
        result = updater_helper.apply_update(marker)
        updater_helper._safe_write_json(marker["result_path"], result)
        updater_helper._cleanup(marker)
        os.remove(marker_path_ or updater.marker_path())
        results.append(result)
    monkeypatch.setattr(updater, "launch_helper", launch)
    return results


# --- a test release adds a file named only in its list ---------------------------------------------------------------

def test_a_test_release_adds_a_file_named_only_in_its_list(install, local_release, monkeypatch):
    info = update_checker.get_update_info()
    assert info.version == "2.5.1" and info.files and info.app_package_url.startswith("file:")
    assert classify_update("2.5.0", info) == "APP"
    assert updater.can_auto_apply(info)
    marker = updater.prepare_update(info)
    assert not os.path.exists(updater.marker_path())                  # staged, not armed
    added = [t for t in marker["targets"] if t.get("added")]
    assert [os.path.relpath(t["dest"], install) for t in added] == [os.path.join("_internal", "新しい", "lib", "extra.dll")]
    results = _helper_runs_in_process(monkeypatch)
    updater.arm_and_launch(marker)
    assert results[0]["status"] == "success", results
    new = install / "_internal" / "新しい" / "lib" / "extra.dll"
    assert new.read_bytes() == DLL_NEW                                # landed in a new sub-folder…
    assert updater.sha256_file(str(new)) == updater.sha256_file(str(local_release.parent / "stage" / "extra.dll"))
    assert (install / "Surasura.exe").read_bytes() == EXE_NEW          # …with the rest of the list
    assert (install / "_internal" / "templates" / "web_app.html").read_text(encoding="utf-8") == TEMPLATE_NEW
    res = updater.consume_result()                                    # the relaunched app
    assert res["status"] == "success"
    assert new.exists() and not os.path.exists(updater.added_path())


def test_an_added_file_is_gone_after_a_failed_swap(install, local_release, monkeypatch):
    info = update_checker.get_update_info()
    marker = updater.prepare_update(info)
    # The staged exe is damaged after it was checked: the helper's post-swap check fails and rolls back.
    with open(os.path.join(marker["payload_dir"], "Surasura.exe"), "ab") as f:
        f.write(b"!")
    results = _helper_runs_in_process(monkeypatch)
    updater.arm_and_launch(marker)
    assert results[0]["status"] == "failed"
    new_dir = install / "_internal" / "新しい"
    assert (new_dir / "lib" / "extra.dll").exists()                   # the helper's rollback leaves it
    res = updater.consume_result()
    assert res["status"] == "failed"
    assert not new_dir.exists()                                       # the relaunched app takes it away
    assert (install / "Surasura.exe").read_bytes() == EXE_OLD


def test_an_update_whose_helper_never_ran_removes_nothing_it_did_not_add(install, local_release, monkeypatch):
    info = update_checker.get_update_info()
    marker = updater.prepare_update(info)
    monkeypatch.setattr(updater, "launch_helper", lambda marker_path_=None: None)   # started, then killed
    updater.arm_and_launch(marker)
    assert (install / "_internal" / "新しい" / "lib").is_dir()          # its folder was made before the launch
    res = updater.consume_result()
    assert res["status"] == "failed" and res["reason"] == "update did not complete"
    assert not (install / "_internal" / "新しい").exists()
    assert (install / "_internal" / "templates").is_dir() and (install / "Surasura.exe").exists()


def test_the_helper_that_cannot_start_leaves_nothing_armed_or_made(install, local_release, monkeypatch):
    info = update_checker.get_update_info()
    marker = updater.prepare_update(info)
    def blocked(marker_path_=None):
        raise OSError("[WinError 5] アクセスが拒否されました。")
    monkeypatch.setattr(updater, "launch_helper", blocked)
    with pytest.raises(OSError):
        updater.arm_and_launch(marker)
    assert not os.path.exists(updater.marker_path()) and not os.path.exists(updater.added_path())
    assert not (install / "_internal" / "新しい").exists()


def test_a_staged_file_whose_bytes_differ_from_its_sha256_is_refused(install, tmp_path, monkeypatch):
    folder = _test_release(tmp_path / "bad")
    data = json.loads((folder / "update.json").read_text(encoding="utf-8"))
    data["files"][2]["sha256"] = "00" * 32
    (folder / "update.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(update_checker.UPDATE_SOURCE_ENV, str(folder))
    monkeypatch.setattr(build_info, "RELEASE_BUILD", False)
    info = update_checker.get_update_info()
    with pytest.raises(updater.UpdateError):
        updater.prepare_update(info)
    assert not os.path.isdir(updater.staging_dir())


def test_a_release_without_a_list_gets_the_three_targets(install, tmp_path):
    payload = tmp_path / "payload"
    (payload / "templates").mkdir(parents=True)
    (payload / "Surasura.exe").write_bytes(EXE_NEW)
    (payload / "RELEASE_NOTES.md").write_text("# 2.5.1\n", encoding="utf-8")
    marker = updater.build_marker(UpdateInfo(version="2.5.1"), str(payload), 1)
    assert [t["name"] for t in marker["targets"]] == ["Surasura.exe", "templates", "RELEASE_NOTES.md"]
    assert not any(t.get("added") for t in marker["targets"])


def test_a_new_program_rides_in_the_list(install, tmp_path):
    """surasura-cli.exe: a file 2.4.0's updater could never bring, named by the list."""
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "surasura-cli.exe").write_bytes(b"MZcli")
    files = [{"name": "surasura-cli.exe", "dest": "surasura-cli.exe", "kind": "file",
              "sha256": updater.sha256_file(str(tmp_path / "p" / "surasura-cli.exe"))}]
    marker = updater.build_marker(UpdateInfo(version="2.5.1", files=files), str(tmp_path / "p"), 1)
    [t] = marker["targets"]
    assert t["dest"] == str(install / "surasura-cli.exe") and t["added"] is True and t["sha256"]


# --- the allow-list ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("dest", [
    "..\\settings.json", "../settings.json", "SETTINGS.JSON", "settings.json", "_internal/../settings.json",
    "C:\\Windows\\evil.dll", "C:evil.dll", "/etc/passwd", "\\\\server\\share\\x", "User Files/ja/KnownWord.json",
    "data/ja/HighPriority/x.txt", "results/report.html", "updater.exe", "pending_update.json", "_internal",
    "Surasura.exe.", "Surasura.exe ", "Surasura.exe:stream", "", "templates/web_app.html",
    "/_internal/x.dll", "\\_internal\\x.dll", "_internal/lib./x.dll", "_internal/lib /x.dll",
])
def test_a_destination_outside_the_allow_list_makes_the_update_full(install, dest):
    with pytest.raises(updater.UpdateError):
        updater.resolve_destination(dest)
    files = [{"name": "x", "dest": dest, "kind": "file", "sha256": "ab" * 32}]
    info = UpdateInfo(version="2.5.1", update_type="app", sha256="ab" * 32, app_package_url="x", files=files)
    assert updater.can_auto_apply(info) is False
    assert updater.effective_class("APP", info, can_apply=updater.can_auto_apply(info)) == "FULL"


@pytest.mark.parametrize("dest", ["Surasura.exe", "surasura.EXE", "surasura-cli.exe", "RELEASE_NOTES.md",
                                  "_internal/templates", "_INTERNAL/新しい/x.dll", "_internal\\a\\b.pyd"])
def test_a_destination_in_the_allow_list_is_taken(install, dest):
    path = updater.resolve_destination(dest)
    assert os.path.normcase(path).startswith(os.path.normcase(str(install)) + os.sep)


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows'")
def test_a_junction_out_of_the_install_folder_is_refused(install, tmp_path):
    import _winapi
    outside = tmp_path / "外"
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(install / "_internal" / "link"))
    with pytest.raises(updater.UpdateError, match="outside"):
        updater.resolve_destination("_internal/link/evil.dll")


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows'")
def test_a_junction_from_internal_to_the_users_files_is_refused(install):
    """Inside the install folder, but not inside _internal: User Files is never an update's to write."""
    import _winapi
    (install / "User Files" / "ja").mkdir(parents=True)
    _winapi.CreateJunction(str(install / "User Files"), str(install / "_internal" / "uf"))
    with pytest.raises(updater.UpdateError, match="outside _internal"):
        updater.resolve_destination("_internal/uf/ja/KnownWord.json")


def test_a_tampered_added_record_never_deletes_outside_the_install(install, tmp_path):
    """consume_result deletes only what the record names INSIDE this install."""
    outside = tmp_path / "大切.txt"
    outside.write_text("ユーザーのファイル", encoding="utf-8")
    with open(updater.added_path(), "w", encoding="utf-8") as f:
        json.dump({"added": [str(outside)], "dirs": [str(tmp_path)]}, f)
    with open(updater.result_path(), "w", encoding="utf-8") as f:
        json.dump({"status": "failed", "from": "2.5.0", "to": "2.5.1", "reason": "swap failed"}, f)
    assert updater.consume_result()["status"] == "failed"
    assert outside.read_text(encoding="utf-8") == "ユーザーのファイル"


def test_a_malformed_file_list_makes_the_update_full(tmp_path, monkeypatch):
    folder = _test_release(tmp_path / "rel")
    data = json.loads((folder / "update.json").read_text(encoding="utf-8"))
    data["files"] = "Surasura.exe"
    (folder / "update.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv(update_checker.UPDATE_SOURCE_ENV, str(folder))
    monkeypatch.setattr(build_info, "RELEASE_BUILD", False)
    info = update_checker.get_update_info()
    assert info.update_type == "full" and classify_update("2.5.0", info) == "FULL"


@pytest.mark.parametrize("entry", [
    {"name": "a/b", "dest": "_internal/x", "kind": "file", "sha256": "ab" * 32},      # not flat
    {"name": "x", "dest": "_internal/x", "kind": "link", "sha256": "ab" * 32},        # unknown kind
    {"name": "x", "dest": "_internal/x", "kind": "file", "sha256": "abc"},            # no sha256
    {"name": "x", "dest": "_internal/x", "kind": "file"},
])
def test_a_malformed_entry_is_refused(install, entry):
    with pytest.raises(updater.UpdateError):
        updater.resolve_files([entry])


def test_two_entries_with_one_name_or_one_destination_are_refused(install):
    sha = "ab" * 32
    with pytest.raises(updater.UpdateError):
        updater.resolve_files([{"name": "a", "dest": "_internal/x", "sha256": sha},
                               {"name": "A", "dest": "_internal/y", "sha256": sha}])
    with pytest.raises(updater.UpdateError):
        updater.resolve_files([{"name": "a", "dest": "_internal/x", "sha256": sha},
                               {"name": "b", "dest": "_INTERNAL/X", "sha256": sha}])


# --- the override is a non-release build's only ----------------------------------------------------------------------

def test_a_release_build_ignores_the_local_folder(local_release, monkeypatch):
    monkeypatch.setattr(build_info, "RELEASE_BUILD", True)
    asked = []
    monkeypatch.setattr(update_checker, "_http_json", lambda url, timeout=10: asked.append(url) or None)
    assert update_checker.get_update_info() is None
    assert asked and asked[0].startswith("https://api.github.com/")


def test_no_folder_set_asks_github(monkeypatch):
    monkeypatch.delenv(update_checker.UPDATE_SOURCE_ENV, raising=False)
    monkeypatch.setattr(build_info, "RELEASE_BUILD", False)
    asked = []
    monkeypatch.setattr(update_checker, "_http_json", lambda url, timeout=10: asked.append(url) or None)
    update_checker.get_update_info()
    assert asked


def test_the_source_tree_is_never_a_release_build():
    assert build_info.RELEASE_BUILD is False


def test_package_app_writes_the_release_flag_for_a_release_freeze_only(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    original = open(os.path.join(PROJECT, "app", "build_info.py"), "rb").read()
    (tmp_path / "app" / "build_info.py").write_bytes(original)
    monkeypatch.chdir(tmp_path)
    with package_app._release_flag(False):
        assert b"RELEASE_BUILD = False" in (tmp_path / "app" / "build_info.py").read_bytes()
    with pytest.raises(ZeroDivisionError):
        with package_app._release_flag(True):
            assert b"RELEASE_BUILD = True" in (tmp_path / "app" / "build_info.py").read_bytes()
            1 / 0                                         # a failed freeze still puts it back
    assert (tmp_path / "app" / "build_info.py").read_bytes() == original


def test_the_freeze_runs_inside_the_release_flag():
    import inspect
    src = inspect.getsource(package_app.build)
    assert "_release_flag(release)" in src
    assert src.index("_release_flag(release)") < src.index("subprocess.run(cmd")


# --- the packager emits the list the client checks --------------------------------------------------------------------

def test_the_packager_lists_every_file_with_its_sha256(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    final = tmp_path / "dist" / "Surasura"
    (final / "_internal" / "templates").mkdir(parents=True)
    (final / "_internal" / "templates" / "web_app.html").write_text(TEMPLATE_NEW, encoding="utf-8")
    (final / "Surasura.exe").write_bytes(EXE_NEW)
    (final / "surasura-cli.exe").write_bytes(b"MZcli")
    (final / "RELEASE_NOTES.md").write_text("# 2.5.1\n", encoding="utf-8")
    package_app._build_app_package(str(final), "2.5.1", full_update=False)
    manifest = json.loads((tmp_path / "dist" / "update.json").read_text(encoding="utf-8"))
    assert {f["dest"] for f in manifest["files"]} == {"Surasura.exe", "surasura-cli.exe", "RELEASE_NOTES.md",
                                                      "_internal/templates"}
    pkg = str(tmp_path / "dist" / "Surasura_app_v2.5.1.zip")
    # The client accepts it by the list (2.5) and by 2.4.0's own check (the same layout).
    assert updater.extract_and_validate(pkg, str(tmp_path / "p1"), manifest["files"]) is True
    assert updater.extract_and_validate(pkg, str(tmp_path / "p2")) is True


# --- cancel / close / kill during the wait ------------------------------------------------------------------------------

def test_a_killed_app_during_the_wait_leaves_no_failure_and_the_lock_free(install, local_release):
    """A real process stages the update, holds the lock, and is killed during the wait: the next start reports
    nothing (no marker was written) and a new update can take the lock."""
    code = textwrap.dedent(f"""
        import sys, time
        from app import path_utils, updater, update_checker
        path_utils.is_frozen = lambda: True
        path_utils.get_user_data_path = lambda: {str(install)!r}
        path_utils.get_base_path = lambda: {os.path.join(str(install), "_internal")!r}
        lock = updater.take_update_lock()
        updater.hold_children()
        updater.prepare_update(update_checker.get_update_info())
        print("waiting" if lock else "no lock", flush=True)
        time.sleep(60)
    """)
    env = dict(os.environ, PYTHONPATH=PROJECT, PYTHONIOENCODING="utf-8")
    env.pop("PYTEST_CURRENT_TEST", None)
    p = subprocess.Popen([PYTHON, "-c", code], cwd=PROJECT, env=env, stdout=subprocess.PIPE)
    try:
        assert p.stdout.readline().strip() == b"waiting"
        assert updater.take_update_lock() is None            # held by the waiting app
    finally:
        p.kill()
        p.wait()
    assert updater.consume_result() is None
    lock = updater.take_update_lock()
    assert lock is not None
    updater.drop_update_lock(lock)
