"""Distil JMdict's set phrases into app/phrase_data.py (DEV ONLY — never shipped).

Why this exists
---------------
The tokenizer never joins a phrase — 気がする stays 気 + が + する — so, with Settings -> Language & Parsing -> "Idioms
and set phrases on your list" on, the analyzer finds the dictionary's set phrases in the words it already has and lists
each one the library meets often enough as a row of its own (app/phrases.py). Which strings are set phrases, and which
of their words live only inside them, is a question about Japanese, not about any learner: it depends on JMdict, the
frequency lists, general text and the tokenizer — all fixed when we build. So it is decided HERE, once, and the app
ships the result: each phrase's lemmas, their readings, each word's role and a spelling to show. No glosses.

The rule, in order (each step's count and examples go to debug/phrase_data.md, for a person to read):
  R1 spellings  each entry's kanji forms (not irregular, outdated, rare or search-only) with the readings that go with
                them, and its kana forms when it has no kanji form or a sense usually written in kana; up to 16
                characters; no Latin letters or digits.
  R2 read alone each spelling read by the app's own tokenizer, the way shared data is read (join_affixes(...,
                library=False)). One word -> never a phrase: UniDic keeps it whole, or an affix, a compound, a name or a
                sound word + と made it one word, and the list counts it as that word already.
  R3 shaped     2-5 words; no number or symbol inside; no proper noun; not starting with grammar (a particle, an
                ending, a suffix, a grammar stem), a conjunction or a filler as read alone; not a shape the compound
                table owns (nouns, な-words and affixes only; a verb stem + a verb); no spelling the compound table
                holds (予想通り and こと自体 are compounds, with or without "Phrases and titles as one word").
  R4 roles      each word grammar (a particle, an ending, a prefix or suffix, a grammar stem, an auxiliary verb right
                after the て / で that makes it one), a light verb or adjective (する, なる, ある, いる, できる, ない,
                いい and their polite forms) or a real word.
  R5 a phrase   two real words, or one with a light one (気がする, 間違いない, もしかしたら); never one word with only
                grammar after it (それは, 言って, 帰ってくる); never a card the app reads as one word + an ending
                (anki_match.one_word: どうしよう is どう + する, as 努力する is 努力); never one word said twice (うんうん).
  R6 keys       a phrase is its words' lemmas: spellings that share them are one phrase, shown in their commonest
                spelling (the one the frequency lists rank best).
  R7 a unit     in general text — the shared set's text, as the compound table's counts are made — each phrase's
                matches by the app's own matcher, turned into the rank they would have among that text's words. Kept
                when JPDB 2024 (else Jiten) ranks the phrase at most UNIT_RATIO times rarer than that; left out when
                neither list has it, or when the text meets it far more often than the lists rank it: most of those
                matches are its words side by side (いいと思う, するという). A form that fails and is a kept phrase +
                grammar (腑に落ちない for 腑に落ちる) is left out too, so its text counts for that phrase.
  R8 bound      a real word lives only inside its phrase when JPDB 2024 lists the phrase and ranks the word alone
                rarer, or doesn't list it (腑 in 腑に落ちる, 眉根 in 眉根を寄せる): learned with the phrase, and its
                uses inside the phrase are the phrase's. No JPDB entry for the phrase: nothing bound.

Run it after scripts/build_reference_data.py: it reads the tables that build installed, so no phrase is made of what
the tokenizer already joins. Every parsing switch is read at its default, whatever settings.json says. Rebuilding
changes what a run lists: the analyzer's ENGINE_REVISION goes up with it (the token cache doesn't change).

Output: app/phrase_data.py (committed; ships), with the EDRDG's attribution (CC BY-SA 4.0), and debug/phrase_data.md
(gitignored), the report. Inputs: docs/assets/reference_lists/JMdict_e.gz, JPDB 2024.json and Jiten.json, and the
shared set's text in docs/assets/corpora/_text/ (all gitignored).

Usage:  python scripts/build_phrase_data.py [--jmdict PATH] [--workers N]
"""

import argparse
import base64
import bisect
import hashlib
import json
import os
import random
import re
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from app.unicode_ranges import HAN, KANA  # noqa: E402  (pure)

