"""The card and Swap ask the score (the sentence choice, release 1; SPEC § 10.2 E-CONNECT): at
`plan_rules.SENTENCE_TABLE` >= 1 with a table there, Connect's one door (`sentences.choose`) gathers the moment — the
dates, which files have only their show's date, how each is heard, the young words, the words marked since, the
learner's Length — and asks the score (`sentence_score.choose`); with no table, or at level 0, today's path.

What each test holds: the card's line is the score's first; *Nearest* stays in the mined episode; Swap's presses take
the next lines best first, never the old card's; *Bad card* another line; a new arrival's episode still gives cards; a
silent episode ranks, never vanishes; a book with the AI voice on and off; *Ensure an audio example*; Anki absent; the
dates kept between picks and read again after a watched mark; an unwatched episode of a started show and a book's
unread chapter; a word known since the Generate; the lines the cut can't make never crowd out one it can (Kyou-PB's
cap of 8 gone); level 0 never asks the score.

The table is the score's own in-memory one in SPEC § 3.3's shape (`tests/test_sentence_score.py`), its files real
subtitles in the sandbox's data folder; the lines are tests/Test Resources' (placed_episode.srt, night_market.srt).
"""
import os
from types import SimpleNamespace

import pytest

from app import plan_rules
from app import sentence_score as SS
from app.connect import sentences
from app.path_utils import get_data_path
from tests.test_sentence_score import FESTIVAL, NIGHT, PREPARE, SIGN, L, Library, Tokens

FEST = ("文化祭", "ぶんかさい")
MARKET = ("夜市", "yèshì")
LONG_JA = "文化祭の準備で忙しくて、ぼーっとしてて気がつかなかったけど、もう外は暗かった。"   # 39 characters
LONG_ZH = "今天晚上我们要去台北最热闹的夜市，先点一碗牛肉面，再来一杯珍珠奶茶。"
SETTINGS = {"logic": {"context": {"min_chars": 14, "preferred_max_chars": 25, "max_chars": 150}}}


class World:
    """A sandbox library at level 1: the table (`SS._table`), the moment's library (`sentences._library`: {path: (item,
    context, heard, a book or a text, its date only its show's)}), the token store's text (`SS._tokens`), settings."""

    def __init__(self, monkeypatch, language="ja", level=1, settings=None):
        self.mp, self.language = monkeypatch, language
        self.lib = Library(get_data_path(language))
        self.info, self.tokens, self.reads = {}, {}, []
        self.settings = dict(SETTINGS, **(settings or {}))
        monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", level)
        monkeypatch.setattr(sentences, "_library", self._library)
        monkeypatch.setattr(sentences, "_store_stamp", lambda language: None)
        monkeypatch.setattr(SS, "_tokens", lambda language: Tokens(self.tokens))
        from app import settings_manager
        monkeypatch.setattr(settings_manager, "load_settings", lambda *a, **k: dict(self.settings))
        sentences._DATES.clear()

    def table(self, keys, episodes, word, folder="HighPriority/show", words=None):
        """`episodes` [(name, [text, …])]: every line holding `word` is a line of row 0."""
        tab = self.lib.table([keys], episodes, lambda f, n, t: L(0, f, n, t, word) if word in t else None,
                             folder=folder)
        for name, texts in episodes:
            path = os.path.join(self.lib.root, *folder.split("/"), f"{name}.srt")
            self.tokens[path] = [(t, [[w, "", w] for w in (words or {}).get(t, ())]) for t in texts]
        self.mp.setattr(SS, "_table", lambda language: tab)
        return tab

    def path(self, name, folder="HighPriority/show"):
        return os.path.join(self.lib.root, *folder.split("/"), f"{name}.srt")

    def place(self, name, item_id, ctx=0.0, hear=sentences.REAL, text=False, show_only=False, folder=None):
        at = os.path.normcase(os.path.abspath(self.path(name, folder or "HighPriority/show")))
        self.info[at] = (item_id, ctx, hear, text, show_only)

    def _library(self, language, store=None, ai=False, only=None, scored=False):
        self.reads.append(scored)
        return {k: (v if scored else v[:4]) for k, v in self.info.items()}


