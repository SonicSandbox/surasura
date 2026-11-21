"""Tidy: Connect's backlog cleared (Kyou-SH2, 3.0.18; Sonic 2026-11-20 plan v2 point 3, 2026-11-21 MODEL.md round 3:
"Clutter would want to be automatic too … Maybe 1.5x the cap (connects cards plus the overflow) or something that is
quickly evaluated"; ROLES.md: Tidy keeps Anki uncluttered and never deletes without a backup).

- **When:** by itself when the cards waiting for a language (the cap's window + its overflow: what Connect's count
  saw, `runner.Steps.waiting_count`, plus Connect's own waiting cards off your list and the ones on its old shelf)
  pass **1.5 × the cap** (`THRESHOLD`); and on your press (*Tidy now*, Settings), whenever more than the cap wait. A
  quick check: the count Connect already read and the ledger, no Anki call (`choose`). No cap (0): never.
- **What goes:** only **Connect's own cards you never studied** past the window, the lowest in the study order first
  (off your list and set aside first, then a finished show's), as many as wait past the cap (yours past it stay). Never yours (no
  `surasura::connect::` tag, or not in Connect's made words), never a pinned show's or an episode you asked for,
  never a card studied, suspended by you, buried, flagged, in a filtered deck or changed after it was made — each
  read again under Anki's write lock, as *Undo this batch* reads them (`undo._why_kept`).
- **A backup first, byte for byte:** the notes and cards as Anki describes them (`notes.json`), their clip and
  picture files (`media/`, with each file's sha1), and an Anki package of exactly those notes, scheduling included
  (`cards.apkg`: their cards moved into a deck of their own, `TEMP_DECK`, exported, the package opened and its note
  ids checked) — in Connect's folder, `tidy/<id>/`, kept. Nothing is deleted unless the package holds every note.
- **Then:** the notes deleted (`deleteNotes`) and their media once no other note uses it (Anki's media trash), the
  words freed in the library (**Surasura's delete**: `library.unmake`, so N15 — a card you deleted is never made
  again — doesn't hold them; they're mined again if they climb back), the shelf's rows of those cards closed.
  Recorded in Connect's ledger (`tidies`) **before** Anki is written; a kill half-way is finished at the next look
  (`finish_pending`: cards left in the deck of its own go back).
- **Undo** (`restore`): the media put back where Anki lacks it, the package imported, each card moved back to its
  deck, the library's made words, receipts and lines back as they were (`library.remake`), the shelf's rows back.
- **Said in the window:** *Needs you* — *N set-aside cards tidied.* · *Undo* · *OK* (`status`'s `tidied`).

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
AUTO, NOW = "auto", "now"                   # why a tidy ran: by itself, or your press
FILTERED = "it's in a filtered deck"

Reviewing = undo.Reviewing


class Refused(Exception):
    """Nothing to tidy, or a tidy that can't be undone (gone, undone already): `say` in plain words."""

    def __init__(self, say):
        super().__init__(say)
        self.say = say


NOTHING = "Nothing to tidy: no more cards wait than your limit."
ALL_KEPT = "the cards past your limit are yours to keep: studied, changed or set aside by you."
NOT_UNDOABLE = "That tidy can't be undone now."
NOT_SAVED = "Anki didn't save a copy of the cards, so nothing was deleted."

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
# state: writing (recorded, Anki maybe written) -> done (deleted, words freed) | failed (nothing deleted) ->
# restoring (Undo recorded, Anki maybe written) -> undone
WRITING, DONE, FAILED, RESTORING, UNDONE = "writing", "done", "failed", "restoring", "undone"


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

    def export_package(self, deck, path):
        from app import anki_connect
        return anki_connect.invoke("exportPackage", self.url, timeout=300, deck=deck, path=path,
                                   includeSched=True) is True

    def import_package(self, path):
        from app import anki_connect
        return anki_connect.invoke("importPackage", self.url, timeout=300, path=path) is True

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
    row = ledger.conn.execute("SELECT j.updated_at FROM outcomes o JOIN jobs j ON j.id = o.job_id WHERE o.note_id = ? "
                              "AND o.outcome = 'made' ORDER BY o.job_id DESC LIMIT 1", (int(note_id),)).fetchone()
    return undo._epoch(row[0]) if row else None


