"""Persistent, incremental per-file token index.

Why this exists
---------------
Tokenizing the whole library is by far the most expensive part of a run (~seconds on a large
library). The word-selection preview (density bands / coverage %) needs the library's frequency
distribution *instantly* and *always fresh*, without paying a full re-run. So we persist a
per-file token cache and reconcile only the DELTA — added / changed / removed files — against
filesystem truth, never re-tokenizing an unchanged file.

Design invariants (do not break these)
--------------------------------------
1. **Store RAW counts** — every target-language token, BEFORE the known/ignore filter. Known-word
   and ignore-list changes then re-filter cheaply at READ time (`unknown_frequencies`) with NO
   re-tokenization. This is why importing Anki words never triggers a re-index.
2. **Trust the filesystem, not UI events.** Reconciliation compares each file's (mtime, size)
   against the cache, so a file edited/added/removed *outside* the content importer is still
   caught. Importer hooks are only an optional pre-warm; correctness lives here.
3. **Maintain the aggregate incrementally** (add/subtract per changed file) — never re-sum the
   whole library on open — so opening the selector stays O(delta), which is what scales to huge
   libraries.

The index is disposable/regenerable: a version bump or an unreadable cache simply rebuilds it.
"""

import os
import json
from collections import Counter

from app.path_utils import get_user_file

# Bump when the on-disk shape changes; an older/newer cache is discarded and rebuilt.
INDEX_VERSION = 1


# --------------------------------------------------------------------------- #
# Keys & paths
# --------------------------------------------------------------------------- #
def make_key(lemma, reading):
    """Stable string key for a (lemma, reading) pair — mirrors word_stats.json ('lemma|reading')."""
    return f"{lemma}|{reading}"


def split_key(key):
    """Inverse of make_key. Splits on the first '|' (lemmas never contain it)."""
    lemma, _sep, reading = key.partition("|")
    return lemma, reading


def index_path_for(language):
    """Where the index for a language lives (alongside the other generated results)."""
    return get_user_file(os.path.join("results", f"token_index_{language}.json"))


def _norm(path):
    """Normalize a path into a stable dict key (case-insensitive on Windows)."""
    return os.path.normcase(os.path.abspath(path))


def file_signature(path):
    """(mtime, size) — the cheap fingerprint we reconcile against. Raises OSError if missing."""
    st = os.stat(path)
    return st.st_mtime, st.st_size


# --------------------------------------------------------------------------- #
# Index structure
# --------------------------------------------------------------------------- #
def empty_index():
    return {"version": INDEX_VERSION, "files": {}, "aggregate": {}, "total_tokens": 0}


def _apply(aggregate, counts, sign):
    """Add (sign=+1) or subtract (sign=-1) a file's counts into the running aggregate,
    pruning entries that fall to zero so the aggregate never accumulates dead keys."""
    for k, n in counts.items():
        new = aggregate.get(k, 0) + sign * n
        if new > 0:
            aggregate[k] = new
        else:
            aggregate.pop(k, None)


def reconcile(files, tokenize_file, index=None):
    """Bring `index` in sync with the on-disk `files` (a list of paths), re-tokenizing ONLY the
    files whose (mtime, size) changed, dropping files that disappeared, and adding new ones.

    tokenize_file(path) -> Counter mapping 'lemma|reading' -> raw count (all target tokens).
    Returns the (mutated) index. Pure w.r.t. disk — caller decides whether to save.
    """
    if index is None:
        index = empty_index()
    files_map = index["files"]
    agg = index["aggregate"]

    current = {_norm(p): p for p in files}

    # 1. Removals — a cached file that is no longer present: subtract its contribution.
    for key in list(files_map.keys()):
        if key not in current:
            entry = files_map.pop(key)
            _apply(agg, entry["counts"], -1)
            index["total_tokens"] -= entry.get("total", 0)

    # 2. Adds / changes — reuse unchanged files (the fast path), re-tokenize only the delta.
    for key, path in current.items():
        try:
            mtime, size = file_signature(path)
        except OSError:
            # File vanished between listing and stat — skip; a later reconcile will handle it.
            continue

        entry = files_map.get(key)
        if entry is not None and entry.get("mtime") == mtime and entry.get("size") == size:
            continue  # unchanged — no tokenization

        counts = Counter(tokenize_file(path))
        total = sum(counts.values())

        if entry is not None:  # changed file: remove the stale contribution first
            _apply(agg, entry["counts"], -1)
            index["total_tokens"] -= entry.get("total", 0)

        _apply(agg, counts, +1)
        index["total_tokens"] += total
        files_map[key] = {"mtime": mtime, "size": size, "total": total, "counts": dict(counts)}

    return index


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def build_index(per_file_counts):
    """Build a fresh index from already-tokenized per-file counts — {abs_path: {key: count}},
    counts raw (target-filtered). Signatures are read from disk. Lets a full analysis SEED the
    index for free (it already tokenized every file), so the preview needs no re-tokenization."""
    index = empty_index()
    for path, counts in per_file_counts.items():
        try:
            mtime, size = file_signature(path)
        except OSError:
            continue
        counts = {k: n for k, n in counts.items() if n > 0}
        total = sum(counts.values())
        index["files"][_norm(path)] = {"mtime": mtime, "size": size, "total": total, "counts": counts}
        _apply(index["aggregate"], counts, +1)
        index["total_tokens"] += total
    return index


