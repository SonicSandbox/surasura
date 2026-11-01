"""*Start over completely* and *Put back* a Started-over backup (Fresh library, 3.0.1; the spec §4, §6.3–6.5, P1–P16).

Qt-free, light imports: the start gate runs it before anything opens the library.

**The request** (`request`): the window writes this install's journal, `profile-move.json` (status `asked`), then
restarts. Nothing moves until the restart's own start runs it (`run`, from the start gate; P16): a request found on
any other start is asked about first, never run unasked (the gate's, with `pending()`).

**The move** (`run`): refused, nothing moved, while an update is staged, another move runs (PROFILE_MOVE), another
install shares this data name's places (`installs.json`, P14), or another Surasura program is alive (its running mark,
waited for up to `wait` s first: Connect, the command line, Piyo's server, another sign-in's window — P5, P13). Then it
takes PROFILE_MOVE, `connect` and each store's maintenance lock and holds them to the end. Every entry
`path_utils.profile_parts()` marks MOVES is renamed into a `Backups/start-over-<stamp>/` folder inside its own place
(P1): never copied, never deleted (P2). The record (`start-over.json`, in the library folder's backup) and the journal
(`moving`, every move) are written before the first rename; each rename is recorded before it begins; the places in a
fixed order (install → roaming → local → library). A rename refused → every rename done undone, newest first, and
`refused` with the part that was held. All renamed → the journal `done` (the commit point), the records, the journal
gone; a network opt-out of the moved settings carried into a new settings.json (P7, F1).

**Put back** (`request(PUT_BACK, backup)`): one journal — first the live profile set aside into a backup of its own
(kind `put-back-over`), then the chosen backup's parts renamed back where they were, worked out from each part's place
and path (never an absolute path: a library folder moved since still works). Checked before the first rename: every
part there, every place it goes back to free, a backup from a newer Surasura refused. After it, each store put back
gets a new store_id and epoch + 1 and a fresh JSON copy (P4; `library_store.renew_after_put_back`).

**A kill at any step** (`recover`, at the next start, before the window): a journal still `moving` is rolled back —
every rename it began undone, newest first (P10, never forward); one that can't be (a file opened meanwhile) keeps the
journal and says which part, so the window never opens on a half-moved profile. A journal `done` is finished forward
(its records), `undone` its records written.

`backups()` lists both kinds of backup for the sheet (Started over here, Sorted again from each language's `.trash`);
`backup_size()` is a worker's.
"""
import json
import os
import time

from app import locks, path_utils

JOURNAL = path_utils.PROFILE_JOURNAL
RECORD = "start-over.json"
PREFIX = "start-over-"
START_OVER, PUT_BACK = "start-over", "put-back"                 # the journal's actions
ASKED, MOVING, DONE, UNDONE = "asked", "moving", "done", "undone"
KIND_START_OVER, KIND_PUT_BACK_OVER = "start-over", "put-back-over"     # a record's kind
STARTED, PUT_BACK_DONE = "started", "put-back"                  # a record's statuses (with DONE, UNDONE)
SORTED_AGAIN, STARTED_OVER, PUT_BACK_OVER = "sorted-again", "started-over", "put-back-over"   # the sheet's kinds
WAIT = 30.0             # s: the gate waits this long for another Surasura program (Connect…) to end (P5)
NETWORK_OPT_OUTS = ("telemetry_enabled", "update_check_enabled", "auto_update_enabled")   # carried when off (P7, F1)
LANGUAGES = ("ja", "zh")

# Why a move didn't run (nothing changed), in the window's words; the gate shows them (Mado tunes them)
REFUSED_UPDATE = "An update is being installed: try again once it has finished. Nothing was changed."
REFUSED_BUSY = "Another Start over or Put back is running. Nothing was changed."
REFUSED_RUNNING = "{who} is still running: close it, then try again. Nothing was changed."
REFUSED_INSTALL = ("Another Surasura on this PC keeps its files in the same place ({path}): Start over would take its "
                   "files too. Nothing was changed.")
