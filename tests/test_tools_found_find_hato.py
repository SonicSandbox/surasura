"""*Find hato…* (`app/services/tools_found.connect_hato`; Michi-HD, Mattias's 3.0.0 report 2026-11-11: his hato,
unpacked on his D: drive, never seen by Surasura).

The cause, reproduced with hato 1.2.0's published zip (sha256 663ddf4d…8b32) unpacked on another drive: hato writes its
entry in the shared tools folder (`hato.json`) only when it starts and Surasura's own entry (`surasura.json`) is there
already (hato's `connect.write_hato_json`). A hato opened before Surasura was installed — or moved since — is never seen
until hato's window starts again, and Surasura offered nothing but *not installed*.

What a wrong answer would cost: a hato the learner has that Surasura still can't see (the report); a folder that isn't
hato's started anyway, or Surasura's entry written for nothing; a portable Surasura that opens hato for an entry hato
will never write; a press that waits forever, or says "connected" for another copy of hato.

`STAND_IN` is hato's own rule, as 1.2.0 does it (the entry is the one the real hato wrote in the reproduction). Every
test has its own test root and tools folder; the folders carry Japanese names, as learners' drives do.
"""
import json
import os
import sys

import pytest

from app import path_utils, tools_entry
from app.services import tools_found

EXE = ".exe" if sys.platform == "win32" else ""


@pytest.fixture
def tools(tmp_path, monkeypatch):
    root = tmp_path / "データ"
    (root / "User Files" / "ja").mkdir(parents=True)
    monkeypatch.setenv("SURASURA_TEST_ROOT", str(root))
    folder = tmp_path / "tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    return folder


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """An installed Surasura (frozen, library.json naming its library): the one that writes surasura.json."""
    install = tmp_path / "スラスラ"
    install.mkdir()
    (install / "Surasura.exe").write_bytes(b"MZ")
    (install / "surasura-cli.exe").write_bytes(b"MZ")
    library = tmp_path / "ライブラリ"
    library.mkdir()
    monkeypatch.setattr(path_utils, "is_frozen", lambda: True)
    monkeypatch.setattr(path_utils, "installed_library", lambda: str(library))
    monkeypatch.setattr(sys, "executable", str(install / "Surasura.exe"))
    monkeypatch.delenv("SURASURA_TOOLS_CLI", raising=False)
    return install


def unpacked_hato(parent):
    """hato's zip unpacked into `parent` (D:\\hato): its `hato` folder with the programs in it."""
    place = parent / "hato"
    place.mkdir(parents=True)
    for name in ("hato", "hato-cli", "hato-update", "hato-watch"):
        (place / f"{name}{EXE}").write_bytes(b"MZ")
    return place


class StandIn:
    """hato's window starting (`connect.refresh` at its start): hato.json written for the hato in the program's folder
    only when surasura.json is there with its `cli` on disk. `writes=False`: a hato too slow to write it in time."""

    def __init__(self, tools, version="1.2.0", writes=True, verbs=("pairings", "find")):
        self.tools, self.version, self.writes, self.verbs = tools, version, writes, list(verbs)
        self.started = []

    def __call__(self, program):
        self.started.append(program)
        surasura = self.tools / "surasura.json"
        if not self.writes or not surasura.is_file():
            return None
        cli = json.loads(surasura.read_text(encoding="utf-8")).get("cli")
        if not isinstance(cli, str) or not os.path.isfile(cli):
            return None
        here = os.path.dirname(program)
        write_hato_json(self.tools, os.path.join(here, f"hato-cli{EXE}"), self.version, self.verbs,
                        app=program)
        return None


