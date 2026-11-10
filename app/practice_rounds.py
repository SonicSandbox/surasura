"""Saved practice rounds (H9, Sonic 2026-10-28: "save their past ones (as an option) so they can choose to do it again,
as well as ask to save the responses as context for later").

One JSON file per round in `User Files/<lang>/practice/` (user data: never committed, never deleted or trimmed by
Surasura): the round's choices (role, kind, source), its words with their lines, so it can be done again exactly as it
was, and what the learner asked to keep — lines (the AI's checked replies, the learner's answers) and notes ("mixes up
冒険 and 危険"). A later round reads back only a little of it (`context`: the newest rounds' newest lines and notes,
CONTEXT_CHARS at most), so saved rounds never flood the AI's context.

Writes are Surasura's own files only: each save reads the round, adds to it and writes it whole with a temp file and
os.replace (`anki_sync._atomic_write_json`), under the `practice` lock, so a crash mid-save leaves the round as it was
and two AI sessions saving at once never lose each other's lines. Every other round is a file of its own, never
touched by a save. A file that can't be read is left alone: never listed, never written over.

The switch is `practice_keep_rounds` (settings.json, Settings → Connections; on by default, PROVISIONAL A6P-6): off,
nothing is saved and nothing saved is read back to the AI. The MCP server (app/cli/mcp_server.py) is the only caller.
`tests/test_practice_rounds.py`.
"""
import json
import os
import re
import secrets
from datetime import datetime

FOLDER = "practice"
SETTING = "practice_keep_rounds"
TEXT_CHARS = 300                # one saved line or note, at most (an instruction to shorten it otherwise)
PER_SAVE = 20                   # lines (and notes) one save may add
CONTEXT_ROUNDS = 3              # the newest rounds with something kept that a new round reads back
CONTEXT_ITEMS = 6               # of each, its newest lines and notes
CONTEXT_CHARS = 1500            # everything a brief carries back, at most
CONTEXT_SCAN = 30               # the newest round files looked in for it (a round kept with nothing added is passed)
LIST_LIMIT = 50                 # past rounds one listing may give
# A round file's shape: `round` is there and every key that is there holds this type, else the file "isn't a round" and is left alone (a save
# never writes over it, a listing and a read-back pass it over).
_SHAPE = (("round", dict), ("words", list), ("lines", list), ("notes", list))
_ID = re.compile(r"\d{8}-\d{6}-[0-9a-f]{8}\Z")


def keeps(settings):
    """Whether rounds are kept: settings.json's `practice_keep_rounds`, on unless it is set to false."""
    return (settings or {}).get(SETTING, True) is not False


def folder(language):
    from app.path_utils import get_user_files_path
    return os.path.join(get_user_files_path(language), FOLDER)


def new_id(now=None):
    """A round's id: when it started, and eight random hex digits (rounds started in one second never share one: two
    that did would be saved into one file)."""
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)


def _path(language, round_id):
    if not isinstance(round_id, str) or not _ID.match(round_id):
        raise ValueError(f"No saved round {round_id!r}: pass a round_id from surasura_rounds or surasura_practice_start.")
    return os.path.join(folder(language), round_id + ".json")


