"""*Install AnkiConnect for me* (3.0.1; Sonic's AC-1…AC-5, 2026-10-31; the spec and its probe: the 3.0 plan folder's
`tracks/window/work/ankiconnect-install/SPEC.md` + `probe.md`): Surasura downloads AnkiConnect from AnkiWeb — the
copy Anki's own *Get Add-ons…* gets for the learner's Anki — and puts it into Anki's add-ons folder as one new folder,
only while Anki is closed, only after the learner's yes. Windows only.

**The network call** (CLAUDE.md §1, the module-driven list; Sonic's AC-1 yes): one HTTPS GET
`https://ankiweb.net/shared/download/2055492159?v=2.1&p=<Anki's point version>` — the request Anki's add-on manager
makes (`aqt/addons.py download_addon`) — and the redirect AnkiWeb answers with, on `HOSTS` only (the probe: a 303 to
`/svc/shared/download-addon/…` on ankiweb.net itself). Sent: the add-on's number, Anki's version number, Surasura's
User-Agent; nothing about the learner. Never a retry loop, never in the background. Every byte comes through ONE
function, `_fetch`. AnkiWeb publishes no checksum (AC-2 A, a knowing exception to the approved-versions rule): what
comes is checked to look like AnkiConnect (`_check_zip`) and nothing more.

**The writes into Anki's folder** (every one): Surasura's own staging folder `<base>\\.surasura-ankiconnect\\`
(emptied first: a leftover of an install that died), the checked add-on unpacked into its `2055492159\\` with the
`meta.json` Anki writes for an AnkiWeb install, every file compared with the checked zip; then **one rename** of it
into `addons21\\2055492159` — only when no folder of that name is there (a rename never replaces), only while no Anki
runs; then the staging folder removed. Surasura removes only its own staging folder, and only inside an install.
Read, never written: the base folder, `prefs21.db` (Anki's version) and the add-ons' `meta.json` / `manifest.json`
names (is AnkiConnect there already, under any name?). Never another add-on's folder, a profile, a collection,
`prefs21.db`, Anki's program folder.

- `base()` — Anki's base folder: `ANKI_BASE` when set (Anki reads it too), else `%APPDATA%\\Anki2`; it counts only
  when Anki has run there (`prefs21.db`) and has its `addons21`. Never a search: a portable Anki (`-b`) isn't seen.
- `anki_version(base)` — the version Anki saved when it last ran (`prefs21.db`'s `_global` entry,
  `last_run_version`: Anki's point version, 26.9.2 -> 260902, 2.1.66 -> 66), read read-only through an unpickler that
  builds plain values only (any class refused: no code run). Never guessed.
- `look()` — (a worker) a few file checks, no network, no Anki call -> `{"state", "disabled"}`: `can-install` ·
  `there` (`disabled`: its `meta.json` says turned off) · `no-base` · `no-version` · `not-windows` · `off`
  (`DOWNLOAD_ENABLED` False). It never deletes.
- `install(on_progress, cancel, on_end, confirm, shown=None, on_phase=None)` — the route (blocking: a thread of its
  own, never the window's pool: it may wait 10 minutes for Anki to close) -> one of the results below; `on_end` told
  once. `install_as_job(registry, …)`: listed as an `ankiconnect-install` job from the yes until it ends.

Standard library only; no Qt, no Tk.
"""
import http.client
import io
import json
import os
import pickle
import shutil
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

