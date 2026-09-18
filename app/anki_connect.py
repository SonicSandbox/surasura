"""The AnkiConnect wire — the one place in Surasura that speaks to Anki.

Standard library only (`urllib.request`, mirroring `app/update_checker.py`), loopback only, and it
never raises anything but `AnkiError`. Every function here is a thin, testable shell around one
JSON POST, so whatever sits above it stays pure data and the windows above that can degrade
politely when Anki is closed. Callers import it lazily; the Junban module borrows it through
`modules/junban/ankiconnect.py`, which re-exports these names and keeps its own writers.

**Tests reach this module by patching the global `urllib.request.urlopen`.** That only works
because `invoke` calls it through the module attribute. `from urllib.request import urlopen` would
bind the real function at import time and silently defeat every one of those patches.

Everything below was verified live against this user's AnkiConnect (121 actions) on 2026-09-17.
These are reproduced failure modes, not defensive style — each one costs real, silent data damage:

  * **`"version": 6` goes on the envelope AND on every `multi` sub-action.** Omitted, a sub-action
    quietly defaults to version 4 and comes back as a bare result with no `{"result","error"}`
    wrapper — so the caller's error check reads a value that was never there.
  * **`due` must be sent as an `int`.** A string raises *inside* AnkiConnect and surfaces as
    `[[False, "'str' object cannot be interpreted as an integer"]]` with `error: null`, **leaving
    the old value in place**. Measured, restored, confirmed.
  * **Success for `setSpecificValueOfCard` is `result == [True]`, appended once per CALL** — not
    once per key. The README's documented `[true, true]` is simply wrong.
  * **A validation failure returns a bare `false` (or `[[False, msg]]`) with `error: null`.** A
    client that checks only `error` reports success on every silent no-op, which is the worst
    possible outcome here: the user believes their queue was reordered and it was not.
  * **No `Origin` header** is sent (the stdlib default) — that is precisely what avoids the
    permission prompt and any CORS configuration on the Anki side.

Two actions are refused at the choke point rather than left to discipline: `sync` (this module must
never push anything to AnkiWeb on the user's behalf) and `setDueDate` (it converts new cards into
review cards — the exact opposite of what this feature is for, and it would destroy a schedule).
The check covers `multi` sub-actions too, so neither can be smuggled through a batch. A URL that is
not loopback is refused the same way: Surasura is offline-only, and this client may never become a
new network destination (CLAUDE.md §1).
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

# Where AnkiConnect listens unless the user has moved it.
DEFAULT_URL = "http://127.0.0.1:8765"

# AnkiConnect's current API version. It must appear on the envelope *and* on every sub-action of a
# `multi`; see the module docstring.
API_VERSION = 6

# Never sent, from anywhere in Surasura. `sync` is the user's decision and nobody else's;
# `setDueDate` turns a new card into a review card, silently discarding a schedule. Blocking them
# here means no later work package can reach them by accident.
FORBIDDEN_ACTIONS = frozenset({"sync", "setDueDate"})

# The only hosts this client will talk to. Anything else is refused before a socket is opened.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class AnkiError(Exception):
    """A failure worth showing the user, tagged so the caller can react differently per kind.

    kind: 'offline'  — nothing is listening, or it timed out (Anki closed, or no profile loaded)
          'protocol' — something answered, but not in AnkiConnect's shape
          'action'   — AnkiConnect answered and refused the request
          'refused'  — this module declined to send it (FORBIDDEN_ACTIONS, or not loopback)
    """

    def __init__(self, message, kind="action"):
        super().__init__(message)
        self.kind = kind


def is_loopback(url):
    """True only for a URL whose host is 127.0.0.1, localhost or ::1. Never raises."""
    try:
        host = urllib.parse.urlsplit(str(url)).hostname
    except ValueError:
        return False
    return (host or "").lower() in _LOOPBACK_HOSTS


def _forbidden_in(action, params):
    """The first forbidden action name in `action` or, for a `multi`, in any of its sub-actions
    (nested `multi`s included). Returns None when the request is clean."""
    if action in FORBIDDEN_ACTIONS:
        return action
    if action == "multi" and isinstance(params, dict):
        for sub in params.get("actions") or []:
            if isinstance(sub, dict):
                found = _forbidden_in(sub.get("action"), sub.get("params"))
                if found:
                    return found
    return None


# --------------------------------------------------------------------------- #
# One request
# --------------------------------------------------------------------------- #
def invoke(action, url, timeout=30, **params):
    """POST one action and return its `result`, raising `AnkiError` on anything else.

    The `error` field is checked *and* the envelope shape is checked: at version 6 a well-formed
    reply is always `{"result": ..., "error": ...}`, so a reply missing those keys means we are
    talking to something that is not AnkiConnect (a proxy, a dev server on the same port) and the
    caller must not read a `result` out of it.
    """
    forbidden = _forbidden_in(action, params)
    if forbidden:
        # A programming error, not a user one — but it must never become a network call.
        raise AnkiError(f"'{forbidden}' is not allowed from this module.", kind="refused")
    if not is_loopback(url):
        raise AnkiError(f"Refusing to contact {url}: AnkiConnect must be on this computer "
                        "(127.0.0.1 or localhost).", kind="refused")

    payload = {"action": action, "version": API_VERSION, "params": params}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # Content-Type only. No Origin header, deliberately: its absence is what keeps AnkiConnect from
    # showing the user a permission prompt on every run.
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})

    try:
        # Through the module attribute, never a from-import — see the module docstring.
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        raise AnkiError(f"AnkiConnect returned HTTP {e.code} for '{action}'.", kind="protocol")
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        # ConnectionRefusedError is an OSError, and it is by far the common case: Anki is shut.
        raise AnkiError(f"Could not reach Anki at {url} ({e}). Is Anki running?", kind="offline")

    try:
        reply = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise AnkiError(f"Anki sent a reply that isn't JSON (action '{action}').", kind="protocol")

    if not isinstance(reply, dict) or "result" not in reply or "error" not in reply:
        raise AnkiError(f"Unexpected reply shape from '{action}' — is this really AnkiConnect?",
                        kind="protocol")
    if reply["error"] is not None:
        raise AnkiError(f"Anki refused '{action}': {reply['error']}", kind="action")
    return reply["result"]


def multi(actions, url, timeout=60):
    """Send several actions in one request; return the raw per-action replies, unexamined.

    Each sub-action is stamped with the API version here so no caller can forget (forgetting is the
    version-4 trap in the module docstring). The replies are returned *raw* —
    `[{"result": [True], "error": None}, ...]` — because what counts as success differs per action,
    and only the caller knows which item each slot belongs to. A forbidden sub-action refuses the
    whole batch before anything is sent (`invoke` checks it).
    """
    stamped = []
    for action in actions:
        entry = dict(action)
        entry["version"] = API_VERSION
        stamped.append(entry)
    if not stamped:
        return []                       # nothing to send; don't wake Anki up for an empty list

    result = invoke("multi", url, timeout=timeout, actions=stamped)
    if not isinstance(result, list):
        raise AnkiError("'multi' did not return a list of results.", kind="protocol")
    return result


# --------------------------------------------------------------------------- #
# Liveness and capability
# --------------------------------------------------------------------------- #
def probe(url, required=(), timeout=5):
    """Is Anki up, and can it do what the caller needs? Returns a dict; never raises.

    `{"ok": bool, "version": int|None, "missing": [action, ...], "error": str}`

    Windows call this on open and show the answer in their connection row, so every failure has to
    come back as data. `required` is the caller's capability gate: an AnkiConnect too old to expose
    an action the feature depends on cannot be worked around, and the feature must say so up front
    rather than at the moment of use. With no `required` actions, `apiReflect` is not asked at all.
    """
    required = tuple(required or ())
    report = {"ok": False, "version": None, "missing": [], "error": ""}
    try:
        # requestPermission doubles as the liveness check: it is the one action AnkiConnect answers
        # before any API-key check, and its reply carries the version.
        permission = invoke("requestPermission", url, timeout=timeout)
        if isinstance(permission, dict):
            if isinstance(permission.get("version"), int):
                report["version"] = permission["version"]
            granted = permission.get("permission")
            if granted is not None and granted != "granted":
                report["error"] = ("Anki did not grant access (it may be showing a permission "
                                   "prompt — accept it and try again).")
                return report
        if report["version"] is None:
            report["version"] = invoke("version", url, timeout=timeout)

        if required:
            present = invoke("apiReflect", url, timeout=timeout,
                             scopes=["actions"], actions=list(required))
            available = present.get("actions") if isinstance(present, dict) else None
            available = available if isinstance(available, list) else []
            report["missing"] = [name for name in required if name not in available]
    except AnkiError as e:
        report["error"] = str(e)
        return report

    if report["missing"]:
        report["error"] = ("This AnkiConnect is missing " + ", ".join(report["missing"]) +
                           " — update the add-on to use this feature.")
        return report
    report["ok"] = True
    return report


# --------------------------------------------------------------------------- #
# Reading the collection
# --------------------------------------------------------------------------- #
def escape_query(value):
    """Escape a value (usually a deck name) for a quoted Anki search term. Real deck names contain
    both of these."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _int_ids(values):
    """Ids as ints, junk dropped: a malformed id is not worth failing a whole run over, but it must
    never be passed along as a string either."""
    ids = []
    for value in values:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def find_cards(url, query):
    """Card ids for a search. **The order is meaningless** — AnkiConnect calls `find_cards` with
    `SortOrder.NoOrder`, so callers sort by what they care about, never by position in this list."""
    found = invoke("findCards", url, query=query)
    return _int_ids(found) if isinstance(found, list) else []


