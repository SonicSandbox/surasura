"""surasura.json, Surasura's entry in the shared tools folder (app/tools_entry.py; 09-hato-layer §3 v2, RUNBOOK-P3.2
row 3.2.1): its fields, when it is written and when not, the atomic replace and its retries, the 4 KiB limit, how
another tool's entry is read, the pytest guard, and the hooks in the command line and the window.

Every test runs in its own test root (SURASURA_TEST_ROOT) with its own tools folder (HOUSEKI_TOOLS_DIR, or the root's
houseki-tools); the real shared tools folder is never touched. Installs and data roots carry Japanese / Chinese names,
as users' install paths routinely do. A frozen build is faked by `path_utils.is_frozen` and `sys.executable`, an
installed one by `path_utils.installed_library` too (on 3.0 only the installed program advertises itself)."""
import io
import json
import os
import re
import sys
import threading
import time

import pytest

from app import __version__, library_store, path_utils, settings_manager, tools_entry
from app.cli import __main__ as cli
from app.cli import contract


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A data root holding Japanese set up (its User Files/ja), Chinese not."""
    r = tmp_path / "データ根"
    (r / "User Files" / "ja").mkdir(parents=True)
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(r))
    return r


@pytest.fixture
def tools(tmp_path, monkeypatch):
    folder = tmp_path / "tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    return folder


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """A frozen install: Surasura.exe and surasura-cli.exe side by side, the window's exe running, library.json naming
    its library (`installed_library`; settings.json then in the roaming root, under the test root)."""
    install = tmp_path / "スラスラ 安装"
    install.mkdir()
    (install / "Surasura.exe").write_bytes(b"MZ")
    (install / "surasura-cli.exe").write_bytes(b"MZ")
    library = tmp_path / "ライブラリ"
    library.mkdir()
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "installed_library", lambda: str(library))
    monkeypatch.setattr(sys, "executable", str(install / "Surasura.exe"))
    return install


def _write_settings(text):
    """settings.json where the program reads it (`get_settings_path`: an installed one's, in the roaming root)."""
    path = path_utils.get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _file(tools):
    return tools / "surasura.json"


def _load(tools):
    return json.loads(_file(tools).read_text(encoding="utf-8"))


def _hato_folder(root, lang):
    return os.path.normpath(os.path.join(str(root), "data", lang, *library_store.HATO_FOLDER.split("/")))


# --------------------------------------------------------------------------- #
# The entry's fields
# --------------------------------------------------------------------------- #
def test_frozen_entry_names_the_cli_and_app_beside_the_running_exe(root, tools, frozen):
    """Every field, as hato reads them: the command line and window exe in the install's folder, this version and
    contract, `status` only (Connect off), the Japanese drop folder (the only language set up), `updated` in UTC."""
    assert tools_entry.refresh({"connect_enabled": False}) is True
    got = _load(tools)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", got.pop("updated"))
    assert got == {
        "schema": 1, "tool": "surasura", "name": "Surasura", "version": __version__,
        "cli": str(frozen / "surasura-cli.exe"), "app": str(frozen / "Surasura.exe"),
        "contract": contract.CONTRACT, "verbs": ["status"],
        "drop_folders": {"ja": _hato_folder(root, "ja")},
    }
    assert os.path.isabs(got["drop_folders"]["ja"]) and "/" not in got["drop_folders"]["ja"].replace(os.sep, "")


def test_frozen_cli_run_beside_a_missing_window_exe_writes_app_null(root, tools, frozen, monkeypatch):
    """surasura-cli.exe running from a folder without Surasura.exe: `app` is null, `cli` still its own exe."""
    (frozen / "Surasura.exe").unlink()
    monkeypatch.setattr(sys, "executable", str(frozen / "surasura-cli.exe"))
    got = tools_entry.entry({})
    assert got["app"] is None and got["cli"] == str(frozen / "surasura-cli.exe")


def test_frozen_off_windows_names_the_programs_without_exe(root, tools, frozen, monkeypatch):
    """A frozen macOS / Linux build ships `surasura-cli` and `Surasura` (no .exe), as Connect's own start
    (`kick.command`) names them: the entry names those, never a .exe hato would find missing (adversary #2)."""
    (frozen / "Surasura").write_bytes(b"ELF")
    (frozen / "surasura-cli").write_bytes(b"ELF")
    monkeypatch.setattr(sys, "executable", str(frozen / "Surasura"))
    monkeypatch.setattr(sys, "platform", "linux")
    got = tools_entry.entry({})
    assert got["cli"] == str(frozen / "surasura-cli") and got["app"] == str(frozen / "Surasura")


def test_register_is_offered_only_while_connects_preview_is_on(root, tools, frozen):
    """hato registers only when `register` is listed (09-hato-layer v2 Q1): the preview's switch decides it."""
    assert tools_entry.entry({"connect_enabled": True})["verbs"] == ["status", "register"]
    assert tools_entry.entry({"connect_enabled": False})["verbs"] == ["status"]
    assert tools_entry.entry({})["verbs"] == ["status"]


def test_both_languages_set_up_name_both_drop_folders(root, tools, frozen):
    (root / "User Files" / "zh").mkdir()
    assert tools_entry.entry({})["drop_folders"] == {"ja": _hato_folder(root, "ja"), "zh": _hato_folder(root, "zh")}


def test_no_language_set_up_gives_empty_drop_folders(root, tools, frozen):
    """No User Files/<lang>: no hand-off for any language — `{}`, never a folder hato would drop into unread."""
    (root / "User Files" / "ja").rmdir()
    assert tools_entry.entry({})["drop_folders"] == {}


@pytest.mark.parametrize("build", ["portable", "another-data-name"])
def test_a_frozen_build_that_isnt_the_installed_3_0_writes_nothing(root, tools, frozen, monkeypatch, build):
    """On 3.0 a frozen program that isn't installed is portable — a test build, dist\\Surasura, cli_smoke (S3.1 D3) —
    and one whose data name isn't Surasura is a test install. Run on the real profile, either would point Sonic's
    surasura.json (hato's way in) at itself: `cli` at dist, `drop_folders` at dist's data or `{}` (09 §3: a
    developer's tree never steals Sonic's entry)."""
    if build == "portable":
        monkeypatch.setattr(path_utils, "installed_library", lambda: None)
    else:
        monkeypatch.setattr(path_utils, "data_name", lambda: "Surasura-test")
    assert tools_entry.entry({"connect_enabled": True}) is None
    assert tools_entry.refresh({"connect_enabled": True}) is False
    assert not tools.exists()


def test_a_portable_frozen_build_advertises_only_SURASURA_TOOLS_CLI_as_from_source(root, tools, frozen, monkeypatch,
                                                                                   tmp_path):
    monkeypatch.setattr(path_utils, "installed_library", lambda: None)
    cli_path = tmp_path / "開発" / "surasura-cli.cmd"
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(cli_path))
    got = tools_entry.entry({})
    assert got["cli"] == str(cli_path) and got["app"] is None


