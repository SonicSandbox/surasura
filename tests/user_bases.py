"""The per-user bases (%LOCALAPPDATA%, %APPDATA%, XDG_DATA_HOME) moved to a folder of a process's own, so nothing it
runs, or starts, reaches the real Houseki roots through them. One rule, two users:

* every pytest run (tests/harness_guards.py, imported by every suite's conftest): moved unconditionally, at import;
* the shared test data (tests/fixtures/__init__.py): moved only when the bases still name the real profile — a probe
  run by hand (`python probe.py` building the window seed) had no harness, and a seed's row reads Connect's setup
  record (view_rows → anki_miner.mines_now → ledger.folder → get_local_data_path), which made the real, empty
  %LOCALAPPDATA%\\Houseki\\Surasura\\<install key> (2026-10-31 15:43) and failed other lanes' runs. Under pytest the
  harness has already moved them, and a bench's child that names its own bases keeps them.

No pytest import here: a probe imports it outside any test run.
"""
import atexit
import os
import shutil
import sys
import tempfile
import time

ROOTS_PREFIX = "surasura-test-bases-"
BASE_NAMES = ("LOCALAPPDATA", "APPDATA", "XDG_DATA_HOME")


def redirect():
    """Point %LOCALAPPDATA%, %APPDATA% and XDG_DATA_HOME at a new folder in TEMP (removed when this process exits);
    PYTHONUSERBASE keeps naming this user's packages (Python looks for them under %APPDATA%), for the children too."""
    os.environ.setdefault("PYTHONUSERBASE", real_user_base())
    forget_stale()
    bases = tempfile.mkdtemp(prefix=ROOTS_PREFIX)
    atexit.register(shutil.rmtree, bases, True)   # before any test's exit hook, so it runs after them
    for name, sub in (("LOCALAPPDATA", "Local"), ("APPDATA", "Roaming"), ("XDG_DATA_HOME", "Local")):
        os.makedirs(os.path.join(bases, sub), exist_ok=True)
        os.environ[name] = os.path.join(bases, sub)
    return bases


def forget_stale(older_than=86400):
    """Remove the bases a run killed before its exit left in TEMP (a day old or more)."""
    temp = tempfile.gettempdir()
    try:
        names = [n for n in os.listdir(temp) if n.startswith(ROOTS_PREFIX)]
    except OSError:
        return
    for name in names:
        path = os.path.join(temp, name)
        try:
            if time.time() - os.path.getmtime(path) > older_than:
                shutil.rmtree(path, True)
        except OSError:
            pass


def _same_folder(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def names_the_real_profile():
    """True when a base is unset, empty or this user's own (path_utils then reaches the real Houseki roots): Windows
    %APPDATA% / %LOCALAPPDATA% against ~\\AppData\\Roaming / ~\\AppData\\Local, elsewhere XDG_DATA_HOME against
    ~/.local/share — as `with-lock.sh` decides it."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        pairs = (("APPDATA", ("AppData", "Roaming")), ("LOCALAPPDATA", ("AppData", "Local")))
    else:
        pairs = (("XDG_DATA_HOME", (".local", "share")),)
    for name, parts in pairs:
        value = os.environ.get(name)
        if not value or _same_folder(value, os.path.join(home, *parts)):
            return True
    return False


def real_user_base():
    """This user's own Python user base (where `pip install --user` put their packages), whatever %APPDATA% names
    now: Python's rule (`site.getuserbase`, %APPDATA%\\Python on Windows) read against the real profile, as
    `names_the_real_profile` reads it. `site.getuserbase()` alone is the base as this process started: a lane's
    redirected %APPDATA% gave its throwaway folder. Elsewhere the base never moves with these bases (~/.local)."""
    if sys.platform != "win32":
        import site
        return site.getuserbase()
    return os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Python")


def keep_user_site(environ):
    """PYTHONUSERBASE set in `environ` to `real_user_base()` when it is unset and %APPDATA% names another folder, so
    a process started with it still imports this user's packages. -> the base set, or None (nothing to do).
    2026-11-24: a lane's APPDATA at its throwaway folder hid them from run_tests.py's children — certifi: three of a
    level-2 --all's shards ran nothing."""
    if environ.get("PYTHONUSERBASE") or sys.platform != "win32":
        return None
    real = real_user_base()
    if _same_folder(os.path.join(environ.get("APPDATA") or "", "Python"), real):
        return None
    environ["PYTHONUSERBASE"] = real
    return real


def isolate():
    """Move the bases (`redirect`) unless they already name somewhere else (a bench's, an env.sh's) or a pytest
    harness owns them: inside a run, a test that pointed them elsewhere has them put back by its monkeypatch, and a
    move here would outlive it."""
    if "tests.harness_guards" in sys.modules or not names_the_real_profile():
        return None
    return redirect()