CODE = "2055492159"                     # AnkiConnect on AnkiWeb (= `ankiconnect_addon.CODE`)
DOWNLOAD_ENABLED = True                 # the one switch (Sonic's AC-1 yes); False: no button, only *Copy code*
HOSTS = frozenset({"ankiweb.net"})      # the probe (2026-11-05): the download and its redirect, nothing else
DOWNLOAD = "https://ankiweb.net/shared/download/{code}?v=2.1&p={point}"
SIZE_CAP = 5 * 1024 * 1024              # AnkiConnect 2026-10 is 91 KB (the probe): far above, and no more
UNPACKED_CAP = 20 * 1024 * 1024         # 291 KB unpacked
ENTRY_CAP = 500                         # 14 entries
META_CAP = 1024 * 1024                  # an add-on's meta.json / manifest.json read for its name
TIMEOUT_S = 30                          # urllib's per-socket wait
CHUNK = 1 << 16
WAIT_EVERY = 2.0                        # s between looks at the process list while the waiting line shows (AC-3 A)
WAIT_FOR = 600.0                        # s: then *Close Anki, then press Install again*
STAGING = "ankiconnect-install"         # under local data: the download, emptied before, after and on every failure
ANKI_STAGING = ".surasura-ankiconnect"  # in Anki's base folder, beside addons21 (same volume: one rename)
RENAME_TRIES, RENAME_PAUSE = 3, 0.5    # a virus check holding the new files (WinError 5): twice more, 0.5 s apart
APPDATA_UNDER_TESTS = False             # under a test root only `ANKI_BASE` is read (a test of %APPDATA% sets this)

# look's states
CAN_INSTALL, THERE, NO_BASE, NO_VERSION, NOT_WINDOWS, OFF = (
    "can-install", "there", "no-base", "no-version", "not-windows", "off")
# install's results
INSTALLED, DECLINED, CANCELLED, BUSY = "installed", "declined", "cancelled", "busy"
OFFLINE, NO_BRANCH, BLOCKED, ALREADY, STAYED_OPEN, CANT_TELL, REFUSED, NOT_WRITTEN = (
    "offline", "no-branch", "blocked", "already", "stayed-open", "cant-tell", "refused", "not-written")
# the route's phases (`on_phase`)
WAITING, RUNNING = "waiting", "running"

_ONE_INSTALL = threading.Lock()         # one install at a time in the process (a second press is `busy`)

# The words every place shows (setup's Anki step, Settings › Anki & mining, Needs you: `app/qt/addon_steps.py`), as
# `ankiconnect_addon` holds Mado-A's (spec §7, worded again — PROVISIONAL)
BUTTON = "Install AnkiConnect for me"
BUTTON_TIP = ("Downloads the AnkiConnect add-on from AnkiWeb and adds it to Anki, so Surasura can talk to Anki.\n"
              "• It asks first, and waits for Anki to be closed")
SHEET_TITLE = "Install AnkiConnect?"
SHEET_BODY = ("Surasura downloads AnkiConnect from AnkiWeb (the add-on Anki itself uses) and adds it to Anki. "
              "Nothing else in Anki changes.")
SHEET_YES, SHEET_YES_TIP = "Install", "Download AnkiConnect from AnkiWeb and add it to Anki"
SHEET_NO, SHEET_NO_TIP = "Back", "Nothing is downloaded"
OR_YOURSELF = "Or add it in Anki yourself:"
WAITING_LINE = "Close Anki and Surasura installs AnkiConnect right away"
CANCEL, CANCEL_TIP = "Cancel", "Stop waiting: nothing is downloaded"
RUNNING_LINE = "Installing AnkiConnect…"
DONE_LINE = "AnkiConnect is installed"
DONE_ELSEWHERE = ("AnkiConnect is installed. It answers at 127.0.0.1:8765, but Surasura is set to {url} "
                  "(Settings › Anki & mining)")
OPEN, OPEN_TIP = "Open Anki", "Opens Anki. Surasura checks again by itself once AnkiConnect answers"
FAILED_LINE = "Couldn't install it for you: {reason}."
STAYED_OPEN_LINE = "Close Anki, then press Install again."
THERE_LINE = "AnkiConnect is in Anki but isn't answering: restart Anki"
TURNED_OFF_LINE = "AnkiConnect is turned off in Anki: Tools › Add-ons, select it, Toggle Enabled, restart Anki"
REASONS = {"offline": "couldn't reach AnkiWeb", "no-branch": "AnkiWeb has no AnkiConnect for this Anki",
           "blocked": "Windows blocked the file", "already": "AnkiConnect is already there",
           "cant-tell": "couldn't tell whether Anki is closed", "refused": "AnkiWeb's file didn't look like AnkiConnect",
           "not-written": "couldn't write AnkiConnect's files", "no-base": "open Anki once first",
           "no-version": "couldn't tell which Anki you have", "busy": "an install is already going",
           "off": "it can't be done on this computer"}


