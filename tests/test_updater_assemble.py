"""S3.1 row 3.1.3 (D4, D9): a 3.x release is the whole program, downloaded by part and assembled.

The release is built by the packager's own function and signed with a test key into a local folder read through the
update check's override (`update_kit.build_release`; never in a release build). The installed program is a temp folder
with a Japanese name, shaped like a build, beside Inno's uninstaller and — should an installed copy run portable — the
library's own folders. `prepare_update` must hash the install, fetch only the parts holding a changed or missing file,
assemble the complete new program in <Houseki local root>\\update\\stage-<ver> (unchanged files hard-linked), check every
file, and return the swapper's marker without writing it. Any failure leaves nothing staged. The swap is row 3.1.4's
(tests/test_swapper_folder.py)."""
import json
import os
import zipfile

import pytest

from tests import update_kit as kit
from app import path_utils
from app import update_checker
from app import updater
from app.update_checker import UpdateInfo, classify_update


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    kit.isolate_registry(monkeypatch)


@pytest.fixture
def fetched(monkeypatch):
    """Every URL `download` is asked for, in order (the real download still runs)."""
    urls, real = [], updater.download

    def spy(url, dest, progress_cb=None, timeout=60):
        urls.append(os.path.basename(url))
        return real(url, dest, progress_cb=progress_cb, timeout=timeout)
    monkeypatch.setattr(updater, "download", spy)
    return urls


def _update_folder_names():
    return sorted(os.listdir(updater.update_dir()))


def _info():
    info = update_checker.get_update_info()
    assert info.format == 2 and info.signed and info.package, "the test release must read as a signed 3.x release"
    return info


# --- the ordinary release: only the app part ---------------------------------------------------------------------------

def test_only_the_changed_part_is_fetched_and_the_stage_is_exactly_the_release(tmp_path, monkeypatch, fetched):
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    before = kit.tree(root)
    info = _info()
    assert classify_update(kit.OLD, info) == "APP" and updater.can_auto_apply(info)
    seen = []
    marker = updater.prepare_update(info, progress_cb=lambda done, total: seen.append((done, total)))

    assert fetched == [f"surasura_part_app_v{kit.NEW}.zip"], "Qt, the dictionaries and the runtime are unchanged"
    stage = marker["staged"]
    assert stage == updater.stage_dir(kit.NEW) and os.path.dirname(stage) == updater.update_dir()
    assert kit.tree(stage) == kit.digests(kit.program(kit.NEW)), "the complete program, nothing more"
    # unchanged files are the installed bytes, hard-linked (no second copy of 495 MB)
    assert os.path.samefile(os.path.join(stage, "_internal", "PyQt6", "QtCore.pyd"),
                            root / "_internal" / "PyQt6" / "QtCore.pyd")
    assert not os.path.samefile(os.path.join(stage, "Surasura.exe"), root / "Surasura.exe")
    # nothing armed, nothing installed, no download left behind
    assert not os.path.exists(updater.marker_path())
    assert kit.tree(root) == before
    assert _update_folder_names() == [f"stage-{kit.NEW}"]
    # one progress, to one total, never backwards
    totals = {t for _d, t in seen}
    assert len(totals) == 1 and seen[-1][0] == seen[-1][1] and [d for d, _t in seen] == sorted(d for d, _t in seen)


def test_the_marker_is_the_swappers_whole_contract(tmp_path, monkeypatch):
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    marker = updater.prepare_update(_info())
    assert marker["format"] == 3 and marker["kind"] == "folder" and marker["going_back"] is False
    assert (marker["from_version"], marker["target_version"]) == (kit.OLD, kit.NEW)
    assert marker["install"] == str(root) and marker["window"] is True
    assert marker["previous"] == os.path.join(updater.previous_root(), kit.OLD)
    assert marker["swapper"] == os.path.join(marker["staged"], "updater.exe"), "the NEW release's swapper runs"
    assert marker["result_path"] == updater.result_path()
    assert marker["files"] == kit.digests(kit.program(kit.NEW))
    assert marker["kept_files"] == kit.digests(kit.old_program()), "3.0.0's own list, for Go back's proof"
    # the program's entries move; Inno's and the library's never do
    assert {"_internal", "Surasura.exe", "surasura-cli.exe", "updater.exe", "UPDATE_INSTRUCTIONS.md"} <= \
        set(marker["owned"])
    assert not {"unins000.exe", "unins000.dat", "User Files", "data", "results", "settings.json"} & \
        set(marker["owned"])
    headless = updater.prepare_update(_info(), window=False)
    assert headless["window"] is False


