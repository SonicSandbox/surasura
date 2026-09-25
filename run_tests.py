
import sys
import subprocess
import os
import glob
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
    """Run every suite at once, each in its own process. Returns 0 only if every suite passed."""
    # A suite's output can hold characters this console can't print; escape them, don't crash.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    suites = _suites(project_root)

    print("\n" + "="*60)
    print("   SURASURA TEST SUITE RUNNER  (--all: every suite at once)")
    print("="*60 + "\n")
    print(f"Running {len(suites)} suites in parallel: {', '.join(suites)}\n", flush=True)

    started = time.perf_counter()
    results = {}
    with ThreadPoolExecutor(max_workers=len(suites)) as pool:
        futures = [pool.submit(_run_suite, project_root, suite) for suite in suites]
        for future in as_completed(futures):
            suite, code, output, secs = future.result()
            results[suite] = (code, output, secs)
            verdict = "PASS" if code == 0 else "FAIL"
            print(f"  {verdict}  {suite:<34} {secs:5.1f}s  {_last_line(output)}", flush=True)
    wall = time.perf_counter() - started

    failed = [suite for suite in suites if results[suite][0] != 0]
    for suite in failed:
        print("\n" + "="*60)
        print(f"   FAILED: {suite} (exit code {results[suite][0]})")
        print("="*60)
        print(results[suite][1])

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
