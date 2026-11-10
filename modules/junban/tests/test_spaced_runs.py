# SPDX-License-Identifier: GPL-3.0-or-later
"""Junban's runs with the fast re-plan's preview on (E1.1 03 §3, §5; E2.1.2–3), on the fake collection.

`spaced.py` decides the numbers; this file proves the runs that write them, against a collection that
keeps real state (`test_reposition.FakeCollection`, real Japanese words ranked by a real export):

  * **Off is 2.5, request for request** — `test_request_logs.py` holds the recorded logs; here, that no
    file of the preview's is written either.
  * **Tomorrow first** (05 §5): after request 1, Anki's first N new cards by position are the plan's
    first N — N = 1, the deck's New cards/day, the whole backlog.
  * **The re-check**: a card studied, or moved in Anki, between the read and the write is left for the
    next job, never written.
  * **Restore and today's baseline** (03 §5, ✅ G1.5-1): a manual run keeps 2.5's snapshot and refusal; the
    automatic re-orders keep today's baseline, once a day, never a reason to refuse; Restore puts back
    the newer, cards still new only.
  * **The warm card map** (03 §3.2): a later job asks only what changed.
  * **Never a position ≥ 1,000,000** — checked on every write any test here makes.
"""
import json
import os
import time

import pytest

from modules.junban import plan as junban_plan
from modules.junban import reposition, spaced, undo
from modules.junban.tests.test_reposition import (UNRANKED, AnkiRefusal, FakeCollection,  # noqa: F401
                                                  _collection, _patched, _settings, priority_rows,
                                                  ranked_words, write_priority_csv)


class ModCollection(FakeCollection):
    """The fake collection, plus what the preview reads: `getActiveProfile`, `cardsModTime`,
    `notesModTime` — mod times that move when a card is written, as Anki's do (whole seconds)."""

    def __init__(self, *args, profile="DevTest", note_mod_time=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.note_mod_time = note_mod_time
        for card in self.cards.values():
            card.setdefault("mod", 1_700_000_000)
        self.note_mods = {note_id: 1_700_000_000 for note_id in self.notes}
        self.before_cards_info = None           # called with the ids, before each cardsInfo answers
        self.before_mod_times = None            # called with the ids, before each cardsModTime answers
        self.after_first_write = None           # the cards' dues, once the first write request landed
        self.write_requests = []                # [(card_id, due)] per write request, in order
        self.after_writes = []                  # the cards' dues after each write request
        self.buried = False                     # `is:new -is:suspended` finds buried new cards too, as Anki's does
        self.mod_time_calls = 0

    def _find(self, query):
        found = super()._find(query)
        if self.buried:
            deck = query.split('"')[1] if '"' in query else ""
            found = sorted(set(found) | {card["cardId"] for card in self.cards.values()
                                         if card["deckName"] == deck and card["type"] == 0
                                         and card["queue"] in (-2, -3)})
        return found

    def _dispatch(self, action, params):
        if action == "getActiveProfile":
            return self.profile
        if action == "cardsModTime":
            if self.before_mod_times is not None:
                self.before_mod_times(list(params.get("cards", [])))
            return [{"cardId": card_id, "mod": self.cards[card_id]["mod"]} if card_id in self.cards else {}
                    for card_id in params.get("cards", [])]
        if action == "notesModTime":
            if not self.note_mod_time:
                return AnkiRefusal("unsupported action")
            return [{"noteId": note_id, "mod": self.note_mods[note_id]} for note_id in params.get("notes", [])
                    if note_id in self.notes]
        if action == "cardsInfo" and self.before_cards_info is not None:
            self.before_cards_info(list(params.get("cards", [])))
        if action == "modelFieldNames":
            for note in self.notes.values():
                if note.get("modelName") == params.get("modelName"):
                    fields = note.get("fields") or {}
                    return sorted(fields, key=lambda name: (fields[name].get("order", 0), name))
            return AnkiRefusal(f"model was not found: {params.get('modelName')}")
        return super()._dispatch(action, params)

    def _multi(self, actions):
        replies = super()._multi(actions)
        wrote = False
        for entry in actions:
            params = entry.get("params") or {}
            if entry.get("action") == "setSpecificValueOfCard" and params.get("keys") == ["due"]:
                value = params["newValues"][0]
                assert 1 <= value <= spaced.CEILING, f"wrote position {value}"     # never the fold
                self.cards[params["card"]]["mod"] = int(time.time())
                wrote = True
        if wrote:
            self.write_requests.append([(entry["params"]["card"], entry["params"]["newValues"][0])
                                        for entry in actions if entry.get("action") == "setSpecificValueOfCard"])
            self.after_writes.append({card_id: card["due"] for card_id, card in self.cards.items()})
        if wrote and self.after_first_write is None:
            self.after_first_write = {card_id: card["due"] for card_id, card in self.cards.items()}
        return replies

    def queue(self):
        """The deck's new cards as Anki would show them: by position (ties by id)."""
        new = [card for card in self.cards.values() if card["type"] == 0 and card["queue"] == 0]
        return [card["cardId"] for card in sorted(new, key=lambda card: (card["due"], card["cardId"]))]


@pytest.fixture
def deck(ranked_words, write_priority_csv):
    """30 cards: 24 ranked words in the reverse of the list's order, then 6 the list lacks — dense, as
    2.5 leaves a deck (`test_reposition.backlog`'s shape)."""
    write_priority_csv()
    words = ranked_words[:24] + UNRANKED
    dues = list(range(2800 + len(words) - 1, 2799, -1))
    cards, notes, _ = _collection(words, dues=dues)
    return ModCollection(cards, notes)


def _key(row):
    """The word a card carries for a list row — `test_reposition.ranked_words`' own rule."""
    word, orth = row
    key = orth or word
    return word if len(key) == 1 and key != word else key


def _move_on_the_list(write_priority_csv, priority_rows, ranked, picked, to_back=False):
    """A move in the Content Manager, as the list sees it: the `picked` words' rows to the top (or to
    the back, `to_back`)."""
    moved = [row for row in priority_rows if _key(row) in set(picked)]
    rest = [row for row in priority_rows if _key(row) not in set(picked)]
    write_priority_csv(rest + moved if to_back else moved + rest)


def _planned(report):
    return [row.card_id for row in report["stats"]["order"]]


def _subactions(request):
    """A request's actions: a `multi`'s sub-actions, else the one."""
    if request["action"] == "multi":
        return [entry["action"] for entry in request["params"]["actions"]]
    return [request["action"]]


def _reads(deck):
    """{action: its params} over every request and `multi` sub-action the fake answered (the last of each)."""
    out = {}
    for request in deck.requests:
        for entry in (request["params"]["actions"] if request["action"] == "multi" else [request]):
            out[entry["action"]] = entry.get("params") or {}
    return out


def _files(language="ja"):
    from app.path_utils import get_user_files_path
    folder = get_user_files_path(language)
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


# --------------------------------------------------------------------------- #
# Off: nothing of the preview's
# --------------------------------------------------------------------------- #
def test_off_writes_no_baseline_no_ladder_and_reads_nothing_new(deck):
    with _patched(deck):
        report = reposition.run(_settings())
    assert report["ok"] and report["written"]
    assert "numbering" not in report["stats"] and "number" not in report["stats"]
    assert "junban_replan_baseline.json" not in _files() and "junban_ladder.json" not in _files()
    assert not {"cardsModTime", "notesModTime"} & set(deck.action_names)
    assert deck.action_names.count("getActiveProfile") == 1     # FT (K1, on purpose): the run's one profile read
    # 2.5's dense block from min(due), in the list's order.
    assert [deck.cards[card_id]["due"] for card_id in _planned(report)] == list(range(2800, 2830))


# --------------------------------------------------------------------------- #
# The first spaced run, the delta, request 1
# --------------------------------------------------------------------------- #
def test_the_first_spaced_run_spaces_every_card_once_and_a_second_writes_nothing(deck):
    with _patched(deck):
        first = reposition.run(_settings(), job=spaced.Job())
    assert first["ok"] and first["numbering"]["kind"] == spaced.FULL
    assert first["message"].startswith("Spaced your new cards out once")     # 03 §2: announced
    order = _planned(first)
    assert len(first["written"]) == 30 and deck.queue() == order
    dues = [deck.cards[card_id]["due"] for card_id in order]
    assert dues == spaced.layout(30, 2800) and dues[-1] <= spaced.CEILING
    assert undo.ladder_floor("ja", ["TheBank"]) == 2800
    # 2.5's snapshot, as ever, for a run from the window: every movable card at its old position.
    saved = undo.load("ja")
    assert saved["complete"] is True and len(saved["cards"]) == 30 and min(saved["cards"].values()) == 2800

    deck.requests.clear()
    with _patched(deck):
        second = reposition.run(_settings(), job=spaced.Job())
    assert second["ok"] and not second["written"]
    assert "multi" not in deck.action_names        # no write request at all


@pytest.mark.parametrize("front", [1, None, 30])
def test_after_request_1_ankis_first_n_new_cards_are_the_plans_first_n(deck, ranked_words, write_priority_csv,
                                                                       priority_rows, front):
    # None: the deck's New cards/day (the fake says 20); 30: the whole backlog.
    with _patched(deck):
        reposition.run(_settings(), job=spaced.Job())
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[18:24])  # a file's words up
    deck.write_requests.clear()
    deck.after_writes.clear()
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job(front=front))
    assert report["ok"] and report["written"]
    n = 20 if front is None else front
    order = _planned(report)
    rows = report["stats"]["order"]
    group = spaced.front_group([(row.card_id, row.due) for row in rows], [row.position for row in rows], n)
    assert sorted(deck.write_requests[0]) == sorted(group)       # N decides what goes first
    assert len(group) == (1 if n == 1 else 6)                    # the six moved words: one of them at N = 1
    after = deck.after_writes[0]
    first_n = sorted((card_id for card_id in after if card_id in set(order)),
                     key=lambda card_id: (after[card_id], card_id))[:n]
    assert first_n == order[:n]
    assert deck.queue() == order                    # and once every request landed, the whole plan


