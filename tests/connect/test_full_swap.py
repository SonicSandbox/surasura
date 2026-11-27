"""FS-1, the full Swap (Connect; SCOPE.md § 8 — Sonic's decisions 1–15, 2026-11-23): a flagged card gets its new
sentence IN PLACE — the same note and cards, so its reviews, interval and due date stay — behind `swap_in_place`
(off in the tree until FS-2 lands its Settings row, the lead 2026-11-23: these tests turn it on, but the one that
holds the default off — with it, every swap is the simple Swap, as before FS-1).

What each test holds still:
- **the kind** (decided when the swap's job is made, decision 10): in place only for the loop's flag or the journey's
  ⇄, on a card Connect made (decision 6) whose sentence still holds Connect's line (decision 5); a *Bad card*
  (decision 11), the setting off, a card made by hand or changed by hand → a new card, said once;
- **the write** (the one field writer's replace mode): only the sentence side — the sentence, its audio and picture,
  the furigana emptied, the translation the new line's or the old one marked *（前の文）* (decision 2), the source
  field only while it holds Anki Miner's line (decision 4) — never the word, pitch, パターン / 例文, a ヒント, tags;
  the card's schedule untouched; back in reviews after a flag (decision 8), never taken out by a journey ⇄;
- **Undo:** every old value and the old media back, the card left in reviews; refused after a hand edit; twice:
  nothing more; the ledger's line of the card back to the old one (decision 15: *sentence from now*);
- **decision 15:** the card keeps its first job's tag and show tag (*first learned from*), and the ledger's newest
  made outcome of the note is its line now; its first in-place swap adds the episode it was first made from
  (`surasura::learned::<show>::s01e02`), never changed after, taken off by that swap's Undo — the learner's tags
  untouched.
What a wrong answer costs: a card that loses its reviews (the reason to swap), a learner's edit overwritten, a word's
side rewritten, an old clip lost for good, or an Undo that writes over the learner's own work.
Real Japanese and Chinese lines from tests/Test Resources (the simple Swap's CASES); the ledger is real; Anki is the
simple Swap's fake plus the field writer's calls; Anki Miner's `render` answers as its source writes it.
"""
import base64
import json
import os
import time

import pytest

from app import path_utils
from app.connect import (anki_miner, deleted, fields, library, media_names, runner, sentence_audio, shelf, swap,
                         swap_queue, tidy, undo)
from app.connect.ledger import SWAP
from tests.connect.test_kantan_sl_swap import CASES, Anki as SwapAnki, Steps, _lists, _queued, _row, ledger  # noqa: F401

FIRST_TAG = "surasura::connect::x-1"
SHOW_TAG = "Surasura::from::Toshokan"
MAPPING = fields.Mapping("日本語::Mining", "Lapis", {
    "word": "Word", "sentence": "Sentence", "audio": "SentenceAudio", "picture": "Picture",
    "sentence_furigana": "SentenceFurigana", "source": "MiscInfo", "pitch_position": "PitchPosition"},
    "Word", "Sentence", "MiscInfo", None, None)
IN_PLACE_ON = swap.in_place_on          # the real switch (the autouse fixture below turns the setting on)


class Anki(SwapAnki):
    """The simple Swap's fake, plus the one field writer's calls on the same notes (store, update, tag, read)."""

    def __init__(self):
        super().__init__()
        self.editor_open = set()

    def field_writer(self):
        return self

    def store(self, name, data):
        self.log.append(("store", name))
        self.media.setdefault(name, base64.b64decode(data))
        return name

    def update(self, nid, values):
        self.log.append(("update", int(nid), tuple(sorted(values))))
        if int(nid) in self.editor_open:
            return
        for k, v in values.items():
            self.notes_[int(nid)]["fields"][k]["value"] = v
        self.notes_[int(nid)]["mod"] = int(time.time())         # Anki's own: a note written is a note changed

    def tag(self, ids, tag, on=True):
        (self.add_tags if on else self.remove_tags)(ids, tag)

    def read_media(self, name):
        return self.media.get(name)

    def delete_media(self, name):
        self.log.append(("delete_media", name))
        self.media.pop(name, None)


def _card(anki, lang, note=900, reps=5, misc="Toshokan - 02 @ 00:17:27"):
    """A Connect card as Anki Miner + Backfill fill it (Lapis), studied `reps` times, suspended + green (the loop's
    move), its old clip and picture in Anki's media."""
    word, old, _other = CASES[lang]
    anki.add(note, FIRST_TAG, word, 1, cards=[{"reps": reps, "type": 2, "queue": -1, "flags": 3, "ivl": 21,
                                               "due": 830, "lapses": 1}])
    values = {"Word": word, "Sentence": old.replace(word, f"<b>{word}</b>"), "SentenceAudio": "[sound:sl-old.mp3]",
              "Picture": '<img src="sl-old.webp">', "SentenceFurigana": "AJTの色[いろ]", "Hint": "the old line's",
              "MiscInfo": misc, "PitchPosition": "2", "Patterns": "〜てもいい", "ExampleSentences": "例文",
              "IsSentenceCard": ""}
    anki.notes_[note]["fields"] = {k: {"value": v, "order": i} for i, (k, v) in enumerate(values.items())}
    anki.notes_[note]["tags"] = [FIRST_TAG, SHOW_TAG]
    anki.media["sl-old.mp3"], anki.media["sl-old.webp"] = b"ID3 old clip", b"RIFF old picture"
    return anki


def _made_by_connect(ledger, lang, note=900):
    word, old, _other = CASES[lang]
    job = ledger.queue(lang, 3, "user", None, store_id="s1")
    ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made", "note_id": note,
                                       "sentence": old}], deck=MAPPING.deck)
    ledger.set_state(job, "done")
    return job


def _rendered(tmp_path, lang, translation=""):
    """Anki Miner's `render` of the word on the other line: the whole note (the word's side too — never taken)."""
    word, _old, other = CASES[lang]
    clip, picture = tmp_path / "am-clip.mp3", tmp_path / "am-pic.webp"
    clip.write_bytes(b"ID3 " + other.encode("utf-8"))
    picture.write_bytes(b"RIFF new picture")
    values = {"Word": word + "（別）", "Sentence": other.replace(word, f"<b>{word}</b>"),
              "SentenceAudio": "[sound:am-clip.mp3]", "Picture": '<img src="am-pic.webp">',
              "SentenceFurigana": "", "MiscInfo": "Toshokan - 05 @ 00:03:10", "PitchPosition": "0",
              "Patterns": "", "Hint": translation}
    return {"fields": values, "files": [str(clip), str(picture)]}


