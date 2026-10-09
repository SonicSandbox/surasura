"""L1 (P2.4 Part B, charter D31): one cap per language.

Connect's waiting cards are counted per language: `shelf.waiting_count(anki, made)` counts only the waiting cards whose
note is in `made` (one language's store), and every card without `made`. The cap is read per language too:
`connect_backlog_cap` as a {lang: n} dict gives each language its own number, and a plain number is every language's.

What a wrong answer would cost: a Chinese backlog counting Japanese cards (or the reverse) and so holding a whole
language back at the cap, or one language's cap being applied to the other, so one language stops being filled while
the other floods Anki.

Pure: a fake Anki with the two methods the code calls (`find_cards`, `cards_info`), real words, no network, no Anki,
no temp files. The store is not opened: `Steps.waiting_count` is not called, only `shelf.waiting_count` and `cap`.
"""
from app.connect import runner, shelf


class FakeAnki:
    """The two calls `shelf.waiting_count` / `shelf.cards` make: three waiting cards, each in its own note."""

    def __init__(self):
        self.note_of = {1: 11, 2: 12, 3: 13}

    def find_cards(self, query):
        # Why: every query answers the same three waiting cards; the language split is `made`'s job, not the query's.
        return [1, 2, 3]

    def cards_info(self, ids):
        return [{"cardId": i, "note": self.note_of[i]} for i in ids]


# One language's store: note id -> (item id, word). Japanese holds two of the three notes, Chinese the third.
JA_MADE = {11: (1, "勇気"), 12: (1, "約束")}
ZH_MADE = {13: (2, "努力")}


def test_waiting_count_counts_only_the_languages_own_notes():
    # Why: Japanese has two of the three waiting cards in its store, so its cap counts 2, not all 3 of Anki's.
    anki = FakeAnki()
    assert shelf.waiting_count(anki, JA_MADE) == 2
    assert shelf.waiting_count(anki, ZH_MADE) == 1


def test_waiting_count_without_a_store_counts_every_language():
    # Why: with no store given, every waiting card counts (the one-request form), all three of Anki's, not one
    # language's share.
    assert shelf.waiting_count(FakeAnki()) == 3


def test_a_per_language_cap_dict_gives_each_language_its_own_number():
    # Why: Chinese at 50 and Japanese at 300 are read separately; the dict is looked up by the language asked.
    steps = runner.Steps({"connect_enabled": True, "connect_backlog_cap": {"ja": 300, "zh": 50}})
    assert steps.cap("zh") == 50
    assert steps.cap("ja") == 300


def test_a_plain_number_cap_is_every_languages_cap():
    # Why: an older settings.json holds one number; it applies to each language alike, not to the first one asked.
    steps = runner.Steps({"connect_enabled": True, "connect_backlog_cap": 120})
    assert steps.cap("ja") == steps.cap("zh") == 120
