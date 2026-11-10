"""P4.1 row 4.1.1 (C1, WZ-4 / D29): Connect's one 3.0 gate, `settings_manager.connect_on(settings)` — Connect's own
switch (`connect_enabled`, *Make cards for me*) **and** D29's automation (`logic.automation`). Every place that starts
Connect's unattended work reads it: `kick`, the runner's look (`Steps.enabled`), the Anki session (`anki_session.on`:
the session's sync, the waits, *Open Anki for me*), Anki Miner's daily release check, the setup check's *Open Anki for
me*, Known from Anki (`known_signal.signal`, `anki_sync.read_known_signal`) and the verbs' session sync. What
describes your set-up keeps `connect_enabled` alone: hato's back-fill still registers its pairings with the automation
off.

What a wrong answer would cost: with the automation switched off ("nothing automatic", D29) Connect would still start,
open Anki, sync it, ask GitHub every day or mark words known from your suspended cards; or, the other way, hato's
pairings would stop being recorded while the automation is off, so switching it back on would leave every episode
hato paired meanwhile without its video.

The test's own root and settings.json; Anki, GitHub and process starts are stood in for. Real Japanese subtitles for
hato's files (`connect_helpers.drop`).
"""
import json
import os
import subprocess
import types

import pytest

from app import settings_manager
from app.connect import am_release, anki_session, hato, kick, known_signal, open_anki, runner, setup
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

URL = "http://127.0.0.1:8765"
# (name, settings, Connect's unattended work may start)
STATES = [
    ("both on", {"connect_enabled": True}, True),
    ("both on, the automation said", {"connect_enabled": True, "logic": {"automation": True}}, True),
    ("automation off", {"connect_enabled": True, "logic": {"automation": False}}, False),
    ("connect off", {"connect_enabled": False}, False),
    ("connect off, automation on", {"connect_enabled": False, "logic": {"automation": True}}, False),
]
IDS = [s[0] for s in STATES]


@pytest.mark.parametrize("name,settings,on", STATES, ids=IDS)
def test_connect_on_is_both_switches(name, settings, on):
    assert settings_manager.connect_on(settings) is on
    assert settings_manager.connect_on(types.MappingProxyType(settings)) is on, "a window's frozen copy reads alike"


def test_connect_on_reads_none_and_a_torn_file_as_off_and_a_torn_logic_block_as_on():
    assert settings_manager.connect_on(None) is False
    assert settings_manager.connect_on({}) is False
    assert settings_manager.connect_on({"connect_enabled": True, "logic": "torn"}) is True, \
        "a malformed logic block reads the automation on (D29's default), as `automation` does"
    assert settings_manager.connect_on({"connect_enabled": True, "logic": {"automation": None}}) is True


# --------------------------------------------------------------------------- #
# The starters
# --------------------------------------------------------------------------- #
@pytest.fixture
def starts(monkeypatch):
    """`kick` allowed to start under the test root, its process start recorded instead."""
    monkeypatch.setenv("SURASURA_CONNECT_KICK", "1")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a) or "a process")
    monkeypatch.setattr(kick, "running", lambda: False)
    return started


@pytest.mark.parametrize("name,settings,on", STATES, ids=IDS)
def test_kick_starts_connect_only_with_both_on(starts, name, settings, on):
    assert (kick.kick(dict(settings)) == "a process") is on
    assert len(starts) == (1 if on else 0)


@pytest.mark.parametrize("name,settings,on", STATES, ids=IDS)
def test_the_runners_look_reads_both_from_the_file(name, settings, on):
    h.write_settings(**settings)
    steps = runner.Steps({"connect_enabled": True})
    assert steps.enabled() is on, "settings.json as it is now, never the run's start"
    assert runner._stop(steps) == (None if on else runner.SWITCHED_OFF)


@pytest.fixture
def anki(monkeypatch):
    """Anki stood in for at the session's one look: each look counted (closed), *Open Anki for me*'s start recorded."""
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    seen = types.SimpleNamespace(looks=[], opened=[])
    monkeypatch.setattr(anki_session, "look", lambda url: seen.looks.append(url) or "closed")
    monkeypatch.setattr(open_anki, "running", lambda: False)
    monkeypatch.setattr(open_anki, "start", lambda profile: seen.opened.append(profile) and None)
    return seen


@pytest.mark.parametrize("name,settings,on", STATES, ids=IDS)
def test_the_anki_session_opens_and_asks_anki_only_with_both_on(anki, name, settings, on):
    loaded = dict(settings, anki_connect_url=URL, connect_open_anki=True)
    assert anki_session.on(loaded) is on
    out = anki_session.at_window(loaded, opening=True, sleep=lambda s: None)
    if on:
        assert out == {"anki": "closed", "opened": False, "sync": None} and len(anki.opened) == 1, \
            "Open Anki for me tried at the window's start"
    else:
        assert out is None and anki.opened == [], "no Anki opened with the automation off"
    assert anki_session.waiting(URL, loaded) == ("Waiting for Anki: it isn't open." if on else None)
    assert anki_session.begin(URL, loaded) is None
    assert (len(anki.looks) > 0) is on, "off: Anki never even looked at"