OUTPUT = os.path.join(ROOT, "app", "phrase_data.py")
REPORT = os.path.join(ROOT, "debug", "phrase_data.md")
JMDICT = os.path.join(ROOT, "docs", "assets", "reference_lists", "JMdict_e.gz")

MAX_CHARS = 16
RARE_KANJI = frozenset(("iK", "oK", "rK", "sK"))       # irregular, outdated, rarely used, search-only kanji forms
RARE_KANA = frozenset(("ik", "ok", "rk", "sk"))
COMMON = frozenset(("news1", "ichi1", "spec1", "spec2", "gai1"))
_LATIN = re.compile(r"[A-Za-z0-9Ａ-Ｚａ-ｚ０-９]")
_JAPANESE = re.compile(f"[{KANA}{HAN}]")
_KANJI = re.compile(f"[{HAN}]")
# What can't start a phrase, as its first word is read alone: grammar, a conjunction (でまた) or a filler (あの子 —
# the tagger reads あの alone as one).
_NEVER_FIRST = frozenset(("助詞", "助動詞", "接尾辞", "接続詞"))
_GRAMMAR = frozenset(("助詞", "助動詞", "接頭辞", "接尾辞"))
_COMPOUND_POS1 = frozenset(("名詞", "形状詞", "接頭辞", "接尾辞"))
# The light verbs and the grammatical adjectives — する / なる / ある / いる / できる and their polite forms, ない and
# いい: a closed grammatical class (like anki_match.CARD_ENDINGS), never a word a phrase waits for.
LIGHT = frozenset(("為る", "成る", "有る", "居る", "出来る", "為さる", "致す", "御座る", "無い", "良い"))
# R7: how much rarer than its count in general text the lists may rank a phrase and it is still a unit. Read off the
# measurement (the real phrases' ratios sit far below it: 気がする 1.2, 首を傾げる 2.4); moved only with the user.
UNIT_RATIO = 8
WORKERS = min(12, os.cpu_count() or 1)


# --- R1: the spellings -------------------------------------------------------------------------------------------- #

def entry_spellings(entry):
    """[(spelling, [readings])] worth reading for one JMdict entry (R1) — none for a title: an entry every sense of
    which names a work, a product, a company or an organization (進撃の巨人, うまい棒) is a name, never a phrase."""
    import jmdict_flags
    if jmdict_flags.is_title([entry]):
        return []
    out = []
    usually_kana = any("uk" in sense["misc"] for sense in entry["senses"])
    for keb, _pri, inf in entry["kanji"]:
        if RARE_KANJI.intersection(inf):
            continue
        readings = [reb for reb, _pri, restr, nokanji, rinf in entry["kana"]
                    if not nokanji and (not restr or keb in restr) and not RARE_KANA.intersection(rinf)]
        out.append((keb, readings))
    if not entry["kanji"] or usually_kana:
        for reb, _pri, _restr, _nokanji, rinf in entry["kana"]:
            if not RARE_KANA.intersection(rinf):
                out.append((reb, [reb]))
    return [(s, r) for s, r in out
            if len(s) <= MAX_CHARS and not _LATIN.search(s) and _JAPANESE.search(s)]


def pre_noun(entry, idx=None):
    """Does JMdict class the entry only as a pre-noun adjectival — adj-pn in every sense, nothing beside it but exp
    (ああいう, こういう, ひどすぎる) — or file it as an expression every sense of which it sends to one (そういった: exp,
    'see そういう'; `idx`, jmdict_flags.index, looks the reference up)? Then a phrase it alone gives stands only before
    a noun (phrases.before_a_noun)."""
    senses = entry["senses"]
    if not senses:
        return False
    if all("adj-pn" in s["pos"] and set(s["pos"]) <= {"adj-pn", "exp"} for s in senses):
        return True
    if idx is None or not all(set(s["pos"]) == {"exp"} and s["xref"] for s in senses):
        return False
    by_kanji, by_kana = idx
    for s in senses:
        for ref in s["xref"]:
            spelling = ref.split("・")[0]
            if not any(pre_noun(target) for target in by_kanji.get(spelling, []) + by_kana.get(spelling, [])):
                return False
    return True


