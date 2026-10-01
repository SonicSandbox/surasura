"""Words made of words: dictionary compounds are one word, and a sound word + と is that word.

UniDic's short units cut a compound into the words it is made of — 上層部 is 上層 + 部, 一生懸命 一生 + 懸命, and in
a sentence 取り掛かる is 取り + 掛かる — so the list counted 上層 and 部 and never offered the word the content says.
`analyzer.join_affixes` joins such a run back where its spelling is a compound headword of JPDB 2024 or Jiten
(reference_data's compound table, with the list's reading): nouns, places and な-words (kind N), a word holding a
numeral that counts nothing (Q), a verb + a verb (V). Guards keep a person's name, a plural, a count and a run across
a space apart; a katakana compound no dictionary lists gives way to a katakana name around it. It also makes a sound word ending in っ + と one token, the sound word shown with と (ドキッと is どき).

Made-up and dictionary sentences throughout, checked against the project's fugashi + unidic-lite. Where a rule needs
an entry the shipped table may not carry, a small table of its own is handed to the join (as test_affix_join does).
"""

import sys

import pytest

from app import analyzer, names


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


@pytest.fixture
def sanitized(monkeypatch):
    """Every analyzer run sanitizes Japanese lemmas (glossed loanwords: バッグ-bag)."""
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)


def _entry(lemma, reading, kind="N", flags=0):
    """A compound table entry as reference_data ships it: [lemma, reading, kind, flags]."""
    return [lemma, reading, kind, flags]


def _surfaces(tokenizer, text, compounds=None, joins=None):
    """The tokens one line becomes, joined with `compounds` (None: the shipped table)."""
    return [w.surface for w in analyzer.join_affixes(tokenizer.tagger(text), joins, library=False,
                                                     compounds=compounds)]


def _word(tokenizer, text, surface, compounds=None, joins=None):
    """The token of `text` whose surface is `surface`."""
    words = analyzer.join_affixes(tokenizer.tagger(text), joins, library=False, compounds=compounds)
    return next(w for w in words if w.surface == surface)


def _keys(tokenizer, text):
    return [(lemma, reading) for lemma, reading, _surface, _orth in tokenizer.tokenize(text)]


# --- B: noun compounds, with the list's reading ------------------------------------------------------------------ #
@pytest.mark.parametrize("sentence, key", [
    ("上層部の決定に従う。", ("上層部", "ジョウソウブ")),
    ("秘密結社に入った。", ("秘密結社", "ヒミツケッシャ")),
    ("中途半端な気持ちだ。", ("中途半端", "チュウトハンパ")),
    ("株式会社を作る。", ("株式会社", "カブシキガイシャ")),     # the list's reading: never the parts' カイシャ
])
def test_a_dictionary_compound_is_one_word_with_the_lists_reading(tokenizer, sanitized, sentence, key):
    # The list must name what the content says — 上層部, not 上層 and 部 twice over.
    assert _keys(tokenizer, sentence)[0] == key


def test_a_compound_keeps_its_parts_and_the_texts_own_spelling(tokenizer):
    word = _word(tokenizer, "上層部の決定に従う。", "上層部")
    assert isinstance(word, analyzer.JoinedWord) and [s for s, _ in word.parts] == ["上層", "部"]
    assert (word.feature.pos1, word.feature.orthBase) == ("名詞", "上層部")
    assert word.feature.pos2 != "固有名詞"            # a common word, never a name


def test_a_place_can_be_a_part(tokenizer):
    # 日本 and 鳥取 are place names to UniDic (固有名詞・地名); 日本語 and 鳥取県 are words all the same.
    table = {"日本語": _entry("日本語", "ニホンゴ"), "鳥取県": _entry("鳥取県", "トットリケン")}
    assert _surfaces(tokenizer, "日本語を話す。", table)[:2] == ["日本語", "を"]
    assert _surfaces(tokenizer, "鳥取県に住む。", table)[:2] == ["鳥取県", "に"]


def test_a_na_word_part_and_the_class_the_last_part_gives(tokenizer):
    # A な-word last makes a な-word (一生懸命に働く, 自信満々な顔 — 満々 is UniDic's タリ class); a な-word first
    # makes a noun (好き放題).
    table = {"一生懸命": _entry("一生懸命", "イッショウケンメイ"), "自信満々": _entry("自信満々", "ジシンマンマン"),
             "好き放題": _entry("好き放題", "スキホウダイ")}
    assert _word(tokenizer, "一生懸命に働く。", "一生懸命", table).feature.pos1 == "形状詞"
    assert _word(tokenizer, "自信満々な顔だ。", "自信満々", table).feature.pos1 == "形状詞"
    assert _word(tokenizer, "好き放題にする。", "好き放題", table).feature.pos1 == "名詞"


