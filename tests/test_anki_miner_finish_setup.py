"""A4M1-2 and A4M1-3 (alpha 4, leans taken — PROVISIONAL; Sonic 2026-10-27: "I honestly don't want to ever have to
open anki miner. Ever."):

- Surasura finishes Anki Miner's own setup itself (`anki_miner.run_setup` = its `--api setup`, Z-11;
  `services.anki_miner_setup.finish_setup` and its job), never "open Anki Miner and finish its setup";
- an audiobook's or a podcast's part waits for Anki Miner as a book does (`connect.library.waits_for`, one rule;
  `anki_miner.mines` per kind).

What a wrong answer would cost: Surasura running Anki Miner's downloads with its window open or beside Connect's own
run (Anki Miner's lock would refuse, or a window would undo its settings write); a setup that installed only part
called finished (the learner's cards then lack definitions); an audiobook's part asking for a video it can't have
(a *No video* card per part), or a book opening audio before Anki Miner mines it.

No real Anki Miner is run: `anki_miner.api` and the setup checks are stand-ins; Japanese titles are real ones.
"""
import json
import os
import time

import pytest

from app.connect import anki_miner, library, setup
from app.connect import settings_values
from app.services import anki_miner_setup as M

DICTS_JA = M.SAID_DICTS.format(language="Japanese", name="メイン").strip()

MINER = "C:\\Users\\learner\\AppData\\Local\\Programs\\AnkiMiner\\AnkiMiner.exe"


@pytest.fixture(autouse=True)
def no_failed_setup_carried_over():
    """`finish_setup_as_job` remembers a language whose setup didn't finish this session (R2-6): none carried over."""
    M._FAILED.clear()
    yield
    M._FAILED.clear()


# --- anki_miner.run_setup: the verb, its arguments, its verdicts ------------------------------------------------- #
@pytest.fixture
def api(monkeypatch):
    calls = []
    answer = {}

    def fake(path, args, timeout=anki_miner.QUICK_TIMEOUT, on_poll=None, bind=True):
        calls.append({"path": path, "args": list(args), "timeout": timeout, "bind": bind})
        if on_poll is not None:
            on_poll()
        return answer["verdict"]
    monkeypatch.setattr(anki_miner, "api", fake)
    return calls, answer


def _verdict(ok=True, error=None, message=None, pack="installed", resources=(("jmdict", "JMdict", "installed"),)):
    return {"schema": 1, "command": "setup", "ok": ok, "error": error, "message": message,
            "result": {"language": "ja", "profile": "p-main",
                       "language_pack": {"status": pack, "message": None if pack != "failed" else "no space"},
                       "resources": [{"id": i, "kind": "dict", "name": n, "status": s,
                                      "message": "the download broke off" if s == "failed" else None}
                                     for i, n, s in resources]}}


def test_run_setup_asks_anki_miner_for_its_own_setup_in_the_language_and_profile_connect_mines_with(api, tmp_path):
    calls, answer = api
    answer["verdict"] = _verdict()
    progress = tmp_path / "progress.json"
    result = anki_miner.run_setup(MINER, "ja", "p-main", progress)
    assert result["language_pack"]["status"] == "installed"
    assert calls == [{"path": MINER, "args": ["setup", "--language", "ja", "--progress", str(progress),
                                              "--profile", "p-main"], "timeout": anki_miner.SETUP_TIMEOUT,
                      "bind": False}], "never ended with Surasura (review A2-4): it finishes by itself"


def test_run_setup_with_no_profile_uses_anki_miners_current_settings(api, tmp_path):
    calls, answer = api
    answer["verdict"] = _verdict()
    anki_miner.run_setup(MINER, "zh", None, tmp_path / "p.json")
    assert "--profile" not in calls[0]["args"] and calls[0]["args"][:3] == ["setup", "--language", "zh"]


def test_a_setup_that_installed_only_part_is_never_called_finished_and_names_what_failed(api, tmp_path):
    _calls, answer = api
    answer["verdict"] = _verdict(ok=False, resources=(("jmdict", "JMdict", "installed"),
                                                      ("jpdb", "JPDB frequency", "failed")))
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.run_setup(MINER, "ja", None, tmp_path / "p.json")
    assert e.value.kind == "failed" and "JPDB frequency: the download broke off" in e.value.message
    assert "JMdict" not in e.value.message


