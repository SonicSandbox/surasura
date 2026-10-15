"""The start gate's decisions (W3.5 part 3; S3.1 D3, D11, D12, D13; Minato's IK-4 / IK-1 Inbox lines). Qt-free: the
window's `app/qt/start_gate.py` asks `state()` before the window's services open the library, and runs `run()` on a
worker.

`state()` -> a dict whose `state` is, checked in this order:
  * `library-missing` — an installed program whose library folder isn't there, though it was there before (this note
    names it, or the import's note brought a library into it): a NAS or OneDrive folder offline, a drive unplugged.
    Refused, never made again empty (D3); *Try again* looks again.
  * `import-unfinished` — `import.json` says an import into this library didn't finish (cancelled, failed, the PC
    went off). Refused: a half-copied library is never used (D11); *Try again* resumes it (`run_import`'s default:
    the files already copied whole are kept; `restart` would copy every one again).
  * `import` — an installed program with a new or empty library, no import made, and 2.5's note naming a 2.x install
    that still holds its library (`import_2x.find_installs`, newest first): it is brought over.
  * `ask-folder` — the same, with no note but 2.x's own per-user folder on this PC (2.4 and earlier write no note, but
    every 2.x keeps its telemetry id, パターン and Koe there): the window asks for the old folder (`check_source`), or
    the user starts fresh (recorded, never asked again for this library).
  * `ready` — anything else. A source run (a developer's tree), a portable program and a test root import nothing
    unless `import.json` names their own folder as unfinished.

A library folder that isn't there and was never there before is a new install's first start (the installer never
makes it, D2): `create` is True and `run` makes it through the write check (`probe_library`, D12: access denied names
Controlled Folder Access, `CFA_MESSAGE`). `run(state, progress, cancel)` then runs the import (`run_import`, progress
`(stage, done, total)`, `cancel()` between files) and `graduated_merge.merge_all()` — at every start that runs it: it
is idempotent (no list, nothing done). `needs_run(state)` is False for an everyday start, so the gate opens no window
and runs nothing: the library there and recorded, no GraduatedList waiting.

`first_run.json` in the Houseki local root records each installed library this gate saw there (and whether its user
chose to start fresh): what tells a library offline from a new one.
"""
import json
import os
import time

from app import graduated_merge, import_2x, path_utils

NOTE = "first_run.json"
NOTE_VERSION = 1

LIBRARY_MISSING = "library-missing"
IMPORT_UNFINISHED = "import-unfinished"
IMPORT = "import"
ASK_FOLDER = "ask-folder"
READY = "ready"
STATES = (LIBRARY_MISSING, IMPORT_UNFINISHED, IMPORT, ASK_FOLDER, READY)

LANGUAGES = import_2x.LANGUAGES


# --- The note: which libraries this gate has seen ---------------------------------------------------------------- #

def note_path():
    return os.path.join(path_utils.local_data_root(), NOTE)


