"""`undo.act` and `undo.owe_sync`: the gaps the P3.1 mutant pass found (2026-10-11).

What a wrong answer would cost:
  * a Chinese batch's undo opening the Japanese library: the Chinese words the batch made stay held there, and the
    Japanese library is written for an undo of Chinese cards;
  * an undo's sync owed as "tomorrow's cards didn't change" (`after_write(settings, False)`), or the session's answer
    never handed to the sync kick: the phone keeps cards that are gone here;
  * a raise from arranging the sync reaching the undo: the batch is already undone in Anki.

Anki is a fake (no test reaches Anki); the library, the run, the session and the kick are stood in for, so the tests
record only what the undo asks of them. Real Japanese words; the batch's language is what matters, not the spelling.
"""
import contextlib
import os

import pytest

from app.connect import library, undo
from app.connect.ledger import Ledger, path

TAG = "surasura::connect::"
WORDS = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")]
ZH_ON = {"connect_enabled": True, "target_language": "zh", "anki_connect_url": "http://127.0.0.1:9"}


class FakeAnki:
    """Anki that answers nothing: the undo is run by the fake `undo.run` below, and the write lock is free."""

    def __init__(self):
        self.url = ZH_ON["anki_connect_url"]
        self.synced = []

    def reviewing(self):
        return False

    def writer(self, verb):
        return contextlib.nullcontext()


@pytest.fixture
def anki(monkeypatch):
    """Chinese set up (its folder made), Anki the fake, no real sync: each owed sync is counted in `anki.synced`."""
    os.makedirs(os.path.join(os.environ["SURASURA_TEST_ROOT"], "User Files", "zh"), exist_ok=True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    fake = FakeAnki()
    monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: fake)
    monkeypatch.setattr(undo, "owe_sync", lambda settings: fake.synced.append(settings))
    return fake


def _zh_batch(language="zh"):
    """A finished batch of item 7 in the given language that made the five notes -> the job id."""
    with Ledger(path()) as ledger:
        job_id = ledger.queue(language, 7, "user", None, store_id="s1")
        ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                             for n, w in WORDS])
        ledger.set_state(job_id, "done")
    return job_id


def test_undo_of_a_chinese_batch_opens_the_chinese_library(anki, monkeypatch):
    """Undoing a Chinese batch opens the Chinese library: the words it made are freed there. Asserting the language
    the library is opened with (not the rows) pins the rule, since the Japanese library would free other words."""
    opened = []

    def fake_store(language, role="connect"):
        opened.append(language)
        return None

    def fake_run(anki_, ledger, job_id, open_store=None, language=None):
        open_store()                            # what the real run does first: open the library for this batch
        return {"job": job_id, "language": language}

    monkeypatch.setattr(library, "open_store", fake_store)
    monkeypatch.setattr(undo, "run", fake_run)
    monkeypatch.setattr(undo, "summary", lambda done: {})

    job_id = _zh_batch()
    result = undo.act(ZH_ON, "zh", job=job_id, confirm=True)

    assert opened == ["zh"], "the Chinese batch's undo must open the Chinese library, not the Japanese one"
    assert result["confirm"] is True and result["language"] == "zh"
    assert len(anki.synced) == 1               # the owed sync still follows a done write


@pytest.fixture
def sync_calls(monkeypatch):
    """Records what `owe_sync` asks of the session and hands to the sync kick, in order."""
    calls = {"after_write": [], "pending": []}
    due = object()                      # a marker the session "answers" with, so identity can be checked

    def fake_after_write(settings, front_changed):
        calls["after_write"].append((settings, front_changed))
        return due

    def fake_sync_pending(loaded, answer):
        calls["pending"].append((loaded, answer))

    from app.connect import anki_session
    import app.cli.verbs as verbs
    monkeypatch.setattr(anki_session, "after_write", fake_after_write)
    monkeypatch.setattr(verbs, "_sync_pending", fake_sync_pending)
    calls["due"] = due
    return calls


def test_undo_owes_its_sync_as_a_change_to_tomorrows_cards_and_hands_the_answer_to_the_kick(sync_calls):
    """A batch undo deletes or shelves back cards, which changes tomorrow's cards. The rule: the session is asked with
    `front_changed=True` (never False), and the answer it gives is the one the sync kick receives."""
    settings = {"connect_enabled": True, "target_language": "ja"}

    undo.owe_sync(settings)

    assert sync_calls["after_write"] == [(settings, True)], "the undo must report a change to tomorrow's cards"
    assert len(sync_calls["pending"]) == 1
    loaded, answer = sync_calls["pending"][0]
    assert loaded is settings
    assert answer is sync_calls["due"], "the sync kick must get exactly the session's answer, not a rebuilt one"


def test_undo_owe_sync_never_raises_when_the_session_fails(monkeypatch, sync_calls):
    """If the session cannot arrange the sync, the undo still completes: `owe_sync` returns normally and nothing is
    kicked. The batch is already undone in Anki when this runs, so a raise would be an error for a finished change."""
    from app.connect import anki_session

    def broken_after_write(settings, front_changed):
        raise RuntimeError("the session's clock file is unreadable")

    monkeypatch.setattr(anki_session, "after_write", broken_after_write)

    result = undo.owe_sync({"connect_enabled": True})

    assert result is None
    assert sync_calls["pending"] == [], "no sync is kicked when the session could not arrange one"
