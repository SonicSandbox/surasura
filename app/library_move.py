"""*Move my library* (3.0.1, Controlled folder access; QUESTIONS.md *Controlled folder access*, Sonic 2026-11-10).

An installed library that Windows won't let Surasura write (Documents\\Surasura under Controlled folder access, `cfa`)
moves, on one press, to a folder Windows doesn't protect (`cfa.move_target()`: C:\\Users\\<you>\\Surasura). User data
is sacred (CLAUDE.md §4), so the move COPIES, never moves:

  1. Refused, nothing done: not an installed program; an update staged; another move, another Surasura program or
     Connect running; the new folder inside the old one (or the other way round), inside a protected folder while CFA
     is on, or already holding something.
  2. The library's own folders (`PARTS`: User Files, data, results, Backups — nothing else in the old folder is
     Surasura's) copied file by file into a new folder beside the target (`<target>.moving-<stamp>`), each file's
     times kept and its sha256 read back from the copy and checked against the original's; a file the original
     changed while it was copied, a cancel or any failure: the new folder (only ever Surasura's copy) is removed and
     nothing else changed. Then it is renamed to the target.
  3. What the local data folder keeps under the library's key (named by its data folder's path:
     `library_store.library_db_path`) — each language's library store and its kept text (`token_index.kept_text_path`)
     — copied under the new key with SQLite's backup (whole, consistent, in its own journal mode — the stores are WAL;
     the JSON copy in a blocked library may be stale, so the store is never rebuilt from it), checked (`integrity_check`,
     the same rows in every table); the store's own backups and damage record beside it copied and checked too. A file
     already there under the new name is set aside beside it, never deleted.
  4. library.json (the installer's note, `path_utils.LIBRARY_NOTE`) now names the new folder: the one switch, written
     last and atomically. The start gate's note records the new library as seen.
  5. The record, `library_move.json` in the Houseki local root: `moving` from before the first file (a move a kill
     stopped is recognised by it, and its own copy cleared, at the next move), `done` with from, to, when and the
     counts once switched — what *Undo* reads. A library seen here before but not there now (offline) never moves.

The old folder is left exactly as it was (under CFA nothing could change it anyway): the learner deletes it once
happy. **Undo** (`undo`, with the library to itself as the move) points library.json back at the old folder and
renames the new one aside (`<target> (moved back <stamp>)`), never deleting it: anything saved there since stays.

No Qt, no Tk: the start gate runs `move` / `undo` on a worker, before anything opens the library.
"""
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import time

from app import cfa, locks, path_utils

PARTS = ("User Files", "data", "results", path_utils.BACKUPS)      # the library place's own names (path_utils.PARTS)
RECORD = "library_move.json"
RECORD_VERSION = 1
MOVING, DONE = "moving", "done"     # the record's status: a move under way (a kill leaves it), a move made
LANGUAGES = ("ja", "zh")
CHUNK = 1024 * 1024
WAIT = 5.0              # s: another Surasura program is waited for this long before the move is refused
VERB = "Moving your library"

REFUSED_NOT_INSTALLED = "Only an installed Surasura can move its library."
REFUSED_UPDATE = "An update is waiting to be installed. Restart Surasura first, then try again."
REFUSED_BUSY = "Another Surasura is moving or setting aside your library just now. Try again in a moment."
REFUSED_RUNNING = "{who} is still running. Close it, then try again."
REFUSED_INSIDE = "Surasura can't move your library into a folder inside it, or the other way round: {target}."
REFUSED_PROTECTED = "Windows protects {target} too. Surasura can't move your library there."
REFUSED_NOT_EMPTY = ("{target} already holds files. Surasura only moves your library into a new or empty folder: "
                     "move that folder's files somewhere else, then try again.")
REFUSED_MISSING = ("Surasura can't find your library in {old} (a drive unplugged, or a cloud folder not synced "
                   "yet?). Connect it, then try again: nothing was moved.")
