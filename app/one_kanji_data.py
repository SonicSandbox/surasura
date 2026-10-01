"""One-kanji words the list can offer — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_one_kanji_data.py   (after scripts/build_reference_data.py)

Revision: 2026-09-30-f44c8843
  WORDS   1,130 one-kanji words -> "lemma|reading" (UniDic's lemma and its reading): each one general text uses as a
          word of its own (a common noun, a pronoun, a な-word, an adverb, a conjunction or an interjection) that JMdict
          lists with that reading and marks common, or that JPDB 2024 and Jiten both rank in their top 20,000. With
          Settings -> "List one-kanji words only when they're dictionary words" on, these are the one-character words
          the list can offer, counted where they stand on their own (analyzer.bound_uses).
  PIECES  658 one-kanji words general text uses as grammar (a prefix, a suffix, a particle, an auxiliary, the よう of
          ような): never shown as "not on your list" in the report.

Derived from JMdict (JMdict created 2026-09-28), a dictionary of the JMdict/EDICT project, property of the Electronic
Dictionary Research and Development Group (EDRDG), used in conformance with the Group's licence: Creative Commons
Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), https://creativecommons.org/licenses/by-sa/4.0/ —
https://www.edrdg.org/edrdg/licence.html, https://www.edrdg.org/jmdict/j_jmdict.html. Changes: only which one-kanji
spellings and readings are words of their own is kept (no glosses), judged with the app's tokenizer over general text
and the frequency lists' ranks. This table is shared under the same licence.

Stored compressed and decoded when first asked for; empty when it cannot be read, never an exception.
"""

import base64
import json
import zlib

REVISION = "2026-09-30-f44c8843"
JMDICT_CREATED = "2026-09-28"

_WORDS_B64 = (
    "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"
    "wGFV16fyY2gw+t//B9iwkMg="
)

_PIECES_B64 = (
    "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"
)

_words = None
_pieces = None


def _decode(b64):
    return frozenset(tuple(item.split("|", 1)) for item in json.loads(zlib.decompress(base64.b64decode(b64)).decode("utf-8")))


def words():
    """{(lemma, reading)}: the one-kanji words the list can offer. Empty when unreadable."""
    global _words
    if _words is None:
        try:
            _words = _decode(_WORDS_B64)
        except Exception:
            _words = frozenset()
    return _words


def pieces():
    """{(lemma, reading)}: the one-kanji words general text uses as grammar. Empty when unreadable."""
    global _pieces
    if _pieces is None:
        try:
            _pieces = _decode(_PIECES_B64)
        except Exception:
            _pieces = frozenset()
    return _pieces
