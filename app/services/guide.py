"""The feature guide (Hoshi-S, Sonic 2026-11-12, part of the launch; spec: the 3.0 planning folder,
`tracks/window/work/feature-guide-2026-11-12/SPEC.md` — every learner-visible choice PROVISIONAL): *What's new* after
an update and, with it, the header's ✦ that glows while something is unseen. Qt-free: the window (`app/qt/guide.py`)
paints what this says.

- **The notes** — one small file per release beside the code, `app/assets/whats_new/<version>.json`, written at the
  cut from the release notes (CUT.md's step): `{"version", "date", "items": [{"id", "kind", "title", "line", "for",
  "where"}]}`. `kind` one of `KINDS`; `for` tags from `TAGS` (who it matters to); `where` (optional) one anchor of
  `anchor_ok`'s: `tab:<tab>`, `settings:<row or section>`, `help:<card>`, `control:<control>` — where *Show me* goes.
  `problems()` names what's wrong with one; the tests hold every shipped file to it, and refuse a version without its
  file (`tests/test_services_guide.py`): the release PR's version bump stays red until the file is there.
- **What shows** (`unseen`): the releases newer than the one this PC last saw, up to this version, newest first; with
  nothing seen yet (a fresh install, or the first version with the guide) only this version's.
- **For you first** (`profile`, `arrange`): decided here, from what is already on this PC — the language, the library's
  kinds (shows, books, audiobooks: the window's newest view), a known-words sync from Anki, Connect on (Anki Miner),
  hato's entry, a Piyo round kept, 順 on. An item whose tags meet the profile is *for you*; the rest is *everyone*;
  the fixes not for you fold into one line. Nothing is hidden, only ordered.
- **The state** (`guide.json` in the local data folder, beside `window_state.json`: per PC, never settings.json, never
  exported, never sent): `seen`, the newest version whose notes were opened. Written atomically, on a worker.
- **Never on the window's thread:** `look()` (the files and the checks: each a stat or one small read) and `mark_seen()`
  are a worker's; the window only paints their answer.
"""
import json
import os
from collections import namedtuple

KINDS = ("new", "tweak", "fix")                 # the order inside a group
TAGS = ("everyone", "ja", "zh", "shows", "books", "audiobooks", "anki", "miner", "hato", "piyo", "junban")
TABS = ("current", "finished", "needs", "settings")
CONTROLS = ("search", "add", "level", "journey", "arrivals", "known", "circles", "report", "help")
ANCHOR_KINDS = ("tab", "settings", "help", "control")

FOLDER = os.path.join("app", "assets", "whats_new")
STATE_FILE = "guide.json"
STATE_VERSION = 1

# the library's media types (`library_store.MEDIA_TYPES`, `view_rows.MEDIA_WORD`) -> the profile's tag
MEDIA_TAG = {"anime": "shows", "drama": "shows", "movie": "shows", "youtube": "shows", None: "shows",
             "book": "books", "lightnovel": "books", "manga": "books", "text": "books",
             "audiobook": "audiobooks", "podcast": "audiobooks"}

Item = namedtuple("Item", "id kind title line tags where version")
Release = namedtuple("Release", "version date items")
Shown = namedtuple("Shown", "release for_you everyone fixes")        # one release as the panel shows it
Look = namedtuple("Look", "current releases glow")                 # releases: (Shown, …) newest first


# --- versions ------------------------------------------------------------------------------------------------------- #
def version_key(version):
    """'3.0.4' -> (3, 0, 4); None when it isn't dotted numbers (an alpha's 'alpha7' sorts nowhere)."""
    try:
        parts = tuple(int(p) for p in str(version).strip().split("."))
    except (TypeError, ValueError):
        return None
    return parts if parts else None


def current_version():
    from app import __version__
    return __version__


# --- the notes ------------------------------------------------------------------------------------------------------ #
def folder():
    """The notes' folder (frozen or from source)."""
    from app.path_utils import get_resource
    return get_resource(FOLDER)


