"""hato's own update, started by Surasura once a day (Hato-UP, 3.0.18; Sonic 2026-11-21: Surasura starts hato's own
quiet update once a day while hato isn't open; Settings shows hato's version and whether it is up to date). Qt-free.

hato owns its update (3.0 ROLES.md, *hato*: Surasura only starts it). Surasura downloads, reads and replaces none of
hato's files: it starts **hato's own** `hato-cli update --auto` — the call hato's tray and its 03:00 run make (hato's
RUNBOOK LAYER 11g) — and hato decides the rest: its own once-a-day check, its *Update automatically* switch, a copy
another program holds or a source checkout (silent), a version turned away. Then `hato-cli update --check --if-due
--json` gives hato's answer for Settings' row (`status`): the one `--auto` just remembered, so no second ask — except when
hato couldn't tell (offline, GitHub's limit), which hato never remembers: then it asks once more (offline that ask fails
at once). network.md, *Tool-driven*, has the call in full.

- **Installing it** (HATO-UPDATING, 3.0.20): `--auto` only downloads and checks a release (*stages* it). hato puts it in
  place by itself only from its tray (off by default) or its daily run (opted into); otherwise it waits for *Restart now*
  in hato's window — and the row said *updating…* for days. So an answer `ready` is followed by `hato-cli update
  --quiet-install --json` (hato 1.4.3 and later: the daily run's own quiet install, under its rules — *Update
  automatically* on, nothing of hato open, no tray — nothing reopens). `applying`: the row says *updating…* and the next
  look (LOOK_S on) reads hato's answer once more (`_confirm`). Anything else — an older hato's usage error (exit 2),
  `waiting`, no answer — the row says the release is **ready in hato** (`READY`): open hato to install it.

- **When** (`attempt`): at most once a day — the attempt claimed in `hato_update.json` (local data) before hato is
  started, so a window closed mid-way or a second window finds none due — after the window booted, on the scheduler's
  turn (`gentle.hold(KIND)`: never while you review in Anki or the PC is busy; on a gentle PC one heavy job at a time),
  never while one of hato's programs runs from its folder (`hato_open`) or Surasura's own hato run is going
  (`no_subs.finding`), only while *Check for updates* is on and never under `SURASURA_NO_UPDATE_CHECK`.
- **Nothing happens** with no hato (no tools entry, its `cli` gone): no file is written, nothing is started. A hato
  with no `update` command (its usage error, exit 2) is remembered as such: Settings then shows its version alone.
- **Quiet:** hidden, below normal priority, no dialog. A failure (it couldn't start, no answer in time, no network)
  is logged and tried the next day (Settings: *couldn't check*).

`keep(settings, stop)` is the window's daemon thread (`Chores.started`): `attempt` now and then until the window
closes. Light: the standard library; the scheduler, the tools entry and the process list are imported when used.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time

STATE = "hato_update.json"
KIND = "hato-update"            # the scheduler's kind (`gentle.BACKGROUND`)
EVERY_S = 24 * 3600             # at most once a day
LOOK_S = 300.0                  # hato open, Surasura's own hato run, or the scheduler's turn: looked at again then
IDLE_S = 3600.0                 # nothing due (or nothing to do): looked at again then, for a window left open for days
UPDATE_WAIT_S = 15 * 60         # hato's own `update_now` waits this for its `--auto` child (a download: minutes)
ANSWER_WAIT_S = 60              # `--check --if-due --json`: hato's remembered answer, or one ask of GitHub
NO_CHECK_ENV = "SURASURA_NO_UPDATE_CHECK"
USAGE = 2                       # hato's usage error: a hato that has no `update` command
PROGRAMS = ("hato", "hato-cli", "hato-watch", "hato-update")     # hato's programs (its update's REQUIRED_ENTRIES)
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

INSTALL = ("update", "--quiet-install", "--json")   # hato 1.4.3: what `--auto` staged goes in now, quietly
SAID_S = 3600.0                 # *updating…* after hato's `applying` for at most this, unless its answer is read again

UP_TO_DATE, UPDATING, NO_CHECK, OUT, READY = "up-to-date", "updating", "couldnt-check", "out", "ready"
NOT_ALLOWED, NO_HATO, NOT_DUE, WAIT, DONE = "not-allowed", "no-hato", "not-due", "wait", "done"
INSTALLING = "installing"       # hato took its release in just now: its answer is read again on the next look


def _log(line):
    try:
        from app.path_utils import write_app_log
        write_app_log(f"hato's update: {line}")
    except Exception:
        pass


def path():
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), STATE)


def _iso(at):
    return datetime.datetime.fromtimestamp(at, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds(text):
    try:
        return datetime.datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def read_state():
    """The kept state, or {} (none yet, torn, unreadable just now). Never raises."""
    return _load() or {}


def _load():
    """The kept state; {} when there is none or it is torn; None when it is there but can't be opened just now (read as
    not due). Never raises."""
    try:
        with open(path(), "r", encoding="utf-8") as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except FileNotFoundError:
        return {}
    except ValueError:
        return {}
    except Exception:
        return None


def _write(state):
    """Atomically (temp + replace) -> written or not. Never raises."""
    temp = None
    try:
        target = path()
        temp = f"{target}.{os.getpid()}.{threading.get_ident()}.tmp"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(temp, target)
        return True
    except Exception as e:
        _log(f"its state wasn't written ({e!r})")
        if temp:
            try:
                os.remove(temp)
            except OSError:
                pass
        return False


def due(state, now):
    """Is the day's attempt due: never tried, the last one 24 h ago or more, or one in the future (the clock went back)."""
    at = _seconds((state or {}).get("tried_at"))
    return at is None or now - at >= EVERY_S or at > now


