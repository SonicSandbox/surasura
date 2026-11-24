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
        for thread in list(getattr(sentences, "_AHEAD", {}).values()):     # (a read ahead a test before left: done
            thread.join(10)                                                 # before this world's stand-ins are in)
            assert not thread.is_alive(), "a read of the dates ahead outlived its test"
        getattr(sentences, "_AHEAD", {}).clear()
        self.lib = Library(get_data_path(language))
        self.info, self.tokens, self.reads = {}, {}, []
        self.settings = dict(SETTINGS, **(settings or {}))
        monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", level)
        monkeypatch.setattr(sentences, "_library", self._library)
        # (raising=False, getattr: the fixture holds on the code before, so a red there is the behaviour's, not setup's)
        monkeypatch.setattr(sentences, "_store_stamp", lambda language: None, raising=False)
        monkeypatch.setattr(SS, "_tokens", lambda language: Tokens(self.tokens))
        from app import settings_manager
        monkeypatch.setattr(settings_manager, "load_settings", lambda *a, **k: dict(self.settings))
        getattr(sentences, "_DATES", {}).clear()

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


def test_each_swap_press_is_the_scores_first_line_at_that_press_as_a_young_line_enters_the_young_window(monkeypatch):
    # why: the lead's ruling 2 (2026-11-23, drill 2: three of five words' presses were not the static list's next
    # three) — a press asks the score at its own moment, the lines moved away from banned; a line holding a young word
    # is lifted only while it is among the first YOUNG_LINES the score walks, so once the lines ahead of it are banned
    # it is lifted and comes sooner than the list before the presses said. Never a bug of Swap's: the score's own
    w = World(monkeypatch)
    guitar = "文化祭のライブでギターを弾くことになった。"
    episodes = FIVE + [("ep06", [guitar])]
    w.table(FEST, episodes, "文化祭", words={guitar: ["ギター"]})
    for n, (name, _lines) in enumerate(episodes, 1):
        w.place(name, n, ctx=0.5 - n / 10)
    monkeypatch.setattr(sentences, "young_weights", lambda language, read=None: {"ギター": 1.0})
    before = _texts(sentences.choose("ja", [FEST], dial=sentences.BEST)[FEST])
    assert before.index(guitar) == SS.YOUNG_LINES          # past the young window: not lifted yet
    from app.connect import swap
    avoid, presses = {before[0]}, []
    for _press in range(3):
        at_press = sentences.choose("ja", [FEST], dial=sentences.BEST, never={FEST: set(avoid)})[FEST]
        item, text = swap.choose_line("ja", FEST[0], avoid=avoid, reading=FEST[1])
        assert text == at_press[0].text                    # the score's first line at the press
        presses.append(text)
        avoid.add(text)
    assert presses == [before[1], guitar, before[2]] != before[1:4]


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
        getattr(sentences, "_DATES", {}).clear()
        w.place("book01", 1, ctx=0.5, hear=hear, text=True)
        monkeypatch.setattr(sentences, "ai_voice", lambda settings, language, on=ai: on)
        got = {c.item_id: c for c in sentences.choose(lang, [key], dial=sentences.BEST, young={},
                                                     reach=lambda item: item == 2)[key]}
        assert got[1].ai is ai and got[1].audio is ai
        assert got[1].cost == pytest.approx(got[2].cost - SS.CONTEXT * 0.5 + rate)


def _said(*lines):
    """A lined-up book's usable line-up that says `lines` (`lineup.reach`'s own shape)."""
    from app.connect import lineup
    texts = [lineup.clean(t) for t in lines]
    heads = {}
    for t in texts:
        if len(t) >= lineup.MIN_CHARS:
            heads.setdefault(t[:lineup.MIN_CHARS], set()).add(t)
    return lineup.Reach(frozenset(texts), "\n".join(texts), heads)


def test_a_lined_up_books_line_its_line_up_never_says_is_weighed_as_unheard(monkeypatch):
    # why: Kyou-PB — a paired chapter is heard only where its line-up gives the line a clip (`lineup.said`); the score
    # weighs that line as the book with no audiobook's (silent, the AI voice off), its said line as its own clip
    w = World(monkeypatch)
    w.table(FEST, [("book01", [FESTIVAL, PREPARE])], "文化祭")
    w.place("book01", 1, hear=_said(PREPARE), text=True)
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: True)[FEST]
    assert [(c.text, c.audio) for c in got] == [(PREPARE, True), (FESTIVAL, False)]
    assert got[1].cost == pytest.approx(SS.HEARD_SILENT)


