# SPDX-License-Identifier: GPL-3.0-or-later
"""The AnkiConnect wire — the only place in this module that speaks to Anki.

Standard library only (`urllib.request`, mirroring `app/update_checker.py`), loopback only, and it
never raises anything but `AnkiError`. Every function here is a thin, testable shell around one
JSON POST, so the planner above it stays pure data and the panel above that can degrade politely
when Anki is closed.

Everything below was verified live against this user's AnkiConnect (121 actions) on 2026-09-17.
These are reproduced failure modes, not defensive style — each one costs real, silent data damage:

  * **`"version": 6` goes on the envelope AND on every `multi` sub-action.** Omitted, a sub-action
    quietly defaults to version 4 and comes back as a bare result with no `{"result","error"}`
    wrapper — so the caller's error check reads a value that was never there.
  * **`due` must be sent as an `int`.** A string raises *inside* AnkiConnect and surfaces as
    `[[False, "'str' object cannot be interpreted as an integer"]]` with `error: null`, **leaving
    the old value in place**. Measured, restored, confirmed.
  * **Success for `setSpecificValueOfCard` is `result == [True]`, appended once per CALL** — not
    once per key. The README's documented `[true, true]` is simply wrong.
  * **A validation failure returns a bare `false` (or `[[False, msg]]`) with `error: null`.** A
    client that checks only `error` reports success on every silent no-op, which is the worst
    possible outcome here: the user believes their queue was reordered and it was not.
  * **No `Origin` header** is sent (the stdlib default) — that is precisely what avoids the
    permission prompt and any CORS configuration on the Anki side.

Two actions are refused at the choke point rather than left to discipline: `sync` (this module must
never push anything to AnkiWeb on the user's behalf) and `setDueDate` (it converts new cards into
review cards — the exact opposite of what this feature is for, and it would destroy a schedule).
"""

# The generic client lives in core (`app/anki_connect.py`) since the Anki known-words sync needed it
# too. Everything Junban calls is re-exported here, so every call site (`ankiconnect.invoke`,
# `ankiconnect.probe`, ...) and every test patch of `urllib.request.urlopen` keeps working unchanged.
from app import anki_connect as _core
from app.anki_connect import (API_VERSION, FORBIDDEN_ACTIONS, AnkiError, invoke, multi,  # noqa: F401
                              find_cards, cards_info, notes_info, escape_query, _chunks)

# The feature is impossible without these two, so `probe` gates the whole module on them rather
# than letting the user press Reorder and watch it fail card by card.
REQUIRED_ACTIONS = ("setSpecificValueOfCard", "multi")

# Compatibility names for Junban's existing call sites.
_escape = escape_query
find_new_cards = find_cards


# --------------------------------------------------------------------------- #
# Liveness and capability
# --------------------------------------------------------------------------- #
def probe(url, extra=()):
    """Is Anki up, and can it reorder? The core probe, gated on Junban's REQUIRED_ACTIONS plus any
    `extra` the run needs (`suspend`/`unsuspend` when the cards not on the list are suspended).
    Returns `{"ok", "version", "missing", "error"}`; never raises."""
    return _core.probe(url, required=REQUIRED_ACTIONS + tuple(extra or ()))


# --------------------------------------------------------------------------- #
# Reading the collection (Junban-specific queries)
# --------------------------------------------------------------------------- #
def new_card_query(deck):
    """The one query this module ever searches with: unsuspended new cards in `deck` (and subdecks).

    Plain `deck:"X"` includes subdecks, which is both Anki's own search semantics and what the user
    expects. The `is:new -is:suspended` half is belt; the planner's per-card `type`/`queue` check is
    braces, because this is a string and that is not.

    `-deck:filtered`: a new card pulled into a filtered deck (a leftover Custom Study session) still
    matches its home deck, and `is:new` only means card type 0 — but its `due` lives in the filtered
    range (around -100000). Gathered, it dragged `min(due)` there and moved the whole deck with it.
    """
    return f'deck:"{_escape(deck)}" is:new -is:suspended -deck:filtered'


