# SPDX-License-Identifier: GPL-3.0-or-later
"""*Study its cards first* — the user's own pins, as the card groups every Junban run puts first (P2.2 row 2.2.3).

G1.6-10: an item the user pins (a finished show whose cards they still want to work through) has its still-new cards
go first in Anki's queue until studied; *Done with its cards* takes the pin off. Only the user ever pins (L2.2 §5.6:
`items.pinned`, written by the store's `pin` / `unpin` alone): no move, finish, Connect or Junban run does. ✅ E1.3-3:
none of it in 2.x — `connect.PINS` is False there and nothing here is read; the 3.0 line turns it on.

**An item's cards** (E1.1 03 §8, Kura's L2.2 §5.6): the store's `cards_of(item_ids)` (its Anki links and the notes
Connect made for it) ∪ the scoped deck's cards whose Anki Miner source names the item's file — **the one source-name
rule**, `source_names` (both of Anki Miner's forms: the old bare name and 3.5's `folder — name`; exact keys, never a
substring; HTML entities read as the characters they stand for), for the item's paired video (its pairing record's
`video_path`) and its own file. A key two titles of the library share (`Season 01 — 01`) names neither. A `MiscInfo`
with no time after ` @ ` (a Migaku note's hint) names nothing.

Pure apart from `read`'s one store read (read-only, `role="reader"`); no Tk, no settings file, no writes.
"""
from modules.junban import connect, source_names


def source_of(misc_info):
    """A card's Anki Miner source as a key (`source_names.card_key`), or None when `MiscInfo` isn't in its shape."""
    return source_names.card_key(misc_info)


def names_of(path, video_path=None):
    """Every key Anki Miner's source can carry for an item in its folder forms (`source_names.names_of(bare=False)`):
    these keys move cards in Anki (first, or taken out), so a bare name — `OVA`, another show's `Special 01` — never
    claims one."""
    return source_names.names_of(path, video_path, bare=False)


def _items(store):
    """`[(item_id, rel_path, work_id)]` — the store's items with their title (a key two titles share names neither;
    one title's two folders, or a copy beside its original, still name it)."""
    try:
        return store.conn.execute("SELECT id, rel_path, work_id FROM items").fetchall()
    except Exception:                               # (a store without titles: every item its own)
        return [(i, p, None) for i, p in store.conn.execute("SELECT id, rel_path FROM items")]


def _open_store(language):
    """The language's store, read-only, or None (no store yet, JSON mode)."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    return library_store.open_store(language, get_data_path(language), get_user_files_path(language), role="reader")


def read(language):
    """`(pins, notes, videos, shared)` for the run: `pins` = `[(item_id, rel_path, pinned_at)]` from the store's
    `pinned()`, the oldest first; `notes` = `{item_id: [note ids]}` from its `cards_of()`; `videos` =
    `{item_id: video_path}` from the pairing records; `shared` = the keys items of two or more titles of the library
    carry (they name no item). Empty when pins are off (2.x), there's no store, or the store reads no pins (a 2.x
    store has no `pinned()`). Never raises: a store that can't be read pins nothing this run."""
    if not connect.PINS:
        return [], {}, {}, set()
    try:
        store = _open_store(language)
        if store is None:
            return [], {}, {}, set()
        with store:
            pinned = getattr(store, "pinned", None)
            if pinned is None:
                return [], {}, {}, set()
            pins = [(p.item_id, p.rel_path, p.pinned_at) for p in pinned()]
            if not pins:
                return [], {}, {}, set()
            ids = [item_id for item_id, _path, _at in pins]
            cards_of = getattr(store, "cards_of", None)
            notes = cards_of(ids) if cards_of is not None else {}
            from app.connect import library
            records = library.pairings(store)
            rows = _items(store)
        videos = {}
        for item_id, item_records in records.items():
            for record in item_records or ():
                if isinstance(record, dict) and record.get("video_path"):
                    videos[item_id] = record["video_path"]
        work = {item_id: w for item_id, _path, w in rows}
        shared = source_names.shared_names({i: names_of(path, videos.get(i)) for i, path, _w in rows}, work.get)
        return pins, notes, {i: videos[i] for i in ids if i in videos}, shared
    except Exception:
        return [], {}, {}, set()


