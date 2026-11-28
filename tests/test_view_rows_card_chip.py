"""The ✓ chip's rows (Michi-CK2; CARD-LEFT, Sonic § 113): an episode in Anki says how many of the cards holding its
words are still left to study — its own and those carded elsewhere (`view_rows.build(elsewhere=)`, the counter's
(left, done) answers), none left the ✓ alone — and its hover keeps the record: *20 cards left to study · 31 of its words
have cards, 11 known · 9 made from this episode* (PROVISIONAL words). The reader asks the counter of its mined episodes and builds
its answers in; the word card hands Anki's studied cards on (never a second read of Anki).

Why these matter: the chip must never redraw what didn't move (a Connect batch moves a few counts: only those rows are
rebuilt — the rest are the same objects, so the window repaints nothing for them), never jump (the first build after
the first screen keeps the last count; Anki closed keeps it), and a count not known yet reads as before. Japanese and
Chinese titles; hand-made feed rows and the stand-in store's seed.
"""
import time
import types

import pytest

from app.services import library_reader, view_rows as vr
from tests.test_view_rows import WORKS, eps, items_of, work

TITLES = {"ja": ["星降る街の小さな工房", "雲の上の郵便屋さん", "海辺の図書室"],
          "zh": ["星落小镇的工坊", "云端邮差", "海边的图书室"]}


@pytest.fixture(autouse=True)
def _works():
    WORKS.clear()
    yield
    WORKS.clear()


def _three_shows(language, finished=False):
    for wid, title in enumerate(TITLES[language], 1):
        work(wid, title)
    spec = [("now", 1, 1, eps(TITLES[language][0], 1, 3), {}),                 # ids 1–3
            ("now", 2, 2, eps(TITLES[language][1], 1, 2), {}),                 # ids 4–5
            ("now", 3, 3, eps(TITLES[language][2], 1, 1), {})]                 # id 6
    if finished:                                                                # ids 7–8, Finished
        work(4, "白銀の書庫番" if language == "ja" else "白银书库管理员", media="lightnovel")
        spec.append(("graduated", 4, 4, eps(WORKS[4]["title"], 1, 2),
                     {k: {"graduated_at": "2026-11-01T10:00:00Z"} for k in range(2)}))
    return items_of(spec)


