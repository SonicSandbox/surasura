"""*Undo this batch* (P2.5 row 2.5.5; P1.5 02-data-model N9, 03-actors §2, 06-edges E31; ✅ Q2-6: "undoing a bad
batch", touching only cards the suite made and nobody studied) and the shelf put back (row 2.5.6, Sonic's gate (b)).

- **What goes:** the notes one finished job made (its `made` outcomes, N9) that still carry **its** tag
  (`surasura::connect::<job>`), whose every card was never studied (no review, still new), none suspended by you
  (the shelf's own suspend doesn't count), and that weren't changed since Connect last touched them (the job's end,
  or the shelf's own tag writes; a 5 s grace) — your edit or tag keeps a card. Everything else stays and is listed
  with why. A job still running is refused.
- **How:** `plan` first (read-only: what would go, what stays); `run` holds Anki's write lock (`anki-writer`), is
  never written while you review (K88), plans again under the lock, deletes the notes (`deleteNotes`), then their
  clip and picture once no other note uses them. Then the ledger (the undo recorded, the job `undone`, its item's
  needs fixed) and the store, one short write (`library.unmake`): **the gone notes' words are free again** (ASK-SONIC
  P2.5-1 ⭐: an undo says "this batch was wrong"; a card you delete by hand is still never made again, G1.3-4) and the
  item's receipt is cleared when nothing of it is left. The episode isn't mined again by itself: only when you place
  it into the top 20 again. Anki's sync is owed (the session's rule, P2.3).
- **The shelf put back** (`restore_shelf`): `shelf.restore` for one restore point. Who took a card off the shelf is
  recorded (✅ Sonic 2026-10-08, P2.5-2): you (put back here, or un-suspended in Anki) → never shelved again, at the
  cap Connect waits; Surasura (the swap-in: its word relevant again) → it may be shelved again later.

The window's only in 2.x (it warns first: this can't be undone, K33); `surasura-cli undo --job N --confirm` /
`--shelf RUN --confirm` (without `--confirm`, the plan). Anki through the adapter it is handed (`AnkiConnectUndo`;
tests hand a fake).
"""
import datetime
import re

from app.connect import runfile

