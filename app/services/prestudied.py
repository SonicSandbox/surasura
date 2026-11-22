"""J-STORE (3.0.19; journey v3 SPEC §2, §3.3): pre-studied through the journey's door — its two routes and the reader
the door's `state` asks. Qt-free; nothing here before the journey's cut-over calls it (the door's registry names it).

  set_route(body, language=None)   `episode/prestudied`: {id, on, why: "end" | "press", lang?, pressed_at?}
                                   -> {on, at, by, undo_id} (undo_id None: nothing changed)
  undo_route(body, language=None)  `episode/undo`: {undo_id} -> {done}
  changes(language)                the door's `state`: {"prestudied": {id: {"at", "by"}}}, every mark now

The library store owns the mark (`Store.set_prestudied`, `Store.prestudied_marks`): this file reads the page's body,
opens the store on the door's own handler thread (a handle of its own for each call: never the window's, never a
widget), keeps each write's Change for its Undo by id, and says a refusal in plain words. `language`: the door's (the
window's) language; a `lang` in the body is the page's own and wins — an episode's id is its language's store's. The
window hears of a press through the store's `state_version` bump, which its rows already follow.

`pressed_at` (ms since 1970, the page's clock): when a press the page kept while Surasura was closed was made — the
store leaves an episode marked after it as it is, and the answer says `stale` (G4: a waiting press never erases newer
work). `changes` answers every mark, not only those since the render: an un-mark has no date, so the page reads the
whole set as the app's (an episode the render had marked and the set hasn't is un-marked).
"""
import itertools
import threading
import time
from collections import OrderedDict

LANGUAGES = ("ja", "zh")
UNDO_KEPT = 100                   # the last writes whose Undo the page can still ask for (a toast's, a press's)
BUSY_WAIT = 1.0                   # s: a store another writer holds is waited for this long, then "busy"

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


def _language(body, language):
    lang = body.get("lang", language)
    if lang not in LANGUAGES:
        _refuse("Surasura couldn't tell which library that episode is in.")
    return lang


def _open(language):
    from app import library_store
    from app.path_utils import get_data_path, get_user_files_path
    try:
        store = library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                         role="window", busy_wait=BUSY_WAIT)
    except library_store.StoreError:
        store = None
    if store is None:
        _refuse("Surasura's library isn't ready: try again in a moment.", "busy")
    return store


def _stamp(ms):
    """The page's ms since 1970 as the store's UTC stamp (`library_store._now`'s form), None when it isn't one."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not 0 < ms < 10 ** 14:
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


def set_route(body, language=None):
    """`episode/prestudied`: the end card reached (`why` "end", `on` true) or a press on the episode's stone or R
    (`why` "press", on or off) -> {on, at, by, undo_id}: the episode's mark now, and the id its Undo asks with (None
    when nothing changed: an end card on an episode touched before, a press on one already so)."""
    from app import library_store
    lang = _language(body, language)
    item, on, why = body.get("id"), body.get("on"), body.get("why")
    if (isinstance(item, bool) or not isinstance(item, int) or not isinstance(on, bool)
            or why not in ("end", "press") or (why == "end" and not on)):
        _refuse("Surasura couldn't read that mark.")
    pressed = body.get("pressed_at")
    pressed_at = _stamp(pressed)
    if pressed is not None and pressed_at is None:
        _refuse("Surasura couldn't read that mark.")
    store = _open(lang)
    try:
        if store.item(item) is None:
            _refuse("That episode isn't in your library any more.", "gone")
        try:
            change = store.set_prestudied([item], on, why, pressed_at=pressed_at)
        except library_store.StoreBusy:
            _refuse("Surasura's library is busy: try again in a moment.", "busy")
        now = store.item(item) or {}                          # (an un-mark too: 'off', no date)
        at, by = now.get("prestudied_at"), now.get("prestudied_by")
    finally:
        store.close()
    if change is None and pressed_at is not None and at is not None and at > pressed_at:
        _refuse("That episode was marked since.", "stale")
    return {"on": at is not None, "at": at, "by": by, "undo_id": _keep(lang, change) if change is not None else None}


def undo_route(body, language=None):
    """`episode/undo`: the write `undo_id` taken back — each episode's mark as it was, and how it was set — where it
    still holds what that write left (the store's value check) -> {done}: whether anything went back."""
    from app import library_store
    undo_id = body.get("undo_id")
    with _LOCK:
        kept = _KEPT.pop(undo_id, None) if isinstance(undo_id, int) and not isinstance(undo_id, bool) else None
    if kept is None:
        _refuse("Surasura can't undo that any more.", "gone")
    lang, change = kept
    store = _open(lang)
    try:
        out = store.undo(change)
    except library_store.UndoRefused as e:
        _refuse(f"Surasura can't undo that: {e}.", "gone")
    except library_store.StoreBusy:
        with _LOCK:
            _KEPT[undo_id] = kept                                  # (asked again, it can still go back)
        _refuse("Surasura's library is busy: try again in a moment.", "busy")
    finally:
        store.close()
    return {"done": bool(out is not None and out.status)}


def changes(language):
    """The door's `state` reader: {"prestudied": {id: {"at", "by"}}} — every episode marked now (by "end" or
    "press"); {} for the marks while the library isn't ready (the page keeps what it has)."""
    from app import library_store
    if language not in LANGUAGES:
        return {"prestudied": {}}
    try:
        store = _open(language)
    except Exception:                                            # (not ready: `_refuse`'s busy)
        return {"prestudied": {}}
    try:
        marks = store.prestudied_marks(by=True)
    except (library_store.StoreError, library_store.sqlite3.Error):
        marks = {}
    finally:
        store.close()
    return {"prestudied": {i: {"at": at, "by": by} for i, (at, by) in marks.items()}}
