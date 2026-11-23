"""Swap on a card Best made from another episode's line (Kantan-SD 6 joined with Kantan-SL's Swap).

Under *Card sentences: Best* a word mined with episode A can be cut from episode B's line (`runner._best` marks it
`from`, `_borrow` picks it there), and the card is A's job's. Swap (the review loop's ⇄, and Kyou-DW's *Bad card*
through the same `swap.make_card`) must then avoid the line the card really holds — B's, as the job's record keeps it
(the outcome's sentence, from the pick's `from`) — never the mined episode's own line, which the card never had. The
new card is cut where its new line is, and Undo puts the Best card back as the learner left it.

What a wrong answer costs: a new card from the very line the learner wanted gone (the old card's, read as if it were
the mined episode's), or a good line of the mined episode refused, or an Undo that loses the Best card.

A real ledger and library store; Connect's loop against `FakeSteps`; Anki is Tidy's fake. Real Japanese and Chinese
lines from tests/Test Resources (Swap's own cases).
"""
import calendar
import time
import types
from collections import namedtuple

import pytest

from app.connect import library, runner, runfile, swap, swap_queue
from app.connect.ledger import SWAP, Ledger
from tests import connect_helpers as c
from tests.connect.fake_steps import FakeSteps
from tests.connect.test_kantan_sl_swap import CASES, Anki, Steps, _lists, _make_the_job, _opener, _row

Choice = namedtuple("Choice", "file item_id text others weight here audio")


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    monkeypatch.setattr(runfile.time, "sleep", lambda s: None)


@pytest.fixture
def path(tmp_path, monkeypatch):
    from app.connect import ledger as ledger_mod
    where = str(tmp_path / "connect" / "ledger.sqlite")
    monkeypatch.setattr(ledger_mod, "path", lambda: where)
    return where


def _best_card(tmp_path, monkeypatch, path, lang):
    """Episode `mined` is mined under Best; its word's line is cut from episode `source` (the old card's line there),
    while the mined episode's own line is the other one -> (mined, source, the Best card's note id)."""
    word, old, other = CASES[lang]
    c.library(lang)
    _lists(lang)
    with c.store(lang) as s:
        mined, source = s.ids("now")[:2]
    steps = FakeSteps(str(tmp_path), {"line": {lang: [mined]}, "queue": {lang: [mined]},
                                      "words": {str(mined): [(word, "")], str(source): [(word, "")]}})
    lines = {mined: other, source: old}
    real = steps.pick

    def pick(lang_, job, video):            # each episode's own line for the word (FakeSteps says one for all)
        got = real(lang_, job, video)
        for w in got["words"]:
            w["line_text"] = lines[job["item_id"]]
        return got
    steps.pick = pick

    def best(steps_, ledger, lang_, job, words, here):  # the dial: the word's best line is the other episode's
        return [dict(w, **{"from": source}) for w in words], []
    monkeypatch.setattr(runner, "_best", best)
    with Ledger(path) as ledger:
        runner.run({}, [lang], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        (job,) = ledger.jobs(lang)
        made = [o for o in ledger.outcomes(job["id"]) if o["outcome"] == "made"]
        picked = ledger.picked(job["id"])
    assert job["item_id"] == mined and [o["word"] for o in made] == [word]
    assert picked["words"][0]["from"] == source, "the card's line was cut from the other episode"
    return mined, source, int(made[0]["note_id"])


def _picker(monkeypatch, ranked):
    asked = []

    def choose(language, keys, *, never=None, reach=None, files=None, **kw):
        asked.append(never)
        return {k: [x for x in ranked if reach(x.item_id)] for k in keys}
    monkeypatch.setattr(swap, "_picker", lambda: types.SimpleNamespace(choose=choose))
    return asked


@pytest.mark.parametrize("by", [swap.BY_SWAP, swap.BY_BAD_CARD])
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_best_card_from_another_episodes_line_swapped_avoids_that_line_and_undo_puts_it_back(
        tmp_path, monkeypatch, path, lang, by):
    # Why: the Best card's line is the source episode's, not the mined one's. Swap reads "the old card's line" from
    # the job's record of where it was cut; a reader by the mined episode would refuse that episode's good line and
    # let the old one through.
    word, old, other = CASES[lang]
    mined, source, note = _best_card(tmp_path, monkeypatch, path, lang)
    anki = Anki()
    anki.add(note, "Japanese", word, 1, cards=[{"reps": 3, "type": 2, "queue": -1, "flags": 3}])   # suspended, green
    card = note * 10
    # the picker ranks the old card's line (in the source episode) first; the mined episode's own line next
    asked = _picker(monkeypatch, [Choice("b.srt", source, old, 0, 1.0, False, True),
                                  Choice("a.srt", mined, other, 0, 0.5, False, True)])
    with Ledger(path) as ledger:
        if by == swap.BY_SWAP:
            entry = swap_queue.add(lang, word, card, note, "sync-1")
        else:
            entry = None
            assert swap.make_card(lang, word, old_note=note, by=by, ledger=ledger, wake=False)["state"] == swap.ASKED
        swap.look(Steps(), ledger, lang, store_id="s1", anki=anki, files=5)
        row = swap._rows(ledger, "language = ?", (lang,))[0]
        assert asked == [{(word, ""): {old}}], "the line avoided is the one the Best card holds, from its episode"
        assert (row["state"], row["item_id"], row["line"]) == (swap.QUEUED, mined, other)
        job = ledger.job_by_id(row["job_id"])
        assert (job["kind"], job["item_id"]) == (SWAP, mined), "the new card is cut where its new line is"
        assert swap.spec_of(job["id"], lang)["avoid"] == [old]
        # the swap's job makes its card; the next look records it and tags the Best card
        tag = "surasura::connect::" + ledger.tag_id(row["job_id"])
        _make_the_job(ledger, row, note=950, record=True)
        done_at = calendar.timegm(time.strptime(job["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
        anki.add(950, tag, word, done_at - 60, sound="swap-new.mp3")
        swap.look(Steps(), ledger, lang, anki=anki, files=5)
        assert (_row(ledger, row["id"])["state"], _row(ledger, row["id"])["new_note"]) == (swap.MADE, 950)
        assert swap.SWAP_TAG in anki.notes_[note]["tags"]
        with c.store(lang) as s:
            assert 950 in s.made(mined)[word], "the new card is recorded on the episode it was cut from"
        assert swap.undo(anki, ledger, lang, row["id"], open_store=_opener(lang))["undone"]
    assert anki.deleted == [950]
    back = anki.cards_[card]
    assert (back["queue"], back["flags"]) == (0, 0) and swap.SWAP_TAG not in anki.notes_[note]["tags"]
    assert note in anki.notes_, "the Best card is back to study, never deleted"
    if entry is not None:
        assert [e["state"] for e in swap_queue.load(lang) if e["id"] == entry["id"]] == [swap_queue.UNDONE]