def test_source_checkout_advertises_SURASURA_TOOLS_CLI_with_no_window(root, tools, monkeypatch, tmp_path):
    cli_path = tmp_path / "開発" / "surasura-cli.cmd"
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(cli_path))
    got = tools_entry.entry({})
    assert got["cli"] == str(cli_path) and got["app"] is None


# --------------------------------------------------------------------------- #
# When it is written
# --------------------------------------------------------------------------- #
def test_a_second_refresh_with_nothing_changed_writes_nothing(root, tools, frozen):
    """No write at every launch (§3): bytes and mtime unchanged, the first `updated` kept."""
    assert tools_entry.refresh({}) is True
    before_bytes, before_mtime = _file(tools).read_bytes(), os.stat(_file(tools)).st_mtime_ns
    time.sleep(1.1)       # a rewrite would carry a later `updated` second
    assert tools_entry.refresh({}) is False
    assert _file(tools).read_bytes() == before_bytes and os.stat(_file(tools)).st_mtime_ns == before_mtime


def test_a_changed_field_rewrites_the_entry(root, tools, frozen):
    """Connect's switch turned on: `register` appears for hato at once."""
    tools_entry.refresh({"connect_enabled": False})
    assert tools_entry.refresh({"connect_enabled": True}) is True
    assert _load(tools)["verbs"] == ["status", "register"]
    (root / "User Files" / "zh").mkdir()
    assert tools_entry.refresh({"connect_enabled": True}) is True
    assert set(_load(tools)["drop_folders"]) == {"ja", "zh"}


