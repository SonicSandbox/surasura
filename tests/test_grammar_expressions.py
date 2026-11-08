"""Grammar expressions as rows of their own (ENGINE 38; app/phrases.py, scripts/build_phrase_data.py's RG).

A grammar expression JMdict lists (かもしれない, として, について, という) is found by the set-phrase matcher and is a row
learned as one unit, marked as grammar; every word in it that isn't grammar gives its use there to the row, and the
same word anywhere else (気心が知れる) is counted as before. Real sentences; the shipped phrase data.
"""
import pytest

from app import analyzer, phrases


@pytest.fixture(scope="module")
def loaded():
    found = phrases.load()
    if found is None:
        pytest.skip("no phrase data in this build")
    return found


@pytest.fixture(scope="module")
def tokenizer():
    analyzer.SANITIZE_JA = True
    return analyzer.JapaneseTokenizer(library=False)


def _found(loaded, tokenizer, text):
    """[(the phrase's spelling shown, its words as written there, the lemmas it takes the uses of)] in `text`."""
    out = []
    for sentence, tokens in tokenizer.tokenize_sentences(text):
        for start, end, index in loaded.find(tokens, sentence):
            phrase = loaded.entry(index)
            out.append((phrase.display, "".join(t[2] for t in tokens[start:end]),
                        [tokens[start + k][0] for k in phrases.bound_at(phrase)]))
    return out


def test_kamoshirenai_is_one_grammar_row_and_its_shiru_the_rows(loaded, tokenizer):
    # Why: 知れる from かもしれない was a list row no learner wants ("しれる" cards with a かもしれない sentence).
    assert _found(loaded, tokenizer, "これは私たちの問題かもしれない。") == [("かもしれない", "かもしれない", ["知れる"])]
    may = loaded.entry(loaded.of_word("かも知れるない"))
    assert may.grammar == 1 and may.roles == "ggbg"


def test_the_same_word_outside_the_expression_is_still_its_own(loaded, tokenizer):
    # 気心が知れる 'know each other well': the verb 知れる, no grammar expression — nothing takes its use.
    assert _found(loaded, tokenizer, "彼とは気心が知れる仲だ。") == []


@pytest.mark.parametrize("text, shown", [
    ("やっぱり無理かもしれなかった。", "かもしれない"),        # ending in grammar: every form of that grammar
    ("明日は雨かもしれません。", "かもしれません"),             # JMdict's polite expression of its own
    ("彼は医者として働いている。", "として"),
    ("日本の歴史について話した。", "について"),
    ("毎朝走るようにしている。", "ようにする"),                 # JMdict conjugates it (vs-i): any form
    ("田中という人が来た。", "という"),
    ("彼は教師として来た。", "として"),                         # 来る a word of its own after it: still として
    ("この件について見ていきましょう。", "について"),
])
def test_each_expression_is_found_where_it_stands(loaded, tokenizer, text, shown):
    assert [display for display, _w, _b in _found(loaded, tokenizer, text)] == [shown]


@pytest.mark.parametrize("text", [
    "彼は行くと言った。",              # と言った is 言う 'said': という only uninflected, before a word of its own
    "昔ここに城があったという。",      # the hearsay 〜という。: no word of its own after it
    "このボタンは本体についている。",  # 付く + ている: an expression ending in て is none before an auxiliary verb
    "まるで口のようにして笑った。",    # のように 'like' + して: ようにする follows a verb, never の
])
def test_the_words_stay_words_where_the_expression_isnt_one(loaded, tokenizer, text):
    assert _found(loaded, tokenizer, text) == []


def test_a_set_phrase_wins_where_it_holds_the_expression(loaded, tokenizer):
    # あっという間に holds という: the longest match at its first word wins, so 言う stays the set phrase's.
    assert [d for d, _w, _b in _found(loaded, tokenizer, "あっという間に終わった。")] == ["あっという間に"]
    # ような気がする's words from 気 on are 気がする: never a grammar row of its own.
    assert "ような気がする" not in {e.display for e in loaded.entries}


def test_a_tally_gives_the_bound_words_uses_to_the_row(loaded, tokenizer):
    """What the token store keeps per file: the row's uses, and the uses its words give it (`taken`) — 知れる twice
    from かもしれない, never the one in 気心が知れる."""
    text = "明日は雨かもしれない。それは嘘かもしれない。彼とは気心が知れる仲だ。"
    uses, taken = phrases.tally(list(tokenizer.tokenize_sentences(text)), loaded)
    may = loaded.of_word("かも知れるない")
    assert uses[may][0] == 2 and taken == {"知れる|シレル": 2}


def test_every_grammar_row_starts_with_grammar_and_gives_every_other_word_to_itself(loaded):
    rows = [e for e in loaded.entries if e.grammar]
    assert len(rows) >= 40
    for e in rows:
        assert e.roles[0] == phrases.GRAMMAR and set(e.roles) == {phrases.GRAMMAR, phrases.BOUND}, e.display
    assert {e.display for e in rows if e.grammar == phrases.AS_WRITTEN} >= {"という"}


def test_a_set_phrase_is_never_marked_grammar(loaded):
    for word in ("気が付く", "腑に落ちる", "若しか為るた"):
        assert loaded.entry(loaded.of_word(word)).grammar == 0, word


def test_rows_without_the_grammar_field_read_as_plain_phrases():
    # An older table (six fields a row) still loads: no row is grammar.
    old = phrases.PhraseSet([["気|が|為る", "キ|ガ|スル", "cgl", "気がする", "キガスル", 0]])
    assert old.entry(0).grammar == 0
