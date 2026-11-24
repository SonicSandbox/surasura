"""Connect's pick on the score reads only what it uses (the sentence choice, release 1; SPEC § 6.1 rows 4-6): the
card's ask (`runner._best`) and Swap's (`swap.choose_line`) read the text of the lines they take — the score's first
and the mined episode's own — so the token store decodes those files only, and the choice is the one asking eight
lines a word gave. What makes one line enough: a file outside the store is heard by its own extension inside the score
(`Moment.unnamed`), so the score's first is Connect's first; a line the cut can't make, or *Ensure an audio example*
with no heard line the cut can make, asks again for more; a young word's lines are read only where it can lift one to
the top (an exact bound). The words marked since the Generate and the rows' arrays are kept across picks while
nothing they are made of changed. The cut takes the score's best line that fits the 8 s cap uncut, else its first
(SPEC §§ 11-12).

The table and the token store are the score's in-memory ones (`tests/connect/test_e_connect_score.py`'s World), the
files real subtitles in the sandbox's data folder; lines as tests/Test Resources/ja|zh write them.
"""
import os

import pytest

from app import analyzer, cues
from app import sentence_score as SS
from app.connect import pick, sentences
from app.connect.ledger import Ledger
from tests.connect.test_e_connect_score import FEST, LONG_JA, LONG_ZH, MARKET, World
from tests.test_sentence_score import FESTIVAL, NIGHT, PREPARE, SIGN, Tokens

SHOP_ZH = "我们在夜市买了很多好吃的小吃。"
TOMORROW_ZH = "我们明天去夜市吃牛肉面吧"
HOT_ZH = "夜市好热闹。"
LINES = {"ja": [FESTIVAL, PREPARE, SIGN, "文化祭、楽しみだね。", LONG_JA],
         "zh": [NIGHT, SHOP_ZH, TOMORROW_ZH, HOT_ZH, LONG_ZH]}
CASES = [("ja", FEST, "文化祭", LONG_JA), ("zh", MARKET, "夜市", LONG_ZH)]


class Counted(Tokens):
    """The token store's read side, each file it decodes noted (`file_tokens`: a whole file's sentences)."""

    def __init__(self, files, reads):
        super().__init__(files)
        self.reads = reads

    def file_tokens(self, path):
        self.reads.append(os.path.splitext(os.path.basename(path))[0])
        return super().file_tokens(path)


def _counted(monkeypatch, w):
    reads = []
    monkeypatch.setattr(SS, "_tokens", lambda language: Counted(w.tokens, reads))
    return reads


class _Steps:
    """The runner's steps as `_best` asks them: Best, a video for every item but those in `no_video`, books mined."""

    def __init__(self, no_video=()):
        self.no_video = set(no_video)

    def _settings(self, lang):
        return {"connect_sentence_dial": "best"}

    def mines(self, lang, what):
        return True

    def video(self, lang, job):
        return None if job["item_id"] in self.no_video else f"episode-{job['item_id']}.mkv"


def _best(tmp_path, lang, key, here, steps=None):
    """`runner._best` for one word of the episode `here` (item 1) -> (kept, moved)."""
    from app.connect import runner
    words = [{"word": key[0], "reading": key[1], "line_text": "", "other_new": 3}]
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        job = {"id": 9, "item_id": 1, "kind": "new", "store_id": "s-1"}
        return runner._best(steps or _Steps(), ledger, lang, job, words, here)


@pytest.fixture(autouse=True)
def _no_young(monkeypatch):
    monkeypatch.setattr(sentences, "young_weights", lambda language, read=None: {})


# --- the card and Swap read the lines they take -------------------------------------------------------------------- #

