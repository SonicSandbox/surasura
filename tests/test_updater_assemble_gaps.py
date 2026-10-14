"""S3.1 row 3.1.3: gaps the Haiku mutant list found in the assembler's checks (tests/test_updater_assemble.py holds the
rest). Each test names the guarantee it holds; none touches the network, the registry or a real install."""
import errno
import os

import pytest

from app import updater
from tests import update_kit as kit
from tests.test_updater_assemble import _info


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    kit.isolate_registry(monkeypatch)


def _files(paths):
    return [{"path": p, "sha256": "cd" * 32, "size": 2, "part": "app"} for p in paths]


def test_a_release_naming_a_top_level_file_where_another_needs_its_folder_is_refused():
    # `tools` as a file and `tools/y.dll` can't both be in one program folder. The folder check has to count a
    # top-level name as a folder too, not only deeper ones (the suite's case is `_internal/x` + `_internal/x/y.dll`):
    # otherwise the stage is half-built when the second file can't be written.
    files = _files(["Surasura.exe", "surasura-cli.exe", "updater.exe", "tools", "tools/y.dll"])
    with pytest.raises(updater.UpdateError, match="needs a folder"):
        updater.package_files({"files": files})


def test_a_progress_window_that_raises_never_stops_the_staging(tmp_path, monkeypatch):
    # The caller's progress callback is a window's: closed mid-update, Qt raises RuntimeError ("wrapped C/C++ object
    # ... has been deleted"). The figure is the window's business; the staging goes on to a whole stage.
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)

    def closed(done, total):
        raise RuntimeError("wrapped C/C++ object of type QProgressBar has been deleted")
    marker = updater.prepare_update(_info(), progress_cb=closed)
    assert kit.tree(marker["staged"]) == kit.digests(kit.program(kit.NEW))


def test_a_failure_that_isnt_an_update_error_still_leaves_nothing_staged(tmp_path, monkeypatch):
    # "Any failure leaves nothing staged": a disk filling up mid-extract raises OSError, not UpdateError — it too is
    # reported as an UpdateError (what the caller catches) and takes the half-built stage with it.
    kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(updater, "_extract", full)
    with pytest.raises(updater.UpdateError):
        updater.prepare_update(_info())
    assert not os.path.exists(updater.stage_dir(kit.NEW))


def test_where_a_hard_link_is_refused_unchanged_files_are_copied_and_the_install_is_untouched(tmp_path, monkeypatch):
    # The stage hard-links the installed program's unchanged files. A volume that refuses a link for any reason (FAT or
    # exFAT, another device, a link limit — not only "access denied") falls back to a COPY, and only a copy: the
    # installed program is the user's to keep working with should the update stop, so not one of its files may move.
    root = kit.install(tmp_path, monkeypatch)
    kit.build_release(tmp_path, monkeypatch)
    before = kit.tree(root)

    def refused(src, dst, *args, **kwargs):
        raise OSError(errno.EXDEV, "no hard links here", src)
    monkeypatch.setattr(updater.os, "link", refused)
    marker = updater.prepare_update(_info())
    stage = marker["staged"]
    assert kit.tree(stage) == kit.digests(kit.program(kit.NEW)), "the complete program, its unchanged files copied"
    assert not os.path.samefile(os.path.join(stage, "_internal", "PyQt6", "QtCore.pyd"),
                                root / "_internal" / "PyQt6" / "QtCore.pyd")
    assert kit.tree(root) == before


def test_an_internal_folder_that_is_a_junction_out_of_the_install_is_refused(tmp_path):
    # The install-folder check compares REAL paths: when `_internal` itself is a junction to a folder elsewhere, every
    # destination under it resolves outside the install. The `_internal` check alone can't see it (both sides resolve
    # through the same junction), and a path compared as written always starts with the install folder.
    _winapi = pytest.importorskip("_winapi")
    root = tmp_path / "スラスラ 本番"
    outside = tmp_path / "外の場所"
    root.mkdir()
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(root / "_internal"))
    try:
        with pytest.raises(updater.UpdateError, match="outside the install folder"):
            updater.resolve_destination("_internal/新しい/x.dll", str(root))
    finally:
        os.rmdir(root / "_internal")                     # the junction only, never what it points at
    assert os.listdir(outside) == []
