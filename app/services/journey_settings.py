"""Journey v3's page settings (SPEC §1.4, J-SET; the settings table J-SET-TABLE.md and Sonic's answers, 2026-11-22):
the one place that says which settings the page has, the key each is kept in, the page's word for each value, and how
a value saved before the page reads. Settings › App › Journey (`app/qt/settings_catalog.py`), the page's ⚙ (the door's
`settings/set`, `door_route`) and its read-back (`door_state`) all go through here. Qt-free.

**The keys** (no new key while an existing one means the same, ROLES.md § The backbone): three the app already has —
*The page's theme* is `theme`, *Where each line is from* is `source_display`, *Sentences per word* is
`logic.context.max_contexts` (0 = All, `plan_rules.ALL_CONTEXTS`) — and six new ones (`settings_manager`'s defaults).

**A value saved before reads as its new meaning, never rewritten** (settings criteria 11: nothing writes on load): the
five looks read as Night, but *Modern Light* as Light; *Hidden* reads as Icon (PROVISIONAL, table Q4), *File name* and
*Icon + file name* as Icon + name. The learner's next press writes the new value. **What a press stores keeps the
YouTube preview right** — it still paints the old page from `theme` and `source_display`: Night stores *Dark Flow*,
Light *Modern Light* (the preview's own names), Icon + name *full*; *Only on hover* stores "hover", which the preview
reads as hidden (`preview.py`'s check: a value it doesn't know is "off").

Off until the cut-over (`v3()`): J-CUT turns the door on (`journey_door.ON`), and with it these rows; until then
Settings shows the old Journey rows and nothing here is called.
"""
import os
from collections.abc import Mapping

ON = False                      # on for a run without the door's switch (a test, a capture); J-CUT flips the door's

SENTENCES = "logic.context.max_contexts"
ALL = 0                         # *All* (plan_rules.ALL_CONTEXTS): every sentence the list keeps for the word
SENTENCE_CHOICES = tuple(range(1, 11)) + (ALL,)        # Settings: 1–10 or All (PROVISIONAL, table Q3); the page offers
#                                                        1 · 2 · 3 · 5 · 10 · All, all of them among these
NIGHT, LIGHT = "Dark Flow", "Modern Light"             # what Night and Light store in `theme` (the preview's names)
ACTIONS = ("known", "ignore", "pick", "pre", "line", "word", "meaning", "pitch", "filter", "focus", "lookup",
           "picker")                                   # the page's key map's actions (its ACTIONS), for your own keys

# key -> {the page's value: what is stored} for the keys whose page words differ from what they store, else the
# choices (stored as the page says them); `journey_keys` also takes your own {action: key} map
_STORED = {
    "theme": {"night": NIGHT, "light": LIGHT},
    "source_display": {"icon": "icon", "icon_name": "full", "hover": "hover"},
}
CHOICES = {
    SENTENCES: SENTENCE_CHOICES,
    "journey_pitch": ("shown", "hidden"),
    "journey_meanings": ("en", "yours_en", "yours"),
    "source_display": tuple(_STORED["source_display"]),
    "journey_word_size": ("s", "m", "l"),
    "journey_sentence_size": ("s", "m", "l"),
    "theme": tuple(_STORED["theme"]),
    "journey_keys": ("qwerty", "dvorak"),
    "journey_first_meeting": (True, False),
}
KEYS = tuple(CHOICES)           # the keys the page may set (SPEC §3.3: only §1.4's, as the table corrected them)
LOOKS = frozenset(KEYS) - {SENTENCES, "journey_meanings"}   # applied in the page: a change never re-renders

# How a value saved before the page reads (the table's §1): theme and where-from; anything else unknown is the default
_LIGHTS = (LIGHT, "modern-light")              # Light (the look's name, or the id a hand-edited file may hold); else Night
_OLD_SOURCE = {"off": "icon", "icon": "icon", "filename": "icon_name", "full": "icon_name", "hover": "hover"}


def v3():
    """Whether journey v3's settings are the ones Settings shows: `ON`, or the door's cut-over switch."""
    if ON:
        return True
    try:
        from app.services import journey_door
    except ImportError:
        return False
    return bool(getattr(journey_door, "ON", False))


def _get(settings, key, default=None):
    node = settings
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return default
        node = node[part]
    return node


def _default(key):
    from app import settings_manager
    return _get(settings_manager.DEFAULT_SETTINGS, key)