def test_a_said_line_behind_eight_unsaid_ones_still_gives_the_card(monkeypatch):
    # why: the lead's ruling (2026-11-23) — paired books' hearing is exact inside the score, not re-weighed after it:
    # re-weighing the eight lines the score returned missed a said line just behind them, and the card got a line with
    # no clip. Eight chapters whose line-up never says the word's line (each 0 in the zone, 0.4 unheard) and a ninth
    # that says its line (13 characters: 0.03)
    w = World(monkeypatch)
    episodes = [(f"ch{n:02d}", [FESTIVAL]) for n in range(1, 9)] + [("ch09", [SIGN])]
    w.table(FEST, episodes, "文化祭")
    for n in range(1, 10):
        w.place(f"ch{n:02d}", n, hear=_said(SIGN), text=True)
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: True)[FEST]
    assert (got[0].text, got[0].item_id, got[0].audio) == (SIGN, 9, True)
    assert got[0].cost == pytest.approx(0.03) and all(c.cost == pytest.approx(SS.HEARD_SILENT) for c in got[1:])


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


def _synced(language, word):
    """KnownWord.json as the Anki sync leaves it after a card of `word` turned known (`anki_sync._entry`'s shape),
    written long after the Generate."""
    import json
    from app import anki_sync
    path = anki_sync._known_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {"dictForm": word, "knownStatus": "KNOWN", "hasCard": 1, "language": language, "source": anki_sync.SOURCE}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"source": anki_sync.SOURCE, "words": [entry]}, f, ensure_ascii=False)
    os.utime(path, ns=(2 * 10 ** 18, 2 * 10 ** 18))


def test_a_word_the_anki_sync_marks_known_is_never_later_on_the_new_path_than_on_todays(monkeypatch):
    # why: the lead's ruling (2026-11-23) — the new path is never behind today's. Today's list path counts a line's
    # other new words as the last Generate wrote them (`_from_list`: the plan's co-words, never re-read at the pick),
    # so a word the Anki sync marks known counts from the next Generate on (Connect's verdict runs one after mining);
    # the score's path is the same for the sync's words (the table's places) — and ahead for a word marked in the
    # window, above. Both are pinned here, so a later change that makes either count at once moves both.
    from tests.connect.test_kantan_sd_list import BOUKEN, EASY, HARD, _plan, _write
    monkeypatch.setattr(plan_rules, "SENTENCE_TABLE", 0)
    here = _write("ja", "第01話.srt", [HARD])
    info = {os.path.normcase(os.path.abspath(here)): (1, 0.0, sentences.REAL, False)}
    monkeypatch.setattr(sentences, "_library", lambda language, store=None, ai=False, only=None, scored=False: info)
    _plan("ja", [here], {BOUKEN: [(0, 0, HARD, 3)]})
    today = sentences.choose("ja", [BOUKEN], dial=sentences.BEST, young={})[BOUKEN]
    _synced("ja", "迷宮")                           # one of HARD's other new words
    assert [c.others for c in sentences.choose("ja", [BOUKEN], dial=sentences.BEST, young={})[BOUKEN]] == \
        [c.others for c in today] == [3], "today's: counted from the plan until the next Generate"
    # the score's path: 看板, a row below 文化祭, known by the sync since the table was written
    w = World(monkeypatch)
    keys = [FEST, ("看板", "かんばん")]
    tab = w.lib.table(keys, [("ep01", [FESTIVAL, SIGN])], lambda f, n, t: L(0, f, n, t, "文化祭", cow=[0] if n else ()),
                      cowords=[(1, [[1]])], folder="HighPriority/show")
    w.tokens[w.path("ep01")] = [(FESTIVAL, []), (SIGN, [])]
    monkeypatch.setattr(SS, "_table", lambda language: tab)
    w.place("ep01", 1)
    from app.path_utils import get_user_file
    results = get_user_file("results")
    with open(os.path.join(results, "sentences.bin"), "wb") as f:
        f.write(b"the Generate's table")
    os.utime(os.path.join(results, "sentences.bin"), ns=(1, 10 ** 18))
    before = {c.text: c.others for c in sentences.choose("ja", [FEST], dial=sentences.BEST, young={})[FEST]}
    _synced("ja", "看板")
    assert sentences.known_since("ja") == set(), "the sync's entry is no mark made in the window"
    after = {c.text: c.others for c in sentences.choose("ja", [FEST], dial=sentences.BEST, young={})[FEST]}
    assert before[SIGN] == after[SIGN] == 1, "the score's: new until the next Generate, as today's"


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
        # (the fade reads the clock at each call: the two reads are milliseconds apart)
        assert scored[second][0] == pytest.approx(today[second][0], abs=1e-6), "the context itself is Connect's"
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
    getattr(sentences, "_DATES", {}).clear()
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
    monkeypatch.setattr(sentences, "_store_stamp", lambda language: ("store", (1, 1), None), raising=False)
    assert sentences.read_ahead("ja") is True
    sentences._AHEAD[("ja", False)].join(10)       # (the dates are a thread's read: E-FAST 6, row 16)
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


