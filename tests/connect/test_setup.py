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
        missing = [a for a in required if a in self.missing]
        # as `anki_connect.probe` answers: not ok whenever an action is missing
        return {"ok": not missing, "version": 6, "missing": missing,
                "error": "This AnkiConnect is missing " + ", ".join(missing) if missing else ""}

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
    monkeypatch.setattr(anki_miner, "_registry_location", lambda: os.path.dirname(fake_miner.path))
    monkeypatch.setattr(anki_miner, "EXE", os.path.basename(fake_miner.path))      # the installer's program
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.4.2")
    # chosen by hand or found by its installer: the installer's version is read first either way
    check = _by_id(setup.checks(_settings(fake_miner), "ja"))["anki_miner_version"]
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
    # marked: updating is the better fix (from 3.7 no profile is needed); the wizard leads with it, in its own words
    assert check.get("update") is True and '"Surasura"' in check["say"]


def test_from_37_no_surasura_profile_means_no_profile_line_and_no_update(monkeypatch, ready_37):
    # 3.7 without a "Surasura" profile: the usual profile is used, so neither the update nor the steps by hand show
    StandInAnki(monkeypatch)
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_profile"]
    assert check["state"] == "ok" and "メイン" in check["say"]
    assert not check.get("update") and "Manage profiles" not in (check.get("do") or "")


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


@pytest.mark.parametrize("language, items, named, ours", [
    ("ja", [{"name": "dictionary", "ok": False, "message": "No dictionary is installed."},
            {"name": "anki", "ok": True, "message": None}], "dictionary: No dictionary is installed.", True),
    ("zh", [{"name": "language_pack", "ok": False, "message": "The Chinese language pack isn't installed."},
            {"name": "resources", "ok": False, "message": "Its frequency list is out of date."}],
     "The Chinese language pack isn't installed.", True),
    # A4M1-2b: the deck is Surasura's to set too (Anki Miner's settings-import), with the dictionaries or alone
    ("ja", [{"name": "dictionary", "ok": False, "message": "No dictionary is installed."},
            {"name": "deck", "ok": False, "message": "no deck chosen"}], "deck: no deck chosen", "both"),
    ("ja", [{"name": "deck", "ok": False, "message": "no deck chosen"}], "deck: no deck chosen", "settings"),
    # what neither verb sets is still Surasura's to finish around, and named (intent keeper IK-A2)
    ("ja", [{"name": "dictionary", "ok": False, "message": "No dictionary is installed."},
            {"name": "ffmpeg", "ok": False, "message": "ffmpeg was not found. Install ffmpeg, or set its location in "
                                                       "Anki Miner's settings."}], "ffmpeg: not found", "some"),
    ("zh", [{"name": "language-pack", "ok": False, "message": "The Chinese language pack isn't installed."}],
     "The Chinese language pack isn't installed.", False),         # an item name Surasura doesn't know: never ours
])
def test_anki_miners_own_setup_unfinished_names_what_it_says(monkeypatch, ready_37, language, items, named, ours):
    """A4M1-2 (lean taken, PROVISIONAL): what Anki Miner's own `setup` installs (its dictionaries, resources, language
    pack) Surasura finishes itself — the check says so and is marked `setup` (the wizard's *Finish its setup*), never
    "open Anki Miner"; anything else keeps naming what Anki Miner says."""
    StandInAnki(monkeypatch)
    _synced_once(language)
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": items})
    check = _by_id(setup.checks(_settings(ready_37), language))["anki_miner_setup"]
    assert check["state"] == "needs-you" and named in check["say"]
    if ours == "some":
        assert check["do"] == setup.SETUP_DO_SOME.format(rest="ffmpeg") and check["setup"] is True
        assert "Open Anki Miner" not in check["do"]
    elif ours == "both":
        assert check["do"] == setup.BOTH_DO and check["setup"] is True and check["items"] == ["deck", "dictionary"]
    elif ours == "settings":
        assert check["do"] == setup.SETTINGS_DO and check["setup"] is True and check["items"] == ["deck"]
    elif ours:
        assert check["do"] == setup.SETUP_DO and check["setup"] is True and "Open Anki Miner" not in check["do"]
    else:       # A5F2: what neither verb sets comes with Anki Miner's installer: Surasura's update, never its window
        assert check["do"] == setup.UPDATE_DO and not check.get("setup") and check["update"] is True
    asked = [c["argv"] for c in ready_37.calls() if c["argv"][1] == "check"][0]
    assert asked[2:4] == ["--language", language]


