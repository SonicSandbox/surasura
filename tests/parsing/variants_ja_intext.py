"""In-text compounds (2026-09-30, a learner's report: 出来損ない) — a headword the compound build reads only ALONE is
missed where the text reads it another way. 出来損ない alone is two verbs (出来る + 損なう: no compound shape, so the
build never keys it); in a sentence it is two nouns (出来 + 損ない), and the list offered 損ない 'harm'. Nothing in
app/ changes: these variants patch the tables (and, for -stems, the join) for one scorecard run.

    intext-nouns    the compound table as the build would make it when it also reads each headword where the reference
                    text shows it: a headword it never took, seen as a run of 2-3 nouns spelling it, is a noun compound
                    with those nouns as its parts (出来 + 損ない -> 出来損ない), through every gate the build has (the
                    even odds, the plural guard, a word the tagger reads whole, no word made of itself). Data only.
    intext-stems    intext-nouns, and a verb's stem (連用形, never する's) may stand in a compound JMdict lists as a noun
                    that the text — or the headword read alone — shows written so: a run ending in a noun joins anywhere
                    (出来[stem] + 損ない, 待ち[stem] + 時間, as the tagger often reads them), a run ending in a stem only
                    when nothing but closing punctuation follows it on its line — a card, a known word, a line that is
                    just the word (出来る + 損なう -> 出来損ない) — never in a sentence, where 位置づけ + て is the verb.

Both read debug/parsing_fixes_run/in_text_compounds/tables/intext.json (tables_diff.py there wrote it from the
candidate build tables/t1/ against tables/baseline/): the entries the build adds, their parts, the affix joins its
second pass adds, and the words the stem flag goes on. The measurement: that folder's REPORT.md.
"""
import json
import os

from app import analyzer, reference_data
from tests.parsing import harness
from tests.parsing.harness import patched
from tests.parsing.variants import variant

DATA = os.path.join(harness.ROOT, "debug", "parsing_fixes_run", "in_text_compounds", "tables", "intext.json")
STEMS = 8                     # the flag a stem-allowing entry would carry (dictionary_data's next free bit)
_CLOSERS = frozenset("。．.！？!?」』）)】〕…‥―ー～〜")
_DATA = {}


def data():
    """{"entries": {spelling: [lemma, reading, kind, flags]}, "parts": {spelling: [[lemma, reading, free], ...]},
    "affix": {spelling: [lemma, reading]}, "stems": [spelling, ...], "reparted": {spelling: [noun parts, stem parts]}}
    — read once, when a variant is entered. A stem-flag word's parts are its commonest reading's (立ち位置: 立つ + 位置);
    "reparted" keeps the noun reading's too, for intext-nouns."""
    if not _DATA:
        if not os.path.isfile(DATA):
            raise FileNotFoundError(f"{DATA} is missing — PYTHONIOENCODING=utf-8 python "
                                    "debug/parsing_fixes_run/in_text_compounds/tables_diff.py")
        with open(DATA, encoding="utf-8") as handle:
            _DATA.update(json.load(handle))
    return _DATA


def _tables(stems):
    """The installed tables with the build's additions — copies: the installed ones are never touched."""
    d = data()
    joins = dict(reference_data.compound_joins())
    joins.update((w, tuple(e)) for w, e in d["entries"].items())
    if stems:
        for w in d["stems"]:
            e = joins.get(w)
            if e is not None:
                joins[w] = (e[0], e[1], e[2], e[3] | STEMS)
    parts = dict(reference_data.compound_parts())
    parts.update(d["parts"])
    if not stems:
        # without the stem rule a word is joined only where the text reads it as nouns: its parts are those nouns
        parts.update((w, old) for w, (old, _new) in d.get("reparted", {}).items())
    affix = dict(reference_data.affix_joins())
    affix.update((w, tuple(e)) for w, e in d["affix"].items())
    return joins, parts, affix


def stem(word):
    """A verb's stem as a noun is written (出来, 損ない, 待ち): 連用形 in its plain form — never する's, never a sound
    change (損なっ comes only before た / て)."""
    f = word.feature
    return f.pos1 == "動詞" and not word.is_unk and f.lemma != "為る" and str(f.cForm) == "連用形-一般"


