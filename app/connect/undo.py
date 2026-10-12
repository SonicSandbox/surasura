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
import logging
import os
import re
import sqlite3

from app.connect import runfile

log = logging.getLogger("surasura-cli")
GRACE_S = 5                     # a note changed this long after Connect's own last write is still Connect's
STILL_RUNNING = "Connect is still making this episode's cards. Undo it once they're made."
NOTHING = "This batch has no cards to undo."
_SOUND = re.compile(r"\[sound:([^\]]+)\]")
_IMG = re.compile(r"""<img[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)

# Why a card stays (the list the window shows)
STUDIED = "you've studied it"
CHANGED = "it was changed after it was made"
SUSPENDED = "you suspended it"
BURIED = "you buried it"
FLAGGED = "you flagged it"
NOT_ITS_TAG = "it doesn't carry this batch's tag"
DEFAULT = object()              # `open_store` not given: the job's language's library store


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
    """{card id: (on the shelf now, [(epoch of a shelf write, the note's mod just before it), ...])} from the ledger's
    shelf table (none: {}). A write whose mod wasn't read carries None: the note is kept (it may hide your edit)."""
    if not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shelf'").fetchone():
        return {}
    from app.connect import shelf
    shelf.ensure(ledger)
    out = {}
    for card, shelved, back, mod_shelved, mod_back in ledger.conn.execute(
            "SELECT card_id, shelved_at, back_at, mod_shelved, mod_back FROM shelf"):
        on, events = out.get(card, (False, []))
        events = events + [(_epoch(shelved), mod_shelved)]
        if back is not None:
            events.append((_epoch(back), mod_back))
        out[card] = (on or back is None, events)
    return out


def _changed(mod, done_at, events):
    """Was the note changed by anyone but Connect since the batch ended? Walks Connect's own writes in time order: a
    mod read just before a shelf write that is past the previous write (+ the grace) is your edit, which the shelf's
    write then hid; the note's mod now past the last write (+ the grace) is too. Unknown → changed (kept)."""
    if not done_at or not isinstance(mod, (int, float)) or isinstance(mod, bool):
        return True                         # when, or whether, it changed can't be read: never deleted unread
    last = done_at
    for at, before in sorted((e for e in events if e[0] is not None), key=lambda e: e[0]):
        if at < last:
            continue                        # a write before the batch ended (another batch's note history)
        if not isinstance(before, (int, float)) or isinstance(before, bool) or before > last + GRACE_S:
            return True
        last = at
    return float(mod) > last + GRACE_S


def _job(ledger, job_id, language=None):
    job = ledger.job_by_id(job_id)
    if job is None or (language is not None and job["language"] != language):
        raise Refused(NOTHING)
    from app.connect.ledger import OPEN
    if job["state"] in OPEN:
        raise Refused(STILL_RUNNING)
    return job


def plan(anki, ledger, job_id, language=None):
    """What *Undo this batch* would do now, read-only -> {"job", "item", "delete": [note ids], "keep": [[note id,
    word, why], …], "gone": [note ids already gone from Anki: deleted by you, their words stay blocked], "words":
    {note id: word}}. `language`: the window's (D31): a batch of another language is refused. Raises Refused."""
    job = _job(ledger, job_id, language)
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
    events = []
    mine = [cards.get(int(c)) for c in info.get("cards") or ()]
    for card_id in info.get("cards") or ():
        events += shelf.get(int(card_id), (False, []))[1]
    for card in mine:
        if card is None:
            return STUDIED                  # a card Anki didn't describe: never deleted unread
        if int(card.get("reps") or 0) > 0 or int(card.get("type") or 0) != 0:
            return STUDIED
        if int(card.get("queue") or 0) == -1 and not shelf.get(int(card["cardId"]), (False, []))[0]:
            return SUSPENDED
        if int(card.get("queue") or 0) == -3:
            return BURIED
        if int(card.get("flags") or 0) != 0:
            return FLAGGED                  # a flag is a card's mark, not the note's: its mod doesn't move (#3)
    if _changed(info.get("mod"), done_at, events):
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


def run(anki, ledger, job_id, open_store=DEFAULT, language=None):
    """*Undo this batch*: plan again under Anki's write lock, record the undo **before** Anki is written (a kill after
    the delete is finished by the next look, `finish_pending`), delete what may go and its unused media, then finish
    -> the plan as done, with "deleted" (note ids gone now), "freed" (words free again) and "placed_again" (whether
    placing the episode into the top 20 again makes its cards again). `open_store()`: the library store (default:
    the job's language's); `language`: the window's (D31). Raises Reviewing, Refused, the lock's Busy and
    AnkiConnect's errors (an undo recorded but not begun is finished as nothing deleted)."""
    job = _job(ledger, job_id, language)
    if open_store is DEFAULT:
        open_store = _store_opener(job["language"])
    earlier = None
    for pending in ledger.pending_undos(job["language"]):
        if pending["job_id"] == job_id:     # a kill left this one half-way: finish it, then plan what's left
            earlier = finish(anki, ledger, pending, open_store)
    with anki.writer("Connect's undo"):
        try:
            done = plan(anki, ledger, job_id, language)
        except Refused:
            if earlier is None:
                raise
            return dict({"job": job_id, "item": job["item_id"], "language": job["language"], "delete": [],
                         "gone": [], "words": {}}, **earlier)      # that finish was the undo (adversary P2.5 #8)
        if anki.reviewing():
            raise Reviewing()
        undo_id = ledger.start_undo(job_id, done["language"], done["delete"], done["keep"])
        media = set()
        if done["delete"]:
            for info in anki.notes(done["delete"]):
                if isinstance(info, dict):
                    media |= _media(info)
            anki.delete_notes(done["delete"])
            for name in sorted(media):
                if not anki.users(name):
                    anki.delete_media(name)
    pending = {"id": undo_id, "job_id": job_id, "language": done["language"], "deleted": done["delete"],
               "kept": done["keep"]}
    return dict(done, **finish(anki, ledger, pending, open_store))


def _store_opener(language):
    def open_store():
        from app.connect import library
        return library.open_store(language)
    return open_store


def _no_store(language):
    """No library store at all for the language (JSON mode): nothing holds the words, nothing to free."""
    try:
        from app import library_store
        from app.path_utils import get_data_path
        import os
        return not os.path.exists(library_store.library_db_path(language, get_data_path(language)))
    except Exception:
        return False


def finish(anki, ledger, pending, open_store=None):
    """An undo recorded before Anki was written, finished: which of its notes are gone now (Anki read), those words
    freed in the store (✅ P2.5-1), the shelf's rows of their cards closed, the job `undone` and its item's needs
    fixed -> {"deleted", "keep", "freed", "placed_again", "pending"}. `open_store()`: the library store (or None),
    opened only after Anki has answered — never held across an Anki call (L3.3); when it can't be opened or written
    just now, the undo stays pending (`pending`: its words are freed by the next look, `finish_pending`). Raises
    AnkiConnect's errors (left pending)."""
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
    freed, receipt_left, stored = [], None, True
    if open_store is not None and gone:
        stored = False              # the store busy or not ready: the undo stays pending, its words freed next time
        try:
            store = open_store()
            if store is not None:
                from app.connect import library
                with store:
                    freed = library.unmake(store, job.get("item_id"), gone, {words[n] for n in gone if n in words})
                    receipt_left = library.mined_at(store, job.get("item_id")) is not None
                stored = True
            elif _no_store(pending["language"]):
                stored = True       # JSON mode: no made words anywhere (placing again is decided by the ledger)
        except Exception:
            log.exception("Connect's undo: the library couldn't free the words just now; tried again next time")
    with ledger.transaction():
        if stored:
            ledger.finish_undo(pending["id"], gone, keep)
        if gone:                    # nothing gone (a kill before Anki's delete, every card kept): the job stays as it
            if job.get("state") != "undone":        # was, so it can be undone later
                ledger.set_state(pending["job_id"], "undone", reason="you undid this batch")
            ledger.fix(pending["language"], item_id=job.get("item_id"))
            _close_shelf(ledger, gone)
    # placing the episode again makes its cards again only when neither the store's receipt nor a done job holds it
    placed_again = bool(gone) and stored and not receipt_left and not ledger.mined(pending["language"],
                                                                                   job.get("item_id"))
    return {"deleted": gone, "keep": keep, "freed": freed, "placed_again": placed_again, "pending": not stored}


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


def restore_shelf(anki, ledger, run_id, language=None):
    """The shelf put back by you: `shelf.restore(run)` with the shelf's Anki adapter (`shelf.AnkiConnectAnki`) -> how
    many cards came back (recorded as yours: never shelved again, ✅ P2.5-2). `language`: the window's (D31): a
    restore point of another language is refused."""
    from app.connect import shelf
    if language is not None and not any(r["run"] == run_id for r in shelf.runs(ledger, language)):
        raise Refused("There's no shelf restore point with that name.")
    return shelf.restore(anki, ledger, run_id)


PREVIEW_OFF = "connect preview off"
NO_ANKI = "Anki is switched off for this run (SURASURA_NO_ANKI_SYNC)"
NO_LEDGER = "Connect hasn't made any cards here yet."
NO_SHELF_RUN = "There's no shelf restore point with that name."
NEEDS_JUNBAN = "Putting the shelf back needs Junban (順), which isn't installed."
REVIEWING = "You're reviewing in Anki. Undo once you've finished."
WRITER_BUSY = "Another program is writing to Anki. Try again in a moment."
RECORDS = "Connect's records couldn't be written just now: "


def act(settings, language, job=None, shelf_run=None, confirm=False, sync=None):
    """*Undo this batch* (`job`) or a shelf restore point put back (`shelf_run`), as the command line's `undo` and the
    window both do it (P3.1 row 3.1.5: one sequence, so the two never drift) -> the answer, the command line's own:
    {"skipped": why} (the preview off; Anki switched off for this run); without `confirm` the plan, nothing written
    (`summary(plan)` + {"language", "confirm": False}, or the shelf run's row + the same); with it what was done
    (`summary(done)` + {"language", "confirm": True}, or {"language", "shelf", "back", "confirm": True}), Anki's sync
    owed after (`sync(settings)`; default `owe_sync`). The ledger is never made here: none yet is
    *nothing made*. Raises `app.cli.contract.CliError` in plain words (`message`; `code` the command line's exit:
    not-set-up, bad-data, needs-you, skipped, anki-busy, busy, anki-closed, failed — the ledger or the library locked or
    unwritable, `RECORDS`). Waits up to 10 s for Anki's write lock:
    the window calls it on a worker, never the Tk thread."""
    from app.cli.contract import CliError
    if not (settings or {}).get("connect_enabled"):
        return {"skipped": PREVIEW_OFF}
    from app.cli.verbs import require_set_up
    require_set_up(language)
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):         # the test suites, a developer's run: Anki is never reached
        return {"skipped": NO_ANKI}
    from app import anki_connect, locks
    from app.cli import contract
    from app.connect import library, shelf
    from app.connect.ledger import Ledger, TooNew, path
    if not os.path.exists(path()):                      # Ledger() would make one
        raise CliError("bad-data", NO_LEDGER)
    anki = AnkiConnectUndo(anki_connect.address(settings))
    sync = sync or owe_sync
    try:
        with Ledger() as ledger:
            if shelf_run is not None:
                point = next((r for r in shelf.runs(ledger, language) if r["run"] == shelf_run), None)
                if point is None:
                    raise CliError("bad-data", NO_SHELF_RUN, shelf=shelf_run)
                if not confirm:
                    return dict(point, language=language, confirm=False)
                try:
                    back = restore_shelf(shelf.AnkiConnectAnki(anki.url), ledger, shelf_run, language=language)
                except ImportError:
                    raise CliError("skipped", NEEDS_JUNBAN) from None
                sync(settings)
                return {"language": language, "shelf": shelf_run, "back": back, "confirm": True}
            row = ledger.job_by_id(job)
            if row is None or row["language"] != language:
                raise CliError("bad-data", f"There's no batch {job} in the {language} library.", job=job)
            if not confirm:
                return dict(summary(plan(anki, ledger, job, language)), language=language, confirm=False)
            done = run(anki, ledger, job, open_store=lambda: library.open_store(language), language=language)
            sync(settings)
            return dict(summary(done), language=language, confirm=True)
    except TooNew as e:
        raise CliError("needs-you", str(e), ask="Update Surasura") from None
    except Refused as e:
        raise CliError("bad-data", e.say, job=job) from None
    except (Reviewing, shelf.Reviewing):
        raise CliError("anki-busy", REVIEWING) from None
    except locks.Busy as e:
        raise contract.busy_error("anki-writer", e.holder, WRITER_BUSY) from None
    except anki_connect.AnkiError as e:
        raise CliError("anki-closed", f"Anki isn't open (or stopped answering): {e}") from None
    except (sqlite3.Error, OSError) as e:               # the ledger or the library locked, a disk refusing a write
        raise CliError("failed", RECORDS + (str(e).splitlines() or [type(e).__name__])[0][:160]) from None


def owe_sync(settings):
    """Cards deleted or back from the shelf change tomorrow's cards: the session's sync (P2.3), sent by Connect (a
    kick). Never fails the undo."""
    try:
        from app.cli.verbs import _sync_pending
        from app.connect import anki_session
        _sync_pending(settings, anki_session.after_write(settings, True))
    except Exception:
        log.exception("the sync after an undo wasn't arranged")


def summary(done):
    """A plan or an undo, as the window and the command line say it."""
    out = {"job": done["job"], "item": done["item"], "delete": len(done["delete"]), "gone": len(done["gone"]),
           "keep": [{"note": n, "word": w, "why": why} for n, w, why in done["keep"]]}
    if "deleted" in done:
        out["deleted"] = len(done["deleted"])
        out["freed"] = done.get("freed") or []
        out["placed_again"] = bool(done.get("placed_again"))
        out["pending"] = bool(done.get("pending"))
        blocked = (f" {len(done['gone'])} you had deleted yourself stay deleted, and their words aren't made "
                   "again." if done.get("gone") else "")
        if not done["deleted"]:
            out["say"] = "No cards deleted: every card of this batch stays (see why)." + blocked
        elif done.get("pending"):
            out["say"] = (f"{len(done['deleted'])} cards deleted. Surasura's library was busy: Connect frees their "
                          "words at its next start." + blocked)
        else:
            out["say"] = f"{len(done['deleted'])} cards deleted." + (
                " Place the episode in your top 20 again to make its cards again." if done.get("placed_again") else
                " Some of this episode's cards are still in Anki, so placing it again makes no new cards.") + blocked
    return out