def deck_names_with_new(url):
    """Every deck that actually holds at least one unsuspended new card, in Anki's own order.

    Filtered rather than listed whole: on the reference collection the raw list includes `Default`
    (empty) and `Migaku Reference` (2,046 cards, all suspended), and offering either as a reorder
    target is offering a no-op. One `multi` does the whole survey, so this stays a single request no
    matter how many decks the user has.
    """
    names = invoke("deckNames", url)
    names = [str(name) for name in names] if isinstance(names, list) else []
    if not names:
        return []

    replies = multi([{"action": "findCards", "params": {"query": new_card_query(name)}}
                     for name in names], url)

    keep = []
    for name, reply in zip(names, replies):
        # Decided against plain data, never against a reply's truthiness: a search that errored is
        # simply not evidence of new cards (testing.md §5.3).
        if not isinstance(reply, dict) or reply.get("error") is not None:
            continue
        found = reply.get("result")
        if isinstance(found, list) and len(found) > 0:
            keep.append(name)
    return keep


def browse(url, query, card_ids=()):
    """Anki's browser on `query`, sorted by due, the first of `card_ids` selected (backlog onboarding: *Try it on my
    cards* shows the deck's new cards with the moved ones on top) -> "sorted". An AnkiConnect that can't sort the
    browser (`reorderCards`, 2023) or select a card (`guiSelectCard`) gets the plain search instead — the cards
    alone, `cid:…` -> "plain". Opens a window and changes no card or note (`READ_ACTIONS`; the browser remembers its
    sort column); raises `AnkiError` when Anki can't be reached."""
    ids = [int(card_id) for card_id in card_ids or ()]
    try:
        invoke("guiBrowse", url, query=query, reorderCards={"order": "ascending", "columnId": "cardDue"})
        if ids:
            invoke("guiSelectCard", url, card=ids[0])
        return "sorted"
    except AnkiError as e:
        if e.kind != "action":
            raise
    invoke("guiBrowse", url, query=cards_query(ids) if ids else query)
    return "plain"


def cards_query(card_ids):
    """The search for exactly these cards (`cid:1,2,3`)."""
    return "cid:" + ",".join(str(int(card_id)) for card_id in card_ids)


def deck_config(url, deck):
    """The deck's options group. Preflight reads `new.order` from this — `0` means random insertion
    order, in which case card positions are ignored and the whole feature is a no-op."""
    config = invoke("getDeckConfig", url, deck=deck)
    return config if isinstance(config, dict) else {}


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
def _write_action(card_id, due, key="due"):
    """One `setSpecificValueOfCard` sub-action. `due` is an int by the time it gets here — see
    `set_due`, and the module docstring for what a string does. `key="flags"` writes a card's flag
    the same way (0 none … 7 purple; verified on TheBank 2026-09-23 — no `warning_check` needed)."""
    return {"action": "setSpecificValueOfCard",
            "params": {"card": card_id, "keys": [key], "newValues": [due]}}


def _verdict(reply):
    """Did this one sub-action actually write? Returns "" for success, else why not.

    The whole point of this function: AnkiConnect reports a *validation* failure as a bare `False`
    (or `[[False, message]]`) with `error: null`, so checking `error` alone reports success on a
    silent no-op. Success is `[True]` — appended once per call, not once per key.
    """
    if not isinstance(reply, dict):
        return "Anki sent no reply for this card."
    if reply.get("error") is not None:
        return str(reply["error"])

    result = reply.get("result")
    if result is False:
        return "Anki rejected the write (no reason given)."
    if not isinstance(result, list) or not result:
        return f"Unexpected reply from Anki: {result!r}"
    if result[0] is True:
        return ""
    if isinstance(result[0], list) and len(result[0]) > 1:
        return str(result[0][1])        # the [[False, "…"]] shape, message included
    return f"Anki rejected the write: {result!r}"


