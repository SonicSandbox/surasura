"""The folder a press opens for some of the library's items (a7, DIAGNOSIS 7; Sonic: "should be opening the location of
the content itself unless it doesn't exist") — one rule for every *Open its folder* (Current, Finished, New arrivals,
Goal) and the pickers that look for a video (Needs you's *Choose file…*, a row's *Link…*). Qt-free; read on a worker
(a drive may be slow or gone).

The first of these that exists:
1. an item's original's folder (where it is read from; a book's part `<book>.epub#<n>`: the EPUB's folder);
2. its paired video's folder;
3. the nearest existing folder above an original, never above the source folder it is read from (a show's folder
   gone: the folder it was in; the source itself gone, or no source — + Add's, Extract's: no climb);
4. the stored copy's folder in the library, else the nearest existing folder above it inside the library;
5. the library itself.

The originals are the store's live origin records (`Store.origins(items=…)`: never another version's, never one whose
file moved on). An item with none (Surasura 2's, a sample) is its stored copy: 4. Relinking a gone copy (Needs you's
*Choose file…* for a file gone, *Choose a folder…*) is not this: the store takes only a file inside the library
(`Store.relink`), so those pickers start at the stored copy's side (`library_side`).
"""
import os


def _isdir(path):
    try:
        return bool(path) and os.path.isdir(path)
    except (OSError, ValueError):
        return False


def _nearest(folder, stop=None):
    """`folder`, else the nearest existing folder above it — never above `stop` (when given) — or None."""
    stop = os.path.normcase(os.path.abspath(stop)) if stop else None
    while folder:
        at = os.path.normcase(os.path.abspath(folder))
        if stop is not None and at != stop and not at.startswith(stop.rstrip(os.sep + "/") + os.sep):
            return None
        if _isdir(folder):
            return folder
        up = os.path.dirname(folder)
        if up == folder:
            return None
        folder = up
    return None


def library_side(data_dir, rels=(), folders=()):
    """4 and 5 alone: the first stored copy's folder (`rels`: files; `folders`: folders — both data-folder relative), or
    the nearest one above it inside the library, else the library."""
    wanted = [os.path.dirname(os.path.join(data_dir, *rel.split("/"))) for rel in rels if rel]
    wanted += [os.path.join(data_dir, *[p for p in folder.split("/") if p]) for folder in folders if folder]
    for folder in wanted:
        found = _nearest(folder, stop=data_dir)
        if found:
            return found
    return data_dir


def originals(store, ids):
    """[Origin] of `ids`, in their order (each item's records in key order), live ones only; [] without a store or when
    it can't be read."""
    if store is None or not ids or not hasattr(store, "origins"):
        return []
    try:
        found = store.origins(items=list(ids))
    except Exception as e:                          # noqa: BLE001 — an unreadable store: the library's side
        print(f"Open its folder: the originals couldn't be read: {e!r}")
        return []
    by = {}
    for o in found.values():
        if not o.version and not getattr(o, "moved_to", None) and isinstance(o.origin, str):
            by.setdefault(o.item_id, []).append(o)
    return [o for i in dict.fromkeys(ids) for o in by.get(i, ())]


def _roots(store, origins):
    """{root id: its folder} of the sources `origins` are read from (stopped ones too); {} when it can't be read."""
    if not any(o.root is not None for o in origins) or not hasattr(store, "sources"):
        return {}
    try:
        return {s["id"]: s["path"] for s in store.sources(all=True, counts=False) if s.get("path")}
    except Exception as e:                          # noqa: BLE001 — no climb then
        print(f"Open its folder: the sources couldn't be read: {e!r}")
        return {}


def find(store, data_dir, ids=(), rels=(), folders=()):
    """The folder to open for items `ids` (their stored copies: `rels` files, `folders` folders, data-folder relative):
    the module's rule. Each folder is looked at once, however many parts share it (a slow or offline share: A7S-4)."""
    origins = originals(store, ids)
    own = [os.path.dirname(o.origin) for o in origins]           # `dirname` takes a part's `#<n>` off with its name
    beside = own + [os.path.dirname(o.video_path) for o in origins if isinstance(o.video_path, str) and o.video_path]
    for folder in dict.fromkeys(f for f in beside if f):
        if _isdir(folder):
            return folder
    roots = _roots(store, origins)
    for folder, root in dict.fromkeys((f, roots.get(o.root)) for f, o in zip(own, origins) if f):
        found = _nearest(os.path.dirname(folder), stop=root) if root else None
        if found:
            return found
    return library_side(data_dir, rels, folders)


def read(opener, data_dir, ids=(), rels=(), folders=()):
    """(A worker.) `find` through a store handle of this worker's own (the library's opener, closed after — as Needs
    you's reads are); no store to read: the library's side."""
    store = None
    if opener is not None and getattr(opener, "mode", None) == "store" and hasattr(opener, "handle"):
        try:
            store = opener.handle()
        except Exception as e:                      # noqa: BLE001
            print(f"Open its folder: the library couldn't be opened: {e!r}")
    try:
        return find(store, data_dir, ids, rels, folders)
    finally:
        close = getattr(opener, "close", None) if store is not None else None
        if close is not None:
            try:
                close()
            except Exception:
                pass


def opener_of(win):
    """The library's opener a window reads through (`services.library.opener`), or None."""
    return getattr(getattr(getattr(win, "services", None), "library", None), "opener", None)
