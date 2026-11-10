"""S3.1 rows 3.1.4 / S3.1-5: gaps the Haiku mutant list found in the swapper (tests/test_swapper_folder.py holds the
rest, and its fixtures build the swaps here too: a 3.0.0 program installed in a temp folder with a Japanese name, a
signed 3.0.1 release assembled by the app's own `prepare_update`). No test here reaches the registry: the swapper file's
throwaway RunOnce key is in force, and where the entry is concerned its key is refused before it is opened."""
import os

import pytest

import updater_helper
from app import updater
from tests import update_kit as kit
from tests.test_swapper_folder import (_fast, _run, _splash_on_the_tests_desktop, _values, registry,  # noqa: F401
                                       runonce, staged)                                # (fixtures, by name)


def test_forgetting_the_recovery_entry_never_raises_whatever_refuses_it(tmp_path, monkeypatch):
    # forget_recovery runs in the `finally` of every installer-mode swap and recovery: a failure there (the key
    # refused — access denied, or, under a test, no throwaway key named) must never replace the swap's own exit code
    # or stop its result being written. A narrower `except` (only a missing value) would let it escape.
    def refused():
        raise PermissionError("the RunOnce key refused")
    monkeypatch.setattr(updater_helper, "_runonce_root", refused)
    assert updater_helper.forget_recovery(str(tmp_path)) is None


@pytest.mark.parametrize("change", ["staged in a sibling named like the update folder", "install is the update folder",
                                    "owns data. (Windows reads it as data)"])
def test_a_marker_the_app_didnt_write_changes_nothing_however_close_it_comes(staged, change):
    # The swapper trusts no path in the marker: the stage must be strictly INSIDE the update folder (`update` and
    # `update-old` are siblings, whatever their names share), the install apart from it — not even the same folder —
    # and every entry it moves one plain name. A trailing dot is no plain name: Windows drops it, so "data." would
    # move the library's own data folder.
    root, marker, before = staged
    update = updater.update_dir()
    if change.startswith("staged"):
        marker["staged"] = os.path.join(update.rstrip("\\/") + "-old", os.path.basename(marker["staged"]))
        os.makedirs(marker["staged"])
    elif change.startswith("install"):
        marker["install"] = update
    else:
        marker["owned"] = marker["owned"] + ["data."]
    ops = kit.FakeOps()
    code, result = _run(marker, ops)
    assert result["status"] == "failed" and "were not Surasura's" in result["reason"]
    assert kit.tree(root) == before and ops.started == [], "nothing touched, nothing started"


@pytest.mark.parametrize("nth", [1, 6])
def test_a_rename_that_fails_is_never_counted_as_an_item_left_out(staged, monkeypatch, nth):
    # A move is recorded only once its rename has gone through: the rollback then reverses what really moved, and
    # the person is told nothing is stuck. Recording it first would have the rollback try to bring back an entry that
    # never left, fail, and report "1 item(s) could not be put back" over an install that is whole.
    root, marker, before = staged
    real_rename, calls = os.rename, []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == nth:
            raise PermissionError(13, "simulated: held by another process", src)
        return real_rename(src, dst)
    monkeypatch.setattr(updater_helper.os, "rename", flaky)
    monkeypatch.setattr(updater_helper, "RENAME_TRIES", 1)
    code, result = _run(marker, kit.FakeOps())
    monkeypatch.setattr(updater_helper.os, "rename", real_rename)
    assert result["status"] == "failed" and "could not be put back" not in result["reason"]
    assert kit.tree(root) == before


@pytest.mark.parametrize("path", ["D:x", "_internal/C:python311.dll", "README.md:hidden"])
def test_a_release_file_named_with_a_drive_or_a_stream_isnt_one(tmp_path, path):
    # The release's file list is checked inside the install only: "D:x" would be joined onto drive D (outside the
    # install), "name:stream" would read an alternate stream of another file. Neither is a file the release can name.
    with pytest.raises(updater_helper.SwapError, match="isn't one"):
        updater_helper._file_path(str(tmp_path), path)


def test_the_uninstall_entry_carries_the_versions_minor_number(tmp_path, registry):
    # Windows' installed-apps list reads MinorVersion / VersionMinor: 3.4.1 is minor 4. Every release so far has a
    # minor of 0 (3.0.x), so only a version with another minor tells the second number from none.
    root = tmp_path / "スラスラ 本番"
    root.mkdir()
    path = registry("{SURASURA-TEST-8}", root, DisplayVersion="3.0.1")
    assert updater_helper.write_uninstall_version("{SURASURA-TEST-8}", str(root), "3.4.1") is True
    values = _values(path)
    assert values["DisplayVersion"] == "3.4.1"
    assert (values["MajorVersion"], values["MinorVersion"], values["VersionMajor"], values["VersionMinor"]) == \
        (3, 4, 3, 4)


def test_what_setup_wrote_goes_even_when_it_cant_be_set_aside(tmp_path):
    # A failed installer-mode swap clears what Setup wrote under the program's names by moving it to
    # previous\failed-<ver>; when that folder can't be made (here a file holds its name) each entry is removed
    # instead. Left in place, it would block the old entry coming back from previous.
    install = tmp_path / "スラスラ"
    (install / "_internal").mkdir(parents=True)
    (install / "_internal" / "python311.dll").write_bytes(b"new build")
    (install / "Surasura.exe").write_bytes(b"new build")
    (install / "設定メモ.txt").write_text("the person's own file", encoding="utf-8")
    previous = tmp_path / "update" / "previous" / "3.0.0"
    previous.mkdir(parents=True)
    blocker = previous.parent / "failed-3.0.1"
    blocker.write_bytes(b"a file where the folder would go")
    m = {"install": str(install), "previous": str(previous), "target_version": "3.0.1"}
    updater_helper._clear_setups(m, ["_internal", "Surasura.exe"], lambda _s: None)
    assert sorted(os.listdir(install)) == ["設定メモ.txt"]
    assert blocker.read_bytes() == b"a file where the folder would go"
