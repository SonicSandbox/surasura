"""The swap queue (Kyou-LR, 3.0.18; the review loop's ⇄ Swap = Suspend + Green flag, WL-46b): the cards whose word
wants a better sentence, waiting for Swap to make it (Kantan-SL: a new card from the word's best other line; the full
Swap, 3.1 #385, rewrites the old card in place from the same record).

The record: `<local data>/connect/swap-queue-<lang>.json` (Connect's local data, never User Files) —
`{"version": 1, "swaps": [entry, …]}`, oldest first. An entry:

    id       "<card>-<queued ms>"            one card, one waiting entry at a time
    word     the card's Word-field word      (`known_signal._words_of`: the word only)
    card     the old card's id               note: its note's id
    queued   when the reader queued it (ISO)  sync: the review loop's sync that queued it (`review_loop`, for Undo)
    state    "waiting" · "made" · "dropped" · "undone" (made, then Swap's Undo took the new card back)
    made     {"note": the new note's id, "at": ISO} once Swap made the new card, else None (kept when undone)
    undone   when Swap's Undo took the made card back (ISO); only on an "undone" entry
    why      None, or why it was dropped: "undone" · "taken back" · "known" · "ignored"
    line_id  optional: the sentence the learner picked for the new card (the journey page's door, journey v3 SPEC §6 /
             §3.3); absent or None (a green flag from Anki) = Swap picks the line itself. Kept through Undo.

Writers, each under the known-words lock (`anki_sync.hold_known_words`: the reader holds it already), written whole
and atomic; nothing ever deletes an entry (the made ones are the record the full Swap reads):

    add(language, word, card, note, sync, line_id=None)
                                            the reader: a card newly Suspended + Green (None when it waits already);
                                            the journey's door: with the line picked
    waiting(language)                       Swap's read: the waiting entries, oldest first
    made(language, id, note)                Swap: the new card exists
    undone(language, id)                    Swap's Undo: the made card taken back (only from "made"); a card flagged
                                            green again later queues a new entry
    drop(language, id, why)                 Swap: the word is now Known / Ignored ("known" · "ignored"); the reader:
                                            "taken back" (the old card no longer Suspended + Green), "undone"
    drop_sync(language, sync, why)          the reader's Undo: that sync's waiting entries

A deleted old card keeps its entry waiting (the learner still wants the word). Qt-free; standard library only.
"""
import contextlib
import datetime
import json
import os
import time

VERSION = 1
WAITING, MADE, DROPPED, UNDONE = "waiting", "made", "dropped", "undone"
WHY = ("undone", "taken back", "known", "ignored")
VERB = "The swap queue"


class Unreadable(RuntimeError):
    """The queue exists but can't be read: nothing is written over it."""


def path(language):
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect", f"swap-queue-{language}.json")


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


@contextlib.contextmanager
def _held(language):
    from app import anki_sync
    held, refused = anki_sync.hold_known_words(language, VERB)
    if refused is not None:
        raise RuntimeError(refused[0])
    try:
        yield
    finally:
        if held is not None:
            held.release()


def load(language):
    """The queue's entries ([] when there's none yet); raises `Unreadable` when it exists and can't be read."""
    try:
        with open(path(language), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise Unreadable(f"The swap queue can't be read ({e}); it was left as it is.") from None
    swaps = data.get("swaps") if isinstance(data, dict) else None
    if not isinstance(swaps, list):
        raise Unreadable("The swap queue isn't what it should be; it was left as it is.")
    return [s for s in swaps if isinstance(s, dict)]


def _save(language, swaps):
    from app import anki_sync
    os.makedirs(os.path.dirname(path(language)), exist_ok=True)
    anki_sync._atomic_write_json(path(language), {"version": VERSION, "swaps": swaps}, indent=1)


def waiting(language):
    """The waiting entries, oldest first (Swap's read)."""
    return [dict(s) for s in load(language) if s.get("state") == WAITING]


def add(language, word, card, note, sync, line_id=None):
    """A card newly Suspended + Green (or a swap asked on the journey page, with the `line_id` picked), queued -> its
    entry; None when that card waits already."""
    with _held(language):
        swaps = load(language)
        if any(s.get("card") == card and s.get("state") == WAITING for s in swaps):
            return None
        entry = {"id": f"{card}-{int(time.time() * 1000)}", "word": word, "card": card, "note": note,
                 "queued": _now(), "sync": sync, "state": WAITING, "made": None, "why": None}
        if line_id is not None:
            entry["line_id"] = line_id
        _save(language, swaps + [entry])
        return entry


def _change(language, pick, state, frm=WAITING, **values):
    with _held(language):
        swaps = load(language)
        hit = [s for s in swaps if s.get("state") == frm and pick(s)]
        for s in hit:
            s["state"] = state
            s.update(values)
        if hit:
            _save(language, swaps)
        return [dict(s) for s in hit]


def made(language, swap_id, note):
    """Swap made the new card (`note`: its note id) -> the entry, or None when no waiting entry has that id."""
    hit = _change(language, lambda s: s.get("id") == swap_id, MADE, made={"note": note, "at": _now()})
    return hit[0] if hit else None


def undone(language, swap_id):
    """Swap's Undo took the made card back -> the entry (its `made` kept, `undone` the time), or None when no made
    entry has that id. The queue stays the one record of a swap: nothing is deleted."""
    hit = _change(language, lambda s: s.get("id") == swap_id, UNDONE, frm=MADE, undone=_now())
    return hit[0] if hit else None


def drop(language, swap_id, why):
    """A waiting entry dropped (`why`, one of WHY) -> the entry, or None."""
    if why not in WHY:
        raise ValueError(f"no such reason: {why!r}")
    hit = _change(language, lambda s: s.get("id") == swap_id, DROPPED, why=why)
    return hit[0] if hit else None


def drop_cards(language, cards, why):
    """The waiting entries of these old cards dropped -> the entries."""
    cards = set(cards)
    return _change(language, lambda s: s.get("card") in cards, DROPPED, why=why) if cards else []


def drop_sync(language, sync, why="undone"):
    """The waiting entries a sync queued dropped (its Undo) -> the entries; a made one stays made."""
    return _change(language, lambda s: s.get("sync") == sync, DROPPED, why=why)
