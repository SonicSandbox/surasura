"""The level raise beyond the top 20 (P4.1 row 4.1.5; C4; E23, HC-N53's "the rest in the background"; IK B1).

On the 3.0 line (`level.BEYOND_LINE`) a raise gives every already-mined item its newly listed words: the top 20
first, then the rest of Current in order, then Goal — never Finished (not analysed: the last Generate lists no word of
it, D16 / D23) and never an item taken out of the learning order (`in_learning_order = 0`, D14). Its jobs are never
dropped for being out of the line; a `finished` or `removed` event still drops one not started.

What a wrong answer would cost: these jobs write the user's Anki unattended. A job for a Finished title or one whose
cards the user took out (*Take its new cards out*) puts back cards the user said no to; a job dropped as "left the top
20" leaves the raise's words unmade below the line for ever (the list it was read from is recorded); the same word
made for two episodes is a duplicate card.

Real subtitles (the suite's own, copied as 28 episodes) in a store built from folders; real Japanese lemmas; the list
is handed in (no Generate); Anki and Anki Miner are `FakeSteps`' stand-ins — never a live Anki.
"""
import os

import pytest

from app.connect import inbox, level, library, runner
from app.connect.ledger import LEVEL, Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps

BEFORE = {("冒険", "ボウケン"), ("散歩", "サンポ")}
RAISED = BEFORE | {("眼鏡", "メガネ"), ("老婆", "ロウバ")}


def _names(s, ids):
    return {i: os.path.basename(s.item(i)["rel_path"]) for i in ids}


def _check(listed, signature, file_words):
    with c.store() as s:
        return level.check(s, "ja", listed, signature, file_words)


def _look():
    with c.store() as s, Ledger() as ledger:
        return inbox.consume(s, "ja", ledger)


def _level_jobs():
    with Ledger() as ledger:
        return [j for j in ledger.jobs("ja") if j["kind"] == LEVEL]


def _library_of_28():
    """28 episodes: the top 20 and 2 more in Current, 3 in Goal, 2 in Finished and 1 in Goal taken out of the learning
    order (*Take its new cards out*, then put back in Goal) — every one already mined. -> (top 20, rest of Current,
    Goal in its order, Finished, the taken-out one, {item: file name})."""
    c.library(extra=25)
    with c.store() as s:
        ids = s.ids("now")
        assert len(ids) == 28
        s.set_tier(ids[22:25], "goal")
        s.set_tier(ids[25:27], "graduated")
        s.finish([ids[27]], keep_cards=False)
        s.set_tier([ids[27]], "goal")
        assert s.item(ids[27])["in_learning_order"] == 0
        for item_id in ids:
            s.receipt(item_id, "2026-10-07T09:00:00Z")
        top = library.mine_line(s)
        rest = [i for i in s.ids("now") + s.ids("soon") if i not in top]
        goal = [i for i in s.ids("goal") if i != ids[27]]
        return top, rest, goal, ids[25:27], ids[27], _names(s, ids)


def test_a_raise_queues_every_mined_item_top_20_first_then_current_then_goal():
    top, rest, goal, finished, taken_out, names = _library_of_28()
    assert (len(top), len(rest), len(goal)) == (20, 2, 3)
    files = {name: ["眼鏡", "散歩"] for name in names.values()}
    assert _check(BEFORE, "run-1", files)["first"] is True
    out = _check(RAISED, "run-2", files)
    assert out["queued"] == top + rest + goal, "the top 20 first, then the rest of Current, then Goal, in order"
    queued = {j["item_id"] for j in _level_jobs()}
    assert len(queued) == 25
    assert not queued & set(finished), "never Finished (D16 / D23: no list words for it)"
    assert taken_out not in queued, "never one taken out of the learning order (D14)"
    assert all(j["words"] == '[["眼鏡", "メガネ"]]' for j in _level_jobs())


class LineSteps(FakeSteps):
    """FakeSteps over the real store's top 20 and the real inbox (its drops); Anki and Anki Miner stand in."""

    def consume(self, lang, ledger):
        with c.store(lang) as s:
            inbox.consume(s, lang, ledger)

    def mine_line(self, lang):
        with c.store(lang) as s:
            return library.mine_line(s)

    def store_id(self, lang):
        with c.store(lang) as s:
            return library.store_id(s)


