"""Laptop round 8 #49 (LF4-1 ⭐ A, PROVISIONAL): a level raise never mines an episode you've watched, and never waits
for (or asks for) a video.

What Sonic met: two episodes were mined, watched, their videos deleted; the list gained words overnight,
so the level raise queued "the new words' cards" for both, and their picks waited on the video — *Needs you* asked
him to choose a video or mine the text only, for episodes Connect had already mined. What a wrong answer costs: a
question about an episode that needs nothing, and the newest words carded from scenes already seen instead of the
episodes ahead.

The store tests use the suite's real subtitles (`connect_helpers.library`); the runner tests `FakeSteps` (real
Japanese words, synthetic titles). Never a live Anki.
"""
import os

import pytest

from app.connect import level, library, runner
from app.connect.ledger import LEVEL, Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps

BEFORE = {("冒険", "ボウケン"), ("散歩", "サンポ")}
RAISED = BEFORE | {("眼鏡", "メガネ"), ("老婆", "ロウバ")}


def _line(n=3):
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": n}, copy_carries=True)
        line = library.mine_line(s)
        return [(i, os.path.basename(s.item(i)["rel_path"])) for i in line]


def _level_jobs():
    with Ledger() as ledger:
        return [ledger.job_by_id(j["id"]) for j in ledger.jobs("ja") if j["kind"] == LEVEL]


def test_a_watched_mined_episode_gets_no_level_job_and_its_new_word_goes_to_the_next_mined_one():
    (a, fa), (b, fb), _d = _line()
    with c.store() as s:
        s.receipt(a, "2026-10-22T07:01:55Z")
        s.receipt(b, "2026-10-22T07:05:55Z")
        s.set_watched([a])                          # mined and watched
    files = {fa: ["眼鏡", "老婆"], fb: ["眼鏡"]}
    with c.store() as s:
        level.check(s, "ja", BEFORE, "run-1", files)
        out = level.check(s, "ja", RAISED, "run-2", files)
    assert out["queued"] == [b], "the watched episode is passed over; the one ahead of you takes the new word"
    assert [(j["item_id"], j["words"]) for j in _level_jobs()] == [(b, [("眼鏡", "メガネ")])]


def test_wants_is_the_one_rule_for_watched_and_taken_out_items():
    assert level.wants({"watched": 0, "in_learning_order": 1})
    assert not level.wants({"watched": 1, "in_learning_order": 1})
    assert not level.wants({"watched": 0, "in_learning_order": 0})
    assert not level.wants(None)


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan):
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    return steps, summary


def test_a_level_job_whose_video_is_gone_waits_quietly_never_asking_for_it(tmp_path, ledger):
    plan = {"line": {"ja": [13]}, "level": [("ja", 13, [("血族", "ケツゾク")])], "videos": {"13": None}}
    steps, summary = _run(tmp_path, ledger, plan)
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("waiting", runner.LEVEL_NO_VIDEO)
    assert runner.LEVEL_NO_VIDEO != runner.NO_VIDEO, "Needs you's *No video* lists NO_VIDEO's waits only"
    assert not any(e[0] == "mine" for e in steps.log)
    # review A8: the video back on this computer at a later start, its new words' cards are made
    plan.pop("videos")
    steps, summary = _run(tmp_path, ledger, plan)
    assert ledger.jobs("ja")[0]["state"] == "done" and [e[3] for e in steps.log if e[0] == "mine"] == [["血族"]]


def test_your_ask_on_a_level_job_is_a_yes_watched_or_without_its_video(tmp_path, ledger):
    # review A1: *Mine now* moved onto an open level job — watched, it still mines; with no video it asks for it
    plan = {"line": {"ja": [15]}, "level": [("ja", 15, [("好く", "スク")])], "watched": [15]}
    steps = FakeSteps(str(tmp_path), plan)
    steps.consume("ja", ledger)
    with ledger.transaction():
        ledger.ask("ja", 15, "2026-10-22T23:10:00.000000Z", store_id="store-1")
    plan.pop("level")
    _run(tmp_path, ledger, plan)
    assert ledger.jobs("ja")[0]["state"] == "done"
    plan = {"line": {"ja": [16]}, "level": [("ja", 16, [("存在感", "ソンザイカン")])], "videos": {"16": None}}
    steps = FakeSteps(str(tmp_path), plan)
    steps.consume("ja", ledger)
    with ledger.transaction():
        ledger.ask("ja", 16, "2026-10-22T23:11:00.000000Z", store_id="store-1")
    plan.pop("level")
    _run(tmp_path, ledger, plan)
    job = [j for j in ledger.jobs("ja") if j["item_id"] == 16][0]
    assert (job["state"], job["reason"]) == ("waiting", runner.NO_VIDEO)


