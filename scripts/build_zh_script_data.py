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

Length-preserving by construction (spec I3). Every entry whose source and target lengths differ is
dropped and counted, so an offset in converted text is always the same offset in the original.

Inputs live in docs/assets/opencc/. That folder is gitignored and holds the four dictionaries, the
LICENSE, and SOURCE_TAG.txt naming the OpenCC release they came from. It is a one-time download at
development time; nothing is fetched at runtime (spec I5). The output, app/zh_script_data.py, is
committed and ships.

Usage:  python scripts/build_zh_script_data.py
"""

import base64
import json
import os
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


def distil_phrases(chars, phrases):
    """Only the phrases that say something the character table doesn't."""
    return {src: dst for src, dst in phrases.items()
            if "".join(chars.get(ch, ch) for ch in src) != dst}


def _blob(obj):
    return base64.b64encode(
        zlib.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    ).decode("ascii")


def main(opencc_dir=OPENCC_DIR, output=OUTPUT):
    tag_path = os.path.join(opencc_dir, "SOURCE_TAG.txt")
    try:
        with open(tag_path, "r", encoding="utf-8") as f:
            tag = f.read().strip() or "unknown"
    except OSError:
        tag = "unknown"
    print(f"OpenCC dictionaries from {opencc_dir} (tag {tag})")

    blobs, summary = {}, {}
    for direction, (chars_name, phrases_name) in DIRECTIONS.items():
        chars, dropped_chars = load_dictionary(opencc_dir, chars_name)
        phrases, dropped_phrases = load_dictionary(opencc_dir, phrases_name)
        kept = distil_phrases(chars, phrases)
        print(f"  {direction}: {len(chars):>6,} characters ({dropped_chars} dropped, unequal length)")
        print(f"  {direction}: {len(kept):>6,} of {len(phrases):,} phrases kept "
              f"({dropped_phrases} dropped, unequal length)")
        blobs[direction] = _blob({"chars": chars, "phrases": kept})
        summary[direction] = (len(chars), len(kept), dropped_chars + dropped_phrases)

    with open(output, "w", encoding="utf-8") as f:
        f.write(MODULE_TEMPLATE.format(
            revision=date.today().isoformat(),
            tag=tag,
            s2t_chars=summary["s2t"][0], s2t_phrases=summary["s2t"][1], s2t_dropped=summary["s2t"][2],
            t2s_chars=summary["t2s"][0], t2s_phrases=summary["t2s"][1], t2s_dropped=summary["t2s"][2],
            s2t_b64=blobs["s2t"],
            t2s_b64=blobs["t2s"],
        ))
    print(f"\nWrote {output} ({os.path.getsize(output) / 1024:,.0f} KB)")
    return summary


MODULE_TEMPLATE = '''"""Chinese script tables distilled from OpenCC — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_zh_script_data.py

Revision: {revision}   OpenCC: {tag}
  S2T  {s2t_chars:,} characters + {s2t_phrases:,} phrases ({s2t_dropped} unequal-length entries dropped)
  T2S  {t2s_chars:,} characters + {t2s_phrases:,} phrases ({t2s_dropped} unequal-length entries dropped)

Derived from the dictionaries of Open Chinese Convert (OpenCC), https://github.com/BYVoid/OpenCC,
by Carbo Kuo and contributors. Licensed under the Apache License, Version 2.0:
https://www.apache.org/licenses/LICENSE-2.0 (entries reduced to their first candidate; phrases that
match a character-by-character conversion omitted).

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
