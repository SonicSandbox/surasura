"""The command line's one numbering rule for its Junban writers (`verbs.numbering_job`): from 3.0 always an automatic
spaced job — the dry run and the run alike.

What a wrong answer would cost a learner: `junban --dry-run` (or `resort --dry-run`) planned as the 順 window's own
run — its fallbacks and suggestions included — while the run itself is automatic and lean, so the preview promises
moves the run never makes; or a run that keeps the window's snapshot instead of today's baseline.
"""
import pytest

from app.cli import verbs


@pytest.mark.parametrize("settings", [
    {"target_language": "ja", "junban_deck": "日本語::Mining"},
    {"target_language": "zh", "junban_deck": "中文::Mining", "logic": {"automation": False}},
])
def test_the_command_lines_junban_job_is_automatic_whatever_the_switches_say(settings):
    pytest.importorskip("modules.junban")
    from modules.junban import spaced
    job = verbs.numbering_job(settings, settings["target_language"])
    assert isinstance(job, spaced.Job)
    assert job.automatic is True, "the dry run would be planned as the window's run, not the automatic one"