REFUSED_HELD = "Start over didn't run: {what} had a file open. Nothing was changed."
REFUSED_NEWER = "Made by a newer Surasura ({version}): update first."
REFUSED_MISSING = "Part of this backup is missing ({what}): nothing was put back."
REFUSED_TAKEN = "{what} is in the way of putting this backup back: nothing was put back."
REFUSED_GONE = "This backup can't be read ({why}): nothing was put back."
REFUSED_JOURNAL = "Nothing was changed: {why}"
STUCK = "{what} couldn't be put back where it was: close whatever has it open, then try again."
UNREADABLE = "The record of a Start over or Put back can't be read ({path}): nothing was moved."
WHO = {"window": "Surasura's window (in another sign-in?)", "cli": "Surasura's command line", "mcp": "Piyo's helper",
       "connect": "Connect"}
WHAT = {"user_files": "your known words and lists", "data": "your library's copies", "results": "your list and report",
        "settings": "your settings", "token_store": "a word store", "patterns": "パターン", "koe_key": "Koe",
        "koe_usage": "Koe", "reports": "your saved reports", "connect": "Connect's records",
        "library_store": "your library", "covers": "the covers", "window_state": "the window's own files",
        "window_cache": "the window's own files", "window_pending": "the window's own files",
        "needs_seen": "the window's own files"}


class MoveRefused(Exception):
    """A move refused before anything was renamed: `reason` (a short code), `words` (the window's), `part` and
    `holder` when known."""

    def __init__(self, reason, words, part=None, holder=None):
        super().__init__(words)
        self.reason, self.words, self.part, self.holder = reason, words, part, holder


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _app_version():
    try:
        from app import __version__
        return __version__
    except Exception:
        return None


def _version(text):
    """'3.0.1' -> (3, 0, 1); anything else -> ()."""
    out = []
    for piece in str(text or "").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def _write_json(path, data):
    """`.tmp` + fsync + replace: whole or as it was."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("not a record")
    return data


# --- The journal and the request ----------------------------------------------------------------------------------- #

def journal_path():
    return os.path.join(path_utils.get_local_data_path(), JOURNAL)


def pending():
    """This install's journal, or None: {action, status (asked | moving | done | undone), …}; {"status":
    "unreadable", "path"} for a file there that can't be read (never guessed at)."""
    path = journal_path()
    try:
        return _read_json(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"status": "unreadable", "path": path}


def request(action, backup=None):
    """The learner asked to start over (`START_OVER`) or to put back the Started-over backup `backup` (its stamp, the
    folder's name after PREFIX): the journal written (`asked`) for the restart's start to run -> the journal. Refused
    (`MoveRefused`, nothing written) while an update is staged, a move is in flight, or the journal can't be written
    (REFUSED_JOURNAL with why: the window then never restarts)."""
    if action not in (START_OVER, PUT_BACK) or (action == PUT_BACK and not backup):
        raise ValueError(f"not a move: {action!r} {backup!r}")
    from app import library_store
    if library_store.update_staged():
        raise MoveRefused("update", REFUSED_UPDATE)
    now = pending()
    if now is not None and now.get("status") != ASKED:
        raise MoveRefused("busy", REFUSED_BUSY)
    journal = {"action": action, "status": ASKED, "asked_at": _now(), "app_version": _app_version(),
               "backup": backup if action == PUT_BACK else None}
    try:
        _write_json(journal_path(), journal)
    except OSError as e:
        raise MoveRefused("journal", REFUSED_JOURNAL.format(why=e)) from e
    return journal


def cancel_request():
    """An `asked` request taken back (the restart never came: said in the window; or the learner's *No* at the gate)
    -> True when one was taken back. A move in flight is never taken back here. Never raises."""
    now = pending()
    if not now or now.get("status") != ASKED:
        return False
    try:
        os.remove(journal_path())
        return True
    except OSError:
        return False


def _clear_journal():
    try:
        os.remove(journal_path())
    except FileNotFoundError:
        pass


