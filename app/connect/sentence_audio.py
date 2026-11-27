"""Sentence audio put on cards that have none — ONE field-writing path (Kura-AB3, 2026-11-11; shared on purpose with
Iro-AA's AI sentence audio): `fill`, and its one `undo`. *Add audio to these cards* (a book's text-only cards, once its
audiobook is lined up: spec `tracks/pipeline/work/AB3/add-audio-spec.md`) calls it with Anki Miner's clips; the AI audio
calls it with its own. Neither ever writes the field another way. **Any field, a text** (Piyo-TR, 2026-11-12): `texts`
in place of `clips` writes a text as given — Piyo's translations into the field the card's 翻訳 toggle shows
(`app/card_translations.py`) — by the same contract, and `field` may name each note's own field ({note id: field}: one
batch across note types is still one call and one Undo). One writer for every field Surasura fills on a card.

**The contract** — `fill(anki, ledger, clips, field=FIELD, tag=TAG, by=..., texts=None, verb=VERB)`:
- **In:** `clips` {note id: an audio file on this computer} (who made the clip is the caller's business) — or `texts`
  {note id: the field's new value, as written}, never both; `field`: the note field the card layout plays as its
  sentence's audio (`SentenceAudio`, `Anki_Card_Layout_Spec.md` row 4R — the caller's field mapping may name another),
  or {note id: field}; `tag`: put on every note filled (which path filled it); `by`: who asked, kept in the record.
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

**Its one replace mode** (FS-1, the full Swap: a card's sentence side rewritten in place) — `replace(anki, ledger,
note_id, new, was, media=, keep_dir=, tag=, by=)`: the fields of `new` written over **only while each still holds
exactly its value in `was`** (what the caller read when it decided; anything else, a space too, refuses the whole note:
`CHANGED`), the same lock, review checks and one record before Anki (`mode` `replace`, the old values in `was`). The
media `was` names and `new` doesn't are copied into `keep_dir` and read back by sha1 BEFORE the record, removed from
Anki after the write only when no note names them; `undo` then puts every old value back — only while every field
still holds what was written — stores a kept file again, takes `tag` off unless the note had it, and deletes each new
file no note names; once a kept copy is gone (the caller purges its folder 30 days on, the trash clock's rule) it is
refused, `TOO_OLD`, and nothing is written. A write Anki didn't keep (a note open in its editor) is read back: `NOT_APPLIED`, nothing undone
needed. Fill-only-empty stays every other caller's mode (Piyo's, the AI voice's).

Light: the standard library; Anki through the adapter handed in (`AnkiConnectNotes`; tests hand a fake).
"""
import base64
import hashlib
import json
import os
import re
import time
import uuid

FIELD = "SentenceAudio"
TAG = "surasura::audio-added"
RECORD = "sentence_audio:"            # ledger meta: `sentence_audio:<id>` -> the call's Undo record (JSON)
# AUDIO-FILL (3.0.21): a reader's fold of the records up to an id ({"upto": id, …}: Card sound's `ai_held` snapshot,
# so a look reads only the records after it). A record at or before `upto` written again (an Undo) drops the fold.
FOLD = "sentence_audio_fold"
VERB = "Adding sentence audio"
CHUNK = 50                            # notes written between two looks at whether you're reviewing
WRITING, DONE, UNDONE = "writing", "done", "undone"
GONE, NO_FIELD, HAS_AUDIO, NO_CLIP = ("not in Anki", "its note type has no {field} field",
                                      "it has sentence audio already", "its clip isn't on this computer")
HAS_TEXT, NO_TEXT = "its {field} has something in it already", "nothing to write"     # `texts` (Piyo-TR)
REPLACE = "replace"                   # a record's `mode` for `replace` (FS-1): the old values kept, put back by Undo
CHANGED, NOT_APPLIED = "changed since it was read", "Anki didn't take the change (is the card open in its editor?)"
TOO_OLD = "its kept clip and picture are gone (kept 30 days)"    # a `replace` record past its copies' purge (FS-1)
_MEDIA = (re.compile(r"\[sound:([^\]]+)\]"), re.compile(r"<img[^>]*?\bsrc=[\"']([^\"']+)[\"']", re.I))


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

    def read_media(self, name):
        """A media file's bytes, or None when Anki has no such file (`replace` keeps a copy of what it replaces)."""
        from app import anki_connect
        got = anki_connect.invoke("retrieveMediaFile", self.url, filename=name)
        return base64.b64decode(got) if isinstance(got, str) and got else None


