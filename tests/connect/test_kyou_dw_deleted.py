"""Kyou-DW: a card Surasura made that the learner deletes in Anki asks why (the review loop's fourth move, WL-35).

What is pinned here: Connect's deleted-card look remembers the cards it saw gone (`deleted.seen`, from the made card's
own record in the ledger: its word and sentence), *Needs you* asks about them in one quiet card (Known · Ignore ·
Parsing mistake · Bad card; *Same for all* from two), and each answer goes through the one owner — the word lists'
writer, Send report's list, Swap's maker — with an Undo that takes it back only while the word is as it left it. The
one-time list of deletes from before the loop asked is kept once, never grown, and never holds a delete the loop
asked about.

What a wrong answer would cost: a learner asked about a word they already know or ignore (the nag WL-6 / WL-44 rule
out), a word ignored or marked known that they can't take back, a parsing line never reaching us, a second card made
twice for one press, or Surasura's own deletes (Tidy, *Undo this batch*) asked about as if the learner had made them.
Real lines from `tests/Test Resources/ja/library_episode.ass` and `context_test.txt` (危険 and 有名 are known in the
suite's KnownWord.json from another source: the Ignore that turns them not known, and its Undo, are exercised) and
`zh/night_market.srt`, ja + zh.
"""
import datetime
import json

import pytest

from app.connect import deleted, library, status
from app.connect.ledger import Ledger
from app.services import flags, needs, word_marks
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

# (word, reading, sentence) — each sentence a real line of the suite's data that says its word
LINES = {
    "ja": [("図書館", "としょかん", "市立図書館"), ("図書", "としょ", "図書カードはお持ちですか？"),
           ("危険", "きけん", "冒険は危険だが、価値がある。"), ("有名", "ゆうめい", "彼は冒険家として非常に有名です。")],
    "zh": [("夜市", "yèshì", "今天我们要去台北的夜市吃东西。"), ("有名", "yǒumíng", "這家店的牛肉麵非常有名，"),
           ("排隊", "páiduì", "每天都有很多人排隊。"), ("頻道", "píndào", "大家好，歡迎回到我的頻道。")],
}
NOTE = 1_700_000_000_000            # Anki note ids are creation milliseconds: a later card has a bigger id


def _never(_word, _reading=""):
    return None


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _made(lang, ledger, n=4, first=NOTE):
    """An episode Connect mined: `n` of LINES' words made, notes first, first+1, … (the store's made words and the
    ledger's outcomes, as a batch records them) -> (item id, [note ids])."""
    c.library(lang)
    with c.store(lang) as s:
        item = s.ids("now")[0]
    notes = [first + i for i in range(n)]
    rows = [LINES[lang][i % len(LINES[lang])] for i in range(n)]
    with c.store(lang) as s:
        library.record_batch(s, item, {w if i < len(LINES[lang]) else f"{w}{i}": [notes[i]]
                                       for i, (w, _r, _s) in enumerate(rows)}, "2026-11-22T10:00:00Z", batch="t-1")
    job = ledger.queue(lang, item, "test", None)
    with ledger.transaction():
        ledger.record_outcomes(job, 1, [{"word": w if i < len(LINES[lang]) else f"{w}{i}", "reading": r,
                                         "sentence": sent, "line_start": 12.5 + i, "line_end": 14.0 + i,
                                         "outcome": "made", "note_id": notes[i]}
                                        for i, (w, r, sent) in enumerate(rows)])
    return item, notes


def _gone(lang, ledger, notes, state_of=_never, now=None):
    """The look: the store told (`library.notes_gone`, as `Steps.notes_gone` does), then `deleted.seen`."""
    with c.store(lang) as s:
        library.notes_gone(s, notes)
        return deleted.seen(lang, notes, s, state_of=state_of, ledger=ledger, now=now)


def _asked(lang, ledger, **kw):
    return deleted.status_of(ledger.conn, lang, **kw)