CARDS = {1: 9, 2: 4, 3: 2, 4: 5, 5: 1, 6: 3}


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_check_counts_the_cards_left_to_study_and_its_hover_keeps_the_record(language):
    """Ep 1: 9 cards of its own, 31 of its words on cards, 11 of them known — ✓ 20, *20 cards left to study · 31 of its
    words have cards, 11 known · 9 made from this episode*. None left: the ✓ alone. The show's row counts its words
    once (its own answer, never the sum of its episodes')."""
    elsewhere = {1: (20, 11), 2: (5, 4), 3: (0, 2), (1, 2, 3): (25, 15), 4: (1, 5), 5: (2, 1), (4, 5): (3, 6), 6: (0, 10)}
    view = vr.build(_three_shows(language), WORKS, {}, cards=CARDS, elsewhere=elsewhere, language=language)
    row = view.rows[0]
    ep1 = row.episodes[0]
    assert ep1.status.kind == "in_anki" and ep1.status.label == "20"
    assert ep1.status.tip == "20 cards left to study · 31 of its words have cards, 11 known · 9 made from this episode"
    assert row.episodes[2].status.kind == "in_anki" and row.episodes[2].status.label == "", "none left: the ✓ alone"
    assert row.episodes[2].status.tip == ("No cards left to study · 2 of its words have cards, 2 known · 2 made from "
                                          "this episode")
    assert row.episodes[1].status.label == "5"
    assert row.status.label == "25", "its words once: its own answer, not 20 + 5 + 0"
    assert row.status.tip == ("25 cards left to study · 40 of its words have cards, 15 known · 15 made from its 3 "
                              "episodes")
    assert view.rows[1].episodes[0].status.tip.startswith("1 card left to study · ")
    assert view.rows[2].status.label == "", "a one-file row: its file's answer"
    assert vr.spoken(ep1.status) == "20 in Anki"
    assert vr.spoken(view.rows[2].status) == "In Anki, no cards left to study"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_not_counted_yet_reads_as_before_and_an_episode_not_in_anki_has_no_count(language):
    """No answers (no counter, or not answered yet): its own cards, today's hover. An episode not in Anki never takes
    an answer (the chip shows only on rows in Anki), and its row's status is the one it had (not *N in Anki*)."""
    items = _three_shows(language)
    before = vr.build(items, WORKS, {}, cards=CARDS, language=language).rows[0]
    assert before.episodes[0].status.label == "9" and before.episodes[0].status.tip == vr.STRINGS["tip_in_anki"].format(
        n=9)
    assert before.status.tip == vr.STRINGS["tip_in_anki_k"].format(k=3, n=15)
    some = vr.build(items, WORKS, {}, cards={1: 9}, elsewhere={1: (20, 11), 2: (6, 0), (1, 2, 3): (40, 3)},
                    language=language).rows[0]
    assert some.episodes[0].status.label == "20"
    assert some.episodes[1].elsewhere is None and some.episodes[1].status.kind != "in_anki"
    plain = vr.build(items, WORKS, {}, cards={1: 9}, language=language).rows[0]
    assert some.status == plain.status, "a row not all in Anki reads as before"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_batch_that_moves_one_count_rebuilds_only_that_row(language):
    """A Connect batch: one episode's answer moved — its row is built again, every other row is the same object (the
    window repaints nothing for it), Finished's too."""
    items = _three_shows(language, finished=True)
    fin_ids = [i for i, r in items.items() if r["tier"] == "graduated"]
    assert fin_ids == [7, 8]
    cards = {**CARDS, **{i: 2 for i in fin_ids}}
    cache = vr.RowCache()
    first = {1: (20, 11), 2: (5, 4), 3: (0, 2), (1, 2, 3): (25, 15), 4: (1, 5), 5: (2, 1), (4, 5): (3, 6),
             6: (0, 10), fin_ids[0]: (4, 2), fin_ids[1]: (1, 2), tuple(fin_ids): (5, 3)}
    one = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, elsewhere=first, cache=cache, language=language)
    moved = {**first, 4: (2, 5), (4, 5): (4, 6)}               # a batch carded one more of show 2's words
    two = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, elsewhere=moved, cache=cache, language=language)
    assert two.rows[0] is one.rows[0] and two.rows[2] is one.rows[2]
    assert two.rows[1] is not one.rows[1] and two.rows[1].status.label == "4"
    assert two.finished[0].rows[0] is one.finished[0].rows[0], "Finished's rows kept: their answers didn't move"
    again = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, elsewhere=dict(moved), cache=cache,
                     language=language)
    assert [r is s for r, s in zip(again.rows, two.rows)] == [True, True, True], "equal answers: nothing rebuilt"
    studied = {**moved, 4: (1, 6), (4, 5): (3, 7)}             # CARD-LEFT: a card learned — left falls, its row alone
    three = vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, elsewhere=studied, cache=cache, language=language)
    assert three.rows[0] is again.rows[0] and three.rows[2] is again.rows[2]
    assert three.rows[1] is not two.rows[1] and three.rows[1].status.label == "3"
    assert three.finished[0].rows[0] is again.finished[0].rows[0]


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_finisheds_section_is_kept_while_its_own_counts_read_the_same_and_built_again_when_one_moves(language):
    """Built as the reader builds (nothing in the feed changed: `changed` empty), Finished's section is kept whole
    while its own answers read the same — a Current answer moving doesn't build it — and built again when one of its
    own moves, its row then showing the new count (mutant M17)."""
    items = _three_shows(language, finished=True)
    cards = {**CARDS, 7: 2, 8: 2}
    cache = vr.RowCache()
    tiers = vr._by_tier(items)                                  # the reader's tiers: the same lists while unmoved
    base = {1: (20, 11), 2: (5, 4), 3: (0, 2), (1, 2, 3): (25, 15), 4: (1, 5), 5: (2, 1), (4, 5): (3, 6), 6: (0, 10),
            7: (4, 2), 8: (1, 2), (7, 8): (5, 3)}

    def build(elsewhere):
        return vr.build(items, WORKS, {}, numbers=(1, {}), cards=cards, elsewhere=elsewhere, cache=cache,
                        tiers=tiers, changed=set(), changed_works=set(), language=language)
    build(base)                                                 # the first build keys nothing yet
    one = build(dict(base))
    two = build({**base, 6: (1, 10)})                           # a Current answer moved
    assert two.finished is one.finished, "Finished kept whole"
    three = build({**base, 6: (1, 10), 7: (9, 2), (7, 8): (10, 3)})     # one of Finished's own moved
    assert three.finished is not two.finished
    assert three.finished[0].rows[0].status.label == "10"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_count_survives_the_first_screens_cache_and_a_drop_reading_the_top_again(language):
    """The first frame shows last session's count; a drop that reads the top again (`topped`) keeps it on the rows it
    reads again — never back to its own cards."""
    import json
    items = _three_shows(language)
    elsewhere = {1: (20, 11), 2: (5, 4), 3: (0, 2), (1, 2, 3): (25, 15), 4: (1, 5), 5: (2, 1), (4, 5): (3, 6), 6: (0, 10)}
    view = vr.build(items, WORKS, {"mine_line": 20}, cards=CARDS, elsewhere=elsewhere, language=language)
    back = vr.from_cache(json.loads(json.dumps(vr.to_cache(view))))
    assert back.rows[0].episodes[0].status.label == "20" and back.rows[0].status.label == "25"
    rows, changed = vr.topped(view.rows, 2)
    assert changed, "the line moved: rows read again"
    assert rows[0].episodes[0].status.label == "20" and rows[0].status.label == "25"
    assert rows[0].status.tip == ("25 cards left to study · 40 of its words have cards, 15 known · 15 made from its 3 "
                                  "episodes")


