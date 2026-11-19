"""The ✓ chip says honestly what was made (Sonic's lean A, 2026-11-18): with *Only i+1* Connect makes cards from words
on the learner's list and from i+1 words below it, while the row's *N new* counts only the list's — a tester saw *16
new* and 34 cards. The pick now marks each word (`pick.pick`'s `listed`), the ledger hands those marks back read-only
(`ledger.listed_of`), the counter splits an episode's own cards (`card_chip`'s ("level", key) answers) and the hover
says *34 from this episode (16 at your level + 18 below it) · …* (PROVISIONAL words). Real Japanese and Chinese
subtitles; a real ledger in a temp folder.
"""
import json
import os

import pytest

from app import analyzer, cues
from app.connect import ledger as L
from app.connect import pick
from app.services import card_chip, view_rows as vr
from tests.test_view_rows import WORKS, eps, items_of, work

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "tests", "Test Resources")


@pytest.fixture(autouse=True)
def _a_japanese_run():
    analyzer.SANITIZE_JA = True             # as analyzer.main sets it (conftest restores the global)


@pytest.mark.parametrize("language,name", [("ja", "library_episode.ass"), ("zh", "night_market.srt")])
def test_each_picked_word_says_whether_it_was_on_the_list(language, name):
    """*Every new word* / *Only i+1* send words on the list and off it: each says which; with no list given, neither
    (None) — never a guess."""
    read = cues.read(os.path.join(RES, language, name), language)
    tokens = cues.tokens(read, language) if language == "ja" else cues.tokens(read, language, script="s")
    every = pick.pick(read, tokens, language, lambda key: False, mode="unknown")["words"]
    assert len(every) >= 4
    on = {(w["word"], w["reading"]) for w in every[::2]}
    listed = {k: n for n, k in enumerate(sorted(on))}
    chosen = pick.pick(read, tokens, language, lambda key: False, mode="unknown", listed=listed)["words"]
    assert chosen and all(w["listed"] is ((w["word"], w["reading"]) in on) for w in chosen)
    assert {w["listed"] for w in chosen} == {True, False}
    assert all(w["listed"] is None for w in every), "no list: not said"
    only = pick.pick(read, tokens, language, lambda key: False, mode="list", listed=listed)["words"]
    assert only and all(w["listed"] is True for w in only)


def test_the_ledger_hands_back_each_items_marks_read_only_and_a_later_pick_wins(tmp_path):
    """The marks of each item's jobs, the later job's over the earlier; a pick from before the marks gives none; no
    ledger gives none; reading writes nothing (the ledger's file untouched)."""
    db = str(tmp_path / "ledger.sqlite")
    assert L.listed_of("ja", [1], db) == {1: {}}
    with L.Ledger(db) as led:
        for item, words, state in ((1, [{"word": "延長", "listed": True}, {"word": "用紙", "listed": False}], "done"),
                                   (1, [{"word": "用紙", "listed": True}], "done"),
                                   (2, [{"word": "小説"}], "done"),            # picked before the marks
                                   (3, [{"word": "夜市", "listed": False}], "done")):
            led.conn.execute("INSERT INTO jobs (language, item_id, state, created_at, updated_at, picked) "
                             "VALUES (?, ?, ?, 't', 't', ?)", ("ja" if item < 3 else "zh", item, state,
                                                               json.dumps({"words": words}, ensure_ascii=False)))
    before = os.stat(db).st_mtime_ns
    got = L.listed_of("ja", [1, 2, 3], db)
    assert got == {1: {"延長": True, "用紙": True}, 2: {}, 3: {}}
    assert L.listed_of("zh", [3], db) == {3: {"夜市": False}}
    assert os.stat(db).st_mtime_ns == before


class _Lib:
    """The counter over a token store that holds no file (the split needs none), its made words and marks by hand."""

    def __init__(self, tmp_path):
        self.made, self.flags, self.tmp = {}, {}, str(tmp_path)
        self.cache = str(tmp_path / "card_chip_ja.json")

    def chips(self):
        return card_chip.Chips("ja", open_tokens=lambda: None, data_dir=self.tmp,
                               read_made=lambda _l, ids: {i: set(self.made.get(i, ())) for i in ids},
                               read_listed=lambda _l, ids: {i: dict(self.flags.get(i, {})) for i in ids},
                               read_backlog=lambda _l: set(), backlog_stamp=lambda _l: 1, cache_file=self.cache)


def test_the_counter_splits_an_episodes_own_cards_and_a_rows_is_the_sum(tmp_path):
    """Ep 1: three list words and two below — (3, 2); ep 2 all on the list — (2, 0); the row (5, 2). A made word the
    pick didn't mark (an older job) leaves its episode — and its row — unsplit. Handed on with the answers, and kept
    on disk for the next session."""
    lib = _Lib(tmp_path)
    lib.made = {1: {"延長", "用紙", "図書", "小説", "雨宿り"}, 2: {"夜", "朝"}, 3: {"窓", "扉"}}
    lib.flags = {1: {"延長": True, "用紙": True, "図書": True, "小説": False, "雨宿り": False},
                 2: {"夜": True, "朝": True}, 3: {"窓": True}}
    chips = lib.chips()
    try:
        chips.want({1: ("a.srt", 1, 5), 2: ("b.srt", 1, 2), 3: ("c.srt", 1, 2)}, [(1, 2), (2, 3)])
        assert chips.idle(10)
        got = chips.answers()
        assert got[("level", 1)] == (3, 2) and got[("level", 2)] == (2, 0)
        assert got[("level", (1, 2))] == (5, 2)
        assert ("level", 3) not in got and ("level", (2, 3)) not in got, "an unmarked word: not split"
    finally:
        chips.close()
        assert chips.idle(10)
    chips._save(now=True)
    again = lib.chips()
    try:
        seeded = again.seeded()
        assert seeded[("level", 1)] == (3, 2) and seeded[("level", (1, 2))] == (5, 2)
    finally:
        again.close()


