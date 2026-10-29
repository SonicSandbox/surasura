"""Settings export and import (alpha 6, Mattias's note 8; Sonic 2026-10-29: "We can have him save his settings and import
it next run"; leans SI-1…SI-5, PROVISIONAL): one file of the app's settings, saved from one Surasura and brought into
the next alpha or onto a new PC. Qt-free, Tk-free; every call here reads or writes files — a worker's.

**What the file holds** (`export`): settings.json as the file holds it (`settings.file_as_is`: the choices made, never
the defaults — a default left unsaved follows the next version's), stamped with the format (`MARK`), the app version,
the language and the time. The 3.0 line keeps every setting in settings.json (the window, Connect, Junban and Piyo's
included: `settings_placement.PLACED`); the other files beside it are this PC's records, the user's data or caches and
stay out: the window's size and place (`window_state.json`), Connect's setup record (`connect/setup.json`: the Anki
profile and Anki Miner found here), *Needs you*'s answers, Junban's pairs and snapshots, practice rounds, the known
words, the word lists and the library store. Never a secret: Speech's key lives in its keystore, never settings.json,
and a key named like one (`SECRET`) is left out of the file and of an import.

**An import** (`read`, then `apply`): the file read and judged first, nothing written —
- refused, in plain words, when it is empty, isn't a Surasura settings file, or comes from a newer Surasura than this
  one (`newer`): the newer version's settings may mean what this one can't read;
- a key this version doesn't know (`known`: placed, its module installed) is left out, counted; a key the file lacks
  takes its default (the file replaces settings.json whole, and every reader fills the defaults);
- Anki Miner's place (`connect_anki_miner_path`) not on this PC goes back to its default (Surasura finds Anki Miner
  itself); a video folder (`connect_video_folders`) not on this PC is kept and named — *Needs you* asks for it
  (`missing_folders`, a card each: *Find it…* · *Stop looking there*, `folder_change`).
`apply(plan)` replaces settings.json **whole, never merged**: the settings service's changes still queued land first,
then, under the `settings` lock, a dated copy of the file now (`path_utils.backup_to_trash`: `.trash` beside it; none
made, nothing written), then the file written atomically (`settings_manager.save_settings`). The run and render
signatures read the file as any change leaves it (`analyzer.compute_run_signature`): a moved analysis setting means a
full Generate, the same settings none. The window restarts after it (every reader starts from the file).
"""
import datetime
import json
import os
import re
import threading
from collections import namedtuple

from app import path_utils, settings_manager, settings_placement

MARK = "surasura_settings"
FORMAT = 1                       # the file's own shape; a newer one is refused as a newer version is
RECORD = "settings_import.json"  # local data: the last import's folders not on this PC (the *Needs you* cards')
NAME = "Surasura settings {date}.json"
FOLDERS = "connect_video_folders"
MINER_PATH = "connect_anki_miner_path"
# A key named like a secret never leaves or comes in (none is in settings.json: Speech's key is in its keystore)
SECRET = re.compile(r"(^|_)(api_?key|key|token|secret|password|passwd|credentials?)s?$", re.IGNORECASE)
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}

Outcome = namedtuple("Outcome", "ok message path", defaults=(None,))
# read's answer: `refused` (plain words) or None; `settings` what apply writes; `dropped` the keys left out (dotted);
# `missing` the video folders not on this PC; `miner_reset` Anki Miner's place not here (set back to its default)
Plan = namedtuple("Plan", "refused settings version language exported dropped missing miner_reset source",
                  defaults=(None, None, "", "", "", (), (), False, ""))

