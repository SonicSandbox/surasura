"""Live Anki -> known words: the sync engine behind the Anki window and the dashboard's auto-sync.

Pure data, no tkinter, no tokenizer (the dashboard process imports this — spec I6). It talks to Anki
only through `app/anki_connect.py` and only ever READS from it (I7).

**Why no tokenizer:** the analyzer tokenizes every `dictForm` itself when it loads KnownWord.json and
also keeps the raw string as a known lemma (`analyzer.load_known_words`). So a synced entry's
`dictForm` is simply the cleaned field text — the user's own spelling, no mis-tokenised isolated word.

The rules that make this safe to run silently in the background:

  * **Append-only.** A sync never modifies, removes or reorders an existing entry (D2/I3). The only
    path that removes anything is the explicit `replace()`, which backs the file up to `.trash/` and
    verifies the copy byte-for-byte first (D12).
  * **Only studied notes count** (`-is:new`, D3) — the new-card backlog is exactly what Junban ranks.
  * **A file we cannot parse is never written** (I4). Every write is temp file + `os.replace` (I5).
  * **Delta by default.** The state file remembers the note ids already seen; only new ones are
    fetched. Any change of decks/fields/url/suspended, or a KnownWord.json someone else rewrote
    (D4: its stat signature no longer matches the one we recorded AFTER our own write), makes the
    next run a full one — harmless, because appends are deduped.
"""

import json
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from app import anki_connect
from app.anki_connect import AnkiError
from app.anki_utils import clean_field_html
from app.path_utils import get_user_files_path
from app.token_index import known_signature

KNOWN_FILE = "KnownWord.json"
STATE_FILE = "anki_sync_state.json"
STATE_VERSION = 1
SOURCE = "AnkiConnect"
# The new-card backlog of the same decks (Junban_Backlog_Spec §5.2, WP-B7): the words waiting in Anki,
# so the report can mark them. Derived data — never the user's known words — and read-only on Anki.
BACKLOG_FILE = "anki_backlog.json"
BACKLOG_VERSION = 1

# Copied from analyzer.has_target_language — importing the analyzer would load fugashi/pandas into
# the dashboard (I6).
_JA_TARGET_RE = re.compile(r'[぀-ゟ゠-ヿ一-龯]')  # Hiragana + Katakana + Kanji
_ZH_TARGET_RE = re.compile(r'[一-鿿]')                            # any CJK ideograph

# The dashboard's auto-sync thread and the window's Sync button may overlap; one writer at a time.
_LOCK = threading.Lock()


@dataclass
class SyncResult:
    added: int = 0                 # words appended (sync) / words in the new file (replace)
    scanned: int = 0               # notes examined this run
    mode: str = "delta"            # "delta" | "full" | "replace" | "restore" | "dry-run"
    skipped_by_model: dict = field(default_factory=dict)   # {model_name: notes skipped (no usable field)}
    fields_by_model: dict = field(default_factory=dict)    # {model_name: [resolved field names]} ([] = unresolved)
    total_known: int = 0           # count_known() after the operation
    backup: "str | None" = None    # replace/restore: backup filename written
    error: "str | None" = None     # human-readable, shown in the UI verbatim; None on success


class _KnownFileError(Exception):
    """KnownWord.json exists but is not something we can safely append to."""


# --------------------------------------------------------------------------- #
# Paths and small file helpers
# --------------------------------------------------------------------------- #
def _known_path(language):
    return os.path.join(get_user_files_path(language), KNOWN_FILE)


def _state_path(language):
    return os.path.join(get_user_files_path(language), STATE_FILE)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_bytes(path, data):
    """Temp file in the same folder, fsync, then os.replace — a reader never sees half a file."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path, data, indent=2):
    _atomic_write_bytes(path, json.dumps(data, ensure_ascii=False, indent=indent).encode("utf-8"))


def _read_known_file(language):
    """(data, words) for the current KnownWord.json; (None, None) when it does not exist.
    Raises _KnownFileError when it exists but cannot be used — the caller must then write nothing."""
    path = _known_path(language)
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise _KnownFileError(f"Your known words file could not be read, so nothing was changed "
                              f"({KNOWN_FILE}: {e}).")
    if isinstance(data, list):
        return data, data
    if isinstance(data, dict):
        words = data.get("words", [])
        if isinstance(words, list):
            return data, words
    raise _KnownFileError(f"Your known words file is not in a format Surasura recognises, so "
                          f"nothing was changed ({KNOWN_FILE}).")


def _norm(term):
    return unicodedata.normalize("NFKC", str(term or "")).strip()


def _is_known(entry):
    """Same rule as analyzer.load_known_words."""
    return isinstance(entry, dict) and (entry.get("knownStatus", "") == "KNOWN"
                                        or entry.get("hasCard", 0) == 1)


def _known_keys(words):
    return {key for key in (_norm(w.get("dictForm")) for w in words if _is_known(w)) if key}


def count_known(language):
    """Distinct known dictForms in KnownWord.json (all sources), NFKC-normalised. 0 when the file is
    missing or unreadable. A JSON count — known ENTRIES, not the analyzer's expanded lemma set."""
    try:
        _data, words = _read_known_file(language)
    except _KnownFileError:
        return 0
    return len(_known_keys(words or []))


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
def _read_state(language, quarantine):
    path = _state_path(language)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if isinstance(state, dict):
            return state
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    if quarantine:
        # The Junban/Reels precedent: keep the evidence, start clean. A full sync follows, which is
        # harmless because appends are deduped.
        try:
            os.replace(path, f"{path}.corrupt-{time.strftime('%Y%m%d%H%M%S')}")
        except OSError:
            pass
    return {}


