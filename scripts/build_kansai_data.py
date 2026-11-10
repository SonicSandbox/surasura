"""Distil JMdict's everyday Kansai words the tagger can't read into app/kansai_data.py (DEV ONLY — never shipped).

Why this exists
---------------
UniDic reads standard Japanese. A Kansai word it has never seen comes out as pieces it makes up: あかん 'no good' is the
filler あ + かん read as 彼 'he', おかん 'mom' お + 彼, せやな 'yeah' a person's name セヤ + な — so the list counted a
filler and 彼, and never offered the word. JMdict marks its Kansai words (the ksb dialect tag), and such a run is that
word (app/analyzer.py § Kansai). Which strings are Kansai words, and which of them the tagger can't read, is a question
about Japanese, not about any learner: JMdict, the frequency lists and the tokenizer decide it, here, once.

The rule (each step's count and examples go to the console):
  K1 entries   JMdict entries whose first sense — JMdict's commonest — is marked Kansai-ben (ksb), none marked
               archaic, dated, obsolete or rare (当て 'aim', whose fourth sense is Kansai's, is standard Japanese).
  K2 learned   a word a learner would learn: JPDB 2024 and Jiten both list one of its spellings, the better rank within
               60,000 — the 20 % of a Kansai learner's words both lists hold.
  K3 misread   a kana spelling the tokenizer reads, alone, as 2-5 pieces of which at least one it made up — a filler,
               an interjection of one kana, a symbol or a proper noun (analyzer._made_up): あかん (あ + 彼), おかん, せやな (セヤ + な), めっさ (symbols). A
               spelling it reads as real words is read right, or as a standard form (こない 'not come', やった 'did',
               ほんで それ + で, こたち 子 + たち) — never touched. Never a spelling drawn out (あかーん: the stretch
               rules read it) or one ending in the negative へん / ひん (the negative's own rules, app/analyzer.py).
  The word: the lemma and reading the tagger gives a kanji spelling of the entry it reads as one word (あほう is 阿呆,
  as アホ is), else as written (as the cut words are); a part of speech from JMdict's (a particle, an auxiliary, an
  interjection, an adverb, a な-word, a noun, a pronoun, an adjective, a conjunction; an expression a な-word).

Run it after scripts/build_reference_data.py: it reads the tables that build installed. Every parsing switch is read at
its default, whatever settings.json says. Rebuilding changes cached tokenization: the analyzer's ENGINE_REVISION and
token_index's SCHEMA_VERSION go up with it.

Output: app/kansai_data.py (committed; ships), with the EDRDG's attribution (CC BY-SA 4.0). Inputs:
docs/assets/reference_lists/JMdict_e.gz, JPDB 2024.json and Jiten.json (gitignored).

Usage:  python scripts/build_kansai_data.py [--jmdict PATH]
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
OUTPUT = os.path.join(ROOT, "app", "kansai_data.py")
JMDICT = os.path.join(ROOT, "docs", "assets", "reference_lists", "JMdict_e.gz")

OLD = frozenset(("arch", "dated", "obs", "rare", "obsc"))
RANK = 60_000
# JMdict's part of speech -> UniDic's pos1, in this order (the first a sense gives wins).
POS = (("prt", "助詞"), ("aux", "助動詞"), ("aux-v", "助動詞"), ("aux-adj", "助動詞"), ("int", "感動詞"), ("adv", "副詞"),
       ("adj-na", "形状詞"), ("n", "名詞"), ("pn", "代名詞"), ("adj-i", "形容詞"), ("conj", "接続詞"), ("exp", "形状詞"))


def _katakana(text):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


def pos1_of(entry):
    """The UniDic part of speech the word stands as: JMdict's (POS)."""
    tags = {p for s in entry["senses"] for p in s["pos"]}
    return next((pos1 for tag, pos1 in POS if tag in tags), "名詞")


