# SPDX-License-Identifier: GPL-3.0-or-later
"""Chinese パターン — tokens and the key-space contract (Patterns_Chinese_Spec.md WP-Z1).

The failure that matters most here is silent: if the builder keys a word differently from the analyzer,
every lookup misses and a Chinese card says "not found" for words plainly there (§17 #1). So the first
test holds the builder to `ChineseTokenizer`'s keys over every Chinese fixture, both segmentation
settings — the day the analyzer's tokenizer changes, it trips. Real sentences throughout
(`tests/Test Resources/zh`: BBC news, the 冒险 lines, Taiwanese news, a mixed-script transcript, and the
two パターン samples written for this, CRLF and Traditional).
"""
import os

import jieba
import pytest

from app import analyzer, settings_manager, zh_script
from modules.junban import patterns_zh as pz

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ZH = os.path.join(_ROOT, "tests", "Test Resources", "zh")
FIXTURES = ["chinese_text_1.txt", "context_test.txt", "mixed_script_transcript.txt", "traditional_news.txt",
            "patterns_zh_sample.txt", "patterns_zh_sample_trad.txt"]
SIMPLIFIED = ["context_test.txt", "patterns_zh_sample.txt"]
BOUNDARIES = settings_manager.DEFAULT_SETTINGS["logic"]["sentence_boundaries"]["zh"]


def _read(name):
    with open(os.path.join(ZH, name), encoding="utf-8", newline="") as f:
        return f.read()


@pytest.fixture
def same_boundaries(monkeypatch):
    """The analyzer and the builder split sentences at the same (default) zh set in these tests."""
    logic = dict(analyzer.LOGIC)
    logic["sentence_boundaries"] = dict(logic.get("sentence_boundaries") or {}, zh=BOUNDARIES)
    monkeypatch.setattr(analyzer, "LOGIC", logic)


@pytest.fixture
def jieba_state():
    """Tuning jieba's dictionary (suggest_freq) holds for the whole process: put it back, or every
    later test in the run would segment 就把 differently (§17 #2)."""
    import jieba.finalseg as finalseg
    jieba.dt.check_initialized()
    freq, total, forced = dict(jieba.dt.FREQ), jieba.dt.total, set(finalseg.Force_Split_Words)
    yield
    jieba.dt.FREQ.clear()
    jieba.dt.FREQ.update(freq)
    jieba.dt.total = total
    finalseg.Force_Split_Words.clear()
    finalseg.Force_Split_Words.update(forced)


def _words(text):
    return [t.key for sentence in pz.iter_tokens(text, frozenset(BOUNDARIES)) for t in sentence if t.key]


def _analyzer(text, script, reinforce=False):
    tok = analyzer.ChineseTokenizer(reinforce_segmentation=reinforce, script=script)
    return [lemma for _s, tokens in tok.tokenize_sentences(text) for lemma, *_ in tokens]


# --- the key-space contract (§8.2) --------------------------------------------------------------- #
def test_the_zh_builder_keys_every_word_exactly_as_the_analyzer_does(same_boundaries, jieba_state):
    # Every fixture: the builder's words are the analyzer's under zh_script = s — with the retired reinforce
    # passed too, which neither reads any more.
    for reinforce in (False, True):
        for name in FIXTURES:
            text = _read(name)
            assert _words(text) == _analyzer(text, "s", reinforce), (name, reinforce)


def test_traditional_text_is_keyed_through_simplified(same_boundaries):
    # 經濟部 is keyed 经济部 and remembered as written, for the alias table; and the builder's cuts are
    # the analyzer's under zh_script = t — the same segmentation, sliced from the Traditional text.
    tokens = [t for s in pz.iter_tokens(_read("traditional_news.txt"), frozenset(BOUNDARIES)) for t in s if t.key]
    assert ("经济部", "經濟部") in {(t.text, t.orig) for t in tokens}
    for name in FIXTURES:
        trad = []
        for line in _read(name).split("\n"):
            simp = zh_script.to_simplified(line)
            out, pos = zh_script.to_traditional(simp), 0
            for sentence in pz.iter_tokens(line, frozenset(BOUNDARIES)):
                for t in sentence:
                    if t.key:
                        trad.append(out[pos:pos + len(t.text)])
                    pos += len(t.text)
        assert trad == _analyzer(_read(name), "t"), name


def test_on_simplified_text_the_keys_are_the_as_written_ones(same_boundaries):
    for name in SIMPLIFIED:
        assert _words(_read(name)) == _analyzer(_read(name), "asis"), name


def test_zero_and_the_extension_characters_are_chinese_to_the_builder_as_to_the_analyzer(same_boundaries):
    # 〇 (二〇一六年), 䶮 (刘䶮, Extension A) and 𨋢 (Hong Kong 'lift', Extension B) are Chinese characters to
    # the ChineseTokenizer (app/unicode_ranges.py); the builder reads the same ranges, so they are Chinese -
    # never barriers - to it too, keyed as the analyzer keys them (𨋢 is 䢂 in Simplified). 〇 is a numeral:
    # Chinese, but a number is no word, to either.
    text = "今天是二〇一六年十一月二十三日。\n刘䶮是南汉的开国皇帝。\n我哋搭𨋢上去。"
    words = _words(text)
    assert {"䶮", "䢂"} <= set(words) and "〇" not in words
    assert words == _analyzer(text, "s")
    zero = next(t for s in pz.iter_tokens(text, frozenset(BOUNDARIES)) for t in s if t.text == "〇")
    assert zero.word and not zero.key and not pz.is_barrier(zero)