@pytest.mark.parametrize("error, kind", [("BUSY", "busy"), ("CANCELLED", "cancelled"), ("BAD_ARGUMENTS", "refused")])
def test_an_anki_miner_refusal_keeps_its_kind(api, tmp_path, error, kind):
    """Its window open (BUSY), its own cancel, a language never used in that profile (BAD_ARGUMENTS)."""
    _calls, answer = api
    answer["verdict"] = _verdict(ok=False, error=error, message="Anki Miner's window is open.")
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.run_setup(MINER, "ja", None, tmp_path / "p.json")
    assert e.value.kind == kind


@pytest.mark.parametrize("features, items, ours", [
    (["setup"], {"dictionary"}, True),
    (["setup"], {"dictionary", "resources", "language_pack"}, True),
    (["setup"], {"dictionary", "deck"}, True),            # the dictionaries done, the deck named (IK-A2)
    (["setup"], {"deck", "note_type"}, False),            # a deck is Anki's: never Anki Miner's setup
    (["setup", "settings-import"], {"deck", "note_type"}, True),   # A4M1-2b: Surasura sets them (Z-3)
    (["settings-import"], {"fields"}, True),
    (["settings-import"], {"dictionary", "ffmpeg"}, False),        # its settings-import downloads nothing
    (["setup"], set(), False),                            # nothing missing: nothing to run
    ([], {"dictionary"}, False),                          # an Anki Miner that names no `setup` (before 3.7)
])
def test_can_set_up_only_what_its_setup_installs_and_only_when_it_names_the_verb(features, items, ours):
    assert anki_miner.can_set_up({"features": features}, items) is ours


# --- services.anki_miner_setup.finish_setup and its job ------------------------------------------------------------ #
@pytest.fixture
def world(monkeypatch, tmp_path):
    """The checks Connect's setup makes, the run lock and Anki Miner's `setup` stood in; local data in tmp."""
    state = {"setup": True, "busy": False, "runs": [], "raise": None, "progress": None, "still": False}

    def checks(settings, language, keep=True):
        assert keep is False, "finishing the setup never writes Connect's setup record"
        if state["setup"]:
            check = setup._check("anki_miner_setup", "needs-you", "Anki Miner still needs its dictionaries "
                                 "(dictionary: No dictionary is installed.).", setup.SETUP_DO)
            check["setup"] = True
        else:
            check = setup._check("anki_miner_setup", "ok", "Anki Miner's own setup is finished.")
        return {"checks": [check], "anki_miner": {"path": MINER, "profile": "p-main", "profile_name": "メイン",
                                                  "features": ["setup"]}}

    def run_setup(path, language, profile, progress_path, on_poll=None):
        state["runs"].append((path, language, profile))
        assert os.path.isdir(os.path.dirname(progress_path)), "its --progress folder exists before it starts"
        if state["progress"] is not None:
            with open(progress_path, "w", encoding="utf-8") as f:
                json.dump(state["progress"], f)
            on_poll()
        if state["raise"] is not None:
            raise state["raise"]
        state["setup"] = state["still"]      # what its check says after: set up, unless it still lacks something
        return {}
    monkeypatch.setattr(setup, "checks", checks)
    monkeypatch.setattr(anki_miner, "run_setup", run_setup)
    # the language already mined in that profile, its deck and note type right: nothing for settings-import (A4M1-2b)
    monkeypatch.setattr(anki_miner, "settings_export", lambda path, language, out, profile=None: {"configured": True})
    monkeypatch.setattr(M, "_busy", lambda: state["busy"])
    from app import path_utils
    monkeypatch.setattr(path_utils, "get_local_data_path", lambda: str(tmp_path / "local"))
    state["staging"] = tmp_path / "local" / M.SETUP_STAGING
    return state