def groups(language, cards, notes_by_id, pinned=None):
    """`plan`'s `pins`: `[[card_id, …], …]`, one group per pin (`plan_rules.pin_groups`, the oldest first), each the
    cards in scope that are the group's items' — the store's notes for them, or an Anki Miner source naming one.
    `cards`: the run's gathered cards (`card_id`, `note`); `notes_by_id`: `{note_id: {"fields": {…}}}`. `pinned`: what
    `read` returns (read here when None). None when nothing is pinned."""
    pins, store_notes, videos, *rest = read(language) if pinned is None else pinned
    shared = rest[0] if rest else set()
    if not pins:
        return None
    from app import plan_rules
    path_of = {item_id: path for item_id, path, _at in pins}
    item_groups = plan_rules.pin_groups([(item_id, at) for item_id, _path, at in pins],
                                        place=lambda item_id: (path_of.get(item_id) or "", item_id))
    names = {item_id: names_of(path_of.get(item_id), videos.get(item_id)) - shared for item_id in path_of}
    out = _matched(item_groups, cards, notes_by_id, store_notes, names)
    return out if any(out) else None


def _matched(item_groups, cards, notes_by_id, store_notes, names):
    """`[[card_id, …], …]`, one per group of items: the cards in scope that are the group's items' — the store's notes
    for them (`store_notes`: {item_id: [note ids]}), or an Anki Miner source naming one (`names`: {item_id: {keys}})."""
    # Kyou-B: one walk over the cards whatever the number of groups (side by side hands every Current title in): each
    # card goes to every group whose notes hold it or whose items its source names — the groups' own lists as before
    by_note, by_name = {}, {}
    for g, items in enumerate(item_groups):
        for item_id in items:
            for note in store_notes.get(item_id) or ():
                by_note.setdefault(note, set()).add(g)
            for key in names.get(item_id, ()):
                by_name.setdefault(key, set()).add(g)
    out = [[] for _items in item_groups]
    for card in cards or ():
        note = card.get("note")
        groups = set(by_note.get(note, ()))
        if len(groups) < len(out):
            fields = ((notes_by_id or {}).get(note) or {}).get("fields") or {}
            source = source_of(fields.get("MiscInfo"))
            if source is not None:
                groups |= by_name.get(source, set())
        for g in sorted(groups):
            out[g].append(card["card_id"])
    return out


# --- Kyou-A: *New cards come from: Current's top two, side by side* (SCOPE §2; Sonic's answers 1–5, 2026-11-15) ---- #
def read_side(language):
    """The titles side by side for the run, read once: `(titles, notes, names)` — `titles` = the store's
    `side_by_side()` ([[item id, …], …]: Current's titles' items, every title holding a file to study — Kyou-B: the plan
    takes them two at a time; [] while it's off or there aren't two),
    `notes` = `{item_id: [note ids]}` (`cards_of`), `names` = `{item_id: {source keys}}` (a key two titles of the library
    share names neither, as a pin's). Empty `titles` when pins are off (2.x), there's no store, or the store has no
    such option. Never raises: a store that can't be read weaves nothing this run."""
    if not connect.PINS:
        return [], {}, {}
    try:
        store = _open_store(language)
        if store is None:
            return [], {}, {}
        with store:
            side = getattr(store, "side_by_side", None)
            titles = side() if side is not None else []
            if not titles:
                return [], {}, {}
            ids = [item_id for title in titles for item_id in title]
            cards_of = getattr(store, "cards_of", None)
            notes = cards_of(ids) if cards_of is not None else {}
            from app.connect import library
            records = library.pairings(store)
            rows = _items(store)
        videos = {}
        for item_id, item_records in records.items():
            for record in item_records or ():
                if isinstance(record, dict) and record.get("video_path"):
                    videos[item_id] = record["video_path"]
        work = {item_id: w for item_id, _path, w in rows}
        every = {i: names_of(path, videos.get(i)) for i, path, _w in rows}
        shared = source_names.shared_names(every, work.get)
        wanted = set(ids)
        return titles, notes, {i: every.get(i, set()) - shared for i in wanted}
    except Exception:
        return [], {}, {}


SIDE_WIDTH = 2                  # Kyou-B: `plan`'s `width` — the store's `SIDE_TITLES`, two titles take turns at a time