STRINGS = {
    "exported": "Settings saved to {path}",
    "export_failed": "Couldn't save your settings: {why}",
    "empty": "That file is empty: it holds no settings.",
    "not_ours": "That isn't a Surasura settings file. Save one with Export settings… first.",
    "unreadable": "Couldn't read that file: {why}",
    "no_version": "That settings file doesn't say which Surasura saved it, so it can't be imported safely.",
    "newer": "These settings come from Surasura {theirs}, newer than this one ({ours}). Update Surasura first, then "
             "import them.",
    "newer_format": "These settings were saved by a newer Surasura in a shape this one can't read. Update Surasura "
                    "first, then import them.",
    "ask_title": "Replace your settings?",
    "ask_body": "Every setting is replaced by the ones saved from Surasura {version}{when}{language}: nothing is mixed "
                "in. Your settings now are kept in a dated copy first. Your known words, word lists and library "
                "stay as they are.",
    "ask_dropped_one": "1 setting this version doesn't use is left out.",
    "ask_dropped": "{n} settings this version doesn't use are left out.",
    "ask_missing_one": "1 video folder in them isn't on this computer: Needs you asks you to find it.",
    "ask_missing": "{n} video folders in them aren't on this computer: Needs you asks you to find them.",
    "ask_miner": "Anki Miner isn't where they say on this computer: Surasura finds it by itself.",
    "ask_restart": "Surasura restarts to use them.",
    "ask_yes": "Import and restart",
    "imported": "Settings imported. Your settings before are in {backup}",
    "imported_first": "Settings imported.",
    "busy": "Your settings are being saved by another window just now. Try again in a moment.",
    "backup_failed": "Couldn't keep a copy of your settings now, so nothing was changed: {why}",
    "write_failed": "Couldn't write the settings, so nothing was changed.",
}


def _now():
    return datetime.datetime.now()


def app_version():
    from app import __version__
    return __version__


def _numbers(version):
    """A version's numbers, trailing zeros dropped (2.9.0 is 2.9), or None when it holds none."""
    from app.update_checker import version_string
    text = version_string(str(version or ""))
    if not text:
        return None
    numbers = [int(n) for n in text.split(".")]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def newer(theirs, ours=None):
    """Whether version `theirs` is newer than `ours` (this app's). A version without numbers is never compared."""
    a, b = _numbers(theirs), _numbers(app_version() if ours is None else ours)
    return a is not None and b is not None and a > b


def known(path):
    """Whether this version knows the setting at `path` (a top-level key or a dotted `logic.…` path): it, or a block it
    sits in, is placed, its optional module is installed, and it isn't named like a secret. A `_comment` note isn't a
    setting (the defaults bring their own back)."""
    leaf = path.rsplit(".", 1)[-1]
    if leaf == "_comment" or SECRET.search(leaf):
        return False
    placed = path
    while placed not in settings_placement.PLACED and "." in placed:
        placed = placed.rsplit(".", 1)[0]
    return placed in settings_placement.PLACED and settings_placement._installed(placed)


def _filter(value, path, dropped):
    """`value` (a dict at `path`) with only the settings this version knows; the others' dotted paths into `dropped`."""
    out = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        child = f"{path}.{key}" if path else key
        if child == "logic" and isinstance(item, dict):
            out[key] = _filter(item, child, dropped)
        elif known(child):
            out[key] = _no_secrets(item)
        elif isinstance(item, dict) and path and not SECRET.search(key) and key != "_comment":
            kept = _filter(item, child, dropped)         # a block of placed settings (logic.weights: .high, .low …)
            if kept:
                out[key] = kept
        elif key != "_comment":
            dropped.append(child)
    return out


def _no_secrets(value):
    """`value` with every key named like a secret left out, at any depth (a placed block is kept whole otherwise)."""
    if isinstance(value, dict):
        return {k: _no_secrets(v) for k, v in value.items() if not (isinstance(k, str) and SECRET.search(k))}
    if isinstance(value, list):
        return [_no_secrets(v) for v in value]
    return value


def _clean(settings):
    """settings.json's dict with only what this version knows -> (the dict, the dotted keys left out)."""
    dropped = []
    return _filter(settings, "", dropped), tuple(dropped)


# --- export ------------------------------------------------------------------------------------------------------- #
def default_name(now=None):
    return NAME.format(date=(now or _now()).strftime("%Y-%m-%d"))


