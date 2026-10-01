"""The set phrases' matcher (app/phrases.py) — how a sentence's words are read for the dictionary's set phrases.

The tokenizer never joins a phrase, so the list finds 気がつく, あっという間に or 腑に落ちる in the words it already has,
by their lemmas: any form counts (気がついた is 気 + が + 付く + た). At each place the longest phrase wins and the search
goes on after it; a run whose words stand on both sides of a comma the tokenizer dropped (気が、ついた) is no phrase, and
the next shorter one at that place is tried. Pure: a hand-built set of real phrases (in app/phrase_data.py's own
shape) and the app's real tokenizer, so the matcher is tested whatever the shipped data holds.
"""

import pytest

from app import analyzer, phrases

# [lemmas, readings, roles, spelling, reading] — as app/phrase_data.py stores a phrase.
ROWS = [
    ["気|が|付く", "キ|ガ|ツク", "cgc", "気がつく", "キガツク"],
    ["あっ|と|言う|間", "アッ|ト|イウ|マ", "cgcb", "あっという間", "アットイウマ"],
    ["あっ|と|言う|間|に", "アッ|ト|イウ|マ|ニ", "cgcbg", "あっという間に", "アットイウマニ"],
    ["腑|に|落ちる", "フ|ニ|オチル", "bgc", "腑に落ちる", "フニオチル"],
    ["手っ取り|早い", "テットリ|ハヤイ", "bc", "手っ取り早い", "テットリバヤイ"],
    ["本題|に|入る", "ホンダイ|ニ|ハイル", "cgc", "本題に入る", "ホンダイニハイル"],
    ["若し|か|為る|た", "モシ|カ|スル|タ", "cglg", "もしかしたら", "モシカシタラ"],
    ["気|を|付ける", "キ|ヲ|ツケル", "cgc", "気をつける", "キヲツケル"],
]


@pytest.fixture(scope="module")
def tokenizer():
    analyzer.SANITIZE_JA = True
    return analyzer.JapaneseTokenizer(library=False)


@pytest.fixture(scope="module")
def found_in():
    return phrases.PhraseSet(ROWS)


def _found(found_in, tokenizer, text):
    """(sentence, [(phrase row Word, the tokens' surfaces)]) for each sentence of `text`."""
    out = []
    for sentence, tokens in tokenizer.tokenize_sentences(text):
        out += [(found_in.entry(i).word, "".join(t[2] for t in tokens[a:b]))
                for a, b, i in found_in.find(tokens, sentence)]
    return out


def test_a_phrase_is_found_by_its_lemmas_in_any_form(found_in, tokenizer):
    """気がついた and 気が付いて are both 気が付く (the list keys a phrase by its lemmas joined), written as the text
    writes it."""
    assert _found(found_in, tokenizer, "やっと気がついた。") == [("気が付く", "気がつい")]
    assert _found(found_in, tokenizer, "彼女はすぐに気が付いて振り返った。") == [("気が付く", "気が付い")]


def test_the_longest_phrase_wins_and_the_search_goes_on_after_it(found_in, tokenizer):
    """あっという間に holds あっという間: the longer phrase is the one met there, never both; then the rest of the
    sentence is read on."""
    assert _found(found_in, tokenizer, "夏休みはあっという間に終わり、本題に入った。") == [
        ("あっと言う間に", "あっという間に"), ("本題に入る", "本題に入っ")]


def test_a_run_across_a_dropped_comma_is_no_phrase(found_in, tokenizer):
    """The token store drops the comma of 気が、ついた — its words' lemmas still stand side by side, but they are not one
    run of the sentence, so they are no phrase there."""
    sentence, tokens = next(iter(tokenizer.tokenize_sentences("気が、ついたら朝だった。")))
    assert [t[0] for t in tokens][:3] == ["気", "が", "付く"], "the lemmas do meet"
    assert found_in.find(tokens, sentence) == []


