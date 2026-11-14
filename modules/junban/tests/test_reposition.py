# SPDX-License-Identifier: GPL-3.0-or-later
"""The orchestration, end to end, against a fake collection — never the real one.

**No test here may touch Anki.** The developer's own collection lives on this machine; `urlopen` is
intercepted by `FakeCollection`, which keeps the cards in a dict and answers in real JSON bytes, so
every branch downstream of `json.loads` decides against plain data and no `MagicMock` can fake its
way through one (`testing.md` §5.3, spec §18.0 rule 6).

What this file is actually guarding, in order of how much it would cost the user:

  * **The snapshot must reach disk before the first write.** `setSpecificValueOfCard` hardcodes
    `skip_undo_entry=True`, so a run that repositions a backlog creates zero Anki undo entries and
    this file is the only way back (invariant I3). The test does not check that `undo.save` was
    called — it checks that the file was *readable on disk* at the instant the first write arrived,
    which is the only version of the claim that matters.
  * **A half-finished run must still be undoable.** Anki disappearing mid-run is the ordinary
    failure here: it is a desktop app the user can close. The cards already written stay written,
    the snapshot stays intact and complete, and the report says how far it got.
  * **Preflight must refuse rather than repair.** Random new-card order, a missing AnkiConnect
    action and a missing priority list each stop the run; a stale library only warns, because
    hijacking a seconds-long reposition into a minutes-long analysis is the surprise §15 #5 forbids.
  * **The preview must perform no writes at all.**

Words and ranks come from a real Surasura export (`tests/Test Resources/ja/expected_output.csv` —
row index *is* the rank, exactly as `priority_learning_list.csv` is read), so the match index is
real linguistic data including the orth/lemma disagreements the whole feature turns on, rather than
ASCII stand-ins (`testing.md` §1).
"""
import csv
import json
import os
import urllib.error
from unittest import mock

import pytest

import modules.junban as junban
from modules.junban import reposition, spaced, undo

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_RESOURCE_CSV = os.path.join(_ROOT, "tests", "Test Resources", "ja", "expected_output.csv")

URL = "http://127.0.0.1:8765"

# Real card ids from the verified 2026-09-17 proof-of-concept run, so ids have the magnitude of
# genuine Anki data rather than 1/2/3.
FIRST_CARD = 1789712080000
FIRST_NOTE = 1789712000000

# Real Japanese words the fixture export does NOT rank — ordinary vocabulary of the kind a learner
# mines indiscriminately. Asserted to be absent, so the day the resource changes the suite says so.
UNRANKED = ["須藤", "鳥取", "美術館", "新幹線", "味噌汁", "洗濯機"]


# --------------------------------------------------------------------------- #
# The fake collection
# --------------------------------------------------------------------------- #
class _FakeResponse:
    """Minimal stand-in for what `urlopen` yields: a context manager with `.read()`."""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class AnkiRefusal:
    """AnkiConnect answering `{"result": null, "error": "…"}` — it heard us and said no.

    Distinct from raising: a refusal is a reply, and the client has to read `error` rather than
    assume the socket died. The two failures need different handling and different messages.
    """

    def __init__(self, message):
        self.message = message


class FakeCollection:
    """One Anki collection, in a dict, behind a mocked `urlopen`.

    Holds real state rather than canned replies: a write actually changes the card, so a test can
    assert on where the cards ended up instead of on which calls were made. `writes` records every
    `(card_id, due)` that reached the wire, in order, which is what the ordering claims are checked
    against.
    """

    def __init__(self, cards, notes, new_order=1, actions=("setSpecificValueOfCard", "multi"),
                 offline=False, fail_write_chunk=None, on_write=None, on_note_write=None,
                 refuse_note_writes="", reviewing=False):
        self.cards = {card["cardId"]: dict(card) for card in cards}
        self.notes = {note["noteId"]: note for note in notes}
        self.new_order = new_order
        self.actions = list(actions)
        self.offline = offline
        self.fail_write_chunk = fail_write_chunk    # 1-based index of the write `multi` that dies
        self.on_write = on_write                    # called once, when the first write arrives
        self.on_note_write = on_note_write          # called once, when the first FIELD write arrives
        self.refuse_note_writes = refuse_note_writes    # AnkiConnect's error text, if it refuses
        self.reviewing = reviewing                  # `guiReviewActive`: the user is mid-review

        self.requests = []                          # every envelope, in order
        self.writes = []                            # (card_id, due) pairs that reached Anki
        self.write_chunks = 0
        self.note_writes = []                       # (note_id, {field: value}) that reached Anki
        self.tag_calls = []                         # (action, [note_id], tag)
        self.flag_writes = []                       # (card_id, flag) that reached Anki
        self.suspend_calls = []                     # ("suspend" | "unsuspend", [card_id])

    # --- wire ------------------------------------------------------------- #
    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append(payload)
        if self.offline:
            raise urllib.error.URLError("[WinError 10061] No connection could be made")
        result = self._dispatch(payload["action"], payload.get("params") or {})
        if isinstance(result, Exception):
            raise result
        envelope = ({"result": None, "error": result.message} if isinstance(result, AnkiRefusal)
                    else {"result": result, "error": None})
        body = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        return _FakeResponse(body)

    @property
    def action_names(self):
        return [request["action"] for request in self.requests]

    # --- actions ---------------------------------------------------------- #
    def _dispatch(self, action, params):
        if action == "requestPermission":
            return {"permission": "granted", "requireApikey": False, "version": 6}
        if action == "version":
            return 6
        if action == "apiReflect":
            return {"scopes": ["actions"],
                    "actions": [name for name in params.get("actions", []) if name in self.actions]}
        if action == "deckNames":
            return sorted({card["deckName"] for card in self.cards.values()} | set(getattr(self, "more_decks", ())))
        if action == "getDeckConfig":
            return dict({"name": "Default", "new": {"order": self.new_order, "perDay": getattr(self, "per_day", 20)}},
                        **getattr(self, "serve", {}))       # R1: `newGatherPriority` / `newSortOrder`, when set
        if action == "findCards":
            return self._find(params.get("query", ""))
        if action == "cardsInfo":
            return [dict(self.cards[card_id]) for card_id in params.get("cards", [])
                    if card_id in self.cards]
        if action == "notesInfo":
            return [self.notes[note_id] for note_id in params.get("notes", [])
                    if note_id in self.notes]
        if action == "updateNoteFields":
            return self._update_note(params.get("note") or {})
        if action in ("addTags", "removeTags"):
            return self._tags(action, params)
        if action in ("suspend", "unsuspend"):
            return self._suspend(action, params.get("cards") or [])
        if action == "multi":
            return self._multi(params.get("actions") or [])
        if action == "guiReviewActive":
            return self.reviewing
        if action in ("reloadCollection", "guiDeckBrowser"):
            return None
        return None

    def _find(self, query):
        """Honour the one query shape this module sends: `deck:"X" is:new -is:suspended
        -deck:filtered`. As in Anki, a card sitting in a filtered deck (`odeck` = its home deck)
        still matches its HOME deck — unless the query excludes filtered decks."""
        deck = query.split('"')[1] if '"' in query else ""
        found = []
        for card in self.cards.values():
            if card.get("odeck") and "-deck:filtered" in query:
                continue
            homes = [card["deckName"]] + ([card["odeck"]] if card.get("odeck") else [])
            in_deck = any(home == deck or home.startswith(deck + "::") for home in homes)
            if in_deck and card["type"] == 0 and card["queue"] == 0:
                if "-card:1" in query and not card.get("ord"):  # gap 1: a note's second card or later only
                    continue
                found.append(card["cardId"])
        return sorted(found)

    def _update_note(self, note):
        """`updateNoteFields` — real state, so a test asserts on what the note HOLDS afterwards.

        Returns `None` on success, as AnkiConnect does: the `[True]` rule belongs to
        `setSpecificValueOfCard` alone, and a client that demanded it here would report every
        successful edit as a failure.
        """
        if self.on_note_write is not None and not self.note_writes:
            self.on_note_write()
        if self.refuse_note_writes:
            return AnkiRefusal(self.refuse_note_writes)
        note_id = note.get("id")
        values = note.get("fields") or {}
        self.note_writes.append((note_id, dict(values)))
        stored = self.notes.get(note_id)
        if stored:
            for name, value in values.items():
                stored.setdefault("fields", {}).setdefault(name, {})["value"] = value
        return None

    def _tags(self, action, params):
        notes = list(params.get("notes") or [])
        tag = params.get("tags")
        self.tag_calls.append((action, notes, tag))
        for note_id in notes:
            stored = self.notes.get(note_id)
            if not stored:
                continue
            tags = list(stored.get("tags") or [])
            if action == "addTags":
                if tag not in tags:
                    tags.append(tag)
            else:
                tags = [name for name in tags if name != tag]
            stored["tags"] = tags
        return None

    def _suspend(self, action, card_ids):
        """As AnkiConnect answers, measured on TheBank 2026-09-23: `suspend` -> true (false when every
        card was already suspended), `unsuspend` -> null. A new card goes back to queue 0."""
        self.suspend_calls.append((action, list(card_ids)))
        changed = False
        for card_id in card_ids:
            card = self.cards.get(card_id)
            if not card:
                continue
            if action == "suspend" and card["queue"] != -1:
                card["queue"], changed = -1, True
            elif action == "unsuspend" and card["queue"] == -1:
                card["queue"] = card["type"]
        return changed if action == "suspend" else None

    def _multi(self, actions):
        writes = [entry for entry in actions
                  if entry.get("action") == "setSpecificValueOfCard"
                  and (entry.get("params") or {}).get("keys") == ["due"]]
        if writes:
            self.write_chunks += 1
            if self.on_write is not None and self.write_chunks == 1:
                self.on_write()
            if self.fail_write_chunk == self.write_chunks:
                # Anki was closed mid-run: the socket dies, and nothing in this chunk lands.
                raise urllib.error.URLError("[WinError 10054] connection forcibly closed")

        replies = []
        for entry in actions:
            if entry.get("action") == "setSpecificValueOfCard":
                params = entry.get("params") or {}
                card_id, value = params["card"], params["newValues"][0]
                if params.get("keys") == ["flags"]:
                    self.cards[card_id]["flags"] = value
                    self.flag_writes.append((card_id, value))
                else:
                    self.cards[card_id]["due"] = value
                    self.writes.append((card_id, value))
                replies.append({"result": [True], "error": None})
            else:
                result = self._dispatch(entry.get("action"), entry.get("params") or {})
                if isinstance(result, AnkiRefusal):
                    replies.append({"result": None, "error": result.message})
                else:
                    replies.append({"result": result, "error": None})
        return replies


def _patched(fake):
    return mock.patch("urllib.request.urlopen", fake)


# --------------------------------------------------------------------------- #
# Fixtures — real words, real ranks
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def priority_rows():
    """`(Word, Orth)` per row of a real export, in the order Surasura ranks them."""
    with open(_RESOURCE_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        return [((row.get("Word") or "").strip(), (row.get("Orth") or "").strip())
                for row in csv.DictReader(handle)]


@pytest.fixture(scope="module")
def ranked_words(priority_rows):
    """The spelling anki_miner would write on the card, in rank order, de-duplicated."""
    seen = []
    for word, orth in priority_rows:
        key = orth or word
        # A one-character spelling of a longer word (ん for the interjection んっ) is never a key in
        # Japanese — `anki_match.build_index`'s guard — so that card carries the word itself.
        if len(key) == 1 and key != word:
            key = word
        if key and key not in seen:
            seen.append(key)
    assert len(seen) > 60, "the fixture export should give a realistically sized match index"
    return seen


@pytest.fixture
def write_priority_csv(tmp_path, priority_rows):
    """Write a real, BOM-carrying priority list into the sandboxed `results/` folder.

    `SURASURA_TEST_ROOT` (conftest) points `get_user_file` here, so `reposition.priority_csv_path()`
    finds this file and never the developer's real 14 MB one (`testing.md` §5.1).
    """
    def _write(rows=None):
        path = os.path.join(str(tmp_path), "results", "priority_learning_list.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Word", "Orth", "Reading", "Tier"])
            for word, orth in (priority_rows if rows is None else rows):
                writer.writerow([word, orth, "", "NOW"])
        return path
    return _write


def _note(note_id, word, model="Lapis", field="Expression"):
    """One `notesInfo` note. Field 0 holds the word, as anki_miner's preflight enforces."""
    return {"noteId": note_id, "modelName": model,
            "fields": {field: {"value": word, "order": 0},
                       "Sentence": {"value": f"{word}を使った文。", "order": 1}}}


def _card(card_id, note_id, due, deck="TheBank", card_type=0, queue=0):
    return {"cardId": card_id, "note": note_id, "due": due,
            "type": card_type, "queue": queue, "deckName": deck}


def _collection(words, dues=None, deck="TheBank", start=0, **kwargs):
    """A FakeCollection of one new card per word, in the queue order `dues` gives."""
    cards, notes = [], []
    for index, word in enumerate(words):
        note_id = FIRST_NOTE + start + index
        due = dues[index] if dues else 2800 + start + index
        notes.append(_note(note_id, word))
        cards.append(_card(FIRST_CARD + start + index, note_id, due, deck=deck))
    return cards, notes, kwargs


def _settings(**over):
    """Loaded-settings shape: the module defaults plus whatever the core would have merged in.

    `junban_order` is pinned to `"priority"` here rather than left at its shipped default. Every
    test in this file predates WP-M and describes the leverage order over
    `priority_learning_list.csv`; saying so explicitly keeps them a **regression guard on the order
    that already worked** instead of silently re-aiming them at the other file. Content order has
    its own file, `test_orders.py`, with its own progressive fixture.
    """
    base = dict(junban.SETTINGS_DEFAULTS)
    base["junban_word_fields"] = dict(base["junban_word_fields"])   # never alias the default (§13 #12)
    base["junban_only_markers"] = list(base["junban_only_markers"])
    base.update({"target_language": "ja", "junban_url": URL, "junban_deck": "TheBank",
                 "junban_order": "priority"})
    base.update(over)
    return base


@pytest.fixture
def backlog(ranked_words, write_priority_csv):
    """A realistic backlog: 24 ranked words in deliberately wrong queue order, plus 6 unranked ones.

    The dues run backwards over the ranked words, so a planner that did nothing would fail almost
    every ordering assertion here rather than passing by luck.
    """
    write_priority_csv()
    matched = ranked_words[:24]
    words = matched + UNRANKED
    dues = list(range(2800 + len(words) - 1, 2799, -1))
    cards, notes, _ = _collection(words, dues=dues)
    return FakeCollection(cards, notes)


# --------------------------------------------------------------------------- #
# Preflight — all four gates
# --------------------------------------------------------------------------- #
def test_preflight_passes_on_a_healthy_collection(backlog):
    with _patched(backlog):
        checks = reposition.preflight(_settings())
    assert checks["ok"] is True
    assert checks["problems"] == []
    assert checks["decks"] == ["TheBank"]


def test_preflight_refuses_when_new_cards_are_inserted_randomly(backlog):
    """`new.order == 0` means Anki gathers new cards randomly and ignores card positions entirely,
    so the run would write, sync to AnkiWeb and change nothing the user can see. It must STOP and
    say so — and it must not repair the deck options on the user's behalf (spec §8 preflight 3)."""
    backlog.new_order = 0
    with _patched(backlog):
        checks = reposition.preflight(_settings())

    assert checks["ok"] is False
    assert any("RANDOM" in problem for problem in checks["problems"])
    assert "saveDeckConfig" not in backlog.action_names, "deck options are the user's, not ours"


@pytest.mark.parametrize("serve, says", [
    ({"newGatherPriority": 3}, "Random notes"),
    ({"newGatherPriority": 4}, "Random cards"),
    ({"newGatherPriority": 5}, "Deck, then random notes"),
    ({"newGatherPriority": 2}, "backwards"),
    ({"newSortOrder": 2}, "Card type, then random"),
    ({"newSortOrder": 3}, "Random note, then card type"),
    ({"newSortOrder": 4}, "'Random'"),
])
def test_preflight_refuses_a_gather_or_sort_order_that_ignores_or_reverses_positions(backlog, serve, says):
    """R1 (Sonic: "When I reorder, that it faithfully reorders accordingly"): Anki's v3 scheduler gathers and sorts
    new cards by two more deck options. A random one ignores Junban's positions as random insertion does; a
    descending gather serves them backwards. Either way the reorder would show the learner nothing it promised, so
    it stops and says which option — and never changes it (read only)."""
    backlog.serve = serve
    with _patched(backlog):
        checks = reposition.preflight(_settings())
    assert checks["ok"] is False
    assert any(says in problem and "'TheBank'" in problem for problem in checks["problems"]), checks["problems"]
    assert "saveDeckConfig" not in backlog.action_names and "setDeckConfigId" not in backlog.action_names


@pytest.mark.parametrize("serve", [{}, {"newGatherPriority": 0, "newSortOrder": 0},
                                   {"newGatherPriority": 1, "newSortOrder": 1}])
def test_preflight_passes_the_gather_and_sort_orders_that_follow_positions(backlog, serve):
    """Deck / Ascending position, with Card type then order gathered (Anki's defaults) or Order gathered, serve the
    positions as written; an Anki before these options (no keys) is no problem either."""
    backlog.serve = serve
    with _patched(backlog):
        checks = reposition.preflight(_settings())
    assert checks["ok"] is True and checks["warnings"] == []


def test_preflight_warns_that_a_deck_by_deck_gather_shows_subdecks_one_after_another(backlog):
    """`Deck` gathers subdeck by subdeck: one order across them needs Ascending position. A warning, not a stop — a
    learner's subdecks may be meant to come one after another."""
    backlog.serve, backlog.more_decks = {"newGatherPriority": 0}, ["TheBank::文法", "TheBankrupt"]
    with _patched(backlog):
        checks = reposition.preflight(_settings())
    assert checks["ok"] is True
    assert [w for w in checks["warnings"] if "subdecks" in w and "Ascending position" in w]
    backlog.serve = {"newGatherPriority": 1}
    with _patched(backlog):
        assert not [w for w in reposition.preflight(_settings())["warnings"] if "subdecks" in w]
    backlog.serve, backlog.more_decks = {"newGatherPriority": 0}, ["TheBankrupt"]      # a name that only starts so
    with _patched(backlog):
        assert not [w for w in reposition.preflight(_settings())["warnings"] if "subdecks" in w]


