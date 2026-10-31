"""Calling Anki Miner (P1.3 row 1.3.5; API.md, the Integration Spec §4.1 and §4.4, 06-edges E7–E14 and W1).

Anki Miner is a separate program, called at arm's length: `AnkiMiner.exe --api <command>`, one JSON verdict on the
last line of stdout, exit 0 whenever a verdict was written (BUSY and SETUP_ERROR included); any other exit is a crash.
Its stdout is a pipe and its stderr goes nowhere (without a stdout handle its verdict is lost); every call has a
timeout and is killed at it; nothing opens a window (CREATE_NO_WINDOW).

- `find(settings)` — where it is: `connect_anki_miner_path`, then its installer's uninstall key (InstallLocation), then
  its default folder (%LOCALAPPDATA%\\Programs\\AnkiMiner). Absent -> None: the mine step is `skipped`, never an error.
- `version`, `profiles`, `settings_export` — read once a Connect run, again after any failure, every 15 min and
  whenever Anki Miner's program or settings files change (`stamp`; LF-mining row 25, amending E10's "read before
  every batch, never cached": PROVISIONAL, Michi's technical rule; `verbs._anki_miner_setup`); `check` before every batch, never cached (E9, E10: it updates itself).
- `mine_batch(...)` — one batch, holding Surasura's Anki-write lock (`anki-writer`, E1.4) from start to end: the
  version and `features` read again (or handed in: `known`), the profile chosen (`choose_profile`), the whitelist
  file rewritten (N10, until Z-1), the run file written (`runfile`: from 3.7, one entry a word, its `surface` and
  reading — Z-2), `mine` called, its results read back as Surasura's outcomes (IS §4.4): `made` with the note id,
  `duplicate`, `not_found`, `no_definition`, `media_failed`, `refused`, `not_attempted`, `uncertain`. Each returned
  `line_start` is checked against the one sent: off by more than 0.05 s, the card took another line, and the row says
  so. Then the cards made for names get `surasura::name` (G1.3: Anki Miner's tags belong to an episode, never to one
  word): one `addTags`, still inside the hold; when Anki doesn't take it, the note ids come back as `tag_pending`, a
  step of its own Connect's ledger resumes (`tag_names`; the notes are findable by the job's tag).

Failures are AnkiMinerError with a `kind` the runner (P2.4) acts on: `busy` (its window is open, or another run works:
retry later, E8), `writer-busy` (another Surasura program writes Anki), `reviewing` (you're reviewing: E2), `anki-closed` (E1), `quarantined` (Windows Security blocked it: WinError 225, never retried
silently, W1), `crashed` / `timeout` (the batch is `uncertain`: checked in Anki by the job's tag before any retry,
E11/E14), `unknown-version` (a schema Surasura wasn't built for, E12), `too-old` (a build before 3.5.0, never run), `refused` (a run file it refused), `no-reading` (a book's batch for an
Anki Miner that doesn't name `reading`, Z-9: never sent), `unreadable` (a video, subtitle or book it can't read), `setup` (its
setup is incomplete: `check`'s items name what), `absent`.
"""
import json
import os
import subprocess
import sys
import time

from app.connect import runfile, stopping

API_SCHEMA = 1
QUICK_TIMEOUT = 60.0            # version / profiles / check / settings-export
MINE_TIMEOUT = 3 * 60 * 60.0    # one mine call (sim.py's 3 h; R03:249)
SETUP_TIMEOUT = 60 * 60.0       # one `setup` call (Z-11): a language's dictionaries downloaded and indexed
# What Anki Miner's own `setup` (Z-11) sets right by itself: these of its `check` items (its language pack and its
# recommended dictionaries, frequency and pitch lists). A deck, a note type, a tool are never its (A4M1-2)
SETUP_ITEMS = frozenset(("dictionary", "resources", "language_pack"))
# What Surasura sets itself through Anki Miner's `settings-import` (Z-3, A4M1-2b): these of its `check` items — the
# deck, note type and fields a language's cards go to (`connect.miner_settings`)
SETTINGS_ITEMS = frozenset(("deck", "note_type", "fields"))
# Its `check` items a mine needs (the same nine in every build from 3.5.0 to its 2026-10-31 main), and those only its
# fetch, speech and OCR commands use, which its own `ready` leaves out (3.7's yt_dlp and speech_model; main's
# `_NOT_FOR_MINE` adds ocr and video_ocr): `unfinished`
MINE_ITEMS = SETUP_ITEMS | SETTINGS_ITEMS | frozenset(("anki", "ffmpeg", "ffprobe"))
NOT_FOR_MINE = frozenset(("yt_dlp", "speech_model", "ocr", "video_ocr"))
LINE_TOLERANCE = 0.05           # seconds: a returned line_start further off is another line (sim.py, IS:311)
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{15B09250-AC39-4792-A15A-B73BD8E218A1}_is1"
EXE = "AnkiMiner.exe"
CREATE_NO_WINDOW = 0x08000000
WINERROR_VIRUS = 225            # "Operation did not complete successfully because the file contains a virus"
DEFAULT_PROFILE = "Surasura"    # connect_anki_miner_profile's default (settings_manager)
# A5F4: the settings keys Surasura writes with `settings_import`, in plain words (a refusal never names a key)
KEY_WORDS = {"anki_deck_name": "the deck", "anki_note_type": "the note type", "anki_fields": "the fields",
             "card_type": "the card type", "pitch_category_format": "the pitch format",
             "ankiconnect_url": "Surasura's AnkiConnect address"}
# A5F2: a profile Surasura's setting names that Anki Miner lacks (`choose_profile`): what to do, never "make it in
# Anki Miner"
PROFILE_MADE = "Surasura makes it for you: Settings → Anki & mining → Finish its setup…"
PROFILE_UPDATE = ("Choose a profile Anki Miner has in Surasura's settings, or update Anki Miner from Surasura so "
                  "Surasura can make it.")
