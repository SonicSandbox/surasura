"""The rules a Generate and the fast re-plan share (E1.1 02 §2, RUNBOOK E1.3.1): one implementation, two callers.

`app/analyzer.py` calls them with its own tables, `app/plan_engine.py` with the plan file's: the spelling a row shows
(`display_orth`), the spellings it was met in (`display_forms`), the progressive pass (`progressive_pass`) and the run
signature's digest (`signature_digest`). Pure: the standard library and the app's own data tables only — no pandas,
no tokenizer, no settings — so the engine can import it in any process (E1.3.5's guard).
"""
import base64
import bisect
import hashlib
import json
import re
import sys
import zlib
from array import array

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
      tokens     `(keys, counts, bounds)`, three parallel sequences: every other word met here, in the file's order —
                 its count after its pieces, and the uses a set phrase took of it (a word met here only inside its
                 phrase is no new word);
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
        for key, count, bound in zip(*tokens):
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
# Example sentences (F7, RP-11; Sonic 2026-11-06: "build it with the new version only. 60 is fine.")
# --------------------------------------------------------------------------------------------------------------- #
# A word's candidate sentences never depend on the order: the walk keeps, per list row, its first sentence in every
# file that holds it (Context 1 wherever the file goes, and — NEAR_FILES of them after its first meeting — the
# sentences right after that meeting, whatever the order), an order-free shortlist of POOL sentences (the whole library's counts, then a hash of the text — `order_free_key`; at most PER_FILE from one
# file, so a very common word's shortlist is spread across the library), an audio shortlist of AUDIO_POOL and up to
# FINISHED_POOL sentences from Finished content (newest finished first among equally easy ones). Which three of them
# a row shows is the order's: `ContextPicker`, down the list, against the words learned above it — the analyzer's
# selection pass and the plan engine's re-pick call this one implementation.
POOL = 60
AUDIO_POOL = 24
FINISHED_POOL = 15
PER_FILE = 2
NEAR_FILES = 10                 # the pick also weighs a row's first sentence in each of the next 10 files holding it
NOT_FINISHED = 1 << 30          # a sentence's finish rank when it isn't from Finished content (0 = finished last)


def order_free_key(short, long, cost, unknowns, text, where, text_hash=None):
    """How a shortlist ranks a candidate, the same in any order of the library: too short, too long, the co-words
    rarer than the word by the whole library's counts (`cost`), every unknown co-word (`unknowns`), then a hash of
    the text (`text_hash`, `text_hash_of`; worked out when not given) — never the text itself first (a text order
    picked "..."-led lines: Haya-D, 2026-11-06) — and the text and its file's path (`where`) last, so no two
    candidates tie."""
    return (short, long, cost, unknowns, text_hash_of(text) if text_hash is None else text_hash, text, where)


def text_hash_of(text):
    """The hash `order_free_key` ranks a text by (CRC-32 of its UTF-8: the same in every process and run)."""
    return zlib.crc32(text.encode("utf-8"))


def keep_best(pool, ctx, size, key_at, src_at, per_file=PER_FILE, text_at=None):
    """Offer `ctx` to `pool` (kept sorted by `ctx[key_at]`): the best `size` candidates with at most `per_file` from
    one source (`ctx[src_at]`), each key once. The result is the same set whatever order the candidates come in (the
    best `per_file` of each file, then the best `size` of those), which is what makes the shortlist order-free.
    `text_at` (a pool with no cap a file): each text once, its best copy (a line said in every episode — a show's
    song — would fill the pool with one sentence); the same in any order too (a text's best copy only gets better)."""
    key = ctx[key_at]
    if len(pool) >= size and key >= pool[-1][key_at]:
        return
    if text_at is not None:
        text = ctx[text_at]
        for i, c in enumerate(pool):
            if c[text_at] == text:
                if c[key_at] <= key:
                    return                          # a copy as good or better, kept already
                del pool[i]
                break
    src = ctx[src_at]
    same = [i for i, c in enumerate(pool) if c[src_at] == src]
    for i in same:
        if pool[i][key_at] == key:
            return                                  # this very sentence, kept already
    if len(same) >= per_file:
        worst = same[-1]                            # the pool is sorted: the file's last is its worst
        if key >= pool[worst][key_at]:
            return
        del pool[worst]
    at = bisect.bisect_left([c[key_at] for c in pool], key)
    pool.insert(at, ctx)
    del pool[size:]