def test_a_typical_move_writes_the_cards_it_moved_not_the_backlog(ranked_words, write_priority_csv, priority_rows):
    # 400 cards on the ladder; one file's six words pulled to the top of the list.
    write_priority_csv()
    words = ranked_words[:400] if len(ranked_words) >= 400 else ranked_words
    cards, notes, _ = _collection(words)
    fake = ModCollection(cards, notes)
    with _patched(fake):
        reposition.run(_settings(), job=spaced.Job())
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, words[-6:])
    with _patched(fake):
        report = reposition.run(_settings(), job=spaced.Job())
    assert report["ok"] and fake.queue() == _planned(report)
    assert len(report["written"]) <= 12             # dense numbering rewrites every card between
    with _patched(fake):
        dense = reposition.dry_run(_settings())     # what 2.5 would write for the same move
    assert dense[1]["to_write"] > 5 * len(report["written"])


def test_the_preview_numbers_as_the_run_writes_and_a_click_is_replanned_the_same_way(deck):
    with _patched(deck):
        writes, stats = reposition.dry_run(_settings(), job=spaced.Job())
    assert stats["numbering"]["kind"] == spaced.FULL and not deck.writes
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job())
    assert [(row.card_id, row.position) for row in stats["order"]] == \
        [(card_id, deck.cards[card_id]["due"]) for card_id in _planned(report)]
    # The panel's click (WP-O) re-plans through `plan.replan` with the run's own numbering.
    dropped = {stats["order"][0].card_id}
    _writes, replanned = junban_plan.replan(stats["order"], dropped, number=stats["number"])
    assert replanned["numbering"]["kind"] == spaced.FULL
    assert [row.position for row in replanned["order"]] == spaced.layout(30, 2800)


# --------------------------------------------------------------------------- #
# The re-check before each request (03 §3.5)
# --------------------------------------------------------------------------- #
def test_a_card_studied_between_the_read_and_the_write_is_left_for_the_next_job(deck):
    calls = []

    def study_one(ids):
        calls.append(ids)
        if len(calls) == 2:                         # the first re-check: the user just studied a card
            card = deck.cards[ids[0]]
            card["type"], card["queue"], card["due"] = 2, 2, 20000
    deck.before_cards_info = study_one
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job())
    studied = calls[1][0]
    assert studied in report["left"] and studied not in report["written"]
    assert all(card_id != studied for card_id, _due in deck.writes)
    assert deck.cards[studied]["due"] == 20000      # a review card's date, untouched (I1)
    assert "wait for the next re-order" in report["message"]


def test_a_card_moved_in_anki_meanwhile_is_left_not_overwritten(deck):
    calls = []

    def move_one(ids):
        calls.append(ids)
        if len(calls) == 2:
            deck.cards[ids[-1]]["due"] = 1             # the user repositioned it by hand
    deck.before_cards_info = move_one
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job())
    assert calls[1][-1] in report["left"] and deck.cards[calls[1][-1]]["due"] == 1


# --------------------------------------------------------------------------- #
# Today's baseline and Restore (03 §5)
# --------------------------------------------------------------------------- #
def test_the_automatic_reorders_keep_todays_baseline_once_and_never_the_windows_snapshot(deck, ranked_words,
                                                                                     write_priority_csv,
                                                                                     priority_rows):
    before = {card_id: card["due"] for card_id, card in deck.cards.items()}
    with _patched(deck):
        report = reposition.run(_settings(junban_tag="Surasura"), refresh=False, job=spaced.Job(automatic=True))
    assert report["ok"] and report["written"]
    assert undo.load("ja") is None                  # the window's way back is not taken over
    baseline = undo.load("ja", "baseline")
    assert baseline["day"] == undo.anki_day() and baseline["complete"] is True
    assert {int(k): v for k, v in baseline["cards"].items()} == before
    assert not deck.tag_calls and not deck.note_writes        # positions only (04 §1)
    assert report["snapshot"] == undo.snapshot_path("ja", "baseline")

    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[10:14])
    with _patched(deck):
        later = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert later["ok"] and later["written"]
    assert undo.load("ja", "baseline") == baseline  # the day's first order, kept as it was

    # Restore puts back the order before today's first automatic re-order, and ends the baseline.
    with _patched(deck):
        restored = reposition.restore(_settings())
    assert restored["ok"]
    assert {card_id: card["due"] for card_id, card in deck.cards.items()} == before
    # Ended (the next automatic write starts a new one), and still what a second Restore offers: the same
    # order again, as 2.5's second press does — never an older manual run's (review #3).
    assert undo.load("ja", "baseline")["ended_at"] and undo.restorable("ja") == undo.load("ja", "baseline")
    # The next automatic write starts a new baseline.
    with _patched(deck):
        reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert not undo.load("ja", "baseline").get("ended_at")


def test_a_manual_run_ends_todays_baseline_and_restore_puts_back_the_newer(deck, ranked_words,
                                                                       write_priority_csv, priority_rows):
    with _patched(deck):
        reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    after_auto = {card_id: card["due"] for card_id, card in deck.cards.items()}
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[5:9])
    with _patched(deck):
        manual = reposition.run(_settings(), job=spaced.Job())
    assert manual["ok"] and undo.load("ja", "baseline")["ended_at"]
    assert undo.restorable("ja") == undo.load("ja")
    with _patched(deck):
        restored = reposition.restore(_settings())
    assert restored["ok"]
    assert {card_id: card["due"] for card_id, card in deck.cards.items()} == after_auto


def test_restore_puts_back_still_new_cards_only(deck):
    with _patched(deck):
        reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    studied = next(iter(deck.cards))
    deck.cards[studied].update(type=2, queue=2, due=30)
    with _patched(deck):
        restored = reposition.restore(_settings())
    assert restored["ok"] and deck.cards[studied]["due"] == 30
    assert "moved on" in restored["message"]


def test_an_automatic_write_that_dies_midway_is_simply_run_again(deck):
    deck.fail_write_chunk = 1                       # Anki closes during the first write request
    with _patched(deck):
        first = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert not first["ok"] and first["failures"]
    baseline = undo.load("ja", "baseline")
    deck.fail_write_chunk = None
    with _patched(deck):
        again = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert again["ok"] and again["written"]         # never refused for its own unfinished write
    assert undo.load("ja", "baseline") == baseline  # and today's order is still the one before both


