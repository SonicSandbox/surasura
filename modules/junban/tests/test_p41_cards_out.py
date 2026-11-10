# SPDX-License-Identifier: GPL-3.0-or-later
"""*Take its new cards out* — Junban's half (P4.1 L2 package T, with the review's fixes TF; L2.2 05 §5.7, D14; W1.2
01-scope fc).

The window's *Take its new cards out* leaves an item out of the learning order (`in_learning_order` 0). Every Junban
run then places that item's new cards whose words left the list after every other card; a run whose caller records
what it changes in the store (`spaced.Job.cards_out`: the window's re-order host, Connect's step) also suspends and
tags them `Surasura::out` — never deleted, whatever the `junban_later_*` settings say — and the next such run after
*Put back* restores what Junban's tag still marks. What a wrong answer would cost, most first:

  * **never a card you studied or suspended yourself** — only the run's own new, unsuspended cards go out, never one
    you mined yourself (TF fix 2, P4.1-6); Put back unsuspends only cards still suspended and new on a note still
    carrying the tag, so one you suspended after a Restore gave it back stays suspended (TF fix 4);
  * **never a word you still need** — a card whose word is on the list stays in, placed by the list (TF fix 3,
    P4.1-7: the shelf's rule);
  * **never another item's card** (T-3) — a card an item still in the order claims, by the store or by its source,
    stays in; a note two out items claim comes back with either (TF fix 7);
  * **nothing lost** — what was asked is recorded (a batch that timed out after it landed too), a suspend no record
    names is found by its tag, a record of another Anki profile waits for it, and a take-out or Put back that didn't
    land stays owed (TF fixes 4–6);
  * **positions only means positions only** — `junban --auto` and `resort` (and any run that records nothing) only
    move them to the end.

Against Junban's fake collection (`ModCollection`, plus the two tag searches Put back sends), real Japanese and Chinese
words; the store's reader stood in by `pins.read_out`'s shape (the real store's own tests:
tests/test_library_store_cards_out.py; the whole loop through the window's re-order host:
tests/test_replan_preview_cards_out.py). Never Anki: every request goes to the fake (`_patched`).
"""
import pytest

from modules.junban import auto, connect, first_touch, pins, plan, reposition, touchup, unlisted
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, AnkiRefusal, _card_of, _collection, _patched,
                                                  _results, _settings, _tags_of)
from modules.junban.tests.test_spaced_runs import ModCollection

_ACTIONS = ("setSpecificValueOfCard", "multi", "suspend", "unsuspend")
OUT_ITEM, OTHER_OUT = 7, 8
OUT_TAG = "Surasura::out"
URL = "http://127.0.0.1:8765"           # only ever the fake's: every call below runs inside `_patched`

# Per language: the list's words (in Current), the out item's new cards — one whose word is on the list (it stays in:
# P4.1-7) and two whose words aren't — its reviewed card, and a card it shares with an item still in the order.
SCENES = {
    "ja": dict(listed=["冒険", "散歩"], by_list="老婆", out=["須藤", "台所"], reviewed="眼鏡", shared="図書館",
               progressive=_JOURNEY, library=_LIBRARY),
    "zh": dict(listed=["学习", "认真"], by_list="老师", out=["一石二鸟", "熊猫"], reviewed="眼镜", shared="图书馆",
               progressive=[(1, "学习", "学习", 50, 5), (1, "认真", "认真", 40, 4), (2, "老师", "老师", 30, 3)],
               library=None),
}