def test_the_longest_compound_wins_from_the_left(tokenizer):
    table = {"経済成長": _entry("経済成長", "ケイザイセイチョウ"), "成長期": _entry("成長期", "セイチョウキ"),
             "経済成長期": _entry("経済成長期", "ケイザイセイチョウキ")}
    assert _surfaces(tokenizer, "経済成長期の日本。", table)[:2] == ["経済成長期", "の"]
    del table["経済成長期"]
    # Without the longer word the first one met from the left is taken: 経済成長 + 期, never 経済 + 成長期.
    assert _surfaces(tokenizer, "経済成長期の日本。", table)[:2] == ["経済成長", "期"]


# --- numeral words: a numeral that counts nothing ---------------------------------------------------------------- #
def test_a_numeral_word_joins_where_its_numeral_counts_nothing(tokenizer, sanitized):
    # 二十歳 はたち and 十人十色 (four pieces: 十 + 人 + 十 + 色) are words; the table holds them as numeral words.
    table = {"二十歳": _entry("二十歳", "ハタチ", "Q"), "十人十色": _entry("十人十色", "ジュウニントイロ", "Q")}
    word = _word(tokenizer, "二十歳の誕生日を祝う。", "二十歳", table)
    assert (word.feature.lemma, word.feature.lForm) == ("二十歳", "ハタチ")
    assert analyzer.word_lemma(word) == "二十歳"          # a word, though a number is no word
    assert _surfaces(tokenizer, "十人十色の考え方がある。", table)[0] == "十人十色"


@pytest.mark.parametrize("text, pieces", [
    ("二日後にまた来ます。", ["二", "日"]),
    ("五分待つ。", ["五", "分"]),
    ("十円玉を拾う。", ["十", "円", "玉"]),
    ("弟は三年生になった。", ["三", "年", "生"]),
])
def test_counts_stay_apart(tokenizer, text, pieces):
    # A count is no word (二日 'two days', 五分 'five minutes'): the numeral and its counter stay apart, and no
    # compound is read after the number that counts it.
    words = _surfaces(tokenizer, text)
    start = words.index(pieces[0])
    assert words[start:start + len(pieces)] == pieces


def test_a_run_that_starts_with_a_numeral_joins_only_a_numeral_word(tokenizer):
    # Only an entry the build judged a numeral word may start with a numeral; any other kind never does.
    assert _surfaces(tokenizer, "二日後にまた来ます。", {"二日": _entry("二日", "フツカ")})[:2] == ["二", "日"]
    # ...and only from the first numeral of its run: 三十 + 八 + 番 is never 三十 + 八番.
    table = {"八番": _entry("八番", "ハチバン", "Q")}
    assert _surfaces(tokenizer, "八番の席。", table)[0] == "八番"
    assert _surfaces(tokenizer, "三十八番の席。", table)[:3] == ["三十", "八", "番"]


def test_a_numeral_inside_a_word_counts_nothing(tokenizer):
    # 精一杯 is 精 + 一杯 to the tagger in one sentence and 精 + 一 + 杯 in another; both spell the word, whose
    # numeral sits inside it, after a piece that is no number.
    table = {"精一杯": _entry("精一杯", "セイイッパイ"), "力一杯": _entry("力一杯", "チカライッパイ")}
    assert "精一杯" in _surfaces(tokenizer, "精一杯やった。", table)
    assert "精一杯" in _surfaces(tokenizer, "今日も精一杯した。", table)
    assert "力一杯" in _surfaces(tokenizer, "彼は力一杯投げた。", table)
    # a numeral word never ends in a bare number
    assert _surfaces(tokenizer, "今日も精一杯した。", {"精一": _entry("精一", "セイイチ", "Q")})[2:4] == ["精", "一"]


# --- compound verbs ---------------------------------------------------------------------------------------------- #
def test_a_compound_verb_is_one_verb_keyed_by_its_dictionary_form(tokenizer):
    # A verb in its 連用形 + a verb, keyed as the first is written and the second in its dictionary form: 走り + 出し
    # is 走り出す, conjugating as the second verb does.
    table = {"走り出す": _entry("走り出す", "ハシリダス", "V"), "取り掛かる": _entry("取り掛かる", "トリカカル", "V")}
    word = _word(tokenizer, "初恋は走り出した。", "走り出し", table)
    assert (word.feature.pos1, word.feature.lemma, word.feature.lForm) == ("動詞", "走り出す", "ハシリダス")
    assert word.feature.cForm.startswith("連用形")
    # UniDic keeps 取り掛かる whole alone and cuts it in some sentences: one verb either way.
    assert "取り掛かる" in _surfaces(tokenizer, "彼女は早速料理に取り掛かる。", table)