def _small(line=2):
    """6 episodes, the top `line` mined by Connect: 2 above the line, 3 more in NOW, the last one in Goal, all mined;
    Connect's first look made. -> (ids in walk order, {item: file name})."""
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": line}, copy_carries=True)
        ids = s.ids("now")
        s.set_tier([ids[-1]], "goal")
        for item_id in ids:
            s.receipt(item_id, "2026-10-07T09:00:00Z")
        order = s.ids("now") + s.ids("goal")
        names = _names(s, order)
    _look()
    return order, names


def test_the_raises_jobs_run_in_order_none_dropped_one_card_per_word(tmp_path):
    order, names = _small()
    files = {names[order[0]]: ["眼鏡"], names[order[3]]: ["眼鏡", "老婆"], names[order[-1]]: ["老婆"]}
    _check(BEFORE, "run-1", files)
    assert _check(RAISED, "run-2", files)["queued"] == [order[0], order[3], order[-1]]
    steps = LineSteps(str(tmp_path), {})
    with Ledger() as ledger:
        out = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    mined = [(e[1], e[3]) for e in steps.log if e[0] == "mine"]
    assert mined == [(order[0], ["眼鏡"]), (order[3], ["老婆"])], \
        "the top first; a word made by a higher job isn't sent again lower down (P2.2's rule)"
    done = out["languages"]["ja"]
    assert sorted(done["done"]) == sorted([order[0], order[3], order[-1]]) and done["dropped"] == []
    assert sorted(steps.anki.words()) == ["眼鏡", "老婆"]


def test_one_finished_meanwhile_is_dropped_before_mining_one_moved_out_of_the_line_is_kept(tmp_path):
    order, names = _small()
    files = {names[i]: ["眼鏡"] for i in order}
    _check(BEFORE, "run-1", files)
    _check(RAISED, "run-2", files)
    with c.store() as s:
        library.finish(s, order[3])                     # finished before its job started
        library.place(s, order[0], "goal")              # the top episode moved out of the line, to Goal
    got = _look()
    assert got["dropped"] == [order[3]]
    states = {j["item_id"]: (j["state"], j["reason"]) for j in _level_jobs()}
    assert states[order[3]] == ("dropped", "left the top 20")
    assert states[order[0]][0] == "queued", "out of the line is no reason to drop a level job on 3.0"
    steps = LineSteps(str(tmp_path), {})
    with Ledger() as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
    assert order[3] not in [e[1] for e in steps.log if e[0] == "pick"]
    # picked and done, not dropped (its 眼鏡 already carded by the new top episode's job, run first: no second card)
    assert order[0] in [e[1] for e in steps.log if e[0] == "pick"]
    assert {j["item_id"]: j["state"] for j in _level_jobs()}[order[0]] == "done"
    assert steps.anki.words() == ["眼鏡"]


def test_with_beyond_line_off_only_the_top_20_as_before(monkeypatch):
    """The 2.x line (`BEYOND_LINE = False`): the top 20 only, request for request as P2.2 built it."""
    monkeypatch.setattr(level, "BEYOND_LINE", False)
    top, _rest, _goal, _finished, _taken_out, names = _library_of_28()
    files = {name: ["眼鏡"] for name in names.values()}
    _check(BEFORE, "run-1", files)
    assert _check(RAISED, "run-2", files)["queued"] == top


@pytest.mark.parametrize("beyond", [True, False])
def test_a_level_job_out_of_the_line_in_the_runner_follows_the_flag(tmp_path, monkeypatch, beyond):
    """`runner._job`: a level job not started whose item is out of the top 20 is mined on 3.0, dropped on 2.x."""
    monkeypatch.setattr(level, "BEYOND_LINE", beyond)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            ledger.queue_level("ja", 7, [("眼鏡", "メガネ")], store_id="store-1")
        steps = FakeSteps(str(tmp_path), {"line": {"ja": [1, 2]}})
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        job = ledger.jobs("ja")[0]
    assert (job["state"], job["reason"]) == (("done", None) if beyond else ("dropped", "left the top 20"))
