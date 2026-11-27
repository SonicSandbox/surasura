"""AM-START (Anki Miner's start-up cost, 2026-11-27): every Anki Miner `--api` call costs ~1.2 s before it does
anything (its whole mining stack and its window's module imported: J-CLIP 2), and the window's flows asked it again
for answers Surasura already had.

DSA-CONNECT 2 keeps Anki Miner's `version` and `profiles` answers on disk (`anki_miner.kept_look_ups`: keyed on its
program, its home, the installer's version and its settings files' stamp; dropped by Surasura's own writes), but only
Connect's run read them. Counted at the base on this PC's Anki Miner 3.13 (the lane's own home): setup's page 5 and
Settings › Anki & mining started `version` + `profiles` + `check` at every look, *Add sound* `version` + `profiles` +
`settings-export` before its `media`, *Finish its setup* `profiles` again right after its look read it, and the
subtitle-track and no-subtitle looks two starts per process. Every one of them now reads the kept pair (one helper,
`anki_miner.look_ups`), and every fresh read keeps it for the next reader. Never a stale answer: the invalidations
DSA-CONNECT 2 named hold for each reader — tested here for the profile made in Anki Miner's window and its update.

Against the fake Anki Miner (its call log counts the starts); Anki is closed (a stand-in that never answers), so
`check` still says what it says. Japanese and Chinese settings alike.
"""
import json
import os
import shutil

import pytest

from app import anki_connect
from app.cli import verbs
from app.connect import anki_miner, setup
from tests import cli_helpers as h
from tests.connect.fake_anki_miner import FEATURES_37, LAPIS_EXPORT
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

LANGS = ["ja", "zh"]
DECKS = {"ja": ["日本語::Mining"], "zh": ["中文::挖掘"]}


def _home(profiles=("default", "p-surasura")):
    """Anki Miner's home as 3.9+ keeps it: gui_config.json naming the active profile, one file a named profile."""
    home = os.environ["ANKI_MINER_HOME"]
    os.makedirs(os.path.join(home, "profiles"), exist_ok=True)
    with open(os.path.join(home, "gui_config.json"), "w", encoding="utf-8") as f:
        json.dump({"active_profile_id": profiles[0], "anki_note_type": "Lapis"}, f)
    for name in profiles:
        with open(os.path.join(home, "profiles", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump({"name": name.title()}, f)


@pytest.fixture
def miner(fake_miner, tmp_path, monkeypatch):
    """The fake Anki Miner 3.7 as a program file of the test's own (so a test can replace it, as an update does);
    Anki closed (every question refused, as a closed Anki's would be)."""
    _home()
    path = str(tmp_path / "AnkiMiner.py")
    shutil.copy(fake_miner.path, path)
    fake_miner.path = path
    fake_miner.plan(app="3.7.0", features=FEATURES_37 + ["transcribe", "inspect", "tracks"],
                    export=dict(LAPIS_EXPORT, app_version="3.7.0"))
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)

    def closed(*_a, **_k):
        raise anki_connect.AnkiError("closed", kind="offline")
    monkeypatch.setattr(anki_connect, "probe", lambda *a, **k: {"ok": False, "version": None, "missing": [],
                                                                  "error": "closed", "timed_out": False})
    monkeypatch.setattr(anki_connect, "invoke", closed)
    return fake_miner


def _settings(miner, lang):
    return {"connect_enabled": True, "target_language": lang, "anki_connect_url": "http://127.0.0.1:8765",
            "anki_sync_decks": DECKS, "connect_anki_miner_path": miner.path}


def _look(miner, lang):
    """Setup's page 5 / Settings › Anki & mining: `setup.checks` (as `anki_miner_setup.look` and `_miner_look` ask)."""
    return setup.checks(_settings(miner, lang), lang, keep=False)


def _miner_checks(result):
    return [c for c in result["checks"] if c["id"].startswith("anki_miner")]


# --- setup's look and Settings' open --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_setups_look_again_starts_only_check_when_anki_miner_is_as_it_was(miner, lang):
    # why: page 5's *entered* and *Check again*, and Settings › Anki & mining at every open, started `version` +
    # `profiles` + `check` (~3.6 s the learner waits on the page's dots); the first two answer for files unchanged
    first = _look(miner, lang)
    assert miner.commands() == ["version", "profiles", "check"]
    again = _look(miner, lang)
    assert miner.commands() == ["version", "profiles", "check", "check"], "one start: `check` (Anki's state)"
    assert _miner_checks(again) == _miner_checks(first), "the same states and words as a look that reads all three"
    assert again["anki_miner"] == first["anki_miner"]


@pytest.mark.parametrize("lang", LANGS)
def test_a_connect_run_after_setups_look_starts_only_its_export(miner, lang):
    # why: setup's look reads what a Connect run's first pick reads: kept by one, answered for the other
    _look(miner, lang)
    h.write_settings(target_language=lang, connect_anki_miner_path=miner.path)
    from app.connect import runner
    steps = runner.Steps(verbs.settings())
    verbs._anki_miner_setup(steps.loaded, lang, steps.run_dir({"id": 1}), held=steps._anki_miner_held(lang))
    assert miner.commands() == ["version", "profiles", "check", "settings-export"]


@pytest.mark.parametrize("lang", LANGS)
def test_a_profile_made_in_anki_miners_window_between_two_looks_is_read_again(miner, lang):
    # why: the learner makes Connect's profile in Anki Miner's own window, then presses *Check again*: a kept
    # `profiles` would still say it is missing. Anki Miner writes the new profile's file: the stamp moved
    miner.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "default", "name": "Default", "active": True}],
               export=dict(LAPIS_EXPORT, app_version="3.7.0"))
    _home(profiles=("default",))
    _look(miner, lang)
    miner.plan(app="3.7.0", features=FEATURES_37, profiles=[{"id": "default", "name": "Default", "active": True},
                                                            {"id": "p-surasura", "name": "Surasura"}],
               export=dict(LAPIS_EXPORT, app_version="3.7.0"))
    _home(profiles=("default", "p-surasura"))
    again = _look(miner, lang)
    assert miner.commands() == ["version", "profiles", "check"] * 2
    assert again["anki_miner"]["profile"] == "p-surasura", "the profile made in its window is the one Connect uses"