@pytest.mark.parametrize("lang, key, word, long_line", CASES)
def test_the_cards_pick_decodes_only_its_first_lines_file_and_the_mined_episodes(monkeypatch, tmp_path, lang, key,
                                                                                 word, long_line):
    # why: E-CONNECT's booking — the door asked the score for eight lines a word and the score decoded each one's
    # whole file for its text (138 files for 45 words), where the card reads the first and the mined episode's own
    w = World(monkeypatch, lang)
    episodes = [("ep01", [long_line])] + [(f"ep{n:02d}", [LINES[lang][0]]) for n in range(2, 12)]
    w.table(key, episodes, word)
    for n in range(1, 12):
        w.place(f"ep{n:02d}", n, ctx=0.5 - n / 100)          # ep02 the best remembered of the others
    reads = _counted(monkeypatch, w)
    kept, moved = _best(tmp_path, lang, key, w.path("ep01"))
    assert [k.get("from") for k in kept] == [2] and moved == [], "the better line elsewhere, its video there"
    assert sorted(set(reads)) == ["ep01", "ep02"], reads


@pytest.mark.parametrize("lang, key, word, long_line", CASES)
def test_swap_decodes_only_the_old_line_and_the_next_and_still_skips_a_line_outside_the_library(monkeypatch, lang, key,
                                                                                                word, long_line):
    # why: Swap takes the first line it can use: one asked, and more only when that one names no library item
    from app.connect import swap
    w = World(monkeypatch, lang)
    lines = LINES[lang]
    episodes = [(f"ep{n:02d}", [text]) for n, text in enumerate(lines, 1)]
    w.table(key, episodes, word)
    for n in range(1, len(lines) + 1):
        w.place(f"ep{n:02d}", n, ctx=0.5 - n / 10)
    reads = _counted(monkeypatch, w)
    assert swap.choose_line(lang, key[0], avoid=[lines[0]], reading=key[1]) == (2, lines[1])
    assert sorted(set(reads)) == ["ep01", "ep02"], reads    # the old card's line (to see it is), then the next
    # the next line is in a file the library doesn't hold (no item: no card can be swapped to it) -> the one after
    w.info.pop(os.path.normcase(os.path.abspath(w.path("ep02"))))
    sentences._DATES.clear()
    assert swap.choose_line(lang, key[0], avoid=[lines[0]], reading=key[1]) == (3, lines[2])


@pytest.mark.parametrize("lang, key, word, long_line", CASES)
def test_swap_reads_the_old_cards_line_once_where_it_repeats_across_files(monkeypatch, lang, key, word, long_line):
    # why: a line said the same in many files (a show's song, the zh resources' shared lines) was read from each file
    # to see it is the old card's line — 109 whole files decoded for one zh Swap. The table's fingerprint of a line's
    # text (CRC-32, kept where another line of the word says the same: what "the same sentence twice" already trusts)
    # tells the copies apart unread: the first copy is read and refused, the rest skipped, the answer the same
    from app import plan_rules
    from app.connect import swap
    from tests.test_sentence_score import L
    w = World(monkeypatch, lang)
    old, other = LINES[lang][0], LINES[lang][1]
    episodes = [(f"ep{n:02d}", [old]) for n in range(1, 9)] + [("ep09", [other])]
    fp = max(plan_rules.text_hash_of(old), 1)               # (the Generate's: repeated -> its CRC-32, never 0)
    tab = w.lib.table([key], episodes, lambda f, n, t: L(0, f, n, t, word, repeat=fp if t == old else 0)
                      if word in t else None, folder="HighPriority/show")
    for name, texts in episodes:
        w.tokens[w.path(name)] = [(t, []) for t in texts]
    monkeypatch.setattr(SS, "_table", lambda language: tab)
    for n in range(1, 10):
        w.place(f"ep{n:02d}", n, ctx=0.5 - n / 100)         # every copy of the old line ahead of the other line
    reads = _counted(monkeypatch, w)
    assert swap.choose_line(lang, key[0], avoid=[old], reading=key[1]) == (9, other)
    assert sorted(set(reads)) == ["ep01", "ep09"], reads     # the first copy (to see it is the old line), the next
    # every copy of the old line is still the old line: none is offered when no other line is left
    reads.clear()
    sentences._DATES.clear()
    w.info.pop(os.path.normcase(os.path.abspath(w.path("ep09"))))
    assert swap.choose_line(lang, key[0], avoid=[old], reading=key[1]) is None
    assert "ep02" not in reads, reads


