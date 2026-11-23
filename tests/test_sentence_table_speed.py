"""The sentence table, made cheap at Generate (E-SPEED): the same numbers and the same bytes as the way first built.

What these prove:
  - the one pass that counts a line's two numbers (`LineWords`: words besides the word, where it starts) gives every
    line of the real ja + zh files the numbers the rule written out whole gives (`LineWords._linked`, kept for a line
    that holds a name link) — with and without people's names, for every word and every set-phrase span in it;
  - the lines that take the rule's corners (a token the text doesn't hold, a helping verb after て, a counter after
    its number, a person with a title, a call, a name link) agree too;
  - the table packed from real lines is the same bytes as before the speed work (its content pinned: the head, the
    sources, the formulas and every block, decompressed — so a zlib of another build can't move it);
  - a line offered for several words keeps each word's own numbers and co-words, and the finish lets go of the packed
    lines (another line can still be added after it) and works in little more memory than the lines themselves.

What a wrong answer would cost a learner: the card's sentence chosen on a wrong count of what it says about the word,
or a Generate that holds hundreds of MB more at its end than it did — the slow PC the app is meant for runs out.
"""
import hashlib
import json
import os
import tracemalloc
import zlib

import pytest

from app import plan_rules
from app import sentence_table as st

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(REPO, "tests", "Test Resources")
FILES = {
    "ja": ("sentence_words.txt", "context_test.txt", "runaway_transcript.txt", "phrases_sample.srt",
           "placed_episode.srt", "rare_compound_episode.ja.srt", "readings_sample.srt", "repeated_lines.ja.srt",
           "utterances_sample.srt", "library_episode.ass", "tv_captions.ass"),
    "zh": ("sentence_words.txt", "mixed_script_transcript.txt", "chinese_text_1.txt", "night_market.srt",
           "context_test.txt"),
}


def _lines(language):
    """Every sentence of the language's real files, as the walk reads them: [(text, tokens)], tokens as the store
    keeps them (lemma, reading, surface, spelling)."""
    from app import analyzer
    tokenizer = analyzer.JapaneseTokenizer() if language == "ja" else analyzer.ChineseTokenizer()
    out = []
    for name in FILES[language]:
        for text, tokens in analyzer._tokenize_file(tokenizer, os.path.join(RESOURCES, language, name), language):
            out.append((text, [tuple(t) for t in tokens]))
    return out


@pytest.fixture(scope="module", params=["ja", "zh"])
def real(request):
    language = request.param
    return language, _lines(language)


def _whole(tokens, text, language, people):
    """The rule written out whole, asked of any line (the one pass asks it only of a line holding a name link)."""
    words = st.LineWords.__new__(st.LineWords)
    words.tokens = tokens
    words._linked(tokens, text, *st._lists(language), people)
    return words


def _answers(words, tokens):
    keys = list(dict.fromkeys((t[0], t[1]) for t in tokens))
    spans = [(a, a + n) for n in (1, 2, 3) for a in range(len(tokens))]
    return (list(words.at), [bool(c) for c in words.counted], words.total, [words.of_word(k) for k in keys],
            [words.of_span(a, b) for a, b in spans], words.of_word(("無い語", "ナイゴ")))


def _people(lines):
    """Names to ask the person rule with: every katakana surface of two or more (taken as its lemma), and 私 — a word
    the library would never name, so a line about it counts it and a call to it does not."""
    import re
    kata = re.compile(r"[゠-ヿ]{2,}")
    return frozenset({t[0] for _text, tokens in lines for t in tokens if kata.fullmatch(t[2])} | {"私"})


def test_the_one_pass_gives_every_real_line_the_numbers_the_rule_written_out_whole_gives(real):
    # why: the one pass is what Generate runs a million times at 20,000 files; the rule written out whole is the one
    # the sentence study scored. Every real line, every word and every phrase span in it: the same two numbers
    language, lines = real
    assert len(lines) > 100
    for people in (frozenset(), _people(lines)):
        for text, tokens in lines:
            assert _answers(st.LineWords(tokens, text, language, people), tokens) == \
                _answers(_whole(tokens, text, language, people), tokens), text