REFUSED_LINK = "Surasura can't copy {path}: it's a link to another folder. Nothing was moved."
REFUSED_ROOM = ("There isn't room for your library in {target}: it needs {need:,} MB and {free:,} MB are free. "
                "Make room, then try again.")
ROOM_SPARE = 64 * 1024 * 1024    # bytes left free beyond the copy itself
FAILED = "Surasura couldn't copy your library ({error}). Nothing was moved: your library is still in {old}."
CHANGED = "{path} changed while it was being copied. Nothing was moved: try again."
MISMATCH = "The copy of {path} didn't match the original. Nothing was moved: your library is still in {old}."
STORE_FAILED = "Surasura couldn't copy your library's order ({error}). Nothing was moved: your library is still in {old}."
NOTE_FAILED = "Surasura couldn't save where your library is now ({error}). Nothing was moved."
CANCELLED = "Stopped. Nothing was moved: your library is still in {old}."
MOVED = ("Your library is now in {new}. Your old folder, {old}, is kept just as it was: delete it yourself once "
         "you're happy.")
UNDO_NONE = "There's no move to undo."
UNDONE = "Your library is back in {old}. The copy is kept as {aside}."
UNDONE_KEPT = "Your library is back in {old}. The copy stays in {new} (it couldn't be renamed: {error})."
WHO = {"window": "Surasura's window (in another sign-in?)", "cli": "Surasura's command line", "mcp": "Piyo's helper",
       "connect": "Connect"}


class MoveRefused(Exception):
    def __init__(self, reason, words):
        super().__init__(words)
        self.reason = reason
        self.words = words


