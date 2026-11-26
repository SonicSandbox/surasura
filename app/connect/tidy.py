"""Tidy: Connect's backlog cleared (Kyou-SH2, 3.0.18; Sonic 2026-11-20 plan v2 point 3, 2026-11-21 MODEL.md round 3:
the clutter clears by itself too, at a line that is quick to check, about 1.5 x the cap (Connect's cards plus the
overflow); ROLES.md: Tidy keeps Anki uncluttered and never deletes without a backup).

- **When:** by itself when the cards waiting for a language (the cap's window + its overflow: what Connect's count
  saw, `runner.Steps.waiting_count`, plus Connect's own waiting cards off your list and the ones on its old shelf)
  pass **1.5 × the cap** (`THRESHOLD`); and on your press (*Tidy now*, Settings), whenever more than the cap wait. A
  quick check: the count Connect already read and the ledger, no Anki call (`choose`). No cap (0): never.
- **What goes:** only **Connect's own cards you never studied** past the window, the lowest in the study order first
  (off your list and set aside first, then a finished show's), as many as wait past the cap (yours past it stay).
  **The guarantee, one function (`why_kept`, Kyou-SH3):** a card is Tidy's to take only if Connect made it (the
  library's made-words record holds the note and Connect's ledger made it — its `surasura::connect::` tag alone never
  is: you can add a tag), it has no review history at all (Anki's review log: a card answered once and reset to new is
  yours), you never changed it (edited, tagged, flagged, buried, suspended, in a filtered deck: `undo._why_kept`) and
  you never asked for it (`asked_for`: a swap's new card, your ⇄ — never past the cap either; *Add now*, journey v3
  D3, once built). Never a pinned show's or an episode you
  asked for either (the runner's `mine`). Each read again under Anki's write lock, automatic and *Tidy now* alike.
- **A backup first, byte for byte:** the notes and cards as Anki describes them (`notes.json`), their clip and
  picture files (`media/`, with each file's sha1), and an Anki package of exactly those notes, scheduling included
  (`cards.apkg`: their cards moved into a deck of their own, `TEMP_DECK`, exported, the package opened and its note
  ids checked) — in Connect's folder, `tidy/<id>/`, kept. **Read back before anything is deleted** (`_read_back`,
  Kyou-SH3): the package readable and holding every note (their number and ids), notes.json holding them, each clip's
  bytes matching its sha1; a backup that can't be written or doesn't read back deletes nothing, every card goes home,
  the tidy is `unsaved` and *Needs you* says so (`status`'s `tidy_unsaved`).
- **Then:** the notes deleted (`deleteNotes`) and their media once no other note uses it (Anki's media trash), the
  words freed in the library (**Surasura's delete**: `library.unmake`, so N15 — a card you deleted is never made
  again — doesn't hold them; they're mined again if they climb back), the shelf's rows of those cards closed.
  Recorded in Connect's ledger (`tidies`) **before** Anki is written; a kill half-way is finished at the next look
  (`finish_pending`: cards left in the deck of its own go back).
- **Undo** (`restore`): the media put back where Anki lacks it, the package imported, each card moved back to its
  deck, the library's made words, receipts and lines back as they were (`library.remake`), the shelf's rows back. A
  note whose word has a card Surasura made again since (it climbed back and was mined) is left out — never two cards
  for one word — and the answer says how many (`skipped`, Kyou-SH3).
- **Said in the window:** *Needs you* — *N unstudied cards deleted, a copy kept.* · *Undo* · *OK* (`status`'s
  `tidied`); a backup that didn't read back: *Nothing deleted …* · *OK* (`tidy_unsaved`).

Every write holds Anki's write lock (`anki-writer`, one writer: `anki_connect.writer`) and asks `guiReviewActive` first
(K88). Anki through the adapter it is handed (`AnkiConnectTidy`; tests hand a fake).
"""
import base64
import datetime
import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import zipfile

from app.connect import undo

log = logging.getLogger("surasura-cli")
THRESHOLD = 1.5                 # Sonic 2026-11-21: Tidy goes by itself past 1.5 × the cap
CONNECT_TAG = "surasura::connect::"
TEMP_DECK = "Surasura Tidy {id}"            # a top-level deck of its own: no parent deck made, deleted once empty
VERB = "Connect's tidy"
CHUNK = 250                                 # notes read again under the lock at a time; card ids per search
PACKAGE_S = 300                             # an Anki package's export or import waits this long at least ...
PACKAGE_NOTE_S = 0.5                        # ... and this much more a note past the first 600 (REMAKE: thousands)
AUTO, NOW = "auto", "now"                   # why a tidy ran: by itself, or your press
REMAKE = "remake"                           # ... or *Make my new cards again…* (REMAKE, 3.0.19: `remake`)
FILTERED = "it's in a filtered deck"
MOVED = "you moved it to a deck of your own"   # Kyou-SH4: not in the deck Surasura last put it in (`homes`)
NO_HOME = "Surasura has no record of the deck it put it in"     # made before homes were recorded: kept in doubt
NOT_MADE = "Surasura didn't make it"         # the guarantee's first clause: the made-words record, never a tag alone
ASKED = "you asked for it"                  # a swap's new card (`asked_for`); journey v3 D3's *Add now* once built
KNOWN_MOVE = "it carries your Known move"   # REMAKE: Known's signal on it (`known_signal.terms`), read from that card

Reviewing = undo.Reviewing


class Refused(Exception):
    """Nothing to tidy, or a tidy that can't be undone (gone, undone already): `say` in plain words."""

    def __init__(self, say):
        super().__init__(say)
        self.say = say


NOTHING = "Nothing to tidy: no more cards wait than your limit."
ALL_KEPT = "the cards past your limit are yours to keep: studied, changed, moved or set aside by you."
NOT_UNDOABLE = "That tidy can't be undone now."
NOT_SAVED = "Anki didn't save a copy of the cards, so nothing was deleted."
NOT_READ_BACK = "The copy of the cards couldn't be saved and read back, so nothing was deleted."
MOVED_MEANWHILE = "A card was moved in Anki while Surasura read it, so nothing was deleted. It looks again next time."

_SQL = """CREATE TABLE IF NOT EXISTS tidies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  language TEXT NOT NULL,
  at TEXT NOT NULL,
  why TEXT NOT NULL,
  state TEXT NOT NULL,
  folder TEXT NOT NULL,
  notes TEXT NOT NULL,
  made TEXT NOT NULL,
  deleted TEXT,
  kept TEXT,
  finished_at TEXT,
  undone_at TEXT)"""
# state: writing (recorded, Anki maybe written) -> done (deleted, words freed) | failed (nothing deleted) | unsaved
# (nothing deleted: its backup couldn't be written or didn't read back — said in *Needs you*) ->
# restoring (Undo recorded, Anki maybe written) -> undone
WRITING, DONE, FAILED, RESTORING, UNDONE = "writing", "done", "failed", "restoring", "undone"
UNSAVED = "unsaved"


def ensure(ledger):
    ledger.conn.execute(_SQL)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Which cards: pure, from what Connect's count already read (no Anki call)
# --------------------------------------------------------------------------- #
class Card:
    """One waiting card as the count saw it: its note, word, item, its place in the study order (lower: sooner),
    whether Tidy may take it (`mine`: Connect's own, not a pinned show's nor an ask's), on the old shelf, of a
    finished show."""

    __slots__ = ("note", "word", "item", "place", "mine", "shelved", "finished")

    def __init__(self, note, word=None, item=None, place=0, mine=False, shelved=False, finished=False):
        self.note, self.word, self.item, self.place = note, word, item, place
        self.mine, self.shelved, self.finished = mine, shelved, finished

    def __repr__(self):
        return f"Card({self.note}, {self.word}, place {self.place}{', mine' if self.mine else ''})"


def over(total, cap, now=False):
    """Is the pile past what Tidy waits for? By itself past THRESHOLD × the cap; on your press past the cap."""
    if not cap or cap <= 0:
        return False
    return total > cap if now else total > THRESHOLD * cap