def test_an_anki_miner_that_names_no_setup_is_never_set_up_by_surasura(monkeypatch, ready_37):
    """A4M1-2: Surasura runs only a verb the Anki Miner names (`features`: Z-11's `setup`)."""
    StandInAnki(monkeypatch)
    _synced_once()
    ready_37.plan(app="3.7.0", features=[f for f in FEATURES_37 if f != "setup"],
                  profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": [{"name": "dictionary", "ok": False, "message": "none"}]})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert not check.get("setup") and check["do"] == setup.UPDATE_DO and check["update"] is True


def test_anki_miner_not_reaching_anki_while_anki_is_closed_is_only_a_wait(monkeypatch, ready_37):
    StandInAnki(monkeypatch, open_=False)
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": [{"name": "anki", "ok": False, "message": "Anki isn't running."}]})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["state"] == "waiting"


# Anki Miner 3.7's own `check` items (3.7.0 cli/api/commands.py), as it answers them
ITEMS_37 = ["anki", "deck", "note_type", "fields", "dictionary", "resources", "language_pack", "ffmpeg", "ffprobe",
            "yt_dlp", "speech_model"]


def _items(failing, message="not ready"):
    return [{"name": n, "ok": n not in failing, "message": message if n in failing else None} for n in ITEMS_37]


def test_what_only_anki_miners_youtube_fetch_needs_never_stops_connect(monkeypatch, ready_37):
    # 3.7 says ready without yt-dlp or a speech model: Connect mines videos only, and trusts that verdict
    StandInAnki(monkeypatch)
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": True, "items": _items({"yt_dlp", "speech_model"})})
    result = setup.checks(_settings(ready_37), "ja")
    assert _by_id(result)["anki_miner_setup"]["state"] == "ok" and result["ready"]


def test_anki_closed_fails_anki_miners_deck_and_fields_too_and_that_is_one_wait(monkeypatch, ready_37):
    StandInAnki(monkeypatch, open_=False)
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": _items({"anki", "deck", "note_type", "fields", "yt_dlp"},
                                                         "Not checked: Anki is not reachable.")})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["state"] == "waiting" and check["do"] == "Open Anki"


def test_anki_closed_and_a_dictionary_missing_names_only_the_dictionary(monkeypatch, ready_37):
    StandInAnki(monkeypatch, open_=False)
    items = _items({"anki", "deck", "note_type", "fields"}, "Not checked: Anki is not reachable.")
    items[4] = {"name": "dictionary", "ok": False, "message": "No dictionary is installed."}
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": items})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["state"] == "needs-you" and "dictionary: No dictionary is installed." in check["say"]
    assert "deck" not in check["say"], "what Anki's being closed explains isn't named as missing"


def test_anki_miner_not_reaching_anki_that_surasura_reaches_has_its_address_set_by_surasura(monkeypatch, ready_37):
    """A5F2: Surasura sets Anki Miner's AnkiConnect address itself (settings-import, Z-3): *Finish its setup*, never
    "check Anki Miner's AnkiConnect address"."""
    StandInAnki(monkeypatch)
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": _items({"anki", "deck", "note_type", "fields"})})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["state"] == "needs-you" and check["say"] == setup.ADDRESS_SAY
    assert check["do"] == setup.ADDRESS_DO and check["setup"] is True and check["items"] == ["anki"]


