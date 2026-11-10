"""Windows Defender's Controlled folder access (3.0.1, Mattias 2026-11-10; QUESTIONS.md *Controlled folder access*).

Controlled folder access (CFA: Defender's ransomware protection, off by default) refuses writes by any program it
doesn't know inside its protected folders — Documents, Pictures, Videos, Music, Desktop, Favorites (the user's and
Public's) and any folder the user adds. 3.0.0's installer put the library in Documents\\Surasura, so with CFA on every
write there fails with access denied (WinError 5).

Never guessed from the error alone: a refusal is CFA's only when Defender's own switch says it is on (1; 2 is audit,
which blocks nothing), the folder is inside a protected one, and the write was refused. The allowed-apps list can't
be read without admin, so a write check (`probe`) has the last word.

  * `mode()` — the switch (the policy's first, then the user's setting), None off Windows or when unreadable.
  * `protected_folders()` / `protecting(path)` — the protected folder holding `path`, or None.
  * `at_risk(path)` — CFA on and `path` inside a protected folder: only then is a write check worth making.
  * `probe(folder)` — writes and deletes one small file in `folder` and in its parts that are there.
  * `refused(exc, path)` — this OSError is CFA's refusal.
  * `words(...)` / `programs()` / `move_target()` / `open_settings()` — what the window and the command line say.

Standard library only (the command line imports it); nothing here writes the registry or Defender's settings.
"""
import errno
import os
import sys

KEY = r"SOFTWARE\Microsoft\Windows Defender\Windows Defender Exploit Guard\Controlled Folder Access"
POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Windows Defender\Windows Defender Exploit Guard\Controlled Folder Access"
SWITCH = "EnableControlledFolderAccess"
PROTECTED = "ProtectedFolders"            # a subkey: each value's NAME is a folder the user (or a policy) added
ON = 1                                    # 0 off · 1 on · 2 audit · 3 / 4 disks only: only 1 refuses a folder write
USER_FOLDERS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"      # HKCU
USER_NAMES = ("Personal", "My Pictures", "My Video", "My Music", "Desktop", "Favorites")
PUBLIC_FOLDERS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"           # HKLM
PUBLIC_NAMES = ("Common Documents", "CommonPictures", "CommonVideo", "CommonMusic", "Common Desktop")
SETTINGS_PAGE = "windowsdefender://ransomwareprotection"     # Windows Security → Ransomware protection
PROBE_NAME = ".surasura-write-check"
PARTS = ("User Files", "data", "results")                    # the library's own folders (path_utils' INSTALLED layout)
NEED = "windows-folder-access"                               # the command line's `need` (02 §3, exit 4)
LIBRARY_NAME = "Surasura"                                    # the library's folder in the user's folder (3.0.1)


def _windows():
    return sys.platform == "win32"


def _hive(machine):
    import winreg
    return winreg.HKEY_LOCAL_MACHINE if machine else winreg.HKEY_CURRENT_USER


def _read(key, name, machine=True):
    """One registry value, or None (no key, no value, not readable). Tests replace it."""
    try:
        import winreg
        with winreg.OpenKey(_hive(machine), key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, name)[0]
    except (OSError, ImportError):
        return None


def _names(key, machine=True):
    """The value names under a registry key ([] when it can't be read). Tests replace it."""
    try:
        import winreg
        out = []
        with winreg.OpenKey(_hive(machine), key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumValue(k, i)[0])
                except OSError:
                    return out
                i += 1
    except (OSError, ImportError):
        return []


def mode():
    """Defender's CFA switch as an int (a policy's value wins over the user's setting), or None: not Windows, or
    neither value there or readable (CFA has never been set: off)."""
    if not _windows():
        return None
    for key in (POLICY_KEY, KEY):
        value = _read(key, SWITCH)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def is_on():
    return mode() == ON


def _expand(path):
    return os.path.normpath(os.path.expandvars(path)) if isinstance(path, str) and path.strip() else None


def protected_folders():
    """Every folder CFA protects here: Windows' own (this user's and Public's) and the ones added (the user's and a
    policy's). [] off Windows."""
    if not _windows():
        return []
    found = [_expand(_read(USER_FOLDERS, name, machine=False)) for name in USER_NAMES]
    found += [_expand(_read(PUBLIC_FOLDERS, name)) for name in PUBLIC_NAMES]
    for key in (KEY, POLICY_KEY):
        found += [_expand(name) for name in _names(key + "\\" + PROTECTED)]
    out = []
    for folder in found:
        if folder and folder not in out:
            out.append(folder)
    return out


