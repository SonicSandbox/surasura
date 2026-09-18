"""The core AnkiConnect client (`app/anki_connect.py`), against a mocked `urlopen` — never live Anki.

**No test here may touch Anki.** The developer's real collection lives on this machine. Every request
is intercepted by `FakeAnki` (the Junban pattern, `modules/junban/tests/test_ankiconnect.py`), which
records the exact bytes that would have gone over the wire — most of the failure modes this client
exists to survive are *shapes*, not exceptions.

Junban's own suite keeps running against the same code through `modules/junban/ankiconnect.py`'s
re-exports; these tests pin the core contract on its own, so it holds with `modules/` deleted
(Prime Invariant) — plus the four things core adds: forbidden actions inside `multi`, the loopback
guard, the `urllib.request.urlopen` patching contract, and a cheap import.

Decided against plain data throughout: `FakeAnki` returns real JSON bytes, so everything downstream
of `json.loads` is a plain dict or list and no `MagicMock` can fake its way through a branch
(`testing.md` §5.3).
"""
import json
import os
import socket
import subprocess
import sys
import urllib.error
from unittest import mock

import pytest

from app import anki_connect
from app.anki_connect import AnkiError

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Real identifiers from the verified 2026-09-17 run on TheBank, so the fixtures have the shape and
# magnitude of genuine Anki data rather than 1/2/3.
CARD_A = 1789712080047
CARD_B = 1789711432547
NOTE_A = CARD_A - 1

URL = anki_connect.DEFAULT_URL

# Real decks on the reference collection.
DECKS = ["Default", "TheBank", "The Accelerator", "Migaku Reference"]


@pytest.fixture
def ja_sentences(ja_resources_dir):
    """Real Japanese sentences from the shared test resources — never dummy ASCII (`testing.md` §1)."""
    with open(os.path.join(ja_resources_dir, "context_test.txt"), "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


# --------------------------------------------------------------------------- #
# The fake wire
# --------------------------------------------------------------------------- #
class _FakeResponse:
    """Minimal stand-in for what `urlopen` yields: a context manager with `.read()`."""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeAnki:
    """Records every request and answers it from `handler(payload)`.

    A handler may return an envelope dict (serialised to JSON), raw `bytes` (for the
    not-really-AnkiConnect cases), or an `Exception` instance to be raised as the socket would.
    """

    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        self.headers = []

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append(payload)
        self.headers.append({name.lower(): value for name, value in request.header_items()})
        reply = self.handler(payload)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, bytes):
            return _FakeResponse(reply)
        return _FakeResponse(json.dumps(reply, ensure_ascii=False).encode("utf-8"))

    @property
    def actions(self):
        return [request["action"] for request in self.requests]


def _ok(result):
    return {"result": result, "error": None}


def _route(**answers):
    """Answer by action name. Values are envelopes, callables taking the payload, or Exceptions."""
    def handler(payload):
        answer = answers.get(payload["action"], _ok(None))
        return answer(payload) if callable(answer) else answer
    return handler


def _run(handler):
    """Patch the GLOBAL `urllib.request.urlopen` — the same target every Junban test patches."""
    fake = FakeAnki(handler)
    return fake, mock.patch("urllib.request.urlopen", fake)


# --------------------------------------------------------------------------- #
# One request: the envelope
# --------------------------------------------------------------------------- #
def test_the_envelope_carries_version_6_and_sends_no_origin_header():
    """Version 6 is what produces the `{"result","error"}` wrapper at all; the *absence* of an
    Origin header is what stops AnkiConnect showing a permission prompt on every run."""
    fake, patched = _run(_route(deckNames=_ok(DECKS)))
    with patched:
        assert anki_connect.invoke("deckNames", URL) == DECKS

    assert fake.requests[0]["version"] == 6
    assert fake.requests[0]["params"] == {}
    assert "origin" not in fake.headers[0], "an Origin header re-introduces the permission prompt"
    assert fake.headers[0]["content-type"] == "application/json"


def test_an_error_field_becomes_an_ankierror_of_kind_action():
    """The ordinary refusal path — a deck that does not exist, a malformed search."""
    fake, patched = _run(_route(findNotes={"result": None, "error": "deck was not found: 存在しない"}))
    with patched:
        with pytest.raises(AnkiError) as caught:
            anki_connect.find_notes(URL, 'deck:"存在しない"')
    assert caught.value.kind == "action"
    assert "存在しない" in str(caught.value)


