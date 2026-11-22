"""Distil KANJIDIC2's meanings and readings into app/kanji_data.py (DEV ONLY — never shipped).

Why this exists
---------------
The journey (v3, SPEC §5.1) shows a kanji's meaning and readings on hover, from data that ships with the app. Surasura
ships no per-kanji data, so this table is built HERE, once, from KANJIDIC2 (EDRDG), and the render
(app/journey_render.py) writes into the page only the kanji its words hold:

  DATA  one line per kanji with an English meaning: the kanji, up to 3 meanings ("; " between), up to 3 on readings
        (katakana), up to 3 kun readings (hiragana, the okurigana after a "."), each list " · " between.

Only the meanings and the readings are taken: KANJIDIC2's §8 conditions (the SKIP codes, the other indices) cover
none of them (https://www.edrdg.org/edrdg/licence.html §8). The lines' UTF-8, lzma-compressed, base 64.
Input (gitignored, local): docs/assets/reference_lists/kanjidic2.xml.gz, fetched from
https://www.edrdg.org/kanjidic/kanjidic2.xml.gz. Output is committed and ships: app/kanji_data.py. No run output
reads it, so a rebuild bumps nothing.

Usage:  python scripts/build_kanji_data.py
"""

import gzip
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.build_gloss_data import LISTS_DIR, _pack, _wrap, _write  # noqa: E402

KANJIDIC = "kanjidic2.xml.gz"
OUTPUT = os.path.join(ROOT, "app", "kanji_data.py")
KEEP = 3                    # meanings, on readings, kun readings: the first three of each


def kanji_lines(path):
    """kanjidic2.xml.gz -> (the DATA lines, the file's date of creation)."""
    root = ET.fromstring(gzip.open(path).read())
    created = root.findtext("header/date_of_creation") or ""
    lines = []
    for character in root.iter("character"):
        rm = character.find("reading_meaning/rmgroup")
        if rm is None:
            continue
        meanings = [m.text for m in rm.findall("meaning") if m.text and "m_lang" not in m.attrib][:KEEP]
        if not meanings:
            continue
        on = [r.text for r in rm.findall("reading") if r.get("r_type") == "ja_on" and r.text][:KEEP]
        kun = [r.text for r in rm.findall("reading") if r.get("r_type") == "ja_kun" and r.text][:KEEP]
        lines.append("\t".join([character.findtext("literal"), "; ".join(meanings), " · ".join(on), " · ".join(kun)]))
    return sorted(lines), created


def main(lists_dir=LISTS_DIR, output=OUTPUT):
    lines, created = kanji_lines(os.path.join(lists_dir, KANJIDIC))
    text = TEMPLATE.format(revision=date.today().isoformat(), created=created, n=len(lines), keep=KEEP,
                           data=_wrap(_pack(lines)))
    wrote = _write(output, text)
    print(f"{'Wrote' if wrote else 'Kept (unchanged)'} {output} ({os.path.getsize(output) / 1e3:,.0f} KB): "
          f"{len(lines):,} kanji")


TEMPLATE = '''"""Kanji meanings and readings for the journey's hover — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_kanji_data.py

Revision: {revision}   KANJIDIC2 created: {created}
  DATA  {n:,} kanji: the kanji, up to {keep} English meanings, up to {keep} on readings, up to {keep} kun readings
Tab-separated lines, sorted, lzma-compressed, base 64. Read through app/journey_render.py (`Kanji`), for the kanji
of the words on a page only.

Derived from KANJIDIC2, property of the Electronic Dictionary Research and Development Group (EDRDG), used in
conformance with the Group's licence (CC BY-SA 4.0, https://www.edrdg.org/edrdg/licence.html): the meanings and
readings only. Changes: the first three of each kept. This table is shared under the same licence,
https://creativecommons.org/licenses/by-sa/4.0/.
"""

REVISION = "{revision}"

DATA = """
{data}
"""
'''


if __name__ == "__main__":
    main()
