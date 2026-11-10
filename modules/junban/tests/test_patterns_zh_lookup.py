# SPDX-License-Identifier: GPL-3.0-or-later
"""Chinese パターン — from a card's word to its lines, in the card's own script (Patterns_Chinese_Spec.md
§7, WP-Z3).

The database keys in Simplified; a Traditional learner's card must find the same key and read its lines
in Traditional — converted WITH the card's word in them, because OpenCC's phrases need their context
(只猫 → 只貓 but 一只猫 → 一隻貓; 头发 → 頭髮, never 頭發). Exact stores built from rows, real words.
"""
import re

import pytest

from modules.junban import patterns as pt, patterns_build as pb, patterns_zh as pz
from modules.junban.match import normalize_word
from modules.junban.patterns_store import open_store


@pytest.fixture
def make_store(tmp_path):
    """An exact Chinese store from rows — (word, tag, count), aliases, patterns; closed at teardown."""
    opened = []

    def make(words, patterns=(), aliases=(), floor=1, tokens=1000):
        db = str(tmp_path / f"patterns_zh_{len(opened)}.db")
        lemmas = [(w, "", w, tag, count) for w, tag, count in words]
        alias = [(w, w, "", count) for w, _tag, count in words] + [(o, w, "", c) for o, w, c in aliases]
        rows = [(w, "", kind, item, count, logdice, section) for w, kind, item, count, logdice, section in patterns]
        pb.write_rows(db, lemmas, alias, rows, {"floor": floor, "tokens": tokens, "language": "zh"})
        opened.append(open_store(db, language="zh"))
        return opened[-1]
    yield make
    for store in opened:
        store.close()


def _text(html):
    return " / ".join(re.findall(r">([^<]+)<", html))


# --- the key ------------------------------------------------------------------------------------- #
def test_a_traditional_card_finds_the_simplified_key(make_store):
    store = make_store([("问题", "n", 40)])
    assert pz.resolve_key("問題", store) == (("问题", ""), None)
    assert pz.resolve_key("问题", store) == (("问题", ""), None)


def test_a_card_with_pinyin_brackets_is_found(make_store):
    # A CC-CEDICT-style card: 学习[xue2 xi2] — normalize_word strips the brackets (Z-F16).
    store = make_store([("学习", "v", 40)])
    assert pz.resolve_key(normalize_word("学习[xue2 xi2]"), store) == (("学习", ""), None)


def test_a_multi_word_card_is_a_phrase_and_an_unknown_word_is_not_found(make_store):
    store = make_store([("朋友", "n", 40)])
    assert pz.resolve_key("打电话给朋友", store) == (None, "phrase")
    assert pz.resolve_key("冒险", store) == (None, "not found")


def test_a_card_with_de_or_di_or_doubled_finds_its_word(make_store):
    # 认真地 and 漂亮的 are 认真 and 漂亮 (a 的 / 地 written on: anki_match.ZH_CARD_ENDINGS); 开开心心 is 开心, as the
    # builder keys it; 目的 is a word of its own, never 目.
    store = make_store([("认真", "a", 40), ("漂亮", "a", 30), ("开心", "a", 20), ("目", "n", 10)])
    assert pz.resolve_key("认真地", store) == (("认真", ""), None)
    assert pz.resolve_key("漂亮的", store) == (("漂亮", ""), None)
    assert pz.resolve_key("开开心心", store) == (("开心", ""), None)
    assert pz.resolve_key("目的", store) == (None, "not found")


def test_a_card_with_its_aspect_after_a_verb_finds_the_verb(make_store):
    # 吃了, 去过 and 看着 are their verbs (anki_match.ZH_ASPECTS after a verb by jieba's tags); 人了 is no verb's.
    store = make_store([("吃", "v", 40), ("去", "v", 30), ("看", "v", 20), ("人", "n", 10)])
    assert pz.resolve_key("吃了", store) == (("吃", ""), None)
    assert pz.resolve_key("去过", store) == (("去", ""), None)
    assert pz.resolve_key("看着", store) == (("看", ""), None)
    assert pz.resolve_key("人了", store) == (None, "phrase")


def test_a_word_with_kana_is_never_looked_up_in_chinese(make_store):
    # S4: 勉強する is Japanese — even where a Chinese store could match its kanji (勉强).
    store = make_store([("勉强", "a", 40)])
    assert pz.resolve_key("勉強する", store) == (None, "language")


