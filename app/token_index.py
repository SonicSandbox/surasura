"""Persistent, incremental per-file token store (SQLite).

Why this exists
---------------
Tokenizing the whole library is by far the most expensive part of a run. The word-selection
preview (density bands / coverage %) needs the library's frequency distribution *instantly*, and
Generate wants to reuse unchanged files' tokens. So we keep a persistent per-file token store and
reconcile only the DELTA — added / changed / removed files — against filesystem truth.

Why SQLite (not JSON)
---------------------
- **O(delta) updates.** A JSON index must load + rewrite the WHOLE file on every change (to
  subtract a file's counts). SQLite updates only the changed rows, so a one-file change never
  rewrites hundreds of MB.
- **Concurrency for free.** WAL + `BEGIN IMMEDIATE` gives atomic commits, lock-free concurrent
  readers, and writer serialization (via `busy_timeout`) — replacing a hand-rolled lockfile +
  atomic-rename. It's embedded/local (no server, no network) and rolls back cleanly if a process
  is killed mid-write.

Design invariants (do not break)
--------------------------------
1. **Store RAW counts** — every target token, BEFORE the known/ignore filter. Known/ignore changes
   re-filter cheaply at READ time (`unknown_frequencies`), never re-tokenizing.
2. **Trust the filesystem, not UI events.** Reconcile compares (mtime, size)/existence, so a file
   edited/added/removed outside the content importer is still caught.
3. **Maintain the `aggregate` incrementally** — never re-sum the whole library on read.
4. **Disposable/regenerable** — a schema-version mismatch or corruption simply rebuilds.
"""

import os
import json
import zlib
import sqlite3
from collections import Counter

# Bump when the on-disk SHAPE changes — or when the tokenizer would now produce DIFFERENT sentences
# for the same file, since the cached blobs would otherwise keep serving the old split. A mismatched
# DB is dropped + rebuilt.
# v2 added the per-file token SEQUENCE blob (so Generate reuses unchanged files' tokens).
# v3 fixed subtitle sentence splitting (halfwidth ｡, terminators glued to adjacent symbols, and
#    continuation arrows joining cues), so every cached tokenization predates the fix.
SCHEMA_VERSION = 3


# --------------------------------------------------------------------------- #
# Keys, paths, signatures
# --------------------------------------------------------------------------- #
def make_key(lemma, reading):
    """Stable string key for a (lemma, reading) pair — mirrors word_stats.json ('lemma|reading')."""
    return f"{lemma}|{reading}"


def split_key(key):
    """Inverse of make_key. Splits on the first '|' (lemmas never contain it)."""
    lemma, _sep, reading = key.partition("|")
    return lemma, reading


def _norm(path):
    """Normalize a path into a stable primary key (case-insensitive on Windows)."""
    return os.path.normcase(os.path.abspath(path))


def file_signature(path):
    """(mtime, size) — the cheap fingerprint we reconcile against. Raises OSError if missing."""
    st = os.stat(path)
    return st.st_mtime, st.st_size


def store_path_for(language):
    """Where the token store DB for a language lives.

    Local disk (WAL is unhappy on cloud-synced folders), survives app updates, and separate from
    the regenerable results/. `SURASURA_TEST_ROOT` overrides it so tests never touch real %APPDATA%.
    """
    root = os.environ.get("SURASURA_TEST_ROOT")
    if root:
        base = os.path.join(root, "index")
    else:
        from app.path_utils import get_persistent_user_data_path
        base = get_persistent_user_data_path()
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"token_store_{language}.db")


# --------------------------------------------------------------------------- #
# Per-file counts blob (compact; used to subtract a file's contribution on change/remove)
# --------------------------------------------------------------------------- #
def _encode_counts(counts):
    return zlib.compress(json.dumps(counts, ensure_ascii=False).encode("utf-8"))


def _decode_counts(blob):
    if not blob:
        return {}
    try:
        return json.loads(zlib.decompress(blob).decode("utf-8"))
    except Exception:
        return {}


def _encode_tokens(sentences):
    """Per-file tokenized sentences [(s_text, [[lemma,reading,surface],...]),...] -> compact blob.
    Reused by Generate so unchanged files never re-tokenize."""
    return zlib.compress(json.dumps(sentences, ensure_ascii=False).encode("utf-8"))


