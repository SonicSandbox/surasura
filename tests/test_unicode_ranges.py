"""`app/unicode_ranges.py` — Han and kana, the Unicode Standard's own blocks, defined once.

Every script test in the app used to spell its own range, and each stopped short somewhere else: the Japanese
test at U+9FAF, the Chinese one at U+9FFF, anki_match at U+FAFF, none past the Basic Multilingual Plane. A 𩸽
card (ほっけ, CJK Extension B) was dropped by the Anki sync, 〇 in 二〇一六年 and 䶮 (Extension A) were no Chinese,
and the ・ of a Chinese name counted as kana. These tests pin the one
definition to Unicode itself — the character names in Python's own Unicode database — and check that every core
script test reads it. (The Junban module checks its own readers in modules/junban/tests.)
"""
import re
import unicodedata

import pytest

from app import analyzer, anki_match, anki_sync, sentence_corpus
from app.unicode_ranges import HAN, KANA, KANA_LETTERS

_HAN = re.compile(f"[{HAN}]")
_KANA = re.compile(f"[{KANA}]")
_KANA_LETTER = re.compile(f"[{KANA_LETTERS}]")
# The kana blocks' characters Unicode's Scripts.txt files as Common or Inherited, not Hiragana / Katakana: the
# (combining) voiced sound marks ゛ ゜, the double hyphen ゠, the middle dot ・ and the prolonged sound mark ー.
_NOT_LETTERS = {0x3099, 0x309A, 0x309B, 0x309C, 0x30A0, 0x30FB, 0x30FC}

# Characters past the old ranges, each a real one: 𩸽 ほっけ and 𠮷 (the 吉 of 𠮷野家) are Extension B, 䶮 names a
# Southern Han emperor (刘䶮, CC-CEDICT) and 㗎 is a Cantonese particle (Extension A), 〇 is the zero of 二〇一六年,
# 々 the iteration mark of 人々, and U+9FF0 sits in the Unified Ideographs block past U+9FAF.
BEYOND_THE_OLD_RANGES = ["𩸽", "𠮷", "䶮", "㗎", "〇", "々", chr(0x9FF0), chr(0xFA11)]


def _assigned(first, last):
    """(character, its Unicode name) for every assigned code point in [first, last]."""
    for cp in range(first, last + 1):
        name = unicodedata.name(chr(cp), "")
        if name:
            yield chr(cp), name


def test_han_is_every_character_unicode_names_a_cjk_ideograph_and_nothing_else():
    """Extension A, the whole Unified block, the compatibility ideographs and Extension B on are Han — with 々 and
    〇, Han by their Script property. The radicals (a Kangxi radical is a symbol NFKC reads as its ideograph) and
    every other symbol are not."""
    ideograph = ("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-")
    for ch, name in _assigned(0x2000, 0x3FFFF):
        assert bool(_HAN.fullmatch(ch)) == (name.startswith(ideograph) or ch in "々〇"), (hex(ord(ch)), name)


def test_kana_is_every_character_of_the_kana_blocks_and_nothing_else():
    """Hiragana, Katakana (ー and ・ included), Katakana Phonetic Extensions and the historic kana of plane 1 — and
    no half-width or circled katakana: those are compatibility forms, which NFKC reads as the kana blocks' own."""
    blocks = ((0x3040, 0x30FF), (0x31F0, 0x31FF), (0x1AFF0, 0x1B16F))
    for ch, name in _assigned(0x2000, 0x1FFFF):
        in_a_block = any(first <= ord(ch) <= last for first, last in blocks)
        assert bool(_KANA.fullmatch(ch)) == in_a_block, (hex(ord(ch)), name)
    assert not _KANA.search("ｷﾐ") and not _KANA.search(chr(0x32D0)), "half-width ｷﾐ, circled katakana A"


def test_a_kana_letter_is_every_kana_block_character_but_its_punctuation():
    """KANA_LETTERS — what a Chinese test counts as kana: every character of the kana blocks whose Script is
    Hiragana or Katakana (the iteration marks ゝ ヽ and Ainu's ㇰ included), never ・ — the name dot Chinese
    writes too (约翰・列侬) — nor ー and the sound marks."""
    blocks = ((0x3040, 0x30FF), (0x31F0, 0x31FF), (0x1AFF0, 0x1B16F))
    for ch, name in _assigned(0x2000, 0x1FFFF):
        letter = any(first <= ord(ch) <= last for first, last in blocks) and ord(ch) not in _NOT_LETTERS
        assert bool(_KANA_LETTER.fullmatch(ch)) == letter, (hex(ord(ch)), name)


def test_the_chinese_tokenizers_kana_test_is_the_kana_letters():
    """A Chinese token holding a kana letter is Japanese noise; ・ and ー are no kana letter."""
    assert all(analyzer._KANA_LETTER_RE.search(ch) for ch in "あアゝヽㇰ")
    assert not any(analyzer._KANA_LETTER_RE.search(ch) for ch in "・ー゠")


@pytest.mark.parametrize("ch", BEYOND_THE_OLD_RANGES)
def test_every_script_test_sees_the_same_han(ch):
    """The analyzer's Japanese and Chinese tests, the Anki sync's copies (it must not import the analyzer), the
    matcher's and the sentence dictionary's "has a kanji": one answer for one character."""
    assert analyzer.has_target_language(ch, "ja") and analyzer.has_target_language(ch, "zh")
    assert anki_sync._has_target(ch, "ja") and anki_sync._has_target(ch, "zh")
    assert anki_match._KANJI_RE.search(ch) and sentence_corpus._KANJI.search(ch)


def test_latin_and_digits_are_neither_language_and_half_width_katakana_is_read_not_ranged():
    """What the ranges leave out is still out: Latin and digits (ASCII and full-width) are neither language, and
    half-width katakana (a compatibility form) is in no range. The analyzer's sentence check reads a line the way
    the tagger does (analyzer.tagger_text: ｷﾐ is its full-width form), so a subtitle written in half-width
    katakana counts as Japanese; the Anki sync's own check (no tokenizer, I6) reads the ranges only."""
    for text in ("iPhone", "2026", "２０２６"):
        assert not analyzer.has_target_language(text, "ja") and not anki_sync._has_target(text, "ja"), text
        assert not analyzer.has_target_language(text, "zh"), text
    assert not anki_sync._has_target("ｷﾐ", "ja")
    assert analyzer.has_target_language("ｷﾐ", "ja") and not analyzer.has_target_language("ｷﾐ", "zh")

