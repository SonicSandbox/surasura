"""Report a problem (alpha 3 on; `tracks/ship/work/report/scope.md`): the tester's saved reports and the one zip that
carries them, with what Sonic needs to see beside them. Qt-free: the window (`app/qt/report.py`) calls it on workers.

**The saved list** lives in the persistent data folder (`path_utils.get_persistent_user_data_path()`/reports — never
User Files, never the library), so it survives a restart, an update and a crash. Each report is one folder,
`<id>/` holding `report.json` (its words, its notes, when, which build) and its pictures (`picture-<n>.png`). A save is
made in `<id>.part/` and renamed into place last, so a crash leaves either the whole report or a `.part` folder the list
never shows (cleared by a zip once it is an hour old: a save under way keeps its own). A note rewrites `report.json`
atomically. *Remove* moves the folder to `removed/` (Undo puts it back). The list empties — the reports in the zip and
the ones removed before it was planned deleted — only after a zip was written whole and read back; a report given a
note while the zip was written stays on the list, and one removed meanwhile keeps its Undo.

**The zip** (`plan` lists every file first, `make_zip` writes it): each saved report's words and pictures; `about.txt`
(version, build, commit, system, the window's scale); the logs of the last 7 days (`status.log_files`, the rule
Connect's *Save logs* uses), Anki Miner's run results among them scrubbed to states and counts; Connect's status
(`scrub`: no title, line or word) and its job ledger as rows of states and counts; the Anki sync's state (its note ids
counted); settings.json with every key, token and password blanked; the library's counts and folder list;
`results` (the last Generate's lists — they quote short lines from the tester's subtitles and books, so the window
lets the tester leave them out). **Never** a subtitle or book file, an Anki card's fields, a key or a token, a link
followed, a cloud placeholder downloaded. The rules are the evidence collector's (`Collect laptop evidence.ps1`:
`SECRET_NAMES`, links, placeholders), kept here once (`why_not`, which both zips ask); the collector stays for when the
app won't open, and a test holds its list to this one.

Nothing here sends anything anywhere: the zip is written to a folder on this PC (Downloads, or one the tester picks)
and the tester sends it.
"""
import datetime
import fnmatch
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading
import time
import uuid
import zipfile

from app import path_utils

REPORTS_DIR = "reports"
REMOVED_DIR = "removed"
REPORT_FILE = "report.json"
PART = ".part"
PICTURE = "picture-{n}.png"
FORMAT = 1
RESULTS_CAP = 200 * 1024 * 1024  # results\ larger than this is left out whole, said in the zip's list
ZIP_NAME = "Surasura-problems-{stamp}.zip"
MAX_PICTURES = 6
STALE_PART_S = 3600             # a `.part` folder this old was left by a crash (a save takes well under a second)
_STAMP = "%Y%m%d-%H%M%S-%f"     # an id's time, UTC to the microsecond
_SAVING = threading.Lock()      # saves run on workers: two never pick the same time

# --- the collector's rules (one copy: `Collect laptop evidence.ps1`'s $SecretNames is held to this by a test) ----- #
SECRET_NAMES = (".env", "*.env", "*.key", "*.pem", "*.pfx", "*credential*", "*keystore*", "*secret*", "*api_key*",
                "*apikey*")
_DB_SUFFIX = re.compile(r"-(wal|shm|journal)$", re.IGNORECASE)
# settings.json: a key whose name says it holds a secret has its value blanked, wherever it sits
_SECRET_KEY = re.compile(r"(key|token|secret|password|passwd|credential|cookie|auth)", re.IGNORECASE)
BLANKED = "(left out)"
# Windows' file attributes: a cloud placeholder (OneDrive's recall-on-open / -on-access, offline) is never read
_PLACEHOLDER = 0x400000 | 0x40000 | 0x1000


def is_secret(name):
    """A file or folder name that names a key or a secret (a database's -wal / -shm / -journal as its database)."""
    name = _DB_SUFFIX.sub("", os.path.basename(name)).lower()
    return any(fnmatch.fnmatchcase(name, p.lower()) for p in SECRET_NAMES)


