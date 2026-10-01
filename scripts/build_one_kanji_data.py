"""Distil the one-kanji words the list can offer into app/one_kanji_data.py (DEV ONLY — never shipped).

Why this exists
---------------
About half of every Japanese text is "one-character words": UniDic files a word under a lemma of one character. Most of
those uses are grammar (の, は, た, て), but many are real words — 手, 目, 顔, 私, 何, and words written in kana whose
lemma is one kanji (こと 事, もの 物, ため 為, わけ 訳, しばしば 屡). With Settings -> Language & Parsing -> "List one-kanji
words only when they're dictionary words" on (exclude_single, the default) a one-kanji word is a list word when the
language says it is a word — a question about Japanese, not about any learner. So it is decided HERE, once, from
general text, JMdict and the frequency lists, and the app ships the answer: every (lemma, reading) that passes.

A one-kanji (lemma, reading) is a list word when all three hold (the fourth gate, "only where it stands on its own",
is the app's, per use: analyzer.bound_uses):
  1 a word of its own   in general text the tagger uses it, most of the time, as a common noun, a pronoun, a
                        な-word, an adverb, a conjunction or an interjection — never a prefix, a suffix, a proper
                        noun or the よう of ような;
  2 in the dictionary   JMdict lists that spelling with that reading — or, for a word UniDic files under a one-kanji
                        lemma that JMdict spells otherwise (しばしば: 屡 / 屡々), that reading under a spelling holding
                        the lemma — with a sense that is not only a prefix, a suffix, a counter, a numeral or a
                        particle;
  3 common              JMdict marks the entry common (news1, ichi1, spec1, spec2, gai1), or both JPDB 2024 and Jiten
                        rank that spelling with that reading within their top 20,000 — a word mostly written in kana
                        by its kana spelling too (こと, ranked 15th and 17th).
Each reading is its own word and passes on its own: (時, とき) is listed, (時, じ) only when its own sense and uses pass;
中 ちゅう, 的 and 様 さま are suffixes (gate 1) and never are.

PIECES, the second table: the one-kanji (lemma, reading)s general text uses as grammar — a prefix, a suffix, a
particle, an auxiliary or the よう of ような (お 御, たち 達, 様 さま, 的, 中 ちゅう). The report's "Also in this file,
not on your list" never shows them: they are pieces of words and grammar, never a word to make a card for.

The general text is the shared set's (docs/assets/corpora/_text/, sliced as build_reference_data.py slices it — the
text the compound table's counts and the phrases' unit test are made from), read by the app's own tokenizer the way
shared data is read: join_affixes(..., library=False), every parsing switch at its default. Run it after
scripts/build_reference_data.py: it reads the tables that build installed, so a word the tokenizer joins is never a
one-kanji word here.

Rebuilding changes what a run lists, never how text is tokenized: the analyzer's ENGINE_REVISION goes up with it, not
the token store's SCHEMA_VERSION.

Output: app/one_kanji_data.py (committed; ships), with the EDRDG's attribution (CC BY-SA 4.0), and
debug/one_kanji_data.md (gitignored), the report. Inputs: docs/assets/reference_lists/JMdict_e.gz, JPDB 2024.json and
Jiten.json, and the shared set's text in docs/assets/corpora/_text/ (all gitignored).

Usage:  python scripts/build_one_kanji_data.py [--jmdict PATH] [--workers N] [--text PATH] [--dump PATH]
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from app.unicode_ranges import HAN  # noqa: E402  (pure)

OUTPUT = os.path.join(ROOT, "app", "one_kanji_data.py")
REPORT = os.path.join(ROOT, "debug", "one_kanji_data.md")
JMDICT = os.path.join(ROOT, "docs", "assets", "reference_lists", "JMdict_e.gz")
LISTS = os.path.join(ROOT, "docs", "assets", "reference_lists")

RANK = 20_000           # gate 3: both JPDB 2024 and Jiten within their top 20,000
COMMON = frozenset(("news1", "ichi1", "spec1", "spec2", "gai1"))
# JMdict's parts of speech that only build or follow a word — never a word of its own (gate 2).
NOT_CONTENT = frozenset(("n-pref", "n-suf", "pref", "suf", "ctr", "num", "prt", "aux", "aux-v", "aux-adj", "cop",
                         "unc"))
# UniDic's parts of speech (pos1, pos2) of a word of its own (gate 1): a common noun, a pronoun, a な-word (タリ too), an
# adverb, a conjunction, an interjection or a filler.
CONTENT_POS = frozenset((("名詞", "普通名詞"), ("代名詞", "*"), ("形状詞", "一般"), ("形状詞", "タリ"), ("副詞", "*"),
                         ("接続詞", "*"), ("感動詞", "一般"), ("感動詞", "フィラー")))
# What general text uses as grammar (PIECES): a prefix, a suffix, a particle, an auxiliary, the よう of ような.
GRAMMAR_POS1 = frozenset(("接頭辞", "接尾辞", "助詞", "助動詞"))
GRAMMAR_POS = frozenset((("形状詞", "助動詞語幹"),))
WORKERS = min(4, os.cpu_count() or 1)
_ONE_KANJI = re.compile(f"^[{HAN}]$")
_HAS_KANJI = re.compile(f"[{HAN}]")


def hiragana(text):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


# --- Gate 1: how general text uses each one-kanji word ------------------------------------------------------------ #

_WORKER = {}


def _init():
    """A worker: the tagger and the joins as shared data reads text (every switch at its default)."""
    from app import analyzer
    import build_reference_data as brd
    brd.pin_parsing_defaults()
    analyzer.SANITIZE_JA = True
    _WORKER.update(analyzer=analyzer, tagger=analyzer.Tagger(), joins=analyzer.affix_joins())


def _count_file(path):
    """-> (path, {(lemma, reading): [{(pos1, pos2): uses}, {surface: uses}]}) for one text file: every counted token
    whose lemma is one kanji (analyzer.word_lemma, sanitized, as tokenize_sentences keys it)."""
    analyzer, tagger, joins = _WORKER["analyzer"], _WORKER["tagger"], _WORKER["joins"]
    sanitize, word_lemma = analyzer._sanitize_term, analyzer.word_lemma
    out = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            for word in analyzer.join_affixes(tagger(line), joins, library=False):
                lemma = word_lemma(word)
                if lemma is None or len(lemma) > 30:
                    continue
                lemma = sanitize(lemma)
                if len(lemma) != 1 or _ONE_KANJI.match(lemma) is None:
                    continue
                f = word.feature
                key = (lemma, f.lForm or f.kana or "")
                entry = out.get(key)
                if entry is None:
                    entry = out[key] = [Counter(), Counter()]
                entry[0][(f.pos1, f.pos2)] += 1
                entry[1][word.surface] += 1
    return path, out


def corpus_pass(workers, log, text=None):
    """Every one-kanji word's parts of speech and spellings over the shared set's text (`text`: where it is staged,
    when not in docs/assets/corpora/_text/)."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    import build_reference_data as brd
    if text:
        brd.CORPUS_TEXT = text
    paths = sorted(brd._corpus_texts(), key=lambda p: -os.path.getsize(p))
    pos, surf = defaultdict(Counter), defaultdict(Counter)
    t0 = time.time()
    with ProcessPoolExecutor(workers, multiprocessing.get_context("spawn"), _init) as pool:
        for done, (path, counts) in enumerate(pool.map(_count_file, paths), 1):
            for key, (poses, surfaces) in counts.items():
                pos[key].update(poses)
                surf[key].update(surfaces)
            log(f"    {done}/{len(paths)} {os.path.relpath(path, brd.CORPUS_TEXT)} ({time.time() - t0:.0f} s)")
    return pos, surf, len(paths)