# --- what is installed decides what is fetched -----------------------------------------------------------------------

def test_a_corrupted_installed_file_fetches_its_part(tmp_path, monkeypatch, fetched):
    root = kit.install(tmp_path, monkeypatch)
    (root / "_internal" / "PyQt6" / "QtCore.pyd").write_bytes(b"MZ\x90\x00 damaged on disk")
    kit.build_release(tmp_path, monkeypatch)
    marker = updater.prepare_update(_info())
    assert sorted(fetched) == sorted([f"surasura_part_app_v{kit.NEW}.zip", f"surasura_part_qt_v{kit.NEW}.zip"])
    assert kit.tree(marker["staged"]) == kit.digests(kit.program(kit.NEW))
    assert (root / "_internal" / "PyQt6" / "QtCore.pyd").read_bytes() == b"MZ\x90\x00 damaged on disk", \
        "the install itself is never written while staging"


def test_a_missing_installed_file_fetches_its_part(tmp_path, monkeypatch, fetched):
    root = kit.install(tmp_path, monkeypatch)
    os.remove(root / "_internal" / "jieba" / "dict.txt")
    kit.build_release(tmp_path, monkeypatch)
    marker = updater.prepare_update(_info())
    assert f"surasura_part_dict_v{kit.NEW}.zip" in fetched
    assert kit.tree(marker["staged"]) == kit.digests(kit.program(kit.NEW))


def test_a_same_size_file_with_other_bytes_is_not_trusted(tmp_path, monkeypatch, fetched):
    """Size alone never decides: a file of the right size with other bytes fetches its part."""
    root = kit.install(tmp_path, monkeypatch)
    data = (root / "_internal" / "sqlite3.dll").read_bytes()
    (root / "_internal" / "sqlite3.dll").write_bytes(data[:-1] + b"!")
    kit.build_release(tmp_path, monkeypatch)
    updater.prepare_update(_info())
    assert f"surasura_part_runtime_v{kit.NEW}.zip" in fetched


# --- stale and foreign files -----------------------------------------------------------------------------------------

def test_stale_files_are_not_staged_and_foreign_files_are_never_named(tmp_path, monkeypatch):
    root = kit.install(tmp_path, monkeypatch, layout="unins")
    kit.build_release(tmp_path, monkeypatch)
    marker = updater.prepare_update(_info())
    staged = kit.tree(marker["staged"])
    assert "_internal/old_only.dll" not in staged and "UPDATE_INSTRUCTIONS.md" not in staged
    assert not any(p.startswith(("unins", "User Files", "data/", "results/", "settings.json")) for p in staged)
    assert "UPDATE_INSTRUCTIONS.md" in marker["owned"], "a dropped program file moves out with the swap"
    assert (root / "User Files" / "ja" / "KnownWord.json").read_bytes() == kit.FOREIGN["User Files/ja/KnownWord.json"]


@pytest.mark.parametrize("path, why", [
    ("../outside.dll", "leaves"),
    ("C:/Windows/evil.dll", "absolute"),
    ("User Files/ja/KnownWord.json", "not the program's"),
    ("settings.json", "not the program's"),
    ("data/ja/x.txt", "not the program's"),
    ("unins000.exe", "not the program's"),
    ("_internal/con.txt", "device"),
    ("_internal/PROGRA~1/x.dll", "short"),
    ("_internal/a.dll:stream", "plain"),
    ("_internal/trailing.", "plain"),
])
def test_a_release_naming_what_isnt_the_programs_is_refused(path, why):
    files = [{"path": p, "sha256": "ab" * 32, "size": 1, "part": "app"}
             for p in ("Surasura.exe", "surasura-cli.exe", "updater.exe", path)]
    with pytest.raises(updater.UpdateError, match=why):
        updater.package_files({"files": files})


