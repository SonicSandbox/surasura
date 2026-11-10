# SPDX-License-Identifier: GPL-3.0-or-later
"""The user's answers to "Same word as one on your list?" — `User Files/<lang>/junban_pairs.json`.

Junban_Backlog_Spec §16. The matcher only ever SUGGESTS that a card's word (見とれる) is a list word
spelled another way (見惚れる); the user ticks the ones that are, and the answers are recorded here
when they press Reorder — ticked = "yes", unticked = "no":

```json
{"version": 1, "pairs": {"見とれる": {"target": "見惚れる", "answer": "yes", "via": "L6",
                                      "at": "2026-09-23T21:04:11"}}}
```

Keyed by the card's WORD, not its id: the next card mined for the same word needs no second answer.
A "yes" places that word as the list word from then on, in every run — the automatic one included;
a "no" means the pair is never proposed again. Only the panel records anything: an answer is
something the user saw and chose, which a background run never is.

The rules of `undo.py`, for the same reason — this is the user's own work, under `User Files/`: the
write is atomic (`.tmp` + `os.replace`), and a file that will not parse is moved aside
(`.corrupt-<ts>`), never overwritten.
"""

import json
import os
import time

FILENAME = "junban_pairs.json"
VERSION = 1


def pairs_path(language="ja"):
    """Where the answers live. Language-isolated like every other user file."""
    from app.path_utils import get_user_files_path
    return os.path.join(get_user_files_path(language), FILENAME)


def load(language="ja"):
    """`{card_word: {"target", "answer", ...}}` — `{}` when there are none. Never raises; a file
    that will not parse is quarantined and read as empty, and an entry this code cannot use is
    skipped rather than trusted."""
    path = pairs_path(language)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        _quarantine(path)
        return {}
    pairs = data.get("pairs") if isinstance(data, dict) else None
    if not isinstance(pairs, dict):
        _quarantine(path)
        return {}
    return {word: entry for word, entry in pairs.items()
            if isinstance(word, str) and word and isinstance(entry, dict)
            and isinstance(entry.get("target"), str) and entry["target"]
            and entry.get("answer") in ("yes", "no")}


def record(language, answers):
    """Merge `[(card_word, target, matched, via)]` into the file — a later answer for a word replaces
    its earlier one, every other word's is kept. Returns the path. Raises `OSError`: the caller is
    about to run on these answers, and must not run as if they were saved when they were not."""
    pairs = load(language)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    for word, target, matched, via in answers or ():
        if isinstance(word, str) and word and isinstance(target, str) and target:
            pairs[word] = {"target": target, "answer": "yes" if matched else "no",
                           "via": str(via or ""), "at": stamp}
    path = pairs_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump({"version": VERSION, "pairs": pairs}, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)             # atomic: an interrupted save cannot lose the answers
    return path


def _quarantine(path):
    """Move an unreadable file aside instead of overwriting it (as `undo._quarantine`)."""
    moved = f"{path}.corrupt-{time.strftime('%Y%m%d%H%M%S')}"
    try:
        os.replace(path, moved)
    except OSError:
        return None
    return moved