# --- the reader: asks the counter, builds its answers in ---------------------------------------------------- #
class _Counter:
    """The counter as the reader sees it: asks recorded, answers handed on through `on_change`."""

    def __init__(self, language, seeded=None):
        self.language = language
        self.on_change = None
        self.asks, self.forgot, self.closed, self.known = [], [], False, 0
        self._seeded = dict(seeded or {})

    def seeded(self):
        return dict(self._seeded)

    def want(self, asks, rows=()):
        self.asks.append((dict(asks), set(rows)))

    def forget(self, ids, rows=()):
        self.forgot.append((set(ids), set(rows)))

    def known_moved(self):
        self.known += 1

    def close(self):
        self.closed = True


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def _reader(language, counter, cards):
    from tests.fixtures import window_seed
    seed = window_seed.build(language=language)
    views = []
    reader = library_reader.LibraryReader(seed.opener, language=language, numbers=seed.numbers, mining=seed.mining,
                                          poll=0.02, chips=counter)
    reader.subscribe(views.append)
    with seed.library._lock:
        for item, n in cards.items():
            seed.library._cards[item] = list(range(1, n + 1))
        seed.library._data_version += 1
    return seed, reader, views


def _episode(view, item):
    """An episode of Current's or Finished's rows (None: in neither)."""
    rows = list(view.rows) + [r for m in (view.finished or ()) for r in m.rows]
    return next((e for r in rows for e in r.episodes if e.id == item), None)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_reader_asks_its_mined_episodes_and_rebuilds_only_the_rows_whose_answer_moved(language):
    """After a build: each mined episode asked with its file, date and cards, one not mined as None; the counter's
    answer lands in the next view on that episode alone — every other row the same object."""
    counter = _Counter(language)
    seed, reader, views = _reader(language, counter, {})
    reader.start()
    try:
        assert _wait(lambda: views and views[-1].state == "full")
        first = views[-1]
        row = next(r for r in first.rows if len(r.episodes) == 1)
        item = row.episodes[0].id
        with seed.library._lock:
            seed.library._cards[item] = [11, 12, 13]
            seed.library._data_version += 1
        assert _wait(lambda: _episode(views[-1], item).cards == 3)
        assert _wait(lambda: any(a.get(item) == (row.episodes[0].rel_path, row.episodes[0].disk, 3)
                                 for a, _r in counter.asks))
        for a, _r in counter.asks:                       # every other episode asked: None unless in Anki
            for i, v in a.items():
                e = _episode(views[-1], i)
                if i != item and e is not None:
                    assert (v is None) == (not e.cards), i
        before = views[-1]
        counter.on_change({item: (20, 3)})
        assert _wait(lambda: _episode(views[-1], item).status.label == "20")
        after = views[-1]
        assert _episode(after, item).status.tip == ("20 cards left to study · 23 of its words have cards, 3 known · 3 "
                                                    "made from this episode")
        kept = [a is b for a, b in zip(before.rows, after.rows) if a.key != row.key]
        assert kept and all(kept), "only the row whose answer moved is built again"
    finally:
        reader.stop()
    assert counter.closed, "the reader's stop closes the counter (its answers on disk)"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_readers_first_build_reads_the_last_answers_on_disk(language):
    """Next session, before the counter answers (Anki closed, or still counting): the first build already shows the
    last count — never its own cards alone, then the whole."""
    from tests.fixtures import window_seed
    probe = window_seed.build(language=language)
    probe_reader = library_reader.LibraryReader(probe.opener, language=language, numbers=probe.numbers,
                                                mining=probe.mining, poll=0.02)
    got = []
    probe_reader.subscribe(got.append)
    probe_reader.start()
    try:
        assert _wait(lambda: got and got[-1].state == "full")
        item = next(r for r in got[-1].rows if len(r.episodes) == 1).episodes[0].id
    finally:
        probe_reader.stop()
    counter = _Counter(language, seeded={item: (30, 4)})
    _seed, reader, views = _reader(language, counter, {item: 2})
    reader.start()
    try:
        assert _wait(lambda: views and views[-1].state == "full")
        assert _episode(views[-1], item).status.label == "30"
        assert len(counter.asks) >= 1
    finally:
        reader.stop()