class TagCollection(ModCollection):
    """The fake collection, plus the two searches Put back sends, as Anki answers them: `findNotes` for the notes
    carrying a tag (or one under it) that hold a suspended new card, `findCards` for those notes' suspended new
    cards. Optionally a suspend that lands and then times out (`late_suspend`), or an unsuspend Anki refuses."""

    def __init__(self, *args, late_suspend=False, refuse_unsuspend=False, refuse_out_tag=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.late_suspend = late_suspend
        self.refuse_unsuspend = refuse_unsuspend
        self.refuse_out_tag = refuse_out_tag

    def _tags(self, action, params):
        if action == "addTags" and self.refuse_out_tag and params.get("tags") == OUT_TAG:
            self.tag_calls.append((action, list(params.get("notes") or []), params.get("tags")))
            return AnkiRefusal("collection is not open")
        return super()._tags(action, params)

    def _held(self, card):
        return card["type"] == 0 and card["queue"] == -1

    def _dispatch(self, action, params):
        query = params.get("query", "") if isinstance(params, dict) else ""
        if action == "findNotes" and query.startswith('"tag:'):
            tag = query.split('"')[1][len("tag:"):]
            return sorted({card["note"] for card in self.cards.values() if self._held(card)
                           and touchup.carries_tag(self.notes[card["note"]].get("tags") or [], tag)})
        if action == "findCards" and query.startswith("nid:"):
            notes = {int(n) for n in query.split()[0][len("nid:"):].split(",")}
            return sorted(c["cardId"] for c in self.cards.values() if c["note"] in notes and self._held(c))
        return super()._dispatch(action, params)

    def _suspend(self, action, card_ids):
        if action == "unsuspend" and self.refuse_unsuspend:
            self.suspend_calls.append((action, list(card_ids)))
            return AnkiRefusal("collection is not open")
        done = super()._suspend(action, card_ids)
        if action == "suspend" and self.late_suspend:
            return AnkiRefusal("timed out")             # applied, then the answer never came back in time
        return done


def _scene(tmp_path, language, **fake):
    """The deck: the out item's cards first in the queue (the list would keep 老婆 / 老师 ahead), then the rest."""
    s = SCENES[language]
    _results(tmp_path, progressive=s["progressive"], library=s["library"], floor=11 if s["library"] else None)
    words = [s["by_list"]] + s["out"] + [s["shared"], s["reviewed"]] + s["listed"]
    cards, notes, _ = _collection(words)
    collection = TagCollection(cards, notes, actions=_ACTIONS, **fake)
    reviewed = _card_of(collection, s["reviewed"])
    reviewed.update(type=2, queue=2, due=400)                  # studied: never a new card again
    return collection


def _note(fake, word):
    return _card_of(fake, word)["note"]


def _read(fake, language, back=(), held=()):
    """`pins.read_out`'s answer for the scene: the out item claims its new cards, its reviewed card and the shared
    card by the store (`cards_of`); the item still in the order claims the shared card too."""
    s = SCENES[language]
    mine = [_note(fake, w) for w in [s["by_list"]] + s["out"] + [s["reviewed"], s["shared"]]]
    return {"out": [(OUT_ITEM, "Hato/番組 - 05.srt")], "notes": {OUT_ITEM: mine}, "names": {OUT_ITEM: set()},
            "kept_notes": {_note(fake, s["shared"])}, "kept_names": set(), "back": list(back), "held": list(held)}


def _settings_for(language, **over):
    # Every "not on your list" action off: the take-out suspends and tags all the same (T-1).
    return _settings(junban_order="content", target_language=language, **over)


@pytest.fixture
def three_oh(monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)


def _new_dues(fake):
    return {c["cardId"]: c["due"] for c in fake.cards.values() if c["type"] == 0}


def _record(row, record_id):
    """A report's `cards_out` row as the store hands it back (`anki_changes_of`)."""
    item_id, action, notes, before, after = row
    return {"id": record_id, "item_id": item_id, "action": action, "notes": notes, "before": before, "after": after}


def _taken_out(tmp_path, monkeypatch, language="ja", read=None, **fake):
    """The scene after one recording run took the out item's cards out -> (fake, the report)."""
    collection = _scene(tmp_path, language, **fake)
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: read(collection) if read else
                        _read(collection, lang))
    with _patched(collection):
        report = auto.reorder(_settings_for(language), list_current=True, cards_out=True)["report"]
    return collection, report


def _unsuspended(fake):
    return [c for action, ids in fake.suspend_calls if action == "unsuspend" for c in ids]


def _put_back(fake, read):
    """`_put_back_out` alone, as a run calls it: holding Anki's write lock (a write without it is refused), every
    request to the fake."""
    from app import anki_connect
    held, problem = anki_connect.take_writer("TF's test", URL)
    assert held is not None, problem
    with _patched(fake), held:
        return reposition._put_back_out(URL, _settings_for("ja"), ["TheBank"], read)


