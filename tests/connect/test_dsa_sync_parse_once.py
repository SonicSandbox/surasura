"""DSA-SYNC (3.0.19, the DSA audit's G10) — one known-words sync parses KnownWord.json once, a Known mark keeps the next
sync a delta, and the review loop's Undo writes the known words once.

Pinned here, end to end through Kyou-LR's stand-in Anki (`LoopAnki`) and the real sync (`anki_sync.sync_all`):
- **parsed once a sync**: the studied words, Known from Anki, the review loop's Ignore and Swap, the read-back and the
  sync's total read ONE parse of the file, handed down (before: up to 9 a sync, ~0.05 s each at 9,000 words);
- **another program's write is always read**: the handed-down copy is used only while the file's bytes are the ones
  it parsed or wrote, so a write in between (the window's mark, another program) is parsed again, never lost;
- **the Known mark follows the sync's record**: it only appends, so the sync's recorded signature moves with it and
  the next sync stays a delta (before: every Known mark made the next sync a full one — every note in scope read);
- **one Undo, one write**: a sync's Known words taken out together (one parse, one dated copy, one write), never once
  per word; the lists' own write is word_marks' one, as before;
- the files a sync leaves are the same (KnownWord.json, the Ignore list, the swap queue).

What a wrong answer would cost: a stale copy written over another program's write loses the learner's known words (the
file is user data: CLAUDE.md §4); a Known mark that leaves the next sync full costs every later sync its delta. Real
words (ja + zh, tests/Test Resources' sentences); every file in the test's temp root; never a live Anki.
"""
import json
import os

import pytest

from app import anki_sync, path_utils
from app.connect import known_signal, review_loop, swap_queue
from app.path_utils import get_user_files_path
from app.services import word_marks
from tests.connect.test_kyou_lr_review_loop import (DECK, GREEN, RED, URL, WORDS, LoopAnki, _ignored, _known,
                                                     _settings, _sync, _waiting, connect_on)  # noqa: F401 (fixture)


@pytest.fixture
def anki(monkeypatch):
    return LoopAnki(monkeypatch)


def _path(language):
    return os.path.join(get_user_files_path(language), "KnownWord.json")


class Count:
    """Every parse of KnownWord.json (anki_sync's `json.loads`: the sync's own state and records are read with
    `json.load`), every write of it and every dated copy of it, while counting is on."""

    def __init__(self, monkeypatch, language):
        self.parses = self.writes = self.backups = 0
        self.on = False
        path = _path(language)
        real_loads, real_bytes, real_backup = json.loads, anki_sync._atomic_write_bytes, path_utils.backup_to_trash
        me = self

        class _Json:
            def __getattr__(self, name):
                return getattr(json, name)

            @staticmethod
            def loads(text, *a, **k):
                me.parses += me.on
                return real_loads(text, *a, **k)

        def write(p, data):
            if os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(path)):
                me.writes += me.on
            return real_bytes(p, data)

        def backup(p, *a, **k):
            if os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(path)):
                me.backups += me.on
            return real_backup(p, *a, **k)
        monkeypatch.setattr(anki_sync, "json", _Json())
        monkeypatch.setattr(anki_sync, "_atomic_write_bytes", write)
        monkeypatch.setattr(path_utils, "backup_to_trash", backup)

    def __enter__(self):
        self.parses = self.writes = self.backups = 0
        self.on = True
        return self

    def __exit__(self, *exc):
        self.on = False


