"""Known and Ignore, marked by hand (Kotoba-K, 3.0.12; the lead's draft for Sonic, leans PROVISIONAL): two categories,
kept apart, each in the file it already lives in.

- **Known** — you know it: an entry in `User Files/<lang>/KnownWord.json` (`source: "Surasura"`, `MARKED_SOURCE`), so
  it counts as known everywhere the known words count (the bar's figure, % known, Piyo's checks) and leaves your list.
  A Replace from Anki keeps it, as it keeps a past Graduate's word (`anki_sync.kept_graduated`).
- **Ignore** — not a word to learn (a name, a noise, a mis-parse): a line of `User Files/<lang>/IgnoreList.txt`, so it
  leaves your list but is never one of your known words.

    apply(language, marks)      [(word, mark)], mark "known" · "ignore" · None (clears what this module marked)
                                -> a `Marked`; one write of each file that changes, in the order given (the last
                                mark of a word wins); pushed on the language's undo stack (`Marked.undo_id`)
    undo(language, undo_id)     that write (else the last) put back as it was -> a `Marked` (`done` empty: none)
    marks(language)             {word: "known" | "ignore"}: what is marked now (our known entries, the Ignore list)
    left_out(language)          the words the window's numbers leave out at once (`Numbers.leave_out`): marks' words

A word known some other way (Anki, an import) is known already: Known writes nothing for it, and clearing never takes
another source's entry. Ignore and Known are one or the other: marking one clears this module's other.

Every write follows the word lists' rules (`app/services/word_lists.py`, CLAUDE.md §4): KnownWord.json's lock held for
the read-modify-write (one hold covers both files), each file read again under it, a file no encoding reads whole never
written, one dated byte-verified copy of each file per session before its first write (`word_lists._backup_once`: a
copy that fails writes nothing), atomic replace. A write that only
adds this module's own entries moves the sync's recorded signature with it, so the next sync stays a delta (one
that takes an entry out leaves the next sync a full one: a word Anki studied meanwhile is read again).
Qt-free and Tk-free: every call blocks on the files — the window calls it on a worker.
"""
import itertools
import os
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass, field

from app import anki_sync
from app.services import word_lists

MARKS = ("known", "ignore")
MARKED_SOURCE = anki_sync.MARKED_SOURCE     # a KnownWord.json entry marked known here ("Surasura")
VERB = "Marking words"
UNDO_DEPTH = 40
WORD_MAX = 64                       # a word longer than this is no word of a list

_UNDO = {}                          # language -> [(undo id, [(word, before), …]), …]: each apply's words as they were
_UNDO_LOCK = threading.Lock()
_IDS = itertools.count(1)


@dataclass
class Marked:
    done: list = field(default_factory=list)      # [(word, before, after)]: each word whose mark changed
    error: "str | None" = None                     # a plain sentence: nothing was changed
    busy: bool = False                             # another program held the known words' lock
    backups: list = field(default_factory=list)    # the dated copies this write made (the session's first)
    undo_id: "int | None" = None                   # this write on the undo stack (`undo(language, undo_id)`)


def _norm(word):
    return unicodedata.normalize("NFKC", str(word or "")).strip()


def _ours(entry):
    return isinstance(entry, dict) and entry.get("source") == MARKED_SOURCE and anki_sync._is_known(entry)


def clean(marks):
    """[(word, mark)] with every word trimmed and checked (a blank, a comment or an over-long word dropped, a mark not
    known to this module refused) -> the list, in order. ValueError for a mark that isn't one."""
    out = []
    for word, mark in marks:
        word = str(word or "").strip()
        if mark not in MARKS and mark is not None:
            raise ValueError(f"no such mark: {mark!r}")
        if (word and not word.startswith("#") and len(word) <= WORD_MAX and len(_norm(word)) <= WORD_MAX
                and "\n" not in word and "\r" not in word):
            out.append((word, mark))
    return out


def apply(language, marks, undoable=True):
    """Each word marked as asked (see the module docstring) -> a `Marked`."""
    try:
        wanted = clean(marks)
    except ValueError as e:
        return Marked(error=str(e))
    result = Marked()
    if not wanted:
        return result
    held, refused = anki_sync.hold_known_words(language, VERB)
    if refused is not None:
        result.error, result.busy = refused[0], True
        return result
    try:
        _apply_held(language, wanted, result)
    finally:
        if held is not None:
            held.release()
    if undoable and result.done and result.error is None:
        with _UNDO_LOCK:
            stack = _UNDO.setdefault(language, [])
            result.undo_id = next(_IDS)
            stack.append((result.undo_id, [(word, before) for word, before, _after in result.done]))
            del stack[:-UNDO_DEPTH]
    if result.done and result.error is None:
        _door_changed(language, result.done)
    return result