def set_flags(url, pairs, chunk=150):
    """Write card flags. `pairs` is `[(card_id, flag)]`; returns `(written, failures)` as `set_due`
    does, through the same verdict — a flag is a card value like `due`, and fails silently the same
    way when it is not an int."""
    prepared, failures = [], []
    for card_id, flag in pairs or []:
        try:
            prepared.append((int(card_id), int(flag)))
        except (TypeError, ValueError):
            failures.append((card_id, f"Not a flag: {flag!r}"))
    written = []
    for batch in _chunks(prepared, chunk):
        try:
            replies = multi([_write_action(card_id, flag, key="flags") for card_id, flag in batch], url)
        except AnkiError as e:
            failures.extend((card_id, str(e)) for card_id, _flag in batch)
            continue
        for index, (card_id, _flag) in enumerate(batch):
            reason = _verdict(replies[index] if index < len(replies) else None)
            if reason:
                failures.append((card_id, reason))
            else:
                written.append(card_id)
    return written, failures


def _suspend_action(action, url, card_ids, chunk=150):
    """Shared body of `suspend`/`unsuspend`: one call per chunk of cards. Judged by the error field
    alone — `suspend` answers `false` when every card was already suspended, and `unsuspend` answers
    `null` on success (both measured on TheBank, 2026-09-23)."""
    clean = []
    for card_id in card_ids or []:
        try:
            clean.append(int(card_id))
        except (TypeError, ValueError):
            continue
    done, failures = [], []
    for batch in _chunks(clean, chunk):
        try:
            invoke(action, url, cards=batch)
        except AnkiError as e:
            failures.extend((card_id, str(e)) for card_id in batch)
            continue
        done.extend(batch)
    return done, failures


def suspend(url, card_ids, chunk=150):
    """Suspend the cards not on the list, when the user asked for it (Junban_Backlog_Spec §13)."""
    return _suspend_action("suspend", url, card_ids, chunk=chunk)


def unsuspend(url, card_ids, chunk=150):
    """Unsuspend, on restore — only ever the cards Junban itself suspended (`undo.restore_suspended`)."""
    return _suspend_action("unsuspend", url, card_ids, chunk=chunk)


def set_due(url, pairs, chunk=150, progress=None):
    """Write new queue positions. `pairs` is `[(card_id, due)]`; returns `(written, failures)`.

    `written` is the list of card ids that genuinely changed; `failures` is `[(card_id, reason)]`,
    so the panel can name the cards rather than showing a bare count. Nothing raises: a run that
    loses Anki halfway through must still report what it managed, because the snapshot is the only
    undo there is and a half-written run has to be describable.

    Chunked at ~150 by default. AnkiConnect is single-threaded on Anki's Qt GUI thread with a 25 ms
    poll, so one enormous `multi` freezes Anki with no progress bar and no cancel — and gives no
    partial-progress checkpoint if it dies.
    """
    prepared, failures = [], []
    for card_id, due in pairs:
        try:
            # int() is the guard, not a convenience: a str `newValue` fails INSIDE AnkiConnect and
            # leaves the old position in place, reported with error: null.
            prepared.append((int(card_id), int(due)))
        except (TypeError, ValueError):
            failures.append((card_id, f"Not a whole-number position: {due!r}"))

    written = []
    total = len(prepared)
    done = 0
    stopped = ""
    for batch in _chunks(prepared, chunk):
        if stopped:
            # Anki went away mid-run. Report the rest honestly instead of hammering a dead socket.
            failures.extend((card_id, stopped) for card_id, _due in batch)
            continue
        try:
            replies = multi([_write_action(card_id, due) for card_id, due in batch], url)
        except AnkiError as e:
            stopped = str(e)
            failures.extend((card_id, stopped) for card_id, _due in batch)
            continue

        for index, (card_id, _due) in enumerate(batch):
            reply = replies[index] if index < len(replies) else None
            reason = _verdict(reply)
            if reason:
                failures.append((card_id, reason))
            else:
                written.append(card_id)

        done += len(batch)
        if progress is not None:
            try:
                progress(done, total)
            except Exception:
                # A broken progress callback must not abandon a half-written collection.
                pass
    return written, failures