def test_preflight_warns_that_card_type_then_order_gathered_shows_first_cards_before_second_ones(backlog):
    """Drill A3, gap 1 (the lead's ruling): Anki's default sort, 'Card type, then order gathered', serves every note's
    first card before any second one — so a Basic (and reversed) note's back card is not where Junban put it. A
    warning when a new card in scope is a second card or later (one search: `-card:1`); never with one-card notes,
    never with 'Order gathered'; the deck options are never changed."""
    backlog.serve = {"newGatherPriority": 0, "newSortOrder": 0}
    with _patched(backlog):
        checks = reposition.preflight(_settings())
    assert checks["ok"] is True and checks["warnings"] == [], "one card a note: nothing to say"
    some = next(iter(backlog.cards.values()))
    backlog.cards[some["cardId"] + 1_000_000] = dict(some, cardId=some["cardId"] + 1_000_000, ord=1)
    with _patched(backlog):
        checks = reposition.preflight(_settings())
    assert checks["ok"] is True
    assert [w for w in checks["warnings"] if "'Order gathered'" in w and "first card" in w], checks["warnings"]
    backlog.serve = {"newGatherPriority": 0, "newSortOrder": 1}
    with _patched(backlog):
        assert reposition.preflight(_settings())["warnings"] == []
    assert "saveDeckConfig" not in backlog.action_names


def test_in_all_decks_a_deck_tree_is_searched_and_warned_about_once(backlog):
    """R1 review: scope "all" lists a parent and its subdeck, and the parent's search holds the subdeck's cards — one
    request for every deck tree's second cards, and one warning a tree, at its top."""
    backlog.serve = {"newGatherPriority": 0, "newSortOrder": 0}
    cards = list(backlog.cards.values())
    cards[0]["deckName"] = "TheBank::文法"
    back = dict(cards[1], cardId=cards[1]["cardId"] + 1_000_000, ord=1, deckName="TheBank::文法")
    backlog.cards[back["cardId"]] = back
    with _patched(backlog):
        checks = reposition.preflight(_settings(junban_scope="all"))
    assert sorted(checks["decks"]) == ["TheBank", "TheBank::文法"]
    assert len([w for w in checks["warnings"] if "first card" in w]) == 1, checks["warnings"]
    assert len([w for w in checks["warnings"] if "subdecks" in w]) == 1, checks["warnings"]
    searches = [r for r in backlog.requests if r["action"] == "multi" and "-card:1" in json.dumps(r)]
    assert len(searches) == 1


def test_preflight_refuses_when_ankiconnect_cannot_write_a_card(backlog):
    """The `apiReflect` gate: an AnkiConnect too old to expose `setSpecificValueOfCard` cannot be
    worked around, so the feature has to say so up front rather than card by card."""
    backlog.actions = ["multi"]
    with _patched(backlog):
        checks = reposition.preflight(_settings())

    assert checks["ok"] is False
    assert any("setSpecificValueOfCard" in problem for problem in checks["problems"])


def test_preflight_refuses_when_there_is_no_priority_list(tmp_path, ranked_words):
    """A first run that has never been analysed: there is no order to follow, so there is nothing
    honest to write."""
    cards, notes, _ = _collection(ranked_words[:5])
    fake = FakeCollection(cards, notes)
    assert not os.path.exists(os.path.join(str(tmp_path), "results", "priority_learning_list.csv"))

    with _patched(fake):
        checks = reposition.preflight(_settings())

    assert checks["ok"] is False
    assert any("priority learning list" in problem for problem in checks["problems"])


def test_a_library_newer_than_the_list_warns_but_does_not_block(backlog, tmp_path):
    """Spec §15 #5: warn only, and never offer to re-run the journey. A reposition is seconds and an
    analysis is minutes; hijacking one into the other is the surprise Reels was criticised for."""
    manifest = os.path.join(str(tmp_path), "User Files", "ja", "master_manifest.json")
    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    with open(manifest, "w", encoding="utf-8") as handle:
        json.dump({"phases": {"HighPriority": []}}, handle)
    csv_path = reposition.priority_csv_path()
    os.utime(manifest, (os.path.getmtime(csv_path) + 60, os.path.getmtime(csv_path) + 60))

    with _patched(backlog):
        checks = reposition.preflight(_settings())

    assert checks["ok"] is True, "a stale list must never block a reorder"
    assert any("changed since the last analysis" in warning for warning in checks["warnings"])

    with _patched(backlog):
        report = reposition.run(_settings())
    assert report["ok"] is True and report["written"], "the run goes ahead, carrying the warning"
    assert report["warnings"] == checks["warnings"]


def test_preflight_refuses_an_unmatched_placement_this_version_cannot_do(backlog):
    """`junban_unlisted` is honoured, not ignored: "tiers" and "back" exist, and a settings value
    that silently does something else is worse than one that is missing."""
    with _patched(backlog):
        checks = reposition.preflight(_settings(junban_unlisted="front"))
    assert checks["ok"] is False
    assert any("back of the queue" in problem for problem in checks["problems"])
    with _patched(backlog):
        assert reposition.preflight(_settings(junban_unlisted="back"))["ok"] is True


def test_preflight_refuses_a_tag_anki_would_split(backlog):
    """"Surasura order" is TWO tags to Anki. The run would add "order" too, and Restore would then
    take "order" off every moved note — including ones the user had tagged that way themselves."""
    with _patched(backlog):
        checks = reposition.preflight(_settings(junban_tag="Surasura order"))
        fine = reposition.preflight(_settings(junban_tag="Surasura_order"))
    assert checks["ok"] is False
    assert any("contains a space" in problem for problem in checks["problems"])
    assert fine["ok"] is True
    assert backlog.writes == []


def test_preflight_degrades_politely_when_anki_is_closed(backlog):
    """Anki is a desktop app the user can close. That is a sentence in the panel, not a traceback."""
    backlog.offline = True
    with _patched(backlog):
        checks = reposition.preflight(_settings())

    assert checks["ok"] is False
    assert checks["decks"] == []
    assert any("Is Anki running?" in problem for problem in checks["problems"])


def test_preflight_refuses_when_no_deck_is_nominated(backlog):
    """The shipped default is scope "deck" with an empty deck name — nothing may reach the
    collection until the user has actually chosen one."""
    with _patched(backlog):
        checks = reposition.preflight(_settings(junban_deck=""))
    assert checks["ok"] is False
    assert any("no deck is selected" in problem for problem in checks["problems"])


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #
def test_scope_deck_only_gathers_the_nominated_deck(ranked_words, write_priority_csv):
    write_priority_csv()
    bank_cards, bank_notes, _ = _collection(ranked_words[:6], deck="TheBank")
    other_cards, other_notes, _ = _collection(ranked_words[6:12], deck="The Accelerator", start=50)
    fake = FakeCollection(bank_cards + other_cards, bank_notes + other_notes)

    with _patched(fake):
        writes, stats = reposition.dry_run(_settings())

    assert stats["decks"] == ["TheBank"]
    assert stats["considered"] == 6
    touched = {card_id for card_id, _due in writes}
    assert all(fake.cards[card_id]["deckName"] == "TheBank" for card_id in touched)


def test_scope_all_covers_every_deck_that_has_new_cards(ranked_words, write_priority_csv):
    """§15 #3: the offer is filtered to decks that actually hold unsuspended new cards, so a deck
    that is empty or entirely suspended is never presented as a reorder target."""
    write_priority_csv()
    bank_cards, bank_notes, _ = _collection(ranked_words[:6], deck="TheBank")
    other_cards, other_notes, _ = _collection(ranked_words[6:12], deck="The Accelerator", start=50)
    # Entirely suspended, like the real `Migaku Reference`: it must not appear in the scope at all.
    suspended = [_card(FIRST_CARD + 900 + i, FIRST_NOTE + 900 + i, 10 + i,
                       deck="Migaku Reference", queue=-1) for i in range(3)]
    suspended_notes = [_note(FIRST_NOTE + 900 + i, UNRANKED[i]) for i in range(3)]
    fake = FakeCollection(bank_cards + other_cards + suspended,
                          bank_notes + other_notes + suspended_notes)

    with _patched(fake):
        writes, stats = reposition.dry_run(_settings(junban_scope="all"))

    assert stats["decks"] == ["The Accelerator", "TheBank"]
    assert stats["considered"] == 12
    assert "Migaku Reference" not in stats["decks"]


def test_a_card_in_a_subdeck_is_counted_once_not_twice(ranked_words, write_priority_csv):
    """Subdecks are included by plain `deck:"X"` (§15 #4), so an "all decks" run sees a subdeck's
    cards under both the parent and the child. Counting them twice would make every number the
    confirmation states wrong."""
    write_priority_csv()
    parent, parent_notes, _ = _collection(ranked_words[:4], deck="TheBank")
    child, child_notes, _ = _collection(ranked_words[4:8], deck="TheBank::Mining", start=20)
    fake = FakeCollection(parent + child, parent_notes + child_notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_scope="all"))

    assert stats["decks"] == ["TheBank", "TheBank::Mining"]
    assert stats["considered"] == 8, "8 cards, not 12 — the subdeck's four were seen twice"
    assert len({row.card_id for row in stats["order"]}) == 8


def test_an_unknown_scope_is_refused_rather_than_guessed(backlog):
    """Defaulting a typo to "all" would reorder every deck the user owns."""
    with _patched(backlog):
        checks = reposition.preflight(_settings(junban_scope="everything"))
    assert checks["ok"] is False
    assert any("Unknown scope" in problem for problem in checks["problems"])


# --------------------------------------------------------------------------- #
# The preview
# --------------------------------------------------------------------------- #
def test_a_new_card_in_a_filtered_deck_is_left_out(ranked_words, write_priority_csv):
    """A leftover Custom Study session holds one of the deck's new cards. Anki numbers filtered cards
    from about -100000, and `is:new` alone still matched it through its home deck, so `min(due)`
    dragged every card in scope into that range — to the front of every deck — and a later Restore
    would write those values back onto the card once it returned home."""
    write_priority_csv()
    cards, notes, _ = _collection(ranked_words[:6], dues=[2805, 2804, 2803, 2802, 2801, 2800])
    stray = dict(cards[0], deckName="Custom Study Session", odeck="TheBank", due=-100000)
    cards[0] = stray
    fake = FakeCollection(cards, notes)
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    in_scope = {row.card_id for row in stats["order"]}
    assert stray["cardId"] not in in_scope
    assert len(in_scope) == 5
    assert stats["base"] >= 2800, "the block must stay where the deck's own new cards are"


def test_dry_run_performs_zero_writes(backlog):
    """The preview is read-only by contract — it is what the user is shown *before* consenting, and
    a preview that has already changed the collection is not a preview."""
    with _patched(backlog):
        writes, stats = reposition.dry_run(_settings())

    assert writes, "this backlog is deliberately in the wrong order, so there is work to show"
    assert backlog.writes == []
    assert "setSpecificValueOfCard" not in json.dumps(backlog.requests)
    assert stats["to_write"] == len(writes)
    assert len(stats["order"]) == stats["considered"]
    # Nothing moved: every card still sits at the due it started with.
    assert all(card["due"] >= 2800 for card in backlog.cards.values())


def test_the_preview_and_the_run_agree_card_for_card(backlog):
    """Invariant I5 — the counts shown ARE the counts written. A preview computed by a second code
    path is a second implementation, free to disagree with the one that writes."""
    with _patched(backlog):
        previewed, stats = reposition.dry_run(_settings())
        report = reposition.run(_settings())

    assert [card_id for card_id, _due in previewed] == report["written"]
    assert report["stats"]["to_write"] == stats["to_write"]


def test_the_preview_names_the_field_each_note_type_was_read_from(ranked_words, write_priority_csv):
    """Spec §18.1: field 0 is an anki_miner invariant, not an Anki one — `Migaku Japanese` puts a
    whole sentence there. The panel must SHOW the resolved field so a wrong guess is visible rather
    than silent, which means the override has to be threaded through to here."""
    write_priority_csv()
    lapis = _note(FIRST_NOTE, ranked_words[0])
    migaku = {"noteId": FIRST_NOTE + 1, "modelName": "Migaku Japanese",
              "fields": {"Sentence": {"value": f"{ranked_words[1]}が好きです。", "order": 0},
                         "Target Word": {"value": ranked_words[1], "order": 1}}}
    cards = [_card(FIRST_CARD, FIRST_NOTE, 2805), _card(FIRST_CARD + 1, FIRST_NOTE + 1, 2801)]
    fake = FakeCollection(cards, [lapis, migaku])
    overrides = {"Migaku Japanese": "Target Word"}

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_word_fields=overrides))

    assert stats["fields"] == {"Lapis": "Expression", "Migaku Japanese": "Target Word"}
    assert stats["matched"] == 2, "the Migaku card matches only because the override was honoured"


def test_the_word_field_overrides_are_never_mutated_in_place(backlog):
    """§13 #12: the dict in loaded settings IS the object inside `SETTINGS_DEFAULTS`, because
    `settings_manager` merges module defaults with a shallow `dict.update()`. Mutating it here would
    poison every later `load_settings()` in the process."""
    settings = _settings()
    settings["junban_word_fields"] = junban.SETTINGS_DEFAULTS["junban_word_fields"]   # the alias
    with _patched(backlog):
        reposition.dry_run(settings)
    assert junban.SETTINGS_DEFAULTS["junban_word_fields"] == {}


# --------------------------------------------------------------------------- #
# The run — the snapshot, and what survives a failure
# --------------------------------------------------------------------------- #
def test_the_snapshot_is_on_disk_before_the_very_first_write(backlog):
    """Invariant I3, checked the only way that means anything: the file must be READABLE at the
    instant the first `setSpecificValueOfCard` arrives, not merely scheduled.

    There is no Anki-side undo — `setSpecificValueOfCard` hardcodes `skip_undo_entry=True` — so a
    write that lands before this file exists is a one-way door.
    """
    seen = {}

    def _look():
        path = undo.snapshot_path("ja")
        seen["exists"] = os.path.isfile(path)
        if seen["exists"]:
            with open(path, "r", encoding="utf-8") as handle:
                seen["payload"] = json.load(handle)

    backlog.on_write = _look
    with _patched(backlog):
        report = reposition.run(_settings())

    assert seen.get("exists") is True, "cards moved before the only undo there is reached disk"
    assert seen["payload"]["scope"] == ["TheBank"]
    # Every movable card, at the position it held BEFORE the run — not just the ones that changed,
    # so the file describes the whole scope as it stood.
    assert len(seen["payload"]["cards"]) == report["stats"]["considered"]
    assert seen["payload"]["cards"][str(FIRST_CARD)] == 2829


def test_a_mid_run_transport_failure_keeps_the_snapshot_and_reports_partial_progress(backlog):
    """Anki closing halfway through is the ordinary failure, and the one the snapshot exists for.

    What must hold afterwards: the cards already written stay written, the snapshot on disk still
    covers the WHOLE scope (so a restore can put all of it back), and the report says plainly how
    far it got instead of claiming success or raising.
    """
    backlog.fail_write_chunk = 2
    settings = _settings(junban_chunk_size=5)

    with _patched(backlog):
        report = reposition.run(settings)

    assert report["ok"] is False
    assert len(report["written"]) == 5, "the first chunk landed and must be reported as landed"
    assert report["failures"], "the rest must be named, not silently dropped"
    assert "Reordered 5 of" in report["message"]

    snapshot = undo.load("ja")
    assert snapshot is not None, "the undo file must survive the failure that made it necessary"
    assert len(snapshot["cards"]) == report["stats"]["considered"]
    written_ids = set(report["written"])
    assert all(str(card_id) in snapshot["cards"] for card_id in written_ids)


def test_a_run_after_an_interrupted_one_is_refused_until_it_is_restored(backlog):
    """The same failure one step on: Anki died mid-run, the report said the previous order is still
    saved, and the user re-previewed and pressed Reorder to finish the job. That second run used to
    snapshot the HALF-WRITTEN order over the only copy of how the deck really was."""
    original = {card_id: card["due"] for card_id, card in backlog.cards.items()}
    backlog.fail_write_chunk = 2
    with _patched(backlog):
        assert reposition.run(_settings(junban_chunk_size=5))["ok"] is False
        saved = undo.load("ja")["cards"]
        writes_so_far = len(backlog.writes)

        second = reposition.run(_settings(junban_chunk_size=5))
        assert second["ok"] is False
        assert any("Undo the last reorder first" in problem for problem in second["problems"])
        assert len(backlog.writes) == writes_so_far, "the refused run must write nothing"
        assert undo.load("ja")["cards"] == saved, "the only way back must be left untouched"

        assert reposition.restore(_settings())["ok"] is True
        assert {card_id: card["due"] for card_id, card in backlog.cards.items()} == original
        third = reposition.run(_settings())
    assert third["ok"] is True, "once the way back has been taken, reordering works again"


def test_a_failed_preflight_writes_nothing_at_all(backlog):
    """The gates are gates: a refusal must reach the collection as zero requests, not as a rollback."""
    backlog.new_order = 0
    with _patched(backlog):
        report = reposition.run(_settings())

    assert report["ok"] is False
    assert backlog.writes == []
    assert report["snapshot"] is None
    assert undo.load("ja") is None, "no snapshot is written for a run that never started"


def test_a_healthy_run_reorders_every_card_into_the_list_order(backlog, ranked_words):
    """The success path: matched cards in Surasura's order, unmatched keeping their relative order
    behind them, occupying exactly the span of positions the block already held."""
    with _patched(backlog):
        report = reposition.run(_settings())

    assert report["ok"] is True
    assert report["failures"] == []
    final = sorted(backlog.cards.values(), key=lambda card: card["due"])
    words = [backlog.notes[card["note"]]["fields"]["Expression"]["value"] for card in final]
    assert words[:24] == ranked_words[:24], "matched cards follow the priority list exactly"
    assert set(words[24:]) == set(UNRANKED)
    dues = [card["due"] for card in final]
    assert dues == list(range(2800, 2800 + len(final))), "the block stays where it was"


def test_a_second_run_writes_nothing_and_keeps_the_earlier_snapshot(backlog):
    """Idempotence, and the reason an empty run must NOT save: overwriting the saved order with an
    empty one would throw away the user's only route back from the previous run, and they would not
    find out until they pressed Restore."""
    with _patched(backlog):
        first = reposition.run(_settings())
        before = undo.load("ja")
        backlog.writes.clear()
        second = reposition.run(_settings())

    assert first["written"] and second["written"] == []
    assert backlog.writes == []
    assert second["ok"] is True and "already in the right place" in second["message"]
    assert undo.load("ja") == before, "the previous order must still be restorable"