@pytest.fixture
def _works():
    WORKS.clear()
    work(1, "星降る街の小さな工房")
    work(2, "云端邮差")
    yield
    WORKS.clear()


@pytest.mark.parametrize("wid,language", [(1, "ja"), (2, "zh")])
def test_the_hover_says_at_your_level_and_below_it_only_when_some_are_below(_works, wid, language):
    """34 cards made from Ep 11, 16 on the list and 18 below it: *34 from this episode (16 at your level + 18 below
    it) · 22 from other episodes and shows*; the show's row says its own. All on the list, or a split that isn't its
    count: the plain hover."""
    items = items_of([("now", wid, 1, eps(WORKS[wid]["title"], 11, 13), {})])
    cards = {1: 34, 2: 12, 3: 5}
    answers = {1: 22, 2: 3, 3: 1, (1, 2, 3): 25, ("level", 1): (16, 18), ("level", 2): (12, 0),
               ("level", 3): (2, 2), ("level", (1, 2, 3)): (30, 21)}
    row = vr.build(items, WORKS, {}, cards=cards, elsewhere=answers, language=language).rows[0]
    e11, e12, e13 = row.episodes
    assert e11.status.label == "56"
    assert e11.status.tip == "34 from this episode (16 at your level + 18 below it) · 22 from other episodes and shows"
    assert e12.status.tip == "12 from this episode · 3 from other episodes and shows", "none below: as before"
    assert e13.status.tip == "5 from this episode · 1 from other episodes and shows", "2 + 2 isn't its 5: not split"
    assert row.status.tip == ("51 from its 3 episodes (30 at your level + 21 below it) · 25 from other episodes and "
                              "shows")
    cache = vr.RowCache()
    one = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, elsewhere=answers, cache=cache, language=language)
    two = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, cache=cache, language=language,
                   elsewhere={**answers, ("level", 1): (17, 17)})
    assert two.rows[0] is not one.rows[0] and "17 at your level + 17 below it" in two.rows[0].episodes[0].status.tip


def test_a_ledger_from_a_newer_surasura_or_one_without_picks_gives_no_marks(tmp_path):
    """Never read: a newer Surasura's ledger (as the ledger's own open refuses it); an old one from before the job's
    pick was kept, or a file that was never set up, gives no marks rather than an error each round (review L-C1/C3)."""
    import sqlite3
    db = str(tmp_path / "ledger.sqlite")
    with L.Ledger(db) as led:
        led.conn.execute("INSERT INTO jobs (language, item_id, state, created_at, updated_at, picked) VALUES "
                         "('ja', 1, 'done', 't', 't', ?)", (json.dumps({"words": [{"word": "延長", "listed": True}]}),))
        assert L.listed_of("ja", [1], db) == {1: {"延長": True}}
        led.conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(L.SCHEMA + 1),))
    assert L.listed_of("ja", [1], db) == {1: {}}
    old = str(tmp_path / "old.sqlite")
    with sqlite3.connect(old) as c:
        c.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        c.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, language TEXT, item_id INTEGER, state TEXT)")
    assert L.listed_of("ja", [1], old) == {1: {}}
    bare = str(tmp_path / "bare.sqlite")
    sqlite3.connect(bare).close()
    assert L.listed_of("ja", [1], bare) == {1: {}}


def test_the_ledger_busy_as_an_episodes_cards_move_drops_its_split_and_reads_it_again_by_itself(tmp_path, monkeypatch):
    """Ep 1's cards moved (one made word swapped for another, the same count) while the ledger is busy: its old split
    is never shown for the new words — dropped — and the round is tried again a moment later, the new split read
    (review L-S1)."""
    import time
    monkeypatch.setattr(card_chip, "RETRY_S", 0.05)
    lib = _Lib(tmp_path)
    lib.made = {1: {"延長", "小説"}}
    lib.flags = {1: {"延長": True, "小説": False}}
    busy = []

    def read_listed(_l, ids):
        if busy:
            busy.pop()
            return None
        return {i: dict(lib.flags.get(i, {})) for i in ids}
    chips = lib.chips()
    chips._read_listed = read_listed
    try:
        chips.want({1: ("a.srt", 1, 2)})
        assert chips.idle(10) and chips.answers()[("level", 1)] == (1, 1)
        lib.made = {1: {"延長", "雨宿り"}}
        lib.flags = {1: {"延長": True, "雨宿り": True}}
        busy.append(1)
        chips.want({1: ("a.srt", 1, (2, "swapped"))})
        assert chips.idle(10) and ("level", 1) not in chips.answers()
        deadline = time.monotonic() + 5
        while chips.answers().get(("level", 1)) is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert chips.idle(10) and chips.answers()[("level", 1)] == (2, 0)
    finally:
        chips.close()