# --- Plans: what moves where ------------------------------------------------------------------------------------- #

def _path(places, place, rel):
    folder = places.get(place)
    return None if folder is None else os.path.join(folder, *rel.split("/"))


def _stamp(places):
    """A stamp no place's Backups folder has yet."""
    base = time.strftime("%Y%m%d-%H%M%S")
    stamp, n = base, 1
    while any(os.path.lexists(os.path.join(folder, path_utils.BACKUPS, PREFIX + stamp)) for folder in places.values()):
        stamp = f"{base}-{n}"
        n += 1
    return stamp


def _aside(stamp, rel):
    return f"{path_utils.BACKUPS}/{PREFIX}{stamp}/{rel}"


def _plan_aside(places, stamp):
    """Every part that MOVES -> its move into `Backups/start-over-<stamp>/` of its own place, in the places' order."""
    return [{"place": p["place"], "role": p["role"], "rel": p["rel"], "src": p["rel"], "dst": _aside(stamp, p["rel"]),
             "unlisted": p["unlisted"], "begun": False}
            for p in path_utils.profile_parts(places) if p["start_over"] == path_utils.MOVES]


def record_path(stamp, places=None):
    places = places or path_utils.profile_places()
    return os.path.join(places["library"], path_utils.BACKUPS, PREFIX + stamp, RECORD)


def _plan_back(places, stamp, aside):
    """The chosen backup's parts back where they were -> (record, moves); refused (MoveRefused) when its record can't
    be read, it isn't a finished backup, it comes from a newer Surasura, a part is missing, or a place a part goes back
    to is taken by something the live profile's own setting-aside doesn't clear."""
    try:
        record = _read_json(record_path(stamp, places))
    except (OSError, ValueError) as e:
        raise MoveRefused("gone", REFUSED_GONE.format(why=e)) from e
    if record.get("status") != DONE:
        raise MoveRefused("gone", REFUSED_GONE.format(why=f"its status is {record.get('status')!r}"))
    mine, theirs = _version(_app_version()), _version(record.get("app_version"))
    if mine and theirs > mine:
        raise MoveRefused("newer", REFUSED_NEWER.format(version=record.get("app_version")))
    freed = {os.path.normcase(_path(places, m["place"], m["src"])) for m in aside}
    moves = []
    for m in record.get("moves") or ():
        try:
            place, rel, dst = m["place"], m["rel"], m["dst"]
        except (KeyError, TypeError):
            raise MoveRefused("gone", REFUSED_GONE.format(why="a part without its place")) from None
        here, there = _path(places, place, dst), _path(places, place, rel)
        what = WHAT.get(m.get("role"), rel)
        if here is None or not os.path.lexists(here):
            raise MoveRefused("missing", REFUSED_MISSING.format(what=what), part=m)
        if os.path.lexists(there) and os.path.normcase(there) not in freed:
            raise MoveRefused("taken", REFUSED_TAKEN.format(what=what), part=m)
        moves.append({"place": place, "role": m.get("role"), "rel": rel, "src": dst, "dst": rel,
                      "unlisted": bool(m.get("unlisted")), "begun": False, "back": True})
    return record, moves


# --- Holders ------------------------------------------------------------------------------------------------------- #

def other_install():
    """P14: another install named in `installs.json` whose library folder and program are still there (it shares
    this data name's roaming and local places) -> its library folder, else None."""
    mine = os.path.normcase(os.path.realpath(path_utils.get_user_data_path()))
    for entry in path_utils.read_install_note():
        root, exe = entry.get("data_root"), entry.get("exe")
        if not isinstance(root, str) or not isinstance(exe, str):
            continue
        if os.path.normcase(os.path.realpath(root)) == mine:
            continue
        if os.path.isdir(root) and os.path.isfile(exe):
            return root
    return None


