"""Connect's thin adapter on the library store (P2.1): what `place`, `finish`, the placing rules, the inbox and the
start-up notice need from `app/library_store.py` that its API doesn't name yet.

The store is Kura's. Who made a placement goes through its own `by=` (✅ G1.3-5: another program's placement counts
like yours, its name recorded). What leans on its internals until its API names them (L2.2): the mine line, the log's
last id and the pairings, read with the store's own queries (`_mine_ids`, `_log_seq`, the `pairings` table).

Light (02 §5): the standard library and the store only.
"""
import json
from collections import namedtuple

READER = "connect"          # the placement log's reader for Connect (✅ G1.1-2: its watermark is set at switch-on)


def open_store(language, role="connect"):
    """The language's store, or None (no store yet, JSON mode, read-only)."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    return library_store.open_store(language, get_data_path(language), get_user_files_path(language), role=role)


def three_oh(store):
    """The 3.0 behaviour (New arrivals, one *Current* list, `finish`) is on: the store's `arrivals_on` switch."""
    return bool(store.meta().get("arrivals_on"))


def has_reader(store, name=READER):
    return f"reader:{name}" in store.meta()


def ensure_reader(store, name=READER):
    """Connect's watermark, set once — the first time anything runs with Connect on — so nothing placed before it is
    ever read (✅ G1.1-2). A no-op (and no write) once it exists."""
    if not has_reader(store, name):
        store.register_reader(name)


def switch_on(store, name=READER):
    """Connect switched on (again): its watermark at the log's end, so nothing placed while it was off is ever read
    (✅ G1.1-2, every switch-on). For the preview's switch (P3.1); a first switch-on is `ensure_reader`'s."""
    if not has_reader(store, name):
        store.register_reader(name)
    else:
        store.advance_reader(name, log_seq(store))


def mine_line(store):
    """The top N of Current's available items (`meta.mine_line`, default 20), in order."""
    from app import library_store
    with store._reading():
        n = store.meta().get("mine_line", library_store.MINE_LINE_DEFAULT)
        return store._mine_ids(n)


def counting(store, tier):
    """[item ids] of `tier` in the store's order, available on disk, that count — W-1's one rule
    (`library_store.counts_sql` with the library's `keep_watched`): a watched one while it's off has nothing left to
    mine, as the mine line itself (`Store._mine_ids`)."""
    from app import library_store
    with store._reading():
        rule = library_store.counts_sql(store._keep_watched())
        return [r[0] for r in store.conn.execute(
            f"SELECT id FROM items WHERE tier = ? AND availability = 'available' AND {rule} ORDER BY ord, id",
            (tier,))]


def counts(store, item):
    """Does this item (a `store.item` dict) count (W-1's `library_store.counts`, the library's `keep_watched`)?"""
    from app import library_store
    return library_store.counts(item.get("tier"), item.get("watched"), store._keep_watched())


def log_seq(store):
    """The placement log's last id (a reader caught up to it has read everything)."""
    with store._reading():
        return store._log_seq()


def mined_at(store, item_id):
    item = store.item(item_id)
    return None if item is None else item.get("mined_at")


def show_title(store, item_id):
    """The title of the show (its work) an item belongs to, or None (laptop round 8 #50: the cards' show tags)."""
    with store._reading():
        row = store.conn.execute("SELECT w.title FROM items i JOIN works w ON w.id = i.work_id WHERE i.id = ?",
                                 (item_id,)).fetchone()
    return row[0] if row and row[0] else None


def made_words_all(store):
    """Every word Connect has made a card for in this language's library, whatever the episode (N15, the store's
    `made_words`, keyed by the lemma; G1.3-4: a word made once is never made again automatically, even when its card
    was deleted) — empty while the table holds nothing (2.x: written from P2.4 on)."""
    if not store.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'made_words'").fetchone():
        return set()
    return {row[0] for row in store.conn.execute("SELECT DISTINCT word FROM made_words")}


def pairings(store):
    """{item_id: [record, …]} for every paired item (the record as hato wrote it)."""
    out = {}
    for item_id, text in store.conn.execute("SELECT item_id, pairing FROM pairings"):
        try:
            out.setdefault(item_id, []).append(json.loads(text))
        except ValueError:
            continue
    return out


