
import ast
import re
import sys
import subprocess
import os
import glob
import shutil
import threading
import textwrap
import time
import locale
from concurrent.futures import ThreadPoolExecutor, as_completed


# --- every child without a console window of its own ----------------------------------------------------------- #
# On Windows, a console program started by a parent that has no console (an AI app's shell, a scheduled task, an IDE)
# gets a NEW console window: each --all shard, pytest run, git and taskkill opened one and took the focus, so the PC
# couldn't be used while the suite ran. CREATE_NO_WINDOW starts a child on a console with no window, and whatever it
# starts in turn (pytest, a test's own `python -m app.cli …`) shares that console: no window anywhere below, and no
# test has to pass the flag itself. Such a child would write to its windowless console, so it gets this process's own
# stdin, stdout and stderr unless the call names its own. A parent IN a console (a terminal) changes nothing: its
# children share that console, as they always did.
def _has_console():
    """Has this process a console (a terminal)? Always, off Windows: there no child opens a window of its own."""
    if os.name != "nt":
        return True
    import ctypes
    return bool(ctypes.windll.kernel32.GetConsoleWindow())


def _quiet(kwargs):
    """`kwargs` for a child, without a console window of its own when this process has none (`_run`, `_popen`)."""
    if _has_console():
        return kwargs
    kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    for name, stream in (("stdin", sys.stdin), ("stdout", sys.stdout), ("stderr", sys.stderr)):
        if kwargs.get(name) is None:
            try:
                stream.flush() if name != "stdin" else None
                stream.fileno()
                kwargs[name] = stream
            except (AttributeError, OSError, ValueError):
                kwargs[name] = subprocess.DEVNULL
    return kwargs


def _run(*args, **kwargs):
    """subprocess.run, without a console window of its own (`_quiet`)."""
    return subprocess.run(*args, **_quiet(kwargs))


def _popen(*args, **kwargs):
    """subprocess.Popen, without a console window of its own (`_quiet`)."""
    return subprocess.Popen(*args, **_quiet(kwargs))


# --- --all: every suite at once --------------------------------------------------------------- #
# Each suite runs in its own `python -m pytest <dir>` process from the project root — the command
# docs/agent instructions/testing.md gives for a module suite — so they share nothing but the
# machine. The pytest cache is off (-p no:cacheprovider): concurrent sessions would all write the
# same .pytest_cache files, and no test reads the cache. Spec: Parallel_Test_Runner_Spec.md.

def _suites(project_root):
    """Core first, then every module suite on disk (a checkout without modules/ runs core only)."""
    suites = ["tests"]
    for path in sorted(glob.glob(os.path.join(project_root, "modules", "*", "tests"))):
        if os.path.isdir(path):
            suites.append(os.path.relpath(path, project_root).replace(os.sep, "/"))
    return suites


# --- --all: the core suite split into shards --------------------------------------------------- #
# The core suite is most of an --all (~17 min of ~6,000 tests alone, 2026-10-06; a module suite ends in about a
# minute), so --all splits it by file into shards, each its own `python -m pytest <files>` process like a suite. Each
# shard's files are packed by their last recorded times: this copy's own (debug/test_times.json, written by the shards'
# own conftest hook, SURASURA_TEST_TIMES) over the tracked ones (tests/test_times.json, a train's green --all's, saved
# by --save-times: all a fresh copy or GitHub has), the file's size where neither has one. How many shards: as many as
# fit in the memory free now (one unsplit core process peaked at ~4.8 GB; each further shard adds ~0.5 GB; RESERVE_MB
# is left for the module suites and the machine), at most SHARD_MAX and half the CPUs idle over half a second as it
# starts (two logical CPUs share a core) — so a quiet machine gets more, one already running other test runs fewer.
# SURASURA_TEST_SHARDS=N chooses N (1: unsplit).

SHARD_MAX = 8
CORE_PEAK_MB = 4800
SHARD_MB = 500
RESERVE_MB = 3000
TIMES = os.path.join("debug", "test_times.json")
TRACKED_TIMES = os.path.join("tests", "test_times.json")


def _core_files(project_root):
    """Every core test file (pytest's default pattern), as paths from the project root, in order."""
    files = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(project_root, "tests")):
        top = os.path.normcase(dirpath) == os.path.normcase(os.path.join(project_root, "tests"))
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith(".")
                             and not (top and d == STRESS_DIR))           # the stress set: --stress only
        for name in sorted(filenames):
            if name.startswith("test_") and name.endswith(".py"):
                files.append(os.path.relpath(os.path.join(dirpath, name), project_root).replace(os.sep, "/"))
    return sorted(files)


def _free_memory_mb():
    """Physical memory free now, in MB; None where it can't be read."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullAvailPhys // 1048576
            return None
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // 1048576
    except (AttributeError, ValueError, OSError):
        return None


def _idle_cpus(cpus, seconds=0.5):
    """How many of the `cpus` logical CPUs sat idle over the next `seconds`; None where it can't be read."""
    def sample():
        if sys.platform == "win32":
            import ctypes
            idle, kernel, user = (ctypes.c_ulonglong() for _ in range(3))
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return None
            return idle.value, kernel.value + user.value          # kernel time includes idle time
        with open("/proc/stat") as f:
            values = [int(v) for v in f.readline().split()[1:]]
        return values[3] + values[4], sum(values)                 # idle + iowait, all
    try:
        first = sample()
        time.sleep(seconds)
        second = sample()
    except (AttributeError, OSError, ValueError, IndexError):
        return None
    if not first or not second or second[1] <= first[1] or not cpus:
        return None
    return cpus * (second[0] - first[0]) / (second[1] - first[1])


