"""DSA-CONNECT 2 (the two costs DSA-CONNECT left, 2026-11-25): Anki Miner's three look-ups at every run's first pick,
and the store opened again and again for each episode Best borrows a line from.

1. The look-ups. Connect's run keeps one set of Anki Miner's answers (row 25: `version`, `profiles`, `settings-export`,
   ~1.2 s a program start each), but only inside its process: every Connect run's first pick started Anki Miner three
   times (DevTest split: 3.78 s, Best's and Nearest's alike). `version` answers for the program, `profiles` for the
   home's profiles folder and gui_config.json — what `anki_miner.stamp` watches — so both are now kept from one run to
   the next (`anki_miner.kept_look_ups`) and a run's first pick starts Anki Miner once, for the export (which may hold
   a key: never kept on disk). Never a stale answer: each invalidation is named and tested here — Anki Miner's profile
   switched, *Finish its setup* (Surasura's own `settings-import` / `setup`), an Anki Miner update (its program, its
   installer's version, or an export naming another version), any failure; and Anki's own profile switched (the note
   type is asked of Anki at each run's first look: never kept).
2. The store. Each borrowed episode was read 4–5 times a pick step (its video's pairing and row, the pick's row, the
   made words and the plan, then `_borrow`'s pairing and title), each a store open. Now each item's pairing and row
   are read once, in one open, while Best looks and borrows (`runner._reads_once`), and a borrow takes its job's
   made words and plan from the job's pick context. The mine and fit steps read again.

Against the fake Anki Miner (its call log counts the starts) and the suite's real library (ja + zh); Anki is closed.
"""
import json
import os
import pytest

from app import library_store
from app.cli import verbs
from app.cli.contract import CliError
from app.connect import anki_miner, library, runner
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.connect.fake_anki_miner import FEATURES_37, LAPIS_EXPORT
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

LOOK_UPS = ["version", "profiles", "settings-export"]
LANGS = ["ja", "zh"]