def test_a_doubled_form_is_keyed_by_its_word_as_the_analyzer_counts_it(same_boundaries):
    # 开开心心 is 开心's (analyzer.chinese_base), as 休息休息 is one 休息 and 哈哈哈哈哈 one 哈哈; the token keeps the
    # text it covers, so the rules still read the sentence as written.
    text = "大家都开开心心的。\n你應該休息休息。\n哈哈哈哈哈！\n这里有形形色色的人。"
    words = _words(text)
    assert words == _analyzer(text, "s")
    assert {"开心", "休息", "哈哈", "形形色色"} <= set(words) and "开开心心" not in words
    happy = next(t for s in pz.iter_tokens(text, frozenset(BOUNDARIES)) for t in s if t.key == "开心")
    assert (happy.text, happy.orig) == ("开开心心", "开开心心")


def test_crlf_never_reaches_a_key():
    # The sample is written with CRLF on purpose (testing.md §2): a \r glued to a word would be a key
    # no card can find.
    text = _read("patterns_zh_sample.txt")
    assert "\r\n" in text
    tokens = [t for s in pz.iter_tokens(text, frozenset(BOUNDARIES)) for t in s]
    assert not any("\r" in t.text for t in tokens if t.word)
    assert all(pz.is_barrier(t) for t in tokens if "\r" in t.text)


def test_punctuation_is_a_barrier_and_the_boundary_set_ends_a_sentence():
    # ，and ；are barriers inside a sentence (nothing pairs across them — a semicolon joins the clauses of one
    # sentence, GB/T 15834-2011); 。 ends it, character-wise, as the analyzer splits.
    sentences = list(pz.iter_tokens("我买了书，他买了笔；我们都很高兴。他也来了。", frozenset(BOUNDARIES)))
    assert ["".join(t.text for t in s) for s in sentences] == ["我买了书，他买了笔；我们都很高兴。", "他也来了。"]
    for mark in ("，", "；"):
        barrier = next(t for t in sentences[0] if t.text == mark)
        assert pz.is_barrier(barrier) and not barrier.word
    assert not pz.is_barrier(next(t for t in sentences[0] if t.text == "书"))


def test_traditional_zhe_after_a_verb_is_the_aspect_marker():
    # to_simplified leaves 著 as it is (著 is also Simplified: 著名), and the dictionary tags it a noun —
    # after a verb it is the aspect marker 着 (Z-F6).
    tokens = [t for s in pz.iter_tokens("他笑著說：「沒問題！」", frozenset(BOUNDARIES)) for t in s]
    i = [t.text for t in tokens].index("著")
    assert tokens[i - 1].text == "笑" and tokens[i - 1].tag.startswith("v")
    assert pz.aspect(tokens[i].text) == "着" and pz.aspect("着") == "着" and pz.aspect("著名") is None


def test_a_token_outside_the_dictionary_is_split_for_counting_but_stays_one_word(same_boundaries):
    # With jieba's guesses off, 很难 is 很 + 难, two words for the analyzer and the builder alike. A token outside
    # jieba's dictionary is now a doubled form (or a guessed name): 休息休息 stays one token, keyed 休息, and the
    # rules read it as 休息 + 休息.
    text = "这个问题很难回答。你应该休息休息。"
    assert "很难" not in _words(text) and {"很", "难"} <= set(_words(text)) and _words(text) == _analyzer(text, "s")
    doubled = next(t for s in pz.iter_tokens(text, frozenset(BOUNDARIES)) for t in s if t.text == "休息休息")
    assert doubled.tag is None and doubled.key == "休息"
    assert [w for w, _tag in pz.parts(doubled)] == ["休息", "休息"]
    assert pz.parts(next(t for s in pz.iter_tokens(text, frozenset(BOUNDARIES)) for t in s if t.text == "问题")) \
        == [("问题", "n")]


# --- WP-Z2: the counting rules, one real sentence at a time ------------------------------------ #
def _rows(text, monkeypatch, floor=1):
    """Every pattern row `text` gives, with the ≥3 pattern floor and the form share off, so one sentence
    is enough."""
    from modules.junban import patterns_build as pb
    monkeypatch.setattr(pb, "MIN_PATTERN", 1)
    monkeypatch.setattr(pz, "FORM_SHARE", 0.0)             # Chinese's own (E7), no longer patterns_build's
    counts = pz.count(pz.iter_tokens(text, frozenset(BOUNDARIES)), pb.Counts())
    return pz.score(counts, floor)


def _items(rows, word, kind):
    return {r[3]: r[4] for r in rows[2] if r[0] == word and r[2] == kind}


def test_measure_words_arrive_fused_and_are_still_counted(monkeypatch):
    # Z-F5: 83% of measure words come fused — 一碗 牛肉面, 这家 店, 三 本书, 两辆车 — and the noun inside a
    # fused token is a use of that noun (书, 车), so its count includes it.
    rows = _rows("我们吃了一碗牛肉面。这家店很好。我买了三本书。他家有两辆车。桌上有一个杯子。", monkeypatch)
    assert _items(rows, "牛肉面", "particle") == {"碗": 1}
    assert _items(rows, "店", "particle") == {"家": 1}
    assert _items(rows, "书", "particle") == {"本": 1}
    assert _items(rows, "车", "particle") == {"辆": 1}            # 车 is `zg`: the measure word says noun
    assert _items(rows, "杯子", "particle") == {"个": 1}
    assert {r[0]: r[4] for r in rows[0]}["书"] == 1


