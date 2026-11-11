"""3.0.1 — Windows Defender's Controlled folder access (`app/cfa.py`; Mattias 2026-11-10: surasura-cli blocked writing
%USERPROFILE%\\Documents\\Surasura\\results).

What a wrong answer would cost: a refusal taken for CFA's when Defender's switch is off or audit-only, or when the
folder isn't a protected one (the learner sent to Windows Security for nothing — "never guess from the error alone");
a real CFA refusal shown as a crash or a bare "Access is denied"; a write check that leaves a file behind or writes
when nothing is at risk. Every registry read goes through `cfa._read` / `cfa._names` (a fake registry here: no test
reads or writes Defender's real settings) and `cfa._windows` (so these run on Linux CI too); a refusal is a fake
PermissionError from `cfa._write_check`. Folders are temp folders with real Japanese names."""
import os

import pytest

from app import cfa


def fake_registry(monkeypatch, switch=None, policy=None, documents=None, added=(), policy_added=(), windows=True):
    """Defender's values as a dict the fakes answer from: `switch` (the user's setting), `policy` (a policy's),
    `documents` (this user's Documents), `added` (folders the user protected)."""
    values = {(cfa.KEY, cfa.SWITCH): switch, (cfa.POLICY_KEY, cfa.SWITCH): policy,
              (cfa.USER_FOLDERS, "Personal"): documents}
    names = {cfa.KEY + "\\" + cfa.PROTECTED: list(added), cfa.POLICY_KEY + "\\" + cfa.PROTECTED: list(policy_added)}
    monkeypatch.setattr(cfa, "_windows", lambda: windows)
    monkeypatch.setattr(cfa, "_read", lambda key, name, machine=True: values.get((key, name)))
    monkeypatch.setattr(cfa, "_names", lambda key, machine=True: names.get(key, []))
    return values


def refuse_inside(monkeypatch, folder):
    """Windows' refusal, faked: every write check inside `folder` is access denied (WinError 5's errno 13)."""
    real = cfa._write_check
    top = os.path.normcase(os.path.abspath(folder))

    def check(place):
        if os.path.normcase(os.path.abspath(place)).startswith(top):
            raise PermissionError(13, "Access is denied", os.path.join(place, cfa.PROBE_NAME))
        real(place)
    monkeypatch.setattr(cfa, "_write_check", check)


@pytest.fixture
def documents(tmp_path):
    folder = tmp_path / "ユーザー" / "Documents"
    (folder / "Surasura" / "results").mkdir(parents=True)
    return str(folder)


# --- the switch ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("switch, policy, on", [
    (None, None, False),        # never set: off
    (0, None, False),
    (1, None, True),
    (2, None, False),           # audit: Windows only logs, never refuses
    (3, None, False),           # disks only (block disk modification): no folder refused
    (0, 1, True),               # a policy wins over the user's setting
    (1, 0, False),
])
def test_cfa_is_on_only_when_defenders_own_switch_says_1(monkeypatch, documents, switch, policy, on):
    fake_registry(monkeypatch, switch=switch, policy=policy, documents=documents)
    assert cfa.is_on() is on
    assert cfa.at_risk(os.path.join(documents, "Surasura")) is on


def test_off_windows_nothing_is_read_and_nothing_is_at_risk(monkeypatch, documents):
    fake_registry(monkeypatch, switch=1, documents=documents, windows=False)
    assert cfa.mode() is None and cfa.protected_folders() == []
    assert not cfa.at_risk(os.path.join(documents, "Surasura"))


def test_an_unreadable_switch_is_off(monkeypatch, documents):
    fake_registry(monkeypatch, switch="not a number", documents=documents)
    assert cfa.mode() is None and not cfa.is_on()


# --- the protected folders ---------------------------------------------------------------------------------------

def test_documents_and_an_added_folder_are_protected_and_the_users_own_folder_is_not(monkeypatch, tmp_path, documents):
    added = tmp_path / "動画フォルダ"
    added.mkdir()
    fake_registry(monkeypatch, switch=1, documents=documents, added=[str(added)])
    library = os.path.join(documents, "Surasura")
    assert cfa.protecting(library) == documents
    assert cfa.protecting(os.path.join(library, "results", "reading_list_static.html")) == documents
    assert cfa.protecting(str(added / "日本語")) == str(added)
    assert cfa.protecting(str(tmp_path / "ユーザー" / "Surasura")) is None
    # a sibling whose name only starts the same is not inside it
    assert cfa.protecting(documents + " (old)") is None


def test_a_documents_path_with_a_variable_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("SURASURA_FAKE_PROFILE", str(tmp_path / "ミカエル"))
    fake_registry(monkeypatch, switch=1, documents="%SURASURA_FAKE_PROFILE%" + os.sep + "Documents")
    assert cfa.protecting(str(tmp_path / "ミカエル" / "Documents" / "Surasura")) == \
        os.path.normpath(str(tmp_path / "ミカエル" / "Documents"))


def test_a_policys_protected_folder_counts_too(monkeypatch, tmp_path, documents):
    fake_registry(monkeypatch, switch=1, documents=documents, policy_added=[str(tmp_path / "共有")])
    assert cfa.protecting(str(tmp_path / "共有" / "Surasura")) == str(tmp_path / "共有")


