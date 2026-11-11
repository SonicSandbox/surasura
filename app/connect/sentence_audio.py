"""Sentence audio put on cards that have none — ONE field-writing path (Kura-AB3, 2026-11-12; shared on purpose with
Iro-AA's AI sentence audio): `fill`, and its one `undo`. *Add audio to these cards* (a book's text-only cards, once its
audiobook is lined up: spec `tracks/pipeline/work/AB3/add-audio-spec.md`) calls it with Anki Miner's clips; the AI audio
calls it with its own. Neither ever writes the field another way.

**The contract** — `fill(anki, ledger, clips, field=FIELD, tag=TAG, by=...)`:
- **In:** `clips` {note id: an audio file on this computer} (who made the clip is the caller's business); `field`: the
  note field the card layout plays as its sentence's audio (`SentenceAudio`, `Anki_Card_Layout_Spec.md` row 4R — the
  caller's field mapping may name another); `tag`: put on every note filled (which path filled it); `by`: who asked,
  kept in the record.
- **Only an empty field is filled:** each note read again under Anki's write lock just before it is written; a note
  gone, one whose type has no such field, or one whose field holds anything (sound, text, a space) is skipped with its
  why — never overwritten. Nothing else of a note is written: one `updateNoteFields` naming that field alone, then
  `addTags` with `tag`.
- **The clip** is stored once by its bytes (`surasura-sa-<sha1>.<ext>`; `deleteExisting` false: a file of the
  learner's is never replaced; the same clip for two notes is one file).
- **One Undo record a call**, written to the ledger's meta BEFORE Anki is (`RECORD` + its id → {at, field, tag, by,
  notes {id: what was written}, media [names], state}); `undo(anki, ledger, id)` empties the field only where it still
  holds exactly what was written (an edit of yours since keeps it), takes the tag off those notes, then deletes each
  clip no note names any more. A call killed mid-way leaves its record `writing`: its Undo works the same.
- **Never while you review** in Anki (`Reviewing`); every write holds `anki_connect.writer` (the one writer).
- **Out:** {"id", "filled": [note ids], "skipped": {note id: why}}. Anki's sync is owed by the caller (its session's
  rule, `anki_sync_rule`).

Light: the standard library; Anki through the adapter handed in (`AnkiConnectNotes`; tests hand a fake).
"""
import base64
import hashlib
import json
import os
import time
import uuid

FIELD = "SentenceAudio"
TAG = "surasura::audio-added"
RECORD = "sentence_audio:"            # ledger meta: `sentence_audio:<id>` -> the call's Undo record (JSON)
VERB = "Adding sentence audio"
CHUNK = 50                            # notes written between two looks at whether you're reviewing
WRITING, DONE, UNDONE = "writing", "done", "undone"
GONE, NO_FIELD, HAS_AUDIO, NO_CLIP = ("not in Anki", "its note type has no {field} field",
                                      "it has sentence audio already", "its clip isn't on this computer")


class Reviewing(Exception):
    """You're reviewing in Anki: nothing written (press again when you're done)."""


class AnkiConnectNotes:
    """`fill`'s and `undo`'s Anki: AnkiConnect, loopback."""

    def __init__(self, url):
        self.url = url

    def reviewing(self):
        from app import anki_connect
        return anki_connect.reviewing(self.url)

    def writer(self, verb):
        from app import anki_connect
        return anki_connect.writer(verb, wait=10.0)

    def notes(self, ids):
        from app import anki_connect
        return anki_connect.notes_info(self.url, ids)

    def store(self, name, data):
        """-> the name Anki stored it under (its own, when a file of that name was there already)."""
        from app import anki_connect
        return anki_connect.invoke("storeMediaFile", self.url, filename=name, data=data, deleteExisting=False)

    def update(self, note_id, fields):
        from app import anki_connect
        anki_connect.invoke("updateNoteFields", self.url, note={"id": int(note_id), "fields": fields})

    def tag(self, ids, tag, on=True):
        from app import anki_connect
        anki_connect.invoke("addTags" if on else "removeTags", self.url, notes=[int(n) for n in ids], tags=tag)

    def users(self, name):
        from app.connect import media_names
        return media_names.AnkiConnectMedia(self.url).users(name)

    def delete_media(self, name):
        from app import anki_connect
        anki_connect.invoke("deleteMediaFile", self.url, filename=name)


def sound(name):
    return f"[sound:{name}]"