def test_a_measure_word_reaches_its_noun_past_a_modifier_never_past_another_noun(monkeypatch):
    # UD's arcs (WP-Z4): Chinese puts the modifier between them — 一个有趣的故事, 这件糟糕的事, 一件新衣服;
    # speech drops the 一 after a verb (是个好人). In 一个人的故事 the 个 is 人's, not 故事's.
    rows = _rows("我讲了一个有趣的故事。这件糟糕的事过去了。我买了一件新衣服。这是一个人的故事。", monkeypatch)
    assert _items(rows, "故事", "particle") == {"个": 1}          # not 2: the last one is 人's
    assert _items(rows, "人", "particle") == {"个": 1}
    assert _items(rows, "事", "particle") == {"件": 1}
    assert _items(rows, "衣服", "particle") == {"件": 1}


def test_a_bare_ge_after_a_verb_is_a_measure_word(monkeypatch):
    # Speech drops the 一: 是 个 好人, 找 了 个 工作 — and jieba glues the 个 to the verb in 买个 手机, 吃个 饭.
    rows = _rows("他是个好人。他找了个工作。我想买个手机。我们吃个饭吧。", monkeypatch)
    for noun in ("好人", "工作", "手机", "饭"):
        assert _items(rows, noun, "particle") == {"个": 1}, noun


def test_the_preposition_ba_is_never_a_measure_word(monkeypatch):
    # 我把书放在桌子上: 把 after a pronoun is the preposition (Z-F9) — 一把刀 is the measure word.
    rows = _rows("我把书放在桌子上了。他买了一把刀。", monkeypatch)
    assert "把" not in _items(rows, "书", "particle")
    assert _items(rows, "刀", "particle") == {"把": 1}


def test_a_verbal_classifier_is_not_a_measure_word(monkeypatch):
    # 打了三次电话: 次 counts how often, not what 电话 is counted in.
    rows = _rows("我给他打了三次电话。这部电影我看了两遍。", monkeypatch)
    assert _items(rows, "电话", "particle") == {}


def test_a_coverb_is_found_across_a_noun_phrase(monkeypatch):
    # 跟〜 结婚, 对〜 满意 / 重要 (past the adverb 很), 把〜 放 (the head of 放在), 给〜 打.
    rows = _rows("她跟男朋友结婚了。我对这个结果很满意。这件事对我很重要。我把书放在桌子上了。我给他打了电话。",
                 monkeypatch)
    assert _items(rows, "结婚", "particle") == {"跟": 1}
    assert _items(rows, "满意", "particle") == {"对": 1}
    assert _items(rows, "重要", "particle") == {"对": 1}
    assert _items(rows, "放", "particle") == {"把": 1}
    assert _items(rows, "打", "particle") == {"给": 1}


def test_the_progressive_zai_is_not_a_coverb(monkeypatch):
    # 他在睡觉: 在 right before the verb, nothing between — the progressive. 在家吃饭: 在〜, a place. And a
    # coverb introduces an ARGUMENT: the short passive 他被打了 names no one — 被老师批评 does.
    rows = _rows("他在睡觉。我们在家吃饭。他被打了。他被老师批评了。", monkeypatch)
    assert _items(rows, "睡觉", "particle") == {}
    assert _items(rows, "吃饭", "particle") == {"在": 1}
    assert _items(rows, "打", "particle") == {} and _items(rows, "批评", "particle") == {"被": 1}


def test_zai_opening_a_time_clause_is_not_a_place(monkeypatch):
    # 在我睡觉的时候: 在 opens a time clause whose subject is 我 — no place. 在床上睡觉 / 在我们家睡觉 are.
    rows = _rows("在我睡觉的时候，他来了。我在床上睡觉。你在我们家睡觉吧。", monkeypatch)
    assert _items(rows, "睡觉", "particle") == {"在": 2}


def test_words_the_dictionary_misfiles_get_their_lines(monkeypatch):
    # 一样 is filed as a pronoun, 高兴 as 区别词 (`b`): 跟〜一样 and 很高兴 are still counted (TAG_FIXES).
    rows = _rows("他跟你一样。我很高兴认识你。她跟我一样。", monkeypatch)
    assert _items(rows, "一样", "particle") == {"跟": 2}
    assert _items(rows, "高兴", "form") == {"很{w}": 1}


def test_he_and_gen_as_and_are_not_coverbs(monkeypatch):
    # D3: 和 / 跟 mean "and" when 一起 / 一样 / 都 / 也 follow the noun phrase.
    rows = _rows("我和她一起去看电影。他跟你一样喜欢音乐。", monkeypatch)
    assert _items(rows, "去", "particle") == {} and _items(rows, "喜欢", "particle") == {}


# --- WP-Z6: what the balanced build (19.6M words) taught ------------------------------------------ #
def test_two_characters_then_one_is_a_compound_never_a_pair(monkeypatch):
    # The [2+1] rule of Chinese word structure: 推荐 + 菜, 制作 + 人, 统计 + 书, 便宜 + 坊 are compound nouns
    # (the balanced build had 2,835 such verb–object pairings) — 买 + 书, 新 + 衣服 and 便宜的店 are pairs.
    rows = _rows("这家餐厅的推荐菜很好吃。他是这部电影的制作人。他统计书的数量。我们去便宜坊吃烤鸭。"
                 "我昨天买了书。我买了一件新衣服。这是一家很便宜的店。", monkeypatch)
    assert _items(rows, "推荐", "colloc") == {} and _items(rows, "菜", "colloc") == {}
    assert _items(rows, "制作", "colloc") == {} and "统计{w}" not in _items(rows, "书", "colloc")
    assert "{w}坊" not in _items(rows, "便宜", "colloc")
    assert "{w}书" in _items(rows, "买", "colloc") and "{w}衣服" in _items(rows, "新", "colloc")
    assert "{w}的店" in _items(rows, "便宜", "colloc")