def test_a_reply_that_is_not_ankiconnects_shape_is_refused_rather_than_read():
    """Something else on port 8765 answers 200 with its own JSON. Reading a `result` out of that
    would hand the caller garbage it cannot tell from real collection data."""
    fake, patched = _run(_route(deckNames={"decks": DECKS}))
    with patched:
        with pytest.raises(AnkiError) as caught:
            anki_connect.invoke("deckNames", URL)
    assert caught.value.kind == "protocol"


def test_a_reply_that_is_not_json_is_refused():
    """An HTML error page from whatever else is listening must not crash on json.loads."""
    fake, patched = _run(_route(deckNames="<html>AnkiConnect ではありません</html>".encode("utf-8")))
    with patched:
        with pytest.raises(AnkiError) as caught:
            anki_connect.invoke("deckNames", URL)
    assert caught.value.kind == "protocol"


def test_connection_refused_is_offline_and_probe_returns_it_as_data():
    """Anki closed is the most common state this client meets. It must arrive as an `AnkiError`
    (and, through `probe`, as plain data), never as a raw `ConnectionRefusedError` escaping into
    the dashboard's event loop."""
    refused = urllib.error.URLError(ConnectionRefusedError(10061, "No connection could be made"))
    fake, patched = _run(lambda payload: refused)
    with patched:
        with pytest.raises(AnkiError) as caught:
            anki_connect.invoke("deckNames", URL)
        assert caught.value.kind == "offline"
        assert "Is Anki running?" in str(caught.value)

        report = anki_connect.probe(URL)
    assert report["ok"] is False
    assert report["version"] is None
    assert "Is Anki running?" in report["error"]


def test_a_timeout_is_reported_as_offline_not_raised():
    """Anki busy on its GUI thread (a big import, a sync) looks exactly like this."""
    fake, patched = _run(lambda payload: socket.timeout("timed out"))
    with patched:
        with pytest.raises(AnkiError) as caught:
            anki_connect.notes_info(URL, [NOTE_A])
    assert caught.value.kind == "offline"


@pytest.mark.parametrize("action", ["sync", "setDueDate"])
def test_the_forbidden_actions_never_reach_the_wire(action):
    """`sync` is the user's decision alone; `setDueDate` destroys a schedule. Blocked at the choke
    point so no caller can reach either by accident."""
    fake, patched = _run(_route())
    with patched:
        with pytest.raises(AnkiError) as caught:
            anki_connect.invoke(action, URL, cards=[CARD_A])
    assert caught.value.kind == "refused"
    assert fake.requests == [], "the request must not have been sent at all"


@pytest.mark.parametrize("action", ["sync", "setDueDate"])
def test_a_forbidden_action_inside_multi_is_refused(action):
    """The gap the Junban client had: a forbidden name as a `multi` sub-action went straight to the
    wire. The whole batch is refused — including the harmless `findNotes` beside it — and so is the
    same thing hand-built through `invoke("multi", ...)` or nested one `multi` deeper."""
    fake, patched = _run(_route())
    with patched:
        with pytest.raises(AnkiError) as caught:
            anki_connect.multi([{"action": "findNotes", "params": {"query": 'deck:"TheBank"'}},
                                {"action": action, "params": {}}], URL)
        assert caught.value.kind == "refused"

        with pytest.raises(AnkiError) as caught:
            anki_connect.invoke("multi", URL, actions=[{"action": action, "version": 6}])
        assert caught.value.kind == "refused"

        nested = {"action": "multi", "params": {"actions": [{"action": action}]}}
        with pytest.raises(AnkiError) as caught:
            anki_connect.multi([nested], URL)
        assert caught.value.kind == "refused"
    assert fake.requests == []


@pytest.mark.parametrize("url", ["http://192.168.1.20:8765", "https://ankiweb.net",
                                 "http://127.0.0.1.example.com:8765", "not a url", ""])
def test_a_non_loopback_url_is_refused_before_any_request(url):
    """Surasura is offline-only (CLAUDE.md §1). A mistyped or malicious `anki_connect_url` must not
    turn this client into a new network destination — refused in code, before a socket opens."""
    fake, patched = _run(_route(deckNames=_ok(DECKS)))
    with patched:
        with pytest.raises(AnkiError) as caught:
            anki_connect.invoke("deckNames", url)
        assert caught.value.kind == "refused"
        report = anki_connect.probe(url)             # probe still never raises
    assert report["ok"] is False and report["error"]
    assert fake.requests == []


@pytest.mark.parametrize("url", ["http://127.0.0.1:8765", "http://localhost:8765",
                                 "http://LOCALHOST:8765/", "http://[::1]:8765"])