@pytest.mark.parametrize("lang", LANGS)
def test_an_anki_miner_update_between_two_looks_is_read_again(miner, lang):
    # why: an update replaces its program: a kept `version` would name the old build and its old features
    _look(miner, lang)
    miner.plan(app="3.13.0", features=FEATURES_37, export=dict(LAPIS_EXPORT, app_version="3.13.0"))
    with open(miner.path, "a", encoding="utf-8") as f:
        f.write("\n# 3.13.0\n")                                 # the program file replaced: its size moved
    again = _look(miner, lang)
    assert miner.commands() == ["version", "profiles", "check"] * 2
    assert again["anki_miner"]["app"] == "3.13.0"


@pytest.mark.parametrize("lang", LANGS)
def test_with_connect_off_a_look_keeps_nothing_yet_reads_a_pair_kept_while_it_was_on(miner, lang):
    # why: with Connect switched off nothing of Connect's is written (`setup.checks`' rule, 2.5's) — the pair isn't
    # kept by setup's or Settings' look then; one kept while it was on still answers (a read writes nothing)
    off = dict(_settings(miner, lang), connect_enabled=False)
    setup.checks(off, lang, keep=False)
    assert not os.path.exists(anki_miner._kept_path()), "nothing of Connect's written while it is off"
    _look(miner, lang)
    setup.checks(off, lang, keep=False)
    assert miner.commands() == ["version", "profiles", "check"] * 2 + ["check"]


# --- *Add sound* ----------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_add_sound_starts_only_the_export_before_its_cut_once_the_answers_are_kept(miner, monkeypatch, lang):
    # why: *Add sound* (`add_audio._add`) read Anki Miner with no run set of its own: `version` + `profiles` +
    # `settings-export` at every press (~3.6 s before the first clip). The first press keeps the pair; a press after it
    # (or after a look or a Connect run) starts the export alone (it may hold a key: never kept on disk). The press's
    # plan is a stand-in that finds nothing to cut, so the starts counted are its look-ups alone
    from app.connect import add_audio
    seen = []
    monkeypatch.setattr(add_audio, "plan", lambda anki, steps, language, book, mapping: seen.append(mapping) or {
        "title": "杜子春", "can": {}, "unheard": [], "has_audio": [], "gone": [], "lined": True,
        "field": "SentenceAudio"})
    book = os.path.join(os.path.dirname(__file__), "..", "Test Resources", "ja", "books", "toshisyun_book.txt")
    s = _settings(miner, lang)
    add_audio._add(s, lang, book, True, None, None)
    assert miner.commands() == ["version", "profiles", "settings-export"]
    add_audio._add(s, lang, book, True, None, None)
    assert miner.commands() == ["version", "profiles", "settings-export", "settings-export"]
    assert dict(seen[1].fields) == dict(seen[0].fields), "the same fields as a press that reads all three"
    assert not os.listdir(os.path.join(verbs._connect_folder(), "add-audio")), "each press's run folder removed"