PROGRESS = "progress.json"      # a run's progress, in its folder (API.md; written at most every 0.25 s)
HEARTBEAT = "heartbeat"         # A5F1: touched by Surasura each poll of its setup, beside Anki Miner's progress file
# *Finish its setup*'s folder under local data (`services.anki_miner_setup`): the settings file and Anki Miner's
# `--progress` file while it runs, emptied after. Its folder or progress file moved within SETUP_FRESH_S is a setup
# running (`setting_up`, A2-6); one a Surasura that quit mid-setup left goes stale once Anki Miner is done.
SETUP_STAGING = "anki-miner-setup"
SETUP_FRESH_S = 600
POLL_S = 1.0                    # how often a mine call's progress is read while it runs (laptop round 5 #23)
# The read-only verbs (row 56): one still under way at a job's *Stop* is ended (`stopping.wait`), the job stopped
# before its step. Never `mine`, nor any verb that may write: Anki Miner's run is cancelled through its cancel file.
LOOK_UPS = frozenset(("version", "profiles", "check", "settings-export"))
# Each of a mine run's five stages (parsing, filtering, media, definitions, cards), as a share of its time: the
# episode's percent (`percent`). Measured on DevTest, two episodes of 50 words (fresh media): media 51–63 %, cards
# 30–43 %, the rest a few % (laptop round 5, 2026-10-22).
STAGE_SHARES = (0.05, 0.01, 0.57, 0.01, 0.36)

# Anki Miner's `features` names (Z-4; 3.7.0 `cli/api/contract.py` FEATURES), and the ask each answers. A name not
# here is a later addition: ignored until Surasura knows it.
FEATURES = {"named-words-whitelisted": "Z-1", runfile.WORD_FROM_LINE: "Z-2", "settings-import": "Z-3",
            runfile.SENTENCE_RULES_OFF: "Z-4", runfile.BOLD_TARGET: "Z-5", "filter-names": "Z-6",
            runfile.DRY_RUN: "Z-7", "fetch": "Z-8", "render": "Z-10", "media": "Z-10", "setup": "Z-11",
            "script-fold": "Z-12", "beside-window": "Z-13", runfile.READING: "Z-9"}
# Round 2's Z-9 (books and text in `mine`, 2026-10-28: Sonic, a must for 3.0): an episode naming `reading_file`. In
# FEATURES: `mines("books")` is True with an Anki Miner whose `version` names it, False with any other (alpha 4 M1)
READING = runfile.READING
# Round 2's Z-16 (an episode naming `audio_file`): its `features` name. Not in FEATURES until Surasura mines audio:
# `mines("audio")` is False with every Anki Miner until then (alpha 4 A4M1-3)
AUDIO = "audio-episodes"
# What Connect sets aside until Anki Miner mines it (`library.waits_for`'s kinds) -> the Z-ask that opens it
WAITS = {"books": "Z-9", "audio": "Z-16"}

# A verdict's error code -> the kind Surasura acts on
KINDS = {"BUSY": "busy", "ANKI_UNREACHABLE": "anki-closed", "SETUP_ERROR": "setup", "PROFILE_UNREADABLE": "setup",
         "BAD_RUN_FILE": "refused", "BAD_ARGUMENTS": "refused", "SUBTITLE_UNREADABLE": "unreadable",
         "VIDEO_UNREADABLE": "unreadable", "SOURCE_UNREADABLE": "unreadable", "MINING_FAILED": "failed", "CANCELLED": "cancelled",
         "INTERNAL": "crashed"}

# The outcome of each status (IS §4.4)
OUTCOMES = {"created": "made", "duplicate": "duplicate", "not_found": "not_found", "no_definition": "no_definition",
            "media_failed": "media_failed", "refused": "refused", "not_attempted": "not_attempted",
            "uncertain": "uncertain", "ready": "ready"}       # ready: a dry run would make it (Z-7)
# A run that stopped with one of these and wrote no result never reached Anki: refused, never uncertain
BEFORE_ANKI = frozenset(("VIDEO_UNREADABLE", "SUBTITLE_UNREADABLE", "SOURCE_UNREADABLE", "ANKI_UNREACHABLE", "SETUP_ERROR",
                         "PROFILE_UNREADABLE", "BAD_RUN_FILE", "CANCELLED"))
# When a word went as two entries (its card front, and Surasura's Word), the better outcome is the word's
_BEST = ("made", "ready", "duplicate", "uncertain", "media_failed", "refused", "no_definition", "not_attempted",
         "not_found")


class AnkiMinerError(Exception):
    """A call that gave no usable verdict, or a verdict refusing the work: `kind` (above), `message` (plain words or
    Anki Miner's own), `code` (Anki Miner's error code, when it gave one)."""

    def __init__(self, kind, message, code=None, verdict=None):
        super().__init__(message)
        self.kind, self.message, self.code, self.verdict = kind, message, code, verdict


# --------------------------------------------------------------------------- #
# Finding it
# --------------------------------------------------------------------------- #
def _registry_location():
    """InstallLocation from Anki Miner's per-user uninstall key (its Inno installer is per-user only), or None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            return winreg.QueryValueEx(key, "InstallLocation")[0] or None
    except OSError:
        return None


MIN_VERSION = (3, 5, 0)        # the first release with `--api` (IS §4.1)


def version_tuple(text):
    """"3.7.0" -> (3, 7, 0), padded to three parts ("3.5" -> (3, 5, 0)); None when it isn't a dotted version."""
    parts = []
    for piece in str(text or "").strip().lstrip("vV").split("."):
        digits = ""
        for ch in piece:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple((parts + [0, 0, 0])[:max(3, len(parts))]) if parts else None


def too_old(text):
    found = version_tuple(text)
    return found is not None and found < MIN_VERSION


def too_old_install(path):
    """The installer's version when the program at `path` is the one its installer put in place (InstallLocation)
    and it is older than 3.5.0, else None. Such a build has no `--api`: run with it, it opens its window."""
    folder = _registry_location()
    if not folder or not path:
        return None
    try:
        same = os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(os.path.join(folder, EXE)))
    except (TypeError, ValueError):
        return None
    installed = installed_version() if same else None
    return installed if installed and too_old(installed) else None


def installed_version():
    """DisplayVersion from Anki Miner's per-user uninstall key ("3.7.0"), or None (not installed by its installer, off
    Windows, under a test root). Read before Anki Miner is first run (P2.3's setup checks): a build older than 3.5.0
    has no `--api`, and running it opens its window."""
    if sys.platform != "win32" or os.environ.get("SURASURA_TEST_ROOT"):
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            value = winreg.QueryValueEx(key, "DisplayVersion")[0]
    except OSError:
        return None
    return str(value).strip() or None