# --------------------------------------------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_recording_run_suspends_and_tags_the_items_unlisted_new_cards_last_and_records_them(tmp_path, monkeypatch,
                                                                                                three_oh, language):
    """T-1/T-3/T-6, and P4.1-7 (TF fix 3; moved from T-2's "the item wins over the list"): the out item's two cards
    whose words left the list go after every other card, then are tagged `Surasura::out` and suspended, with every
    "not on your list" action off; its card whose word is still on the list (老婆 / 老师) stays in, placed by the list;
    its reviewed card and the card an item still in the order shares are untouched; the report carries one record for
    the store, in the open Anki profile (TF fix 5)."""
    s = SCENES[language]
    fake, report = _taken_out(tmp_path, monkeypatch, language)
    assert report["ok"], report["problems"]
    out_ids = sorted(_card_of(fake, w)["cardId"] for w in s["out"])
    dues = _new_dues(fake)
    others = [due for card_id, due in dues.items() if card_id not in out_ids]
    assert min(dues[c] for c in out_ids) > max(others), "placed after every other card before they were suspended"
    assert all(_card_of(fake, w)["queue"] == -1 for w in s["out"])
    assert all(OUT_TAG in _tags_of(fake, w) for w in s["out"])
    listed = _card_of(fake, s["by_list"])
    assert listed["queue"] == 0 and OUT_TAG not in _tags_of(fake, s["by_list"]), "P4.1-7: its word is on the list"
    order = report["stats"]["order"]
    assert [(r.word, r.tier, r.out) for r in order if r.word == s["by_list"]] == [(s["by_list"], "list", None)]
    assert dues[listed["cardId"]] < min(dues[c] for c in out_ids), "placed by the list, ahead of the out cards"
    reviewed = _card_of(fake, s["reviewed"])
    assert (reviewed["type"], reviewed["queue"]) == (2, 2) and OUT_TAG not in _tags_of(fake, s["reviewed"])
    assert _card_of(fake, s["shared"])["queue"] == 0 and OUT_TAG not in _tags_of(fake, s["shared"])
    assert not [tag for _a, _n, tag in fake.tag_calls if tag and tag.endswith("::later")], "T-1: not §13's"
    assert [c for action, ids in fake.suspend_calls if action == "suspend" for c in ids] == out_ids
    notes = sorted(_note(fake, w) for w in s["out"])
    assert report["cards_out"] == [(OUT_ITEM, "cards_out", notes, {"queue": 0, "tagged": []},
                                    {"queue": -1, "suspended": out_ids, "tag": OUT_TAG, "tagged": notes,
                                     "profile": "DevTest"})]
    assert report["cards_taken_out"] == 2 and "Taken out of your order: suspended 2 cards" in report["message"]


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("how", ["positions-only", "manual", "no-recorder"])
def test_a_run_that_records_nothing_only_moves_them_to_the_end(tmp_path, monkeypatch, three_oh, language, how):
    """T-6: `junban --auto` / `resort` (positions only), a run you start in 順, and any automatic run whose caller
    records nothing (2.x's dashboard step): the out item's unlisted cards go after every other card — no tag, no
    suspend — and its listed card keeps the list's place (P4.1-7, moved from T-2)."""
    s = SCENES[language]
    fake = _scene(tmp_path, language)
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: _read(fake, lang))
    with _patched(fake):
        if how == "positions-only":
            report = auto.reorder(_settings_for(language), list_current=True, positions_only=True,
                                  cards_out=True)["report"]
        elif how == "manual":
            report = reposition.run(_settings_for(language))
        else:
            report = auto.reorder(_settings_for(language, junban_auto_actions=True), list_current=True)["report"]
    assert report["ok"], report["problems"]
    out_ids = [_card_of(fake, w)["cardId"] for w in s["out"]]
    dues = _new_dues(fake)
    assert min(dues[c] for c in out_ids) > max(d for c, d in dues.items() if c not in out_ids)
    assert dues[_card_of(fake, s["by_list"])["cardId"]] < min(dues[c] for c in out_ids), "the list's word: in"
    assert all(_card_of(fake, w)["queue"] == 0 for w in s["out"])
    assert fake.suspend_calls == [] and not [t for _a, _n, t in fake.tag_calls if t == OUT_TAG]
    assert "cards_out" not in report


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_put_back_restores_exactly_the_recorded_cards_and_never_one_you_suspended(tmp_path, monkeypatch, three_oh,
                                                                                    language):
    """T-5: the item is back in the order; the next recording run unsuspends exactly the recorded cards still suspended
    and new, takes `Surasura::out` off exactly the notes it tagged, places them, and reports the record restored.
    Meanwhile you suspended a list card, and studied-then-suspended one of the recorded ones: both stay suspended."""
    s = SCENES[language]
    fake, first = _taken_out(tmp_path, monkeypatch, language)
    record = _record(first["cards_out"][0], 41)
    yours = _card_of(fake, s["listed"][1])
    yours["queue"] = -1                                         # you suspended it yourself
    studied = _card_of(fake, s["out"][1])
    studied.update(type=2)                                      # unsuspended, studied and suspended again by you
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: {"out": [], "back": [record], "held": []})
    with _patched(fake):
        done = auto.reorder(_settings_for(language), list_current=True, cards_out=True)
    report = done["report"]
    assert report["ok"], report["problems"]
    back = _card_of(fake, s["out"][0])
    assert back["queue"] == 0 and OUT_TAG not in _tags_of(fake, s["out"][0])
    assert OUT_TAG not in _tags_of(fake, s["out"][1]), "the tag comes off every note it put it on"
    assert studied["queue"] == -1 and yours["queue"] == -1
    assert _unsuspended(fake) == [back["cardId"]]
    assert report["put_back"] == [41] and report["cards_put_back"] == 1
    assert back["cardId"] in [row.card_id for row in report["stats"]["order"]], "placed in the same run"
    assert not [row for row in report["stats"]["order"] if row.out], "nothing is out any more"


