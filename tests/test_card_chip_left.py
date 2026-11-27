"""The ✓ chip counts the cards still left to study (CARD-LEFT, 3.0.21; Sonic § 113, 2026-11-27): of the cards that
hold an episode's (or a show's) words, how many Surasura doesn't count known yet — and the number falls as the learner
learns them, to the ✓ alone. `app/services/card_chip.py` (the (left, done) answers), `app/services/view_rows.py`
(`status_of`'s label and hover), the two triggers (`LibraryReader._ask_chips`, the shell's `_known_moved`).

Why these matter: the chip counted every word of the show that had a card anywhere, so for a learner with thousands
of cards it was mostly the show's known words — 1,831 on one show for a tester with ~6,300 notes — and it only ever
grew. A card is left until its word counts as known by Surasura's own known rule: the token store's normalization of
KnownWord.json (Generate's and the indexer's, the set the list's % known reads), never a second reading and never
Anki. On real Japanese and Chinese files in a real token store, the known words written by the analyzer's own
`read_known_words`; every answer checked against a count made the slow way.
"""
import json
import os
import random
import types

import pytest

from app import analyzer
from app import token_index as ti
from app.services import card_chip, view_rows as vr
from tests.test_card_chip import Lib, _settle, _tokenized

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources")


@pytest.fixture(scope="module")
def _built(tmp_path_factory):
    made = {}

    def get(language):
        if language not in made:
            made[language] = _tokenized(str(tmp_path_factory.mktemp(f"chip-left-{language}")), language)
        return made[language]
    return get


@pytest.fixture(params=["ja", "zh"])
def lib(request, tmp_path, _built):
    return Lib(str(tmp_path), request.param, _built(request.param))


def _known_file(lib, words):
    """KnownWord.json as the known-words sync writes it: each word KNOWN (its studied card counted known)."""
    path = os.path.join(os.path.dirname(lib.db), f"KnownWord_{lib.language}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"words": [{"dictForm": w, "knownStatus": "KNOWN", "hasCard": 1, "language": lib.language}
                             for w in sorted(words)]}, f, ensure_ascii=False)
    return path


def _normalize(lib, path, tokenizer):
    """What Generate / the indexer do after a sync: the known words normalized into the token store (written)."""
    store = ti.open_store(lib.language, path=lib.db)
    try:
        analyzer.read_known_words(store, path, ti.known_signature(path), tokenizer)
    finally:
        store.close()
    reader = ti.open_reader(lib.language, lib.db)
    try:
        return set(json.loads(reader.get_meta("known_lemmas") or "[]"))
    finally:
        reader.close()


def _tokenizer(language):
    return analyzer.ChineseTokenizer() if language == "zh" else analyzer.JapaneseTokenizer()


def _label(lib, answers, item, cards):
    """The ✓ the window shows for a one-file row of `item` with `cards` cards of its own and these answers."""
    st, _mark = vr.status_of([types.SimpleNamespace(cards=cards, mined=True, mining=False, missing=False,
                                                    removed=False, in_top=False, deleted=False, waiting=False)],
                             "video", None, answers.get(item), answers.get(("level", item)))
    return st


