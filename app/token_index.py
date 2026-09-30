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
from operator import itemgetter

# Bump when the on-disk SHAPE changes — or when the tokenizer would now produce DIFFERENT sentences
# for the same file, since the cached blobs would otherwise keep serving the old split. A mismatched
# DB is dropped + rebuilt.
# v2 added the per-file token SEQUENCE blob (so Generate reuses unchanged files' tokens).
# v3 fixed subtitle sentence splitting (halfwidth ｡, terminators glued to adjacent symbols, and
#    continuation arrows joining cues), so every cached tokenization predates the fix.
# v4 widened the token tuple to (lemma, reading, surface, orth). A v3 blob unpacks three values
#    into a four-value loop and raises, so the old cache cannot be read — it has to be rebuilt.
# v5 Japanese readings are the lemma's (UniDic lForm), no longer the conjugated surface's, so every
#    cached blob — and the aggregate built from them — carries the old, per-conjugation readings.
# v6 prefixes and suffixes are joined to their word, so every cached blob holds the old pieces
#    (幹線 for 新幹線, 可能 + 性 for 可能性 — analyzer.join_affixes).
# v7 the join table's お / ご words are decided once per word (おやすみ joins as お休み does; お話し
#    splits as お話 does) and 複雑さ / 三大祭り stay in pieces — still 2.3, so users rebuild once; a v6 blob
#    holds the first table's words (Patterns_Quality_Spec §15.9).
# v8 the parsing fixes (2026-09-27) change what a file's text becomes — its encoding, its
#    markup and conventions, where sentences end, the tagger reading NFKC, numbers and symbols no words — so every
#    cached blob holds the old sentences and tokens.
# v9 names stay whole (app/names.py): a v8 blob holds a name the tagger cut in pieces, and the store now records each
#    file's name candidates in a column a v8 store lacks — still 2.4, so users rebuild once with v8.
# v10 the text a file becomes reads differently again: a word stretched with a wave dash or a long mark is read as the
#    word (すご～い), 𠮟 as 叱, and sentences end by the quotation and caption rules — a v9 blob holds the old tokens
#    and sentences; still 2.4, so users rebuild once.
# v11 words made of words are one word (上層部, 二十歳, 走り出す), a sound word + と is one (ドキッと), お守り and お帰り
#    are words of their own and laughter stays in pieces: a v10 blob holds compounds in pieces, ドキッ + と, a laugh
#    joined as a name and those お / ご words split — still 2.4, so users rebuild once with v8, v9 and v10.
# v12 each file's record also holds the words that are people's names there (app/names.py, for Settings' "Ignore
#    names"): a v11 store's records hold none, so the switch would hide no name from a file read before — still 2.4,
#    so users rebuild once with v8–v11.
SCHEMA_VERSION = 12


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
# zlib's level for the blobs: 4 compresses a full re-read's 200 MB of tokens in about 2.3 s where the default (6) took
# 5.4 s, for a store about 12% bigger. Every level reads back the same data (zlib), so a store written at the old
# level is read as it is: the cached tokens don't change, and neither does SCHEMA_VERSION.
_BLOB_LEVEL = 4