def hato_cli():
    """hato's command line from its tools entry (`tools_entry.read`), or None: no hato, or its `cli` gone. Never raises."""
    try:
        from app import tools_entry
        entry = tools_entry.read("hato")
    except Exception:
        return None
    cli = entry.get("cli") if isinstance(entry, dict) else None
    return cli if isinstance(cli, str) and cli and os.path.isfile(cli) else None


def hato_open(cli):
    """Does one of hato's programs run from `cli`'s folder (its window, tray, a run, its updater)? Windows only (elsewhere
    False). A look that fails counts as open: unsure is not now."""
    folder = os.path.dirname(os.path.abspath(cli))
    ext = ".exe" if sys.platform == "win32" else ""
    try:
        from app import updater
        return bool(updater._processes_running([os.path.join(folder, name + ext) for name in PROGRAMS]))
    except Exception:
        return True


def _finding():
    try:
        from app import no_subs
        return no_subs.finding()
    except Exception:
        return False


def _turn():
    """The scheduler's word for KIND now (None: go). None with no scheduler (a test, a command-line run)."""
    try:
        from app.services import gentle
        return gentle.hold(KIND)
    except Exception:
        return None


def allowed(settings):
    """*Check for updates* on (`settings_manager.update_check_on`: off, no update request is sent at all) and the real
    call not gated (NO_CHECK_ENV, set for every test)."""
    from app import settings_manager
    return settings_manager.update_check_on(settings) and not os.environ.get(NO_CHECK_ENV)