def _key(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def read_note():
    """first_run.json as written -> {"version", "libraries": {key: {"library", "seen", "fresh"}}}; an empty one when
    there is none or it can't be read."""
    try:
        with open(note_path(), "r", encoding="utf-8") as f:
            note = json.load(f)
        if isinstance(note, dict) and isinstance(note.get("libraries"), dict):
            return note
    except (OSError, ValueError):
        pass
    return {"version": NOTE_VERSION, "libraries": {}}


def _seen(library):
    """This note's record of `library`, or None."""
    entry = read_note()["libraries"].get(_key(library))
    return entry if isinstance(entry, dict) else None


def record(library, fresh=False):
    """`library` seen there (and, with `fresh`, its user chose to start fresh) -> True when written. Never raises: a
    note that can't be written only means the next start looks again."""
    note = read_note()
    key = _key(library)
    entry = note["libraries"].get(key) if isinstance(note["libraries"].get(key), dict) else {}
    entry = dict(entry, library=os.path.abspath(library), seen=entry.get("seen") or time.strftime("%Y-%m-%dT%H:%M:%S"),
                 fresh=bool(fresh or entry.get("fresh")))
    note["libraries"][key] = entry
    note["version"] = NOTE_VERSION
    try:
        import_2x._write_json(note_path(), note)
        return True
    except OSError as e:
        print(f"Start: the first-run note could not be written ({e}).")
        return False


# --- What this start must do ------------------------------------------------------------------------------------- #

def _same(a, b):
    return bool(a) and bool(b) and _key(a) == _key(b)


def _unfinished(note, library):
    return bool(note) and not note.get("complete") and _same(str(note.get("to") or ""), library)


def legacy_data_here():
    """Has a 2.x run on this PC? Its per-user folder (`legacy_persistent_root`: the telemetry id, パターン, Koe) holds a
    file. 3.0 never makes that folder (only the import reads it)."""
    root = path_utils.legacy_persistent_root()
    try:
        return os.path.isdir(root) and any(os.scandir(root))
    except OSError:
        return False


def lists_waiting(library):
    """The languages whose GraduatedList.txt waits in `library` (`merge_all`'s work): two file checks."""
    return [lang for lang in LANGUAGES
            if os.path.isfile(os.path.join(library, "User Files", lang, graduated_merge.LIST_FILE))]


def state():
    """What this start must do before the window opens the library (see the module docstring) -> {state, library,
    installed, create, recorded, source, installs, note, lists}. File checks only: never writes, never raises for a
    missing or unreadable file."""
    installed = path_utils.installed_library()
    library = installed or path_utils.get_user_data_path()
    note = import_2x.read_import_note()
    out = {"state": READY, "library": library, "installed": bool(installed), "create": False, "recorded": True,
           "source": None, "installs": [], "note": note, "lists": []}
    if installed:
        seen = _seen(library)
        out["recorded"] = seen is not None
        if not os.path.isdir(library):
            if seen is not None or (note and _same(str(note.get("to") or ""), library)):
                out["state"] = LIBRARY_MISSING
                return out
            out["create"] = True                  # a new install's first start: made after the write check (D12)
    if _unfinished(note, library):
        out.update(state=IMPORT_UNFINISHED, source=note.get("from"))
        return out
    if not out["create"]:
        out["lists"] = lists_waiting(library)
    if not installed:
        return out
    seen = _seen(library)
    if (note and note.get("complete")) or (seen and seen.get("fresh")):
        return out                                # brought over once already, or a fresh start chosen
    if not out["create"] and import_2x.library_content(library):
        return out                                # a library in use: never imported over (D11)
    installs = import_2x.find_installs()
    if installs:
        out.update(state=IMPORT, source=installs[0]["data_root"], installs=installs)
    elif legacy_data_here():
        out["state"] = ASK_FOLDER
    return out


def needs_run(st):
    """Does this start need `run` (the gate's worker)? False for an everyday start: ready, the library there and
    recorded, no GraduatedList waiting."""
    return st["state"] != READY or st["create"] or not st["recorded"] or bool(st["lists"])


def _result(status="done", reason=None, message=None):
    return {"status": status, "reason": reason, "message": message, "import": None, "graduated": None}


def run(st, progress=None, cancel=None, source=None, fresh=False, restart=False):
    """Do what `state()` said, on a worker -> {status, reason, message, import, graduated}. `status`: done, refused
    (the library missing; or the import's refusal), blocked (the write check: `message` is CFA_MESSAGE when Windows'
    folder access denied it), cancelled or failed (the import's: its note says unfinished). `source`: the old folder
    the user chose (`ask-folder`); `fresh`: the user starts fresh instead. `restart` is `run_import`'s. Nothing is
    written for a missing library; the merge runs only once the library is safe to use."""
    library = st["library"]
    kind = st["state"]
    if kind == LIBRARY_MISSING:
        return _result("refused", "library_missing", None)
    importing = kind in (IMPORT, IMPORT_UNFINISHED) or (kind == ASK_FOLDER and source and not fresh)
    if st["installed"] and (st["create"] or importing):
        probe = import_2x.probe_library(library)
        if not probe["ok"]:
            return _result("blocked", probe["reason"], probe["message"])
    out = _result()
    if importing:
        result = import_2x.run_import(source or st["source"], library, progress=progress, cancel=cancel,
                                      restart=restart)
        out["import"] = result
        if result["status"] != "done":
            out.update(status=result["status"], reason=result["reason"], message=result["message"])
            return out
    if st["installed"]:
        record(library, fresh=fresh and kind == ASK_FOLDER)
    out["graduated"] = graduated_merge.merge_all()
    for lang, counts in out["graduated"].items():
        if counts.get("error"):
            print(f"Start: {lang} Graduated list: {counts['error']}")
    return out