def said(result):
    """The line for a route's end, or None (installed: the done line; declined, cancelled: nothing to say)."""
    if result in (INSTALLED, DECLINED, CANCELLED):
        return None
    if result == STAYED_OPEN:
        return STAYED_OPEN_LINE
    return FAILED_LINE.format(reason=REASONS.get(result, REASONS["not-written"]))


class _Refused(Exception):
    """The route stops here; `result` is what the learner is told."""

    def __init__(self, result, why=""):
        super().__init__(why or result)
        self.result = result


# --------------------------------------------------------------------------- #
# Anki's folder and version
# --------------------------------------------------------------------------- #
def base():
    """Anki's base folder, or None when Anki hasn't run there (no `prefs21.db`) or it has no `addons21`."""
    named = os.environ.get("ANKI_BASE")
    if named:
        folder = os.path.abspath(os.path.expanduser(named))
    elif os.environ.get("SURASURA_TEST_ROOT") and not APPDATA_UNDER_TESTS:
        return None                     # a test (or a window it leaves open) never reads the real Anki's folder
    else:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        folder = os.path.join(appdata, "Anki2")
    if os.path.isfile(os.path.join(folder, "prefs21.db")) and os.path.isdir(os.path.join(folder, "addons21")):
        return folder
    return None


class _Plain(pickle.Unpickler):
    """Plain values only (dict, list, str, int, float, bool, None, bytes, tuple, set): any class is refused, so
    nothing in the file can run code."""

    def find_class(self, module, name):
        raise pickle.UnpicklingError(f"not a plain value: {module}.{name}")


def anki_version(folder):
    """Anki's point version from `prefs21.db` (the version it last ran as), or None. Read-only."""
    try:
        uri = "file:" + urllib.request.pathname2url(os.path.join(folder, "prefs21.db")) + "?mode=ro"
        db = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            row = db.execute("select cast(data as blob) from profiles where name = '_global'").fetchone()
        finally:
            db.close()
        meta = _Plain(io.BytesIO(row[0])).load() if row and row[0] else None
    except Exception:
        return None
    point = meta.get("last_run_version") if isinstance(meta, dict) else None
    return point if isinstance(point, int) and not isinstance(point, bool) and point > 0 else None


def _addons(folder):
    return os.path.join(folder, "addons21")


def _small_json(path):
    try:
        if os.path.getsize(path) > META_CAP:
            return None
        with open(path, encoding="utf-8") as f:
            found = json.load(f)
        return found if isinstance(found, dict) else None
    except (OSError, ValueError):
        return None


def _names_ankiconnect(text):
    return isinstance(text, str) and "ankiconnect" in "".join(c for c in text.lower() if c.isalnum())


def _present(folder):
    """AnkiConnect already in Anki's add-ons, under any folder name (two would fight over its port: P7)? ->
    None, or {"disabled": bool} (its meta.json says turned off)."""
    addons = _addons(folder)
    own = os.path.join(addons, CODE)
    try:
        names = os.listdir(addons)
    except OSError:
        names = []
    for name in ([CODE] if os.path.lexists(own) else []) + sorted(n for n in names if n != CODE):
        path = os.path.join(addons, name)
        if not os.path.isdir(path):
            continue
        meta = _small_json(os.path.join(path, "meta.json")) or {}
        manifest = _small_json(os.path.join(path, "manifest.json")) or {}
        if name == CODE or _names_ankiconnect(name) or _names_ankiconnect(meta.get("name")) \
                or _names_ankiconnect(manifest.get("name")) or _names_ankiconnect(manifest.get("package")):
            return {"disabled": meta.get("disabled") is True}
    if os.path.lexists(own):                # a file (or a link) of its name: the rename can't go there either
        return {"disabled": False}
    return None