def sound(name):
    return f"[sound:{name}]"


def clip_name(path):
    """The clip's name in Anki's media: by its bytes -> (name, its base64)."""
    with open(path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(path)[1].lower() or ".mp3"
    return f"surasura-sa-{hashlib.sha1(data).hexdigest()[:16]}{ext}", base64.b64encode(data).decode("ascii")


def _why_not(note, field, full=HAS_AUDIO):
    """Why `note` (a notesInfo entry, or None) isn't filled, or None when its `field` is there and empty."""
    if not isinstance(note, dict) or not note.get("noteId"):
        return GONE
    fields = note.get("fields") or {}
    if field not in fields:
        return NO_FIELD.format(field=field)
    value = fields[field].get("value") if isinstance(fields[field], dict) else fields[field]
    return full.format(field=field) if str(value or "") != "" else None


def _field_of(field, n):
    """The field note `n` is written in: `field` itself, or its entry when `field` is {note id: field}."""
    return field.get(n) if isinstance(field, dict) else field


def _by_id(notes):
    return {int(n["noteId"]): n for n in notes or () if isinstance(n, dict) and n.get("noteId")}


def _write_record(ledger, rid, record, new=False):
    """A call's record: its first write a plain INSERT (an id met twice raises, never overwrites an Undo: r2 N2). An
    older record written again (an Undo) inside the fold drops it (FOLD: the next look reads every record again)."""
    ledger.conn.execute(("INSERT" if new else "INSERT OR REPLACE") + " INTO meta (key, value) VALUES (?, ?)",
                        (RECORD + rid, json.dumps(record, ensure_ascii=False)))
    if not new:
        row = ledger.conn.execute("SELECT value FROM meta WHERE key = ?", (FOLD,)).fetchone()
        try:
            upto = str((json.loads(row[0]) or {}).get("upto") or "") if row else ""
        except (TypeError, ValueError, AttributeError):
            upto = "~"                                     # (a fold that can't be read: dropped too)
        if upto and str(rid) <= upto:
            ledger.conn.execute("DELETE FROM meta WHERE key = ?", (FOLD,))


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


def fill(anki, ledger, clips, field=FIELD, tag=TAG, by="connect", texts=None, verb=VERB):
    """The contract above -> {"id" (None when nothing was written), "filled", "skipped"}. Raises Reviewing, the
    writer's Busy, AnkiConnect's errors (a record already written is undone as any). `texts` in place of `clips`: each
    note's field gets its text as given, no media; `verb`: what the write lock says is writing."""
    if clips and texts:
        raise ValueError("fill writes clips or texts, never both in one call")
    if isinstance(field, dict):
        field = {int(n): f for n, f in field.items()}
    if texts:
        texts = {int(n): v for n, v in texts.items()}
        skipped = {n: NO_TEXT for n, v in texts.items() if not (isinstance(v, str) and v.strip())}
        ready, full = {n: v for n, v in texts.items() if n not in skipped}, HAS_TEXT
    else:
        clips = {int(n): p for n, p in (clips or {}).items()}
        skipped = {n: NO_CLIP for n, p in clips.items() if not (isinstance(p, str) and os.path.isfile(p))}
        ready, full = {n: p for n, p in clips.items() if n not in skipped}, HAS_AUDIO
    if not ready:
        return {"id": None, "filled": [], "skipped": skipped}
    if anki.reviewing():
        raise Reviewing()
    with anki.writer(verb):
        if anki.reviewing():
            raise Reviewing()
        info = _by_id(anki.notes(sorted(ready)))              # read again under the lock: only an empty field
        todo = {}
        for n, p in sorted(ready.items()):
            why = _why_not(info.get(n), _field_of(field, n), full)
            if why:
                skipped[n] = why
            else:
                todo[n] = p
        if not todo:
            return {"id": None, "filled": [], "skipped": skipped}
        named = {} if texts else {n: clip_name(p) for n, p in todo.items()}
        rid = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "field": _field_of(field, min(todo)),
               "tag": tag, "by": by, "notes": {str(n): todo[n] if texts else sound(named[n][0]) for n in todo},
               "media": sorted({v[0] for v in named.values()}), "state": WRITING}
        if isinstance(field, dict):                           # each note's own field, for its Undo
            rec["fields"] = {str(n): field[n] for n in todo}
        _write_record(ledger, rid, rec, new=True)             # before Anki: a kill after a write is undone as any
        try:
            stored = {}
            for k, n in enumerate(sorted(todo)):
                if k and k % CHUNK == 0 and anki.reviewing():
                    raise Reviewing()                         # you started reviewing meanwhile: the rest wait
                if texts:
                    anki.update(n, {_field_of(field, n): todo[n]})
                    continue
                name, data = named[n]
                if name not in stored:
                    got = anki.store(name, data)
                    stored[name] = got if isinstance(got, str) and got else name    # Anki's name for it (r2 N1)
                value = sound(stored[name])
                if value != rec["notes"][str(n)]:             # recorded before it is written, as the rest
                    rec = dict(rec, notes=dict(rec["notes"], **{str(n): value}),
                               media=sorted(set(rec["media"]) | {stored[name]}))
                    _write_record(ledger, rid, rec)
                anki.update(n, {_field_of(field, n): value})
            anki.tag(sorted(todo), tag)
        except BaseException as e:
            e.sentence_audio_id = rid                         # the caller's way to its Undo (`pending` too: r2 S4)
            raise
        _write_record(ledger, rid, dict(rec, state=DONE))
    return {"id": rid, "filled": sorted(todo), "skipped": skipped}


