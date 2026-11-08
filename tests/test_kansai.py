"""Kansai speech read as Kansai (ENGINE 38, SCHEMA 21; app/analyzer.py § Kansai, app/kansai_data.py).

UniDic reads standard Japanese: やってへん's へん became the word 辺, 来えへん a prefix and a filler, ちゃう てしまう's
ending, あかん a filler + 彼 'he'. The tokenizer reads the negative after a verb as the verb + its ending, ちゃう standing on
its own as 違う, and JMdict's Kansai words the tagger can't read as those words — and leaves standard Japanese alone.
Real Kansai sentences.
"""
import os
import sys

import pytest

from app import analyzer

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def tokenizer():
    analyzer.SANITIZE_JA = True
    return analyzer.JapaneseTokenizer(library=False)


def _words(tokenizer, text):
    """[(surface, lemma, pos1)] of every word `text` is read as, after the joins (join_affixes, library-free)."""
    return [(w.surface, w.feature.lemma, w.feature.pos1)
            for w in analyzer.join_affixes(tokenizer.tagger(text), analyzer.affix_joins(), library=False)]


def _counted(tokenizer, text):
    return [lemma for _s, tokens in tokenizer.tokenize_sentences(text) for lemma, *_rest in tokens]


ENDING = ("へん", "助動詞")


@pytest.mark.parametrize("text, verb, ending", [
    ("えっ、宿題まだやってへんの？", ("やっ", "遣る"), "へん"),       # て + へん: never the noun 辺
    ("まだ本を読んでへん。", ("読ん", "読む"), "へん"),
    ("あいつ、また来えへんのか。", ("来え", "来る"), "へん"),        # never the prefix 来 + a filler
    ("彼は来へんで。", ("来", "来る"), "へん"),
    ("けえへんかもな。", ("けえ", "来る"), "へん"),
    ("そんなん見いひんわ。", ("見い", "見る"), "ひん"),              # never 言う + ん
    ("昨日は全然寝えへんかった。", ("寝え", "寝る"), "へんかっ"),   # never 得る
    ("宿題なんかしいひん。", ("しい", "為る"), "ひん"),              # never 椎 + 干る
])
def test_the_negative_after_a_verb_is_the_verb_and_its_ending(tokenizer, text, verb, ending):
    words = _words(tokenizer, text)
    at = next(k for k, w in enumerate(words) if w[:2] == verb)
    following = words[at + 1] if words[at + 1][0] == ending else words[at + 2]     # て / で between, where it stands
    assert (following[0], following[1], following[2]) == (ending,) + ENDING
    assert not {"辺", "干る", "椎", "えへん"} & {lemma for _s, lemma, _p in words}


def test_ya_tte_hen_counts_yaru_and_no_word_called_hen(tokenizer):
    # Why: やってへん put a 辺 'area' row on the list. The list counts やる; へん is grammar, as UniDic's own is.
    counted = _counted(tokenizer, "えっ、宿題まだやってへんの？")
    assert "遣る" in counted and "辺" not in counted and "へん" in counted


@pytest.mark.parametrize("text, chau", [
    ("ちゃうちゃう、それ俺のや。", ["違う", "違う"]),     # at the start: 違う 'no', twice
    ("それ、行くんちゃう？", ["違う"]),                   # after の (ん)
    ("それはちゃいます。", ["違う"]),                     # ちゃい before ます
    ("全部食べちゃう。", ["ちゃう"]),                     # right after a verb: てしまう's ending, standard Japanese
    ("させちゃう", ["ちゃう"]),                           # right after an ending too
])
def test_chau_standing_on_its_own_is_chigau(tokenizer, text, chau):
    assert [lemma for s, lemma, _p in _words(tokenizer, text) if s.startswith("ちゃ")] == chau


@pytest.mark.parametrize("text, word, lemma", [
    ("そんなんあかんで。", "あかん", "あかん"),            # never the filler あ + 彼 'he'
    ("おかんが言うてた。", "おかん", "おかん"),            # 'mom', never お + 彼
])
def test_jmdicts_kansai_words_the_tagger_cant_read_are_words(tokenizer, text, word, lemma):
    words = _words(tokenizer, text)
    assert (word, lemma) in {(s, le) for s, le, _p in words}
    assert "彼" not in {le for _s, le, _p in words}


@pytest.mark.parametrize("text, kept", [
    ("この辺で待ってて。", ("辺", "辺")),                  # 辺 written as such
    ("その辺に置いといて。", ("辺", "辺")),
    ("変な人がいる。", ("変", "変")),
    ("彼に言った。", ("彼", "彼")),                        # 彼 'he' is 彼
    ("わからへんかった。", ("わから", "分かる")),           # UniDic's own Kansai negative, as it reads it
])
def test_standard_japanese_and_what_unidic_reads_right_are_untouched(tokenizer, text, kept):
    assert kept in {(s, le) for s, le, _p in _words(tokenizer, text)}


def test_a_longer_stem_is_never_drawn_out(tokenizer):
    # ありえへん is あり得る + へん: only a one-mora stem (寝, 出, 見) draws its vowel out.
    words = _words(tokenizer, "そんなんありえへんわ。")
    assert ("え", "得る") in {(s, le) for s, le, _p in words}
    assert not any(s == "ありえ" for s, _le, _p in words)


