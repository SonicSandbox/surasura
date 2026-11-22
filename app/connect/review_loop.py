"""The review loop's reader (Kyou-LR, 3.0.18; the loop's wave 2, lane 1; design: the window track's WL notes, the
moves ruled 2026-11-20 — WL-36, WL-46, WL-46b).

The learner answers a card on their phone with one of three moves, each *suspend, plus why*:

    ✓ Known   Suspend + Mark (or the signal they chose: *Count as known in Anki*, `known_from_anki`; WL-12)
    ⇄ Swap    Suspend + Green flag (flag:3)    a better sentence, please: the word stays one to learn
    ✕ Ignore  Suspend + Red flag (flag:1)      not a word to learn

A plain suspend means nothing; red and green never count as known, and win over every other state.

**Each known-words sync** (`anki_sync.sync_all` → `read_known_signal`, while Connect is on) reads them here, in the
sync's decks: Known first, as before (`known_signal.read`: its one-time offer, its record, `knownBy: anki-signal`),
then ONE `multi` of findCards for the two others (never a card Surasura suspended, nor a leech: `known_signal._never`
without its flags). A card newly carrying a move since the last read, per Anki profile, is read for its Word field's
word (`known_signal._words_of`, the word only), and:

- **Ignore** → the word on the Ignore list (`word_marks.apply(..., unknow=True)`, the list's own writer: its lock, its
  backups) — and, when another source counted it known already (a studied card the plain sync read before the flag:
  Kotoba-WS2's note a), its known entries turned not known (**the move rule**: an ignored word is no known word).
- **Swap** → the word Still learning (its known entries turned not known, the same rule; nothing when it wasn't known)
  and **a swap queued** (`app/connect/swap_queue.py`, the record Swap reads). When one word has both in one sync,
  Ignore wins (Swap never makes a card for an ignored word).
- **Known** after the loop moved that word before (a red card unflagged, then suspended and marked): the loop's mark
  is cleared, so the word is known and off the Ignore list.
- **A card's newest move wins** (red, later green: off the Ignore list, a swap queued). The list's own state machine
  does it (`word_marks`: the last mark wins).
- A swap card **taken back** (still in Anki, no longer Suspended + Green) before Swap made its card: its entry dropped.
  A deleted card keeps its entry (the learner still wants the word).

**Undo per sync** (`undo`): each read that moved something is one *sync* in the record (its id, the Known words, the
list changes with each word's state before): Undo puts each word back **while it is still as that sync left it**
(a later move of the same word stands), takes the Known words it marked out (`known_signal.undo(..., cards_too=False)`),
and drops its waiting swaps; twice is nothing more. **No card is ever touched** — no suspend, flag, tag, unsuspend or
delete — and Anki is only read (findCards, cardsInfo, notesInfo): so a review going on is never disturbed, and there is
nothing to hold for one (Haya-LD2's rule is for writers). An undone card stays read while it keeps its move (it isn't
moved again until it loses the move and gets it back).

**The payoff** (`read`'s `loop`: {"sync", "known", "swap", "ignored", "unknown"}) is the window's *From your phone*
toast with Undo — only when the phone sent something (WL-7).

The record: `<local data>/connect/review-loop-<lang>.json` (Connect's local data, never User Files), under the
known-words lock; one that exists but can't be read stops the read and is never written over. Standard library only;
Anki through `app/anki_connect` (loopback).
"""
import datetime
import json
import os
import time

from app.connect import known_signal, swap_queue

VERB = "The review loop"
IGNORE, SWAP = "ignore", "swap"
MOVES = {IGNORE: "is:suspended flag:1", SWAP: "is:suspended flag:3"}      # Suspend + Red · Suspend + Green
KEEP_SYNCS = 30             # the newest syncs kept for Undo


class Unreadable(RuntimeError):
    """The record exists but can't be read: nothing is written over it."""