def set_due_checked(url, batches, gathered, progress=None, stop_if=None, mods=None, since=None, on_busy=None):
    """The fast re-plan's writes (E1.1 03 §3.5–6): `batches` as `spaced.requests` builds them — request
    1 tomorrow's cards, then the rest — each sent as ONE `multi`, in order. Returns `(written, failures,
    left)`.

    **Re-checked before each request:** one `cardsInfo` re-reads that request's cards, and a card that
    is no longer new (`type 0`, `queue 0`) or no longer at the position it was read at (`gathered`:
    `{card_id: due}`) is left out of this job — in `left`, for the next job to place, never written
    blind. The plan was made from a read that may be a second old by now; a card studied in that second
    is a review card, and a position written onto it would reschedule it to a garbage date (I1).

    `mods` / `since` (E3.1-B2: the warm card map read for this job, and no sync since): `{card_id: mod}` as that read
    saw each card, and the whole second from which a mod time proves nothing (the read's own, less one). Anki moves
    a card's mod time on every change — a review, a reposition, a sync bringing either — so a card whose mod time is
    still the one read, and older than `since`, is unchanged since the read: still new, still where it was read. Its
    re-check asks `cardsModTime` (no fields, no rendering); `cardsInfo` is asked for the rest only; both in one
    request with the review check (`stop_if(active)`).

    Nothing raises: once Anki stops answering, the remaining cards are failures, as `set_due` reports; a re-check
    read met by Anki busy (`anki_connect.is_busy`: its sync, Check Database, #370) leaves this and every later
    request's cards in `left` instead, and calls `on_busy()` (the caller's report says so).

    `stop_if` (the fast re-plan's automatic job: a review began): asked before every request, the first too (a
    session's sync may just have run); True leaves this and every later request's cards in `left`, for the next job.
    """
    written, failures, left = [], [], []
    total = sum(len(batch) for batch in batches or [])
    done = 0
    stopped = ""
    paused = False
    for number, batch in enumerate(batches or []):
        if stopped:
            failures.extend((card_id, stopped) for card_id, _due in batch)
            continue
        if paused:
            left.extend(card_id for card_id, _due in batch)
            continue
        ids = [card_id for card_id, _due in batch]
        try:
            if mods is None:
                if stop_if is not None:
                    try:
                        paused = bool(stop_if())
                    except Exception:
                        paused = False
                    if paused:
                        left.extend(ids)
                        continue
                sure, now = {}, {row.get("cardId"): row for row in cards_info(url, ids)}
            else:
                active, sure, now = _checked(url, ids, mods, since, stop_if is not None)
                if stop_if is not None:
                    try:
                        paused = bool(stop_if(active))
                    except Exception:
                        paused = False
                    if paused:
                        left.extend(ids)
                        continue
        except AnkiError as e:
            if _core.is_busy(e):        # Anki busy (its sync, Check Database, #370): nothing sent, the next re-order
                paused = True
                left.extend(ids)
                if on_busy is not None:
                    on_busy()
                continue
            stopped = str(e)
            failures.extend((card_id, stopped) for card_id, _due in batch)
            continue
        ready = []
        for card_id, due in batch:
            row = now.get(card_id) or {}
            if card_id in sure:
                unchanged = sure[card_id] == mods.get(card_id)
            else:
                unchanged = (row.get("type") == 0 and row.get("queue") == 0 and row.get("due") == gathered.get(card_id)
                             and all(isinstance(row.get(key), int) and not isinstance(row.get(key), bool)
                                     for key in ("type", "queue", "due")))
            if unchanged:
                ready.append((card_id, due))
            else:
                left.append(card_id)
        if ready:
            sent, refused = set_due(url, ready, chunk=len(ready))
            written.extend(sent)
            failures.extend(refused)        # Anki gone mid-request: the next request's re-read stops the rest
        done += len(batch)
        if progress is not None:
            try:
                progress(done, total)
            except Exception:
                pass                # a broken progress callback must not abandon a half-written collection
    return written, failures, left


