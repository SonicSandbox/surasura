"""P4.1 row 4.1.7 (P3.3's F9): *Connect is updating your list* — the status line while Connect's own Generate runs.

The runner marks `generating:<lang>` in the ledger's meta around `Steps._generate` — prepare's Generate first and
F11's Generate after mining — and clears it however the Generate ends; `status._line` says *Connect is updating your
list* while Connect runs and the mark is set. A mining job's line still wins (*Making cards 2 of 5 — …*); a mark a
crash left says nothing (Connect isn't running) and the next run clears it.

A real ledger under the test's folder, read by `status.read` as the window reads it (its own read-only connection),
from inside a spy Generate. What a wrong answer would cost: the window saying *Up to date* (or an old wait) for the
minute Connect spends Generating — or *updating your list* for ever after a crash.
"""
from types import SimpleNamespace

import pytest

from app.cli import verbs
from app.cli.contract import CliError
from app.connect import anki_session, runner, status
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps


@pytest.fixture
def ledger_path(tmp_path):
    path = str(tmp_path / "ledger.sqlite")
    with Ledger(path):
        pass
    return path


@pytest.fixture
def running(monkeypatch):
    """Connect's lock held (it is running) unless a test says otherwise."""
    state = {"on": True}
    monkeypatch.setattr(status, "running", lambda: state["on"])
    return state


def _ja(path):
    return status.read(["ja"], path=path)["languages"]["ja"]


def _current(generate, reason="test"):
    from app.connect import replan
    return replan.Current(("generate-first", "files") if generate == "first" else None, generate, reason)


class _Steps(runner.Steps):
    """Connect's real steps around the Generate: prepare's and F11's own code; the session, the known-sync, the shelf
    and the plan's reads stand in (their own suites)."""

    def __init__(self, verdicts):
        super().__init__({"target_language": "ja"})
        self.verdicts = list(verdicts)

    def current(self, lang, fresh=False):
        return self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]

    def notes_gone(self, lang):
        return []

    def shelf_session(self, lang, ledger):
        pass


@pytest.fixture
def prepared(monkeypatch):
    monkeypatch.setattr(verbs, "_results_language", lambda: "ja")
    monkeypatch.setattr(anki_session, "begin", lambda url, loaded: None)
    monkeypatch.setattr(verbs, "known_sync", lambda ns: {"added": 0})


def _spy_generate(monkeypatch, path, seen, fail=None):
    def generate(ns):
        seen.append(_ja(path))              # the window's read, mid-Generate
        if fail is not None:
            raise fail
        return {"language": ns.lang}
    monkeypatch.setattr(verbs, "generate", generate)


def test_prepares_generate_first_says_connect_is_updating_your_list_and_the_line_goes_after(
        ledger_path, running, prepared, monkeypatch):
    seen = []
    _spy_generate(monkeypatch, ledger_path, seen)
    steps = _Steps([_current("first"), _current("no")])
    with Ledger(ledger_path) as ledger:
        jid = ledger.queue("ja", 11, "user", None)          # the job that waits for the list: not mid-step
        steps.prepare("ja", ledger)
    assert len(seen) == 1, "the Generate ran once"
    assert seen[0]["line"] == status.UPDATING_LINE and seen[0]["state"] == "working", seen[0]
    assert seen[0]["updating"] is True
    after = _ja(ledger_path)
    assert after["line"] != status.UPDATING_LINE and after["updating"] is False, after
    assert jid


def test_the_generate_after_mining_says_it_too(ledger_path, running, monkeypatch):
    seen = []
    _spy_generate(monkeypatch, ledger_path, seen)
    steps = _Steps([_current("no")])
    steps._after["ja"] = "new-files"                     # F11: owed once mining is done
    with Ledger(ledger_path) as ledger:
        assert steps.generate_after("ja", ledger) is True
    assert [s["line"] for s in seen] == [status.UPDATING_LINE]
    assert _ja(ledger_path)["line"] == "Up to date"


@pytest.mark.parametrize("fail", [CliError("failed", "the analyzer stopped"), CliError("busy", "another Generate"),
                                  RuntimeError("boom")])
def test_a_generate_that_fails_or_waits_clears_the_mark_too(ledger_path, running, monkeypatch, fail):
    seen = []
    _spy_generate(monkeypatch, ledger_path, seen, fail=fail)
    steps = _Steps([_current("no")])
    steps._after["ja"] = "known"
    with Ledger(ledger_path) as ledger:
        with pytest.raises((runner.Wait, runner.Needs, RuntimeError)):
            steps.generate_after("ja", ledger)
        assert ledger.updating("ja") is None, "cleared however the Generate ended"
    assert seen[0]["line"] == status.UPDATING_LINE
    assert _ja(ledger_path)["updating"] is False


def test_a_mining_jobs_line_still_wins(ledger_path, running):
    with Ledger(ledger_path) as ledger:
        ledger.mark_run("ja")
        first = ledger.queue("ja", 21, "user", None)
        ledger.queue("ja", 22, "user", None)
        ledger.set_state(first, "mining")
        with ledger.transaction():
            ledger.mark_updating("ja")
    ja = _ja(ledger_path)
    assert ja["line"].startswith("Making cards 1 of 2") and ja["state"] == "working", ja


def test_a_mark_a_crash_left_says_nothing_and_the_next_run_clears_it(ledger_path, running, tmp_path):
    with Ledger(ledger_path) as ledger:
        with ledger.transaction():
            ledger.mark_updating("ja")              # Connect was killed mid-Generate
    running["on"] = False
    ja = _ja(ledger_path)
    assert ja["line"] == "Up to date" and ja["updating"] is False, "not running: no line"
    running["on"] = True
    assert _ja(ledger_path)["line"] == status.UPDATING_LINE, "(the mark is still there)"
    steps = FakeSteps(str(tmp_path), {"line": {"ja": []}})
    with Ledger(ledger_path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert ledger.updating("ja") is None, "the next run cleared it"
    assert _ja(ledger_path)["line"] == "Up to date"


def test_an_idle_run_writes_no_mark_to_clear(ledger_path, tmp_path):
    # S19: no mark, nothing written (the ledger's file stays as it is: the window's stamp doesn't move)
    with Ledger(ledger_path) as ledger:
        before = status.stamp(ledger_path, ["ja"])[:2]
        runner._updating(ledger, "ja", False)
        assert status.stamp(ledger_path, ["ja"])[:2] == before


def test_a_ledger_fault_never_stops_the_generate(monkeypatch):
    calls = []
    monkeypatch.setattr(verbs, "generate", lambda ns: calls.append(ns.lang) or {"language": ns.lang})
    broken = SimpleNamespace(updating=lambda lang: 1 / 0, transaction=lambda: 1 / 0)
    steps = _Steps([_current("no")])
    steps._generate(SimpleNamespace(lang="ja", wait=0, full=False, force=False), "say", broken)
    assert calls == ["ja"]
