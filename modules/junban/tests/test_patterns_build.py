# SPDX-License-Identifier: GPL-3.0-or-later
"""The パターン builder (Patterns_Spec.md WP-P2) — what gets counted, and what must never be.

The one failure that matters most here is silent: if the builder keys a word differently from the
analyzer, every lookup misses and the panel shows "not found" for words that are plainly there
(spec §12 #1). So the first test holds the two to the same (lemma, reading) over a real sample file.
The rest pin §6's rules one at a time on real sentences, and the corpus rules that keep a count
honest — each distinct file once, staging folders never (F13), a crashed build never half-written.
"""
import os
import sqlite3
from collections import Counter

import pytest

from app import analyzer
from app.path_utils import get_data_path
from modules.junban import patterns, patterns_build as pb

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(scope="module")
def tagger():
    # The builder's own tagger (_init_worker): it reads text as the tokenizer does — the sample's ４ and ＯＬ
    # are 4 and OL to both (analyzer.tagger_text).
    return analyzer.Tagger()


def _counts(text, tagger):
    boundaries = frozenset(analyzer.LOGIC["sentence_boundaries"]["ja"])
    return pb.count(pb.iter_tokens(text, tagger, analyzer._sanitize_term, boundaries), pb.Counts())


def _rows(text, tagger, monkeypatch, floor=1):
    """Every pattern row for `text`, with the ≥3 pattern floor off so one sentence is enough."""
    monkeypatch.setattr(pb, "MIN_PATTERN", 1)
    return pb.score(_counts(text, tagger), floor)[2]


def _items(rows, lemma, kind):
    return {r[3]: r[4] for r in rows if r[0] == lemma and r[2] == kind}


def _library(files):
    """Write `{relative path: text}` under data/ja (sandboxed by conftest)."""
    root = get_data_path("ja")
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return root


def _db_rows(db, sql):
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# --- the key-space contract --------------------------------------------------------------------- #
def test_the_builder_keys_every_word_exactly_as_the_analyzer_does(tagger, monkeypatch):
    # Over a real sample file, sentence by sentence, the builder's (lemma, reading) for each content
    # token must equal the tokenizer's with sanitisation on — the analyzer always runs Japanese with
    # SANITIZE_JA (analyzer.main), and the priority list is keyed that way. Any drift here and the
    # panel quietly finds nothing.
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)
    with open(os.path.join(_ROOT, "samples", "ja", "HighPriority", "H_priority_sample_1.txt"),
              encoding="utf-8") as f:
        text = f.read()
    # ...for the words the list counts: analyzer.main counts a token only when its key or its text holds Japanese
    # script — the sample's ＯＬ (office lady) holds none.
    expected = Counter((lemma, reading)
                       for _, toks in analyzer.JapaneseTokenizer().tokenize_sentences(text)
                       for lemma, reading, surface, _ in toks
                       if analyzer.has_target_language(lemma, "ja") or analyzer.has_target_language(surface, "ja"))
    boundaries = frozenset(analyzer.LOGIC["sentence_boundaries"]["ja"])
    built, apart = Counter(), set()
    for sentence in pb.iter_tokens(text, tagger, analyzer._sanitize_term, boundaries):
        # The tokenizer drops a sentence with no Japanese in it (punctuation debris); so does this.
        if analyzer.has_target_language("".join(t.surface for t in sentence), "ja"):
            # The builder counts what the list counts (analyzer.word_lemma, in Japanese script): no punctuation,
            # space, symbol, number or Latin word — so the two hold exactly the same words.
            built.update((t.lemma, t.reading) for t in sentence if t.word)
            apart.update((t.lemma, t.entry) for t in sentence if t.word and t.entry)
    assert expected and built == expected
    # The one key that may differ is deliberate: a spelling the dictionary keeps apart from its lemma is counted under
    # itself (この本は読める: 読める, not 読む), and a card finds it by that spelling (patterns.resolve_key's by_orth).
    from app.anki_match import two_words
    assert apart and all(two_words(spelling, lemma) for lemma, spelling in apart)


def test_numbers_and_symbols_are_no_word_and_a_letter_spelled_out_is_one(tagger):
    # The builder counts what the tokenizer counts (analyzer.word_lemma), and a card's lookup reads text the same
    # way: 百 is a number, never a word with lines of its own — nor is 二十 inside 二十歳, a word of its own — and ω,
    # a letter written as the symbol, is no word. デルタ, a letter spelled out, is the word デルタ, as the list has
    # it, not the symbol δ UniDic makes its lemma. 円 after 百 is a piece of the count, as the list has it: no use of 円.
    text = "二十歳の誕生日に百円玉を拾った。デルタ波を測る(´ω`)。"
    counts = _counts(text, tagger)
    lemmas = {counts.keys[i][0] for i in counts.word}
    assert {"二十歳", "デルタ"} <= lemmas and ("円", "エン") in counts.bound
    assert not lemmas & {"二十", "百", "円", "ω-omega", "δ"}
    looked_up = [lemma for lemma, _, _, _ in patterns.tokenizer(tagger)(text)]
    assert "デルタ" in looked_up and not set(looked_up) & {"百", "ω-omega", "δ"}


def test_a_latin_word_is_no_word_as_the_list_has_it(tagger):
    # Subtitles keep their Latin letters since the parsing fixes (FBI, DNA, Game Over), and the list never counts a
    # token without Japanese script in it (analyzer.main) — nor does the builder: 938 such words (the, you, FBI)
    # had reached the conversational set at its floor. The words beside them still count (捜査官, 鑑定), and so
    # does a compound that holds one (DNA鑑定); a run of Latin words alone (GameOver) is no compound.
    counts = _counts("FBIの捜査官がDNA鑑定を行った。画面にGame Overと出た。", tagger)
    lemmas = {counts.keys[i][0] for i in counts.word}
    assert {"捜査官", "鑑定", "DNA鑑定", "画面"} <= lemmas
    assert not lemmas & {"FBI", "DNA", "Game", "Over", "GameOver"}


def test_a_verbs_conjugated_forms_count_as_one_word(tagger):
    # The reading is the lemma's (lForm) since ENGINE_REVISION 10 — 辿り着いた and 辿り着く are one key.
    counts = _counts("やっと辿り着いた。ここに辿り着く。早く辿り着けば。", tagger)
    keys = {counts.keys[i] for i in counts.word if counts.keys[i][0] == "辿り着く"}
    assert keys == {("辿り着く", "タドリツク")}