def test_every_loopback_spelling_is_accepted(url):
    """The guard must not lock out the addresses AnkiConnect really listens on."""
    assert anki_connect.is_loopback(url) is True


def test_urlopen_is_called_through_the_module_attribute():
    """Every AnkiConnect test (core and Junban) patches the global `urllib.request.urlopen`. A
    `from urllib.request import urlopen` in core would bind the real function at import and silently
    defeat every one of those patches — so the module must hold no `urlopen` of its own, and a patch
    of the global must intercept the call."""
    assert not hasattr(anki_connect, "urlopen"), "urlopen must not be bound into the module"
    fake, patched = _run(_route(version=_ok(6)))
    with patched:
        assert anki_connect.invoke("version", URL) == 6
    assert fake.actions == ["version"]


def test_importing_anki_connect_is_cheap():
    """The dashboard imports this lazily on its UI thread; it must stay a stdlib-only shell. Run in
    a CLEAN subprocess (mirroring `tests/test_lazy_imports.py`): pytest has already imported half of
    these in this process."""
    watch = ("tkinter", "pandas", "fugashi", "jieba")
    code = ("import app.anki_connect; import sys; "
            "print(','.join(m for m in %r if m in sys.modules))" % (watch,))
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"importing app.anki_connect failed:\n{result.stderr}"
    loaded = [m for m in result.stdout.strip().split(",") if m]
    assert loaded == [], f"`import app.anki_connect` eagerly loaded: {loaded}"


# --------------------------------------------------------------------------- #
# multi
# --------------------------------------------------------------------------- #
def test_every_subaction_carries_version_6():
    """A sub-action without it silently defaults to version 4 and comes back as a BARE result with
    no `{"result","error"}` wrapper. Verified live; this is why `multi()` stamps them itself."""
    fake, patched = _run(_route(multi=lambda p: _ok([_ok([NOTE_A]) for _ in p["params"]["actions"]])))
    with patched:
        replies = anki_connect.multi([{"action": "findNotes",
                                       "params": {"query": f'deck:"{deck}" -is:new'}}
                                      for deck in ("TheBank", "The Accelerator")], URL)

    assert replies == [_ok([NOTE_A]), _ok([NOTE_A])], "replies come back raw, one per sub-action"
    assert fake.requests[0]["version"] == 6, "the envelope"
    subs = fake.requests[0]["params"]["actions"]
    assert all(sub["version"] == 6 for sub in subs), "every sub-action, not just the envelope"


def test_an_empty_batch_is_never_sent():
    """Anki is single-threaded on its GUI thread; waking it for nothing is pure latency."""
    fake, patched = _run(_route())
    with patched:
        assert anki_connect.multi([], URL) == []
    assert fake.requests == []


# --------------------------------------------------------------------------- #
# probe — liveness, with an explicit capability gate
# --------------------------------------------------------------------------- #
GRANTED = _ok({"permission": "granted", "requireApikey": False, "version": 6})


def test_probe_reports_ok_and_the_version_when_the_required_actions_are_present():
    fake, patched = _run(_route(
        requestPermission=GRANTED,
        apiReflect=_ok({"scopes": ["actions"], "actions": ["findNotes", "notesInfo"]}),
    ))
    with patched:
        report = anki_connect.probe(URL, required=("findNotes", "notesInfo"))

    assert report == {"ok": True, "version": 6, "missing": [], "error": ""}
    assert "version" not in fake.actions, "requestPermission already carries it — don't ask twice"
    assert fake.requests[-1]["params"]["actions"] == ["findNotes", "notesInfo"]


def test_probe_reports_a_missing_required_action():
    """An AnkiConnect too old to expose what the caller needs must be named up front."""
    fake, patched = _run(_route(
        requestPermission=GRANTED,
        apiReflect=_ok({"scopes": ["actions"], "actions": ["findNotes"]}),
    ))
    with patched:
        report = anki_connect.probe(URL, required=("findNotes", "notesInfo"))

    assert report["ok"] is False
    assert report["missing"] == ["notesInfo"]
    assert "notesInfo" in report["error"]


def test_probe_with_nothing_required_does_not_ask_apireflect():
    """The default gate is liveness only; asking for capabilities nobody needs is wasted latency."""
    fake, patched = _run(_route(requestPermission=GRANTED))
    with patched:
        report = anki_connect.probe(URL)
    assert report == {"ok": True, "version": 6, "missing": [], "error": ""}
    assert fake.actions == ["requestPermission"]


