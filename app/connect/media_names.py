"""Media named by the line (P2.4 Part B row 2.4.13; Sonic, 2026-10-07 *Windows' change reports; Connect's card rules*:
"May be worth hashing it for speed / length?", *the shelf*: by the line; ✅ P2.4-4 ⭐ 2026-10-08).

Anki Miner 3.7.0 names each card's clip and picture by its word (`<word>_<ms>_<seq>_<sha1[:12]>.mp3`, its
`services/media_extractor.py` and `anki_media_store.py`): three words cut from one line make three audio files and
three pictures, and a card made again for the same line uploads its files again. Surasura renames them **at the end of
the mining step** (every batch's notes; a job that ends skipped or failed too), to one short fixed-length name per line:

    sl-<16 hex>.<ext>   the sha256 of (the episode's key, the line's start and end in ms, the line's fingerprint)

- **The episode's key**: hato's `content_key` when it paired the episode, else the library item's own key; two
  episodes with the same sentence text get two names. **The fingerprint**: the store's `line_fingerprint` where it has
  one (3.0), else a hash of the line's text.
- **One file per line**: the first note of a line gives its file under the new name (`retrieveMediaFile` →
  `storeMediaFile`); every note of the line is pointed at it (`updateNoteFields`), and the old names of the notes it
  pointed are deleted in the same rename, once no note uses them (adversary B #15; only a kill, or Anki gone, between
  the points and the deletes leaves one). **A name already in Anki is reused**, never uploaded again — a card made
  again for the same line (the shelf's swap back, a deleted card made again on request) costs no upload.
- **One `multi` a kind** (LF-mining row 25): the batch's name checks, reads, stores, points, searches and deletes go as
  one AnkiConnect request each (the adapter's `many`): ~8 requests for an episode's 24 notes, not ~270. One action
  failing in its slot leaves only its notes as they are — never pointed at a file that wasn't stored, an old file whose
  search failed never deleted — the rest is done, and the rename raises AnkiError as a failed request always did: the
  job waits, and the next look finishes what was left.
- **Killed half-way**: run again, it finishes (the field mapping read back from the job's settings export) — a note
  already pointing at the new name is left; one still on its old name whose new file exists is pointed at it; no note
  ever points at a file that isn't there.
- Holds Anki's write lock from its first read; never while you review (K88: asked once, after the reads and before the
  batch's first write — its writes are three requests under the lock; before row 25 it was asked before each note's
  writes: PROVISIONAL, Michi's technical rule). The next request to Zero asks for a run-file key that names each line's
  media, and then this step goes (P2.4-4).

Standard library only; Anki through the adapter it is handed (`AnkiConnectMedia`; tests hand a fake).
"""
import hashlib
import os
import re

