"""Kyou-DW 3: *Parsing mistake* on a deleted card asks one more thing — **The word is wrong** or **Only in this
sentence** (words PROVISIONAL).

What is pinned here: *The word is wrong* stays what *Parsing mistake* did (the word ignored, never mined again, its
line in Send report's list). *Only in this sentence* leaves the word alone: its line goes in Send report's list and is
never used for the word again, and the word gets a new card from another sentence through the door *Bad card* uses
(`swap.make_card(..., by=BY_BAD_CARD)`: no second card maker) — waiting in Swap's own card when the library has no
other sentence yet. Each Undo puts back exactly what was there before the press (the line off the list, the ban gone,
the new card taken back). Which answer is offered first is Surasura's guess, made by the deleted-card look: a word a
dictionary holds (the shipped meanings, the learner's own) that the last Generate kept sentences for in several other
files is offered *Only in this sentence* first; anything else *The word is wrong* first. Never chosen for the learner.

What a wrong answer would cost: a real word never mined again because one line was cut wrong, or a card made from the
very line that read it wrong; a ban an Undo leaves behind; a guess that answers for the learner.
Real lines from `tests/Test Resources/ja/library_episode.ass` and `context_test.txt` and `zh/night_market.srt`
(through the deleted-card suite's LINES), ja + zh.
"""
import pytest

from app.connect import deleted, library
from app.connect.ledger import Ledger
from app.services import flags, needs, word_marks
from tests import connect_helpers as c
from tests.connect.test_kantan_sd_list import _plan, _write
from tests.connect.test_kyou_dw_deleted import (LINES, NEW, OTHER, _asked, _gone, _made, _make_it, _never,  # noqa: F401
                                                ledger, swap_world)
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _only_line(lang, anki, monkeypatch, line=True, notes_of=slice(0, 1)):
    """A Connect card deleted, the look's stamp, then *Only in this sentence* -> (led, notes, the swaps' rows,
    avoided): Swap's ask recorded and its look run (another sentence, or none: `line` False)."""
    from app.connect import swap
    from tests.connect.test_kantan_sl_swap import Steps
    led = Ledger()
    item, notes = _made(lang, led)
    for (job,) in led.conn.execute("SELECT id FROM jobs").fetchall():
        led.set_state(job, "done")                  # the deleted card's own mining ended long ago
    _gone(lang, led, notes[notes_of])
    avoided = []

    def choose(language, w, avoid, reachable=None, skip_items=(), reading=None):
        avoided.append((w, list(avoid)))
        return (item, OTHER[lang]) if line else None
    monkeypatch.setattr(swap, "choose_line", choose)
    got = deleted.answer(lang, notes[notes_of], deleted.LINE, ledger=led)
    assert got["done"] == [(n, w) for n, (w, _r, _s) in zip(notes[notes_of], LINES[lang][notes_of])]
    assert got["skipped"] == []
    swap.look(Steps(), led, lang, anki=anki, files=5)
    return led, notes, swap._rows(led, "language = ?", (lang,)), avoided


