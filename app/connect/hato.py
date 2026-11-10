"""hato's pairings back-filled (P3.2 row 3.2.4; docs/agent instructions/3.0/P1.5-connect/09-hato-layer.md §4, v2):
when Connect's preview is switched on, and when *Needs you*'s *Ask hato again* is pressed, Surasura asks hato for every
pairing it has made (`hato-cli pairings --json --lang <lang>`) and registers each one through `register`'s own code.

- **Found** through hato's entry in the shared tools folder (`tools_entry.read("hato")`, 09 §3): absent, too new, its
  `cli` missing, or no `pairings` among its verbs → hato can't be asked: logged, nothing written.
- **Asked** off the window's thread, with no console window and stdin closed, for at most 60 s, its stdout read up to
  16 MiB. Exit 0, every line a JSON object, the last `{"type":"result","ok":true,…}` with `complete_since`; anything
  else (no answer in time, a line that isn't JSON, no result line, a failed exit, more than 16 MiB) → `Unavailable`,
  and nothing is registered.
- **Registered**, every line (09-hato-layer v2, the back-fill): the record without its `type` and `registered`, through
  `connect_verbs.register_record(..., backfill=True)` — one already in the store answers `same` and writes nothing,
  and no registration logs a placement event for the item it registers, so nothing is mined because of it and no job
  is queued. On 3.0, New arrivals on (the default, D30): a drop the store doesn't hold yet waits at the end of New
  arrivals, placed by no rule, and nothing is pushed; New arrivals off (2.x's way), it lands at the top of NOW and the
  items it pushes out of the top 20 log `left_mine_line`. A line Surasura refuses (`bad-data`,
  `version-skew`, `usage`, or its own copy or record that can't be read: `unreadable`) is logged and counted, and the
  rest go on; the library or the settings not available (`busy`, `settings-unreadable`, `update-staged`, `needs-you`,
  `failed`, `not-set-up`) or any other fault stops it there: what was registered stays, the next back-fill takes the
  rest.
- **No pairing from hato:** the files in the language's drop folder (sub-folders too, the disk sync's file rules) last
  changed before hato's `complete_since` that no line names → one *Needs you* entry per language (`no-pairing`) saying
  how many, the files themselves in the log; raised again only when its words change (a dismissed one stays dismissed,
  its words as they were), fixed by a back-fill that finds none left. `complete_since` null: nothing is listed.
  settings.json is read again first: the preview switched off meanwhile (or the file unreadable) → no entry.

With the preview off: `skipped`, hato never asked, nothing written. One back-fill at a time in a process: a second
while one runs answers at once that hato is being asked already. The lines go to Connect's logger; in the window (no
command-line log open) to `hato-backfill.log` in the logs folder too, where *Open logs folder* finds them.
"""
import contextlib
import datetime
import json
import logging
import os
import subprocess
import sys
import threading
import time

KIND = "no-pairing"             # the *Needs you* entry (one per language)
VERB = "pairings"
TIMEOUT = 60.0                  # seconds hato is given to answer
MAX_OUT = 16 * 1024 * 1024      # its answer read up to this; more → not used
CREATE_NO_WINDOW = 0x08000000
ASKED = "asked"
ASKING = "hato is being asked already"      # a second back-fill while one runs: answered at once, nothing done
LOG_FILE = "hato-backfill.log"
PREVIEW_OFF = "connect preview off"
SWITCHED_OFF = "Connect's preview was switched off."
# A line's own fault: refused, logged and counted; the rest go on. Any other refusal stops the back-fill there.
REFUSED = ("bad-data", "version-skew", "usage")
STOP, LEAVE = "stop", "leave"   # a line's outcome besides "go on": the back-fill stops · the span is left (library busy)
LANGUAGE_NAMES = {"ja": "Japanese", "zh": "Chinese"}

