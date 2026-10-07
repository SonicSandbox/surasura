
import sys
import subprocess
import os
import glob
import shutil
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
# share a core) — so a quiet machine gets more, one already running other test runs fewer. SURASURA_TEST_SHARDS=N chooses N (1: unsplit). Measurements: tracks/ship/notes/ in the
# 3.0 planning folder (parallel-tests.md, Job 3).

SHARD_MAX = 8
CORE_PEAK_MB = 4800
SHARD_MB = 500
RESERVE_MB = 3000
TIMES = os.path.join("debug", "test_times.json")


def _core_files(project_root):
    """Every core test file (pytest's default pattern), as paths from the project root, in order."""
    files = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(project_root, "tests")):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith("."))
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
    return label, result.returncode, _decode(result.stdout), time.perf_counter() - started


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
    count = min(_shard_count(_free_memory_mb(), cpus, _idle_cpus(cpus)), len(files)) if len(files) > 1 else 1
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
    shutil.rmtree(times_dir, ignore_errors=True)

    failed_jobs = [label for label, _ in jobs if results[label][0] != 0]
    for label in failed_jobs:
        print("\n" + "="*60)
        print(f"   FAILED: {label} (exit code {results[label][0]})")
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


def main():
    """
    Run the comprehensive test suite for Surasura.

    `python run_tests.py`        runs the core suite (tests/), as it always has.
    `python run_tests.py --all`  runs the core suite AND every module suite at the same time.
    """
    # 1. Setup environment
    project_root = os.path.dirname(os.path.abspath(__file__))
    if "--all" in sys.argv[1:]:
        try:
            sys.exit(run_all(project_root))
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
