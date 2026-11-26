"""E-JOURNEY 3: two lines that start together (two speakers at once), pressed on the journey page, end to end through
the door and Connect's look — the card is made from the line pressed (journey v3 SPEC § 3.3 row 11; SPEC § 10.3).

The line id `<item>:<start ms>` names both lines; the press carries the word (the door's body), Swap's row keeps it,
and both find the line again by it (`swap.line_cue(word=)`: the line the analyzer reads the word in). What a wrong
answer costs: a card cut from the other speaker's line, or a ⇄ refused as the old card's own line when the learner
pressed the other one. Real Japanese lines (tests/Test Resources/ja/repeated_lines.ja.srt: cues 4 and 5 both start at
7.000 s); the ledger and the library store are real, Anki is Tidy's fake.
"""
import os

import pytest

from app import cues
from app.connect import door_routes, swap
from tests.connect.test_j_swap_door import _asks, _press, _refused
from tests.connect.test_kantan_sl_swap import MINING, RESOURCES, Anki, Steps, _row, ledger  # noqa: F401  (`ledger`)
from tests.connect import test_j_swap_door as door_case

SRT = os.path.join(RESOURCES, "ja", "repeated_lines.ja.srt")
FIRST, SECOND = "早く窓口に返却しないと", "でも まだ半分しか読んでない"    # cues 4 and 5: one start, two speakers


@pytest.fixture
def item(monkeypatch):
    """The subtitle as the one item in NOW, Connect on -> its item id (J-SWAP's library, with this file)."""
    monkeypatch.setattr(door_case, "JA", SRT)
    return door_case._library("ja")


def _text(said):
    return [q.text for q in cues.read(SRT, "ja") if q.text.replace("\n", " ") == said][0]


def _card(ledger, item, word, note, sentence):
    """Connect made `word`'s card `note` from `sentence` (its batch's outcome, as the runner records it)."""
    job = ledger.queue("ja", item, "user", None, store_id="s1")
    ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made", "note_id": note,
                                       "sentence": sentence}], deck=MINING)
    ledger.set_state(job, "done")


def test_add_now_on_the_second_of_two_lines_that_start_together_makes_the_card_from_that_line(ledger, item,
                                                                                               monkeypatch):
    # why: the bug — *Add now* for 読む on でも まだ半分しか読んでない made its card from 早く窓口に返却しないと, the first
    # line at that start: Connect's look finds the row's line again (`swap._start`) by the row's word, said inflected
    got = _press("card/make", "ja", "読む", swap.line_id(item, 7.0))
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: pytest.fail("the learner pressed a line"))
    swap.look(Steps(subtitle=SRT), ledger, "ja", anki=Anki(), files=5)
    row = _row(ledger, got["id"])
    assert (row["state"], row["item_id"], row["line"]) == (swap.QUEUED, item, _text(SECOND)), row


def test_swap_on_the_second_line_is_not_the_old_cards_line_when_that_card_was_cut_from_the_first(ledger, item):
    # why: a card the bug made (読む's, cut from the first speaker's line): ⇄ on the line that says 読む is the
    # learner's way out — the door's check (never the old card's own line) must find the line pressed, not the first
    # at that start, or it refuses the press as the same line
    _card(ledger, item, "読む", 900, FIRST)
    got = _press("swap/queue", "ja", "読む", swap.line_id(item, 7.0))
    assert got["queued"] and [r["line_id"] for r in _asks(ledger)] == [swap.line_id(item, 7.0)]


def test_swap_on_the_old_cards_own_line_at_a_shared_start_is_still_refused(ledger, item):
    # why: edge case — the check still holds at a shared start: 返却's card was cut from 早く窓口に返却しないと, and ⇄
    # on that very line (the line that says 返却) is its own line: refused, nothing asked
    _card(ledger, item, "返却", 901, FIRST)
    e = _refused("swap/queue", "ja", "返却", swap.line_id(item, 7.0))
    assert e.message == door_routes.SAME and _asks(ledger) == []