def candidates(cards, cap, now=False):
    """Tidy's candidates among `cards` (every card that waits: the window, its overflow, Connect's off the list and set
    aside) -> ([Card], how many should go): Connect's own (`mine`) past the window, the lowest first, and how many are
    past the cap; ([], 0) when the pile isn't past the line (`over`). The window is the first `cap` in the study order
    (a tie: kept before a card set aside, before a finished show's, before an older one) — yours and a pinned show's
    are never candidates. `run` takes the first `need` of them that may go (a candidate you studied or changed stays,
    and the next one is read instead)."""
    cards = list(cards)
    if not over(len(cards), cap, now):
        return [], 0
    ranked = sorted(cards, key=lambda c: (c.place, c.shelved, c.finished, -int(c.note)))
    return [c for c in reversed(ranked[int(cap):]) if c.mine], len(cards) - int(cap)


def choose(cards, cap, now=False):
    """The candidates Tidy would take if every one may go -> [Card], lowest first (`candidates`)."""
    out, need = candidates(cards, cap, now)
    return out[:need]


# --------------------------------------------------------------------------- #
# Anki
# --------------------------------------------------------------------------- #
class AnkiConnectTidy(undo.AnkiConnectUndo):
    """Tidy's Anki: AnkiConnect, loopback (undo's reads and deletes, plus decks, packages and media bytes). `wait`: how
    long the write lock is waited for (the window's press: 10 s; Connect's own look: 0, never holding mining)."""

    def __init__(self, url, wait=10.0):
        super().__init__(url)
        self.wait = wait

    def writer(self, verb):
        from app import anki_connect
        return anki_connect.writer(verb, wait=self.wait)

    def find_cards(self, query):
        from app import anki_connect
        return list(anki_connect.invoke("findCards", self.url, query=query) or [])

    def find_notes(self, query):
        from app import anki_connect
        return list(anki_connect.find_notes(self.url, query) or [])

    def change_deck(self, card_ids, deck):
        from app import anki_connect
        anki_connect.invoke("changeDeck", self.url, cards=list(card_ids), deck=deck)

    def delete_deck(self, deck):
        from app import anki_connect
        anki_connect.invoke("deleteDecks", self.url, decks=[deck], cardsToo=True)

    package_timeout = PACKAGE_S             # `run` and `restore` set it by the number of notes (`package_timeout`)

    def export_package(self, deck, path):
        from app import anki_connect
        return anki_connect.invoke("exportPackage", self.url, timeout=self.package_timeout, deck=deck, path=path,
                                   includeSched=True) is True

    def import_package(self, path):
        from app import anki_connect
        return anki_connect.invoke("importPackage", self.url, timeout=self.package_timeout, path=path) is True

    def sync(self):
        """Anki's own sync with AnkiWeb, asked now under the write lock held (the sync rule's `sync_now`) -> its
        answer ("synced", "not-signed-in", "full-sync", "busy", "failed: …")."""
        from app import anki_sync_rule
        return anki_sync_rule.sync_now(self.url)

    def reviewed(self, card_ids):
        """The card ids of `card_ids` with any line in Anki's review log (a review, a relearn, a reset) -> a set, or
        None when Anki's answer can't be read (the guarantee then keeps every card)."""
        from app import anki_connect
        ids, out = sorted({int(c) for c in card_ids}), set()
        for at in range(0, len(ids), CHUNK):
            got = anki_connect.invoke("getReviewsOfCards", self.url, cards=ids[at:at + CHUNK])
            if not isinstance(got, dict) or {str(c) for c in ids[at:at + CHUNK]} - {str(k) for k in got}:
                return None                 # no answer, or one that leaves out a card asked for: every card kept
            out |= {int(c) for c, lines in got.items() if lines}
        return out

    def media_bytes(self, name):
        from app import anki_connect
        got = anki_connect.invoke("retrieveMediaFile", self.url, filename=name)
        return base64.b64decode(got) if isinstance(got, str) and got else None

    def store_media(self, name, data):
        from app import anki_connect
        anki_connect.invoke("storeMediaFile", self.url, filename=name,
                            data=base64.b64encode(data).decode("ascii"), deleteExisting=False)


def _connect_tag(info):
    return next((str(t).lower() for t in info.get("tags") or () if str(t).lower().startswith(CONNECT_TAG)), None)


def _done_at(ledger, note_id):
    """When the job that made the note ended (its `updated_at`, as *Undo this batch* reads it), or None."""
    return _done_ats(ledger, [note_id]).get(int(note_id))


def _done_ats(ledger, note_ids):
    """`_done_at` of every note of `note_ids` -> {note id: epoch} (a note no made outcome holds: absent): one query a
    chunk, by the outcomes' note index (REMAKE: one query per note before, each a scan of every outcome)."""
    ids = sorted({int(n) for n in note_ids})
    newest = {}
    for at in range(0, len(ids), CHUNK):
        chunk = ids[at:at + CHUNK]
        for note_id, job_id, ended in ledger.conn.execute(
                "SELECT o.note_id, o.job_id, j.updated_at FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE "
                f"o.note_id IN ({','.join('?' * len(chunk))}) AND o.outcome = 'made'", chunk):
            if note_id not in newest or job_id > newest[note_id][0]:     # the newest made job's end, as before
                newest[note_id] = (job_id, ended)
    return {int(n): undo._epoch(ended) for n, (_j, ended) in newest.items()}


def _carries(info, card, terms):
    """Does `card` carry Known's signal — every one of `terms` (`known_signal.terms`: "suspended", "marked",
    "flag:N") holds? No terms (the signal off): never."""
    if not terms:
        return False
    tags = {str(t).lower() for t in info.get("tags") or ()}
    for term in terms:
        if term == "suspended":
            if int(card.get("queue") or 0) != -1:
                return False
        elif term == "marked":
            if "marked" not in tags:
                return False
        elif str(term).startswith("flag:"):
            if str(int(card.get("flags") or 0)) != str(term)[len("flag:"):]:
                return False
        else:
            return False
    return True


def why_kept(info, cards, made, reviewed, filtered, done_at, shelf, asked=frozenset(), yours=frozenset(), home=None,
             ours=frozenset(), tidying=frozenset(), mode=None, before=frozenset(), known=()):
    """**Tidy's guarantee** (Kyou-SH3), every clause in one place: why one note is not Tidy's to take, or None when it
    is. A card is Tidy's only if
    - **Connect made it**: the library's made-words record holds the note (`made`) and Connect's ledger made it
      (`done_at`, when its job ended) — its `surasura::connect::` tag alone never is: you can add a tag (it must
      still carry one: a tag you took off is a change);
    - **you never asked for it** (`asked`, `asked_for`: a swap's new card; journey v3 D3's *Add now* once built);
    - **it was never reviewed**: no line in Anki's review log for any of its cards (`reviewed`; None = the log
      couldn't be read: kept) — a card answered once and reset to new still has its history and is yours — and none
      studied (reps, type);
    - **you never changed it**: not edited or tagged since Connect's last write, flagged, buried, suspended by you
      (`undo._why_kept`), taken off the old shelf by you (`yours`: put back, or un-suspended in Anki — P2.5-2), nor
      in a filtered deck (`filtered`);
    - **you never moved it** (Kyou-SH4, Sonic 2026-11-22): every card of it is in its `home` — the deck Surasura last
      put it in (Connect's ledger, `homes`: its batch's deck, or *Move them to X*'s) — or, only for a card with no
      home on record (made before homes were), in one of `ours` (the deck Surasura shows for new cards now); Tidy's
      own deck while it backs the card up (`tidying`) counts too. Anywhere else — a deck or a subdeck of yours, a deck
      renamed since — it is yours. No home on record and not in `ours`: kept, never a guess. Junban never moves a deck (its reorder moves a card's
      due and the card's mod, which is why the mod can't tell: the guarantee's review, G3).
    `cards` {card id: Anki's card}; `shelf` the old shelf's rows (`undo._shelf_rows`).

    **`mode` REMAKE** (*Make my new cards again…*; the lead's rulings 2026-11-25 on Sonic's "start clean"): the same
    clauses but these — a card you edited or tagged, suspended, buried or took off the old shelf goes too (it is in
    the backup); one carrying a daily-loop move stays (any flag: Ignore's, Swap's or yours; Known's signal, `known`:
    `KNOWN_MOVE`); a note Surasura didn't make goes only when its note type is one of `before` (the tick *from
    before*: Connect's own note type; off, none), tag or no tag; and a card in its home or in one of `ours`
    (Surasura's deck itself) is in place. Studied, asked for, in a filtered deck or a deck of yours: kept, as always."""
    note_id = int(info["noteId"])
    remake = mode == REMAKE
    if note_id not in made or not done_at:
        if not (remake and info.get("modelName") in before):
            return NOT_MADE
    elif note_id in asked:
        return ASKED
    tag = _connect_tag(info)
    if tag is None and not remake:
        return undo.NOT_ITS_TAG
    card_ids = [int(c) for c in info.get("cards") or ()]
    if reviewed is None or any(c in reviewed for c in card_ids):
        return undo.STUDIED
    if remake:
        why = _remake_kept(info, cards, card_ids, known)
    elif any(c in yours for c in card_ids):
        return undo.CHANGED
    else:
        why = undo._why_kept(info, cards, tag, done_at, shelf)
    if why:
        return why
    if any(c in filtered for c in card_ids):
        return FILTERED
    if remake:
        fine = {str(d).casefold() for d in {home} | set(ours) | set(tidying) if d}
    else:
        fine = {str(d).casefold() for d in ({home} if home else ours) | set(tidying) if d}
    if any(str((cards.get(c) or {}).get("deckName") or "").casefold() not in fine for c in card_ids):
        return MOVED if home else NO_HOME
    return None