def _wait_others(wait, on_wait, cancel):
    """Every other Surasura program's running mark, waited for up to `wait` s -> [] once none is held, else the
    holders still there."""
    deadline = time.monotonic() + max(0.0, float(wait))
    told = False
    while True:
        others = locks.running_others()
        if not others or time.monotonic() >= deadline or (cancel is not None and cancel.is_set()):
            return others
        if not told and on_wait is not None:
            told = True
            on_wait(others)
        time.sleep(locks.POLL)


def _store_locks(token):
    """Each store of this install that exists, its maintenance lock taken -> the locks; one held (the helper) ->
    MoveRefused, the ones taken let go."""
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


# --- The move ------------------------------------------------------------------------------------------------------ #

def run(wait=WAIT, on_wait=None, cancel=None, _step=None, _rename=None):
    """Run this install's journal (the start gate, the restart's own start or the learner's yes) -> {status, reason,
    words, part, holder, backup}. `status`: "none" (no journal), "done", "refused" (nothing moved; the request kept for
    *Try again*), "undone" (a rename was refused: every one done undone; the request cleared), "stuck" (a rename
    couldn't be undone: the journal kept, `words` names the part), "rolled-back" (a journal a kill left `moving`,
    `recover`'s). `on_wait(holders)` once while another program is waited for; `cancel` (an Event) ends the wait.
    `_step(name)` (tests) after each step; `_rename` (tests) replaces `os.rename`."""
    journal = pending()
    if journal is None:
        return _result("none")
    status = journal.get("status")
    if status == "unreadable":
        return _result("refused", "unreadable", UNREADABLE.format(path=journal.get("path")))
    if status in (MOVING, DONE, UNDONE):
        return recover(_step=_step, _rename=_rename)
    if status != ASKED:
        return _result("refused", "unreadable", UNREADABLE.format(path=journal_path()))
    try:
        return _run(journal, wait, on_wait, cancel, _step or (lambda _name: None), _rename or os.rename)
    except MoveRefused as e:
        return _result("refused", e.reason, e.words, part=e.part, holder=e.holder)


def _result(status, reason=None, words=None, part=None, holder=None, backup=None):
    return {"status": status, "reason": reason, "words": words, "part": part, "holder": holder, "backup": backup}


def _run(journal, wait, on_wait, cancel, step, rename):
    from app import library_store
    if library_store.update_staged():
        raise MoveRefused("update", REFUSED_UPDATE)
    token = object()
    held = []
    try:
        try:
            held.append(locks.take(locks.PROFILE_MOVE, "Setting your old Surasura aside", owner=token))
        except locks.Busy as e:
            raise MoveRefused("busy", REFUSED_BUSY, holder=e.holder) from None
        other = other_install()
        if other:
            raise MoveRefused("install", REFUSED_INSTALL.format(path=other))
        others = _wait_others(wait, on_wait, cancel)
        if others:
            who = WHO.get(others[0].get("kind"), "Another Surasura program")
            raise MoveRefused("running", REFUSED_RUNNING.format(who=who), holder=others[0])
        try:
            held.append(locks.take("connect", "Setting your old Surasura aside", owner=token))
        except locks.Busy as e:
            raise MoveRefused("running", REFUSED_RUNNING.format(who="Connect"), holder=e.holder) from None
        stores = _store_locks(token)
        try:
            return _move(journal, step, rename)
        finally:
            for lock in stores:
                lock.close()
    finally:
        for h in reversed(held):
            h.release()