def test_nearest_in_an_episode_the_table_holds_no_line_of_the_word_reads_it_as_today(monkeypatch):
    # why: the table is the last Generate's; an episode it holds no line of the word in (a new arrival's, a file read
    # again since) is read as today — the episode's own lines from the token store — never left with no sentence
    from tests.connect.test_kantan_sd_dial import EASY, HARD, _key, _lemmas
    from tests.connect.test_kantan_sd_dial import _library as indexed
    (new,) = indexed("ja", {"新着第01話.txt": [EASY]}, known=_lemmas(EASY) - {"冒険"})
    w = World(monkeypatch)
    monkeypatch.setattr(sentences, "_library", lambda language, store=None, ai=False, only=None, scored=False: {})
    key = _key(EASY, "冒険")
    w.table(key, [("ep01", [HARD])], "冒険")          # a row of the table, its one line elsewhere
    got = sentences.choose("ja", [key], here=new, dial=sentences.NEAREST, young={})[key]
    assert _texts(got) == [EASY] and got[0].here and got[0].cost is None


def test_the_mined_episodes_own_line_comes_back_beside_the_best_eight_when_it_is_not_among_them(monkeypatch):
    # why: Best moves a word only for a strictly better sentence (`runner._best` compares the two by cost) — so the
    # episode's own line is asked apart when the eight best are all elsewhere, and handed back with its own cost
    w = World(monkeypatch)
    episodes = [(f"ep{n:02d}", [FESTIVAL]) for n in range(2, 11)] + [("ep01", [LONG_JA])]
    w.table(FEST, episodes, "文化祭")
    for n in range(1, 11):
        w.place(f"ep{n:02d}", n)
    got = sentences.choose("ja", [FEST], here=w.path("ep01"), dial=sentences.BEST, young={})[FEST]
    assert len(got) == sentences.TOP + 1 and [c.here for c in got] == [False] * sentences.TOP + [True]
    assert got[-1].text == LONG_JA and got[-1].cost > got[0].cost and sentences.better(got[0], got[-1])


def test_one_pick_builds_the_scores_setup_once_across_its_asks_and_chooses_the_same(monkeypatch):
    # why: the lead's waste card (F6, 2026-11-23) — one pick asks the score more than once (the main ask, then the
    # mined episode's own line apart; a growth ask when lines can't be cut): the rows' index and the moment's arrays
    # are the same between them, so they are built once a pick — and the choices are the ones built afresh each ask
    w = World(monkeypatch)
    episodes = [(f"ep{n:02d}", [FESTIVAL]) for n in range(2, 11)] + [("ep01", [LONG_JA])]
    w.table(FEST, episodes, "文化祭")
    for n in range(1, 11):
        w.place(f"ep{n:02d}", n)
    real_choose, real_rows, real_known = SS.choose, SS._key_rows, SS.known_at
    asks, built = [], {"rows": 0, "known": 0}

    def counted(name, real):
        def call(*a, **k):
            built[name] += 1
            return real(*a, **k)
        return call
    monkeypatch.setattr(SS, "_key_rows", counted("rows", real_rows))
    monkeypatch.setattr(SS, "known_at", counted("known", real_known))
    monkeypatch.setattr(SS, "choose", lambda *a, **k: (asks.append(k.get("only")), real_choose(*a, **k))[1])
    got = sentences.choose("ja", [FEST], here=w.path("ep01"), dial=sentences.BEST, young={"準備": 0.5})[FEST]
    assert len(asks) == 2 and asks[1] is not None           # the main ask, then the mined episode's own line
    assert built == {"rows": 1, "known": 1}
    # the same choices, and the same costs, as two asks that each build their own
    monkeypatch.setattr(SS, "choose", lambda *a, memo=None, **k: real_choose(*a, **k))
    fresh = sentences.choose("ja", [FEST], here=w.path("ep01"), dial=sentences.BEST, young={"準備": 0.5})[FEST]
    assert [(c.text, c.file, c.cost, c.here) for c in got] == [(c.text, c.file, c.cost, c.here) for c in fresh]
    assert got[-1].here and got[-1].text == LONG_JA


