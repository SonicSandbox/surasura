"""S3.1 row 3.1.0 — where the 3.0 program keeps its files (SPEC D3, D14, D20).

What a wrong answer would cost, in order:
  * an installed program writing the library, or settings.json, into its program folder — a whole-folder update swap
    (D4, D9) would carry them away;
  * the per-install folder (window state, logs, locks) moving with the library;
  * a 2.x and a 3.0 writing Anki at once — the shared `anki-writer` lock is taken in BOTH per-user roots;
  * a source run or a test reading the installer's library.json — they keep the layout they have;
  * a new library that never gets the bundled default lists, or one whose own list is overwritten by them;
  * GraduatedList.txt made again after 3.0 merged it into the known words (row 3.1.7).

Every root here is a temp folder: the environment's %LOCALAPPDATA% / %APPDATA% / XDG_DATA_HOME and the program's
`sys.executable` are pointed into `tmp_path`, never the real ones. Folder names carry Japanese and Chinese, as users'
paths do."""
import json
import os
import subprocess
import sys

import pytest

from app import locks, path_utils

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable          # the real interpreter: the `program` fixture points sys.executable at a fake exe
WINDOWS = sys.platform == "win32"


def _outside_pytest(monkeypatch):
    """What the app sees outside a test: no test root, no PYTEST_CURRENT_TEST."""
    monkeypatch.delenv("SURASURA_TEST_ROOT", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)


@pytest.fixture
def bases(tmp_path, monkeypatch):
    """The per-user bases pointed into tmp_path (every system's variable), library.json's cache emptied."""
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("XDG_DATA_HOME", str(local))
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(tmp_path / "home")))
    monkeypatch.setattr(path_utils, "_LIBRARY", {})
    return {"local": str(local), "roaming": str(roaming)}


@pytest.fixture
def program(tmp_path, monkeypatch, bases):
    """A frozen program in `Programs/すらすら` (its bundle, `_internal`, beside it), outside any test root. (A test
    that reaches the per-install folder or the local root calls `_outside_pytest` in its body too: pytest sets
    PYTEST_CURRENT_TEST again for the call.)"""
    folder = tmp_path / "Programs" / "すらすら"
    (folder / "_internal").mkdir(parents=True)
    _outside_pytest(monkeypatch)
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(folder / "Surasura.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(folder / "_internal"), raising=False)
    monkeypatch.setattr(path_utils, "_DATA_NAME", {})
    return str(folder)


def _write_note(content):
    """Write library.json into the Houseki local root (as the installer does, before any start)."""
    root = path_utils._local_data_root()
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, path_utils.LIBRARY_NOTE)
    with open(path, "wb") as f:
        f.write(content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode("utf-8"))
    return path


def _library_note(program, library):
    """The installer's note for `program`: its library is `library`."""
    return _write_note({"version": 1, "install": program, "library": library})


# --- installed vs portable vs source vs test root ------------------------------------------------------------------

def test_an_installed_program_keeps_the_library_in_the_chosen_folder_and_settings_in_the_roaming_root(tmp_path,
                                                                                                      program,
                                                                                                      monkeypatch):
    _outside_pytest(monkeypatch)                        # the roaming root refuses a test without a root
    library = str(tmp_path / "ドキュメント" / "すらすら 图书馆")
    note = _library_note(program, library)
    assert os.path.dirname(note) == os.path.join(path_utils._local_base(), "Houseki", "Surasura")   # LOCAL root
    assert path_utils.installed_library() == library
    assert path_utils.get_user_data_path() == library
    assert path_utils.get_user_files_path("ja") == os.path.join(library, "User Files", "ja")
    assert path_utils.get_data_path("zh") == os.path.join(library, "data", "zh")
    assert path_utils.get_user_file("results") == os.path.join(library, "results")
    assert path_utils.get_settings_path() == os.path.join(path_utils._roaming_base(), "Houseki", "Surasura",
                                                          "settings.json")
    # Never beside the program: a whole-folder update swap would take it along.
    assert not path_utils.get_settings_path().startswith(program)