def _key(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def protecting(path, folders=None):
    """The protected folder `path` is in (or is), or None."""
    if not path:
        return None
    here = _key(path)
    for folder in protected_folders() if folders is None else folders:
        top = _key(folder)
        if here == top or here.startswith(top.rstrip("\\/") + os.sep):
            return folder
    return None


def _holds_protected(path, folders):
    """A protected folder inside `path` (a user who protected one part of the library only)."""
    top = _key(path).rstrip("\\/") + os.sep
    return any(_key(folder).startswith(top) for folder in folders)


def at_risk(path):
    """CFA is on and `path` is inside a protected folder, or holds one: a write there may be refused (`probe` says
    whether)."""
    if not path or not is_on():
        return False
    folders = protected_folders()
    return protecting(path, folders) is not None or _holds_protected(path, folders)


def denied(exc):
    """An OSError that is access denied (what CFA's refusal looks like)."""
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) == 5 or \
        getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM)


def refused(exc, path=None):
    """Was this OSError CFA's refusal? Access denied, CFA on, and the path (`path`, else the error's own file) inside
    a protected folder — never the error alone."""
    target = path or getattr(exc, "filename", None)
    return isinstance(exc, OSError) and denied(exc) and isinstance(target, str) and at_risk(target)


def _write_check(folder):
    path = os.path.join(folder, f"{PROBE_NAME}-{os.getpid()}.tmp")
    with open(path, "wb") as f:
        f.write(b"surasura")
    os.remove(path)


def probe(folder):
    """A write check in `folder` and in each of its library parts that is there (a user may protect one part only)
    -> None when every write went through, else the folder whose write CFA refused. Makes nothing: a folder that isn't
    there is skipped. Only worth calling when `at_risk(folder)`; another error (not CFA's) is not a refusal: None."""
    for place in (folder,) + tuple(os.path.join(folder, part) for part in PARTS):
        if not os.path.isdir(place):
            continue
        try:
            _write_check(place)
        except OSError as e:
            if refused(e, place):
                return place
    return None


def program_folder():
    """The folder Surasura's programs are in (frozen), else None (a source run)."""
    return os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else None


def programs():
    """The two programs CFA must allow, with their full paths when installed (Surasura.exe, surasura-cli.exe)."""
    folder = program_folder()
    names = ("Surasura.exe", "surasura-cli.exe")
    return [os.path.join(folder, n) for n in names] if folder else list(names)


def move_target():
    """Where *Move my library* puts it: the user's own folder, outside every folder Windows protects (3.0.1's
    default, as the installer's)."""
    return os.path.join(os.path.expanduser("~"), LIBRARY_NAME)


def open_settings(opener=None):
    """Windows Security's Ransomware protection page -> True when it opened. Never raises."""
    try:
        (opener or os.startfile)(SETTINGS_PAGE)
        return True
    except (OSError, AttributeError) as e:
        print(f"Controlled folder access: Windows Security didn't open ({e}).")
        return False


# --- What it says (the window's screen and the command line's `error`) ------------------------------------------- #
HEADING = "Windows is blocking Surasura from saving your library"
LINE = ("Windows' ransomware protection (Controlled folder access) won't let Surasura save to {folder}. Move your "
        "library to {target}, or allow Surasura in Windows Security.")
ALLOW_STEPS = ("In Windows Security: Ransomware protection → Allow an app through Controlled folder access → Add an "
               "allowed app → choose {programs}.")
CLI_WORDS = ("Windows' ransomware protection (Controlled folder access) blocked surasura-cli from saving to {folder}. "
             "Either open Surasura and press Move my library to {target}, or allow both programs in Windows Security "
             "(Ransomware protection → Allow an app through Controlled folder access → Add an allowed app): "
             "{programs}.")


def words(folder, target=None):
    """The window's line: what is blocked and the two ways out."""
    return LINE.format(folder=folder, target=target or move_target())


def allow_steps():
    return ALLOW_STEPS.format(programs=" and ".join(programs()))


def cli_words(folder, target=None):
    return CLI_WORDS.format(folder=folder, target=target or move_target(), programs=" and ".join(programs()))
