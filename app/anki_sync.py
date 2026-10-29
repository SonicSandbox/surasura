"""Live Anki -> known words: the sync engine behind the Anki window and the dashboard's auto-sync.

Pure data, no tkinter, no tokenizer (the dashboard process imports this — spec I6). It talks to Anki
only through `app/anki_connect.py` and only ever READS from it (I7).

**Why no tokenizer:** the analyzer tokenizes every `dictForm` itself when it loads KnownWord.json and
also keeps the raw string as a known lemma (`analyzer.load_known_words`). So a synced entry's
`dictForm` is simply the word the field holds (`anki_match.card_word` for Japanese) — the user's own
spelling, no mis-tokenised isolated word.

The rules that make this safe to run silently in the background:

  * **Append-only.** A sync never modifies, removes or reorders an existing entry (D2/I3). The only
    path that removes anything is the explicit `replace()`, which backs the file up to `.trash/` and
    verifies the copy byte-for-byte first (D12).
  * **Only studied notes count** (`-is:new`, D3) — the new-card backlog is exactly what Junban ranks.
  * **A file we cannot parse is never written** (I4). Every write is temp file + `os.replace` (I5).
  * **Delta by default.** The state file remembers the note ids already seen; only new ones are
    fetched — and, in the same request, those Anki says were edited since the last sync (its own
    `edited:n` search), so a card corrected after it was read is read again. A review is no edit.
    Still append-only: a word an edit took out stays known (`replace()` starts over). Any change of
    decks/fields/url/suspended, or a KnownWord.json someone else rewrote (D4: its stat signature no
    longer matches the one we recorded AFTER our own write), makes the next run a full one —
    harmless, because appends are deduped.
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
from app.path_utils import get_user_files_path, read_text
from app.token_index import known_signature
from app.unicode_ranges import HAN, KANA

KNOWN_FILE = "KnownWord.json"
STATE_FILE = "anki_sync_state.json"
STATE_VERSION = 1
SOURCE = "AnkiConnect"
# The source of the words GraduatedList.txt held, merged once into KnownWord.json (app/graduated_merge.py): Replace
# keeps them.
GRADUATED_SOURCE = "GraduatedList"
GRADUATED_MARK = "graduated"        # an entry the merge raised to KNOWN: kept_graduated keeps it known too
# The new-card backlog of the same decks (Junban_Backlog_Spec §5.2, WP-B7): the words waiting in Anki,
# so the report can mark them. Derived data — never the user's known words — and read-only on Anki.
BACKLOG_FILE = "anki_backlog.json"
# Bump when a note's entry would now be read differently: a backlog saved under another version is
# read again in full, once. 2: a field is read as its one word (`anki_match.card_word`: 「撒く」 -> 撒く).
# 3: in NFKC (ﾊﾞｼｯと -> バシッと).
BACKLOG_VERSION = 3
# The young cards of the same decks (Piyo ぴよ, Sonic 2026-10-29): each studied card not yet mature, its word and its
# interval, so a practice round ranks the words still being learned first (`app/practice.py`) with Anki closed. Derived
# data, read-only on Anki; a version change reads every young note again.
YOUNG_FILE = "anki_young.json"
YOUNG_VERSION = 1
MATURE_DAYS = 21                    # Anki's own line: a card is mature from a 21-day interval

# analyzer.has_target_language, built from the same ranges (app/unicode_ranges.py) — importing the
# analyzer would load fugashi/pandas into the dashboard (I6). The copy this replaced stopped at U+9FAF,
# so a card whose word is written in CJK Extension B (𠮷, 𩸽) was dropped as "no Japanese".
_JA_TARGET_RE = re.compile(f'[{KANA}{HAN}]')  # Hiragana + Katakana + Kanji
_ZH_TARGET_RE = re.compile(f'[{HAN}]')        # any CJK ideograph

# The dashboard's auto-sync thread and the window's Sync button may overlap; one writer at a time.
_LOCK = threading.Lock()

# ...and across programs (P0.3 04 §2): KnownWord.json's read-modify-write holds `known-words-<lang>` (`app/locks.py`),
# taken here for every caller — the dashboard's sync, the Anki window, surasura-cli's known-sync — and by the
# known-words imports. Every caller runs on a worker, so it may wait this long for another program's write.
KNOWN_LOCK_WAIT = 10.0


def known_lock_name(language):
    return f"known-words-{language}"


def hold_known_words(language, verb, wait=None):
    """KnownWord.json's lock for `verb` (a short user-facing phrase) -> (the held lock or None, a refusal or None).
    The refusal is a plain sentence naming the program that kept it. No lock (None, None) when this thread holds it
    already (the command line takes it first, to answer `busy`), or when it can't be used at all."""
    from app import locks
    name = known_lock_name(language)
    try:
        if locks.held_here(name):
            return None, None
        return locks.take(name, verb, wait=KNOWN_LOCK_WAIT if wait is None else wait), None
    except locks.Busy as e:
        who = (e.holder or {}).get("verb") or "another Surasura program"
        return None, (f"Your known words are being updated by {who}. Nothing was changed: try again in a moment.",
                      e.holder)
    except Exception as e:
        print(f"Warning: the known-words lock can't be used ({e}).")
        return None, None