def anchor_ok(where, has_card=None, locate=None):
    """Whether `where` names a place *Show me* can go. `has_card(id)` / `locate(target)`: the help cards' and the
    Settings catalog's checks (the tests pass the real ones; left out, only the shape is checked)."""
    if not isinstance(where, str) or ":" not in where:
        return False
    kind, _sep, name = where.partition(":")
    if kind not in ANCHOR_KINDS or not name:
        return False
    if kind == "tab":
        return name in TABS
    if kind == "control":
        return name in CONTROLS
    if kind == "help":
        return has_card(name) if has_card else True
    return locate(name) is not None if locate else True


def problems(data, has_card=None, locate=None):
    """What's wrong with one notes file's contents (a dict), as plain lines; [] when nothing is."""
    out = []
    if not isinstance(data, dict):
        return ["not an object"]
    if version_key(data.get("version")) is None:
        out.append(f"version {data.get('version')!r} isn't dotted numbers")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return out + ["no items"]
    seen = set()
    for n, item in enumerate(items):
        at = f"item {n + 1}"
        if not isinstance(item, dict):
            out.append(f"{at}: not an object")
            continue
        at = f"item {item.get('id') or n + 1}"
        if not item.get("id") or item.get("id") in seen:
            out.append(f"{at}: its id is missing or used twice")
        seen.add(item.get("id"))
        if item.get("kind") not in KINDS:
            out.append(f"{at}: kind {item.get('kind')!r} isn't one of {', '.join(KINDS)}")
        for key in ("title", "line"):
            if not isinstance(item.get(key), str) or not item.get(key).strip():
                out.append(f"{at}: no {key}")
        tags = item.get("for")
        if not isinstance(tags, list) or not tags or any(t not in TAGS for t in tags):
            out.append(f"{at}: for {tags!r} isn't a list of {', '.join(TAGS)}")
        if "where" in item and not anchor_ok(item["where"], has_card, locate):
            out.append(f"{at}: where {item['where']!r} names no place")
    return out


def _release(data):
    items = tuple(Item(i["id"], i["kind"], i["title"].strip(), i["line"].strip(), tuple(i["for"]), i.get("where"),
                       data["version"]) for i in data["items"])
    return Release(data["version"], data.get("date") or "", items)