def test_a_spelling_the_dictionary_lists_apart_from_its_lemma_is_counted_as_its_own_word(tagger, monkeypatch):
    # UniDic files 揚げる 'deep-fry' and 挙げる 'raise (a hand)' under 上げる 'lift', 建てる under 立てる and 撮る under 取る;
    # JMdict gives each an entry of its own, and a card that says 揚げる must find 揚げる's uses, never 上げる's. Each is a
    # word of its own as well — its row, its spelling, its pairings — while あげる, written in kana, is 上げる's alone.
    text = ("天ぷらを揚げる。鳥の唐揚げを揚げた。手を挙げて答えた。手を上げる。気分を上げる。プレゼントをあげる。"
            "家を建てる。写真を撮った。")
    counts = _counts(text, tagger)
    uses = {counts.keys[i]: c for i, c in counts.word.items()}
    assert uses[("揚げる", "アゲル")] == 2 and uses[("挙げる", "アゲル")] == 1
    assert uses[("建てる", "タテル")] == 1 and uses[("撮る", "トル")] == 1
    # The spelling is the word of its own's: a 揚げる card finds 揚げる alone, never 上げる by its spelling.
    lemma_rows, alias_rows, _ = pb.score(counts, 1)
    assert ("揚げる", "揚げる", "アゲル", 2) in alias_rows
    assert not [row for row in alias_rows if row[0] in ("揚げる", "挙げる") and row[1] == "上げる"]
    rows = _rows(text, tagger, monkeypatch)
    assert _items(rows, "揚げる", "colloc") == {"天ぷらを{w}": 1, "唐揚げを{w}": 1}
    assert _items(rows, "挙げる", "colloc") == {"手を{w}": 1}
    # The lemma keeps every use, as a compound's parts keep theirs: 上げる still counts all six, 揚げる's and 挙げる's among
    # them, and its rows and every other word's are exactly what a build without the change makes, strengths too —
    # nothing a card had moves. The only rows the change adds are the words of their own.
    assert uses[("上げる", "アゲル")] == 6 and uses[("立てる", "タテル")] == 1 and uses[("取る", "トル")] == 1
    monkeypatch.setattr(pb, "_entry", lambda lemma, orth, ctype: "")
    before = _rows(text, tagger, monkeypatch)
    added = {row[0] for row in set(rows) - set(before)}
    assert set(before) <= set(rows) and added == {"揚げる", "挙げる", "建てる", "撮る"}


def test_a_word_counted_under_its_own_spelling_is_still_the_word_grammar_reads(tagger, monkeypatch):
    # 就いて in 利用に就いて is UniDic's 付く, the verb inside について: counted as 就く 'take up (a post)', its own
    # dictionary word, yet the rules read it as UniDic does — the compound particle, printed as written, never
    # 利用に就く.
    counts = _counts("利用に就いて話す。", tagger)
    assert ("就く", "ツク") in {counts.keys[i] for i in counts.word}
    assert _items(_rows("利用に就いて話す。", tagger, monkeypatch), "利用", "colloc") == {"{w}に就いて": 1}


@pytest.mark.parametrize("text, lemma, spelling", [
    ("プレゼントをあげる。", ("上げる", "アゲル"), ("あげる", "アゲル")),        # kana: no entry of its own
    ("たった一人で来た。", ("唯", "タダ"), ("たった", "タダ")),                # though JMdict lists たった apart
    ("実り多き秋を迎えた。", ("多い", "オオイ"), ("多し", "オオイ")),            # an older conjugation of 多い
    ("彼女を愛さない。", ("愛する", "アイスル"), ("愛す", "アイスル")),          # 愛さない is 愛する's negative
    ("例え負けても諦めない。", ("仮令", "タトエ"), ("例え", "タトエ")),          # 'even if', not the noun 'simile'
])
def test_a_spelling_that_is_no_word_of_its_own_there_stays_with_its_lemma(tagger, text, lemma, spelling):
    # Kana is no dictionary entry; a classical inflection's base spelling is the word in an older conjugation; a す
    # verb is its する verb conjugated another way (as a じる verb is its ずる form); and where UniDic lists the
    # spelling as a word of its own, it already told the two apart where the text stands.
    keys = {key for key in _counts(text, tagger).keys}
    assert lemma in keys and spelling not in keys


# --- §6: what each line counts ------------------------------------------------------------------ #
def test_a_nouns_particle_comes_from_its_right_and_a_verbs_from_its_left(tagger, monkeypatch):
    # Particle-after is meaningless for a verb (it is followed by an auxiliary or て); what a
    # learner needs is the particle that marks its argument: 影響を受ける.
    rows = _rows("台風の影響を受けて電車が止まった。", tagger, monkeypatch)
    assert _items(rows, "影響", "particle") == {"を": 1}
    assert _items(rows, "受ける", "particle") == {"を": 1}
    assert "て" not in _items(rows, "受ける", "particle")


def test_nothing_pairs_across_a_comma_or_a_full_stop(tagger, monkeypatch):
    rows = _rows("大きな影響を受ける。影響、を受ける。影響。を受ける。", tagger, monkeypatch)
    assert _items(rows, "影響", "colloc") == {"{w}を受ける": 1}


def test_no_is_never_a_particle_share_and_ha_never_forms_a_collocation(tagger, monkeypatch):
    # D4: の is the default noun-to-noun link and would take a slot on almost every noun. は still
    # counts as a share, but 影響は受ける would only repeat 影響を受ける with a thinner count.
    rows = _rows("目の前が暗くなった。影響は受ける。", tagger, monkeypatch)
    assert "の" not in _items(rows, "目", "particle")
    assert _items(rows, "影響", "particle") == {"は": 1}
    assert _items(rows, "影響", "colloc") == {}


def test_to_iu_becomes_the_frame_toiu_never_the_fragment_iu(tagger, monkeypatch):
    rows = _rows("そんな話があるという話だった。", tagger, monkeypatch)
    frames = _items(rows, "話", "frame")
    assert frames == {"そんな〜": 1, "という〜": 1}
    assert not any(item.startswith("いう") for item in frames)


def test_a_nouns_collocations_and_frames_on_real_sentences(tagger, monkeypatch):
    rows = _rows("気持ち悪い。気持ちがいい。彼の話に大きな影響を受けた。経験者だ。", tagger, monkeypatch)
    assert _items(rows, "気持ち", "colloc") == {"{w}悪い": 1, "{w}がいい": 1}
    assert _items(rows, "影響", "frame") == {"大きな〜": 1}
    assert _items(rows, "経験", "frame") == {"〜者": 1}


def test_a_compound_noun_collocate_is_shown_whole(tagger, monkeypatch):
    # UniDic splits 違和感 into 違和 + 感; taking only the head put 感を感じる ×22 on the user's
    # 感じる card (measured on the real library, 2026-09-23). The whole compound is the collocate.
    rows = _rows("違和感を感じる。存在感を感じた。緊張感が大きい。", tagger, monkeypatch)
    assert _items(rows, "感ずる", "colloc") == {"違和感を{w}": 1, "存在感を{w}": 1}
    assert _items(rows, "大きい", "colloc") == {"緊張感が{w}": 1}


