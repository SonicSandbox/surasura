"""Connect's setup checks (P2.3 row 2.3.1; P1.5 04-onboarding §1, S1–S8; 06-edges E3, E5, E7, E9–E12, E28, W1): each
piece checked in order, each missing one named in one plain sentence with its one action, a waiting state never
*Needs you*, and the setup record kept only while Connect's preview is on.

Anki is a stand-in (`anki_connect.probe` / `invoke` patched: read-only questions only); Anki Miner is the fake one
(07-tests §1), so the real one is never found, started or read. Profile names are real Japanese and Chinese ones (a
profile can be called anything a learner types).
"""
import json
import os

import pytest

from app import anki_connect, anki_sync
from app.connect import anki_miner, setup
from tests.connect.fake_anki_miner import FEATURES_37

ORDER = ["anki", "anki_profile", "ankiweb", "first_known_sync", "anki_miner", "anki_miner_version",
         "anki_miner_profile", "anki_miner_setup", "junban", "backfill"]


class StandInAnki:
    """What Anki answers: open or not, the actions its add-on has, the open profile. Records every question."""

    def __init__(self, monkeypatch, open_=True, profile="日本語", missing=(), timed_out=False):
        self.open, self.profile, self.missing, self.timed_out = open_, profile, list(missing), timed_out
        self.asked = []
        monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
        monkeypatch.setattr(anki_connect, "probe", self.probe)
        monkeypatch.setattr(anki_connect, "invoke", self.invoke)

    def probe(self, url, required=(), timeout=5):
        self.asked.append(("probe", tuple(required)))
        if not self.open:
            return {"ok": False, "version": None, "missing": [], "error": "closed", "timed_out": self.timed_out}
        return {"ok": True, "version": 6, "missing": [a for a in required if a in self.missing], "error": ""}

    def invoke(self, action, url, timeout=30, **params):
        self.asked.append((action, params))
        if not self.open:
            raise anki_connect.AnkiError("closed", kind="offline")
        if action == "getActiveProfile":
            return self.profile
        raise AssertionError(f"the setup checks asked Anki for {action}: they only read")


def _settings(fake_miner=None, **values):
    settings = {"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:8765",
                "anki_sync_decks": {"ja": ["日本語::Mining"], "zh": ["中文::挖掘"]}}
    if fake_miner is not None:
        settings["connect_anki_miner_path"] = fake_miner.path
    settings.update(values)
    return settings


def _synced_once(language="ja"):
    anki_sync._save_state(language, {"last_sync": "2026-10-07T08:15:00", "decks": ["日本語::Mining"]})


@pytest.fixture
def ready_37(fake_miner):
    """Anki Miner 3.7 with its features, the user's own profile active (no "Surasura" one: optional from 3.7)."""
    fake_miner.plan(app="3.7.0", features=FEATURES_37,
                    profiles=[{"id": "p-main", "name": "メイン", "active": True}])
    _synced_once()
    return fake_miner


def _by_id(result):
    return {c["id"]: c for c in result["checks"]}


# --------------------------------------------------------------------------- #
# Everything there
# --------------------------------------------------------------------------- #
def test_with_every_piece_there_connect_is_ready_and_the_record_keeps_what_it_found(monkeypatch, ready_37):
    StandInAnki(monkeypatch, profile="日本語")
    result = setup.checks(_settings(ready_37), "ja")
    assert [c["id"] for c in result["checks"]] == ORDER, "the order of 04-onboarding §1"
    assert result["ready"] and all(c["state"] in ("ok", "skipped") for c in result["checks"]), result
    checks = _by_id(result)
    assert '"メイン"' in checks["anki_miner_profile"]["say"]          # the active one, by name (Z-1: optional)
    record = setup.read_record()
    assert record["anki_profile"] == "日本語", "the first profile Anki answered with is Connect's"
    assert record["anki_miner"]["app"] == "3.7.0" and record["anki_miner"]["profile"] == "p-main"
    assert [c["id"] for c in record["checks"]["ja"]] == ORDER
    # Anki Miner was only asked: version first, then profiles, then check (research/01: version before anything)
    assert ready_37.commands() == ["version", "profiles", "check"]


def test_the_record_is_atomic_utf8_and_lives_in_connects_own_local_data(monkeypatch, ready_37):
    StandInAnki(monkeypatch, profile="中文学习")
    setup.checks(_settings(ready_37), "zh")
    path = setup.record_path()
    assert os.path.commonpath([path, os.environ["SURASURA_TEST_ROOT"]]) == os.environ["SURASURA_TEST_ROOT"]
    assert os.path.basename(os.path.dirname(path)) == "connect"
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["anki_profile"] == "中文学习"
    assert not [n for n in os.listdir(os.path.dirname(path)) if n.endswith(".tmp")], "no temp file left behind"