# --------------------------------------------------------------------------- #
# What is asked
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_no_deleted_cards_asks_nothing_and_shows_no_card(lang, ledger):
    # why: a learner who deleted nothing sees nothing; an empty ledger (no table yet) reads as empty, never raises
    assert deleted.status_of(ledger.conn, lang) == {"asked": [], "known": 0, "ignored": 0, "old": []}
    _made(lang, ledger)
    assert _gone(lang, ledger, []) == 0
    rec = _asked(lang, ledger)
    assert rec["asked"] == [] and rec["old"] == []
    assert needs._deleted_entries({"deleted": rec}, set(), set()) == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_one_deleted_card_is_asked_with_its_word_sentence_and_four_chips(lang, ledger):
    # why: the card shows what the learner deleted (its word and the line it was cut from: the ledger's record — the
    # store keeps no sentence), one line, the four chips, no *Same for all* for one
    item, notes = _made(lang, ledger)
    assert _gone(lang, ledger, notes[:1]) == 1
    rec = _asked(lang, ledger)
    word, _r, sentence = LINES[lang][0]
    assert [(a["note_id"], a["word"], a["sentence"], a["item_id"]) for a in rec["asked"]] == \
        [(notes[0], word, sentence, item)]
    (entry,) = needs._deleted_entries({"deleted": rec}, set(), set())
    assert entry.kind == needs.DELETED and entry.title == needs.STRINGS["deleted_title_one"]
    assert [ln.text for ln in entry.lines] == [f"「{word}」 {sentence}"]
    assert entry.lines[0].actions == needs.DELETED_ACTIONS and entry.lines[0].number == notes[0]
    assert entry.actions == ("dw_leave",), "one card: no Same for all"
    assert entry.say and entry.say not in entry.title


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_many_deleted_cards_are_one_card_with_same_for_all_and_a_mass_title(lang, ledger):
    # why: a 12-card delete is ONE quiet card (never 12), its title asks for a few, and Same for all covers every
    # card, shown or not (WL-27)
    _item, notes = _made(lang, ledger, n=12)
    assert _gone(lang, ledger, notes) == 12
    (entry,) = needs._deleted_entries({"deleted": _asked(lang, ledger)}, set(), set())
    assert len(entry.lines) == 12 and entry.title == needs.STRINGS["deleted_title_many"].format(n=12)
    assert entry.actions == needs.DELETED_ALL + ("dw_leave",)
    assert sorted(entry.data["notes"]) == notes
    assert sorted(needs.answer_keys(entry)) == sorted(needs.deleted_line_key(n) for n in notes)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_whose_word_was_already_known_or_ignored_is_never_asked(lang, ledger):
    # why: WL-6 / WL-44 — the tester who synced their red flags and then deleted the cards is never asked again;
    # the look keeps them as known / ignored (counted), the rest are asked
    _item, notes = _made(lang, ledger)
    words = [w for w, _r, _s in LINES[lang]]
    state = {words[0]: "known", words[1]: "ignored"}
    _gone(lang, ledger, notes, state_of=lambda w, _r="": state.get(w))
    rec = _asked(lang, ledger)
    assert [a["word"] for a in rec["asked"]] == [words[3], words[2]], "newest note first; known / ignored not asked"
    assert (rec["known"], rec["ignored"]) == (1, 1)


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_deleted_card_whose_word_has_a_new_card_since_is_not_asked(lang, ledger):
    # why: Connect made the word a new card after the delete (a Swap, an ask): nothing is left to decide
    item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:1])
    word, reading, sentence = LINES[lang][0]
    job = ledger.queue(lang, item + 1, "test", None)
    with ledger.transaction():
        ledger.record_outcomes(job, 1, [{"word": word, "reading": reading, "sentence": sentence, "outcome": "made",
                                         "note_id": NOTE + 100}])
    assert _asked(lang, ledger)["asked"] == []
    _gone(lang, ledger, [NOTE + 100])               # that one deleted too: the newest is asked, the older not again
    assert [a["note_id"] for a in _asked(lang, ledger)["asked"]] == [NOTE + 100, notes[0]]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_learners_own_card_and_one_seen_twice_are_stamped_once_or_not_at_all(lang, ledger):
    # why: only Surasura's cards are asked (a note Connect has no outcome for is the learner's own); the look runs
    # every run, so a note seen gone again is never a second line
    _item, notes = _made(lang, ledger)
    assert _gone(lang, ledger, [NOTE + 999]) == 0
    assert _gone(lang, ledger, notes[:1]) == 1
    assert deleted.seen(lang, notes[:1], None, state_of=_never, ledger=ledger) == 0
    assert len(_asked(lang, ledger)["asked"]) == 1


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_unanswered_card_goes_after_two_weeks(lang, ledger):
    # why: WL-31 — it never nags: unanswered after ASK_DAYS it leaves the page by itself
    _item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:1], now="2026-11-01T10:00:00Z")
    late = datetime.datetime(2026, 11, 22, tzinfo=datetime.timezone.utc)
    assert _asked(lang, ledger, now=late)["asked"] == []
    assert len(_asked(lang, ledger, now=datetime.datetime(2026, 11, 10, tzinfo=datetime.timezone.utc))["asked"]) == 1


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_answered_or_left_line_leaves_the_card_and_a_new_delete_joins_it(lang, ledger):
    # why: *Leave them* / an answer records each line's key: the card holds only what still waits, and a later
    # delete joins the same card (WL-31) instead of bringing the left ones back
    _item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:2])
    (entry,) = needs._deleted_entries({"deleted": _asked(lang, ledger)}, set(), set())
    answered = set(needs.answer_keys(entry))
    _gone(lang, ledger, notes[2:3])
    (again,) = needs._deleted_entries({"deleted": _asked(lang, ledger)}, set(), answered)
    assert [ln.number for ln in again.lines] == [notes[2]] and again.key != entry.key


