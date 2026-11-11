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
- `open_hato(folder, settings)` + `hato_seen(place)`: *Find hato…* (Michi-HD; Mattias's 3.0.0 report, 2026-11-11: his hato, unpacked
  on his D: drive, never seen). hato writes its entry (`hato.json`) only when it starts and Surasura's own is there
  already, so a hato last opened before Surasura was installed — or moved since — stays unseen. The learner picks
  hato's folder (the folder itself, or the `hato` folder its zip unpacks into); Surasura's entry is written fresh and
  hato is opened from there once, so hato connects itself (its entry stays hato's to write: 09-hato-layer §3); the
  window then looks at its entry every `CONNECT_EVERY_S` until it names that folder (or another copy), up to
  `CONNECT_WAIT_S` -> `Connected(version, why)`.

Qt-free, light: the standard library and the readers named above.
"""
import os
import subprocess
import sys
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
CONNECT_WAIT_S = 30.0           # how long an opened hato is followed for its entry (its window's start: about 1 s)
CONNECT_EVERY_S = 0.5           # the window's look at the entry meanwhile (`hato_seen`, one file read on a worker)
NOT_HATO, NOT_INSTALLED, NOT_STARTED, NO_ANSWER = "not-hato", "not-installed", "not-started", "no-answer"
ANOTHER = "another-hato"        # the entry names another copy of hato (one already open: the picked one only raised it)

Connected = namedtuple("Connected", "version why")      # version: hato's ("" none named) once one is found, else None


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


def start_hato(program, tools):
    """hato's window started from its own folder, detached, as Anki is (`open_anki.start`: this program's runtime
    variables left out, so a frozen hato never reads Surasura's), told the shared tools folder Surasura reads
    (`HOUSEKI_TOOLS_DIR`, which hato honours too) -> the process. OSError: it couldn't start."""
    from app.connect import open_anki
    env = open_anki.environment()
    env["HOUSEKI_TOOLS_DIR"] = tools
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                   env=env, cwd=os.path.dirname(program))
    if sys.platform != "win32":
        return subprocess.Popen([program], start_new_session=True, **options)
    flags = open_anki.DETACHED_PROCESS | open_anki.CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen([program], creationflags=flags | open_anki.CREATE_BREAKAWAY_FROM_JOB, **options)
    except OSError:             # a job that forbids breaking away: hato lives as long as this program's job
        return subprocess.Popen([program], creationflags=flags, **options)


def open_hato(folder, settings, start=start_hato):
    """(A worker; quick.) *Find hato…* on `folder` -> (the folder hato's programs are in or None, an answer now or
    None). Answered now: NOT_HATO (no hato and hato-cli there: nothing written, nothing started), NOT_INSTALLED (this
    Surasura writes no entry — a portable build, a source run — so no hato can connect to it), NOT_STARTED (hato
    couldn't be opened), or `Connected(version, None)` (its entry names that folder already: nothing started). Else
    Surasura's entry is written fresh and hato started there: the caller follows it with `hato_seen` (never a wait
    here: the quit waits for workers only a few seconds). Surasura's entry not there after its refresh: raises."""
    from app import tools_entry
    place = hato_programs(folder)
    if place is None:
        return None, Connected(None, NOT_HATO)
    entry = tools_entry.read("hato")
    if entry is not None and _names(entry, place):
        return place, Connected(_version(entry), None)
    if tools_entry.entry(settings) is None:
        return place, Connected(None, NOT_INSTALLED)
    tools_entry.refresh(settings)           # hato connects only to an entry that is there when it starts
    if tools_entry.read(tools_entry.TOOL) is None:
        raise OSError("surasura.json couldn't be written in the shared tools folder")
    try:
        start(os.path.join(place, _program("hato")), tools_entry.tools_dir())
    except OSError:
        return place, Connected(None, NOT_STARTED)
    return place, None


def hato_seen(place):
    """(A worker; one file read.) The opened hato's entry looked at -> `Connected(version, None)` once it names the hato
    in `place`; `Connected(version, ANOTHER)` while it names another usable copy; None: no usable entry yet."""
    from app import tools_entry
    entry = tools_entry.read("hato")
    if entry is None:
        return None
    return Connected(_version(entry), None if _names(entry, place) else ANOTHER)
