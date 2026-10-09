"""Review B #11: the media step asks Anki which notes use a file before it deletes the file. If Anki's answer
to that search isn't a list, the step must raise, never read it as "no note uses this file" — that reading
would delete a file a note still plays. What a wrong answer would cost: a learner's audio gone from a card.
"""
import pytest

from app import anki_connect
from app.connect import media_names


@pytest.fixture
def answer(monkeypatch):
    """Stand in for AnkiConnect's answer to `findNotes`. Only `invoke` is replaced; `users` and `_ask` run as written."""
    calls = []
    reply = {"value": None}

    def fake_invoke(action, url, timeout=30, **params):
        calls.append((action, params))
        return reply["value"]

    monkeypatch.setattr(anki_connect, "invoke", fake_invoke)

    def set_reply(value):
        reply["value"] = value

    set_reply.calls = calls
    return set_reply


def test_users_raises_when_find_notes_answers_no_list(answer):
    # Why: AnkiConnect answering with null, a dict or a number means it did not search at all. Returning that as
    # an empty list would tell the caller that no note uses the file, and the file would be deleted.
    media = media_names.AnkiConnectMedia("http://127.0.0.1:8765")
    for bad in (None, {}, 0, "勇気.mp3"):
        answer(bad)
        with pytest.raises(anki_connect.AnkiError) as info:
            media.users("勇気.mp3")
        assert info.value.kind == "protocol"
    assert answer.calls and all(action == "findNotes" for action, _ in answer.calls)


def test_users_returns_the_note_ids_when_find_notes_answers_a_list(answer):
    # Why: the other half of the rule — a real answer is passed back as it came, so the caller can keep the note ids.
    media = media_names.AnkiConnectMedia("http://127.0.0.1:8765")
    answer([1700000001, 1700000002])
    assert media.users("勇気.mp3") == [1700000001, 1700000002]
    assert answer.calls[-1][0] == "findNotes"
    assert answer.calls[-1][1]["query"] == '"勇気.mp3"'