def test_a_three_character_word_jieba_reads_as_two_and_one_is_not_a_verb_and_its_object(monkeypatch):
    # 放大器 (an amplifier) is 放大 + 器 and 打火机 (a lighter) 打火 + 机 by jieba's own frequencies — not 放 +
    # 大器 or 打 + 火机; 打电话 stays 打 + 电话.
    rows = _rows("他用打火机点了一支烟。这台放大器很贵。我给妈妈打电话。", monkeypatch)
    assert _items(rows, "打", "colloc") == {"{w}电话": 1}
    assert _items(rows, "放", "colloc") == {}


def test_he_joining_two_nouns_is_and_and_an_adjective_after_de_has_no_coverb(monkeypatch):
    # 经济和社会发展, 经济、商业和文化发展: 和 joins nouns ("and") — most of 发展's 和〜 in the balanced build.
    # 他对公司的重要贡献: 重要 describes 贡献, so 对 is not its coverb. After a pronoun 和 stays one.
    rows = _rows("经济和社会发展很快。政府要推动经济、商业和文化发展。大家都记得他对公司的重要贡献。我和他见面了。",
                 monkeypatch)
    assert _items(rows, "发展", "particle") == {} and _items(rows, "重要", "particle") == {}
    assert _items(rows, "见面", "particle") == {"和": 1}


def test_a_verb_of_feeling_takes_degree_words_and_a_lexicalised_one_never(monkeypatch):
    # 很喜欢, 非常感谢 (one jieba word), 很忙 (one word, 忙 a verb), 越来越喜欢 — and 更新 "update" is not
    # 更 + 新.
    rows = _rows("我很喜欢这本书。我非常感谢你。我很忙。他越来越喜欢中文了。请更新你的软件。", monkeypatch)
    assert _items(rows, "喜欢", "form") == {"很{w}": 1} and "越来越〜" in _items(rows, "喜欢", "frame")
    assert _items(rows, "感谢", "form") == {"非常{w}": 1} and _items(rows, "忙", "form") == {"很{w}": 1}
    assert "更{w}" not in _items(rows, "新", "form")


def test_verbs_the_dictionary_files_as_nouns_pair_with_their_objects(monkeypatch):
    # 学 and 问 are filed `n`, 喝 `vg` (TAG_FIXES): 学中文, 问老师, 喝了茶 are pairs. 时 ("when", after a
    # clause) pairs with nothing: 他死时 and 你到时 are not a verb and its object.
    rows = _rows("我们一起学中文吧。你可以问老师。我喝了茶。他死时才三十岁。你到时给我打电话。", monkeypatch)
    assert "{w}中文" in _items(rows, "学", "colloc") and "{w}老师" in _items(rows, "问", "colloc")
    assert "{w}茶" in _items(rows, "喝", "colloc")
    assert _items(rows, "死", "colloc") == {} and _items(rows, "时", "colloc") == {}
    assert "{w}时" not in _items(rows, "到", "colloc")


def test_any_aspect_marker_may_stand_between_a_verb_and_its_object(monkeypatch):
    # 拿着书, 戴着眼镜, 拿著手機 (著 = 着) — as 打了电话 and 去过北京.
    rows = _rows("他拿着书走了。她戴着眼镜。她拿著手機。", monkeypatch)
    assert _items(rows, "拿", "colloc") == {"{w}书": 1, "{w}手机": 1}
    assert _items(rows, "戴", "colloc") == {"{w}眼镜": 1}


def test_a_noun_compound_takes_its_measure_word_at_its_head(monkeypatch):
    # Chinese noun phrases end in their head: 一名网球选手 counts 选手 (filed `v` by the dictionary — a
    # TAG_FIXES noun) and 一个中国人 counts 人, never 网球 or 中国. A noun that starts with a measure word is
    # one noun: 列车 is no 列〜 for 车, 一家人 no 家〜 for 人.
    rows = _rows("他是一名网球选手。我认识一个中国人。我坐一列车去上海。他们一家人都来了。", monkeypatch)
    assert _items(rows, "网球", "particle") == {} and _items(rows, "选手", "particle") == {"名": 1}
    assert _items(rows, "中国", "particle") == {} and _items(rows, "人", "particle") == {"个": 1}
    assert _items(rows, "车", "particle") == {}


def test_guanyu_opens_a_topic_and_is_no_coverb(monkeypatch):
    # 关于他的作品你知道哪些？ — KdConv asks it 106 times; 关于 is the topic, not 知道's argument.
    rows = _rows("关于他的作品你知道哪些？我对这个结果很满意。", monkeypatch)
    assert _items(rows, "知道", "particle") == {} and _items(rows, "满意", "particle") == {"对": 1}


def test_nouns_the_dictionary_files_as_verbs_get_their_measure_words(monkeypatch):
    # 看法 and 想法 are filed `v`, 同意 `d` (TAG_FIXES): 这种看法, 这个想法 count measure words; 同意了 is a form.
    # And the everyday verbs it files as nouns: 跟朋友聊天 (a coverb, not a measure word), 毕业了, 做作业 (a
    # verb and its object in one word).
    rows = _rows("这种看法很普遍。这个想法很好。他们都同意了。我跟朋友聊天。他去年毕业了。我在做作业。", monkeypatch)
    assert _items(rows, "看法", "particle") == {"种": 1} and _items(rows, "想法", "particle") == {"个": 1}
    assert _items(rows, "同意", "form") == {"{w}了": 1} and _items(rows, "毕业", "form") == {"{w}了": 1}
    assert _items(rows, "聊天", "particle") == {"跟": 1} and "{w}作业" in _items(rows, "做", "colloc")