def _shard_count(free_mb, cpus, idle=None):
    """How many shards the core suite runs in (see above)."""
    forced = os.environ.get("SURASURA_TEST_SHARDS", "").strip()
    if forced.isdigit():
        return max(1, int(forced))
    cap = max(1, min(SHARD_MAX, cpus or 1))
    if idle is not None:
        cap = max(1, min(cap, int(idle // 2)))      # two logical CPUs a shard: they share a core
    if free_mb is None:
        return max(1, min(4, cap // 2))
    shards = 1
    while shards < cap and CORE_PEAK_MB + SHARD_MB * shards <= free_mb - RESERVE_MB:   # what shards + 1 would need
        shards += 1
    return shards


STRESS_DIR = "stress"


def _read_times(project_root):
    """{file: seconds}: the tracked times, then this copy's own over them (a file in both: this copy's). An entry that
    isn't a finite number of seconds is left out alone (that file packs by size), never the whole file."""
    import json
    import math
    times = {}
    for name in (TRACKED_TIMES, TIMES):
        try:
            with open(os.path.join(project_root, name), encoding="utf-8") as f:
                part = json.load(f)
        except (OSError, ValueError):
            continue
        for k, v in (part.items() if isinstance(part, dict) else ()):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0:
                times[k] = float(v)
    return times


def _shards(project_root, files, count):
    """`files` packed into `count` shards by their recorded times (longest first, each into the lightest shard), each
    shard's files in path order. A file with no record weighs its size (~1 s per 10 KB)."""
    times = _read_times(project_root)

    def weight(path):
        if path in times:
            return times[path]
        try:
            return os.path.getsize(os.path.join(project_root, path)) / 10000.0
        except OSError:
            return 1.0
    shards = [[] for _ in range(count)]
    loads = [0.0] * count
    for path in sorted(files, key=lambda p: (-weight(p), p)):
        i = loads.index(min(loads))
        shards[i].append(path)
        loads[i] += weight(path)
    return [sorted(shard) for shard in shards if shard]


def _save_times(project_root, parts):
    """Merge each shard's file times into debug/test_times.json (written whole, then moved in)."""
    import json
    times = _read_times(project_root)
    for part in parts:
        try:
            with open(part, encoding="utf-8") as f:
                times.update({k: round(float(v), 3) for k, v in json.load(f).items()})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    path = os.path.join(project_root, TIMES)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(times, f, indent=0, sort_keys=True)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


# --- --save-times: the times GitHub and a fresh copy pack by ------------------------------------------------------- #
# debug/test_times.json is this copy's and git-ignored, so GitHub's PR shards (pr.yml) packed by file size: the slowest
# of four took 27-38 min against the fastest's 20-26 (2026-11-21). After a train's green --all, `--save-times` writes
# tests/test_times.json (tracked) from it: only the core test files git tracks (a local-only suite's names never go
# public), to a tenth of a second, sorted. It writes nothing when this copy has no times or git can't list the files.

def save_times(project_root):
    """`--save-times`: tests/test_times.json from this copy's times (a file this copy hasn't timed keeps its tracked
    time). Returns 0, or 2 with nothing written."""
    import json
    tracked = set(_git_out(project_root, "-c", "core.quotepath=false", "ls-files", "--", "tests").splitlines())
    if not os.path.isfile(os.path.join(project_root, TIMES)) or not tracked:
        print(f"--save-times: no {TIMES} here (an --all writes it) or git lists no tests/ files: nothing written.")
        return 2
    times = _read_times(project_root)
    core = [path for path in _core_files(project_root) if path in tracked]
    kept = {path: round(times[path], 1) for path in core if path in times}
    path = os.path.join(project_root, TRACKED_TIMES)
    try:
        with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as f:
            json.dump(kept, f, indent=0, sort_keys=True)
            f.write("\n")
        os.replace(path + ".tmp", path)
    except OSError as e:                                     # (held open by an editor, a scanner): the old file stays
        print(f"--save-times: {TRACKED_TIMES} could not be written ({e}): nothing written.")
        try:
            os.remove(path + ".tmp")
        except OSError:
            pass
        return 2
    print(f"--save-times: {TRACKED_TIMES} holds {len(kept)} files' times ({sum(kept.values()) / 60:.0f} min); "
          f"{len(core) - len(kept)} core file(s) without one pack by size; {len(set(times) - set(kept))} name(s) "
          f"left out (not a tracked core test file).")
    return 0


# --- --local-only: what GitHub's pull request run cannot see (Minato-GH, 2026-11-22) ------------------------------- #
# A train's pull request runs the public core suite and the public module suites on GitHub, on the merge commit (the
# tree that lands). `--local-only` runs the rest of an --all and nothing more: the core test files the public repo
# doesn't track (the local-only parsing suite), the suites of the private modules installed here, and every tracked core
# test file that names a private folder (on GitHub such a file takes the module-absent path). The set is derived on
# every run, never kept by hand: the private folders are the module and test folders the private repo
# (<top folder>.priv.git, as `git priv` finds it) tracks, and the module folders here that the public repo tracks no
# file of. A private folder the private repo tracks but this checkout lacks is named, never skipped quietly.
# tests/test_run_tests_runner.py proves the two halves hold every file of --all between them (the cover check), and
# that no tracked core file importing a private module is left out of the set (the import check).

PRIVATE_TOPS = ("modules", "tests")      # the private repo's code folders: modules/<name>/ and tests/<name>/
_SEP = r"""(?:[./\\]+|["']\s*,\s*["'])"""  # modules/x, modules.x, modules\x (or \\x), "modules", "x"


def _names_folder(folder):
    """A pattern for a source naming `folder` ("modules/<name>"): as a path, a dotted module, os.path.join's parts, or
    `from modules import <name>` (on one line, or in brackets over several)."""
    top, name = (re.escape(part) for part in folder.split("/"))
    return re.compile(rf"\b{top}{_SEP}{name}\b|\bfrom\s+{top}\s+import\s+(?:\([^)]*?|[^\n]*?)\b{name}\b")


def _private_folders(project_root, public):
    """(here, missing): the private folders ("modules/<name>", "tests/<name>") this checkout holds, and those the
    private repo tracks that it lacks. `public`: the public repo's files. None when the private repo is here but git
    can't read it (never read as "it tracks nothing")."""
    shared = {"/".join(p.split("/")[:2]) for p in public if p.count("/") >= 2}
    listed = []
    if os.path.isdir(project_root + ".priv.git"):
        try:
            out = _run(["git", "-c", "core.quotepath=false", f"--git-dir={project_root}.priv.git", "ls-files", "-z",
                        "--", *PRIVATE_TOPS], cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return None
        if out.returncode != 0:
            return None
        listed = out.stdout.decode("utf-8", "replace").split("\0")
    folders = {"/".join(p.split("/")[:2]) for p in listed if p.count("/") >= 2}
    top = os.path.join(project_root, "modules")
    on_disk = {f"modules/{name}" for name in (os.listdir(top) if os.path.isdir(top) else ())
               if os.path.isdir(os.path.join(top, name)) and name != "__pycache__"
               and any(entry != "__pycache__" for entry in os.listdir(os.path.join(top, name)))}   # (a left-over: none)
    folders = (folders | on_disk) - shared
    here = sorted(f for f in folders if os.path.isdir(os.path.join(project_root, f)))
    return here, sorted(folders - set(here))


def local_only(project_root):
    """--local-only's part of an --all: {"core": {file: why}, "suites": [module suites], "missing": [private folders not
    here], "private_repo": bool}; None when git can't list the public repo's files, or the private repo's."""
    try:
        public = _public_files(project_root)
    except OSError:                                          # no git on PATH
        public = None
    if not public:
        return None
    folders = _private_folders(project_root, public)
    if folders is None:
        return None
    here, missing = folders
    names = [(folder, folder.split("/")[1], _names_folder(folder)) for folder in here]
    core, all_core = {}, _core_files(project_root)
    for path in all_core:
        if path not in public:
            folder = "/".join(path.split("/")[:2])
            core[path] = f"in {folder}/, which the public repo doesn't track" if folder in here else \
                "not tracked by the public repo"
    # What a tracked file of tests/ names (read once; the pattern only where the name is in the text at all): a test
    # file for itself; a conftest for every test file under its folder; a helper for every test file that imports it,
    # and every test file under a conftest that imports it.
    texts = {}
    for path in (p for p in public if p.startswith("tests/") and p.endswith(".py")):
        try:
            texts[path] = _text(project_root, path)
        except OSError:
            continue
    named = {}
    for path in sorted(texts, key=lambda p: (not os.path.basename(p).startswith("test_"), p)):    # test files first
        hits = [folder for folder, name, pattern in names if name in texts[path] and pattern.search(texts[path])]
        if hits:
            named[path] = hits
    tracked_core = [p for p in all_core if p in texts]
    for path, hits in named.items():
        base = os.path.basename(path)
        if base.startswith("test_"):
            users = [path] if path in tracked_core else []
        elif base == "conftest.py":
            users = [p for p in tracked_core if p.startswith(path[:-len(base)])]
        else:
            stem = base[:-3]
            word = re.escape(stem)
            uses = re.compile(rf"\b(?:import|from)\s+(?:[\w.]*\.)?{word}\b|\bimport\s+[^\n]*\b{word}\b")
            importers = [p for p in texts if p != path and stem in texts[p] and uses.search(texts[p])]
            users = [p for p in importers if p in tracked_core]
            for conftest in (p for p in importers if os.path.basename(p) == "conftest.py"):
                users += [p for p in tracked_core if p.startswith(conftest[:-len("conftest.py")])]
        for user in users:
            why = f"names {', '.join(hits)}" + ("" if user == path else f" (through {path})")
            core.setdefault(user, why)
    suites = [f"{folder}/tests" for folder in here
              if folder.startswith("modules/") and os.path.isdir(os.path.join(project_root, folder, "tests"))]
    gone = [f"{folder}/tests" for folder in here
            if folder.startswith("modules/") and f"{folder}/tests" not in suites]
    return {"core": dict(sorted(core.items())), "suites": suites, "missing": missing + gone,
            "private_repo": os.path.isdir(project_root + ".priv.git")}


def _local_only_summary(part):
    """The set's size, by part: said on every --local-only run."""
    untracked = sum(1 for why in part["core"].values() if not why.startswith("names "))
    lines = [f"Local-only set: {len(part['core'])} core test file(s) ({untracked} the public repo doesn't track, "
             f"{len(part['core']) - untracked} naming a private folder) + {len(part['suites'])} private module "
             f"suite(s){': ' + ', '.join(part['suites']) if part['suites'] else ''}"]
    if part["missing"]:
        lines.append(f"  NOT HERE (a private folder this checkout lacks, or a private module without its tests/): "
                     f"{', '.join(part['missing'])}")
    if not part["private_repo"]:
        lines.append("  no private repo beside this checkout (<top folder>.priv.git): a private module it lacks can't "
                     "be named")
    return "\n".join(lines)


def run_local_only(project_root, listing=False):
    """`--local-only`: the local-only set (local_only()), run as --all runs its part. 0 when all passed; 2 when git
    can't list the public repo's files (nothing run)."""
    part = local_only(project_root)
    if part is None:
        print("--local-only: git can't list the public repo's files here, or the private repo's: nothing was run.")
        return 2
    print(_local_only_summary(part), flush=True)
    if listing:
        for path, why in part["core"].items():
            print(f"  {path}  ({why})")
        for suite in part["suites"]:
            print(f"  {suite}  (a private module's suite)")
        return 0
    return run_all(project_root, only=part)


def _run_shard(project_root, label, files, times_path):
    """Run one core shard (its files, in one pytest process) to the end. Returns (label, exit code, output, seconds)."""
    started = time.perf_counter()
    env = os.environ.copy()
    env["SURASURA_TEST_TIMES"] = times_path
    result = _run(
        [sys.executable, "-m", "pytest", *files, "-ra", "-p", "no:cacheprovider"],
        cwd=project_root, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    code = 0 if result.returncode == 5 else result.returncode     # 5: no tests in these files (a helper's), no failure
    return label, code, _decode(result.stdout), time.perf_counter() - started


# --- --shard I/N: one shard of the core suite -------------------------------------------------- #
# GitHub's PR tests (.github/workflows/pr.yml) run the core suite as N jobs side by side, each well under the runner's
# time cap: job I runs `python run_tests.py --shard I/N`, the core files of shard I, packed as --all packs them. Every
# job packs the same checkout the same way, so each file runs in exactly one job.

def _shard_of(project_root, spec):
    """The core files of shard `spec` ("I/N", 1 <= I <= N), in path order. ValueError for anything else."""
    i, n = (int(part) for part in spec.split("/"))
    if not 1 <= i <= n:
        raise ValueError(spec)
    shards = _shards(project_root, _core_files(project_root), n)
    return shards[i - 1] if i <= len(shards) else []       # more shards than files: the extra ones are empty


# A pytest process that died by a Windows status, not an exit of its own (flakes-2026-11-05 #5): GitHub's bash shows
# every one as 127, which names nothing. Said in hex with its kind: an access violation, or a fail-fast that leaves
# no faulthandler line (a guarded call through freed memory), are different hunts.
DEATHS = {0xC0000005: "an access violation", 0xC0000409: "a fail-fast (a guarded call or a stack check)",
          0xC0000374: "heap corruption", 0xC00000FD: "a stack overflow", 0xC000013A: "Ctrl+C or the job ended",
          0x40000015: "abort()"}


def death(code):
    """The words for a pytest process's exit `code` when a Windows status ended it (it never finished), else None."""
    status = code & 0xFFFFFFFF if isinstance(code, int) and code >= 0 else 0     # (negative: a POSIX signal)
    if status == 3:                     # pytest's own internal error prints INTERNALERROR lines; abort() prints nothing
        return "exit 3: abort() (Qt's qFatal, a fatal Python error) unless INTERNALERROR lines are above"
    if status < 0x40000000:
        return None
    return f"the process died: exit 0x{status:08X}, {DEATHS.get(status, 'a Windows status')}"


def run_shard(project_root, spec):
    """`--shard I/N`: run that shard's files, verbose like the default run. Returns pytest's exit code, as the default
    run does (5, nothing collected, fails); 2 for a bad I/N or a checkout with no core test files."""
    try:
        files = _shard_of(project_root, spec)
    except ValueError:
        print(f"--shard takes I/N with 1 <= I <= N, not {spec!r}")
        return 2
    if not _core_files(project_root):
        print(f"No core test files under {os.path.join(project_root, 'tests')}")
        return 2
    print(f"Core suite, shard {spec}: {len(files)} files", flush=True)
    if not files:                                          # more shards than files: nothing of the suite is lost
        return 0
    result = _run([sys.executable, "-m", "pytest", *files, "-v", "-ra"],
                            cwd=project_root, env=os.environ.copy())
    died = death(result.returncode)
    if died:
        print(f"\nCore suite, shard {spec}: {died}, in the test named last above", flush=True)
    return result.returncode


def _decode(raw):
    """A suite's captured output, decoded the way the child wrote it (it has our environment):
    PYTHONIOENCODING if set, else the locale's encoding. Display only, so it never raises."""
    encoding = os.environ.get("PYTHONIOENCODING", "").split(":")[0] or locale.getpreferredencoding(False)
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _run_suite(project_root, suite):
    """Run one suite to the end. Returns (suite, exit code, output, seconds)."""
    started = time.perf_counter()
    result = _run(
        [sys.executable, "-m", "pytest", suite, "-ra", "-p", "no:cacheprovider"],
        cwd=project_root, env=os.environ.copy(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return suite, result.returncode, _decode(result.stdout), time.perf_counter() - started


def _last_line(output):
    """pytest's closing summary ("1227 passed, 2 skipped in 65.9s") without its ===== rule."""
    lines = [line.strip(" =") for line in output.splitlines() if line.strip(" =")]
    return lines[-1] if lines else "(no output)"


def run_all(project_root, only=None):
    """Run every suite at once, each in its own process (the core suite in shards). Returns 0 only if every suite
    passed. `only`: --local-only's part (local_only()): its core files and module suites alone, run the same way."""
    # A suite's output can hold characters this console can't print; escape them, don't crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    suites = _suites(project_root) if only is None else (["tests"] if only["core"] else []) + only["suites"]
    files = _core_files(project_root) if only is None else list(only["core"])
    cpus = os.cpu_count()
    chosen = os.environ.get("SURASURA_TEST_SHARDS", "").strip().isdigit()
    idle = None if chosen or len(files) < 2 else _idle_cpus(cpus)        # half a second, spent only when it counts
    count = min(_shard_count(_free_memory_mb(), cpus, idle), len(files)) if len(files) > 1 else 1
    # A part's core files always go as shards (one at least): never `pytest tests`, the whole core suite.
    shards = _shards(project_root, files, count) if count > 1 or (only is not None and files) else []
    jobs = [(f"tests [{i}/{len(shards)}]", shard) for i, shard in enumerate(shards, 1)] or \
        ([("tests", None)] if "tests" in suites else [])
    jobs += [(suite, None) for suite in suites if suite != "tests"]

    print("\n" + "="*60)
    print("   SURASURA TEST SUITE RUNNER  " + ("(--all: every suite at once)" if only is None else
                                             "(--local-only: what GitHub's pull request run can't run)"))
    print("="*60 + "\n")
    if not jobs:
        print("Nothing to run: no local-only test file and no private module suite here.")
        return 0
    split = f" (the core suite in {len(shards)} shards)" if shards else ""
    print(f"Running {len(suites)} suites in parallel{split}: {', '.join(suites)}\n", flush=True)

    import tempfile
    times_dir = tempfile.mkdtemp(prefix="surasura-times-")
    started = time.perf_counter()
    results = {}
    try:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(_run_shard, project_root, label, files_, os.path.join(times_dir, f"{i}.json"))
                       if files_ else pool.submit(_run_suite, project_root, label)
                       for i, (label, files_) in enumerate(jobs)]
            for future in as_completed(futures):
                label, code, output, secs = future.result()
                results[label] = (code, output, secs)
                verdict = "PASS" if code == 0 else "FAIL"
                print(f"  {verdict}  {label:<34} {secs:5.1f}s  {_last_line(output)}", flush=True)
        wall = time.perf_counter() - started
        if shards:
            _save_times(project_root, [os.path.join(times_dir, f"{i}.json") for i in range(len(shards))])
    finally:
        shutil.rmtree(times_dir, ignore_errors=True)

    failed_jobs = [label for label, _ in jobs if results[label][0] != 0]
    for label in failed_jobs:
        print("\n" + "="*60)
        print(f"   FAILED: {label} ({death(results[label][0]) or f'exit code {results[label][0]}'})")
        print("="*60)
        print(results[label][1])
    failed = [suite for suite in suites if any(label == suite or label.startswith(suite + " [") for label in failed_jobs)]

    print("\n" + "-"*60)
    if failed:
        print(f"  [FAIL]  {len(failed)} OF {len(suites)} SUITES FAILED: {', '.join(failed)}")
    else:
        print(f"  [PASS]  ALL {len(suites)} SUITES PASSED")
    print(f"  Wall time {wall:.1f}s (the suites took {sum(r[2] for r in results.values()):.1f}s between them)")
    print("-" * 60)
    return 1 if failed else 0


# --- --stress, --stress-changed: the same tests again and again, the machine loaded ----------------------------- #
# A flake is a test whose answer depends on the machine's timing (tests/FLAKES.md). `--stress [N]` runs the stress set
# (tests/stress/: real concurrency, invariants only, never a timing) N times; `--stress-changed [BASE]` runs every test
# the branch changed since BASE (default origin/3.0-dev) STRESS_TIMES times in a row, each suite's tests in their own
# process, while two core shards run beside them as load — a lane's last check before READY
# (_work/prompts/train-rule.md § 1). Either stops at the first red and prints it whole.
# The changed tests (Tool-T, 2026-11-12; whole files before, which held a slot for hours): by test function, from the
# lines changed between BASE's merge-base and the working tree — a test whose own lines changed (added or edited), and
# a test in a changed test file that uses a changed name: a helper, fixture or constant of its file (and whatever of
# the file's uses one), or a function, method or constant of the app's code that the branch changed. A test file that
# doesn't parse goes whole.

STRESS_TIMES = 20
LOAD_SHARDS = ("1/4", "3/4")             # the load beside --stress-changed: two quarters of the core suite, looped


def _suite_of(path):
    """The suite a test file belongs to (its own process): "tests", or "modules/<name>/tests"."""
    parts = path.replace(os.sep, "/").split("/")
    return "/".join(parts[:3]) if parts[0] == "modules" and len(parts) > 3 and parts[2] == "tests" else "tests"


def _changed_test_files(project_root, base):
    """The test files (test_*.py under tests/ or modules/*/tests/, still on disk) changed between BASE and HEAD, plus
    those changed and not yet committed, in path order."""
    names = set()
    for args in (["diff", "--name-only", f"{base}...HEAD"], ["diff", "--name-only", "HEAD"]):
        out = _run(["git", "-c", "core.quotepath=false", *args], cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        names.update(line.strip() for line in _decode(out.stdout).splitlines() if line.strip())
    return sorted(n for n in names if _is_test_file(n) and os.path.isfile(os.path.join(project_root, n)))


def _is_test_file(path):
    """A test file: test_*.py under tests/ or modules/*/tests/ (a path from the project root, with /)."""
    return (os.path.basename(path).startswith("test_") and path.endswith(".py")
            and (path.startswith("tests/") or (path.startswith("modules/") and "/tests/" in path)))


def _git_out(project_root, *args):
    try:
        out = _run(["git", *args], cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:                                          # no git on PATH: as a failed git
        return ""
    return _decode(out.stdout) if out.returncode == 0 else ""


def _changed_lines(project_root, base):
    """{path: the line numbers changed in the working tree's copy} between BASE's merge-base with HEAD and the working
    tree (committed and not yet committed alike); a deletion marks the line before it (inside the definition it
    was cut from, unless it was a whole one: its users changed too)."""
    rev = _git_out(project_root, "merge-base", base, "HEAD").strip() or base
    lines, path, before = {}, None, ""
    for line in _git_out(project_root, "-c", "core.quotepath=false", "diff", "-U0", "--no-color", "--no-ext-diff", rev,
                         "--").splitlines():
        if line.startswith("+++ ") and before.startswith("--- "):   # (an added line "++ x" reads "+++ x": no header)
            name = line[4:].strip()
            path = name[2:] if name.startswith("b/") else None
            if path:
                lines.setdefault(path, set())
        elif line.startswith("@@") and path:
            new = line.split("+", 1)[1].split(" ", 1)[0]
            start, _sep, count = new.partition(",")
            start, count = int(start), int(count or 1)
            lines[path].update(range(start, start + count) if count else (start,))
        before = line
    return lines


def _defs(source):
    """The top-level definitions of a Python source: (path, start, end, names it uses), path ("f",), ("C",) for a
    class's own lines or ("C", "m") for its methods; a decorator's lines count as its definition's."""
    out = []

    def used(node):
        names = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                names.add(n.id)
            elif isinstance(n, ast.Attribute):
                names.add(n.attr)
            elif isinstance(n, ast.arg):
                names.add(n.arg)                            # (a fixture is asked for by its parameter's name)
        return names

    def span(node):
        return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]), node.end_lineno
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(((node.name,), *span(node), used(node)))
        elif isinstance(node, ast.ClassDef):
            out.append(((node.name,), *span(node), used(node)))
            out.extend(((node.name, m.name), *span(m), used(m)) for m in node.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                for n in ast.walk(target):
                    if isinstance(n, ast.Name):
                        out.append(((n.id,), node.lineno, node.end_lineno, used(node.value) if node.value else set()))
    return out


def _is_test(path):
    return (len(path) == 1 and path[0].startswith("test")) or (len(path) == 2 and path[0].startswith("Test")
                                                               and path[1].startswith("test"))


def _touched(defs, changed):
    """The definitions with a changed line; a line inside a method is the method's, not its class's."""
    hit = set()
    for path, start, end, _names in defs:
        lines = {n for n in changed if start <= n <= end}
        if not lines:
            continue
        if len(path) == 1:
            methods = [(s, e) for p, s, e, _n in defs if len(p) == 2 and p[0] == path[0]]
            lines = {n for n in lines if not any(s <= n <= e for s, e in methods)}
        if lines:
            hit.add(path)
    return hit


def _changed_tests(project_root, base):
    """The tests changed since BASE (see above), as pytest node ids in path order -> (node ids, notes)."""
    lines = _changed_lines(project_root, base)
    app_names = set()
    for path, changed in lines.items():                       # what the branch changed in the app's code
        if not path.endswith(".py") or _is_test_file(path) or not os.path.isfile(os.path.join(project_root, path)):
            continue
        try:
            defs = _defs(_read_source(project_root, path))
        except SyntaxError:
            continue
        app_names.update(p[-1] for p in _touched(defs, changed) if not p[-1].startswith("__"))
    ids, notes = [], []
    for path in _changed_test_files(project_root, base):
        try:
            defs = _defs(_read_source(project_root, path))
        except SyntaxError:
            ids.append(path)
            notes.append(f"{path}: doesn't parse, run whole")
            continue
        touched = _touched(defs, lines.get(path, set()))
        names = {p[0] for p in touched if not _is_test(p)} | app_names   # (a helper class's method: the class)
        grew = True
        while grew:                                           # a helper that uses a changed name has changed too
            grew = False
            for p, _s, _e, used in defs:
                if not _is_test(p) and p[0] not in names and used & names:
                    names.add(p[0])
                    grew = True
        classes = {p[0] for p in touched if p[0].startswith("Test") and not _is_test(p)}   # a test class's own
        # lines or one of its fixtures / helper methods: every test of the class
        picked = [p for p, _s, _e, used in defs if _is_test(p) and (p in touched or used & names or p[0] in classes)]
        if not picked:
            notes.append(f"{path}: no test changed (its changed lines are outside every test and helper)")
        ids.extend(path + "".join("::" + part for part in p) for p in dict.fromkeys(picked))
    return ids, notes


def _read_source(project_root, path):
    with open(os.path.join(project_root, path), "rb") as f:
        return f.read()


ARGS_MAX = 20000                         # characters of node ids in one pytest command (Windows' line: 32,767)


def _repeat(project_root, groups, times, env):
    """Each (label, pytest args) group run `times` times in a row, one process each. -> (label, run, output) of the
    first red, or None."""
    for n in range(1, times + 1):
        for label, args in groups:
            result = _run([sys.executable, "-m", "pytest", *args, "-q", "-ra", "-p", "no:cacheprovider"],
                                    cwd=project_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            code = result.returncode
            print(f"  {'PASS' if code == 0 else 'FAIL'}  {label} run {n}/{times}  {_last_line(_decode(result.stdout))}",
                  flush=True)
            if code != 0:
                return label, n, (death(code) or f"exit code {code}") + "\n" + _decode(result.stdout)
    return None


def run_stress(project_root, times=1):
    """`--stress [N]`: the stress set (tests/stress/), N times. 0 when every run passed."""
    env = os.environ.copy()
    env["SURASURA_STRESS"] = "1"
    folder = os.path.join("tests", STRESS_DIR)
    print(f"Stress set ({folder}), {times} time(s)", flush=True)
    red = _repeat(project_root, [("stress", [folder])], times, env)
    if red:
        print(f"\n  [FAIL]  {red[0]}, run {red[1]}: {red[2]}")
        return 1
    print(f"\n  [PASS]  the stress set passed {times} time(s)")
    return 0


def run_stress_changed(project_root, base="origin/3.0-dev", times=STRESS_TIMES, listing=False):
    """`--stress-changed [BASE]`: every test changed since BASE beside two core shards — the ones that wait on time or
    threads `times` times, the others once (see TIMING). 0 when every run passed (a branch that changed no test passes
    at once, and says so). `listing`: the picks and their counts, nothing run."""
    ids, notes = _changed_tests(project_root, base)
    for note in notes:
        print(f"  ({note})")
    if not ids:
        print(f"No test changed since {base}: nothing to repeat")
        return 0
    timed, steady = _timing_tests(project_root, ids)
    files = len({node.split("::", 1)[0] for node in ids})
    print(f"{len(ids)} changed test(s) in {files} file(s) since {base}, beside core shards {' and '.join(LOAD_SHARDS)}: "
          f"{len(timed)} wait on time or threads, {times} times each; {len(steady)} don't, once:", flush=True)
    for node in timed:
        print(f"  x{times}  {node}")
    for node in steady:
        print(f"  x1   {node}")
    if listing:
        return 0
    def start(spec):
        return _popen([sys.executable, os.path.abspath(__file__), "--shard", spec], cwd=project_root,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    loads = {spec: start(spec) for spec in LOAD_SHARDS}      # started before the first repeat, ended after the last
    stop = threading.Event()

    def keep_loading():                                     # a shard that ends starts again; its result is no verdict
        while not stop.wait(0.5):
            for spec, proc in list(loads.items()):
                if proc.poll() is not None:
                    loads[spec] = start(spec)
    keeper = threading.Thread(target=keep_loading, name="stress-load", daemon=True)
    keeper.start()
    try:
        red = (_repeat(project_root, sorted(_groups(steady, " (once)").items()), 1, os.environ.copy())
               or _repeat(project_root, sorted(_groups(timed).items()), times, os.environ.copy()))
    finally:
        stop.set()
        keeper.join(60)
        for proc in loads.values():
            _end_tree(proc)
    if red:
        print(f"\n  [FAIL]  {red[0]}, run {red[1]} of {times}: {red[2]}")
        return 1
    print(f"\n  [PASS]  every changed test passed under load: {len(timed)} of them {times} times, {len(steady)} once")
    return 0


def _groups(nodes, suffix=""):
    """{label: node ids}: each suite's tests, split where one command would be too long (ARGS_MAX)."""
    groups, size = {}, {}
    for node in nodes:
        suite = _suite_of(node.split("::", 1)[0])
        part = size.get(suite, (1, 0))
        if part[1] + len(node) > ARGS_MAX:
            part = (part[0] + 1, 0)
        size[suite] = (part[0], part[1] + len(node) + 1)
        label = (suite if part[0] == 1 else f"{suite} (part {part[0]})") + suffix
        groups.setdefault(label, []).append(node)
    return groups


def _end_tree(proc):
    """End a load shard and every process it started (pytest's own children too)."""
    if sys.platform == "win32":
        _run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    else:
        proc.kill()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        pass


# --- --stress-changed: only the tests that wait on time repeat (Minato-TS, 2026-11-21) ------------------------------- #
# A test can flake only where its answer waits on the clock or on another thread: a sleep, a Qt wait or timer, an
# event / join / thread / process, a deadline. Repeating a test with none of those twenty times under load finds
# nothing a single run doesn't (Mado-EZC's runs: 12m49s and 56m05s, ~70 % of its 218 picked tests with no wait), so
# those run ONCE, under the same load, and the rest STRESS_TIMES times. Static: the test's own lines, every helper,
# fixture or constant it uses (of its file, its folder's conftest.py and those above it, a tests.* module it imports
# names from), and theirs in turn; its file's own autouse fixtures too. A file that doesn't parse, or can't be read,
# repeats whole, as before.

TIMING = re.compile(r"\b(?:sleep|qWait\w*|waitUntil|waitSignals?|waitExposed|waitActive|waitCallback|wait_until|wait_for\w*|"
                    r"singleShot|QTimer|QThread\w*|processEvents|settle\w*|threading|Thread\w*|Event|Condition|Barrier|"
                    r"Semaphore|Lock|Popen|subprocess|multiprocessing|asyncio|concurrent|\w*Executor|\w*Pool|monotonic|"
                    r"perf_counter|timeout|deadline|time\.time(?:_ns)?|exec|acquire|communicate|recv\w*|poll\w*|\w*Queue)\b|"
                    r"\.wait\(|\.join\(\s*(?:\)|timeout|\d|[A-Za-z_]\w*\s*\))|\.start\(\s*\)")   # (t.join(left), never
#                                                                                   "/".join([...]) nor os.path.join(a, b))


def _text(project_root, path):
    """A source as text (a byte-order mark dropped: ast refuses one)."""
    return _read_source(project_root, path).decode("utf-8-sig", "replace")


def _lines(text):
    """A source's lines as ast numbers them (\\r\\n, \\r or \\n: never a form feed or U+2028, as splitlines would)."""
    return re.split(r"\r\n|\r|\n", text)


def _helper_sources(project_root, path, tree):
    """The other sources a test file's tests can reach by name: its folder's conftest.py and each above it up to tests/
    (or a module's tests/), and each tests.* module it imports from. -> [(path, source text)]."""
    out, seen = [], {path}
    folder = os.path.dirname(path)
    while folder and folder not in ("", "."):
        conf = f"{folder}/conftest.py"
        if conf not in seen and os.path.isfile(os.path.join(project_root, conf)):
            seen.add(conf)
            out.append(conf)
        if folder in ("tests",) or folder.endswith("/tests") and folder.startswith("modules/"):
            break
        folder = os.path.dirname(folder)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "tests":
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]   # (from tests import helpers)
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names if a.name.split(".")[0] == "tests"]
        for name in names:
            for candidate in (name.replace(".", "/") + ".py", name.replace(".", "/") + "/__init__.py"):
                if candidate not in seen and os.path.isfile(os.path.join(project_root, candidate)):
                    seen.add(candidate)
                    out.append(candidate)
    texts = []
    for p in out:
        try:
            texts.append((p, _text(project_root, p)))
        except OSError:
            continue
    return texts


def _spans(source):
    """{name: [(source text of that definition, names it uses)]} for a source's top-level definitions (a class's
    methods under the class's name too, so a fixture method or helper method is reached through its class), and the
    functions and classes defined under a top-level `if` / `try` / `with` (a helper per platform)."""
    lines = _lines(source)
    out = {}
    for path, start, end, used in _defs(source):
        out.setdefault(path[0], []).append(("\n".join(lines[start - 1:end]), used))
    for top in ast.parse(source).body:
        if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
            continue
        for node in ast.walk(top):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                used |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                used |= {n.arg for n in ast.walk(node) if isinstance(n, ast.arg)}
                out.setdefault(node.name, []).append(("\n".join(lines[node.lineno - 1:node.end_lineno]), used))
    return out


def _autouse(source):
    """The names of a source's own autouse fixtures."""
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                if any(isinstance(k, ast.keyword) and k.arg == "autouse" and getattr(k.value, "value", None) is True
                       for k in getattr(d, "keywords", ())):
                    names.add(node.name)
    return names


def _timing_tests(project_root, ids):
    """`ids` (node ids) split -> (the ones that wait on time or threads, the ones that don't), each in its order."""
    by_file, timed, steady = {}, set(), set()
    for node in ids:
        by_file.setdefault(node.split("::", 1)[0], []).append(node)
    for path, nodes in by_file.items():
        try:
            source = _text(project_root, path)
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            timed.update(nodes)                               # can't tell: as before, every repeat
            continue
        own = _spans(source)
        pool = {}
        for _p, text in reversed(_helper_sources(project_root, path, tree)):   # nearer conftests win, the file over all
            try:
                pool.update(_spans(text))
            except (SyntaxError, ValueError):
                continue
        pool.update(own)
        start = _autouse(source)
        for node in nodes:
            if "::" not in node:                              # a whole file (didn't parse before): every repeat
                timed.add(node)
                continue
            parts = node.split("::")[1:]
            names, todo, hit = set(), [parts[0]] + sorted(start), False
            texts = []
            if len(parts) == 2:                               # a test class's method: the class's own lines and the method
                texts += [t for t, _u in own.get(parts[0], [])]
            while todo and not hit:
                name = todo.pop()
                if name in names:
                    continue
                names.add(name)
                for text, used in pool.get(name, []):
                    texts.append(text)
                    todo.extend(u for u in used if u in pool and u not in names)
                hit = any(TIMING.search(t) for t in texts)
            (timed if hit or any(TIMING.search(t) for t in texts) else steady).add(node)
    return [n for n in ids if n in timed], [n for n in ids if n in steady]


# --- --guards: the whole-repo guard tests, before every push (Minato-TS, 2026-11-21) -------------------------------- #
# Of the four GitHub-only reds on 2026-11-20, three were whole-repo scans that take seconds; 2026-11-21 brought three
# more (the press rule, the picture-mode scrub again, the stacked-rows pin) and a build-spec read. A lane's touched
# run never ran them (they read the app's source, not the lane's code), so GitHub found them, a CI cycle each.
# GUARDS: every test that reads the app's own source as text (an AST or grep scan, a walk of app/ or app/qt/, a pin of
# a list in the code) — found by what they do, not by name: a read-audit survey of a whole --all
# (tests/read_audit.py, survey mode, 2026-11-21) listed each test that opened a tracked .py / .qss / .html / .js /
# .json of the app as a file, not an import. Each row: the test (a file, or a file::test when the file's other tests
# are no guards), and the folders whose change makes it the area's guard for --touched-callers.
# A new guard (a test that scans the app's source) is added here in the same pull request.

GUARDS = {
    ("modules/junban/tests/test_module_contract.py::"
     "test_every_setting_is_either_honoured_or_declared_inert"): ("app/", "modules/"),
    ("tests/connect/test_never_opens_anki.py::"
     "test_only_a_windows_session_start_calls_open_anki_start"): ("app/", "modules/"),
    "tests/connect/test_no_auto_pins.py::test_no_code_outside_the_store_writes_a_pin": ("app/", "modules/"),
    "tests/qt/test_bridge.py::test_no_user_string_is_written_inline_under_app_qt": ("app/", "modules/"),
    ("tests/qt/test_entry.py::"
     "test_the_window_route_sends_the_heartbeat_once_before_the_window"): ("app/qt/", "app/services/"),
    "tests/qt/test_motion.py::test_no_literal_spring_constants_under_app_qt": ("app/qt/",),
    "tests/qt/test_motion.py::test_no_other_animation_engine_and_no_motion_literals_under_app_qt": ("app/", "modules/"),
    "tests/qt/test_picture_mode.py::test_every_delegate_of_its_own_reads_its_words_through_the_scrub": ("app/qt/",),
    ("tests/qt/test_picture_mode.py::"
     "test_every_painter_in_the_window_draws_its_text_through_the_scrub_or_says_why_it_needs_none"): ("app/qt/",),
    "tests/qt/test_picture_mode.py::test_every_shortened_text_in_the_window_is_scrubbed_before_it_is_cut": ("app/qt/",),
    "tests/qt/test_press_static.py::test_every_allowed_entry_still_names_a_function_and_says_why": ("app/", "modules/"),
    "tests/qt/test_press_static.py::test_no_press_hands_its_work_over_except_through_press": ("app/", "modules/"),
    ("tests/qt/test_reduced_motion.py::"
     "test_every_motion_entry_point_has_a_sweep_entry_and_every_entry_is_driven"): ("app/qt/",),
    "tests/qt/test_style.py::test_no_colour_is_spelled_under_app_qt": ("app/qt/",),
    "tests/qt/test_wiring.py::test_no_modal_dialog_and_no_qprocess_in_the_window": ("app/", "modules/"),
    "tests/qt/test_wiring.py::test_the_window_never_names_the_2x_folders": ("app/", "modules/"),
    "tests/test_anki_address.py::test_no_code_reads_either_address_key_but_the_one_function": ("app/", "modules/"),
    ("tests/test_anki_deck_options.py::"
     "test_savedeckconfig_is_sent_only_through_the_one_door_by_the_one_caller"): ("app/", "modules/"),
    "tests/test_cli_imports.py::test_no_cli_source_names_a_dialog_toolkit": ("app/cli/",),
    ("tests/test_flake_lints.py::"
     "test_this_tree_has_nothing_the_allowlist_doesnt_explain_and_no_entry_left_over"): ("app/", "modules/"),
    "tests/test_guard_lints.py": ("app/", "modules/"),
    "tests/test_import_guard.py::test_no_file_outside_the_windows_folders_imports_qt": ("app/", "modules/"),
    ("tests/test_import_guard.py::"
     "test_nothing_outside_the_window_reaches_qt_or_the_window_but_the_entrys_one_door"): ("app/", "modules/"),
    "tests/test_import_guard.py::test_the_window_imports_only_the_qt_modules_the_stack_names": ("app/", "modules/"),
    "tests/test_list_reader.py::test_no_list_reader_goes_around_the_shared_one": ("app/", "modules/"),
    "tests/test_packaging_config.py": ("app/", "modules/", "packaging/", "app_entry.py", "package_app.py"),
    "tests/test_profile_parts.py::test_every_place_the_code_names_a_data_root_is_counted_here": ("app/", "modules/"),
    ("tests/test_run_tests_runner.py::"
     "test_githubs_run_and_the_local_only_run_hold_every_file_of_all_between_them"): ("tests/", "modules/", ".github/",
                                                                                      "run_tests.py"),
    ("tests/test_run_tests_runner.py::"
     "test_no_tracked_core_test_file_imports_a_private_module_outside_the_local_only_set"): ("tests/", "modules/",
                                                                                             "run_tests.py"),
    ("tests/test_scrub.py::"
     "test_every_short_hash_in_the_app_is_an_install_key_identity_knows_or_hashes_no_install"): ("app/", "modules/"),
    ("tests/test_services_phase.py::"
     "test_every_job_kind_the_window_can_register_names_its_circle_or_none"): ("app/", "modules/"),
    ("tests/test_settings_catalog.py::"
     "test_an_empty_slot_row_with_no_filler_fails_the_placement_proof"): ("app/", "modules/"),
    ("tests/test_settings_catalog.py::"
     "test_every_installed_placed_setting_is_in_exactly_one_row_or_not_shown"): ("app/", "modules/"),
    "tests/test_tsubasa_bundle.py::test_nothing_of_surasuras_imports_tsubasa": ("app/", "modules/"),
    "tests/test_w41_place_names.py": ("app/qt/",),
}

GUARDS_BUDGET_S = 120


def _public_files(project_root):
    """The files the public repo tracks (what GitHub's runner checks out), as paths from the top, or None."""
    out = _run(["git", "-c", "core.quotepath=false", "ls-files", "-z"], cwd=project_root,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if out.returncode != 0:
        return None
    return {p for p in out.stdout.decode("utf-8", "replace").split("\0") if p}


def _audit_env():
    """The environment for a run under the read audit (tests/read_audit.py): no test may read a file the public repo
    ignores (2026-11-20: lists/jmnedict.zip, on this PC only, went red on GitHub only)."""
    env = os.environ.copy()
    env["SURASURA_READ_AUDIT"] = "ignored"
    return env


def _by_suite(nodes):
    """Node ids or files grouped by the suite (its own process) they belong to, in order."""
    groups = {}
    for node in nodes:
        groups.setdefault(_suite_of(node.split("::", 1)[0]), []).append(node)
    return groups


def _run_groups(project_root, groups, env, label):
    """Each suite's tests in one pytest process (the read audit on), side by side. -> (failed suites, outputs)."""
    def one(suite, nodes):
        result = _run([sys.executable, "-m", "pytest", *nodes, "-q", "-ra", "-p", "no:cacheprovider",
                                 "-p", "tests.read_audit"], cwd=project_root, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return suite, result.returncode, _decode(result.stdout)
    failed, outputs = [], {}
    if not groups:
        return failed, outputs
    with ThreadPoolExecutor(max_workers=len(groups)) as pool:
        for future in as_completed([pool.submit(one, s, n) for s, n in groups.items()]):
            suite, code, output = future.result()
            outputs[suite] = output
            code = 0 if code == 5 else code
            print(f"  {'PASS' if code == 0 else 'FAIL'}  {label} {suite:<28} {_last_line(output)}", flush=True)
            if code != 0:
                failed.append(suite)
    return failed, outputs


def run_guards(project_root, listing=False):
    """`--guards`: every whole-repo guard test (GUARDS), under the read audit. 0 when all passed."""
    nodes = [n for n in GUARDS if os.path.isfile(os.path.join(project_root, n.split("::", 1)[0]))]
    gone = [n for n in GUARDS if n not in nodes]
    print(f"Guard set: {len(nodes)} whole-repo guard test(s)/file(s), the read audit on"
          + (f" ({len(gone)} not in this checkout: {', '.join(gone)})" if gone else ""), flush=True)
    if listing:
        for n in nodes:
            print(f"  {n}")
        return 0
    started = time.perf_counter()
    failed, outputs = _run_groups(project_root, _by_suite(nodes), _audit_env(), "guards")
    wall = time.perf_counter() - started
    for suite in failed:
        print("\n" + "=" * 60 + f"\n   FAILED: guards in {suite}\n" + "=" * 60 + "\n" + outputs[suite])
    over = f" — over its {GUARDS_BUDGET_S} s budget: tell the lead" if wall > GUARDS_BUDGET_S else ""
    print(f"\n  [{'FAIL' if failed else 'PASS'}]  the guard set, {wall:.1f}s{over}")
    return 1 if failed else 0


# --- --touched-callers [BASE]: a lane's touched run (Minato-TS, 2026-11-21) ------------------------------------------ #
# A lane tests what it changed, not a glob of its area: 5 of 26 "touched" runs on 2026-11-20 took 19-28 min, and
# Kura-SO's ran all 29 test_library_store_*.py though 6 reach the changed code. The picks, from the lines changed
# since BASE's merge-base (committed or not), each with its reason:
#   - every test file the branch changed (whole: its own tests, its helpers);
#   - every test file that names a changed definition of the app's code (a function, method, constant, or a class's
#     own lines), by name in its code (never its comments or strings, but a patch target's): the callers, as
#     --stress-changed picks tests. A name many test files use (more than RARE_TESTS, or COMMON) counts only in a file
#     that imports the changed module: `replace` or `record` alone would pick every file. Not its callers' callers
#     (measured on five lanes' branches, 2026-11-21: one step further doubled the picks, 13 -> 23 min for Kura-SO):
#     what reaches the change only through another function is the GitHub run's and the train's --all;
#   - every test file under a changed conftest.py's folder, or that imports a changed test helper;
#   - every test file that names a changed data file, template or stylesheet (its whole file name, or its folder's when
#     few test files name it);
#   - the area's guards: each GUARDS row whose folders hold a changed file.
# Run under the read audit (no test reads a git-ignored file), one process per suite. `--list` prints the picks only.

RARE_TESTS = 12
COMMON = {"run", "main", "load", "save", "get", "set", "start", "stop", "close", "open", "read", "write", "update",
          "add", "remove", "clear", "reset", "show", "hide", "refresh", "build", "make", "apply", "check", "name",
          "path", "text", "value", "items", "keys", "data", "result", "state", "label", "title", "language", "done",
          "setup", "teardown", "paint", "paintEvent", "resizeEvent", "showEvent", "closeEvent", "keyPressEvent",
          "event", "eventFilter", "sizeHint", "changed", "clicked", "toggled", "finished", "started"}


def _imports(text, module):
    """True when a source imports the module at `module` (a path: app/connect/library.py): `import
    app.connect.library`, `from app.connect.library import ...`, `from app.connect import (..., library, ...)`, or names
    its dotted path (a patch target, an importlib string). A test helper (tests/connect_helpers.py) the same way."""
    p = module[:-3] if module.endswith(".py") else module
    if p.endswith("/__init__"):
        p = p[:-9]
    dotted = p.replace("/", ".")
    if dotted in text:
        return True
    package, _sep, stem = dotted.rpartition(".")
    if not package:
        return re.search(r"^\s*import\s+" + re.escape(stem) + r"\b", text, re.M) is not None
    for m in re.finditer(r"from\s+" + re.escape(package) + r"\s+import\s+(\([^)]*\)|[^\n]*)", text):
        if re.search(r"(?<![\w.])" + re.escape(stem) + r"(?![\w])", m.group(1)):
            return True
    return False


def _idents(text):
    """The names a source's code uses (never its comments or the words of its strings): names, attributes, imports,
    definitions, arguments, keywords, and a string that is a name or a dotted path (a patch target). A source that
    doesn't parse: every word in it."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set(re.findall(r"\w+", text))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.alias):
            out.update(n.name.split("."))
            if n.asname:
                out.add(n.asname)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            out.add(n.arg)
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.update(n.module.split("."))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and re.fullmatch(r"[A-Za-z_][\w.]*", n.value):
            out.update(n.value.split("."))
    return out


def _changed_app_names(project_root, lines):
    """{module path: the names changed in it} for the app's code (every .py that isn't under a tests/ folder): each
    changed function, method, constant and class (its own lines); a changed dunder method (__init__) names its class,
    a dunder constant (__version__) itself."""
    out = {}
    for path, changed in lines.items():
        if (not path.endswith(".py") or path.startswith("tests/") or "/tests/" in path
                or not os.path.isfile(os.path.join(project_root, path))):
            continue
        try:
            source = _read_source(project_root, path)
            defs = _defs(source)
            funcs = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        except (SyntaxError, ValueError):
            continue
        text = _lines(source.decode("utf-8-sig", "replace"))
        changed = {n for n in changed if n <= len(text) and text[n - 1].strip()
                   and not text[n - 1].strip().startswith("#")}     # (a blank line between two methods is no change)
        touched = _touched(defs, changed)
        names = {p[-1] for p in touched if not (p[-1].startswith("__") and p[-1] in funcs)}
        names |= {p[0] for p in touched if len(p) == 2 and p[1].startswith("__")}
        if names:
            out[path] = names
    return out


def _rare(name, counts, limit):
    """A name few files use (`counts`: {name: how many files hold it}), so naming it is naming the definition."""
    return name not in COMMON and len(name) >= 4 and counts.get(name, 0) <= limit


def _counts(idents):
    """{name: how many of the files (their identifier sets) hold it}."""
    out = {}
    for names in idents:
        for n in names:
            out[n] = out.get(n, 0) + 1
    return out


GENERIC_DIRS = {"app", "qt", "tests", "docs", "assets", "modules", "templates", "scripts", "packaging", "data",
                "Test Resources", "ja", "zh", "services", "connect", "cli", "pages", "static", "images"}


def _test_files(project_root):
    """Every test file of every suite (the stress set's left out), as paths from the top."""
    tests = [p for p in _core_files(project_root) if not p.startswith(f"tests/{STRESS_DIR}/")]
    for path in sorted(glob.glob(os.path.join(project_root, "modules", "*", "tests", "**", "test_*.py"), recursive=True)):
        tests.append(os.path.relpath(path, project_root).replace(os.sep, "/"))
    return tests


def _removed_app_names(project_root, base):
    """{module path: the definitions the branch removed from it} for the app's code: a function, method, class or
    constant BASE's merge-base had and the working tree hasn't — a whole module gone too (its tests still import it)."""
    rev = _git_out(project_root, "merge-base", base, "HEAD").strip() or base
    out = {}
    for path in _git_out(project_root, "-c", "core.quotepath=false", "diff", "--name-only", "--no-renames", rev,
                         "--").splitlines():
        path = path.strip()
        if not path.endswith(".py") or path.startswith("tests/") or "/tests/" in path:
            continue
        before = _git_out(project_root, "show", f"{rev}:{path}")
        try:
            had = {p[-1] for p, _s, _e, _u in _defs(before)} if before else set()
            now = os.path.join(project_root, path)
            has = {p[-1] for p, _s, _e, _u in _defs(_read_source(project_root, path))} if os.path.isfile(now) else set()
        except (OSError, SyntaxError, ValueError):
            continue
        gone = {n for n in had - has if not n.startswith("__")}
        if gone:
            out[path] = gone
    return out


def _file_pattern(path):
    """How code names a file: its whole name, or its folder's path ("docs", "releases" — never GitHub's /releases/,
    nor the word)."""
    folders = path.split("/")[:-1]
    parts = [re.escape(path.rsplit("/", 1)[-1])]
    if folders and len(folders[-1]) >= 6 and folders[-1] not in GENERIC_DIRS:
        tail = [re.escape(f) for f in folders[-2:]]
        parts.append(r"[\"'/\\]" + r"[\"'/\\,\s]{1,6}".join(tail) + r"[\"'/\\]")
    return re.compile("|".join(parts))


def _strings(node):
    """A definition's (or a module's) string constants, quoted, in order — never a comment or a docstring: how its
    code names a file ("docs", "releases", "RELEASE_v3.0.17.md")."""
    docs = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant):
            docs.add(id(n.body[0].value))
    return " ".join(f'"{n.value}"' for n in ast.walk(node)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs)


def _namers(project_root, path):
    """{source: its definitions that name the file at `path`} over the app's code and the tests' helper modules (one
    by one, never a whole class)."""
    pattern, out = _file_pattern(path), {}
    for top in ("app", "modules", "tests"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(project_root, top)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")
                           and not (top == "modules" and d == "tests")]
            for n in filenames:
                if not n.endswith(".py") or n.startswith("test_"):
                    continue
                source = os.path.relpath(os.path.join(dirpath, n), project_root).replace(os.sep, "/")
                try:
                    text = _text(project_root, source)
                    if not pattern.search(text):
                        continue
                    tree = ast.parse(text)
                except (OSError, SyntaxError, ValueError):
                    continue
                names = set()
                for node in tree.body:                        # (a method one by one, never its whole class)
                    for d in (node.body if isinstance(node, ast.ClassDef) else [node]):
                        name = getattr(d, "name", None) or next((t.id for t in getattr(d, "targets", [])
                                                                 if isinstance(t, ast.Name)), None)
                        if name and pattern.search(_strings(d)):
                            names.add(name)
                if names:
                    out[source] = names
    return out


def _touched_callers(project_root, base):
    """-> (the test files and guards picked, in path order; {pick: why}; notes)."""
    lines = _changed_lines(project_root, base)
    why, notes = {}, []
    for path in _changed_test_files(project_root, base):
        why[path] = "changed on the branch"
    changed = _changed_app_names(project_root, lines)
    for module, names in _removed_app_names(project_root, base).items():   # a caller left behind goes red: picked
        changed.setdefault(module, set()).update(names)
    texts = {}
    for path in _test_files(project_root):
        try:
            texts[path] = _text(project_root, path)
        except OSError:
            continue
    idents = {p: _idents(t) for p, t in texts.items()}
    counts = _counts(idents.values())
    folder_users, quoted = {}, {}

    def strings(test_path):                                   # a test file's string constants (once each)
        if test_path not in quoted:
            try:
                quoted[test_path] = _strings(ast.parse(texts[test_path]))
            except (SyntaxError, ValueError):
                quoted[test_path] = texts[test_path]
        return quoted[test_path]
    others = sorted(c for c in lines if not _is_test_file(c) and os.path.isfile(os.path.join(project_root, c))
                    and not (c.endswith(".py") and (c.startswith("tests/") or "/tests/" in c))   # (a .py read as text
                    and not c.rsplit("/", 1)[-1].startswith("__"))    # too; never by a name every package has)
    helpers = sorted(c for c in lines if c.endswith(".py") and (c.startswith("tests/") or "/tests/" in c)
                     and not _is_test_file(c) and os.path.isfile(os.path.join(project_root, c)))
    for other in (o for o in others if not o.endswith(".py")):   # a definition that names a changed data file has
        for source, names in _namers(project_root, other).items():   # changed: BASE_HASHES (plan_file_base_hashes.json)
            changed.setdefault(source, set()).update(names)
    for path, text in texts.items():
        if path in why:
            continue
        for module, names in sorted(changed.items()):
            hit = sorted(n for n in names if n in idents[path])
            if hit and not _imports(text, module):
                hit = [n for n in hit if _rare(n, counts, RARE_TESTS)]
            if hit:
                why[path] = f"names {', '.join(hit[:3])}{' …' if len(hit) > 3 else ''} ({module}, changed)"
                break
        if path in why:
            continue
        for helper in helpers:                                # a test helper or conftest the branch changed
            folder = helper.rsplit("/", 1)[0] + "/"
            if (helper.endswith("/conftest.py") and path.startswith(folder)) or _imports(text, helper):
                why[path] = f"uses {helper} (changed)"
                break
        if path in why:
            continue
        for other in others:                                  # a changed data file, template, stylesheet, notes file
            if other not in folder_users:                     # (Surasura.spec, never "Surasura"; "releases" as
                pattern = _file_pattern(other)                # a path part, never the word; in the code's strings,
                folder_users[other] = {p for p in texts if pattern.search(strings(p))}   # never a comment)
            users = folder_users[other]
            if path in users and (other.rsplit("/", 1)[-1] in strings(path) or len(users) <= RARE_TESTS):
                why[path] = f"names {other.rsplit('/', 1)[-1]} or its folder ({other}, changed)"
                break
    for node, folders in GUARDS.items():
        f = node.split("::", 1)[0]
        if node in why or f in why or not os.path.isfile(os.path.join(project_root, f)):
            continue
        hit = sorted(c for c in lines if any(c.startswith(d) for d in folders))
        if hit:
            why[node] = f"the area's guard ({', '.join(folders)}: {hit[0]}{' …' if len(hit) > 1 else ''})"
    if not lines:
        notes.append(f"nothing changed since {base}")
    return sorted(why), why, notes


def run_touched_callers(project_root, base="origin/3.0-dev", listing=False):
    """`--touched-callers [BASE]`: the test files that reach what the branch changed (see above), under the read
    audit. 0 when every one passed (nothing picked passes, and says so)."""
    picked, why, notes = _touched_callers(project_root, base)
    for note in notes:
        print(f"  ({note})")
    print(f"{len(picked)} test file(s) reach what changed since {base} (the read audit on):", flush=True)
    for p in picked:
        print(f"  {p}  <- {why[p]}")
    if listing or not picked:
        return 0
    started = time.perf_counter()
    groups = _by_suite(picked)
    core = groups.pop("tests", [])
    jobs = {}
    if core:
        count = max(1, min(4, len(core) // 6, _shard_count(_free_memory_mb(), os.cpu_count())))
        parts = _shards(project_root, core, count) if count > 1 else [core]
        for i, part in enumerate(parts, 1):
            jobs[f"tests [{i}/{len(parts)}]" if len(parts) > 1 else "tests"] = part
    jobs.update(groups)
    failed, outputs = [], {}
    env = _audit_env()

    def one(label, nodes):
        result = _run([sys.executable, "-m", "pytest", *nodes, "-q", "-ra", "-p", "no:cacheprovider",
                                 "-p", "tests.read_audit"], cwd=project_root, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return label, (0 if result.returncode == 5 else result.returncode), _decode(result.stdout)
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        for future in as_completed([pool.submit(one, k, v) for k, v in jobs.items()]):
            label, code, output = future.result()
            outputs[label] = output
            print(f"  {'PASS' if code == 0 else 'FAIL'}  {label:<34} {_last_line(output)}", flush=True)
            if code != 0:
                failed.append(label)
    for label in failed:
        print("\n" + "=" * 60 + f"\n   FAILED: {label}\n" + "=" * 60 + "\n" + outputs[label])
    print(f"\n  [{'FAIL' if failed else 'PASS'}]  {len(picked)} touched file(s), {time.perf_counter() - started:.1f}s")
    return 1 if failed else 0


FLAGS = ("--all", "--shard", "--stress", "--stress-changed", "--guards", "--touched-callers", "--list", "--save-times",
         "--local-only", "--help", "-h")                                                       # main's (a value follows some)


def _value_after(args, flag):
    """The value given after `flag` (`--flag V` or `--flag=V`), or None."""
    for i, a in enumerate(args):
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
        if a == flag and i + 1 < len(args) and not args[i + 1].startswith("--"):
            return args[i + 1]
    return None


def main():
    """
    Run the comprehensive test suite for Surasura.

    `python run_tests.py`        runs the core suite (tests/), as it always has.
    `python run_tests.py --all`  runs the core suite AND every module suite at the same time.
    `python run_tests.py --shard I/N`  runs shard I of the core suite split N ways (GitHub's PR tests).
    `python run_tests.py --stress [N]`  runs the stress set (tests/stress/) N times (1).
    `python run_tests.py --stress-changed [BASE]`  runs every test changed since BASE (origin/3.0-dev) under load (a
        lane's check before READY), by test function: 20 times each one that waits on time or threads, once the rest.
    `python run_tests.py --guards`  runs every whole-repo guard test (GUARDS), under the read audit: before every push.
    `python run_tests.py --touched-callers [BASE]`  a lane's touched run: the test files that reach what the branch
        changed since BASE (origin/3.0-dev) and the area's guards, under the read audit (no test reads an ignored file).
    `python run_tests.py --local-only`  what GitHub's pull request run can't run, and nothing it can: the core test
        files the public repo doesn't track, the private module suites, the tracked core files that name a private
        folder (a train's local gate beside its pull request's GitHub run). Prints the set's size first.
    `--list` with any of the four: prints what it would run, and runs nothing.
    `python run_tests.py --save-times`  writes tests/test_times.json (the times GitHub's shards pack by) from this
        copy's last --all: a train's, after its green --all. Runs no test.
    `python run_tests.py --help`  prints this and runs nothing; so does a flag it doesn't know (exit 2).
    """
    # 0. --help, or a flag it doesn't know: the usage, nothing run (either used to start the whole core suite — outside
    #    with-lock.sh and its throwaway data folders: Flake-F3, 2026-11-15)
    args = sys.argv[1:]
    helping = "--help" in args or "-h" in args
    unknown = [a for a in args if a.startswith("-") and a.split("=", 1)[0] not in FLAGS]
    if helping or unknown:
        if not helping:
            print(f"run_tests.py: no such option {unknown[0]!r}: nothing was run.\n")
        print(textwrap.dedent("    " + main.__doc__.strip()))
        sys.exit(0 if helping else 2)
    # 1. Setup environment
    project_root = os.path.dirname(os.path.abspath(__file__))
    listing = "--list" in args
    if listing and not any(a.split("=", 1)[0] in ("--stress-changed", "--touched-callers", "--guards", "--local-only")
                           for a in args):
        print("run_tests.py: --list goes with --touched-callers, --stress-changed, --guards or --local-only: nothing was "
              "run.\n")
        print(textwrap.dedent("    " + main.__doc__.strip()))
        sys.exit(2)                    # (alone, or with --all / --shard, it started the whole core run: train 53's keeper)
    for flag, run in (("--stress-changed", lambda v: run_stress_changed(project_root, v or "origin/3.0-dev",
                                                                         listing=listing)),
                      ("--touched-callers", lambda v: run_touched_callers(project_root, v or "origin/3.0-dev",
                                                                          listing=listing)),
                      ("--guards", lambda v: run_guards(project_root, listing=listing)),
                      ("--local-only", lambda v: run_local_only(project_root, listing=listing)),
                      ("--stress", lambda v: run_stress(project_root, int(v) if v and v.isdigit() else 1))):
        if flag in args or any(a.startswith(flag + "=") for a in args):
            try:
                sys.exit(run(_value_after(args, flag)))
            except KeyboardInterrupt:
                print("\nTest run cancelled via KeyboardInterrupt.")
                sys.exit(130)
    if "--save-times" in args:
        sys.exit(save_times(project_root))
    if "--all" in sys.argv[1:]:
        try:
            sys.exit(run_all(project_root))
        except KeyboardInterrupt:
            print("\nTest run cancelled via KeyboardInterrupt.")
            sys.exit(130)
    args = sys.argv[1:]
    joined = [a.split("=", 1)[1] for a in args if a.startswith("--shard=")]
    if "--shard" in args or joined:
        at = args.index("--shard") if "--shard" in args else None
        spec = joined[0] if joined else (args[at + 1] if at + 1 < len(args) else "")
        try:
            sys.exit(run_shard(project_root, spec))
        except KeyboardInterrupt:
            print("\nTest run cancelled via KeyboardInterrupt.")
            sys.exit(130)
    test_dir = os.path.join(project_root, "tests")
    
    print("\n" + "="*60)
    print("   SURASURA TEST SUITE RUNNER")
    print("="*60 + "\n")
    
    # 2. Command Construction: Use pytest
    # -v: Verbose output
    # -ra: Show extra test summary info
    cmd = [sys.executable, "-m", "pytest", test_dir, "-v", "-ra"]
    
    try:
        # 3. Execution
        result = _run(cmd, env=os.environ.copy())
        
        # 4. Result Handling
        print("\n" + "-"*60)
        if result.returncode == 0:
            print("  [PASS]  ALL TESTS PASSED")
        else:
            print("  [FAIL]  TESTS FAILED")
        print("-" * 60)
        
        sys.exit(result.returncode)
        
    except FileNotFoundError:
        print("Error: Pytest not found. Please install dependencies: pip install requirements.txt")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nTest run cancelled via KeyboardInterrupt.")
        sys.exit(130)

if __name__ == "__main__":
    main()
