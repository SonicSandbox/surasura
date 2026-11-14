"""What Anki knows of the learner's words (`app/anki_words.py`, Piyo-AK): each studied note's standing — leech,
lapses, how hard, young or mature, learned today — read live through a fake AnkiConnect, never live Anki.

**Why it matters:** Piyo's rounds from Anki (struggling, today, known) and the word hover read the learner's cards
through this one reader. A struggling round that shows easy cards, a "known" round with a word still being learned, a
card from a deck the learner didn't choose, or a word counted twice for its two cards would practise the wrong words;
and it must stay light on Anki (one request of searches, nothing rendered) and never write.

`CardCollection` judges every search card by card, as Anki does (a note is found when ONE of its cards matches every
term): deck (subdecks too), `-is:new`, `-is:suspended`, `(-is:suspended OR tag:leech)`, `tag:leech`, `prop:lapses`,
`prop:d` (FSRS's difficulty; refused by an Anki without FSRS), `prop:ease`, `prop:ivl` and `introduced:1` (refused by
an Anki too old for it). Real Japanese (tests/Test Resources/ja/context_test.txt) and Chinese (zh/context_test.txt).
"""
import re
from unittest import mock

import pytest

from app import anki_connect, anki_words
from app.anki_connect import AnkiError
from tests.test_anki_sync import URL, FakeCollection, _ok

JA_DECK = "日本語::Mining"


class CardCollection(FakeCollection):
    """FakeCollection whose notes carry cards: each {ivl, lapses, d, ease, new, suspended, today}."""

    def __init__(self, fsrs=True, introduced=True, busy=False, **kw):
        super().__init__(**kw)
        self.fsrs, self.introduced, self.busy = fsrs, introduced, busy

    def card_note(self, word, cards, deck=JA_DECK, leech=False, **kw):
        """A note of `cards`; a card's own `deck` (Anki keeps the deck per card) defaults to the note's."""
        note_id = self.add(word, deck=deck, **kw)
        full = []
        for card in cards:
            full.append({"ivl": 0, "lapses": 0, "d": None, "ease": 2.5, "new": False, "suspended": False,
                         "today": False, "deck": deck, **card})
        self.note(note_id).update(cards=full, leech=leech)
        return note_id

    def _answer(self, payload):
        if self.busy and payload["action"] == "multi":
            return {"result": None, "error": "a collection operation is active"}
        if payload["action"] == "findNotes":
            query = payload["params"]["query"]
            if "prop:d" in query and not self.fsrs:
                return {"result": None, "error": "Invalid search: prop:d"}
            if "introduced:" in query and not self.introduced:
                return {"result": None, "error": "Invalid search: introduced:1"}
            return _ok(self._card_find(query))
        return super()._answer(payload)

    def _card_find(self, query):
        decks = [self._unescape(d) for d in re.findall(r'deck:"((?:[^"\\]|\\.)*)"', query)]
        out = []
        for n in self.notes:
            if any(any(c["deck"] == d or c["deck"].startswith(d + "::") for d in decks)
                   and self._card_matches(query, c, n["leech"]) for c in n["cards"]):
                out.append(n["noteId"])
        return out

    @staticmethod
    def _card_matches(query, c, leech):
        rest = query
        if "(-is:suspended OR tag:leech)" in rest:
            if c["suspended"] and not leech:
                return False
            rest = rest.replace("(-is:suspended OR tag:leech)", "")
        if "-is:new" in rest and c["new"]:
            return False
        if "-is:suspended" in rest and c["suspended"]:
            return False
        if "tag:leech" in rest and not leech:
            return False
        if "introduced:1" in rest and not c["today"]:
            return False
        for prop, op, value in re.findall(r"prop:(\w+)(>=|<|=)([\d.]+)", rest):
            have = c[{"lapses": "lapses", "d": "d", "ease": "ease", "ivl": "ivl"}[prop]]
            if have is None:
                return False
            value = float(value)
            if not {">=": have >= value, "<": have < value, "=": have == value}[op]:
                return False
        return True

    def multis(self):
        return [r for r in self.requests if r["action"] == "multi"]


def _settings(decks=(JA_DECK,), fields=(), language="ja"):
    return {"anki_sync_decks": {language: list(decks)}, "anki_sync_fields": {language: list(fields)},
            "anki_connect_url": URL}