def _to_job(ledger, lang, anki, monkeypatch):
    """The loop's green read into an ask, then the look that makes its job (the line picked: the other one)."""
    word, _old, other = CASES[lang]
    _lists(lang)
    entry = _queued(lang, word, card=9000, note=900)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, other))
    swap.look(Steps(), ledger, lang, store_id="s1", anki=anki, files=5)
    return entry, swap._rows(ledger, "language = ? AND ref = ?", (lang, entry["id"]))[-1]


def _job_made(ledger, row, note):
    """The swap job's batch ends as `runner._mine` ends it: its made outcome (the old note, for an in-place swap)."""
    word, _old, other = CASES[row["language"]]
    ledger.end_batch(row["job_id"], 1, "done", [{"word": row["word"], "reading": "", "outcome": "made",
                                                 "note_id": note, "sentence": other}], deck=MAPPING.deck)
    ledger.set_state(row["job_id"], "done")


def _value(anki, field, note=900):
    return anki.notes_[note]["fields"][field]["value"]


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setattr(swap, "_swap_flag", lambda: 3)       # the learner's Swap flag: green (the default)
    # *Same card, new sentence* on (the learner's pick: off in the tree until FS-2's row); a test that hands its own
    # settings reads them
    monkeypatch.setattr(swap, "in_place_on", lambda settings=None: IN_PLACE_ON(
        {swap.SETTING: True} if settings is None else settings))


# --------------------------------------------------------------------------- #
# The whole round: in place, back in reviews, Undo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_flagged_connect_card_gets_its_new_sentence_in_place_keeps_its_reviews_and_undo_puts_it_back(
        ledger, lang, tmp_path, monkeypatch):
    word, old, other = CASES[lang]
    anki = _card(Anki(), lang)
    first_job = _made_by_connect(ledger, lang)
    entry, row = _to_job(ledger, lang, anki, monkeypatch)
    assert (row["state"], row["kind"]) == (swap.QUEUED, swap.IN_PLACE)
    assert ledger.job_by_id(row["job_id"])["kind"] == SWAP
    assert swap.in_place_row(ledger, row["job_id"])["id"] == row["id"]
    before = dict(anki.cards_[9000])
    kind, note = swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, str(tmp_path / "kept"))
    assert (kind, note) == (swap.IN_PLACE, 900)
    _job_made(ledger, swap.in_place_row(ledger, row["job_id"]), 900)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = _row(ledger, row["id"])
    assert (row["state"], row["new_note"], row["kind"], row["tagged"]) == (swap.MADE, 900, swap.IN_PLACE, 1)
    assert [e for e in swap_queue.load(lang) if e["id"] == entry["id"]][0]["state"] == "made"
    # the sentence side is the new line's
    assert _value(anki, "Sentence") == other.replace(word, f"<b>{word}</b>")
    assert _value(anki, "SentenceAudio") == "[sound:am-clip.mp3]" and _value(anki, "Picture") == '<img src="am-pic.webp">'
    assert _value(anki, "SentenceFurigana") == ""                                  # AJT's colours of the old line
    assert _value(anki, "Hint") == swap.MARK + "the old line's"                    # decision 2: kept, marked
    assert _value(anki, "MiscInfo") == "Toshokan - 05 @ 00:03:10"                  # decision 4/15: from now
    # the word's side, pitch, パターン / 例文 and the card type: never written
    for name, value in (("Word", word), ("PitchPosition", "2"), ("Patterns", "〜てもいい"),
                        ("ExampleSentences", "例文"), ("IsSentenceCard", "")):
        assert _value(anki, name) == value
    # the card: its reviews, interval, due and lapses kept; back in your reviews, its green flag off (decision 8)
    card = anki.cards_[9000]
    assert {k: card[k] for k in ("reps", "ivl", "due", "lapses")} == {k: before[k] for k in ("reps", "ivl", "due",
                                                                                              "lapses")}
    assert (card["queue"], card["flags"]) == (0, 0)
    # decision 15: first learned from — the first job's tag and the show's stay; the line now — the ledger's newest
    assert {FIRST_TAG, SHOW_TAG, swap.SWAP_TAG} <= set(anki.notes_[900]["tags"])
    assert deleted._made(ledger.conn, lang, 900)[2] == other
    assert ledger.outcomes(first_job)[0]["outcome"] == "made"                       # never overwritten
    # the old clip and picture: kept on disk first, then gone from Anki (no other note names them)
    assert "sl-old.mp3" not in anki.media and "sl-old.webp" not in anki.media
    assert swap.status_of(ledger.conn, lang)["made"][0]["kind"] == swap.IN_PLACE
    # Undo: the old sentence side back, the old media stored again, the card left in reviews
    got = swap.undo(anki, ledger, lang, row["id"])
    assert got == {"undone": True, "word": word, "kind": swap.IN_PLACE}
    assert _value(anki, "Sentence") == old.replace(word, f"<b>{word}</b>")
    assert _value(anki, "SentenceFurigana") == "AJTの色[いろ]" and _value(anki, "Hint") == "the old line's"
    assert _value(anki, "MiscInfo") == "Toshokan - 02 @ 00:17:27"
    assert anki.media["sl-old.mp3"] == b"ID3 old clip" and "am-clip.mp3" not in anki.media
    assert swap.SWAP_TAG not in anki.notes_[900]["tags"] and anki.cards_[9000]["queue"] == 0
    assert deleted._made(ledger.conn, lang, 900)[2] == old                         # the card's line is its old one
    assert [e for e in swap_queue.load(lang) if e["id"] == entry["id"]][0]["state"] == "undone"
    with pytest.raises(tidy.Refused) as twice:
        swap.undo(anki, ledger, lang, row["id"])
    assert twice.value.say == swap.ALREADY


class _Store:
    """The library store as `learned_tag` reads it: an item's file, its show's title and its record."""

    def __init__(self, rel_path, title=None, record=None):
        self.rel_path, self.title, self.record = rel_path, title, record or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def item(self, item_id):
        return {"id": item_id, "rel_path": self.rel_path}

    def _show_record(self, item_id):
        return self.record


