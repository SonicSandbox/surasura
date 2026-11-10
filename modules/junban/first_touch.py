# SPDX-License-Identifier: GPL-3.0-or-later
"""The first-touch backup, and "Put Anki back the way it was before Surasura" (FT, Sonic 2026-10-13; the spec's
amendments K1–K14 win over D1–D9; the build review's fixes C1–C30, 2026-10-14).

Before Surasura's first-ever write to a deck it keeps every new card's position, and as it goes, what Junban suspends,
flags, tags and fills — in `User Files/<lang>/anki_first_touch/`, never overwritten, never purged:

* **The order files** (D2): `order-<deck key>-<profile key>.json`, one per (scope, Anki profile) — an "all decks" run's
  `order-all-decks-<its decks' key>-<profile key>.json` — created once and never replaced: written to a temporary file,
  fsync'd, then moved to its name by a rename that fails when the name exists (`os.rename` on Windows; elsewhere
  `os.link`, else an `O_EXCL` create, K13): two writers racing keep the first. `{schema, taken_at, taken_ms, profile,
  mode, scope, earlier, cards: [[card id, due], …]}`: every unsuspended new card in scope (`reposition._run`'s
  `in_scope`), taken right before the run's snapshot. A deck is covered, for one profile (K1), by its own file or by an
  "all decks" file whose decks hold it (C2); a run looks only at the files named for it (C7). A later version's file
  covers and is never put back or moved (C6); one that parses broken is set aside (`.unreadable-<stamp>`, never
  deleted) by a writer holding the lock, never by `plan` (C6) — a rename that fails refuses the run (C25); one that
  can't be read just now refuses the run (K10).
* **`started.json`** (C13): whether Junban or Backfill had written anything before Surasura's first-ever touch, decided
  once then: the first order file's `earlier` is that answer, every later one's False.
* **The journal** (D4): `changes.jsonl`, append-only, one fsync'd line per write, each carrying the profile and the
  decks (K1): before a run's writes reach Anki, what it means to suspend / unsuspend, flag (old → new), tag (only notes
  that lacked the tag, as Junban records them) and fill (before / after); after `_apply_later`, what landed (`landed`,
  K3); after a Restore, what it undid. Connect's batch tags (`surasura::connect::<job>`) are never journalled (D6), and
  Connect's own writes aren't at all (K5): its ledger owns them.

`plan` reads (no lock, no writes, nothing moved); `put_back` writes, holding `anki-writer` (D5, K11, K14): the deck's
automatic re-order stands aside first (FT-1; a settings file that can't be saved refuses, C12), then — asking before
each request whether you started reviewing (K14) — Junban's suspends off (only one surely Junban's: still new, still
suspended, still carrying the tag it went with, never unsuspended by Surasura since, K3), the new cards' order back
(the earliest file holding a card wins, by card id — unless a file covering its deck was taken before the card was
made: then it was added since, C5; a card you added since goes after, in the order added; a card Surasura made after
yours, K5; a studied card, one you suspended, one moved in from elsewhere is left alone), Junban's flags and tags off,
and — offered — the fields back where you haven't edited them (the journal's, chained to Junban's and Backfill's own
snapshots from before the record, K7 / C19). Each request's cards and notes are read again just before it goes
(C3). Junban's own changes come off a card Surasura made too (C18); the card itself, Connect's shelf and tags stay
(K5). Older changes from before the record, in the record's decks, are counted and done only when asked (K4, C10).
No Tk, no Qt.

Paths resolve through `app.path_utils`, imported inside the functions (the tests patch it; `undo.py` says why).
"""

import hashlib
import json
import os
import time

SCHEMA = 1
FOLDER = "anki_first_touch"
JOURNAL = "changes.jsonl"
STARTED = "started.json"
ORDER_PREFIX = "order-"
ALL_KEY = "all-decks"
ALL_DECKS = "all decks"                 # Backfill's deck when it fills every deck ("All decks"), as it journals it
CONNECT_TAG = "surasura::connect::"     # D6 / K5: Connect's batch tags — a note carrying one is a card Surasura made
LANGUAGES = ("ja", "zh")
SETTINGS_WAIT_S = 5.0                   # C12: how long the put-back waits for the settings file before refusing

NOTHING = "Surasura hasn't changed this language's Anki cards."
ANKI_CLOSED = "Open Anki first: nothing was changed."
REVIEWING_STOP = "You started reviewing in Anki, so the rest waits. Press it again when you're done."

_COVERED = set()                # (folder, mode, scope, profile): an order file covers it — never forgotten
_STARTED = {}                   # folder -> started.json's answer, once read or made (C13)


def folder(language):
    """`User Files/<lang>/anki_first_touch`."""
    from app.path_utils import get_user_files_path
    return os.path.join(get_user_files_path(language), FOLDER)


def _key(text):
    """A file-name key: the name as far as a file name can hold it, and a hash that tells two names apart."""
    text = str(text or "")
    readable = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)[:40].strip("_") or "x"
    return f"{readable}-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"


def _mode(mode):
    return "all" if mode == "all" else "deck"


def _scope(scope):
    from modules.junban import undo
    return undo.normalize_scope(scope)