def _default_location():
    base = os.environ.get("LOCALAPPDATA")
    return os.path.join(base, "Programs", "AnkiMiner") if base and sys.platform == "win32" else None


def home():
    """Anki Miner's home as the Anki Miner Connect starts reads it (3.9 `config/paths.py`): ANKI_MINER_HOME in this
    process's environment (the child inherits it), else ~/.anki_miner. Its gui_config.json holds the active profile
    and the field mapping, `profiles/<id>.json` the named profiles — what `--api` reads."""
    from pathlib import Path
    return os.environ.get("ANKI_MINER_HOME") or str(Path.home() / ".anki_miner")


def stamp(path):
    """What Anki Miner's look-ups read, as a change signal (S19: update only what changed; LF-mining R2-7, IK-r2-3):
    (mtime_ns, size) of its program `path`, its gui_config.json (written whole on every save), its profiles folder
    and each file in it. A file that isn't there stamps as absent; one that can't be read -> None (a change)."""
    def one(p):
        try:
            st = os.stat(p)
        except FileNotFoundError:
            return None
        return st.st_mtime_ns, st.st_size
    try:
        folder = os.path.join(home(), "profiles")
        try:
            names = sorted(e.name for e in os.scandir(folder) if e.is_file())
        except FileNotFoundError:
            names = []
        return (one(path), one(os.path.join(home(), "gui_config.json")), one(folder),
                tuple((n, one(os.path.join(folder, n))) for n in names))
    except OSError:
        return None


def find(settings):
    """The path of Anki Miner's program, or None when it isn't installed (E7)."""
    chosen = str((settings or {}).get("connect_anki_miner_path") or "").strip()
    if chosen:
        return chosen if os.path.isfile(chosen) else None
    if os.environ.get("SURASURA_TEST_ROOT"):
        return None             # a test (and a child it starts) never finds, let alone runs, a real Anki Miner
    for folder in (_registry_location(), _default_location()):
        if folder and os.path.isfile(os.path.join(folder, EXE)):
            return os.path.join(folder, EXE)
    return None


def _command(path):
    # A .py is run by this Python: the tests' fake Anki Miner (tests/connect/fake_anki_miner.py), a source checkout.
    return [sys.executable, path] if path.lower().endswith(".py") else [path]


# --------------------------------------------------------------------------- #
# One call
# --------------------------------------------------------------------------- #
_job_handle = None      # Windows: one job object for this process's Anki Miner calls, closed (and they ended) with it


def _bind(proc):
    """Windows: Anki Miner (and its ffmpeg children) ends when this process ends, however it ends — a Connect killed
    mid-batch never leaves an Anki Miner adding cards with no one holding Anki's write lock (adversary P2.4-A #4).
    Standard library `ctypes`; anything that fails leaves the call as it was."""
    global _job_handle
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if _job_handle is None:
            class _Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _Extended(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_uint64 * 6),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            handle = kernel32.CreateJobObjectW(None, None)
            if not handle:
                return
            info = _Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(wintypes.HANDLE(handle), 9, ctypes.byref(info),
                                                    ctypes.sizeof(info)):    # 9: JobObjectExtendedLimitInformation
                kernel32.CloseHandle(wintypes.HANDLE(handle))
                return
            _job_handle = handle
        kernel32.AssignProcessToJobObject(wintypes.HANDLE(_job_handle), wintypes.HANDLE(int(proc._handle)))
    except Exception:
        pass


def _stop(proc):
    """Stop a call past its timeout with every process it started (Anki Miner's ffmpeg children too): Connect's one
    process-ender (`stopping.end`; row 56)."""
    stopping.end(proc)


def _communicate(proc, timeout, on_poll=None, look_up=False):
    """`proc`'s stdout once it ends, waiting at most `timeout` s (TimeoutExpired past it): `stopping.wait` in slices of
    POLL_S — `on_poll()` each (a mine call's progress, laptop round 5 #23; its failure never stops the wait), and for a
    look-up the job's *Stop* asked (row 56)."""
    return stopping.wait(proc, timeout, on_poll, _stop, look_up=look_up, every=POLL_S)[0]


