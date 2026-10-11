"""Connect's switch reads as off when settings.json can't be read, and as on when it says so (P2.4-E05).
`runner.Steps.enabled()` reads `connect_enabled` from settings.json at every look and before each job. A file that
can't be read must stop the run (the switch reads off); only a file that says the switch is on lets it run.

What a wrong answer would cost: a broken or half-written settings.json would switch Connect on, so cards would be
made into Anki unattended by a user who had turned the preview off.

Real settings values; the settings reader is monkeypatched on `verbs` (as the neighbour tests do); Anki is never
reached.
"""
from app.cli import verbs
from app.connect import runner


def test_settings_that_cannot_be_read_switch_connect_off(monkeypatch):
    # why: an unreadable file is not a "yes" — the run must stop, never mine cards unasked
    def unreadable():
        raise RuntimeError("bad-data")

    monkeypatch.setattr(verbs, "settings", unreadable)
    assert runner.Steps({}).enabled() is False


def test_settings_that_say_connect_is_on_switch_it_on(monkeypatch):
    monkeypatch.setattr(verbs, "settings", lambda: {"connect_enabled": True})
    assert runner.Steps({}).enabled() is True
