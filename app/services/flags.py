"""The flagged sentences: Send report's list (journey v3 SPEC §4, J-FLAGS). The journey page's ⚑ (through the door's
`line/flag`) and, later, the review loop's *Parsing mistake* both add to this one list; Send report shows it on *What
goes*, a tick each, and carries the ticked lines in its zip (`app/report.py`, `journey/flagged.json`).

    add(language, line, word, source, …)   flag a line (flagged again: its new reasons and note) -> the record
    unflag(language, source, key, word)    take one off -> True when it was there
    read(language)                         every flagged line, oldest first
    count(language)                        how many
    for_report(language)                   [(id, changed_ns, what the zip holds)] for Send report
    clear_sent(language, sent)             after the receiver's confirmed answer: the lines it holds, unless changed since
    door_route(body, app) · door_state(lang, since_ns, app)   the door's `line/flag` and the lit ⚑ read back

**A line** (one per source + the page's key + word): `line` (its text, cut at `LINE_MAX`), `word`, `show` and `episode`
(names, never a path: `place()`), `at` (the line's time in seconds, or None), `reasons` (of `REASONS`), `note`, `source`
(`journey` · `loop`), `added`, and the list's own `id`, `key` and `changed_ns`. Never the text of the learner's own
dictionaries, never any other line of the file.

**The file** is user data: `User Files/<lang>/flagged_lines.json`, written only here — atomically (a temp file, then
replace), under the `flagged-lines-<lang>` lock (the door's threads and the loop both write), read through
`path_utils.read_text` strictly. A file no encoding reads, or that isn't the list, is set aside into `.trash` (dated,
never purged) before a fresh list is written: never overwritten. At `MAX_LINES` a new line is refused in words (`Full`),
never an old one dropped. Qt-free; every call blocks on the file (the window calls it on a worker, the door on its own
thread).
"""
import datetime
import json
import ntpath
import os
import re
import secrets
import time

from app import path_utils

FILE = "flagged_lines.json"
FORMAT = 1
SOURCES = ("journey", "loop")            # the journey's ⚑ · the review loop's *Parsing mistake* (Kyou-DW)
REASONS = ("parsing", "too_long", "bad_audio", "wrong_sentence", "other")
PARSING = "parsing"
MAX_LINES = 200                          # a language's list (PROVISIONAL): past it a new line is refused
LINE_MAX = 400
WORD_MAX = 64
NAME_MAX = 120
NOTE_MAX = 500
KEY_MAX = 200
LOCK_WAIT = 5.0
VERB = "Flagging a sentence"
FULL = (f"You've flagged {MAX_LINES} sentences. Send them in a report first, or take some off.")   # (PROVISIONAL)

_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)|\\")     # a drive, a share, a root or a backslash (Fate/Zero: a title)


class Full(Exception):
    """The list holds `MAX_LINES`: a new line is refused (one already there may still change)."""


def _path(language):
    return os.path.join(path_utils.get_user_files_path(language), FILE)


def _cut(text, most):
    return " ".join(str(text or "").split())[:most]


def place(path):
    """A file the line is from -> (show, episode): its folder's name and its own name without the extension. Only the
    names: never the rest of the path."""
    path = str(path or "").rstrip("\\/")
    folder, name = ntpath.split(path)
    return _cut(ntpath.basename(folder.rstrip("\\/")), NAME_MAX), _cut(ntpath.splitext(name)[0], NAME_MAX)


def _name(text):
    """A show or episode name as given; one that is a path keeps only its last part (never a folder above it)."""
    text = str(text or "").strip()
    if _PATH.search(text):
        text = ntpath.basename(text.rstrip("\\/"))
    return _cut(text, NAME_MAX)


def _time(at):
    if isinstance(at, bool) or not isinstance(at, (int, float)) or at != at or at < 0:
        return None
    return round(float(at), 2)


def _reasons(reasons):
    given = {str(r) for r in (reasons or ())}
    return [r for r in REASONS if r in given]


def _same(entry, source, key, word):
    return entry.get("source") == source and entry.get("key") == key and entry.get("word") == word


