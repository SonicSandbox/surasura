"""Anki's *New cards a day* for one deck — read, and changed only on the user's confirmed click (G1.2-5; K84).

Settings' *New cards a day* row (05 §5.7: "a setting Anki also holds shows Anki's value and offers to change it
there") shows the deck's own value, read on a worker with one `getDeckConfig`; *Change in Anki…* writes it only after a
confirmation naming the deck and its options group (`confirmation`). Level's older *New words a day* row goes: one
number, Anki's. `words_per_day` (the report's pace, "reach your target in N days") is that row's number while Anki
can't be read (`row_number`) and follows a confirmed change (`words_per_day_after`, saved by the caller through the
settings service — nothing here writes settings.json, and a read never does).

**The deck** is Junban's (`deck_for`): `junban_deck` while `junban_scope` is "deck" — the deck E1.1 D6 reads
*New cards/day* from for "the next day's cards" (`app/connect/anki_session.per_day`). With scope "all" there is no
one deck, and the row says so.

**The write** (`write_new_per_day`) holds the Anki-write lock (E1.4: `anki_connect.take_writer`, on the worker that
writes, never a GUI thread) from its first read to its read-back: it reads the options group again, refuses when
*New cards a day* is no longer what the user saw (`expect`), changes `new.perDay` alone — every other key of the
group goes back as Anki sent it — through `anki_connect.save_deck_config` (the one door for `saveDeckConfig`), then
reads it back, the whole group compared (`_moved`): an option Anki's save dropped or changed is named, never reported
as done. A deck's own *This deck* / *Today only* limit wins over the group's number and can't be read: the
confirmation and the success line say it still applies (`OWN_LIMIT`). A shared options group changes for every deck
using it; AnkiConnect's `getDeckConfig` doesn't say how many do, so the confirmation says it conditionally
(`shared_with` is None).

Qt-free and Tk-free; never raises past a plain-words answer.
"""

import collections
import copy

from app import anki_connect

# Anki's own bounds for *New cards/day* (its deck options take 0–9999).
MAX_PER_DAY = 9999

# The lock holder's verb, as another writer's status line names it ("Waiting for New cards a day to finish…").
VERB = "New cards a day"

# How long one read or write waits for Anki (anki_session.per_day's figure).
TIMEOUT = 10

# Anki's own per-deck limit (its deck options' "This deck" / "Today only", Anki 2.1.55+) wins over the options group's
# number, and AnkiConnect can't read it: the question and the answer both say so.
OWN_LIMIT = ("If the deck has its own “This deck” or “Today only” limit in Anki's options, that limit still "
             "applies.")

# What a save changes by itself in the options group it reads back (Anki's stamps), beside the write's own key.
_SAVE_STAMPS = ("mod", "usn", "new.perDay")
_MISSING = object()

# A read: Anki's value, the deck, its options group's name, and how many decks share that group (None: not told).
Reading = collections.namedtuple("Reading", "value deck config_name shared_with")

# A write's answer: did Anki take it, the plain words, Anki's value now (None when unknown), the lock was held.
Outcome = collections.namedtuple("Outcome", "ok message value busy")


def deck_for(settings):
    """The deck the row means: Junban's deck (`junban_deck`) while its scope is one deck, else ""."""
    settings = settings or {}
    if str(settings.get("junban_scope") or "deck").strip().lower() != "deck":
        return ""
    return str(settings.get("junban_deck") or "").strip()


def valid(value):
    """Is `value` a *New cards a day* Anki takes: a whole number 0–9999 (never a bool)?"""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_PER_DAY


def _per_day(config):
    """`new.perDay` of an options group, or None when it has none."""
    new = config.get("new") if isinstance(config, dict) else None
    value = new.get("perDay") if isinstance(new, dict) else None
    return value if valid(value) else None


def _why(error, deck):
    """An AnkiError in plain words."""
    if error.kind == "offline":
        return "Anki isn't open, so its New cards a day can't be read."
    if error.kind == "refused":
        return "Anki's address isn't on this computer (127.0.0.1), so Surasura doesn't ask it."
    return f"Anki couldn't answer for the deck “{deck}”: {error}"


def _read(url, deck):
    """One `getDeckConfig` -> (the options group, None) or (None, why not)."""
    try:
        config = anki_connect.invoke("getDeckConfig", url, timeout=TIMEOUT, deck=deck)
    except anki_connect.AnkiError as e:
        return None, _why(e, deck)
    if config is False:                         # AnkiConnect's answer for a deck it doesn't have
        return None, f"Anki has no deck named “{deck}”."
    if _per_day(config) is None:
        return None, f"Anki's options for “{deck}” have no New cards a day."
    return config, None


def read_new_per_day(settings, deck):
    """Anki's *New cards a day* for `deck` -> `Reading(value, deck, config_name, shared_with)`, or a plain reason it
    can't be read (a str): no deck, Anki closed, no such deck, an address that isn't loopback. One `getDeckConfig`;
    run it on a worker."""
    deck = str(deck or "").strip()
    if not deck:
        return "Choose Junban's deck first: New cards a day is that deck's option in Anki."
    config, problem = _read(anki_connect.address(settings), deck)
    if problem:
        return problem
    return Reading(_per_day(config), deck, str(config.get("name") or ""), None)