def load_state(language):
    """The saved sync state, or {} when missing or corrupt. Keys: version, url, decks, fields,
    include_suspended, note_ids, known_sig, last_sync (ISO), last_added, last_backup."""
    return _read_state(language, quarantine=False)


def _save_state(language, state):
    state = dict(state)
    state["version"] = STATE_VERSION
    _atomic_write_json(_state_path(language), state)


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def _clean_decks(decks):
    return [str(d) for d in (decks or []) if str(d or "").strip()]


def scope_query(decks, include_suspended=False):
    """'(deck:"A" OR deck:"B") -is:new [-is:suspended]'. `deck:"A"` includes A's subdecks."""
    terms = " OR ".join(f'deck:"{anki_connect.escape_query(d)}"' for d in _clean_decks(decks))
    query = f"({terms}) -is:new"
    return query if include_suspended else query + " -is:suspended"


def _multi_ids(url, queries):
    """One `multi` of findNotes; per-slot count of ids (a failed slot counts as 0)."""
    replies = anki_connect.multi([{"action": "findNotes", "params": {"query": q}} for q in queries], url)
    counts = []
    for reply in list(replies) + [None] * (len(queries) - len(replies)):
        result = reply.get("result") if isinstance(reply, dict) and reply.get("error") is None else None
        counts.append(len(result) if isinstance(result, list) else 0)
    return counts


def deck_study_counts(url, decks, include_suspended=False):
    """{deck: studied note count} in ONE request. Raises AnkiError (offline etc.)."""
    decks = _clean_decks(decks)
    if not decks:
        return {}
    counts = _multi_ids(url, [scope_query([d], include_suspended) for d in decks])
    return dict(zip(decks, counts))


def models_in_scope(url, decks, include_suspended=False):
    """{model_name: [field names in field order]} for the note types that have studied notes in the
    chosen decks. Three cheap requests: modelNames, one multi of findNotes, one multi of
    modelFieldNames. Raises AnkiError."""
    decks = _clean_decks(decks)
    if not decks:
        return {}
    names = anki_connect.invoke("modelNames", url)
    names = [str(n) for n in names] if isinstance(names, list) else []
    if not names:
        return {}
    scope = scope_query(decks, include_suspended)
    counts = _multi_ids(url, [f'{scope} note:"{anki_connect.escape_query(m)}"' for m in names])
    used = [m for m, n in zip(names, counts) if n]
    replies = anki_connect.multi([{"action": "modelFieldNames", "params": {"modelName": m}}
                                  for m in used], url)
    out = {}
    for model, reply in zip(used, replies):
        result = reply.get("result") if isinstance(reply, dict) and reply.get("error") is None else None
        out[model] = [str(f) for f in result] if isinstance(result, list) else []
    return out


def resolve_fields(model_fields, chosen):
    """Which of a note type's fields to read. `chosen == []` means Auto: the first field. Otherwise
    each chosen name present on the model (exact, then case-insensitive), in the chosen order.
    [] when none resolve — the caller skips and reports that note type."""
    model_fields = [str(f) for f in (model_fields or [])]
    chosen = [str(c) for c in (chosen or []) if str(c or "").strip()]
    if not chosen:
        return model_fields[:1]
    resolved = []
    for name in chosen:
        match = name if name in model_fields else next(
            (f for f in model_fields if f.lower() == name.lower()), None)
        if match is not None and match not in resolved:
            resolved.append(match)
    return resolved


# --------------------------------------------------------------------------- #
# Notes -> terms
# --------------------------------------------------------------------------- #
def _has_target(text, language):
    pattern = _ZH_TARGET_RE if language == "zh" else _JA_TARGET_RE
    return bool(pattern.search(text))