def media_in(value):
    """The media file names a field's value plays or shows (`[sound:…]`, `<img src=…>`), in order, each once."""
    out = []
    for pattern in _MEDIA:
        out += [m for m in pattern.findall(str(value or "")) if m not in out]
    return out


def _keep(anki, names, keep_dir):
    """Each media file of `names` Anki has, copied into `keep_dir` and read back -> {name: sha1}; a copy that doesn't
    read back the same raises OSError (nothing is written to Anki then). A name Anki has no file for: not kept."""
    kept = {}
    for name in names:
        data = anki.read_media(name)
        if not data:
            continue
        os.makedirs(keep_dir, exist_ok=True)
        path = os.path.join(keep_dir, os.path.basename(name))
        with open(path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with open(path, "rb") as f:
            if hashlib.sha1(f.read()).hexdigest() != hashlib.sha1(data).hexdigest():
                raise OSError(f"the copy of {name} didn't read back the same")
        kept[name] = hashlib.sha1(data).hexdigest()
    return kept


def replace(anki, ledger, note_id, new, was, media=None, keep_dir=None, tag=None, by="swap", verb=VERB, extra=(),
            on_record=None, loose=()):
    """The replace mode (the docstring above) -> {"id" (None when nothing was written), "filled": [note id] or [],
    "skipped": {note id: why}}. `new` {field: value}; `was` {field: the value it must still hold}, one per field of
    `new`; `media` {name: a file on disk} stored under that name (Anki's own answer is the name written); `keep_dir`:
    where the replaced media are copied first; `extra`: more tags put on with `tag` (FS-1: the first-episode tag),
    each only when the note hasn't it — those, recorded, are the ones its Undo takes off; `on_record(id)`: called with
    the record's id once it is written, before Anki is touched (the caller keeps it: a kill or an error anywhere after
    leaves a record it can settle); `loose`: fields of `new` another fill writes after this one (FS-1: the sentence
    furigana it empties, Backfill's ふりがな refills) — Undo puts them back too, but never reads them as changed since.
    Raises Reviewing, the
    writer's Busy, AnkiConnect's errors, OSError (a copy that didn't read back), ValueError (a field of `new` with no
    `was`)."""
    n = int(note_id)
    if set(new) - set(was):
        raise ValueError("replace needs each field's old value")
    if anki.reviewing():
        raise Reviewing()
    with anki.writer(verb):
        if anki.reviewing():
            raise Reviewing()
        note = _by_id(anki.notes([n])).get(n)                 # read again under the lock: only what was read
        if note is None:
            return {"id": None, "filled": [], "skipped": {n: GONE}}
        fields = note.get("fields") or {}
        for field in new:
            if field not in fields:
                return {"id": None, "filled": [], "skipped": {n: NO_FIELD.format(field=field)}}
            if str((fields[field] or {}).get("value") or "") != str(was[field] or ""):
                return {"id": None, "filled": [], "skipped": {n: CHANGED}}
        stored_new = {name: path for name, path in (media or {}).items() if os.path.isfile(path)}
        gone = [m for f in new for m in media_in(was[f]) if m not in {x for v in new.values() for x in media_in(v)}]
        rid = f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
        kept = _keep(anki, gone, os.path.join(keep_dir, rid)) if keep_dir and gone else {}
        had = any(str(t).lower() == str(tag or "").lower() for t in note.get("tags") or ())
        on = {str(t).lower() for t in note.get("tags") or ()}
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "mode": REPLACE, "field": None,
               "tag": tag, "had_tag": had, "extra": [t for t in extra or () if t and t.lower() not in on],
               "loose": sorted(f for f in loose or () if f in new),
               "by": by, "notes": {str(n): dict(new)},
               "was": {str(n): {f: str(was[f] or "") for f in new}}, "media": sorted(stored_new), "kept": kept,
               "keep_dir": os.path.join(keep_dir, rid) if kept else None, "state": WRITING}
        _write_record(ledger, rid, rec, new=True)             # before Anki: a kill after a write is undone as any
        if on_record is not None:
            on_record(rid)
        try:
            value = dict(new)
            for name, path in sorted(stored_new.items()):
                with open(path, "rb") as f:
                    got = anki.store(name, base64.b64encode(f.read()).decode("ascii"))
                if isinstance(got, str) and got and got != name:     # Anki's name for it is the one written
                    value = {f: v.replace(name, got) for f, v in value.items()}
                    rec = dict(rec, notes={str(n): value}, media=sorted(set(rec["media"]) - {name} | {got}))
                    _write_record(ledger, rid, rec)
            if anki.reviewing():
                raise Reviewing()                             # you started reviewing meanwhile: asked again
            anki.update(n, value)
            now = (_by_id(anki.notes([n])).get(n) or {}).get("fields") or {}
            if any(str((now.get(f) or {}).get("value") or "") != v for f, v in value.items()):
                for name in rec["media"]:                     # stored for a write Anki didn't keep: none left behind
                    if not anki.users(name):
                        anki.delete_media(name)
                _write_record(ledger, rid, dict(rec, state=UNDONE, not_applied=True))
                return {"id": None, "filled": [], "skipped": {n: NOT_APPLIED}}
            if tag and not had:
                anki.tag([n], tag)
            for t in rec["extra"]:
                anki.tag([n], t)
            for name in kept:
                if not anki.users(name):                      # an old file no other note names goes (a copy kept)
                    anki.delete_media(name)
        except BaseException as e:
            e.sentence_audio_id = rid
            raise
        _write_record(ledger, rid, dict(rec, state=DONE))
    return {"id": rid, "filled": [n], "skipped": {}}