# --- the word card hands Anki's studied cards on ------------------------------------------------------------- #
def test_the_word_cards_read_of_anki_hands_its_studied_words_on_and_closed_hands_nothing():
    """The one read of Anki's studied cards (the word card's, on its worker): its words to the counter; Anki closed
    or no decks: nothing handed (the counter keeps its last)."""
    from app.anki_connect import AnkiError
    from app.services import title_words as TW
    from app.anki_words import Standing
    told, whole = [], []
    kana = Standing(1, sentence="<b>ねこ</b>が寝ている。")      # Kyou-KN: a kana card's sentence reaches the counter
    answers = [{"猫": object(), "走る": object(), "ねこ": kana}, AnkiError("Anki is not running")]

    def read(_language, _settings):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    tw = TW.TitleWords(None, "ja", read_standing=read)
    tw.on_standing = lambda words: (told.append(sorted(words)), whole.append(words))
    try:
        tw.refresh_anki(force=True)
        assert tw.idle(5)
        assert told == [["ねこ", "猫", "走る"]]
        assert whole[0]["ねこ"] is kana, "the Standings themselves, each kana card's sentence on it (the ✓ chip's)"
        tw.refresh_anki(force=True)
        assert tw.idle(5)
        assert tw.standing() == TW.ANKI_CLOSED and told == [["ねこ", "猫", "走る"]]
    finally:
        tw.close()


def test_the_window_hands_studied_words_only_to_its_own_languages_counter():
    """A language switch under way: words read for the other language's word card never reach this counter."""
    from app.qt.shell import ShellWindow
    got = []
    chips = types.SimpleNamespace(language="zh", studied=got.append)
    win = types.SimpleNamespace(services=types.SimpleNamespace(library=types.SimpleNamespace(language="zh",
                                                                                                chips=chips)),
                                language="zh")
    ShellWindow._studied_words(win, ["家"], "ja")
    assert got == []
    ShellWindow._studied_words(win, ["家"], "zh")
    assert got == [["家"]]
    ShellWindow._studied_words(types.SimpleNamespace(services=types.SimpleNamespace(library=None), language="zh"),
                               ["家"], "zh")
    assert got == [["家"]]