def offer_spread(spread, best, ctx, size, key_at, src_at, text_at, per_file=PER_FILE):
    """Offer `ctx` to a shortlist kept in two parts (`shortlist` joins them): `spread`, the best `size` with at most
    `per_file` from one file, and `best`, the best `size` texts from any (each text once). Both are the same sets in
    any order."""
    keep_best(spread, ctx, size, key_at, src_at, per_file)
    keep_best(best, ctx, size, key_at, src_at, size, text_at)


def shortlist(spread, best, size, key_at, text_at):
    """The shortlist from its two parts (`offer_spread`): every spread candidate first, then the best of the rest —
    the best `size` texts of all, each text once (its first copy here), a file's candidates past its `per_file` best
    taken only when the spread can't fill the shortlist (a word met in a few files keeps every good sentence it has;
    a common one's come from many files)."""
    out, texts = [], set()
    for c in list(spread) + list(best):
        if c[text_at] not in texts:
            texts.add(c[text_at])
            out.append(c)
            if len(out) == size:
                break
    return out


# Known-when formulas: a co-word stops being an unknown once ANY of its clauses has every one of its rows learned
# above the word (a clause: a tuple of list rows). TRUE (known from the start): one empty clause; FALSE: none.
TRUE = ((),)
FALSE = ()


def clauses_or(*parts):
    """The clauses of either formula, each kept once and none that holds another (it adds nothing)."""
    found = sorted({tuple(sorted(set(c))) for part in parts for c in part}, key=len)
    out = []
    for c in found:
        s = set(c)
        if not any(s.issuperset(o) for o in out):
            out.append(c)
    return tuple(out)


def clauses_and(*parts):
    """The clauses of both formulas (every pair of clauses joined)."""
    out = TRUE
    for part in parts:
        if not part:
            return FALSE
        out = clauses_or([a + b for a in out for b in part])
    return out


# A sentence as the pick reads it: [text, shown (None: the text), too short, too long, source, co-words, set-phrase
# rows, its number in its file, the hash of its text (what two sentences are told apart by), its length]. A row's
# first sentence in each file is kept without its text (`Firsts`: text and shown None) — the plan holds every file's,
# most of a large library's sentences — and only the few a pick shows are read (the caller's token store).
TEXT, SHOWN, SHORT, LONG, SRC, COWORDS, CROWD, NUMBER, HASH, CHARS = range(10)
_FIRSTS_INTS = ("src", "number", "chars", "cow_at", "cow", "crowd_at", "crowd")


def pack_firsts(rows):
    """The per-file first sentences as the plan file keeps them: one dict of base64 columns (fast to read whole: the
    plan's largest table). `rows`: [(source, number, too short, too long, co-words, set-phrase rows, hash, length)]."""
    cols = {name: array("i") for name in _FIRSTS_INTS}
    flags, hashes = array("b"), array("I")
    cols["cow_at"].append(0)
    cols["crowd_at"].append(0)
    for src, number, short, long, cowords, crowd, text_hash, chars in rows:
        cols["src"].append(src)
        cols["number"].append(number)
        cols["chars"].append(chars)
        flags.append(short | (long << 1))
        hashes.append(text_hash)
        cols["cow"].extend(cowords)
        cols["cow_at"].append(len(cols["cow"]))
        cols["crowd"].extend(crowd)
        cols["crowd_at"].append(len(cols["crowd"]))
    out = {"n": len(rows), "order": sys.byteorder}
    for name, arr in list(cols.items()) + [("flags", flags), ("hash", hashes)]:
        out[name] = base64.b64encode(arr.tobytes()).decode("ascii")
    return out


