# SPDX-License-Identifier: GPL-3.0-or-later
"""パターン lookup and formatter (Patterns_Spec.md WP-P3) — from a card's word to its field.

The formatter answers to `Anki_Card_Layout_Spec.md` §5, which is binding: the card's template files
each line by its content (`%` → particles, `×N` → collocations, anything else → frames) and splits
items on `·` / `・` / a full-width space / two spaces. So the tests parse the output back the way the
template does, and an item holding a separator must be dropped, never split.

The lookup answers to §7. Its real traps are pinned with the measured cases: 気 (キ 3,848 / ゲ 559
in the user's library) for homographs, 引きずる written for UniDic's 引き摺る, and 感じる, which
UniDic files under 感ずる (F14).
"""
import os
import re
import sqlite3

import pytest

from app.path_utils import get_data_path
from modules.junban import patterns as pt
from modules.junban import patterns_build as pb
from modules.junban.patterns_store import open_store

CANONICAL = ("<div>が 26% · は 20% · を 18% · に 12%</div>"
             "<div>気持ち悪い ×26 · 気持ちがいい ×5</div>"
             "<div>そんな〜 · という〜 · ちょっと〜</div>")


@pytest.fixture(scope="module")
def tokenize():
    return pt.tokenizer()


@pytest.fixture
def make_store(tmp_path):
    """Build an exact store from rows; every store is closed at teardown (Windows keeps an open
    SQLite file locked, and tmp_path cleanup would trip over it)."""
    opened = []

    def make(lemmas=(), aliases=(), patterns=(), floor=12, tokens=None):
        db = str(tmp_path / f"patterns_{len(opened)}.db")
        meta = {"floor": floor} if tokens is None else {"floor": floor, "tokens": tokens}
        pb.write_rows(db, list(lemmas), list(aliases), list(patterns), meta)
        opened.append(open_store(db))
        return opened[-1]
    yield make
    for store in opened:
        store.close()


def _template_kinds(field):
    """File each line the way the card template does (§5): by its `pat-<kind>` class; a line
    without one by content, split with the template's own regex (`<br>`, any `<div …>` / `</div>`,
    `<p …>`, newline) — `%` particles, `×N` collocations, anything else frames."""
    if 'class="pat-' in field:
        return re.findall(r'class="pat-(particle|form|colloc|frame|register)', field)
    kinds = []
    for line in filter(None, (l.strip() for l in re.split(r"<br\s*/?>|</?div[^>]*>|</?p[^>]*>|\n", field))):
        if "%" in line:
            kinds.append("particle")
        elif "×" in line or re.search(r"x\d", line):
            kinds.append("colloc")
        else:
            kinds.append("frame")
    return kinds


# --- the formatter ------------------------------------------------------------------------------ #
def test_the_formatter_writes_the_layouts_lines():
    # The layout's canonical example (Anki_Card_Layout_Spec §5), as written since the user's changes of
    # 2026-09-24: each line names its kind, only the two commonest particles, 〜 on the word's side,
    # and no counts on the collocations.
    lines = {"particle": [("が", .26), ("は", .20), ("を", .18), ("に", .12)],
             "colloc": [("{w}悪い", 26), ("{w}がいい", 5)],
             "frame": [("そんな〜", 9), ("という〜", 7), ("ちょっと〜", 4)]}
    assert pt.format_patterns(lines, "気持ち") == ('<div class="pat-particle">〜が 26% · 〜は 20%</div>'
                                                 '<div class="pat-colloc">気持ち悪い · 気持ちがいい</div>'
                                                 '<div class="pat-frame">そんな〜 · という〜 · ちょっと〜</div>')


def test_the_output_parses_back_as_exactly_the_kinds_in_order():
    # The spec's canonical example has no classes, so an older template's content rule still files it.
    assert _template_kinds(CANONICAL) == ["particle", "colloc", "frame"]
    lines = {"particle": [("が", .26)], "form": [("{w}する", .4)], "colloc": [("{w}悪い", 26)],
             "frame": [("そんな〜", 3)]}
    assert _template_kinds(pt.format_patterns(lines, "期待")) == ["particle", "form", "colloc", "frame"]


def test_particles_show_which_side_of_the_word_they_sit_on():
    # The user (2026-09-24) asked which side a particle is on. After a noun (探検に出かける), before a
    # verb or an adjective (…を受ける, …が深い) — the 〜 stands for the word, as in a frame.
    assert pt.format_patterns({"particle": [("に", .34)], "side": "after"}, "探検") == \
        '<div class="pat-particle">〜に 34%</div>'
    assert pt.format_patterns({"particle": [("を", .86)], "side": "before"}, "受ける") == \
        '<div class="pat-particle">を〜 86%</div>'


def test_a_collocation_shows_the_cards_own_spelling():
    # UniDic files 感じる under 感ずる; the card says 感じる, so the item must too.
    assert pt.format_patterns({"colloc": [("影響を{w}", 3)]}, "感じる") == \
        '<div class="pat-colloc">影響を感じる</div>'


def test_an_item_holding_a_separator_is_dropped_never_split():
    # A katakana name with ・ would otherwise break a line in two; % would file a frame as particles.
    lines = {"frame": [("アイリス・リー〜", 5), ("その〜", 4), ("100%〜", 3)],
             "colloc": [("{w}がいい", 5)]}
    field = pt.format_patterns(lines, "気持ち")
    assert field == '<div class="pat-colloc">気持ちがいい</div><div class="pat-frame">その〜</div>'
    # ...and a word that itself holds a separator loses every item it would appear in.
    assert pt.format_patterns({"colloc": [("{w}が来る", 5)]}, "マイン・ルッツ") == ""


def test_the_source_rides_as_a_second_class():
    # The template files a line by its kind class and reads the source class only for the quiet dot
    # after パターン — so a source changes no line's kind.
    lines = {"particle": [("が", .26), ("を", .18)], "colloc": [("{w}悪い", 26)], "frame": [("そんな〜", 3)]}
    field = pt.format_patterns(lines, "気持ち", source="balanced")
    assert field.count(" pat-src-balanced\"") == 3
    assert _template_kinds(field) == ["particle", "colloc", "frame"]
    assert pt.format_patterns(lines, "気持ち") == field.replace(" pat-src-balanced", "")


