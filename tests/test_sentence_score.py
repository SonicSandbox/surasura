"""The sentence score and its reader (app/sentence_score.py; SPEC § 4, § 5): every term alone on real sentences, each
rate by name, ties, the reader's refusals (never, the same sentence twice, a changed file, the wall), the moment's
young words, the words known since the Generate, the unwatched factor, Length handed in, ja + zh.

The table's columns are built here in the frozen shape of SPEC § 3.3 (one row's lines together; the co-words as
formulas over list rows); the round trip over a real `app/sentence_table.py` table is E-TABLE's branch's.
The sentences are lines of tests/Test Resources (placed_episode.srt, books/toshisyun_book.txt, night_market.srt,
chinese_text_1.txt); a line's characters are counted as the app counts them, the full stop too.
"""
import os

import numpy as np
import pytest

from app import plan_rules
from app import sentence_score as SS

# --- real lines --------------------------------------------------------------------------------------------------- #
FESTIVAL = "文化祭まで、あと三日しかないよ。"                 # 16 characters
PREPARE = "文化祭の準備、手伝ってくれない？"                   # 16
SIGN = "文化祭の看板は私が描くね。"                           # 13
COLOUR = "看板の色はみんなで決めよう。"                       # 14
NOTICED = "ごめん、ぼーっとしてて気がつかなかった。"           # 20
DARK = "気がついたら、もう外は暗かった。"                     # 16
MAYBE = "もしかしたら、今日は遅くなるかもしれない。"           # 21
SHORT_JA = "やっと気がついた。"                               # 9
GATE = "唐の都洛陽の西の門の下に、ぼんやり空を仰いでゐる、一人の若者がありました。"   # 37: 若者 late
STARE = "しかし杜子春は相変らず、門の壁に身を凭せて、ぼんやり空ばかり眺めてゐました。"  # 38: 杜子春 early
RICH = "杜子春は一日の内に、洛陽の都でも唯一人といふ大金持になりました。"     # 32: 杜子春 first
SEAT = "すると鉄冠子は杜子春を峨眉山の絶壁の下に坐らせて、かう言ひました。"     # 33

NIGHT = "今天我们要去台北的夜市吃东西。"                      # 15
NOODLE = "我们先点一碗牛肉面，"                                # 10
TEA = "再来一杯珍珠奶茶。"                                    # 9
PRICE = "味道真的很好，我觉得这个价格很合理。"                # 18
SUN_LATE = "她还提到，展柜里会有一份1920年代的《臺湾民报》复印件，上面刊登了当时读者对孙中山去世的悼念文章。"
SUN_EARLY = (
    "据史料记载，孙中山十三岁时随母亲去了檀香山，在那里第一次接触到西方的学校教育。",
    "1912年1月1日，孙中山在南京宣誓就任中华民国临时大总统，这里也是他办公的地方。",
    "一位退休的历史老师对本报说，孙中山的思想很复杂，参观者不应该只记住几句口号，而要多读原文。",
    "这四个字出自《礼记》，孙中山一生中写过许多次，送给不同的朋友和团体。",
)
LENGTH = (14, 25)


def test_the_real_lines_are_counted_as_the_comments_say():
    # (the numbers every test below leans on)
    assert [len(s) for s in (FESTIVAL, SIGN, COLOUR, NOTICED, MAYBE, SHORT_JA, GATE, STARE, RICH)] == \
        [16, 13, 14, 20, 21, 9, 37, 38, 32]
    assert [len(s) for s in (NIGHT, NOODLE, TEA, PRICE)] == [15, 10, 9, 18]
    assert GATE.find("若者") / len(GATE) >= 2 / 3 and STARE.find("杜子春") / len(STARE) < 2 / 3
    assert SUN_LATE.find("孙中山") / len(SUN_LATE) >= 2 / 3
    assert all(len(s) > 25 and s.find("孙中山") / len(s) < 2 / 3 for s in SUN_EARLY)


# --- the table, in SPEC § 3.3's shape ------------------------------------------------------------------------------ #

def L(row, src, number, text, word, besides=2, cow=(), crowd=(), flags=0, repeat=0):
    """One candidate line of a list row, as the table keeps it (its text only for the test's own `shown`)."""
    start = text.find(word)
    assert start >= 0, (word, text)
    return {"row": row, "src": src, "number": number, "chars": len(text), "flags": flags, "besides": besides,
            "start": min(start, 255), "hash": repeat, "cow": list(cow), "crowd": list(crowd), "text": text}


class Table:
    """A table in memory with `sentence_table.Table`'s reading side: `keys` every list row (the Generate's list order
    unless `places` says another), `sources` [(rel, kind, digest)], `lines` (`L`), `cowords` [(its own row or -1,
    clauses of rows)]. `blocked` the rows whose blocks were read."""

    def __init__(self, keys, sources, lines, cowords=(), places=True):
        keys = [list(k) for k in keys]
        self.head = {"keys": keys}
        if places is True:
            self.head["places"] = list(range(len(keys)))
        elif places is not None:
            self.head["places"] = list(places)
        self._sources = [list(s) for s in sources]
        self.lines = sorted(lines, key=lambda l: (l["row"], l["src"], l["number"]))
        self.cowords = list(cowords)
        self.blocked = []

    def sources(self):
        return self._sources

    def places(self):
        return self.head["places"]

    def rows(self):
        keys = self.head["keys"]
        return {tuple(keys[k]): k for k in sorted({l["row"] for l in self.lines})}

    def block(self, row):
        self.blocked.append(row)
        lines = [l for l in self.lines if l["row"] == row]
        if not lines:
            return None
        cols = {theirs: np.asarray([l[mine] for l in lines], dtype)
                for mine, theirs, dtype in (("src", "src", "<i4"), ("number", "number", "<i4"),
                                            ("chars", "chars", "<u2"), ("flags", "marks", "u1"),
                                            ("hash", "fp", "<u4"), ("besides", "besides", "u1"),
                                            ("start", "starts", "u1"))}
        cols["ncow"] = np.asarray([len(l["cow"]) for l in lines], "<u2")
        cols["nphr"] = np.asarray([len(l["crowd"]) for l in lines], "<u2")
        return (cols, np.asarray([c for l in lines for c in l["cow"]], "<i4"),
                np.asarray([c for l in lines for c in l["crowd"]], "<i4"))

    def take(self, rows):
        """The cost's columns, as the reader takes them."""
        return SS._take(self, rows)

    def formulas(self):
        own = np.asarray([c[0] for c in self.cowords], np.int32)
        ncl = np.asarray([len(c[1]) for c in self.cowords], np.int32)
        cl_len = np.asarray([len(cl) for c in self.cowords for cl in c[1]], np.int32)
        cl_rows = np.asarray([r for c in self.cowords for cl in c[1] for r in cl], np.int32)
        return own, ncl, cl_len, cl_rows

    def shown(self):
        return {(self._sources[l["src"]][0], l["number"]): l["text"] for l in self.lines}


def costs(tab, length=LENGTH, moment=None, order=None):
    """{(row, src, number): cost} of every line of `tab` at `moment`."""
    arrays, _files = SS._moment_arrays(tab, moment or SS.Moment(), order, os.getcwd())
    cols = tab.take(sorted(tab.rows().values()))
    total = SS.cost(cols, arrays, *length)[0]
    return {(int(r), int(s), int(n)): float(c) for r, s, n, c in zip(cols["row"], cols["src"], cols["number"], total)}


