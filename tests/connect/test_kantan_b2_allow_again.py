"""Kantan-B2: the words Surasura won't mine again, and *Allow again* / *Mine again* (a new tester, 2026-11-18).

Where the record is: the store's `made_words` — every word Connect made a card for, per episode, with its notes. A
card the learner deletes in Anki loses its note there (`notes_gone`) and the word keeps its row: never made again
unless asked (G1.3-4). Pinned here:
- `Store.unmined_words`: exactly the words whose every card is gone (never one with a card still in Anki anywhere),
  the newest first, one episode's when asked;
- `Store.allow_again`: those words' rows deleted — the next job may make them again —, a word still in Anki left as it
  is; one command, Undo puts the rows back, unless the word was made again meanwhile (the new record stands);
- *Mine again* (an episode's ⋯) is an ask on a mined episode: Connect queues it, and its job makes only the words
  Anki doesn't hold — the deleted ones come back, never a second card of one still there.

What a wrong answer would cost: a word the learner wanted that can never be mined again (he deleted a card only for
its sentence), a list that says a word is blocked while its card is still in Anki, or a second card of a word he
already has. Real subtitles (the suite's library), real words, ja + zh.
"""
import pytest

from app.connect import inbox, library
from app.connect.ledger import ASKED, Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

WORDS = {"ja": ("ほっ", "残念", "綺麗"), "zh": ("哎呀", "遗憾", "漂亮")}


def _mined(lang):
    """Two episodes mined: the first made WORDS[0] and WORDS[1] (notes 101, 102), the second WORDS[2] and WORDS[1]
    again (notes 201, 202) -> (first id, second id)."""
    c.library(lang)
    w = WORDS[lang]
    with c.store(lang) as s:
        a, b = s.ids("now")[:2]
        library.record_batch(s, a, {w[0]: [101], w[1]: [102]}, "2026-11-18T10:00:00Z", batch="t-1")
        library.record_batch(s, b, {w[2]: [201], w[1]: [202]}, "2026-11-18T11:00:00Z", batch="t-2")
    return a, b


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_only_words_whose_every_card_is_gone_are_listed_newest_first(lang):
    # why: the tester deleted junk cards; the list must hold them, and never a word whose card is still in Anki
    a, b = _mined(lang)
    w = WORDS[lang]
    with c.store(lang) as s:
        assert s.unmined_words() == []
        s.notes_gone([101, 102, 201])                    # w[1]'s second card (202) is still in Anki
        got = s.unmined_words()
        assert [e["word"] for e in got] == [w[2], w[0]], "newest made first; w[1] still has a card"
        assert got[0]["items"] == [b] and got[1]["items"] == [a]
        assert [e["word"] for e in s.unmined_words([a])] == [w[0]]
        assert s.unmined_words([999999]) == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_allow_again_frees_the_word_and_undo_keeps_it_out_again(lang):
    # why: a freed word is one Connect may make again (`made_words_all` no longer holds it); Undo is exact
    a, _b = _mined(lang)
    w = WORDS[lang]
    with c.store(lang) as s:
        s.notes_gone([101])
        assert w[0] in library.made_words_all(s)
        change = s.allow_again([w[0]])
        assert change is not None and [r[:2] for r in change.made_rows] == [(a, w[0])]
        assert w[0] not in library.made_words_all(s) and s.unmined_words() == []
        out = s.undo(change)
        assert out is not None and [r[:2] for r in out.made_rows] == [(a, w[0])]
        assert w[0] in library.made_words_all(s) and [e["word"] for e in s.unmined_words()] == [w[0]]


def test_allow_again_leaves_a_word_with_a_card_still_in_anki_and_nothing_to_free_is_no_change():
    # why: a word with any card in Anki isn't blocked by a deletion — freeing it would make a second card
    _mined("ja")
    w = WORDS["ja"]
    with c.store("ja") as s:
        s.notes_gone([102])                             # w[1] keeps 202
        before = s.versions()["state_version"]
        assert s.allow_again([w[1]]) is None
        assert s.allow_again(["見たことのない言葉"]) is None and s.allow_again([]) is None
        assert s.versions()["state_version"] == before, "nothing written (S19)"
        assert w[1] in library.made_words_all(s)


def test_an_undo_after_the_word_was_made_again_keeps_the_new_record():
    # why: Connect made the word again meanwhile — its new card's note must never be overwritten by the old empty row
    a, _b = _mined("ja")
    w = WORDS["ja"]
    with c.store("ja") as s:
        s.notes_gone([101])
        change = s.allow_again([w[0]])
        library.record_batch(s, a, {w[0]: [301]}, None, batch="t-3")       # made again (a level job's batch)
        out = s.undo(change)
        assert out.made_rows == [] and out.notes
        row = s.conn.execute("SELECT note_ids FROM made_words WHERE item_id = ? AND word = ?", (a, w[0])).fetchone()
        assert row[0] == "[301]"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_mine_again_is_an_ask_that_makes_only_what_anki_no_longer_holds(lang):
    # why: *Mine again* on the episode's ⋯ — its deleted cards' words come back, its cards still in Anki never twice
    a, _b = _mined(lang)
    w = WORDS[lang]
    with c.store(lang) as s, Ledger() as ledger:
        inbox.consume(s, lang, ledger)                  # Connect on: its watermark
        s.notes_gone([101])                             # w[0]'s card deleted; w[1]'s (102) still there
        s.ask_mining([a])
        out = inbox.consume(s, lang, ledger)
        assert out["queued"] == [a] and out["asked"] == [a]
        job = ledger.job(lang, a)
        assert job["kind"] == ASKED
        made = library.made_words_for(s, job)
        assert w[1] in made and w[0] not in made, "the deleted word may be made again, the one in Anki never twice"