def _practise(fake, source, limit=10, language="ja", settings=None):
    with mock.patch("urllib.request.urlopen", fake):
        found = anki_words.practise(language, source, limit, settings or _settings(language=language))
    return None if found is None else [(row["word"], row["lapses"], row["leech"]) for row in found]


def _deck():
    """A learner's mined deck, from the words of tests/Test Resources/ja/context_test.txt."""
    fake = CardCollection()
    ids = {
        "冒険": fake.card_note("冒険", [{"ivl": 2, "lapses": 3, "ease": 2.1}]),
        "準備": fake.card_note("準備", [{"ivl": 1, "lapses": 6, "ease": 1.3}], leech=True, ),
        "危険": fake.card_note("危険", [{"ivl": 0, "lapses": 8, "suspended": True}], leech=True),   # suspended leech
        "価値": fake.card_note("価値", [{"ivl": 40}, {"ivl": 25}]),                                  # mature, both cards
        "有名": fake.card_note("有名", [{"ivl": 30}, {"ivl": 4, "lapses": 1}]),                      # one card young
        "冒険家": fake.card_note("冒険家", [{"new": True}]),                                          # never studied
        "求める": fake.card_note("求める", [{"ivl": 1, "today": True}]),
        "今夜": fake.card_note("今夜", [{"ivl": 0, "today": True}]),
        "素晴らしい": fake.card_note("素晴らしい", [{"ivl": 60, "lapses": 2, "suspended": True}]),   # put away
        "出かける": fake.card_note("出かける", [{"ivl": 90}]),
    }
    return fake, ids


# --------------------------------------------------------------------------- #
# Each source: the right cards in the right order
# --------------------------------------------------------------------------- #
def test_struggling_is_anki_s_leeches_first_then_the_most_forgotten_and_never_a_new_or_put_away_card():
    """A leech Anki suspended (its leech action) is still struggling; a card the learner suspended (not a leech), a
    new card and a card never forgotten aren't. Among the leeches, and then the rest, the most lapses first."""
    fake, _ids = _deck()
    assert _practise(fake, "struggling") == [("危険", 8, True), ("準備", 6, True), ("冒険", 3, False),
                                             ("有名", 1, False)]


def test_a_leech_comes_before_a_card_forgotten_more_and_stays_struggling_once_its_lapses_were_reset():
    """Anki's leech tag outranks lapses: a leech forgotten twice comes before a card forgotten five times; and a leech
    whose card was reset (Anki's Forget, its lapses back at 0) keeps its tag, so it is still struggling."""
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3, "lapses": 5}])
    fake.card_note("準備", [{"ivl": 3, "lapses": 2}], leech=True)
    fake.card_note("危険", [{"ivl": 1}], leech=True)
    assert _practise(fake, "struggling") == [("準備", 2, True), ("危険", 0, True), ("冒険", 5, False)]


def test_struggling_breaks_a_tie_in_lapses_by_how_hard_the_card_is_fsrs_or_ease():
    """Equal lapses: FSRS's difficulty (prop:d) or SM-2's ease (prop:ease) says which is harder; then the newest."""
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3, "lapses": 2, "d": 0.55}])
    fake.card_note("準備", [{"ivl": 3, "lapses": 2, "d": 0.95}])        # FSRS: the hardest
    fake.card_note("価値", [{"ivl": 3, "lapses": 2, "ease": 1.5}])      # SM-2: low ease, past all three steps
    fake.card_note("有名", [{"ivl": 3, "lapses": 2}])
    assert [w for w, *_ in _practise(fake, "struggling")] == ["準備", "価値", "冒険", "有名"]


def test_an_anki_without_fsrs_still_ranks_struggling_cards_by_lapses_and_ease():
    """An Anki before FSRS refuses `prop:d`: that search counts as none, never as a failed read."""
    fake = CardCollection(fsrs=False)
    fake.card_note("冒険", [{"ivl": 3, "lapses": 2, "ease": 2.4}])
    fake.card_note("準備", [{"ivl": 3, "lapses": 2, "ease": 1.5}])
    fake.card_note("価値", [{"ivl": 3, "lapses": 5}])
    assert [w for w, *_ in _practise(fake, "struggling")] == ["価値", "準備", "冒険"]


