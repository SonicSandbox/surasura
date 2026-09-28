"""Distil the dictionary lists into app/katakana_data.py and app/name_data.py (DEV ONLY — never shipped).

Why this exists
---------------
A name the dictionary lacks is cut by the tagger into pieces that are words or letters of their own
(トゥー + リ, グリム + ジョー, 一 + 護), and those pieces then count as words. app/names.py keeps such a name one
word, judged from Japanese as a whole — never from the user's own content — so the tables it reads are built
HERE, once, from the dictionary lists, and the app ships only the result:

  KATAKANA_HEADWORDS  every kana headword of JPDB 2024 and Jiten, at any rank, written in katakana
                      (どきどき is listed as ドキドキ): a katakana run the tagger cuts is ONE word only when
                      no headword is spelled like it (ホストファミリー and パーキング stay the words they are).
  PERSON_NAMES        every spelling of a person's name — a surname or a given name — in JMnedict (the EDRDG's
                      Japanese names dictionary, through anki_miner's name wordsets) that holds a kanji, is 2–8
                      characters long and is no JPDB 2024 headword (冬月 'winter moon', 伊吹, 一葉 are words
                      too): a run of kanji the tagger cuts can be one name only when it is spelled as one of
                      them. Kept with whether it is a surname (宮崎 + 駿 is a full name, two words; 司波 is a
                      surname).

Inputs live in docs/assets/reference_lists/ (gitignored, like build_reference_data.py's): JPDB 2024.json,
Jiten.json and anki_miner_wordsets/ (surnames.txt, given-names.txt, LICENSE.txt). Output is committed and ships:
app/katakana_data.py (the headwords, read wherever Japanese is) and app/name_data.py (the person names, read only
where the library is indexed; JMnedict's licence, CC BY-SA 4.0, in its header). Rebuilding either changes what the
token store caches: bump SCHEMA_VERSION (app/token_index.py) and ENGINE_REVISION (app/analyzer.py) with it.

Usage:  python scripts/build_name_data.py
"""

import json
import os
import re
import sys
import zlib
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.unicode_ranges import HAN  # noqa: E402

LISTS_DIR = os.path.join(ROOT, "docs", "assets", "reference_lists")
OUTPUT = os.path.join(ROOT, "app", "name_data.py")
KATAKANA_OUTPUT = os.path.join(ROOT, "app", "katakana_data.py")
HEADWORD_LISTS = ("JPDB 2024", "Jiten")
NAME_LISTS = (("surnames", 1), ("given-names", 2))     # anki_miner_wordsets/<name>.txt, the bit it sets
_KANA = re.compile(r"^[ぁ-ゖゝゞァ-ヺー-ヾ]+$")
_HAN = re.compile(f"[{HAN}]")


def katakana(text):
    """ひらがな in カタカナ (ゝゞ -> ヽヾ): the two kana are one spelling for a list lookup."""
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" or c in "ゝゞ" else c for c in text)


def _headwords(lists_dir, name):
    """Every headword of one frequency list: a bare string, or the word of a [word, reading] pair."""
    with open(os.path.join(lists_dir, name + ".json"), encoding="utf-8") as handle:
        raw = json.load(handle)
    return [entry[0] if isinstance(entry, list) else entry for entry in raw]


def katakana_headwords(lists_dir):
    """Every kana headword of the lists, in katakana, sorted."""
    spellings = set()
    for name in HEADWORD_LISTS:
        kana = {katakana(word) for word in _headwords(lists_dir, name) if word and _KANA.match(word)}
        print(f"  {name}: {len(kana):,} kana headwords")
        spellings |= kana
    return sorted(spellings)


def person_names(lists_dir):
    """{spelling: bits} — JMnedict's surnames (1) and given names (2) with a kanji, 2-8 characters, that are no
    JPDB 2024 headword."""
    names = {}
    for name, bit in NAME_LISTS:
        with open(os.path.join(lists_dir, "anki_miner_wordsets", name + ".txt"), encoding="utf-8") as handle:
            for line in handle:
                word = line.strip()
                if word and not word.startswith("#") and 2 <= len(word) <= 8 and _HAN.search(word):
                    names[word] = names.get(word, 0) | bit
    words = set(_headwords(lists_dir, "JPDB 2024"))
    kept = {word: bits for word, bits in names.items() if word not in words}
    print(f"  JMnedict: {len(names):,} person-name spellings with a kanji, {len(names) - len(kept):,} of them "
          f"JPDB 2024 headwords: {len(kept):,} kept")
    return kept