def settle(anki, ledger, rid, verb=VERB):
    """A `replace` record a kill or an error left `writing` (its note maybe written, maybe not) put right before the
    same write is tried again: undone as any (`undo`: every old value back where the note holds the write), then
    closed `undone`, each new file no note names deleted -> True when it was one to settle."""
    rec = record(ledger, rid)
    if rec is None or rec.get("mode") != REPLACE or rec.get("state") != WRITING:
        return False
    undo(anki, ledger, rid, verb=verb)
    rec = record(ledger, rid)
    if rec is not None and rec.get("state") != UNDONE:
        with anki.writer(verb):
            for name in rec.get("media") or ():
                if not anki.users(name):
                    anki.delete_media(name)
            _write_record(ledger, rid, dict(rec, state=UNDONE, settled=True))
    return True


def _undo_replace(anki, rec):
    """`undo` of a `replace` record, under the caller's lock -> (emptied, kept, deleted): every old value back only
    while every field still holds what was written; a kept file stored again (Anki's name for it put in the values)."""
    emptied, kept, deleted = [], {}, []
    wrote = {int(n): v for n, v in (rec.get("notes") or {}).items()}
    info = _by_id(anki.notes(sorted(wrote)))
    for n, value in sorted(wrote.items()):
        note = info.get(n)
        if note is None:
            kept[n] = GONE
            continue
        fields = note.get("fields") or {}
        old = dict((rec.get("was") or {}).get(str(n)) or {})
        if old and all(str((fields.get(f) or {}).get("value") or "") == v for f, v in old.items()):
            emptied.append(n)                                 # put back already (an Undo stopped after its write)
            _tags_off(anki, n, rec)
            continue
        loose = set(rec.get("loose") or ())
        if any(str((fields.get(f) or {}).get("value") or "") != v for f, v in value.items() if f not in loose):
            kept[n] = "changed since"
            continue
        for name in rec.get("kept") or {}:
            path = os.path.join(rec.get("keep_dir") or "", os.path.basename(name))
            with open(path, "rb") as f:
                got = anki.store(name, base64.b64encode(f.read()).decode("ascii"))
            if isinstance(got, str) and got and got != name:
                old = {f: v.replace(name, got) for f, v in old.items()}
        anki.update(n, old)
        emptied.append(n)
        _tags_off(anki, n, rec)
    if emptied:
        for name in rec.get("media") or ():
            if not anki.users(name):
                anki.delete_media(name)
                deleted.append(name)
    return emptied, kept, deleted