@pytest.fixture
def _titles(monkeypatch):
    monkeypatch.setattr(library, "show_title", lambda store, item_id: store.title)


@pytest.mark.parametrize("store, tag", [
    (_Store("Toshokan/Toshokan - 02.mkv", "Toshokan"), "surasura::learned::toshokan::s01e02"),
    (_Store("ゆるキャン△/Season 02/ゆるキャン△ S02E03.mkv", "ゆるキャン△ SEASON２"),
     "surasura::learned::ゆるキャン△_season２::s02e03"),
    (_Store("hato/abc.mkv", "Hibike! Euphonium 3", {"show": {"season": 3, "episode": 4}}),
     "surasura::learned::hibike!_euphonium_3::s03e04"),      # hato's record names the place: it wins
    (_Store("甄嬛传/甄嬛传 第05集.mp4", "甄嬛传"), "surasura::learned::甄嬛传::s01e05"),
    (_Store("三体.epub"), "surasura::learned::三体"),           # a book: no place in a show, no show — its name
    (_Store("Toshokan/Toshokan - 12.5.mkv", "Toshokan", {"show": {"episode": 12.5}}),
     "surasura::learned::toshokan::s01e12.5"),
])
def test_the_first_episode_tag_names_the_show_and_episode_as_connect_names_them(ledger, _titles, store, tag):
    """Decision 15's tag (PROVISIONAL): the show in its `Surasura::from::` form, lowercase, the episode as Connect
    places it in its show — from the item the card was FIRST made from (the note's first made outcome), never the
    swap's."""
    _made_by_connect(ledger, "ja")
    swap_job = ledger.queue("ja", 8, "user", None, store_id="s1")
    ledger.end_batch(swap_job, 1, "done", [{"word": "w", "reading": "", "outcome": "made", "note_id": 900,
                                            "sentence": "新しい行"}], deck=MAPPING.deck)
    seen = []

    def open_store():
        seen.append(1)
        return store
    assert swap.learned_tag(ledger, 900, open_store) == tag
    assert seen == [1]


def test_the_first_episode_tag_is_none_when_nothing_can_say_it(ledger, _titles):
    assert swap.learned_tag(ledger, 900, lambda: _Store("a.mkv", "A")) is None      # no card made of that note
    _made_by_connect(ledger, "ja")
    assert swap.learned_tag(ledger, 900, None) is None

    def busy():
        raise runner.Wait(runner.LIBRARY_BUSY)
    assert swap.learned_tag(ledger, 900, busy) is None                  # the store busy: no tag, never a wrong one
    assert swap.learned_tag(ledger, 900, lambda: _Store("", None)) is None


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_first_in_place_swap_adds_the_first_episode_tag_once_and_its_undo_takes_it_off(
        ledger, lang, tmp_path, monkeypatch):
    learned = "surasura::learned::toshokan::s01e02"
    anki = _card(Anki(), lang)
    anki.notes_[900]["tags"].append("my_own")
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, str(tmp_path / "kept"),
                               learned=learned) == (swap.IN_PLACE, 900)
    assert set(anki.notes_[900]["tags"]) == {FIRST_TAG, SHOW_TAG, "my_own", swap.SWAP_TAG, learned}
    row = _row(ledger, row["id"])
    # never changed after: a later in-place swap of the card finds the first standing (and the tag on)
    later = dict(row, id=row["id"] + 1000)
    assert not swap._first_in_place(ledger, later, anki.notes_[900])
    assert not swap._first_in_place(ledger, later, {"tags": []})          # the first swap stands
    assert not swap._first_in_place(ledger, row, anki.notes_[900])        # the tag on: never a second one
    _job_made(ledger, swap.in_place_row(ledger, row["job_id"]), 900)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    swap.undo(anki, ledger, lang, row["id"])
    assert set(anki.notes_[900]["tags"]) == {FIRST_TAG, SHOW_TAG, "my_own"}   # the learner's tags untouched
    assert swap._first_in_place(ledger, later, anki.notes_[900])           # undone: the next swap is the first


def test_a_card_already_holding_a_first_episode_tag_keeps_it_and_its_undo_leaves_it(ledger, tmp_path, monkeypatch):
    """The tag is written once: a card that has one (its first swap's, kept by the learner after a hand fix, or one
    the learner wrote) gets no second, and this swap's Undo never takes off what it didn't put on."""
    anki = _card(Anki(), "ja")
    anki.notes_[900]["tags"].append("surasura::learned::toshokan::s01e01")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja"), MAPPING, str(tmp_path / "kept"),
                        learned="surasura::learned::toshokan::s01e02")
    tags = [t for t in anki.notes_[900]["tags"] if t.startswith(swap.LEARNED_PREFIX)]
    assert tags == ["surasura::learned::toshokan::s01e01"]
    _job_made(ledger, swap.in_place_row(ledger, row["job_id"]), 900)
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    swap.undo(anki, ledger, "ja", row["id"])
    assert "surasura::learned::toshokan::s01e01" in anki.notes_[900]["tags"]


def test_a_journey_swap_in_place_never_takes_the_card_out_of_reviews(ledger, tmp_path, monkeypatch):
    lang = "ja"
    anki = _card(Anki(), lang)
    anki.cards_[9000].update(queue=2, flags=0)                       # in reviews, unflagged: the page's ⇄
    _made_by_connect(ledger, lang)
    got = swap.make_card(lang, CASES[lang][0], old_note=900, old_card=9000, by=swap.BY_JOURNEY, ledger=ledger,
                         wake=False, state_of=lambda w, r: None)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, CASES[lang][2]))
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = _row(ledger, got["id"])
    assert row["kind"] == swap.IN_PLACE
    swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, str(tmp_path / "kept"))
    _job_made(ledger, _row(ledger, got["id"]), 900)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert _row(ledger, got["id"])["state"] == swap.MADE
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (2, 0)
    assert not [e for e in anki.log if e[0] in ("suspend", "unsuspend", "set_flag")]


# --------------------------------------------------------------------------- #
# The kind: who gets a new card instead
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_whose_sentence_was_changed_by_hand_gets_a_new_card_said_once(ledger, lang, monkeypatch):
    anki = _card(Anki(), lang)
    anki.notes_[900]["fields"]["Sentence"]["value"] = "自分で書き直した文です。"
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    assert (row["kind"], row["kind_why"], row["why"]) == (swap.NEW_CARD, swap.HAND_EDITED, None)