def _blob(lines):
    return zlib.compress("\n".join(lines).encode("utf-8"), 9).hex()


def main(lists_dir=LISTS_DIR, output=OUTPUT, katakana_output=KATAKANA_OUTPUT):
    print(f"Dictionary lists from {lists_dir}")
    headwords = katakana_headwords(lists_dir)
    persons = person_names(lists_dir)
    surnames = sorted(word for word, bits in persons.items() if bits & 1)
    given = sorted(word for word, bits in persons.items() if bits & 2)
    revision = date.today().isoformat()
    with open(katakana_output, "w", encoding="utf-8") as handle:
        handle.write(KATAKANA_TEMPLATE.format(revision=revision, lists=" and ".join(HEADWORD_LISTS),
                                              n_katakana=len(headwords), katakana_hex=_blob(headwords)))
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(NAMES_TEMPLATE.format(revision=revision, n_persons=len(persons), n_surnames=len(surnames),
                                           n_given=len(given), surnames_hex=_blob(surnames), given_hex=_blob(given)))
    print(f"\nWrote {katakana_output} ({os.path.getsize(katakana_output) / 1024:,.0f} KB): {len(headwords):,} "
          f"katakana headwords")
    print(f"Wrote {output} ({os.path.getsize(output) / 1024:,.0f} KB): {len(persons):,} person-name spellings "
          f"({len(surnames):,} surnames, {len(given):,} given names)")


_DECODE = '''

def _lines(text):
    return zlib.decompress(bytes.fromhex(text)).decode("utf-8").split("\\n")
'''

KATAKANA_TEMPLATE = '''"""Katakana headwords distilled from the dictionary lists — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_name_data.py

Revision: {revision}
  KATAKANA_HEADWORDS  {n_katakana:,} spellings — every kana headword of {lists} (any rank), in katakana:
                      a katakana run the tagger cuts is one word only when none of them is spelled
                      like it (app/names.py).

Stored compressed (zlib, as hexadecimal text) and decoded lazily, so importing this module is cheap and
a process that never reads a Japanese word never pays for it.
"""

import zlib

REVISION = "{revision}"

_KATAKANA_HEADWORDS = (
    "{katakana_hex}"
)
''' + _DECODE + '''

def katakana_headwords():
    """The katakana spellings, a list (app/names.py keeps them as hashes)."""
    return _lines(_KATAKANA_HEADWORDS)
'''

NAMES_TEMPLATE = '''"""Person names distilled from JMnedict — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_name_data.py

Revision: {revision}
  PERSON_NAMES  {n_persons:,} spellings — {n_surnames:,} surnames and {n_given:,} given names of JMnedict
                with a kanji, 2-8 characters, that are no JPDB 2024 headword: a run of kanji the tagger
                cuts can be one name only when it is spelled as one of them (app/names.py).

Derived from JMnedict, the Japanese proper-names dictionary of the JMdict/EDICT project, property of the
Electronic Dictionary Research and Development Group (EDRDG), used in conformance with the Group's licence:
Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0),
https://creativecommons.org/licenses/by-sa/4.0/ — https://www.edrdg.org/edrdg/licence.html,
https://www.edrdg.org/enamdict/enamdict_doc.html. Changes: only the spellings of surnames and given names
are kept (no readings, no glosses), filtered as above. This table is shared under the same licence.

Stored compressed (zlib, as hexadecimal text) and decoded lazily: only where the library is indexed.
"""

import zlib

REVISION = "{revision}"

_SURNAMES = (
    "{surnames_hex}"
)

_GIVEN_NAMES = (
    "{given_hex}"
)
''' + _DECODE + '''

def surnames():
    """JMnedict's surname spellings, a list (app/names.py keeps them as hashes)."""
    return _lines(_SURNAMES)


def given_names():
    """JMnedict's given-name spellings, a list."""
    return _lines(_GIVEN_NAMES)
'''

if __name__ == "__main__":
    main()