def usually_kana(entry):
    """Does JMdict say the entry is usually written in kana — "uk" on every sense (そういった, ああいう, どういう)? A
    pre-noun adjectival that only such entries give is found only as written in kana (phrases.before_a_noun): with the
    verb's kanji, そう言ったのは is 'that he said so'."""
    return bool(entry["senses"]) and all("uk" in s["misc"] for s in entry["senses"])


def pre_noun_mark(c):
    """The data's sixth field for candidate `c`: 1 a pre-noun adjectival (`pre_noun`), 2 one usually written in kana
    too (`usually_kana`) that has a spelling in kana to be found in, else 0 — every entry behind the key, or none."""
    if not c["prenoun"]:
        return 0
    return 2 if c["kana"] and any(not _KANJI.search(s) for s in c["spellings"]) else 1


def entry_flags(entry):
    """What JMdict says of an entry, for the report: an expression, an idiom, a proverb, common."""
    pos = {p for sense in entry["senses"] for p in sense["pos"]}
    misc = {m for sense in entry["senses"] for m in sense["misc"]}
    pri = {p for _k, pri, _i in entry["kanji"] for p in pri} | {p for _r, pri, *_x in entry["kana"] for p in pri}
    return {"exp": "exp" in pos, "idiom": "id" in misc, "proverb": "proverb" in misc, "common": bool(COMMON & pri)}


# --- R2-R5: a spelling read alone --------------------------------------------------------------------------------- #

def read_alone(tagger, joins, spelling):
    """The words of `spelling` read alone, as the tokenizer reads a line of shared data: [(lemma or None, reading,
    surface, orth, pos1, pos2)] — a symbol, a space or a number kept, with lemma None (analyzer.word_lemma)."""
    from app import analyzer
    out = []
    for word in analyzer.join_affixes(tagger(spelling), joins, library=False):
        f = word.feature
        lemma = analyzer.word_lemma(word)
        if lemma is not None:
            lemma = analyzer._sanitize_term(lemma)
        orth = analyzer._sanitize_term(f.orthBase or word.surface)
        out.append((lemma, f.lForm or f.kana or "", word.surface, orth, f.pos1, f.pos2))
    return out


def shape(tokens, spelling, compounds):
    """Why a spelling read as several words is no phrase (R3), or "" for one that may be."""
    if any(t[0] is None for t in tokens):
        return "a number or a symbol inside"
    if not 2 <= len(tokens) <= 5:
        return "more than 5 words"
    if any(t[5] == "固有名詞" for t in tokens):
        return "a proper noun inside"
    if any("|" in t[0] or not t[0].strip() or t[0] != t[0].strip() or " " in t[0] for t in tokens):
        return "a lemma a key can't hold"
    first = tokens[0]
    if first[4] in _NEVER_FIRST or (first[4] == "形状詞" and first[5] == "助動詞語幹"):
        return "starts with grammar or a conjunction"
    if first[5] == "フィラー":
        return "starts with a filler"
    if all(t[4] in _COMPOUND_POS1 and not (t[4] == "形状詞" and t[5] == "助動詞語幹") for t in tokens):
        return "a compound's shape (nouns / な-words / affixes)"
    if len(tokens) == 2 and tokens[0][4] == "動詞" and tokens[1][4] == "動詞":
        return "a compound's shape (a verb + a verb)"
    if spelling in compounds:
        return "a spelling the compound table holds"
    return ""


def roles(tokens):
    """Each word's role (R4): "g" grammar, "l" light, "c" a real word."""
    out = []
    for i, t in enumerate(tokens):
        pos1, pos2 = t[4], t[5]
        after_te = i and tokens[i - 1][4] == "助詞" and tokens[i - 1][0] in ("て", "で")
        if pos1 in _GRAMMAR or (pos1 == "形状詞" and pos2 == "助動詞語幹"):
            out.append("g")
        elif pos1 in ("動詞", "形容詞") and pos2 == "非自立可能" and after_te:
            out.append("g")
        elif t[0] in LIGHT:
            out.append("l")
        else:
            out.append("c")
    return "".join(out)