def test_a_verb_after_a_verbal_noun_and_suru_stays_apart(tokenizer):
    # 始める after 勉強し builds by grammar, not the dictionary (the table leaves such verbs out) — and する is never
    # a first verb, whatever a table says.
    assert _surfaces(tokenizer, "食べ始めた。")[:2] == ["食べ", "始め"]
    table = {"し始める": _entry("し始める", "シハジメル", "V")}
    assert _surfaces(tokenizer, "勉強し始める。", table)[:3] == ["勉強", "し", "始める"]


# --- the guards, one by one (each table offers the join; the rule itself must refuse it) --------------------------- #
def test_a_persons_name_is_never_a_part(tokenizer):
    table = {"田中部長": _entry("田中部長", "タナカブチョウ")}
    assert _surfaces(tokenizer, "田中部長が来た。", table)[:2] == ["田中", "部長"]


def test_a_plural_is_never_joined(tokenizer):
    # The lists carry 先生方 (センセイガタ) — a plural, as 子供たち is. 相手方 アイテカタ 'the other party' is a word.
    table = {"先生方": _entry("先生方", "センセイガタ"), "相手方": _entry("相手方", "アイテカタ")}
    assert _surfaces(tokenizer, "先生方が来た。", table)[:2] == ["先生", "方"]
    assert _surfaces(tokenizer, "相手方の意見。", table)[0] == "相手方"


def test_after_a_number_only_a_compound_the_number_does_not_count_joins(tokenizer):
    table = {"円玉": _entry("円玉", "エンダマ"), "得意気": _entry("得意気", "トクイゲ")}
    assert _surfaces(tokenizer, "10円玉を拾う。", table)[:3] == ["10", "円", "玉"]     # 10 counts 円
    assert _surfaces(tokenizer, "円玉を拾う。", table)[0] == "円玉"
    # 何 is tagged a number (as in 何人), but here it is "what": 得意気 is no count of it.
    assert "得意気" in _surfaces(tokenizer, "何得意気にしゃべってんだよ！", table)


def test_never_across_a_space(tokenizer):
    table = {"上層部": _entry("上層部", "ジョウソウブ")}
    assert _surfaces(tokenizer, "上層 部の決定。", table)[:2] == ["上層", "部"]
    assert _surfaces(tokenizer, "上層部の決定。", table)[0] == "上層部"


def test_a_grammar_stem_is_no_part(tokenizer):
    # みたい is UniDic's 形状詞・助動詞語幹 — grammar ('like'), not a な-word: バカみたい is バカ + みたい.
    table = {"バカみたい": _entry("バカみたい", "バカミタイ")}
    assert _surfaces(tokenizer, "悩むなんてバカみたいだ。", table)[-4:-2] == ["バカ", "みたい"]


def test_phrases_and_titles_join_only_while_the_switch_is_on(tokenizer, monkeypatch):
    # A phrase or a title the dictionaries mark (予想通り) is one word by default; switched off, its parts. Every
    # other compound joins either way.
    table = {"予想通り": _entry("予想通り", "ヨソウドオリ", flags=1), "上層部": _entry("上層部", "ジョウソウブ")}
    assert _surfaces(tokenizer, "予想通りの結果だ。", table)[0] == "予想通り"
    monkeypatch.setitem(analyzer.LOGIC, "phrases_and_titles", False)
    assert _surfaces(tokenizer, "予想通りの結果だ。", table)[:2] == ["予想", "通り"]
    assert _surfaces(tokenizer, "上層部の決定。", table)[0] == "上層部"


# --- words the text writes as words; a verb's stem inside a noun (the mark 8) ------------------------------------ #
# The table also holds headwords the tagger reads otherwise alone, as general text writes them: 出来損ない 'a failure'
# is 出来 + 損ない (two nouns) in a sentence and 出来る + 損なう (two verbs) alone. A noun compound JMdict lists as a noun
# that the text, or the word alone, writes with a verb's stem carries the mark 8, and a run of nouns and stems that
# spells it joins too: anywhere when it ends in a noun, but when it ends in a stem only at the end of its line.
_FAILURE = "出来損ない"


def test_a_word_the_text_writes_as_nouns_is_one_word_there(tokenizer):
    # No mark needed: in a sentence 出来 and 損ない are nouns, a run the compound join takes as it is.
    table = {_FAILURE: _entry(_FAILURE, "デキソコナイ")}
    word = _word(tokenizer, "この出来損ないの計画はもう捨てよう。", _FAILURE, table)
    assert (word.feature.pos1, word.feature.lemma, word.feature.lForm) == ("名詞", _FAILURE, "デキソコナイ")
    assert [s for s, _ in word.parts] == ["出来", "損ない"]