def test_a_shows_cards_turning_known_one_by_one_bring_its_number_down_to_the_check_alone(lib):
    """Ep 1 and its show: cards made from it (Connect), new cards from the backlog and studied ones — none known yet.
    Each card's word turns known in KnownWord.json (a sync), Surasura normalizes it (Generate / the indexer), and the
    window says so (`known_moved`): ep 1's number and its show's fall by the words that turned, never a recount — to
    the ✓ alone. The record stays: its words on cards in all stay the same throughout."""
    rng = random.Random(113)
    ep1 = sorted(lib.words[1])
    lib.made = {1: set(rng.sample(ep1, 3))}
    lib.backlog = set(rng.sample(sorted(set(ep1) - lib.made[1]), 4))
    studied = set(rng.sample(sorted(set(ep1) - lib.made[1] - lib.backlog), 3)) | set(rng.sample(sorted(lib.words[2]), 3))
    path = _known_file(lib, ())
    tok = _tokenizer(lib.language)
    known = _normalize(lib, path, tok)
    got = []
    chips = lib.chips(got)
    try:
        chips.studied(studied)
        chips.want(lib.ask([1, 2]), [(1, 2)])
        _settle(chips)
        first = chips.answers()
        assert first[1] == lib.expected(1, studied, known) and first[1][0] >= 10 and first[1][1] == 0
        assert first[(1, 2)] == lib.expected((1, 2), studied, known)
        total = sum(first[1])
        reads = chips.read_files
        carded = sorted(lib.made[1] | lib.backlog | (studied & set(ep1)))
        learned, before = set(), first[1][0]
        for word in carded:
            learned.add(word)
            known = _normalize(lib, _known_file(lib, learned), tok)
            chips.known_moved()
            _settle(chips)
            now = chips.answers()
            for key in (1, 2, (1, 2)):
                assert now[key] == lib.expected(key, studied, known), (word, key)
            assert now[1][0] <= before and sum(now[1]) == total, word     # (a word's pieces may turn first)
            before = now[1][0]
        assert now[1] == (0, total), "every card of ep 1 learned: none left"
        assert chips.read_files == reads, "the known words moved: stepped through, no file read again"
        st = _label(lib, now, 1, 3)
        assert st.kind == "in_anki" and st.label == "", "none left: the ✓ alone"
        assert st.tip.startswith("No cards left to study · ")
        assert got[-1] == now
    finally:
        chips.close()


def test_a_card_learned_and_a_new_card_made_in_one_round_move_the_number_by_both(lib):
    """A sync that turns one word known while Connect makes a card of another (one round): the count steps by both —
    the new card left, the learned one done — and a word known before it had a card adds nothing until it has one."""
    rng = random.Random(7)
    ep1 = sorted(lib.words[1])
    a, b, c = rng.sample(ep1, 3)
    lib.backlog = {a}
    path = _known_file(lib, {c})                     # c known (read in a book), no card yet
    tok = _tokenizer(lib.language)
    known = _normalize(lib, path, tok)
    chips = lib.chips()
    try:
        chips.want(lib.ask([1]))
        _settle(chips)
        assert chips.answers()[1] == lib.expected(1, (), known) == (1, 0)
        known = _normalize(lib, _known_file(lib, {a, c}), tok)
        lib.backlog, lib.stamp[0] = {a, b}, 1        # ... and the same sync's new card of b
        chips.known_moved()
        _settle(chips)
        assert chips.answers()[1] == lib.expected(1, (), known) == (1, 1)
        lib.backlog, lib.stamp[0] = {a, b, c}, 2      # c's card made: done at once (already known)
        chips.known_moved()
        _settle(chips)
        assert chips.answers()[1] == lib.expected(1, (), known) == (1, 2)
    finally:
        chips.close()