def structure(tokens, role):
    """Why a phrase-shaped reading is not built like a phrase (R5), or "" for one that is."""
    from app import anki_match
    content, light = role.count("c"), role.count("l")
    if not (content >= 2 or (content == 1 and light)):
        return "one word + grammar"
    if anki_match.one_word([t[:4] for t in tokens]) is not None:
        return "a card the app reads as one word + an ending"
    words = [t[0] for t, r in zip(tokens, role) if r == "c"]
    if len(words) >= 2 and len(set(words)) == 1:
        return "one word said twice"
    return ""


def candidates(entries, compounds, log):
    """-> ([candidate], {step: Counter}, {step: [examples]}) — every JMdict phrase built like one (R1-R6). A
    candidate: {"key", "readings", "roles", "spellings", "readings_jm", "orths", "flags", "seqs"}."""
    from app import analyzer
    spellings = defaultdict(list)          # spelling -> [(entry index, [readings])]
    for i, entry in enumerate(entries):
        for spelling, readings in entry_spellings(entry):
            spellings[spelling].append((i, readings))
    log(f"  R1: {len(spellings):,} spellings to read")
    steps, examples = Counter(), defaultdict(list)

    def out(step, spelling):
        steps[step] += 1
        if len(examples[step]) < 20:
            examples[step].append(spelling)

    tagger, joins = analyzer.Tagger(), analyzer.affix_joins()
    import jmdict_flags
    idx = jmdict_flags.index(entries)       # a cross-reference looked up (pre_noun)
    by_key = {}
    t0 = time.time()
    for n, (spelling, found) in enumerate(spellings.items(), 1):
        tokens = read_alone(tagger, joins, spelling)
        if sum(1 for t in tokens if t[0] is not None) <= 1 and len(tokens) <= 1:
            out("R2 one word", spelling)
            continue
        why = shape(tokens, spelling, compounds)
        if why:
            out("R3 " + why, spelling)
            continue
        role = roles(tokens)
        why = structure(tokens, role)
        if why:
            out("R5 " + why, spelling)
            continue
        out("phrase-shaped", spelling)
        key = tuple(t[0] for t in tokens)
        item = by_key.get(key)
        if item is None:
            item = by_key[key] = {"key": key, "readings": tuple(t[1] for t in tokens), "roles": role,
                                  "spellings": [], "readings_jm": [], "orths": [set() for _ in tokens],
                                  "spelled": {}, "flags": Counter(), "seqs": set(), "prenoun": True,
                                  "kana": True}
        item["spellings"].append(spelling)
        for k, t in enumerate(tokens):
            item["orths"][k].add(t[3])
        for i, readings in found:
            item["seqs"].add(entries[i]["seq"])
            item["prenoun"] = item["prenoun"] and pre_noun(entries[i], idx)     # every entry behind it, or none
            item["kana"] = item["kana"] and usually_kana(entries[i])
            item["flags"].update(k for k, v in entry_flags(entries[i]).items() if v)
            for reading in readings:
                kana = _katakana(reading)
                if kana not in item["readings_jm"]:
                    item["readings_jm"].append(kana)
                item["spelled"].setdefault(spelling, kana)      # the first reading JMdict gives this spelling
        if n % 50_000 == 0:
            log(f"    {n:,} read ({time.time() - t0:.0f} s)")
    log(f"  R2-R6: {len(by_key):,} phrases built like one, from {steps['phrase-shaped']:,} spellings "
        f"({time.time() - t0:.0f} s)")
    return list(by_key.values()), steps, examples


def _katakana(text):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


# --- R7: a unit in general text ----------------------------------------------------------------------------------- #

_WORKER = {}


def _init(rows):
    """A worker: the tokenizer as shared data reads text (every switch at its default), and the matcher."""
    from app import analyzer, phrases
    import build_reference_data as brd
    brd.pin_parsing_defaults()
    analyzer.SANITIZE_JA = True
    _WORKER.update(tokenizer=analyzer.JapaneseTokenizer(library=False), phrases=phrases.PhraseSet(rows),
                   has=analyzer.has_target_language)