def test_no_form_share_passes_one_hundred_percent(monkeypatch):
    # 很难 arrived fused (很难回答, jieba's guess) and separate (这件事很 / 难): both are uses of 难, so 很难 is 2 of
    # 难's 2 uses — the prototype, counting only the separate ones, had 很难 at 117% (§6.2). With the guesses off
    # both arrive separate.
    lemmas, _aliases, rows = _rows("这个问题很难回答。这件事很难。", monkeypatch)
    uses = {r[0]: r[4] for r in lemmas}
    forms = {r[3]: r[4] for r in rows if r[0] == "难" and r[2] == "form"}
    assert forms == {"很{w}": 2} and uses["难"] == 2 and "很难" not in uses
    assert all(r[4] <= uses[r[0]] for r in rows if r[2] == "form")


def test_aspect_complement_and_potential_forms(monkeypatch):
    # 买了, 去过, 笑著 (= 笑着), 看完, 放下, 看不懂.
    rows = _rows("我买了一本书。我去过北京。他笑著說。我看完了这本书。把东西放下吧。这个字我看不懂。", monkeypatch)
    assert "{w}了" in _items(rows, "买", "form") and "{w}过" in _items(rows, "去", "form")
    assert _items(rows, "笑", "form") == {"{w}着": 1}
    assert "{w}完" in _items(rows, "看", "form") and "{w}不懂" in _items(rows, "看", "form")
    assert "{w}下" in _items(rows, "放", "form")


def test_a_lexicalised_compound_is_never_a_form(monkeypatch):
    # 打开 is "open", 难过 "sad", 很快 "soon" — not 打 + 开, 难 + 过, 很 + 快.
    rows = _rows("请打开窗户。听到这个消息，我很难过。他很快就回来了。", monkeypatch)
    assert "{w}开" not in _items(rows, "打", "form")
    assert "{w}过" not in _items(rows, "难", "form")
    assert "很{w}" not in _items(rows, "快", "form")


def test_a_separable_verb_split_is_a_form(monkeypatch):
    # 洗了个澡, 生我的气, 见个面, 帮我一个忙 — read from the sentence (jieba cuts 洗 / 个 / 澡).
    rows = _rows("他洗了个澡就睡觉了。别生我的气。我们明天见个面吧。你能帮我一个忙吗？", monkeypatch)
    assert _items(rows, "洗澡", "form") == {"洗了个澡": 1}
    assert _items(rows, "生气", "form") == {"生我的气": 1}
    assert _items(rows, "见面", "form") == {"见个面": 1}
    assert _items(rows, "帮忙", "form") == {"帮我一个忙": 1}


def test_chance_pairs_are_not_splits(monkeypatch):
    # Tatoeba (WP-Z4): with a loose insertion rule, 190 of 213 splits were pairs of characters that make a
    # dictionary word by chance — 看一下 (看下), 听我说 (听说), 认识的人 (认人), 有足够的钱 (有钱), 不了解 (不解),
    # 下一步 (下步), 带我去 (带去). None is a separable verb split.
    rows = _rows("你看一下。你听我说。他是我认识的人。他有足够的钱。我不了解他。下一步怎么办？你带我去吧。", monkeypatch)
    splits = [r for r in rows[2] if r[2] == "form" and "{w}" not in r[3]]
    assert splits == []
    # …and the shapes the second Tatoeba pass found: a measure word counting its noun (买了辆车, 喝了杯茶), a
    # pronoun or a particle second (忘了我, 懂了吗), a numeral or a coverb first (几个字, 把他的手), the same
    # word twice (拍了拍), a verb, 着, a preposition (试着用).
    rows = _rows("他买了辆车。我喝了杯茶。你忘了我吗？你懂了吗？我认识几个字。他握住把他的手。他拍了拍我。你试着用吧。"
                 "这是不了义的说法。", monkeypatch)
    assert [r for r in rows[2] if r[2] == "form" and "{w}" not in r[3]] == []


def test_real_splits_the_wiktionary_list_misses_are_kept(monkeypatch):
    # 受了伤, 迷了路, 冒这个险 are separable verbs Wiktionary's category does not list; 搬了家 ends its clause.
    rows = _rows("他受了伤。我们迷了路。别冒这个险。他们去年搬了家。", monkeypatch)
    assert {r[0]: r[3] for r in rows[2] if r[2] == "form" and "{w}" not in r[3]} == \
        {"受伤": "受了伤", "迷路": "迷了路", "冒险": "冒这个险", "搬家": "搬了家"}


def test_the_next_shift_is_not_a_split_xiaban(monkeypatch):
    # 等下一班 is "wait for the next one", not 下班 split by 一 (NOT_SPLITS — 班吧 is no word, so nothing else
    # stops it); 请了个客人 is "invited a guest", not a split of 请客 — the second character must end a
    # word there, and 客人 is one.
    rows = _rows("这班车满了，我们等下一班吧。他请了个客人来家里吃饭。", monkeypatch)
    assert _items(rows, "下班", "form") == {} and _items(rows, "请客", "form") == {}


def test_a_vn_word_takes_the_line_with_more_slots(monkeypatch):
    # 影响 is a noun and a verb (`vn`): 这个影响 counts a measure word, 对我影响很大 a coverb twice — the
    # line is the coverb's; the measure word's rows are not written.
    rows = _rows("这个影响不小。台风对交通影响很大。对我影响很大。", monkeypatch)
    assert _items(rows, "影响", "particle") == {"对": 2}


def test_nothing_pairs_across_punctuation(monkeypatch):
    # 他买了书，电话 — 书 and 电话 never pair across the comma; 买 and 书 do.
    rows = _rows("他买了书，电话响了。", monkeypatch)
    assert "{w}书" in _items(rows, "买", "colloc")
    assert not any("电话" in item for item in _items(rows, "书", "colloc"))


