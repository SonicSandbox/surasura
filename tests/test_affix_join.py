"""Words keep their prefixes and suffixes (Patterns_Quality_Spec.md Part A, §6).

UniDic's short units cut 接頭辞 and 接尾辞 off a word, so the list counted 幹線 for 新幹線, 可能 for
可能性 and 日本 for 日本人, and never offered the word the content says. `analyzer.join_affixes` joins
such a run back when the joined form is a dictionary word — a JPDB 2024 / Jiten headword, shipped in
`app/reference_data.py` with its reading — and nothing else: names, counts and name honorifics stay
pieces. Real Japanese sentences throughout, checked against the project's fugashi + unidic-lite.
"""

import json

import pandas as pd
import pytest
from unittest.mock import patch

from app import analyzer, reference_data, sentence_corpus


@pytest.fixture(scope="module")
def tokenizer():
    return analyzer.JapaneseTokenizer()


@pytest.fixture
def sanitized(monkeypatch):
    """Every analyzer run sanitizes Japanese lemmas (glossed loanwords: アメリカ-America)."""
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)


def _words(tokenizer, text):
    return [lemma for lemma, _reading, _surface, _orth in tokenizer.tokenize(text)]


def _keys(tokenizer, text):
    return [(lemma, reading) for lemma, reading, _surface, _orth in tokenizer.tokenize(text)]


@pytest.mark.parametrize("sentence, word", [
    ("新幹線に乗った。", "新幹線"),           # 新 + 幹線: a prefix
    ("小学校の先生。", "小学校"),
    ("可能性がある。", "可能性"),             # 可能 + 性: a suffix
    ("具体的な話。", "具体的"),
    ("違和感がある。", "違和感"),             # 感 is filed as a noun, but builds words like a suffix
    ("利用者が多い。", "利用者"),
    ("不自然な動きだ。", "不自然"),
    ("お願いします。", "お願い"),             # お + a verb's 連用形 used as a noun
])
def test_a_word_with_its_prefix_or_suffix_is_one_word(tokenizer, sanitized, sentence, word):
    # The list must name what the content says — not 幹線, 可能, 自然 or 利用.
    assert word in _words(tokenizer, sentence)


@pytest.mark.parametrize("text, pieces", [
    ("田中さんが来た。", ["タナカ", "さん"]),   # a person's name and its honorific
    ("私たちの家。", ["私", "達"]),            # a plural suffix
    ("第3話", ["第", "3", "話"]),            # nothing after a number is a base
    ("三回目", ["三", "回", "目"]),            # 回目 IS a headword — but it follows a number
    ("3年生", ["3", "年", "生"]),
    ("レーマン人", ["レーマン", "人"]),         # a name + 人 is no dictionary word
    ("不自然さ", ["不自然", "さ"]),            # the user (U2): さ stays, and counts toward 不自然
    ("霊子", ["霊", "子"]),                  # one list's long tail, a name read タマコ (checkpoint A)
    ("エジプト人", ["エジプト", "人"]),         # one list only, past its top 60,000
])
def test_names_numbers_plurals_and_long_tail_headwords_stay_in_pieces(tokenizer, sanitized, text, pieces):
    words = _words(tokenizer, text)
    assert words[:len(pieces)] == pieces, words


@pytest.mark.parametrize("sentence, key", [
    ("母さんが呼んでいる。", ("母さん", "カアサン")),        # not 母 read はは + さん
    ("皆さん、こんにちは。", ("皆さん", "ミナサン")),
    ("神様に祈った。", ("神様", "カミサマ")),
    ("お客様が来た。", ("お客様", "オキャクサマ")),
    ("お嬢さんが来た。", ("お嬢さん", "オジョウサン")),
    ("お母さんが来た。", ("お母さん", "オカアサン")),        # through お母, which is no word
])
def test_a_dictionary_word_that_ends_in_an_honorific_is_one_word(tokenizer, sanitized, sentence, key):
    # The user (checkpoint A): "join honorific words" — each with its own reading.
    assert _keys(tokenizer, sentence)[0] == key


def test_the_longest_dictionary_word_wins_even_through_a_piece_that_is_no_word():
    # お母 is not in the table, お母さん is: the join looks past the piece. Alone, お母 stays お + 母.
    tagger = analyzer.JapaneseTokenizer().tagger
    table = {"お母さん": ["お母さん", "オカアサン"]}
    assert [w.surface for w in analyzer.join_affixes(tagger("お母さんが来た"), table)][:2] == ["お母さん", "が"]
    assert [w.surface for w in analyzer.join_affixes(tagger("お母が来た"), table)][:3] == ["お", "母", "が"]
    # And past a word to a longer one: 心理学 is a word, but the text says 心理学者.
    assert [w.surface for w in analyzer.join_affixes(tagger("心理学者になる"))][:2] == ["心理学者", "に"]