def test_review_cards_are_never_written(ranked_words, write_priority_csv):
    """Invariant I1, at the orchestration level rather than the planner's: a review card whose word
    the list ranks looks exactly like work to do. Writing `due` on it does not fail — it silently
    reschedules it to a garbage date and syncs that to AnkiWeb and mobile."""
    write_priority_csv()
    new_cards, notes, _ = _collection(ranked_words[:6], dues=[2805, 2804, 2803, 2802, 2801, 2800])
    reviews = [_card(FIRST_CARD + 500 + i, FIRST_NOTE + 500 + i, 120 + i, card_type=2, queue=2)
               for i in range(4)]
    review_notes = [_note(FIRST_NOTE + 500 + i, ranked_words[6 + i]) for i in range(4)]
    # The query would not return them; a hand-edited collection or a card studied between the search
    # and the write still can, which is why the check is re-made against the card itself.
    fake = FakeCollection(new_cards + reviews, notes + review_notes)
    fake._find = lambda query: sorted(fake.cards)        # every card, review ones included

    with _patched(fake):
        report = reposition.run(_settings())

    assert report["ok"] is True
    review_ids = {card["cardId"] for card in reviews}
    assert not review_ids & {card_id for card_id, _due in fake.writes}
    assert all(fake.cards[card_id]["due"] == 120 + index
               for index, card_id in enumerate(sorted(review_ids)))
    assert report["stats"]["skipped_review"] == 4


def test_the_reviewer_queue_is_refreshed_after_writing(backlog):
    """`reloadCollection` then `guiDeckBrowser`, or the reviewer keeps serving the old queue and the
    user concludes the button did nothing (spec §8)."""
    with _patched(backlog):
        reposition.run(_settings())

    names = backlog.action_names
    assert names[-2:] == ["reloadCollection", "guiDeckBrowser"]
    assert names.index("reloadCollection") > max(i for i, n in enumerate(names) if n == "multi")


def test_the_configured_chunk_size_is_what_reaches_the_wire(backlog):
    """`junban_chunk_size` is honoured, not decorative. AnkiConnect runs on Anki's Qt GUI thread
    with a 25 ms poll: one oversized `multi` freezes Anki with no progress and no cancel."""
    progress = []
    with _patched(backlog):
        report = reposition.run(_settings(junban_chunk_size=4),
                               progress=lambda done, total: progress.append((done, total)))

    writes = len(report["written"])
    assert backlog.write_chunks == (writes + 3) // 4
    assert progress[-1] == (writes, writes)


def test_a_snapshot_that_cannot_be_saved_stops_the_run(backlog):
    """If the undo file cannot be written the run must not happen at all. A reposition with no
    snapshot is irreversible: AnkiConnect writes no undo entry, and Anki's own Undo would revert
    whatever the user did *before* the run while leaving ours in place."""
    with _patched(backlog), mock.patch.object(undo, "save", side_effect=OSError("disk full")):
        report = reposition.run(_settings())

    assert report["ok"] is False
    assert backlog.writes == []
    assert any("undo snapshot" in problem for problem in report["problems"])


def test_an_empty_deck_is_an_ordinary_answer(write_priority_csv):
    """Empty state: a deck with no new cards at all. Nothing to plan, nothing to write, no snapshot,
    and certainly no exception."""
    write_priority_csv()
    fake = FakeCollection([_card(FIRST_CARD, FIRST_NOTE, 3, card_type=2, queue=2)],
                          [_note(FIRST_NOTE, UNRANKED[0])])

    with _patched(fake):
        report = reposition.run(_settings())

    assert report["ok"] is True
    assert report["written"] == [] and fake.writes == []
    assert undo.load("ja") is None


def test_a_list_that_matches_nothing_leaves_the_queue_alone(ranked_words, write_priority_csv):
    """Empty state: the analysis ranks none of the mined words — every card is unmatched, keeps its
    relative order, and therefore nothing moves."""
    write_priority_csv(rows=[("無関係", "無関係")])
    cards, notes, _ = _collection(UNRANKED, dues=[2800 + i for i in range(len(UNRANKED))])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        report = reposition.run(_settings())

    assert report["ok"] is True
    assert report["stats"]["matched"] == 0
    assert fake.writes == []


def test_spelling_and_script_variants_match_and_a_surname_kanji_does_not(tmp_path):
    """Junban_Backlog_Spec WP-B2, end to end on real misses from the user's backlog: 見とれる is how
    the content spelled 見惚れる (its `Forms`), スルリ is するり in katakana — both now land on their
    word. 谷 was matching the surname タニ, whose commonest spelling it is; it no longer does."""
    path = os.path.join(str(tmp_path), "results", "priority_learning_list.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Word", "Orth", "Reading", "Forms"])
        writer.writerows([("タニ", "谷", "タニ", ""), ("冒険", "冒険", "ボウケン", ""),
                          ("見惚れる", "見惚れる", "ミトレル", "見とれる|見惚れ"),
                          ("するり", "するり", "スルリ", "")])
    cards, notes, _ = _collection(["谷", "スルリ", "見とれる", "冒険"], dues=[2804, 2803, 2802, 2801])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    ranks = {row.word: row.rank for row in stats["order"]}
    assert ranks == {"冒険": 1, "見とれる": 2, "スルリ": 3, "谷": None}
    assert [row.word for row in stats["order"]] == ["冒険", "見とれる", "スルリ", "谷"]
    assert fake.writes == [], "a preview never writes"


# --------------------------------------------------------------------------- #
# Junban_Backlog_Spec §11.1 — the words the list cut off, placed where the journey meets them
# --------------------------------------------------------------------------- #
def _results(tmp_path, progressive=None, priority=None, library=None, floor=None):
    """The three results files a run leaves: the two lists and the library map (revision 11), whose
    `settings.min_count` is the list's cut-off — `floor`, when given."""
    folder = os.path.join(str(tmp_path), "results")
    os.makedirs(folder, exist_ok=True)
    if progressive is not None:
        with open(os.path.join(folder, "progressive_learning_list.csv"), "w", encoding="utf-8-sig",
                  newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Sequence", "Word", "Orth", "Score", "Occurrences (Global)"])
            writer.writerows(progressive)
    if priority is not None:
        with open(os.path.join(folder, "priority_learning_list.csv"), "w", encoding="utf-8-sig",
                  newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Word", "Orth", "Score", "Occurrences"])
            writer.writerows(priority)
    if library is not None:
        with open(os.path.join(folder, "library_frequency.json"), "w", encoding="utf-8") as handle:
            json.dump({"settings": {} if floor is None else {"min_count": floor}, "words": library},
                      handle, ensure_ascii=False)


# A library as the analyser maps it: the listed words too, and two it cut off — 引き摺る (spelled
# 引きずる in the content, met in file 1) and 眼鏡 (file 2).
_LIBRARY = {"冒険|ボウケン": [5, 5, 0, 0, 1, 50, "冒険"], "散歩|サンポ": [2, 2, 0, 0, 1, 20, "散歩"],
            "老婆|ロウバ": [3, 3, 0, 0, 3, 30, "老婆"],
            "引き摺る|ヒキズル": [1, 1, 0, 0, 1, 30, "引きずる"], "眼鏡|メガネ": [1, 1, 0, 0, 2, 10, "眼鏡"]}
_JOURNEY = [(1, "冒険", "冒険", 50, 5), (1, "散歩", "散歩", 20, 2), (3, "老婆", "老婆", 30, 3)]


def test_a_word_the_list_cut_off_lands_where_the_journey_meets_it(tmp_path):
    """The user's D7: "identical to the journey they would experience". 引きずる (file 1, score 30)
    goes between file 1's 冒険 (50) and 散歩 (20); 眼鏡 (file 2) before file 3's 老婆; 須藤, in no
    list and no library, keeps its place at the back."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY)
    cards, notes, _ = _collection(["須藤", "老婆", "眼鏡", "散歩", "引きずる", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content", junban_unlisted="journey"))

    assert [row.word for row in stats["order"]] == ["冒険", "引きずる", "散歩", "眼鏡", "老婆", "須藤"]
    assert [row.tier for row in stats["order"]][:5] == ["list", "library", "list", "library", "list"]
    assert stats["order"][5].tier not in ("list", "library"), "須藤 is placed by its sentence, after"
    assert (stats["matched"], stats["library"]) == (3, 2)
    assert stats["library_missing"] is False
    # How often, and where first — "library" alone said nothing. No library files here to name,
    # so the file goes by its number.
    assert stats["order"][1].why == "1× · file 1"


def test_rp10_a_word_the_list_cut_off_follows_its_file_through_the_new_order(tmp_path):
    """RP-10 (E3.1): between Generates the library map still carries the last run's file numbers; a fast re-plan's
    job hands their numbers in the new order (`spaced.Job.places`). File 2 moved to the front: 眼鏡 (met first in
    file 2) now goes before 引きずる (file 1), and its "why" names its file's new place."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY)
    cards, notes, _ = _collection(["引きずる", "眼鏡"])
    fake = FakeCollection(cards, notes)
    settings = _settings(junban_order="content", junban_unlisted="journey")

    with _patched(fake):
        _writes, before = reposition.dry_run(settings)
        _writes, after = reposition.dry_run(settings, job=spaced.Job(places={1: 2, 2: 1, 3: 3}))

    assert [row.word for row in before["order"]] == ["引きずる", "眼鏡"]
    assert [row.word for row in after["order"]] == ["眼鏡", "引きずる"]
    assert after["order"][0].why == "1× · file 1"


def test_by_leverage_a_library_word_goes_by_its_score(tmp_path):
    """The priority order is Score first: a word the list cut off but met in NOW scores 30 and goes
    before a listed word scoring 20."""
    _results(tmp_path, priority=[("冒険", "冒険", 50, 5), ("散歩", "散歩", 20, 2)], library=_LIBRARY)
    cards, notes, _ = _collection(["散歩", "引きずる", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="priority", junban_unlisted="journey"))

    assert [row.word for row in stats["order"]] == ["冒険", "引きずる", "散歩"]


def test_back_keeps_every_card_the_list_lacks_behind_the_list_as_before(tmp_path):
    """`junban_unlisted: "back"` is v1's placement, still there for anyone who wants it."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY)
    cards, notes, _ = _collection(["眼鏡", "散歩", "引きずる", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content", junban_unlisted="back"))

    assert [row.word for row in stats["order"]] == ["冒険", "散歩", "眼鏡", "引きずる"]
    assert stats["library"] == 0 and stats["library_missing"] is False


def test_a_library_map_from_before_the_journey_numbers_places_nothing_and_says_so(tmp_path):
    """A map written before ENGINE_REVISION 11 stops at the four counts: with "List first" off, the
    words the list cut off wait at the back, and the stats carry the reason for the panel to state."""
    _results(tmp_path, progressive=_JOURNEY,
             library={"引き摺る|ヒキズル": [1, 1, 0, 0], "冒険|ボウケン": [5, 5, 0, 0]})
    cards, notes, _ = _collection(["引きずる", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content", junban_unlisted="journey"))

    assert [row.word for row in stats["order"]] == ["冒険", "引きずる"]
    assert stats["library"] == 0 and stats["library_missing"] is True


def test_a_phrase_card_is_placed_where_the_library_meets_that_run_of_words(tmp_path):
    """L9, end to end: 恩を売る is one card word to anki_miner and three words to Surasura, so no key
    reaches it — but the library says it in file 1, once, in NOW. It lands among file 1's words by
    that score; 須藤, met nowhere, keeps its place at the back."""
    from app import token_index
    now = os.path.join(str(tmp_path), "data", "ja", "HighPriority")
    os.makedirs(now, exist_ok=True)
    episode = os.path.join(now, "第01話.txt")
    with open(episode, "w", encoding="utf-8") as handle:
        handle.write("冒険は続く。\n恩を売るつもりはない。\n")
    token_index.reconcile_language("ja", [episode])
    _results(tmp_path, progressive=[(1, "冒険", "冒険", 50, 5)], library=_LIBRARY)
    cards, notes, _ = _collection(["須藤", "恩を売る", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content", junban_unlisted="journey"))

    assert [row.word for row in stats["order"]] == ["冒険", "恩を売る", "須藤"]
    assert stats["order"][1].tier == "library" and stats["order"][1].sort == (1, -10, -1, 1, 0)
    assert os.path.isfile(reposition.phrase_cache_path()), "the pass is cached for the next preview"


# --------------------------------------------------------------------------- #
# "List first" — the default (the user, 2026-09-23): the list's words ahead of all it cut off
# --------------------------------------------------------------------------- #
def _episode(tmp_path, name, lines):
    """One subtitle file in the sandboxed library's NOW tab, read into the token store the way a
    Generate reads it — the phrase lookup's only source."""
    from app import token_index
    now = os.path.join(str(tmp_path), "data", "ja", "HighPriority")
    os.makedirs(now, exist_ok=True)
    path = os.path.join(now, name)
    with open(path, "w", encoding="utf-8") as handle:
        for i, line in enumerate(lines, 1):
            handle.write(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n{line}\n\n")
    token_index.reconcile_language("ja", [path])


def test_list_first_puts_every_word_on_the_list_before_any_word_it_cut_off(tmp_path):
    """The user's rule: "anything that IS in our list should come first". 引きずる and 眼鏡 are in
    the library but under the list's cut-off — "exactly the words we DON'T really want to learn
    right now" — so they wait behind every listed word, although the journey meets 引きずる in file
    1; 須藤, in no list and no library, waits with them. Nothing needs switching on: it's the default."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "老婆", "眼鏡", "散歩", "引きずる", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))

    order = stats["order"]
    assert [row.word for row in order][:3] == ["冒険", "散歩", "老婆"], "the list, in journey order"
    assert [row.why for row in order][:3] == ["list #1", "list #2", "list #3"]
    assert {row.word for row in order[3:]} == {"須藤", "眼鏡", "引きずる"}
    assert all(row.tier in ("i+1", "multi", "rest") for row in order[3:]), "then by their sentence"
    assert (stats["matched"], stats["library"], stats["unlisted"]) == (3, 0, "list_first")
    assert stats["library_missing"] is False


def test_list_first_by_leverage_keeps_the_lists_own_order_ahead_too(tmp_path):
    """The same rule in the other order: by leverage the list goes by Score, and 引きずる — which
    out-scores 散歩 (30 to 20) — still waits behind it, because the list cut it off."""
    _results(tmp_path, priority=[("冒険", "冒険", 50, 5), ("散歩", "散歩", 20, 2)], library=_LIBRARY,
             floor=11)
    cards, notes, _ = _collection(["散歩", "引きずる", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="priority"))

    assert [row.word for row in stats["order"]] == ["冒険", "散歩", "引きずる"]


def test_list_first_a_phrase_met_as_often_as_the_lists_words_goes_with_its_episodes_words(tmp_path):
    """A phrase can never be on the list — to the list 恩を売る is three words — so it is held to the
    list's own bar instead: met at least as often as the cut-off asks of a word (here 2), it is placed
    as a listed word would be, with its episode's words — before 散歩, a listed word first met one
    episode later (the user: "Include them along with the episodes words"). Met less, like 気がつく
    (once), it waits with the rarer cards. Its why says how often and where it is first met."""
    _episode(tmp_path, "[SubsPlease] Honzuki no Gekokujou - 21 (1080p) [2BF87A0D].ja.srt",
             ["冒険は続く。", "恩を売るつもりはない。", "また恩を売るのか。", "やっと気がつくと朝だった。"])
    _results(tmp_path, progressive=[(1, "冒険", "冒険", 50, 5), (2, "散歩", "散歩", 20, 2)],
             library=_LIBRARY, floor=2)
    cards, notes, _ = _collection(["散歩", "気がつく", "須藤", "恩を売る", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))

    order = stats["order"]
    assert [row.word for row in order][:3] == ["冒険", "恩を売る", "散歩"]
    assert order[1].tier == "phrase"
    assert order[1].why == "phrase · 2× · Honzuki no Gekokujou - 21"
    assert {row.word for row in order[3:]} == {"気がつく", "須藤"}
    assert all(row.tier in ("i+1", "multi", "rest") for row in order[3:])
    assert stats["tiers"]["phrase"] == 1


def test_with_phrases_switched_off_every_phrase_card_waits_with_the_rest(tmp_path):
    """The panel's "Phrases", unticked: 恩を売る clears the list's bar exactly as above, but the user
    has asked for phrases not to be placed as list words — so it goes by its sentence with the rarer
    cards, the library is not even searched for it, and a missing bar is nothing to warn about."""
    _episode(tmp_path, "[SubsPlease] Honzuki no Gekokujou - 21 (1080p) [2BF87A0D].ja.srt",
             ["冒険は続く。", "恩を売るつもりはない。", "また恩を売るのか。"])
    _results(tmp_path, progressive=[(1, "冒険", "冒険", 50, 5), (2, "散歩", "散歩", 20, 2)],
             library=_LIBRARY, floor=2)
    cards, notes, _ = _collection(["散歩", "恩を売る", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content", junban_phrases=False))

    order = stats["order"]
    assert [row.word for row in order] == ["冒険", "散歩", "恩を売る"]
    assert order[2].tier in ("i+1", "multi", "rest") and stats["tiers"]["phrase"] == 0
    assert not os.path.isfile(reposition.phrase_cache_path()), "no phrase pass was paid for"

    _results(tmp_path, progressive=[(1, "冒険", "冒険", 50, 5)])
    os.remove(reposition.library_map_path())
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content", junban_phrases=False))
    assert stats["library_missing"] is False, "no map is no loss with the phrases off"


@pytest.mark.parametrize("over, language, applies", [
    ({}, "ja", True),                                             # the defaults: After it, nothing marked
    ({"junban_unlisted": "journey"}, "ja", True),
    ({"junban_unlisted": " Journey "}, "ja", True),               # read as the run reads it: trimmed, lowercased
    ({"junban_unlisted": "back"}, "ja", False),                   # at the back: no tiers, neither switch is asked
    ({}, "zh", False),                                            # Japanese only (jieba cuts whole words)
    ({"junban_only_markers": ["star"]}, "ja", False),             # a marker filter: only the chosen words move
    ({"junban_only_markers": ["Reading"]}, "ja", False),          # a hand-edited mark, read as the filter reads it
    ({"junban_only_markers": ["sparkle"]}, "ja", True),           # no mark this version knows: no filter
])
def test_first_applies_says_when_the_phrases_and_i_plus_one_first_switches_take_part(over, language, applies):
    """Q31: the Settings page shows *Idioms and set phrases* and *i+1 first* only where a run uses them, by this one
    rule — the run's own (`tiers`, Japanese) — never a second copy of it."""
    assert reposition.first_applies(_settings(**over), language) is applies


def test_the_run_asks_first_applies_before_placing_a_phrase(tmp_path):
    """The run decides the switches through the exported rule itself: told no, 恩を売る — placed as a list word
    above — waits with the rest, though its switch is on."""
    _episode(tmp_path, "[SubsPlease] Honzuki no Gekokujou - 21 (1080p) [2BF87A0D].ja.srt",
             ["冒険は続く。", "恩を売るつもりはない。", "また恩を売るのか。"])
    _results(tmp_path, progressive=[(1, "冒険", "冒険", 50, 5), (2, "散歩", "散歩", 20, 2)],
             library=_LIBRARY, floor=2)
    cards, notes, _ = _collection(["散歩", "恩を売る", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))
    assert stats["tiers"]["phrase"] == 1
    with _patched(fake), mock.patch.object(reposition, "first_applies", return_value=False) as asked:
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))
    assert asked.called and stats["tiers"]["phrase"] == 0
    assert [row.word for row in stats["order"]] == ["冒険", "散歩", "恩を売る"]


def test_list_first_holds_a_phrase_to_the_lists_lowest_count_not_the_maps_prefilter(tmp_path):
    """Under the "coverage" selection the map's min_count is only the pre-filter (2 by default) and
    greedy coverage cuts the list further. A phrase met twice must not join a list whose least
    frequent word was met five times — "as often as the list's words" means THOSE words."""
    _episode(tmp_path, "[SubsPlease] Honzuki no Gekokujou - 21 (1080p) [2BF87A0D].ja.srt",
             ["恩を売るつもりはない。", "また恩を売るのか。"])
    _results(tmp_path, progressive=[(1, "冒険", "冒険", 50, 5), (2, "散歩", "散歩", 20, 5)],
             library=_LIBRARY, floor=2)
    cards, notes, _ = _collection(["散歩", "恩を売る", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))

    assert [row.word for row in stats["order"]] == ["冒険", "散歩", "恩を売る"]
    assert stats["tiers"]["phrase"] == 0


def test_the_first_preview_in_a_fresh_process_reads_known_words_as_a_run_does(tmp_path, monkeypatch):
    """The dashboard process never runs the analyzer, so `analyzer.SANITIZE_JA` starts False there.
    Read with it off, the known word パーティ is UniDic's raw パーティー-party while the sentence says
    パーティー — the first preview called 冒険 "1 unknown" and the Reorder that followed, "i+1": a
    confirmation that disagreed with the write (found by review, 2026-09-23)."""
    from app import analyzer
    monkeypatch.setattr(analyzer, "SANITIZE_JA", False)
    _results(tmp_path, progressive=[(1, "無関係", "無関係", 1, 1)], floor=2,
             library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["パーティ"])
    fake = _mined([("冒険", "パーティの<b>冒険</b>。", 900, "")])

    with _patched(fake):
        _writes, preview = reposition.dry_run(_settings(junban_order="content", junban_phrases=False))
    with _patched(fake):
        _writes, again = reposition.dry_run(_settings(junban_order="content", junban_phrases=False))

    assert [(row.tier, row.why) for row in preview["order"]] == [("i+1", "i+1")]
    assert [(row.tier, row.why) for row in again["order"]] == [("i+1", "i+1")]


def test_a_chinese_preview_never_promises_phrases(tmp_path):
    """The phrase lookup is Japanese-only (jieba already cuts whole words), so with no library map a
    Chinese preview must not say the next Generate will place its phrases."""
    _results(tmp_path, progressive=[(1, "学习", "学习", 50, 5)])
    cards, notes, _ = _collection(["一石二鸟", "学习"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content", target_language="zh"))

    assert [row.word for row in stats["order"]] == ["学习", "一石二鸟"]
    assert stats["library_missing"] is False


def test_a_chinese_card_with_its_ending_is_placed_on_its_word(tmp_path):
    """认真地 is 认真 on the list (match.card_key, L7: the card read alone by the analyzer's Chinese tokenizer) —
    placed by the list, before the card the list doesn't hold."""
    _results(tmp_path, progressive=[(1, "学习", "学习", 50, 5), (2, "认真", "认真", 40, 4)])
    cards, notes, _ = _collection(["一石二鸟", "认真地", "学习"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content", target_language="zh"))

    assert [row.word for row in stats["order"]] == ["学习", "认真地", "一石二鸟"]


def test_loop_f2_a_card_connect_made_for_a_name_row_is_placed_on_that_row(tmp_path, monkeypatch):
    """LOOP-F2 (drill LOOP, Bocchi the Rock! 01): Connect mined the katakana name ヒトリ and Anki Miner's card reads
    ひとり — a hiragana card of an everyday word never takes a name's row by its letters (`anki_match.not_the_name`),
    so it went after every listed card. Connect's own record (`made_words`: the note and the row it was made for)
    now places it on ヒトリ's row; a card Connect has no record of is placed by its word, as before."""
    _results(tmp_path, progressive=[(1, "ヒトリ", "ヒトリ", 50, 5), (2, "冒険", "冒険", 40, 4)])
    cards, notes, _ = _collection(["一石二鳥", "ひとり", "冒険"])
    fake = FakeCollection(cards, notes)
    monkeypatch.setattr(reposition, "_made_by_connect", lambda language: {})
    with _patched(fake):
        _writes, before = reposition.dry_run(_settings(junban_order="content"))
    assert [row.word for row in before["order"]][0] == "冒険", "no record: not the name's row"
    monkeypatch.setattr(reposition, "_made_by_connect", lambda language: {FIRST_NOTE + 1: "ヒトリ",
                                                                           FIRST_NOTE + 7: "冒険"})
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))
    assert [row.word for row in stats["order"]] == ["ひとり", "冒険", "一石二鳥"]


def test_loop_f2_the_record_never_overrides_your_no_or_a_cards_own_listed_word(tmp_path, monkeypatch):
    """Review F-3: Connect's record places a card only where its own word finds no row of its own — never over your
    "no" to that row ("Same word as ヒトリ?" — no), nor over a word on the list the card holds (you corrected it to
    冒険): Junban's own rules first, as before."""
    _results(tmp_path, progressive=[(1, "ヒトリ", "ヒトリ", 50, 5), (2, "冒険", "冒険", 40, 4)])
    cards, notes, _ = _collection(["一石二鳥", "ひとり", "冒険"])
    fake = FakeCollection(cards, notes)
    monkeypatch.setattr(reposition, "_made_by_connect", lambda language: {FIRST_NOTE + 1: "ヒトリ",
                                                                           FIRST_NOTE + 2: "ヒトリ"})
    from modules.junban import pairs
    pairs.record("ja", [("ひとり", "ヒトリ", False, "L6")])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))
    order = [row.word for row in stats["order"]]
    assert order[0] == "冒険", "your no stands, and 冒険's card stays on 冒険's row"


def test_loop_f2_a_record_naming_a_word_off_the_list_places_the_card_by_its_own_word(tmp_path, monkeypatch):
    """A word Connect made a card for that the list no longer holds (learnt since, or the list changed) is no row:
    the card goes by its own word, never on a row that isn't there."""
    _results(tmp_path, progressive=[(1, "冒険", "冒険", 40, 4)])
    cards, notes, _ = _collection(["一石二鳥", "冒険"])
    fake = FakeCollection(cards, notes)
    monkeypatch.setattr(reposition, "_made_by_connect", lambda language: {FIRST_NOTE: "ヒトリ"})
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))
    assert [row.word for row in stats["order"]] == ["冒険", "一石二鳥"]