def majority(poses):
    """The (pos1, pos2) a word is used as most often; ties to the smaller tuple, so a rebuild is stable."""
    return max(poses.items(), key=lambda item: (item[1], tuple(-ord(c) for c in "".join(item[0]))))[0]


# --- Gates 2 and 3: JMdict and the frequency lists ---------------------------------------------------------------- #

def jmdict_facts(idx, lemma, reading):
    """(found, a content sense, common) — what JMdict says of `lemma` read `reading` (katakana): the spelling with that
    reading; else, a word UniDic files under a one-kanji lemma that JMdict spells otherwise (しばしば: 屡 / 屡々, まま:
    侭 / 儘), that reading as a kana form of an entry whose kanji forms hold the lemma."""
    import jmdict_flags as jf
    found = jf.lookup(idx, lemma, reading)
    if not found and reading:
        found = [e for e in idx[1].get(hiragana(reading), ()) if any(lemma in k[0] for k in e["kanji"])]
    content = common = False
    for entry in found:
        marks = {p for k in entry["kanji"] for p in k[1]} | {p for r in entry["kana"] for p in r[1]}
        common |= bool(marks & COMMON)
        content |= any(set(sense["pos"]) - NOT_CONTENT for sense in entry["senses"])
    return bool(found), content, common


def load_ranks(name):
    """({(spelling, reading): rank}, {kana spelling: rank}) — a list's entries as docs/assets/reference_lists holds
    them: [spelling, reading] pairs, or plain strings for words written in kana."""
    with open(os.path.join(LISTS, f"{name}.json"), encoding="utf-8") as f:
        entries = json.load(f)
    pair, plain = {}, {}
    for rank, entry in enumerate(entries, 1):
        if isinstance(entry, list) and len(entry) >= 2:
            pair.setdefault((entry[0], entry[1]), rank)
        elif isinstance(entry, str):
            plain.setdefault(entry, rank)
    return pair, plain


