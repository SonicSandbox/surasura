"""Kyou-LR — the review loop's reader (3.0.18; the moves ruled 2026-11-20: ✓ Known = Suspend + Mark · ⇄ Swap =
Suspend + Green flag · ✕ Ignore = Suspend + Red flag; a plain suspend means nothing; red / green never Known).

Pinned here, end to end — the cards in a stand-in Anki → the known-words sync (`anki_sync.sync_all`) → the word lists,
the swap queue and the payoff:
- red → the Ignore list; green → a swap queued; a plain suspend nothing; both read at each sync, ja + zh;
- **the move rule**: a word the plain sync counted known before its card was flagged is moved (no longer known, its
  entry kept as it was under `notKnown`), and a studied, unsuspended red / green card never counts known;
- **Still learning**: a word known from a marked, suspended or deleted card goes back to not known, with Undo, and the
  sync never reads it known again from that card — only a new card, or a fresh Known move;
- **Undo per sync**: the lists back, its swaps dropped, no card touched; twice is nothing more; a word a later sync
  moved is left as it is;
- a card red, then green (and green, then red); a deleted swap card; Anki closed; empty states; the date known.

What a wrong answer would cost: a word the learner meant to ignore or swap stays known (it leaves their list and
journey for good — the sync is append-only), a word they took back to *Still learning* comes back known at the next
sync, or an Undo that touches their cards. Real words (ja + zh, the words of tests/Test Resources' sentences);
settings.json, KnownWord.json and every record in the test's temp root; a stand-in Anki that answers each search card by
card, never a live one (the live read: DevTest, in the register).
"""
import json
import os
import re
import time

import pytest

from app import anki_connect, anki_sync, settings_manager
from app.anki_connect import AnkiError
from app.connect import known_signal, review_loop, swap_queue
from app.path_utils import get_settings_path, get_user_files_path
from app.services import word_lists, word_marks

URL = "http://127.0.0.1:8765"
DECK = "Mining"
RED, GREEN, ORANGE = 1, 3, 2
WORDS = {"ja": ("冒険", "準備", "危険", "価値", "有名", "出かける"),
         "zh": ("冒险", "准备", "危险", "价值", "有名", "出发")}
WRITES = {"suspend", "unsuspend", "setSpecificValueOfCard", "addTags", "removeTags", "deleteNotes", "setFlag",
          "changeDeck", "updateNoteFields"}


def _tag_hit(tags, wanted):
    wanted = wanted.lower()
    return any(t.lower() == wanted or t.lower().startswith(wanted + "::") for t in tags)