# --- parsed once a sync -------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_sync_with_every_move_from_the_phone_parses_the_known_words_once(anki, monkeypatch, language):
    # why: the sync, Known from Anki, the loop's lists, its read-back and the total each parsed the file again (7 here)
    known, ignore, swap, studied, *_ = WORDS[language]
    anki.add(4, studied)
    _sync(language)                                                  # studied: known (and Known's first read)
    anki.add(1, known, suspended=True, tags=["marked"])
    anki.add(2, ignore, suspended=True, flag=RED)
    anki.add(3, swap, suspended=True, flag=GREEN)
    anki.set(4, suspended=True, flag=RED)                            # the move rule: a known word ignored
    with Count(monkeypatch, language) as n:
        result, _ = _sync(language)
    assert result.loop["known"] == 1 and result.loop["ignored"] == 2 and result.loop["swap"] == 1
    assert _known(language) == {known} and _ignored(language) == {ignore, studied}
    assert _waiting(language) == [(swap, 3)]
    assert result.total_known == 1                                   # the total from the copy handed down
    assert n.parses == 1, n.parses
    assert n.writes == 2, n.writes                                   # Known's append, the lists' write: as before


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_known_word_after_a_loop_move_parses_once_too(anki, monkeypatch, language):
    # why: the loop reads each word's state before clearing its own mark (`word_marks.states`: two parses each time)
    word, studied, *_ = WORDS[language]
    anki.add(4, studied)                                             # a known-words file to parse
    anki.add(1, word, suspended=True, flag=RED)
    _sync(language)
    assert _ignored(language) == {word}
    anki.set(1, flag=0, tags=["marked"])                             # unflagged, then suspended and marked: Known
    with Count(monkeypatch, language) as n:
        result, _ = _sync(language)
    assert _known(language) == {word, studied} and _ignored(language) == set()
    assert result.loop["known"] == 1
    assert n.parses == 1, n.parses


def test_a_quiet_sync_parses_once_and_writes_nothing(anki, monkeypatch):
    # why: nothing from the phone — the sync's own parse only, and no write (charter S19)
    word, *_ = WORDS["ja"]
    anki.add(1, word)
    _sync("ja")
    before = open(_path("ja"), "rb").read()
    with Count(monkeypatch, "ja") as n:
        result, _ = _sync("ja")
    assert result.loop is None and n.parses == 1 and n.writes == 0
    assert open(_path("ja"), "rb").read() == before


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_another_programs_write_between_the_sync_and_the_loop_is_read_not_written_over(anki, monkeypatch, language):
    # why: the copy handed down from the sync crosses a gap with the lock let go (the new cards, the young cards): a
    # word the window marked known meanwhile must survive the loop's write
    known, ignore, studied, by_hand, *_ = WORDS[language]
    anki.add(4, studied)
    _sync(language)
    anki.add(1, known, suspended=True, tags=["marked"])
    anki.add(2, ignore, suspended=True, flag=RED)
    real = anki_sync.sync_young

    def meanwhile(*a, **k):
        word_marks.apply(language, [(by_hand, "known")])             # another writer, between the two holds
        return real(*a, **k)
    monkeypatch.setattr(anki_sync, "sync_young", meanwhile)
    _sync(language)
    assert _known(language) == {known, studied, by_hand}
    assert _ignored(language) == {ignore}