@pytest.mark.parametrize("lang, key, word, long_line", CASES)
def test_a_book_outside_the_store_is_heard_as_a_book_inside_the_score_so_the_first_line_is_connects(monkeypatch,
                                                                                                    tmp_path, lang,
                                                                                                    key, word,
                                                                                                    long_line):
    # why: Connect weighs a file outside the store by its extension (a book's line silent); the score heard every
    # such file by its own clip, and Connect re-weighed the eight it was handed — with one line handed, the book's
    # line (first by its path on a tie) would have stood in for the episode's
    from app.connect import library
    w = World(monkeypatch, lang)
    w.table(key, [("book01", [LINES[lang][0]]), ("ep02", [LINES[lang][0]]), ("ep03", [long_line])], word)
    w.place("ep02", 2)
    w.place("ep03", 1)
    real = library.text_only
    monkeypatch.setattr(library, "text_only", lambda item: "book01" in str(item.get("rel_path")) or real(item))
    kept, moved = _best(tmp_path, lang, key, w.path("ep03"))
    assert [k.get("from") for k in kept] == [2] and moved == []
    got = {os.path.basename(c.file): c for c in sentences.choose(lang, [key], dial=sentences.BEST, young={})[key]}
    assert next(iter(got)) == "ep02.srt" and got["ep02.srt"].audio and not got["book01.srt"].audio
    assert got["book01.srt"].cost - got["ep02.srt"].cost == pytest.approx(SS.HEARD_SILENT)


def test_ensure_an_audio_example_still_finds_a_heard_line_it_can_cut_when_the_first_heard_one_cant_be(monkeypatch,
                                                                                                     tmp_path):
    # why: the score puts its first heard line first; when the cut can't make that one, Connect asks again until it
    # holds a heard line it can make (or the word has no more), never settling for a silent one it was handed first
    w = World(monkeypatch, settings={"ensure_audio_example": True})
    episodes = [("ep01", [LONG_JA])] + [(f"ep{n:02d}", [FESTIVAL]) for n in range(2, 12)]
    w.table(FEST, episodes, "文化祭")
    w.place("ep01", 1, ctx=0.0)
    for n in range(2, 12):                  # ep02-ep09 silent but better remembered; ep10 heard, its video gone; ep11
        heard = n >= 10
        w.place(f"ep{n:02d}", n, ctx=0.0 if heard else 1.0 - n / 100, hear=sentences.REAL if heard else sentences.SILENT)
    kept, moved = _best(tmp_path, "ja", FEST, w.path("ep01"), _Steps(no_video={10}))
    assert [k.get("from") for k in kept] == [11]


class _Decoded(list):
    """One file's sentences as the token store hands them: a fresh list each decode, so a test can see it let go."""


def _alive(monkeypatch, w):
    """The token store's read side, noting at each decode how many earlier decodes are still held -> (reads, peak)."""
    import weakref
    reads, refs, peak = [], [], [0]

    class Alive(Tokens):
        def file_tokens(self, path):
            peak[0] = max(peak[0], sum(1 for r in refs if r() is not None))
            reads.append(os.path.splitext(os.path.basename(path))[0])
            got = _Decoded(super().file_tokens(path))
            refs.append(weakref.ref(got))
            return got

    monkeypatch.setattr(SS, "_tokens", lambda language: Alive(w.tokens))
    return reads, peak