def ends_line(words, k):
    """Nothing but closing punctuation from words[k] on: the run is the whole text read (a card, a known word)."""
    return all(w.feature.pos1 in ("補助記号", "空白") and all(ch in _CLOSERS for ch in w.surface) for w in words[k:])


def _joins_with_stems(words, i, run, entry):
    """May `run` — holding a verb's stem — be joined as the noun `entry` (the -stems rule above)?"""
    if entry[2] != "N" or not entry[3] & STEMS or len(run) > 3 or not any(stem(w) for w in run):
        return False
    if not all(stem(w) or analyzer._compound_part(w, "N") for w in run):
        return False
    if i and words[i - 1].feature.pos2 == "数詞" and analyzer._counter(run[0]):
        return False
    return not stem(run[-1]) or ends_line(words, i + len(run))


def _compound_at(words, i, table, heads, fringe):
    """analyzer._compound_at with the -stems rule: the app's own answer first (a verb + verb, or the longest noun
    compound it joins); else a run that starts with a noun or a verb's stem, holding a stem, that spells a
    stem-allowing entry — the longest first."""
    first = words[i]
    f = first.feature
    if f.pos1 == "動詞":
        second = words[i + 1]
        g = second.feature
        if g.pos1 == "動詞" and not getattr(second, "white_space", "") and str(f.cForm).startswith("連用形"):
            key = analyzer._read(first) + (g.orthBase or analyzer._read(second))
            entry = table.get(key)
            if (entry is not None and entry[2] == "V" and not (entry[3] & 1 and not fringe)
                    and analyzer._compound_part(first, "V") and analyzer._compound_part(second, "V")):
                return i + 1, key, "動詞", entry
        if not stem(first):
            return None
    key = analyzer._read(first)
    if hash(key) not in heads:
        return None
    found = []
    for j in range(i + 1, min(len(words), i + 4)):
        w = words[j]
        if w.feature.pos1 not in analyzer._LATER_POS1 or getattr(w, "white_space", ""):
            break
        key += analyzer._read(w)
        entry = table.get(key)
        if entry is not None:
            found.append((j, key, entry))
        if hash(key) not in heads:
            break
    for end, key, entry in reversed(found):
        run = words[i:end + 1]
        if entry[3] & 1 and not fringe:
            continue
        if f.pos1 != "動詞" and analyzer._joins_here(words, i, run, entry, fringe):
            return end, key, "形状詞" if words[end].feature.pos1 == "形状詞" else "名詞", entry
        if _joins_with_stems(words, i, run, entry):
            return end, key, "名詞", entry
    return None


def _entered(stems):
    joins, parts, affix = _tables(stems)
    return joins, parts, affix


@variant("intext-nouns",
         "A headword the compound build reads only alone is also read where the reference text shows it: seen as a "
         "run of 2-3 nouns spelling it (出来 + 損ない), it is a noun compound with those parts, through every gate the "
         "build has (even odds, plurals, a word the tagger reads whole, no word made of itself) — table data only, no "
         "code change. Reads debug/parsing_fixes_run/in_text_compounds/tables/intext.json.")
def _intext_nouns():
    joins, parts, affix = _entered(False)
    with patched(reference_data, "compound_joins", lambda: joins), \
            patched(reference_data, "compound_parts", lambda: parts), \
            patched(reference_data, "affix_joins", lambda: affix):
        yield


@variant("intext-stems",
         "intext-nouns, and a verb's stem may stand in a compound JMdict lists as a noun that the text or the word "
         "alone shows written so: a run ending in a noun joins anywhere (出来[stem] + 損ない, 待ち[stem] + 時間); a run "
         "ending in a stem only when it is the whole line — a card, a known word (出来る + 損なう -> 出来損ない) — never "
         "in a sentence (位置づけ + て stays the verb). A code change in _compound_at plus a flag per word.")
def _intext_stems():
    joins, parts, affix = _entered(True)
    with patched(reference_data, "compound_joins", lambda: joins), \
            patched(reference_data, "compound_parts", lambda: parts), \
            patched(reference_data, "affix_joins", lambda: affix), \
            patched(analyzer, "_compound_at", _compound_at):
        yield