def clip_name(path):
    """The clip's name in Anki's media: by its bytes -> (name, its base64)."""
    with open(path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(path)[1].lower() or ".mp3"
    return f"surasura-sa-{hashlib.sha1(data).hexdigest()[:16]}{ext}", base64.b64encode(data).decode("ascii")


def _why_not(note, field):
    """Why `note` (a notesInfo entry, or None) isn't filled, or None when its `field` is there and empty."""
    if not isinstance(note, dict) or not note.get("noteId"):
        return GONE
    fields = note.get("fields") or {}
    if field not in fields:
        return NO_FIELD.format(field=field)
    value = fields[field].get("value") if isinstance(fields[field], dict) else fields[field]
    return HAS_AUDIO if str(value or "") != "" else None


def _by_id(notes):
    return {int(n["noteId"]): n for n in notes or () if isinstance(n, dict) and n.get("noteId")}


def _write_record(ledger, rid, record, new=False):
    """A call's record: its first write a plain INSERT (an id met twice raises, never overwrites an Undo: r2 N2)."""
    ledger.conn.execute(("INSERT" if new else "INSERT OR REPLACE") + " INTO meta (key, value) VALUES (?, ?)",
                        (RECORD + rid, json.dumps(record, ensure_ascii=False)))


def pending(ledger):
    """The ids of the calls a failure or a kill left `writing` (their Undo works as any: r2 S4), oldest first."""
    out = []
    for key, value in ledger.conn.execute("SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key",
                                          (RECORD + "%",)):
        try:
            if json.loads(value).get("state") == WRITING:
                out.append(key[len(RECORD):])
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def record(ledger, rid):
    """A call's Undo record, or None."""
    row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (RECORD + str(rid),)).fetchone()
    try:
        got = json.loads(row[0]) if row else None
    except (TypeError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def fill(anki, ledger, clips, field=FIELD, tag=TAG, by="connect"):
    """The contract above -> {"id" (None when nothing was written), "filled", "skipped"}. Raises Reviewing, the
    writer's Busy, AnkiConnect's errors (a record already written is undone as any)."""
    clips = {int(n): p for n, p in (clips or {}).items()}
    skipped = {n: NO_CLIP for n, p in clips.items() if not (isinstance(p, str) and os.path.isfile(p))}
    ready = {n: p for n, p in clips.items() if n not in skipped}
    if not ready:
        return {"id": None, "filled": [], "skipped": skipped}
    if anki.reviewing():
        raise Reviewing()
    with anki.writer(VERB):
        if anki.reviewing():
            raise Reviewing()
        info = _by_id(anki.notes(sorted(ready)))              # read again under the lock: only an empty field
        todo = {}
        for n, p in sorted(ready.items()):
            why = _why_not(info.get(n), field)
            if why:
                skipped[n] = why
            else:
                todo[n] = p
        if not todo:
            return {"id": None, "filled": [], "skipped": skipped}
        named = {n: clip_name(p) for n, p in todo.items()}
        rid = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "field": field, "tag": tag, "by": by,
               "notes": {str(n): sound(named[n][0]) for n in todo}, "media": sorted({v[0] for v in named.values()}),
               "state": WRITING}
        _write_record(ledger, rid, rec, new=True)             # before Anki: a kill after a write is undone as any
        try:
            stored = {}
            for k, n in enumerate(sorted(todo)):
                if k and k % CHUNK == 0 and anki.reviewing():
                    raise Reviewing()                         # you started reviewing meanwhile: the rest wait
                name, data = named[n]
                if name not in stored:
                    got = anki.store(name, data)
                    stored[name] = got if isinstance(got, str) and got else name    # Anki's name for it (r2 N1)
                value = sound(stored[name])
                if value != rec["notes"][str(n)]:             # recorded before it is written, as the rest
                    rec = dict(rec, notes=dict(rec["notes"], **{str(n): value}),
                               media=sorted(set(rec["media"]) | {stored[name]}))
                    _write_record(ledger, rid, rec)
                anki.update(n, {field: value})
            anki.tag(sorted(todo), tag)
        except BaseException as e:
            e.sentence_audio_id = rid                         # the caller's way to its Undo (`pending` too: r2 S4)
            raise
        _write_record(ledger, rid, dict(rec, state=DONE))
    return {"id": rid, "filled": sorted(todo), "skipped": skipped}


def undo(anki, ledger, rid):
    """A `fill`'s one Undo -> {"emptied": [note ids], "kept": {note id: why}, "deleted": [clip names]}: the field
    emptied only where it still holds what was written, the tag off those notes, then each clip no note names any
    more. A record already undone, or none: nothing written ({"emptied": [], …, "refused": why})."""
    rec = record(ledger, rid)
    if rec is None or rec.get("state") == UNDONE:
        return {"emptied": [], "kept": {}, "deleted": [], "refused": "nothing to undo"}
    if anki.reviewing():
        raise Reviewing()
    emptied, kept, deleted = [], {}, []
    with anki.writer(VERB + " (undo)"):
        if anki.reviewing():
            raise Reviewing()
        rec = record(ledger, rid)                             # read again under the lock: two Undos, one runs (r2 N4)
        if rec is None or rec.get("state") == UNDONE:
            return {"emptied": [], "kept": {}, "deleted": [], "refused": "nothing to undo"}
        field, wrote = rec["field"], {int(n): v for n, v in (rec.get("notes") or {}).items()}
        info = _by_id(anki.notes(sorted(wrote)))
        for n, value in sorted(wrote.items()):
            note = info.get(n)
            if note is None:
                kept[n] = GONE
                continue
            now = ((note.get("fields") or {}).get(field) or {}).get("value")
            if now != value:
                kept[n] = "never written" if not now else "changed since"
                continue
            anki.update(n, {field: ""})
            emptied.append(n)
        if emptied:
            anki.tag(emptied, rec.get("tag") or TAG, on=False)
        for name in rec.get("media") or ():
            if not anki.users(name):                          # a clip still named by a note stays
                anki.delete_media(name)
                deleted.append(name)
        _write_record(ledger, rid, dict(rec, state=UNDONE, undone_at=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                                    time.gmtime())))
    return {"emptied": emptied, "kept": kept, "deleted": deleted}
