"""DSA-CONNECT 4 (2026-11-25): the speech check rewrote Anki Miner's settings at every mine.

`anki_miner.speech_ready` (the spot-check's "can Anki Miner listen?") asked `check`, and with no speech model set each
of SPEECH_MODELS on Surasura's profile in turn (`settings-import` of `asr_model`), the one the profile already held
included, and asked `check` again after each. On DevTest (no speech model): one import and two `check` starts at every
mine (~1.2 s each), 14 in 14 mines — and each import rewrote the profile, so the look-ups kept from run to run
(DSA-CONNECT 2) never held. Now:

1. The model the profile holds (the settings export the run already read) is never imported: the first `check` asked.
2. Its import of another model is a real change; it re-keys the kept answers to the files' new stamp, only when they
   held just before it and it set `asr_model` alone on an existing profile. Every other write still drops them.
3. The no is kept from run to run while nothing `check` reads for it has changed: the program, Anki Miner's settings
   files, and its speech folders (`asr_models`, `asr_pack`). Never a stale no: a model installed — by Surasura's own
   setup, or in Anki Miner's window — is seen at the next run. Dropped by Surasura's own writes and any failure; a no
   only a busy Anki Miner gave is never kept.

Against the fake Anki Miner (its call log counts the starts; its speech models live in its home's fake-models.json, and
a model installed in its window is put in its `asr_models` folder, as Anki Miner's own installer does). Anki is closed.
"""
import json
import os
import time
import pytest

from app.cli import verbs
from app.connect import anki_miner, lineup, runner
from tests import cli_helpers as h

LANGS = ["ja", "zh"]
PROFILE = "p-surasura"