def test_collocations_and_frames(monkeypatch):
    # 打电话 (one jieba word: verb + object), 看电影 (with the 吧 jieba glued on), 重要的事情, 这个〜, 〜里,
    # 〜们, 越来越〜 — and 看著 is 看 + the aspect marker, never a verb and its object.
    rows = _rows("我给妈妈打电话。我们去看电影吧。重要的事情要先做。这个问题很难。房间里很安静。朋友们都来了。"
                 "天气越来越冷了。他正看著電視。", monkeypatch)
    assert "打{w}" in _items(rows, "电话", "colloc") and "看{w}" in _items(rows, "电影", "colloc")
    assert "重要的{w}" in _items(rows, "事情", "colloc") and "{w}的事情" in _items(rows, "重要", "colloc")
    assert "这个〜" in _items(rows, "问题", "frame") and "〜里" in _items(rows, "房间", "frame")
    assert "〜们" in _items(rows, "朋友", "frame") and "越来越〜" in _items(rows, "冷", "frame")
    assert not any("著" in item for item in _items(rows, "看", "colloc"))


def test_a_candidate_is_stored_but_never_a_line(monkeypatch):
    # The gate (WP-Z6) made 压力很大 (subject–predicate: 很大 is 很 + 大, so the pair is 压力 + 大) and 认真地学习
    # pairs; 在家〜 (the coverb's noun) is still counted and filed `cand`, never shown.
    rows = _rows("我最近压力很大。他认真地学习。我们在家吃饭。", monkeypatch)
    assert "{w}大" in _items(rows, "压力", "colloc") and "{w}地学习" in _items(rows, "认真", "colloc")
    assert "在家〜" in _items(rows, "吃饭", "cand") and "在家〜" not in _items(rows, "吃饭", "colloc")


def test_a_subject_pair_needs_an_adjective_ending_its_clause(monkeypatch):
    # 天气很冷。身体好吗？ are pairs. 中国最大的公司 (最大 describes 公司), 水平显著提高 (显著 is an adverb),
    # 国家安全 (one noun, 安全 `an`) and 中心主任 (主任 `b`, never a predicate) are not.
    rows = _rows("天气很冷。他身体好吗？这是中国最大的公司。学生水平显著提高了。我们要维护国家安全。中心主任来了。",
                 monkeypatch)
    assert _items(rows, "天气", "colloc") == {"{w}冷": 1} and _items(rows, "身体", "colloc") == {"{w}好": 1}
    for noun in ("中国", "水平", "国家", "中心"):          # no subject pair ({w} first); 是中国 is the copula's object
        assert not [item for item in _items(rows, noun, "colloc") if item.startswith("{w}")], noun


def test_an_object_that_is_a_noun_compound_pairs_at_its_head(monkeypatch):
    # 维护国家安全: 维护 keeps 安全 safe, not 国家 — the object's head is its last noun (解决实际问题 → 解决问题).
    # A one-character last noun is no head: 告全国民众书 (an open letter) is no 告 + 书.
    rows = _rows("我们要维护国家安全。他们解决实际问题。他们发表了告全国民众书。", monkeypatch)
    assert _items(rows, "维护", "colloc") == {"{w}安全": 1} and _items(rows, "解决", "colloc") == {"{w}问题": 1}
    assert _items(rows, "国家", "colloc") == {} and _items(rows, "实际", "colloc") == {}
    assert "告{w}" not in _items(rows, "书", "colloc")


def test_a_traditional_spelling_is_an_alias_of_the_simplified_word(monkeypatch):
    lemmas, aliases, _rows_ = _rows("這個問題很重要。这个问题很重要。", monkeypatch)
    assert ("问题", "", "问题", "n", 2) in lemmas
    assert {(a[0], a[1]) for a in aliases} >= {("問題", "问题"), ("问题", "问题")}


# --- the quality redesign's Chinese part (Patterns_Quality_Spec.md §10, E4–E7) ------------------------ #
def test_chinese_keeps_its_own_form_share_when_japanese_lowers_its_own(monkeypatch):
    # E7: Japanese lowers patterns_build.FORM_SHARE to 0.05 (§8.1 c); a Chinese build keeps 0.10 as built. 买了
    # is 1 of 买's 12 uses here (8%) — Japanese's share would keep it, Chinese's does not; 卖了, 1 of 卖's 2,
    # is kept. MIN_PATTERN stays shared (patched as in `_rows`).
    from modules.junban import patterns_build as pb
    monkeypatch.setattr(pb, "MIN_PATTERN", 1)
    monkeypatch.setattr(pb, "FORM_SHARE", 0.05)
    text = ("我昨天买了一本书。你想买什么？我们去超市买水果吧。他每天早上都买报纸。妈妈让我去市场买鸡蛋。"
            "这件衣服太贵，我不买。我要买一张去北京的火车票。他没有钱买新房子。她喜欢在网上买衣服。你能帮我买一杯咖啡吗？"
            "我们应该买一台新电脑。爸爸打算买一辆车。他卖了旧房子。他想卖他的车。")
    rows = pz.score(pz.count(pz.iter_tokens(text, frozenset(BOUNDARIES)), pb.Counts()), 1)
    assert pz.FORM_SHARE == 0.10 and {r[0]: r[4] for r in rows[0]}["买"] == 12
    assert _items(rows, "买", "form") == {} and _items(rows, "卖", "form") == {"{w}了": 1}