def test_the_word_alone_is_one_word_with_the_mark_and_two_verbs_without_it(tokenizer):
    # A card or a known word holds the word alone, which the tagger reads as two verbs: one word only with the mark.
    assert _surfaces(tokenizer, _FAILURE, {_FAILURE: _entry(_FAILURE, "デキソコナイ", flags=8)}) == [_FAILURE]
    assert _surfaces(tokenizer, _FAILURE, {_FAILURE: _entry(_FAILURE, "デキソコナイ")}) == ["出来", "損ない"]
    word = _word(tokenizer, _FAILURE, _FAILURE, {_FAILURE: _entry(_FAILURE, "デキソコナイ", flags=8)})
    assert (word.feature.pos1, word.feature.lemma) == ("名詞", _FAILURE)   # the noun, never a verb's conjugation
    # closing punctuation after it is still the end of the line (「出来損ない」 on a card, 出来損ない。)
    assert _surfaces(tokenizer, "「出来損ない」", {_FAILURE: _entry(_FAILURE, "デキソコナイ", flags=8)}) == \
        ["「", _FAILURE, "」"]


def test_a_run_starting_with_a_stem_joins_anywhere(tokenizer):
    # 待ち here is 待つ's stem, 立ち 立つ's: the run ends in a noun, so it is the noun wherever it stands.
    table = {"待ち時間": _entry("待ち時間", "マチジカン", flags=8), "立ち位置": _entry("立ち位置", "タチイチ", flags=8)}
    assert _surfaces(tokenizer, "駅での待ち時間はいつも長い。", table)[3] == "待ち時間"
    assert _surfaces(tokenizer, "自分の立ち位置を考える。", table)[2] == "立ち位置"
    # without the mark the stem stays the verb's
    assert _surfaces(tokenizer, "駅での待ち時間はいつも長い。", {"待ち時間": _entry("待ち時間", "マチジカン")})[3:5] == \
        ["待ち", "時間"]


def test_a_run_ending_in_a_stem_joins_only_at_the_end_of_its_line(tokenizer):
    # 拍子抜け alone on a line (a card, a known word) is the noun; before した it is the verb's stem, and 位置づけ before
    # て is the verb 位置付ける — a sentence never joins a run that ends in a stem.
    table = {"拍子抜け": _entry("拍子抜け", "ヒョウシヌケ", flags=8), "位置づけ": _entry("位置付け", "イチヅケ", flags=8)}
    assert _surfaces(tokenizer, "拍子抜け。", table) == ["拍子抜け", "。"]
    assert _surfaces(tokenizer, "拍子抜けした。", table)[:2] == ["拍子", "抜け"]
    assert _surfaces(tokenizer, "彼を中心に位置づけて考える。", table)[4:7] == ["位置", "づけ", "て"]


def test_a_stem_is_a_verbs_plain_stem_never_suru_or_a_sound_change(tokenizer):
    def node(text, surface):
        return next(w for w in tokenizer.tagger(text) if w.surface == surface)
    assert analyzer._stem(node("駅での待ち時間は長い。", "待ち"))
    assert not analyzer._stem(node("勉強した。", "し"))            # する's 連用形: never a noun's part
    assert not analyzer._stem(node("健康を損なった。", "損なっ"))    # a sound change comes only before た / て
    assert not analyzer._stem(node("この先は通行止めです。", "止め"))  # read as the noun here: a noun part, no stem


def test_a_stem_run_keeps_the_guards_of_any_compound(tokenizer, monkeypatch):
    # The phrases-and-titles switch: a marked phrase (flags 1 | 8) stays apart with the switch off, whichever path.
    table = {"待ち時間": _entry("待ち時間", "マチジカン", flags=9)}
    assert _surfaces(tokenizer, "駅での待ち時間はいつも長い。", table)[3] == "待ち時間"
    monkeypatch.setitem(analyzer.LOGIC, "phrases_and_titles", False)
    assert _surfaces(tokenizer, "駅での待ち時間はいつも長い。", table)[3:5] == ["待ち", "時間"]
    monkeypatch.undo()
    # Right after a number that counts its first part, never (10 + 円玉); a plural, never. The run below is 時間 + a
    # verb's stem, so only the stem path could join it.
    three, hours = tokenizer.tagger("三時間")
    stem = next(w for w in tokenizer.tagger("駅での待ち時間は長い。") if w.surface == "待ち")
    stop = tokenizer.tagger("。")[0]
    entry = ("時間待ち", "ジカンマチ", "N", 8)
    assert analyzer._joins_with_stems([hours, stem, stop], 0, [hours, stem], entry, True)
    assert not analyzer._joins_with_stems([three, hours, stem, stop], 1, [hours, stem], entry, True)
    assert not analyzer._joins_with_stems([hours, stem, stop], 0, [hours, stem], ("時間待ち", "ジカンマチ", "N", 0), True)
    # never a verb + verb or a numeral word, whatever its mark; never more than three words
    assert not analyzer._joins_with_stems([hours, stem, stop], 0, [hours, stem], ("時間待ち", "ジカンマチ", "V", 8), True)