# --- Card sound's audiobook step (AM-START 2) ------------------------------------------------------------------ #
@pytest.fixture
def press(miner, monkeypatch, tmp_path):
    """*Add sound*'s press as `card_sound.act` makes it: `_mapping` (the press's set, `_HELD`), then the audiobook
    cards' cut (`_cut_book`) in the same run folder. The cut itself is a stand-in, so the starts counted are the
    look-ups alone; -> the profile each cut was handed."""
    from app.connect import add_audio, card_sound
    monkeypatch.setattr(card_sound, "_HELD", {})                # (a process's set: none held before the test)
    cut_with = []
    monkeypatch.setattr(add_audio, "cut", lambda miner_path, l, profile, can, run_dir: cut_with.append(profile) or {})

    def go(lang, settings=None):
        s = settings or _settings(miner, lang)
        run_dir, mapping = card_sound._mapping(s, lang)
        card_sound._cut_book(s, lang)(lang, {101: object()}, run_dir)
        shutil.rmtree(run_dir, ignore_errors=True)
        return mapping
    go.cut_with = cut_with
    return go


@pytest.mark.parametrize("lang", LANGS)
def test_card_sounds_audiobook_step_starts_nothing_after_its_press_read_anki_miner(miner, press, lang):
    # why: *Add sound*'s audiobook cards (`card_sound._cut_book`, train 98) set Anki Miner up again with no set of their
    # own: `version` + `profiles` + `settings-export` (~3.6 s) right after the press's own `_mapping` had read all three.
    # The cut now takes the press's set (`_HELD`, 15 min, Anki Miner's files' stamp checked): nothing started
    mapping = press(lang)
    assert miner.commands() == ["version", "profiles", "settings-export"], "the press's own read, the cut none"
    assert mapping is not None and press.cut_with == ["p-surasura"], "the profile the press read"


@pytest.mark.parametrize("lang", LANGS)
def test_card_sounds_press_after_setups_look_starts_only_its_export(miner, press, lang):
    # why: setup's look (or Settings' open, a Connect run) kept the pair: the press starts the export alone
    _look(miner, lang)
    press(lang)
    assert miner.commands() == ["version", "profiles", "check", "settings-export"]


@pytest.mark.parametrize("lang", LANGS)
def test_card_sounds_audiobook_step_reads_again_when_anki_miners_profile_moved_meanwhile(miner, press, monkeypatch,
                                                                                         lang):
    # why: never a stale answer — the learner switches Anki Miner's profile in its window between the press's read and
    # the cut: its files' stamp moved, so the cut reads all three again and hands Anki Miner the profile it now names
    from app.connect import card_sound
    real_cut_book = card_sound._cut_book

    def switched_first(settings, language):
        cut = real_cut_book(settings, language)

        def go(l, can, run_dir):
            miner.plan(app="3.7.0", features=FEATURES_37 + ["transcribe", "inspect", "tracks"],
                       profiles=[{"id": "default", "name": "Default", "active": True},
                                 {"id": "p-other", "name": "Other"}],
                       export=dict(LAPIS_EXPORT, app_version="3.7.0"))
            _home(profiles=("default", "p-other", "p-surasura-gone"))
            return cut(l, can, run_dir)
        return go
    monkeypatch.setattr(card_sound, "_cut_book", switched_first)
    press(lang)
    assert miner.commands() == ["version", "profiles", "settings-export"] * 2
    assert press.cut_with == ["default"], "the profile Anki Miner names now (Connect's own gone: its active one)"