def side_groups(language, cards, notes_by_id, side=None):
    """`plan`'s `weave`: `[[card_id, …], …]`, Current's titles' cards in scope (every title holding a file to study, in
    Current's order — the plan takes them `SIDE_WIDTH` at a time, so a title with no card left hands its turn to the
    next: Kyou-B) by the pins' own matching (`_matched`: the store's notes, or an Anki Miner source naming one of the
    title's items). `side`: what `read_side` returns (read here when None). None while side by side is off, or no
    title has a card in scope."""
    titles, store_notes, names = read_side(language) if side is None else side
    if not titles:
        return None
    out = _matched(titles, cards, notes_by_id, store_notes, names)
    return out if any(out) else None


def record_side(store, report, by="connect"):
    """Kyou-C: after a run, by the caller holding a store it may write (Junban's own handle is read-only, as for
    `record`): the run's count of each side-by-side title's still-new cards (`report["stats"]["side_cards"]`:
    [[item ids, cards], …]) into the store (`Store.set_side_cards`) — the one rule the window, Connect's top N and
    Generate's order follow (`library_store.side_pair`), so they pick the titles Anki weaves. Nothing counted (side by
    side off, no store option): nothing written. Kyou-E: with the count's time (`stats["side_at"]`, when the run began
    reading Anki), when the run gave one. -> whether it was written."""
    side = ((report or {}).get("stats") or {}).get("side_cards")
    write = getattr(store, "set_side_cards", None)
    if not side or write is None:
        return False
    at = report["stats"].get("side_at")
    return bool(write([(ids, n) for ids, n in side], by=by, **({"at": at} if at else {})))
# --- end Kyou-A


# --- P4.1 L2: *Take its new cards out* (05 §5.7, D14; W1.2 01-scope fc) — the same matching as a pin's ---------- #
OUT_ACTION = "cards_out"        # the store's `anki_changes.action` for these records


def read_out(language, claims=False):
    """The run's view of the items whose new cards were taken out (the store's `cards_out()`), read once ->
    `{"out": [(item_id, rel_path)], "notes": {item_id: [note ids]}, "names": {item_id: {reduced names}},
    "kept_notes": {note ids}, "kept_names": {reduced names}, "back": [records], "held": [records]}` — `notes` /
    `names` an out item's cards by the store and by Anki Miner's source (`groups`' two rules); `kept_*` the same for
    every item still in the learning order (a pinned one included: a pin is the later click), so a card one of them
    claims stays in (T-3); `back` the open records of items back in the order, for the run to restore; `held` the open
    records of items still out (TF: their cards stay as they are, and a note they name is no unrecorded suspend).
    `claims` (TF fix 4): the claims are read even when nothing is out — Put back's look at a suspend no record names.
    `{}` when pins are off (2.x), there's no store, or nothing is out or owed back (and `claims` is off). Never
    raises: a store that can't be read changes nothing this run."""
    if not connect.PINS:
        return {}
    try:
        store = _open_store(language)
        if store is None:
            return {}
        with store:
            reader = getattr(store, "cards_out", None)
            if reader is None:
                return {}
            got = reader()
            if not got["out"] and not claims:
                return {"out": [], "back": got["back"], "held": []} if got["back"] else {}
            rows = _items(store)
            out_ids = [item_id for item_id, _path in got["out"]]
            gone = set(out_ids)
            kept_ids = [item_id for item_id, _path, _work in rows if item_id not in gone]
            notes = store.cards_of(out_ids + kept_ids)
            held = [r for r in store.anki_changes_of(out_ids) if r["action"] == OUT_ACTION] if out_ids else []
            from app.connect import library
            records = library.pairings(store)
        videos = {}
        for item_id, item_records in records.items():
            for record in item_records or ():
                if isinstance(record, dict) and record.get("video_path"):
                    videos[item_id] = record["video_path"]
        names = {item_id: names_of(path, videos.get(item_id)) for item_id, path, _work in rows}
        work = {item_id: w for item_id, _path, w in rows}
        shared = source_names.shared_names(names, work.get)
        return {"out": list(got["out"]), "notes": {i: list(notes.get(i) or ()) for i in out_ids},
                "names": {i: names.get(i, set()) - shared for i in out_ids},
                "kept_notes": {n for i in kept_ids for n in notes.get(i) or ()},
                "kept_names": {n for i in kept_ids for n in names.get(i, set())} - shared,
                "back": got["back"], "held": held}
    except Exception:
        return {}