def look():
    """(A worker.) When the button shows (module docstring) -> {"state", "disabled", "base", "point"}."""
    out = {"state": OFF, "disabled": False, "base": None, "point": None}
    if not DOWNLOAD_ENABLED:
        return out
    if sys.platform != "win32":
        out["state"] = NOT_WINDOWS
        return out
    try:
        folder = base()
        if folder is None:
            out["state"] = NO_BASE
            return out
        out["base"] = folder
        there = _present(folder)
        if there is not None:
            out.update(state=THERE, disabled=there["disabled"])
            return out
        out["point"] = anki_version(folder)
        out["state"] = CAN_INSTALL if out["point"] is not None else NO_VERSION
    except Exception:
        out["state"] = NO_BASE
    return out


# --------------------------------------------------------------------------- #
# The download
# --------------------------------------------------------------------------- #
def _ankiweb(url):
    try:
        parts = urllib.parse.urlsplit(str(url))
    except (TypeError, ValueError):
        return False
    return parts.scheme == "https" and (parts.hostname or "").lower() in HOSTS and not parts.username \
        and parts.port in (None, 443)


class _AnkiWebOnly(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to `HOSTS`, over https."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _ankiweb(newurl):
            raise urllib.error.HTTPError(newurl, code, "a redirect away from AnkiWeb", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url):
    """THE network function: the open response (a context manager), redirects followed only within `HOSTS`."""
    if not DOWNLOAD_ENABLED:
        raise _Refused(OFF, "the download isn't enabled")
    if not _ankiweb(url):
        raise _Refused(REFUSED, f"not AnkiWeb: {url}")
    from app import update_checker
    opener = urllib.request.build_opener(_AnkiWebOnly())
    return opener.open(urllib.request.Request(url, headers={"User-Agent": update_checker._USER_AGENT}),
                       timeout=TIMEOUT_S)


def _meta_of(url):
    """AnkiWeb's meta from the redirect's address (`t`, `minpt`, `maxpt`, `bidx`: what Anki's own
    `extract_meta_from_download_url` reads) -> dict, else _Refused."""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(str(url)).query)
    try:
        values = {key: int(query[key][0]) for key in ("t", "minpt", "maxpt", "bidx")}
    except (KeyError, IndexError, ValueError):
        raise _Refused(REFUSED, f"AnkiWeb's answer carries no add-on meta: {url}")
    return values


def _stopped(cancel):
    if cancel is None:
        return False
    try:
        return bool(cancel.is_set() if hasattr(cancel, "is_set") else cancel())
    except Exception:
        return False


def _download(point, path, on_progress, cancel):
    """Stream the add-on to `path` -> AnkiWeb's meta; _Refused on a foreign host, an error answer, the cap, a cancel."""
    url = DOWNLOAD.format(code=CODE, point=point)
    done = 0
    try:
        response = _fetch(url)
    except urllib.error.HTTPError as e:     # a redirect off AnkiWeb (`_AnkiWebOnly`), or AnkiWeb's own error
        result = REFUSED if e.code < 400 else NO_BRANCH if e.code in (404, 410) else OFFLINE
        raise _Refused(result, f"AnkiWeb answered {e.code}")
    except _Refused:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise _Refused(OFFLINE, str(e))
    with response:
        final = response.geturl()
        if not _ankiweb(final):
            raise _Refused(REFUSED, f"the download came from outside AnkiWeb: {final}")
        meta = _meta_of(final)
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        if total > SIZE_CAP:
            raise _Refused(REFUSED, f"the download is {total} bytes")
        try:
            with open(path, "wb") as out:
                while True:
                    if _stopped(cancel):
                        raise _Refused(CANCELLED)
                    try:
                        chunk = response.read(CHUNK)
                    except (OSError, http.client.HTTPException, ValueError) as e:     # the network, mid-download
                        if getattr(e, "winerror", None) == 225:                   # Windows' virus check
                            raise _Refused(BLOCKED, str(e))
                        raise _Refused(OFFLINE, str(e))
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > SIZE_CAP:
                        raise _Refused(REFUSED, "the download is larger than any AnkiConnect")
                    out.write(chunk)
                    if on_progress:
                        try:
                            on_progress(done, total or None)
                        except Exception:
                            pass
        except OSError as e:                # writing the download into Surasura's own folder
            raise _Refused(BLOCKED if getattr(e, "winerror", None) == 225 else NOT_WRITTEN, str(e))
    if total and done != total:
        raise _Refused(OFFLINE, f"{done} of {total} bytes came")
    return meta


