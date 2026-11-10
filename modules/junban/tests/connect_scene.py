# SPDX-License-Identifier: GPL-3.0-or-later
"""The scene P1.4's tests share: `test_preview_gate.SCENE` (every trigger of Connect's preview in one deck) on a fake
collection that also answers the two reads the preview adds — the oldest note Connect made (`findNotes "tag:…::*"`)
and the cards Junban parked (`findCards … is:suspended "tag:…"`). Real Japanese words on real Lapis fields; never Anki.
"""
import os

from modules.junban.tests.test_preview_gate import CONNECT_TAG, KNOWN, SCENE
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, FIRST_CARD, FIRST_NOTE, FakeCollection, _card,
                                                  _known, _results, _settings)

ACTIONS = ("setSpecificValueOfCard", "multi", "suspend", "unsuspend")


def _has_tag(tags, wanted):
    wanted = wanted.lower()
    return any(str(t).lower() == wanted or str(t).lower().startswith(wanted + "::") for t in tags or ())


class ConnectCollection(FakeCollection):
    """FakeCollection plus Connect's reads, honouring the query shapes Junban sends."""

    def __init__(self, cards, notes, **kwargs):
        kwargs.setdefault("actions", ACTIONS)
        super().__init__(cards, notes, **kwargs)

    def _dispatch(self, action, params):
        query = params.get("query", "")
        if action == "findNotes" and '"tag:' in query:
            prefix = query.split('"tag:')[1].split('"')[0].rstrip("*").lower()
            return sorted(n for n, note in self.notes.items()
                          if any(str(t).lower().startswith(prefix) for t in note.get("tags") or ()))
        if action == "findCards" and " is:suspended" in query and "-is:suspended" not in query:
            deck = query.split('deck:"')[1].split('"')[0]
            tag = query.split('"tag:')[1].split('"')[0]
            return sorted(c["cardId"] for c in self.cards.values()
                          if (c["deckName"] == deck or c["deckName"].startswith(deck + "::"))
                          and c["type"] == 0 and c["queue"] == -1 and not c.get("odeck")
                          and _has_tag(self.notes[c["note"]].get("tags"), tag))
        return super()._dispatch(action, params)

    def card_of(self, word):
        for card in self.cards.values():
            if self.notes[card["note"]]["fields"]["Expression"]["value"] == word:
                return card
        raise KeyError(word)

    def queue_order(self):
        """The unsuspended new cards' words, in the order Anki will show them."""
        new = [c for c in self.cards.values() if c["type"] == 0 and c["queue"] == 0]
        new.sort(key=lambda c: (c["due"], c["cardId"]))
        return [self.notes[c["note"]]["fields"]["Expression"]["value"] for c in new]


def scene(tmp_path, entries=None, start=300, **kwargs):
    """The scene's collection (`entries` as `SCENE`'s rows: word, sentence, FreqSort, tags, queue), with the list, the
    library map and the known words written under `tmp_path`."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    _known(tmp_path, KNOWN)
    cards, notes = [], []
    for i, (word, sentence, freqsort, tags, queue) in enumerate(SCENE if entries is None else entries):
        note_id = FIRST_NOTE + start + i
        notes.append({"noteId": note_id, "modelName": "Lapis", "tags": list(tags), "fields": {
            "Expression": {"value": word, "order": 0},
            "Sentence": {"value": sentence, "order": 1},
            "FreqSort": {"value": str(freqsort), "order": 2},
            "MiscInfo": {"value": "", "order": 3}}})
        card = _card(FIRST_CARD + start + i, note_id, 2800 + i)
        card["queue"] = queue
        cards.append(card)
    return ConnectCollection(cards, notes, **kwargs)


def settings(preview=True, **over):
    """The 順 window's saved choices — content order, all three "not on your list" actions — with the preview on."""
    base = dict(junban_order="content", junban_later_tag=True, junban_later_flag=True, junban_later_suspend=True,
                connect_enabled=preview, enable_junban=True)
    base.update(over)
    return _settings(**base)


def without_connect(entries=None):
    """The scene's rows with Connect's tag taken off: nothing is "yours" until Connect has made a card."""
    return [(word, sentence, freqsort, [t for t in tags if t != CONNECT_TAG], queue)
            for word, sentence, freqsort, tags, queue in (SCENE if entries is None else entries)]


def runs_on_disk(language="ja"):
    from modules.junban import undo
    folder = undo.runs_folder(language)
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


__all__ = ["CONNECT_TAG", "ConnectCollection", "scene", "settings", "runs_on_disk"]