# --- *Finish its setup* ---------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_finish_its_setups_write_asks_no_profiles_again_after_its_look(miner, tmp_path, lang):
    # why: `_write_settings` asked `profiles` right after the press's `setup.checks` had read it (one more start)
    from app.services import anki_miner_setup as M
    miner.plan(app="3.7.0", features=FEATURES_37, export=dict(LAPIS_EXPORT, app_version="3.7.0", configured=False))
    found = _look(miner, lang)["anki_miner"]
    before = len(miner.commands())
    folder = str(tmp_path / "staging")
    os.makedirs(folder)                                         # (as `_finish` makes it)
    M._write_settings(found, _settings(miner, lang), lang, set(), folder, None, lambda *a, **k: None)
    assert miner.commands()[before:] == ["settings-export", "settings-import"]


# --- the looks of subtitle tracks and of videos without subtitles ---------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("module", ["tracks", "no_subs"])
def test_a_new_processs_track_and_no_subtitle_looks_start_nothing_once_the_answers_are_kept(miner, monkeypatch,
                                                                                           lang, module):
    # why: each kept its `version` + `profiles` for its own process only: two starts in every new window
    import importlib
    mod = importlib.import_module(f"app.{module}")
    _look(miner, lang)
    monkeypatch.setattr(mod, "_MINERS", {})                    # a new process: nothing in memory
    before = len(miner.commands())
    got = mod._miner(miner.path, _settings(miner, lang)) if module == "tracks" else \
        mod.can_make(_settings(miner, lang), path=miner.path)
    assert got == (miner.path, "p-surasura")
    assert miner.commands()[before:] == [], "answered from the kept pair"


@pytest.mark.parametrize("module", ["tracks", "no_subs"])
def test_an_anki_miner_without_the_feature_is_asked_no_profiles_and_keeps_nothing(miner, monkeypatch, module):
    # why: an Anki Miner that can't look inside a video (before 3.11) or make subtitles has no use for its profiles:
    # one start, `version`, as before — and no pair kept from half a read
    import importlib
    mod = importlib.import_module(f"app.{module}")
    monkeypatch.setattr(mod, "_MINERS", {})                    # (nothing in memory from another test)
    miner.plan(app="3.7.0", features=FEATURES_37, export=dict(LAPIS_EXPORT, app_version="3.7.0"))
    got = mod._miner(miner.path, _settings(miner, "ja")) if module == "tracks" else \
        mod.can_make(_settings(miner, "ja"), path=miner.path)
    assert got is None
    assert miner.commands() == ["version"]
    assert not os.path.exists(anki_miner._kept_path())


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("module", ["tracks", "no_subs"])
def test_with_connect_off_the_track_and_no_subtitle_looks_keep_nothing(miner, monkeypatch, lang, module):
    # why: nothing of Connect's is written while it is off (`setup.checks`' rule) — these looks run with it off too
    import importlib
    mod = importlib.import_module(f"app.{module}")
    monkeypatch.setattr(mod, "_MINERS", {})                    # (nothing in memory from another test)
    off = dict(_settings(miner, lang), connect_enabled=False)
    got = mod._miner(miner.path, off) if module == "tracks" else mod.can_make(off, path=miner.path)
    assert got == (miner.path, "p-surasura")
    assert miner.commands() == ["version", "profiles"]
    assert not os.path.exists(anki_miner._kept_path())


@pytest.mark.parametrize("module", ["tracks", "no_subs"])
def test_a_track_or_no_subtitle_look_with_nothing_kept_keeps_its_read_for_the_next_window(miner, monkeypatch, module):
    # why: the first window after a fresh install reads the pair here before any setup look: kept (Connect on), so the
    # next window's look, and Connect's run, start nothing for it
    import importlib
    mod = importlib.import_module(f"app.{module}")
    monkeypatch.setattr(mod, "_MINERS", {})
    look = (lambda: mod._miner(miner.path, _settings(miner, "zh"))) if module == "tracks" else \
        (lambda: mod.can_make(_settings(miner, "zh"), path=miner.path))
    assert look() == (miner.path, "p-surasura")
    monkeypatch.setattr(mod, "_MINERS", {})                    # the next window
    assert look() == (miner.path, "p-surasura")
    assert miner.commands() == ["version", "profiles"]
