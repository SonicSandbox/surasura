"""Ukai's pairing (鵜 Ukai, the browser extension: TheForge `Projects/Houseki/Ukai/SPEC.md` §0 U4, §6 U-S1; the
token's file adapted from #474's `online_receiver.token_path` / `kept_token`, by mattias).

**One Allow, nothing typed** (Sonic, U4: "zero resistance"): Ukai asks, Surasura's window shows *Allow 鵜 Ukai to
send to Surasura?* with a 4-digit code that Ukai's menu shows too (only to match at a glance), and the learner's Allow
is the switch. Two routes on the door's extension class (`app/door.py` `Extension`, both `open`: they need no token):

- `POST /v1/pair` (an extension's Origin, `chrome-extension://<32 letters a-p>`, Chrome's id; body `{"version"}`) ->
  `{"pair": <id>, "code": "<4 digits>", "wait_s"}` and the window's card opens (`ask(Request)`, on the door's
  thread). One card at a time: the same extension asking again while it is open gets the same id and code; another
  extension waits (409 `busy`).
- `GET /v1/pair/<id>` -> `{"state": "waiting"}` while the card is open; `{"state": "denied"}` once after *Not now*;
  `{"state": "allowed", "token"}` **once** after *Allow* — the token is made then, written, and handed over (the
  same extension asking again meanwhile gets the same id: its Allow is kept). A
  replayed id, an unknown or expired one: 404 `gone`. An Origin on it other than the asking one: 403 (Chrome's GET
  carries none, as measured: the 128-bit id, handed only in the POST's answer, is then its gate).

**The pairing file** `ukai_keystore.json` in the persistent folder (`path_utils.PARTS`: it STAYS on *Start over*; its
name is one Send report leaves out, `report.SECRET_NAMES`' `*keystore*`): the token, the paired Origin and Ukai's
version. Never settings.json (it ships in the release and leaves with every export), never a log, never a command line.
Read once and kept: the door asks `pairing()` at every call, and *Forget Ukai* (`forget`) clears the kept copy before
the file, so the next call is refused at once. A new Allow replaces the pairing (the Ukai paired before gets 401).

Off with the door's class: built only while `door.EXTENSION_ON` (the window's `ukai_extension`). Standard library only.
"""
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass

FILE = "ukai_keystore.json"
WAIT_S = 600.0                  # a card unanswered this long is let go (Ukai asks again from its menu)
CLAIM_S = 60.0                  # an answered card waits this long for Ukai's GET (it asks about every second)
PAIR_ID = r"[A-Za-z0-9_-]{22}"  # `secrets.token_urlsafe(16)`: 128 bits
EXT_ID = re.compile(r"chrome-extension://([a-p]{32})\Z")    # Chrome's and Edge's extension ids: 32 letters a-p
VERSION = re.compile(r"[0-9A-Za-z.+-]{1,32}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_-]{32}\Z")    # `secrets.token_urlsafe(24)`: 192 bits
MAX_BODY = 4096
STORE_IDS = {}                  # Ukai's store ids -> the store's name, for the card (filled when Ukai is listed)
WAITING, ALLOWED, DENIED = "waiting", "allowed", "denied"
_UNREAD = object()


@dataclass(frozen=True)
class Request:
    """What the window's card shows: `code` the 4 digits, `ext_id` Chrome's id, `store` the store's name (None: an id
    no store gave, the card warns), `replaces` another pairing is kept now."""
    id: str
    code: str
    origin: str
    ext_id: str
    store: object
    version: str
    replaces: bool


@dataclass
class _Pending:
    id: str
    code: str
    origin: str
    version: str
    asked: float
    state: str = WAITING
    answered: float = 0.0


def path():
    """The pairing file's place (the persistent folder; made only when it's written)."""
    from app.path_utils import persistent_root
    return os.path.join(persistent_root(), FILE)


def _error(message, kind, status):
    from app import door
    return door.RouteError(message, kind, status=status)