def test_finish_setup_runs_anki_miners_setup_in_the_profile_connect_uses_and_cleans_its_progress_file(world):
    world["progress"] = {"schema": 1, "item": "jmdict", "stage": 2, "stages": 4, "done": 10, "total": 100}
    seen = []
    # A5F4: where its setup switched the dictionaries on is said (Z-11 writes only them, into that profile)
    assert M.finish_setup({}, "ja", lambda *a: seen.append(a)) == (M.SET_UP, DICTS_JA)
    assert world["runs"] == [(MINER, "ja", "p-main")]
    assert seen == [(2, 4, "jmdict")]
    assert not world["staging"].exists(), "its progress file is gone after"


def test_finish_setup_waits_while_anki_miner_or_connect_runs_and_runs_nothing(world):
    world["busy"] = True
    assert M.finish_setup({}, "ja") == (M.BUSY, None)
    assert world["runs"] == []


def test_finish_setup_runs_nothing_when_its_check_no_longer_asks_for_it(world):
    """Set up meanwhile (its own window, an earlier press): the check finds nothing its setup installs."""
    world["setup"] = False
    assert M.finish_setup({}, "ja") == ("ready", None)
    assert world["runs"] == []


def test_a_setup_that_failed_says_anki_miners_words_and_its_window_open_is_busy(world):
    world["raise"] = anki_miner.AnkiMinerError("failed", "Anki Miner's setup didn't finish — JMdict: no space")
    assert M.finish_setup({}, "ja") == (M.SETUP_FAILED, "Anki Miner's setup didn't finish — JMdict: no space")
    assert not world["staging"].exists()
    world["raise"] = anki_miner.AnkiMinerError("busy", "Anki Miner's window is open.")
    assert M.finish_setup({}, "ja") == (M.BUSY, None)


def test_a_setup_whose_check_still_asks_after_is_never_called_finished(world):
    """Review A2-3: Anki Miner's setup ran but its check still lacks something (a resource you imported yourself,
    which its setup never reinstalls): named, never "finished" — the wizard then stops offering it (it would loop)."""
    world["still"] = True
    result, detail = M.finish_setup({}, "ja")
    assert result == M.SETUP_FAILED and "Anki Miner still needs its dictionaries" in detail


def test_dictionaries_in_with_a_deck_still_to_choose_is_said_as_such_never_finished(world, monkeypatch):
    """Round 2 R2-7: the mixed case — its setup put the dictionaries in, its check still names a deck: the rest is
    named ("rest"), never "Anki Miner's setup is finished"."""
    real = setup.checks

    def checks(settings, language, keep=True):
        out = real(settings, language, keep)
        if world["runs"]:
            out["checks"] = [setup._check("anki_miner_setup", "needs-you", "Anki Miner's own setup isn't finished "
                                          "(deck: no deck chosen).", setup.SETTINGS_DO)]
        return out
    monkeypatch.setattr(setup, "checks", checks)
    assert M.finish_setup({}, "ja") == (M.SET_UP_REST, "Anki Miner's own setup isn't finished (deck: no deck chosen). "
                                        + DICTS_JA)


def test_a_setup_that_didnt_finish_is_not_offered_again_this_session(world, monkeypatch):
    """Round 2 R2-6: once a setup ran and didn't finish, the page's look no longer offers it this session (any wizard,
    Settings' too) and says where it can be finished instead."""
    from app.services.jobs import JobRegistry
    world["raise"] = anki_miner.AnkiMinerError("failed", "Anki Miner's setup didn't finish — JMdict: no space")
    M.finish_setup_as_job(JobRegistry(), {}, "ja")
    check = setup._check("anki_miner_setup", "needs-you", "Anki Miner still needs its dictionaries.", setup.SETUP_DO)
    check["setup"] = True
    monkeypatch.setattr(setup, "checks", lambda settings, language, keep=True: {
        "checks": [setup._check("anki_miner", "ok", "Anki Miner is installed."), check],
        "anki_miner": {"path": MINER, "app": "3.10.1"}})
    fix = M.look({}, "ja")["fix"]
    assert fix["setup"] is False and fix["do"] == M.SETUP_DO_FAILED
    assert M.look({}, "zh")["fix"]["setup"] is True, "another language is offered as before"


