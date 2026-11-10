"""surasura-cli's surasura.json hook: the gap the P3.2 mutant pass found (research/mutants/JUDGED-P3.2.md) — a planted
bug in app/cli/__main__.py that test_tools_entry.py let through. The test names its mutant.

The test's own root (`--root`) and its own tools folder; a synthetic command line advertised; Japanese text echoed."""
import io

from app import tools_entry
from app.cli import __main__ as cli


def _call(argv):
    out = io.StringIO()
    code = cli.main(argv, out=out)
    return code, out.getvalue()


def test_a_refresh_failing_with_any_error_never_changes_the_verbs_answer(tmp_path, monkeypatch):
    """P3.2-B78. The refresh raising something other than an OSError (tools_dir's RuntimeError, an unreadable
    settings error): the verb answers and exits as it would, the failure only in cli.log."""
    r = tmp_path / "根"
    expected = _call(["--root", str(r), "_selftest", "ok", "--echo", "日本語"])
    assert expected[0] == 0

    def boom(settings=None):
        raise RuntimeError("a test reached the real shared tools folder")
    monkeypatch.setattr(tools_entry, "refresh", boom)
    assert _call(["--root", str(r), "_selftest", "ok", "--echo", "日本語"]) == expected