CORNERS = [
    # (text, tokens as (lemma, reading, surface), people)
    ("駅人", [("」", "", "」"), ("駅", "エキ", "駅"), ("人", "ヒト", "人")], ()),                      # a token not in the text
    ("見ている", [("見る", "ミル", "見"), ("て", "テ", "て"), ("居る", "イル", "いる")], ()),            # a helping verb
    ("見 いる", [("見る", "ミル", "見"), ("て", "テ", "て"), ("居る", "イル", "いる")], ()),             # て not in the text
    ("走っていく", [("走る", "ハシル", "走っ"), ("て", "テ", "て"), ("行く", "イク", "いく")], ()),
    ("三人と２０分", [("人", "ニン", "人"), ("と", "ト", "と"), ("分", "フン", "分")], ()),               # counters
    ("ルーサー警部は来た", [("ルーサー", "ルーサー", "ルーサー"), ("警部", "ケイブ", "警部"), ("は", "ハ", "は"),
                          ("来る", "クル", "来"), ("た", "タ", "た")], ("ルーサー",)),                    # a person, titled
    ("ありがとう、ルーサー", [("ありがとう", "アリガトウ", "ありがとう"), ("ルーサー", "ルーサー", "ルーサー")],
     ("ルーサー",)),                                                                                  # a call
    ("ルーサー！ 来て", [("ルーサー", "ルーサー", "ルーサー"), ("来る", "クル", "来"), ("て", "テ", "て")],
     ("ルーサー",)),
    ("ルーサーだ", [("ルーサー", "ルーサー", "ルーサー"), ("だ", "ダ", "だ")], ("ルーサー",)),
    ("フランク・ライアンが来た", [("フランク", "フランク", "フランク"), ("ライアン", "ライアン", "ライアン"),
                              ("が", "ガ", "が"), ("来る", "クル", "来"), ("た", "タ", "た")], ("フランク",)),
    ("Ａ＝Ｂです", [("Ａ", "エー", "Ａ"), ("Ｂ", "ビー", "Ｂ"), ("です", "デス", "です")], ()),
    ("……", [("…", "", "…"), ("…", "", "…")], ()),                                                    # marks only
    ("", [], ()),
    ("駅駅", [("駅", "エキ", "駅"), ("駅", "エキ", "駅")], ()),                                          # a word twice
    ("いるいる", [("居る", "イル", "いる"), ("居る", "イル", "いる")], ()),                              # a helper first
    ("駅は三", [("駅", "エキ", "駅"), ("は", "ハ", "は"), ("三", "サン", "三")], ()),                    # first, a numeral last
    ("ルーサー、は", [("ルーサー", "ルーサー", "ルーサー"), ("警部", "ケイブ", "警部"), ("は", "ハ", "は")],
     ("ルーサー",)),                                                                                  # a title not in the text
]


@pytest.mark.parametrize("text, tokens, people", CORNERS, ids=[c[0] or "empty" for c in CORNERS])
def test_the_rules_corners_count_in_the_one_pass_as_in_the_rule_written_out_whole(text, tokens, people):
    # why: the real files hold few of these; each is a branch of the rule (a quote mark cut off, 見ている, 三人, a
    # titled name, a call at the line's end or before a mark, a name of two pieces) the one pass takes on its own
    tokens = [(lemma, reading, surface, surface) for lemma, reading, surface in tokens]
    people = frozenset(people)
    assert _answers(st.LineWords(tokens, text, "ja", people), tokens) == \
        _answers(_whole(tokens, text, "ja", people), tokens)


def test_a_chinese_line_with_an_equals_sign_takes_the_rule_written_out_whole_and_agrees():
    # why: = is a name link for the rule; a Chinese line holding one (a formula in a transcript) goes the long way
    from app import analyzer
    (text, tokens), = analyzer.ChineseTokenizer().tokenize_sentences("他说一加一=二，老师笑了。")
    assert "=" in text
    assert _answers(st.LineWords(tokens, text, "zh"), tokens) == _answers(_whole(tokens, text, "zh", frozenset()),
                                                                          tokens)


def _pack(language, lines):
    """A table packed as the walk packs it from real lines: every word of a line that is said twice or more in the
    language's files is a row; each line offered for each of its words with the line's other words as co-words (the
    same set object for all of a line's words, as the walk passes it) and its two numbers from LineWords; a word known
    from the start (the first three rows) is left out of the formulas."""
    from collections import Counter
    said = Counter(k for _text, tokens in lines for k in {(t[0], t[1]) for t in tokens})
    keys = sorted(k for k, n in said.items() if n >= 2)
    row = {k: i for i, k in enumerate(keys)}
    p = st.Packer()
    for number, (text, tokens) in enumerate(lines):
        words = st.LineWords(tokens, text, language)
        unknown = {(t[0], t[1]) for t in tokens} - set(keys[:3])
        for key in dict.fromkeys((t[0], t[1]) for t in tokens):
            p.add(key, number % 7, number, len(text), plan_rules.text_hash_of(text), unknown, (number % 3,) * (number % 2),
                  *words.of_word(key), over=len(text) > 40)
    clauses = (lambda k: plan_rules.TRUE if k in keys[:3] else ((row[k],),) if k in row else plan_rules.FALSE)
    return p, p.finish(keys, row.get, clauses, lambda k: row.get(k, -1), lambda k: k, lambda i: i if i < 2 else None,
                       [[f"show/{n}.srt", "subtitle", None] for n in range(7)],
                       {"engine": "e47", "run_signature": "sig", "language": language},
                       places=list(range(len(keys))))


