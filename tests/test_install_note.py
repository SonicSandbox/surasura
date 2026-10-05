"""K100 (S1.1): the note in the local data root naming every install's data folder, so 3.0's first start finds the
library — `installs.json`, one entry per install, written by the frozen app only, atomically, and never by a test
outside its own root. Also `local_data_root()` itself: one root for every system.

The installs here are real folders with Japanese / Chinese names (users' install paths routinely carry them) holding
the `User Files/<lang>` folders the note reads its languages from."""
import json
import os
import subprocess
import sys
import textwrap
from unittest.mock import patch

import pytest

from app import path_utils

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _install(tmp_path, name, languages=("ja",)):
    folder = tmp_path / name
    for lang in languages:
        (folder / "User Files" / lang).mkdir(parents=True)
    return str(folder)


def _note():
    with open(os.path.join(path_utils.local_data_root(), path_utils.INSTALLS_NOTE), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def frozen_install(tmp_path, monkeypatch):
    """A frozen app whose install folder is `すらすら 本番` (its data root)."""
    install = _install(tmp_path, "すらすら 本番", ("ja", "zh"))
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: install)
    return install


def test_the_note_names_this_installs_data_folder(frozen_install):
    assert path_utils.write_install_note() is True
    [entry] = _note()
    assert entry["data_root"] == frozen_install
    assert entry["exe"] == sys.executable
    from app import __version__
    assert entry["version"] == __version__
    assert entry["languages"] == ["ja", "zh"]
    assert entry["last_run"][:4].isdigit()
    assert set(entry) == {"data_root", "exe", "version", "languages", "last_run"}


def test_the_note_lives_in_the_test_roots_local_root(frozen_install):
    path_utils.write_install_note()
    assert os.path.isfile(os.path.join(os.environ["SURASURA_TEST_ROOT"], "local_root", "installs.json"))


def test_a_second_install_adds_its_own_entry_and_never_touches_the_first(tmp_path, frozen_install, monkeypatch):
    path_utils.write_install_note()
    first = _note()[0]
    other = _install(tmp_path, "插件 测试", ("zh",))
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: other)
    path_utils.write_install_note()
    entries = {e["data_root"]: e for e in _note()}
    assert set(entries) == {frozen_install, other}
    assert entries[frozen_install] == first           # untouched
    assert entries[other]["languages"] == ["zh"]
    # The first install starting again replaces only its own entry: still two.
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: frozen_install)
    path_utils.write_install_note()
    assert sorted(e["data_root"] for e in _note()) == sorted([frozen_install, other])