def _move(journal, step, rename):
    places = path_utils.profile_places()
    stamp = _stamp(places)
    moves = _plan_aside(places, stamp)
    back = None
    if journal["action"] == PUT_BACK:
        back, back_moves = _plan_back(places, journal["backup"], moves)
        moves = moves + back_moves
    kind = KIND_PUT_BACK_OVER if back is not None else KIND_START_OVER
    record = {"kind": kind, "status": STARTED, "stamp": stamp, "started_at": _now(), "app_version": _app_version(),
              "moves": [{k: m[k] for k in ("place", "role", "rel", "dst", "unlisted")}
                        for m in moves if not m.get("back")],
              "how_to_put_back": "Close Surasura. Move every part back from Backups/start-over-<stamp>/ inside its own "
                                 "place to the same path in that place."}
    if back is not None:
        record["put_back_of"] = journal["backup"]
    where = record_path(stamp, places)
    try:
        _write_json(where, record)
        journal = dict(journal, status=MOVING, stamp=stamp, record=where, moving_at=_now(), moves=moves)
        _write_json(journal_path(), journal)
    except OSError as e:
        _forget_folders(places, stamp)
        _clear_record(where)
        raise MoveRefused("journal", REFUSED_JOURNAL.format(why=e)) from e
    step("planned")
    for n, move in enumerate(moves):
        move["begun"] = True                            # recorded before it begins (H1): a kill here is undone too
        _write_json(journal_path(), journal)
        src, dst = _path(places, move["place"], move["src"]), _path(places, move["place"], move["dst"])
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.lexists(dst):
                raise FileExistsError(dst)
            rename(src, dst)
        except OSError as e:
            print(f"Start over: {move['rel']} couldn't be moved ({e!r}); undoing")
            stuck = _undo(journal, places, rename)
            if stuck:
                return _result("stuck", "stuck", STUCK.format(what=WHAT.get(stuck["role"], stuck["rel"])), part=stuck)
            _settle(journal, places, UNDONE, held=move)
            return _result("undone", "held", REFUSED_HELD.format(what=WHAT.get(move["role"], move["rel"])), part=move)
        step(f"moved:{n}")
    journal["status"] = DONE                            # the commit point: from here on it is finished forward
    journal["done_at"] = _now()
    _write_json(journal_path(), journal)
    step("committed")
    return _finish(journal, places, step)


def _undo(journal, places, rename):
    """Every move the journal began, undone newest first -> None, or the first move that couldn't be (left as it is:
    the journal stays for *Try again*)."""
    for move in reversed(journal.get("moves") or ()):
        if not move.get("begun"):
            continue
        src, dst = _path(places, move["place"], move["src"]), _path(places, move["place"], move["dst"])
        if src is None or dst is None:
            return move
        if not os.path.lexists(dst):
            move["begun"] = False                       # never got there: still in its place
            continue
        if os.path.lexists(src):
            return move                                 # something new in its place: never written over
        try:
            rename(dst, src)
        except OSError as e:
            print(f"Start over: {move['rel']} couldn't be put back ({e!r})")
            try:
                _write_json(journal_path(), journal)
            except OSError:
                pass
            return move
        move["begun"] = False
        try:
            _write_json(journal_path(), journal)
        except OSError:
            pass
    return None


def recover(_step=None, _rename=None):
    """A journal a kill left behind, at the next start (before the window opens anything) -> `run`'s answer:
    "rolled-back" (a `moving` one undone; the window says *Start over was stopped part way; everything is as it
    was*), "stuck" (a rename that couldn't be undone: the journal kept), "done" (a `done` one finished forward),
    "undone", "none"."""
    journal = pending()
    if journal is None:
        return _result("none")
    places = path_utils.profile_places()
    status = journal.get("status")
    if status == MOVING:
        stuck = _undo(journal, places, _rename or os.rename)
        if stuck:
            return _result("stuck", "stuck", STUCK.format(what=WHAT.get(stuck.get("role"), stuck.get("rel"))),
                           part=stuck)
        _settle(journal, places, UNDONE)
        return _result("rolled-back", "stopped")
    if status == DONE:
        return _finish(journal, places, _step or (lambda _name: None))
    if status == UNDONE:
        _settle(journal, places, UNDONE)
        return _result("undone")
    return _result("none")