def test_a_torn_entry_on_disk_is_rewritten(root, tools, frozen):
    tools.mkdir()
    _file(tools).write_bytes(b'{"schema": 1, "tool": "sur')
    assert tools_entry.refresh({}) is True
    assert _load(tools)["tool"] == "surasura"


def test_source_without_SURASURA_TOOLS_CLI_reads_and_writes_nothing(root, tools, monkeypatch):
    """A developer's tree never takes Sonic's entry, and the gate costs nothing: no settings read, no tools folder."""
    reads = []      # recorded, not raised: refresh swallows a settings error, which would hide the read
    monkeypatch.setattr(settings_manager, "load_settings", lambda *a, **k: reads.append("settings") or {})
    monkeypatch.setattr(tools_entry, "tools_dir", lambda: reads.append("tools_dir") or str(tools))
    assert tools_entry.entry({}) is None
    assert tools_entry.refresh() is False
    assert reads == [] and not tools.exists()


def test_refresh_reads_settings_itself_when_none_are_given(root, tools, frozen):
    _write_settings(json.dumps({"connect_enabled": True}))
    assert tools_entry.refresh() is True
    assert _load(tools)["verbs"] == ["status", "register"]


def test_unreadable_settings_skip_the_refresh_quietly(root, tools, frozen, caplog):
    """A half-written settings.json: no entry from a guess at the switch (a fallback could drop `register`)."""
    _write_settings('{"connect_enabled": tr')
    assert tools_entry.refresh() is False
    assert not _file(tools).exists()
    assert "settings.json can't be read" in caplog.text


# --------------------------------------------------------------------------- #
# The atomic replace
# --------------------------------------------------------------------------- #
def _replace_failing(monkeypatch, times):
    """os.replace raising PermissionError `times` times (a reader holding the file open), then the real one."""
    real, calls = os.replace, []
    def flaky(src, dst):
        calls.append(dst)
        if len(calls) <= times:
            raise PermissionError(32, "The process cannot access the file because it is being used")
        return real(src, dst)
    monkeypatch.setattr(tools_entry.os, "replace", flaky)
    return calls


def test_a_reader_holding_the_file_open_is_waited_for_then_written(root, tools, frozen, monkeypatch):
    tools_entry.refresh({})
    calls = _replace_failing(monkeypatch, 3)
    assert tools_entry.refresh({"connect_enabled": True}) is True
    assert len(calls) == 4 and _load(tools)["verbs"] == ["status", "register"]
    assert [p for p in os.listdir(tools) if p.endswith(".tmp")] == []


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses to replace a file another handle holds")
def test_a_real_open_handle_on_windows_is_waited_for_then_written(root, tools, frozen):
    """A real reader (Python's open shares read/write, not delete: os.replace fails while it is open)."""
    tools_entry.refresh({})
    held = open(_file(tools), "rb")
    threading.Timer(0.3, held.close).start()
    try:
        assert tools_entry.refresh({"connect_enabled": True}) is True
    finally:
        held.close()
    assert _load(tools)["verbs"] == ["status", "register"]


def test_a_replace_that_keeps_failing_leaves_the_old_file_and_no_tmp(root, tools, frozen, monkeypatch, caplog):
    """Up to 1 s of tries, then False: the old entry intact, the tmp removed."""
    tools_entry.refresh({})
    old = _file(tools).read_bytes()
    monkeypatch.setattr(tools_entry, "REPLACE_WAIT", 0)
    calls = _replace_failing(monkeypatch, 10 ** 6)
    assert tools_entry.refresh({"connect_enabled": True}) is False
    assert len(calls) == tools_entry.REPLACE_TRIES
    assert _file(tools).read_bytes() == old
    assert os.listdir(tools) == ["surasura.json"]
    assert "held it open" in caplog.text


