"""The window's search (W3.2 S4; the window's spec A2 #79–86, 05 §5.3): what *Search your library* finds, grouped as the
results overlay shows it. Qt-free; it runs on a worker holding its own store handle, never the window's thread.

- **`search(store, view, query, limit=6)`**: the store's `Store.search` (the folded keys: a title, its other titles —
  romaji among them — and each file's own title; Chinese read as Simplified) mapped onto the reader's `View` → groups
  in the overlay's order, **Current · Goal · New arrivals · Finished**, each in its own order (Current by its place,
  Goal by the tier's order, New arrivals as the tray shows them, Finished newest month first), at most `limit` hits a
  group (`Group.total` says how many matched). A row is a piece, so **a split show is listed once per piece**. Goal's
  pieces aren't in the view (it shows a strip), so Goal is read from the store for the titles the search found: one hit
  per title, as Goal's sheet tiles them.
- **A hit** (`Hit`): the row's key (Current's and Finished's `Row.key`, the tray's `Arrival.key`; Goal's `w<work id>`),
  its title, **the matched spans** in that title ((start, end) in its characters, for the lit text — none where only a
  file's name or another title held the query: a romaji title finds 星降る街の小さな工房 but lights nothing in it),
  **the where-line** (*#5 in Current* · *Goal · 12 episodes · next up: Ep 3* · *New arrivals · Ep 1–6* · *Finished ·
  March 2026*; a piece of a show split into several says its range first: *Ep 5–8 · #7 in Current*), its item ids,
  `can_play` (Current only: its next episode can be opened) and `can_top` (every hit but Current's first row).
- An empty or whitespace query, no view, or no hit → no groups.
- **`Searcher(opener, view)`**: one worker thread with its own handle (`opener.handle()` on that thread, as the reader
  opens its own); `ask(query, callback)` returns at once and the latest query wins — one asked while another runs is
  answered, the ones between are dropped. `callback(query, groups, ms)` is called on the worker (the window's bridge
  queues it). The window debounces (120 ms) before it asks.

Its words are the overlay's: `STRINGS` here, nothing in Qt.
"""
import threading
import time
from collections import namedtuple

from app.services import view_rows
from app.services.automation import Worker

LIMIT = 6                                   # hits shown a group (A2 #81)
GROUPS = ("current", "goal", "arrivals", "finished")

Hit = namedtuple("Hit", "key group title spans where item_ids work_id piece_id can_play can_top play_tip cover_title "
                        "accessible")
#   spans: ((start, end), …) in `title`'s characters, the parts the query lights; () when the title doesn't hold it
Group = namedtuple("Group", "kind label hits total")

STRINGS = {
    "groups": {"current": "Current", "goal": "Goal", "arrivals": "New arrivals", "finished": "Finished"},
    "in_current": "#{n} in Current",
    "goal": "Goal · {n} {units}", "goal_next": "Goal · {n} {units} · next up: {next}",
    "arrivals": "New arrivals · {line}", "arrivals_plain": "New arrivals",
    "finished": "Finished · {month}", "finished_plain": "Finished",
    "piece": "{range} · {where}",
    "acc_hit": "{title} · {where}",
}


# --- the lit text ------------------------------------------------------------------------------------------------- #
def spans(title, query, language=None):
    """Where the folded `query` sits in `title`, as ((start, end), …) in the title's own characters, by the store's
    one fold (`library_store.search_fold`: NFKC, case, katakana as hiragana, a whitespace run as one space, Chinese as
    Simplified). () when the title doesn't hold it (a romaji or a file-name match)."""
    from app import library_store
    key = library_store.search_fold(query, language)
    if not key or not title:
        return ()
    chars, at = [], []
    for i, ch in enumerate(title):
        folded = " " if ch.isspace() else library_store.search_fold(ch)
        for c in folded:
            if c == " " and (not chars or chars[-1] == " "):
                continue                                  # a whitespace run is one space, none leading
            chars.append(c)
            at.append(i)
    text = "".join(chars)
    if language == "zh" and text:
        from app.zh_script import to_simplified
        whole = to_simplified(text)                       # the whole title read at once, as the store keys it
        text = whole if len(whole) == len(text) else "".join((to_simplified(c) or c)[:1] for c in text)
    out, start = [], 0
    while True:
        k = text.find(key, start)
        if k < 0:
            break
        a, b = at[k], at[k + len(key) - 1] + 1
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
        start = k + len(key)
    return tuple(out)