def _texts(choices):
    return [c.text for c in choices]


# --- the card ------------------------------------------------------------------------------------------------------ #

@pytest.mark.parametrize("lang, key, word, here_line, better_line",
                         [("ja", FEST, "文化祭", LONG_JA, FESTIVAL), ("zh", MARKET, "夜市", LONG_ZH, NIGHT)])
def test_a_card_takes_the_scores_first_line_and_best_moves_it_only_for_a_lower_cost(monkeypatch, tmp_path, lang, key,
                                                                                   word, here_line, better_line):
    # why: release 1 — the card's sentence is the score's (the zone, the context), every line of the word a candidate;
    # the mined episode's own line comes back beside it (`_best` compares the two by their costs)
    w = World(monkeypatch, lang)
    w.table(key, [("ep01", [here_line]), ("ep02", [better_line])], word)
    w.place("ep01", 1, ctx=0.2)
    w.place("ep02", 2, ctx=0.2)
    here = w.path("ep01")
    got = sentences.choose(lang, [key], here=here, dial=sentences.BEST, young={},
                           reach=lambda item: item == 2)[key]
    direct = SS.choose(lang, [key], n=2, moment=SS.Moment(files={
        os.path.normcase(os.path.abspath(w.path(n))): SS.Seen(i, 0.2) for n, i in (("ep01", 1), ("ep02", 2))}),
        length=(14, 25))[key]
    assert _texts(got) == _texts(direct) == [better_line, here_line]
    assert [c.cost for c in got] == [l.cost for l in direct] and got[0].cost < got[1].cost
    assert got[1].here and not got[0].here and got[0].item_id == 2
    assert sentences.better(got[0], got[1]) and not sentences.better(got[1], got[0])
    # ...and through the runner's Best: the word is cut from the other episode's line, inside this job
    from app.connect import runner
    from app.connect.ledger import Ledger
    from tests.connect.test_kantan_sd_dial import _Steps
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        job = {"id": 9, "item_id": 1, "kind": "new", "store_id": "s-1"}
        words = [{"word": key[0], "reading": key[1], "line_text": here_line, "other_new": 0}]
        kept, moved = runner._best(_Steps(videos=(2,)), ledger, lang, job, words, here)
        assert moved == [] and kept[0]["from"] == 2


def test_two_lines_of_equal_cost_keep_the_word_in_its_episode():
    # why: a word moves to another episode only for a better sentence (`better`: strictly lower cost)
    a = sentences.Choice("ep02.srt", 2, FESTIVAL, 0, 0.2, False, True, False, 0, 0.12)
    b = sentences.Choice("ep01.srt", 1, PREPARE, 0, 0.2, True, True, False, 0, 0.12)
    assert not sentences.better(a, b) and not sentences.better(b, a)
    assert sentences.better(a._replace(cost=0.11), b)
    # a choice with no cost (today's path, or the episode's own line the table doesn't hold): today's rank
    assert sentences.better(a._replace(cost=None, others=0), b._replace(cost=None, others=1))


def test_nearest_stays_inside_the_mined_episode(monkeypatch):
    w = World(monkeypatch)
    w.table(FEST, [("ep01", [LONG_JA, PREPARE]), ("ep02", [FESTIVAL])], "文化祭")
    w.place("ep01", 1)
    w.place("ep02", 2, ctx=1.0)
    got = sentences.choose("ja", [FEST], here=w.path("ep01"), dial=sentences.NEAREST, young={})[FEST]
    assert _texts(got) == [PREPARE, LONG_JA], "the episode's own lines, by the score's order; never ep02's"
    assert all(c.here and c.cost is not None for c in got)