def _home():
    """Anki Miner's home as 3.9+ keeps it (what `anki_miner.stamp` watches): gui_config.json and one file a profile."""
    home = os.environ["ANKI_MINER_HOME"]
    os.makedirs(os.path.join(home, "profiles"), exist_ok=True)
    with open(os.path.join(home, "gui_config.json"), "w", encoding="utf-8") as f:
        json.dump({"active_profile_id": "default", "anki_note_type": "Lapis"}, f)
    for name in ("default", PROFILE):
        with open(os.path.join(home, "profiles", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump({"name": name}, f)
    return home


def _state():
    path = os.path.join(os.environ["ANKI_MINER_HOME"], "fake-models.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _holds(profile=PROFILE):
    """The model the profile holds, as the run's settings export names it."""
    try:
        state = _state()
    except OSError:
        return "small"
    return state["profiles"].get(profile, state["model"])


def _export(model):
    return {"settings": {"asr_model": model}, "app_version": "3.13.0"}


def _one_run(miner, lang, folder, profile=PROFILE):
    """One Connect run's speech check (a new process: its own `_SPEECH`), handed the export the run read."""
    anki_miner._SPEECH.clear()
    return anki_miner.speech_ready(miner.path, lang, profile, folder, export=_export(_holds(profile)))


def _install_in_its_window(model, where=("asr_models", "faster-whisper-{model}", "model.bin")):
    """A model installed in Anki Miner's own window: its file written in its speech folder (as its installer puts it
    there), and so `check` sees it."""
    home = os.environ["ANKI_MINER_HOME"]
    file = os.path.join(home, *[part.format(model=model) for part in where])
    os.makedirs(os.path.dirname(file), exist_ok=True)
    with open(file, "wb") as f:
        f.write(bytes(64))
    state = _state()
    state["installed"].append(model)
    with open(os.path.join(home, "fake-models.json"), "w", encoding="utf-8") as f:
        json.dump(state, f)


@pytest.fixture
def miner(fake_miner):
    anki_miner._SPEECH.clear()          # (this process's answers: never another test's)
    _home()
    fake_miner.plan(speech={"installed": [], "model": "small"})     # DevTest's: no model, the profile on `small`
    return fake_miner


@pytest.fixture
def folder(tmp_path):
    return str(tmp_path / "speech")


def _imports(miner, since=0):
    return miner.commands()[since:].count("settings-import")


def _checks(miner, since=0):
    return miner.commands()[since:].count("check")


# --- 1. the model the profile holds --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_the_model_the_profile_already_holds_is_never_imported_again(miner, folder, lang):
    # why: the profile held `small`; `check` had just said it can't listen with it, and Surasura set `small` again
    assert _one_run(miner, lang, folder) is False
    assert miner.commands() == ["check", "settings-import", "check"], "only the model it doesn't hold is set"
    assert _holds() == "large-v3"


@pytest.mark.parametrize("lang", LANGS)
def test_with_no_export_every_model_is_set_in_turn_as_before(miner, folder, lang):
    # why: an export read before the files changed (or none) can't say what the profile holds: nothing is skipped
    assert anki_miner.speech_ready(miner.path, lang, PROFILE, folder) is False
    assert _imports(miner) == len(anki_miner.SPEECH_MODELS)


@pytest.mark.parametrize("lang", LANGS)
def test_a_model_the_profile_holds_that_is_installed_is_ready_with_no_import(miner, folder, lang):
    miner.plan(speech={"installed": ["small"], "model": "small"})
    assert _one_run(miner, lang, folder) is True
    assert miner.commands() == ["check"]


@pytest.mark.parametrize("lang", LANGS)
def test_the_other_model_installed_is_found_and_set(miner, folder, lang):
    # why: the skip must never hide the other size (AB-Q2 (a): one it has is used as it is)
    miner.plan(speech={"installed": ["large-v3"], "model": "small"})
    assert _one_run(miner, lang, folder) is True
    assert miner.commands() == ["check", "settings-import", "check"] and _holds() == "large-v3"


# --- 3. the no kept across runs (the counter: 14 mines, as on DevTest) ----------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_fourteen_runs_with_no_model_import_at_most_once_and_check_twice(miner, folder, lang):
    # why: DevTest's 14 mines made 14 imports and 28 `check` starts to say the same no; each import also dropped the
    # look-ups kept for the next run
    for _ in range(14):
        assert _one_run(miner, lang, folder) is False
    assert _imports(miner) <= 1 and _checks(miner) <= 2, miner.commands()
    assert anki_miner.kept_no_speech(miner.path, lang, PROFILE)


@pytest.mark.parametrize("lang", LANGS)
def test_a_model_installed_in_anki_miners_window_after_a_kept_no_is_seen_at_the_next_run(miner, folder, lang):
    # why (never a stale no): the learner installs the model in Anki Miner's own window between two runs
    assert _one_run(miner, lang, folder) is False
    _install_in_its_window("large-v3")
    assert not anki_miner.kept_no_speech(miner.path, lang, PROFILE)
    before = len(miner.commands())
    assert _one_run(miner, lang, folder) is True
    assert _checks(miner, before) == 1


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("where", [("asr_models", "ggml", "ggml-small-q5_1.bin"),
                                   ("asr_pack", "faster_whisper", "__init__.py")],
                         ids=["a-whisper-cpp-model-in-ggml", "the-engine-pack"])
def test_a_file_filled_in_two_levels_into_the_speech_folders_is_seen(miner, folder, lang, where):
    # why: whisper.cpp's models go into asr_models/ggml/ (a folder that may be there already), the engine into
    # asr_pack/<package>/ — a file there written whole in place (its folder's own time unchanged) must not leave a no
    file = os.path.join(os.environ["ANKI_MINER_HOME"], *where)
    os.makedirs(os.path.dirname(file), exist_ok=True)
    open(file, "wb").close()                            # (there, not yet whole)
    assert _one_run(miner, lang, folder) is False
    assert anki_miner.kept_no_speech(miner.path, lang, PROFILE)
    inner = os.stat(os.path.dirname(file)).st_mtime_ns
    _install_in_its_window("small", where=where)
    os.utime(os.path.dirname(file), ns=(inner, inner))  # (the folder's own time as it was: only the file shows it)
    assert not anki_miner.kept_no_speech(miner.path, lang, PROFILE)
    assert _one_run(miner, lang, folder) is True


@pytest.mark.parametrize("lang", LANGS)
def test_a_model_installed_by_surasuras_own_setup_drops_the_kept_no(miner, folder, lang):
    # why: *Finish its setup*'s `setup --speech-model` (a DROPS call) — the no is gone the moment it starts
    assert _one_run(miner, lang, folder) is False
    miner.plan(speech={"installed": [], "model": "small"}, speech_setup="installed")
    lineup.start_speech(miner.path, lang, PROFILE)
    for _ in range(200):
        if not lineup.running(lineup.SPEECH):
            break
        time.sleep(0.05)
    assert lineup.look(lineup.SPEECH)["status"] == lineup.DONE
    assert not os.path.exists(anki_miner._kept_path(anki_miner.NO_SPEECH_KEPT)), "dropped by its setup"
    assert _one_run(miner, lang, folder) is True


@pytest.mark.parametrize("lang", LANGS)
def test_surasuras_own_settings_write_and_any_failure_drop_the_kept_no(miner, folder, lang, tmp_path):
    assert _one_run(miner, lang, folder) is False
    anki_miner.settings_import(miner.path, lang, {}, str(tmp_path / "import"), profile=PROFILE)
    assert not anki_miner.kept_no_speech(miner.path, lang, PROFILE), "Surasura's own write drops it"
    assert _one_run(miner, lang, folder) is False
    assert anki_miner.kept_no_speech(miner.path, lang, PROFILE)
    verbs.drop_anki_miner_held({})
    assert not anki_miner.kept_no_speech(miner.path, lang, PROFILE), "a failure's drop takes it too"


@pytest.mark.parametrize("lang", LANGS)
def test_anki_miners_settings_changed_in_its_window_ask_again(miner, folder, lang):
    # why: `asr_device` (or the model) changed in its window is in its settings files: `check` reads them
    assert _one_run(miner, lang, folder) is False
    path = os.path.join(os.environ["ANKI_MINER_HOME"], "gui_config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"active_profile_id": "default", "anki_note_type": "Lapis", "asr_device": "cpu"}, f)
    assert not anki_miner.kept_no_speech(miner.path, lang, PROFILE)
    before = len(miner.commands())
    assert _one_run(miner, lang, folder) is False
    assert _checks(miner, before) >= 1


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("kind", ["busy", "crashed", "timeout"])
def test_a_no_from_a_busy_or_failed_import_is_never_kept(miner, folder, lang, kind, monkeypatch):
    # why (Michi-T1): a mine beside the check makes the import busy: the other model was never asked about
    def refused(*a, **k):
        raise anki_miner.AnkiMinerError(kind, "Anki Miner is busy")
    monkeypatch.setattr(anki_miner, "settings_import", refused)
    assert _one_run(miner, lang, folder) is False
    assert not anki_miner.kept_no_speech(miner.path, lang, PROFILE)


@pytest.mark.parametrize("lang", LANGS)
def test_a_no_for_the_windows_own_profile_is_kept(miner, folder, lang):
    # why: Anki Miner refuses to change its window's profile; `check` already asked about the model it holds
    miner.plan(speech={"installed": [], "model": "small"}, active_profile="default")
    assert _one_run(miner, lang, folder, profile="default") is False
    assert anki_miner.kept_no_speech(miner.path, lang, "default")
    before = len(miner.commands())
    assert _one_run(miner, lang, folder, profile="default") is False
    assert miner.commands()[before:] == []


def test_a_no_answers_only_its_own_language_and_profile_and_both_languages_hold(miner, folder, writes_its_profile):
    # why: one Surasura profile mines ja and zh; each language's import changed the profile the other's no was kept
    # for — re-keyed, two languages run in turn import once each, then nothing
    assert _one_run(miner, "ja", folder) is False
    assert not anki_miner.kept_no_speech(miner.path, "zh", PROFILE)
    assert not anki_miner.kept_no_speech(miner.path, "ja", "default")
    assert _one_run(miner, "zh", folder) is False
    for _ in range(3):
        assert _one_run(miner, "ja", folder) is False and _one_run(miner, "zh", folder) is False
    assert _imports(miner) == 2 and _checks(miner) == 4, [c["argv"][1:] for c in miner.calls() if "argv" in c]


# --- 2. the import re-keys the kept look-ups ------------------------------------------------------------------- #
@pytest.fixture
def writes_its_profile(monkeypatch):
    """Anki Miner's `settings-import` rewrites the profile's file (the fake writes none): the stamp moves."""
    real = anki_miner._communicate

    def communicate(proc, *a, **k):
        out = real(proc, *a, **k)
        if "settings-import" in proc.args:
            with open(os.path.join(os.environ["ANKI_MINER_HOME"], "profiles", f"{PROFILE}.json"), "a",
                      encoding="utf-8") as f:
                f.write(" ")
        return out
    monkeypatch.setattr(anki_miner, "_communicate", communicate)


def _run(miner, lang, job=1):
    """One Connect run's first look (verbs' setup: the kept look-ups)."""
    h.write_settings(target_language=lang, connect_anki_miner_path=miner.path)
    steps = runner.Steps(verbs.settings())
    verbs._anki_miner_setup(steps.loaded, lang, steps.run_dir({"id": job}), held=steps._anki_miner_held(lang))
    return steps


@pytest.mark.parametrize("lang", LANGS)
def test_the_speech_checks_own_import_re_keys_the_kept_look_ups(miner, folder, lang, writes_its_profile):
    _run(miner, lang)
    kept = anki_miner.kept_look_ups(miner.path, anki_miner.stamp(miner.path))
    assert kept is not None
    before = anki_miner.stamp(miner.path)
    assert _one_run(miner, lang, folder) is False
    assert anki_miner.stamp(miner.path) != before, "the import rewrote the profile"
    assert anki_miner.kept_look_ups(miner.path, anki_miner.stamp(miner.path)) == kept
    calls = len(miner.commands())
    _run(miner, lang, job=2)
    assert miner.commands()[calls:] == ["settings-export"], "the next run's first look: one start"


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("values, named", [({"asr_model": "small", "anki_deck": "Mining"}, None),
                                           ({"asr_model": "small"}, "Another"),
                                           ({}, None)],
                         ids=["another-key-beside-it", "a-new-profile", "the-language-alone"])
def test_any_other_import_still_drops_the_kept_answers(miner, folder, lang, values, named, tmp_path,
                                                       writes_its_profile):
    _run(miner, lang)
    assert _one_run(miner, lang, folder) is False
    try:
        anki_miner.settings_import(miner.path, lang, values, str(tmp_path / "import"), name=named,
                                   profile=None if named else PROFILE, keeps=True)
    except anki_miner.AnkiMinerError:
        pass                            # (the fake refuses a new profile's name: dropped all the same)
    now = anki_miner.stamp(miner.path)
    assert anki_miner.kept_look_ups(miner.path, now) is None
    assert not anki_miner.kept_no_speech(miner.path, lang, PROFILE)


@pytest.mark.parametrize("lang", LANGS)
def test_answers_that_no_longer_held_before_the_import_are_not_kept_after_it(miner, folder, lang, tmp_path,
                                                                             writes_its_profile):
    # why: the profile switched in Anki Miner's window before the import — re-keying would keep a stale `profiles`
    _run(miner, lang)
    with open(os.path.join(os.environ["ANKI_MINER_HOME"], "gui_config.json"), "w", encoding="utf-8") as f:
        json.dump({"active_profile_id": PROFILE, "anki_note_type": "Lapis"}, f)
    anki_miner.settings_import(miner.path, lang, {"asr_model": "large-v3"}, str(tmp_path / "import"),
                               profile=PROFILE, keeps=True)
    assert anki_miner.kept_look_ups(miner.path, anki_miner.stamp(miner.path)) is None


@pytest.mark.parametrize("lang", LANGS)
def test_a_failed_import_drops_the_kept_answers(miner, folder, lang, tmp_path, writes_its_profile):
    _run(miner, lang)
    miner.plan(speech={"installed": [], "model": "small"}, active_profile=PROFILE)    # refused: BAD_ARGUMENTS
    with pytest.raises(anki_miner.AnkiMinerError):
        anki_miner.settings_import(miner.path, lang, {"asr_model": "large-v3"}, str(tmp_path / "import"),
                                   profile=PROFILE, keeps=True)
    assert anki_miner.kept_look_ups(miner.path, anki_miner.stamp(miner.path)) is None


# --- the runner hands the run's export over ------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", LANGS)
def test_the_runner_hands_over_the_export_only_while_its_files_hold(miner, lang, monkeypatch):
    handed = []
    monkeypatch.setattr(anki_miner, "speech_ready", lambda *a, export=None: handed.append(export) or False)
    steps = _run(miner, lang)
    held = steps._anki_miner_held(lang)
    runner._speech_ready(steps, lang, miner.path, held["set"][1])
    assert handed[-1] == held["set"][3] and handed[-1]["settings"]["asr_model"] == "small"
    runner._speech_ready(steps, lang, miner.path, "another-profile")
    assert handed[-1] is None, "another profile's export never says what this one holds"
    with open(os.path.join(os.environ["ANKI_MINER_HOME"], "gui_config.json"), "a", encoding="utf-8") as f:
        f.write(" ")
    runner._speech_ready(steps, lang, miner.path, held["set"][1])
    assert handed[-1] is None, "the files changed since the export was read"
    runner._speech_ready(object(), lang, miner.path, held["set"][1])
    assert handed[-1] is None, "a stand-in with no set"