def claimer(read):
    """T-3's rule for one note -> `claim(note, misc_info)`: `"kept"` when an item still in the learning order claims
    it (by the store, or by its Anki Miner source), else the out items that do, oldest first (a tuple; `()`: none).
    `read`: `read_out`'s."""
    by_note, by_name = {}, {}
    for item_id, notes in ((read or {}).get("notes") or {}).items():
        for note in notes:
            by_note.setdefault(note, set()).add(item_id)
    for item_id, names in ((read or {}).get("names") or {}).items():
        for name in names:
            by_name.setdefault(name, set()).add(item_id)
    kept_notes, kept_names = (read or {}).get("kept_notes") or set(), (read or {}).get("kept_names") or set()

    def claim(note, misc_info):
        source = source_of(misc_info)
        if note in kept_notes or (source is not None and source in kept_names):
            return "kept"
        items = set(by_note.get(note) or ())
        if source is not None:
            items |= by_name.get(source) or set()
        return tuple(sorted(items))
    return claim


def out_cards(cards, notes_by_id, read):
    """`{card_id: (item ids)}` — the run's cards that are a taken-out item's (`read`: `read_out`'s) and no other item's
    still in the learning order (T-3: a card such an item claims, by the store or by its source, stays in). A card two
    out items claim is recorded under each (TF fix 7, adversary S4): putting either back brings it back — the other
    item's record then finds it no longer suspended, so nothing is restored twice. `{}` when nothing is out."""
    if not read or not read.get("out"):
        return {}
    claim = claimer(read)
    out = {}
    for card in cards or ():
        note, card_id = card.get("note"), card.get("card_id")
        if not isinstance(card_id, int) or isinstance(card_id, bool):
            continue
        fields = ((notes_by_id or {}).get(note) or {}).get("fields") or {}
        items = claim(note, fields.get("MiscInfo"))
        if items and items != "kept":
            out[card_id] = items
    return out


def out_records(out, done, profile=None):
    """The store's records for what a run's *Take its new cards out* sent (`out`: `unlisted.plan_out`'s; `done`:
    `{"tag": [note ids], "suspend": [card ids]}` the run asked Anki for — TF fix 4, adversary S6: a batch that timed out
    after Anki applied it is recorded too; Put back reads each card again before it touches it) -> `[(item_id,
    "cards_out", [note ids], before, after)]` for `record_anki_changes`, one per item (a card two out items claim in
    each one's): `after` names the cards suspended and the notes tagged, the tag, and the Anki profile they're in (TF
    fix 5, D31: a card id is one collection's) — what *Put back* restores, never more."""
    if not out or not done:
        return []
    item_of, note_of = out.get("item_of") or {}, out.get("note_of") or {}
    suspended, tagged = set(done.get("suspend") or ()), set(done.get("tag") or ())
    by_item = {}
    for card_id, items in item_of.items():
        for item_id in (items if isinstance(items, (tuple, list, set, frozenset)) else (items,)):
            entry = by_item.setdefault(item_id, {"cards": [], "notes": set()})
            if card_id in suspended:
                entry["cards"].append(card_id)
            if note_of.get(card_id) in tagged:
                entry["notes"].add(note_of[card_id])
    rows = []
    for item_id in sorted(by_item):
        cards, notes = sorted(by_item[item_id]["cards"]), sorted(by_item[item_id]["notes"])
        if not cards and not notes:
            continue
        touched = sorted(set(notes) | {note_of[c] for c in cards if isinstance(note_of.get(c), int)})
        after = {"queue": -1, "suspended": cards, "tag": out.get("tag") or "", "tagged": notes}
        if isinstance(profile, str) and profile:
            after["profile"] = profile
        rows.append((item_id, OUT_ACTION, touched, {"queue": 0, "tagged": []}, after))
    return rows


def record(store, report, by="connect"):
    """After a run, by the caller holding a store it may write (Junban's own handle is read-only): what its *Take its
    new cards out* changed (`report["cards_out"]`) into `anki_changes`, and the records its *Put back* restored
    (`report["put_back"]`) closed. Whatever landed is recorded, a run that stopped part way too. `by`: the caller, as
    the store's command records it (TF fix 10: Connect's step "connect", the window's re-order host "replan").
    Returns `(record ids, records closed)`."""
    report = report or {}
    rows, back = report.get("cards_out") or [], report.get("put_back") or []
    ids = store.record_anki_changes(rows, by=by) if rows else []
    closed = store.mark_anki_reverted(back, by=by) if back else 0
    return ids, closed
# --- end P4.1 L2 ---