def test_a_card_studied_between_the_plan_and_the_suspend_is_never_suspended_or_recorded(tmp_path, monkeypatch,
                                                                                         three_oh):
    """The re-check just before the actions (`_still_new`, as §13's): 台所 was studied on the phone while the positions
    went out — it is not suspended, its note not tagged, and the record names 須藤 alone. Not owed either: a studied
    card is never out again (TF fix 6)."""
    fake = _scene(tmp_path, "ja")
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: _read(fake, lang))
    out_ids = {_card_of(fake, w)["cardId"] for w in ("須藤", "台所")}

    def studied_meanwhile(ids):
        if set(ids) == out_ids:                                 # the re-check of the out cards alone
            _card_of(fake, "台所")["type"] = 2
    fake.before_cards_info = studied_meanwhile
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert report["ok"], report["problems"]
    assert _card_of(fake, "台所")["queue"] == 0 and OUT_TAG not in _tags_of(fake, "台所")
    assert _card_of(fake, "須藤")["queue"] == -1
    (_item, _action, notes, _before, after), = report["cards_out"]
    assert after["suspended"] == [_card_of(fake, "須藤")["cardId"]] and notes == [_note(fake, "須藤")]
    assert report["left"] == []


def test_put_back_with_anki_not_answering_restores_nothing_and_closes_no_record(tmp_path, monkeypatch, three_oh):
    """A record whose cards can't be read stays open, owed: the next run tries again; nothing is unsuspended blind."""
    fake = _scene(tmp_path, "ja")
    card = _card_of(fake, "須藤")
    card["queue"] = -1
    record = {"id": 5, "item_id": OUT_ITEM, "action": "cards_out", "notes": [card["note"]], "before": {},
              "after": {"suspended": [card["cardId"]], "tag": OUT_TAG, "tagged": [card["note"]]}}
    monkeypatch.setattr(reposition.ankiconnect, "multi", lambda *a, **k: (_ for _ in ()).throw(
        reposition.AnkiError("Anki stopped answering")))
    done = _put_back(fake, {"out": [], "back": [record], "held": []})
    assert done["restored"] == [] and done["left"] == [card["cardId"]]
    assert card["queue"] == -1


# --------------------------------------------------------------------------------------------------------------- #
# TF: the review's fixes
# --------------------------------------------------------------------------------------------------------------- #
def test_your_own_cards_are_never_taken_out(tmp_path, monkeypatch, three_oh):
    """TF fix 2 (P4.1-6 ⭐ (b); ruling P1.4-1, Settings' "Your own cards first": never suspended): 須藤 carries your own
    tag — the out item claims it, its word is off the list, and still it is neither suspended nor tagged nor moved
    last; 台所, Connect's, goes out."""
    fake = _scene(tmp_path, "ja")
    fake.notes[_note(fake, "須藤")]["tags"] = ["immersion"]
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: _read(fake, lang))
    with _patched(fake):
        report = auto.reorder(_settings_for("ja", connect_enabled=True, junban_own_tag="immersion"),
                              list_current=True, cards_out=True)["report"]
    assert report["ok"], report["problems"]
    mine = _card_of(fake, "須藤")
    assert mine["queue"] == 0 and OUT_TAG not in _tags_of(fake, "須藤")
    assert [(row.word, row.tier, row.out) for row in report["stats"]["order"] if row.word == "須藤"] == \
        [("須藤", "yours", None)]
    assert _card_of(fake, "台所")["queue"] == -1
    assert report["cards_out"][0][4]["suspended"] == [_card_of(fake, "台所")["cardId"]]


def test_put_back_leaves_a_card_you_suspended_after_a_restore_gave_it_back(tmp_path, monkeypatch, three_oh):
    """TF fix 4 (adversary S1): 順's *Put Anki back…* gave 須藤 back — unsuspended, the tag taken off — while its record
    stayed open; you then suspended it yourself. Put back leaves it suspended (its note no longer carries the tag)
    and still restores 台所, which nothing gave back; the record closes."""
    fake, first = _taken_out(tmp_path, monkeypatch)
    record = _record(first["cards_out"][0], 12)
    card = _card_of(fake, "須藤")
    note = fake.notes[card["note"]]
    card["queue"], note["tags"] = 0, [t for t in note.get("tags") or [] if t != OUT_TAG]    # the undo
    card["queue"] = -1                                                                       # you, after it
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: {"out": [], "back": [record], "held": []})
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert report["ok"], report["problems"]
    assert card["queue"] == -1, "a card you suspended yourself stays suspended"
    assert _unsuspended(fake) == [_card_of(fake, "台所")["cardId"]]
    assert report["put_back"] == [12]


