"""The start gate's decisions (W3.5 part 3; S3.1 D3, D11, D12, D13; Minato's IK-4 / IK-1 Inbox lines). Qt-free: the
window's `app/qt/start_gate.py` asks `state()` before the window's services open the library, and runs `run()` on a
worker.

`state()` -> a dict whose `state` is, checked in this order:
  * `library-missing` — an installed program whose library folder isn't there, though it was there before (this note
    names it, or the import's note brought a library into it): a NAS or OneDrive folder offline, a drive unplugged.
    Refused, never made again by itself (D3); *Try again* looks again; only the user's own *Start with a new, empty
    library here* makes it (`run(..., fresh=True)`).
  * `library-holds-program` — the installed library folder holds a Surasura program (a 2.x unzipped into it later):
    refused, never worked in (D11: the old folder is never written; IK-1). Moving the program out, then *Try again*.
  * `import-unfinished` — `import.json` says an import into this library didn't finish (cancelled, failed, the PC
    went off). Refused: a half-copied library is never used (D11); *Try again* resumes it (`run_import`'s default:
    the files already copied whole are kept; `restart` would copy every one again). `lost` is True when the old folder
    it came from isn't a 2.x library there any more: the user chooses where it is now (`run(..., source=)`: the note
    follows it), or starts fresh (`run(..., fresh=True)`: what was copied so far is moved, whole, into a folder of its
    own in the library, never deleted).
  * `import` — an installed program with a new or empty library, no import made into it, and 2.5's note naming one
    2.x install that still holds its library (`import_2x.find_installs`): it is brought over.
  * `ask-folder` — the same with several 2.x installs (D11: the user picks; `installs` names each), with an import
    already made into another library (`elsewhere`: asked again, never left empty without a word), or with no note
    but 2.x's own per-user folder on this PC (2.4 and earlier write no note, but every 2.x keeps its telemetry id,
    パターン and Koe there): the window asks for the old folder (`check_source`), or the user starts fresh (recorded,
    never asked again for this library).
  * `library-new` — an installed program whose library folder isn't there and was never seen here, with nothing to
    bring over. Nothing on this PC tells a new install's first start from a library offline that this PC never saw:
    the installer writes only library.json, with no stamp, and never makes the folder (D2), and a new PC's OneDrive
    Documents not synced yet looks the same. So it is never made by itself: the user's *Start with a new, empty
    library here* makes it (`run(..., fresh=True)`, through the write check `probe_library`, D12: access denied names
    Controlled Folder Access, `CFA_MESSAGE`), or *Try again* once the drive is back.
  * `ready` — anything else. A source run (a developer's tree), a portable program and a test root import nothing
    unless `import.json` names their own folder as unfinished.

An import into a library folder that isn't there yet makes it (`create`: the import fills it, never leaves it empty).
`run(state, progress, cancel)` runs the import (`run_import`, progress `(stage, done, total)`, `cancel()` between
files) and `graduated_merge.merge_all()` — at every start that runs it: it is idempotent (no list, nothing done).
`needs_run(state)` is False for an everyday start, so the gate opens no window and runs nothing: the library there and
recorded, no GraduatedList waiting.

`first_run.json` in the Houseki local root records each installed library this gate saw there (and whether its user
chose to start fresh): what tells a library offline from one never made.
"""
import json
import os
import time

from app import graduated_merge, import_2x, path_utils

NOTE = "first_run.json"
NOTE_VERSION = 1

LIBRARY_MISSING = "library-missing"
HOLDS_PROGRAM = "library-holds-program"
IMPORT_UNFINISHED = "import-unfinished"
IMPORT = "import"
ASK_FOLDER = "ask-folder"
LIBRARY_NEW = "library-new"
READY = "ready"
STATES = (LIBRARY_MISSING, HOLDS_PROGRAM, IMPORT_UNFINISHED, IMPORT, ASK_FOLDER, LIBRARY_NEW, READY)

LANGUAGES = import_2x.LANGUAGES
ASIDE = "Unfinished import from Surasura 2 ({stamp})"     # a fresh start's folder for an unfinished import's copy


# --- The note: which libraries this gate has seen ---------------------------------------------------------------- #

def note_path():
    return os.path.join(path_utils.local_data_root(), NOTE)