def test_the_shipped_tables_read_the_word_the_text_writes_as_words(tokenizer, sanitized):
    # 出来損ない is in the shipped table with the mark: one word in a sentence, alone (a card), and at a line's end;
    # its parts are 出来 + 損ない, and 損ない is bound (no word of its own a learner meets outside it).
    assert analyzer.compound_joins()[_FAILURE][:3] == (_FAILURE, "デキソコナイ", "N")
    assert analyzer.compound_joins()[_FAILURE][3] & 8
    for text in ("この出来損ないの計画はもう捨てよう。", _FAILURE, "「出来損ない」"):
        assert (_FAILURE, "デキソコナイ") in _keys(tokenizer, text), text
    assert [(p[0], p[2]) for p in analyzer.compound_parts()[(_FAILURE, "デキソコナイ")]] == [("出来", True),
                                                                                         ("損ない", False)]
    # 立ち位置 is written 立ち[立つ] + 位置 far more often than as two nouns: its parts are that reading's, the verb a
    # learner knows (立つ), never the rare noun 立ち
    assert analyzer.compound_parts()[("立ち位置", "タチイチ")][0][:2] == ("立つ", "タツ")
    # the verb 損なう on its own stays itself
    assert ("損なう", "ソコナウ") in _keys(tokenizer, "健康を損なう。")


def test_a_katakana_word_is_left_to_the_katakana_name_rule(tokenizer):
    # ダンボール (ダン, read as a name, + ボール) is kept whole by the katakana rule (app/names.py); a compound entry
    # would take the spelling from that rule and then refuse the name's piece, so the table holds no katakana-only word
    # the text alone vouched for.
    assert "ダンボール" not in analyzer.compound_joins()
    assert _surfaces(tokenizer, "ダンボール箱を運んだ。")[0] == "ダンボール"


def test_without_the_dictionaries_table_the_word_alone_stays_in_pieces(tokenizer, monkeypatch):
    # The mark is app/dictionary_data.py's: without that module a sentence's noun run still joins (the table holds the
    # word), and the word alone is two verbs as before — never an error.
    monkeypatch.setattr(analyzer, "_DICTIONARY", [None])
    assert _surfaces(tokenizer, _FAILURE) == ["出来", "損ない"]
    assert _surfaces(tokenizer, "この出来損ないの計画はもう捨てよう。")[1] == _FAILURE


# --- known words ------------------------------------------------------------------------------------------------- #
def _known(folder, *words):
    import json
    folder.mkdir()
    path = folder / "KnownWord.json"
    path.write_text(json.dumps({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in words]},
                               ensure_ascii=False), encoding="utf-8")
    return analyzer.load_known_words(str(path), analyzer.JapaneseTokenizer())


def test_a_known_compound_marks_its_parts_known_and_not_the_reverse(tmp_path, sanitized):
    # Knowing 秘密結社 is knowing 秘密 and 結社 too; knowing both parts does not make the compound known — it stays
    # a word to learn, with its own card and reading.
    tuples, lemmas = _known(tmp_path / "compound", "秘密結社")
    assert ("秘密結社", "ヒミツケッシャ") in tuples
    assert ("秘密", "ヒミツ") in tuples and ("結社", "ケッシャ") in tuples and "結社" in lemmas
    tuples, lemmas = _known(tmp_path / "parts", "秘密", "結社")
    assert ("秘密結社", "ヒミツケッシャ") not in tuples and "秘密結社" not in lemmas


# --- a compound takes its affixes; the order with names ------------------------------------------------------------ #
def test_a_compound_takes_its_prefix_and_suffixes(tokenizer):
    table = {"同性愛": _entry("同性愛", "ドウセイアイ")}
    joins = {"同性愛者": ["同性愛者", "ドウセイアイシャ"]}
    words = analyzer.join_affixes(tokenizer.tagger("同性愛者の権利。"), joins, library=False, compounds=table)
    assert words[0].surface == "同性愛者" and words[0].feature.lemma == "同性愛者"
    assert [s for s, _ in words[0].parts] == ["同性愛", "者"]
    # Without the compound, the suffix finds no word to join.
    assert _surfaces(tokenizer, "同性愛者の権利。", {}, joins)[:3] == ["同性", "愛", "者"]
    # A prefix too: 新 + 自由主義.
    table, joins = {"自由主義": _entry("自由主義", "ジユウシュギ")}, {"新自由主義": ["新自由主義", "シンジユウシュギ"]}
    assert _surfaces(tokenizer, "新自由主義の経済。", table, joins)[:2] == ["新自由主義", "の"]
    # A compound that meets no affix leaves the rest of the line as the first pass made it.
    assert _surfaces(tokenizer, "新自由主義と新幹線。", table, dict(joins, 新幹線=["新幹線", "シンカンセン"]))[:4] == \
        ["新自由主義", "と", "新幹線", "。"]


