"""The 2.x -> 3.0 import (S3.1 D11, D12, D14; RUNBOOK row 3.1.6). No Tk, no Qt: the window's first-run page calls it.

It COPIES a 2.x install into a new 3.0 library; the old folder and 2.x's own per-user folders (SonicSandbox) are only
ever read, so the user can go back to 2.x at any time (CLAUDE.md §4: user data is sacred).

  * `find_installs()` — the 2.x installs 2.5's note names (`<legacy local root>\\installs.json`), newest `last_run`
    first, each whose folder still holds `User Files\\` or `data\\`. None (2.4 and earlier write no note): the window
    asks for the folder (*Find my old Surasura*) or starts fresh.
  * `check_source(folder)` — refused while any program in that folder runs (2.x writes its library as it runs).
  * `probe_library(folder)` — D12: the folder is made if missing and a test file written and deleted there; access
    denied names Controlled Folder Access and the steps to allow Surasura.exe.
  * `run_import(source, library, progress, cancel)` — only into an empty or new library (never over a 3.0 library
    holding content): `User Files\\` copied with its dates (the 30-day trash clock), every file's sha256 checked
    against its source: the known words, the word lists, Junban's and the Anki sync's files. No content (Sonic
    2026-10-23: shows and books come in again through library folders): `data\\`, the library store and
    `master_manifest.json` (2.x's library order and its backups: 3.0's store would rebuild 2.x's content from it) are
    left behind. settings.json converted in the copy (`junban_url` -> `anki_connect_url`, as `anki_connect.address`
    reads them); the パターン databases, Koe's files (the key is a secret: never logged) and the telemetry id copied
    into the Houseki roaming root; token stores, `results\\` and `bin\\` left behind (caches); the GraduatedList merged
    (`graduated_merge.merge_all`) when the library is this program's own. `import.json` in the Houseki local root
    records it: from, to, when, counts, a sha256 summary and `complete`. A cancel (between files) or a failure leaves
    `"complete": false`: the next run into that folder from the same install resumes (files already copied whole are
    kept) or, with `restart`, copies every file again.

`python -m app.import_2x --from <2.x folder> [--to <library>] [--dry-run]` runs it for tests and support.
"""

import argparse
import errno
import filecmp
import hashlib
import json
import os
import shutil
import sys
import time

from app import path_utils

IMPORT_NOTE = "import.json"
NOTE_VERSION = 1
LIBRARY_FOLDERS = ("User Files", "data")        # what makes a folder a library (a 2.x one, or a 3.0 one with content)
COPIED_FOLDERS = ("User Files",)                # what is copied from the 2.x folder: no content (Sonic 2026-10-23)
LEFT_BEHIND = "master_manifest"                 # 2.x's library order and its backups: 3.0's store would rebuild from it
LANGUAGES = ("ja", "zh")
ROAMING_FILES = ("koe_credentials.json", "koe_usage.json", "telemetry_id.json")   # Koe's kept for its return (3.1)
SECRET_FILES = ("koe_credentials.json",)        # never logged, never hashed into the summary
REPLACED_FILES = ("telemetry_id.json",)         # carried over even when 3.0 made its own (S3.1-4: the same user)
STORE_SUFFIXES = ("", "-wal", "-shm")           # a store is moved as a set (first_run's set-aside): a .db alone
                                                # loses committed rows
PROGRAM_SKIP = ("User Files", "data", "results", ".trash", ".update_staging", ".update_backup")
EMPTY_LISTS = ("Blacklist.txt", "IgnoreList.txt")   # a new library's start writes these with comments only
TMP_SUFFIX = ".import-tmp"
PROBE_NAME = ".surasura-write-check"
PROGRAM_MARKS = ("Surasura.exe", "_internal")   # a folder holding either is a Surasura program, never a library
LIBRARY_FALLBACK = "Surasura Library"           # the library's name in Documents when Documents\Surasura holds a
                                                # program (IK-1; the installer's LibraryFallback says the same)

CFA_MESSAGE = (
    "Surasura could not write to {folder}. Windows may be protecting this folder (Controlled folder access). "
    "To allow Surasura: open Windows Security → Virus & threat protection → Ransomware protection → "
    "Allow an app through Controlled folder access → Add an allowed app → choose Surasura.exe "
    "({exe}). Then restart Surasura. Or choose another folder for your library.")


class ImportFailed(Exception):
    """A step that must stop the import (a copy that doesn't match its source, a file that can't be written)."""


class _Cancelled(Exception):
    pass