def test_across_a_comma_the_next_shorter_phrase_at_that_place_is_tried(tokenizer):
    """あっという間、に — the five-word phrase straddles the comma; あっという間 before it is still one."""
    found_in = phrases.PhraseSet(ROWS)
    sentence, tokens = next(iter(tokenizer.tokenize_sentences("あっという間、にぎやかになった。")))
    [(a, b, index)] = found_in.find(tokens, sentence)
    assert found_in.entry(index).display == "あっという間"


def test_a_phrase_with_a_form_of_its_own_is_found_only_in_that_form(tokenizer):
    """そういうことなら and ここまで来たら end in grammar in a form of their own (なら, たら — never the dictionary form
    だ, た): そういうことだ and ここまで来た are other expressions, and the next shorter phrase there is tried
    (そういう). One that ends in its dictionary form (目を輝かせる) is found in any form, and named in that form."""
    found_in = phrases.PhraseSet([
        ["そう|言う|事|だ", "ソウ|イウ|コト|ダ", "cccg", "そういうことなら", "ソウイウコトナラ"],
        ["そう|言う", "ソウ|イウ", "cc", "そういう", "ソウイウ"],
        ["此処|まで|来る|た", "ココ|マデ|クル|タ", "cgcg", "ここまで来たら", "ココマデキタラ"],
        ["目|を|輝く|せる", "メ|ヲ|カガヤク|セル", "cgcg", "目を輝かせる", "メヲカガヤカセル"]])
    assert _found(found_in, tokenizer, "そういうことなら、行こう。") == [("そう言う事だ", "そういうことなら")]
    assert _found(found_in, tokenizer, "答えは簡単で、つまりそういうことだ。") == [("そう言う", "そういう")]
    assert _found(found_in, tokenizer, "ここまで来たら戻れない。") == [("此処まで来るた", "ここまで来たら")]
    assert _found(found_in, tokenizer, "長い旅だったが、ここまで来たんだ。") == []
    assert _found(found_in, tokenizer, "彼は目を輝かせて話した。") == [("目を輝くせる", "目を輝かせ")]
    sentence, tokens = next(tokenizer.tokenize_sentences("彼は目を輝かせて話した。"))
    ((start, end, index),) = found_in.find(tokens, sentence)
    assert phrases.spellings(tokens, start, end, found_in.entry(index)) == ("目を輝かせる", "目を輝かせ")
    assert phrases.fixed_form(found_in.entry(found_in.of_word("此処まで来るた")))
    assert not phrases.fixed_form(found_in.entry(index)) and not phrases.fixed_form(found_in.entry(1))


def test_a_pre_noun_adjectival_stands_only_before_a_word_of_its_own(tokenizer):
    """ああいう, どういう and 罪なき are what JMdict classes only as pre-noun adjectivals (adj-pn; the sixth field):
    one is found only uninflected — as its spelling ends (罪なき) or in its dictionary form (どう言う) — straight before a
    word of its own or the 'one' の, a space between at most. ああ言って is the words 'say so', ああいうよ ends on
    grammar, 罪なく is another form: none of them is the phrase. A phrase without the mark is found as before."""
    found_in = phrases.PhraseSet([
        ["ああ|言う", "アア|イウ", "cc", "ああいう", "アアイウ", 1],
        ["どう|言う", "ドウ|イウ", "cc", "どういう", "ドウイウ", 1],
        ["罪|無い", "ツミ|ナイ", "cl", "罪なき", "ツミナキ", 1],
        ["気|が|付く", "キ|ガ|ツク", "cgc", "気がつく", "キガツク"]])
    assert found_in.entry(0).prenoun and not found_in.entry(3).prenoun
    assert _found(found_in, tokenizer, "ああいう人は苦手だ。") == [("ああ言う", "ああいう")]
    assert _found(found_in, tokenizer, "ああいうのが好きなんだ。") == [("ああ言う", "ああいう")]
    assert _found(found_in, tokenizer, "ああいう　建物が好きだ。") == [("ああ言う", "ああいう")]
    assert _found(found_in, tokenizer, "どう言う意味ですか。") == [("どう言う", "どう言う")]
    assert _found(found_in, tokenizer, "罪なき人々を守る。") == [("罪無い", "罪なき")]
    assert _found(found_in, tokenizer, "先生がああ言っていた。") == []
    assert _found(found_in, tokenizer, "ほら、ああいうよ。") == []
    assert _found(found_in, tokenizer, "彼は罪なく生きた。") == []
    assert _found(found_in, tokenizer, "やっと気がついた。") == [("気が付く", "気がつい")]


