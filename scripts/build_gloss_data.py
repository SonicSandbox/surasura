"""Distil JMdict's English glosses and CC-CEDICT's senses into app/gloss_ja_data.py and app/gloss_zh_data.py (DEV ONLY
— never shipped).

Why this exists
---------------
The journey (v3, SPEC §5.1) shows a word's meaning beside its sentences, from data that ships with the app — never a
lookup off the machine. Today's tables keep no glosses (app/jmdict_data.py holds spellings only, app/cedict_data.py
splits, folds and sounds), so this table is built HERE, once, and the render (app/journey_render.py) looks up only the
words on the page:

  JA   one line per JMdict entry: its kanji forms (commas between), its readings (commas between), then up to 3 senses,
       each "<part-of-speech codes, ; between>|<up to 3 glosses, '; ' between>" (a sense without its own part of
       speech takes the one before it, as JMdict means). Codes are JMdict's entity names (n, vs, adj-na, v5r …).
  ZH   one line per CC-CEDICT entry: Simplified, Traditional, pinyin (tone numbers), then up to 3 senses — a
       variant's, a surname's or a "see …" line kept as CC-CEDICT writes it.

Each table is the lines' UTF-8, compressed with lzma and written in base 64 (a hex dump, the other tables' encoding,
would pass 10 MB here; base 85's decoder is pure Python, ~1 s for JA), one module a language so a Chinese render never
loads the Japanese table. Inputs (gitignored, local): docs/assets/reference_lists/JMdict_e.gz (build_name_data.py's)
and docs/assets/zh_gold/cedict_1_0_ts_utf-8_mdbg.zip (fetch_gold.py's). Output is committed and ships:
app/gloss_ja_data.py, app/gloss_zh_data.py. No run output reads it, so a rebuild bumps nothing (the journey's render signature takes the
table's REVISION).

Usage:  python scripts/build_gloss_data.py
"""

import base64
import gzip
import lzma
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.build_cedict_data import GOLD_DIR, _REVISION_LINE, load_cedict  # noqa: E402

LISTS_DIR = os.path.join(ROOT, "docs", "assets", "reference_lists")
JMDICT = "JMdict_e.gz"
OUTPUTS = {"ja": os.path.join(ROOT, "app", "gloss_ja_data.py"), "zh": os.path.join(ROOT, "app", "gloss_zh_data.py")}
SENSES = 3                  # a word's first senses, as the page shows them
GLOSSES = 3                 # a sense's first glosses
GLOSS_MAX = 80              # characters a gloss keeps (the rare long one is cut at a word)
_ENTITY = re.compile(r"&([\w.-]+);")
_JMDICT_DATE = re.compile(r"<!-- JMdict created: (\d{4}-\d{2}-\d{2}) -->")


def _cut(text):
    text = " ".join(text.split())
    if len(text) <= GLOSS_MAX:
        return text
    return text[:GLOSS_MAX].rsplit(" ", 1)[0] + "…"


def jmdict_lines(path):
    """JMdict_e.gz -> (the JA lines, JMdict's date). Entities (&n;) are read as their names: the DTD is not loaded."""
    text = gzip.open(path).read().decode("utf-8")
    dated = _JMDICT_DATE.search(text)
    body = _ENTITY.sub(r"\1", text[text.index("<JMdict>"):])
    lines = []
    for entry in ET.fromstring(body).iter("entry"):
        kanji = [k.findtext("keb") for k in entry.findall("k_ele")]
        readings = [r.findtext("reb") for r in entry.findall("r_ele")]
        senses, pos = [], ""
        for sense in entry.findall("sense"):
            pos = ";".join(p.text for p in sense.findall("pos") if p.text) or pos
            glosses = [_cut(g.text) for g in sense.findall("gloss") if g.text][:GLOSSES]
            if glosses:
                senses.append(f"{pos}|{'; '.join(glosses)}")
            if len(senses) == SENSES:
                break
        if senses and readings:
            lines.append("\t".join([",".join(kanji), ",".join(readings)] + senses))
    return lines, dated.group(1) if dated else ""


def cedict_lines(entries):
    """parse_cedict's entries -> the ZH lines, by Simplified headword (CC-CEDICT's own order within one)."""
    lines = []
    for simplified in sorted(entries):
        for traditional, pinyin, senses in entries[simplified]:
            kept = [_cut(s).replace("\t", " ") for s in senses[:SENSES]]
            if kept:
                lines.append("\t".join([simplified, traditional, pinyin] + kept))
    return lines


DICT_SIZE = 8 << 20         # lzma's window: a reader holds this much while it decompresses (preset 9's 64 MB
#                             cost the render ~55 MB of its memory budget for 1 % of the size)


def _pack(lines):
    filters = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME, "dict_size": DICT_SIZE}]
    return base64.b64encode(lzma.compress("\n".join(lines).encode("utf-8"), filters=filters)).decode()


def _write(path, text):
    """Write unless only the Revision lines differ (a rebuild from unchanged inputs moves nothing) -> written?"""
    try:
        with open(path, encoding="utf-8") as handle:
            old = handle.read()
    except OSError:
        old = None
    if old is not None and _REVISION_LINE.sub("", old) == _REVISION_LINE.sub("", text):
        return False
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return True


def main(lists_dir=LISTS_DIR, gold_dir=GOLD_DIR, outputs=None):
    outputs = outputs or OUTPUTS
    ja, jmdict_date = jmdict_lines(os.path.join(lists_dir, JMDICT))
    entries, cedict_date = load_cedict(gold_dir)
    zh = cedict_lines(entries)
    revision = date.today().isoformat()
    for lang, lines, what, source in (("ja", ja, "JMdict entries: kanji forms, readings, then up to {senses} senses "
                                                  "(\"<pos codes>|<up to {glosses} glosses>\")", f"JMdict created: {jmdict_date}"),
                                      ("zh", zh, "CC-CEDICT entries: Simplified, Traditional, pinyin, then up to "
                                                 "{senses} senses", f"CC-CEDICT: {cedict_date}")):
        text = TEMPLATE.format(revision=revision, source=source, n=len(lines),
                               what=what.format(senses=SENSES, glosses=GLOSSES), data=_wrap(_pack(lines)))
        wrote = _write(outputs[lang], text)
        print(f"{'Wrote' if wrote else 'Kept (unchanged)'} {outputs[lang]} "
              f"({os.path.getsize(outputs[lang]) / 1e6:.1f} MB): {len(lines):,} {source.split(':')[0].split()[0]} entries")


def _wrap(packed, width=116):
    return "\n".join(packed[i:i + width] for i in range(0, len(packed), width))


TEMPLATE = '''"""English meanings for the journey — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_gloss_data.py

Revision: {revision}   {source}
  DATA  {n:,} {what}
Tab-separated lines, lzma-compressed, base 64 (scripts/build_gloss_data.py says why). Read through
app/journey_render.py (`Meanings`), for the words on a page only.

Derived from JMdict, property of the Electronic Dictionary Research and Development Group (EDRDG), used in conformance
with the Group's licence (CC BY-SA 4.0, https://www.edrdg.org/edrdg/licence.html), and from CC-CEDICT (MDBG,
CC BY-SA 4.0, https://cc-cedict.org/wiki/). Changes: only the first senses and glosses kept. This table is shared
under the same licence, https://creativecommons.org/licenses/by-sa/4.0/.
"""

REVISION = "{revision}"

DATA = """
{data}
"""
'''


if __name__ == "__main__":
    main()