def test_the_anki_session_stays_off_under_no_anki_sync_with_both_on(anki, monkeypatch):
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    assert anki_session.on({"connect_enabled": True}) is False


@pytest.mark.parametrize("name,settings,on", STATES, ids=IDS)
def test_anki_miners_daily_check_asks_github_only_with_both_on(monkeypatch, name, settings, on):
    monkeypatch.setattr(am_release, "_thread", None)
    asked = []
    out = am_release.check(dict(settings), now=1_760_000_000, fetch=lambda: asked.append(1) or
                           {"tag_name": "v3.8.0", "html_url": am_release.RELEASES + "/tag/v3.8.0"})
    assert (out is not None, len(asked)) == ((True, 1) if on else (False, 0))
    assert os.path.exists(am_release.path()) is on, "off: nothing read or written either"


@pytest.mark.parametrize("name,settings,on", STATES, ids=IDS)
def test_the_setup_check_names_open_anki_for_me_only_when_it_would_open_anki(monkeypatch, name, settings, on):
    monkeypatch.setattr(open_anki, "find", lambda: ["anki.exe"])
    checks = setup._open_anki(dict(settings, connect_open_anki=True))
    assert [ch["id"] for ch in checks] == (["open_anki"] if on else [])


def test_the_setup_record_is_kept_with_the_automation_off(monkeypatch):
    """`setup.checks` keeps its record while Connect's switch is on, whatever the automation says (set-up, not
    automation): the check's own `keep` reads `connect_enabled`."""
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")             # Anki isn't asked: its check says so
    h.seed_library("ja", templates=False)
    out = setup.checks({"connect_enabled": True, "logic": {"automation": False}}, "ja")
    assert out["recorded"] is True and "ja" in setup.read_record().get("checks", {})


@pytest.mark.parametrize("name,settings,on", STATES, ids=IDS)
def test_known_from_anki_reads_nothing_unless_both_on(monkeypatch, name, settings, on):
    from app import anki_sync
    loaded = dict(settings, known_from_anki=["suspended"])
    assert known_signal.signal(loaded) == (["suspended"] if on else [])
    read = []
    monkeypatch.setattr(known_signal, "read", lambda *a: read.append(a) or {"marked": 0})
    out = anki_sync.read_known_signal("ja", URL, ["日本語"], ["Word"], loaded)
    assert (out, len(read)) == (({"marked": 0}, 1) if on else (None, 0))


@pytest.mark.parametrize("name,settings,on", STATES, ids=IDS)
def test_the_verbs_session_sync_only_with_both_on(monkeypatch, name, settings, on):
    from app.cli import verbs
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    assert (verbs._session(dict(settings)) is anki_session) is on


# --------------------------------------------------------------------------- #
# The set-up keeps `connect_enabled`
# --------------------------------------------------------------------------- #
@pytest.fixture
def tools(tmp_path, monkeypatch):
    """The test's own shared tools folder: the real one is never read or written."""
    folder = tmp_path / "houseki-tools"
    monkeypatch.setenv("HOUSEKI_TOOLS_DIR", str(folder))
    return folder


def test_hatos_backfill_still_registers_with_the_automation_off(tmp_path, tools):
    """Set-up, not automation: hato's pairings are recorded with the automation off (Connect's switch on), so the
    episodes are ready when it goes back on — and none is mined because of it (no event, no job, no kick)."""
    paths = [c.drop(f"Example Show - {n:02d}.ja.srt") for n in range(1, 3)]
    c.library(logic={"automation": False})
    with c.store() as s:
        from app.connect import library
        library.switch_on(s)
    lines = [c.pairing_line(c.hato_record(p, n)) for n, p in enumerate(paths, 1)]
    c.fake_hato(tmp_path, lines, c.result_line(2, None))
    loaded = settings_manager.load_settings(strict=True)
    assert settings_manager.connect_on(loaded) is False, "the automation is off"
    out = hato.backfill("ja", loaded)
    assert (out["skipped"], out["hato"], out["new"], out["refused"]) == (None, hato.ASKED, 2, []), out
    with c.store() as s:
        stored = {json.loads(p)["library_path"] for (p,) in s.conn.execute("SELECT pairing FROM pairings")}
        rows, gap = s.read_events(library.READER)
    assert stored == set(paths)
    assert not gap and rows == [], "nothing logged: nothing mined because of it"


def test_hatos_backfill_with_connect_off_asks_nothing(tmp_path, tools):
    paths = [c.drop("Example Show - 01.ja.srt")]
    c.library(connect=False)
    fake = c.fake_hato(tmp_path, [c.pairing_line(c.hato_record(paths[0], 1))], c.result_line(1, None))
    out = hato.backfill("ja", settings_manager.load_settings(strict=True))
    assert out["skipped"] == hato.PREVIEW_OFF and fake.calls() == []