def api(path, args, timeout=QUICK_TIMEOUT, on_poll=None, bind=True):
    """Run `<path> --api <args…>` and return its verdict (a dict). Raises AnkiMinerError for a call with no verdict
    (absent, quarantined, crashed, timeout, unknown-version); a verdict with `ok: false` is returned as it is.
    `on_poll`: called every POLL_S while the call runs. A look-up (LOOK_UPS) still under way at the job's *Stop* is
    ended and raises `stopping.Stopped` (row 56: never an AnkiMinerError — nothing of it is kept). `bind` False: the
    call is never ended with this process (`_bind`) — Anki Miner's own `setup`, under its own run lock, finishes
    whenever Surasura quits (review A2-4)."""
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    look_up = bool(args) and args[0] in LOOK_UPS    # row 56: read before the program starts, never after
    try:
        proc = subprocess.Popen(_command(path) + ["--api", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, creationflags=flags)
        if bind:
            _bind(proc)
    except FileNotFoundError:
        raise AnkiMinerError("absent", "Anki Miner isn't installed where Surasura looked.") from None
    except OSError as e:
        if getattr(e, "winerror", None) == WINERROR_VIRUS:
            raise AnkiMinerError("quarantined", "Windows Security blocked Anki Miner. Check Windows Security → "
                                 "Protection history, then allow it if you trust it.") from None
        raise AnkiMinerError("crashed", f"Anki Miner couldn't be started: {e}") from None
    try:
        stdout = _communicate(proc, timeout, on_poll, look_up=look_up)
    except subprocess.TimeoutExpired:
        _stop(proc)
        raise AnkiMinerError("timeout", f"Anki Miner didn't answer within {int(timeout)} s, so it was stopped.") \
            from None
    lines = [line for line in stdout.decode("ascii", "replace").splitlines() if line.strip()]
    if proc.returncode != 0 or not lines:
        raise AnkiMinerError("crashed", f"Anki Miner stopped without an answer (exit code {proc.returncode}).")
    try:
        verdict = json.loads(lines[-1])
    except ValueError:
        raise AnkiMinerError("crashed", "Anki Miner's answer couldn't be read.") from None
    if not isinstance(verdict, dict) or verdict.get("schema") != API_SCHEMA:
        raise AnkiMinerError("unknown-version", "This Anki Miner isn't one Surasura has been checked with. "
                             "Update Surasura, or wait for an update that knows it.", verdict=verdict)
    return verdict


def _result(verdict):
    if not verdict.get("ok"):
        code = verdict.get("error")
        raise AnkiMinerError(KINDS.get(code, "failed"), verdict.get("message") or code or "Anki Miner refused.",
                             code=code, verdict=verdict)
    return verdict.get("result") or {}


def version(path):
    """{"app", "schema", "commands", "features"}: what this Anki Miner is and can do (read once a run: row 25, E10). A
    build its installer says is older than 3.5.0 is never run (it has no `--api`, and would open its window):
    AnkiMinerError `too-old`."""
    old = too_old_install(path)
    if old:
        raise AnkiMinerError("too-old", f"Anki Miner {old} is too old for Surasura: Connect needs 3.5.0 or later.")
    result = _result(api(path, ["version"]))
    if result.get("schema") != API_SCHEMA:
        raise AnkiMinerError("unknown-version", f"Anki Miner {result.get('app')} isn't one Surasura has been "
                             "checked with. Update Surasura, or wait for an update that knows it.")
    result.setdefault("features", [])
    return result


def features(info):
    """The Z-asks this Anki Miner says it answers (from `version`'s `features`)."""
    return {FEATURES[name] for name in info.get("features") or () if name in FEATURES}


def mines(kind, info=None):
    """Can Connect make cards from `kind` (`WAITS`: "books" — books and texts, Z-9; "audio" — audiobooks and podcasts,
    Z-16)? Only once Surasura knows the ask (`FEATURES` maps its name to it) and — given `info`, a `version` answer —
    this Anki Miner names it. Until then such an item waits by itself, never a *No video* (alpha 4 M1 / A4M1-3, Sonic
    2026-10-27: "I honestly don't want to ever have to open anki miner. Ever."); `info` None asks only whether this
    Surasura could."""
    ask = WAITS[kind]
    if ask not in FEATURES.values():
        return False
    return info is None or ask in features(info or {})


_NOW = {}           # `mines_now`'s last read: {"stamp": the setup record's (mtime_ns, size), "info": its Anki Miner}


def mines_now(kind):
    """Can Connect make cards from `kind` now — this Surasura knows its ask and the Anki Miner Connect's setup record
    last found (`setup.read_record`'s `anki_miner`, a `version` answer) names it (`mines`)? No record: no. The one
    answer for Connect's jobs (`runner.Steps.mines`) and the window's rows and *Mine* (`view_rows._mines`); the record
    is read again only once its file changed (a row a book's part: S19). Never raises."""
    if not mines(kind):
        return False                    # this build mines none of it whatever Anki Miner says: no record read
    from app.connect import setup
    try:
        st = os.stat(setup.record_path())
        stamp = (st.st_mtime_ns, st.st_size)
    except (OSError, ValueError):
        stamp = None
    if stamp is None or _NOW.get("stamp") != stamp:
        _NOW.update(stamp=stamp, info=(setup.read_record().get("anki_miner") if stamp is not None else None))
    info = _NOW["info"]
    return mines(kind, info if isinstance(info, dict) else {"features": []})


def can_set_up(info, items):
    """A4M1-2 / A4M1-2b: can Surasura do some of this Anki Miner's setup itself — one of the `check` items `items`
    names is one its `setup` (Z-11) sets right (`SETUP_ITEMS`), or one its `settings-import` (Z-3) does
    (`SETTINGS_ITEMS`: the deck, note type and fields), and it names that verb? The rest (ffmpeg) stays named (intent
    keeper IK-A2: what Surasura can do never waits for it)."""
    return bool(set(items or ()) & ours(info))


def unfinished(items, ready):
    """The failed `check` items ({name: item}) that keep a mine from starting, given its `ready` (Michi-K,
    PROVISIONAL): none while it says ready; else only those a mine needs (`MINE_ITEMS`), so an item a newer Anki Miner
    adds for another command (main's ocr, video_ocr) is never named as missing nor sent to an update. When none of
    them failed, every other failed item but NOT_FOR_MINE (one a newer build's mine needs), and when only those
    failed, those: what its `ready` stands on is named, never hidden."""
    if ready is True:
        return {}
    failed = {name: item for name, item in items.items() if not item.get("ok")}
    needed = {name: item for name, item in failed.items() if name in MINE_ITEMS}
    return needed or {name: item for name, item in failed.items() if name not in NOT_FOR_MINE} or failed


def ours(info):
    """The `check` items Surasura sets right itself with this Anki Miner (`can_set_up`)."""
    named = features(info or {})
    return (SETUP_ITEMS if "Z-11" in named else frozenset()) | (SETTINGS_ITEMS if "Z-3" in named else frozenset())


def setting_up():
    """Is Surasura's *Finish its setup* running Anki Miner's setup now (A2-6: a Connect run told BUSY meanwhile names
    the setup, never "Anki Miner is open")? Its folder is there, and it or the progress file Anki Miner writes in it
    moved within SETUP_FRESH_S — or Surasura's heartbeat file, touched every poll while `run_setup` waits (A5F1).
    Never raises."""
    try:
        from app.path_utils import get_local_data_path
        folder = os.path.join(get_local_data_path(), SETUP_STAGING)
        times = [os.stat(folder).st_mtime]
    except Exception:
        return False
    for name in (PROGRESS, HEARTBEAT):
        try:
            times.append(os.stat(os.path.join(folder, name)).st_mtime)
        except OSError:
            pass
    return time.time() - max(times) < SETUP_FRESH_S


def run_setup(path, language, profile, progress_path, on_poll=None):
    """Anki Miner's own `setup` (Z-11) for `language` under `profile` (None: its current settings): its language pack
    and recommended dictionaries downloaded and switched on, as its setup wizard does — Anki Miner's downloads, never
    Surasura's. Its `--progress` file is `progress_path` (its folder must exist). Under Anki Miner's run lock: its
    window open or a run of its own -> AnkiMinerError `busy`; a language that profile never mined -> `refused`. Never
    stopped part-way by Surasura (only a signal stops it cleanly, and a hidden program gets none): not ended when
    Surasura quits (`bind=False`: it finishes by itself), ended only past SETUP_TIMEOUT, an hour (a download that
    stalled; what finished stays installed and the next press resumes the rest). -> its `result`; a setup that
    installed only part -> AnkiMinerError `failed` naming what didn't install."""
    args = ["setup", "--language", language, "--progress", str(progress_path)] + (["--profile", profile]
                                                                                    if profile else [])
    beat = os.path.join(os.path.dirname(str(progress_path)), HEARTBEAT)

    def poll():
        # A5F1: a heartbeat — a file of Surasura's own beside the progress file, written each poll, so a long download
        # that writes no progress for SETUP_FRESH_S still reads as "finishing its setup" (`setting_up`), never "close
        # Anki Miner"; never the folder itself (review: a handle on it could meet Anki Miner's renames into it), and
        # never made when the folder is gone ("a" opens no folder)
        try:
            with open(beat, "a"):
                pass
            os.utime(beat)
        except OSError:
            pass
        if on_poll is not None:
            on_poll()
    verdict = api(path, args, timeout=SETUP_TIMEOUT, on_poll=poll, bind=False)
    if verdict.get("ok") or verdict.get("error"):
        return _result(verdict)
    result = verdict.get("result") or {}
    pieces = [("its language pack", result.get("language_pack"))] + \
        [(r.get("name") or r.get("id"), r) for r in result.get("resources") or () if isinstance(r, dict)]
    failed = [f"{name}: {r.get('message') or 'not installed'}" for name, r in pieces
              if isinstance(r, dict) and r.get("status") == "failed"]
    raise AnkiMinerError("failed", "Anki Miner's setup didn't finish" + (" — " + "; ".join(failed) if failed else "."))


def settings_import(path, language, values, folder, name=None, profile=None):
    """Anki Miner's own `settings-import` (Z-3, A4M1-2b): `values` (its settings keys: the deck, note type and fields,
    or {} for the language alone) written into the profile `profile` (an id), or into a new profile called `name`, a
    copy of the one its window uses — never that one (Anki Miner refuses it: `refused`). `language` is the profile's
    mining language after, as its window's switch sets it; a language that profile never mined is set up for it.
    The file it reads is written in `folder` (which must exist) and removed after. Under its run lock: its window open
    or a run of its own -> `busy`. Never ended with Surasura (`bind=False`: a settings write is finished, never cut).
    -> its `result` ({"profile", "created", "invalid_fields"}); a value it refused -> AnkiMinerError `refused` naming
    it (the profile keeps its own value for it)."""
    if bool(name) == bool(profile):
        raise ValueError("settings_import takes a new profile's name or an existing profile, one of them")
    os.makedirs(folder, exist_ok=True)
    file = os.path.join(folder, f"settings-{language}.{os.getpid()}.json")
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(values, f, ensure_ascii=False)
        args = ["settings-import", file, "--language", language] + (["--name", name] if name else
                                                                    ["--profile", profile])
        result = _result(api(path, args, bind=False))
    finally:
        try:
            os.remove(file)
        except OSError:
            pass
    refused = [str(key) for key in result.get("invalid_fields") or ()]
    if refused:
        said = list(dict.fromkeys(KEY_WORDS.get(key, "one of its other settings") for key in refused))
        raise AnkiMinerError("refused", "Anki Miner didn't take " + " or ".join(said) + " from Surasura.",
                             verdict=result)
    return result


def profiles(path):
    return _result(api(path, ["profiles"])).get("profiles") or []


def check(path, language, profile=None):
    """`check`'s {"ready", "items"} for `language` under `profile`."""
    args = ["check", "--language", language] + (["--profile", profile] if profile else [])
    return _result(api(path, args))


def settings_export(path, language, out, profile=None):
    """The export `--api settings-export` writes, read back and put in place at `out`. Row 56: Anki Miner writes it
    under a temporary name beside `out`, replaced in only once it is whole and read — an export ended mid-write (a
    press, a timeout, a crash) leaves the last whole one at `out`, never half of one, and its part is removed."""
    root, ext = os.path.splitext(out)
    part = f"{root}.{os.getpid()}.part{ext}"        # the extension kept: Anki Miner writes the JSON file it is named
    args = ["settings-export", "--language", language, "--out", part] + (["--profile", profile] if profile else [])
    try:
        _result(api(path, args))
        try:
            with open(part, encoding="utf-8") as f:
                export = json.load(f)
            os.replace(part, out)
        except (OSError, ValueError) as e:
            raise AnkiMinerError("crashed", f"Anki Miner's settings export couldn't be read: {e}") from None
        return export
    finally:
        try:
            os.remove(part)
        except OSError:
            pass                        # replaced in, or never written


def profile_id(listed, name):
    """The id of the profile called `name` (or with that id) among `profiles`' list, or None (E9). Names compare
    ignoring case, as Anki Miner keeps them apart."""
    for entry in listed:
        called = entry.get("name")
        if name == entry.get("id") or (isinstance(called, str) and called.casefold() == name.casefold()):
            return entry.get("id")
    return None


def choose_profile(info, listed, name):
    """The id of the Anki Miner profile Connect mines with — the run file, `check` and the settings export all name
    it, so one batch reads one profile. The one `connect_anki_miner_profile` names when Anki Miner has it. Once every
    named word is whitelisted (Z-1, 3.7) the "Surasura" profile is optional (Sonic, 2026-10-07): with the setting left
    at its default (or empty) and no such profile, the profile `profiles` marks active, your usual one (None only when
    none is marked: Anki Miner then reads its window's settings). A profile you named yourself that Anki Miner doesn't
    have is never swapped for another: AnkiMinerError `needs-you` (E9), as is a missing "Surasura" profile before Z-1
    (its whitelist is how the named words pass the name lists, IS-R3, N10)."""
    found = profile_id(listed, name) if name else None
    if found is not None:
        return found
    if name and name != DEFAULT_PROFILE:
        # A5F2: Surasura makes it (Z-3, *Finish its setup*), never Anki Miner's window; the setup check words it
        # again (`setup.PROFILE_SAY`)
        raise AnkiMinerError("needs-you", f'Anki Miner has no profile called "{name}", the one Surasura\'s Anki Miner '
                             "profile setting names. " + (PROFILE_MADE if "Z-3" in features(info) else PROFILE_UPDATE))
    if "Z-1" in features(info):
        return next((entry.get("id") for entry in listed if entry.get("active")), None)
    raise AnkiMinerError("needs-you", f'Anki Miner has no profile called "{DEFAULT_PROFILE}", which an Anki Miner '
                         "older than 3.7 needs to make Surasura's cards. Update Anki Miner from Surasura (Settings → "
                         "Anki & mining).")


# --------------------------------------------------------------------------- #
# The whitelist file (N10): until Z-1, how the named words pass Anki Miner's name lists
# --------------------------------------------------------------------------- #
def whitelist_path(language):
    from app.path_utils import get_local_data_path
    return os.path.join(get_local_data_path(), "connect", f"whitelist-{language}.txt")


def write_whitelist(language, names):
    """Rewrite `whitelist-<lang>.txt` with this batch's names, one a line, UTF-8 without a BOM, atomically. The
    "Surasura" profile points its whitelist at this file (set up once, P1.5-14)."""
    path = whitelist_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"{name}\n" for name in dict.fromkeys(names)))
    os.replace(tmp, path)
    return path