def test_a_chinese_name_written_with_the_katakana_middle_dot_is_a_phrase_never_another_language(make_store):
    # 约翰・列侬 (John Lennon) writes its name dot with the kana block's ・ (U+30FB), as Traditional text often
    # does: punctuation, no kana letter (Unicode files it Common). Two words, a phrase, as with the Chinese dot
    # · — never refused as Japanese (every Chinese kana test reads app/unicode_ranges.KANA_LETTERS).
    store = make_store([("约翰", "nr", 40), ("列侬", "nr", 5)])
    assert pz.resolve_key("约翰・列侬", store) == (None, "phrase")
    assert pz.resolve_key("约翰·列侬", store) == (None, "phrase")


# --- the lines, in the card's script ------------------------------------------------------------ #
def test_a_chinese_line_one_item_sits_before_the_word(make_store):
    # Z-F15: lines_for puts a line-1 item after the word only for a Japanese 名詞 — a jieba tag never is,
    # so 个〜 and 跟〜 sit before, which is right for both Chinese line-1 kinds.
    store = make_store([("问题", "n", 40)], [("问题", "particle", "个", 30, None, None),
                                             ("问题", "particle", "条", 10, None, None)])
    lines = pt.lines_for(store, "问题", "")
    assert lines["side"] == "before"
    assert pt.format_patterns(lines, "问题").startswith('<div class="pat-particle">个〜 75% · 条〜 25%</div>')


def test_a_classifier_renders_in_traditional_beside_its_noun(make_store):
    # 只〜 beside 猫 on a Traditional card is 隻〜: converted with a numeral, as OpenCC needs.
    store = make_store([("猫", "n", 40)], [("猫", "particle", "只", 40, None, None)])
    html, reason, _src = pz.from_sources("貓", [("library", store)])
    assert _text(html) == "隻〜 100%" and reason is None
    assert _text(pz.from_sources("猫", [("library", store)])[0]) == "只〜 100%"


def test_an_item_converts_with_the_cards_word_in_context(make_store):
    # 洗头发 on a Traditional card: 洗頭髮 — character by character it would be 頭發 (Z-F6). And where the
    # card's own word decides a character: 头 + 发 is 頭髮, hair — the item alone would give 發, to send.
    store = make_store([("洗", "v", 40), ("头", "n", 40)], [("洗", "colloc", "{w}头发", 12, 9.0, "VO"),
                                                           ("头", "colloc", "{w}发", 12, 9.0, "SP")])
    assert pz.render_lines(pt.lines_for(store, "洗", ""), "洗", "t")["colloc"][0][0] == "{w}頭髮"
    assert pz.render_lines(pt.lines_for(store, "头", ""), "頭", "t")["colloc"][0][0] == "{w}髮"


def test_the_cards_own_spelling_fills_the_word(make_store):
    # The card says 問題: its lines say 沒問題 and 這個〜, in Traditional throughout.
    store = make_store([("问题", "n", 40)], [("问题", "colloc", "没{w}", 12, 9.0, "VO"),
                                             ("问题", "frame", "这个〜", 20, 10.0, "F1")])
    assert _text(pz.from_sources("問題", [("library", store)])[0]) == "沒問題 / 這個〜"
    assert _text(pz.from_sources("问题", [("library", store)])[0]) == "没问题 / 这个〜"


def test_a_card_read_as_its_word_writes_its_lines_with_that_word(make_store):
    # 认真地, 吃了 and 开开心心 are read as 认真, 吃 and 开心 (resolve_key): their lines are those words' lines, and say
    # the words as they are — 认真履行, 吃晚饭, 很开心 — never 认真地履行, 吃了晚饭 or 很开开心心 (found reading the
    # rebuilt shared set v3, 2026-10-01). A Traditional card read so writes its word in Traditional (認真地: 認真履行);
    # a card that IS the word keeps its own spelling (test_the_cards_own_spelling_fills_the_word).
    store = make_store([("认真", "a", 40), ("吃", "v", 40), ("开心", "a", 40)],
                       [("认真", "colloc", "{w}履行", 12, 9.0, "DV"), ("吃", "colloc", "{w}晚饭", 12, 9.0, "VO"),
                        ("开心", "form", "很{w}", 8, None, "W")])
    assert _text(pz.from_sources("认真地", [("library", store)])[0]) == "认真履行"
    assert _text(pz.from_sources("吃了", [("library", store)])[0]) == "吃晚饭"
    assert _text(pz.from_sources("开开心心", [("library", store)])[0]) == "很开心 20%"
    assert _text(pz.from_sources("認真地", [("library", store)])[0]) == "認真履行"
    assert _text(pz.from_sources("认真", [("library", store)])[0]) == "认真履行"