def _remake_kept(info, cards, card_ids, known):
    """REMAKE's card clauses (`why_kept`): studied (reps, type; the review log is read first), a flag (the loop's
    Ignore or Swap, or one of yours), Known's signal -> why, or None. Suspended, buried, edited: they go."""
    for c in card_ids:
        card = cards.get(c)
        if card is None:
            return undo.STUDIED             # a card Anki didn't describe: never deleted unread
        if int(card.get("reps") or 0) > 0 or int(card.get("type") or 0) != 0:
            return undo.STUDIED
        if int(card.get("flags") or 0) != 0:
            return undo.FLAGGED
        if _carries(info, card, known):
            return KNOWN_MOVE
    return None


def _shelf_read(ledger):
    """What `check` reads of the ledger's old shelf: (its rows, `undo._shelf_rows`; the cards you took off it)."""
    return undo._shelf_rows(ledger), _back_by_you(ledger)


def _back_by_you(ledger):
    """The cards you took off the old shelf — put back from a restore point, or un-suspended in Anki (`shelf.YOURS`,
    P2.5-2: never shelved again) -> a set. Un-suspending a card is your choice to study it: never Tidy's."""
    if not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shelf'").fetchone():
        return set()
    from app.connect import shelf
    shelf.ensure(ledger)
    return {int(r[0]) for r in ledger.conn.execute("SELECT card_id FROM shelf WHERE back_by IN (?, ?)", shelf.YOURS)}


def asked_for(ledger, language, note_ids, why=None):
    """The notes of `note_ids` you asked for -> frozenset: a card you asked for is never Tidy's, studied or not, past
    the cap or not (`why_kept`'s ASKED). A swap's new card is one (your ⇄ — Suspend + Green flag — asked for it, as it
    is never held by the cap: OPEN 56 f / g, PROVISIONAL), read from Swap's own record (`swap.new_cards`), but not in
    the swap's own Undo (`why` "swap"), which takes back the card it made. Journey v3 D3's *Add now* is one too: it
    asks through Swap's maker (`door_routes.card_route`), so its card is in the same record."""
    from app.connect import swap
    asked = set()
    if why != swap.BY_SWAP:
        asked |= swap.new_cards(ledger, language, note_ids)
    return frozenset(asked)


def check(anki, ledger, note_ids, made, asked=frozenset(), ours=frozenset(), tidying=frozenset(), mode=None,
          before=frozenset(), known=(), read=None):
    """Read under the lock: which of `note_ids` may go now (`why_kept`; `made`: the notes the library's made-words
    record holds; `ours`: the decks that are Surasura's whatever a card's home — `run`'s; `mode`, `before`, `known`:
    REMAKE's; `read`: the ledger's shelf rows as `_shelf_read` gave them, read once for every chunk) -> (go [note
    ids], kept [[note id, why]], infos {id: note}, cards {id: card}). A note Anki no longer has is neither."""
    infos = {int(n["noteId"]): n for n in anki.notes(sorted({int(n) for n in note_ids}))
             if isinstance(n, dict) and n.get("noteId")}
    card_ids = sorted({int(c) for n in infos.values() for c in n.get("cards") or ()})
    cards = {int(c["cardId"]): c for c in (anki.cards(card_ids) if card_ids else []) if isinstance(c, dict)
             and c.get("cardId")}
    reviewed = anki.reviewed(card_ids) if card_ids else set()
    filtered = set()                # an Anki that can't search for them fails here: nothing is deleted unread
    for at in range(0, len(card_ids), CHUNK):
        filtered |= set(anki.find_cards("deck:filtered cid:" + ",".join(map(str, card_ids[at:at + CHUNK]))) or ())
    shelf, yours = read if read is not None else _shelf_read(ledger)
    homes = ledger.homes(infos)
    done_at = _done_ats(ledger, infos)
    go, kept = [], []
    for note_id in [int(n) for n in dict.fromkeys(note_ids) if int(n) in infos]:     # in the order asked: lowest first
        why = why_kept(infos[note_id], cards, made, reviewed, filtered, done_at.get(note_id), shelf, asked, yours,
                       homes.get(note_id), ours, tidying, mode, before, known)
        if why:
            kept.append([note_id, why])
        else:
            go.append(note_id)
    return go, kept, infos, cards


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


def package_notes(path):
    """The note ids an Anki package holds, or None when it can't be read (no collection inside, a damaged file)."""
    ids = _package_note_ids(path)
    return None if ids is None else set(ids)


def _package_note_ids(path):
    """Every note row an Anki package holds (a list: their number counts), or None when it can't be read."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            for name in ("collection.anki21b", "collection.anki21", "collection.anki2"):
                if name not in names:
                    continue
                data = z.read(name)
                if name.endswith("b"):
                    import zstandard
                    data = zstandard.ZstdDecompressor().stream_reader(data).read()
                fd, tmp = tempfile.mkstemp(suffix=".sqlite")
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(data)
                    conn = sqlite3.connect(tmp)
                    try:
                        return [int(r[0]) for r in conn.execute("SELECT id FROM notes")]
                    finally:
                        conn.close()
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
    except Exception:
        log.exception("Connect's tidy: the package couldn't be read")
    return None


def _folder(ledger):
    """Connect's folder beside the ledger: `<connect>/tidy/`."""
    row = ledger.conn.execute("PRAGMA database_list").fetchone()
    base = os.path.dirname(row[2]) if row and row[2] else tempfile.gettempdir()
    return os.path.join(base, "tidy")