def _field_order(value):
    try:
        return int(value.get("order", 0)) if isinstance(value, dict) else 0
    except (TypeError, ValueError):
        return 0


def _terms_from_notes(notes, fields, language, result):
    """[(term, note_id)] from notesInfo entries, in note order, deduped within the batch.
    Fills result.fields_by_model and result.skipped_by_model."""
    out = []
    seen = set()
    for note in notes:
        model = str(note.get("modelName", ""))
        note_fields = note.get("fields") if isinstance(note.get("fields"), dict) else {}
        # Field order is the `order` value, never dict order (spec gotcha 9).
        ordered = sorted(note_fields, key=lambda name: _field_order(note_fields[name]))
        resolved = resolve_fields(ordered, fields)
        result.fields_by_model.setdefault(model, resolved)
        if not resolved:
            result.skipped_by_model[model] = result.skipped_by_model.get(model, 0) + 1
            continue
        for name in resolved:
            value = note_fields.get(name)
            raw = value.get("value", "") if isinstance(value, dict) else ""
            # One term per line: a <br> between two words must not fuse them. Separators like 、 or
            # ・ within a line stay whole — the analyzer tokenizes the dictForm anyway.
            for line in clean_field_html(raw).split("\n"):
                term = line.strip()
                key = _norm(term)
                if not key or key in seen or not _has_target(term, language):
                    continue
                seen.add(key)
                out.append((term, note.get("noteId")))
    return out


def _entry(term, note_id, language, now):
    entry = {"dictForm": term, "secondary": "", "partOfSpeech": "", "language": language,
             "knownStatus": "KNOWN", "hasCard": 1, "tracked": 0,
             "created": now, "mod": now, "isModern": 1, "source": SOURCE}
    try:
        entry["ankiNoteId"] = int(note_id)
    except (TypeError, ValueError):
        pass
    return entry


def _fresh_file(words):
    return {"exportDate": _now_iso(), "source": SOURCE, "statistics": {}, "words": words}


# --------------------------------------------------------------------------- #
# Sync (append-only)
# --------------------------------------------------------------------------- #
def sync(language, url, decks, fields, include_suspended=False, full=False):
    """Append the words of newly studied notes to KnownWord.json. Never raises; errors come back in
    `SyncResult.error` with nothing written."""
    with _LOCK:
        try:
            return _sync(language, url or anki_connect.DEFAULT_URL, _clean_decks(decks),
                         [str(f) for f in (fields or [])], bool(include_suspended), full)
        except AnkiError as e:
            return SyncResult(mode="full" if full else "delta", error=str(e),
                              total_known=count_known(language))
        except OSError as e:
            return SyncResult(mode="full" if full else "delta",
                              error=f"Could not save your known words: {e}",
                              total_known=count_known(language))


def _sync(language, url, decks, fields, include_suspended, full):
    if not decks:
        return SyncResult(mode="full" if full else "delta", error="Choose at least one deck first.",
                          total_known=count_known(language))

    state = _read_state(language, quarantine=True)
    known_path = _known_path(language)
    changed = (not state
               or state.get("url") != url
               or sorted(state.get("decks") or []) != sorted(decks)
               or list(state.get("fields") or []) != fields
               or bool(state.get("include_suspended")) != include_suspended
               or state.get("known_sig") != known_signature(known_path))
    full = bool(full or changed)
    result = SyncResult(mode="full" if full else "delta")

    note_ids = anki_connect.find_notes(url, scope_query(decks, include_suspended))
    seen = set() if full else set(_int_list(state.get("note_ids")))
    todo = [n for n in note_ids if n not in seen]
    notes = anki_connect.notes_info(url, todo)
    result.scanned = len(notes)
    terms = _terms_from_notes(notes, fields, language, result)

    # Re-read right before writing: never append to a stale in-memory copy.
    try:
        data, words = _read_known_file(language)
    except _KnownFileError as e:
        result.error = str(e)
        result.total_known = 0
        return result

    known = _known_keys(words or [])
    now = _now_iso()
    new_entries = [_entry(t, nid, language, now) for t, nid in terms if _norm(t) not in known]

    if new_entries:
        if data is None:
            data = _fresh_file(new_entries)
        elif isinstance(data, list):
            data = data + new_entries
        else:
            data = dict(data)      # every other top-level key (e.g. databaseFile) kept untouched
            data["words"] = list(words) + new_entries
        _atomic_write_json(known_path, data)
        words = data if isinstance(data, list) else data["words"]

    result.added = len(new_entries)
    result.total_known = len(_known_keys(words or []))
    _save_state(language, {
        "url": url, "decks": decks, "fields": fields, "include_suspended": include_suspended,
        "note_ids": sorted(note_ids),                       # N, not a union (spec gotcha 8)
        "known_sig": known_signature(known_path),           # AFTER our own write (gotcha 7)
        "last_sync": now, "last_added": result.added,
        "last_backup": state.get("last_backup"),
    })
    return result