def _load(language):
    """The list as written -> [entries]. Raises ValueError (not the list, or no encoding reads it whole)."""
    path = _path(language)
    if not os.path.exists(path):
        return []
    try:
        data = json.loads(path_utils.read_text(path, language, errors="strict"))
    except UnicodeDecodeError as e:
        raise ValueError(f"unreadable ({e})")
    if not isinstance(data, dict) or not isinstance(data.get("lines"), list):
        raise ValueError("not the flagged sentences' list")
    return [e for e in data["lines"] if isinstance(e, dict) and e.get("id")]


def read(language):
    """Every flagged line, oldest first ([] when there is none, or the file can't be read: it is never written over)."""
    try:
        return _load(language)
    except (OSError, ValueError):
        return []


def count(language):
    return len(read(language))


def _write(language, lines):
    from app.anki_sync import _atomic_write_bytes
    data = {"format": FORMAT, "lines": lines}
    _atomic_write_bytes(_path(language), json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))


def _change(language, change):
    """`change(lines) -> answer` under the list's lock, the file read again under it, written once when `change`
    changed it. A file that can't be read is set aside first (`backup_to_trash(move=True)`), never written over."""
    from app import locks
    with locks.take(f"flagged-lines-{language}", VERB, wait=LOCK_WAIT):
        try:
            lines = _load(language)
        except ValueError as e:
            kept = path_utils.backup_to_trash(_path(language), move=True)
            print(f"Flagged sentences: the list couldn't be read ({e}); set aside as {kept}, a new one started.")
            lines = []
        before = json.dumps(lines, ensure_ascii=False, sort_keys=True)
        answer = change(lines)
        if json.dumps(lines, ensure_ascii=False, sort_keys=True) != before:
            _write(language, lines)
        return answer


def add(language, line, word, source, key="", show="", episode="", at=None, reasons=(), note="", path=None,
        now=None):
    """Flag `line` (for `word`) from `source` (`SOURCES`); `key`: the source's own key for the line (the page's
    line_id); `path`: the file it's from, when the caller has no names (kept as `place(path)`). The same source, key
    and word flagged again takes the new reasons and note. Raises ValueError (no line, an unknown source), Full,
    locks.Busy. -> the record."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    line, word, key = _cut(line, LINE_MAX), _cut(word, WORD_MAX), _cut(key, KEY_MAX)
    if not line:
        raise ValueError("no line to flag")
    if path:
        show, episode = place(path)
    record = {"line": line, "word": word, "show": _name(show), "episode": _name(episode), "at": _time(at),
              "reasons": _reasons(reasons), "note": _cut(note, NOTE_MAX), "source": source, "key": key}

    def change(lines):
        for entry in lines:
            if _same(entry, source, key, word):
                if any(entry.get(k) != v for k, v in record.items()):
                    entry.update(record, changed_ns=time.time_ns())
                return dict(entry)
        if len(lines) >= MAX_LINES:
            raise Full(FULL)
        stamp = (now or datetime.datetime.now()).isoformat(timespec="seconds")
        entry = dict(record, id=secrets.token_hex(6), added=stamp, changed_ns=time.time_ns())
        lines.append(entry)
        return dict(entry)
    return _change(language, change)


def unflag(language, source, key, word):
    """The line `add` keeps for this source, key and word taken off -> True when it was there."""
    key, word = _cut(key, KEY_MAX), _cut(word, WORD_MAX)

    def change(lines):
        kept = [e for e in lines if not _same(e, source, key, word)]
        gone = len(kept) != len(lines)
        lines[:] = kept
        return gone
    return _change(language, change)


def changed_ns(language, source, key, word):
    """When that line last changed (ns), or None: not flagged."""
    for entry in read(language):
        if _same(entry, source, _cut(key, KEY_MAX), _cut(word, WORD_MAX)):
            return entry.get("changed_ns")
    return None


def clear_sent(language, sent):
    """After the receiver's confirmed answer: each line of `sent` ({id: changed_ns} as zipped) leaves the list, unless
    it changed since (flagged again with a new note: it stays for the next report). -> how many left."""
    sent = dict(sent or {})
    if not sent:
        return 0

    def change(lines):
        kept = [e for e in lines if not (e.get("id") in sent and e.get("changed_ns") == sent[e.get("id")])]
        gone = len(lines) - len(kept)
        lines[:] = kept
        return gone
    return _change(language, change)


# --- Send report ----------------------------------------------------------------------------------------------------- #
def _split(language, text):
    """How Surasura reads the line: [[surface, word], …] by the list's own tokenizer; None when it can't be worked out
    (no tagger)."""
    from app import analyzer
    if language == "zh":
        tokens = analyzer.ChineseTokenizer().tokenize(text)
    else:
        analyzer.SANITIZE_JA = True                  # (as the token store read the library)
        tokens = analyzer.JapaneseTokenizer().tokenize(text)
    return [[t[2], t[0]] for t in tokens]


def for_report(language, split=None):
    """The list for Send report's zip -> [(id, changed_ns, line)], `line` exactly what `journey/flagged.json` holds for
    it: the line, its word, show, episode, time, reasons, note, when, which piece, and for a parsing line Surasura's
    split of it (`split(language, text)`, the tokenizer by default; None when it fails). Never the list's id or key."""
    split = split or _split
    out = []
    for entry in read(language):
        shown = {k: entry.get(k) for k in ("line", "word", "show", "episode", "at", "reasons", "note", "added",
                                            "source")}
        if PARSING in (entry.get("reasons") or ()):
            try:
                shown["split"] = split(language, entry.get("line") or "")
            except Exception as e:                   # the split is help, never a reason to fail the report
                print(f"Flagged sentences: a line couldn't be split ({type(e).__name__}).")
                shown["split"] = None
        out.append((entry["id"], entry.get("changed_ns"), shown))
    return out