@pytest.mark.parametrize("young", [False, True])
@pytest.mark.parametrize("lang, key, word, long_line", CASES)
def test_a_file_s_tokens_are_let_go_once_its_texts_are_read(monkeypatch, lang, key, word, long_line, young):
    # why: the score kept every touched file's whole tokens for its call (for a line's text and its young words) —
    # the list's call touches nearly every file: +337 MB at 2k. A file's texts (and, with young words, each line's
    # youngest word) are all the walk reads: those are kept, the tokens let go at once; the answer the same
    w = World(monkeypatch, lang)
    lines = LINES[lang]
    young_word = {"ja": "看板", "zh": "牛肉面"}[lang]
    episodes = [(f"ep{n:02d}", [lines[n % 4]]) for n in range(1, 13)]
    w.table(key, episodes, word, words={lines[2]: [word, young_word]})
    for n in range(1, 13):
        w.place(f"ep{n:02d}", n, ctx=0.5 - n / 100)
    reads, peak = _alive(monkeypatch, w)
    got = sentences.choose(lang, [key], dial=sentences.BEST, young={young_word: 1.0} if young else {})[key]
    assert len(set(reads)) >= sentences.TOP, reads           # one call read many files
    assert peak[0] == 0, (peak[0], reads)                     # none of them held when the next is read
    # the answers the code before gave (ja: the young word's line, ep02's, among the leading four, lifted to the top;
    # zh: its young line is fifth, past the four whose young words are read)
    before = {("ja", False): [1, 4, 5, 2, 8, 9, 6, 12], ("ja", True): [2, 1, 4, 5, 8, 9, 6, 12],
              ("zh", False): [1, 4, 5, 8, 2, 9, 12, 6], ("zh", True): [1, 4, 5, 8, 2, 9, 12, 6]}
    assert [c.item_id for c in got] == before[(lang, young)]


@pytest.mark.parametrize("lang, key, word, long_line", CASES)
def test_a_malformed_entry_in_a_files_tokens_costs_only_its_own_line(monkeypatch, lang, key, word, long_line):
    # why: what the walk reads of a file is made whole at its first read; one entry the token store holds badly (no
    # text, no tokens, a lemma that is no string) must not blank the file's other lines — the walk read them line by
    # line before, and met a bad entry only on its own line
    w = World(monkeypatch, lang)
    lines = LINES[lang]
    w.table(key, [("ep01", [lines[0], "-", "-", "-"]), ("ep02", [lines[1]])], word)
    w.place("ep01", 1, ctx=0.5)
    w.place("ep02", 2, ctx=0.1)
    w.tokens[w.path("ep01")] = [(lines[0], [[word, "", word]]), (), ("-", None), ("-", [[["not", "a", "string"]]])]
    got = sentences.choose(lang, [key], dial=sentences.BEST, young={"看板": 1.0})[key]
    assert [c.item_id for c in got] == [1, 2] and got[0].text == lines[0]


# --- a young word's lines ------------------------------------------------------------------------------------------ #

def test_a_young_word_is_read_only_in_lines_it_can_lift_to_the_top(monkeypatch, tmp_path):
    # why: the young word lifts a line by at most YOUNG × its weight; a line whose cost is further than that behind the
    # best read so far can never be first, so its file is not decoded for it — while one close enough still is, and wins
    monkeypatch.setattr(sentences, "young_weights", lambda language, read=None: {"看板": 1.0})
    guitar = "文化祭の看板を見に行こう。"
    w = World(monkeypatch)
    w.table(FEST, [("ep01", [LONG_JA]), ("ep02", [FESTIVAL]), ("ep03", [guitar]), ("ep04", [PREPARE]),
                   ("ep05", [SIGN])], "文化祭", words={guitar: ["文化祭", "看板"]})
    w.place("ep01", 1, ctx=0.0)
    w.place("ep02", 2, ctx=1.0)             # far ahead: 0.9 of context, more than the young word's 0.3
    for n in (3, 4, 5):
        w.place(f"ep{n:02d}", n, ctx=0.0)
    reads = _counted(monkeypatch, w)
    kept, _moved = _best(tmp_path, "ja", FEST, w.path("ep01"))
    assert [k.get("from") for k in kept] == [2]
    assert sorted(set(reads)) == ["ep01", "ep02"], reads
    # close behind: the young line is read and lifted past the best one
    w.place("ep02", 2, ctx=0.2)
    sentences._DATES.clear()
    del reads[:]
    kept, _moved = _best(tmp_path, "ja", FEST, w.path("ep01"))
    assert [k.get("from") for k in kept] == [3]
    assert "ep03" in reads


# --- kept across picks --------------------------------------------------------------------------------------------- #