@pytest.mark.parametrize("claimed", ["by-an-item-in-the-order", "by-the-out-item"])
def test_a_suspend_no_record_names_is_put_back_by_its_tag_or_recorded_for_its_item(tmp_path, monkeypatch, three_oh,
                                                                                    claimed):
    """TF fix 4 (adversary N6; IK #4): a run suspended and tagged 台所 and ended before its record reached the store.
    An item in the order claims its note: Put back finds it by the tag, unsuspends it and takes the tag off. Only the
    out item claims it: it stays out, and the run's report now records it for that item (`found`), so a later Put
    back has it."""
    fake = _scene(tmp_path, "ja")
    card = _card_of(fake, "台所")
    card["queue"] = -1
    fake.notes[card["note"]]["tags"] = [OUT_TAG]
    kept = claimed == "by-an-item-in-the-order"
    read = {"out": [(OTHER_OUT if kept else OUT_ITEM, "番組/番組 - 06.srt")],
            "notes": {OTHER_OUT: []} if kept else {OUT_ITEM: [card["note"]]}, "names": {},
            "kept_notes": {card["note"]} if kept else set(), "kept_names": set(), "back": [], "held": []}
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: read)
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert report["ok"], report["problems"]
    if kept:
        assert card["queue"] == 0 and OUT_TAG not in _tags_of(fake, "台所")
        assert not report.get("cards_out")
    else:
        assert card["queue"] == -1 and OUT_TAG in _tags_of(fake, "台所")
        assert report["cards_out"] == [(OUT_ITEM, "cards_out", [card["note"]], {"queue": 0, "tagged": []},
                                        {"queue": -1, "suspended": [card["cardId"]], "tag": OUT_TAG,
                                         "tagged": [card["note"]], "found": True, "profile": "DevTest"})]


def test_a_suspend_that_landed_but_timed_out_is_recorded_and_put_back(tmp_path, monkeypatch, three_oh):
    """TF fix 4 (adversary S6): Anki applied the suspend and its answer timed out — the run counts it failed, but the
    record names what was asked, so Put back finds both cards (and reads each again before it touches it)."""
    fake, first = _taken_out(tmp_path, monkeypatch, late_suspend=True)
    out_ids = sorted(_card_of(fake, w)["cardId"] for w in ("須藤", "台所"))
    assert not first["ok"] and all(fake.cards[c]["queue"] == -1 for c in out_ids), "landed, answered late"
    assert first["cards_out"][0][4]["suspended"] == out_ids
    fake.late_suspend = False
    record = _record(first["cards_out"][0], 3)
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: {"out": [], "back": [record], "held": []})
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert all(fake.cards[c]["queue"] == 0 for c in out_ids) and report["put_back"] == [3]


def test_a_card_whose_note_could_not_be_tagged_is_never_suspended(tmp_path, monkeypatch, three_oh):
    """TF fix 4: Put back finds a card by its note's tag — so a card is suspended only once its note carries it. Anki
    refused the tag: neither card is suspended (the next run tries again), and the run says it didn't finish."""
    fake, report = _taken_out(tmp_path, monkeypatch, refuse_out_tag=True)
    assert all(_card_of(fake, w)["queue"] == 0 for w in ("須藤", "台所"))
    assert not [ids for action, ids in fake.suspend_calls if action == "suspend"]
    assert not report["ok"] and report["note_failures"]


def test_a_note_keeps_the_tag_while_a_card_of_an_item_still_out_stays_suspended_on_it(tmp_path, three_oh):
    """TF fix 7: the tag is the note's. 須藤's note holds two new cards, each taken out under another item; putting back
    item 8 restores its card, and the note keeps `Surasura::out` while item 7's card stays out on it — so 7's own Put
    back still finds that card later."""
    fake = _scene(tmp_path, "ja")
    first = _card_of(fake, "須藤")
    second = dict(first, cardId=first["cardId"] + 900, due=first["due"] + 900)
    fake.cards[second["cardId"]] = second
    for card in (first, second):
        card["queue"] = -1
    fake.notes[first["note"]]["tags"] = [OUT_TAG]
    back = {"id": 31, "item_id": OTHER_OUT, "action": "cards_out", "notes": [first["note"]], "before": {},
            "after": {"suspended": [first["cardId"]], "tag": OUT_TAG, "tagged": [first["note"]]}}
    held = {"id": 30, "item_id": OUT_ITEM, "action": "cards_out", "notes": [first["note"]], "before": {},
            "after": {"suspended": [second["cardId"]], "tag": OUT_TAG, "tagged": []}}
    done = _put_back(fake, {"out": [(OUT_ITEM, "x.srt")], "notes": {OUT_ITEM: [first["note"]]}, "names": {},
                            "kept_notes": set(), "kept_names": set(), "back": [back], "held": [held]})
    assert done["restored"] == [31] and (first["queue"], second["queue"]) == (0, -1)
    assert OUT_TAG in _tags_of(fake, "須藤"), "kept for item 7's card"