def test_a_language_the_profile_never_mined_is_refused_in_plain_words(world):
    """Review A2-5: Anki Miner refuses a language its profile never used (BAD_ARGUMENTS, kind `refused`): said in
    plain words — never its command-line hint about settings-import."""
    world["raise"] = anki_miner.AnkiMinerError("refused", "'zh' has never been used in the active profile. Run setup "
                                               "on a profile that mines 'zh', e.g. one made with settings-import …")
    result, detail = M.finish_setup({}, "zh")
    assert (result, detail) == (M.SETUP_FAILED, M.SETUP_REFUSED) and "settings-import" not in detail


def test_one_setup_at_a_time_and_never_beside_an_install(world):
    assert M._ONE_INSTALL.acquire(blocking=False)
    try:
        assert M.finish_setup({}, "ja") == (M.BUSY, None)
    finally:
        M._ONE_INSTALL.release()
    assert world["runs"] == []


def test_the_setup_is_a_job_with_no_cancel_that_the_quit_leaves_to_finish(world):
    """The bottom bar lists it while it runs, with its stage; it can't be stopped part-way (Anki Miner's index), and
    Anki Miner finishes it by itself whenever Surasura quits (review A2-4): the quit neither waits nor cancels."""
    from app.services.jobs import JobRegistry
    registry = JobRegistry()
    world["progress"] = {"schema": 1, "item": "jmdict", "stage": 1, "stages": 3, "done": 0, "total": 0}
    live = []
    answer = M.finish_setup_as_job(registry, {}, "ja", lambda *a: live.extend(registry.live(M.SETUP_JOB_KIND)))
    assert answer == (M.SET_UP, DICTS_JA)
    assert [(j.label, j.on_quit) for j in live] == [(M.SETUP_JOB_LABEL, "detach")], "listed while it runs"
    assert not live[0].can_cancel
    ended = [j for j in registry.snapshot() if j.kind == M.SETUP_JOB_KIND]
    assert len(ended) == 1 and ended[0].state == "done" and registry.live(M.SETUP_JOB_KIND) == ()


def test_a_failed_setup_job_ends_failed_with_anki_miners_words(world):
    from app.services.jobs import JobRegistry
    registry = JobRegistry()
    world["raise"] = anki_miner.AnkiMinerError("failed", "Anki Miner's setup didn't finish — JMdict: no space")
    M.finish_setup_as_job(registry, {}, "ja")
    ended = [j for j in registry.snapshot() if j.kind == M.SETUP_JOB_KIND][0]
    assert ended.state != "done" and "JMdict: no space" in (ended.message or "")


def test_the_setup_kind_is_on_the_mining_circle_and_conflicts_with_nothing_but_itself():
    from app.services import jobs, phase
    assert jobs.RESOURCES[M.SETUP_JOB_KIND] == set() and phase.KINDS[M.SETUP_JOB_KIND] == phase.MINER


def test_the_settings_card_offers_finish_its_setup_only_when_its_check_is_ours():
    def result(ours):
        check = setup._check("anki_miner_setup", "needs-you", "Anki Miner still needs its dictionaries.", setup.SETUP_DO)
        if ours:
            check["setup"] = True
        return {"checks": [setup._check("anki_miner", "ok", "Anki Miner is installed."),
                           setup._check("anki_miner_version", "ok", "Anki Miner 3.10.1 answers Surasura."),
                           setup._check("anki_miner_profile", "ok", "Connect makes cards with Anki Miner's current "
                                        "settings."), check],
                "anki_miner": {"path": MINER, "app": "3.10.1"}}
    assert settings_values.card_state(result(True))["can_set_up"] is True
    assert settings_values.card_state(result(False))["can_set_up"] is False