# --- the groups --------------------------------------------------------------------------------------------------- #
def _range_of(media, episodes):
    return view_rows.range_text(media, [e.number for e in episodes if e.number is not None], len(episodes))


def _hit(key, group, title, query, language, where, item_ids, work_id, piece_id, can_play=False, can_top=True,
         play_tip="", cover_title=None):
    return Hit(key=key, group=group, title=title, spans=spans(title, query, language), where=where,
               item_ids=tuple(item_ids), work_id=work_id, piece_id=piece_id, can_play=can_play, can_top=can_top,
               play_tip=play_tip, cover_title=cover_title or title,
               accessible=STRINGS["acc_hit"].format(title=title, where=where))


def _goal(store, view, works, items, probe, query, language, limit):
    """Goal's hits from the store: each title found by its name (`works`) or by one of its files in Goal (`items`), in
    the tier's order (its first file's place), one hit a title. `probe`: more titles to look for in Goal only to say
    whether they have a piece there (a split show). → (hits, total, the titles with files in Goal among all asked)."""
    from app import library_store as ls
    conn = store.conn
    elsewhere = {e.id for r in view.rows for e in r.episodes} | {i for a in view.arrivals for i in a.item_ids} | \
        {e.id for m in view.finished for r in m.rows for e in r.episodes}
    listed = set(works)
    for chunk in _chunks([i for i in items if i not in elsewhere], 500):
        # by id (`+tier`: the tier only filters, never the index walked), each title once
        listed.update(w for (w,) in conn.execute(
            f"SELECT DISTINCT work_id FROM items WHERE id IN ({','.join('?' * len(chunk))}) AND +tier = 'goal'",
            chunk))
    listed.discard(None)
    asked = listed | set(probe)
    asked.discard(None)
    if not asked:
        return (), 0, set()
    first = []                                    # each title's first place in Goal (one row a title, by its index)
    for chunk in _chunks(sorted(asked), 500):
        # the titles' files walked (`items_work`), never all of Goal
        first += conn.execute(f"SELECT work_id, MIN(ord) FROM items WHERE +tier = 'goal' AND work_id IN "
                              f"({','.join('?' * len(chunk))}) GROUP BY work_id", chunk).fetchall()
    first.sort(key=lambda r: (r[1] or 0.0, r[0]))
    order = [w for w, _o in first if w in listed]
    shown = order[:limit]
    cols = ", ".join(ls.FEED_ITEM_FIELDS)
    by_work = {w: [] for w in shown}
    if shown:                                     # the files of the titles shown only
        for r in conn.execute(f"SELECT {cols} FROM items WHERE +tier = 'goal' AND work_id IN "
                              f"({','.join('?' * len(shown))}) ORDER BY ord, id", shown):
            r = dict(zip(ls.FEED_ITEM_FIELDS, r))
            by_work[r["work_id"]].append(r)
    wcols = ", ".join(ls.FEED_WORK_FIELDS)
    found = {r[0]: dict(zip(ls.FEED_WORK_FIELDS, r)) for r in conn.execute(
        f"SELECT {wcols} FROM works WHERE id IN ({','.join('?' * len(shown))})", shown)} if shown else {}
    hits = []
    for w in shown:
        files = by_work[w]
        row = view_rows._row(0, "goal", files, found, {}, {}, set(), set(), 20, finished=True)
        unit = view_rows._arrival_unit(row.media)
        one, many = view_rows.STRINGS["arr_units"][unit]
        n = len(files)
        nxt = next((e for e in row.episodes if not e.watched), None)
        where = STRINGS["goal_next" if n > 1 and nxt is not None else "goal"].format(
            n=view_rows.thousands(n), units=one if n == 1 else many, next=nxt.label if nxt is not None else "")
        hits.append(_hit(f"w{w}", "goal", row.title, query, language, where, [r["id"] for r in files], w, None,
                         cover_title=row.cover_title))
    return tuple(hits), len(order), {w for w, _o in first}


