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
import sqlite3

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
def test_a_newer_card_surasuras_tidy_deleted_never_hides_the_ask_and_one_its_undo_put_back_does(lang, ledger):
    # why: a Bad card's Undo (and any tidy) takes the newer card out of Anki: the deleted card must ask again, never
    # stay hidden behind a card that is gone; a tidy undone puts the card back, so it hides the ask again
    from app.connect import tidy
    item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:1])
    word, reading, sentence = LINES[lang][0]
    job = ledger.queue(lang, item + 1, "test", None)
    with ledger.transaction():
        ledger.record_outcomes(job, 1, [{"word": word, "reading": reading, "sentence": sentence, "outcome": "made",
                                         "note_id": NOTE + 100}])
    ledger.conn.execute(tidy._SQL)
    with ledger.transaction():
        cur = ledger.conn.execute("INSERT INTO tidies (language, at, why, state, folder, notes, made, deleted) VALUES "
                                  "(?, ?, 'swap', 'done', '', '{}', '[]', ?)", (lang, "2026-11-22T10:00:00Z",
                                                                                json.dumps([NOTE + 100])))
    assert [a["note_id"] for a in _asked(lang, ledger)["asked"]] == notes[:1], "the newer card is gone: asked"
    with ledger.transaction():
        ledger.conn.execute("UPDATE tidies SET state = 'undone' WHERE id = ?", (cur.lastrowid,))
    assert _asked(lang, ledger)["asked"] == [], "put back by the tidy's Undo: it stands, nothing to ask"
    other = "zh" if lang == "ja" else "ja"
    with ledger.transaction():
        ledger.conn.execute("UPDATE tidies SET state = 'done', language = ? WHERE id = ?", (other, cur.lastrowid))
    assert _asked(lang, ledger)["asked"] == [], "another language's tidy says nothing of this one's cards"


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
@pytest.mark.parametrize("state", ["writing", "done"])
def test_a_card_surasuras_tidy_deleted_is_never_stamped_even_before_the_store_heard(lang, state, ledger):
    # why: Tidy deletes in Anki first and tells the store after (`tidy.finish`); a look in between (a *Tidy now* while
    # Connect runs, or a store write that failed) sees the note gone — it is Surasura's own delete, never the learner's,
    # so it is never asked about (only another language's tidy leaves this one's notes to the look)
    from app.connect import tidy
    _item, notes = _made(lang, ledger)
    ledger.conn.execute(tidy._SQL)
    other = "zh" if lang == "ja" else "ja"
    with ledger.transaction():
        for language, note in ((lang, notes[0]), (other, notes[1])):
            ledger.conn.execute("INSERT INTO tidies (language, at, why, state, folder, notes, made) VALUES "
                                "(?, ?, 'auto', ?, '', ?, '[]')", (language, "2026-11-22T10:00:00Z", state,
                                                                   json.dumps({str(note): {"cards": {}}})))
    assert _gone(lang, ledger, notes[:2]) == 1
    assert [a["note_id"] for a in _asked(lang, ledger)["asked"]] == [notes[1]]

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
    rec = _asked(lang, ledger)
    assert rec["asked"] == [] and rec["known"] == 1, "known since: it leaves the card, counted, never asked again"


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


# --------------------------------------------------------------------------- #
# The look itself (`runner.Steps.notes_gone`)
# --------------------------------------------------------------------------- #
@pytest.fixture
def real_look(monkeypatch):
    from app.connect import anki_session
    monkeypatch.setattr(anki_session, "waiting", lambda url, settings: None)      # Anki open on Connect's profile
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(deleted, "_states", lambda _lang: _never)


def test_the_real_look_asks_about_a_deleted_card_and_asks_nothing_while_anki_is_closed(real_look):
    # why: Anki closed is never "every card deleted": nothing is asked until a look Anki answers
    from app.connect import runner
    from tests.connect.test_deleted_cards_every_run import FakeAnki
    with Ledger() as led:
        _item, notes = _made("ja", led, n=2)
    steps = runner.Steps({"connect_enabled": True})
    anki = FakeAnki(still_there={notes[1]}, down=1)
    steps._anki = lambda: anki
    runner._gone_look(steps, "ja")
    with Ledger() as led:
        assert deleted.status_of(led.conn, "ja")["asked"] == []
    assert steps.notes_gone("ja") == [notes[0]]
    with Ledger() as led:
        assert [a["word"] for a in deleted.status_of(led.conn, "ja")["asked"]] == [LINES["ja"][0][0]]