def test_a_na_adjective_takes_its_particle_from_the_left(tagger, monkeypatch):
    # UniDic tags the に of 大切にする as the copula だ, not a particle — so 大切's particle is the
    # one before it (時間が大切だ), the way NLT groups it too (…が大切だ 10,316 vs 大切が… 8). The を
    # of 家族を大切にする lands here as well, which is right: 大切にする takes を, and a learner
    # meets 大切 that way as often as with が.
    rows = _rows("時間が大切だ。家族を大切にする。", tagger, monkeypatch)
    assert _items(rows, "大切", "particle") == {"が": 1, "を": 1}
    assert _items(rows, "大切", "colloc") == {"時間が{w}": 1, "{w}にする": 1}


def test_a_words_part_of_speech_is_the_use_its_particles_were_counted_from(tagger, tmp_path):
    # 目 (eye) and the counter 〜目 (三回目, 二年目) share lemma and reading, and news has more counters
    # than eyes: filed as a suffix, 目's card put its particle on the wrong side (を〜 for 〜を). The
    # particles come from the noun uses alone, so the noun is its part of speech. A word the rules never
    # count (的, only ever a suffix) keeps what it is.
    from modules.junban import patterns as pt
    from modules.junban.patterns_store import Store
    text = "三回目の挑戦だ。二年目の春だ。五人目の選手だ。朝、目を覚ます。論理的な話だ。"
    lemma_rows, alias_rows, pattern_rows = pb.score(_counts(text, tagger), 1)
    pos = {r[:2]: r[3] for r in lemma_rows}
    assert pos[("目", "メ")] == "名詞" and pos[("的", "テキ")] == "接尾辞"
    db = str(tmp_path / "patterns_ja.db")
    pb.write_rows(db, lemma_rows, alias_rows, pattern_rows, {"floor": 1, "tokens": 1})
    store = Store(db)
    try:
        assert pt.lines_for(store, "目", "メ")["side"] == "after"      # 〜を, the noun's side
    finally:
        store.close()


def test_the_four_additions_from_the_quality_check_reach_the_card_lines(tagger, monkeypatch):
    # WP-P4 put four additions to the user and all four went in (2026-09-23): noun の noun, what an
    # adjective modifies, an adjective's adverb + verb (collocations), and な-adjective frames.
    rows = _rows("目の前。深い関係。深く考える。大切な人。貴重な経験。", tagger, monkeypatch)
    assert _items(rows, "目", "colloc") == {"{w}の前": 1}
    assert _items(rows, "深い", "colloc") == {"{w}関係": 1, "深く考える": 1}
    assert _items(rows, "大切", "colloc") == {"{w}な人": 1}
    assert _items(rows, "経験", "frame") == {"貴重な〜": 1}
    assert {r[2] for r in rows} <= {"particle", "form", "colloc", "frame"}


def test_the_forms_a_word_itself_takes(tagger, monkeypatch):
    # The fourth line (the user, 2026-09-24): how the word itself is used — a verb's voice, negative,
    # progressive; an adjective's く / さ / くない; a な-adjective's or noun's な / に / だ / する. Each as
    # the text writes it, contractions in full (知ってる is 知っている, 忘れちゃう 忘れてしまう), a
    # な-adjective's and a noun's in the card's own spelling ({w}な).
    rows = _rows("緑に囲まれた。緑に囲まれる。家を囲む。構わない。構わん。知ってる。知っている。"
                 "忘れちゃう。忘れてしまう。大切な人。大切にする。大切だ。大切です。期待する。期待した。"
                 "深く考える。深さ。深くない。", tagger, monkeypatch)
    assert _items(rows, "囲む", "form") == {"囲まれる": 2}
    assert _items(rows, "構う", "form") == {"構わない": 2}
    assert _items(rows, "知る", "form") == {"知っている": 2}
    assert _items(rows, "忘れる", "form") == {"忘れてしまう": 2}
    assert _items(rows, "大切", "form") == {"{w}な": 1, "{w}に": 1, "{w}だ": 2}
    assert _items(rows, "期待", "form") == {"{w}する": 2}
    assert _items(rows, "深い", "form") == {"深く": 1, "深さ": 1, "深くない": 1}


def test_a_form_must_cover_a_twentieth_of_the_words_uses(tagger, monkeypatch):
    # One passive among twenty-one uses is noise, not how the word is used — 5%, the one line every share
    # on a card is held to (Patterns_Quality_Spec decision 2; it was a tenth before builder 6).
    rows = _rows("家を囲む。" * 20 + "緑に囲まれる。", tagger, monkeypatch)
    assert _items(rows, "囲む", "form") == {}
    rows = _rows("家を囲む。" * 12 + "緑に囲まれる。", tagger, monkeypatch)
    assert _items(rows, "囲む", "form") == {"囲まれる": 1}


def test_the_other_word_is_spelled_the_way_the_pairing_writes_it(tagger, monkeypatch):
    # 会う is the lemma's commonest spelling, but ひどい目に遭う writes 遭う — so must the card (目に会う
    # reached the first spread preview, 2026-09-24). And UniDic files 信じて / 信じた under the base
    # spelling 信ずる, which nobody writes today: the じる spelling wins wherever the text has it.
    rows = _rows("ひどい目に遭った。友達に会う。友達に会った。先生に会う。"
                 "神を信じている。神を信じた。仏を信じる。", tagger, monkeypatch)
    assert _items(rows, "目", "colloc") == {"{w}に遭う": 1}
    assert _items(rows, "友達", "colloc") == {"{w}に会う": 2}
    assert _items(rows, "神", "colloc") == {"{w}を信じる": 2}


def test_a_passive_or_causative_stays_in_the_pairing(tagger, monkeypatch):
    # The passive is a token of its own (囲ま + れる); dropped, it turns the meaning around — 緑に囲む
    # says the opposite of 緑に囲まれる, and 雰囲気にのむ is not Japanese (it reached the 2026-09-24
    # samples). On the other word's card and on the verb's own card alike.
    rows = _rows("緑に囲まれた家。緑に囲まれる。雰囲気にのまれた。子供を遊ばせる。", tagger, monkeypatch)
    assert _items(rows, "緑", "colloc") == {"{w}に囲まれる": 2}
    assert _items(rows, "囲む", "colloc") == {"緑に囲まれる": 2}
    assert _items(rows, "雰囲気", "colloc") == {"{w}にのまれる": 1}
    assert _items(rows, "遊ぶ", "colloc") == {"子供を遊ばせる": 1}


def test_a_classical_inflection_is_shown_in_its_modern_form(tagger, monkeypatch):
    # UniDic files 実り多き's 多き under the classical base spelling 多し, and 実り多し reached the
    # 2026-09-24 samples. The word's modern form stands in: 実り多い, 美しい〜.
    rows = _rows("実り多き人生。美しき花。", tagger, monkeypatch)
    assert _items(rows, "実り", "colloc") == {"{w}多い": 1}
    assert _items(rows, "花", "frame") == {"美しい〜": 1}