def test_a_listed_katakana_compound_is_the_word_it_spells_never_a_name(tokenizer):
    # Half-width katakana is read as full width before the join.
    table = {"トートバッグ": _entry("トートバッグ", "トートバッグ")}
    for text in ("トートバッグを持つ。", "ﾄｰﾄﾊﾞｯｸﾞを持つ。"):
        word = analyzer.join_affixes(tokenizer.tagger(text), None, library=False, compounds=table)[0]
        assert (word.feature.lemma, word.is_unk) == ("トートバッグ", False), text


# A katakana compound no dictionary of the language lists gives way to a katakana name around it. ビルデイング, an old
# spelling of ビルディング 'building', is one loanword; the tagger cuts it ビル + デ + イング, and the katakana-name rule
# (app/names.py) keeps that run whole (デ is no common word). The frequency lists' tail spells ビルデ (ビル + デ) — JMdict has no such word — and
# joined first it would leave ビルデ + イング, two listed words, in pieces. The dictionaries' table marks such a compound
# (flag 4); one JMdict lists (フジテレビ) carries no mark and keeps its join.
_BUILDING = "石造りの古いビルデイングが並んでいる。"


def test_an_unlisted_katakana_compound_gives_way_to_the_name_around_it(tokenizer):
    table = {"ビルデ": _entry("ビルデ", "ビルデ", flags=4)}
    words = analyzer.join_affixes(tokenizer.tagger(_BUILDING), None, library=False, compounds=table)
    word = next(w for w in words if w.surface.startswith("ビル"))
    assert (word.surface, word.feature.lemma, word.is_unk) == ("ビルデイング", "ビルデイング", True)
    assert [s for s, _ in word.parts] == ["ビル", "デ", "イング"]
    # The same line with the compound unmarked is today's reading: the compound cuts the name.
    assert _surfaces(tokenizer, _BUILDING, {"ビルデ": _entry("ビルデ", "ビルデ")})[3:5] == ["ビルデ", "イング"]


def test_a_katakana_compound_jmdict_lists_keeps_its_join_inside_a_longer_run(tokenizer):
    # フジテレビ (Fuji TV) + アナウンサー 'announcer': a network and a job, two words a learner knows apart. Without the
    # compound, フジ (a name piece) makes the whole run one unknown word; フジテレビ is listed, so it carries no mark.
    table = {"フジテレビ": _entry("フジテレビ", "フジテレビ")}
    assert _surfaces(tokenizer, "元フジテレビアナウンサーの女性が司会を務めた。", table)[1:3] == ["フジテレビ", "アナウンサー"]
    # On a line where a marked compound gives way, the listed one beside it still keeps its join.
    table = dict(table, ビルデ=_entry("ビルデ", "ビルデ", flags=4))    # a new table: the join caches one per table
    words = _surfaces(tokenizer, "フジテレビアナウンサーが古いビルデイングの前に立った。", table)
    assert words[:2] == ["フジテレビ", "アナウンサー"] and "ビルデイング" in words


def test_a_marked_compound_that_is_the_whole_run_or_among_common_words_still_joins(tokenizer, monkeypatch):
    # Alone, ビルデ is the listed word it spells — there is no longer name to give way to; across a space the runs are
    # apart. Among common words (トート + バッグ + ショップ) the katakana-name rule keeps the run in pieces: no name.
    table = {"ビルデ": _entry("ビルデ", "ビルデ", flags=4), "トートバッグ": _entry("トートバッグ", "トートバッグ", flags=4)}
    assert _surfaces(tokenizer, "ビルデの前で待つ。", table)[0] == "ビルデ"
    assert _surfaces(tokenizer, "ビルデ イング", table) == ["ビルデ", "イング"]
    assert _surfaces(tokenizer, "トートバッグショップに寄った。", table)[:2] == ["トートバッグ", "ショップ"]
    # A marked compound that is the whole run is the table's word, with its reading — never made a name of.
    whole = {"ビルデイング": _entry("ビルデイング", "ビルデイング", flags=4)}
    word = _word(tokenizer, _BUILDING, "ビルデイング", whole)
    assert (word.is_unk, word.feature.kana) == (False, "ビルデイング")
    # The mark is no phrase or title: the "Phrases and titles" switch never puts such a compound in its parts.
    monkeypatch.setitem(analyzer.LOGIC, "phrases_and_titles", False)
    assert _surfaces(tokenizer, "ビルデの前で待つ。", table)[0] == "ビルデ"