def _home(active, profiles=("default", "p-surasura")):
    """Anki Miner's home as 3.9+ keeps it: gui_config.json naming the active profile, one file a named profile."""
    home = os.environ["ANKI_MINER_HOME"]
    os.makedirs(os.path.join(home, "profiles"), exist_ok=True)
    with open(os.path.join(home, "gui_config.json"), "w", encoding="utf-8") as f:
        json.dump({"active_profile_id": active, "anki_note_type": "Lapis"}, f)
    for name in profiles:
        with open(os.path.join(home, "profiles", f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump({"name": name.title()}, f)


def _own_miner(fake_miner, tmp_path):
    """The fake Anki Miner as a program file of the test's own (so the test can replace it, as an update does)."""
    import shutil
    path = str(tmp_path / "AnkiMiner.py")
    shutil.copy(fake_miner.path, path)
    fake_miner.path = path
    return path


def _run(fake_miner, lang, job=1):
    """One Connect run's first look (a new `Steps`: its own set) -> (version answer, profile, mapping's fields)."""
    h.write_settings(target_language=lang, connect_anki_miner_path=fake_miner.path)
    steps = runner.Steps(verbs.settings())
    info, profile, mapping = verbs._anki_miner_setup(steps.loaded, lang, steps.run_dir({"id": job}),
                                                     held=steps._anki_miner_held(lang))
    return info, profile, dict(mapping.fields)


@pytest.fixture
def miner(fake_miner, tmp_path):
    _home("default")
    _own_miner(fake_miner, tmp_path)
    return fake_miner


# --- 1. Anki Miner's look-ups ------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("lang", LANGS)
def test_a_runs_first_look_starts_anki_miner_once_when_nothing_changed_since_the_last_run(miner, lang):
    # why: the 3.78 s at every run's first pick were three program starts whose answers hadn't changed
    first = _run(miner, lang)
    assert miner.commands() == LOOK_UPS
    second = _run(miner, lang, job=2)
    assert miner.commands() == LOOK_UPS + ["settings-export"], "one start: the export (never kept on disk)"
    assert second == first, "the same version answer, profile and fields as a run that reads all three"
    # a third run, and the export's own run folder written as before (a run after a kill reads it there)
    _run(miner, lang, job=3)
    assert miner.commands() == LOOK_UPS + ["settings-export"] * 2
    assert os.path.isfile(os.path.join(runner.Steps({}).run_dir({"id": 3}), "settings-export.json"))


def test_the_kept_answers_hold_no_export(miner):
    # why: an export may hold a key (clips.py: never kept on disk) — only `version` and `profiles` are kept
    _run(miner, "ja")
    with open(anki_miner._kept_path(), encoding="utf-8") as f:
        kept = json.load(f)
    assert set(kept) == {"key", "version", "profiles"}
    text = json.dumps(kept)
    assert '"settings":' not in text and "anki_miner_settings" not in text, "nothing of the export is kept"


@pytest.mark.parametrize("lang", LANGS)
def test_anki_miners_profile_switched_between_runs_reads_all_three_again(miner, lang):
    # why (a profile switch): with no "Surasura" profile Connect mines with Anki Miner's active one; switched in its
    # window between two runs, a kept `profiles` would mine the old profile's deck and fields. Anki Miner saves the
    # switch to gui_config.json: the stamp moved
    anime, drama = {"id": "anime", "name": "Anime"}, {"id": "drama", "name": "Drama"}
    miner.plan(app="3.7.0", features=FEATURES_37, profiles=[anime, dict(drama, active=True)],
               export=dict(LAPIS_EXPORT, app_version="3.7.0"))
    _home("drama", profiles=("anime", "drama"))
    assert _run(miner, lang)[1] == "drama"
    miner.plan(app="3.7.0", features=FEATURES_37, profiles=[dict(anime, active=True), drama],
               export=dict(LAPIS_EXPORT, app_version="3.7.0"))
    _home("anime", profiles=("anime", "drama"))
    assert _run(miner, lang, job=2)[1] == "anime"
    assert miner.commands() == LOOK_UPS * 2


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("write", ["settings-import", "setup"])
def test_finish_its_setup_drops_the_kept_answers(miner, tmp_path, lang, write):
    # why (*Finish its setup*): Surasura's own `settings-import` (the profile, its deck and fields) and `setup` rewrite
    # Anki Miner's settings — even where its files keep their stamp (the fake's import writes none), nothing is
    # answered from before it
    _run(miner, lang)
    assert anki_miner.kept_look_ups(miner.path, anki_miner.stamp(miner.path)) is not None
    if write == "settings-import":
        anki_miner.settings_import(miner.path, lang, {}, str(tmp_path / "import"), profile="p-surasura")
    else:
        anki_miner.api(miner.path, ["setup", "--language", lang, "--progress", str(tmp_path / "progress.json")])
    assert not os.path.exists(anki_miner._kept_path()), "dropped by the write"
    assert anki_miner.stamp(miner.path) is not None
    _run(miner, lang, job=2)
    assert miner.commands()[-3:] == LOOK_UPS, "the next run reads all three"


def test_a_speech_model_setup_started_drops_the_kept_answers(miner, tmp_path):
    # why: `setup --speech-model` runs for minutes beside Connect (`anki_miner.start`) and may rewrite the profile
    _run(miner, "ja")
    out = tmp_path / "setup.out"
    proc = anki_miner.start(miner.path, ["setup", "--language", "ja", "--progress", str(tmp_path / "p.json"),
                                         "--speech-model", "--model", "small"], str(out))
    proc.wait(30)
    assert not os.path.exists(anki_miner._kept_path())


@pytest.mark.parametrize("lang", LANGS)
def test_an_anki_miner_updated_between_runs_reads_all_three_again(miner, lang):
    # why (an Anki Miner update, 1): its program file replaced — its features or fields may be named otherwise
    _run(miner, lang)
    with open(miner.path, "a", encoding="utf-8") as f:
        f.write("\n# 3.13.1\n")
    _run(miner, lang, job=2)
    assert miner.commands() == LOOK_UPS * 2


def test_an_installer_version_changed_between_runs_reads_all_three_again(miner, monkeypatch):
    # why (an update, 2): the installer's DisplayVersion moved, whatever the program file's stamp says
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.13.0")
    _run(miner, "ja")
    monkeypatch.setattr(anki_miner, "installed_version", lambda: "3.14.0")
    _run(miner, "ja", job=2)
    assert miner.commands() == LOOK_UPS * 2


@pytest.mark.parametrize("lang", LANGS)
def test_an_export_naming_another_version_reads_version_and_profiles_again(miner, lang):
    # why (an update, 3): one the stamp and the installer can't see — the export is read every run and names its
    # program's version: another than the kept one, and the kept answers are read again before anything is mined
    miner.plan(app="3.5.0", export=dict(LAPIS_EXPORT, app_version="3.5.0"))
    _run(miner, lang)
    miner.plan(app="3.7.0", features=FEATURES_37, export=dict(LAPIS_EXPORT, app_version="3.7.0"))
    info, _profile, _fields = _run(miner, lang, job=2)
    assert info["app"] == "3.7.0" and "Z-1" in anki_miner.features(info)
    assert miner.commands() == LOOK_UPS + ["settings-export"] + LOOK_UPS
    _run(miner, lang, job=3)
    assert miner.commands()[-1:] == ["settings-export"], "the new answers kept"


@pytest.mark.parametrize("lang", LANGS)
def test_a_failed_look_up_drops_the_kept_answers_and_the_next_run_reads_all_three(miner, lang):
    # why (any failure, row 25): a refused export may be the kept profile gone — read everything again
    _run(miner, lang)
    miner.plan(replay={"settings-export": {"schema": 1, "command": "settings-export", "ok": False,
                                           "error": "PROFILE_UNREADABLE", "message": "unreadable"}})
    with pytest.raises(CliError):
        _run(miner, lang, job=2)
    assert not os.path.exists(anki_miner._kept_path())
    miner.plan()
    _run(miner, lang, job=3)
    assert miner.commands() == LOOK_UPS + ["settings-export"] + LOOK_UPS


def test_the_runners_failure_drop_takes_the_kept_answers_too(miner):
    # why: the runner empties its set after a failed fetch, pick, render or mine (`runner._drop_held`); a set emptied
    # mid-run must not be filled from the disk copy of the answers that just failed
    h.write_settings(connect_anki_miner_path=miner.path)
    steps = runner.Steps(verbs.settings())
    held = steps._anki_miner_held("ja")
    verbs._anki_miner_setup(steps.loaded, "ja", steps.run_dir({"id": 1}), held=held)
    runner._drop_held(held)
    assert held == {} and not os.path.exists(anki_miner._kept_path())
    verbs._anki_miner_setup(steps.loaded, "ja", steps.run_dir({"id": 2}), held=held)
    assert miner.commands() == LOOK_UPS * 2


def test_a_set_read_again_inside_a_run_reads_all_three(miner, monkeypatch):
    # why: inside a run the 15-minute rule (row 25) is unchanged: a set that old reads Anki Miner again, the disk
    # copy is never its answer
    class Clock:
        now = 5000.0

        def monotonic(self):
            return self.now

        def __getattr__(self, name):
            import time
            return getattr(time, name)
    clock = Clock()
    monkeypatch.setattr(verbs, "time", clock)
    h.write_settings(connect_anki_miner_path=miner.path)
    steps = runner.Steps(verbs.settings())
    held = steps._anki_miner_held("ja")
    verbs._anki_miner_setup(steps.loaded, "ja", steps.run_dir({"id": 1}), held=held)
    clock.now += 15 * 60 + 1
    verbs._anki_miner_setup(steps.loaded, "ja", steps.run_dir({"id": 2}), held=held)
    assert miner.commands() == LOOK_UPS * 2


def test_ankis_own_profile_switched_between_runs_asks_the_note_type_again(miner, monkeypatch):
    # why (Anki's profile switched, DevTest ↔ yours): the note type and its fields are Anki's, asked at each run's
    # first look — the kept answers are Anki Miner's alone
    asked = []
    real = verbs._check_note_type
    monkeypatch.setattr(verbs, "_check_note_type", lambda *a, **k: asked.append(1) or real(*a, **k))
    _run(miner, "ja")
    _run(miner, "ja", job=2)
    assert len(asked) == 2 and miner.commands() == LOOK_UPS + ["settings-export"]


def test_the_command_lines_pick_never_reads_the_kept_answers(miner):
    # why: `surasura-cli pick` holds no set (row 25): it reads Anki Miner each call, kept answers or not
    _run(miner, "ja")
    loaded = verbs.settings()
    verbs._anki_miner_setup(loaded, "ja", str(miner.path) + ".run", held=None)
    assert miner.commands() == LOOK_UPS * 2


# --- 2. The store, once an item a pick step --------------------------------------------------------------------- #
def _counting_opens(monkeypatch):
    opened = []
    real = library_store.open_store

    def counted(*a, **k):
        opened.append(1)
        return real(*a, **k)
    monkeypatch.setattr(library_store, "open_store", counted)
    return opened


def _library_with_videos(lang):
    """The suite's real library (ja / zh subtitles), each subtitle with a video beside it -> its item ids."""
    data = c.library(lang, extra=3)
    with c.store(lang) as s:
        ids = s.ids("now")
        for item_id in ids:
            sub = os.path.join(data, *str(s.item(item_id)["rel_path"]).replace("\\", "/").split("/"))
            stem = os.path.basename(sub).split(".")[0]
            open(os.path.join(os.path.dirname(sub), stem + ".mkv"), "wb").close()
    return ids


def _stand_in_pick(monkeypatch, made_reads):
    """`verbs.pick` answering as Best's borrow is answered (the words it was asked for, on their line)."""
    def pick(ns):
        ns.context.setdefault("job", ns.job)
        words = [{"word": w, "reading": r, "line_start": 1.0} for w, r in (ns.only or [("約束", "ヤクソク")])]
        return {"words": words, "subtitle": ns.file}
    monkeypatch.setattr(verbs, "pick", pick)
    real = library.made_words_for
    monkeypatch.setattr(library, "made_words_for", lambda store, job: made_reads.append(job["item_id"]) or
                        real(store, job))


@pytest.mark.parametrize("lang", LANGS)
def test_best_reads_each_borrowed_episode_from_the_store_once_a_pick_step(monkeypatch, lang):
    # why: each borrowed episode was read 4–5 times a pick step (its video's pairing and row, its pick's row, made
    # words and plan, `_borrow`'s pairing and title), each a store open (~15 ms on DevTest, ×10 episodes)
    ids = _library_with_videos(lang)
    own, others = ids[0], ids[1:4]
    made_reads = []
    _stand_in_pick(monkeypatch, made_reads)
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT, "target_language": lang})
    job = {"id": 8, "item_id": own}
    steps.pick(lang, job, "episode.mkv")                # the episode's own pick: starts the job's context
    words = [{"word": f"w{n}", "reading": "", "from": item} for n, item in enumerate(others)]
    opened = _counting_opens(monkeypatch)
    seen = runner._VideosOnce(steps)
    with runner._reads_once(steps):
        for item in others:                              # `_best`'s reach looks each video up first
            assert seen.video(lang, dict(job, item_id=item))
        out, sources = runner._borrow(seen, lang, job, words)
    assert len(opened) == len(others), f"one store open a borrowed episode, not {len(opened) / len(others):.1f}"
    assert made_reads == [own], "a borrow takes its job's made words (and plan) from the job's context"
    assert steps._step_reads is None, "the step's reads end with it"
    # the same answer as a pick step that reads everything each time
    steps.pick(lang, job, "episode.mkv")
    plain = runner._borrow(runner._VideosOnce(steps), lang, job, words)
    assert (out, sources) == plain
    assert sorted(sources) == sorted(str(i) for i in others)
    assert all(src["title"] and src["video"].endswith(".mkv") for src in sources.values())