def test_a_learner_with_thousands_of_cards_most_known_sees_a_small_number_and_the_whole_record(lib):
    """A tester's shape (~6,300 notes, most of them known): thousands of studied cards, KnownWord.json's thousands of
    known words (ja: the real 11,582-entry list), and an episode whose few unlearned cards are the only ones left. The
    number is those few; the hover keeps the record (all its words on cards, the known ones, its own cards)."""
    with open(os.path.join(RES, "ja", "KnownWord.json"), encoding="utf-8-sig") as f:
        listed = [e["dictForm"] for e in json.load(f)["words"]
                  if e.get("knownStatus") == "KNOWN" or e.get("hasCard") == 1]
    rng = random.Random(6300)
    ep1 = sorted(lib.words[1])
    fresh = set(rng.sample(ep1, 5))                   # its unlearned cards: 3 made from it, 2 new from the backlog
    lib.made = {1: set(sorted(fresh)[:3])}
    lib.backlog = set(sorted(fresh)[3:])
    every = set().union(*lib.words.values())
    studied = (set(listed[:6300]) if lib.language == "ja" else set()) | (every - fresh)
    known_words = (set(listed) if lib.language == "ja" else set()) | (every - fresh)
    store = ti.open_store(lib.language, path=lib.db)
    try:                                              # the analyzer's own writer, as a Generate leaves it
        store.set_cached_known(ti.known_signature(os.path.join(os.path.dirname(lib.db), "KnownWord.json")),
                               set(), known_words - fresh, suffix="")
    finally:
        store.close()
    known = known_words - fresh
    chips = lib.chips()
    try:
        chips.studied(studied)
        chips.want(lib.ask([1, 2, 3, 4], cards=None), [(1, 2)])
        _settle(chips)
        answers = chips.answers()
        for key in (1, 2, 3, 4, (1, 2)):
            assert answers[key] == lib.expected(key, studied, known), key
        left, done = answers[1]
        assert left == 5 and done == len(set(ep1) - fresh), "only its unlearned cards are left"
        assert answers[2][0] == len(lib.words[2] & fresh), "the other episode: only the shared unlearned words"
        st = _label(lib, answers, 1, 3)
        assert st.label == "5"
        assert st.tip == vr.STRINGS["tip_in_anki_chip"].format(left_line="5 cards left to study", all=5 + done,
                                                                done=done, own=3)
    finally:
        chips.close()


def test_a_cache_from_before_hands_on_no_old_totals_but_keeps_its_studied_words(lib):
    """The first start after the update: the disk's last answers were the old total (every word with a card) — never
    shown as cards left (the first frame says its own cards until counted); the studied words it kept still count
    (Anki closed at the open keeps the cards), and the next save writes the new answers."""
    studied = set(random.Random(3).sample(sorted(lib.words[1]), 6))
    with open(lib.cache, "w", encoding="utf-8") as f:
        json.dump({"v": card_chip.CACHE_VERSION, "studied": sorted(studied), "studied_said": [], "reads": [],
                   "items": {"1": 1704}, "rows": {"1,2": 1831}, "levels": {}}, f, ensure_ascii=False)
    chips = lib.chips()
    try:
        assert chips.seeded() == {}, "an old total is another count: never handed on"
        chips.want(lib.ask([1]))
        _settle(chips)
        assert chips.answers()[1] == lib.expected(1, studied) == (6, 0), "the kept studied words counted"
        chips._save(now=True)
        with open(lib.cache, encoding="utf-8") as f:
            assert json.load(f)["items"]["1"] == [6, 0]
    finally:
        chips.close()
    again = lib.chips()
    try:
        assert again.seeded()[1] == (6, 0)
    finally:
        again.close()