def one(tab, **kw):
    """The cost of a table's only line."""
    (got,) = costs(tab, **kw).values()
    return got


def solo(line, keys=(("文化祭", "ぶんかさい"),), sources=(("show/ep01.srt", "subtitle", None),), cowords=()):
    return Table(keys, sources, [line], cowords)


# --- the rates: one block, one door --------------------------------------------------------------------------------- #

def test_every_number_of_the_spec_is_a_named_rate_with_its_spec_value():
    r = SS.rates()
    assert (r.new_word, r.new_phrase, r.outside, r.few_words, r.few_words_cost) == (1.0, 1.0, 0.03, 2, 0.5)
    assert (r.late_from, r.late_cost, r.late_habit, r.late_habit_lines) == (2 / 3, 0.3, 0.5, 5)
    assert (r.context, r.unwatched) == (0.9, 0.8)
    assert (r.heard_real, r.heard_ai, r.heard_silent) == (0.0, 0.15, 0.4)
    assert (r.young, r.young_lines) == (0.3, 4)


def test_the_young_lines_reach_is_connects_own_until_its_gate_measures_it():
    # SPEC § 9 C: today's four leading lines stay; one number in two places must not drift apart
    from app.connect import sentences
    assert SS.YOUNG_LINES == sentences.YOUNG_LINES


def test_a_rate_changed_reaches_the_next_cost_with_no_new_table(monkeypatch):
    # The same columns, one rate changed: the cost follows at once (decision 18: a weight tuned rebuilds nothing)
    tab = solo(L(0, 0, 3, SIGN, "文化祭"))                       # 13 characters: one under the zone
    assert one(tab) == pytest.approx(0.03)
    monkeypatch.setattr(SS, "OUTSIDE", 0.1)
    assert SS.rates().outside == 0.1
    assert one(tab) == pytest.approx(0.1)


def test_the_score_module_imports_nothing_heavy_at_its_top():
    # Pure in plan_rules' sense: numpy inside the functions, no pandas / Qt / Tk / settings / stores at import
    import ast
    with open(SS.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    top = {alias.name.split(".")[0] for node in tree.body if isinstance(node, ast.Import) for alias in node.names}
    top |= {node.module.split(".")[0] for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert top <= {"os", "math", "collections"}, top


# --- every term alone -------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("text, word, expected", [
    (COLOUR, "看板", 0.0),          # 14: the zone's bottom, inside
    (SIGN, "看板", 0.03),           # 13: one character under
    (SHORT_JA, "気", 0.15),         # 9: five under
    (MAYBE, "今日", 0.0),           # 21: inside
])
def test_characters_outside_the_zone_cost_a_little_each(text, word, expected):
    assert one(solo(L(0, 0, 1, text, word))) == pytest.approx(expected)


def test_the_zone_is_the_learners_length_handed_in_not_a_number_of_the_score():
    # Length as 14–25 and as a learner's own 10–50: the same line, the zone moves with it
    gate = solo(L(0, 0, 1, GATE, "門"))                          # 37 characters, the word early (門 at 8)
    assert one(gate, length=(14, 25)) == pytest.approx(0.03 * 12)
    assert one(gate, length=(10, 50)) == pytest.approx(0.0)
    assert one(gate, length=(37, 37)) == pytest.approx(0.0)
    assert one(gate, length=(38, 60)) == pytest.approx(0.03)
    assert one(gate, length=(14, 36)) == pytest.approx(0.03)


@pytest.mark.parametrize("besides, expected", [(0, 0.5), (1, 0.5), (2, 0.0), (5, 0.0)])
def test_a_line_saying_fewer_than_two_other_words_costs_half_a_new_word(besides, expected):
    # デービッドだ。-like lines: the word and nothing about it (decision 9b); the count is the table's, per line
    assert one(solo(L(0, 0, 1, FESTIVAL, "文化祭", besides=besides))) == pytest.approx(expected)


def test_the_late_word_costs_a_third_in_a_long_line_and_nothing_early_or_in_the_zone():
    keys = (("若者", "わかもの"), ("杜子春", "とししゅん"))
    late = Table(keys, [("book/toshisyun.txt", "book", None)], [L(0, 0, 0, GATE, "若者")])
    early = Table(keys, [("book/toshisyun.txt", "book", None)], [L(1, 0, 4, STARE, "杜子春")])
    assert one(late) == pytest.approx(0.03 * 12 + 0.3)
    assert one(early) == pytest.approx(0.03 * 13)
    # In the zone (Length set long by the learner) the late word costs nothing: its cost starts at the zone's top
    assert one(late, length=(14, 40)) == pytest.approx(0.0)


def test_the_late_word_starts_exactly_at_two_thirds():
    # SEAT is 33 characters: the causative せ(る) starting at 22 (exactly 2/3) is late; 坐る at 20 (0.61) is not
    assert len(SEAT) == 33 and SEAT.find("せ") == 22 and SEAT.find("坐") == 20
    at_22 = solo(L(0, 0, 0, SEAT, "せ"), keys=(("せる", "せる"),))
    at_20 = solo(L(0, 0, 0, SEAT, "坐"), keys=(("坐る", "すわる"),))
    assert one(at_22) - one(at_20) == pytest.approx(0.3)
    assert one(at_20) == pytest.approx(0.03 * 8)
    zone_top = solo(L(0, 0, 0, NIGHT + NOODLE, "牛肉面"), keys=(("牛肉面", "niúròumiàn"),))
    assert len(NIGHT + NOODLE) == 25                             # not longer than the zone: never late
    assert one(zone_top) == pytest.approx(0.0)


def _sun(late_files, early=SUN_EARLY):
    lines = [L(0, s, 7, SUN_LATE, "孙中山", repeat=11) for s in range(late_files)]
    lines += [L(0, late_files + i, 2, text, "孙中山") for i, text in enumerate(early)]
    sources = [(f"docs/news{s:02d}.txt", "text", None) for s in range(len(lines))]
    return Table([("孙中山", "sūn zhōngshān")], sources, lines)


def test_a_word_that_lives_at_the_end_of_its_long_lines_is_not_charged_for_it():
    # 5 late of 9 long lines (over half): where this word sits, not a bother (かもしれない, 違いない…)
    got = costs(_sun(5))
    late = [c for (r, s, n), c in got.items() if n == 7]
    assert late == pytest.approx([0.03 * (len(SUN_LATE) - 25)] * 5)


def test_a_word_late_in_exactly_half_of_its_long_lines_is_charged():
    # "more than half": 4 of 8 is not more
    got = costs(_sun(4))
    late = [c for (r, s, n), c in got.items() if n == 7]
    assert late == pytest.approx([0.03 * (len(SUN_LATE) - 25) + 0.3] * 4)


def test_a_word_with_fewer_than_five_long_lines_is_charged_like_any_other():
    # 4 long lines, every one late: too few to judge where it lives
    got = costs(_sun(4, early=()))
    assert list(got.values()) == pytest.approx([0.03 * (len(SUN_LATE) - 25) + 0.3] * 4)
    # ...and five, every one late: judged, and free
    got = costs(_sun(5, early=()))
    assert list(got.values()) == pytest.approx([0.03 * (len(SUN_LATE) - 25)] * 5)


