
import ast
import sys
import subprocess
import os
import glob
import shutil
import threading
import time
import locale
from concurrent.futures import ThreadPoolExecutor, as_completed


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
# shard's files are packed by their last recorded times (debug/test_times.json, written by the shards' own conftest
# hook, SURASURA_TEST_TIMES), the file's size until there is one. How many shards: as many as fit in the memory free
# now (one unsplit core process peaked at ~4.8 GB; each further shard adds ~0.5 GB; RESERVE_MB is left for the module
# suites and the machine), at most SHARD_MAX and half the CPUs idle over half a second as it starts (two logical CPUs
# share a core) — so a quiet machine gets more, one already running other test runs fewer. SURASURA_TEST_SHARDS=N
# chooses N (1: unsplit).

SHARD_MAX = 8
CORE_PEAK_MB = 4800
SHARD_MB = 500
RESERVE_MB = 3000
TIMES = os.path.join("debug", "test_times.json")


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
    import json
    try:
        with open(os.path.join(project_root, TIMES), encoding="utf-8") as f:
            times = json.load(f)
        return {k: float(v) for k, v in times.items()} if isinstance(times, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


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


def _run_shard(project_root, label, files, times_path):
    """Run one core shard (its files, in one pytest process) to the end. Returns (label, exit code, output, seconds)."""
    started = time.perf_counter()
    env = os.environ.copy()
    env["SURASURA_TEST_TIMES"] = times_path
    result = subprocess.run(
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
    result = subprocess.run([sys.executable, "-m", "pytest", *files, "-v", "-ra"],
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
    result = subprocess.run(
        [sys.executable, "-m", "pytest", suite, "-ra", "-p", "no:cacheprovider"],
        cwd=project_root, env=os.environ.copy(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return suite, result.returncode, _decode(result.stdout), time.perf_counter() - started


def _last_line(output):
    """pytest's closing summary ("1227 passed, 2 skipped in 65.9s") without its ===== rule."""
    lines = [line.strip(" =") for line in output.splitlines() if line.strip(" =")]
    return lines[-1] if lines else "(no output)"


def run_all(project_root):
    """Run every suite at once, each in its own process (the core suite in shards). Returns 0 only if every suite
    passed."""
    # A suite's output can hold characters this console can't print; escape them, don't crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    suites = _suites(project_root)
    files = _core_files(project_root)
    cpus = os.cpu_count()
    chosen = os.environ.get("SURASURA_TEST_SHARDS", "").strip().isdigit()
    idle = None if chosen or len(files) < 2 else _idle_cpus(cpus)        # half a second, spent only when it counts
    count = min(_shard_count(_free_memory_mb(), cpus, idle), len(files)) if len(files) > 1 else 1
    shards = _shards(project_root, files, count) if count > 1 else []
    jobs = [(f"tests [{i}/{len(shards)}]", shard) for i, shard in enumerate(shards, 1)] or [("tests", None)]
    jobs += [(suite, None) for suite in suites[1:]]

    print("\n" + "="*60)
    print("   SURASURA TEST SUITE RUNNER  (--all: every suite at once)")
    print("="*60 + "\n")
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
        out = subprocess.run(["git", *args], cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        names.update(line.strip() for line in _decode(out.stdout).splitlines() if line.strip())
    return sorted(n for n in names if _is_test_file(n) and os.path.isfile(os.path.join(project_root, n)))


def _is_test_file(path):
    """A test file: test_*.py under tests/ or modules/*/tests/ (a path from the project root, with /)."""
    return (os.path.basename(path).startswith("test_") and path.endswith(".py")
            and (path.startswith("tests/") or (path.startswith("modules/") and "/tests/" in path)))


def _git_out(project_root, *args):
    out = subprocess.run(["git", *args], cwd=project_root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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
            result = subprocess.run([sys.executable, "-m", "pytest", *args, "-q", "-ra", "-p", "no:cacheprovider"],
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


def run_stress_changed(project_root, base="origin/3.0-dev", times=STRESS_TIMES):
    """`--stress-changed [BASE]`: every test changed since BASE, `times` times, beside two core shards. 0 when every
    run passed (a branch that changed no test passes at once, and says so)."""
    ids, notes = _changed_tests(project_root, base)
    for note in notes:
        print(f"  ({note})")
    if not ids:
        print(f"No test changed since {base}: nothing to repeat")
        return 0
    groups, size = {}, {}
    for node in ids:                                        # each suite's tests, split where a command would be long
        suite = _suite_of(node.split("::", 1)[0])
        part = size.get(suite, (1, 0))
        if part[1] + len(node) > ARGS_MAX:
            part = (part[0] + 1, 0)
        size[suite] = (part[0], part[1] + len(node) + 1)
        label = suite if part[0] == 1 else f"{suite} (part {part[0]})"
        groups.setdefault(label, []).append(node)
    files = len({node.split("::", 1)[0] for node in ids})
    print(f"{len(ids)} changed test(s) in {files} file(s) since {base}, {times} times each, beside core shards "
          f"{' and '.join(LOAD_SHARDS)}:", flush=True)
    for node in ids:
        print(f"  {node}")
    def start(spec):
        return subprocess.Popen([sys.executable, os.path.abspath(__file__), "--shard", spec], cwd=project_root,
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
        red = _repeat(project_root, sorted(groups.items()), times, os.environ.copy())
    finally:
        stop.set()
        keeper.join(60)
        for proc in loads.values():
            _end_tree(proc)
    if red:
        print(f"\n  [FAIL]  {red[0]}, run {red[1]} of {times}: {red[2]}")
        return 1
    print(f"\n  [PASS]  every changed test file passed {times} times under load")
    return 0


def _end_tree(proc):
    """End a load shard and every process it started (pytest's own children too)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    else:
        proc.kill()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        pass


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
    `python run_tests.py --stress-changed [BASE]`  runs every test changed since BASE (origin/3.0-dev) 20 times
        under load (a lane's check before READY): by test function, not whole files.
    """
    # 1. Setup environment
    project_root = os.path.dirname(os.path.abspath(__file__))
    args = sys.argv[1:]
    for flag, run in (("--stress-changed", lambda v: run_stress_changed(project_root, v or "origin/3.0-dev")),
                      ("--stress", lambda v: run_stress(project_root, int(v) if v and v.isdigit() else 1))):
        if flag in args or any(a.startswith(flag + "=") for a in args):
            try:
                sys.exit(run(_value_after(args, flag)))
            except KeyboardInterrupt:
                print("\nTest run cancelled via KeyboardInterrupt.")
                sys.exit(130)
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
        result = subprocess.run(cmd, env=os.environ.copy())
        
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