def record_path(language):
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect", f"review-loop-{language}.json")


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load(language):
    try:
        with open(record_path(language), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise Unreadable(f"The review loop's record can't be read ({e}); it was left as it is.") from None
    if not isinstance(data, dict):
        raise Unreadable("The review loop's record isn't what it should be; it was left as it is.")
    return data


def _save(language, data):
    from app import anki_sync
    os.makedirs(os.path.dirname(record_path(language)), exist_ok=True)
    anki_sync._atomic_write_json(record_path(language), data, indent=1)


def query(move, decks, settings=None):
    """The search for the cards carrying `move` in `decks` (never one Surasura suspended, never a leech), or None."""
    if not decks:
        return None
    from app import anki_connect
    scope = " OR ".join(f'deck:"{anki_connect.escape_query(d)}"' for d in dict.fromkeys(decks))
    never = [t for t in known_signal._never(settings) if not t.startswith("-flag:")]
    return f"({scope}) {MOVES[move]} " + " ".join(never)


def _found(url, queries):
    """{move: set of card ids} in ONE request; raises AnkiError when a slot fails (nothing is read this time)."""
    from app import anki_connect
    from app.anki_connect import AnkiError
    replies = list(anki_connect.multi([{"action": "findCards", "params": {"query": q}} for q in queries.values()],
                                      url) or [])
    out = {}
    for move, reply in zip(queries, replies + [None] * len(queries)):
        if not isinstance(reply, dict) or reply.get("error") is not None or not isinstance(reply.get("result"), list):
            error = reply.get("error") if isinstance(reply, dict) else None
            raise AnkiError(f"Anki could not search your decks: {error or 'no answer'}", kind="action")
        out[move] = set(anki_connect._int_ids(reply["result"]))
    return out


def _ints(values):
    out = set()
    for v in values or ():
        try:
            out.add(int(v))
        except (TypeError, ValueError):
            continue
    return out


def read(language, url, decks, fields, settings):
    """One read, beside the known-words sync -> `known_signal.read`'s answer, plus `loop`: the payoff
    ({"sync": its id, "known": n, "swap": n, "ignored": n, "unknown": n known words taken out}) when the phone sent
    something, else None (and `loop_error` when the moves couldn't be read or written this time)."""
    out = dict(known_signal.read(language, url, decks, fields, settings) or {})
    out["loop"] = None
    queries = {m: query(m, decks, settings) for m in MOVES}
    if not decks:
        return out
    from app import anki_connect
    from app.services import word_marks
    if known_signal.SIGNAL_WORD_ONLY:
        fields = list(fields or [])[:1]
    with known_signal._held(language, VERB):
        state = load(language)
        try:
            profile = str(anki_connect.invoke("getActiveProfile", url) or "")
            found = _found(url, queries)
            seen_all = state.setdefault("seen", {})
            seen = {m: _ints((seen_all.get(profile) or {}).get(m)) for m in MOVES}
            new = {m: sorted(found[m] - seen[m]) for m in MOVES}
            move_of = {c: m for m in MOVES for c in new[m]}
            words = known_signal._words_of(url, new[IGNORE] + new[SWAP], fields, language) if move_of else []
        except anki_connect.AnkiError as e:     # Anki closed or busy mid-read: the Known words stand, the rest waits
            out["loop_error"] = str(e)
            return out
        sync = str(int(time.time() * 1000))
        cards = state.setdefault("cards", {})
        # Known after a move of the loop's: the loop's mark cleared (known, and off the Ignore list)
        moved_words = {r.get("word") for r in cards.values() if not r.get("undone")}
        known_words = list(out.get("marked") or ())
        marks = [(w, None) for w in known_words if w in moved_words]
        marks += [(w, "learning") for w, c, _n in words if move_of.get(c) == SWAP]
        marks += [(w, "ignore") for w, c, _n in words if move_of.get(c) == IGNORE]    # last: Ignore wins
        changes, known_before = [], set()
        if marks:
            from app import anki_sync
            try:
                _data, entries = anki_sync._read_known_file(language)
                known_before = anki_sync._known_keys(entries or [])
            except anki_sync._KnownFileError:
                pass                                        # word_marks says why below, writing nothing
            done = word_marks.apply(language, marks, undoable=False, unknow=True)
            if done.error is not None:
                out["loop_error"] = done.error              # nothing written: read again at the next sync
                return out
            changes = [{"word": w, "before": b, "after": a} for w, b, a in done.done]
        ignored = sorted({w for w, c, _n in words if move_of.get(c) == IGNORE})
        queued = []
        for w, c, n in words:
            if move_of.get(c) == SWAP and w not in ignored and swap_queue.add(language, w, c, n, sync) is not None:
                queued.append(w)
            cards[str(c)] = {"move": move_of.get(c), "word": w, "note": n, "sync": sync, "at": _now()}
        _taken_back(language, url, seen[SWAP] - found[SWAP])
        unknown = sum(1 for c in changes if c["after"] in (IGNORE, "learning")
                      and word_marks._norm(c["word"]) in known_before)     # known words the move rule took out
        payoff = {"sync": sync, "known": len(known_words), "swap": len(set(queued)),
                  "ignored": len({c["word"] for c in changes if c["after"] == IGNORE}), "unknown": unknown}
        moved = payoff["known"] or payoff["swap"] or payoff["ignored"]
        if moved:
            syncs = state.setdefault("syncs", [])
            syncs.append({"id": sync, "at": _now(), "known": known_words, "changes": changes,
                          "swaps": sorted(set(queued)), "undone": None})
            del syncs[:-KEEP_SYNCS]
            out["loop"] = payoff
        now_seen = {m: sorted(found[m]) for m in MOVES}
        if moved or words or seen_all.get(profile) != now_seen:
            seen_all[profile] = now_seen
            state["read"] = _now()
            _save(language, state)          # nothing new, nothing written (charter S19)
        return out


def _taken_back(language, url, gone):
    """The swap cards no longer Suspended + Green: those still in Anki were taken back — their waiting entries dropped;
    a deleted card (cardsInfo has nothing for it) keeps its entry."""
    if not gone:
        return
    try:
        waiting = {s.get("card") for s in swap_queue.waiting(language)}
    except swap_queue.Unreadable as e:
        print(f"The review loop: {e}")
        return
    ask = sorted(c for c in gone if c in waiting)
    if not ask:
        return
    from app import anki_connect
    still = {c.get("cardId") for c in known_signal._chunked(anki_connect.cards_info, url, ask)
             if isinstance(c, dict) and c.get("cardId") is not None}
    swap_queue.drop_cards(language, still, "taken back")


def syncs(language):
    """The syncs kept for Undo, newest last."""
    return list(load(language).get("syncs") or ())


def undo(language, sync_id):
    """One sync's moves undone (see the module docstring) -> {"undone": bool, "words": [words put back], "kept":
    [words a later move changed since, left as they are]}. Raises when the known words are being written by another
    program, or a list can't be written: nothing changed then (the next press asks again)."""
    from app.services import word_marks
    with known_signal._held(language, f"{VERB} (undo)"):
        state = load(language)
        sync = next((s for s in state.get("syncs") or () if s.get("id") == sync_id), None)
        if sync is None or sync.get("undone"):
            return {"undone": False, "words": [], "kept": []}
        changes = list(sync.get("changes") or ())
        now = word_marks.states(language, [c["word"] for c in changes])
        back = [(c["word"], c["before"]) for c in reversed(changes) if now.get(c["word"]) == c["after"]]
        kept = [c["word"] for c in changes if now.get(c["word"]) != c["after"]]
        if back:
            done = word_marks.apply(language, back, undoable=False, unknow=True)   # an Ignore put back is the
            if done.error is not None:                                              # loop's: no known word
                raise RuntimeError(done.error)
        for word in sync.get("known") or ():
            known_signal.undo(language, word, None, cards_too=False)
        swap_queue.drop_sync(language, sync_id, "undone")
        stamp = _now()
        for record in (state.get("cards") or {}).values():
            if record.get("sync") == sync_id:
                record["undone"] = stamp
        sync["undone"] = stamp
        _save(language, state)
        words = [w for w, _b in back] + list(sync.get("known") or ()) + list(sync.get("swaps") or ())
        return {"undone": True, "words": list(dict.fromkeys(words)), "kept": kept}