def undo(language, undo_id=None):
    """The write `undo_id` of `language` (else its last) put back — its words' marks as they were before it — and taken
    off the stack (a review's finding: a batch's Undo after another mark must undo the batch, not that mark). -> a
    `Marked`; nothing to undo (none, or that write is gone from the stack): an empty `done`. A refused or failed undo
    stays on the stack (the next asks again)."""
    with _UNDO_LOCK:
        stack = _UNDO.get(language) or []
        at = len(stack) - 1 if undo_id is None else next(
            (i for i, (uid, _w) in enumerate(stack) if uid == undo_id), None)
        entry = stack.pop(at) if at is not None and 0 <= at < len(stack) else None
    if entry is None:
        return Marked()
    result = apply(language, list(reversed(entry[1])), undoable=False)
    if result.error is not None:
        with _UNDO_LOCK:
            _UNDO.setdefault(language, []).append(entry)
    return result


def can_undo(language):
    with _UNDO_LOCK:
        return bool(_UNDO.get(language))


def marks(language):
    """{word: "known" | "ignore"} — this module's known entries (as written) and the Ignore list's words, each as the
    run reads its line ({} for a file that can't be read). A word on both reads "known"."""
    out = {}
    try:
        for word in word_lists._File(word_lists.list_path("ignore", language), language).words():
            out[word_lists._term(word, language)] = "ignore"    # a line's word as the run reads it (幽霊 - ghost: 幽霊)
    except (OSError, word_lists.Unreadable):
        pass
    try:
        _data, words = anki_sync._read_known_file(language)
    except anki_sync._KnownFileError:
        words = None
    for e in words or ():
        if _ours(e):
            word = str(e.get("dictForm") or "").strip()
            if word:
                out[word] = "known"
    return out


def left_out(language, since_ns=None):
    """The words marked here that the window's numbers leave out at once: every mark's word (`marks`). `since_ns`: a
    plan's time — neither file written since, the plan's Generate read them all and there is nothing to leave out (the
    known words aren't parsed at every plan read)."""
    if since_ns is not None:
        try:
            times = [os.stat(p).st_mtime_ns for p in (anki_sync._known_path(language),
                                                       word_lists.list_path("ignore", language)) if os.path.exists(p)]
        except OSError:
            times = None
        if times is not None and all(t < since_ns for t in times):
            return set()
    return set(marks(language))