# --------------------------------------------------------------------------- #
# The answers and their Undo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_known_marks_the_word_through_the_word_lists_and_undo_takes_it_back(lang, ledger):
    # why: Known is the word lists' one writer (Kyou-LR's rules); a second press finds nothing to answer; Undo puts
    # the word as it was and the card asks again
    _item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:1])
    word = LINES[lang][0][0]
    got = deleted.answer(lang, notes[:1], deleted.KNOWN, ledger=ledger, state_of=_never)
    assert got["done"] == [(notes[0], word)] and got["skipped"] == []
    assert word_marks.states(lang, [word])[word] == "known"
    assert _asked(lang, ledger)["asked"] == []
    assert deleted.answer(lang, notes[:1], deleted.KNOWN, ledger=ledger, state_of=_never)["done"] == []
    out = deleted.undo(lang, notes[:1], ledger=ledger)
    assert out["done"] == [(notes[0], word)]
    assert word_marks.states(lang, [word])[word] is None
    assert [a["note_id"] for a in _asked(lang, ledger)["asked"]] == notes[:1]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_ignore_for_all_is_one_write_and_undo_is_refused_for_a_word_changed_since(lang, ledger):
    # why: Same for all is one answer; Undo never overwrites what the learner did since (a word marked Known after
    # the Ignore keeps its Known), and takes back the others
    _item, notes = _made(lang, ledger, n=3)
    _gone(lang, ledger, notes)
    words = [w for w, _r, _s in LINES[lang][:3]]
    got = deleted.answer(lang, notes, deleted.IGNORE, ledger=ledger, state_of=_never)
    assert sorted(w for _n, w in got["done"]) == sorted(words)
    assert all(v == "ignore" for v in word_marks.states(lang, words).values())
    word_marks.apply(lang, [(words[0], "known")])
    out = deleted.undo(lang, notes, ledger=ledger)
    assert out["skipped"] == [(notes[0], words[0], deleted.REFUSED["changed"])]
    assert sorted(n for n, _w in out["done"]) == notes[1:]
    st = word_marks.states(lang, words)
    assert st[words[0]] == "known" and st[words[1]] is None and st[words[2]] is None


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_parsing_mistake_ignores_the_word_and_puts_its_line_in_send_reports_list(lang, ledger):
    # why: WL-28 / J-FLAGS — the line goes to Send report's one list (source `loop`, reason parsing), with the
    # episode's names and never a path; Undo takes the line off and the word off the Ignore list
    _item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[1:2])
    word, _r, sentence = LINES[lang][1]
    got = deleted.answer(lang, notes[1:2], deleted.PARSING, ledger=ledger, state_of=_never)
    assert got["done"] == [(notes[1], word)]
    assert word_marks.states(lang, [word])[word] == "ignore"
    (line,) = flags.read(lang)
    assert (line["line"], line["word"], line["source"], line["reasons"], line["key"]) == \
        (sentence, word, "loop", ["parsing"], f"note:{notes[1]}")
    assert line["at"] == 13.5
    assert "/" not in line["show"] + line["episode"] and "\\" not in line["show"] + line["episode"]
    assert deleted.undo(lang, notes[1:2], ledger=ledger)["done"] == [(notes[1], word)]
    assert flags.read(lang) == [] and word_marks.states(lang, [word])[word] is None


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_answer_for_a_word_known_since_the_delete_is_skipped_and_said(lang, ledger):
    # why: the word became known (a sync) between the delete and the press: nothing is written, the line says so
    _item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:1])
    word = LINES[lang][0][0]
    got = deleted.answer(lang, notes[:1], deleted.IGNORE, ledger=ledger, state_of=lambda w, _r="": "known")
    assert got["done"] == [] and got["skipped"] == [(notes[0], word, deleted.REFUSED["known"])]
    assert word_marks.states(lang, [word])[word] is None


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_refused_word_list_write_answers_nothing(lang, ledger, monkeypatch):
    # why: the word lists busy (a sync holding KnownWord.json): nothing is recorded as answered, the card still asks
    _item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:1])
    monkeypatch.setattr(word_marks, "apply", lambda *_a, **_k: word_marks.Marked(error="busy", busy=True))
    got = deleted.answer(lang, notes[:1], deleted.KNOWN, ledger=ledger, state_of=_never)
    assert got["done"] == [] and got["error"] == "busy"
    assert len(_asked(lang, ledger)["asked"]) == 1