def test_the_words_marked_since_are_read_once_while_neither_file_changes(monkeypatch, tmp_path):
    # why: once KnownWord.json is newer than the table every pick parsed it again (`word_marks.left_out`)
    from app import path_utils, sentence_table
    from app.services import word_marks
    results = os.path.join(tmp_path, "results")
    os.makedirs(results)
    real = path_utils.get_user_file
    monkeypatch.setattr(path_utils, "get_user_file", lambda name, *a, **k: results if name == "results"
                        else real(name, *a, **k))
    table = os.path.join(results, sentence_table.TABLE_FILE)
    with open(table, "wb") as f:
        f.write(b"\0")
    os.utime(table, ns=(1_000_000_000, 1_000_000_000))
    known = os.path.join(tmp_path, "KnownWord.json")
    with open(known, "w", encoding="utf-8") as f:
        f.write("[]")
    from app import anki_sync
    monkeypatch.setattr(anki_sync, "_known_path", lambda language: known)
    parsed = []
    monkeypatch.setattr(word_marks, "marks", lambda language: parsed.append(language) or {"文化祭": "known"})
    for _pick in range(3):
        assert sentences.known_since("ja") == {("文化祭", "")}
    assert parsed == ["ja"]
    with open(known, "w", encoding="utf-8") as f:
        f.write('[{"dictForm": "文化祭"}]')         # a mark since: read again
    assert sentences.known_since("ja") == {("文化祭", "")} and parsed == ["ja", "ja"]
    assert sentences.known_since("zh") == {("文化祭", "")} and parsed == ["ja", "ja", "zh"]


def test_the_rows_arrays_are_built_once_across_picks_at_one_moment_and_again_for_another(monkeypatch):
    # why: the rows' arrays (the list's order, the words known since, the young words) were built at every pick
    w = World(monkeypatch)
    tab = w.table(FEST, [(f"ep{n:02d}", [text]) for n, text in enumerate(LINES["ja"], 1)], "文化祭")
    for n in range(1, 6):
        w.place(f"ep{n:02d}", n)
    built = []
    real = SS._row_arrays
    monkeypatch.setattr(SS, "_row_arrays", lambda *a: built.append(1) or real(*a))
    first = [sentences.choose("ja", [FEST], dial=sentences.BEST, young={})[FEST][0].text for _pick in range(3)]
    assert first == [FESTIVAL] * 3 and len(built) == 1
    lifted = sentences.choose("ja", [FEST], dial=sentences.BEST, young={"手伝う": 1.0})[FEST]
    assert len(built) == 2 and lifted[0].text == FESTIVAL           # another moment: built again, never the old one's
    assert tab.head["keys"]


@pytest.mark.parametrize("lang, key, word, here_line", [(c[0], c[1], c[2], c[3]) for c in CASES])
def test_a_picks_later_asks_take_and_cost_no_line_again(monkeypatch, lang, key, word, here_line):
    # why: a pick asks the score up to three times — its first line, more when that one can't be cut, the mined
    # episode's own — and each ask took the word's every line from the table and costed them again: the same rows at
    # the same moment (a line's cost is its own row's alone), so one take and one cost a pick, the answer the same
    w = World(monkeypatch, lang)
    w.table(key, [("ep01", [here_line])] + [(f"ep{n:02d}", [t]) for n, t in enumerate(LINES[lang][:4], 2)], word)
    for n in range(1, 6):
        w.place(f"ep{n:02d}", n)
    first = sentences.choose(lang, [key], dial=sentences.BEST, young={}, top=1)[key][0]
    assert first.item_id != 1
    real_choose = SS.choose
    monkeypatch.setattr(SS, "choose", lambda *a, memo=None, **k: real_choose(*a, **k))      # each ask on its own
    alone = sentences.choose(lang, [key], here=w.path("ep01"), dial=sentences.BEST, young={},
                             reach=lambda item: item != first.item_id, top=1)[key]
    monkeypatch.setattr(SS, "choose", real_choose)
    calls = []
    for name in ("_take", "cost"):
        real = getattr(SS, name)
        monkeypatch.setattr(SS, name, lambda *a, _n=name, _f=real, **k: calls.append(_n) or _f(*a, **k))
    got = sentences.choose(lang, [key], here=w.path("ep01"), dial=sentences.BEST, young={},
                           reach=lambda item: item != first.item_id, top=1)[key]
    assert got == alone and [c.here for c in got] == [False, True] and got[0].item_id != first.item_id
    assert sorted(calls) == ["_take", "cost"], calls


