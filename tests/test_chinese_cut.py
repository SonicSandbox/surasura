"""The one Chinese cut (analyzer.chinese_cut) and word test (analyzer.chinese_word) that every Chinese caller reads —
the tokenizer, the パターン builder and its card lookups — so a word is keyed alike everywhere.

jieba, the cutter, works from a dictionary that holds phrases no dictionary lists as words (吃了饭 'ate', 一碗 'a bowl
(of)', 电影吧 'the film, then', 很多 'very many'). The cut reads such an entry as its words where its words hold grammar
— an aspect marker after its verb, a particle after its word, a number or this / that before a measure word — and
leaves whole what CC-CEDICT lists (这个, 一下, 出租车), names jieba tags as names, and doubled words; a count CC-CEDICT
lists is its number and its measure word (一个 is 一 + 个). Real sentences: tests/Test Resources/zh and
dictionary-example lines.
"""
import os

import pytest

from app import analyzer

ZH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Test Resources", "zh")


def _cut(text):
    return analyzer.chinese_cut(text)


@pytest.mark.parametrize("sentence, entry, words", [
    ("我已经吃了饭。", "吃了饭", ["吃", "了", "饭"]),                 # an aspect marker after its verb
    ("他们去年结了婚。", "结了婚", ["结", "了", "婚"]),               # inside an entry jieba tags a verb
    ("我去过北京，也去过上海。", "去过", ["去", "过"]),
    ("我们中午吃了一碗牛肉面。", "一碗", ["一", "碗"]),              # a number before a measure word
    ("我给他打了三次电话。", "三次", ["三", "次"]),
    ("这次我们去看电影吧。", "这次", ["这", "次"]),                  # this / that before a measure word
    ("这次我们去看电影吧。", "电影吧", ["电影", "吧"]),               # a sentence-final particle after its word
    ("我很着急。", "很着急", ["很", "着急"]),                       # the degree adverb
    ("我有很多朋友。", "很多", ["很", "多"]),
    ("我买了一个苹果。", "一个", ["一", "个"]),                     # a count CC-CEDICT lists: number + measure word
    ("一万二千名学生参加了考试。", "一万二千名", ["一万二千", "名"]),   # a number in pieces is one piece
])
def test_a_phrase_entry_is_read_as_its_words(sentence, entry, words):
    import jieba
    assert entry in list(jieba.cut(sentence, cut_all=False)), "jieba's own dictionary makes it one token"
    pieces = _cut(sentence)
    start = sentence.index(entry)
    covered, pos = [], 0
    for piece in pieces:
        if start <= pos < start + len(entry):
            covered.append(piece)
        pos += len(piece)
    assert covered == words, pieces


@pytest.mark.parametrize("sentence, word", [
    ("这个问题很重要。", "这个"),          # CC-CEDICT lists it: the dictionary wins
    ("每个人都有自己的梦想。", "每个"),
    ("我有一些朋友。", "一些"),            # a number + more that the treebanks keep whole
    ("我们一起去吧。", "一起"),
    ("我坐出租车去酒吧。", "出租车"),
    ("我坐出租车去酒吧。", "酒吧"),
    ("你看着办吧。", "看着办"),
    ("我受不了了。", "受不了"),
    ("我听得懂中文。", "听得懂"),
    ("你什么时候喝咖啡？", "喝咖啡"),      # no grammar inside: a phrase entry left as jieba has it
    ("这块农业用地很大。", "农业用地"),    # 地 'land' after a noun is no adverb-making 地
    ("地安门在北京。", "地安门"),          # nor first
    ("他录得一千万的收入。", "录得"),      # 得 last is 'obtain', no complement
    ("你在说甚么？", "甚么"),              # 么 after an adverb is no sentence-final particle
    ("王小明是我的朋友。", "王小明"),      # a name jieba tags as one
    ("开开心心地玩。", "开开心心"),        # a doubled word, for its base to read
])
def test_what_a_dictionary_lists_and_grammar_doesnt_hold_stays_whole(sentence, word):
    assert word in _cut(sentence)


@pytest.mark.parametrize("text", [
    "我已经吃了饭。", "", "！？……", "我考了HSK四级。", "他认真地学习，一万二千名学生参加了考试。\n第二行。\r\n",
])
def test_the_pieces_spell_the_text(text):
    assert "".join(_cut(text)) == text


def test_with_the_table_missing_the_cut_is_jiebas(monkeypatch):
    # app/cedict_data.py can't be read: the cut degrades to jieba's dictionary words, never a crash.
    import jieba
    monkeypatch.setitem(analyzer._CEDICT, "splits", {})
    monkeypatch.setitem(analyzer._CEDICT, "surnames", frozenset())
    sentence = "我已经吃了饭，这次我们去看电影吧。李明来了。"
    assert _cut(sentence) == list(jieba.cut(sentence, cut_all=False, HMM=False))