def _read(path, language):
    """A round file -> its dict; None when there is none. ValueError when it is there but unreadable (it is left alone)."""
    from app.path_utils import read_text
    if not os.path.isfile(path):
        return None
    try:
        data = json.loads(read_text(path, language, errors="strict"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"The saved round {os.path.basename(path)} can't be read, so it was left as it is ({e}).")
    if (not isinstance(data, dict) or not isinstance(data.get("round"), dict)
            or any(key in data and not isinstance(data[key], kind) for key, kind in _SHAPE)):
        raise ValueError(f"The saved round {os.path.basename(path)} isn't a round, so it was left as it is.")
    return data


def words(data):
    """A saved round's words as a brief uses them, each {word, orth, reading, lines: [{line, from}]}; an entry that isn't
    one (a hand-edited file) is passed over."""
    out = []
    for w in data.get("words") or []:
        if isinstance(w, dict) and isinstance(w.get("word"), str) and w["word"]:
            lines = [{"line": x["line"], "from": x.get("from") if isinstance(x.get("from"), str) else ""}
                     for x in w.get("lines") or [] if isinstance(x, dict) and isinstance(x.get("line"), str)]
            out.append({"word": w["word"], "orth": w.get("orth") if isinstance(w.get("orth"), str) else w["word"],
                        "reading": w.get("reading") if isinstance(w.get("reading"), str) else "",
                        "lines": lines if isinstance(w.get("lines"), list) else []})
    return out


def _texts(values, what):
    """The lines or notes a save adds, each stripped; too many or too long -> ValueError saying what to do."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out = [str(v).strip() for v in values if v is not None and str(v).strip()]
    if len(out) > PER_SAVE:
        raise ValueError(f"At most {PER_SAVE} {what} in one save: save the rest in another call.")
    for text in out:
        if len(text) > TEXT_CHARS:
            raise ValueError(f"Each of the {what} is kept short, {TEXT_CHARS} characters at most: shorten "
                             f"\"{text[:30]}…\" and save again. Nothing was saved.")
    return out


def save(language, round_id, start=None, lines=None, notes=None):
    """Keep a round: written the first time with `start` (the brief's round: its choices and words), then each later
    save adds `lines` and `notes` and marks it done again. -> the round as saved. ValueError (said as what to do) for an
    unknown round, an unreadable file, too many or too long texts; `contract.CliError` (busy) when the lock is held."""
    from app.anki_sync import _atomic_write_json
    from app.cli import contract
    path = _path(language, round_id)
    lines, notes = _texts(lines, "lines"), _texts(notes, "notes")
    now = datetime.now().isoformat(timespec="seconds")
    with contract.take_lock("practice", "saving a practice round", wait=5.0):
        data = _read(path, language)
        if data is None:
            if not start:
                raise ValueError(f"No saved round {round_id}. Start a round with surasura_practice_start, or pick one "
                                 f"from surasura_rounds.")
            data = {"round_id": round_id, "language": language, "started": now,
                    "round": dict(start.get("round") or {}), "words": list(start.get("words") or []),
                    "lines": [], "notes": []}
        data["saved"] = now
        for key, new in (("lines", lines), ("notes", notes)):
            data[key] = data.get(key, []) + [{"text": text, "at": now} for text in new]
        _atomic_write_json(path, data)
    return data


def load(language, round_id):
    """A saved round -> its dict. ValueError when there is none or it can't be read."""
    data = _read(_path(language, round_id), language)
    if data is None:
        raise ValueError(f"No saved round {round_id}. surasura_rounds lists the past rounds.")
    return data


def _newest(language):
    """(mtime, path) of every round file, the latest saved first; [] when there is no folder."""
    try:
        entries = [(e.stat().st_mtime, e.path) for e in os.scandir(folder(language))
                   if e.is_file() and e.name.endswith(".json") and _ID.match(e.name[:-5])]
    except OSError:
        return []
    return sorted(entries, reverse=True)


def rounds(language, limit=10):
    """The past rounds, the latest saved first, at most `limit` (LIST_LIMIT): each its id, when, choices, words and how
    much is kept. A file that can't be read is passed over."""
    from app.cli import contract
    out = []
    for _mtime, path in _newest(language):
        if len(out) >= min(limit, LIST_LIMIT):
            break
        try:
            data = _read(path, language)
        except ValueError:
            contract.log.warning("practice: %s can't be read; left as it is", path)
            continue
        out.append({"round_id": os.path.basename(path)[:-5], "started": data.get("started"), "saved": data.get("saved"),
                    **_choices(data),
                    "round_words": [w["orth"] for w in words(data)],
                    "lines_kept": len(_texts_of(data, "lines")), "notes_kept": len(_texts_of(data, "notes"))})
    return out


def _choices(data):
    """A round's role, kind, source and number of words as listed and read back: a value a hand edit made long or odd
    is left out (it would otherwise flood the AI's context)."""
    return {k: v for k, v in data["round"].items()
            if k in ("role", "kind", "source", "words") and isinstance(v, (str, int)) and len(str(v)) <= 20}


def _texts_of(data, key):
    return [item["text"] for item in data.get(key) or [] if isinstance(item, dict) and isinstance(item.get("text"), str)]


def context(language, first=None):
    """What a new round reads back: the newest CONTEXT_ROUNDS rounds with lines or notes kept (`first`, the round done
    again, before them), each its newest CONTEXT_ITEMS notes and lines, newest first, CONTEXT_CHARS in all."""
    picked = []
    again = _path(language, first) if first else None
    others = [path for _m, path in _newest(language)[:CONTEXT_SCAN] if path != again]
    for path in ([again] if again else []) + others:
        if len([p for p in picked if p[0] != again]) >= CONTEXT_ROUNDS:
            break
        try:
            data = _read(path, language)
        except ValueError:
            continue
        if not data:
            continue
        notes, lines = _texts_of(data, "notes")[::-1], _texts_of(data, "lines")[::-1]
        if notes or lines:
            picked.append((path, data, notes[:CONTEXT_ITEMS], lines[:CONTEXT_ITEMS]))
    out, left = [], CONTEXT_CHARS
    for path, data, notes, lines in picked:
        kept = {"notes": [], "lines": []}
        for key, texts in (("notes", notes), ("lines", lines)):
            for text in texts:
                if len(text) > left:
                    continue                # too long for what is left: an older, shorter one may still fit
                kept[key].append(text)
                left -= len(text)
        if kept["notes"] or kept["lines"]:
            choices = _choices(data)
            out.append({"round_id": os.path.basename(path)[:-5], "role": choices.get("role"),
                        "kind": choices.get("kind"), **kept})
    return out