def test_put_back_leaves_another_profiles_records_open_and_counts_one_with_none_as_this_ones(tmp_path, three_oh):
    """TF fix 5 (adversary S2, D31): DevTest is open. A record made in TheBank names card ids of another collection:
    left open, nothing asked of its cards, and not owed here (it waits for its own profile). A record with no
    profile (none exist outside tests) counts as the open profile's."""
    fake = _scene(tmp_path, "ja")
    theirs, ours = _card_of(fake, "須藤"), _card_of(fake, "台所")
    for card in (theirs, ours):
        card["queue"] = -1
        fake.notes[card["note"]]["tags"] = [OUT_TAG]
    rows = [{"id": 1, "item_id": OUT_ITEM, "action": "cards_out", "notes": [theirs["note"]], "before": {},
             "after": {"suspended": [theirs["cardId"]], "tag": OUT_TAG, "tagged": [theirs["note"]],
                       "profile": "TheBank"}},
            {"id": 2, "item_id": OUT_ITEM, "action": "cards_out", "notes": [ours["note"]], "before": {},
             "after": {"suspended": [ours["cardId"]], "tag": OUT_TAG, "tagged": [ours["note"]]}}]
    done = _put_back(fake, {"out": [], "back": rows, "held": []})
    assert done["restored"] == [2] and done["left"] == []
    assert theirs["queue"] == -1 and OUT_TAG in _tags_of(fake, "須藤")
    assert ours["queue"] == 0 and OUT_TAG not in _tags_of(fake, "台所")


def test_a_take_out_dropped_at_the_re_check_stays_owed(tmp_path, monkeypatch, three_oh):
    """TF fix 6 (adversary S3): a review began just before the suspends — nothing is acted on, and the report says the
    cards are still owed (`left`), so neither caller records the plan as written and the next look tries again."""
    fake = _scene(tmp_path, "ja")
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: _read(fake, lang))
    out_ids = sorted(_card_of(fake, w)["cardId"] for w in ("須藤", "台所"))

    def review_begins(ids):
        if sorted(ids) == out_ids:
            fake.reviewing = True
    fake.before_cards_info = review_begins
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert all(fake.cards[c]["queue"] == 0 for c in out_ids) and fake.suspend_calls == []
    assert set(out_ids) <= set(report["left"]), "owed: the next re-order takes them out"
    assert not report.get("cards_out")


def test_a_put_back_that_failed_stays_owed_and_its_record_open(tmp_path, monkeypatch, three_oh):
    """TF fix 6: Anki refused the unsuspend — the run is not `ok`, the failure is named, and the record stays open
    (`put_back` holds nothing), so the plan is not recorded as written and the next look tries again."""
    fake, first = _taken_out(tmp_path, monkeypatch)
    record = _record(first["cards_out"][0], 9)
    fake.refuse_unsuspend = True
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: {"out": [], "back": [record], "held": []})
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert not report["ok"] and "put_back" not in report
    assert {c for c, _why in report["failures"]} >= set(record["after"]["suspended"])
    assert any("Putting back" in p for p in report["problems"])
    assert set(record["after"]["suspended"]) <= set(report["left"])


def test_a_note_two_out_items_claim_comes_back_with_the_newer_and_the_older_record_stays_right(tmp_path, monkeypatch,
                                                                                               three_oh):
    """TF fix 7 (adversary S4): items 7 and 8 are out and both claim 須藤's note. The take-out records 須藤 under each;
    putting back the newer (8) brings 須藤 back and takes its tag off, while 7's record stays open with 台所 still out;
    putting back 7 later restores 台所 alone (須藤 is no longer suspended: nothing twice)."""
    def read(fake):
        both = _read(fake, "ja")
        both["out"].append((OTHER_OUT, "Hato/番組 - 06.srt"))
        both["notes"][OTHER_OUT] = [_note(fake, "須藤")]
        both["names"][OTHER_OUT] = set()
        return both
    fake, first = _taken_out(tmp_path, monkeypatch, read=read)
    by_item = {row[0]: row for row in first["cards_out"]}
    sudo, kitchen = _card_of(fake, "須藤")["cardId"], _card_of(fake, "台所")["cardId"]
    assert by_item[OUT_ITEM][4]["suspended"] == sorted([sudo, kitchen]) and by_item[OTHER_OUT][4]["suspended"] == [sudo]
    older, newer = _record(by_item[OUT_ITEM], 20), _record(by_item[OTHER_OUT], 21)
    seven_out = _read(fake, "ja", back=[newer], held=[older])
    seven_out["kept_notes"] = seven_out["kept_notes"] | {_note(fake, "須藤")}       # 8 is back in the order
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: seven_out)
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert report["put_back"] == [21] and _unsuspended(fake) == [sudo]
    assert fake.cards[sudo]["queue"] == 0 and OUT_TAG not in _tags_of(fake, "須藤")
    assert fake.cards[kitchen]["queue"] == -1 and OUT_TAG in _tags_of(fake, "台所")
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: {"out": [], "back": [older], "held": []})
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert report["put_back"] == [20] and _unsuspended(fake) == [sudo, kitchen]