def test_probe_reports_a_refused_permission_instead_of_claiming_ok():
    """AnkiConnect can be showing a modal permission prompt behind Anki's window; the user needs to
    be told to accept it."""
    fake, patched = _run(_route(requestPermission=_ok({"permission": "denied", "version": 6})))
    with patched:
        report = anki_connect.probe(URL, required=("findNotes",))

    assert report["ok"] is False
    assert "permission" in report["error"].lower()
    assert "apiReflect" not in fake.actions, "no point probing capability we may not use"


def test_probe_survives_an_ankiconnect_without_apireflect():
    """apiReflect itself is version-dependent. Its absence means we cannot prove capability, so the
    answer is a plain not-ok — never an exception out of a liveness check."""
    fake, patched = _run(_route(
        requestPermission=_ok({"permission": "granted", "version": 6}),
        apiReflect={"result": None, "error": "unsupported action"},
    ))
    with patched:
        report = anki_connect.probe(URL, required=("findNotes",))
    assert report["ok"] is False
    assert report["error"]


# --------------------------------------------------------------------------- #
# Reading the collection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("finder, action", [(anki_connect.find_cards, "findCards"),
                                            (anki_connect.find_notes, "findNotes")])
def test_find_returns_ints_and_ignores_junk(finder, action):
    """Ids are what callers key on; a non-numeric one is not worth failing a run over, but it must
    never be passed along as a string either."""
    fake, patched = _run(_route(**{action: _ok([CARD_A, str(CARD_B), None, "不明"])}))
    with patched:
        found = finder(URL, 'deck:"TheBank" -is:new -is:suspended')
    assert found == [CARD_A, CARD_B]
    assert all(isinstance(value, int) for value in found)
    assert fake.requests[0]["params"] == {"query": 'deck:"TheBank" -is:new -is:suspended'}


def test_deck_names_returns_strings_in_ankis_order():
    fake, patched = _run(_route(deckNames=_ok(DECKS + ["日本語::文法"])))
    with patched:
        assert anki_connect.deck_names(URL) == DECKS + ["日本語::文法"]


def test_notes_info_chunks_and_concatenates_in_order(ja_sentences):
    """One huge request blocks Anki's Qt GUI thread with no progress and no cancel. Real Japanese
    sentences ride along in the fields so the round trip is exercised with non-ASCII payloads."""
    ids = list(range(NOTE_A, NOTE_A + 7))

    def info(payload):
        return _ok([{"noteId": note, "modelName": "Lapis",
                     "fields": {"Expression": {"value": "冒険", "order": 0},
                                "Sentence": {"value": ja_sentences[index], "order": 1}}}
                    for index, note in enumerate(payload["params"]["notes"])])

    fake, patched = _run(_route(notesInfo=info))
    with patched:
        notes = anki_connect.notes_info(URL, ids, chunk=3)

    assert [request["params"]["notes"] for request in fake.requests] == [ids[0:3], ids[3:6], ids[6:7]]
    assert [note["noteId"] for note in notes] == ids, "order preserved across chunks"
    assert notes[0]["fields"]["Sentence"]["value"] == ja_sentences[0]


def test_cards_info_drops_ids_anki_no_longer_knows():
    """A deleted card comes back as an empty dict. Dropping it here means no caller has to guard a
    missing `cardId`."""
    fake, patched = _run(_route(cardsInfo=_ok([
        {"cardId": CARD_A, "type": 2, "queue": 2, "note": NOTE_A, "deckName": "TheBank"},
        {},
    ])))
    with patched:
        cards = anki_connect.cards_info(URL, [CARD_A, CARD_B])
    assert [card["cardId"] for card in cards] == [CARD_A]
    assert fake.requests[0]["params"] == {"cards": [CARD_A, CARD_B]}


def test_info_asks_nothing_when_there_are_no_usable_ids():
    """No ids (or only junk ids) must not produce a request."""
    fake, patched = _run(_route())
    with patched:
        assert anki_connect.notes_info(URL, []) == []
        assert anki_connect.cards_info(URL, ["不明", None]) == []
    assert fake.requests == []


def test_a_deck_name_with_quotes_and_backslashes_is_escaped():
    """Anki deck names really do contain quotes and backslashes; an unescaped one silently searches
    something else entirely."""
    assert anki_connect.escape_query('TheBank "2026"') == 'TheBank \\"2026\\"'
    assert anki_connect.escape_query("語彙\\N5") == "語彙\\\\N5"
    assert anki_connect.escape_query("日本語::文法") == "日本語::文法"