def test_at_level_zero_the_score_is_never_asked(monkeypatch):
    # why: inert — at 0 every reader takes today's path (drill 7: the same episode gives exactly today's cards)
    w = World(monkeypatch, level=0)
    w.table(FEST, [("ep01", [FESTIVAL])], "文化祭")

    def asked(*a, **k):
        raise AssertionError("the score was asked at level 0")
    monkeypatch.setattr(SS, "choose", asked)
    assert sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, files=[]) == {FEST: []}
    assert True not in w.reads, "the moment's show-only mark is the score's alone"
    assert sentences.read_ahead("ja") is False


def test_no_table_takes_todays_path(monkeypatch):
    w = World(monkeypatch)
    monkeypatch.setattr(SS, "_table", lambda language: None)
    monkeypatch.setattr(sentences, "_from_list", lambda *a, **k: pytest.fail("no plan here either"))
    assert sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, files=[]) == {FEST: []}
    assert sentences.read_ahead("ja") is False


# --- Swap and *Bad card* --------------------------------------------------------------------------------------------- #

FIVE = [("ep01", [FESTIVAL]), ("ep02", [PREPARE]), ("ep03", ["文化祭の看板は私が描くね。"]),
        ("ep04", ["文化祭、楽しみだね。"]), ("ep05", [LONG_JA])]


def _five(monkeypatch):
    w = World(monkeypatch)
    w.table(FEST, FIVE, "文化祭")
    for n, (name, _lines) in enumerate(FIVE, 1):
        w.place(name, n, ctx=0.5 - n / 10)          # each a little less remembered than the one before
    return w


def test_swap_three_presses_give_the_next_three_lines_best_first_never_the_old_cards(monkeypatch):
    from app.connect import swap
    w = _five(monkeypatch)
    best = _texts(sentences.choose("ja", [FEST], dial=sentences.BEST, young={})[FEST])
    assert best[0] == FESTIVAL and len(best) == 5
    avoid, presses = {FESTIVAL}, []                 # the old card's line
    for _press in range(3):
        item, text = swap.choose_line("ja", FEST[0], avoid=avoid, reading=FEST[1])
        presses.append(text)
        avoid.add(text)                             # a swap moved away from is never offered again
    assert presses == best[1:4]
    assert FESTIVAL not in presses


def test_bad_card_takes_another_line_never_the_deleted_cards_or_its_episodes(monkeypatch):
    from app.connect import swap
    _five(monkeypatch)
    item, text = swap.choose_line("ja", FEST[0], avoid={FESTIVAL}, skip_items={2}, reading=FEST[1])
    assert (item, text) == (3, "文化祭の看板は私が描くね。")


# --- what the cut can make, and how a line is heard ---------------------------------------------------------------- #

def test_lines_whose_media_cant_be_cut_never_crowd_out_the_one_that_can(monkeypatch):
    # why: Kyou-PB's gap — today a word kept 8 lines before the unsaid ones were dropped; the score's reader has every
    # line, so a word whose ten best lines can't be cut still gets its eleventh
    w = World(monkeypatch)
    episodes = [(f"ep{n:02d}", [FESTIVAL if n < 11 else LONG_JA]) for n in range(1, 12)]
    w.table(FEST, episodes, "文化祭")
    for n in range(1, 12):
        w.place(f"ep{n:02d}", n)
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: item == 11)[FEST]
    assert [(c.item_id, c.text) for c in got] == [(11, LONG_JA)]


def test_a_silent_episode_ranks_lower_but_never_vanishes(monkeypatch):
    # why: his principle — "It should not remove those entirely, it should just be less weighted"; today a book's line
    # nothing can speak was dropped wherever media is cut
    w = World(monkeypatch)
    w.table(FEST, [("ep01", [FESTIVAL]), ("book01", [PREPARE])], "文化祭")
    w.place("ep01", 1)
    w.place("book01", 2, hear=sentences.SILENT, text=True)
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: item == 1)[FEST]
    assert [(c.text, c.audio) for c in got] == [(FESTIVAL, True), (PREPARE, False)]
    assert got[1].cost - got[0].cost == pytest.approx(SS.HEARD_SILENT)
    # where books can't be mined at all (Anki Miner's books off), its line is no card: left out
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: item == 1,
                           books=False)[FEST]
    assert _texts(got) == [FESTIVAL]