def test_an_unreadable_table_module_is_an_empty_table(monkeypatch):
    import sys
    import app
    monkeypatch.setattr(analyzer, "_CEDICT", {})
    monkeypatch.delattr(app, "cedict_data", raising=False)
    monkeypatch.setitem(sys.modules, "app.cedict_data", None)      # the import fails
    assert analyzer._cedict_table("splits") == {}
    assert "吃了饭" in _cut("我已经吃了饭。")
    assert _cut("他来了。") == ["他", "来", "了", "。"], "no table: no guess kept either"


def test_a_table_that_fails_to_decode_is_an_empty_table(monkeypatch):
    from app import cedict_data

    def corrupt():
        raise ValueError("a damaged table")
    monkeypatch.setattr(analyzer, "_CEDICT", {})
    monkeypatch.setattr(cedict_data, "splits", corrupt)
    assert analyzer._cedict_table("splits") == {}


def test_the_tokenizer_counts_the_words_of_a_phrase_entry():
    tok = analyzer.ChineseTokenizer()
    words = [w for _s, ts in tok.tokenize_sentences("我们中午吃了一碗牛肉面，这次去看电影吧。") for w, *_ in ts]
    assert "吃了饭" not in words and "电影吧" not in words
    assert {"吃", "了", "碗", "电影", "吧", "次"} <= set(words)


def test_traditional_text_is_cut_alike_and_keeps_its_spelling():
    # The table is keyed in Simplified; the tokenizer slices each word from the text as written.
    tok = analyzer.ChineseTokenizer()
    words = [w for _s, ts in tok.tokenize_sentences("我們中午吃了一碗牛肉麵。") for w, *_ in ts]
    assert words[:5] == ["我們", "中午", "吃", "了", "碗"], "and the number is no word"


def test_the_patterns_sample_reads_its_phrase_entries_as_words():
    with open(os.path.join(ZH, "patterns_zh_sample.txt"), encoding="utf-8") as handle:
        text = handle.read()
    tok = analyzer.ChineseTokenizer()
    words = [w for _s, ts in tok.tokenize_sentences(text) for w, *_ in ts]
    assert "一碗" not in words and "这家" not in words
    assert {"碗", "家", "这个", "每个"} <= set(words), "the measure words count; CC-CEDICT's 这个 and 每个 stay whole"


# --- numbers ------------------------------------------------------------------------------------------------ #
def _counted(text):
    tok = analyzer.ChineseTokenizer()
    return [w for _s, ts in tok.tokenize_sentences(text) for w, *_ in ts]


@pytest.mark.parametrize("text, gone, kept", [
    ("我们学校有三千五百个学生。", "三千五百", "个"),       # a number said is no word; its measure word is
    ("他今年二十五岁。", "二十五", "岁"),
    ("我们一起吃了一碗饭。", "一", "碗"),
    ("我有两个苹果。", "两", "个"),
    ("十一国庆节放假。", "十一", "国庆节"),                  # 'eleven' — 'National Day' is CC-CEDICT's name sense
    ("今天是二〇一六年。", "〇", "今天"),
    ("一百十个人来了。", "一百十", "个"),                    # 110 — 百十 'a hundred or so' is a quantity, no word
])
def test_a_number_is_no_word(text, gone, kept):
    words = _counted(text)
    assert gone not in words and kept in words, words


@pytest.mark.parametrize("text, word", [
    ("你千万不要去！", "千万"),            # 'by all means' counts nothing
    ("万一下雨怎么办？", "万一"),          # 'just in case'
    ("他是个二百五。", "二百五"),          # 'idiot'
    ("他把钱包拾了起来。", "拾"),          # 'pick up' — a financial numeral, no numeral of running text
    ("他是第一。", "第一"),                # an ordinal holds 第
    ("问题我们一一解决。", "一一"),        # 'one by one'
])
def test_a_word_made_of_numerals_that_counts_nothing_stays_a_word(text, word):
    assert word in _counted(text)


def test_a_line_of_numbers_alone_has_no_word():
    assert _counted("一，二，三。") == []


def test_the_word_test_reads_traditional_numbers_too():
    assert not analyzer.chinese_word("兩") and not analyzer.chinese_word("一萬") and analyzer.chinese_word("萬一")


def test_with_the_table_unreadable_no_number_is_dropped(monkeypatch):
    # The NOT_COUNTS table spares 千万 and 万一: without it the test drops nothing rather than every number-like word.
    monkeypatch.setitem(analyzer._CEDICT, "not_counts", frozenset())
    assert analyzer.chinese_word("三千五百") and analyzer.chinese_word("千万")


# --- doubled forms ------------------------------------------------------------------------------------------ #
def _tokens(text, script="asis"):
    tok = analyzer.ChineseTokenizer(script=script)
    return [(w, surface) for _s, ts in tok.tokenize_sentences(text) for w, _r, surface, _o in ts]