class Firsts:
    """The per-file first sentences read back (`pack_firsts`): `firsts[j]` a sentence row with no text. ValueError
    when the columns don't fit together."""

    def __init__(self, packed, deep=True):
        if not isinstance(packed, dict) or packed.get("order") != sys.byteorder or type(packed.get("n")) is not int:
            raise ValueError("the first sentences are damaged")
        n = packed["n"]
        cols = {}
        for name, code in [(name, "i") for name in _FIRSTS_INTS] + [("flags", "b"), ("hash", "I")]:
            arr = array(code)
            try:
                arr.frombytes(base64.b64decode(packed[name], validate=True))
            except (KeyError, TypeError, ValueError):
                raise ValueError("the first sentences are damaged") from None
            cols[name] = arr
        for name in ("src", "number", "chars", "flags", "hash"):
            if len(cols[name]) != n:
                raise ValueError("the first sentences are damaged")
        for at, flat in (("cow_at", "cow"), ("crowd_at", "crowd")):
            offsets = cols[at]
            if len(offsets) != n + 1 or (n and (offsets[0] != 0 or offsets[-1] != len(cols[flat]))) or (deep and any(
                    a > b for a, b in zip(offsets, offsets[1:]))):
                raise ValueError("the first sentences are damaged")
        self.n, self.cols = n, cols

    def __len__(self):
        return self.n

    def __getitem__(self, j):
        c = self.cols
        flags = c["flags"][j]
        return (None, None, flags & 1, (flags >> 1) & 1, c["src"][j], tuple(c["cow"][c["cow_at"][j]:c["cow_at"][j + 1]]),
                tuple(c["crowd"][c["crowd_at"][j]:c["crowd_at"][j + 1]]), c["number"][j], c["hash"][j], c["chars"][j])


class SentenceView:
    """The pick's sentences: a table of them with their text, then (ids from `len(table)` on) the `Firsts`."""

    def __init__(self, table, firsts=None):
        self.table, self.firsts, self.n = table, firsts, len(table)
        self._cache = {}

    def __len__(self):
        return self.n + (len(self.firsts) if self.firsts is not None else 0)

    def __getitem__(self, s):
        if s < self.n:
            return self.table[s]
        found = self._cache.get(s)
        if found is None:
            found = self._cache[s] = self.firsts[s - self.n]
        return found