def test_a_headword_joins_when_both_lists_have_it_or_one_ranks_it_high():
    # The user (checkpoint A): both JPDB 2024 and Jiten, or one's top 60,000. The lists' long tails are
    # names and misreadings (霊子 タマコ, 新大橋 シンオオハ, 金家 カナヤ); everyday one-list words stay.
    joins = reference_data.affix_joins()
    for word in ("宇宙人", "母上", "情熱的", "敷地内", "新幹線", "違和感"):
        assert word in joins, word
    for word in ("霊子", "新大橋", "金家", "エジプト人"):
        assert word not in joins, word


def test_every_spelling_of_a_word_is_one_word(tokenizer, sanitized):
    # The user (checkpoint A): おすすめ, お勧め and オススメ are one list word, under the best-ranked
    # spelling — and each text keeps its own spelling to show.
    tokens = [tokenizer.tokenize(s)[0] for s in ("おすすめの本。", "お勧めの本。", "オススメの本。")]
    assert {(lemma, reading) for lemma, reading, _surface, _orth in tokens} == {("おすすめ", "オススメ")}
    assert [orth for _lemma, _reading, _surface, orth in tokens] == ["おすすめ", "お勧め", "オススメ"]
    assert _keys(tokenizer, "面倒臭い")[0] == _keys(tokenizer, "面倒くさい")[0]
    # An お word joins or not as one word: 御金 is too rare to decide alone, お金 carries it.
    assert _keys(tokenizer, "御金を払った。")[0] == ("お金", "オカネ")


def test_knowing_one_spelling_knows_them_all(tmp_path, sanitized):
    # A KnownWord おしゃべり used to leave the text's お喋り unknown.
    tuples, _lemmas = _known(tmp_path, "おしゃべり")
    assert _keys(analyzer.JapaneseTokenizer(), "お喋りな人だ。")[0] in tuples


@pytest.mark.parametrize("text, allowed, expected", [
    ("田中さんが来た", "田中さん", ["田中", "さん"]),    # a name takes no honorific, listed or not
    ("子供たちの声", "子供たち", ["子供", "たち"]),     # nor a plural suffix
    ("三回目の挑戦", "回目", ["三", "回", "目"]),      # nothing after a number is a base
    ("不自然さを感じる", "不自然さ", ["不自然", "さ"]),  # さ after a な-word stays (U2)
    ("レーマン人の町", "レーマン人", ["レーマン", "人"]),  # a person's name is no base
])
def test_each_guard_holds_even_where_the_dictionary_would_allow_the_join(text, allowed, expected):
    # The real table already leaves these out; here the table offers each one, so the rule itself must
    # refuse it (不自然 is allowed too, so only the nominalizer rule keeps さ apart).
    tagger = analyzer.JapaneseTokenizer().tagger
    table = {allowed: [allowed, ""], "不自然": ["不自然", "フシゼン"]}
    assert [w.surface for w in analyzer.join_affixes(tagger(text), table)][:len(expected)] == expected


def test_a_joined_word_reads_as_the_dictionary_reads_it(tokenizer, sanitized):
    # unidic-lite reads the suffix 人 as ニン everywhere (日本人 would be ニッポンニン), 中 as チュウ and 上 as
    # ウエ-less ジョウ — the reading comes from the dictionary list instead.
    assert _keys(tokenizer, "日本人") == [("日本人", "ニホンジン")]
    assert _keys(tokenizer, "世界中") == [("世界中", "セカイジュウ")]
    assert _keys(tokenizer, "父上") == [("父上", "チチウエ")]


def test_a_glossed_loanword_keeps_its_whole_spelling_when_joined(tokenizer, sanitized):
    # Sanitizing the parts' lemmas and then joining cut アメリカ人 to アメリカ (the lemma is
    # "アメリカ-America"): the joined word's lemma is the dictionary headword, never the parts'.
    assert _keys(tokenizer, "アメリカ人が来た。")[0] == ("アメリカ人", "アメリカジン")


def test_the_suffix_decides_the_part_of_speech():
    tagger = analyzer.JapaneseTokenizer().tagger

    def feature(text):
        joined = analyzer.join_affixes(tagger(text))
        assert len(joined) == 1 and isinstance(joined[0], analyzer.JoinedWord), text
        return joined[0].feature

    assert feature("可能性").pos1 == "名詞"            # 形状詞 + a noun-making suffix is a noun
    assert feature("具体的").pos1 == "形状詞"          # 名詞 + 的 is a な-adjective
    adjective = feature("子供っぽく")                 # an adjective, conjugated as the text wrote it
    assert (adjective.pos1, adjective.lemma, adjective.cForm) == ("形容詞", "子供っぽい", "連用形-一般")
    assert feature("嫌がっ").pos1 == "動詞"
    # A joined word is a common word, never a name — 日本人 must not count as one (patterns._is_name).
    assert feature("日本人").pos2 != "固有名詞"