@pytest.mark.parametrize("lang", LANGS)
def test_outside_the_pick_steps_borrows_every_read_opens_the_store_as_before(monkeypatch, lang):
    # why: the fit and mine steps check the pairing as it is now (`_fit_sources`: a pairing changed since the pick
    # sends the words home) — the step's reads never reach them, even when the step fails part way
    ids = _library_with_videos(lang)
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT, "target_language": lang})
    job = {"id": 8, "item_id": ids[1]}
    with pytest.raises(KeyError):
        with runner._reads_once(steps):
            steps.pairing(lang, job)
            raise KeyError("a pick step that failed part way")
    assert steps._step_reads is None
    opened = _counting_opens(monkeypatch)
    for _ in range(2):
        steps.pairing(lang, job)
        steps.title(lang, job)
    assert len(opened) == 4, "each read its own open, as before"


@pytest.mark.parametrize("lang", LANGS)
def test_a_borrow_of_another_job_reads_its_own_made_words(monkeypatch, lang):
    # why: the made words and the plan kept in the context are one job's: a borrow for another job reads them itself
    ids = _library_with_videos(lang)
    made_reads = []
    _stand_in_pick(monkeypatch, made_reads)
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT, "target_language": lang})
    steps.pick(lang, {"id": 8, "item_id": ids[0]}, "episode.mkv")
    steps.pick(lang, {"id": 9, "item_id": ids[1], "only": [("約束", "ヤクソク")]}, "episode.mkv")
    steps.pick(lang, {"id": 8, "item_id": ids[2], "only": [("約束", "ヤクソク")]}, "episode.mkv")
    assert made_reads == [ids[0], ids[1], ids[2]], "another job's borrow, then a borrow after it: each reads its own"