def confirmation(reading, value):
    """The question *Change in Anki…* asks before writing: the deck, the change, and the options group it lives in."""
    lines = [f"Change New cards a day for the deck “{reading.deck}” in Anki from {reading.value} to {value}?"]
    group = reading.config_name or "its options group"
    shared = reading.shared_with
    if shared is None:
        lines.append(f"It is set in the options group “{group}”: every deck using that group changes too.")
    elif shared > 1:
        lines.append(f"{shared} decks use the options group “{group}”: all of them change.")
    lines.append(OWN_LIMIT)
    return "\n".join(lines)


def write_new_per_day(settings, deck, value, expect, wait=0.0, cancel=None, on_wait=None):
    """Set `deck`'s *New cards a day* to `value` in Anki — only after the user confirmed it (`confirmation`) — when
    Anki still holds `expect` (the value the user saw) -> `Outcome`. Run on a worker: the Anki-write lock is taken
    here (`wait` / `cancel` / `on_wait` as E1.4's callers pass them: the page passes `wait=None` and an Event set
    when it closes; `on_wait(holder)` only posts `anki_connect.waiting_line(holder)` to its queue), held from the
    read to the read-back. Only `new.perDay` changes. Never raises."""
    deck = str(deck or "").strip()
    if not deck:
        return Outcome(False, "Choose Junban's deck first. Nothing was changed in Anki.", None, False)
    if not valid(value):
        return Outcome(False, f"New cards a day is a whole number from 0 to {MAX_PER_DAY}. Nothing was changed.",
                       None, False)
    url = anki_connect.address(settings)
    try:
        held, problem = anki_connect.take_writer(VERB, url, wait, cancel, on_wait)
    except Exception as e:                      # a nested take, a lock folder that can't be opened
        return Outcome(False, f"Nothing was changed in Anki: {e}", None, True)
    if held is None:
        if cancel is not None and cancel.is_set():
            problem = "Stopped before writing anything."
        return Outcome(False, problem, None, True)
    with held:
        return _write(url, deck, value, expect)


def _write(url, deck, value, expect):
    """The write, holding the lock: read again, refuse a moved value, change `new.perDay` alone, read it back."""
    config, problem = _read(url, deck)
    if problem:
        return Outcome(False, f"{problem} Nothing was changed.", None, False)
    current = _per_day(config)
    if current != expect:
        return Outcome(False, f"New cards a day for “{deck}” is now {current} in Anki — it changed since it was "
                              "read. Nothing was changed; look at it again.", current, False)
    if current == value:
        return Outcome(True, f"New cards a day for “{deck}” is already {value} in Anki. {OWN_LIMIT}", value, False)
    changed = copy.deepcopy(config)
    changed["new"]["perDay"] = value
    try:
        saved = anki_connect.save_deck_config(url, changed, timeout=TIMEOUT)
    except anki_connect.AnkiError as e:
        if e.kind == "offline":
            return Outcome(False, "Anki stopped answering while it was being changed: look at the deck's options in "
                                  "Anki to see whether it took.", None, False)
        return Outcome(False, f"Anki refused the change: {e}", current, False)
    if not saved:
        return Outcome(False, f"Anki didn't save the options for “{deck}”. Nothing was changed.", current, False)
    back, problem = _read(url, deck)
    if problem:
        return Outcome(False, f"Anki took the change, but reading it back failed: {problem}", None, False)
    now = _per_day(back)
    if now != value:
        return Outcome(False, f"Anki was asked for {value} New cards a day for “{deck}”, but now says {now}.",
                       now, False)
    moved = _moved(changed, back)
    if moved:
        group = str(config.get("name") or "") or deck
        return Outcome(False, f"Anki took {value} New cards a day for “{deck}”, but other options of “{group}” came "
                              f"back different: {', '.join(moved)}. Check the options group “{group}” in Anki.",
                       now, False)
    return Outcome(True, f"New cards a day for “{deck}” is now {value} in Anki. {OWN_LIMIT}", value, False)


def _moved(sent, back, path=""):
    """The options of the group Anki read back different from what was sent -> their names, dotted ("new.delays"),
    in the group's order: a key dropped, added or changed. A save's own stamps (`mod`, `usn`), the write's
    `new.perDay` and `id` read back as a str (AnkiConnect's) are not moves."""
    out = []
    for key in list(sent) + [k for k in back if k not in sent]:
        name = f"{path}.{key}" if path else str(key)
        if name in _SAVE_STAMPS:
            continue
        a, b = sent.get(key, _MISSING), back.get(key, _MISSING)
        if name == "id" and a is not _MISSING and b is not _MISSING and str(a) == str(b):
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            out += _moved(a, b, name)
        elif a is _MISSING or b is _MISSING or a != b:
            out.append(name)
    return out


def _words_per_day(settings):
    value = (settings or {}).get("words_per_day", 5)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 5


def row_number(settings, reading):
    """The number the row shows: Anki's when it was read (a `Reading`), else `words_per_day` — the report's pace,
    which the row edits while Anki can't be read."""
    return reading.value if isinstance(reading, Reading) else _words_per_day(settings)


def words_per_day_after(settings, outcome):
    """What the caller saves through the settings service after a write: `{"words_per_day": n}` when Anki now holds a
    new `n` (a confirmed change, `n` ≥ 1 — the report reads 0 as its default 5, so 0 leaves the pace as it is), else
    `{}`."""
    if not isinstance(outcome, Outcome) or not outcome.ok or not valid(outcome.value) or outcome.value < 1:
        return {}
    return {} if outcome.value == (settings or {}).get("words_per_day") else {"words_per_day": outcome.value}
