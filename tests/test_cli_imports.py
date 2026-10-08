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


# --------------------------------------------------------------------------- #
# P1.2's verbs (row 1.2.3): the quick ones load nothing heavy and read no text; the rest load no GUI toolkit, no
# pandas and no network library either (fugashi only where text is read: `junban`, `known` on a stale cache)
# --------------------------------------------------------------------------- #
NOT_EVEN_TEXT = FORBIDDEN                                       # quick verbs: no tokenizer either
NOT_HEAVY = tuple(m for m in FORBIDDEN if m not in ("fugashi", "jieba"))


@pytest.fixture
def generated():
    """A library generated once (the analyzer runs as its own process: it is not this guard's subject)."""
    from tests import cli_helpers as h
    h.seed_library("ja")
    h.write_settings()
    code, lines = h.run_cli("generate")
    assert code == 0, lines
    return h.root()


def _loaded(argv, root):
    code, loaded = _loaded_by(argv, root)
    return code, set(loaded)


@pytest.mark.parametrize("argv", [["status"], ["status", "--anki"], ["list", "--limit", "5"],
                                  ["list", "--order", "encounter"], ["known"], ["setup"]])
def test_the_quick_verbs_load_nothing_heavy_and_no_tokenizer(generated, argv):
    code, loaded = _loaded(argv, generated)
    assert code == 0 and not loaded & set(NOT_EVEN_TEXT), loaded


@pytest.mark.parametrize("argv", [["generate"], ["known-sync"], ["junban", "--dry-run"], ["junban", "--auto"],
                                  ["resort"], ["resort", "--dry-run"],
                                  ["backfill", "--tag", "surasura::connect::job-1"],
                                  ["backfill", "--notes", "1789712000000", "--dry-run"]])
def test_the_other_verbs_load_no_gui_toolkit_pandas_or_network_library(generated, argv):
    """`generate` with nothing changed answers without pandas; the Anki verbs reach Anki through the standard library
    (here with Anki switched off for the run, as the suites keep it)."""
    code, loaded = _loaded(argv, generated)
    assert code == 0 and not loaded & set(NOT_HEAVY), loaded


@pytest.mark.parametrize("argv", [["pick", "--file", "{library}/phrases_sample.srt"],
                                  ["pick", "--file", "{library}/phrases_sample.srt", "--words", "unknown"],
                                  ["list", "--file", "{library}/phrases_sample.srt", "--order", "encounter"]])
def test_pick_and_a_subtitles_list_read_text_but_load_no_gui_toolkit_pandas_or_network_library(generated, argv):
    """P1.3: `pick` is a quick verb in what it loads (no Tk, Qt, pandas, requests); it reads a subtitle, so the
    tokenizer loads — and nothing of Connect's beyond what it calls."""
    library = os.path.join(generated, "data", "ja", "HighPriority")
    code, loaded = _loaded([a.replace("{library}", library) for a in argv], generated)
    assert code == 0 and not loaded & set(NOT_HEAVY), loaded


def test_nothing_of_connect_loads_unless_a_verb_needs_it(tmp_path):
    # Preview off is 2.5: a call that isn't pick or a subtitle's list never imports app.connect or app.cues
    script = textwrap.dedent("""
        import json, sys
        from app.cli import __main__ as cli
        for argv in (["--version"], ["status"], ["list"], ["known"], ["nope"]):
            cli.main(argv)
        sys.stdout.write("\\n" + json.dumps(sorted(m for m in sys.modules if m.startswith(("app.connect", "app.cues"))))
                         + "\\n")
    """)
    environment = dict(os.environ, PYTHONPATH=PROJECT_ROOT, SURASURA_TEST_ROOT=str(tmp_path))
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(tmp_path), env=environment,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    assert json.loads(proc.stdout.decode("ascii").splitlines()[-1]) == []


# --------------------------------------------------------------------------- #
# P2.1's verbs (row 2.1.8): `register`, `place`, `finish` and `connect --consume-only` are quick — no tokenizer either
# --------------------------------------------------------------------------- #
@pytest.fixture
def paired_library():
    """A library with its store, Connect on, and one hato drop with its pairing record on disk."""
    from tests import cli_helpers as h
    from tests import connect_helpers as c
    c.library()
    record = c.write_record(c.record(c.drop("Example Show - 05.ja.srt"), "video-05"))
    return h.root(), record


@pytest.mark.parametrize("argv, exit_code", [
    (["register", "--pairing", "{record}"], 0),
    (["place", "--file", "1", "--to", "soon", "--source", "test"], 0),
    (["finish", "--file", "1", "--source", "test"], 2),            # held to 3.0
    (["connect", "--consume-only"], 0),
])
def test_p2_1s_verbs_load_nothing_heavy_and_no_tokenizer(paired_library, argv, exit_code):
    root, record = paired_library
    code, loaded = _loaded([a.replace("{record}", record) for a in argv], root)
    assert code == exit_code and not loaded & set(NOT_EVEN_TEXT), loaded
