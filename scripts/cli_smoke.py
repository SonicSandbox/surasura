"""Smoke run of surasura-cli (P0.3 RUNBOOK P1.1 row 1.1.7; S3.1 runs it on every release build).

    python scripts/cli_smoke.py dist\\Surasura     the frozen surasura-cli.exe in a built distribution
    python scripts/cli_smoke.py --source          `python -m app.cli` from this checkout (the test suite runs this)

Runs the command line from a temporary working folder outside the checkout, with a temporary test root, started the
way callers start it (CREATE_NO_WINDOW on Windows), and checks the contract: --version exit 0 with its JSON line;
an unknown command exit 2; `_selftest raise` exit 1 with its JSON line, a traceback in the log and an events line;
`_selftest ok --echo あ` hands back "あ" escaped; the log lands in the test root's local data, nothing in the working
folder or the real local data folder. Prints SMOKE OK (exit 0) or SMOKE FAILED with the reasons (exit 1).
"""
import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

CLI_EXE_NAME = "surasura-cli.exe"


def _subsystem(exe):
    """The PE header's subsystem: 2 a windowed program, 3 a console program."""
    with open(exe, "rb") as f:
        f.seek(0x3C)
        pe = struct.unpack("<I", f.read(4))[0]
        f.seek(pe + 4 + 20 + 68)
        return struct.unpack("<H", f.read(2))[0]


def _folder_files(folder):
    found = []
    for dirpath, _dirs, names in os.walk(folder):
        found += [os.path.relpath(os.path.join(dirpath, n), folder) for n in names]
    return sorted(found)


def smoke(command, install_dir, frozen):
    """Run every check; returns the list of failures (empty when the smoke passes)."""
    from app import path_utils
    failures = []

    def check(ok, what):
        print(f"  {'ok  ' if ok else 'FAIL'} {what}", flush=True)
        if not ok:
            failures.append(what)

    work = tempfile.mkdtemp(prefix="cli_smoke_work_")
    root = tempfile.mkdtemp(prefix="cli_smoke_root_テスト_")
    real_local = os.path.join(path_utils._local_data_root(), path_utils._install_key(install_dir))
    real_before = _folder_files(real_local) if os.path.isdir(real_local) else None
    environment = dict(os.environ, SURASURA_TEST_ROOT=root)
    environment.pop("PYTEST_CURRENT_TEST", None)
    if not frozen:
        environment["PYTHONPATH"] = PROJECT_ROOT
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    def call(*args):
        proc = subprocess.run(command + list(args), cwd=work, env=environment, creationflags=flags,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        try:
            lines = [json.loads(line) for line in proc.stdout.decode("ascii").splitlines()]
        except (UnicodeDecodeError, ValueError):
            lines = None
        return proc.returncode, lines, proc.stdout, proc.stderr

    try:
        if frozen:
            exe = command[0]
            check(_subsystem(exe) == 3, f"{CLI_EXE_NAME} is a console program")
            check(_subsystem(os.path.join(install_dir, "Surasura.exe")) == 2, "Surasura.exe keeps its window")
            check(os.path.isdir(os.path.join(install_dir, "_internal")) and
                  not os.path.exists(os.path.join(install_dir, "surasura-cli", "_internal")), "one _internal shared")
            print(f"  size: {CLI_EXE_NAME} {os.path.getsize(exe) / (1024 * 1024):.1f} MB, Surasura.exe "
                  f"{os.path.getsize(os.path.join(install_dir, 'Surasura.exe')) / (1024 * 1024):.1f} MB", flush=True)

        code, lines, raw, err = call("--version")
        check(code == 0 and lines is not None and len(lines) == 1 and lines[0].get("type") == "result"
              and raw.endswith(b"}\n") and b"\r" not in raw
              and lines[0].get("contract") == 1 and {"app", "engine", "schema", "store"} <= set(lines[0]),
              f"--version: exit 0, one result line ending in \\n ({raw[:120]!r}, exit {code}, stderr {err[:200]!r})")

        code, lines, raw, _err = call("nope")
        check(code == 2 and lines is not None and len(lines) == 1 and lines[0].get("code") == "usage",
              f"nope: exit 2, a usage error line ({raw[:120]!r}, exit {code})")

        code, lines, raw, _err = call("_selftest", "raise")
        check(code == 1 and lines is not None and len(lines) == 1 and lines[0].get("code") == "failed",
              f"_selftest raise: exit 1, one error line ({raw[:120]!r}, exit {code})")
        logs = os.path.join(root, "local", "logs")
        try:
            with open(os.path.join(logs, "cli.log"), encoding="utf-8") as f:
                log = f.read()
        except OSError:
            log = ""
        check("Traceback (most recent call last)" in log, "the traceback is in the test root's cli.log")
        try:
            with open(os.path.join(logs, "cli-events.jsonl"), encoding="utf-8") as f:
                events = [json.loads(line) for line in f.read().splitlines()]
        except (OSError, ValueError):
            events = []
        check([e.get("code") for e in events] == ["usage", "failed"], "an events line for each error (nope, raise)")

        code, lines, raw, _err = call("_selftest", "ok", "--echo", "あ", "--progress")
        check(code == 0 and lines is not None and [line.get("type") for line in lines] == ["progress", "result"]
              and lines[-1].get("echo") == "あ" and b"\\u3042" in raw,
              f'_selftest ok --echo あ: exit 0, "あ" handed back escaped ({raw[:160]!r}, exit {code})')

        check(os.listdir(work) == [], "nothing written in the working folder")
        real_after = _folder_files(real_local) if os.path.isdir(real_local) else None
        check(real_after == real_before, f"the real local data folder untouched ({real_local})")
    finally:
        for folder in (work, root):
            shutil.rmtree(folder, ignore_errors=True)
        check(not os.path.exists(work) and not os.path.exists(root), "the temporary folders removed")
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("dist", nargs="?", help="the built distribution folder (holding surasura-cli.exe)")
    parser.add_argument("--source", action="store_true", help="run `python -m app.cli` from this checkout instead")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")      # a console that can't print あ still gets the report
    if args.source:
        command, install_dir, frozen = [sys.executable, "-m", "app.cli"], PROJECT_ROOT, False
    elif args.dist:
        install_dir = os.path.abspath(args.dist)
        command, frozen = [os.path.join(install_dir, CLI_EXE_NAME)], True
        if not os.path.isfile(command[0]):
            print(f"SMOKE FAILED: {command[0]} not found")
            return 1
    else:
        parser.error("name the distribution folder, or --source")
    print(f"surasura-cli smoke: {' '.join(command)}", flush=True)
    failures = smoke(command, install_dir, frozen)
    if failures:
        print(f"SMOKE FAILED: {len(failures)} check(s): " + "; ".join(failures))
        return 1
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