def test_baby_talk_chai_is_never_chigau(tokenizer):
    assert "違う" not in {lemma for _s, lemma, _p in _words(tokenizer, "ごめんちゃい。")}


def test_a_line_with_no_kansai_is_the_same_list(tokenizer):
    # Most lines hold none of the surfaces the rules start from: the step hands back the very same list.
    words = analyzer.join_affixes(tokenizer.tagger("今日はいい天気ですね。"), analyzer.affix_joins(), library=False)
    assert analyzer._kansai(words) is words


def test_without_the_kansai_table_the_rules_for_the_negative_still_hold(tokenizer, monkeypatch):
    # The table can't be read (a broken build): あかん stays in pieces, the negative's rules need no table.
    monkeypatch.setattr(analyzer, "_KANSAI", [({}, frozenset(), analyzer._KANSAI_ENDS | analyzer._CHAU)])
    words = _words(tokenizer, "そんなんあかんで。やってへん。")
    assert "あかん" not in {s for s, _le, _p in words}
    assert ("へん", "へん") in {(s, le) for s, le, _p in words}


def test_the_kansai_table_is_jmdicts_misread_kansai_words():
    from app import kansai_data
    table = kansai_data.words()
    assert kansai_data.COUNT == len(table) >= 5 and kansai_data.REVISION and "CC BY-SA 4.0" in kansai_data.__doc__
    assert {"あかん", "おかん"} <= set(table)
    for spelling, (lemma, reading, pos1, first, pieces) in table.items():
        assert spelling.startswith(first) and 2 <= pieces <= 5 and lemma and reading, spelling
        assert not spelling.endswith(("へん", "ひん")) and "ー" not in spelling, spelling


# --------------------------------------------------------------------------- #
# The build's rule (scripts/build_kansai_data.py), on JMdict-shaped entries
# --------------------------------------------------------------------------- #
@pytest.fixture
def bkd():
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
    try:
        import build_kansai_data
        yield build_kansai_data
    finally:
        sys.path.remove(os.path.join(PROJECT_ROOT, "scripts"))


class _Ranks:
    def __init__(self, ranks):
        self.ranks = ranks

    def rank(self, spellings, _reading):
        found = [self.ranks[s] for s in spellings if s in self.ranks]
        return min(found) if found else None


def _entry(kanji, kana, pos, dial=("ksb",), misc=()):
    return {"kanji": [(k, (), ()) for k in kanji], "kana": [(r, (), (), False, ()) for r in kana],
            "senses": [{"pos": tuple(pos), "misc": tuple(misc), "dial": tuple(dial)}]}


def test_the_build_keeps_only_learned_kansai_words_the_tagger_misreads(bkd, monkeypatch):
    monkeypatch.setattr(analyzer, "_KANSAI", [])          # the build sets its own reading; put it back after
    entries = [
        _entry(["明かん"], ["あかん"], ["exp"], misc=("uk",)),           # あ + 彼: made up -> kept
        _entry([], ["ほんで"], ["conj"]),                                 # それ + で: read right -> never touched
        _entry(["当て"], ["あて"], ["n"], dial=()),                        # first sense standard -> not Kansai's
        _entry(["お母ん"], ["おかん"], ["n"], misc=("dated",)),            # dated -> left out
        _entry([], ["めっさ"], ["adv"]),                                  # no list ranks it here -> left out
        _entry(["構へん"], ["かまへん"], ["exp"]),                         # the negative's own rules
    ]
    ranks = {"あかん": 5_919, "ほんで": 13_221, "あて": 5_163, "おかん": 38_246, "かまへん": 34_565}
    table = bkd.build(entries, analyzer.Tagger(), analyzer.affix_joins(), _Ranks(ranks), _Ranks(ranks),
                      lambda _line: None)
    assert table == {"あかん": ["あかん", "アカン", "形状詞", "あ", 2]}


@pytest.mark.parametrize("text", ["怖がっちゃう。", "子供じみちゃう。", "痛がっちゃいます。"])
def test_chau_after_a_suffix_that_makes_a_verb_stays_the_ending(tokenizer, text):
    # がる / じみる make a verb (UniDic's 接尾辞): ちゃう after it is てしまう's, never 違う.
    assert "違う" not in {lemma for _s, lemma, _p in _words(tokenizer, text)}


def test_dekihen_is_dekiru_and_its_ending(tokenizer):
    # できへん 'can't' (Kansai): 出来る + へん — never で + 木偏 'the tree radical'.
    words = _words(tokenizer, "そんなんできへんわ。")
    assert ("でき", "出来る", "動詞") in words and ("へん", "へん", "助動詞") in words
    assert "木偏" not in {lemma for _s, lemma, _p in words}


def test_a_real_interjection_is_no_made_up_piece(tokenizer):
    # もう帰るわ、いや待って without the comma: わ + いや 'no' — read right, never the Kansai word わいや.
    assert "わいや" not in {s for s, _le, _p in _words(tokenizer, "もう帰るわいや待って。")}


@pytest.mark.parametrize("text", ["そのへんで待ってて。", "へんな人がいる。"])
def test_hen_in_kana_that_is_no_negative_stays_its_word(tokenizer, text):
    # へん written in kana after a word that isn't a verb's て (その辺, 変な): never the ending.
    assert ("へん", "助動詞") not in {(s, p) for s, _le, p in _words(tokenizer, text)}
