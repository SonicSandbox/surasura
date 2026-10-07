import os
import sys

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import re
import csv
import hashlib
import threading
import time
import unicodedata
# Heavy libraries are imported LAZILY (inside the tokenizer classes / extract_text / main), NOT at
# module top. `jieba` alone costs ~0.17s to import, `pandas` ~0.35s, `fugashi` loads for Japanese,
# `pysrt` only for .srt files. Consequences: a "nothing changed" skip builds no tokenizer and writes
# no CSV, so it imports NONE of them; a Japanese run never loads jieba; a Chinese run never loads
# fugashi. (Python caches imports, so the repeated `import` inside a method is a cheap dict lookup.)
import bisect
from collections import defaultdict, Counter
from itertools import accumulate, compress, repeat
from operator import attrgetter, eq, itemgetter
from datetime import datetime
import abc

from app.path_utils import (get_user_file, get_resource, get_data_path, get_user_files_path,
                            is_content_file, infer_source_type, read_source_marker, read_text,
                            SUBTITLE_EXTENSIONS)
from app import settings_manager
from app import word_selection
from app import modality
from app import zh_script   # cheap: its tables decode only on the first conversion
from app import names       # cheap: its tables decode only when a Japanese word is first read
from app.batch_gc import without_cycle_collection
from app.unicode_ranges import HAN, KANA, KANA_LETTERS
from app import plan_rules  # the rules a Generate and the fast re-plan share (Orth / Forms, the progressive pass)

# Default Weights (Overwritten by settings.json if present)
WEIGHT_HIGH = 10
WEIGHT_LOW = 5
WEIGHT_GOAL = 2

# Filters
SKIP_SINGLE_CHARS = True
MIN_FREQ = 0  # Hide words with frequency <= MIN_FREQ
SANITIZE_JA = False # Strip -suffixes for Japanese
ONLY_I_PLUS_ONE = False
# Give the last example slot to a sentence you can hear, when none of the chosen ones came
# with audio. Off by default; set from --ensure-audio-example.
ENSURE_AUDIO_EXAMPLE = False

# BUMP THIS whenever a change alters what a run OUTPUTS for unchanged inputs — new/renamed CSV
# columns, different sentence selection, different scoring. It feeds the run-signature, so a bump
# invalidates every stored signature and forces a real re-run.
#
# Without it the signature's only engine component is `__version__`, which moves once per RELEASE:
# during development (and for any hotfix shipped without a version bump) identical inputs matched the
# stored signature and the analyzer served the OLD report from before the change.
# 10: Japanese words are keyed by the lemma's reading (UniDic lForm) — one row per word, however it
#     is conjugated (JapaneseTokenizer.tokenize_sentences).
# 11: library_frequency.json is written on every run and carries each word's first file, score and
#     spelling (Junban places a mined word below the list's cut-off where the journey meets it).
# 12: a Japanese example sentence loses a leading verse number (「13そこで…」 -> 「そこで…」,
#     strip_verse_number) — never a counted number (「3人で」, 「5番目」).
# 13: words keep their prefixes and suffixes — 不自然, 新幹線, 可能性 are one word each (join_affixes);
#     one you can read through its known word (利用者, 利用 known) scores half and is no unknown in a
#     sentence (U9).
# 14: the join table's お / ご words are decided once per word, however UniDic tags each spelling
#     (おやすみ, ご存知 / ご存じ); さ after a な-word and a prefix after a number stay apart (複雑さ, 三大祭り);
#     a Chinese run reads no Japanese spoken ranks, so no 文 badge on 描写. Still 2.3: one re-analysis with 13.
# 15: the parsing fixes (2026-09-27): every file read in its own encoding; subtitle markup
#     stripped but not its letters, and each format's own conventions honoured (headers, SDH cues, Aozora ruby,
#     scripture apparatus); sentences end per UAX #29 and the file's timing; the tagger reads NFKC (ﾅｲﾌ is ナイフ);
#     numbers and symbols are no words; Han by Unicode's own ranges; a hiragana list line names its word.
# 16: names stay whole (app/names.py) — a katakana name no dictionary lists, a katakana run the library keeps using
#     as one, and a JMnedict person name the library holds 3+ times are one word each, every switch in Settings.
#     Still 2.4: one re-analysis with 15.
# 17: a word stretched with a wave dash or a long mark is that word (すご～い is 凄い) and 𠮟 is 叱; quotations in a row
#     taken by what follows are one sentence, and a comma after closing marks continues it; a Chinese caption's line
#     break joins; broadcast captions part by speaker colour; a known-word entry is cut at a space only when no
#     Japanese follows, and KnownWord.json's IGNORED entries are ignored; a card field is its one word, a する or
#     copula form goes to its word, a kanji card read alone as one word is placed without asking. Still 2.4.
# 18: words made of words are one word (上層部, 一生懸命, 二十歳, 走り出す) and take their affixes (同性愛者); a sound
#     word + と is its word, shown with と (ドキッと); お守り and お帰り are words of their own; laughter in katakana
#     stays in pieces (アッハハ). A compound you can read through words you know sits lower and is no unknown; a rare
#     compound counts toward its parts. Still 2.4: one re-analysis with 15, 16 and 17.
# 19: a card with a polite お / ご, a plural (たち, ら, ども) or a noun-making さ / み on it is its word — 順, the "In
#     Anki" mark, パターン and 例文 read お部屋 as 部屋, 俺たち as 俺 and 優しさ as 優しい, as the list always has; an
#     お / ご word you can read through its word (お茶 through 茶) sits lower and is no unknown. Still 2.4: one
#     re-analysis with 15–18.
# 20: a story's own kanji words that the library keeps using as one are one word (logic.names_work_terms);
#     auto-generated captions don't count toward them. A katakana word the lists hold but no dictionary join makes
#     is one word, and a katakana name no longer takes the head of a word written on in hiragana. Still 2.4: one
#     re-analysis with 15–19.
# 21: a word general text writes as words, though the tagger reads it otherwise alone, is one word (出来損ない, 通行止め,
#     郵便受け), and a verb's stem may stand in a noun the dictionaries mark (立ち位置, 待ち時間, 見間違い) — so a card's
#     word alone is that noun too (出来損ない, not 出来る + 損なう). Still 2.4: one re-analysis with 15–20.
# 22: the dictionary decides whether a card is the word it is read as — a card JMdict gives an entry of its own (心する,
#     一気に, 揚げる, the noun 集い in the verb 集う's spellings) is a word of its own in 順, the "In Anki" mark, パターン
#     and 例文, never that word's row, known status, lines or sentences. Still 2.4: one re-analysis with 15–21.
# 23: sounds and dashes — two fillers the tagger cut out of one interjection are that word (まあ, ああ～, いえ), a sound
#     said three times or more that the dictionary doesn't know is the sound word said twice (ハァハァハァ is はあはあ),
#     a dash drawn out inside a word is a stretch (ザ─────ック, お母さ───ん), a dash is never a word (－ read as から),
#     and the next line's opening bracket glued to a full stop opens the next sentence (｡｢). Still 2.4: one re-analysis
#     with 15–22.
# 24: idioms and set phrases get rows of their own (logic.phrase_rows: 気がする, 腑に落ちる, もしかしたら) — a phrase whose
#     words you know sits lower, one waiting for a new word sorts after it; a word that lives only inside a phrase
#     (手っ取り) gives it its uses; a word's example sentences without a new phrase come first. Still 2.4: one
#     re-analysis with 15–23.
# 25: one-kanji dictionary words are list words (手, 目, 顔, こと, もの — app/one_kanji_data.py), counted where they
#     stand on their own (not 斬 in 斬魄刀, not 年 in 三年); a one-character word the list can never offer (は, スバル
#     read as 昴) keeps no sentence from i+1 and counts as nothing to learn in a file; each file names its one-kanji
#     words the list can't offer. Still 2.4: one re-analysis with 15–24.
# 26: Chinese reads like Chinese — …… and ；no longer end a sentence; Traditional text read as-is is cut through
#     Simplified (為什麼 one word, spelled as written); only jieba's dictionary makes a word (他来 is 他 + 来; a guessed
#     name led by a surname is kept); a jieba phrase CC-CEDICT doesn't list is its words (吃了饭 is 吃 + 了 + 饭, a count
#     its number and measure word: 一个 is 一 + 个); a number is no word; a doubled form is its word (开开心心 is 开心);
#     Traditional is written in Taiwan's standard characters (吃飯, 裡面); 著急 is read as 着急 where CC-CEDICT pairs
#     them; a Chinese card's field is its one word (学习 (xuéxí) is 学习; 认真地 认真, 吃了 吃). Still 2.4: one
#     re-analysis with 15–25.
# 27: words the tagger cuts at their grammar are the dictionary's words — a verb + its negative or causative JMdict's
#     editors list (くだらない, つまらない, 知らせる, 思わず; すまない only in kana) and a word + particles it lists as
#     an adverb or a conjunction (いつも, ちなみに, どうにか, a clause's でも), each counted as itself; a pronoun + a
#     suffix the lists carry is one word (何様, 俺様, お前さん — logic.pronoun_bases); a katakana word stretched inside
#     that is no word with its one ー is read without the stretch where that is a word (バイバ～イ is バイバイ); a
#     pre-noun phrase usually written in kana counts only written in kana (そういった). Still 2.4: one re-analysis
#     with 15–26.
# 28: a sound word said with と and without (one row) shows its と form when JMdict lists the word with its と
#     (ドキッと, ぐっと, はっと — _display_orth), so the list and the cards made from it write it as dictionaries do.
#     Still 2.4: one re-analysis with 15–27.
# 29: a one-kanji word right after a number's counter written in kanji is a piece of the count — the 目 of ２時間目
#     'second period', the 前 of 三週間前 — no use of 目 'eye' (_bound_at). Still 2.4: one re-analysis with 15–28.
# 30: the idiom data is rebuilt: a dictionary spelling the tokenizer reads as other words keys no phrase — 彼の方 'that
#     person' read 彼 'he' + の + 方 counted every 彼のほう 'his side', 口の端 'gossip' every corner of a mouth
#     (scripts/build_phrase_data.py, R6). Still 2.4: one re-analysis with 15–29.
# 31: Japanese TV captions are read through the caption cleaner (app/caption_clean.py, P1.3 row 1.3.2, ✅ G1.3-11 and
#     P1.3-1 a): a word's reading written as a small-type row of its own is no line and no words (its kana counted as
#     words before) — the list reads the lines Connect's pick and Anki Miner read. The release after 2.5: one re-analysis, with SCHEMA_VERSION 20.
ENGINE_REVISION = 31

# Load Logic Settings from settings.json
LOGIC = {
    "weights": {"high": 10, "low": 5, "goal": 2},
    "tiers": {"thresholds": [2500, 5000, 7500, 10000]},
    "context": {"search_range": 20, "min_words": 4, "max_extra": 2, "preferred_max_chars": 50},
    "sentence_boundaries": {
        "ja": "。｡．！？!?\n",
        "zh": "。｡！？!?\n"
    },
    "priority_markers": {
        "priority_threshold": 0.5,
        "priority_min": 3,
        "lopsided_threshold": 0.8
    }
}

try:
    full_settings = settings_manager.load_settings()
    LOGIC.update(full_settings.get("logic", {}))
    
    # Update global weights for backward compatibility in the script
    WEIGHT_HIGH = LOGIC["weights"].get("high", 10)
    WEIGHT_LOW = LOGIC["weights"].get("low", 5)
    WEIGHT_GOAL = LOGIC["weights"].get("goal", 2)
except Exception as e:
    print(f"Warning: Could not load logic settings: {e}")

# Paths - Now determined dynamically in main()
# RESULTS_DIR remains shared for the "Active" analysis result
RESULTS_DIR = get_user_file("results")
os.makedirs(RESULTS_DIR, exist_ok=True)

OUTPUT_CSV = os.path.join(RESULTS_DIR, "priority_learning_list.csv")
OUTPUT_STATS = os.path.join(RESULTS_DIR, "file_statistics.txt")
OUTPUT_PROGRESSIVE = os.path.join(RESULTS_DIR, "progressive_learning_list.csv")


# --- Classes & Functions ---

class Tokenizer(abc.ABC):
    @abc.abstractmethod
    def tokenize(self, text):
        pass

    @abc.abstractmethod
    def tokenize_sentences(self, text):
        pass

# --- What the tagger reads ---------------------------------------------------------------------------- #
# A compatibility character is the same text in another form (Unicode NFKC): ﾅｲﾌ is ナイフ, ５０ is 50, ⽅ — the
# Kangxi radical PDF extraction emits for 方 — is 方, ㌔ is キロ. A tagger knows one form only: unidic-lite reads
# ﾅｲﾌ as an unknown word (the library's 6,727 half-width katakana tokens were never counted), １０分 as the
# loanword テン + ブン, ⽅法 as nothing; jieba cuts a word at an invisible zero-width space. So every tagger call —
# both tokenizers, the known words, the token store, パターン, the sentence dictionary, 順 — reads text through
# `tagger_text`: a character whose NFKC form is made of letters, marks and digits is read in that form (ｶﾞ → ガ,
# Ａ → A, ① → 1, and か + U+3099 → が), a default-ignorable one (a zero-width space, a variation selector,
# a soft hyphen) is not read at all, and punctuation, symbols and spaces are read as written. Those are never
# words; UniDic writes Japanese punctuation full width (its lemma for ! is ！); and NFKC would turn a full-width
# space — a token that keeps two words apart — into a space the tagger skips. Each token keeps the text's own
# spelling as its surface (`Tagger`): what a sentence shows, what the boundary test reads, what a source anchor
# finds.

# Default_Ignorable_Code_Point (Unicode's DerivedCoreProperties.txt): invisible, no text of their own.
_IGNORABLE = ((0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C), (0x115F, 0x1160), (0x17B4, 0x17B5),
              (0x180B, 0x180F), (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164),
              (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF), (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
              (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF))
# One character, two code points — read as UniDic writes it. ～ (U+FF5E) is JIS X 0208's wave dash as Windows' code
# page 932 decodes it; the JIS standard's own mapping, and UniDic, write it 〜 (U+301C): すご〜い and あま〜い are
# words UniDic lists, where すご～い is none and its ～ is read から. And the 常用漢字表 (2010) allows 叱 for 𠮟 (its
# 許容字体): of the table's four such pairs that Unicode encodes apart (𠮟 叱, 塡 填, 剝 剥, 頰 頬), UniDic reads the
# other three under their word already, and drops 𠮟 — outside the Basic Multilingual Plane — as a symbol: 𠮟られた
# lost its 叱る.
_SAME_CHARACTER = {"\uff5e": "\u301c", "\U00020b9f": "\u53f1"}
_READ_AS = {}       # character -> what a tagger reads for it, where that differs ("" = nothing)
_COMBINES = set()   # characters that compose with the one before them (NFC): U+3099 in か + U+3099 = が
_READ_RE = []       # the pattern of those up to U+FFFF that `tagger_text` reads differently, made on first use
_READ_ASTRAL = set()  # and those above U+FFFF, made with it
_ASTRAL_RE = re.compile(r'[\U00010000-\U0010ffff]')


def _read_pattern():
    """The pattern of every character up to U+FFFF that `tagger_text` reads differently, and the set of those above it
    (_READ_ASTRAL) — once per process, on first use: a pass over Unicode's decompositions (about 0.07 s), so a line with
    none of them is read as written at regex speed. The ones above U+FFFF (about 6,000: invisible tags and variation
    selectors, compatibility ideographs, mathematical letters) stay out of the pattern: as about 90 more ranges in its
    class, `re` compared every character of every line with each of them in turn — measured on a 1,987-file library,
    0.92 s for the test instead of 0.13 s."""
    if not _READ_RE:
        # Only a character with a decomposition is read otherwise, and a run of characters none of which has one is
        # its own NFKD form (a decomposition always changes the text) — so each run of 4,096, then of 64, that NFKD
        # leaves as it is is passed over in C: about 23,000 characters are looked at one by one, not 1.1 million.
        for first in range(0, sys.maxunicode + 1, 4096):
            if unicodedata.is_normalized("NFKD", "".join(map(chr, range(first, first + 4096)))):
                continue
            for start in range(first, first + 4096, 64):
                if unicodedata.is_normalized("NFKD", "".join(map(chr, range(start, start + 64)))):
                    continue
                for point in range(start, start + 64):
                    ch = chr(point)
                    decomposition = unicodedata.decomposition(ch)
                    if not decomposition:
                        continue
                    parts = decomposition.split()
                    if len(parts) == 2 and not decomposition.startswith("<"):
                        _COMBINES.add(chr(int(parts[1], 16)))
                    form = unicodedata.normalize("NFKC", ch)
                    if form != ch and all(unicodedata.category(c)[0] in "LMN" for c in form):
                        _READ_AS[ch] = form
        _READ_AS.update(_SAME_CHARACTER)
        for first, last in _IGNORABLE:
            _READ_AS.update((chr(point), "") for point in range(first, last + 1))
        points, ranges = sorted({ord(ch) for ch in _READ_AS} | {ord(ch) for ch in _COMBINES}), []
        for point in points:
            if point > 0xFFFF:
                _READ_ASTRAL.add(chr(point))
            elif ranges and point == ranges[-1][1] + 1:
                ranges[-1][1] = point
            else:
                ranges.append([point, point])
        _READ_RE.append(re.compile("[" + "".join(f"\\U{a:08x}-\\U{b:08x}" for a, b in ranges) + "]"))
    return _READ_RE[0]


def _reads_differently(text):
    """Does `text` hold a character `tagger_text` reads differently? The pattern, then the set of those above U+FFFF —
    looked at only when `text` holds such a character (_read_pattern)."""
    return _read_pattern().search(text) is not None or (
        _ASTRAL_RE.search(text) is not None and not _READ_ASTRAL.isdisjoint(text))


def tagger_text(text, unread=()):
    """(read, at): `text` as every tagger reads it (§ above) and, for read[i:j], the part text[at[i]:at[j]] it was
    read from — or (text, None) when a tagger reads `text` as written, as it does most lines. A character that is
    not read rides with the one before it, so every character of `text` belongs to exactly one part; a piece that
    starts inside one character's reading (株式会社 read from ㍿ is 株式 + 会社) has an empty part after the first.
    `unread`: the indices of characters not to read at all — a stretched vowel's mark (§ A stretched vowel).

    Only the characters read otherwise are looked at one by one; the text between them is copied as it stands — a
    subtitle file is one line, and one ～ in an episode used to walk all of it a character at a time."""
    if not text or not (_reads_differently(text) or unread or _stretched(text)):
        return text, None
    groups = []                                     # [start, end, form]: the characters read as one; a run read
    last = 0                                        # as written is [start, end, its text, True]
    for i in _odd_characters(text, unread):
        if last < i:
            groups.append([last if groups else 0, i, text[last:i], True])
        last = i + 1
        form = "" if i in unread else _READ_AS.get(text[i], text[i])
        if groups and (not form or unicodedata.combining(form[0]) or form[0] in _COMBINES):
            group = groups[-1]
            if len(group) == 4:                     # a run read as written: its last character takes this one
                end = group[1]
                if len(group[2]) > 1:
                    group[1], group[2] = end - 1, group[2][:-1]
                    group = [end - 1, end, text[end - 1]]
                    groups.append(group)
                else:
                    group = groups[-1] = [group[0], end, group[2]]
            group[1], group[2] = i + 1, group[2] + form
        elif form:
            groups.append([i if groups else 0, i + 1, form])
    if last < len(text):
        groups.append([last if groups else 0, len(text), text[last:], True])
    read, at = [], []
    for group in _stretches(groups):
        start, end, form = group[0], group[1], group[2]
        if len(group) == 4:
            read.append(form)
            at.append(start)
            at.extend(range(end - len(form) + 1, end))
        else:
            form = unicodedata.normalize("NFC", form)
            read.append(form)
            at.extend([start] + [end] * (len(form) - 1))
    at.append(len(text))
    return "".join(read), at


_MARKS_RE = re.compile("[ー〜─━―—]")
_ATTACHING_RE = []  # the pattern of the combining marks up to U+FFFF, which ride with the character before them


def _odd_characters(text, unread):
    """The indices, in order, of the characters of `text` that tagger_text doesn't read one by one as themselves:
    those read in another form or composing with the one before (_read_pattern), every other combining mark (it rides
    with the character before it), the marks a stretched vowel may hold, and `unread`."""
    if not _ATTACHING_RE:
        points = [point for point in range(0x10000) if unicodedata.combining(chr(point))]
        _ATTACHING_RE.append(re.compile("[" + "".join(f"\\u{point:04x}" for point in points) + "]"))
    odd = {m.start() for m in _read_pattern().finditer(text)}
    odd.update(m.start() for m in _ATTACHING_RE[0].finditer(text))
    odd.update(m.start() for m in _MARKS_RE.finditer(text))
    if _ASTRAL_RE.search(text) is not None:
        odd.update(m.start() for m in _ASTRAL_RE.finditer(text)
                   if m.group() in _READ_ASTRAL or unicodedata.combining(m.group()))
    odd.update(unread)
    return sorted(odd)


# A stretched vowel. Inside a word — after a kana or a kanji, before a kana — a wave dash or a run of prolonged sound
# marks stands for one prolonged sound mark (長音符), as UniDic's own pronunciations read it (あま〜い is アマーイ):
# すご〜い, いらっしゃ～い and すごーーい are read すごーい and いらっしゃーい, spellings UniDic lists. Where it lists
# no stretched spelling of the word, the tagger reads the mark as a symbol of its own — ふるーい is 振る + ー + い,
# 暗ーい 暗 + ー + い — and after hiragana or a kanji the mark only lengthens the vowel before it: the word is read
# without it (ふるい, 暗い). Hiragana writes a long vowel with a vowel letter (現代仮名遣い: おかあさん), so a ー there is
# a stretch; katakana writes it with ー (外来語の表記: オットー, ゼニー), part of the word, so a mark after katakana stays.
# A dash drawn out — ─ ━ (box drawing, which web text writes for a dash), ― (the horizontal bar), — (an em dash) — is a
# stretch too, but only where it can't be the dash Japanese writes between two words far more often (それは──あなたの,
# メイド──ラム): before a ん / ン that ends the word (お母さ───ん, う────ん, ド────ン), and between katakana where the
# word goes on after a ッ, a small kana or ン, none of which begins a word (ザ─────ック, read ザーック as ザ～ック
# is). A ッ that ends the word is the catch of a shout (待て──ッ; read as a stretch, 何──ッ became 何 + つ), and a
# hiragana っ or ん that goes on starts the next word (──って, ──んだ): there the dash stays a dash.
# A katakana word stretched so (two marks or more, a wave dash, a dash run) that is no word with its one ー is read
# without it when that is a word — a headword of the lists, or one the tagger reads alone as one word it knows:
# バイバ～イ is バイバイ, スト～ップ ストップ, ジャ─────ック ジャック. One ー as written is the word's own (オットー), and a
# stretched spelling that is a word with one ー keeps it (スーーパー is スーパー).
_STRETCH_MARKS = frozenset("ー〜─━―—")
_DASHES = frozenset("─━―—")
_DASH_RUN = "[ー〜─━―—]*[─━―—][ー〜─━―—]*"
_DASH_STRETCH_RE = re.compile(
    f"(?<=[{KANA_LETTERS}{HAN}]){_DASH_RUN}(?=[んン](?![{KANA_LETTERS}]))"
    f"|(?<=[\u30a1-\u30fa\u30fd-\u30ff]){_DASH_RUN}(?=[ァィゥェォッャュョヮヵヶン][\u30a1-\u30fa\u30fd-\u30ff])")
_STRETCH_BEFORE = re.compile(f"[{KANA_LETTERS}{HAN}]")
_STRETCH_DROPPED_AFTER = re.compile(f"[\u3041-\u3096\u309d-\u309f{HAN}]")    # hiragana or a kanji
_STRETCH_DROPPED_RE = re.compile(f"[\u3041-\u3096\u309d-\u309f{HAN}]ー[{KANA_LETTERS}]")
_STRETCH_AFTER = re.compile(f"[{KANA_LETTERS}]")
_STRETCH_RE = re.compile(f"(?<=[{KANA_LETTERS}{HAN}])[ー〜]+(?=[{KANA_LETTERS}])")


def _stretched(text):
    """Does `text` hold a stretched vowel that is read otherwise than as written — a wave dash, two or more marks, or a
    dash inside a word? (A text with a ～ is read differently anyway.)"""
    return ((("〜" in text or "ーー" in text) and any(m.group() != "ー" for m in _STRETCH_RE.finditer(text)))
            or (("─" in text or "━" in text or "―" in text or "—" in text)
                and _DASH_STRETCH_RE.search(text) is not None))


def _stretches(groups):
    """tagger_text's `groups` with the marks of each stretched vowel read as one ー (§ above)."""
    out, i, n = [], 0, len(groups)
    while i < n:
        j = i
        while j < n and groups[j][2] in _STRETCH_MARKS:
            j += 1
        if i < j < n and out and _STRETCH_BEFORE.match(out[-1][2][-1]) and _inside_a_word(out[-1][2][-1], groups, i, j):
            out.append([groups[i][0], groups[j - 1][1], "ー"])
            i = j
        else:
            out.append(groups[i])
            i += 1
    return out


def _inside_a_word(before, groups, i, j):
    """Do the marks groups[i:j], after the letter `before`, stretch a vowel inside a word (§ above)? A wave dash or ー
    does before any kana; a run holding a dash only where _DASH_STRETCH_RE finds it."""
    run = "".join(group[2] for group in groups[i:j])
    if _DASHES.isdisjoint(run):
        return _STRETCH_AFTER.match(groups[j][2]) is not None
    after = "".join(group[2] for group in groups[j:j + 2])[:2]
    return _DASH_STRETCH_RE.match(before + run + after, 1) is not None


def _lone_marks(read, at, nodes):
    """The indices of the text `read` was read from (tagger_text) that hold a stretched vowel's mark the tagger read
    as a symbol of its own (§ A stretched vowel)."""
    lone, end = set(), 0
    for node in nodes:
        start = end + len(node.white_space)
        end = start + len(node.surface)
        if (node.surface == "ー" and start and end < len(read) and _STRETCH_DROPPED_AFTER.match(read[start - 1])
                and _STRETCH_AFTER.match(read[end])):
            lone.update(range(start, end) if at is None else range(at[start], at[end]))
    return lone


_KATAKANA_LETTER = re.compile("[\u30a1-\u30fa\u30fd-\u30ff]")
_KATAKANA_IN_A_WORD = re.compile("[\u30a1-\u30fa\u30fc-\u30ff]")


def _known_katakana(spelling):
    """Is `spelling` a katakana word the dictionaries know as one word — a headword of the lists, or one the tagger
    reads alone as one word it knows?"""
    listed = names.katakana_headwords()
    return (listed is not None and spelling in listed) or names._read_whole(spelling) is not None


def _katakana_stretches(text, read, at):
    """The indices of `text` holding the marks of a katakana word's stretch to read as nothing (§ A stretched vowel):
    a stretch tagger_text read as one ー — never one ー as written — between two katakana letters, in a word that is
    no word the dictionaries know with that ー and is one without it."""
    drop = set()
    for k in range(1, len(read) - 1):
        if (read[k] != "ー" or text[at[k]:at[k + 1]] == "ー" or not _KATAKANA_LETTER.match(read[k - 1])
                or not _KATAKANA_LETTER.match(read[k + 1])):
            continue
        a, b = k, k + 1
        while a and _KATAKANA_IN_A_WORD.match(read[a - 1]):
            a -= 1
        while b < len(read) and _KATAKANA_IN_A_WORD.match(read[b]):
            b += 1
        if not _known_katakana(read[a:b]) and _known_katakana(read[a:k] + read[k + 1:b]):
            drop.update(range(at[k], at[k + 1]))
    return drop


class ReadNode:
    """A tagger's node for text it read in another form (`tagger_text`): fugashi's feature, is_unk and white_space
    (the spaces before it), with the text's own spelling as its surface."""
    __slots__ = ("surface", "feature", "is_unk", "white_space")

    def __init__(self, surface, feature, is_unk, white_space=""):
        self.surface, self.feature, self.is_unk, self.white_space = surface, feature, is_unk, white_space


_FEATURES = {}          # a node's raw feature string -> fugashi's reading of it, for the entries met lately (Tagger)
_FEATURES_KEPT = 5000   # entries, about 7 MB — about 90% of a library's tokens; when full it starts again


class Tagger:
    """fugashi's tagger reading text as every caller must (`tagger_text`): `tagger(text)` -> the nodes of `text` as
    read, each keeping the text's own spelling as its surface. The one tagger the tokenizer, パターン, the sentence
    dictionary and 順 make.

    Each node is a copy (ReadNode), valid after the next call too, whose feature is shared by every node of the same
    dictionary entry: fugashi splits a node's feature string into its 26 fields anew for every token — a library's
    5 million tokens are about 60,000 entries, and that splitting was a fifth of a full re-read."""

    def __init__(self):
        import fugashi   # lazy: only a Japanese run pays this import
        self._tagger = fugashi.Tagger()

    def __call__(self, text, unread=()):
        read, at = tagger_text(text, unread)
        nodes = self._tagger(read)
        if not unread and "ー" in read:
            # a stretch UniDic lists no spelling for, or a stretched katakana word no dictionary has with its one ー
            # where it has the word without it: read the word without the stretch (§ A stretched vowel)
            lone = _lone_marks(read, at, nodes) if _STRETCH_DROPPED_RE.search(read) else set()
            if at is not None:
                lone |= _katakana_stretches(text, read, at)
            if lone:
                return self(text, lone)
        out, end = [], 0
        for node in nodes:
            raw = node.feature_raw
            feature = _FEATURES.get(raw)
            if feature is None:
                feature = node.feature
                if len(_FEATURES) >= _FEATURES_KEPT:
                    _FEATURES.clear()
                _FEATURES[raw] = feature
            if at is None:
                out.append(ReadNode(node.surface, feature, node.is_unk, node.white_space))
                continue
            start = end + len(node.white_space)
            end = start + len(node.surface)
            if node.is_unk:
                # A word the dictionary doesn't know has no lemma: every caller names it by its text — the text
                # as read (ﾀﾅｶ is the name タナカ, ５０ is 50), not the spelling kept as its surface.
                feature = feature._replace(lemma=node.surface, orth=node.surface, orthBase=node.surface)
            out.append(ReadNode(text[at[start]:at[end]], feature, node.is_unk, node.white_space))
        return out


# --- What a token counts as ------------------------------------------------------------------------ #
# UniDic's symbol classes are never words: 補助記号 (punctuation, emoji), 空白 (spaces) and 記号 — a character read
# as a character (玖 キュウ in 玖渚, 乃 ノ in 二乃, しゃ in うっしゃ, the ああ it files as 記号). The filter named
# 记号, the Chinese spelling, so a 1-in-10 sample of the library kept 913 of those as words (about 9,100 library-
# wide: アア was list row #187, イー #641, ホウ #869). One kind of 記号 is text, though: a letter spelled out by its
# name (記号,文字 — デルタ, アルファ, ガンマ線's ガンマ), a word in JMdict, which counts under that name — UniDic's
# lForm, so アルファー is アルファ — and not under the symbol UniDic makes its lemma (δ, α-alpha); a letter written
# as the symbol itself (ω in a kaomoji) is no word. Nor is a number (the user's call, 2026-09-27):
# UniDic's 数詞 — 二十, 百, 〇, Ⅲ, 50, and 何 / 数 / 幾 counting (何人, 数十) — is never a list word and never an
# unknown in a sentence (二十 was row #28, 五十 #102). Nor is a dash, though UniDic reads one as a word by context — the
# full-width hyphen-minus － as から, 対, マイナス or 引く, the wave dash 〜 as から: Unicode's dash punctuation (Pd, and
# ～, which the tagger reads as the wave dash) is punctuation — between a heading's two parts (祈り－心からの願い), in a
# range, for a minus — never a word the text says. Every caller that reads words off the tagger keys through
# `word_lemma`: the tokenizer (so the token store, the known words, 例文 and card matching) and 順's sentences.
_DASH = frozenset(chr(point) for point in range(0x10000) if unicodedata.category(chr(point)) == "Pd") | {"\uff5e"}


def word_lemma(word):
    """The lemma a tagger's node counts under (§ above), before sanitizing — or None when it is no word."""
    f = word.feature
    if f.pos1 in ("補助記号", "空白") or f.pos2 == "数詞":
        return None
    if f.pos1 == "記号":
        return f.lForm if f.pos2 == "文字" and f.lForm and has_target_language(word.surface, "ja") else None
    if word.surface in _DASH:                           # one lookup: this runs for every token
        return None
    return f.lemma or word.surface


# --- Words keep their prefixes and suffixes (Patterns_Quality_Spec.md Part A) ----------------------- #
# UniDic's short units cut 接頭辞 and 接尾辞 off a word — 新幹線 is 新 + 幹線, 可能性 可能 + 性, 日本人 日本 +
# 人 — so the list counted 幹線, 可能 and 日本, and never offered the word the content says. A run is
# joined back where the joined form is a dictionary word: a headword of JPDB 2024 or Jiten, distilled at
# build time into reference_data's affix joins together with its reading (unidic-lite reads the suffix 人
# as ニン everywhere: 日本人 would be ニッポンニン). So names (レーマン人), counts (三回目, 3年生) and odd
# pieces (お兄) never become words. `join_affixes` is the ONE place this happens: the analyzer, the
# パターン builder and its lookup, the sentence dictionary, 順 and the reference-data build all key words
# through it.

# Never joined onto a word: plural / collective suffixes (私たち, 子供たち, 先生方). An honorific joins
# only where the dictionary has the word (母さん, 皆さん, 神様, お客様 — the user, checkpoint A); never
# after a name, since a name is no base (田中さん).
# A pronoun carries the suffixes after it too — 何様, 俺様, お前さん, それなり, これっぽっち: words of their own the
# lists carry — while Settings -> "Pronouns with a suffix as one word" is on (logic.pronoun_bases, the default); off,
# they count as their parts (何 + 様). Never a plural: the table's build reads 方 by the lists' reading, so あなた方
# (アナタガタ) is never a word here, though the tagger reads its 方 カタ.
_NEVER_JOINED = frozenset(("たち", "達", "ら", "等", "ども", "共", "がた"))
# A nominalizer after a な-word stays a token of its own: 不自然さ counts toward 不自然 (the user, U2). UniDic
# files most な-words as nouns that can be one (複雑, 便利: 形状詞可能) — 複雑さ and 便利さ stay apart too, while
# 人間味 and よそみ, whose み is 味 and 見, still join. After a pronoun it is never one: これ + さ is これ and the
# particle さ.
_NOMINALIZERS = frozenset(("さ", "み"))
# UniDic files 感 as a noun, not a suffix, though it builds words the way 性 and 的 do: 違和感, 存在感,
# 緊張感, 罪悪感.
_NOUN_SUFFIXES = frozenset(("感",))
_ORTH, _SURFACE = attrgetter("feature.orth"), attrgetter("surface")   # a node's text as read, as written
# A suffix's category decides what the joined word is: 可能性 (形状詞 + 名詞的 性) is a noun, 具体的 (名詞 +
# 形状詞的 的) a な-adjective, 子供っぽい (名詞 + 形容詞的 っぽい) an adjective, 嫌がる (形状詞 + 動詞的 がる) a verb.
_SUFFIX_POS = {"名詞的": "名詞", "形状詞的": "形状詞", "形容詞的": "形容詞", "動詞的": "動詞"}


class JoinedWord:
    """A run of tokens joined into one word. Shaped like a fugashi node (`surface`, `feature`,
    `is_unk`, `white_space` — the spaces before its first piece), so every caller reads it the same way,
    plus `parts`: each piece's (surface, feature). Built from copies — a fugashi node is only valid until
    the tagger's next call."""
    __slots__ = ("surface", "feature", "parts", "is_unk", "white_space")

    def __init__(self, surface, feature, parts, white_space=""):
        self.surface, self.feature, self.parts, self.is_unk = surface, feature, parts, False
        self.white_space = white_space


_MERGED = {}   # name -> (the tables a merged table below was built from, the merged table): built once


def _merged(name, sources, build):
    """The table `build(*sources)` makes, built once while `sources` (each generated table, as its module
    hands it out) stay the same objects."""
    held = _MERGED.get(name)
    if held is None or held[0] != sources:      # the same objects: an identity test per table (this runs per line)
        held = _MERGED[name] = (sources, build(*sources))
    return held[1]


_DICTIONARY = []   # app.dictionary_data, or None where it can't be imported: looked for once per process


def _dictionary_table(name, empty):
    """app/dictionary_data.py's table `name` — the part of the tables distilled from the EDRDG dictionaries
    (CC BY-SA 4.0, kept in a module of its own) — or `empty` when the module or the table can't be read. The
    module is looked for once: a failed import searches the disk again on every call, and this runs per line."""
    if not _DICTIONARY:
        try:
            from app import dictionary_data
        except Exception:
            dictionary_data = None
        _DICTIONARY.append(dictionary_data)
    if _DICTIONARY[0] is None:
        return empty
    try:
        return getattr(_DICTIONARY[0], name)() or empty
    except Exception:
        return empty


# join_affixes asks for its tables on every line (the affix joins, the compounds, the words the tagger cuts), and the
# full lookup — the import, both modules' accessors and the merge's identity test — cost more than a short line's own
# join. So each is resolved once and held with what it was resolved from: the reference module (a test can take it
# away), its accessor (a test can swap it) and the dictionaries' module (`_DICTIONARY`, which tests swap). A change to
# any of them resolves the table again.
_RESOLVED = {}   # name -> (app.reference_data, its accessor `name`, _DICTIONARY, the table)


def _resolved(name, resolve):
    """`resolve()`'s table — reference_data's `name`, with the dictionaries' part — held while what it came from stays
    the same objects (§ above)."""
    reference = sys.modules.get("app.reference_data")
    held = _RESOLVED.get(name)
    if (held is None or held[0] is not reference or held[1] is not getattr(reference, name, None)
            or held[2] is not _DICTIONARY):
        table = resolve()
        reference = sys.modules.get("app.reference_data")       # imported by `resolve`, when it can be
        held = _RESOLVED[name] = (reference, getattr(reference, name, None), _DICTIONARY, table)
    return held[3]


def affix_joins():
    """{written form: [lemma, reading]} — the dictionary words `join_affixes` may make: reference_data's
    table, with the お / ご words the dictionary lists with a meaning of their own (お守り 'amulet', お帰り
    'welcome home' — app/dictionary_data.py) added. Degrades to {} when the generated table is absent, as
    `_spelling_alias` does: words stay in UniDic's pieces. Resolved once (`_resolved`)."""
    return _resolved("affix_joins", _affix_joins)


def _affix_joins():
    try:
        from app import reference_data
        table = getattr(reference_data, "affix_joins", dict)()
    except Exception:
        return {}
    extra = _dictionary_table("ogo_joins", {})
    if not table or not extra:
        return table
    return _merged("affix_joins", (table, extra), lambda table, extra: dict(table, **extra))


def compound_joins():
    """{written form: (lemma, reading, kind, flags)} — the dictionary compounds `join_affixes` may make
    (§ Words made of words): reference_data's table, with the dictionaries' marks OR-ed into `flags` (1: a
    phrase or a title, joined only while logic.phrases_and_titles is on — app/dictionary_data.py) in place
    (`_mark`). `kind` is "N" (nouns, places, な-words), "Q" (a numeral that counts nothing) or "V" (verb + verb).
    What each is made of is `compound_parts`, a table of its own: a process that only tokenizes never decodes it.
    Degrades to {} when the table can't be read: words then stay in UniDic's pieces. Resolved once
    (`_resolved`)."""
    return _resolved("compound_joins", _compound_joins)


def _compound_joins():
    try:
        from app import reference_data
        table = reference_data.compound_joins()
    except Exception:
        return {}
    if not table:
        return {}
    _mark(table, _dictionary_table("compound_flags", {}))
    return table


# The dictionaries' marks go into reference_data's compound table itself — one table in memory, not a copy of it
# (about 2 MB). What a mark replaced is kept, so other marks (a test's), or none, first put the table back as it was
# decoded.
_MARKED = (None, None, {})   # (the table, the marks it holds, {written form: its entry before them})


def _mark(table, flags):
    """OR `flags` ({written form: flags}) into `table`'s entries in place, once per table and marks (§ above)."""
    global _MARKED
    held_table, held_flags, was = _MARKED
    if held_table is table and held_flags is flags:
        return
    if held_table is table:
        table.update(was)
    was = {}
    for key, flag in flags.items():
        entry = table.get(key)
        if entry is not None and flag:
            was[key] = entry
            table[key] = (entry[0], entry[1], entry[2], entry[3] | flag)
    _MARKED = (table, flags, was)


def compound_parts():
    """{(lemma, reading): ((part lemma, part reading, free), …)} — what each compound word of `compound_joins`
    is made of (every kind, a phrase or a title too), keyed as a Japanese run keys the joined word — its lemma
    and reading, which the table holds as the tokenizer keys them (lemmas sanitized at build time, as every
    Japanese run sanitizes) — and each part as a run keys that part. `free`: the lists rank the part no
    rarer than the compound (a word of its own a learner meets anyway); a bound part (理 in 理不尽) is not.
    Where spellings share a word, the one spelled as its lemma speaks for it, else the first. No tagger call;
    reference_data's parts table is decoded here, the first time it is asked for. {} when either table can't
    be read."""
    table = compound_joins()
    try:
        from app import reference_data
        parts_of = reference_data.compound_parts()
    except Exception:
        return {}
    if not table or not parts_of:
        return {}

    def build(table, parts_of):
        out = {}
        for spelling, entry in table.items():
            lemma, reading = entry[0], entry[1]
            key = (lemma, reading)
            if key not in out or spelling == lemma:
                out[key] = tuple((part[0], part[1], bool(part[2])) for part in parts_of.get(spelling, ()))
        return out
    return _merged("compound_parts", (table, parts_of), build)


def _counters():
    """The spellings the lists carry as counters though UniDic files them as plain nouns or suffixes (人, 冊,
    軒 after a number) — reference_data's, as a set; empty when it can't be read."""
    try:
        from app import reference_data
        spellings = reference_data.counters()
    except Exception:
        return frozenset()
    return _merged("counters", (spellings,), frozenset)


def _is_base(word, honorific=False):
    """Can `word` carry a prefix or a suffix? A noun (never a number or a person's name — place names
    join: 日本人, アメリカ人) or a な-word; after お / ご / 御, also a verb in the 連用形 used as a noun
    (お願い, お休み, ご存じ)."""
    f = word.feature
    if word.is_unk:
        return False
    if f.pos1 == "名詞":
        return f.pos2 != "数詞" and not (f.pos2 == "固有名詞" and f.pos3 == "人名")
    if f.pos1 == "形状詞":
        return True
    return honorific and f.pos1 == "動詞" and str(f.cForm).startswith("連用形")


def _read(word):
    """A node's text as the tagger read it: UniDic's orth, which is its surface unless `tagger_text` read the text in
    another form (ｱﾒﾘｶ人 read as アメリカ人 meets the table's アメリカ人). An unknown word has no orth."""
    return word.feature.orth or word.surface


def _suffixed(words, end, key, pos1, joins):
    """-> (end, key, pos1) of the longest dictionary word that `key` (the word ending at words[end])
    grows into with the suffixes after it, each in its dictionary form (子供 + っぽく -> 子供っぽい) —
    through pieces that are no word themselves (お母 + さん -> お母さん) — or None."""
    found = (end, key, pos1) if key in joins else None
    while end + 1 < len(words):
        s = words[end + 1]
        f = s.feature
        if f.pos1 == "接尾辞":
            category, spelled = _SUFFIX_POS.get(f.pos2), f.orthBase or _read(s)
        elif f.pos1 == "名詞" and _read(s) in _NOUN_SUFFIXES:
            category, spelled = "名詞", _read(s)
        else:
            break
        if (category is None or _read(s) in _NEVER_JOINED or f.lemma in _NEVER_JOINED
                or (f.lemma == "方" and f.lForm == "ガタ")
                or (_read(s) in _NOMINALIZERS
                    and (pos1 in ("形状詞", "代名詞") or words[end].feature.pos3 == "形状詞可能"))):
            break
        key, pos1, end = key + spelled, category, end + 1
        if key in joins:
            found = (end, key, pos1)
    return found


def _joined(parts, key, pos1, entry):
    """One `JoinedWord` for the nodes `parts`: lemma and reading from the dictionary (日本人 ニホンジン,
    never the parts' ニッポン + ニン), the text's own spelling, the part of speech of the suffix — or, with
    only a prefix, of the base — and the conjugation of the last part (子供っぽく, 嫌がった)."""
    lemma, reading = entry
    snaps = tuple((w.surface, w.feature) for w in parts)
    last = snaps[-1][1]
    # A noun keeps its last part's use (真夜中 副詞可能, 再開発 サ変可能, 午前中 副詞可能); お + a verb is a
    # plain noun; only a verb or an adjective conjugates.
    pos3 = last.pos3 if pos1 == "名詞" and last.pos1 != "動詞" else "*"
    ctype, cform = (last.cType, last.cForm) if pos1 in ("動詞", "形容詞") else ("*", "*")
    surface = "".join(s for s, _ in snaps)
    read = "".join(f.orth or s for s, f in snaps)       # as the tagger read it (`_read`): the surface, mostly
    feature = last._replace(
        pos1=pos1, pos2="普通名詞" if pos1 == "名詞" else "一般", pos3=pos3 if pos3 else "*", pos4="*",
        cType=ctype, cForm=cform, lForm=reading, lemma=lemma, orth=read, orthBase=key,
        pron=reading, pronBase=reading, kana=reading, kanaBase=reading, form=reading, formBase=reading)
    return JoinedWord(surface, feature, snaps, getattr(parts[0], "white_space", ""))


def join_affixes(words, joins=None, library=True, compounds=None, cut_words=None):
    """`words` — one tagger call's nodes — with every prefix / suffix run that makes a dictionary word
    joined into one `JoinedWord` (§ above); every other node passes through untouched.

    A prefix joins the noun or な-word after it (不 + 自然, 新 + 幹線, お + 茶); a word then takes the
    suffixes that follow (可能 + 性, 日本 + 人, 子供 + っぽい), up to the longest run that `joins` has —
    the written form: prefix and base as the text writes them (as the tagger read it: `_read`), each suffix
    in its dictionary form.
    Nothing after a number is ever a base (3年生, 三回目, 第3話), nor does a prefix after one join its word:
    三大祭り is "the three great" festivals — 三 + 大 + 祭り, never 三 + 大祭り. `joins` defaults to
    reference_data's table.

    Then a run of words that spells a dictionary compound is one word (§ Words made of words: 上層部,
    一生懸命, 二十歳, 取り掛かる; `compounds` defaults to `compound_joins()`, {} joins none) — except a katakana
    compound the dictionaries don't list inside a katakana name (ビルデイング) — and a compound
    takes its own prefix and suffixes (同性愛 + 者); then two fillers cut out of one interjection are that word (ま +
    あ = まあ) and a sound said over and over that the dictionary doesn't know is its sound word (ハァハァハァ is はあはあ);
    then a sound word + と is that word shown with と (ドキッと); then a word the dictionary lists that the tagger cuts
    at its grammar is that word (§ Words the tagger cuts: くだらない, 知らせる, いつも, ちなみに; `cut_words` defaults to
    `cut_word_tables()`, ({}, {}) joins none). These depend on the text alone, so the token store caches them.

    Then a name the tagger cut into pieces is made one word (app/names.py): a katakana name no dictionary
    list spells (logic.names_katakana), and — with `library`, from the library's own tables — a katakana name
    the library keeps using (logic.names_recurring), a kanji name it holds (logic.names_kanji) and a story's own
    kanji term it keeps using as one (logic.names_work_terms). `library=False` is for what must not depend on one
    user's library: the token store's cached tokens (they record the candidates instead) and shared data."""
    if joins is None:
        joins = affix_joins()
    pos1s = [w.feature.pos1 for w in words]     # each token's part of speech, looked at once for every step
    fillers = "感動詞" in pos1s                  # a filler is an interjection (§ Sounds), and no join makes one
    # Only a line holding a prefix, a suffix or a noun that acts as one (`_NOUN_SUFFIXES`, as the tagger read it or as
    # written) can join one: most lines hold none and pass here in C.
    if joins and ("接頭辞" in pos1s or "接尾辞" in pos1s or not _NOUN_SUFFIXES.isdisjoint(map(_ORTH, words))
                  or not _NOUN_SUFFIXES.isdisjoint(map(_SURFACE, words))):
        joined = _join_affix_runs(words, joins)
        if len(joined) != len(words):           # a run was joined: the line's parts of speech are the joined words'
            words, pos1s = joined, [w.feature.pos1 for w in joined]
    if compounds is None:
        compounds = compound_joins()
    if compounds:
        at = []                                  # where each compound landed
        joined = _join_compounds(words, compounds, pos1s, at)
        if joined is not words:
            # A katakana compound the dictionaries don't list gives way to a katakana name around it (ビルデイング):
            # looked at only on lines where one landed.
            if LOGIC.get("names_katakana", True) and any(compounds[joined[k].feature.orthBase][3] & 4 for k in at):
                joined = _give_way_to_names(words, joined, at, compounds)
            # A compound takes its affixes (同性愛 + 者): Part A again, on lines where one meets a prefix or a suffix.
            if joins and any(_meets_an_affix(joined, k) for k in at):
                joined = _join_affix_runs(joined, joins)
            # Neither step makes or takes an adverb: the old list still says whether the line holds one.
            words, pos1s = joined, (None if "副詞" in pos1s else pos1s)
    if fillers or any(map(_UNKNOWN, words)):
        sounds = _sounds(words, fillers)
        if sounds is not words:
            words, pos1s = sounds, None             # a sound word may be an adverb: _join_sokuon_to looks again
    words = _join_sokuon_to(words, pos1s)
    if cut_words is None:
        cut_words = cut_word_tables()
    if cut_words[0] or cut_words[1]:
        words = _join_cut_words(words, cut_words[0], cut_words[1])
    if LOGIC.get("names_katakana", True):
        words = names.join_katakana(words)
    if library:
        words = names.join_library(words, LOGIC.get("names_recurring", True), LOGIC.get("names_kanji", True),
                                   LOGIC.get("names_work_terms", True))
    return words


def _join_affix_runs(words, joins):
    """join_affixes' prefix / suffix joins (§ above)."""
    out, i, n = [], 0, len(words)
    pronouns = LOGIC.get("pronoun_bases", True)
    while i < n:
        w = words[i]
        f = w.feature
        found = None
        if f.pos1 == "接頭辞":
            if (i + 1 < n and _is_base(words[i + 1], honorific=f.lemma == "御")
                    and not (i and words[i - 1].feature.pos2 == "数詞")):
                base = words[i + 1]
                found = _suffixed(words, i + 1, _read(w) + _read(base),
                                  "名詞" if base.feature.pos1 == "動詞" else base.feature.pos1, joins)
                # A polite お / ご gives way to a longer word its base makes with the suffixes after it:
                # お父上 is お + 父上, never お父 + 上 (お父, おとう, is a word too).
                if found and f.lemma == "御" and _is_base(base):
                    own = _suffixed(words, i + 1, _read(base), base.feature.pos1, joins)
                    if own and own[0] > found[0]:
                        found = None
        elif (i + 1 < n and (words[i + 1].feature.pos1 == "接尾辞" or _read(words[i + 1]) in _NOUN_SUFFIXES)
                and (_is_base(w) or (pronouns and f.pos1 == "代名詞" and not w.is_unk))
                and not (i and words[i - 1].feature.pos2 == "数詞")):
            found = _suffixed(words, i, _read(w), f.pos1, joins)
        if found and found[0] > i:
            end, key, pos1 = found
            out.append(_joined(words[i:end + 1], key, pos1, joins[key]))
            i = end + 1
        else:
            out.append(w)
            i += 1
    return out


# --- Words made of words: dictionary compounds ------------------------------------------------------ #
# UniDic's short units cut a compound into the words it is made of — 上層部 is 上層 + 部, 秘密結社 秘密 + 結社,
# 一生懸命 一生 + 懸命, and in a sentence 取り掛かった is 取り + 掛かっ — so the list counted 上層 and 部 and
# never offered the word the content says. A run is joined back where its spelling is a compound headword of
# JPDB 2024 or Jiten that the tagger reads as those words, distilled at build time into reference_data's
# compound table with the list's reading (株式会社 カブシキガイシャ, never the parts' カイシャ) — minus the
# spellings whose parts meet in general text no more often than chance would have them meet. Kinds:
#   N  two or three nouns — places (日本語, 鳥取県) and な-words (自信満々) among them; a な-word last makes a
#      な-word (一生懸命に). Never a number, a person's name, a word the dictionary lacks, or a grammar stem:
#      バカみたい is バカ + みたい. Also a headword the tagger reads otherwise alone that general text writes as
#      nouns (出来損ない: 出来 + 損ない in a sentence, 出来る + 損なう alone).
#      A verb's stem may stand in a noun compound JMdict lists as a noun that the text, or the word alone, writes
#      with one (the dictionaries' mark 8): 立ち[立つ] + 位置, 待ち[待つ] + 時間, a card's 出来る + 損なう. A run of
#      nouns and stems (a verb's plain 連用形, never する's) spelling it joins as the noun — anywhere when it ends
#      in a noun, but when it ends in a stem only where nothing but closing punctuation follows on the line (a
#      card, a known word, a line that is the word): in a sentence 位置づけ + て is the verb.
#   Q  a word holding a numeral that counts nothing (up to four pieces): 十人十色, 二十歳 (はたち), 精一杯.
#      Counts stay apart — 二日, 五分, 十円玉, 三年生 are no table words — and a run that starts with a
#      numeral joins only a Q word, from the first numeral of its run (三 + 十八番 is never 十八番).
#   V  a verb in its 連用形 + a verb (取り + 掛かる, 走り + 出す), keyed as the first is written and the second in
#      its dictionary form. A second verb that also follows a verbal noun + し (勉強し始める) builds by grammar,
#      not the dictionary: the table leaves those out, and 食べ始める stays two words.
# The longest run from the left wins (4, then 3, then 2 pieces); never across a space; never a plural or a
# collective (先生方 is 先生 + 方, as 子供たち is 子供 + たち); and right after a number only where that
# number counts nothing in the word — its first part is no counter (何 + 得意気 joins, 10 + 円玉 doesn't). A
# phrase or a title the dictionaries mark as one (予想通り, 元首相, もののけ姫) joins only while
# logic.phrases_and_titles is on. A compound spelled in katakana alone that the dictionaries don't list (ビルデ =
# ビル + デ: the lists' tails hold pieces of foreign names) gives way to a katakana name around it: inside a longer
# katakana run that app/names.py would make one name from the tagger's own pieces, its pieces go back and the name
# stays one word (ビルデイング, never ビルデ + イング); one they list keeps its join (フジテレビ + アナウンサー). A compound
# keeps its parts: a known compound marks them known, and パターン counts them in context.
_FIRST_POS1 = frozenset(("名詞", "形状詞", "動詞"))            # what a compound can start with (a number is a 名詞)
_LATER_POS1 = frozenset(("名詞", "形状詞", "動詞", "接尾辞"))   # ...and go on with (a numeral word's 歳, 日)
_NA_WORD_CLASSES = frozenset(("一般", "タリ"))                   # a な-word proper — never 助動詞語幹 (みたい, そう)
_COUNTER_CLASSES = frozenset(("助数詞", "助数詞可能"))            # UniDic's own counters (日, 円, 階, 歳)
# A plural or collective suffix, and how the lists read it when it is one: 先生方 is センセイガタ (the tagger
# reads its 方 as ホウ), while 相手方 アイテカタ is a word and 上等 ジョウトウ no plural.
_PLURAL_READINGS = {"たち": ("タチ", "ダチ"), "達": ("タチ", "ダチ"), "ら": ("ラ",), "等": ("ラ",),
                    "ども": ("ドモ",), "共": ("ドモ",), "がた": ("ガタ",), "方": ("ガタ",)}


def _compound_part(word, kind="N"):
    """Can `word` be a part of a dictionary compound of `kind` (§ above)? Never a word the dictionary lacks.
    N: a noun that can carry an affix (`_is_base` — no number, no person's name; a place can: 日本 + 語) or a
    な-word proper (懸命, 満々 — never a grammar stem: みたい, そう). A word joined with its affixes is a part like
    any noun (お味噌 + 汁). Q: also a number or a noun suffix (二十 + 歳, 十 + 人 + 十 + 色). V: a verb other
    than する."""
    if word.is_unk:
        return False
    f = word.feature
    if kind == "V":
        return f.pos1 == "動詞" and f.lemma != "為る"
    if kind == "Q" and (f.pos2 == "数詞" or (f.pos1 == "接尾辞" and f.pos2 == "名詞的")):
        return True
    if f.pos1 == "形状詞":
        return f.pos2 in _NA_WORD_CLASSES
    return f.pos1 == "名詞" and _is_base(word)


def _counter(word):
    """Is `word` a counter — one UniDic files as one (日, 円, 階), or one the lists carry after many numbers
    (人, 冊, 軒)? Right after a number, a compound starting with one is a count, never a word (10 + 円玉)."""
    return word.feature.pos3 in _COUNTER_CLASSES or _read(word) in _counters()


def _plural(last, reading):
    """Does a compound whose last part is written `last` and read `reading` by the lists end in a plural or
    collective suffix (§ above)?"""
    return reading.endswith(_PLURAL_READINGS.get(last, ()))


def _joins_here(words, i, run, entry, fringe):
    """May `run` (words[i:i + len(run)], nouns, a numeral or suffixes) be joined as the table's `entry` — its
    kind, its parts and the guards (§ above)?"""
    kind, numbers = entry[2], [w.feature.pos2 == "数詞" for w in run]
    if kind == "V" or (len(run) > 3 and kind != "Q") or (entry[3] & 1 and not fringe):
        return False
    after_number = i and words[i - 1].feature.pos2 == "数詞"
    if numbers[0]:
        if kind != "Q" or after_number:
            return False
    elif after_number and _counter(run[0]):
        return False
    if any(numbers):
        if numbers[-1]:
            return False                        # never ending in a bare number
        test = "Q"                              # a numeral inside the word counts nothing in it (精 + 一 + 杯)
    else:
        test = "Q" if kind == "Q" else "N"
    return all(_compound_part(w, test) for w in run) and not _plural(_read(run[-1]), entry[1])


_STEMS = 8                      # the dictionaries' mark: a verb's stem may stand in this noun compound (§ above)
_CLOSING = frozenset("。．.！？!?」』）)】〕…‥―ー～〜")   # what may follow a stem that ends the line's word


def _stem(word):
    """A verb's stem as a noun is written (出来, 損ない, 待ち): its 連用形 in the plain form — never する's, never a sound
    change (損なっ comes only before た / て)."""
    f = word.feature
    return f.pos1 == "動詞" and not word.is_unk and f.lemma != "為る" and str(f.cForm) == "連用形-一般"


def _joins_with_stems(words, i, run, entry, fringe):
    """May `run` (words[i:i + len(run)]), nouns and at least one verb's stem, be joined as the noun compound `entry`
    — one a verb's stem may stand in (the mark 8, § above)? A run ending in a noun joins anywhere (待ち + 時間); one
    ending in a stem only when nothing but closing punctuation follows it on the line — a card, a known word, a line
    that is the word (出来る + 損なう) — never in a sentence, where 位置づけ + て is the verb. The guards of any compound
    hold: never after a number that counts its first part, never a plural."""
    if (entry[2] != "N" or not entry[3] & _STEMS or (entry[3] & 1 and not fringe) or len(run) > 3
            or not any(_stem(w) for w in run) or not all(_stem(w) or _compound_part(w, "N") for w in run)):
        return False
    if i and words[i - 1].feature.pos2 == "数詞" and _counter(run[0]):
        return False
    if _plural(_read(run[-1]), entry[1]):
        return False
    return not _stem(run[-1]) or all(w.feature.pos1 in ("補助記号", "空白") and _CLOSING.issuperset(w.surface)
                                     for w in words[i + len(run):])


_HEADS = (None, frozenset())   # (a compound table, `_heads` of it): made once per table


def _heads(table):
    """Every spelling a word of `table` starts with, short of the whole (上, 上層 for 上層部), held as its hash: a
    run whose text so far hashes to none of them can grow into no table word, so most runs are given up after one
    lookup. Hashes, not the spellings: a third less memory, and a hash two spellings share only lets a run be read
    further — the table itself says what is a word — so the joins are the same. Made once per table, held while it
    is the same object (this runs per line)."""
    global _HEADS
    if _HEADS[0] is not table:
        _HEADS = (table, frozenset(hash(key[:end]) for key in table for end in range(1, len(key))))
    return _HEADS[1]


def _compound_at(words, i, table, heads, fringe):
    """-> (end, key, pos1, entry): the longest dictionary compound starting at words[i] (§ above), or None."""
    first = words[i]
    f = first.feature
    if f.pos1 == "動詞":
        second = words[i + 1]
        g = second.feature
        if g.pos1 == "動詞" and not getattr(second, "white_space", "") and str(f.cForm).startswith("連用形"):
            key = _read(first) + (g.orthBase or _read(second))
            entry = table.get(key)
            if (entry is not None and entry[2] == "V" and not (entry[3] & 1 and not fringe)
                    and _compound_part(first, "V") and _compound_part(second, "V")):
                return i + 1, key, "動詞", entry
        if not _stem(first):
            return None                         # a verb starts no other compound, save as a noun's stem (待ち + 時間)
    key = _read(first)
    if hash(key) not in heads:
        return None
    found = []                                  # (end, key, entry): the table's words from here, shortest first
    for j in range(i + 1, min(len(words), i + 4)):
        w = words[j]
        if w.feature.pos1 not in _LATER_POS1 or getattr(w, "white_space", ""):
            break
        key += _read(w)
        entry = table.get(key)
        if entry is not None:
            found.append((j, key, entry))
        if hash(key) not in heads:
            break
    for end, key, entry in reversed(found):
        run = words[i:end + 1]
        if f.pos1 != "動詞" and _joins_here(words, i, run, entry, fringe):
            return end, key, "形状詞" if words[end].feature.pos1 == "形状詞" else "名詞", entry
        if _joins_with_stems(words, i, run, entry, fringe):
            return end, key, "名詞", entry
    return None


def _meets_an_affix(words, k):
    """Can Part A join more at the compound words[k] — a prefix before it, a suffix after it? Only then is it run
    over the line again: one long subtitle line holding a compound cost a whole second pass."""
    return ((k and words[k - 1].feature.pos1 == "接頭辞")
            or (k + 1 < len(words) and (words[k + 1].feature.pos1 == "接尾辞" or _read(words[k + 1]) in _NOUN_SUFFIXES)))


def _join_compounds(words, table, pos1s=None, at=None):
    """join_affixes' compound joins (§ above): `words` with every compound the table spells joined into one
    word — the same list when none is. `pos1s`: each token's part of speech, when the caller has them; `at`, a
    list, receives where each compound landed. Only a token of a compound's parts of speech followed by another
    is looked at more closely, and most of those are given up after one lookup (`_heads`): the common path
    stays in C."""
    if pos1s is None:
        pos1s = [w.feature.pos1 for w in words]
    first, later = _FIRST_POS1, _LATER_POS1
    starts = [i for i in range(len(pos1s) - 1) if pos1s[i] in first and pos1s[i + 1] in later]
    if not starts:
        return words
    heads, fringe = _heads(table), LOGIC.get("phrases_and_titles", True)
    out, last = None, 0
    for i in starts:
        if i < last:
            continue
        w = words[i]
        if pos1s[i] != "動詞" and hash(w.feature.orth or w.surface) not in heads:
            continue                            # no table word starts so (`_compound_at`'s first test, `_read`)
        found = _compound_at(words, i, table, heads, fringe)
        if found is None:
            continue
        end, key, pos1, entry = found
        if out is None:
            out = []
        out.extend(words[last:i])
        if at is not None:
            at.append(len(out))
        out.append(_joined(words[i:end + 1], key, pos1, (entry[0], entry[1])))
        last = end + 1
    if out is None:
        return words
    out.extend(words[last:])
    return out


def _give_way_to_names(words, joined, at, table):
    """join_affixes' give-way (§ above): `joined` — `words` with the compounds joined, each landed at `at` — with
    every katakana compound the dictionaries don't list (flag 4) that sits inside a longer katakana run the
    katakana-name rule (app/names.py) would make one name from `words` put back in its pieces; that rule then makes
    the run one word. `at` is updated to where the compounds kept landed; `words` itself comes back when every
    compound gave way."""
    listed = names.katakana_headwords()
    if not listed:
        return joined
    runs = [(a, b) for a, b in names.katakana_runs(words) if names.katakana_kind(words[a:b], listed) == "name"]
    if not runs:
        return joined
    out, kept, landed, i = [], [], set(at), 0
    for k, word in enumerate(joined):
        n = len(word.parts) if k in landed else 1
        if (k in landed and table[word.feature.orthBase][3] & 4
                and any(a <= i and i + n <= b and b - a > n for a, b in runs)):
            out.extend(words[i:i + n])          # the name around it wins: the pieces go back
        else:
            if k in landed:
                kept.append(len(out))
            out.append(word)
        i += n
    if len(out) == len(joined):
        return joined
    at[:] = kept
    return words if not kept else out


# --- Sounds the tagger cut or left unknown ------------------------------------------------------------------------ #
# Two fillers cut out of one interjection: in speech without punctuation the tagger may prefer a chain of one-kana
# fillers — ま + あ for まあ, read まー + あー, or あ + あ～ for ああ～ — to the word it lists, and it reads the pair alone
# as that word. Two fillers in a row, each one kana (a stretch mark aside), are the interjection or adverb the pair
# reads as alone: まあ, ああ, いえ, ええ, うん. Only where the pair reads alone as ONE such word: ま + え (したまえ) and
# う + え (うえ～ん) stay as they are, as do two whole interjections (あー + あー, each ああ).
# A sound said over and over: the dictionary lists a sound word said twice (はあはあ, ふふ, だらだら), and the tagger
# leaves the same sound said three times or more as a katakana word it doesn't know (ハァハァハァ, ﾌﾌﾌﾌﾌ), counted as an
# unknown word of its own. Such a word is the sound word the tagger reads that sound said twice as, alone, when it is
# one — an interjection or an adverb — shown as written: ハァハァハァ is はあはあ's. A sound whose double is no such word
# stays as it was (ヘヘヘ: ヘヘ reads as two words; ゼロゼロゼロ).
_UNKNOWN, _POS2 = attrgetter("is_unk"), attrgetter("feature.pos2")
_ONE_KANA = re.compile(f"^[{KANA_LETTERS}][ー〜]*$")      # UniDic spells some fillers with 〜 (え〜)
_KATAKANA_WORD = re.compile("^[\u30a1-\u30fa\u30fc-\u30ff]+$")
_SOUND_POS1 = frozenset(("感動詞", "副詞"))
_FILLER_MARKS = re.compile("[ー〜]")


def _sound_word(spelling):
    """The tagger's feature for `spelling` read alone, when it reads it as ONE interjection or adverb it knows — else
    None (asked once per spelling: app/names.py keeps the answers)."""
    whole = names._read_whole(spelling)
    return whole if whole is not None and whole.pos1 in _SOUND_POS1 else None


def _repeated_unit(text):
    """The sound a katakana word says three times or more, less a final ッ or ー (ハァ in ハァハァハァ, フ in フフフフッ) —
    else None."""
    if not _KATAKANA_WORD.match(text):
        return None
    spelling = text.rstrip("ッー")
    n = len(spelling)
    for k in range(1, n // 3 + 1):
        if n % k == 0 and spelling == spelling[:k] * (n // k):
            return spelling[:k]
    return None


def _sounds(words, fillers):
    """join_affixes' sounds (§ above): `words` with each unknown sound said three times or more read as its sound word
    and — on a line holding an interjection (`fillers`) — each pair of fillers that reads alone as one word joined into
    it; the same list when there is none. Only the unknown words and the fillers are looked at, each found in C."""
    n, found = len(words), {}           # where a sound word goes -> (the word, how many tokens it takes the place of)
    for i in compress(range(n), map(_UNKNOWN, words)):
        unit = _repeated_unit(_read(words[i]))
        whole = _sound_word(unit * 2) if unit else None
        if whole is not None:
            found[i] = (ReadNode(words[i].surface, whole, False, getattr(words[i], "white_space", "")), 1)
    if fillers:
        free = 0                        # the first token no pair has taken yet
        for i in compress(range(n - 1), map(eq, map(_POS2, words), repeat("フィラー"))):
            w, v = words[i], words[i + 1]
            if (i >= free and v.feature.pos2 == "フィラー" and not getattr(v, "white_space", "")
                    and _ONE_KANA.match(_read(w)) and _ONE_KANA.match(_read(v))):
                spelling = _read(w) + _read(v)
                whole = _sound_word(spelling) or _sound_word(_FILLER_MARKS.sub("", spelling))
                if whole is not None:
                    parts = ((w.surface, w.feature), (v.surface, v.feature))
                    found[i] = (JoinedWord(w.surface + v.surface, whole, parts, getattr(w, "white_space", "")), 2)
                    free = i + 2
    if not found:
        return words
    out, last = [], 0
    for i in sorted(found):
        word, width = found[i]
        out.extend(words[last:i])
        out.append(word)
        last = i + width
    out.extend(words[last:])
    return out


# A sound word ending in っ / ッ said with と — ドキッと, ざっと, ぎゅっと. UniDic files the sound word as an
# adverb and cuts the と off as a particle, so the list counted ドキッ and a card mined as ドキッと reached its
# row only by dropping the ending. The adverb and its と are one token: the same word shown with と — UniDic's
# lemma and reading kept (どき / ドキ), so it counts on the adverb's own row, shown ドキッと where the text
# writes it so, and a known ぐっ makes ぐっと known. Only a kana adverb ending in っ directly followed by the case
# particle と: 「バシッ」と, バシッ！と and 行っとく stay as they are; ポンと and くるりと, whose と is optional,
# too.
_SOKUON_ADVERB = plan_rules._SOKUON_ADVERB      # one pattern: _display_orth reads a sound word's と by it too


def _join_sokuon_to(words, pos1s=None):
    """join_affixes' sound word + と (§ above): the same list when there is none. `pos1s`: each token's part of
    speech, when the caller has them — most lines hold no adverb, and that test stays in C."""
    if pos1s is None:
        pos1s = [w.feature.pos1 for w in words]
    if "副詞" not in pos1s:
        return words
    out, last, n = None, 0, len(words)
    for i in [i for i, pos1 in enumerate(pos1s) if pos1 == "副詞"]:
        if i < last or i + 1 >= n:
            continue
        w, following = words[i], words[i + 1]
        f = w.feature
        if (_read(following) != "と" or following.feature.pos2 != "格助詞"
                or not _SOKUON_ADVERB.match(_read(w))):
            continue
        if out is None:
            out = []
        out.extend(words[last:i])
        out.append(_joined(words[i:i + 2], (f.orthBase or _read(w)) + "と", "副詞",
                           (f.lemma or w.surface, f.lForm or f.kana or "")))
        last = i + 2
    if out is None:
        return words
    out.extend(words[last:])
    return out


# --- Words the tagger cuts at their grammar: the dictionary's words -------------------------------------------- #
# UniDic's short units read some words as a word + its grammar: くだらない 'trivial' is 下る 'descend' + the negative
# ない, つまらない 'boring' 詰まる 'be packed' + ない, 思わず 'involuntarily' 思う + ず, 知らせる 'inform' 知る + the
# causative せる — so the list counted another verb for each use; いつも 'always' is いつ 'when' + も, ちなみに 'by the
# way' 因み + に, どうにか 'somehow' どう + に + か, and a clause's opening でも 'but' two particles. JMdict lists each as
# a word of its own, and such a run is that word (app/dictionary_data.py, built by scripts/build_reference_data.py):
#   A verb + its negative or causative (ない; ず, ぬ, ん; せる, させる) — never only tense, politeness or aspect
#     (変わった, すみません), never after a light verb (される is する's passive) — where JMdict's editors list the whole
#     as a word: a priority tag of a curated list (ichi, spec). 変わらない 'constant', marked only as frequent in the
#     news, is 変わる's negative in nearly every use; 知らない and 足りない carry no tag. A word JMdict says is usually
#     written in kana counts only as written in kana: すまない 'sorry', never 済まない (済む's negative: では済まない).
#     Keyed by its dictionary form when it conjugates (くだら + なかっ is くだらない's past: くだらなかっ + た), else as
#     written (思わず, 絶えず).
#   A word + particles JMdict lists as an adverb or a conjunction (never only as an expression: those stay pieces, and
#     the phrase rows carry them) — a curated word that JPDB 2024 and Jiten each rank about as often as general text
#     holds the run — whose first word is a closed-class word: particles opening a clause (でも; never after a word, a
#     closing bracket or a quote: 『題』でも is the title + で + も), a pronoun (いつも, それとも), an adverb with more
#     than an optional と / に after it (どうにか; すぐに is すぐ's) — or a noun the lists rank rarer alone than the
#     whole (因み in ちなみに; 本当に stays 本当 + に). A run inside a longer dictionary spelling is that spelling's
#     pieces (か + どう + か is かどうか, それに + し + て + も それにしても).
# The longest match from the left wins. Each is a word of its own: it counts as itself, never as known through its
# parts (knowing それ, と and も is no knowing それとも).
_CUT_CONTENT = frozenset(("名詞", "代名詞", "副詞", "形状詞", "連体詞", "接続詞", "感動詞"))
_CLOSERS = frozenset("」』）)】〕〉》］]｝}’”〟")      # a closing bracket or quote: a quoted name takes a particle
_CUT_HEADS = (None, None, frozenset(), frozenset(), frozenset())   # (aux, particles, their first words, either)


def cut_word_tables():
    """(verb + auxiliary words, word + particle words): app/dictionary_data.py's tables (§ above) — {key: [lemma,
    reading, pos1, first word as read, …]} — resolved once; ({}, {}) when the module or a table can't be read: such
    words stay in UniDic's pieces."""
    return _resolved("cut_word_tables", _cut_word_tables)


def _cut_word_tables():
    return _dictionary_table("aux_words", {}), _dictionary_table("particle_words", {})


def _cut_heads(aux, particles):
    """The first words, as read, of `aux`'s and `particles`' words, and both together — made once per tables: a line
    holding none of them holds no such word, and that test runs in C."""
    global _CUT_HEADS
    if _CUT_HEADS[0] is not aux or _CUT_HEADS[1] is not particles:
        a, p = frozenset(e[3] for e in aux.values()), frozenset(e[3] for e in particles.values())
        _CUT_HEADS = (aux, particles, a, p, a | p)
    return _CUT_HEADS[2:]


def _clause_start(words, i):
    """Nothing before words[i] on the line but punctuation that opens or separates: a case particle needs a word
    before it, so particles there open a clause (え、でも). Never after a closing bracket or quote (『題』でも)."""
    if not i:
        return True
    before = words[i - 1]
    return before.feature.pos1 in ("補助記号", "空白") and not (before.surface and before.surface[-1] in _CLOSERS)


def _aux_word(words, i, aux):
    """(end, key) of the longest verb + auxiliaries at words[i] that `aux` holds — keyed by its dictionary form (the
    last auxiliary's) when it conjugates, else as written — or None."""
    w = words[i]
    if w.is_unk or w.feature.pos1 != "動詞":
        return None
    j, n = i + 1, len(words)
    while j < n and words[j].feature.pos1 == "助動詞" and not getattr(words[j], "white_space", ""):
        j += 1
    for end in range(j, i + 1, -1):
        written, last = "".join(map(_read, words[i:end - 1])), words[end - 1]
        key = written + _read(last)
        entry = aux.get(key)
        if entry is not None and not entry[4]:
            return end, key
        key = written + (last.feature.orthBase or _read(last))
        entry = aux.get(key)
        if entry is not None and entry[4]:
            return end, key
    return None


def _blocked(words, i, end, longer):
    """Does one of `longer` (longer dictionary spellings) hold words[i:end] here — on the tokens' bounds, reaching
    before it or after it?"""
    n = len(words)
    for a in range(max(0, i - 3), i + 1):
        for b in range(end, min(n, end + 4) + 1):
            if (a < i or b > end) and "".join(map(_read, words[a:b])) in longer:
                return True
    return False


def _particle_word(words, i, particles):
    """(end, key) of the longest word + particles (or particles opening a clause) at words[i] that `particles`
    holds, unless a longer dictionary spelling holds it here — or None."""
    w = words[i]
    first = w.feature.pos1
    if w.is_unk or not (first in _CUT_CONTENT or (first == "助詞" and _clause_start(words, i))):
        return None
    j, n = i + 1, len(words)
    while j < n and j - i <= 3 and words[j].feature.pos1 == "助詞" and not getattr(words[j], "white_space", ""):
        j += 1
    for end in range(j, i + 1, -1):
        key = "".join(map(_read, words[i:end]))
        entry = particles.get(key)
        if entry is not None:
            if bool(entry[4]) != (first == "助詞") or (entry[5] and _blocked(words, i, end, entry[5])):
                return None
            return end, key
    return None


def _join_cut_words(words, aux, particles):
    """join_affixes' words the tagger cuts at their grammar (§ above): `words` with each joined into one word — the
    same list when there is none. Only a token whose text heads such a word is looked at, found in C."""
    heads_aux, heads_particles, heads = _cut_heads(aux, particles)
    hits = list(compress(range(len(words) - 1), map(heads.__contains__, map(_ORTH, words))))
    if not hits:
        return words
    out, last = None, 0
    for i in hits:
        if i < last:
            continue
        head, found, table = _ORTH(words[i]), None, None
        if head in heads_aux:
            found, table = _aux_word(words, i, aux), aux
        if found is None and head in heads_particles:
            found, table = _particle_word(words, i, particles), particles
        if found is None:
            continue
        end, key = found
        entry = table[key]
        word = _joined(words[i:end], key, entry[2], (entry[0], entry[1]))
        if entry[2] == "形容詞":
            word.feature = word.feature._replace(cType="形容詞")    # ない conjugates as an adjective does
        if out is None:
            out = []
        out.extend(words[last:i])
        out.append(word)
        last = end
    if out is None:
        return words
    out.extend(words[last:])
    return out


def see_through_base(lemma, reading, tagger, joins=None):
    """(lemma, reading) of the word inside a word + suffixes that make a noun — 利用 in 利用者, 可能 in 可能性,
    母 in 母さん, and 茶 in お茶: the polite お / ご the one prefix read through — else None. Never another prefix word
    (不自然: the prefix changes the meaning) and never a suffix that makes another kind of word (具体的, 子供っぽい).
    For U9 (Patterns_Quality_Spec.md §6.8): when the learner knows that word, the joined one stays on the list,
    lower, and is no unknown when choosing example sentences."""
    if joins is None:
        joins = affix_joins()
    entry = joins.get(lemma)
    if not entry or tuple(entry) != (lemma, reading):
        return None
    words = join_affixes(tagger(lemma), joins)
    if len(words) != 1 or not isinstance(words[0], JoinedWord) or words[0].feature.pos1 != "名詞":
        return None
    surface, base = words[0].parts[0]
    if base.pos1 == "接頭辞":
        # The polite お / ご is the one prefix read through: it adds politeness, not meaning — お茶 is 茶, ご苦労 苦労.
        if (base.lemma, base.lForm) not in (("御", "オ"), ("御", "ゴ")) or len(words[0].parts) < 2:
            return None
        surface, base = words[0].parts[1]
        if base.pos1 == "接頭辞":
            return None
    base_lemma = base.lemma or surface
    return (_sanitize_term(base_lemma) if SANITIZE_JA else base_lemma), base.lForm or base.kana or ""


# --- What there is to learn in a word: one rule for the list, the Rarity slider, 例文 and 順 ------------- #
# A compound is one word (上層部, 秘密結社, トランスジェンダー), and each of its parts is known to be a word of its own
# or not ("free": JPDB 2024 or Jiten meets it alone at least as often as it meets the compound; 千載 and 一遇 are
# not). Two things follow for what a learner meets:
#   * A compound none of whose parts is an unknown — each known, ignored, read through its known word (利用者), or
#     itself such a compound — is read already: it stays a list word with its own card (上層部 with 上層 and 部 known),
#     sits lower (half score, as a word read through its known word does) and is no unknown in a sentence.
#   * A compound too rare for the list (under its cut-off), which the learner neither knows nor ignores, counts
#     toward its free parts: each use is a use of 撤回 in 前言撤回 though 前言 is bound. In a sentence it is its
#     parts when all of them are free (トランスジェンダー: two words to learn), and one word when one is bound
#     (千載一遇). A rare part is taken apart in turn (経済成長期 -> 経済成長 + 期 -> 経済 + 成長 + 期).
# Which compounds are rare is fixed once, from the uses the list was cut on, before anything is credited — so a
# word never flips across the cut-off because of what its compounds gave it. A sentence is still an example only
# for the words that stand in it on their own, and a word is never taken apart against itself (a card for a rare
# compound keeps its own sentences). The run (analyzer.main), the Rarity slider (token_index / word_selection),
# the sentence dictionary and 例文 (sentence_corpus) and 順 (modules/junban) all read words through LearningView.

def library_counts(path, language=None):
    """({(lemma, reading): uses}, the list's cut-off) as the last run wrote them to library_frequency.json — every
    word the learner didn't know then, the list's and the rarer ones — or (None, None) when there is none yet, or
    when it is another language's (results/ holds one language's run at a time)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        settings = data.get("settings") or {}
        if language and settings.get("language", language) != language:
            return None, None
        floor = settings.get("min_count")
        words = data.get("words") or {}
        if not isinstance(floor, (int, float)) or isinstance(floor, bool) or not isinstance(words, dict):
            return None, None
        counts = {}
        for key, entry in words.items():
            lemma, _sep, reading = key.partition("|")
            counts[(lemma, reading)] = entry[0] if isinstance(entry, list) and entry else 0
        return counts, floor
    except (OSError, ValueError, AttributeError, TypeError):
        return None, None


class LearningView:
    """How the words of a sentence count for learning (§ above). `known(key)`: the learner knows or ignores the word
    (key = (lemma, reading)), by the caller's own lists. `counts` ({key: uses}) and `floor` are what the list was
    cut on — without them no compound is rare (before the first Generate): each word is itself. `parts` defaults to
    the tokenizer's table; `tagger` is made when a word is first read through its known word."""

    def __init__(self, counts=None, floor=0, known=None, parts=None, joins=None, tagger=None):
        self.parts = compound_parts() if parts is None else parts
        self.joins = affix_joins() if joins is None else joins
        self._counts, self._floor, self._known = counts, floor, known or (lambda key: False)
        self._tagger = tagger
        self._rare, self._units, self._credits, self._bases, self._cycles = {}, {}, {}, {}, {}

    def _on_cycle(self, key):
        """Do `key`'s parts lead back to it — a table entry holding itself (教える = 教える + 得る), or two holding each
        other? Such an entry is taken as one word: one unit, no credit, never read through its parts. Every other
        entry is taken apart as it always is, and no key is ever followed round again: one that would be is on a
        cycle, and stops there."""
        found = self._cycles.get(key)
        if found is None:
            found, seen, todo = False, set(), [key]
            while todo and not found:
                for lemma, reading, _free in self.parts.get(todo.pop(), ()):
                    part = (lemma, reading)
                    if part == key:
                        found = True
                        break
                    if part not in seen and part in self.parts:
                        seen.add(part)
                        todo.append(part)
            self._cycles[key] = found
        return found

    def rare(self, key):
        """Is `key` a compound under the list's cut-off that the learner neither knows nor ignores?"""
        found = self._rare.get(key)
        if found is None:
            found = self._rare[key] = (self._counts is not None and key in self.parts
                                       and self._counts.get(key, 0) < self._floor and not self._known(key))
        return found

    def units(self, key, keep=None):
        """The words one use of `key` is in a sentence: a rare compound whose parts are all free is its parts (a rare
        part taken apart in turn); any other word is itself. `keep` is never taken apart: the word a sentence is
        ranked for is never counted as its own parts against it."""
        if keep is not None:
            if (key == keep or not self.rare(key) or not all(free for _l, _r, free in self.parts[key])
                    or self._on_cycle(key)):
                return (key,)
            return tuple(unit for lemma, reading, _free in self.parts[key] for unit in self.units((lemma, reading), keep))
        found = self._units.get(key)
        if found is None:
            found = (key,)
            if self.rare(key) and all(free for _l, _r, free in self.parts[key]) and not self._on_cycle(key):
                found = tuple(unit for lemma, reading, _free in self.parts[key]
                              for unit in self.units((lemma, reading)))
            self._units[key] = found
        return found

    def credits(self, key):
        """The words one use of `key` also counts for on the list: a rare compound's free parts (a rare part's own
        free parts in turn); nothing for any other word."""
        found = self._credits.get(key)
        if found is None:
            found = ()
            if self.rare(key) and not self._on_cycle(key):
                found = tuple(credit for lemma, reading, free in self.parts[key] if free
                              for credit in (self.credits((lemma, reading)) if self.rare((lemma, reading))
                                             else ((lemma, reading),)))
            self._credits[key] = found
        return found

    def readable(self, key, known=None):
        """Is `key` no unknown though the learner doesn't know it — a word read through its known word (利用者 with
        利用 known: see_through_base), or a compound none of whose parts is an unknown? `known` defaults to the
        view's own; the report passes the words learned so far down the list."""
        if key[0] not in self.joins and key not in self.parts:
            return False                # neither kind of word: most of them, decided here
        known = known or self._known
        base = self._bases.get(key, False)
        if base is False:
            base = None
            if key[0] in self.joins:
                if self._tagger is None:
                    self._tagger = Tagger()
                base = see_through_base(key[0], key[1], self._tagger, self.joins)
            self._bases[key] = base
        if base is not None and known(base):
            return True
        parts = self.parts.get(key)
        return bool(parts) and not self._on_cycle(key) and all(
            known((lemma, reading)) or self.readable((lemma, reading), known) for lemma, reading, _free in parts)


# --- One-character words: the ones the list can offer ------------------------------------------------------------ #
# About half of what a Japanese text says is words UniDic files under a one-character lemma, and most of those uses
# are grammar (の, は, た, て). With Settings -> "List one-kanji words only when they're dictionary words" on
# (exclude_single, the default), a one-character word is a list word only when the language says it is a word: a
# one-kanji word general text uses as a word of its own that JMdict lists, and that JMdict or both frequency lists call
# common — 手, 目, 顔, 私, and こと 事, もの 物, ため 為, しばしば 屡 written in kana (app/one_kanji_data.py, built by
# scripts/build_one_kanji_data.py from the language, never from a library). Each reading is its own word: (時, とき) is
# one, 中 read ちゅう and 様 read さま are suffixes and never are. And it counts only where it stands on its own
# (`bound_uses`): glued to another one-kanji piece (斬 + 魄 + 刀, 狛 + 村) or right after a number (三 + 年), a use is a
# piece of something else — not a use of the word, not an example of it, not an unknown in its sentence.
# A one-character word the list can never offer — grammar, a name the tagger reads as a common noun (スバル as 昴), a
# rare kanji (簪), a piece of a term — never keeps a sentence from i+1 either, and counts as nothing to learn in a
# file's coverage: the list, the report's examples, the progressive list, 例文, the sentence dictionary, 順 and the
# YouTube preview all count exactly what the list can offer (`single_kind`, `unoffered`). The report names those words
# per file ("Also in this file, not on your list", `not_on_list`) so a learner can still make a card for one.
# Off, every one-character word is listed and every use counts, as it always was. Chinese keeps every word: most of
# its common words are one character.

_ONE_KANJI = []         # [(words, their lemmas, pieces)] once read: app/one_kanji_data.py; empty sets when unreadable
UNLISTED_SHOWN = 12     # the one-kanji words a file names as "not on your list" (file_statistics.json), most used first


def _one_kanji():
    """(the one-kanji words the list can offer, their lemmas, the one-kanji words general text uses as grammar) —
    {(lemma, reading)}, {lemma}, {(lemma, reading)}; empty when the table can't be read."""
    if not _ONE_KANJI:
        try:
            from app import one_kanji_data
            words, pieces = one_kanji_data.words(), one_kanji_data.pieces()
        except Exception:
            words, pieces = frozenset(), frozenset()
        _ONE_KANJI.append((words, frozenset(lemma for lemma, _reading in words), pieces))
    return _ONE_KANJI[0]


def single_kind(key, rule=True):
    """How the list treats `key` (lemma, reading): 0 — any word (two characters or more, or `rule` off: Settings'
    "List one-kanji words only when they're dictionary words", whose off lists every one-character word; Chinese
    callers pass False); 1 — a one-character word the list can never offer; 2 — a one-kanji word it offers where it
    stands on its own (`bound_uses`)."""
    if not rule or len(key[0]) != 1:
        return 0
    return 2 if key in _one_kanji()[0] else 1


def not_on_list(key):
    """Does the report name `key` per file as "also in this file, not on your list" (the rule on)? A one-kanji word
    none of whose readings the list can offer, that general text never uses as grammar (a prefix, a suffix, a particle,
    an auxiliary — never お, たち, 様 さま): a name the tagger reads as a common noun (スバル, 昴), a rare word (簪), a
    term's piece standing on its own. A word the list offers in some reading (私: わたし) is on it, and grammar never
    shows. The analyzer counts its uses where it stands on its own (`bound_uses`)."""
    words, lemmas, pieces = _one_kanji()
    return (len(key[0]) == 1 and _KANJI_RE.match(key[0]) is not None and key[0] not in lemmas
            and key not in pieces)


def _numberish(ch):
    """A character a number ends in, or a one-kanji piece is: a digit or numeral (Ⅲ, 〇), or a kanji."""
    return ch.isnumeric() or _KANJI_RE.match(ch) is not None


def _may_be_bound(text, surface):
    """Could a one-kanji word written `surface` be bound anywhere in `text` — after a digit, a numeral or a kanji, or,
    written as one kanji, before a kanji? Most uses stand beside kana (手を, 私は) and are passed over without locating
    a word. Every token of a library's one-kanji words is asked as the token store indexes it, so the tests are
    written out: kana and Latin sort below U+3400, where Han begins but for 々 and 〇."""
    kanji = _KANJI_RE.match
    one = len(surface) == 1 and kanji(surface) is not None
    size, length = len(surface), len(text)
    at = text.find(surface)
    while at >= 0:
        if at:
            ch = text[at - 1]
            if ch.isnumeric() or ((ch >= "\u3400" or ch == "\u3005") and kanji(ch) is not None):
                return True
        end = at + size
        if one and end < length:
            ch = text[end]
            if (ch >= "\u3400" or ch in "\u3005\u3007") and kanji(ch) is not None:
                return True
        at = text.find(surface, end)
    return False


def word_spans(text, tokens, upto=None):
    """[(start, end) or None] — where each of `tokens` (in order, (lemma, reading, surface, …)) is in `text`, found by
    its surface after the one before it; None for one not found (the tokenizer drops punctuation, numbers and symbols,
    which leave gaps). `upto`: only the first that many (a paragraph read as one sentence can hold hundreds)."""
    spans, at = [], 0
    for token in (tokens if upto is None else tokens[:upto]):
        surface = token[2]
        found = text.find(surface, at) if surface else -1
        if found < 0:
            spans.append(None)
            continue
        at = found + len(surface)
        spans.append((found, at))
    return spans


def _beside(spans, i, step):
    """The span of the nearest located word before (`step` -1) or after (+1) word `i`, or None."""
    j = i + step
    while 0 <= j < len(spans):
        if spans[j] is not None:
            return spans[j]
        j += step
    return None


def _bound_at(text, spans, i):
    """Is word `i` (located at spans[i]) a piece of something else — glued to a one-kanji piece, after a number, or
    after a number's counter (the 目 of ２時間目)?"""
    span = spans[i]
    if span is None:
        return False                    # not found: taken as standing on its own
    start, end = span
    one = end - start == 1 and _KANJI_RE.match(text[start]) is not None
    if start:
        before = _beside(spans, i, -1)
        if before is not None and before[1] == start:
            # a counted word ends right before it — never a number (numbers are no words): glued when it is one kanji
            if one and before[1] - before[0] == 1 and _KANJI_RE.match(text[before[0]]) is not None:
                return True
            # ... or a counter written in kanji right after a number (時間 in ２時間目, 週間 in 三週間前): the one-kanji
            # word after it belongs to the count. A number proper (２, 二, 十, 万) — _numberish takes any kanji too — and
            # never の or つ between (三の矢 is the arrow).
            if (one and before[0] and text[before[0] - 1].isnumeric()
                    and _KANJI_RE.search(text[before[0]:before[1]]) is not None):
                return True
        elif _numberish(text[start - 1]):
            return True                 # after a number, or a kanji no word covers (a numeral, a symbol's kanji)
    if one and end < len(text):
        after = _beside(spans, i, 1)
        if after is not None and after[0] == end:
            if after[1] - after[0] == 1 and _KANJI_RE.match(text[end]) is not None:
                return True             # a word written as one kanji right after it
        elif _KANJI_RE.match(text[end]) is not None:
            return True                 # a kanji no word covers
    return False


def bound_uses(text, tokens, spans=None, only=None):
    """The indices of `tokens` — one sentence's counted words in order, (lemma, reading, surface, …) as
    tokenize_sentences yields them with its `text` — that are one-kanji words standing there as pieces of something
    else (§ above): written as one kanji right beside another one-kanji piece, right after a number, or right after a
    number's counter written in kanji (the 目 of ２時間目). A one-kanji
    piece is a word written as one kanji, or a kanji no counted word covers (a numeral, a kanji the tagger reads as a
    symbol); a number before it is a digit or such a kanji. A sentence's text holds no spaces between its words, so
    私 今 reads as 私今. `spans` (`word_spans`), when the caller has located the words already; `only`, the indices
    to judge, when the caller asks of a few. Pure: the token store counts each file's with it as it indexes, the
    analyzer each sentence it reads."""
    kanji = _KANJI_RE.match
    # A one-kanji lemma sorts at or past U+3400 (kana and grammar below it: most of a sentence's one-character words).
    risky = [i for i, token in (enumerate(tokens) if only is None else ((i, tokens[i]) for i in only))
             if len(token[0]) == 1 and token[0] >= "\u3400" and kanji(token[0]) is not None
             and token[2] and _may_be_bound(text, token[2])]
    if not risky:
        return set()
    if spans is None:
        # Located only as far as the last word asked about needs: its neighbour after it, or the next one found.
        last, upto = max(risky), max(risky) + 2
        spans = word_spans(text, tokens, upto)
        while upto < len(tokens) and all(span is None for span in spans[last + 1:]):
            upto = min(len(tokens), upto * 2)
            spans = word_spans(text, tokens, upto)
    return {i for i in risky if _bound_at(text, spans, i)}


def unoffered(text, tokens, rule=True, spans=None):
    """The indices of `tokens` (one sentence's, as tokenize_sentences yields them with `text`) whose one-character word
    the list can't offer there: one it never offers (`single_kind` 1), or a one-kanji word that is a piece of something
    else there (`bound_uses`). None of them is a use, an example or an unknown of the sentence. Empty with `rule` off
    (Settings' "List one-kanji words only when they're dictionary words"; Chinese callers pass False)."""
    if not rule:
        return set()
    out, offered = set(), []
    for i, token in enumerate(tokens):
        kind = single_kind((token[0], token[1])) if len(token[0]) == 1 else 0
        if kind == 1:
            out.add(i)
        elif kind == 2:
            offered.append(i)
    if offered:
        out |= bound_uses(text, tokens, spans, offered)
    return out


# --- Where a sentence ends: Unicode UAX #29 (Sentence Boundaries) ---------------------------------- #
# A token holding a character of the language's boundary set (settings: logic.sentence_boundaries) ends
# a sentence — character-wise, since the tokenizer glues a terminator to a symbol (➡。). Then:
#   SB8a / SB9  what closes a sentence stays with it — more terminators, closing brackets and quotes,
#               spaces: 反応は!? (the ? was cut off and dropped as debris, leaving 反応は!), 「行くぞ。」
#               (the 」 opened the next sentence and the ja tokenizer threw it away), “是黑车吗？”.
#   SB6–SB8     a full stop that is also a decimal point or an abbreviation's (．, .) ends nothing when a
#               digit or a Latin letter follows it: ３．１４, Ｎｏ．６, Ｍｒ．Ｓｍｉｔｈ.
#   SB8a        a comma, a colon or a dash after them (Unicode's SContinue) continues the sentence:
#               「はい。」、と彼は言った。 is one sentence (Japanese).
# Japanese only — a particle cannot begin a sentence:
#   a question or exclamation quoted without brackets runs on to its verb: 本当に？と聞いた is one
#   sentence. It keeps its ？ / ！ before と; a full stop before と is the conjunction and ends the
#   sentence (ドアを開けた。と、そこには… — UniDic tags both と 格助詞).
#   A quotation followed by a particle (UniDic 助詞: と / って, で, が, の …) or a verb is one sentence
#   with what follows, whatever it holds: 「今日は晴れ。明日は雨」と言った。, 『吾輩は猫である。名前は
#   まだ無い。』で始まる小説 (the user's call, 2026-09-27: the quotation is part of the sentence it stands in).
#   Quotations in a row are taken together by what follows the last: 「やめて。」「いやだ。」と言い合った。
#   Any other follower — a noun, a new subject — leaves its inner sentences apart (「行くぞ。」次だ。
#   and 「はい。」彼女は頷いた。 are two each).
# … is no boundary: it is as often a pause as an end (あの…すみません — the user's call, 2026-09-27).
# A subtitle cue that ends in one has ended on its own timing (close_cue).
_ATERMS = frozenset(".．")                                    # UAX #29 ATerm: the full stops that can be a
_ATERM_JOINS = re.compile(r"[0-9A-Za-z０-９Ａ-Ｚａ-ｚ]")         # decimal point or an abbreviation's
_QUOTE_OPENERS = frozenset("「『｢〝“")                          # Unicode's Quotation_Mark brackets
_QUOTE_CLOSERS = frozenset("」』｣〞〟”")
_QUOTED_MARKS = frozenset("！？!?")                            # what a quoted question or exclamation keeps
_SCONTINUE = frozenset(",-:" "\u3001\uff0c\uff64\uff1a\uff0d\u2013\u2014"   # UAX #29 SContinue: 、，､：－–—
                       "\ufe10\ufe11\ufe13\ufe31\ufe32\ufe50\ufe51\ufe55\ufe58\ufe63")  # and their small forms


def _terminates(surface, following, boundaries):
    """Does the token `surface` end a sentence? `following` is the next token's surface ("" at the end
    of the line): an ATerm with a digit or a Latin letter right after it is inside a number or a word."""
    for k, ch in enumerate(surface):
        if ch in boundaries and (ch not in _ATERMS or not _ATERM_JOINS.match(surface[k + 1:k + 2] or following[:1])):
            return True
    return False


def _closes(surface, boundaries):
    """Is the token part of what closes a sentence (SB8a / SB9): a terminator, a closing bracket or
    quote, a space? With an empty `boundaries`: only a closing mark or a space."""
    return all(ch in boundaries or ch.isspace() or unicodedata.category(ch) in ("Pe", "Pf") for ch in surface)


def _takes_quotation(word, bracketed=False):
    """Does `word` take what stands before it as a quotation: the quotative と / って — or, right after a
    quotation's closing bracket, any particle or a verb (『…。…。』で始まる, 「うん」頷いた)?"""
    f = word.feature
    if bracketed:
        return f.pos1 in ("助詞", "動詞")
    return f.pos1 == "助詞" and f.lemma in ("と", "って")


def _opening(surface, boundaries):
    """Where the next sentence begins inside `surface`, the token a sentence ends with: an opening bracket or quote
    after its terminator, which the tagger read as one symbol with it (｡｢, 。〝 and ｡(( are one token each) — else 0.
    An opening mark never ends a sentence (_closes): it opens the next one."""
    for k in range(1, len(surface)):
        if unicodedata.category(surface[k]) in ("Ps", "Pi") and not boundaries.isdisjoint(surface[:k]):
            return k
    return 0


def _sentence_ends(words, surfaces, boundaries):
    """The indices of the tokens of one line (fugashi nodes or JoinedWords, and their surfaces) that a
    Japanese sentence ends after (§ above). Only the tokens holding a boundary character are looked at
    one by one, and quotations only on a line that has one: for most tokens the test stays in C
    (measured: the tokenizer's pass 5% slower on prose, 6% on short subtitle-like lines)."""
    n = len(surfaces)
    runs, last = [], -1              # (a terminator's index, the index of the last token closing it)
    for i in [i for i, surface in enumerate(surfaces) if not boundaries.isdisjoint(surface)]:
        if i > last and _terminates(surfaces[i], surfaces[i + 1] if i + 1 < n else "", boundaries):
            last = i
            while last + 1 < n and _closes(surfaces[last + 1], boundaries):
                last += 1
            runs.append((i, last))
    if not runs:
        return ()
    joined = set()                   # the runs a quotation keeps inside its sentence
    line = "".join(surfaces)
    if not (_QUOTE_OPENERS.isdisjoint(line) and _QUOTE_CLOSERS.isdisjoint(line)):
        opened = []                  # the index of each quotation still open on this line
        run_of = None                # (where a run of quotations began, the index its next quotation opens at)
        for k, surface in enumerate(surfaces):
            for ch in surface:
                if ch in _QUOTE_OPENERS:
                    opened.append(k)
                elif ch in _QUOTE_CLOSERS:
                    start = opened.pop() if opened else -1      # a closer alone: opened on an earlier line
                    if run_of is not None and run_of[1] == start:
                        start = run_of[0]                       # 「…。」「…。」と: the run is taken together
                    run_of = None
                    f = k + 1
                    while f < n and _closes(surfaces[f], ()):
                        f += 1
                    if f < n and surfaces[f][:1] in _QUOTE_OPENERS:
                        run_of = (start, f)
                    elif f < n and _takes_quotation(words[f], bracketed=True):
                        joined.update(run for run in runs if start < run[0] < k)
    return {j for i, j in runs if (i, j) not in joined and not (j + 1 < n and surfaces[j + 1][:1] in _SCONTINUE)
            and not (j + 1 < n and _takes_quotation(words[j + 1])
                     and _QUOTED_MARKS.issuperset(ch for s in surfaces[i:j + 1] for ch in s if ch in boundaries))}


class JapaneseTokenizer(Tokenizer):
    def __init__(self, library=True):
        self.tagger = Tagger()   # fugashi, reading text as every caller does (§ What the tagger reads)
        # The library's name tables (app/names.py) — off only for the token store, which records their candidates
        # (`tokenize_sentences(names=…)`) and applies the tables to its cached tokens as it reads them.
        self.library = library

    def tokenize(self, text, pieces=None):
        """Returns a list of (lemma, parsing_reading, original_surface, orth_base) tuples. `pieces`, a
        list, also receives the (lemma, reading) of each piece of every joined word (§ above)."""
        # Simple wrapper around sentences
        all_tokens = []
        for _, tokens in self.tokenize_sentences(text, pieces):
            all_tokens.extend(tokens)
        return all_tokens

    def tokenize_sentences(self, text, pieces=None, names=None):
        """Yields (sentence_string, list_of_filtered_tokens).

        Fugashi consumes newlines, so '\\n' in the boundary set never fired and separate lines
        (e.g. a transcript's title / URL / '----' header) merged into one giant sentence. We
        therefore process the text line by line, treating each line break as a hard boundary.

        `names`, an app.names.Record, receives every run the library's name tables could join, with the
        sentence (as yielded) and the counted tokens it covers — how the token store keeps them for later.
        """
        # Unidic-lite pos1: '補助記号' (punctuation), '空白' (spaces)
        # A frozenset + isdisjoint keeps the per-token boundary test in C. This runs millions of
        # times on a full library, and an `any(ch in ... for ch in surface)` generator here measured
        # ~11% slower across the whole tokenization pass.
        boundaries = frozenset(LOGIC.get("sentence_boundaries", {}).get("ja", "。｡．！？!?\n"))
        joins = affix_joins()
        sanitized = _SANITIZED.get      # a term met before, cleaned (_sanitize_term): looked up for every token
        yielded = 0                  # sentences yielded so far: the index of the one being built

        for line in text.split("\n"):
            current_sentence_tokens = []
            current_sentence_surface = []
            words = join_affixes(self.tagger(line), joins, library=self.library)
            surfaces = [word.surface for word in words]
            # Where each token lands — (sentence, counted tokens before it) — for the name candidates' spans.
            cands = names.read_line(words) if names is not None else ()
            at = [] if cands else None
            # CHARACTER-wise, not whole-token: the tokenizer glues a terminator to an adjacent
            # symbol, so '➡。' and '｡。' arrive as single tokens. Testing the whole surface let
            # every one of those slip past, and a "sentence" ran on through a dozen subtitle
            # cues (measured: 409 characters on a real episode). What closes a sentence, and where
            # a quotation keeps its sentences together: _sentence_ends (UAX #29).
            ends = _sentence_ends(words, surfaces, boundaries)

            for i, word in enumerate(words):
                if pieces is not None and isinstance(word, JoinedWord):
                    for part_surface, part in word.parts:
                        part_lemma = part.lemma if part.lemma else part_surface
                        pieces.append((_sanitize_term(part_lemma) if SANITIZE_JA else part_lemma,
                                       part.lForm or part.kana or ""))
                surface = surfaces[i]

                lemma = word_lemma(word)     # None: no word — a symbol, a space, a number (§ above)
                if SANITIZE_JA and lemma is not None:
                    lemma = sanitized(lemma) or _sanitize_term(lemma)
                # The reading of the LEMMA (UniDic lForm), not of this conjugated surface (`kana`):
                # a word is keyed on (lemma, reading), so the surface reading split a verb into one
                # row per conjugation — 辿り着く sat on four rows (タドリツイ 102, タドリツク 40,
                # タドリツケ 32, タドリツキ 18) and ranked far below its true 192, and a word none of
                # whose forms cleared the floor alone (立ち入る, 31 in all) never appeared. lForm is one
                # value per word (辿り着い / 辿り着ける -> タドリツク; 仕方ねえ -> シカタナイ) yet still
                # tells real homographs apart (上手: ジョウズ / カミテ). `kanaBase` is no substitute: it
                # keeps the potential form (辿り着ける -> タドリツケル). Chinese readings stay "".
                reading = word.feature.lForm or word.feature.kana or ""
                # orthBase is the dictionary form in the spelling THIS text used, where `lemma` is
                # UniDic's canonical headword for the lexeme. They differ for ~38% of content
                # tokens: 引きずって -> lemma 引き摺る but orthBase 引きずる; 須藤 -> lemma スドウ
                # (proper nouns get a katakana lemma) but orthBase 須藤. The lemma stays the
                # identity — it is what merges いう/言う/言える into one word for counting — and the
                # orth rides along purely as the name to SHOW. Never key anything on it.
                orth = word.feature.orthBase if word.feature.orthBase else word.surface
                if SANITIZE_JA:
                    orth = sanitized(orth) or _sanitize_term(orth)

                current_sentence_surface.append(surface)
                if at is not None:
                    at.append((yielded, len(current_sentence_tokens), lemma is not None))
                if lemma is not None:
                    current_sentence_tokens.append((lemma, reading, word.surface, orth))

                if i in ends:
                    # The next sentence's bracket, glued to this end — a token of one character holds none.
                    opening = _opening(surface, boundaries) if len(surface) > 1 else 0
                    if opening:
                        current_sentence_surface[-1] = surface[:opening]
                    s_text = "".join(current_sentence_surface).lstrip("」』”'\" ").strip()
                    # A fragment with no Japanese in it is punctuation debris — a line that is
                    # only 「…………」, a list number's １． Never a usable example sentence.
                    if s_text and has_target_language(s_text, 'ja'):
                        yield s_text, current_sentence_tokens
                        yielded += 1
                    current_sentence_tokens = []
                    current_sentence_surface = [surface[opening:]] if opening else []

            # End of a line is itself a hard sentence boundary — flush any remainder.
            if current_sentence_surface:
                s_text = "".join(current_sentence_surface).lstrip("」』”'\" ").strip()
                if s_text and has_target_language(s_text, 'ja'):
                    yield s_text, current_sentence_tokens
                    yielded += 1
            # A candidate holds kana or kanji, so its sentence was yielded; no sentence end falls inside one.
            for cand in cands:
                sentence, a, _counted = at[cand.i]
                _s, before, counted = at[cand.j - 1]
                names.span(sentence, cand, a, before + counted, surfaces[cand.i:cand.j])

_LEADING_DIGITS_RE = re.compile(r"^[0-9０-９]+")


def strip_verse_number(sentence, tagger):
    """A Japanese example sentence without the verse number some texts put before it — 「13そこで
    モーサヤは…」 reads 「そこでモーサヤは…」 (a scripture-style book in the library numbered every
    verse, and those numbers were landing on cards). Only a number made of digits, and only when what
    follows is not what the number counts: a counter or suffix (3人, 2つ目, 10年前, 5番目, 12月,
    1日中), another number (100万) or punctuation (2、3日) keeps it. Only the front is cut, so the
    sentence is still a verbatim piece of its file and its source anchor still finds it.

    `tagger` is the fugashi tagger the run already holds; the digits are not a word, so nothing the
    analysis counted changes — only the sentence shown."""
    if not sentence or not _LEADING_DIGITS_RE.match(sentence):
        return sentence
    words = list(tagger(sentence))
    if len(words) < 2:
        return sentence
    first, following = words[0], words[1]
    if first.feature.pos2 != "数詞" or not _LEADING_DIGITS_RE.fullmatch(first.surface):
        return sentence
    feature = following.feature
    if (feature.pos1 in ("接尾辞", "補助記号", "空白") or feature.pos2 == "数詞"
            or str(feature.pos3 or "").startswith("助数詞")):
        return sentence
    return sentence[len(first.surface):].lstrip() or sentence


# --- Chinese: one cut and one word test for every caller ------------------------------------------------- #
# The tokenizer, the パターン builder and its card lookups all cut Chinese here and count a word by chinese_word, so
# a word is keyed alike everywhere (a builder that cut differently would silently miss every lookup).
_CEDICT = {}   # name -> a table of app/cedict_data.py, decoded on the first Chinese cut


def _cedict_table(name):
    """app/cedict_data.py's table `name` (CC-CEDICT, CC BY-SA 4.0 — a module of its own), decoded once, or an empty
    table when the module can't be read: the cut is then jieba's dictionary words alone, never a crash."""
    table = _CEDICT.get(name)
    if table is None:
        try:
            from app import cedict_data
            table = getattr(cedict_data, name)() or {}
        except Exception:
            table = {}
        _CEDICT[name] = table
    return table


def chinese_cut(text):
    """The pieces of `text` — read already (tagger_text) and in Simplified, the only script jieba's dictionary
    holds — in order: together they spell the text.

    Only jieba's dictionary makes a word: its statistical guesses glue neighbours into non-words (他来, 我要, 这是),
    so they are off — but a name it guesses is kept (_guessed_names). jieba's dictionary holds phrases no dictionary
    lists as words (吃了饭, 一碗, 电影吧, 很多): an entry CC-CEDICT doesn't list whose words hold grammar is read as
    those words, and a count CC-CEDICT lists is read as its number and its measure word (一个 is 一 + 个) — the table
    scripts/build_cedict_data.py builds (app/cedict_data.py). Pieces that say one word doubled are one piece
    (_join_doubled); chinese_base reads its word."""
    import jieba   # lazy (cached after first use): only a Chinese run loads jieba
    pieces = list(jieba.cut(text, cut_all=False, HMM=False))
    splits = _cedict_table("splits")
    if not splits:
        return pieces
    return _join_doubled(_guessed_names(pieces, splits), text)


_CHINESE_CHAR = {}      # one character -> whether it is Chinese (_ZH_TARGET_RE, asked once per character)


def _guessed_names(pieces, splits):
    """`pieces` — jieba's dictionary cut — with the names jieba's model would guess kept whole, and each entry of
    `splits` (the CC-CEDICT table) read as its words. Only a run of single characters the dictionary left is
    guessed at, by jieba's own model (finalseg), as its cut with the guesses on would; a guess stays whole when it is
    2-3 characters led by a character CC-CEDICT gives a surname, no word of jieba's dictionary, with no character
    jieba's tags file as grammar and, at 3, no verb last — 李明, 王芳; else its first two characters are tried (龙仁用 is
    龙仁 + 用), and any other guess stays in characters (我要 is 我 + 要)."""
    import jieba
    from jieba import finalseg
    freq, family = jieba.dt.FREQ, _cedict_table("surnames")
    grammar, verbs = _cedict_table("grammar_chars"), _cedict_table("verb_chars")

    def named(run):
        return (2 <= len(run) <= 3 and run[0] in family and not freq.get(run) and grammar.isdisjoint(run)
                and not (len(run) == 3 and run[-1] in verbs))

    def guessed(run):
        text = "".join(run)
        if len(run) < 2 or not family or freq.get(text):
            out.extend(run)         # jieba guesses only where the run is no word of its own
            return
        for guess in finalseg.cut(text):
            if named(guess):
                out.append(guess)
            elif len(guess) == 3 and named(guess[:2]):
                out.extend((guess[:2], guess[2]))
            else:
                out.extend(guess)

    out, run = [], []
    chinese = _CHINESE_CHAR
    for piece in pieces:
        if len(piece) == 1:
            single = chinese.get(piece)
            if single is None:
                single = chinese[piece] = bool(_ZH_TARGET_RE.match(piece))
            if single:
                run.append(piece)
                continue
        if run:
            guessed(run)
            run = []
        cuts = splits.get(piece)
        if cuts is None:
            out.append(piece)
            continue
        pos = 0
        for n in cuts:
            out.append(piece[pos:pos + n])
            pos += n
    if run:
        guessed(run)
    return out


# Where a word can be said doubled in a text: a run of one character (哈哈哈), or two said twice (休息休息).
_DOUBLINGS = re.compile(r"(.)\1\1|(..)\2")


def _join_doubled(pieces, text):
    """Pieces that touch in the text and say one word doubled are one piece, where chinese_base reads the whole as
    its word: a word of two characters said twice (休息 + 休息), a run of one character jieba cut by length (哈哈哈 +
    哈哈). Punctuation and spaces are pieces of their own, so nothing joins across them. Only the pieces where `text`
    (which they spell) doubles something are looked at."""
    windows, ends = [], None
    for found in _DOUBLINGS.finditer(text):
        if ends is None:
            ends = list(accumulate(map(len, pieces)))
        first, last = bisect.bisect_right(ends, found.start()), bisect.bisect_right(ends, found.end() - 1)
        if windows and first <= windows[-1][1] + 1:
            windows[-1][1] = max(windows[-1][1], last)
        else:
            windows.append([first, last])
    if not windows:
        return pieces
    out = []
    i, n = 0, len(pieces)
    for first, last in windows:
        if i < first:
            out.extend(pieces[i:first])
            i = first
        while i <= last and i < n:
            piece, j = pieces[i], i + 1
            if j < n and (pieces[j] == piece or pieces[j][:1] == piece[-1:]):
                if len(piece) == 2 and pieces[j] == piece and piece[0] != piece[1]:
                    j += 1
                elif piece == piece[0] * len(piece):
                    while j < n and pieces[j] == piece[0] * len(pieces[j]):
                        j += 1
                whole = "".join(pieces[i:j])
                if j > i + 1 and chinese_base(whole):
                    out.append(whole)
                    i = j
                    continue
            out.append(piece)
            i += 1
    out.extend(pieces[i:])
    return out


def chinese_base(piece, form=None):
    """The word a doubled form counts as, or None — read on chinese_cut's piece (Simplified), spelled as `form`, the
    same stretch in the text's own script (conversion is length-preserving), spells it:
      开开心心 is 开心: a doubled form whose word CC-CEDICT lists, unless the form has a meaning of its own (马马虎虎
        'so-so', 形形色色 'all kinds of' stay whole) — app/cedict_data.py's FOLDS;
      休息休息 is 休息: a word of two characters said twice;
      哈哈哈哈哈 is 哈哈: a run of one character, when the shortest run CC-CEDICT lists is a sound or a laugh (SOUNDS) —
        好好好 stays as it is cut.
    Two characters (人人, 看看, 慢慢) are never folded, nor anything with the table unreadable."""
    n = len(piece)
    if n < 3:
        return None
    folds = _cedict_table("folds")
    if not folds:
        return None
    form = form or piece
    if n == 4:
        if piece[:2] == piece[2:] and piece[0] != piece[1]:
            return form[:2] if chinese_word(piece[:2]) else None
        if piece in folds:
            return form[0] + form[2]
    if piece == piece[0] * n:
        sounds = _cedict_table("sounds")
        for size in range(2, n):
            if piece[:size] in sounds:
                return form[:size]
    return None


# The numerals of Chinese running text (GB/T 15835-2011: 〇 零 一 … 九 十 百 千 万 亿, with the Traditional 萬 億) and
# 两 / 兩, the numeral a count takes. Unicode's numeric property is no test: it numbers 拾 'pick up' and 陆 'land' (their
# financial forms) and gives 两 no value.
_ZH_NUMERALS = "〇零一二三四五六七八九十百千万亿萬億两兩"


def chinese_word(word):
    """Whether a piece is a Chinese word: it holds a Chinese character (Unicode's own ranges, app/unicode_ranges.py —
    〇 and Extension A / B included), no kana letter (a Japanese line in a Chinese library is no Chinese), and is no
    number — a number said (三千五百, 二十五, 一) is never a list word nor an unknown in a sentence, as in Japanese.
    A word made only of numerals that counts nothing stays a word (千万 'by all means', 万一 'just in case' —
    app/cedict_data.py's NOT_COUNTS); with that table unreadable, no number is dropped."""
    if not _ZH_TARGET_RE.search(word) or _KANA_LETTER_RE.search(word):
        return False
    if word.strip(_ZH_NUMERALS):
        return True
    spared = _cedict_table("not_counts")
    return not spared or zh_script.to_simplified(word) in spared


_ZH_TAGS = []      # jieba's own tag table (jieba.posseg's word_tag_tab), read on the first ask


def chinese_verb(word):
    """Is `word` (in either script) a verb to jieba's own tag table — v, vn, vd, vi … (jieba.posseg's word_tag_tab,
    read once: about 0.3 s, only when a card asks)? A card's 了 / 过 / 着 comes off only after a verb
    (anki_match.one_word)."""
    if not _ZH_TAGS:
        try:
            import jieba.posseg as posseg
            _ZH_TAGS.append(posseg.dt.word_tag_tab)
        except Exception:
            _ZH_TAGS.append({})
    return str(_ZH_TAGS[0].get(zh_script.to_simplified(word)) or "").startswith("v")


class ChineseTokenizer(Tokenizer):
    def __init__(self, reinforce_segmentation=False, script="asis"):
        # Which script every token and sentence comes out in (the `zh_script` setting): "asis" is
        # the text as written, "s" Simplified, "t" Traditional. See app/zh_script.py.
        self.script = script if script in ("s", "t") else "asis"
        if self.script != "asis":
            print(f"Configuration: Chinese read as {'Simplified' if self.script == 's' else 'Traditional'}.")
        # `reinforce_segmentation` is retired and ignored: it was a hand list of two pairs (就把, 您不) that the
        # dictionary's own cut already splits; an old settings.json or command line still passes it.

    def tokenize(self, text):
        """Returns a list of (lemma, pinyin_placeholder, original_surface, orth) tuples."""
        all_tokens = []
        for _, tokens in self.tokenize_sentences(text):
            all_tokens.extend(tokens)
        return all_tokens

    def tokenize_sentences(self, text):
        """Yields (sentence_string, list_of_filtered_tokens)"""
        # The text is cut by chinese_cut, the one Chinese cut every caller reads
        # We need to manually handle sentence splitting because jieba just streams tokens
        
        # 1. Split text into blocks by punctuation (broadly) to avoid feeding massive text to jieba if needed,
        # but jieba is fast. However, we need to reconstruct sentences for context.
        
        # Simple approach: Tokenize everything, then buffer into sentences based on punctuation tokens

        # jieba reads the text as every tagger does (§ What the tagger reads): ⽅法 is 方法, and a zero-width
        # space no longer cuts a word in two. Each piece comes out as (word, surface): the word as read — the
        # dictionary form, keyed and listed — and the text's own spelling, for the sentence and the boundary
        # test. They differ only where the text was read in another form.
        read, at = tagger_text(text)
        # Segment in SIMPLIFIED whichever script is wanted: jieba's dictionary is Simplified only
        # (學習/這個 aren't in it, 学习/这个 are), so a Traditional text cut as written came out in
        # pieces (為 / 什麼, 經濟關 / 係). As-is keeps every word as the text writes it; "s" / "t" convert.
        # Every conversion is length-preserving (zh_script, I3), so each piece's offsets in `cut` are
        # its offsets in the output text too — slice there.
        cut = zh_script.to_simplified(read)
        if self.script == "asis":
            words, shown = read, text
        else:
            words = cut if self.script == "s" else zh_script.to_traditional(cut)
            shown = words if at is None else (zh_script.to_simplified(text) if self.script == "s"
                                              else zh_script.to_traditional(zh_script.to_simplified(text)))

        def _aligned(pieces, pos=0):
            for w in pieces:
                end = pos + len(w)
                yield w, words[pos:end], (shown[pos:end] if at is None else shown[at[pos]:at[end]])
                pos = end

        seg_list = _aligned(chinese_cut(cut))
        
        current_sentence_tokens = []
        current_sentence_surface = []
        
        punctuation_str = LOGIC.get("sentence_boundaries", {}).get("zh", "。｡！？!?\n")
        punctuation = set(list(punctuation_str))
        # Common particles/punctuation to skip in "meaningful token" list might be needed,
        # but for now we include everything that isn't strict punctuation/space.
        
        ended = line_end = False
        for piece, word, surface in seg_list:
            # What closes a sentence stays with it (UAX #29 SB8a / SB9, § above JapaneseTokenizer):
            # ？？ and ？！ end together, and a closing quote joins the sentence it closes — “是黑车吗？”
            # — where it used to open the next one. A line end ends the sentence where it stands.
            if ended and (line_end or not _closes(surface, punctuation)):
                s_text = "".join(current_sentence_surface).strip()
                # Punctuation-only debris is never a usable example sentence.
                if s_text and has_target_language(s_text, 'zh'):
                    yield s_text, current_sentence_tokens
                current_sentence_tokens = []
                current_sentence_surface = []
                ended = False
            line_end = surface.strip() == '' and '\n' in surface
            # Character-wise for the same reason as Japanese: a terminator can arrive glued to an
            # adjacent symbol, and comparing the whole token would miss it. isdisjoint keeps the
            # per-token test in C.
            is_boundary = not punctuation.isdisjoint(surface) or line_end
            
            # A doubled form counts as its word (chinese_base): 开开心心 is 开心, the text's own stretch its surface.
            if len(piece) > 2:
                word = chinese_base(piece, word) or word
            # Strict filtering: a Chinese word holds a Chinese character and no kana letter (chinese_word,
            # the builder's test too).
            is_skippable = not chinese_word(word)
            
            # For Chinese, "lemma" is just the word. "Reading" (Pinyin) requires pypinyin, 
            # but user didn't ask for Pinyin injection yet, and existing data might not have it.
            # We will use empty string for reading for now, or the word itself if that helps matching.
            # Surasura uses (lemma, reading) as unique key.
            # If we use "" for reading, we might merge homophones? 
            # Japanese relies on reading for disambiguation sometimes? 
            # Actually, (lemma, reading) tuple is the key. 
            # For Chinese, (Word, "") is fine. Distinct words are distinct characters.
            
            current_sentence_surface.append(surface)
            
            if not is_skippable:
                # Jieba has no lemma/orth distinction — the word as read IS the dictionary form — so the
                # orth slot simply repeats it, keeping the tuple shape identical across languages.
                current_sentence_tokens.append((word, "", surface, word))
            
            ended = ended or is_boundary

        # Flush
        if current_sentence_surface:
            s_text = "".join(current_sentence_surface).strip()
            if s_text and has_target_language(s_text, 'zh'):
                yield s_text, current_sentence_tokens


# How the aggregation ranks a word's candidate examples while it keeps the best 30: (too short, too long, cost).
_CONTEXT_RANK = itemgetter(0, 1, 2)


def rolling_context_cost(target_freq, sorted_unknown_freqs):
    """Approximate the i+1 cost of a candidate sentence for a target word.

    A candidate's true i+1 quality depends on which of its OTHER unknown words are still
    unknown once the learner reaches the target. More-common co-words are learned first
    (higher priority), so they won't make the sentence harder — only RARER co-words remain.
    Approximate that with running frequency: count the sentence's unknowns whose frequency is
    strictly below the target's. `sorted_unknown_freqs` must be ascending. O(log n).
    """
    return bisect.bisect_left(sorted_unknown_freqs, target_freq)


def _sanitize_term(term):
    """
    Strip all characters starting from the hyphen - or space in the Term field.
    Example: \"アイリス-iris\" -> \"アイリス\"
    """
    if not isinstance(term, str):
        return term
    
    # If sanitization is DISABLED and we aren't loading an external frequency list, 
    # we should just strip whitespace. 
    # Actually, let's keep _sanitize_term as a raw helper and have the CALLERS decide.
    # No, wait. The user wants the toggle to affect analysis AND loading.
    
    # A term met before is looked up: this runs for every token read, twice (its lemma and its spelling), and a
    # library's tokens are a few tens of thousands of terms (_SANITIZED).
    done = _SANITIZED.get(term)
    if done is not None:
        return done

    # First strip leading/trailing whitespace
    stripped = term.strip()

    # Everything before the first hyphen or space — what re.split(r'[-\s]', term)[0] is, from one precompiled
    # search
    cut = _TERM_CUT_RE.search(stripped)
    done = stripped if cut is None else stripped[:cut.start()]
    if len(_SANITIZED) >= _SANITIZED_KEPT:
        _SANITIZED.clear()
    _SANITIZED[term] = done
    return done


_TERM_CUT_RE = re.compile(r'[-\s]')
_SANITIZED = {}             # term -> _sanitize_term(term), for the terms met lately: the same text, looked up
_SANITIZED_KEPT = 100000    # terms, about 15 MB — a large library's lemmas and spellings; when full it starts again

def _known_term(term):
    """A KnownWord.json dictForm as a known word. Migaku writes some with a gloss after the word (アイリス-iris): cut
    off as `_sanitize_term` cuts a lemma — but only when what follows the first space or hyphen holds no Japanese. A
    sentence an Anki "Also read" field synced (そうだ　女の子だ) stays whole, so every word in it is known."""
    if not isinstance(term, str):
        return term
    cut = _sanitize_term(term)
    return term.strip() if _JA_TARGET_RE.search(term.strip()[len(cut) + 1:]) else cut

# The spelling a row shows and the spellings it was met in: one rule, the analyzer's and the fast re-plan's
# (app/plan_rules.py).
from app.plan_rules import (FORMS_LIMIT, _jmdict_to_readings, _said_with_to,  # noqa: E402
                            display_orth as _display_orth, display_forms as _display_forms)

# A list line is compared with the lemma as it stands — the report's Ignore button writes lemmas (為る,
# 其れ) — so a line typed the way Japanese is mostly written, in hiragana (する, ある, それ), ignored nothing.
# Such a line also names the ONE word the tokenizer reads it as, when that word is spelled with a kanji
# and sounds as the line does (its reading, UniDic's lForm, IS the line): する -> 為る, それ -> 其れ. Only
# that: the lists hold lemmas the report wrote, and read alone 12 of the user's 105 lines are ANOTHER
# word (為る -> 成る, 書き -> 書く) and 12 split (一日 -> 一 + 日) — so a kanji or katakana line, a line read
# as another sound (どん -> 何の ドノ, よう -> 良く ヨク) or as several words stays the lemma it names, and
# the user's Blacklist 為る never ignores なる. A kana line names one homophone, as a kana known word
# does (まく -> 膜); one kana is never read (お alone is the prefix 御). On the user's three
# lists: adds nothing.
_HIRAGANA_LINE_RE = re.compile(r'^[ぁ-ゖ]{2,}$')
_KANJI_RE = re.compile(f'[{HAN}]')   # app/unicode_ranges.py


def _kana_lines_read(lines):
    """The kanji-spelled words the hiragana `lines` are typed for (する -> 為る; see above)."""
    lines = [line for line in lines if _HIRAGANA_LINE_RE.match(line)]
    if not lines:
        return set()                                   # no tokenizer is built for a list without one
    try:
        tokenizer = JapaneseTokenizer()
        words = set()
        for line in lines:
            tokens = tokenizer.tokenize(line)
            sound = "".join(chr(ord(ch) + 0x60) for ch in line)   # the line in katakana, as lForm writes it
            if len(tokens) == 1 and _KANJI_RE.search(tokens[0][0]) and tokens[0][1] == sound:
                words.add(tokens[0][0])
        return words
    except Exception:
        return set()                                   # no tokenizer: the lines as they are, as before


def load_simple_list(file_path, script="asis", language=None):
    if not os.path.exists(file_path):
        return set()
    # In the file's own encoding (path_utils.read_text): a list saved with a BOM, as UTF-16 or in
    # Windows' "ANSI" (CP932 / GBK) reads like any other instead of losing its first entry or
    # stopping the run.
    return _list_words(read_text(file_path, language).splitlines(), script)


def _list_words(lines, script="asis"):
    """The words a list's `lines` name, as every ignore set holds them (`load_simple_list`)."""
    # Ignore comments starting with # and empty lines. Chinese entries are read in the library's
    # script (`zh_script`) so they still match converted tokens; the file itself is never touched.
    entries = set(zh_script.convert(_sanitize_term(line.strip()) if SANITIZE_JA else line.strip(), script)
                  for line in lines if line.strip() and not line.strip().startswith("#"))
    # Japanese: a hiragana line also names the word it is typed for (する -> 為る; `_kana_lines_read`).
    return (entries | _kana_lines_read(entries)) if SANITIZE_JA else entries


def load_ignored_entries(user_files_dir, script="asis", language=None):
    """KnownWord.json's IGNORED entries (Migaku's status: a word the user dismissed there) and, with Ignore names on,
    the library's names, as ignored words — each read as a line of the Ignore list is (`_list_words`). The one reader
    (`token_index.ignored_entries`) is the Rarity preview's too, so the slider counts what the list counts."""
    from app import token_index
    return _list_words(token_index.ignored_entries(user_files_dir, language), script)

def discover_yomitan_frequency_lists(user_files_dir, language='ja'):
    """
    Scan User Files directory for frequency_list_{lang}_*.csv files.
    Returns a dictionary mapping frequency list name -> filepath.
    """
    freq_lists = {}
    if not os.path.exists(user_files_dir):
        return freq_lists
    
    prefix = f"frequency_list_{language}_"
    
    try:
        for filename in os.listdir(user_files_dir):
            if filename.startswith(prefix) and filename.endswith(".csv"):
                # Extract name: frequency_list_ja_Novel.csv -> Novel
                list_name = filename.replace(prefix, "").replace(".csv", "")
                filepath = os.path.join(user_files_dir, filename)
                freq_lists[list_name] = filepath
    except Exception as e:
        print(f"Warning: Error scanning frequency lists: {e}")
    
    return freq_lists

def load_yomitan_frequency_list(csv_path, script="asis", language=None):
    """
    Load a frequency list from a CSV file.
    Returns a dictionary mapping word -> rank (int).

    CSV format: Two columns: Word, Rank
    Example:
    Word,Rank
    の,1
    は,2
    ...

    Note: Multiple words can have the same rank value.
    Uses csv module for fast loading of large files.

    `script` ("s"/"t", Chinese only) reads the words in the library's script. Two spellings can then
    become one word (乾 and 幹 are both 干 in Simplified); it keeps the commoner rank.

    Read in the file's own encoding (path_utils.read_text): Excel's "CSV UTF-8" starts with a BOM,
    which glued to the "Word" header skipped every row, and its plain CSV is CP932 / GBK.
    """
    word_to_rank = {}
    
    if not os.path.exists(csv_path):
        print(f"Warning: Frequency list not found: {csv_path}")
        return word_to_rank
    
    try:
        reader = csv.DictReader(read_text(csv_path, language).splitlines())
        for row in reader:
            try:
                # Sanitize to match analysis lemmas ONLY when JA term sanitization is active.
                # _sanitize_term strips from the first hyphen/space (a Japanese-only cleanup);
                # Chinese (and JA with the toggle off) must keep the raw word.
                word = _sanitize_term(row['Word']) if SANITIZE_JA else (row['Word'] or '').strip()
                rank = int(row['Rank'])
                if script != "asis":
                    word = zh_script.convert(word, script)
                    if word_to_rank.get(word, rank) < rank:
                        continue
                word_to_rank[word] = rank
            except (ValueError, KeyError):
                continue  # Skip malformed rows
    except Exception as e:
        print(f"Warning: Error loading frequency list {csv_path}: {e}")
    
    print(f"Loaded {len(word_to_rank)} words from {os.path.basename(csv_path)}")
    return word_to_rank

def get_tier_from_rank(rank):
    """
    Determine tier from frequency rank.
    Tier ranges:
    - Tier 1: 1-2500 (most common)
    - Tier 2: 2501-5000
    - Tier 3: 5001-7500
    - Tier 4: 7501-10000
    - Tier 5: 10001+ (least common)
    """
    thresholds = LOGIC.get("tiers", {}).get("thresholds", [2500, 5000, 7500, 10000])
    
    if not isinstance(rank, int) or rank <= 0:
        return "Outside"
    
    for i, threshold in enumerate(thresholds):
        if rank <= threshold:
            return str(i + 1)
            
    return str(len(thresholds) + 1)

def load_known_words(json_path, tokenizer):
    try:
        print(f"Loading known words from {json_path}...")
    except UnicodeEncodeError:
        print("Loading known words (path contains non-ASCII characters)...")
    if not os.path.exists(json_path):
        print("Warning: Known words file not found.")
        return set(), set()
    
    # In the file's own encoding (path_utils.read_text): saved with a BOM (Notepad's "UTF-8 with
    # BOM") or as UTF-16, json.load refused it and Generate stopped. The tokenizer says the language.
    data = json.loads(read_text(json_path, "ja" if isinstance(tokenizer, JapaneseTokenizer) else "zh"))
        
    known_tuples = set()
    known_lemmas = set()
    # A Chinese tokenizer reading in one script (`zh_script`) converts every term it tokenizes; the
    # raw term trusted below must be read in that same script or it can never match. Converted
    # separately from the ORIGINAL term, exactly as the tokenizer converts it, so the two can't drift.
    script = getattr(tokenizer, "script", "asis")
    # Idioms and set phrases on the list (logic.phrase_rows, Japanese): a phrase row is its words' lemmas joined
    # (気が付く), so a known phrase is known however its sentences spell it — a 気がつく card synced from Anki makes
    # the row 気が付く known. Only a set phrase's run: 努力する's words joined name nothing. Off, nothing is added (the
    # known-words cache is keyed on the switch and the phrases: token_index).
    phrase_set = None
    if isinstance(tokenizer, JapaneseTokenizer) and LOGIC.get("phrase_rows", True):
        try:
            from app import phrases as _phrases
            phrase_set = _phrases.load()
        except Exception:
            phrase_set = None
    # Handle both Dict (list in 'words') and List formats
    if isinstance(data, dict):
         word_list = data.get("words", [])
    elif isinstance(data, list):
         word_list = data
    else:
         word_list = []

    for entry in word_list:
        status = entry.get("knownStatus", "")
        has_card = entry.get("hasCard", 0)
        
        is_known = (status == "KNOWN") or (has_card == 1)
        
        if is_known:
            term = entry.get("dictForm", "")
            if SANITIZE_JA:
                term = _known_term(term)     # a gloss cut off; a sentence kept whole
            
            if term:
                # Normalize using the same tokenizer
                try:
                    # A known joined word marks its pieces known too, as it did before words kept their
                    # affixes: 時間 is known only through the user's 時間帯 (Patterns_Quality_Spec §6.2a).
                    pieces = [] if isinstance(tokenizer, JapaneseTokenizer) else None
                    tokens = tokenizer.tokenize(term) if pieces is None else tokenizer.tokenize(term, pieces)
                    term = zh_script.convert(term, script)

                    # 0. Trust the explicit dictForm as a lemma (catches cases where tokenizer normalizes "その" -> "其の")
                    known_lemmas.add(term)

                    # 1. Add individual tokens
                    for lemma, reading, _, _ in tokens:
                        known_tuples.add((lemma, reading))
                        known_lemmas.add(lemma)
                    for lemma, reading in pieces or ():
                        known_tuples.add((lemma, reading))
                        known_lemmas.add(lemma)

                    # 2. Heuristic: If multiple tokens, add the combined form too.
                    # This fixes issues like "まで" (which tokenizer might split as "Ma"+"De" in isolation, 
                    # but find as "Made" particle in context).
                    if len(tokens) > 1:
                        full_reading = "".join([t[1] for t in tokens if t[1]]) # Concat readings
                        known_tuples.add((term, full_reading))
                        known_lemmas.add(term)
                        if phrase_set is not None and phrase_set.of_word("".join(t[0] for t in tokens)) is not None:
                            known_lemmas.add("".join(t[0] for t in tokens))

                except Exception:
                    # Fallback if tokenization fails
                    pass
                
    print(f"Loaded {len(known_tuples)} known word variations and {len(known_lemmas)} unique lemmas.")
    return known_tuples, known_lemmas

# Precompiled once at import \u2014 has_target_language runs per-token (millions of calls on a large
# library), so compiling these inline made re.compile the single biggest hot spot in a full run.
# The ranges are Unicode's own blocks (app/unicode_ranges.py), shared by every script test: the kanji
# range used to stop at U+9FAF, so a word or card in CJK Extension A / B, the compatibility
# ideographs or 〇 held no Japanese or Chinese at all.
_JA_TARGET_RE = re.compile(f'[{KANA}{HAN}]')    # Hiragana + Katakana + Kanji
_ZH_TARGET_RE = re.compile(f'[{HAN}]')          # any CJK ideograph
# A kana LETTER: a Chinese token holding one is Japanese. Never the kana block's ・ — Chinese writes a
# foreign name with it (约翰・列侬) — or ー.
_KANA_LETTER_RE = re.compile(f'[{KANA_LETTERS}]')


def has_target_language(text, language='ja'):
    if language == 'ja':
        pattern = _JA_TARGET_RE
    elif language == 'zh':
        # Japanese also uses Hanzi but usually mixed with Kana; pure Chinese is Hanzi + punctuation.
        # This check basically asks: "Is there any CJK character?"
        pattern = _ZH_TARGET_RE
    else:
        return False
    if pattern.search(text):
        return True
    # The language in another form is still the language: a line in half-width katakana (ｷﾐ｡), a Kangxi
    # radical (⽅) — so ask again of the text as every tagger reads it (§ What the tagger reads). The ranges
    # stay the blocks' own; only a text with no match at all pays for the second look.
    read, at = tagger_text(text)
    return at is not None and bool(pattern.search(read))

# Terminators a subtitle line may already end with. Includes the HALFWIDTH ｡ / ！ / ？, which anime
# subs use throughout — treating those as "unterminated" appended a second, redundant '。' and left
# the ugly '｡。' pairs that showed up in example sentences.
_CUE_TERMINATORS = '。｡．！？!?！？'

# Continuation markers. A cue ending in one of these is explicitly saying "this sentence runs into
# the next cue", so the right move is to drop the arrow and let the two cues JOIN — rather than
# terminating there (which strands a fragment like 'our final objective is…').
#
# ― (U+2015 HORIZONTAL BAR) and — (U+2014 EM DASH) are Netflix's continuation markers, where the
# fansub convention is an arrow. Measured on 4,200 real Netflix cues: 3.4% end in a dash, and every
# one of them was being terminated mid-clause into a fragment. They are only ever consulted at the
# END of a cue, so a leading speech dash (—そうだね) is untouched. ➨ is the broadcast captions' arrow
# (a broadcast .ja.ass: 35 sentences of one episode were closed mid-clause as …のは➨。).
_CUE_CONTINUATIONS = '➡➨→⇒➔►―—'

# A comma is a pause INSIDE a sentence (UAX #29 SContinue; 逗号 / 読点): a cue ending in one runs on into
# the next, the comma kept as text — 我觉得， + 他不会来 read 我觉得，。 before. A semicolon too: it joins the clauses
# of one sentence (UAX #29 SContinue; 分号, GB/T 15834-2011) — 我买了书； + 他买了笔。 read 我买了书；。 before.
_CUE_COMMAS = '、，,､；;'

# A cue that ends in an ellipsis has ended — the subtitle's own mark of speech trailing off — but … is
# no sentence end inside running text (it is as often a pause), so the cue gains no 。: its end is marked with a
# line break, which every reader takes as the end of a sentence, and the sentence stays a verbatim piece
# of its file (12,530 .srt cues of the library read …。 before).
_CUE_ELLIPSES = '…‥'


def close_cue(block_text):
    """Finish one subtitle cue's text for concatenation with the next.

    Returns the text terminated with '。' when the cue really ends, with a line break when it ends in
    an ellipsis, or left open when it continues into the following cue (arrow removed, comma kept).
    A terminator is looked for past closing brackets and quotes: 「行くぞ。」 has ended (UAX #29 SB9)."""
    block_text = (block_text or '').strip()
    if not block_text:
        return ''
    if block_text[-1] in _CUE_CONTINUATIONS:
        return block_text.rstrip(_CUE_CONTINUATIONS).rstrip()
    if block_text[-1] in _CUE_COMMAS:
        return block_text
    last = len(block_text) - 1
    while last > 0 and unicodedata.category(block_text[last]) in ('Pe', 'Pf'):
        last -= 1
    if block_text[last] in _CUE_ELLIPSES:
        return block_text + '\n'
    if block_text[last] not in _CUE_TERMINATORS:
        return block_text + '。'
    return block_text


# A caption's lines are read as CSS Text 3 reads a line break in running text (its segment break rules): nothing
# between two East Asian wide characters (width F, W or H, and not Hangul) — 我觉得 / 他不会来 is 我觉得他不会来, not
# 我觉得 他不会来 — and a space elsewhere (我买了 / T恤). Japanese keeps the space: the tagger reads it as the word
# boundary the subtitler broke the line at, and the sentence it shows drops it — the same text.
_HANGUL_RE = re.compile('[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff\uffa0-\uffdc]')


def _wide(ch):
    return unicodedata.east_asian_width(ch) in ("F", "W", "H") and not _HANGUL_RE.match(ch)


def _join_lines(lines, language='ja'):
    """A caption's `lines` — cleaned, none empty — as one text (§ above)."""
    if language == 'ja' or not lines:
        return " ".join(lines)
    text = lines[0]
    for line in lines[1:]:
        text += line if _wide(text[-1]) and _wide(line[0]) else " " + line
    return text


def _captions(events, language='ja'):
    """Each caption's text, closed (close_cue), from an .ass file's `events` — (timing, colour, text) in the
    file's order. Consecutive events with one timing — one start, one end — are on screen together: the
    lines of one caption, read as one cue like an .srt cue's two lines (a broadcast .ja.ass writes
    《門番は城への侵入者を / 厳しく取り調べた》 as two events; each was closed with 。 mid-clause) — one caption
    per colour: Japanese TV captions (字幕放送) tell speakers apart by colour, so two colours on screen at once
    are two people speaking (え…養父様を？ in yellow, うむ。 in white; in the library every pair of events with
    one timing and two colours is two speakers), each speaker's lines in the file's order. An .srt
    is not read this way: its cue IS the caption, and two cues with one timing are two captions shown
    at once — Netflix writes two speakers talking together so (the 五等分の花嫁 sample: （風太郎）あれは
    てめえが薬を… / （二乃）フフフフ…)."""
    screen, shown = {}, None                        # colour -> the texts in it, of the events on screen together
    for timing, colour, text in events:
        if screen and timing != shown:
            yield from (close_cue(_join_lines(texts, language)) for texts in screen.values())
            screen = {}
        screen.setdefault(colour, []).append(text)
        shown = timing
    yield from (close_cue(_join_lines(texts, language)) for texts in screen.values())


_OPEN_BRACKETS = '(（'
_CLOSE_BRACKETS = ')）'


def _strip_bracketed(text):
    """Remove balanced parenthesised groups — ASCII or fullwidth, however deeply nested.

    Replaces a non-greedy `[\\(（].*?[\\)）]`, which cannot count and so mis-handles the single most
    common shape in Netflix subtitles: a speaker label whose name carries furigana,
    `（石崎(いしざき)）`. The lazy match stops at the INNER `)`, removes `（石崎(いしざき)` and leaves
    an orphan `）` at the head of the line — which then reached the learner in example sentences and
    in every export.

    Two deliberate asymmetries:

    * An unmatched CLOSER is dropped. It is precisely the residue this function exists to prevent,
      and a lone `）` is never content.
    * An unmatched OPENER keeps the text after it. Deleting to end-of-line would silently swallow
      real dialogue whenever a cue contains a stray `（`; the old regex left such text alone, and
      losing subtitle text is a far worse failure than keeping one stray bracket.
    """
    out = []
    starts = []                       # output offsets where each still-open group began
    for ch in text:
        if ch in _OPEN_BRACKETS:
            starts.append(len(out))
            out.append(ch)            # provisional — removed if this group turns out to close
        elif ch in _CLOSE_BRACKETS:
            if starts:
                del out[starts.pop():]    # drop the whole balanced group, innermost first
            # else: orphan closer, drop it
        else:
            out.append(ch)
    return ''.join(out)


# SubRip's markup is HTML-style tags — <b> <i> <u> <s> and <font color="#ffff00" face=… size=…>, each closed by
# its </…> — and a tag's name starts with a Latin letter, which is no Japanese or Chinese text. (The Amazon
# subtitles in the library wrap every line in <b>: 4,638 pairs, 3,050 sentences.)
_SUBRIP_TAG_RE = re.compile(r'</?[A-Za-z][^<>]*>')

# ASS's escapes in an event's text: \N a forced line break, \n a soft one, \h a hard space (the ASS / SSA spec).
_ASS_BREAK_RE = re.compile(r'\\[Nn]')
_ASS_ESCAPE_RE = re.compile(r'\\[Nnh]')

# ASS override blocks ({\pos(10,20)}, {\an8}, {\c&H00FFFF00&}) style the text around them. With \p1 — any \p
# scale above 0 — what follows a block is a vector drawing (m 0 0 l 100 0 …) until \p0: the spec's drawing mode.
_ASS_BLOCK_RE = re.compile(r'\{[^}]*\}')
_ASS_DRAWING_RE = re.compile(r'\\p(\d+)')

# Karaoke timing (\k, \K, \kf, \ko: each syllable's duration) marks an event as sung — an OP / ED the file itself
# marks as song, repeated every episode. Decided 2026-09-27: skip only what the file marks as song;
# a ♪ line is dialogue and a sign is content, so both stay. (A style's name is the subtitler's free text, not
# the format's, so an OP whose lines carry no karaoke timing still counts.)
_ASS_KARAOKE_RE = re.compile(r'\{[^}]*\\(?:kf|ko|k|K)\d')

# Captions write what is heard but not said in square brackets — [音楽] [拍手] [笑い] (YouTube's captions), [無線]
# 'over the radio', ［拍手］ — the SDH convention, as a subtitle's parentheses hold its sounds and labels.
_SOUND_CUE_RE = re.compile(r'\[[^\[\]\n]*\]|［[^［］\n]*］')

# A caption names who speaks with Name + a colon at the start of the line (アサ：…, 田中:…), or just inside the
# voice-over bracket that opens it (⸨アサ：…⸩, 《田中:…》 — Unicode's open punctuation; the bracket stays, it is
# the line's). A name holds no hiragana: Japanese grammar — particles, endings — is written in hiragana, so a colon
# after a clause (理由は簡単：…) is speech and stays. Chinese has no such tell (他说：… is speech): Japanese only.
_SPEAKER_LABEL_RE = re.compile(r'(\W?)(?:(?![\u3040-\u309F])[^\W\d_]|[・･])+[:：](?!//)\s*')


def _strip_speaker_label(line):
    label = _SPEAKER_LABEL_RE.match(line)
    if label is None or (label.group(1) and unicodedata.category(label.group(1)) != 'Ps'):
        return line
    return label.group(1) + line[label.end():]


def clean_subtitle_text(text, language='ja'):
    """One subtitle line as speech: the format's markup removed, the words kept whatever their script.

    Latin letters and digits are part of what a line says — 30階, iPhoneを買った, No.６, T恤, 我有2个苹果 —
    so only markup goes: ASS override blocks and escapes, SubRip's tags, the parenthesised groups (labels,
    readings, sounds), sound cues in square brackets, a leading dialogue dash or >, and (Japanese)
    a speaker's Name： label. What is left in Latin script is still never counted — analyzer.main (and the
    Chinese tokenizer) count a token only when it holds the language's own script — and a line with none of it
    (an English translation line) never gets here (the callers test has_target_language first). The cleaner
    used to strip every ASCII letter and digit instead (to 2026-09): 30階の中野さん read 階の中野さん,
    <i>…</i> left <>…</>, T恤 became 恤, and the number guard lost its numbers."""
    # ASS override tags like {\pos(10,20)}, and SubRip's {b} / {\an8} (players read ASS's tags in .srt too)
    text = _ASS_BLOCK_RE.sub('', text)
    text = _SUBRIP_TAG_RE.sub('', text)
    text = _ASS_ESCAPE_RE.sub(' ', text)

    # Remove speaker labels and furigana in parens (nested-aware — see _strip_bracketed)
    # Decided 2026-09-27: every group goes, a thought line with them, until a library shows one.
    text = _strip_bracketed(text)
    text = _SOUND_CUE_RE.sub('', text)

    # Strip common subtitle noise like - or > if they are alone at start
    text = re.sub(r'^[ \->]+', '', text)
    if language == 'ja':
        text = _strip_speaker_label(text)
    return text.strip()


def _ass_event_text(text):
    """An ASS event's Text field without its override blocks — and without the drawing a \\p block starts."""
    out, drawing, pos = [], False, 0
    for block in _ASS_BLOCK_RE.finditer(text):
        if not drawing:
            out.append(text[pos:block.start()])
        scales = _ASS_DRAWING_RE.findall(block.group())
        if scales:
            drawing = int(scales[-1]) > 0
        pos = block.end()
    if not drawing:
        out.append(text[pos:])
    return ''.join(out)


def ass_dialogue_text(text, language='ja'):
    """One ASS / SSA Dialogue event's Text as speech, or '' — read like an .srt cue: its lines (split at the
    \\N / \\n line breaks) each kept only when they hold the language's script and cleaned, then joined
    as extract_text joins a cue's lines (_join_lines). A sung event (karaoke timing) is no speech."""
    if _ASS_KARAOKE_RE.search(text):
        return ""
    lines = _ASS_BREAK_RE.split(_ass_event_text(text))
    kept = [clean_subtitle_text(line, language) for line in lines if has_target_language(line, language)]
    return _join_lines([line for line in kept if line], language)


# The colour a Japanese TV caption tells its speaker by (_captions): an ASS event's text is drawn in its style's
# PrimaryColour — &H00BBGGRR (ASS), a decimal number (SSA) — until an override block's \c / \1c sets another or \r
# resets it to a style's.
_ASS_COLOUR_RE = re.compile(r'\\(?:1?c(&H[0-9A-Fa-f]+)|r([^\\}]*))')


def _ass_colour_value(value):
    """A colour as ASS or SSA writes it, as BBGGRR."""
    value = value.strip().rstrip('&')
    try:
        number = int(value[2:], 16) if value[:2].upper() == '&H' else int(value)
    except ValueError:
        return value
    return format(number & 0xFFFFFF, '06X')


def _ass_colour(text, colour, colours):
    """The colour an event's first visible character is drawn in: `colour` (its style's) as the override blocks
    before that character change it (§ above; `colours` holds each style's)."""
    style_colour, pos = colour, 0
    for block in _ASS_BLOCK_RE.finditer(text):
        if _ASS_ESCAPE_RE.sub('', text[pos:block.start()]).strip():
            break
        for value, reset in _ASS_COLOUR_RE.findall(block.group()):
            colour = _ass_colour_value(value) if value else colours.get(reset.strip(), style_colour)
        pos = block.end()
    return colour


def parse_ass(file_path, language='ja'):
    try:
        content = read_text(file_path, language)    # the file's own encoding (path_utils.read_text)
    except Exception as e:
        print(f"Error reading ASS/SSA {file_path}: {e}")
        return ""
    # TV captions read as card-making reads them (ENGINE_REVISION 31): their reading rows dropped, a caption's rows
    # one event — the same lines Connect's pick and Anki Miner read. Arrows stay: close_cue reads them as "runs on"
    from app import caption_clean
    content = caption_clean.clean(content, arrows=False)

    lines = content.splitlines()
    events_section = False
    format_line = None
    text_index = 9 # Default for standard ASS
    start_index, end_index, style_index = 1, 2, 3
    colours, colour_index = {}, 3   # each style's PrimaryColour (§ above), and where a Style line holds it
    
    events = []
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        if line == '[Events]':
            events_section = True
            continue
        
        if events_section:
            if line.startswith('Format:'):
                format_line = line[7:].split(',')
                format_line = [f.strip() for f in format_line]
                try:
                    text_index = format_line.index('Text')
                    start_index, end_index = format_line.index('Start'), format_line.index('End')
                    style_index = format_line.index('Style')
                except ValueError:
                    pass
                continue
            
            if line.startswith('Dialogue:'):
                # Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
                # Split by comma but only up to text_index
                comma_parts = line.split(',', text_index)
                if len(comma_parts) > text_index:
                    cleaned = ass_dialogue_text(comma_parts[text_index], language)
                    if cleaned:
                        colour = _ass_colour(comma_parts[text_index], colours.get(comma_parts[style_index].strip(), ''),
                                             colours)
                        events.append(((comma_parts[start_index].strip(), comma_parts[end_index].strip()),
                                       colour, cleaned))
        elif line.startswith('Format:'):          # [V4+ Styles] / [V4 Styles]
            fields = [f.strip() for f in line[7:].split(',')]
            if 'PrimaryColour' in fields:
                colour_index = fields.index('PrimaryColour')
        elif line.startswith('Style:'):
            fields = line[6:].split(',')
            if len(fields) > colour_index:
                colours[fields[0].strip()] = _ass_colour_value(fields[colour_index])

    return " ".join(caption for caption in _captions(events, language) if caption)


# --- what a text file's own format writes around its text ------------------------------------------------------ #
# The transcript downloader's output (modules/youtube_downloader/downloader.build_text): six header lines — the
# title, 'channel | date | duration', 'Captions: <language> (<kind>)', the URL, a blank line, a rule of 60 dashes
# — then the cues from the next line on, joined by spaces or, with timestamps kept, one per line as '[00:01:02]
# text' (the time as the cue's timing line wrote it: clean_vtt_cues). 93 of 原作's 160 uses came from headers.
_TRANSCRIPT_RULE = "-" * 60
_TRANSCRIPT_TIME_RE = re.compile(r'^\[(?:\d+:)?\d{2}:\d{2}\] ', re.M)
_CAPTION_KIND_RE = re.compile(r'\(([^()]*)\)$')
# The header's caption kinds that no person wrote, as the transcript downloader names them: YouTube's own speech
# recognition, and its machine translation of another language's captions. The recognizer misspells a word the same
# way every time, so its text never tells the library what a story's own words are (names.Record).
AUTO_CAPTIONS = frozenset(("native auto", "auto-translated"))

# Markdown (CommonMark) marks structure and emphasis with ASCII punctuation — # headings, > quotes, - / 1. list
# items, **strong** / *emphasis* / _emphasis_ (not inside a word), `code`, ~~strike~~, [text](url) links and
# ![alt](src) images — markup, not text.
_MD_BLOCK_RE = re.compile(r'^[ \t]{0,3}(?:#{1,6}(?=[ \t]|$)|(?:>[ \t]?)+|(?:[-*+]|\d{1,9}[.)])(?=[ \t]))[ \t]*',
                          re.M)
_MD_LINK_RE = re.compile(r'!?\[([^\[\]\n]*)\]\([^()\n]*\)')
_MD_INLINE_RE = re.compile(r'\*+|`+|~~|(?<![^\W_])_+|_+(?![^\W_])')

# Aozora Bunko's input notation (青空文庫 注記一覧; the plain-text ruby of 小説家になろう and カクヨム too): 《…》
# right after kanji is its reading (漢字《かんじ》), ｜ marks where the ruby's base starts when it is not a run of
# kanji (｜夏目漱石《なつめそうせき》), ［＃…］ is the transcriber's note (外字, 傍点, the source edition's
# wording). A reading is kana, so 《…》 quoting a message (《直ちに着水せよ》) stays text. The file opens with a
# legend of that notation between two rules of dashes (【テキスト中に現れる記号について】《》：ルビ …) and ends with
# its colophon — 底本：, 初出：, 入力：, 校正：, the 青空文庫 notice — opening with the line 底本：.
_KANJI = '\u3005\u3006\u3007\u30f6\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f'
_RUBY_KANA = '\u3041-\u309f\u30a1-\u30ff'
_RUBY_BASE_RE = re.compile(rf'[|｜]([^|｜《》\n]+)《[{_RUBY_KANA}]+》')
_RUBY_RE = re.compile(rf'(?<=[{_KANJI}])《[{_RUBY_KANA}]+》')
_AOZORA_NOTE_RE = re.compile(r'［＃[^］\n]*］')
# Kana alone in parentheses right after kanji — 山田太郎(やまだ・たろう), 窮鼠（きゅうそ） — is by typographic habit that
# kanji's reading: ruby where a plain .txt has none (小説家になろう turns it into ruby in its own files). Read as text
# it is the same word counted again, often in pieces that are no word at all. A kanji's reading is written in
# hiragana; katakana after kanji is as often an aside naming who is meant or a loanword's gloss (彼（ケン）は,
# 複製（コピー）). So it is the learner's choice, settings.json logic.paren_readings: "hiragana" (the default) drops a
# hiragana group (with ・ ー) as a 《ruby》 is dropped, "any" a katakana one too, "off" keeps every group as text.
# Measured 2026-09-27 on 1,620 chapters of novels and non-fiction (.txt): 40 kana-only groups after kanji — 19
# readings, 6 glosses, 15 asides; the 16 in hiragana were 15 readings and one gloss, no aside; 4 of the 24 with
# katakana were readings.
PAREN_READINGS = {"hiragana": '\u3041-\u309f\u30fb\u30fc', "any": _RUBY_KANA, "off": ""}
_PAREN_READING_RES = {option: re.compile(rf'(?<=[{_KANJI}])[(（][{kana}]+[)）]')
                      for option, kana in PAREN_READINGS.items() if kana}
_AOZORA_LEGEND_RE = re.compile(r'^-{10,}\r?\n【テキスト中に現れる記号について】.*?^-{10,}\r?$', re.M | re.S)
_AOZORA_COLOPHON_RE = re.compile(r'^底本[：:]', re.M)

# Scripture apparatus. A cross-reference is a book's abbreviation, then chapter・verse — 1ニフ12・20－23,
# アル45・14: the citation form of Japanese scripture; a line of nothing but references is
# a chapter's footnotes (2,690 abbreviation tokens; ニフ was row #1 of the list). An abbreviation is katakana or
# kanji — a hiragana run is a clause.
_CITATION = r'\d*(?:(?![\u3040-\u309f])[^\W\d_]){1,6}\d+・\d+(?:[－\-–]\d+)?'
_CITATION_LINE_RE = re.compile(
    rf'^[ \t\u3000]*{_CITATION}(?:[ \t\u3000]*[、，,；;][ \t\u3000]*(?:{_CITATION}|\d+(?:[－\-–]\d+)?))*'
    r'[ \t\u3000\r]*$', re.M)
# Footnote marks: circled numbers (①–⑳, ㉑–㉟, ㊱–㊿ — Unicode's CIRCLED NUMBERs) tie a word to its note below the
# text, or number a list; never a word. UniDic reads ① as 一, and the mark changes the parse around it (①罪 → ザイ).
_CIRCLED_NUMBER_RE = re.compile('[①-⑳㉑-㉟㊱-㊿]')
# A verse number opens each verse's line (see _strip_verse_numbers).
_LEADING_NUMBER_RE = re.compile(r'[0-9０-９]+[ \u3000]?')

# What the reader removes from INSIDE a line. The report's source anchor lets these sit between a sentence's
# characters when it looks the sentence up in its file (static_html_generator.AnchorFinder._loose). A reading in
# parentheses is listed as any kana — what every paren_readings option removes, so a sentence is found whichever
# the learner chose (and one that kept its group simply matches it as written). Each piece must fit in one way at
# a place (end at its first closing mark), as each does: the anchor steps over them one piece at a time.
REMOVED_INLINE = '|'.join((rf'《[{_RUBY_KANA}]+》', rf'[(（][{_RUBY_KANA}]+[)）]', r'[|｜]', _AOZORA_NOTE_RE.pattern,
                           _CIRCLED_NUMBER_RE.pattern, _SOUND_CUE_RE.pattern, _SUBRIP_TAG_RE.pattern,
                           _ASS_BLOCK_RE.pattern))


def paren_readings(logic=None):
    """What kana in parentheses right after kanji is in a Japanese book, as `logic` (a settings.json logic block;
    default: this run's, LOGIC) sets it: "hiragana", "any" or "off" (see PAREN_READINGS). A missing or unknown value
    is the default."""
    default = settings_manager.DEFAULT_SETTINGS["logic"]["paren_readings"]
    option = (LOGIC if logic is None else logic).get("paren_readings", default)
    return option if option in PAREN_READINGS else default


def transcript_body(text):
    """The cues of a transcript the downloader wrote (its header gone), or None — any other text has no such
    header."""
    lines = text.split("\n", 6)
    if (len(lines) >= 6 and lines[2].startswith("Captions: ") and not lines[4].strip()
            and lines[5].strip() == _TRANSCRIPT_RULE):
        return lines[6] if len(lines) == 7 else ""
    return None


def caption_kind(text):
    """The kind of captions a transcript the downloader wrote names in its header — "manual", "native auto" or
    "auto-translated" (see AUTO_CAPTIONS) — or None: any other text has no such header."""
    if transcript_body(text) is None:
        return None
    kind = _CAPTION_KIND_RE.search(text.split("\n", 3)[2].strip())
    return kind.group(1) if kind else None


def _strip_verse_numbers(text):
    """A verse-numbered book's text without its verse numbers. The numbers count up line after line (1, 2, 3 …);
    glued to the verse they change its parse — 7わが子よ reads 7わ as a count (把 'bundles'), so わが is no 我が.
    Three or more lines in a row counting up by one are the book's numbering, and their numbers go before the
    text is read. A count that opens every line of such a run (1人目 / 2人目 / 3人目 — the same character after
    each number) is the text's own and stays, as does any number outside a run (3人で主に祈った。). What is shown
    is still tidied by strip_verse_number, for a number this doesn't see."""
    lines = text.split("\n")
    runs, run, previous = [], [], None
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        number = _LEADING_NUMBER_RE.match(line)
        n = int(number.group().strip()) if number and line[number.end():].strip() else None
        if n is not None and run and n == previous + 1:
            run.append((i, number.end()))
        else:
            if len(run) >= 3:
                runs.append(run)
            run = [(i, number.end())] if n is not None else []
        previous = n
    if len(run) >= 3:
        runs.append(run)
    for run in runs:
        if len({lines[i][end] for i, end in run}) > 1:
            for i, end in run:
                lines[i] = lines[i][end:]
    return "\n".join(lines)


def strip_text_conventions(text, language='ja', ext='.txt'):
    """A text file's content without what its format writes around the text: the downloader's header, its
    timestamps and the captions' sound cues; Markdown's markup (.md); and in Japanese books Aozora Bunko's ruby,
    notes and colophon, a reading in parentheses (as paren_readings() says) and a scripture's apparatus
    (references, footnote marks, verse numbers). The words and punctuation of the text itself are taken as
    written."""
    body = transcript_body(text)
    if body is not None:
        return _SOUND_CUE_RE.sub('', _TRANSCRIPT_TIME_RE.sub('', body))
    if ext == '.md':
        text = _MD_LINK_RE.sub(r'\1', _SUBRIP_TAG_RE.sub('', text))
        text = _MD_INLINE_RE.sub('', _MD_BLOCK_RE.sub('', text))
    if language != 'ja':
        return text
    colophon = _AOZORA_COLOPHON_RE.search(text)
    if colophon:
        text = text[:colophon.start()]
    text = _AOZORA_LEGEND_RE.sub('', text)
    text = _RUBY_RE.sub('', _RUBY_BASE_RE.sub(r'\1', _AOZORA_NOTE_RE.sub('', text)))
    readings = _PAREN_READING_RES.get(paren_readings())
    if readings:
        text = readings.sub('', text)
    text = _CIRCLED_NUMBER_RE.sub('', _CITATION_LINE_RE.sub('', text))
    return _strip_verse_numbers(text)


def extract_text(file_path, language='ja', facts=None):
    # Every format is decoded the one way (path_utils.read_text): a BOM names the encoding, else
    # strict UTF-8, else the language's Windows encodings (CP932; GB18030, Big5) — a CP932 subtitle,
    # a UTF-16 or GBK .txt contributed nothing before, silently.
    # `facts`, a dict, receives what the file's own format says about its text — "captions": the kind a downloaded
    # transcript's header names (caption_kind), or None — for the token store (names.Record); the text is the same.
    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    if ext == '.srt':
        try:
            import pysrt   # lazy: only reading a .srt subtitle file pays this import
            subs = pysrt.from_string(read_text(file_path, language))
            parts = []
            for sub in subs:
                # Filter out lines without Target characters
                lines = sub.text.splitlines()
                filtered_lines = []
                for l in lines:
                    if not has_target_language(l, language):
                        continue
                    
                    cleaned = clean_subtitle_text(l, language)
                    if cleaned:
                        filtered_lines.append(cleaned)

                if filtered_lines:
                    block_text = close_cue(_join_lines(filtered_lines, language))
                    if block_text:
                        parts.append(block_text)
            text = "".join(parts)
        except Exception as e:
            print(f"Error reading SRT {file_path}: {e}")
    elif ext in ['.ass', '.ssa']:
        text = parse_ass(file_path, language)
    else:
        text = read_text(file_path, language)

    if ext not in SUBTITLE_EXTENSIONS:
        if facts is not None:
            facts["captions"] = caption_kind(text)
        text = strip_text_conventions(text, language, ext)
    return text

def find_context_sentence(full_text, target_surface):
    sentences = re.split(r'([。！？\n])', full_text)
    current_sent = ""
    for part in sentences:
        current_sent += part
        if any(d in part for d in '。！？\n'):
            if target_surface in current_sent:
                return current_sent.strip()
            current_sent = ""
            
    idx = full_text.find(target_surface)
    if idx != -1:
        search_range = LOGIC.get("context", {}).get("search_range", 20)
        start = max(0, idx - search_range)
        end = min(len(full_text), idx + search_range)
        return "..." + full_text[start:end].replace("\n", " ") + "..."
    return ""

_SIMPLIFIED_SOURCES = {}    # file name -> the name group_sources lists it under: worked out once per name, not per word


def group_sources(source_list):
    """
    Groups similar filenames.
    Less picky: Removes trailing digits, brackets, etc.
    """
    if not source_list: return ""

    simplified_sources = []
    for s in source_list:
        simple = _SIMPLIFIED_SOURCES.get(s)
        if simple is not None:
            simplified_sources.append(simple)
            continue
        base = os.path.splitext(s)[0]

        # 1. Simplify CRC/Hash like [A1B2C3D4] or (1920x1080)
        # Remove standard CRC [8 chars hex]
        base = re.sub(r'\s*\[[0-9a-fA-F]{8}\]\s*$', '', base)

        # 2. Heuristic: Remove trailing number sequence (likely episode/volume number)
        # Matches: Optional separators + Digits + Optional separators + End
        # This keeps "861" from "861_1" (removes _1)
        # But "861" -> Removes "861" -> Becomes empty -> Reverts to "861" below.
        simple = re.sub(r'[\s_\-\(\)\[\]]*\d+[\s_\-\(\)\[\]]*$', '', base)

        if not simple:
             simple = base

        _SIMPLIFIED_SOURCES[s] = simple
        simplified_sources.append(simple)
    
    groups = Counter(simplified_sources)
    result_parts = []
    # Sort groups by count desc, then name? Or just name. 
    # Counter.items() is arbitrary order. Sort for consistency.
    sorted_groups = sorted(groups.items(), key=lambda x: (-x[1], x[0]))
    
    for key, count in sorted_groups:
        if count > 1:
            result_parts.append(f"{key} ({count})")
        else:
            result_parts.append(key)
            
    return ", ".join(result_parts)

# Volume suffixes: "Honzuki v1" / "Honzuki_2" / "Honzuki - 3" are one work, not three. Same
# grouping the Immersion Architect uses to build its reading queues, so a series means the same
# thing in both places.
_VOLUME_SUFFIX_RE = re.compile(r"[_Vv\s\-]*\d+$")


def _series_name(file_path, data_dir):
    """Which WORK a content file belongs to — the folder under its tier, volumes merged.

    Used for dispersion: a word confined to one work is that story's vocabulary (a character, a
    place, a piece of jargon), while genuine reading vocabulary turns up across many. Grouping by
    file would not do — a light novel is hundreds of chapter files, so a character name looks
    beautifully "dispersed" while appearing in exactly one book.

    Loose files directly under a tier are each their own work, which is the honest reading: we
    have no evidence they belong together.
    """
    try:
        rel = os.path.relpath(file_path, data_dir).replace("\\", "/")
    except ValueError:      # different drive on Windows
        return os.path.basename(file_path)
    parts = [p for p in rel.split("/") if p]
    if len(parts) < 2:
        return rel                      # shouldn't happen; degrade to the path itself
    if len(parts) == 2:
        return parts[1]                 # loose file sitting directly in the tier folder
    return _VOLUME_SUFFIX_RE.sub("", parts[1]) or parts[1]


def _spelling_alias(word):
    """The spelling a frequency list is likely to store for this lemma, or None.

    Unidic gives us ORTHOGRAPHIC lemmas — 為る, 矢張り, 其れ, 呉れる — while every frequency list
    stores the ordinary spelling (する, やっぱり, それ, くれる). Nothing bridged the two, so the most
    common verb in the language reported as "Outside": 為る accounts for tens of thousands of tokens
    in a real library and matched nothing. The bridge is precomputed at build time (it depends only
    on unidic + the reference corpora, both fixed then), so this costs a dict lookup.

    Degrades to None when the generated table is absent — the app still runs, tiers just revert to
    the old behaviour.
    """
    try:
        from app import reference_data
        return reference_data.aliases().get(word)
    except Exception:
        return None


def get_tier_label(word, freq_data):
    """
    Get tier labels for a word from all frequency lists.
    Returns a list of (source_name, tier_number) tuples.
    Example: [("Novel", "1"), ("Anime", "2")]
    Empty list means word is not in any frequency list (Outside).
    """
    tiers_found = []
    alias = None   # resolved lazily: only words that MISS need the bridge

    # Check all frequency lists and collect all tiers
    for source_name in sorted(freq_data.keys()):
        rank = freq_data[source_name].get(word)
        if rank is None:
            # A direct hit always wins over the alias. 呉れる is present in some lists at its own
            # (rare) rank, and its alias くれる is far more common — crediting the alias there would
            # overstate how common the word we actually matched is.
            if alias is None:
                alias = _spelling_alias(word) or ""
            if alias:
                rank = freq_data[source_name].get(alias)
        if rank is not None:
            tier = get_tier_from_rank(rank)
            if tier != "Outside":
                tiers_found.append((source_name, tier))

    return tiers_found


# --- Content Manager sidecars (right-sized reads of word_stats.json) ----------------------------- #
# word_stats.json is large (candidate_contexts dominate) but the Content Manager only needs two tiny
# slices: which files were analyzed, and per-file its words. We derive those into small sidecars so a
# big library never freezes the GUI. Writes are ATOMIC (temp + os.replace) so a concurrent reader in
# the Content Manager process never sees a half-written file. word_stats.json is written BEFORE the
# sidecars, so a sidecar is always at least as new as it — the readers use that mtime rule to ignore a
# stale sidecar left by an interrupted run and fall back to word_stats.json.
def _write_sidecars(results_dir, stats):
    """Derive analyzed_files.json (list of basenames) + file_words.json ({basename: [lemmas]}) from a
    word_stats-shaped dict and write them atomically. Best-effort: returns True on success."""
    analyzed = set()
    file_words = {}
    for key, data in stats.items():
        lemma = key.split("|")[0]
        for src in (data.get("sources", []) if isinstance(data, dict) else []):
            analyzed.add(src)
            file_words.setdefault(src, []).append(lemma)

    def _atomic_dump(name, obj):
        final = os.path.join(results_dir, name)
        tmp = final + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps(obj, ensure_ascii=False))
        os.replace(tmp, final)   # atomic on the same volume

    _atomic_dump("analyzed_files.json", sorted(analyzed))
    _atomic_dump("file_words.json", file_words)
    return len(analyzed)


def _backfill_sidecars(results_dir):
    """Skip-path safety net: if a completed run is being reused but the sidecars are missing or older
    than word_stats.json (e.g. first launch after updating, or an interrupted prior write), rebuild
    them from word_stats.json so the Content Manager gets the fast path without a fresh analysis.
    One-time cost (a single word_stats.json read); no-op once the sidecars are present and current."""
    ws = os.path.join(results_dir, "word_stats.json")
    if not os.path.exists(ws):
        return
    af = os.path.join(results_dir, "analyzed_files.json")
    fw = os.path.join(results_dir, "file_words.json")
    ws_m = os.path.getmtime(ws)
    fresh = (os.path.exists(af) and os.path.exists(fw)
             and os.path.getmtime(af) >= ws_m and os.path.getmtime(fw) >= ws_m)
    if fresh:
        return
    try:
        with open(ws, 'r', encoding='utf-8') as f:
            stats = json.load(f)
        n = _write_sidecars(results_dir, stats)
        print(f"Backfilled Content Manager sidecars ({n} files).")
    except Exception as e:
        print(f"Warning: could not backfill sidecars: {e}")


# --- The plan file (results/plan.json.gz; E1.1-fast-replan/01-plan-file.md) ----------------------------------------- #
# Every full Generate writes what a re-plan needs to recompute the order's columns — Score, the tier counts, first
# places, the priority order, the progressive list, Orth and Forms where spellings tie — for ANY order of the same
# files, without the tokenizer: each file's uses of each list word as the aggregation counted them, in the order first
# counted, and what the progressive pass reads of each file. Nothing reads it unless the fast re-plan's preview is on
# (E1.3, E3.1). Written last, just before the run's stamp, atomically: a run that dies between the two leaves a plan
# whose run_signature no stamp matches. Never fails a Generate.
PLAN_FILE = "plan.json.gz"
PLAN_FORMAT = 1
_PLAN_CHUNK = 2000              # table rows per line: no one line's decode holds a reader's interpreter long
_PLAN_TIERS = {"HighPriority": "now", "LowPriority": "soon", "GoalContent": "goal"}


def _plan_file(records, word_stats, phrase_spelled, phrase_stats):
    """A file's part of the plan, from the aggregation's records: ({key: its counted uses here}, the words' unusual
    spellings here, the phrases')."""
    uses, spelled = {}, {}
    for key, record in records.items():
        uses[key] = record[1]
        if record[2] is not None:
            spelled[key] = record[2]
    return (uses, _unusual_spellings(spelled, word_stats),
            _unusual_spellings(phrase_spelled, phrase_stats) if phrase_spelled else None)


def _unusual_spellings(spelled, entries):
    """`spelled` without the words met here only as they were first met anywhere (their Counters' first keys) — what
    nearly every word is: the plan file implies those (`_plan_spellings`). A value is (spelling, surface) when the word
    was met here in one, else [{spelling: None, …}, {surface: None, …}], each in the order met (main()'s word site)."""
    out = {}
    for key, met in spelled.items():
        if type(met) is tuple:
            entry = entries[key]
            if met[0] == next(iter(entry["orths"])) and met[1] == next(iter(entry["surfaces"])):
                continue
        out[key] = met
    return out


def _spelling_ties(lemma, orths, surfaces):
    """(the spellings, the surfaces) whose order of first meeting can decide `Orth` or `Forms` (K108): spellings tied
    at the top count (`_display_orth`: the first met wins a tie), and every surface of a count shared with another one
    near enough the front to reach `Forms` (`_display_forms`: equal counts keep the order met; one place more, for the
    spelling shown, which `Forms` leaves out). Both empty: the order of the files can't change either column."""
    candidates = _said_with_to(orths) or orths
    top = max([n for o, n in candidates.items() if o] or [0])
    tied_orths = [o for o, n in candidates.items() if o and n == top]
    if len(tied_orths) < 2:
        tied_orths = []
    tied_surfaces = []
    ranked = sorted(((n, s) for s, n in surfaces.items() if s and s != lemma), key=lambda ns: -ns[0])
    place = 0
    while place < len(ranked) and place <= FORMS_LIMIT:
        end = place
        while end < len(ranked) and ranked[end][0] == ranked[place][0]:
            end += 1
        if end - place > 1:
            tied_surfaces.extend(s for _n, s in ranked[place:end])
        place = end
    return tied_orths, tied_surfaces


def _plan_spellings(key, k, word_uses, unusual, entry, ties):
    """[k, the tied spellings met in this file, the tied surfaces] in the order met here, or None."""
    met = unusual.get(key) if unusual else None
    if met is None:
        met = (next(iter(entry["orths"])), next(iter(entry["surfaces"]))) if word_uses else None
        if met is None:
            return None
    tied_orths, tied_surfaces = ties
    orths = [o for o in ([met[0]] if type(met) is tuple else met[0]) if o in tied_orths]
    surfaces = [s for s in ([met[1]] if type(met) is tuple else met[1]) if s in tied_surfaces]
    return [k, orths, surfaces] if orths or surfaces else None


def plan_lines(run):
    """The plan file's lines, each one JSON text (E1.1 01 §2): the header, then the tables in chunks, then one line per
    file in the run's order. `run`: what main() still holds when every output is written (names below). Raises
    ValueError when the per-file uses don't add up to each word's `Occurrences` — then no plan is written."""
    word_stats, phrase_keys = run["word_stats"], run["phrase_keys"]
    floor, data_dir = run["floor"], run["data_dir"]
    found_files, plan_files = run["found_files"], run["plan_files"]
    phrase_set = run["phrase_set"]
    phrase_key_of = {index: key for key, index in phrase_keys.items()}     # the phrase whose entry is the row

    keys = run["keys"]
    index = {key: k for k, key in enumerate(keys)}
    # Each phrase met: (its row's k when its entry is the row's, its row's k) — once per phrase (`_phrase_rows`).
    phrase_rows = {}

    valid = run["valid_lrs"]
    listed = {(r["Word"], r["Reading"]): r for r in run["output_rows"]
              if valid is None or (r["Word"], r["Reading"]) in valid}
    n_contexts = run["max_contexts"]
    rows, ties, tied = [], [], {}
    for k, key in enumerate(keys):
        entry = word_stats[key]
        is_phrase = key in phrase_keys
        r = listed.get(key)
        rows.append(None if r is None else [
            r["Tier"], _plan_tier(key[0], run["freq_data"]) if is_phrase else None, r["Modality"], r["Sources"],
            r["Orth"], r["Forms"],
            [r.get(f"{c} {i}", "") for i in range(1, n_contexts + 1) for c in ("Context", "Src")]])
        found = _spelling_ties(key[0], entry["orths"], entry["surfaces"])
        if found[0] or found[1]:
            tied[key] = found
            ties.append([k, dict(entry["orths"]), dict(entry["surfaces"]),
                         {o: _plan_tier(o, run["freq_data"]) for o in found[0]} if is_phrase else None])

    library = run["library"] or {}
    header = {
        "format": PLAN_FORMAT, "language": run["language"], "engine": run["engine"],
        "run_signature": run["run_signature"], "order_free_signature": run["order_free_signature"],
        "store": {name: library.get(name) for name in ("epoch", "order_version", "pins_version")},
        "weights": dict(zip(("now", "soon", "goal"), run["weights"])),
        "floor": floor, "total_tokens": run["total_tokens"], "phrase_rows": run["phrase_rows"],
        "target_coverage": run["target_coverage"], "only_i_plus_one": run["only_i_plus_one"],
        "max_contexts": n_contexts, "files": len(found_files), "keys": len(keys),
        "shared_phrases": sorted(index[key] for key in run["shared_phrases"] if key in index),
        # Each part of the order-free signature on its own, so a re-plan can name what moved since (E1.3: the known
        # words, the word lists, files only removed — or anything else, a Generate first).
        "order_free_parts": plan_rules.part_digests(run["signature_parts"]),
    }
    yield _plan_json(header)
    prefix = os.path.join(data_dir, "")
    signed = run["signature_parts"]["files"]
    if [entry[0] for entry in signed] != [f[0] for f in found_files]:
        raise ValueError("the signature's files aren't the run's")
    # [rel_path, tier, the file's own digest]: the digest tells a re-plan which files are still the same (E1.3).
    files = [[(f[0][len(prefix):] if f[0].startswith(prefix) else os.path.relpath(f[0], data_dir)).replace("\\", "/"),
              _PLAN_TIERS.get(f[1], "goal"), plan_rules.file_digest(entry)] for f, entry in zip(found_files, signed)]
    for name, table in (("files", files),
                        ("keys", [[key[0], key[1], key in phrase_keys, key in run["halved"],
                                   word_stats[key]["total_count"]] for key in keys]),
                        ("rows", rows), ("ties", ties)):
        for start in range(0, len(table), _PLAN_CHUNK):
            yield _plan_json({name: table[start:start + _PLAN_CHUNK]})

    counted = [0] * len(keys)
    for f, (file_path, _label, _weight, _type) in enumerate(found_files):
        uses, unusual, phrase_unusual = plan_files[f]
        credits = run["credit_cache"].get(file_path) or {}
        main, spellings = [], []
        for key, n in uses.items():
            k = index.get(key)
            if k is None:
                continue
            main += (k, n)
            counted[k] += n
            if key in tied:
                found = _plan_spellings(key, k, n > credits.get(key, 0), unusual, word_stats[key], tied[key])
                if found:
                    spellings.append(found)
        phrases, met = [], []           # the row's entry's uses; every phrase use on a row (the progressive pass's)
        for phrase, n in (run["phrase_cache"].get(file_path) or {}).items():
            row_of = phrase_rows.get(phrase) or _phrase_rows(phrase_rows, phrase, phrase_set, phrase_keys,
                                                             phrase_key_of, index)
            if row_of[1] is not None:
                met += (row_of[1], n)
            k = row_of[0]
            if k is None:
                continue
            key = keys[k]
            phrases += (k, n)
            counted[k] += n
            if key in tied:
                found = _plan_spellings(phrase, k, True, phrase_unusual, word_stats[key], tied[key])
                if found:
                    spellings.append(found)
        yield _plan_json({"f": f, "main": main, "ph": phrases, "sp": spellings,
                          "prog": _plan_progressive(run, f, file_path, index, met)})
    for k, key in enumerate(keys):
        if counted[k] != word_stats[key]["total_count"]:
            raise ValueError(f"the uses of {key} add up to {counted[k]}, not {word_stats[key]['total_count']}")


def _phrase_rows(phrase_rows, phrase, phrase_set, phrase_keys, phrase_key_of, index):
    """(the row's k when this phrase's entry holds the row, else None; the k of the phrase row its words and reading
    name, else None — never a word's row of the same Word and Reading, which the progressive pass never gives a phrase's
    uses) — for `plan_lines`' cache."""
    entry = phrase_set.entry(phrase)
    key = (entry.word, entry.reading)
    row_of = phrase_rows[phrase] = (index.get(phrase_key_of.get(phrase)),
                                    index.get(key) if key in phrase_keys else None)
    return row_of


def _plan_progressive(run, f, file_path, index, phrases):
    """[Total Count, the baseline known, tokens, phrase-given, credits, phrases, siblings]: what the progressive pass
    reads of a file, in its own order. Total Count, the baseline, tokens [k, count after pieces, …] for the list words
    met here, phrase-given [k, uses given to a phrase, …] (only where any) and siblings [[lemma, n], …] — the other
    words of a list word's lemma, known here once that lemma is learned — as the pass read them (`prog`); credits
    [k, n, …] for the list words met inside a rare compound; phrases [k, n, …] per phrase on a row (`plan_lines`)."""
    total, baseline, tokens, bound, siblings = run["prog"][f]
    credits = []
    for key, n in (run["credit_cache"].get(file_path) or {}).items():
        k = index.get(key)
        if k is not None:
            credits += (k, n)
    return [total, baseline, tokens, [x for k, n in bound.items() for x in (k, n)], credits, phrases,
            [[lemma, n] for lemma, n in siblings.items()]]


def _plan_tier(text, freq_data):
    tier_labels = get_tier_label(text, freq_data)
    return ";".join([f"{source}:{tier}" for source, tier in tier_labels]) if tier_labels else "Outside"


def _plan_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def write_plan_file(results_dir, lines):
    """Write the plan file atomically: a temp file, gzip level 3, flushed and fsynced, read back whole (the gzip CRC,
    and the header's JSON — every line is `json.dumps`' own), then `os.replace`. On any error the temp is removed, the
    old plan stays as it was, and the error is raised for the caller to log. Returns the bytes written."""
    import gzip
    import time
    path = os.path.join(results_dir, PLAN_FILE)
    tmp = f"{path}.{os.getpid()}.tmp"
    for name in os.listdir(results_dir):
        old = os.path.join(results_dir, name)
        if name.startswith(PLAN_FILE + ".") and name.endswith(".tmp") and old != tmp:
            try:
                if time.time() - os.path.getmtime(old) > 60:
                    os.remove(old)
            except OSError:
                pass
    try:
        with open(tmp, "wb") as raw:
            # Level 3: a quarter of level 6's time for a tenth more bytes (E1.2.3). mtime=0: the bytes are the
            # content's alone — the same run writes the same file.
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=3, mtime=0) as gz:
                for line in lines:
                    gz.write(line.encode("utf-8"))
                    gz.write(b"\n")
            raw.flush()
            os.fsync(raw.fileno())
        with gzip.open(tmp, "rb") as gz:
            json.loads(gz.readline())
            while gz.read(1 << 20):     # to the end: the CRC and the length are checked there
                pass
        size = os.path.getsize(tmp)
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:         # Windows: a reader has the old plan open (a virus scan, the re-plan)
                if attempt == 4:
                    raise
                time.sleep(0.2)
        return size
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _build_analysis_parser():
    import argparse
    parser = argparse.ArgumentParser(description="Japanese Text Analyzer")
    parser.add_argument("--include-single-chars", action="store_true", help="Include 1-character words (overrides default skip)")
    parser.add_argument("--exclude-freq-one", action="store_true", help="Backward compat: Exclude words with frequency of 1")
    parser.add_argument("--min-freq", type=int, default=0, help="Hide words with frequency < this value (default 0)")
    parser.add_argument("--reinforce", action="store_true", help="Retired: ignored (an old command line may pass it)")
    parser.add_argument("--zh-script", choices=zh_script.SCRIPTS, default="asis", help="Read all Chinese as Simplified (s) or Traditional (t); asis = as written")
    parser.add_argument("--visualize-only", action="store_true", help="Launch visualizer server")
    parser.add_argument("--static-only", action="store_true", help="Generate static HTML")
    parser.add_argument("--visualize", action="store_true", help="Launch visualizer after analysis")
    parser.add_argument("--static", action="store_true", help="Generate static HTML after analysis")
    parser.add_argument("--app-mode", action="store_true", help="Open the static report in a dedicated app window")
    parser.add_argument("--theme", type=str, default="default", help="Theme for static HTML (default, world-class, modern-light, zen-focus)")
    parser.add_argument("--target-coverage", type=int, default=0, help="Target cumulative coverage percent (0-100)")
    parser.add_argument("--language", type=str, default="ja", help="Target language code (ja, zh)")
    parser.add_argument("--zen-limit", type=int, default=0, help="Limit words for Zen Mode")
    parser.add_argument("--only-i-plus-one", action="store_true", help="Only include words with i+1 sentences")
    parser.add_argument("--ensure-audio-example", action="store_true", help="Give the last example slot to a sentence that has audio, when none of the chosen ones do")
    parser.add_argument("--context-min", type=int, default=None, help="Ideal sentence minimum words/characters")
    parser.add_argument("--context-max", type=int, default=None, help="Ideal sentence maximum words/characters")
    parser.add_argument("--max-contexts", type=int, default=3, help="Maximum number of example sentences exported per word")
    # The dashboard's automatic Generate (after the Anki sync adds known words): write the report,
    # do not open it. Not an analysis input, so it stays out of compute_run_signature.
    parser.add_argument("--no-open", action="store_true", help="Write the report but do not open it")
    # The window's progress (W1.3): P0.3's JSON lines on stdout. Not an analysis input: out of compute_run_signature.
    parser.add_argument("--progress-json", action="store_true", help="Print progress as JSON lines (the window's)")
    return parser


def parse_analysis_args(argv=None):
    """Parse the analyzer CLI args (argv=None -> sys.argv). Shared so the dashboard can reconstruct
    the EXACT args namespace the run-signature depends on, from the same argv it would pass to the
    analyzer subprocess — no risk of the two drifting."""
    args, _unknown = _build_analysis_parser().parse_known_args(argv)
    return args


def _library_store():
    """The library store module (`app/library_store.py`), or None where it can't be loaded: every caller
    then takes the file, as before."""
    try:
        from app import library_store
        return library_store
    except Exception:
        return None


# The journey check's disk syncs, one at a time per language (Library_Store_Spec §7): a check asked while one
# runs waits for it, and the first of those waiting runs one follow-up for all of them (`_journey_sync`).
_JOURNEY_SYNC_LOCKS = {}
_JOURNEY_SYNC_STARTED = {}             # language -> how many syncs have started
_JOURNEY_SYNC_GUARD = threading.Lock()


def _journey_sync(ls, store, language):
    """`sync_for_window` for the journey check, coalesced: a sync that started after this request was made
    already covers it, so a burst of checks (focus, a language switch, Generate) costs at most two walks. Syncs are
    counted, not timed: Windows' clock ticks every ~15 ms, and a check asked in the same tick as a sync started
    must still get a walk of its own."""
    with _JOURNEY_SYNC_GUARD:
        lock = _JOURNEY_SYNC_LOCKS.setdefault(language, threading.Lock())
        asked = _JOURNEY_SYNC_STARTED.get(language, 0)
    with lock:
        if _JOURNEY_SYNC_STARTED.get(language, 0) > asked:
            return
        with _JOURNEY_SYNC_GUARD:
            _JOURNEY_SYNC_STARTED[language] = _JOURNEY_SYNC_STARTED.get(language, 0) + 1
        ls.sync_for_window(store)


def read_library_schedule(language, data_dir=None, user_files_dir=None):
    """A reader's list (Library_Store_Spec §6.2, §6.6): `(schedule, versions)` from a ready store, read in
    one transaction, else `(None, None)`. A reader never builds: with no ready store, or on any database
    error, the caller takes the file for this call."""
    ls = _library_store()
    if ls is None:
        return None, None
    data_dir = data_dir or get_data_path(language)
    user_files_dir = user_files_dir or get_user_files_path(language)
    try:
        store = ls.open_store(language, data_dir, user_files_dir, role="reader")
        if store is None:
            # Read-only mode: every reader takes the list Generate takes (§6.9), so the journey check, the indexer
            # and the report never disagree with it about a file dropped in since.
            if ls.check_mode(language, data_dir, busy_wait=0.0)[0] == "read-only":
                return ls.read_only_schedule(language, data_dir, user_files_dir), None
            return None, None
        with store:
            return store.schedule(with_versions=True)
    except Exception:
        return None, None


def prepare_library(language, data_dir=None, user_files_dir=None):
    """Generate's list (§7, A10): the store builds or checks itself (`maintain` steps 1–2, in-process),
    takes in what the disk holds (`sync_disk`), and the schedule and its `order_version` are read in one
    transaction; the copy is then written by the helper, which the run never waits for. Returns
    {"schedule", "order_version", "epoch", "pins_version"}: `schedule` None = no store, so the file as before (and no
    `record_analysed`). Read-only mode reads the copy, with untracked files added in memory (§6.9)."""
    out = {"schedule": None, "order_version": None, "epoch": None, "pins_version": None}
    ls = _library_store()
    if ls is None:
        return out
    data_dir = data_dir or get_data_path(language)
    user_files_dir = user_files_dir or get_user_files_path(language)
    try:
        ls.maintain(language, data_dir, user_files_dir, export=False)
        store = ls.open_store(language, data_dir, user_files_dir, role="analyzer")
        if store is None:
            mode, reason = ls.check_mode(language, data_dir)
            if mode == "read-only":
                print(f"Library store is read-only ({reason}): new files are analysed but not added to the order.")
                out["schedule"] = ls.read_only_schedule(language, data_dir, user_files_dir)
            return out
    except Exception as e:
        print(f"Library store unavailable ({e}); reading the library file.")
        return out
    try:
        with store:
            store.sync_disk()
            schedule, versions = store.schedule(with_versions=True)
            if store.export_due():
                ls.spawn_maintain(language)
    except Exception as e:
        print(f"Library store couldn't be read ({e}); reading the library file.")
        return out
    out.update(schedule=schedule, order_version=versions["order_version"], epoch=versions["epoch"],
               pins_version=versions["pins_version"])
    return out


def record_analysed(language, library, data_dir=None, user_files_dir=None):
    """A Generate that read the store finished (or reused results already current): the store records the
    `order_version` it read, so Junban's "journey pending" clears. Never after a JSON fallback, and never
    across a rebuild (a version means nothing outside its epoch, §6.6). Best-effort."""
    if not library or library.get("order_version") is None:
        return
    ls = _library_store()
    try:
        store = ls.open_store(language, data_dir or get_data_path(language),
                              user_files_dir or get_user_files_path(language), role="analyzer")
        if store is None:
            return
        with store:
            if store.versions()["epoch"] == library["epoch"]:
                store.record_analysed(library["order_version"])
    except Exception:
        pass


def resolve_found_files(language, verbose=True, schedule=None, read_store=True):
    """Resolve the ordered [(abs_path, label, weight, source_type), ...] content files for a run —
    from the library store's schedule (phase order) when one is ready, else master_manifest.json, else a
    recursive fallback scan. Shared by main() and the dashboard's no-change pre-flight, so both compute
    the run-signature over exactly the same list. `schedule`: one already read (Generate's, the journey
    check's). `read_store=False`: with no `schedule` given, take the file without opening the store (a caller that
    has already read it read-only and found no ready store: `journey_check`).

    No folder fallback when the list came from a store or from a copy the store wrote (it carries
    `surasura_library`): there an empty list is an empty run (K21) — the scan would analyse every file a
    Graduate left in its tier folder.

    source_type drives the report's per-sentence source badge (subtitle / youtube / bilibili / epub
    / text).
    It prefers what the importer recorded on the manifest entry, then a producer's directory marker
    (read ONCE per directory here), then the filename."""
    data_dir = get_data_path(language)
    user_files_dir = get_user_files_path(language)
    found_files = []
    manifest_path = os.path.join(user_files_dir, "master_manifest.json")
    if schedule is None and read_store:
        schedule, _versions = read_library_schedule(language, data_dir, user_files_dir)
    no_fallback = schedule is not None

    _marker_cache = {}

    def _stype(path, declared=None):
        folder = os.path.dirname(path)

        def _marker():
            # Lazy + cached: a probe per DIRECTORY, and only for files the extension didn't settle.
            if folder not in _marker_cache:
                _marker_cache[folder] = read_source_marker(folder).get("source_type")
            return _marker_cache[folder]

        return infer_source_type(path, declared=declared, marker_type=_marker)

    if no_fallback or os.path.exists(manifest_path):
        if verbose and no_fallback:
            print("Loading Sort Order from the library store")
        elif verbose:
            try:
                print(f"Loading Sort Order from Manifest: {manifest_path}")
            except UnicodeEncodeError:
                print("Loading Sort Order from Manifest (path contains non-ASCII characters)")
        try:
            if not no_fallback:
                # utf-8-sig: the same BOM tolerance as the Content Manager's load_manifest, so a
                # manifest re-saved from Notepad orders the analysis exactly as the library shows it.
                with open(manifest_path, 'r', encoding='utf-8-sig') as f:
                    manifest = json.load(f)
                no_fallback = isinstance(manifest.get("surasura_library"), dict)
                schedule = manifest.get("schedule", {})
            phases = ["PHASE_1_NOW", "PHASE_2_SOON", "PHASE_3_LATER"]  # order matters
            seen_paths = set()
            for phase_key in phases:
                for item in schedule.get(phase_key, []):
                    rel_path = item.get("physical_path", "")
                    if rel_path.startswith("./"):
                        rel_path = rel_path[2:]
                    abs_path = os.path.join(data_dir, rel_path)
                    if not os.path.exists(abs_path):
                        if verbose:
                            print(f"Warning: Manifest file not found: {abs_path}")
                        continue
                    if abs_path in seen_paths:
                        continue
                    seen_paths.add(abs_path)
                    # BOTH the weight (-> Score) and the label (-> Count High/Low/Goal, which drive
                    # the report's ✦ / ⚖ markers) come from the SCHEDULE: the phase this entry is
                    # filed under.
                    #
                    # The label used to be read from `origin_source` instead — a historical note
                    # recording which FOLDER a file sat in when the Architect planned, not where it
                    # was scheduled. After a Smart-Sort the two disagree by design (re-phasing is the
                    # Architect's whole job), and the Content Manager doesn't write a tier there at
                    # all ("Manual Import"), so anything added by hand fell through to GoalContent no
                    # matter which tab it was dropped into. The markers ended up answering "which
                    # folder did this word live in?" instead of "when will I actually meet it?".
                    label, weight = "GoalContent", WEIGHT_GOAL
                    if phase_key == "PHASE_1_NOW":
                        label, weight = "HighPriority", WEIGHT_HIGH
                    elif phase_key == "PHASE_2_SOON":
                        label, weight = "LowPriority", WEIGHT_LOW
                    found_files.append((abs_path, label, weight, _stype(abs_path, item.get("source_type"))))
            if verbose:
                print(f"Manifest Loaded: {len(found_files)} files scheduled.")
        except Exception as e:
            if verbose:
                print(f"Error reading manifest: {e}. Falling back to default scan.")
            found_files = []  # Trigger fallback

    if not found_files and not no_fallback:
        if verbose:
            print("Scaning folders recursively (Default Order)...")
        scan_targets = [
            ("HighPriority", os.path.join(data_dir, "HighPriority"), WEIGHT_HIGH),
            ("LowPriority", os.path.join(data_dir, "LowPriority"), WEIGHT_LOW),
            ("GoalContent", os.path.join(data_dir, "GoalContent"), WEIGHT_GOAL),
        ]

        def get_files_recursive(directory):
            results = []
            if not os.path.exists(directory):
                return []
            for root, dirs, files in os.walk(directory):
                files.sort()
                dirs.sort()
                for file in files:
                    # .epub/.html are intentionally excluded (they must go through the content
                    # importer). CONTENT_EXTENSIONS is shared with the importer + indexer.
                    if is_content_file(file):
                        results.append(os.path.join(root, file))
            return results

        for label, folder, weight in scan_targets:
            if not os.path.exists(folder):
                continue
            for path in get_files_recursive(folder):
                found_files.append((path, label, weight, _stype(path)))

    return found_files


def journey_is_current(args, language):
    """Would Generate compute anything new? True when the last run still describes this library, these
    known words and these analysis settings; False when it would not (or never ran); None when it cannot
    tell. The analyzer's OWN signature (`compute_run_signature` + the token store's last one + the results
    stamp), so the Generate button's state can never disagree with what Generate then does —
    `_try_open_existing_report` asks exactly this before reopening. Presentation (theme, Zen limit) is not
    part of it: that re-renders in a moment and needs no nudge.

    With a library store (Library_Store_Spec §7): the disk is synced first (a hato drop then turns the ✓
    off), and the list and its `order_version` are read in one transaction; the signature still decides —
    the versions are never a substitute. When it matches, the store records that `order_version` as
    analysed, so a move and its reverse, or a Generate that already covered the change, clear Junban's
    "journey pending". With no ready store the helper is started to build one, and the file is read
    meanwhile. Runs on a worker, never a window's thread: it stats every library file."""
    try:
        from app import token_index as _ti
        from app.path_utils import get_user_file

        library = {"schedule": None, "order_version": None, "epoch": None}
        ls = _library_store()
        if ls is not None:
            data_dir, user_files_dir = get_data_path(language), get_user_files_path(language)
            try:
                store = ls.open_store(language, data_dir, user_files_dir, role="window")
            except Exception:
                store = None
            if store is None:
                ls.spawn_build_if_waiting(language, data_dir, user_files_dir)
            else:
                try:
                    with store:
                        _journey_sync(ls, store, language)
                        schedule, versions = store.schedule(with_versions=True)
                    library.update(schedule=schedule, order_version=versions["order_version"],
                                   epoch=versions["epoch"])
                except Exception:
                    pass
        found = resolve_found_files(language, verbose=False, schedule=library["schedule"])
        if not found:
            return None
        sig = compute_run_signature(language, found, parse_analysis_args(args[1:]))
        if not sig:
            return None
        results_dir = get_user_file("results")
        if not all(os.path.exists(os.path.join(results_dir, name)) for name in
                   ("priority_learning_list.csv", "progressive_learning_list.csv", "word_stats.json")):
            return False
        store = _ti.open_store(language)
        try:
            stored = store.get_meta("last_run_signature")
        finally:
            store.close()
        current = stored == sig and read_run_stamp(results_dir) == sig
        if current:
            record_analysed(language, library)
        return current
    except Exception:
        return None


def journey_check(args, language):
    """`journey_is_current`, for a caller that must write nothing (surasura-cli `status`, P1.2): the same question
    asked of the same signature — True, False, or None when it can't tell — with every store opened `mode=ro`, the
    disk never synced into the library store, its helper never started and nothing recorded. The window keeps its own
    call (which syncs first).

    None also while the library store holds a change from disk it hasn't synced yet (a file dropped in since): only
    a sync can tell, and this check never syncs. It stats every library file, as the window's check does."""
    try:
        from app.path_utils import get_user_file

        schedule = None
        ls = _library_store()
        if ls is not None:
            mode, schedule, _versions, pending = ls.read_only_view(language, get_data_path(language),
                                                                   get_user_files_path(language))
            if mode == "unknown" or pending:
                return None
        found = resolve_found_files(language, verbose=False, schedule=schedule, read_store=False)
        if not found:
            return None
        sig = compute_run_signature(language, found, parse_analysis_args(args[1:]))
        if not sig:
            return None
        results_dir = get_user_file("results")
        if not all(os.path.exists(os.path.join(results_dir, name)) for name in
                   ("priority_learning_list.csv", "progressive_learning_list.csv", "word_stats.json")):
            return False
        return _token_store_meta(language, "last_run_signature") == sig and read_run_stamp(results_dir) == sig
    except Exception:
        return None


def _token_store_meta(language, key):
    """A value the language's token store keeps in its meta table, as written (`Store.set_meta`), read through a
    `mode=ro` connection — None when there is no store or no such value. Never writes, never raises."""
    import pathlib
    import sqlite3
    from app import token_index as _ti
    path = _ti.store_path_for(language)
    if not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=5.0)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def compute_run_signature(language, found_files, args, order_free=False):
    """The run-signature: a filesystem fingerprint of everything that affects the analysis OUTPUT
    (content files + their order/weights, known words, ignore/blacklist/graduated lists, frequency
    lists, the analysis-affecting settings, the analysis-affecting args, and the engine version).
    Presentation (theme / app-mode / zen / words-per-day) is deliberately excluded. Returns the
    sha256 hex or None. SHARED by main() (decide the skip) and the dashboard (decide, in-process,
    whether Generate can just reopen the existing report without spawning the analyzer).

    `order_free`: the plan file's form (`signature_digest`) — the same library in any order has one."""
    return signature_digest(run_signature_parts(language, found_files, args), order_free)


# The run signature's digest: one encoder and one rule, the analyzer's and the fast re-plan's (app/plan_rules.py).
_SIGNATURE_ENCODER = plan_rules.SIGNATURE_ENCODER
signature_digest = plan_rules.signature_digest


def run_signature_parts(language, found_files, args):
    """What the run signature hashes (`compute_run_signature`), as a dict; None when it can't be read."""
    try:
        from app import token_index as _token_index
        user_files_dir = get_user_files_path(language)
        known_file = os.path.join(user_files_dir, "KnownWord.json")
        ignore_list_file = os.path.join(user_files_dir, "IgnoreList.txt")
        black_list_file = os.path.join(user_files_dir, "Blacklist.txt")
        graduated_list_file = os.path.join(user_files_dir, "GraduatedList.txt")
        # getattr: an args namespace built by hand (a test, an older caller) predates --zh-script,
        # and an AttributeError here would silently return None and disable the skip.
        script = zh_script.effective(language, getattr(args, "zh_script", "asis"))
        known_sig = _token_index.known_signature(known_file, script)       # stat only
        available_freq_lists = discover_yomitan_frequency_lists(user_files_dir, language)  # paths only

        def _fsig(p):
            try:
                _st = os.stat(p)
                return [_st.st_mtime, _st.st_size]
            except OSError:
                return None

        _NON_ANALYSIS_SETTINGS = {
            "theme", "open_app_mode", "zen_limit",
            "words_per_day", "show_words_per_day",
            "open_count", "skipped_version", "failed_update_version",
            "source_display",   # badge rendering only — re-renders (see compute_render_signature)
            "word_search_enabled", "word_search_category",   # lookup button — same, re-render only
            "sentence_dictionary_source",   # the sentence dictionary export's own choice — no run
            "index_pool_workers",           # how many processes tokenize: speed only, the same tokens (W1.3)
            "app_theme", "text_size",       # the 3.0 window's look (W2.1): no run or report reads them
            # Connect's switch and the New arrivals placing rules: where an item lands, never what a run counts
            "connect_enabled", "placing_rules",
            # Anki sync config: what it WRITES (KnownWord.json) is already in known_sig; the deck
            # and field picks themselves must not force a re-analysis on every click.
            "anki_connect_url", "anki_sync_auto", "anki_sync_decks", "anki_sync_fields",
            "anki_sync_include_suspended", "anki_backlog_on_generate", "anki_auto_generate",
            # Connect's mine path: what `pick` sends Anki Miner, never what a run counts
            "connect_mine_words", "connect_send_grammar", "connect_anki_miner_path", "connect_anki_miner_profile",
            # Optional-module switches that change what the app SHOWS, never what a run computes.
            # (`enable_youtube_preview` joined them at ENGINE_REVISION 11: every run now writes the
            # library_frequency.json it used to switch on.)
            "hide_satoru", "enable_youtube_transcripts", "youtube_risk_acknowledged",
            "enable_youtube_preview", "enable_koe", "enable_junban", "enable_reels",
            # The app's own and the importers': telemetry, automatic updates, the welcome guide, the
            # EPUB importer's part size, the Content Manager's "Add Words on 'Graduate'". No run reads them.
            "telemetry_enabled", "auto_update_enabled", "onboarding_completed", "split_length",
            "add_graduated_words",
            # Rarity or coverage: a run reads neither key, only the --target-coverage the dashboard
            # passes in coverage mode — in the args below.
            "strategy", "target_coverage",
            # Retired: ChineseTokenizer ignores it. A window that saved every default kept writing it
            # back, and each such save cost a full re-analysis.
            "reinforce_segmentation",
        }
        # The optional modules' own tunables. The Junban panel saves its deck, order and touch-ups
        # on every change, and hashing them made each of those clicks cost a full re-analysis.
        _NON_ANALYSIS_PREFIXES = ("junban_", "koe_", "reels_")
        # The logic keys no run reads: the tooltip delay and the EPUB importer's split; and the report's
        # own — "Show 'Target Met' inline", "Hide Audio Button", the page size and the ✦ / ⚖ thresholds —
        # which compute_render_signature holds instead (a re-render, never a re-analysis).
        _NON_ANALYSIS_LOGIC = {"gui", "importer",
                               "inline_completed_files", "hide_audio_button", "chunk_size", "priority_markers"}
        _UNREAD_CONTEXT = {"search_range", "max_extra", "min_words"}   # no code reads them
        # Read by a Japanese run only (measured: flipping any of them leaves every output of a Chinese
        # run byte for byte the same; the one-character rule's --include-single-chars too, in the args).
        _JAPANESE_ONLY_LOGIC = {"paren_readings", "names_katakana", "names_recurring", "names_kanji",
                                "names_work_terms", "phrases_and_titles", "pronoun_bases", "phrase_rows",
                                "ignore_names"}
        _settings_for_sig = ""
        try:
            # The settings as the run reads them (load_settings: the defaults filled in, a saved value
            # always winning). A key written at its default and one left out are then the same
            # settings, as they are to the run: an update's first start, which writes the new defaults
            # into the file, and a window that saves every default re-analyze nothing.
            _sj = settings_manager.load_settings()
            for _k in _NON_ANALYSIS_SETTINGS:
                _sj.pop(_k, None)
            for _k in [k for k in _sj if k.startswith(_NON_ANALYSIS_PREFIXES)]:
                _sj.pop(_k, None)
            _logic = {k: v for k, v in _sj.get("logic", {}).items() if k not in _NON_ANALYSIS_LOGIC}
            if isinstance(_logic.get("context"), dict):
                _logic["context"] = {k: v for k, v in _logic["context"].items() if k not in _UNREAD_CONTEXT}
            # Each language's own: its sentence ends, never the other's; the Chinese script only for
            # Chinese (a Japanese run's args carry no script), the Japanese-only switches only for Japanese.
            if isinstance(_logic.get("sentence_boundaries"), dict):
                _logic["sentence_boundaries"] = {language: _logic["sentence_boundaries"].get(language)}
            if language == "zh":
                _sj.pop("exclude_single", None)
                for _k in _JAPANESE_ONLY_LOGIC:
                    _logic.pop(_k, None)
            else:
                _sj.pop("zh_script", None)
            _sj["logic"] = _logic
            _settings_for_sig = json.dumps(_without_comments(_sj), sort_keys=True, ensure_ascii=False)
        except Exception:
            pass

        from app import __version__ as _app_version
        _sig_parts = {
            "files": [[fp, _fsig(fp), _l, _w, _st] for (fp, _l, _w, _st) in found_files],
            "known": known_sig,
            "lists": [_fsig(p) for p in (ignore_list_file, black_list_file, graduated_list_file)],
            "freq": sorted([_fsig(p) for p in available_freq_lists.values()]),
            "settings": _settings_for_sig,
            "args": [args.language, args.min_freq, args.target_coverage, args.only_i_plus_one,
                     args.ensure_audio_example,
                     # The one-character rule is Japanese only (skip_singles in main()).
                     args.include_single_chars and language != "zh", args.exclude_freq_one, args.reinforce,
                     args.context_min, args.context_max, args.max_contexts, script],
            "engine": f"{_app_version}|schema{_token_index.SCHEMA_VERSION}|rev{ENGINE_REVISION}",
            "debug_word_stats": bool(os.environ.get("SURASURA_DEBUG_WORD_STATS")),
        }
        # Q4-3: with Automatic rarity on, the band the library's store remembers helps pick the list (the second
        # threshold): a part of its own, present only then, so no other library's signature moves.
        try:
            _auto_on = ((settings_manager.load_settings().get("logic") or {}).get("selection") or {}).get("auto") is True
        except Exception:
            _auto_on = False
        if _auto_on:
            try:
                from app import library_store as _library_store
                _sig_parts["auto_band"] = _library_store.read_auto_band(language, get_data_path(language))
            except Exception:                     # no store to ask (refused, a path error): nothing remembered
                _sig_parts["auto_band"] = None
        return _sig_parts
    except Exception as e:
        print(f"Warning: could not compute run signature: {e}")
        return None


def _without_comments(value):
    """`value` without its "_comment" keys, at any depth: notes to the reader of settings.json, which no code reads."""
    if isinstance(value, dict):
        return {k: _without_comments(v) for k, v in value.items() if k != "_comment"}
    return value


def compute_render_signature(args):
    """Fingerprint of everything that changes the RENDERED report but NOT the analysis, so those
    changes re-render instead of re-analyzing. SHARED with the dashboard's fast path so the two can
    never disagree about whether the existing report is still correct.

    Anything static_html_generator INJECTS into the report belongs here. words_per_day /
    show_words_per_day were injected but unlisted, so editing them left the report showing the old
    "At N words a day..." estimate until something else forced a re-render.

    `--app-mode` is deliberately excluded: it changes only HOW the browser opens the report, not a
    byte of its contents, so toggling it reopens the existing file instead of re-rendering."""
    try:
        _s = settings_manager.load_settings()
    except Exception:
        _s = {}
    _logic = _s.get("logic") if isinstance(_s.get("logic"), dict) else {}
    _markers = _logic.get("priority_markers")
    return json.dumps([
        args.theme,
        int(args.zen_limit or 0),
        _s.get("source_display", "off"),
        # Word lookup button: whether it renders at all, and which Nadeshiko category the link
        # carries. Both are INJECTED into the report, so both must re-render — the same rule that
        # words_per_day was missing above.
        bool(_s.get("word_search_enabled", True)),
        _s.get("word_search_category", "all"),
        _s.get("words_per_day", 5),
        bool(_s.get("show_words_per_day", True)),
        # Speech (optional module) is INJECTED into the report — the helper endpoint, and which
        # sentences already have audio. Toggling it must therefore re-render. Without this, turning
        # speech on while the badge was already visible changed nothing in the signature, so the
        # existing report was reused and its badges stayed mute. Absent module -> False, so this
        # costs nothing for anyone who doesn't have it.
        bool(_s.get("enable_koe", False)),
        # "Label backlogged Anki words" (Junban_Backlog_Spec WP-B8): the switch, and — only while it
        # is on — the backlog file the Anki sync keeps. Both are INJECTED, so a sync costs one
        # re-render on the next Generate, never a re-analysis (§3 I3).
        bool(_s.get("anki_backlog_on_generate", True)),
        _backlog_fingerprint(getattr(args, "language", "ja"))
        if _s.get("anki_backlog_on_generate", True) else None,
        # …and the answers to Junban's "Same word as one on your list?": a "yes" labels its word too
        # (Anki_Match_Consistency_Scope.md item 1).
        _backlog_fingerprint(getattr(args, "language", "ja"), "junban_pairs.json")
        if _s.get("anki_backlog_on_generate", True) else None,
        # The report's own logic keys, which the templates read from the logic block they embed
        # (globalLogic): "Show 'Target Met' inline", "Hide Audio Button", the page size and the ✦ / ⚖
        # thresholds. No run reads them, so compute_run_signature leaves them out: changing one
        # re-renders, never re-analyzes. The report embeds the whole block, so a template that starts
        # reading another logic key adds it here.
        bool(_logic.get("inline_completed_files", False)),
        bool(_logic.get("hide_audio_button", False)),
        _logic.get("chunk_size", 50),
        {k: v for k, v in _markers.items() if k != "_comment"} if isinstance(_markers, dict) else _markers,
        # Speech's port: the report embeds it to reach the helper, but only while Speech is on.
        _s.get("koe_port") if _s.get("enable_koe", False) else None,
        # The templates themselves. Without this a template-only change (a new report tab, a CSS
        # fix) was invisible to both fast paths: they reopened the old HTML until something else
        # forced a re-render. Hashing makes it a cheap re-render, never a re-analysis.
        _template_fingerprint(),
    ])


def _backlog_fingerprint(language, name="anki_backlog.json"):
    """(mtime, size) of `User Files/<lang>/<name>` — the Anki backlog, or Junban's answers — or None
    when there is none."""
    try:
        st = os.stat(os.path.join(get_user_files_path(language), name))
        return [st.st_mtime, st.st_size]
    except (OSError, TypeError):
        return None


def _template_fingerprint():
    """Short hash of both report templates; a constant if they can't be read (never raises)."""
    h = hashlib.sha1()
    try:
        for name in ("web_app.html", "zen_app.html"):
            with open(get_resource(os.path.join("templates", name)), "rb") as f:
                h.update(f.read())
    except Exception:
        return "templates-unreadable"
    return h.hexdigest()[:12]


# --- Which run the files in results/ came from --------------------------------------------------- #
# results/ holds ONE set of outputs, shared by both languages, while each language keeps its own
# "last run signature" in its own token store. So after Generate in Japanese, then Chinese, then
# Japanese again with nothing changed, the Japanese signature still matched and the skip reopened
# the CHINESE results as the Japanese report. A completed run now also stamps results/ with its
# signature, and both skips (main() below, and the dashboard's in-process fast path) require the
# stamp to match too. When it doesn't, they simply run — exactly what happens today when anything
# changes. A stamp that is missing (results from before this existed) counts as a mismatch: one
# full run, then back to skipping.
RUN_STAMP_FILE = "run_signature.txt"


def read_run_stamp(results_dir):
    """The run signature that produced the outputs in `results_dir`, or None. Never raises."""
    try:
        with open(os.path.join(results_dir, RUN_STAMP_FILE), "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _set_run_stamp(results_dir, signature):
    """Record (or, with signature=None, forget) which run the outputs in `results_dir` belong to.
    Best-effort: a stamp that can't be written only costs one extra full run next time."""
    path = os.path.join(results_dir, RUN_STAMP_FILE)
    try:
        if signature:
            with open(path, "w", encoding="utf-8") as f:
                f.write(signature)
        elif os.path.exists(path):
            os.remove(path)
    except OSError as e:
        print(f"Warning: could not update the results stamp: {e}")


# results/ is written by one Generate at a time, across programs (P0.3 04 §2): the analyzer holds the `results` lock
# (`app/locks.py`) for its whole run — itself, the writer, so a parent killed meanwhile (surasura-cli's `generate`)
# never leaves a writer without the lock. Whoever starts it waits for the lock to be free first (the window on a
# worker, the command line with --wait); the analyzer waits this long more (SURASURA_RESULTS_WAIT, seconds, or
# "forever": the window's, which has already waited its turn and stops it by closing) for the moment between the two,
# then gives up with RESULTS_BUSY, nothing written. 75 (EX_TEMPFAIL), never 3: on Windows a native crash (abort) exits
# 3 too, and a crash must never read as "busy, try later".
RESULTS_WAIT = 10.0
RESULTS_BUSY = 75


def _report_written(path, since):
    """Did the report generator write `path` (at or after `since`)? It says its own failures (a missing template, an
    unreadable list) and returns: the run's exit code reads them here."""
    try:
        if os.path.getmtime(path) >= since - 2:
            return True
    except OSError:
        pass
    print("Error: the report was not written (see the lines above).")
    return False


# --progress-json (W1.3; the window's spec 04 §4.2, P0.3 02 §2): the run's steps as JSON lines on stdout, ASCII-escaped
# and flushed — {"type":"progress","step":…,"done":…,"total":…} — then one {"type":"result",…} or {"type":"error",…},
# always last. The analyzer's own lines stay as they are; without the flag nothing here prints.
#
# A cancel: the window that started the run names a file in SURASURA_CANCEL_FILE and makes it to cancel. The run looks
# for it (a stat) at each step and before each file it tokenizes, and stops there as long as it hasn't reached *Writing
# your list* — nothing of results/ written but the stamp it dropped as it started — answering the `cancelled` error
# line (GENERATE_CANCELLED). From *Writing your list* on it finishes: the CSV writes aren't atomic, and only the run
# itself knows which step it is in (W1.3 adversary #6, #7). (Not stdin: on Windows a thread waiting on a pipe stalls
# the run's other calls on it.)
PROGRESS_STEPS = ("Reading your files", "Counting words", "Picking sentences", "Writing your list",
                  "Writing the journey")
WRITING_STEPS = ("Writing your list", "Writing the journey")
GENERATE_CANCELLED = 76
_PROGRESS = {"on": False, "ran": False, "cancel_file": None, "writing": False}


class _GenerateCancelled(BaseException):
    """The window cancelled the run before it wrote anything (a BaseException: no `except Exception` swallows it)."""


def _progress_line(record):
    if _PROGRESS["on"]:
        print(json.dumps(record, ensure_ascii=True), flush=True)


def _cancel_point():
    """Stop here if the window asked, and nothing is being written yet."""
    if _PROGRESS["cancel_file"] and not _PROGRESS["writing"] and os.path.exists(_PROGRESS["cancel_file"]):
        raise _GenerateCancelled()


def _progress(step, done=None, total=None):
    if _PROGRESS["on"]:
        _cancel_point()
        if step in WRITING_STEPS:
            _PROGRESS["writing"] = True
        _progress_line({"type": "progress", "step": step, "done": done, "total": total})


def _cancellable(tokenize_file):
    """The reconcile's tokenizer with a cancel point before each file (--progress-json only)."""
    if not _PROGRESS["on"]:
        return tokenize_file

    def tokenize(path):
        _cancel_point()
        return tokenize_file(path)
    return tokenize


def _reporting_progress(run):
    """The result or error line after the run, with --progress-json (outermost: the busy answer, a cancel and a crash
    too). Without the flag the run is untouched: an exception goes on as it always did."""
    import functools

    @functools.wraps(run)
    def wrapper(*args, **kwargs):
        on = "--progress-json" in sys.argv[1:]
        _PROGRESS.update(on=on, ran=False, writing=False,
                         cancel_file=(os.environ.get("SURASURA_CANCEL_FILE") or None) if on else None)
        try:
            code = run(*args, **kwargs)
        except _GenerateCancelled:
            _progress_line({"type": "error", "contract": 1, "ok": False, "code": "cancelled",
                            "message": "Generate was cancelled before your list was written."})
            return GENERATE_CANCELLED
        except BaseException as e:
            if not on:
                raise
            if isinstance(e, SystemExit):
                sys.stderr.flush()
                _progress_line({"type": "error", "contract": 1, "ok": False,
                                "code": "usage" if e.code not in (0, None) else "failed",
                                "message": "Generate's options weren't understood."})
                raise
            import traceback
            traceback.print_exc()                       # the traceback first: the error line is always last
            sys.stderr.flush()
            _progress_line({"type": "error", "contract": 1, "ok": False, "code": "failed",
                            "message": f"Generate stopped: {e}"})
            return 1
        if code == RESULTS_BUSY:
            _progress_line({"type": "error", "contract": 1, "ok": False, "code": "busy", "lock": "results",
                            "message": "Another Surasura program is writing your list; nothing was changed."})
        elif code:
            _progress_line({"type": "error", "contract": 1, "ok": False, "code": "partial",
                            "message": "Your list was written, but the report couldn't be."})
        else:
            record = {"type": "result", "contract": 1, "ok": True, "ran": _PROGRESS["ran"]}
            if not _PROGRESS["ran"]:
                record["skipped"] = "report only" if "--static-only" in sys.argv else "nothing changed"
            _progress_line(record)
        return code
    return wrapper


def _holding_results(run):
    """Run `run` holding the `results` lock; still held by another program after the wait -> RESULTS_BUSY."""
    import functools

    @functools.wraps(run)
    def wrapper(*args, **kwargs):
        from app import locks
        held = None
        if not locks.held_here("results"):
            raw = os.environ.get("SURASURA_RESULTS_WAIT", "")
            try:
                wait = None if raw == "forever" else float(raw or RESULTS_WAIT)
            except ValueError:
                wait = RESULTS_WAIT
            try:
                held = locks.take("results", "Generate", wait=wait, on_wait=lambda holder: print(
                    f"Waiting for {(holder or {}).get('verb') or 'another Generate'} to finish writing results/..."))
            except locks.Busy as e:
                verb = (e.holder or {}).get("verb") or "another Surasura program"
                print(f"Error: results/ is being written by {verb}; nothing was changed. Try again when it has finished.")
                return RESULTS_BUSY
            except Exception as e:
                print(f"Warning: the results lock can't be used ({e}); generating without it.")
        try:
            return run(*args, **kwargs)
        finally:
            if held is not None:
                held.release()
    return wrapper


@_reporting_progress
@without_cycle_collection
@_holding_results
def main():
    """The analyzer's run. Returns its exit code: None (0) when it finished, 1 when the report couldn't be written
    (results/ is complete; the next Generate re-renders it), RESULTS_BUSY when another program held results/."""
    import sys

    # --- VISUALIZER REMOVED ---
    # Legacy interactive visualizer logic removed.

    # --- STATIC ONLY MODE ---
    if "--static-only" in sys.argv:
        try:
            import static_html_generator
            print("\n---------------------------------------------------")
            print("Generating Static HTML (Skipping Analysis)...")
            static_html_generator.generate_static_html()
            return
        except ImportError:
            print("Error: static_html_generator.py not found.")
            return

    # --- ARGUMENT PARSING (shared parser so the dashboard reconstructs the identical args) ---
    args = parse_analysis_args()
    _report_failed = False      # the report couldn't be written: the run's exit code says so (1)

    global SKIP_SINGLE_CHARS, MIN_FREQ, SANITIZE_JA, ONLY_I_PLUS_ONE, ENSURE_AUDIO_EXAMPLE
    ONLY_I_PLUS_ONE = args.only_i_plus_one
    ENSURE_AUDIO_EXAMPLE = args.ensure_audio_example

    # Override logic settings if supplied
    if args.context_min is not None:
        if "context" not in LOGIC:
            LOGIC["context"] = {}
        LOGIC["context"]["min_chars"] = args.context_min
        print(f"Configuration: Context Min Length = {args.context_min}")
        
    if args.context_max is not None:
        if "context" not in LOGIC:
            LOGIC["context"] = {}
        LOGIC["context"]["preferred_max_chars"] = args.context_max
        print(f"Configuration: Context Max Length = {args.context_max}")
    
    # Logic: Default SKIP_SINGLE_CHARS is True. 
    # If --include-single-chars is present, set to False.
    if args.include_single_chars:
        SKIP_SINGLE_CHARS = False
        print("Configuration: Single character words INCLUDED.")
    else:
        SKIP_SINGLE_CHARS = True
        print("Configuration: Single character words SKIPPED (Default).")

    # Min Frequency Logic
    # NOTE: raw --min-freq is retired as the user-facing selector (replaced by density bands
    # below); it is kept ONLY as an explicit raw-count OVERRIDE for the CLI / tests / power users.
    # When passed (>0) it bypasses the bands entirely.
    if args.min_freq > 0:
        MIN_FREQ = args.min_freq
        print(f"Configuration: Raw min-freq override - words with count < {MIN_FREQ} EXCLUDED.")
    elif args.exclude_freq_one:
        # Backward compatibility
        MIN_FREQ = 1
        print("Configuration: Frequency < 1 words EXCLUDED (via flag).")
    else:
        MIN_FREQ = 0

    # Density-band selection config (used unless a raw --min-freq override or coverage mode is
    # active). Read from settings; the GUI band slider writes logic.selection.band.
    _sel = LOGIC.get("selection", {})
    SELECT_BAND = _sel.get("band", "occasional")
    SELECT_BANDS_PPM = _sel.get("bands_ppm") or word_selection.DEFAULT_BANDS_PPM
    SELECT_MIN_COUNT = _sel.get("min_count", word_selection.DEFAULT_MIN_COUNT)
    # Automatic rarity (logic.selection.auto, off by default): the band is picked at the cut below —
    # the rarest band with auto_max_words words or fewer — in place of SELECT_BAND.
    SELECT_AUTO = _sel.get("auto") is True
    SELECT_AUTO_MAX_WORDS = _sel.get("auto_max_words", word_selection.DEFAULT_AUTO_MAX_WORDS)

    language = args.language
    print(f"Configuration: Target Language = {language}")

    # Japanese Unidic lemmas carry a gloss suffix (e.g. テスト-test); always strip it for JA so
    # lemmas match the (clean) frequency lists and a word never splits into -suffix variants.
    SANITIZE_JA = (language == 'ja')
    print(f"Configuration: Japanese term sanitization = {SANITIZE_JA}")

    # Chinese script (`zh_script`): content, known words, lists and frequency lists are all read in
    # this ONE script. "asis" for Japanese and for anyone who never set it — today's exact behaviour.
    script = zh_script.effective(language, args.zh_script)

    # Japanese one-character words follow the dictionary rule (§ One-character words, above): only one-kanji dictionary
    # words are listed, where they stand on their own, and nothing else of one character counts. In Chinese most
    # high-frequency words ARE single characters — never skip them for zh.
    skip_singles = SKIP_SINGLE_CHARS and language == 'ja'

    def _never(lr):
        """A one-character word the list can never offer (the rule on): no use, example or unknown anywhere."""
        return skip_singles and single_kind(lr) == 1

    print(f"\nLoading resources...")
    
    # Resolve Paths based on Language
    data_dir = get_data_path(language)
    user_files_dir = get_user_files_path(language)
    known_file = os.path.join(user_files_dir, "KnownWord.json")
    ignore_list_file = os.path.join(user_files_dir, "IgnoreList.txt")
    black_list_file = os.path.join(user_files_dir, "Blacklist.txt")
    graduated_list_file = os.path.join(user_files_dir, "GraduatedList.txt")

    # Open the persistent SQLite token store (known-words cache, delta reconcile, run-signature).
    from app import token_index as _token_index
    try:
        _store = _token_index.open_store(language)
    except Exception as e:
        print(f"Warning: could not open token store: {e}")
        _store = None

    # --- SIGNATURE INPUTS ONLY (cheap: file stats + paths, NO file content) ---
    # Everything the run-signature needs is a filesystem fingerprint, not file content. So the
    # signature + skip decision below happen BEFORE loading any heavy content: the tokenizer, the
    # known-words (a ~3 MB JSON), the ignore lists, or the frequency-list CSVs. A "nothing changed"
    # skip needs none of those, and on a big library that content-loading is the bulk of a skip's
    # wasted time. (They're loaded further down, only once we know a real run is happening.)
    _known_sig = _token_index.known_signature(known_file, script)   # stat only (no tokenizer, no 3MB read)
    print(f"Scanning for {language} frequency lists in {user_files_dir}...")
    available_freq_lists = discover_yomitan_frequency_lists(user_files_dir, language)   # paths only
    if not available_freq_lists:
        print("Warning: No frequency lists found in User Files/")
        print("Expected format: frequency_list_{lang}_*.csv")

    word_stats = defaultdict(lambda: {
        "score": 0, "total_count": 0, "sources": set(),
        "high_count": 0, "low_count": 0, "goal_count": 0,
        "candidate_contexts": [], # List of (is_too_short, is_too_long, initial_cost, unique_lrs, s_text)
        "first_context": None,
        "surface": "",
        # How this word is actually SPELLED in the library, counted so the commonest wins. UniDic's
        # lemma is a canonical headword that often nobody writes (有る for ある, スドウ for 須藤), and
        # it is the wrong string to put on a card or in the report. Counting rather than last-wins
        # because one stray spelling shouldn't rename the word.
        "orths": Counter(),
        # Every surface (inflected) form met, counted — becomes the report's `Forms` column so the
        # Search tab can find 食べた under 食べる. `surface` above keeps only the last one seen.
        "surfaces": Counter(),
        "min_seq": float('inf'), # Track first appearance sequence index
        # Reading-vs-listening inputs (see app/modality.py). spoken_count is how often the word
        # was met in the user's OWN subtitle/YouTube files — evidence that beats the bundled
        # estimate. series is the set of distinct works it appears in, which separates general
        # vocabulary from one story's names and jargon.
        "spoken_count": 0,
        "series": set(),
        # Best few candidates that come with audio, for the "guarantee an audio example" option.
        # Only populated when that option is on, so it costs nothing otherwise.
        "audio_contexts": [],
    })
    
    words_skipped_i_plus_one = 0 # Track skips explicitly for visibility

    # Library-wide modality inputs, accumulated during aggregation (see app/modality.py).
    library_series = set()      # every distinct work — the denominator for the dispersion check
    spoken_file_count = 0       # subtitle/YouTube files, i.e. how much listening material there is

    file_stats = []
    
    # 3. Process Files (Aggregation Phase)

    # New Logic: Use master_manifest.json if available.
    # Fallback: Alphabetical scan (Phase 0 behavior)
    
    # The library's list: the store's (built, checked and synced with the disk first), else the file.
    _library = prepare_library(language, data_dir, user_files_dir)
    found_files = resolve_found_files(language, schedule=_library["schedule"])   # shared with the GUI
    print(f"Final Count: Found {len(found_files)} files to process.")

    # --- #2 Run-signature: skip the ENTIRE run if nothing affecting the analysis changed ---
    # Computed by the shared compute_run_signature() (the dashboard calls the same function in-process
    # to decide whether Generate can just reopen the existing report without spawning this analyzer).
    # Its parts are kept: the plan file (below) carries the same signature without the order, from this very read.
    _sig_parts = run_signature_parts(language, found_files, args)
    _run_sig = signature_digest(_sig_parts, chunked=False)
    _auto_pick = {}                      # Q4-3: the band Automatic picks below, remembered before the stamp

    # The ANALYSIS outputs the report renders from (not the HTML itself — that's re-rendered below).
    _analysis_outputs_present = (os.path.exists(OUTPUT_CSV) and os.path.exists(OUTPUT_PROGRESSIVE)
                                 and os.path.exists(os.path.join(RESULTS_DIR, "word_stats.json")))
    # Presentation fingerprint that decides whether the HTML must be RE-RENDERED (see
    # compute_render_signature — shared with the dashboard so the two can't drift).
    _render_sig = compute_render_signature(args)
    if (_store is not None and _run_sig and _analysis_outputs_present
            and not os.environ.get("SURASURA_FORCE_RUN")         # surasura-cli generate --force
            and _store.get_meta("last_run_signature") == _run_sig
            and read_run_stamp(RESULTS_DIR) == _run_sig):   # ...and results/ is THIS run's (above)
        print("Nothing affecting the analysis changed since the last run - reusing existing results.")
        _progress("Writing the journey")    # the sidecars and a re-render write results/: a cancel waits for the end
        record_analysed(language, _library, data_dir, user_files_dir)
        # A completed run is being reused; make sure the Content Manager sidecars exist and are
        # current (backfills them from word_stats.json on the first skip after an update). One-time.
        _backfill_sidecars(RESULTS_DIR)
        if args.static:
            try:
                try:
                    from app import static_html_generator
                except ImportError:
                    import static_html_generator
                _html = os.path.join(RESULTS_DIR, "reading_list_static.html")
                # Fast "same setting" path: if the presentation is ALSO unchanged, the existing
                # report is already correct — just open it (no re-render, and pandas is never
                # imported). Otherwise re-render with the new theme/Zen (still no re-analysis).
                if os.path.exists(_html) and _store.get_meta("last_render_sig") == _render_sig:
                    print("Report already up to date - opening it.")
                    if not args.no_open:
                        static_html_generator.open_report(app_mode=args.app_mode)
                else:
                    print("Re-rendering report from existing results (presentation changed)...")
                    _rendering = time.time()
                    static_html_generator.generate_static_html(
                        theme=args.theme, app_mode=args.app_mode, zen_limit=args.zen_limit,
                        open_browser=not args.no_open)
                    _report_failed = not _report_written(_html, _rendering)
                    try:
                        _store.set_meta("last_render_sig", _render_sig)
                    except Exception:
                        pass
            except Exception as e:
                print(f"Error: Could not generate static HTML: {e}")
                _report_failed = True
        _store.close()
        return 1 if _report_failed else None

    # pandas is only needed from here on (to write the CSVs on a full run). Import it lazily so the
    # "nothing changed" skip path above never pays its ~0.35s import cost.
    import pandas as pd

    # A real run is about to replace results/. Drop the stamp first, so a run that dies part-way
    # leaves outputs that no skip will ever mistake for a finished run. Re-stamped at the end.
    _set_run_stamp(RESULTS_DIR, None)
    _PROGRESS["ran"] = True
    _progress("Reading your files", 0, len(found_files))

    # --- Past the skip: this is a real run, so NOW load the heavy content the skip check above
    #     deliberately avoided (tokenizer, known-words normalization, ignore lists, frequency lists). ---
    if language == 'zh':
        tokenizer = ChineseTokenizer(reinforce_segmentation=args.reinforce, script=script)
    else:
        tokenizer = JapaneseTokenizer()

    # Reconcile the token store: tokenize ONLY changed/new files (into cached sentences); the
    # aggregation below reads those cached tokens, so unchanged files are never re-tokenized. First,
    # because it also computes the library's name tables (app/names.py), which every word read from
    # here on — the known words included — is read with.
    if _store is not None:
        try:
            _store.reconcile([_fp for (_fp, _l, _w, _st) in found_files],
                             _cancellable(_token_index.make_tokenizer(language, reinforce=args.reinforce,
                                                                      script=script)),
                             build_signature=_token_index.build_signature(language, args.reinforce, script))
        except Exception as e:
            print(f"Warning: token store reconcile failed; using direct tokenization: {e}")
            try:
                _store.close()
            except Exception:
                pass
            _store = None
    if language == 'ja':
        # Without the store (locked, damaged) the run still reads with the tables the last index computed when the
        # store's file can be read, so its words are the ones the Rarity slider counted; else names split, as they
        # do before a first index.
        names.use_library_tables(_store.names_tables() if _store is not None
                                 else _token_index.read_names_tables(language))

    # Known-words normalization tokenizes ~10k terms — expensive. Reuse the cached result when
    # KnownWord.json is unchanged; any edit / delete / newly-added file flips _known_sig (computed
    # above) and forces a fresh normalization, so a change to your known words is always reflected.
    _cached_known = _store.get_cached_known(_known_sig) if _store else None
    if _cached_known is not None:
        known_words_initial, known_lemmas_initial = _cached_known
        print("Reused cached known-words normalization.")
    else:
        known_words_initial, known_lemmas_initial = load_known_words(known_file, tokenizer)
        if _store:
            try:
                _store.set_cached_known(_known_sig, known_words_initial, known_lemmas_initial)
            except Exception:
                pass

    ignore_list = load_simple_list(ignore_list_file, script, language)
    ignore_list.update(load_simple_list(black_list_file, script, language))        # merge blacklist into ignore list
    ignore_list.update(load_simple_list(graduated_list_file, script, language))    # merge graduated list into ignore list
    ignore_list.update(load_ignored_entries(user_files_dir, script, language))     # and KnownWord.json's IGNORED entries

    # A word + a noun-making suffix whose word the learner knows — 利用者 when 利用 is known — is still a
    # word to learn (its card, its reading), but it sits lower on the list and is no unknown when choosing
    # example sentences (the user's "halfway + lower", U9, Patterns_Quality_Spec.md §6.8). So is a compound none
    # of whose parts is an unknown (上層部 with 上層 and 部 known); and a compound too rare for the list counts
    # toward its parts — which compounds are rare is fixed with the list's cut-off, before the aggregation
    # (LearningView, above).
    _joins = affix_joins() if language == 'ja' else {}
    _parts = compound_parts() if language == 'ja' else {}
    # Idioms and set phrases on the list (logic.phrase_rows, Japanese; app/phrases.py and below). Off, the phrases are
    # never read and every output is what it was without them.
    _phrase_set = None
    if language == 'ja' and LOGIC.get("phrase_rows", True):
        try:
            from app import phrases as _phrases
            _phrase_set = _phrases.load()
        except Exception as e:
            print(f"Warning: the set phrases could not be read ({e}); the list holds words only.")

    def _known(lr):
        """Does the learner know or ignore `lr`, as this run started?"""
        return lr in known_words_initial or lr[0] in known_lemmas_initial or lr[0] in ignore_list

    def _readable(lr, known_tuples, known_lemmas):
        """Is `lr` read already with these known words — through its known word, or as a compound of them?"""
        if lr[0] not in _joins and lr not in _parts:
            return False                # neither kind of word: most of them, decided here
        return _view.readable(lr, lambda key: key in known_tuples or key[0] in known_lemmas or key[0] in ignore_list)

    # Load all yomitan frequency lists (discovered above; contents read here on a real run only).
    freq_data = {}
    for list_name, filepath in sorted(available_freq_lists.items()):
        freq_data[list_name] = load_yomitan_frequency_list(filepath, script, language)
    print(f"Found {len(freq_data)} frequency lists: {', '.join(sorted(freq_data.keys()))}")

    # Per-file (lemma, reading) counts captured during aggregation and reused by the
    # progressive pass, so the whole library is tokenized once instead of twice.
    file_token_cache = {}

    # --- Per-sentence provenance ("which file did this example come from?") --------------------- #
    # Candidate sentences carry an INDEX into these tables rather than a path string: a large library
    # holds hundreds of thousands of candidates, and interning keeps that to one int each.
    source_list = []            # idx -> {"path": <rel>, "abs": <abs>, "name": <basename>, "type": ...}
    source_index = {}           # abs_path -> idx
    src_audio_rank = []         # idx -> 0 youtube | 1 other audio | 2 text (see _source_idx)

    def _source_idx(path, stype):
        idx = source_index.get(path)
        if idx is None:
            idx = len(source_list)
            source_index[path] = idx
            source_list.append({
                "path": os.path.relpath(path, data_dir).replace("\\", "/"),
                # Absolute path so the report's badge can put something on the clipboard that
                # pastes straight into Explorer. The CSVs keep the RELATIVE path (portable, and
                # what an exported Anki card should carry).
                "abs": os.path.abspath(path),
                "name": os.path.basename(path),
                "type": stype,
            })
            # Parallel list, not a dict lookup: this is read inside sort keys over hundreds of
            # thousands of candidates, and a list index is the cheapest thing available.
            # 0 = YouTube (badge opens the video at that second), 1 = other audio (names an
            # episode you must then find — bilibili.tv too: its badge opens the episode, but there
            # is no verified way to start it at the moment), 2 = text.
            src_audio_rank.append(0 if stype == "youtube" else
                                  (1 if stype in ("subtitle", "bilibili") else 2))
        return idx

    def _sentences_of(file_path):
        """A file's tokenized sentences: cached in the store (fresh for changed files, reused otherwise), else
        tokenized here."""
        if _store is None:
            return tokenizer.tokenize_sentences(extract_text(file_path, language))
        sentences = _store.file_tokens(file_path)
        # Safety net: an empty result for a NON-empty file means the cached blob was unreadable
        # (disk damage) while its (mtime,size) still matched, so reconcile didn't refresh it.
        # Re-tokenize directly rather than silently drop the whole file's contribution.
        if not sentences:
            try:
                if os.path.getsize(file_path) > 0:
                    sentences = tokenizer.tokenize_sentences(extract_text(file_path, language))
            except OSError:
                pass
        return sentences

    def _floor_count(total_tokens, own_freqs):
        """The word-selection floor (replaces the retired raw min_freq default): a density band's ppm floor as a
        concrete occurrence count in a library of `total_tokens`. Precedence:
          1. explicit --min-freq override (raw count),
          2. coverage mode (only drop one-offs; target_coverage handles the rest downstream),
          3. density band (the default): max(min_count, band ppm -> count).
        `own_freqs()`: this run's own distribution, for automatic rarity when the store can't be read."""
        if MIN_FREQ > 0:
            return MIN_FREQ
        if args.target_coverage > 0:
            return SELECT_MIN_COUNT
        band, why = SELECT_BAND, ""
        if SELECT_AUTO:
            # Automatic rarity: the RAREST band whose list holds auto_max_words words or fewer
            # (word_selection.auto_band), decided on the numbers the Rarity slider shows —
            # token_index.preview_frequencies, the dashboard's own recipe, over this run's store — so
            # the band the dashboard shows is the band this run uses. It picks the band only: the list
            # itself keeps this run's own ignore set. Without the store, this run's own counts.
            freqs = None
            if _store is not None:
                try:
                    freqs = _token_index.preview_frequencies(_store, language, user_files_dir, script)
                except Exception as e:
                    # Open, but unreadable now (locked, an I/O error, a damaged table): the same as no
                    # store. Keeping the hand-picked band instead stamped this run current on a band
                    # the dashboard doesn't show (I3) — the band isn't in the run signature, so every
                    # later Generate skipped.
                    print(f"Warning: automatic rarity could not read the token store ({e}); "
                          f"deciding on this run's own counts.")
            remembered = (_sig_parts or {}).get("auto_band")
            try:
                if freqs is None:
                    freqs = own_freqs()
                previews = word_selection.band_previews(freqs, SELECT_BANDS_PPM, SELECT_MIN_COUNT)
                auto = word_selection.auto_band(previews, SELECT_AUTO_MAX_WORDS, remembered=remembered)
                plain = word_selection.auto_band(previews, SELECT_AUTO_MAX_WORDS)
            except Exception as e:
                print(f"Warning: automatic rarity could not pick a band ({e}); keeping '{SELECT_BAND}'.")
                auto = None
            if auto is not None:
                band, why = auto, f" (automatic: the rarest band with {SELECT_AUTO_MAX_WORDS} words or fewer)"
                if auto != plain:
                    why = f" (automatic: kept until its list passes {word_selection.DEFAULT_AUTO_STEP_BACK_WORDS} words)"
                _auto_pick.update(band=auto, words=previews[auto]["word_count"])
        floor = word_selection.band_floor_count(band, total_tokens, SELECT_BANDS_PPM, SELECT_MIN_COUNT)
        print(f"Configuration: Selection band '{band}'{why} -> keep count >= {floor:.2f} "
              f"(of {total_tokens} library tokens).")
        return floor

    # --- The floor, fixed BEFORE the aggregation --------------------------------------------------- #
    # The library's size and each word's uses come from the token store — its totals and per-word counts, the
    # numbers the Rarity slider shows — and decide the cut-off and which compounds are too rare for the list,
    # once: nothing a rare compound then gives its parts can move a word across it. Without the store, a first
    # pass counts the same sentences the aggregation then reads (Japanese, where there is a compound table);
    # with nothing to give back, the aggregation's own totals, as always.
    _counts, floor_count, total_tokens = None, None, 0
    _bound_counts = None        # {(lemma, reading): uses that are pieces of something else} — one-kanji words (above)
    _phrase_table = None        # the set phrases, counted as the store counts them, when the store can't be read
    _phrases_found = {}         # file path -> its set phrases as that first pass found them (Store.phrase_matches)
    if _store is not None:
        try:
            _counts, total_tokens = _store.word_counts()
            _bound_counts = _store.bound_counts()
        except Exception as e:
            print(f"Warning: could not read the token store's counts ({e}); counting the library first.")
            _counts = _bound_counts = None
    if _counts is None and _parts:
        _counts, total_tokens, _bound_counts = Counter(), 0, Counter()
        tallies = [] if _phrase_set is not None else None
        for file_path, _label, _weight, _type in found_files:
            sentences = _sentences_of(file_path)
            if tallies is not None:
                sentences, flat = list(sentences), []
                tallies.append(_phrases.tally(sentences, _phrase_set, flat))
                _phrases_found[file_path] = (len(sentences), flat)
            for s_text, s_tokens in sentences:
                for lemma, reading, surface, _orth in s_tokens:
                    if has_target_language(lemma, language) or has_target_language(surface, language):
                        _counts[(lemma, reading)] += 1
                        total_tokens += 1
                if language == 'ja':
                    for i in bound_uses(s_text, s_tokens):
                        _bound_counts[(s_tokens[i][0], s_tokens[i][1])] += 1
        if tallies is not None:
            _phrase_table = _phrases.table(tallies, _phrase_set)
    if _counts is not None:
        floor_count = _floor_count(total_tokens, lambda: _token_index.unknown_distribution(
            _counts, total_tokens, known_words_initial, known_lemmas_initial, ignore_list, skip_singles, language,
            _phrase_table, _bound_counts))
    _view = LearningView(_counts, floor_count or 0, _known, parts=_parts, joins=_joins,
                         tagger=tokenizer.tagger if language == 'ja' else None)
    # Every compound too rare for the list, as one set: a sentence holding none — nearly all — is passed over in C.
    _rare = frozenset(key for key in _parts if _view.rare(key)) if _counts is not None else frozenset()
    # The words each file met inside a rare compound, for the progressive pass (a word's row sits in the file
    # it is first met in — inside a compound too).
    file_credit_cache = {}
    # Each file's uses of one-kanji list words that are pieces of something else there (三年's 年), likewise: they are
    # nothing to learn in that file.
    file_piece_cache = {}
    # The unknowns read already with the known words the run started with (利用者 with 利用 known, 上層部 with its parts
    # known): those don't change during the aggregation, so each word is judged once — `_judged` — and a sentence's
    # difficulty below takes a set lookup per word.
    _judged, _read_already = set(), set()
    # (lemma, reading) -> (what the aggregation's per-token tests say of the word, its key as first met), asked once per
    # word (below).
    _word_state = {}
    # An example sentence's lengths, the same for every sentence of the run.
    min_chars = LOGIC.get("context", {}).get("min_chars", 10)
    preferred_max_chars = LOGIC.get("context", {}).get("preferred_max_chars", 50)
    max_chars = LOGIC.get("context", {}).get("max_chars", 150)

    # --- Idioms and set phrases on the list (logic.phrase_rows, Japanese; app/phrases.py) ------------------------- #
    # The tokenizer never joins a phrase, so the dictionary's set phrases are found in each sentence's words, and one the
    # library meets as often as the cut-off asks of a word is a row of its own (気がする, 腑に落ちる, もしかしたら) — its
    # Word the lemmas joined (気が付く), its Orth the commonest spelling. Additive: every word keeps its uses, coverage
    # and the cut-off stay the tokens', and a phrase adds no unknown to another word's sentence — it only puts that
    # sentence after cleaner ones among the word's examples — except that a word living only inside its phrase (腑 in
    # 腑に落ちる) gives the phrase its uses there. A phrase is ready once every other real word in it is known
    # (phrases.waiting): one made of known words sits lower, as 利用者 does; one waiting for a new word counts that word
    # as an unknown in its own sentences, and sorts after it. Off (and for Chinese) nothing here runs (`_phrase_set`,
    # read before the cut-off).
    phrase_stats = {}           # phrase index -> its entry, shaped as a word's in word_stats
    _phrase_known = {}          # phrase index -> known or ignored as a whole (phrases.known_whole)
    _phrase_waits = {}          # phrase index -> (the words it waits for, every real word in it known)
    _phrase_bound = {}          # phrase index -> the positions of the words that live only inside it
    file_phrase_cache = {}      # file path -> {phrase index: uses}, for the progressive pass
    file_bound_cache = {}       # file path -> {(lemma, reading): uses given to a phrase}, likewise

    def _readable_now(lr):
        """Known, ignored or read already with the known words the run started with — a phrase's word, for readiness."""
        return _known(lr) or _readable(lr, known_words_initial, known_lemmas_initial)

    def _phrase_facts(index):
        """(the phrase, what it waits for, the positions of its bound words) — worked out once per phrase."""
        phrase = _phrase_set.entry(index)
        waits = _phrase_waits.get(index)
        if waits is None:
            # A one-kanji word the list offers is waited for like any word (手に入れる waits for 手); one it never offers
            # never is.
            waits = _phrase_waits[index] = _phrases.waiting(phrase, _readable_now, lambda lr: not _never(lr))
            _phrase_bound[index] = _phrases.bound_at(phrase)
        return phrase, waits, _phrase_bound[index]

    # Each file's set phrases as the token store's last index found them (or this run's first pass, above), so its
    # sentences are not searched for them again — each file's let go once read.
    if _phrase_set is not None and _store is not None and not _phrases_found:
        _phrases_found = _store.phrase_matches([file_path for file_path, _l, _w, _t in found_files])

    def _phrases_at(file_path, sentences):
        """{sentence number: [(start, end, index)]} — a file's set phrases as they were found before in these very
        tokens; None when they weren't or don't fit the tokens (the file changed since): they are searched for here
        (PhraseSet.find)."""
        held = _phrases_found.pop(file_path, None)
        if held is None or held[0] != len(sentences):
            return None
        at, entries, numbers = {}, _phrase_set.entries, iter(held[1])
        try:
            for number, start, end, index in zip(numbers, numbers, numbers, numbers):
                tokens, key = sentences[number][1], entries[index].key
                if end - start != len(key) or tokens[start][0] != key[0] or tokens[end - 1][0] != key[-1]:
                    return None
                found = at.get(number)
                if found is None:
                    at[number] = [(start, end, index)]
                else:
                    found.append((start, end, index))
        except (IndexError, TypeError):
            return None
        return at

    # How often each phrase is met, when every file's phrases were found before (above): one met less often than the
    # cut-off is never a row, so its sentences are never weighed as its examples.
    _phrase_uses = None
    if _phrase_set is not None and floor_count is not None and all(
            file_path in _phrases_found for file_path, _l, _w, _t in found_files):
        _phrase_uses = Counter()
        for _sentences, flat in _phrases_found.values():
            _phrase_uses.update(flat[3::4])

    def _unknown_counts(lrs):
        """The running counts, ascending, of the words in `lrs` not read already — what a candidate example's cost is
        weighed on (rolling_context_cost), as a word's are below."""
        fresh = lrs.difference(_judged)
        if fresh:
            _judged.update(fresh)
            _read_already.update(lr for lr in fresh if _readable(lr, known_words_initial, known_lemmas_initial))
        return sorted([word_stats[lr]["total_count"] if lr in word_stats else 0
                       for lr in lrs if lr not in _read_already])

    def _could_take(entry, short, long, src_idx, file_is_spoken, is_over_hard_max):
        """Could a sentence of these lengths join a phrase's examples (`_offer_context`) at any cost? Not when both
        pools are full of sentences at least as good as its best case (no unknown) — then its cost isn't worked out."""
        candidates = entry["candidate_contexts"]
        if len(candidates) < 30 or (short, long, 0) < _CONTEXT_RANK(candidates[-1]):
            return True
        if not (ENSURE_AUDIO_EXAMPLE and file_is_spoken and not is_over_hard_max):
            return False
        audio_pool = entry["audio_contexts"]
        if len(audio_pool) < 12:
            return True
        worst = audio_pool[-1]
        return (src_audio_rank[src_idx], short, long, 0) < (src_audio_rank[worst[5]], worst[0], worst[1], worst[2])

    def _offer_context(entry, new_ctx, file_is_spoken, is_over_hard_max):
        """A candidate example sentence for a phrase row, kept as a word's are (below): the audio pool, then the best
        30 by length and cost, the phrase's first sentence as its fallback."""
        s_text = new_ctx[4]
        if ENSURE_AUDIO_EXAMPLE and file_is_spoken and not is_over_hard_max:
            audio_pool = entry["audio_contexts"]
            if not any(c[4] == s_text for c in audio_pool):
                audio_pool.append(new_ctx)
                audio_pool.sort(key=lambda x: (src_audio_rank[x[5]], x[0], x[1], x[2]))
                del audio_pool[12:]
        candidates = entry["candidate_contexts"]
        if len(candidates) >= 30 and (new_ctx[0], new_ctx[1], new_ctx[2]) >= _CONTEXT_RANK(candidates[-1]):
            return
        if s_text in [c[4] for c in candidates]:
            return
        if not entry["first_context"]:
            entry["first_context"] = new_ctx
        if is_over_hard_max:
            return
        candidates.append(new_ctx)
        candidates.sort(key=_CONTEXT_RANK)
        del candidates[30:]

    # The plan file's (written at the end): per file, in order, its uses of each word as counted below — credits too —
    # in the order first counted, and the spellings each word and phrase was met in there, in the order met, where they
    # aren't simply the ones it was first met in anywhere (`_unusual_spellings`). Kept for the words that can reach the
    # list only (`_plan_keys`): those whose uses can reach the cut-off — the store's count less its one-kanji pieces,
    # plus the uses of every rare compound that counts toward it, bound a word's counted uses. Nearly every word met is
    # in the long tail below the cut-off; the writer checks every list word's uses add up. None: the cut-off is fixed
    # only after the aggregation — every word.
    plan_files = []
    _plan_keys = None
    if _counts is not None and floor_count is not None:
        _pieces = (_bound_counts or {}) if skip_singles else {}     # pieces count when the one-kanji rule is off
        _room = Counter()
        for compound in _rare:
            n = _counts.get(compound)
            if n:                       # (most of the table's compounds aren't in the library at all)
                for part in _view.credits(compound):
                    _room[part] += n
        _plan_keys = {key for key in set(_counts).union(_room)
                      if _counts.get(key, 0) - _pieces.get(key, 0) + _room.get(key, 0) >= floor_count}

    # --- AGGREGATION PASS ---
    for seq_idx, (file_path, label, weight, source_type) in enumerate(found_files, 1):
        _progress("Reading your files", seq_idx - 1, len(found_files))
        try:
            print(f"Processing {os.path.basename(file_path)}...")
        except UnicodeEncodeError:
            print(f"Processing file {seq_idx}...")
        src_idx = _source_idx(file_path, source_type)

        # Cached tokenized sentences from the store (fresh for changed files, reused otherwise).
        sentences = _sentences_of(file_path)

        file_total_words = 0
        file_known_words = 0
        # Multiset of every (lemma, reading) this file yields — mirrors tokenizer.tokenize()
        # exactly (built in first-appearance order) for the progressive pass to reuse.
        file_counter = Counter()
        file_count = file_counter.get
        file_credits = Counter()                      # the words this file meets inside a rare compound
        file_phrases, file_bound = Counter(), Counter()   # its set phrases, and the uses its bound words give them
        file_pieces = Counter()     # one-kanji list words' uses here that are pieces of something else (三年's 年)
        file_unlisted = {}          # (lemma, reading) -> {spelling: uses}: one-kanji words the list can't offer
        file_uses = {}              # (lemma, reading) -> [this file, its counted uses here, spellings]: the plan file's
        file_phrase_spelled = {}    # phrase index -> (spelling, surface) met here, or the dicts of them (the plan file)
        file_basename = os.path.basename(file_path)   # constant per file — hoisted out of the token loop
        # Modality inputs, also constant per file (see app/modality.py).
        file_is_spoken = source_type in ("subtitle", "youtube", "bilibili")
        file_series = _series_name(file_path, data_dir)
        library_series.add(file_series)
        if file_is_spoken:
            spoken_file_count += 1
        # The set phrases of each sentence, as they were found before (above) — else searched for below.
        found_at = None
        if _phrase_set is not None:
            sentences = list(sentences)
            found_at = _phrases_at(file_path, sentences)

        for s_no, (s_text, s_tokens) in enumerate(sentences):
            # 1. Identify unknowns and calculate cost (relative to constant initial knowns)
            sentence_unknowns = []
            unknown_keys = []
            named = None        # [(token number, key, spelling)]: this sentence's words for the file's line (below)
            for t_no, (lemma, reading, surface, orth) in enumerate(s_tokens):
                # What the word is, asked once per word (`_word_state`), not per token: this loop runs over every
                # token of the library. Bit 1: known (KnownWord.json) or ignored; bit 2: a lemma with no Target
                # characters (e.g. SSA/ASS tags like {\an8}, timestamps, markup, or other ASCII-only tokens) — such a
                # token counts toward the totals, or as an unknown, only when its surface has some. With the
                # one-character rule on (§ One-character words): bit 4, a one-character word the list never offers
                # (bit 16: one the report names for its file); bit 8, a one-kanji word it offers where it stands free.
                # Kept with the word's key as first met, which every file's counts and sentences then share: each file's
                # tokens are read anew from the store, and its own copy of each key (and of its text) stayed in memory
                # with the file's counts until the run ended — some 150 MB on a large library.
                known = _word_state.get((lemma, reading))
                if known is None:
                    key = (lemma, reading)
                    state = ((0 if has_target_language(lemma, language) else 2)
                             + (1 if (lemma in ignore_list or key in known_words_initial
                                      or lemma in known_lemmas_initial) else 0))
                    kind = single_kind(key, skip_singles)
                    if kind:
                        state += 8 if kind == 2 else 4 + (16 if not_on_list(key) else 0)
                    known = _word_state[key] = (state, key)
                state, key = known
                # Cache EVERY token (before the target-language filter below) so the cached
                # multiset matches what tokenizer.tokenize() yields for the progressive pass.
                file_counter[key] = file_count(key, 0) + 1
                if state & 2 and not has_target_language(surface, language):
                    continue

                file_total_words += 1
                if state & 1:
                    file_known_words += 1
                    continue
                if state & 12:
                    # A one-character word counts only where the list can offer it: never one it doesn't list, never
                    # a one-kanji word standing as a piece of something else. Neither is a use, an example or an
                    # unknown here — nothing to learn, so known to the file's coverage, as in the progressive pass.
                    if state & 4:
                        file_known_words += 1
                        # Named for the file where it stands on its own (never 卍 in a term's run, 条 after 第一) —
                        # once this sentence's set phrases are known (below).
                        if state & 16 and not bound_uses(s_text, s_tokens, only=(t_no,)):
                            if named is None:
                                named = []
                            named.append((t_no, key, orth))
                        continue
                    if bound_uses(s_text, s_tokens, only=(t_no,)):     # asked of this word alone
                        file_known_words += 1
                        file_pieces[key] += 1
                        continue

                # It's an unknown word!
                sentence_unknowns.append((lemma, reading, surface, orth))
                unknown_keys.append(key)

            # Unique unknowns in this sentence.
            unique_lrs = set(unknown_keys)
            # The words the sentence can be an example FOR: those that stand in it on their own. A compound too
            # rare for the list gets none (it is never listed), and nor do the parts it counts toward. How hard the
            # sentence is: such a compound is its parts when all of them are free (LearningView.units).
            targets = unique_lrs
            rare = None if _rare.isdisjoint(unique_lrs) else [lr for lr in unique_lrs if lr in _rare]
            if rare:
                targets = unique_lrs.difference(rare)
                unique_lrs = {unit for lr in unique_lrs for unit in _view.units(lr)
                              if not (_known(unit) or _never(unit))}

            # The set phrases here (above): each one counted for its row as a word is; a word living only inside its
            # phrase gives the phrase that use (no count, score or example of its own from it — it still makes the
            # sentence harder), so a sentence holding it only there is no example for it either.
            if found_at is not None:
                found = found_at.get(s_no, ())
            else:
                found = _phrase_set.find(s_tokens, s_text) if _phrase_set is not None else ()
            taken = None
            if found:
                for start, end, index in found:
                    phrase, _waits, bound = _phrase_facts(index)
                    if bound:
                        if taken is None:
                            taken = Counter()
                        for k in bound:
                            taken[(s_tokens[start + k][0], s_tokens[start + k][1])] += 1
                    orth, written = _phrases.spellings(s_tokens, start, end, phrase)
                    entry = phrase_stats.get(index)
                    if entry is None:
                        entry = phrase_stats[index] = word_stats.default_factory()
                    entry["score"] += weight
                    entry["total_count"] += 1
                    entry["sources"].add(file_basename)
                    entry["surface"] = written
                    orths, surfaces = entry["orths"], entry["surfaces"]
                    spelled_anew = orth not in orths or written not in surfaces
                    orths[orth] += 1
                    surfaces[written] += 1
                    if label == "HighPriority": entry["high_count"] += 1
                    elif label == "LowPriority": entry["low_count"] += 1
                    elif label == "GoalContent": entry["goal_count"] += 1
                    if file_is_spoken: entry["spoken_count"] += 1
                    entry["series"].add(file_series)
                    if seq_idx < entry["min_seq"]:
                        entry["min_seq"] = seq_idx
                    file_phrases[index] += 1
                    # The plan file's spellings, for a phrase met as often as a row needs (`_phrase_uses`, as words'
                    # `_plan_keys` below).
                    if _phrase_uses is None or _phrase_uses[index] >= floor_count:
                        met = file_phrase_spelled.get(index)
                        if met is None:
                            file_phrase_spelled[index] = (orth, written)
                        elif met.__class__ is tuple:
                            if met[0] != orth or met[1] != written:
                                file_phrase_spelled[index] = [{met[0]: None, orth: None}, {met[1]: None, written: None}]
                        else:
                            met[0][orth] = None
                            met[1][written] = None
                    # Known as a whole? Asked again only for a spelling not met before.
                    if spelled_anew and not _phrase_known.get(index):
                        _phrase_known[index] = _phrases.known_whole(phrase, (orth, written), known_words_initial,
                                                                    known_lemmas_initial, ignore_list)
                if taken:
                    file_bound.update(taken)
                    uses = Counter((t[0], t[1]) for t in sentence_unknowns if (t[0], t[1]) in taken)
                    gone = {key for key, n in uses.items() if n <= taken[key]}
                    if gone:
                        targets = targets - gone
            if named:
                # The file's line names a word the list can't offer — never where it lives only inside a set phrase
                # that takes the use (腑 in 腑に落ちる): it is learned with the phrase, as on the list.
                inside = {start + k for start, _end, index in found for k in _phrase_facts(index)[2]} if found else ()
                for t_no, key, orth in named:
                    if t_no in inside:
                        continue
                    spelled = file_unlisted.get(key)
                    if spelled is None:
                        spelled = file_unlisted[key] = Counter()
                    spelled[orth] += 1

            # 2. Update Stats for all unknown tokens in this sentence (a one-character word only where the list can
            # offer it — above)
            for key, (lemma, reading, surface, orth) in zip(unknown_keys, sentence_unknowns):
                if taken and taken.get(key):
                    taken[key] -= 1      # a use its phrase has taken (above)
                    continue

                entry = word_stats[key]
                entry["score"] += weight
                entry["total_count"] += 1
                entry["sources"].add(file_basename)
                entry["surface"] = surface
                entry["orths"][orth] += 1
                entry["surfaces"][surface] += 1
                if label == "HighPriority": entry["high_count"] += 1
                elif label == "LowPriority": entry["low_count"] += 1
                elif label == "GoalContent": entry["goal_count"] += 1
                if file_is_spoken: entry["spoken_count"] += 1
                entry["series"].add(file_series)
                
                # Track first appearance sequence
                if seq_idx < entry["min_seq"]:
                    entry["min_seq"] = seq_idx
                # The plan file's (below): the word's uses here and the spellings met here, on a record its entry
                # holds for the file it was last met in (no lookup by key per use; taken off after the pass). False:
                # a word that can't reach the list (`_plan_keys`), decided once.
                plan = entry.get("_plan")
                if plan is not False:
                    if plan is None or plan[0] != seq_idx:
                        if plan is None and _plan_keys is not None and key not in _plan_keys:
                            entry["_plan"] = False
                        else:
                            file_uses[key] = entry["_plan"] = [seq_idx, 1, (orth, surface)]
                    else:
                        plan[1] += 1
                        met = plan[2]
                        if met is None:                     # met here as a credit first (below)
                            plan[2] = (orth, surface)
                        elif met.__class__ is tuple:
                            if met[0] != orth or met[1] != surface:
                                plan[2] = [{met[0]: None, orth: None}, {met[1]: None, surface: None}]
                        else:                               # spellings met here, in order (a dict keeps the first)
                            met[0][orth] = None
                            met[1][surface] = None

            if rare:
                # Each use of a rare compound is also a use of its free parts on the list — their count, score,
                # tiers, sources and the file they are first met in; never an example sentence (above).
                rare = set(rare)
                for lemma, reading, _surface, _orth in sentence_unknowns:
                    if (lemma, reading) not in rare:
                        continue
                    for part in _view.credits((lemma, reading)):
                        file_credits[part] += 1
                        if _known(part) or _never(part):
                            continue
                        entry = word_stats[part]
                        entry["score"] += weight
                        entry["total_count"] += 1
                        entry["sources"].add(file_basename)
                        if label == "HighPriority": entry["high_count"] += 1
                        elif label == "LowPriority": entry["low_count"] += 1
                        elif label == "GoalContent": entry["goal_count"] += 1
                        if file_is_spoken: entry["spoken_count"] += 1
                        entry["series"].add(file_series)
                        if seq_idx < entry["min_seq"]:
                            entry["min_seq"] = seq_idx
                        plan = entry.get("_plan")
                        if plan is not False:
                            if plan is None or plan[0] != seq_idx:
                                if plan is None and _plan_keys is not None and part not in _plan_keys:
                                    entry["_plan"] = False
                                else:
                                    file_uses[part] = entry["_plan"] = [seq_idx, 1, None]
                            else:
                                plan[1] += 1

            # Each phrase the learner doesn't know as a whole takes the sentence as a candidate example. Its unknowns
            # are the sentence's unknown words outside it, and the words it waits for (never the i+1 of a phrase whose
            # own word is still new: 本題に入る while 本題 is); a word's examples keep their own unknowns (above).
            marks = unk_freqs = None
            if found:
                marks = tuple(index for _start, _end, index in found)
                unknown_uses = None         # the sentence's unknown words, each with its uses here
                is_too_short = 1 if len(s_text) < min_chars else 0
                is_too_long = 1 if len(s_text) > preferred_max_chars else 0
                is_over_hard_max = len(s_text) > max_chars
                for start, end, index in found:
                    if _phrase_known.get(index) or (_phrase_uses is not None and _phrase_uses[index] < floor_count):
                        continue
                    entry = phrase_stats[index]
                    if not _could_take(entry, is_too_short, is_too_long, src_idx, file_is_spoken, is_over_hard_max):
                        continue
                    if unknown_uses is None:
                        unknown_uses = Counter(unknown_keys)
                    waits = _phrase_waits[index][0]
                    inside = [(t[0], t[1]) for t in s_tokens[start:end]]
                    if not waits and unknown_uses.keys().isdisjoint(inside):
                        # No new word inside it and none waited for: the sentence's unknowns are its words' own (3.).
                        if unk_freqs is None:
                            unk_freqs = _unknown_counts(unique_lrs)
                        lrs, freqs = unique_lrs, unk_freqs
                    else:
                        # The unknowns outside the phrase: a word met only inside it is the phrase's own.
                        lrs = set(unknown_uses)
                        for lr in inside:
                            if lr in lrs and unknown_uses[lr] <= inside.count(lr):
                                lrs.discard(lr)
                        lrs.update(waits)
                        if rare:
                            lrs = ((lrs - rare)
                                   | {unit for lr in lrs & rare for unit in _view.units(lr) if not _known(unit)})
                        freqs = _unknown_counts(lrs)
                    _offer_context(entry, (is_too_short, is_too_long, rolling_context_cost(entry["total_count"], freqs),
                                           lrs, s_text, src_idx, marks),
                                   file_is_spoken, is_over_hard_max)

            # 3. Update Best Contexts (once per unique unknown per sentence)
            if not targets:
                continue        # an example for no word (most sentences, once most words are known)
            is_too_short = 1 if len(s_text) < min_chars else 0
            
            is_too_long = 1 if len(s_text) > preferred_max_chars else 0
            # Hard cap: sentences longer than this are excluded from the candidate pool (they
            # make poor examples); a word's own/original sentence is still kept as a fallback.
            is_over_hard_max = len(s_text) > max_chars

            # Running frequency of each of this sentence's unknowns (ascending) — used to score
            # each candidate by its rarer-than-target co-words (see rolling_context_cost). A word the
            # learner can read through its known word (利用者) is not one of them (U9, above).
            if unk_freqs is None:           # (worked out already when a set phrase here needed it, above)
                if not _judged.issuperset(unique_lrs):
                    new = unique_lrs.difference(_judged)
                    _judged.update(new)
                    _read_already.update(lr for lr in new if _readable(lr, known_words_initial, known_lemmas_initial))
                unk_freqs = sorted(
                    word_stats[lr]["total_count"] if lr in word_stats else 0
                    for lr in unique_lrs
                    if lr not in _read_already
                )

            for (lemma, reading) in targets:
                entry = word_stats[(lemma, reading)]

                # Rank this candidate by how many of the sentence's OTHER unknown words are
                # rarer than this word — a proxy for how many stay unknown when the learner
                # reaches it (common co-words are learned first). Same buffer / fast-exit.
                cost = rolling_context_cost(entry["total_count"], unk_freqs)
                new_ctx = (is_too_short, is_too_long, cost, unique_lrs, s_text, src_idx)
                if marks:
                    new_ctx += (marks,)     # the phrases here: a new one puts the sentence after cleaner ones

                # The audio pool is filled FIRST, before any of the main pool's early-outs below.
                # Those exist to keep the best 30 sentences overall, and every one of them —
                # the full-pool fast exit especially — would also throw away the audio candidate
                # this feature exists to find. That is the whole reason the pool is separate:
                # gating it behind the main pool's decisions makes it silently useless for exactly
                # the book-heavy words that need it.
                if ENSURE_AUDIO_EXAMPLE and file_is_spoken and not is_over_hard_max:
                    audio_pool = entry["audio_contexts"]
                    if not any(c[4] == s_text for c in audio_pool):
                        audio_pool.append(new_ctx)
                        # YouTube first, then the usual length/cost ranking. A YouTube badge opens
                        # the video at the second the line is spoken, so hearing the example costs
                        # one click; a subtitle only names an episode you then have to find.
                        audio_pool.sort(key=lambda x: (
                            src_audio_rank[x[5]], x[0], x[1], x[2]))
                        # Roomier than it needs to be on purpose. This ordering is only an
                        # approximation — the real i+1 cost isn't known until selection, which
                        # re-scores every entry — so the pool's job is to keep enough plausible
                        # candidates for that choice to be a real one, not to make the choice.
                        del audio_pool[12:]


                # Optimization 1: Insertion Caching - Fast exit if list is full and new sentence is worse
                candidates = entry["candidate_contexts"]
                if len(candidates) >= 30:
                    worst_stored_ctx = candidates[-1]
                    # Compare only the first three sorting tuples (is_too_short, is_too_long, cost)
                    new_sorting_tuple = (new_ctx[0], new_ctx[1], new_ctx[2])
                    worst_sorting_tuple = (worst_stored_ctx[0], worst_stored_ctx[1], worst_stored_ctx[2])
                    
                    if new_sorting_tuple >= worst_sorting_tuple:
                        continue # No chance of beating the top 30, discard early!

                # Check if this exact sentence is already in candidate_contexts (Moved AFTER fast-path)
                if s_text in [c[4] for c in candidates]:
                    continue

                if not entry["first_context"]:
                    entry["first_context"] = new_ctx

                # Very long sentences make poor secondary examples — keep them only as the
                # word's own/original fallback (first_context above), not in the candidate pool.
                if is_over_hard_max:
                    continue

                candidates.append(new_ctx)
                # Sort initially by: length validity, then initial cost
                candidates.sort(key=_CONTEXT_RANK)
                # Keep up to 30 promising candidates
                del candidates[30:]

        
        file_token_cache[file_path] = file_counter
        plan_files.append(_plan_file(file_uses, word_stats, file_phrase_spelled, phrase_stats))
        if file_credits:
            file_credit_cache[file_path] = file_credits
        if file_phrases:
            file_phrase_cache[file_path] = file_phrases
        if file_bound:
            file_bound_cache[file_path] = file_bound
        if file_pieces:
            file_piece_cache[file_path] = file_pieces
        coverage = (file_known_words / file_total_words * 100) if file_total_words > 0 else 0
        file_stats.append({
            "File": os.path.basename(file_path),
            "Total Words": file_total_words,
            "Known Count": file_known_words,
            "Coverage (%)": round(coverage, 2)
        })
        if file_unlisted:
            # The one-kanji words here the list can't offer (§ One-character words) — a name read as a common noun
            # (スバル), a rare word (簪) — for the report to name, most used first: [spelling, lemma, uses where it stands
            # on its own], by lemma.
            by_lemma = {}
            for (lemma, _reading), spelled in file_unlisted.items():
                found = by_lemma.get(lemma)
                if found is None:
                    found = by_lemma[lemma] = Counter()
                found.update(spelled)
            file_stats[-1]["Not On List"] = sorted(
                ([max(spelled.items(), key=lambda item: (item[1], item[0]))[0], lemma, sum(spelled.values())]
                 for lemma, spelled in by_lemma.items()), key=lambda row: (-row[2], row[1]))[:UNLISTED_SHOWN]

    # (The token store stays open until the end of the run so we can record the run-signature.)
    _progress("Reading your files", len(found_files), len(found_files))
    _progress("Counting words")

    for entry in word_stats.values():
        entry.pop("_plan", None)        # the plan file's per-file records (above): no output carries them

    # U9's "lower": a word the learner can read through its known word (利用者) scores half — as does a compound
    # none of whose parts is an unknown (上層部).
    _halved = set()             # the keys scored half (the plan file's)
    for lr, entry in word_stats.items():
        if _readable(lr, known_words_initial, known_lemmas_initial):
            entry["score"] //= 2
            _halved.add(lr)

    # The set phrases met join the words, keyed as a word is — (Word, Reading): their lemmas and readings joined — so
    # every output below lists them the same way. No row for a phrase known or ignored as a whole, nor for one whose
    # lemmas joined are a word the library holds (the word keeps its row). A ready phrase whose real words are all
    # known scores half, as a word read through its known word does (利用者).
    phrase_keys = {}                # (Word, Reading) -> phrase index: the phrases this run may list
    # Rows two phrases share (甘い物好き spelled two ways): the one met last in the run holds it — an order the plan
    # file can't replay, so it names them.
    _shared_phrases = set()
    if phrase_stats:
        lemmas = ({key[0] for key in _counts} if _counts is not None
                  else {key[0] for counts in file_token_cache.values() for key in counts})
        for index, entry in phrase_stats.items():
            phrase = _phrase_set.entry(index)
            if _phrase_known.get(index) or phrase.word in lemmas:
                continue
            key = (phrase.word, phrase.reading)
            if key in phrase_keys:
                _shared_phrases.add(key)
            if _phrase_waits[index][1]:
                entry["score"] //= 2
                _halved.add(key)
            else:
                _halved.discard(key)        # the entry stored last holds the row (below), and its own half
            phrase_keys[key] = index
            word_stats[(phrase.word, phrase.reading)] = entry

    # --- The word-selection floor, when it could not be fixed before the aggregation ---
    # No store and no compound table (Chinese; Japanese before the table): nothing is given back, so the
    # aggregation's own totals and counts decide it, as they always did.
    if floor_count is None:
        total_tokens = sum(s['Total Words'] for s in file_stats)
        floor_count = _floor_count(total_tokens, lambda: {
            "total_tokens": total_tokens,
            "unknown": [(_token_index.make_key(l, r), e["total_count"]) for (l, r), e in word_stats.items()]})

    # Output Priority CSV
    rolling_known_tuples = set(known_words_initial)
    rolling_known_lemmas = set(known_lemmas_initial)

    # --- Recency reinforcement -------------------------------------------------------------- #
    # All else equal (same i+1 cost, same length), prefer the example sentence whose OTHER words you
    # met recently — the one that reinforces what you just studied instead of vocabulary from months
    # ago. "Recently" is measured in FILES: a co-word counts when it was first met in this word's
    # own file, or up to `recency_files` files earlier.
    #
    # Only words learned during THIS journey get an entry, so long-known vocabulary never counts as
    # reinforcement. Strictly a tiebreaker — it is the LAST key in both sort orders below, so it can
    # never promote a worse-i+1 or worse-length sentence.
    RECENCY_FILES = LOGIC.get("context", {}).get("recency_files", 1)
    _recency_on = RECENCY_FILES >= 0
    learned_at_file = {}       # (lemma, reading) -> the file index where the learner first meets it

    # --- Reading-vs-listening ------------------------------------------------------------------ #
    # The spoken-rank table is precomputed at build time (it depends only on unidic + the reference
    # corpora, both fixed then), so all that happens here is a dict lookup and a division per word.
    # Loaded once, lazily: a library with no matching words still pays nothing beyond the decode.
    _MODALITY_CFG = LOGIC.get("modality", {})
    _minutes_per_file = LOGIC.get("selection", {}).get("minutes_per_file",
                                                       word_selection.MINUTES_PER_FILE)
    _listening_hours = modality.listening_hours(spoken_file_count, _minutes_per_file)
    _library_series = len(library_series)
    try:
        from app import reference_data as _reference_data
        # The ranks are Japanese words' (spoken Japanese, through unidic): a Chinese word written like one
        # (描写, 研究) would take a Japanese word's rank and its 文 badge, so a Chinese run has none.
        _spoken_ranks = _reference_data.spoken_ranks() if language == 'ja' else {}
    except Exception as e:
        # Missing/corrupt generated data must never break a run — the column just stays blank.
        print(f"Warning: reading/listening reference data unavailable ({e}).")
        _spoken_ranks = {}

    # Roll the evidence up BY LEMMA before judging. word_stats is keyed by (lemma, reading), and
    # unidic hands the same word more than one reading — 差し伸べる arrives as both サシノベ and
    # サシノベル. Judged per entry, each sees only a share of the times you actually heard the word,
    # so a word you meet every 23 hours can look unheard twice over and get flagged twice. The
    # reference rank is per-lemma anyway, so the library evidence has to be too.
    _lemma_evidence = defaultdict(lambda: {"total": 0, "spoken": 0, "series": set()})
    for (_lemma, _rdg), _d in word_stats.items():
        _e = _lemma_evidence[_lemma]
        _e["total"] += _d.get("total_count", 0)
        _e["spoken"] += _d.get("spoken_count", 0)
        _e["series"].update(_d.get("series", ()))

    def _modality_of(lemma):
        """"reading" when a word is worth a reading-first card, else None. See app/modality.py.

        Takes the LEMMA only — every input now comes from the per-lemma roll-up above, so there is
        no per-(lemma, reading) entry left for a caller to pass in. Judging one entry's share of
        the evidence is the bug this replaced."""
        if not _spoken_ranks:
            return None
        ev = _lemma_evidence.get(lemma)
        if ev is None:
            return None
        return modality.classify(
            _spoken_ranks.get(lemma),
            ev["total"],
            spoken_count=ev["spoken"],
            series_count=len(ev["series"]),
            library_series=_library_series,
            listening_hours_total=_listening_hours,
            config=_MODALITY_CFG,
        )

    preliminary_rows = []
    for (lemma, reading), data in word_stats.items():
        if data["total_count"] < floor_count:
            continue

        # A phrase is looked up in the frequency lists as it is written (気がする), not as its lemmas joined.
        tier_labels = get_tier_label(_display_orth(lemma, data["orths"]) if (lemma, reading) in phrase_keys else lemma,
                                     freq_data)
        # Format tiers as "Source1:Tier1;Source2:Tier2" or "Outside" if not in any list
        tier_str = ";".join([f"{source}:{tier}" for source, tier in tier_labels]) if tier_labels else "Outside"
        source_display = group_sources(data["sources"])

        row = {
            "Word": lemma,
            "Orth": _display_orth(lemma, data["orths"]),
            "Forms": _display_forms(lemma, data["orths"], data["surfaces"]),
            "Reading": reading,
            "Tier": tier_str,
            "Score": data["score"],
            "Occurrences": data["total_count"],
            "Count (High)": data["high_count"],
            "Count (Low)": data["low_count"],
            "Count (Goal)": data["goal_count"],
            # "reading" = you'll meet this in text but essentially never hear it, so it wants a
            # reading-first card. Blank means hearable OR not enough evidence — deliberately not
            # a claim. NOT named "Context ..." : both report templates collect example sentences
            # with startsWith('Context '), and such a column would render as a bogus example.
            "Modality": _modality_of(lemma) or "",
            "Sources": source_display, # Moved to end
            "_MinSeq": data["min_seq"], # Helper for sorting
            "_CandidateContexts": data["candidate_contexts"],
            "_FirstContext": data["first_context"]
        }
        preliminary_rows.append(row)
        
    # Sort Logic: Primary = Score (Desc), Secondary = First Appearance (Asc) — and a phrase after the words it ties
    # with, so one waiting for a word never comes before it.
    preliminary_rows.sort(key=lambda x: (-x["Score"], x["_MinSeq"], (x["Word"], x["Reading"]) in phrase_keys))

    # The phrases listed so far down the list, for a sentence's new phrases (below). A phrase row adds only itself —
    # never its words, which keep their own places on the list.
    phrase_rows = {phrase_keys[(r["Word"], r["Reading"])] for r in preliminary_rows
                   if (r["Word"], r["Reading"]) in phrase_keys}
    rolling_known_phrases = set()

    _progress("Picking sentences")
    output_rows = []
    for r in preliminary_rows:
        target_lr = (r["Word"], r["Reading"])
        target_lemma = r["Word"]
        target_seq = r["_MinSeq"]       # the file where the learner first meets THIS word
        target_phrase = phrase_keys.get(target_lr)

        # Evaluate candidate contexts against rolling knowns
        evaluated_candidates = []
        seen_sentences = set()
        
        ctx_list = r["_CandidateContexts"]
        first_ctx_data = r.get("_FirstContext")
        if first_ctx_data and first_ctx_data not in ctx_list:
            ctx_list.insert(0, first_ctx_data)
            
        for ctx in ctx_list:
            sentence_text = ctx[4].strip()
            if not sentence_text or sentence_text in seen_sentences:
                continue
            seen_sentences.add(sentence_text)
            
            unique_lrs = ctx[3]
            unknown_count = 0
            recent_hits = 0
            for lr in unique_lrs:
                if lr == target_lr: continue
                if lr not in rolling_known_tuples and lr[0] not in rolling_known_lemmas:
                    # 利用者 once 利用 is known by this point of the list is no unknown (U9).
                    if _readable(lr, rolling_known_tuples, rolling_known_lemmas):
                        continue
                    unknown_count += 1
                    # Optimization 4: Fast-Fail Evaluation
                    # If strict i+1 mode is ON, any sentence > 0 unknowns is guaranteed garbage
                    if ONLY_I_PLUS_ONE and unknown_count > 0:
                        break
                elif _recency_on:
                    # A co-word the learner already knows: does it count as RECENTLY learned?
                    seq = learned_at_file.get(lr)
                    if seq is not None and 0 <= target_seq - seq <= RECENCY_FILES:
                        recent_hits += 1

            # If we fast-failed, don't even bother appending the evaluated candidate
            if ONLY_I_PLUS_ONE and unknown_count > 0:
                continue

            # A set phrase of the sentence still new at this point of the list (a phrase row further down, never this
            # row's own) makes it a less clean example: it goes after the sentences with as many unknowns and none.
            # Never an unknown of its own — an i+1 sentence stays i+1, so no word loses its last one.
            crowd = 0
            if len(ctx) > 6:
                crowd = sum(1 for index in set(ctx[6]) if index in phrase_rows and index != target_phrase
                            and index not in rolling_known_phrases)

            evaluated_candidates.append(
                (ctx[0], ctx[1], unknown_count, sentence_text, recent_hits, ctx[5], crowd))

            # Optimization 2: Early Exit
            # If we found enough "perfect" contexts (0 unknowns AND perfectly sized) we can stop evaluating.
            # With recency on we look at twice as many before stopping: the tiebreaker can only choose
            # among candidates we actually evaluated, so stopping at exactly max_contexts would leave
            # it nothing to choose between. Still bounded (candidate_contexts caps at 30).
            if unknown_count == 0 and not crowd and ctx[0] == 0 and ctx[1] == 0:
                perfect_count = sum(1 for c in evaluated_candidates
                                    if c[2] == 0 and not c[6] and c[0] == 0 and c[1] == 0)
                if perfect_count >= (args.max_contexts * 2 if _recency_on else args.max_contexts):
                     # Stop scanning constraints - we already have max perfect i+1s ready
                     break

        first_evaluated = None
        if first_ctx_data:
            first_text = first_ctx_data[4].strip()
            for c in evaluated_candidates:
                if c[3] == first_text:
                    first_evaluated = c
                    break

        i_plus_one_candidates = [c for c in evaluated_candidates if c[2] == 0]
        
        if ONLY_I_PLUS_ONE:
            if not i_plus_one_candidates:
                words_skipped_i_plus_one += 1
                continue # Skip this word entirely
                
            # Optimization 3: Explicit Length Sorting for Strict Mode
            # Ensure we still prioritize the best length even if all are i+1s
            # (-x[4]: recency reinforcement, last so it only breaks exact ties)
            # With the audio option on, prefer a hearable sentence among candidates that are
            # ALREADY equally good — never in place of quality. Every candidate here is i+1
            # already, so audio rank leads; length still breaks its ties. (x[6]: a new set phrase, above — first.)
            if ENSURE_AUDIO_EXAMPLE:
                i_plus_one_candidates.sort(
                    key=lambda x: (x[6], src_audio_rank[x[5]], x[0], x[1], -x[4]))
            else:
                i_plus_one_candidates.sort(key=lambda x: (x[6], x[0], x[1], -x[4]))
            selected_contexts = i_plus_one_candidates[:args.max_contexts]
        else:
            # Sort by: Fewest Unknowns, then Not Too Short, then Not Too Long, then recency
            # i+1 cost stays the first key with the option on, so quality is never traded for
            # convenience; audio only decides between sentences of equal difficulty. A new set phrase
            # (x[6], above) comes right after the unknowns.
            if ENSURE_AUDIO_EXAMPLE:
                evaluated_candidates.sort(
                    key=lambda x: (x[2], x[6], src_audio_rank[x[5]], x[0], x[1], -x[4]))
            else:
                evaluated_candidates.sort(key=lambda x: (x[2], x[6], x[0], x[1], -x[4]))
            
            selected_contexts = []
            if first_evaluated:
                selected_contexts.append(first_evaluated)
                if first_evaluated in evaluated_candidates:
                    evaluated_candidates.remove(first_evaluated)
                    
            for c in evaluated_candidates:
                if len(selected_contexts) >= args.max_contexts:
                    break
                selected_contexts.append(c)

        # --- Guarantee one example you can actually hear ---------------------------------------- #
        # A word can easily end up with five perfect examples that all came from books, leaving no
        # way to study it by ear. When the option is on, the LAST slot is given to the best audio
        # candidate — replacing that slot rather than adding a sixth, so max_contexts and the CSV
        # column count are unchanged.
        #
        # Three deliberate refusals: it does nothing when only one example is requested (the single
        # best sentence is worth more than an audio one), nothing when a selected sentence is
        # already audio, and nothing in strict i+1 mode unless the audio sentence is itself i+1 —
        # honouring i+1 is the stronger promise, so the slot is left as it is.
        if ENSURE_AUDIO_EXAMPLE and args.max_contexts >= 2 and selected_contexts:
            def _is_audio(src_idx):
                return (src_idx is not None and src_idx < len(source_list)
                        and source_list[src_idx]["type"] in ("subtitle", "youtube", "bilibili"))

            if not any(_is_audio(c[5]) for c in selected_contexts):
                chosen = {c[3] for c in selected_contexts}
                best = None
                for ctx in word_stats[target_lr]["audio_contexts"]:
                    s_text = ctx[4].strip()
                    if not s_text or s_text in chosen:
                        continue
                    # The pool is ordered by an APPROXIMATION made during aggregation, before we
                    # knew which words the learner would already have met by this point. So every
                    # candidate is re-scored here against the rolling knowns and the best one wins
                    # — taking the first in pool order would hand out a four-unknown sentence while
                    # a perfect one sat behind it.
                    unknowns = sum(1 for lr in ctx[3]
                                   if lr != target_lr
                                   and lr not in rolling_known_tuples
                                   and lr[0] not in rolling_known_lemmas
                                   and not _readable(lr, rolling_known_tuples, rolling_known_lemmas))
                    if ONLY_I_PLUS_ONE and unknowns > 0:
                        continue
                    # i+1 first, because an example you can actually read is worth more than a
                    # convenient one; then YouTube over other audio; then the usual lengths.
                    rank = (unknowns, src_audio_rank[ctx[5]], ctx[0], ctx[1])
                    if best is None or rank < best[0]:
                        best = (rank, (ctx[0], ctx[1], unknowns, s_text, 0, ctx[5]))

                if best is not None:
                    # Only displace an existing example when the slots are actually full —
                    # otherwise the audio one is free and nothing has to be given up for it.
                    if len(selected_contexts) < args.max_contexts:
                        selected_contexts.append(best[1])
                    else:
                        selected_contexts[-1] = best[1]

        for i in range(args.max_contexts):
            context_key = f"Context {i+1}"
            has_ctx = len(selected_contexts) > i
            context_val = selected_contexts[i][3].strip() if has_ctx else ""
            if context_val and args.language == "ja":
                context_val = strip_verse_number(context_val, tokenizer.tagger)
            r[context_key] = context_val
            # Where that sentence came from. Deliberately NOT named "Context Source N": both report
            # templates collect extra examples with startsWith('Context '), so such a column would
            # be rendered as another example sentence.
            src_val = ""
            if has_ctx:
                _si = selected_contexts[i][5]
                if _si is not None and _si < len(source_list):
                    src_val = source_list[_si]["path"]
            r[f"Src {i+1}"] = src_val

            # Save back to data dictionary for progressive report and json dumping
            data = word_stats[(r["Word"], r["Reading"])]
            data[f"final_context_{i+1}"] = context_val
            data[f"final_src_{i+1}"] = src_val
        # Add to rolling known list and output
        if target_phrase is not None:
            rolling_known_phrases.add(target_phrase)     # the phrase alone, never its words (above)
        else:
            rolling_known_tuples.add(target_lr)
            rolling_known_lemmas.add(target_lemma)
            # Record WHERE it was learned, so later words can prefer sentences that reuse it.
            learned_at_file[target_lr] = target_seq
        
        del r["_CandidateContexts"] # Cleanup
        if "_FirstContext" in r:
            del r["_FirstContext"]
        output_rows.append(r)
        
    _progress("Writing your list")          # results/ is written from here on: a cancel waits for the end (W1.3)
    df = pd.DataFrame(output_rows)
    # The listed words, once the list is written; None: no list, so nothing below is held back. Bound here rather
    # than tested with `in locals()`, which copies every local of this function on each test (a word, per file).
    valid_lrs = None
    if not df.empty:
        # Drop the helper key if we added it (we need to add it to row first)
        df_display = df.drop(columns=["_MinSeq"])
        
        # TARGET COVERAGE LOGIC
        if args.target_coverage > 0:
            total_tokens = sum(s['Total Words'] for s in file_stats)
            current_known = sum(s['Known Count'] for s in file_stats)
            
            if total_tokens > 0:
                current_pct = (current_known / total_tokens) * 100
                print(f"Current Cumulative Coverage: {current_pct:.2f}% (Target: {args.target_coverage}%)")
                
                if current_pct >= args.target_coverage:
                    print(f"Goal Achieved: Target coverage of {args.target_coverage}% is already met ({current_pct:.2f}%).")
                    df = df.iloc[0:0] # Empty dataframe
                else:
                    # Greedy selection logic
                    needed_rows = []
                    running_known = current_known
                    target_tokens = (args.target_coverage / 100) * total_tokens
                    
                    for index, row in df.iterrows():
                        needed_rows.append(row)
                        # A phrase row makes no more of the text known than its words do: coverage is the tokens'.
                        if (row['Word'], row['Reading']) not in phrase_keys:
                            running_known += row['Occurrences']
                        if running_known >= target_tokens:
                            break
                    
                    final_pct = (running_known / total_tokens) * 100
                    df = pd.DataFrame(needed_rows)
                    
                    if final_pct >= args.target_coverage:
                        print(f"Successfully reached {final_pct:.2f}% coverage by adding {len(df)} words.")
                    else:
                        print(f"Note: Could only reach {final_pct:.2f}% coverage after adding ALL {len(df)} unknown words.")
                        print(f"  (This is because some unique tokens remain that were not in the candidate list.)")
            
            # Use the filtered DF for output, but make sure to drop _MinSeq
            df_display = df.drop(columns=["_MinSeq"], errors='ignore')
            
        valid_lrs = set(zip(df_display['Word'], df_display['Reading']))
        df_display.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')
        try:
            print(f"Saved priority list to {OUTPUT_CSV}")
        except UnicodeEncodeError:
            print("Saved priority list to CSV.")
    else:
        print("No unknown words found!")

    OUTPUT_STATS_JSON = os.path.join(RESULTS_DIR, "file_statistics.json")
    with open(OUTPUT_STATS, 'w', encoding='utf-8') as f:
        f.write("--- File Statistics ---\n")
        f.write(f"Configuration: Skip Single Chars = {skip_singles}\n")
        if ONLY_I_PLUS_ONE:
             f.write(f"i+1 Constraint: {words_skipped_i_plus_one} Words Evaluated & Skipped\n")
        f.write("\n")
        for stat in file_stats:
            f.write(f"File: {stat['File']}\n")
            f.write(f"  Total Words: {stat['Total Words']}\n")
            f.write(f"  Known Words: {stat['Known Count']}\n")
            f.write(f"  Coverage: {stat['Coverage (%)']}%\n")
            f.write("\n")
        try:
            print(f"Saved stats to {OUTPUT_STATS}")
        except UnicodeEncodeError:
            print("Saved stats to file.")
    
    with open(OUTPUT_STATS_JSON, 'w', encoding='utf-8') as f:
        f.write(json.dumps(file_stats, indent=4, ensure_ascii=False))
    try:
        print(f"Saved JSON stats to {OUTPUT_STATS_JSON}")
    except UnicodeEncodeError:
        print("Saved JSON stats.")

    # Output Raw Word Stats for GUI
    OUTPUT_WORD_STATS = os.path.join(RESULTS_DIR, "word_stats.json")
    # Convert word_stats to JSON-serializable format
    # Keys are (lemma, reading) tuples -> Convert to string "lemma|reading"
    # Values have sets -> Convert to lists
    # By default word_stats.json is LEAN: it drops the raw sentence-selection INPUTS — the up-to-30
    # `candidate_contexts` pool and the word's own `first_context` — which are ~99% of the file's size
    # on a large library and which NOTHING reads back (selection happens in-memory; the CHOSEN sentences
    # live in the CSV and in final_context_N below). Set SURASURA_DEBUG_WORD_STATS=1 to include the full
    # pool when debugging why a word got the example sentences it did. All stats + final_context_N are
    # always kept, so the Content Manager fallback and any inspection of the chosen sentences still work.
    _debug_word_stats = bool(os.environ.get("SURASURA_DEBUG_WORD_STATS"))
    serializable_stats = {}
    for (lemma, reading), data in word_stats.items():
        if valid_lrs is not None and (lemma, reading) not in valid_lrs:
            continue

        key = f"{lemma}|{reading}"
        serializable_data = data.copy()
        serializable_data["sources"] = list(data["sources"])
        # `series` is a set like `sources`; JSON has no set type. Kept as a COUNT rather than the
        # names — nothing reads the names back, and on a large library storing them would inflate
        # word_stats.json for no purpose (the file was deliberately slimmed for exactly this reason).
        serializable_data["series"] = len(data.get("series", ()))

        if _debug_word_stats:
            # Full dump: keep the raw selection inputs, converting their unique_lrs sets to lists.
            if "candidate_contexts" in serializable_data:
                serializable_data["candidate_contexts"] = [
                    (ctx[0], ctx[1], ctx[2], list(ctx[3]), ctx[4], ctx[5])
                    for ctx in serializable_data["candidate_contexts"]
                ]
            if serializable_data.get("first_context"):
                ctx = serializable_data["first_context"]
                serializable_data["first_context"] = (ctx[0], ctx[1], ctx[2], list(ctx[3]), ctx[4], ctx[5])
            # Same treatment for the audio pool — its entries carry the same unique_lrs SET, and
            # json.dump would raise on it, taking the whole run down in debug mode.
            if serializable_data.get("audio_contexts"):
                serializable_data["audio_contexts"] = [
                    (c[0], c[1], c[2], list(c[3]), c[4], c[5])
                    for c in serializable_data["audio_contexts"]
                ]
        else:
            # Lean default: drop the heavy, unread selection inputs (from the COPY only — the in-memory
            # word_stats keeps them for the progressive pass that runs after this).
            serializable_data.pop("candidate_contexts", None)
            serializable_data.pop("first_context", None)
            serializable_data.pop("audio_contexts", None)
            # Emitted as the CSVs' `Forms` column; nothing reads it back from here.
            serializable_data.pop("surfaces", None)

        serializable_stats[key] = serializable_data

    with open(OUTPUT_WORD_STATS, 'w', encoding='utf-8') as f:
        # One write of the whole text: json.dump writes it piece by piece (about a million writes here), and only
        # json.dumps uses the fast encoder where there is no indent (the source table, the frequency map). The same text.
        f.write(json.dumps(serializable_stats, indent=2, ensure_ascii=False))
    try:
        print(f"Saved {'FULL' if _debug_word_stats else 'lean'} word stats to {OUTPUT_WORD_STATS}")
    except UnicodeEncodeError:
        print("Saved word stats.")

    # Source table for the report's per-sentence badge: relative path -> {name, type}. Kept OUT of
    # the CSVs (which carry the readable path, so exports stay human-readable) and out of word_stats;
    # the renderer joins on the path. Small — one row per content FILE, not per sentence.
    try:
        OUTPUT_SOURCES = os.path.join(RESULTS_DIR, "sources.json")
        with open(OUTPUT_SOURCES, 'w', encoding='utf-8') as f:
            f.write(json.dumps({s["path"]: {"name": s["name"], "type": s["type"], "abs": s["abs"]}
                                for s in source_list}, ensure_ascii=False))
        print(f"Saved source table ({len(source_list)} files).")
    except Exception as e:
        print(f"Warning: could not write source table: {e}")

    # Content Manager sidecars: derived from the SAME serializable_stats we just wrote (identical
    # semantics), written atomically AFTER word_stats.json. See _write_sidecars. Wrapped so a failure
    # never breaks a run — the readers fall back to word_stats.json (and the mtime rule ignores any
    # stale sidecar left behind).
    try:
        n = _write_sidecars(RESULTS_DIR, serializable_stats)
        try:
            print(f"Saved Content Manager sidecars ({n} files).")
        except UnicodeEncodeError:
            print("Saved Content Manager sidecars.")
    except Exception as e:
        print(f"Warning: could not write Content Manager sidecars: {e}")

    # --- Reading-words sidecar (feeds the "Export Reading Words" Yomitan list) ------------------ #
    # Written from word_stats rather than the CSV on purpose: the CSV is cut at the selection
    # band's floor, and a word you meet five times is exactly the case where a mining decision
    # benefits most from knowing "you'll never hear this". Keeping the verdict here also means the
    # exporter never re-derives it — one implementation of the rule, in app/modality.py.
    # Written as a CSV with the SAME column names as the priority list, so every existing exporter
    # (Migaku / Yomitan / plain text) reads it without a single format-specific branch — the export
    # dialog just points at a different file.
    try:
        # One row per WORD, not per (word, reading): unidic gives some words several readings, and
        # a dictionary listing 差し伸べる twice with two different ranks is just noise to whoever
        # loads it. Occurrences are summed and the reading of the commonest variant is kept.
        _best = {}
        for (lemma, reading_kana), data in word_stats.items():
            if _modality_of(lemma) != "reading":
                continue
            n = data["total_count"]
            prev = _best.get(lemma)
            if prev is None:
                # reading, count-of-that-reading, total, spellings-seen
                _best[lemma] = [reading_kana, n, n, Counter(data["orths"])]
            else:
                prev[2] += n
                # Spellings are pooled across every reading of the word, for the same reason the
                # counts are: they are all one word, and splitting the evidence per reading would
                # let a rare variant win the name.
                prev[3].update(data["orths"])
                if n > prev[1]:
                    prev[0], prev[1] = reading_kana, n
        _reading = sorted(((w, _display_orth(w, v[3]), v[0], v[2]) for w, v in _best.items()),
                          key=lambda r: (-r[3], r[0]))
        with open(os.path.join(RESULTS_DIR, "reading_words.csv"), 'w', encoding='utf-8-sig',
                  newline='') as f:
            _w = csv.writer(f)
            _w.writerow(["Word", "Orth", "Reading", "Occurrences"])
            _w.writerows(_reading)
        print(f"Saved reading-words list ({len(_reading)} words).")
    except Exception as e:
        print(f"Warning: could not write reading-words list: {e}")

    # --- The full library frequency map: every word, including the sub-threshold ones the other
    # outputs drop ---
    # Read by the YouTube Preview (counts) and by Junban (Junban_Backlog_Spec §11.1), which places a
    # mined word below the list's cut-off exactly where the journey would meet it: its first file in
    # study order and its score, plus the spelling the content uses — anki_miner writes that
    # spelling, not the lemma. Written on EVERY run since ENGINE_REVISION 11 (it used to wait for the
    # preview toggle): it reuses the in-memory word_stats and measured ~30 ms on a 25k-word library.
    # A separate file; it never modifies word_stats.json or any other output, and is wrapped so a
    # failure can't break a run. Entries: [total, high, low, goal, first_file, score, spelling].
    try:
        OUTPUT_LIB_FREQ = os.path.join(RESULTS_DIR, "library_frequency.json")
        _weights = LOGIC.get("weights", {})
        _lib_words = {}
        for (lemma, reading), data in word_stats.items():
            _first = data.get("min_seq", 0)
            _lib_words[f"{lemma}|{reading}"] = [
                data.get("total_count", 0), data.get("high_count", 0),
                data.get("low_count", 0), data.get("goal_count", 0),
                _first if _first != float('inf') else 0, data.get("score", 0),
                _display_orth(lemma, data.get("orths")),
            ]
        _lib_payload = {
            "settings": {
                # The active selection's effective count floor (was 'min_freq'). The YouTube
                # preview keeps a word if library+in-video counts meet this. total_tokens lets
                # the preview reason in density terms. 'min_freq' kept for older-cache readers.
                "min_count": floor_count,
                "min_freq": MIN_FREQ,
                # Whose run this is: results/ holds one language's at a time (library_counts).
                "language": language,
                "total_tokens": total_tokens,
                "weights": {
                    "high": _weights.get("high", 10),
                    "low": _weights.get("low", 5),
                    "goal": _weights.get("goal", 2),
                },
            },
            "words": _lib_words,
        }
        with open(OUTPUT_LIB_FREQ, 'w', encoding='utf-8') as f:
            f.write(json.dumps(_lib_payload, ensure_ascii=False))
        try:
            print(f"Saved library frequency map to {OUTPUT_LIB_FREQ} ({len(_lib_words)} words)")
        except UnicodeEncodeError:
            print("Saved library frequency map.")
    except Exception as e:
        # Never let this map interfere with a normal run.
        print(f"Warning: Could not write library frequency map: {e}")

    # --- Persist the token index (seed-for-free) so the word-selection preview is instant and
    # always fresh without re-tokenizing. Built from the per-file counts already computed this
    # run (target-language tokens only, matching coverage accounting). Best-effort; never fatal. ---
    # (The token store was already reconciled at the start of the run, before aggregation.)

    # --- PROGRESSIVE REPORT PASS ---
    print("Generating Progressive Report...")
    progressive_rows = []
    # Work with a COPY of known words so we don't pollute the global set if we re-run logic, 
    # but here we just have one run.
    # We need a new set tracking "Learned in this session" to exclude from later files.
    
    # Start with initial known
    session_known = set(known_words_initial)
    session_lemmas = set(known_lemmas_initial)
    word_state = _word_state.get
    # The plan file's: every list key (in word_stats' order) and, per file, what this pass reads of the words a list
    # word's lemma names — (Total Count, the baseline known, [k, count, …], {k: uses a phrase took}, {lemma: count}).
    plan_keys = [key for key, entry in word_stats.items() if entry["total_count"] >= floor_count]
    plan_index = {key: k for k, key in enumerate(plan_keys)}
    plan_lemmas = {key[0] for key in plan_keys if key not in phrase_keys}
    plan_prog = []
    
    def _progressive_files():
        """Each file as the progressive pass reads it (`plan_rules.progressive_pass`), and the plan file's record of
        it: the words not known before any file, in the file's order (their uses after pieces, and those a phrase
        took), and the rare compounds' and the set phrases' credits."""
        for file_path, _label, _weight, _source_type in found_files:
            # Reuse the (lemma, reading) multiset captured during the aggregation pass instead of
            # re-tokenizing. Deterministic: same tokenizer + same text => same tokens. The rare
            # cache-miss branch re-tokenizes, so behaviour is never wrong, only slower.
            file_counter = file_token_cache.get(file_path)
            if file_counter is None:
                file_counter = Counter((l, r) for (l, r, s, o) in tokenizer.tokenize(extract_text(file_path, language)))

            file_total_tokens = 0
            file_baseline_known_count = 0     # Strictly initial known (JSON + Ignore)
            # A word whose every use here went to its phrase (it lives only inside it) is not met here on its own.
            file_bound = file_bound_cache.get(file_path)
            # A one-kanji list word's uses here as a piece of something else (三年's 年) are nothing to learn here.
            file_pieces = file_piece_cache.get(file_path)
            plan_tokens, plan_bound, plan_siblings = [], {}, {}
            keys, counts, bounds = [], [], []

            for key, count in file_counter.items():
                lemma = key[0]
                file_total_tokens += count

                # Check strictly against initial known list — known then in the session too (it starts from that
                # list) — and a one-character word the list never offers: nothing to learn either (§ One-character
                # words). The aggregation asked both of every word it met (`_word_state`: bits 1 and 4); a file read
                # here again asks.
                known = word_state(key)
                if known is None:
                    state = ((1 if (lemma in ignore_list or key in known_words_initial or lemma in known_lemmas_initial)
                              else 0) + (4 if _never(key) else 0))
                else:
                    state = known[0]
                if state & 5:
                    file_baseline_known_count += count
                    continue
                if file_pieces and key in file_pieces:
                    file_baseline_known_count += file_pieces[key]
                    count -= file_pieces[key]
                    if count <= 0:
                        continue
                bound = file_bound.get(key, 0) if file_bound else 0
                if lemma in plan_lemmas:
                    k = plan_index.get(key)
                    if k is None:
                        plan_siblings[lemma] = plan_siblings.get(lemma, 0) + count
                    else:
                        plan_tokens += (k, count)
                        if file_bound and key in file_bound:
                            plan_bound[k] = file_bound[key]
                keys.append(key)
                counts.append(count)
                bounds.append(bound)

            plan_prog.append((file_total_tokens, file_baseline_known_count, plan_tokens, plan_bound, plan_siblings))

            # A word met in this file only inside a rarer compound is met here too — its row sits here — but learning
            # it makes none of this file's tokens known: coverage stays in the tokenizer's words.
            credits = [(key, count) for key, count in file_credit_cache.get(file_path, {}).items()
                       if not (key[0] in ignore_list or _never(key))]
            # So is a set phrase met here — a row of its own, in the file it is first met in — which makes none of the
            # file's tokens known either: learning 気がする adds nothing to what 気 and する already cover.
            phrases = []
            if phrase_keys:
                for index, count in file_phrase_cache.get(file_path, {}).items():
                    phrase = _phrase_set.entry(index)
                    key = (phrase.word, phrase.reading)
                    if key in phrase_keys:
                        phrases.append((key, count))
            yield file_total_tokens, file_baseline_known_count, (keys, counts, bounds), (), credits, phrases

    _no_stats = {"score": 0, "total_count": 0, "high_count": 0, "low_count": 0, "goal_count": 0,
                 "final_context_1": "", "final_context_2": "", "final_context_3": ""}

    def _listed(key):
        if valid_lrs is not None and key not in valid_lrs:
            return False
        return word_stats.get(key, _no_stats)["total_count"] >= floor_count

    def _rank(key):
        stats = word_stats.get(key, _no_stats)
        return stats["score"], stats["total_count"]

    for seq_idx, ((file_path, _label, _weight, _source_type), (file_rows, baseline_pct, total)) in enumerate(zip(
            found_files, plan_rules.progressive_pass(_progressive_files(), session_known, session_lemmas,
                                                     itemgetter(0), _listed, _rank, args.target_coverage)), 1):
        filename = os.path.basename(file_path)
        for (lemma, reading), count, known_count, start_pct, end_pct in file_rows:
            tier_labels = get_tier_label(lemma, freq_data)
            tier_str = ";".join([f"{source}:{tier}" for source, tier in tier_labels]) if tier_labels else "Outside"
            stats = word_stats.get((lemma, reading), _no_stats)
            row = {
                "Sequence": seq_idx,
                "Source File": filename,
                "Word": lemma,
                # Same spelling the priority list shows, in the same position relative to Word.
                # Both files are read by the same consumers (the exporters, and junban's content
                # ordering), and a word named 須藤 in one and スドウ in the other would match in one
                # place and not the other.
                # .get: `stats` can be the bare fallback above, which has no spelling counters.
                "Orth": _display_orth(lemma, stats.get("orths")),
                "Forms": _display_forms(lemma, stats.get("orths"), stats.get("surfaces")),
                "Reading": reading,
                "Tier": tier_str,
                "Score": stats["score"],
                "Occurrences (Global)": stats["total_count"],
                "Occurrences (File)": count,
                "Count (High)": stats.get("high_count", 0),
                "Count (Low)": stats.get("low_count", 0),
                "Count (Goal)": stats.get("goal_count", 0),
                "Modality": _modality_of(lemma) or "",
            }
            # Dynamically attach all context strings currently tracked
            for k, v in stats.items():
                if k.startswith("final_context_"):
                    # Map final_context_N -> Context N
                    row[f"Context {k.replace('final_context_', '')}"] = v
                elif k.startswith("final_src_"):
                    # Map final_src_N -> Src N (the source file behind that example sentence)
                    row[f"Src {k.replace('final_src_', '')}"] = v
            row["Baseline %"] = baseline_pct
            row["Current %"] = start_pct
            row["New %"] = end_pct
            row["Known Count"] = known_count
            row["Total Count"] = total
            progressive_rows.append(row)
        
    df_prog = pd.DataFrame(progressive_rows)
    if not df_prog.empty:
        df_prog.to_csv(OUTPUT_PROGRESSIVE, index=False, encoding='utf-8-sig')
        print(f"Saved progressive report to {OUTPUT_PROGRESSIVE}")
    else:
        print("No progressive words found (all known).")

    # --- VISUALIZER REMOVED ---
            
    # --- STATIC GENERATION ---
    _progress("Writing the journey")
    if args.static:
        try:
            try:
                from app import static_html_generator
            except ImportError:
                import static_html_generator

            print("\n---------------------------------------------------")
            print("Generating Static HTML...")
            _rendering = time.time()
            static_html_generator.generate_static_html(
                theme=args.theme, app_mode=args.app_mode, zen_limit=args.zen_limit,
                open_browser=not args.no_open)
            _report_failed = not _report_written(os.path.join(RESULTS_DIR, "reading_list_static.html"), _rendering)
        except Exception as e:
            print(f"Error: Could not generate static HTML: {e}")
            _report_failed = True

    # The plan file (E1.1 01), last: every output exists, and the stamp below comes only after it. Never fails the run.
    # Q4-3: a band Automatic chose that differs from the one remembered is remembered now, and the run is stamped (and
    # its plan written) with it — the parts the next check will read — so a band change never costs a second Generate.
    try:
        from app import library_store as _library_store
        if _auto_pick and _sig_parts is not None and "auto_band" in _sig_parts:
            if _auto_pick["band"] != _sig_parts["auto_band"] and _library_store.record_auto_band(
                    language, data_dir, user_files_dir, _auto_pick["band"], _auto_pick["words"]):
                _sig_parts = dict(_sig_parts, auto_band=_auto_pick["band"])
                _run_sig = signature_digest(_sig_parts, chunked=False)
        elif not SELECT_AUTO:
            _library_store.forget_auto_band(language, data_dir, user_files_dir)   # off: switched on again, it starts fresh
    except Exception as e:
        print(f"Warning: automatic rarity could not remember its band ({e}); the next run decides afresh.")

    # No run signature, no plan: nothing could tell which run it describes.
    try:
        if not _run_sig:
            raise ValueError("the run has no signature")
        from app import __version__ as _app_version
        _plan_size = write_plan_file(RESULTS_DIR, plan_lines({
            "language": language,
            "engine": f"{_app_version}|schema{_token_index.SCHEMA_VERSION}|rev{ENGINE_REVISION}",
            "run_signature": _run_sig, "order_free_signature": signature_digest(_sig_parts, order_free=True,
                                                                                         chunked=False),
            "signature_parts": _sig_parts,
            "library": _library, "weights": (WEIGHT_HIGH, WEIGHT_LOW, WEIGHT_GOAL), "floor": floor_count,
            "total_tokens": total_tokens, "phrase_rows": _phrase_set is not None,
            "target_coverage": args.target_coverage, "only_i_plus_one": bool(ONLY_I_PLUS_ONE),
            "max_contexts": args.max_contexts, "data_dir": data_dir, "found_files": found_files,
            "plan_files": plan_files, "word_stats": word_stats, "phrase_keys": phrase_keys, "halved": _halved,
            "shared_phrases": _shared_phrases, "output_rows": output_rows, "valid_lrs": valid_lrs,
            "freq_data": freq_data, "phrase_set": _phrase_set, "word_state": _word_state,
            "token_cache": file_token_cache, "credit_cache": file_credit_cache, "phrase_cache": file_phrase_cache,
            "bound_cache": file_bound_cache, "piece_cache": file_piece_cache, "keys": plan_keys,
            "prog": plan_prog}))
        print(f"Saved the plan file ({_plan_size:,} bytes).")
    except Exception as e:
        print(f"Warning: could not write the plan file ({e}); the last one is left as it was.")

    # All outputs are now written — record the run-signature so an identical re-run can skip
    # entirely next time (and the presentation fingerprint so a same-setting re-run can open the
    # report without re-rendering), then close the store.
    _set_run_stamp(RESULTS_DIR, _run_sig)
    record_analysed(language, _library, data_dir, user_files_dir)
    if _store is not None:
        try:
            if _run_sig:
                _store.set_meta("last_run_signature", _run_sig)
            if args.static:
                _store.set_meta("last_render_sig", _render_sig)
        except Exception:
            pass
        _store.close()

    if "--visualize" not in sys.argv and "--static" not in sys.argv:
        print("\nAnalysis complete.")
        print("Use '--visualize' to run the interactive server.")
        print("Use '--static' to generate a standalone HTML file.")
    return 1 if _report_failed else None

if __name__ == "__main__":
    sys.exit(main() or 0)
