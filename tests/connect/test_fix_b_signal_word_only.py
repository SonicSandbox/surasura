"""Known from Anki: the signal marks the card's word, never the words of its "Also read" lines (P2.4 Part B, final
review; item J21).

What the rule protects: a flagged or suspended card's Word is the word the user is asking about. Its Sentence field
holds other words (種を撒く holds 種 and the whole phrase), and the known-words sync reads those too. If the signal read
the Sentence as well, suspending one card would mark 種 known in KnownWord.json, a word the user never accepted. A wrong
answer here is a word silently added to the user's known list.

Anki is faked at the app.anki_connect functions the reader calls; KnownWord.json and the record live in the per-test
temp root (conftest's SURASURA_TEST_ROOT), so nothing touches the real library or a real Anki.
"""
import contextlib
import json
import os

import pytest

from app import anki_connect
from app.connect import known_signal
from app.path_utils import get_user_files_path

URL = "http://127.0.0.1:8765"
SETTINGS = {"connect_enabled": True, "known_from_anki": ["suspended"]}


class FakeAnki:
    """Cards and notes held in memory; the signal's query is ignored, `found` is what Anki answers. Each note keeps
    its full field map, Word and Sentence alike, as notes_info returns it."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> note id
        self.notes = {}      # note id -> {field name: value}
        self.found = []
        monkeypatch.setattr(anki_connect, "find_cards", lambda url, query: list(self.found))
        monkeypatch.setattr(anki_connect, "cards_info",
                            lambda url, ids: [{"cardId": c, "note": self.cards[c]} for c in ids])
        monkeypatch.setattr(anki_connect, "notes_info", lambda url, ids: [self._note(n) for n in ids])
        monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **kwargs: None)
        monkeypatch.setattr(anki_connect, "writer", lambda *a, **k: contextlib.nullcontext())

    def _note(self, note):
        fields = self.notes[note]
        return {"noteId": note, "modelName": "Basic",
                "fields": {name: {"value": value, "order": i} for i, (name, value) in enumerate(fields.items())}}

    def add(self, card, note, word, sentence):
        self.cards[card] = note
        self.notes[note] = {"Word": word, "Sentence": sentence}


@pytest.fixture
def anki(monkeypatch):
    return FakeAnki(monkeypatch)


@pytest.fixture
def known_file():
    """A KnownWord.json with one unrelated known word, written in the user's folder for the test."""
    folder = get_user_files_path("ja")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "KnownWord.json")
    data = {"words": [{"dictForm": "溜め息", "knownStatus": "KNOWN", "hasCard": 1, "knownBy": "user"}]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


def _known_forms(path):
    with open(path, "r", encoding="utf-8") as f:
        return {w.get("dictForm") for w in json.load(f).get("words", []) if isinstance(w, dict)}


def test_signal_marks_the_word_field_and_never_the_sentence_words(anki, known_file):
    """A card newly suspended after the baseline read marks its Word (撒く) only. Its Sentence (種を撒く) holds 種 and
    the phrase; neither reaches out["marked"] or KnownWord.json. Why: the Sentence's words are the sentence's, not
    the card's word, and the user only suspended the card for 撒く."""
    anki.found = []
    known_signal.read("ja", URL, ["DevTest"], ["Word", "Sentence"], SETTINGS)    # the baseline: no cards yet

    anki.add(201, 11, "撒く", "種を撒く")                                          # the card the user suspends
    anki.found = [201]
    out = known_signal.read("ja", URL, ["DevTest"], ["Word", "Sentence"], SETTINGS)

    assert out["marked"] == ["撒く"]                                              # the Word only
    forms = _known_forms(known_file)
    assert "撒く" in forms                                                        # marked in KnownWord.json
    assert "種を撒く" not in forms and "種" not in forms                          # the Sentence's words stay unknown