def test_a_first_mining_with_no_video_still_waits_for_it(tmp_path, ledger):
    # the rule is the level raise's alone: an episode not mined yet still asks for its video (E15)
    plan = {"line": {"ja": [16]}, "queue": {"ja": [16]}, "videos": {"16": None}}
    _steps, summary = _run(tmp_path, ledger, plan)
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("waiting", runner.NO_VIDEO)
    assert summary["languages"]["ja"]["waiting"] == {16: runner.NO_VIDEO}


def test_a_level_job_queued_before_its_episode_was_watched_is_dropped_when_it_starts(tmp_path, ledger):
    plan = {"line": {"ja": [15]}, "level": [("ja", 15, [("好く", "スク")])], "watched": [15]}
    steps, summary = _run(tmp_path, ledger, plan)
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("dropped", runner.WATCHED)
    assert summary["languages"]["ja"]["dropped"] == [15]
    assert not any(e[0] in ("pick", "mine") for e in steps.log)


def test_an_asked_job_on_a_watched_episode_still_mines(tmp_path, ledger):
    # *Mine this* is yours: watched or not, it is mined (3.0's rule is Connect's own mining only)
    with ledger.transaction():
        ledger.ask("ja", 1, "2026-10-22T23:00:00.000000Z", store_id="store-1")
    _steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "watched": [1]})
    assert summary["languages"]["ja"]["done"] == [1]


def test_connects_own_first_mining_of_a_watched_episode_makes_no_cards_yet(tmp_path, ledger):
    # Sonic (LF4-1 = A): "new words never come from a watched episode YET" — 3.0's rule, lifted by 3.1's pick
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": [1]}, "watched": [1]})
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("dropped", runner.WATCHED)
    assert not any(e[0] == "mine" for e in steps.log)
    assert level.WATCHED_GIVES_NO_NEW_CARDS is True, "3.0's rule; 3.1's best-sentence pick sets it False"


def test_with_the_rule_lifted_a_watched_episode_is_mined_again(tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(level, "WATCHED_GIVES_NO_NEW_CARDS", False)
    assert level.wants({"watched": 1, "in_learning_order": 1})
    assert not level.watched_out({"watched": 1})


# --- laptop round 8 #52 (LF4-4 ⭐ A): a word Anki Miner has no definition for is no card in any episode ----------- #
# What Sonic met: a name at the top of his journey with no card; Anki Miner answers "no definition" for a name its
# dictionary lacks, and Connect sent the same names again with every episode. Cost of a wrong answer: a word sent and
# refused once an episode forever — or, the other way, a word a new Anki Miner could card never sent again.

NAME_WORDS = {"21": [("ルーデウス", "ルーデウス"), ("魔術", "マジュツ")],
              "22": [("ルーデウス", "ルーデウス"), ("剣術", "ケンジュツ")]}


def _sent(steps):
    return [(e[1], e[3]) for e in steps.log if e[0] == "mine"]


def test_a_word_with_no_definition_in_two_episodes_is_never_sent_from_a_third(tmp_path, ledger):
    words = dict(NAME_WORDS, **{"23": [("ルーデウス", "ルーデウス"), ("杖", "ツエ")]})
    plan = {"line": {"ja": [21, 22, 23]}, "queue": {"ja": [21, 22, 23]}, "words": words,
            "no_definition": ["ルーデウス"]}
    steps, _summary = _run(tmp_path, ledger, plan)
    # one episode's answer is no verdict on the word (review A6: Anki Miner reads it from its line); two are
    assert _sent(steps) == [(21, ["ルーデウス", "魔術"]), (22, ["ルーデウス", "剣術"]), (23, ["杖"])]
    assert ledger.uncardable("ja") == {("ルーデウス", "ルーデウス")}
    assert ledger.uncardable("zh") == set(), "one language's answers never another's"


def test_a_new_anki_miner_version_is_asked_again(tmp_path, ledger):
    plan = {"line": {"ja": [21, 22]}, "queue": {"ja": [21, 22]}, "words": NAME_WORDS, "no_definition": ["ルーデウス"]}
    _run(tmp_path, ledger, plan)
    words = {"24": [("ルーデウス", "ルーデウス"), ("杖", "ツエ")]}
    plan = {"line": {"ja": [24]}, "queue": {"ja": [24]}, "words": words, "app": "3.11.0"}
    steps, _summary = _run(tmp_path, ledger, plan)
    assert _sent(steps) == [(24, ["ルーデウス", "杖"])], "another dictionary may know it"
    assert ledger.uncardable("ja", "3.7.0") == {("ルーデウス", "ルーデウス")}
    assert ledger.uncardable("ja", "3.11.0") == set()