def test_surasuras_own_delete_is_never_asked(real_look):
    # why: *Undo this batch* and Tidy free their notes first (`library.unmake`): the look never sees them, so the
    # learner is never asked why about a card Surasura deleted
    from app.connect import runner
    from tests.connect.test_deleted_cards_every_run import FakeAnki
    with Ledger() as led:
        item, notes = _made("ja", led, n=2)
    with c.store("ja") as s:
        library.unmake(s, item, notes[:1], words=[LINES["ja"][0][0]])
    steps = runner.Steps({"connect_enabled": True})
    steps._anki = lambda: FakeAnki(still_there={notes[1]})
    assert steps.notes_gone("ja") == []
    with Ledger() as led:
        rec = deleted.status_of(led.conn, "ja")
    assert rec["asked"] == [] and rec["old"] == [], "a freed word is no delete, old or new"


# --------------------------------------------------------------------------- #
# Bad card: Swap's one maker, the real one (Kantan-SL: `swap.make_card(..., by=BY_BAD_CARD)`, `swap.act_undo`)
# --------------------------------------------------------------------------- #
NEW = NOTE + 100                    # the Bad card's new note: made after the deleted one (a bigger id)
OTHER = {"ja": "図書館で古い地図を見つけた。", "zh": "我们明天去夜市吃牛肉面吧"}   # another real line saying LINES[lang][0]


@pytest.fixture
def swap_world(monkeypatch):
    """The suite's own ledger (Swap's Undo opens it by its path, as the window's press does), the word lists empty,
    Anki the fake Swap's tests use (a real package for Tidy's backup), Anki answering."""
    from app.connect import swap
    from tests.connect.test_kantan_sl_swap import Anki, _lists
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    anki = Anki()
    monkeypatch.setattr(swap, "AnkiSwap", lambda _url: anki)
    return anki, _lists


def _bad_card(lang, anki, monkeypatch, line=True):
    """A Connect card deleted, the look's stamp, then *Bad card* -> (led, notes, word, the swap's row, avoided):
    Swap's ask recorded and its look run (a line from another sentence, or none: `line` False)."""
    from app.connect import swap
    from tests.connect.test_kantan_sl_swap import Steps
    led = Ledger()
    item, notes = _made(lang, led)
    for (job,) in led.conn.execute("SELECT id FROM jobs").fetchall():
        led.set_state(job, "done")                  # the deleted card's own mining ended long ago
    _gone(lang, led, notes[:1])
    word = LINES[lang][0][0]
    avoided = []

    def choose(language, w, avoid, reachable=None, skip_items=(), reading=None):
        avoided.append(list(avoid))
        return (item, OTHER[lang]) if line else None
    monkeypatch.setattr(swap, "choose_line", choose)
    got = deleted.answer(lang, notes[:1], deleted.BAD, ledger=led)
    assert got["done"] == [(notes[0], word)] and got["skipped"] == []
    swap.look(Steps(), led, lang, anki=anki, files=5)
    rows = swap._rows(led, "language = ?", (lang,))
    assert len(rows) == 1, "one ask for one press"
    return led, notes, word, rows[0], avoided


