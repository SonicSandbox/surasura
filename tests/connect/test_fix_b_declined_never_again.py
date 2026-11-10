"""Known from Anki: a declined offer's cards are never offered again (P2.4 Part B final-adversary fix, J20).

What the rule protects: when the user declines the one-time offer, its cards go into the record's `declined` set. A
later read that starts a new offer (here, after a switch of Anki profile, which changes the scope) must leave those
cards out, so the user is not asked again about words they already turned down. A wrong answer here would re-offer
declined words every time the scope changes, and the user would have to answer the same question over and over.

Anki is faked at the app.anki_connect functions the reader calls; the record lives in the per-test temp root
(conftest's SURASURA_TEST_ROOT), so nothing touches the real library or a real Anki.
"""
import pytest

from app import anki_connect
from app.connect import known_signal

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True}  # known_from_anki defaults to ["suspended"]

# Real Japanese words, one note each.
UPPER = (201, 11, "上層部")
ISSHO = (202, 12, "一生懸命")


class FakeAnki:
    """The signal's cards: a card is signalled while it sits in `suspended`. The active profile is switchable."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> note id
        self.words = {}      # note id -> the Expression field
        self.suspended = set()
        self.profile = "Default"
        monkeypatch.setattr(anki_connect, "find_cards", self._find_cards)
        monkeypatch.setattr(anki_connect, "cards_info", self._cards_info)
        monkeypatch.setattr(anki_connect, "notes_info", self._notes_info)
        monkeypatch.setattr(anki_connect, "invoke", self._invoke)

    def add(self, card, note, word, signalled=True):
        self.cards[card] = note
        self.words[note] = word
        if signalled:
            self.suspended.add(card)

    def _find_cards(self, url, query):
        return sorted(self.suspended)

    def _cards_info(self, url, ids):
        return [{"cardId": c, "note": self.cards[c]} for c in ids]

    def _notes_info(self, url, ids):
        return [{"noteId": n, "modelName": "Lapis",
                 "fields": {"Expression": {"value": self.words[n], "order": 0}}} for n in ids]

    def _invoke(self, action, *args, **kwargs):
        # The reader asks only the active profile (its scope key); any other Anki call here is a test bug.
        assert action == "getActiveProfile", f"unexpected AnkiConnect action {action!r}"
        return self.profile


@pytest.fixture
def anki(monkeypatch):
    return FakeAnki(monkeypatch)


def test_a_declined_card_is_not_offered_again_after_a_scope_change(anki):
    """The user declines 上層部's offer. Later, 上層部's card is un-suspended while 一生懸命's is signalled (a read under
    another profile records 一生懸命 as seen, so 上層部 is no longer seen). Then 上層部 is signalled again under the first
    profile: that is a new read of an unseen card, but the declined 上層部 must not go back into the offer."""
    anki.add(*UPPER)
    anki.add(*ISSHO, signalled=False)
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    assert [c["card"] for c in known_signal.load("ja")["offer"]["cards"]] == [UPPER[0]]

    known_signal.decline_offer("ja")
    assert known_signal.load("ja")["declined"] == [UPPER[0]]

    anki.suspended = {ISSHO[0]}               # 上層部 un-suspended, 一生懸命 signalled
    anki.profile = "Other"
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)
    assert known_signal.load("ja")["seen"] == [ISSHO[0]]

    anki.suspended = {UPPER[0], ISSHO[0]}     # 上層部 signalled again, as an unseen card
    anki.profile = "Default"
    known_signal.read("ja", URL, ["DevTest"], ["Expression"], SETTINGS)

    state = known_signal.load("ja")
    assert state["offer"]["state"] == "pending"
    assert [c["card"] for c in state["offer"]["cards"]] == [ISSHO[0]], "the declined 上層部 is not offered again"