# --------------------------------------------------------------------------- #
# The two answers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_only_in_this_sentence_keeps_the_word_flags_its_line_and_asks_swap_for_another_sentence(
        lang, swap_world, monkeypatch):
    # why: the word is real, this line read it wrong — so the word is never ignored, the line reaches Send report's
    # list as a parsing report (the same entry *The word is wrong* adds: nothing new leaves), and the word's new card
    # comes from Swap's one maker naming the deleted note (the bad-card way), never from the line that was wrong
    from app.connect import swap
    anki, lists = swap_world
    lists(lang)
    led, notes, rows, avoided = _only_line(lang, anki, monkeypatch)
    word, _r, sentence = LINES[lang][0]
    try:
        assert word_marks.states(lang, [word])[word] is None, "the word is real: never ignored"
        (line,) = flags.read(lang)
        assert (line["line"], line["word"], line["source"], line["reasons"], line["key"]) == \
            (sentence, word, "loop", ["parsing"], f"note:{notes[0]}")
        (row,) = rows
        assert (row["by"], row["old_note"], row["state"], row["line"]) == \
            (swap.BY_BAD_CARD, notes[0], swap.QUEUED, OTHER[lang]), "one ask, the bad-card way, from another line"
        assert avoided == [(word, [sentence])], "the line that read it wrong is never the new card's"
        assert _asked(lang, led)["asked"] == [], "answered: asked no more"
        assert deleted.answer(lang, notes[:1], deleted.LINE, ledger=led)["done"] == [], "a second press asks nothing"
        assert len(swap._rows(led, "language = ?", (lang,))) == 1 and len(flags.read(lang)) == 1
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_word_is_wrong_still_ignores_it_and_asks_swap_for_nothing(lang, swap_world, monkeypatch):
    # why: the other half of the question — a wrong split is no word: ignored (never mined again), its line in Send
    # report's list, and no new card (another sentence would carry the same wrong word)
    from app.connect import swap
    _anki, lists = swap_world
    lists(lang)
    led = Ledger()
    try:
        _item, notes = _made(lang, led)
        _gone(lang, led, notes[:1])
        word = LINES[lang][0][0]
        got = deleted.answer(lang, notes[:1], deleted.PARSING, ledger=led, state_of=_never)
        assert got["done"] == [(notes[0], word)]
        assert word_marks.states(lang, [word])[word] == "ignore"
        assert [ln["word"] for ln in flags.read(lang)] == [word]
        swap.ensure(led)
        assert swap._rows(led, "language = ?", (lang,)) == [], "no card asked for a word that is no word"
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_only_in_this_sentence_is_made_and_its_undo_takes_back_card_line_and_ban(lang, swap_world, monkeypatch):
    # why: Undo puts back exactly what was before the press — the new card deleted through Swap's own Undo (Tidy's
    # guarantee, a backup), the line off Send report's list, the line's ban gone — and the deleted card asks again
    from app.connect import swap
    anki, lists = swap_world
    lists(lang)
    led, notes, (row,), _avoided = _only_line(lang, anki, monkeypatch)
    word = LINES[lang][0][0]
    try:
        made = _make_it(led, anki, row, lang)
        assert (made["state"], made["new_note"]) == (swap.MADE, NEW)
        out = deleted.undo(lang, notes[:1], settings={})
        assert out == {"done": [(notes[0], word)], "skipped": []}
        assert anki.deleted == [NEW] and flags.read(lang) == []
        assert swap._rows(led, "id = ?", (row["id"],))[0]["state"] == swap.UNDONE
        assert word_marks.states(lang, [word])[word] is None
        assert [a["note_id"] for a in _asked(lang, led)["asked"]] == notes[:1], "Undone · asked again"
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_line_is_never_used_for_the_word_again_by_a_later_swap_until_the_answer_is_undone(
        lang, swap_world, monkeypatch):
    # why: "never used for the word again" must hold after the new card exists — a later ⇄ of the word (the journey's,
    # the loop's) avoids the line too; once the answer is undone the ban goes with it (back to exactly before)
    from app.connect import swap
    from tests.connect.test_kantan_sl_swap import Steps
    anki, lists = swap_world
    lists(lang)
    led, notes, (row,), avoided = _only_line(lang, anki, monkeypatch)
    word, _r, sentence = LINES[lang][0]
    try:
        _make_it(led, anki, row, lang)
        later = swap.make_card(lang, word, by=swap.BY_JOURNEY, ledger=led, wake=False, state_of=_never)
        avoided.clear()
        swap.look(Steps(), led, lang, anki=anki, files=5)
        assert avoided and sentence in avoided[0][1], "a later swap of the word never goes back to the wrong line"
        swap._set(led, later["id"], state=swap.DROPPED, why="test")      # that later ask is over
        assert deleted.undo(lang, notes[:1], settings={})["done"] == [(notes[0], word)]
        again = swap.make_card(lang, word, by=swap.BY_JOURNEY, ledger=led, wake=False, state_of=_never)
        avoided.clear()
        swap.look(Steps(), led, lang, anki=anki, files=5)
        assert avoided and sentence not in avoided[0][1], "undone: the line's ban went with the answer"
        assert again["state"] == swap.ASKED
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_only_in_this_sentence_with_no_other_sentence_waits_in_swaps_card_and_its_undo_is_refused_in_its_words(
        lang, swap_world, monkeypatch):
    # why: the library says the word only in the deleted card's line: Swap's ask waits in its own *Needs you* card (as
    # Bad card's does), the answer stands; an Undo before the card is made is refused in Swap's words and leaves the
    # line on Send report's list (nothing half undone)
    from app.connect import swap
    anki, lists = swap_world
    lists(lang)
    led, notes, (row,), _avoided = _only_line(lang, anki, monkeypatch, line=False)
    word = LINES[lang][0][0]
    try:
        assert row["state"] == swap.WAITS
        rec = {"swaps": swap.status_of(led.conn, lang), "deleted": _asked(lang, led)}
        (wait,) = needs._swap_entries(rec, set(), set())
        assert wait.kind == needs.SWAP_WAITS and word in wait.title
        assert needs._deleted_entries(rec, set(), set()) == []
        out = deleted.undo(lang, notes[:1], settings={})
        assert out == {"done": [], "skipped": [(notes[0], word, swap.NOT_MADE)]}
        assert [ln["word"] for ln in flags.read(lang)] == [word], "refused: the line stays as the answer left it"
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_only_in_these_sentences_for_all_asks_one_card_each_and_flags_each_line(lang, swap_world, monkeypatch):
    # why: *Same for all* answers every card of the card, once: one ask a word (each naming its own deleted note), one
    # line each in Send report's list, no word ignored
    from app.connect import swap
    anki, lists = swap_world
    lists(lang)
    led, notes, rows, _avoided = _only_line(lang, anki, monkeypatch, notes_of=slice(0, 2))
    try:
        assert sorted((r["word"], r["old_note"], r["by"]) for r in rows) == \
            sorted((LINES[lang][i][0], notes[i], swap.BY_BAD_CARD) for i in range(2))
        assert sorted(ln["key"] for ln in flags.read(lang)) == sorted(f"note:{n}" for n in notes[:2])
        assert all(s is None for s in word_marks.states(lang, [w for w, _r, _s in LINES[lang][:2]]).values())
    finally:
        led.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_only_in_this_sentence_for_a_word_known_since_is_skipped_and_said(lang, ledger):
    # why: a word the learner marked Known after the delete gets no card and no report: skipped, said, counted
    _item, notes = _made(lang, ledger)
    _gone(lang, ledger, notes[:1])
    word = LINES[lang][0][0]
    got = deleted.answer(lang, notes[:1], deleted.LINE, ledger=ledger, state_of=lambda w, _r="": "known")
    assert got["done"] == [] and got["skipped"] == [(notes[0], word, deleted.REFUSED["known"])]
    assert flags.read(lang) == [] and _asked(lang, ledger)["known"] == 1


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_only_in_this_sentence_needs_no_anki_at_the_press(lang, swap_world, monkeypatch):
    # why: Anki closed (or not installed): the press still records the ask and the line — Swap makes the card at
    # Connect's next look with Anki open; nothing at the press talks to Anki
    from app.connect import swap
    _anki, lists = swap_world
    lists(lang)

    def no_anki(*_a, **_k):
        raise ConnectionRefusedError("Anki is closed")
    monkeypatch.setattr(swap, "AnkiSwap", no_anki)
    led = Ledger()
    try:
        _item, notes = _made(lang, led)
        _gone(lang, led, notes[:1])
        got = deleted.answer(lang, notes[:1], deleted.LINE, ledger=led, state_of=_never)
        assert got["done"] == [(notes[0], LINES[lang][0][0])]
        assert [r["state"] for r in swap._rows(led, "language = ?", (lang,))] == [swap.ASKED]
        assert len(flags.read(lang)) == 1
    finally:
        led.close()