def _make_it(led, anki, row, lang):
    """Connect's swap job ends as the runner's own steps end every job: the batch with its deck (the card's home), the
    library's made-words record, done; the card in Anki untouched since; then Swap's next look sees it made."""
    import calendar
    import time
    from app.connect import swap
    from tests.connect.test_kantan_sl_swap import MINING, Steps, _make_the_job
    tag = "surasura::connect::" + led.tag_id(row["job_id"])
    _make_the_job(led, row, note=NEW, record=True, deck=MINING)
    done_at = calendar.timegm(time.strptime(led.job_by_id(row["job_id"])["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki.add(NEW, tag, row["word"], done_at - 60, deck=MINING, sound="bad-card-new.mp3")
    swap.look(Steps(), led, lang, anki=anki, files=5)
    return swap._rows(led, "id = ?", (row["id"],))[0]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_bad_card_is_a_new_card_from_another_line_made_as_every_connect_card_and_its_undo_asks_again(
        lang, swap_world, monkeypatch):
    # why: Bad card = "the word is fine, the card wasn't": Swap's one maker is asked once, by "bad card", naming the
    # deleted note so its line (Connect's record of it) is avoided; Connect's job makes the card through the runner's
    # own record step (the batch's deck, the made-words record — the records Tidy's guarantee asks of a card
    # Surasura made); the Undo deletes that card with a backup and the deleted card asks again, as its toast says
    from app.connect import swap, tidy
    anki, lists = swap_world
    lists(lang)
    led, notes, word, row, avoided = _bad_card(lang, anki, monkeypatch)
    try:
        assert (row["by"], row["old_note"], row["state"]) == (swap.BY_BAD_CARD, notes[0], swap.QUEUED)
        assert avoided == [[LINES[lang][0][2]]], "the deleted card's own line is never the new card's"
        assert row["line"] == OTHER[lang]
        assert deleted.answer(lang, notes[:1], deleted.BAD, ledger=led)["done"] == [], "a second press asks nothing"
        made = _make_it(led, anki, row, lang)
        assert (made["state"], made["new_note"]) == (swap.MADE, NEW)
        assert _asked(lang, led)["asked"] == [], "answered: never asked while its new card stands"
        out = deleted.undo(lang, notes[:1], settings={})
        assert out == {"done": [(notes[0], word)], "skipped": []}
        assert anki.deleted == [NEW], "the new card deleted through Tidy's guarantee (a backup kept)"
        assert swap._rows(led, "id = ?", (row["id"],))[0]["state"] == swap.UNDONE
        assert [a["note_id"] for a in _asked(lang, led)["asked"]] == notes[:1], \
            "Undone · asked again: the new card Surasura took back never counts as the word's newer card"
        assert tidy.asked_for(led, lang, [NEW]) == frozenset(), "an undone swap asks for nothing"
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_undo_on_a_bad_cards_swap_card_deletes_the_new_card_and_leaves_the_deleted_one_as_it_is(
        lang, swap_world, monkeypatch):
    # why: FS-2 2 (the lead's ruling): *Needs you*'s card for a Bad card's swap says what its Undo does, so that is
    # pinned here — Swap's own Undo (`swap.act_undo`, the window's `undo_swap_deleted`) deletes the new card through
    # Tidy's guarantee (a backup kept) and writes nothing to the old note: it is deleted, nothing to unsuspend,
    # unflag or untag. The answer itself stands (only the deleted card's own Undo takes it back and asks again)
    from app.connect import swap
    anki, lists = swap_world
    lists(lang)
    led, notes, _word, row, _avoided = _bad_card(lang, anki, monkeypatch)
    try:
        _make_it(led, anki, row, lang)
        del anki.log[:]
        assert swap.act_undo({}, lang, row["id"]) == {"undone": True, "word": row["word"]}
        assert anki.deleted == [NEW], "the new card deleted through Tidy's guarantee (a backup kept)"
        assert [e for e in anki.log if e[0] in ("unsuspend", "set_flag", "remove_tags")] == [],             "the old card is deleted: nothing put back, unflagged or untagged"
        assert swap._rows(led, "id = ?", (row["id"],))[0]["state"] == swap.UNDONE
        assert _asked(lang, led)["asked"] == [], "the Bad card answer stands: the old card stays deleted, unasked"
    finally:
        led.close()

@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("why", ["auto", "now"])
def test_an_ordinary_tidy_keeps_a_bad_cards_new_card_you_asked_for(lang, why, swap_world, monkeypatch):
    # why: the learner asked for this card (OPEN 56 g: a swap's new card counts as asked for, `tidy.asked_for`): an
    # ordinary tidy past the cap must never delete it, or the word is left with no card at all — the old one is
    # deleted, not suspended as a ⇄'s is
    from app.connect import library, tidy
    anki, lists = swap_world
    lists(lang)
    led, _notes, _word, row, _avoided = _bad_card(lang, anki, monkeypatch)
    try:
        _make_it(led, anki, row, lang)
        assert tidy.asked_for(led, lang, [NEW]) == {NEW}
        with pytest.raises(tidy.Refused) as kept:
            tidy.run(anki, led, lang, [NEW], why={"auto": tidy.AUTO, "now": tidy.NOW}[why],
                     open_store=lambda: library.open_store(lang))
        assert kept.value.say == tidy.ALL_KEPT and anki.deleted == []
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_bad_card_whose_word_has_no_other_sentence_waits_in_swaps_own_words_and_its_undo_is_refused_in_them(
        lang, swap_world, monkeypatch):
    # why: the library says the word only in the deleted card's line: Swap's ask waits (said once on *Needs you* in
    # Swap's own card, never a second one of Kyou-DW's), the answer stands, and an Undo before the card is made is
    # refused in Swap's words — the deleted card isn't asked again while its new card may still come
    from app.connect import swap
    anki, lists = swap_world
    lists(lang)
    led, notes, word, row, _avoided = _bad_card(lang, anki, monkeypatch, line=False)
    try:
        assert row["state"] == swap.WAITS
        rec = {"swaps": swap.status_of(led.conn, lang), "deleted": _asked(lang, led)}
        (wait,) = needs._swap_entries(rec, set(), set())
        assert wait.kind == needs.SWAP_WAITS and word in wait.title
        assert needs._deleted_entries(rec, set(), set()) == [], "answered: the deleted card asks nothing more"
        out = deleted.undo(lang, notes[:1], settings={})
        assert out == {"done": [], "skipped": [(notes[0], word, swap.NOT_MADE)]}
        assert _asked(lang, led)["asked"] == [] and anki.deleted == []
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_bad_card_for_a_word_ignored_since_is_dropped_by_swap_and_said(lang, swap_world, monkeypatch):
    # why: Swap never makes a card for a word now Ignored or Known (its own test, at its ask): the card is not
    # answered, says why, and leaves the list counted — never a card the learner didn't want
    from app.connect import swap
    anki, lists = swap_world
    word = LINES[lang][0][0]
    lists(lang, ignored=[word])
    led = Ledger()
    try:
        _item, notes = _made(lang, led)
        _gone(lang, led, notes[:2])
        got = deleted.answer(lang, notes[:2], deleted.BAD, ledger=led, state_of=_never)   # the look's test missed it
        assert got["done"] == [(notes[1], LINES[lang][1][0])]
        assert got["skipped"] == [(notes[0], word, deleted.REFUSED["ignored"])]
        rec = _asked(lang, led)
        assert rec["asked"] == [] and rec["ignored"] == 1, "Swap's own test says ignored: it leaves the card, counted"
        assert [r["state"] for r in swap._rows(led, "word = ?", (word,))] == [swap.DROPPED]
    finally:
        led.close()


# --------------------------------------------------------------------------- #
# An Undo whose last write failed (a database error after its own writes) is never stuck
# --------------------------------------------------------------------------- #
class _FailingOnce:
    """The ledger, with its next transaction failing as a locked database does."""

    def __init__(self, led):
        self._led, self.failed = led, False

    def __getattr__(self, name):
        return getattr(self._led, name)

    def transaction(self):
        if not self.failed:
            self.failed = True
            raise sqlite3.OperationalError("database is locked")
        return self._led.transaction()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_undo_whose_record_failed_after_the_mark_went_back_finishes_on_a_retry(lang, ledger):
    # why: Undo puts the word's mark back, then clears its answer; a locked ledger in between left the mark back but
    # the card answered — every later Undo said "it changed since" and the card was never asked again. A retry finds
    # the word as it was before the answer and finishes the Undo
    _item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:1])
    word = LINES[lang][0][0]
    assert word_marks.states(lang, [word])[word] is None
    assert deleted.answer(lang, notes[:1], deleted.KNOWN, ledger=ledger, state_of=_never)["done"]
    with pytest.raises(sqlite3.OperationalError):
        deleted.undo(lang, notes[:1], ledger=_FailingOnce(ledger))
    assert word_marks.states(lang, [word])[word] is None, "the mark went back before the record failed"
    assert _asked(lang, ledger)["asked"] == []
    out = deleted.undo(lang, notes[:1], ledger=ledger)
    assert out == {"done": [(notes[0], word)], "skipped": []}
    assert [a["note_id"] for a in _asked(lang, ledger)["asked"]] == notes[:1], "asked again"
    assert word_marks.states(lang, [word])[word] is None


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_bad_cards_undo_whose_record_failed_after_swap_undid_it_finishes_on_a_retry(lang, swap_world, monkeypatch):
    # why: Swap's Undo took the new card back, then Kyou-DW's record failed: a retry is told "undone already" by
    # Swap — that is this Undo done, never a refusal that leaves the card answered for good
    anki, lists = swap_world
    lists(lang)
    led, notes, word, row, _avoided = _bad_card(lang, anki, monkeypatch)
    try:
        _make_it(led, anki, row, lang)
        failing = _FailingOnce(led)
        with pytest.raises(sqlite3.OperationalError):
            deleted.undo(lang, notes[:1], ledger=failing, settings={})
        assert anki.deleted == [NEW]
        out = deleted.undo(lang, notes[:1], ledger=led, settings={})
        assert out == {"done": [(notes[0], word)], "skipped": []} and anki.deleted == [NEW], "never deleted twice"
        assert [a["note_id"] for a in _asked(lang, led)["asked"]] == notes[:1]
    finally:
        led.close()


def test_a_look_that_cannot_remember_its_deletes_marks_nothing_and_looks_again(real_look, monkeypatch):
    # why: the store forgets a gone note once told; a stamp that failed first (the ledger busy) must leave the
    # note for the next look, or the learner's delete is never asked
    from app.connect import runner
    from tests.connect.test_deleted_cards_every_run import FakeAnki
    with Ledger() as led:
        item, notes = _made("ja", led, n=2)
    steps = runner.Steps({"connect_enabled": True})
    steps._anki = lambda: FakeAnki(still_there={notes[1]})
    real_seen = deleted.seen

    def busy(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(deleted, "seen", busy)
    assert steps.notes_gone("ja") == []
    with c.store("ja") as s:
        assert notes[0] in s.cards_of([item])[item], "nothing marked gone"
    monkeypatch.setattr(deleted, "seen", real_seen)
    assert steps.notes_gone("ja") == [notes[0]], "asked again in the same run"
    with Ledger() as led:
        assert [a["note_id"] for a in deleted.status_of(led.conn, "ja")["asked"]] == [notes[0]]
