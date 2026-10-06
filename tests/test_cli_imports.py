"""The command line stays light (P0.3 02-contract §4–§5, P1.1 row 1.1.3): its quick calls load no GUI toolkit, no
pandas, no network library, no dashboard, and nothing that can open a dialog.

Each case runs in a fresh `python -c` process, so nothing a test already imported can hide an import.
"""
import glob
import json
import os
import subprocess
import sys
import textwrap

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FORBIDDEN = ("tkinter", "_tkinter", "tkinter.messagebox", "PyQt6", "pandas", "numpy", "requests",
             "app.main", "app.telemetry", "app.static_html_generator", "app.content_importer_gui",
             "fugashi", "jieba")


def _loaded_by(argv, root):
    """The forbidden modules a process has loaded after one call of `argv`, and that call's exit code."""
    script = textwrap.dedent(f"""
        import json, sys
        from app.cli import __main__ as cli
        code = cli.main({argv!r})
        sys.stdout.write("\\n" + json.dumps([code, sorted(m for m in {FORBIDDEN!r} if m in sys.modules)]) + "\\n")
    """)
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(root))
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(root), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return json.loads(proc.stdout.decode("ascii").splitlines()[-1])


@pytest.mark.parametrize("argv, exit_code", [
    (["--version"], 0),
    (["nope"], 2),
    (["_selftest", "ok"], 0),
    (["_selftest", "raise"], 1),       # the crash path: no dialog toolkit even when something fails
])
def test_quick_calls_load_nothing_heavy(tmp_path, argv, exit_code):
    assert _loaded_by(argv, tmp_path) == [exit_code, []]


def test_the_guard_sees_a_forbidden_import(tmp_path, monkeypatch):
    # The check itself works: a verb that imports tkinter is caught (the import guard's own witness).
    script = textwrap.dedent(f"""
        import json, sys
        from app.cli import __main__ as cli
        cli.VERBS["_selftest"] = (cli._selftest_args, lambda a: __import__("tkinter") and {{}}, False)
        cli.main(["_selftest", "ok"])
        sys.stdout.write("\\n" + json.dumps(sorted(m for m in {FORBIDDEN!r} if m in sys.modules)) + "\\n")
    """)
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(tmp_path))
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(tmp_path), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert "tkinter" in json.loads(proc.stdout.decode("ascii").splitlines()[-1])


def test_no_cli_source_names_a_dialog_toolkit():
    # Nothing on a CLI path may even reach for messagebox (02 §4): not in a function-level import either.
    for path in glob.glob(os.path.join(PROJECT_ROOT, "app", "cli", "*.py")):
        with open(path, encoding="utf-8") as f:
            source = f.read()
        for name in ("tkinter", "messagebox", "PyQt6", "pandas", "requests"):
            assert f"import {name}" not in source and f"from {name}" not in source, (path, name)