def build(entries, tagger, joins, jpdb, jiten, log):
    from app import analyzer
    # Read as the tagger reads without this table (a rebuild would see あかん already joined); the rules stay.
    analyzer._KANSAI[:] = [({}, frozenset(), analyzer._KANSAI_ENDS | analyzer._CHAU)]
    table, steps = {}, {"K1 Kansai entries": 0, "K2 learned": 0, "K3 misread": 0}
    for entry in entries:
        senses = entry["senses"]
        if not senses or "ksb" not in senses[0]["dial"] or any(OLD.intersection(s["misc"]) for s in senses):
            continue
        steps["K1 Kansai entries"] += 1
        spellings = [k[0] for k in entry["kanji"]] + [r[0] for r in entry["kana"]]
        ranks = [r for r in (jpdb.rank(spellings, None), jiten.rank(spellings, None)) if r is not None]
        if len(ranks) < 2 or min(ranks) > RANK:
            continue
        steps["K2 learned"] += 1
        known = None                        # (lemma, reading) of a kanji spelling the tagger reads as one word (a kana
        for spelling in (k[0] for k in entry["kanji"]):     # one can be another word's: いやや's やや 'slightly')
            alone = analyzer.join_affixes(tagger(spelling), joins, library=False)
            if len(alone) == 1 and alone[0].feature.lemma and not analyzer._made_up(alone[0]):
                known = (alone[0].feature.lemma, alone[0].feature.lForm or _katakana(spelling))
                break
        for reb, _pri, _restr, _nokanji, rinf in entry["kana"]:
            if OLD.intersection(rinf) or "ik" in rinf or reb.endswith(("へん", "ひん")) or set("ーぁぃぅぇぉ～〜") & set(reb):
                continue
            words = analyzer.join_affixes(tagger(reb), joins, library=False)
            if not 2 <= len(words) <= 5 or "".join(w.surface for w in words) != reb:
                continue
            if not any(map(analyzer._made_up, words)):
                continue
            steps["K3 misread"] += 1
            lemma, reading = known or (reb, _katakana(reb))
            table[reb] = [lemma, reading, pos1_of(entry), words[0].surface, len(words)]
            log(f"    {reb}: {' + '.join(f'{w.surface}[{w.feature.lemma}]' for w in words)} -> {table[reb][2]}")
    for step, n in steps.items():
        log(f"  {step}: {n:,}")
    return dict(sorted(table.items()))


def main(argv=None):
    import build_reference_data as brd
    import jmdict_flags
    from app import analyzer
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jmdict", default=JMDICT)
    args = parser.parse_args(argv)
    brd.pin_parsing_defaults()
    analyzer.SANITIZE_JA = True
    created = jmdict_flags.created(args.jmdict)
    entries = jmdict_flags.load(args.jmdict)
    print(f"JMdict: {len(entries):,} entries, created {created}")
    table = build(entries, analyzer.Tagger(), analyzer.affix_joins(), brd.ListReadings("JPDB 2024"),
                  brd.ListReadings("Jiten"), print)
    body = json.dumps(table, ensure_ascii=False, sort_keys=True)
    revision = f"{date.today().isoformat()}-{hashlib.sha1(body.encode('utf-8')).hexdigest()[:8]}"
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(TEMPLATE.format(revision=revision, created=created or "", count=len(table),
                                rows="".join(f"    {json.dumps(k, ensure_ascii=False)}: "
                                             f"{json.dumps(v, ensure_ascii=False)},\n" for k, v in table.items())))
    print(f"Wrote {OUTPUT}: {len(table)} words, revision {revision}")
    return 0


TEMPLATE = '''"""Kansai words the tagger can't read — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_kansai_data.py   (after scripts/build_reference_data.py)

Revision: {revision}
  WORDS  {count} words -> {{spelling: [lemma, reading, pos1, first piece, pieces]}}: JMdict's Kansai-ben words (ksb)
         both JPDB 2024 and Jiten rank within 60,000, in a kana spelling the tokenizer reads, alone, as pieces it made
         up (a filler, a symbol, a proper noun: あかん is あ + 彼). The tokenizer joins such a run into the word
         (app/analyzer.py § Kansai); `first piece` and `pieces` are how it reads the spelling alone.

Derived from JMdict (JMdict created {created}), a dictionary of the JMdict/EDICT project, property of the Electronic
Dictionary Research and Development Group (EDRDG), used in conformance with the Group's licence: Creative Commons
Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), https://creativecommons.org/licenses/by-sa/4.0/ —
https://www.edrdg.org/edrdg/licence.html, https://www.edrdg.org/jmdict/j_jmdict.html. Changes: only the kana headwords
of its Kansai words are kept (no glosses), with a part of speech, those the frequency lists rank and the tokenizer
misreads. This table is shared under the same licence.
"""

REVISION = "{revision}"
JMDICT_CREATED = "{created}"
COUNT = {count}

_WORDS = {{
{rows}}}


def words():
    """{{spelling: [lemma, reading, pos1, first piece, pieces]}} — every word (the table itself: never change it)."""
    return _WORDS
'''


if __name__ == "__main__":
    sys.exit(main())