def test_the_install_field_is_matched_whatever_its_case_or_separators(tmp_path, program):
    library = str(tmp_path / "すらすら")
    _library_note(program.replace("\\", "/").upper() if WINDOWS else program + os.sep, library)
    assert path_utils.installed_library() == library


def test_an_installed_programs_own_folder_is_keyed_on_the_program_folder_not_the_library(tmp_path, program,
                                                                                         monkeypatch):
    _outside_pytest(monkeypatch)
    _library_note(program, str(tmp_path / "图书馆 A"))
    first = path_utils.get_local_data_path()
    assert first == os.path.join(path_utils._local_data_root(), path_utils._install_key(program))
    # The library moved (the installer wrote another folder): window state, logs and locks stay where they were.
    monkeypatch.setattr(path_utils, "_LIBRARY", {})
    _library_note(program, str(tmp_path / "ライブラリ B"))
    assert path_utils.get_user_data_path() == str(tmp_path / "ライブラリ B")
    assert path_utils.get_local_data_path() == first


def test_without_library_json_the_program_is_portable_and_keeps_the_2x_layout(program, monkeypatch):
    _outside_pytest(monkeypatch)
    assert path_utils.installed_library() is None
    assert path_utils.get_user_data_path() == program
    assert path_utils.get_settings_path() == os.path.join(program, "settings.json")
    assert path_utils.get_local_data_path() == os.path.join(path_utils._local_data_root(),
                                                            path_utils._install_key(program))


def test_a_note_naming_another_programs_folder_leaves_this_one_portable(tmp_path, program):
    # dist\Surasura, a test build: the installed copy's note never makes them read the real library.
    _library_note(str(tmp_path / "Programs" / "Surasura"), str(tmp_path / "ドキュメント" / "Surasura"))
    assert path_utils.installed_library() is None
    assert path_utils.get_user_data_path() == program


@pytest.mark.parametrize("content", [
    {"version": 1, "install": "PROGRAM", "library": "ドキュメント/すらすら"},   # relative library
    {"version": 1, "install": "PROGRAM", "library": ""},
    {"version": 1, "install": "PROGRAM", "library": "   "},
    {"version": 1, "install": "PROGRAM", "library": 5},
    {"version": 1, "install": "PROGRAM", "libary": "C:/すらすら"},             # another key
    {"version": 1, "library": "LIBRARY"},                                      # no install
    {"version": 1, "install": "Programs/すらすら", "library": "LIBRARY"},      # relative install
    ["PROGRAM", "LIBRARY"],                                                    # another shape
    b'{"version": 1, "install": "C:/\xe3\x81\x99',                             # cut off mid-write
    b"\xff\xfe\x00{",                                                          # not UTF-8
])
def test_a_library_json_without_a_usable_install_and_library_leaves_the_program_portable(tmp_path, program,
                                                                                          content):
    if not isinstance(content, bytes):
        content = json.loads(json.dumps(content).replace("PROGRAM", program.replace("\\", "/"))
                             .replace("LIBRARY", str(tmp_path / "lib").replace("\\", "/")))
    _write_note(content)
    assert path_utils.installed_library() is None
    assert path_utils.get_user_data_path() == program
    assert path_utils.get_settings_path() == os.path.join(program, "settings.json")


def test_a_library_json_the_installer_wrote_with_a_bom_is_read(tmp_path, program):
    library = str(tmp_path / "すらすら")
    _write_note(b"\xef\xbb\xbf" + json.dumps({"version": 1, "install": program, "library": library}).encode("utf-8"))
    assert path_utils.get_user_data_path() == library


def test_a_source_run_never_reads_library_json(tmp_path, program, monkeypatch):
    _library_note(program, str(tmp_path / "すらすら"))
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    assert path_utils.installed_library() is None
    assert path_utils.get_user_data_path() == PROJECT
    assert path_utils.get_settings_path() == os.path.join(PROJECT, "settings.json")


def test_a_test_root_wins_over_an_installed_layout(tmp_path, program, monkeypatch):
    _library_note(program, str(tmp_path / "すらすら"))
    root = tmp_path / "test_root"
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))
    assert path_utils.installed_library() is None
    assert path_utils.get_user_data_path() == str(root)
    assert path_utils.get_settings_path() == os.path.join(str(root), "settings.json")
    assert path_utils.get_local_data_path() == os.path.join(str(root), "local")


