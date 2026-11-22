"""The mining line under *Card sentences: Best* (Kantan-SD 6, PROVISIONAL: For Sonic 15): while a word's sentence is
cut from another episode in the mined episode's one Anki Miner call, the line keeps naming the episode whose cards are
made, then where this sentence is from — *Making cards · 01 — a sentence from 04 · Cutting clips 40%* — and its bar goes
once over the whole call (one run an episode, in turn), never back to 0 at each.

What a wrong answer would cost (Kantan-SD 5's timed mine): the line named the other episode as if it were being mined,
and its count jumped from 1 of 1 to 1 of 11 — a learner can't tell what the press they made is doing.

A real ledger, the status reader, the feed and the window's job registry; real Japanese and Chinese titles.
"""
import pytest

from app.connect import anki_miner, feed, status
from app.connect.ledger import Ledger
from app.services import status as S
from app.services.jobs import JobRegistry
from app.services.status import job_line

TITLES = {"ja": ("ぼっち・ざ・ろっく！ 第01話", "ぼっち・ざ・ろっく！ 第04話"), "zh": ("夜市 第一集", "夜市 第四集")}
STEP = {"stage": 3, "stages": 5, "done": 1, "total": 2}


def _mining(tmp_path, monkeypatch, lang, progress):
    """One job of `lang` mining, its saved progress `progress`; Connect running -> (status.read's language, path)."""
    monkeypatch.setattr(status, "running", lambda: True)
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        job = ledger.queue(lang, 101, "test", "ev-1")
        ledger.mark_run(lang)
        ledger.set_state(job, "mining", progress=progress)
    return status.read([lang], path=path), path


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_line_names_the_mined_episode_then_where_this_sentence_is_from(tmp_path, monkeypatch, lang):
    _own, other = TITLES[lang]
    got, _path = _mining(tmp_path, monkeypatch, lang, dict(STEP, run=1, runs=2, source=other))
    line = got["languages"][lang]["line"]
    assert line == f"Making cards 1 of 1 for an episode — a sentence from {other} (Anki Miner)"
    assert "1 of 1" in line, "the count is the episodes', never one a sentence's episode"


def test_the_episodes_own_line_reads_as_it_always_did(tmp_path, monkeypatch):
    got, _path = _mining(tmp_path, monkeypatch, "ja", dict(STEP, run=0, runs=2))
    assert got["languages"]["ja"]["line"] == "Making cards 1 of 1 — an episode (Anki Miner)"


@pytest.mark.parametrize("source", ["", "   ", 7, None])
def test_a_source_that_isnt_a_title_is_never_said(tmp_path, monkeypatch, source):
    # why: a saved progress written by another version, or cut short, must never make the line say "from 7" or "from "
    got, _path = _mining(tmp_path, monkeypatch, "ja", dict(STEP, source=source))
    assert got["languages"]["ja"]["line"] == "Making cards 1 of 1 — an episode (Anki Miner)"


def _percent(progress):
    return status._progress({"state": "mining", "progress": __import__("json").dumps(progress)})["percent"]


def test_the_bar_goes_once_over_every_run_of_the_call_and_never_back():
    # why: each run's own percent restarts at 0 — read alone, the bar would run to its end and jump back per episode
    span = status.MINE_TO - status.MINE_FROM
    one = anki_miner.percent(STEP)
    assert _percent(dict(STEP, run=0, runs=2)) == status.MINE_FROM + span * (one // 2) // 100
    assert _percent(dict(STEP, run=1, runs=2)) == status.MINE_FROM + span * ((100 + one) // 2) // 100
    walk = [_percent(dict(STEP, stage=stage, run=run, runs=3)) for run in range(3) for stage in (1, 3, 5)]
    assert walk == sorted(walk) and walk[-1] <= status.MINE_TO, "only forward, within Anki Miner's share"


@pytest.mark.parametrize("run, runs", [(2, 2), (-1, 2), (True, 2), (0, 0), ("1", 2), (None, 2)])
def test_a_run_count_that_doesnt_add_up_is_read_as_one_run(run, runs):
    assert _percent(dict(STEP, run=run, runs=runs)) == _percent(STEP)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_feed_hands_the_source_on_and_the_window_says_both_episodes(tmp_path, monkeypatch, lang):
    # why: the window's line (bottom left) is the one a learner reads; it must say the same as Connect's own
    own, other = TITLES[lang]
    got, _path = _mining(tmp_path, monkeypatch, lang, dict(STEP, run=1, runs=2, source=other))
    built = feed.build(got, lang)
    (item,) = [it for it in built.items.values() if it.kind == feed.MINING]
    assert item.source == other
    registry = JobRegistry()
    S.mirror_connect(registry, built._replace(items={1: item._replace(title=own + ".srt")}))
    (live,) = registry.live(S.CONNECT_JOB_KIND)
    assert job_line(live).startswith(f"Making cards · {own} — a sentence from {other} · ")
    S.mirror_connect(registry, None)


def test_the_window_line_without_a_source_is_the_episode_alone():
    registry = JobRegistry()
    item = feed.Item(feed.MINING, feed.WORDS[feed.MINING], "", 7, 0, 0, 40, "Cutting clips (3 of 40)",
                     title="第01話.srt")
    S.mirror_connect(registry, feed.Feed(on=True, mining=frozenset({1}), items={1: item}, line="Mining", state="ok",
                                         unseen=0, updating=False))
    (live,) = registry.live(S.CONNECT_JOB_KIND)
    assert job_line(live) == "Making cards · 第01話 · Cutting clips (3 of 40) 40%"
    S.mirror_connect(registry, None)