def test_a_manual_run_keeps_25s_snapshot_and_refusal_with_the_preview_on(deck):
    deck.fail_write_chunk = 1
    with _patched(deck):
        first = reposition.run(_settings(), job=spaced.Job())
    assert not first["ok"] and undo.load("ja")["complete"] is False
    deck.fail_write_chunk = None
    for job in (spaced.Job(), spaced.Job(automatic=True), None):
        with _patched(deck):
            refused = reposition.run(_settings(), refresh=False, job=job)
        assert not refused["ok"] and "did not finish" in refused["problems"][0]
    assert undo.restorable("ja") == undo.load("ja")


def test_an_item_moved_down_on_purpose_gets_no_special_treatment(deck, ranked_words, write_priority_csv,
                                                                 priority_rows):
    # F10, ✅ G1.5-4: every card follows the new order — the words a move sent down go where the list
    # now puts them, nothing kept in place.
    with _patched(deck):
        reposition.run(_settings(), job=spaced.Job())
    down = ranked_words[:4]
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, down, to_back=True)
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job())
    assert report["ok"] and deck.queue() == _planned(report)
    words = {card_id: report["stats"]["order"][i].word for i, card_id in enumerate(_planned(report))}
    ranked_cards = [card_id for card_id in deck.queue() if words[card_id] in set(ranked_words[:24])]
    assert [words[card_id] for card_id in ranked_cards[-4:]] == down


# --------------------------------------------------------------------------- #
# The ladder's bottom (E2.1-1) and the 1,000,000 fold
# --------------------------------------------------------------------------- #
def test_the_ladders_bottom_is_kept_after_the_front_is_studied(deck, ranked_words, write_priority_csv,
                                                              priority_rows):
    with _patched(deck):
        first = reposition.run(_settings(), job=spaced.Job())
    for card_id in _planned(first)[:5]:            # five days' worth of the front, studied
        deck.cards[card_id].update(type=2, queue=2, due=40)
    ranked = [row for row in first["stats"]["order"] if row.rank is not None]
    last = ranked[-1]                               # the list's last word on the deck, pulled to the top
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, [last.word])
    with _patched(deck):
        moved = reposition.run(_settings(), job=spaced.Job())
    assert moved["ok"] and moved["numbering"]["base"] == 2800
    assert moved["written"] == [last.card_id]       # into the room the studied cards left: one write
    still = [card_id for card_id in _planned(first)[5:] if card_id != last.card_id]
    assert 2800 <= deck.cards[last.card_id]["due"] < min(deck.cards[c]["due"] for c in still)


def test_cards_anki_numbered_past_the_ceiling_are_brought_under_it(deck):
    # After a Check Database Anki's counter sits past the ladder's top: newly mined cards land at
    # 1,000,000 and above (kept by Anki up to 1,999,999). The next re-order places them on the ladder.
    with _patched(deck):
        reposition.run(_settings(), job=spaced.Job())
    for offset, card_id in enumerate(list(deck.cards)[-3:]):
        deck.cards[card_id]["due"] = 1_000_000 + offset
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job())
    assert report["ok"] and max(card["due"] for card in deck.cards.values()) <= spaced.CEILING


# --------------------------------------------------------------------------- #
# The warm card map (03 §3.2) and the engine's rows (02 §4)
# --------------------------------------------------------------------------- #
def test_a_warm_card_map_asks_only_what_changed(deck):
    card_map = reposition.CardMap()
    with _patched(deck):
        cold = reposition._gather(reposition.URL if hasattr(reposition, "URL") else "http://127.0.0.1:8765",
                                  ["TheBank"], {}, "ja", card_map=card_map)
        plain = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja")
    assert cold == plain and card_map.fresh == 1

    deck.requests.clear()
    with _patched(deck):
        warm = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    assert warm == plain
    # E3.1-B2: two round trips — the profile, the ids and the note types' fields; then both kinds of mod time.
    assert deck.action_names == ["multi", "multi"]
    assert _subactions(deck.requests[0]) == ["getActiveProfile", "findCards", "modelFieldNames"]
    assert _subactions(deck.requests[1]) == ["cardsModTime", "notesModTime"]

    # A card written since, and a note whose word was fixed: only those are read again — in one request.
    card_id = next(iter(deck.cards))
    deck.cards[card_id].update(due=4000, mod=int(time.time()))
    note_id = deck.cards[card_id]["note"]
    deck.notes[note_id]["fields"]["Expression"]["value"] = "図書館"
    deck.note_mods[note_id] = int(time.time())
    deck.requests.clear()
    with _patched(deck):
        cards, _detail = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    assert len(deck.requests) == 3 and _subactions(deck.requests[2]) == ["cardsInfo", "notesInfo"]
    reads = _reads(deck)
    assert reads["cardsInfo"]["cards"] == [card_id] and reads["notesInfo"]["notes"] == [note_id]
    mine = next(card for card in cards if card["card_id"] == card_id)
    assert mine["due"] == 4000 and mine["word"] == "図書館"

    # A mod time that moved but reads as older than the last read (Anki's clock set back) is a change too.
    other = list(deck.cards)[5]
    other_note = deck.cards[other]["note"]
    deck.notes[other_note]["fields"]["Expression"]["value"] = "美術館"
    deck.note_mods[other_note] = 1_700_000_100
    deck.cards[other].update(due=4100, mod=1_700_000_100)
    deck.requests.clear()
    with _patched(deck):
        cards, _detail = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    reads = _reads(deck)
    # (the card written a moment ago may be read once more: its mod time is within a second of the last read)
    assert other in reads["cardsInfo"]["cards"] and len(reads["cardsInfo"]["cards"]) <= 2
    assert other_note in reads["notesInfo"]["notes"] and len(reads["notesInfo"]["notes"]) <= 2
    mine = next(card for card in cards if card["card_id"] == other)
    assert mine["due"] == 4100 and mine["word"] == "美術館"


def test_another_profile_or_no_notes_mod_time_reads_afresh(deck):
    card_map = reposition.CardMap()
    with _patched(deck):
        reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    deck.profile = "Sonic"
    with _patched(deck):
        reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    assert card_map.fresh == 2
    old = ModCollection(list(deck.cards.values()), list(deck.notes.values()), note_mod_time=False)
    card_map = reposition.CardMap()
    for _ in range(2):
        with _patched(old):
            cards, _ = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    assert card_map.fresh == 2 and len(cards) == 30   # every read gathered afresh, nothing lost


def test_a_job_with_a_warm_map_writes_what_a_fresh_run_writes(deck, ranked_words, write_priority_csv,
                                                             priority_rows):
    card_map = reposition.CardMap()
    with _patched(deck):
        reposition.run(_settings(), job=spaced.Job(cards=card_map))
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[12:16])
    with _patched(deck):
        fresh = reposition.dry_run(_settings(), job=spaced.Job())
        report = reposition.run(_settings(), job=spaced.Job(cards=card_map))
    assert [(row.card_id, row.position) for row in fresh[1]["order"]] == \
        [(row.card_id, row.position) for row in report["stats"]["order"]]


def test_the_engines_rows_rank_the_cards_as_a_csv_of_that_order_would(deck, ranked_words, write_priority_csv,
                                                                       priority_rows):
    import csv
    # The engine's rows for an order the CSV doesn't hold yet (a move just made): the run follows the
    # rows, exactly as it would follow a Generate's CSV of that order.
    picked = ranked_words[16:22]
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, picked)
    with open(reposition.order_csv_path(_settings()), "r", encoding="utf-8-sig", newline="") as handle:
        moved_rows = list(csv.DictReader(handle))
    with _patched(deck):
        by_moved_csv = reposition.dry_run(_settings(), job=spaced.Job())
    write_priority_csv()                            # the last Generate's CSV: the order before the move
    with _patched(deck):
        by_rows = reposition.dry_run(_settings(), job=spaced.Job(rows=moved_rows))
        by_old_csv = reposition.dry_run(_settings(), job=spaced.Job())
    assert [row.card_id for row in by_rows[1]["order"]] == [row.card_id for row in by_moved_csv[1]["order"]]
    assert [row.card_id for row in by_rows[1]["order"]] != [row.card_id for row in by_old_csv[1]["order"]]
    assert by_rows[1]["matched"] == 24