def test_an_unknown_answer_is_refused():
    with pytest.raises(ValueError):
        deleted.answer("ja", [1], "maybe")


# --------------------------------------------------------------------------- #
# The old deletes, once
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_old_deletes_are_kept_once_never_grown_and_never_hold_an_asked_one(lang, ledger):
    # why: the Discord promise — the deletes from before the loop asked can be forgotten once; a delete the loop
    # asked about is never in that list, and a later delete never joins it
    _item, notes = _made(lang, ledger)
    with c.store(lang) as s:
        library.notes_gone(s, notes[:2])            # deleted before this version: the store emptied, never stamped
    _gone(lang, ledger, notes[2:3])                 # the first look in this version: asked, and the list kept
    words = [w for w, _r, _s in LINES[lang]]
    rec = _asked(lang, ledger)
    assert sorted(o["word"] for o in rec["old"]) == sorted(words[:2])
    assert {o["word"]: o["sentence"] for o in rec["old"]} == {w: s for w, _r, s in LINES[lang][:2]}
    assert [a["word"] for a in rec["asked"]] == [words[2]]
    _gone(lang, ledger, notes[3:4])
    assert sorted(o["word"] for o in _asked(lang, ledger)["old"]) == sorted(words[:2]), "never grown"
    entries = needs._deleted_entries({"deleted": _asked(lang, ledger)}, set(), set())
    old = next(e for e in entries if e.kind == needs.OLD_DELETES)
    assert old.actions == ("dw_forget_all", "dw_keep_old") and all(ln.actions == ("dw_forget",) for ln in old.lines)
    left = needs._deleted_entries({"deleted": _asked(lang, ledger)}, set(), {needs.old_line_key(words[0])})
    assert [ln.label for ln in next(e for e in left if e.kind == needs.OLD_DELETES).lines] == [words[1]]
    kept = needs._deleted_entries({"deleted": _asked(lang, ledger)}, set(), {needs.OLD_DELETES})
    assert all(e.kind != needs.OLD_DELETES for e in kept), "Keep them: gone for good"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_forgetting_an_old_delete_is_the_stores_allow_again_and_undo_keeps_it_deleted(lang, ledger):
    # why: Forget is the one write the episode's window already has (`Store.allow_again`): the word may be made
    # again; its Undo puts the record back; a word still with a card is never touched
    _item, notes = _made(lang, ledger)
    with c.store(lang) as s:
        library.notes_gone(s, notes[:1])
    _gone(lang, ledger, [])
    word = LINES[lang][0][0]
    assert [o["word"] for o in _asked(lang, ledger)["old"]] == [word]
    with c.store(lang) as s:
        change = s.allow_again([word, LINES[lang][1][0]])
        assert [r[1] for r in change.made_rows] == [word], "the word with a card is left alone"
        assert word not in library.made_words_all(s)
        s.undo(change)
        assert word in library.made_words_all(s)


def test_the_status_record_carries_the_deleted_cards(tmp_path, monkeypatch):
    # why: *Needs you* reads Connect's record (`status.read`), read-only: the deleted cards ride in it
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path) as led:
        _item, notes = _made("ja", led)
        _gone("ja", led, notes[:1])
    rec = status.language_record(status.read(["ja"], path=path), "ja")
    assert [a["note_id"] for a in rec["deleted"]["asked"]] == notes[:1]
    assert json.loads(json.dumps(rec["deleted"])) == rec["deleted"]