class LoopAnki:
    """Cards in memory, each on its own note; every search answered card by card for the terms Surasura sends
    (`is:new` · `is:suspended` · `tag:` · `flag:n` · `-` · `edited:n` = no edits), findCards and findNotes, alone or in a
    `multi`. Every action asked is kept: a write would show in `asked`."""

    def __init__(self, monkeypatch):
        self.cards = {}             # card id -> {"word", "new", "suspended", "tags", "flag", "note"}
        self.asked = []
        self.closed = False
        self.profile = "DevTest"
        monkeypatch.setattr(anki_connect, "find_cards", lambda url, q: self._ask("findCards", self._find(q)))
        monkeypatch.setattr(anki_connect, "find_notes", lambda url, q: self._ask(
            "findNotes", sorted({self.cards[c]["note"] for c in self._find(q)})))
        monkeypatch.setattr(anki_connect, "cards_info", lambda url, ids, chunk=250: self._ask(
            "cardsInfo", [{"cardId": c, "note": self.cards[c]["note"]} if c in self.cards else {} for c in ids]))
        monkeypatch.setattr(anki_connect, "notes_info", lambda url, ids, chunk=250: self._ask(
            "notesInfo", [self._note(n) for n in ids]))
        monkeypatch.setattr(anki_connect, "invoke", self._invoke)
        monkeypatch.setattr(anki_connect, "multi", self._multi)

    def _ask(self, action, answer):
        self.asked.append(action)
        if self.closed:
            raise AnkiError("Anki isn't running", kind="offline")
        return answer

    def _invoke(self, action, url, **params):
        self._ask(action, None)
        if action == "getActiveProfile":
            return self.profile
        return None

    def _multi(self, actions, url, timeout=60):
        self._ask("multi", None)
        out = []
        for a in actions:
            ids = self._find(a["params"]["query"])
            if a["action"] == "findNotes":
                ids = sorted({self.cards[c]["note"] for c in ids})
            out.append({"result": ids, "error": None})
        return out

    def add(self, card, word, new=False, suspended=False, tags=(), flag=0, note=None):
        self.cards[card] = {"word": word, "new": new, "suspended": suspended, "tags": list(tags), "flag": flag,
                            "note": note if note is not None else card + 1000}

    def set(self, card, **values):
        self.cards[card].update(values)

    def _note(self, note):
        card = next((c for c in self.cards.values() if c["note"] == note), None)
        if card is None:
            return {}
        return {"noteId": note, "modelName": "Lapis", "tags": [],
                "fields": {"Word": {"value": card["word"], "order": 0}}}

    def _find(self, query):
        assert f'deck:"{DECK}"' in query, query
        if '"tag:' in query or "prop:" in query or "introduced:" in query:
            return []                               # the backlog's and the young cards' reads: none of this test's
        terms = re.findall(r'(?<![\w"])-?[a-z]+:[^\s)"]+', query.replace(f'deck:"{DECK}"', ""))
        out = []
        for cid, card in sorted(self.cards.items()):
            ok = True
            for term in terms:
                neg, (key, value) = term.startswith("-"), term.lstrip("-").split(":", 1)
                if key == "is":
                    hit = card["suspended"] if value == "suspended" else card["new"] if value == "new" else False
                elif key == "tag":
                    hit = _tag_hit(card["tags"], value)
                elif key == "flag":
                    hit = card["flag"] == int(value)
                elif key == "edited":
                    hit = False                     # no card was edited
                else:
                    raise AssertionError(f"a term this stand-in doesn't know: {term}")
                ok = ok and (hit != neg)
            if ok:
                out.append(cid)
        return out


@pytest.fixture
def anki(monkeypatch):
    return LoopAnki(monkeypatch)


@pytest.fixture(autouse=True)
def connect_on():
    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"connect_enabled": True}, f)


def _settings():
    return settings_manager.load_settings()


def _sync(language, full=False):
    """One known-words sync, as the window runs it (the studied words, the new cards, the young ones, the moves)."""
    result, signal = anki_sync.sync_all(language, URL, [DECK], [], _settings(), include_suspended=False, full=full)
    assert not result.error, result.error
    return result, signal