def find_notes(url, query):
    """Note ids for a search, as ints. Same caveat on order as `find_cards`."""
    found = invoke("findNotes", url, query=query)
    return _int_ids(found) if isinstance(found, list) else []


def deck_names(url):
    """Every deck name, in Anki's own order."""
    names = invoke("deckNames", url)
    return [str(name) for name in names] if isinstance(names, list) else []


def _chunks(items, size):
    """Fixed-size slices. `size` is clamped to at least 1 so a bad setting cannot loop forever."""
    size = max(1, int(size or 1))
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _info(action, url, ids, chunk):
    """Shared body of cards_info/notes_info: chunk, request, keep the dicts, preserve order."""
    ids = _int_ids(ids)                 # nothing here may raise past AnkiError
    if not ids:
        return []                       # no ids means no request at all
    out = []
    for batch in _chunks(ids, chunk):
        result = invoke(action, url, cards=batch) if action == "cardsInfo" \
            else invoke(action, url, notes=batch)
        if not isinstance(result, list):
            raise AnkiError(f"'{action}' did not return a list.", kind="protocol")
        # AnkiConnect returns an empty dict for an id that no longer exists; dropping those here
        # means no caller ever has to guard a missing `cardId`/`noteId`.
        out.extend(entry for entry in result if isinstance(entry, dict) and entry)
    return out


def cards_info(url, ids, chunk=250):
    """`due`, `type`, `queue`, `note` and `deckName` per card. Chunked: one 5,000-card request
    blocks Anki's GUI thread with no progress and no cancel."""
    return _info("cardsInfo", url, ids, chunk)


def notes_info(url, ids, chunk=250):
    """`modelName` and `fields` (`{name: {"value", "order"}}`) per note. Chunked like `cards_info`."""
    return _info("notesInfo", url, ids, chunk)