def test_a_card_connect_did_not_make_is_never_rewritten(ledger, monkeypatch):
    anki = _card(Anki(), "ja")                                       # flagged green, but mined by hand
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    assert (row["kind"], row["kind_why"]) == (swap.NEW_CARD, swap.NOT_CONNECTS)


def test_the_setting_off_and_a_bad_card_make_a_new_card(ledger, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    with monkeypatch.context() as patched:
        patched.setattr(swap, "in_place_on", lambda settings=None: False)
        _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    assert row["kind"] == swap.NEW_CARD
    bad = {"by": swap.BY_BAD_CARD, "old_note": 900}
    assert swap._kind_of(ledger, bad, anki) == (swap.NEW_CARD, None)


def test_a_swap_waiting_when_the_setting_is_switched_follows_it_when_its_job_is_made(ledger, monkeypatch):
    """Decision 10: the ask was made while *Same card* was on; switched to *A new card* before Connect's look: the job
    made then is a new card's (nothing redone for swaps already made)."""
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    swap.make_card("ja", CASES["ja"][0], old_note=900, old_card=9000, ledger=ledger, wake=False,
                   state_of=lambda w, r: None)
    assert IN_PLACE_ON({"swap_in_place": True}) and not IN_PLACE_ON({"swap_in_place": False})
    assert IN_PLACE_ON({}) and IN_PLACE_ON({"swap_in_place": "yes"})        # anything else: the default, on (decision 1)
    monkeypatch.setattr(swap, "in_place_on", lambda settings=None: False)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, CASES["ja"][2]))
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    assert swap._rows(ledger, "language = ?", ("ja",))[-1]["kind"] == swap.NEW_CARD


def test_the_shipped_default_rewrites_a_flagged_connect_card_in_place(ledger):
    """Decision 1 (FS-2's flip): *Same card, new sentence* is the default, so with the settings as shipped a flagged
    card Connect made — its sentence still Connect's line — is a swap in place."""
    from app import settings_manager
    assert settings_manager.DEFAULT_SETTINGS[swap.SETTING] is True and IN_PLACE_ON() is True
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    assert swap._kind_of(ledger, {"by": swap.BY_SWAP, "old_note": 900}, anki) == (swap.IN_PLACE, None)
    assert swap._kind_of(ledger, {"by": swap.BY_JOURNEY, "old_note": 900}, anki) == (swap.IN_PLACE, None)


def test_with_a_new_card_picked_every_swap_is_the_simple_swap_as_before(ledger, tmp_path, monkeypatch):
    """*A new card* (the learner's pick): a flagged card Connect made — the one card the full Swap rewrites — gets
    the simple Swap's new card: its job mines (nothing rendered, nothing written over), nothing is handed to the
    record or to Backfill as rewritten, and the old card keeps every field and tag but the simple Swap's own."""
    monkeypatch.setattr(swap, "in_place_on", lambda settings=None: IN_PLACE_ON({swap.SETTING: False}))
    anki = _card(Anki(), "ja")
    anki.notes_[900]["tags"].append("my_own")
    fields_before = {k: dict(v) for k, v in anki.notes_[900]["fields"].items()}
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    assert (row["kind"], row["kind_why"]) == (swap.NEW_CARD, None)
    assert swap.in_place_row(ledger, row["job_id"]) is None
    job = ledger.job_by_id(row["job_id"])
    calls = []

    class S:
        def swap_in_place(self, *a):
            calls.append("in place")

        def mine(self, *a):
            calls.append("mine")
            return {"outcomes": []}
    monkeypatch.setattr(runner, "_part_read", lambda *a: {})
    runner._mine_batch(S(), ledger, "ja", job, {}, [], 1)
    assert calls == ["mine"]
    _job_made(ledger, row, 901)                                     # the simple Swap's new card
    assert runner._rewritten(ledger, job) == [] and swap.rewritten(ledger, row["job_id"]) == []
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    row = _row(ledger, row["id"])
    assert (row["state"], row["new_note"], row["kind"], row["wrote"]) == (swap.MADE, 901, swap.NEW_CARD, None)
    assert anki.notes_[900]["fields"] == fields_before
    assert set(anki.notes_[900]["tags"]) == {FIRST_TAG, SHOW_TAG, "my_own", swap.SWAP_TAG}
    assert not any(op[0] in ("update", "store", "delete_media") for op in anki.log)


def test_anki_unreadable_at_the_look_decides_nothing(ledger, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")

    def gone(ids):
        raise OSError("Anki stopped answering")
    anki.notes = gone
    assert swap._kind_of(ledger, {"by": swap.BY_SWAP, "old_note": 900}, anki) == (None, None)


# --------------------------------------------------------------------------- #
# The write's own rules
# --------------------------------------------------------------------------- #
def test_a_hand_edit_between_the_look_and_the_write_falls_back_to_a_new_card(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    anki.notes_[900]["fields"]["Sentence"]["value"] = "電話で直した。"
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja"), MAPPING, str(tmp_path / "k")) == (
        swap.NEW_CARD, swap.HAND_EDITED)
    assert not [e for e in anki.log if e[0] == "update"]


def test_a_source_field_holding_a_hint_and_a_rendered_translation(ledger, tmp_path, monkeypatch):
    """The source field holds the learner's ヒント, not Anki Miner's line: kept (decision 4). The new line comes with
    its own translation (a second subtitle track): it replaces the old one, no mark."""
    anki = _card(Anki(), "ja", misc="借りる＝to borrow（自分のメモ）")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja", translation="May I borrow a pen?"), MAPPING,
                        str(tmp_path / "k"))
    assert _value(anki, "MiscInfo") == "借りる＝to borrow（自分のメモ）"
    assert _value(anki, "Hint") == "May I borrow a pen?"


def test_a_book_line_with_no_audio_or_picture_empties_them(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    book = _rendered(tmp_path, "ja")
    book["fields"].update(SentenceAudio="", Picture="")
    book["files"] = []
    swap.write_in_place(anki, ledger, row, book, MAPPING, str(tmp_path / "k"))
    assert _value(anki, "SentenceAudio") == "" and _value(anki, "Picture") == ""


def test_a_card_open_in_ankis_editor_is_asked_again_never_a_new_card(ledger, tmp_path, monkeypatch):
    """The write read back unchanged (Anki's editor keeps its own copy): no card made, the swap still in place and
    queued — the runner's batch waits (`Wait`) and renders the same line again at the next look."""
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    anki.editor_open.add(900)
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja"), MAPPING, str(tmp_path / "k")) == (
        None, swap.NOT_APPLIED)
    row = _row(ledger, row["id"])
    assert (row["state"], row["kind"], row["wrote"]) == (swap.QUEUED, swap.IN_PLACE, None)
    assert "sl-old.mp3" in anki.media