def test_with_connects_preview_off_it_checks_and_writes_nothing(monkeypatch, ready_37):
    # Off = 2.5: nothing of Connect's is written (ORDER's rule); the answer still names each piece
    StandInAnki(monkeypatch)
    result = setup.checks(_settings(ready_37, connect_enabled=False), "ja")
    assert result["ready"] and result["recorded"] is False
    assert not os.path.exists(setup.record_path())
    assert result["anki_profile"] == "日本語", "said, not kept"


# --------------------------------------------------------------------------- #
# Anki (S1, S2, E3, E5)
# --------------------------------------------------------------------------- #
def test_anki_closed_is_a_wait_never_needs_you_and_its_profile_waits_to_be_checked(monkeypatch, ready_37):
    StandInAnki(monkeypatch, open_=False)
    result = setup.checks(_settings(ready_37), "ja")
    checks = _by_id(result)
    assert checks["anki"]["state"] == "waiting" and "Anki isn't open" in checks["anki"]["say"]
    assert checks["anki"]["do"] == "Open Anki"
    assert checks["anki_profile"]["state"] == "not-checked"
    assert not result["ready"]
    assert "anki_profile" not in setup.read_record(), "no profile is recorded until Anki answers"


def test_anki_closed_with_open_anki_for_me_on_says_surasura_opens_it(monkeypatch, ready_37):
    StandInAnki(monkeypatch, open_=False)
    checks = _by_id(setup.checks(_settings(ready_37, connect_open_anki=True), "ja"))
    assert "Surasura opens it when you open Surasura" in checks["anki"]["say"]


def test_anki_busy_is_never_taken_for_closed(monkeypatch, ready_37):
    StandInAnki(monkeypatch, open_=False, timed_out=True)
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki"]
    assert check["state"] == "waiting" and "busy" in check["say"]


def test_an_add_on_on_port_8765_missing_an_action_is_named(monkeypatch, ready_37):
    # E5: AnkiConnect Extended or a fork — Connect never guesses
    anki = StandInAnki(monkeypatch, missing=["getActiveProfile"])
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki"]
    assert check["state"] == "needs-you" and '"getActiveProfile"' in check["say"]
    assert "2055492159" in check["do"]
    assert ("probe", setup.ANKI_ACTIONS) in anki.asked, "every action Connect needs is asked for by name"


def test_anki_open_on_another_profile_waits_and_names_both(monkeypatch, ready_37):
    anki = StandInAnki(monkeypatch, profile="日本語")
    setup.checks(_settings(ready_37), "ja")                       # set up with 日本語
    anki.profile = "DevTest"
    result = setup.checks(_settings(ready_37), "ja")
    check = _by_id(result)["anki_profile"]
    assert check["state"] == "waiting" and '"DevTest"' in check["say"] and '"日本語"' in check["say"]
    assert not result["ready"], "no card lands in the wrong profile (E3)"
    assert setup.anki_profile() == "日本語", "a look never moves Connect to another profile"


def test_use_the_open_profile_moves_connect_to_it(monkeypatch, ready_37):
    anki = StandInAnki(monkeypatch, profile="日本語")
    setup.checks(_settings(ready_37), "ja")
    anki.profile = "中文学习"
    result = setup.checks(_settings(ready_37), "ja", use_open_profile=True)
    assert _by_id(result)["anki_profile"]["state"] == "ok" and setup.anki_profile() == "中文学习"


def test_the_checks_only_read_anki(monkeypatch, ready_37):
    anki = StandInAnki(monkeypatch)
    setup.checks(_settings(ready_37), "ja")
    assert {action for action, _ in anki.asked} <= {"probe", "getActiveProfile"}


def test_with_anki_switched_off_for_the_run_anki_is_never_asked(monkeypatch, ready_37):
    anki = StandInAnki(monkeypatch)
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki"]
    assert check["state"] == "not-checked" and anki.asked == []


# --------------------------------------------------------------------------- #
# The first known-words sync (S3, E28)
# --------------------------------------------------------------------------- #
def test_known_words_never_read_from_anki_needs_you_first(monkeypatch, fake_miner):
    StandInAnki(monkeypatch)
    check = _by_id(setup.checks(_settings(fake_miner), "ja"))["first_known_sync"]
    assert check["state"] == "needs-you" and check["blocks"]
    assert check["do"] == "Sync once from Surasura's Anki window first"


def test_no_decks_chosen_is_named_before_the_first_sync(monkeypatch, fake_miner):
    StandInAnki(monkeypatch)
    check = _by_id(setup.checks(_settings(fake_miner, anki_sync_decks={}), "zh"))["first_known_sync"]
    assert check["state"] == "needs-you" and "choose your decks" in check["do"]