PREFIX = "sl-"
_SOUND = re.compile(r"\[sound:([^\]]+)\]")
_IMG = re.compile(r"""<img[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)
MANY_CHUNK = 100        # actions in one `multi` at most: an episode's batch is one request a kind


class Reviewing(Exception):
    """You started reviewing: nothing (more) was written."""


def fingerprint(text):
    """A line's fingerprint where the store has none: a short hash of its text, spaces folded."""
    folded = " ".join(str(text or "").split())
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()[:16]


def line_name(key, start, end, print_, ext):
    """The line's fixed name: `sl-` + 16 hex of sha256(key | start ms | end ms | fingerprint) + the extension."""
    start_ms = int(round(float(start) * 1000))
    end_ms = int(round(float(end) * 1000)) if end is not None else -1
    digest = hashlib.sha256(f"{key}|{start_ms}|{end_ms}|{print_}".encode("utf-8")).hexdigest()[:16]
    return f"{PREFIX}{digest}{ext.lower()}"


def _named(value, pattern):
    found = pattern.search(value or "")
    return found.group(1) if found else None


def _query(name):
    """A search for the file's name, as written."""
    from app import anki_connect
    return f'"{anki_connect.escape_query(name)}"'


# the adapter's kinds of call -> (AnkiConnect's action, its params from the call's arguments)
_ACTIONS = {
    "exists": ("getMediaFilesNames", lambda name: {"pattern": name}),
    "read": ("retrieveMediaFile", lambda name: {"filename": name}),
    "store": ("storeMediaFile", lambda name, data: {"filename": name, "data": data, "deleteExisting": False}),
    "point": ("updateNoteFields", lambda note_id, fields: {"note": {"id": note_id, "fields": fields}}),
    "users": ("findNotes", lambda name: {"query": _query(name)}),
    "delete": ("deleteMediaFile", lambda name: {"filename": name}),
}


class AnkiConnectMedia:
    """The media step's Anki: AnkiConnect, loopback."""

    def __init__(self, url):
        self.url = url

    def notes(self, ids):
        from app import anki_connect
        return anki_connect.notes_info(self.url, ids)

    def users(self, name):
        """The notes whose fields name the file (a search for the name, as written). An answer that isn't a list
        raises: never read as "no one", which would delete a file in use (review B #11)."""
        from app import anki_connect
        found = anki_connect.invoke("findNotes", self.url, timeout=60, query=_query(name))
        if not isinstance(found, list):
            raise anki_connect.AnkiError(f"findNotes answered {type(found).__name__}, not a list", kind="protocol")
        return found

    def many(self, kind, items):
        """One call of `kind` (exists, read, store, point, users, delete) for each of `items` (its arguments), sent as
        one AnkiConnect `multi` (MANY_CHUNK at most a request) -> [(ok, the call's answer)] in order: exists → bool,
        read → the data, users → the note ids. A slot Anki refused, or a search that isn't a list (review B #11), is
        (False, None); a request that fails as a whole raises AnkiError."""
        from app import anki_connect
        action, params = _ACTIONS[kind]
        out = []
        for start in range(0, len(items), MANY_CHUNK):
            chunk = items[start:start + MANY_CHUNK]
            replies = anki_connect.multi([{"action": action, "params": params(*item)} for item in chunk], self.url,
                                         timeout=60 + len(chunk))
            out += self._read(kind, chunk, replies)
        return out

    @staticmethod
    def _read(kind, items, replies):
        """A `multi`'s raw replies as `many`'s (ok, answer) pairs, one per item (a reply missing: failed)."""
        out = []
        for n, item in enumerate(items):
            reply = replies[n] if n < len(replies) else None
            if not isinstance(reply, dict) or reply.get("error") is not None:
                out.append((False, None))
            elif kind == "exists":
                out.append((True, item[0] in (reply.get("result") or [])))
            elif kind == "users" and not isinstance(reply.get("result"), list):
                out.append((False, None))
            else:
                out.append((True, reply.get("result")))
        return out

    def reviewing(self):
        from app import anki_connect
        return anki_connect.reviewing(self.url)

    def writer(self, verb):
        from app import anki_connect
        return anki_connect.writer(verb, wait=10.0)


def rename(media, made, key, audio_field, picture_field, fingerprints=None):
    """Rename one batch's media by the line. `made`: [(note id, line start, line end, line text)] — the notes the
    batch made; `key`: the episode's key; `fingerprints`: {(start, end): the store's fingerprint} where it has one ->
    {"renamed": n notes pointed, "stored": n files stored, "reused": n names already in Anki, "deleted": n old}.
    Raises Reviewing (nothing written), or AnkiError once the rest is done when an action failed (§ One `multi`)."""
    out = {"renamed": 0, "stored": 0, "reused": 0, "deleted": 0}
    if not made:
        return out
    failed = 0
    with media.writer("Connect's media names"):     # held from the first read (review B #25)
        by_id = {n.get("noteId"): n for n in media.notes([m[0] for m in made])}
        plan, source = [], {}           # [(note id, [(field, value, old, new)])], {new name: the old file it is from}
        for note_id, start, end, text in made:
            note = by_id.get(note_id)
            if note is None:
                continue                # deleted meanwhile: nothing to point
            print_ = (fingerprints or {}).get((start, end)) or fingerprint(text)
            changes = []
            for field, pattern in ((audio_field, _SOUND), (picture_field, _IMG)):
                if not field:
                    continue
                value = ((note.get("fields") or {}).get(field) or {}).get("value") or ""
                old = _named(value, pattern)
                if not old or old.startswith(PREFIX):
                    continue            # nothing there, or named by the line already (a resumed rename)
                new = line_name(key, start, end, print_, os.path.splitext(old)[1] or ".bin")
                source.setdefault(new, old)         # the line's first note gives its file
                changes.append((field, value, old, new))
            if changes:
                plan.append((note_id, changes))
        if not plan:
            return out
        news = list(source)
        ready, missing = set(), []      # names in Anki now; names to store
        for new, (ok, there) in zip(news, media.many("exists", [(n,) for n in news])):
            if not ok:
                failed += 1
            elif there:
                ready.add(new)
                out["reused"] += 1
            else:
                missing.append(new)
        stores = []
        for new, (ok, data) in zip(missing, media.many("read", [(source[n],) for n in missing])):
            if not ok:
                failed += 1
            elif data:
                stores.append((new, data))  # an old file that isn't there (empty, False): its notes are left as is
        if media.reviewing():           # asked once, before the batch's first write (K88): resumed next look
            raise Reviewing()
        for (new, _data), (ok, _answer) in zip(stores, media.many("store", stores)):
            if ok:
                ready.add(new)
                out["stored"] += 1
            else:
                failed += 1
        points = []                     # (note id, its fields, its old names): pointed only at names in Anki
        for note_id, changes in plan:
            moved = [(field, value, old, new) for field, value, old, new in changes if new in ready]
            if moved:
                points.append((note_id, {f: v.replace(o, n) for f, v, o, n in moved}, {o for _f, _v, o, _n in moved}))
        olds = set()
        for (_id, _fields, old_names), (ok, _answer) in zip(points, media.many("point", [p[:2] for p in points])):
            if ok:
                out["renamed"] += 1
                olds |= old_names
            else:
                failed += 1             # its old names stay: the note still plays them
        olds = sorted(olds)             # the pointed notes' old names, now no note's (another may share one)
        gone = []
        for old, (ok, users) in zip(olds, media.many("users", [(o,) for o in olds])):
            if not ok:
                failed += 1             # no answer is never "no one" (review B #11)
            elif not users:
                gone.append(old)
        for _old, (ok, _answer) in zip(gone, media.many("delete", [(o,) for o in gone])):
            if ok:
                out["deleted"] += 1
            else:
                failed += 1
    if failed:
        from app import anki_connect
        raise anki_connect.AnkiError(f"Anki refused {failed} of the media rename's actions; the rest was done.")
    return out