def kana_spelling(surfaces):
    """A word mostly written in kana is ranked by that spelling too — two kana or more (a one-kana spelling is the
    particle's: さ, そ): its commonest kana spelling, in hiragana, or None."""
    uses = sum(surfaces.values())
    kana = sum(n for s, n in surfaces.items() if not _HAS_KANJI.search(s))
    top = next((s for s, _n in sorted(surfaces.items(), key=lambda item: (-item[1], item[0]))
                if not _HAS_KANJI.search(s)), None)
    return hiragana(top) if top and len(top) >= 2 and kana * 2 >= uses else None


def ranks_of(lemma, reading, kana, lists):
    """(JPDB 2024's rank, Jiten's) — the pair first, else a word mostly written in kana by its kana spelling."""
    out = []
    for pair, plain in lists:
        rank = pair.get((lemma, reading))
        if rank is None and kana:
            rank = plain.get(kana)
        out.append(rank)
    return tuple(out)


def verdicts(pos, surf, idx, lists):
    """{(lemma, reading): its facts} for every one-kanji word the text holds, with its verdicts: "word" (gates 1-3)
    and "piece" (grammar in general text)."""
    out = {}
    for key, poses in pos.items():
        lemma, reading = key
        p = majority(poses)
        found, content, common = jmdict_facts(idx, lemma, reading)
        kana = kana_spelling(surf[key])
        jpdb, jiten = ranks_of(lemma, reading, kana, lists)
        listed = bool(jpdb and jiten and max(jpdb, jiten) <= RANK)
        word = p in CONTENT_POS and found and content and (common or listed)
        piece = p[0] in GRAMMAR_POS1 or p in GRAMMAR_POS
        out[key] = {"uses": sum(poses.values()), "pos": p, "share": round(poses[p] / sum(poses.values()), 3),
                    "found": found, "content": content, "common": common, "jpdb": jpdb, "jiten": jiten,
                    "kana": kana, "word": bool(word), "piece": bool(piece),
                    "surface": max(surf[key].items(), key=lambda item: (item[1], item[0]))[0]}
    return out


# --- The module ----------------------------------------------------------------------------------------------------- #

def blob(obj):
    raw = zlib.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    text = base64.b64encode(raw).decode("ascii")
    return "\n".join(f'    "{text[i:i + 100]}"' for i in range(0, len(text), 100))


def write_module(words, pieces, created, path=OUTPUT):
    """app/one_kanji_data.py — the two tables, sorted, compressed; REVISION names the build (date + a digest)."""
    words = sorted(f"{lemma}|{reading}" for lemma, reading in words)
    pieces = sorted(f"{lemma}|{reading}" for lemma, reading in pieces)
    digest = hashlib.sha1(json.dumps([words, pieces], ensure_ascii=False).encode("utf-8")).hexdigest()[:8]
    revision = f"{date.today().isoformat()}-{digest}"
    text = f'''"""One-kanji words the list can offer — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_one_kanji_data.py   (after scripts/build_reference_data.py)

Revision: {revision}
  WORDS   {len(words):,} one-kanji words -> "lemma|reading" (UniDic's lemma and its reading): each one general text uses as a
          word of its own (a common noun, a pronoun, a な-word, an adverb, a conjunction or an interjection) that JMdict
          lists with that reading and marks common, or that JPDB 2024 and Jiten both rank in their top 20,000. With
          Settings -> "List one-kanji words only when they're dictionary words" on, these are the one-character words
          the list can offer, counted where they stand on their own (analyzer.bound_uses).
  PIECES  {len(pieces):,} one-kanji words general text uses as grammar (a prefix, a suffix, a particle, an auxiliary, the よう of
          ような): never shown as "not on your list" in the report.

Derived from JMdict (JMdict created {created}), a dictionary of the JMdict/EDICT project, property of the Electronic
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

REVISION = "{revision}"
JMDICT_CREATED = "{created}"

_WORDS_B64 = (
{blob(words)}
)

_PIECES_B64 = (
{blob(pieces)}
)

_words = None
_pieces = None


def _decode(b64):
    return frozenset(tuple(item.split("|", 1)) for item in json.loads(zlib.decompress(base64.b64decode(b64)).decode("utf-8")))


def words():
    """{{(lemma, reading)}}: the one-kanji words the list can offer. Empty when unreadable."""
    global _words
    if _words is None:
        try:
            _words = _decode(_WORDS_B64)
        except Exception:
            _words = frozenset()
    return _words


def pieces():
    """{{(lemma, reading)}}: the one-kanji words general text uses as grammar. Empty when unreadable."""
    global _pieces
    if _pieces is None:
        try:
            _pieces = _decode(_PIECES_B64)
        except Exception:
            _pieces = frozenset()
    return _pieces
'''
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return revision, os.path.getsize(path)