# --------------------------------------------------------------------------- #
# Tidy
# --------------------------------------------------------------------------- #
def run(anki, ledger, language, note_ids, why=AUTO, open_store=None, limit=None, ours=None, before=frozenset(),
        known=(), sync=False):
    """Tidy `note_ids` (`candidates`, lowest first): under Anki's write lock, read again (`check`, a chunk at a time
    until `limit` may go), recorded in the ledger (with the library's made-words rows of those notes) before Anki is
    written, backed up (`_backup`: refused → nothing deleted), deleted, then finished (`finish`: the words freed) ->
    {"id", "deleted", "kept", "freed", "pending"}. `ours`: the deck Surasura shows for the language's new cards
    (`fields.surasura_deck`; REMAKE: Surasura's decks, a set), or None. `why` REMAKE reads `why_kept` in its mode
    (`before`, `known`: its own); `sync`: Anki's own sync asked under the lock before anything is read (`synced`:
    REMAKE's, so a review made on another device is in Anki first). Raises Reviewing, Refused (none may go:
    `ALL_KEPT`; `NOT_SAVED`; the sync's words), the lock's Busy, AnkiConnect's errors."""
    ensure(ledger)
    ids = [int(n) for n in dict.fromkeys(note_ids)]
    limit = len(ids) if limit is None else int(limit)
    ours = frozenset({ours} if isinstance(ours, str) else (d for d in ours or () if d))
    mode = REMAKE if why == REMAKE else None
    with anki.writer(VERB):
        if anki.reviewing():
            raise Reviewing()
        if sync:
            synced(anki)
        for pending in pending_tidies(ledger, language):      # a kill's half-way tidy first, under this lock
            finish(anki, ledger, pending, open_store)
        made_ids = _made_notes(open_store, ids)             # the guarantee's first clause: the library's record
        asked = asked_for(ledger, language, ids, why)
        read = _shelf_read(ledger)
        go, kept, infos, cards = [], [], {}, {}
        for at in range(0, len(ids), CHUNK):
            if len(go) >= limit:
                break
            g, k, i, c = check(anki, ledger, ids[at:at + CHUNK], made_ids, asked, ours, mode=mode, before=before,
                               known=known, read=read)
            go += g
            kept += k
            infos.update(i)
            cards.update(c)
        go = go[:limit]
        if not go:
            raise Refused(ALL_KEPT)
        notes = {}
        for n in go:
            info = infos[n]
            notes[str(n)] = {"cards": {str(c): (cards.get(int(c)) or {}).get("deckName") for c in info.get("cards") or ()},
                             "ords": {str(c): (cards.get(int(c)) or {}).get("ord") for c in info.get("cards") or ()},
                             "model": info.get("modelName"), "tags": info.get("tags") or [],
                             "fields": {k: (v.get("value") if isinstance(v, dict) else v)
                                        for k, v in (info.get("fields") or {}).items()},
                             "media": sorted(undo._media(info))}
        made = _store_rows(open_store, go)
        with ledger.transaction():
            cur = ledger.conn.execute(
                "INSERT INTO tidies (language, at, why, state, folder, notes, made, kept) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (language, _now(), why, WRITING, "", json.dumps(notes, ensure_ascii=False),
                 json.dumps(made, ensure_ascii=False), json.dumps(kept, ensure_ascii=False)))
            tidy_id = cur.lastrowid
            folder = os.path.join(_folder(ledger), f"{language}-{tidy_id}")
            ledger.conn.execute("UPDATE tidies SET folder = ? WHERE id = ?", (folder, tidy_id))
        if hasattr(anki, "package_timeout"):        # a package of thousands of notes and their clips takes a while
            anki.package_timeout = package_timeout(len(go))
        try:
            _backup(anki, infos, cards, go, tidy_id, folder)
        except Refused as e:
            # said in *Needs you*: nothing deleted, every card home (a card moved meanwhile: failed, said by *Tidy now*)
            _fail(anki, ledger, tidy_id, notes, FAILED if e.say == MOVED_MEANWHILE else UNSAVED)
            raise
        except Exception:
            _fail(anki, ledger, tidy_id, notes)
            raise
        # read once more just before the delete: a card you answered or changed while Anki exported stays (its card
        # back home); the package may hold it too, and Undo leaves a note Anki still has as it is — in Tidy's own deck
        # now (`_backup` moved it there): one you moved out of it meanwhile is yours
        still, late, now_infos, _c = check(anki, ledger, go, made_ids, asked, ours, {TEMP_DECK.format(id=tidy_id)},
                                           mode=mode, before=before, known=known, read=_shelf_read(ledger))
        grew = [n for n in still if {str(c) for c in now_infos[n].get("cards") or ()} != set(notes[str(n)]["cards"])]
        if grew:                        # a card Anki made for the note since the backup isn't in the copy: kept
            grown = set(grew)
            still = [n for n in still if n not in grown]
            late += [[n, undo.CHANGED] for n in grew]
        if late:
            late_ids = {int(n) for n, _w in late}
            _cards_home(anki, tidy_id, {k: v for k, v in notes.items() if int(k) in late_ids})
            kept += late
            with ledger.transaction():
                ledger.conn.execute("UPDATE tidies SET kept = ? WHERE id = ?",
                                    (json.dumps(kept, ensure_ascii=False), tidy_id))
        if anki.reviewing():
            _fail(anki, ledger, tidy_id, notes)
            raise Reviewing()
        media = set()
        for n in still:
            media |= set(notes[str(n)]["media"])
        if still:
            anki.delete_notes(still)
        _drop_temp(anki, tidy_id)
        for name in sorted(media):
            if not anki.users(name):
                anki.delete_media(name)
        row = tidy_row(ledger, tidy_id)
        return dict(finish(anki, ledger, row, open_store, home=False), id=tidy_id)


def _made_notes(open_store, note_ids):
    """The notes of `note_ids` the library's made-words record holds (Connect made them) -> a set; none with no
    store (JSON mode has no made words). A store that can't be read now raises: nothing is written to Anki."""
    if open_store is None:
        return set()
    store = open_store()
    if store is None:
        return set()
    from app.connect import library
    wanted = {int(n) for n in note_ids}
    with store:
        rows = library.made_rows(store, wanted).get("words") or ()
    return {int(n) for row in rows for n in row[2]} & wanted


def _backup(anki, infos, cards, go, tidy_id, folder):
    """notes.json + media/ + cards.apkg in `folder`, then read back (`_read_back`) -> Refused(NOT_READ_BACK) when
    the folder can't be written or the copy doesn't read back, Refused(NOT_SAVED) when Anki exported nothing."""
    record = {"notes": [infos[n] for n in go], "cards": [cards[int(c)] for n in go for c in infos[n].get("cards") or ()
                                                       if int(c) in cards], "media": {}}
    try:
        os.makedirs(os.path.join(folder, "media"), exist_ok=True)
        for n in go:
            for name in sorted(undo._media(infos[n])):
                if name in record["media"]:
                    continue
                data = anki.media_bytes(name)
                if data is None:
                    record["media"][name] = None            # Anki had no such file: nothing to keep
                    continue
                with open(os.path.join(folder, "media", os.path.basename(name)), "wb") as f:
                    f.write(data)
                record["media"][name] = _sha1(data)
        with open(os.path.join(folder, "notes.json"), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=1)
    except OSError:
        log.exception("Connect's tidy: its backup couldn't be written")
        raise Refused(NOT_READ_BACK) from None
    deck = TEMP_DECK.format(id=tidy_id)
    card_ids = [int(c) for n in go for c in infos[n].get("cards") or ()]
    # Kyou-SH4 (lens #1): a card you moved while the copy was written would be overwritten by the move below and then
    # read as Tidy's own: read the decks again first; one moved → nothing deleted, tried again next time (kept then)
    now = {int(c["cardId"]): c.get("deckName") for c in anki.cards(card_ids) if isinstance(c, dict) and c.get("cardId")}
    if any(now.get(c) != (cards.get(c) or {}).get("deckName") for c in card_ids):
        raise Refused(MOVED_MEANWHILE)
    anki.change_deck(card_ids, deck)
    package = os.path.join(folder, "cards.apkg")
    if not anki.export_package(deck, package):
        raise Refused(NOT_SAVED)
    if not _read_back(folder, go, record["media"]):
        raise Refused(NOT_READ_BACK)


def _read_back(folder, go, media):
    """F4 (Kyou-SH3): the backup as written, read back from the disk before anything is deleted -> does it hold
    every note of `go`? The package readable, its notes exactly `go` (their number and ids); notes.json the same
    notes and the same sha1s; every clip kept (`media` {name: sha1 | None}) byte for byte."""
    want = sorted(int(n) for n in go)
    if sorted(_package_note_ids(os.path.join(folder, "cards.apkg")) or []) != want:
        return False
    try:
        with open(os.path.join(folder, "notes.json"), encoding="utf-8") as f:
            record = json.load(f)
        if sorted(int(n["noteId"]) for n in record.get("notes") or ()) != want or record.get("media") != media:
            return False
        for name, sha in media.items():
            if sha is None:
                continue
            with open(os.path.join(folder, "media", os.path.basename(name)), "rb") as f:
                if _sha1(f.read()) != sha:
                    return False
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        log.exception("Connect's tidy: its backup didn't read back")
        return False
    return True


def _fail(anki, ledger, tidy_id, notes, state=FAILED):
    """The backup didn't hold (`unsaved`) or you started reviewing (`failed`): every card back in its deck, nothing
    deleted. A move home that fails leaves it `writing`: the next look (`finish`) puts the cards home."""
    try:
        _cards_home(anki, tidy_id, notes)
    except Exception:
        log.exception("Connect's tidy: its cards couldn't go back to their decks now; the next look does it")
        return
    with ledger.transaction():
        ledger.conn.execute("UPDATE tidies SET state = ?, deleted = '[]', finished_at = ? WHERE id = ?",
                            (state, _now(), tidy_id))