def _count_file(path):
    """-> (path, sentences, {(lemma, reading): uses}, {phrase index: matches}) for one text file of the shared set."""
    tokenizer, found_in, has = _WORKER["tokenizer"], _WORKER["phrases"].find, _WORKER["has"]
    words, found, sentences = Counter(), Counter(), 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            for text, tokens in tokenizer.tokenize_sentences(line):
                sentences += 1
                for lemma, reading, surface, _orth in tokens:
                    if has(lemma, "ja") or has(surface, "ja"):
                        words[(lemma, reading)] += 1
                for _start, _end, index in found_in(tokens, text):
                    found[index] += 1
    return path, sentences, words, found


def corpus_pass(rows, workers, log):
    """Every phrase's matches and every word's uses over the shared set's text. -> (words, found, sentences, files)."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor
    import build_reference_data as brd
    paths = sorted(brd._corpus_texts(), key=lambda p: -os.path.getsize(p))
    words, found, sentences = Counter(), Counter(), 0
    t0 = time.time()
    with ProcessPoolExecutor(workers, multiprocessing.get_context("spawn"), _init, (rows,)) as pool:
        for done, (path, n, w, f) in enumerate(pool.map(_count_file, paths), 1):
            words.update(w)
            found.update(f)
            sentences += n
            log(f"    {done}/{len(paths)} {os.path.relpath(path, brd.CORPUS_TEXT)} ({time.time() - t0:.0f} s)")
    return words, found, sentences, len(paths)


def unit_test(cands, found, words, jpdb, jiten):
    """R7 — which candidates are units in general text. -> (kept, dropped, folded {key: the key it counts for}),
    each candidate given "uses" (its matches, with the forms folded into it), "rank" (JPDB, else Jiten), "list" (which)
    and "ratio" (its rank over the rank its uses would have among the text's words)."""
    counts = sorted((n for n in words.values() if n >= 2), reverse=True)
    negated = [-n for n in counts]

    def text_rank(uses):
        return bisect.bisect_left(negated, -uses) + 1

    by_key = {}
    for i, c in enumerate(cands):
        c["uses"] = found.get(i, 0)
        by_key[c["key"]] = c
        readings = c["readings_jm"] or [None]
        c["jpdb"] = min((r for r in (jpdb.rank(c["spellings"], rd) for rd in readings) if r), default=None)
        c["jiten"] = min((r for r in (jiten.rank(c["spellings"], rd) for rd in readings) if r), default=None)
        c["rank"], c["list"] = (c["jpdb"], "JPDB") if c["jpdb"] is not None else (c["jiten"], "Jiten")

    def passes(c):
        if c["rank"] is None:
            c["ratio"] = None
            return False
        c["ratio"] = c["rank"] / text_rank(c["uses"])
        return c["ratio"] <= UNIT_RATIO

    kept, dropped, folded = [], [], {}
    # Longest first: a form that fails folds its matches into the shorter phrase it is + grammar, before that one's test.
    for c in sorted(cands, key=lambda c: (-len(c["key"]), c["key"])):
        if passes(c):
            kept.append(c)
            continue
        base = None
        for k in range(len(c["key"]) - 1, 1, -1):
            b = by_key.get(c["key"][:k])
            if b is not None and all(r == "g" for r in c["roles"][k:]):
                base = b
                break
        if base is not None:
            base["uses"] += c["uses"]
            folded[c["key"]] = base["key"]
        dropped.append(c)
    return kept, dropped, folded


# --- R8: the words that live only inside their phrase -------------------------------------------------------------- #

def piece_rank(ranks, spellings, reading, phrase_readings):
    """A word's best rank in `ranks`, reading-aware — and, when the list lacks the word in the reading it was read
    with, in another reading the list gives it that the phrase's own reading holds: read alone, a headword's word can
    be read wrong (気の強い's 強い as シイ, ほめ上手's 上手 as カミテ), and the dictionary's reading of the phrase
    (キノツヨイ) says which word it is."""
    rank = ranks.rank(spellings, reading)
    if rank is None:
        for s in spellings:
            for other in ranks.readings.get(s, ()):
                found = ranks.pairs.get((s, other)) if other != reading else None
                if found is not None and any(other in whole for whole in phrase_readings) \
                        and (rank is None or found < rank):
                    rank = found
    return rank


def bind(c, jpdb):
    """`c`'s roles with each real word that lives only inside it marked "b" (R8)."""
    if c["jpdb"] is None:
        return c["roles"]
    out = []
    for k, role in enumerate(c["roles"]):
        if role == "c":
            rank = piece_rank(jpdb, sorted(c["orths"][k]) + [c["key"][k]], c["readings"][k], c["readings_jm"])
            if rank is None or rank > c["jpdb"]:
                role = "b"
        out.append(role)
    return "".join(out)


def display(c, jpdb, jiten):
    """The spelling to show when the library never writes the phrase itself — the one the lists rank best, else the
    first — among those JMdict reads as the phrase's own words read (a spelling of another word the tagger misreads
    into the same words, こん身 for 渾身 among この身's, never names it), else among all."""
    readings = c["readings_jm"] or [None]
    own = "".join(c["readings"])

    def best(ranks, s):
        found = [r for r in (ranks.rank([s], rd) for rd in readings) if r]
        return min(found) if found else float("inf")
    return min(c["spellings"], key=lambda s: (c["spelled"].get(s) != own, best(jpdb, s), best(jiten, s),
                                              c["spellings"].index(s)))


# --- the module --------------------------------------------------------------------------------------------------- #

def rows_of(kept):
    """[lemmas, readings, roles, spelling, its reading, pre-noun] per phrase: the row's Reading is the dictionary's
    reading of the spelling shown (モシカシタラ for もしかしたら, not the words' own readings run together), else theirs;
    pre-noun 1 when JMdict classes the phrase only as a pre-noun adjectival, 2 when it is usually written in kana too
    (`pre_noun_mark`)."""
    return sorted([["|".join(c["key"]), "|".join(c["readings"]), c["bound"], c["display"],
                    c["spelled"].get(c["display"]) or "".join(c["readings"]), pre_noun_mark(c)] for c in kept])


def blob(obj):
    return base64.b64encode(
        zlib.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)).decode("ascii")