def _settle(journal, places, status, held=None):
    """An undone move's end: the journal `undone`, its record `undone` (with the part that was held), the backup
    folders it made and left empty taken away again, the journal gone."""
    try:
        journal["status"] = status
        _write_json(journal_path(), journal)
    except OSError:
        pass
    where = journal.get("record")
    try:
        record = _read_json(where)
        record.update(status=UNDONE, undone_at=_now())
        if held is not None:
            record["held"] = {"place": held["place"], "role": held["role"], "rel": held["rel"]}
        _write_json(where, record)
    except (OSError, ValueError, TypeError):
        pass
    _forget_folders(places, journal.get("stamp"), keep=where)
    _clear_journal()


def _forget_folders(places, stamp, keep=None):
    """A backup that never happened: its empty folders taken away (`keep`'s folder, the record, stays). Never
    raises; never removes a file."""
    if not stamp:
        return
    for folder in places.values():
        top = os.path.join(folder, path_utils.BACKUPS, PREFIX + stamp)
        if keep and os.path.normcase(os.path.dirname(keep)) == os.path.normcase(top):
            continue
        for where, _dirs, _names in sorted(os.walk(top, topdown=False), key=lambda w: -len(w[0])):
            try:
                os.rmdir(where)
            except OSError:
                pass
        try:
            os.rmdir(os.path.join(folder, path_utils.BACKUPS))
        except OSError:
            pass


def _clear_record(where):
    try:
        os.remove(where)
        os.rmdir(os.path.dirname(where))
    except OSError:
        pass


def _finish(journal, places, step):
    """After the commit point: the records, the opt-outs carried (a Start over) or the stores renewed (a Put back),
    the journal gone. Each step best-effort, logged: the move stands."""
    stamp, back = journal.get("stamp"), journal.get("backup")
    where = journal.get("record") or record_path(stamp, places)
    try:
        record = _read_json(where)
        record.update(status=DONE, finished_at=_now())
        if journal["action"] == START_OVER:
            record["carried"] = _carry_opt_outs(places, record)
        _write_json(where, record)
    except Exception as e:
        print(f"Start over: its record couldn't be finished ({e!r}); everything moved")
    step("record")
    if journal["action"] == PUT_BACK and back:
        try:
            chosen = _read_json(record_path(back, places))
            chosen.update(status=PUT_BACK_DONE, put_back_at=_now(), put_back_over=stamp)
            _write_json(record_path(back, places), chosen)
        except Exception as e:
            print(f"Put back: the backup's record couldn't be marked put back ({e!r}); everything moved")
        _renew_stores(places, stamp)
        step("renewed")
    _clear_journal()
    step("cleared")
    return _result("done", backup=stamp)


def _carry_opt_outs(places, record):
    """P7 / F1: every network opt-out (`NETWORK_OPT_OUTS` off) of the settings.json just set aside written into a new
    settings.json, those keys only — the learner's own choice, never a new one -> what was carried ({} when none).
    A settings file that isn't there or can't be read carries nothing."""
    target = path_utils.get_settings_path()
    for move in record.get("moves") or ():
        if move.get("role") != "settings":
            continue
        moved = _path(places, move["place"], move["dst"])
        if os.path.normcase(_path(places, move["place"], move["rel"])) != os.path.normcase(target):
            continue
        try:
            with open(moved, "r", encoding="utf-8-sig") as f:
                old = json.load(f)
        except (OSError, ValueError):
            return {}
        carried = {k: False for k in NETWORK_OPT_OUTS if isinstance(old, dict) and old.get(k) is False}
        if carried and not os.path.exists(target):
            _write_json(target, carried)
        return carried
    return {}


def _renew_stores(places, stamp):
    """P4 after a Put back: each store put back gets a new store_id, epoch + 1 and a fresh JSON copy (Connect's jobs
    queued since drop; every window reads it in full). Best-effort, logged."""
    from app import library_store
    for lang in LANGUAGES:
        data_dir = path_utils.get_data_path(lang)
        if not os.path.exists(library_store.library_db_path(lang, data_dir)):
            continue
        try:
            library_store.renew_after_put_back(lang, data_dir, path_utils.get_user_files_path(lang))
        except Exception as e:
            print(f"Put back: the {lang} library couldn't be given a new id ({e!r}); the next full read finds it")