@pytest.mark.parametrize("lang, key, word", [(c[0], c[1], c[2]) for c in CASES])
def test_a_picks_files_are_placed_once_while_the_librarys_dates_are_kept(monkeypatch, lang, key, word):
    # why: each pick placed every file of its words' lines again (its path, how it is heard, its context: a 20,000
    # file library's commonest words are in most of its files) — kept now while the dates Connect keeps are the same
    w = World(monkeypatch, lang)
    w.table(key, [(f"ep{n:02d}", [t]) for n, t in enumerate(LINES[lang], 1)], word)
    for n in (1, 2, 3):
        w.place(f"ep{n:02d}", n)                    # ep04 and ep05: outside the store, heard by their extension
    stamp = [(1, 1)]
    monkeypatch.setattr(sentences, "_store_stamp", lambda language: stamp[0])
    placed = []
    real = SS._unnamed
    monkeypatch.setattr(SS, "_unnamed", lambda *a: placed.append(1) or real(*a))
    picks = [sentences.choose(lang, [key], dial=sentences.BEST, young={}, top=1)[key] for _pick in range(3)]
    assert picks[0] == picks[1] == picks[2] and picks[0]
    assert len(placed) == 2, placed                 # the first pick's two, none after
    stamp[0] = (2, 2)                               # the store written: its dates read again, every file placed again
    assert sentences.choose(lang, [key], dial=sentences.BEST, young={}, top=1)[key] == picks[0]
    assert len(placed) == 4


@pytest.mark.parametrize("lang, key, word", [(c[0], c[1], c[2]) for c in CASES])
def test_a_library_with_a_lined_up_book_keeps_its_files_placed_while_the_books_line_up_is_the_same(monkeypatch, lang,
                                                                                                  key, word):
    # why: a paired book's hearing is asked again at every pick (its line-up writes nothing to the store), and the
    # dates came back as new dicts each time even when every book's answer was the same: every file placed again
    from app.connect import lineup
    w = World(monkeypatch, lang)
    w.table(key, [(f"ep{n:02d}", [t]) for n, t in enumerate(LINES[lang], 1)], word)
    for n in (1, 2):
        w.place(f"ep{n:02d}", n)
    book = os.path.normcase(os.path.abspath(w.path("ep03")))
    w.info[book] = (3, 0.0, sentences.REAL, True, False, ("book-3", {"state": "done"}))
    answer = [lineup.Reach(frozenset(), frozenset(), ())]
    monkeypatch.setattr(lineup, "reach", lambda record: answer[0])
    monkeypatch.setattr(sentences, "_store_stamp", lambda language: (1, 1))
    placed = []
    real = SS._unnamed
    monkeypatch.setattr(SS, "_unnamed", lambda *a: placed.append(1) or real(*a))
    picks = [sentences.choose(lang, [key], dial=sentences.BEST, young={}, top=1)[key] for _pick in range(3)]
    assert picks[0] == picks[1] == picks[2] and picks[0]
    assert len(placed) == 2, placed                 # ep04 and ep05 at the first pick, none after
    answer[0] = lineup.Reach(frozenset(), frozenset(), ())      # the line-up done again: another answer
    assert sentences.choose(lang, [key], dial=sentences.BEST, young={}, top=1)[key] == picks[0]
    assert len(placed) == 4