def test_a_card_is_filled_from_the_first_source_that_can(make_store, tokenize):
    # conversational -> balanced -> library (user, 2026-09-24). A word only the user's own library
    # knows (a character name, a niche word) still gets its lines — marked as the library's.
    def store_with(word, reading):
        key = (word, reading)
        return make_store(lemmas=[(*key, word, "名詞", 400)], aliases=[(word, *key, 400)],
                          patterns=[(*key, "frame", "大きな〜", 5, 9.0)], floor=12)
    conv = store_with("影響", "エイキョウ")
    lib = store_with("鎖国", "サコク")
    stores = [("conversational", conv), ("balanced", None), ("library", lib)]
    assert pt.patterns_from_sources("影響", "", stores, tokenize) == (
        '<div class="pat-frame pat-src-conversational">大きな〜</div>', None, "conversational")
    assert pt.patterns_from_sources("鎖国", "", stores, tokenize) == (
        '<div class="pat-frame pat-src-library">大きな〜</div>', None, "library")
    assert pt.patterns_from_sources("冒険", "", stores, tokenize) == ("", "not found", None)


def test_the_shareable_database_serves_a_user_without_the_personal_ones(make_store, tokenize, monkeypatch):
    # Patterns_Spec §18: another user has the shared database and their own library; the developer has
    # the two personal ones and no shared one. One order serves both — shared after the personal ones,
    # before the library — and a card says which it came from.
    assert pt.SOURCE_ORDER == ("conversational", "balanced", "shared", "library")
    key = ("影響", "エイキョウ")
    shared = make_store(lemmas=[(*key, "影響", "名詞", 400)], aliases=[("影響", *key, 400)],
                        patterns=[(*key, "frame", "大きな〜", 5, 9.0)], floor=20)
    stores = [("conversational", None), ("balanced", None), ("shared", shared), ("library", None)]
    assert pt.patterns_from_sources("影響", "", stores, tokenize) == (
        '<div class="pat-frame pat-src-shared">大きな〜</div>', None, "shared")
    opened = []
    monkeypatch.setattr("modules.junban.patterns_store.open_store",
                        lambda language, name=None: opened.append(name))
    pt.open_sources("ja")
    assert opened == ["conversational", "balanced", "shared", None]      # None: the library's own file


def test_a_card_takes_the_first_source_with_four_collocations_else_the_richest(make_store, tokenize):
    # The user (2026-09-24): "4 in total would be nice (if there are)". The fill order still decides
    # between equals; a later source wins only by giving the card more collocations.
    key = ("影響", "エイキョウ")

    def store_with(verbs):
        return make_store(lemmas=[(*key, "影響", "名詞", 400)], aliases=[("影響", *key, 400)],
                          patterns=[(*key, "colloc", f"{{w}}を{v}", 9, 9.0 - i, "C1を")
                                    for i, v in enumerate(verbs)])
    one = store_with(["受ける"])
    four = store_with(["受ける", "与える", "及ぼす", "残す"])
    five = store_with(["受ける", "与える", "及ぼす", "残す", "出す"])
    field, reason, source = pt.patterns_from_sources(
        "影響", "", [("conversational", one), ("balanced", four), ("library", five)], tokenize)
    assert (source, reason, pt._collocations(field)) == ("balanced", None, 4)   # the first with four
    two_a, two_b = store_with(["受ける", "与える"]), store_with(["受ける", "与える"])
    assert pt.patterns_from_sources("影響", "", [("conversational", two_a), ("balanced", two_b),
                                                ("library", one)], tokenize)[2] == "conversational"


def test_no_qualifying_line_leaves_the_field_empty():
    assert pt.format_patterns({"particle": [], "colloc": [], "frame": []}, "我慢") == ""


def test_lines_are_capped_at_two_two_four_three():
    # The user (2026-09-24): the two commonest particles — the ones a learner takes note of, one row
    # on the card — two forms, four collocations, three frames. Each form is a line of its own
    # (Patterns_Quality_Spec decision 1: "they are longer and it looks better to have them on their
    # own line").
    lines = {"particle": [(p, .1) for p in "がをにでとは"],
             "form": [("{w}する", .4), ("{w}だ", .2), ("{w}な", .1)],
             "colloc": [(f"{{w}}{v}", 9) for v in ("受ける", "与える", "及ぼす", "残す", "出る")],
             "frame": [(f"{m}〜", 9) for m in ("大きな", "その", "強い", "悪い")]}
    field = pt.format_patterns(lines, "影響")
    assert [len(line.split(" · ")) for line in re.findall(r"<div[^>]*>(.*?)</div>", field)] == [2, 1, 1, 4, 3]


def test_the_forms_line_shows_how_the_word_itself_is_used(make_store):
    # The fourth line (the user, 2026-09-24): the forms the word takes, as shares of all its uses —
    # 大切 is 大切な 59% and 大切に 20% on the conversational corpus. Two at most, commonest first, in the
    # card's own spelling.
    key = ("大切", "タイセツ")
    store = make_store(lemmas=[(*key, "大切", "形状詞", 1000)], patterns=[
        (*key, "form", "{w}な", 590, None, "W"), (*key, "form", "{w}に", 200, None, "W"),
        (*key, "form", "{w}だ", 140, None, "W")])
    assert pt.format_patterns(pt.lines_for(store, *key), "大切") == \
        '<div class="pat-form">大切な 59%</div><div class="pat-form">大切に 20%</div>'
    # A verb's form is written as the text writes it: 囲まれる, not the card's 囲む.
    verb = ("囲む", "カコム")
    store = make_store(lemmas=[(*verb, "囲む", "動詞", 910)],
                       patterns=[(*verb, "form", "囲まれる", 692, None, "W")])
    assert pt.format_patterns(pt.lines_for(store, *verb), "囲む") == \
        '<div class="pat-form">囲まれる 76%</div>'


def _register_stores(make_store, key, spoken, written, tokens=(42_656_232, 82_547_185)):
    """The two general stores for one word: the balanced corpus contains the conversational one."""
    conv = make_store(lemmas=[(*key, key[0], "名詞", spoken)], aliases=[(key[0], *key, spoken)],
                      floor=20, tokens=tokens[0])
    bal = make_store(lemmas=[(*key, key[0], "名詞", spoken + written)],
                     aliases=[(key[0], *key, spoken + written)], floor=20, tokens=tokens[1])
    return [("conversational", conv), ("balanced", bal), ("library", None)]