def _checked(url, ids, mods, since, review):
    """`set_due_checked`'s re-check of one request's cards, in one request -> `(reviewing, sure, now)`: whether a
    review is on (asked only with `review`; False when Anki doesn't say), `{card id: mod time now}` for the cards
    `mods` can vouch for (read before `since`; None for a card Anki no longer has), and `{card id: cardsInfo row}`
    for the rest. An AnkiConnect that refuses `cardsModTime` gets those cards' rows instead. Raises `AnkiError`."""
    clear = [card_id for card_id in ids if since is not None and isinstance(mods.get(card_id), int)
             and not isinstance(mods.get(card_id), bool) and mods[card_id] < since]
    clear_set = set(clear)
    rest = [card_id for card_id in ids if card_id not in clear_set]
    actions = ([{"action": "guiReviewActive"}] if review else []) \
        + ([{"action": "cardsModTime", "params": {"cards": clear}}] if clear else []) \
        + ([{"action": "cardsInfo", "params": {"cards": rest}}] if rest else [])
    replies = multi(actions, url)
    if not isinstance(replies, list) or len(replies) != len(actions):
        raise AnkiError("'multi' did not answer every action.", kind="protocol")
    replies = list(replies)
    reviewing = False
    if review:
        reply = replies.pop(0)
        if isinstance(reply, dict) and reply.get("error") is not None:
            refused = _core.refusal("guiReviewActive", reply["error"])
            if refused.busy:            # no proof you aren't reviewing (an answered card is a collection operation,
                raise refused           # #370): this request and the rest wait, as for any busy read
        reviewing = isinstance(reply, dict) and reply.get("error") is None and reply.get("result") is True
    sure, unsure = {}, []
    if clear:
        reply = replies.pop(0)
        result = reply.get("result") if isinstance(reply, dict) and reply.get("error") is None else None
        if isinstance(result, list):
            sure = {card_id: None for card_id in clear}
            for entry in result:
                if isinstance(entry, dict) and entry.get("cardId") in sure and isinstance(entry.get("mod"), int):
                    sure[entry["cardId"]] = entry["mod"]
        else:
            unsure = clear                          # no cardsModTime here: those are read the long way
    now = {}
    if rest:
        reply = replies.pop(0)
        if not isinstance(reply, dict) or reply.get("error") is not None:
            raise _core.refusal("cardsInfo", reply.get("error") if isinstance(reply, dict) else reply)
        if not isinstance(reply.get("result"), list):
            raise AnkiError("'cardsInfo' did not return a list.", kind="protocol")
        now = {row.get("cardId"): row for row in reply["result"] if isinstance(row, dict) and row}
    if unsure:
        now.update({row.get("cardId"): row for row in cards_info(url, unsure)})
    return reviewing, sure, now


def mod_times(url, action, ids, chunk=1000):
    """`{id: mod}` from `cardsModTime` or `notesModTime` — the fast re-plan's warm card map asks these
    instead of re-reading every card and note (03 §3.2; `cardsModTime` measured to exist, E0.1). One
    light request per `chunk` ids; an id Anki no longer has is simply absent. Raises `AnkiError`."""
    key, field = ("cards", "cardId") if action == "cardsModTime" else ("notes", "noteId")
    out = {}
    for batch in _chunks([int(value) for value in ids or []], chunk):
        result = invoke(action, url, **{key: batch})
        if not isinstance(result, list):
            raise AnkiError(f"'{action}' did not return a list.", kind="protocol")
        for entry in result:
            if isinstance(entry, dict) and isinstance(entry.get(field), int) and isinstance(entry.get("mod"), int):
                out[entry[field]] = entry["mod"]
    return out