GRACE_S = 5                     # a note changed this long after Connect's own last write is still Connect's
STILL_RUNNING = "Connect is still making this episode's cards. Undo it once they're made."
NOTHING = "This batch has no cards to undo."
_SOUND = re.compile(r"\[sound:([^\]]+)\]")
_IMG = re.compile(r"""<img[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)

# Why a card stays (the list the window shows)
STUDIED = "you've studied it"
CHANGED = "it was changed after it was made"
SUSPENDED = "you suspended it"
NOT_ITS_TAG = "it doesn't carry this batch's tag"


class Reviewing(Exception):
    """You started reviewing: nothing was deleted."""


class Refused(Exception):
    """The batch can't be undone (still running, nothing to undo): `say` in plain words."""

    def __init__(self, say):
        super().__init__(say)
        self.say = say


class AnkiConnectUndo:
    """Undo's Anki: AnkiConnect, loopback."""

    def __init__(self, url):
        self.url = url

    def notes(self, ids):
        from app import anki_connect
        return anki_connect.notes_info(self.url, ids)

    def cards(self, ids):
        from app import anki_connect
        return anki_connect.cards_info(self.url, ids)

    def reviewing(self):
        from app import anki_connect
        return anki_connect.reviewing(self.url)

    def writer(self, verb):
        from app import anki_connect
        return anki_connect.writer(verb, wait=10.0)

    def delete_notes(self, ids):
        from app import anki_connect
        anki_connect.invoke("deleteNotes", self.url, notes=list(ids))

    def users(self, name):
        from app.connect import media_names
        return media_names.AnkiConnectMedia(self.url).users(name)

    def delete_media(self, name):
        from app import anki_connect
        anki_connect.invoke("deleteMediaFile", self.url, filename=name)


def _epoch(utc_text):
    try:
        return datetime.datetime.strptime(utc_text[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _shelf_rows(ledger):
    """{card id: (on the shelf now, the latest shelf write's epoch)} from the ledger's shelf table (none: {})."""
    if not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shelf'").fetchone():
        return {}
    out = {}
    for card, shelved, back in ledger.conn.execute("SELECT card_id, shelved_at, back_at FROM shelf"):
        on = back is None
        latest = max(t for t in (_epoch(shelved), _epoch(back), 0) if t is not None)
        had = out.get(card, (False, 0))
        out[card] = (had[0] or on, max(had[1], latest))
    return out


def _job(ledger, job_id):
    job = ledger.job_by_id(job_id)
    if job is None:
        raise Refused(NOTHING)
    from app.connect.ledger import OPEN
    if job["state"] in OPEN:
        raise Refused(STILL_RUNNING)
    return job


def plan(anki, ledger, job_id):
    """What *Undo this batch* would do now, read-only -> {"job", "item", "delete": [note ids], "keep": [[note id,
    word, why], …], "gone": [note ids already gone from Anki], "words": {note id: word}}. Raises Refused."""
    job = _job(ledger, job_id)
    words = {}
    for o in ledger.outcomes(job_id):
        if o["outcome"] == "made" and o["note_id"] is not None:
            words[int(o["note_id"])] = o["word"]
    if not words or job["state"] == "undone":
        raise Refused(NOTHING)
    tag = runfile.job_tag(job["tag"]).lower()
    done_at = _epoch(job.get("updated_at")) or 0
    shelf = _shelf_rows(ledger)
    infos = {int(n["noteId"]): n for n in anki.notes(sorted(words)) if isinstance(n, dict) and n.get("noteId")}
    card_ids = sorted({int(c) for n in infos.values() for c in n.get("cards") or ()})
    cards = {int(c["cardId"]): c for c in (anki.cards(card_ids) if card_ids else []) if isinstance(c, dict)}
    out = {"job": job_id, "item": job["item_id"], "language": job["language"], "delete": [], "keep": [],
           "gone": [], "words": words}
    for note_id in sorted(words):
        info = infos.get(note_id)
        if info is None:
            out["gone"].append(note_id)
            continue
        why = _why_kept(info, cards, tag, done_at, shelf)
        if why:
            out["keep"].append([note_id, words[note_id], why])
        else:
            out["delete"].append(note_id)
    return out


def _why_kept(info, cards, tag, done_at, shelf):
    """Why one note stays, or None when it can go."""
    if tag not in {str(t).lower() for t in info.get("tags") or ()}:
        return NOT_ITS_TAG
    touched = done_at
    mine = [cards.get(int(c)) for c in info.get("cards") or ()]
    for card_id in info.get("cards") or ():
        touched = max(touched, shelf.get(int(card_id), (False, 0))[1])
    for card in mine:
        if card is None:
            return STUDIED                  # a card Anki didn't describe: never deleted unread
        if int(card.get("reps") or 0) > 0 or int(card.get("type") or 0) != 0:
            return STUDIED
        if int(card.get("queue") or 0) == -1 and not shelf.get(int(card["cardId"]), (False, 0))[0]:
            return SUSPENDED
    mod = info.get("mod")
    if mod is not None and touched and float(mod) > touched + GRACE_S:
        return CHANGED
    return None


def _media(info):
    """The file names a note's fields point at (its clip and picture)."""
    names = set()
    for field in (info.get("fields") or {}).values():
        value = field.get("value", "") if isinstance(field, dict) else str(field or "")
        names.update(_SOUND.findall(value))
        names.update(_IMG.findall(value))
    return names


def run(anki, ledger, job_id, open_store=None):
    """*Undo this batch*: plan again under Anki's write lock, record the undo **before** Anki is written (a kill after
    the delete is finished by the next look, `finish_pending`), delete what may go and its unused media, then finish
    -> the plan as done, with "deleted" (note ids gone now), "freed" (words free again) and "placed_again" (whether
    placing the episode into the top 20 again makes its cards again). Raises Reviewing, Refused, the lock's Busy and
    AnkiConnect's errors (an undo recorded but not begun is finished as nothing deleted)."""
    for pending in ledger.pending_undos(ledger.job_by_id(job_id)["language"] if ledger.job_by_id(job_id) else ""):
        if pending["job_id"] == job_id:     # a kill left this one half-way: finish it, then plan what's left
            finish(anki, ledger, pending, open_store)
    with anki.writer("Connect's undo"):
        done = plan(anki, ledger, job_id)
        if anki.reviewing():
            raise Reviewing()
        undo_id = ledger.start_undo(job_id, done["language"], done["delete"] + done["gone"], done["keep"])
        media = set()
        if done["delete"]:
            for info in anki.notes(done["delete"]):
                if isinstance(info, dict):
                    media |= _media(info)
            anki.delete_notes(done["delete"])
            for name in sorted(media):
                if not anki.users(name):
                    anki.delete_media(name)
    pending = {"id": undo_id, "job_id": job_id, "language": done["language"],
               "deleted": done["delete"] + done["gone"], "kept": done["keep"]}
    return dict(done, **finish(anki, ledger, pending, open_store))


def finish(anki, ledger, pending, open_store=None):
    """An undo recorded before Anki was written, finished: which of its notes are gone now (Anki read), those words
    freed in the store (✅ P2.5-1), the shelf's rows of their cards closed, the job `undone` and its item's needs
    fixed -> {"deleted", "keep", "freed", "placed_again"}. `open_store()`: the library store (or None), opened only
    after Anki has answered — never held across an Anki call (L3.3). Raises AnkiConnect's errors (left pending)."""
    job = ledger.job_by_id(pending["job_id"]) or {}
    planned = [int(n) for n in pending["deleted"]]
    still = {int(n["noteId"]) for n in (anki.notes(planned) if planned else [])
             if isinstance(n, dict) and n.get("noteId")}
    gone = [n for n in planned if n not in still]
    words = {}
    for o in ledger.outcomes(pending["job_id"]):
        if o["outcome"] == "made" and o["note_id"] is not None:
            words[int(o["note_id"])] = o["word"]
    keep = [list(k) for k in pending["kept"]] + [[n, words.get(n), "Anki didn't delete it"] for n in sorted(still)]
    freed = []
    store = open_store() if open_store is not None and gone else None
    if store is not None:
        from app.connect import library
        with store:
            freed = library.unmake(store, job.get("item_id"), gone, {words[n] for n in gone if n in words})
    with ledger.transaction():
        ledger.finish_undo(pending["id"], gone, keep)
        if job.get("state") != "undone":
            ledger.set_state(pending["job_id"], "undone", reason="you undid this batch")
        ledger.fix(pending["language"], item_id=job.get("item_id"))
        _close_shelf(ledger, gone)
    placed_again = not ledger.mined(pending["language"], job.get("item_id"))
    return {"deleted": gone, "keep": keep, "freed": freed, "placed_again": placed_again}


def _close_shelf(ledger, note_ids):
    """The shelf's rows of deleted notes leave the shelf (they are no longer on it; intent keeper P2.5 #9)."""
    if not note_ids or not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shelf'"
                                               ).fetchone():
        return
    from app.connect import shelf
    shelf.ensure(ledger)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger.conn.executemany("UPDATE shelf SET back_at = ?, back_by = 'undone' WHERE note_id = ? AND back_at IS NULL",
                            [(now, int(n)) for n in note_ids])


def finish_pending(anki, ledger, language, open_store=None):
    """Every undo a kill left half-way, finished (a Connect run's first look at Anki) -> how many."""
    pending = ledger.pending_undos(language)
    for row in pending:
        finish(anki, ledger, row, open_store)
    return len(pending)


def restore_shelf(anki, ledger, run_id):
    """The shelf put back by you: `shelf.restore(run)` -> how many cards came back (recorded as yours: never shelved
    again, ✅ P2.5-2)."""
    from app.connect import shelf
    return shelf.restore(anki, ledger, run_id)


def summary(done):
    """A plan or an undo, as the window and the command line say it."""
    out = {"job": done["job"], "item": done["item"], "delete": len(done["delete"]), "gone": len(done["gone"]),
           "keep": [{"note": n, "word": w, "why": why} for n, w, why in done["keep"]]}
    if "deleted" in done:
        out["deleted"] = len(done["deleted"])
        out["freed"] = done.get("freed") or []
        out["placed_again"] = bool(done.get("placed_again"))
        out["say"] = (f"{len(done['deleted'])} cards deleted." + (
            " Place the episode in your top 20 again to make its cards again." if done.get("placed_again") else
            " Another batch of this episode is still in Anki, so placing it again makes no new cards."))
    return out
