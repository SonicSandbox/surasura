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
  `storeMediaFile`); every note of the line is pointed at it (`updateNoteFields`), and its old names are deleted right
  after, once no note uses them — so a rename stopped half-way leaves no old file behind for the notes it pointed
  (adversary B #15; only a kill between a note's pointing and its deletes can). **A name already in Anki is reused**, never uploaded again — a card made again for the same line (the
  shelf's swap back, a deleted card made again on request) costs no upload.
- **Killed half-way**: run again, it finishes (the field mapping read back from the job's settings export) — a note already pointing at the new name is left; one still on its old
  name whose new file exists is pointed at it; no note ever points at a file that isn't there.
- Holds Anki's write lock from its first read; never while you review (K88, asked before each note's writes). The next request to Zero asks for a run-file key
  that names each line's media, and then this step goes (P2.4-4).

Standard library only; Anki through the adapter it is handed (`AnkiConnectMedia`; tests hand a fake).
"""
import hashlib
import os
import re

PREFIX = "sl-"
_SOUND = re.compile(r"\[sound:([^\]]+)\]")
_IMG = re.compile(r"""<img[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)


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


class AnkiConnectMedia:
    """The media step's Anki: AnkiConnect, loopback."""

    def __init__(self, url):
        self.url = url

    def _ask(self, action, **params):
        from app import anki_connect
        return anki_connect.invoke(action, self.url, timeout=60, **params)

    def notes(self, ids):
        from app import anki_connect
        return anki_connect.notes_info(self.url, ids)

    def exists(self, name):
        return name in (self._ask("getMediaFilesNames", pattern=name) or [])

    def read(self, name):
        return self._ask("retrieveMediaFile", filename=name)

    def store(self, name, data):
        return self._ask("storeMediaFile", filename=name, data=data, deleteExisting=False)

    def point(self, note_id, fields):
        return self._ask("updateNoteFields", note={"id": note_id, "fields": fields})

    def delete(self, name):
        return self._ask("deleteMediaFile", filename=name)

    def users(self, name):
        """The notes whose fields name the file (a search for the name, as written). An answer that isn't a list
        raises: never read as "no one", which would delete a file in use (review B #11)."""
        from app import anki_connect
        found = self._ask("findNotes", query=f'"{anki_connect.escape_query(name)}"')
        if not isinstance(found, list):
            raise anki_connect.AnkiError(f"findNotes answered {type(found).__name__}, not a list", kind="protocol")
        return found

    def reviewing(self):
        from app import anki_connect
        return anki_connect.reviewing(self.url)

    def writer(self, verb):
        from app import anki_connect
        return anki_connect.writer(verb, wait=10.0)


def rename(media, made, key, audio_field, picture_field, fingerprints=None):
    """Rename one batch's media by the line. `made`: [(note id, line start, line end, line text)] — the notes the
    batch made; `key`: the episode's key; `fingerprints`: {(start, end): the store's fingerprint} where it has one ->
    {"renamed": n notes pointed, "stored": n files stored, "reused": n names already in Anki, "deleted": n old}."""
    out = {"renamed": 0, "stored": 0, "reused": 0, "deleted": 0}
    if not made:
        return out
    with media.writer("Connect's media names"):     # held from the first read (review B #25)
        by_id = {n.get("noteId"): n for n in media.notes([m[0] for m in made])}
        seen = set()                    # new names stored (or found) in this call
        for note_id, start, end, text in made:
            note = by_id.get(note_id)
            if note is None:
                continue                # deleted meanwhile: nothing to point
            if media.reviewing():       # asked before each note's writes (K88, review B #6): resumed next look
                raise Reviewing()
            print_ = (fingerprints or {}).get((start, end)) or fingerprint(text)
            fields, old_names = {}, set()
            for field, pattern in ((audio_field, _SOUND), (picture_field, _IMG)):
                if not field:
                    continue
                value = ((note.get("fields") or {}).get(field) or {}).get("value") or ""
                old = _named(value, pattern)
                if not old or old.startswith(PREFIX):
                    continue            # nothing there, or named by the line already (a resumed rename)
                new = line_name(key, start, end, print_, os.path.splitext(old)[1] or ".bin")
                if new not in seen:
                    if media.exists(new):
                        out["reused"] += 1
                    else:
                        data = media.read(old)
                        if not data:
                            continue    # the old file isn't there: leave the note as it is
                        media.store(new, data)
                        out["stored"] += 1
                    seen.add(new)
                fields[field] = value.replace(old, new)
                old_names.add(old)
            if fields:
                media.point(note_id, fields)
                out["renamed"] += 1
            for old in sorted(old_names):       # this note's old names, now no note's (another may share one)
                if not media.users(old):
                    media.delete(old)
                    out["deleted"] += 1
    return out