def test_undo_after_a_hand_edit_is_refused_and_changes_nothing(ledger, tmp_path, monkeypatch):
    anki = _card(Anki(), "ja")
    _made_by_connect(ledger, "ja")
    _entry, row = _to_job(ledger, "ja", anki, monkeypatch)
    swap.write_in_place(anki, ledger, row, _rendered(tmp_path, "ja"), MAPPING, str(tmp_path / "k"))
    _job_made(ledger, _row(ledger, row["id"]), 900)
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    anki.notes_[900]["fields"]["Sentence"]["value"] = "直した。"
    with pytest.raises(tidy.Refused) as e:
        swap.undo(anki, ledger, "ja", row["id"])
    assert e.value.say == swap.CHANGED
    assert _value(anki, "Sentence") == "直した。" and _row(ledger, row["id"])["state"] == swap.MADE


# --------------------------------------------------------------------------- #
# The runner and Anki Miner's render
# --------------------------------------------------------------------------- #
def test_the_swap_jobs_batch_renders_in_place_and_falls_back_to_mining_when_it_cant(ledger, monkeypatch):
    calls = []

    class S:
        def swap_in_place(self, lang, job, picked, words, attempt, ledger_, row):
            calls.append(("in place", row["id"]))
            return self.answer

        def mine(self, lang, job, picked, words, attempt):
            calls.append(("mine",))
            return {"outcomes": []}
    steps = S()
    monkeypatch.setattr(runner, "_part_read", lambda *a: {})
    monkeypatch.setattr(swap, "in_place_row", lambda l, j: {"id": 4})
    steps.answer = {"outcomes": ["made"]}
    assert runner._mine_batch(steps, ledger, "ja", {"id": 1, "kind": SWAP}, {}, [], 1) == {"outcomes": ["made"]}
    steps.answer = None                                              # it can't be rewritten: a new card
    assert runner._mine_batch(steps, ledger, "ja", {"id": 1, "kind": SWAP}, {}, [], 1) == {"outcomes": []}
    runner._mine_batch(steps, ledger, "ja", {"id": 2, "kind": "level"}, {}, [], 1)
    assert calls == [("in place", 4), ("in place", 4), ("mine",), ("mine",)]


def test_render_line_reads_render_rows_and_needs_render(tmp_path, monkeypatch):
    """Anki Miner's `render` (its source: `runs.py` writes `render-NNN.json`, rows with `fields` and `files` inside the
    run folder): the word's note read back; an Anki Miner without `render` (Z-10) → `no-render` (a new card)."""
    word, _old, other = CASES["ja"]
    run_dir = tmp_path / "run"
    sent = []

    def api(path, args, timeout=None, **_k):
        sent.append(args[0])
        run_id = "j7-1"
        folder = run_dir / run_id
        (folder / "render-001").mkdir(parents=True)
        (folder / "render-001" / "am-clip.mp3").write_bytes(b"ID3")
        (folder / "render-001.json").write_text(json.dumps({"words": [
            {"word": word, "mined_form": word, "status": "rendered", "line_start": 12.5,
             "fields": {"Sentence": other, "SentenceAudio": "[sound:am-clip.mp3]"},
             "files": ["render-001/am-clip.mp3"]}]}, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "runs": [{"run_id": run_id, "ok": True, "file": "render-001.json"}]}
    info = {"app": "3.12.0", "features": ["render", "media"]}
    monkeypatch.setattr(anki_miner, "preflight", lambda *a, **k: (info, "p1"))
    monkeypatch.setattr(anki_miner, "api", api)
    words = [{"word": word, "reading": "", "line_start": 12.5, "line_expansion": [0, 0], "sent": [word]}]
    got = anki_miner.render_line("am.exe", "ja", "j7", "ep.mkv", "ep.ass", words, MAPPING, "Surasura", str(run_dir))
    assert sent == ["render"]
    assert got[(word, "")]["fields"]["Sentence"] == other
    assert got[(word, "")]["files"] == [os.path.join(str(run_dir), "j7-1", "render-001", "am-clip.mp3")]
    info["features"] = ["media"]
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        anki_miner.render_line("am.exe", "ja", "j7", "ep.mkv", "ep.ass", words, MAPPING, "Surasura", str(run_dir))
    assert e.value.kind == "no-render"


def test_the_field_writers_adapter_is_swaps_for_its_in_place_write():
    assert isinstance(swap.AnkiSwap("http://127.0.0.1:8765").field_writer(), sentence_audio.AnkiConnectNotes)


# --------------------------------------------------------------------------- #
# The gates session's five gaps (FS-1 G, 2026-11-23)
# --------------------------------------------------------------------------- #
def _swapped(ledger, lang, tmp_path, monkeypatch):
    """The whole in-place round up to *made* (the first test's) -> (anki, the first job, the swap's row)."""
    anki = _card(Anki(), lang)
    first_job = _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    kind, _note = swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, swap.kept_folder())
    assert kind == swap.IN_PLACE
    _job_made(ledger, swap.in_place_row(ledger, row["job_id"]), 900)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    return anki, first_job, _row(ledger, row["id"])


