"""The journey's door's routes (journey v3 SPEC §3.2–§3.4): one registry, so each owner writes only its own function in
its own file and no two lanes edit one table. The transport is `app/door.py` (loopback, the token, Host / Origin);
the window hands this registry to it (`ShellWindow.door_routes`, started after the first frame).

**A route** is a row of `ROUTES`: its name (frozen in SPEC §3.3) -> (its owner's module, function), imported on the
first call, on the door's thread. The owner writes, in its own file:

    def door_route(body, app) -> dict         # body: the page's JSON, the token taken out; app: an `App`

It answers a dict (the door adds `ok: true`) or refuses with `door.RouteError(<plain words>, <kind>)`. It runs on the
door's handler thread: it opens what it needs there (the library store: its own connection on that thread), never
touches a widget, and the window hears of it the way it hears of its own presses (SPEC §3.2). A row whose module or
function isn't there yet answers `{ok: false, kind: "not_yet"}` (`NOT_YET`), and `hello` lists only the built ones,
so the page hides the rest.

**A reader** is a row of `READERS`, read by `state` ({since: render_stamp}) under its key:

    def door_state(lang, since_ns, app) -> a JSON value, or None (nothing changed since: left out)

`since_ns` is the page's render stamp in ns (None: the page sent none, so everything). A reader not built yet, or one
that raises (logged), is left out of the answer; `state` itself never fails for one reader.

**A waiting press never erases newer work** (Charter G4): a write sent from the page's queue carries `at`, its press
time in ms since the epoch (the page's `Date.now()`). Its owner asks `stale(at, <its record's last change, ns>)` and
skips a stale write, saying so (`door.RouteError(..., STALE)` for one record; a list of the skipped for a batch, as
`words/mark` does). The page then drops it and draws the app's value.

Off until the journey v3 page ships (`enabled()`; J-CUT turns `ON`): until then the window starts no door, nothing
listens, and *Your journey* opens the report as before. Light to import: the window imports it after its first frame.
"""
import importlib
import os
import time
from dataclasses import dataclass
from typing import Callable

ON = False                      # the journey v3 cut-over (J-CUT) turns the door on: this one line
ENV = "SURASURA_DOOR"           # "1": on for a run (the v3 page's own lanes, a test), whatever ON says
LANGS = ("ja", "zh")
NOT_YET = "not_yet"             # a route whose owner isn't built yet: the page hides its control
STALE = "stale"                 # a waiting press older than its record's last change: skipped
CLOSED = "closed"               # Surasura is quitting: the page keeps the press in its queue

# The routes (SPEC §3.3; names frozen): route -> (the owner's module, its function `fn(body, app) -> dict`)
ROUTES = {
    "words/mark": ("app.services.word_marks", "door_route"),             # the word lists (Kotoba-K, J-DOOR)
    "words/undo": ("app.services.word_marks", "door_undo"),
    "episode/prestudied": ("app.services.prestudied", "door_route"),     # the library store (J-STORE)
    "episode/undo": ("app.services.prestudied", "door_undo"),
    "line/flag": ("app.services.flags", "door_route"),                   # Send report's list (J-FLAGS)
    "settings/set": ("app.services.journey_settings", "door_route"),     # the page's settings (J-SET)
    "swap/queue": ("app.connect.door_routes", "swap_route"),             # Swap, the loop's queue (J-SWAP)
    "card/make": ("app.connect.door_routes", "card_route"),              # Connect, an asked card (J-SWAP)
    "clip/cut": ("app.connect.door_routes", "clip_route"),               # Connect's clip (`door.serve_file`)
    "word/audio": ("app.connect.door_routes", "audio_route"),            # a card's word audio, read-only
}

# What `state` reads back (SPEC §3.4): key in its answer -> (the owner's module, `fn(lang, since_ns, app)`)
READERS = {
    "marks": ("app.services.word_marks", "door_state"),
    "prestudied": ("app.services.prestudied", "door_state"),
    "flags": ("app.services.flags", "door_state"),
    "settings": ("app.services.journey_settings", "door_state"),
    "swaps": ("app.connect.door_routes", "swaps_state"),
    "cards": ("app.connect.door_routes", "cards_state"),
}