def test_list_first_with_no_library_map_the_phrases_wait_and_the_panel_is_told(tmp_path):
    """No map, no cut-off to hold a phrase to: until the next Generate every card the list lacks goes
    by its sentence, and the stats carry that for the panel to say."""
    _episode(tmp_path, "第01話.srt", ["恩を売るつもりはない。", "また恩を売るのか。"])
    _results(tmp_path, progressive=[(1, "冒険", "冒険", 50, 5)])
    cards, notes, _ = _collection(["恩を売る", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(junban_order="content"))

    assert [row.word for row in stats["order"]] == ["冒険", "恩を売る"]
    assert stats["order"][1].tier in ("i+1", "multi", "rest")
    assert stats["library_missing"] is True


def _mined(entries, start=300):
    """A FakeCollection of anki_miner notes: `(word, sentence, FreqSort, source)` per new card, the
    fields a real Lapis note carries (§4.2)."""
    cards, notes = [], []
    for i, (word, sentence, freqsort, source) in enumerate(entries):
        note_id = FIRST_NOTE + start + i
        notes.append({"noteId": note_id, "modelName": "Lapis", "fields": {
            "Expression": {"value": word, "order": 0},
            "Sentence": {"value": sentence, "order": 1},
            "FreqSort": {"value": str(freqsort or ""), "order": 2},
            "MiscInfo": {"value": source, "order": 3}}})
        cards.append(_card(FIRST_CARD + start + i, note_id, 2800 + i))
    return FakeCollection(cards, notes)


def _known(tmp_path, words):
    folder = os.path.join(str(tmp_path), "User Files", "ja")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as handle:
        json.dump({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in words]}, handle,
                  ensure_ascii=False)