def _encode_counts(counts):
    return zlib.compress(json.dumps(counts, ensure_ascii=False).encode("utf-8"), _BLOB_LEVEL)


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
    return zlib.compress(json.dumps(sentences, ensure_ascii=False).encode("utf-8"), _BLOB_LEVEL)


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
# IF NOT EXISTS on every object, deliberately. Two processes can both read a stale `user_version`
# (the background indexer and a Generate run race routinely), both decide the schema is missing, and
# both execute this script; without the guard the loser dies on "table files already exists". The
# work is idempotent either way — the winner's tables are the ones everybody ends up using.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path   TEXT PRIMARY KEY,   -- normcase abspath
    mtime  REAL, size INTEGER, -- reconcile signature (filesystem truth)
    total  INTEGER,            -- token count for this file
    counts BLOB,               -- zlib(json {"lemma|reading": n}) for O(delta) subtract
    tokens BLOB,               -- zlib(json sentences) — cached tokenization for Generate reuse
    names  BLOB                -- zlib(json app.names.Record data) — the file's name candidates (Japanese)
);
CREATE TABLE IF NOT EXISTS aggregate (  -- maintained rollup; the preview reads this
    lemma TEXT, reading TEXT, count INTEGER,
    PRIMARY KEY (lemma, reading)
);
CREATE INDEX IF NOT EXISTS idx_aggregate_count ON aggregate(count DESC);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _ensure_schema(conn):
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver == SCHEMA_VERSION:
        try:  # verify tables actually exist (guard a half-built DB)
            conn.execute("SELECT names FROM files LIMIT 1")
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
        return Store(_connect(), language)
    except sqlite3.DatabaseError:
        # Corrupt DB -> delete + rebuild (it's a regenerable cache).
        _delete_db(db_path)
        return Store(_connect(), language)


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
class Store:
    def __init__(self, conn, language=None):
        self.conn = conn
        self.language = language
        self._names = None          # the library's name tables, read on the first cached file (Japanese)

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
        Empty list if the file isn't indexed. Lets Generate reuse tokens for unchanged files.

        Japanese: with the library's name tables applied (app/names.py) — the cache holds each file as it reads
        alone, plus where its name candidates sit, so a new table needs no re-tokenizing."""
        row = self.conn.execute("SELECT tokens, names FROM files WHERE path=?", (_norm(path),)).fetchone()
        if not row:
            return []
        sentences = _decode_tokens(row[0])
        switches = _library_switches(self.language)
        if row[1] and any(switches):
            if self._names is None:
                self._names = self.names_tables() or {}
            if self._names:
                from app import names
                spans = _decode_counts(row[1]).get("s", [])
                if spans:
                    names.apply_spans(sentences, spans, self._names, *switches)
        return sentences

    # -- the library's name tables (app/names.py) ---------------------------- #
    def names_tables(self):
        """The name tables the last index computed, or None (none yet, or not a Japanese store)."""
        try:
            return json.loads(self.get_meta("names_tables") or "null")
        except Exception:
            return None

    def _update_names_tables(self, cur):
        """Compute the library's name tables from every file's recorded candidates (and the last tables, for the
        flip guard) and store them, with the library's names (`names.name_words`, for Ignore names) — after a
        reconcile changed something. Japanese only."""
        from app import analyzer, names
        row = cur.execute("SELECT value FROM meta WHERE key='names_tables'").fetchone()
        try:
            previous = json.loads(row[0]) if row else None
        except Exception:
            previous = None
        records = [_decode_counts(blob) for (blob,) in cur.execute("SELECT names FROM files WHERE names IS NOT NULL")]
        tables = names.compute_tables(records, previous, analyzer._sanitize_term)
        for key, value in (("names_tables", tables), ("names_adjust", self._names_adjust(cur, tables)),
                           ("names_words", names.name_words(records, tables, analyzer._sanitize_term))):
            value = json.dumps(value, ensure_ascii=False)
            cur.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=?",
                        (key, value, value))
        self._names = None

    def _names_adjust(self, cur, tables):
        """What the name tables change in the running totals, for each way the two switches can be set. The aggregate
        counts each file as it reads alone; the list counts its cached tokens with the tables applied (file_tokens) —
        so the Rarity slider's numbers, and the band automatic rarity picks from them, must add each joined name and
        take away its pieces, counted as the aggregate counts (a token with target-language characters).
        {"11" | "10" | "01" (recurring, kanji): {"counts": [[lemma, reading, delta], ...], "total": delta}}."""
        from app import analyzer, names
        if not tables:
            return {}
        has_lang = analyzer.has_target_language
        spellings = {kind: set(table) for kind, table in tables.items() if isinstance(table, dict)}
        deltas = {combo: [Counter(), 0] for combo in ("11", "10", "01")}
        for tokens_blob, names_blob in cur.execute(
                "SELECT tokens, names FROM files WHERE names IS NOT NULL").fetchall():
            spans = _decode_counts(names_blob).get("s", [])
            if not any(span[6] in spellings.get(span[5], ()) for span in spans):
                continue                                # no joined name here: nothing to decode
            sentences = _decode_tokens(tokens_blob)
            for combo, switches in (("11", (True, True)), ("10", (True, False)), ("01", (False, True))):
                delta = deltas[combo]
                for s, a, b, token in names.chosen(sentences, spans, tables, *switches):
                    joined = [(token, 1)] + [(piece, -1) for piece in sentences[s][1][a:b]]
                    for (lemma, reading, surface, *_rest), sign in joined:
                        if has_lang(lemma, self.language) or has_lang(surface, self.language):
                            delta[0][(lemma, reading)] += sign
                            delta[1] += sign
        return {combo: {"counts": [[l, r, n] for (l, r), n in counts.items() if n], "total": total}
                for combo, (counts, total) in deltas.items()}

    def _names_adjustment(self):
        """({(lemma, reading): delta}, total delta) that the name tables make with the switches set now — ({}, 0) when
        both are off, before the first index, or for Chinese."""
        combo = "".join("1" if on else "0" for on in _library_switches(self.language))
        if combo == "00":
            return {}, 0
        try:
            entry = json.loads(self.get_meta("names_adjust") or "{}").get(combo) or {}
            return {(l, r): n for l, r, n in entry.get("counts", ())}, int(entry.get("total", 0))
        except Exception:
            return {}, 0

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
    def _known_key(self, signature):
        """`signature` with what else decides how a Japanese known word reads: the names switches and the library's
        name tables (a known name is one word only with them), and the phrases switch (a known 予想通り is one word
        or two) — so any change reads the known words again. The switches are read fresh, as the build signature's
        are: the dashboard's check must see a change as the indexer it launches will."""
        if not signature or self.language != "ja":
            return signature
        try:
            from app import settings_manager
            logic = settings_manager.load_settings()["logic"]
        except Exception:
            return signature
        switches = [bool(logic.get(k, True)) for k in ("names_katakana", "names_recurring", "names_kanji")]
        stamp = (self.names_tables() or {}).get("stamp") if any(switches[1:]) else None
        if switches != [True, True, True] or stamp is not None:
            signature = f"{signature}|names={''.join('1' if s else '0' for s in switches)}:{stamp}"
        return signature if logic.get("phrases_and_titles", True) else f"{signature}|phrases_and_titles=off"

    def get_cached_known(self, signature):
        """Return (known_tuples, known_lemmas) if the cache matches `signature`, else None.
        `signature` encodes KnownWord.json's (exists, mtime, size) — so any edit/delete/add misses."""
        signature = self._known_key(signature)
        if not signature or self.get_meta("known_sig") != signature:
            return None
        try:
            tuples = {(l, r) for l, r in json.loads(self.get_meta("known_tuples") or "[]")}
            lemmas = set(json.loads(self.get_meta("known_lemmas") or "[]"))
            return tuples, lemmas
        except Exception:
            return None

    def set_cached_known(self, signature, known_tuples, known_lemmas):
        signature = self._known_key(signature)
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
    def _apply(self, cur, counts):
        cur.executemany(
            "INSERT INTO aggregate(lemma, reading, count) VALUES(?,?,?) "
            "ON CONFLICT(lemma, reading) DO UPDATE SET count = count + ?",
            [(*split_key(key), n, n) for key, n in counts.items()],
        )

    def reconcile(self, files, tokenize_file, build_signature=None):
        """Bring the store in sync with the on-disk `files`, re-tokenizing ONLY changed/new files.

        tokenize_file(path) -> {"sentences": [...], "counts": Counter} (Japanese: and "names", the file's
        name candidates). Sequences are cached (for Generate reuse); counts maintain the aggregate; after
        a change the library's name tables are computed again. Runs in a single BEGIN IMMEDIATE
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
        changed = False
        try:
            if build_signature is not None:
                _row = cur.execute("SELECT value FROM meta WHERE key='build_sig'").fetchone()
                if _row is not None and _row[0] != build_signature:
                    cur.execute("DELETE FROM files")      # tokenizer identity changed -> full rebuild
                    cur.execute("DELETE FROM aggregate")
                    changed = True
            existing = {
                r[0]: {"mtime": r[1], "size": r[2], "total": r[3], "counts": r[4]}
                for r in cur.execute("SELECT path, mtime, size, total, counts FROM files")
            }
            current = {_norm(p): p for p in files}
            # What the files change in the aggregate, summed over the whole pass and written once at the end: a full
            # rebuild wrote a million rows (every word of every file) where the library has some 50,000 words.
            # Keys stay in the order they are first met, so new words are added in the same order as file by file.
            delta = Counter()

            # Removals — subtract vanished files.
            for key in list(existing):
                if key not in current:
                    delta.subtract(_decode_counts(existing[key]["counts"]))
                    cur.execute("DELETE FROM files WHERE path=?", (key,))
                    changed = True

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
                    delta.subtract(_decode_counts(row["counts"]))
                delta.update(counts)
                names = result.get("names")
                cur.execute(
                    "INSERT OR REPLACE INTO files(path, mtime, size, total, counts, tokens, names) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (key, mtime, size, total, _encode_counts(counts),
                     _encode_tokens(result["sentences"]), _encode_counts(names) if names is not None else None),
                )
                changed = True

            self._apply(cur, delta)
            cur.execute("DELETE FROM aggregate WHERE count <= 0")  # prune emptied words
            if self.language == "ja" and (changed or cur.execute(
                    "SELECT 1 FROM meta WHERE key='names_tables'").fetchone() is None):
                self._update_names_tables(cur)
            if build_signature is not None:
                cur.execute("INSERT INTO meta(key, value) VALUES('build_sig', ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=?", (build_signature, build_signature))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self

    # -- read layer (known/ignore filter WITHOUT re-tokenizing) -------------- #
    def word_counts(self):
        """({(lemma, reading): uses}, total tokens) — the aggregate as a run counts the library. Japanese: with the
        name tables' joins, so these counts are the list's (a joined name counts once, its pieces no more there)."""
        rows = self.conn.execute("SELECT lemma, reading, count FROM aggregate").fetchall()
        counts = {(lemma, reading): n for lemma, reading, n in rows}
        adjust, total_adjust = self._names_adjustment()
        if adjust:
            for key, delta in adjust.items():
                counts[key] = counts.get(key, 0) + delta
            # What no longer counts goes — deleted in place, not the whole table copied (every slider refresh reads it).
            for key in [key for key, n in counts.items() if n <= 0]:
                del counts[key]
        return counts, self.total_tokens() + total_adjust

    def unknown_frequencies(self, known_tuples=None, known_lemmas=None, ignore_set=None,
                            skip_singles=False):
        """Project the aggregate into the *learnable unknown* distribution (`unknown_distribution`)."""
        counts, total = self.word_counts()
        return unknown_distribution(counts, total, known_tuples, known_lemmas, ignore_set, skip_singles,
                                    self.language)


def unknown_distribution(counts, total_tokens, known_tuples=None, known_lemmas=None, ignore_set=None,
                         skip_singles=False, language=None):
    """{total_tokens, known_tokens, unknown:[(key,count)...], all_counts:[asc]} from the library's per-word counts
    ({(lemma, reading): uses}) and the learner's lists — the Rarity slider's numbers, and the analyzer's own when it
    decides a band without the store.

    Japanese, with the tokenizer's compound table: also "compounds" — ({key: uses}, {key: its parts}) for every
    compound the learner neither knows nor ignores that the library holds, and every such compound inside one — so
    each band can count a compound too rare for it toward its free parts, as Generate's list does
    (analyzer.LearningView; word_selection.preview). A part is kept only when a use could reach the list through
    it: free, and an unknown word that can be listed (a single character can't) or an unknown compound."""
    known_tuples = known_tuples or set()
    known_lemmas = known_lemmas or set()
    ignore_set = ignore_set or set()
    table = {}
    if language == "ja":
        from app import analyzer
        table = analyzer.compound_parts()
    met = []                        # the unknown compounds the library holds

    unknown, known_tokens, all_counts = [], 0, []
    for key, n in counts.items():               # key = (lemma, reading), looked up as it is (this runs per word)
        all_counts.append(n)
        lemma = key[0]
        if lemma in ignore_set or key in known_tuples or lemma in known_lemmas:
            known_tokens += n
            continue
        if skip_singles and len(lemma) == 1:
            # Single-char tokens are baseline noise for ja learning; still count toward total.
            known_tokens += n
            continue
        unknown.append((f"{lemma}|{key[1]}", n))       # make_key
        if key in table:
            met.append(key)

    # Most uses first, ties by key: two stable sorts in C, not a key tuple built per word.
    unknown.sort(key=itemgetter(0))
    unknown.sort(key=itemgetter(1), reverse=True)
    all_counts.sort()
    freqs = {"total_tokens": total_tokens, "known_tokens": known_tokens, "unknown": unknown,
             "all_counts": all_counts}
    if table:
        uses, parts, bases = {}, {}, {}
        todo = met
        while todo:
            key = todo.pop()
            if key in parts:
                continue
            uses[key] = counts.get(key, 0)
            kept = []
            for lemma, reading, free in table[key]:
                part = (lemma, reading)
                if not free or lemma in ignore_set or part in known_tuples or lemma in known_lemmas:
                    continue
                if part in table:
                    todo.append(part)
                elif skip_singles and len(lemma) == 1:
                    continue
                kept.append((lemma, reading, True))
                bases[make_key(lemma, reading)] = counts.get(part, 0)
            parts[key] = tuple(kept)
        freqs["compounds"] = (uses, parts, bases)
    return freqs


def read_names_tables(language):
    """The library's name tables the language's store holds (app/names.py), read without writing anything — None
    when there is no store or no tables yet."""
    return _read_meta(language, "names_tables")


def _read_meta(language, key):
    """The JSON value `key` the language's store keeps in its meta table, read without writing anything — None when
    there is no store or no such value."""
    path = store_path_for(language)
    if not os.path.exists(path):
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else None
    except (sqlite3.Error, ValueError):
        return None


def ignored_names(language):
    """The library's names as ignored words — with Ignore names on (logic.ignore_names, off by default: a learner
    learns names too, unless they choose not to): the lemmas the last index found to be people's names
    (app/names.py `name_words`), read without writing anything. Part of `ignored_entries`, so every ignore set holds
    them — the list, the Rarity slider and automatic rarity, Junban, 例文, the sentence dictionary, the YouTube
    preview. [] with the switch off, for Chinese, and before the first index. The switch is read fresh, as the build
    signature's are: the dashboard's slider must see a change as the next Generate will."""
    if language != "ja":
        return []
    try:
        from app import settings_manager
        if not settings_manager.load_settings()["logic"].get("ignore_names", False):
            return []
    except Exception:
        return []
    words = _read_meta(language, "names_words")
    return [str(word) for word in words if word] if isinstance(words, list) else []


def _library_switches(language):
    """(recurring, kanji): which of the library's name tables apply — Japanese only, as the run's settings say."""
    if language != "ja":
        return (False, False)
    try:
        from app import analyzer
        return (bool(analyzer.LOGIC.get("names_recurring", True)), bool(analyzer.LOGIC.get("names_kanji", True)))
    except Exception:
        return (False, False)


def known_signature(known_path, script="asis"):
    """A tokenizer-free fingerprint of the known-words file: (exists, mtime, size). A deleted or
    edited or newly-added KnownWord.json all yield a DIFFERENT signature, so the cache invalidates.

    `script` is the EFFECTIVE Chinese script (zh_script.effective). The cached set is normalized in
    that script, so switching script must miss even though the file is untouched. Folded in only when
    converting, so as-is signatures stay byte-identical and nobody re-normalizes on upgrade (I2)."""
    try:
        st = os.stat(known_path)
        sig = [True, st.st_mtime, st.st_size]
    except OSError:
        sig = [False, None, None]   # missing / deleted
    if script in ("s", "t"):
        sig.append(f"script={script}")
    return json.dumps(sig)


# --------------------------------------------------------------------------- #
# The Rarity slider's distribution — one recipe for the dashboard and the analyzer
# --------------------------------------------------------------------------- #
def preview_frequencies(store, language, user_files_dir, script="asis"):
    """The unknown-word distribution behind the Rarity slider's numbers. ONE recipe, shared: the
    dashboard's preview reads it, and the analyzer's automatic rarity decides from it, so the band the
    dashboard shows is the band Generate uses. Neither side keeps its own copy.

    Tokenizer-free, so the dashboard can run it (fugashi never enters the GUI process): known words
    are the store's normalized known cache when it matches KnownWord.json, else the dictForm
    approximation; the three lists are their plain lines (the analyzer's own ignore set also reads a
    hiragana line through the tokenizer, する -> 為る, and still decides the list itself — this one
    only the band); single characters never count in Japanese. None for an empty store."""
    if not store.total_tokens():
        return None
    cached = store.get_cached_known(known_signature(os.path.join(user_files_dir, "KnownWord.json"), script))
    if cached is not None:
        known_tuples, known_lemmas = cached
    else:
        known_tuples, known_lemmas = None, preview_known_approx(user_files_dir, language, script)
    return store.unknown_frequencies(
        known_tuples=known_tuples, known_lemmas=known_lemmas,
        ignore_set=preview_ignore_set(user_files_dir, language, script), skip_singles=(language == "ja"))


def preview_ignore_set(user_files_dir, language, script="asis"):
    """The ignore / blacklist / graduated words as preview_frequencies reads them — cheap plain-text
    reads, each file in its own encoding, in the library's Chinese script like the analyzer reads them
    (stdlib only, so the conversion is safe in the GUI process; the tables load only if a script is
    chosen) — and KnownWord.json's IGNORED entries and, with Ignore names on, the library's names (`ignored_entries`),
    as the analyzer ignores them."""
    from app.path_utils import read_text
    from app.zh_script import convert
    ignore = set()
    for name in ("IgnoreList.txt", "Blacklist.txt", "GraduatedList.txt"):
        try:
            for line in read_text(os.path.join(user_files_dir, name), language).splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    ignore.add(convert(s, script))
        except Exception:
            pass
    ignore.update(convert(term, script) for term in ignored_entries(user_files_dir, language))
    return ignore


def ignored_entries(user_files_dir, language):
    """The dictForms of KnownWord.json's IGNORED entries, as written — Migaku's status for a word the user dismissed
    there — and, with Ignore names on, the library's names (`ignored_names`). They are ignored words, as a line of the
    Ignore list is: off the list, and never an unknown in a sentence. One reader for every ignore set — the analyzer's
    (`analyzer.load_ignored_entries`, a list's lines read the way the lists are) and the Rarity preview's
    (`preview_ignore_set`), so the slider counts what the list counts. Tokenizer-free, in the file's own encoding; a
    file that won't read ignores none of its entries.

    The file's entries are read again only when the file changes (`known_signature`, as the known-words cache is):
    every Rarity slider refresh asked, and parsing a large KnownWord.json was about a quarter of the refresh. The names
    are asked every time — the switch and the library's tables change without the file."""
    from app.path_utils import read_text
    path = os.path.join(user_files_dir, "KnownWord.json")
    signature = (language, known_signature(path))
    kept = _IGNORED_ENTRIES.get(path)
    if kept is None or kept[0] != signature:
        try:
            data = json.loads(read_text(path, language))
        except Exception:
            data = None
        entries = data.get("words", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        kept = _IGNORED_ENTRIES[path] = (signature, [
            str(e.get("dictForm") or "").strip() for e in entries
            if isinstance(e, dict) and e.get("knownStatus") == "IGNORED" and str(e.get("dictForm") or "").strip()])
    return list(kept[1]) + ignored_names(language)


_IGNORED_ENTRIES = {}   # KnownWord.json's path -> (its signature, its IGNORED dictForms), for ignored_entries


def preview_known_approx(user_files_dir, language, script="asis"):
    """Known lemmas WITHOUT the tokenizer (dictForm approximation), for preview_frequencies when the
    store's normalized known cache is stale — parsing KnownWord.json is the expensive bit on a big
    library, so it's kept off the common (fresh-cache) path."""
    from app.path_utils import read_text
    from app.zh_script import convert
    known = set()
    try:
        data = json.loads(read_text(os.path.join(user_files_dir, "KnownWord.json"), language))   # its own encoding
        entries = data.get("words", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for e in entries:
            if e.get("knownStatus") == "KNOWN" or e.get("hasCard") == 1:
                term = e.get("dictForm", "")
                if term:
                    known.add(convert(term, script))
    except Exception:
        pass
    return known


# --------------------------------------------------------------------------- #
# Tokenizer factory (default; injectable for tests)
# --------------------------------------------------------------------------- #
def build_signature(language, reinforce=False, script="asis"):
    """Fingerprint of the tokenizer identity that produced the cache, passed to reconcile so a
    config change invalidates stale tokens. What varies at runtime: Chinese `reinforce`
    segmentation, `script` conversion, the sentence boundaries settings.json sets — they decide
    where every file splits — what a Japanese book's kana in parentheses become, whether a
    katakana name is one word (logic.names_katakana) and whether a phrase or a title is
    (logic.phrases_and_titles; language is already isolated per DB; a
    tokenizer-LIBRARY change, or a change of a DEFAULT, is handled by bumping SCHEMA_VERSION, which
    rebuilds). Normalized so ja ignores a stray reinforce or script. Each suffix appears ONLY when it
    departs from the default — the script when converting, the boundaries when edited, the readings
    when not hiragana only, the katakana names or the phrases when off — so a store built as shipped
    keeps its exact old signature and upgrading never rebuilds anyone's index (spec I2)."""
    from app.zh_script import effective
    eff_reinforce = bool(reinforce) and language == "zh"
    sig = f"{language}|reinforce={eff_reinforce}"
    eff_script = effective(language, script)
    if eff_script != "asis":
        sig = f"{sig}|script={eff_script}"
    boundaries = _edited_boundaries(language)
    if boundaries is not None:
        sig = f"{sig}|boundaries={boundaries}"
    readings = _chosen_paren_readings(language)
    if readings is not None:
        sig = f"{sig}|paren_readings={readings}"
    for key in ("names_katakana", "phrases_and_titles"):
        if _switched_off(language, key):
            sig = f"{sig}|{key}=off"
    return sig


def _edited_boundaries(language):
    """The language's sentence boundaries as settings.json sets them (every run and the indexer split
    with these) — a sorted JSON list — or None when they are the default set in any order: load_settings
    adds any default character an old copy lacks, so the user's own 。！？!?\\n｡ counts as the default.
    Read fresh, not from the analyzer's import-time LOGIC: the dashboard's check must see a hand edit
    as the indexer it launches will."""
    try:
        from app import settings_manager
        default = settings_manager.DEFAULT_SETTINGS["logic"]["sentence_boundaries"].get(language)
        current = settings_manager.load_settings()["logic"]["sentence_boundaries"].get(language)
    except Exception:
        return None
    if not isinstance(current, str) or not isinstance(default, str) or set(current) == set(default):
        return None
    return json.dumps(sorted(set(current)), ensure_ascii=False)


def _chosen_paren_readings(language):
    """What a Japanese book's kana in parentheses right after kanji become when settings.json chooses
    other than the default (logic.paren_readings: "any" or "off" — analyzer.strip_text_conventions
    reads it), else None: hiragana only, an unknown value, or a Chinese store the rule never reaches.
    Read fresh, as the boundaries are."""
    if language != "ja":
        return None
    try:
        from app import analyzer, settings_manager
        option = analyzer.paren_readings(settings_manager.load_settings()["logic"])
        default = settings_manager.DEFAULT_SETTINGS["logic"]["paren_readings"]
    except Exception:
        return None
    return None if option == default else option


def _switched_off(language, key):
    """Whether settings.json switches off a Japanese reading rule applied as a file is tokenized — katakana names
    (logic.names_katakana: app/names.py) or phrases and titles as one word (logic.phrases_and_titles) — for a
    Japanese store. Read fresh, as the boundaries are."""
    if language != "ja":
        return False
    try:
        from app import settings_manager
        return not settings_manager.load_settings()["logic"].get(key, True)
    except Exception:
        return False


def make_tokenizer(language, reinforce=False, script="asis"):
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
    # Japanese: each file as it reads alone, its name candidates recorded beside it (app/names.py) — the library's
    # tables are applied as the cache is read (`Store.file_tokens`), so a new table needs no re-tokenizing.
    tok = analyzer.ChineseTokenizer(reinforce_segmentation=reinforce, script=script) \
        if language == "zh" else analyzer.JapaneseTokenizer(library=False)
    has_lang, extract = analyzer.has_target_language, analyzer.extract_text
    lemma_in_language = {}      # lemma -> has_lang(lemma), asked once per word: the count below runs on every token

    def tokenize_file(path):
        from app import names
        record = names.Record() if language == "ja" else None
        sentences = list(tok.tokenize_sentences(extract(path, language), names=record) if record
                         else tok.tokenize_sentences(extract(path, language)))
        counts = Counter()
        for _s_text, s_tokens in sentences:
            for lemma, reading, surface, _orth in s_tokens:
                in_language = lemma_in_language.get(lemma)
                if in_language is None:
                    in_language = lemma_in_language[lemma] = has_lang(lemma, language)
                if in_language or has_lang(surface, language):
                    counts[make_key(lemma, reading)] += 1
        result = {"sentences": sentences, "counts": counts}
        if record is not None:
            result["names"] = record.data()
        return result

    return tokenize_file


def reconcile_language(language, files, path=None, reinforce=False, script="asis"):
    """Convenience: open the store and reconcile it with the default tokenizer."""
    store = open_store(language, path)
    try:
        store.reconcile(files, make_tokenizer(language, reinforce, script),
                        build_signature=build_signature(language, reinforce, script))
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