def test_a_noun_that_ends_like_a_verb_and_its_complement_is_not_a_form(monkeypatch):
    # E5: 演唱会 is a concert and 教会 a church, not 演唱 + 会 or 教 + 会 — the shared set showed 演唱 `演唱会 45%`,
    # 活 `活动 90%`, 闪 `闪光 32%`. A word the dictionary files as a noun that ends in 会, 动 or 光 is that noun:
    # its first part gets no form from it, and no use (活's count no longer holds every 活动).
    rows = _rows("我们周末去听演唱会。他们下周举行研讨会。周末我们有个聚会。他每个星期天都去教会。这完全是一个误会。"
                 "学校组织了很多活动。电脑启动得很慢。天空中出现了一道闪光。", monkeypatch)
    for stem in ("演唱", "研讨", "聚", "教", "误", "活", "启", "闪"):
        assert _items(rows, stem, "form") == {}, stem
    uses = {r[0]: r[4] for r in rows[0]}
    assert "活" not in uses and uses["活动"] == 1 and uses["演唱会"] == 1


def test_real_forms_jieba_files_as_nouns_keep_their_forms(monkeypatch):
    # The noun tag alone would take real forms too: jieba files 睁开, 染上, 伪装成, 写信给, 折射出, 咽下 as `n` and
    # 托付给 as `vn` — only the endings 会 / 动 / 光 make the noun. 开会 and 转会 are verbs (`v`), and the modal
    # 会 on its own (可能 会) is no fused token: all keep their forms. 学会 is the accepted cost (U12): filed
    # as a noun ("a society"), it is no longer a form of 学.
    rows = _rows("他慢慢睁开了眼睛。他染上了重感冒。小偷伪装成警察的样子。她把孩子托付给我。我每个月写信给妈妈。"
                 "水面折射出美丽的光。他咽下最后一口饭。我们明天上午开会。他转会到另一支球队。明天可能会下雨。"
                 "我学会了游泳。", monkeypatch)
    assert {stem: _items(rows, stem, "form") for stem in ("睁", "染", "伪装", "托付", "写信", "折射", "咽", "开",
                                                          "转", "可能")} == \
        {"睁": {"{w}开": 1}, "染": {"{w}上": 1}, "伪装": {"{w}成": 1}, "托付": {"{w}给": 1}, "写信": {"{w}给": 1},
         "折射": {"{w}出": 1}, "咽": {"{w}下": 1}, "开": {"{w}会": 1}, "转": {"{w}会": 1}, "可能": {"{w}会": 1}}
    assert _items(rows, "学", "form") == {}


def test_an_adverb_pairs_with_the_verb_right_after_it(monkeypatch):
    # E6: jieba files 马上 已经 一直 终于 as `d`, which no rule counted — their cards said "no pattern clears
    # the floors". An adverb and the verb right after it are now the adverb's pairing, in its own section (DV).
    rows = _rows("我们马上出发。他已经走了。她一直哭。我们终于见面了。", monkeypatch)
    assert {r[0]: (r[3], r[6]) for r in rows[2] if r[2] == "colloc"} == \
        {"马上": ("{w}出发", "DV"), "已经": ("{w}走", "DV"), "一直": ("{w}哭", "DV"), "终于": ("{w}见面", "DV")}


def test_an_adverb_before_a_verb_counts_once_and_the_verb_keeps_its_side(monkeypatch):
    # 突然 is `ad` (an adjective class) and 失控 `vn` (a noun too), so the adjective + noun rule paired them by
    # accident: on 突然's card 突然失控 is now DV's alone, never also AN's. The verb keeps AN's side of it —
    # 努力工作 on 工作 is a real pairing (41 cards would lose one: the Chinese judge, 2026-09-25) — but a `d`
    # adverb gives a verb nothing back (every verb would fill with 不〜, 也〜, 都〜). An adverb pairs only with
    # the verb right after it (马上就来: 就来, not 马上来); an adjective (`a`) before a noun that is also a verb
    # stays AN (重要影响), and so does 突然的变化.
    rows = _rows("他突然失控了。我们马上出发。我马上就来。这对经济产生了重要影响。这是一个突然的变化。", monkeypatch)
    assert sorted((r[3], r[4], r[6]) for r in rows[2] if r[0] == "突然" and r[2] == "colloc") == \
        [("{w}失控", 1, "DV"), ("{w}的变化", 1, "AN")]
    assert _items(rows, "失控", "colloc") == {"突然{w}": 1} and _items(rows, "出发", "colloc") == {}
    assert _items(rows, "马上", "colloc") == {"{w}出发": 1} and _items(rows, "就", "colloc") == {"{w}来": 1}
    assert _items(rows, "重要", "colloc") == {"{w}影响": 1} and _items(rows, "影响", "colloc") == {"重要{w}": 1}


def test_zai_closed_by_a_localizer_after_the_word_is_a_frame_not_its_coverb(monkeypatch):
    # E4 rule 1: 在老师的帮助下 is the frame 在〜下 around 帮助, not 在 introducing an argument of it — the shared
    # set showed 帮助 `在〜 62%`, from such frames. So are 在他的影响下, 在大家的支持下, 在经济发展中, and 在家学习中
    # (在家 is one jieba word). 影响, a noun too, keeps its frame 〜下.
    rows = _rows("在老师的帮助下，他进步了。在他的影响下，我开始学习中文。在大家的支持下，我们成功了。"
                 "在经济发展中，我们遇到了问题。在家学习中遇到问题。", monkeypatch)
    for word in ("帮助", "影响", "支持", "发展", "学习"):
        assert _items(rows, word, "particle") == {}, word
    assert "〜下" in _items(rows, "影响", "frame")


def test_only_the_frames_zai_goes_and_a_direction_complement_keeps_its_coverb(monkeypatch):
    # jieba cuts 在墙上挂上 and 请在这里躺下 as 挂 / 上 and 躺 / 下: 上 or 下 after a one-character verb is its
    # direction complement, and 在 its coverb (181 of the 5,674 在 slots before a localizer in the balanced
    # build: 写上, 贴上, 住下). And only 在 makes the frame: 影响 keeps 对〜 (台风对交通影响很大).
    rows = _rows("他在墙上挂上一幅画。我在门上贴上通知。他在北京住下了。请在这里躺下。我们在公园散步。"
                 "在他的影响下，我开始学习中文。台风对交通影响很大。", monkeypatch)
    for word in ("挂", "贴", "住", "躺", "散步"):
        assert _items(rows, word, "particle") == {"在": 1}, word
    assert _items(rows, "影响", "particle") == {"对": 1}