def _tags_off(anki, n, rec):
    """A `replace` record's tags off its note on Undo: `tag` unless the note had it, and each `extra` it put on."""
    if rec.get("tag") and not rec.get("had_tag"):
        anki.tag([n], rec["tag"], on=False)
    for t in rec.get("extra") or ():
        anki.tag([n], t, on=False)


def undo(anki, ledger, rid, verb=VERB):
    """A `fill`'s one Undo -> {"emptied": [note ids], "kept": {note id: why}, "deleted": [clip names]}: the field
    emptied only where it still holds what was written, the tag off those notes, then each clip no note names any
    more. A `replace` record: the old values put back instead (`_undo_replace`); one whose note changed since is
    kept, its record left as it was (an Undo after you put the swap's text back works). A record already undone, or
    none: nothing written ({"emptied": [], …, "refused": why})."""
    rec = record(ledger, rid)
    if rec is None or rec.get("state") == UNDONE:
        return {"emptied": [], "kept": {}, "deleted": [], "refused": "nothing to undo"}
    if anki.reviewing():
        raise Reviewing()
    emptied, kept, deleted = [], {}, []
    with anki.writer(verb + " (undo)"):
        if anki.reviewing():
            raise Reviewing()
        rec = record(ledger, rid)                             # read again under the lock: two Undos, one runs (r2 N4)
        if rec is None or rec.get("state") == UNDONE:
            return {"emptied": [], "kept": {}, "deleted": [], "refused": "nothing to undo"}
        if rec.get("mode") == REPLACE:
            if any(not os.path.isfile(os.path.join(rec.get("keep_dir") or "", os.path.basename(name)))
                   for name in rec.get("kept") or {}):
                return {"emptied": [], "kept": {}, "deleted": [], "refused": TOO_OLD}  # nothing put back by halves
            emptied, kept, deleted = _undo_replace(anki, rec)
            if emptied:
                _write_record(ledger, rid, dict(rec, state=UNDONE, undone_at=time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
            return {"emptied": emptied, "kept": kept, "deleted": deleted}
        wrote = {int(n): v for n, v in (rec.get("notes") or {}).items()}
        fields = {int(n): f for n, f in (rec.get("fields") or {}).items()}      # a batch across note types
        info = _by_id(anki.notes(sorted(wrote)))
        for n, value in sorted(wrote.items()):
            note, field = info.get(n), fields.get(n) or rec["field"]
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
