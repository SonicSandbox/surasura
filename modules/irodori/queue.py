# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect's waiting list for AI audio (README § Running): a book's new cards, made with *Make AI audio (beta)*.

Connect queues a part's notes when it fills them (`add`), and makes their audio at the end of its run, after every
mining job (`run`): AI audio never holds a part back. The list is `<local data>/irodori-queue-<lang>.json` ({"entries":
[{"notes", "source", "added_at", "tries"}]}), written whole (a temp file renamed). An entry goes once its run wrote
(or found nothing left to write); a stopped one stays as it is; one that failed is tried again at a later run, up to
TRIES times, after the others.
"""
import json
import os
import threading
import time

TRIES = 3
_LOCK = threading.Lock()


def _path(language):
    """In the local data folder, never the runtime's: *Remove* never takes a queued book's cards with it."""
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), f"irodori-queue-{language}.json")


def _read(language):
    try:
        with open(_path(language), "r", encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        return []
    entries = got.get("entries") if isinstance(got, dict) else None
    return [e for e in entries or () if isinstance(e, dict) and isinstance(e.get("notes"), list)]


def _write(language, entries):
    path = _path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def add(language, note_ids, source=None):
    """Queue `note_ids` (one part's cards) -> how many notes were queued (0: none, or all queued already)."""
    ids = []
    for n in note_ids or ():
        try:
            ids.append(int(n))
        except (TypeError, ValueError):
            pass
    with _LOCK:
        entries = _read(language)
        have = {n for e in entries for n in e["notes"]}
        new = [n for n in dict.fromkeys(ids) if n not in have]
        if not new:
            return 0
        entries.append({"notes": new, "source": source, "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tries": 0})
        _write(language, entries)
    return len(new)


def waiting(language):
    return sum(len(e["notes"]) for e in _read(language))


def run(settings, language, should_stop=None, say=None, make_for_notes=None):
    """Make the queue's audio, entry by entry, until it is empty or `should_stop()` -> {"written", "runs", "left"}.
    The beta off, the voice not installed or the writer not there: nothing made, the queue kept."""
    from modules.irodori import make, on
    if not on(settings, language):
        return {"written": 0, "runs": [], "left": waiting(language)}
    make_for_notes = make_for_notes or make.make_for_notes
    written, runs, tried = 0, [], 0
    while True:
        if should_stop is not None and should_stop():
            break
        with _LOCK:
            entries = _read(language)
        if not entries or tried >= len(entries) * TRIES:
            break
        tried += 1
        entry = entries[0]
        report = make_for_notes(settings, language, entry["notes"], say=say, should_stop=should_stop, source="connect")
        written += len(report.get("written") or ())
        if report.get("run"):
            runs.append(report["run"])
        if report.get("stopped") or report.get("busy"):
            break           # the entry stays as it is: next time its notes filled now read as kept, the rest are made
        done = report.get("ok") or (not report.get("todo") and not report.get("problems"))
        with _LOCK:
            entries = _read(language)
            if entries and entries[0].get("notes") == entry["notes"]:
                if done or entries[0].get("tries", 0) + 1 >= TRIES:
                    if not done:                            # said in the log: the cards stay without audio
                        import logging
                        logging.getLogger("surasura-cli").warning(
                            "AI audio gave up on %d queued cards (%s): %s", len(entry["notes"]), language,
                            "; ".join(report.get("problems") or ()) or "no reason given")
                    entries.pop(0)
                else:
                    entries[0]["tries"] = entries[0].get("tries", 0) + 1
                    entries.append(entries.pop(0))          # tried again later, after the others
                _write(language, entries)
    return {"written": written, "runs": runs, "left": waiting(language)}