# --- the write, the lock held ------------------------------------------------------------------------------------ #
def _apply_held(language, wanted, result):
    try:
        data, words = anki_sync._read_known_file(language)
    except anki_sync._KnownFileError as e:
        result.error = str(e)
        return
    ignore_path = word_lists.list_path("ignore", language)
    try:
        ignore = word_lists._File(ignore_path, language)
    except word_lists.Unreadable:
        result.error = word_lists._unreadable(word_lists.KINDS["ignore"])
        return
    except OSError as e:
        result.error = f"Nothing was changed: {word_lists.KINDS['ignore']} could not be read ({e})."
        return
    words = list(words or [])
    known_any = anki_sync._known_keys(words)
    ours = {_norm(e.get("dictForm")) for e in words if _ours(e)}
    listed = {word_lists._term(w, language) for w in ignore.words()}

    def state(word):
        if _norm(word) in ours:
            return "known"
        if word_lists._term(word, language) in listed:
            return "ignore"
        return None

    last = {}
    for word, mark in wanted:                       # the last mark of a word wins; each word once, in first order
        last[word] = mark
    add_known, drop_known, add_ignore, drop_ignore = [], set(), [], set()
    for word, mark in last.items():
        before = state(word)
        if before == mark:
            continue
        key, term = _norm(word), word_lists._term(word, language)
        if before == "known":
            drop_known.add(key)
            ours.discard(key)
            known_any.discard(key)
        elif before == "ignore":
            drop_ignore.add(term)
            listed.discard(term)
        if mark == "known":
            if key not in known_any:                # known some other way already: nothing to write for it
                add_known.append(word)
                known_any.add(key)
            ours.add(key)
        elif mark == "ignore":
            if term not in listed:
                add_ignore.append(word)
                listed.add(term)
        result.done.append((word, before, mark))
    if not result.done:
        return
    known_changed = bool(add_known or drop_known)
    ignore_changed = bool(add_ignore or drop_ignore)
    # Backups first, both: a copy that fails writes nothing at all.
    for path, changed in ((anki_sync._known_path(language), known_changed), (ignore_path, ignore_changed)):
        if not changed:
            continue
        try:
            made = word_lists._backup_once(path)
        except OSError as e:
            result.done = []
            result.error = f"Nothing was changed: {os.path.basename(path)} could not be backed up ({e})."
            return
        if made:
            result.backups.append(made)
    # KnownWord.json first, then the Ignore list; an Ignore list that can't be written puts the known words back as
    # they were: a write changes both files or neither.
    known_path = anki_sync._known_path(language)
    known_raw = None
    if known_changed:
        try:
            with open(known_path, "rb") as f:
                known_raw = f.read()
        except FileNotFoundError:
            known_raw = None
        except OSError as e:
            result.done = []
            result.error = f"Nothing was changed: your known words could not be read ({e})."
            return
        if not _write_known(language, data, words, add_known, drop_known, result):
            return
    if ignore_changed:
        if drop_ignore:
            ignore.lines = [(t, raw) for t, raw in ignore.lines
                            if word_lists._entry(t) is None or word_lists._term(word_lists._entry(t), language)
                            not in drop_ignore]
        if add_ignore:
            if not ignore.exists:
                ignore.add([word_lists.HEADERS["ignore"]])
            ignore.add(add_ignore)
        try:
            anki_sync._atomic_write_bytes(ignore.path, ignore.data())
        except OSError as e:
            if known_changed:
                _put_back(language, known_path, known_raw)
            result.done = []
            result.error = f"Nothing was changed: {word_lists.KINDS['ignore']} could not be written ({e})."
            return


def _put_back(language, path, raw):
    """KnownWord.json as it was before this write (`raw`; None: there was none)."""
    before_sig = anki_sync.known_signature(path)
    try:
        if raw is None:
            os.remove(path)
        else:
            anki_sync._atomic_write_bytes(path, raw)
    except OSError as e:
        print(f"Warning: the known words couldn't be put back after a failed write ({e}).")
        return
    anki_sync.follow_known_write(language, before_sig)


def _write_known(language, data, words, add_known, drop_known, result):
    path = anki_sync._known_path(language)
    before_sig = anki_sync.known_signature(path)
    kept = [e for e in words if not (_ours(e) and _norm(e.get("dictForm")) in drop_known)]
    now = anki_sync._now_iso()
    for word in add_known:
        entry = anki_sync._entry(word, None, language, now)
        entry.update(hasCard=0, source=MARKED_SOURCE)
        kept.append(entry)
    if data is None:
        data = anki_sync._fresh_file(kept)
        data["source"] = MARKED_SOURCE
    elif isinstance(data, list):
        data = kept
    else:
        data = dict(data)                           # every other top-level key kept untouched
        data["words"] = kept
    try:
        anki_sync._atomic_write_json(path, data)
    except OSError as e:
        result.done = []
        result.error = f"Nothing was changed: your known words could not be written ({e})."
        return False
    if not drop_known:                              # only adds: the sync's view holds (an entry taken out: a full sync
        anki_sync.follow_known_write(language, before_sig)   # next, so a word Anki studied meanwhile comes back)
    return True



# --- J-DOOR: the journey's door (app/door.py; the registry, app/services/journey_door.py) ------------------------ #
DOOR_MOST = 500                     # marks one door call may carry (the page's waiting marks, sent in batches)
DOOR_UNREAD = "Surasura couldn't read those marks."
_DOOR_SESSION = secrets.token_hex(4)    # this process's: an undo id the page got from an earlier one is refused
_CHANGED = {}                       # language -> {word: ns}: each word's last change by `apply` in this process
_CHANGED_LOCK = threading.Lock()


def _door_changed(language, done):
    """`apply`'s words, timed: the stale rule's record of a word changed (and changed back) in this session."""
    now = time.time_ns()
    with _CHANGED_LOCK:
        changed = _CHANGED.setdefault(language, {})
        for word, _before, _after in done:
            changed[_norm(word)] = now