# --------------------------------------------------------------------------- #
# The automatic step's entry point
# --------------------------------------------------------------------------- #
def test_the_automatic_step_with_a_job_numbers_spaced_and_keeps_todays_baseline(deck):
    # 2.x-dev: positions only, whatever junban_auto_actions says, and today's baseline; 3.0 (W3.5 row 7, Haya's G2b):
    # the job `auto.reorder` hands on carries the actions it decided — here the Surasura tag on the notes that moved —
    # and an action to write keeps the window's snapshot instead of the baseline. With the actions off, the baseline.
    from modules.junban import auto
    with _patched(deck):
        done = auto.reorder(_settings(junban_auto_reorder=True, junban_auto_actions=True, junban_tag="Surasura"),
                            list_current=True, job=spaced.Job())
    assert done["outcome"] == "ran" and done["report"]["numbering"]["kind"] == spaced.FULL
    assert {tag for _action, _notes, tag in deck.tag_calls} == {"Surasura"}
    assert undo.load("ja")["tags"] and undo.load("ja", "baseline") is None
    with _patched(deck):
        deck.cards[min(deck.cards)]["due"], deck.cards[max(deck.cards)]["due"] = \
            deck.cards[max(deck.cards)]["due"], deck.cards[min(deck.cards)]["due"]
        again = auto.reorder(_settings(junban_auto_reorder=True, junban_tag="Surasura"), list_current=True,
                             job=spaced.Job())
    assert again["outcome"] == "ran" and again["report"]["written"]
    assert undo.load("ja", "baseline") and len(deck.tag_calls) == 1, "actions off: positions only, the baseline"


@pytest.mark.parametrize("over", [
    {"junban_replan_preview": False},                                  # 2.x's box off
    {"junban_replan_preview": False, "logic": {"automation": False}},  # D29 off too
    {"junban_replan_preview": True, "junban_replan_language": "zh"},   # the box on for the other language
], ids=["box-off", "d29-off", "other-language"])
def test_on_3_0_the_automatic_step_numbers_spaced_with_no_job_whatever_the_switches(deck, over):
    """2.x-dev numbers dense here (no job, `is_on` False: 2.5's run); 3.0 (E1.1 04 §5, Haya's G2b): spaced numbering
    always, regardless of D29, the language or the preview's box — one numbering for every Junban writer. Still an
    automatic run, and the actions `auto.reorder` decided ride its job (W3.5 row 7): the Surasura tag on the notes
    that moved, under the window's snapshot instead of today's baseline."""
    from modules.junban import auto
    with _patched(deck):
        done = auto.reorder(_settings(junban_auto_reorder=True, junban_auto_actions=True, junban_tag="Surasura",
                                      **over), list_current=True)
    assert done["outcome"] == "ran", done
    assert done["report"]["numbering"]["kind"] == spaced.FULL
    assert undo.load("ja")["tags"] and undo.load("ja", "baseline") is None
    assert {tag for _action, _notes, tag in deck.tag_calls} == {"Surasura"}


def test_on_3_0_job_none_said_outright_numbers_spaced_too(deck):
    """2.x-dev keeps `job=None` as 2.5's dense block with the preview off
    (test_job_none_said_outright_is_still_2_5s_dense_block_for_the_command_line); 3.0 (W3.5 row 7, Michi's answer:
    `verbs.numbering_job` is spaced always): None is no dense run any more — an automatic spaced job, today's baseline,
    so no caller can ask 順 for 2.5's numbering behind the others' backs."""
    from modules.junban import auto
    with _patched(deck):
        done = auto.reorder(_settings(junban_auto_reorder=True), list_current=True, job=None)
    assert done["outcome"] == "ran", done
    assert done["report"]["numbering"]["kind"] == spaced.FULL
    assert "junban_replan_baseline.json" in _files()


# --------------------------------------------------------------------------- #
# The review's gaps (reviews/E2.1-adversary.md)
# --------------------------------------------------------------------------- #
def test_a_card_modified_in_the_second_of_the_read_is_read_again(deck):
    # #6 / M8: mod times are whole seconds. A card changed in the very second the map read it keeps the
    # mod time the map saw; only the "within a second of the last read" rule reads it again.
    card_id = next(iter(deck.cards))
    deck.cards[card_id]["mod"] = int(time.time())
    card_map = reposition.CardMap()
    with _patched(deck):
        reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    deck.cards[card_id]["due"] = 4321               # changed again, same second, same mod time
    with _patched(deck):
        cards, _ = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    assert next(card for card in cards if card["card_id"] == card_id)["due"] == 4321


def test_todays_baseline_is_per_deck_and_starts_again_the_next_day(deck):
    # #2, #6 / M24: a baseline for another deck, or another day, gives way to a new one.
    pairs = [(1789712080000, 2800), (1789712080001, 2801)]
    path, first = undo.save_baseline(pairs, ["TheBank"], day="2026-10-06")
    _path, again = undo.save_baseline([(1789712080000, 9)], ["TheBank"], day="2026-10-06")
    assert first and not again and undo.load("ja", "baseline")["cards"]["1789712080000"] == 2800
    _path, other = undo.save_baseline([(1789712090000, 50)], ["Kanji"], day="2026-10-06")
    assert other and undo.load("ja", "baseline")["scope"] == ["Kanji"]
    assert undo.restorable("ja", ["Kanji"])["scope"] == ["Kanji"]
    _path, tomorrow = undo.save_baseline([(1789712090000, 60)], ["Kanji"], day="2026-10-07")
    assert tomorrow and undo.load("ja", "baseline")["day"] == "2026-10-07"


def test_ankis_day_turns_at_four_in_the_morning():
    # #6 / M11: the hours after midnight are still yesterday, as in Anki.
    import datetime
    before = datetime.datetime(2026, 10, 7, 3, 59).timestamp()
    after = datetime.datetime(2026, 10, 7, 4, 0).timestamp()
    assert undo.anki_day(before) == "2026-10-06" and undo.anki_day(after) == "2026-10-07"


def test_an_unfinished_manual_run_outranks_a_newer_baseline():
    # #6 / M19: the unfinished manual snapshot is the only way back from that run.
    undo.save([(1789712080000, 2800)], ["TheBank"])                     # saved incomplete
    time.sleep(1.1)
    undo.save_baseline([(1789712080000, 5000)], ["TheBank"], day="2026-10-06")
    assert undo.restorable("ja")["complete"] is False
    undo.mark_complete("ja")
    assert undo.is_baseline(undo.restorable("ja"))                      # finished: the newer one


def test_a_buried_card_is_never_written_and_the_plans_first_n_still_come_first(deck):
    # #11: `is:new -is:suspended` finds buried siblings too; the plan skips them (they keep their numbers),
    # so "Anki's first N" is about the cards Anki will show — queue 0 — which the plan orders.
    deck.buried = True
    buried = list(deck.cards)[3]
    deck.cards[buried]["queue"] = -3
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job())
    assert report["ok"] and buried not in report["written"] and deck.cards[buried]["due"] == 2826
    assert report["stats"]["skipped_other"] == 1 and deck.queue() == _planned(report)


def test_a_newly_mined_card_the_list_lacks_goes_behind_the_older_ones_with_the_preview_on(deck):
    # #4: Anki gives a new card its counter, which sits below the whole ladder; "by current position" would
    # put it ahead of every older card the list lacks. Ties go by card id with the preview on, as 2.5's
    # counter put them.
    settings = _settings(junban_unlisted="back")
    with _patched(deck):
        reposition.run(settings, job=spaced.Job())
    cards, notes, _ = _collection(["掃除機"], dues=[2830], start=30)       # mined after: Anki's counter
    deck.cards[cards[0]["cardId"]] = dict(cards[0], mod=int(time.time()))
    deck.notes[notes[0]["noteId"]] = notes[0]
    deck.note_mods[notes[0]["noteId"]] = int(time.time())
    with _patched(deck):
        report = reposition.run(settings, job=spaced.Job())
    unranked = [row.card_id for row in report["stats"]["order"] if row.rank is None]
    assert unranked[-1] == cards[0]["cardId"] and deck.queue()[-1] == cards[0]["cardId"]