def test_the_cards_the_library_cannot_place_go_by_their_sentence_and_known_words_go_last(tmp_path):
    """§5.4 / §5.5 with the user's answers (D1, D3, D4): a card whose sentence holds no other unknown
    word first (i+1), then fewest unknowns, then the cards with no sentence by FreqSort; a word the
    learner already knows (終わり) goes last, whatever its FreqSort says. (彼, a one-kanji dictionary word, is known
    here; 本 read ほん is no list word, so it is nothing to learn beside 美術館.)"""
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["終わり", "毎日", "出かける", "行く", "彼"])
    fake = _mined([("終わり", "夏の終わりが来た。", 825, ""),
                   ("味噌汁", "", 5000, ""),
                   ("眼鏡", "新しい<b>眼鏡</b>を買いに行った。", 4000, ""),
                   ("洗濯機", "", 3000, ""),
                   ("美術館", "美術館で本を読んだ。", 6000, ""),
                   ("冒険", "彼は毎日冒険に出かける。", 9000, "")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    order = stats["order"]
    assert [row.word for row in order] == ["冒険", "美術館", "眼鏡", "洗濯機", "味噌汁", "終わり"]
    assert [row.why for row in order] == ["i+1", "1 unknown", "2 unknown", "FreqSort 3,000",
                                          "FreqSort 5,000", "known"]
    assert stats["tiers"] == {"list": 0, "library": 0, "phrase": 0, "i+1": 1, "multi": 2, "rest": 2,
                              "known": 1}
    assert stats["unmatched"] == 0 and stats["banner"] == []


def test_a_source_with_ten_cards_the_library_lacks_is_named_until_its_episode_is_added(tmp_path):
    """The banner (§5.4, D9) — kept quiet: it needs 10 cards from one source, and it goes away the
    moment a file of that name is in the library. The source is what anki_miner writes in MiscInfo."""
    from app import token_index
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    source = "[SubsPlease] Tetsunabe no Jan! - 04 (1080p)"
    words = ["甜麺醤", "飯店", "食通", "脚光", "豚バラ肉", "伊勢海老", "干し貝柱", "ヒレ肉", "塩コショウ",
             "野菜スープ"]
    fake = _mined([(word, f"{word}を使った料理だ。", 20000 + i, f"{source} @ 00:0{i}:36")
                   for i, word in enumerate(words)])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert stats["banner"] == [{"source": source, "cards": 10}]

    now = os.path.join(str(tmp_path), "data", "ja", "HighPriority")
    os.makedirs(now, exist_ok=True)
    episode = os.path.join(now, f"{source} [2BF87A0D].ja.srt")
    with open(episode, "w", encoding="utf-8") as handle:
        handle.write("1\n00:00:01,000 --> 00:00:02,000\n甜麺醤を使った料理だ。\n")
    token_index.reconcile_language("ja", [episode])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert stats["banner"] == []


def test_a_folder_form_source_of_an_episode_in_the_library_is_never_named_missing(tmp_path):
    """Mattias's note 13 (pipeline Inbox, 2026-10-29): Anki Miner 3.5+ writes the source as "<folder> — <name>", and the
    footer compared that whole label to bare file names — a show IN the library was named as missing. The one
    source-name rule (`source_names`) reads both forms; a show that really isn't there is still named, and a near
    name (episode 40 for episode 4) never stands in for it."""
    from app import token_index
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    folder = "[SubsPlease] 鉄鍋のジャン (1080p)"
    source = "鉄鍋のジャン — 鉄鍋のジャン - 04"                 # 3.10's cleaning: each part, tags and [group] off
    words = ["甜麺醤", "飯店", "食通", "脚光", "豚バラ肉", "伊勢海老", "干し貝柱", "ヒレ肉", "塩コショウ",
             "野菜スープ"]
    fake = _mined([(word, f"{word}を使った料理だ。", 20000 + i, f"{source} @ 00:0{i}:36")
                   for i, word in enumerate(words)])
    now = os.path.join(str(tmp_path), "data", "ja", "HighPriority", folder)
    os.makedirs(now, exist_ok=True)
    near = os.path.join(now, "[SubsPlease] 鉄鍋のジャン - 40 (1080p) [2BF87A0D].ja.srt")
    with open(near, "w", encoding="utf-8") as handle:
        handle.write("1\n00:00:01,000 --> 00:00:02,000\n甜麺醤を使った料理だ。\n")
    token_index.reconcile_language("ja", [near])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert stats["banner"] == [{"source": source, "cards": 10}]          # episode 40 is not episode 4

    episode = os.path.join(now, "[SubsPlease] 鉄鍋のジャン - 04 (1080p) [2BF87A0D].ja.srt")
    with open(episode, "w", encoding="utf-8") as handle:
        handle.write("1\n00:00:01,000 --> 00:00:02,000\n甜麺醤を使った料理だ。\n")
    token_index.reconcile_language("ja", [near, episode])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert stats["banner"] == []                                         # in the library: never named


def _ten(source):
    """Ten of Anki Miner's cards from `source` (the footer's floor), each a real word in a real sentence."""
    words = ["甜麺醤", "飯店", "食通", "脚光", "豚バラ肉", "伊勢海老", "干し貝柱", "ヒレ肉", "塩コショウ", "野菜スープ"]
    return [(word, f"{word}を使った料理だ。", 20000 + i, f"{source} @ 00:0{i}:36") for i, word in enumerate(words)]


def test_a_single_videos_bare_title_in_the_library_is_never_named_missing_and_another_name_still_is(tmp_path):
    """Junban-X3 (based on Mattias's #447, 3.0.10): his single YouTube video's cards carry its bare title, with no
    episode — the footer named it missing while its subtitle was in the library. The third source he reported is in
    his library under another name: exact keys only, it is still named."""
    from app import token_index
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    title, abroad = "笑い過ぎて一生忘れられないTRPG", "【留学なし】誰から何も言われずに"
    fake = _mined(_ten(title) + _ten(abroad), start=400)
    folder = os.path.join(str(tmp_path), "data", "ja", "HighPriority", title)
    os.makedirs(folder, exist_ok=True)
    video = os.path.join(folder, f"{title} [IIqUltT_x0c].ja.srt")
    with open(video, "w", encoding="utf-8") as handle:
        handle.write("1\n00:00:01,000 --> 00:00:02,000\n甜麺醤を使った料理だ。\n")
    token_index.reconcile_language("ja", [video])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert stats["banner"] == [{"source": abroad, "cards": 10}]


def test_a_deck_of_audiobook_cards_alone_finds_its_audiobook(tmp_path, monkeypatch):
    """Junban-X3: `Audio — <name>` is no bare name, yet only the counted names carry it — a deck whose sources are all
    an audiobook's still reads them (`source_names.only_counted`), so his カラフル is never named missing."""
    from modules.junban import backlog_shows, source_names
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    source = "Audio — カラフル (文春文庫) - 森 絵都"
    record = {"audiobook": {"files": ["//hemma/data/Japanese/Book Sync/カラフル/カラフル (文春文庫) - 森 絵都.m4b"],
                            "title": "カラフル", "titles": ["カラフル"]}}
    asked = []

    def counted(language, bare=True):
        asked.append(bare)
        return source_names.names_of_record(record, bare=bare)
    monkeypatch.setattr(backlog_shows, "counted_names", counted)
    with _patched(_mined(_ten(source), start=400)):
        _writes, stats = reposition.dry_run(_settings())
    assert asked == [True] and stats["banner"] == []


def test_a_preview_of_a_thousand_cards_takes_under_a_second(tmp_path, priority_rows):
    """Spec §7's performance guard (I8): the whole ladder and every tier over 1,000 cards of real
    words and real sentences, tokenizer start-up included, well under a second on Surasura's side
    (Anki's own replies come on top: ~0.6 s for 398 cards on the reference machine)."""
    import time
    with open(os.path.join(_ROOT, "tests", "Test Resources", "ja", "context_test.txt"),
              encoding="utf-8") as handle:
        sentences = [line.strip() for line in handle if line.strip()]
    words = [orth or word for word, orth in priority_rows] + UNRANKED
    # Only the first 40 rows listed, so most cards miss the list and take the slow road: the
    # library, the phrase lookup, the tokenizer over their sentence.
    _results(tmp_path, priority=[(word, orth, 100 - i, 5) for i, (word, orth) in enumerate(priority_rows[:40])],
             library=_LIBRARY)
    _known(tmp_path, ["終わり", "毎日", "行く"])
    # Each card's word inside a real sentence, so every card the list does not place is really read.
    fake = _mined([(words[i % len(words)],
                    f"{sentences[i % len(sentences)]}<b>{words[i % len(words)]}</b>だ。", 1000 + i, "")
                   for i in range(1000)])

    # Anki answering, as I8 says: its reads take time — measured ~0.6 s for 398 cards on the reference
    # machine; 0.6 s for these 1,000 cards and their notes here, the conservative side. Surasura's side is
    # what is left (F1, E2.1.4): the tables a first preview builds are built while Anki answers, so the
    # guard holds run alone, cold, as well as in the suite's order.
    waited = []
    answer = fake._dispatch

    def answering(action, params):
        if action in ("cardsInfo", "notesInfo"):
            pause = 0.0003 * len(params.get("cards") or params.get("notes") or [])
            time.sleep(pause)
            waited.append(pause)
        return answer(action, params)
    fake._dispatch = answering

    with _patched(fake):
        started = time.perf_counter()
        _writes, stats = reposition.dry_run(_settings())
        elapsed = time.perf_counter() - started - sum(waited)

    assert stats["considered"] == 1000
    assert stats["tiers"]["multi"] + stats["tiers"]["i+1"] > 0, "the sentences were read"
    # 1 s in a timed run only (SURASURA_STORE_BENCH=1, the machine to itself), as the store's bounds are:
    # elsewhere the machine is shared — the other suites of an --all, up to three --all side
    # by side, a GitHub runner's few cores (1.01 s seen) — and 3 s still catches a preview several times slower.
    budget = 1.0 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 3.0
    assert elapsed < budget, f"a 1,000-card preview took {elapsed:.2f} s beside Anki's answers"


def test_the_journey_key_reads_as_the_progressive_list_does():
    """File first, then Score and occurrences, highest first; a listed word before a library word
    with the same numbers. By leverage: Score first."""
    content = sorted([reposition.journey_sort("content", (3, 30, 3), rank=4),
                      reposition.journey_sort("content", (1, 30, 1)),
                      reposition.journey_sort("content", (1, 50, 5), rank=0),
                      reposition.journey_sort("content", (1, 30, 1), rank=1)])
    assert content == [(1, -50, -5, 0, 0), (1, -30, -1, 0, 1), (1, -30, -1, 1, 0), (3, -30, -3, 0, 4)]
    assert (reposition.journey_sort("priority", (1, 30, 1))
            < reposition.journey_sort("priority", (0, 20, 2), rank=1))


# --------------------------------------------------------------------------- #
# Junban_Backlog_Spec §13 — the cards NOT on the list: tag / flag purple / suspend, undone by Restore
# --------------------------------------------------------------------------- #
_ALL_LATER = {"junban_later_tag": True, "junban_later_flag": True, "junban_later_suspend": True}


def _later_backlog(tmp_path, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend")):
    """冒険 and 散歩 on the list; 須藤 (no list, no library) and 美術館 not on it — what §13 acts on."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "散歩", "美術館", "冒険"])
    return FakeCollection(cards, notes, actions=actions)


def _card_of(fake, word):
    for card in fake.cards.values():
        if fake.notes[card["note"]]["fields"]["Expression"]["value"] == word:
            return card
    raise KeyError(word)


def _tags_of(fake, word):
    return fake.notes[_card_of(fake, word)["note"]].get("tags") or []


def test_the_cards_not_on_the_list_are_tagged_flagged_and_suspended_and_restore_undoes_it(tmp_path):
    """The user's choice, all three ticked: 須藤 and 美術館 — not on the list in any form — get the
    Surasura::later tag, the purple flag and a suspension; the list's own words get none of it. The
    report says so in the same sentence as the move. Restore puts every bit back: unsuspended first
    (a suspended card is outside the new-card search, so its position could not be restored), flags
    to what they were, the tag off exactly those notes, positions as they were."""
    fake = _later_backlog(tmp_path)
    before = {card_id: dict(card) for card_id, card in fake.cards.items()}
    settings = _settings(junban_order="content", **_ALL_LATER)

    with _patched(fake):
        report = reposition.run(settings)

    assert report["ok"], report
    for word in ("須藤", "美術館"):
        assert _card_of(fake, word)["queue"] == -1 and _card_of(fake, word)["flags"] == 7
        assert "Surasura::later" in _tags_of(fake, word)
    for word in ("冒険", "散歩"):
        assert _card_of(fake, word)["queue"] == 0 and not _card_of(fake, word).get("flags")
        assert "Surasura::later" not in _tags_of(fake, word)
    assert "Not on your list: tagged 2 notes, flagged 2 cards purple, and suspended 2 cards." \
        in report["message"]

    with _patched(fake):
        restored = reposition.restore(settings)

    assert restored["ok"], restored
    assert "unsuspended 2 cards Junban had suspended" in restored["message"]
    for card_id, card in fake.cards.items():
        assert (card["queue"], card["due"], card.get("flags") or 0) == \
            (before[card_id]["queue"], before[card_id]["due"], 0)
    assert not any("Surasura::later" in _tags_of(fake, word) for word in ("須藤", "美術館"))


def test_with_nothing_to_move_the_chosen_actions_still_happen_and_a_users_own_flag_is_kept(tmp_path):
    """The trap in `run`: it used to stop at "nothing to reorder". Ordered once, then asked to flag,
    the second run moves nothing yet must still flag — snapshot first. 美術館, which the user flagged
    red themselves, keeps red, and the snapshot records only the card Junban flagged."""
    fake = _later_backlog(tmp_path)
    with _patched(fake):
        reposition.run(_settings(junban_order="content"))
    _card_of(fake, "美術館")["flags"] = 1

    with _patched(fake):
        report = reposition.run(_settings(junban_order="content", junban_later_flag=True))

    assert report["ok"] and report["written"] == [], report
    assert _card_of(fake, "須藤")["flags"] == 7 and _card_of(fake, "美術館")["flags"] == 1
    assert undo.load("ja")["flags"] == {str(_card_of(fake, "須藤")["cardId"]): 0}


def test_restore_leaves_a_card_the_user_has_flagged_since(tmp_path):
    """Like an edited field: Junban's purple on 須藤 became the user's green since the run, so Restore
    keeps green and says so, while 美術館 gets its old flag back."""
    fake = _later_backlog(tmp_path)
    settings = _settings(junban_order="content", junban_later_flag=True)
    with _patched(fake):
        reposition.run(settings)
    _card_of(fake, "須藤")["flags"] = 3

    with _patched(fake):
        restored = reposition.restore(settings)

    assert (_card_of(fake, "須藤")["flags"], _card_of(fake, "美術館")["flags"]) == (3, 0)
    assert "1 card had been flagged again since and kept that flag." in restored["message"]


def test_a_word_clicked_off_the_list_is_treated_as_not_on_it(tmp_path):
    """The user (2026-09-23): "I want it to be treated as 'not-on-your-list'". 冒険 — on the list —
    clicked off is placed by its own sentence among the cards not on the list, loses the list's own
    'Surasura' tag, and gets what was ticked for them: suspended, and tagged later. The run writes
    what the preview showed (I5). A card already not on the list, clicked, is still left alone."""
    fake = _later_backlog(tmp_path)
    off, alone = _card_of(fake, "冒険")["cardId"], _card_of(fake, "須藤")["cardId"]
    settings = _settings(junban_order="content", junban_later_suspend=True,
                         junban_exclude_cards=[off, alone])

    with _patched(fake):
        _writes, preview = reposition.dry_run(settings)
    row = next(row for row in preview["order"] if row.card_id == off)
    assert row.rank is None and row.tier in ("i+1", "multi", "rest")
    assert preview["taken_off_ids"] == [off] and preview["later"]["suspend"] == sorted(
        [off, _card_of(fake, "美術館")["cardId"]])

    with _patched(fake):
        report = reposition.run(settings)

    assert report["ok"], report
    assert _card_of(fake, "冒険")["queue"] == -1 and "Surasura::later" in _tags_of(fake, "冒険")
    assert "Surasura" not in _tags_of(fake, "冒険"), "off the list: not tagged as a list word"
    assert _card_of(fake, "須藤")["queue"] == 0, "left alone"
    assert _card_of(fake, "美術館")["queue"] == -1


def test_a_card_deselected_in_the_preview_is_never_acted_on(tmp_path):
    """WP-O: a row the user clicked off is their choice — not suspended, not flagged, not tagged."""
    fake = _later_backlog(tmp_path)
    kept = _card_of(fake, "須藤")["cardId"]

    with _patched(fake):
        reposition.run(_settings(junban_order="content", junban_exclude_cards=[kept], **_ALL_LATER))

    assert _card_of(fake, "須藤")["queue"] == 0 and not _card_of(fake, "須藤").get("flags")
    assert "Surasura::later" not in _tags_of(fake, "須藤")
    assert _card_of(fake, "美術館")["queue"] == -1


def test_a_marker_filter_never_makes_a_listed_word_look_unlisted(tmp_path):
    """With "only ☆" ticked, 冒険 (on the list, no star) is unmatched for the ORDER — but it is still on
    the list, so it must not be suspended as if it were not. 須藤 and 美術館 are."""
    fake = _later_backlog(tmp_path)

    with _patched(fake):
        reposition.run(_settings(junban_order="content", junban_only_markers=["star"],
                                 junban_later_suspend=True))

    assert [_card_of(fake, word)["queue"] for word in ("冒険", "散歩")] == [0, 0]
    assert [_card_of(fake, word)["queue"] for word in ("須藤", "美術館")] == [-1, -1]


def test_suspending_is_refused_by_an_ankiconnect_that_cannot_undo_it(tmp_path):
    """Suspend is only offered back by `unsuspend`. An AnkiConnect without the pair is refused in
    preflight — and only when Suspend is ticked; reordering alone still passes."""
    fake = _later_backlog(tmp_path, actions=("setSpecificValueOfCard", "multi"))

    with _patched(fake):
        refused = reposition.preflight(_settings(junban_order="content", junban_later_suspend=True))
        fine = reposition.preflight(_settings(junban_order="content"))

    assert not refused["ok"] and "suspend" in " ".join(refused["problems"])
    assert fine["ok"], fine["problems"]


def test_a_restore_refused_for_another_deck_unsuspends_nothing(tmp_path):
    """The scope check runs BEFORE the first write: a restore asked for the wrong deck must leave
    Junban's suspended cards exactly as they are, not unsuspend them and then refuse."""
    fake = _later_backlog(tmp_path)
    with _patched(fake):
        reposition.run(_settings(junban_order="content", junban_later_suspend=True))

    with _patched(fake):
        refused = reposition.restore(_settings(junban_order="content", junban_deck="Mining"))

    assert not refused["ok"] and "different scope" in refused["problems"][0]
    assert not any(action == "unsuspend" for action, _ids in fake.suspend_calls)
    assert _card_of(fake, "須藤")["queue"] == -1


# --------------------------------------------------------------------------- #
# Restore
# --------------------------------------------------------------------------- #
def test_restore_returns_every_card_to_where_it_started(backlog):
    before = {card_id: card["due"] for card_id, card in backlog.cards.items()}

    with _patched(backlog):
        reposition.run(_settings())
        assert {c["due"] for c in backlog.cards.values()} != set(before.values()) or True
        report = reposition.restore(_settings())

    assert report["ok"] is True
    assert {card_id: card["due"] for card_id, card in backlog.cards.items()} == before


def test_restore_refuses_a_snapshot_taken_for_another_scope(ranked_words, write_priority_csv):
    """Replaying one deck's positions into a different run would write real positions into cards the
    snapshot never covered — a second mess on top of the first."""
    write_priority_csv()
    bank, bank_notes, _ = _collection(ranked_words[:6], dues=[2805, 2804, 2803, 2802, 2801, 2800])
    other, other_notes, _ = _collection(ranked_words[6:10], deck="The Accelerator", start=50)
    fake = FakeCollection(bank + other, bank_notes + other_notes)

    with _patched(fake):
        reposition.run(_settings())                     # snapshot taken for TheBank alone
        fake.writes.clear()
        report = reposition.restore(_settings(junban_scope="all"))

    assert report["ok"] is False
    assert fake.writes == []
    assert any("different scope" in problem for problem in report["problems"])


def test_an_all_decks_restore_survives_a_deck_running_out_of_new_cards(ranked_words,
                                                                       write_priority_csv):
    """"All decks" means every deck that still holds a new card — a list that changes the moment the
    user studies a small deck's last new card. The saved list then never matched again, and Restore
    was refused with no way back at all."""
    write_priority_csv()
    bank, bank_notes, _ = _collection(ranked_words[:6], dues=[2805, 2804, 2803, 2802, 2801, 2800])
    small, small_notes, _ = _collection(ranked_words[6:8], deck="The Accelerator", start=50,
                                        dues=[2851, 2850])
    fake = FakeCollection(bank + small, bank_notes + small_notes)
    original = {card_id: card["due"] for card_id, card in fake.cards.items()}
    settings = _settings(junban_scope="all")

    with _patched(fake):
        assert reposition.run(settings)["ok"] is True
        for card in fake.cards.values():             # The Accelerator's new cards get studied
            if card["deckName"] == "The Accelerator":
                card["type"], card["queue"], card["due"] = 2, 2, 42
        report = reposition.restore(settings)

    assert report["ok"] is True, report["problems"]
    for card_id, card in fake.cards.items():
        if card["deckName"] == "TheBank":
            assert card["due"] == original[card_id]
        else:
            assert card["due"] == 42, "a card studied since is never written to"


def test_restore_with_nothing_saved_says_so_and_touches_nothing(backlog):
    with _patched(backlog):
        report = reposition.restore(_settings())

    assert report["ok"] is False
    assert backlog.writes == []
    assert any("no saved order" in problem.lower() for problem in report["problems"])


def test_restore_leaves_cards_the_user_has_since_studied_alone(backlog):
    """A card studied since the snapshot was taken is a review card now, and its `due` is a day
    number. Writing a queue position onto it would silently reschedule it — so it is skipped, and
    the count is reported rather than quietly dropped."""
    with _patched(backlog):
        reposition.run(_settings())
        studied = sorted(backlog.cards)[0]
        backlog.cards[studied].update({"type": 2, "queue": 2, "due": 217})
        backlog.writes.clear()
        report = reposition.restore(_settings())

    assert report["ok"] is True
    assert studied not in {card_id for card_id, _due in backlog.writes}
    assert backlog.cards[studied]["due"] == 217
    assert "had moved on" in report["message"]


def test_restore_degrades_when_anki_is_closed(backlog):
    with _patched(backlog):
        reposition.run(_settings())
    backlog.offline = True
    with _patched(backlog):
        report = reposition.restore(_settings())

    assert report["ok"] is False
    assert any("Anki" in problem for problem in report["problems"])


# --------------------------------------------------------------------------- #
# WP-L — the optional card touch-ups, end to end
# --------------------------------------------------------------------------- #
# The measured shape on the user's own 115 anki_miner notes: 96/115 carry JPDB's entry in
# `Frequency` and its bare number in `FreqSort`, and `SelectionText` is the only empty field.
JPDB = "<ul><li>JPDBv2㋕: 54614</li></ul>"

LAPIS_FIELDS = ("Expression", "Sentence", "Frequency", "FreqSort", "Glossary", "MiscInfo",
                "Hint", "SelectionText")


def _lapis_note(note_id, word, sentence=None, frequency=JPDB, freqsort="54614",
                selection="", tags=None):
    """A Lapis note as `notesInfo` returns it — the real field set, in Anki's own order."""
    values = {"Expression": word,
              "Sentence": sentence if sentence is not None else f"{word}が出てくる場面。",
              "Frequency": frequency,
              "FreqSort": freqsort,
              "Glossary": f"<div>{word}</div>",
              "MiscInfo": "[SubsPlease] Tetsunabe no Jan! - 04",
              "Hint": "",
              "SelectionText": selection}
    return {"noteId": note_id, "modelName": "Lapis",
            "tags": list(tags or []),
            "fields": {name: {"value": values[name], "order": index}
                       for index, name in enumerate(LAPIS_FIELDS)}}


@pytest.fixture
def real_priority_csv(tmp_path):
    """A real export copied verbatim into the sandboxed `results/`, `Context N` columns and all.

    The narrower `write_priority_csv` above deliberately writes only the columns the ORDERING needs;
    the example-sentence touch-up reads three more, and reading them off a genuine export is the
    only way to know the sentences are real Japanese rather than something a test made up.
    """
    with open(_RESOURCE_CSV, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    path = os.path.join(str(tmp_path), "results", "priority_learning_list.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return rows


@pytest.fixture
def touchup_backlog(real_priority_csv, ranked_words):
    """Six real ranked words plus two the list does not know, mined in the wrong order.

    Every card moves, so every matched note is a candidate for all three touch-ups — which is what
    makes the "unmatched gets nothing" assertions mean something.
    """
    words = ranked_words[:6] + UNRANKED[:2]
    dues = list(range(2800 + len(words) - 1, 2799, -1))
    cards, notes = [], []
    for index, word in enumerate(words):
        note_id = FIRST_NOTE + index
        notes.append(_lapis_note(note_id, word))
        cards.append(_card(FIRST_CARD + index, note_id, dues[index]))
    return FakeCollection(cards, notes)


def _touched(fake, note_id):
    """One note's fields as they stand in the fake collection now."""
    return {name: value["value"] for name, value in fake.notes[note_id]["fields"].items()}


def test_nothing_is_written_to_a_note_when_every_touch_up_is_off(touchup_backlog):
    """The module as it behaved before WP-L: `due` and nothing else. With the tag cleared this is
    the whole feature switched off, and the wire must show it."""
    with _patched(touchup_backlog):
        report = reposition.run(_settings(junban_tag=""))

    assert report["ok"] is True and report["written"]
    assert touchup_backlog.note_writes == [], "a note was edited with every touch-up off"
    assert touchup_backlog.tag_calls == []
    assert "updateNoteFields" not in touchup_backlog.action_names


def test_only_the_notes_of_moved_matched_cards_are_tagged(touchup_backlog):
    """The tag is the answer to "which of these did Surasura touch?", so it has to be true: no
    unmatched card, and no card that was already in the right place."""
    with _patched(touchup_backlog):
        report = reposition.run(_settings())

    assert report["ok"] is True
    tagged = set(report["tagged"])
    matched_notes = {FIRST_NOTE + index for index in range(6)}
    unmatched_notes = {FIRST_NOTE + 6, FIRST_NOTE + 7}
    assert tagged == matched_notes
    assert not (tagged & unmatched_notes), "an unmatched card's note was tagged"
    for note_id in unmatched_notes:
        assert "Surasura" not in touchup_backlog.notes[note_id]["tags"]
    assert "tagged 6 notes 'Surasura'" in report["message"]


def test_the_frequency_entry_is_appended_beside_jpdbs_and_the_sort_key_is_left_alone(
        touchup_backlog):
    """The two halves of the measured reality in one run: `Frequency` is a list and gains an entry,
    `FreqSort` is a single sort key the user's browser ordering depends on and is NOT touched."""
    with _patched(touchup_backlog):
        report = reposition.run(_settings(junban_write_frequency=True))

    assert report["ok"] is True
    fields = _touched(touchup_backlog, FIRST_NOTE)
    assert "JPDBv2㋕: 54614" in fields["Frequency"]
    assert fields["Frequency"].count("<li>") == 2
    assert fields["FreqSort"] == "54614", "the browser's sort key was overwritten without being asked"
    assert all("FreqSort" not in values for _note_id, values in touchup_backlog.note_writes)


def test_the_sort_key_is_written_only_when_its_own_key_is_on(touchup_backlog):
    with _patched(touchup_backlog):
        reposition.run(_settings(junban_write_frequency=True, junban_write_freqsort=True))

    fields = _touched(touchup_backlog, FIRST_NOTE)
    assert fields["FreqSort"] != "54614"
    assert fields["FreqSort"].isdigit()
    assert "JPDBv2㋕: 54614" in fields["Frequency"], "the append still appends"


def test_a_second_run_replaces_our_entry_rather_than_adding_a_second(touchup_backlog):
    """Pressing Reorder again a week later must not grow a column of stale Surasura entries."""
    settings = _settings(junban_write_frequency=True)
    with _patched(touchup_backlog):
        reposition.run(settings)
        first = _touched(touchup_backlog, FIRST_NOTE)["Frequency"]
        # Shuffle the queue so there is something to reorder, and run it all again.
        for index, card_id in enumerate(sorted(touchup_backlog.cards)):
            touchup_backlog.cards[card_id]["due"] = 2900 + index
        reposition.run(settings)

    second = _touched(touchup_backlog, FIRST_NOTE)["Frequency"]
    assert second.count("Surasura:") == 1, "a second entry accumulated"
    assert second == first
    assert "JPDBv2㋕: 54614" in second


def test_only_the_named_frequency_field_is_ever_written(touchup_backlog):
    """WP-L: a note field is written only when the user named it — with the frequency on, that
    field and nothing else (the extra sentence is Backfill's 例文 now, 2026-09-24)."""
    with _patched(touchup_backlog):
        reposition.run(_settings(junban_write_frequency=True))

    for _note_id, values in touchup_backlog.note_writes:
        assert set(values) <= {"Frequency"}, f"an unnominated field was written: {sorted(values)}"
    assert _touched(touchup_backlog, FIRST_NOTE)["SelectionText"] == ""
    assert _touched(touchup_backlog, FIRST_NOTE)["Hint"] == ""


def test_the_prior_values_are_on_disk_before_the_field_write_reaches_the_wire(touchup_backlog):
    """Invariant I3, extended to WP-L and the single most important claim in this section.

    A clobbered field has destroyed the user's own content and the snapshot is the ONLY copy, so
    the check is not "was `undo.save` called" but "was the prior value READABLE ON DISK at the
    instant the first field write arrived".
    """
    seen = {}

    def _peek():
        with open(undo.snapshot_path("ja"), "r", encoding="utf-8") as handle:
            seen.update(json.load(handle))

    touchup_backlog.on_note_write = _peek
    with _patched(touchup_backlog):
        reposition.run(_settings(junban_write_frequency=True))

    assert seen, "no snapshot existed when the first field write arrived"
    assert seen["fields"][str(FIRST_NOTE)]["Frequency"]["before"] == JPDB
    assert FIRST_NOTE in seen["tags"] and seen["tag"] == "Surasura"


def test_restore_puts_the_fields_back_and_takes_our_tag_off(touchup_backlog):
    with _patched(touchup_backlog):
        reposition.run(_settings(junban_write_frequency=True, junban_write_freqsort=True))
        assert _touched(touchup_backlog, FIRST_NOTE)["Frequency"] != JPDB
        report = reposition.restore(_settings(junban_write_frequency=True))

    assert report["ok"] is True, report["problems"]
    fields = _touched(touchup_backlog, FIRST_NOTE)
    assert fields["Frequency"] == JPDB
    assert fields["FreqSort"] == "54614"
    assert "Surasura" not in touchup_backlog.notes[FIRST_NOTE]["tags"]
    assert report["fields_skipped"] == 0


def test_the_users_own_sort_number_survives_a_second_run(touchup_backlog):
    """With the FreqSort overwrite on, the user's own sort number (54614) existed only in the undo
    file, and the next run of ANY deck replaced that file. Restore after the second run must still
    give it back, whether or not that run needed to write the field again."""
    settings = _settings(junban_write_frequency=True, junban_write_freqsort=True)
    with _patched(touchup_backlog):
        assert reposition.run(settings)["ok"] is True
        # New mining puts the queue out of order again, so the second run moves cards too.
        for index, card in enumerate(sorted(touchup_backlog.cards.values(),
                                            key=lambda c: c["cardId"])):
            card["due"] = 3100 - index
        assert reposition.run(settings)["ok"] is True
        report = reposition.restore(settings)

    assert report["ok"] is True, report["problems"]
    for note_id in touchup_backlog.notes:
        fields = _touched(touchup_backlog, note_id)
        assert fields["FreqSort"] == "54614", f"note {note_id} lost its own sort number"
        assert fields["Frequency"] == JPDB


def test_restore_skips_a_field_the_user_edited_after_the_run_and_says_how_many(touchup_backlog):
    """The promise that makes Restore safe to press. Their edit is newer than anything the snapshot
    knows about, and reverting it would destroy writing that exists nowhere else."""
    with _patched(touchup_backlog):
        reposition.run(_settings(junban_write_frequency=True))
        mine = _touched(touchup_backlog, FIRST_NOTE)["Frequency"] + "<p>私のメモ</p>"
        touchup_backlog.notes[FIRST_NOTE]["fields"]["Frequency"]["value"] = mine
        report = reposition.restore(_settings(junban_write_frequency=True))

    assert report["fields_skipped"] == 1
    assert "had been edited since the reorder" in report["message"]
    assert _touched(touchup_backlog, FIRST_NOTE)["Frequency"] == mine, "the user's edit was reverted"
    # Every other note still comes back.
    assert _touched(touchup_backlog, FIRST_NOTE + 1)["Frequency"] == JPDB


def test_restore_never_removes_a_tag_the_user_put_there_themselves(real_priority_csv, ranked_words):
    """A note that already carried the tag was never recorded, so a restore cannot strip it."""
    note = _lapis_note(FIRST_NOTE, ranked_words[0], tags=["Surasura", "anki_miner"])
    fake = FakeCollection([_card(FIRST_CARD, FIRST_NOTE, 2801),
                           _card(FIRST_CARD + 1, FIRST_NOTE + 1, 2800)],
                          [note, _lapis_note(FIRST_NOTE + 1, ranked_words[1])])

    with _patched(fake):
        reposition.run(_settings())
        reposition.restore(_settings())

    assert "Surasura" in fake.notes[FIRST_NOTE]["tags"], "a tag the user owns was removed"
    assert "Surasura" not in fake.notes[FIRST_NOTE + 1]["tags"]


def test_a_refused_note_write_is_reported_without_losing_the_reorder(touchup_backlog):
    """AnkiConnect answering `error: "…"` is a refusal, not a dead socket. The positions already
    landed and the report has to say both things — and the snapshot stays on disk."""
    touchup_backlog.refuse_note_writes = "note was not found"
    with _patched(touchup_backlog):
        report = reposition.run(_settings(junban_write_frequency=True))

    assert report["ok"] is False
    assert report["written"], "the reorder itself succeeded and must be reported as such"
    assert len(report["note_failures"]) == 6
    assert "not found" in report["problems"][0]
    assert os.path.isfile(report["snapshot"])


def test_a_preview_writes_no_field_and_adds_no_tag(touchup_backlog):
    """The dry run reads, plans the touch-ups so the preview can state them, and touches nothing."""
    with _patched(touchup_backlog):
        _writes, stats = reposition.dry_run(_settings(junban_write_frequency=True))

    assert touchup_backlog.note_writes == [] and touchup_backlog.tag_calls == []
    assert "updateNoteFields" not in touchup_backlog.action_names
    counts = stats["touchups"]["counts"]
    assert counts["tag"] == 6 and counts["frequency"] == 6
    assert counts["notes"] == 6, "only the matched, moving cards are counted"


def test_the_preview_offers_the_note_types_real_field_names(touchup_backlog):
    """The panel's field pickers are filled from this, so a user never has to guess a field name —
    and WP-L forbids Surasura guessing one for them."""
    with _patched(touchup_backlog):
        _writes, stats = reposition.dry_run(_settings())

    assert set(LAPIS_FIELDS) <= set(stats["field_names"])


def test_a_run_with_nothing_to_move_touches_no_note(touchup_backlog):
    """Idempotence, across all three: a second press writes no position, so nothing "moved", so
    nothing is tagged or edited either."""
    settings = _settings(junban_write_frequency=True)
    with _patched(touchup_backlog):
        reposition.run(settings)
        touchup_backlog.note_writes.clear()
        touchup_backlog.tag_calls.clear()
        report = reposition.run(settings)

    assert report["ok"] is True
    assert "already in the right place" in report["message"]
    assert touchup_backlog.note_writes == [] and touchup_backlog.tag_calls == []


# --------------------------------------------------------------------------- #
# WP-N — the marker tags, on the wire
# --------------------------------------------------------------------------- #
# Every row of the real export is ⚖ lopsided (its words come entirely from the HighPriority tier),
# so these tests exercise the marker path against genuine analyser output rather than counts a test
# made up — and they exercise the half of the mutual-exclusion rule that is easy to get wrong.
def test_the_marker_tags_reach_anki_as_ascii_sub_tags_of_the_parent(touchup_backlog):
    with _patched(touchup_backlog):
        report = reposition.run(_settings(junban_tag_markers=True))

    assert report["ok"] is True, report["problems"]
    added = {tag for action, _notes, tag in touchup_backlog.tag_calls if action == "addTags"}
    assert "Surasura" in added
    assert "Surasura::⚖" in added
    assert "Surasura::☆" not in added, "a lopsided word is never also starred"
    for tag in added:
        assert "︎" not in tag and "️" not in tag, (
            f"{tag} carries an invisible variation selector — Anki would treat it as a "
            f"different tag from the same glyph without one")
    assert report["marker_tagged"], "the report has to name what it marked"
    assert "marked" in report["message"]


def test_no_marker_tag_is_added_unless_the_switch_is_on(touchup_backlog):
    """Off by default, like every other thing junban writes into a note."""
    with _patched(touchup_backlog):
        reposition.run(_settings())

    added = {tag for action, _notes, tag in touchup_backlog.tag_calls if action == "addTags"}
    assert added == {"Surasura"}


def test_restore_takes_the_marker_tags_back_off_again(touchup_backlog):
    """The same promise as the plain tag: everything junban added, junban removes — and only from
    the notes it added it to."""
    with _patched(touchup_backlog):
        reposition.run(_settings(junban_tag_markers=True))
        assert "Surasura::⚖" in touchup_backlog.notes[FIRST_NOTE]["tags"]
        report = reposition.restore(_settings(junban_tag_markers=True))

    assert report["ok"] is True, report["problems"]
    assert touchup_backlog.notes[FIRST_NOTE]["tags"] == []
    assert "removed the marker tags" in report["message"]


def test_a_marker_tag_the_user_already_applied_is_left_alone_by_restore(real_priority_csv,
                                                                       ranked_words):
    """A note that already carried `Surasura::⚖` was never recorded, so Restore cannot take
    away a tag the user put there themselves."""
    words = ranked_words[:3]
    cards, notes = [], []
    for index, word in enumerate(words):
        note_id = FIRST_NOTE + index
        notes.append(_lapis_note(note_id, word,
                                 tags=["Surasura::⚖"] if index == 0 else None))
        cards.append(_card(FIRST_CARD + index, note_id, 2802 - index))
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        reposition.run(_settings(junban_tag_markers=True))
        reposition.restore(_settings(junban_tag_markers=True))

    assert fake.notes[FIRST_NOTE]["tags"] == ["Surasura::⚖"], \
        "the user's own tag was removed by a restore"


# --------------------------------------------------------------------------- #
# WP-O — rows the user deselected in the preview
# --------------------------------------------------------------------------- #
def test_a_deselected_card_is_written_to_the_back_and_the_rest_reorder_around_it(
        backlog, ranked_words):
    """The panel's click, all the way to the wire: the excluded card is planned as unmatched, so it
    keeps its existing order at the back and the cards the list does rank close up in front of it.

    The ids travel in the settings dict the panel hands the engine — the same dict the preview was
    taken from — so the run writes the order the user was actually looking at (I5)."""
    victim_card = FIRST_CARD + 3                      # the 4th ranked word, deselected
    with _patched(backlog):
        report = reposition.run(_settings(junban_exclude_cards=[victim_card]))

    assert report["ok"] is True and report["failures"] == []
    final = sorted(backlog.cards.values(), key=lambda card: card["due"])
    words = [backlog.notes[card["note"]]["fields"]["Expression"]["value"] for card in final]
    expected = [word for word in ranked_words[:24] if word != ranked_words[3]]

    assert words[:23] == expected, "the rest follow the list with no hole where the card was"
    assert ranked_words[3] in words[23:], "the deselected card belongs at the back"
    dues = [card["due"] for card in final]
    assert dues == list(range(2800, 2800 + len(final))), "the block stays contiguous, and where it was"


def test_the_preview_and_the_run_agree_card_for_card_with_rows_deselected(backlog):
    """I5 again, under the one thing that can change between them without a re-read: the preview is
    the confirmation, and it is only a confirmation while the run honours the same exclusions."""
    settings = _settings(junban_exclude_cards=[FIRST_CARD, FIRST_CARD + 5])
    with _patched(backlog):
        previewed, stats = reposition.dry_run(settings)
        report = reposition.run(settings)

    assert [card_id for card_id, _due in previewed] == report["written"]
    assert stats["deselected"] == 2
    assert report["stats"]["to_write"] == stats["to_write"]


def test_clicking_every_row_off_leaves_nothing_on_the_list(backlog):
    """The user (2026-09-23): a word clicked off the list is "treated as 'not-on-your-list'" — so
    with every row clicked off, nothing is placed as a list word: the 24 listed words go by their own
    sentences among the cards not on the list, and the six that were never on it (clicked off too) are
    left alone, at the very back in their existing order. Legal, and nothing is left unpositioned."""
    every = list(backlog.cards)
    with _patched(backlog):
        _writes, stats = reposition.dry_run(_settings(junban_exclude_cards=every))

    assert (stats["matched"], stats["taken_off"], stats["deselected"]) == (0, 24, 30)
    assert all(row.rank is None for row in stats["order"])
    tail = stats["order"][-6:]
    assert {row.word for row in tail} == set(UNRANKED)
    assert [row.due for row in tail] == sorted(row.due for row in tail), "their existing order"
    assert [row.position for row in stats["order"]] == list(range(2800, 2830)), "contiguous, in place"


def test_a_deselected_card_is_not_tagged_or_touched_up(touchup_backlog, ranked_words):
    """A deselected card is unmatched, and an unmatched card gets no tag, no frequency entry and no
    sentence — for free, because it comes out of the planner with no rank. The tag answers "which of
    these did Surasura touch?", and it must not claim one the user took out of the run."""
    victim_note = FIRST_NOTE + 2
    with _patched(touchup_backlog):
        report = reposition.run(_settings(junban_exclude_cards=[FIRST_CARD + 2],
                                          junban_write_frequency=True))

    assert report["ok"] is True
    assert victim_note not in report["tagged"]
    assert victim_note not in [note_id for note_id, _fields in touchup_backlog.note_writes]
    assert "Surasura" not in touchup_backlog.notes[victim_note]["tags"]
    assert _touched(touchup_backlog, victim_note)["Frequency"] == JPDB, "its frequency was edited"


def test_the_exclusion_is_a_run_time_key_and_never_a_setting(backlog):
    """WP-O: deselection is a decision about one run. It has no default, so it can never be written
    to `settings.json` by the core's module merge — a remembered exclusion the user cannot see would
    quietly leave cards out of every run from then on."""
    assert "junban_exclude_cards" not in junban.SETTINGS_DEFAULTS
    with _patched(backlog):
        _writes, stats = reposition.dry_run(_settings())
    assert stats["deselected"] == 0, "nothing is excluded unless the panel says so"


def test_a_garbage_exclusion_is_ignored_rather_than_obeyed(backlog):
    """Read defensively like every other setting: `True` is an `int` in Python, so a stray boolean
    would otherwise silently drop card id 1, and a string would be read as a bag of characters."""
    with _patched(backlog):
        baseline = reposition.dry_run(_settings())
        for junk in ("1789712080000", {"card": 1}, [True, False, None, "x"], 5):
            writes, stats = reposition.dry_run(_settings(junban_exclude_cards=junk))
            assert stats["deselected"] == 0, junk
            assert writes == baseline[0], junk


# --------------------------------------------------------------------------- #
# §16 — "Same word as one on your list?": suggested, never applied until the user ticks it
# --------------------------------------------------------------------------- #
def _check_backlog(tmp_path, card="みとれる"):
    """The real backlog's spelling variants (§12): みとれる — written in kana — on the card, 見惚れる on the
    list; 同行する on the card, the noun 同行 on the list. 冒険 matches exactly; 美術館 is on no list at all.
    `card="見とれる"`: the same word written with its kanji."""
    _results(tmp_path, priority=[("冒険", "冒険", 100, 5), ("見惚れる", "見惚れる", 90, 4), ("同行", "同行", 80, 3)],
             library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    return _mined([("美術館", "美術館で本を読んだ。", 6000, ""),
                   ("同行する", "私も<b>同行する</b>よ", 15000, ""),
                   (card, f"思わず<b>{card[:-1]}て</b>しまった。", 12000, ""),
                   ("冒険", "彼は毎日冒険に出かける。", 9000, "")])


def _row(stats, word):
    return next(row for row in stats["order"] if row.word == word)


def test_a_card_spelled_another_way_is_offered_and_moves_nothing_until_it_is_ticked(tmp_path):
    """The user reversed I6 (§16.1): nothing is pre-ticked. The card keeps its sentence's place, and
    carries the place a tick would give it. A kana card is asked about through its own sentence — read
    alone, kana is the tagger's guess (まく -> 膜). Not so a word with its する (2026-09-26, "I'd prefer them
    to be one word"): 同行する IS 同行, placed with the list and never asked about
    (Anki_Match_Consistency_Scope.md item 2)."""
    fake = _check_backlog(tmp_path)
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    assert [(entry["word"], entry["key"], entry["reading"], entry["evidence"], entry["answer"])
            for entry in stats["suggestions"]] == [
        ("みとれる", "見惚れる", "みとれる", "same word, other spelling", None)]
    assert stats["suggestions"][0]["excerpt"] == "思わず【みとれて】しまった。"
    assert stats["matched"] == 2, "冒険 exactly, and 同行する as 同行 — the other spelling waits for the user"
    assert (_row(stats, "同行する").tier, _row(stats, "同行する").why) == ("list", "list #3")
    row = _row(stats, "みとれる")
    assert row.rank is None and row.tier != "list"
    assert row.suggestion[0] == "見惚れる" and row.suggestion[1] == 1
    assert row.suggestion[3] == "list #2" + reposition.MATCHED_BY_YOU


def test_a_kanji_card_read_alone_as_one_word_is_placed_with_no_question(tmp_path):
    """The user, 2026-09-29: Junban and the report's "In Anki" label give one answer. 見とれる holds a kanji
    and, read alone, is ONE word — UniDic's 見惚れる, the list's row — so it is placed there as the label
    marks it, never asked about; only a kana card or a word its sentence alone shows still asks."""
    fake = _check_backlog(tmp_path, card="見とれる")
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    assert stats["suggestions"] == []
    assert stats["matched"] == 3, "冒険 exactly, 同行する as 同行, 見とれる as 見惚れる"
    assert (_row(stats, "見とれる").tier, _row(stats, "見とれる").why) == ("list", "list #2")


def test_a_card_for_a_storys_own_kanji_term_is_placed_at_its_row(tmp_path):
    """A story's own kanji term the library keeps using as one (app/names.py — 焔魄陣, a made-up technique the tagger
    cuts 焔 + 魄 + 陣) is a row of the list, keyed as a word no dictionary has: the spelling, no reading. A card mined
    for it takes that row's place with no question asked."""
    from app import names
    _results(tmp_path, priority=[("冒険", "冒険", 100, 5), ("焔魄陣", "焔魄陣", 90, 4)],
             library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    fake = _mined([("焔魄陣", "彼は<b>焔魄陣</b>を放った。", 12000, ""), ("冒険", "彼は毎日冒険に出かける。", 9000, "")])
    names.use_library_tables({"k": {}, "j": {}, "w": {"焔魄陣": [1.0, "焔魄陣", "", "焔魄陣"]}, "stamp": "term"},
                             pin=True)
    try:
        with _patched(fake):
            _writes, stats = reposition.dry_run(_settings())
    finally:
        names.forget_library_tables()
    assert stats["suggestions"] == []
    assert (_row(stats, "焔魄陣").tier, _row(stats, "焔魄陣").why) == ("list", "list #2")


def test_a_known_word_with_its_suru_goes_last_and_a_listed_sound_word_with_its_to_takes_its_place(tmp_path):
    """The user, 2026-09-26: 努力する and 仲良くする came up among the next new cards although 努力 and 仲良く
    were known — UniDic reads each as the word + する, so each was placed as a two-word phrase ("is it
    double counting 努力?"). A word with ONE ending written onto it is that word: known, it goes last;
    on the list — a tester's バシッと, 2026-09-26 — it takes the word's place, with no question. (A sound word
    ending in っ + と is one token, the sound word shown with と, so a list built since shows the row as the
    content writes it — バシッと — and the card lands there by its own spelling.)"""
    _results(tmp_path, priority=[("ばし", "バシッと", 90, 12), ("無関係", "無関係", 1, 1)],
             library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["努力", "仲良く", "毎日", "皆"])
    fake = _mined([("努力する", "毎日<b>努力する</b>。", 3000, ""),
                   ("仲良くする", "みんなと<b>仲良くする</b>。", 3100, ""),
                   ("バシッと", "ドアを<b>バシッと</b>閉めた。", 3200, "")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    assert (_row(stats, "バシッと").tier, _row(stats, "バシッと").why) == ("list", "list #1")
    assert _row(stats, "努力する").why == "known" and _row(stats, "仲良くする").why == "known"
    assert [row.word for row in stats["order"]][-2:] == ["努力する", "仲良くする"], "known words go last"
    assert stats["suggestions"] == [], "none of them is a question any more"


def test_a_word_ignored_in_the_known_words_file_goes_last_like_a_known_one(tmp_path):
    """The user, 2026-09-29: KnownWord.json's IGNORED entries (Migaku's status — a word dismissed there) are
    ignored words, as a line of the Ignore list is — for the list, the sentences and 順 alike. A card for
    one is no word to learn next: it goes last, and never counts as an unknown beside another card."""
    _results(tmp_path, priority=[("冒険", "冒険", 100, 5), ("探検", "探検", 90, 4)],
             library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    folder = os.path.join(str(tmp_path), "User Files", "ja")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "KnownWord.json"), "w", encoding="utf-8") as handle:
        json.dump({"words": [{"dictForm": "探検", "knownStatus": "IGNORED"},
                             {"dictForm": "毎日", "knownStatus": "KNOWN"}]}, handle, ensure_ascii=False)
    fake = _mined([("探検", "毎日<b>探検</b>に出かける。", 1200, ""),
                   ("冒険", "毎日<b>冒険</b>に出かける。", 9000, "")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert [(row.word, row.tier, row.why) for row in stats["order"]] == [
        ("冒険", "list", "list #1"), ("探検", "known", "known")]


def test_a_known_word_goes_last_even_where_the_list_has_a_key_for_it(tmp_path):
    """D3, "whatever else matched it" (2026-09-27): known is tested before the
    list key, for every card. The user knows だいぶ and 好き, yet the list's kana fold filed だいぶ under the
    loanword ダイブ 'dive', and 好き is a spelling in the verb 好く's Forms — each card took a list slot.
    Both go last now, "i+1 first" never brings one forward, and the list's own word keeps its place."""
    path = os.path.join(str(tmp_path), "results", "priority_learning_list.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Word", "Orth", "Reading", "Forms", "Score", "Occurrences"])
        writer.writerows([("ダイブ", "ダイブ", "ダイブ", "", 90, 12), ("好く", "好く", "スク", "好き|好か", 80, 11),
                          ("冒険", "冒険", "ボウケン", "", 70, 10)])
    _known(tmp_path, ["だいぶ", "好き"])
    fake = _mined([("だいぶ", "<b>だいぶ</b>慣れてきた。", 1200, ""),
                   ("好き", "猫が<b>好き</b>だ。", 300, ""),
                   ("冒険", "明日から<b>冒険</b>に出かけよう。", 9000, "")])

    for ready_first in (False, True):
        with _patched(fake):
            _writes, stats = reposition.dry_run(_settings(junban_ready_first=ready_first))
        assert [(row.word, row.tier, row.rank, row.why) for row in stats["order"]] == [
            ("冒険", "list", 2, "list #3"), ("だいぶ", "known", None, "known"), ("好き", "known", None, "known")]
        assert stats["matched"] == 1 and stats["tiers"]["known"] == 2


def test_a_word_written_in_kana_is_known_only_by_the_reading_its_letters_spell(tmp_path):
    """2026-09-27: read alone, kana is the tagger's guess — かに comes out
    か + に, かする か + する, カミ the lemma 上 — so a card written in kana is known as card_key reads it, by
    its own letters: never through a single kana (the particle か is known), never through a lemma known in
    another reading (上 known as うえ says nothing of かみ). A word known WITH the reading its letters spell
    still is — あおぐ (仰ぐ), ホッとする (ほっと + する) — so is a lemma the ignore list holds (たまに: 偶に),
    and a kanji card still reads through its lemma (帰れる → 帰る). Backfill's known skip (`known_test`)
    and Junban's known tier give one answer."""
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["か", "上", "仰ぐ", "ほっと", "帰る"])
    with open(os.path.join(str(tmp_path), "User Files", "ja", "IgnoreList.txt"), "w", encoding="utf-8") as handle:
        handle.write("偶に\n")
    cards = ["かに", "かする", "カミ", "あおぐ", "ホッとする", "たまに", "帰れる"]
    known = ["あおぐ", "ホッとする", "たまに", "帰れる"]

    is_known = reposition.known_test("ja", _settings())
    assert [word for word in cards if is_known(word)] == known

    fake = _mined([(word, "", 1000 + i, "") for i, word in enumerate(cards)])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert [row.word for row in stats["order"] if row.tier == "known"] == known
    assert [row.word for row in stats["order"] if row.tier == "rest"] == ["かに", "かする", "カミ"]


def test_a_card_whose_base_is_known_goes_last_as_known(tmp_path):
    """お部屋, 俺たち and 優しさ are 部屋, 俺 and 優しい with their own grammar on them — the tokenizer keeps the
    polite お, the plural and the さ apart, and the list always counted the word. So a card for one whose word is
    known is known, whatever its phrase count, in Junban's tier and Backfill's skip alike. A kana card keeps its
    rule: おれたち is known only when 俺 is known read おれ; やさしさ keeps its さ (優しさ or 易しさ?)."""
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["部屋", "俺", "優しい", "挨拶"])
    cards = ["お部屋", "俺たち", "優しさ", "ご挨拶", "おれたち", "やさしさ", "お守り"]
    known = ["お部屋", "俺たち", "優しさ", "ご挨拶", "おれたち"]

    is_known = reposition.known_test("ja", _settings())
    assert [word for word in cards if is_known(word)] == known

    fake = _mined([(word, "", 1000 + i, "") for i, word in enumerate(cards)])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert [row.word for row in stats["order"] if row.tier == "known"] == known


def test_a_card_whose_base_is_on_the_list_lands_on_that_row(tmp_path):
    """With 部屋 and 俺 still to learn, an お部屋 or 俺たち card is placed at their rows, with no question."""
    _results(tmp_path, priority=[("部屋", "部屋", 5, 5), ("俺", "俺", 4, 4)],
             library={"部屋|ヘヤ": [5, 5, 0, 0, 1, 50, "部屋"], "俺|オレ": [4, 4, 0, 0, 1, 40, "俺"]})
    _known(tmp_path, ["無関係"])
    fake = _mined([("お部屋", "", 1000, ""), ("俺たち", "", 1001, "")])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    rows = {row.word: row for row in stats["order"]}
    assert rows["お部屋"].rank == 0 and rows["俺たち"].rank == 1


def test_a_card_the_dictionary_keeps_apart_is_never_known_through_the_word_it_is_read_as(tmp_path):
    """The dictionary decides (the user, 2026-09-30): 心する 'take heed', 一気に 'in one go' and 揚げる 'deep-fry' are
    JMdict entries of their own, apart from 心, 一気 and 上げる (UniDic's word for 揚げる), so knowing those says nothing
    of the cards — they go by their own sentence, in Junban's tier and Backfill's skip alike; ことに (殊に's reading)
    is no 事 + に. A card the dictionary does not set apart is known as before: 努力する through 努力, 信じる through
    UniDic's 信ずる (one verb, conjugated two ways), お部屋 through 部屋 (its own grammar); and a card the learner
    knows as itself is known."""
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["心", "一気", "上げる", "事", "努力", "信ずる", "部屋", "堪らない"])
    cards = ["心する", "一気に", "揚げる", "ことに", "努力する", "信じる", "お部屋", "堪らない"]
    known = ["努力する", "信じる", "お部屋", "堪らない"]

    is_known = reposition.known_test("ja", _settings())
    assert [word for word in cards if is_known(word)] == known

    fake = _mined([(word, "", 1000 + i, "") for i, word in enumerate(cards)])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert [row.word for row in stats["order"] if row.tier == "known"] == known
    assert [row.word for row in stats["order"] if row.tier == "rest"] == ["心する", "一気に", "揚げる", "ことに"]


def test_a_sentence_that_says_the_cards_own_word_again_is_still_i_plus_one(tmp_path):
    """2026-09-27: 撒け、撒け、撒くんだ！ and 企む奴が企む。 hold nothing new but the
    card's own word, said more than once — every other word is grammar, or 奴, a one-kanji word the learner knows.
    Junban counted each repeat beside the card ("2 unknown") and both cards dropped from i+1 to multi."""
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["奴"])
    fake = _mined([("撒く", "撒け、撒け、撒くんだ！", 3000, ""), ("企む", "企む奴が企む。", 3100, "")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    assert [(row.word, row.tier, row.why) for row in stats["order"]] == [("撒く", "i+1", "i+1"),
                                                                         ("企む", "i+1", "i+1")]


def test_a_hand_typed_field_is_placed_as_the_one_word_it_holds_and_a_past_as_its_verb(tmp_path):
    """A Japanese card holds ONE word. 撒く typed in quotes with its
    reading on a second line is 撒く, on the list; 取り消した, the past of a known 取り消す, is that word
    (JMdict's headword is the dictionary form) and goes last."""
    _results(tmp_path, priority=[("撒く", "撒く", 90, 12), ("無関係", "無関係", 1, 1)],
             library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["取り消す", "予約"])
    fake = _mined([("取り消した", "予約を<b>取り消した</b>。", 3000, ""),
                   ("「撒く」<br>まく", "庭に水を<b>撒く</b>。", 3100, "")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    assert (_row(stats, "撒く").tier, _row(stats, "撒く").why) == ("list", "list #1")
    assert [(row.word, row.why) for row in stats["order"]][-1] == ("取り消した", "known")


def test_a_yes_places_the_word_as_the_list_word_and_a_no_is_never_offered_again(tmp_path):
    from modules.junban import pairs
    fake = _check_backlog(tmp_path)
    pairs.record("ja", [("みとれる", "見惚れる", True, "L6"), ("同行する", "同行", False, "L7")])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())

    row = _row(stats, "みとれる")
    assert (row.tier, row.rank, row.why) == ("list", 1, "list #2" + reposition.MATCHED_BY_YOU)
    assert row.fallback is not None, "clicking it off the list still has somewhere to send it"
    assert stats["matched"] == 2
    answers = {entry["word"]: entry["answer"] for entry in stats["suggestions"]}
    assert answers == {"みとれる": "yes", "同行する": "no"}, "answered, so shown only as earlier answers"
    assert _row(stats, "同行する").tier != "list"


def test_the_preview_after_a_tick_is_the_run_after_the_answer_is_recorded(tmp_path):
    """I5: the panel re-plans a tick from the rows in hand (`with_answers` + `replan`); the run reads
    the answer the panel records. Card for card, position for position, reason for reason — both
    ways: ticking a suggestion, and unticking an earlier yes."""
    from modules.junban import pairs
    from modules.junban.plan import replan, with_answers
    fake = _check_backlog(tmp_path)

    def placed(stats):
        return [(row.card_id, row.position, row.tier, row.why) for row in stats["order"]]

    with _patched(fake):
        _writes, before = reposition.dry_run(_settings())
        ticked_writes, ticked = replan(with_answers(before["order"], {"みとれる": True}))
        pairs.record("ja", [("みとれる", "見惚れる", True, "L6")])
        run_writes, recorded = reposition.dry_run(_settings())
        assert placed(ticked) == placed(recorded) and ticked_writes == run_writes

        unticked_writes, unticked = replan(with_answers(recorded["order"], {"みとれる": False}))
        pairs.record("ja", [("みとれる", "見惚れる", False, "L6")])
        run_writes, recorded = reposition.dry_run(_settings())
        assert placed(unticked) == placed(recorded) and unticked_writes == run_writes


def test_a_run_never_records_an_answer_itself(tmp_path):
    """Only the panel records what the user ticked; a run — and so the automatic one — reads."""
    from modules.junban import pairs
    fake = _check_backlog(tmp_path)
    with _patched(fake):
        report = reposition.run(_settings())
    assert report["ok"] is True
    assert not os.path.exists(pairs.pairs_path("ja"))


def _sentence_list(tmp_path, rows):
    """A priority list in leverage order: `(word, score, [Context 1..3])` — the §17 tests give no
    contexts; the columns are the list's real shape."""
    path = os.path.join(str(tmp_path), "results", "priority_learning_list.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Word", "Orth", "Score", "Occurrences", "Context 1", "Context 2", "Context 3"])
        for word, score, contexts in rows:
            writer.writerow([word, word, score, score // 10] + list(contexts) + [""] * (3 - len(contexts)))


# --------------------------------------------------------------------------- #
# §17 — "i+1 first": the word a card's own sentence needs comes first, or the card waits
# --------------------------------------------------------------------------- #
def _mined_sentences(entries):
    """One Lapis card per `(word, its own sentence)`, mined in reverse — so every card has somewhere
    to go and the order below is Junban's, not the mining order's."""
    cards, notes = [], []
    for index, (word, sentence) in enumerate(entries):
        notes.append(_lapis_note(FIRST_NOTE + index, word, sentence=sentence))
        cards.append(_card(FIRST_CARD + index, FIRST_NOTE + index, 2900 - index))
    return FakeCollection(cards, notes)


def _ready(**over):
    return _settings(junban_ready_first=True, **over)


def _order_of(stats):
    return [(row.word, row.why) for row in stats["order"]]


def test_the_word_a_sentence_needs_comes_right_before_it_or_the_card_waits(tmp_path):
    """The user's rule (2026-09-24), on one list — leverage order 冒険, 散歩, 手紙, 眼鏡, 財布:

      * 散歩's sentence has 眼鏡, which comes later — and 眼鏡's own card is i+1 at 散歩's spot
        (掛ける is not on the list, 毎日 is known), so 眼鏡 is brought right before 散歩;
      * 手紙's sentence has 眼鏡 too — already brought forward, so already learned: 手紙 stays;
      * 冒険's sentence has 財布, which has no card of its own: 冒険 waits with the multi cards.
    """
    _known(tmp_path, ["持つ", "行く", "毎日"])
    _sentence_list(tmp_path, [("冒険", 100, []), ("散歩", 90, []), ("手紙", 85, []), ("眼鏡", 80, []),
                              ("財布", 70, [])])
    fake = _mined_sentences([("冒険", "冒険で財布を落とした。"), ("散歩", "散歩に眼鏡を持って行く。"),
                             ("手紙", "手紙に眼鏡の絵を描く。"), ("眼鏡", "眼鏡を毎日かける。")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_ready())

    assert _order_of(stats) == [("眼鏡", "first, for 散歩 · list #4"), ("散歩", "after 眼鏡 · list #2"),
                                ("手紙", "list #3"), ("冒険", "waits for 財布 · list #1")]
    assert stats["order"][3].tier == "multi" and stats["order"][3].rank is None
    assert stats["ready_first"] == {"pulled": 1, "held": 1}


def test_two_cards_that_need_each_other_never_loop(tmp_path):
    """散歩 needs 眼鏡 and 眼鏡's sentence needs 散歩: 眼鏡 is not i+1 at 散歩's spot, so it is not
    brought forward, and 散歩 waits. 眼鏡, after 散歩 on the list, counts 散歩 as learned and stays."""
    _known(tmp_path, ["持つ", "行く"])
    _sentence_list(tmp_path, [("散歩", 90, []), ("眼鏡", 80, [])])
    fake = _mined_sentences([("散歩", "散歩に眼鏡を持って行く。"), ("眼鏡", "眼鏡をかけて散歩に行く。")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_ready())

    assert _order_of(stats) == [("眼鏡", "list #2"), ("散歩", "waits for 眼鏡 · list #1")]
    assert stats["ready_first"] == {"pulled": 0, "held": 1}


def test_a_card_brought_forward_never_brings_anything_itself(tmp_path):
    """No chains: 散歩 needs 眼鏡, but 眼鏡's own sentence needs 財布 — so 散歩 waits rather than
    pulling 財布 AND 眼鏡 in front of it. 眼鏡 is then judged on its own: 財布's card is i+1 at its
    spot, so 財布 comes right before 眼鏡."""
    _known(tmp_path, ["持つ", "行く"])
    _sentence_list(tmp_path, [("散歩", 90, []), ("眼鏡", 80, []), ("財布", 70, [])])
    fake = _mined_sentences([("散歩", "散歩に眼鏡を持って行く。"), ("眼鏡", "眼鏡と財布を持って行く。"),
                             ("財布", "財布を持って行く。")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_ready())

    assert _order_of(stats) == [("財布", "first, for 眼鏡 · list #3"), ("眼鏡", "after 財布 · list #2"),
                                ("散歩", "waits for 眼鏡 · list #1")]
    assert stats["ready_first"] == {"pulled": 1, "held": 1}


def test_a_name_holds_a_card_back_like_any_word_unless_names_are_ignored(tmp_path):
    """The user, 2026-09-30: "you would still need to learn names UNLESS they select ignore names as a
    setting". 須藤 is on the list after 冒険, so 冒険 waits for it like any word, as the report counts it;
    コリアンタマー (a word the dictionary has never heard of) counts too — both used to pass for names here.
    With Settings' Ignore names on, the library's names are ignored words: 須藤 holds nothing back, while
    コリアンタマー, which UniDic knows as no name, still does. パピルス is a word, and counts either way. And
    with "i+1 first" off (the default) nothing about the order changes at all."""
    from app import token_index
    _known(tmp_path, ["行く"])
    _sentence_list(tmp_path, [("冒険", 100, []), ("散歩", 95, []), ("須藤", 90, []), ("コリアンタマー", 85, []),
                              ("パピルス", 80, [])])
    fake = _mined_sentences([("冒険", "須藤と冒険に行く。"), ("散歩", "コリアンタマーと散歩に行く。")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_ready())
        assert _order_of(stats) == [("散歩", "waits for コリアンタマー · list #2"), ("冒険", "waits for 須藤 · list #1")]

    library = os.path.join(str(tmp_path), "village.txt")        # the library the names come from, indexed
    with open(library, "w", encoding="utf-8") as handle:
        handle.write("須藤と冒険に行く。\nコリアンタマーと散歩に行く。\n")
    token_index.reconcile_language("ja", [library])
    with open(os.path.join(str(tmp_path), "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"logic": {"ignore_names": True}}, handle)
    with _patched(fake):
        _writes, stats = reposition.dry_run(_ready())
        assert _order_of(stats) == [("冒険", "list #1"), ("散歩", "waits for コリアンタマー · list #2")]

    fake = _mined_sentences([("冒険", "パピルスと冒険に行く。")])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_ready())
        assert _order_of(stats) == [("冒険", "waits for パピルス · list #1")], "a real word still counts"
        assert stats["ready_first"] == {"pulled": 0, "held": 1}
        _writes, stats = reposition.dry_run(_settings())
    assert stats["ready_first"] is None


def test_a_letter_named_in_kana_holds_a_card_back_and_a_number_never_does(tmp_path):
    """The sentence's words are the analyzer's (analyzer.word_lemma): デルタ is a letter's name UniDic files
    as the symbol δ — the word デルタ, on the list after 冒険, so 冒険 waits for it (as the one character δ it
    was skipped); 二十 is a number, never a word, so even a list row for it holds nothing
    back and 散歩 stays where the list puts it."""
    _known(tmp_path, ["行く"])
    _sentence_list(tmp_path, [("冒険", 100, []), ("散歩", 95, []), ("デルタ", 90, []), ("二十", 80, [])])
    fake = _mined_sentences([("冒険", "デルタと冒険に行く。"), ("散歩", "二十人で散歩に行く。")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_ready())

    assert _order_of(stats) == [("散歩", "list #2"), ("冒険", "waits for デルタ · list #1")]
    assert stats["ready_first"] == {"pulled": 0, "held": 1}


def test_a_sentence_that_says_its_own_word_twice_never_holds_the_card_back(tmp_path):
    """Only the first 冒険 is the card's marked span; the second is still the card's own word — the
    same list row — not a later word to wait for."""
    _known(tmp_path, ["毎日", "行く"])
    _sentence_list(tmp_path, [("冒険", 100, []), ("散歩", 90, [])])
    fake = _mined_sentences([("冒険", "冒険だ。毎日冒険に行く。")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_ready())
    assert _order_of(stats) == [("冒険", "list #1")]


def test_the_preview_a_click_and_the_run_agree(tmp_path):
    """I5: the moves ride on the rows' own sort keys, so re-planning a click in the panel keeps
    them, and the run writes what the preview showed."""
    from modules.junban.plan import replan
    _known(tmp_path, ["持つ", "行く", "毎日"])
    _sentence_list(tmp_path, [("冒険", 100, []), ("散歩", 90, []), ("手紙", 85, []), ("眼鏡", 80, []),
                              ("財布", 70, [])])
    fake = _mined_sentences([("冒険", "冒険で財布を落とした。"), ("散歩", "散歩に眼鏡を持って行く。"),
                             ("手紙", "手紙に眼鏡の絵を描く。"), ("眼鏡", "眼鏡を毎日かける。")])

    with _patched(fake):
        writes, stats = reposition.dry_run(_ready())
        _writes, clicked = replan(stats["order"], {FIRST_CARD + 2})       # 手紙 left alone
        report = reposition.run(_ready())

    assert [row.word for row in clicked["order"]][:2] == ["眼鏡", "散歩"]
    assert "冒険" in [row.word for row in clicked["order"] if row.tier == "multi"]
    assert report["ok"] is True
    assert sorted(report["written"]) == sorted(card_id for card_id, _due in writes)
    assert {card_id: due for card_id, due in fake.writes} == dict(writes), "the positions previewed"


# --------------------------------------------------------------------------- #
# The list's own learning rule (analyzer.LearningView): a card's sentence is read as the list reads it
# --------------------------------------------------------------------------- #
# Dictionary compounds, joined by a fixture table (the tokenizer's join and its parts table patched), so these
# tests hold whatever the shipped table holds. (lemma, reading, parts: (part lemma, part reading, free)).
_COMPOUNDS = {
    "秘密結社": ("秘密結社", "ヒミツケッシャ", (("秘密", "ヒミツ", True), ("結社", "ケッシャ", True))),
    "トランスジェンダー": ("トランスジェンダー", "トランスジェンダー",
                   (("トランス", "トランス", True), ("ジェンダー", "ジェンダー", True))),
    "千載一遇": ("千載一遇", "センザイイチグウ", (("千載", "センザイ", False), ("一遇", "イチグウ", False))),
    "自動車学校": ("自動車学校", "ジドウシャガッコウ", (("自動車", "ジドウシャ", True), ("学校", "ガッコウ", True))),
}


@pytest.fixture
def compounds(monkeypatch):
    from app import analyzer
    real = analyzer.join_affixes

    def join(words, joins=None, library=True, **options):
        words = real(words, joins, library, **options)
        out, i = [], 0
        while i < len(words):
            word = words[i]
            if isinstance(word, analyzer.JoinedWord) and word.surface in _COMPOUNDS:
                lemma, reading, _parts = _COMPOUNDS[word.surface]
                out.append(analyzer.JoinedWord(word.surface, word.feature._replace(lemma=lemma, lForm=reading),
                                               word.parts, word.white_space))
                i += 1
                continue
            run = words[i:i + 2]
            spelling = "".join(w.surface for w in run)
            if len(run) == 2 and spelling in _COMPOUNDS:
                lemma, reading, _parts = _COMPOUNDS[spelling]
                out.append(analyzer._joined(run, spelling, "名詞", (lemma, reading)))
                i += 2
            else:
                out.append(word)
                i += 1
        return out
    monkeypatch.setattr(analyzer, "join_affixes", join)
    monkeypatch.setattr(analyzer, "compound_parts",
                        lambda: {(lemma, reading): parts for lemma, reading, parts in _COMPOUNDS.values()})


def _map_entry(uses):
    return [uses, uses, 0, 0, 1, uses * 10, ""]


def _why_by_sentence(tmp_path, sentence, known, rare=None, **settings):
    """Where a 撒く card the list doesn't hold goes by its own sentence — the row's "why". `rare`: compounds the
    last Generate met too seldom for the list, {key: uses} under a cut-off of 3; None: no library map yet.
    `settings`: what the run's settings say besides (exclude_single)."""
    library = {"無関係|ムカンケイ": _map_entry(3)}
    library.update({key: _map_entry(uses) for key, uses in (rare or {}).items()})
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library=library, floor=3 if rare is not None else None)
    _known(tmp_path, known)
    with _patched(_mined([("撒く", sentence, 5000, "")])):
        _writes, stats = reposition.dry_run(_settings(**settings))
    return stats["order"][0].why


# 餌, a one-kanji dictionary word, is on the list and new where it stands on its own: the tests about another word
# beside the card know it (test_a_one_character_word_the_list_cant_offer_is_no_unknown_beside_the_card).
def test_a_word_read_through_its_known_word_is_no_unknown_beside_the_card(tmp_path):
    """利用者 with 利用 known is read already, as in the report and 例文: the card is i+1 (it counted 利用者)."""
    assert _why_by_sentence(tmp_path, "利用者が餌を<b>撒い</b>た。", ["利用", "餌"]) == "i+1"
    assert _why_by_sentence(tmp_path, "利用者が餌を<b>撒い</b>た。", ["餌"]) == "1 unknown"


def test_a_compound_none_of_whose_parts_is_unknown_is_no_unknown_beside_the_card(tmp_path, compounds):
    """秘密結社 with 秘密 and 結社 known is read already; with 結社 unknown it is one word to learn."""
    assert _why_by_sentence(tmp_path, "秘密結社が餌を<b>撒い</b>た。", ["秘密", "結社", "餌"]) == "i+1"
    assert _why_by_sentence(tmp_path, "秘密結社が餌を<b>撒い</b>た。", ["秘密", "餌"]) == "1 unknown"


def test_a_compound_too_rare_for_the_list_counts_as_its_parts_beside_the_card(tmp_path, compounds):
    """With the last Generate's map: トランスジェンダー (1 use, free halves) is two words to learn, 千載一遇 (bound
    halves) one. Before the first Generate a compound is one word."""
    assert _why_by_sentence(tmp_path, "トランスジェンダーが餌を<b>撒い</b>た。", ["餌"]) == "1 unknown"
    assert _why_by_sentence(tmp_path, "トランスジェンダーが餌を<b>撒い</b>た。", ["餌"],
                            rare={"トランスジェンダー|トランスジェンダー": 1}) == "2 unknown"
    assert _why_by_sentence(tmp_path, "千載一遇の餌を<b>撒い</b>た。", ["餌"],
                            rare={"千載一遇|センザイイチグウ": 1}) == "1 unknown"


def test_a_one_character_word_the_list_cant_offer_is_no_unknown_beside_the_card(tmp_path):
    """The list's rule for one-character words, beside a card as everywhere: スバル (read as 昴, a name the list never
    offers) and the particles are nothing to learn; 餌, a one-kanji dictionary word, is an honest unknown where it
    stands on its own; 年 right after a number (三年) is a count, no unknown, though 年 alone is one. With Settings'
    "List one-kanji words only when they're dictionary words" off, every one-character word counts."""
    assert _why_by_sentence(tmp_path, "スバルは餌を<b>撒い</b>た。", ["餌"]) == "i+1"
    assert _why_by_sentence(tmp_path, "スバルは餌を<b>撒い</b>た。", []) == "1 unknown"
    assert _why_by_sentence(tmp_path, "三年前に餌を<b>撒い</b>た。", ["餌"]) == "i+1"
    assert _why_by_sentence(tmp_path, "年が明けて餌を<b>撒い</b>た。", ["餌", "明ける"]) == "1 unknown"
    assert _why_by_sentence(tmp_path, "スバルは餌を<b>撒い</b>た。", ["餌"], exclude_single=False) == "4 unknown"


def test_i_plus_one_first_waits_for_a_one_kanji_list_word_only_where_it_stands_on_its_own(tmp_path):
    """"i+1 first" reads the card's sentence as the list does: 年 on the list after 撒く makes 撒く wait for it where
    年 stands on its own, never in 三年 (a count); スバル is no list word and blocks nothing."""
    _sentence_list(tmp_path, [("撒く", 100, []), ("年", 90, [])])
    _results(tmp_path)
    _known(tmp_path, ["餌", "明ける"])
    with _patched(_mined_sentences([("撒く", "年が明けて餌を<b>撒い</b>た。")])):
        _writes, stats = reposition.dry_run(_ready())
    assert _order_of(stats) == [("撒く", "waits for 年 · list #1")]
    with _patched(_mined_sentences([("撒く", "スバルは三年前に餌を<b>撒い</b>た。")])):
        _writes, stats = reposition.dry_run(_ready())
    assert _order_of(stats) == [("撒く", "list #1")]


def test_i_plus_one_first_waits_for_the_listed_word_inside_a_rare_compound(tmp_path, compounds):
    """撒く's sentence holds 自動車学校, too rare for the list: it counts as 自動車 + 学校, and 自動車 comes later on
    the list with no card of its own — so 撒く waits for it (as one word, 自動車学校, nothing on the list would ever
    teach it). With 自動 known, 自動車 is read through it and 撒く keeps its place."""
    _sentence_list(tmp_path, [("撒く", 100, []), ("自動車", 90, [])])
    _results(tmp_path, library={"自動車学校|ジドウシャガッコウ": _map_entry(1)}, floor=3)
    _known(tmp_path, ["学校"])
    with _patched(_mined_sentences([("撒く", "自動車学校で餌を<b>撒い</b>た。")])):
        _writes, stats = reposition.dry_run(_ready())
    assert _order_of(stats) == [("撒く", "waits for 自動車 · list #1")]

    _known(tmp_path, ["学校", "自動"])
    with _patched(_mined_sentences([("撒く", "自動車学校で餌を<b>撒い</b>た。")])):
        _writes, stats = reposition.dry_run(_ready())
    assert _order_of(stats) == [("撒く", "list #1")]


def test_a_phrase_card_goes_on_the_lists_row_for_its_phrase(tmp_path):
    """With set phrases on the list (Settings' "Idioms and set phrases on your list", on by default) the list has rows
    for phrases, keyed by their words' lemmas joined: a phrase card read alone as those words goes on that row with
    the list's words — "list #N" — however either is spelled (興味をもつ on the row 興味を持つ). Off, the list has no
    such row: the card goes by its sentence."""
    _results(tmp_path, priority=[("冒険", "冒険", 50, 5), ("興味を持つ", "興味を持つ", 20, 2)],
             library={"冒険|ボウケン": [5, 5, 0, 0, 1, 50, "冒険"]}, floor=2)
    cards, notes, _ = _collection(["須藤", "興味をもつ", "冒険"])
    fake = FakeCollection(cards, notes)

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    order = stats["order"]
    assert [row.word for row in order][:2] == ["冒険", "興味をもつ"]
    assert order[1].why == "list #2" and stats["tiers"]["list"] == 2

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(logic={"phrase_rows": False}))
    [card] = [row for row in stats["order"] if row.word == "興味をもつ"]
    assert card.tier in ("i+1", "multi", "rest") and stats["tiers"]["list"] == 1


def test_a_phrase_card_waiting_for_a_new_word_is_no_i_plus_one_card(tmp_path):
    """本題に入る waits for 本題 while 本題 is new (the list's own rule): its sentence holds no other new word, but the
    phrase and 本題 are two new things — "1 unknown", never i+1. Once 本題 is known it is i+1; with the switch off it
    is i+1 as before."""
    _results(tmp_path, priority=[("無関係", "無関係", 1, 1)], library={"無関係|ムカンケイ": [1, 1, 0, 0, 1, 10, "無関係"]})
    _known(tmp_path, ["入る"])
    fake = _mined([("本題に入る", "では<b>本題に入ろう</b>。", 5000, "")])

    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert stats["order"][0].why == "1 unknown"
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings(logic={"phrase_rows": False}))
    assert stats["order"][0].why == "i+1"
    _known(tmp_path, ["入る", "本題"])
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings())
    assert stats["order"][0].why == "i+1"


@pytest.mark.parametrize("failure", ["refused-in-batch", "whole-request"])
def test_a_failed_sibling_card_request_gives_no_sibling_warning(backlog, failure):
    """A failed sibling search is not evidence that a deck holds second cards: the sibling warning
    is for a deck where the search answered and found some. When the `-card:1` search fails, either
    as an error reply inside the batched `multi` or as the whole request failing, the preflight must
    stay silent about siblings, not warn on a guess."""
    # why: `_serve_order` warns only when the search found a card; an error reply (or a failed
    # request, caught as no replies) means "unknown", and an unknown count must not be reported as
    # "some notes have more than one card".
    backlog.serve = {"newGatherPriority": 0, "newSortOrder": 0}
    some = next(iter(backlog.cards.values()))                  # a second card: a search that answers finds it
    backlog.cards[some["cardId"] + 1_000_000] = dict(some, cardId=some["cardId"] + 1_000_000, ord=1)
    with _patched(backlog):
        assert reposition.preflight(_settings())["warnings"], "the control: an answered search warns"

    class SiblingSearchFails(FakeCollection):
        def __call__(self, request, timeout=None):
            if failure == "whole-request" and b"-card:1" in request.data:
                self.requests.append(json.loads(request.data.decode("utf-8")))
                raise urllib.error.URLError("[WinError 10054] connection forcibly closed")
            return super().__call__(request, timeout)

        def _dispatch(self, action, params):
            if failure == "refused-in-batch" and action == "findCards" and "-card:1" in params.get("query", ""):
                return AnkiRefusal("sibling search refused")
            return super()._dispatch(action, params)

    refused = SiblingSearchFails(list(backlog.cards.values()), list(backlog.notes.values()))
    refused.serve = backlog.serve
    with _patched(refused):
        checks = reposition.preflight(_settings())
    # why: no sibling warning of any wording may appear on an unknown count; checking the whole list
    # keeps the test from passing vacuously when the warning text is reworded.
    assert checks["warnings"] == [], checks["warnings"]


# why: with no tag to put back (none, or an empty one) there is no later-back plan, even when the card returns
# from a suspension; a plan keyed on a None tag would reach Anki as a tag named "None".
def test_a_returning_card_with_no_later_tag_makes_no_later_back_plan(tmp_path):
    cards = [{"card_id": FIRST_CARD, "note": FIRST_NOTE, "parked": True}]
    assert reposition._later_back(cards, [FIRST_CARD], None) == {}
    assert reposition._later_back(cards, [FIRST_CARD], "") == {}
    assert reposition._later_back(cards, [FIRST_CARD], "Surasura::later") == {"Surasura::later": [FIRST_NOTE]}
