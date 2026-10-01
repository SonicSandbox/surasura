"""Distil the dictionary lists into app/katakana_data.py, app/name_data.py and app/jmdict_data.py (DEV ONLY — never
shipped).

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
  KANJI_FORMS         every kanji spelling of JMdict (the EDRDG's Japanese-English dictionary), entry by entry:
                      a run of kanji a story keeps using is one word of its own only when no entry is spelled
                      like it (鄭寧 is Sōseki's 丁寧, a dictionary word). Kept by entry, so a spelling also says
                      which dictionary word it belongs to (生き and 活き are one entry; 集い and 集う are two).
  READINGS            the readings of JMdict's entries that a card written in kana alone can be read through, with
                      the entries they read: one is taken for another word only with something written onto it (an
                      ending, the copula or する in a form of its own — CARD_TAILS), so only a reading that ends so is
                      kept. ことに is the reading of 殊に, an entry of its own, so a ことに card is no 事 + に
                      (app/anki_match.py `two_words`).

Inputs live in docs/assets/reference_lists/ (gitignored, like build_reference_data.py's): JPDB 2024.json,
Jiten.json, anki_miner_wordsets/ (surnames.txt, given-names.txt, LICENSE.txt) and JMdict_e.gz. Output is committed
and ships: app/katakana_data.py (the headwords, read wherever Japanese is), app/name_data.py (the person names, read
only where the library is indexed) and app/jmdict_data.py (the kanji spellings and the readings, read where the
library's tables are computed and where a card's word is matched) — the EDRDG's licence, CC BY-SA 4.0, in each
dictionary table's header. A table whose inputs didn't change is kept as it is (only its Revision line would move).
Rebuilding any of them changes what the token store caches: bump SCHEMA_VERSION (app/token_index.py) and
ENGINE_REVISION (app/analyzer.py) with it — except READINGS alone, which only cards read: ENGINE_REVISION (the
report's "In Anki" mark).

Usage:  python scripts/build_name_data.py
"""

import base64
import gzip
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
JMDICT_OUTPUT = os.path.join(ROOT, "app", "jmdict_data.py")
JMDICT = "JMdict_e.gz"
_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)
_KEB = re.compile(r"<keb>([^<]+)</keb>")
_REB = re.compile(r"<reb>([^<]+)</reb>")
_CREATED = re.compile(r"JMdict created: (\d{4}-\d{2}-\d{2})")
# How a card written in kana alone ends when app/anki_match.py's `one_word` reads it as another word with something
# written onto it: an ending (する, な, に, と — CARD_ENDINGS), or the copula or する in a form of its own (だ, です, た,
# ない, ます, ません: しずかだった, ハンパじゃない, べんきょうします). Only a reading that ends so can set such a card
# apart from that word, so only those are kept (READINGS) — a few thousand of JMdict's 260,000 readings.
CARD_TAILS = ("する", "な", "に", "と", "だ", "です", "た", "ない", "ます", "ません")
HEADWORD_LISTS = ("JPDB 2024", "Jiten")
NAME_LISTS = (("surnames", 1), ("given-names", 2))     # anki_miner_wordsets/<name>.txt, the bit it sets
_KANA = re.compile(r"^[ぁ-ゖゝゞァ-ヺー-ヾ]+$")
_HAN = re.compile(f"[{HAN}]")


def katakana(text):
    """ひらがな in カタカナ (ゝゞ -> ヽヾ): the two kana are one spelling for a list lookup."""
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" or c in "ゝゞ" else c for c in text)


def hiragana(text):
    """カタカナ in ひらがな, everything else as it is — app/anki_match.py's `fold_kana`, the card's side of a lookup."""
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


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