def page_value(settings, key):
    """`key`'s value in the page's words, as `settings` hold it now (an older value read as its new meaning)."""
    found = _get(settings, key, _default(key))
    if key == "theme":
        return "light" if found in _LIGHTS else "night"
    if key == "source_display":
        return _OLD_SOURCE.get(found, "icon") if isinstance(found, str) else "icon"     # (a hand-edited list)
    if key == SENTENCES:
        if isinstance(found, bool) or not isinstance(found, int):
            return _default(key)
        return max(ALL, found)          # a hand-edited 15 is what the run reads; below 0, All (as the run reads it)
    if key == "journey_keys" and isinstance(found, Mapping):
        return _own_keys(found)
    if key == "journey_first_meeting":
        return found if isinstance(found, bool) else _default(key)     # a hand-edited "false" is no switch
    return found if found in CHOICES[key] else _default(key)


def page_values(settings):
    """{key: its value in the page's words} for every key the page has (the render's head, the door's read-back)."""
    return {key: page_value(settings, key) for key in KEYS}


def stored(key, value):
    """What setting `key` to the page's `value` stores; ValueError for a key the page doesn't have or a value it
    doesn't offer."""
    if key not in CHOICES:
        raise ValueError(f"not a journey setting: {key!r}")
    if key == "journey_keys" and isinstance(value, Mapping):
        own = _own_keys(value)
        if own != dict(value):
            raise ValueError("not a key map")
        return own
    if key == "journey_first_meeting":
        if not isinstance(value, bool):
            raise ValueError(f"not a switch: {value!r}")
        return value
    if isinstance(value, bool) or value not in CHOICES[key] or (key == SENTENCES and not isinstance(value, int)):
        raise ValueError(f"not a choice of {key}: {value!r}")
    return _STORED.get(key, {}).get(value, value)


def stored_now(settings, key):
    """`key`'s value as stored, read the way the page reads it: what Settings shows lit (an old *Midnight* is Night)."""
    value = page_value(settings, key)
    if key == SENTENCES and value not in SENTENCE_CHOICES:
        return value                    # a hand-edited number past the choices: shown as it is, no choice lit
    return stored(key, value)


def _own_keys(value):
    """Your own key map, the part of it that is one: known actions, each a key of a few characters (or "" for none)."""
    return {action: key for action, key in value.items()
            if action in ACTIONS and isinstance(key, str) and len(key) <= 12 and "\n" not in key}


# --- the door (SPEC §3.3: `settings/set` {key, value}; `state`'s "settings") -------------------------------------- #
def door_route(body, app):
    """The page's ⚙: `{key, value, at?}` -> `{saved: the value in the page's words}`. Only the page's keys, only the
    values it offers; written through the window's settings service (the learner's press: one key, one write), or
    without a window onto the file as it is (`save_keys`; a `logic.` key put in its place, the block kept).

    A setting is the learner's last press (no `stale` check: settings.json has one change time for every key, so a
    queue of two presses would skip its own second one). The page queues a press only while Surasura is closed, and
    sends the queue at `hello`, before Settings can be opened."""
    from app import door
    from app.services.settings import put
    key, value = body.get("key"), body.get("value")
    try:
        to_store = stored(key, value)
    except (ValueError, TypeError):
        raise door.RouteError("Surasura couldn't read that setting.", "refused")
    service = getattr(getattr(app, "services", None), "settings", None)
    if service is not None:
        service.set({key: to_store})
    else:
        from app import settings_manager
        settings_manager.save_keys(update=lambda on_file: put(on_file, key, to_store))
    return {"saved": page_value(_nested(key, to_store), key)}


def door_state(lang, since_ns, app):
    """`state`'s "settings": every page setting in the page's words when settings.json changed since the page's
    render (`since_ns`; None: always), else None (left out)."""
    changed = _changed_ns()
    if since_ns is not None and changed is not None and changed <= since_ns:
        return None
    service = getattr(getattr(app, "services", None), "settings", None)
    if service is not None:
        settings = service.get()
    else:
        from app import settings_manager
        settings = settings_manager.load_settings()
    return page_values(settings)


def _changed_ns():
    """settings.json's last change (ns), or None when there is none yet."""
    from app.path_utils import get_settings_path
    try:
        return os.stat(get_settings_path()).st_mtime_ns
    except OSError:
        return None


def _nested(key, value):
    """{key: value} as settings.json holds it (a dotted `logic.` path nested)."""
    out = value
    for part in reversed(key.split(".")):
        out = {part: out}
    return out