def test_a_pre_noun_adjectival_usually_written_in_kana_is_found_only_so(tokenizer):
    """そういった and どういう are pre-noun adjectivals JMdict says are usually written in kana (the sixth field 2):
    found only as written in kana. With the verb's kanji, そう言ったのは and そう言った途端 are 'said so' — the words,
    never そういった 'such' — and the rarer kanji-written どう言う意味 is given up with them. A mark-1 phrase (罪なき)
    is found in kanji as before, and the noun rule holds for both."""
    found_in = phrases.PhraseSet([
        ["そう|言う|た", "ソウ|イウ|タ", "ccg", "そう言った", "ソウイッタ", 2],
        ["どう|言う", "ドウ|イウ", "cc", "どういう", "ドウイウ", 2],
        ["罪|無い", "ツミ|ナイ", "cl", "罪なき", "ツミナキ", 1]])
    assert found_in.entry(0).prenoun == phrases.KANA_ONLY and found_in.entry(2).prenoun == 1
    assert _found(found_in, tokenizer, "そういった問題はよくある。") == [("そう言うた", "そういった")]
    assert _found(found_in, tokenizer, "君がそう言ったのは覚えている。") == []
    assert _found(found_in, tokenizer, "そう言った途端、彼は笑った。") == []
    assert _found(found_in, tokenizer, "それはどういう意味ですか。") == [("どう言う", "どういう")]
    assert _found(found_in, tokenizer, "それはどう言う意味ですか。") == []
    assert _found(found_in, tokenizer, "罪なき人々を守る。") == [("罪無い", "罪なき")]
    assert _found(found_in, tokenizer, "彼は確かにそういった。") == []


def test_conjugated_and_folded_uses(found_in, tokenizer):
    """もしかしたら ends in grammar and is found as written; 気をつけて is 気をつける + て — the phrase, then an ending."""
    assert _found(found_in, tokenizer, "もしかしたら雨かも。") == [("若しか為るた", "もしかしたら")]
    assert _found(found_in, tokenizer, "車に気をつけて。") == [("気を付ける", "気をつけ")]


def test_nothing_to_find(found_in, tokenizer):
    """An empty sentence, a sentence with no phrase's first word (passed over at once) and one whose first word
    starts a phrase that never comes."""
    assert found_in.find([], "") == []
    assert _found(found_in, tokenizer, "窓の外で鳥が鳴いている。") == []
    assert _found(found_in, tokenizer, "気が短い人だ。") == []


def test_a_phrase_is_at_most_five_words_and_at_least_two(found_in):
    """The trie holds nothing longer than the data does (2-5 words): a six-word run matches its longest prefix."""
    tokens = [[w, "", w, w] for w in ("あっ", "と", "言う", "間", "に", "も")]
    assert found_in.find(tokens, "あっと言う間にも") == [(0, 5, 2)]


def test_readiness_waits_only_for_real_words_it_does_not_hold_alone():
    """本題に入る waits for 本題 while 本題 is new (learning both would be two new things); 腑に落ちる never waits for
    腑 — it lives only inside the phrase — nor for a one-character word; a phrase is 'all known' only when every real
    word in it is, bound ones included."""
    found_in = phrases.PhraseSet(ROWS)
    subject = found_in.entry(found_in.of_word("本題に入る"))
    assert phrases.waiting(subject, lambda key: key[0] == "入る") == ((("本題", "ホンダイ"),), False)
    assert phrases.waiting(subject, lambda key: key[0] in ("本題", "入る")) == ((), True)
    gut = found_in.entry(found_in.of_word("腑に落ちる"))
    assert phrases.waiting(gut, lambda key: key[0] == "落ちる") == ((), False), "ready, but 腑 is still new"
    notice = found_in.entry(found_in.of_word("気が付く"))
    assert phrases.waiting(notice, lambda key: key[0] == "付く") == ((), False), "気 is one character: never waited for"