# --- the build ------------------------------------------------------------------------------------ #
def _zh_library(files):
    """Write `{relative path: text}` under data/zh (sandboxed by conftest)."""
    from app.path_utils import get_data_path
    root = get_data_path("zh")
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return root


def _db_rows(db, sql):
    import sqlite3
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_a_chinese_build_writes_the_same_schema(tmp_path):
    # The same four tables as Japanese (the store, lookup and packages serve both), keyed (word, ""),
    # and a meta that says what it is: zh, keyed in Simplified, cut with or without reinforce.
    from modules.junban import patterns_build as pb
    from modules.junban.patterns_store import Store
    _zh_library({"HighPriority/样本.txt": _read("patterns_zh_sample.txt")})
    db = str(tmp_path / "patterns_zh.db")
    meta = pb.build(db_path=db, language="zh", floor=1)
    columns = {t: [c[1] for c in _db_rows(db, f"PRAGMA table_info({t})")] for t in ("lemma", "alias", "pattern", "meta")}
    assert columns == {"lemma": ["lemma", "reading", "orth", "pos", "count"],
                       "alias": ["orth", "lemma", "reading", "count"],
                       "pattern": ["lemma", "reading", "kind", "item", "count", "logdice", "section", "files"],
                       "meta": ["key", "value"]}
    stored = dict(_db_rows(db, "SELECT key, value FROM meta"))
    assert (stored["language"], stored["script"], stored["reinforce"], stored["builder_version"]) == \
        ("zh", "s", "False", str(pz.BUILDER_VERSION))
    assert meta["files"] == 1 and not _db_rows(db, "SELECT * FROM lemma WHERE reading != ''")
    store = Store(db)
    try:
        assert store.word("问题", "")[:2] == ("问题", "n")
    finally:
        store.close()


def test_the_cli_builds_the_language_it_is_given(tmp_path, capsys):
    # `junban_patterns --language zh` builds the Chinese library into patterns_zh.db — never Japanese's.
    from modules.junban import patterns_build as pb
    _zh_library({"HighPriority/样本.txt": "这个问题很重要。我们需要解决这个问题。"})
    assert pb.main(["--language", "zh"]) == 0
    assert "Built: 1 files" in capsys.readouterr().out
    assert os.path.exists(pb.default_db_path("zh")) and not os.path.exists(pb.default_db_path("ja"))
    assert dict(_db_rows(pb.default_db_path("zh"), "SELECT key, value FROM meta"))["language"] == "zh"


def test_a_parallel_chinese_build_equals_a_single_process_one(tmp_path, monkeypatch):
    # Preparing the general corpora uses many processes; the answer must not depend on how many. One file
    # per batch, so the parts are counted apart (in spawned workers, each loading jieba) and merged.
    from modules.junban import patterns_build as pb
    lines = _read("patterns_zh_sample.txt").splitlines()
    _zh_library({f"HighPriority/part{i}.txt": "\n".join(lines[i::3]) for i in range(3)})
    monkeypatch.setattr(pb, "_batches", lambda paths: ([p] for p in paths))
    one, two = str(tmp_path / "one.db"), str(tmp_path / "two.db")
    pb.build(db_path=one, language="zh", floor=1)
    pb.build(db_path=two, language="zh", floor=1, workers=2)
    for table in ("lemma", "alias", "pattern"):
        assert sorted(_db_rows(one, f"SELECT * FROM {table}")) == sorted(_db_rows(two, f"SELECT * FROM {table}"))


@pytest.mark.parametrize("text, split", [
    ("一碗", ("一", "碗", "")),          # [NUM+CL] + noun: 一碗 牛肉面
    ("这家", ("这", "家", "")),          # [DEM+CL] + noun: 这家 店
    ("两辆车", ("两", "辆", "车")),       # [NUM+CL+N] fused whole
    ("每个", ("每", "个", "")),
    ("3本", ("3", "本", "")),
    ("我把", None),                      # a pronoun is never a numeral: 我把书 is the preposition 把
    ("三次", None),                      # a verbal measure word: 打了三次电话 counts nothing for 电话
    ("他家", None),                      # "his home", not a measure word
])
def test_a_fused_measure_word_is_taken_apart(text, split):
    assert pz.split_classifier(text) == split


def test_line_one_names_its_kind_and_every_pattern_counts_its_documents(tmp_path):
    # Builder 2 (Patterns_Quality_Spec §10 E1, E4): a pairing must be seen in three documents — here three
    # staged blocks of a general corpus — and line 1 says whether it is a measure word (Q) or a coverb (P),
    # so the lookup can hide a thin coverb row without touching a measure word's.
    from modules.junban import patterns_build as pb
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "staged.txt").write_text("我买了一本书。\n\n她买了一本书。\n\n我们买了一本书。\n", encoding="utf-8")
    db = str(tmp_path / "patterns_zh_general.db")
    pb.build(corpus_dir=str(corpus), db_path=db, language="zh", floor=1)
    assert _db_rows(db, "SELECT item, section, files FROM pattern WHERE lemma = '书' AND kind = 'particle'") \
        == [("本", "Q", 3)]
    assert _db_rows(db, "SELECT item, files FROM pattern WHERE lemma = '买' AND kind = 'form'") == [("{w}了", 3)]