def _decode_tokens(blob):
    if not blob:
        return []
    try:
        return json.loads(zlib.decompress(blob).decode("utf-8"))
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE files (
    path   TEXT PRIMARY KEY,   -- normcase abspath
    mtime  REAL, size INTEGER, -- reconcile signature (filesystem truth)
    total  INTEGER,            -- token count for this file
    counts BLOB,               -- zlib(json {"lemma|reading": n}) for O(delta) subtract
    tokens BLOB                -- zlib(json sentences) — cached tokenization for Generate reuse
);
CREATE TABLE aggregate (       -- maintained rollup; the preview reads this
    lemma TEXT, reading TEXT, count INTEGER,
    PRIMARY KEY (lemma, reading)
);
CREATE INDEX idx_aggregate_count ON aggregate(count DESC);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _ensure_schema(conn):
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver == SCHEMA_VERSION:
        try:  # verify tables actually exist (guard a half-built DB)
            conn.execute("SELECT 1 FROM files LIMIT 1")
            conn.execute("SELECT 1 FROM aggregate LIMIT 1")
            return
        except sqlite3.DatabaseError:
            pass  # fall through to rebuild
    conn.executescript(
        "DROP TABLE IF EXISTS files; DROP TABLE IF EXISTS aggregate; DROP TABLE IF EXISTS meta;"
        + _SCHEMA
    )
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def _delete_db(path):
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