class ContextPicker:
    """The example sentences of each list row, down the list (one rule, the analyzer's and the plan engine's).

    `sentences`: rows (`TEXT` … `CHARS`, above), indexable — the text (stripped; None for one kept without it; its
    hash is what two sentences are told apart by), what Context shows (None: the text), the lengths (0 / 1), the caller's source id, the sentence's unknown
    co-words (ids into `cowords`) and the set phrases in it that are list rows (row ids). `cowords`: [(its own row or
    -1, its clauses)]. `place(src)`: (finish rank — 0 the last finished, `NOT_FINISHED` for counted content —, the
    file's place in the study order); `audio(src)`: 0 YouTube, 1 other audio, 2 text. `recency_files`: a co-word
    learned in the word's own file or up to this many files before it counts as recently learned (< 0: off).

    For each row, in list order: `pick(row, seq, first, pool, audio_pool)` -> the sentence ids chosen (None: *Only
    i+1* has no sentence for it, so it is skipped and never learned), then `learn(row, is_phrase, seq)` once it is."""

    def __init__(self, sentences, cowords, max_contexts, place, audio, only_i_plus_one=False, ensure_audio=False,
                 recency_files=1):
        self.sentences, self.max, self.place, self.audio = sentences, max_contexts, place, audio
        self.only, self.ensure, self.recency = bool(only_i_plus_one), bool(ensure_audio), recency_files
        self._own = [own for own, _clauses in cowords]
        self._known = [False] * len(cowords)
        self._left = []
        self._by_row = {}
        for c, (_own, clauses) in enumerate(cowords):
            self._left.append([len(clause) for clause in clauses])
            for i, clause in enumerate(clauses):
                for r in clause:
                    self._by_row.setdefault(r, []).append((c, i))
        self._learned = {}              # row -> the file it is learned in (its first file's place)
        self._phrases = set()           # the phrase rows learned

    def learn(self, row, is_phrase, seq):
        """`row` is learned (its sentences are chosen): a phrase row only takes the sentences it is in out of the
        crowd; a word's row makes known every co-word one of whose clauses it completes."""
        if is_phrase:
            self._phrases.add(row)
            return
        self._learned[row] = seq
        left, known = self._left, self._known
        for c, i in self._by_row.get(row, ()):
            left[c][i] -= 1
            if not left[c][i]:
                known[c] = True

    def _weigh(self, row, seq, s):
        """(unknown co-words, the crowd of new set phrases, the co-words learned recently) of sentence `s` for `row`
        here; the unknowns stop at 1 under *Only i+1*."""
        sentence = self.sentences[s]
        cowords, crowd = sentence[COWORDS], sentence[CROWD]
        unknown = recent = 0
        own, known, learned, window = self._own, self._known, self._learned, self.recency
        for c in cowords:
            r = own[c]
            if r == row:
                continue                            # the word itself
            if not known[c]:
                unknown += 1
                if self.only:
                    break
            elif window >= 0 and r in learned and 0 <= seq - learned[r] <= window:
                recent += 1
        phrases = self._phrases
        n_crowd = sum(1 for r in set(crowd) if r != row and r not in phrases) if crowd else 0
        return unknown, n_crowd, recent

    def _key(self, s, unknown, crowd, recent, i):
        sentence = self.sentences[s]
        short, long, src = sentence[2], sentence[3], sentence[4]
        finished, seq = self.place(src)
        return (unknown, crowd, self.audio(src) if self.ensure else 0, short, long, finished, -recent, seq, i)

    def pick(self, row, seq, first, pool, audio_pool=()):
        """The sentences for `row` (first met in the file at `seq`), best first. `first`: its first sentence (Context
        1 outside *Only i+1*, whatever it holds; under it, one more candidate), or None; `pool`: its shortlist then its
        Finished sentences; `audio_pool`: its audio shortlist (with *Ensure an audio example*). Among sentences of equal
        ease (unknowns, a new set phrase, the audio rule, the lengths): Finished content first, the newest finished
        first, then the sentences that reinforce what was just learned, then the files nearest after the word's first
        meeting, then the shortlist's own order."""
        sentences = self.sentences
        seen, candidates = set(), []
        pinned = None
        if first is not None and sentences[first][TEXT] == "":
            first = None
        if first is not None and not self.only:
            pinned = first
            seen.add(sentences[first][HASH])
        elif first is not None and first not in pool:
            pool = [first] + list(pool)              # (`Only i+1`: a candidate like the rest, at the front)
        for i, s in enumerate(pool):
            sentence = sentences[s]
            if sentence[TEXT] == "" or sentence[HASH] in seen:
                continue
            seen.add(sentence[HASH])
            unknown, crowd, recent = self._weigh(row, seq, s)
            if self.only and unknown:
                continue
            candidates.append((self._key(s, unknown, crowd, recent, i), s))
        if self.only and not candidates:
            return None
        candidates.sort()
        chosen = [] if pinned is None else [pinned]
        for _key, s in candidates:
            if len(chosen) >= self.max:
                break
            chosen.append(s)
        if self.ensure and self.max >= 2 and chosen and not any(self.audio(sentences[s][4]) < 2 for s in chosen):
            # One example the learner can hear: the best audio candidate (re-weighed here, against the words learned
            # above) takes the last slot — the free one, else the last one filled — and never under Only i+1 unless
            # it is i+1 itself.
            texts = {sentences[s][HASH] for s in chosen}
            best = None
            for i, s in enumerate(audio_pool):
                sentence = sentences[s]
                short, long, src = sentence[SHORT], sentence[LONG], sentence[SRC]
                if sentence[TEXT] == "" or sentence[HASH] in texts:
                    continue
                unknown = self._weigh(row, seq, s)[0]
                if self.only and unknown:
                    continue
                key = (unknown, self.audio(src), short, long) + self.place(src) + (i,)
                if best is None or key < best[0]:
                    best = (key, s)
            if best is not None:
                if len(chosen) < self.max:
                    chosen.append(best[1])
                else:
                    chosen[-1] = best[1]
        return chosen

    def shown(self, s):
        """What Context shows for sentence `s` (None for one kept without its text: the caller reads it)."""
        text, display = self.sentences[s][TEXT], self.sentences[s][SHOWN]
        return text if display is None else display


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
