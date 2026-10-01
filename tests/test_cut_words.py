"""Words the tagger cuts at their grammar (analyzer § Words the tagger cuts; app/dictionary_data.py).

UniDic's short units read some dictionary words as a word + its grammar: くだらない is 下る + ない, 知らせる 知る + せる,
思わず 思う + ず, いつも いつ + も, ちなみに 因み + に, a clause's opening でも two particles. JMdict lists each as a word of
its own, and such a run is that word: a verb + its negative or causative that JMdict's editors list (a usually-kana
word only in kana), and a word + particles JMdict lists as an adverb or a conjunction (particles only opening a
clause, never inside a longer dictionary spelling). Each counts as itself — never known through its parts.

The rules are tested on small tables of the build's shape, so they hold whatever the shipped data holds; the shipped
tables are checked for the words the build's gates keep and refuse. Made-up sentences, read by the project's fugashi
+ unidic-lite.
"""
import pytest

from app import analyzer, dictionary_data

AUX = {"くだらない": ["くだらない", "クダラナイ", "形容詞", "くだら", 1],
       "知らせる": ["知らせる", "シラセル", "動詞", "知ら", 1],
       "思わず": ["思わず", "オモワズ", "副詞", "思わ", 0],
       "すまない": ["すまない", "スマナイ", "形容詞", "すま", 1]}
PARTICLES = {"いつも": ["いつも", "イツモ", "副詞", "いつ", 0, []],
             "ちなみに": ["ちなみに", "チナミニ", "接続詞", "ちなみ", 0, []],
             "でも": ["でも", "デモ", "接続詞", "で", 1, []],
             "どうか": ["どうか", "ドウカ", "副詞", "どう", 0, ["かどうか"]]}


@pytest.fixture(scope="module")
def tagger():
    return analyzer.Tagger()


def _read(tagger, line, aux=AUX, particles=PARTICLES):
    return analyzer.join_affixes(tagger(line), {}, library=False, compounds={}, cut_words=(aux, particles))


def _joined(tagger, line, **tables):
    return {w.surface: w for w in _read(tagger, line, **tables) if isinstance(w, analyzer.JoinedWord)}


# --- A verb + its negative or causative --------------------------------------------------------------------------- #

def test_a_verb_and_its_negative_the_dictionary_lists_is_one_word_in_any_form(tagger):
    word = _joined(tagger, "そんなくだらない話はやめろ。")["くだらない"]
    assert (word.feature.lemma, word.feature.lForm, word.feature.pos1) == ("くだらない", "クダラナイ", "形容詞")
    assert word.feature.cType == "形容詞", "it conjugates as an adjective does"
    # its past: くだら + なかっ is the word, た stays the past it ends in
    words = [w.surface for w in _read(tagger, "くだらなかった。")]
    assert words[:2] == ["くだらなかっ", "た"]


def test_a_causative_word_is_keyed_by_its_dictionary_form(tagger):
    word = _joined(tagger, "早く知らせてくれ。")["知らせ"]
    assert (word.feature.lemma, word.feature.orthBase, word.feature.pos1) == ("知らせる", "知らせる", "動詞")


def test_a_word_that_does_not_conjugate_matches_only_as_written(tagger):
    # 思わず 'without meaning to' is the table's; 思わぬ 'unexpected', which UniDic gives the same dictionary form, is
    # another word the table doesn't hold: 思う + ぬ.
    assert "思わず" in _joined(tagger, "思わず笑った。")
    assert not _joined(tagger, "思わぬ事故に遭った。")


def test_a_usually_kana_word_is_that_word_only_written_in_kana(tagger):
    # The build keeps すまない 'sorry' (JMdict: usually written in kana) and never 済まない, 済む's negative in
    # 済まないぞ — so the kanji spelling stays the verb.
    assert "すまない" in _joined(tagger, "すまない、遅れてしまった。")
    assert not _joined(tagger, "済まないぞ。")