@pytest.mark.parametrize("lang, key, word, lines", [("ja", FEST, "文化祭", [FESTIVAL, PREPARE]),
                                                    ("zh", MARKET, "夜市", [NIGHT, NIGHT.replace("今天", "明天")])])
def test_a_book_with_the_ai_voice_on_is_weighed_as_voiced_and_off_as_silent(monkeypatch, lang, key, word, lines):
    w = World(monkeypatch, lang)
    w.table(key, [("book01", [lines[0]]), ("ep02", [lines[1]])], word)
    w.place("ep02", 2)
    for ai, hear, rate in ((True, sentences.AI_VOICE, SS.HEARD_AI), (False, sentences.SILENT, SS.HEARD_SILENT)):
        sentences._DATES.clear()
        w.place("book01", 1, ctx=0.5, hear=hear, text=True)
        monkeypatch.setattr(sentences, "ai_voice", lambda settings, language, on=ai: on)
        got = {c.item_id: c for c in sentences.choose(lang, [key], dial=sentences.BEST, young={},
                                                     reach=lambda item: item == 2)[key]}
        assert got[1].ai is ai and got[1].audio is ai
        assert got[1].cost == pytest.approx(got[2].cost - SS.CONTEXT * 0.5 + rate)


def test_a_lined_up_books_line_its_line_up_never_says_is_weighed_as_unheard(monkeypatch):
    # why: Kyou-PB — a paired chapter is heard only where its line-up gives the line a clip; the score weighs a file,
    # so the line it doesn't say is re-weighed by the two hearing rates (a clip, then none)
    w = World(monkeypatch)
    w.table(FEST, [("book01", [FESTIVAL, PREPARE])], "文化祭")
    w.place("book01", 1, text=True)
    monkeypatch.setattr(sentences, "_heard_line",
                        lambda hear, text, ai: sentences.SILENT if text == FESTIVAL else sentences.REAL)
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: True)[FEST]
    assert [(c.text, c.audio) for c in got] == [(PREPARE, True), (FESTIVAL, False)]
    assert got[1].cost == pytest.approx(SS.HEARD_SILENT)


def test_ensure_an_audio_example_gives_the_card_the_heard_line_and_keeps_the_silent_one(monkeypatch):
    # drill 6: a word with one heard and one better silent sentence gets the heard one
    w = World(monkeypatch, settings={"ensure_audio_example": True})
    w.table(FEST, [("book01", [FESTIVAL]), ("ep02", [LONG_JA])], "文化祭")
    w.place("book01", 1, ctx=1.0, hear=sentences.SILENT, text=True)
    w.place("ep02", 2)
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: item == 2)[FEST]
    assert _texts(got) == [LONG_JA, FESTIVAL] and got[1].cost < got[0].cost
    w.settings["ensure_audio_example"] = False
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: item == 2)[FEST]
    assert _texts(got) == [FESTIVAL, LONG_JA]


# --- the moment ---------------------------------------------------------------------------------------------------- #

def test_a_young_word_lifts_its_sentence_and_with_anki_absent_nothing_breaks(monkeypatch):
    # drill 8: a word still young in one of two otherwise equal sentences — the card takes that sentence; Anki absent
    # (its young record unreadable): no young word, the score's own order
    w = World(monkeypatch)
    w.table(FEST, [("ep01", [FESTIVAL, PREPARE])], "文化祭", words={PREPARE: ["文化祭", "手伝う"]})
    w.place("ep01", 1)
    assert _texts(sentences.choose("ja", [FEST], dial=sentences.BEST, young={"手伝う": 0.5})[FEST]) == \
        [PREPARE, FESTIVAL]
    from app import anki_sync

    def closed(language):
        raise OSError("Anki isn't there")
    monkeypatch.setattr(anki_sync, "young_words", closed)
    assert sentences.young_weights("ja") == {}
    assert _texts(sentences.choose("ja", [FEST], dial=sentences.BEST)[FEST]) == [FESTIVAL, PREPARE]


