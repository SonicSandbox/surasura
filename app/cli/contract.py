"""The rules every surasura-cli verb follows (docs/agent instructions/3.0/P0.3-cli-contract/02-contract.md).

stdout carries only JSON lines — ASCII-escaped, one object a line, each flushed: any number of `progress` lines (with
--progress), then exactly one `result` or `error`. The exit code says how it went: 0 done, 1 failed, 2 wrong command
or not set up, 3 busy, 4 needs a person. Nothing opens a dialog: an exception becomes an `error` line, a traceback in
the log and exit 1. Diagnostics go to <local data>/logs/cli.log, never to stdout; every `error` is also kept in
<local data>/logs/cli-events.jsonl (the newest 200) for the window to show.

Light by rule (02 §5): nothing here imports tkinter, Qt, pandas or requests.
"""
import datetime
import faulthandler
import io
import json
import logging
import os
import pathlib
import sqlite3
import sys
import time
import traceback

CONTRACT = 1

# error.code → exit code (02 §3)
EXIT_CODES = {
    "failed": 1, "partial": 1, "crashed-child": 1, "bad-data": 1,
    "usage": 2, "not-set-up": 2, "version-skew": 2,
    "busy": 3, "anki-closed": 3, "anki-busy": 3, "anki-miner-busy": 3, "update-staged": 3,
    "needs-you": 4,
}

LOG_BYTES = 1024 * 1024     # cli.log rotates at 1 MB, three old ones kept (M-6 6)
LOG_BACKUPS = 3
EVENTS_KEPT = 200

# updater.MARKER_NAME, named here so a quick verb never imports the updater (urllib, zipfile)
UPDATE_MARKER = "pending_update.json"

log = logging.getLogger("surasura-cli")


class CliError(Exception):
    """A verb's failure with its contract code: becomes the `error` line and its exit code."""

    def __init__(self, code, message, **context):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context


class _ToLog(io.TextIOBase):
    """Stands in for sys.stdout / sys.stderr while a verb runs: a stray print from any module lands in the log, so
    stdout keeps only the JSON lines."""

    def writable(self):
        return True

    def write(self, text):
        if text.strip():
            log.info("output: %s", text.rstrip())
        return len(text)


_out = None             # the JSON channel: this process's own stdout
_err = None             # the real stderr: only for a log that can't be written
_progress = False
_verb = "?"
_fault_file = None


def open_channel(out=None):
    """Take stdout as the JSON channel, UTF-8 and line-buffered (02 §8: today's rewrap in app_entry.py isn't)."""
    global _out, _err
    if out is None:
        out = sys.stdout
        if hasattr(out, "reconfigure"):
            out.reconfigure(encoding="utf-8", line_buffering=True, newline="\n")     # lines end in \n, never \r\n
    _out = out
    _err = sys.stderr


def log_folder():
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "logs")


def _rotate(path):
    """cli.log → cli.log.1 → … .3 once it reaches 1 MB. The log is moved aside first: while another surasura-cli holds
    it open that fails and nothing shifts (the next start rotates it), so a rotation never half-happens."""
    if not (os.path.exists(path) and os.path.getsize(path) >= LOG_BYTES):
        return
    aside = f"{path}.{os.getpid()}.rotating"
    try:
        os.replace(path, aside)
    except OSError:
        return
    for n in range(LOG_BACKUPS - 1, 0, -1):
        if os.path.exists(f"{path}.{n}"):
            os.replace(f"{path}.{n}", f"{path}.{n + 1}")
    os.replace(aside, f"{path}.1")


_raise_exceptions = logging.raiseExceptions
_fault_was_enabled = False