def _jmdict_entries(lists_dir):
    """(entries, created) — JMdict's entries as (kanji forms, readings), numbered as the tables number them: those with
    a kanji form first, by their KANJI_FORMS line (two entries spelled alike keep JMdict's order), then those written
    in kana alone, in JMdict's order; JMdict's "created" date. Raises when the dictionary is missing: an empty table
    would pass every spelling as no dictionary word."""
    path = os.path.join(lists_dir, JMDICT)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{path} is missing — JMdict's kanji spellings are never written empty")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        text = handle.read()
    created = _CREATED.search(text)
    entries = [(_KEB.findall(entry.group(1)), _REB.findall(entry.group(1))) for entry in _ENTRY.finditer(text)]
    kanji = sorted((entry for entry in entries if entry[0]), key=lambda entry: "\t".join(entry[0]))
    if not kanji:
        raise ValueError(f"{path} holds no kanji forms — not JMdict?")
    return kanji + [entry for entry in entries if not entry[0]], (created.group(1) if created else "unknown")


def jmdict_kanji_forms(lists_dir):
    """(lines, created, forms) — every JMdict entry with a kanji form as one line, its kanji forms (<keb>, search-only
    ones included) joined by tabs in JMdict's order, the lines sorted; JMdict's "created" date; how many forms in all.
    An entry written only in kana has no line. Raises when the dictionary is missing: an empty table would pass every
    spelling as no dictionary word."""
    entries, created = _jmdict_entries(lists_dir)
    lines = ["\t".join(kanji) for kanji, _readings in entries if kanji]
    forms = sum(len(kanji) for kanji, _readings in entries)
    print(f"  JMdict ({created}): {len(lines):,} entries with a kanji form, {forms:,} forms")
    return lines, created, forms


def jmdict_readings(lists_dir):
    """(lines, entries) — the readings (<reb>, in hiragana) that end as a card written in kana alone can (CARD_TAILS),
    one line each: the reading, then the ids of the entries it reads, commas between — an entry's KANJI_FORMS line
    number, or past their end for an entry written in kana alone (_jmdict_entries' numbering) — sorted; how many
    entries they read."""
    entries, _created = _jmdict_entries(lists_dir)
    ids = {}
    for number, (_kanji, readings) in enumerate(entries):
        for reading in readings:
            reading = hiragana(reading)
            if len(reading) > 1 and reading.endswith(CARD_TAILS):
                ids.setdefault(reading, []).append(number)
    lines = sorted(f"{reading}\t{','.join(map(str, dict.fromkeys(numbers)))}" for reading, numbers in ids.items())
    read = len({number for numbers in ids.values() for number in numbers})
    print(f"  JMdict: {len(lines):,} readings a kana card can end in, of {read:,} entries")
    return lines, read


def _blob(lines):
    return zlib.compress("\n".join(lines).encode("utf-8"), 9).hex()


def _blob64(lines):
    return base64.b64encode(zlib.compress("\n".join(lines).encode("utf-8"), 9)).decode("ascii")


_REVISION_LINE = re.compile(r'^(Revision: |REVISION = ").*$', re.M)