def load_index(path):
    """Load an index from disk, or return a fresh empty one if missing/unreadable/outdated."""
    if not path or not os.path.exists(path):
        return empty_index()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("version") != INDEX_VERSION:
            return empty_index()
        # Minimal shape guard — a corrupt cache should rebuild, never crash a run.
        data.setdefault("files", {})
        data.setdefault("aggregate", {})
        data.setdefault("total_tokens", 0)
        return data
    except Exception:
        return empty_index()


def save_index(index, path):
    """Persist the index next to the other generated results. Never raises."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
    except Exception as e:
        print(f"Warning: could not save token index: {e}")


# --------------------------------------------------------------------------- #
# Tokenizer factory (default; injectable for tests)
# --------------------------------------------------------------------------- #
def make_tokenizer(language, reinforce=False):
    """Build the default `tokenize_file(path) -> Counter` for a language, reusing the analyzer's
    real tokenizer + text extraction so the index matches exactly what a run would count.

    Stores every token whose lemma OR surface contains target-language characters (mirrors the
    analyzer's `file_total_words` accounting), so `total_tokens` lines up with run coverage.
    """
    from app import analyzer

    # Japanese lemmas carry a gloss suffix; the analyzer strips it for ja. Match that so index
    # lemmas equal run lemmas (and so single-char detection below is on the clean form).
    analyzer.SANITIZE_JA = (language == "ja")

    if language == "zh":
        tok = analyzer.ChineseTokenizer(reinforce_segmentation=reinforce)
    else:
        tok = analyzer.JapaneseTokenizer()

    has_lang = analyzer.has_target_language
    extract = analyzer.extract_text

    def tokenize_file(path):
        text = extract(path, language)
        counts = Counter()
        for lemma, reading, surface in tok.tokenize(text):
            if has_lang(lemma, language) or has_lang(surface, language):
                counts[make_key(lemma, reading)] += 1
        return counts

    return tokenize_file


def reconcile_language(language, files, index=None, path=None, reinforce=False, save=True):
    """Convenience wrapper: reconcile a language's index with the default tokenizer, then save."""
    idx_path = path or index_path_for(language)
    if index is None:
        index = load_index(idx_path)
    reconcile(files, make_tokenizer(language, reinforce), index)
    if save:
        save_index(index, idx_path)
    return index


# --------------------------------------------------------------------------- #
# Read layer — applies the known/ignore filter WITHOUT re-tokenizing
# --------------------------------------------------------------------------- #
def unknown_frequencies(index, known_tuples=None, known_lemmas=None, ignore_set=None,
                        skip_singles=False):
    """Project the raw aggregate into the *learnable unknown* distribution, applying the current
    known / ignore / single-char filter at read time. This is the whole point of storing raw
    counts: a known-word change re-runs only this cheap pass, never the tokenizer.

    Returns dict:
      - total_tokens : library size (all target tokens, known + unknown)
      - known_tokens : occurrences filtered out as known/ignored/single (the coverage baseline)
      - unknown      : list of (key, count) for learnable words, sorted by count desc then key
    """
    known_tuples = known_tuples or set()
    known_lemmas = known_lemmas or set()
    ignore_set = ignore_set or set()

    agg = index.get("aggregate", {})
    total = index.get("total_tokens", 0)
    unknown = []
    known_tokens = 0

    for key, n in agg.items():
        lemma, reading = split_key(key)
        if lemma in ignore_set or (lemma, reading) in known_tuples or lemma in known_lemmas:
            known_tokens += n
            continue
        if skip_singles and len(lemma) == 1:
            # Single-char tokens are baseline noise for ja learning; they still count toward the
            # library total (coverage), matching the analyzer's treatment.
            known_tokens += n
            continue
        unknown.append((key, n))

    unknown.sort(key=lambda kv: (-kv[1], kv[0]))
    # all_counts (ascending, EVERY word known+unknown) powers the standard vocabulary-coverage
    # curve in the preview: "words this common cover X% of your library" — baseline-independent,
    # so it spans ~50%..~99% instead of being pinned near the learner's already-high baseline.
    all_counts = sorted(agg.values())
    return {"total_tokens": total, "known_tokens": known_tokens,
            "unknown": unknown, "all_counts": all_counts}


def to_ppm(count, total_tokens):
    """Occurrences -> parts-per-million density (the scale-invariant 'how common' measure)."""
    return (count / total_tokens * 1_000_000) if total_tokens else 0.0


def coverage_percent(known_tokens, total_tokens):
    """Share of the library already understood (0-100)."""
    return (known_tokens / total_tokens * 100) if total_tokens else 0.0