def test_two_refreshes_at_once_never_share_a_tmp_and_the_switchs_settings_win(root, tools, frozen, monkeypatch):
    """The window's start-up refresh (reading settings.json itself, Connect off) still replacing the entry when the
    Connect switch's refresh comes with the settings it just saved (on): neither fails, each writes its own tmp file,
    and the entry ends as the switch left it — `register` listed."""
    # why: both threads wrote surasura.json.<pid>.tmp, so the second os.replace found it gone (FileNotFoundError, not
    # the PermissionError the retry knows); and a start-up refresh holding the settings from before the switch could
    # replace the entry last, so hato saw no `register` while Connect was on
    _write_settings(json.dumps({"connect_enabled": False}))
    real, inside, release, sources, errors = os.replace, threading.Event(), threading.Event(), [], []

    def replace(src, dst):
        sources.append(os.path.basename(src))
        if threading.current_thread().name == "start-up" and not inside.is_set():
            inside.set()
            release.wait(5)                     # the start-up refresh caught between its tmp and its replace
        return real(src, dst)
    monkeypatch.setattr(tools_entry.os, "replace", replace)

    def refresh(settings):
        try:
            tools_entry.refresh(settings)
        except Exception as e:
            errors.append((threading.current_thread().name, e))
    start_up = threading.Thread(target=refresh, args=(None,), name="start-up")
    start_up.start()
    assert inside.wait(5)
    saved = {"connect_enabled": True}           # the switch saved on, then refreshes with what it saved
    _write_settings(json.dumps(saved))
    switch = threading.Thread(target=refresh, args=(saved,), name="switch")
    switch.start()
    switch.join(0.5)
    release.set()
    start_up.join(5)
    switch.join(5)
    assert errors == [], errors
    assert _load(tools)["verbs"] == ["status", "register"], "the entry as the switch left it"
    assert len(set(sources)) == len(sources) == 2, f"each refresh its own tmp file: {sources}"
    assert [p for p in os.listdir(tools) if p.endswith(".tmp")] == []


def test_retries_span_about_one_second():
    """§3's 'retried for up to 1 s': the waits between tries add up to one second."""
    assert abs((tools_entry.REPLACE_TRIES - 1) * tools_entry.REPLACE_WAIT - 1.0) < 1e-9


def test_the_tmp_file_is_synced_to_disk_before_it_replaces_the_entry(root, tools, frozen, monkeypatch):
    """The tmp file's own descriptor is fsynced, then renamed over surasura.json. Why: a power cut after the rename
    can leave the new name over bytes never written (NTFS and ext4 may commit the rename first) — an empty entry, and
    hato finds no Surasura. Every other test passes with the fsync gone, so this one watches it."""
    tools_entry.refresh({})
    real_fsync, real_replace, events = os.fsync, os.replace, []
    def fsync(fd):
        synced = [name for name in os.listdir(tools) if name.endswith(".tmp")
                  and os.path.samestat(os.fstat(fd), os.stat(tools / name))]
        events.append(("fsync", synced))
        return real_fsync(fd)
    def replace(src, dst):
        events.append(("replace", [os.path.basename(src)]))
        return real_replace(src, dst)
    monkeypatch.setattr(tools_entry.os, "fsync", fsync)
    monkeypatch.setattr(tools_entry.os, "replace", replace)
    assert tools_entry.refresh({"connect_enabled": True}) is True
    tmp = f"surasura.json.{os.getpid()}.{threading.get_ident()}.tmp"
    assert events == [("fsync", [tmp]), ("replace", [tmp])]
    assert _load(tools)["verbs"] == ["status", "register"]


def test_an_entry_over_4_KiB_is_refused(root, tools, monkeypatch, caplog):
    """The file is small by rule: a command line path long enough to pass 4 KiB is never written."""
    monkeypatch.setenv("SURASURA_TOOLS_CLI", os.path.join(str(root), "長" * 1500, "surasura-cli.exe"))
    assert tools_entry.refresh({}) is False
    assert not _file(tools).exists()
    assert "over the 4096-byte limit" in caplog.text