def open_log():
    """cli.log under local data, rotated at 1 MB × 3, and faulthandler writing into it (a native crash leaves a trace).
    A log that can't be opened is said once on stderr; the verb still answers. A log that fails while writing is
    dropped silently: logging's own error report would land in the log again (stderr is the log while a verb runs)."""
    global _fault_file, _raise_exceptions, _fault_was_enabled
    close_log()
    _raise_exceptions, logging.raiseExceptions = logging.raiseExceptions, False
    try:
        folder = log_folder()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "cli.log")
        _rotate(path)
        handler = logging.FileHandler(path, encoding="utf-8", delay=True)
        handler.setFormatter(logging.Formatter("%(asctime)s pid=%(process)d %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
        _fault_file = open(path, "a", encoding="utf-8")
        _fault_was_enabled = faulthandler.is_enabled()
        faulthandler.enable(_fault_file, all_threads=True)
    except Exception as e:
        if _err is not None:
            try:
                _err.write(f"surasura-cli: the log can't be written: {e}\n")
                _err.flush()
            except Exception:
                pass


def close_log():
    global _fault_file
    for handler in list(log.handlers):
        log.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass                                # a broken log never fails the call
    if _fault_file is not None:
        faulthandler.disable()
        if _fault_was_enabled:                  # the caller's own (pytest's, in-process tests) comes back
            faulthandler.enable(sys.__stderr__, all_threads=True)
        _fault_file.close()
        _fault_file = None
    logging.raiseExceptions = _raise_exceptions


def _emit(line):
    if _out is None:
        return
    _out.write(json.dumps(line, ensure_ascii=True, separators=(",", ":")) + "\n")
    _out.flush()


def emit_progress(step, done, total=None):
    """A `progress` line, only when the caller asked for --progress."""
    if _progress:
        _emit({"type": "progress", "step": step, "done": done, "total": total})


def finish(**fields):
    """The `result` line. Returns exit code 0. A verb's fields never replace the envelope's."""
    clash = {"type", "contract", "ok"} & set(fields)
    if clash:
        raise ValueError(f"a verb's result may not set {sorted(clash)}")
    _emit({"type": "result", "contract": CONTRACT, "ok": True, **fields})
    return 0


def fail(code, message, **context):
    """The `error` line, also kept in the events file. Returns its exit code."""
    envelope = {"type": "error", "contract": CONTRACT, "ok": False, "code": code, "message": message}
    _emit({**envelope, **{k: v for k, v in context.items() if k not in envelope}})
    exit_code = EXIT_CODES.get(code, 1)
    _record_event({"time": datetime.datetime.now().isoformat(timespec="seconds"), "pid": os.getpid(),
                   "verb": _verb, "exit": exit_code, "code": code, "message": message})
    return exit_code


def replace_with_retry(src, dst, tries=5, wait=0.1):
    """os.replace, retried briefly: it fails while another process holds `dst` open, even a reader (02 §8)."""
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return True
        except PermissionError:
            if attempt < tries - 1:
                time.sleep(wait)
    return False


class _Locked:
    """Holds `path`'s byte 0 for a moment (04 §2's pattern; waits up to ~10 s). Only the events file uses it until E1.4's
    lock helper lands (P1.2)."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.f = open(self.path, "a+b")
        if sys.platform == "win32":
            import msvcrt
            self.f.seek(0)
            msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if sys.platform == "win32":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f, fcntl.LOCK_UN)
        finally:
            self.f.close()


def _record_event(event):
    """Append an error to cli-events.jsonl under its lock, so two failing calls never lose one. Once the file passes
    twice EVENTS_KEPT lines it is cut back to the newest EVENTS_KEPT (a reader holding it open only delays the cut)."""
    try:
        path = os.path.join(log_folder(), "cli-events.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
        with _Locked(path + ".lock"):
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
            with open(path, encoding="utf-8") as f:
                kept = [x for x in f.read().splitlines() if x.strip()]
            if len(kept) > 2 * EVENTS_KEPT:
                tmp = f"{path}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                    f.write("\n".join(kept[-EVENTS_KEPT:]) + "\n")
                if not replace_with_retry(tmp, path):
                    os.remove(tmp)
    except Exception:
        log.exception("the events file can't be written")


# --------------------------------------------------------------------------- #
# Checks at start
# --------------------------------------------------------------------------- #
def _lock_held(path):
    """True when another process holds `path`'s byte 0 (04 §2's lock pattern). Until E1.4's lock helper lands (P1.2)
    this probe is all the command line needs: it only asks, never creates the file or keeps the lock."""
    try:
        f = open(path, "r+b")
    except FileNotFoundError:
        return False
    except PermissionError:
        return True
    with f:
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
        except OSError:
            return True
    return False


def check_update():
    """An update staged (the window's pending_update.json) or swapping (the `update` lock): answer `update-staged`."""
    from app.path_utils import get_user_data_path, get_local_data_path
    if os.path.exists(os.path.join(get_user_data_path(), UPDATE_MARKER)) or \
            _lock_held(os.path.join(get_local_data_path(), "locks", "update.lock")):
        raise CliError("update-staged", "Surasura is installing an update. Try again once it has restarted.")


def check_token_stores():
    """Refuse (`version-skew`) when a token store was written by another schema than this program's (02 §7), opening
    each read-only so the check itself can never wipe one. An unreadable store is left to the verb that needs it."""
    from app import token_index
    for language in ("ja", "zh"):
        path = token_index.store_path_for(language)
        if not os.path.isfile(path):
            continue
        try:
            conn = sqlite3.connect(pathlib.Path(path).as_uri() + "?mode=ro", uri=True)
            try:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error as e:
            log.warning("token store %s not checked: %s", path, e)
            continue
        if version and version != token_index.SCHEMA_VERSION:
            raise CliError("version-skew",
                           "This command line and Surasura's word index are from different versions. "
                           "Open Surasura once, or update it.",
                           language=language, store_schema=version, schema=token_index.SCHEMA_VERSION)


# --------------------------------------------------------------------------- #
# The wrapper
# --------------------------------------------------------------------------- #
def run(verb, call, argv, progress=False):
    """Run one verb: `call()` returns the result's fields or raises. Every outcome becomes one line and an exit code;
    one log line per call (verb, exit code, duration, argv — argv never holds a secret)."""
    global _progress, _verb
    _progress, _verb = progress, verb
    started = time.monotonic()
    code = "interrupted"
    try:
        code = finish(**call())
    except CliError as e:
        log.info("%s: %s", e.code, e.message)
        code = fail(e.code, e.message, **e.context)
    except Exception as e:
        log.error("crashed:\n%s", traceback.format_exc())
        code = fail("failed", f"Surasura's command line failed ({type(e).__name__}: {e}). The details are in its log.")
    finally:
        log.info("verb=%s exit=%s %.3fs argv=%r", verb, code, time.monotonic() - started, argv)
    return code