# --- A word + particles -------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("line, surface, lemma, pos1", [
    ("彼はいつも遅れてくる。", "いつも", "いつも", "副詞"),
    ("ちなみに、明日は休みです。", "ちなみに", "ちなみに", "接続詞"),
    ("どうか助けてください。", "どうか", "どうか", "副詞"),
])
def test_a_word_and_its_particles_the_dictionary_lists_is_one_word(tagger, line, surface, lemma, pos1):
    word = _joined(tagger, line)[surface]
    assert (word.feature.lemma, word.feature.pos1) == (lemma, pos1)


@pytest.mark.parametrize("line, joined", [
    ("でも、行きたいんだ。", True),           # the line opens with it
    ("うん。でも、まだ早い。", True),         # after a sentence's end
    ("「でも、本当なの？」", True),           # after an opening bracket
    ("子供でも分かる話だ。", False),          # after a word: で + も
    ("『名探偵』でも話題になった。", False),   # after a closing bracket: a title + で + も
])
def test_particles_are_a_word_only_opening_a_clause(tagger, line, joined):
    assert ("でも" in _joined(tagger, line)) is joined


def test_a_run_inside_a_longer_dictionary_spelling_stays_its_pieces(tagger):
    # か + どう + か is かどうか, an expression: どう + か stays its piece there, and is どうか anywhere else.
    assert "どうか" not in _joined(tagger, "行くかどうか分からない。")
    assert "どうか" in _joined(tagger, "どうか許してほしい。")


def test_without_the_tables_nothing_is_joined(tagger, monkeypatch):
    # The dictionaries' module can't be read: the tables are empty and every word stays in UniDic's pieces.
    monkeypatch.setattr(analyzer, "_DICTIONARY", [None])
    assert analyzer.cut_word_tables() == ({}, {})
    words = analyzer.join_affixes(tagger("彼はいつも遅れてくる。"), {}, library=False, compounds={})
    assert not any(isinstance(w, analyzer.JoinedWord) for w in words)


def test_a_dictionary_module_that_cannot_decode_hands_out_empty_tables(monkeypatch):
    monkeypatch.setattr(dictionary_data, "_AUX_WORDS_B64", "not base64 at all")
    monkeypatch.setattr(dictionary_data, "_aux", None)
    monkeypatch.setattr(dictionary_data, "_PARTICLE_WORDS_B64", "")
    monkeypatch.setattr(dictionary_data, "_particles", None)
    assert dictionary_data.aux_words() == {} and dictionary_data.particle_words() == {}


# --- The shipped tables --------------------------------------------------------------------------------------------- #

def test_the_shipped_tables_hold_the_words_the_rules_keep():
    aux, particles = dictionary_data.aux_words(), dictionary_data.particle_words()
    # curated negatives and causatives; a usually-kana word only in kana
    for key in ("くだらない", "つまらない", "知らせる", "済ませる", "思わず", "すまない"):
        assert key in aux, key
    # 済まない is すまない written in kanji; 変わらない JMdict marks only as frequent in the news; される is する's
    # passive, 思われる 思う's
    for key in ("済まない", "変わらない", "される", "思われる"):
        assert key not in aux, key
    for key in ("いつも", "でも", "ちなみに", "どうにか", "それとも", "何か"):
        assert key in particles, key
    # 本当 is a word of its own (本当に is 本当 + に); すぐに an adverb + an optional に
    for key in ("本当に", "すぐに"):
        assert key not in particles, key
    assert "かどうか" in particles["どうか"][5]
    assert particles["でも"][4] == 1 and particles["いつも"][4] == 0


def test_a_shipped_word_counts_as_itself_not_through_its_parts(tagger):
    # Knowing いつ and も is no knowing いつも: the word is no affix join and no compound, so nothing reads it through
    # its parts — it is an unknown in a sentence until the learner knows it.
    word = next(w for w in analyzer.join_affixes(tagger("彼はいつも遅れてくる。"), library=False)
                if w.surface == "いつも")
    key = (word.feature.lemma, word.feature.lForm)
    assert isinstance(word, analyzer.JoinedWord) and key == ("いつも", "イツモ")
    view = analyzer.LearningView(known=lambda k: k != key)
    assert not view.readable(key)