def write_hato_json(tools, cli, version="1.2.0", verbs=("pairings", "find"), app=None):
    """hato.json as hato 1.2.0 wrote it in the reproduction."""
    tools.mkdir(parents=True, exist_ok=True)
    entry = {"schema": 1, "tool": "hato", "name": "hato", "version": version, "cli": cli, "app": app, "contract": 1,
             "verbs": list(verbs), "updated": "2026-11-11T04:35:01Z"}
    (tools / "hato.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Clock:
    """A test clock: `sleep` moves it, nothing waits."""

    def __init__(self):
        self.now = 0.0
        self.slept = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.slept += 1


SETTINGS = {"connect_enabled": False}


# --- the cause ------------------------------------------------------------------------------------------------------ #
def test_a_hato_opened_before_surasura_was_installed_is_never_seen(tools, installed, tmp_path):
    # the reproduction: hato's window started with no surasura.json -> hato writes no entry; Surasura installs later
    place = unpacked_hato(tmp_path / "D_ドライブ")
    hato = StandIn(tools)
    hato(str(place / f"hato{EXE}"))
    assert not (tools / "hato.json").exists()
    tools_entry.refresh(SETTINGS)                       # Surasura's window starts: its own entry, nothing of hato's
    assert (tools / "surasura.json").is_file()
    assert tools_found.hato_version() is None           # Settings: *not installed*


# --- the fix -------------------------------------------------------------------------------------------------------- #
def test_find_hato_on_the_unpacked_folder_opens_hato_once_and_finds_its_version(tools, installed, tmp_path):
    picked = tmp_path / "D_ドライブ"                     # the learner picks D:\hato (the zip's own folder is inside)
    place = unpacked_hato(picked)
    hato, clock = StandIn(tools), Clock()
    answer = tools_found.connect_hato(str(picked), SETTINGS, start=hato, clock=clock, sleep=clock.sleep)
    assert answer == tools_found.Connected("1.2.0", None)
    assert hato.started == [os.path.normpath(str(place / f"hato{EXE}"))]        # hato.exe, from its own folder, once
    assert (tools / "surasura.json").is_file()                                   # written before hato started
    assert tools_found.hato_version() == "1.2.0"                                 # every reader sees it now


def test_the_folder_with_the_programs_in_it_works_too(tools, installed, tmp_path):
    place = unpacked_hato(tmp_path / "ツール")
    hato, clock = StandIn(tools), Clock()
    assert tools_found.connect_hato(str(place), SETTINGS, start=hato, clock=clock, sleep=clock.sleep).why is None
    assert len(hato.started) == 1


def test_a_hato_that_moved_is_found_in_its_new_folder(tools, installed, tmp_path):
    # its old entry names a folder that is gone (moved to D:): `read` counts it absent; the new one replaces it
    write_hato_json(tools, str(tmp_path / "Downloads" / "hato" / f"hato-cli{EXE}"))
    assert tools_found.hato_version() is None
    picked = tmp_path / "D_ドライブ"
    unpacked_hato(picked)
    hato, clock = StandIn(tools, version="1.2.0"), Clock()
    assert tools_found.connect_hato(str(picked), SETTINGS, start=hato, clock=clock, sleep=clock.sleep) == \
        tools_found.Connected("1.2.0", None)


def test_a_hato_already_connected_from_that_folder_is_answered_at_once(tools, installed, tmp_path):
    place = unpacked_hato(tmp_path / "D_ドライブ")
    write_hato_json(tools, str(place / f"hato-cli{EXE}"), version="1.1.0")
    hato, clock = StandIn(tools), Clock()
    assert tools_found.connect_hato(str(place.parent), SETTINGS, start=hato, clock=clock, sleep=clock.sleep) == \
        tools_found.Connected("1.1.0", None)
    assert hato.started == [] and clock.slept == 0


def test_hatos_connect_switch_off_still_counts_as_found(tools, installed, tmp_path):
    # hato's *Hand new subtitles to Surasura* off: its entry keeps its cli with no verbs (A1) — hato is there
    picked = tmp_path / "D_ドライブ"
    unpacked_hato(picked)
    hato, clock = StandIn(tools, verbs=()), Clock()
    assert tools_found.connect_hato(str(picked), SETTINGS, start=hato, clock=clock, sleep=clock.sleep) == \
        tools_found.Connected("1.2.0", None)


# --- what is refused, and the waits ----------------------------------------------------------------------------------- #
@pytest.mark.parametrize("layout", ["empty", "only_the_window", "a_video_folder"])
def test_a_folder_that_isnt_hatos_starts_nothing_and_writes_nothing(tools, installed, tmp_path, layout):
    picked = tmp_path / "動画"
    picked.mkdir()
    if layout == "only_the_window":                     # hato.exe without hato-cli: not a hato Surasura can ask
        (picked / f"hato{EXE}").write_bytes(b"MZ")
    elif layout == "a_video_folder":
        (picked / "ぼっち・ざ・ろっく！ 01.mkv").write_bytes(b"\x1a\x45\xdf\xa3")
        (picked / "ぼっち・ざ・ろっく！ 01.ja.srt").write_text("1\r\n00:00:01,000 --> 00:00:02,000\r\nこんにちは\r\n",
                                                          encoding="utf-8")
    hato, clock = StandIn(tools), Clock()
    assert tools_found.connect_hato(str(picked), SETTINGS, start=hato, clock=clock, sleep=clock.sleep) == \
        tools_found.Connected(None, tools_found.NOT_HATO)
    assert hato.started == [] and not tools.exists()


def test_a_surasura_that_writes_no_entry_never_opens_hato(tools, tmp_path, monkeypatch):
    # a source run without SURASURA_TOOLS_CLI (a portable build is the same): hato would never write its entry
    monkeypatch.delenv("SURASURA_TOOLS_CLI", raising=False)
    picked = tmp_path / "D_ドライブ"
    unpacked_hato(picked)
    hato, clock = StandIn(tools), Clock()
    assert tools_found.connect_hato(str(picked), SETTINGS, start=hato, clock=clock, sleep=clock.sleep) == \
        tools_found.Connected(None, tools_found.NOT_INSTALLED)
    assert hato.started == [] and not (tools / "surasura.json").exists()


def test_a_hato_that_cant_be_started_says_so(tools, installed, tmp_path):
    picked = tmp_path / "D_ドライブ"
    unpacked_hato(picked)

    def refused(_program):
        raise PermissionError(13, "Access is denied")     # Controlled folder access, an antivirus
    clock = Clock()
    assert tools_found.connect_hato(str(picked), SETTINGS, start=refused, clock=clock, sleep=clock.sleep) == \
        tools_found.Connected(None, tools_found.NOT_STARTED)


def test_a_hato_that_writes_nothing_in_time_is_waited_for_then_given_up(tools, installed, tmp_path):
    picked = tmp_path / "D_ドライブ"
    unpacked_hato(picked)
    hato, clock = StandIn(tools, writes=False), Clock()
    answer = tools_found.connect_hato(str(picked), SETTINGS, start=hato, wait=30.0, every=0.5, clock=clock,
                                      sleep=clock.sleep)
    assert answer == tools_found.Connected(None, tools_found.NO_ANSWER)
    assert 30.0 <= clock.now <= 30.5 and len(hato.started) == 1          # waited its time, opened once


def test_an_entry_another_hato_wrote_meanwhile_is_not_this_one(tools, installed, tmp_path):
    # another copy of hato (say a held one) wrote its own entry: still not the picked folder's -> keep waiting
    picked = tmp_path / "D_ドライブ"
    unpacked_hato(picked)
    other = unpacked_hato(tmp_path / "ほか")

    def elsewhere(_program):
        write_hato_json(tools, str(other / f"hato-cli{EXE}"))
    clock = Clock()
    assert tools_found.connect_hato(str(picked), SETTINGS, start=elsewhere, wait=2.0, clock=clock,
                                    sleep=clock.sleep) == tools_found.Connected(None, tools_found.NO_ANSWER)
    assert tools_found.hato_version() == "1.2.0"        # the other hato is still seen, as it was


def test_start_hato_starts_the_program_detached_from_its_folder_without_surasuras_runtime(tmp_path, monkeypatch):
    calls = []

    def popen(argv, **options):
        calls.append((argv, options))
        return "proc"
    monkeypatch.setattr(tools_found.subprocess, "Popen", popen)
    monkeypatch.setenv("_MEIPASS2", "C:\\Temp\\_MEI1234")            # a frozen Surasura's own: never hato's
    program = str(tmp_path / "D_ドライブ" / "hato" / f"hato{EXE}")
    assert tools_found.start_hato(program) == "proc"
    argv, options = calls[0]
    assert argv == [program] and options["cwd"] == os.path.dirname(program)
    assert "_MEIPASS2" not in options["env"] and options["stdin"] is tools_found.subprocess.DEVNULL