def test_a_known_words_sync_done_is_ok_for_its_own_language_only(monkeypatch, fake_miner):
    StandInAnki(monkeypatch)
    _synced_once("ja")
    assert _by_id(setup.checks(_settings(fake_miner), "ja"))["first_known_sync"]["state"] == "ok"
    assert _by_id(setup.checks(_settings(fake_miner), "zh"))["first_known_sync"]["state"] == "needs-you"


# --------------------------------------------------------------------------- #
# Anki Miner (S4–S7, E7, E9–E12, W1)
# --------------------------------------------------------------------------- #
def test_anki_miner_not_installed_is_named_with_install_and_the_rest_waits_for_it(monkeypatch):
    StandInAnki(monkeypatch)
    _synced_once()
    checks = _by_id(setup.checks(_settings(), "ja"))
    assert checks["anki_miner"]["state"] == "needs-you" and "Install Anki Miner" in checks["anki_miner"]["do"]
    assert setup.RELEASES in checks["anki_miner"]["do"]
    assert all(checks[i]["state"] == "not-checked" for i in ("anki_miner_version", "anki_miner_profile",
                                                             "anki_miner_setup"))


def test_an_anki_miner_setting_that_points_nowhere_names_the_path(monkeypatch, tmp_path):
    StandInAnki(monkeypatch)
    gone = str(tmp_path / "ツール" / "AnkiMiner.exe")
    check = _by_id(setup.checks(_settings(connect_anki_miner_path=gone), "ja"))["anki_miner"]
    assert check["state"] == "needs-you" and gone in check["say"]


def test_a_build_its_installer_says_is_older_than_35_is_never_run(monkeypatch, fake_miner):
    # research/01:228 — a build without --api opens its window: the uninstall key's version is read first
    StandInAnki(monkeypatch)
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.4.2")
    monkeypatch.setattr(anki_miner, "find", lambda settings: fake_miner.path)     # found by its installer
    check = _by_id(setup.checks(_settings(), "ja"))["anki_miner_version"]
    assert check["state"] == "needs-you" and "3.4.2" in check["say"] and "Update Anki Miner" in check["do"]
    assert fake_miner.calls() == [], "never started"


@pytest.mark.parametrize("plan, words", [
    ({"app": "3.4.0"}, "too old"),                                   # it answered, but before the API Connect uses
    ({"schema": 2}, "isn't one Surasura has been checked with"),     # E12
])
def test_a_version_connect_cant_use_needs_you(monkeypatch, fake_miner, plan, words):
    StandInAnki(monkeypatch)
    fake_miner.plan(**plan)
    check = _by_id(setup.checks(_settings(fake_miner), "ja"))["anki_miner_version"]
    assert check["state"] == "needs-you" and words in check["say"]
    assert fake_miner.commands() == ["version"], "nothing else is asked of a version Connect can't use"


def test_windows_security_blocking_anki_miner_is_named_never_retried(monkeypatch, fake_miner):
    import subprocess
    StandInAnki(monkeypatch)

    def blocked(*a, **k):
        error = OSError("Operation did not complete successfully because the file contains a virus")
        error.winerror = anki_miner.WINERROR_VIRUS
        raise error
    monkeypatch.setattr(subprocess, "Popen", blocked)
    check = _by_id(setup.checks(_settings(fake_miner), "ja"))["anki_miner_version"]
    assert check["state"] == "needs-you" and "Windows Security" in check["say"]
    assert check["do"] == "Windows Security → Protection history"


def test_anki_miner_busy_is_a_wait(monkeypatch, fake_miner):
    StandInAnki(monkeypatch)
    fake_miner.plan(replay={"version": {"schema": 1, "command": "version", "ok": False, "error": "BUSY",
                                        "message": "Anki Miner is busy."}})
    assert _by_id(setup.checks(_settings(fake_miner), "ja"))["anki_miner_version"]["state"] == "waiting"


def test_before_37_a_missing_surasura_profile_shows_the_two_guided_steps(monkeypatch, fake_miner):
    StandInAnki(monkeypatch)
    fake_miner.plan(app="3.6.0", profiles=[{"id": "default", "name": "Default", "active": True}])
    check = _by_id(setup.checks(_settings(fake_miner), "ja"))["anki_miner_profile"]
    assert check["state"] == "needs-you" and "Manage profiles" in check["do"]
    assert anki_miner.whitelist_path("ja") in check["do"], "the file to choose, with its real path"