def test_an_automatic_job_never_runs_on_all_decks(deck):
    # Rule 6, whoever calls it (a direct E3.1 caller too): one nominated deck only.
    with _patched(deck):
        report = reposition.run(_settings(junban_scope="all"), refresh=False, job=spaced.Job(automatic=True))
    assert not report["ok"] and "one deck only" in report["problems"][0] and not deck.writes


def test_the_warm_up_never_outlives_a_read_that_failed(deck, monkeypatch):
    # #14 (b): Anki dies mid-read; the tables' thread is waited for all the same, so it can't outlive the run
    # (in the suite: its test's temporary folders).
    import threading
    monkeypatch.setattr(reposition, "_WARMING", {})
    monkeypatch.setattr(reposition, "_warm_tables", lambda language, phrase_rows: time.sleep(0.3))
    deck.offline = True
    started = []
    real = threading.Thread.start
    monkeypatch.setattr(threading.Thread, "start", lambda self: (started.append(self), real(self))[1])
    with _patched(deck), pytest.raises(reposition.AnkiError):
        reposition._plan_scope(_settings(), ["TheBank"], "http://127.0.0.1:8765")
    assert started and not started[0].is_alive()


def test_a_warm_refresh_of_5000_cards_costs_surasura_little(ranked_words):
    # #8: 03 §4's ≤ 100 ms for a no-change refresh at 5,000 cards is Anki's answers and Surasura's work
    # together; Surasura's share, on the fake, stays well inside it (measured in As built). The tight budget
    # in a timed run only (SURASURA_STORE_BENCH=1, the machine alone), 3x on a shared one.
    import os
    words = [ranked_words[i % len(ranked_words)] for i in range(5000)]
    cards, notes, _ = _collection(words)
    fake = ModCollection(cards, notes)
    card_map = reposition.CardMap()
    with _patched(fake):
        reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
        time.sleep(1.1)                             # past the same-second window
        reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
        best = 1e9
        for _ in range(3):
            started = time.perf_counter()
            reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
            best = min(best, time.perf_counter() - started)
    budget = 0.1 if os.environ.get("SURASURA_STORE_BENCH") == "1" else 0.3
    assert best < budget, f"a warm no-change refresh took {best * 1000:.0f} ms"


def test_a_renamed_note_type_or_field_reads_afresh_and_so_does_a_refused_cards_mod_time(deck):
    # Reviews #13 and 2 #5: renaming a note type or a field in Anki moves no mod time; the warm map asks
    # the field names of its note types each time (one request) and reads afresh when they changed — never
    # on a timer, which cost a whole cold read inside a job. A refused cardsModTime reads afresh too.
    card_map = reposition.CardMap()
    with _patched(deck):
        reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
        reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
        assert card_map.fresh == 1
        for note in deck.notes.values():             # the field the word is in, renamed
            note["fields"] = {("Word" if name == "Expression" else name): value
                              for name, value in note["fields"].items()}
        cards, detail = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {"Lapis": "Word"}, "ja",
                                           card_map=card_map)
        assert card_map.fresh == 2 and "Word" in detail["field_names"]
        for note in deck.notes.values():             # the note type renamed
            note["modelName"] = "Lapis 2"
        reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    assert card_map.fresh == 3
    answer = deck._dispatch
    deck._dispatch = lambda action, params: (AnkiRefusal("unsupported action") if action == "cardsModTime"
                                             else answer(action, params))
    with _patched(deck):
        cards, _ = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    assert card_map.fresh == 4 and len(cards) == 30


# --------------------------------------------------------------------------- #
# The second pass's gaps (reviews/E2.1-adversary-2.md)
# --------------------------------------------------------------------------- #
def test_restore_prefers_the_asked_decks_snapshot_over_a_newer_one_for_another(deck):
    # 2 #6 / X1: a newer baseline for another deck doesn't hide this deck's own snapshot.
    undo.save([(1789712080000, 2800)], ["TheBank"])
    undo.mark_complete("ja")
    time.sleep(1.1)
    undo.save_baseline([(1789712090000, 50)], ["Kanji"], day="2026-10-06")
    assert undo.restorable("ja", ["TheBank"])["scope"] == ["TheBank"]
    assert undo.restorable("ja")["scope"] == ["Kanji"]                  # by time alone: the newest


def test_the_windows_restore_and_the_restore_itself_ask_the_same_deck(deck, monkeypatch):
    # 2 #2 / #6 X9: the window describes, and Restore restores, the snapshot for the window's deck.
    from modules.junban import gui as junban_gui
    undo.save([(card_id, card["due"]) for card_id, card in deck.cards.items()], ["TheBank"])
    undo.mark_complete("ja")
    time.sleep(1.1)
    undo.save_baseline([(1789712090000, 50)], ["Kanji"], day="2026-10-06")
    asked = {}
    monkeypatch.setattr(junban_gui, "ask", lambda parent, question, details=None, **kw: asked.update(
        details=details) or False)

    class Window:
        busy = False

        def _lang_code(self):
            return "ja"

        def _settings(self):
            return _settings()

        def _clear_messages(self):
            pass

        def _write(self, *args):
            pass
    junban_gui.JunbanGui.on_restore(Window())
    assert asked["details"][0].startswith("30 cards saved from TheBank")
    with _patched(deck):
        restored = reposition.restore(_settings())
    assert restored["ok"] and len(restored["written"]) <= 30 and restored["snapshot"].endswith("junban_undo.json")


def test_restore_refuses_when_a_newer_order_was_saved_while_it_waited(deck):
    # 2 #6 / X3: the window confirmed one order; a writer it waited for saved a newer one — refused.
    import threading
    from app import anki_connect
    undo.save([(card_id, card["due"]) for card_id, card in deck.cards.items()], ["TheBank"])
    undo.mark_complete("ja")
    confirmed = undo.restorable("ja", ["TheBank"])["written_at"]
    holding = threading.Event()

    def other_writer():
        with anki_connect.writer("another writer"):
            holding.set()
            time.sleep(1.1)
            undo.save_baseline([(card_id, 1) for card_id in deck.cards], ["TheBank"], day="2026-10-06")
    thread = threading.Thread(target=other_writer)
    thread.start()
    holding.wait(5)
    with _patched(deck):
        refused = reposition.restore(_settings(), wait=10, confirmed=confirmed)
    thread.join()
    assert not refused["ok"] and refused.get("busy") and not deck.writes


def test_a_restore_of_the_manual_snapshot_ends_the_baseline_too(deck):
    # 2 #6 / X14: any Restore ends the baseline (03 §5), whichever snapshot it put back.
    undo.save_baseline([(card_id, card["due"]) for card_id, card in deck.cards.items()], ["TheBank"],
                       day=undo.anki_day())
    time.sleep(1.1)
    undo.save([(card_id, card["due"]) for card_id, card in deck.cards.items()], ["TheBank"])
    undo.mark_complete("ja")
    with _patched(deck):
        restored = reposition.restore(_settings())
    assert restored["ok"] and undo.load("ja", "baseline")["ended_at"]


def test_the_join_cache_follows_the_word_field_overrides(deck):
    # 2 #6 / X5: the same notes read with other word-field overrides give the words those overrides name.
    card_map = reposition.CardMap()
    url = "http://127.0.0.1:8765"
    with _patched(deck):
        plain, _ = reposition._gather(url, ["TheBank"], {}, "ja", card_map=card_map)
        other, _ = reposition._gather(url, ["TheBank"], {"Lapis": "Sentence"}, "ja", card_map=card_map)
    assert card_map.fresh == 1 and [c["word"] for c in plain] != [c["word"] for c in other]


def test_a_note_modified_in_the_second_of_the_read_is_read_again(deck):
    # 2 #6 / X6: the notes' whole-second rule, as the cards'.
    note_id = next(iter(deck.notes))
    deck.note_mods[note_id] = int(time.time())
    card_map = reposition.CardMap()
    url = "http://127.0.0.1:8765"
    with _patched(deck):
        reposition._gather(url, ["TheBank"], {}, "ja", card_map=card_map)
    deck.notes[note_id]["fields"]["Expression"]["value"] = "図書館"     # same second, same mod time
    with _patched(deck):
        cards, _ = reposition._gather(url, ["TheBank"], {}, "ja", card_map=card_map)
    assert next(card for card in cards if card["note"] == note_id)["word"] == "図書館"