def test_a_word_the_dictionary_does_not_list_stays_in_pieces():
    tagger = analyzer.JapaneseTokenizer().tagger
    # 啓示的 is no dictionary word: 啓示 keeps the 〜的 as a suffix of its own.
    assert [w.surface for w in analyzer.join_affixes(tagger("啓示的な体験"))][:2] == ["啓示", "的"]
    # The same shape joins only with the dictionary's say-so: take 可能性 out of the table and it splits.
    table = {"可能性": ["可能性", "カノウセイ"]}
    assert [w.surface for w in analyzer.join_affixes(tagger("可能性"), table)] == ["可能性"]
    assert [w.surface for w in analyzer.join_affixes(tagger("可能性"), {"不可能": ["不可能", "フカノウ"]})] \
        == ["可能", "性"]


def test_the_polite_prefix_joins_only_where_it_is_a_usual_form_of_the_word():
    # The user (U1): お / ご words join when the prefixed form is at least 30% of the word's uses in the
    # shared corpus — お茶, お金, お菓子 are words; お名前 and お仕事 are お + a word. The set is mostly
    # written, so a word said with お at least half the time in its conversation joins too (checkpoint
    # A: お祭り 76% there, 16% overall); お見舞い is too rare there to tell, and stays apart.
    joins = reference_data.affix_joins()
    for word in ("お茶", "お金", "お菓子", "お願い", "お祭り", "お湯"):
        assert word in joins, word
    for word in ("お名前", "お仕事", "お部屋", "お話", "お見舞い"):
        assert word not in joins, word


def test_a_joined_word_outlives_the_taggers_next_call():
    # A fugashi node is only valid until the tagger runs again; a joined word is built from copies.
    tagger = analyzer.JapaneseTokenizer().tagger
    joined = analyzer.join_affixes(tagger("新幹線"))[0]
    tagger("全然違う話だ")
    assert (joined.surface, joined.feature.lemma, [s for s, _ in joined.parts]) == ("新幹線", "新幹線", ["新", "幹線"])


def test_the_sentence_dictionary_reads_a_joined_word_as_one_headword():
    # The Yomitan export tags each spelling alone: 可能性 must come back as ONE word with its reading.
    tag = sentence_corpus._default_tagger()
    assert tag("可能性") == ("可能性", "カノウセイ", "カノウセイ", "")


def _known(tmp_path, *words):
    path = tmp_path / "KnownWord.json"
    path.write_text(json.dumps({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in words]},
                               ensure_ascii=False), encoding="utf-8")
    return analyzer.load_known_words(str(path), analyzer.JapaneseTokenizer())


def test_a_known_joined_word_still_marks_its_pieces_known(tmp_path, sanitized):
    # §6.2a: the user's 時間 is known only through their 時間帯 — the join must not take that away.
    tuples, lemmas = _known(tmp_path, "時間帯")
    assert ("時間帯", "ジカンタイ") in tuples
    assert ("時間", "ジカン") in tuples and "時間" in lemmas


def test_knowing_the_base_does_not_make_the_joined_word_known(tmp_path, sanitized):
    # Not the reverse: knowing 利用 does not make 利用者 known — it stays a word to learn, for its card and
    # its reading (the user, U9: "halfway + lower" — see the tests below).
    tuples, lemmas = _known(tmp_path, "利用")
    assert ("利用者", "リヨウシャ") not in tuples and "利用者" not in lemmas


def test_a_noun_made_by_a_suffix_can_be_read_through_the_word_inside_it(sanitized):
    # U9 covers a word + a noun-making suffix only: 不自然 is a prefix word (不 changes the meaning) and
    # 具体的 a な-adjective, so knowing 自然 or 具体 reads neither.
    tagger = analyzer.JapaneseTokenizer().tagger
    assert analyzer.see_through_base("利用者", "リヨウシャ", tagger) == ("利用", "リヨウ")
    assert analyzer.see_through_base("可能性", "カノウセイ", tagger) == ("可能", "カノウ")
    assert analyzer.see_through_base("母さん", "カアサン", tagger) == ("母", "ハハ")
    assert analyzer.see_through_base("不自然", "フシゼン", tagger) is None
    assert analyzer.see_through_base("新幹線", "シンカンセン", tagger) is None     # a prefix noun too
    assert analyzer.see_through_base("具体的", "グタイテキ", tagger) is None
    assert analyzer.see_through_base("公園", "コウエン", tagger) is None           # no joined word at all
    assert analyzer.see_through_base("利用者", "リヨウモノ", tagger) is None       # not the table's reading