log = logging.getLogger("surasura-cli.hato")
_running = threading.Lock()     # one back-fill at a time in a process (the switch's and *Ask hato again*)


class Unavailable(Exception):
    """hato can't be asked, or its answer can't be used (`reason`, in plain words): nothing is registered."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def connected():
    """Has hato an entry in the shared tools folder (`hato.json`, usable or not)? Without one, hato isn't installed or
    never connected to Surasura: the switch-on says nothing of it in the Processing Log."""
    from app import tools_entry
    return os.path.exists(os.path.join(tools_entry.tools_dir(), "hato.json"))


def find():
    """hato's entry in the shared tools folder (a dict with its `cli`), or `Unavailable`."""
    from app import tools_entry
    entry = tools_entry.read("hato")
    if entry is None:
        if not connected():
            raise Unavailable("hato isn't connected to Surasura (it has no entry in the shared tools folder)")
        raise Unavailable("hato's entry in the shared tools folder can't be used: its program isn't there, or it is "
                          "newer than this Surasura reads")
    verbs = entry.get("verbs")
    if not isinstance(verbs, list):
        raise Unavailable("this hato doesn't offer its pairings (hato 1.1.0 and later do)")
    if VERB not in verbs:                   # hato 1.1.0 switched off keeps its entry with no verbs
        raise Unavailable("hato isn't offering its pairings now (its Connect to Surasura setting is off, or it's "
                          "older than 1.1.0)")
    return entry


def _stop(proc):
    """A call past its time or its size stopped, with every process it started (a .cmd's child too): Connect's one
    process-ender (`stopping.end`, row 56), its output left to `_run`'s own reader."""
    from app.connect import stopping
    stopping.end(proc, collect=False)