def test_with_katakana_names_off_a_marked_compound_joins_as_before(tokenizer, monkeypatch):
    # Nothing to give way to: with Settings -> Katakana names off, the run stays as the compound join leaves it.
    monkeypatch.setitem(analyzer.LOGIC, "names_katakana", False)
    table = {"ビルデ": _entry("ビルデ", "ビルデ", flags=4)}
    assert _surfaces(tokenizer, _BUILDING, table)[3:5] == ["ビルデ", "イング"]


def test_the_shipped_marks_and_what_they_do_without_the_dictionaries_table(tokenizer, monkeypatch):
    # The shipped tables mark ビルデ and not フジテレビ; without app/dictionary_data.py there is no mark, and the line
    # reads as it did before the marks (the compound cuts the name) — never an error.
    table = analyzer.compound_joins()
    assert table["ビルデ"][3] & 4 and not table["フジテレビ"][3] & 4
    assert "ビルデイング" in _surfaces(tokenizer, _BUILDING)
    assert _surfaces(tokenizer, "元フジテレビアナウンサーの女性が司会を務めた。")[1:3] == ["フジテレビ", "アナウンサー"]
    monkeypatch.setattr(analyzer, "_DICTIONARY", [None])
    assert not analyzer.compound_joins()["ビルデ"][3] & 4
    assert _surfaces(tokenizer, _BUILDING)[3:5] == ["ビルデ", "イング"]


@pytest.fixture
def library_names():
    """A made-up library whose name table holds 成長期 — as a name — three times over."""
    names.use_library_tables({"k": {}, "j": {"成長期": [3, "成長期", "", "成長期"]}, "stamp": "test"}, pin=True)
    yield
    names.forget_library_tables()


def test_a_name_from_the_library_never_cuts_a_compound(tokenizer, library_names):
    # The library's names are found on the joined words: the dictionary word is judged first.
    words = analyzer.join_affixes(tokenizer.tagger("経済成長期の日本。"), None, library=True, compounds={})
    assert [w.surface for w in words][:2] == ["経済", "成長期"]
    table = {"経済成長": _entry("経済成長", "ケイザイセイチョウ")}
    words = analyzer.join_affixes(tokenizer.tagger("経済成長期の日本。"), None, library=True, compounds=table)
    assert [w.surface for w in words][:2] == ["経済成長", "期"]


# --- the っ rule: a sound word + と is that word, shown with と ----------------------------------------------------- #
def test_a_sound_word_with_its_to_is_one_token_of_the_sound_words_own_row(tokenizer, sanitized):
    assert _keys(tokenizer, "胸がドキッとした。")[2] == ("どき", "ドキ")
    lemma, reading, surface, orth = tokenizer.tokenize("胸がドキッとした。")[2]
    assert (surface, orth) == ("ドキッと", "ドキッと")
    # the same row as ドキッ said alone — one word, one known status
    assert ("どき", "ドキ") in _keys(tokenizer, "ドキッ！")
    assert _keys(tokenizer, "ぐっと来る。")[0] == ("ぐっ", "グッ")
    # read as full width first
    assert _keys(tokenizer, "ﾄﾞｷｯとした。")[0] == ("どき", "ドキ")


@pytest.mark.parametrize("text, pieces", [
    ("ポンと叩く。", ["ポン", "と"]),          # its と is optional: listed bare, the card's ending bridges it
    ("「バシッ」と音がした。", ["バシッ", "」", "と"]),
    ("バシッ！と閉めた。", ["バシッ", "！", "と"]),
    ("行っとくよ。", ["行っ", "とく"]),        # a verb, not a sound word
])
def test_only_a_sound_word_right_before_its_to_is_joined(tokenizer, text, pieces):
    words = _surfaces(tokenizer, text)
    start = words.index(pieces[0])
    assert words[start:start + len(pieces)] == pieces


# --- the table, the accessors, and the edges ----------------------------------------------------------------------- #
def test_words_stay_in_pieces_when_the_compound_table_cannot_be_read(tokenizer, monkeypatch):
    # CLAUDE.md "fail gracefully": every caller tokenizes through the table, so a missing one leaves UniDic's
    # pieces, never raises — and the sound-word rule, which needs no table, still holds.
    import app
    monkeypatch.delattr(app, "reference_data")
    monkeypatch.setitem(sys.modules, "app.reference_data", None)
    assert analyzer.compound_joins() == {} and analyzer.compound_parts() == {}
    assert _surfaces(tokenizer, "上層部の決定。")[:2] == ["上層", "部"]
    assert _surfaces(tokenizer, "ドキッとした。")[0] == "ドキッと"


