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


def pairings(store):
    """{item_id: [record, …]} for every paired item (the record as hato wrote it)."""
    out = {}
    for item_id, text in store.conn.execute("SELECT item_id, pairing FROM pairings"):
        try:
            out.setdefault(item_id, []).append(json.loads(text))
        except ValueError:
            continue
    return out


def place(store, item_id, tier, before_id=None, after_id=None, source="user"):
    """Move one item (a drag), its events logged as `source`'s. Returns the store's Change, or None for a no-op."""
    return store.move([item_id], tier, before_id=before_id, after_id=after_id, by=source)


def finish(store, item_id, source="user"):
    """Move one item to *Finished* (the store's `graduated` tier), its event logged as `source`'s. Never touches known
    words or Anki: the store's `set_tier` moves no file and writes nothing else (✅ Q2-5, Q2-6)."""
    return store.set_tier([item_id], "graduated", by=source)