def check(anki, ledger, note_ids):
    """Read under the lock: which of `note_ids` may go now -> (go [note ids], kept [[note id, why]], infos {id: note},
    cards {id: card}). A note Anki no longer has is neither."""
    infos = {int(n["noteId"]): n for n in anki.notes(sorted({int(n) for n in note_ids}))
             if isinstance(n, dict) and n.get("noteId")}
    card_ids = sorted({int(c) for n in infos.values() for c in n.get("cards") or ()})
    cards = {int(c["cardId"]): c for c in (anki.cards(card_ids) if card_ids else []) if isinstance(c, dict)
             and c.get("cardId")}
    filtered = set()
    found = getattr(anki, "find_cards", None)
    for at in range(0, len(card_ids), CHUNK) if found else ():
        filtered |= set(found("deck:filtered cid:" + ",".join(map(str, card_ids[at:at + CHUNK]))) or ())
    shelf = undo._shelf_rows(ledger)
    go, kept = [], []
    for note_id in [int(n) for n in dict.fromkeys(note_ids) if int(n) in infos]:     # in the order asked: lowest first
        info = infos[note_id]
        tag = _connect_tag(info)
        why = undo.NOT_ITS_TAG if tag is None else undo._why_kept(info, cards, tag, _done_at(ledger, note_id) or 0,
                                                                 shelf)
        if why is None and any(int(c) in filtered for c in info.get("cards") or ()):
            why = FILTERED
        if why:
            kept.append([note_id, why])
        else:
            go.append(note_id)
    return go, kept, infos, cards


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


def package_notes(path):
    """The note ids an Anki package holds, or None when it can't be read (no collection inside, a damaged file)."""
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
                        return {int(r[0]) for r in conn.execute("SELECT id FROM notes")}
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
def run(anki, ledger, language, note_ids, why=AUTO, open_store=None, limit=None):
    """Tidy `note_ids` (`candidates`, lowest first): under Anki's write lock, read again (`check`, a chunk at a time
    until `limit` may go), recorded in the ledger (with the library's made-words rows of those notes) before Anki is
    written, backed up (`_backup`: refused → nothing deleted), deleted, then finished (`finish`: the words freed) ->
    {"id", "deleted", "kept", "freed", "pending"}. Raises Reviewing, Refused (none may go: `ALL_KEPT`; `NOT_SAVED`),
    the lock's Busy, AnkiConnect's errors."""
    ensure(ledger)
    ids = [int(n) for n in dict.fromkeys(note_ids)]
    limit = len(ids) if limit is None else int(limit)
    with anki.writer(VERB):
        if anki.reviewing():
            raise Reviewing()
        for pending in pending_tidies(ledger, language):      # a kill's half-way tidy first, under this lock
            finish(anki, ledger, pending, open_store)
        go, kept, infos, cards = [], [], {}, {}
        for at in range(0, len(ids), CHUNK):
            if len(go) >= limit:
                break
            g, k, i, c = check(anki, ledger, ids[at:at + CHUNK])
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
        try:
            _backup(anki, infos, cards, go, tidy_id, folder)
        except Exception:
            _fail(anki, ledger, tidy_id, notes)
            raise
        # read once more just before the delete: a card you answered or changed while Anki exported stays (its card
        # back home); the package may hold it too, and Undo leaves a note Anki still has as it is
        still, late, _i, _c = check(anki, ledger, go)
        if late:
            _cards_home(anki, tidy_id, {k: v for k, v in notes.items() if int(k) in {int(n) for n, _w in late}})
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