def test_each_row_names_the_construction_it_comes_from(tagger, monkeypatch):
    # The lookup spreads a card's items over constructions (patterns._spread), so every row says which
    # one it is — NLT's own groups: the case particle splits a noun's collocations (問題を解く /
    # 問題に答える) and a verb's, and a 連体詞 frame (この〜) is not an adjective frame (難しい〜).
    rows = _rows("この問題を解く。難しい問題に答える。彼が問題を出す。", tagger, monkeypatch)
    assert {r[3]: r[6] for r in rows if r[0] == "問題" and r[2] != "particle"} == {
        "{w}を解く": "C1を", "{w}に答える": "C1に", "{w}を出す": "C1を",
        "この〜": "F1連体詞", "難しい〜": "F1形容詞"}
    assert {r[6] for r in rows if r[0] == "解く" and r[2] == "colloc"} == {"C3を"}
    # A particle row's section is its side (builder 6): after a noun, before a verb.
    assert {r[6] for r in rows if r[2] == "particle" and r[0] == "問題"} == {"after"}
    assert {r[6] for r in rows if r[2] == "particle" and r[0] == "解く"} == {"before"}


def test_an_empty_noun_after_no_is_never_a_collocation(tagger, monkeypatch):
    # 実りのこと ×6 reached a card's collocation line (2026-09-24 preview): 〜のこと, 〜のもの,
    # 〜のため go with nearly any noun. 目の前 and 心の中 carry meaning and stay.
    rows = _rows("実りのこと。天性のもの。君のため。目の前。心の中。", tagger, monkeypatch)
    assert _items(rows, "実り", "colloc") == {}
    assert _items(rows, "天性", "colloc") == {}
    assert _items(rows, "目", "colloc") == {"{w}の前": 1}
    assert _items(rows, "心", "colloc") == {"{w}の中": 1}


def test_a_name_honorific_is_a_frame_only_when_the_word_itself_takes_it(tagger):
    # 母さん: the word takes さん — kept. 実り picked up 〜ちゃん from a character named みのり — a
    # sliver of the word's uses, dropped (HONORIFIC_SHARE).
    ordinary = ("実りの秋。実りが多い。実りを祝う。実りの季節。実りある一年。実りがない。実りと収穫。"
                "実りを待つ。実りのある話。実りが少ない。実りを得る。")
    text = ("母さんが来た。母さんに会う。母さんは優しい。母の手紙。母が笑う。"
            + ordinary * 3 +                                    # 33 real uses of 実り …
            "実りちゃんが来た。実りちゃんと話す。実りちゃんに会う。")   # … and 3 of a name (8%)
    rows = pb.score(_counts(text, tagger), floor=1)[2]
    frames = lambda lemma: {r[3] for r in rows if r[0] == lemma and r[2] == "frame"}
    assert "〜さん" in frames("母")
    assert "〜ちゃん" not in frames("実り")


def test_a_name_misread_as_a_word_never_gives_it_an_honorific_frame(tagger, monkeypatch):
    # Real subtitle lines: UniDic reads the name みのり as the word 実り in 28 of 84 of them. Written in
    # plain kana though the word's dictionary form has kanji, then an honorific: a name.
    rows = _rows("俺が みのりちゃんと いくら遊ぼうがね。ようやく みのりちゃんと。母さんが来た。",
                 tagger, monkeypatch)
    assert "〜ちゃん" not in _items(rows, "実り", "frame")
    assert "〜さん" in _items(rows, "母", "frame")


def test_a_compound_noun_is_a_word_of_its_own(tagger, monkeypatch):
    # 156 of the user's Lapis notes are compound nouns UniDic splits (奨学金 = 奨学 + 金); they were
    # skipped as phrases. Counted as one unit they get a noun's lines — and their parts keep theirs.
    rows = _rows("奨学金を受ける。奨学金が必要だ。大きな奨学金。", tagger, monkeypatch)
    assert _items(rows, "奨学金", "particle") == {"を": 1, "が": 1}
    assert _items(rows, "奨学金", "colloc") == {"{w}を受ける": 1}
    assert _items(rows, "奨学金", "frame") == {"大きな〜": 1}
    counts = _counts("奨学金を受ける。", tagger)
    assert ("奨学金", "ショウガクキン") in counts.ids and ("金", "キン") in counts.ids


def test_a_number_never_makes_a_compound(tagger):
    # 3人, 第2話 — every count would become a word of its own.
    counts = _counts("3人が来た。第2話を見た。", tagger)
    assert not any(any(ch.isdigit() for ch in lemma) and len(lemma) > 1 for lemma, _ in counts.ids)


def test_a_verbs_collocation_is_scored_on_the_verbs_own_count(tagger, monkeypatch):
    # The collocate of 気持ち + に + なる is なる; scoring it as if it were the particle に (count 0)
    # floated every common verb to the top of line 2. A frequent verb must score BELOW a rarer one
    # with the same pair count.
    monkeypatch.setattr(pb, "MIN_PATTERN", 1)
    counts = _counts("気持ちになる。気持ちになる。気持ちを伝える。気持ちを伝える。"
                     "雨になる。夜になる。春になる。冬になる。", tagger)
    rows = {r[3]: r[5] for r in pb.score(counts, floor=1)[2] if r[0] == "気持ち" and r[2] == "colloc"}
    assert rows["{w}を伝える"] > rows["{w}になる"]


def test_a_word_under_the_floor_gets_no_pattern_rows_but_keeps_its_count(tagger):
    # So the panel can say "too rare (5 < 12)" rather than "not found".
    lemma_rows, _, pattern_rows = pb.score(_counts("影響を受ける。" * 5, tagger), floor=12)
    assert ("影響", "エイキョウ", "影響", "名詞", 5) in lemma_rows
    assert not [r for r in pattern_rows if r[0] == "影響"]


def test_log_dice_prefers_the_word_that_goes_with_this_word():
    # Same pair count, but a collocate common everywhere scores lower than one that isn't.
    assert pb.log_dice(10, 50, 20) > pb.log_dice(10, 50, 5000)


# --- the corpus ---------------------------------------------------------------------------------- #
def test_the_same_file_in_two_tabs_counts_once_and_staging_is_never_read(tmp_path):
    # F13: data/ja's staging folders are mostly byte-identical copies of tab files. Reading them, or
    # counting a copy twice, would double every ×N on the user's cards.
    text = "彼の言葉に大きな影響を受けた。"
    _library({"HighPriority/a.txt": text, "GoalContent/b.txt": text,
              "Processed/a.txt": text, "Pre-YT/a.txt": text, "ja/HighPriority/a.txt": text})
    meta = pb.build(db_path=str(tmp_path / "p.db"), floor=1)
    assert (meta["files"], meta["duplicates"]) == (1, 1)
    assert _db_rows(str(tmp_path / "p.db"),
                    "SELECT count FROM lemma WHERE lemma='影響'") == [(1,)]


