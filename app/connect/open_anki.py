"""*Open Anki for me* (P2.3; ✅ Q4-16, K102; P1.5 03-actors §6 `connect_open_anki`, 06-edges E1): an opt-in, off by
default, read only while Connect's preview is on. With it on, Surasura starts Anki **when a session starts** — your
phone's reviews come in through Anki's own sync on open, and Surasura reads your progress and orders your cards —
**never after mining**: Sonic, "I mentioned not opening Anki for me specifically after mining with Anki Miner. That's
the reason: so that we can choose when to open it or not." Connect, hato and every command-line verb never call
`start`; only a window's session start does (`anki_session.at_window`). Anki's own window appears (it has no hidden
start), and Surasura never closes it.

- `find()` — Anki's program where its installers put it, never a search (as Anki Miner 3.7 finds it,
  `gui/utils/ankiconnect_help.py`): Windows `%LOCALAPPDATA%\\Programs\\Anki\\anki.exe` (Anki's per-user installer),
  `%ProgramFiles%\\Anki\\anki.exe` (older ones), then the program Windows opens an `.apkg` with; macOS
  `/Applications/Anki.app` through `open`; elsewhere `anki` on PATH. None when it isn't there.
- `running()` — is an Anki process running (Windows: `tasklist`)? True / False, or None when it can't tell. Anki
  starting, or open without AnkiConnect, doesn't answer Surasura: it is never started twice.
- `start(profile=None)` — Anki started detached (no console), on `profile` when Connect was set up with one (`-p`), so
  its cards land in that profile; the environment without this program's Python, Tcl/Tk or Qt variables, which would
  break Anki's own. Returns the process, or None.

Under a test root nothing is found unless the test names a stand-in (`SURASURA_ANKI_PROGRAM`): a test never starts the
real Anki.
"""
import os
import re
import shutil
import subprocess
import sys

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
CREATE_NO_WINDOW = 0x08000000
MAC_BUNDLE = "/Applications/Anki.app"
STAND_IN = "SURASURA_ANKI_PROGRAM"          # tests and the live drill only: the program to start as "Anki"
# Variables this program's own runtime sets that would point Anki's Python or Qt at the wrong files: Python's and
# PyInstaller's, Tcl/Tk's (2.x), and the Qt paths a frozen PyQt6 program sets (3.0) — never the user's own Qt choices
# (QT_QPA_PLATFORM, QT_SCALE_FACTOR: Anki honours them too)
_NOT_FOR_ANKI = ("PYTHON", "_MEI", "_PYI")
_NOT_FOR_ANKI_NAMES = frozenset({"TCL_LIBRARY", "TK_LIBRARY", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                                 "QML2_IMPORT_PATH", "QML_IMPORT_PATH"})
_ANKI_EXE = re.compile(r"^(.*?anki\.exe)(?:\s|$)", re.IGNORECASE)


def _command(path):
    # A .py stand-in (the tests') is run by this Python
    return [sys.executable, path] if path.lower().endswith(".py") else [path]


def _association():
    """The program Windows opens an `.apkg` with (Anki's installers register it), or None."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ".apkg") as key:
            kind = winreg.QueryValueEx(key, "")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, rf"{kind}\shell\open\command") as key:
            command = winreg.QueryValueEx(key, "")[0]
    except (OSError, TypeError):
        return None
    return program_of(command)


def program_of(command):
    """The program in a Windows command line (`"C:\\…\\Anki.exe" "%1"` -> `C:\\…\\Anki.exe`), or None: quoted,
    or not (a path with spaces, up to its `anki.exe`), `%ProgramFiles%`-style variables expanded."""
    command = os.path.expandvars(str(command or "").strip())
    if command.startswith('"'):
        end = command.find('"', 1)
        path = command[1:end] if end > 0 else ""
    else:
        found = _ANKI_EXE.match(command)
        path = found.group(1) if found else command.split(" ", 1)[0]
    return path if os.path.basename(path).lower() == "anki.exe" else None


def _windows_places():
    places = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        places.append(os.path.join(local, "Programs", "Anki", "anki.exe"))
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            places.append(os.path.join(base, "Anki", "anki.exe"))
    associated = _association()
    if associated:
        places.append(associated)
    return places


def find():
    """The command that starts Anki, or None when it isn't where its installers put it."""
    if os.environ.get("SURASURA_TEST_ROOT"):
        stand_in = os.environ.get(STAND_IN)
        return _command(stand_in) if stand_in and os.path.isfile(stand_in) else None
    if sys.platform == "win32":
        return next(([path] for path in _windows_places() if os.path.isfile(path)), None)
    if sys.platform == "darwin":
        return ["open", MAC_BUNDLE] if os.path.isdir(MAC_BUNDLE) else None
    found = shutil.which("anki")
    return [found] if found else None


def running():
    """Is an Anki running? True / False, or None when this can't tell (off Windows, or `tasklist` failed)."""
    if sys.platform != "win32":
        return None
    try:
        done = subprocess.run(["tasklist", "/FI", "IMAGENAME eq anki.exe", "/FO", "CSV", "/NH"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=10, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return b'"anki.exe"' in done.stdout.lower()


def environment():
    """This program's environment, less what would steer Anki's own Python or Qt."""
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith(_NOT_FOR_ANKI) and key.upper() not in _NOT_FOR_ANKI_NAMES}


def start(profile=None):
    """Start Anki, detached, on `profile` when given -> the process, or None (not found, or it couldn't start)."""
    command = find()
    if command is None:
        return None
    if profile:
        command = command + (["--args", "-p", profile] if command[0] == "open" else ["-p", profile])
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                   env=environment(), cwd=os.path.expanduser("~"))
    try:
        if sys.platform != "win32":
            return subprocess.Popen(command, start_new_session=True, **options)
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(command, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, **options)
        except OSError:         # a job that forbids breaking away: Anki lives as long as this program's job
            return subprocess.Popen(command, creationflags=flags, **options)
    except OSError as e:
        print(f"Open Anki for me: Anki couldn't be started: {e}")
        return None