def _call(argv, wait, popen, read=True):
    """`argv` hidden, below normal priority, its output read (`read`; else none taken: `--auto` prints nothing, and a pipe
    nobody reads after a wait ran out could fill and stall hato) -> (exit code, stdout bytes); (None, b"") when it
    couldn't start, failed in any way, or gave no answer within `wait` s — then `--auto` (unread) is left to finish on its
    own (hato's own download is never cut off), an answer's read is stopped (only telling: nothing of hato's is cut)."""
    from app.connect import open_anki, power
    try:
        proc = power.popen_below_normal(argv, popen=popen, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE if read else subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW,
                                        env=open_anki.environment(), cwd=os.path.dirname(os.path.abspath(argv[0])))
    except Exception as e:
        _log(f"hato couldn't be started ({e!r})")
        return None, b""
    try:
        out, _err = proc.communicate(timeout=wait)
    except subprocess.TimeoutExpired:
        _log(f"no answer from hato in {wait:.0f} s: tried again tomorrow")
        if read:
            try:
                proc.kill()
            except Exception:
                pass
        return None, b""
    except Exception as e:
        _log(f"hato's answer couldn't be read ({e!r})")
        return None, b""
    return proc.returncode, out or b""


def _answer(out):
    """hato's `--json` answer (its last `{"type": "update", …}` line) -> {kind, version, current, reason} or None."""
    for line in reversed((out or b"").decode("utf-8", "replace").splitlines()):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "update" and obj.get("kind") in ("none", "ready", "tell"):
            return {key: obj.get(key) if isinstance(obj.get(key), str) else None
                    for key in ("kind", "version", "current", "reason")}
    return None


def _installing(out, latest):
    """hato's `--quiet-install --json` answer -> True when its last `applying` / `waiting` line says it is installing
    `latest` (the release its answer named) now."""
    for line in reversed((out or b"").decode("utf-8", "replace").splitlines()):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("type") in ("applying", "waiting"):
            return obj.get("type") == "applying" and obj.get("version") == latest and _parts(latest) is not None
    return False


def _install(cli, latest, popen):
    """hato's own quiet install of the release `--auto` staged (`INSTALL`) -> True when hato says it is installing
    `latest` now. An older hato has no such command (its usage error): the release waits for a press in hato."""
    code, out = _call([cli, *INSTALL], ANSWER_WAIT_S, popen)
    if code == 0 and _installing(out, latest):
        _log(f"hato is installing {latest} by itself")
        return True
    _log(f"hato {latest} waits for Restart now in hato's window" if code is not None else
         f"hato {latest} waits: hato's quiet install gave no answer")
    return False


def run(cli, now, popen=None):
    """The day's attempt (claimed): hato's `update --auto`, then its answer, then — a release it can install — its quiet
    install -> the state as kept (`installing`: hato said it is installing that release). Never raises."""
    state = {"tried_at": _iso(now)}
    code, _out = _call([cli, "update", "--auto"], UPDATE_WAIT_S, popen, read=False)
    if code == USAGE:
        state["unsupported"] = True             # a hato with no `update` command: its version alone in Settings
    elif code is not None:
        code, out = _call([cli, "update", "--check", "--if-due", "--json"], ANSWER_WAIT_S, popen)
        state["answer"] = _answer(out) if code == 0 else None
        answer = state["answer"] or {}
        if answer.get("kind") == "ready" and _install(cli, answer.get("version"), popen):
            state["installing"] = answer.get("version")
    else:
        state["answer"] = None
    if "answer" in state and state["answer"] is None:
        _log("hato gave no answer: tried again tomorrow")
    _write(state)
    return state


def _confirm(cli, state, popen=None):
    """After hato's quiet install: its answer read once more (`--check --if-due`: the day's answer judged against the
    hato installed now — no ask of GitHub when the day's was remembered), `installing` dropped -> the state as kept. The
    day's attempt stays spent. Never raises."""
    code, out = _call([cli, "update", "--check", "--if-due", "--json"], ANSWER_WAIT_S, popen)
    kept = {key: value for key, value in state.items() if key != "installing"}
    kept["answer"] = _answer(out) if code == 0 else None
    _write(kept)
    return kept