# --- Finding a 2.x install ----------------------------------------------------------------------------------------- #

def _key(path):
    return os.path.normcase(os.path.realpath(path))


def _same(a, b):
    return _key(a) == _key(b)


def _inside(path, folder):
    """True when `path` is `folder` or under it (real paths)."""
    p, f = _key(path), _key(folder)
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


def is_2x_folder(folder):
    """A folder holding a 2.x library the import can bring over: `User Files\\` in it (a `data\\` alone holds only
    content, which never comes over: offered, it would import nothing and be recorded as done)."""
    return any(os.path.isdir(os.path.join(folder, name)) for name in COPIED_FOLDERS)


def holds_program(folder):
    """A folder holding a Surasura program (`Surasura.exe` or `_internal`): a 2.x unzipped there, or a 3.0 install.
    It is never a library: 3.0 would work on that copy in place, and an update or an uninstall replaces it."""
    return any(os.path.exists(os.path.join(folder, name)) for name in PROGRAM_MARKS)


def find_installs():
    """The 2.x installs 2.5's note names, newest `last_run` first, one per folder, each whose folder still holds a
    library -> [{data_root, exe, version, languages, last_run}]. [] with no note (2.4 and earlier): the window asks."""
    note = os.path.join(path_utils.legacy_local_root(), path_utils.INSTALLS_NOTE)
    found = {}
    for entry in path_utils.read_install_note(note):
        root = entry.get("data_root")
        if not isinstance(root, str) or not root or not is_2x_folder(root):
            continue
        key = _key(root)
        if key not in found or str(entry.get("last_run") or "") > str(found[key].get("last_run") or ""):
            found[key] = entry
    return sorted(found.values(), key=lambda e: str(e.get("last_run") or ""), reverse=True)


def _note_entry(source):
    """The note's entry for `source`, or None."""
    for entry in find_installs():
        if _same(entry["data_root"], source):
            return entry
    return None


def _program_images(folder):
    """Every program (.exe) in the 2.x folder, its user folders skipped: the images a process holding it would run."""
    images = []
    for dirpath, dirs, files in os.walk(folder):
        if dirpath == folder:
            dirs[:] = [d for d in dirs if d not in PROGRAM_SKIP]
        images += [os.path.join(dirpath, f) for f in files if f.lower().endswith(".exe")]
    return images


def running_from(folder):
    """{pid: image} of every running process whose program lives in `folder` (Windows; elsewhere {}): the updater's
    process listing (`updater._processes_running`)."""
    from app import updater
    return updater._processes_running(_program_images(folder))


def check_source(folder):
    """Can `folder` be imported now? -> {ok, reason, message, running: [{pid, image}]}. Reasons: `missing` (no such
    folder), `not_2x` (no User Files\\), `running` (a program from it runs: close it first)."""
    result = {"ok": False, "reason": None, "message": None, "running": []}
    if not folder or not os.path.isdir(folder):
        result.update(reason="missing", message=f"The folder {folder} isn't there.")
        return result
    if not is_2x_folder(folder):
        result.update(reason="not_2x", message=f"{folder} holds no Surasura word lists (no User Files folder).")
        return result
    running = running_from(folder)
    if running:
        result.update(reason="running", running=[{"pid": p, "image": i} for p, i in sorted(running.items())],
                      message="Your old Surasura is still open. Close it, then try again.")
        return result
    result["ok"] = True
    return result


# --- The library folder: Controlled Folder Access (D12) ---------------------------------------------------------- #

def _denied(exc):
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 5 or \
        getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM)


def _write_probe(path):
    with open(path, "wb") as f:
        f.write(b"surasura")
    os.remove(path)


def probe_library(folder):
    """D12: make `folder` if it is missing, then write and delete a test file there -> {ok, reason, message,
    created}. `reason` is `access_denied` (the message names Controlled Folder Access and how to allow Surasura.exe)
    or `error`. A folder this probe made is removed again when the write fails, so an unusable library is never
    taken for one that is there."""
    folder = os.path.abspath(folder)
    made, p = [], folder
    while not os.path.isdir(p):
        made.append(p)
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    result = {"ok": True, "reason": None, "message": None, "created": bool(made), "folder": folder}
    try:
        os.makedirs(folder, exist_ok=True)
        _write_probe(os.path.join(folder, f"{PROBE_NAME}-{os.getpid()}.tmp"))
        return result
    except OSError as e:
        exe = sys.executable if path_utils.is_frozen() else "Surasura.exe"
        if _denied(e):
            result.update(ok=False, reason="access_denied", message=CFA_MESSAGE.format(folder=folder, exe=exe))
        else:
            result.update(ok=False, reason="error", message=f"Surasura could not write to {folder} ({e}).")
    for d in made:                                  # innermost first; only empty folders this probe made
        try:
            os.rmdir(d)
        except OSError:
            break
    return result


