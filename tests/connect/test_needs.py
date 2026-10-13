"""Needs you's rules in the ledger (`Ledger.need`, `needs`, `mark_seen`, `dismiss`, `fix`).

The rule: a standing need (not-timed, no-subtitle...) raised again while it is open changes nothing, so the
window never shows the same wait twice or resets what you already saw; a failure you have seen and that happens
again counts again with its new words; a failure you have not seen yet is left as it is; a need fixed earlier
is a new entry when its trouble comes back; a dismissed entry stays dismissed; and `fix` keeps the need whose
words are in `keep` (a step the job ended without: its trouble still stands).

What a wrong answer would cost: a standing wait re-raised on every run would reappear in the window and the badge
after you had dismissed it, and a failure you saw but that came back silently would never count again, so you
would not learn that Anki Miner stopped again.
"""

import pytest

from app.connect.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _open_ja(ledger):
    return ledger.needs("ja")


def test_standing_need_raised_again_while_open_writes_nothing_even_after_seen(ledger):
    # Why: a standing state stays until its cause goes; raising it again must not reset `at` or the words, even
    # once you have seen it (a seen row would otherwise match the failure-path UPDATE).
    assert ledger.need("ja", "not-timed", "上層部は時間が決まっていません") is True
    first = _open_ja(ledger)[0]
    assert ledger.mark_seen([first["id"]]) == 1

    assert ledger.need("ja", "not-timed", "気配は時間が決まっていません") is False

    rows = ledger.needs("ja", listed=False)
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["say"] == "上層部は時間が決まっていません"
    assert rows[0]["at"] == first["at"]


def test_failure_seen_and_raised_again_counts_again_with_its_new_words(ledger):
    # Why: a failure that comes back after you saw it is news; the badge must count it again with the new words.
    assert ledger.need("ja", "mine-failed", "上層部: Anki Miner stopped", item_id=3) is True
    row = _open_ja(ledger)[0]
    ledger.mark_seen([row["id"]])
    assert ledger.needs("ja", unseen=True) == []

    assert ledger.need("ja", "mine-failed", "一生懸命: Anki Miner stopped twice", item_id=3) is True

    unseen = ledger.needs("ja", unseen=True)
    assert [r["id"] for r in unseen] == [row["id"]]
    assert unseen[0]["say"] == "一生懸命: Anki Miner stopped twice"
    assert unseen[0]["seen_at"] is None


def test_failure_not_yet_seen_raised_again_is_left_as_it_is(ledger):
    # Why: one you have not seen yet is still in front of you; raising it again writes nothing and says nothing new.
    assert ledger.need("ja", "mine-failed", "溜め息: Anki Miner stopped", item_id=4) is True

    assert ledger.need("ja", "mine-failed", "溜め息: Anki Miner stopped again", item_id=4) is False

    rows = _open_ja(ledger)
    assert len(rows) == 1
    assert rows[0]["say"] == "溜め息: Anki Miner stopped"


def test_fixed_failure_raised_again_is_a_new_entry(ledger):
    # Why: once fixed, the trouble coming back is a new trouble, so it gets a row of its own and counts.
    assert ledger.need("ja", "mine-failed", "勇気: Anki Miner stopped", item_id=3) is True
    old = _open_ja(ledger)[0]
    assert [r["id"] for r in ledger.fix("ja", item_id=3)] == [old["id"]]
    assert _open_ja(ledger) == []

    assert ledger.need("ja", "mine-failed", "勇気: Anki Miner stopped again", item_id=3) is True

    rows = _open_ja(ledger)
    assert len(rows) == 1
    assert rows[0]["id"] != old["id"]


def test_dismissed_entry_stays_dismissed_when_standing_need_is_raised_again(ledger):
    # Why: Dismiss takes the entry off the list until its cause goes; raising the same standing wait again must not
    # bring it back, while it is still open underneath.
    assert ledger.need("ja", "not-timed", "約束は時間が決まっていません") is True
    row = _open_ja(ledger)[0]
    assert ledger.dismiss(row["id"]) is True
    assert ledger.needs("ja") == []
    assert len(ledger.needs("ja", listed=False)) == 1

    assert ledger.need("ja", "not-timed", "約束は時間が決まっていません") is False

    assert ledger.needs("ja") == []
    assert len(ledger.needs("ja", listed=False)) == 1


def test_fix_keeps_the_need_named_in_keep_and_fixes_the_items_others(ledger):
    # Why: a step the job ended without keeps its own trouble open (the `keep` words), while the item's other
    # needs are fixed when the job is done.
    assert ledger.need("ja", "mine-failed", "上層部: Anki Miner stopped twice", item_id=3) is True
    assert ledger.need("ja", "no-subtitle", "気配: no subtitle", item_id=3) is True

    fixed = ledger.fix("ja", item_id=3, keep={"上層部: Anki Miner stopped twice"})

    assert [r["say"] for r in fixed] == ["気配: no subtitle"]
    still_open = _open_ja(ledger)
    assert [r["say"] for r in still_open] == ["上層部: Anki Miner stopped twice"]
