# SPDX-License-Identifier: GPL-3.0-or-later
"""The show a card is ordered for: `Surasura::for::<show>` (laptop round 8 #50, LF4-3 = A).

Sonic (2026-10-22): "I'd add the show title it came from, and probably the show that it's targeted for in case the 2
are different right? One wouldn't change, the other would if it's shuffled." The show a card came from is fixed when
Connect mines it (`Surasura::from::<show>`, `app/connect/runfile.from_tag`). The show it's for moves with the order.
Each re-order that may act on your cards (one you start, or an automatic one with its actions on; never a
positions-only move) labels every card it places with the list by the show of the episode the journey meets its word
in. Only the notes whose label changed are written ("update only what changed"): one `removeTags` and one `addTags`
per show whose notes changed.

- **Which show:** the card's place on the journey, the file number of its word's first episode in study order (the
  list's `Sequence`; the library map's for a word the list cut off or a phrase). That file's item in the library store
  gives its work's title (`file_shows`). A card in scope the list doesn't place (not on your list, known, your own
  cards ahead of the rest) carries no `for` label: one it had comes off. A card that left the scope (studied, suspended
  by you) keeps the label it had: no run reads it any more.
- **Numbers and shows in one order:** a fast re-plan's numbers are the store's order as it stands; a run reading the
  last Generate's (the 順 window's) labels nothing while a move waits for the next Generate (`journey_pending`), so a
  label never names the show that moved into a file's place.
- **One note, one label:** a note with several cards in scope takes its earliest card's show.
- **Not an undo matter:** a label describes the order as it stands. A Restore that takes Junban's own tag off a note
  (`Surasura`) takes its children too, this label among them; the next re-order puts it back. Known from Anki never
  reads it (it reads suspensions).

Pure apart from `file_shows`' reads (the run's file list and the store, read-only). Light: the standard library.
"""
import os
import unicodedata

from app.connect.runfile import FOR_PREFIX, show_slug


_MEMO = {}


def file_shows(language, current=False):
    """[show title or None, …] by study-order file number (index 0 = file 1), as Generate numbers the files
    (`analyzer.resolve_found_files(..., missing=True)`, Generate's own list) — in the store's order as it stands, so a
    move re-labels at the next re-order (a fast re-plan's numbers are the new order's). None when the library can't be
    read, and while a move waits for the next Generate unless `current` (the caller's numbers are the store's order as it
    stands: a fast re-plan's): then no label is touched. Read again only when the store changed (its versions)."""
    try:
        from app import analyzer
        from modules.junban import pins
        store = pins._open_store(language)
    except Exception:
        return None
    if store is None:
        return None
    try:
        with store, store._reading():
            versions = store._versions()
            if not current and versions.get("analysed_order_version", 0) < versions.get("order_version", 0):
                return None             # round 2 B2: the numbers are the last Generate's, the order has moved since
            key = tuple(sorted(versions.items()))
            hit = _MEMO.get(language)
            if hit is not None and hit[0] == key:
                return hit[1]
            rows = store.conn.execute("SELECT i.rel_path, w.title FROM items i LEFT JOIN works w ON w.id = i.work_id"
                                      ).fetchall()
        found = analyzer.resolve_found_files(language, verbose=False, missing=True)
    except Exception:
        return None
    by_name = {}
    for rel, title in rows:
        rel = _norm(rel)
        by_name.setdefault(rel.rsplit("/", 1)[-1], []).append((rel, title))
    out = []
    for path, *_rest in found:
        path = _norm(path)
        hits = [title for rel, title in by_name.get(path.rsplit("/", 1)[-1], ())
                if rel and (path == rel or path.endswith("/" + rel))]
        out.append(hits[0] if len(set(hits)) == 1 and hits[0] else None)
    _MEMO[language] = (key, out)
    return out


def _norm(path):
    return os.path.normpath(str(path or "")).replace("\\", "/").lower()


def is_for_tag(tag):
    return _fold(tag).startswith(_fold(FOR_PREFIX))


def _fold(tag):
    """A tag as Anki compares tags: NFC, case folded (round 2 B5: an NFD title would flap remove-then-add)."""
    return unicodedata.normalize("NFC", str(tag)).casefold()


def plan(cards, shows, notes):
    """`{"add": {tag: [note ids]}, "remove": {tag: [note ids]}, "counts": {"labelled", "changed"}}` — the `for`
    labels this order means, only where a note's label differs from what it carries. `cards`: the run's card dicts
    (`file`: the study-order file number their place came from, set by the planner; absent: not placed with the
    list); `shows`: `file_shows`' (None: the library couldn't be read, so nothing is planned); `notes`: `{note id:
    {"tags": [...]}}`."""
    if shows is None:
        return {"add": {}, "remove": {}, "counts": {"labelled": 0, "changed": 0}}
    first = {}
    for card in cards or ():
        note = card.get("note")
        if not isinstance(note, int):
            continue
        number = card.get("file")
        number = number if isinstance(number, int) and 1 <= number <= len(shows or ()) else None
        if note not in first or (number is not None and (first[note] is None or number < first[note])):
            first[note] = number
    add, remove, labelled = {}, {}, 0
    for note, number in sorted(first.items()):
        slug = show_slug(shows[number - 1]) if number is not None and shows[number - 1] else ""
        wanted = FOR_PREFIX + slug if slug else None
        has = [t for t in (((notes or {}).get(note) or {}).get("tags") or ()) if is_for_tag(t)]
        if wanted:
            labelled += 1
        for tag in has:
            if wanted is None or _fold(tag) != _fold(wanted):
                remove.setdefault(tag, []).append(note)
        if wanted and not any(_fold(tag) == _fold(wanted) for tag in has):
            add.setdefault(wanted, []).append(note)
    changed = len({n for ids in list(add.values()) + list(remove.values()) for n in ids})
    return {"add": add, "remove": remove, "counts": {"labelled": labelled, "changed": changed}}


def has_work(planned):
    return bool((planned or {}).get("add") or (planned or {}).get("remove"))


def apply(url, planned, chunk=150):
    """Write the plan: each old label off, then each new one on (one request a show, in chunks) -> (notes changed,
    [(note id, why)] failures)."""
    from modules.junban import ankiconnect
    done, failures = set(), []
    for tag, notes in sorted(((planned or {}).get("remove") or {}).items()):
        ok, failed = ankiconnect.remove_tags(url, notes, tag, chunk=chunk)
        done |= set(ok or ())
        failures += list(failed)
    for tag, notes in sorted(((planned or {}).get("add") or {}).items()):
        ok, failed = ankiconnect.add_tags(url, notes, tag, chunk=chunk)
        done |= set(ok or ())
        failures += list(failed)
    return len(done), failures