def read_notes(base=None, log=None):
    """Every release's notes in `base` (default: `folder()`), newest first. A file that can't be read or has a problem
    is left out (and said to `log`): a bad file never takes the others with it."""
    base = base or folder()
    try:
        names = [n for n in os.listdir(base) if n.endswith(".json")]
    except OSError:
        return ()
    out = []
    for name in names:
        try:
            with open(os.path.join(base, name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            if log:
                log(f"whats_new {name}: unreadable ({e})")
            continue
        wrong = problems(data)
        if wrong or name[:-5] != data.get("version"):
            if log:
                log(f"whats_new {name}: {'; '.join(wrong) or 'its name is not its version'}")
            continue
        out.append(_release(data))
    out.sort(key=lambda r: version_key(r.version), reverse=True)
    return tuple(out)


def unseen(releases, seen, current):
    """The releases to show: newer than `seen`, up to `current`, newest first. `seen` None (nothing seen on this PC
    yet): only `current`'s. A `current` that isn't a version (a source checkout's odd one): nothing."""
    now = version_key(current)
    if now is None:
        return ()
    last = version_key(seen) if seen else None
    if last is None:
        return tuple(r for r in releases if version_key(r.version) == now)
    return tuple(r for r in releases if last < version_key(r.version) <= now)


# --- for you -------------------------------------------------------------------------------------------------------- #
def media_tags(view):
    """The library's kinds in the window's newest view (`view_rows.View`, frozen: read on a worker): Current's rows,
    Goal's works and Finished's rows — {"shows", "books", "audiobooks"} as far as they are there."""
    tags = set()
    if view is None:
        return tags
    rows = list(getattr(view, "rows", ()) or ())
    for month in getattr(view, "finished", ()) or ():
        rows += list(getattr(month, "rows", ()) or ())
    goal = getattr(view, "goal", None)
    for work in getattr(goal, "works", ()) or ():
        rows.append(work)
    for row in rows:
        tag = MEDIA_TAG.get(getattr(row, "media", None))
        if tag:
            tags.add(tag)
        if getattr(row, "audio", ""):
            tags.add("audiobooks")
        if len(tags) == 3:
            break
    return tags


def _module_on(settings, name, key):
    from app.services import help_cards
    return help_cards.module_present(name) and bool(settings.get(key))


def profile(language, settings, view=None):
    """What this learner uses (a set of `TAGS`), from what is already on this PC; each check a stat or one small read,
    and any that fails counts as not used. A worker's."""
    tags = {"everyone"}
    if language in ("ja", "zh"):
        tags.add(language)
    tags |= media_tags(view)
    settings = settings or {}
    if settings.get("connect_enabled"):
        tags.add("miner")
    try:
        if _module_on(settings, "junban", "enable_junban"):
            tags.add("junban")
    except Exception:
        pass
    try:
        from app import anki_sync
        if anki_sync.load_state(language).get("last_sync"):
            tags.add("anki")
    except Exception:
        pass
    try:
        from app import tools_entry
        if tools_entry.read("hato") is not None:
            tags.add("hato")
    except Exception:
        pass
    try:
        from app import path_utils
        practice = os.path.join(path_utils.get_user_files_path(language), "practice")
        if os.path.isdir(practice) and any(n.endswith(".json") for n in os.listdir(practice)):
            tags.add("piyo")
    except Exception:
        pass
    return tags


def arrange(release, tags):
    """One release as the panel shows it: (for you, everyone, the folded fixes) — each kept in its kind's order. An
    item is for you when a tag other than `everyone` meets `tags`; a fix for you stays in view, the others fold."""
    order = {k: n for n, k in enumerate(KINDS)}
    items = sorted(release.items, key=lambda i: order[i.kind])        # (stable: the file's order inside a kind)
    mine = [i for i in items if set(i.tags) & (set(tags) - {"everyone"})]
    rest = [i for i in items if i not in mine]
    return Shown(release, tuple(mine), tuple(i for i in rest if i.kind != "fix"),
                 tuple(i for i in rest if i.kind == "fix"))


# --- the state ------------------------------------------------------------------------------------------------------ #
def state_path():
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), STATE_FILE)


def read_state(path=None):
    """The guide's state, or {} when it's missing, unreadable or not ours."""
    try:
        with open(path or state_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("version") == STATE_VERSION else {}


def write_state(data, path=None):
    """Atomically (a crash mid-write leaves the old file, never half of one)."""
    path = path or state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = dict(data, version=STATE_VERSION)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# --- the worker's two calls ---------------------------------------------------------------------------------------- #
def look(language, settings, view=None, current=None, base=None, path=None, log=None):
    """(A worker.) What the panel shows and whether the ✦ glows: `Look(current, releases, glow)`."""
    current = current or current_version()
    seen = read_state(path).get("seen")
    notes = read_notes(base, log)
    fresh = unseen(notes, seen, current)
    shown = fresh or unseen(notes, None, current)          # seen already: this version's, still there to read again
    if not shown:
        return Look(current, (), False)
    tags = profile(language, settings, view)
    return Look(current, tuple(arrange(r, tags) for r in shown), bool(fresh))


def mark_seen(current=None, path=None):
    """(A worker.) This version's notes were opened: the glow is over until the next update. Written only when it
    changes (S19). -> True when written."""
    current = current or current_version()
    state = read_state(path)
    if state.get("seen") == current:
        return False
    write_state(dict(state, seen=current), path)
    return True