def _run(argv, timeout):
    """`argv` with no console window and stdin closed -> (exit code, stdout: at most MAX_OUT + 1 bytes, read on a
    thread so a bigger answer is never held whole). No answer in time → stopped, `Unavailable`; more than MAX_OUT
    bytes → stopped, the bytes read so far returned (`pairings` refuses them)."""
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=flags)
    except OSError as e:
        raise Unavailable(f"hato's command line couldn't be started ({e})") from None
    chunks, size = [], [0]

    def read():
        try:
            while size[0] <= MAX_OUT:
                block = proc.stdout.read(65536)
                if not block:
                    return
                chunks.append(block)
                size[0] += len(block)
        except (OSError, ValueError):
            pass

    deadline = time.monotonic() + timeout
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    if reader.is_alive():
        _stop(proc)
        raise Unavailable(f"hato didn't answer within {timeout:g} s, so it was stopped")
    proc.stdout.close()
    if size[0] > MAX_OUT:
        _stop(proc)
        return proc.returncode, b"".join(chunks)
    try:
        code = proc.wait(timeout=max(0.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        _stop(proc)
        raise Unavailable(f"hato didn't answer within {timeout:g} s, so it was stopped") from None
    return code, b"".join(chunks)


def _no_constant(name):
    raise ValueError(f"{name} isn't JSON")


def _since(result):
    """`complete_since` as a POSIX time, or None (null, or absent: nothing listed); a value that isn't an ISO time →
    `Unavailable` (09-hato-layer v2, complete_since)."""
    value = result.get("complete_since")
    if value is None:
        return None
    try:
        at = datetime.datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (TypeError, ValueError, AttributeError):
        raise Unavailable("hato's answer gives no time its pairings are complete from") from None
    if at.tzinfo is None:
        at = at.replace(tzinfo=datetime.timezone.utc)
    return at.timestamp()


def pairings(cli, lang, run=None, timeout=TIMEOUT):
    """`<cli> pairings --json --lang <lang>` -> (its `pairing` lines, its result line), or `Unavailable`. `run(argv,
    timeout)` -> (exit code, stdout bytes): the call itself (tests hand a stand-in)."""
    code, data = (run or _run)([cli, VERB, "--json", "--lang", lang], timeout)
    if len(data) > MAX_OUT:
        raise Unavailable(f"hato's answer is over {MAX_OUT // (1024 * 1024)} MiB, so it wasn't read")
    if code != 0:
        raise Unavailable(f"hato's command line ended with exit code {code}")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Unavailable("hato's answer isn't UTF-8") from None
    found = []
    for n, raw in enumerate(text.split("\n"), 1):     # "\n" only: a record may hold U+2028 as it is
        if not raw.strip():
            continue
        try:
            value = json.loads(raw, parse_constant=_no_constant)
        except ValueError:
            raise Unavailable(f"hato's answer has a line that isn't JSON (line {n})") from None
        if not isinstance(value, dict):
            raise Unavailable(f"hato's answer has a line that isn't a JSON object (line {n})")
        found.append(value)
    if not found or found[-1].get("type") != "result" or found[-1].get("ok") is not True:
        raise Unavailable("hato's answer has no result line: it stopped part-way")
    result = found[-1]
    _since(result)
    return [v for v in found[:-1] if v.get("type") == "pairing"], result


def drop_folder(lang):
    """hato's drop folder for `lang` (surasura.json's `drop_folders`, the store's HATO_FOLDER)."""
    from app import library_store
    from app.path_utils import get_data_path
    return os.path.join(get_data_path(lang), *library_store.HATO_FOLDER.split("/"))


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def need_words(n):
    if n == 1:
        return "1 file in hato's folder has no pairing from hato, so Connect can't tell which video it belongs to."
    return f"{n} files in hato's folder have no pairing from hato, so Connect can't tell which video they belong to."


@contextlib.contextmanager
def _logged():
    """In the window (no command-line log open): the back-fill's lines in the logs folder too, `hato-backfill.log`."""
    handler = None
    if not logging.getLogger("surasura-cli").handlers:
        try:
            from app.cli import contract
            folder = contract.log_folder()
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, LOG_FILE)
            contract._rotate(path)
            # a path hato sent with a lone surrogate is written as an escape, never a logging error in its place
            handler = logging.FileHandler(path, encoding="utf-8", delay=True, errors="backslashreplace")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            log.addHandler(handler)
            log.setLevel(logging.INFO)
        except Exception:
            handler = None          # a log that can't be written never stops the back-fill
    try:
        yield
    finally:
        if handler is not None:
            log.removeHandler(handler)
            handler.close()


def backfill(lang, settings, wait=10, run=None):
    """Every pairing hato has for `lang`, registered (`wait`: seconds a busy library is waited for, each line) -> the
    summary: {"language", "hato" (ASKED, or why it couldn't be asked), "new", "same", "replaced", "refused" [(path,
    code, message)], "unpaired" [paths], "stopped" (None, or why it stopped part-way), "skipped" (the preview off),
    "need" (the *Needs you* entry: "raised", "kept", "fixed" or None)}. `settings`: settings.json as read; the preview
    off → skipped, hato never asked, nothing written."""
    summary = {"language": lang, "hato": None, "new": 0, "same": 0, "replaced": 0, "refused": [], "unpaired": [],
               "stopped": None, "skipped": None, "need": None}
    if not (settings or {}).get("connect_enabled"):     # set-up, not automation (P4.1 row 4.1.1): never `connect_on`
        summary["skipped"] = PREVIEW_OFF
        return summary
    if not _running.acquire(blocking=False):        # the switch's back-fill or *Ask hato again* is asking hato now
        summary["hato"] = ASKING
        return summary
    try:
        with _logged():
            _backfill(lang, wait, run, summary)
    finally:
        _running.release()
    return summary


def _backfill(lang, wait, run, summary):
    try:
        entry = find()
        lines, result = pairings(entry["cli"], lang, run=run, timeout=TIMEOUT)
    except Unavailable as e:
        summary["hato"] = e.reason
        log.warning("hato's pairings (%s) weren't read, nothing registered: %s", lang, e.reason)
        return
    summary["hato"] = ASKED
    _register_all(lang, lines, wait, summary)
    try:
        if summary["stopped"] != SWITCHED_OFF:          # switched off: nothing more of Connect's is written
            # read again (strictly) before the entry: a switch-off no line came after to see (none, or after the last)
            from app.cli import verbs
            if verbs.settings().get("connect_enabled"):         # set-up (P4.1 row 4.1.1), as above
                _no_pairing(lang, lines, _since(result), summary)
            else:
                summary["stopped"] = SWITCHED_OFF
    except Exception as e:      # the ledger busy or newer, settings.json unreadable: the entry waits for the next one
        log.warning("hato's files with no pairing (%s) weren't noted: %s", lang, e)
    log.info("hato's pairings (%s): %d new, %d same, %d replaced, %d refused, %d with no pairing%s", lang,
             summary["new"], summary["same"], summary["replaced"], len(summary["refused"]),
             len(summary["unpaired"]), f"; stopped: {summary['stopped']}" if summary["stopped"] else "")


def _register_all(lang, lines, wait, summary):
    """The lines in turn, back to back through one store handle (`library_store.held()`; measured on already-paired
    lines: 60 took 0.88 s with a handle a line and 0.11 s with one, 2,000 took 139 s and 3.9 s). Never a lock's wait
    inside the span: a busy library ends it, the line is tried again with its `wait` and no handle held, and the rest
    go on in a new span."""
    from app import library_store
    n = 0
    while n < len(lines):
        with library_store.held():
            while n < len(lines):
                done = _register_one(lang, lines[n], 0.0, summary, leave=True)
                if done == LEAVE:
                    break
                n += 1
                if done == STOP:
                    return
        if n < len(lines):                      # the library busy: waited for outside the span
            done = _register_one(lang, lines[n], wait, summary)
            n += 1
            if done == STOP:
                return


def _register_one(lang, line, wait, summary, leave=False):
    """One line registered, refused or the back-fill stopped (summary written) -> None (go on), STOP, or LEAVE (`leave`:
    the library busy, nothing written to the summary: the caller waits for it with no handle held)."""
    from app.cli import connect_verbs
    from app.cli.contract import CliError
    record = {k: v for k, v in line.items() if k not in ("type", "registered")}
    path = record.get("library_path")
    try:
        if len(json.dumps(record, ensure_ascii=False).encode("utf-8")) > connect_verbs.RECORD_MAX:
            raise CliError("bad-data", f"The pairing record is over {connect_verbs.RECORD_MAX // 1024} KiB.")
        # settings.json read again for each line (`loaded` None): switched off part-way, the rest are skipped
        out = connect_verbs.register_record(record, lang, backfill=True, wait=wait, loaded=None)
    except CliError as e:
        if e.code in REFUSED:
            summary["refused"].append((path, e.code, e.message))
            log.warning("hato's pairing refused (%s) for %s: %s", e.code, path, e.message)
            return None
        if leave and e.code == "busy":
            return LEAVE
        summary["stopped"] = e.message
        log.warning("hato's pairings (%s) stopped at %s (%s): %s", lang, path, e.code, e.message)
        return STOP
    except (OSError, ValueError) as e:
        # this line's own read: its copy held by another program or unreadable, a path no file system takes, a lone
        # surrogate (a UnicodeError is a ValueError) — the line refused, the rest go on (hato's order is stable:
        # stopping here would stop every back-fill at the same line)
        code = "unreadable" if isinstance(e, OSError) else "bad-data"
        message = f"Its copy or record can't be read ({type(e).__name__}: {e})."
        summary["refused"].append((path, code, message))
        log.warning("hato's pairing refused (%s) for %s: %s", code, path, message)
        return None
    except Exception as e:
        log.exception("hato's pairings (%s) stopped at %s", lang, path)
        summary["stopped"] = f"Surasura couldn't take hato's pairing ({type(e).__name__}: {e})."
        return STOP
    if out.get("skipped"):
        summary["stopped"] = SWITCHED_OFF
        return STOP
    summary[out["pairing"]] += 1
    return None


def _no_pairing(lang, lines, since, summary):
    """The drop folder's files older than `since` that no line names → `summary["unpaired"]`, each in the log, and the
    language's one *Needs you* entry raised, kept or fixed. `since` None: nothing listed, the entry left as it is."""
    if since is None:
        return
    from app import library_store
    paired = {_key(line["library_path"]) for line in lines if isinstance(line.get("library_path"), str)}
    folder = drop_folder(lang)
    files, _bad = library_store.walk_tree(folder, "")
    for rel, _size, mtime_ns in files:
        path = os.path.join(folder, *rel.split("/"))
        if mtime_ns / 1e9 < since and _key(path) not in paired:
            summary["unpaired"].append(path)
    for path in summary["unpaired"]:
        log.info("no pairing from hato (%s): %s", lang, path)
    summary["need"] = _need(lang, len(summary["unpaired"]))


def _need(lang, n):
    """The language's one `no-pairing` entry -> "raised" (new, or its words changed: it counts again), "kept" (the
    same words, or dismissed: nothing written, no new badge), "fixed" (none left) or None (nothing open, none left)."""
    from app.connect import ledger as book
    if n == 0:
        if not os.path.exists(book.path()):
            return None                         # no ledger: nothing open (and none made here)
        with book.Ledger() as ledger:
            rows = ledger.fix(lang, kinds=(KIND,))
        for row in rows:
            log.info("Connect: fixed by itself (%s, %s): %s", lang, KIND, row["say"])
        return "fixed" if rows else None
    say = need_words(n)

    def standing(ledger):
        """The open entry (or None), and whether it stays as it is: the same words, or dismissed."""
        found = [x for x in ledger.needs(lang, listed=False) if x["kind"] == KIND and x["item_id"] is None]
        entry = found[0] if found else None
        return entry, entry is not None and (entry["say"] == say or bool(entry["dismissed_at"]))
    with book.Ledger() as ledger:
        if standing(ledger)[1]:
            return "kept"                       # read only: no write transaction for a write never made
        with ledger.transaction():
            entry, keep = standing(ledger)      # read again under the lock: a Dismiss meanwhile is kept as it is
            if keep:
                return "kept"
            if entry is not None:
                ledger.fix(lang, kinds=(KIND,))     # its words changed: the old entry gives way to one that counts
            ledger.need(lang, KIND, say)
    return "raised"


def say(summary):
    """The summary in plain words (the Processing Log's line, *Ask hato again*'s note)."""
    name = LANGUAGE_NAMES.get(summary.get("language"), summary.get("language") or "")
    if summary.get("skipped"):
        return f"hato's pairings ({name}) weren't asked for: Connect's preview is off."
    if summary.get("hato") == ASKING:
        return f"hato is being asked already ({name}); try again once it has answered."
    if summary.get("hato") != ASKED:
        return f"hato couldn't be asked for its pairings ({name}): {summary.get('hato')}."
    parts = [f"{summary['new']} new", f"{summary['same']} already there"]
    if summary["replaced"]:
        parts.append(f"{summary['replaced']} updated")
    text = f"hato's pairings ({name}): {', '.join(parts)}."
    if summary["refused"]:
        text += f" {len(summary['refused'])} refused: the logs say why."
    if summary["unpaired"]:
        text += " " + need_words(len(summary["unpaired"]))
    if summary["stopped"] == SWITCHED_OFF:
        text += " Connect was switched off, so it stopped."
    elif summary["stopped"]:
        text += f" It stopped part-way, so try again later (what was paired stays): {summary['stopped']}"
    return text