def test_where_a_word_lives_follows_the_length_of_the_moment():
    # At a long Length the early lines (38–45 characters) are no longer "long": 5 late of 5 long -> free
    tab = _sun(5)
    high = max(len(s) for s in SUN_EARLY)
    assert high < len(SUN_LATE)
    late = [c for (r, s, n), c in costs(tab, length=(14, high)).items() if n == 7]
    assert late == pytest.approx([0.03 * (len(SUN_LATE) - high)] * 5)


def test_a_line_over_never_longer_than_is_never_a_candidate():
    # the table's own mark (sung lines carry none: Connect's cut refuses them)
    from app import sentence_table
    assert SS.OVER_WALL == sentence_table.OVER
    tab = Table([("文化祭", "ぶんかさい")], [("show/ep01.srt", "subtitle", None)],
                [L(0, 0, 0, FESTIVAL, "文化祭", flags=SS.OVER_WALL), L(0, 0, 2, SIGN, "文化祭")])
    got = costs(tab)
    assert got[(0, 0, 0)] == float("inf")
    assert got[(0, 0, 2)] == pytest.approx(0.03)


# --- other new words and set phrases, the list's way ------------------------------------------------------------------- #

KEYS = (("文化祭", "ぶんかさい"), ("準備", "じゅんび"), ("手伝う", "てつだう"), ("看板", "かんばん"), ("描く", "かく"))
COWORDS = ((0, ((0,),)), (1, ((1,),)), (2, ((2,),)), (3, ((3,),)), (4, ((4,),)),
           (-1, ((1, 4),)))                                       # a compound known once 準備 and 描く are taught


# each row's line, as the word is written in it: three rows meet in PREPARE (16), 看板 in COLOUR (14), 描く in SIGN (13)
_MET = {0: (PREPARE, "文化祭"), 1: (PREPARE, "準備"), 2: (PREPARE, "手伝"), 3: (COLOUR, "看板"), 4: (SIGN, "描")}


def _prepare(row, cow, crowd=()):
    text, surface = _MET[row]
    return Table(KEYS, [("show/ep01.srt", "subtitle", None)], [L(row, 0, 3, text, surface, cow=cow, crowd=crowd)],
                 COWORDS)


def test_another_new_word_costs_one_and_a_word_taught_above_costs_nothing():
    # 準備 (row 1) in 手伝う's sentence (row 2): taught above, known when 手伝う's card comes
    assert one(_prepare(2, cow=(2, 1))) == pytest.approx(0.0)
    # 手伝う in 準備's sentence: below it on the list, still new
    assert one(_prepare(1, cow=(1, 2))) == pytest.approx(1.0)
    # the word itself is never "another" word
    assert one(_prepare(1, cow=(1,))) == pytest.approx(0.0)


def test_a_coword_known_only_when_every_row_of_its_clause_is_taught():
    # the compound needs 準備 (1) and 描く (4): in 看板's sentence (3) only 準備 is above -> new
    assert one(_prepare(3, cow=(3, 5))) == pytest.approx(1.0)
    # after a move that puts 描く above 看板 it is known: no Generate (the formula is the table's)
    order = {("文化祭", "ぶんかさい"): 0, ("準備", "じゅんび"): 1, ("描く", "かく"): 2, ("看板", "かんばん"): 3,
             ("手伝う", "てつだう"): 4}
    assert one(_prepare(3, cow=(3, 5)), order=order) == pytest.approx(0.0)


def test_a_word_known_since_the_generate_no_longer_counts_as_new_in_a_sentence():
    # SPEC § 7 row 8: the known-words sync marks 手伝う known; 準備's sentence holding it is clean at once
    known = SS.Moment(known={("手伝う", "てつだう")})
    assert one(_prepare(1, cow=(1, 2))) == pytest.approx(1.0)
    assert one(_prepare(1, cow=(1, 2)), moment=known) == pytest.approx(0.0)
    # a key with no reading: every row of the lemma
    assert one(_prepare(1, cow=(1, 2)), moment=SS.Moment(known={("手伝う", "")})) == pytest.approx(0.0)


def test_a_new_set_phrase_costs_one_until_it_is_taught_above():
    # 看板 (3) as a phrase row in 準備's (1) sentence: below, new; in 描く's (4) sentence: above, taught
    assert one(_prepare(1, cow=(1,), crowd=(3,))) == pytest.approx(1.0)
    assert one(_prepare(4, cow=(4,), crowd=(3,))) == pytest.approx(0.03)      # (SIGN: 13 characters)
    assert one(_prepare(3, cow=(3,), crowd=(3,))) == pytest.approx(0.0)       # its own phrase


def test_the_count_of_new_words_is_the_lists_own_at_the_generates_order():
    # The same rule as the walk's (plan_rules.ContextPicker), evaluated at once over the table: one count, two readers
    lines, sentences = [], []
    plan = [(1, (1, 2)), (2, (2, 1, 0)), (3, (3, 5, 4)), (4, (4, 5)), (0, (0, 3, 4, 2))]
    for s, (row, cow) in enumerate(plan):
        text = (PREPARE, NOTICED, COLOUR, SIGN, FESTIVAL)[s]
        lines.append(L(row, 0, s, text, text[:1], cow=cow))
        sentences.append((text, None, 0, 0, 0, list(cow), [], s, s + 1, len(text)))
    tab = Table(KEYS, [("show/ep01.srt", "subtitle", None)], lines, COWORDS)
    ours = costs(tab)
    picker = plan_rules.ContextPicker(sentences, COWORDS, 5, lambda src: (plan_rules.NOT_FINISHED, 0),
                                      lambda src: 0)
    theirs = {}
    for row in range(len(KEYS)):
        for s, (r, _cow) in enumerate(plan):
            if r == row:
                theirs[(row, 0, s)] = picker._weigh(row, row, s)[0]
        picker.learn(row, False, row)
    zone = {(r, 0, s): 0.03 * max(0, 14 - len(sentences[s][0])) for (r, _z, s) in theirs}
    assert {k: round(v - zone[k], 6) for k, v in ours.items()} == {k: float(v) for k, v in theirs.items()}


# --- the moment: context, the unwatched factor, how it is heard, young words ------------------------------------------ #

def _seen(tab, root, **by_rel):
    return {os.path.normcase(os.path.abspath(os.path.join(root, rel))): seen for rel, seen in by_rel.items()}


def test_remembered_context_takes_point_nine_of_the_files_context():
    tab = solo(L(0, 0, 1, FESTIVAL, "文化祭"))
    files = _seen(tab, os.getcwd(), **{"show/ep01.srt": SS.Seen(7, 0.5)})
    assert one(tab, moment=SS.Moment(files=files)) == pytest.approx(-0.45)