def write_report(facts, files, created, revision, size, seconds, path=REPORT):
    """debug/one_kanji_data.md — what passed and what didn't, by gate, with the most used of each, for a person."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = sorted(facts.items(), key=lambda item: (-item[1]["uses"], item[0]))
    words = [(k, f) for k, f in rows if f["word"]]
    pieces = [(k, f) for k, f in rows if f["piece"]]

    def why_not(f):
        if f["pos"] not in CONTENT_POS:
            return "gate 1: " + "-".join(f["pos"])
        if not f["found"]:
            return "gate 2: not in JMdict with this reading"
        if not f["content"]:
            return "gate 2: only an affix / counter / numeral / particle sense"
        return f"gate 3: not common (JPDB {f['jpdb']}, Jiten {f['jiten']})"
    rejected = Counter(why_not(f).split(":")[0] for _k, f in rows if not f["word"])
    lines = [f"# One-kanji words the list can offer — the build (revision {revision})", "",
             f"JMdict created {created}; the shared set's text, {files} files; {seconds:.0f} s; app/one_kanji_data.py "
             f"{size:,} bytes.", "",
             f"- One-kanji (lemma, reading)s the text holds: {len(rows):,} ({sum(f['uses'] for _k, f in rows):,} uses).",
             f"- WORDS (gates 1-3): **{len(words):,}** ({sum(f['uses'] for _k, f in words):,} uses).",
             f"- PIECES (grammar in general text): {len(pieces):,}.",
             "- Kept off: " + ", ".join(f"{gate} {n:,}" for gate, n in sorted(rejected.items())) + ".", "",
             "## WORDS, by uses in the text (first 300)", "",
             "| lemma | reading | spelled | uses | pos (share) | JMdict common | JPDB | Jiten |", "|---|---|---|--:|---|---|--:|--:|"]
    for (lemma, reading), f in words[:300]:
        lines.append(f"| {lemma} | {reading} | {f['surface']} | {f['uses']:,} | {'-'.join(f['pos'])} ({f['share']}) | "
                     f"{'yes' if f['common'] else ''} | {f['jpdb'] or ''} | {f['jiten'] or ''} |")
    lines += ["", "## Kept off, by uses in the text (first 300)", "", "| lemma | reading | spelled | uses | why |",
              "|---|---|---|--:|---|"]
    for (lemma, reading), f in [(k, f) for k, f in rows if not f["word"]][:300]:
        lines.append(f"| {lemma} | {reading} | {f['surface']} | {f['uses']:,} | {why_not(f)}"
                     f"{' · piece' if f['piece'] else ''} |")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--jmdict", default=JMDICT)
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--text", default=None, help="the shared set's staged text, when not in docs/assets/corpora/_text")
    parser.add_argument("--dump", default=None, help="also write every word's facts and parts of speech (JSON) here")
    args = parser.parse_args(argv)
    t0 = time.time()

    def log(text):
        print(text, flush=True)

    import jmdict_flags as jf
    created = jf.created(args.jmdict)
    log(f"JMdict created {created}: reading it...")
    idx = jf.index(jf.load(args.jmdict))
    lists = [load_ranks("JPDB 2024"), load_ranks("Jiten")]
    log(f"Reading the shared set's text with {args.workers} workers...")
    pos, surf, files = corpus_pass(args.workers, log, args.text)
    facts = verdicts(pos, surf, idx, lists)
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            json.dump({f"{lemma}|{reading}": {**fact, "pos": "-".join(fact["pos"]),
                                               "poses": {"-".join(p): n for p, n in pos[(lemma, reading)].items()}}
                       for (lemma, reading), fact in facts.items()}, f, ensure_ascii=False)
    words = {key for key, f in facts.items() if f["word"]}
    pieces = {key for key, f in facts.items() if f["piece"] and not f["word"]}
    revision, size = write_module(words, pieces, created)
    seconds = time.time() - t0
    write_report(facts, files, created, revision, size, seconds)
    log(f"{len(words):,} words, {len(pieces):,} pieces -> {os.path.relpath(OUTPUT, ROOT)} ({size:,} bytes, "
        f"revision {revision}); {seconds:.0f} s. Report: {os.path.relpath(REPORT, ROOT)}")


if __name__ == "__main__":
    main()