def test_subtitle_timestamps_and_cue_numbers_never_reach_the_database(tmp_path, monkeypatch):
    # Every file goes through analyzer.extract_text, which strips an .srt's timing lines.
    monkeypatch.setattr(pb, "MIN_PATTERN", 1)
    srt = ("1\n00:00:01,000 --> 00:00:03,500\n台風の影響を受けて\n\n"
           "2\n00:00:04,000 --> 00:00:06,000\n電車が止まった。\n\n"
           "3\n00:00:07,120 --> 00:00:09,800\n大きな影響を受けた\n")
    _library({"LowPriority/ep01.srt": srt})
    db = str(tmp_path / "p.db")
    pb.build(db_path=db, floor=1)
    everything = _db_rows(db, "SELECT lemma, orth FROM lemma") + _db_rows(db, "SELECT item, kind FROM pattern")
    assert everything
    assert not any(ch.isdigit() or "-->" in s or ":" in s for row in everything for s in row for ch in s)


def test_a_general_corpus_is_read_whole_and_uses_the_higher_floor(tmp_path):
    corpus = tmp_path / "cc100"
    (corpus / "part1").mkdir(parents=True)
    (corpus / "part1" / "a.txt").write_text("大きな影響を受けた。", encoding="utf-8")
    meta = pb.build(corpus_dir=str(corpus), db_path=str(tmp_path / "p.db"))
    assert (meta["corpus_kind"], meta["floor"], meta["files"]) == ("general", pb.FLOOR_GENERAL, 1)


def test_several_source_folders_build_as_one_corpus(tmp_path):
    # A general set is several prepared sources (subtitles, chat, speech) read together.
    for name, text in (("subs", "大きな影響を受けた。"), ("chat", "影響を与える。")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "a.txt").write_text(text, encoding="utf-8")
    meta = pb.build(corpus_dir=[str(tmp_path / "subs"), str(tmp_path / "chat")],
                    db_path=str(tmp_path / "p.db"), floor=1)
    assert (meta["corpus_kind"], meta["files"]) == ("general", 2)
    assert _db_rows(str(tmp_path / "p.db"), "SELECT count FROM lemma WHERE lemma='影響'") == [(2,)]


def test_an_interrupted_build_leaves_the_previous_database_untouched(tmp_path, monkeypatch):
    _library({"HighPriority/a.txt": "大きな影響を受けた。", "HighPriority/b.txt": "影響を与える。"})
    db = tmp_path / "p.db"
    pb.build(db_path=str(db), floor=1)
    before = db.read_bytes()

    real = analyzer.extract_text

    def dies_on_the_second_file(path, language="ja"):
        if path.endswith("b.txt"):
            raise KeyboardInterrupt
        return real(path, language)
    monkeypatch.setattr(analyzer, "extract_text", dies_on_the_second_file)
    with pytest.raises(KeyboardInterrupt):
        pb.build(db_path=str(db), floor=1)
    assert db.read_bytes() == before
    assert not os.path.exists(str(db) + ".tmp")


@pytest.mark.parametrize("files", [
    {},                                                                  # an empty library
    {"HighPriority/notes.txt": "Meeting notes: call Bob at 3pm."},      # no Japanese at all
    {"GoalContent/empty.txt": ""},                                      # an empty file
])
def test_empty_states_build_an_empty_database_without_error(tmp_path, files):
    _library(files)
    db = str(tmp_path / "p.db")
    meta = pb.build(db_path=db)
    assert meta["patterns"] == 0
    assert _db_rows(db, "SELECT count(*) FROM pattern") == [(0,)]


def test_counts_merged_from_two_halves_equal_counting_the_whole(tagger):
    # A worker's ids are its own; merging maps them through the (lemma, reading) keys — the
    # pairings' spellings included (ひどい目に遭った beside 友達に会う).
    first, second = "大きな影響を受けた。気持ち悪い。ひどい目に遭った。", "影響を与える。違和感を感じる。目の前。友達に会う。三年が過ぎた。"
    whole = _counts(first + second, tagger)
    merged = pb.merge(_counts(first, tagger), _counts(second, tagger))

    def canon(c):
        key = c.keys.__getitem__

        def rule(k):
            return tuple(key(v) if isinstance(v, int) else v for v in k)
        return ({key(i): n for i, n in c.word.items()},
                {(key(x), rule(k)): n for (x, k), n in c.pattern.items()},
                {(key(x), rule(k), o, t): n for (x, k, o, t), n in c.spell.items()},
                c.teiu, c.tokens, dict(c.bound))
    assert canon(merged) == canon(whole)
    assert canon(merged)[5] == {("年", "ネン"): 1}            # a piece (年 in 三年) merges as the text has it
    assert any(o == "遭う" for _, _, o, _ in canon(merged)[2])


def test_a_parallel_build_writes_the_same_database_as_a_single_process(tmp_path, monkeypatch):
    # Preparing a large corpus uses many processes (WP-P10); the answer must not depend on how many.
    # One file per batch, so the three parts really are counted apart and merged.
    with open(os.path.join(_ROOT, "samples", "ja", "LowPriority", "L_priority_sample_1.txt"),
              encoding="utf-8") as f:
        lines = f.read().splitlines()
    _library({f"HighPriority/part{i}.txt": "\n".join(lines[i::3]) for i in range(3)})
    monkeypatch.setattr(pb, "_batches", lambda paths: ([p] for p in paths))
    one, two = str(tmp_path / "one.db"), str(tmp_path / "two.db")
    pb.build(db_path=one, floor=1)
    pb.build(db_path=two, floor=1, workers=2)
    for table in ("lemma", "alias", "pattern"):
        assert sorted(_db_rows(one, f"SELECT * FROM {table}")) == sorted(_db_rows(two, f"SELECT * FROM {table}"))


def test_a_named_corpus_gets_its_own_database_file():
    assert os.path.basename(pb.default_db_path("ja")) == "patterns_ja.db"
    assert os.path.basename(pb.default_db_path("ja", "conversational")) == "patterns_ja_conversational.db"


def test_the_cli_reports_progress_and_the_totals(tmp_path, capsys):
    _library({"HighPriority/a.txt": "大きな影響を受けた。"})
    assert pb.main(["--db", str(tmp_path / "p.db")]) == 0
    out = capsys.readouterr().out
    assert "PROGRESS 1/1" in out and "Built: 1 files" in out


def test_the_build_counts_with_the_cycle_collector_paused_and_leaves_it_on(tmp_path, monkeypatch):
    # The build's tables grow all through the library and hold no cycles; the collector re-walking them cost
    # seconds a build. It is off while the build counts, and on again once main returns.
    import gc
    seen = []
    real_build = pb.build

    def build(*args, **kwargs):
        seen.append(gc.isenabled())
        return real_build(*args, **kwargs)
    monkeypatch.setattr(pb, "build", build)
    _library({"HighPriority/a.txt": "大きな影響を受けた。"})
    assert pb.main(["--db", str(tmp_path / "p.db")]) == 0
    assert seen == [False]
    assert gc.isenabled()