def test_an_unwatched_episode_of_a_started_show_counts_four_fifths_of_its_shows_context():
    # three episodes, the show seen today (1.0): ep01 watched itself, ep03 unwatched (its show's date),
    # and a Finished show's episode (every episode of it seen: not reduced)
    tab = Table([("文化祭", "ぶんかさい")], [("show/ep01.srt", "subtitle", None), ("show/ep03.srt", "subtitle", None),
                                            ("done/ep02.srt", "subtitle", None)],
                [L(0, 0, 1, FESTIVAL, "文化祭"), L(0, 1, 1, FESTIVAL, "文化祭"), L(0, 2, 1, FESTIVAL, "文化祭")])
    files = _seen(tab, os.getcwd(), **{"show/ep01.srt": SS.Seen(1, 1.0), "show/ep03.srt": SS.Seen(3, 1.0, SS.REAL, True),
                                       "done/ep02.srt": SS.Seen(9, 1.0)})
    got = costs(tab, moment=SS.Moment(files=files))
    assert got[(0, 0, 1)] == pytest.approx(-0.9)
    assert got[(0, 1, 1)] == pytest.approx(-0.72)
    assert got[(0, 2, 1)] == pytest.approx(-0.9)
    # ...and still beats an equal sentence from a show never started (DevTest drill 9's order)
    assert got[(0, 1, 1)] < 0.0


@pytest.mark.parametrize("heard, expected", [(SS.REAL, 0.0), (SS.AI_VOICE, 0.15), (SS.SILENT, 0.4)])
def test_how_a_file_is_heard_is_a_weight(heard, expected):
    tab = solo(L(0, 0, 1, FESTIVAL, "文化祭"), sources=(("books/toshisyun.epub", "book", None),))
    files = _seen(tab, os.getcwd(), **{"books/toshisyun.epub": SS.Seen(2, 0.0, heard)})
    assert one(tab, moment=SS.Moment(files=files)) == pytest.approx(expected)


def test_a_young_coword_weighs_point_three_of_its_weight_and_only_the_youngest_counts():
    # 準備 (1) and 文化祭 (0) both taught above 手伝う (2), both still young in Anki: the youngest, once
    young = SS.Moment(young={"準備": 1.0, "文化祭": 0.5})
    assert one(_prepare(2, cow=(2, 1, 0)), moment=young) == pytest.approx(-0.3)
    assert one(_prepare(2, cow=(2, 0)), moment=young) == pytest.approx(-0.15)
    # a new co-word is no young word (it is not being learned yet), nor the word itself
    assert one(_prepare(1, cow=(1, 2)), moment=SS.Moment(young={"手伝う": 1.0, "準備": 1.0})) == pytest.approx(1.0)


# --- the cost's boundary: arrays and numbers only (SPEC § 13.3) ------------------------------------------------------- #

def test_the_cost_takes_arrays_and_numbers_and_refuses_a_python_list_per_line():
    tab = solo(L(0, 0, 1, FESTIVAL, "文化祭"))
    arrays, _files = SS._moment_arrays(tab, SS.Moment(), None, os.getcwd())
    cols = tab.take([0])
    cols["chars"] = cols["chars"].tolist()
    with pytest.raises(TypeError):
        SS.cost(cols, arrays, *LENGTH)
    arrays["ctx"] = [0.0]
    with pytest.raises(TypeError):
        SS.cost(tab.take([0]), arrays, *LENGTH)


def test_the_reader_hands_the_cost_arrays_only(monkeypatch, tmp_path):
    lib = Library(tmp_path)
    seen = []
    real = SS.cost

    def spy(columns, moment, low, high, r=None):
        seen.append([type(v) for v in list(columns.values()) + list(moment.values())] + [type(low), type(high)])
        return real(columns, moment, low, high, r)
    monkeypatch.setattr(SS, "cost", spy)
    tab = lib.table([("文化祭", "ぶんかさい")], [("ep01", [FESTIVAL, PREPARE])], lambda f, n, t: L(0, f, n, t, "文化祭"))
    assert SS.choose("ja", [("文化祭", "ぶんかさい")], moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert seen and all(t in (np.ndarray, int) for t in seen[0])


# --- the reader -------------------------------------------------------------------------------------------------------- #

class Library:
    """A data folder with real subtitle files the table's lines come from (each file's digest as the Generate
    writes it, so a changed file is told)."""

    def __init__(self, root):
        self.root = str(root)
        self.files = {}

    def write(self, rel, lines):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\r\n") as f:
            for n, text in enumerate(lines, 1):
                f.write(f"{n}\n00:00:{n:02d},000 --> 00:00:{n:02d},900\n{text}\n\n")
        st = os.stat(path)
        return plan_rules.file_digest([os.path.join(self.root, rel), [st.st_mtime, st.st_size], None, None, "srt"])

    def table(self, keys, episodes, line, cowords=(), folder="show"):
        """`episodes` [(name, [text, …])]; `line(file, number, text)` -> `L` or None."""
        sources, lines = [], []
        for f, (name, texts) in enumerate(episodes):
            rel = f"{folder}/{name}.srt"
            sources.append((rel, "srt", self.write(rel, texts)))
            for n, text in enumerate(texts):
                got = line(f, n, text)
                if got is not None:
                    lines.append(got)
        return Table(keys, sources, lines, cowords)

    def path(self, rel):
        return os.path.normcase(os.path.abspath(os.path.join(self.root, *rel.split("/"))))

    def moment(self, files=None, **kw):
        return SS.Moment(files={self.path(rel): seen for rel, seen in (files or {}).items()}, root=self.root, **kw)


FEST = [("文化祭", "ぶんかさい")]


def _fest(lib, episodes, **kw):
    return lib.table(FEST, episodes, lambda f, n, t: L(0, f, n, t, "文化祭", **kw) if "文化祭" in t else None)


def test_the_best_lines_come_first_with_their_numbers(tmp_path):
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL, NOTICED, PREPARE, SIGN])])
    got = SS.choose("ja", FEST, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    lines = got[FEST[0]]
    # 16 / 16 in the zone (a tie: the earlier place first), then SIGN at 13 characters
    assert [l.text for l in lines] == [FESTIVAL, PREPARE, SIGN]
    assert [l.number for l in lines] == [0, 2, 3]
    assert lines[2].cost == pytest.approx(0.03) and lines[2].chars == 13
    assert lines[0].file == os.path.join(lib.root, "show", "ep01.srt")


def test_a_word_with_no_usable_line_gets_an_empty_list_and_a_word_off_the_list_is_left_out(tmp_path):
    lib = Library(tmp_path)
    tab = lib.table([("文化祭", "ぶんかさい"), ("看板", "かんばん")], [("ep01", [FESTIVAL])],
                    lambda f, n, t: L(0, f, n, t, "文化祭", flags=SS.OVER_WALL))
    got = SS.choose("ja", [("文化祭", "ぶんかさい"), ("看板", "かんばん"), ("夜市", "yèshì")], moment=lib.moment(),
                    length=LENGTH, table=tab, shown=tab.shown())
    assert got == {("文化祭", "ぶんかさい"): [], ("看板", "かんばん"): []}


def test_no_table_reads_as_none_and_the_caller_takes_todays_path(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "app.sentence_table", None)          # not built / not importable
    assert SS._table("ja") is None
    assert SS.choose("ja", FEST, moment=SS.Moment(), length=LENGTH) is None

    class Broken:
        @staticmethod
        def read(language):
            raise ValueError("damaged")
    monkeypatch.setitem(sys.modules, "app.sentence_table", Broken)
    assert SS.choose("ja", FEST, moment=SS.Moment(), length=LENGTH) is None


def test_ties_fall_by_the_files_path_then_the_lines_place_whatever_order_the_files_were_added(tmp_path):
    # Four equal lines in three episodes; the Generate numbered the files in two different orders
    lib = Library(tmp_path)
    episodes = [("ep02", [PREPARE, FESTIVAL]), ("ep01", [DARK, FESTIVAL]), ("ep10", [FESTIVAL])]
    firsts = []
    for order in (episodes, episodes[::-1], [episodes[1], episodes[2], episodes[0]]):
        tab = _fest(lib, order)
        got = SS.choose("ja", FEST, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
        firsts.append([(os.path.basename(l.file), l.number) for l in got[FEST[0]]])
    assert firsts[0] == firsts[1] == firsts[2] == [("ep01.srt", 1), ("ep02.srt", 0), ("ep02.srt", 1)]


def test_never_returns_the_old_cards_line_and_takes_the_next_best(tmp_path):
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL, PREPARE, SIGN])])
    got = SS.choose("ja", FEST, n=2, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown(),
                    never={FEST[0]: {"<b>文化祭</b>まで、あと三日しかないよ。[sound:ep01.mp3]"}})
    assert [l.text for l in got[FEST[0]]] == [PREPARE, SIGN]