# --- A4M1-3: one rule for what Anki Miner can't mine yet ------------------------------------------------------------- #
@pytest.mark.parametrize("item, media, kind", [
    ({"rel_path": "白銀の書庫番/白銀の書庫番 01.epub", "source_type": "epub"}, "lightnovel", "books"),
    ({"rel_path": "草枕.txt", "source_type": None}, "text", "books"),
    ({"rel_path": "銀河鉄道の夜 朗読/01.srt", "source_type": "subtitle"}, "audiobook", "audio"),
    ({"rel_path": "ゆる言語学ラジオ/第1回.srt", "source_type": "subtitle"}, "podcast", "audio"),
    ({"rel_path": "ぼっち・ざ・ろっく！/01.srt", "source_type": "subtitle"}, "anime", None),
    ({"rel_path": "ぼっち・ざ・ろっく！/01.srt", "source_type": "subtitle"}, None, None),
    ({"rel_path": "ゆる言語学ラジオ/第1回.epub", "source_type": "epub"}, "podcast", "books"),   # its file first
    ({}, "audiobook", None),
])
def test_waits_for_reads_a_books_file_type_and_an_audio_titles_type(item, media, kind):
    assert library.waits_for(item, media) == kind


def test_neither_kind_is_mined_by_this_surasura_whatever_anki_miner_names():
    """Until a Surasura knows how to send books (Z-9) or audio (Z-16), both wait — even with an Anki Miner that names
    them; once it knows one, only the Anki Miner that names it mines it, and one kind never opens the other."""
    named = {"features": ["reading", "audio-episodes"]}
    assert not anki_miner.mines("books") and not anki_miner.mines("audio", named)


def test_a_kind_opens_only_with_its_own_ask(monkeypatch):
    monkeypatch.setitem(anki_miner.FEATURES, anki_miner.AUDIO, "Z-16")
    assert anki_miner.mines("audio") and anki_miner.mines("audio", {"features": ["audio-episodes"]})
    assert not anki_miner.mines("audio", {"features": ["reading"]})
    assert not anki_miner.mines("books", {"features": ["reading", "audio-episodes"]}), "books still unknown here"


# --- A5F1: a long download that writes no progress still reads as "finishing its setup" ------------------------------ #
def test_run_setup_touches_its_folder_every_poll_so_a_quiet_download_is_never_read_as_close_anki_miner(
        api, tmp_path, monkeypatch):
    """`setting_up` reads the setup's folder and progress file as fresh for SETUP_FRESH_S: a single download writing
    nothing for longer made a Connect run told BUSY say "close Anki Miner". The folder is touched each poll."""
    from app import path_utils
    _calls, answer = api
    answer["verdict"] = _verdict()
    monkeypatch.setattr(path_utils, "get_local_data_path", lambda: str(tmp_path))
    folder = tmp_path / anki_miner.SETUP_STAGING
    folder.mkdir()
    stale = time.time() - anki_miner.SETUP_FRESH_S - 60       # an hour-long download's quiet stretch
    os.utime(folder, (stale, stale))
    assert anki_miner.setting_up() is False, "before the heartbeat: read as not running"
    polled = []
    anki_miner.run_setup(MINER, "ja", None, folder / "progress.json", on_poll=lambda: polled.append(1))
    assert polled == [1], "the caller's own poll still runs"
    assert anki_miner.setting_up() is True and os.stat(folder).st_mtime > stale


def test_a_heartbeat_into_a_folder_already_removed_never_raises(api, tmp_path):
    _calls, answer = api
    answer["verdict"] = _verdict()
    anki_miner.run_setup(MINER, "ja", None, tmp_path / "gone" / "progress.json")


# --- A5F2: the card's state names what Surasura sets itself and what only an update brings -------------------------- #
def test_the_card_offers_finish_for_a_profile_surasura_makes_and_the_steps_only_before_37():
    found = {"anki_miner": {"path": MINER, "app": "3.10.1"}}
    made = {"id": "anki_miner_profile", "state": "needs-you", "setup": True, "make": "字幕", "say": "no 字幕"}
    state = settings_values.card_state(dict(found, checks=[{"id": "anki_miner", "state": "ok"}, made]))
    assert state["can_set_up"] is True and state["steps"] is False and state["update"] is False
    old = {"id": "anki_miner_profile", "state": "needs-you", "update": True, "say": "no Surasura"}
    state = settings_values.card_state(dict(found, checks=[{"id": "anki_miner", "state": "ok"}, old]))
    assert state["steps"] is True and state["update"] is True and state["can_set_up"] is False