def entry_bytes(language, lines):
    """`journey/flagged.json`'s bytes for `lines` (`for_report`'s third parts), UTF-8."""
    return json.dumps({"format": FORMAT, "language": language, "lines": list(lines)}, ensure_ascii=False,
                      indent=1).encode("utf-8")


# --- the door (journey v3 SPEC §3.3: `line/flag`; app/services/journey_door.py's registry) -------------------------- #
def door_route(body, app):
    """`line/flag` {line_id, word, line, show, episode, time, reasons, note, on, at?} -> {flagged}. `at`: a queued
    press's time (ms), skipped when the line changed after it (journey_door.stale). Refuses in words: no line, a
    stale press, the list full (`full`), the list busy."""
    from app import door, locks
    from app.services import journey_door
    lang = body.get("lang") or app.language()
    if lang not in ("ja", "zh"):
        raise door.RouteError("This page's language isn't one Surasura reads.", "refused")
    key, word = str(body.get("line_id") or ""), str(body.get("word") or "")
    if journey_door.stale(body.get("at"), changed_ns(lang, "journey", key, word)):
        raise door.RouteError("This flag changed in Surasura since: the page shows it as it is now.",
                              journey_door.STALE)
    try:
        if not body.get("on", True):
            unflag(lang, "journey", key, word)
            return {"flagged": False}
        add(lang, body.get("line"), word, "journey", key=key, show=body.get("show"), episode=body.get("episode"),
            at=body.get("time"), reasons=body.get("reasons") or (), note=body.get("note") or "")
    except Full as e:
        raise door.RouteError(str(e), "full")
    except locks.Busy:
        raise door.RouteError("Surasura is busy with your flagged sentences: try again in a moment.", "busy")
    except ValueError as e:
        raise door.RouteError(f"Nothing was flagged ({e}).", "refused")
    return {"flagged": True}


def door_state(lang, since_ns, app):
    """The lit ⚑: every line the journey flagged, [[line_id, word], …] — the whole set each time (the render carries
    no flags, so a page always needs them)."""
    return {"flagged": [[e.get("key") or "", e.get("word") or ""] for e in read(lang) if e.get("source") == "journey"]}
