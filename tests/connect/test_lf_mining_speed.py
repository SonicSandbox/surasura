"""LF-mining row 25, fix 1: one set of Anki Miner look-ups per Connect run, not ten starts an episode.

Before, every episode started Anki Miner for `version`, `profiles` and `settings-export` in its pick, again in its
mine step, and `version` + `profiles` once more in `preflight` — nine look-ups, ~1.5 s each, before `check` and
`mine`. Now `runner.Steps` keeps, per language, the set its first look-up read (the version answer, the profile's id,
the field mapping and the export) and hands it to `verbs.pick` and to the mine step; `preflight` calls only `check`
(every batch: E9's readiness, Anki reachable). The set is read again after any failure and once it is 15 minutes old
(`verbs.SETUP_FOR_S`: an Anki Miner updated or reconfigured mid-run is read again at the latest then). The command
line's own `pick`, holding no set, reads as it always did.

What a wrong answer would cost: ~11.6 s an episode here (~23 s on the laptop) spent starting Anki Miner; or, kept too
long, a run mining with a profile or a field mapping Anki Miner no longer has. Against the fake Anki Miner and a real
Generate's list; Anki is closed (a closed loopback port), never a live Anki.
"""
import json
import os
import time
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.connect import anki_miner, runner
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.connect.fake_anki_miner import LAPIS_EXPORT
from tests.connect.test_pick_cli import library  # noqa: F401  (fixture: a generated Japanese library)
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

LOOK_UPS = ["version", "profiles", "settings-export"]


class _Clock:
    """`time` as verbs sees it, its monotonic clock moved by hand; everything else is the real module."""

    def __init__(self):
        self.now = 5000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


def _steps(fake_miner):
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    return runner.Steps(verbs.settings())


def _pick(steps, job, subtitle, video):
    """`Steps.pick`'s call of `verbs.pick` (its library reads left out): the language's set handed in."""
    ns = SimpleNamespace(lang="ja", file=subtitle, video=video, words=None, job=str(job["id"]), wait=5.0, made=None,
                         listed=None, held=steps._anki_miner_held("ja"))
    out = verbs.pick(ns)
    assert out["words"], "the episode has words to mine, or the mine step proves nothing"
    return {"video": video, "subtitle": out["subtitle"], "profile": out["anki_miner"]["profile"]}, out["words"][:3]


def _episode(steps, job, subtitle, video):
    picked, words = _pick(steps, job, subtitle, video)
    return steps.mine("ja", job, picked, words, 1)


def test_two_jobs_in_one_run_read_anki_miner_once_then_check_and_mine_each(library, fake_miner):  # noqa: F811
    # why: the nine look-ups an episode were ~36 % of its time; one set a run leaves `check` + `mine` per job
    subtitle, video = library
    steps = _steps(fake_miner)
    first = _episode(steps, {"id": 1, "item_id": 1}, subtitle, video)
    second = _episode(steps, {"id": 2, "item_id": 2}, subtitle, video)
    assert [o["outcome"] for o in first["outcomes"]] == ["made"] * 3
    assert [o["outcome"] for o in second["outcomes"]] == ["made"] * 3
    assert fake_miner.commands() == LOOK_UPS + ["check", "mine", "check", "mine"]


def test_the_kept_export_is_written_into_the_second_jobs_run_folder(library, fake_miner):  # noqa: F811
    # why: a run after a kill reads the job's field mapping from its own folder's export (by_tag, the media names):
    # a job whose set was kept must still have the file there
    subtitle, video = library
    steps = _steps(fake_miner)
    _episode(steps, {"id": 1, "item_id": 1}, subtitle, video)
    _episode(steps, {"id": 2, "item_id": 2}, subtitle, video)
    export = os.path.join(steps.run_dir({"id": 2}), "settings-export.json")
    with open(export, encoding="utf-8") as f:
        assert json.load(f) == LAPIS_EXPORT
    assert steps._export_fields("ja", {"id": 2})["audio"] == "SentenceAudio"


def test_a_failed_mine_call_reads_the_set_again_for_the_next_job(library, fake_miner):  # noqa: F811
    # why: Anki Miner refusing (its window open: BUSY) may mean it changed; the next job never trusts the old set
    subtitle, video = library
    steps = _steps(fake_miner)
    fake_miner.plan(mine="busy")
    with pytest.raises(runner.Wait):
        _episode(steps, {"id": 1, "item_id": 1}, subtitle, video)
    assert steps._anki_miner_held("ja") == {}, "the failure emptied the set"
    fake_miner.plan()
    _episode(steps, {"id": 2, "item_id": 2}, subtitle, video)
    assert fake_miner.commands() == LOOK_UPS + ["check", "mine"] + LOOK_UPS + ["check", "mine"]


def test_a_set_older_than_fifteen_minutes_is_read_again(library, fake_miner, monkeypatch):  # noqa: F811
    # why: an Anki Miner that updated itself mid-run (E10) is read again at the latest 15 minutes on
    subtitle, video = library
    clock = _Clock()
    monkeypatch.setattr(verbs, "time", clock)
    steps = _steps(fake_miner)
    _episode(steps, {"id": 1, "item_id": 1}, subtitle, video)
    clock.now += verbs.SETUP_FOR_S - 1
    _episode(steps, {"id": 2, "item_id": 2}, subtitle, video)
    assert fake_miner.commands() == LOOK_UPS + ["check", "mine"] * 2, "still fresh: kept"
    clock.now += 2
    _episode(steps, {"id": 3, "item_id": 3}, subtitle, video)
    assert fake_miner.commands() == LOOK_UPS + ["check", "mine"] * 2 + LOOK_UPS + ["check", "mine"]


def test_the_command_lines_pick_holds_no_set_and_reads_anki_miner_each_time(library, fake_miner):  # noqa: F811
    # why: `surasura-cli pick` is one call; it never keeps (nor finds) a set
    subtitle, video = library
    h.write_settings(connect_anki_miner_path=fake_miner.path)
    for job in ("job-41", "job-42"):
        code, lines = h.run_cli("pick", "--file", subtitle, "--video", video, "--job", job)
        assert code == 0 and h.answer(lines)["run_file"], lines
    assert fake_miner.commands() == LOOK_UPS * 2


def test_steps_pick_and_mine_hand_on_one_set_a_language(monkeypatch):
    # why: the set pick reads is the one the mine step reuses; another language keeps its own (its own export)
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
    steps = runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT})
    seen = []
    monkeypatch.setattr(verbs, "pick", lambda ns: seen.append(ns.held) or {"words": [], "subtitle": None})
    steps.pick("ja", {"id": 8, "item_id": item}, "episode.mkv")
    steps.pick("ja", {"id": 9, "item_id": item}, "episode.mkv")
    assert seen[0] is seen[1] is steps._anki_miner_held("ja")
    assert steps._anki_miner_held("zh") is not seen[0]

    monkeypatch.setattr(anki_miner, "find", lambda loaded: "AnkiMiner.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup",
                        lambda loaded, lang, run_dir, held=None: seen.append(held) or ({}, "p1", SimpleNamespace()))
    known = []
    monkeypatch.setattr(anki_miner, "mine_batch", lambda *a, **k: known.append(k.get("known")) or {"outcomes": []})
    steps.mine("ja", {"id": 8, "item_id": item}, {"video": "v", "subtitle": "s", "profile": "p1"}, [], 1)
    assert seen[2] is seen[0], "the mine step's look-up is handed the same set"
    assert known == [({}, "p1")], "preflight is told the version answer and profile already read"