def _hold_known(language, mode):
    """`hold_known_words` for the sync -> (the held lock or None, a refusal `SyncResult` or None)."""
    held, refused = hold_known_words(language, "Anki known-words sync")
    if refused is None:
        return held, None
    return None, SyncResult(mode=mode, error=refused[0], busy=True, held_by=refused[1],
                            total_known=count_known(language))


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
    busy: bool = False             # refused: another program held KnownWord.json (`held_by` is its record)
    held_by: "dict | None" = None
    # replace (and its dry run): what the new file keeps beside Anki's words, and its known total
    kept_graduated: int = 0        # the old GraduatedList.txt's words (past Graduates), kept known
    dropped_ignored: int = 0       # the words dismissed (IGNORED entries) the new file drops: back on the list
    total_after: int = 0           # the known total the replace writes (`total_known`: the file now, for a dry run)
    changed: bool = False          # replace / restore with `expect`: the numbers moved since they were confirmed;
                                   # nothing was written (the numbers now are in this result)
    # sync: the notes it read (notesInfo), handed to the young cards' read beside it (`sync_all`) so a card studied
    # today isn't asked for twice; emptied there, never shown
    read: list = field(default_factory=list, repr=False, compare=False)


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
        for attempt in range(5):            # a reader holding the file open refuses the replace for a moment (02 §8)
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path, data, indent=2):
    _atomic_write_bytes(path, json.dumps(data, ensure_ascii=False, indent=indent).encode("utf-8"))


def _read_known_file(language, path=None):
    """(data, words) for the current KnownWord.json (or the one at `path`); (None, None) when it does not exist.
    Raises _KnownFileError when it exists but cannot be used — the caller must then write nothing."""
    path = path or _known_path(language)
    if not os.path.exists(path):
        return None, None
    try:
        # In the file's own encoding (path_utils.read_text) — a BOM or UTF-16 no longer refuses it —
        # strictly: this file is written back, so a byte no encoding reads stops the sync instead.
        data = json.loads(read_text(path, language, errors="strict"))
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


def known_file_refusal(language, path=None):
    """Why a replacing import must write nothing over KnownWord.json (or the one at `path`): it exists but can't be
    read, so its past Graduates' words can't be kept and its known words can't be counted (AD2-1: the
    rule the .apkg merge follows). -> that plain sentence, or None (missing or usable)."""
    try:
        _read_known_file(language, path)
    except _KnownFileError as e:
        return str(e)
    return None


def _norm(term):
    return unicodedata.normalize("NFKC", str(term or "")).strip()


def _is_known(entry):
    """Same rule as analyzer.load_known_words."""
    return isinstance(entry, dict) and (entry.get("knownStatus", "") == "KNOWN"
                                        or entry.get("hasCard", 0) == 1)


def _known_keys(words):
    return {key for key in (_norm(w.get("dictForm")) for w in words if _is_known(w)) if key}


def count_known(language, path=None):
    """Distinct known dictForms in KnownWord.json (all sources; or the one at `path`), NFKC-normalised. 0 when the file
    is missing or unreadable. A JSON count — known ENTRIES, not the analyzer's expanded lemma set."""
    try:
        _data, words = _read_known_file(language, path)
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


# The automatic sync runs at most this often (seconds). The dashboard counts its own presses; another program
# (surasura-cli known-sync) counts from the last sync on disk, so the limit holds across programs.
SYNC_EVERY = 300


def may_sync(language, settings, throttle=True, now=None):
    """May a sync of `language`'s known words start now? None when it may; else `(why, plain words)`. The gates the
    dashboard's automatic sync and `surasura-cli known-sync` share (P1.2), in order:

      * "off" — `SURASURA_NO_ANKI_SYNC` (the test suites, a developer's run): Anki is never reached;
      * "no-decks" — no decks chosen for this language in the Anki window;
      * "never-synced" — the FIRST sync is always the user's own "Sync now" (Anki_Known_Sync_Spec §5.6): the Anki
        window pre-picks every studied deck the moment it opens, and until the user has reviewed that pick and synced
        once, nothing may be read into their known words behind their back (appends can't be taken back);
      * "throttled" (only with `throttle`) — the last sync on disk is under SYNC_EVERY seconds old.
    """
    if os.environ.get("SURASURA_NO_ANKI_SYNC"):
        return "off", "Anki is switched off for this run (SURASURA_NO_ANKI_SYNC)."
    if not list(((settings or {}).get("anki_sync_decks") or {}).get(language) or []):
        return "no-decks", "Choose your Anki decks in Surasura's Anki window first."
    last = load_state(language).get("last_sync")
    if not last:
        return "never-synced", "Sync once from Surasura's Anki window first."
    if throttle:
        try:
            age = ((now or datetime.now()) - datetime.fromisoformat(str(last))).total_seconds()
        except ValueError:
            age = None
        if age is not None and 0 <= age < SYNC_EVERY:
            return "throttled", f"synced {int(age)} s ago"
    return None


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