def test_a_word_that_leans_hard_toward_writing_says_so(make_store):
    # Measured on the corpora (2026-09-24): 及び 740 spoken / 13,554 written, 設立 507 / 5,208.
    stores = _register_stores(make_store, ("及び", "オヨビ"), 740, 13_554)
    assert pt.register_of(("及び", "オヨビ"), stores) == pt.WRITTEN
    stores = _register_stores(make_store, ("設立", "セツリツ"), 507, 5208)
    assert pt.register_of(("設立", "セツリツ"), stores) == pt.WRITTEN


def test_there_is_no_spoken_tag(make_store):
    # The user's choice (2026-09-24): written only. Subtitles are drama, so やばい (3,105 / 102) leans
    # "spoken" — and so does 海鮮丼 (80 / 1), which is only a show's topic. Neither gets a tag.
    assert pt.register_of(("ヤバい", "ヤバイ"),
                          _register_stores(make_store, ("ヤバい", "ヤバイ"), 3105, 102)) is None
    assert pt.register_of(("海鮮丼", "カイセンドン"),
                          _register_stores(make_store, ("海鮮丼", "カイセンドン"), 80, 1)) is None


def test_most_words_lean_neither_way_and_rare_or_missing_data_says_nothing(make_store):
    # 目: 30,033 / 41,011 — used both ways, no tag. Too few uses, or no general corpus built (another
    # user's machine), and the card says nothing rather than guess.
    assert pt.register_of(("目", "メ"), _register_stores(make_store, ("目", "メ"), 30_033, 41_011)) is None
    assert pt.register_of(("マジ", "マジ"), _register_stores(make_store, ("マジ", "マジ"), 40, 1)) is None
    lonely = [("conversational", None), ("balanced", None), ("library", None)]
    assert pt.register_of(("マジ", "マジ"), lonely) is None


def test_the_register_rides_on_the_field_as_its_own_line(make_store, tokenize):
    # Its own kind of line — a chip on the Lapis card, a plain line anywhere else — and never written
    # alone: a word with nothing else to show keeps an empty field.
    key = ("設立", "セツリツ")

    def stores(patterns=()):
        conv = make_store(lemmas=[(*key, "設立", "名詞", 507)], aliases=[("設立", *key, 507)],
                          floor=20, tokens=42_656_232, patterns=patterns)
        bal = make_store(lemmas=[(*key, "設立", "名詞", 5715)], aliases=[("設立", *key, 5715)],
                         floor=20, tokens=82_547_185)
        return [("conversational", conv), ("balanced", bal), ("library", None)]
    field, reason, source = pt.patterns_from_sources(
        "設立", "", stores([(*key, "form", "{w}する", 152, None, "W")]), tokenize)
    assert (reason, source) == (None, "conversational")
    assert field == ('<div class="pat-form pat-src-conversational">設立する 30%</div>'
                     '<div class="pat-register">書き言葉</div>')
    assert pt.patterns_from_sources("設立", "", stores(), tokenize)[0] == ""


def test_a_name_never_gets_the_written_tag(make_store, tokenize):
    # ユウカ, a character's name (UniDic 固有名詞), is rarer in subtitles than in Wikipedia — a topic,
    # not a register. It was on one of the user's TheBank cards (2026-09-24): 14 spoken / 76 written.
    key = ("ユウカ", "ユウカ")
    conv = make_store(lemmas=[(*key, "ユウカ", "名詞", 14)], aliases=[("ユウカ", *key, 14)], floor=12,
                      tokens=42_656_232, patterns=[(*key, "form", "{w}さん", 12, None, "W")])
    bal = make_store(lemmas=[(*key, "ユウカ", "名詞", 90)], aliases=[("ユウカ", *key, 90)], floor=20,
                     tokens=82_547_185)
    stores = [("conversational", conv), ("balanced", bal), ("library", None)]
    assert pt.register_of(key, stores) == pt.WRITTEN          # the numbers alone would say so
    field, _reason, _source = pt.patterns_from_sources("ユウカ", "", stores, tokenize)
    assert field and "pat-register" not in field


@pytest.mark.parametrize("word, key, chip", [
    ("スドウ", ("スドウ", ""), False),                      # a surname the names layer makes whole: ス + ドウ
    ("リンタロウ", ("リンタロウ", ""), False),              # a given name: リン + タロウ
    ("ハイスペック", ("ハイスペック", "ハイスペック"), True),   # a loanword the tagger reads whole: no name
])
def test_a_name_the_names_layer_makes_whole_never_gets_the_written_tag(make_store, tokenize, word, key, chip):
    # A katakana name no dictionary holds whole (スドウ is ス + ドウ to the tagger) is made one word by the names layer — a
    # word its dictionary lacks, a common noun to it — so UniDic's proper-noun tag alone missed it, and the name took
    # 書き言葉 for being rarer in subtitles than in Wikipedia: a topic, as ユウカ's (above), not a register. A katakana
    # word the tagger knows whole keeps its register.
    conv = make_store(lemmas=[(*key, word, "名詞", 14)], aliases=[(word, *key, 14)], floor=12, tokens=42_656_232,
                      patterns=[(*key, "particle", "が", 5, None, "after", 3)])
    bal = make_store(lemmas=[(*key, word, "名詞", 90)], aliases=[(word, *key, 90)], floor=20, tokens=82_547_185)
    stores = [("conversational", conv), ("balanced", bal), ("library", None)]
    assert pt.register_of(key, stores) == pt.WRITTEN          # the numbers alone would say so
    field, _reason, _source = pt.patterns_from_sources(word, "", stores, tokenize)
    assert field and ("pat-register" in field) == chip