# --- The record: import.json ------------------------------------------------------------------------------------- #

def note_path():
    return os.path.join(path_utils.local_data_root(), IMPORT_NOTE)


def read_import_note():
    """import.json as written, or None (none, unreadable)."""
    try:
        with open(note_path(), "r", encoding="utf-8") as f:
            note = json.load(f)
    except (OSError, ValueError):
        return None
    return note if isinstance(note, dict) else None


def _write_json(path, data):
    """Temp file + fsync + `os.replace`: old or new, never half."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# --- What a library holds ---------------------------------------------------------------------------------------- #

def _only_comments(path):
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return False
    return all(not line.strip() or line.strip().startswith("#") for line in text.splitlines())


def _is_default(path, default):
    """Is the file at `path` the bundled default list, byte for byte (an edited one is the user's)?"""
    try:
        return os.path.isfile(default) and filecmp.cmp(path, default, shallow=False)
    except OSError:
        return False


def library_content(library):
    """The first file that makes `library` a library holding content, or None for an empty or new one. A new 3.0
    library's start writes only folders, the bundled default lists and comment-only Blacklist / IgnoreList: those
    don't count; any other file under `User Files\\` or `data\\` does."""
    for top in LIBRARY_FOLDERS:
        base = os.path.join(library, top)
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                path = os.path.join(dirpath, name)
                if top == "User Files" and os.path.dirname(dirpath) == base:
                    language = os.path.basename(dirpath)
                    if name in EMPTY_LISTS and _only_comments(path):
                        continue
                    if _is_default(path, os.path.join(path_utils.get_base_path(), "defaults", language, name)):
                        continue
                return path
    return None


# --- Copying ----------------------------------------------------------------------------------------------------- #

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _plan_files(source):
    """[(relative path, size)] of every file under the 2.x folder's `User Files\\` but its library order (LEFT_BEHIND:
    `master_manifest.json` and its backups), sorted; the empty folders too ([relative folder])."""
    files, folders = [], []
    for top in COPIED_FOLDERS:
        base = os.path.join(source, top)
        for dirpath, dirs, names in os.walk(base):
            dirs.sort()
            rel_dir = os.path.relpath(dirpath, source)
            if not names and not dirs:
                folders.append(rel_dir)
            for name in sorted(names):
                if not name.lower().startswith(LEFT_BEHIND):
                    files.append((os.path.join(rel_dir, name), os.path.getsize(os.path.join(dirpath, name))))
    return files, folders


def _copy_checked(src, dst, src_sha=None):
    """`src` -> `dst` with its dates (copy2), through a temp name swapped in, the copy's sha256 checked against the
    source's -> the sha256. Raises ImportFailed when they differ (the temp is removed, `dst` untouched)."""
    src_sha = src_sha or sha256_file(src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + TMP_SUFFIX
    try:
        shutil.copy2(src, tmp)
        if sha256_file(tmp) != src_sha:
            raise ImportFailed(f"the copy of {os.path.basename(src)} did not match the original")
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return src_sha


def _settings_target(library):
    """settings.json's place for `library`: this program's settings file when the library is its own (installed: the
    Houseki roaming root), else beside the library (a portable program's layout)."""
    if _same(library, path_utils.get_user_data_path()):
        return path_utils.get_settings_path()
    return os.path.join(library, "settings.json")


def convert_settings(settings):
    """2.x's settings as 3.0 reads them (in place, -> the keys changed): `junban_url` becomes the one address,
    `anki_connect_url`, as `anki_connect.address` decides between them, and leaves the file."""
    if "junban_url" not in settings:
        return []
    from app import anki_connect
    settings["anki_connect_url"] = anki_connect.address(settings)
    settings.pop("junban_url", None)
    return ["anki_connect_url", "junban_url"]


def _import_settings(source, library):
    """2.x's settings.json into 3.0's place -> 'converted' | 'copied' | 'copied as is' (not readable as settings: kept
    for the user, not converted) | 'none'. A settings file already there is backed up to `.trash` first."""
    src = os.path.join(source, "settings.json")
    if not os.path.isfile(src):
        return "none"
    dst = _settings_target(library)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        settings = json.loads(path_utils.read_text(src, errors="strict"))
        if not isinstance(settings, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        settings = None
    held = None
    if dst == path_utils.get_settings_path():
        from app import settings_manager
        try:
            held = settings_manager._settings_lock(settings_manager.LOCK_WAIT)
        except Exception as e:          # locks.Busy: another Surasura program is saving its settings
            raise ImportFailed(f"settings.json is being saved by another Surasura program ({e})")
    try:
        path_utils.backup_to_trash(dst)
        if settings is None or not convert_settings(settings):
            _copy_checked(src, dst)
            return "copied" if settings is not None else "copied as is"
        from app import settings_manager
        settings_manager._write_atomically(dst, settings)
        with open(dst, "r", encoding="utf-8") as f:
            if json.load(f) != settings:
                raise ImportFailed("settings.json did not read back as written")
        return "converted"
    finally:
        if held is not None:
            held.release()


def _roaming_plan():
    root = path_utils.legacy_persistent_root()
    if not os.path.isdir(root):
        return []
    names = sorted(n for n in os.listdir(root) if n.startswith("patterns_") and n.endswith(".db"))
    return [n for n in names + list(ROAMING_FILES) if os.path.isfile(os.path.join(root, n))]


def _import_roaming(name):
    """One of 2.x's per-user files into the Houseki roaming root -> 'copied' | 'same' | 'kept' (3.0 already has its
    own: never overwritten, but for the telemetry id, which is carried over)."""
    src = os.path.join(path_utils.legacy_persistent_root(), name)
    dst = os.path.join(path_utils.get_persistent_user_data_path(), name)
    sha = sha256_file(src)
    if os.path.isfile(dst):
        if sha256_file(dst) == sha:
            return "same"
        if name not in REPLACED_FILES:
            return "kept"
    _copy_checked(src, dst, sha)
    return "copied"


# --- The import --------------------------------------------------------------------------------------------------- #

def _refused(reason, message, **extra):
    out = {"status": "refused", "reason": reason, "message": message}
    out.update(extra)
    return out


def run_import(source, library, progress=None, cancel=None, dry_run=False, restart=False, again=False):
    """Copy the 2.x install at `source` into the 3.0 library folder `library` (see the module docstring).

    `progress(stage, done, total)`, when given, is called as it goes (stage: files, settings, roaming, graduated);
    `cancel()`, when it returns True, stops it between two files. `dry_run`: every check, nothing written (no probe
    either) -> the plan. `restart`: an incomplete import into this folder copies every file again instead
    of keeping those already whole. `again`: a second import after a complete one (into an empty folder).

    -> a dict: `status` done | cancelled | failed | refused | dry-run, `reason` and `message` (a plain sentence)
    when not done, and the counts. Refusals: `running`, `missing`, `not_2x` (`check_source`), `same_folder` (the
    library inside the old folder or the other way round), `holds_program` (a folder holding Surasura.exe or
    `_internal`: `holds_program`), `already_imported`, `other_import` (an unfinished import
    into this folder from another install), `not_empty` (a 3.0 library holding content), `access_denied` / `error`
    (`probe_library`)."""
    source, library = os.path.abspath(source), os.path.abspath(library)
    check = check_source(source)
    if not check["ok"]:
        return _refused(check["reason"], check["message"], running=check["running"])
    if _inside(library, source) or _inside(source, library):
        return _refused("same_folder", "Choose a library folder outside your old Surasura folder.")
    if holds_program(library):
        return _refused("holds_program", f"{library} holds a Surasura program, not a library. Choose another folder, "
                        f"such as Documents\\{LIBRARY_FALLBACK}.")
    previous = read_import_note()
    resuming = False
    if previous and previous.get("complete") and not again:
        return _refused("already_imported", f"Your library was already imported from {previous.get('from')} "
                        f"on {previous.get('finished')}.", previous=previous)
    if previous and not previous.get("complete") and _same(str(previous.get("to") or ""), library) \
            and os.path.isdir(library):
        if not _same(str(previous.get("from") or ""), source):
            return _refused("other_import", f"{library} holds an unfinished import from {previous.get('from')}. "
                            "Finish that one, or choose an empty folder.", previous=previous)
        resuming = True
    if not resuming and os.path.isdir(library):
        found = library_content(library)
        if found:
            return _refused("not_empty", f"{library} already holds a library. Choose an empty folder.",
                            found=found)

    try:
        files, folders = _plan_files(source)
    except OSError as e:
        return _refused("error", f"Your old Surasura folder could not be read ({e}). Nothing was copied.")
    languages = [lang for lang in LANGUAGES if any(
        os.path.isdir(os.path.join(source, top, lang)) for top in COPIED_FOLDERS)]
    entry = _note_entry(source)
    result = {"status": "dry-run" if dry_run else "done", "reason": None, "message": None,
              "from": source, "to": library, "from_version": (entry or {}).get("version"),
              "languages": languages, "resumed": resuming,
              "counts": {"files": len(files), "bytes": sum(s for _r, s in files), "copied": 0, "kept": 0,
                         "folders": len(folders)},
              "settings": "convert" if os.path.isfile(os.path.join(source, "settings.json")) else "none",
              "roaming": {name: "copy" for name in _roaming_plan()},
              "graduated": None, "sha256": None}
    if dry_run:
        return result

    probe = probe_library(library)
    if not probe["ok"]:
        return _refused(probe["reason"], probe["message"])
    record = {"version": NOTE_VERSION, "from": source, "to": library, "from_version": result["from_version"],
              "started": _now(), "finished": None, "complete": False}
    if resuming:
        record["started"] = previous.get("started") or record["started"]
    try:
        _write_json(note_path(), record)
    except OSError as e:
        return _refused("error", f"The import could not start: its record could not be written ({e}). Nothing was "
                        "copied.")

    def tick(stage, done, total):
        if progress is not None:
            progress(stage, done, total)

    def stop():
        if cancel is not None and cancel():
            raise _Cancelled()

    digest, sums = hashlib.sha256(), 0
    try:
        for i, (rel, _size) in enumerate(files):
            stop()
            src, dst = os.path.join(source, rel), os.path.join(library, rel)
            sha = sha256_file(src)
            if not restart and os.path.isfile(dst) and sha256_file(dst) == sha:
                result["counts"]["kept"] += 1          # resumed: already copied whole
            else:
                _copy_checked(src, dst, sha)
                result["counts"]["copied"] += 1
            digest.update(f"{rel.replace(os.sep, '/')}\t{sha}\n".encode("utf-8"))
            sums += 1
            tick("files", i + 1, len(files))
        for rel in folders:
            os.makedirs(os.path.join(library, rel), exist_ok=True)
        result["sha256"] = {"files": sums, "summary": digest.hexdigest()}

        stop()
        result["settings"] = _import_settings(source, library)
        tick("settings", 1, 1)

        if running_from(source):        # started meanwhile: its lists may have changed under the copy
            raise ImportFailed("your old Surasura was started during the import; close it, then run the import again")

        names = list(result["roaming"])
        for i, name in enumerate(names):
            stop()
            result["roaming"][name] = _import_roaming(name)
            tick("roaming", i + 1, len(names))

        if _same(library, path_utils.get_user_data_path()):
            from app import graduated_merge
            result["graduated"] = graduated_merge.merge_all(tuple(languages))
        else:
            result["graduated"] = "at the library's first start"
        tick("graduated", 1, 1)
    except _Cancelled:
        result.update(status="cancelled", reason="cancelled",
                      message="The import was stopped. Your old Surasura is unchanged; run it again to finish.")
    except (ImportFailed, OSError) as e:
        result.update(status="failed", reason="failed",
                      message=f"The import stopped: {e}. Your old Surasura is unchanged; run it again to finish.")
    record.update({"finished": _now(), "complete": result["status"] == "done", "status": result["status"],
                   "languages": languages, "counts": result["counts"], "settings": result["settings"],
                   "roaming": result["roaming"], "sha256": result["sha256"],
                   "graduated": result["graduated"]})
    if result["message"]:
        record["message"] = result["message"]
    try:
        _write_json(note_path(), record)
    except OSError as e:
        result.update(status="failed", reason="failed",
                      message=f"The import's record could not be written ({e}). Your old Surasura is unchanged; run "
                              "the import again to finish.")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m app.import_2x",
                                     description="Copy a Surasura 2.x install into a 3.0 library.")
    parser.add_argument("--from", dest="source", required=True, help="the 2.x folder (the one holding Surasura.exe)")
    parser.add_argument("--to", dest="library", default=None, help="the 3.0 library folder (default: this program's)")
    parser.add_argument("--dry-run", action="store_true", help="check and plan; write nothing")
    parser.add_argument("--restart", action="store_true", help="an unfinished import: copy every file again")
    args = parser.parse_args(argv)
    library = args.library or path_utils.get_user_data_path()
    result = run_import(args.source, library, dry_run=args.dry_run, restart=args.restart)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["status"] in ("done", "dry-run") else 1


if __name__ == "__main__":
    sys.exit(main())
