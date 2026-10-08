"""Connect's loop (P2.4 row 2.4.2; P1.5 02-data-model §2, §4; 06-edges E18, E19, E23, E24): every queued job, in
top-20 order, through pick → fit check → mine → backfill → junban, each step saved; one known-sync and one Generate a
run; the carded set read again for every pick; the profile pinned from pick to mine.

What a wrong answer would cost: the same card made twice (a word a higher job just carded, picked again lower down);
cards made with another Anki Miner profile than the one the words were picked for (its whitelist, its deck); a
Generate per episode (a 20-drop burst would take twenty × 13 s and 0.7 GB each); the next day's words reaching Anki
last; Chinese cards made before Anki Miner can make them.

Runs against `FakeSteps` (real Japanese words, synthetic titles); the real steps' seams are tested beside it
(`test_runner_steps.py`). Never a live Anki.
"""
import pytest

from app.connect import runner
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _run(tmp_path, ledger, plan, looks=1, languages=("ja",)):
    steps = FakeSteps(str(tmp_path), plan)
    summary = runner.run({}, list(languages), steps=steps, ledger=ledger, sleep=lambda s: None, looks=looks)
    return steps, summary


def _states(ledger, lang="ja"):
    return {j["item_id"]: j["state"] for j in ledger.jobs(lang)}


def test_one_placement_goes_end_to_end_and_every_step_is_recorded(tmp_path, ledger):
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": [1]}})
    assert summary["languages"]["ja"]["done"] == [1]
    assert _states(ledger) == {1: "done"}
    assert [e[0] for e in steps.log if e[0] in ("prepare", "pick", "fit", "mine", "record", "fill", "order")] == \
        ["prepare", "pick", "fit", "mine", "record", "fill", "order"]
    job = ledger.jobs("ja")[0]
    made = {o["word"]: o for o in ledger.outcomes(job["id"])}
    assert set(made) == {w for w, _r in WORDS[1]} and all(o["outcome"] == "made" for o in made.values())
    # D1: each word's line stays in the ledger (start, end, sentence) with its predicted class
    assert made["上層部"]["line_end"] == 12.5 and made["上層部"]["sentence"] == "上層部の台詞"
    assert made["上層部"]["predicted"] == "word"
    assert sorted(ledger.undo_record(job["id"])) == sorted(o["note_id"] for o in made.values())
    assert steps.records == [(1, {w: [made[w]["note_id"]] for w in made}, True)], "receipt + made words, one write"
    assert ledger.batches(job["id"])[0]["state"] == "done" and ledger.batches(job["id"])[0]["anki_miner"] == "3.7.0"


def test_chinese_waits_until_anki_miner_makes_chinese_cards(tmp_path, ledger):
    steps, summary = _run(tmp_path, ledger, {"line": {"zh": [1]}, "queue": {"zh": [1]}}, languages=("zh",))
    job = ledger.jobs("zh")[0]
    assert (job["state"], job["reason"]) == ("waiting", runner.CHINESE)
    assert not any(e[0] in ("prepare", "pick", "mine") for e in steps.log), "nothing of Chinese is mined"
    assert summary["looks"] == 1, "Chinese waits for the next start: no look every 2 minutes for it"


def test_a_burst_of_twenty_runs_in_top_20_order_with_one_prepare(tmp_path, ledger):
    line = list(range(101, 121))
    queued = list(reversed(line))               # placed in the opposite order to the top 20's
    words = {str(i): [(f"単語{i}", f"タンゴ{i}")] for i in line}
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": line}, "queue": {"ja": queued}, "words": words})
    assert [e[1] for e in steps.log if e[0] == "mine"] == line, "the next day's words first: the top 20's order"
    assert [e for e in steps.log if e[0] == "prepare"] == [("prepare", "ja")], "one known-sync + Generate a run"
    assert sorted(summary["languages"]["ja"]["done"]) == line


def test_a_level_job_mines_only_its_named_words(tmp_path, ledger):
    plan = {"line": {"ja": [1]}, "level": [("ja", 1, [("気配", "ケハイ")])]}
    steps, _summary = _run(tmp_path, ledger, plan)
    assert [e[3] for e in steps.log if e[0] == "mine"] == [["気配"]]
    assert ledger.jobs("ja")[0]["kind"] == "level"
    assert steps.records[0][2] is False, "a level job's batch keeps the item's first receipt"


def test_a_word_a_higher_job_just_carded_is_skipped_lower_down(tmp_path, ledger):
    # 一生懸命 is in both episodes: the higher one (item 1) makes it, item 2's pick (read after) leaves it out
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": [1, 2]}, "queue": {"ja": [2, 1]}})
    mined = [(e[1], e[3]) for e in steps.log if e[0] == "mine"]
    assert mined[0][0] == 1 and "一生懸命" in mined[0][1]
    assert mined[1][0] == 2 and "一生懸命" not in mined[1][1]
    assert steps.anki.words().count("一生懸命") == 1


def test_a_profile_switched_between_pick_and_mine_is_picked_again(tmp_path, ledger):
    plan = {"line": {"ja": [1]}, "queue": {"ja": [1]}, "profile_at_pick": "p1", "profile_at_mine": "p2"}
    steps, _summary = _run(tmp_path, ledger, plan)
    assert [e[0] for e in steps.log if e[0] in ("pick", "mine")] == ["pick", "mine", "pick", "mine"]
    assert ledger.picked(ledger.jobs("ja")[0]["id"])["profile"] == "p2"
    assert _states(ledger) == {1: "done"}
    assert len(steps.anki.words()) == len(WORDS[1]), "nothing was mined with the old profile"


def test_an_item_that_left_the_top_20_before_mining_is_dropped(tmp_path, ledger):
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [2]}, "queue": {"ja": [1, 2]}})
    assert _states(ledger) == {1: "dropped", 2: "done"}
    assert summary["languages"]["ja"]["dropped"] == [1]
    assert not any(e[0] == "pick" and e[1] == 1 for e in steps.log)


def test_an_item_that_left_once_mining_started_finishes(tmp_path, ledger):
    with ledger.transaction():
        job_id = ledger.queue("ja", 1, "user", None, store_id="store-1")
    ledger.set_state(job_id, "filling")
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": []}})
    assert _states(ledger) == {1: "done"}, "E18: once mining started, it finishes"


def test_a_job_of_a_store_set_up_again_is_dropped_before_mining(tmp_path, ledger):
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": [1]}, "queued_store": "old",
                                             "store_id": "new"})
    assert _states(ledger) == {1: "dropped"}
    assert ledger.jobs("ja")[0]["reason"] == "the library was set up again"
    assert not any(e[0] == "pick" for e in steps.log)


def test_an_episode_with_no_word_to_make_is_done_with_its_receipt(tmp_path, ledger):
    steps, _summary = _run(tmp_path, ledger, {"line": {"ja": [9]}, "queue": {"ja": [9]}, "words": {"9": []}})
    job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == ("done", runner.NO_WORDS)
    assert steps.records == [(9, {}, True)], "a finished zero-card job writes its receipt (Mado's W2.2 ask)"
    assert not any(e[0] in ("mine", "fill", "order") for e in steps.log)


def test_an_update_staged_stops_the_run_before_any_job(tmp_path, ledger):
    steps, summary = _run(tmp_path, ledger, {"line": {"ja": [1]}, "queue": {"ja": [1]}, "staged": True})
    assert summary["stopped"] == runner.STOPPED_FOR_UPDATE
    assert not any(e[0] == "pick" for e in steps.log)
    assert ("settle",) in steps.log, "a pending sync is still sent before it exits"