# --------------------------------------------------------------------------- #
# Writing note CONTENT (WP-L) — a different risk class from writing `due`
# --------------------------------------------------------------------------- #
def _note_verdict(reply):
    """Did this sub-action land? Returns "" for success, else why not.

    `updateNoteFields`, `addTags` and `removeTags` all answer with a **null result** on success, so
    the `[True]` rule that `setSpecificValueOfCard` follows does not apply here and checking for it
    would report every successful edit as a failure. The error field is the signal — and a missing
    envelope still counts as one, because a reply we cannot read is not evidence of a write.
    """
    if not isinstance(reply, dict):
        return "Anki sent no reply for this note."
    if reply.get("error") is not None:
        return str(reply["error"])
    return ""


def update_notes(url, edits, chunk=150):
    """Write note fields. `edits` is `{note_id: {field: value}}`; returns `(updated, failures)`.

    One `updateNoteFields` per note, batched through `multi` exactly as the `due` writes are — the
    server is single-threaded on Anki's Qt GUI thread, and one enormous request freezes it with no
    progress and no cancel.

    **Anki creates nothing here:** `updateNoteFields` ignores a field the note type does not have
    and errors on nothing else, and the caller (`touchup.plan`) has already refused to name a field
    the note does not carry. Nothing raises — a run that loses Anki halfway must still be able to
    say which notes it managed, because the snapshot is the only copy of what was there before.
    """
    prepared = []
    for note_id, values in (edits or {}).items():
        if not isinstance(values, dict) or not values:
            continue
        try:
            prepared.append((int(note_id), {str(name): "" if value is None else str(value)
                                            for name, value in values.items()}))
        except (TypeError, ValueError):
            continue

    updated, failures = [], []
    stopped = ""
    for batch in _chunks(prepared, chunk):
        if stopped:
            failures.extend((note_id, stopped) for note_id, _values in batch)
            continue
        try:
            replies = multi([{"action": "updateNoteFields",
                              "params": {"note": {"id": note_id, "fields": values}}}
                             for note_id, values in batch], url)
        except AnkiError as e:
            stopped = str(e)
            failures.extend((note_id, stopped) for note_id, _values in batch)
            continue
        for index, (note_id, _values) in enumerate(batch):
            reason = _note_verdict(replies[index] if index < len(replies) else None)
            if reason:
                failures.append((note_id, reason))
            else:
                updated.append(note_id)
    return updated, failures


def _tag_action(action, url, note_ids, tag, chunk=150):
    """Shared body of `add_tags`/`remove_tags`: one call per chunk of notes, never one per note."""
    tag = str(tag or "").strip()
    clean = []
    for note_id in note_ids or []:
        try:
            clean.append(int(note_id))
        except (TypeError, ValueError):
            continue
    if not tag or not clean:
        return [], []

    touched, failures = [], []
    for batch in _chunks(clean, chunk):
        try:
            invoke(action, url, notes=batch, tags=tag)
        except AnkiError as e:
            failures.extend((note_id, str(e)) for note_id in batch)
            continue
        touched.extend(batch)
    return touched, failures


def add_tags(url, note_ids, tag, chunk=150):
    """Tag the notes junban moved. Idempotent — Anki ignores a tag a note already carries."""
    return _tag_action("addTags", url, note_ids, tag, chunk=chunk)


def remove_tags(url, note_ids, tag, chunk=150):
    """Take junban's own tag back off, on restore. Removing one a note does not have is a no-op."""
    return _tag_action("removeTags", url, note_ids, tag, chunk=chunk)