def _cards_home(anki, tidy_id, notes, id_map=None):
    """Cards still in the tidy's own deck back to the decks they were in (`notes`' record), by card id or, for a note
    Anki gave a new id (`id_map` {old note: new note}), by the card's place in its note (`ord`)."""
    deck = TEMP_DECK.format(id=tidy_id)
    there = set(anki.find_cards(f'"deck:{deck}"') or ())
    if not there:
        _drop_temp(anki, tidy_id)
        return
    by_deck = {}
    for old, rec in notes.items():
        for cid, home in (rec.get("cards") or {}).items():
            if int(cid) in there and home:
                by_deck.setdefault(home, []).append(int(cid))
    if id_map:
        moved = {c for ids in by_deck.values() for c in ids}
        new_cards = {}
        infos = anki.notes(sorted(set(id_map.values())))
        for info in infos:
            for c in info.get("cards") or ():
                if int(c) in there and int(c) not in moved:
                    new_cards[int(c)] = int(info["noteId"])
        if new_cards:
            back = {v: k for k, v in id_map.items()}
            for card in anki.cards(sorted(new_cards)):
                old = back.get(new_cards.get(int(card.get("cardId") or 0)))
                rec = notes.get(str(old)) or {}
                home = next((rec["cards"][cid] for cid, o in (rec.get("ords") or {}).items()
                             if o == card.get("ord") and (rec.get("cards") or {}).get(cid)), None)
                if home:
                    by_deck.setdefault(home, []).append(int(card["cardId"]))
    for home, ids in sorted(by_deck.items()):
        anki.change_deck(sorted(ids), home)
    _drop_temp(anki, tidy_id)


def _drop_temp(anki, tidy_id):
    """The tidy's own deck goes once no card is in it (never a card with it)."""
    deck = TEMP_DECK.format(id=tidy_id)
    if not anki.find_cards(f'"deck:{deck}"'):
        try:
            anki.delete_deck(deck)
        except Exception:
            log.warning("Connect's tidy: its deck %s wasn't removed", deck, exc_info=True)


def _store_rows(open_store, note_ids):
    """The library's record of `note_ids` before Tidy touches it: {"words": [[item, word, note_ids, made_at, batch]],
    "receipts": {item: mined_at}, "lines": [[note_id, item, start_ms, end_ms, line_fp, made_at]]} ({} with no store)."""
    if open_store is None:
        return {}
    store = open_store()            # a store that can't be read now raises: nothing is written to Anki (no Undo
    if store is None:               # could put the words back) — JSON mode has no made words at all
        return {}
    from app.connect import library
    with store:
        return library.made_rows(store, note_ids)


def finish(anki, ledger, row, open_store=None, home=True):
    """A tidy recorded before Anki was written, finished: which notes are gone now (Anki read), any card left in its
    own deck back home, those words freed in the store (`library.unmake`: Surasura's delete), the shelf's rows
    closed, the tidy `done` -> {"deleted", "kept", "freed", "pending"} (`pending`: the store couldn't be written just
    now — freed by the next look)."""
    planned = [int(n) for n in json.loads(row["notes"])]
    notes = json.loads(row["notes"])
    still = {int(n["noteId"]) for n in (anki.notes(planned) if planned else []) if isinstance(n, dict) and n.get("noteId")}
    if home:                        # a kill's tidy: cards left in its own deck go home, the deck goes once empty
        _cards_home(anki, row["id"], {k: v for k, v in notes.items() if int(k) in still})
    gone = [n for n in planned if n not in still]
    went = set(gone)
    made = json.loads(row["made"] or "{}")
    by_item = {}
    for item, word, ids, _at, _batch in made.get("words") or ():
        for n in ids:
            if int(n) in went:
                by_item.setdefault(item, (set(), set()))
                by_item[item][0].add(int(n))
                by_item[item][1].add(word)
    freed, stored = [], True
    if open_store is not None and gone:
        stored = False
        try:
            store = open_store()
            if store is not None:
                from app.connect import library
                with store:
                    for item, (ids, words) in sorted(by_item.items()):
                        freed += library.unmake(store, item, sorted(ids), words)
                    library.notes_gone(store, gone)     # their lines too (made words freed first: never blocked)
                stored = True
            elif undo._no_store(row["language"]):
                stored = True
        except Exception:
            log.exception("Connect's tidy: the library couldn't free the words just now; tried again next time")
    kept = json.loads(row["kept"] or "[]")
    said = {int(k[0]) for k in kept}
    kept += [[n, "Anki didn't delete it"] for n in sorted(still) if n not in said]     # never twice (the last read's)
    with ledger.transaction():
        if stored:
            ledger.conn.execute("UPDATE tidies SET state = ?, deleted = ?, kept = ?, finished_at = ? WHERE id = ?",
                                (DONE if gone else FAILED, json.dumps(gone), json.dumps(kept, ensure_ascii=False),
                                 _now(), row["id"]))
        _close_shelf(ledger, gone)
    return {"deleted": gone, "kept": kept, "freed": sorted(set(freed)), "pending": not stored}


def _close_shelf(ledger, note_ids):
    if not note_ids or not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shelf'"
                                               ).fetchone():
        return
    from app.connect import shelf
    shelf.ensure(ledger)
    now = _now()
    ledger.conn.executemany("UPDATE shelf SET back_at = ?, back_by = 'tidied' WHERE note_id = ? AND back_at IS NULL",
                            [(now, int(n)) for n in note_ids])


def tidy_row(ledger, tidy_id):
    ensure(ledger)
    cur = ledger.conn.execute("SELECT * FROM tidies WHERE id = ?", (int(tidy_id),))
    r = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], r)) if r else None


PAST = 10                                   # *Put back…* lists the last 10 tidies (Sonic 2026-11-22, PROVISIONAL)
CAN, PUT_BACK, GONE = "can", "put back", "gone"     # a past tidy, for *Put back…*: Undo takes it / undone / no copy


def past(ledger, language, n=PAST):
    """*Put back…* (Kyou-SH3 part 2): `language`'s last `n` tidies that deleted cards, newest first ->
    [{"id", "at", "why", "cards", "can"}] — `can`: CAN (done, its copy on disk: `restore` takes it), PUT_BACK
    (undone already: a tidy goes back once) or GONE (its copy isn't on disk any more). A tidy that deleted nothing,
    one still writing or putting back, and Swap's own Undo (`why` swap, never shown as a tidy) aren't listed; older
    ones stay on disk, unlisted."""
    ensure(ledger)
    out = []
    for tidy_id, at, why, state, folder, deleted in ledger.conn.execute(
            "SELECT id, at, why, state, folder, deleted FROM tidies WHERE language = ? AND state IN (?, ?) AND why != ? "
            "ORDER BY id DESC", (language, DONE, UNDONE, "swap")):
        try:
            cards = len(json.loads(deleted or "[]"))
        except ValueError:
            cards = 0
        if not cards:
            continue
        can = PUT_BACK if state == UNDONE else CAN if os.path.exists(os.path.join(folder or "", "cards.apkg")) else GONE
        out.append({"id": int(tidy_id), "at": at, "why": why, "cards": cards, "can": can})
        if len(out) >= n:
            break
    return out


def pending_tidies(ledger, language):
    """Tidies a kill left half-way (recorded, Anki maybe written), oldest first."""
    ensure(ledger)
    cur = ledger.conn.execute("SELECT * FROM tidies WHERE language = ? AND state = ? ORDER BY id", (language, WRITING))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def finish_pending(anki, ledger, language, open_store=None):
    """Every tidy and Undo a kill left half-way, finished (a Connect run's first look), holding Anki's write lock ->
    how many. While you review: none (Reviewing; the next look)."""
    ensure(ledger)
    rows = pending_tidies(ledger, language)
    cur = ledger.conn.execute("SELECT * FROM tidies WHERE language = ? AND state = ? ORDER BY id", (language, RESTORING))
    names = [d[0] for d in cur.description]
    restoring = [dict(zip(names, r)) for r in cur.fetchall()]
    if not rows and not restoring:
        return 0
    with anki.writer(VERB):
        if anki.reviewing():
            raise Reviewing()
        for row in rows:
            finish(anki, ledger, row, open_store)
        for row in restoring:
            _restored(anki, ledger, row, open_store)
    return len(rows) + len(restoring)