def test_the_known_words_unreadable_for_a_round_are_read_again(lib):
    """The token store busy as the round reads its known words: the round is tried again, never a count that stays
    without them."""
    path = _known_file(lib, set(sorted(lib.words[1])[:2]))
    known = _normalize(lib, path, _tokenizer(lib.language))
    lib.backlog = set(sorted(lib.words[1])[:4])
    calls = []

    def read_known(store, last):
        calls.append(last)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return card_chip._store_known(store, last)
    chips = lib.chips()
    chips._read_known = read_known
    old_retry = card_chip.RETRY_S
    card_chip.RETRY_S = 0.05
    try:
        chips.want(lib.ask([1]))
        _settle(chips)
        import time
        deadline = time.monotonic() + 5
        while chips.answers().get(1) != lib.expected(1, (), known) and time.monotonic() < deadline:
            time.sleep(0.02)
        _settle(chips)
        assert chips.answers()[1] == lib.expected(1, (), known) and len(calls) >= 2
    finally:
        card_chip.RETRY_S = old_retry
        chips.close()


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_each_generate_and_each_indexer_run_ask_the_counter_to_read_the_known_words_again(language):
    """The two moments the known words move in the window: a Generate's end and an indexer run (each normalizes them
    after a sync) — the window asks its own language's counter only."""
    import threading
    from app.qt.shell import Services
    told = []
    ended = types.SimpleNamespace(closing=threading.Event(), gentle=None, writer=None, language=language,
                                  _known_moved=told.append)
    Services._generate_ended(ended, None, "current")
    assert told == [language]
    got = []
    chips = types.SimpleNamespace(language="zh", known_moved=lambda: got.append("zh"))
    services = types.SimpleNamespace(library=types.SimpleNamespace(language="zh", chips=chips))
    Services._known_moved(services, "ja")
    assert got == []
    Services._known_moved(services, "zh")
    assert got == ["zh"]
    Services._known_moved(types.SimpleNamespace(library=None), "zh")
    assert got == ["zh"]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_first_screens_cache_from_before_the_update_reads_its_own_cards_and_never_fails(language):
    """The window's first-screen cache written by the version before holds the old answer (a bare number) on its
    episodes and rows; a drop that reads the top again (`topped`) derives their status from it — its own cards, as
    when not counted yet, never a failure and never the old total called *left*."""
    import json as _json
    from tests.test_view_rows_card_chip import CARDS, _three_shows, WORKS
    WORKS.clear()
    try:
        items = _three_shows(language)
        view = vr.build(items, WORKS, {"mine_line": 20}, cards=CARDS, language=language)
        back = vr.from_cache(_json.loads(_json.dumps(vr.to_cache(view))))
        back_rows = [r._replace(episodes=tuple(e._replace(elsewhere=22) for e in r.episodes), elsewhere=40)
                     for r in back.rows]
        rows, changed = vr.topped(back_rows, 2)
        assert changed
        assert rows[0].episodes[0].status.label == "9", "its own cards, as when not counted yet"
        st, _ = vr.status_of([types.SimpleNamespace(cards=9, mined=True, mining=False, missing=False, removed=False,
                                                    in_top=False, deleted=False, waiting=False)], "video", None, 22)
        assert st.label == "9" and st.tip == vr.STRINGS["tip_in_anki"].format(n=9)
    finally:
        WORKS.clear()


def test_a_store_built_again_counts_nothing_as_left_until_its_known_words_are_normalized(lib):
    """An update builds the token store again; the indexer writes the files' counts first and the known words after.
    In between, an episode it read is never shown with every carded word left: its last number stands (on disk)
    until the known words are in, then the indexer's end (`known_moved`) counts it."""
    studied = set(sorted(lib.words[1])[:6])
    path = _known_file(lib, set(sorted(studied)[:4]))
    known = _normalize(lib, path, _tokenizer(lib.language))
    first = lib.chips()
    first.studied(studied)
    first.want(lib.ask([1]))
    _settle(first)
    last = first.answers()[1]
    first.close()
    assert first.idle(10) and last == lib.expected(1, studied, known) == (2, 4)
    import sqlite3
    conn = sqlite3.connect(lib.db)                       # the rebuilt store: files counted, no known words yet
    try:
        conn.execute("DELETE FROM meta WHERE key IN ('known_sig', 'known_lemmas', 'known_tuples')")
        conn.commit()
    finally:
        conn.close()
    again = lib.chips()
    try:
        assert again.seeded()[1] == last
        again.studied(studied)
        again.want(lib.ask([1]))
        _settle(again)
        assert again.answers()[1] == last, "its last number stands, never (6, 0)"
        known = _normalize(lib, path, _tokenizer(lib.language))      # the indexer's known step, then its end
        again.known_moved()
        _settle(again)
        assert again.answers()[1] == lib.expected(1, studied, known) == (2, 4)
    finally:
        again.close()
