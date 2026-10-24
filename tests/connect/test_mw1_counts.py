"""M-W1: Connect's mine line on W-1's one "counts" rule (`library_store.counts` / `counts_sql`, the library's
`keep_watched`).

A stone (an episode marked watched) in an analysed tier stops counting while *Keep studying watched episodes* is off:
the store's own mine line (`Store._mine_ids`) already passes it; Connect's level raise beyond the line
(`level._walk` → `library.counting`) and a gap's reconcile (`inbox._gone` → `library.counts`) now read the same rule,
never a second copy of it. LF4-1 stays stricter: Connect never mines a watched episode on its own, even with the
option on (`level.wants`); your ask always does.

What a wrong answer would cost: a level job for a stoned episode makes cards from scenes already seen, unattended, in
the user's Anki; a reconcile that keeps such a job holds a queued job the runner only drops at its start; one that
drops an ask loses the user's *Mine this*.

Real subtitles (the suite's own) in a store built from folders; real Japanese lemmas; the list is handed in (no
Generate); never a live Anki.
"""
import os

from app import library_store
from app.connect import inbox, level, library
from app.connect.ledger import ASKED, LEVEL, Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

BEFORE = {("冒険", "ボウケン"), ("散歩", "サンポ")}
RAISED = BEFORE | {("眼鏡", "メガネ"), ("老婆", "ロウバ")}


def _small(line=2):
    """6 episodes, the top `line` in the line, 3 more in NOW, the last in Goal, all mined; Connect's first look made.
    -> (ids in walk order, {item: file name})."""
    c.library()
    with c.store() as s:
        s.bookkeeping({"mine_line": line}, copy_carries=True)
        ids = s.ids("now")
        s.set_tier([ids[-1]], "goal")
        for item_id in ids:
            s.receipt(item_id, "2026-10-07T09:00:00Z")
        order = s.ids("now") + s.ids("goal")
        names = {i: os.path.basename(s.item(i)["rel_path"]) for i in order}
    _look()
    return order, names


def _look(gap=False):
    with c.store() as s, Ledger() as ledger:
        if gap:
            s.read_events = lambda reader: ([], True)        # the log pruned past Connect's watermark
        return inbox.consume(s, "ja", ledger)


def _check(listed, signature, file_words):
    with c.store() as s:
        return level.check(s, "ja", listed, signature, file_words)


def _jobs(kind=None):
    with Ledger() as ledger:
        return {j["item_id"]: (j["state"], j["reason"]) for j in ledger.jobs("ja") if kind is None or j["kind"] == kind}


def _keep_watched(on):
    with c.store() as s:
        s.set_library_options(keep_watched=on)


def test_the_walk_beyond_the_line_passes_a_stone_while_keep_studying_is_off_and_reads_it_when_on():
    order, _names = _small()
    beyond = order[3]
    with c.store() as s:
        s.set_watched([beyond])
        assert beyond not in level._walk(s), "a stone has nothing left to mine: the store's own rule says so"
        assert library.counting(s, "now") == [i for i in s.ids("now") if i != beyond]
    _keep_watched(True)
    with c.store() as s:
        assert beyond in level._walk(s), "with Keep studying on it counts again, in its place"


def test_a_stone_beyond_the_line_gets_no_level_job_whether_keep_studying_is_on_or_off():
    order, names = _small()
    beyond = order[3]
    with c.store() as s:
        s.set_watched([beyond])
    files = {names[i]: ["眼鏡"] for i in order}
    _check(BEFORE, "run-1", files)
    out = _check(RAISED, "run-2", files)
    assert beyond not in out["queued"] and beyond not in _jobs(LEVEL)
    assert out["queued"], "the others still get the raise's word"
    _keep_watched(True)
    _check(RAISED | {("約束", "ヤクソク")}, "run-3", {names[i]: ["約束"] for i in order})
    assert beyond not in _jobs(LEVEL), "LF4-1 (YET): Connect never mines a watched episode on its own, option on or off"


def test_a_gap_drops_a_not_started_level_job_whose_episode_was_stoned_as_a_finished_ones():
    order, names = _small()
    beyond = order[3]
    files = {names[i]: ["眼鏡"] for i in order}
    _check(BEFORE, "run-1", files)
    _check(RAISED, "run-2", files)
    assert _jobs(LEVEL)[beyond] == ("queued", None)
    with c.store() as s:
        s.set_watched([beyond])                         # stoned after its level job was queued
        assert library.counts(s, s.item(beyond)) is False
    got = _look(gap=True)
    assert got["reconciled"] and beyond in got["dropped"]
    assert _jobs(LEVEL)[beyond] == ("dropped", "left the top 20")
    assert all(state == "queued" for i, (state, _r) in _jobs(LEVEL).items() if i != beyond), \
        "the counting ones beyond the line stay (C4)"


def test_with_keep_studying_on_a_gap_keeps_a_stoned_episodes_level_job_for_the_runner_to_drop():
    order, names = _small()
    beyond = order[3]
    files = {names[i]: ["眼鏡"] for i in order}
    _check(BEFORE, "run-1", files)
    _check(RAISED, "run-2", files)
    _keep_watched(True)
    with c.store() as s:
        s.set_watched([beyond])
        assert library.counts(s, s.item(beyond)) is True
    _look(gap=True)
    assert _jobs(LEVEL)[beyond] == ("queued", None), "it counts: the runner's WATCHED drop at its start decides (LF4-1)"


def test_an_ask_on_a_stoned_episode_is_kept_through_a_gap():
    order, _names = _small()
    beyond = order[3]
    with c.store() as s:
        s.set_watched([beyond])
        s.ask_mining([beyond])                          # *Mine this* on an episode you've watched: always a yes
    _look()
    assert _jobs(ASKED)[beyond][0] == "queued"
    got = _look(gap=True)
    assert beyond not in got["dropped"] and _jobs(ASKED)[beyond][0] == "queued"


def test_a_library_from_before_w1_reads_keep_studying_as_off():
    order, _names = _small()
    with c.store() as s:
        s.set_watched([order[3]])
        assert "keep_watched" not in (s.meta() or {}), "no key: as every library before W-1"
        assert library.counts(s, s.item(order[3])) is False
        assert order[3] not in library.counting(s, "now")
        assert library.counts(s, {"tier": "graduated", "watched": 0}) is False, "Finished never counts"
        assert library.counts(s, {"tier": "arrivals", "watched": 0}) is False, "nor New arrivals (not placed)"
        assert library_store.counts("now", 1, True) is True