def test_progress_is_said_after_every_request(deck):
    # 2 #6 / X12: 03 §3.6, "progress per request" — the first spaced run, 30 cards in requests of 7.
    ticks = []
    with _patched(deck):
        report = reposition.run(_settings(junban_chunk_size=7), job=spaced.Job(),
                                progress=lambda done, total: ticks.append((done, total)))
    assert report["ok"] and len(deck.write_requests) == len(ticks) == 5
    assert ticks[-1] == (30, 30) and [done for done, _ in ticks] == sorted(done for done, _ in ticks)


def test_an_automatic_run_never_touches_the_windows_snapshot(deck):
    # 2 #11: today's baseline is the automatic re-orders' way back; the window's file is not even rewritten.
    undo.save([(card_id, card["due"]) for card_id, card in deck.cards.items()], ["TheBank"])
    undo.mark_complete("ja")
    path = undo.snapshot_path("ja")
    before = (open(path, "rb").read(), os.stat(path).st_mtime_ns)
    time.sleep(0.05)
    with _patched(deck):
        report = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert report["ok"] and report["written"]
    assert (open(path, "rb").read(), os.stat(path).st_mtime_ns) == before


def test_existing_cards_keep_their_order_and_only_new_ones_go_behind(ranked_words, write_priority_csv):
    # 2 #3: "back" mode with a curated order (a premade deck's: not the order the cards were made) — the
    # preview keeps it, as 2.5 does; a card mined since the last spaced run goes after the others.
    write_priority_csv()
    cards, notes, _ = _collection(UNRANKED, dues=[2805, 2804, 2803, 2802, 2801, 2800])   # curated: reversed ids
    fake = ModCollection(cards, notes)
    settings = _settings(junban_unlisted="back")
    with _patched(fake):
        first = reposition.run(settings, job=spaced.Job())
    curated = [card["cardId"] for card in sorted(cards, key=lambda card: card["due"])]
    assert first["ok"] and fake.queue() == curated
    assert undo.ladder("ja", ["TheBank"])["seen"] == max(curated)
    mined, mined_notes, _ = _collection(["掃除機"], dues=[2806], start=40)
    fake.cards[mined[0]["cardId"]] = dict(mined[0], mod=int(time.time()))
    fake.notes[mined_notes[0]["noteId"]] = mined_notes[0]
    fake.note_mods[mined_notes[0]["noteId"]] = int(time.time())
    with _patched(fake):
        again = reposition.run(settings, job=spaced.Job())
    assert again["ok"] and fake.queue() == curated + [mined[0]["cardId"]]


def test_the_cards_placed_are_recorded_only_when_every_one_landed(deck):
    deck.fail_write_chunk = 1
    with _patched(deck):
        reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert undo.ladder("ja", ["TheBank"])["seen"] is None
    deck.fail_write_chunk = None
    with _patched(deck):
        reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert undo.ladder("ja", ["TheBank"])["seen"] == max(deck.cards)


def test_a_click_in_the_panel_is_re_planned_with_the_previews_numbering(deck):
    # 2 #6 / X10 and 2 #9: the panel's click (WP-O) gives the run's own spaced numbers and its numbering.
    from modules.junban import gui as junban_gui
    with _patched(deck):
        _writes, stats = reposition.dry_run(_settings(), job=spaced.Job())

    class Window:
        _preview_stats = stats
        _ticked = {}
        _deselected = {stats["order"][0].card_id}

        def _changed_ticks(self):
            return {}

        def _settings(self):
            return _settings()

        def _lang_code(self):
            return "ja"
    merged = junban_gui.JunbanGui._with_deselection(Window(), stats)
    assert merged["numbering"]["kind"] == spaced.FULL
    assert [row.position for row in merged["order"]] == spaced.layout(30, 2800)


# --------------------------------------------------------------------------- #
# The third pass's gaps (reviews/E2.1-adversary-3.md)
# --------------------------------------------------------------------------- #
def test_a_new_card_of_a_list_word_goes_after_the_older_card_of_that_word(deck, ranked_words):
    # 3 #2 / E1: matched ties (two cards of one word) — the card mined since the last spaced run goes after
    # the one already placed, though Anki numbered it below the whole ladder.
    with _patched(deck):
        reposition.run(_settings(), job=spaced.Job())
    old = next(card_id for card_id in deck.cards if deck.notes[deck.cards[card_id]["note"]]["fields"]
               ["Expression"]["value"] == ranked_words[0])
    cards, notes, _ = _collection([ranked_words[0]], dues=[2830], start=50)
    deck.cards[cards[0]["cardId"]] = dict(cards[0], mod=int(time.time()))
    deck.notes[notes[0]["noteId"]] = notes[0]
    deck.note_mods[notes[0]["noteId"]] = int(time.time())
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job())
    queue = deck.queue()
    assert report["ok"] and queue.index(cards[0]["cardId"]) == queue.index(old) + 1


def test_the_cards_placed_are_not_recorded_when_the_re_check_left_one(deck):
    # 3 #2 / E4: a card left for the next job is not placed: `seen` waits for a run that placed every card.
    calls = []

    def study_one(ids):
        calls.append(ids)
        if len(calls) == 2:
            deck.cards[ids[0]].update(type=2, queue=2, due=20000)
    deck.before_cards_info = study_one
    with _patched(deck):
        report = reposition.run(_settings(), job=spaced.Job())
    assert report["left"] and undo.ladder("ja", ["TheBank"])["seen"] is None
    assert undo.ladder("ja", ["TheBank"])["floor"] == 2800          # cards did land: the bottom is kept


def test_the_click_carries_the_re_planned_numbering_not_the_one_before(deck):
    # 3 #2 / E9: what the panel shows after a click is the re-planned numbering.
    from modules.junban import gui as junban_gui
    with _patched(deck):
        _writes, stats = reposition.dry_run(_settings(), job=spaced.Job())
    stats = dict(stats, numbering={"kind": "before the click"})

    class Window:
        _preview_stats = stats
        _ticked = {}
        _deselected = {stats["order"][0].card_id}

        def _changed_ticks(self):
            return {}

        def _settings(self):
            return _settings()

        def _lang_code(self):
            return "ja"
    merged = junban_gui.JunbanGui._with_deselection(Window(), stats)
    assert merged["numbering"]["kind"] == spaced.FULL


def test_spaced_out_once_the_first_time_and_again_after_anki_renumbered_the_deck(deck):
    # 3 #2 / E11 and 3 #7: "once" the first time a ladder is laid for a deck, "again" afterwards; a first
    # run that wrote nothing lays nothing.
    deck.fail_write_chunk = 1
    with _patched(deck):
        failed = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert not failed["written"] and undo.ladder_floor("ja", ["TheBank"]) is None
    deck.fail_write_chunk = None
    with _patched(deck):
        first = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert first["message"].startswith("Spaced your new cards out once")
    for offset, card_id in enumerate(sorted(deck.cards, key=lambda c: deck.cards[c]["due"])):
        deck.cards[card_id]["due"] = 1 + offset                     # Anki renumbered the deck from 1
    with _patched(deck):
        again = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True))
    assert again["message"].startswith("Spaced your new cards out again")


def test_in_all_decks_restore_offers_the_all_decks_order_not_a_one_deck_baseline(deck):
    # 3 #5: a one-deck baseline would only be refused in All decks; the All-decks snapshot is offered.
    undo.save([(card_id, card["due"]) for card_id, card in deck.cards.items()], ["TheBank"], mode="all")
    undo.mark_complete("ja")
    time.sleep(1.1)
    undo.save_baseline([(1789712090000, 50)], ["Kanji"], day="2026-10-06")
    assert undo.restorable("ja", undo.ALL_DECKS).get("mode") == "all"
    assert reposition._restore_scope(_settings(junban_scope="all")) is undo.ALL_DECKS


