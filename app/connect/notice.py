"""The start-up notice (P2.1 row 2.1.7): items another program registered while Surasura was closed, named once in the
window's bottom bar when it opens — "3 episodes arrived from hato while Surasura was closed" — from the placement log;
and, once, when Connect lost track of the library's moves (✅ P2.1-3: the 2.x preview's word for 3.0's *Needs you*).

The log is read as its own reader, `window-notice`: set the first time the window opens with Connect on, moved to the
log's end each time the window opens (after naming what arrived) and when it closes (so what arrived while it was open
is never named again). Only with Connect's preview on: with it off the window imports nothing from here.
"""
import datetime

from app.connect import library

READER = "window-notice"
PEOPLE = ("user", "undo")       # placements a person made in the window: never "arrived"


def _arrived(store, rows):
    """{program: number of items} for the items another program added since the reader's last move: a `placed` event
    that isn't a person's or a placing rule's, of an item added no earlier than a second before the first event read
    (an add and its event share one transaction: microseconds apart). Another program's move of an item the user
    already had is no arrival."""
    seen, out = set(), {}
    first = min((r[6] for r in rows), default=None)
    if first is None:
        return out
    since = (datetime.datetime.strptime(first[:19], "%Y-%m-%dT%H:%M:%S")
             - datetime.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S")
    for _id, item_id, kind, by, _explicit, _version, _at in rows:
        if kind != "placed" or by in PEOPLE or str(by).startswith("rule:") or item_id in seen:
            continue
        seen.add(item_id)
        item = store.item(item_id)
        if item is None or (item.get("added_at") or "") < since:
            continue
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


def _lost_track(language):
    """Connect's gaps not yet named (✅ P2.1-3) -> their line, marked named; None when there's none. The ledger is only
    read when it exists: the window never makes one."""
    import os
    from app.connect import ledger as ledger_module
    if not os.path.exists(ledger_module.path()):
        return None
    with ledger_module.Ledger() as ledger, ledger.transaction():
        gaps = ledger.gaps(language, unnoticed=True)
        if not gaps:
            return None
        ledger.mark_noticed([g["id"] for g in gaps])
    count = len({i for g in gaps for i in g["items"]})
    since, until = gaps[0]["since"], gaps[-1]["until"]
    span = f"from {since[:10]} to {until[:10]}" if since else f"until {until[:10]}"
    noun = "episode" if count == 1 else "episodes"
    have = "has" if count == 1 else "have"
    return f"Connect lost track of your moves {span}: {count} {noun} in the top 20 {have} no cards"


def at_open(language):
    """On a worker when the window opens -> the line to show, or None. Moves the reader to the log's end."""
    store = library.open_store(language, role="window")
    if store is None:
        return None
    with store:
        if not library.has_reader(store, READER):
            store.register_reader(READER)           # the first session with Connect on: from now on
            arrived = {}
        else:
            rows, gap = store.read_events(READER)
            arrived = {} if gap else _arrived(store, rows)
            _catch_up(store, gap)
    lines = [line for line in (_words(arrived) if arrived else None, _lost_track(language)) if line]
    return " · ".join(lines) or None


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
