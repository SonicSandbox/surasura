"""The start-up notice (P2.1 row 2.1.7): items another program registered while Surasura was closed, named once in the
window's bottom bar when it opens — "3 episodes arrived from hato while Surasura was closed" — from the placement log.

The log is read as its own reader, `window-notice`: set the first time the window opens with Connect on, moved to the
log's end each time the window opens (after naming what arrived) and when it closes (so what arrived while it was open
is never named again). Only with Connect's preview on: with it off the window imports nothing from here.
"""
from app.connect import library

READER = "window-notice"
PEOPLE = ("user", "undo")       # placements a person made in the window: never "arrived"


def _arrived(rows):
    """{program: number of items} for the items another program added (a `placed` event that isn't a person's or a
    placing rule's)."""
    seen, out = set(), {}
    for _id, item_id, kind, by, _explicit, _version, _at in rows:
        if kind != "placed" or by in PEOPLE or str(by).startswith("rule:") or item_id in seen:
            continue
        seen.add(item_id)
        out[by] = out.get(by, 0) + 1
    return out


def _words(arrived):
    total = sum(arrived.values())
    noun = "episode" if total == 1 else "episodes"
    verb = "arrived"
    if len(arrived) == 1:
        (program, _n), = arrived.items()
        return f"{total} {noun} {verb} from {program} while Surasura was closed"
    parts = ", ".join(f"{n} from {program}" for program, n in sorted(arrived.items(), key=lambda kv: (-kv[1], kv[0])))
    return f"{total} {noun} {verb} while Surasura was closed: {parts}"


def at_open(language):
    """On a worker when the window opens -> the line to show, or None. Moves the reader to the log's end."""
    store = library.open_store(language, role="window")
    if store is None:
        return None
    with store:
        if not library.has_reader(store, READER):
            store.register_reader(READER)           # the first session with Connect on: from now on
            return None
        rows, gap = store.read_events(READER)
        arrived = {} if gap else _arrived(rows)
        _catch_up(store, gap)
    return _words(arrived) if arrived else None


def _catch_up(store, gap=False):
    """The reader to the log's end — a write only when there is something to pass (each open needn't write)."""
    end = library.log_seq(store)
    if gap or store.meta().get(f"reader:{READER}") != end:
        store.advance_reader(READER, end)


def at_close(language):
    """When the window closes: what arrived while it was open was seen there, never named at the next start."""
    store = library.open_store(language, role="window")
    if store is None:
        return
    with store:
        if library.has_reader(store, READER):
            _catch_up(store)