def test_a_memo_kept_from_another_moment_is_built_again_and_never_answers_for_it(monkeypatch):
    # why: the memo is the asks of one pick's — a caller that hands the same dict to another moment (another young
    # word, another file's date) gets that moment's choices, never the first one's arrays
    w = World(monkeypatch)
    w.table(FEST, FIVE, "文化祭")
    root, memo = get_data_path("ja"), {}
    at = {name: os.path.normcase(os.path.abspath(w.path(name))) for name, _lines in FIVE}
    old = SS.Moment(files={at["ep01"]: SS.Seen(1, 1.0)}, root=root)
    new = SS.Moment(files={at["ep05"]: SS.Seen(5, 1.0)}, root=root)
    for moment in (old, new, old):
        kept = SS.choose("ja", [FEST], n=5, moment=moment, length=(14, 25), memo=memo)[FEST]
        fresh = SS.choose("ja", [FEST], n=5, moment=moment, length=(14, 25))[FEST]
        assert [(l.text, l.cost) for l in kept] == [(l.text, l.cost) for l in fresh]
    assert SS.choose("ja", [FEST], n=1, moment=new, length=(14, 25))[FEST][0].text == LONG_JA !=         SS.choose("ja", [FEST], n=1, moment=old, length=(14, 25))[FEST][0].text


def test_the_mined_episodes_own_line_comes_back_after_an_ask_that_heard_a_lined_up_book_line_by_line(monkeypatch):
    # why: the asks of one pick share the moment's arrays (the waste card) — the first ask's per-line hearing of a
    # lined-up book is its own: the next ask (the mined episode's own line, apart) never inherits it
    w = World(monkeypatch)
    episodes = [(f"ch{n:02d}", [FESTIVAL]) for n in range(1, 10)] + [("ep01", [LONG_JA])]
    w.table(FEST, episodes, "文化祭")
    for n in range(1, 10):
        w.place(f"ch{n:02d}", n, hear=_said(FESTIVAL), text=True)
    w.place("ep01", 10)
    got = sentences.choose("ja", [FEST], here=w.path("ep01"), dial=sentences.BEST, young={},
                           reach=lambda item: True)[FEST]
    assert len(got) == sentences.TOP + 1 and all(c.audio and not c.here for c in got[:-1])
    assert got[-1].here and got[-1].text == LONG_JA


def test_a_later_ask_for_other_words_never_inherits_the_first_asks_per_line_hearing(monkeypatch):
    # why: the moment's arrays are shared by the asks of one pick (the waste card); the per-line hearing of a lined-up
    # book is one ask's own, sized to its lines — a later ask (a growth ask, other words) reads its own or none
    w = World(monkeypatch)
    ready, ready_key = "明日の準備はもう終わったの？", ("準備", "じゅんび")
    tab = w.lib.table([FEST, ready_key], [("book01", [FESTIVAL, SIGN]), ("ep02", [ready])],
                      lambda f, n, t: L(0, f, n, t, "文化祭") if "文化祭" in t else
                      (L(1, f, n, t, "準備") if "準備" in t else None), folder="HighPriority/show")
    w.tokens.update({w.path("book01"): [(FESTIVAL, []), (SIGN, [])], w.path("ep02"): [(ready, [])]})
    monkeypatch.setattr(SS, "_table", lambda language: tab)
    book = os.path.normcase(os.path.abspath(w.path("book01")))
    moment = SS.Moment(files={book: SS.Seen(1, 0.0, said=lambda text: text == SIGN)}, root=get_data_path("ja"))
    memo = {}
    first = SS.choose("ja", [FEST], n=2, moment=moment, length=(1, 99), memo=memo)[FEST]
    assert [(l.text, l.heard) for l in first] == [(SIGN, SS.REAL), (FESTIVAL, SS.SILENT)]
    later = SS.choose("ja", [ready_key], n=1, moment=moment, length=(1, 99), memo=memo)[ready_key]
    fresh = SS.choose("ja", [ready_key], n=1, moment=moment, length=(1, 99))[ready_key]
    assert [(l.text, l.cost, l.heard) for l in later] == [(l.text, l.cost, l.heard) for l in fresh]
    assert later[0].text == ready