# --- a refusal is CFA's only when everything says so ----------------------------------------------------------------

def test_access_denied_inside_a_protected_folder_with_cfa_on_is_cfas_refusal(monkeypatch, documents):
    fake_registry(monkeypatch, switch=1, documents=documents)
    target = os.path.join(documents, "Surasura", "results", "reading_list_static.html")
    assert cfa.refused(PermissionError(13, "Access is denied", target))
    error = OSError(13, "Access is denied", target)
    error.winerror = 5
    assert cfa.refused(error)


@pytest.mark.parametrize("why", ["cfa off", "audit", "outside", "not denied", "no path"])
def test_never_guessed_from_the_error_alone(monkeypatch, tmp_path, documents, why):
    fake_registry(monkeypatch, switch={"cfa off": 0, "audit": 2}.get(why, 1), documents=documents)
    target = os.path.join(documents, "Surasura", "results", "x.csv")
    error = PermissionError(13, "Access is denied", str(tmp_path / "ユーザー" / "Surasura" / "x.csv")
                            if why == "outside" else target)
    if why == "not denied":
        error = FileNotFoundError(2, "No such file", target)
    if why == "no path":
        error = PermissionError(13, "Access is denied")
    assert not cfa.refused(error)


# --- the write check -----------------------------------------------------------------------------------------------

def test_the_write_check_names_the_refused_folder_and_leaves_nothing_behind(monkeypatch, documents):
    fake_registry(monkeypatch, switch=1, documents=documents)
    library = os.path.join(documents, "Surasura")
    before = sorted(os.listdir(library))
    assert cfa.probe(library) is None, "nothing refused yet: every write went through"
    assert sorted(os.listdir(library)) == before and os.listdir(os.path.join(library, "results")) == []
    refuse_inside(monkeypatch, documents)
    assert cfa.probe(library) == library


def test_a_protected_part_alone_is_found_and_a_missing_part_is_never_made(monkeypatch, tmp_path, documents):
    # A user who protected only the library's results folder: the root's check passes, results' is refused.
    library = tmp_path / "ユーザー" / "Surasura"
    (library / "results").mkdir(parents=True)
    fake_registry(monkeypatch, switch=1, documents=documents, added=[str(library / "results")])
    refuse_inside(monkeypatch, str(library / "results"))
    assert cfa.probe(str(library)) == str(library / "results")
    assert not (library / "User Files").exists() and not (library / "data").exists()


def test_another_error_in_the_write_check_is_not_a_refusal(monkeypatch, documents):
    fake_registry(monkeypatch, switch=1, documents=documents)

    def full(place):
        raise OSError(28, "No space left on device", place)
    monkeypatch.setattr(cfa, "_write_check", full)
    assert cfa.probe(os.path.join(documents, "Surasura")) is None


# --- what it says ----------------------------------------------------------------------------------------------------

def test_the_words_name_the_folder_the_target_and_both_programs(monkeypatch, tmp_path):
    monkeypatch.setattr(cfa.sys, "frozen", True, raising=False)
    monkeypatch.setattr(cfa.sys, "executable", str(tmp_path / "Programs" / "Surasura" / "Surasura.exe"))
    folder = str(tmp_path / "Documents" / "Surasura")
    line = cfa.words(folder, target=str(tmp_path / "Surasura"))
    assert folder in line and str(tmp_path / "Surasura") in line and "Controlled folder access" in line
    said = cfa.cli_words(folder, target=str(tmp_path / "Surasura"))
    for program in ("Surasura.exe", "surasura-cli.exe"):
        assert str(tmp_path / "Programs" / "Surasura" / program) in said
        assert str(tmp_path / "Programs" / "Surasura" / program) in cfa.allow_steps()
    assert "Move my library" in said


def test_a_source_run_names_the_programs_without_a_folder(monkeypatch):
    monkeypatch.delattr(cfa.sys, "frozen", raising=False)
    assert cfa.programs() == ["Surasura.exe", "surasura-cli.exe"]


def test_the_move_target_is_the_users_own_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "ミカエル"))
    monkeypatch.setenv("HOME", str(tmp_path / "ミカエル"))
    assert cfa.move_target() == os.path.join(str(tmp_path / "ミカエル"), "Surasura")


def test_windows_security_opens_on_its_ransomware_page_and_a_failure_never_raises():
    opened = []
    assert cfa.open_settings(opener=opened.append) is True and opened == ["windowsdefender://ransomwareprotection"]

    def broken(_page):
        raise OSError("no handler")
    assert cfa.open_settings(opener=broken) is False


def test_a_library_holding_a_protected_part_is_at_risk_and_its_part_is_checked(monkeypatch, tmp_path, documents):
    library = tmp_path / "ユーザー" / "Surasura"
    (library / "results").mkdir(parents=True)
    fake_registry(monkeypatch, switch=1, documents=documents, added=[str(library / "results")])
    assert cfa.at_risk(str(library)) and not cfa.at_risk(str(tmp_path / "ユーザー" / "Surasura2"))