def test_put_back_stands_aside_while_you_review_and_journals_what_landed_when_a_request_raises(tmp_path, monkeypatch,
                                                                                               three_oh):
    """TF fix 9 (H1; IK #8): a review in progress, asked in the same request as the cards' read — nothing restored,
    the record owed. Then a request that raises after the unsuspend landed: the unsuspend is journalled all the same
    (the way back's record of it), and nothing is reported restored."""
    fake = _scene(tmp_path, "ja")
    card = _card_of(fake, "須藤")
    card["queue"] = -1
    fake.notes[card["note"]]["tags"] = [OUT_TAG]
    record = {"id": 6, "item_id": OUT_ITEM, "action": "cards_out", "notes": [card["note"]], "before": {},
              "after": {"suspended": [card["cardId"]], "tag": OUT_TAG, "tagged": [card["note"]]}}
    read = {"out": [], "back": [record], "held": []}
    fake.reviewing = True
    done = _put_back(fake, read)
    assert done["restored"] == [] and done["left"] == [card["cardId"]] and card["queue"] == -1
    assert any({"cardsInfo", "guiReviewActive"} <= {a["action"] for a in r["params"]["actions"]}
               for r in fake.requests if r["action"] == "multi"), "asked in the same request as the cards' read"
    fake.reviewing = False
    noted = []
    monkeypatch.setattr(first_touch, "noted", lambda *a, **k: noted.append(k))
    monkeypatch.setattr(reposition.ankiconnect, "remove_tags", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("the socket closed")))
    with pytest.raises(RuntimeError):
        _put_back(fake, read)
    assert card["queue"] == 0 and noted == [{"unsuspended": [card["cardId"]], "tags_off": {}}]


def test_a_recording_run_reads_what_is_out_once(tmp_path, monkeypatch, three_oh):
    """TF fix 10 (IK #10, S19): the store's view of what is out is read once per run — Put back and the plan share it."""
    fake = _scene(tmp_path, "ja")
    calls = []
    monkeypatch.setattr(pins, "read_out", lambda lang, claims=False: calls.append(claims) or _read(fake, lang))
    with _patched(fake):
        report = auto.reorder(_settings_for("ja"), list_current=True, cards_out=True)["report"]
    assert report["ok"], report["problems"]
    assert calls == [False]


# --------------------------------------------------------------------------------------------------------------- #
# The pieces
# --------------------------------------------------------------------------------------------------------------- #
def _cards(*ids):
    return [{"card_id": i, "due": 100 + i, "type": 0, "queue": 0, "word": w, "note": 500 + i}
            for i, w in zip(ids, ["冒険", "散歩", "老婆", "須藤", "図書館", "眼鏡"])]


def test_plan_puts_the_out_cards_last_in_the_order_planned_and_replan_keeps_them_there():
    """A stable partition: 老婆 (rank 0) and 須藤 go after 散歩 and 図書館, keeping their own order; a pinned card is never
    out (the later click), and one you clicked off stays where the click left it. (The planner places what it is
    handed: which cards are out — never a listed word's, P4.1-7 — is `_plan_scope`'s.)"""
    cards = _cards(1, 2, 3, 4, 5)
    rank_of = {"老婆": 0, "冒険": 1, "散歩": 2}
    _writes, stats = plan.plan(cards, rank_of, out={3, 4})
    assert [row.word for row in stats["order"]] == ["冒険", "散歩", "図書館", "老婆", "須藤"]
    assert [row.out for row in stats["order"]] == [None, None, None, True, True] and stats["out"] == 2
    _writes, again = plan.replan(stats["order"], exclude={2})
    assert [row.word for row in again["order"]][-2:] == ["老婆", "須藤"], "a click keeps them last"
    _writes, pinned = plan.plan(cards, rank_of, pins=[[3]], out={3, 4})
    assert [row.word for row in pinned["order"]][0] == "老婆" and pinned["order"][-1].word == "須藤"
    _writes, clicked = plan.plan(cards, rank_of, exclude={4}, out={3, 4})
    assert clicked["order"][-1].word == "老婆" and "out" in clicked
    _writes, none = plan.plan(cards, rank_of)
    assert "out" not in none and all(row.out is None for row in none["order"])