def test_the_handed_down_copy_parses_again_when_the_bytes_change():
    # why: the copy is the bytes it read or wrote — any other bytes (another writer, the same size and second too) parse
    a, b, *_ = WORDS["ja"]
    path = _path("ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    known = anki_sync.KnownFile("ja")
    assert known.read() == (None, None)                              # no file yet
    data = anki_sync._fresh_file([anki_sync._entry(a, 1, "ja", "2026-11-25T15:00:00")])
    known.write(data)
    assert known.read()[1][0]["dictForm"] == a
    with open(path, "rb") as f:
        raw = f.read()
    with open(path, "wb") as f:                                      # same length, other bytes, written in place
        f.write(raw.replace(a.encode("utf-8"), b.encode("utf-8")))
    assert known.read()[1][0]["dictForm"] == b
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"words": [')
    with pytest.raises(anki_sync._KnownFileError):
        known.read()
    os.remove(path)
    assert known.read() == (None, None)


# --- the Known mark follows the sync's record ---------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_known_mark_keeps_the_next_sync_a_delta(anki, language):
    # why: the mark only appends, so the sync's view of the file holds — before, it left the next sync a full one
    known, studied, *_ = WORDS[language]
    anki.add(4, studied)
    _sync(language)
    anki.add(1, known, suspended=True, tags=["marked"])
    first, _ = _sync(language)
    assert first.loop["known"] == 1 and _known(language) == {known, studied}
    assert anki_sync.load_state(language)["known_sig"] == anki_sync.known_signature(_path(language))
    again, _ = _sync(language)
    assert again.mode == "delta"


def test_the_accepted_offer_follows_too(anki):
    # why: the one-time offer's words are appended by the same mark
    word, studied, *_ = WORDS["ja"]
    anki.add(4, studied)
    anki.add(1, word, suspended=True, tags=["marked"])               # signalled before the first read: an offer
    _sync("ja")
    assert known_signal.accept_offer("ja", URL) == [word]
    assert anki_sync.load_state("ja")["known_sig"] == anki_sync.known_signature(_path("ja"))
    again, _ = _sync("ja")
    assert again.mode == "delta" and _known("ja") == {word, studied}


def test_a_known_mark_after_another_writer_leaves_the_next_sync_full(anki, monkeypatch):
    # why: the follow is only for a file the sync's record still describes — an outside edit keeps its full sync
    known, studied, *_ = WORDS["ja"]
    anki.add(4, studied)
    _sync("ja")
    anki.add(1, known, suspended=True, tags=["marked"])
    real = anki_sync.sync_young

    def edited(*a, **k):
        with open(_path("ja"), "a", encoding="utf-8") as f:          # an editor's save, outside Surasura
            f.write("\n")
        return real(*a, **k)
    monkeypatch.setattr(anki_sync, "sync_young", edited)
    _sync("ja")
    monkeypatch.setattr(anki_sync, "sync_young", real)
    again, _ = _sync("ja")
    assert again.mode == "full"


# --- one Undo, one write ------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_undo_of_a_syncs_known_words_writes_and_backs_up_the_file_once(anki, monkeypatch, language):
    # why: each Known word was taken out on its own — a parse, a dated 3 MB copy and a write per word
    a, b, c, studied, *_ = WORDS[language]
    anki.add(4, studied)
    _sync(language)
    for card, word in ((1, a), (2, b), (3, c)):
        anki.add(card, word, suspended=True, tags=["marked"])
    result, _ = _sync(language)
    assert result.loop["known"] == 3 and _known(language) == {a, b, c, studied}
    anki.asked.clear()
    with Count(monkeypatch, language) as n:
        answer = review_loop.undo(language, result.loop["sync"])
    assert answer["undone"] and set(answer["words"]) == {a, b, c}
    assert _known(language) == {studied}
    assert n.writes == 1 and n.backups == 1 and n.parses == 1, (n.writes, n.backups, n.parses)
    assert [m["undone"] is not None for m in known_signal.load(language)["marked"]] == [True] * 3
    assert anki.asked == []                                          # no card touched


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_undo_of_every_move_puts_each_file_back_and_parses_once(anki, monkeypatch, language):
    # why: the lists' Undo and the Known words' read one parse; the swap queue drops its own entries as before
    known, ignore, swap, studied, *_ = WORDS[language]
    anki.add(4, studied)
    _sync(language)
    anki.add(1, known, suspended=True, tags=["marked"])
    anki.add(2, ignore, suspended=True, flag=RED)
    anki.add(3, swap, suspended=True, flag=GREEN)
    result, _ = _sync(language)
    with Count(monkeypatch, language) as n:
        review_loop.undo(language, result.loop["sync"])
    assert _known(language) == {studied} and _ignored(language) == set() and _waiting(language) == []
    assert [s["why"] for s in swap_queue.load(language)] == ["undone"]
    assert n.parses == 1, n.parses


def test_the_per_word_undo_of_the_known_window_is_unchanged(anki, monkeypatch):
    # why: the small window's Undo per word keeps its own call and answer
    word, other, *_ = WORDS["ja"]
    anki.add(4, other)
    _sync("ja")
    anki.add(1, word, suspended=True, tags=["marked"])
    _sync("ja")
    assert known_signal.undo("ja", word, URL, cards_too=False) == {"removed": True, "unsuspended": []}
    assert _known("ja") == {other}
    assert known_signal.undo("ja", word, URL, cards_too=False) == {"removed": False, "unsuspended": []}