def test_an_address_anki_miner_cant_set_from_surasura_is_surasuras_update(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    ready_37.plan(app="3.7.0", features=[f for f in FEATURES_37 if f != "settings-import"],
                  profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": _items({"anki", "deck", "note_type", "fields"})})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["say"] == setup.ADDRESS_SAY and check["do"] == setup.UPDATE_DO and check["update"] is True
    assert not check.get("setup") and "Check Anki Miner" not in check["do"]


def test_the_address_is_set_with_the_dictionaries_when_both_are_missing(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    _synced_once()
    items = _items({"anki", "deck", "note_type", "fields"})
    items[4] = {"name": "dictionary", "ok": False, "message": "No dictionary is installed."}
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": items})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["setup"] is True and check["items"] == ["anki", "dictionary"]


def test_a_named_profile_anki_miner_lacks_is_made_by_surasura(monkeypatch, ready_37):
    """A5F2: never "make it in Anki Miner": Surasura makes it (settings-import, Z-3) on *Finish its setup*."""
    StandInAnki(monkeypatch)
    check = _by_id(setup.checks(_settings(ready_37, connect_anki_miner_profile="字幕"), "ja"))["anki_miner_profile"]
    assert check["say"] == setup.PROFILE_SAY.format(name="字幕") and check["do"] == setup.PROFILE_DO
    assert check["setup"] is True and check["make"] == "字幕"
    assert "didn't answer" not in check["say"] and "in Anki Miner" not in check["do"]


def test_a_named_profile_an_anki_miner_without_settings_import_lacks_points_at_surasura(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    ready_37.plan(app="3.7.0", features=[f for f in FEATURES_37 if f != "settings-import"],
                  profiles=[{"id": "p-main", "name": "メイン", "active": True}])
    check = _by_id(setup.checks(_settings(ready_37, connect_anki_miner_profile="字幕"), "ja"))["anki_miner_profile"]
    assert check["do"] == setup.UPDATE_PROFILE_DO and not check.get("setup") and not check.get("make")
    assert check["update"] is True, "its Update button is shown (review): never a pointer at a hidden one"


def test_the_record_forgets_an_anki_miner_that_was_uninstalled(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    setup.checks(_settings(ready_37), "ja")
    assert setup.read_record()["anki_miner"]["app"] == "3.7.0"
    setup.checks(_settings(), "ja")                               # gone: nothing found
    assert setup.read_record()["anki_miner"] is None


def test_a_profile_another_program_chose_meanwhile_is_kept(monkeypatch, ready_37):
    # Two writers of the record: a look that read it before a slow Anki Miner call writes back only what it decided
    anki = StandInAnki(monkeypatch, profile="日本語")
    setup.checks(_settings(ready_37), "ja")
    real_version = anki_miner.version

    def slow_version(path):
        setup.write_record(dict(setup.read_record(), anki_profile="中文学习"))      # `setup --use-anki-profile` elsewhere
        return real_version(path)
    monkeypatch.setattr(anki_miner, "version", slow_version)
    anki.profile = "日本語"
    setup.checks(_settings(ready_37), "ja")
    assert setup.anki_profile() == "中文学习", "the other program's choice survives"


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
    assert setup.version_tuple("3.5") == (3, 5, 0), "two parts are padded, so 3.5 is never too old"
    assert setup.version_tuple("") is None and setup.version_tuple("dev") is None
    assert setup._too_old("3.4.9") and not setup._too_old("3.5.0") and not setup._too_old("3.5")
    assert not setup._too_old("dev")


def test_open_anki_for_me_is_read_only_with_connects_preview_on(monkeypatch, ready_37):
    StandInAnki(monkeypatch, open_=False)
    checks = _by_id(setup.checks(_settings(ready_37, connect_enabled=False, connect_open_anki=True), "ja"))
    assert "open_anki" not in checks and "Surasura opens it" not in checks["anki"]["say"]


# --------------------------------------------------------------------------- #
# The mutant round's gaps (P2.3)
# --------------------------------------------------------------------------- #
def test_anki_busy_leaves_the_profile_check_waiting_to_be_asked(monkeypatch, ready_37):
    """Anki open but too busy to answer in time: it hasn't answered, so the profile check waits to be checked and
    Anki is asked nothing more — never a second question to a busy Anki, never a profile read as missing."""
    anki = StandInAnki(monkeypatch, open_=False, timed_out=True)
    checks = _by_id(setup.checks(_settings(ready_37), "ja"))
    assert checks["anki_profile"]["state"] == "not-checked"
    assert [a for a, _p in anki.asked if a == "getActiveProfile"] == []


def test_with_the_preview_off_use_the_open_profile_moves_nothing(monkeypatch, ready_37):
    """Connect was set up with 日本語; Anki is open on DevTest. With Connect's preview off nothing is kept, so "use the
    open profile" can't move Connect to DevTest: the check still says Connect waits for 日本語, never that cards
    will land in DevTest."""
    setup.write_record({"anki_profile": "日本語"})
    StandInAnki(monkeypatch, profile="DevTest")
    result = setup.checks(_settings(ready_37, connect_enabled=False), "ja", use_open_profile=True)
    assert _by_id(result)["anki_profile"]["state"] == "waiting"
    assert result["anki_profile"] == "日本語" and setup.read_record()["anki_profile"] == "日本語"


def test_a_chinese_known_words_check_reads_the_chinese_decks(monkeypatch, fake_miner):
    """Decks chosen for Chinese only, and a Chinese known-words sync done: the Chinese check is ok. Read through the
    Japanese decks, it would say no decks are chosen."""
    StandInAnki(monkeypatch)
    anki_sync._save_state("zh", {"last_sync": "2026-10-07T08:15:00", "decks": ["中文::挖掘"]})
    check = _by_id(setup.checks(_settings(fake_miner, anki_sync_decks={"zh": ["中文::挖掘"]}), "zh"))["first_known_sync"]
    assert check["state"] == "ok", check


def test_anki_miner_waiting_for_the_anki_writer_is_a_wait_never_needs_you():
    """Another Surasura program holds the Anki writer while Anki Miner is asked (`writer-busy`): a wait with the busy
    text, as plain `busy` is."""
    for kind in ("busy", "writer-busy"):
        check = setup._miner_error("anki_miner_version", anki_miner.AnkiMinerError(kind, "Anki Miner is busy."))
        assert check["state"] == "waiting" and "busy" in check["say"], (kind, check)


def test_junban_without_backfill_names_backfill_as_skipped(monkeypatch):
    """Junban installed but not its Backfill: the Backfill check is skipped, never ok — Connect would otherwise promise
    the パターン and 例文 fields with nothing there to fill them."""
    monkeypatch.setattr(setup, "_present", lambda module: module == "modules.junban.reposition")
    checks = {c["id"]: c for c in setup._modules()}
    assert checks["junban"]["state"] == "ok" and checks["backfill"]["state"] == "skipped"


def test_anki_miners_own_words_that_send_you_to_its_window_are_said_as_surasuras(monkeypatch, ready_37):
    """A5F2: Anki Miner's ffmpeg line says "set its location in Anki Miner's settings": named in Surasura's words,
    the fix its update (its installer brings ffmpeg)."""
    StandInAnki(monkeypatch)
    _synced_once()
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": _items({"ffmpeg", "ffprobe"}, "ffmpeg was not found. Install ffmpeg, "
                                                         "or set its location in Anki Miner's settings.")})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["say"] == "Anki Miner's own setup isn't finished (ffmpeg: not found; ffprobe: not found)."
    assert check["do"] == setup.UPDATE_DO and check["update"] is True and "Anki Miner's settings" not in check["say"]


def test_a_setup_anki_miner_calls_unfinished_without_naming_anything_is_surasuras_update(monkeypatch, ready_37):
    StandInAnki(monkeypatch)
    ready_37.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "p-main", "name": "メイン", "active": True}],
                  check={"ready": False, "items": _items(set())})
    check = _by_id(setup.checks(_settings(ready_37), "ja"))["anki_miner_setup"]
    assert check["say"] == setup.UNSAID_SAY and check["do"] == setup.UPDATE_DO and check["update"] is True
