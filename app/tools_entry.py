"""surasura.json, Surasura's entry in the shared tools folder: how hato and other tools find Surasura's command line,
the verbs it offers them and the folders their files land in (docs/agent instructions/3.0/P1.5-connect/09-hato-layer.md
§3, v2).

Written by Surasura alone, at the window's start, at every surasura-cli call and when Connect's switch turns on or off;
rewritten only when a field other than `updated` differs. The installed 3.0 writes it; a portable or test build
(frozen, not installed, or another data name) and a source checkout only when SURASURA_TOOLS_CLI names the command line
to advertise, so a developer's tree or a dist build never takes Sonic's entry. A failure is logged, never shown, and
never fails the window or the verb.

Light by rule (the command line imports it at every call): the standard library only at the top; app modules are
imported inside the functions, after the gate.
"""
import datetime
import json
import logging
import os
import sys
import threading
import time

SCHEMA = 1
TOOL = "surasura"
MAX_BYTES = 4096            # the file is small by rule (§3): a bigger entry is refused, never written
REPLACE_TRIES = 11          # os.replace retried for up to 1 s while a reader holds the file open (§3)
REPLACE_WAIT = 0.1
READ_RETRY_WAIT = 0.05      # a torn read (another tool mid-replace) is tried once more after 50 ms
LANGUAGES = ("ja", "zh")

# A child of the command line's logger, so a refusal lands in cli.log during a verb; the window has no handler on it.
log = logging.getLogger("surasura-cli.tools")
# One refresh at a time in a process (the window's start-up worker and the Connect switch's): the later one reads the
# settings and the entry after the earlier one has written, so it is the one that counts
_refreshing = threading.Lock()


def tools_dir():
    """The shared tools folder: HOUSEKI_TOOLS_DIR, else <test root>/houseki-tools under SURASURA_TEST_ROOT, else
    `path_utils.tools_root()` (%LOCALAPPDATA%\\Houseki\\tools; S3.1 D20). A test that reaches the real one raises (as
    path_utils.local_data_root)."""
    override = os.environ.get("HOUSEKI_TOOLS_DIR")
    if override:
        return override
    root = os.environ.get("SURASURA_TEST_ROOT")
    if root:
        return os.path.join(root, "houseki-tools")
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError("a test reached the real shared tools folder: set SURASURA_TEST_ROOT or HOUSEKI_TOOLS_DIR")
    from app import path_utils
    return path_utils.tools_root()


def _advertised():
    """(cli, app) this process advertises, or None when it writes no entry: the installed 3.0 (frozen, library.json
    naming its library, the data name Surasura) → surasura-cli.exe and Surasura.exe in the running exe's folder (no
    .exe off Windows, as `connect.kick` names them; app null when absent); otherwise — a portable or test build (S3.1
    D3), a source checkout — SURASURA_TOOLS_CLI, app null; else None."""
    from app import path_utils
    if (path_utils.is_frozen() and path_utils.installed_library() is not None
            and path_utils.data_name() == path_utils.DATA_NAME):
        app = path_utils.program_beside("Surasura")
        return path_utils.program_beside("surasura-cli"), (app if os.path.isfile(app) else None)
    cli = os.environ.get("SURASURA_TOOLS_CLI")
    if cli:
        return os.path.abspath(cli), None
    return None


def _drop_folders():
    """{lang: hato's drop folder} for each language Surasura is set up for (its User Files/<lang> exists)."""
    from app import library_store, path_utils
    folders = {}
    for lang in LANGUAGES:
        if os.path.isdir(path_utils.get_user_files_path(lang)):
            folder = os.path.join(path_utils.get_data_path(lang), *library_store.HATO_FOLDER.split("/"))
            folders[lang] = os.path.normpath(os.path.abspath(folder))
    return folders


def entry(settings):
    """Surasura's entry as a dict, or None when this process writes none (a portable or test build, or a source
    checkout, without SURASURA_TOOLS_CLI). `register` is offered to other tools only while Connect's preview is on."""
    advertised = _advertised()
    if advertised is None:
        return None
    from app import __version__
    from app.cli.contract import CONTRACT
    cli, app = advertised
    verbs = ["status"] + (["register"] if (settings or {}).get("connect_enabled") else [])
    return {
        "schema": SCHEMA,
        "tool": TOOL,
        "name": "Surasura",
        "version": __version__,
        "cli": cli,
        "app": app,
        "contract": CONTRACT,
        "verbs": verbs,
        "drop_folders": _drop_folders(),
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _same(old, new):
    """True when every field but `updated` matches: nothing to write."""
    if not isinstance(old, dict):
        return False
    return {k: v for k, v in old.items() if k != "updated"} == {k: v for k, v in new.items() if k != "updated"}


def refresh(settings=None):
    """Rewrite surasura.json when a field other than `updated` differs; True when written. The gate comes first: a
    process that writes no entry reads nothing. `settings` None → read strictly (inside the refresh's lock, so a
    later refresh never writes settings older than an earlier one's); unreadable → skipped (logged). A replace that
    keeps failing returns False with the old file intact and no tmp left; other errors raise (callers wrap)."""
    from app import path_utils
    if not (path_utils.is_frozen() or os.environ.get("SURASURA_TOOLS_CLI")):
        return False
    with _refreshing:
        return _refresh(settings)


def _refresh(settings):
    if settings is None:
        from app import settings_manager
        try:
            settings = settings_manager.load_settings(strict=True)
        except Exception as e:
            log.warning("surasura.json not refreshed: settings.json can't be read (%s)", e)
            return False
    new = entry(settings)
    if new is None:
        return False
    folder = tools_dir()
    path = os.path.join(folder, TOOL + ".json")
    try:
        with open(path, "rb") as f:
            old = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError):
        old = None
    if _same(old, new):
        return False
    data = (json.dumps(new, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(data) > MAX_BYTES:
        log.warning("surasura.json not written: %d bytes, over the %d-byte limit", len(data), MAX_BYTES)
        return False
    os.makedirs(folder, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"     # its own per process and thread
    written = False
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                written = True
                break
            except PermissionError:
                if attempt < REPLACE_TRIES - 1:
                    time.sleep(REPLACE_WAIT)
        if not written:
            log.warning("surasura.json not written: another program held it open for over a second")
        return written
    finally:
        if not written:
            try:
                os.remove(tmp)
            except OSError:
                pass


def read(tool):
    """Another tool's entry (`<tool>.json`) as a dict, or None when the tool counts as absent: no file, unreadable
    twice (50 ms apart), not an object, its `cli` missing, or a `schema` / `contract` newer than Surasura speaks."""
    path = os.path.join(tools_dir(), f"{tool}.json")
    for attempt in range(2):
        try:
            with open(path, "rb") as f:
                found = json.loads(f.read().decode("utf-8"))
            break
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            if attempt == 0:
                time.sleep(READ_RETRY_WAIT)
    else:
        return None
    from app.cli.contract import CONTRACT
    if not isinstance(found, dict):
        return None
    schema, contract, cli = found.get("schema"), found.get("contract"), found.get("cli")
    if not isinstance(schema, int) or schema > SCHEMA or not isinstance(contract, int) or contract > CONTRACT:
        return None
    if not isinstance(cli, str) or not os.path.exists(cli):
        return None
    return found