def test_a_script_neutral_card_follows_the_users_setting():
    # 洗 is the same in both scripts: the user's zh_script decides.
    assert pz.script_of("洗", "t") == "t" and pz.script_of("洗", "s") == "s" and pz.script_of("洗") == "s"
    assert pz.script_of("學習") == "t" and pz.script_of("学习", "t") == "s"


def test_an_item_holding_a_name_dot_is_dropped(make_store):
    # 列夫·托尔斯泰: the · would split the line on the card (the field contract) — the item is dropped.
    store = make_store([("写", "v", 40)], [("写", "colloc", "列夫·托尔斯泰{w}", 12, 9.0, "SP"),
                                           ("写", "colloc", "{w}小说", 10, 8.0, "VO")])
    assert _text(pz.from_sources("写", [("library", store)])[0]) == "写小说"


# --- the register ----------------------------------------------------------------------------- #
def _register_stores(make_store, word, tag):
    """A conversational store where `word` is rare and a balanced one (which holds it) where it is not:
    1 use in 1,000 spoken words, 200 in 2,000 written — 50 times rarer in speech."""
    speech = make_store([(word, tag, 1)], [(word, "colloc", "{w}工作", 1, 9.0, "VO")], tokens=1000)
    both = make_store([(word, tag, 201)], [(word, "colloc", "{w}工作", 30, 9.0, "VO")], tokens=3000)
    return [("conversational", speech), ("balanced", both)]


def test_chinese_has_no_register_in_v1(make_store):
    # D9's own condition failed at the gate (WP-Z6): the speech we may share is too small and too narrow,
    # and 3,457 of the 6,000 commonest words would lean "written" — 政府 and 比赛 among them. No row, no tag.
    stores = _register_stores(make_store, "进行", "v")
    assert "zh" not in pt.REGISTER and pt.register_of(("进行", ""), stores, "zh") is None
    assert pz.from_sources("进行", stores)[0] and "pat-register" not in pz.from_sources("进行", stores)[0]


def test_the_register_label_follows_the_cards_script(make_store, monkeypatch):
    # Kept for the day a spoken corpus makes the tag honest: the label is written in the card's script.
    monkeypatch.setitem(pt.REGISTER, "zh", (4.0, 50, "书面语"))
    stores = _register_stores(make_store, "进行", "v")
    assert _text(pz.from_sources("进行", stores)[0]).endswith("书面语")
    assert _text(pz.from_sources("進行", stores)[0]).endswith("書面語")


def test_a_chinese_name_never_gets_the_written_tag(make_store, monkeypatch):
    # 鲁迅 leans written like any author's name — a name has no register (§9); 李明, outside the
    # dictionary, is a name by posseg's own cut.
    monkeypatch.setitem(pt.REGISTER, "zh", (4.0, 50, "书面语"))
    for name in ("鲁迅", "李明"):
        stores = _register_stores(make_store, name, "nr")
        html = pz.from_sources(name, stores)[0]
        assert html and "pat-register" not in html
    assert pz.is_name("鲁迅") and pz.is_name("李明") and not pz.is_name("进行")


def test_the_japanese_register_is_unchanged():
    # The per-language table holds Japanese's constants exactly (§13). The line moved on purpose once: 4.155 is
    # 4.0 re-drawn on builder 8's counting, where numbers, symbols and Latin words are no tokens.
    assert pt.REGISTER["ja"] == (pt.REGISTER_LEAN, pt.REGISTER_MIN, pt.WRITTEN) == (4.155, 50, "書き言葉")
    assert pt.sources_for("ja") == pt.SOURCE_ORDER and pt.sources_for("ko") == ()