def write_module(rows, created, path=OUTPUT):
    for key, readings, role, shown, reading, prenoun in rows:
        lemmas = key.split("|")
        assert 2 <= len(lemmas) <= 5 and all(lemmas) and " " not in key, key
        assert len(readings.split("|")) == len(lemmas) == len(role) and shown and reading and prenoun in (0, 1, 2), key
    body = blob(rows)
    revision = f"{date.today().isoformat()}-{hashlib.sha1(body.encode('ascii')).hexdigest()[:8]}"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(TEMPLATE.format(revision=revision, created=created or "", count=len(rows),
                                n_bound=sum(1 for r in rows if "b" in r[2]), n_prenoun=sum(1 for r in rows if r[5]),
                                n_kana=sum(1 for r in rows if r[5] == 2), body=body))
    return revision


def main(argv=None):
    import build_reference_data as brd
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jmdict", default=JMDICT)
    parser.add_argument("--lists", default=brd.LISTS_DIR, help="the folder holding JPDB 2024.json and Jiten.json")
    parser.add_argument("--corpus", default=brd.CORPUS_TEXT, help="the shared set's text (docs/assets/corpora/_text)")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args(argv)
    brd.LISTS_DIR, brd.CORPUS_TEXT = args.lists, args.corpus
    t0 = time.time()
    lines = []

    def log(text):
        print(text, flush=True)
        lines.append(text)

    import jmdict_flags
    from app import analyzer
    brd.pin_parsing_defaults()
    analyzer.SANITIZE_JA = True
    created = jmdict_flags.created(args.jmdict)
    entries = jmdict_flags.load(args.jmdict)
    log(f"JMdict: {len(entries):,} entries, created {created} ({time.time() - t0:.0f} s)")
    cands, steps, examples = candidates(entries, analyzer.compound_joins(), log)
    del entries
    jpdb, jiten = brd.ListReadings("JPDB 2024"), brd.ListReadings("Jiten")
    for c in cands:
        # Before the corpus pass: a phrase with a form of its own (もしかしたら) is found only in that form
        # (phrases.fixed_form), so the matcher needs the spelling it shows.
        c["display"] = display(c, jpdb, jiten)
    rows = [["|".join(c["key"]), "|".join(c["readings"]), c["roles"], c["display"], "", pre_noun_mark(c)]
            for c in cands]
    log(f"R7: the shared set's text, {args.workers} workers...")
    t1 = time.time()
    words, found, sentences, files = corpus_pass(rows, args.workers, log)
    log(f"  {files} files, {sentences:,} sentences, {sum(words.values()):,} words counted, "
        f"{sum(found.values()):,} phrase matches ({time.time() - t1:.0f} s)")
    kept, dropped, folded = unit_test(cands, found, words, jpdb, jiten)
    for c in kept:
        c["bound"] = bind(c, jpdb)
    rows = rows_of(kept)
    revision = write_module(rows, created)
    size = os.path.getsize(OUTPUT)
    log(f"Wrote {OUTPUT}: {len(rows):,} phrases, {size / 1024:,.0f} KB, revision {revision} "
        f"({time.time() - t0:.0f} s in all)")
    write_report(cands, kept, dropped, folded, steps, examples, words, lines, created, revision, size,
                 time.time() - t0)
    return 0