def _content(path):
    """sha256 of the table's content: its head, sources and formulas as read, and every block decompressed."""
    raw = open(path, "rb").read()
    hl, sl, fl = (int.from_bytes(raw[8 + 4 * i:12 + 4 * i], "little") for i in range(3))
    at = 20
    parts = []
    for size in (hl, sl, fl):
        parts.append(zlib.decompress(raw[at:at + size]))
        at += size
    for size in json.loads(parts[0])["sizes"]:
        parts.append(zlib.decompress(raw[at:at + size]))
        at += size
    assert at == len(raw)
    return hashlib.sha256(b"|".join(parts)).hexdigest()


# Pinned from 3.0-dev d171b0c7 (the table as E-TABLE built it), before the speed work: re-pin only with a change of
# the table's bytes made on purpose (and its format's VERSION).
PINNED = {"ja": "bc918e6d781de5bc56622ae4acec772a4d4dccbccefc44604146fed1ab562c3d",
          "zh": "5988eb87850ebfbdc0bf8d1f75e474e647e69c8b908c467712d09f58bcf970ec"}


def test_the_table_packed_from_real_lines_is_the_same_bytes_as_before_the_speed_work(real, tmp_path):
    # why: the speed work changes how the lines are held and put together, never what the table says; a reader
    # (the card's pick, Swap) must read exactly what it read before
    language, lines = real
    _p, table = _pack(language, lines)
    path = str(tmp_path / st.TABLE_FILE)
    table.write(path)
    assert _content(path) == PINNED[language]


def test_a_line_offered_for_several_words_keeps_each_words_own_numbers_and_co_words(tmp_path):
    # why: the packer reuses the co-words' ids of a line offered again with the same set; a set it has not seen, or
    # one seen before another, must still get its own ids — never the last line's
    a, b, c = ("駅", "エキ"), ("人", "ヒト"), ("犬", "イヌ")
    first, second = {b, c}, {a}
    p = st.Packer()
    p.add(a, 0, 0, 5, 11, first, besides=2, starts=0)
    p.add(b, 0, 0, 5, 11, first, besides=1, starts=1)       # the same line, the same set: its ids reused
    p.add(c, 0, 1, 4, 12, second, besides=1, starts=2)
    p.add(b, 0, 2, 6, 13, first, besides=3, starts=4)       # the first set again, after another
    p.add(c, 0, 3, 6, 14, {a, b}, besides=0, starts=5)      # a new set equal to none before
    keys = [a, b, c]
    row = {k: i for i, k in enumerate(keys)}
    t = p.finish(keys, row.get, lambda k: ((row[k],),), row.get, lambda k: k, lambda i: None, [["s", "subtitle", None]],
                 {"engine": "e47", "run_signature": "sig", "language": "ja"})
    path = str(tmp_path / "t.bin")
    t.write(path)
    t = st.open_table(path)
    got = {}
    for k in range(3):
        cols, cow, _phr = t.block(k)
        at = 0
        for i in range(len(cols["src"])):
            n = int(cols["ncow"][i])
            got.setdefault(k, []).append((int(cols["number"][i]), int(cols["besides"][i]), int(cols["starts"][i]),
                                          sorted(cow[at:at + n].tolist())))
            at += n
    # co-words numbered by key: 人 0, 犬 1, 駅 2
    assert got == {0: [(0, 2, 0, [0, 1])], 1: [(0, 1, 1, [0, 1]), (2, 3, 4, [0, 1])],
                   2: [(1, 1, 2, [2]), (3, 0, 5, [0, 2])]}


def _big(lines=40000, cowords=17):
    """A packer of many lines with many co-words each (as the Chinese root: 17 a line), real keys' shape."""
    keys = [(f"語{i}", f"ゴ{i}") for i in range(900)]
    p = st.Packer()
    for n in range(lines):
        p.add(keys[n % 900], n // 50, n % 50, 20 + n % 40, n * 2654435761,
              {keys[(n * 7 + j * 13) % 900] for j in range(cowords)}, (), n % 9, n % 60)
    row = {k: i for i, k in enumerate(keys)}
    return p, keys, row


def test_the_finish_lets_go_of_the_packed_lines_and_works_in_little_more_memory_than_they_take():
    # why: the finish runs at the end of a Generate, at the run's most memory; working in 8-byte copies of every
    # line and co-word cost a 400-file Chinese library 160 MB there (the packed lines took 19 MB)
    p, keys, row = _big()
    packed = 40000 * 31 + 40000 * 17 * 4        # the lines as packed: 31 bytes a line, 4 a co-word's id
    tracemalloc.start()
    try:
        t = p.finish(keys, row.get, lambda k: ((row[k],),), row.get, lambda k: k, lambda i: None,
                     [["s", "subtitle", None]], {"engine": "e47", "run_signature": "sig", "language": "zh"})
        _now, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert sum(t.head["lines"]) == 40000
    # measured: 5.1 x packed since the speed work, 11.8 x on 3.0-dev d171b0c7 (its int64 copies) — the bound between
    assert peak < 8 * packed, (peak, packed)
    p.add(keys[0], 0, 99, 5, 1)                 # no view of the packed lines is left behind
    assert len(p) == 40001
