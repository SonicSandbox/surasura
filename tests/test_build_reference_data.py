"""The compound tables' build (scripts/build_reference_data.py) — its pieces on toy inputs, and the shipped tables.

The build decides which dictionary compounds the tokenizer joins: the headwords UniDic reads as words of their own
(上層部 = 上層 + 部), minus a string two words make by chance, the counts among the words holding a number, the verbs
whose second verb is grammar, and the plurals; each compound's parts are free or bound by the lists' ranks. Every
piece is tested here on made-up counts and tiny word lists, with real Japanese words through the project's fugashi +
unidic-lite — never the reference corpora, which the build alone reads.
"""

import importlib.util
import json
import os
import sys
from collections import Counter

import pytest

from app import analyzer, dictionary_data, reference_data


@pytest.fixture(scope="module")
def brd():
    """scripts/build_reference_data.py — it builds the tables and never ships, so it is no package."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts",
                        "build_reference_data.py")
    spec = importlib.util.spec_from_file_location("build_reference_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tagger():
    return analyzer.Tagger()


def _words(brd, tagger, word):
    """`word` read alone as the build reads a headword: the tagger, no affix table."""
    return [brd._snap(w) for w in analyzer._join_affix_runs(tagger(word), {})]


def _lists(brd, tmp_path, monkeypatch, *lists):
    """Tiny frequency lists in the lists' own shape ([word, reading] pairs, best rank first), as ListReadings."""
    monkeypatch.setattr(brd, "LISTS_DIR", str(tmp_path))
    out = []
    for n, entries in enumerate(lists):
        name = f"list{n}"
        (tmp_path / f"{name}.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        out.append(brd.ListReadings(name))
    return out


# --- The even-odds test ---------------------------------------------------------------------------------------- #

def test_chance_is_how_often_the_parts_meet_side_by_side_by_chance(brd):
    # f(A)·f(B) / N: 今 met 2,000 times and 頭 1,000 times in 100,000 tokens meet by chance about 20 times. With three
    # parts, the split most likely by chance counts: the pair 経済 + 成長 side by side, then 期.
    counts = {"tokens": 100_000, "uni": Counter({"今": 2_000, "頭": 1_000, "経済": 500, "成長": 400, "期": 300}),
              "big": Counter({("経済", "成長"): 100, ("成長", "期"): 5})}
    assert brd.chance(counts, ["今", "頭"]) == pytest.approx(20.0)
    assert brd.chance(counts, ["経済", "成長", "期"]) == pytest.approx(max(100 * 300, 500 * 5) / 100_000)
    assert brd.chance(counts, ["今", "未知"]) == 0.0          # a part the text never has: no chance to speak of


def test_a_calibration_reads_a_rank_as_the_median_count_and_never_rarer_at_a_better_rank(brd):
    # The lists' own compounds whose parts almost never meet by chance: at a rank, how often the text joins them.
    points = [(1_000 + i, 40) for i in range(20)] + [(30_000 + i, 3) for i in range(20)] + [(31_000, 90)] * 20
    cal = brd.Calibration(points)
    assert cal(1_010) == pytest.approx(40)
    assert cal(30_010) <= cal(1_010)            # forced non-increasing: the 90s at 31,000 don't lift the curve
    assert cal(None) == 0.0


def test_the_even_odds_test_refuses_only_where_neither_the_text_nor_both_lists_vouch(brd, tmp_path, monkeypatch):
    # 上層部: its parts almost never meet by chance, so the text vouches. 今頭 (今、頭が痛い): chance accounts for
    # it and only one list carries it — refused. 仕事人間: chance could account for it, but both lists carry it as often
    # as chance would — kept. The calibration comes from twenty compounds at the same ranks (100-119: one bin of
    # the log-rank curve), after 99 other words.
    rare = [f"語{i:02d}" for i in range(20)]
    other = [[f"他{i:02d}", "タ"] for i in range(99)]
    first = other + [[w, "ゴ"] for w in rare] + [["仕事人間", "シゴトニンゲン"], ["上層部", "ジョウソウブ"]]
    second = other + [[w, "ゴ"] for w in rare] + [["仕事人間", "シゴトニンゲン"], ["今頭", "イマガシラ"]]
    lists = _lists(brd, tmp_path, monkeypatch, first, second)
    nouns = {w: [None] for w in rare + ["仕事人間", "上層部", "今頭"]}
    parts = {w: [w + "甲", w + "乙"] for w in rare}
    parts.update({"仕事人間": ["仕事", "人間"], "上層部": ["上層", "部"], "今頭": ["今", "頭"]})
    uni = Counter({"仕事": 3_000, "人間": 2_000, "上層": 50, "部": 300, "今": 3_000, "頭": 1_000})
    uni.update({p: 1 for w in rare for p in parts[w]})
    counts = {"tokens": 1_000_000, "uni": uni, "big": Counter(),
              "join": Counter({**{w: 10 for w in rare}, "仕事人間": 7, "上層部": 5, "今頭": 1}),
              "raw": Counter({**{w: 10 for w in rare}, "仕事人間": 7, "上層部": 5, "今頭": 1})}
    monkeypatch.setattr(brd, "_read", lambda w: w)
    nouns = {w: parts[w] for w in nouns}
    refused, evidence = brd.even_odds(nouns, counts, lists)
    assert "今頭" in refused and evidence["今頭"]["est"] == 0.0      # one list only: the lists can't vouch
    assert "上層部" not in refused and evidence["上層部"]["e"] < 1
    assert "仕事人間" not in refused and evidence["仕事人間"]["e"] >= 1 and evidence["仕事人間"]["est"] >= 6


# --- Whether a part is free ------------------------------------------------------------------------------------- #

def test_a_part_is_free_where_a_list_ranks_it_at_least_as_well_as_its_compound(brd, tagger, tmp_path, monkeypatch):
    # 撤回 lives outside 前言撤回 (ranked better than the compound); 前言 doesn't. 千載一遇's halves are in neither
    # list: bound. A number is never free (no word). Reading-aware: a part is ranked under its own reading.
    lists = _lists(brd, tmp_path, monkeypatch,
                   [["撤回", "テッカイ"], ["前言撤回", "ゼンゲンテッカイ"], ["千載一遇", "センザイイチグウ"],
                    ["前言", "ゼンゲン"], ["二十", "ニジュウ"], ["歳", "サイ"], ["二十歳", "ハタチ"]])
    table = {"前言撤回": ["前言撤回", "ゼンゲンテッカイ", "N", 0, []], "千載一遇": ["千載一遇", "センザイイチグウ", "N", 0, []],
             "二十歳": ["二十歳", "ハタチ", "Q", 0, []]}
    words_of = {w: _words(brd, tagger, w) for w in table}
    brd.compound_parts(table, words_of, lists)
    assert {p[0]: p[2] for p in table["前言撤回"][4]} == {"前言": 0, "撤回": 1}
    assert [p[2] for p in table["千載一遇"][4]] == [0, 0]
    assert [(p[0], p[2]) for p in table["二十歳"][4]] == [("二十", 0), ("歳", 1)]


def test_a_three_part_compound_shows_a_compound_inside_it_as_one_part(brd, tagger, tmp_path, monkeypatch):
    # 経済成長期 read with the table's other words: 経済成長 + 期 — the reading a longer word's use credits.
    lists = _lists(brd, tmp_path, monkeypatch, [["経済成長", "ケイザイセイチョウ"], ["経済成長期", "ケイザイセイチョウキ"]])
    table = {"経済成長": ["経済成長", "ケイザイセイチョウ", "N", 0, []],
             "経済成長期": ["経済成長期", "ケイザイセイチョウキ", "N", 0, []]}
    words_of = {w: _words(brd, tagger, w) for w in table}
    brd.compound_parts(table, words_of, lists)
    assert [p[0] for p in table["経済成長期"][4]] == ["経済成長", "期"]
    assert [p[0] for p in table["経済成長"][4]] == ["経済", "成長"]
    assert list(table) == ["経済成長", "経済成長期"]          # the table keeps its order


# --- Numbers ---------------------------------------------------------------------------------------------------- #

NUMERAL_READINGS = {
    "三人": {"サンニン"}, "五人": {"ゴニン"}, "一冊": {"イッサツ"},
    "二十歳": {"ハタチ"}, "十歳": {"ジッサイ"}, "三歳": {"サンサイ"}, "二十日": {"ハツカ"},
    "三日": {"ミッカ"}, "二日": {"フツカ"}, "四日": {"ヨッカ"}, "三つ": {"ミッツ"},
    "一日": {"イチニチ", "ツイタチ"}, "一日中": {"イチニチジュウ"}, "中": {"ナカ", "チュウ", "ジュウ"},
    "十円玉": {"ジュウエンダマ"}, "百円玉": {"ヒャクエンダマ"}, "十円": {"ジュウエン"}, "玉": {"タマ"},
    "十人十色": {"ジュウニントイロ"}, "一大事": {"イチダイジ"}, "五十人": {"イソンド"},
}


@pytest.fixture(scope="module")
def numerals(brd, tagger):
    return {w: _words(brd, tagger, w) for w in NUMERAL_READINGS if brd.compound_shape(_words(brd, tagger, w), w) == "Q"}


def test_a_counter_is_a_word_the_lists_carry_after_two_or_more_numbers(brd, numerals):
    # 人 after 三 and 五: a counter, though UniDic files it as a plain suffix there — so the table names it. 冊 after
    # one number only is none by the lists (UniDic's own class still makes a word a counter where it files one).
    counters, named = brd.counters_of(numerals)
    assert "人" in counters and "人" in named
    assert "冊" not in counters


@pytest.fixture(scope="module")
def numeral_test(brd, numerals):
    counters, _named = brd.counters_of(numerals)
    both = set(numerals) - {"五十人"}                    # 五十人's odd reading comes from one list alone
    return brd.NumeralTest(numerals, NUMERAL_READINGS, counters, both)


@pytest.mark.parametrize("word, clause", [
    ("十人十色", "inside"),         # a number after a word of its own: no count starts there
    ("一大事", "no counter"),       # 大事 counts nothing
    ("二十歳", "not a count"),      # ハタチ reads 歳 as no other count of it does (十歳 ジッサイ, 三歳 サンサイ)
    ("一日中", "fixed count"),      # 一日 is a count, but the lists carry 日中 after no other number
    ("三日", "count"),              # ミ (三つ) + カ (二日, 四日): read as the lists' other counts read them
    ("一日", "count"),              # both a word and a count (ツイタチ, イチニチ): counts stay apart
    ("十円玉", "count"),            # 百円玉 too: the frame takes other numbers
    ("五十人", "count"),            # a reading one list alone gives never makes a count a word
])
def test_a_word_holding_a_number_joins_only_where_the_number_counts_nothing(numeral_test, word, clause):
    assert numeral_test.clause(word) == clause


# The lists' readings of a few words holding a number: 位, 節, 歳, 期 and 回 count after two numbers or more.
JMDICT_NUMERALS = {
    "三位": {"サンミ"}, "一位": {"イチイ"}, "二位": {"ニイ"},
    "七節": {"ナナフシ"}, "一節": {"イッセツ"}, "二節": {"ニセツ"},
    "一期": {"イチゴ"}, "二期": {"ニキ"}, "三期": {"サンキ"}, "一回": {"イッカイ"}, "三回": {"サンカイ"},
    "二十歳": {"ハタチ"}, "十歳": {"ジッサイ"}, "三歳": {"サンサイ"}, "二十日": {"ハツカ"}, "二十分": {"ニジュップン"},
}


def _entry(kanji, kana, senses, pos=("n",)):
    """One JMdict entry as scripts/jmdict_flags.load hands it out: kanji [(spelling, priority tags)], kana [(reading,
    priority tags, the spellings it is restricted to)], senses [(marks, gloss)], each sense of the part of speech
    `pos`."""
    return {"seq": 0, "kanji": [(k, pri, ()) for k, pri in kanji],
            "kana": [(r, pri, restr, False, ()) for r, pri, restr in kana],
            "senses": [{"pos": pos, "misc": misc, "field": (), "gloss": (gloss,), "xref": (), "stagk": (),
                        "stagr": (), "lsource": ()} for misc, gloss in senses]}


def _jmdict_of(brd, entries, tmp_path, monkeypatch):
    """scripts/jmdict_flags.py as the build imports it, reading `entries` for JMdict."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "jmdict_flags.py")
    spec = importlib.util.spec_from_file_location("jmdict_flags", path)
    jmdict_flags = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jmdict_flags)
    monkeypatch.setitem(sys.modules, "jmdict_flags", jmdict_flags)
    monkeypatch.setattr(jmdict_flags, "load", lambda _path: entries)
    (tmp_path / "JMdict_e.gz").write_bytes(b"")
    monkeypatch.setattr(brd, "JMDICT", str(tmp_path / "JMdict_e.gz"))


def test_a_word_the_lists_read_as_no_count_goes_apart_where_jmdict_reads_it_as_a_count(brd, tagger, tmp_path,
                                                                                       monkeypatch):
    # A word the lists read as no count joins only where JMdict agrees. 三位 サンミ: JMdict reads it さんい too ('third place') and marks neither reading common — apart. 七節
    # ナナフシ: the insect is usually written in kana, so the kanji spell 'seven sections' — apart. 二十歳 はたち: read
    # にじゅっさい too, but JMdict marks はたち common, and the archaic はたとせ reads nothing — joined. 一期 イチゴ
    # 'one's lifetime' is marked common, but JMdict lists 一期 いっき 'one term' as a word of its own — apart. (The
    # entries are abridged from JMdict, by the EDRDG, CC BY-SA 4.0.)
    numerals = {w: _words(brd, tagger, w) for w in JMDICT_NUMERALS}
    counters, _named = brd.counters_of(numerals)
    test = brd.NumeralTest(numerals, JMDICT_NUMERALS, counters)
    clauses = {w: test.clause(w) for w in ("三位", "七節", "二十歳", "一期")}
    assert set(clauses.values()) == {"not a count"}
    assert test.reads_as_count_by("二十歳", "ニジュッサイ") and not test.reads_as_count_by("二十歳", "ハタチ")
    headwords = {"三位": ("サンミ", 1), "七節": ("ナナフシ", 2), "二十歳": ("ハタチ", 3), "一期": ("イチゴ", 4)}
    hatachi = [("はたち", ("ichi1",), ()), ("にじゅっさい", (), ("二十歳",))]
    entries = [_entry([("三位", ())], [("さんみ", (), ()), ("さんい", (), ())], [((), "third place")]),
               _entry([("七節", ())], [("ななふし", (), ())], [(("uk",), "walking stick")]),
               _entry([("二十歳", ("ichi1",))], hatachi, [((), "20 years old")]),
               _entry([("二十歳", ())], [("はたとせ", (), ())], [(("arch",), "twenty years")]),
               _entry([("一期", ("news1",))], [("いちご", ("news1",), ())], [((), "one's lifetime")]),
               _entry([("一期", ())], [("いっき", (), ())], [((), "one term")])]
    _jmdict_of(brd, entries, tmp_path, monkeypatch)
    assert set(brd.jmdict_counts(test, clauses, headwords)) == {"三位", "七節", "一期"}
    # unmarked, 二十歳's はたち would be one reading among counts: apart too
    entries[2] = _entry([("二十歳", ())], [("はたち", (), ()), ("にじゅっさい", (), ("二十歳",))], [((), "20 years old")])
    assert set(brd.jmdict_counts(test, clauses, headwords)) == {"三位", "七節", "一期", "二十歳"}
    # without JMdict's file nothing is checked: every word the lists read as no count joins
    monkeypatch.setattr(brd, "JMDICT", str(tmp_path / "missing.gz"))
    assert brd.jmdict_counts(test, clauses, headwords) == {}


# --- Verb + verb --------------------------------------------------------------------------------------------------- #

def test_a_second_verb_is_grammar_where_it_follows_a_verbal_noun_as_often_as_the_aspect_verbs_do(brd):
    # Uses after a verb's stem and, of those, after a verbal noun + し (勉強し始める). The aspect verbs sit at or above
    # the cut and the word-making ones (出す among them: 走り出す joins) below; a verb met fewer than 20 times makes words.
    shares = {"始める": (100, 12), "続ける": (100, 15), "終わる": (100, 4), "終える": (100, 6), "過ぎる": (100, 7),
              "込む": (100, 0), "上げる": (100, 0), "付ける": (100, 0), "回す": (100, 1), "出す": (100, 2),
              "合う": (100, 50), "慣れる": (100, 0), "損ねる": (5, 5)}
    counts = {"vv": Counter({v: n for v, (n, _m) in shares.items()}),
              "vv_noun": Counter({v: m for v, (_n, m) in shares.items()})}
    grammar, cut, table, (low, high) = brd.aspect_verbs(counts)
    assert grammar == {"始める", "続ける", "終わる", "終える", "過ぎる", "合う"}
    assert low == pytest.approx(0.02) and high == pytest.approx(0.04) and cut == high
    assert table["損ねる"] == (5, 5, 1.0) and "損ねる" not in grammar


def test_the_cut_sits_at_the_lowest_aspect_verb_so_a_second_verb_in_the_gap_makes_words(brd):
    # The cut is 終わる's share, not the middle of the gap below it: a second verb in the gap — 掛かる at 3% here —
    # makes words (斬りかかる joins) while every aspect verb stays grammar.
    shares = {"始める": (100, 12), "続ける": (100, 15), "終わる": (100, 4), "終える": (100, 6), "過ぎる": (100, 7),
              "込む": (100, 0), "上げる": (100, 0), "付ける": (100, 0), "回す": (100, 1), "出す": (100, 2),
              "掛かる": (100, 3)}
    counts = {"vv": Counter({v: n for v, (n, _m) in shares.items()}),
              "vv_noun": Counter({v: m for v, (_n, m) in shares.items()})}
    grammar, cut, _table, (_low, high) = brd.aspect_verbs(counts)
    assert cut == high and "掛かる" not in grammar and "終わる" in grammar


def test_a_verb_plus_verb_is_keyed_by_its_first_verb_as_written_and_its_second_dictionary_form(brd, tagger):
    assert brd.compound_shape(_words(brd, tagger, "走り出す"), "走り出す") == "V"
    # する is never a first verb: 勉強し始める is grammar, never a candidate
    assert brd.compound_shape(_words(brd, tagger, "し始める"), "し始める") is None


# --- Shapes, plurals, and a compound's affixes ------------------------------------------------------------------- #

@pytest.mark.parametrize("word, kind", [
    ("上層部", "N"), ("日本語", "N"),        # a place is a part
    ("一生懸命", "N"), ("自信満々", "N"),    # a な-word of its own is a part
    ("二十歳", "Q"), ("十人十色", "Q"),
    ("バカみたい", None),                     # a grammar stem is no part
])
def test_the_kinds_of_compound_a_headword_read_alone_makes(brd, tagger, word, kind):
    assert brd.compound_shape(_words(brd, tagger, word), word) == kind


def test_a_plural_is_never_a_compound_as_the_list_reads_it(brd, tagger):
    # 先生方 is センセイガタ in the lists (the tagger reads 方 ホウ there); 相手方 アイテカタ is a word of its own.
    assert brd.plural(_words(brd, tagger, "先生方"), "センセイガタ")
    assert not brd.plural(_words(brd, tagger, "相手方"), "アイテカタ")


def test_a_word_the_tagger_reads_whole_is_never_a_compound(brd, tagger):
    # 見える is one word to UniDic. A sentence may cut it み + える, but a table word keyed 見える ミエル with the parts
    # 見る + 得る would make every 見える look like that compound; 上層部 is read in pieces, a compound.
    table = {"見える": ["見える", "ミエル", "V", 0, []], "上層部": ["上層部", "ジョウソウブ", "N", 0, []]}
    assert brd.own_words(tagger, table, {}) == ["見える"]
    # no word is made of itself: 教える read as 教える + 得る
    table = {"教える": ["教える", "オシエル", "V", 0, [["教える", "オシエル", 1], ["得る", "エル", 1]]],
             "走り出す": ["走り出す", "ハシリダス", "V", 0, [["走る", "ハシル", 1], ["出す", "ダス", 1]]]}
    assert brd.own_parts(table) == ["教える"]


def test_a_kana_verb_compound_jmdict_knows_only_as_another_word_is_no_compound(brd, tmp_path, monkeypatch):
    # The tagger reads the kana きおく alone as 来 + 置く, a verb + verb; JMdict lists きおく as 記憶 'memory', a noun
    # that takes する (n, vs, vt) — never a verb of its own: no compound. とりかかる JMdict lists as a verb (v5r):
    # kept. 滅びゆく JMdict lists only as a noun's modifier (adj-f), but its kanji say which verbs it holds: kept.
    # ほえだす, a kana spelling JMdict doesn't list here, keeps its entry. (Entries abridged from JMdict, by the EDRDG,
    # CC BY-SA 4.0.)
    table = {"きおく": ["きおく", "キオク", "V", 0, []], "とりかかる": ["とりかかる", "トリカカル", "V", 0, []],
             "滅びゆく": ["滅びゆく", "ホロビユク", "V", 0, []], "ほえだす": ["ほえだす", "ホエダス", "V", 0, []],
             "上層部": ["上層部", "ジョウソウブ", "N", 0, []]}
    entries = [_entry([("記憶", ("ichi1",))], [("きおく", ("ichi1",), ())], [((), "memory")], ("n", "vs", "vt")),
               _entry([("取り掛かる", ())], [("とりかかる", (), ())], [((), "to set about")], ("v5r", "vi")),
               _entry([("滅びゆく", ())], [("ほろびゆく", (), ())], [((), "doomed")], ("adj-f",))]
    _jmdict_of(brd, entries, tmp_path, monkeypatch)
    assert brd.kana_non_verbs(table) == ["きおく"]
    # a verb's class in any sense is enough: a kana word JMdict lists as a noun and as a verb stays
    entries[0] = _entry([("記憶", ())], [("きおく", (), ())], [((), "memory")], ("n", "v5k"))
    assert brd.kana_non_verbs(table) == []
    # without JMdict's file nothing is checked
    monkeypatch.setattr(brd, "JMDICT", str(tmp_path / "missing.gz"))
    assert brd.kana_non_verbs(table) == []


def test_a_compound_and_its_affixes_make_a_word_of_the_affix_table(brd, tagger):
    # 同性愛者: no affix join makes it from 同性 + 愛 + 者, but the compound 同性愛 takes the suffix 者 — the
    # tokenizer's order, compound first.
    compounds = {"同性愛": ["同性愛", "ドウセイアイ", "N", 0, []]}
    headwords = {"同性愛者": ("ドウセイアイシャ", 1), "同性愛": ("ドウセイアイ", 2)}
    assert brd.affix_pass_two(tagger, headwords, {}, compounds) == {"同性愛者": ["同性愛者", "ドウセイアイシャ"]}
    assert brd.affix_pass_two(tagger, headwords, {}, {}) == {}          # no compound: no word


# --- The in-text pass: words the text writes as words ------------------------------------------------------------ #
# Made-up lines, read the way the pass reads its reference text. Each tests one piece: the runs kept, the guards, the
# words a verb's stem may stand in, and a new such word's parts.
IN_TEXT_LINES = [
    "この出来損ないの計画はもう捨てよう。",       # 出来 + 損ない: two nouns, apart
    "駅での待ち時間はいつも長い。",              # 待ち (待つ's stem) + 時間
    "上層部の決定に従う。",                      # joined by the tables: no evidence
    "経済成長期の日本。",                        # 成長 + 期 inside a word the tables join
    "個人情報保護の法律。",                      # 情報 + 保護 across one
    "昨日は夜更けまで起きていた。",              # 夜更け read as one word
    "藩の中屋敷に住む。",                        # 中 + 屋敷 — but 中屋敷 alone is one word
    "今頭が痛い。",                              # 今 + 頭: a compound's shape alone, which the build decided
    "大事なマイルストーンだ。",                  # マイル + ストーン: katakana alone
    "この先は通行止めです。",                    # 通行 + 止め (nouns); alone 通行 + 止める (a stem)
    "ただの見間違いだった。",                    # 見 + 間違い as nouns once...
    "それは見間違いだ。", "見間違いかもしれない。", "見間違いでした。",   # ...and three times 見る's stem + 間違い
]
IN_TEXT_WORDS = {"出来損ない": "デキソコナイ", "待ち時間": "マチジカン", "上層部": "ジョウソウブ", "成長期": "セイチョウキ",
                 "情報保護": "ジョウホウホゴ", "夜更け": "ヨフケ", "中屋敷": "ナカヤシキ", "今頭": "イマガシラ",
                 "マイルストーン": "マイルストーン", "通行止め": "ツウコウドメ", "見間違い": "ミマチガイ"}


def _in_text_tables(brd):
    """The tables the pass reads with (those of the headwords read alone): 上層部, 経済成長期, 個人情報 and 待ち時間."""
    table = {w: [w, r, "N", 0, []] for w, r in (("上層部", "ジョウソウブ"), ("経済成長期", "ケイザイセイチョウキ"),
                                               ("個人情報", "コジンジョウホウ"), ("待ち時間", "マチジカン"))}
    return {"table": table, "compounds": {w: e[:4] for w, e in table.items()}, "joins": {}, "ogo": {},
            "named": frozenset()}


def _read_in_text(brd, tmp_path, monkeypatch, alone, targets, lines=IN_TEXT_LINES):
    """What `in_text_readings` returns for `lines`, read in this process (no pool). A worker sets the counters the
    build is making on reference_data: put back after the test."""
    path = tmp_path / "text.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(reference_data, "_counters", reference_data._counters)
    brd._in_text_init(frozenset(targets), alone["joins"], alone["compounds"], alone["named"])
    runs, examples, whole = brd._in_text_file(str(path))
    return {"runs": runs, "examples": examples, "whole": whole, "files": 1, "seconds": 0.0}


def test_the_in_text_pass_keeps_only_the_runs_the_tables_leave_apart(brd, tmp_path, monkeypatch):
    alone = _in_text_tables(brd)
    read = _read_in_text(brd, tmp_path, monkeypatch, alone, IN_TEXT_WORDS)
    runs = {(word, kind): n for (word, kind, _shape), n in read["runs"].items()}
    assert runs[("出来損ない", "N")] == 1 and runs[("待ち時間", "S")] == 1
    assert runs[("通行止め", "N")] == 1 and runs[("見間違い", "N")] == 1 and runs[("見間違い", "S")] == 3
    # a run the tables join, one inside a word they join, one across one: no evidence
    assert not {w for w, _k in runs} & {"上層部", "成長期", "情報保護"}
    # the words of each run as the text reads them, and the line they came from (a window around them)
    shape = next(s for (w, k, s) in read["runs"] if w == "出来損ない")
    assert [t[4] for t in shape] == ["出来", "損ない"] and [t[0] for t in shape] == ["名詞", "名詞"]
    assert read["examples"][("出来損ない", shape)] == [IN_TEXT_LINES[0]]
    # a word the text reads as one word, with its reading
    assert read["whole"][("夜更け", "ヨフケ")] == 1


def test_the_in_text_words_their_guards_and_the_words_a_stem_may_stand_in(brd, tagger, tmp_path, monkeypatch):
    alone = _in_text_tables(brd)
    words = dict(IN_TEXT_WORDS, 郵便受け="ユウビンウケ")
    headwords = {w: (r, n) for n, (w, r) in enumerate(words.items(), 1)}
    # 郵便 + 受け: two nouns here, and read as one word elsewhere (as 夜更け is in the test above)
    read = _read_in_text(brd, tmp_path, monkeypatch, alone, words, IN_TEXT_LINES + ["郵便受けの中。"])
    read["whole"][("郵便受け", "ユウビンウケ")] += 1
    monkeypatch.setattr(brd, "in_text_readings", lambda *args, **kwargs: read)
    # JMdict lists these as nouns (待ち時間, already in the table, too); 郵便受け is never asked
    nouns = {"出来損ない": "できそこない", "通行止め": "つうこうどめ", "見間違い": "みまちがい", "待ち時間": "まちじかん"}
    _jmdict_of(brd, [_entry([(w, ())], [(r, (), ())], [((), "a noun")]) for w, r in nouns.items()], tmp_path, monkeypatch)
    found = brd.in_text_words(tagger, headwords, {}, alone)
    # the words the text writes as nouns, each with the words of its commonest run of nouns for its parts
    assert list(found["nouns"]) == sorted(["出来損ない", "通行止め", "見間違い"])
    assert [(brd._read(w), w.feature.pos1) for w in found["nouns"]["出来損ない"]] == [("出来", "名詞"), ("損ない", "名詞")]
    assert [brd._read(w) for w in found["nouns"]["見間違い"]] == ["見", "間違い"]
    # kept out: read whole alone (中屋敷), read whole in the text (郵便受け), a compound's shape alone (今頭 — the even
    # odds decide it), katakana alone (マイルストーン — the katakana-name rule's)
    assert found["refused"] == {"read whole alone": ["中屋敷"], "read whole in the text": ["郵便受け"],
                                "a compound's shape alone": ["今頭"], "katakana alone": ["マイルストーン"]}
    # a verb's stem may stand in 待ち時間 (in the table, written with 待つ's stem), 出来損ない and 通行止め (alone 出来る
    # + 損なう, 通行 + 止める: a card's word) and 見間違い (見る's stem, its commonest reading — whose words it takes: 見,
    # read as the verb, + 間違い); the others keep the parts they have
    assert set(found["stems"]) == {"待ち時間", "出来損ない", "通行止め", "見間違い"}
    assert found["stems"]["待ち時間"] is found["stems"]["出来損ない"] is found["stems"]["通行止め"] is None
    assert [(w.surface, w.feature.pos1, w.feature.lemma) for w in found["stems"]["見間違い"]] == \
        [("見", "動詞", "見る"), ("間違い", "名詞", "間違い")]
    # without JMdict no word takes the mark; the nouns are found all the same
    monkeypatch.setattr(brd, "JMDICT", str(tmp_path / "missing.gz"))
    found = brd.in_text_words(tagger, headwords, {}, alone)
    assert found["stems"] == {} and len(found["nouns"]) == 3


def test_jmdict_says_which_words_are_nouns(brd, tmp_path, monkeypatch):
    # A noun: a sense that is a common noun, an adverbial or temporal one, or one used as a suffix (出来損ない n, 思い通り
    # adj-na and n). 予想通り is listed only as an adverb: no noun. (Entries abridged from JMdict, EDRDG, CC BY-SA 4.0.)
    entries = [_entry([("出来損ない", ())], [("できそこない", (), ())], [((), "failure")]),
               _entry([("思い通り", ())], [("おもいどおり", (), ())], [((), "as one likes")], ("adj-na", "n")),
               _entry([("予想通り", ())], [("よそうどおり", (), ())], [((), "as expected")], ("adv",))]
    _jmdict_of(brd, entries, tmp_path, monkeypatch)
    jmdict_flags = sys.modules["jmdict_flags"]
    index = jmdict_flags.index(entries)
    assert jmdict_flags.lists_as_noun(index, "出来損ない", "デキソコナイ")
    assert jmdict_flags.lists_as_noun(index, "思い通り", "オモイドオリ")
    assert not jmdict_flags.lists_as_noun(index, "予想通り", "ヨソウドオリ")
    assert not jmdict_flags.lists_as_noun(index, "出来損ない", "デキゾコナイ")       # another reading: not this word


def test_the_mark_goes_on_the_table_words_it_was_found_for_and_into_the_dictionary_table(brd, tmp_path, monkeypatch):
    table = {"待ち時間": ["待ち時間", "マチジカン", "N", 0, [["待ち", "マチ", 1], ["時間", "ジカン", 1]]],
             "上層部": ["上層部", "ジョウソウブ", "N", 0, [["上層", "ジョウソウ", 1], ["部", "ブ", 1]]]}
    _jmdict_of(brd, [], tmp_path, monkeypatch)
    monkeypatch.setattr(brd, "TITLES", str(tmp_path / "no-titles.txt"))
    flags, _ogo, _created, _skipped = brd.dictionary_flags(table, {}, ["待ち時間", "出来損ない"])
    assert flags == {"待ち時間": 8}                      # 出来損ない isn't in this table: nothing to mark
    out = tmp_path / "dictionary_data.py"
    monkeypatch.setattr(brd, "DICTIONARY_OUTPUT", str(out))
    brd.write_dictionary_data(flags, {}, "2026-09-28")
    spec = importlib.util.spec_from_file_location("written_dictionary_data_stems", str(out))
    written = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(written)
    assert written.compound_flags() == {"待ち時間": 8}
    assert "8 a noun JMdict lists that the text" in written.__doc__


def test_a_new_marked_word_is_parted_as_the_text_mostly_writes_it(brd, tagger, tmp_path, monkeypatch):
    # 立ち位置 is mostly 立ち (立つ's stem) + 位置 in text: its parts are the verb a learner knows and 位置 — never the
    # rare noun 立ち that a reading as two nouns shows.
    lists = _lists(brd, tmp_path, monkeypatch, [["立つ", "タツ"], ["位置", "イチ"], ["立ち位置", "タチイチ"]])
    table = {"立ち位置": ["立ち位置", "タチイチ", "N", 0, []]}
    words = [w for w in tagger("自分の立ち位置を考える。") if w.surface in ("立ち", "位置")]
    brd.compound_parts(table, {"立ち位置": words}, lists)
    assert table["立ち位置"][4] == [["立つ", "タツ", 1], ["位置", "イチ", 1]]


# --- What the build reads ------------------------------------------------------------------------------------------ #


# --- What the build reads ------------------------------------------------------------------------------------------ #

def test_the_build_reads_with_the_default_switches_whatever_settings_json_says(brd, tagger, monkeypatch):
    # Shared data never follows the builder's own settings: with the phrases-and-titles switch off in LOGIC, a
    # flagged compound would stay in pieces — pinned to the defaults, the build reads it joined.
    table = {"予想通り": ["予想通り", "ヨソウドオリ", "N", 1, []]}
    monkeypatch.setitem(analyzer.LOGIC, "phrases_and_titles", False)
    monkeypatch.setitem(analyzer.LOGIC, "names_katakana", False)
    assert [w.surface for w in brd.read_words(tagger, "予想通りだ", {}, table)][0] == "予想"
    brd.pin_parsing_defaults()
    assert analyzer.LOGIC["names_katakana"] is True
    assert [w.surface for w in brd.read_words(tagger, "予想通りだ", {}, table)][0] == "予想通り"


def test_a_katakana_loanword_is_never_a_title(brd, tmp_path, monkeypatch):
    # JMnedict's product names include loanwords spelled in katakana alone: one word with the switch off too.
    titles = tmp_path / "org-product.txt"
    titles.write_text("# a comment\nもののけ姫\nソフトバンク\n", encoding="utf-8")
    monkeypatch.setattr(brd, "TITLES", str(titles))
    assert brd.titles({"もののけ姫": [], "ソフトバンク": [], "上層部": []}) == {"もののけ姫": 3}


def test_the_build_marks_the_katakana_compounds_jmdict_does_not_list(brd, tmp_path, monkeypatch):
    # ビルデ (ビル + デ) is no word of JMdict's: marked 4, so it gives way to a katakana name around it (ビルデイング).
    # フジテレビ is listed, and 上層部 — missing here — is no katakana word: neither is marked. The table written for
    # the app hands the mark back. (The entry is abridged from JMdict, by the EDRDG, CC BY-SA 4.0.)
    table = {"ビルデ": ["ビルデ", "ビルデ", "N", 0, [["ビル", "ビル", 1], ["デ", "デ", 0]]],
             "フジテレビ": ["フジテレビ", "フジテレビ", "N", 0, [["フジ", "フジ", 1], ["テレビ", "テレビ", 1]]],
             "上層部": ["上層部", "ジョウソウブ", "N", 0, [["上層", "ジョウソウ", 1], ["部", "ブ", 1]]]}
    _jmdict_of(brd, [_entry([], [("フジテレビ", (), ())], [(("company",), "Fuji TV")])], tmp_path, monkeypatch)
    monkeypatch.setattr(brd, "TITLES", str(tmp_path / "no-titles.txt"))
    flags, _ogo, _created, skipped = brd.dictionary_flags(table, {})
    assert flags == {"ビルデ": 4} and not skipped
    out = tmp_path / "dictionary_data.py"
    monkeypatch.setattr(brd, "DICTIONARY_OUTPUT", str(out))
    brd.write_dictionary_data(flags, {}, "2026-09-28")
    spec = importlib.util.spec_from_file_location("written_dictionary_data", str(out))
    written = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(written)
    assert written.compound_flags() == {"ビルデ": 4} and written.ogo_joins() == {}
    assert "4 a word spelled in katakana alone that JMdict doesn't list" in written.__doc__


def test_the_compact_tables_come_back_as_the_seam_shapes(brd):
    table = {"上層部": ["上層部", "ジョウソウブ", "N", 0, [["上層", "ジョウソウ", 0], ["部", "ブ", 1]]],
             "生徒会": ["生徒会", "セイトカイ", "N", 0, [["生徒", "セイト", 1], ["会", "カイ", 1]]],
             "予定どおり": ["予定通り", "ヨテイドオリ", "N", 0, [["予定", "ヨテイ", 1], ["通り", "ドオリ", 1]]]}
    joins = brd.compact_compounds(table)
    assert joins["上層部"][0] == "" and joins["予定どおり"][0] == "予定通り"
    parts = brd.compact_parts(table)
    assert len(parts["parts"]) == 6 and [parts["parts"][i] for i in parts["of"]["上層部"]] == table["上層部"][4]


# --- Aliases ------------------------------------------------------------------------------------------------------ #

def test_an_alias_never_takes_a_stretched_spelling_the_tagger_reads_as_its_word(brd, tagger):
    # The analyzer reads a stretched vowel as its word (シリ〜ズ is シリーズ, ド〜ン ドーン, and しゃーない without its ー is
    # しゃない, read 社内), so a list's stretched spelling, ranked better than the word's own, used to become the word's
    # "common spelling". A spelling UniDic lists with its ー (はーい for はい) and a katakana ー (シリーズ) are no stretch.
    for word in ("シリ〜ズ", "シリ～ズ", "ア〜ン", "ド〜ン", "しゃーない", "すごーーい", "暗ーい"):
        assert brd.stretched(tagger, word), word
    for word in ("シリーズ", "ラーメン", "はーい", "する", "しぃ", "食べる"):
        assert not brd.stretched(tagger, word), word
    aliases = brd.build_aliases(tagger, [{"シリ〜ズ": 1, "ド〜ン": 2, "しゃーない": 3, "すごーーい": 4, "する": 5, "しぃ": 6},
                                         {"シリーズ": 1, "しゃない": 2}])
    assert aliases == {"為る": "する", "社内": "しゃない"}
    assert brd.build_aliases(tagger, [{}]) == {}


# --- The shipped tables ---------------------------------------------------------------------------------------------- #

def test_the_shipped_compound_table_names_each_word_its_kind_and_its_parts():
    joins, parts = reference_data.compound_joins(), reference_data.compound_parts()
    # each entry a tuple (smaller than the list it is stored as); flags 0 — the dictionaries' marks, which the
    # tokenizer ORs in, are app/dictionary_data.py's
    assert joins["上層部"] == ("上層部", "ジョウソウブ", "N", 0)
    assert joins["二十歳"][1:3] == ("ハタチ", "Q") and joins["走り出す"][2] == "V"
    assert [p[0] for p in parts["上層部"]] == ["上層", "部"]
    # a part met in many compounds is one list in memory
    assert parts["上層部"][1] is parts[next(w for w, ps in parts.items() if w != "上層部" and ps[-1] == ["部", "ブ", 1])][-1]
    for word in ("三日", "十円玉", "先生方", "食べ始める", "今頭", "見える", "教える"):
        assert word not in joins, word      # a count, a plural, grammar, a coincidence, words UniDic reads whole
    # JMdict reads 三位 as a count too (さんい 'third place') and marks no reading common: apart; 二十歳 joins
    assert "三位" not in joins and "一期" not in joins
    # a second verb between the word-making verbs and 終わる makes words; きおく (記憶) is no verb + verb
    assert joins["斬りかかる"][2] == "V" and joins["言い忘れる"][2] == "V" and "きおく" not in joins
    for word, entry in joins.items():      # no compound among its own parts
        assert all((p[0], p[1]) != (entry[0], entry[1]) for p in parts[word]), word
    assert "人" in reference_data.counters()


def test_the_dictionary_tables_are_the_same_object_on_every_call():
    # The tokenizer merges them by identity, once: a new table per call would rebuild the merge on every line.
    assert dictionary_data.compound_flags() is dictionary_data.compound_flags()
    assert dictionary_data.ogo_joins() is dictionary_data.ogo_joins()
    assert reference_data.compound_joins() is reference_data.compound_joins()
    assert reference_data.compound_parts() is reference_data.compound_parts()
    assert dictionary_data.compound_flags().get("もののけ姫") == 3
    # a katakana compound JMdict doesn't list is marked 4 (never the switch's 1); one it lists (フジテレビ) isn't
    assert dictionary_data.compound_flags().get("ビルデ") == 4 and "フジテレビ" not in dictionary_data.compound_flags()