def test_the_same_sentence_twice_is_shown_once(tmp_path):
    lib = Library(tmp_path)
    tab = lib.table(FEST, [("ep01", [FESTIVAL, SIGN]), ("ep02", [FESTIVAL])],
                    lambda f, n, t: L(0, f, n, t, "文化祭", repeat=77 if t == FESTIVAL else 0))
    got = SS.choose("ja", FEST, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert [l.text for l in got[FEST[0]]] == [FESTIVAL, SIGN]


def test_a_file_changed_since_the_generate_is_skipped_whole_and_the_next_best_taken(tmp_path):
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL, PREPARE]), ("ep02", [SIGN])])
    path = os.path.join(lib.root, "show", "ep01.srt")
    with open(path, "a", encoding="utf-8") as f:
        f.write("3\n00:00:09,000 --> 00:00:09,900\n看板の色はみんなで決めよう。\n")
    got = SS.choose("ja", FEST, n=2, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert [l.text for l in got[FEST[0]]] == [SIGN]
    os.remove(path)                                                       # gone: the same
    got = SS.choose("ja", FEST, n=2, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert [l.text for l in got[FEST[0]]] == [SIGN]


class Tokens:
    """The token store's read side, as the reader asks it: each file's sentences and their words."""

    def __init__(self, files):
        self.files = {os.path.normcase(os.path.abspath(p)): s for p, s in files.items()}
        self.closed = False

    def file_tokens(self, path):
        return self.files.get(os.path.normcase(os.path.abspath(path)), [])

    def file_stamps(self, paths):
        return {}

    def close(self):
        self.closed = True


def test_the_text_comes_from_the_token_store_and_a_place_past_the_files_end_is_skipped(monkeypatch, tmp_path):
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL, PREPARE, SIGN])])
    path = os.path.join(lib.root, "show", "ep01.srt")
    store = Tokens({path: [(" " + FESTIVAL + " ", [["文化祭", "ぶんかさい", "文化祭"]]),
                           (PREPARE, [["文化祭", "ぶんかさい", "文化祭"], ["準備", "じゅんび", "準備"]])]})
    monkeypatch.setattr(SS, "_tokens", lambda language: store)
    got = SS.choose("ja", FEST, n=3, moment=lib.moment(), length=LENGTH, table=tab)
    assert [l.text for l in got[FEST[0]]] == [FESTIVAL, PREPARE]            # SIGN's place is past the store's end
    assert store.closed


def test_a_young_word_known_before_the_generate_is_read_in_the_leading_lines(monkeypatch, tmp_path):
    # Two equal lines; the second holds 手伝う, a young card known before the Generate (no co-word of the table):
    # read from the token store, it takes the lead (DevTest drill 8)
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL, PREPARE])])
    path = os.path.join(lib.root, "show", "ep01.srt")
    store = Tokens({path: [(FESTIVAL, [["文化祭", "", "文化祭"], ["三日", "", "三日"]]),
                           (PREPARE, [["文化祭", "", "文化祭"], ["手伝う", "", "手伝っ"]])]})
    monkeypatch.setattr(SS, "_tokens", lambda language: store)
    got = SS.choose("ja", FEST, n=2, moment=lib.moment(young={"手伝う": 0.5}), length=LENGTH, table=tab)
    lines = got[FEST[0]]
    assert [l.text for l in lines] == [PREPARE, FESTIVAL]
    assert lines[0].cost == pytest.approx(-0.15)
    # the word itself, young too, is never its own young word
    got = SS.choose("ja", FEST, n=2, moment=lib.moment(young={"文化祭": 1.0}), length=LENGTH, table=tab)
    assert [(l.text, l.cost) for l in got[FEST[0]]] == [(FESTIVAL, 0.0), (PREPARE, 0.0)]


def test_a_silent_line_ranks_lower_but_is_never_removed(tmp_path):
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL]), ("ep02", [SIGN])])
    files = {"show/ep01.srt": SS.Seen(1, 0.0, SS.SILENT), "show/ep02.srt": SS.Seen(2, 0.0, SS.REAL)}
    got = SS.choose("ja", FEST, n=2, moment=lib.moment(files), length=LENGTH, table=tab, shown=tab.shown())
    assert [(l.text, l.heard) for l in got[FEST[0]]] == [(SIGN, SS.REAL), (FESTIVAL, SS.SILENT)]


def test_heard_first_puts_the_best_heard_line_first_and_keeps_the_rest_in_their_order(tmp_path):
    # A clean silent line far better than the heard one (context): heard_first gives the card the heard one
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL, PREPARE]), ("ep02", [SIGN])])
    files = {"show/ep01.srt": SS.Seen(1, 1.0, SS.SILENT), "show/ep02.srt": SS.Seen(2, 0.0, SS.AI_VOICE)}
    plain = SS.choose("ja", FEST, n=3, moment=lib.moment(files), length=LENGTH, table=tab, shown=tab.shown())
    assert [l.text for l in plain[FEST[0]]] == [FESTIVAL, PREPARE, SIGN]
    first = SS.choose("ja", FEST, n=3, moment=lib.moment(files), length=LENGTH, table=tab, shown=tab.shown(),
                      heard_first=True)
    assert [l.text for l in first[FEST[0]]] == [SIGN, FESTIVAL, PREPARE]
    one_line = SS.choose("ja", FEST, n=1, moment=lib.moment(files), length=LENGTH, table=tab, shown=tab.shown(),
                         heard_first=True)
    assert [l.text for l in one_line[FEST[0]]] == [SIGN]
    # no heard line at all: the order is the score's
    files["show/ep02.srt"] = SS.Seen(2, 0.0, SS.SILENT)
    none = SS.choose("ja", FEST, n=1, moment=lib.moment(files), length=LENGTH, table=tab, shown=tab.shown(),
                     heard_first=True)
    assert [l.text for l in none[FEST[0]]] == [FESTIVAL]