def is_link(path):
    """A symbolic link or a junction (never followed)."""
    try:
        if os.path.islink(path):
            return True
        is_junction = getattr(os.path, "isjunction", None)        # Python 3.12+
        if is_junction is not None and is_junction(path):
            return True
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return True                                               # gone or odd: left out


def is_placeholder(path):
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & _PLACEHOLDER)
    except OSError:
        return False


def why_not(path):
    """Why a zip may not read this file — a link, a key or secret by its name, a cloud placeholder — or None."""
    if is_link(path):
        return "a link (not followed)"
    if is_secret(os.path.basename(path)):
        return "a key or secret by its name (never taken)"
    if is_placeholder(path):
        return "a cloud placeholder (not downloaded)"
    return None


# What a person wrote or watched, in a record that is otherwise states and counts (Connect's status, Anki Miner's run
# results): each such value is replaced by how many there were, so no title, card word or sentence goes in the zip
CONTENT_KEYS = frozenset(("title", "titles", "name", "line", "say", "word", "words", "orth", "reading", "readings",
                          "sentence", "sentences", "sent", "expression", "kept", "deleted", "statuses", "file",
                          "filename", "episode", "definition", "glossary", "meaning", "translation", "hint", "fields"))


def scrub(obj):
    """`obj` with every value under a CONTENT_KEYS key replaced by a count (a list or dict) or "(left out)", and the
    secrets blanked (`strip_secrets`), at any depth."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in CONTENT_KEYS and v not in (None, "", [], {}):
                out[k] = f"{len(v)} left out" if isinstance(v, (list, dict)) else BLANKED
            else:
                out[k] = scrub(v)
        return strip_secrets(out)
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


def _now():
    return datetime.datetime.now().astimezone()


def folder():
    """The saved reports' folder (made)."""
    path = os.path.join(path_utils.get_persistent_user_data_path(), REPORTS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _atomic_write(path, data):
    """Temp file beside it, fsync, os.replace: a reader (or a crash) never sees half a file."""
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:                               # a reader holds it for a moment
                if attempt == 4:
                    raise
                time.sleep(0.1)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _json_bytes(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


# --- what a report records about the program ---------------------------------------------------------------------- #
def build():
    """{version, build_id, commit, data_name, frozen}: what the zip's about.txt and each report name."""
    from app import __version__, build_info
    out = {"version": __version__, "build_id": build_info.BUILD_ID,
           "commit": getattr(build_info, "BUILD_COMMIT", None),
           "data_name": path_utils.data_name(), "frozen": path_utils.is_frozen()}
    try:
        with open(os.path.join(path_utils.get_base_path(), path_utils.BUILD_STAMP), "r", encoding="utf-8-sig") as f:
            stamp = json.load(f)
        if isinstance(stamp, dict):
            out["build_id"] = out["build_id"] or stamp.get("build_id")
    except (OSError, ValueError):
        pass
    if out["commit"] is None and not out["frozen"]:
        out["commit"] = _source_commit()
    return out


def _source_commit():
    """From source: the checkout's HEAD, read from .git (no git process)."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        head = open(os.path.join(root, ".git", "HEAD"), encoding="ascii").read().strip()
        if head.startswith("ref: "):
            ref = head[5:]
            path = os.path.join(root, ".git", *ref.split("/"))
            if os.path.exists(path):
                return open(path, encoding="ascii").read().strip()[:12]
            for line in open(os.path.join(root, ".git", "packed-refs"), encoding="ascii"):
                if line.rstrip().endswith(" " + ref):
                    return line.split()[0][:12]
            return None
        return head[:12]
    except (OSError, ValueError):
        return None


# --- the saved list ------------------------------------------------------------------------------------------------ #
class Report:
    """One saved report as read: `id`, `created` (ISO), `what`, `expected`, `notes` [{at, text}], `pictures` (file
    names in its folder), `where` (the window / tab it came from), `build`."""

    __slots__ = ("id", "path", "created", "what", "expected", "notes", "pictures", "where", "build")

    def __init__(self, path, data):
        self.id = os.path.basename(path)
        self.path = path
        self.created = str(data.get("created") or "")
        self.what = str(data.get("what") or "")
        self.expected = str(data.get("expected") or "")
        self.notes = [n for n in (data.get("notes") or []) if isinstance(n, dict) and n.get("text")]
        self.pictures = [p for p in (data.get("pictures") or [])
                         if isinstance(p, str) and os.path.basename(p) == p and os.path.isfile(os.path.join(path, p))]
        self.where = str(data.get("where") or "")
        self.build = data.get("build") if isinstance(data.get("build"), dict) else {}

    def title(self):
        """Its first line of words, for the list."""
        first = (self.what.strip().splitlines() or [""])[0]
        return first

    def data(self):
        return {"format": FORMAT, "created": self.created, "what": self.what, "expected": self.expected,
                "notes": self.notes, "pictures": self.pictures, "where": self.where, "build": self.build}


def _stamp_of(name):
    """The UTC time a report id (or its `.part` folder) names, or None."""
    try:
        return datetime.datetime.strptime(name[:22], _STAMP).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _new_id(now, names=()):
    """When it was saved (UTC, to the microsecond: a clock put back an hour in autumn never reorders them) and a few
    random letters: ids sort in the order they were saved. A save in the same clock tick as the newest of `names` (the
    folder's ids), or with the clock put back, takes the microsecond after it — never left to the random letters (a4:
    two quick saves on a coarse clock came back out of order)."""
    utc = now.astimezone(datetime.timezone.utc)
    newest = max(filter(None, map(_stamp_of, names)), default=None)
    if newest is not None and utc <= newest:
        try:
            utc = newest + datetime.timedelta(microseconds=1)
        except OverflowError:                       # (a hand-made name at the calendar's end: the clock's own time)
            pass
    return f"{utc.strftime(_STAMP)}-{uuid.uuid4().hex[:4]}"


def _ids_in(root):
    """Every id the folder holds — listed, being saved or removed (an Undo puts one back in its place)."""
    names = []
    for path in (root, os.path.join(root, REMOVED_DIR)):
        try:
            names += os.listdir(path)
        except OSError:                             # none yet, or not a folder: the clock's time alone, as before
            pass
    return names


def save(what, expected="", pictures=(), where="", root=None, now=None):
    """Save one report. `pictures`: PNG bytes, at most MAX_PICTURES. -> the Report. Raises ValueError on no words.
    The folder is written as `<id>.part` and renamed last: a crash part-way leaves nothing the list shows."""
    what = (what or "").strip()
    if not what:
        raise ValueError("a report needs its words")
    root = root or folder()
    now = now or _now()
    with _SAVING:
        rid = _new_id(now, _ids_in(root))
        part = os.path.join(root, rid + PART)
        os.makedirs(part)
    try:
        names = []
        for n, png in enumerate(list(pictures)[:MAX_PICTURES], 1):
            name = PICTURE.format(n=n)
            with open(os.path.join(part, name), "wb") as f:
                f.write(png)
                f.flush()
                os.fsync(f.fileno())
            names.append(name)
        data = {"format": FORMAT, "created": now.isoformat(timespec="seconds"), "what": what,
                "expected": (expected or "").strip(), "notes": [], "pictures": names, "where": where or "",
                "build": build()}
        _atomic_write(os.path.join(part, REPORT_FILE), _json_bytes(data))
        final = os.path.join(root, rid)
        os.rename(part, final)
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    return Report(final, data)


def _read(path):
    try:
        with open(os.path.join(path, REPORT_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not str(data.get("what") or "").strip():
        return None
    return Report(path, data)


def listed(root=None, unreadable=None):
    """The saved reports, oldest first (a `.part` folder, `removed/` and a folder without a readable report.json are
    never listed; `unreadable`, a list, is given the names of the last). A folder that can't be listed raises: an empty
    list is never said for reports that are there."""
    root = root or folder()
    out = []
    try:
        names = os.listdir(root)
    except FileNotFoundError:
        return out
    for name in names:
        path = os.path.join(root, name)
        if name == REMOVED_DIR or name.endswith(PART) or not os.path.isdir(path) or is_link(path):
            continue
        r = _read(path)
        if r is not None:
            out.append(r)
        elif unreadable is not None:
            unreadable.append(name)
    out.sort(key=lambda r: r.id)
    return out


def count(root=None):
    return len(listed(root))


def _own(root, rid):
    """The report folder `rid` names inside `root` — never a path outside it."""
    if not isinstance(rid, str) or not rid or os.path.basename(rid) != rid or rid in (".", "..", REMOVED_DIR) \
            or rid.endswith(PART):
        raise ValueError(f"not a report: {rid!r}")
    return os.path.join(root, rid)


def add_note(rid, text, root=None, now=None):
    """Add a note to a saved report (report.json rewritten atomically). -> the Report."""
    text = (text or "").strip()
    if not text:
        raise ValueError("an empty note")
    root = root or folder()
    path = _own(root, rid)
    r = _read(path)
    if r is None:
        raise FileNotFoundError(rid)
    r.notes.append({"at": (now or _now()).isoformat(timespec="seconds"), "text": text})
    _atomic_write(os.path.join(path, REPORT_FILE), _json_bytes(r.data()))
    return r


def remove(rid, root=None):
    """Take a report off the list: its folder moves to `removed/` (Undo: `restore`). -> True when it was there."""
    root = root or folder()
    path = _own(root, rid)
    if not os.path.isdir(path):
        return False
    gone = os.path.join(root, REMOVED_DIR)
    os.makedirs(gone, exist_ok=True)
    os.replace(path, os.path.join(gone, rid))
    return True


def restore(rid, root=None):
    """Undo a remove. -> True when it came back."""
    root = root or folder()
    path = _own(root, rid)
    held = os.path.join(root, REMOVED_DIR, rid)
    if not os.path.isdir(held) or os.path.exists(path):
        return False
    os.replace(held, path)
    return True


# --- what the zip holds ------------------------------------------------------------------------------------------- #
def strip_secrets(obj):
    """settings as read, every value under a key naming a key / token / secret / password blanked, at any depth."""
    if isinstance(obj, dict):
        return {k: (BLANKED if isinstance(k, str) and _SECRET_KEY.search(k) and v not in (None, "", [], {})
                    else strip_secrets(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_secrets(v) for v in obj]
    return obj


def _settings_bytes():
    path = path_utils.get_settings_path()
    if not os.path.isfile(path) or is_link(path) or is_placeholder(path):
        return None
    try:
        data = json.loads(path_utils.read_text(path))
    except (OSError, ValueError) as e:
        return _json_bytes({"unreadable": str(e)})
    return _json_bytes(strip_secrets(data))


def _about_bytes(language, extra=None):
    import platform
    lines = [f"Surasura problem reports, {_now().strftime('%Y-%m-%d %H:%M:%S %z')}"]
    for k, v in build().items():
        lines.append(f"{k}: {v}")
    lines.append(f"language: {language}")
    lines.append(f"system: {platform.platform()}")
    lines.append(f"python: {sys.version.split()[0]}")
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")
    return ("\n".join(lines) + "\n").encode("utf-8")


# A job's columns that hold states, counts and times — never its words, its pick, its sentences (`outcomes`)
_JOB_COLUMNS = ("id", "language", "item_id", "kind", "state", "resume", "attempt", "failures", "source",
                "created_at", "updated_at", "asked_at")


def _ledger_bytes():
    """Connect's job ledger, read-only: each job's state row, each batch's state, the outcomes counted per job.
    -> JSON bytes, or None (no ledger)."""
    import pathlib
    from app.connect import ledger as book
    path = book.path()
    if not os.path.isfile(path):
        return None
    conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True, timeout=2.0, isolation_level=None)
    try:
        conn.execute("PRAGMA query_only=1")
        have = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        cols = [c for c in _JOB_COLUMNS if c in have]
        out = {"jobs": [dict(zip(cols, r)) for r in conn.execute(
            f"SELECT {', '.join(cols)} FROM jobs ORDER BY id DESC LIMIT 2000")]}
        try:
            out["batches"] = [dict(zip(("job_id", "attempt", "state", "started_at", "ended_at"), r)) for r in
                              conn.execute("SELECT job_id, attempt, state, started_at, ended_at FROM batches "
                                           "ORDER BY job_id DESC LIMIT 2000")]
            out["outcomes"] = [dict(zip(("job_id", "outcome", "n"), r)) for r in conn.execute(
                "SELECT job_id, outcome, COUNT(*) FROM outcomes GROUP BY job_id, outcome ORDER BY job_id DESC")]
        except sqlite3.Error:
            pass
        out["meta"] = dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()
    return _json_bytes(out)


def _connect_status_bytes():
    """Connect's status record as the window reads it, its titles, lines and words left out (`scrub`)."""
    from app.connect import status
    return _json_bytes(scrub(status.read()))


def _scrubbed_json(path):
    """A JSON file (Anki Miner's run result) read and scrubbed: its states and counts, never a word or a sentence."""
    try:
        data = json.loads(_read_shared(path).decode("utf-8-sig"))
    except (OSError, ValueError) as e:
        return _json_bytes({"unreadable": type(e).__name__})
    return _json_bytes(scrub(data))


def _anki_bytes(language):
    """The Anki sync's own record of its last answers (when, what it added, its decks and fields) — its note ids
    counted, never listed; nothing of a card's fields is in it."""
    from app import anki_sync
    path = os.path.join(path_utils.get_user_files_path(language), anki_sync.STATE_FILE)
    if not os.path.isfile(path) or is_link(path) or is_placeholder(path):
        return None
    try:
        data = json.loads(path_utils.read_text(path, language))
    except (OSError, ValueError) as e:
        return _json_bytes({"unreadable": str(e)})

    def counted(o):
        if isinstance(o, dict):
            return {k: (f"{len(v)} ids" if isinstance(v, list) and "id" in str(k).lower() else counted(v))
                    for k, v in o.items()}
        if isinstance(o, list):
            return [counted(v) for v in o]
        return o
    return _json_bytes(strip_secrets(counted(data)))


class Entry:
    """One file the zip will hold: `name` (in the zip), `source` (a path read as it is) or `data` (bytes made here)."""
    __slots__ = ("name", "source", "data", "size")

    def __init__(self, name, source=None, data=None):
        self.name, self.source, self.data = name.replace("\\", "/"), source, data
        if data is not None:
            self.size = len(data)
        else:
            try:
                self.size = os.path.getsize(source)
            except OSError:
                self.size = 0


class Plan:
    """What `make_zip` writes: `entries` (in order), `left_out` (words: what wasn't taken and why), `reports` (their
    ids: the ones the list loses once the zip is written)."""

    def __init__(self):
        self.entries, self.left_out, self.reports, self.removed = [], [], [], []

    def add(self, name, source=None, data=None):
        self.entries.append(Entry(name, source, data))

    def size(self):
        return sum(e.size for e in self.entries)


def _file_ok(path, label, plan):
    """A file the zip may read (`why_not`), else said in `left_out`."""
    why = why_not(path)
    if why:
        plan.left_out.append(f"{label}: {why}")
    return why is None


def report_text(r):
    """A report in words (report.txt in the zip)."""
    text = [f"When: {r.created}"]
    if r.where:
        text.append(f"Where: {r.where}")
    text += ["", "What happened:", r.what]
    if r.expected:
        text += ["", "What I expected:", r.expected]
    for n in r.notes:
        text += ["", f"Note ({n.get('at', '')}):", str(n.get("text", ""))]
    if r.build:
        text += ["", "Build: " + ", ".join(f"{k} {v}" for k, v in r.build.items())]
    return "\n".join(text) + "\n"


def _report_entries(plan, reports):
    for r in reports:
        base = f"reports/{r.id}"
        plan.add(f"{base}/report.txt", data=report_text(r).encode("utf-8"))
        for name in [REPORT_FILE] + r.pictures:
            full = os.path.join(r.path, name)
            if _file_ok(full, f"{base}/{name}", plan):
                plan.add(f"{base}/{name}", source=full)
        plan.reports.append(r.id)


def _results_entries(plan):
    root = os.path.join(path_utils.get_user_data_path(), "results")
    if not os.path.isdir(root):
        plan.left_out.append("results\\: not there (no Generate yet)")
        return
    if is_link(root):
        plan.left_out.append("results\\: a link (not followed)")
        return
    found = []
    for folder_, dirs, files in os.walk(root):
        for d in list(dirs):
            full = os.path.join(folder_, d)
            if is_link(full) or is_secret(d):
                plan.left_out.append(f"results\\{os.path.relpath(full, root)}\\: a link or a secret's name")
                dirs.remove(d)
        for name in sorted(files):
            full = os.path.join(folder_, name)
            rel = os.path.relpath(full, root)
            if _file_ok(full, f"results\\{rel}", plan):
                found.append((full, "results/" + rel))
    entries = [Entry(name, source=full) for full, name in found]
    total = sum(e.size for e in entries)
    if total > RESULTS_CAP:
        plan.left_out.append(f"results\\: {total // (1024 * 1024)} MB, more than {RESULTS_CAP // (1024 * 1024)} MB "
                             "(left out whole)")
        return
    plan.entries += entries


def plan(language, include_results=True, library=None, root=None, extra=None):
    """Every file the zip will hold, worked out without writing anything (but the reports folder, made when missing).
    `library`: the window's counts and folder list (`{counts, sources, state}`) as it shows them. -> a Plan."""
    p = Plan()
    root = root or folder()
    unreadable = []
    _report_entries(p, listed(root, unreadable))
    for name in unreadable:                                        # kept on disk, never cleared: said in the zip
        p.left_out.append(f"reports/{name}: its report.json couldn't be read (kept on this PC)")
    try:
        p.removed = sorted(os.listdir(os.path.join(root, REMOVED_DIR)))
    except OSError:
        p.removed = []
    p.add("about.txt", data=_about_bytes(language, extra))
    try:
        from app.connect import status
        refused = []
        for full, name in status.log_files(left_out=refused):
            if name.replace('\\', "/").startswith("anki-miner/"):        # a run's results: states and counts only
                try:
                    p.add(name, data=_scrubbed_json(full))
                except Exception as e:
                    p.left_out.append(f"{name}: couldn't be read ({type(e).__name__})")
            else:
                p.add(name, source=full)
        p.left_out += refused
    except Exception as e:                                         # the logs are help, never a reason to fail
        p.left_out.append(f"logs: couldn't be listed ({e})")
    for name, make in (("connect/status.json", _connect_status_bytes), ("connect/ledger.json", _ledger_bytes),
                       (f"anki/anki_sync_state-{language}.json", lambda: _anki_bytes(language)),
                       ("settings.json", _settings_bytes)):
        try:
            data = make()
        except Exception as e:
            p.left_out.append(f"{name}: couldn't be read ({e})")
            continue
        if data is None:
            p.left_out.append(f"{name}: not there")
        else:
            p.add(name, data=data)
    p.add("library/summary.json", data=_json_bytes(library or {"library": "none open"}))
    if include_results:
        _results_entries(p)
    else:
        p.left_out.append("results\\: left out (Include my last lists was unticked)")
    p.left_out.append("never taken: your subtitle and book files, Anki's cards, keys and tokens, the library's "
                      "database; Connect's titles and words and Anki Miner's sentences are counted, never copied")
    return p


def describe(p):
    """The plan in words, for *Show me what's in it*: every file and its size, then what's left out and why."""
    lines = [f"{len(p.entries) + 1} files, about {_mb(p.size())} before it's packed", ""]
    for e in p.entries:
        lines.append(f"{e.name}  ({_kb(e.size)})")
    lines.append("MANIFEST.txt  (this list, with each file's sha256)")
    lines += ["", "Left out:"] + [f"  {x}" for x in p.left_out]
    return "\n".join(lines)


def _kb(n):
    return f"{max(1, round(n / 1024))} KB" if n >= 1024 else f"{n} bytes"


def _mb(n):
    return f"{n / (1024 * 1024):.1f} MB" if n >= 1024 * 1024 else _kb(n)


def _manifest(p, hashes):
    lines = [f"Surasura problem reports: {len(p.entries)} files (sha256  size  name)"]
    for e in p.entries:
        lines.append(f"{hashes.get(e.name, '-')}  {e.size}  {e.name}")
    lines += ["", "Left out:"] + [f"  {x}" for x in p.left_out]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _read_shared(path):
    """A source file's bytes, read once (opened read-only; Python's open on Windows shares reading and writing)."""
    with open(path, "rb") as f:
        return f.read()


def zip_name(dest, now=None):
    """A new zip's path in `dest`: Surasura-problems-<date>-<time>.zip, -2, -3 … when one is there."""
    stamp = (now or _now()).strftime("%Y-%m-%d-%H%M%S")
    path = os.path.join(dest, ZIP_NAME.format(stamp=stamp))
    n = 2
    while os.path.exists(path) or os.path.exists(path + PART):
        path = os.path.join(dest, ZIP_NAME.format(stamp=f"{stamp}-{n}"))
        n += 1
    return path


def make_zip(dest, language, include_results=True, library=None, root=None, extra=None, now=None):
    """The zip, in `dest` (made if missing): written as `<name>.zip.part`, read back whole (every name, every CRC),
    renamed into place — and only then are its reports taken off the list (and `removed/`, the `.part` folders a crash
    left, cleared). A failure part-way leaves no zip and the list as it was. -> the zip's path."""
    import hashlib
    root = root or folder()
    p = plan(language, include_results, library, root, extra)
    if not p.reports:
        raise ValueError("there are no saved reports to send")
    os.makedirs(dest, exist_ok=True)
    final = zip_name(dest, now)
    part = final + PART
    hashes = {}
    try:
        with zipfile.ZipFile(part, "x", zipfile.ZIP_DEFLATED) as z:
            for e in p.entries:
                try:
                    data = e.data if e.data is not None else _read_shared(e.source)
                except OSError as err:
                    if e.name.startswith("reports/"):
                        raise                                        # a report not read whole: no zip
                    p.left_out.append(f"{e.name}: couldn't be read ({err})")
                    continue
                e.size = len(data)
                hashes[e.name] = hashlib.sha256(data).hexdigest()
                z.writestr(e.name, data)
            p.entries = [e for e in p.entries if e.name in hashes]
            z.writestr("MANIFEST.txt", _manifest(p, hashes))
        with zipfile.ZipFile(part) as z:                               # read back: every file whole
            if z.testzip() is not None or set(z.namelist()) != set(hashes) | {"MANIFEST.txt"}:
                raise OSError("the zip didn't read back whole")
        os.replace(part, final)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    zipped = {rid: hashes.get(f"reports/{rid}/{REPORT_FILE}") for rid in p.reports}
    _clear(root, zipped, p.removed)
    return final


def _unchanged(path, digest):
    import hashlib
    try:
        with open(os.path.join(path, REPORT_FILE), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest() == digest
    except OSError:
        return False


def _clear(root, zipped, removed=()):
    """After a good zip: each report in it — unless its report.json changed since it was zipped (a note added
    meanwhile: it stays on the list) —, the reports removed before it (`removed`; one removed meanwhile keeps its
    Undo) and the `.part` folders a crash left (an hour old: a save under way keeps its own). A report saved meanwhile
    stays."""
    for rid, digest in zipped.items():
        path = _own(root, rid)
        if _unchanged(path, digest):
            shutil.rmtree(path, ignore_errors=True)
    for rid in removed:
        try:
            _own(root, rid)                                        # a plain report id, never a path
        except ValueError:
            continue
        shutil.rmtree(os.path.join(root, REMOVED_DIR, rid), ignore_errors=True)
    try:
        os.rmdir(os.path.join(root, REMOVED_DIR))                  # only when nothing is left in it
    except OSError:
        pass
    try:
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if name.endswith(PART) and time.time() - os.path.getmtime(full) > STALE_PART_S:
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)
    except OSError:
        pass
