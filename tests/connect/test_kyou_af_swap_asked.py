"""Kyou-AF: Swap's record of the cards asked from the journey (*Add now*, journey v3 D3), read for Junban's order.

`swap.asked_first(language)` is the one read: the new notes of the made *Add now* asks, in the order they were asked,
each once. What it holds still: only *Add now* (`by` "add now" — never the loop's ⇄, a *Bad card*, or the journey's ⇄
on a word that has a card), only made (an ask Connect hasn't made, one dropped or undone: none), only this language;
read-only (a missing ledger is never made, a present one never written); [] before any swap was asked.
Real words from tests/Test Resources (the Kantan-SL cases); the ledger is real.
"""
import hashlib
import os

from app.connect import ledger as ledger_mod
from app.connect import swap
from app.connect.ledger import Ledger


def _ask(ledger, language, word, note_id, by=swap.BY_ADD_NOW, state=swap.MADE):
    got = swap.make_card(language, word, line_id="3:41500", by=by, ledger=ledger, wake=False,
                         state_of=lambda _w, _r: None)
    swap._set(ledger, got["id"], state=state, new_note=note_id)
    return got["id"]


def test_no_ledger_is_no_ask_and_is_never_made(tmp_path):
    path = tmp_path / "connect" / "ledger.sqlite"
    assert swap.asked_first("ja", db_path=str(path)) == []
    assert not path.exists() and not path.parent.exists()


def test_a_ledger_before_any_swap_has_no_ask(tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    Ledger(path).close()                         # Connect's ledger, no `swaps` table yet
    assert swap.asked_first("ja", db_path=path) == []


def test_only_made_add_now_asks_of_this_language_in_the_order_asked(tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        _ask(ledger, "ja", "借りる", 1700000000300)
        _ask(ledger, "ja", "眼鏡", 1700000000200, by=swap.BY_SWAP)            # the loop's ⇄: Tidy's, not D3's
        _ask(ledger, "ja", "冒険", 1700000000100)                             # asked second, an older note
        _ask(ledger, "zh", "我们", 1700000000400)                             # another language
        _ask(ledger, "ja", "散歩", 1700000000500, state=swap.UNDONE)          # its Undo took the card back
        _ask(ledger, "ja", "須藤", 1700000000600, state=swap.ASKED)           # Connect hasn't made it yet
        _ask(ledger, "ja", "図書館", 1700000000700, by=swap.BY_BAD_CARD)
        _ask(ledger, "ja", "走る", 1700000000800, by=swap.BY_JOURNEY)          # the journey's ⇄ (a word with a card)
        _ask(ledger, "ja", "借りる", 1700000000300)                           # asked again: once, at its first place
    assert swap.asked_first("ja", db_path=path) == [1700000000300, 1700000000100]
    assert swap.asked_first("zh", db_path=path) == [1700000000400]


def test_the_read_never_writes_the_ledger(tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as ledger:
        _ask(ledger, "ja", "借りる", 1700000000300)
        ledger.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert swap.asked_first("ja", db_path=path) == [1700000000300]
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == before


def test_the_default_ledger_is_connects_own(tmp_path):
    """No path: Connect's ledger in the local data folder (the test root's, under the harness)."""
    with Ledger() as ledger:
        _ask(ledger, "ja", "借りる", 1700000000300)
    assert os.path.dirname(ledger_mod.path()) == ledger_mod.folder()
    assert swap.asked_first("ja") == [1700000000300]