# --------------------------------------------------------------------------- #
# Which answer is offered first (the look's guess; never chosen for the learner)
# --------------------------------------------------------------------------- #
SAID = {  # a word the shipped dictionary holds, natural lines saying it (one the deleted card's), and a non-word
    "ja": ("図書館", "としょかん", ["市立図書館", "図書館で古い地図を見つけた。", "図書館は九時に開きます。",
                                   "駅の前に新しい図書館ができた。"], ("ビルデ", "", "ビルデイングの前で待ってる。")),
    "zh": ("夜市", "", ["今天我们要去台北的夜市吃东西。", "我们明天去夜市吃牛肉面吧", "夜市的人真多。",
                       "这个夜市每天都开。"], ("了饭", "", "我们吃了饭就去夜市。")),
}


def _files(lang, lines, key, name="第{:02d}話.srt"):
    """One file a line, then a plan whose row for `key` keeps each line from its file -> the paths."""
    paths = [_write(lang, name.format(i + 1), [text]) for i, text in enumerate(lines)]
    _plan(lang, paths, {key: [(i, 0, text, 1) for i, text in enumerate(lines)]})
    return paths


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_dictionary_word_said_in_several_other_files_is_offered_only_in_this_sentence_first(lang, monkeypatch):
    # why: a word the dictionary knows that the learner's library says in other files is most likely a real word this
    # one line read wrong; the deleted card's own file never counts as another
    from app import own_dicts
    monkeypatch.setattr(own_dicts, "lookup", lambda words, root=None: {})
    word, reading, lines, _odd = SAID[lang]
    _files(lang, lines, (word, reading))
    got = deleted.likely(lang, [(1, word, reading, lines[0])])
    assert got == {1: deleted.LINE}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_word_said_in_too_few_other_files_or_in_no_dictionary_is_offered_the_word_is_wrong_first(
        lang, monkeypatch):
    # why: a word met in one other file, or one no dictionary holds (a wrong split's piece), is most likely no word
    from app import own_dicts
    monkeypatch.setattr(own_dicts, "lookup", lambda words, root=None: {})
    word, reading, lines, (odd, odd_reading, odd_line) = SAID[lang]
    _files(lang, lines[:3], (word, reading))
    got = deleted.likely(lang, [(1, word, reading, lines[0])])
    assert got == {1: deleted.PARSING}, "two other files: too few — the deleted card's own file is never one of them"
    _files(lang, [odd_line] * 4, (odd, odd_reading), name="他{:02d}.srt")
    assert deleted.likely(lang, [(2, odd, odd_reading, "")]) == {2: deleted.PARSING}, "no dictionary holds it"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_word_only_the_learners_own_dictionary_holds_counts_as_a_dictionary_word(lang, monkeypatch):
    # why: the learner's own dictionaries (Anki Miner's) are read too — a word they hold that the shipped table
    # lacks is still a word
    from app import own_dicts
    _word, _reading, _lines, (odd, odd_reading, odd_line) = SAID[lang]
    monkeypatch.setattr(own_dicts, "lookup", lambda words, root=None: {
        k: ("JMdict", "a meaning") for k in words if k[0] == odd})
    _files(lang, [odd_line] * 4, (odd, odd_reading), name="他{:02d}.srt")
    assert deleted.likely(lang, [(2, odd, odd_reading, "")]) == {2: deleted.LINE}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_no_plan_offers_the_word_is_wrong_first_and_never_raises(lang, monkeypatch):
    # why: before any Generate (or with its plan unreadable) the guess falls back to today's order, quietly
    word, reading, lines, _odd = SAID[lang]
    assert deleted.likely(lang, [(1, word, reading, lines[0])]) == {1: deleted.PARSING}
    from app.connect import sentences
    monkeypatch.setattr(sentences, "files_saying", lambda *a, **k: (_ for _ in ()).throw(OSError("held open")))
    assert deleted.likely(lang, [(1, word, reading, lines[0])]) == {}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_look_keeps_its_guess_and_the_card_offers_that_answer_first(lang, ledger):
    # why: the guess is made once, by the look that saw the card go (never at the window's paint), kept with the card,
    # and only orders the follow-up's two chips — the learner still picks
    _item, notes = _made(lang, ledger)
    guess = {notes[0]: deleted.LINE}
    with c.store(lang) as s:
        library.notes_gone(s, notes[:2])
        deleted.seen(lang, notes[:2], s, state_of=_never, ledger=ledger,
                     likely_of=lambda language, rows: {n: guess.get(n, deleted.PARSING) for n, *_ in rows})
    rec = _asked(lang, ledger)
    assert {a["note_id"]: a["likely"] for a in rec["asked"]} == {notes[0]: deleted.LINE, notes[1]: deleted.PARSING}
    keys = {n: needs.deleted_line_key(n) for n in notes[:2]}
    (entry,) = needs._deleted_entries({"deleted": rec}, set(), set(), asking=frozenset(notes[:2]))
    how = {ln.number: ln.actions for ln in entry.lines if ln.key.startswith(needs.DELETED_HOW)}
    assert how == {notes[0]: ("dw_only_line", "dw_word_wrong"), notes[1]: ("dw_word_wrong", "dw_only_line")}
    order = [ln.key for ln in entry.lines]
    for n in notes[:2]:
        assert order.index(needs.deleted_how_key(n)) == order.index(keys[n]) + 1, "the follow-up under its own line"
    (plain,) = needs._deleted_entries({"deleted": rec}, set(), set())
    assert not any(ln.key.startswith(needs.DELETED_HOW) for ln in plain.lines), "asked only after Parsing mistake"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_same_for_all_asks_the_follow_up_once_for_the_whole_card_and_says_so(lang, ledger):
    # why: *All parsing mistakes* asks its follow-up once, for every card (shown or not), first on the card, its words
    # saying it is for all of them; the order follows most of the cards' guesses (a tie: The word is wrong first)
    _item, notes = _made(lang, ledger, n=3)
    with c.store(lang) as s:
        library.notes_gone(s, notes)
        deleted.seen(lang, notes, s, state_of=_never, ledger=ledger,
                     likely_of=lambda language, rows: {n: deleted.LINE if n != notes[0] else deleted.PARSING
                                                       for n, *_ in rows})
    rec = _asked(lang, ledger)
    (plain,) = needs._deleted_entries({"deleted": rec}, set(), set())
    (entry,) = needs._deleted_entries({"deleted": rec}, set(), set(), asking=frozenset({plain.key}))
    first = entry.lines[0]
    assert first.key == needs.deleted_how_key(None) and first.actions == ("dw_all_only_line", "dw_all_word_wrong")
    assert first.text == needs.STRINGS["deleted_how_all"].format(n=3)
    assert sum(ln.key.startswith(needs.DELETED_HOW) for ln in entry.lines) == 1, "asked once"
    assert sorted(entry.data["notes"]) == notes
    assert "dw_all_parsing" not in entry.actions, "the follow-up stands in for the batch's own press"
    (two,) = needs._deleted_entries({"deleted": dict(rec, asked=rec["asked"][:2])}, set(), set(),
                                    asking=frozenset({plain.key}))
    assert not any(ln.key.startswith(needs.DELETED_HOW) for ln in two.lines),         "a card that changed since (a line answered) is not asked for all until pressed again"
    assert "dw_all_parsing" in two.actions
    tie = dict(rec, asked=[dict(rec["asked"][0], likely=deleted.LINE), dict(rec["asked"][1], likely=deleted.PARSING)])
    (even,) = needs._deleted_entries({"deleted": tie}, set(), set())
    (even,) = needs._deleted_entries({"deleted": tie}, set(), set(), asking=frozenset({even.key}))
    assert even.lines[0].actions == ("dw_all_word_wrong", "dw_all_only_line"), "a tie: The word is wrong first"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_own_dictionary_that_cant_be_read_takes_nothing_from_the_shipped_one(lang, monkeypatch):
    # why: one broken dictionary of the learner's must not drop the whole guess — the shipped meanings still count
    from app import own_dicts

    def broken(words, root=None):
        raise OSError("a dictionary file held open")
    monkeypatch.setattr(own_dicts, "lookup", broken)
    word, reading, lines, _odd = SAID[lang]
    _files(lang, lines, (word, reading))
    assert deleted.likely(lang, [(1, word, reading, lines[0])]) == {1: deleted.LINE}