# --------------------------------------------------------------------------- #
# Reading another tool's entry
# --------------------------------------------------------------------------- #
def _hato(tools, tmp_path, **fields):
    hato_cli = tmp_path / "hato" / "hato-cli.exe"
    hato_cli.parent.mkdir(exist_ok=True)
    hato_cli.write_bytes(b"MZ")
    entry = {"schema": 1, "tool": "hato", "name": "hato", "version": "1.1.0", "cli": str(hato_cli), "app": None,
             "contract": 1, "verbs": ["pairings"], "updated": "2026-10-12T09:00:00Z"}
    entry.update(fields)
    tools.mkdir(exist_ok=True)
    (tools / "hato.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    return entry


def test_read_returns_a_present_tools_entry(tools, tmp_path):
    entry = _hato(tools, tmp_path)
    assert tools_entry.read("hato") == entry


def test_read_retries_a_torn_entry_once_after_50_ms(tools, tmp_path, monkeypatch):
    """hato mid-replace: the first read is torn, the one 50 ms later whole."""
    entry = _hato(tools, tmp_path)
    good = (tools / "hato.json").read_bytes()
    (tools / "hato.json").write_bytes(good[:20])
    waits = []
    def sleep(seconds):
        waits.append(seconds)
        (tools / "hato.json").write_bytes(good)
    monkeypatch.setattr(tools_entry.time, "sleep", sleep)
    assert tools_entry.read("hato") == entry
    assert waits == [0.05]


def test_read_torn_twice_is_absent(tools, tmp_path, monkeypatch):
    _hato(tools, tmp_path)
    (tools / "hato.json").write_bytes(b'{"schema": 1, "cli"')
    monkeypatch.setattr(tools_entry.time, "sleep", lambda s: None)
    assert tools_entry.read("hato") is None


def test_read_a_missing_entry_is_absent(tools):
    assert tools_entry.read("hato") is None


def test_read_an_entry_whose_cli_is_gone_is_absent(tools, tmp_path):
    """A deleted 2.x zip install leaves its entry behind: its `cli` missing means the tool is absent."""
    entry = _hato(tools, tmp_path)
    os.remove(entry["cli"])
    assert tools_entry.read("hato") is None


@pytest.mark.parametrize("field", ["contract", "schema"])
def test_read_an_entry_too_new_is_absent(tools, tmp_path, field):
    _hato(tools, tmp_path, **{field: 2})
    assert tools_entry.read("hato") is None


@pytest.mark.parametrize("wrong", [[], "hato", None, {"schema": "1"}, {"contract": "1"}, {"cli": None}],
                         ids=["a-list", "a-string", "null", "schema-as-text", "contract-as-text", "cli-null"])
def test_read_an_entry_written_wrong_is_absent_never_a_crash(tools, tmp_path, wrong):
    """Another program's file: no object at all, a version that isn't a number or no command line named means hato
    counts as absent. Why: a TypeError here would stop the caller (the back-fill, the window's worker asking for hato)
    instead of saying "hato isn't there"."""
    entry = _hato(tools, tmp_path)
    if isinstance(wrong, dict):
        entry.update(wrong)
    else:
        entry = wrong
    (tools / "hato.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    assert tools_entry.read("hato") is None


# --------------------------------------------------------------------------- #
# Where the folder is
# --------------------------------------------------------------------------- #
def test_a_test_with_neither_folder_nor_root_raises(monkeypatch):
    """The pytest guard: a test can never reach the real %LOCALAPPDATA%\\Houseki\\tools."""
    monkeypatch.delenv("HOUSEKI_TOOLS_DIR", raising=False)
    monkeypatch.delenv("SURASURA_TEST_ROOT", raising=False)
    assert "PYTEST_CURRENT_TEST" in os.environ
    with pytest.raises(RuntimeError, match="real shared tools folder"):
        tools_entry.tools_dir()


def test_the_test_root_holds_houseki_tools(root, monkeypatch):
    monkeypatch.delenv("HOUSEKI_TOOLS_DIR", raising=False)
    assert tools_entry.tools_dir() == os.path.join(str(root), "houseki-tools")


def test_HOUSEKI_TOOLS_DIR_wins_over_the_test_root(root, tools):
    assert tools_entry.tools_dir() == str(tools)


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows location")
def test_the_real_folder_is_local_appdata_houseki_tools(monkeypatch, tmp_path):
    """Outside a test (both overrides and PYTEST_CURRENT_TEST gone): computed only, never created."""
    monkeypatch.delenv("HOUSEKI_TOOLS_DIR", raising=False)
    monkeypatch.delenv("SURASURA_TEST_ROOT", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert tools_entry.tools_dir() == os.path.join(str(tmp_path / "Local"), "Houseki", "tools")
    assert not (tmp_path / "Local").exists()


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_the_real_folder_off_windows_is_path_utils_tools_root(monkeypatch, tmp_path, platform):
    """One folder, one definition (S3.1 D20, 09 §3): `path_utils.tools_root()` — Linux $XDG_DATA_HOME/Houseki/tools,
    macOS ~/Library/Application Support/Houseki/tools. Why: tools_entry once worked out its own Linux folder
    ($XDG_STATE_HOME/houseki/tools), so Surasura would write where Torii and hato never look."""
    monkeypatch.delenv("HOUSEKI_TOOLS_DIR", raising=False)
    monkeypatch.delenv("SURASURA_TEST_ROOT", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    home = str(tmp_path / "家")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "共有"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "状態"))
    monkeypatch.setattr(os.path, "expanduser", lambda p: home + p[1:] if p.startswith("~") else p)
    monkeypatch.setattr(sys, "platform", platform)
    expected = (os.path.join(str(tmp_path / "共有"), "Houseki", "tools") if platform == "linux" else
                os.path.join(home, "Library", "Application Support", "Houseki", "tools"))
    assert tools_entry.tools_dir() == path_utils.tools_root() == expected


# --------------------------------------------------------------------------- #
# The hooks: every surasura-cli call, the window's start
# --------------------------------------------------------------------------- #
def _call(argv):
    out = io.StringIO()
    code = cli.main(argv, out=out)
    return code, out.getvalue()


def test_a_cli_call_under_root_writes_its_entry_there(tmp_path, monkeypatch):
    """`--root` applies first, so the entry lands in <root>/houseki-tools; the verb answers as without it."""
    monkeypatch.delenv("HOUSEKI_TOOLS_DIR", raising=False)
    closed = _call(["--root", str(tmp_path / "閉"), "_selftest", "ok", "--echo", "日本語"])
    r = tmp_path / "根"
    (r / "User Files" / "zh").mkdir(parents=True)
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(tmp_path / "surasura-cli.cmd"))
    assert _call(["--root", str(r), "_selftest", "ok", "--echo", "日本語"]) == closed
    got = json.loads((r / "houseki-tools" / "surasura.json").read_text(encoding="utf-8"))
    assert got["drop_folders"] == {"zh": _hato_folder(r, "zh")}
    assert not (tmp_path / "閉" / "houseki-tools").exists()      # the closed gate wrote nothing


def _stage_update(r):
    """The updater's marker armed under the test root `r` (<root>/local_root/update/, S3.1 D9) -> its path."""
    marker = r / "local_root" / path_utils.UPDATE_DIRNAME / path_utils.UPDATE_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")
    return marker


@pytest.mark.parametrize("argv", [["--version"], ["status", "--lang", "ja"]], ids=["--version", "status"])
def test_a_staged_update_leaves_the_entry_alone_for_the_verbs_that_answer_then(tmp_path, monkeypatch, argv):
    """02 §7: `status`, `logs` and `--version` write nothing while an update is staged, and the swapper proves a swap
    by the new program's --version while its marker exists (S3.1 D9). Refreshed then, surasura.json would name the
    new version mid-update: hato's "retry once `version` changes" (09 §2) fires while the update is still staged, and
    a swap undone after that proof leaves the entry naming a version that isn't there. Never written: still absent;
    written: untouched to the byte; the verb's answer as with the gate closed. The marker gone, the same call writes."""
    monkeypatch.delenv("HOUSEKI_TOOLS_DIR", raising=False)
    r = tmp_path / "根"
    (r / "User Files" / "ja").mkdir(parents=True)
    marker = _stage_update(r)
    closed = _call(["--root", str(r)] + argv)
    assert closed[0] == 0, closed           # both answer while staged (status says so: `update_staged`)
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(tmp_path / "スラスラ" / "surasura-cli.cmd"))
    entry_file = r / "houseki-tools" / "surasura.json"
    assert _call(["--root", str(r)] + argv) == closed
    assert not entry_file.exists()
    entry_file.parent.mkdir()
    old = json.dumps({"schema": 1, "tool": "surasura", "version": "2.5.0", "cli": "旧"}, ensure_ascii=False)
    entry_file.write_bytes(old.encode("utf-8"))
    assert _call(["--root", str(r)] + argv) == closed
    assert entry_file.read_bytes() == old.encode("utf-8")
    marker.unlink()
    _call(["--root", str(r)] + argv)
    assert _load(entry_file.parent)["version"] == __version__