def open_store(language, path=None):
    """Open (or create/rebuild) the SQLite token store for a language. WAL, busy-timeout, schema
    ensured, corruption self-heals by rebuilding."""
    db_path = path or store_path_for(language)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def _connect():
        c = sqlite3.connect(db_path, timeout=5.0)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            c.execute("PRAGMA synchronous=NORMAL")
            _ensure_schema(c)
        except Exception:
            c.close()   # never leak a handle to a corrupt file (Windows can't delete an open file)
            raise
        return c

    try:
        return Store(_connect())
    except sqlite3.DatabaseError:
        # Corrupt DB -> delete + rebuild (it's a regenerable cache).
        _delete_db(db_path)
        return Store(_connect())


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
class Store:
    def __init__(self, conn):
        self.conn = conn

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- signatures / totals ------------------------------------------------- #
    def total_tokens(self):
        r = self.conn.execute("SELECT COALESCE(SUM(total), 0) FROM files").fetchone()
        return int(r[0]) if r else 0

    def file_count(self):
        return int(self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def file_tokens(self, path):
        """Cached tokenized sentences for a file: [(s_text, [[lemma,reading,surface],...]),...].
        Empty list if the file isn't indexed. Lets Generate reuse tokens for unchanged files."""
        row = self.conn.execute("SELECT tokens FROM files WHERE path=?", (_norm(path),)).fetchone()
        return _decode_tokens(row[0]) if row else []

    # -- meta key/value (run-signature, known-words cache) ------------------- #
    def get_meta(self, key, default=None):
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_meta(self, key, value):
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=?",
            (key, value, value))
        self.conn.commit()

    # -- known-words cache (skip re-tokenizing known terms every run) -------- #
    def get_cached_known(self, signature):
        """Return (known_tuples, known_lemmas) if the cache matches `signature`, else None.
        `signature` encodes KnownWord.json's (exists, mtime, size) — so any edit/delete/add misses."""
        if not signature or self.get_meta("known_sig") != signature:
            return None
        try:
            tuples = {(l, r) for l, r in json.loads(self.get_meta("known_tuples") or "[]")}
            lemmas = set(json.loads(self.get_meta("known_lemmas") or "[]"))
            return tuples, lemmas
        except Exception:
            return None

    def set_cached_known(self, signature, known_tuples, known_lemmas):
        cur = self.conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            for k, v in (("known_sig", signature),
                         ("known_tuples", json.dumps([list(t) for t in known_tuples], ensure_ascii=False)),
                         ("known_lemmas", json.dumps(list(known_lemmas), ensure_ascii=False))):
                cur.execute("INSERT INTO meta(key, value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=?", (k, v, v))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def needs_reconcile(self, files):
        """Cheap disk-vs-store delta check (stat only, NO tokenizer) — for a GUI pre-gate."""
        rows = {r[0]: (r[1], r[2]) for r in self.conn.execute("SELECT path, mtime, size FROM files")}
        current = {_norm(p): p for p in files}
        if set(rows) != set(current):
            return True
        for key, realpath in current.items():
            try:
                if rows[key] != file_signature(realpath):
                    return True
            except OSError:
                return True
        return False

    # -- reconcile (delta, one transaction) ---------------------------------- #
    def _apply(self, cur, counts, sign):
        for key, n in counts.items():
            lemma, reading = split_key(key)
            d = sign * n
            cur.execute(
                "INSERT INTO aggregate(lemma, reading, count) VALUES(?,?,?) "
                "ON CONFLICT(lemma, reading) DO UPDATE SET count = count + ?",
                (lemma, reading, d, d),
            )

    def reconcile(self, files, tokenize_file, build_signature=None):
        """Bring the store in sync with the on-disk `files`, re-tokenizing ONLY changed/new files.

        tokenize_file(path) -> {"sentences": [...], "counts": Counter}. Sequences are cached (for
        Generate reuse); counts maintain the aggregate. Runs in a single BEGIN IMMEDIATE
        transaction (atomic; serialized against other writers).

        `build_signature` (optional) fingerprints the TOKENIZER IDENTITY (e.g. Chinese `reinforce`
        segmentation). Reconcile keys "unchanged" on (mtime, size) only, so a tokenizer-config
        change wouldn't otherwise refresh cached tokens. If the stored signature differs, every
        cached tokenization is stale -> drop it all and rebuild. (Callers MUST pass a CONSISTENT
        signature — the analyzer and the background indexer both derive it from the same setting —
        or the store would thrash, each rebuilding what the other just wrote.)
        """
        cur = self.conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            if build_signature is not None:
                _row = cur.execute("SELECT value FROM meta WHERE key='build_sig'").fetchone()
                if _row is not None and _row[0] != build_signature:
                    cur.execute("DELETE FROM files")      # tokenizer identity changed -> full rebuild
                    cur.execute("DELETE FROM aggregate")
            existing = {
                r[0]: {"mtime": r[1], "size": r[2], "total": r[3], "counts": r[4]}
                for r in cur.execute("SELECT path, mtime, size, total, counts FROM files")
            }
            current = {_norm(p): p for p in files}

            # Removals — subtract vanished files.
            for key in list(existing):
                if key not in current:
                    self._apply(cur, _decode_counts(existing[key]["counts"]), -1)
                    cur.execute("DELETE FROM files WHERE path=?", (key,))

            # Adds / changes — reuse unchanged (fast path), tokenize only the delta.
            for key, realpath in current.items():
                try:
                    mtime, size = file_signature(realpath)
                except OSError:
                    continue  # vanished between listing and stat — a later reconcile handles it
                row = existing.get(key)
                if row is not None and row["mtime"] == mtime and row["size"] == size:
                    continue  # unchanged — no tokenization
                result = tokenize_file(realpath)   # {"sentences": [...], "counts": Counter}
                counts = {k: n for k, n in result["counts"].items() if n > 0}
                total = sum(counts.values())
                if row is not None:  # changed: subtract the stale contribution first
                    self._apply(cur, _decode_counts(row["counts"]), -1)
                self._apply(cur, counts, +1)
                cur.execute(
                    "INSERT OR REPLACE INTO files(path, mtime, size, total, counts, tokens) "
                    "VALUES(?,?,?,?,?,?)",
                    (key, mtime, size, total, _encode_counts(counts),
                     _encode_tokens(result["sentences"])),
                )

            cur.execute("DELETE FROM aggregate WHERE count <= 0")  # prune emptied words
            if build_signature is not None:
                cur.execute("INSERT INTO meta(key, value) VALUES('build_sig', ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=?", (build_signature, build_signature))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self

    # -- read layer (known/ignore filter WITHOUT re-tokenizing) -------------- #
    def unknown_frequencies(self, known_tuples=None, known_lemmas=None, ignore_set=None,
                            skip_singles=False):
        """Project the aggregate into the *learnable unknown* distribution. Same shape as before:
        {total_tokens, known_tokens, unknown:[(key,count)...], all_counts:[asc]}."""
        known_tuples = known_tuples or set()
        known_lemmas = known_lemmas or set()
        ignore_set = ignore_set or set()

        unknown, known_tokens, all_counts = [], 0, []
        for lemma, reading, n in self.conn.execute("SELECT lemma, reading, count FROM aggregate"):
            all_counts.append(n)
            if lemma in ignore_set or (lemma, reading) in known_tuples or lemma in known_lemmas:
                known_tokens += n
                continue
            if skip_singles and len(lemma) == 1:
                # Single-char tokens are baseline noise for ja learning; still count toward total.
                known_tokens += n
                continue
            unknown.append((make_key(lemma, reading), n))

        unknown.sort(key=lambda kv: (-kv[1], kv[0]))
        all_counts.sort()
        return {"total_tokens": self.total_tokens(), "known_tokens": known_tokens,
                "unknown": unknown, "all_counts": all_counts}