# --------------------------------------------------------------------------- #
# What came, checked; then placed
# --------------------------------------------------------------------------- #
_DEVICES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"COM{i}" for i in range(10)}
                     | {f"LPT{i}" for i in range(10)})      # Windows' device names: never a file


def _entry_ok(info):
    name = info.filename
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return False
    parts = name.rstrip("/").split("/")
    if any(part in ("..", ".", "") for part in parts):
        return False
    if any(part.endswith((".", " ")) or part.split(".", 1)[0].upper().rstrip(" ") in _DEVICES for part in parts):
        return False                        # Windows drops a trailing dot or space; CON, aux.py: a device
    kind = (info.external_attr >> 16) & 0o170000
    return kind != 0o120000                 # never a link


def _check_zip(path):
    """The download is an add-on and looks like AnkiConnect: a zip with `__init__.py` at its root, every entry a
    plain path inside it (no absolute path, drive, `..` or link), at most `ENTRY_CAP` entries and `UNPACKED_CAP`
    bytes unpacked -> (its files' infos, its manifest dict), else _Refused."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > ENTRY_CAP:
                raise _Refused(REFUSED, f"{len(infos)} entries")
            if not all(_entry_ok(i) for i in infos):
                raise _Refused(REFUSED, "an entry outside the add-on")
            files = [i for i in infos if not i.is_dir()]
            if sum(i.file_size for i in files) > UNPACKED_CAP:
                raise _Refused(REFUSED, "too large unpacked")
            if len({i.filename for i in files}) != len(files) or "meta.json" in {i.filename for i in files}:
                raise _Refused(REFUSED, "a name twice, or a meta.json of its own")
            if "__init__.py" not in {i.filename for i in files}:
                raise _Refused(REFUSED, "no __init__.py at its root")
            manifest = {}
            if "manifest.json" in {i.filename for i in files}:
                try:
                    manifest = json.loads(z.read("manifest.json").decode("utf-8"))
                except ValueError:
                    manifest = {}
            return files, manifest if isinstance(manifest, dict) else {}
    except _Refused:
        raise
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError) as e:
        raise _Refused(REFUSED, f"not an add-on: {e}")


def add_on_meta(ankiweb, manifest):
    """The `meta.json` Anki writes for an AnkiWeb install (read from a real one, the probe): its name the add-on's
    own (the manifest's, as Anki keeps a packaged name), AnkiWeb's mod time and versions, on, updated by Anki."""
    name = manifest.get("name")
    conflicts = manifest.get("conflicts")
    return {"name": name if isinstance(name, str) and name.strip() else "AnkiConnect",
            "mod": ankiweb["t"], "min_point_version": ankiweb["minpt"], "max_point_version": ankiweb["maxpt"],
            "branch_index": ankiweb["bidx"], "disabled": False,
            "conflicts": [c for c in conflicts if isinstance(c, str)] if isinstance(conflicts, list) else [],
            "update_enabled": True}


def _unpack(zip_path, files, folder, meta):
    """Every file into `folder` (new), counted as it comes; `meta.json` beside them; then each compared with the zip."""
    os.makedirs(folder)
    written = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in files:
            target = os.path.join(folder, *info.filename.split("/"))
            if os.path.commonpath([os.path.realpath(folder), os.path.realpath(target)]) != os.path.realpath(folder):
                raise _Refused(REFUSED, f"outside the add-on: {info.filename}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > UNPACKED_CAP:
                        raise _Refused(REFUSED, "too large unpacked")
                    out.write(chunk)
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as out:
            json.dump(meta, out)
        for info in files:
            with open(os.path.join(folder, *info.filename.split("/")), "rb") as f:
                if f.read() != z.read(info):
                    raise _Refused(NOT_WRITTEN, f"{info.filename} isn't what came")
    on_disk = {os.path.relpath(os.path.join(root, f), folder).replace(os.sep, "/")
               for root, _dirs, names in os.walk(folder) for f in names}
    if on_disk != {i.filename for i in files} | {"meta.json"}:
        raise _Refused(NOT_WRITTEN, "the folder holds more than the add-on")


def staging_folder():
    from app import path_utils
    return os.path.join(path_utils.get_local_data_path(), STAGING)


def _remove(folder):
    try:
        shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass


def _running():
    from app.connect import open_anki
    return open_anki.running()


def _wait_closed(cancel, shown, on_phase, clock, sleep, deadline):
    """AC-3 A: until no Anki runs. The process list looked at once, then every `WAIT_EVERY` s while the install's line
    (or the bottom bar's job) is on screen (`shown()`), never otherwise; `deadline` (the clock's) passed -> STAYED_OPEN; a look that can't tell ->
    CANT_TELL (never written blind); the learner's Cancel -> CANCELLED. Returns None once Anki is closed."""
    said, first = False, True
    while True:
        if _stopped(cancel):
            raise _Refused(CANCELLED)
        if first or shown is None or _shown(shown):     # the first look at once: the press was just made on screen
            now = _running()
            if now is None:
                raise _Refused(CANT_TELL)
            if now is False:
                if said and on_phase:
                    on_phase(RUNNING)
                return
            if not said and on_phase:
                on_phase(WAITING)
            said = True
        first = False
        if clock() >= deadline:
            raise _Refused(STAYED_OPEN)
        sleep(WAIT_EVERY)


def _shown(shown):
    try:
        return bool(shown())
    except Exception:
        return True


def _route(on_progress, cancel, confirm, shown, on_phase, clock, sleep):
    if not DOWNLOAD_ENABLED or sys.platform != "win32":
        return OFF
    if confirm is None:                 # no one said yes: nothing is fetched
        return DECLINED
    if not confirm():                   # the one confirm, before any byte
        return DECLINED
    deadline = clock() + WAIT_FOR
    local = staging_folder()
    staged = None
    try:
        _wait_closed(cancel, shown, on_phase, clock, sleep, deadline)
        found = look()                  # nothing changed meanwhile (the learner may have added it by hand)
        if found["state"] == THERE:
            return ALREADY
        if found["state"] != CAN_INSTALL:
            return {NO_VERSION: NO_VERSION, NOT_WINDOWS: OFF, OFF: OFF}.get(found["state"], NO_BASE)
        folder, point = found["base"], found["point"]
        _remove(local)
        os.makedirs(local, exist_ok=True)
        zip_path = os.path.join(local, "AnkiConnect.ankiaddon")
        meta = _download(point, zip_path, on_progress, cancel)
        files, manifest = _check_zip(zip_path)
        staged = os.path.join(folder, ANKI_STAGING)
        _remove(staged)                 # a leftover of an install that died first
        if os.path.lexists(staged):
            raise _Refused(NOT_WRITTEN, "the staging folder couldn't be emptied")
        added = os.path.join(staged, CODE)
        _unpack(zip_path, files, added, add_on_meta(meta, manifest))
        while True:
            if _stopped(cancel):
                raise _Refused(CANCELLED)
            now = _running()            # Anki opened during the download: wait again, staging kept
            if now is None:
                raise _Refused(CANT_TELL)
            if not now:
                break
            _wait_closed(cancel, shown, on_phase, clock, sleep, deadline)
        target = os.path.join(_addons(folder), CODE)
        if _present(folder) is not None:
            raise _Refused(ALREADY)
        for attempt in range(RENAME_TRIES):
            try:
                os.rename(added, target)    # THE one move into addons21: atomic, and never over a folder there
                break
            except FileExistsError as e:    # one came meanwhile (the learner's own wins)
                raise _Refused(ALREADY, str(e))
            except PermissionError as e:    # a virus check still reading the new files: a moment, then again
                if os.path.lexists(target):
                    raise _Refused(ALREADY, str(e))
                if attempt == RENAME_TRIES - 1:
                    raise _Refused(NOT_WRITTEN, str(e))
                sleep(RENAME_PAUSE)
            except OSError as e:
                raise _Refused(ALREADY if os.path.lexists(target) else NOT_WRITTEN, str(e))
        return INSTALLED
    except _Refused as e:
        return e.result
    except OSError as e:
        return BLOCKED if getattr(e, "winerror", None) == 225 else NOT_WRITTEN
    finally:
        if staged is not None:
            _remove(staged)
        _remove(local)


def install(on_progress, cancel, on_end, confirm=None, shown=None, on_phase=None, clock=time.monotonic,
            sleep=time.sleep):
    """The route (module docstring) -> `installed` · `declined` · `cancelled` · `busy` · `off` · a reason
    (`offline`, `no-branch`, `blocked`, `already`, `stayed-open`, `cant-tell`, `refused`, `not-written`, `no-base`,
    `no-version`). Blocking; never raises; `on_end(result)` told once. `shown()`: is the waiting line on screen now
    (the process list is looked at only then); `on_phase(WAITING | RUNNING)`: the route waits for Anki to close, or
    goes on."""
    if not _ONE_INSTALL.acquire(blocking=False):
        result = BUSY
    else:
        try:
            result = _route(on_progress, cancel, confirm, shown, on_phase, clock, sleep)
        except Exception:
            result = NOT_WRITTEN
        finally:
            _ONE_INSTALL.release()
    if on_end:
        try:
            on_end(result)
        except Exception:
            pass
    return result


JOB_KIND = "ankiconnect-install"        # its kind in the window's registry (`jobs.RESOURCES`)
JOB_LABEL = "Installing AnkiConnect"
JOB_WAITING = "Waiting for Anki to close"
JOB_NEEDS = "Close Anki"


def install_as_job(registry, on_progress, cancel, on_end, confirm=None, shown=None, on_phase=None, **kw):
    """`install`, listed in `registry` as an `ankiconnect-install` job from the learner's yes until the route ends
    (waiting while Anki is open: its Cancel — and the quit's — sets `cancel`). No registry: `install` alone."""
    if registry is None:
        return install(on_progress, cancel, on_end, confirm, shown, on_phase, **kw)
    job = []

    def asked():
        yes = confirm() if confirm is not None else False
        if yes:
            job.append(registry.record(JOB_KIND, JOB_LABEL, cancel=lambda _job: cancel.set(), on_quit="cancel"))
        return yes

    def phase(now):
        if job:
            if now == WAITING:
                job[0].hold(JOB_WAITING, needs=JOB_NEEDS)
            else:
                job[0].resume()
        if on_phase:
            on_phase(now)

    def progress(done, total):
        if on_progress:
            on_progress(done, total)
        if job:
            job[0].progress(JOB_LABEL, done, total)
    result = BUSY
    try:
        result = install(progress, cancel, on_end, confirm=asked if confirm is not None else None, shown=shown,
                         on_phase=phase, **kw)
    finally:
        if job:
            job[0].finish(ok=result == INSTALLED, message=said(result), cancelled=result == CANCELLED)
    return result