# --- the walk's order ---------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("lang, key, word, here_line", [(c[0], c[1], c[2], c[3]) for c in CASES])
def test_the_mined_episodes_own_ask_ranks_only_that_episodes_lines(monkeypatch, lang, key, word, here_line):
    # why: the episode's own line was found by ranking the word's every line in the library and walking past the
    # other files' ones (a common word: tens of thousands) — now only the episode's lines are ranked; the same line
    w = World(monkeypatch, lang)
    others = [(f"ep{n:02d}", [t]) for n, t in enumerate(LINES[lang][:4] * 5, 2)]
    w.table(key, [("ep01", [here_line])] + others, word)
    for n in range(1, len(others) + 2):
        w.place(f"ep{n:02d}", n)
    ranked = []
    real = SS._ranked
    monkeypatch.setattr(SS, "_ranked", lambda *a, **k: (lambda got: ranked.append(len(got)) or iter(got))(
        list(real(*a, **k))))
    got = sentences.choose(lang, [key], here=w.path("ep01"), dial=sentences.BEST, young={}, top=1)[key]
    assert [c.text for c in got if c.here] == [here_line] and not got[0].here
    assert ranked == [len(others) + 1, 1], ranked     # the first ask: every line; the episode's own: its one


def test_the_lines_are_put_in_order_as_the_walk_takes_them_and_the_order_is_the_whole_sorts():
    # why: a word's every line was sorted for the one or two a pick reads; the first few (with every line tied with
    # the last of them) are put in order first, the rest only when the walk goes past them — the same order
    import numpy as np
    rng = np.random.default_rng(7)
    n = 300
    total = np.round(rng.integers(0, 12, n) / 4.0 + rng.integers(0, 3, n) * 1e-12, 12)   # ties within 9 decimals
    total[rng.integers(0, n, 20)] = np.inf
    number, src = rng.integers(0, 50, n), rng.integers(0, 40, n)
    tie = rng.permutation(40)
    whole = sorted((i for i in range(10, 290) if np.isfinite(total[i])),
                   key=lambda i: (round(float(total[i]), SS._RANK_DIGITS), int(tie[src[i]]), int(number[i])))
    for first in (1, 4, 64, 1000):
        assert list(SS._ranked(total, number, tie, src, 10, 290, first=first)) == whole
    within = np.array([3, 17, 22], np.int64)
    assert list(SS._ranked(total, number, tie, src, 10, 290, within=within, first=4)) == [
        i for i in whole if src[i] in (3, 17, 22)]
    lazy = SS._ranked(total, number, tie, src, 10, 290, first=4)
    assert [next(lazy) for _ in range(3)] == whole[:3]


# --- the cap ------------------------------------------------------------------------------------------------------- #

def _long_first(tmp_path, lang, texts, long_ones):
    """A subtitle of `texts`, each 0.9 s long but those of `long_ones`, 9.5 s (past the 8 s cap)."""
    path = os.path.join(tmp_path, f"cap.{lang}.srt")
    at = 1.0
    with open(path, "w", encoding="utf-8", newline="\r\n") as f:
        for n, text in enumerate(texts, 1):
            end = at + (9.5 if n - 1 in long_ones else 0.9)
            f.write(f"{n}\n{_ts(at)} --> {_ts(end)}\n{text}\n\n")
            at = end + 1.0
    return path


def _ts(s):
    ms = int(round(s * 1000))
    return f"00:{ms // 60000:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


@pytest.mark.parametrize("lang, word, texts", [("ja", "文化祭", [FESTIVAL, PREPARE, SIGN]),
                                               ("zh", "夜市", [NIGHT, SHOP_ZH, TOMORROW_ZH])])
def test_the_cut_takes_the_scores_best_line_that_fits_the_cap_else_its_first(tmp_path, lang, word, texts):
    # why: SPEC §§ 11-12 — a clip over 8 s chosen first is refused and the score's next is taken; only when none of
    # the score's lines fits is its first cut (past the cap), never a line the score didn't choose
    analyzer.SANITIZE_JA = lang == "ja"
    first, second, other = texts

    def chosen(long_ones):
        path = _long_first(tmp_path, lang, texts, long_ones)
        read = cues.read(path, lang)
        got = pick.pick(read, cues.tokens(read, lang), lang, lambda k: k[0] != word, mode="unknown",
                        ranked=lambda keys: {k: [first, second] for k in keys if k[0] == word})
        return [x["line_text"] for x in got["words"] if x["word"] == word]
    assert chosen({0}) == [second]                  # the score's first is past the cap: its next, which fits
    assert chosen(set()) == [first]                 # both fit: the score's first
    assert chosen({0, 1}) == [first]                # none of the score's fits: its first, not the line it didn't name