def build(settings=None, now=None):
    """The export's dict: settings.json as the file holds it (or `settings`), secrets left out at any depth, stamped."""
    from app.services.settings import file_as_is
    held = file_as_is() if settings is None else settings
    held = {k: v for k, v in _no_secrets(held).items() if isinstance(k, str)}
    loaded = settings_manager.load_settings() if settings is None else held
    return {MARK: FORMAT, "version": app_version(), "language": loaded.get("target_language") or "ja",
            "exported": (now or _now()).isoformat(timespec="seconds"), "settings": held}


def _write_json(path, data):
    """`data` to `path` whole or not at all (a temp file beside it, then `os.replace`)."""
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass


def export(path, settings=None, now=None, service=None, flush_s=10):
    """The settings saved to `path` -> Outcome (its message the bar's). `service` (the window's settings service): its
    queued changes written first, so a change pressed just before is in the file (not written in time: nothing saved)."""
    flush = getattr(service, "flush", None)
    if flush is not None and not flush(flush_s):
        return Outcome(False, STRINGS["busy"], path)
    try:
        _write_json(path, build(settings, now))
    except (OSError, ValueError, TypeError) as e:
        return Outcome(False, STRINGS["export_failed"].format(why=e), path)
    return Outcome(True, STRINGS["exported"].format(path=path), path)


# --- import ------------------------------------------------------------------------------------------------------- #
def _folders(value):
    """Every folder a `connect_video_folders` value names (a list, one folder, or {lang: [...]}), in order, once."""
    if isinstance(value, dict):
        value = [f for lang in value.values() for f in (lang if isinstance(lang, list) else [lang])]
    elif not isinstance(value, list):
        value = [value]
    return list(dict.fromkeys(f for f in value if isinstance(f, str) and f.strip()))


