"""The ✓ chip counts every word of an episode that has a card, wherever it was made (Michi-CK2; Sonic's ruling 2,
2026-11-17, on the lead's route 2026-11-18): `app/services/card_chip.py`, the store's `made_words_of`.

Why these matter: the chip was the cards made *from* the episode alone — a word carded from an earlier episode, another
show or by hand in Anki never counted, so a well-studied episode read as barely touched. Its cards now come from the
known-words sync's new cards (`anki_backlog.json`), the studied cards Anki last said (the word card's own read, handed
on), and the words Connect made cards for that still have a note in Anki. Only mined files are counted (the chip shows
only on rows in Anki), and a change moves only the answers it touches. On real Japanese and Chinese files, tokenized
into a real token store; every answer is checked against a count made the slow way.
"""
import json
import os
import random
import shutil
import time

import pytest

from app import token_index as ti
from app.services import card_chip

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")
# two "shows" of two episodes each, from the real test texts
FILES = {"ja": {1: ("星の工房", "placed_episode.srt"), 2: ("星の工房", "readings_sample.srt"),
                3: ("雨の書庫", "phrases_sample.srt"), 4: ("雨の書庫", "repeated_lines.ja.srt")},
         "zh": {1: ("夜市", "night_market.srt"), 2: ("夜市", "repeated_lines.zh.srt"),
                3: ("故事", "chinese_text_1.txt"), 4: ("故事", "mixed_script_transcript.txt")}}


class Lib:
    """A token store over the four files, and what the counter is handed: the backlog, the made words per item."""

    def __init__(self, root, language, built):
        self.language = language
        self.data, built_db = built
        self.db = os.path.join(root, f"tokens_{language}.db")
        shutil.copy(built_db, self.db)                         # each test its own copy of the one tokenized store
        self.cache = os.path.join(root, f"card_chip_{language}.json")
        self.rel = {item: f"HighPriority/{show}/{name}" for item, (show, name) in FILES[language].items()}
        self.backlog, self.made, self.made_reads, self.stamp = set(), {}, [], [0]
        self.words = {i: self._lemmas(i) for i in self.rel}

    def _lemmas(self, item):
        reader = ti.open_reader(self.language, self.db)
        try:
            row = reader.conn.execute("SELECT counts FROM files WHERE path=?",
                                      (ti._norm(os.path.join(self.data, *self.rel[item].split("/"))),)).fetchone()
            return {k.partition("|")[0] for k in ti._decode_counts(row[0])}
        finally:
            reader.close()

    def chips(self, got=None):
        def read_made(_language, ids):
            self.made_reads.append(sorted(ids))
            return {i: set(self.made.get(i, ())) for i in ids}
        return card_chip.Chips(self.language, on_change=(got.append if got is not None else None),
                               open_tokens=lambda: ti.open_reader(self.language, self.db), data_dir=self.data,
                               read_made=read_made, read_backlog=lambda _l: set(self.backlog),
                               backlog_stamp=lambda _l: self.stamp[0], cache_file=self.cache)

    def ask(self, items, cards=None):
        """The reader's asks for `items` in Anki (each with `cards` cards, else as many as it made)."""
        return {i: (self.rel[i], 1, cards if cards is not None else max(1, len(self.made.get(i, ())))) for i in items}

    def expected(self, key, studied, known=()):
        """The slow count (CARD-LEFT): (left, done) — the words of `key` (an item, or a row's items: each word once)
        with a card anywhere and the ones it made itself, split by whether Surasura counts them known."""
        ids = key if isinstance(key, tuple) else (key,)
        words = set().union(*(self.words[i] for i in ids))
        own = set().union(*(self.made.get(i, set()) for i in ids))
        cards = self.backlog | set(studied) | set().union(*self.made.values()) if self.made else \
            self.backlog | set(studied)
        carded = {w for w in words if w in cards} | own
        return len(carded - set(known)), len(carded & set(known))


