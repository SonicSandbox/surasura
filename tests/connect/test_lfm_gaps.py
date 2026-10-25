"""Connect's media rename and profile pick after the laptop fixes (mining): each test pins a rule the real code holds
that no earlier test did.

- the batch search for a file's users (`many("users", ...)`) is escaped exactly like the single one
  (`users(name)`): a name holding `"` or `\\` goes into the Anki search quoted and escaped, or the search is broken or
  finds no one, and a file still in use could be deleted.
- no profile recorded and Anki naming none: a wait (NO_PROFILE_YET), no deck look-up, nothing recorded.
- `AnkiConnectMedia.many` answers one (ok, answer) pair per item, in order, every item sent once across its
  `multi` chunks — a dropped one would leave a note unrenamed or an old file undeleted.

Against stand-ins for AnkiConnect and a record file in a temp folder; never a live Anki.
"""
import pytest

from app import anki_connect
from app.connect import anki_session, media_names, runner, setup
from tests.connect.test_lf_mining import _anki

# a file name with both characters Anki's search needs escaped: a double quote and a backslash
NAME = 'clip "1" \\ a.mp3'
# the search Anki must receive: the name quoted, its " and \ each escaped with a backslash
ESCAPED_QUERY = '"clip \\"1\\" \\\\ a.mp3"'


@pytest.fixture
def sent(monkeypatch):
    """Captures what the adapter sends: the actions of each `multi`, and each single `findNotes` query."""
    captured = {"multi": [], "invoke": []}

    def fake_multi(actions, url, timeout=30):
        captured["multi"].extend(actions)
        return [{"result": [], "error": None} for _ in actions]

    def fake_invoke(action, url, timeout=30, **params):
        captured["invoke"].append((action, params))
        return []

    monkeypatch.setattr(anki_connect, "multi", fake_multi)
    monkeypatch.setattr(anki_connect, "invoke", fake_invoke)
    return captured


def test_batch_users_search_is_escaped_the_same_as_the_single_search_for_a_name_with_quote_and_backslash(sent):
    # why: the batch route must search for the same escaped text as the single route, or a file in use is read
    # as unused and deleted; an unescaped quote or backslash also breaks the search outright
    media = media_names.AnkiConnectMedia("http://127.0.0.1:8765")

    media.many("users", [(NAME,)])
    media.users(NAME)

    batch_query = sent["multi"][0]["params"]["query"]
    single_query = sent["invoke"][0][1]["query"]
    assert batch_query == single_query, "the batch search is the single search"
    assert batch_query == ESCAPED_QUERY, "the name is quoted, with its \" and \\ escaped as Anki's search needs"


@pytest.mark.parametrize("open_now", [None, ""])
def test_no_profile_recorded_and_anki_naming_none_waits_without_asking_decks_or_recording(monkeypatch, tmp_path,
                                                                                           open_now):
    # why: no record and Anki names no open profile (the call fails or answers empty): even with decks chosen
    # the answer is a wait (NO_PROFILE_YET), Anki is never asked for its decks, and nothing is written to the record
    monkeypatch.setattr(setup, "record_path", lambda: str(tmp_path / "setup.json"))
    calls = []
    _anki(monkeypatch, open_now, calls=calls, decks=["Default"])
    settings = {"connect_enabled": True, "anki_sync_decks": {"ja": ["日本語::アニメ"]}}
    # a call that times out is Anki busy (alpha 3 review A5: plain, not amber); one answering empty names no profile
    want = anki_session.BUSY if open_now is None else anki_session.NO_PROFILE_YET
    assert runner.Steps(settings).blocked("ja") == want
    assert "deckNames" not in calls
    assert setup.anki_profile() is None
    assert "anki_profile_at" not in setup.read_record()


def test_many_sends_every_item_once_in_order_across_chunks(monkeypatch):
    # why: with chunks of 2, five items are three requests (2, 2, 1); a chunk edge that skips or repeats an item
    # changes the answers or their order
    existing = {"a.mp3", "c.mp3", "e.mp3"}
    names = ["a.mp3", "b.mp3", "c.mp3", "d.mp3", "e.mp3"]
    requests = []

    def fake_multi(actions, url, timeout=None, **kw):
        requests.append(actions)
        return [{"result": [a["params"]["pattern"]] if a["params"]["pattern"] in existing else [], "error": None}
                for a in actions]

    monkeypatch.setattr(media_names, "MANY_CHUNK", 2)
    monkeypatch.setattr(anki_connect, "multi", fake_multi)

    out = media_names.AnkiConnectMedia("http://127.0.0.1:8765").many("exists", [(n,) for n in names])

    assert out == [(True, True), (True, False), (True, True), (True, False), (True, True)], out
    sent = [a["params"]["pattern"] for request in requests for a in request]
    assert sent == names, "every name sent exactly once, in order"
    assert [len(r) for r in requests] == [2, 2, 1], "no request over MANY_CHUNK actions"