class _Now:
    """`path_utils.cleanup_trash_async`'s thread, run at once: the purge's result read right after the look."""

    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_kept_clip_and_picture_go_30_days_on_and_undo_then_says_too_old(ledger, lang, tmp_path, monkeypatch):
    """Decision 7: the old clip and picture an in-place swap removed from Anki are kept on disk 30 days (the trash
    clock's rule and its one purge), then Undo says *too old to undo* and writes nothing — never half an Undo (the old
    sentence with no clip to play). 29 days on they are still there. Costs if wrong: copies kept for ever, or an Undo
    that puts the old sentence back over a clip that is gone."""
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    monkeypatch.setattr(path_utils.threading, "Thread", _Now)
    monkeypatch.setattr(swap, "PURGE_EVERY_S", 0)          # the look's own pace (twice a day) is the next test's
    monkeypatch.setattr(swap, "_PURGED", {})
    anki, _first, row = _swapped(ledger, lang, tmp_path, monkeypatch)
    kept = [os.path.join(r, f) for r, _d, files in os.walk(tmp_path / "swap-kept") for f in files]
    assert sorted(os.path.basename(k) for k in kept) == ["sl-old.mp3", "sl-old.webp"]

    def age(days):
        then = time.time() - days * 24 * 60 * 60
        for path in kept:
            os.utime(path, (then, then))
    age(29)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert all(os.path.isfile(k) for k in kept)
    age(31)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert not any(os.path.exists(k) for k in kept)
    with pytest.raises(tidy.Refused) as e:
        swap.undo(anki, ledger, lang, row["id"])
    assert e.value.say == swap.TOO_OLD
    word, _old, other = CASES[lang]
    assert _value(anki, "Sentence") == other.replace(word, f"<b>{word}</b>")       # nothing put back by halves
    assert _row(ledger, row["id"])["state"] == swap.MADE


def test_undo_this_batch_never_deletes_a_card_a_swap_rewrote_in_place(ledger, tmp_path, monkeypatch):
    """*Undo this batch* deletes a batch's untouched new cards. A card rewritten in place is the learner's card from
    its FIRST job (it still carries that job's tag) — here a journey ⇄ on a card never studied, the one case the
    review check doesn't keep. Its first job's Undo keeps it (changed since: the swap wrote it), and the swap job's
    keeps it (it never carries the swap job's tag). Costs if wrong: the learner's card deleted."""
    lang = "ja"
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    anki = _card(Anki(), lang, reps=0)
    anki.cards_[9000].update(queue=0, type=0, flags=0)                # new, in reviews: the page's ⇄
    first = _made_by_connect(ledger, lang)
    an_hour_ago = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    ledger.conn.execute("UPDATE jobs SET updated_at = ? WHERE id = ?", (an_hour_ago, first))
    from app.connect import runfile
    anki.notes_[900]["tags"] = [runfile.job_tag(ledger.job_by_id(first)["tag"]), SHOW_TAG]   # the first job's own
    got = swap.make_card(lang, CASES[lang][0], old_note=900, old_card=9000, by=swap.BY_JOURNEY, ledger=ledger,
                         wake=False, state_of=lambda w, r: None)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: (7, CASES[lang][2]))
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    row = _row(ledger, got["id"])
    assert row["kind"] == swap.IN_PLACE
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, swap.kept_folder())[0] == \
        swap.IN_PLACE
    _job_made(ledger, swap.in_place_row(ledger, row["job_id"]), 900)
    first_plan = undo.plan(anki, ledger, first)
    assert first_plan["delete"] == [] and first_plan["keep"] == [[900, CASES[lang][0], undo.CHANGED]]
    swap_plan = undo.plan(anki, ledger, row["job_id"])
    assert swap_plan["delete"] == [] and swap_plan["keep"] == [[900, row["word"], undo.NOT_ITS_TAG]]


def test_the_swap_jobs_record_holds_the_card_under_its_new_episode_alone():
    """The store's made words (N15): a card rewritten in place shows the swap's line now, so the swap job's record puts
    it under that item and takes it out of its first item's — one note, one item (the shelf's finished-show check, Add
    audio's book and the translations read a note's item) — while the word stays made there (G1.3-4: never made
    again; the first item's receipt untouched). Undo moves it back (`swap._store_back`'s call). Costs if wrong: a card
    whose sentence is now from a show you watch shelved as a finished show's, or given another book's audio."""
    from tests import connect_helpers as c
    word = CASES["ja"][0]
    c.library()
    with c.store() as s:
        first, second = s.ids("now")[:2]
        library.record_batch(s, first, {word: [900], "見る": [901]}, "2026-11-20T09:00:00Z", batch="a")
        receipt = s.item(first).get("mined_at")
        library.record_batch(s, second, {word: [900]}, None, batch="b", moved=[900])
        assert shelf.made_notes(s)[900] == (second, word) and shelf.made_notes(s)[901] == (first, "見る")
        rows = {(i, w): json.loads(n) for i, w, n in s.conn.execute("SELECT item_id, word, note_ids FROM made_words")}
        assert rows[(first, word)] == [] and rows[(second, word)] == [900]
        assert word in library.made_words_all(s) and s.item(first).get("mined_at") == receipt
        made_at = s.conn.execute("SELECT made_at FROM made_words WHERE item_id = ? AND word = ?",
                                 (first, word)).fetchone()[0]
        library.record_batch(s, first, {word: [900]}, None, batch=None, moved=[900])
        assert shelf.made_notes(s)[900] == (first, word)
        rows = {(i, w): json.loads(n) for i, w, n in s.conn.execute("SELECT item_id, word, note_ids FROM made_words")}
        assert rows[(second, word)] == [] and rows[(first, word)] == [900]
        # refuter R10: the move back keeps the word's first date (the words list orders by it): no card was made
        assert s.conn.execute("SELECT made_at FROM made_words WHERE item_id = ? AND word = ?",
                              (first, word)).fetchone()[0] == made_at == "2026-11-20T09:00:00Z"


def test_an_undone_in_place_swap_moves_its_record_back_to_the_line_it_shows(ledger, tmp_path, monkeypatch):
    """`_store_back`: after the Undo the card's newest made outcome is its first job's again, so the store's record goes
    back to that job's item — the store asked once, the note taken out of the swap job's item."""
    lang = "ja"
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    anki, first, row = _swapped(ledger, lang, tmp_path, monkeypatch)
    calls = []

    class Store:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(library, "record_batch", lambda *a, **k: calls.append((a[1:], k)))
    assert swap.undo(anki, ledger, lang, row["id"], open_store=Store)["undone"]
    assert calls == [((ledger.job_by_id(first)["item_id"], {CASES[lang][0]: [900]}, None, ledger.tag_id(first)),
                      {"moved": [900]})]                              # the first job's batch, as its record named it