# --------------------------------------------------------------------------- #
# A batch
# --------------------------------------------------------------------------- #
def cancel(run_dir, run_id):
    """Ask a running (or queued) episode to stop: Anki Miner polls `<run_dir>/<run_id>/cancel` every 0.2 s."""
    folder = os.path.join(run_dir, run_id)
    os.makedirs(folder, exist_ok=True)
    open(os.path.join(folder, "cancel"), "a").close()


def read_progress(run_dir, run_id):
    """Where a run stands, from its `progress.json` (API.md: `{"stage", "stages", "done", "total"}`, the stages
    parsing, filtering, media, definitions, cards) -> {"stage", "stages", "done", "total"} (ints), or None (none yet,
    or one that can't be read: the next look reads it again)."""
    try:
        # read whole and closed before the parse: the file is held open as briefly as it can be, since on Windows
        # Anki Miner's replace of it is refused while it is open
        with open(os.path.join(run_dir, run_id, PROGRESS), "rb") as f:
            text = f.read()
        data = json.loads(text.decode("utf-8"))
        out = {key: data[key] for key in ("stage", "stages", "done", "total")}
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in out.values()):
        return None
    return out


def percent(progress):
    """How far a run is, 0–99 (100 is the run's end, never its progress file): its finished stages' shares of the
    run's time plus the share of the one under way that is done (STAGE_SHARES; another number of stages than
    measured: equal shares)."""
    stage, stages, done, total = (progress[k] for k in ("stage", "stages", "done", "total"))
    shares = STAGE_SHARES if stages == len(STAGE_SHARES) else (1.0 / stages,) * stages if stages else ()
    if not shares or stage < 1:
        return 0
    stage = min(stage, len(shares))
    part = sum(shares[:stage - 1]) + shares[stage - 1] * (min(done, total) / total if total else 0.0)
    return max(0, min(99, int(100 * part)))


