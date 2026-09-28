"""Han and kana — the Unicode Standard's own blocks and Script property, defined in ONE place.

Every script test builds its character class from these: whether a text holds Japanese or Chinese
(`analyzer.has_target_language`, the Anki sync), whether a Chinese token, card or note is Chinese and not
Japanese (the ChineseTokenizer, パターン zh, Backfill), whether a card's word holds a kanji (`anki_match`,
Anki's bracket furigana, the sentence dictionary), whether a word is written in kana alone. Each used to
spell its own range, and they stopped short in different places — the Japanese test (the analyzer, the
Anki sync) at U+9FAF, the Chinese one at U+9FFF, anki_match at U+FAFF, none past the Basic Multilingual
Plane — so a 𠮷 or 𩸽 card (CJK Extension B) was dropped by the Anki sync, 〇 in 二〇一六年 and 䶮
(Extension A) were no Chinese, and the ・ of a Chinese name (约翰・列侬) counted as kana.

Each is the inside of a character class — `re.compile(f"[{KANA}{HAN}]")` — never a pattern of its own.
Pure: no imports, so the dashboard's Anki sync can read it without the analyzer (Anki_Known_Sync_Spec I6).
"""

# Han: the CJK ideographs — the Unified Ideographs (U+4E00–9FFF), Extension A (U+3400–4DBF), the
# Compatibility Ideographs (U+F900–FAFF), and planes 2 and 3, which Unicode gives to CJK ideographs alone
# (Extensions B–F and I, the Compatibility Ideographs Supplement, G, H and those still to come) — with 々 and
# 〇, Han by their Script property though they sit among the CJK symbols (人々, 二〇一六年).
HAN = "\u3005\u3007\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0003FFFF"

# Kana: the kana blocks — Hiragana and Katakana (U+3040–30FF, its ・ and ー included), Katakana Phonetic
# Extensions (U+31F0–31FF, the small ㇰ of Ainu) and the historic kana of plane 1 (U+1AFF0–1B16F: Kana
# Extended-B, Kana Supplement, Kana Extended-A, Small Kana Extension). Half-width katakana (U+FF65–FF9F)
# are compatibility forms, which NFKC reads as these, and no kana block.
KANA = "\u3040-\u30FF\u31F0-\u31FF\U0001AFF0-\U0001B16F"

# The kana LETTERS of those blocks, by their Script property (Hiragana, Katakana) — never the blocks' ・ ー ゠
# ゛ ゜, which Unicode files as Common: ・ is Chinese's name separator too (约翰・列侬). A test that tells
# Japanese from Chinese — does this Chinese token, card or note hold kana? — reads these.
KANA_LETTERS = "\u3041-\u3096\u309D-\u309F\u30A1-\u30FA\u30FD-\u30FF\u31F0-\u31FF\U0001AFF0-\U0001B16F"
