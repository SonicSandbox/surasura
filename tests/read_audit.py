"""Which files of the repo a test reads (run_tests.py --guards; Minato-TS, 2026-11-21).

Loaded only by `-p tests.read_audit` (run_tests.py --guards sets it), never by conftest: a normal run never pays for it.
An audit hook sees every file opened for reading while a test runs (setup, call, teardown) or its file is collected;
importing code doesn't count (a data file opened during an import does). It sees this process only: a child process's
reads, and SQLite's own opens, are not seen (known limits, 2026-11-21 review).

    SURASURA_READ_AUDIT=ignored          the run fails, naming each test and file, when a test read a file of the repo
                                         that the public repo ignores (git check-ignore): GitHub's runner has no such
                                         file. 2026-11-20: a test leaned on this PC's lists/jmnedict.zip and went red
                                         on GitHub only.
    SURASURA_READ_AUDIT=survey:<folder>  writes <folder>/<pid>.json: {node id: {"reads": [paths from the repo's top
                                         folder], "s": seconds}} — how run_tests.py's GUARDS were found (the tests
                                         that read the app's own source as text: whole-repo and window-wide guards).
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WRITE = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
_SKIP = (os.sep + ".git" + os.sep, os.sep + "__pycache__" + os.sep, os.sep + ".pytest_cache" + os.sep)
_STATE = {"mode": None, "out": None, "test": None, "reads": {}, "written": set(), "secs": {}, "t0": 0.0}
CODE = (".py", ".pyc", ".pyd")


def _mode():
    value = os.environ.get("SURASURA_READ_AUDIT", "").strip()
    if value == "ignored":
        return "ignored", None
    if value.startswith("survey:") and value[7:]:
        return "survey", value[7:]
    return None, None


def _importing():
    """True when the open comes from an import (importlib's frames are on the stack). Asked only for code: a data file a
    module opens as it is imported is a read like any other."""
    frame = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_filename.startswith("<frozen importlib"):
            return True
        frame = frame.f_back
    return False


def _hook(event, args):
    if event != "open" or _STATE["test"] is None:
        return
    path, mode, flags = (tuple(args) + (None, None, None))[:3]
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if not isinstance(path, str) or not path:
        return                                              # (a file descriptor: opened before, seen then)
    real = os.path.abspath(path)
    full = os.path.normcase(real)                           # (compared case-blind, as Windows does; named as written)
    if not full.startswith(ROOT + os.sep) or any(s in full for s in _SKIP):
        return
    rel = real[len(ROOT) + 1:].replace(os.sep, "/")
    if (isinstance(flags, int) and flags & _WRITE) or (isinstance(mode, str) and any(c in mode for c in "wax+")):
        _STATE["written"].add(rel)                          # written, not read (and read back later: its own file)
        return
    if full.endswith(CODE) and _importing():
        return
    _STATE["reads"].setdefault(_STATE["test"], set()).add(rel)


def pytest_configure(config):
    _STATE["mode"], _STATE["out"] = _mode()
    if _STATE["mode"]:
        sys.addaudithook(_hook)                             # (can't be removed: it goes quiet once the session ends)


def pytest_collectstart(collector):
    """A test file's own top-level reads (as it is imported to be collected) count as the file's."""
    if getattr(collector, "path", None) is not None and str(collector.path).endswith(".py"):
        _STATE["test"] = collector.nodeid


def pytest_collectreport(report):
    _STATE["test"] = None


def pytest_runtest_logstart(nodeid, location):
    _STATE["test"], _STATE["t0"] = nodeid, time.perf_counter()


def pytest_runtest_logfinish(nodeid, location):
    _STATE["secs"][nodeid] = time.perf_counter() - _STATE["t0"]
    _STATE["test"] = None


def _git(*args, stdin=None):
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=ROOT, input=stdin,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode("utf-8", "replace") if out.returncode in (0, 1) else None


# What a test may read although the public repo ignores it, because it reads it only when it is there (the survey of
# 2026-11-21 found these, each tolerated on GitHub's runner): code is never this guard's (a whole-repo scan reads the
# private modules' sources where they are checked out), nor these. A new entry says why the test passes without it.
TOLERATED = (
    ("docs/agent instructions/", "the leak checks read the private docs' never-public list when it is there"),
    ("debug/test_times.json", "the shard packer reads the recorded times, else the files' sizes"),
    ("tests/parsing/", "the local-only parsing suite: its readers skip without it"),
)


def _tolerated(path):
    p = path.replace("\\", "/").lower()
    return p.endswith(CODE) or any(p.startswith(prefix.lower()) for prefix, _why in TOLERATED)


def ignored_reads(reads, written=()):
    """{node id: [the files it read that the public repo ignores]} for `reads` ({node id: {paths}}), leaving out code,
    TOLERATED and the files the run wrote itself (`written`); None when git can't say (no repo: no verdict, a red)."""
    tracked = _git("ls-files", "-z")
    if tracked is None:
        return None
    tracked = {os.path.normcase(p.replace("/", os.sep)) for p in tracked.split("\0") if p}
    mine = {os.path.normcase(p.replace("/", os.sep)) for p in written}
    untracked = sorted({p for paths in reads.values() for p in paths
                        if os.path.normcase(p.replace("/", os.sep)) not in tracked | mine and not _tolerated(p)})
    if not untracked:
        return {}
    answer = _git("check-ignore", "--no-index", "--stdin", "-z",
                  stdin="\0".join(untracked).encode("utf-8", "surrogateescape"))
    if answer is None:
        return None
    ignored = {p for p in answer.split("\0") if p}
    out = {}
    for node, paths in reads.items():
        hit = sorted(p for p in paths if p in ignored)
        if hit:
            out[node] = hit
    return out


def pytest_sessionfinish(session, exitstatus):
    mode = _STATE["mode"]
    _STATE["test"] = None
    if mode == "survey":
        try:
            os.makedirs(_STATE["out"], exist_ok=True)
            with open(os.path.join(_STATE["out"], f"{os.getpid()}.json"), "w", encoding="utf-8") as f:
                json.dump({n: {"reads": sorted(_STATE["reads"].get(n, ())), "s": round(s, 3)}
                           for n, s in _STATE["secs"].items()}, f)
        except OSError as e:
            sys.__stderr__.write(f"read_audit: survey not written: {e}\n")
    elif mode == "ignored":
        found = ignored_reads(_STATE["reads"], _STATE["written"])
        _STATE["found"] = found
        if found or found is None:
            session.exitstatus = 1


def pytest_terminal_summary(terminalreporter):
    if _STATE["mode"] != "ignored":
        return
    found = _STATE.get("found")
    if found is None:
        terminalreporter.write_line("READ AUDIT FAILED: git couldn't list the repo's files: ignored reads NOT checked",
                                    red=True)
        return
    if not found:
        terminalreporter.write_line(f"READ AUDIT: no test read a git-ignored file ({len(_STATE['secs'])} tests)")
        return
    terminalreporter.write_line("READ AUDIT FAILED: these tests read files the public repo ignores (GitHub's runner "
                                "has none of them; make the test build its own, e.g. in tmp_path):", red=True)
    for node, paths in sorted(found.items()):
        terminalreporter.write_line(f"  {node}", red=True)
        for p in paths:
            terminalreporter.write_line(f"      {p}", red=True)