def read(path, isdir=os.path.isdir, isfile=os.path.isfile):
    """The file at `path` judged for an import -> Plan (`refused` the plain words when it can't be). Writes nothing."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return Plan(STRINGS["unreadable"].format(why=e.strerror or e), source=path)
    if not raw.strip():
        return Plan(STRINGS["empty"], source=path)
    try:
        data = json.loads(path_utils.decode_text(raw, None, "strict", name=os.path.basename(path)))
    except ValueError:                            # not JSON, or not text at all (UnicodeDecodeError)
        return Plan(STRINGS["not_ours"], source=path)
    if not isinstance(data, dict) or MARK not in data or not isinstance(data.get("settings"), dict):
        return Plan(STRINGS["not_ours"], source=path)
    version = data.get("version")
    if _numbers(version) is None:
        return Plan(STRINGS["no_version"], source=path)
    if newer(version):
        return Plan(STRINGS["newer"].format(theirs=version, ours=app_version()), version=str(version), source=path)
    if not isinstance(data[MARK], int) or isinstance(data[MARK], bool) or data[MARK] > FORMAT:
        return Plan(STRINGS["newer_format"], version=str(version), source=path)
    settings, dropped = _clean(data["settings"])
    miner = settings.get(MINER_PATH)
    miner_reset = isinstance(miner, str) and bool(miner.strip()) and not isfile(miner)
    if miner_reset or (MINER_PATH in settings and not isinstance(miner, str)):
        settings.pop(MINER_PATH)                  # its default: found by its installer's key
    missing = tuple(f for f in _folders(settings.get(FOLDERS)) if not isdir(f))
    language = settings.get("target_language") or data.get("language") or "ja"
    return Plan(None, settings, str(version), str(language), str(data.get("exported") or ""), dropped, missing,
                miner_reset, path)


def question(plan):
    """The words the window asks before an import replaces anything -> (title, body, yes)."""
    when = ""
    try:
        when = " on " + datetime.datetime.fromisoformat(plan.exported).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        pass
    language = f" for {LANGUAGE_NAMES[plan.language]}" if plan.language in LANGUAGE_NAMES else ""
    said = [STRINGS["ask_body"].format(version=plan.version, when=when, language=language)]
    n = len(plan.dropped)
    if n:
        said.append(STRINGS["ask_dropped_one"] if n == 1 else STRINGS["ask_dropped"].format(n=n))
    n = len(plan.missing)
    if n:
        said.append(STRINGS["ask_missing_one"] if n == 1 else STRINGS["ask_missing"].format(n=n))
    if plan.miner_reset:
        said.append(STRINGS["ask_miner"])
    said.append(STRINGS["ask_restart"])
    return STRINGS["ask_title"], " ".join(said), STRINGS["ask_yes"]


def record_path():
    return os.path.join(path_utils.get_local_data_path(), RECORD)


def apply(plan, service=None, wait=settings_manager.LOCK_WAIT, flush_s=10):
    """settings.json replaced whole by `plan`'s settings -> Outcome (`path`: the dated copy of the settings before).
    `service` (the window's settings service): its queued changes land first, then it reads the new file. Nothing is
    written when they don't land in `flush_s`, when the copy can't be made, or when another program holds the lock
    past `wait`. Left (the review's limits): a change pressed in the moment between the flush and the lock still
    lands after the import — the window restarts at once; and a version's letters are never compared (2.6.0-alpha.3
    reads as 2.6.0): the 3.0 line's versions are numbers only."""
    from app import locks
    if plan.refused is not None or plan.settings is None:
        return Outcome(False, plan.refused or STRINGS["not_ours"])
    flush = getattr(service, "flush", None)
    if flush is not None and not flush(flush_s):  # a change pressed just before is replaced too, never written after:
        return Outcome(False, STRINGS["busy"])    # one still queued (the lock held elsewhere) would land on top
    try:
        held = settings_manager._settings_lock(wait)
    except locks.Busy:
        return Outcome(False, STRINGS["busy"])
    try:
        path = path_utils.get_settings_path()
        try:
            backup = path_utils.backup_to_trash(path)
        except OSError as e:
            return Outcome(False, STRINGS["backup_failed"].format(why=e.strerror or e))
        if not settings_manager.save_settings(dict(plan.settings)):
            return Outcome(False, STRINGS["write_failed"], backup)
    finally:
        if held is not None:
            held.release()
    try:
        _write_json(record_path(), {"version": 1, "at": _now().isoformat(timespec="seconds"), "from": plan.version,
                                    "folders": list(plan.missing)})
    except OSError as e:
        print(f"Settings import: the folders' record wasn't written: {e}")
        try:                                      # never the last import's cards for this one's settings
            os.remove(record_path())
        except OSError:
            pass
    if getattr(service, "reload", None) is not None:
        try:
            service.reload()
        except Exception as e:
            print(f"Settings import: the window's settings weren't read again: {e}")
    return Outcome(True, STRINGS["imported"].format(backup=backup) if backup else STRINGS["imported_first"], backup)


# --- the folders not on this PC (Needs you) ------------------------------------------------------------------------ #
def _recorded():
    try:
        with open(record_path(), encoding="utf-8") as f:
            data = json.load(f)
        return [p for p in data.get("folders") or () if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        return []


def missing_folders(settings, language, isdir=os.path.isdir):
    """The video folders the last import brought that `language` still looks in and this PC still lacks. `settings`: a
    plain dict or the window's frozen one (`settings.get()`)."""
    from app.connect import videos
    from app.services.settings import thaw
    if not settings:
        return []
    looked = set(videos.configured({FOLDERS: thaw(settings.get(FOLDERS))}, language))
    return [p for p in _recorded() if p in looked and not isdir(p)]


def folder_change(settings, old, new=None):
    """{connect_video_folders: …} with folder `old` replaced by `new` in every language that names it, or taken out
    (`new` None) — each other folder as it is."""
    def swap(folders):
        out = [new if f == old else f for f in folders if new is not None or f != old]
        return list(dict.fromkeys(out))
    from app.services.settings import thaw
    value = thaw((settings or {}).get(FOLDERS)) or []
    if isinstance(value, dict):
        value = {lang: swap(v if isinstance(v, list) else [v]) for lang, v in value.items()}
    else:
        value = swap(value if isinstance(value, list) else [value])
    return {FOLDERS: value}
