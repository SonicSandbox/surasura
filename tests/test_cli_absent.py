"""Every optional module removed — Junban (and Backfill with it), Koe, YouTube, Reels: the app and the command line
still run, and `junban` says it is absent (RD-S10; P0.3 05; P1.2 row 1.2.6's proof).

A build without `modules/` is a supported build (CLAUDE.md's modularity rule). Each case runs in a child process
whose import system refuses every `modules.*` import, as a build without the folder would.
"""
import json
import os
import subprocess
import sys
import textwrap

import pytest

from tests import cli_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.tk_on_github import REASON, on_github

_NO_MODULES = textwrap.dedent("""
    import importlib.abc, sys

    class NoModules(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name == "modules" or name.startswith("modules."):
                raise ModuleNotFoundError(f"No module named {name!r} (this build has no modules)")
            return None

    sys.meta_path.insert(0, NoModules())
""")


def _without_modules(body):
    proc = subprocess.run([sys.executable, "-c", _NO_MODULES + textwrap.dedent(body)], cwd=h.root(),
                          env=h.child_env(), capture_output=True, timeout=300)
    return proc.returncode, proc.stdout.decode("ascii", "replace"), proc.stderr.decode("utf-8", "replace")


def _cli_without_modules(*argv):
    code, out, err = _without_modules(f"""
        from app.cli import __main__ as cli
        sys.exit(cli.main({list(argv)!r}))
    """)
    lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    assert lines, err
    return code, lines[-1]


def test_the_command_line_runs_with_every_module_removed():
    h.seed_library("ja")
    h.write_settings(enable_junban=True, junban_auto_reorder=True)
    code, status = _cli_without_modules("status")
    assert code == 0 and status["junban"] == "absent" and status["backfill"] == "absent"
    for how in ("--dry-run", "--auto"):
        code, line = _cli_without_modules("junban", how)
        assert code == 0 and line["skipped"] == "junban absent" and line["moves"] == 0, (how, line)
    code, line = _cli_without_modules("backfill", "--tag", "surasura::connect::job-1")         # P1.4 row 1.4.7
    assert code == 0 and line["skipped"] == "backfill absent" and line["filled"] == 0, line
    code, line = _cli_without_modules("generate")
    assert code == 0 and line["ran"] is True
    code, line = _cli_without_modules("list", "--limit", "3")
    assert code == 0 and line["words"]
    code, line = _cli_without_modules("known")
    assert code == 0 and line["count"] > 1000


@pytest.mark.skipif(on_github(), reason=REASON)
def test_the_dashboard_opens_and_closes_with_every_module_removed():
    h.seed_library("ja", templates=False)
    h.write_settings(enable_junban=True)
    code, out, err = _without_modules("""
        import os
        os.environ["SURASURA_NO_UI_TIMERS"] = "1"
        from tests.quiet_windows import quiet_windows
        quiet_windows()                         # the dashboard on the tests' own desktop, as in the suite
        import tkinter as tk
        from app.main import MasterDashboardApp
        root = tk.Tk()
        root.withdraw()
        app = MasterDashboardApp(root)
        root.update()
        app._maybe_junban_auto(force=True)          # the automatic reorder's trigger, with no module to call
        root.destroy()
        print("OPENED")
    """)
    assert code == 0 and "OPENED" in out, err