# --- the quality redesign's Chinese part (Patterns_Quality_Spec.md §10) ---------------------------- #
def test_is_x_a_weak_partner_and_a_demonstrative_that_merely_fits_are_left_out(make_store):
    # E1: 是{w} ("is X") was a shown pairing on 1,837 words — the twin of Japanese {w}という; a partner under
    # strength 2 goes with everything (让猫 2.1 → out at 1.2 here); 这个〜 shows only where it covers 10% of the
    # word's uses, as この〜 does.
    store = make_store([("猫", "n", 1000)], [
        ("猫", "colloc", "是{w}", 50, 8.0, "VO"), ("猫", "colloc", "养{w}", 40, 9.0, "VO"),
        ("猫", "colloc", "让{w}", 10, 1.2, "VO"), ("猫", "frame", "这个〜", 20, 6.0, "F1"),
        ("猫", "frame", "〜咪", 30, 9.0, "F3")])
    lines = pt.lines_for(store, "猫", "")
    assert [item for item, _ in lines["colloc"]] == ["养{w}"]
    assert [item for item, _ in lines["frame"]] == ["〜咪"]


def test_every_chinese_demonstrative_frame_follows_the_ten_percent_rule(make_store):
    # The Chinese F1 rule writes only demonstrative frames — 这 / 那 / 每 / 某 / 各, with or without a measure
    # word — and the shared set had 149 of them, not just the eight named: 公司 这家〜 on 1.7% of its uses, 问题
    # 各种〜 on 0.3% (the adversarial sweep, 2026-09-25). Under 10% they go; where one IS the word's use it stays.
    store = make_store([("公司", "n", 1000), ("东西", "n", 1000)], [
        ("公司", "frame", "这家〜", 17, 7.0, "F1"), ("公司", "frame", "各种〜", 3, 6.0, "F1"),
        ("公司", "frame", "〜内", 40, 9.0, "F3"),
        ("东西", "frame", "这种〜", 150, 8.0, "F1")])
    assert [item for item, _ in pt.lines_for(store, "公司", "")["frame"]] == ["〜内"]
    assert [item for item, _ in pt.lines_for(store, "东西", "")["frame"]] == ["这种〜"]


def test_a_coverb_row_on_few_of_the_words_uses_is_hidden_but_a_measure_word_row_is_not(make_store):
    # E4: 突然 在〜 58% rested on 4.9% of its uses — hidden under 6%; 影响 对〜 on 8.9% stays. A measure word
    # answers "which one" and is only used when counting, so its row keeps its own line (猫 只〜 at 5%).
    store = make_store([("突然", "ad", 1400), ("影响", "vn", 9600), ("猫", "n", 1000)], [
        ("突然", "particle", "在", 40, None, "P"), ("突然", "particle", "对", 29, None, "P"),
        ("影响", "particle", "对", 754, None, "P"), ("影响", "particle", "在", 103, None, "P"),
        ("猫", "particle", "只", 50, None, "Q")])
    assert pt.lines_for(store, "突然", "")["particle"] == []
    assert [p for p, _ in pt.lines_for(store, "影响", "")["particle"]] == ["对", "在"]
    assert pt.lines_for(store, "猫", "")["particle"] == [("只", 1.0)]


@pytest.mark.parametrize("uses, thin", [(49, True), (50, False)])
def test_a_chinese_card_resting_on_few_uses_says_so(make_store, uses, thin):
    # E3: the thin colour reaches Chinese in its own lookup (the Japanese one returns early for zh).
    store = make_store([("人工授精", "n", uses)], [("人工授精", "colloc", "进行{w}", 5, 8.0, "VO")])
    field, _reason, _source = pz.from_sources("人工授精", [("balanced", store)])
    assert (" pat-thin" in field) == thin


def test_a_thin_chinese_source_gives_way_to_a_full_one_that_is_not(make_store):
    pairs = [("处理", "colloc", f"{{w}}{n}", 5, 8.0 - i, "VO") for i, n in enumerate(("问题", "事情", "数据", "文件"))]
    thin = make_store([("处理", "v", 42)], pairs)
    full = make_store([("处理", "v", 554)], pairs)
    assert pz.from_sources("处理", [("conversational", thin), ("balanced", full)])[2] == "balanced"


def test_a_chinese_database_from_builder_one_is_not_read(tmp_path):
    # §8.3a: builder 2 keys the same words but writes documents and line 1's kind; a builder-1 file would
    # skip every new rule, so it counts as not built until the new shared set is downloaded.
    from modules.junban.patterns_store import is_current
    for version, readable in ((1, False), (pz.BUILDER_VERSION, True)):
        db = str(tmp_path / f"zh{version}.db")
        pb.write_rows(db, [("问题", "", "问题", "n", 100)], [], [],
                      {"floor": 20, "language": "zh", "builder_version": version})
        assert is_current(db, "zh") == readable