def test_only_stays_inside_the_mined_episode_and_clean_only_keeps_i_plus_one(tmp_path):
    lib = Library(tmp_path)
    keys = [("文化祭", "ぶんかさい"), ("準備", "じゅんび")]
    tab = lib.table(keys, [("ep01", [FESTIVAL, PREPARE]), ("ep02", [SIGN])],
                    lambda f, n, t: L(0, f, n, t, "文化祭", cow=(1,) if t == FESTIVAL else ()) if "文化祭" in t else None,
                    cowords=((0, ((0,),)), (1, ((1,),))))
    got = SS.choose("ja", keys[:1], n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown(),
                    only=[os.path.join(lib.root, "show", "ep02.srt")])
    assert [l.text for l in got[keys[0]]] == [SIGN]
    got = SS.choose("ja", keys[:1], n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown(),
                    clean_only=True)
    assert [l.text for l in got[keys[0]]] == [PREPARE, SIGN]
    plain = SS.choose("ja", keys[:1], n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert [(l.text, l.others) for l in plain[keys[0]]] == [(PREPARE, 0), (SIGN, 0), (FESTIVAL, 1)]


def test_whole_scores_every_row_in_one_pass_with_the_same_answer(tmp_path):
    lib = Library(tmp_path)
    keys = [("文化祭", "ぶんかさい"), ("看板", "かんばん")]
    tab = lib.table(keys, [("ep01", [FESTIVAL, SIGN, COLOUR]), ("ep02", [PREPARE])],
                    lambda f, n, t: L(0 if "文化祭" in t else 1, f, n, t, "文化祭" if "文化祭" in t else "看板")
                    if "文化祭" in t or "看板" in t else None)
    parts = SS.choose("ja", keys, n=2, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert tab.blocked == [0, 1]
    whole = SS.choose("ja", keys, n=2, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown(), whole=True)
    assert parts == whole and tab.blocked == [0, 1, 0, 1]
    only_one = SS.choose("ja", keys[1:], n=2, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert tab.blocked[4:] == [1] and only_one[keys[1]] == parts[keys[1]]


def test_chinese_lines_through_the_same_reader(tmp_path):
    lib = Library(tmp_path)
    keys = [("夜市", "yèshì"), ("牛肉面", "niúròumiàn")]
    # night_market.srt's lines: 夜市 in a 15-character line; 牛肉面 in a 10-character fragment and a nested folder
    tab = lib.table(keys, [("vlog/ep01", [NIGHT, NOODLE, TEA, PRICE])],
                    lambda f, n, t: L(0, f, n, t, "夜市") if "夜市" in t else
                    L(1, f, n, t, "牛肉面", besides=1) if "牛肉面" in t else None, folder="taipei/2024")
    got = SS.choose("zh", keys, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert [l.text for l in got[keys[0]]] == [NIGHT] and got[keys[0]][0].cost == pytest.approx(0.0)
    assert got[keys[1]][0].cost == pytest.approx(0.03 * 4 + 0.5)
    assert got[keys[1]][0].file == os.path.join(lib.root, "taipei", "2024", "vlog", "ep01.srt")


def test_a_key_with_no_reading_finds_the_lemmas_one_row(tmp_path):
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL])])
    got = SS.choose("ja", [("文化祭", "")], moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown())
    assert [l.text for l in got[("文化祭", "")]] == [FESTIVAL]


def test_an_empty_ask_and_an_empty_table(tmp_path):
    lib = Library(tmp_path)
    empty = Table(FEST, [], [])
    assert SS.choose("ja", [], moment=lib.moment(), length=LENGTH, table=empty) == {}
    assert SS.choose("ja", FEST, moment=lib.moment(), length=LENGTH, table=empty) == {FEST[0]: []}


def test_a_table_damaged_inside_its_blocks_reads_as_none_never_an_exception(tmp_path):
    # the head read, a block that won't unpack: the caller takes today's path (CLAUDE.md § 6, fail gracefully)
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL])])

    def broken(row):
        raise ValueError("a block of the wrong size")
    tab.block = broken
    assert SS.choose("ja", FEST, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown()) is None


def test_an_order_handed_in_with_no_reading_finds_its_row():
    # rows with no reading; after a move the caller names them (lemma, None): the same rows as (lemma, "")
    tab = Table([("文化祭", ""), ("準備", "")], [("show/ep01.srt", "subtitle", None)],
                [L(0, 0, 3, PREPARE, "文化祭", cow=(0, 1))], ((0, ((0,),)), (1, ((1,),))))
    assert one(tab) == pytest.approx(1.0)                                 # 準備 below 文化祭: new
    assert one(tab, order={("準備", None): 0, ("文化祭", None): 1}) == pytest.approx(0.0)


# --- the gates session: the refuters' findings that held, the waste lens, the round trip ----------------------------- #

def test_never_names_a_row_with_or_without_its_reading(tmp_path):
    # Swap's old card named (lemma, reading), the ask (lemma, ""): the same row, so the old line is still never shown
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL, PREPARE])])
    got = SS.choose("ja", [("文化祭", "")], moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown(),
                    never={("文化祭", "ぶんかさい"): {FESTIVAL}})
    assert [l.text for l in got[("文化祭", "")]] == [PREPARE]
    got = SS.choose("ja", FEST, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown(),
                    never={("文化祭", None): {FESTIVAL}})
    assert [l.text for l in got[FEST[0]]] == [PREPARE]


def test_a_context_or_young_weight_that_is_no_number_never_drops_a_line(monkeypatch, tmp_path):
    # A broken moment (NaN) is weighed as nothing known of it: the line is still a candidate, never silently gone
    monkeypatch.setattr(SS, "_tokens", lambda language: None)
    lib = Library(tmp_path)
    tab = lib.table(KEYS[:2], [("ep01", [FESTIVAL, PREPARE])],
                    lambda f, n, t: L(0, f, n, t, "文化祭", cow=(1,) if t == PREPARE else ()),
                    cowords=((0, ((0,),)), (1, ((1,),))))
    for broken in (float("nan"), float("inf")):
        files = {"show/ep01.srt": SS.Seen(1, broken)}
        got = SS.choose("ja", FEST, n=2, moment=lib.moment(files, young={"準備": broken}), length=LENGTH,
                        table=tab, shown=tab.shown(), order={KEYS[1]: 0, KEYS[0]: 1})
        assert [(l.text, l.cost, l.context) for l in got[FEST[0]]] == [(FESTIVAL, 0.0, 0.0), (PREPARE, 0.0, 0.0)]


def test_a_young_word_still_below_on_the_list_lends_no_young_weight(monkeypatch, tmp_path):
    # 看板 is a row below 文化祭 (still new when the card is studied): a new word, never the line's young word, though
    # the token store reads it in the line and Anki holds a young card of it
    lib = Library(tmp_path)
    tab = lib.table([FEST[0], ("看板", "かんばん")], [("ep01", [SIGN])],
                    lambda f, n, t: L(0, f, n, t, "文化祭", cow=(1,)), cowords=((0, ((0,),)), (1, ((1,),))))
    path = os.path.join(lib.root, "show", "ep01.srt")
    store = Tokens({path: [(SIGN, [["文化祭", "", "文化祭"], ["看板", "", "看板"], ["描く", "", "描く"]])]})
    monkeypatch.setattr(SS, "_tokens", lambda language: store)
    got = SS.choose("ja", FEST, moment=lib.moment(young={"看板": 1.0}), length=LENGTH, table=tab)
    assert got[FEST[0]][0].cost == pytest.approx(1.0 + 0.03)
    # ...while a word known before the Generate (no row) still lends its weight
    got = SS.choose("ja", FEST, moment=lib.moment(young={"看板": 1.0, "描く": 0.5}), length=LENGTH, table=tab)
    assert got[FEST[0]][0].cost == pytest.approx(1.0 + 0.03 - 0.15)


