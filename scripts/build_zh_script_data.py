"""Distil OpenCC's dictionaries into app/zh_script_data.py (DEV ONLY — never shipped).

Why this exists
---------------
The Chinese `zh_script` setting reads a whole library in one script — Simplified or Traditional —
so 学习 and 學習 count as one word (spec: docs/agent instructions/Chinese_Script_Conversion_Spec.md).
The mapping is OpenCC's generic s2t / t2s data (Apache-2.0). CLAUDE.md §4 rules out a new pip
dependency, so the dictionaries are distilled HERE, once, into a small committed table, and
app/zh_script.py converts with the standard library alone.

What it keeps, per direction (s2t, t2s)
---------------------------------------
  CHARS    character -> OpenCC's FIRST candidate, which is its preferred one.
  PHRASES  phrase -> its first candidate, but ONLY the phrases whose conversion differs from
           converting their characters one at a time. That is 9,788 of STPhrases' 49,238 at
           ver.1.4.2. The rest exist to steer OpenCC's own forward maximum matching, and
           app/zh_script.py fixes context only at the characters a phrase can change, so they add
           nothing. Measured on real news text against a maximum-matching reference: keeping them
           changed 2 characters in 3,697, and both of those changes were worse (關系 for 關係).

Traditional is written in Taiwan's standard characters
------------------------------------------------------
OpenCC's generic Traditional writes some characters in forms Taiwan's standard (and Hong Kong's) doesn't: 爲, 裏, 麪,
衆, 喫 where Taiwan writes 為, 裡, 麵, 眾, 吃. TWVariants.txt — OpenCC's own table of them, the one its s2tw setting
reads — maps each generic form to Taiwan's, one character to one. When it is there:
  S2T      every character target and every phrase's characters go through it (为 -> 為, 面条 -> 麵條, 吃饭 -> 吃飯),
           and a character the generic table leaves alone but Taiwan writes otherwise enters it (着 -> 著, 污 -> 汙);
  T2S      Taiwan's form is read back as Simplified where the generic table can't already (簷 -> 檐, 痺 -> 痹) —
           never 著, a character of Simplified text too (著名 'famous'): Taiwan's 著 for 着 is read phrase by
           phrase, where the dictionaries pair the spellings.
Without it the tables are OpenCC's generic forms.

Traditional spellings are read as CC-CEDICT pairs them
-----------------------------------------------------
CC-CEDICT, the community Chinese–English dictionary, gives each word both spellings. Where the Traditional→Simplified
table reads a Traditional word otherwise, its pair becomes a phrase of that table (T2S) when it is length-preserving
and has one Simplified spelling:
  著 / 着   every pair whose Traditional holds 著 where its Simplified holds 着 — 睡著 -> 睡着, 著急 -> 着急, 隨著 ->
           随着 (著名 'famous' stays: CC-CEDICT writes it 著名 in both);
  no word  every other pair whose Simplified reading by the table is no word of jieba's dictionary nor of CC-CEDICT,
           where CC-CEDICT's is one of jieba's — 砲擊 -> 炮击 (the table's 砲击 is no word), 姪女 -> 侄女, 暱稱 -> 昵称.
The rest — pairs whose reading by the table is a word too (計畫: OpenCC's 计划, CC-CEDICT's 计画), or whose CC-CEDICT
spelling jieba doesn't hold — are counted and left as the table reads them. OpenCC's own phrases win a tie. Read from
docs/assets/zh_gold/cedict_1_0_ts_utf-8_mdbg.zip (checked as scripts/build_cedict_data.py checks it) and the installed
jieba's dictionary, when the dictionary is there.

Length-preserving by construction (spec I3). Every entry whose source and target lengths differ is
dropped and counted, so an offset in converted text is always the same offset in the original.

Inputs live in docs/assets/opencc/. That folder is gitignored and holds the four dictionaries, the
LICENSE, SOURCE_TAG.txt naming the OpenCC release they came from, and TWVariants.txt (FETCHED.json
records its URL, size and sha256). It is a one-time download at development time; nothing is fetched at
runtime (spec I5). The output, app/zh_script_data.py, is committed and ships.

Usage:  python scripts/build_zh_script_data.py
"""

import base64
import json
import os
import sys
import zlib
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENCC_DIR = os.path.join(ROOT, "docs", "assets", "opencc")
OUTPUT = os.path.join(ROOT, "app", "zh_script_data.py")

# direction -> (character dictionary, phrase dictionary)
DIRECTIONS = {
    "s2t": ("STCharacters", "STPhrases"),
    "t2s": ("TSCharacters", "TSPhrases"),
}
TW_VARIANTS = "TWVariants"
GOLD_DIR = os.path.join(ROOT, "docs", "assets", "zh_gold")
CEDICT = "cedict_1_0_ts_utf-8_mdbg.zip"
# Characters of Simplified text too, never read back from Taiwan's form (this module's docstring).
SIMPLIFIED_TOO = frozenset("著")