def test_the_runner_hands_a_rewritten_card_to_the_record_and_to_backfill(ledger, tmp_path, monkeypatch):
    """The swap job's record and Backfill's fill name the card it rewrote (`swap.rewritten`): the record moves it
    (above), Backfill fills its new line's ふりがな though it is studied (Junban's own test). The first job: neither."""
    lang = "ja"
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    _anki, first, row = _swapped(ledger, lang, tmp_path, monkeypatch)
    job = ledger.job_by_id(row["job_id"])
    assert runner._rewritten(ledger, job) == [900] and runner._rewritten(ledger, ledger.job_by_id(first)) == []
    seen = {}

    class S:
        def record(self, lang_, job_, made, mined_at, batch, moved=()):
            seen["record"] = (made, mined_at, list(moved))

        def fill(self, lang_, job_, ids, rewritten=()):
            seen["fill"] = (list(ids), list(rewritten))
    monkeypatch.setattr(runner, "_through", lambda *a: None)
    monkeypatch.setattr(runner, "_blocked", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_circle_paused", lambda *a: False)
    monkeypatch.setattr(runner, "_queue_sound", lambda *a: None)
    monkeypatch.setattr(ledger, "undo_record", lambda jid: [900])
    runner._record_made(S(), ledger, lang, job, True)
    runner._fill(S(), ledger, lang, job)
    assert seen == {"record": ({row["word"]: [900]}, None, [900]), "fill": ([900], [900])}


def test_the_swapped_cards_media_are_named_by_the_line_before_the_write_so_its_undo_still_works(
        ledger, tmp_path, monkeypatch):
    """Connect names every card's clip and picture by its line after mining (`media_names.rename`, `sl-…`). An
    in-place write is undone only while the card holds exactly what it wrote — so a rename after the write made every
    in-place Undo refuse. The swap's step names render's files by the line BEFORE the write (`media_names.by_line`,
    the same names): the rename after finds nothing to do, and Undo works. No line start: render's names kept."""
    lang = "ja"
    word, old, other = CASES[lang]
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    anki = _card(Anki(), lang)
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    rendered = _rendered(tmp_path, lang)
    from app.cli import verbs
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "am.exe")
    monkeypatch.setattr(anki_miner, "render_line", lambda *a, **k: {(word, ""): rendered})
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda *a, **k: ({}, "p1", MAPPING))
    monkeypatch.setattr(swap, "AnkiSwap", lambda url: anki)
    steps = runner.Steps({"connect_enabled": True})
    monkeypatch.setattr(steps, "run_dir", lambda job: str(tmp_path / "run"))
    monkeypatch.setattr(steps, "_anki_miner_held", lambda l: {})
    monkeypatch.setattr(steps, "_settings", lambda l: {})
    monkeypatch.setattr(steps, "show", lambda l, j: None)
    monkeypatch.setattr(steps, "_media_key", lambda l, j: "toshokan-05")
    picked = {"video": "Toshokan - 05.mkv", "subtitle": "Toshokan - 05.ass"}
    words = [{"word": word, "reading": "", "line_start": 190.0, "line_end": 193.5, "line_text": other}]
    job = ledger.job_by_id(row["job_id"])
    done = steps.swap_in_place(lang, job, picked, words, 1, ledger, swap.in_place_row(ledger, row["job_id"]))
    assert done["in_place"] and done["outcomes"][0]["note_id"] == 900
    clip = media_names.line_name("toshokan-05", 190.0, 193.5, media_names.fingerprint(other), ".mp3")
    assert _value(anki, "SentenceAudio") == f"[sound:{clip}]" and clip in anki.media
    assert _value(anki, "Picture").startswith('<img src="sl-') and "am-clip.mp3" not in anki.media
    from tests.connect.test_media_names import FakeMedia
    media = FakeMedia([anki.notes_[900]], anki.media)
    assert media_names.rename(media, [(900, 190.0, 193.5, other)], "toshokan-05", "SentenceAudio", "Picture") == \
        {"renamed": 0, "stored": 0, "reused": 0, "deleted": 0}
    _job_made(ledger, swap.in_place_row(ledger, row["job_id"]), 900)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert swap.undo(anki, ledger, lang, row["id"])["undone"]
    assert _value(anki, "Sentence") == old.replace(word, f"<b>{word}</b>")
    values, named = media_names.by_line(rendered["fields"], {"am-clip.mp3": "x"}, "k", None, None, other,
                                        "SentenceAudio", "Picture")
    assert values == rendered["fields"] and named == {"am-clip.mp3": "x"}


# --------------------------------------------------------------------------- #
# The review's fixes (FS-1 G, 2026-11-23: Haiku lenses + own read)
# --------------------------------------------------------------------------- #
def test_a_write_stopped_after_ankis_update_is_settled_when_tried_again_never_called_a_hand_edit(
        ledger, tmp_path, monkeypatch):
    """The note written, then Anki failing on the tag: the record stays `writing`. Before: the retry read the card's
    new sentence as a hand edit and made a new card, the half write never undoable. Now the swap keeps the record's
    id, the retry puts the half write back first (`sentence_audio.settle`) and writes again: one in-place swap, its
    Undo whole."""
    from app import anki_connect
    lang = "ja"
    word, old, other = CASES[lang]
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    anki = _card(Anki(), lang)
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    real_tag = anki.tag
    fail = {"once": True}

    def tag(ids, t, on=True):
        if fail.pop("once", False):
            raise anki_connect.AnkiError("Anki stopped answering")
        return real_tag(ids, t, on)
    monkeypatch.setattr(anki, "tag", tag)
    with pytest.raises(anki_connect.AnkiError):
        swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, swap.kept_folder())
    assert _value(anki, "Sentence") == other.replace(word, f"<b>{word}</b>")      # the half write
    row = swap.in_place_row(ledger, row["job_id"])
    first = row["wrote"]
    assert sentence_audio.record(ledger, first)["state"] == sentence_audio.WRITING
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, swap.kept_folder()) == \
        (swap.IN_PLACE, 900)
    assert sentence_audio.record(ledger, first)["state"] == sentence_audio.UNDONE
    row = swap.in_place_row(ledger, row["job_id"])
    assert row["wrote"] != first and swap.SWAP_TAG in anki.notes_[900]["tags"]
    _job_made(ledger, row, 900)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert swap.undo(anki, ledger, lang, row["id"])["undone"]
    assert _value(anki, "Sentence") == old.replace(word, f"<b>{word}</b>")
    assert anki.media["sl-old.mp3"] == b"ID3 old clip"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_undo_after_backfill_refilled_the_new_lines_furigana_puts_the_old_card_back(ledger, lang, tmp_path,
                                                                                     monkeypatch):
    """The swap empties the sentence furigana and the same job's Backfill refills it for the new line (`run_named`'s
    `rewritten`). Before: Undo read that fill as the learner's edit — every in-place Undo of a card with a furigana
    field refused. Now the furigana is the writer's `loose` field: put back with the old line, never read as an edit;
    a real edit of the sentence still refuses."""
    word, old, other = CASES[lang]
    anki, _first, row = _swapped(ledger, lang, tmp_path, monkeypatch)
    anki.notes_[900]["fields"]["SentenceFurigana"]["value"] = "新[あたら]しい 行[ぎょう]"       # Backfill's fill
    assert swap.undo(anki, ledger, lang, row["id"])["undone"]
    assert _value(anki, "Sentence") == old.replace(word, f"<b>{word}</b>")
    assert _value(anki, "SentenceFurigana") == "AJTの色[いろ]"