# --- builder 6 (Patterns_Quality_Spec.md §8.1) --------------------------------------------------- #
def test_a_word_with_a_suffix_keeps_its_bases_use_and_a_prefix_makes_another_word(tagger, monkeypatch):
    # 利用者 is a word, and 利用 keeps the use with 〜者 as its frame (the way compounds always worked);
    # 不自然 is a word, and 自然 does NOT count it — the prefix changes the meaning (§8.1 a).
    counts = _counts("利用者が多い。不自然な動きだ。自然な動きだ。", tagger)
    word = {key: counts.word[i] for key, i in counts.ids.items()}
    assert word[("利用者", "リヨウシャ")] == 1 and word[("利用", "リヨウ")] == 1
    assert word[("不自然", "フシゼン")] == 1 and word[("自然", "シゼン")] == 1
    rows = _rows("利用者が多い。", tagger, monkeypatch)
    assert _items(rows, "利用", "frame") == {"〜者": 1}


def test_a_sound_word_shown_with_its_to_counts_once_and_pairs_with_its_verb(tagger, monkeypatch):
    # ドキッと is ONE token, the sound word どき shown with と (analyzer.join_affixes): counted once per use —
    # never again as its own first part — and, an adverb, it pairs with the verb it goes with.
    counts = _counts("胸がドキッとした。ドキッとする話だ。書類にざっと目を通す。ざっと見る。", tagger)
    word = {key: counts.word[i] for key, i in counts.ids.items()}
    assert word[("どき", "ドキ")] == 2 and word[("ざっ", "ザッ")] == 2
    rows = _rows("胸がドキッとした。ざっと見る。", tagger, monkeypatch)
    assert _items(rows, "どき", "colloc") == {"{w}する": 1}
    assert _items(rows, "ざっ", "colloc") == {"{w}見る": 1}


def test_a_suru_nouns_particle_and_objects_are_counted_before_it(tagger, monkeypatch):
    # サービスを利用する: を sits BEFORE the noun and says how the verb is used (を〜 31% of 利用's uses,
    # F10), and サービス is its object — a pairing of its own (C6). 利用を控える keeps を after it.
    rows = _rows("サービスを利用する。自分を反省する。利用を控える。", tagger, monkeypatch)
    sides = {(r[3], r[6]) for r in rows if r[0] == "利用" and r[2] == "particle"}
    assert sides == {("を", "before"), ("を", "after")}
    assert _items(rows, "利用", "colloc") == {"サービスを{w}する": 1, "{w}を控える": 1}
    assert _items(rows, "反省", "colloc") == {"自分を{w}する": 1}
    assert {r[6] for r in rows if r[0] == "利用" and r[3] == "サービスを{w}する"} == {"C6を"}


def test_a_suru_nouns_pairing_keeps_its_voice_and_a_count_is_no_partner(tagger, monkeypatch):
    # The text says 死亡が確認された, so the pairing is 死亡が確認される — 死亡が確認する is not Japanese — and
    # 身元を確認した stays 身元を確認する. What a number counts is no partner: 2003年に設立した printed
    # 年に設立する, and 三年を過ごした 年を過ごす (found on the rebuilt shared set, 2026-09-25).
    rows = _rows("死亡が確認された。身元を確認した。2003年に設立した。三年を過ごした。三に分けた。",
                 tagger, monkeypatch)
    assert _items(rows, "確認", "colloc") == {"死亡が{w}される": 1, "身元を{w}する": 1}
    assert not any("年" in item for item in _items(rows, "設立", "colloc"))
    assert not any("年" in item for item in _items(rows, "過ごす", "colloc"))
    assert not any("三" in item for item in _items(rows, "分ける", "colloc"))     # nor a number itself


def test_compound_particles_are_printed_as_the_text_writes_them(tagger, monkeypatch):
    # UniDic splits として into と + し(為る) + て: the verb's dictionary form printed 啓示とする, 利用につく
    # (F4). As written — and a real とする stays とする.
    rows = _rows("啓示として受け取る。利用について話す。利用において重要だ。子供にとって大切だ。"
                 "目標とする。社会における問題。", tagger, monkeypatch)
    assert _items(rows, "啓示", "colloc") == {"{w}として": 1}
    assert _items(rows, "利用", "colloc") == {"{w}について": 1, "{w}において": 1}
    # における is 於く too (於け + る), and printed 社会におく until builder 6. One verb, one item: a word
    # with both shows the commoner writing.
    assert _items(rows, "社会", "colloc") == {"{w}における": 1}
    assert _items(rows, "子供", "colloc") == {"{w}にとって": 1}
    assert _items(rows, "目標", "colloc") == {"{w}とする": 1}


def test_an_adverb_pairs_with_its_predicate_and_takes_no(tagger, monkeypatch):
    # 再度 is a noun UniDic marks 副詞可能: 76% of its uses are adverbial (F11). Its predicates are its
    # pairings (A1), の after it is its particle, and used more as an adverb it is filed 副詞 — so its
    # card shows 〜の and 再度確認する. A plain adverb (やっぱり) gets the same.
    text = "再度確認する。再度見直す。再度行う。再度の襲撃。やっぱり行く。"
    rows = _rows(text, tagger, monkeypatch)
    adverbial = {item: n for item, n in _items(rows, "再度", "colloc").items() if not item.startswith("{w}の")}
    assert adverbial == {"{w}確認する": 1, "{w}見直す": 1, "{w}行う": 1}     # (再度の襲撃 is K1's, as for any noun)
    assert {(r[3], r[6]) for r in rows if r[0] == "再度" and r[2] == "particle"} == {("の", "after")}
    assert {r[6] for r in rows if r[0] == "再度" and r[2] == "colloc"} == {"A1", "K1"}
    lemmas = {r[0]: r[3] for r in pb.score(_counts(text, tagger), 1)[0]}
    assert lemmas["再度"] == "副詞"
    assert _items(rows, "矢張り", "colloc") == {"{w}行く": 1}           # UniDic files やっぱり under 矢張り


def test_an_adverbial_word_takes_no_compound_partner(tagger, monkeypatch):
    # After 再度, 最近 or 毎日 the next noun is where the sentence goes, not a word built with it: 再度交渉する
    # is A1's 再度交渉する, and the frames 〜交渉 / 〜攻撃 / 〜旅行 said nothing (found on the rebuilt data,
    # 2026-09-25: 以前 〜正真, 明日 〜奈). A noun's compound partners stay: 反省会.
    rows = _rows("再度交渉する。再度攻撃を行う。最近旅行に行った。毎日練習する。反省会を開く。", tagger, monkeypatch)
    assert _items(rows, "再度", "frame") == {}
    assert _items(rows, "再度", "colloc").get("{w}交渉する") == 1
    assert _items(rows, "最近", "frame") == {} and "〜練習" not in _items(rows, "毎日", "frame")
    assert _items(rows, "反省", "frame") == {"〜会": 1}


