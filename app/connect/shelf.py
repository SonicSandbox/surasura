"""Connect's backlog and its shelf (P2.4 Part B rows 2.4.10–2.4.12; Sonic, 2026-10-07 *restart, the backlog's size*,
*Windows' change reports; Connect's card rules*, *the shelf*, *the swap-in*; 2026-10-08 *P2.4's six*, *the big gap*).

- **The cap** (`connect_backlog_cap`, default 300, "keep up to N Surasura cards waiting"): *waiting* = Connect's own
  notes (its tag `surasura::connect::<job>`), new, not suspended — one `findCards` (`waiting_count`). Connect tops up:
  it mines while fewer than N wait, checked before a job's first batch (never mid-episode), and waits (*Your N cards are waiting*) at the cap; as
  you study, the next look tops up. A whole episode at a time: one batch can take it over N by its own words. The
  learner's own cards never count and are never touched (they don't carry Connect's tag).
- **The shelf** (in 2.x too, ✅ P2.4-1): at the cap, once a run, Connect's waiting cards are ranked by Junban's order
  (the list's: a word's place on it, a word no longer listed behind every listed one) against the words the next batch
  needs. Only on **a big gap** — at least a quarter of the cap (`gap_needed`: 75 at 300, ✅ P2.4-2) of the waiting
  cards rank behind every word the batch needs — the lowest go to the shelf (suspended, tagged `surasura::shelf`),
  as many as make room for the batch, never more than rank behind it. **A pinned show's cards never** (✅ N7: "if
  they are pinned then they are at the front"). Nothing else moves a card on its own; nothing is ever deleted here.
- **Remove** (✅ N7): a finished show's "remove" = `shelve_item`: its never-seen Connect cards shelved now, undoable.
- **The swap-in** (✅ P2.4-5 ⭐): a shelved word one of the top 20 needs again comes back from the shelf (un-suspended,
  its tag taken off), never made again. Its card's line still from the journey (its show not finished or removed) →
  only that; from a finished or dropped show → also marked for 3.1's rewrite (Swap, P6.1), with the journey item that
  holds the word now (the ledger's `rewrites`). No media is removed here.
- **A shelved card you un-suspended in Anki** → its shelf tag taken off; it counts as waiting again.
- **The restore point**: every shelving is recorded in Connect's ledger (`shelf`, its run id) before Anki is
  written (adversary B #12); `restore(run)` puts every card of a run back (un-suspended, tag off) — the cards still
  suspended by the shelf only. **No 2.x window offers `restore` or `shelve_item` yet**: 3.0's window (Mado) does
  (adversary B #14); until then they are Connect's own and the tests'.
- **The tag is the note's**: taking a card off the shelf (the swap-in, a restore, a card you un-suspended) leaves
  the tag on a note whose other card is still shelved (review B #10, adversary B #13).

Every write holds Anki's write lock (`anki-writer`, Junban's writer) and asks `guiReviewActive` first (K88). Pure apart
from the `Anki` adapter it is handed (`AnkiConnectAnki` for the real one; tests hand a fake), the ledger and the
store's reads.
"""
import datetime
import json

SHELF_TAG = "surasura::shelf"
CONNECT_TAG = "surasura::connect::*"
WAITING_QUERY = f'"tag:{CONNECT_TAG}" is:new -is:suspended'
SHELVED_QUERY = f'"tag:{SHELF_TAG}"'
NOT_LISTED = 10 ** 9            # a word no longer on the list ranks behind every listed one

