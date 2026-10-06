"""path_utils.get_local_data_path(): the per-install local folder the command line keeps its logs, locks and events in
(P0.3 02-contract §6), and the conftest guard that keeps every test out of the real one."""
import os
import sys

import pytest

from app import path_utils
from tests import conftest


def _outside_pytest(monkeypatch):
    """What the app sees outside a test: no test root, no PYTEST_CURRENT_TEST."""
    monkeypatch.delenv("SURASURA_TEST_ROOT", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


def test_test_root_moves_the_local_folder_into_it(tmp_path, monkeypatch):
    # Every test and every smoke run keeps its logs inside its own root, created on first use.
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(tmp_path))
    path = path_utils.get_local_data_path()
    assert path == os.path.join(str(tmp_path), "local")
    assert os.path.isdir(path)


def test_a_test_without_a_root_is_refused_before_anything_is_written(monkeypatch):
    # The real folder is never one bug away from a test run (Library_Store_Spec I7, enforced in code).
    monkeypatch.delenv("SURASURA_TEST_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="SURASURA_TEST_ROOT"):
        path_utils.get_local_data_path()


@pytest.mark.skipif(sys.platform != "win32", reason="%LOCALAPPDATA% is Windows'")
def test_windows_folder_is_local_appdata_keyed_per_install(tmp_path, monkeypatch):
    _outside_pytest(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    install = tmp_path / "すらすら 日本語"          # a Japanese install folder name
    install.mkdir()
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: str(install))
    path = path_utils.get_local_data_path()
    parent, key = os.path.split(path)
    assert parent == os.path.join(str(tmp_path / "Local"), "SonicSandbox", "Surasura")
    assert len(key) == 16 and all(c in "0123456789abcdef" for c in key)
    assert os.path.isdir(path)


def test_two_installs_never_share_a_folder_and_one_install_always_gets_the_same(tmp_path, monkeypatch):
    # A development checkout and an installed copy get different keys; a second start of one install gets its own
    # key again (so its logs and locks are found).
    _outside_pytest(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))     # macOS's root comes from ~
    paths = {}
    for name in ("checkout", "インストール"):
        install = tmp_path / name
        install.mkdir()
        monkeypatch.setattr(path_utils, "get_user_data_path", lambda d=install: str(d))
        paths[name] = path_utils.get_local_data_path()
        assert path_utils.get_local_data_path() == paths[name]
    assert paths["checkout"] != paths["インストール"]


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS ignores case")
def test_windows_key_ignores_case_and_separators(tmp_path):
    # The same folder spelled differently is the same install (Library_Store_Spec §6.4: normcase on Windows). Not
    # created: realpath() spells an existing folder as the disk does, which would hide a missing normcase.
    folder = str(tmp_path / "Surasura")
    assert path_utils._install_key(folder) == path_utils._install_key(folder.upper().replace("\\", "/"))


def test_macos_and_linux_folders(tmp_path, monkeypatch):
    # Not verifiable on this machine except by the folder each system is given (05 §2: macOS/Linux until the
    # installers). Linux keeps it in $XDG_DATA_HOME, not $XDG_STATE_HOME (S1.1 K100).
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path / "home")))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert path_utils._local_data_root() == os.path.join(
        str(tmp_path / "home"), "Library", "Application Support", "SonicSandbox", "Surasura")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert path_utils._local_data_root() == os.path.join(str(tmp_path / "share"), "SonicSandbox", "Surasura")
    monkeypatch.delenv("XDG_DATA_HOME")
    assert path_utils._local_data_root() == os.path.join(
        str(tmp_path / "home"), ".local", "share", "SonicSandbox", "Surasura")


def test_the_guard_watches_the_folder_the_app_would_write(monkeypatch):
    # conftest's guard compares this checkout's real folder before and after every test; it must be the very folder
    # get_local_data_path() resolves to outside a test (computed here without creating it).
    _outside_pytest(monkeypatch)
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: None)
    assert path_utils.get_local_data_path() == conftest._REAL_LOCAL_DATA


def test_the_guard_sees_a_new_file(tmp_path):
    # The guard's comparison notices a folder appearing and a file written into it.
    folder = tmp_path / "local"
    empty = conftest._folder_state(str(folder))
    folder.mkdir()
    assert conftest._folder_state(str(folder)) != empty
    made = conftest._folder_state(str(folder))
    (folder / "cli.log").write_text("2026-10-04 ログ\n", encoding="utf-8")
    assert conftest._folder_state(str(folder)) != made
