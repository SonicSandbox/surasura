"""Connect's prepare step with a list in another language (P2.4 review fix R20; runner `Steps.prepare`, the
WAIT_FOR_OTHER_LIST switch): while the results hold a Chinese list and Connect is set to run Japanese, the job waits
with a reason that names Chinese, and nothing is started: no Anki session sync, no known-sync, no Generate. A list
that is already in the job's language goes on as before.

What a wrong answer would cost: Connect Generating over your Chinese list and replacing it with a Japanese one behind
your back; Connect's Anki session opened for a job that then waits anyway.

Real `Steps` with its Anki session and verbs monkeypatched to record calls; no Anki, no network, no real sleeps.
"""
import pytest

from app.cli import verbs
from app.connect import anki_session, runner


@pytest.fixture
def calls(monkeypatch):
    """Record every call the prepare step could make; `begin` stops the run if it is ever reached, so a wrong
    answer can't reach the real Anki session or the real Generate."""
    recorded = {"begin": 0, "generate": 0}

    def begin(url, loaded):
        recorded["begin"] += 1
        raise RuntimeError("sentinel: the Anki session was reached")

    def generate(ns):
        recorded["generate"] += 1
        raise RuntimeError("Generate must not run over another language's list")
    monkeypatch.setattr(anki_session, "begin", begin)
    monkeypatch.setattr(verbs, "generate", generate)
    return recorded


def test_a_list_in_another_language_makes_connect_wait_naming_it_and_starts_nothing(monkeypatch, calls):
    monkeypatch.setattr(verbs, "_results_language", lambda: "zh")
    steps = runner.Steps({})
    with pytest.raises(runner.Wait) as caught:
        steps.prepare("ja", None)
    # the reason names the other list (Chinese), so Sonic can see why the job waits
    assert "Chinese" in caught.value.reason
    assert calls == {"begin": 0, "generate": 0}, "neither the session nor Generate may start over a Chinese list"


def test_a_list_in_the_job_language_goes_on_to_the_session(monkeypatch, calls):
    # control: with the list already Japanese, prepare is not held back, so the Anki session is reached
    monkeypatch.setattr(verbs, "_results_language", lambda: "ja")
    steps = runner.Steps({})
    with pytest.raises(RuntimeError, match="sentinel"):
        steps.prepare("ja", None)
    assert calls["begin"] == 1, "a Japanese list lets the job reach the session"
