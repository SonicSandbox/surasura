"""J-STORE (3.0.19; journey v3 SPEC §2, §3.3): pre-studied through the journey's door — its two routes and the reader
the door's `state` asks. Qt-free; nothing here before the journey's cut-over calls it (the door's registry,
`app/services/journey_door.py`, names these three; the door is off until then).

  door_route(body, app)            `episode/prestudied`: {id, on, why: "end" | "press", lang?, at?}
                                   -> {on, at, by, undo_id} (undo_id None: nothing changed)
  door_undo(body, app)             `episode/undo`: {undo_id} -> {done}
  door_state(lang, since_ns, app)  the door's `state`, key "prestudied": {id: {"at", "by"}}, every mark now

The library store owns the mark (`Store.set_prestudied`, `Store.prestudied_marks`): this file reads the page's body,
opens the store on the door's own handler thread (a handle of its own for each call: never the window's, never a
widget), keeps each write's Change for its Undo by id, and says a refusal in plain words. `app`: the door's
(`journey_door.App`; only its `language()` is read): a `lang` in the body is the page's own and wins over the window's
language now — an episode's id is its language's store's. The window hears of a press through the store's
`state_version` bump, which its rows already follow.

`at` in the body (ms since 1970, the page's clock): when a press the page kept while Surasura was closed was made — the
store leaves an episode marked after it as it is, and the answer is `stale` (G4: a waiting press never erases newer
work). `door_state` answers every mark, not only those since the render (`since_ns` unread): an un-mark has no date, so
the page reads the whole set as the app's (an episode the render had marked and the set hasn't is un-marked).
"""
import itertools
import threading
import time
from collections import OrderedDict

LANGUAGES = ("ja", "zh")
UNDO_KEPT = 100                   # the last writes whose Undo the page can still ask for (a toast's, a press's)
BUSY_WAIT = 1.0                   # s: a store another writer holds is waited for this long, then "busy"
LATEST_MS = 4102444800000         # 2100-01-01 in ms: a press time past it is not one

_IDS = itertools.count(1)
_KEPT = OrderedDict()             # undo_id -> (language, Change), the newest last
_LOCK = threading.Lock()


class _Refused(Exception):
    """The door's `RouteError` shape (message, kind), until the door is in this build (J-DOOR)."""

    def __init__(self, message, kind="refused"):
        super().__init__(message)
        self.message, self.kind = message, kind


def _refuse(message, kind="refused"):
    try:
        from app.door import RouteError
    except ImportError:
        raise _Refused(message, kind) from None
    raise RouteError(message, kind)


def _language(body, app):
    lang = body.get("lang")
    if lang is None and app is not None:
        lang = app.language()
    if lang not in LANGUAGES:
        _refuse("Surasura couldn't tell which library that episode is in.")
    return lang


def _store(language):
    """The language's store, opened on this thread (None: no store ready — not built, JSON mode, read-only, busy)."""
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    try:
        return library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                        role="window", busy_wait=BUSY_WAIT)
    except library_store.StoreBusy:
        return None


def _open(language):
    store = _store(language)
    if store is None:
        _refuse("Surasura's library isn't ready: try again in a moment.", "busy")
    return store


def _stamp(ms):
    """The page's ms since 1970 as the store's UTC stamp (`library_store._now`'s form), None when it isn't one (or
    isn't before 2100: Windows' clock functions stop at the year 3000)."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not 0 < ms < LATEST_MS:
        return None
    secs, frac = divmod(int(ms * 1000), 10 ** 6)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(secs)) + ".%06dZ" % frac


def _keep(language, change):
    with _LOCK:
        undo_id = next(_IDS)
        _KEPT[undo_id] = (language, change)
        while len(_KEPT) > UNDO_KEPT:
            _KEPT.popitem(last=False)
    return undo_id


def _drop(undo_id):
    with _LOCK:
        _KEPT.pop(undo_id, None)


def door_route(body, app=None):
    """`episode/prestudied`: the end card reached (`why` "end", `on` true) or a press on the episode's stone or R
    (`why` "press", on or off) -> {on, at, by, undo_id}: the episode's mark now, and the id its Undo asks with (None
    when nothing changed: an end card on an episode touched before, a press on one already so)."""
    from app import library_store
    lang = _language(body, app)
    item, on, why = body.get("id"), body.get("on"), body.get("why")
    if (isinstance(item, bool) or not isinstance(item, int) or not 0 < item < 2 ** 63 or not isinstance(on, bool)
            or why not in ("end", "press") or (why == "end" and not on)):
        _refuse("Surasura couldn't read that mark.")
    pressed = body.get("at")
    pressed_at = _stamp(pressed)
    if pressed is not None and pressed_at is None:
        _refuse("Surasura couldn't read that mark.")
    store = _open(lang)
    try:
        try:
            change = store.set_prestudied([item], on, why, pressed_at=pressed_at)
        except library_store.StoreBusy:
            _refuse("Surasura's library is busy: try again in a moment.", "busy")
        undo_id = _keep(lang, change) if change is not None else None     # (kept before anything else can fail)
        now = store.item(item)                                  # (an un-mark too: 'off', no date)
    finally:
        store.close()
    if now is None:
        _refuse("That episode isn't in your library any more.", "gone")
    at, by = now.get("prestudied_at"), now.get("prestudied_by")
    if change is None and pressed_at is not None and at is not None and at > pressed_at:
        _refuse("That episode was marked since.", "stale")
    return {"on": at is not None, "at": at, "by": by, "undo_id": undo_id}


def door_undo(body, app=None):
    """`episode/undo`: the write `undo_id` taken back — each episode's mark as it was, and how it was set — where it
    still holds what that write left (the store's value check) -> {done}: whether anything went back. The id is let
    go of once its Undo ran, or can never run (the library rebuilt since); a busy library keeps it for the next ask."""
    from app import library_store
    undo_id = body.get("undo_id")
    with _LOCK:
        kept = _KEPT.get(undo_id) if isinstance(undo_id, int) and not isinstance(undo_id, bool) else None
    if kept is None:
        _refuse("Surasura can't undo that any more.", "gone")
    lang, change = kept
    store = _open(lang)
    try:
        out = store.undo(change)
    except library_store.UndoRefused as e:
        _drop(undo_id)
        _refuse(f"Surasura can't undo that: {e}.", "gone")
    except library_store.StoreBusy:
        _refuse("Surasura's library is busy: try again in a moment.", "busy")
    finally:
        store.close()
    _drop(undo_id)
    return {"done": bool(out is not None and out.status)}


def door_state(language, since_ns=None, app=None):
    """The door's `state` reader (its key "prestudied"): {id: {"at", "by"}} — every episode marked now (by "end" or
    "press"), whatever `since_ns`; None (nothing to say: the page keeps what it has) while the library isn't ready. A
    failure is the door's to leave out (its registry leaves a raising reader out of the answer)."""
    if language not in LANGUAGES:
        return None
    store = _store(language)
    if store is None:
        return None
    try:
        marks = store.prestudied_marks(by=True)
    finally:
        store.close()
    return {i: {"at": at, "by": by} for i, (at, by) in marks.items()}