def write_report(cands, kept, dropped, folded, steps, examples, words, lines, created, revision, size, seconds):
    """debug/phrase_data.md (gitignored): how the phrases were decided, for a person to read."""
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    rng = random.Random(20260930)
    out = [f"# The phrase data — built {date.today().isoformat()} (revision {revision})", "",
           f"JMdict created {created}; {len(kept):,} phrases kept of {len(cands):,} built like one; "
           f"app/phrase_data.py {size / 1024:,.0f} KB; {seconds:.0f} s.", "", "## Log", ""]
    out += [f"    {line}" for line in lines]
    out += ["", "## R1-R5, spellings by step (20 examples each)", ""]
    for step, n in sorted(steps.items(), key=lambda kv: -kv[1]):
        out.append(f"- **{step}**: {n:,} — " + ", ".join(examples[step]))
    ratio = [c for c in cands if c.get("ratio") is not None]
    near_kept = sorted([c for c in ratio if c in kept], key=lambda c: -c["ratio"])[:50]
    near_dropped = sorted([c for c in ratio if c not in kept and c["key"] not in folded], key=lambda c: c["ratio"])[:50]
    out += ["", f"## R7, the unit test (ratio = list rank / the rank its matches have in the text; kept at "
            f"<= {UNIT_RATIO})", ""]
    out.append(f"Dropped: {len(dropped):,} — in no list {sum(1 for c in dropped if c['rank'] is None):,}, "
               f"folded into their phrase {len(folded):,}, too common as words side by side "
               f"{sum(1 for c in dropped if c['rank'] is not None and c['key'] not in folded):,}.")
    for title, pool in (("The 50 kept nearest the line", near_kept), ("The 50 dropped nearest the line", near_dropped)):
        out += ["", f"### {title}", "", "| phrase | matches | list rank | ratio | JMdict |", "| :-- | --: | --: | --: | :-- |"]
        for c in pool:
            out.append(f"| {c['spellings'][0]} | {c['uses']:,} | {c['list']} {c['rank']:,} | {c['ratio']:.1f} | "
                       f"{', '.join(sorted(c['flags']))} |")
    common = sorted([c for c in dropped if c["rank"] is not None and c["key"] not in folded], key=lambda c: -c["uses"])
    out += ["", "### Dropped with the most matches", "", ", ".join(f"{c['spellings'][0]} ({c['uses']:,})"
                                                             for c in common[:60])]
    out += ["", "### Folded into their phrase (the 40 with the most matches)", ""]
    out.append(", ".join(f"{c['spellings'][0]} → {''.join(folded[c['key']])} ({c['uses']:,})"
                         for c in sorted([c for c in dropped if c["key"] in folded], key=lambda c: -c["uses"])[:40]))
    keys = {c["key"]: c for c in kept}
    near = [(keys[c["key"][:k]], c) for c in kept for k in range(len(c["key"]) - 1, 1, -1)
            if c["key"][:k] in keys and all(r == "g" for r in c["roles"][k:])]
    out += ["", f"## Near-duplicates kept as two rows ({len(near):,}: a phrase and the phrase + grammar)", "",
            ", ".join(f"{a['display']} / {b['display']}" for a, b in near[:80])]
    bound = [(c, k) for c in kept for k, r in enumerate(c["bound"]) if r == "b"]
    out += ["", f"## R8, words that live only inside their phrase: {len(bound):,} in "
            f"{sum(1 for c in kept if 'b' in c['bound']):,} phrases (50 at random)", ""]
    for c, k in rng.sample(bound, min(50, len(bound))):
        out.append(f"- {c['key'][k]} in {c['display']} (the phrase JPDB #{c['jpdb']:,})")
    pre = sorted(c["display"] for c in kept if c["prenoun"])
    kana = sorted(c["display"] for c in kept if c["prenoun"] and c["kana"])
    out += ["", f"## Pre-noun adjectivals (JMdict: adj-pn in every sense, nothing beside it but exp — or an expression "
            f"it sends to one): {len(pre):,} — "
            "found only uninflected, straight before a word of its own", "", ", ".join(pre), "",
            f"Usually written in kana (JMdict's uk on every sense), found only so: {len(kana):,} — " + ", ".join(kana)]
    differ = [c for c in kept if c["spelled"].get(c["display"]) != "".join(c["readings"])]
    out += ["", f"## Readings: {len(differ):,} phrases shown in a spelling whose dictionary reading is not their words' "
            "own readings run together (a conjugated end, a voiced sound — or a word the tagger misreads alone)", "",
            "| shown | its reading (the row's) | the words' readings | lemmas |", "| :-- | :-- | :-- | :-- |"]
    for c in sorted(differ, key=lambda c: c["display"])[:150]:
        out.append(f"| {c['display']} | {c['spelled'].get(c['display'])} | {''.join(c['readings'])} | "
                   f"{'|'.join(c['key'])} |")
    out += ["", "## 50 kept phrases at random", "", ", ".join(c["display"] for c in rng.sample(kept, min(50, len(kept))))]
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"Wrote {REPORT}")