def test_spellings_and_the_known_test():
    """A match's spellings: its dictionary form (the last word as the text spells its dictionary form) and as
    written; a phrase is known as a whole by its Word, its spelling, a spelling the text gives it, or its Word and
    reading together."""
    found_in = phrases.PhraseSet(ROWS)
    notice = found_in.entry(found_in.of_word("気が付く"))
    tokens = [["気", "キ", "気", "気"], ["が", "ガ", "が", "が"], ["付く", "ツク", "つい", "つく"], ["た", "タ", "た", "た"]]
    assert phrases.spellings(tokens, 0, 3, notice) == ("気がつく", "気がつい")
    assert phrases.known_whole(notice, (), set(), {"気がつく"}, set())
    assert phrases.known_whole(notice, ("気がつい",), set(), set(), {"気がつい"})
    assert phrases.known_whole(notice, (), {("気が付く", "キガツク")}, set(), set())
    assert not phrases.known_whole(notice, ("気がつい",), set(), {"気", "付く"}, set()), "its words are not it"


def test_tally_and_table_count_what_the_list_counts():
    """One file's tally: each phrase's uses and spellings, and the uses its bound words give it; the table sums them
    under the rows' own keys, with the dictionary's spelling among the spellings."""
    found_in = phrases.PhraseSet(ROWS)
    sentences = [("手っ取り早い方法だ。", [["手っ取り", "テットリ", "手っ取り", "手っ取り"],
                                        ["早い", "ハヤイ", "早い", "早い"], ["方法", "ホウホウ", "方法", "方法"]])]
    uses, taken = phrases.tally(sentences, found_in)
    index = found_in.of_word("手っ取り早い")
    assert uses == {index: [1, ["手っ取り早い"]]} and taken == {"手っ取り|テットリ": 1}
    summed = phrases.table([(uses, taken), ({str(index): [2, ["手っ取り早く"]]}, {"手っ取り|テットリ": 2})], found_in)
    assert summed == {"rows": {"手っ取り早い|テットリバヤイ": [3, ["手っ取り早い", "手っ取り早く"]]},
                      "taken": {"手っ取り|テットリ": 3}}


def test_tally_also_gives_every_match_where_generate_reads_it():
    """The token store keeps each file's matches for Generate, four numbers each — the sentence, where the phrase
    starts and ends in its words, which phrase — in the order the sentences are searched: a sentence with none adds
    nothing, and the tally itself is the same with or without them."""
    found_in = phrases.PhraseSet(ROWS)
    quick = [["手っ取り", "テットリ", "手っ取り", "手っ取り"], ["早い", "ハヤイ", "早い", "早い"]]
    sentences = [("手っ取り早い。", quick), ("今日は雨だ。", [["今日", "キョウ", "今日", "今日"]]),
                 ("もっと手っ取り早い。", [["もっと", "モット", "もっと", "もっと"], *quick])]
    matches = []
    with_them = phrases.tally(sentences, found_in, matches)
    index = found_in.of_word("手っ取り早い")
    assert matches == [0, 0, 2, index, 2, 1, 3, index]
    assert with_them == phrases.tally(sentences, found_in)
    empty = []
    assert phrases.tally([], found_in, empty) == ({}, {}) and empty == []


def test_the_shipped_set_loads_once_per_process():
    """load() decodes app/phrase_data.py once and keeps it; the set holds the phrases the data holds."""
    first = phrases.load()
    assert first is not None and first is phrases.load()
    from app import phrase_data
    assert len(first) == phrase_data.COUNT