def _entries(language):
    path = os.path.join(get_user_files_path(language), "KnownWord.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [w for w in json.load(f).get("words", []) if isinstance(w, dict)]


def _known(language):
    return {w["dictForm"] for w in _entries(language) if anki_sync._is_known(w)}


def _ignored(language):
    return set(word_lists._File(word_lists.list_path("ignore", language), language).words())


def _waiting(language):
    return [(s["word"], s["card"]) for s in swap_queue.waiting(language)]


def _baseline(language):
    """The first read: nothing signalled yet (Known's first read only records an offer)."""
    _sync(language)


# --- the reader ---------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_red_ignores_green_queues_a_swap_and_a_plain_suspend_means_nothing(anki, language):
    # why: the three moves are suspends with a reason; a suspend alone often says "a bad sentence" and is no move
    known, ignore, swap, plain, *_ = WORDS[language]
    _baseline(language)
    anki.add(1, known, suspended=True, tags=["marked"])
    anki.add(2, ignore, suspended=True, flag=RED)
    anki.add(3, swap, new=True, suspended=True, flag=GREEN)             # a new card: its sentence, not its word, is bad
    anki.add(4, plain, suspended=True)
    result, signal = _sync(language)
    assert _known(language) == {known}
    assert _ignored(language) == {ignore}
    assert _waiting(language) == [(swap, 3)]
    assert result.loop == {"sync": result.loop["sync"], "known": 1, "swap": 1, "ignored": 1, "unknown": 0}
    assert not WRITES & set(anki.asked), anki.asked                      # the reader only reads Anki


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_cards_already_flagged_at_the_first_read_are_read_and_another_colour_is_the_learners(anki, language):
    # why: testers flagged cards before the loop shipped (PROVISIONAL lean: read them, with Undo); orange is theirs
    ignore, swap, orange, *_ = WORDS[language]
    anki.add(1, ignore, suspended=True, flag=RED)
    anki.add(2, swap, suspended=True, flag=GREEN)
    anki.add(3, orange, suspended=True, flag=ORANGE)
    result, _ = _sync(language)
    assert _ignored(language) == {ignore} and _waiting(language) == [(swap, 2)]
    assert orange not in _known(language) and result.loop["ignored"] == 1 and result.loop["swap"] == 1


def test_a_move_is_read_once_and_nothing_is_written_when_nothing_moved(anki):
    ignore, *_ = WORDS["ja"]
    anki.add(1, ignore, suspended=True, flag=RED)
    _sync("ja")
    record = review_loop.record_path("ja")
    stamp = os.stat(record).st_mtime_ns
    result, _ = _sync("ja")
    assert result.loop is None and _ignored("ja") == {ignore}
    assert os.stat(record).st_mtime_ns == stamp                          # S19: nothing new, nothing written


def test_surasuras_own_suspends_and_leeches_are_never_a_move(anki):
    # why: Junban's later / out, Connect's shelf and Anki's leeches are suspends the learner didn't make
    a, b, c, d, *_ = WORDS["ja"]
    anki.add(1, a, suspended=True, flag=RED, tags=["Surasura::later"])
    anki.add(2, b, suspended=True, flag=GREEN, tags=["surasura::shelf"])
    anki.add(3, c, suspended=True, flag=RED, tags=["leech"])
    anki.add(4, d, suspended=True, flag=GREEN, tags=["Surasura::out"])
    result, _ = _sync("ja")
    assert result.loop is None and _ignored("ja") == set() and _waiting("ja") == []


def test_the_moves_search_reads_suspend_plus_red_and_suspend_plus_green_only():
    for move, flag in ((review_loop.IGNORE, "flag:1"), (review_loop.SWAP, "flag:3")):
        parts = review_loop.query(move, [DECK], {}).split()
        assert "is:suspended" in parts and flag in parts and "-tag:leech" in parts and "-tag:Surasura::later" in parts
        assert not [p for p in parts if p.startswith("-flag:")], parts
    assert review_loop.query(review_loop.IGNORE, [], {}) is None


# --- the move rule ------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("flag", [RED, GREEN])
def test_a_word_the_plain_sync_counted_known_is_moved_when_its_card_is_flagged(anki, language, flag):
    # why (Kotoba-WS2's note a): a studied card's word is known from the sync before its flag — Ignore / Swap must
    # move it, and the sync must never read it known again from that card (append-only would bring it straight back)
    word, other, *_ = WORDS[language]
    anki.add(1, word)                                                  # studied, not suspended: known
    anki.add(2, other)
    _sync(language)
    assert _known(language) == {word, other}
    anki.set(1, suspended=True, flag=flag)
    result, _ = _sync(language)
    assert _known(language) == {other}
    assert result.loop["unknown"] == 1 and result.total_known == 1
    entry = next(w for w in _entries(language) if w["dictForm"] == word)
    assert entry[word_marks.NOT_KNOWN]["was"] == {"knownStatus": "KNOWN", "hasCard": 1}   # kept, as it was
    assert (word in _ignored(language)) == (flag == RED)
    assert (_waiting(language) == [(word, 1)]) == (flag == GREEN)
    _sync(language, full=True)                                         # a full read of every studied card
    assert _known(language) == {other}


@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("flag", [RED, GREEN])
def test_a_studied_unsuspended_red_or_green_card_never_counts_known(anki, language, flag):
    # why (Kotoba-WS2's note b; lean: red never Known, suspended or not): the plain sync used to count it
    word, other, *_ = WORDS[language]
    anki.add(1, word, flag=flag)
    anki.add(2, other, flag=ORANGE)
    _sync(language)
    assert _known(language) == {other}
    assert anki_sync.scope_query([DECK]).endswith("-flag:1 -flag:3")


# --- Still learning ------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", ["ja", "zh"])
@pytest.mark.parametrize("how", ["studied", "marked", "deleted"])
def test_still_learning_turns_a_known_word_back_and_the_sync_never_reads_it_known_from_that_card(anki, language, how):
    # why (WL ⑦, the way back): marked, suspended or deleted, the word is not known again until a new card or a fresh
    # Known move says so
    word, *_ = WORDS[language]
    _baseline(language)
    if how == "marked":
        anki.add(1, word, suspended=True, tags=["marked"])               # a Known move
    else:
        anki.add(1, word)
    _sync(language)
    assert word in _known(language)
    if how == "deleted":
        del anki.cards[1]
    r = word_marks.apply(language, [(word, "learning")])
    assert r.error is None and r.done == [(word, None, "learning")]
    assert word not in _known(language) and word in word_marks.learning(language)
    _sync(language)
    _sync(language, full=True)
    assert word not in _known(language)
    assert word_marks.undo(language, r.undo_id).done                   # Undo: known again, as it was
    assert word in _known(language) and word not in word_marks.learning(language)


def test_after_still_learning_a_new_card_or_a_fresh_known_move_makes_it_known_again(anki):
    word, other, *_ = WORDS["ja"]
    anki.add(1, word, suspended=True, tags=["marked"])
    anki.add(9, other, suspended=True, tags=["marked"])               # (an empty answer never empties the signal's
    _sync("ja")                                                        # record: one other card keeps it honest)
    known_signal.accept_offer("ja", URL)
    assert word in _known("ja")
    word_marks.apply("ja", [(word, "learning")])
    _sync("ja")
    assert word not in _known("ja")                                    # the same card, still marked: not again
    anki.set(1, suspended=False)
    _sync("ja")
    anki.set(1, suspended=True)                                        # suspended + marked again: a fresh Known move
    _sync("ja")
    assert word in _known("ja")
    word_marks.apply("ja", [(word, "learning")])
    assert word not in _known("ja")
    anki.add(2, word, note=int(time.time() * 1000) + 60_000)          # a new card for it, made after, studied
    _sync("ja", full=True)
    assert word in _known("ja")


def test_still_learning_on_a_word_never_known_writes_nothing(anki):
    word, *_ = WORDS["zh"]
    r = word_marks.apply("zh", [(word, "learning")])
    assert r.done == [] and r.error is None and _entries("zh") == []


def test_a_surasura_known_word_still_learning_drops_its_mark_and_undo_brings_it_back():
    word, *_ = WORDS["ja"]
    word_marks.apply("ja", [(word, "known")])
    r = word_marks.apply("ja", [(word, "learning")])
    assert r.done == [(word, "known", "learning")] and word not in _known("ja")
    word_marks.undo("ja", r.undo_id)
    assert word_marks.marks("ja").get(word) == "known"


# --- Undo per sync ------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_undo_puts_the_lists_back_drops_its_swaps_touches_no_card_and_twice_is_nothing(anki, language):
    known, ignore, swap, studied, *_ = WORDS[language]
    anki.add(4, studied)
    _sync(language)                                                    # studied: known (and Known's first read)
    anki.add(1, known, suspended=True, tags=["marked"])
    anki.add(2, ignore, suspended=True, flag=RED)
    anki.add(3, swap, suspended=True, flag=GREEN)
    anki.set(4, suspended=True, flag=RED)                              # the move rule: a known word ignored
    result, _ = _sync(language)
    assert _known(language) == {known} and _ignored(language) == {ignore, studied}
    anki.asked.clear()
    answer = review_loop.undo(language, result.loop["sync"])
    assert answer["undone"] and set(answer["words"]) == {known, ignore, swap, studied}
    assert _known(language) == {studied}                               # back as it was before the sync
    assert _ignored(language) == set() and _waiting(language) == []
    assert [s["why"] for s in swap_queue.load(language)] == ["undone"]
    assert anki.asked == []                                            # Anki never asked: no card touched
    assert review_loop.undo(language, result.loop["sync"]) == {"undone": False, "words": [], "kept": []}
    again, _ = _sync(language)                                         # the cards keep their moves: not read again
    assert again.loop is None and _ignored(language) == set()


def test_undo_leaves_a_word_a_later_sync_moved(anki):
    word, *_ = WORDS["ja"]
    anki.add(1, word, suspended=True, flag=RED)
    first, _ = _sync("ja")
    anki.set(1, flag=GREEN)                                            # later: green — a swap now
    second, _ = _sync("ja")
    answer = review_loop.undo("ja", first.loop["sync"])
    assert answer["kept"] == [word] and _waiting("ja") == [(word, 1)]  # the later move stands


# --- a card's moves over time -------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_red_then_green_ends_a_swap_off_the_ignore_list_and_green_then_red_drops_the_swap(anki, language):
    a, b, *_ = WORDS[language]
    anki.add(1, a, suspended=True, flag=RED)
    anki.add(2, b, suspended=True, flag=GREEN)
    _sync(language)
    anki.set(1, flag=GREEN)
    anki.set(2, flag=RED)
    _sync(language)
    assert _ignored(language) == {b}
    assert _waiting(language) == [(a, 1)]
    dropped = [s for s in swap_queue.load(language) if s["state"] == swap_queue.DROPPED]
    assert [(s["word"], s["why"]) for s in dropped] == [(b, "taken back")]


def test_a_known_move_after_an_ignore_takes_the_word_off_the_ignore_list(anki):
    word, *_ = WORDS["ja"]
    _baseline("ja")
    anki.add(1, word, suspended=True, flag=RED)
    _sync("ja")
    anki.set(1, flag=0, tags=["marked"])                               # red off, marked: Known now
    result, _ = _sync("ja")
    assert word in _known("ja") and word not in _ignored("ja") and result.loop["known"] == 1


def test_a_deleted_swap_card_keeps_its_entry_and_an_unflagged_one_is_taken_back(anki):
    a, b, *_ = WORDS["zh"]
    anki.add(1, a, suspended=True, flag=GREEN)
    anki.add(2, b, suspended=True, flag=GREEN)
    _sync("zh")
    del anki.cards[1]                                                  # deleted: the learner still wants the word
    anki.set(2, suspended=False, flag=0)                               # taken back
    _sync("zh")
    assert _waiting("zh") == [(a, 1)]


# --- Anki closed, empty states, the record ----------------------------------------------------------------------- #
def test_a_sync_with_anki_closed_reads_nothing_and_changes_nothing(anki):
    word, *_ = WORDS["ja"]
    anki.add(1, word, suspended=True, flag=RED)
    anki.closed = True
    result, signal = anki_sync.sync_all("ja", URL, [DECK], [], _settings())
    assert result.error and signal is None
    assert not os.path.exists(review_loop.record_path("ja")) and _ignored("ja") == set()


def test_anki_closing_between_the_known_read_and_the_moves_keeps_the_known_words(anki, monkeypatch):
    word, *_ = WORDS["ja"]
    anki.add(1, word, suspended=True, flag=RED)
    monkeypatch.setattr(anki_connect, "multi", lambda *a, **k: (_ for _ in ()).throw(AnkiError("gone", kind="offline")))
    out = review_loop.read("ja", URL, [DECK], [], _settings())
    assert out["loop"] is None and "gone" in out["loop_error"] and _ignored("ja") == set()


def test_empty_states_no_decks_no_cards_no_files(anki):
    assert review_loop.read("ja", URL, [], [], _settings())["loop"] is None
    result, _ = _sync("ja")
    assert result.loop is None and _entries("ja") == [] and swap_queue.waiting("ja") == []


def test_an_unreadable_record_is_never_written_over(anki):
    path = review_loop.record_path("ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    anki.add(1, WORDS["ja"][0], suspended=True, flag=RED)
    with pytest.raises(review_loop.Unreadable):
        review_loop.read("ja", URL, [DECK], [], _settings())
    with open(path, encoding="utf-8") as f:
        assert f.read() == "{not json"


def test_another_profiles_cards_are_their_own(anki):
    # why: card ids are a profile's own; switching DevTest -> User 1 and back must not queue a swap twice
    word, *_ = WORDS["ja"]
    anki.add(1, word, suspended=True, flag=GREEN)
    _sync("ja")
    anki.profile = "User 1"
    _sync("ja")
    anki.profile = "DevTest"
    result, _ = _sync("ja")
    assert result.loop is None and len(swap_queue.load("ja")) == 1


# --- the swap queue's contract ------------------------------------------------------------------------------------- #
def test_the_swap_queue_made_and_drop_and_nothing_ever_deletes_an_entry(anki):
    a, b, *_ = WORDS["ja"]
    anki.add(1, a, suspended=True, flag=GREEN)
    anki.add(2, b, suspended=True, flag=GREEN)
    _sync("ja")
    first, second = swap_queue.waiting("ja")
    assert set(first) == {"id", "word", "card", "note", "queued", "sync", "state", "made", "why"}
    assert swap_queue.made("ja", first["id"], 99)["made"]["note"] == 99
    assert swap_queue.drop("ja", second["id"], "ignored")["why"] == "ignored"
    assert swap_queue.waiting("ja") == [] and len(swap_queue.load("ja")) == 2
    with pytest.raises(ValueError):
        swap_queue.drop("ja", first["id"], "because")


def test_ignore_wins_when_one_word_has_both_in_one_sync(anki):
    word, *_ = WORDS["ja"]
    anki.add(1, word, suspended=True, flag=RED)
    anki.add(2, word, suspended=True, flag=GREEN, note=2002)
    result, _ = _sync("ja")
    assert _ignored("ja") == {word} and _waiting("ja") == [] and result.loop["swap"] == 0


# --- the date known ------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_every_entry_surasura_appends_keeps_the_date_it_became_known(anki, language):
    synced, marked, signal, *_ = WORDS[language]
    _baseline(language)
    anki.add(1, synced)
    anki.add(2, signal, suspended=True, tags=["marked"])
    _sync(language)
    word_marks.apply(language, [(marked, "known")])
    for entry in _entries(language):
        assert entry["knownAt"] and entry["knownAt"] == entry["created"], entry


def test_a_swap_asked_with_a_line_keeps_its_line_id_through_undo():
    # why (journey v3 SPEC §6 / §3.3): the journey page queues a swap with the sentence the learner picked; a green
    # flag from Anki has none (Swap picks the line); Undo keeps the record whole
    word, *_ = WORDS["zh"]
    entry = swap_queue.add("zh", word, 7, 1007, "s1", line_id="ep03:0412")
    plain = swap_queue.add("zh", WORDS["zh"][1], 8, 1008, "s1")
    assert entry["line_id"] == "ep03:0412" and "line_id" not in plain
    swap_queue.drop_sync("zh", "s1")
    kept = {s["card"]: s for s in swap_queue.load("zh")}
    assert kept[7]["line_id"] == "ep03:0412" and kept[7]["why"] == "undone"