def test_undo_after_backfill_still_refuses_a_hand_edit_of_the_new_sentence(ledger, tmp_path, monkeypatch):
    anki, _first, row = _swapped(ledger, "ja", tmp_path, monkeypatch)
    anki.notes_[900]["fields"]["SentenceFurigana"]["value"] = "新[あたら]しい"
    anki.notes_[900]["fields"]["Sentence"]["value"] += "（直した）"
    with pytest.raises(tidy.Refused) as refused:
        swap.undo(anki, ledger, "ja", row["id"])
    assert refused.value.say == swap.CHANGED
    assert _value(anki, "SentenceFurigana") == "新[あたら]しい"                        # nothing changed


def test_the_swap_names_its_write_before_anki_is_touched_so_a_kill_anywhere_after_is_settled(
        ledger, tmp_path, monkeypatch):
    """Refuter R1: the swap kept the record's id only when `replace` raised or returned — a kill of the app after
    Anki's update (or the record's last write failing) left the row without it, and the retry read the card's new
    sentence as a hand edit: a new card, the half write undoable by nobody. Now the row names the record the moment
    it is written, before Anki is touched."""
    lang = "ja"
    anki = _card(Anki(), lang)
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    seen = []
    real_update = anki.update

    def update(nid, values):
        seen.append(_row(ledger, row["id"])["wrote"])
        return real_update(nid, values)
    monkeypatch.setattr(anki, "update", update)
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, str(tmp_path / "kept")) == \
        (swap.IN_PLACE, 900)
    wrote = _row(ledger, row["id"])["wrote"]
    assert seen == [wrote] and wrote


def test_an_undo_stopped_after_its_write_finishes_when_pressed_again(ledger, tmp_path, monkeypatch):
    """Undo's write landed, then Anki failed taking the tag off: before, every later Undo read the card as changed
    since and refused for good. A card already holding its old values now counts as put back: the second press
    finishes (the tag off, the swap undone)."""
    from app import anki_connect
    lang = "ja"
    word, old, _other = CASES[lang]
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    anki, _first, row = _swapped(ledger, lang, tmp_path, monkeypatch)
    real_tag = anki.tag
    fail = {"once": True}

    def tag(ids, t, on=True):
        if not on and fail.pop("once", False):
            raise anki_connect.AnkiError("Anki stopped answering")
        return real_tag(ids, t, on)
    monkeypatch.setattr(anki, "tag", tag)
    with pytest.raises(anki_connect.AnkiError):
        swap.undo(anki, ledger, lang, row["id"])
    assert _value(anki, "Sentence") == old.replace(word, f"<b>{word}</b>")
    assert swap.undo(anki, ledger, lang, row["id"])["undone"]
    assert swap.SWAP_TAG not in anki.notes_[900]["tags"] and _row(ledger, row["id"])["state"] == swap.UNDONE


def test_a_write_anki_did_not_keep_leaves_no_new_clip_behind(ledger, tmp_path, monkeypatch):
    """The card open in Anki's editor: the write isn't kept (`NOT_APPLIED`, tried again later) — and the clip and
    picture it stored first are deleted again, none left in Anki's media folder with no card naming them."""
    lang = "ja"
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    anki = _card(Anki(), lang)
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    anki.editor_open.add(900)
    assert swap.write_in_place(anki, ledger, row, _rendered(tmp_path, lang), MAPPING, swap.kept_folder()) == \
        (None, swap.NOT_APPLIED)
    assert "am-clip.mp3" not in anki.media and "am-pic.webp" not in anki.media
    assert anki.media["sl-old.mp3"] == b"ID3 old clip"


@pytest.mark.parametrize("broken", ["no sentence", "a clip it didn't hand over"])
def test_a_render_with_no_sentence_or_a_missing_clip_is_never_written(ledger, tmp_path, monkeypatch, broken):
    """Render's note with an empty sentence, or naming a clip whose file it didn't hand over: never written over the
    learner's card (its sentence blanked, or pointed at a clip that isn't there) — a new card instead."""
    lang = "ja"
    word, old, _other = CASES[lang]
    monkeypatch.setattr(swap, "kept_folder", lambda: str(tmp_path / "swap-kept"))
    anki = _card(Anki(), lang)
    _made_by_connect(ledger, lang)
    _entry, row = _to_job(ledger, lang, anki, monkeypatch)
    rendered = _rendered(tmp_path, lang)
    if broken == "no sentence":
        rendered["fields"]["Sentence"] = ""
    else:
        rendered["files"] = rendered["files"][1:]
    assert swap.write_in_place(anki, ledger, row, rendered, MAPPING, swap.kept_folder()) == (swap.NEW_CARD, None)
    assert _value(anki, "Sentence") == old.replace(word, f"<b>{word}</b>") and not swap.in_place_row(ledger, row["job_id"])["wrote"]


def test_the_kept_copies_are_looked_at_twice_a_day_never_every_look(tmp_path, monkeypatch):
    """A 30-day clock needs no purge every few minutes: one per process each 12 hours (a thread a look, before)."""
    folder = tmp_path / "swap-kept"
    folder.mkdir()
    calls = []
    monkeypatch.setattr(swap, "kept_folder", lambda: str(folder))
    monkeypatch.setattr(swap, "_PURGED", {})
    monkeypatch.setattr(path_utils, "cleanup_trash_async", lambda path: calls.append(path))
    swap._purge_kept()
    swap._purge_kept()
    assert calls == [str(folder)]