TEMPLATE = '''"""Idioms and set phrases the list can offer — GENERATED, DO NOT EDIT BY HAND.

Regenerate with:  python scripts/build_phrase_data.py   (after scripts/build_reference_data.py)

Revision: {revision}
  PHRASES  {count:,} set phrases -> [lemmas, readings, roles, spelling, reading, pre-noun]: each phrase's words
           as the tokenizer reads them (UniDic lemmas and readings, `|`-joined), each word's role — "c" a real word,
           "b" a real word that lives only inside the phrase ({n_bound:,} phrases hold one), "l" a light verb or
           adjective, "g" grammar — the dictionary's commonest spelling with its reading, and 1 when JMdict classes
           the phrase only as a pre-noun adjectival ({n_prenoun:,} phrases), 2 when it also says it is usually
           written in kana ({n_kana:,} of them, found only so). app/phrases.py finds them in a sentence's words;
           Settings -> "Idioms and set phrases on your list" lists the ones a library meets often enough.

Derived from JMdict (JMdict created {created}), a dictionary of the JMdict/EDICT project, property of the Electronic
Dictionary Research and Development Group (EDRDG), used in conformance with the Group's licence: Creative Commons
Attribution-ShareAlike 4.0 International (CC BY-SA 4.0), https://creativecommons.org/licenses/by-sa/4.0/ —
https://www.edrdg.org/edrdg/licence.html, https://www.edrdg.org/jmdict/j_jmdict.html. Changes: only the headwords of
its set phrases are kept (no glosses), read into their words by the app's tokenizer, with which of them live only
inside the phrase (by JPDB 2024's ranks) and which phrases are units in general text. This table is shared under the
same licence.

Stored compressed and decoded when first asked for; empty when it cannot be read, never an exception.
"""

import base64
import json
import zlib

REVISION = "{revision}"
JMDICT_CREATED = "{created}"
COUNT = {count}

_PHRASES_B64 = (
    "{body}"
)


def phrases():
    """[[lemmas, readings, roles, spelling, reading, pre-noun], ...] — every phrase, decoded on each call
    (app/phrases.py keeps one decoded set per process); [] when unreadable."""
    try:
        return json.loads(zlib.decompress(base64.b64decode(_PHRASES_B64)).decode("utf-8"))
    except Exception:
        return []
'''


if __name__ == "__main__":
    sys.exit(main())
