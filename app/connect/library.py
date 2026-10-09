"""Connect's thin adapter on the library store (P2.1): what `place`, `finish`, the placing rules, the inbox and the
start-up notice need from `app/library_store.py` that its API doesn't name yet.

The store is Kura's. Who made a placement goes through its own `by=` (✅ G1.3-5: another program's placement counts
like yours, its name recorded). What leans on its internals until its API names them (L2.2): the mine line, the log's
last id and the pairings, read with the store's own queries (`_mine_ids`, `_log_seq`, the `pairings` table).

Light (02 §5): the standard library and the store only.
"""
import json

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


def log_seq(store):
    """The placement log's last id (a reader caught up to it has read everything)."""
    with store._reading():
        return store._log_seq()


def mined_at(store, item_id):
    item = store.item(item_id)
    return None if item is None else item.get("mined_at")


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
    """The item's newest pairing record (hato's, as written), or None."""
    row = store.conn.execute("SELECT pairing FROM pairings WHERE item_id = ? ORDER BY paired_at DESC, rowid DESC "
                             "LIMIT 1", (item_id,)).fetchone()
    try:
        return json.loads(row[0]) if row else None
    except ValueError:
        return None


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
    with store._reading():
        rows = store.conn.execute("SELECT word, note_ids FROM made_words WHERE item_id = ?", (item_id,)).fetchall()
    changed = {}
    for word, ids in rows:
        try:
            had = [int(n) for n in json.loads(ids)]
        except (ValueError, TypeError):
            continue
        left = [n for n in had if n not in gone]
        if left != had or (not left and word in undone):
            changed[word] = left
    if not changed:
        return []
    freed = sorted(w for w, left in changed.items() if not left)
    with store._command("receipt", by=READER) as cmd:
        for word, left in changed.items():
            if left:
                store.conn.execute("UPDATE made_words SET note_ids = ? WHERE item_id = ? AND word = ?",
                                   (json.dumps(left), item_id, word))
            else:
                store.conn.execute("DELETE FROM made_words WHERE item_id = ? AND word = ?", (item_id, word))
        cmd.touch()
        if not store.conn.execute("SELECT 1 FROM made_words WHERE item_id = ? LIMIT 1", (item_id,)).fetchone():
            store.receipt(item_id, None)
    return freed


def place(store, item_id, tier, before_id=None, after_id=None, source="user", explicit=None):
    """Move one item (a drag), its events logged as `source`'s (explicit as the store's `move` decides, unless
    `explicit` says). Returns the store's Change, or None for a no-op."""
    return store.move([item_id], tier, before_id=before_id, after_id=after_id, by=source, explicit=explicit)


def finish(store, item_id, source="user", explicit=None):
    """Move one item to *Finished* (the store's `graduated` tier), its event logged as `source`'s. Never touches known
    words or Anki: the store's `set_tier` moves no file and writes nothing else (✅ Q2-5, Q2-6)."""
    return store.set_tier([item_id], "graduated", by=source, explicit=explicit)