def test_the_words_own_other_reading_is_never_its_young_word():
    # 描く read かく is taught above 描く read えがく: its young weight is the lemma's own, never the line's young word
    keys = [("描く", "かく"), ("描く", "えがく")]
    tab = Table(keys, [("show/ep01.srt", "subtitle", None)], [L(1, 0, 2, SIGN, "描く", cow=(0,))],
                ((0, ((0,),)), (1, ((1,),))))
    assert one(tab, moment=SS.Moment(young={"描く": 1.0})) == pytest.approx(0.03)
    # another word's young weight still counts (the same line, 看板 taught above and young)
    keys = [("看板", "かんばん"), ("描く", "えがく")]
    tab = Table(keys, [("show/ep01.srt", "subtitle", None)], [L(1, 0, 2, SIGN, "描く", cow=(0,))],
                ((0, ((0,),)), (1, ((1,),))))
    assert one(tab, moment=SS.Moment(young={"看板": 1.0})) == pytest.approx(0.03 - 0.3)


class _Counted(dict):
    def __init__(self, *a):
        super().__init__(*a)
        self.asked = 0

    def get(self, key, default=None):
        self.asked += 1
        return super().get(key, default)


def test_heard_first_on_a_word_with_no_heard_line_reads_no_more_lines_than_without(tmp_path):
    # Every line silent: the ask cannot be met, so the walk stops at n as without it (never every line of the word)
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL]), ("ep02", [PREPARE]), ("ep03", [SIGN])])
    files = {f"show/ep0{i}.srt": SS.Seen(i, 0.0, SS.SILENT) for i in (1, 2, 3)}
    plain, asked = _Counted(tab.shown()), _Counted(tab.shown())
    a = SS.choose("ja", FEST, moment=lib.moment(files), length=LENGTH, table=tab, shown=plain)
    b = SS.choose("ja", FEST, moment=lib.moment(files), length=LENGTH, table=tab, shown=asked, heard_first=True)
    assert a == b and [l.text for l in b[FEST[0]]] == [FESTIVAL]
    assert asked.asked == plain.asked == 1


def test_only_the_files_of_the_lines_taken_are_resolved_and_ranked(tmp_path):
    # 20,000 files, a word in two: the moment's per-file work and the tie ranks are the two files', not the library's
    sources = [(f"show/ep{i:05d}.srt", "subtitle", None) for i in range(6)]
    tab = Table(FEST, sources, [L(0, 4, 0, FESTIVAL, "文化祭"), L(0, 1, 0, PREPARE, "文化祭")])
    arrays, files = SS._moment_arrays(tab, SS.Moment(), None, str(tmp_path), [1, 4])
    assert sorted(files) == [1, 4] and len(arrays["ctx"]) == 6
    ranks = SS._tie_ranks(tab.sources(), [4, 1])
    assert (ranks[1], ranks[4]) == (0, 1) and all(ranks[s] == SS.BIG for s in (0, 2, 3, 5))


def test_a_head_without_places_is_refused_unless_an_order_is_handed_in(tmp_path):
    # Every table of format 3 names the Generate's list order ("places"); a head without it is a damaged one: with no
    # order handed in, "new when studied" cannot be weighed — today's path
    lib = Library(tmp_path)
    tab = _fest(lib, [("ep01", [FESTIVAL])])
    del tab.head["places"]
    assert SS.choose("ja", FEST, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown()) is None
    got = SS.choose("ja", FEST, moment=lib.moment(), length=LENGTH, table=tab, shown=tab.shown(), order={FEST[0]: 0})
    assert [l.text for l in got[FEST[0]]] == [FESTIVAL]


def test_the_lists_order_is_the_heads_places_not_the_rows_numbering():
    # rows numbered as Generate met them (文化祭 0, 準備 1); the list puts 準備 first: then it is known above
    tab = Table([("文化祭", "ぶんかさい"), ("準備", "じゅんび")], [("show/ep01.srt", "subtitle", None)],
                [L(0, 0, 3, PREPARE, "文化祭", cow=(1,))], ((0, ((0,),)), (1, ((1,),))), places=[1, 0])
    assert one(tab) == pytest.approx(0.0)
    tab.head["places"] = [0, 1]
    assert one(tab) == pytest.approx(1.0)
    tab.head["places"] = [0, -1]                                          # 準備 off the list: never taught
    assert one(tab) == pytest.approx(1.0)


# --- the round trip: a table Generate's packer wrote, read back by the reader ---------------------------------------- #

RT_KEYS = [("文化祭", "ぶんかさい"), ("準備", "じゅんび"), ("看板", "かんばん")]
RT_EPISODES = [("ep01", [FESTIVAL, PREPARE, SIGN]), ("ep02", [COLOUR, PREPARE])]
RT_WORDS = {FESTIVAL: ["文化祭"], PREPARE: ["文化祭", "準備"], SIGN: ["文化祭", "看板"], COLOUR: ["看板"]}
RT_JA = ("ja", RT_KEYS, RT_EPISODES, RT_WORDS)
# night_market.srt: 我们 in two lines, each with one other list word (夜市, 牛肉面) — which is taught first moves its cost
RT_ZH = ("zh", [("我们", "wǒmen"), ("夜市", "yèshì"), ("牛肉面", "niúròumiàn")],
         [("ep01", [NIGHT, TEA]), ("ep02", [NOODLE, PRICE])],
         {NIGHT: ["我们", "夜市"], NOODLE: ["我们", "牛肉面"], TEA: [], PRICE: []})


def _rt_lines(case=RT_JA):
    """Every (row, file, place, text, word, its other words) of the two episodes."""
    _language, keys, episodes, words = case
    out = []
    for f, (_name, texts) in enumerate(episodes):
        for n, text in enumerate(texts):
            for word in words[text]:
                row = [k[0] for k in keys].index(word)
                out.append((row, f, n, text, word, [c for c in words[text] if c != word]))
    return out


def _rt_sources(lib, case=RT_JA):
    """The two episodes written once: [[rel, kind, digest]] as the plan numbers its files."""
    return [[f"show/{name}.srt", "srt", lib.write(f"show/{name}.srt", texts)] for name, texts in case[2]]