def known_signature(known_path):
    """A tokenizer-free fingerprint of the known-words file: (exists, mtime, size). A deleted or
    edited or newly-added KnownWord.json all yield a DIFFERENT signature, so the cache invalidates."""
    try:
        st = os.stat(known_path)
        return json.dumps([True, st.st_mtime, st.st_size])
    except OSError:
        return json.dumps([False, None, None])   # missing / deleted


# --------------------------------------------------------------------------- #
# Tokenizer factory (default; injectable for tests)
# --------------------------------------------------------------------------- #
def build_signature(language, reinforce=False):
    """Fingerprint of the tokenizer identity that produced the cache, passed to reconcile so a
    config change invalidates stale tokens. Only Chinese `reinforce` segmentation varies at runtime
    (ja tokenization is fixed; language is already isolated per DB; a tokenizer-LIBRARY change is
    handled by bumping SCHEMA_VERSION, which rebuilds). Normalized so ja ignores a stray reinforce."""
    eff_reinforce = bool(reinforce) and language == "zh"
    return f"{language}|reinforce={eff_reinforce}"


def make_tokenizer(language, reinforce=False):
    """Build the default `tokenize_file(path) -> {"sentences", "counts"}`, reusing the analyzer's
    real tokenizer + text extraction so the store matches what a run would produce.

    - `sentences`: the FULL tokenize_sentences output [(s_text, [(lemma,reading,surface),...]),...]
      (every token, so Generate's aggregation can reuse it verbatim).
    - `counts`: Counter('lemma|reading' -> n) over tokens whose lemma OR surface has target-language
      chars (mirrors the analyzer's file_total_words accounting) — the aggregate the preview reads.
    """
    from app import analyzer

    # ja lemmas carry a gloss suffix the analyzer strips; match it so store lemmas == run lemmas.
    analyzer.SANITIZE_JA = (language == "ja")
    tok = analyzer.ChineseTokenizer(reinforce_segmentation=reinforce) if language == "zh" \
        else analyzer.JapaneseTokenizer()
    has_lang, extract = analyzer.has_target_language, analyzer.extract_text

    def tokenize_file(path):
        sentences = list(tok.tokenize_sentences(extract(path, language)))
        counts = Counter()
        for _s_text, s_tokens in sentences:
            for lemma, reading, surface in s_tokens:
                if has_lang(lemma, language) or has_lang(surface, language):
                    counts[make_key(lemma, reading)] += 1
        return {"sentences": sentences, "counts": counts}

    return tokenize_file


def reconcile_language(language, files, path=None, reinforce=False):
    """Convenience: open the store and reconcile it with the default tokenizer."""
    store = open_store(language, path)
    try:
        store.reconcile(files, make_tokenizer(language, reinforce),
                        build_signature=build_signature(language, reinforce))
    finally:
        store.close()
    return store


# --------------------------------------------------------------------------- #
# Small math helpers (unchanged)
# --------------------------------------------------------------------------- #
def to_ppm(count, total_tokens):
    """Occurrences -> parts-per-million density (the scale-invariant 'how common' measure)."""
    return (count / total_tokens * 1_000_000) if total_tokens else 0.0


def coverage_percent(known_tokens, total_tokens):
    """Share of the library already understood (0-100)."""
    return (known_tokens / total_tokens * 100) if total_tokens else 0.0