def test_the_dictionaries_marks_and_polite_words_are_merged_in(monkeypatch):
    # app/dictionary_data.py (the dictionaries' own part, CC BY-SA) adds flags to the compound table and お/ご words
    # to the affix table; without it both tables are reference_data's as they are. The real module is set aside
    # first — it lists お守り itself — so the base tables are reference_data's alone.
    monkeypatch.setattr(analyzer, "_DICTIONARY", [None])
    base = analyzer.compound_joins()
    assert base and "お守り" not in analyzer.affix_joins()
    entry = base["上層部"]
    flags, polite = {"上層部": 1}, {"お守り": ["お守り", "オマモリ"]}

    class Dictionaries:             # its accessors decode once and hand out the same table, as reference_data's do
        compound_flags = staticmethod(lambda: flags)
        ogo_joins = staticmethod(lambda: polite)
    monkeypatch.setattr(analyzer, "_DICTIONARY", [Dictionaries])
    # The marks go into the one table, in place (no copy of it): a marked word gets a new entry.
    assert analyzer.compound_joins() is base and base["上層部"][3] & 1 and entry[3] == 0
    assert analyzer.affix_joins()["お守り"] == ["お守り", "オマモリ"]
    assert analyzer.compound_joins() is analyzer.compound_joins()        # merged once
    # Without the marks again, the table is as reference_data decoded it; with the real module, its marks.
    monkeypatch.setattr(analyzer, "_DICTIONARY", [None])
    assert analyzer.compound_joins()["上層部"] is entry
    monkeypatch.undo()
    assert analyzer.compound_joins()["上層部"] is entry and analyzer.compound_joins()["もののけ姫"][3] == 3


def test_compound_parts_are_keyed_as_a_run_keys_the_word(monkeypatch):
    # Two spellings of one word read the parts of the one spelled as its lemma; every kind has parts.
    from app import reference_data
    table = {"予定どおり": _entry("予定通り", "ヨテイドオリ"), "予定通り": _entry("予定通り", "ヨテイドオリ"),
             "走り出す": _entry("走り出す", "ハシリダス", "V")}
    parts_of = {"予定通り": [["予定", "ヨテイ", 1], ["通り", "トオリ", 0]],
                "予定どおり": [["予定", "ヨテイ", 1], ["どおり", "ドオリ", 0]],
                "走り出す": [["走る", "ハシル", 1], ["出す", "ダス", 1]]}
    monkeypatch.setattr(analyzer, "compound_joins", lambda: table)
    monkeypatch.setattr(reference_data, "compound_parts", lambda: parts_of)
    parts = analyzer.compound_parts()
    assert parts[("予定通り", "ヨテイドオリ")] == (("予定", "ヨテイ", True), ("通り", "トオリ", False))
    assert parts[("走り出す", "ハシリダス")] == (("走る", "ハシル", True), ("出す", "ダス", True))
    assert analyzer.compound_parts() is parts


def test_the_shipped_table_and_its_parts(sanitized):
    # The parts are a table of their own, decoded only where they are asked for (never to tokenize).
    lemma, reading, kind, _flags = analyzer.compound_joins()["上層部"]
    assert (lemma, reading, kind) == ("上層部", "ジョウソウブ", "N")
    assert [part[:2] for part in analyzer.compound_parts()[("上層部", "ジョウソウブ")]] == [("上層", "ジョウソウ"),
                                                                                       ("部", "ブ")]


@pytest.mark.parametrize("text", ["", "……！？", "上層部の決定。\r\n秘密結社だ。\r\n", "iPhoneの上層部"])
def test_edges_empty_text_symbols_crlf_and_mixed_scripts(tokenizer, sanitized, text):
    words = [lemma for lemma, _r, _s, _o in tokenizer.tokenize(text)]
    if "上層部" in text:
        assert "上層部" in words and "上層" not in words
    else:
        assert words == []


def test_a_joined_compound_outlives_the_taggers_next_call(tokenizer):
    # A fugashi node is only valid until the tagger runs again; a joined word is built from copies.
    joined = analyzer.join_affixes(tokenizer.tagger("秘密結社"), compounds={"秘密結社": _entry("秘密結社", "ヒミツケッシャ")})[0]
    tokenizer.tagger("全然違う話だ")
    assert (joined.surface, joined.feature.lemma, [s for s, _ in joined.parts]) == ("秘密結社", "秘密結社", ["秘密", "結社"])