def _rt_written(sources, tmp_path, language="ja", run="sig-1", case=RT_JA, places=None):
    from app import sentence_table as st
    keys = case[1]
    rows = [k[0] for k in keys]
    p = st.Packer()
    for row, f, n, text, word, others in _rt_lines(case):
        p.add(keys[row], f, n, len(text), plan_rules.text_hash_of(text), [keys[rows.index(c)] for c in others],
              besides=len(others), starts=text.find(word))
    row_of = {k: i for i, k in enumerate(keys)}
    tab = p.finish(keys, row_of.get, lambda key: ((row_of[key],),), lambda key: row_of.get(key, -1),
                   lambda key: key, lambda index: None, sources,
                   {"engine": "e47", "run_signature": run, "language": language}, places=places)
    path = os.path.join(str(tmp_path), "results", st.TABLE_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tab.write(path)
    return path


def _rt_fake(sources, case=RT_JA, places=True):
    keys = case[1]
    rows = [k[0] for k in keys]
    lines = [L(row, f, n, text, word, besides=len(others), cow=[rows.index(c) for c in others],
               repeat=plan_rules.text_hash_of(text) & 0xFFFFFFFF if text == PREPARE else 0)
             for row, f, n, text, word, others in _rt_lines(case)]
    return Table(keys, sources, lines, [(k, ((k,),)) for k in range(len(keys))], places=places)


def test_the_round_trip_a_written_table_gives_the_reader_what_its_lines_give(tmp_path):
    # Generate's packer writes the two episodes' lines; opened from disk, the reader chooses what it chooses from the
    # same lines in memory — every row, every order, ja
    from app import sentence_table as st
    lib = Library(tmp_path)
    sources = _rt_sources(lib)
    opened = st.open_table(_rt_written(sources, tmp_path), language="ja", engine="e47", run_signature="sig-1")
    assert opened is not None and opened.head["keys"] == [list(k) for k in RT_KEYS]
    fake = _rt_fake(sources)
    shown = fake.shown()
    for order in ({k: i for i, k in enumerate(RT_KEYS)}, {RT_KEYS[1]: 0, RT_KEYS[2]: 1, RT_KEYS[0]: 2}):
        ours = SS.choose("ja", RT_KEYS, n=3, moment=lib.moment(), length=LENGTH, table=opened, shown=shown,
                         order=order)
        mine = SS.choose("ja", RT_KEYS, n=3, moment=lib.moment(), length=LENGTH, table=fake, shown=shown,
                         order=order)
        assert ours == mine and all(ours[k] for k in RT_KEYS)
    # 準備's PREPARE in both episodes is one sentence: shown once (the table's fingerprint)
    assert [l.text for l in ours[RT_KEYS[1]]] == [PREPARE]


def _opened(tmp_path, case, places, run):
    """The case's two episodes written by Generate's packer with `places`, opened from disk: (library, sources,
    table)."""
    from app import sentence_table as st
    lib = Library(tmp_path / run)
    sources = _rt_sources(lib, case)
    path = _rt_written(sources, tmp_path / run, language=case[0], run=run, case=case, places=places)
    tab = st.open_table(path, language=case[0], engine="e47", run_signature=run)
    assert tab is not None and tab.places() == places
    return lib, sources, tab


def _costs(got, keys):
    return [[(l.text, l.cost) for l in got[k]] for k in keys]


@pytest.mark.parametrize("case", [RT_JA, RT_ZH], ids=["ja", "zh"])
def test_with_no_order_handed_in_the_reader_weighs_by_the_tables_places(tmp_path, case):
    # E-TABLE's format 3: each row's place in the list Generate wrote (-1: not on it). With no order handed in, the
    # reader gives what the same places handed in as an order give, and what its lines in memory give; another list
    # order gives another answer (the places are read, not the rows' first-met numbering)
    language, keys = case[0], case[1]
    costs = {}
    for run, places in (("first", [0, 1, 2]),      # the word first: its lines' other words still new when studied
                        ("last", [2, 0, 1]),       # both other words before it: known when it is studied
                        ("off", [2, -1, 1])):      # as "last", but the second word off the list: never taught
        lib, sources, tab = _opened(tmp_path, case, places, run)
        shown = _rt_fake(sources, case).shown()
        got = SS.choose(language, keys, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=shown)
        as_order = {k: at for k, at in zip(keys, places) if at >= 0}
        assert got == SS.choose(language, keys, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=shown,
                                order=as_order)
        # an order handed in with the places' own -1 kept: off the list too, never a place before every word
        assert got == SS.choose(language, keys, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=shown,
                                order=dict(zip(keys, places)))
        assert got == SS.choose(language, keys, n=3, moment=lib.moment(), length=LENGTH,
                                table=_rt_fake(sources, case, places), shown=shown)
        assert all(got[k] for k in keys)
        costs[run] = _costs(got, keys)
    first, last = dict(costs["first"][0]), dict(costs["last"][0])   # the word's lines: {text: cost}
    assert first.keys() == last.keys() and all(last[t] <= first[t] for t in first)
    assert sum(last.values()) < sum(first.values())   # cheaper once its lines' other words are taught first
    assert costs["off"][0] != costs["last"][0]     # -1 is off the list, never a place before the word (known)


@pytest.mark.parametrize("case", [RT_JA, RT_ZH], ids=["ja", "zh"])
def test_an_order_handed_in_after_a_move_wins_over_the_tables_places(tmp_path, case):
    # SPEC § 5: a move rewrites the list, never the table — the caller hands the new order, and it wins over `places`
    language, keys = case[0], case[1]
    lib, sources, tab = _opened(tmp_path, case, [0, 1, 2], "before")
    shown = _rt_fake(sources, case).shown()
    moved = {keys[1]: 0, keys[2]: 1, keys[0]: 2}
    after = SS.choose(language, keys, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=shown, order=moved)
    before = SS.choose(language, keys, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=shown)
    lib2, _sources, tab2 = _opened(tmp_path, case, [2, 0, 1], "moved")      # the moved list, as a Generate writes it
    again = SS.choose(language, keys, n=3, moment=lib2.moment(), length=LENGTH, table=tab2, shown=shown)
    assert _costs(after, keys) == _costs(again, keys)
    assert _costs(after, keys)[0] != _costs(before, keys)[0]
    # an order that names only some words: the rest are off the list, never filled in from the table's places
    part = SS.choose(language, keys, n=3, moment=lib.moment(), length=LENGTH, table=tab, shown=shown,
                     order={keys[1]: 0, keys[0]: 1})
    lib3, _sources, tab3 = _opened(tmp_path, case, [1, 0, -1], "part")
    assert _costs(part, keys) == _costs(SS.choose(language, keys, n=3, moment=lib3.moment(), length=LENGTH,
                                                   table=tab3, shown=shown), keys)


def test_the_reader_opens_results_table_once_while_its_stamp_holds(monkeypatch, tmp_path):
    # SPEC § 5.3: the head kept per process until the file's (path, time, size) or the run's stamp changes; another
    # run, language or engine, or no table: None
    from app import analyzer, path_utils
    lib = Library(tmp_path)
    sources = _rt_sources(lib)
    path = _rt_written(sources, tmp_path)
    monkeypatch.setattr(path_utils, "get_user_file", lambda rel: os.path.join(str(tmp_path), rel))
    monkeypatch.setattr(analyzer, "engine_id", lambda: "e47")
    run = ["sig-1"]
    monkeypatch.setattr(analyzer, "read_run_stamp", lambda results: run[0])
    monkeypatch.setattr(SS, "_HEAD", {})
    first = SS._table("ja")
    assert first is not None and SS._table("ja") is first
    assert SS._table("zh") is None
    _rt_written(sources, tmp_path, run="sig-2")
    run[0] = "sig-2"
    again = SS._table("ja")
    assert again is not None and again is not first
    run[0] = "sig-3"
    assert SS._table("ja") is None
    run[0] = None
    assert SS._table("ja") is None
    run[0] = "sig-2"
    os.remove(path)
    assert SS._table("ja") is None
