"""Kantan-B2: what counts as known when cards are suspended (a new tester, 2026-11-18: "if Junban is set to tag later
and suspend cards, will they all then be marked known with this setting on?").

The facts, settled from the code by the lead (2026-11-18) and pinned here end to end — a card's state in Anki → the
search Surasura sends → the words marked known:
- *Count as known in Anki* (`known_signal`, the default term *Suspended*) counts a card **you** suspended, a new one
  included — Sonic's own workflow;
- **Surasura's own suspensions never count**: Junban's later cards (`Surasura::later`, or `<your tag>::later`), *Take
  its new cards out*'s (`::out`), Connect's shelf (`surasura::shelf`) — and Anki's leeches;
- the known-words sync (`anki_sync.scope_query`) reads studied cards only (`-is:new`): a new card — a later one too —
  never counts there.

The stand-in Anki answers the search as Anki's own search does for these terms (a tag matches itself and its children,
any case; `-` excludes), so a search that lost an exclusion would mark a 順-later word known. What a wrong answer would
cost: every word Junban set aside for later marked known — the learner's list and journey would skip words he never
learnt. Real words, ja + zh; KnownWord.json and the record in the test's temp root; never a live Anki.
"""
import contextlib
import json
import os
import re

import pytest

from app import anki_connect, anki_sync
from app.connect import known_signal
from app.path_utils import get_user_files_path

URL = "http://127.0.0.1:8765"
DECK = "Mining"


def _tag_hit(tags, wanted):
    wanted = wanted.lower()
    return any(t.lower() == wanted or t.lower().startswith(wanted + "::") for t in tags)


class SearchingAnki:
    """Cards held in memory; `find_cards` answers the search the way Anki does for the terms Surasura sends."""

    def __init__(self, monkeypatch):
        self.cards = {}      # card id -> {"word", "new", "suspended", "tags", "note"}
        self.queries = []
        monkeypatch.setattr(anki_connect, "find_cards", self.find)
        monkeypatch.setattr(anki_connect, "cards_info",
                            lambda url, ids: [{"cardId": c, "note": self.cards[c]["note"]} for c in ids])
        monkeypatch.setattr(anki_connect, "notes_info", lambda url, ids: [self._note(n) for n in ids])
        monkeypatch.setattr(anki_connect, "invoke", lambda action, url, **kwargs: "DevTest")
        monkeypatch.setattr(anki_connect, "writer", lambda *a, **k: contextlib.nullcontext())

    def add(self, card, word, new=True, suspended=False, tags=(), flag=0):
        self.cards[card] = {"word": word, "new": new, "suspended": suspended, "tags": list(tags), "note": card + 1000,
                            "flag": flag}

    def _note(self, note):
        card = next(c for c in self.cards.values() if c["note"] == note)
        return {"noteId": note, "modelName": "Lapis", "fields": {"Word": {"value": card["word"], "order": 0}}}

    def find(self, url, query):
        self.queries.append(query)
        assert query.startswith(f'(deck:"{DECK}")'), query
        terms = re.findall(r'-?[a-z]+:[^\s]+', query.split(")", 1)[1])
        out = []
        for cid, card in sorted(self.cards.items()):
            ok = True
            for term in terms:
                neg, (key, value) = term.startswith("-"), term.lstrip("-").split(":", 1)
                if key == "is":
                    hit = card["suspended"] if value == "suspended" else card["new"] if value == "new" else False
                elif key == "tag":
                    hit = _tag_hit(card["tags"], value)
                elif key == "flag":                    # Anki's flag:n (Kotoba-WS2: -flag:1 / -flag:3 on every search)
                    hit = card["flag"] == int(value)
                else:
                    raise AssertionError(f"a term this stand-in doesn't know: {term}")
                ok = ok and (hit != neg)
            if ok:
                out.append(cid)
        return out


@pytest.fixture
def anki(monkeypatch):
    return SearchingAnki(monkeypatch)


def _known_forms(language):
    path = os.path.join(get_user_files_path(language), "KnownWord.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {w.get("dictForm") for w in json.load(f).get("words", []) if isinstance(w, dict)}


WORDS = {"ja": ("残念", "綺麗", "大丈夫", "泥棒", "諦める"), "zh": ("遗憾", "漂亮", "没关系", "小偷", "放弃")}


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("junban_tag", ["", "MyTag"])
def test_a_junban_later_card_suspended_is_never_known_and_one_you_suspended_is(anki, language, junban_tag):
    # why: Junban's later suspends a whole backlog of new cards; with the default term on, only the learner's own
    # suspensions may say "I know this"
    later, mine, out, shelf, leech = WORDS[language]
    parent = junban_tag or "Surasura"
    settings = {"connect_enabled": True, "known_from_anki": ["suspended"], "junban_tag": junban_tag}
    known_signal.read(language, URL, [DECK], [], settings)                      # the baseline: nothing signalled yet
    anki.add(1, later, new=True, suspended=True, tags=[f"{parent}::later"])     # Junban: not on your list, for later
    anki.add(2, mine, new=True, suspended=True)                                  # suspended by hand, never studied
    anki.add(3, out, new=True, suspended=True, tags=[f"{parent.lower()}::out"])  # *Take its new cards out*
    anki.add(4, shelf, new=False, suspended=True, tags=["surasura::shelf"])      # Connect's shelf
    anki.add(5, leech, new=False, suspended=True, tags=["leech"])                # Anki's own leech
    got = known_signal.read(language, URL, [DECK], [], settings)
    assert got["marked"] == [mine]
    assert later not in _known_forms(language) and mine in _known_forms(language)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_known_words_sync_never_reads_a_new_card_later_or_not(anki, language):
    # why: the sync counts studied cards; a 順-later card is new, so it is never known through the sync either
    later, mine, *_rest = WORDS[language]
    anki.add(1, later, new=True, suspended=True, tags=["Surasura::later"])
    anki.add(2, mine, new=False, suspended=False)
    for include in (False, True):
        assert anki.find(URL, anki_sync.scope_query([DECK], include_suspended=include)) == [2]