def pairing_of(store, item_id):
    """The item's newest pairing record (hato's, as written), or None. A source folder's origin row (`src:…`, SRC B1)
    only when the item has no other — it never shadows hato's video path, ids and episode numbers — and read without
    the origin's size, time and sha256, which a re-copy rewrites: the pairing's version (`fit_check.version`) stays.
    Among origin rows, one naming a video first, then the oldest: an origin attached later (a moved original, the same
    bytes found again) never drops the video nor moves the version — but an origin whose original moved (D5: its
    record marked `moved_to`, `library_store._MOVED_ROW`) after every live one: the episode is read where it is now
    (its pairing's version moves once, so its fit is checked once at the new place). Never another version of the
    item's episode (LM1b: an origin flagged `version`, `library_store._VERSION_ROW`)."""
    from app import library_store
    origin = library_store._ORIGIN_ROW
    video_last = (f"CASE WHEN {origin} AND json_valid(p.pairing) THEN json_extract(p.pairing, '$.video_path') IS NULL "
                  "ELSE 1 END")
    row = store.conn.execute(f"SELECT content_key, pairing FROM pairings p WHERE item_id = ? AND NOT "
                             f"{library_store._VERSION_ROW} ORDER BY {origin}, {library_store._MOVED_ROW}, "
                             f"{video_last}, CASE WHEN {origin} THEN 0 ELSE paired_at END DESC, "
                             f"CASE WHEN {origin} THEN 0 ELSE rowid END DESC, paired_at, rowid LIMIT 1",
                             (item_id,)).fetchone()
    try:
        record = json.loads(row[1]) if row else None
    except ValueError:
        return None
    if isinstance(record, dict) and row[0].startswith(library_store.SOURCE_KEY):
        record = {k: v for k, v in record.items() if k not in library_store.SOURCE_STATS}
    return record


# D5 / MV-2 (PROVISIONAL): what the store knows of an episode's move, read beside its pairing — the store's alone, no
# disk (`runner.moved_video` / `runner.video_left` look at the disk after, outside the store's reads). `root`: the path
# of the source folder its origin was read from (its record's `root`), None for any other record; `was`: the videos its
# origins marked `moved_to` named, newest mark first — a mark is never trusted alone (Kura's MV-A5: the same bytes
# found elsewhere while the original was only briefly away), so while the live record's video is gone, one still on
# disk there is the episode's
Moved = namedtuple("Moved", "root was")
NOT_MOVED = Moved(None, ())


def moved_of(store, item_id, record):
    """The item's `Moved` (above) for its pairing `record` (`pairing_of`'s)."""
    from app import library_store
    root = None
    if isinstance(record, dict) and record.get("producer") == library_store.SOURCE_PRODUCER and \
            record.get("root") is not None:
        root = next((s["path"] for s in store.sources(all=True, counts=False) if s["id"] == record["root"]), None)
    was = []
    marked = (f"SELECT pairing FROM pairings p WHERE item_id = ? AND {library_store._ORIGIN_ROW} AND "
              f"{library_store._MOVED_ROW} AND NOT {library_store._VERSION_ROW} ORDER BY rowid DESC")
    for (text,) in store.conn.execute(marked, (item_id,)):
        try:
            path = json.loads(text).get("video_path")
        except (ValueError, AttributeError):        # a malformed record, or one that isn't an object: no video
            continue
        if isinstance(path, str) and path and path not in was:
            was.append(path)
    return Moved(root, tuple(was)) if root or was else NOT_MOVED


# --------------------------------------------------------------------------- #
# P4.1 row 4.1.3: asked mining (C2 — *Mine now*, *Mine this*, *Mine it too* are all the store's `ask_mining`)
# --------------------------------------------------------------------------- #
def asks(store):
    """{item_id: (mine_asked, mined_at)} of every item with an ask, read-only (`store.conn`, as `pairings`)."""
    return asks_in(store.conn)


def asks_in(conn):
    """`asks` on any connection to the store (the window's look opens it read-only), or None when it can't be read
    (locked, damaged, a store before the column): unknown, never "no asks" — read as none, every asked job would be
    dropped as undone (adversary AD-6)."""
    import sqlite3
    try:
        rows = conn.execute("SELECT id, mine_asked, mined_at FROM items WHERE mine_asked IS NOT NULL").fetchall()
    except sqlite3.Error:
        return None
    return {item_id: (asked_at, mined) for item_id, asked_at, mined in rows}