# --------------------------------------------------------------------------- #
# Undo
# --------------------------------------------------------------------------- #
def restore(anki, ledger, tidy_id, open_store=None, language=None, word_of=None):
    """*Undo* a tidy: under Anki's write lock, recorded first (`restoring`), the media Anki lacks put back from the
    backup's bytes, the package imported, each card moved back to its deck, the library's record back
    (`library.remake`), the shelf's rows back -> {"id", "back" (notes in Anki again), "missing" (notes not found
    after the import), "skipped" (left out: their word has a card again, `_mined_again`; `word_of(note)`: the word of
    a card the made-words record never held — a remake's from before), "media_missing"}. Raises Refused
    (`NOT_UNDOABLE`), Reviewing, the lock's Busy, AnkiConnect's errors."""
    row = tidy_row(ledger, tidy_id)
    if row is None or row["state"] != DONE or (language is not None and row["language"] != language):
        raise Refused(NOT_UNDOABLE)
    if hasattr(anki, "package_timeout"):
        anki.package_timeout = package_timeout(len(json.loads(row["deleted"] or "[]")))
    package = os.path.join(row["folder"], "cards.apkg")
    if not os.path.exists(package):
        raise Refused(NOT_UNDOABLE)
    with anki.writer(VERB):
        if anki.reviewing():
            raise Reviewing()
        with ledger.transaction():
            claimed = ledger.conn.execute("UPDATE tidies SET state = ? WHERE id = ? AND state = ?",
                                          (RESTORING, row["id"], DONE)).rowcount
        if not claimed:                 # put back meanwhile (*Needs you*'s Undo and *Put back…* at once): never twice
            raise Refused(NOT_UNDOABLE)
        try:
            with open(os.path.join(row["folder"], "notes.json"), encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError):
            record = {"media": {}}
        lost = []                           # files the backup can't give back as they were (said in the answer)
        try:
            for name, sha in sorted((record.get("media") or {}).items()):
                if not sha or anki.media_bytes(name) is not None:
                    continue
                try:
                    with open(os.path.join(row["folder"], "media", os.path.basename(name)), "rb") as f:
                        data = f.read()
                except OSError:
                    lost.append(name)
                    continue
                if _sha1(data) != sha:
                    lost.append(name)
                    continue
                anki.store_media(name, data)
            imported = anki.import_package(package)
        except Exception:
            _not_back(ledger, row["id"])
            raise
        if not imported:
            _not_back(ledger, row["id"])
            raise Refused(NOT_UNDOABLE)
        row["state"] = RESTORING
        return dict(_restored(anki, ledger, row, open_store, word_of), media_missing=lost)


def _not_back(ledger, tidy_id):
    """An import that didn't take: the tidy stays `done` (its Undo offered again)."""
    with ledger.transaction():
        ledger.conn.execute("UPDATE tidies SET state = ? WHERE id = ?", (DONE, tidy_id))


def _match(anki, row, notes):
    """{old note id: its note in Anki now}: the same id (the import keeps it when it's free), else the note in the
    tidy's own deck with the same note type and fields."""
    deleted = [int(n) for n in json.loads(row["deleted"] or "[]")]
    there = {int(n["noteId"]): n for n in anki.notes(deleted) if isinstance(n, dict) and n.get("noteId")}
    id_map = {n: n for n in deleted if n in there}
    left = [n for n in deleted if n not in id_map]
    if left:
        found = anki.find_notes(f'"deck:{TEMP_DECK.format(id=row["id"])}"')
        taken = set(id_map.values())
        by_content = {}                     # (note type, fields) -> the notes in the tidy's own deck holding them
        for info in anki.notes(sorted(set(found))):
            if isinstance(info, dict) and info.get("noteId") and int(info["noteId"]) not in taken:
                fields = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in (info.get("fields") or {}).items()}
                key = (info.get("modelName"), json.dumps(fields, sort_keys=True, ensure_ascii=False))
                by_content.setdefault(key, []).append(int(info["noteId"]))
        for old in left:
            rec = notes.get(str(old)) or {}
            key = (rec.get("model"), json.dumps(rec.get("fields") or {}, sort_keys=True, ensure_ascii=False))
            if by_content.get(key):
                id_map[old] = by_content[key].pop(0)
    return id_map


def _restored(anki, ledger, row, open_store, word_of=None):
    """An Undo's import done (or a kill after it): cards home, the library's record and the shelf's rows back, the
    tidy `undone`."""
    notes = json.loads(row["notes"])
    id_map = _match(anki, row, notes)
    deleted = [int(n) for n in json.loads(row["deleted"] or "[]")]
    again = _mined_again(anki, row, deleted, set(id_map.values()), open_store, word_of)
    if not id_map and set(deleted) - again:
        _not_back(ledger, row["id"])        # a kill before the import took: nothing came back, its Undo stays
        return {"id": row["id"], "back": 0, "missing": deleted, "skipped": [], "pending": False}
    # left out: the copies deleted again now, and (a kill's second look) the ones already deleted again before
    skipped = _left_out(anki, row, notes, id_map, again & set(id_map)) | (again - set(id_map))
    id_map = {old: new for old, new in id_map.items() if old not in skipped}
    _cards_home(anki, row["id"], notes, id_map)
    made = json.loads(row["made"] or "{}")
    stored = True
    if open_store is not None and made:
        stored = False
        try:
            store = open_store()
            if store is not None:
                from app.connect import library
                with store:
                    library.remake(store, made, id_map)
                stored = True
        except Exception:
            log.exception("Connect's tidy: the library's record couldn't be put back just now; tried again next time")
    with ledger.transaction():
        if stored:
            ledger.conn.execute("UPDATE tidies SET state = ?, undone_at = ? WHERE id = ?", (UNDONE, _now(), row["id"]))
        ledger.carry_homes(id_map)          # a note the import gave a new id is home in the same deck (Kyou-SH4)
        if ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shelf'").fetchone():
            for old, new in id_map.items():
                ledger.conn.execute("UPDATE shelf SET back_at = NULL, back_by = NULL, note_id = ? WHERE note_id = ? AND "
                                    "back_by = 'tidied'", (new, old))
    return {"id": row["id"], "back": len(id_map),
            "missing": [n for n in deleted if n not in id_map and n not in skipped], "skipped": sorted(skipped),
            "pending": not stored}


def _mined_again(anki, row, deleted, back, open_store, word_of=None):
    """F5 (Kyou-SH3): the tidied notes (`deleted`, old ids) whose word has a card Surasura made again since — the
    word climbed back and Connect mined it: the made-words record holds another note for it made after the tidy (a
    note id is its creation time; not one of this tidy's, nor of `back`, their copies in Anki now — a second card the
    word had before the tidy doesn't count), and Anki has that note. Their Undo would make two cards for one word, so
    they're left out (`_left_out`). A note the record never held (a remake's card from before Surasura) is read by
    its word field (`word_of(the note as the backup keeps it)`, REMAKE; none given: not read). No store: none."""
    if open_store is None or not deleted:
        return set()
    wanted = {int(n) for n in deleted}
    words = {}
    for _item, word, ids, _at, _batch in (json.loads(row["made"] or "{}").get("words") or ()):
        for n in ids:
            if int(n) in wanted:
                words.setdefault(int(n), set()).add(word)
    if word_of is not None and wanted - set(words):
        for info in _backed_up(row):
            note_id = int(info.get("noteId") or 0)
            if note_id in wanted and note_id not in words:
                word = word_of(info)
                if word:
                    words[note_id] = {word}
    if not words:
        return set()
    store = open_store()
    if store is None:
        return set()
    from app.connect import library
    with store:
        now = library.word_notes(store, {w for ws in words.values() for w in ws})
    ours = {int(n) for n in json.loads(row["notes"])} | {int(n) for n in back}
    since = (undo._epoch(row["at"]) or 0) * 1000
    others = sorted({n for ids in now.values() for n in ids if n not in ours and n > since})
    there = {int(i["noteId"]) for i in (anki.notes(others) if others else []) if isinstance(i, dict) and i.get("noteId")}
    return {old for old, ws in words.items() if any(set(now.get(w) or ()) & there for w in ws)}


def _backed_up(row):
    """The notes a tidy's backup keeps (its notes.json, as Anki described them) -> [], unreadable."""
    try:
        with open(os.path.join(row["folder"], "notes.json"), encoding="utf-8") as f:
            return [n for n in json.load(f).get("notes") or () if isinstance(n, dict)]
    except (OSError, ValueError, AttributeError, TypeError):
        return []