def test_an_adverb_written_in_kana_never_gets_the_written_tag(make_store, tokenize):
    # にこにこ: 119 uses in speech, 1,092 in writing (the rebuilt sets, 2026-09-25) — novels' narration,
    # not written language. The user: no chip on a kana-only adverb. 予め, written with kanji, keeps it.
    def stores(key, pos, spoken, written):
        conv = make_store(lemmas=[(*key, key[0], pos, spoken)], aliases=[(key[0], *key, spoken)], floor=20,
                          tokens=42_118_281, patterns=[(*key, "colloc", "{w}笑う", 30, 9.0, "A1", 12)])
        bal = make_store(lemmas=[(*key, key[0], pos, spoken + written)], aliases=[(key[0], *key, spoken + written)],
                         floor=20, tokens=81_436_180)
        return [("conversational", conv), ("balanced", bal), ("library", None)]
    mimetic = stores(("にこにこ", "ニコニコ"), "副詞", 119, 1092)
    assert pt.register_of(("にこにこ", "ニコニコ"), mimetic) == pt.WRITTEN      # the numbers alone would say so
    field, _reason, _source = pt.patterns_from_sources("にこにこ", "", mimetic, tokenize)
    assert field and "pat-register" not in field
    bookish = stores(("予め", "アラカジメ"), "副詞", 60, 2400)
    field, _reason, _source = pt.patterns_from_sources("予め", "", bookish, tokenize)
    assert '<div class="pat-register">書き言葉</div>' in field


_ME = ("目", "メ")


def test_collocations_are_spread_over_the_ways_the_word_is_used(make_store):
    # The user (2026-09-24): four collocations "from the most useful sections" — how the word is used
    # and what it pairs with. By logDice alone 目's four would all be を + a verb. One per construction
    # first, the commonest construction first; 目で見る is under 5% of 目's collocations, so its high
    # logDice earns it no slot of its own.
    store = make_store(lemmas=[(*_ME, "目", "名詞", 4866)], patterns=[
        (*_ME, "colloc", "{w}を覚ます", 1557, 9.5, "C1を"), (*_ME, "colloc", "{w}を閉じる", 603, 9.2, "C1を"),
        (*_ME, "colloc", "{w}を開ける", 400, 9.0, "C1を"), (*_ME, "colloc", "{w}を逸らす", 300, 8.9, "C1を"),
        (*_ME, "colloc", "{w}が覚める", 951, 8.7, "C1が"), (*_ME, "colloc", "{w}に入る", 500, 8.0, "C1に"),
        (*_ME, "colloc", "{w}の前", 2699, 7.5, "K1"), (*_ME, "colloc", "{w}で見る", 40, 9.9, "C1で")])
    assert pt.format_patterns(pt.lines_for(store, *_ME), "目") == (
        '<div class="pat-colloc">目を覚ます · 目の前 · 目が覚める · 目に入る</div>')


def test_frames_are_spread_the_same_way(make_store):
    # 大きな〜 · 小さな〜 · 色んな〜 say one thing three times; a 連体詞, an adjective and という〜 say three.
    key = ("問題", "モンダイ")
    store = make_store(lemmas=[(*key, "問題", "名詞", 900)], patterns=[
        (*key, "frame", "大きな〜", 50, 9.0, "F1連体詞"), (*key, "frame", "小さな〜", 40, 8.9, "F1連体詞"),
        (*key, "frame", "色んな〜", 30, 8.5, "F1連体詞"), (*key, "frame", "難しい〜", 20, 8.0, "F1形容詞"),
        (*key, "frame", "という〜", 15, 7.0, "F2")])
    assert pt.format_patterns(pt.lines_for(store, *key), "問題") == \
        '<div class="pat-frame">大きな〜 · 難しい〜 · という〜</div>'