def test_out_cards_takes_the_items_cards_by_the_store_and_by_their_source_and_leaves_shared_ones_in():
    """T-3 and the pins' two rules: a note the store links to the out item, a card whose Anki Miner source names its
    file; a card an item still in the order claims (by the store, or by its source) stays in; a note two out items
    claim goes under both (TF fix 7, moved from "the older item only")."""
    source = "番組 — 番組 - 05 @ 00:01:00"
    cards = [{"card_id": i, "note": 600 + i} for i in range(1, 7)]
    notes = {606: {"fields": {"MiscInfo": source}}, 603: {"fields": {"MiscInfo": "他の番組 — 他の番組 - 01 @ 00:01:00"}}}
    read = {"out": [(7, "番組/番組 - 05.srt"), (8, "x.srt")], "notes": {7: [601, 602, 603], 8: [601, 605]},
            "names": {7: pins.names_of("番組/番組 - 05.srt"), 8: set()},
            "kept_notes": {602}, "kept_names": pins.names_of("他の番組/他の番組 - 01.srt")}
    assert pins.out_cards(cards, notes, read) == {1: (7, 8), 5: (8,), 6: (7,)}
    assert pins.out_cards(cards, notes, {}) == {} and pins.out_cards(cards, notes, {"out": [], "back": [1]}) == {}


def test_a_parked_card_of_an_out_item_never_comes_back_by_the_list():
    """T-5: parked (`::later`) and its word on the list again — but its item is out: it stays parked."""
    cards = [{"card_id": 1, "word": "冒険", "parked": True}, {"card_id": 2, "word": "冒険", "parked": True}]
    kept, back = connect.returning(cards, {"冒険": {}}, "ja", out={1})
    assert back == [2] and [c["card_id"] for c in kept] == [2]


def test_the_not_on_your_list_actions_pass_an_out_card_by_and_plan_out_tags_each_note_once():
    """§13 never also acts on an out card; `plan_out` suspends every out row and tags only notes not already carrying
    the tag (so Put back never takes off one you put there), under Junban's own tag parent."""
    _w, stats = plan.plan(_cards(1, 2, 3, 4), {"冒険": 0}, out={3, 4})
    order = stats["order"]
    later = unlisted.plan(order, {"冒険": {}}, "ja", {}, {}, {"tag": True, "flag": False, "suspend": True},
                          out={3: (7,), 4: (7,)})
    assert later["suspend"] == [2]
    notes = {503: {"tags": ["mine::OUT"]}, 504: {"tags": []}}
    out = unlisted.plan_out(order, {3: (7,), 4: (7,)}, notes, parent="Mine")
    assert (out["tag"], out["suspend"], out["tag_notes"], out["item_of"]) == ("Mine::out", [3, 4], [504],
                                                                              {3: (7,), 4: (7,)})
    assert unlisted.plan_out(order, {3: (7,), 4: (7,)}, notes)["tag"] == OUT_TAG
    assert unlisted.plan_out(order, {3: (7,)}, notes, exclude={3}) == {} and unlisted.plan_out(order, {}, notes) == {}


def test_the_record_names_only_what_was_asked_in_its_profile_under_every_item_claiming_it():
    """One card's suspend wasn't sent (its note's tag failed): the record names the card that was sent and the notes
    tagged — Put back restores what was changed, never more — in the profile named (TF fix 5), and a card two out
    items claim in both items' records (TF fix 7)."""
    out = {"item_of": {3: (7,), 4: (7,), 9: (7, 8)}, "note_of": {3: 503, 4: 504, 9: 509}, "tag": OUT_TAG}
    rows = pins.out_records(out, {"suspend": [3, 9], "tag": [503, 504, 509]}, profile="DevTest")
    assert rows == [(7, "cards_out", [503, 504, 509], {"queue": 0, "tagged": []},
                     {"queue": -1, "suspended": [3, 9], "tag": OUT_TAG, "tagged": [503, 504, 509],
                      "profile": "DevTest"}),
                    (8, "cards_out", [509], {"queue": 0, "tagged": []},
                     {"queue": -1, "suspended": [9], "tag": OUT_TAG, "tagged": [509], "profile": "DevTest"})]
    assert "profile" not in pins.out_records(out, {"suspend": [3], "tag": []})[0][4]
    assert pins.out_records(out, {"suspend": [], "tag": []}) == [] and pins.out_records({}, {"suspend": [3]}) == []


def test_record_hands_the_caller_to_the_store():
    """TF fix 10 (IK #12): the store's command records who wrote the record — the host's "replan", Connect's
    "connect"."""
    seen = []

    class Store:
        def record_anki_changes(self, rows, by):
            seen.append(("record", by))
            return [1]

        def mark_anki_reverted(self, ids, by):
            seen.append(("closed", by))
            return len(ids)
    assert pins.record(Store(), {"cards_out": [("row",)], "put_back": [4]}, by="replan") == ([1], 1)
    pins.record(Store(), {"cards_out": [("row",)]})
    assert seen == [("record", "replan"), ("closed", "replan"), ("record", "connect")]
