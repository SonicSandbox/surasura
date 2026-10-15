"""W3.5 part 3 — the start gate's decisions (`app/services/first_run.py`; S3.1 D3, D11, D12, D13).

What a wrong answer would cost, in order:
  * an installed library that is offline (a NAS, OneDrive, a drive unplugged) made again, empty, in its place (D3) — the
    window would then show the learner an empty library and the store would start over;
  * a half-copied import used as a library (D11), or an import over a library in use;
  * the user's known words written twice or damaged by the GraduatedList merge run at every start (Q4-10);
  * a developer's source tree imported into, or a 2.x user never offered their library;
  * Controlled Folder Access refusing the library with no word of how to allow Surasura (D12).

Every root is a temp folder: USERPROFILE, APPDATA, LOCALAPPDATA and XDG_DATA_HOME point into tmp_path, the test root
(conftest) is the library, 2.x's own folders are `<root>/legacy_local_root` and `<root>/legacy_persistent_root`. An
installed program is `path_utils.installed_library()` answering a library folder (a frozen program reading its
library.json: the one switch the layout reads). The 2.x install is `test_import_2x`'s: real Japanese and Chinese
content, known words and GraduatedLists from tests/Test Resources/."""
import json
import os
import time

import pytest

from app import import_2x, path_utils
from app.services import first_run
from tests.test_import_2x import GRADUATED, _old_install, _sha, _tree, _write