def _left_out(anki, row, notes, id_map, again):
    """The imported copies of `again` deleted again — only a note whose every card is still in the tidy's own deck
    (just imported) and has no line in Anki's review log (never answered since) — with a clip of theirs no other note
    uses -> the old ids left out."""
    if not again:
        return set()
    there = set(anki.find_cards(f'"deck:{TEMP_DECK.format(id=row["id"])}"') or ())
    new = {id_map[old]: old for old in again}
    copies = [i for i in anki.notes(sorted(new)) if isinstance(i, dict) and i.get("cards")
              and all(int(c) in there for c in i["cards"])]
    reviewed = anki.reviewed([int(c) for i in copies for c in i["cards"]]) if copies else set()
    if reviewed is None:
        return set()                # the log can't be read: nothing deleted, they come back
    drop = [int(i["noteId"]) for i in copies if not any(int(c) in reviewed for c in i["cards"])]
    if not drop:
        return set()
    anki.delete_notes(drop)
    for name in sorted({m for n in drop for m in (notes.get(str(new[n])) or {}).get("media") or ()}):
        if not anki.users(name):
            anki.delete_media(name)
    return {new[n] for n in drop}


# --------------------------------------------------------------------------- #
# The window's presses (on a worker): *Tidy now*, *Undo*
# --------------------------------------------------------------------------- #
def act(settings, language, steps=None):
    """*Tidy now* (Settings): Connect's count read now, then a tidy past the cap -> {"cards": deleted, "id"} or
    {"cards": 0, "say": why nothing}. Raises `app.cli.contract.CliError` in plain words, as `undo.act` does."""
    from app.cli.contract import CliError
    from app.connect import runner
    if not (settings or {}).get("connect_enabled"):
        return {"cards": 0, "say": undo.PREVIEW_OFF}
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return {"cards": 0, "say": undo.NO_ANKI}
    from app.connect.ledger import Ledger, path
    if not os.path.exists(path()):
        raise CliError("bad-data", undo.NO_LEDGER)
    steps = steps or runner.Steps(settings, live=True)

    def tidy_now(ledger):
        try:
            return steps.tidy(language, ledger, now=True) or {"cards": 0, "say": NOTHING}
        except runner.Wait as e:                # the library or Anki busy just now: said, nothing deleted
            raise CliError("busy", e.reason) from None
        except runner.Needs as e:
            raise CliError("needs-you", e.say) from None
    return _guarded(settings, tidy_now, Ledger)


def act_undo(settings, language, tidy_id):
    """*Undo* a tidy (Needs you) -> {"back", "missing"}. Raises CliError in plain words."""
    from app.connect import library
    from app.connect.ledger import Ledger, path
    from app.cli.contract import CliError
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return {"back": 0, "missing": [], "say": undo.NO_ANKI}
    if not os.path.exists(path()):
        raise CliError("bad-data", undo.NO_LEDGER)
    from app import anki_connect
    anki = AnkiConnectTidy(anki_connect.address(settings))
    return _guarded(settings, lambda ledger: restore(anki, ledger, tidy_id, lambda: library.open_store(language),
                                                     language=language, word_of=card_word_of(settings, language)),
                    Ledger)


def act_past(language):
    """*Put back…*'s list (`past`), read from Connect's ledger (no Anki) -> [] when Connect hasn't made a card yet."""
    from app.connect.ledger import Ledger, path
    if not os.path.exists(path()):
        return []
    with Ledger() as ledger:
        return past(ledger, language)


# --------------------------------------------------------------------------- #
# *Make my new cards again…* (REMAKE, 3.0.19; Sonic's § 98, the lead's rulings 2026-11-25; words PROVISIONAL)
# --------------------------------------------------------------------------- #
# Tidy with no cap: every card in Surasura's deck for the language that was never reviewed (`why_kept`'s REMAKE
# mode), backed up and read back, deleted, its words freed — then each freed word queued again as a best-sentence
# job at its best line (`requeue`), so Connect makes it again in the normal order, the cap holding it. Anki syncs
# before the count and again before the delete (`synced`): a review on the phone not yet synced must never read as
# never reviewed. Undo, *Needs you* and *Put back…* are Tidy's own.
SYNC_OK = ("synced", "not-signed-in")       # a profile with no AnkiWeb login has no other device's reviews to bring
SYNC_FULL = "Anki wants a full sync first (it asks you which side to keep). Sync in Anki, then try again."
SYNC_BUSY = "Anki is busy just now (syncing or checking its collection). Try again in a moment."
SYNC_FAILED = ("Anki couldn't sync with AnkiWeb just now, so a card you studied on your phone might not be in yet. "
               "Nothing was deleted: try again once Anki syncs.")
NOTHING_NEW = "No card in Surasura's deck is waiting unstudied: there's nothing to make again."
REMAKE_ALL_KEPT = "Every unstudied card there is yours to keep (moved, flagged or marked by you): nothing was deleted."


def package_timeout(notes):
    """How long one Anki package of `notes` notes may take to export or import (seconds): PACKAGE_S, and
    PACKAGE_NOTE_S a note past the first 600 (Tidy's tens fit the 300 s; a remake's thousands don't)."""
    return PACKAGE_S + max(0, int(notes) - 600) * PACKAGE_NOTE_S


def synced(anki):
    """Anki's own sync with AnkiWeb, asked now under the write lock (`anki.sync`), so a card studied on another
    device reads as studied -> its answer; raises Refused in plain words when it didn't sync."""
    answer = str(anki.sync() or "failed")
    if answer in SYNC_OK:
        return answer
    raise Refused(SYNC_FULL if answer == "full-sync" else SYNC_BUSY if answer == "busy" else SYNC_FAILED)


def _all_made(open_store):
    """Every note the language's made-words record holds -> a set (none with no store)."""
    store = open_store() if open_store is not None else None
    if store is None:
        return set()
    from app.connect import library
    with store:
        return {int(n) for n in library.made_notes(store)}


def remake_decks(ledger, settings, language, made):
    """Surasura's decks for `language`: the deck it shows for new cards (`fields.surasura_deck`) and each deck it put
    one of `made` in (the ledger's `homes`) -> sorted."""
    from app.connect import fields
    decks = set(ledger.homes(made).values()) if made else set()
    decks.add(fields.surasura_deck(settings, language))
    return sorted(d for d in decks if d)


def remake_notes(anki, decks):
    """The notes with a card new in one of `decks` itself, never in a subdeck (`is:new`: suspended and buried ones
    too; a card reset to new as well — `why_kept` reads its review log) -> sorted. One search a deck."""
    from app import anki_connect
    found = set()
    for deck in decks:
        d = anki_connect.escape_query(deck)
        found |= {int(n) for n in anki.find_notes(f'deck:"{d}" -deck:"{d}::*" is:new') or ()}
    return sorted(found)


def connect_models(anki, made):
    """The note type Connect mines into, as its newest card still in Anki has it -> frozenset (none: empty)."""
    newest = sorted(made)[-CHUNK:]
    infos = [n for n in (anki.notes(newest) if newest else []) if isinstance(n, dict) and n.get("noteId")]
    if not infos:
        return frozenset()
    model = max(infos, key=lambda n: int(n["noteId"])).get("modelName")
    return frozenset({model}) if model else frozenset()


def remake_plan(anki, ledger, language, settings, open_store):
    """What *Make my new cards again…* finds now, read-only (the caller holds the write lock: Anki's review log is
    read under it) -> {"decks", "made": [note ids made by Surasura that go],
    "before": [note ids from before Surasura, of Connect's note type, that go with the tick], "kept": {why: n},
    "models"}."""
    ensure(ledger)
    made_all = _all_made(open_store)
    decks = remake_decks(ledger, settings, language, made_all)
    ids = remake_notes(anki, decks) if decks else []
    models = connect_models(anki, made_all)
    made_ids = _made_notes(open_store, ids)
    asked = asked_for(ledger, language, ids, REMAKE)
    read, known = _shelf_read(ledger), _known_terms(settings)
    go, kept = [], {}
    for at in range(0, len(ids), CHUNK):
        g, k, _i, _c = check(anki, ledger, ids[at:at + CHUNK], made_ids, asked, frozenset(decks), mode=REMAKE,
                             before=models, known=known, read=read)
        go += g
        for _n, why in k:
            kept[why] = kept.get(why, 0) + 1
    return {"decks": decks, "made": [n for n in go if n in made_ids], "before": [n for n in go if n not in made_ids],
            "kept": kept, "models": sorted(models)}


def _known_terms(settings):
    from app.connect import known_signal
    return tuple(known_signal.terms(settings))