def test_under_the_suites_own_test_root_settings_stay_in_the_root():
    # The ~80 tests that write <test root>/settings.json keep working unchanged.
    assert path_utils.get_settings_path() == os.path.join(os.environ["SURASURA_TEST_ROOT"], "settings.json")


def test_settings_are_saved_and_read_in_the_roaming_root_when_installed(tmp_path, program, monkeypatch):
    from app import settings_manager
    _outside_pytest(monkeypatch)
    library = tmp_path / "图书馆"
    _library_note(program, str(library))
    assert settings_manager.save_keys({"language": "zh"}) is not False
    saved = os.path.join(path_utils._roaming_base(), "Houseki", "Surasura", "settings.json")
    with open(saved, encoding="utf-8") as f:
        assert json.load(f)["language"] == "zh"
    assert settings_manager.load_settings()["language"] == "zh"
    for elsewhere in (library / "settings.json", os.path.join(program, "settings.json"),
                      os.path.join(path_utils._local_data_root(), "settings.json")):
        assert not os.path.exists(elsewhere)


# --- the build's data name ------------------------------------------------------------------------------------------

def _stamp(program, content):
    with open(os.path.join(program, "_internal", path_utils.BUILD_STAMP), "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False)


def test_a_test_builds_data_name_gives_it_roots_of_its_own(tmp_path, program, monkeypatch):
    _outside_pytest(monkeypatch)
    _stamp(program, {"version": "3.0.0", "build_id": "t1", "data_name": "Surasura-test"})
    assert path_utils.data_name() == "Surasura-test"
    assert path_utils.local_data_root() == os.path.join(path_utils._local_base(), "Houseki", "Surasura-test")
    assert path_utils.get_persistent_user_data_path() == os.path.join(path_utils._roaming_base(), "Houseki",
                                                                      "Surasura-test")
    # Its own library.json: the real install's note, in Houseki\Surasura, is never read.
    real = os.path.join(path_utils._local_base(), "Houseki", "Surasura")
    os.makedirs(real)
    with open(os.path.join(real, path_utils.LIBRARY_NOTE), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "install": program, "library": str(tmp_path / "本物")}, f, ensure_ascii=False)
    assert path_utils.installed_library() is None
    _library_note(program, str(tmp_path / "テスト"))
    monkeypatch.setattr(path_utils, "_LIBRARY", {})
    assert path_utils.get_user_data_path() == str(tmp_path / "テスト")
    assert path_utils.get_settings_path().endswith(os.path.join("Houseki", "Surasura-test", "settings.json"))
    # Legacy roots and Torii's place never carry it.
    assert path_utils.legacy_local_root().endswith(os.path.join("SonicSandbox", "Surasura"))
    assert path_utils.tools_root() == os.path.join(path_utils._local_base(), "Houseki", "tools")


@pytest.mark.parametrize("stamp", [None, {}, {"data_name": ""}, {"data_name": ".."}, {"data_name": "a/b"},
                                   {"data_name": "a\\b"}, {"data_name": "C:"}, {"data_name": 5},
                                   {"data_name": "Surasura."}, ["Surasura-test"]])
def test_no_stamp_or_a_data_name_that_is_not_one_plain_folder_name_is_surasura(program, stamp):
    if stamp is not None:
        _stamp(program, stamp)
    assert path_utils.data_name() == "Surasura"


def test_a_source_run_is_always_surasura(program, monkeypatch):
    _stamp(program, {"data_name": "Surasura-test"})
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    assert path_utils.data_name() == "Surasura"


# --- an installed library that isn't there --------------------------------------------------------------------------

def test_a_missing_library_folder_is_never_created_nor_an_empty_library_made(tmp_path, program, monkeypatch):
    _outside_pytest(monkeypatch)
    library = tmp_path / "NAS" / "すらすら"            # offline
    _library_note(program, str(library))
    assert path_utils.library_available() is False
    assert path_utils.ensure_data_setup("ja") is False
    assert path_utils.copy_default_lists("ja") == []
    assert not os.path.exists(library) and not os.path.exists(library.parent)
    library.mkdir(parents=True)                         # back online
    assert path_utils.library_available() is True
    assert path_utils.ensure_data_setup("ja") is True
    assert os.path.isdir(library / "User Files" / "ja") and os.path.isdir(library / "data" / "ja" / "HighPriority")