@pytest.mark.parametrize("lang, key, word", [(c[0], c[1], c[2]) for c in CASES])
def test_swap_asks_for_more_when_the_scores_one_line_is_in_a_file_outside_the_library(monkeypatch, lang, key, word):
    # why: Swap asks the score for one line first; one in a file outside the library (no item) can't be its card's,
    # so it asks again for the picker's eight and takes the first it can use
    from app.connect import swap
    w = World(monkeypatch, lang)
    w.table(key, [("ep01", [LINES[lang][0]]), ("ep02", [LINES[lang][4]])], word)
    w.place("ep02", 2)                              # ep01: there on disk, outside the store
    os.makedirs(os.path.dirname(w.path("ep01")), exist_ok=True)
    if not os.path.isfile(w.path("ep01")):
        with open(w.path("ep01"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(f"1\n00:00:01,000 --> 00:00:02,000\n{LINES[lang][0]}\n")
    first = sentences.choose(lang, [key], dial=sentences.BEST, young={}, top=1)[key]
    assert [c.item_id for c in first] == [None]     # the score's first line: outside the library
    assert swap._chosen(lang, {key}, set(), None, set(), None) == (2, LINES[lang][4])


# --- the table's file check: one spelling of a file's path ------------------------------------------------------- #

def _spelled_apart(root):
    """The data folder as another process may spell it: forward slashes and the drive's other case on Windows (a
    bench's `h:/…` beside the window's backslashes), a `.` part elsewhere — the same folder."""
    if os.sep == "\\":
        spelled = root.replace("\\", "/")
        return spelled[0].swapcase() + spelled[1:] if spelled[1:2] == ":" else spelled
    head, tail = os.path.split(root)
    return os.path.join(head, ".", tail)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_data_folder_the_generate_spelled_another_way_still_finds_every_file_and_the_same_lines(language,
                                                                                                    monkeypatch):
    # why: the table signs each file's path; a Generate that spelled the data folder `H:/…` and a reader that spells
    # it `H:\…` (a bench, a tool) refused every line of every file — no sentence from a table that is right. The file
    # is the same file: the word card and the score find it, and give the same lines, whichever way either spells it
    from app import plan_engine, sentence_table, token_index
    from app.path_utils import get_data_path
    from tests import services_helpers as h
    from tests.test_sentence_table import _generate_at, _seed
    monkeypatch.delenv("SURASURA_SENTENCE_TABLE", raising=False)
    results = _seed(language)
    root = h.root()
    store = os.path.join(root, "index", f"token_store_{language}.db")       # the Generate's (a child process)
    monkeypatch.setattr(SS, "_tokens", lambda lang: token_index.open_reader(lang, store))
    monkeypatch.setenv("SURASURA_TEST_ROOT", _spelled_apart(root))
    generated = get_data_path(language)                     # the data folder as the Generate spells it
    _generate_at(language, 1)
    monkeypatch.setenv("SURASURA_TEST_ROOT", root)
    data_dir = get_data_path(language)                      # and as this reader does
    assert generated != data_dir and os.path.samefile(generated, data_dir)
    table = sentence_table.open_table(os.path.join(results, sentence_table.TABLE_FILE), language=language)
    plan = plan_engine.load(os.path.join(results, analyzer.PLAN_FILE))
    files = range(len(plan.files))
    assert plan.files and all(table.as_read(f, data_dir) for f in files)       # the word card's check (E-HOVER)
    assert all(table.as_read(f, generated) for f in files)
    keys = sorted(table.rows())
    lines = {}
    for spelled in (data_dir, generated):
        got = SS.choose(language, keys, n=3, moment=SS.Moment(root=spelled), length=(10, 50), table=table)
        # (each line names its file as the asker spells its folder: the same file)
        lines[spelled] = {k: [x._replace(file=os.path.normcase(os.path.abspath(x.file))) for x in v]
                          for k, v in got.items()}
    assert sum(1 for got in lines[data_dir].values() if got) >= len(keys) // 2, "the rows' lines, read here"
    assert lines[data_dir] == lines[generated]