def remake(anki, ledger, language, settings, open_store, before=False):
    """*Make my new cards again…*: the plan read again, then `run` in REMAKE mode (no cap; Anki synced under the lock
    first; `before`: the cards from before Surasura too) -> `run`'s answer. Raises as `run` does (Refused
    `NOTHING_NEW` when there's nothing to remove)."""
    made_all = _all_made(open_store)
    decks = remake_decks(ledger, settings, language, made_all)
    ids = remake_notes(anki, decks) if decks else []
    if not ids:
        raise Refused(NOTHING_NEW)
    try:
        return run(anki, ledger, language, ids, why=REMAKE, open_store=open_store, limit=None, ours=decks,
                   before=connect_models(anki, made_all) if before else frozenset(), known=_known_terms(settings),
                   sync=True)
    except Refused as e:
        if e.say == ALL_KEPT:
            raise Refused(REMAKE_ALL_KEPT) from None
        raise


def requeue(steps, ledger, language, done, settings=None, open_store=None):
    """The words a remake freed, queued again (the lead's ruling 4): each as a best-sentence job (`level.BEST`: kept
    past a watched episode, held by the cap) at its best line (`sentences.choose`, one call for every word; Nearest:
    the removed card's own episode), grouped one job an item, in one ledger transaction -> {"queued": words,
    "ahead": words no job can take now (an episode's job already running there, no line found): they come back as
    Connect meets them}. A card Surasura made: its word and reading from Connect's ledger, only when the record freed
    it and holds it nowhere else now (`open_store`: a word with a card in another episode, or one you deleted there
    on purpose, stays made). A card from before: its word field's word (the known-words sync's field), only while the
    list holds it."""
    from app.connect import level, sentences
    row = tidy_row(ledger, done["id"])
    deleted = {int(n) for n in json.loads(row["deleted"] or "[]")}
    freed = set(done.get("freed") or ()) - _made_words(open_store)
    item_of = {}
    for item, _word, ids, _at, _batch in (json.loads(row["made"] or "{}").get("words") or ()):
        for n in ids:
            if int(n) in deleted:
                item_of[int(n)] = item
    own, keys = {}, set()
    made = sorted(item_of)
    for at in range(0, len(made), CHUNK):
        chunk = made[at:at + CHUNK]
        for note_id, word, reading in ledger.conn.execute(
                f"SELECT note_id, word, reading FROM outcomes WHERE note_id IN ({','.join('?' * len(chunk))}) AND "
                "outcome = 'made'", chunk):
            if word in freed:
                keys.add((word, reading))
                own.setdefault((word, reading), item_of[int(note_id)])
    legacy = deleted - set(item_of)
    if legacy:
        keys |= _listed_keys_of(ledger, language, settings, row, legacy)
    best = {}
    if keys and sentences.dial_of(settings) == sentences.BEST:
        mines = getattr(steps, "mines", None)
        try:
            found = sentences.choose(language, sorted(keys), dial=sentences.BEST, top=1,
                                     reach=lambda item_id: steps.video(language, {"item_id": item_id}) is not None,
                                     books=bool(mines is not None and mines(language, "books")))
            best = {k: v[0].item_id for k, v in found.items() if v and v[0].item_id is not None}
        except Exception as e:      # never the remake's fault: the removed cards' own episodes, as Nearest
            log.info("Connect's remake: best sentences not read (%s): %s", language, e)
    store_id = steps.store_id(language)
    queued, ahead = 0, 0
    with ledger.transaction():
        tries = [best, own]
        left = sorted(keys)
        for where in tries:
            by_item = {}
            for k in left:
                if where.get(k) is not None:
                    by_item.setdefault(where[k], []).append(k)
            took = set()
            for item, ks in sorted(by_item.items()):
                if ledger.queue_level(language, item, ks, source=level.BEST, store_id=store_id) is not None:
                    took |= set(ks)
            queued += len(took)
            left = [k for k in left if k not in took]
        ahead = len(left)
    return {"queued": queued, "ahead": ahead}


def _made_words(open_store):
    """Every word the made-words record holds now, any episode (`library.made_words_all`) -> a set; none, no store."""
    store = open_store() if open_store is not None else None
    if store is None:
        return set()
    from app.connect import library
    with store:
        return library.made_words_all(store)


def _listed_keys_of(ledger, language, settings, row, notes):
    """The list's keys of the words the cards from before held (`notes`; their word field as the backup keeps it,
    `anki_sync._note_word`) -> a set; none while Connect has read no list."""
    _sig, listed = ledger.recorded_list(language)
    if not listed:
        return set()
    by_word = {}
    for word, reading in listed:
        by_word.setdefault(word, []).append((word, reading))
    word_of = card_word_of(settings, language)
    out = set()
    for info in _backed_up(row):
        if int(info.get("noteId") or 0) in notes:
            out |= set(by_word.get(word_of(info)) or ())
    return out


def card_word_of(settings, language):
    """A card's word as the known-words sync reads its word field (`anki_sync._note_word`) -> fn(note) -> word."""
    from app import anki_sync
    fields = list(((settings or {}).get("anki_sync_fields") or {}).get(language) or [])
    return lambda info: anki_sync._note_word(info, fields, language)


def act_remake_plan(settings, language, anki=None):
    """The sheet's count (on a worker): under the write lock (Anki's review log is read under it, as Tidy's every
    read), Anki synced, then `remake_plan` -> its answer, or {"say": why nothing} (Connect off, Anki switched off).
    Nothing is written but the sync. Raises CliError in plain words."""
    from app.connect import library
    from app.connect.ledger import Ledger
    off = _remake_off(settings)
    if off:
        return off
    if anki is None:
        from app import anki_connect
        anki = AnkiConnectTidy(anki_connect.address(settings))

    def plan(ledger):
        with anki.writer(VERB):
            if anki.reviewing():
                raise Reviewing()
            synced(anki)
            return remake_plan(anki, ledger, language, settings, lambda: library.open_store(language))
    return _guarded(settings, plan, Ledger)


def act_remake(settings, language, before=False, steps=None, anki=None):
    """*Make my new cards again…*'s yes (on a worker): `remake`, then its freed words queued again (`requeue`) and
    Connect woken -> {"cards", "id", "kept", "queued", "ahead"}, or {"cards": 0, "say": why nothing}. Raises CliError
    in plain words (reviewing, another writer, Anki closed, the sync's words, nothing to make again)."""
    from app.connect import library, runner
    from app.connect.ledger import Ledger
    off = _remake_off(settings)
    if off:
        return off
    if anki is None:
        from app import anki_connect
        anki = AnkiConnectTidy(anki_connect.address(settings))
    steps = steps or runner.Steps(settings, live=True)

    def go(ledger):
        done = remake(anki, ledger, language, settings, lambda: library.open_store(language), before=before)
        again = requeue(steps, ledger, language, done, settings, lambda: library.open_store(language))
        return {"cards": len(done["deleted"]), "id": done["id"], "kept": len(done["kept"]), **again}
    out = _guarded(settings, go, Ledger)
    try:
        from app.connect import kick
        kick.kick(settings)
    except Exception:
        log.info("Connect's remake: Connect not woken now (its next look mines them)", exc_info=True)
    return out


def _remake_off(settings):
    """Why the remake can't run at all now -> {"cards": 0, "say": …}, or None. Raises CliError with no ledger."""
    from app.cli.contract import CliError
    from app.connect.ledger import path
    if not (settings or {}).get("connect_enabled"):
        return {"cards": 0, "say": undo.PREVIEW_OFF}
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return {"cards": 0, "say": undo.NO_ANKI}
    if not os.path.exists(path()):
        raise CliError("bad-data", undo.NO_LEDGER)
    return None


def _guarded(settings, fn, Ledger):
    from app import anki_connect, locks
    from app.cli import contract
    from app.cli.contract import CliError
    from app.connect.ledger import TooNew
    try:
        with Ledger() as ledger:
            done = fn(ledger)
        undo.owe_sync(settings)
        return done
    except TooNew as e:
        raise CliError("needs-you", str(e), ask="Update Surasura") from None
    except Refused as e:
        raise CliError("bad-data", e.say) from None
    except Reviewing:
        raise CliError("anki-busy", undo.REVIEWING) from None
    except locks.Busy as e:
        raise contract.busy_error("anki-writer", e.holder, undo.WRITER_BUSY) from None
    except anki_connect.AnkiError as e:
        raise CliError("anki-closed", f"Anki isn't open (or stopped answering): {e}") from None
    except (sqlite3.Error, OSError) as e:
        raise CliError("failed", undo.RECORDS + (str(e).splitlines() or [type(e).__name__])[0][:160]) from None
