# SPDX-License-Identifier: GPL-3.0-or-later
"""The one seam to the shared SentenceAudio writer (one writer, never two).

Every write of the AI voice goes through here, and from here through **Connect's sentence-audio writer**,
`app/connect/sentence_audio.py`: `fill(anki, ledger, clips, field, tag, by, texts, verb)` (this seam gives
clips, never `texts`) fills only an exactly empty field,
read again under the Anki-write lock, never while you review, the clip stored once by its bytes, one Undo record a
call in Connect's ledger before Anki is written; `undo(anki, ledger, id)` empties only a field still holding what was
written, takes the tag off, deletes each clip no note names any more. This module writes nothing itself.

The beta turns on only where that writer is in the tree with exactly that contract (`CONTRACT`, its signature): a
writer that changed shape turns AI audio off, never on. `look` is the read-only count before a press.
"""
import inspect

from app import anki_connect
from app.anki_connect import AnkiError

FIELD = "SentenceAudio"
AI_TAG = "surasura::ai-audio"           # PROVISIONAL: the AI voice's cards (the narrator's clips: surasura::audio-added)
BY = "ai-audio"
WAITS = "AI audio waits for Surasura's sentence-audio writer, which isn't in this build."
# The writer's `texts` / `verb` (their defaults keep the clips path as it was): the seam never passes them
CONTRACT = {"fill": ("anki", "ledger", "clips", "field", "tag", "by", "texts", "verb"),
            "undo": ("anki", "ledger", "rid", "verb"), "record": ("ledger", "rid")}
NAMES = ("Reviewing", "AnkiConnectNotes")       # what else the seam uses of it


def _shared():
    """The shared writer when it honours this seam's contract (its two calls' parameters, in order), else None."""
    try:
        from app.connect import sentence_audio
    except ImportError:
        return None
    try:
        for name, params in CONTRACT.items():
            if tuple(inspect.signature(getattr(sentence_audio, name)).parameters) != params:
                return None
        if not all(isinstance(getattr(sentence_audio, n), type) for n in NAMES):
            return None
    except (AttributeError, TypeError, ValueError):
        return None
    return sentence_audio


def available():
    return _shared() is not None


def is_empty(value):
    """Empty = exactly nothing (the shared writer's own rule: a space, `<br>`, a `[sound:…]` all hold something)."""
    return value is None or value == ""


def _field_value(note, field):
    entry = (note.get("fields") or {}).get(field)
    if entry is None:
        return None
    return entry.get("value", "") if isinstance(entry, dict) else str(entry)


def look(url, note_ids, field=FIELD):
    """(Read-only, no lock.) -> {"ok", "empty": [ids], "kept", "no_field", "gone", "problems"}."""
    ids = []
    for n in note_ids or ():
        try:
            ids.append(int(n))
        except (TypeError, ValueError):
            pass
    ids = list(dict.fromkeys(ids))
    try:
        notes = anki_connect.notes_info(url, ids) if ids else []
    except AnkiError as e:
        return {"ok": False, "empty": [], "kept": 0, "no_field": 0, "gone": 0, "problems": [str(e)]}
    empty, kept, no_field, found = [], 0, 0, 0
    for note in notes or ():
        if not isinstance(note, dict) or not isinstance(note.get("noteId"), int):
            continue
        found += 1
        value = _field_value(note, field)
        if value is None:
            no_field += 1
        elif is_empty(value):
            empty.append(note["noteId"])
        else:
            kept += 1
    return {"ok": True, "empty": sorted(empty), "kept": kept, "no_field": no_field, "gone": len(ids) - found,
            "problems": []}


def _report(ok, message, **extra):
    report = {"ok": ok, "message": message, "problems": [], "written": [], "run": None, "busy": False}
    report.update(extra)
    return report


def _ledger():
    from app.connect import ledger
    return ledger.Ledger(ledger.path())


def fill(url, language, files, *, tag=AI_TAG, field=FIELD):
    """`files` ({note id: an audio file}) into the notes' empty `field`, through the shared writer -> {"ok", "message",
    "problems", "written" (note ids), "run" (its Undo's id), "busy", "reviewing", "skipped"}. Never raises."""
    shared = _shared()
    if shared is None:
        return _report(False, "Nothing was added.", problems=[WAITS], waits=True)
    from app import locks
    try:
        with _ledger() as ledger:
            got = shared.fill(shared.AnkiConnectNotes(url), ledger, files, field=field, tag=tag, by=BY)
    except Exception as e:                  # never raised; a write cut part-way keeps its Undo
        rid = getattr(e, "sentence_audio_id", None)
        written = _recorded(shared, rid)
        if isinstance(e, shared.Reviewing):
            why, extra = anki_connect.REVIEWING, {"reviewing": True}
        elif isinstance(e, locks.Busy):
            why, extra = anki_connect.busy_message(e), {"busy": True}
        else:
            why, extra = str(e) or type(e).__name__, {}
        return _report(False, "Not all of it was added: Undo takes off what was." if rid else "Nothing was added.",
                       problems=[why], run=rid, written=written, **extra)
    filled, skipped = list(got.get("filled") or ()), dict(got.get("skipped") or {})
    n = len(filled)
    message = f"Added AI sentence audio to {n} card{'' if n == 1 else 's'}." if n else "Nothing to add."
    return _report(True, message, written=filled, run=got.get("id"), skipped=skipped)


def _recorded(shared, rid):
    """The notes a call's record says were (or were being) written — a write cut part-way's, for its Undo."""
    if not rid:
        return []
    try:
        with _ledger() as ledger:
            rec = shared.record(ledger, rid) or {}
        return sorted(int(n) for n in rec.get("notes") or ())
    except Exception:
        return []


def undo(url, language, run_id):
    """That run put back through the shared writer -> {"ok", "message", "problems", "written" (the notes emptied),
    "kept" (changed since: as you left them)}. Never raises."""
    shared = _shared()
    if shared is None:
        return _report(False, "Nothing was undone.", problems=[WAITS], waits=True)
    from app import locks
    try:
        with _ledger() as ledger:
            got = shared.undo(shared.AnkiConnectNotes(url), ledger, run_id)
    except Exception as e:                  # never raised
        if isinstance(e, shared.Reviewing):
            return _report(False, "Nothing was undone.", problems=[anki_connect.REVIEWING], reviewing=True)
        if isinstance(e, locks.Busy):
            return _report(False, "Nothing was undone.", problems=[anki_connect.busy_message(e)], busy=True)
        return _report(False, "Nothing was undone.", problems=[str(e) or type(e).__name__])
    if got.get("refused"):
        return _report(False, "Nothing was undone.", problems=[f"That AI audio was already taken off ({got['refused']})."])
    n, kept = len(got.get("emptied") or ()), len(got.get("kept") or {})
    message = f"Took the AI sentence audio off {n} card{'' if n == 1 else 's'}."
    if kept:
        message += f" {kept} you changed since were left as they are."
    return _report(True, message, written=list(got.get("emptied") or ()), kept=kept)