def _tokenized(root, language):
    """The four files copied into a data folder and tokenized once into a token store (the real tokenizer) ->
    (data folder, store path)."""
    data = os.path.join(root, "data", language)
    paths = []
    for show, name in FILES[language].values():
        path = os.path.join(data, "HighPriority", show, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy(os.path.join(RES, language, name), path)
        paths.append(path)
    db = os.path.join(root, f"built_{language}.db")
    store = ti.open_store(language, path=db)
    try:
        store.reconcile(paths, ti.make_tokenizer(language), build_signature=ti.build_signature(language))
        # (CARD-LEFT) and the known words normalized, as the indexer leaves every store: none known here
        store.set_cached_known(ti.known_signature(os.path.join(root, "KnownWord.json")), set(), set(), suffix="")
    finally:
        store.close()
    return data, db


@pytest.fixture(scope="module")
def _built(tmp_path_factory):
    made = {}

    def get(language):
        if language not in made:
            made[language] = _tokenized(str(tmp_path_factory.mktemp(f"chip-{language}")), language)
        return made[language]
    return get


@pytest.fixture(params=["ja", "zh"])
def lib(request, tmp_path, _built):
    return Lib(str(tmp_path), request.param, _built(request.param))


def _pick(words, n, seed):
    return sorted(random.Random(seed).sample(sorted(words), n))


def _settle(chips):
    assert chips.idle(10)


def test_card_chip_counts_every_word_of_an_episode_with_a_card_wherever_it_was_made(lib):
    """Ep 1's words carded from ep 2 (Connect's), from the backlog (another show's new cards) and studied in Anki all
    count; the words ep 1 made itself are the row's own count, never counted twice."""
    shared = lib.words[1] & lib.words[2]
    lib.made = {1: set(_pick(lib.words[1], 3, 1)), 2: set(_pick(shared, 4, 2))}
    lib.backlog = set(_pick(lib.words[1] | lib.words[3], 6, 3))
    studied = set(_pick(lib.words[1] | lib.words[4], 8, 4))
    got = []
    chips = lib.chips(got)
    try:
        chips.studied(studied)
        chips.want(lib.ask([1, 2, 3, 4]))
        _settle(chips)
        answers = chips.answers()
        for item in (1, 2, 3, 4):
            assert answers[item] == lib.expected(item, studied), item
        assert answers[1][0] > 0, "ep 1 holds words carded elsewhere"
        assert got and got[-1] == answers
    finally:
        chips.close()


def test_card_chip_a_card_made_by_hand_in_anki_counts_once_anki_says_it_is_studied(lib):
    """A word no episode made a card for, studied in Anki (made by hand): every mined episode holding it gains one."""
    lib.made = {1: set(_pick(lib.words[1], 2, 5))}
    chips = lib.chips()
    try:
        chips.want(lib.ask([1, 2, 3, 4]))
        _settle(chips)
        before = chips.answers()
        hand = next(w for w in sorted(lib.words[1] & lib.words[3]) if w not in lib.made[1])
        chips.studied({hand})
        _settle(chips)
        after = chips.answers()
        for item in (1, 2, 3, 4):
            assert after[item][0] == before[item][0] + (hand in lib.words[item]), item
            assert after[item] == lib.expected(item, {hand})
    finally:
        chips.close()


def test_card_chip_a_card_deleted_in_anki_leaves_the_count(lib):
    """A studied card deleted in Anki: the next read doesn't hold it, and the episodes holding its word lose one. A card
    Connect made from ep 2 and deleted (its notes gone at the sync, ep 2's cards fewer): ep 1 loses that word too."""
    word = sorted(lib.words[1] & lib.words[2])[0]
    other = sorted(lib.words[1] & lib.words[2])[1]
    studied = {word, other}
    lib.made = {2: {other}}
    chips = lib.chips()
    try:
        chips.studied(studied)
        chips.want(lib.ask([1, 2]))
        _settle(chips)
        assert chips.answers()[1] == lib.expected(1, studied) == (2, 0)
        chips.studied({other})                                 # the card of `word` deleted in Anki
        _settle(chips)
        assert chips.answers()[1] == (1, 0)
        studied = set()
        chips.studied({"∅"})                              # Anki's next read: `other`'s card deleted too
        lib.made = {2: set()}                                  # ... and its notes gone from Connect's record
        chips.want(lib.ask([2], cards=0) | {1: (lib.rel[1], 1, 1)})
        _settle(chips)
        assert chips.answers()[1] == (0, 0)
    finally:
        chips.close()


def test_card_chip_an_empty_answer_from_anki_keeps_the_last_studied_words(lib):
    """Anki answering with no studied card where there were some (another profile, renamed decks) keeps them, as the
    backlog keeps its last: the chip never drops to its own cards for a profile switch."""
    studied = set(_pick(lib.words[1], 5, 6))
    chips = lib.chips()
    try:
        chips.studied(studied)
        chips.want(lib.ask([1]))
        _settle(chips)
        before = chips.answers()[1]
        assert before == (5, 0)
        chips.studied(set())
        _settle(chips)
        assert chips.answers()[1] == before
    finally:
        chips.close()


def test_card_chip_anki_closed_at_the_next_open_keeps_the_last_count(lib):
    """Next session, Anki closed (no studied read): the counter reads the studied words it saved, so the chip keeps its
    count — the reader's first build reads the saved answers too (never its own cards alone, then the whole)."""
    lib.made = {2: set(_pick(lib.words[2], 3, 7))}
    lib.backlog = set(_pick(lib.words[3], 3, 8))
    studied = set(_pick(lib.words[1] | lib.words[3], 9, 9))
    first = lib.chips()
    first.studied(studied)
    first.want(lib.ask([1, 2, 3, 4]), [(1, 2), (3, 4)])
    _settle(first)
    answers = first.answers()
    first.close()
    assert first.idle(10)
    with open(lib.cache, encoding="utf-8") as f:
        assert sorted(json.load(f)["studied"]) == sorted(studied)
    again = lib.chips()
    try:
        assert again.seeded() == answers, "the last answers, before any count"
        again.want(lib.ask([1, 2, 3, 4]), [(1, 2), (3, 4)])
        _settle(again)
        assert again.answers() == answers
    finally:
        again.close()


def test_card_chip_a_row_of_several_files_counts_each_word_once(lib):
    """A show's row: its two episodes' words each once (a word in both counts one), less what either made."""
    lib.made = {1: set(_pick(lib.words[1], 2, 10))}
    studied = set(_pick(lib.words[1] & lib.words[2], 6, 11)) | set(_pick(lib.words[2], 4, 12))
    chips = lib.chips()
    try:
        chips.studied(studied)
        chips.want(lib.ask([1, 2]), [(1, 2)])
        _settle(chips)
        answers = chips.answers()
        assert answers[(1, 2)] == lib.expected((1, 2), studied)
        assert answers[(1, 2)][0] < answers[1][0] + answers[2][0], "a word in both episodes counts once on the row"
    finally:
        chips.close()


def test_card_chip_steps_through_the_index_agree_with_a_full_count(lib):
    """Forty changes in a row — studied reads, backlog syncs, Connect's batches, files asked and let go — and after
    each the answers equal the slow count: the one-step updates never drift from a recount."""
    rnd = random.Random(13)
    every = sorted(set().union(*lib.words.values()))
    studied = set()
    asked = {1, 2}
    chips = lib.chips()
    try:
        for step in range(40):
            kind = rnd.choice(("studied", "backlog", "made", "ask"))
            if kind == "studied":
                studied = set(rnd.sample(every, rnd.randint(1, 30)))
                chips.studied(studied)
            elif kind == "backlog":
                lib.backlog = set(rnd.sample(every, rnd.randint(0, 20)))
                lib.stamp[0] += 1
            elif kind == "made":
                item = rnd.choice(sorted(asked))
                lib.made[item] = set(rnd.sample(sorted(lib.words[item]), rnd.randint(0, 8)))
            else:
                asked = set(rnd.sample([1, 2, 3, 4], rnd.randint(1, 4)))
            for gone in {1, 2, 3, 4} - asked:
                lib.made.pop(gone, None)
            chips.want({i: (lib.rel[i], 1, (step, len(lib.made.get(i, ())))) if i in asked else None
                        for i in (1, 2, 3, 4)}, [tuple(sorted(asked))] if len(asked) > 1 else [])
            _settle(chips)
            answers = chips.answers()
            for item in asked:
                assert answers[item] == lib.expected(item, studied), (step, kind, item)
            if len(asked) > 1:
                key = tuple(sorted(asked))
                assert answers[key] == lib.expected(key, studied), (step, kind)
            assert not {i for i in answers if not isinstance(i, tuple)} - asked, "a file let go keeps no answer"
    finally:
        chips.close()


def test_card_chip_reads_only_the_mined_files_and_hands_on_only_what_moved(lib):
    """An episode not in Anki is never read; asking the same again reads nothing and hands nothing on; a Connect batch
    (an episode's cards rose) reads that episode's made words alone."""
    got = []
    chips = lib.chips(got)
    try:
        chips.studied(set(_pick(lib.words[1], 4, 14)))
        chips.want({**lib.ask([1, 2]), 3: None, 4: None})
        _settle(chips)
        assert chips.read_files == 2 and set(chips.answers()) == {1, 2}
        handed, reads = len(got), list(lib.made_reads)
        chips.want(lib.ask([1, 2]))
        _settle(chips)
        assert len(got) == handed and lib.made_reads == reads and chips.read_files == 2, "the same asks: nothing"
        lib.made = {2: set(_pick(lib.words[2], 3, 15))}
        chips.want(lib.ask([2], cards=3))
        _settle(chips)
        assert lib.made_reads[-1] == [2] and chips.read_files == 2, "a batch: its made words, no file again"
    finally:
        chips.close()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_card_chip_made_words_of_keeps_only_cards_still_in_anki(language):
    """The store's made words for the chip: a word whose notes Anki no longer has (`notes_gone` at a sync) is left out,
    its row kept (never made again); every other word of the item is there."""
    from tests.test_library_store_support import migrated, names
    store = migrated(language, shows=1, episodes=2)
    try:
        a, b = store.ids("now")[:2]
        words = names(language)[3:6]
        store.record_made(a, [(words[0], [501]), (words[1], [502])])
        store.record_made(b, [(words[2], [503])])
        assert store.made_words_of([a, b]) == {a: {words[0], words[1]}, b: {words[2]}}
        store.notes_gone([502])
        assert store.made_words_of([a, b, 999999]) == {a: {words[0]}, b: {words[2]}, 999999: set()}
        assert words[1] in store.made(a), "its row stays (never made again unless asked)"
    finally:
        store.close()


def test_card_chip_a_file_the_token_store_hasnt_counted_has_no_count_and_its_cards_leave_when_it_is_let_go(lib):
    """An episode in Anki whose file the token store holds no count of (not read yet): no answer for it, while the
    words Connect made from it still count on the others; let go (its row gone), its words leave the card set too —
    never held on by a file that was never read. Review (own read): its made words leaked."""
    word = sorted(lib.words[1])[0]
    lib.rel[9] = "HighPriority/まだ/未読.srt"
    lib.made = {9: {word}}
    chips = lib.chips()
    try:
        chips.want(lib.ask([1, 9]))
        _settle(chips)
        answers = chips.answers()
        assert 9 not in answers and answers[1] == (1, 0), "the uncounted file's card counts on ep 1"
        chips.forget([9])
        _settle(chips)
        assert chips.answers()[1] == (0, 0)
    finally:
        chips.close()


def test_card_chip_the_word_cards_read_before_the_first_ask_never_empties_the_last_count(lib):
    """Next session, the word card's Anki read lands before the reader's first ask: no answer is handed on until a
    round has counted asked files — the last answers on disk stay the chip's (review H-F5: it handed on {})."""
    studied = set(_pick(lib.words[1], 6, 16))
    first = lib.chips()
    first.studied(studied)
    first.want(lib.ask([1, 2]))
    _settle(first)
    answers = first.answers()
    first.close()
    assert first.idle(10)
    got = []
    again = lib.chips(got)
    try:
        assert again.seeded() == answers
        again.studied(studied | {"∅"})                        # Anki read first, nothing asked yet
        _settle(again)
        assert got == [] and again.answers() == answers
        again.want(lib.ask([1, 2]))
        _settle(again)
        assert again.answers() == answers, "∅ is in no file: the same count"
    finally:
        again.close()


def test_card_chip_a_token_store_busy_for_a_moment_is_read_again_by_itself(lib, monkeypatch):
    """The token store locked as the round reads (another program's write): the round is tried again a moment later by
    itself — never left uncounted until something else asks (review H-F4)."""
    import sqlite3
    monkeypatch.setattr(card_chip, "RETRY_S", 0.05)
    studied = set(_pick(lib.words[1], 5, 17))

    class Locked:
        class conn:
            @staticmethod
            def execute(*_a):
                raise sqlite3.OperationalError("database is locked")

        @staticmethod
        def close():
            pass
    opened = []

    def open_tokens():
        opened.append(1)
        return Locked() if len(opened) == 1 else ti.open_reader(lib.language, lib.db)
    chips = lib.chips()
    chips._open_tokens = open_tokens
    try:
        chips.studied(studied)
        chips.want(lib.ask([1]))
        deadline = time.monotonic() + 5
        while chips.answers().get(1) is None and time.monotonic() < deadline:
            time.sleep(0.02)
        _settle(chips)
        assert chips.answers().get(1) == (5, 0) and len(opened) == 2
    finally:
        chips.close()


def test_card_chip_a_rows_file_no_longer_counted_leaves_the_rows_count(lib):
    """A show's row of two episodes; one episode's file changes and the token store holds no count of it yet: the row
    is counted again from the other episode alone — never left with the old file's words (mutant M12)."""
    studied = set(_pick(lib.words[1] | lib.words[2], 10, 18))
    chips = lib.chips()
    try:
        chips.studied(studied)
        chips.want(lib.ask([1, 2]), [(1, 2)])
        _settle(chips)
        assert chips.answers()[(1, 2)] == lib.expected((1, 2), studied)
        lib.rel[2] = "HighPriority/星の工房/編集中.srt"            # its file changed: not counted yet
        chips.want({2: (lib.rel[2], 2, 1)})
        _settle(chips)
        answers = chips.answers()
        assert 2 not in answers
        assert answers[(1, 2)] == lib.expected(1, studied), "the row from episode 1's words alone"
    finally:
        chips.close()


def _files_out(db):
    """The token store's per-file counts taken out, as an update's schema bump leaves it: the first writer (the indexer,
    a Generate) drops every table and builds it again, empty until each file is read again -> the rows, to put back."""
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT * FROM files").fetchall()
        conn.execute("DELETE FROM files")
        conn.commit()
    finally:
        conn.close()
    return rows


def _files_back(db, rows):
    """The indexer has read every file again: their counts back in the store."""
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        conn.executemany(f"INSERT INTO files VALUES ({','.join('?' * len(rows[0]))})", rows)
        conn.commit()
    finally:
        conn.close()


def test_card_chip_a_token_store_rebuilt_by_an_update_keeps_the_last_count_then_counts_the_files_read_again(lib):
    """The start after an update whose token store is built again (Kura-CC, 3.0.18, a tester's restart): the files'
    counts are gone until the indexer reads each one again. The chip keeps the last count it showed (on disk) for an
    episode and a show's row it can't count yet — never its own cards alone, then the whole again at the next start —
    and once the files are read again, the reader's next build asks the same episodes and they are counted: an episode
    the counter couldn't read is asked again, never left on the last session's count (or none) all session."""
    lib.made = {2: set(_pick(lib.words[2], 3, 31))}
    lib.backlog = set(_pick(lib.words[3], 3, 32))
    studied = set(_pick(lib.words[1] | lib.words[2], 12, 33))
    first = lib.chips()
    first.studied(studied)
    first.want(lib.ask([1, 2, 3]), [(1, 2)])
    _settle(first)
    answers = first.answers()
    first.close()
    assert first.idle(10)
    assert answers[1][0] > 0 and answers[(1, 2)][0] > 0
    rows = _files_out(lib.db)                                  # the update: the store built again, nothing read yet
    got = []
    again = lib.chips(got)
    try:
        assert again.seeded() == answers
        again.want(lib.ask([1, 2, 3]), [(1, 2)])
        _settle(again)
        assert again.read_files == 0
        assert again.answers() == answers, "the last count stands while the files aren't read again"
        assert all(g == answers for g in got), "never handed on without them"
        _files_back(lib.db, rows)                              # the indexer has read them again
        studied2 = studied | set(_pick(lib.words[1] - studied - lib.made[2], 2, 34))   # (two more studied meanwhile)
        again.studied(studied2)
        again.want(lib.ask([1, 2, 3]), [(1, 2)])               # the next build's asks: the same episodes
        _settle(again)
        assert again.read_files == 3, "each file read once it is in the store"
        now = again.answers()
        for key in (1, 2, 3, (1, 2)):
            assert now[key] == lib.expected(key, studied2), key
        assert now[1][0] == answers[1][0] + 2
    finally:
        again.close()


def test_card_chip_a_file_counted_this_session_then_unread_is_never_given_last_sessions_count(lib):
    """The last session's count stands only for a file not counted yet this session: one counted, then changed and not
    read yet (a re-sync's new subtitle), has no count until it is read — never the older session's figure back."""
    studied = set(_pick(lib.words[1], 6, 35))
    first = lib.chips()
    first.studied(studied)
    first.want(lib.ask([1]))
    _settle(first)
    first.close()
    assert first.idle(10)
    again = lib.chips()
    try:
        assert again.seeded()[1] == (6, 0)
        again.studied(set(_pick(lib.words[1], 3, 36)))
        again.want(lib.ask([1]))
        _settle(again)
        assert again.answers()[1] == (3, 0)                    # counted this session
        lib.rel[1] = "HighPriority/星の工房/編集中.srt"           # its file changed: not counted yet
        again.want({1: (lib.rel[1], 2, 1)})
        _settle(again)
        assert 1 not in again.answers()
    finally:
        again.close()


def test_card_chip_a_rows_last_count_stands_through_a_card_studied_meanwhile_until_its_files_are_all_read(lib):
    """A show's row with one episode read again and one not yet: the row keeps its last count (never a part of it);
    a card studied meanwhile steps the read episode's count, never the row's into a figure of that card alone; the
    other file read, the row is counted whole."""
    studied = set(_pick(lib.words[1] | lib.words[2], 10, 37))
    first = lib.chips()
    first.studied(studied)
    first.want(lib.ask([1, 2]), [(1, 2)])
    _settle(first)
    answers = first.answers()
    first.close()
    assert first.idle(10)
    import sqlite3
    path2 = ti._norm(os.path.join(lib.data, *lib.rel[2].split("/")))
    conn = sqlite3.connect(lib.db)
    try:
        row2 = conn.execute("SELECT * FROM files WHERE path=?", (path2,)).fetchone()
        conn.execute("DELETE FROM files WHERE path=?", (path2,))
        conn.commit()
    finally:
        conn.close()
    again = lib.chips()
    try:
        again.seeded()
        again.studied(studied)
        again.want(lib.ask([1, 2]), [(1, 2)])
        _settle(again)
        got = again.answers()
        assert got[1] == lib.expected(1, studied) and got[(1, 2)] == answers[(1, 2)] and got[2] == answers[2]
        more = studied | {sorted(lib.words[1] - studied)[0]}
        again.studied(more)
        _settle(again)
        got = again.answers()
        assert got[1] == lib.expected(1, more)
        assert got[(1, 2)] == answers[(1, 2)], "the row's last count stands, never stepped from nothing"
        _files_back(lib.db, [row2])
        again.want(lib.ask([1, 2]), [(1, 2)])
        _settle(again)
        got = again.answers()
        assert got[2] == lib.expected(2, more) and got[(1, 2)] == lib.expected((1, 2), more)
    finally:
        again.close()
