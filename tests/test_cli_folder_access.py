"""3.0.1 — surasura-cli under Windows' Controlled folder access (Mattias 2026-11-10: "surasura-cli got a block by
defender for trying to write into %userprofile%\\Documents\\Surasura\\results").

What a wrong answer would cost: hato (or any caller) told "failed" with a traceback for a refusal only the learner can
fix — or worse, a verb that half-writes and then crashes; the CLI's contract broken by a new code callers don't know
(it is 02 §3's `needs-you`, exit 4, with `need` and `ask`); a write check where nothing is at risk (every call, for
everyone) or on a verb that writes nothing (`status` must always answer).

In-process calls (`cli.main(argv, out=…)`), the verb itself a stand-in so only the check is under test; Defender's
values and Windows' refusal are faked (`tests/test_cfa`); the library is an installed one in a stand-in Documents."""
import io
import json
import os

import pytest

from app import cfa, path_utils
from app.cli import __main__ as cli
from app.cli import contract
from tests.test_cfa import fake_registry, refuse_inside


@pytest.fixture
def documents(tmp_path, monkeypatch):
    for name, sub in (("USERPROFILE", "profile"), ("HOME", "profile")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    folder = tmp_path / "profile" / "Documents"
    library = folder / "Surasura"
    (library / "results").mkdir(parents=True)
    (library / "User Files" / "ja").mkdir(parents=True)
    monkeypatch.setattr(path_utils, "installed_library", lambda: str(library))
    return str(folder)


def _verb(monkeypatch, name, body):
    add, _run, public = cli.VERBS[name]
    monkeypatch.setitem(cli.VERBS, name, (add, body, public))


def _call(argv):
    out = io.StringIO()
    code = cli.main(argv, out=out)
    return code, [json.loads(line) for line in out.getvalue().splitlines()]


def test_a_writing_verb_blocked_by_windows_needs_you_with_both_ways_out(monkeypatch, documents):
    fake_registry(monkeypatch, switch=1, documents=documents)
    refuse_inside(monkeypatch, documents)
    ran = []
    _verb(monkeypatch, "generate", lambda args: ran.append(1) or {"ran": True})
    code, lines = _call(["generate"])
    assert code == 4 and ran == [], "the verb never started"
    error = lines[-1]
    library = os.path.join(documents, "Surasura")
    assert error["type"] == "error" and error["code"] == "needs-you" and error["need"] == cfa.NEED
    assert error["folder"] == library and error["move_to"] == cfa.move_target()
    assert error["allow"] == ["Surasura.exe", "surasura-cli.exe"] and error["settings"] == cfa.SETTINGS_PAGE
    for words in ("Controlled folder access", "Move my library", "surasura-cli.exe", library):
        assert words in error["message"] and error["ask"] == error["message"]
    assert os.listdir(os.path.join(library, "results")) == [], "nothing written"


def test_the_refusal_is_kept_for_the_window_too(monkeypatch, documents):
    fake_registry(monkeypatch, switch=1, documents=documents)
    refuse_inside(monkeypatch, documents)
    _verb(monkeypatch, "known-sync", lambda args: {"synced": True})
    assert _call(["known-sync"])[0] == 4
    with open(os.path.join(contract.log_folder(), "cli-events.jsonl"), encoding="utf-8") as f:
        last = json.loads(f.read().splitlines()[-1])
    assert last["code"] == "needs-you" and last["exit"] == 4 and "Controlled folder access" in last["message"]


@pytest.mark.parametrize("verb", ["status", "list"])
def test_a_verb_that_writes_nothing_is_never_checked(monkeypatch, documents, verb):
    fake_registry(monkeypatch, switch=1, documents=documents)
    monkeypatch.setattr(cfa, "probe", lambda folder: pytest.fail("a write check for a verb that writes nothing"))
    _verb(monkeypatch, verb, lambda args: {"answered": True})
    code, lines = _call([verb])
    assert code == 0 and lines[-1]["answered"] is True


@pytest.mark.parametrize("why", ["cfa off", "outside", "allowed", "portable"])
def test_nothing_at_risk_or_allowed_runs_the_verb(monkeypatch, tmp_path, documents, why):
    if why == "outside":
        monkeypatch.setattr(path_utils, "installed_library", lambda: str(tmp_path / "profile"))
    if why == "portable":
        monkeypatch.setattr(path_utils, "installed_library", lambda: None)
    fake_registry(monkeypatch, switch=0 if why == "cfa off" else 1, documents=documents)
    if why != "allowed":
        monkeypatch.setattr(cfa, "probe", lambda folder: pytest.fail("a write check with nothing at risk"))
    _verb(monkeypatch, "generate", lambda args: {"ran": True})
    code, lines = _call(["generate"])
    assert code == 0 and lines[-1]["ran"] is True


def test_a_refusal_in_the_middle_of_a_verb_is_the_same_answer_never_a_crash(monkeypatch, documents):
    # The write check passed (Windows changed its mind, or one part only is protected): the verb's own write refused.
    fake_registry(monkeypatch, switch=1, documents=documents)
    report = os.path.join(documents, "Surasura", "results", "reading_list_static.html")

    def generate(args):
        raise PermissionError(13, "Access is denied", report)
    _verb(monkeypatch, "generate", generate)
    code, lines = _call(["generate"])
    assert code == 4 and lines[-1]["code"] == "needs-you" and lines[-1]["folder"] == os.path.dirname(report)


def test_access_denied_outside_a_protected_folder_stays_a_plain_failure(monkeypatch, tmp_path, documents):
    fake_registry(monkeypatch, switch=1, documents=documents)
    elsewhere = str(tmp_path / "profile" / "Surasura" / "results" / "x.csv")

    def generate(args):
        raise PermissionError(13, "Access is denied", elsewhere)
    _verb(monkeypatch, "generate", generate)
    code, lines = _call(["generate"])
    assert code == 1 and lines[-1]["code"] == "failed"