def door_route(body, app):
    """`words/mark`: {lang, marks: [{word, mark: "known" | "ignore" | "", at?, was?}]} -> {done, undo_id, stale},
    `undo_id` this session's ("<session>.<n>": `words/undo` refuses one from an earlier Surasura),
    written as the word card's are (`app.services.mark_words`: the window follows). `mark` "" clears what this module
    marked. A mark sent from the page's queue carries `at` (its press time, ms since the epoch) and `was` (the mark the
    page showed before the press): one whose word has changed since the page drew it, in a file written after the
    press, or changed by this Surasura after the press (even back again), is skipped and listed in `stale` (Charter G4: a waiting press never erases newer work; the page then draws
    the app's mark). Marks it can't read are refused (the page lets them go); a write that couldn't be made is "busy"
    (another program holds the known words) or "failed", in plain words: the page keeps those marks."""
    from app import door
    from app.services import journey_door
    language, sent = body.get("lang"), body.get("marks")
    if language not in journey_door.LANGS or not isinstance(sent, list) or len(sent) > DOOR_MOST:
        raise door.RouteError(DOOR_UNREAD, "refused")
    for m in sent:
        if (not isinstance(m, dict) or not isinstance(m.get("word"), str)
                or m.get("mark") not in ("known", "ignore", "", None)
                or m.get("was") not in ("known", "ignore", "", None)):
            raise door.RouteError(DOOR_UNREAD, "refused")
    pairs, stale, now = [], [], None
    for m in sent:
        if m.get("at") is not None:
            if now is None:
                now = (marks(language), _door_times(language))
            if _door_stale(language, m, *now):
                stale.append(m["word"])
                continue
        pairs.append((m["word"], m.get("mark") or None))
    if not pairs:
        return {"done": 0, "undo_id": None, "stale": stale}
    result = app.services.mark_words(language, pairs)
    if result.error is not None:
        raise door.RouteError(result.error, "busy" if result.busy else "failed")     # (the page keeps them)
    undo_id = f"{_DOOR_SESSION}.{result.undo_id}" if result.undo_id is not None else None
    return {"done": len(result.done), "undo_id": undo_id, "stale": stale}


def door_undo(body, app):
    """`words/undo`: {lang, undo_id} -> {done}: that write put back (`app.services.undo_marks`), never another one (a
    call without its id is refused: the window's own last write is not the page's; so is an id from an earlier
    Surasura, whose numbers this one reuses). An Undo is never queued by the page: Surasura closed, it is let go."""
    from app import door
    from app.services import journey_door
    language, sent = body.get("lang"), body.get("undo_id")
    session, _dot, number = sent.partition(".") if isinstance(sent, str) else ("", "", "")
    if language not in journey_door.LANGS or not number.isdigit() or not number.isascii():
        raise door.RouteError("Surasura couldn't read that Undo.", "refused")
    if session != _DOOR_SESSION:
        raise door.RouteError("That Undo is from before Surasura was opened again.", "refused")
    undo_id = int(number)
    result = app.services.undo_marks(language, undo_id)
    if result.error is not None:
        raise door.RouteError(result.error, "busy" if result.busy else "failed")
    return {"done": len(result.done)}


def door_state(language, since_ns, app):
    """`state`'s marks: every mark this module holds now ({word: "known" | "ignore"}: a word the render drew marked
    here that isn't in it was cleared), or None when neither file was written since the render (`since_ns`)."""
    if since_ns is not None and all(t < since_ns for t in _door_times(language).values()):   # (a file gone: read)
        return None
    return marks(language)


def _door_times(language):
    """{"known": ns, "ignore": ns}: each file's last write (a file missing now: changed now, as far as anyone can tell —
    one deleted since the render or the press is newer work)."""
    times = {}
    for mark, path in (("known", anki_sync._known_path(language)), ("ignore", word_lists.list_path("ignore", language))):
        try:
            times[mark] = os.stat(path).st_mtime_ns
        except OSError:
            times[mark] = time.time_ns()
    return times


def _door_stale(language, m, current, times):
    """A waiting mark whose word changed after its press: changed by this Surasura since (`_CHANGED`: even back to what
    the page showed), or its mark now isn't the one the page showed (`was`) and the file that could have changed it
    was written after `at` (the word's file for a mark it has now; either file for one it lost)."""
    from app.services import journey_door
    with _CHANGED_LOCK:
        here = _CHANGED.get(language, {}).get(_norm(m["word"]))
    if journey_door.stale(m.get("at"), here):
        return True
    now = current.get(m["word"].strip(), "")
    if now == (m.get("was") or ""):
        return False
    changed = times.get(now) if now else max(times.values(), default=None)
    return journey_door.stale(m.get("at"), changed)