def test_a_book_outside_the_store_is_weighed_as_a_book_with_no_audiobook(monkeypatch):
    # why: the score hears a file it has no word of by its own clip; Connect knows a book or a text by its extension
    # (`library.text_only`) — with no store (or a file it doesn't hold) a book's line is weighed silent, as today
    from app.connect import library
    w = World(monkeypatch)
    w.table(FEST, [("book01", [FESTIVAL]), ("ep02", [FESTIVAL])], "文化祭")
    real = library.text_only
    monkeypatch.setattr(library, "text_only", lambda item: "book01" in str(item.get("rel_path")) or real(item))
    got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={})[FEST]
    assert [(os.path.basename(c.file), c.audio) for c in got] == [("ep02.srt", True), ("book01.srt", False)]
    assert got[1].cost - got[0].cost == pytest.approx(SS.HEARD_SILENT)


def test_a_line_up_that_changes_between_picks_is_heard_as_it_is_now_while_the_dates_are_kept(monkeypatch):
    # why: a line-up that finishes, is done again or loses its audio writes nothing to the library store, so the kept
    # dates can't tell — each paired book's hearing is asked again at every pick (`lineup.reach`, its own cache)
    from app.connect import lineup
    w = World(monkeypatch)
    monkeypatch.setattr(sentences, "_store_stamp", lambda language: ("store", (1, 1), None), raising=False)
    w.table(FEST, [("book01", [FESTIVAL]), ("ep02", [FESTIVAL])], "文化祭")
    w.place("ep02", 2)
    record = {"book": {"key": "bk"}}
    at = os.path.normcase(os.path.abspath(w.path("book01")))
    w.info[at] = (1, 0.0, _said(FESTIVAL), True, False, ("book01", record))
    now = {"reach": _said(FESTIVAL)}
    monkeypatch.setattr(lineup, "reach", lambda audiobook: now["reach"] if audiobook is record else None)

    def heard_book():
        got = sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, reach=lambda item: True)[FEST]
        return {c.item_id: c.audio for c in got}[1]
    assert heard_book() is True
    now["reach"] = None                             # its audiobook moved away: no clip any more
    assert heard_book() is False and w.reads == [True], "the dates kept (one read), the hearing asked again"
    now["reach"] = _said(PREPARE)                   # lined up again: it says another line, not this one
    assert heard_book() is False
    now["reach"] = True                             # not lined up yet: its part's job lines it up first
    assert heard_book() is True


def test_an_empty_answer_from_the_store_is_never_kept(monkeypatch):
    # why: a store busy at its open answers {} — kept, every pick of the next hour would weigh no dates at all
    w = World(monkeypatch)
    monkeypatch.setattr(sentences, "_store_stamp", lambda language: ("store", (1, 1), None), raising=False)
    sentences._dates("ja", False)
    w.place("ep01", 1, ctx=0.5)
    info, _seen = sentences._dates("ja", False)
    assert w.reads == [True, True] and info, "read again: the first answer was empty"


def test_a_failure_on_the_scores_path_takes_todays_path(monkeypatch):
    # why: the score's path never makes a pick worse than today's
    w = World(monkeypatch)
    w.table(FEST, [("ep01", [FESTIVAL])], "文化祭")

    def broken(language, ai):
        raise OSError("the store's disk went away")
    monkeypatch.setattr(sentences, "_dates", broken)
    today = []
    monkeypatch.setattr(sentences, "_listed", lambda language: today.append(language) or (None, {}))
    assert sentences.choose("ja", [FEST], dial=sentences.BEST, young={}, files=[]) == {FEST: []}
    assert today == ["ja"]


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