def test_an_ordinary_noun_never_counts_no_as_its_particle(tagger, monkeypatch):
    # D4 (2026-09-22): の stays out for ordinary nouns — only an adverbial word counts it.
    rows = _rows("先生の本。先生の車。先生が来た。", tagger, monkeypatch)
    assert {r[3] for r in rows if r[0] == "先生" and r[2] == "particle"} == {"が"}


def test_a_compound_partner_is_a_frame_named_by_its_length(tagger, monkeypatch):
    # 反省会, 反省点, 反省文: the nouns 反省 builds words with (the user, U6). A longer partner (経済政策)
    # is a frame too, in its own section so the lookup can hold it to one slot (U10).
    rows = _rows("反省会を開いた。反省点が多い。反省文を書く。経済政策を見直す。", tagger, monkeypatch)
    assert _items(rows, "反省", "frame") == {"〜会": 1, "〜点": 1, "〜文": 1}
    assert {r[6] for r in rows if r[0] == "反省" and r[2] == "frame"} == {"F4"}
    assert {(r[3], r[6]) for r in rows if r[0] == "経済" and r[2] == "frame"} == {("〜政策", "F4m")}


def test_a_person_is_never_a_partner_but_a_place_is(tagger, monkeypatch):
    # A series' names pass every count (船長のアーチャー, 王の手): no pairing or frame with a person's name
    # (UniDic 人名). Place names stay: 日本に降り立つ (§8.1 j).
    rows = _rows("田中を信じる。日本に降り立つ。友達の田中。友達の家。", tagger, monkeypatch)
    assert _items(rows, "信ずる", "colloc") == {}                    # UniDic files 信じる under 信ずる
    assert _items(rows, "下り立つ", "colloc") == {"日本に{w}": 1}      # ... and 降り立つ under 下り立つ
    assert _items(rows, "友達", "colloc") == {"{w}の家": 1}


def test_dekiru_is_a_form_of_a_noun(tagger, monkeypatch):
    # 利用できる 8% of 利用's uses (F10) — whichever way the text spells it.
    rows = _rows("利用できる。利用出来る。利用する。", tagger, monkeypatch)
    assert _items(rows, "利用", "form") == {"{w}できる": 2, "{w}する": 1}


def test_documents_are_files_in_a_library_and_blank_line_blocks_in_a_corpus(tmp_path):
    # A pattern seen in three documents is common; seen thirty times in one book it is that book's
    # (再度生老人, F7). A general corpus is staged one document per blank-line block; a library file is
    # one document — a subtitle file's cues are blank-line separated, and must never be split (§8.1 h).
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "staged.txt").write_text("大きな影響を受けた。\n\n大きな影響を受けた。\n\n大きな影響を受けた。\n",
                                       encoding="utf-8")
    general = str(tmp_path / "general.db")
    pb.build(corpus_dir=str(corpus), db_path=general, floor=1)
    sql = "SELECT files FROM pattern WHERE lemma = '影響' AND item = '{w}を受ける'"
    assert _db_rows(general, sql) == [(3,)]
    # (A subtitle file's cues lose their blank lines on reading; a book's text keeps its paragraphs'.)
    _library({"HighPriority/book.txt": "大きな影響を受けた。\n\n大きな影響を受けた。\n\n大きな影響を受けた。\n"})
    library = str(tmp_path / "library.db")
    pb.build(db_path=library, floor=1)
    assert _db_rows(library, sql) == [(1,)]


# --- a one-kanji word's lines come from its own uses ---------------------------------------------- #
def test_a_one_kanji_piece_glued_to_another_gives_its_row_no_line_and_the_word_alone_does(tagger, monkeypatch):
    # 炎剣 is no word a dictionary lists, so it reads as two one-kanji pieces, 炎 + 剣 — and a piece is no use of the
    # word (the list's own test, analyzer.bound_uses): 剣's row gets neither a count nor a line from it, nor 炎's.
    # 剣 standing on its own (剣が光る) gives its line as before; the two pieces still make their compound, which
    # keeps its own lines (大きな〜, を), and the verb still pairs with it.
    text = "大きな炎剣を抜く。剣が光る。"
    counts = _counts(text, tagger)
    word = {key: counts.word[i] for key, i in counts.ids.items() if counts.word[i]}
    assert word[("剣", "ケン")] == 1 and ("炎", "ホノオ") not in word
    assert counts.bound == {("炎", "ホノオ"): 1, ("剣", "ケン"): 1}
    assert counts.tokens == 8                       # 大きな 炎 剣 を 抜く 剣 が 光る: the corpus size does not shrink
    rows = _rows(text, tagger, monkeypatch)
    assert _items(rows, "剣", "particle") == {"が": 1}
    assert not [r for r in rows if r[0] == "炎"]
    assert _items(rows, "炎剣", "particle") == {"を": 1} and _items(rows, "炎剣", "frame") == {"大きな〜": 1}
    assert _items(rows, "抜く", "colloc") == {"炎剣を{w}": 1}


def test_a_one_kanji_word_right_after_a_number_gives_its_row_no_line(tagger, monkeypatch):
    # 年 in 三年, 3年 or 何年 counts years — a piece of the number, not the word 年, as the list has it: no count and
    # no line (三年が過ぎた gave 年 its が). 年 standing on its own in 年に一度 gives its line; 度 after 一 is a piece.
    counts = _counts("三年が過ぎた。3年が過ぎた。何年も待った。年に一度会う。", tagger)
    assert counts.word[counts.ids[("年", "ネン")]] == 1
    assert counts.bound == {("年", "ネン"): 3, ("度", "ド"): 1}
    rows = _rows("三年が過ぎた。3年が過ぎた。何年も待った。年に一度会う。", tagger, monkeypatch)
    assert _items(rows, "年", "particle") == {"に": 1}
    assert not [r for r in rows if r[0] == "度"]


def test_a_one_kanji_word_after_a_numbers_counter_is_a_piece_as_the_list_counts_it(tagger, monkeypatch):
    # The list's counter clause (analyzer._bound_at, ENGINE 29): the 目 of ２時間目, the 前 of 三週間前 and the 半 of
    # 二時間半 belong to the count — no use of 目 'eye' — and the builder sees the number two tokens back, as the list
    # does on the whole sentence (asking the word's two neighbours alone missed it: found 2026-10-01, before the v5
    # build). 目 standing on its own (目を開けた) and 三の矢's 矢 (の between: the arrow) stay uses.
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)
    text = "２時間目の授業が始まった。三週間前に会った。二時間半も待った。目を開けた。三の矢を放った。"
    counts = _counts(text, tagger)
    assert {lemma for lemma, _reading in counts.bound} == {"目", "前", "半"}
    word = {key[0]: counts.word[i] for key, i in counts.ids.items() if counts.word[i]}
    assert word["目"] == 1 and word["矢"] == 1
    # One rule: sentence by sentence, the builder's pieces are the list's.
    listed = Counter()
    for s_text, tokens in analyzer.JapaneseTokenizer(library=False).tokenize_sentences(text):
        listed.update((tokens[i][0], tokens[i][1]) for i in analyzer.bound_uses(s_text, tokens))
    assert Counter(counts.bound) == listed


