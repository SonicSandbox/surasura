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

Counted and kept (L2.2 05 §5.10, E2.2)
---------------------------------------
Each file is **counted** (`files.counted` 1: the analysed tiers, and a missing item until the user decides) or
**kept** (0: Finished, New arrivals, removed items whose sentences weren't forgotten). `reconcile(files, ...,
kept=)` takes both lists; a kept file is tokenized and cached like any other (`file_tokens` serves both), but every
sum reads counted files only — the aggregate and `bound` (a file moving between the lists moves its counts in or out,
never re-tokenized: invariant 3 holds), `total_tokens`, `has_tokens`, `file_count`, the name tables and their
adjustment, the phrase table and its matches. A file in neither list leaves. A store made before the flag gets the
column by an `ALTER TABLE`, every row counted (it was counted before): nothing is rebuilt.

A third class, **set aside** (W-1, K-W2: `files.aside` 1, `counted` 0 — a watched episode while the library's *Keep
studying watched episodes* is off; `reconcile(..., aside=)`): tokenized and cached as a counted file is, never summed
— every count above leaves it exactly as it leaves a kept file — but still the name tables' evidence (their sums, the
names Ignore names reads, the arrivals gate's records: `_EVIDENCE`), so a stone never changes what a word is. A file
moves between the three classes with no tokenizing. Its own column, added in place like `counted` (no SCHEMA_VERSION):
a build before it reads an aside row as kept — never summed — so neither build's sums go wrong in the other.

A kept file's text lives in `kept_text_<lang>_<key>.db` beside the library store (`_KeptText`), never in this cache:
invariant 4 stays true for this file — a wipe or a reset deletes only it, and the next reconcile reads a kept file that
is gone from the disk back in from its kept text. Kept rows and kept text go only when the user forgets a file
(`reconcile`'s `forgotten`), never because a list left them out. A file that moves keeps its row (`reconcile`'s
re-key: one leaving row and one new path with the same name, size and modified time).
"""

import os
import json
import hashlib
import zlib
import sqlite3
import time
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
# v13 each file also records its runs of one-kanji pieces, how often each kanji stands alone, and whether a
#    transcript's captions are auto-generated — a story's own kanji terms are one word; a katakana word the lists hold
#    that no dictionary join makes is one word, and a katakana name no longer takes the head of a word written on in
#    hiragana — still 2.4, so users rebuild once with v8–v12.
# v14 a word general text writes as words though the tagger reads it otherwise alone is one word (出来損ない: 出来 +
#    損ない in a sentence), and a verb's stem may stand in a noun the dictionaries mark (待ち + 時間, 立ち + 位置): a v13
#    blob holds those words in pieces — still 2.4, so users rebuild once with v8–v13.
# v15 two fillers cut out of one interjection are that word (まあ, not ま + あ), a sound said three times or more that
#    the dictionary doesn't know is the sound word said twice (ハァハァハァ is はあはあ), a dash drawn out inside a word is
#    a stretch (ザ─────ック), a dash is never a word, and the next line's opening bracket glued to a full stop opens
#    the next sentence: a v14 blob holds the pieces and the old sentences — still 2.4, so users rebuild once with v8–v14.
# v16 each file also records how often each one-kanji word stands there as a piece of something else (年 in 三年, 斬 in
#    斬魄刀 — analyzer.bound_uses), kept summed in the `bound` table: the Rarity slider counts a one-kanji list word by
#    the uses Generate counts, where it stands on its own — still 2.4, so users rebuild once with v8–v15.
# v17 Chinese is cut by analyzer.chinese_cut — jieba's dictionary only, CC-CEDICT's words, numbers no words, doubled
#    forms at their word, Traditional through Simplified — with the new sentence ends: a v16 blob holds Chinese cut by
#    jieba's guesses and phrases, numbers as words and …… / ；ending sentences — still 2.4, so users rebuild once
#    with v8–v16.
# v18 a verb + its negative or causative and a word + particles the dictionary lists are one word (くだらない, 知らせる,
#    いつも, ちなみに), a pronoun + a suffix the lists carry is one (何様, お前さん), and a katakana word stretched
#    inside is read without the stretch where that is a word (バイバ～イ): a v17 blob holds them in pieces — still 2.4,
#    so users rebuild once with v8–v17.
# v19 a one-kanji word right after a number's counter written in kanji is a piece of the count (the 目 of ２時間目,
#    analyzer._bound_at): a v18 store counted it as a use in each file's `bound` record — still 2.4, so users rebuild
#    once with v8–v18.
# v20 an .ass file is read through the caption cleaner (app/caption_clean.py, ENGINE_REVISION 31): a v19 blob holds a
#    TV caption's small-type reading rows as words — the release after 2.5, so users rebuild once (P1.3-1 a).
SCHEMA_VERSION = 20

# The form of each file's remembered share of the name tables' adjustments (meta names_adjust_files,
# Store._names_adjust): a change here, or to how a share is computed, makes every file's share computed again.
_NAMES_SHARES = 1


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
# IF NOT EXISTS on every object, kept as a second guard. Two processes can both read a stale `user_version` (the
# background indexer and a Generate run race routinely) and both decide the schema is missing; what keeps them apart is
# the write lock: _ensure_schema builds inside BEGIN IMMEDIATE and looks at the version again inside it, so the second
# finds the first's build done and runs nothing.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path   TEXT PRIMARY KEY,   -- normcase abspath
    mtime  REAL, size INTEGER, -- reconcile signature (filesystem truth)
    total  INTEGER,            -- token count for this file
    counts BLOB,               -- zlib(json {"lemma|reading": n}) for O(delta) subtract
    tokens BLOB,               -- zlib(json sentences) — cached tokenization for Generate reuse
    names  BLOB,               -- zlib(json app.names.Record data) — the file's name candidates (Japanese)
    bound  BLOB,               -- zlib(json {"lemma|reading": n}) — one-kanji words' uses as pieces (Japanese)
    counted INTEGER NOT NULL DEFAULT 1, -- 1 counted, 0 kept: tokenized, never summed (module docstring)
    aside INTEGER NOT NULL DEFAULT 0    -- 1 with counted 0: set aside (W-1), never summed, the name tables' evidence
);
CREATE TABLE IF NOT EXISTS aggregate (  -- maintained rollup; the preview reads this
    lemma TEXT, reading TEXT, count INTEGER,
    PRIMARY KEY (lemma, reading)
);
CREATE INDEX IF NOT EXISTS idx_aggregate_count ON aggregate(count DESC);
CREATE TABLE IF NOT EXISTS bound (      -- maintained rollup of the files' `bound`: the preview reads this too
    lemma TEXT, reading TEXT, count INTEGER,
    PRIMARY KEY (lemma, reading)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _statements(script):
    """A script's statements, one by one (a ';' inside a comment ends none: sqlite3.complete_statement decides)."""
    out, part = [], ""
    for piece in script.split(";"):
        part += piece + ";"
        if sqlite3.complete_statement(part):
            statement = part.strip().rstrip(";").strip()
            if statement:
                out.append(statement)
            part = ""
    return out


_REBUILD = [f"DROP TABLE IF EXISTS {t}" for t in ("files", "aggregate", "bound", "meta")] + _statements(_SCHEMA)


def _schema_ready(conn):
    """The store is this schema, every table there. A table or column missing (a half-built DB) is "not ready"; any other
    error — busy, a disk error, damage — is raised, never read as "build it again" (the build drops every table)."""
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        return False
    try:
        conn.execute("SELECT names, bound FROM files LIMIT 1")
        conn.execute("SELECT 1 FROM aggregate LIMIT 1")
        conn.execute("SELECT 1 FROM bound LIMIT 1")
        conn.execute("SELECT 1 FROM meta LIMIT 1")
    except sqlite3.OperationalError as e:
        if "no such" in str(e).lower():
            return False
        raise
    return True


def _ensure_schema(conn):
    """The schema, built when it is missing or old — inside BEGIN IMMEDIATE, the version looked at again inside the lock:
    two first opens (Generate and the indexer) both read user_version 0, and the second's drops, landing between the
    first's statements, gave it "no such table" (read as damage: open_store deleted the store) or took tables it was
    already writing to. Now the second waits for the first's build (up to the busy timeout; past it, "database is
    locked", which open_store raises and never deletes on) and finds it done. Statement by statement, never
    executescript (it COMMITs the open transaction first); a build cut short leaves nothing (rolled back)."""
    if not _schema_ready(conn):
        conn.execute("BEGIN IMMEDIATE")
        try:
            if not _schema_ready(conn):
                for statement in _REBUILD:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    _add_counted(conn)


# A file's class (module docstring): its (counted, aside) columns read as one value — `_STATE` in SQL — and written back
# by `_columns`. Sums read `counted = 1`; the name tables' evidence reads `_EVIDENCE`.
KEPT, COUNTED, ASIDE = 0, 1, 2
_STATE = "CASE WHEN counted = 1 THEN 1 WHEN aside = 1 THEN 2 ELSE 0 END"
_EVIDENCE = "(counted = 1 OR aside = 1)"
_ADDED = (("counted", "INTEGER NOT NULL DEFAULT 1"), ("aside", "INTEGER NOT NULL DEFAULT 0"))


def _columns(state):
    """(counted, aside) for a file's class."""
    return (1 if state == COUNTED else 0), (1 if state == ASIDE else 0)


def _add_counted(conn):
    """The counted / kept flag (E2.2) and the set-aside one (W-1) on a store made before them: added, every row counted
    and none aside — as it was read before — so the store is read exactly as it was, nothing rebuilt and no version
    moved. Two first opens may race to add them; the loser finds them there (looked at again inside the write lock; a
    "duplicate column" is success; any other error is raised, and open_store deletes the store only when it says the
    file is damaged: `_damaged`)."""
    def missing():
        have = [r[1] for r in conn.execute("PRAGMA table_info(files)")]
        return [(name, kind) for name, kind in _ADDED if name not in have]
    if not missing():
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for name, kind in missing():
            conn.execute(f"ALTER TABLE files ADD COLUMN {name} {kind}")
        conn.commit()
    except sqlite3.OperationalError as e:
        conn.rollback()
        if "duplicate column" not in str(e).lower():
            raise


def _delete_db(path):
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


def open_store(language, path=None):
    """Open (or create/rebuild) the SQLite token store for a language. WAL, busy-timeout, schema
    ensured, corruption self-heals by rebuilding; any other database error (busy, a full disk, an I/O error) is
    raised, the store kept (`_damaged`)."""
    db_path = path or store_path_for(language)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def _connect():
        c = sqlite3.connect(db_path, timeout=5.0)
        try:
            # Before the switch to WAL: a new file's switch is a rollback-mode commit, and at the default FULL each
            # attempt fsyncs a journal — under a disk storm one attempt's wait could use the loop's whole 5 s.
            c.execute("PRAGMA synchronous=NORMAL")
            # A new file's switch to WAL answers "database is locked" at once — no busy timeout — while another
            # connection makes the same file (two first opens: Generate and the indexer on a first run). Asked
            # again until the busy timeout, as any other wait for the file.
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    c.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as e:
                    if not _locked(e) or time.monotonic() > deadline:
                        raise
                    time.sleep(0.02)
            c.execute("PRAGMA busy_timeout=5000")
            _ensure_schema(c)
        except Exception:
            c.close()   # never leak a handle to a corrupt file (Windows can't delete an open file)
            raise
        return c

    try:
        return Store(_connect(), language, db_path)
    except sqlite3.DatabaseError as e:
        if not _damaged(e):
            raise                       # busy, a full disk, an I/O error: the file may be whole — never delete it
        # Corrupt DB -> delete + rebuild (it's a regenerable cache). The kept text beside it is another file: untouched.
        _delete_db(db_path)
        return Store(_connect(), language, db_path)


def open_reader(language, path=None):
    """The token store opened to read only (the warm arrivals worker, E2.2 D10: "writes nothing") — no schema ensured,
    no rebuild of a damaged file, SQLite refusing any write (`query_only`) — or None when there is none or it can't be
    read. Opened `mode=rw` (never made), not `mode=ro`: a read-only connection to a WAL file makes its -wal / -shm
    files and can't remove them when it closes, so they'd stay behind; this one, the last to close, tidies them as
    every other connection does."""
    db_path = path or store_path_for(language)
    if not os.path.exists(db_path):
        return None
    try:
        from pathlib import Path
        c = sqlite3.connect(Path(os.path.abspath(db_path)).as_uri() + "?mode=rw", uri=True, timeout=5.0)
    except sqlite3.Error:
        return None
    try:
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA query_only=ON")
        c.execute("SELECT 1 FROM meta LIMIT 1")
        have = {r[1] for r in c.execute("PRAGMA table_info(files)")}
    except sqlite3.Error:
        c.close()
        return None
    store = Store(c, language, db_path)
    if "aside" not in have:         # a store no writer has opened since the set-aside mark: read as it was (no column
        store._evidence = "counted = 1" if "counted" in have else "1"   # added here: a reader never writes)
    return store


# SQLite's primary result codes (Python 3.11's sqlite3.SQLITE_*), read from an error's `sqlite_errorcode`.
_BUSY_CODES = (5, 6, 15)        # SQLITE_BUSY, SQLITE_LOCKED, SQLITE_PROTOCOL
_DAMAGE_CODES = (11, 26)        # SQLITE_CORRUPT, SQLITE_NOTADB


def _code(error):
    """The error's primary SQLite result code, or None (an error raised by hand, an older Python): read by its text."""
    code = getattr(error, "sqlite_errorcode", None)
    return None if code is None else code & 0xFF


def _locked(error):
    """SQLite's "database is locked" / "busy" / "locking protocol": another connection holds the file, or the WAL
    index was changing as this one looked (SQLITE_PROTOCOL, after SQLite's own retries) — an OperationalError, which is
    a DatabaseError too, and never a sign of a damaged file. Waited on and asked again where an open waits; else raised."""
    code = _code(error)
    if code is not None:
        return code in _BUSY_CODES
    text = str(error).lower()
    return isinstance(error, sqlite3.OperationalError) and (
        "locked" in text or "busy" in text or "locking protocol" in text)


def _damaged(error):
    """The file itself is damaged — SQLite says it is corrupt or not a database (a file cut short or scribbled on lands
    here too) — the one error open_store answers by deleting the store (a cache: built again). Anything else says
    nothing of the file and is raised, the store kept: busy or a locking protocol (another connection), a full disk (a
    rebuild would only fill it again), a disk I/O error (the disk's: a rebuild meets the same disk), no permission,
    can't open. Never deleted for it: the next open tries again, and Generate runs on without the cache meanwhile. By
    its text only when raised without a code: SQLite's own words for damage, never any "malformed" (JSON's is not)."""
    code = _code(error)
    if code is not None:
        return code in _DAMAGE_CODES
    text = str(error).lower()
    return any(words in text for words in ("database disk image is malformed", "malformed database schema",
                                           "not a database"))


# --------------------------------------------------------------------------- #
# Kept text (L2.2 05 §5.10, E2.2): the sentences of the files the store keeps and may not read again from the disk
# --------------------------------------------------------------------------- #
_KEPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS kept (
    rel   TEXT PRIMARY KEY,   -- the file's path relative to the data folder ('/'), as the store keys it (normcase)
    text  TEXT,               -- what extract_text made of it (facts "rebuilt": its cached sentences, one a line)
    facts TEXT,               -- JSON: what the file said of itself as it was read (extract_text's "captions")
    mtime REAL, size INTEGER  -- the file's (mtime, size) when its text was read
);
"""


def kept_text_path(language, data_dir):
    """`kept_text_<lang>_<key>.db`: beside the library store's own file and keyed as it is (the language and the data
    folder: `library_store.library_db_path`) — the local data folder, never %APPDATA% beside this cache; under the test
    root as the library store's."""
    from app import library_store
    db = library_store.library_db_path(language, data_dir)
    os.makedirs(os.path.dirname(db), exist_ok=True)
    return os.path.join(os.path.dirname(db), "kept_text_" + os.path.basename(db)[len("library_"):])


class _KeptText:
    """`kept_text_<lang>_<key>.db` (`kept_text_path`): the text of each kept file, and of each counted file gone from the
    disk, so a wipe of the token store (a cache: it deletes itself when damaged, a new schema or tokenizer identity
    empties it) can read them back in. Its own file, `synchronous=FULL`, never touched by the store's wipe or reset; a
    file's text goes only when the user forgets it (`reconcile`'s `forgotten`). Opened only
    when something is kept, read or dropped — a reconcile with nothing kept never makes it. A file that isn't a
    database any more is set aside once (renamed, with a printed line) and a new one started, never fatal; any other
    error (locked, the disk full) is raised, so the reconcile rolls back and deletes nothing."""

    def __init__(self, path, data_dir=None):
        self.path = path
        self.root = _norm(data_dir) if data_dir else None
        self.conn = None

    def _rel(self, key):
        """The store's key (a normcase absolute path) as the kept text keys it: relative to the data folder."""
        if self.root and key.startswith(self.root + os.sep):
            return key[len(self.root) + 1:].replace(os.sep, "/")
        return key

    def _key(self, rel):
        return _norm(os.path.join(self.root, rel)) if self.root and not os.path.isabs(rel) else rel

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=5.0)
        try:
            c.execute("PRAGMA busy_timeout=5000")
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=FULL")
            c.executescript(_KEPT_SCHEMA)
            c.execute("SELECT rel, text, facts, mtime, size FROM kept LIMIT 1")
        except Exception:
            c.close()
            raise
        return c

    def _set_aside(self, error):
        """Rename the damaged file aside (a new name each time: an earlier copy is never overwritten). False when it
        can't be moved (held open elsewhere): it is left as it is and nothing is started anew."""
        stamp = time.strftime('%Y%m%d-%H%M%S')
        aside, n = f"{self.path}.damaged-{stamp}", 1
        while any(os.path.exists(aside + suffix) for suffix in ("", "-wal", "-shm")):
            n += 1
            aside = f"{self.path}.damaged-{stamp}-{n}"
        try:
            os.replace(self.path, aside)
        except OSError as e:
            print(f"Some kept sentences couldn't be read ({error}), and {os.path.basename(self.path)} couldn't be set "
                  f"aside ({e}): it is left as it is.")
            return False
        for suffix in ("-wal", "-shm"):
            try:
                os.replace(self.path + suffix, aside + suffix)
            except OSError:
                pass
        print(f"Some kept sentences couldn't be read ({error}): {os.path.basename(self.path)} was set aside as "
              f"{os.path.basename(aside)} and a new one started.")
        return True

    def _run(self, work, default, create=False):
        """`work(conn)` on the file — `default` when it doesn't exist and isn't to be made (`create`)."""
        for attempt in (0, 1):
            try:
                if self.conn is None:
                    if not create and not os.path.exists(self.path):
                        return default
                    self.conn = self._connect()
                return work(self.conn)
            except sqlite3.DatabaseError as e:
                if isinstance(e, sqlite3.OperationalError) or attempt:
                    raise                           # locked, the disk full, an I/O error: nothing is set aside
                self.close()
                if not self._set_aside(e):          # not a database (damaged): once
                    raise                           # it can't be moved: never written over, the caller's work undone
                create = True
        return default

    def held(self, stamps=False):
        """{key: whether its text was rebuilt from cached sentences} — every file whose text is kept; `stamps`:
        {key: (rebuilt, mtime, size)}, the (mtime, size) of the file the text was kept for."""
        def work(conn):
            return {self._key(rel): ("rebuilt" in json.loads(facts or "{}"), mtime, size) if stamps else
                    "rebuilt" in json.loads(facts or "{}")
                    for rel, facts, mtime, size in conn.execute("SELECT rel, facts, mtime, size FROM kept")}
        return self._run(work, {})

    def has(self, keys):
        """The `keys` whose text is kept — read only (never made, never set aside: a cheap check's). Raises when the
        file can't be read."""
        if not os.path.exists(self.path):
            return set()
        import pathlib
        c = sqlite3.connect(pathlib.Path(self.path).as_uri() + "?mode=ro", uri=True, timeout=0.5)
        try:
            rels = {self._rel(key): key for key in keys}
            return {rels[rel] for (rel,) in c.execute("SELECT rel FROM kept") if rel in rels}
        finally:
            c.close()

    def get(self, key):
        """(text, facts, mtime, size) kept for the store's `key`, or None."""
        def work(conn):
            row = conn.execute("SELECT text, facts, mtime, size FROM kept WHERE rel=?", (self._rel(key),)).fetchone()
            return None if row is None else (row[0] or "", json.loads(row[1] or "{}"), row[2], row[3])
        return self._run(work, None)

    def put(self, rows):
        """Keep {key: (text, facts, mtime, size)}, in one transaction, committed before this returns."""
        if not rows:
            return

        def work(conn):
            with conn:
                conn.executemany("INSERT OR REPLACE INTO kept(rel, text, facts, mtime, size) VALUES(?,?,?,?,?)",
                                 [(self._rel(key), text, json.dumps(facts or {}, ensure_ascii=False), mtime, size)
                                  for key, (text, facts, mtime, size) in rows.items()])
        self._run(work, None, create=True)

    def drop(self, keys):
        keys = list(keys)
        if keys:
            def work(conn):
                with conn:
                    conn.executemany("DELETE FROM kept WHERE rel=?", [(self._rel(key),) for key in keys])
            self._run(work, None)

    def rekey(self, old, new):
        """A moved file's text follows it (9a)."""
        def work(conn):
            with conn:
                conn.execute("DELETE FROM kept WHERE rel=?", (self._rel(new),))
                conn.execute("UPDATE kept SET rel=? WHERE rel=?", (self._rel(new), self._rel(old)))
        self._run(work, None)

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None


def _rebuilt_text(sentences, names=None):
    """(text, facts) of a file read from its cached sentences, one a line — all there is to keep of a file gone from the
    disk before its text was kept (the spaces the tagger drops are gone with it); `names`, its name record, says
    whether its captions were auto-generated ("a")."""
    facts = {"rebuilt": True}
    if names and names.get("a"):
        facts["auto"] = True
    return "\n".join(s_text for s_text, _tokens in sentences), facts


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
class Store:
    _evidence = _EVIDENCE       # the name tables' evidence, as this store's columns can say it (`open_reader`)

    def __init__(self, conn, language=None, path=None):
        self.conn = conn
        self.language = language
        self.path = path            # the store's file
        self._names = None          # the library's name tables, read on the first cached file (Japanese)
        self._adjust = None         # (meta names_adjust as stored, parsed): `_names_entry`

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
        """The counted files' tokens (a kept file's never count)."""
        r = self.conn.execute("SELECT COALESCE(SUM(total), 0) FROM files WHERE counted = 1").fetchone()
        return int(r[0]) if r else 0

    def has_tokens(self):
        """Does any counted file hold a token — `total_tokens()` > 0 (a file's total is never negative), without
        summing every file."""
        return self.conn.execute("SELECT 1 FROM files WHERE total > 0 AND counted = 1 LIMIT 1").fetchone() is not None

    def file_count(self):
        """How many counted files the store holds (the library's size, as the Rarity slider's average file reads it)."""
        return int(self.conn.execute("SELECT COUNT(*) FROM files WHERE counted = 1").fetchone()[0])

    def counted_files(self):
        """The counted files' keys (normcase absolute paths), in the table's order."""
        return [r[0] for r in self.conn.execute("SELECT path FROM files WHERE counted = 1 ORDER BY rowid")]

    def kept_files(self):
        """The kept files' keys: tokenized and cached, never counted."""
        return [r[0] for r in self.conn.execute(f"SELECT path FROM files WHERE {_STATE} = 0 ORDER BY rowid")]

    def aside_files(self):
        """The set-aside files' keys (W-1): tokenized and cached, never counted, the name tables' evidence."""
        return [r[0] for r in self.conn.execute(f"SELECT path FROM files WHERE {_STATE} = 2 ORDER BY rowid")]

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

    def _update_names_tables(self, cur, build_signature=None):
        """Compute the library's name tables from every file's recorded candidates (and the last tables, for the
        flip guard) and store them, with the library's names (`names.name_words`, for Ignore names) — after a
        reconcile changed something. Japanese only. `build_signature`: the tokenizer identity the files were just
        read with (reconcile's), for `_names_adjust`'s per-file memory."""
        from app import analyzer, names
        row = cur.execute("SELECT value FROM meta WHERE key='names_tables'").fetchone()
        try:
            previous = json.loads(row[0]) if row else None
        except Exception:
            previous = None
        # In the table's own order (rowid, as a scan reads it): the tables and the adjustments sum the files in it. The
        # tables (and the names) from the evidence — counted and set-aside files (W-1: a stone never changes what a word
        # is); the adjustment to the running totals from the counted files alone, as the totals hold them.
        rows = cur.execute(f"SELECT path, mtime, size, names, counted FROM files WHERE names IS NOT NULL AND "
                           f"{_EVIDENCE} ORDER BY rowid").fetchall()
        records = [_decode_counts(row[3]) for row in rows]
        tables = names.compute_tables(records, previous, analyzer._sanitize_term)
        counted = [i for i, row in enumerate(rows) if row[4] == 1]
        adjust = self._names_adjust(cur, tables, [rows[i][:4] for i in counted], [records[i] for i in counted],
                                    build_signature)
        for key, value in (("names_tables", tables), ("names_adjust", adjust),
                           ("names_words", names.name_words(records, tables, analyzer._sanitize_term))):
            value = json.dumps(value, ensure_ascii=False)
            cur.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=?",
                        (key, value, value))
        self._names = None

    def _names_adjust(self, cur, tables, files, records, build_signature=None):
        """What the name tables change in the running totals, for each way the three switches can be set. The
        aggregate counts each file as it reads alone; the list counts its cached tokens with the tables applied
        (file_tokens) — so the Rarity slider's numbers, and the band automatic rarity picks from them, must add each
        joined name and take away its pieces, counted as the aggregate counts (a token with target-language
        characters) — and the one-kanji words a join makes or unmakes pieces of something else (`bound`: 斬 + 魄 + 刀
        joined as a term are no pieces any more; a word beside them no longer stands glued to them). {"111" | "110" |
        … | "001" (recurring, kanji, terms): {"counts": [[lemma, reading, delta], ...], "total": delta, "bound":
        [[lemma, reading, delta], ...]}}.

        `files` ((path, mtime, size, names blob), in the table's order) and their decoded `records`. Each file's
        share is remembered (meta names_adjust_files) with what decides it — the file as read ((mtime, size), under
        the same tokenizer identity and engine) and what the tables make of its name candidates (`_names_held`) — so
        a change reads again only the files it touched or whose names the tables now read otherwise; every file's
        share is then summed in the table's order, exactly as one pass over every file sums them."""
        from app import analyzer
        if not tables:
            return {}
        spellings = {kind: set(table) for kind, table in tables.items() if isinstance(table, dict)}
        terms = spellings.get("w", ())
        combos = [(f"{r:d}{k:d}{t:d}", (bool(r), bool(k), bool(t)))
                  for r in (1, 0) for k in (1, 0) for t in (1, 0) if r or k or t]
        deltas = {combo: [Counter(), 0, Counter()] for combo, _switches in combos}
        if build_signature is None:
            row = cur.execute("SELECT value FROM meta WHERE key='build_sig'").fetchone()
            build_signature = row[0] if row else None
        state = [_NAMES_SHARES, SCHEMA_VERSION, analyzer.ENGINE_REVISION, build_signature]
        row = cur.execute("SELECT value FROM meta WHERE key='names_adjust_files'").fetchone()
        try:
            kept = json.loads(row[0]) if row else {}
            kept = kept.get("files", {}) if kept.get("state") == state else {}
        except (ValueError, AttributeError):
            kept = {}
        reads = _names_reads(tables)
        shares = {}
        for (path, mtime, size, _blob), record in zip(files, records):
            spans = record.get("s", [])
            if not any(span[6] in spellings.get(span[5], ()) or (span[5] == "w" and _holds_a_term(span[6], terms))
                       for span in spans):
                continue                                # no joined name here: nothing to decode
            held = _names_held(spans, reads, (True, True, True))
            entry = kept.get(path)
            if entry is None or entry[0] != mtime or entry[1] != size or entry[2] != held:
                blob = cur.execute("SELECT tokens FROM files WHERE path=?", (path,)).fetchone()[0]
                entry = [mtime, size, held, self._names_share(_decode_tokens(blob), spans, tables, combos)]
            shares[path] = entry
            for combo, (counts, total, pieces) in entry[3].items():
                delta = deltas[combo]
                for lemma, reading, n in counts:
                    delta[0][(lemma, reading)] += n
                delta[1] += total
                for lemma, reading, n in pieces:
                    delta[2][(lemma, reading)] += n
        value = json.dumps({"state": state, "files": shares}, ensure_ascii=False, separators=(",", ":"))
        cur.execute("INSERT INTO meta(key, value) VALUES('names_adjust_files', ?) ON CONFLICT(key) DO UPDATE SET value=?",
                    (value, value))
        return {combo: {"counts": [[l, r, n] for (l, r), n in counts.items() if n], "total": total,
                        "bound": [[l, r, n] for (l, r), n in pieces.items() if n]}
                for combo, (counts, total, pieces) in deltas.items()}

    def _names_share(self, sentences, spans, tables, combos):
        """One file's share of `_names_adjust`, for each switch combination: {combo: [[[lemma, reading, delta], ...],
        total delta, [[lemma, reading, delta], ...] (bound)]} — every word it touches, in the order first touched, a
        delta that nets to nothing included: summed file by file in the table's order, the words come in the order a
        single pass meets them."""
        from app import analyzer, names
        has_lang = analyzer.has_target_language
        share = {}
        alone = {}                                      # sentence -> its pieces as the file reads alone (every combo's)
        for combo, switches in combos:
            counts, total, bound = Counter(), 0, Counter()
            cuts = {}                                   # sentence -> its joins, in order
            for s, a, b, token in names.chosen(sentences, spans, tables, *switches):
                cuts.setdefault(s, []).append((a, b, token))
                joined = [(token, 1)] + [(piece, -1) for piece in sentences[s][1][a:b]]
                for (lemma, reading, surface, *_rest), sign in joined:
                    if has_lang(lemma, self.language) or has_lang(surface, self.language):
                        counts[(lemma, reading)] += sign
                        total += sign
            # A join takes its pieces away and gives each word beside it a new neighbour; no other word's place
            # changes, so only those are asked again (a word's piece-ness is decided by its neighbours).
            for s, joins in cuts.items():
                text, tokens = sentences[s]
                pieces = alone.get(s)
                if pieces is None:
                    pieces = alone[s] = analyzer.bound_uses(text, tokens)
                joined, gone, beside, shift = list(tokens), set(), set(), 0
                for a, b, _token in joins:
                    gone.update(range(max(a - 1, 0), min(b + 1, len(tokens))))
                    if a:
                        beside.add(a - 1 - shift)
                    if b < len(tokens):
                        beside.add(a - shift + 1)
                    shift += b - a - 1
                for a, b, token in reversed(joins):
                    joined[a:b] = [token]
                for i in gone & pieces:
                    bound[(tokens[i][0], tokens[i][1])] -= 1
                for i in analyzer.bound_uses(text, joined, only=sorted(beside)):
                    bound[(joined[i][0], joined[i][1])] += 1
            share[combo] = [[[l, r, n] for (l, r), n in counts.items()], total,
                            [[l, r, n] for (l, r), n in bound.items()]]
        return share

    def _names_entry(self):
        """What the name tables change with the switches set now (`_names_adjust`, one switch combination) — {} when all
        are off, before the first index, or for Chinese. Parsed once while the stored value stays the same: a slider
        refresh reads it twice (`word_counts`, `bound_counts`)."""
        combo = "".join("1" if on else "0" for on in _library_switches(self.language))
        if "1" not in combo:
            return {}
        try:
            raw = self.get_meta("names_adjust") or "{}"
            if self._adjust is None or self._adjust[0] != raw:
                self._adjust = (raw, json.loads(raw))
            return self._adjust[1].get(combo) or {}
        except Exception:
            return {}

    def _names_adjustment(self):
        """({(lemma, reading): delta}, total delta) that the name tables make with the switches set now — ({}, 0) when
        all are off, before the first index, or for Chinese."""
        try:
            entry = self._names_entry()
            return {(l, r): n for l, r, n in entry.get("counts", ())}, int(entry.get("total", 0))
        except Exception:
            return {}, 0

    def _names_bound(self):
        """{(lemma, reading): delta} — how the name tables' joins change the one-kanji words' uses as pieces of
        something else, with the switches set now ({} as `_names_adjustment`)."""
        try:
            return {(l, r): n for l, r, n in self._names_entry().get("bound", ())}
        except Exception:
            return {}

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
        name tables (a known name is one word only with them), and the phrases and pronouns switches (a known 予想通り
        or 何様 is one word or two) — so any change reads the known words again. The switches are read fresh, as the
        build signature's are: the dashboard's check must see a change as the indexer it launches will."""
        if not signature or self.language != "ja":
            return signature
        try:
            from app import settings_manager
            logic = settings_manager.load_settings()["logic"]
        except Exception:
            return signature
        switches = [bool(logic.get(k, True))
                    for k in ("names_katakana", "names_recurring", "names_kanji", "names_work_terms")]
        stamp = (self.names_tables() or {}).get("stamp") if any(switches[1:]) else None
        if switches != [True] * 4 or stamp is not None:
            signature = f"{signature}|names={''.join('1' if s else '0' for s in switches)}:{stamp}"
        for key in ("phrases_and_titles", "pronoun_bases"):
            if not logic.get(key, True):
                signature = f"{signature}|{key}=off"
        # Idioms and set phrases on the list: a known phrase is also known as its lemmas joined — the phrases' own, so the
        # phrase data's revision too (analyzer.load_known_words).
        if not logic.get("phrase_rows", True):
            return signature
        try:
            from app import phrase_data
            return f"{signature}|phrase_rows={phrase_data.REVISION}"
        except Exception:
            return f"{signature}|phrase_rows=on"

    def get_cached_known(self, signature):
        """Return (known_tuples, known_lemmas) if the cache matches `signature`, else None.
        `signature` encodes KnownWord.json's (exists, mtime, size) — so any edit/delete/add misses.

        Parsed again only when the cached values change (`_KNOWN_READ`): every Rarity slider refresh, and the
        dashboard's check before launching the indexer, asked — each caller gets sets of its own."""
        signature = self._known_key(signature)
        if not signature or self.get_meta("known_sig") != signature:
            return None
        try:
            raw = (self.get_meta("known_tuples") or "[]", self.get_meta("known_lemmas") or "[]")
            kept = _KNOWN_READ[0]
            if kept is None or kept[0] != raw:
                kept = _KNOWN_READ[0] = (raw, {(l, r) for l, r in json.loads(raw[0])}, set(json.loads(raw[1])))
            return set(kept[1]), set(kept[2])
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

    def _listed(self, files, kept, flags, forgotten=None, aside=None):
        """The lists as reconcile reads them: (counted, aside, kept, forgotten), the first three {key: path} in their
        lists' order. A path in two lists is counted, else aside. Kept: `kept`, then every kept row the store holds
        (`flags`: key -> its class, KEPT / COUNTED / ASIDE) that no list names — a kept row never goes because a list
        left it out — except the `forgotten` ones (the user's *forget its sentences*), which go with their kept text: a
        set of keys, never one a list names. Aside: `aside`, and with `aside` None (a caller that knows only the run's
        list) every aside row the store holds that no list names — it stays aside, as a kept row stays kept."""
        counted = {_norm(p): p for p in files}
        put = {}
        for p in aside or ():
            key = _norm(p)
            if key not in counted:
                put.setdefault(key, p)
        held = {}
        for p in kept or ():
            key = _norm(p)
            if key not in counted and key not in put:
                held.setdefault(key, p)
        gone = {_norm(p) for p in forgotten or ()} - set(counted) - set(put) - set(held)
        for key, flag in flags.items():
            if key in counted or key in put or key in held or key in gone:
                continue
            if flag == KEPT:
                held[key] = key
            elif flag == ASIDE and aside is None:
                put[key] = key
        return counted, put, held, gone

    def needs_reconcile(self, files, kept=None, elsewhere=None, forgotten=None, data_dir=None, aside=None):
        """Cheap disk-vs-store delta check (stat only, NO tokenizer) — for a GUI pre-gate. `kept`, `elsewhere`,
        `forgotten`, `data_dir` and `aside` as `reconcile` takes them. A listed file gone from the disk keeps its row as
        it is, so it is a change only when its flag moved, when the store lacks it and its file is elsewhere (a removed
        item's, in the trash), or when its text isn't kept yet (the reconcile keeps it at once: a missing item's only
        sentences never wait for an unrelated change)."""
        rows = {r[0]: (r[1], r[2], r[3]) for r in self.conn.execute(f"SELECT path, mtime, size, {_STATE} FROM files")}
        counted, put, held, _gone = self._listed(files, kept, {key: row[2] for key, row in rows.items()}, forgotten,
                                                 aside)
        if any(key not in counted and key not in put and key not in held for key in rows):
            return True
        others = {_norm(p): where for p, where in (elsewhere or {}).items()}
        missing = []                        # rows whose file is gone, unchanged otherwise: is their text kept?
        for listed, flag in ((counted, COUNTED), (put, ASIDE), (held, KEPT)):
            for key, realpath in listed.items():
                row = rows.get(key)
                try:
                    signature = file_signature(realpath)
                except OSError:
                    if (row is None and key in others and os.path.exists(others[key])) or (
                            row is not None and row[2] != flag):
                        return True
                    if row is not None:
                        missing.append(key)
                    continue
                if row is None or row[:2] != signature or row[2] != flag:
                    return True
        if missing:
            try:
                return len(self._kept_text(data_dir).has(missing)) < len(missing)
            except Exception:
                return True                 # can't tell: the reconcile looks
        return False

    # -- reconcile (delta, one transaction) ---------------------------------- #
    def _apply(self, cur, counts, table="aggregate"):
        cur.executemany(
            f"INSERT INTO {table}(lemma, reading, count) VALUES(?,?,?) "
            "ON CONFLICT(lemma, reading) DO UPDATE SET count = count + ?",
            [(*split_key(key), n, n) for key, n in counts.items()],
        )

    def _kept_text(self, data_dir=None):
        """The library's kept text (`_KeptText`, `kept_text_path`), keyed relative to the data folder (default the
        language's)."""
        if data_dir is None:
            from app.path_utils import get_data_path
            data_dir = get_data_path(self.language)
        return _KeptText(kept_text_path(self.language, data_dir), data_dir)

    def reconcile(self, files, tokenize_file, build_signature=None, workers=None, kept=None, elsewhere=None,
                  data_dir=None, forgotten=None, aside=None):
        """Bring the store in sync with the on-disk `files`, re-tokenizing ONLY changed/new files.

        tokenize_file(path) -> {"sentences": [...], "counts": Counter} (Japanese: and "names", the file's
        name candidates, and "bound", its one-kanji words' uses as pieces of something else). Sequences are
        cached (for Generate reuse); counts maintain the aggregate, and "bound" the bound table; after
        a change the library's name tables are computed again. Runs in a single BEGIN IMMEDIATE
        transaction (atomic; serialized against other writers).

        `build_signature` (optional) fingerprints the TOKENIZER IDENTITY (e.g. the Chinese `script`
        conversion). Reconcile keys "unchanged" on (mtime, size) only, so a tokenizer-config
        change wouldn't otherwise refresh cached tokens. If the stored signature differs, every
        cached tokenization is stale -> drop it all and rebuild. (Callers MUST pass a CONSISTENT
        signature — the analyzer and the background indexer both derive it from the same setting —
        or the store would thrash, each rebuilding what the other just wrote.)

        `workers`: how many processes tokenize the changed files (W1.3, `pool_workers`): None decides — the tokenizing
        pool in the indexer only (the process holding the `indexer` lock), one process everywhere else; 0 or 1, one
        process. Every file's tokens are the same either way, and this process alone writes the store, file by file in
        the files' order.

        Counted and kept (module docstring): `files` is the counted list, `kept` the kept one — tokenized and cached,
        never summed; a path in both is counted, and a file moving between them moves its counts, never re-tokenized.
        A kept row neither list names stays kept, its text too (`kept` None: a caller that knows only the run's list —
        Generate, the sentence dictionary); a counted row neither list names goes, as ever. `forgotten`: the paths
        whose sentences the user forgot (*This file is junk*) — their rows and kept text go, unless a list names them.
        `elsewhere`: {listed path: where its file is now} (a removed item's, in the trash). `data_dir`: what the kept
        text is keyed relative to (default the language's data folder). A listed file gone from the disk keeps its row
        as it is. `aside` (W-1): the set-aside list — read as the counted list is (tokenized in the pool, its text kept
        only once its file is gone), never summed, the name tables' evidence; a file moving to or from it moves its
        counts (or none, from kept), never re-tokenized. An aside row no list names stays aside with `aside` None, and
        goes, as a counted row does, when the caller names the list.

        Before anything is deleted or wiped, the text of every kept file and of every counted file gone from the disk
        is kept (`_KeptText`, its own file, written first): read from its file (or `elsewhere`), else — the file gone
        — rebuilt from its cached sentences. A wipe reads such a file back in from it (`tokenize_file.tokenize_text`).
        A listed file the store lacks takes the row of a leaving one — or of a kept row no list names whose file is
        gone — when they are the only two with that name, size and modified time (the file moved, 9a): re-keyed with
        its kept text, never re-tokenized. Two or more alike: each read as it is.
        """
        read = getattr(tokenize_file, "read_text", None)
        from_text = getattr(tokenize_file, "tokenize_text", None)
        texts = self._kept_text(data_dir)
        cur = self.conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        changed = False         # what the counted (or set-aside) files hold changed: the name tables are read again
        phrased = False         # what the counted files hold changed: the phrases too (they read counted files alone)
        try:
            # "counted": the file's class (KEPT / COUNTED / ASIDE, `_STATE`)
            existing = {
                r[0]: {"mtime": r[1], "size": r[2], "total": r[3], "counts": r[4], "bound": r[5], "counted": r[6]}
                for r in cur.execute(f"SELECT path, mtime, size, total, counts, bound, {_STATE} FROM files")
            }
            current, put, held, gone = self._listed(files, kept, {key: row["counted"] for key, row in existing.items()},
                                                    forgotten, aside)
            listed = dict(current)
            listed.update(put)
            listed.update(held)
            others = {_norm(p): where for p, where in (elsewhere or {}).items()}
            signatures = {}
            for key, realpath in listed.items():
                try:
                    signatures[key] = file_signature(realpath)
                except OSError:
                    signatures[key] = None      # gone (or vanished between listing and stat): its row stays as it is
            wipe, stored = False, None
            if build_signature is not None:
                stored = cur.execute("SELECT value FROM meta WHERE key='build_sig'").fetchone()
                wipe = stored is not None and stored[0] != build_signature   # tokenizer identity changed -> full rebuild

            # The file moved (9a): a listed file the store lacks takes the row of a leaving one (or of a kept row no list
            # names, its file gone) — one to one, by name, size and modified time; its key changed, nothing else, and its
            # kept text follows.
            leaving = {key: None for key in existing if key not in listed}
            named = {_norm(p) for p in kept or ()}
            orphans = [key for key in held if key not in named and signatures[key] is None]
            if leaving or orphans:
                olds, news = {}, {}
                for key in list(leaving) + orphans:
                    row = existing[key]
                    olds.setdefault((os.path.basename(key), row["mtime"], row["size"]), []).append(key)
                for key, signature in signatures.items():
                    if signature is not None and key not in existing:
                        news.setdefault((os.path.basename(key), *signature), []).append(key)
                for same, (key,) in ((same, keys) for same, keys in news.items() if len(keys) == 1):
                    if len(olds.get(same, ())) != 1:
                        continue
                    old = olds[same][0]
                    cur.execute("UPDATE files SET path=? WHERE path=?", (key, old))
                    existing[key] = existing.pop(old)
                    if existing[key]["counted"]:
                        changed = True              # the phrase table and matches follow the new path
                        phrased = phrased or existing[key]["counted"] == COUNTED
                    leaving.pop(old, None)
                    if old in held:
                        del held[old], listed[old], signatures[old]
                    texts.rekey(old, key)

            # Kept text first — before anything below is deleted or wiped: each kept file, and each counted file gone
            # from the disk, whose row the store holds and whose text isn't kept yet (one rebuilt from cached sentences
            # is read again once its file can be read). And each row about to leave whose file is gone from the disk,
            # unless the user forgot it: a caller that can't see the library's missing items (the sentence dictionary
            # before its list was read, Generate without the library store) or a removed item met before the indexer
            # keeps it never takes its only sentences with it — a later list naming it reads it back from them.
            lost = [key for key in leaving if key not in gone and not os.path.exists(key)]
            have = texts.held(stamps=True) if (held or lost or None in signatures.values()) else {}
            keep_now = {}
            for key in listed:
                signature, row = signatures[key], existing.get(key)
                if row is None or ((key in current or key in put) and signature is not None):
                    continue
                if signature is not None and (wipe or (row["mtime"], row["size"]) != signature):
                    continue                                # read from its file below, its text kept then
                source = listed[key] if signature is not None else others.get(key)
                # Kept already, for this row's file (its (mtime, size)): kept again only when it was rebuilt and its
                # file can be read now. Kept for an older file (it came back changed, then went again): kept anew.
                if key in have and have[key][1:] == (row["mtime"], row["size"]) and not (
                        have[key][0] and read is not None and source and os.path.exists(source)):
                    continue
                keep_now[key] = self._text_of(cur, key, row, source, read)
            for key in lost:
                if key not in have or have[key][1:] != (existing[key]["mtime"], existing[key]["size"]):
                    keep_now[key] = self._text_of(cur, key, existing[key], others.get(key), read)
            texts.put(keep_now)

            if wipe:
                cur.execute("DELETE FROM files")
                cur.execute("DELETE FROM aggregate")
                cur.execute("DELETE FROM bound")
                existing, leaving, changed, phrased = {}, {}, True, True
            # What the files change in the aggregate, summed over the whole pass and written once at the end: a full
            # rebuild wrote a million rows (every word of every file) where the library has some 50,000 words.
            # Keys stay in the order they are first met, so new words are added in the same order as file by file.
            # Likewise the one-kanji words' uses as pieces (`pieces`, the bound table). Counted files only; a set-aside
            # file changing still changes the name tables' evidence (`changed`).
            delta, pieces = Counter(), Counter()

            # Removals — subtract vanished files (a file in no list).
            for key in leaving:
                row = existing.pop(key)
                if row["counted"] == COUNTED:
                    delta.subtract(_decode_counts(row["counts"]))
                    pieces.subtract(_decode_counts(row["bound"]))
                    phrased = True
                if row["counted"] != KEPT:
                    changed = True
                cur.execute("DELETE FROM files WHERE path=?", (key,))

            def write(key, mtime, size, result, row, flag):
                nonlocal changed, phrased
                counts = {k: n for k, n in result["counts"].items() if n > 0}
                bound = {k: n for k, n in (result.get("bound") or {}).items() if n > 0}
                total = sum(counts.values())
                if row is not None and row["counted"] == COUNTED:  # changed: subtract the stale contribution first
                    delta.subtract(_decode_counts(row["counts"]))
                    pieces.subtract(_decode_counts(row["bound"]))
                if flag == COUNTED:
                    delta.update(counts)
                    pieces.update(bound)
                if flag != KEPT or (row is not None and row["counted"] != KEPT):
                    changed = True
                if flag == COUNTED or (row is not None and row["counted"] == COUNTED):
                    phrased = True
                names = result.get("names")
                cur.execute(
                    "INSERT OR REPLACE INTO files(path, mtime, size, total, counts, tokens, names, bound, counted, "
                    "aside) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (key, mtime, size, total, _encode_counts(counts),
                     _encode_tokens(result["sentences"]), _encode_counts(names) if names is not None else None,
                     _encode_counts(bound) if bound else None, *_columns(flag)),
                )

            # Adds / changes — reuse unchanged (fast path), tokenize only the delta; a flag that moved moves the counts.
            todo, by_hand = [], []
            for key, realpath in listed.items():
                signature, row = signatures[key], existing.get(key)
                flag = COUNTED if key in current else ASIDE if key in put else KEPT
                if row is not None and (signature is None or (row["mtime"], row["size"]) == signature):
                    if row["counted"] != flag:          # unchanged, in another list: its counts move, no tokenizing
                        if COUNTED in (flag, row["counted"]):   # kept <-> aside: no count moves, the evidence does
                            phrased = True
                            counts, bound = _decode_counts(row["counts"]), _decode_counts(row["bound"])
                            if flag == COUNTED:
                                delta.update(counts)
                                pieces.update(bound)
                            else:
                                delta.subtract(counts)
                                pieces.subtract(bound)
                        cur.execute("UPDATE files SET counted=?, aside=? WHERE path=?", (*_columns(flag), key))
                        changed = True
                    continue
                if signature is not None:
                    if flag != KEPT:
                        todo.append((key, realpath, signature, row, flag))
                    else:
                        by_hand.append((key, realpath, signature, row, flag, None))
                    continue
                source = others.get(key)                # gone, not in the store: its file elsewhere, else its kept text
                if source:
                    try:
                        by_hand.append((key, source, file_signature(source), None, flag, None))
                        continue
                    except OSError:
                        pass
                kept_text = texts.get(key) if from_text is not None else None
                if kept_text is not None:
                    by_hand.append((key, None, kept_text[2:], None, flag, kept_text[:2]))
            tokenized = _tokenized([t[1] for t in todo], tokenize_file, workers)
            try:
                for (key, realpath, (mtime, size), row, flag), result in zip(todo, tokenized):
                    write(key, mtime, size, result, row, flag)
            finally:
                tokenized.close()                 # the pool's workers end here, before the tables below
            # A kept file, or one read back from elsewhere or from its kept text: here, its text kept as it is read.
            keep_read = {}
            for key, path, (mtime, size), row, flag, text_facts in by_hand:
                if text_facts is not None:
                    write(key, mtime, size, from_text(*text_facts), row, flag)
                    continue
                if read is not None and from_text is not None:
                    text, facts = read(path)
                    result = from_text(text, facts)
                else:
                    result = tokenize_file(path)
                    text, facts = _rebuilt_text(result["sentences"], result.get("names"))
                write(key, mtime, size, result, row, flag)
                if flag == KEPT or signatures[key] is None:
                    keep_read[key] = (text, facts, mtime, size)
            texts.put(keep_read)

            self._apply(cur, delta)
            cur.execute("DELETE FROM aggregate WHERE count <= 0")  # prune emptied words
            self._apply(cur, pieces, "bound")
            cur.execute("DELETE FROM bound WHERE count <= 0")
            if self.language == "ja" and (changed or cur.execute(
                    "SELECT 1 FROM meta WHERE key='names_tables'").fetchone() is None):
                self._update_names_tables(cur, build_signature)
            if build_signature is not None and (stored is None or stored[0] != build_signature):   # S19: once
                cur.execute("INSERT INTO meta(key, value) VALUES('build_sig', ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=?", (build_signature, build_signature))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            texts.close()
            raise
        if gone:
            # The sentences the user forgot leave the kept text too — only once the store's own change is committed.
            texts.drop([key for key in texts.held() if key in gone])
        texts.close()
        self._update_phrases(phrased)
        return self

    def _text_of(self, cur, key, row, source, read):
        """(text, facts, mtime, size) to keep for a listed file the store holds: read from `source` (its file, or where
        it is now) when it can be, else rebuilt from its cached sentences (`_rebuilt_text`)."""
        if source and read is not None:
            try:
                mtime, size = file_signature(source)
                text, facts = read(source)
                return text, facts, mtime, size
            except Exception:
                pass
        blob, names = cur.execute("SELECT tokens, names FROM files WHERE path=?", (key,)).fetchone()
        return (*_rebuilt_text(_decode_tokens(blob), _decode_counts(names) if names else None),
                row["mtime"], row["size"])

    # -- the phrase table (idioms and set phrases on the list, app/phrases.py) --------------------------------- #
    def _phrases_basis(self, revision):
        """What the set phrases are found in — (what every file's count shares: the phrase data and the matcher, the
        tokenizer's identity and the name tables' switches; what the name tables make of the words they join
        (`_names_reads`), and a digest of it). `file_tokens` reads the cached words through both."""
        from app import phrases
        reads = _names_reads(self.names_tables())
        base = json.dumps([revision, phrases.MATCHER_VERSION, self.get_meta("build_sig"),
                           list(_library_switches(self.language))])
        return base, reads, _digest(reads)

    def _update_phrases(self, changed):
        """Count the set phrases in the cached tokens — as a run reads them, the name tables applied — so the Rarity
        slider and automatic rarity count phrase rows as Generate lists them: each phrase's uses and spellings, and the
        uses its words that live only inside it give it (token_index.unknown_distribution). One tally per file, kept
        while the file reads the same: its (mtime, size), and what the name tables make of its name candidates
        (`_names_read_in`, looked at again only when what the tables join changed — not as their evidence grows) — so
        a change re-reads only the files it touched; all of them again when the phrase data, the tokenizer's identity
        or the switches change. Each file's matches are kept too, for Generate (`phrase_matches`). Counted files only,
        the table and the matches alike (a kept file is never Generate's to read). After the reconcile's own
        transaction: it reads what that wrote. Japanese with the switch on only; a failure leaves the
        last table (never fatal)."""
        if self.language != "ja" or not phrase_rows_on(self.language):
            return
        try:
            from app import phrase_data, phrases
            found = phrases.load()
            if found is None:
                return
            base, reads, names = self._phrases_basis(phrase_data.REVISION)
            state = json.dumps([base, names])
            if not changed and self.get_meta("phrases_state") == state:
                return                                  # nothing read differently since the last table
            held, held_matches, names_moved = {}, {}, True
            try:
                kept = json.loads(self.get_meta("phrase_files") or "{}")
                kept_matches = json.loads(self.get_meta("phrase_matches") or "{}")
                if kept.get("state") == base and kept_matches.get("state") == base:
                    held, held_matches = kept.get("files", {}), kept_matches.get("files", {})
                    names_moved = kept.get("names") != names or kept_matches.get("names") != names
            except ValueError:
                pass
            switches = _library_switches(self.language)
            files, matches = {}, {}
            for path, mtime, size, blob in self.conn.execute(
                    "SELECT path, mtime, size, names FROM files WHERE counted = 1").fetchall():
                entry, met = held.get(path), held_matches.get(path)
                same = (entry is not None and met is not None and entry[:2] == [mtime, size]
                        and met[:2] == [mtime, size])
                if same and names_moved:
                    same = entry[2] == _names_read_in(blob, reads, switches)
                if not same:
                    sentences, flat = self.file_tokens(path), []
                    entry = [mtime, size, _names_read_in(blob, reads, switches), *phrases.tally(sentences, found, flat)]
                    met = [mtime, size, len(sentences), flat]
                files[path], matches[path] = entry, met
            summed = phrases.table(((entry[3], entry[4]) for entry in files.values()), found)
            for key, value in (("phrase_files", {"state": base, "names": names, "files": files}),
                               ("phrase_matches", {"state": base, "names": names, "files": matches}),
                               ("phrases", summed), ("phrases_state", state)):
                self.set_meta(key, value if isinstance(value, str) else
                              json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        except Exception as e:
            print(f"Warning: could not count the set phrases for the Rarity slider: {e}")

    def phrase_matches(self, paths):
        """{path: (its sentences, [sentence, start, end, index, ...])} — the set phrases the last index found in each
        of `paths`' cached tokens, read as `file_tokens` reads them (`_update_phrases`), for the counted files whose
        count is current — none when the phrase data, the name tables' words or a switch changed since. Generate reads these
        instead of searching every sentence again (analyzer.main checks them against its tokens too)."""
        if self.language != "ja":
            return {}
        try:
            from app import phrase_data
            kept = json.loads(self.get_meta("phrase_matches") or "{}")
            base, _reads, names = self._phrases_basis(phrase_data.REVISION)
            if kept.get("state") != base or kept.get("names") != names:
                return {}
            rows = {path: [mtime, size] for path, mtime, size in self.conn.execute(
                "SELECT path, mtime, size FROM files WHERE counted = 1")}
            files, out = kept.get("files", {}), {}
            for path in paths:
                met = files.get(_norm(path))
                if met is not None and rows.get(_norm(path)) == met[:2]:
                    out[path] = (met[2], met[3])
            return out
        except Exception:
            return {}

    def phrase_table(self):
        """The phrase table the last index counted ({"rows", "taken"}, `_update_phrases`), or None — none with the
        switch off, for Chinese, or before the first index."""
        if self.language != "ja" or not phrase_rows_on(self.language):
            return None
        try:
            return json.loads(self.get_meta("phrases") or "null")
        except Exception:
            return None

    def phrase_tallies(self):
        """{path: ({phrase index: [uses, [spellings]]}, {"lemma|reading": uses given to a phrase})} — each counted
        file's `phrases.tally` as the last index kept it (`_update_phrases`), or None when one is missing or not
        current (the phrase data, the name tables' words or a switch changed since): the phrases one by one, which the
        summed table (by row) can't tell apart — E2.2's gate on the phrase rows (`arrivals.Gates`)."""
        if self.language != "ja":
            return None
        try:
            from app import phrase_data
            kept = json.loads(self.get_meta("phrase_files") or "{}")
            base, _reads, names = self._phrases_basis(phrase_data.REVISION)
            if kept.get("state") != base or kept.get("names") != names:
                return None
            files, out = kept.get("files", {}), {}
            for path, mtime, size in self.conn.execute("SELECT path, mtime, size FROM files WHERE counted = 1"):
                entry = files.get(path)
                if entry is None or entry[:2] != [mtime, size]:
                    return None
                out[path] = (entry[3], entry[4])
            return out
        except Exception:
            return None

    def phrase_sums(self):
        """`phrase_tallies` summed by phrase, as the arrivals gate reads it: ({phrase index: uses}, {phrase index:
        [spellings, as met]}) over the counted files, or None when `phrase_tallies` would be. Each file's tally is read
        on its own (SQLite's `json_each` over the kept table), so the whole table — hundreds of MB of Python objects at
        20,000 files, most of it left on the heap after — is never held at once (E2.3). Its reads are one read
        transaction (one snapshot, as `phrase_tallies`' one value was): an index committed between them never mixes a
        new table with the old check."""
        if self.language != "ja":
            return None
        own = not self.conn.in_transaction
        try:
            if own:
                self.conn.execute("BEGIN")
            from app import phrase_data
            base, _reads, names = self._phrases_basis(phrase_data.REVISION)
            head = self.conn.execute("SELECT json_extract(value, '$.state'), json_extract(value, '$.names') FROM meta "
                                     "WHERE key = 'phrase_files' AND json_valid(value)").fetchone()
            if head is None or head[0] != base or head[1] != names:
                return None
            counted = {path: [mtime, size] for path, mtime, size in self.conn.execute(
                "SELECT path, mtime, size FROM files WHERE counted = 1")}
            uses, spellings, seen = Counter(), {}, 0
            for path, text in self.conn.execute("SELECT j.key, j.value FROM meta, json_each(meta.value, '$.files') "
                                                "AS j WHERE meta.key = 'phrase_files'"):
                stamp = counted.get(path)
                if stamp is None:
                    continue                            # a file no longer counted: not the gate's
                entry = json.loads(text)
                if not isinstance(entry, list) or len(entry) < 5 or entry[:2] != stamp:
                    return None                         # stale, or a shape `phrase_tallies` couldn't read either
                seen += 1
                for index, (n, spelled) in entry[3].items():
                    uses[int(index)] += n
                    held = spellings.setdefault(int(index), [])
                    held.extend(x for x in spelled if x not in held)
            return (uses, spellings) if seen == len(counted) else None
        except Exception:
            return None
        finally:
            if own and self.conn.in_transaction:
                try:
                    self.conn.execute("COMMIT")
                except sqlite3.Error:
                    pass

    def names_records(self):
        """The name tables' evidence (counted and set-aside files'): their name records (`names.Record` data), in the
        table's order — what the name tables are computed from (`_update_names_tables`)."""
        return list(self.iter_names_records())

    def iter_names_records(self):
        """`names_records` one at a time: a reader that only sums them never holds every file's record at once."""
        for (blob,) in self.conn.execute(
                f"SELECT names FROM files WHERE names IS NOT NULL AND {self._evidence} ORDER BY rowid"):
            yield _decode_counts(blob)

    def names_record(self, path):
        """One file's name record (counted or kept), or None: not held, or not a Japanese store."""
        row = self.conn.execute("SELECT names FROM files WHERE path=?", (_norm(path),)).fetchone()
        return _decode_counts(row[0]) if row and row[0] else None

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

    def bound_counts(self):
        """{(lemma, reading): uses} — how often each one-kanji word stands as a piece of something else (年 in 三年,
        斬 in 斬魄刀: analyzer.bound_uses), counted as `word_counts` counts: with the name tables' joins. A one-kanji
        list word's uses on the list are its count less these."""
        rows = self.conn.execute("SELECT lemma, reading, count FROM bound").fetchall()
        bound = {(lemma, reading): n for lemma, reading, n in rows}
        for key, delta in self._names_bound().items():
            bound[key] = bound.get(key, 0) + delta
        return bound

    def unknown_frequencies(self, known_tuples=None, known_lemmas=None, ignore_set=None,
                            skip_singles=False):
        """Project the aggregate into the *learnable unknown* distribution (`unknown_distribution`), the set
        phrases' rows included when the switch is on (`phrase_table`), the one-kanji list words by their uses where
        they stand on their own (`bound_counts`)."""
        counts, total = self.word_counts()
        return unknown_distribution(counts, total, known_tuples, known_lemmas, ignore_set, skip_singles,
                                    self.language, self.phrase_table(),
                                    self.bound_counts() if skip_singles and self.language == "ja" else None)


def unknown_distribution(counts, total_tokens, known_tuples=None, known_lemmas=None, ignore_set=None,
                         skip_singles=False, language=None, phrases=None, bound=None):
    """{total_tokens, known_tokens, unknown:[(key,count)...], all_counts:[asc]} from the library's per-word counts
    ({(lemma, reading): uses}) and the learner's lists — the Rarity slider's numbers, and the analyzer's own when it
    decides a band without the store.

    Japanese, with the tokenizer's compound table: also "compounds" — ({key: uses}, {key: its parts}) for every
    compound the learner neither knows nor ignores that the library holds, and every such compound inside one — so
    each band can count a compound too rare for it toward its free parts, as Generate's list does
    (analyzer.LearningView; word_selection.preview). A part is kept only when a use could reach the list through
    it: free, and an unknown word that can be listed (a single character can't) or an unknown compound.

    `phrases`, the store's phrase table (`Store.phrase_table`), adds the set phrases as Generate lists them: each one
    the learner neither knows nor ignores as a whole (its Word, its reading, or a spelling on the lists) is an unknown
    of its own uses — unless its lemmas joined are a word the library holds — and a word that lives only inside its
    phrase counts without the uses it gives the phrase. Coverage and the known share stay the tokens'.

    `skip_singles` (Japanese, Settings' "List one-kanji words only when they're dictionary words" on): a one-character
    word counts as the list counts it (analyzer § One-character words) — a one-kanji dictionary word by its uses where
    it stands on its own, less `bound` ({(lemma, reading): uses as pieces of something else}, `Store.bound_counts`);
    any other one-character word, and those pieces, are nothing to learn (known tokens)."""
    known_tuples = known_tuples or set()
    known_lemmas = known_lemmas or set()
    ignore_set = ignore_set or set()
    bound = bound or {}
    table = {}
    single_kind = None
    if language == "ja":
        from app import analyzer
        table = analyzer.compound_parts()
        single_kind = analyzer.single_kind
    met = []                        # the unknown compounds the library holds
    taken = (phrases or {}).get("taken") or {}

    unknown, known_tokens = [], 0
    for key, n in counts.items():               # key = (lemma, reading), looked up as it is (this runs per word)
        lemma = key[0]
        if lemma in ignore_set or key in known_tuples or lemma in known_lemmas:
            known_tokens += n
            continue
        if skip_singles and len(lemma) == 1:
            # Only a one-kanji dictionary word is learnable, where it stands on its own; the rest still count toward
            # the total.
            if single_kind is None or single_kind(key) != 2:
                known_tokens += n
                continue
            pieces = bound.get(key, 0)
            if pieces:
                known_tokens += min(pieces, n)
                n -= pieces
                if n <= 0:
                    continue
        name = f"{lemma}|{key[1]}"                      # make_key
        unknown.append((name, n - taken[name] if name in taken else n))
        if key in table:
            met.append(key)
    rows = (phrases or {}).get("rows") or {}
    if rows:
        lemmas = {key[0] for key in counts}
        for name, row in rows.items():
            n = phrase_row_uses(name, row, lemmas, known_tuples, known_lemmas, ignore_set)
            if n is not None:
                unknown.append((name, n))

    # Most uses first, ties by key: two stable sorts in C, not a key tuple built per word.
    unknown.sort(key=itemgetter(0))
    unknown.sort(key=itemgetter(1), reverse=True)
    all_counts = sorted(counts.values())         # every word's uses, ascending (one sort, in C)
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
                elif skip_singles and len(lemma) == 1 and (single_kind is None or single_kind(part) != 2):
                    continue
                kept.append((lemma, reading, True))
                bases[make_key(lemma, reading)] = (counts.get(part, 0) - taken.get(make_key(lemma, reading), 0)
                                                   - (bound.get(part, 0) if skip_singles else 0))
            parts[key] = tuple(kept)
        freqs["compounds"] = (uses, parts, bases)
    return freqs


def phrase_row_uses(name, row, lemmas, known_tuples, known_lemmas, ignore_set):
    """A phrase row of the store's table (`name` "Word|Reading", `row` [uses, spellings]) as an unknown of the Rarity
    slider's (`unknown_distribution`): its uses — or None when it has none, its lemmas joined are a word the library
    holds (`lemmas`), or the learner knows or ignores it as a whole (its Word, its reading, a spelling)."""
    n, spelled = row
    word, _sep, reading = name.partition("|")
    if not n or word in lemmas or (word, reading) in known_tuples \
            or any(s in known_lemmas or s in ignore_set for s in (word, *spelled)):
        return None
    return n


def phrase_rows_on(language):
    """Settings -> "Idioms and set phrases on your list" (logic.phrase_rows, on by default), Japanese only — read fresh,
    as the build signature's switches are: the dashboard's slider must see a change as the next Generate will."""
    if language != "ja":
        return False
    try:
        from app import settings_manager
        return bool(settings_manager.load_settings()["logic"].get("phrase_rows", True))
    except Exception:
        return False


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
    """(recurring, kanji, terms): which of the library's name tables apply — Japanese only, as the run's settings
    say."""
    if language != "ja":
        return (False, False, False)
    try:
        from app import analyzer
        return tuple(bool(analyzer.LOGIC.get(key, True))
                     for key in ("names_recurring", "names_kanji", "names_work_terms"))
    except Exception:
        return (False, False, False)


def _holds_a_term(spelling, terms):
    """Does a recorded run of one-kanji tokens (`spelling`) hold a stretch the terms table (`terms`) names? Any stretch
    of 2+ of its pieces may be one, once other names have taken theirs."""
    return bool(terms) and any(spelling[start:end] in terms for start in range(len(spelling) - 1)
                               for end in range(start + 2, len(spelling) + 1))


def _names_reads(tables):
    """What the library's name tables make of the runs they join: {kind: {spelling: [lemma, reading, orth]}} — without
    their stickiness and evidence, which move with nearly every new file and change no word (names.choose asks only
    whether a table holds a spelling)."""
    return {kind: {spelling: entry[1:] for spelling, entry in table.items()}
            for kind, table in (tables or {}).items() if kind in ("k", "j", "w") and isinstance(table, dict)}


def _names_read_in(blob, reads, switches):
    """What the name tables (`_names_reads`) make of one file's recorded name candidates (its `names` column), as a
    short digest — each one a table holds, a term inside a run of one-kanji words included, with the word it becomes:
    the file's cached words read differently only when this does. "" when none is held."""
    recurring, kanji, terms = switches
    if not blob or not (recurring or kanji or terms):
        return ""
    held = _names_held(_decode_counts(blob).get("s", []), reads, switches)
    return _digest(held) if held else ""


def _names_held(spans, reads, switches):
    """What the name tables (`_names_reads`) make of one file's recorded name candidates (`spans`, its record's "s"),
    with the switches (recurring, kanji, terms) set so: [[kind, spelling, [lemma, reading, orth]], ...], sorted — each
    one a table holds, a term inside a run of one-kanji words included, with the word it becomes. All that the tables
    decide of the file's joins: `names.choose` asks only whether a table holds a spelling, and makes it that word."""
    recurring, kanji, terms = switches
    held = set()
    for span in spans:
        kind, spelling = span[5], span[6]
        if kind == "w":
            if terms:
                table = reads.get("w", {})
                held.update(("w", spelling[a:b]) for a in range(len(spelling) - 1)
                            for b in range(a + 2, len(spelling) + 1) if spelling[a:b] in table)
        elif ((kind == "k" and recurring) or (kind == "j" and kanji)) and spelling in reads.get(kind, {}):
            held.add((kind, spelling))
    return sorted([kind, spelling, reads[kind][spelling]] for kind, spelling in held)


def _digest(value):
    """A short fingerprint of a JSON-able `value`."""
    return hashlib.sha1(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


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
    only the band); Japanese one-character words count as the list counts them, by Settings' "List one-kanji
    words only when they're dictionary words" (`singles_rule`). None for an empty store."""
    if not store.has_tokens():
        return None
    return store.unknown_frequencies(**preview_lists(store, language, user_files_dir, script))


def preview_lists(store, language, user_files_dir, script="asis"):
    """The learner's lists as `preview_frequencies` counts by them: {known_tuples, known_lemmas, ignore_set,
    skip_singles} — `unknown_frequencies`' (and `unknown_distribution`'s) keyword arguments."""
    cached = store.get_cached_known(known_signature(os.path.join(user_files_dir, "KnownWord.json"), script))
    if cached is not None:
        known_tuples, known_lemmas = cached
    else:
        known_tuples, known_lemmas = None, preview_known_approx(user_files_dir, language, script)
    return {"known_tuples": known_tuples, "known_lemmas": known_lemmas,
            "ignore_set": preview_ignore_set(user_files_dir, language, script),
            "skip_singles": language == "ja" and singles_rule()}


def prepare_preview(language, user_files_dir):
    """Decode, ahead of the Rarity slider's first refresh, what that refresh would otherwise decode before it counts:
    the analyzer's compound table (`unknown_distribution`'s compounds) and one-kanji words, and KnownWord.json's
    IGNORED entries (`ignored_entries`). Each is decoded once per process, by whichever caller asks first, and kept as
    decoded — so nothing here changes a number. The dashboard calls it on a background thread as its window opens
    (MasterDashboardApp._prepare_preview). Never fatal."""
    try:
        if language == "ja":
            from app import analyzer
            analyzer.compound_parts()
            analyzer.single_kind(("手", "テ"))      # a one-kanji word: its table is read on the first one asked
        ignored_entries(user_files_dir, language)
    except Exception:
        pass


def singles_rule():
    """Settings -> "List one-kanji words only when they're dictionary words" (exclude_single, on by default): the
    analyzer's rule for Japanese one-character words (analyzer § One-character words) — off lists every one. Read
    fresh, as the build signature's switches are: the dashboard's slider must see a change as the next Generate
    will."""
    try:
        from app import settings_manager
        return bool(settings_manager.load_settings().get("exclude_single", True))
    except Exception:
        return True


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
_KNOWN_READ = [None]    # ((the known cache's two values as stored), their tuples, their lemmas): Store.get_cached_known


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
    config change invalidates stale tokens. What varies at runtime: Chinese `script`
    conversion, the sentence boundaries settings.json sets — they decide
    where every file splits — what a Japanese book's kana in parentheses become, whether a
    katakana name is one word (logic.names_katakana), whether a phrase or a title is
    (logic.phrases_and_titles) and whether a pronoun + a suffix is (logic.pronoun_bases; language is
    already isolated per DB; a tokenizer-LIBRARY change, or a change of a DEFAULT, is handled by
    bumping SCHEMA_VERSION, which rebuilds). Normalized so ja ignores a stray script. Chinese
    `reinforce` is retired: every store reads "reinforce=False", the string a store built as shipped
    already holds. Each suffix appears ONLY when it departs from the default — the script when
    converting, the boundaries when edited, the readings when not hiragana only, the katakana names,
    the phrases or the pronouns when off — so a store built as shipped keeps its exact old signature
    and upgrading never rebuilds anyone's index (spec I2)."""
    from app.zh_script import effective
    sig = f"{language}|reinforce=False"
    eff_script = effective(language, script)
    if eff_script != "asis":
        sig = f"{sig}|script={eff_script}"
    boundaries = _edited_boundaries(language)
    if boundaries is not None:
        sig = f"{sig}|boundaries={boundaries}"
    readings = _chosen_paren_readings(language)
    if readings is not None:
        sig = f"{sig}|paren_readings={readings}"
    for key in ("names_katakana", "phrases_and_titles", "pronoun_bases"):
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
    (logic.names_katakana: app/names.py), phrases and titles as one word (logic.phrases_and_titles) or pronouns with
    a suffix (logic.pronoun_bases) — for a Japanese store. Read fresh, as the boundaries are."""
    if language != "ja":
        return False
    try:
        from app import settings_manager
        return not settings_manager.load_settings()["logic"].get(key, True)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# The tokenizing pool (W1.3; the window's spec 04 §4.2; research/11, 11-W3: 3.3× on 4 workers, 67 MB each)
# --------------------------------------------------------------------------- #
# The indexer tokenizes the changed files in worker processes when there are enough of them to pay for the workers'
# start: each worker builds the same tokenizer from the parent's settings, the results come back in the files' order
# (never as they finish), and only the parent writes the store. `index_pool_workers` in settings.json: None (the
# default) sizes it from the CPU count and the free memory, 0 is one process, N is N workers.
POOL_MIN_FILES = 64          # fewer changed files: one process (a worker's start costs about what 60 files do)
POOL_MAX_WORKERS = 4         # the laptop: 4 cores (research/11 §5)
POOL_WORKER_MB = 100         # measured 67 MB private per worker; the rest is headroom
POOL_BATCH_PER_WORKER = 8    # files handed out at a time per worker: what can wait for the writer is bounded
_POOL_WORKER = {}


def _free_memory_mb():
    """Physical memory free now, in MB (None when it can't be told)."""
    try:
        if os.name == "nt":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullAvailPhys // (1024 * 1024)
            return None
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)
    except Exception:
        return None


def pool_workers(n_files, setting=None, cpus=None, free_mb=None):
    """How many processes tokenize `n_files` changed files: 1 is this process alone. `setting`: settings.json's
    `index_pool_workers` (None = automatic: half the logical CPUs, at most 4, at most what a quarter of the free memory
    holds, and only from POOL_MIN_FILES files; N asks for N, never more than the CPUs, the files or what half the free
    memory holds)."""
    if n_files < 2:
        return 1
    if setting is not None:
        try:
            setting = int(setting)
        except (TypeError, ValueError, OverflowError):
            setting = None
    cpus = cpus if cpus is not None else (os.cpu_count() or 1)
    free_mb = free_mb if free_mb is not None else _free_memory_mb()
    if setting is not None:
        size = min(setting, n_files, cpus)
        if free_mb is not None:
            size = min(size, max(1, int(free_mb * 0.5) // POOL_WORKER_MB))
        return max(1, size)
    if n_files < POOL_MIN_FILES:
        return 1
    size = min(POOL_MAX_WORKERS, max(1, cpus // 2))
    if free_mb is not None:
        size = min(size, max(1, int(free_mb * 0.25) // POOL_WORKER_MB))
    return size if size >= 2 else 1


def _pool_start(language, reinforce, script, logic):
    """A worker's start: the parent's tokenizer settings, then the same tokenizer (`make_tokenizer`). A worker never
    outlives its parent: on Windows a killed indexer leaves its pool's pipe open, and the workers would wait on it, so
    each one watches the parent's process handle and ends with it."""
    import multiprocessing
    import threading
    parent = multiprocessing.parent_process()
    if parent is not None:
        def watch():
            parent.join()
            os._exit(1)
        threading.Thread(target=watch, name="pool-parent-watch", daemon=True).start()
    from app import analyzer
    analyzer.LOGIC.clear()
    analyzer.LOGIC.update(logic)
    _POOL_WORKER["tokenize"] = make_tokenizer(language, reinforce, script)


def _pool_tokenize(path):
    return _POOL_WORKER["tokenize"](path)


def _tokenized(paths, tokenize_file, workers):
    """Each path's tokenization, in `paths`' order: here, or in a pool of worker processes (see `reconcile`)."""
    spec = getattr(tokenize_file, "pool_spec", None)
    size = 1
    if spec is not None and len(paths) >= 2:
        if workers is None:
            from app import locks
            if locks.held_in_process("indexer"):
                try:
                    from app import settings_manager
                    setting = settings_manager.load_settings().get("index_pool_workers")
                except Exception:
                    setting = None
                size = pool_workers(len(paths), setting)
        else:
            size = pool_workers(len(paths), workers)
    if size <= 1:
        for path in paths:
            yield tokenize_file(path)
        return
    import copy
    import multiprocessing
    from app import analyzer
    print(f"Indexer: tokenizing {len(paths)} files in {size} processes.")
    context = multiprocessing.get_context("spawn")
    batch = size * POOL_BATCH_PER_WORKER       # results waiting for the writer: a bounded few, never the library
    with context.Pool(size, initializer=_pool_start, initargs=spec + (copy.deepcopy(analyzer.LOGIC),)) as pool:
        for start in range(0, len(paths), batch):
            for result in pool.imap(_pool_tokenize, paths[start:start + batch], chunksize=4):
                yield result


def make_tokenizer(language, reinforce=False, script="asis"):
    """Build the default `tokenize_file(path) -> {"sentences", "counts"}`, reusing the analyzer's
    real tokenizer + text extraction so the store matches what a run would produce.

    - `sentences`: the FULL tokenize_sentences output [(s_text, [(lemma,reading,surface),...]),...]
      (every token, so Generate's aggregation can reuse it verbatim).
    - `counts`: Counter('lemma|reading' -> n) over tokens whose lemma OR surface has target-language
      chars (mirrors the analyzer's file_total_words accounting) — the aggregate the preview reads.
    - Japanese, `bound`: Counter('lemma|reading' -> n) of the one-kanji words' uses that are pieces of something
      else as the file reads alone (analyzer.bound_uses) — the bound table the preview reads.
    """
    from app import analyzer

    # ja lemmas carry a gloss suffix the analyzer strips; match it so store lemmas == run lemmas.
    analyzer.SANITIZE_JA = (language == "ja")
    # Japanese: each file as it reads alone, its name candidates recorded beside it (app/names.py) — the library's
    # tables are applied as the cache is read (`Store.file_tokens`), so a new table needs no re-tokenizing.
    tok = analyzer.ChineseTokenizer(reinforce_segmentation=reinforce, script=script) \
        if language == "zh" else analyzer.JapaneseTokenizer(library=False)
    has_lang, extract, bound_uses = analyzer.has_target_language, analyzer.extract_text, analyzer.bound_uses
    lemma_in_language = {}      # lemma -> has_lang(lemma), asked once per word: the count below runs on every token

    def read_text(path):
        """(text, facts): the file's text as every run reads it, and what it says of itself (a transcript of
        auto-generated captions) — what the kept text keeps."""
        facts = {}
        return extract(path, language, facts), facts

    def tokenize_text(text, facts=None):
        """`tokenize_file`'s result for a file's text and facts (`read_text`) — a kept file read back in from its kept
        text gives exactly what its file gave."""
        from app import names
        facts = facts or {}
        record = names.Record() if language == "ja" else None
        if record is not None:
            record.auto = bool(facts.get("auto")) or facts.get("captions") in analyzer.AUTO_CAPTIONS
            sentences = list(tok.tokenize_sentences(text, names=record))
        else:
            sentences = list(tok.tokenize_sentences(text))
        counts, bound = Counter(), Counter()
        for s_text, s_tokens in sentences:
            for lemma, reading, surface, _orth in s_tokens:
                in_language = lemma_in_language.get(lemma)
                if in_language is None:
                    in_language = lemma_in_language[lemma] = has_lang(lemma, language)
                if in_language or has_lang(surface, language):
                    counts[make_key(lemma, reading)] += 1
            if record is not None:
                for i in bound_uses(s_text, s_tokens):
                    bound[make_key(s_tokens[i][0], s_tokens[i][1])] += 1
        result = {"sentences": sentences, "counts": counts}
        if record is not None:
            result["names"] = record.data()
            result["bound"] = bound
        return result

    def tokenize_file(path):
        return tokenize_text(*read_text(path))

    tokenize_file.pool_spec = (language, reinforce, script)      # a pool's worker builds the same tokenizer
    tokenize_file.read_text, tokenize_file.tokenize_text = read_text, tokenize_text   # kept files (reconcile)
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
