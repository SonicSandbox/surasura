"""Kansai words the tagger can't read — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_kansai_data.py   (after scripts/build_reference_data.py)

Revision: 2026-11-07-8a708a62
  WORDS  12 words -> {spelling: [lemma, reading, pos1, first piece, pieces]}: JMdict's Kansai-ben words (ksb)
         both JPDB 2024 and Jiten rank within 60,000, in a kana spelling the tokenizer reads, alone, as pieces it made
         up (a filler, a symbol, a proper noun: あかん is あ + 彼). The tokenizer joins such a run into the word
         (app/analyzer.py § Kansai); `first piece` and `pieces` are how it reads the spelling alone.

Derived from JMdict (JMdict created 2026-09-28), a dictionary of the JMdict/EDICT project, property of the Electronic
Dictionary Research and Development Group (EDRDG), used in conformance with the Group's licence: Creative Commons
Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), https://creativecommons.org/licenses/by-sa/4.0/ —
https://www.edrdg.org/edrdg/licence.html, https://www.edrdg.org/jmdict/j_jmdict.html. Changes: only the kana headwords
of its Kansai words are kept (no glosses), with a part of speech, those the frequency lists rank and the tokenizer
misreads. This table is shared under the same licence.
"""

REVISION = "2026-11-07-8a708a62"
JMDICT_CREATED = "2026-09-28"
COUNT = 12

_WORDS = {
    "あかん": ["あかん", "アカン", "形状詞", "あ", 2],
    "あほう": ["阿呆", "アホウ", "形状詞", "あ", 2],
    "あんなあ": ["あんなあ", "アンナア", "感動詞", "あんな", 2],
    "いやや": ["いやや", "イヤヤ", "感動詞", "い", 2],
    "いんじゃん": ["いんじゃん", "インジャン", "名詞", "い", 3],
    "おかん": ["おかん", "オカン", "名詞", "お", 2],
    "げぼ": ["げぼ", "ゲボ", "名詞", "げ", 2],
    "せやな": ["せやな", "セヤナ", "形状詞", "せや", 2],
    "めっさ": ["めっさ", "メッサ", "副詞", "め", 3],
    "わいや": ["わいや", "ワイヤ", "副詞", "わ", 2],
    "アホんだら": ["阿呆陀羅", "アホダラ", "名詞", "アホ", 3],
    "ドあほ": ["ドあほ", "ドアホ", "名詞", "ド", 2],
}


def words():
    """{spelling: [lemma, reading, pos1, first piece, pieces]} — every word (the table itself: never change it)."""
    return _WORDS
