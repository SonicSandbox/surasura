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

Each table is the lines' UTF-8 in blocks of BLOCK_LINES lines, each block compressed with lzma alone and all of them
written in base 64 (a hex dump, the other tables' encoding, would pass 10 MB here; base 85's decoder is pure Python,
~1 s for JA), one module a language so a Chinese render never loads the Japanese table. Beside it, INDEX: every key a
line is looked up by (ja: its kanji forms and readings · zh: Simplified, Traditional) falls in a bucket (the CRC-32 of
its UTF-8, modulo BUCKETS), and each bucket names the blocks its keys' lines are in — so a render decompresses and
checks only the blocks of the words its memo lacks (G4: it scanned all 218,840 lines for them). A rebuild whose lines are the module's
already keeps its Revision: the journey's memo and render signature follow the meanings, not the file's format. Inputs (gitignored, local): docs/assets/reference_lists/JMdict_e.gz (build_name_data.py's)
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
import zlib
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


BLOCK_LINES = 2048         # a block's lines (~160 KB of JA: 3 ms to decompress, 2 ms to check). 512 cost the JA
#                             module 8.7 MB of blocks for 1 ms a block (2,048: 7.9 MB; one stream: 6.3 MB)
BLOCK_DICT = 1 << 20        # a block's lzma window (the block is smaller): what a reader holds while it decompresses
BUCKETS = 1 << 18           # INDEX's buckets: ~1.5 keys a bucket, so a key's bucket names its own blocks and ~1 other
FORMAT = 2                  # 1 (until 2026-11-25): one lzma stream, scanned whole · 2: blocks + INDEX


def _pack_blocks(lines):
    """[line] -> (DATA in base 64, BLOCKS: where each block starts in the decoded DATA, and the end; INDEX in base 64:
    for each bucket (a key's CRC-32 % BUCKETS; `journey_render._line_keys`) how many blocks it names, one byte each,
    then those blocks' numbers, one byte each, bucket by bucket. A line-by-line index (each key's CRC-32 and line)
    took 2.1 MB and 0.12 s to read — a quarter of what it saved."""
    from app.journey_render import _line_keys
    filters = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME, "dict_size": BLOCK_DICT}]
    encoded = [line.encode("utf-8") for line in lines]
    data, blocks = bytearray(), [0]
    for start in range(0, len(encoded), BLOCK_LINES):
        data += lzma.compress(b"\n".join(encoded[start:start + BLOCK_LINES]), format=lzma.FORMAT_RAW, filters=filters)
        blocks.append(len(data))
    if len(blocks) - 1 > 255:
        raise ValueError(f"{len(blocks) - 1} blocks: INDEX numbers a block in one byte (raise BLOCK_LINES)")
    named = [set() for _b in range(BUCKETS)]
    for n, line in enumerate(encoded):
        for key in _line_keys(line):
            named[zlib.crc32(key) % BUCKETS].add(n // BLOCK_LINES)
    if max(map(len, named), default=0) > 255:
        raise ValueError("a bucket names more than 255 blocks: raise BUCKETS")
    index = bytes(map(len, named)) + bytes(b for found in named for b in sorted(found))
    index = lzma.compress(index, preset=9 | lzma.PRESET_EXTREME)
    return base64.b64encode(bytes(data)).decode(), blocks, base64.b64encode(index).decode()


def module_lines(module):
    """A gloss module's lines (str), in either format (1: one stream · 2: blocks) — what a rebuild compares."""
    data = base64.b64decode(module.DATA)
    if getattr(module, "FORMAT", 1) == 1:
        text = lzma.decompress(data)
        return text.decode("utf-8").split("\n") if text else []
    filters = [{"id": lzma.FILTER_LZMA2, "dict_size": module.BLOCK_DICT}]
    out = []
    for start, end in zip(module.BLOCKS, module.BLOCKS[1:]):
        out += lzma.decompress(data[start:end], format=lzma.FORMAT_RAW, filters=filters).decode("utf-8").split("\n")
    return out


def _read_module(path):
    """The generated module at `path` as a namespace (REVISION, DATA …), or None: none there, or unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        space = {}
        exec(compile(source, path, "exec"), space)      # (our own generated file: constants only)
        return type("GlossModule", (), space)
    except Exception:
        return None


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
    today = date.today().isoformat()
    for lang, lines, what, source in (("ja", ja, "JMdict entries: kanji forms, readings, then up to {senses} senses "
                                                  "(\"<pos codes>|<up to {glosses} glosses>\")", f"JMdict created: {jmdict_date}"),
                                      ("zh", zh, "CC-CEDICT entries: Simplified, Traditional, pinyin, then up to "
                                                 "{senses} senses", f"CC-CEDICT: {cedict_date}")):
        old = _read_module(outputs[lang])
        try:
            same = old is not None and module_lines(old) == lines
        except Exception:
            same = False
        revision = old.REVISION if same else today      # the same meanings keep their Revision, whatever the format
        data, blocks, index = _pack_blocks(lines)
        text = TEMPLATE.format(revision=revision, source=source, n=len(lines),
                               what=what.format(senses=SENSES, glosses=GLOSSES), data=_wrap(data), format=FORMAT,
                               block_lines=BLOCK_LINES, block_dict=BLOCK_DICT, buckets=BUCKETS,
                               blocks=_wrap_numbers(blocks),
                               index=_wrap(index))
        wrote = _write(outputs[lang], text)
        print(f"{'Wrote' if wrote else 'Kept (unchanged)'} {outputs[lang]} "
              f"({os.path.getsize(outputs[lang]) / 1e6:.1f} MB): {len(lines):,} {source.split(':')[0].split()[0]} entries")


def _wrap(packed, width=116):
    return "\n".join(packed[i:i + width] for i in range(0, len(packed), width))


def _wrap_numbers(numbers, width=116):
    """A tuple's items, each with its comma, `width` characters a line at most."""
    lines, line = [], ""
    for n in numbers:
        piece = f"{n},"
        if line and len(line) + 1 + len(piece) > width:
            lines.append(line)
            line = ""
        line = f"{line} {piece}" if line else piece
    if line:
        lines.append(line)
    return "\n".join(lines)


TEMPLATE = '''"""English meanings for the journey — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_gloss_data.py

Revision: {revision}   {source}
  DATA  {n:,} {what}
Tab-separated lines in blocks of BLOCK_LINES, each lzma-compressed alone, base 64; INDEX: the blocks each key's
bucket names (scripts/build_gloss_data.py says why). Read through app/journey_render.py (`Meanings`), for the words
on a page only: their lines' blocks alone.

Derived from JMdict, property of the Electronic Dictionary Research and Development Group (EDRDG), used in conformance
with the Group's licence (CC BY-SA 4.0, https://www.edrdg.org/edrdg/licence.html), and from CC-CEDICT (MDBG,
CC BY-SA 4.0, https://cc-cedict.org/wiki/). Changes: only the first senses and glosses kept. This table is shared
under the same licence, https://creativecommons.org/licenses/by-sa/4.0/.
"""

REVISION = "{revision}"
FORMAT = {format}
BLOCK_LINES = {block_lines}
BLOCK_DICT = {block_dict}
BUCKETS = {buckets}

BLOCKS = (
{blocks}
)

DATA = """
{data}
"""

INDEX = """
{index}
"""
'''


if __name__ == "__main__":
    main()