def test_a_profile_the_user_named_that_anki_miner_lacks_needs_you_whatever_the_version(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    check = _by_id(setup.checks(_settings(ready_37, connect_anki_miner_profile="字幕"), "ja"))["anki_miner_profile"]
    assert check["state"] == "needs-you" and '"字幕"' in check["say"]


def test_a_surasura_profile_is_used_when_there_is_one(monkeypatch, fake_miner):
    StandInAnki(monkeypatch)
    _synced_once()
    fake_miner.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True},
                                                                 {"id": "p-s", "name": "Surasura"}])
    result = setup.checks(_settings(fake_miner), "ja")
    assert '"Surasura"' in _by_id(result)["anki_miner_profile"]["say"] and result["anki_miner"]["profile"] == "p-s"
    check_call = [c["argv"] for c in fake_miner.calls() if c["argv"][1] == "check"][0]
    assert check_call[-2:] == ["--profile", "p-s"], "Anki Miner's own setup is checked in the profile Connect uses"


@pytest.mark.parametrize("language, items, named", [
    ("ja", [{"name": "dictionary", "ok": False, "message": "No dictionary is installed."},
            {"name": "anki", "ok": True, "message": None}], "dictionary: No dictionary is installed."),
    ("zh", [{"name": "language-pack", "ok": False, "message": "The Chinese language pack isn't installed."}],
     "The Chinese language pack isn't installed."),
])
def test_anki_miners_own_setup_unfinished_names_what_it_says(monkeypatch, ready_37, language, items, named):
    StandInAnki(monkeypatch)
    _synced_once(language)
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": items})
    check = _by_id(setup.checks(_settings(ready_37), language))["anki_miner_setup"]
    assert check["state"] == "needs-you" and named in check["say"]
    assert check["do"] == "Open Anki Miner and finish its setup"
    asked = [c["argv"] for c in ready_37.calls() if c["argv"][1] == "check"][0]
    assert asked[2:4] == ["--language", language]


def test_anki_miner_not_reaching_anki_while_anki_is_closed_is_only_a_wait(monkeypatch, ready_37):
    StandInAnki(monkeypatch, open_=False)
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": [{"name": "anki", "ok": False, "message": "Anki isn't running."}]})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["state"] == "waiting"


def test_nothing_of_anki_miners_is_ever_written(monkeypatch, ready_37):
    # Its settings and profiles are its own (01-scope): only `version`, `profiles` and `check` are asked
    StandInAnki(monkeypatch)
    setup.checks(_settings(ready_37), "ja")
    setup.checks(_settings(ready_37), "zh")
    assert set(ready_37.commands()) == {"version", "profiles", "check"}


# --------------------------------------------------------------------------- #
# Junban, Backfill (S8), AnkiWeb, Open Anki for me
# --------------------------------------------------------------------------- #
def test_junban_or_backfill_absent_is_named_and_skipped_never_a_block(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    monkeypatch.setattr(setup, "_present", lambda module: False)
    result = setup.checks(_settings(ready_37), "ja")
    checks = _by_id(result)
    assert checks["junban"]["state"] == checks["backfill"]["state"] == "skipped"
    assert "Junban isn't installed" in checks["junban"]["say"] and result["ready"]


def test_ankiweb_says_anki_carries_the_order_up_on_close_and_never_blocks(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["ankiweb"]
    assert check["state"] == "ok" and not check["blocks"]
    assert "Synchronize automatically on profile open/close" in check["say"]


def test_open_anki_for_me_is_checked_only_when_on(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    from app.connect import open_anki
    assert "open_anki" not in _by_id(setup.checks(_settings(ready_37), "ja"))
    monkeypatch.setattr(open_anki, "find", lambda: None)
    result = setup.checks(_settings(ready_37, connect_open_anki=True), "ja")
    check = _by_id(result)["open_anki"]
    assert check["state"] == "needs-you" and not check["blocks"] and result["ready"]
    monkeypatch.setattr(open_anki, "find", lambda: ["anki.exe"])
    assert _by_id(setup.checks(_settings(ready_37, connect_open_anki=True), "ja"))["open_anki"]["state"] == "ok"


def test_every_missing_piece_has_a_sentence_and_an_action(monkeypatch):
    # The ORDER proof: "the setup checks name each missing piece in plain words" — nothing set up at all
    StandInAnki(monkeypatch, open_=False)
    result = setup.checks(_settings(anki_sync_decks={}, connect_open_anki=True), "ja")
    for check in result["checks"]:
        assert check["say"] and check["say"][-1] in ".)", check
        if check["state"] in ("needs-you", "waiting") and check["id"] != "ankiweb":
            assert check["do"], check
        assert "Traceback" not in check["say"] and "Error" not in check["say"]


def test_version_tuples_read_as_anki_miner_writes_them():
    assert setup.version_tuple("3.7.0") == (3, 7, 0) and setup.version_tuple("v3.5.0-rc1") == (3, 5, 0)
    assert setup.version_tuple("") is None and setup.version_tuple("dev") is None
    assert setup._too_old("3.4.9") and not setup._too_old("3.5.0") and not setup._too_old("dev")