# --- end to end: the list names the whole word ----------------------------------------------------- #
TRAINS = ("新幹線に乗って東京へ行った。\n"
          "新幹線の窓から富士山が見えた。\n"
          "新幹線はとても速い。\n"
          "失敗する可能性がある。\n"
          "成功の可能性は低い。\n"
          "その可能性を考えた。\n")


def _generate(tmp_path, text, known=(), args=()):
    """One real run over a library of one HighPriority file -> the priority list, as a DataFrame."""
    uf = tmp_path / "User Files" / "ja"
    uf.mkdir(parents=True)
    (uf / "KnownWord.json").write_text(
        json.dumps({"words": [{"dictForm": w, "knownStatus": "KNOWN"} for w in known]}, ensure_ascii=False),
        encoding="utf-8")
    high = tmp_path / "data" / "ja" / "HighPriority"
    high.mkdir(parents=True)
    (high / "library.txt").write_text(text, encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    with patch("app.analyzer.get_user_file", side_effect=lambda p: str(tmp_path / p)), \
         patch("app.analyzer.get_data_path",
               side_effect=lambda l=None: str(tmp_path / "data" / l) if l else str(tmp_path / "data")), \
         patch("app.analyzer.get_user_files_path",
               side_effect=lambda l=None: str(tmp_path / "User Files" / l) if l else str(tmp_path / "User Files")), \
         patch("app.analyzer.RESULTS_DIR", str(results)), \
         patch("app.analyzer.OUTPUT_CSV", str(results / "priority_learning_list.csv")), \
         patch("app.analyzer.OUTPUT_STATS", str(results / "file_statistics.txt")), \
         patch("app.analyzer.OUTPUT_PROGRESSIVE", str(results / "progressive_learning_list.csv")), \
         patch("sys.argv", ["analyzer.py", "--language", "ja", "--min-freq", "1", *args]):
        analyzer.main()
    return pd.read_csv(results / "priority_learning_list.csv", encoding="utf-8-sig", keep_default_na=False)


def test_the_list_counts_the_whole_word_not_its_pieces(tmp_path):
    listed = _generate(tmp_path, TRAINS)
    counts = dict(zip(listed["Word"], listed["Occurrences"].astype(int)))
    assert counts.get("新幹線") == 3 and counts.get("可能性") == 3
    assert "幹線" not in counts and "可能" not in counts


PARKS = ("公園の利用者が増えた。\n"
         "今日も公園の利用者が多い。\n"
         "公園の利用者は静かだ。\n"
         "病院の雰囲気が不自然だ。\n"
         "今日も病院の雰囲気は不自然だ。\n"
         "病院の空気が不自然だ。\n")
PARKS_KNOWN = ("の", "が", "は", "た", "だ", "も", "今日", "増える", "多い", "静か", "雰囲気", "空気", "利用", "自然")


def test_a_word_read_through_its_known_word_sits_lower_and_keeps_a_sentence_i_plus_one(tmp_path):
    # U9, "halfway + lower" (the user, checkpoint A). Knowing 利用, the learner reads 利用者: it stays on
    # the list at half the score, and 公園's sentences, whose only other new word it is, stay i+1 — so
    # strict i+1 keeps 公園. A prefix word counts in full: 自然 is known, yet 不自然 leaves every one of
    # 病院's sentences i+2, and strict i+1 drops 病院.
    listed = _generate(tmp_path, PARKS, known=PARKS_KNOWN, args=["--only-i-plus-one"])
    rows = {row["Word"]: row for row in listed.to_dict("records")}
    assert rows["公園"]["Context 1"] in PARKS
    assert int(rows["公園"]["Score"]) == 30 and int(rows["利用者"]["Score"]) == 15
    assert list(listed["Word"]).index("利用者") > list(listed["Word"]).index("公園")
    assert "病院" not in rows and "不自然" not in rows


def test_a_busy_word_keeps_the_sentence_it_can_read_among_its_thirty_candidates(tmp_path):
    # A word keeps its 30 best sentences as the library streams past, ranked by how many rarer new words
    # each holds. 公園's first 30 each hold 猫 (a one-character word: never learned, always new); the
    # 31st holds only 利用者. Counted as new, 利用者 would tie with the worst and never get in; read
    # through 利用 (U9), it is the one sentence strict i+1 can give 公園.
    busy = "".join(f"公園で猫を{n}回見た。\n" for n in range(1, 31)) + "公園の利用者が増えた。\n"
    listed = _generate(tmp_path, busy, known=("で", "を", "回", "見る", "た", "の", "が", "増える", "利用"),
                       args=["--only-i-plus-one"])
    rows = {row["Word"]: row for row in listed.to_dict("records")}
    assert rows["公園"]["Context 1"] == "公園の利用者が増えた。"