def test_a_staged_update_refused_verb_writes_no_entry(tmp_path, monkeypatch):
    """Every other verb answers `update-staged` while an update is staged, and refreshes nothing: the refresh comes
    after the update check."""
    monkeypatch.delenv("HOUSEKI_TOOLS_DIR", raising=False)
    r = tmp_path / "根"
    _stage_update(r)
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(tmp_path / "surasura-cli.cmd"))
    code, out = _call(["--root", str(r), "_selftest", "ok", "--echo", "日本語"])
    assert code == 3 and '"update-staged"' in out
    assert not (r / "houseki-tools").exists()


@pytest.mark.parametrize("outcome, code", [("ok", 0), ("fail", 1)])
def test_a_failing_entry_write_never_changes_the_verbs_answer(tmp_path, monkeypatch, outcome, code):
    """The tools folder is a FILE (unwritable everywhere): the verb answers and exits as it would, the failure only
    in cli.log."""
    r = tmp_path / "根"
    expected = _call(["--root", str(r), "_selftest", outcome])
    assert expected[0] == code
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(blocker))
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(tmp_path / "surasura-cli.cmd"))
    assert _call(["--root", str(r), "_selftest", outcome]) == expected
    with open(os.path.join(str(r), "local", "logs", "cli.log"), encoding="utf-8") as f:
        assert "surasura.json (the shared tools file) wasn't refreshed" in f.read()


