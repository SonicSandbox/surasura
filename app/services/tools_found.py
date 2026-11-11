"""Which of the other tools are here — one answer for Settings, *Needs you*, Anki Miner's card in Connections and the
setup wizard (laptop fixes row 13; its review's B2-7 / IK2-3: each had decided it on its own).

- `tools_found(settings)` -> `Found(hato, miner)`: `hato` — its usable entry in the shared tools folder
  (`tools_entry.read`, as its Connections row reads it); `miner` — `MISSING` or `INSTALLED` (`anki_miner.find`: the
  path chosen, else where its installer puts it). Two file looks: a worker's call, never the window's thread. A look
  that fails counts its tool absent (its rows stay hidden, nothing is written).
- `hato_version()`: hato's version from that entry ("" when it names none), or None: not here.
- `miner_level(state)`: a fuller look's state — the wizard's (`anki_miner_setup.look`: missing · too-old · needs-setup
  · ready) or the card's (`settings_values.card_state`: missing · setup · ready) — on the same scale: `MISSING`,
  `INSTALLED` (too old, or its own setup not finished) or `READY`.
- `make_cards_shown(level, on=False, ready=False)`: **the** rule for "when is *Make cards for me* offered", with its two
  answers — each caller asks the one its own rule asks:
  - installed (`ready=False`; Settings, *Needs you*, Anki Miner's card): any level above `MISSING` — what they can know
    without asking Anki or running Anki Miner; what still needs doing is said beside it (the card's steps, Connect's own
    reason) — or while it is on already (M3: the switch is the way off; then, off, it collapses to the "needs Anki
    Miner" line);
  - ready (`ready=True`; the setup wizard, WZ-4, Sonic 2026-10-14: on by default once Anki Miner is *ready*): only
    `READY`, from the wizard's full look.
- `connect_hato(folder, settings)`: *Find hato…* (Michi-HD; Mattias's 3.0.0 report, 2026-11-11: his hato, unpacked
  on his D: drive, never seen). hato writes its entry (`hato.json`) only when it starts and Surasura's own is there
  already, so a hato last opened before Surasura was installed — or moved since — stays unseen. The learner picks
  hato's folder (the folder itself, or the `hato` folder its zip unpacks into); Surasura's entry is written fresh and
  hato is opened from there once, so hato connects itself (its entry stays hato's to write: 09-hato-layer §3), and its
  entry is looked at until it names that folder -> `Connected(version, why)`.

Qt-free, light: the standard library and the readers named above.
"""
import os
import subprocess
import sys
import time
from collections import namedtuple

MISSING, INSTALLED, READY = "missing", "installed", "ready"
_LEVEL = {"missing": MISSING, "ready": READY}            # every other state of a look: installed, not ready yet

Found = namedtuple("Found", "hato miner")


def hato_version():
    """hato's version from its entry in the shared tools folder ("" when it names none), or None: not installed."""
    from app import tools_entry
    entry = tools_entry.read("hato")
    return None if entry is None else _version(entry)


def _version(entry):
    version = entry.get("version")
    return str(version) if isinstance(version, (str, int, float)) and not isinstance(version, bool) else ""


def tools_found(settings, log=print):
    """(A worker.) -> Found(hato: bool, miner: MISSING | INSTALLED). `log(text)`: a look that failed, said once."""
    hato = False
    try:
        hato = hato_version() is not None
    except Exception as e:
        log(f"looking for hato: {e}")
    miner = MISSING
    try:
        from app.connect import anki_miner
        if anki_miner.find(settings or {}):
            miner = INSTALLED
    except Exception as e:
        log(f"looking for Anki Miner: {e}")
    return Found(hato=hato, miner=miner)


def miner_level(state):
    """A fuller look's Anki Miner state on the one scale (None: not looked yet -> MISSING)."""
    return _LEVEL.get(state, INSTALLED) if state else MISSING


