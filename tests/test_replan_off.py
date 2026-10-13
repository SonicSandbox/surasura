"""Off = byte-identical (E1.1-fast-replan/05 §4; SPEC rule 1; E1.2-1 = B; RUNBOOK E3.1.5), as the 3.0 line reads it.

On the 3.0 line every Generate writes the plan file (E1.2-1, Sonic 2026-10-05: "every Generate from 3.0"; E1.1 04 §5:
with the automation off too): 2.x writes it only while the fast re-plan's preview is on. With the preview off — the
default — a Generate writes every other output exactly as before the plan file existed, and the plan beside them. On
real libraries (tests/plan_file_cases.py: the bundled samples and RP-2's, Japanese and Chinese), every output against
the base's recorded hashes (`plan_file_base_hashes.json`, 2.x-dev before E1.2). Switching it on changes nothing (the
switch is in no signature; the plan is already this run's): the reuse path. A lost or damaged plan gets a full run,
switch on or off. Junban removed: the plan is written all the same. Junban's own requests with the preview off are
E2.1's recorded logs (`modules/junban/tests/test_request_logs.py`).
"""
import json
import os
import subprocess
import sys

import pytest

from app import analyzer
from tests import plan_file_cases as cases


def _plan(root):
    return os.path.join(root, "results", analyzer.PLAN_FILE)


def _switch(root, on):
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"junban_replan_preview": on}, f)


def _base():
    with open(cases.BASE_HASHES, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", ["samples-ja", "rp2-zh"])
def test_off_every_output_is_the_bases_and_the_plan_is_written_all_the_same(tmp_path, case):
    root = str(tmp_path / case)
    cases.build(root, case, preview=False)
    cases.generate(root, case)
    assert os.path.exists(_plan(root)), "3.0: every Generate writes the plan, the preview off too"
    assert cases.output_hashes(root) == _base()[case]


def test_switching_it_on_changes_nothing_and_a_lost_or_damaged_plan_gets_a_full_run(tmp_path):
    case = "samples-ja"
    root = str(tmp_path / case)
    cases.build(root, case, preview=False)
    cases.generate(root, case)
    stamp_off = analyzer.read_run_stamp(os.path.join(root, "results"))
    hashes_off = cases.output_hashes(root)
    assert os.path.exists(_plan(root))
    out = cases.generate(root, case)
    assert "reusing existing results" in out                    # off, nothing changed, the plan this run's: reused

    os.remove(_plan(root))                                      # off and lost: a full run brings it back (3.0)
    out = cases.generate(root, case)
    assert "reusing existing results" not in out and os.path.exists(_plan(root))

    _switch(root, True)
    out = cases.generate(root, case)
    assert "reusing existing results" in out                    # the switch is in no signature; the plan is current
    assert analyzer.read_run_stamp(os.path.join(root, "results")) == stamp_off
    assert cases.output_hashes(root) == hashes_off

    os.remove(_plan(root))                                      # lost: a full run brings it back
    out = cases.generate(root, case)
    assert "reusing existing results" not in out and os.path.exists(_plan(root))

    with open(_plan(root), "rb") as f:
        data = f.read()
    with open(_plan(root), "wb") as f:
        f.write(data[: len(data) // 2])                        # damaged (cut short): a full run too
    out = cases.generate(root, case)
    assert "reusing existing results" not in out
    from app import plan_engine
    assert plan_engine.read_header(_plan(root))["run_signature"] == stamp_off
    assert cases.output_hashes(root) == hashes_off


def test_junban_removed_the_plan_is_written_all_the_same(tmp_path):
    """settings.json says on, but no Junban: the switch reads as off, and the plan is written all the same (3.0)."""
    case = "samples-ja"
    root = str(tmp_path / case)
    cases.build(root, case, preview=False)
    _switch(root, True)                                         # the switch on in settings.json (with Junban or not)
    language, _library, _shipped, args = cases.ALL_CASES[case]
    code = ("import sys, runpy; sys.modules['modules.junban'] = None; "
            f"sys.argv = ['analyzer.py', '--language={language}', '--static', '--no-open'] + {args!r}; "
            "runpy.run_path(r'%s', run_name='__main__')" % os.path.join(cases.REPO, "app", "analyzer.py"))
    p = subprocess.run([sys.executable, "-c", code], cwd=cases.REPO, env=cases.child_env(root), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert p.returncode == 0, p.stderr[-3000:]
    assert os.path.exists(_plan(root))
    assert cases.output_hashes(root) == _base()[case]


def test_the_windows_up_to_date_check_asks_for_the_plan_too(tmp_path, monkeypatch):
    """The window's ✓ and its reopen-only path (`journey_is_current`) ask what the analyzer's reuse gate asks: a run
    without its plan file is not current, so a pressed Generate runs (review #12) — on the 3.0 line with the preview
    off too (every Generate writes the plan)."""
    case = "samples-ja"
    root = str(tmp_path / case)
    env = cases.child_env(root)
    for name in ("SURASURA_TEST_ROOT", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, env[name])
    cases.build(root, case)                                     # the switch on in settings.json
    from app import run_args, settings_manager, token_index
    argv = run_args.analyzer_args(settings_manager.load_settings(), "ja", headless=True)
    cases.generate(root, case, argv=argv[1:])
    # The child's token store holds the run's signature; this process's is the suite's own (conftest): stand it in.
    stamp = analyzer.read_run_stamp(os.path.join(root, "results"))

    class Meta:
        def get_meta(self, key):
            return stamp if key == "last_run_signature" else None

        def close(self):
            pass
    monkeypatch.setattr(token_index, "open_store", lambda language: Meta())
    assert analyzer.journey_is_current(argv, "ja") is True
    os.remove(_plan(root))
    assert analyzer.journey_is_current(argv, "ja") is False
    _switch(root, False)
    assert analyzer.journey_is_current(argv, "ja") is False    # off: 3.0 asks for the plan all the same
