"""*Card sentences: Best* on a real library (Kantan-SD 6): the bookkeeping when a word's line is cut from an episode
that has its own job waiting, and when the band is lowered between two jobs.

Under Best a word whose clearest sentence is in episode B is cut from B's line inside episode A's job: its card is
A's (A's job tag, A's made-words record). What a wrong answer would cost: B's own job making the word a second card
when it is mined later; a deleted card listed under the wrong episode in *Words it won't mine again…* (or under none,
so it could never be allowed again from there); a word the lowered band adds made twice or lost.

On `tests/connect/test_p33_replan.py`'s harness: the RP-2 Japanese library (real subtitles), Connect's real pick, store
and ledger, a stand-in only where Anki Miner sits (one note a word, no duplicate check of its own — so a second card
would show here).
"""
from collections import Counter

import pytest

pytest.importorskip("modules.junban")

from app.connect import library, runner  # noqa: E402
from app.connect.ledger import Ledger  # noqa: E402
from modules.junban.tests.test_reposition import _patched  # noqa: E402
from tests.connect.test_p33_replan import AnkiMinerStandIn, _episodes, _loaded, _settings_file, connect  # noqa: E402,F401
from tests.test_replan_preview import _deck, lib  # noqa: E402,F401


def _mining(steps):
    """Every word sent to the stand-in, with the episode whose job sent it: [(item, word, reading)]."""
    mined, real = [], steps.mine

    def mine(lang, job, picked, words, attempt):
        mined.extend((job["item_id"], w["word"], w["reading"]) for w in words)
        return real(lang, job, picked, words, attempt)
    steps.mine = mine
    return mined


def test_a_word_cut_from_an_episode_with_its_own_job_waiting_is_never_made_again_there(connect, monkeypatch):
    # why: before Kantan-SD 6 a word never moved to an episode with an open job; now it may be cut from that episode's
    # line inside the mined episode's job — that episode's own pick must then count it made (no second card), and a
    # learner who deletes the card finds it under the episode whose card it was
    root, store, _generates, ledger_path = connect
    _settings_file(root, connect_enabled=True, connect_sentence_dial="best")
    fake = _deck(root)
    first, second = _episodes(store)[:2]
    steps = AnkiMinerStandIn(_loaded(), [first, second])
    shared = set()

    def best(steps_, ledger, lang, job, words, here):
        # the dial's answer for every word episode B offers too: its clearest sentence is B's (a video on this PC)
        if job["item_id"] != first:
            return words, []
        theirs = runner.Steps.pick(steps_, lang, dict(job, item_id=second), None)
        offered = {(w["word"], w["reading"]) for w in theirs["words"]}
        out = []
        for w in words:
            if (w["word"], w["reading"]) in offered:
                shared.add((w["word"], w["reading"]))
                w = dict(w, **{"from": second})
            out.append(w)
        return out, []
    monkeypatch.setattr(runner, "_best", best)
    mined = _mining(steps)
    with _patched(fake):
        with Ledger(ledger_path) as ledger:
            runner.run(steps.loaded, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=4)
            jobs = {j["item_id"]: j for j in ledger.jobs("ja")}
            picked = ledger.picked(jobs[first]["id"]) or {}
            made_here = {o["word"]: o["note_id"] for o in ledger.outcomes(jobs[first]["id"]) if o["outcome"] == "made"}
    assert shared, "the library's first two episodes share words (else this proves nothing)"
    assert {jobs[first]["state"], jobs[second]["state"]} <= {"done", "waiting"} and jobs[second]["state"] == "done"
    assert str(second) in (picked.get("sources") or {}), "cut from B's line inside A's job"
    counts = Counter((w, r) for _i, w, r in mined)
    assert not [k for k, n in counts.items() if n > 1], "no word sent twice"
    assert {(i, w, r) for i, w, r in mined if (w, r) in shared} == {(first, w, r) for w, r in shared}, \
        "each shared word made once, by A's job — B's own pick counted it made"
    # the made-words record names A's job's episode only; the card deleted → listed under A, never under B
    word, _reading = sorted(shared)[0]
    rows = store.conn.execute("SELECT item_id FROM made_words WHERE word = ?", (word,)).fetchall()
    assert [r[0] for r in rows] == [first]
    library.notes_gone(store, [made_here[word]])
    assert [e["word"] for e in store.unmined_words(item_ids=[first])] == [word]
    assert store.unmined_words(item_ids=[second]) == []


def test_the_band_lowered_between_two_jobs_under_best_makes_every_extra_word_once_and_loses_none(connect, monkeypatch):
    # why (Kantan-SD 5 checked it by hand): the lowered band adds words to the second job's pick; under Best some of
    # them are cut from other episodes' lines — each must still be made exactly once, none dropped on the way
    root, store, _generates, ledger_path = connect
    _settings_file(root, connect_enabled=True, connect_sentence_dial="best")
    fake = _deck(root)
    items = _episodes(store)[:2]
    steps = AnkiMinerStandIn(_loaded(), items)
    answers, picks = [], []
    real_order, real_pick = steps.order, steps.pick

    def order(lang, job):
        answers.append(real_order(lang, job))
        if len(answers) == 1:           # after the first job: the band lowered (more words listed)
            _settings_file(root, connect_enabled=True, connect_sentence_dial="best",
                           logic={"selection": {"band": "common"}})
        return answers[-1]

    def pick(lang, job, video):
        got = real_pick(lang, job, video)
        if not job.get("only"):
            picks.append((job["item_id"], [(w["word"], w["reading"]) for w in got["words"]]))
        return got
    steps.order, steps.pick = order, pick
    mined = _mining(steps)
    with _patched(fake):
        with Ledger(ledger_path) as ledger:
            runner.run(steps.loaded, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=4)
            jobs = ledger.jobs("ja")
            borrowed = [w for j in jobs for w in (ledger.picked(j["id"]) or {}).get("words") or () if w.get("from")]
    first = {}
    for item, words in picks:
        first.setdefault(item, words)
    wanted = Counter(k for words in first.values() for k in words)
    made = Counter((w, r) for _i, w, r in mined)
    assert sorted(first) == sorted(items) and len(answers) >= 2, "both jobs picked, the band lowered between them"
    assert [j["state"] for j in jobs if j["item_id"] in items] == ["done", "done"]
    assert not [j for j in jobs if j.get("kind") == "level"], "a video's line stays in its episode's job"
    assert borrowed, "some words cut from another episode's line (else this proves nothing new)"
    assert not [k for k, n in made.items() if n > 1], "no word made twice"
    assert set(wanted) <= set(made), "no picked word lost"