def attempt(settings, now=None, popen=None, stopped=lambda: False):
    """One look (the window's thread, `keep`) -> NOT_ALLOWED, NO_HATO, NOT_DUE, WAIT (hato open, Surasura's own hato
    run, the scheduler's turn: look again in LOOK_S; or the quit began: `stopped()`), INSTALLING (hato is installing its
    release: its answer is read again on the next look, LOOK_S on) or DONE. Never raises."""
    now = time.time() if now is None else now
    try:
        if not allowed(settings):
            return NOT_ALLOWED
        cli = hato_cli()
        if cli is None:
            return NO_HATO
        state = _load()
        if state is None or not (due(state, now) or state.get("installing")):
            return NOT_DUE
        if _turn() or _finding() or hato_open(cli) or stopped():
            return WAIT
        if state.get("installing") and not due(state, now):
            _confirm(cli, state, popen)
            return DONE
        claimed = {key: value for key, value in state.items() if key != "installing"}
        claimed["tried_at"] = _iso(now)
        if not _write(claimed):                 # an attempt that can't be kept asks nothing (it would ask every look)
            return NOT_DUE
        return INSTALLING if run(cli, now, popen).get("installing") else DONE
    except Exception as e:
        _log(f"the look failed ({e!r})")
        return NOT_DUE


def keep(settings, stop, popen=None):
    """(A daemon thread, the window's: `Chores.started`.) `attempt` now, then again LOOK_S on while it waits its turn,
    IDLE_S on otherwise, until `stop` (a threading.Event) is set. `settings()`: the settings now."""
    while not stop.is_set():
        try:
            outcome = attempt(settings(), popen=popen, stopped=stop.is_set)
        except Exception:
            outcome = NOT_DUE
        stop.wait(LOOK_S if outcome in (WAIT, INSTALLING) else IDLE_S)


def start(settings, stop):
    """`keep` on its own daemon thread -> the thread."""
    thread = threading.Thread(target=keep, args=(settings, stop), name="hato-update", daemon=True)
    thread.start()
    return thread


# --- Settings' row ------------------------------------------------------------------------------------------------- #
def _parts(version):
    """'1.4.2' -> (1, 4, 2); anything else (hato's one strict shape: ASCII X.Y.Z, no `rc`, no `v`) -> None."""
    got = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", version) if isinstance(version, str) else None
    return tuple(int(n) for n in got.groups()) if got else None


def _newer(candidate, current):
    a, b = _parts(candidate), _parts(current)
    return a is not None and b is not None and a > b


def status(installed, state=None, now=None):
    """hato's update as Settings says it, for the hato `installed` (its entry's version) -> (word, latest) — word one of
    UP_TO_DATE, UPDATING (hato said it is installing that one now: SAID_S at most, unless its answer is read again),
    READY (a newer one hato can install, waiting for Restart now in hato's window), OUT (a newer one hato can't install
    in this copy), NO_CHECK (the last attempt got no answer, or hato couldn't tell) — or (None, None): nothing to say
    (never tried, a hato with no `update` command, a copy another program holds). Compared with the newer of the entry's
    version and the one hato's answer says runs (an entry hato hasn't rewritten since its quiet install). Never raises."""
    try:
        now = time.time() if now is None else now
        state = read_state() if state is None else state
        if state.get("unsupported") or "answer" not in state:
            return None, None
        answer = state.get("answer")
        if not isinstance(answer, dict):
            return NO_CHECK, None
        kind, latest = answer.get("kind"), answer.get("version")
        if kind == "none" and not latest:
            return (None, None) if answer.get("reason") == "held" else (NO_CHECK, None)
        if kind != "none" and _parts(latest) is None:
            return NO_CHECK, None               # a newer one named in no X.Y.Z: never read as "up to date"
        current = answer.get("current")
        if _newer(current, installed):
            installed = current
        if not _newer(latest, installed):
            return UP_TO_DATE, None
        if kind != "ready":
            return OUT, latest
        at = _seconds(state.get("tried_at"))
        said = state.get("installing") == latest and at is not None and 0 <= now - at < SAID_S
        return (UPDATING if said else READY), latest
    except Exception:
        return None, None
