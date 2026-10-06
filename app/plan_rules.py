"""The rules a Generate and the fast re-plan share (E1.1 02 §2, RUNBOOK E1.3.1): one implementation, two callers.

`app/analyzer.py` calls them with its own tables, `app/plan_engine.py` with the plan file's: the spelling a row shows
(`display_orth`), the spellings it was met in (`display_forms`), the progressive pass (`progressive_pass`) and the run
signature's digest (`signature_digest`). Pure: the standard library and the app's own data tables only — no pandas,
no tokenizer, no settings — so the engine can import it in any process (E1.3.5's guard).
"""
import hashlib
import json
import re

from app.unicode_ranges import KANA_LETTERS

# --------------------------------------------------------------------------------------------------------------- #
# Orth and Forms
# --------------------------------------------------------------------------------------------------------------- #

# A sound word's kana ending in っ / ッ (ドキッ, ぐっ): a word join_affixes joins to a と after it.
_SOKUON_ADVERB = re.compile(f"^[{KANA_LETTERS}ー]+[っッ]$")

# JMdict's readings that end in と (app/jmdict_data.py's READINGS: どきっと, ぐっと, はっと), read once — which sound words a
# dictionary writes with their と. Empty when the table can't be read: then every row shows its commonest spelling.
_TO_READINGS = []


def _jmdict_to_readings():
    if not _TO_READINGS:
        try:
            from app import jmdict_data
            readings = (line.partition("\t")[0] for line in jmdict_data.readings().split("\n"))
            _TO_READINGS.append(frozenset(reading for reading in readings if reading.endswith("と")))
        except Exception:
            _TO_READINGS.append(frozenset())
    return _TO_READINGS[0]


def _hiragana(text):
    """Katakana to hiragana, everything else as it is (anki_match.fold_kana): ドキッと -> どきっと."""
    return "".join(chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text)


def _said_with_to(orths):
    """{spelling: count} of a sound word said with と (ドキッと) on a row that holds it bare too (ドキッ — one row:
    join_affixes' sound word + と), when JMdict lists the word with its と (どきっと); {} for every other row — a word
    whose kana ends in と is no sound word (弟 beside おとうと keeps its commonest spelling)."""
    with_to = [orth for orth in orths if orth and orth.endswith("と") and _SOKUON_ADVERB.match(orth[:-1])]
    if not with_to:
        return {}
    bare = {_hiragana(orth) for orth in orths}
    listed = _jmdict_to_readings()
    return {orth: orths[orth] for orth in with_to if _hiragana(orth[:-1]) in bare and _hiragana(orth) in listed}


def display_orth(lemma, orths):
    """The spelling to SHOW for a word: the commonest orthBase seen for it, else the lemma.

    UniDic's lemma is a lexeme id, not a name. It deliberately merges every spelling of a word into
    one headword — which is exactly what you want for counting (いう + 言う + 言える are one verb,
    4,067 occurrences, not three words) and exactly what you do NOT want on a card, because the
    headword is frequently a form nobody writes: 有る for ある, 呉れる for くれる, and — because
    UniDic gives proper nouns a katakana lemma — スドウ for 須藤 and トットリ for 鳥取.

    Measured on the live library: 23.7% of listed words that appear in the user's own content were
    being named with a spelling that content never uses. So `Word` stays the identity and this is
    the label. Ties fall back to the lemma rather than picking arbitrarily.

    A sound word said with と and without is one row; it shows its と form whenever JMdict lists the word with its と —
    ドキッと, ぐっと, はっと, as dictionaries and the cards made from the list write it — even where the library says it
    bare more often (the user, 2026-10-01: "I want them on my cards with the と").
    """
    if not orths:
        return lemma
    best, best_n = None, 0
    for orth, n in (_said_with_to(orths) or orths).items():
        if orth and (n > best_n):
            best, best_n = orth, n
    return best or lemma

# How many inflected forms the `Forms` column keeps per row. The report's Search tab matches them
# as plain substrings, so a handful of the commonest is all it needs — the long tail is noise.
FORMS_LIMIT = 8

def display_forms(lemma, orths, surfaces):
    """The other spellings a word was actually met in, commonest first, joined with `|`.

    Feeds the report's Search tab: typing 食べた finds the 食べる card only because 食べた really
    occurred in the user's content, never because of a guessed de-inflection. The lemma and the
    displayed orth are left out — they are already searchable as `Word` and `Orth`. NOT named
    "Context ...": both report templates collect example sentences with startsWith('Context ').
    """
    if not surfaces:
        return ""
    shown = {lemma, display_orth(lemma, orths)}
    forms = [s for s, _ in sorted(surfaces.items(), key=lambda kv: -kv[1]) if s and s not in shown]
    return "|".join(forms[:FORMS_LIMIT])


# --------------------------------------------------------------------------------------------------------------- #
# The run signature's digest
# --------------------------------------------------------------------------------------------------------------- #

# One encoder for every signature: sorted keys, the text as written, anything else by its str().
SIGNATURE_ENCODER = json.JSONEncoder(sort_keys=True, ensure_ascii=False, default=str)