def test_a_database_from_the_first_builder_still_reads_in_logdice_order(tmp_path):
    # Builder 1 wrote no `section` column: its rows are one construction, so the order is plain
    # logDice — the panel never breaks on a database built before the spread.
    db = str(tmp_path / "builder1.db")
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE lemma (lemma TEXT, reading TEXT, orth TEXT, pos TEXT, count INTEGER);
        CREATE TABLE alias (orth TEXT, lemma TEXT, reading TEXT, count INTEGER);
        CREATE TABLE pattern (lemma TEXT, reading TEXT, kind TEXT, item TEXT, count INTEGER,
                              logdice REAL);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);""")
    con.executemany("INSERT INTO pattern VALUES (?,?,?,?,?,?)", [
        (*_ME, "colloc", "{w}の前", 2699, 7.5), (*_ME, "colloc", "{w}を覚ます", 1557, 9.5)])
    con.commit()
    con.close()
    store = open_store(db)
    try:
        assert pt.lines_for(store, *_ME)["colloc"] == [("{w}を覚ます", 1557), ("{w}の前", 2699)]
    finally:
        store.close()


def test_particle_shares_are_of_all_the_words_uses(make_store):
    # 〜を 26% on 利用 described 1% of its uses: it was a share of the few uses that had a particle
    # (F1). A share of ALL uses (decision 2), at least 5% of them and at least three uses each.
    key = ("影響", "エイキョウ")
    store = make_store(lemmas=[(*key, "影響", "名詞", 100)], patterns=[
        (*key, "particle", "を", 30, None), (*key, "particle", "が", 8, None),
        (*key, "particle", "で", 4, None), (*key, "particle", "に", 2, None)])
    assert pt.lines_for(store, *key)["particle"] == [("を", .30, None), ("が", .08, None)]   # で 4% < 5%
    rare = make_store(lemmas=[(*key, "影響", "名詞", 40)],
                      patterns=[(*key, "particle", "を", 6, None), (*key, "particle", "が", 2, None)])
    assert pt.lines_for(rare, *key)["particle"] == [("を", .15, None)]                  # が: 2 < 3 uses


# --- the lookup (§7) ---------------------------------------------------------------------------- #
@pytest.fixture
def library_store(make_store):
    return make_store(lemmas=[
        ("気", "キ", "気", "名詞", 3848), ("気", "ゲ", "気", "接尾辞", 559),
        ("引き摺る", "ヒキズル", "引きずる", "動詞", 40), ("感ずる", "カンズル", "感じる", "動詞", 1500),
        ("我慢", "ガマン", "我慢", "名詞", 7),
    ], aliases=[
        ("気", "気", "キ", 3848), ("気", "気", "ゲ", 559),
        ("引きずる", "引き摺る", "ヒキズル", 38), ("引き摺る", "引き摺る", "ヒキズル", 2),
        ("感じる", "感ずる", "カンズル", 900), ("感ずる", "感ずる", "カンズル", 600),
        ("我慢", "我慢", "ガマン", 7),
    ])


def test_expression_reading_decides_a_homograph(library_store, tokenize):
    assert pt.resolve_key("気", "げ", library_store, tokenize) == (("気", "ゲ"), None)


def test_without_a_reading_the_better_evidenced_one_wins(library_store, tokenize):
    assert pt.resolve_key("気", "", library_store, tokenize) == (("気", "キ"), None)


def test_hikizuru_resolves_through_the_alias_table(library_store, tokenize):
    assert pt.resolve_key("引きずる", "ひきずる", library_store, tokenize) == (("引き摺る", "ヒキズル"), None)


def test_kanjiru_resolves_to_unidics_kanzuru(library_store, tokenize):
    # F14: the card's reading かんじる never equals the lemma's カンズル, so step 3 misses and the
    # spelling alone (step 4) finds it.
    assert pt.resolve_key("感じる", "かんじる", library_store, tokenize) == (("感ずる", "カンズル"), None)


@pytest.mark.parametrize("written, key", [
    ("斬新な", ("斬新", "ザンシン")),       # な-adjective written attributively
    ("最後に", ("最後", "サイゴ")),         # adverbial に
    ("深入りする", ("深入り", "フカイリ")),   # する-verb written with its する
])
def test_a_word_written_with_its_na_ni_or_suru_attached_is_still_that_word(make_store, tokenize,
                                                                          written, key):
    # 41 of the user's Lapis notes are written this way; the list keys them without the tail.
    store = make_store(lemmas=[(*key, key[0], "名詞", 40)])
    assert pt.resolve_key(written, "", store, tokenize) == (key, None)


@pytest.mark.parametrize("written, key, item, kind, shown", [
    ("斬新な", ("斬新", "ザンシン"), "{w}な発想", "colloc", "斬新な発想"),
    ("最後に", ("最後", "サイゴ"), "{w}に笑う", "colloc", "最後に笑う"),
    ("深入りする", ("深入り", "フカイリ"), "{w}する", "form", "深入りする 79%"),
])
def test_the_lines_of_a_word_written_with_its_tail_are_filled_with_the_bare_word(make_store, tokenize,
                                                                                 written, key, item, kind, shown):
    # 〜 is the word itself. Filled with the card's word as written, the user's cards read 斬新ななアイデア,
    # 一気にに広まる and 深入りするする 79% — the Japanese goldens found it (2026-09-25). (一気に itself is a word of its
    # own since the dictionary decides — below — so 最後に stands in for the particle に.)
    store = make_store(lemmas=[(*key, key[0], "名詞", 100)],
                       patterns=[(*key, kind, item, 79, None if kind == "form" else 9.5, "W" if kind == "form" else "K3")])
    html, _reason = pt.patterns_for(written, "", store, tokenize)
    assert shown in html and written + written[-1:] not in html and written + "な" not in html.replace(shown, "")


@pytest.mark.parametrize("written, key, item, kind, shown", [
    ("お部屋", ("部屋", "ヘヤ"), "{w}を片付ける", "colloc", "部屋を片付ける"),
    ("俺たち", ("俺", "オレ"), "{w}の家", "colloc", "俺の家"),
    ("優しさ", ("優しい", "ヤサシイ"), "{w}人", "colloc", "優しい人"),
    ("ご案内する", ("案内", "アンナイ"), "{w}する", "form", "案内する 79%"),
])
def test_a_card_with_its_words_own_grammar_takes_the_words_lines(make_store, tokenize, written, key, item, kind,
                                                                  shown):
    # お部屋, 俺たち and 優しさ are 部屋, 俺 and 優しい to the tokenizer (their polite お, plural and さ kept apart), so
    # the card takes the word's lines, filled with the word — never 優しさい, お部屋部屋 or 俺たちたち.
    store = make_store(lemmas=[(*key, key[0], "名詞", 100)],
                       patterns=[(*key, kind, item, 79, None if kind == "form" else 9.5, "W" if kind == "form" else "K3")])
    assert pt.resolve_key(written, "", store, tokenize) == (key, None)
    html, _reason = pt.patterns_for(written, "", store, tokenize)
    assert shown in html and written + written[-1:] not in html and "優しさい" not in html


def test_a_word_the_dictionary_lists_whole_takes_none_of_the_word_before_its_ending(make_store, tokenize):
    # The dictionary decides (the user, 2026-09-30): 心する 'take heed' and 一気に 'in one go' are words of their own
    # in JMdict, apart from 心 and 一気 — a phrase to a database that counts UniDic's words, never 心's or 一気's
    # lines. 努力する is still 努力: JMdict lists no 努力する (努力 takes する).
    store = make_store(lemmas=[("心", "ココロ", "心", "名詞", 100), ("一気", "イッキ", "一気", "名詞", 100),
                               ("努力", "ドリョク", "努力", "名詞", 100)])
    assert pt.resolve_key("心する", "", store, tokenize) == (None, "phrase")
    # 一気に is one word since 2026-10-01 (the tokenizer joins an adverb JMdict lists that it cuts at its particle): a
    # key of its own, which this store doesn't hold — still none of 一気's lines.
    assert pt.resolve_key("一気に", "", store, tokenize) == (None, "not found")
    assert pt.resolve_key("努力する", "", store, tokenize) == (("努力", "ドリョク"), None)


def test_a_word_filed_under_another_takes_its_lines_only_where_the_database_writes_it_so(make_store, tokenize):
    # 揚げる 'deep-fry' is UniDic's 上げる: a database that counts it with 上げる 'raise' (as the builder did before it
    # counted such a spelling as its own word, below) writes that word 上げる, so a 揚げる card takes none of its lines.
    # 帰る is UniDic's 返る too, but such a database writes that word 帰る (its main spelling): it holds 帰る. 信じる is
    # UniDic's 信ずる — one verb, conjugated two ways.
    store = make_store(lemmas=[("上げる", "アゲル", "上げる", "動詞", 900), ("返る", "カエル", "帰る", "動詞", 800),
                               ("信ずる", "シンズル", "信ずる", "動詞", 300)],
                       aliases=[("上げる", "上げる", "アゲル", 850), ("揚げる", "上げる", "アゲル", 50),
                                ("帰る", "返る", "カエル", 700), ("返る", "返る", "カエル", 100),
                                ("信じる", "信ずる", "シンズル", 280), ("信ずる", "信ずる", "シンズル", 20)])
    assert pt.resolve_key("揚げる", "", store, tokenize) == (None, "not found")
    assert pt.resolve_key("帰る", "", store, tokenize) == (("返る", "カエル"), None)
    assert pt.resolve_key("信じる", "", store, tokenize) == (("信ずる", "シンズル"), None)
    assert pt.resolve_key("上げる", "", store, tokenize) == (("上げる", "アゲル"), None)


def test_a_card_the_dictionary_keeps_apart_finds_its_own_words_lines_in_a_built_database(make_store, tokenize,
                                                                                        monkeypatch):
    # The builder counts a spelling JMdict lists as a word of its own under that spelling too (揚げる apart from 上げる,
    # 撮る from 取る, 帰る from 返る), so each such card finds its own word's row — 揚げる's 天ぷらを揚げる, never 上げる's
    # 顔を上げる — while a card of the lemma reads the lemma's row as before (UniDic's word, every spelling's uses).
    from app import analyzer
    monkeypatch.setattr(pb, "MIN_PATTERN", 1)
    text = "天ぷらを揚げる。" * 3 + "顔を上げる。" * 3 + "写真を撮る。" * 3 + "帽子を取る。" * 3 + "家に帰る。" * 3
    boundaries = frozenset(analyzer.LOGIC["sentence_boundaries"]["ja"])
    counts = pb.count(pb.iter_tokens(text, analyzer.Tagger(), analyzer._sanitize_term, boundaries), pb.Counts())
    store = make_store(*pb.score(counts, 1), floor=1)
    for card, key in (("揚げる", ("揚げる", "アゲル")), ("上げる", ("上げる", "アゲル")), ("撮る", ("撮る", "トル")),
                      ("取る", ("取る", "トル")), ("帰る", ("帰る", "カエル"))):
        assert pt.resolve_key(card, "", store, tokenize) == (key, None)
    assert [row[0] for row in store.patterns("揚げる", "アゲル", "colloc")] == ["天ぷらを{w}"]
    assert [row[0] for row in store.patterns("撮る", "トル", "colloc")] == ["写真を{w}"]
    assert {row[0] for row in store.patterns("上げる", "アゲル", "colloc")} == {"顔を{w}", "天ぷらを{w}"}


def test_a_kana_card_keeps_its_sa_and_a_dictionary_polite_word_is_its_own(make_store, tokenize):
    # やさしさ could be 優しさ or 易しさ — the tagger's guess — so it stays a phrase; お守り is one word of its own.
    store = make_store(lemmas=[("優しい", "ヤサシイ", "優しい", "形容詞", 100), ("守る", "マモル", "守る", "動詞", 100)])
    assert pt.resolve_key("やさしさ", "", store, tokenize) == (None, "phrase")
    assert pt.resolve_key("お守り", "", store, tokenize)[0] != ("守る", "マモル")
    assert pt._bare_word("やさしさ", tokenize) == "やさしさ"


def test_a_compound_noun_card_finds_its_compound(make_store, tokenize):
    # 奨学金 is two UniDic tokens; the builder stores the compound under its own spelling.
    store = make_store(lemmas=[("奨学金", "ショウガクキン", "奨学金", "名詞", 30)],
                       aliases=[("奨学金", "奨学金", "ショウガクキン", 30)])
    assert pt.resolve_key("奨学金", "しょうがくきん", store, tokenize) == (("奨学金", "ショウガクキン"), None)
    assert pt.resolve_key("時間帯", "じかんたい", store, tokenize) == (None, "not found")


def test_a_multi_token_expression_is_skipped_with_its_reason(library_store, tokenize):
    assert pt.resolve_key("話が弾む", "はなしがはずむ", library_store, tokenize) == (None, "phrase")


def test_a_word_the_corpus_never_saw_is_not_found(library_store, tokenize):
    assert pt.resolve_key("冒険", "ぼうけん", library_store, tokenize) == (None, "not found")


def test_a_word_under_the_floor_stays_empty_and_says_why(library_store, tokenize):
    assert pt.patterns_for("我慢", "がまん", library_store, tokenize) == ("", "too rare (7 < 12)")


# --- a card that holds a number (a number is no word since builder 8) ----------------------------- #
@pytest.fixture
def numbers_store(make_store):
    # What builder 8 counts around numbers: the noun a number stood beside is a word with lines of its own (年,
    # 世界); a word the texts hold whole keeps its spelling (十分, 千万, 何人); 千 and 一 are also names (セン,
    # ハジメ); a numeral inside a joined word belongs to that word (二十歳, 十八番).
    rows = [("年", "ネン", "年", "名詞", 5000), ("世界", "セカイ", "世界", "名詞", 8000),
            ("十分", "ジュウブン", "十分", "形状詞", 6640), ("千万", "センバン", "千万", "名詞", 192),
            ("何人", "ナニビト", "何人", "名詞", 91), ("セン", "セン", "千", "名詞", 935),
            ("ハジメ", "ハジメ", "一", "名詞", 924), ("二十歳", "ハタチ", "二十歳", "名詞", 310),
            ("十八番", "オハコ", "十八番", "名詞", 52), ("一生懸命", "イッショウケンメイ", "一生懸命", "形状詞", 1123)]
    return make_store(lemmas=rows, aliases=[(orth, lemma, reading, n) for lemma, reading, orth, _pos, n in rows],
                      patterns=[("年", "ネン", "colloc", "{w}が経つ", 40, 7.5, "C1が", 30),
                                ("世界", "セカイ", "colloc", "{w}を救う", 60, 8.1, "C1を", 40)])


@pytest.mark.parametrize("card", ["何年", "数年", "一年", "1年", "三月", "世界一", "何度", "五分"])
def test_a_card_holding_a_number_never_borrows_the_word_beside_it(numbers_store, tokenize, card):
    # A number is no word, so a card read without it was 年 or 世界 alone and showed their lines as its own:
    # 数年が経つ, 世界一を救う, 十二月のライオン — on 8 of the user's backlog cards and 21 of their known words
    # (2026-09-29). Read by its whole spelling, as before numbers stopped counting, the card stays empty.
    assert pt.resolve_key(card, "", numbers_store, tokenize) == (None, "not found")
    assert pt.patterns_for(card, "", numbers_store, tokenize) == ("", "not found")


@pytest.mark.parametrize("card", ["一", "三", "二十", "千"])
def test_a_number_alone_is_no_word(numbers_store, tokenize, card):
    # By its spelling 一 found the name ハジメ; 千, which the tagger reads alone as the name セン, found that name's
    # frames (〜紗 · 〜音速). A number card stays empty.
    assert pt.resolve_key(card, "", numbers_store, tokenize) == (None, "phrase")


@pytest.mark.parametrize("card, key", [
    ("十分", ("十分", "ジュウブン")),      # 十 + 分 read alone; the texts hold the word whole (十分に, 十分な)
    ("千万", ("千万", "センバン")),        # two numbers read alone; one word in 迷惑千万
    ("何人", ("何人", "ナニビト")),
    ("二十歳", ("二十歳", "ハタチ")),       # a numeral inside a joined word
    ("十八番", ("十八番", "オハコ")),
    ("一生懸命", ("一生懸命", "イッショウケンメイ")),
])
def test_a_word_written_with_a_numeral_is_still_found(numbers_store, tokenize, card, key):
    assert pt.resolve_key(card, "", numbers_store, tokenize) == (key, None)


def test_no_database_yet_is_a_normal_state(tmp_path):
    assert open_store(str(tmp_path / "missing.db")) is None


# --- end to end ------------------------------------------------------------------------------- #
_EIKYOU = """台風の影響を受けて電車が止まった。
彼の言葉に大きな影響を受けた。
子どもは親の影響を受けやすい。
円安の影響が広がっている。
天気の影響で試合が中止になった。
その本は多くの人に影響を与えた。
大きな影響を与える決定だ。
経済への影響が心配だ。
影響は小さいと思う。
強い影響を受けている。
環境に影響を与える。
影響が出るのは来年だ。
大きな影響はない。
悪い影響を受ける。"""


def test_a_library_build_fills_a_real_word_end_to_end(tmp_path, tokenize):
    # Fourteen real sentences over three episodes, the library's word floor (12), pattern floor (3) and
    # documents floor (3 — a library's document is a file) as shipped.
    tier = os.path.join(get_data_path("ja"), "HighPriority")
    os.makedirs(tier)
    lines = _EIKYOU.splitlines()
    for n in range(3):
        with open(os.path.join(tier, f"影響{n + 1}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines[n::3]))
    db = str(tmp_path / "p.db")
    pb.build(db_path=db)
    store = open_store(db)
    try:
        field, reason = pt.patterns_for("影響", "えいきょう", store, tokenize)
        assert reason is None
        # 大きな〜 (3 uses) is in two of the three episodes — not yet the word's own.
        assert field == ('<div class="pat-particle">〜を 57% · 〜が 21%</div>'
                         '<div class="pat-colloc">影響を受ける · 影響を与える</div>')
        assert pt.patterns_for("受ける", "うける", store, tokenize) == ("", "too rare (5 < 12)")
    finally:
        store.close()


# --- the lookup since builder 6 (Patterns_Quality_Spec.md §8.2) ------------------------------------- #
_HANSEI = ("反省", "ハンセイ")


def test_each_particle_row_sits_on_its_own_side(make_store):
    # A する-noun takes を before it where it is a verb (自分を反省する) and after it where it is a noun
    # (反省をする) — the approved mockup's 〜を 9% · を〜 7%: two rows, two sides, shares of all uses.
    store = make_store(lemmas=[(*_HANSEI, "反省", "名詞", 1000)], patterns=[
        (*_HANSEI, "particle", "を", 90, None, "after"), (*_HANSEI, "particle", "を", 70, None, "before"),
        (*_HANSEI, "particle", "は", 40, None, "after")])
    assert pt.format_patterns(pt.lines_for(store, *_HANSEI), "反省") == \
        '<div class="pat-particle">〜を 9% · を〜 7%</div>'


def test_no_is_an_adverbs_particle_alone(make_store):
    # 再度の襲撃: 〜の on a word used as an adverb (the user: "i'd rather have it 〜の"); an ordinary
    # noun's の stays out (D4), even where the database counted it.
    rows = [(("再度", "サイド"), "副詞"), (("先生", "センセイ"), "名詞")]
    for key, pos in rows:
        store = make_store(lemmas=[(*key, key[0], pos, 1000)],
                           patterns=[(*key, "particle", "の", 70, None, "after")])
        shown = pt.format_patterns(pt.lines_for(store, *key), key[0])
        assert shown == ('<div class="pat-particle">〜の 7%</div>' if pos == "副詞" else ""), key


def test_a_pairing_must_be_seen_in_three_documents_and_be_strong(make_store):
    # One book saying it thirty times is that book's (F7); a partner under strength 2 goes with
    # everything (反省が来る −0.26, F5). A database from before the documents count keeps its rows.
    store = make_store(lemmas=[(*_HANSEI, "反省", "名詞", 1000)], patterns=[
        (*_HANSEI, "colloc", "{w}を促す", 12, 7.5, "C1を", 9),
        (*_HANSEI, "colloc", "{w}の弁", 30, 6.0, "K1", 2),               # one book's
        (*_HANSEI, "colloc", "{w}が来る", 6, -0.26, "C1が", 5),           # goes with everything
        (*_HANSEI, "colloc", "{w}を踏まえる", 6, 7.07, "C1を", 5)])
    assert [item for item, _ in pt.lines_for(store, *_HANSEI)["colloc"]] == ["{w}を促す", "{w}を踏まえる"]
    old = make_store(lemmas=[(*_HANSEI, "反省", "名詞", 1000)],
                     patterns=[(*_HANSEI, "colloc", "{w}の弁", 30, 6.0, "K1")])     # no files: builder 5
    assert [item for item, _ in pt.lines_for(old, *_HANSEI)["colloc"]] == ["{w}の弁"]


def test_filler_goes_by_rule(make_store):
    # {w}という fits any noun; a demonstrative frame shows only where it IS the word's use (そのまま 32%,
    # この辺), not where it merely fits a noun (この事件 8.7% of its uses) — U11.
    key = ("事件", "ジケン")
    store = make_store(lemmas=[(*key, "事件", "名詞", 1000)], patterns=[
        (*key, "colloc", "{w}という", 40, 3.0, "K1", 20), (*key, "colloc", "{w}が起きる", 50, 8.0, "C1が", 30),
        (*key, "frame", "この〜", 87, 7.8, "F1連体詞", 60), (*key, "frame", "殺人〜", 30, 9.0, "K5", 20)])
    lines = pt.lines_for(store, *key)
    assert [item for item, _ in lines["colloc"]] == ["{w}が起きる"]
    assert [item for item, _ in lines["frame"]] == ["殺人〜"]
    place = ("辺", "ヘン")
    common = make_store(lemmas=[(*place, "辺", "名詞", 1000)],
                        patterns=[(*place, "frame", "この〜", 320, 9.0, "F1連体詞", 200)])
    assert [item for item, _ in pt.lines_for(common, *place)["frame"]] == ["この〜"]


def test_one_long_compound_partner_at_most_and_only_as_common_as_what_it_displaces(make_store):
    # News is full of noun + noun runs (日本政府, 経済政策): one-character partners build the word (〜会,
    # 〜点, 〜文), and one longer partner may join them — never two, never over a commoner one (U10).
    key = ("経済", "ケイザイ")
    store = make_store(lemmas=[(*key, "経済", "名詞", 5000)], patterns=[
        (*key, "frame", "〜政策", 400, 10.0, "F4m", 90), (*key, "frame", "〜成長", 300, 9.5, "F4m", 80),
        (*key, "frame", "〜学", 350, 9.0, "F4", 70), (*key, "frame", "〜的", 200, 8.0, "F3", 60)])
    assert [item for item, _ in pt.lines_for(store, *key)["frame"]] == ["〜政策", "〜学", "〜的"]
    # 〜政策 (100) would take the third slot from 〜界 (150): the commoner one-character partner stays.
    rarer = make_store(lemmas=[(*key, "経済", "名詞", 5000)], patterns=[
        (*key, "frame", "〜政策", 100, 10.0, "F4m", 40), (*key, "frame", "〜学", 350, 9.0, "F4", 70),
        (*key, "frame", "〜界", 150, 8.5, "F4", 50), (*key, "frame", "〜的", 200, 8.0, "F3", 60)])
    assert [item for item, _ in pt.lines_for(rarer, *key)["frame"]][:3] == ["〜学", "〜的", "〜界"]


def test_a_long_partner_with_a_free_slot_displaces_nothing_and_one_the_card_cannot_show_takes_no_slot(make_store):
    # The adversarial sweep (2026-09-25): the rule compared a long partner with EVERY later one-character one,
    # so 幼少 showed 〜期 · 〜時 and lost 〜時代 with the third slot free (83 words in the shared set); and an
    # item holding ・ took the one long slot, then the formatter dropped it — かりゆし lost its frames.
    key = ("幼少", "ヨウショウ")
    store = make_store(lemmas=[(*key, "幼少", "名詞", 672)], patterns=[
        (*key, "frame", "〜期", 300, 11.0, "F4", 30), (*key, "frame", "〜時代", 36, 10.5, "F4m", 20),
        (*key, "frame", "〜時", 120, 10.0, "F4", 25)])
    assert [item for item, _ in pt.lines_for(store, *key)["frame"]] == ["〜期", "〜時代", "〜時"]
    wear = ("かりゆし", "カリユシ")
    unsafe = make_store(lemmas=[(*wear, "かりゆし", "名詞", 90)], patterns=[
        (*wear, "frame", "〜アーバンリゾート・ナハ", 30, 12.0, "F4m", 3), (*wear, "frame", "〜ウエア", 18, 11.0, "F4", 5)])
    assert [item for item, _ in pt.lines_for(unsafe, *wear)["frame"]] == ["〜ウエア"]


@pytest.mark.parametrize("uses, thin", [(49, True), (50, False)])
def test_a_card_resting_on_few_uses_says_so(make_store, tokenize, uses, thin):
    # Under 50 uses in its source, every line carries pat-thin and the card's label turns amber —
    # colour only, never a count (decision 3, U5).
    key = ("人工授精", "ジンコウジュセイ")
    store = make_store(lemmas=[(*key, "人工授精", "名詞", uses)], aliases=[("人工授精", *key, uses)],
                       patterns=[(*key, "particle", "を", 13, None, "after"),
                                 (*key, "colloc", "{w}を行う", 5, 8.0, "C1を", 4)])
    field, _reason, _source = pt.patterns_from_sources("人工授精", "", [("balanced", store)], tokenize)
    assert field.count(" pat-thin") == (2 if thin else 0) and field.count("<div") == 2


def test_a_thin_source_gives_way_to_a_full_one_that_is_not(make_store, tokenize):
    # 呈する took the conversational corpus's 42 uses where the balanced one had 554 (§8.2): the first
    # source with four pairings that is not thin wins; a thin one only when no other has four.
    key = ("呈する", "テイスル")

    def store_with(uses):
        return make_store(lemmas=[(*key, "呈する", "動詞", uses)], aliases=[("呈する", *key, uses)],
                          patterns=[(*key, "colloc", f"{n}を{{w}}", 5, 8.0 - i, "C3を", 4)
                                    for i, n in enumerate(("様相", "活況", "疑問", "苦言"))])
    thin, full = store_with(42), store_with(554)
    assert pt.patterns_from_sources("呈する", "", [("conversational", thin), ("balanced", full)],
                                    tokenize)[2] == "balanced"
    field, _reason, source = pt.patterns_from_sources("呈する", "", [("conversational", thin)], tokenize)
    assert source == "conversational" and " pat-thin" in field


def test_a_database_from_an_older_builder_is_never_read(tmp_path):
    # Before words kept their prefixes and suffixes, 不自然 was 不 + 自然: an older database answers "not
    # found" for it and misses every new line — so it counts as not built (§8.3a) until it is rebuilt
    # or downloaded again. A store whose meta names no builder (made by hand) is taken at its name.
    from modules.junban.patterns_store import is_current
    for version, readable in ((pb.BUILDER_VERSION - 1, False), (pb.BUILDER_VERSION, True)):
        db = str(tmp_path / f"v{version}.db")
        pb.write_rows(db, [("反省", "ハンセイ", "反省", "名詞", 100)], [], [],
                      {"floor": 12, "language": "ja", "builder_version": version})
        store = open_store(db)
        assert (store is not None) == readable == is_current(db, "ja")
        if store:
            store.close()
