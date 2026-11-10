"""A word held by two top-20 files belongs to the first item in the top-20 line (P2.4-E18; `Steps._top_words`).

The top 20's line is items 1 then 2. Both files hold 勇気, so it belongs to item 1 (the next day's, the earlier
item); 溜め息 is held by item 2's file alone. Mutant P2.4-E18 writes `holder[word] = item`, so the later file
overwrites the earlier one and 勇気 is wrongly credited to item 2.

What a wrong answer would cost: a shelved word is credited to the wrong top-20 item, so the swap-in or the shelf
mis-attributes which file the learner's next day needs; the word's card can then be held back from the item that
actually needs it.

Against a Steps whose store and list readers are fakes (no live Anki, no network, no sleeps).
"""
from app.cli import connect_verbs
from app.connect import library, runner


class FakeStore:
    """The one store read `_top_words` makes: an item's row, carrying its file's path."""

    def item(self, item_id):
        return {"rel_path": "show/ep1.srt"} if item_id == 1 else {"rel_path": "show/ep2.srt"}


def test_word_held_by_two_top_20_files_belongs_to_the_earlier_item(monkeypatch):
    # the top 20 is item 1 then item 2; both files hold 勇気 — the earlier item (1) must keep it
    monkeypatch.setattr(library, "mine_line", lambda store: [1, 2])
    monkeypatch.setattr(connect_verbs, "_read_list",
                        lambda lang: (None, None, {"ep1.srt": ["勇気"], "ep2.srt": ["勇気", "溜め息"]}))

    held = runner.Steps({})._top_words("ja", FakeStore())

    # 溜め息 is only in item 2's file, so it stays with item 2; 勇気 must not be overwritten by the later file
    assert held == {"勇気": 1, "溜め息": 2}


def test_word_held_by_one_top_20_file_goes_to_that_item(monkeypatch):
    # no overlap: each word goes to the one item whose file holds it, whatever the order of the line
    monkeypatch.setattr(library, "mine_line", lambda store: [2, 1])
    monkeypatch.setattr(connect_verbs, "_read_list",
                        lambda lang: (None, None, {"ep1.srt": ["勇気"], "ep2.srt": ["溜め息"]}))

    held = runner.Steps({})._top_words("ja", FakeStore())

    assert held == {"勇気": 1, "溜め息": 2}