def _write(path, text):
    """Write `text` to `path` — unless the file there differs only in its Revision lines: then it is kept as it is, so
    a table rebuilt from unchanged inputs doesn't move. -> whether it was written."""
    try:
        with open(path, encoding="utf-8") as handle:
            old = handle.read()
    except OSError:
        old = None
    if old is not None and _REVISION_LINE.sub("", old) == _REVISION_LINE.sub("", text):
        return False
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def main(lists_dir=LISTS_DIR, output=OUTPUT, katakana_output=KATAKANA_OUTPUT, jmdict_output=JMDICT_OUTPUT):
    print(f"Dictionary lists from {lists_dir}")
    headwords = katakana_headwords(lists_dir)
    persons = person_names(lists_dir)
    kanji_forms, created, n_forms = jmdict_kanji_forms(lists_dir)
    readings, n_read = jmdict_readings(lists_dir)
    surnames = sorted(word for word, bits in persons.items() if bits & 1)
    given = sorted(word for word, bits in persons.items() if bits & 2)
    revision = date.today().isoformat()
    written = [
        _write(katakana_output, KATAKANA_TEMPLATE.format(revision=revision, lists=" and ".join(HEADWORD_LISTS),
                                                         n_katakana=len(headwords), katakana_hex=_blob(headwords))),
        _write(output, NAMES_TEMPLATE.format(revision=revision, n_persons=len(persons), n_surnames=len(surnames),
                                             n_given=len(given), surnames_hex=_blob(surnames), given_hex=_blob(given))),
        _write(jmdict_output, JMDICT_TEMPLATE.format(revision=revision, created=created, n_entries=len(kanji_forms),
                                                     n_forms=n_forms, forms_b64=_blob64(kanji_forms),
                                                     n_readings=len(readings), n_read=n_read,
                                                     tails=", ".join(CARD_TAILS), readings_b64=_blob64(readings))),
    ]
    for (path, what), wrote in zip(((katakana_output, f"{len(headwords):,} katakana headwords"),
                                    (output, f"{len(persons):,} person-name spellings ({len(surnames):,} surnames, "
                                             f"{len(given):,} given names)"),
                                    (jmdict_output, f"{len(kanji_forms):,} JMdict entries, {n_forms:,} kanji forms, "
                                                    f"{len(readings):,} readings")),
                                   written):
        print(f"{'Wrote' if wrote else 'Kept (unchanged)'} {path} ({os.path.getsize(path) / 1024:,.0f} KB): {what}")


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

JMDICT_TEMPLATE = '''"""JMdict's kanji spellings by entry and the readings kana cards end in — GENERATED, DO NOT EDIT.

Regenerate with:  python scripts/build_name_data.py

Revision: {revision}
  KANJI_FORMS  {n_entries:,} entries of JMdict (JMdict created {created}) that have a kanji form — {n_forms:,} forms
               in all, search-only ones included — one line per entry, its forms separated by tabs as JMdict orders
               them, the lines sorted. A line's number is that entry's id in this revision (a rebuild renumbers: never
               store one): two spellings on one line are one dictionary word (生き and 活き), on two lines two
               (集い is no 集う). app/names.py asks it of a run of kanji a story keeps using: that run is one
               word of its own only when no entry is spelled like it; app/anki_match.py asks it whether a card's word
               and the word the tokenizer reads it as are two dictionary words (揚げる 'deep-fry' is no 上げる).
  READINGS     {n_readings:,} readings of {n_read:,} entries, those a card written in kana alone can end in when it
               is read as another word with something written onto it:
               {tails}.
               One line per reading, in hiragana, then the ids of the entries it reads, commas between (a KANJI_FORMS
               line number; an entry written in kana alone is numbered past their end), the lines sorted. ことに
               reads 殊に: a ことに card is no 事 + に (app/anki_match.py).

Derived from JMdict, the Japanese-multilingual dictionary of the JMdict/EDICT project, property of the Electronic
Dictionary Research and Development Group (EDRDG), used in conformance with the Group's licence: Creative Commons
Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), https://creativecommons.org/licenses/by-sa/4.0/ —
https://www.edrdg.org/edrdg/licence.html, https://www.edrdg.org/jmdict/j_jmdict.html. Changes: only the kanji
spellings, grouped by entry, and the readings above are kept (no glosses). This table is shared under the same licence.

Stored compressed (zlib, as base64 text) and decoded lazily: only where the library's tables are computed or a card's
word is matched.
"""

import base64
import zlib

REVISION = "{revision}"
CREATED = "{created}"

_KANJI_FORMS = (
    "{forms_b64}"
)

_READINGS = (
    "{readings_b64}"
)


def kanji_forms():
    """JMdict's entries that have a kanji form, as text: one line per entry, its kanji forms separated by tabs — a
    line's number is the entry's id in this revision."""
    return zlib.decompress(base64.b64decode(_KANJI_FORMS)).decode("utf-8")


def readings():
    """The readings a card written in kana alone can end in, as text: one line per reading (in hiragana), a tab, the
    ids of the entries it reads, commas between."""
    return zlib.decompress(base64.b64decode(_READINGS)).decode("utf-8")
'''

if __name__ == "__main__":
    main()