def _backup(anki, infos, cards, go, tidy_id, folder):
    """notes.json + media/ + cards.apkg in `folder`; the package must hold exactly `go` (else Refused(NOT_SAVED))."""
    os.makedirs(os.path.join(folder, "media"), exist_ok=True)
    record = {"notes": [infos[n] for n in go], "cards": [cards[int(c)] for n in go for c in infos[n].get("cards") or ()
                                                       if int(c) in cards], "media": {}}
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
    deck = TEMP_DECK.format(id=tidy_id)
    card_ids = [int(c) for n in go for c in infos[n].get("cards") or ()]
    anki.change_deck(card_ids, deck)
    package = os.path.join(folder, "cards.apkg")
    if not anki.export_package(deck, package) or package_notes(package) != set(go):
        raise Refused(NOT_SAVED)


def _fail(anki, ledger, tidy_id, notes):
    """The backup didn't hold (or you started reviewing): every card back in its deck, nothing deleted, the tidy
    `failed`. A move home that fails leaves it `writing`: the next look (`finish`) puts the cards home."""
    try:
        _cards_home(anki, tidy_id, notes)
    except Exception:
        log.exception("Connect's tidy: its cards couldn't go back to their decks now; the next look does it")
        return
    with ledger.transaction():
        ledger.conn.execute("UPDATE tidies SET state = ?, deleted = '[]', finished_at = ? WHERE id = ?",
                            (FAILED, _now(), tidy_id))


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
    made = json.loads(row["made"] or "{}")
    by_item = {}
    for item, word, ids, _at, _batch in made.get("words") or ():
        for n in ids:
            if int(n) in gone:
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
    kept = json.loads(row["kept"] or "[]") + [[n, "Anki didn't delete it"] for n in sorted(still)]
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
def restore(anki, ledger, tidy_id, open_store=None, language=None):
    """*Undo* a tidy: under Anki's write lock, recorded first (`restoring`), the media Anki lacks put back from the
    backup's bytes, the package imported, each card moved back to its deck, the library's record back
    (`library.remake`), the shelf's rows back -> {"id", "back" (notes in Anki again), "missing" (notes not found
    after the import)}. Raises Refused (`NOT_UNDOABLE`), Reviewing, the lock's Busy, AnkiConnect's errors."""
    row = tidy_row(ledger, tidy_id)
    if row is None or row["state"] != DONE or (language is not None and row["language"] != language):
        raise Refused(NOT_UNDOABLE)
    package = os.path.join(row["folder"], "cards.apkg")
    if not os.path.exists(package):
        raise Refused(NOT_UNDOABLE)
    with anki.writer(VERB):
        if anki.reviewing():
            raise Reviewing()
        with ledger.transaction():
            ledger.conn.execute("UPDATE tidies SET state = ? WHERE id = ?", (RESTORING, row["id"]))
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
        return dict(_restored(anki, ledger, row, open_store), media_missing=lost)


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


def _restored(anki, ledger, row, open_store):
    """An Undo's import done (or a kill after it): cards home, the library's record and the shelf's rows back, the
    tidy `undone`."""
    notes = json.loads(row["notes"])
    id_map = _match(anki, row, notes)
    if not id_map and json.loads(row["deleted"] or "[]"):
        _not_back(ledger, row["id"])        # a kill before the import took: nothing came back, its Undo stays
        return {"id": row["id"], "back": 0, "missing": json.loads(row["deleted"] or "[]"), "pending": False}
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
        if ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shelf'").fetchone():
            for old, new in id_map.items():
                ledger.conn.execute("UPDATE shelf SET back_at = NULL, back_by = NULL, note_id = ? WHERE note_id = ? AND "
                                    "back_by = 'tidied'", (new, old))
    deleted = [int(n) for n in json.loads(row["deleted"] or "[]")]
    return {"id": row["id"], "back": len(id_map), "missing": [n for n in deleted if n not in id_map],
            "pending": not stored}


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
                                                     language=language), Ledger)


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