def test_a_word_known_since_the_generate_no_longer_counts_as_new_in_a_sentence(monkeypatch):
    # SPEC § 7 row 8: a word you marked since the Generate (✓ Known, or Ignore) counts as known at once
    from app.path_utils import get_user_file
    from app.services import word_lists
    w = World(monkeypatch)
    keys = [FEST, ("看板", "かんばん")]
    tab = w.lib.table(keys, [("ep01", [FESTIVAL, SIGN])], lambda f, n, t: L(0, f, n, t, "文化祭", cow=[0] if n else ()),
                      cowords=[(1, [[1]])], folder="HighPriority/show")
    w.tokens[w.path("ep01")] = [(FESTIVAL, []), (SIGN, [])]
    monkeypatch.setattr(SS, "_table", lambda language: tab)
    w.place("ep01", 1)
    results = get_user_file("results")
    os.makedirs(results, exist_ok=True)
    with open(os.path.join(results, "sentences.bin"), "wb") as f:
        f.write(b"the Generate's table")
    os.utime(os.path.join(results, "sentences.bin"), ns=(1, 10 ** 18))     # written long before the mark below
    before = {c.text: c for c in sentences.choose("ja", [FEST], dial=sentences.BEST, young={})[FEST]}
    assert before[SIGN].others == 1                 # 看板, a row below 文化祭: new when the card is studied
    path = word_lists.list_path("ignore", "ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("看板\n")
    os.utime(path, ns=(2 * 10 ** 18, 2 * 10 ** 18))
    assert sentences.known_since("ja") == {("看板", "")}
    after = {c.text: c for c in sentences.choose("ja", [FEST], dial=sentences.BEST, young={})[FEST]}
    assert after[SIGN].others == 0 and after[SIGN].cost == pytest.approx(before[SIGN].cost - SS.NEW_WORD)


def _show(language="ja"):
    from tests.test_library_store_support import migrated
    store = migrated(language, shows=1, episodes=3, loose=0, tiers=("now",))
    ids = [row[0] for row in store.conn.execute("SELECT id FROM items ORDER BY rel_path")]
    return store, ids


def test_an_unwatched_episode_of_a_started_show_has_only_its_shows_date_and_a_finished_show_counts_whole():
    store, (first, second, third) = _show()
    with store:
        store.set_watched([first])

        def marks(scored):
            return {v[0]: v[1:] for v in sentences._library("ja", store, scored=scored).values()}
        scored, today = marks(True), marks(False)
        assert scored[first][3] is False and scored[second][3] is True and scored[third][3] is True
        assert scored[second][0] == today[second][0], "the context itself is Connect's, unchanged"
        assert all(len(v) == 3 for v in today.values()), "level 0's answer: today's shape"
        with store._writing():
            store.conn.execute("UPDATE items SET tier = 'graduated' WHERE id = ?", (third,))
        scored = marks(True)
        assert scored[second][3] is False, "some of the show in Finished: every episode counts as seen"


def test_a_books_unread_chapter_counts_by_its_place_not_its_books_date():
    # the lead's ruling (OPEN 78 a, 2026-11-23): an unread chapter of a started book gets no remembered share
    from tests.connect.test_kyou_pb_paired_heard import _books, _parts
    book = _books("ja")
    store = book["store"]
    with store:
        first, second = _parts(store, book["epub"])[:2]
        store.set_watched([first])
        scored = {v[0]: v for v in sentences._library("ja", store, scored=True).values()}
        today = {v[0]: v for v in sentences._library("ja", store).values()}
        assert today[second][1] == today[first][1], "level 0: the book's date (today's rule, unchanged)"
        assert scored[second][1] < scored[first][1] and scored[second][4] is False
        assert scored[first][1] == pytest.approx(today[first][1], abs=1e-6)


def test_the_dates_are_kept_between_picks_and_read_again_after_a_watched_mark(monkeypatch):
    # why: one read of the store was nearly all of a pick's time (SPEC § 5.3); a watched mark changes the store's file
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 1)
    sentences._DATES.clear()
    store, (first, second, _third) = _show()
    reads = []
    real = sentences._library

    def counted(*a, **k):
        reads.append(1)
        return real(*a, **k)
    monkeypatch.setattr(sentences, "_library", counted)
    store.close()
    info, _seen = sentences._dates("ja", False)
    info2, _seen = sentences._dates("ja", False)
    assert len(reads) == 1 and info2 is info, "kept while the store's file is unchanged"
    from app.connect import library
    store = library.open_store("ja", role="window")
    with store:
        store.set_watched([first])
    info3, seen3 = sentences._dates("ja", False)
    assert len(reads) == 2, "read again after a watched mark"
    assert max(v[1] for v in info3.values()) > max(v[1] for v in info.values())
    assert any(s.show_only for s in seen3.values())
    monkeypatch.setattr(sentences, "time", SimpleNamespace(monotonic=lambda: 10.0 ** 9))
    sentences._dates("ja", False)
    assert len(reads) == 3, "an hour at most: the days pass"