# --- The backups, for the sheet ------------------------------------------------------------------------------------ #

def backups(places=None):
    """Every backup there is to put back, newest first, a stopped one before the rest -> [{kind (SORTED_AGAIN,
    STARTED_OVER, PUT_BACK_OVER: the sheet's *Sorted again* / *Started over* / *Put back over*), scope ("library": one
    language's, put back in the running window, `library_store.put_back_library`; "profile": everything, put back by a
    restart, `request(PUT_BACK, stamp)`), folder, stamp, date, status, stopped (a crash stopped it part way: *Put it
    back*), language (a library's), app_version, forgot_known (a 3.0 backup made with *Also forget my known words*:
    P9)}]. Reads folders and records only; a record that can't be read is left out, and so is a backup already put
    back or one that never happened (undone)."""
    places = places or path_utils.profile_places()
    out = []
    journal = pending() or {}
    root = os.path.join(places["library"], path_utils.BACKUPS)
    try:
        names = sorted(n for n in os.listdir(root) if n.startswith(PREFIX))
    except OSError:
        names = []
    for name in names:
        try:
            record = _read_json(os.path.join(root, name, RECORD))
        except (OSError, ValueError):
            continue
        status = record.get("status")
        if status in (UNDONE, PUT_BACK_DONE):
            continue
        stamp = name[len(PREFIX):]
        stopped = status == STARTED and journal.get("stamp") != stamp
        kind = PUT_BACK_OVER if record.get("kind") == KIND_PUT_BACK_OVER else STARTED_OVER
        out.append({"kind": kind, "scope": "profile", "folder": os.path.join(root, name),
                    "stamp": stamp, "date": record.get("started_at"), "status": status, "stopped": stopped,
                    "language": None, "app_version": record.get("app_version"), "forgot_known": False})
    from app import library_store
    for lang in LANGUAGES:
        trash = os.path.join(path_utils.get_user_files_path(lang), ".trash")
        try:
            found = sorted(n for n in os.listdir(trash) if n.startswith(library_store.RESET_PREFIX))
        except OSError:
            continue
        for name in found:
            folder = os.path.join(trash, name)
            try:
                record = _read_json(os.path.join(folder, library_store.RESET_RECORD))
            except (OSError, ValueError):
                continue
            status = record.get("status")
            if status in (UNDONE, PUT_BACK_DONE):
                continue
            stopped = status == STARTED and any(os.path.lexists(str(m.get("to") or ""))
                                                for m in record.get("moves") or () if isinstance(m, dict))
            if status == STARTED and not stopped:
                continue                                # a kill before anything moved: nothing to put back
            kind = PUT_BACK_OVER if record.get("kind") == library_store.RESET_KIND_OVER else SORTED_AGAIN
            out.append({"kind": kind, "scope": "library", "folder": folder, "stamp": name,
                        "date": record.get("started_at"), "status": status, "stopped": stopped, "language": lang,
                        "app_version": record.get("app_version"), "forgot_known": bool(record.get("known"))})
    out.sort(key=lambda b: str(b["date"] or ""), reverse=True)
    out.sort(key=lambda b: not b["stopped"])
    return out


def backup_size(entry, places=None):
    """A backup's size in bytes (a worker's: it walks every file): a Started-over one across every place's
    `Backups/start-over-<stamp>/`, a Sorted-again one its folder. Links are never followed. Never raises."""
    places = places or path_utils.profile_places()
    if entry.get("language"):
        tops = [entry["folder"]]
    else:
        tops = [os.path.join(folder, path_utils.BACKUPS, PREFIX + entry["stamp"]) for folder in places.values()]
    total, seen = 0, set()
    for top in tops:
        key = os.path.normcase(os.path.abspath(top))
        if key in seen:
            continue
        seen.add(key)
        for where, dirs, names in os.walk(top):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(where, d))]
            for n in names:
                try:
                    total += os.lstat(os.path.join(where, n)).st_size
                except OSError:
                    pass
    return total