def test_the_dashboard_start_writes_the_entry_off_its_thread(tools, monkeypatch, tmp_path):
    """The window's start (conftest's test root, with its templates and samples): one refresh, on a worker thread."""
    import tkinter as tk
    from app.main import MasterDashboardApp
    monkeypatch.setenv("SURASURA_TOOLS_CLI", str(tmp_path / "surasura-cli.cmd"))
    window = threading.get_ident()
    threads = []
    real = tools_entry.refresh
    def spy(settings=None):
        threads.append(threading.get_ident())
        return real(settings)
    monkeypatch.setattr(tools_entry, "refresh", spy)
    tk_root = tk.Tk()
    tk_root.withdraw()
    try:
        MasterDashboardApp(tk_root)
        for _ in range(250):
            if _file(tools).exists():
                break
            time.sleep(0.02)
    finally:
        tk_root.destroy()
    assert _load(tools)["cli"] == str(tmp_path / "surasura-cli.cmd")
    assert len(threads) == 1 and window not in threads


def test_the_dashboard_start_survives_a_failing_entry_write(monkeypatch):
    from app.main import MasterDashboardApp
    def boom(settings=None):
        raise OSError("read-only")
    monkeypatch.setattr(tools_entry, "refresh", boom)
    MasterDashboardApp._refresh_tools_entry()       # no exception