def test_read_ahead_reads_the_tables_head_and_the_dates_at_level_one(monkeypatch):
    w = World(monkeypatch)
    w.table(FEST, [("ep01", [FESTIVAL])], "文化祭")
    w.place("ep01", 1)
    monkeypatch.setattr(sentences, "_store_stamp", lambda language: ("store", (1, 1), None))
    assert sentences.read_ahead("ja") is True
    assert w.reads == [True] and ("ja", False) in sentences._DATES
    sentences.choose("ja", [FEST], dial=sentences.BEST, young={})
    assert w.reads == [True], "the first pick reads no store: the dates were read ahead"


def test_a_new_arrivals_episode_still_gives_cards_before_the_next_generate(monkeypatch):
    # SPEC § 7 row 7: the new file has no lines in the table until the next Generate; a word whose only sentence is
    # there is no row of the table, so Connect's own read (the library search over the token store) finds it
    from tests.connect.test_kantan_sd_dial import EASY, _key, _lemmas
    from tests.connect.test_kantan_sd_dial import _library as indexed
    (new,) = indexed("ja", {"新着第01話.txt": [EASY]}, known=_lemmas(EASY) - {"冒険"})
    w = World(monkeypatch)
    monkeypatch.setattr(sentences, "_library", lambda language, store=None, ai=False, only=None, scored=False: {})
    w.table(FEST, [("ep01", [FESTIVAL])], "文化祭")
    key = _key(EASY, "冒険")
    got = sentences.choose("ja", [key, FEST], here=new, dial=sentences.BEST, files=[new], young={})
    assert _texts(got[key]) == [EASY] and got[key][0].here and got[key][0].cost is None
    assert got[FEST] == [], "a row of the table: the score's answer (its one file is outside `files`)"


def test_what_the_moment_hands_the_score_is_connects_own(monkeypatch):
    # the score never reads the store, Anki or settings itself: the young words, the marks since and Length come in
    w = World(monkeypatch, settings={"logic": {"context": {"min_chars": 12, "preferred_max_chars": 40,
                                                           "max_chars": 150}}})
    w.table(FEST, [("ep01", [FESTIVAL])], "文化祭")
    w.place("ep01", 1, ctx=0.25, show_only=True)
    seen = {}
    real = SS.choose

    def spy(language, keys, **kw):
        seen.update(kw)
        return real(language, keys, **kw)
    monkeypatch.setattr(SS, "choose", spy)
    monkeypatch.setattr(sentences, "known_since", lambda language: {("看板", "")})
    sentences.choose("ja", [FEST], dial=sentences.BEST, young={"手伝う": 0.5})
    assert seen["length"] == (12, 40) and seen["heard_first"] is False
    moment = seen["moment"]
    assert moment.young == {"手伝う": 0.5} and moment.known == {("看板", "")}
    (s,) = moment.files.values()
    assert s == SS.Seen(1, 0.25, sentences.REAL, True)