def _root():
    return os.environ["SURASURA_TEST_ROOT"]


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    """No test reaches the real profile: Inno's folders follow USERPROFILE, path_utils' the AppData variables."""
    for name, sub in (("USERPROFILE", "profile"), ("APPDATA", "Roaming"), ("LOCALAPPDATA", "Local"),
                      ("XDG_DATA_HOME", "Roaming")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    return tmp_path


def _installed(monkeypatch, library):
    monkeypatch.setattr(path_utils, "installed_library", lambda: library)
    return library


def _known(library, language):
    return os.path.join(library, "User Files", language, "KnownWord.json")


# --- a 2.x install brought over, then every later start ------------------------------------------------------------

def test_a_2x_install_named_by_its_note_is_brought_over_and_the_next_start_runs_only_the_merge(tmp_path, monkeypatch):
    old = _old_install(tmp_path)
    library = _installed(monkeypatch, _root())
    before = _tree(old)

    st = first_run.state()
    assert st["state"] == first_run.IMPORT and st["source"] == old and first_run.needs_run(st)
    stages = []
    result = first_run.run(st, progress=lambda stage, done, total: stages.append(stage))

    assert result["status"] == "done", result
    assert result["import"]["status"] == "done" and {"files", "settings", "store", "roaming", "graduated"} <= set(stages)
    assert import_2x.read_import_note()["complete"] is True
    assert _tree(old) == before, "the old folder is only read"
    for lang in ("ja", "zh"):
        with open(_known(library, lang), encoding="utf-8") as f:
            words = {w["dictForm"]: w for w in json.load(f)["words"]}
        assert all(words[w]["knownStatus"] == "KNOWN" for w in GRADUATED[lang])
    # the telemetry id carried over (S3.1-4: the same user)
    with open(os.path.join(path_utils.get_persistent_user_data_path(), "telemetry_id.json"), encoding="utf-8") as f:
        assert json.load(f)["uid"] == "2x-user-uid"

    # A second start: ready, nothing for the gate to do; the merge, run anyway, changes nothing byte for byte.
    known = {lang: _sha(_known(library, lang)) for lang in ("ja", "zh")}
    again = first_run.state()
    assert again["state"] == first_run.READY and not first_run.needs_run(again)
    second = first_run.run(again)
    assert second["status"] == "done" and second["import"] is None
    assert all(c["added"] == c["raised"] == 0 and c["error"] is None for c in second["graduated"].values())
    assert {lang: _sha(_known(library, lang)) for lang in ("ja", "zh")} == known


def test_a_graduated_list_written_again_is_merged_once_at_the_next_start(tmp_path, monkeypatch):
    # The Tk Graduate can still write the list (row 3.1.6's open point): the start merges it, once.
    old = _old_install(tmp_path, store=False, languages=("ja",))
    library = _installed(monkeypatch, _root())
    assert first_run.run(first_run.state())["status"] == "done"
    _write(os.path.join(library, "User Files", "ja", "GraduatedList.txt"), "# graduated\n旅行\n")

    st = first_run.state()
    assert st["state"] == first_run.READY and st["lists"] == ["ja"] and first_run.needs_run(st)
    merged = first_run.run(st)["graduated"]["ja"]
    assert merged["added"] == 1 and merged["retired"]
    after = _sha(_known(library, "ja"))
    st = first_run.state()
    assert not first_run.needs_run(st)
    assert first_run.run(st)["graduated"]["ja"]["added"] == 0 and _sha(_known(library, "ja")) == after


# --- refusals ------------------------------------------------------------------------------------------------------

def test_a_cancelled_import_is_refused_until_try_again_resumes_it(tmp_path, monkeypatch):
    old = _old_install(tmp_path)
    library = _installed(monkeypatch, _root())
    files = []
    cancelled = first_run.run(first_run.state(), progress=lambda s, d, t: files.append(d) if s == "files" else None,
                              cancel=lambda: len(files) >= 4)
    assert cancelled["status"] == "cancelled" and cancelled["import"]["counts"]["copied"] == 4

    # Never used half (D11): the next start is refused — not ready, even though the folder now holds content.
    st = first_run.state()
    assert st["state"] == first_run.IMPORT_UNFINISHED and st["source"] == old and first_run.needs_run(st)
    assert not os.path.exists(path_utils.get_settings_path())

    resumed = first_run.run(st)                   # Try again
    assert resumed["status"] == "done" and resumed["import"]["resumed"] is True
    assert resumed["import"]["counts"]["kept"] == 4
    assert first_run.state()["state"] == first_run.READY
    assert os.path.isfile(_known(library, "ja"))


def test_a_library_that_was_there_and_is_missing_is_refused_and_nothing_is_made(tmp_path, monkeypatch):
    nas = tmp_path / "NAS 共有" / "Surasura"
    library = _installed(monkeypatch, str(nas))
    os.makedirs(library)
    assert first_run.run(first_run.state())["status"] == "done"          # its first start: seen there, recorded
    os.rmdir(library)
    os.rmdir(os.path.dirname(library))                                   # the share went offline

    st = first_run.state()
    assert st["state"] == first_run.LIBRARY_MISSING and first_run.needs_run(st)
    result = first_run.run(st)
    assert result["status"] == "refused" and result["reason"] == "library_missing"
    assert not os.path.exists(os.path.dirname(library)), "never made again, not even its parent (D3)"
    assert not path_utils.library_available()


def test_a_library_an_import_went_into_is_known_even_without_the_gates_note(tmp_path, monkeypatch):
    # A library brought over by `python -m app.import_2x` (no gate ran): the import's note names it.
    old = _old_install(tmp_path, store=False, languages=("zh",))
    library = str(tmp_path / "ライブラリ")
    assert import_2x.run_import(old, library)["status"] == "done"
    _installed(monkeypatch, library)
    os.rename(library, library + " (offline)")
    assert first_run.state()["state"] == first_run.LIBRARY_MISSING
    assert not os.path.exists(library)


def test_a_new_installs_library_is_made_after_the_write_check(tmp_path, monkeypatch):
    library = _installed(monkeypatch, str(tmp_path / "Documents" / "Surasura"))
    st = first_run.state()
    assert st["state"] == first_run.READY and st["create"] and first_run.needs_run(st)
    assert first_run.run(st)["status"] == "done"
    assert os.path.isdir(library) and os.listdir(library) == []
    st = first_run.state()
    assert st["state"] == first_run.READY and not st["create"] and not first_run.needs_run(st)


def test_folder_access_denied_says_how_to_allow_surasura_and_leaves_no_folder(tmp_path, monkeypatch):
    def denied(path):
        raise PermissionError(13, "Access is denied", path)

    monkeypatch.setattr(import_2x, "_write_probe", denied)
    library = _installed(monkeypatch, str(tmp_path / "Documents" / "Surasura"))
    result = first_run.run(first_run.state())
    assert result["status"] == "blocked" and result["reason"] == "access_denied"
    assert result["message"] == import_2x.CFA_MESSAGE.format(folder=library, exe="Surasura.exe")
    assert not os.path.exists(os.path.dirname(library))
    assert first_run.read_note()["libraries"] == {}, "a refused library is not recorded as seen"

    old = _old_install(tmp_path / "old", store=False, languages=("ja",))   # the same for an import
    st = first_run.state()
    assert st["state"] == first_run.IMPORT and st["source"] == old
    result = first_run.run(st)
    assert result["status"] == "blocked" and "Controlled folder access" in result["message"]
    assert import_2x.read_import_note() is None


# --- who is asked, who is never imported into ----------------------------------------------------------------------

def test_2x_used_here_with_no_note_asks_for_the_old_folder_and_brings_the_chosen_one(tmp_path, monkeypatch):
    old = _old_install(tmp_path, store=False, note=False)               # 2.4: no installs.json
    _installed(monkeypatch, _root())
    st = first_run.state()
    assert st["state"] == first_run.ASK_FOLDER and st["installs"] == []
    assert import_2x.check_source(old)["ok"]
    result = first_run.run(st, source=old)
    assert result["status"] == "done" and result["import"]["from"] == old
    assert first_run.state()["state"] == first_run.READY


def test_start_fresh_is_remembered_and_never_asked_again(tmp_path, monkeypatch):
    _old_install(tmp_path, store=False, note=False)
    library = _installed(monkeypatch, str(tmp_path / "Documents" / "Surasura"))
    st = first_run.state()
    assert st["state"] == first_run.ASK_FOLDER and st["create"]
    result = first_run.run(st, fresh=True)
    assert result["status"] == "done" and result["import"] is None
    assert os.path.isdir(library) and os.listdir(library) == [], "nothing brought over"
    assert first_run.read_note()["libraries"][first_run._key(library)]["fresh"] is True
    st = first_run.state()
    assert st["state"] == first_run.READY and not first_run.needs_run(st)


def test_a_new_user_who_never_ran_2x_is_never_asked(monkeypatch):
    _installed(monkeypatch, _root())
    assert not os.path.exists(path_utils.legacy_persistent_root())
    assert first_run.state()["state"] == first_run.READY


def test_a_library_in_use_or_already_brought_over_is_never_imported_into(tmp_path, monkeypatch):
    old = _old_install(tmp_path / "old", store=False, languages=("ja",))
    library = _installed(monkeypatch, _root())
    _write(_known(library, "ja"), json.dumps({"words": [{"dictForm": "冒険", "knownStatus": "KNOWN"}]},
                                             ensure_ascii=False))
    assert first_run.state()["state"] == first_run.READY, "a library holding content (D11)"
    os.remove(_known(library, "ja"))
    other = str(tmp_path / "earlier library")
    assert import_2x.run_import(old, other)["status"] == "done"
    assert first_run.state()["state"] == first_run.READY, "brought over once already, into another library"


def test_a_source_run_imports_nothing_unless_the_note_names_its_own_tree_as_unfinished(tmp_path):
    old = _old_install(tmp_path, store=False, languages=("ja",))
    assert path_utils.installed_library() is None                        # a developer's tree, a test root
    st = first_run.state()
    assert st["state"] == first_run.READY and not st["installed"] and st["installs"] == []
    files = []
    import_2x.run_import(old, path_utils.get_user_data_path(), progress=lambda s, d, t: files.append(d),
                         cancel=lambda: len(files) >= 1)
    st = first_run.state()
    assert st["state"] == first_run.IMPORT_UNFINISHED
    assert first_run.run(st)["status"] == "done"
    assert first_run.state()["state"] == first_run.READY


def test_an_unfinished_import_into_another_folder_does_not_hold_this_library(tmp_path, monkeypatch):
    old = _old_install(tmp_path, store=False, languages=("ja",))
    files = []
    import_2x.run_import(old, str(tmp_path / "elsewhere"), progress=lambda s, d, t: files.append(d),
                         cancel=lambda: len(files) >= 1)
    _installed(monkeypatch, _root())
    assert first_run.state()["state"] == first_run.IMPORT


def test_an_unreadable_gate_note_counts_as_none(monkeypatch):
    _write(first_run.note_path(), "{ not json")
    assert first_run.read_note() == {"version": first_run.NOTE_VERSION, "libraries": {}}
    library = _installed(monkeypatch, _root())
    assert first_run.record(library)
    assert first_run._key(library) in first_run.read_note()["libraries"]


def test_an_everyday_start_decides_in_well_under_a_frame(tmp_path, monkeypatch):
    # The gate asks on the window's thread before the first paint: file checks only (measured ~0.2 ms here).
    old = _old_install(tmp_path, store=False)
    _installed(monkeypatch, _root())
    assert first_run.run(first_run.state())["status"] == "done"
    best = min(_timed(first_run.state) for _ in range(5))
    assert best < 0.05, best


def _timed(fn):
    t0 = time.perf_counter()
    st = fn()
    assert not first_run.needs_run(st)
    return time.perf_counter() - t0