def signature_digest(parts, order_free=False, chunked=True):
    """sha256 of the signature's parts (`run_signature_parts`) as sorted-key JSON, or None for none. `chunked`: encoded
    chunk by chunk into the hash (`iterencode`) — the same text `json.dumps` writes, so the same digest, but no single
    call holds the interpreter: the journey check runs this on a worker, and one `json.dumps` of a 20,000-file list
    held the dashboard's thread 42 ms. The analyzer's own run has no other thread to wait: one call, `json.dumps`' C
    encoder (`chunked=False`).

    `order_free` (the plan file's, E1.1 01 §1): the files sorted by path, each without its label and weight — which
    tier a file is in and where, the one thing a re-plan changes; which files, their contents and everything else stay
    in it."""
    if parts is None:
        return None
    try:
        if order_free:
            parts = dict(parts, files=sorted(([fp, sig, st] for fp, sig, _l, _w, st in parts["files"]),
                                             key=lambda f: f[0]))
        if not chunked:
            return hashlib.sha256(SIGNATURE_ENCODER.encode(parts).encode("utf-8")).hexdigest()
        digest = hashlib.sha256()
        for chunk in SIGNATURE_ENCODER.iterencode(parts):
            digest.update(chunk.encode("utf-8"))
        return digest.hexdigest()
    except Exception as e:
        print(f"Warning: could not compute run signature: {e}")
        return None


def part_digests(parts):
    """{part: sha256} of the run signature's parts in their order-free form (`signature_digest`'s): what the plan file
    keeps so a re-plan can name which part of the library moved since (02 §1: known words, the word lists, files).
    `files` is digested whole here; `file_digest` gives each file's own."""
    parts = dict(parts, files=sorted(([fp, sig, st] for fp, sig, _l, _w, st in parts["files"]), key=lambda f: f[0]))
    return {name: hashlib.sha256(SIGNATURE_ENCODER.encode(value).encode("utf-8")).hexdigest()
            for name, value in parts.items()}


def file_digest(entry):
    """A file's own digest from its run-signature entry `[path, (mtime, size), label, weight, type]`: its path, its
    stat and its type — never its tier or place, which a move changes."""
    fp, sig, _l, _w, st = entry
    return hashlib.sha256(SIGNATURE_ENCODER.encode([fp, sig, st]).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------------------------------------------- #
# The progressive pass
# --------------------------------------------------------------------------------------------------------------- #

def progressive_pass(files, known, lemmas, lemma_of, keep, rank, target_coverage=0):
    """The progressive list, file by file in the order given: the words met there not yet known, learned in the file
    where they are met, most useful first, until the file is read (or its coverage target met). `analyzer.main()` runs
    it over its caches, the re-plan over the plan file's per-file records (E1.1 01 §7).

    `files`: per file, in the order, `(total, baseline, tokens, siblings, credits, phrases)` —
      total      the file's tokens (Total Count); baseline the ones known before any file (the known words, the
                 ignored ones, a one-character word the list never offers, a word's uses as a piece of another);
      tokens     flat `[key, count, bound, …]`: every other word met here, in the file's order — count after its
                 pieces, bound the uses a set phrase took (a word met here only inside its phrase is no new word);
      siblings   `[(lemma, count), …]`: words met here that only their lemma makes known (the plan's: words not on
                 the list whose lemma is a list word's; the analyzer hands every word in `tokens` instead);
      credits    `[(key, n), …]`: list words met here inside a rarer compound (ignored and never-offered left out) —
                 a row here, but learning one makes none of this file's tokens known;
      phrases    `[(key, n), …]`: set phrases on a row met here — likewise.
    `known` / `lemmas`: the session's known keys and lemmas; updated in place as each file's words are learned.
    `lemma_of(key)`, `keep(key)` (a listed word), `rank(key)` (the sort key, highest first: Score, Occurrences).

    Yields per file `(rows, Baseline %, Total Count)`, rows `[(key, Occurrences (File), Known Count, Current %, New %),
    …]`."""
    for total, baseline, tokens, siblings, credits, phrases in files:
        current = baseline
        unknown, credited = {}, {}
        for i in range(0, len(tokens), 3):
            key, count, bound = tokens[i], tokens[i + 1], tokens[i + 2]
            if key in known or lemma_of(key) in lemmas:
                current += count
            elif bound < count:
                unknown[key] = unknown.get(key, 0) + count
        for lemma, count in siblings:
            if lemma in lemmas:
                current += count
        for key, count in credits:
            if not (key in known or lemma_of(key) in lemmas):
                credited[key] = credited.get(key, 0) + count
                unknown[key] = unknown.get(key, 0) + count
        for key, count in phrases:
            if key not in known:
                credited[key] = credited.get(key, 0) + count
                unknown[key] = unknown.get(key, 0) + count

        listed = [key for key in unknown if keep(key)]
        listed.sort(key=rank, reverse=True)             # stable: equal ranks keep the order met
        rows = []
        for key in listed:
            start_pct = (current / total * 100) if total > 0 else 0
            if target_coverage > 0 and start_pct >= target_coverage:
                break                                   # the file's target met: the rest stay unknown for later files
            count = unknown[key]
            current += count - credited.get(key, 0)
            end_pct = (current / total * 100) if total > 0 else 0
            rows.append((key, count, current, round(start_pct, 2), round(end_pct, 2)))
        for row in rows:
            known.add(row[0])
            lemmas.add(lemma_of(row[0]))
        yield rows, round((baseline / total * 100) if total > 0 else 0, 2), total


# --------------------------------------------------------------------------------------------------------------- #
# Pins (E1.1 02 §7, 03 §8)
# --------------------------------------------------------------------------------------------------------------- #

def pin_groups(pins, place):
    """The pinned items ("Study its cards first"), in the order their cards go first: groups of item ids, the oldest
    pin first — one `pin` command stamps one time, so a title pinned at once is one group. `pins`: [(item_id,
    pinned_at)] (the store's `pinned()`); `place(item_id)`: the sort key listing a group's items (display only: a
    group's cards go in Junban's own order). The engine's `Result.pinned` and every Junban writer call this one rule."""
    groups = {}
    for item, at in pins:
        groups.setdefault(at, []).append(item)
    return [sorted(groups[at], key=place) for at in sorted(groups)]