def unanswered(found):
    """[(item_id, asked_at)] of `asks` no receipt answers (the item's `mined_at` older than the ask, or none: C3 —
    a receipt at or after the ask answers it), the newest ask first."""
    from app.connect.ledger import stamp_key
    out = [(i, a) for i, (a, mined) in (found or {}).items() if mined is None or stamp_key(mined) < stamp_key(a)]
    return sorted(out, key=lambda p: (stamp_key(p[1]), p[0]), reverse=True)


def asked(store):
    """[(item_id, asked_at)]: the asks with no receipt newer than them, the newest first (RUNBOOK 4.1.3)."""
    return unanswered(asks(store))


def made_words_for(store, job):
    """The words a job's pick counts as made (never sent): every word Connect ever made (G1.3-4) — but for a job an
    ask made (*Mine this*, *Mine it too*, kind `asked`), only the words whose card the store still holds a note for:
    a word whose card you deleted is made again only when you ask (N15; *Mine now* moves a job first and makes
    nothing again, IK S1)."""
    from app.connect.ledger import ASKED
    if (job or {}).get("kind") != ASKED:
        return made_words_all(store)
    if not store.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'made_words'").fetchone():
        return set()
    return {row[0] for row in store.conn.execute("SELECT DISTINCT word FROM made_words WHERE note_ids NOT IN "
                                                 "('[]', '')")}


def store_id(store):
    """The store's identity (a new one when the library is set up again): a job is kept with it (P2.1 adversary
    #12)."""
    return store.meta().get("store_id")


# --------------------------------------------------------------------------- #
# P2.4: Connect's one store write per batch (S-R-6, G1.1-10)
# --------------------------------------------------------------------------- #
def record_batch(store, item_id, made, mined_at, batch=None):
    """A batch's receipt (N8, `mined_at`) and its made-words record (N15: `{word: [note id, …]}`) in **one short
    write**, as role `connect`'s command: the made-words table made inside the write before its rows (Kura's N15 note:
    `ADDED_TABLES_SQL`, no schema step), then the receipt joins the same transaction. A word recorded again gains its
    new note ids (G1.3-4: never made again automatically, whatever became of its card). Raises the store's `StoreBusy`
    when the window holds the write lock past the store's 5 s (the caller tries again later), `StoreReadOnly` when it
    can't be written. A word written moves `state_version` (P2.4 row 11, L3.3: a level job's batch has no receipt to
    move it, and the copy and the window read the step); a word whose note ids are all recorded already is not
    written again, and a level job's batch with nothing new takes no write at all (S19). The store rings its bell
    after the commit (L3.2, `_writing`): nothing to ring here."""
    from app import library_store
    if mined_at is None and _recorded(store, item_id, made):
        return                                  # a level job's batch with nothing new: no write lock taken (S19)
    at = mined_at or library_store._now()
    with store._command("receipt", by=READER) as cmd:
        for sql in library_store.ADDED_TABLES_SQL:
            store.conn.execute(sql)
        for word, note_ids in (made or {}).items():
            row = store.conn.execute("SELECT note_ids FROM made_words WHERE item_id = ? AND word = ?",
                                     (item_id, word)).fetchone()
            had = list(json.loads(row[0])) if row else []
            ids = had + [n for n in note_ids if n not in had]
            if row is not None and ids == had:
                continue                        # nothing new for this word: its row as it is
            store.conn.execute("INSERT OR REPLACE INTO made_words (item_id, word, note_ids, made_at, batch) "
                               "VALUES (?, ?, ?, ?, ?)", (item_id, word, json.dumps(ids), at, batch))
            cmd.touch()
        if mined_at is not None:                # a level job's batch keeps the item's first receipt
            store.receipt(item_id, mined_at)


def _recorded(store, item_id, made):
    """Is every word of `made` recorded for the item with all its note ids already (nothing to write)? Read outside
    the write lock (adversary L3.3 wiring #6)."""
    if not made:
        return True
    if not store.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'made_words'").fetchone():
        return False
    with store._reading():
        for word, note_ids in made.items():
            row = store.conn.execute("SELECT note_ids FROM made_words WHERE item_id = ? AND word = ?",
                                     (item_id, word)).fetchone()
            if row is None or any(n not in json.loads(row[0]) for n in note_ids):
                return False
    return True