class Pairing:
    """Ukai's one pairing. `ask(Request)` opens the window's card (any thread; it must not wait for the answer, which
    comes back through `answer`); `where` the file (default `path()`); `clock` monotonic seconds; `changed()` (any
    thread, never under the lock; UKAI-S2) once Ukai is paired or forgotten — Settings' row paints again."""

    def __init__(self, ask, where=None, clock=time.monotonic, changed=None):
        self._ask, self._where, self._clock = ask, where, clock
        self._changed = changed
        self._lock = threading.Lock()
        self._kept = _UNREAD
        self._pending = None

    # --- the door's side ---------------------------------------------------------------------------------------- #
    def extension(self, paired=None):
        """The door's caller class for Ukai: the pairing's two routes (open), and `paired` {"<METHOD> <path>": fn(call)}
        the routes that need this pairing (U-S2's)."""
        from app import door
        pairing = {"POST /v1/pair": self.ask, "GET /v1/pair/(%s)" % PAIR_ID: self.claim}
        return door.Extension(dict(paired or {}, **pairing), self.pairing, open=tuple(pairing))

    def pairing(self):
        """(origin, token) of the paired Ukai, or None: the door reads it at every call."""
        with self._lock:
            kept = self._load()
        return (kept["origin"], kept["token"]) if kept else None

    def ask(self, call):
        """`POST /v1/pair`: a pairing asked for -> its id and code; the window's card opens."""
        origin = call.headers.get("Origin") or ""
        found = EXT_ID.match(origin)
        if not found:
            raise _error("Only Ukai, from Chrome or Edge, can pair with Surasura.", "refused", 403)
        body = call.json(MAX_BODY)
        version = body.get("version", "")
        if not isinstance(version, str) or (version and not VERSION.match(version)):
            raise _error("version must be Ukai's version, as its manifest says it", "body", 400)
        with self._lock:
            now = self._clock()
            self._expire(now)
            p = self._pending
            if p is not None and p.state != DENIED and p.origin == origin:
                return self._asked(p)                       # its card is open, or allowed: the same id and code
            if p is not None and p.origin != origin:
                raise _error("Surasura is asking about another extension now: try again in a minute.", "busy", 409)
            p = self._pending = _Pending(secrets.token_urlsafe(16), "%04d" % secrets.randbelow(10000), origin,
                                         version, now)
            replaces = self._load() is not None
        request = Request(p.id, p.code, origin, found.group(1), STORE_IDS.get(found.group(1)), version, replaces)
        try:
            self._ask(request)
        except Exception:
            with self._lock:
                if self._pending is p:
                    self._pending = None
            raise
        return self._asked(p)

    def claim(self, call):
        """`GET /v1/pair/<id>`: the card's answer; the token, once, after an Allow."""
        given, origin = call.groups[0], call.headers.get("Origin")
        with self._lock:
            self._expire(self._clock())
            p = self._pending
            if p is None or not hmac.compare_digest(given, p.id):
                raise _error("No such pairing: ask again from Ukai's menu.", "gone", 404)
            if origin is not None and origin != p.origin:
                raise _error("This pairing was asked for by another extension.", "refused", 403)
            if p.state == WAITING:
                return {"state": WAITING}
            if p.state == DENIED:
                self._pending = None
                return {"state": DENIED}
            kept = {"origin": p.origin, "token": secrets.token_urlsafe(24), "version": p.version,
                    "at": int(time.time())}
            try:
                self._write(kept)
            except OSError:                                 # (said as busy, never a crash: its log line names the id)
                raise _error("Surasura couldn't save the pairing: try again.", "busy", 503) from None
            self._kept, self._pending = kept, None
        self._said()
        return {"state": ALLOWED, "token": kept["token"]}

    # --- the window's side -------------------------------------------------------------------------------------- #
    def answer(self, pair_id, allowed):
        """The card's answer (the GUI thread) -> False when its pairing is gone (let go, or another asked since)."""
        with self._lock:
            now = self._clock()
            self._expire(now)
            p = self._pending
            if p is None or p.id != pair_id or p.state != WAITING:
                return False
            p.state, p.answered = (ALLOWED if allowed else DENIED), now
            return True

    def forget(self):
        """*Forget Ukai*: the next call is refused at once (the kept copy first), then the file goes. OSError: the
        file stays on disk (the caller says so); this session is unpaired all the same."""
        held = None
        try:
            with self._lock:
                self._kept, self._pending = None, None
                for name in (self._file(), self._file() + ".part"):     # the pairing first: a held .part never keeps it
                    try:
                        os.remove(name)
                    except FileNotFoundError:
                        pass
                    except OSError as e:
                        held = held or e
            if held is not None:
                raise held
        finally:
            self._said()

    def paired(self):
        """{"origin", "version"} of the paired Ukai, or None — what Settings' row shows (never the token)."""
        with self._lock:
            kept = self._load()
        return {"origin": kept["origin"], "version": kept.get("version") or ""} if kept else None

    # --- inside ------------------------------------------------------------------------------------------------- #
    def _said(self):
        if self._changed is not None:
            try:
                self._changed()
            except Exception:                               # (the row's repaint is never a reason to fail a pairing)
                pass

    def _asked(self, p):
        return {"pair": p.id, "code": p.code, "wait_s": int(WAIT_S)}

    def _expire(self, now):
        p = self._pending
        if p is not None and (now - p.asked > WAIT_S if p.state == WAITING else now - p.answered > CLAIM_S):
            self._pending = None

    def _file(self):
        return self._where or path()

    def _load(self):
        if self._kept is _UNREAD:
            try:
                self._kept = _read(self._file())
            except OSError:                                 # (held for a moment: unpaired now, read again next call)
                return None
        return self._kept

    def _write(self, kept):
        where = self._file()
        os.makedirs(os.path.dirname(where), exist_ok=True)
        part = where + ".part"
        try:
            with open(part, "w", encoding="utf-8") as f:
                json.dump(kept, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(part, where)                         # whole or not at all: a crash keeps the pairing before
        except BaseException:
            try:
                os.remove(part)                             # (it holds the token)
            except OSError:
                pass
            raise


def _read(where):
    """The pairing file's {"origin", "token", "version", "at"}, or None (none, or not a pairing). OSError: there, but
    unreadable now."""
    try:
        with open(where, encoding="utf-8") as f:
            kept = json.load(f)
    except FileNotFoundError:
        return None
    except (ValueError, UnicodeDecodeError, IsADirectoryError):
        return None
    if not isinstance(kept, dict) or not isinstance(kept.get("origin"), str) or not EXT_ID.match(kept["origin"]):
        return None
    token = kept.get("token")
    return kept if isinstance(token, str) and TOKEN.match(token) else None