@pytest.mark.parametrize("paths, why", [
    (["Surasura.exe", "surasura-cli.exe", "updater.exe", "SURASURA.exe"], "twice"),
    (["Surasura.exe", "surasura-cli.exe", "updater.exe", "_internal/x", "_internal/x/y.dll"], "needs a folder"),
    (["Surasura.exe", "surasura-cli.exe", "_internal/x.dll"], "updater.exe"),
    (["surasura-cli.exe", "updater.exe"], "Surasura.exe"),
])
def test_a_release_list_that_cant_be_one_program_is_refused(paths, why):
    files = [{"path": p, "sha256": "cd" * 32, "size": 2, "part": "app"} for p in paths]
    with pytest.raises(updater.UpdateError, match=why):
        updater.package_files({"files": files})


def test_a_bad_list_is_a_manual_download(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    info = UpdateInfo(version=kit.NEW, format=2, signed=True,
                      package={"files": [{"path": "../x", "sha256": "ab" * 32, "size": 1, "part": "app"}]})
    assert updater.can_auto_apply(info) is False
    assert updater.effective_class("APP", info, can_apply=updater.can_auto_apply(info)) == "FULL"


# --- a bad part stages nothing --------------------------------------------------------------------------------------------

def test_a_tampered_part_stages_nothing(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    out = kit.build_release(tmp_path, monkeypatch)
    part = out / f"surasura_part_app_v{kit.NEW}.zip"
    data = bytearray(part.read_bytes())
    data[len(data) // 2] ^= 0xFF
    part.write_bytes(bytes(data))
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.prepare_update(_info())
    assert _update_folder_names() == [] and not os.path.exists(updater.marker_path())


def test_a_part_whose_file_isnt_the_listed_one_stages_nothing(tmp_path, monkeypatch):
    """The part's own sha256 matches (a list built wrong, or a part swapped with its sha256): each file is still
    checked against its own entry as it is taken out — and the half-assembled stage goes."""
    root = kit.install(tmp_path, monkeypatch)
    part = tmp_path / "part_app.zip"
    with zipfile.ZipFile(part, "w") as z:
        for rel in kit.APP_PART_FILES:
            data = kit.program(kit.NEW)[rel]
            z.writestr(rel, data if rel != "_internal/templates/web_app.html" else data.replace(b"3.0.1", b"9.9.9"))
    files = [{"path": rel, "sha256": sha, "size": len(kit.program(kit.NEW)[rel]),
              "part": "app" if rel in kit.APP_PART_FILES else "rest"}
             for rel, sha in kit.digests(kit.program(kit.NEW)).items()]
    info = UpdateInfo(version=kit.NEW, format=2, signed=True, assets={"app.zip": part.as_uri()},
                      package={"parts": [{"name": "app", "asset": "app.zip", "sha256": updater.sha256_file(str(part)),
                                          "size": part.stat().st_size},
                                         {"name": "rest", "asset": "rest.zip", "sha256": "00" * 32, "size": 0}],
                               "files": files, "min_from": "3.0.0", "needs_installer": False})
    before = kit.tree(root)
    # "in the app part": refused as the file leaves its part (`_extract`), not only by the stage check after it, which
    # raises too — with the sha256 taken out of `_extract` (mutant U14) this passed on the stage check's message.
    with pytest.raises(updater.UpdateError, match=r"web_app\.html in the app part"):
        updater.prepare_update(info)
    assert _update_folder_names() == [] and kit.tree(root) == before


def test_an_unsigned_package_is_never_assembled(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    info = UpdateInfo(version=kit.NEW, format=2, signed=False, package={"files": [], "parts": []})
    with pytest.raises(updater.UpdateError, match="signed"):
        updater.prepare_update(info)


# --- only an installed program updates itself --------------------------------------------------------------------

def test_a_portable_program_is_refused(tmp_path, monkeypatch, fetched):
    root = kit.install(tmp_path, monkeypatch, layout="portable")
    kit.build_release(tmp_path, monkeypatch)
    info = _info()
    assert updater.is_installed() is False and updater.can_auto_apply(info) is False
    assert updater.effective_class("APP", info, can_apply=updater.can_auto_apply(info)) == "FULL"
    before = kit.tree(root)
    with pytest.raises(updater.UpdateError, match="only an installed Surasura"):
        updater.prepare_update(info)
    assert fetched == [] and _update_folder_names() == [] and kit.tree(root) == before


def test_a_source_run_is_refused(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    info = _info()
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    assert updater.can_auto_apply(info) is False
    with pytest.raises(updater.UpdateError, match="frozen"):
        updater.prepare_update(info)


def test_an_unreadable_library_note_with_inno_files_still_counts_as_installed(tmp_path, monkeypatch, fetched):
    root = kit.install(tmp_path, monkeypatch, layout="unins")
    kit.build_release(tmp_path, monkeypatch)
    assert updater.is_installed() and updater._install_dir() == str(root)
    marker = updater.prepare_update(_info())
    assert marker["install"] == str(root)
    os.remove(root / "unins000.dat")
    assert updater.is_installed() is False, "without it, the copy is portable"


def test_the_installed_layout_uses_the_program_folder_never_the_library(tmp_path, monkeypatch):
    root = kit.install(tmp_path, monkeypatch, layout="installed")
    assert path_utils.get_user_data_path() != str(root)
    assert updater._install_dir() == str(root)
    assert updater.updater_exe_path() == str(root / "updater.exe")


def test_a_program_on_another_drive_than_its_update_folder_is_refused(tmp_path, monkeypatch):
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    real_stat = os.stat

    class _Other:
        def __init__(self, st):
            self.st = st
            self.st_dev = st.st_dev + 1

        def __getattr__(self, name):
            return getattr(self.st, name)

    def stat(path, *a, **kw):
        st = real_stat(path, *a, **kw)
        return _Other(st) if os.path.normcase(str(path)) == os.path.normcase(str(root)) else st
    monkeypatch.setattr(updater.os, "stat", stat)
    with pytest.raises(updater.UpdateError, match="different drives"):
        updater.prepare_update(_info())
    monkeypatch.setattr(updater.os, "stat", real_stat)
    assert _update_folder_names() == []


# --- the update folder's own housekeeping ----------------------------------------------------------------------------

def test_every_state_file_lives_in_the_update_folder(tmp_path, monkeypatch):
    root = kit.install(tmp_path, monkeypatch)
    folder = os.path.join(path_utils.local_data_root(), "update")
    for path in (updater.marker_path(), updater.result_path(), updater.report_path(), updater.staging_dir(),
                 updater.backup_dir(), updater.added_path(), updater.previous_root(), updater.swapper_dir(),
                 updater.stage_dir(kit.NEW)):
        assert os.path.dirname(path) == folder and not path.startswith(str(root))


def test_a_stage_name_is_only_ever_a_version():
    for bad in ("..", "3.0.1/../x", "3.0.1\\x", "", None, "3.0.1 ", "v3.0.1"):
        with pytest.raises(updater.UpdateError):
            updater.stage_dir(bad)


def test_discard_staged_keeps_the_previous_version(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {f"stage-{kit.NEW}/Surasura.exe": b"MZ", f"download-{kit.NEW}/p.zip": b"PK",
                                          f"installer-{kit.NEW}/setup.exe": b"MZ", "staging/payload/x": b"x",
                                          f"previous/{kit.OLD}/Surasura.exe": b"MZ old",
                                          f"previous/{kit.OLD}.files.json": b"{}"})
    updater.discard_staged()
    assert _update_folder_names() == ["previous"]
    assert sorted(os.listdir(updater.previous_root())) == [kit.OLD, f"{kit.OLD}.files.json"]


def test_a_new_staging_sweeps_an_earlier_one(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {"stage-3.0.0.9/Surasura.exe": b"MZ", "download-3.0.0.9/p.zip": b"PK"})
    updater.prepare_update(_info())
    assert _update_folder_names() == [f"stage-{kit.NEW}"]


def test_2x_state_beside_the_exe_is_read_once_then_gone(tmp_path, monkeypatch):
    """An install whose earlier updater kept its state beside the exe: the next start reads it (from the update
    folder first) and removes it, so it is never reported twice."""
    root = kit.install(tmp_path, monkeypatch, layout="unins")
    kit.write_tree(root, {"last_update_result.json": json.dumps(
        {"status": "failed", "from": "2.5.0", "to": "3.0.0", "reason": "post-swap verification failed"}).encode(),
        ".update_staging/payload/Surasura.exe": b"MZ", ".update_backup/Surasura.exe": b"MZ"})
    res = updater.consume_result()
    assert res["status"] == "failed" and res["to"] == "3.0.0"
    assert not (root / "last_update_result.json").exists()
    assert not (root / ".update_staging").exists() and not (root / ".update_backup").exists()
    assert updater.consume_result() is None
    assert (root / "unins000.dat").exists() and (root / "Surasura.exe").exists()


def test_the_update_folders_result_wins_and_sweeps_spent_swappers(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.update_dir(), {
        "last_update_result.json": json.dumps({"status": "success", "from": kit.OLD, "to": kit.NEW,
                                               "reason": "ok"}).encode(),
        f"swapper/updater-{kit.NEW}.exe": b"MZ", f"stage-{kit.NEW}/x": b"", f"previous/{kit.OLD}/Surasura.exe": b"MZ"})
    assert updater.consume_result()["status"] == "success"
    assert _update_folder_names() == ["previous"]


@pytest.mark.parametrize("damaged, status", [(False, "success"), (True, "failed")])
def test_a_3x_marker_left_by_a_swapper_that_died_is_judged_by_its_files(tmp_path, monkeypatch, damaged, status):
    root = kit.install(tmp_path, monkeypatch, files=kit.program(kit.NEW), version=kit.NEW)
    if damaged:
        (root / "_internal" / "jieba" / "dict.txt").write_bytes(b"half written")
    marker = {"format": 3, "kind": "folder", "from_version": kit.OLD, "target_version": kit.NEW, "install": str(root),
              "files": kit.digests(kit.program(kit.NEW))}
    updater.write_marker(marker)
    res = updater.consume_result()
    assert res["status"] == status and res["to"] == kit.NEW
    assert not os.path.exists(updater.marker_path())


def test_a_3x_marker_for_another_version_is_a_failure(tmp_path, monkeypatch):
    root = kit.install(tmp_path, monkeypatch)
    updater.write_marker({"format": 3, "from_version": kit.OLD, "target_version": kit.NEW, "install": str(root),
                          "files": kit.digests(kit.program(kit.NEW))})
    assert updater.consume_result()["status"] == "failed"


def test_dropping_the_update_lock_twice_never_raises(tmp_path, monkeypatch):
    held = updater.take_update_lock()
    assert held is not None
    updater.drop_update_lock(held)
    updater.drop_update_lock(held)                       # an already-closed handle: path_utils raises ValueError
    updater.drop_update_lock(None)


# --- the wait widened: any program in the folder --------------------------------------------------------------------

def test_another_program_running_from_the_folder_is_waited_for_never_stopped(tmp_path, monkeypatch):
    import shutil
    import subprocess
    root = kit.install(tmp_path, monkeypatch)
    helper = root / "helpers" / "helper.exe"          # not beside the kit's fake python311.dll: it would load that
    helper.parent.mkdir()
    shutil.copy(kit.PYTHON, helper)
    go = tmp_path / "go"
    proc = subprocess.Popen([str(helper), "-c", "import os, time\n"
                             f"while not os.path.exists({str(go)!r}): time.sleep(0.05)"])
    try:
        monkeypatch.setattr(updater, "_install_images", lambda: [str(root / "Surasura.exe"),
                                                                 str(root / "surasura-cli.exe")])
        deadline = __import__("time").monotonic() + 10
        entries = []
        while not entries and __import__("time").monotonic() < deadline:
            entries = [e for e in updater.running_children() if e["pid"] == proc.pid]
        assert entries == [{"pid": proc.pid, "name": "helper.exe", "stop": None}], "wait-only: never ended from here"
        assert updater.can_update_now() is False
        assert all(e["pid"] != proc.pid for e in updater.running_children([], images=[]))
    finally:
        go.write_text("", encoding="utf-8")
        proc.wait(timeout=10)
    assert all(e["pid"] != proc.pid for e in updater.running_children())


# --- installer mode, as the app stages it -------------------------------------------------------------------------

STUB_SETUP = b"MZ\x90\x00stub Setup \xe3\x81\x99\xe3\x82\x89" * 8


def test_installer_mode_stages_the_installer_and_the_swappers_instructions(tmp_path, monkeypatch, fetched):
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch, installer=STUB_SETUP, needs_installer=True)
    info = _info()
    assert classify_update(kit.OLD, info) == "INSTALLER"
    marker = updater.prepare_installer(info)
    assert fetched == [f"in-app-updates-{kit.NEW}.exe"], "installer mode downloads the updater's copy alone"
    assert marker["format"] == 3 and marker["kind"] == "installer"
    assert open(marker["setup"], "rb").read() == STUB_SETUP and marker["path"] == marker["setup"]
    assert os.path.dirname(os.path.dirname(marker["setup"])) == updater.update_dir()
    assert marker["setup_log"] == os.path.join(updater.update_dir(), f"setup-{kit.NEW}.log")
    assert marker["library"] == path_utils.installed_library(), "the app's library, never Inno's remembered one"
    assert marker["swapper"] == str(root / "updater.exe"), "this version's swapper runs Setup"
    assert marker["files"] == kit.digests(kit.program(kit.NEW)), "what Setup installs is proven by the release's list"
    assert not os.path.exists(updater.marker_path())


def test_installer_mode_refuses_a_bad_download_and_an_install_without_updater(tmp_path, monkeypatch):
    root = kit.install(tmp_path, monkeypatch)
    out = kit.build_release(tmp_path, monkeypatch, installer=STUB_SETUP, needs_installer=True)
    (out / f"in-app-updates-{kit.NEW}.exe").write_bytes(STUB_SETUP + b"!")
    with pytest.raises(updater.UpdateError, match="checksum"):
        updater.prepare_installer(_info())
    assert _update_folder_names() == []
    os.remove(root / "updater.exe")
    with pytest.raises(updater.UpdateError, match="updater.exe"):
        updater.prepare_installer(_info())


def test_installer_mode_refuses_a_portable_program(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch, layout="portable")
    kit.build_release(tmp_path, monkeypatch, installer=STUB_SETUP, needs_installer=True)
    with pytest.raises(updater.UpdateError, match="only an installed"):
        updater.prepare_installer(_info())


def test_the_stage_check_refuses_an_extra_file_and_a_damaged_one(tmp_path):
    """The last check before a marker exists: the assembled program is the release and nothing else."""
    files = [{"path": rel, "parts": rel.split("/"), "sha256": sha, "size": len(kit.program(kit.NEW)[rel])}
             for rel, sha in kit.digests(kit.program(kit.NEW)).items()]
    stage = tmp_path / "stage"
    kit.write_tree(stage, kit.program(kit.NEW))
    updater._verify_stage(str(stage), files, updater._Progress(None, 1))
    kit.write_tree(stage, {"_internal/stray.dll": b"MZ not the release's"})
    with pytest.raises(updater.UpdateError, match="doesn't name"):
        updater._verify_stage(str(stage), files, updater._Progress(None, 1))
    os.remove(stage / "_internal" / "stray.dll")
    kit.write_tree(stage, {"_internal/jieba/dict.txt": "开心 3 a\n".encode("utf-8")})
    with pytest.raises(updater.UpdateError, match="dict.txt"):
        updater._verify_stage(str(stage), files, updater._Progress(None, 1))


def test_a_kept_folder_without_its_program_is_never_offered(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.previous_root(), {"2.9.9/_internal/x.dll": b"MZ", "2.9.8.files.json": b"{}"})
    assert updater.previous_version() is None
    kit.write_tree(updater.previous_root(), {"2.9.9/Surasura.exe": b"MZ", "2.9.7/Surasura.exe": b"MZ"})
    assert updater.previous_version() == "2.9.9"


def test_go_back_to_the_running_version_is_refused(tmp_path, monkeypatch):
    kit.install(tmp_path, monkeypatch)
    kit.write_tree(updater.previous_root(), {f"{kit.OLD}/Surasura.exe": b"MZ"})
    with pytest.raises(updater.UpdateError, match="this one"):
        updater.prepare_go_back()