def test_ten_lapses_or_more_count_as_the_most():
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3, "lapses": 9}])
    fake.card_note("準備", [{"ivl": 3, "lapses": 23}])
    assert _practise(fake, "struggling") == [("準備", anki_words.LAPSES_MOST, False), ("冒険", 9, False)]


def test_today_is_the_cards_first_studied_today_the_newest_first():
    fake, _ids = _deck()
    assert [w for w, *_ in _practise(fake, "today")] == ["今夜", "求める"]


def test_known_is_the_mature_cards_only_when_every_studied_card_of_the_note_is_mature():
    """有名's recognition card is mature but its production card is still young: not known well yet. A mature card the
    learner suspended, or a leech, is no known frame either."""
    fake, _ids = _deck()
    fake.card_note("問題", [{"ivl": 50, "lapses": 9}], leech=True)
    assert [w for w, *_ in _practise(fake, "known")] == ["出かける", "価値"]


def test_a_word_with_two_cards_or_two_notes_counts_once_with_its_worst_card():
    """Two cards of one note: the note is found once, at its most forgotten card. Two notes of one word (mined twice):
    the word comes once, from its first note in the order."""
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3, "lapses": 1}, {"ivl": 2, "lapses": 4}])
    fake.card_note("冒険", [{"ivl": 3, "lapses": 2}])
    fake.card_note("準備", [{"ivl": 3, "lapses": 3}])
    assert _practise(fake, "struggling") == [("冒険", 4, False), ("準備", 3, False)]


def test_a_deck_outside_the_mined_decks_is_ignored_and_a_subdeck_is_read():
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3, "lapses": 4}], deck="Core 2k")
    fake.card_note("準備", [{"ivl": 3, "lapses": 2}], deck=JA_DECK + "::Show")
    fake.card_note("危険", [{"ivl": 3, "lapses": 1}], deck="日本語::Mining2")      # a sibling, not a subdeck
    assert _practise(fake, "struggling") == [("準備", 2, False)]


def test_a_card_moved_to_a_deck_outside_the_mined_decks_counts_for_nothing():
    """Anki keeps the deck per card: a note's production card moved to another deck (forgotten 9 times there) is not
    the learner's mined card; its recognition card, in the mined deck, is what counts."""
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3, "lapses": 1}, {"ivl": 3, "lapses": 9, "deck": "Core 2k"}])
    fake.card_note("準備", [{"ivl": 3, "lapses": 2}])
    assert _practise(fake, "struggling") == [("準備", 2, False), ("冒険", 1, False)]


def test_the_word_is_the_known_syncs_word_field_read_as_junban_reads_a_card():
    """撒く<br>まく is 撒く (anki_match.card_word), and the chosen word field is read, never the sentence."""
    fake = CardCollection()
    fake.card_note("撒く", [{"ivl": 3, "lapses": 2}], fields=[("Sentence", "種を撒く。"), ("Word", "撒く<br>まく")])
    assert _practise(fake, "struggling", settings=_settings(fields=["Word"])) == [("撒く", 2, False)]


def test_chinese_cards_are_read_the_same_way():
    fake = CardCollection()
    fake.card_note("冒险", [{"ivl": 3, "lapses": 5}], deck="中文")
    fake.card_note("挑战", [{"ivl": 0, "today": True}], deck="中文")
    fake.card_note("勇敢", [{"ivl": 30}], deck="中文")
    settings = _settings(decks=["中文"], language="zh")
    for source, words in (("struggling", ["冒险"]), ("today", ["挑战"]), ("known", ["勇敢"])):
        assert [w for w, *_ in _practise(fake, source, language="zh", settings=settings)] == words


# --------------------------------------------------------------------------- #
# Light on Anki, read-only
# --------------------------------------------------------------------------- #
def test_one_request_of_searches_then_the_words_only_as_far_as_the_limit_needs():
    """No cardsInfo (it renders every card), no getIntervals, nothing but reads; notesInfo stops once `limit` words
    are found."""
    fake = CardCollection()
    for n, word in enumerate(["冒険", "準備", "危険", "価値", "有名", "求める", "今夜", "出かける"] * 10):
        fake.card_note(word + str(n), [{"ivl": 3, "lapses": 1 + n % 9}])
    with mock.patch("urllib.request.urlopen", fake):
        found = anki_words.practise("ja", "struggling", 3, _settings())
    assert len(found) == 3
    assert len(fake.multis()) == 1
    assert set(fake.actions) == {"multi", "notesInfo"}
    assert len(fake.notes_info_ids()) <= 50, "only the first chunk of notes was asked for its word"
    subs = [a["action"] for r in fake.multis() for a in r["params"]["actions"]]
    assert set(subs) == {"findNotes"} and "notesInfo" in anki_connect.READ_ACTIONS