def test_a_note_type_new_since_the_fresh_read_is_watched_for_renames(deck):
    # 3 #6: a card of a note type the map hadn't seen arrives; renaming that type's field reads afresh.
    card_map = reposition.CardMap()
    url = "http://127.0.0.1:8765"
    with _patched(deck):
        reposition._gather(url, ["TheBank"], {}, "ja", card_map=card_map)
    cards, notes, _ = _collection(["掃除機"], dues=[2830], start=60)
    notes[0]["modelName"] = "Kaishi"
    deck.cards[cards[0]["cardId"]] = dict(cards[0], mod=int(time.time()))
    deck.notes[notes[0]["noteId"]] = notes[0]
    deck.note_mods[notes[0]["noteId"]] = int(time.time())
    with _patched(deck):
        reposition._gather(url, ["TheBank"], {}, "ja", card_map=card_map)
    assert "Kaishi" in card_map.models and card_map.fresh == 1
    notes[0]["fields"] = {("Word" if name == "Expression" else name): value
                          for name, value in notes[0]["fields"].items()}
    with _patched(deck):
        reposition._gather(url, ["TheBank"], {}, "ja", card_map=card_map)
    assert card_map.fresh == 2


# --------------------------------------------------------------------------- #
# E3.1-B2: a warm job asks in fewer round trips, and checks every card as before
# --------------------------------------------------------------------------- #
def _warm_job(deck, ranked_words, write_priority_csv, priority_rows, card_map):
    """A warm automatic job's set-up: the first spaced run (its session's sync too), every card's mod time then
    aged past any second the next read could share, and a move on the list (four words to the top) for the next
    run to write."""
    with _patched(deck):
        first = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True, cards=card_map))
    assert first["ok"] and first["written"]
    for card in deck.cards.values():
        card["mod"] = 1_700_000_500                  # written long ago, as far as the next read can tell
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[12:16])


def _card_of(deck, word):
    return next(card_id for card_id, card in deck.cards.items()
                if deck.notes[card["note"]]["fields"]["Expression"]["value"] == word)


def test_a_warm_jobs_re_check_is_one_request_with_the_review_check_and_mod_times(deck, ranked_words,
                                                                                  write_priority_csv, priority_rows):
    # Before each write request: ONE request asks whether a review is on and the request's cards' mod times
    # (cardsInfo only for a card changed within the read's own second). Never a lone guiReviewActive or cardsInfo,
    # and S1 takes the profile the map read under the same lock.
    card_map = reposition.CardMap()
    _warm_job(deck, ranked_words, write_priority_csv, priority_rows, card_map)
    deck.requests.clear()
    with _patched(deck):
        report = reposition.run(_settings(junban_chunk_size=2), refresh=False,
                                job=spaced.Job(automatic=True, cards=card_map))
    assert report["ok"] and report["written"] and not report["left"]
    actions = [_subactions(request) for request in deck.requests]
    writes = [i for i, names in enumerate(actions) if "setSpecificValueOfCard" in names]
    assert len(writes) >= 2
    for i in writes:
        assert actions[i - 1] == ["guiReviewActive", "cardsModTime"], actions[i - 1]
    top = [request["action"] for request in deck.requests]
    assert not {"guiReviewActive", "cardsInfo", "getActiveProfile"} & set(top), top


def test_a_card_studied_after_a_warm_read_is_left_by_its_mod_time(deck, ranked_words, write_priority_csv,
                                                                   priority_rows):
    # I1 on the light re-check: a card reviewed between the read and its write moves its mod time; it is left for
    # the next job and its review date stays untouched.
    card_map = reposition.CardMap()
    _warm_job(deck, ranked_words, write_priority_csv, priority_rows, card_map)
    calls = []

    def study_one(ids):
        calls.append(ids)
        if len(calls) == 2:                         # the first re-check (the first call is the map's read)
            deck.cards[ids[0]].update(type=2, queue=2, due=20000, mod=int(time.time()))
    deck.before_mod_times = study_one
    deck.writes.clear()
    with _patched(deck):
        report = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True, cards=card_map))
    studied = calls[1][0]
    assert studied in report["left"] and studied not in report["written"]
    assert all(card_id != studied for card_id, _due in deck.writes)
    assert deck.cards[studied]["due"] == 20000


def test_a_card_changed_in_the_reads_own_second_is_re_checked_in_full(deck, ranked_words, write_priority_csv,
                                                                       priority_rows):
    # A mod time proves nothing within the read's own second: such a card is read with cardsInfo, in the same
    # request as the others' mod times. Moved by hand again in that second (same mod time), it is left.
    card_map = reposition.CardMap()
    _warm_job(deck, ranked_words, write_priority_csv, priority_rows, card_map)
    target = _card_of(deck, ranked_words[12])        # one of the words moved to the top: written in request 1
    deck.cards[target]["mod"] = int(time.time())     # changed in the second the next read happens
    calls = []

    def move_it(ids):
        calls.append(ids)
        if len(calls) >= 2 and target in ids:       # after the map's read: the re-check
            deck.cards[target]["due"] = 1
    deck.before_cards_info = move_it
    deck.requests.clear()
    deck.writes.clear()
    with _patched(deck):
        report = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True, cards=card_map))
    check = next(request for request in deck.requests if _subactions(request)[:1] == ["guiReviewActive"]
                 and any(target in (entry.get("params") or {}).get("cards", [])
                         for entry in request["params"]["actions"]))
    by_action = {entry["action"]: entry["params"]["cards"] for entry in check["params"]["actions"][1:]}
    assert target in by_action["cardsInfo"] and target not in by_action.get("cardsModTime", [])
    assert target in report["left"] and deck.cards[target]["due"] == 1
    assert all(card_id != target for card_id, _due in deck.writes)


def test_after_a_session_sync_the_re_check_reads_every_card_in_full(deck, ranked_words, write_priority_csv,
                                                                     priority_rows, monkeypatch):
    # S1 may bring anything from the phone: after it synced, the re-check is cardsInfo again, as before B2.
    from app import anki_sync_rule
    card_map = reposition.CardMap()
    _warm_job(deck, ranked_words, write_priority_csv, priority_rows, card_map)
    monkeypatch.setattr(anki_sync_rule, "before_write", lambda *args, **kwargs: "synced")
    deck.requests.clear()
    with _patched(deck):
        report = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True, cards=card_map))
    assert report["ok"] and report["written"]
    top = [request["action"] for request in deck.requests]
    first = next(i for i, request in enumerate(deck.requests) if "setSpecificValueOfCard" in _subactions(request))
    assert top[first - 2:first] == ["guiReviewActive", "cardsInfo"]


def test_a_job_carrying_its_probe_asks_anki_for_it_no_more(deck):
    # The preview probed a moment ago (before reading the library): the run's preflight reuses that answer.
    with _patched(deck):
        probe = reposition.probe_anki(_settings())
    assert probe["ok"]
    deck.requests.clear()
    with _patched(deck):
        report = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True, probe=probe))
    assert report["ok"]
    assert "requestPermission" not in deck.action_names and "apiReflect" not in deck.action_names
    closed = {"ok": False, "version": None, "missing": [], "error": "Could not reach Anki at x. Is Anki running?"}
    deck.requests.clear()
    with _patched(deck):
        refused = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True, probe=closed))
    assert not refused["ok"] and refused["problems"][0] == closed["error"]
    assert not deck.requests                        # nothing asked of Anki: the probe already said it's closed


def test_reads_pack_actions_into_as_few_requests_as_the_cap_allows(deck):
    # `_reads`: both kinds of mod time in one request when they fit; a big deck splits by the cap; empty asks nothing.
    url = "http://127.0.0.1:8765"
    cards = sorted(deck.cards)
    notes = sorted(deck.notes)
    with _patched(deck):
        assert reposition._reads(url, [("cardsModTime", "cards", []), ("notesModTime", "notes", [])], 10) == \
            {"cardsModTime": [], "notesModTime": []}
        assert not deck.requests
        out = reposition._reads(url, [("cardsModTime", "cards", cards), ("notesModTime", "notes", notes)], 60)
        assert len(deck.requests) == 1 and len(out["cardsModTime"]) == 30 and len(out["notesModTime"]) == 30
        deck.requests.clear()
        out = reposition._reads(url, [("cardsModTime", "cards", cards), ("notesModTime", "notes", notes)], 25)
    assert [len(request["params"]["actions"]) for request in deck.requests] == [1, 2, 1]
    assert sum(len(entry["params"]["cards" if entry["action"] == "cardsModTime" else "notes"])
               for request in deck.requests for entry in request["params"]["actions"]) == 60
    assert len(out["cardsModTime"]) == 30 and len(out["notesModTime"]) == 30