# --------------------------------------------------------------------------- #
# P2.4 Part B: cards deleted in Anki (Sonic, *restart, the backlog's size*)
# --------------------------------------------------------------------------- #
def note_ids(store):
    """Every note id the store holds: the learner's own (`anki_links`, from the known-words sync and the window) and
    Connect's (`made_words`) -> a set."""
    out = {row[0] for row in store.conn.execute("SELECT DISTINCT note_id FROM anki_links")}
    if store.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'made_words'").fetchone():
        for (ids,) in store.conn.execute("SELECT note_ids FROM made_words"):
            try:
                out.update(int(n) for n in json.loads(ids))
            except (ValueError, TypeError):
                continue
    return out


def notes_gone(store, gone):
    """Tell the store these notes are gone from Anki: it takes them out of what reads *in Anki* (`anki_links`, the
    note ids in `made_words`, 3.0's `made_lines`) and keeps the made word (G1.3-4: never made again unless you ask).
    The store's half is Kura's (`Store.notes_gone`, L3.3, P2.4 row 2.4.14) -> the note ids it took out (nothing gone:
    the store isn't asked)."""
    if not gone:
        return []
    return store.notes_gone(sorted(gone), by=READER)


def unmake(store, item_id, note_ids, words=()):
    """*Undo this batch* (P2.5 row 2.5.5, ✅ P2.5-1): the undone notes out of the item's made words, in one short write
    as role `connect`'s command — a word left with no note is free again (its row goes: Connect may make it again),
    and so is one of `words` (the undone notes' words) whose row the deleted-card check already emptied; the item's
    receipt cleared when none of its made words is left -> the words freed. Nothing to change → nothing written
    (S19)."""
    gone = {int(n) for n in note_ids or ()}
    undone = set(words or ())
    if not gone or not store.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'made_words'"
                                          ).fetchone():
        return []

    def changes():
        out = {}
        for word, ids in store.conn.execute("SELECT word, note_ids FROM made_words WHERE item_id = ?", (item_id,)):
            try:
                had = [int(n) for n in json.loads(ids)]
            except (ValueError, TypeError):
                continue
            left = [n for n in had if n not in gone]
            if left != had or (not left and word in undone):
                out[word] = left
        return out

    with store._reading():
        if not changes():                   # nothing to change: no write lock taken (S19)
            return []
    with store._command("receipt", by=READER) as cmd:
        changed = changes()                 # read again under the write lock: a write meanwhile is never undone
        if not changed:
            return []
        for word, left in changed.items():
            if left:
                store.conn.execute("UPDATE made_words SET note_ids = ? WHERE item_id = ? AND word = ?",
                                   (json.dumps(left), item_id, word))
            else:
                store.conn.execute("DELETE FROM made_words WHERE item_id = ? AND word = ?", (item_id, word))
        cmd.touch()
        # the receipt goes once none of the item's cards is left in Anki (a word you deleted by hand keeps its
        # empty row — never made again, G1.3-4 — and holds nothing of the item in Anki)
        if not store.conn.execute("SELECT 1 FROM made_words WHERE item_id = ? AND note_ids NOT IN ('[]', '') LIMIT 1",
                                  (item_id,)).fetchone():
            store.receipt(item_id, None)
    return sorted(w for w, left in changed.items() if not left)


def place(store, item_id, tier, before_id=None, after_id=None, source="user", explicit=None):
    """Move one item (a drag), its events logged as `source`'s (explicit as the store's `move` decides, unless
    `explicit` says). Returns the store's Change, or None for a no-op."""
    return store.move([item_id], tier, before_id=before_id, after_id=after_id, by=source, explicit=explicit)


def finish(store, item_id, source="user", explicit=None):
    """Move one item to *Finished* (the store's `graduated` tier), its event logged as `source`'s. Never touches known
    words or Anki: the store's `set_tier` moves no file and writes nothing else (✅ Q2-5, Q2-6)."""
    return store.set_tier([item_id], "graduated", by=source, explicit=explicit)