def _result(status, reason=None, words=None, **more):
    return dict({"status": status, "reason": reason, "words": words}, **more)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _key(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _inside(child, parent):
    c, p = _key(child), _key(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def record_path():
    return os.path.join(path_utils.local_data_root(), RECORD)


def note_path():
    return os.path.join(path_utils.local_data_root(), path_utils.LIBRARY_NOTE)


def read_record():
    """library_move.json as written, or None (none, unreadable)."""
    try:
        with open(record_path(), "r", encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _write_json(path, data, ascii_only=False):
    """Temp + fsync + `os.replace`: the old file or the new one, never half."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=ascii_only, indent=None if ascii_only else 2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _write_note(library):
    """library.json naming `library` for this program, in the installer's shape (ASCII, its three keys): its
    "install" kept as written (the folder path_utils matched this program by), else this program's folder."""
    try:
        with open(note_path(), "r", encoding="utf-8-sig") as f:
            install = json.load(f).get("install")
    except (OSError, ValueError, AttributeError):
        install = None
    if not isinstance(install, str) or not install.strip():
        install = os.path.dirname(os.path.abspath(sys.executable))
    _write_json(note_path(), {"version": 1, "install": install, "library": os.path.abspath(library)}, ascii_only=True)
    path_utils.forget_library()


def _store_db(library, lang):
    from app import library_store
    return library_store.library_db_path(lang, os.path.join(library, "data", lang))


LINK_TAGS = (0xA000000C, 0xA0000003)     # IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT (a junction)


def _is_link(path):
    """A symlink or a junction: never followed into another folder. Other reparse points (OneDrive's files, often in a
    redirected Documents) are ordinary files and folders here."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in LINK_TAGS


# --- What is copied ----------------------------------------------------------------------------------------------- #

def _raise(error):
    raise error                                        # a folder that can't be listed is never skipped silently


def plan(old):
    """[(relative path, size)] of every file the move copies, and [relative folder] of every folder (empty ones
    too), from the old library's own parts. A link to another folder -> MoveRefused."""
    files, folders = [], []
    for part in PARTS:
        top = os.path.join(old, part)
        if _is_link(top):
            raise MoveRefused("link", REFUSED_LINK.format(path=top))
        if os.path.isfile(top):
            files.append((part, os.path.getsize(top)))
            continue
        if not os.path.isdir(top):
            continue
        folders.append(part)
        for here, dirs, names in os.walk(top, onerror=_raise):
            for d in list(dirs):
                full = os.path.join(here, d)
                if _is_link(full):
                    raise MoveRefused("link", REFUSED_LINK.format(path=full))
                folders.append(os.path.relpath(full, old))
            for n in names:
                full = os.path.join(here, n)
                if _is_link(full):
                    raise MoveRefused("link", REFUSED_LINK.format(path=full))
                files.append((os.path.relpath(full, old), os.path.getsize(full)))
    return files, folders


def _copy_one(src, dst):
    """`src` -> `dst` with its times; -> the sha256 of what was read, and of the copy read back."""
    before = os.stat(src)
    read = hashlib.sha256()
    with open(src, "rb") as fin, open(dst, "xb") as fout:
        while True:
            chunk = fin.read(CHUNK)
            if not chunk:
                break
            read.update(chunk)
            fout.write(chunk)
        fout.flush()
        os.fsync(fout.fileno())
    shutil.copystat(src, dst)
    after = os.stat(src)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise MoveRefused("changed", CHANGED.format(path=src))
    back = hashlib.sha256()
    with open(dst, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            back.update(chunk)
    return read.hexdigest(), back.hexdigest()


def _journal_mode(conn):
    return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()


def _copy_db(old_db, new_db):
    """One database copied whole (SQLite's backup: consistent, its -wal folded in) to `new_db` in the journal mode it
    had (the stores are WAL: every reader and writer counts on it), checked — `integrity_check` ok, the same tables
    with the same row counts. A database already at `new_db` is set aside beside it first, never deleted. -> the set
    aside names. A failure leaves no temp file."""
    os.makedirs(os.path.dirname(new_db), exist_ok=True)
    tmp = f"{new_db}.moving-{os.getpid()}"
    try:
        for suffix in ("", "-journal", "-wal", "-shm"):
            if os.path.exists(tmp + suffix):
                os.remove(tmp + suffix)
        src = sqlite3.connect(f"file:{old_db}?mode=ro", uri=True)
        try:
            mode = _journal_mode(src)
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
                ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
                if ok != "ok":
                    raise sqlite3.DatabaseError(f"the copy's check said {ok}")
                tables = [r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
                for t in tables:
                    q = f'SELECT COUNT(*) FROM "{t}"'
                    if src.execute(q).fetchone()[0] != dst.execute(q).fetchone()[0]:
                        raise sqlite3.DatabaseError(f"the copy's {t} differs")
                dst.execute("PRAGMA journal_mode=DELETE")      # one file to put in place: no -wal beside the temp
            finally:
                dst.close()
        finally:
            src.close()
        aside = _set_aside(new_db)
        os.replace(tmp, new_db)
    except BaseException:
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.remove(tmp + suffix)
            except OSError:
                pass
        raise
    conn = sqlite3.connect(new_db)
    try:
        if mode == "wal" and _journal_mode(conn) != "wal":
            if str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() != "wal":
                raise sqlite3.DatabaseError("the copy couldn't be put back in WAL mode")
    finally:
        conn.close()
    return aside


def _set_aside(path):
    """Whatever is at `path` (and its -wal / -shm) renamed `<name>.before-move-<stamp>`, never deleted."""
    aside = []
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            target = f"{path}{suffix}.before-move-{stamp}"
            os.rename(path + suffix, target)
            aside.append(target)
    return aside


def _keyed(library, lang):
    """[(role, path)] of the files the local data folder keeps under this library's key for `lang`: the library store
    and the kept text beside it (`token_index.kept_text_path`) — both named by the data folder's path."""
    from app import token_index
    data_dir = os.path.join(library, "data", lang)
    return [("store", _store_db(library, lang)), ("kept_text", token_index.kept_text_path(lang, data_dir))]


SIDECAR_SKIP = ("-wal", "-shm", "-journal", ".lock", ".wlock", ".part")


def _sidecars(db):
    """The store's own files beside `db` that belong to it and aren't the live database: its backups (`.bak.<stamp>`)
    and its damage record (`.damaged`) -> [name suffix]. Never a lock, a -wal / -shm or a temp file."""
    folder, base = os.path.split(db)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for name in names:
        if name.startswith(base + ".") and not name.endswith(SIDECAR_SKIP) and ".moving-" not in name \
                and ".before-move-" not in name and os.path.isfile(os.path.join(folder, name)):
            out.append(name[len(base):])
    return sorted(out)


def _carry(old, new):
    """Every language's keyed files carried to the new library's key (`_keyed`): each database whole (`_copy_db`),
    each sidecar as a checked copy -> the record's [{language, role, aside}]."""
    carried = []
    for lang in LANGUAGES:
        for (role, old_db), (_role, new_db) in zip(_keyed(old, lang), _keyed(new, lang)):
            if not os.path.exists(old_db):
                continue
            carried.append({"language": lang, "role": role, "aside": _copy_db(old_db, new_db)})
            for suffix in _sidecars(old_db):
                target = new_db + suffix
                if os.path.exists(target):
                    _set_aside(target)
                read, back = _copy_one(old_db + suffix, target)
                if read != back:
                    raise OSError(f"the copy of {old_db + suffix} didn't match it")
    return carried


# --- The move ----------------------------------------------------------------------------------------------------- #

def _wait_others(wait, cancel):
    deadline = time.monotonic() + max(0.0, float(wait))
    while True:
        others = locks.running_others()
        if not others or time.monotonic() >= deadline or (cancel is not None and cancel()):
            return others
        time.sleep(locks.POLL)


def _store_locks():
    from app import library_store
    taken = []
    for lang in LANGUAGES:
        db = library_store.library_db_path(lang, path_utils.get_data_path(lang))
        if not os.path.exists(db):
            continue
        lock = library_store.MaintenanceLock(db)
        if not lock.try_acquire():
            lock.close()
            for t in taken:
                t.close()
            raise MoveRefused("running", REFUSED_RUNNING.format(who="Surasura's library helper"))
        taken.append(lock)
    return taken


def _held(run, cancel=None, wait=WAIT):
    """`run()` with the library to itself: no update staged, PROFILE_MOVE taken (a starting program waits for it), no
    other Surasura program running (waited for `wait` s), Connect's lock and each store's maintenance lock held."""
    from app import library_store
    if library_store.update_staged():
        return _result("refused", "update", REFUSED_UPDATE)
    try:
        held = locks.take(locks.PROFILE_MOVE, VERB, wait=1.0)
    except locks.Busy:
        return _result("refused", "busy", REFUSED_BUSY)
    try:
        others = _wait_others(wait, cancel)
        if others:
            who = WHO.get(others[0].get("kind"), "Another Surasura program")
            return _result("refused", "running", REFUSED_RUNNING.format(who=who))
        try:
            connect = locks.take("connect", VERB)
        except locks.Busy:
            return _result("refused", "running", REFUSED_RUNNING.format(who="Connect"))
        try:
            stores = _store_locks()
            try:
                return run()
            finally:
                for lock in stores:
                    lock.close()
        finally:
            connect.release()
    except MoveRefused as e:
        return _result("refused", e.reason, e.words)
    finally:
        held.release()


def _free(folder):
    """Free bytes on `folder`'s drive (its nearest existing parent), or None when it can't be read."""
    while folder and not os.path.isdir(folder):
        parent = os.path.dirname(folder)
        if parent == folder:
            return None
        folder = parent
    try:
        return shutil.disk_usage(folder).free
    except OSError:
        return None


def _ours(folder):
    """Does `folder` hold only what a move puts there (the library's own parts)? A folder holding anything else is
    never removed as a leftover."""
    try:
        return all(name in PARTS for name in os.listdir(folder))
    except OSError:
        return False


def _clear_leftover(old):
    """A move a kill or a power cut stopped part way (its record `moving`, library.json still naming the old folder):
    its own copy — the staging folder, or the target it was renamed to — removed, so the next move can run. Only a
    folder holding nothing but the library's parts is removed; the record goes either way."""
    record = read_record()
    if not record or record.get("status") != MOVING or _key(str(record.get("from") or "")) != _key(old):
        return
    for key in ("staging", "to"):
        folder = record.get(key)
        if isinstance(folder, str) and folder and os.path.isdir(folder) and not _is_link(folder) and _ours(folder) \
                and not _inside(folder, old) and not _inside(old, folder):
            _remove_copy(folder, old)
    try:
        os.remove(record_path())
    except OSError:
        pass


def check_target(old, new):
    """Why `new` can't take the library from `old` (MoveRefused), or None."""
    if _inside(new, old) or _inside(old, new):
        raise MoveRefused("inside", REFUSED_INSIDE.format(target=new))
    if cfa.at_risk(new):
        raise MoveRefused("protected", REFUSED_PROTECTED.format(target=new))
    if os.path.lexists(new) and not (os.path.isdir(new) and not _is_link(new) and not os.listdir(new)):
        raise MoveRefused("not_empty", REFUSED_NOT_EMPTY.format(target=new))


def move(new=None, progress=None, cancel=None, wait=WAIT):
    """Move this install's library to `new` (default `cfa.move_target()`) -> {status, reason, words, old, new,
    files, bytes}. `status`: done; refused (nothing done); cancelled or failed (nothing switched: the copy removed).
    `progress(done, total)` per file; `cancel()` -> True stops between files."""
    old = path_utils.installed_library()
    if not old:
        return _result("refused", "not_installed", REFUSED_NOT_INSTALLED)
    new = os.path.abspath(new or cfa.move_target())
    out = _held(lambda: _move(old, new, progress, cancel), cancel, wait)
    out.setdefault("old", old)
    out.setdefault("new", new)
    return out


def _move(old, new, progress, cancel):
    _clear_leftover(old)
    check_target(old, new)
    if not os.path.isdir(old):
        from app.services import first_run
        if first_run._seen(old) is not None:           # seen here before: offline (a drive, a cloud folder), not new
            raise MoveRefused("missing", REFUSED_MISSING.format(old=old))
    files, folders = plan(old) if os.path.isdir(old) else ([], [])
    total = len(files)
    need = sum(size for _rel, size in files)
    free = _free(os.path.dirname(new))
    if free is not None and free < need + ROOM_SPARE:
        raise MoveRefused("room", REFUSED_ROOM.format(target=new, need=-(-(need + ROOM_SPARE) // 2**20),
                                                      free=free // 2**20))
    staging = f"{new}.moving-{time.strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(os.path.dirname(staging), exist_ok=True)
    os.mkdir(staging)                                  # never an existing folder: only ever Surasura's own copy
    switched = False
    placed = False
    try:
        _write_json(record_path(), {"version": RECORD_VERSION, "status": MOVING, "from": old, "to": new,
                                    "staging": staging, "started": _now()})
        for rel in folders:
            os.makedirs(os.path.join(staging, rel), exist_ok=True)
        size = 0
        for done, (rel, _size) in enumerate(files, 1):
            if cancel is not None and cancel():
                return _result("cancelled", "cancelled", CANCELLED.format(old=old))
            read, back = _copy_one(os.path.join(old, rel), os.path.join(staging, rel))
            if read != back:
                return _result("failed", "mismatch", MISMATCH.format(path=os.path.join(old, rel), old=old))
            size += _size
            if progress is not None:
                progress(done, total)
        for rel in folders:                            # the folders' own times, once their files are in
            try:
                shutil.copystat(os.path.join(old, rel), os.path.join(staging, rel))
            except OSError:
                pass
        if os.path.isdir(new):
            os.rmdir(new)                              # empty (check_target): the copy takes its place
        os.rename(staging, new)
        placed = True
        try:
            stores = _carry(old, new)
        except (OSError, sqlite3.Error) as e:
            raise _Failed("store", STORE_FAILED.format(error=e, old=old)) from None
        try:
            _write_note(new)
            switched = True
        except OSError as e:
            raise _Failed("note", NOTE_FAILED.format(error=e)) from None
        _after_switch(old, new, total, size, stores)
        return _result("done", None, MOVED.format(new=new, old=old), files=total, bytes=size)
    except _Failed as e:
        return _result("failed", e.reason, e.words)
    except MoveRefused:
        raise
    except OSError as e:
        return _result("failed", "copy", FAILED.format(error=e, old=old))
    finally:
        if not switched:
            _remove_copy(new if placed else staging, old)
            try:
                os.remove(record_path())               # (the in-progress record: this move's own)
            except OSError:
                pass


class _Failed(Exception):
    def __init__(self, reason, words):
        super().__init__(words)
        self.reason = reason
        self.words = words


def _remove_copy(folder, old):
    """A move that didn't switch: its own copy removed (the original is untouched and still the library). A file the
    copy kept read-only (its original's attribute) is made writable first."""
    if not folder or _inside(folder, old) or _inside(old, folder) or not os.path.isdir(folder) or _is_link(folder):
        return

    def writable(func, path, _info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    shutil.rmtree(folder, onerror=writable)


def _after_switch(old, new, files, size, stores):
    """The record Undo reads, and the start gate's note (the new library seen here). Neither fails the move."""
    from app.services import first_run
    try:
        seen = first_run.read_note()["libraries"].get(first_run._key(old)) or {}
        first_run.record(new, fresh=bool(isinstance(seen, dict) and seen.get("fresh")))
    except Exception as e:
        print(f"Move my library: the start gate's note wasn't written ({e}).")
    try:
        _write_json(record_path(), {"version": RECORD_VERSION, "status": DONE, "from": old, "to": new,
                                    "moved": _now(), "files": files, "bytes": size, "stores": stores,
                                    "undone": None})
    except OSError as e:
        print(f"Move my library: its record wasn't written ({e}); Undo won't be offered.")


def can_undo():
    """The last move's record when Undo still applies (done, not undone, library.json names its new folder), else
    None."""
    record = read_record()
    library = path_utils.installed_library()
    if not record or record.get("status") != DONE or record.get("undone") or not library \
            or not isinstance(record.get("to"), str) or not isinstance(record.get("from"), str) \
            or _key(record["to"]) != _key(library):
        return None
    return record


def undo(wait=WAIT):
    """The last move undone -> {status, reason, words, old, new, aside}: library.json names the old folder again
    (still there, as it was) and the new folder is renamed aside, never deleted (anything saved there since stays).
    With the library to itself, as the move (`_held`): nothing writes the new folder while it is set aside."""
    record = can_undo()
    if record is None:
        return _result("refused", "none", UNDO_NONE)
    return _held(lambda: _undo(record), None, wait)


def _undo(record):
    old, new = record["from"], record["to"]
    try:
        _write_note(old)
    except OSError as e:
        return _result("failed", "note", NOTE_FAILED.format(error=e), old=old, new=new)
    aside, error = f"{new} (moved back {time.strftime('%Y-%m-%d %H%M%S')})", None
    try:
        os.rename(new, aside)
    except OSError as e:
        aside, error = None, e
    try:
        _write_json(record_path(), dict(record, undone=_now(), aside=aside))
    except OSError as e:
        print(f"Move my library: its record wasn't marked undone ({e}).")
    words = UNDONE.format(old=old, aside=aside) if aside else UNDONE_KEPT.format(old=old, new=new, error=error)
    return _result("done", None, words, old=old, new=new, aside=aside)