def load_dictionary(opencc_dir, name):
    """An OpenCC `key<TAB>candidate candidate…` file -> ({key: first candidate}, dropped).

    `dropped` counts the entries whose first candidate is a different length from the key (I3).
    A key listed twice keeps its first line, the same rule as its first candidate."""
    table, dropped = {}, 0
    with open(os.path.join(opencc_dir, name + ".txt"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#"):
                continue
            key, _tab, values = line.partition("\t")
            value = values.split(" ")[0]
            if not key or not value:
                continue
            if len(key) != len(value):
                dropped += 1
                continue
            table.setdefault(key, value)
    return table, dropped


def load_variants(opencc_dir):
    """TWVariants.txt -> {OpenCC's standard character: Taiwan's}, one character to one; {} when it isn't there."""
    if not os.path.isfile(os.path.join(opencc_dir, TW_VARIANTS + ".txt")):
        return {}
    table, _dropped = load_dictionary(opencc_dir, TW_VARIANTS)
    return {key: value for key, value in table.items() if len(key) == 1 and key != value}


def taiwan(s2t_chars, s2t_phrases, t2s_chars, variants):
    """The tables written in Taiwan's standard characters (this module's docstring) -> (s2t characters, s2t phrases,
    t2s characters)."""
    if not variants:
        return s2t_chars, s2t_phrases, t2s_chars
    chars = {src: variants.get(dst, dst) for src, dst in s2t_chars.items()}
    for src, dst in variants.items():
        chars.setdefault(src, dst)
    phrases = {src: "".join(variants.get(ch, ch) for ch in dst) for src, dst in s2t_phrases.items()}
    back = dict(t2s_chars)
    for src, dst in variants.items():
        simplified = t2s_chars.get(src, src)
        if dst not in t2s_chars and simplified != dst and dst not in SIMPLIFIED_TOO:
            back[dst] = simplified
    return chars, phrases, back


def cedict_pairs(gold_dir):
    """({Traditional headword: Simplified}, every Simplified headword) — CC-CEDICT's own pairs of two characters or
    more with one Simplified spelling, length-preserving; ({}, set()) when CC-CEDICT isn't there."""
    if not os.path.isfile(os.path.join(gold_dir, CEDICT)):
        return {}, set()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_cedict_data import load_cedict
    entries, _date = load_cedict(gold_dir)
    held = {}
    for simplified, readings in entries.items():
        for traditional, _pinyin, _senses in readings:
            if len(traditional) == len(simplified) > 1:
                held.setdefault(traditional, set()).add(simplified)
    return ({traditional: next(iter(spellings)) for traditional, spellings in held.items() if len(spellings) == 1},
            set(entries))


def cedict_readings(pairs, headwords, t2s_chars, t2s_phrases, words):
    """(phrases, later) — CC-CEDICT's pairs the Traditional→Simplified table reads otherwise: the 著 / 着 pairs and
    the pairs it reads as no word (this module's docstring) as phrases, and the rest, {Traditional: (CC-CEDICT's
    Simplified, the table's)}, for later. `words` is jieba's dictionary: what holds a word."""
    sys.path.insert(0, ROOT)
    from app.zh_script import _Converter
    read = _Converter({"chars": t2s_chars, "phrases": t2s_phrases}).convert
    phrases, later = {}, {}
    for traditional, simplified in sorted(pairs.items()):
        reading = read(traditional)
        if reading == simplified:
            continue
        if any(a == "著" and b == "着" for a, b in zip(traditional, simplified)):
            phrases[traditional] = simplified
        elif reading not in words and reading not in headwords and simplified in words:
            phrases[traditional] = simplified
        else:
            later[traditional] = (simplified, reading)
    return phrases, later


def jieba_words():
    """The installed jieba's dictionary: every word it holds, by its frequency (a frequency of 0 holds none)."""
    import jieba
    jieba.setLogLevel(60)
    jieba.initialize()
    return {word for word, count in jieba.dt.FREQ.items() if count}


def distil_phrases(chars, phrases):
    """Only the phrases that say something the character table doesn't."""
    return {src: dst for src, dst in phrases.items()
            if "".join(chars.get(ch, ch) for ch in src) != dst}


def _blob(obj):
    return base64.b64encode(
        zlib.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    ).decode("ascii")


def main(opencc_dir=OPENCC_DIR, output=OUTPUT, gold_dir=GOLD_DIR, words=None):
    tag_path = os.path.join(opencc_dir, "SOURCE_TAG.txt")
    try:
        with open(tag_path, "r", encoding="utf-8") as f:
            tag = f.read().strip() or "unknown"
    except OSError:
        tag = "unknown"
    print(f"OpenCC dictionaries from {opencc_dir} (tag {tag})")

    loaded = {direction: (load_dictionary(opencc_dir, chars_name), load_dictionary(opencc_dir, phrases_name))
              for direction, (chars_name, phrases_name) in DIRECTIONS.items()}
    variants = load_variants(opencc_dir)
    s2t_chars, s2t_phrases, t2s_chars = taiwan(loaded["s2t"][0][0], loaded["s2t"][1][0], loaded["t2s"][0][0],
                                               variants)
    t2s_phrases = loaded["t2s"][1][0]
    pairs, headwords = cedict_pairs(gold_dir)
    paired = {}
    if pairs:
        paired, later = cedict_readings(pairs, headwords, t2s_chars, t2s_phrases,
                                        jieba_words() if words is None else words)
        zhe = sum(1 for traditional in paired if "著" in traditional)
        print(f"  CC-CEDICT's own pairs: {zhe} 著 / 着, {len(paired) - zhe} the table reads as no word; "
              f"{len(later)} left as the table reads them")
        t2s_phrases = {**paired, **t2s_phrases}
    tables = {"s2t": (s2t_chars, s2t_phrases), "t2s": (t2s_chars, t2s_phrases)}
    if variants:
        print(f"  Taiwan's standard characters: {len(variants)} variants ({TW_VARIANTS}.txt)")

    blobs, summary = {}, {}
    for direction in DIRECTIONS:
        (_c, dropped_chars), (_p, dropped_phrases) = loaded[direction]
        chars, phrases = tables[direction]
        kept = distil_phrases(chars, phrases)
        print(f"  {direction}: {len(chars):>6,} characters ({dropped_chars} dropped, unequal length)")
        print(f"  {direction}: {len(kept):>6,} of {len(phrases):,} phrases kept "
              f"({dropped_phrases} dropped, unequal length)")
        blobs[direction] = _blob({"chars": chars, "phrases": kept})
        summary[direction] = (len(chars), len(kept), dropped_chars + dropped_phrases)

    with open(output, "w", encoding="utf-8", newline="\n") as f:     # LF, as committed, on any system
        f.write(MODULE_TEMPLATE.format(
            revision=date.today().isoformat(),
            tag=tag,
            variants=(f" — Traditional in Taiwan's standard characters ({TW_VARIANTS}.txt, {len(variants)} variants)"
                      if variants else ""),
            sources=("; Traditional is written in Taiwan's standard characters through OpenCC's\n"
                     f"{TW_VARIANTS}.txt" if variants else ""),
            cedict=(f"\n\nThe {len(paired)} Traditional→Simplified phrases that read a word as CC-CEDICT pairs its spellings "
                    "(睡著 is\n睡着, 砲擊 is 炮击) come from CC-CEDICT, the community Chinese–English dictionary published "
                    "by\nMDBG (https://cc-cedict.org/wiki/), licensed under the Creative Commons Attribution-ShareAlike "
                    "4.0\nInternational License (https://creativecommons.org/licenses/by-sa/4.0/); only the pairs of "
                    "spellings are kept,\nshared under the same licence." if paired else ""),
            s2t_chars=summary["s2t"][0], s2t_phrases=summary["s2t"][1], s2t_dropped=summary["s2t"][2],
            t2s_chars=summary["t2s"][0], t2s_phrases=summary["t2s"][1], t2s_dropped=summary["t2s"][2],
            s2t_b64=blobs["s2t"],
            t2s_b64=blobs["t2s"],
        ))
    print(f"\nWrote {output} ({os.path.getsize(output) / 1024:,.0f} KB)")
    return summary


MODULE_TEMPLATE = '''"""Chinese script tables distilled from OpenCC — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_zh_script_data.py

Revision: {revision}   OpenCC: {tag}{variants}
  S2T  {s2t_chars:,} characters + {s2t_phrases:,} phrases ({s2t_dropped} unequal-length entries dropped)
  T2S  {t2s_chars:,} characters + {t2s_phrases:,} phrases ({t2s_dropped} unequal-length entries dropped)

Derived from the dictionaries of Open Chinese Convert (OpenCC), https://github.com/BYVoid/OpenCC,
by Carbo Kuo and contributors{sources}. Licensed under the Apache License, Version 2.0:
https://www.apache.org/licenses/LICENSE-2.0 (entries reduced to their first candidate; phrases that
match a character-by-character conversion omitted).{cedict}

Both tables are stored compressed and decoded lazily (app/zh_script.py asks for them on its first
conversion), so importing this module is cheap and a process that never converts never pays.
"""

import base64
import json
import zlib

REVISION = "{revision}"
OPENCC_TAG = "{tag}"

_S2T_B64 = (
    "{s2t_b64}"
)

_T2S_B64 = (
    "{t2s_b64}"
)


def _decode(b64):
    return json.loads(zlib.decompress(base64.b64decode(b64)).decode("utf-8"))


def s2t():
    """{{"chars": {{…}}, "phrases": {{…}}}} for Simplified -> Traditional."""
    return _decode(_S2T_B64)


def t2s():
    """{{"chars": {{…}}, "phrases": {{…}}}} for Traditional -> Simplified."""
    return _decode(_T2S_B64)
'''


if __name__ == "__main__":
    main()