@pytest.mark.parametrize("text, word, form", [
    ("大家都开开心心的。", "开心", "开开心心"),            # AABB: the form's word, the form kept as its surface
    ("她高高兴兴地回家了。", "高兴", "高高兴兴"),
    ("我们想要一个干干净净的环境。", "干净", "干干净净"),
    ("方方面面都考虑到了。", "方面", "方方面面"),          # 'all aspects' ~ 'aspect': glosses matched by stem
    ("你應該休息休息。", "休息", "休息休息"),              # a word of two characters said twice
    ("我们一起研究研究这个问题。", "研究", "研究研究"),
    ("哈哈哈哈哈！", "哈哈", "哈哈哈哈哈"),                # a run of a laugh, however jieba cut it
    ("外面的狗一直在叫：汪汪汪！", "汪汪", "汪汪汪"),
    ("爸爸妈妈都来了。", "爸妈", "爸爸妈妈"),              # accepted: 'dad and mom' is 爸妈 'mom and dad'
])
def test_a_doubled_form_counts_as_its_word(text, word, form):
    tokens = _tokens(text)
    assert (word, form) in tokens, tokens
    assert form not in [w for w, _s in tokens]


@pytest.mark.parametrize("text, kept", [
    ("这里有形形色色的人。", ["形形色色"]),                # a meaning of its own: 'all kinds of', not 'shape and color'
    ("他做事马马虎虎的。", ["马马虎虎"]),                  # 'so-so', not 马虎 'careless'
    ("人人都好。", ["人人"]),                              # two characters are never folded
    ("请你看看。", ["看看"]),
    ("你慢慢走。", ["慢慢"]),
    ("汤姆说他想问我一个个人问题。", ["个", "个人"]),       # no doubling: 一 + 个 + 个人
    ("好好好！", ["好好", "好"]),                          # a run folds only to a sound: 好好 'well' is none
    ("他们三三两两地走了。", ["三三两两"]),                # numerals only: the numbers' rule (a word that counts nothing)
])
def test_what_is_no_doubled_word_stays_as_it_is(text, kept):
    words = [w for w, _s in _tokens(text)]
    start = words.index(kept[0])
    assert words[start:start + len(kept)] == kept, words


def test_a_comma_between_keeps_two_uses():
    assert [w for w, _s in _tokens("休息，休息。")] == ["休息", "休息"]


def test_a_doubled_form_keeps_the_texts_script():
    assert _tokens("開開心心") == [("開心", "開開心心")]
    assert _tokens("開開心心", "s") == [("开心", "开开心心")]
    assert _tokens("开开心心", "t") == [("開心", "開開心心")]


def test_the_cut_joins_a_run_and_a_word_said_twice_into_one_piece():
    assert "休息休息" in _cut("你应该休息休息。")
    assert "哈哈哈哈哈" in _cut("哈哈哈哈哈！")
    assert "".join(_cut("哈哈哈哈哈！你应该休息休息。")) == "哈哈哈哈哈！你应该休息休息。"


def test_a_known_doubled_form_makes_its_word_known(tmp_path):
    import json
    path = tmp_path / "KnownWord.json"
    path.write_text(json.dumps({"words": [{"dictForm": "开开心心", "knownStatus": "KNOWN"}]}, ensure_ascii=False),
                    encoding="utf-8")
    known_tuples, known_lemmas = analyzer.load_known_words(str(path), analyzer.ChineseTokenizer())
    assert ("开心", "") in known_tuples and "开心" in known_lemmas


def test_with_the_table_unreadable_nothing_is_folded(monkeypatch):
    monkeypatch.setitem(analyzer._CEDICT, "folds", frozenset())
    assert analyzer.chinese_base("开开心心") is None and analyzer.chinese_base("休息休息") is None
    assert analyzer.chinese_base("哈哈哈") is None



# --- the guesses off, a name kept ----------------------------------------------------------------------------- #
@pytest.mark.parametrize("sentence, pieces", [
    ("他来了。", ["他", "来"]),                    # jieba's model glued a pronoun to its verb: two words
    ("我要一杯咖啡。", ["我", "要"]),
    ("这是我的书。", ["这", "是"]),
    ("我家离学校很近。", ["很", "近"]),
    ("你别生我的气。", ["别", "生"]),              # led by 别, no surname
])
def test_a_guess_that_glues_words_is_its_words(sentence, pieces):
    cut = _cut(sentence)
    start = cut.index(pieces[0])
    assert cut[start:start + len(pieces)] == pieces, cut


@pytest.mark.parametrize("sentence, name", [
    ("李明是我的朋友。", "李明"),                  # a surname leads it: kept whole
    ("王芳来了。", "王芳"),                        # jieba guessed 王芳来: the name is kept, 来 is its verb
])
def test_a_guessed_name_led_by_a_surname_stays_whole(sentence, name):
    assert name in _cut(sentence)


def test_a_guessed_name_glued_to_its_verb_keeps_its_first_two_characters():
    # 龙仁用 is the name 龙仁 + the verb 用: three characters ending in a verb, so its head is tried.
    cut = _cut("于是，龙仁用一尊龙神像设下神圣封印。")
    start = cut.index("龙仁")
    assert cut[start:start + 2] == ["龙仁", "用"], cut


def test_a_dictionary_word_is_never_guessed_at():
    # 王小明 is a jieba entry: the dictionary keeps it, and no guard ever cuts it to 王小 + 明.
    assert "王小明" in _cut("王小明是学生。")