def test_a_needed_search_anki_refuses_fails_the_read_never_a_partial_ranking():
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3, "lapses": 2}])
    original = fake._answer

    def refuse_lapses(payload):
        if payload["action"] == "findNotes" and "prop:lapses=2" in payload["params"]["query"]:
            return {"result": None, "error": refused}
        return original(payload)
    fake._answer = refuse_lapses
    for refused, busy in (("Invalid search", False), ("a collection operation is active", True)):
        with pytest.raises(AnkiError) as raised:
            _practise(fake, "struggling")
        assert anki_connect.is_busy(raised.value) is busy, "a slot refused while Anki is busy is Anki busy"


# --------------------------------------------------------------------------- #
# Empty, closed, too old, no decks
# --------------------------------------------------------------------------- #
def test_no_leech_no_lapse_nothing_today_and_nothing_mature_give_no_words():
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3}])
    fake.card_note("準備", [{"new": True}])
    for source in anki_words.SOURCES:
        assert _practise(fake, source) == []


def test_no_studied_card_at_all_is_another_profile_or_renamed_decks_never_none_and_no_word_says_so():
    """Decks with no studied card (Anki open on another profile, the decks renamed) are no "you have none" — the
    young cards' sync reads it the same way; cards with no word in the chosen word field are their own answer."""
    fake = CardCollection()
    fake.card_note("冒険", [{"new": True}])
    with mock.patch("urllib.request.urlopen", fake):
        for source in anki_words.SOURCES:
            with pytest.raises(anki_words.NoneStudied):
                anki_words.practise("ja", source, 5, _settings())
    fake = CardCollection()
    fake.card_note("冒険", [{"ivl": 3, "lapses": 2}], fields=[("Sentence", "冒険は危険だが、価値がある。"),
                                                             ("Word", "")])
    with mock.patch("urllib.request.urlopen", fake), pytest.raises(anki_words.NoWords):
        anki_words.practise("ja", "struggling", 5, _settings(fields=["Word"]))


def test_an_anki_too_old_to_say_what_was_learned_today_says_so_and_the_rest_still_work():
    fake = CardCollection(introduced=False)
    fake.card_note("冒険", [{"ivl": 3, "lapses": 2, "today": True}])
    assert _practise(fake, "today") is None
    assert _practise(fake, "struggling") == [("冒険", 2, False)]


def test_anki_closed_or_busy_raises_and_no_deck_chosen_is_its_own_answer():
    with pytest.raises(AnkiError):
        _practise(CardCollection(offline=True), "struggling")
    busy = CardCollection(busy=True)
    with mock.patch("urllib.request.urlopen", busy), pytest.raises(AnkiError) as raised:
        anki_words.practise("ja", "known", 5, _settings())
    assert anki_connect.is_busy(raised.value)
    fake, _ids = _deck()
    with mock.patch("urllib.request.urlopen", fake), pytest.raises(anki_words.NoDecks):
        anki_words.practise("ja", "struggling", 5, _settings(decks=()))
    assert fake.requests == [], "no deck: Anki isn't asked at all"


# --------------------------------------------------------------------------- #
# The word hover's reader
# --------------------------------------------------------------------------- #
def test_word_states_give_each_word_its_standing_merged_over_its_notes():
    fake, _ids = _deck()
    fake.card_note("冒険", [{"ivl": 30, "lapses": 1}])          # 冒険 mined again: mature, but the first is young
    with mock.patch("urllib.request.urlopen", fake):
        states = anki_words.word_states("ja", _settings())
    assert set(states) == {"冒険", "準備", "危険", "価値", "有名", "求める", "今夜", "出かける"}
    assert (states["冒険"].lapses, states["冒険"].young, states["冒険"].mature) == (3, True, False)
    assert states["危険"].leech and not states["危険"].young        # a suspended leech: no studied card in play
    assert states["価値"].mature and not states["価値"].young
    assert states["求める"].today and states["求める"].young