# The newest render's stamp for `hello` (J-DATA): `fn(lang)` -> its write time in ms since the epoch, or None
RENDER_STAMP = ("app.journey_render", "render_stamp")


@dataclass
class App:
    """What a route may use of the running app: the window's `Services` (None in a bare test), the window's language
    now, whether the quit has begun, and the door's log (`log(where, exception)`). Read on the door's thread."""
    services: object = None
    language: Callable = lambda: "ja"
    closing: Callable = lambda: False
    log: Callable = lambda where, e: None


def enabled():
    return ON or os.environ.get(ENV) == "1"


def stale(at, changed_ns):
    """True when a waiting press is older than its record's last change: `at` the press's time (ms since the epoch),
    `changed_ns` the record's last change (ns since the epoch; None: unknown or never). A press with no time (sent at
    once, not from the queue) is never stale, and neither is one in the very ms of the change."""
    if isinstance(at, bool) or not isinstance(at, (int, float)) or changed_ns is None:
        return False
    return changed_ns // 1_000_000 > at             # (whole ms: exact for an int or a float `at`)


def resolve(spec):
    """(module, function) -> the function, or None when that module or function doesn't exist yet. A module that is
    there but fails to import raises (a bug, said as one; never hidden as *not yet*)."""
    module, name = spec
    try:
        found = importlib.import_module(module)
    except ModuleNotFoundError as e:
        if e.name is not None and (e.name == module or module.startswith(e.name + ".")):
            return None
        raise
    fn = getattr(found, name, None)
    return fn if callable(fn) else None


def routes(app):
    """The door's route table (`door.start(routes, …)`): every row of `ROUTES`, then `hello` and `state`."""
    table = {name: _route(spec, app) for name, spec in ROUTES.items()}
    table["hello"] = lambda body: hello(body, app)
    table["state"] = lambda body: state(body, app)
    return table


def _route(spec, app):
    def call(body):
        from app import door
        if app.closing():
            raise door.RouteError("Surasura is closing.", CLOSED)
        fn = resolve(spec)
        if fn is None:
            raise door.RouteError("This isn't in your Surasura yet.", NOT_YET)
        return fn(body, app)
    return call


def _lang(body):
    from app import door
    lang = body.get("lang")
    if lang not in LANGS:
        raise door.RouteError("Surasura couldn't read that.", "refused")
    return lang


def _built(spec, app):
    try:
        return resolve(spec) is not None
    except Exception as e:
        app.log("journey_door.resolve", e)
        return False


def hello(body, app):
    """Once, after the page's first word is drawn: the door's version, the window's language, the page's library (the
    store's key for that language's data folder: the page sends its queue only to its own library, D31), the newest
    render's stamp, and the routes that are built (the page hides the others)."""
    from app import door
    lang = _lang(body)
    stamp = None
    try:
        fn = resolve(RENDER_STAMP)
        stamp = fn(lang) if fn is not None else None
    except Exception as e:
        app.log("journey_door.hello", e)
    return {"version": door.VERSION, "lang": app.language(), "library": library_id(lang), "render_stamp": stamp,
            "routes": sorted(name for name, spec in ROUTES.items() if _built(spec, app))}


def library_id(lang):
    """The library store's key for `lang`'s data folder (`library_store.library_key`), or None when it can't be told."""
    try:
        from app import library_store, path_utils
        return library_store.library_key(path_utils.get_data_path(lang))
    except Exception:
        return None


def state(body, app):
    """What changed since the page's render (`since`, its render stamp in ms): each reader's answer under its key,
    readers not built or failing left out, and `at`, the time it was read (ms)."""
    lang = _lang(body)
    since = body.get("since")
    since_ns = (int(since * 1_000_000) if isinstance(since, (int, float)) and not isinstance(since, bool)
                and since >= 0 else None)
    out = {"at": time.time_ns() // 1_000_000}
    for key, spec in READERS.items():
        try:
            fn = resolve(spec)
            value = fn(lang, since_ns, app) if fn is not None else None
        except Exception as e:
            app.log(f"journey_door.state {key}", e)
            continue
        if value is not None:
            out[key] = value
    return out