def _edited_days(since):
    """The n of Anki's `edited:n` that covers every edit since `since` (an ISO time): whole days back, plus one for
    Anki's day boundary. None without a usable `since` (a first read)."""
    try:
        elapsed = (datetime.now() - datetime.fromisoformat(str(since))).total_seconds()
    except (TypeError, ValueError):
        return None
    return int(max(0.0, elapsed) // 86400) + 2


def _ids_and_edits(url, query, since):
    """(the note ids `query` finds, those among them whose text was edited since `since`) in ONE request.

    The edits are Anki's own `edited:n` search: notes whose fields changed in the last n days — n whole
    days back to `since` (an ISO time) plus one for Anki's day boundary, so a day's edits are read again
    once more at most, harmlessly. A review never counts, only an edit. No usable `since` (a first read)
    asks the one question; an Anki too old for `edited:` fails the second slot, and no edits is the answer.
    Raises AnkiError as `find_notes` does when the first slot fails."""
    days = _edited_days(since)
    if days is None:
        return anki_connect.find_notes(url, query), set()
    replies = anki_connect.multi([{"action": "findNotes", "params": {"query": query}},
                                  {"action": "findNotes", "params": {"query": f"({query}) edited:{days}"}}], url)
    found, edits = (list(replies) + [None, None])[:2]
    if not isinstance(found, dict) or found.get("error") is not None or not isinstance(found.get("result"), list):
        error = found.get("error") if isinstance(found, dict) else None
        raise AnkiError(f"Anki could not search your decks: {error or 'no answer'}", kind="action")
    edited = edits.get("result") if isinstance(edits, dict) and edits.get("error") is None else None
    return anki_connect._int_ids(found["result"]), set(anki_connect._int_ids(edited or []))


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


def word_field(model_fields, chosen):
    """[the note type's WORD field] — `chosen[0]`, or Auto's first field when `chosen == []` — or [] when the note
    type lacks it. Roles go by the chosen index, never by position in `resolve_fields`' answer: where the word field
    is missing, the "Also read" field (`chosen[1]`) is still no word field."""
    return resolve_fields(model_fields, list(chosen or [])[:1])


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
    from app import anki_match
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
        words = word_field(ordered, fields) if language == "ja" else []
        for name in resolved:
            value = note_fields.get(name)
            raw = value.get("value", "") if isinstance(value, dict) else ""
            # The Japanese WORD field: the one word it holds, read as Junban and the report read it
            # (`anki_match.card_word`): 撒く<br>まく and 撒く<div>まく</div> are 撒く — never 撒くまく, and never
            # まく, the reading on its second line, known as a word of its own. The "Also read" field, and
            # Chinese: one term per line — a sentence field marks every word of its sentence known (the analyzer
            # tokenizes each term); a <br> or a <div> between two lines parts them (in Japanese an opening <div>
            # too, as Anki writes a second line), never fuses them.
            if name in words:
                lines = [anki_match.card_word(raw, "ja")]
            else:
                lines = clean_field_html(anki_match._LINE_TAG_RE.sub("\n", raw) if language == "ja" else raw).split("\n")
            for line in lines:
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
        held, refused = _hold_known(language, "full" if full else "delta")
        if refused is not None:
            return refused
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
        finally:
            if held is not None:
                held.release()


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

    query = scope_query(decks, include_suspended)
    # A delta asks, in one request, for the studied notes and for those edited since the last sync — an edited
    # card's text is read again (add-only: its new words are appended; a word the edit took out stays known).
    note_ids, edited = ((anki_connect.find_notes(url, query), set()) if full
                        else _ids_and_edits(url, query, state.get("last_sync")))
    seen = set() if full else set(_int_list(state.get("note_ids")))
    todo = [n for n in note_ids if n not in seen or n in edited]
    notes = anki_connect.notes_info(url, todo)
    result.scanned = len(notes)
    result.read = notes
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


# Connect's own notes (P2.5 row 2.5.7): with its preview on, its waiting cards count as backlogged in any deck
CONNECT_TAG_QUERY = '"tag:surasura::connect::*"'


def backlog_query(decks, connect=False):
    """'(deck:"A" OR deck:"B") is:new -is:suspended' — the cards waiting to be learned (D6: the known
    sync's own decks); with `connect`, Connect's waiting cards too, whatever their deck (P2.5 row 2.5.7: the
    report's *In Anki* mark and Junban see what Connect made)."""
    terms = [f'deck:"{anki_connect.escape_query(d)}"' for d in _clean_decks(decks)]
    if connect:
        terms.append(CONNECT_TAG_QUERY)     # no deck chosen: Connect's cards alone (Connect's count, laptop row 41)
    return f"({' OR '.join(terms)}) is:new -is:suspended"


def _connect_on():
    """Connect's preview, as settings.json holds it now (one place for every caller of `sync_backlog`, so the
    window's and the command line's reads never disagree about the scope). Off when it can't be read. `connect_enabled`
    alone, never `connect_on` (P4.1 row 4.1.1): it describes your set-up — the cards Connect made are in Anki with the
    automation off too, and the report's *In Anki* mark still sees them."""
    try:
        from app import settings_manager
        return bool(settings_manager.load_settings().get("connect_enabled"))
    except Exception:
        return False


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


def _note_word(note, fields, language):
    """A notesInfo note's word, or None when it holds none: the known sync's WORD field (`word_field`: Auto = the
    first; never the "Also read" field, even on a note type that lacks the word field), read the way Junban reads it
    (`anki_match.card_word`: 「撒く」 and 撒く<br>まく are 撒く). The backlog and the young cards both read it here."""
    from app import anki_match
    note_fields = note.get("fields") if isinstance(note.get("fields"), dict) else {}
    ordered = sorted(note_fields, key=lambda name: _field_order(note_fields[name]))
    resolved = word_field(ordered, fields)
    if not resolved:
        return None
    value = note_fields.get(resolved[0])
    word = anki_match.card_word(value.get("value", "") if isinstance(value, dict) else "", language)
    if not word or not _has_target(word, language):
        return None
    return word


def _backlog_entry(note, fields, language):
    """{word, keys, source, freqsort} for one backlog note, or None when it holds no usable word. The
    word comes from the known sync's WORD field (`word_field`: Auto = the first; never the "Also read"
    field, even on a note type that lacks the word field), read the way Junban reads it
    (`anki_match.card_word`: 「撒く」 and 撒く<br>まく are 撒く), so the report and the reorder agree on a
    card's word."""
    from app import anki_match
    word = _note_word(note, fields, language)
    if word is None:
        return None
    note_fields = note.get("fields") if isinstance(note.get("fields"), dict) else {}
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


def sync_all(language, url, decks, fields, settings, include_suspended=False, full=False, progress=None):
    """Every known-words sync, in one order (the window's automatic sync and *Sync now*, the Tk dashboard's,
    `surasura-cli known-sync`): the studied words (`sync`), the same decks' new cards (`sync_backlog`, for the report's
    backlog marks), their young cards (`sync_young`, for Piyo's practice rounds), then Known from Anki
    (`read_known_signal`: your suspended or marked cards) -> `(result, signal)`.
    Before, the 3.0 window's sync stopped after the backlog, so the signal was read only by Connect's own known-sync
    — which the window's 5-minute sync nearly always throttled — and a card you suspended and marked never counted
    (laptop round 7 #43). The words the signal marks are words this sync made known: they join its `added` and
    `total_known`, so whoever acts on a sync that added words (the window's automatic Generate) acts on them too. A
    sync that failed reads neither the new cards nor the signal (`signal` None): KnownWord.json or Anki can't be
    trusted this time.
    `progress(what, done, total)`: the command line's progress lines. Never raises (each part keeps its own rule)."""
    if progress is not None:
        progress("reading Anki", 0, 3)
    result = sync(language, url, decks, fields, include_suspended=include_suspended, full=full)
    if getattr(result, "error", None):
        return result, None                 # Anki or KnownWord.json can't be trusted this time: nothing more read
    if progress is not None:
        progress("reading Anki's new cards", 1, 3)
    try:
        sync_backlog(language, url, decks, fields)
    except Exception as e:                  # a backlog read that fails never costs the sync its result
        print(f"Anki sync: the backlog read failed ({e})")
    if progress is not None:
        progress("reading Anki's young cards", 2, 3)
    try:
        sync_young(language, url, decks, fields, read=getattr(result, "read", None))
    except Exception as e:                  # nor does the young cards' read
        print(f"Anki sync: the young cards' read failed ({e})")
    if isinstance(getattr(result, "read", None), list):
        result.read = []                    # read: the notes aren't kept past the sync
    signal = read_known_signal(language, url, decks, fields, settings)
    marked = len((signal or {}).get("marked") or ())
    if marked and result is not None:
        result.added += marked
        result.total_known += marked
    return result, signal


def read_known_signal(language, url, decks, fields, settings):
    """Known from Anki (P2.4 row 2.4.15), beside this sync, in the same decks: cards you suspended (or the signal you
    chose, `known_from_anki`) mark their words known — `app/connect/known_signal.py`. Only while Connect is on (its
    switch and, 3.0, D29's automation: `settings_manager.connect_on`, P4.1 row 4.1.1): off, nothing is imported or
    asked (None). Never raises: a read that fails is tried at the next sync."""
    from app import settings_manager
    if not settings_manager.connect_on(settings):
        return None
    try:
        from app.connect import known_signal
        return known_signal.read(language, url, _clean_decks(decks), [str(f) for f in (fields or [])], settings)
    except Exception as e:
        print(f"Known from Anki skipped: {e}")
        return None


def sync_backlog(language, url, decks, fields):
    """Read the new-card backlog of `decks` into `User Files/<lang>/anki_backlog.json`.

    Read-only on Anki; delta by note id (a note already read keeps its entry — unless Anki says it was
    edited since the backlog was written, when it is read again, so a corrected card's word is the new
    one; the decks, the fields or `BACKLOG_VERSION` changing reads everything again). Never raises:
    returns `(count, error)`.
    A failed read, or an empty answer where there was a backlog, keeps the previous file (the
    "refuse to write when the input can't be trusted" rule). The file is written only when what it
    holds changed — its notes, decks, fields or version: its (mtime, size) is in the report's render
    signature, and a rewrite for a new `synced_at` alone (which nothing reads) made the next Generate
    re-render the report instead of opening it.
    """
    decks = _clean_decks(decks)
    fields = [str(f) for f in (fields or [])]
    if not decks:
        return 0, "Choose at least one deck first."
    url = url or anki_connect.DEFAULT_URL
    connect = _connect_on()
    with _LOCK:
        old = load_backlog(language)
        same_scope = (old.get("version") == BACKLOG_VERSION and old.get("decks") == sorted(decks)
                      and old.get("fields") == fields and bool(old.get("connect")) == connect)
        cached = old.get("notes") if same_scope and isinstance(old.get("notes"), dict) else {}
        query = backlog_query(decks, connect)
        try:
            note_ids, edited = (_ids_and_edits(url, query, old.get("synced_at")) if cached
                                else (anki_connect.find_notes(url, query), set()))
            todo = [n for n in note_ids if str(n) not in cached or n in edited]
            notes = anki_connect.notes_info(url, todo) if todo else []
        except AnkiError as e:
            return count_backlog(language), str(e)
        entries = {str(n): cached[str(n)] for n in note_ids if str(n) in cached and n not in edited}
        for note in notes:
            entry = _backlog_entry(note, fields, language)
            if entry is not None and note.get("noteId") is not None:
                entries[str(note["noteId"])] = entry
        if not entries and count_backlog(language):
            return count_backlog(language), ("Anki answered with an empty backlog, so the last one "
                                             "was kept.")
        if same_scope and old.get("notes") == entries:
            return len(entries), None       # nothing it holds changed: the file stays as it is
        record = {"version": BACKLOG_VERSION, "synced_at": _now_iso(), "decks": sorted(decks),
                  "fields": fields, "notes": entries}
        if connect:
            record["connect"] = True        # the scope read Connect's cards too (absent: as before P2.5)
        try:
            _atomic_write_json(_backlog_path(language), record, indent=None)
        except OSError as e:
            return count_backlog(language), f"Could not save your Anki backlog: {e}"
        return len(entries), None


# --------------------------------------------------------------------------- #
# The young cards (Piyo ぴよ's practice words) — the studied cards of the same decks not yet mature
# --------------------------------------------------------------------------- #
def _young_path(language):
    return os.path.join(get_user_files_path(language), YOUNG_FILE)


def young_lock_name(language):
    return f"anki-young-{language}"


def young_query(decks, interval=None):
    """'(deck:"A" OR deck:"B") -is:new -is:suspended prop:ivl=<interval>': the notes with a studied card of that
    interval in days (0 while it is in its first learning steps); without `interval`, every young one
    (`prop:ivl<MATURE_DAYS`). A suspended card is put away, never being learned."""
    terms = " OR ".join(f'deck:"{anki_connect.escape_query(d)}"' for d in _clean_decks(decks))
    ivl = f"prop:ivl<{MATURE_DAYS}" if interval is None else f"prop:ivl={int(interval)}"
    return f"({terms}) -is:new -is:suspended {ivl}"


def load_young(language, path=None):
    """The saved young cards' record (or the one at `path`), or {} when there is none or it cannot be read."""
    try:
        with open(path or _young_path(language), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def young_words(language, path=None):
    """[(word, interval)] of the saved young cards (or the record at `path`), the least settled first (the shortest
    interval; among equals the newest note), each word once. [] for anyone who never synced, or once every young card
    has grown mature."""
    notes = load_young(language, path).get("notes")
    rows = []
    for note_id, entry in (notes.items() if isinstance(notes, dict) else ()):
        if not isinstance(entry, dict) or not isinstance(entry.get("word"), str) or not entry["word"]:
            continue
        interval = entry.get("interval")
        if isinstance(interval, bool) or not isinstance(interval, int):
            continue
        try:
            newest = -int(note_id)
        except ValueError:
            newest = 0
        rows.append((interval, newest, entry["word"]))
    out, seen = [], set()
    for interval, _newest, word in sorted(rows):
        if word not in seen:
            seen.add(word)
            out.append((word, interval))
    return out


def count_young(language):
    """How many young notes with a word the saved record holds — 0 when none has been read yet."""
    notes = load_young(language).get("notes")
    return sum(1 for e in (notes.values() if isinstance(notes, dict) else ())
               if isinstance(e, dict) and isinstance(e.get("word"), str) and e["word"])


def _young_notes(url, decks, since):
    """({note id: the shortest interval of its young cards}, the young notes edited since `since`, whether the decks
    hold any studied note) in ONE request: a findNotes per interval, 0 to MATURE_DAYS - 1 days, shortest first; the
    decks' studied notes (`scope_query`: an empty answer there is Anki open on another profile, or the decks renamed —
    not every card grown mature); and with `since` Anki's `edited:n` over the young ones (`_edited_days`; an Anki too
    old for it fails that slot, and no edits is the answer). Raises AnkiError when an interval's or the decks' search
    fails: a record missing some intervals would rank words wrongly."""
    actions = [{"action": "findNotes", "params": {"query": young_query(decks, days)}} for days in range(MATURE_DAYS)]
    actions.append({"action": "findNotes", "params": {"query": scope_query(decks)}})
    days = _edited_days(since)
    if days is not None:
        actions.append({"action": "findNotes", "params": {"query": f"({young_query(decks)}) edited:{days}"}})
    replies = list(anki_connect.multi(actions, url)) + [None] * len(actions)
    intervals = {}
    for interval, reply in zip(range(MATURE_DAYS + 1), replies):
        if not isinstance(reply, dict) or reply.get("error") is not None or not isinstance(reply.get("result"), list):
            error = reply.get("error") if isinstance(reply, dict) else None
            raise AnkiError(f"Anki could not search your decks: {error or 'no answer'}", kind="action")
        if interval < MATURE_DAYS:
            for note_id in anki_connect._int_ids(reply["result"]):
                intervals.setdefault(note_id, interval)
    studied = bool(replies[MATURE_DAYS]["result"])
    edits = replies[MATURE_DAYS + 1] if days is not None else None
    edited = edits.get("result") if isinstance(edits, dict) and edits.get("error") is None else None
    return intervals, set(anki_connect._int_ids(edited if isinstance(edited, list) else [])), studied


def sync_young(language, url, decks, fields, read=None):
    """Read the young cards of `decks` into `User Files/<lang>/anki_young.json`: each note with a studied card not yet
    mature (an interval under MATURE_DAYS; never a new or suspended card), its word (`_note_word`, as the backlog reads
    it) and the shortest interval of those cards — what Piyo's practice rounds rank first (`app/practice.py`), read
    from this file with Anki closed.

    Read-only on Anki, and two requests at most beside the sync's own (notesInfo in chunks of 250): notesInfo carries no interval and the known
    sync reads only new or edited notes, while every review moves an interval with no edit — so one request asks the
    notes of each interval (Anki's `prop:ivl=n` searches, 0 to 20 days, in one `multi`: no card is rendered, unlike
    cardsInfo, and no search per card, unlike getIntervals) with the young notes edited since the last read. A note
    the record doesn't hold yet, or one edited, takes its word from `read` (the notes the known sync read a moment
    before: a card studied today, an edit) and only otherwise from a second request, notesInfo (a first read, a
    mature card forgotten back to young, other decks or fields).
    Written under its lock (`anki-young-<lang>`: two programs' syncs never interleave a read and a write) with a temp
    file and os.replace, and only when what it holds changed. A failed read keeps the previous file; no young card at
    all, in decks that still hold studied notes, writes an empty record (every card grew mature); none studied at all
    keeps the last one (another profile open, the decks renamed). Never raises: returns `(count, error)`."""
    decks = _clean_decks(decks)
    fields = [str(f) for f in (fields or [])]
    if not decks:
        return 0, "Choose at least one deck first."
    url = url or anki_connect.DEFAULT_URL
    try:
        from app import locks
        held = locks.take(young_lock_name(language), "reading Anki's young cards", wait=KNOWN_LOCK_WAIT)
    except Exception as e:                  # Busy: another program reads them right now; nothing written here
        return count_young(language), f"Anki's young cards weren't read this time ({e})."
    try:
        return _sync_young(language, url, decks, fields, read)
    finally:
        held.release()


def _sync_young(language, url, decks, fields, read=None):
    old = load_young(language)
    same_scope = (old.get("version") == YOUNG_VERSION and old.get("decks") == sorted(decks)
                  and old.get("fields") == fields)
    cached = old.get("notes") if same_scope and isinstance(old.get("notes"), dict) else {}
    try:
        intervals, edited, studied = _young_notes(url, decks, old.get("synced_at") if cached else None)
        todo = [n for n in intervals if str(n) not in cached or n in edited]
        fresh = {n.get("noteId"): n for n in read or () if isinstance(n, dict)}
        ask = [n for n in todo if n not in fresh]
        notes = [fresh[n] for n in todo if n in fresh] + (anki_connect.notes_info(url, ask) if ask else [])
    except AnkiError as e:
        return count_young(language), str(e)
    if not studied and cached:
        return count_young(language), ("Anki found no studied card in your decks (another profile open, or the decks "
                                       "renamed?), so the last young cards were kept.")
    entries = {}
    for note_id, interval in intervals.items():
        entry = cached.get(str(note_id))
        if note_id not in edited and isinstance(entry, dict) and isinstance(entry.get("word"), str):
            entries[str(note_id)] = {"word": entry["word"], "interval": interval}
    for note in notes:
        note_id = note.get("noteId")
        if note_id in intervals:
            # a note with no usable word is kept with "" so it isn't read again at every sync
            entries[str(note_id)] = {"word": _note_word(note, fields, language) or "", "interval": intervals[note_id]}
    # Nothing it holds changed: the file stays as it is — unless edits were read and its time (the edits' cursor) is a
    # day old, so a note edited without a new word (a Hint, a Meaning) isn't read again at every sync for days.
    if same_scope and old.get("notes") == entries and not (edited and _edited_days(old.get("synced_at")) > 2):
        return count_young(language), None
    record = {"version": YOUNG_VERSION, "synced_at": _now_iso(), "decks": sorted(decks), "fields": fields,
              "notes": entries}
    try:
        _atomic_write_json(_young_path(language), record, indent=None)
    except OSError as e:
        return count_young(language), f"Could not save your Anki young cards: {e}"
    return count_young(language), None


# --------------------------------------------------------------------------- #
# Replace / restore (D12) — the only paths that remove entries, always backed up first
# --------------------------------------------------------------------------- #
def _backup_current(language):
    """Copy KnownWord.json to .trash/KnownWord.<YYYYMMDD-HHMMSS>.json, whole and verified or not at all
    (`path_utils.backup_to_trash`). Returns the backup filename, or None when there is no file. Raises
    OSError when the backup can't be made."""
    from app.path_utils import backup_to_trash
    dst = backup_to_trash(_known_path(language))
    return os.path.basename(dst) if dst else None


def confirmed(result):
    """The numbers Anki's Replace confirmation shows (from its dry run): what Anki brings, the past Graduates' words
    kept, the dismissed words dropped, the known total now and after. `replace(..., expect=)` writes only while they
    still hold."""
    return (result.added, result.kept_graduated, result.dropped_ignored, result.total_known, result.total_after)


def replace(language, url, decks, fields, include_suspended=False, dry_run=False, expect=None):
    """Rebuild KnownWord.json from Anki only — keeping the words the old GraduatedList.txt gave it (`kept_graduated`);
    the dismissed words are dropped (`replaced_words`: the one rule of every replacing import, a clean slate).
    Backs up the current file first and verifies it.
    Offline, an empty result, a KnownWord.json that can't be read (its kept words and its count would be false:
    AD3-2), or a failed backup => nothing written. `dry_run` writes nothing and
    returns the numbers the confirmation dialog shows. `expect` (`confirmed` of the confirmed dry run): when
    the numbers differ by the time the write would start (Anki or the file changed meanwhile), nothing is written and
    the result says `changed`, with the numbers now — the window asks again."""
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
        known_path = _known_path(language)
        refusal = known_file_refusal(language)
        if refusal is not None:
            result.error = refusal
            return result
        if dry_run:
            _count_replacement(result, known_path, language, words)
            return result

        held, refused = _hold_known(language, mode)
        if refused is not None:
            return refused
        try:
            return _replace_held(language, result, known_path, words, url, decks, fields, include_suspended,
                                 note_ids, now, expect)
        finally:
            if held is not None:
                held.release()


def _count_replacement(result, path, language, words):
    """`result`'s numbers for a replace of `path` with `words`: the totals now and after, the words kept. -> the words
    to write."""
    final, result.kept_graduated, result.dropped_ignored = replaced_words(path, language, words)
    result.total_known = count_known(language)
    result.total_after = len(_known_keys(final))
    return final


def _replace_held(language, result, known_path, words, url, decks, fields, include_suspended, note_ids, now,
                  expect=None):
    """`replace`'s write, holding KnownWord.json's lock: the numbers checked against the confirmed ones, the backup,
    then the write."""
    refusal = known_file_refusal(language)                # changed since the dry run: still never written over
    if refusal is not None:
        result.error = refusal
        return result
    words = _count_replacement(result, known_path, language, words)
    if expect is not None and tuple(confirmed(result)) != tuple(expect):
        result.mode, result.changed = "dry-run", True       # nothing written: the window asks again
        return result
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


def kept_graduated(path, language, words):
    """The old GraduatedList.txt's words (merged once, app/graduated_merge.py: entries of `source: "GraduatedList"`,
    or raised and marked GRADUATED_MARK) in the KnownWord.json at `path`, kept known by every import that replaces
    the file — Anki's Replace, the Jiten and Migaku imports (S3.1 D13, Q4-10): -> those `words` doesn't name, to add,
    known (one the user also dismissed, a marked IGNORED entry, is added KNOWN, `previousStatus: IGNORED`: AD-1); and
    an UNKNOWN / LEARNING entry of `words` one of them names is made KNOWN in place (marked too), an IGNORED one only
    marked. A file that is missing or can't be read keeps none (the replacer's backup holds them)."""
    try:
        data = json.loads(read_text(path, language, errors="strict"))
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    current = data.get("words") if isinstance(data, dict) else data
    if not isinstance(current, list):
        return []
    graduated = {}
    for entry in current:
        if isinstance(entry, dict) and (entry.get("source") == GRADUATED_SOURCE or entry.get(GRADUATED_MARK) is True):
            key = _norm(entry.get("dictForm"))
            if key:
                graduated.setdefault(key, entry)
    taken = set()
    for w in words:
        if isinstance(w, dict):
            key = _norm(w.get("dictForm"))
            taken.add(key)
            if key in graduated and w.get("knownStatus") in ("UNKNOWN", "LEARNING"):
                w["previousStatus"] = w["knownStatus"]
                w["knownStatus"] = "KNOWN"
                w[GRADUATED_MARK] = True
            elif key in graduated and w.get("knownStatus") == "IGNORED":
                w[GRADUATED_MARK] = True        # dismissed again by the import: ignored, still a past Graduate's word
    kept = []
    for key, entry in graduated.items():
        if key not in taken:
            taken.add(key)
            if not _is_known(entry):            # a past Graduate's word the user dismissed: known (AD-1)
                entry = dict(entry, previousStatus=entry.get("knownStatus"), knownStatus="KNOWN")
            kept.append(entry)
    return kept


def dismissed_words(path, language, words):
    """The IGNORED entries of the KnownWord.json at `path` — words the user dismissed in Migaku (an earlier import) —
    that `words` doesn't hold known or IGNORED: what a replacing import drops (`replaced_words` counts them: they come
    back on the list, the backup keeps them; one `words` names UNKNOWN / LEARNING comes back too, AD-3). -> those
    entries, first per word, in the file's order. A file missing or unreadable has none."""
    try:
        data = json.loads(read_text(path, language, errors="strict"))
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    current = data.get("words") if isinstance(data, dict) else data
    if not isinstance(current, list):
        return []
    taken = {_norm(w.get("dictForm")) for w in words
             if _is_known(w) or (isinstance(w, dict) and w.get("knownStatus") == "IGNORED")}
    kept = []
    for entry in current:
        if isinstance(entry, dict) and entry.get("knownStatus") == "IGNORED":
            key = _norm(entry.get("dictForm"))
            if key and key not in taken:
                taken.add(key)
                kept.append(entry)
    return kept


def replaced_words(path, language, words):
    """What a replacing import writes over the KnownWord.json at `path` — one rule for Anki's Replace, Migaku's and
    Jiten's (IK-40): `words`, then the past Graduates' words kept known (`kept_graduated`, which may raise an entry of
    `words` in place). Nothing else of the old file: the words the user dismissed are dropped (a clean slate from the
    source; the replacer's backup keeps them). -> (those words, how many Graduates' kept, how many dismissed words
    dropped — `dismissed_words`: back on the list)."""
    graduated = kept_graduated(path, language, words)
    dropped = dismissed_words(path, language, words + graduated)
    return words + graduated, len(graduated), len(dropped)


def replace_numbers(language, words, path=None):
    """What a replacing import's confirmation states, before it runs (IK-18): (known words now, known words after,
    past Graduates' words kept, dismissed words dropped) — `replaced_words` over the language's KnownWord.json (or the
    one at `path`), on a copy. Reads only; `words` is left as it is."""
    import copy
    path = path or _known_path(language)
    trial = copy.deepcopy([w for w in words if isinstance(w, dict)])
    final, graduated, ignored = replaced_words(path, language, trial)
    return count_known(language, path), len(_known_keys(final)), graduated, ignored


# A replacing import's child (Migaku's, Jiten's) given the numbers its confirmation stated (`--expect now,after,
# graduated,ignored`) counts them again holding the lock; moved meanwhile (a sync appended words), it writes nothing and
# exits EXIT_CHANGED, and the window reads again and asks again — the rule Anki's Replace follows (`expect=`).
EXIT_CHANGED = 4


class NumbersChanged(Exception):
    """The known words changed since the user confirmed the replace: nothing was written."""


def parse_expect(text):
    """`--expect`'s "now,after,graduated,ignored" -> the four numbers (a tuple), or None when not given."""
    if not text:
        return None
    return tuple(int(n) for n in str(text).split(","))


def check_numbers(language, words, path, expect):
    """Raises NumbersChanged when `replace_numbers` for `words` over the file at `path` is no longer `expect` (the
    numbers the user confirmed). The caller holds KnownWord.json's lock. `expect` None: nothing checked."""
    if expect is not None and tuple(replace_numbers(language, words, path)) != tuple(expect):
        raise NumbersChanged("Your known words changed since you confirmed, so nothing was replaced.")


def restore_previous(language, expect=None, now=None):
    """Undo the last replace: back up the CURRENT file the same way (so this is undoable too), copy
    the backup back atomically, and clear the seen note ids so the next sync re-evaluates cleanly.
    `expect`: the backup the user confirmed putting back, and `now` the known total they saw; another backup by now
    (a Replace meanwhile) or another total (a sync meanwhile) restores nothing and the result says `changed`."""
    with _LOCK:
        held, refused = _hold_known(language, "restore")
        if refused is not None:
            return refused
        try:
            return _restore_held(language, expect, now)
        finally:
            if held is not None:
                held.release()


def _restore_held(language, expect=None, now=None):
    """`restore_previous`, holding KnownWord.json's lock."""
    result = SyncResult(mode="restore")
    state = load_state(language)
    name = state.get("last_backup")
    if (expect is not None and name != expect) or (now is not None and count_known(language) != now):
        result.changed = True
        result.total_known = count_known(language)
        return result
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