def test_a_writer_whose_entry_was_overwritten_writes_again(tmp_path, frozen_install):
    """The read-back: another install's write lands between this one's swap and its check (it read the note before
    this one wrote, so its list lacks this entry). This one finds itself missing and writes the merged list."""
    other = _install(tmp_path, "インストール2")
    path = os.path.join(path_utils.local_data_root(), path_utils.INSTALLS_NOTE)
    real_replace = os.replace
    clobbered = []

    def replace(src, dst):
        real_replace(src, dst)
        if dst == path and not clobbered:           # the other writer's stale list, right after our swap
            clobbered.append(True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump([{"data_root": other, "exe": "x", "version": "2.5.0", "languages": ["ja"],
                            "last_run": "2026-10-04T20:00:00"}], f)

    with patch.object(path_utils.os, "replace", side_effect=replace):
        assert path_utils.write_install_note() is True
    assert clobbered
    assert sorted(e["data_root"] for e in _note()) == sorted([frozen_install, other])


def test_two_writers_interleaved_both_end_up_in_the_list(tmp_path):
    """Two real processes, each an install of its own, writing the note forty times at once."""
    root = os.environ["SURASURA_TEST_ROOT"]
    installs = [_install(tmp_path, "並行A"), _install(tmp_path, "並行B")]
    code = textwrap.dedent("""
        import sys
        from app import path_utils
        install = sys.argv[1]
        path_utils.is_frozen = lambda: True
        path_utils.get_user_data_path = lambda: install
        ok = all(path_utils.write_install_note() for _ in range(40))
        print("ok" if ok else "lost")
    """)
    env = dict(os.environ, SURASURA_TEST_ROOT=root, PYTHONPATH=PROJECT, PYTHONIOENCODING="utf-8")
    env.pop("PYTEST_CURRENT_TEST", None)
    procs = [subprocess.Popen([sys.executable, "-c", code, d], cwd=PROJECT, env=env, stdout=subprocess.PIPE,
                              text=True, encoding="utf-8") for d in installs]
    outs = [p.communicate(timeout=120)[0].strip() for p in procs]
    assert outs == ["ok", "ok"]
    assert sorted(e["data_root"] for e in _note()) == sorted(installs)


def test_a_source_checkout_writes_nothing(monkeypatch):
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    assert path_utils.write_install_note() is False
    assert not os.path.exists(os.path.join(path_utils.local_data_root(), path_utils.INSTALLS_NOTE))


def test_a_test_without_a_root_is_refused(monkeypatch):
    monkeypatch.delenv("SURASURA_TEST_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="SURASURA_TEST_ROOT"):
        path_utils.local_data_root()


def test_a_folder_that_cannot_be_written_never_blocks(frozen_install, monkeypatch, tmp_path):
    """The root is a FILE (as unwritable as it gets, and the same on every system): the note fails, quietly."""
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(path_utils, "local_data_root", lambda: str(blocker / "SonicSandbox"))
    assert path_utils.write_install_note() is False


def test_the_dashboard_starts_when_the_note_cannot_be_written(monkeypatch):
    """The dashboard's start writes the note off its thread; a failure there is printed, never raised."""
    from app.main import MasterDashboardApp
    def boom(frozen=None):
        raise OSError("read-only")
    monkeypatch.setattr(path_utils, "write_install_note", boom)
    MasterDashboardApp._write_install_note()       # no exception


def test_the_dashboard_start_writes_the_note(monkeypatch):
    import tkinter as tk
    from app.main import MasterDashboardApp
    calls = []
    monkeypatch.setattr(MasterDashboardApp, "_write_install_note", staticmethod(lambda: calls.append(1)))
    root = tk.Tk()
    root.withdraw()
    try:
        MasterDashboardApp(root)
        for _ in range(50):
            if calls:
                break
            import time
            time.sleep(0.02)
    finally:
        root.destroy()
    assert calls == [1]


# --- local_data_root(): one root for every system -------------------------------------------------------------------

def _outside_pytest(monkeypatch):
    monkeypatch.delenv("SURASURA_TEST_ROOT", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


@pytest.mark.skipif(sys.platform != "win32", reason="%LOCALAPPDATA% is Windows'")
def test_windows_root_is_local_appdata(tmp_path, monkeypatch):
    _outside_pytest(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert path_utils.local_data_root() == os.path.join(str(tmp_path / "Local"), "SonicSandbox", "Surasura")


def test_macos_and_linux_roots(tmp_path, monkeypatch):
    _outside_pytest(monkeypatch)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path / "home")))
    monkeypatch.setattr(sys, "platform", "darwin")
    assert path_utils.local_data_root() == os.path.join(
        str(tmp_path / "home"), "Library", "Application Support", "SonicSandbox", "Surasura")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert path_utils.local_data_root() == os.path.join(str(tmp_path / "data"), "SonicSandbox", "Surasura")
    monkeypatch.delenv("XDG_DATA_HOME")
    assert path_utils.local_data_root() == os.path.join(
        str(tmp_path / "home"), ".local", "share", "SonicSandbox", "Surasura")


def test_the_per_install_folder_is_built_on_the_root(tmp_path, monkeypatch):
    _outside_pytest(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "Local"))
    install = _install(tmp_path, "すらすら")
    monkeypatch.setattr(path_utils, "get_user_data_path", lambda: install)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path / "home")))
    parent, key = os.path.split(path_utils.get_local_data_path())
    assert parent == path_utils.local_data_root()
    assert key == path_utils._install_key(install) and len(key) == 16


def test_a_writer_waits_for_another_writers_lock(frozen_install):
    """While another writer holds installs.lock, a write waits for it (up to ~1 s) rather than crossing it: the
    read-back above repairs a crossing it sees, the lock keeps the one it can't see (the other's write landing after
    this one's check) from happening at all."""
    import threading
    import time
    root = path_utils.local_data_root()
    held = path_utils.try_lock(os.path.join(root, "installs.lock"))
    assert held is not None
    threading.Timer(0.4, path_utils.release_lock, args=(held,)).start()
    start = time.monotonic()
    assert path_utils.write_install_note() is True
    assert time.monotonic() - start >= 0.35