def test_a_joined_words_one_kanji_part_is_judged_as_the_parts_stand(tagger):
    # A word made of parts gives its parts their uses too (利用者: 利用 gets 〜者) — but a one-kanji part glued to
    # another one-kanji part (氷刃: 氷 + 刃) or right after a number (二十歳: 二十 + 歳) is a piece there, and gives
    # its row nothing. A one-kanji part after a longer one stands on its own (誕生日: 誕生 + 日), as in the list.
    counts = _counts("氷刃を振るう。二十歳になった。誕生日だ。", tagger)
    word = {key: counts.word[i] for key, i in counts.ids.items() if counts.word[i]}
    assert word[("氷刃", "ヒョウジン")] == 1 and word[("二十歳", "ハタチ")] == 1 and word[("日", "ヒ")] == 1
    assert {lemma for lemma, _reading in counts.bound} == {"氷", "刃", "歳"}
    assert not {lemma for lemma, _reading in word} & {"氷", "刃", "歳"}


def test_a_piece_is_still_its_neighbours_partner_weighed_by_every_use(tagger, monkeypatch):
    # Only the piece's own row changes: its neighbours keep every line it gives them (利用者層: 利用 keeps 〜者, though
    # 者 is a piece there, glued to 層), and a pairing's strength weighs its partner by every time the text holds it
    # — 剣 appears four times, three of them in 炎剣, so 剣を抜く scores logDice(1, 1, 4), as it always has.
    rows = _rows("利用者層が広い。", tagger, monkeypatch)
    assert _items(rows, "利用", "frame") == {"〜者": 1}
    assert not [r for r in rows if r[0] == "者"]
    rows = _rows("剣を抜く。炎剣が光る。炎剣が光る。炎剣が光る。", tagger, monkeypatch)
    strength = {r[3]: r[5] for r in rows if r[0] == "抜く" and r[2] == "colloc"}
    assert strength == {"剣を{w}": round(pb.log_dice(1, 1, 4), 3)}


def test_the_builder_finds_the_pieces_the_list_finds_on_real_text(tagger, monkeypatch):
    # One rule: over the repo's real sample files, the uses the builder takes as pieces are exactly the ones the list
    # does (analyzer.bound_uses over the tokenizer's sentences, read without one library's name tables, as the builder
    # reads, and with the lemmas the analyzer counts by: 君, never UniDic's 君-代名詞) — the builder asks only a word's
    # two neighbours, and only when a number or a kanji touches it, so this holds it to the test it borrows.
    monkeypatch.setattr(analyzer, "SANITIZE_JA", True)
    boundaries = frozenset(analyzer.LOGIC["sentence_boundaries"]["ja"])
    tokenizer, listed, built = analyzer.JapaneseTokenizer(library=False), Counter(), Counter()
    for name in ("HighPriority/H_priority_sample_1.txt", "LowPriority/L_priority_sample_1.txt",
                 "LowPriority/L_priority_sample_2.txt"):
        with open(os.path.join(_ROOT, "samples", "ja", name), encoding="utf-8") as f:
            text = f.read()
        for s_text, tokens in tokenizer.tokenize_sentences(text):
            listed.update((tokens[i][0], tokens[i][1]) for i in analyzer.bound_uses(s_text, tokens))
        for sentence in pb.iter_tokens(text, tagger, analyzer._sanitize_term, boundaries):
            built.update((t.lemma, t.reading) for i, t in enumerate(sentence)
                         if t.word and len(t.lemma) == 1 and pb._piece(sentence, i, analyzer))
    assert sum(listed.values()) >= 10 and built == listed


def test_a_mark_the_tagger_reads_apart_beside_a_one_kanji_word_is_no_neighbour(tagger):
    # An accent mark after a kanji (text from a web page or a PDF) rides with the kanji, and the tagger reads it as a
    # piece of its own with no text: after 花 or before 年 it is no number and no kanji, so the word stands on its own
    # — and the build goes on (a general corpus once stopped on such an empty neighbour).
    counts = _counts("花\u0301が咲く。カフェ\u0301年に一度行く。三年\u0301が過ぎた。", tagger)
    word = {key: counts.word[i] for key, i in counts.ids.items() if counts.word[i]}
    assert word[("花", "ハナ")] == 1 and word[("年", "ネン")] == 1
    assert counts.bound == {("年", "ネン"): 1, ("度", "ド"): 1}     # 三年 is a count, whatever follows it


# --- the library's corpus: the tier folders and the content folder (3.0 Sources) ---------------------------------- #
_OLD_LIBRARY_FOLDERS = ("HighPriority", "LowPriority", "GoalContent", "Graduated")


def _library_tree(root, with_content_folder):
    """A synthetic library: shows in the tier folders, Processed (never read), a trash, and (asked) `Library/<show>`."""
    files = ["HighPriority/星の旅人/第01話.srt", "HighPriority/第01話.srt", "LowPriority/深夜特急/巻1/ch01.txt",
             "GoalContent/三体/chapter_1.txt", "Graduated/旅/ep01.ass", "Processed/旅/part_001.txt",
             "HighPriority/.trash/消えた.txt", "HighPriority/星の旅人/cover.jpg"]
    if with_content_folder:
        files += ["Library/月の庭/第01話.srt", "Library/月の庭/.trash/消えた.srt"]
    for rel in files:
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("今日は天気がいい。\n")


def test_a_library_with_no_content_folder_gives_the_same_file_list_as_before(tmp_path, monkeypatch):
    """A 2.x-shaped library: the corpus is the old list, file for file and in the same order."""
    _library_tree(str(tmp_path), with_content_folder=False)
    monkeypatch.setattr("app.path_utils.get_data_path", lambda language: str(tmp_path))
    now = pb.corpus_files(None, "ja")
    monkeypatch.setattr(pb, "LIBRARY_FOLDERS", _OLD_LIBRARY_FOLDERS)
    assert now == pb.corpus_files(None, "ja")
    assert now[0] == "library" and len(now[2]) == 5


def test_a_content_folder_copy_is_read_once_as_its_tier_twin_is(tmp_path, monkeypatch):
    """`Library/<show>/file` is in the library's set, once, its trash never; the tier folders' files come first, as
    before (the build counts each distinct file once)."""
    _library_tree(str(tmp_path), with_content_folder=True)
    monkeypatch.setattr("app.path_utils.get_data_path", lambda language: str(tmp_path))
    _kind, _root, paths = pb.corpus_files(None, "ja")
    rels = [os.path.relpath(p, str(tmp_path)).replace(os.sep, "/") for p in paths]
    assert rels.count("Library/月の庭/第01話.srt") == 1
    assert rels[-1] == "Library/月の庭/第01話.srt" and len(rels) == 6
    assert not any(".trash" in r or r.startswith("Processed/") for r in rels)