def make_cards_shown(level, on=False, ready=False):
    """Whether *Make cards for me* is offered: Anki Miner installed (or ready), or the switch on already (M3); asked
    `ready` (the wizard, WZ-4): only once Anki Miner is ready."""
    if ready:
        return level == READY
    return bool(on) or level in (INSTALLED, READY)


# --- *Find hato…* ----------------------------------------------------------------------------------------------------- #
HATO_FOLDER = "hato"            # the folder hato's zip unpacks into (hato.exe and hato-cli.exe inside it)
CONNECT_WAIT_S = 30.0           # how long an opened hato is given to write its entry (its window's start: about 1 s)
CONNECT_EVERY_S = 0.5
NOT_HATO, NOT_INSTALLED, NOT_STARTED, NO_ANSWER = "not-hato", "not-installed", "not-started", "no-answer"

Connected = namedtuple("Connected", "version why")      # version: hato's ("" none named) once connected, else None


def _program(name):
    return name + (".exe" if sys.platform == "win32" else "")


def hato_programs(folder):
    """The folder hato's programs (hato and hato-cli) are in: `folder` itself, or the `hato` folder in it -> that
    folder, or None."""
    for place in (folder, os.path.join(folder, HATO_FOLDER)):
        if all(os.path.isfile(os.path.join(place, _program(name))) for name in ("hato", "hato-cli")):
            return os.path.normpath(os.path.abspath(place))
    return None


def _names(entry, place):
    """Does hato's entry name the hato in `place` (its `cli` there)?"""
    cli = entry.get("cli") if isinstance(entry, dict) else None
    return (isinstance(cli, str) and os.path.normcase(os.path.dirname(os.path.abspath(cli)))
            == os.path.normcase(place))


def start_hato(program):
    """hato's window started from its own folder, detached, as Anki is (`open_anki.start`: this program's runtime
    variables left out, so a frozen hato never reads Surasura's) -> the process. OSError: it couldn't start."""
    from app.connect import open_anki
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                   env=open_anki.environment(), cwd=os.path.dirname(program))
    if sys.platform != "win32":
        return subprocess.Popen([program], start_new_session=True, **options)
    flags = open_anki.DETACHED_PROCESS | open_anki.CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen([program], creationflags=flags | open_anki.CREATE_BREAKAWAY_FROM_JOB, **options)
    except OSError:             # a job that forbids breaking away: hato lives as long as this program's job
        return subprocess.Popen([program], creationflags=flags, **options)


def connect_hato(folder, settings, start=start_hato, wait=CONNECT_WAIT_S, every=CONNECT_EVERY_S,
                 clock=time.monotonic, sleep=time.sleep):
    """(A worker.) *Find hato…* on `folder` -> `Connected(version, why)`; `why` None once hato's entry names that
    folder's hato, else NOT_HATO (no hato and hato-cli there: nothing written, nothing started), NOT_INSTALLED (this
    Surasura writes no entry — a portable build or a source run —, so no hato can connect to it), NOT_STARTED (hato
    couldn't be opened) or NO_ANSWER (opened, no entry naming it within `wait`). Already connected from there:
    answered at once, nothing started. Errors writing Surasura's entry raise (the press says it failed)."""
    from app import tools_entry
    place = hato_programs(folder)
    if place is None:
        return Connected(None, NOT_HATO)
    entry = tools_entry.read("hato")
    if entry is not None and _names(entry, place):
        return Connected(_version(entry), None)
    if tools_entry.entry(settings) is None:
        return Connected(None, NOT_INSTALLED)
    tools_entry.refresh(settings)           # hato connects only to an entry that is there when it starts
    try:
        start(os.path.join(place, _program("hato")))
    except OSError:
        return Connected(None, NOT_STARTED)
    deadline = clock() + wait
    while True:
        entry = tools_entry.read("hato")
        if entry is not None and _names(entry, place):
            return Connected(_version(entry), None)
        if clock() >= deadline:
            return Connected(None, NO_ANSWER)
        sleep(every)