def _int_list(values):
    out = []
    for value in values or []:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------- #
# The backlog (Junban_Backlog_Spec §5.2 / WP-B7) — the NEW cards of the same decks
# --------------------------------------------------------------------------- #
def _backlog_path(language):
    return os.path.join(get_user_files_path(language), BACKLOG_FILE)


def backlog_query(decks):
    """'(deck:"A" OR deck:"B") is:new -is:suspended' — the cards waiting to be learned (D6: the known
    sync's own decks)."""
    terms = " OR ".join(f'deck:"{anki_connect.escape_query(d)}"' for d in _clean_decks(decks))
    return f"({terms}) is:new -is:suspended"


def load_backlog(language):
    """The saved backlog, or {} when there is none or it cannot be read."""
    try:
        with open(_backlog_path(language), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def count_backlog(language):
    """How many notes wait in the saved backlog — 0 when none has been read yet."""
    notes = load_backlog(language).get("notes")
    return len(notes) if isinstance(notes, dict) else 0


def backlog_keys(language):
    """Every key a report word can match a backlog card by — its word and, for Japanese kana, the
    hiragana fold (`anki_match`). An empty set for anyone who never synced."""
    notes = load_backlog(language).get("notes")
    keys = set()
    for entry in (notes.values() if isinstance(notes, dict) else ()):
        if isinstance(entry, dict):
            keys.update(str(k) for k in entry.get("keys") or [] if k)
    return keys


def _backlog_entry(note, fields, language):
    """{word, keys, source, freqsort} for one backlog note, or None when it holds no usable word. The
    word comes from the same field the known sync reads (Auto = the first), cleaned the way Junban
    cleans it, so the report and the reorder agree on a card's word."""
    from app import anki_match
    note_fields = note.get("fields") if isinstance(note.get("fields"), dict) else {}
    ordered = sorted(note_fields, key=lambda name: _field_order(note_fields[name]))
    resolved = resolve_fields(ordered, fields)
    if not resolved:
        return None
    value = note_fields.get(resolved[0])
    word = anki_match.normalize_word(value.get("value", "") if isinstance(value, dict) else "")
    if not word or not _has_target(word, language):
        return None
    keys = [word]
    folded = anki_match.fold_kana(word) if language == "ja" else word
    if folded != word:
        keys.append(folded)

    def text(name):
        # HTML out, text kept whole — `normalize_word` would drop "[SubsPlease]" as furigana.
        field_value = note_fields.get(name)
        raw = field_value.get("value", "") if isinstance(field_value, dict) else ""
        return " ".join(clean_field_html(raw).split())

    freq = text("FreqSort")
    return {"word": word, "keys": keys, "source": text("MiscInfo").split(" @ ")[0].strip(),
            "freqsort": int(freq) if freq.isdigit() else None}


def sync_backlog(language, url, decks, fields):
    """Read the new-card backlog of `decks` into `User Files/<lang>/anki_backlog.json`.

    Read-only on Anki; delta by note id (a note already read keeps its entry; the decks or fields
    changing reads everything again). Never raises: returns `(count, error)`. A failed read, or an
    empty answer where there was a backlog, keeps the previous file (the "refuse to write when the
    input can't be trusted" rule).
    """
    decks = _clean_decks(decks)
    fields = [str(f) for f in (fields or [])]
    if not decks:
        return 0, "Choose at least one deck first."
    url = url or anki_connect.DEFAULT_URL
    with _LOCK:
        old = load_backlog(language)
        same_scope = old.get("decks") == sorted(decks) and old.get("fields") == fields
        cached = old.get("notes") if same_scope and isinstance(old.get("notes"), dict) else {}
        try:
            note_ids = anki_connect.find_notes(url, backlog_query(decks))
            todo = [n for n in note_ids if str(n) not in cached]
            notes = anki_connect.notes_info(url, todo) if todo else []
        except AnkiError as e:
            return count_backlog(language), str(e)
        entries = {str(n): cached[str(n)] for n in note_ids if str(n) in cached}
        for note in notes:
            entry = _backlog_entry(note, fields, language)
            if entry is not None and note.get("noteId") is not None:
                entries[str(note["noteId"])] = entry
        if not entries and count_backlog(language):
            return count_backlog(language), ("Anki answered with an empty backlog, so the last one "
                                             "was kept.")
        try:
            _atomic_write_json(_backlog_path(language), {
                "version": BACKLOG_VERSION, "synced_at": _now_iso(), "decks": sorted(decks),
                "fields": fields, "notes": entries}, indent=None)
        except OSError as e:
            return count_backlog(language), f"Could not save your Anki backlog: {e}"
        return len(entries), None


# --------------------------------------------------------------------------- #
# Replace / restore (D12) — the only paths that remove entries, always backed up first
# --------------------------------------------------------------------------- #
def _backup_current(language):
    """Copy KnownWord.json to .trash/KnownWord.<YYYYMMDD-HHMMSS>.json and verify the bytes.
    Returns the backup filename, or None when there is no file. Raises OSError on any mismatch."""
    src = _known_path(language)
    if not os.path.exists(src):
        return None
    trash = os.path.join(get_user_files_path(language), ".trash")
    os.makedirs(trash, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"KnownWord.{stamp}.json"
    n = 1
    while os.path.exists(os.path.join(trash, name)):
        name = f"KnownWord.{stamp}-{n}.json"
        n += 1
    dst = os.path.join(trash, name)
    shutil.copyfile(src, dst)
    with open(src, "rb") as a, open(dst, "rb") as b:
        if a.read() != b.read():
            raise OSError("the backup copy did not match your current file")
    return name


def replace(language, url, decks, fields, include_suspended=False, dry_run=False):
    """Rebuild KnownWord.json from Anki only. Backs up the current file first and verifies it.
    Offline, an empty result, or a failed backup => nothing written. `dry_run` writes nothing and
    returns the numbers the confirmation dialog shows."""
    with _LOCK:
        mode = "dry-run" if dry_run else "replace"
        url = url or anki_connect.DEFAULT_URL
        decks = _clean_decks(decks)
        fields = [str(f) for f in (fields or [])]
        include_suspended = bool(include_suspended)
        result = SyncResult(mode=mode)
        if not decks:
            result.error = "Choose at least one deck first."
            result.total_known = count_known(language)
            return result
        try:
            note_ids = anki_connect.find_notes(url, scope_query(decks, include_suspended))
            notes = anki_connect.notes_info(url, note_ids)
        except AnkiError as e:
            result.error = str(e)
            result.total_known = count_known(language)
            return result
        result.scanned = len(notes)
        terms = _terms_from_notes(notes, fields, language, result)
        now = _now_iso()
        words = [_entry(t, nid, language, now) for t, nid in terms]
        result.added = len(words)

        if not words:
            # An empty replace would wipe the file — never allowed.
            result.error = ("Anki returned no words for these decks and fields, so nothing was "
                            "changed.")
            result.total_known = count_known(language)
            return result
        if dry_run:
            result.total_known = count_known(language)
            return result

        known_path = _known_path(language)
        try:
            result.backup = _backup_current(language)
        except OSError as e:
            result.error = f"Nothing was replaced: your current list could not be backed up ({e})."
            result.total_known = count_known(language)
            return result
        try:
            _atomic_write_json(known_path, _fresh_file(words))
            state = load_state(language)
            state.update({
                "url": url, "decks": decks, "fields": fields, "include_suspended": include_suspended,
                "note_ids": sorted(note_ids), "known_sig": known_signature(known_path),
                "last_sync": now, "last_added": result.added, "last_backup": result.backup,
            })
            _save_state(language, state)
        except OSError as e:
            result.error = f"Replace failed: {e}"
        result.total_known = count_known(language)
        return result


def restore_previous(language):
    """Undo the last replace: back up the CURRENT file the same way (so this is undoable too), copy
    the backup back atomically, and clear the seen note ids so the next sync re-evaluates cleanly."""
    with _LOCK:
        result = SyncResult(mode="restore")
        state = load_state(language)
        name = state.get("last_backup")
        backup_path = os.path.join(get_user_files_path(language), ".trash", str(name or ""))
        if not name or not os.path.isfile(backup_path):
            result.error = "There is no previous list to restore."
            result.total_known = count_known(language)
            return result
        known_path = _known_path(language)
        try:
            with open(backup_path, "rb") as f:
                payload = f.read()
            result.backup = _backup_current(language)
            _atomic_write_bytes(known_path, payload)
            state.update({"note_ids": [], "known_sig": None,   # full resync next time
                          "last_backup": result.backup})
            _save_state(language, state)
        except OSError as e:
            result.error = f"Restore failed, nothing was changed: {e}"
        result.total_known = count_known(language)
        return result