def test_a_refused_card_mod_time_in_the_re_check_reads_those_cards_in_full(deck, ranked_words, write_priority_csv,
                                                                           priority_rows):
    # An AnkiConnect that answers the map's mod times but refuses them inside the re-check: those cards are read
    # with cardsInfo in a request of their own — checked all the same, never written blind.
    from modules.junban.tests.test_reposition import AnkiRefusal
    card_map = reposition.CardMap()
    _warm_job(deck, ranked_words, write_priority_csv, priority_rows, card_map)
    answer, asked = deck._dispatch, []

    def dispatch(action, params):
        if action == "cardsModTime":
            asked.append(len(asked))
            if len(asked) > 1:                       # the map's read went through; the re-checks are refused
                return AnkiRefusal("unsupported action")
        return answer(action, params)
    deck._dispatch = dispatch
    deck.requests.clear()
    with _patched(deck):
        report = reposition.run(_settings(), refresh=False, job=spaced.Job(automatic=True, cards=card_map))
    assert report["ok"] and report["written"] and not report["left"]
    top = [request["action"] for request in deck.requests]
    first = next(i for i, request in enumerate(deck.requests) if "setSpecificValueOfCard" in _subactions(request))
    assert top[first - 1] == "cardsInfo"


def test_the_known_words_memo_reads_again_when_a_switch_or_the_librarys_names_change(monkeypatch):
    # Review 3 R5: the memo was keyed on the four files alone; the known sets also follow the token store's known key
    # (the names, phrases and pronoun switches, the name tables) and the names Ignore names adds.
    from app import token_index
    monkeypatch.setattr(reposition, "_KNOWN_MEMO", {})
    reads = []
    monkeypatch.setattr(reposition, "_known_sets", lambda language, settings: reads.append(1) or (set(), set(), set()))
    names, key = [], ["sig"]
    monkeypatch.setattr(token_index, "ignored_names", lambda language: list(names))
    monkeypatch.setattr(token_index.Store, "_known_key", lambda self, signature: key[0])
    settings = _settings()
    reposition._known_memo("ja", settings)
    reposition._known_memo("ja", settings)
    assert len(reads) == 1                          # nothing changed: read once
    names.append("須藤")                             # Ignore names on, a name the library holds
    reposition._known_memo("ja", settings)
    assert len(reads) == 2
    key[0] = "sig|names=0111:stamp"                 # a names switch turned off
    reposition._known_memo("ja", settings)
    assert len(reads) == 3


def test_a_card_modified_one_second_before_the_last_read_is_read_again(deck, monkeypatch):
    # The docstring's "within a second of the last read" margin: a card whose mod time is one second
    # before the read began may have changed in that same second, so the next warm read picks it up.
    T = 1_800_000_000
    card_id = next(iter(deck.cards))
    with monkeypatch.context() as m:
        m.setattr(reposition.time, "time", lambda: T + 0.5)     # the cold read begins at T
        deck.cards[card_id]["mod"] = T - 1
        card_map = reposition.CardMap()
        with _patched(deck):
            reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
        deck.cards[card_id]["due"] = 4321                       # changed again; mod stays T - 1
        with _patched(deck):
            cards, _ = reposition._gather("http://127.0.0.1:8765", ["TheBank"], {}, "ja", card_map=card_map)
    assert next(card for card in cards if card["card_id"] == card_id)["due"] == 4321
    assert card_map.fresh == 1                                  # the second read was warm, not a full read


@pytest.mark.parametrize("front", [3, 5])
def test_an_item_sent_from_the_front_to_the_back_writes_tomorrows_cards_alone_first(deck, ranked_words,
                                                                                   write_priority_csv, priority_rows,
                                                                                   front):
    """E3.3 (E3.1-B3, Sonic's A): the top eight words sent to the back of the list. Their cards held the lowest
    numbers, so the old rule pushed all eight out of tomorrow's into the first request; now tomorrow's cards are
    numbered below them and go alone first — Anki's first N are the plan's when it lands, the eight follow, the
    preview showed the same numbers, and a second run writes nothing."""
    with _patched(deck):
        reposition.run(_settings(), job=spaced.Job())
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[:8], to_back=True)
    n = front
    deck.write_requests.clear()
    deck.after_writes.clear()
    with _patched(deck):
        _writes, preview = reposition.dry_run(_settings(), job=spaced.Job(front=front))
        report = reposition.run(_settings(), job=spaced.Job(front=front))
    assert report["ok"] and report["stats"]["numbering"]["front_first"] is True
    order = _planned(report)
    assert sorted(card_id for card_id, _new in deck.write_requests[0]) == sorted(order[:n])
    after = deck.after_writes[0]
    assert sorted((card_id for card_id in after if card_id in set(order)),
                  key=lambda card_id: (after[card_id], card_id))[:n] == order[:n]
    assert deck.queue() == order
    assert [row.position for row in preview["order"]] == [row.position for row in report["stats"]["order"]]
    deck.write_requests.clear()
    with _patched(deck):
        again = reposition.run(_settings(), job=spaced.Job(front=front))
    assert again["ok"] and not again["written"]


def test_the_preview_numbers_with_the_decks_own_new_cards_a_day_as_the_run_does(deck, monkeypatch):
    """E3.3: tomorrow's N reaches the numbering — the run's from its preflight, the 順 window's preview from the
    deck's options read for it — so a deck studying 30 new cards a day is previewed with N = 30, not the floor of 20,
    and the preview's numbers are the run's."""
    deck.per_day = 30
    seen = []
    real = reposition._plan_scope

    def spy(*args, **kwargs):
        seen.append(kwargs.get("front"))
        return real(*args, **kwargs)
    monkeypatch.setattr(reposition, "_plan_scope", spy)
    with _patched(deck):
        _writes, preview = reposition.dry_run(_settings(), job=spaced.Job())
        report = reposition.run(_settings(), job=spaced.Job())
    assert seen == [30, 30]
    assert [row.position for row in preview["order"]] == [row.position for row in report["stats"]["order"]]


def test_tomorrows_n_is_the_highest_new_cards_a_day_of_the_decks_and_a_deck_unread_is_left_out(monkeypatch):
    """E3.3: N for the numbering and the requests — the job's own, else the highest New cards/day among the decks in
    scope (two decks studying 25 and 30 a day: tomorrow holds 30), at least 20; a deck whose options can't be read
    is skipped, never the decks after it."""
    from modules.junban import ankiconnect
    assert reposition._front(spaced.Job(front=7), {"A": 30}) == 7
    assert reposition._front(spaced.Job(), {"A": 25, "B": 30, "C": None, "D": True}) == 30
    assert reposition._front(spaced.Job(), {}) == 20

    def config(url, deck):
        if deck == "A":
            raise reposition.AnkiError("deck options unreadable")
        return {"new": {"perDay": 30}}
    monkeypatch.setattr(ankiconnect, "deck_config", config)
    assert reposition._per_day("http://127.0.0.1:8765", ["A", "B"]) == {"B": 30}


def test_the_run_writes_with_the_decks_n_and_names_tomorrows_cards_it_wrote_first(deck, ranked_words,
                                                                                write_priority_csv, priority_rows):
    """E3.3: with no N of its own, the job writes with the deck's New cards/day (30 here) — the N it numbered with —
    and tells its caller tomorrow's cards it wrote first (`front_ids`: the bar's "placing tomorrow's 30 cards" and
    S3's clock), exactly the first request's cards."""
    deck.per_day = 30
    with _patched(deck):
        reposition.run(_settings(), job=spaced.Job())
    _move_on_the_list(write_priority_csv, priority_rows, ranked_words, ranked_words[18:24])  # a file's words up
    deck.write_requests.clear()
    job = spaced.Job()
    with _patched(deck):
        report = reposition.run(_settings(), job=job)
    assert report["ok"] and report["written"]
    assert job.front_size == 30
    assert job.front_ids and set(job.front_ids) == {card_id for card_id, _new in deck.write_requests[0]}
