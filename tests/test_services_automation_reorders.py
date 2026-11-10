"""順's automatic re-order's gate (`automation.reorders`) when its answer can't be had.

What a wrong answer would cost a learner: Anki's new cards re-ordered behind their back on a guess — beside the
re-order host, or with automation off — because the switch's read failed (settings.json mid-write, the host's
predicate raising).
"""
from app import replan_preview
from app.services import automation

SETTINGS = {"target_language": "ja", "enable_junban": True, "junban_scope": "deck", "junban_deck": "日本語::Mining",
            "junban_replan_language": "ja", "junban_replan_deck": "日本語::Mining", "logic": {"automation": True}}


def test_the_automatic_reorder_runs_where_the_host_cannot_and_the_deck_is_recorded(monkeypatch):
    """The setup the next test breaks: the host stands aside here, the deck is recorded for Japanese — 順 re-orders."""
    monkeypatch.setattr(replan_preview, "automation_on", lambda settings, language: False)
    assert automation.reorders(dict(SETTINGS), "ja") is True


def test_a_gate_that_cannot_be_read_never_lets_the_automatic_reorder_write(monkeypatch):
    """The host's predicate fails: no is the answer — never a write to Anki on a guess."""
    def broken(settings, language):
        raise OSError("settings.json is being written")
    monkeypatch.setattr(replan_preview, "automation_on", broken)
    assert automation.reorders(dict(SETTINGS), "ja") is False