# A command line run as an installed program: path_utils reads the installed layout (the rest of the app is source).
_INSTALLED_CLI = r"""
import os, sys
from app import path_utils
program, call = sys.argv[1], sys.argv[2:]
path_utils.is_frozen = lambda: True
sys.executable = os.path.join(program, "surasura-cli.exe")
sys._MEIPASS = os.path.join(program, "_internal")
from app.cli import __main__ as cli
sys.exit(cli.main(call))
"""


def test_the_command_lines_version_never_makes_a_missing_library(tmp_path, program, bases):
    # `surasura-cli --version` imports the analyzer, whose import made <library>\results: on a first start, before the
    # window's write check (D12), it made the library folder; on a NAS offline, an empty one (D3).
    library = tmp_path / "NAS" / "すらすら 图书馆"
    _library_note(program, str(library))
    env = dict(os.environ, LOCALAPPDATA=bases["local"], APPDATA=bases["roaming"], XDG_DATA_HOME=bases["local"],
               PYTHONPATH=PROJECT, PYTHONIOENCODING="utf-8")
    for name in ("SURASURA_TEST_ROOT", "PYTEST_CURRENT_TEST"):          # as the installed program runs
        env.pop(name, None)

    def version():
        out = subprocess.run([PYTHON, "-c", _INSTALLED_CLI, program, "--version"], cwd=str(tmp_path),
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
        line = json.loads(out.stdout.decode("ascii").splitlines()[-1])
        assert line["type"] == "result" and line["engine"]

    version()
    assert not os.path.exists(library.parent), "the command line made the missing library"
    library.mkdir(parents=True)                         # back online: the import makes results\ as before
    version()
    assert os.listdir(library) == ["results"]


def test_a_generate_makes_results_itself_before_writing(tmp_path, monkeypatch, ja_resources_dir):
    # The import makes results\ only where the library is there, so a run makes it before it writes: a window that
    # imported the analyzer before its first-run page made the library, then generates.
    import shutil
    from app import analyzer
    data = tmp_path / "data" / "ja"
    for bucket in ("HighPriority", "LowPriority", "GoalContent"):
        (data / bucket).mkdir(parents=True)
    shutil.copy(os.path.join(ja_resources_dir, "context_test.txt"), str(data / "HighPriority" / "冒険.txt"))
    user_files = tmp_path / "User Files" / "ja"
    user_files.mkdir(parents=True)
    (user_files / "KnownWord.json").write_text("{}", encoding="utf-8")
    results = tmp_path / "results"                      # not there
    monkeypatch.setattr(analyzer, "get_data_path", lambda lang=None: str(data))
    monkeypatch.setattr(analyzer, "get_user_files_path", lambda lang=None: str(user_files))
    monkeypatch.setattr(analyzer, "RESULTS_DIR", str(results))
    for name, file in (("OUTPUT_CSV", "priority_learning_list.csv"), ("OUTPUT_STATS", "file_statistics.txt"),
                       ("OUTPUT_PROGRESSIVE", "progressive_learning_list.csv")):
        monkeypatch.setattr(analyzer, name, str(results / file))
    monkeypatch.setattr(sys, "argv", ["analyzer.py", "--language", "ja", "--min-freq", "1", "--context-min", "0",
                                      "--target-coverage", "100"])
    analyzer.main()
    with open(results / "priority_learning_list.csv", encoding="utf-8-sig") as f:
        assert "冒険" in f.read()


def test_a_generate_on_a_missing_installed_library_runs_nothing_and_makes_nothing(tmp_path, monkeypatch):
    # An installed library folder that isn't there (a drive unplugged, a folder renamed): a run makes no empty library
    # in its place (one would pass for the real library from then on, D3) and says why in its exit code.
    from app import analyzer
    library = tmp_path / "Documents" / "すらすら図書館"            # not there
    monkeypatch.setattr(analyzer, "library_available", lambda: False)
    monkeypatch.setattr(analyzer, "RESULTS_DIR", str(library / "results"))
    monkeypatch.setattr(sys, "argv", ["analyzer.py", "--language", "ja", "--min-freq", "1"])
    assert analyzer.main() == analyzer.LIBRARY_MISSING
    assert not os.path.exists(library) and not os.path.exists(library.parent)


def test_portable_source_and_test_root_libraries_are_always_available(program, monkeypatch):
    assert path_utils.library_available() is True                  # portable
    monkeypatch.setattr(path_utils, "is_frozen", lambda: False)
    assert path_utils.library_available() is True                  # source


# --- the Houseki roots, the legacy roots, tools ---------------------------------------------------------------------

@pytest.mark.skipif(not WINDOWS, reason="%LOCALAPPDATA% / %APPDATA% are Windows'")
def test_windows_roots_move_under_houseki_and_the_legacy_ones_stay_sonicsandbox(monkeypatch, bases):
    _outside_pytest(monkeypatch)
    assert path_utils.local_data_root() == os.path.join(bases["local"], "Houseki", "Surasura")
    assert path_utils.get_persistent_user_data_path() == os.path.join(bases["roaming"], "Houseki", "Surasura")
    assert path_utils.legacy_local_root() == os.path.join(bases["local"], "SonicSandbox", "Surasura")
    assert path_utils.legacy_persistent_root() == os.path.join(bases["roaming"], "SonicSandbox", "Surasura")
    assert path_utils.tools_root() == os.path.join(bases["local"], "Houseki", "tools")


def test_macos_and_linux_roots(tmp_path, monkeypatch, bases):
    _outside_pytest(monkeypatch)
    home = str(tmp_path / "home")
    monkeypatch.setattr(sys, "platform", "darwin")
    support = os.path.join(home, "Library", "Application Support")
    assert path_utils.local_data_root() == os.path.join(support, "Houseki", "Surasura")
    assert path_utils.legacy_local_root() == os.path.join(support, "SonicSandbox", "Surasura")
    assert path_utils.tools_root() == os.path.join(support, "Houseki", "tools")
    # The persistent root keeps 2.x's rule on macOS too ($XDG_DATA_HOME, else ~/.local/share).
    assert path_utils.legacy_persistent_root() == os.path.join(bases["local"], "SonicSandbox", "Surasura")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME")
    share = os.path.join(home, ".local", "share")
    assert path_utils.local_data_root() == os.path.join(share, "Houseki", "Surasura")
    assert path_utils.get_persistent_user_data_path() == os.path.join(share, "Houseki", "Surasura")
    assert path_utils.legacy_local_root() == os.path.join(share, "SonicSandbox", "Surasura")
    assert path_utils.legacy_persistent_root() == os.path.join(share, "SonicSandbox", "Surasura")


def test_the_legacy_roots_and_tools_are_named_only_never_created(monkeypatch, bases):
    _outside_pytest(monkeypatch)
    for path in (path_utils.legacy_local_root(), path_utils.legacy_persistent_root(), path_utils.tools_root()):
        assert not os.path.exists(path)


def test_the_legacy_roots_move_into_a_test_root_and_a_test_without_one_is_refused(monkeypatch):
    root = os.environ["SURASURA_TEST_ROOT"]
    assert path_utils.legacy_local_root() == os.path.join(root, "legacy_local_root")
    assert path_utils.legacy_persistent_root() == os.path.join(root, "legacy_persistent_root")
    monkeypatch.delenv("SURASURA_TEST_ROOT")
    for reach in (path_utils.legacy_local_root, path_utils.legacy_persistent_root):
        with pytest.raises(RuntimeError, match="SURASURA_TEST_ROOT"):
            reach()


def test_the_install_note_is_written_in_the_houseki_root(tmp_path, program, monkeypatch):
    _outside_pytest(monkeypatch)
    library = tmp_path / "すらすら"
    (library / "User Files" / "ja").mkdir(parents=True)
    _library_note(program, str(library))
    assert path_utils.write_install_note() is True
    with open(os.path.join(path_utils._local_data_root(), path_utils.INSTALLS_NOTE), encoding="utf-8") as f:
        [entry] = json.load(f)
    assert entry["data_root"] == str(library) and entry["languages"] == ["ja"]
    assert not os.path.exists(os.path.join(path_utils._local_base(), "SonicSandbox"))


# --- the anki-writer lock, in both roots ------------------------------------------------------------------------------

# A child (a 2.x, or another 3.0) holding the OS lock on one lock file until its stdin closes.
_HOLDER = r"""
import sys
from app import path_utils
handle = path_utils.try_lock(sys.argv[1])
print("held" if handle is not None else "busy", flush=True)
sys.stdin.readline()
path_utils.release_lock(handle)
"""


def _hold(path):
    process = subprocess.Popen([sys.executable, "-c", _HOLDER, path], cwd=PROJECT, env=dict(os.environ),
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    return process, process.stdout.readline().strip()


def _let_go(process):
    process.stdin.close()
    process.wait(timeout=10)


def _lock_files():
    return [os.path.join(where, "anki-writer.lock") for where in locks.folders("anki-writer")]


def test_the_anki_writer_lock_is_taken_in_both_roots_and_released_in_both():
    houseki, legacy = _lock_files()
    assert os.path.commonpath([houseki, path_utils.local_data_root()]) == path_utils.local_data_root()
    assert os.path.commonpath([legacy, path_utils.legacy_local_root()]) == path_utils.legacy_local_root()
    with locks.take("anki-writer", "順 reorder"):
        for path in (houseki, legacy):
            process, first = _hold(path)
            _let_go(process)
            assert first == "busy", path
        # Each root says who holds it: a 2.x waiting on its own root can name this holder.
        for where in locks.folders("anki-writer"):
            with open(os.path.join(where, "anki-writer.holder.json"), encoding="utf-8") as f:
                assert json.load(f)["verb"] == "順 reorder"
    for path in (houseki, legacy):
        process, first = _hold(path)
        _let_go(process)
        assert first == "held", path
    assert not any(os.path.exists(os.path.join(where, "anki-writer.holder.json"))
                   for where in locks.folders("anki-writer"))


@pytest.mark.parametrize("which", ["houseki", "legacy"])
def test_a_holder_in_either_root_blocks_the_take(which):
    houseki, legacy = _lock_files()
    process, first = _hold(houseki if which == "houseki" else legacy)
    try:
        assert first == "held"
        with pytest.raises(locks.Busy):
            locks.take("anki-writer", "Backfill", wait=0.3)
        assert locks.in_use("anki-writer")
        assert locks.held_in_process("anki-writer") is None
        if which == "legacy":
            # The Houseki lock it got first was let go at once: another 3.0 can look at it freely.
            other, got = _hold(houseki)
            _let_go(other)
            assert got == "held"
    finally:
        _let_go(process)
    with locks.take("anki-writer", "Backfill"):        # free again once the holder is gone
        pass
    assert not locks.in_use("anki-writer")


def _spy_handles(monkeypatch):
    """Every OS lock taken (try_lock's open files) and every one let go, in this process."""
    taken, released = [], []
    real_try, real_release = path_utils.try_lock, path_utils.release_lock

    def try_lock(path):
        handle = real_try(path)
        if handle is not None:
            taken.append(handle)
        return handle

    def release_lock(handle):
        released.append(handle)
        real_release(handle)

    monkeypatch.setattr(path_utils, "try_lock", try_lock)
    monkeypatch.setattr(path_utils, "release_lock", release_lock)
    return taken, released


def test_a_take_refused_by_the_legacy_root_lets_the_houseki_lock_go_explicitly(monkeypatch):
    # Not left to the garbage collector: the Houseki lock is let go the moment the second look fails.
    process, first = _hold(_lock_files()[1])
    try:
        assert first == "held"
        taken, released = _spy_handles(monkeypatch)
        with pytest.raises(locks.Busy):
            locks.take("anki-writer", "Backfill")
        assert len(taken) == 1 and released == taken
    finally:
        _let_go(process)


def test_a_release_lets_both_locks_go_newest_first(monkeypatch):
    taken, released = _spy_handles(monkeypatch)
    locks.take("anki-writer", "順 reorder").release()
    assert len(taken) == 2 and released == taken[::-1]


def test_a_2x_holder_record_in_the_legacy_root_is_read():
    legacy = locks.folders("anki-writer")[1]
    os.makedirs(legacy, exist_ok=True)
    record = {"program": "Surasura.exe", "pid": 4242, "started": "2026-10-12T09:00:00", "verb": "順 reorder (2.x)"}
    with open(os.path.join(legacy, "anki-writer.holder.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
    assert locks.read_holder("anki-writer") == record


def test_an_unopenable_legacy_lock_file_is_named(monkeypatch):
    locks.take("anki-writer", "順 reorder").release()      # both folders made
    legacy = _lock_files()[1]
    real_open = open

    def refuse(path, *args, **kwargs):
        if path == legacy:
            raise PermissionError("[WinError 5] Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", refuse)
    assert locks.unopenable("anki-writer") == legacy


def test_a_per_install_lock_stays_in_one_folder():
    assert locks.folders("results") == [os.path.join(path_utils.get_local_data_path(), "locks")]


# --- ensure_data_setup -------------------------------------------------------------------------------------------------

def _user_files(language):
    return path_utils.get_user_files_path(language)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_setup_no_longer_makes_a_graduated_list(language):
    path_utils.ensure_data_setup(language)
    names = os.listdir(_user_files(language))
    assert "GraduatedList.txt" not in names
    assert {"Blacklist.txt", "IgnoreList.txt"} <= set(names)


def test_setup_leaves_an_existing_graduated_list_alone(ja_resources_dir):
    folder = _user_files("ja")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "GraduatedList.txt")
    raw = "# Words from graduated content (automatically added)\n\n# Source: 冒険.txt (2 words graduated)\n冒険\n準備\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    path_utils.ensure_data_setup("ja")
    with open(path, encoding="utf-8") as f:
        assert f.read() == raw            # the merge (graduated_merge) retires it, never the setup


def _defaults(language, files):
    folder = os.path.join(path_utils.get_base_path(), "defaults", language)
    os.makedirs(folder, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)
    return folder


def test_setup_copies_each_missing_default_list_and_never_one_that_is_there():
    _defaults("ja", {"frequency_list_ja_global50k.csv": "Term,Rank\n冒険,1520\n準備,840\n",
                     "IgnoreList.txt": "# Add words to ignore here (one per line)\n為る\n"})
    _defaults("zh", {"frequency_list_zh.csv": "Term,Rank\n冒险,2210\n挑战,980\n"})
    mine = os.path.join(_user_files("ja"), "frequency_list_ja_global50k.csv")
    os.makedirs(os.path.dirname(mine), exist_ok=True)
    with open(mine, "w", encoding="utf-8") as f:
        f.write("Term,Rank\n危険,1\n")             # the user's own edit
    path_utils.ensure_data_setup("ja")
    path_utils.ensure_data_setup("zh")
    with open(mine, encoding="utf-8") as f:
        assert f.read() == "Term,Rank\n危険,1\n"
    with open(os.path.join(_user_files("ja"), "IgnoreList.txt"), encoding="utf-8") as f:
        assert "為る" in f.read()                   # the bundled list, copied before an empty one is made
    with open(os.path.join(_user_files("zh"), "frequency_list_zh.csv"), encoding="utf-8") as f:
        assert "冒险" in f.read()
    assert not os.path.exists(os.path.join(_user_files("zh"), "frequency_list_ja_global50k.csv"))
    assert not [n for n in os.listdir(_user_files("ja")) if n.endswith(".tmp")]


def test_setup_copies_a_default_again_only_once_it_is_missing():
    _defaults("ja", {"frequency_list_ja_global50k.csv": "Term,Rank\n冒険,1520\n"})
    assert path_utils.copy_default_lists("ja") == ["frequency_list_ja_global50k.csv"]
    assert path_utils.copy_default_lists("ja") == []


def test_setup_without_a_defaults_folder_copies_nothing():
    assert not os.path.isdir(os.path.join(path_utils.get_base_path(), "defaults"))
    path_utils.ensure_data_setup("ja")
    assert sorted(os.listdir(_user_files("ja"))) == ["Blacklist.txt", "IgnoreList.txt"]