def result_names(run_dir, run_id):
    """The `result-<n>.json` files a run's folder holds now."""
    try:
        return {name for name in os.listdir(os.path.join(run_dir, run_id))
                if name.startswith("result-") and name.endswith(".json") and name[7:-5].isdigit()}
    except OSError:
        return set()


def read_result(run_dir, run_id, name=None, before=()):
    """A run's result: the file its verdict names, else the newest written since `before` (the names there were
    before the call: an older attempt's result is never taken for this one) — or None. A file that can't be read is
    AnkiMinerError `crashed`: the batch is then checked in Anki by its tag."""
    if name is None:
        fresh = sorted(result_names(run_dir, run_id) - set(before), key=lambda n: int(n[7:-5]))
        if not fresh:
            return None
        name = fresh[-1]
    try:
        with open(os.path.join(run_dir, run_id, os.path.basename(name)), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise AnkiMinerError("crashed", f"Anki Miner's result couldn't be read: {e}") from None


def outcomes(words, rows, run_failed=False, features=()):
    """Surasura's outcome for each picked word (pick's `words`), from one run's result rows — one row per entry
    (`runfile.entries` under these `features`), in the run file's order: [{word, reading, outcome, note_id, mined_form,
    line_start, returned_start, other_line, from_line, filter, statuses, unit_index, location}]. A word sent as two
    entries takes the better one. A book's or a text's row (Z-9) has no time: `unit_index` and `location` say where
    its sentence is (`connect.reading.place` puts it on its part). `from_line`: made from its line (Z-2, counted as made); `filter`: why Anki Miner dropped it, where it says
    (Z-6, `duplicate-expression`). No rows at all (the run wrote no result) is `uncertain` when the run failed (it may
    have written to Anki), `not_attempted` otherwise."""
    rows, out, at = list(rows or ()), [], 0
    for word in words:
        names = runfile.entries(word, features)
        mine = rows[at:at + len(names)]
        at += len(names)
        # a row that isn't the entry it stands for (another build's order or count) proves nothing: uncertain
        statuses = [OUTCOMES.get(row.get("status"), "uncertain") if row.get("word") == name else "uncertain"
                    for row, name in zip(mine, names)] or ["uncertain" if run_failed else "not_attempted"]
        outcome = min(statuses, key=_BEST.index)
        row = next((r for r, s in zip(mine, statuses) if s == outcome), {})
        returned = row.get("line_start")
        other = returned is not None and abs(float(returned) - float(word["line_start"])) > LINE_TOLERANCE
        out.append({"word": word["word"], "reading": word["reading"], "outcome": outcome,
                    "note_id": row.get("note_id"), "mined_form": row.get("mined_form"),
                    "line_start": word["line_start"], "returned_start": returned, "other_line": other,
                    "from_line": row.get("from_line") is True, "filter": row.get("filter"),
                    "statuses": {r.get("word"): r.get("status") for r in mine},
                    "unit_index": row.get("unit_index"), "location": row.get("location")})
    return out


def preflight(path, language, profile_name, known=None):
    """Before every batch (E9, E10): what this Anki Miner is (`version`), the id of the profile Connect mines with
    (`choose_profile`), and its `check` for the language. `known`: (version answer, profile id) as this Connect run's
    look-ups read them (LF-mining row 25) — then only `check` is asked, still before every batch. Raises
    AnkiMinerError: `needs-you` when that profile is missing (`choose_profile`), `anki-closed` when Anki isn't
    reachable, `setup` naming what Anki Miner's own setup lacks."""
    if known is not None:
        info, profile = known
    else:
        info = version(path)
        profile = choose_profile(info, profiles(path), profile_name)
    ready = check(path, language, profile)
    items = {item.get("name"): item for item in ready.get("items") or () if isinstance(item, dict)}
    if items.get("anki") and not items["anki"].get("ok"):
        raise AnkiMinerError("anki-closed", "Anki isn't open (or AnkiConnect isn't installed).")
    if not ready.get("ready"):
        from app.connect import setup
        raise AnkiMinerError("setup", "Anki Miner's setup isn't finished — " + (setup._named(unfinished(items, False))
                                                                               or "it doesn't say what"))
    return info, profile


def tag_names(url, words, outcomes):
    """Add `surasura::name` to the cards made for names (pick marks each `name`): one `addTags`. The caller holds
    `anki-writer`. Returns the note ids tagged; raises anki_connect.AnkiError when Anki refuses or is gone."""
    from app import anki_connect
    ids = [o["note_id"] for w, o in zip(words, outcomes)
           if w.get("name") and o["outcome"] == "made" and o.get("note_id") is not None]
    if ids:
        anki_connect.invoke("addTags", url, notes=ids, tags=runfile.NAME_TAG)
    return ids


def mine_batch(path, language, job, video, subtitle, words, mapping, profile_name, run_dir, url, attempt=1,
               subtitle_offset=0.0, timeout=MINE_TIMEOUT, wait=0.0, expect_profile=None, on_progress=None,
               known=None, should_stop=None, show=None, reading=None):
    """One batch of one episode, end to end (§ above), holding `anki-writer` (waiting up to `wait` s for another
    writer; still held -> AnkiMinerError `busy`). `words`: pick's; `mapping`: fields.Mapping (from this profile's
    export); `profile_name`: `connect_anki_miner_profile`; `url`: AnkiConnect's address, for the names' tag. Returns
    {"run_file", "run", "result", "outcomes", "app", "features", "tagged", "tag_pending"}; raises AnkiMinerError
    (busy, anki-closed, needs-you, setup, refused, crashed …). `expect_profile`: the profile id the words were
    picked for (P1.3-AM37 #5, the runner's half): another one active now -> AnkiMinerError `profile-changed`, before
    anything is mined (the runner picks again). `on_progress(progress)`: while the mine call runs, each `read_progress`
    of its run that answered (laptop round 5 #23: the row moves while Anki Miner works). `known`: `preflight`'s.
    `should_stop()` (laptop round 8 #47, *Stop*): asked at every poll; True -> the run's cancel file (`cancel`), held at every
    poll from then on and removed once the call is over (Anki Miner 3.10 clears an unconsumed one as it starts):
    Anki Miner ends at its own next check (0.2 s), every note it wrote whole. The answer then carries `stopped`
    (an AnkiMinerError `cancelled` too, its `stopped` set). `show` (laptop round 8 #50, LF4-3): the title of the show
    the episode belongs to: every card it makes also carries `runfile.from_tag(show)`. `reading` (Z-9): the book's or
    the text's file Anki Miner reads (an Anki Miner naming `reading` only): `video` and `subtitle` unused, each word
    named by its sentence."""
    from app import anki_connect, locks
    try:
        held = anki_connect.writer("Connect's mine step", wait=wait)
    except locks.Busy as e:
        raise AnkiMinerError("writer-busy", anki_connect.busy_message(e)) from None
    with held:
        if anki_connect.reviewing(url):         # E2: never a write while you review, checked inside the hold
            raise AnkiMinerError("reviewing", "You're reviewing in Anki. Cards are made once you've finished.")
        try:
            done = _mine_held(path, language, job, video, subtitle, words, mapping, profile_name, run_dir, attempt,
                              subtitle_offset, timeout, expect_profile, on_progress, known, should_stop, show,
                              reading)
        except runfile.RunFileError as e:
            raise AnkiMinerError("refused", f"The run file for Anki Miner couldn't be written: {e}") from None
        done["tagged"], done["tag_pending"] = [], []
        try:
            if anki_connect.reviewing(url):
                raise anki_connect.AnkiError(anki_connect.REVIEWING, "refused")
            done["tagged"] = tag_names(url, words, done["outcomes"])
        except anki_connect.AnkiError:
            done["tag_pending"] = [o["note_id"] for w, o in zip(words, done["outcomes"])
                                   if w.get("name") and o["outcome"] == "made" and o.get("note_id") is not None]
        return done


def _mine_held(path, language, job, video, subtitle, words, mapping, profile_name, run_dir, attempt,
               subtitle_offset, timeout, expect_profile=None, on_progress=None, known=None, should_stop=None,
               show=None, reading=None):
    info, profile = preflight(path, language, profile_name, known)
    if expect_profile is not None and profile != expect_profile:
        raise AnkiMinerError("profile-changed", "Anki Miner's profile changed since the words were picked.")
    asks, named = features(info), info.get("features")
    if "Z-1" not in asks:
        write_whitelist(language, [name for word in words for name in runfile.entries(word, named)])
    if reading is not None and READING not in (named or ()):
        # an Anki Miner that no longer names `reading` (another one installed since the pick): nothing sent; the job
        # waits as a book does (`runner.Steps.mine`)
        raise AnkiMinerError("no-reading", "This Anki Miner can't read books or texts.", verdict=info)
    run_id = f"{job}-{attempt}"
    tags = " ".join(t for t in (runfile.job_tag(job), runfile.from_tag(show)) if t)
    if reading is not None:
        episode = runfile.reading_episode(run_id, reading, runfile.word_requests(words, named, book=True), tags)
    else:
        episode = runfile.episode(run_id, video, subtitle, runfile.word_requests(words, named), tags=tags,
                                  subtitle_offset=subtitle_offset)
    data = runfile.build(run_dir, language, [episode], profile=profile,
                         run_config=runfile.config(mapping, info.get("app"), named))
    run_path = runfile.write(os.path.join(run_dir, f"run-{attempt}.json"), data)
    before = result_names(run_dir, run_id)
    try:            # review A2: a cancel file left by a stopped call of this run id (a refused attempt is reused)
        os.remove(os.path.join(run_dir, run_id, "cancel"))
    except OSError:
        pass
    done = {"run_file": run_path, "run": None, "result": None, "app": info.get("app"), "features": sorted(asks),
            "error": None, "_before": before}

    cancelled = []                  # #47: a Stop asked during the call (asked until it is, then held)

    def poll():
        # the cancel file stands while the Stop does: Anki Miner 3.10 deletes an unconsumed one once, before its
        # setup (a second or two in) — written once, a Stop pressed as the call began was lost
        if should_stop is not None and (cancelled or should_stop()):
            cancel(run_dir, run_id)
            cancelled[:] = [True]
        if on_progress is not None:
            progress = read_progress(run_dir, run_id)
            if progress is not None:
                on_progress(progress)
    poll = poll if (on_progress is not None or should_stop is not None) else None
    try:
        return _mine_call(path, run_dir, run_id, run_path, data, done, words, named, timeout, poll, cancelled)
    except AnkiMinerError as e:
        e.stopped = bool(cancelled)
        raise
    finally:
        if cancelled:               # the call over: the file it was held by goes too (none left for the next call)
            try:
                os.remove(os.path.join(run_dir, run_id, "cancel"))
            except OSError:
                pass


def _mine_call(path, run_dir, run_id, run_path, data, done, words, named, timeout, poll, cancelled):
    """`_mine_held`'s call to Anki Miner and the reading of its answer -> `done` (with `stopped`: a *Stop* cancelled
    the run)."""
    before = done.pop("_before")
    done["stopped"] = False
    try:
        verdict = api(path, ["mine", run_path], timeout=timeout, on_poll=poll)
        refused = (not verdict.get("ok") and verdict.get("error") == "BAD_RUN_FILE"
                   and any(k in (verdict.get("message") or "") for k in runfile.SENTENCE_KEYS))
        if refused and any(k in data.get("config", {}) for k in runfile.SENTENCE_KEYS):
            # A build that refuses the two sentence keys while it reports 3.6 (am-upstream D1): once more without them
            run_path = done["run_file"] = runfile.write(run_path, runfile.without_sentence_keys(data))
            verdict = api(path, ["mine", run_path], timeout=timeout, on_poll=poll)
    except AnkiMinerError as e:
        # A crash or a timeout after the run: Anki Miner writes the result before its verdict, so a complete one
        # may be there. Without it, the batch is uncertain: the caller checks Anki by the job's tag (E11, E14).
        if e.kind not in ("crashed", "timeout"):
            raise
        result = read_result(run_dir, run_id, before=before)
        if result is None:
            raise
        done.update(result=result, error=e.kind, outcomes=outcomes(words, result.get("words"), True, named),
                    stopped=bool(cancelled))
        return done
    run = next((r for r in verdict.get("runs") or [] if r.get("run_id") == run_id), None)
    if not verdict.get("ok") and run is None:
        result = read_result(run_dir, run_id, before=before) if verdict.get("error") == "INTERNAL" else None
        if result is None:
            _result(verdict)                # a refusal of the whole call: busy, anki-closed, refused, setup …
        done.update(result=result, error="crashed", outcomes=outcomes(words, result.get("words"), True, named),
                    stopped=bool(cancelled))
        return done
    if run is not None and not run.get("ok") and not run.get("file") and run.get("error") in BEFORE_ANKI:
        # stopped before anything reached Anki (a video or subtitle it can't read, Anki gone at its own check,
        # cancelled before the run began): nothing is uncertain; the batch is refused with its reason
        raise AnkiMinerError(KINDS.get(run["error"], "failed"), run.get("message") or run["error"], code=run["error"])
    result = read_result(run_dir, run_id, run["file"]) if run is not None and run.get("file") else None
    done.update(run=run, result=result,
                outcomes=outcomes(words, (result or {}).get("words"), run is None or not run.get("ok"), named),
                stopped=bool(cancelled))
    return done


def tag_query(tag):
    """A search for one tag as written: Anki reads _ and * in a search as wildcards."""
    from app import anki_connect
    return 'tag:"' + anki_connect.escape_query(tag).replace("_", "\\_").replace("*", "\\*") + '"'


def uncertain_by_tag(url, job, words, word_field):
    """After a crash or a timeout (E11, E14): which words did reach Anki? Reads the notes carrying the job's tag
    (read-only) and marks a word `made` when a note's word field holds one of its names, its Word or its spelling —
    or the kana fold of one: Anki Miner writes the form it placed the word by, which can be the dictionary form
    rather than the name sent. Returns outcomes as `outcomes` does, the rest left `uncertain`."""
    from app import anki_connect, anki_match
    ids = anki_connect.find_notes(url, tag_query(runfile.job_tag(job)))
    notes = anki_connect.notes_info(url, ids) if ids else []
    made = {}
    for note in notes:
        value = ((note.get("fields") or {}).get(word_field) or {}).get("value")
        if value:
            value = anki_match.card_word(value) or value.strip()
            made.setdefault(value, note.get("noteId"))
            made.setdefault(anki_match.fold_kana(value), note.get("noteId"))
    out = []
    for word in words:
        names = [n for n in (*word["sent"], word["word"], word.get("orth")) if n]
        names += [anki_match.fold_kana(n) for n in names]
        note_id = next((made[n] for n in names if n in made), None)
        out.append({"word": word["word"], "reading": word["reading"],
                    "outcome": "made" if note_id is not None else "uncertain", "note_id": note_id,
                    "mined_form": None, "line_start": word["line_start"], "returned_start": None,
                    "other_line": False, "from_line": False, "filter": None, "statuses": {}})
    return out