_SQL = (
    """CREATE TABLE IF NOT EXISTS shelf (
      card_id INTEGER NOT NULL,
      note_id INTEGER NOT NULL,
      language TEXT NOT NULL,
      item_id INTEGER,
      word TEXT,
      run TEXT NOT NULL,
      why TEXT NOT NULL,
      shelved_at TEXT NOT NULL,
      back_at TEXT,
      PRIMARY KEY (card_id, run))""",
    """CREATE TABLE IF NOT EXISTS rewrites (
      note_id INTEGER PRIMARY KEY,
      language TEXT NOT NULL,
      word TEXT,
      from_item INTEGER,
      to_item INTEGER,
      marked_at TEXT NOT NULL)""",
)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gap_needed(cap):
    """A big gap (✅ P2.4-2, 🧭 a quarter of the cap): this many waiting cards behind the batch's words, at least 1."""
    return max(1, -(-int(cap) // 4))


def ensure(ledger):
    for sql in _SQL:
        ledger.conn.execute(sql)


class Card:
    """One of Connect's cards in Anki: `card_id`, `note_id`, its `word` and `item_id` (the store's made words)."""

    __slots__ = ("card_id", "note_id", "word", "item_id", "rank")

    def __init__(self, card_id, note_id, word=None, item_id=None, rank=NOT_LISTED):
        self.card_id, self.note_id, self.word, self.item_id, self.rank = card_id, note_id, word, item_id, rank

    def __repr__(self):
        return f"Card({self.card_id}, {self.word}, rank {self.rank})"


def plan(waiting, needed_ranks, cap, count, pinned_items=(), top_words=(), finished_items=()):
    """Which waiting cards go to the shelf -> [Card], lowest first; [] on a small gap.

    `waiting`: Connect's waiting cards (each with its rank); `needed_ranks`: the list places of the words the next
    batch makes; `count`: how many wait now. A card is *behind* when it ranks behind every needed word; a pinned
    item's cards never are, nor a card whose word one of the top 20 holds (`top_words`: the swap-in would bring it
    straight back — row 2.4.11's "the top 20's words", adversary B #5). A finished or gone show's cards
    (`finished_items`) are candidates whatever their rank, and go first (✅ N7: "the shelf's first candidates";
    intent keeper P2.4-B #6: in 3.0 Finished marks no word known, so rank alone would not put them first). The gap is
    big at `gap_needed(cap)` candidates; then they are shelved, finished first and then the lowest, as many as make
    room for the batch (count + its words − cap), never more than are candidates."""
    if not needed_ranks:
        return []
    worst = max(needed_ranks)
    pinned = set(pinned_items or ())
    top = set(top_words or ())
    done = set(finished_items or ())
    behind = [c for c in waiting if (c.rank > worst or c.item_id in done) and c.item_id not in pinned
              and c.word is not None and c.word not in top]
    if len(behind) < gap_needed(cap):
        return []
    behind.sort(key=lambda c: (c.item_id not in done, -c.rank, -c.card_id))
    room = max(0, int(count) + len(needed_ranks) - int(cap))
    return behind[:room]


class AnkiConnectAnki:
    """The shelf's Anki: AnkiConnect (loopback), through Junban's own suspend and tag calls."""

    def __init__(self, url):
        self.url = url

    def find_cards(self, query):
        return self._ids("findCards", query)

    def find_notes(self, query):
        return self._ids("findNotes", query)

    def _ids(self, action, query):
        """A search's ids; an answer that isn't a list raises (never read as "none": every note would read as gone,
        review B #11)."""
        from app import anki_connect
        found = anki_connect.invoke(action, self.url, query=query)
        if not isinstance(found, list):
            raise anki_connect.AnkiError(f"{action} answered {type(found).__name__}, not a list", kind="protocol")
        return anki_connect._int_ids(found)

    def cards_info(self, ids):
        from app import anki_connect
        return anki_connect.cards_info(self.url, ids)

    def reviewing(self):
        from app import anki_connect
        return anki_connect.reviewing(self.url)

    def writer(self, verb):
        from app import anki_connect
        return anki_connect.writer(verb, wait=10.0)

    def suspend(self, card_ids):
        from modules.junban import ankiconnect
        _taken(ankiconnect.suspend(self.url, card_ids), "suspend")

    def unsuspend(self, card_ids):
        from modules.junban import ankiconnect
        _taken(ankiconnect.unsuspend(self.url, card_ids), "unsuspend")

    def add_tag(self, note_ids, tag):
        from modules.junban import ankiconnect
        _taken(ankiconnect.add_tags(self.url, note_ids, tag), "addTags")

    def remove_tag(self, note_ids, tag):
        from modules.junban import ankiconnect
        _taken(ankiconnect.remove_tags(self.url, note_ids, tag), "removeTags")


def _taken(result, action):
    """Junban's write answers (done, failures), never raising: a write Anki didn't take raises here, so nothing is
    recorded as done (review B #8)."""
    from app import anki_connect
    failures = (result or ((), ()))[1]
    if failures:
        raise anki_connect.AnkiError(f"Anki didn't take {action} for {len(failures)}: {failures[0][1]}")


class Reviewing(Exception):
    """You started reviewing: nothing was written."""


def waiting_count(anki):
    """How many of Connect's cards wait (new, not suspended) — one request."""
    return len(anki.find_cards(WAITING_QUERY))


def cards(anki, query, made):
    """[Card] for the cards `query` finds whose note Connect made (`made`: {note id: (item id, word)}): a card of a
    note it can't place (another library's, a note the store doesn't know) is never touched."""
    ids = anki.find_cards(query)
    if not ids:
        return []
    out = []
    for info in anki.cards_info(ids):
        note = info.get("note")
        if note in made:
            item_id, word = made[note]
            out.append(Card(info.get("cardId"), note, word, item_id))
    return out


def shelve(anki, ledger, language, chosen, why, run=None):
    """Suspend `chosen` (cards) and tag their notes `surasura::shelf`, holding Anki's writer, asked first whether
    you're reviewing; each recorded in the ledger under `run` (the restore point) -> the run id. The rows go in first,
    so a kill half-way still leaves a restore point (`restore` touches only cards the shelf holds suspended; adversary
    B #12); a write Anki doesn't take raises and takes the rows out again. The tag goes on before the suspend: a
    suspend Anki doesn't take leaves a tagged waiting card (`tidy` takes the tag off), never a suspended card without
    the tag, which would read as yours (review B #8)."""
    if not chosen:
        return None
    run = run or datetime.datetime.now().strftime("shelf-%Y%m%d-%H%M%S-%f")
    with anki.writer("Connect's shelf"):
        if anki.reviewing():
            raise Reviewing()
        now = _now()
        with ledger.transaction():
            ensure(ledger)
            ledger.conn.executemany("INSERT OR REPLACE INTO shelf (card_id, note_id, language, item_id, word, run, "
                                    "why, shelved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                    [(c.card_id, c.note_id, language, c.item_id, c.word, run, why, now)
                                     for c in chosen])
        try:
            anki.add_tag(sorted({c.note_id for c in chosen}), SHELF_TAG)
            anki.suspend([c.card_id for c in chosen])
        except Exception:
            with ledger.transaction():
                ledger.conn.execute("DELETE FROM shelf WHERE run = ?", (run,))
            raise
    return run


def _untag(anki, cards_back):
    """The shelf tag taken off the notes of `cards_back` (cards just un-suspended), but a note with another card still
    suspended on the shelf keeps it (review B #10, adversary B #13)."""
    back = {c for c, _n in cards_back}
    still = set(anki.find_cards(f"{SHELVED_QUERY} is:suspended")) - back
    kept = {info.get("note") for info in anki.cards_info(sorted(still))} if still else set()
    notes = sorted({n for _c, n in cards_back} - kept)
    if notes:
        anki.remove_tag(notes, SHELF_TAG)


def bring_back(anki, ledger, language, back, finished_items=(), journey_item_of=None):
    """The swap-in: `back` (shelved cards) un-suspended and untagged; a card from a finished or dropped show
    (`finished_items`) also marked for 3.1's rewrite, with the journey item that holds its word now
    (`journey_item_of(word)`) -> {"back": n, "rewrite": [note ids]}."""
    if not back:
        return {"back": 0, "rewrite": []}
    with anki.writer("Connect's shelf"):
        if anki.reviewing():
            raise Reviewing()
        anki.unsuspend([c.card_id for c in back])
        _untag(anki, [(c.card_id, c.note_id) for c in back])
    now, finished, rewrite = _now(), set(finished_items or ()), []
    with ledger.transaction():
        ensure(ledger)
        for c in back:
            ledger.conn.execute("UPDATE shelf SET back_at = ? WHERE card_id = ? AND back_at IS NULL", (now, c.card_id))
            if c.item_id in finished:
                to = journey_item_of(c.word) if journey_item_of else None
                ledger.conn.execute("INSERT OR REPLACE INTO rewrites (note_id, language, word, from_item, to_item, "
                                    "marked_at) VALUES (?, ?, ?, ?, ?, ?)",
                                    (c.note_id, language, c.word, c.item_id, to, now))
                rewrite.append(c.note_id)
    return {"back": len(back), "rewrite": rewrite}


def tidy(anki, ledger):
    """A shelved card you un-suspended in Anki: its shelf tag taken off (it counts as waiting again) -> how many. The
    tag is the note's: a note with another card still on the shelf keeps it (review B #10)."""
    if not anki.find_cards(f"{SHELVED_QUERY} -is:suspended"):
        return 0
    with anki.writer("Connect's shelf"):        # what it writes is read again under the writer (review B #25)
        ids = anki.find_cards(f"{SHELVED_QUERY} -is:suspended")
        still = set(anki.find_cards(f"{SHELVED_QUERY} is:suspended"))
        kept = {info.get("note") for info in anki.cards_info(sorted(still))} if still else set()
        notes = sorted({info.get("note") for info in anki.cards_info(ids) if info.get("note") is not None} - kept)
        if not notes:
            return 0
        if anki.reviewing():
            raise Reviewing()
        anki.remove_tag(notes, SHELF_TAG)
    now = _now()
    with ledger.transaction():
        ensure(ledger)
        ledger.conn.executemany("UPDATE shelf SET back_at = ? WHERE card_id = ? AND back_at IS NULL",
                                [(now, c) for c in ids])
    return len(notes)


def restore(anki, ledger, run):
    """The restore point: every card shelved in `run` still suspended by the shelf goes back -> how many. No 2.x
    window calls it yet (3.0's does: adversary B #14)."""
    ensure(ledger)
    rows = ledger.conn.execute("SELECT card_id, note_id FROM shelf WHERE run = ? AND back_at IS NULL",
                               (run,)).fetchall()
    if not rows:
        return 0
    with anki.writer("Connect's shelf (restore)"):
        still = set(anki.find_cards(f"{SHELVED_QUERY} is:suspended"))
        cards_back = [c for c, _n in rows if c in still]
        if anki.reviewing():                    # review B #9
            raise Reviewing()
        if cards_back:
            anki.unsuspend(cards_back)
            _untag(anki, [(c, n) for c, n in rows if c in still])
    now = _now()
    with ledger.transaction():
        ledger.conn.executemany("UPDATE shelf SET back_at = ? WHERE card_id = ? AND run = ?",
                                [(now, c, run) for c, _n in rows])
    return len(cards_back)


def runs(ledger, language=None):
    """The shelf's restore points, newest first: [{run, cards, why, at, back}]."""
    ensure(ledger)
    sql = ("SELECT run, COUNT(*), MIN(why), MIN(shelved_at), SUM(back_at IS NOT NULL) FROM shelf"
           + (" WHERE language = ?" if language else "") + " GROUP BY run ORDER BY MIN(shelved_at) DESC")
    return [{"run": r, "cards": n, "why": why, "at": at, "back": back}
            for r, n, why, at, back in ledger.conn.execute(sql, (language,) if language else ())]


def made_notes(store):
    """{note id: (item id, word)} from the store's made words (N15): the notes Connect made, placed."""
    if not store.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'made_words'").fetchone():
        return {}
    out = {}
    for item_id, word, ids in store.conn.execute("SELECT item_id, word, note_ids FROM made_words"):
        try:
            for note in json.loads(ids):
                out[int(note)] = (item_id, word)
        except (ValueError, TypeError):
            continue
    return out


def pinned_items(store):
    return {r[0] for r in store.conn.execute("SELECT id FROM items WHERE pinned IS NOT NULL")}


def finished_items(store, made):
    """The items of `made` whose show is finished or gone (Graduated, or no longer in the library)."""
    items = {item for item, _w in made.values()}
    out = set()
    for item in items:
        row = store.conn.execute("SELECT tier FROM items WHERE id = ?", (item,)).fetchone()
        if row is None or row[0] == "graduated":
            out.add(item)
    return out


def ranks(listed):
    """{word: its best place on the list} from the list's {(Word, Reading): place}."""
    out = {}
    for (word, _reading), place in (listed or {}).items():
        if word not in out or place < out[word]:
            out[word] = place
    return out


GONE_CHUNK = 500


def gone_notes(anki, ids, chunk=GONE_CHUNK):
    """Which of `ids` (note ids the store holds) are no longer in Anki (row 2.4.14): `findNotes "nid:…"` in chunks of
    500 — Anki answers the ids of notes still there. Raises AnkiConnect's error when Anki doesn't answer: nothing is
    then marked gone."""
    ids = sorted({int(i) for i in ids or ()})
    there = set()
    for at in range(0, len(ids), chunk):
        part = ids[at:at + chunk]
        there.update(int(n) for n in anki.find_notes("nid:" + ",".join(str(n) for n in part)))
    return [n for n in ids if n not in there]


def shelve_item(anki, ledger, store, language, item_id):
    """A finished show's "remove" (✅ N7): its never-seen Connect cards (new, not suspended) shelved now, undoable —
    never deleted -> the run id, or None when it had none. No 2.x window calls it yet (3.0's does: adversary B #14)."""
    made = {n: v for n, v in made_notes(store).items() if v[0] == item_id}
    chosen = cards(anki, WAITING_QUERY, made)
    return shelve(anki, ledger, language, chosen, f"removed: item {item_id}")