def _chunks(seq, n):
    seq = list(seq)
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def search(store, view, query, limit=LIMIT):
    """The results overlay's groups for `query` (see the module's doc): a tuple of `Group`, only those holding a hit.
    `store`: a handle of this thread (the searcher's); `view`: the reader's latest `View`."""
    if view is None or store is None or not (query or "").strip():
        return ()
    work_ids, item_ids = store.search(query)
    if not work_ids and not item_ids:
        return ()
    language = view.language
    works, items = set(work_ids), set(item_ids)

    def found(work_id, ids):
        return work_id in works or any(i in items for i in ids)

    current = [r for r in view.rows if found(r.work_id, (e.id for e in r.episodes))]
    arrivals = [a for a in view.arrivals if found(a.work_id, a.item_ids)]
    finished = [(m.label, r) for m in view.finished for r in m.rows if found(r.work_id, (e.id for e in r.episodes))]
    probe = {r.work_id for r in current[:limit]} | {a.work_id for a in arrivals[:limit]} | \
        {r.work_id for _l, r in finished[:limit]}
    goal_hits, goal_total, in_goal = _goal(store, view, works, items, probe, query, language, limit)

    # a title in several pieces (Current's rows, the tray's, Finished's, a piece in Goal): each piece names its range
    pieces_of = dict.fromkeys(in_goal, 1)
    for r in view.rows:
        pieces_of[r.work_id] = pieces_of.get(r.work_id, 0) + 1
    for a in view.arrivals:
        pieces_of[a.work_id] = pieces_of.get(a.work_id, 0) + 1
    for m in view.finished:
        for r in m.rows:
            pieces_of[r.work_id] = pieces_of.get(r.work_id, 0) + 1

    def split(work_id, where, media, episodes):
        if work_id is None or pieces_of.get(work_id, 0) < 2:
            return where
        return STRINGS["piece"].format(range=_range_of(media, episodes), where=where)

    current_hits = tuple(
        _hit(r.key, "current", r.title, query, language,
             split(r.work_id, STRINGS["in_current"].format(n=r.index), r.media, r.episodes),
             (e.id for e in r.episodes), r.work_id, r.piece_id, can_play=bool(r.can_play), can_top=r.index != 1,
             play_tip=r.play_tip, cover_title=r.cover_title)
        for r in current[:limit])
    arrival_hits = tuple(                          # the tray's line is the piece's range already (or its channel)
        _hit(a.key, "arrivals", a.title, query, language,
             STRINGS["arrivals"].format(line=a.line) if a.line else STRINGS["arrivals_plain"], a.item_ids, a.work_id,
             a.piece_id, cover_title=a.cover_title)
        for a in arrivals[:limit])
    finished_hits = tuple(
        _hit(r.key, "finished", r.title, query, language,
             split(r.work_id, STRINGS["finished_plain"] if label == view_rows.STRINGS["earlier"] else
                   STRINGS["finished"].format(month=label), r.media, r.episodes),
             (e.id for e in r.episodes), r.work_id, r.piece_id, cover_title=r.cover_title)
        for label, r in finished[:limit])

    made = {"current": (current_hits, len(current)), "goal": (goal_hits, goal_total),
            "arrivals": (arrival_hits, len(arrivals)), "finished": (finished_hits, len(finished))}
    return tuple(Group(kind, STRINGS["groups"][kind], made[kind][0], made[kind][1])
                 for kind in GROUPS if made[kind][0])


# --- the worker --------------------------------------------------------------------------------------------------- #
class Searcher:
    """The search's own worker (see the module's doc). `opener`: `library_store.StoreOpener`'s shape (its handle is the
    worker thread's); `view`: a callable giving the reader's latest `View` (`LibraryReader.view`)."""

    def __init__(self, opener, view, limit=LIMIT):
        self.opener = opener
        self.view = view
        self.limit = limit
        self._worker = Worker("library-search")
        self._lock = threading.Lock()
        self._asked = 0                             # the latest query's number: an older one still queued is dropped
        self.runs = 0                               # searches run (tests)

    def ask(self, query, callback):
        with self._lock:
            self._asked += 1
            n = self._asked
        return self._worker.put(self._run, n, query, callback)

    def idle(self, timeout=None):
        return self._worker.idle(timeout)

    def close(self):
        self._worker.put(self._close_handle)
        self._worker.close()

    def _run(self, n, query, callback):
        with self._lock:
            if n != self._asked:
                return                              # a newer query is queued behind this one
        t0 = time.perf_counter()
        groups = ()
        try:
            if (query or "").strip() and self.opener.check() == "store":
                groups = search(self.opener.handle(), self.view(), query, self.limit)
        except Exception:
            groups = ()                             # a read that fails finds nothing; the next keystroke asks again
        self.runs += 1
        ms = (time.perf_counter() - t0) * 1000
        try:
            callback(query, groups, ms)
        except Exception:
            pass                                    # a listener's fault never stops the worker

    def _close_handle(self):
        close = getattr(self.opener, "close", None)
        if close is not None:
            try:
                close()                             # this thread's handle, through the store's own close
            except Exception:
                pass