def order_path(language, scope, mode, profile):
    """Where the order file for this (scope, profile) lives — an "all decks" run's named for its decks too (C2: a run
    over more decks than an earlier one keeps a file of its own)."""
    deck = _key("|".join(_scope(scope)))
    if _mode(mode) == "all":
        deck = f"{ALL_KEY}-{deck}"
    return os.path.join(folder(language), f"{ORDER_PREFIX}{deck}-{_key(profile_name(profile))}.json")


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _int(value):
    """A journal key as a whole number, or None (C27: a line hand-edited or cut short never stops the put-back)."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ids(values):
    out = set()
    for value in values or () if isinstance(values, (list, tuple, set)) else ():
        value = _int(value)
        if value is not None:
            out.add(value)
    return sorted(out)


def _within(deck, name):
    """Is `deck` the deck `name` or one under it (Anki's `deck:` search reads subdecks)? A blank name holds nothing:
    it never becomes the "::" prefix (C28)."""
    deck, name = str(deck or "").strip(), str(name or "").strip()
    return bool(deck) and bool(name) and (deck == name or deck.startswith(name + "::"))


def _overlap(one, other):
    """Do two decks reach the same cards — one holds the other, or either is All decks ("" or Backfill's "All
    decks")?"""
    one, other = str(one or "").strip(), str(other or "").strip()
    if not one or not other or ALL_DECKS in (one.casefold(), other.casefold()):
        return True
    return _within(one, other) or _within(other, one)


# --- the profile ------------------------------------------------------------------------------------ #
def profile_name(value):
    """C22: the one form of Anki's answer to `getActiveProfile` — its name, or "" when it names none."""
    return value if isinstance(value, str) else ""


def _ask_profile(url):
    """The open profile, by one `getActiveProfile`. Raises `AnkiError`."""
    from app import anki_connect
    return profile_name(anki_connect.invoke("getActiveProfile", url, timeout=5))


def open_profile(url):
    """The open Anki profile, by one `getActiveProfile` (K1: one per writing run that has no card map to read it from);
    "" when Anki names none. Raises `OSError` when Anki doesn't answer: nothing is journalled or written then."""
    from app import anki_connect
    try:
        return _ask_profile(url)
    except anki_connect.AnkiError as e:
        raise OSError(f"couldn't read which Anki profile is open: {e}") from None


def open_profile_or_none(url):
    """`open_profile`, for a way back's journal line: None when Anki doesn't say (the line is then not written)."""
    try:
        return open_profile(url)
    except OSError:
        return None


# --- the order files -------------------------------------------------------------------------------- #
def _readable(data):
    """An order file this version can put back, or None."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("cards"), list):
        return None
    if not _whole(data.get("taken_ms")) or not isinstance(data.get("scope"), list):
        return None
    cards = []
    for pair in data["cards"]:
        if not isinstance(pair, list) or len(pair) != 2 or not all(_whole(value) for value in pair):
            return None
        cards.append((pair[0], pair[1]))
    return dict(data, cards=cards, scope=_scope(data["scope"]), mode=_mode(data.get("mode")),
                profile=profile_name(data.get("profile")), earlier=data.get("earlier") is True)


def _read_order(path):
    """One order file -> `_readable`'s dict; `{"newer": True, profile, mode, scope}` for a later version's (C6: it
    covers, and is never put back or moved); None when it doesn't parse. Raises `OSError` when it can't be read just
    now (another program holds it)."""
    with open(path, "rb") as handle:
        body = handle.read()
    try:
        data = json.loads(body.decode("utf-8"))
    except ValueError:
        return None
    if isinstance(data, dict) and _whole(data.get("schema")) and data["schema"] > SCHEMA:
        scope = data.get("scope")
        return {"newer": True, "profile": profile_name(data.get("profile")), "mode": _mode(data.get("mode")),
                "scope": _scope(scope) if isinstance(scope, list) else None}
    return _readable(data)


def _set_aside(path):
    """An order file that parses broken is moved aside, never deleted: a later version may read it (K10). Only by a
    writer holding the lock (C6). Raises `OSError` when it can't be moved (C25): the run then writes nothing — never
    a run without its order kept."""
    os.rename(path, f"{path}.unreadable-{time.strftime('%Y%m%d%H%M%S')}")


def set_aside(language):
    """The order files set aside as unreadable, by name (`plan` names them, K10)."""
    try:
        return sorted(name for name in os.listdir(folder(language)) if ".unreadable-" in name)
    except OSError:
        return []


def orders(language, set_aside=False):
    """`(files, busy)`: every order file of this version that reads, earliest first, each with its `path`; `busy`: the
    names that couldn't be read just now (another program holds them) — neither read nor set aside. A later version's
    file is neither listed nor moved (C6); one that doesn't parse is left out, and moved aside only with `set_aside`
    (a caller holding the writer lock: `put_back`; never `plan`, C6). Raises `OSError` when that move fails (C25)."""
    try:
        names = sorted(name for name in os.listdir(folder(language))
                       if name.startswith(ORDER_PREFIX) and name.endswith(".json"))
    except OSError:
        return [], []
    found, busy = [], []
    for name in names:
        path = os.path.join(folder(language), name)
        try:
            data = _read_order(path)
        except OSError:
            busy.append(name)
            continue
        if data is None:
            if set_aside:
                _set_aside(path)
            continue
        if data.get("newer"):
            continue
        found.append(dict(data, path=path))
    found.sort(key=lambda data: (data["taken_ms"], data["path"]))
    return found, busy


def covered(language, scope, mode, profile, set_aside=False):
    """Is this scope's order kept already, for this profile (K1)? A deck by its own file, or by an "all decks" file
    whose decks hold it; an "all decks" run by "all decks" files holding every one of its decks — else it keeps a new
    file (C2). Only the files named for it are read (C7: the deck's own, the profile's "all decks" ones), never every
    file. A later version's counts as covering (C6); one that doesn't parse as absent — moved aside with `set_aside`
    (`keep_order`, holding the writer lock). Raises `OSError` when one can't be read just now (K10) or moved (C25)."""
    scope, mode, profile = _scope(scope), _mode(mode), profile_name(profile)
    try:
        names = set(os.listdir(folder(language)))
    except OSError:
        return False
    own = os.path.basename(order_path(language, scope, "deck", profile))
    ending = f"-{_key(profile)}.json"
    candidates = ([own] if mode == "deck" and own in names else []) + sorted(
        name for name in names if name.startswith(f"{ORDER_PREFIX}{ALL_KEY}-") and name.endswith(ending))
    held = set()
    for name in candidates:
        path = os.path.join(folder(language), name)
        try:
            data = _read_order(path)
        except OSError:
            raise OSError(f"Surasura's saved order {name} can't be read just now (another program holds it)") from None
        if data is None:
            if set_aside:
                _set_aside(path)
            continue
        if data["profile"] != profile:
            continue
        if data["mode"] == "deck":
            if name == own and data["scope"] in (None, scope):
                return True
            continue
        if data["scope"] is None:               # a later version's "all decks" file whose decks this one can't read
            return True
        held |= {deck for deck in scope if any(_within(deck, kept) for kept in data["scope"])}
    return bool(scope) and held >= set(scope)


def _history():
    """K9: had Junban or Backfill written anything — any of their files, in either language?"""
    from app.path_utils import get_user_files_path
    from modules.junban import undo
    for lang in LANGUAGES:
        names = list(undo.FILENAMES.values()) + [undo.LADDER_FILENAME]
        if any(os.path.isfile(os.path.join(get_user_files_path(lang), name)) for name in names):
            return True
        try:
            if any(name.endswith(".json") for name in os.listdir(undo.runs_folder(lang))):
                return True
        except OSError:
            pass
    return False


def _read_started(language):
    try:
        with open(os.path.join(folder(language), STARTED), "rb") as handle:
            data = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("earlier") is True if isinstance(data, dict) else None


def started(language):
    """C13 (D3 / K9): had Junban or Backfill written anything before Surasura's first-ever touch — any of their files,
    in either language? Decided once, at that touch (the first order file or journal line), in a create-once
    `started.json` beside the record — the other language's answer when it has one — and never again: what Surasura
    writes after it never counts. Raises `OSError` when it can't be kept (the run then writes nothing)."""
    here = folder(language)
    if here in _STARTED:
        return _STARTED[here]
    answer = _read_started(language)
    if answer is None:
        others = [_read_started(lang) for lang in LANGUAGES if lang != language]
        answer = next((other for other in others if other is not None), None)
        if answer is None:
            answer = _history()
        _create_once(os.path.join(here, STARTED), {"schema": SCHEMA, "earlier": answer,
                                                   "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        kept = _read_started(language)          # two writers racing: the first one's answer
        answer = answer if kept is None else kept
    _STARTED[here] = answer
    return answer


def _create_once(path, payload):
    """Write `payload` at `path` unless a file is there -> True when this call made it. Temp + fsync, then a rename
    that fails if the name exists (K13: `os.rename` on Windows; `os.link`, else an `O_EXCL` create): a file there is
    never replaced, and two writers racing keep the first."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    temporary = f"{path}.{os.getpid()}-{os.urandom(6).hex()}.tmp"     # one of its own per writer
    try:
        with open(temporary, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "nt":
            os.rename(temporary, path)          # Windows: fails when `path` exists
            return True
        try:
            os.link(temporary, path)            # fails when `path` exists
            return True
        except FileExistsError:
            raise
        except OSError:                         # no hard links here: an exclusive create instead
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            return True
    except FileExistsError:
        return False
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


def keep_order(language, scope, mode, pairs, profile=None, url=None):
    """D2: before a run's first write, keep the scope's new cards' order once, for the open profile -> the file's path,
    or None when an order file covers it already (an in-memory answer after the first: no disk). `pairs`:
    `[(card id, due)]`, every unsuspended new card in scope. `profile`: the open one (the caller read it); None asks
    Anki (`url`). `earlier` (C13): `started`'s answer for the language's first order file, False for every later one,
    True for one replacing a file set aside (K10). Raises `OSError` when the file can't be written, a saved one can't
    be read or set aside: the run then writes nothing, as without its snapshot."""
    scope, mode = _scope(scope), _mode(mode)
    profile = open_profile(url) if profile is None else profile_name(profile)
    asked = (folder(language), mode, tuple(scope), profile)
    if asked in _COVERED:
        return None
    if covered(language, scope, mode, profile, set_aside=True):
        _COVERED.add(asked)
        return None
    path = order_path(language, scope, mode, profile)
    first_touch = started(language)
    try:
        names = os.listdir(folder(language))
    except OSError:
        names = []
    if any(name.startswith(os.path.basename(path) + ".unreadable-") for name in names):
        earlier = True                          # K10: the order before the file set aside is no longer known
    else:
        earlier = first_touch and not any(name.startswith(ORDER_PREFIX) for name in names)
    now = time.time()
    payload = {"schema": SCHEMA, "taken_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
               "taken_ms": int(now * 1000), "profile": profile, "mode": mode, "scope": scope, "earlier": earlier,
               "cards": [[int(card_id), int(due)] for card_id, due in (pairs.items() if isinstance(pairs, dict)
                                                                        else pairs)]}
    made = _create_once(path, payload)
    _COVERED.add(asked)
    return path if made else None


# --- the journal ------------------------------------------------------------------------------------ #
def _ours(tag):
    tag = str(tag or "").strip()
    return bool(tag) and not tag.casefold().startswith(CONNECT_TAG)


def _clean(items):
    """The journal's items, as stored: `suspended` / `unsuspended` card ids; `flags` {card: [old, new]}; `tags` /
    `tags_off` {tag: [note ids]} (never Connect's batch tags, D6); `fields` {note: {field: {before, after}}}. Anything
    else (`landed`, `with_tag`, a put-back's counts) is kept as given. Empty items are left out."""
    out = {}
    for key, value in items.items():
        if key in ("suspended", "unsuspended"):
            value = _ids(value)
        elif key == "flags":
            value = {str(int(card)): [int(pair[0]), int(pair[1])] for card, pair in (value or {}).items()
                     if _int(card) is not None and isinstance(pair, (list, tuple)) and len(pair) == 2
                     and all(_whole(v) for v in pair)}
        elif key in ("tags", "tags_off"):
            value = {str(tag).strip(): _ids(notes) for tag, notes in (value or {}).items()
                     if _ours(tag) and _ids(notes)}
        elif key == "fields":
            value = {str(int(note)): {str(field): {"before": change["before"], "after": change["after"]}
                                      for field, change in (changes or {}).items()
                                      if isinstance(change, dict) and isinstance(change.get("before"), str)
                                      and isinstance(change.get("after"), str)}
                     for note, changes in (value or {}).items() if _int(note) is not None and isinstance(changes, dict)}
            value = {note: changes for note, changes in value.items() if changes}
        if value:
            out[key] = value
    return out


_WHAT = ("suspended", "unsuspended", "flags", "tags", "tags_off", "fields")


def note(language, kind, profile=None, deck=None, **items):
    """D4: one journal line — `kind` (who wrote: "reorder", "backfill", "restore", "put_back"), the open `profile`
    and the `deck`s (K1), and what it changes (`_clean`'s items) — appended in one write and fsync'd (K12), by a
    caller holding `anki-writer`. Nothing to record writes nothing, except a put-back's line. The first line ever
    keeps `started.json` first (C13). Raises `OSError` when it can't be written, `ValueError` without a profile (a
    line no put-back could place)."""
    if profile is None:
        raise ValueError("a first-touch journal line needs the open Anki profile")
    kept = _clean(items)
    if not any(key in kept for key in _WHAT) and kind != "put_back":
        return False
    started(language)
    now = time.time()
    line = dict({"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "ms": int(now * 1000),
                 "kind": str(kind), "profile": str(profile), "deck": _scope(deck)}, **kept)
    path = os.path.join(folder(language), JOURNAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "ab") as handle:
        lead = b""
        if handle.tell():                   # a line cut short by a crash never swallows this one
            with open(path, "rb") as tail:
                tail.seek(-1, os.SEEK_END)
                lead = b"" if tail.read(1) == b"\n" else b"\n"
        handle.write(lead + json.dumps(line, ensure_ascii=False).encode("utf-8") + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def noted(language, kind, profile=None, deck=None, **items):
    """`note`, after a write landed (a Restore): never a reason to stop — False when it couldn't be written, or no
    profile is known."""
    if profile is None:
        return False
    try:
        return note(language, kind, profile, deck, **items)
    except (OSError, ValueError):
        return False


def journal(language):
    """Every journal line that reads, in the order written (a line cut short by a crash is skipped)."""
    path = os.path.join(folder(language), JOURNAL)
    lines = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                try:
                    line = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(line, dict):
                    lines.append(line)
    except OSError:
        pass
    return lines


def parked(language):
    """P4.2.2 (P2.2 adversary #9; the intent keeper's S5 on P4.1): the cards Junban parked, by its lasting record — this
    journal, never purged (a run snapshot keeps only the last 20 runs) — the one set MR-R3's returning word and *Study
    its cards first* read (`connect.returning`) -> {"cards": every card whose suspend landed (K3) with no Surasura
    unsuspend since; "named": every card a line names; "notes": the notes carrying a tag Junban put on by its account;
    "since": the first line's time in ms, or None (no journal yet)}. Every profile's lines: a card id is one
    collection's. Reads only; never raises. A journal that is there but can't be read is the safe side (adversary
    AD-2): no card is Junban's, so none comes back by the record — never the tag rule, which would bring back a card
    you suspended."""
    path = os.path.join(folder(language), JOURNAL)
    try:
        if os.path.exists(path):
            open(path, "rb").close()
    except OSError:
        return {"cards": set(), "named": set(), "notes": set(), "since": 0}
    lines = journal(language)
    state = _state(lines)
    times = [line.get("ms") for line in lines if _whole(line.get("ms"))]
    return {"cards": set(state["suspended"]), "named": set(state["touched"]),
            "notes": {note_id for _tag, note_id in state["tags"]}, "since": min(times) if times else None}


def has_anything(language):
    """Has Surasura kept anything for this language — an order file or a journal line? Local files only."""
    try:
        names = os.listdir(folder(language))
    except OSError:
        return False
    if any(name.startswith(ORDER_PREFIX) and name.endswith(".json") for name in names):
        return True
    try:
        return os.path.getsize(os.path.join(folder(language), JOURNAL)) > 0
    except OSError:
        return False


def undone_fields(snapshot, edits):
    """A Restore's field writes as journal items: `{note: {field: {before: what Surasura wrote, after: the value put
    back}}}`, from its snapshot and the `{note: {field: value}}` it wrote."""
    saved = (snapshot or {}).get("fields") or {}
    out = {}
    for note_id, values in (edits or {}).items():
        for field, value in (values or {}).items():
            change = (saved.get(str(note_id)) or {}).get(field)
            if isinstance(change, dict) and isinstance(change.get("after"), str):
                out.setdefault(str(note_id), {})[field] = {"before": change["after"], "after": value}
    return out


def restored(language, url, snapshot=None, deck=None, unsuspended=(), suspended=(), with_tag="", flags=(),
             tags_off=None, fields=None):
    """A Restore's journal line, once its writes landed — what it undid: the cards it unsuspended, the returning words'
    cards it set aside again (`suspended`, carrying `with_tag`), `flags` `[(card, the flag put back)]` (off Junban's
    purple), `tags_off` `{tag: [note ids]}`, `fields` `{note: {field: the value put back}}` (`snapshot` says what
    Surasura had written). The profile is asked only when there is something to note. Never a reason not to restore."""
    from modules.junban.unlisted import FLAG_PURPLE
    items = dict(unsuspended=unsuspended, suspended=suspended,
                 flags={card: [FLAG_PURPLE, flag] for card, flag in flags or ()}, tags_off=tags_off or {},
                 fields=undone_fields(snapshot, fields))
    if not any(key in _clean(items) for key in _WHAT):
        return False
    return noted(language, "restore", open_profile_or_none(url), deck, landed=True,
                 **(dict(items, with_tag=with_tag) if suspended else items))


def _entries(line, key):
    value = line.get(key)
    return value.items() if isinstance(value, dict) else ()


def _state(lines):
    """What Junban's journalled changes come to, line by line (one profile's lines):
    `suspended` {card: the tag it went with}: suspends that landed (K3) with no Surasura unsuspend since; `named`:
    every card a suspend line names (the intent too); `excluded`: the cards K4's older changes never count — a suspend
    that landed, or a Surasura unsuspend (C11); `touched`: every card a line names; `flags` {card: [the flag to put
    back, Surasura's last]}; `tags` {(tag, note)} still on by Surasura's account; `fields` {(note, field): [the text to
    put back, the text Surasura wrote last]}. A value you changed between two of Surasura's writes is yours: the chain
    starts again from it. A key that isn't a whole number is skipped (C27)."""
    suspended, named, excluded, flags, tags, fields = {}, set(), set(), {}, {}, {}
    for line in lines:
        if not isinstance(line, dict):
            continue
        for card in _ids(line.get("suspended")):
            named.add(card)
            if line.get("landed") is True:
                suspended[card] = str(line.get("with_tag") or "")
                excluded.add(card)
        for card in _ids(line.get("unsuspended")):
            excluded.add(card)
            suspended.pop(card, None)
        for card, pair in _entries(line, "flags"):
            card = _int(card)
            if card is None or not (isinstance(pair, list) and len(pair) == 2 and all(_whole(v) for v in pair)):
                continue
            if card not in flags or flags[card][1] != pair[0]:
                flags[card] = [pair[0], pair[1]]
            else:
                flags[card][1] = pair[1]
        for key, on in (("tags", True), ("tags_off", False)):
            for tag, notes in _entries(line, key):
                if _ours(tag):
                    for note_id in _ids(notes):
                        tags[(str(tag).strip(), note_id)] = on
        for note_id, changes in _entries(line, "fields"):
            note_id = _int(note_id)
            for field, change in changes.items() if note_id is not None and isinstance(changes, dict) else ():
                if not (isinstance(change, dict) and isinstance(change.get("before"), str)
                        and isinstance(change.get("after"), str)):
                    continue
                key = (note_id, str(field))
                if key not in fields or fields[key][1] != change["before"]:
                    fields[key] = [change["before"], change["after"]]
                else:
                    fields[key][1] = change["after"]
    return {"suspended": suspended, "named": named, "excluded": excluded,
            "touched": named | excluded | set(flags), "flags": flags,
            "tags": {key for key, on in tags.items() if on}, "fields": fields}


# --- the put-back ----------------------------------------------------------------------------------- #
def _in_scope(data, deck):
    """Is `deck` one an order file was taken for (its subdecks too, as Anki's `deck:` search reads them)?"""
    return any(_within(deck, name) for name in data["scope"])


def _query(text):
    from modules.junban import ankiconnect
    return ankiconnect.escape_query(text)


def _made_query(deck):
    return f'deck:"{_query(deck)}" is:new "tag:{CONNECT_TAG}*"'


def _older_tags(settings):
    """K4: the tags Junban puts on, under Surasura and under the tag you named — the plain tag, the markers, `later`."""
    from modules.junban import touchup, unlisted
    out = []
    for parent in ("Surasura", touchup.options(settings).get("tag") or ""):
        if parent:
            out += [parent] + [touchup.marker_tag(parent, marker) for marker in touchup.MARKER_TAG_LEAF] + [
                unlisted.later_tag(parent)]
    return list(dict.fromkeys(out))


def _found(replies, action="findCards"):
    from modules.junban import ankiconnect
    out = []
    for reply in replies or []:
        if not isinstance(reply, dict) or reply.get("error") is not None or not isinstance(reply.get("result"), list):
            raise ankiconnect.AnkiError(f"Anki refused '{action}': {(reply or {}).get('error')}", kind="action")
        out.append(set(_ids(reply["result"])))
    return out


def _carries(note, tag):
    return str(tag or "").casefold() in {str(name).casefold() for name in (note or {}).get("tags") or []}


def _made(note):
    return any(str(name).casefold().startswith(CONNECT_TAG) for name in (note or {}).get("tags") or [])


def _snapshot_fields(language):
    """K7 / C19: the fields Junban's own snapshots carry from before the record — Backfill's
    (`junban_backfill_undo.json`) and the reorder's touch-ups (`junban_undo.json`): {(note, field): [the true
    original, Junban's last text]}, carried forward run to run."""
    from modules.junban import undo
    out = {}
    for kind in ("backfill", "reorder"):
        for note_id, changes in ((undo.load(language, kind=kind) or {}).get("fields") or {}).items():
            note_id = _int(note_id)
            for field, change in changes.items() if note_id is not None and isinstance(changes, dict) else ():
                if isinstance(change, dict) and isinstance(change.get("before"), str) \
                        and isinstance(change.get("after"), str):
                    out.setdefault((note_id, str(field)), [change["before"], change["after"]])
    return out


def _survey(url, language, profile, settings, older=True, set_aside=False):
    """Every read the put-back plans from (D5; raises `AnkiError`) -> a dict: the open profile's order files, the cards
    to unsuspend, the positions to write (`[(card, due)]` and the dues read), the flags, the tags and the fields to put
    back, the fields left as you edited them, Surasura's made cards, and — with `older` (C14) — the older changes in
    the record's decks (K4, C10). `set_aside`: a broken order file is moved aside (`put_back`, holding the lock)."""
    from modules.junban import ankiconnect, reposition
    files = [data for data in orders(language, set_aside)[0] if data["profile"] == profile]
    lines = [line for line in journal(language) if line.get("profile") == profile]
    state = _state(lines)
    decks = sorted({deck for data in files for deck in data["scope"]})
    older_tags = _older_tags(settings) if older and decks else []
    later_tags = [tag for tag in older_tags if tag.endswith("::later")]
    not_made = f'-"tag:{CONNECT_TAG}*"'
    within = [f'deck:"{_query(deck)}"' for deck in decks]
    actions = ([{"action": "findCards", "params": {"query": ankiconnect.new_card_query(deck)}} for deck in decks]
               + [{"action": "findCards", "params": {"query": _made_query(deck)}} for deck in decks]
               + [{"action": "findCards", "params": {"query": f'{deck} "tag:{_query(tag)}" is:new is:suspended '
                                                              f'{not_made}'}}
                  for tag in later_tags for deck in within])
    finds = _found(ankiconnect.multi(actions, url)) if actions else []
    found = set().union(*finds[:len(decks)]) if decks else set()
    made_found = set().union(*finds[len(decks):2 * len(decks)]) if decks else set()
    # C11: K4 leaves out only a suspend that landed or a card Surasura unsuspended — an intent whose `landed` line was
    # lost is still offered among the older changes.
    older_cards = set().union(*finds[2 * len(decks):]) - state["excluded"] if later_tags else set()
    older_notes = {}
    if older_tags:
        asked = [(tag, deck) for tag in older_tags for deck in within]
        replies = _found(ankiconnect.multi([{"action": "findNotes", "params": {
            "query": f'{deck} "tag:{_query(tag)}" {not_made}'}} for tag, deck in asked], url), "findNotes")
        for (tag, _deck), ids in zip(asked, replies):
            older_notes.setdefault(tag, set()).update(ids)

    kept, top = {}, 0
    for data in files:                      # earliest first: the earliest file holding a card wins (by card id, K14)
        for card, due in data["cards"]:
            kept.setdefault(card, due)
            top = max(top, due)
    wanted = (found | set(kept) | set(state["suspended"]) | state["named"] | set(state["flags"]) | older_cards
              | made_found)
    rows = {row.get("cardId"): row for row in ankiconnect.cards_info(url, sorted(wanted))
            if reposition._is_int(row.get("cardId"))}

    old_fields = _snapshot_fields(language)
    fields_wanted = dict(old_fields)
    for key, (before, after) in state["fields"].items():
        earlier = old_fields.get(key)
        # C19: the journal's chain goes on from a snapshot from before the record — its last text the journal's first
        # `before`, or the journal's last `after` (the snapshot carried this chain forward): either way the snapshot's
        # `before` is the text from before Surasura.
        if earlier is not None and earlier[1] in (before, after) and earlier[0] != after:
            before = earlier[0]
        fields_wanted[key] = [before, after]
    note_ids = ({row.get("note") for card, row in rows.items()
                 if card in state["suspended"] or card in state["flags"] or card in state["named"]}
                | {note_id for _tag, note_id in state["tags"]} | {note_id for note_id, _f in fields_wanted})
    note_ids = sorted(note_id for note_id in note_ids if reposition._is_int(note_id))
    notes = {note.get("noteId"): note for note in (ankiconnect.notes_info(url, note_ids) if note_ids else [])
             if reposition._is_int(note.get("noteId"))}
    made_notes = {note_id for note_id, note in notes.items() if _made(note)}
    made = made_found | {card for card, row in rows.items() if row.get("note") in made_notes}

    # C18: Junban's own suspends, flags, tags and fields come off a card Surasura made too (K3's rules) — only
    # Connect's own changes stay (K5).
    unsuspend = sorted(card for card, tag in state["suspended"].items() if card in rows
                       and rows[card].get("type") == 0 and rows[card].get("queue") == -1
                       and _carries(notes.get(rows[card].get("note")), tag))
    flags = sorted((card, before) for card, (before, last) in state["flags"].items()
                   if card in rows and (rows[card].get("flags") or 0) == last and before != last)

    # The new cards as they will be once Junban's suspends are off: still new, never in a filtered deck.
    back = set(unsuspend)
    new = {card: row for card, row in rows.items()
           if row.get("type") == 0 and not row.get("odeck") and (row.get("queue") == 0 or card in back)}
    writes, later, made_new = [], [], []
    for card, row in new.items():
        first = next((data for data in files if _in_scope(data, row.get("deckName"))), None)
        if card in made:
            if first is not None:
                made_new.append(card)           # K5: Surasura's own cards go after yours, in the order made
            continue
        if first is not None and card > first["taken_ms"]:
            # C5: made after the earliest file covering its deck — added since, whatever a later file holds.
            if card in found or card in back:
                later.append(card)
        elif card in kept:
            if row.get("due") != kept[card]:
                writes.append((card, kept[card]))
    added, made_after = [], []
    for number, card in enumerate(sorted(later) + sorted(made_new), 1):     # card ids are the moments they were added
        if new[card].get("due") != top + number:
            (made_after if card in made else added).append((card, top + number))
    writes = sorted(writes + added + made_after, key=lambda pair: (pair[1], pair[0]))

    # `Surasura::later` stays on a note while one of its cards a suspend line names stays suspended (C11).
    staying = {rows[card].get("note") for card in state["named"]
               if card in rows and card not in back and rows[card].get("queue") == -1}
    tags = {}
    for tag, note_id in sorted(state["tags"]):
        if note_id in notes and _carries(notes[note_id], tag) and not (tag.endswith("::later") and note_id in staying):
            tags.setdefault(tag, []).append(note_id)
    fields, edited, wrote = {}, set(), {}
    for (note_id, field), (before, after) in sorted(fields_wanted.items()):
        if note_id not in notes:
            continue
        values = reposition._note_values(notes[note_id])
        if field not in values:
            continue
        now = values[field] or ""
        if now == after and now != before:
            fields.setdefault(note_id, {})[field] = before
            wrote[(note_id, field)] = after
        elif now != after and now != before:
            edited.add(note_id)

    # Anki's `tag:X` finds X's children too: each older note is read, and kept only for a tag it carries itself.
    main_tagged = {note_id for ids in tags.values() for note_id in ids}
    unread = sorted({n for ids in older_notes.values() for n in ids} - set(notes) - main_tagged)
    notes.update({note.get("noteId"): note for note in (ankiconnect.notes_info(url, unread) if unread else [])
                  if reposition._is_int(note.get("noteId"))})
    older_notes = {tag: sorted(n for n in ids - main_tagged if _carries(notes.get(n), tag))
                   for tag, ids in older_notes.items()}
    older_notes = {tag: ids for tag, ids in older_notes.items() if ids}
    field_decks = set(decks) | {deck for line in lines if line.get("fields")
                                for deck in _scope(line.get("deck"))}
    return {"files": files, "unsuspend": unsuspend, "writes": writes,
            "gathered": {c: r.get("due") for c, r in new.items()}, "added": {card for card, _due in added},
            "made_after": {card for card, _due in made_after}, "made": len(made), "flags": flags,
            "flag_last": {card: last for card, (_before, last) in state["flags"].items()},
            "suspend_tags": {card: [state["suspended"][card]] for card in unsuspend},
            "later_tags": later_tags, "tags": tags, "fields": fields, "wrote": wrote,
            "edited": len(edited - set(fields)), "older_cards": sorted(older_cards), "older_notes": older_notes,
            "field_decks": sorted(field_decks)}


def _counts(survey):
    tagged = {note_id for notes in survey["tags"].values() for note_id in notes}
    after = len(survey["added"]) + len(survey["made_after"])
    return {"cards_back": len(survey["writes"]) - after, "added_after": len(survey["added"]),
            "made_after": len(survey["made_after"]),
            "unsuspend": len(survey["unsuspend"]), "tags_off": len(tagged), "flags": len(survey["flags"]),
            "fields_unedited": len(survey["fields"]), "fields_edited": survey["edited"],
            "older_suspended": len(survey["older_cards"]),
            "older_tags": len({n for notes in survey["older_notes"].values() for n in notes}),
            "made_left": survey["made"]}


def _settings_language(settings, language):
    from modules.junban import reposition
    return language or reposition._language(settings)


def _base(language):
    return {"ok": False, "problems": [], "profile": None, "taken_at": None, "earlier": False, "cards_back": 0,
            "added_after": 0, "made_after": 0, "unsuspend": 0, "tags_off": 0, "flags": 0, "fields_unedited": 0,
            "fields_edited": 0, "older_suspended": 0, "older_tags": 0, "made_left": 0, "nothing": False,
            "anki_closed": False, "wrong_profile": None, "stands_aside": None, "backfill_fills": None,
            "set_aside": set_aside(language)}


def _anki_problem(base, error):
    """C26: Anki not answering reads "Open Anki first"; a refusal reads as itself."""
    if getattr(error, "kind", None) == "offline":
        base.update(anki_closed=True, problems=[f"{ANKI_CLOSED} ({error})"])
    else:
        base.update(problems=[f"{error} Nothing was changed."])
    return base


def _open(language, url, move=False):
    """The checks every put-back starts with -> `(base, profile)`: `base` is `plan`'s dict so far (`ok` False with
    its reason when it can't go on); `profile` the open one, or None. `move`: a broken order file is set aside
    (`put_back`, holding the lock; never `plan`, C6)."""
    from app import anki_connect
    base = _base(language)
    if not has_anything(language):
        base.update(nothing=True, problems=[NOTHING])
        return base, None
    try:
        files, busy = orders(language, move)
    except OSError as e:
        base["problems"] = [f"A saved order that can't be read couldn't be set aside ({e}): nothing was changed."]
        return base, None
    base["set_aside"] = set_aside(language)
    if busy:
        base["problems"] = [f"{len(busy)} of Surasura's saved orders can't be read just now (another program holds "
                            "it). Try again in a moment: nothing was changed."]
        return base, None
    if not anki_connect.probe(url).get("ok"):
        base.update(anki_closed=True, problems=[ANKI_CLOSED])
        return base, None
    try:
        open_now = _ask_profile(url)
    except anki_connect.AnkiError as e:
        return _anki_problem(base, e), None
    base["profile"] = open_now
    mine = [data for data in files if data["profile"] == open_now]
    lines = [line for line in journal(language) if line.get("profile") == open_now]
    if not mine and not lines:
        named = files[0]["profile"] if files else next(
            (str(line.get("profile")) for line in journal(language) if line.get("profile") is not None), "")
        base.update(wrong_profile=named,
                    problems=[f'Open the profile "{named}" in Anki first: nothing was changed.'])
        return base, None
    if mine:
        base.update(taken_at=mine[0]["taken_at"], earlier=any(data["earlier"] for data in mine))
    return base, open_now


def _aside(settings, language, files, field_decks):
    """FT-1 (D7) as the put-back would apply it -> `{"deck": the recorded (language, deck) pair's deck when an order
    file put back holds it — the automatic re-order then stands aside for it — else None; "backfill": Backfill's deck
    ("" = all your decks) when its automatic step is on and fills a deck whose fields would come back (C16), else
    None}`."""
    from app import replan_preview
    settings = settings or {}
    deck = str(settings.get(replan_preview.DECK) or "").strip()
    recorded = str(settings.get(replan_preview.LANGUAGE) or "").strip().lower()
    stands = deck if deck and recorded in (language, "") and any(_in_scope(data, deck) for data in files) else None
    fills = None
    if settings.get("junban_auto_backfill") is True:
        mine = str(settings.get("junban_backfill_deck") or "").strip()
        if any(_overlap(mine, deck) for deck in field_decks):
            fills = mine
    return {"deck": stands, "backfill": fills}


def plan(settings, language=None, url=None):
    """What a put-back would do now (D5, D8's confirm) — reads Anki, writes nothing, moves nothing, takes no lock. The
    dict: `ok`, `problems`, `profile`, `taken_at` (the earliest order file's), `earlier` (D3), `cards_back`,
    `added_after` (yours), `made_after` (Surasura's made cards going after yours, C18), `unsuspend`, `tags_off`
    (notes), `flags`, `fields_unedited` / `fields_edited` (notes), `older_suspended` / `older_tags` (notes; K4: changes
    from before the record, done only when asked), `made_left` (cards Surasura made: K5), `stands_aside` (the deck the
    automatic re-order will stand aside for, C17) and `backfill_fills` (Backfill's deck — "" all — when its automatic
    step goes off with the fields, C16; else None), `set_aside` (order files set aside as unreadable, by name),
    `nothing` (nothing kept, or nothing left to put back), `anki_closed`, `wrong_profile` (the profile to open, or
    None). Never raises (C27)."""
    asked = language
    try:
        from app import anki_connect
        language = _settings_language(settings, language)
        url = url or anki_connect.address(settings)
        base, open_now = _open(language, url)
        if open_now is None:
            return base
        try:
            survey = _survey(url, language, open_now, settings, older=True)
        except anki_connect.AnkiError as e:
            return _anki_problem(base, e)
        counts = _counts(survey)
        aside = _aside(settings, language, survey["files"], survey["field_decks"])
        base.update(counts, ok=True, stands_aside=aside["deck"], backfill_fills=aside["backfill"])
        # Only K4's older changes left (or none at all): nothing of the record's to put back — the older counts still
        # say what the second question would offer.
        base["nothing"] = not any(value for key, value in counts.items()
                                  if key not in ("fields_edited", "made_left", "older_suspended", "older_tags"))
        return base
    except Exception as e:                      # C27: a confirm never loses its answer to a traceback
        base = _base(language or asked or "ja")
        base["problems"] = [f"Surasura couldn't work out what to put back ({e}): nothing was changed."]
        return base


def _report(ok, message, **extra):
    report = {"ok": ok, "message": message, "problems": [], "warnings": [], "settings_changed": [],
              "done": {"cards": 0, "added_after": 0, "made_after": 0, "unsuspended": 0, "tags_off": 0, "flags": 0,
                       "fields": 0}}
    report.update(extra)
    return report


def _plural(count, word):
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def put_back(settings, language=None, fields=False, progress=None, wait=0.0, cancel=None, on_wait=None, url=None,
             older=False, profile=None):
    """D5: put Anki back the way it was before Surasura, holding `anki-writer` — Anki open, the order files' profile
    open (and `profile`, the one `plan` read, when given: another open refuses, C8). First (K11) the deck's automatic
    re-order stands aside (D7, FT-1: `junban_replan_deck` cleared when it names a deck put back; Backfill's automatic
    step off when it fills a deck whose fields come back, C16), through `settings_manager.save_keys` — a save that
    fails refuses with nothing written (C12). Then, asking before each request whether you started reviewing (K14):
    Junban's suspends off; the new cards' order back; Junban's flags back; its tags off; with `fields`, the fields
    back where you haven't edited them; with `older` (K4), the older suspends and tags too (without it, they aren't
    even read: C14). Each request's cards or notes are read again just before it goes, and only what still holds
    Surasura's change is written (C3). Idempotent: pressed again after a cut, it finishes the job. Then Junban's
    unfinished snapshots this record's decks cover are marked complete (C9: this order supersedes them) and a
    `put_back` line is journalled. Returns `ok`, `message`, `problems`, `done` {cards, added_after, made_after,
    unsuspended, tags_off, flags, fields}, `settings_changed` [keys]. `progress(done, total)` as Junban's runs call
    it. Never raises (C27)."""
    from app import anki_connect
    try:
        language = _settings_language(settings, language)
        url = url or anki_connect.address(settings)
        held, problem = anki_connect.take_writer("Put Anki back", url, wait, cancel, on_wait)
        if held is None:
            return _report(False, "Nothing was put back.", problems=[problem], busy=True)
        with held:
            return _put_back(settings, language, fields, progress, url, older, profile)
    except Exception as e:                      # C27: whatever happened, said — and pressing again finishes the job
        line = f"Putting Anki back stopped ({e}). Press it again: it carries on from where Anki is now."
        return _report(False, line, problems=[line])


def _put_back(settings, language, fields, progress, url, older, profile):
    from app import anki_connect
    from modules.junban import ankiconnect, reposition
    from modules.junban.unlisted import FLAG_PURPLE
    base, open_now = _open(language, url, move=True)
    if open_now is None:
        return _report(False, (base["problems"] or ["Nothing was put back."])[0], problems=base["problems"],
                       anki_closed=base["anki_closed"], wrong_profile=base["wrong_profile"], nothing=base["nothing"])
    if profile is not None and profile_name(profile) != open_now:      # C8: the profile the confirm was about
        line = f'Open the profile "{profile_name(profile)}" in Anki first: nothing was changed.'
        return _report(False, line, problems=[line], wrong_profile=profile_name(profile))
    if anki_connect.reviewing(url):
        return _report(False, anki_connect.REVIEWING, problems=[anki_connect.REVIEWING], reviewing=True)
    try:
        survey = _survey(url, language, open_now, settings, older=older, set_aside=True)
    except anki_connect.AnkiError as e:
        refused = _anki_problem({}, e)
        return _report(False, refused["problems"][0], problems=refused["problems"],
                       anki_closed=bool(refused.get("anki_closed")))
    edits = survey["fields"] if fields else {}
    changed, settings_problem = _stand_aside(settings, language, survey, bool(edits))     # K11: first
    if settings_problem:                        # C12: nothing reaches Anki while the automation would go on
        return _report(False, settings_problem, problems=[settings_problem])
    warnings = []
    chunk = reposition._chunk_size(settings)
    stopped = False

    def reviewing(active=None):
        nonlocal stopped
        stopped = stopped or bool(anki_connect.reviewing(url) if active is None else active)
        return stopped

    failures, left = [], []
    cards_back = list(survey["unsuspend"]) + (list(survey["older_cards"]) if older else [])
    needs = dict(survey["suspend_tags"])
    if older:                                   # an older card: any of Surasura's later tags (K4)
        needs.update({card: survey["later_tags"] for card in survey["older_cards"]})
    unsuspended, failed = _unsuspend_checked(url, cards_back, needs, chunk, reviewing)
    failures += failed
    if not reviewing():
        batches = [survey["writes"][at:at + chunk] for at in range(0, len(survey["writes"]), chunk)]
        written, failed, left = ankiconnect.set_due_checked(url, batches, survey["gathered"], progress=progress,
                                                            stop_if=reviewing)
        failures += failed
    else:
        written, left = [], [card for card, _due in survey["writes"]]
    unflagged, failed = _flags_checked(url, survey["flags"], survey["flag_last"], chunk, reviewing)
    failures += failed
    taking = {tag: list(notes) for tag, notes in survey["tags"].items()}
    for tag, notes in (survey["older_notes"].items() if older else ()):
        taking[tag] = sorted(set(taking.get(tag) or []) | set(notes))
    untagged = {}
    for tag, notes in sorted(taking.items()):
        for at in range(0, len(notes), chunk):
            if reviewing():
                break
            done_notes, failed = ankiconnect.remove_tags(url, notes[at:at + chunk], tag, chunk=chunk)
            if done_notes:
                untagged.setdefault(tag, []).extend(done_notes)
            failures += failed
    updated, put_fields, failed = _fields_checked(url, edits, survey["wrote"], chunk, reviewing)
    failures += failed

    flagged = dict(survey["flags"])
    added = len(set(written) & survey["added"])
    made_after = len(set(written) & survey["made_after"])
    done = {"cards": len(written) - added - made_after, "added_after": added, "made_after": made_after,
            "unsuspended": len(unsuspended), "tags_off": len({n for notes in untagged.values() for n in notes}),
            "flags": len(unflagged), "fields": len(updated)}
    try:
        note(language, "put_back", open_now, sorted({d for data in survey["files"] for d in data["scope"]}),
             landed=True, unsuspended=unsuspended, flags={card: [FLAG_PURPLE, flagged[card]] for card in unflagged},
             tags_off=untagged, fields=put_fields, done=done,
             field_decks=survey["field_decks"] if put_fields else [])     # AD-3: what Connect's fill compares
    except Exception as e:                      # C27: Anki changed already — never a traceback now
        warnings.append(f"What was put back couldn't be noted ({e}); pressing it again changes nothing more.")

    finished = not failures and not left and not stopped
    if finished:
        _supersede(language, survey["files"], fields)
    if written or unsuspended or unflagged or untagged or updated:
        reposition._refresh_anki(url)

    data = survey["files"]
    when = (data[0]["taken_at"] or "")[:10] if data else ""
    order = (f"the order Surasura kept on {when}" if any(d["earlier"] for d in data)
             else f"their order from before Surasura ({when})") if data else ""
    parts = []
    if data and written:                         # FT.5: nothing moved -> no "0 new cards back" line
        parts.append(f"{_plural(done['cards'], 'new card')} back in {order}"
                     + (f"; {_plural(added, 'card')} added since after them" if added else "")
                     + (f"; {_plural(made_after, 'card')} Surasura made after yours" if made_after else ""))
    if unsuspended:
        parts.append(f"{_plural(len(unsuspended), 'card')} unsuspended")
    if done["tags_off"]:
        parts.append(f"Surasura's tags off {_plural(done['tags_off'], 'note')}")
    if unflagged:
        parts.append(f"{_plural(len(unflagged), 'flag')} cleared")
    if updated:
        parts.append(f"{_plural(len(updated), 'note')}' fields put back")
    message = ("Put back: " + " · ".join(parts) + ".") if parts else "Anki was already as it was before Surasura."
    if stopped:
        message += " " + REVIEWING_STOP
    elif left:
        message += (f" {_plural(len(left), 'card')} changed in Anki while this worked: press it again to finish.")
    if failures:
        message += f" {_plural(len(failures), 'change')} couldn't be made: press it again once Anki answers."
    return _report(finished, message, warnings=warnings, done=done, settings_changed=changed, left=left,
                   reviewing=stopped, problems=[reason for _id, reason in failures[:1]])


def _unsuspend_checked(url, cards, needs, chunk, stop):
    """C3: Junban's suspends off, each request's cards read again just before it goes — only a card still new, still
    suspended, its note still carrying the tag it went with (`needs[card]`: any of them) -> `(done, failures)`. A
    review (`stop()`, asked before each request) leaves the rest; Anki going away fails the rest."""
    from modules.junban import ankiconnect
    done, failures = [], []
    for at in range(0, len(cards), chunk):
        if stop():
            break
        batch = cards[at:at + chunk]
        try:
            rows = {row.get("cardId"): row for row in ankiconnect.cards_info(url, batch)}
            note_ids = sorted({row.get("note") for row in rows.values() if _whole(row.get("note"))})
            notes = {note.get("noteId"): note for note in (ankiconnect.notes_info(url, note_ids) if note_ids else [])}
        except ankiconnect.AnkiError as e:
            failures += [(card, str(e)) for card in cards[at:]]
            break
        ready = [card for card in batch if (rows.get(card) or {}).get("type") == 0 and rows[card].get("queue") == -1
                 and any(_carries(notes.get(rows[card].get("note")), tag) for tag in needs.get(card) or ())]
        if ready:
            ok, failed = ankiconnect.unsuspend(url, ready, chunk=len(ready))
            done += ok
            failures += failed
    return done, failures


def _flags_checked(url, pairs, last, chunk, stop):
    """C3: Junban's flags back, each request's cards read again just before it goes — only where the card still has
    Surasura's flag (`last[card]`) -> `(written, failures)`."""
    from modules.junban import ankiconnect
    written, failures = [], []
    for at in range(0, len(pairs), chunk):
        if stop():
            break
        batch = pairs[at:at + chunk]
        try:
            rows = {row.get("cardId"): row for row in ankiconnect.cards_info(url, [card for card, _flag in batch])}
        except ankiconnect.AnkiError as e:
            failures += [(card, str(e)) for card, _flag in pairs[at:]]
            break
        ready = [(card, flag) for card, flag in batch if card in rows and (rows[card].get("flags") or 0) == last[card]]
        if ready:
            ok, failed = ankiconnect.set_flags(url, ready, chunk=len(ready))
            written += ok
            failures += failed
    return written, failures


def _fields_checked(url, edits, wrote, chunk, stop):
    """C3: the fields back, each request's notes read again just before it goes — only a field still holding exactly
    what Surasura wrote last (`wrote[(note, field)]`) -> `(updated, journal items {note: {field: {before, after}}},
    failures)`."""
    from modules.junban import ankiconnect, reposition
    items = sorted(edits.items())
    updated, put, failures = [], {}, []
    for at in range(0, len(items), chunk):
        if stop():
            break
        batch = items[at:at + chunk]
        try:
            notes = {note.get("noteId"): note for note in ankiconnect.notes_info(url, [n for n, _v in batch])}
        except ankiconnect.AnkiError as e:
            failures += [(note_id, str(e)) for note_id, _values in items[at:]]
            break
        ready = {}
        for note_id, values in batch:
            now = reposition._note_values(notes.get(note_id) or {})
            keep = {field: value for field, value in values.items() if field in now
                    and now[field] == wrote.get((note_id, field))}
            if keep:
                ready[note_id] = keep
        if ready:
            ok, failed = ankiconnect.update_notes(url, ready, chunk=len(ready))
            updated += ok
            failures += failed
            for note_id in ok:
                put[str(note_id)] = {field: {"before": wrote[(note_id, field)], "after": value}
                                     for field, value in ready[note_id].items()}
    return updated, put, failures


def _covers_snapshot(files, snapshot):
    """C9: does this record hold every deck a snapshot was taken for? Only then does the put-back's order supersede
    it."""
    from modules.junban import undo
    scope = undo.normalize_scope((snapshot or {}).get("scope"))
    return bool(scope) and all(any(_in_scope(data, deck) for data in files) for deck in scope)


def _supersede(language, files, fields):
    """Junban's unfinished snapshots this record's decks cover are marked complete — the reorder's, and with `fields`
    Backfill's (C9); another deck's stays unfinished, its own Restore the way back from it."""
    from modules.junban import undo
    for kind in ("reorder",) + (("backfill",) if fields else ()):
        saved = undo.load(language, kind=kind) or {}
        if saved.get("complete") is False and _covers_snapshot(files, saved):
            undo.mark_complete(language, kind=kind)
        for run_id, saved in undo.runs(language, kind):
            if saved.get("complete") is False and _covers_snapshot(files, saved):
                undo.mark_complete(language, kind=kind, run_id=run_id)


def _stand_aside(settings, language, survey, filled):
    """D7 (FT-1's lean): after a put-back Surasura stops changing those decks by itself — the recorded (language,
    deck) pair cleared when its deck is put back, and Backfill's automatic step off when it fills a deck whose fields
    are put back (C16) -> `(keys changed, problem or None)`. Through `save_keys` (a window's own keys, never the whole
    file), strictly (C12): a save that fails, or waits too long, is the problem — and nothing reaches Anki."""
    from app import replan_preview, settings_manager
    aside = _aside(settings, language, survey["files"], survey["field_decks"])
    changes = {}
    if aside["deck"] is not None:
        changes[replan_preview.DECK] = ""
    if filled and aside["backfill"] is not None:
        changes["junban_auto_backfill"] = False
    if not changes:
        return [], None
    try:
        settings_manager.save_keys(changes, strict=True, wait=SETTINGS_WAIT_S)
    except OSError as e:
        return [], (f"Your settings couldn't be saved ({e}), so the automatic re-order would go on: nothing was "
                    "changed. Try again in a moment.")
    return sorted(changes), None