def _key(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _load():
    """first_run.json -> the note; None when there is none; False when a file is there that can't be read as one."""
    try:
        with open(note_path(), "r", encoding="utf-8") as f:
            note = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return False
    return note if isinstance(note, dict) and isinstance(note.get("libraries"), dict) else False


def read_note():
    """first_run.json as written -> {"version", "libraries": {key: {"library", "seen", "fresh"}}}; an empty one when
    there is none or it can't be read."""
    return _load() or {"version": NOTE_VERSION, "libraries": {}}


def _seen(library):
    """This note's record of `library`, or None."""
    entry = read_note()["libraries"].get(_key(library))
    return entry if isinstance(entry, dict) else None


def record(library, fresh=False):
    """`library` seen there (and, with `fresh`, its user chose to start fresh) -> True when written. Never raises: a
    note that can't be written only means the next start looks again. A note there that can't be read is kept beside
    it as it was (`first_run.json.unreadable-<when>`), never written over: its other libraries' records stay."""
    loaded = _load()
    if loaded is False:
        try:
            os.replace(note_path(), f"{note_path()}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}")
        except OSError as e:
            print(f"Start: the first-run note can't be read and could not be set aside ({e}).")
            return False
    note = loaded or {"version": NOTE_VERSION, "libraries": {}}
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
    return bool(note) and not note.get("complete") and not note.get("abandoned") and \
        _same(str(note.get("to") or ""), library)


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
    installed, create, recorded, source, installs, note, lists, elsewhere, lost}. File checks only: never writes, never
    raises for a missing or unreadable file."""
    installed = path_utils.installed_library()
    library = installed or path_utils.get_user_data_path()
    note = import_2x.read_import_note()
    out = {"state": READY, "library": library, "installed": bool(installed), "create": False, "recorded": True,
           "source": None, "installs": [], "note": note, "lists": [], "elsewhere": None, "lost": False}
    seen = None
    if installed:
        seen = _seen(library)
        out["recorded"] = seen is not None
        if not os.path.isdir(library):
            if seen is not None or (note and _same(str(note.get("to") or ""), library)):
                out["state"] = LIBRARY_MISSING
                return out
            out["create"] = True                  # never seen here: new, or offline and never seen (the docstring)
        elif import_2x.holds_program(library):
            out["state"] = HOLDS_PROGRAM          # a program's folder is never a library (IK-1, D11)
            return out
    if _unfinished(note, library):
        source = note.get("from")
        out.update(state=IMPORT_UNFINISHED, source=source,
                   lost=not (isinstance(source, str) and bool(source) and import_2x.is_2x_folder(source)))
        return out
    if not out["create"]:
        out["lists"] = lists_waiting(library)
    if not installed:
        return out
    elsewhere = bool(note and note.get("complete")) and not _same(str(note.get("to") or ""), library)
    if (note and note.get("complete") and not elsewhere) or (seen and seen.get("fresh")):
        return out                                # brought over here already, or a fresh start chosen
    if not out["create"] and import_2x.library_content(library):
        return out                                # a library in use: never imported over (D11)
    installs = import_2x.find_installs()
    out.update(installs=installs, elsewhere=note if elsewhere else None)
    if len(installs) == 1 and not elsewhere:
        out.update(state=IMPORT, source=installs[0]["data_root"])
    elif installs or legacy_data_here():
        out["state"] = ASK_FOLDER                 # several: the user picks (D11); brought over elsewhere: asked again
    elif out["create"]:
        out["state"] = LIBRARY_NEW                # never made by itself (D3)
    return out


def needs_run(st):
    """Does this start need `run` (the gate's worker)? False for an everyday start: ready, the library there and
    recorded, no GraduatedList waiting."""
    return st["state"] != READY or st["create"] or not st["recorded"] or bool(st["lists"])


def _result(status="done", reason=None, message=None):
    return {"status": status, "reason": reason, "message": message, "import": None, "graduated": None}


def _store_names(library, folder):
    """[(the library store's file for `library`'s data folder, the one for `folder`'s)] per language: the store is
    keyed on its data folder's real path (`library_store.library_db_path`)."""
    from app import library_store
    return [(library_store.library_db_path(lang, os.path.join(library, "data", lang)),
             library_store.library_db_path(lang, os.path.join(folder, "data", lang))) for lang in LANGUAGES]


def _set_aside(library):
    """A fresh start over an unfinished import: what it copied (`User Files\\`, `data\\`, and the library store it
    made, as a set) moved whole into a new folder of its own in the library (ASIDE), the import's note pointed at it
    -> None when done, else the OSError's words. Renames only: nothing deleted, nothing copied; on a failure every
    move is put back."""
    aside = os.path.join(library, ASIDE.format(stamp=time.strftime("%Y-%m-%d %H%M%S")))
    moved = []
    try:
        os.mkdir(aside)
        moved.append((None, aside))
        for top in import_2x.LIBRARY_FOLDERS:
            if os.path.exists(os.path.join(library, top)):
                os.rename(os.path.join(library, top), os.path.join(aside, top))
                moved.append((os.path.join(library, top), os.path.join(aside, top)))
        for old, new in _store_names(library, aside):
            for suffix in import_2x.STORE_SUFFIXES:
                if os.path.exists(old + suffix):
                    os.rename(old + suffix, new + suffix)
                    moved.append((old + suffix, new + suffix))
        note = dict(import_2x.read_import_note() or {}, to=aside, set_aside=import_2x._now())
        import_2x._write_json(import_2x.note_path(), note)
        return None
    except OSError as e:
        for src, dst in reversed(moved):
            try:
                if src:
                    os.rename(dst, src)
                else:
                    os.rmdir(dst)
            except OSError:
                pass
        return str(e)


def _note_follows(library, source):
    """The user chose where the old folder of an unfinished import into `library` is now: the note's `from` follows
    it — only while the folder it names isn't a 2.x library any more (moved, renamed), so two installs are never mixed
    into one library (`run_import`'s `other_import`). The files already copied are checked against it by sha256."""
    note = import_2x.read_import_note()
    origin = str((note or {}).get("from") or "")
    if _unfinished(note, library) and not (origin and import_2x.is_2x_folder(origin)) and not _same(origin, source):
        note = dict(note, moved_from=origin)
        note["from"] = source
        import_2x._write_json(import_2x.note_path(), note)


def _abandon(library):
    """A fresh start in a library folder made again: an unfinished import into it (its folder gone, nothing of it
    left) is marked abandoned."""
    note = import_2x.read_import_note()
    if _unfinished(note, library):
        import_2x._write_json(import_2x.note_path(), dict(note, abandoned=import_2x._now()))


def run(st, progress=None, cancel=None, source=None, fresh=False, restart=False):
    """Do what `state()` said, on a worker -> {status, reason, message, import, graduated}. `status`: done; refused
    (`reason` library_missing or library_new — never made without the user's `fresh` —, holds_program, set_aside
    (`message`: the OSError's words), or the import's refusal); blocked (the write check: `message` is CFA_MESSAGE
    when Windows' folder access denied it); cancelled or failed (the import's: its note says unfinished). `source`:
    the old folder the user chose; `fresh`: the user starts fresh instead (a missing or new library made, empty; an
    unfinished import's copy set aside). `restart` is `run_import`'s. The merge runs only once the library is safe."""
    library = st["library"]
    kind = st["state"]
    if kind == HOLDS_PROGRAM:
        return _result("refused", "holds_program", None)
    if kind == LIBRARY_MISSING and not fresh:
        return _result("refused", "library_missing", None)
    importing = not fresh and (kind in (IMPORT, IMPORT_UNFINISHED) or bool(source))
    if st["create"] and not (fresh or importing):
        return _result("refused", "library_new", None)     # a folder never seen here: made only by the user's answer
    if st["installed"] and not importing and (st["create"] or kind == LIBRARY_MISSING):
        probe = import_2x.probe_library(library)          # an import probes after its own checks (`run_import`)
        if not probe["ok"]:
            return _result("blocked", probe["reason"], probe["message"])
    out = _result()
    if fresh and kind == IMPORT_UNFINISHED:
        failed = _set_aside(library)
        if failed:
            return _result("refused", "set_aside", failed)
    try:
        if fresh and kind == LIBRARY_MISSING:
            _abandon(library)
        elif importing and source and kind == IMPORT_UNFINISHED:
            _note_follows(library, source)
    except OSError as e:
        return _result("failed", "note", f"The import's record could not be written ({e}).")
    if importing:
        result = import_2x.run_import(source or st["source"], library, progress=progress, cancel=cancel,
                                      restart=restart, again=bool(st.get("elsewhere")))
        out["import"] = result
        if result["status"] != "done":
            status = "blocked" if result["reason"] == "access_denied" else result["status"]
            out.update(status=status, reason=result["reason"], message=result["message"])
            return out
    if st["installed"]:
        record(library, fresh=fresh)
    out["graduated"] = graduated_merge.merge_all()
    for lang, counts in out["graduated"].items():
        if counts.get("error"):
            print(f"Start: {lang} Graduated list: {counts['error']}")
    return out
