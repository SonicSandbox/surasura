# SPDX-License-Identifier: GPL-3.0-or-later
"""The AnkiConnect wire, against a mocked `urlopen` — never a live collection.

**No test here may touch Anki.** The developer's real collection lives on this machine and
`The Accelerator` (777 real review cards) and `Migaku Reference` (2,046 suspended) are read-only,
always (spec §18.0 rule 6). Every request is intercepted by `FakeAnki`, which records the exact
bytes that would have gone over the wire — which is the point: most of the failure modes this
module exists to survive are *shapes*, not exceptions.

Each of the following was reproduced live once, and is pinned here so it cannot regress:

  * a sub-action without `"version": 6` silently answers as version 4;
  * a `str` `due` fails inside AnkiConnect with `error: null` and leaves the old position;
  * success is `[True]` once per call, not `[true, true]` per key;
  * a validation failure is a bare `false` with `error: null` — invisible to an `error`-only check.

Decided against plain data throughout, never against a reply's truthiness: `FakeAnki` returns real
JSON bytes, so everything downstream of `json.loads` is a plain dict or list and no `MagicMock` can
fake its way through a branch (`testing.md` §5.3).
"""
import json
import socket
import urllib.error
from unittest import mock

import pytest

from modules.junban import ankiconnect
from modules.junban.ankiconnect import AnkiError

# Real identifiers from the verified 2026-09-17 proof-of-concept run on TheBank, so the fixtures
# have the shape and magnitude of genuine Anki data rather than 1/2/3.
CARD_A, DUE_A = 1789712080047, 2944
CARD_B, DUE_B = 1789711432547, 2832
CARD_C, DUE_C = 1789711433474, 2833

URL = "http://127.0.0.1:8765"

# The writers here are called directly, so the test holds the Anki-write lock itself (E1.4 §W).
pytestmark = pytest.mark.usefixtures("anki_writer")

# Real decks on the reference collection. Default is empty and Migaku Reference is entirely
# suspended — both must be filtered out of the "all decks" offer (spec §15 #3).
DECKS = ["Default", "TheBank", "The Accelerator", "Migaku Reference"]

# The word that proved the orthBase problem: anki_miner's card says お伽話, UniDic's lemma is 御伽話.
WORD_ORTH, WORD_LEMMA = "お伽話", "御伽話"


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
        self.requests = []          # parsed envelopes, in order
        self.headers = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        self.requests.append(payload)
        self.headers.append({name.lower(): value for name, value in request.header_items()})
        self.timeouts.append(timeout)
        reply = self.handler(payload)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, bytes):
            return _FakeResponse(reply)
        return _FakeResponse(json.dumps(reply, ensure_ascii=False).encode("utf-8"))

    @property
    def actions(self):
        return [request["action"] for request in self.requests]

    def sub_actions(self, index=0):
        """The `multi` sub-actions of the `index`-th request that was a `multi`."""
        multis = [r for r in self.requests if r["action"] == "multi"]
        return multis[index]["params"]["actions"]


def _ok(result):
    return {"result": result, "error": None}


def _route(**answers):
    """Answer by action name. Values are envelopes, callables taking the payload, or Exceptions."""
    def handler(payload):
        answer = answers.get(payload["action"], _ok(None))
        return answer(payload) if callable(answer) else answer
    return handler


def _all_written(payload):
    """A healthy `multi` of writes: `[True]` per sub-action, exactly as the live run returned."""
    return _ok([{"result": [True], "error": None} for _ in payload["params"]["actions"]])


def _run(handler):
    """Patch `urlopen` with a FakeAnki for the duration of a `with` block."""
    fake = FakeAnki(handler)
    return fake, mock.patch("urllib.request.urlopen", fake)


# --------------------------------------------------------------------------- #
# One request: the envelope
# --------------------------------------------------------------------------- #
def test_the_envelope_carries_version_6_and_sends_no_origin_header():
    """Version 6 is what produces the `{"result","error"}` wrapper at all; the *absence* of an
    Origin header is what stops AnkiConnect showing a permission prompt on every single run."""
    fake, patched = _run(_route(deckNames=_ok(DECKS)))
    with patched:
        assert ankiconnect.invoke("deckNames", URL) == DECKS

    assert fake.requests[0]["version"] == 6
    assert fake.requests[0]["params"] == {}
    assert "origin" not in fake.headers[0], "an Origin header re-introduces the permission prompt"
    assert fake.headers[0]["content-type"] == "application/json"


def test_an_error_field_becomes_an_ankierror():
    """The ordinary refusal path — a deck that does not exist, a malformed search."""
    fake, patched = _run(_route(getDeckConfig={"result": None, "error": "deck was not found: 存在しない"}))
    with patched:
        with pytest.raises(AnkiError) as caught:
            ankiconnect.deck_config(URL, "存在しない")
    assert caught.value.kind == "action"
    assert "存在しない" in str(caught.value)


def test_a_reply_that_is_not_ankiconnects_shape_is_refused_rather_than_read():
    """Something else on port 8765 (a dev server, a proxy) answers 200 with its own JSON. Reading a
    `result` out of that would hand the planner garbage it cannot tell from real card data."""
    fake, patched = _run(_route(deckNames={"decks": DECKS}))
    with patched:
        with pytest.raises(AnkiError) as caught:
            ankiconnect.invoke("deckNames", URL)
    assert caught.value.kind == "protocol"


def test_a_reply_that_is_not_json_is_refused():
    """An HTML error page from whatever else is listening must not crash on json.loads."""
    fake, patched = _run(_route(deckNames=b"<html>Not AnkiConnect</html>"))
    with patched:
        with pytest.raises(AnkiError) as caught:
            ankiconnect.invoke("deckNames", URL)
    assert caught.value.kind == "protocol"


def test_connection_refused_degrades_to_error_not_raise():
    """Anki closed is the single most common state this module meets. It must arrive as an
    `AnkiError` the panel can render (and, through `probe`, as plain data), never as a raw
    `ConnectionRefusedError` escaping into the dashboard's event loop."""
    refused = urllib.error.URLError(ConnectionRefusedError(10061, "No connection could be made"))

    fake, patched = _run(lambda payload: refused)
    with patched:
        with pytest.raises(AnkiError) as caught:
            ankiconnect.invoke("deckNames", URL)
        assert caught.value.kind == "offline"
        assert "Is Anki running?" in str(caught.value)

        report = ankiconnect.probe(URL)             # the panel's own path: data, not an exception
    assert report["ok"] is False
    assert report["version"] is None
    assert "Is Anki running?" in report["error"]


def test_a_timeout_is_reported_as_offline_not_raised():
    """Anki busy on its GUI thread (a big import, a sync) looks exactly like this."""
    fake, patched = _run(lambda payload: socket.timeout("timed out"))
    with patched:
        with pytest.raises(AnkiError) as caught:
            ankiconnect.cards_info(URL, [CARD_A])
    assert caught.value.kind == "offline"


@pytest.mark.parametrize("action", ["sync", "setDueDate"])
def test_the_forbidden_actions_never_reach_the_wire(action):
    """`sync` is the user's decision alone; `setDueDate` converts a new card into a review card,
    destroying the schedule this feature promises never to touch. Blocked at the choke point so no
    later work package can reach either by accident."""
    fake, patched = _run(_route())
    with patched:
        with pytest.raises(AnkiError) as caught:
            ankiconnect.invoke(action, URL, cards=[CARD_A])
    assert caught.value.kind == "refused"
    assert fake.requests == [], "the request must not have been sent at all"


# --------------------------------------------------------------------------- #
# multi
# --------------------------------------------------------------------------- #
def test_every_subaction_carries_version_6():
    """A sub-action without it silently defaults to version 4 and comes back as a BARE result with
    no `{"result","error"}` wrapper — so every success check below would be reading a key that was
    never sent. Verified live; this is the reason `multi()` stamps them itself."""
    fake, patched = _run(_route(multi=_all_written))
    with patched:
        ankiconnect.set_due(URL, [(CARD_A, DUE_A), (CARD_B, DUE_B)])

    assert fake.requests[0]["version"] == 6, "the envelope"
    subs = fake.sub_actions()
    assert len(subs) == 2
    assert all(sub["version"] == 6 for sub in subs), "every sub-action, not just the envelope"


def test_an_empty_batch_is_never_sent():
    """Anki is single-threaded on its GUI thread; waking it for nothing is pure latency."""
    fake, patched = _run(_route())
    with patched:
        assert ankiconnect.multi([], URL) == []
    assert fake.requests == []


# --------------------------------------------------------------------------- #
# probe — the capability gate
# --------------------------------------------------------------------------- #
def test_missing_action_is_reported_by_probe():
    """`setSpecificValueOfCard` is the whole feature. An AnkiConnect too old to expose it cannot be
    worked around, so the panel must say so on open rather than at the moment of writing."""
    fake, patched = _run(_route(
        requestPermission=_ok({"permission": "granted", "requireApikey": False, "version": 6}),
        apiReflect=_ok({"scopes": ["actions"], "actions": ["multi"]}),   # the other one is absent
    ))
    with patched:
        report = ankiconnect.probe(URL)

    assert report["ok"] is False
    assert report["missing"] == ["setSpecificValueOfCard"]
    assert "setSpecificValueOfCard" in report["error"]


def test_probe_reports_ok_and_the_version_when_both_actions_are_present():
    fake, patched = _run(_route(
        requestPermission=_ok({"permission": "granted", "requireApikey": False, "version": 6}),
        apiReflect=_ok({"scopes": ["actions"],
                        "actions": ["setSpecificValueOfCard", "multi"]}),
    ))
    with patched:
        report = ankiconnect.probe(URL)

    assert report == {"ok": True, "version": 6, "missing": [], "error": ""}
    assert "version" not in fake.actions, "requestPermission already carries it — don't ask twice"


def test_probe_reports_a_refused_permission_instead_of_claiming_ok():
    """AnkiConnect can be showing a modal permission prompt behind Anki's window; the user needs to
    be told to accept it, not to watch a reorder do nothing."""
    fake, patched = _run(_route(
        requestPermission=_ok({"permission": "denied", "version": 6}),
    ))
    with patched:
        report = ankiconnect.probe(URL)

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
        report = ankiconnect.probe(URL)
    assert report["ok"] is False
    assert report["error"]


# --------------------------------------------------------------------------- #
# Reading the collection
# --------------------------------------------------------------------------- #
def test_deck_names_with_new_filters_to_decks_that_have_unsuspended_new_cards():
    """On the reference collection this hides `Default` (empty) and `Migaku Reference` (2,046 cards,
    every one suspended). Offering either as a reorder target offers a no-op."""
    def survey(payload):
        found = {
            'deck:"TheBank" is:new -is:suspended -deck:filtered': [CARD_A, CARD_B, CARD_C],
            'deck:"The Accelerator" is:new -is:suspended -deck:filtered': [CARD_A],
            'deck:"Default" is:new -is:suspended -deck:filtered': [],
            'deck:"Migaku Reference" is:new -is:suspended -deck:filtered': [],
        }
        return _ok([_ok(found[sub["params"]["query"]]) for sub in payload["params"]["actions"]])

    fake, patched = _run(_route(deckNames=_ok(DECKS), multi=survey))
    with patched:
        assert ankiconnect.deck_names_with_new(URL) == ["TheBank", "The Accelerator"]

    assert fake.actions == ["deckNames", "multi"], "one survey request, not one per deck"


def test_a_deck_whose_search_errored_is_not_offered():
    """A per-sub-action error is not evidence of new cards. Decided on the parsed reply's `error`
    key, never on the reply's truthiness (`testing.md` §5.3)."""
    def survey(payload):
        return _ok([_ok([CARD_A]),
                    {"result": None, "error": "Invalid search"},
                    _ok([]), _ok([])])

    fake, patched = _run(_route(deckNames=_ok(DECKS), multi=survey))
    with patched:
        assert ankiconnect.deck_names_with_new(URL) == ["Default"]


def test_a_deck_name_with_a_quote_is_escaped_in_the_query():
    """Anki deck names really do contain quotes and backslashes; an unescaped one silently searches
    something else entirely — and a search that matches the wrong deck would reorder the wrong deck."""
    query = ankiconnect.new_card_query('TheBank "2026"')
    assert query == 'deck:"TheBank \\"2026\\"" is:new -is:suspended -deck:filtered'
    assert ankiconnect.new_card_query("日本語::文法").startswith('deck:"日本語::文法"')


def test_deck_config_surfaces_a_random_new_order_rather_than_swallowing_it():
    """`new.order == 0` means Anki ignores card positions outright, so the whole feature is a no-op
    in that deck. Preflight (WP-G) reads it from here; the transport must pass it through intact."""
    config = {"name": "Default", "new": {"order": 0, "perDay": 20}, "id": 1}
    fake, patched = _run(_route(getDeckConfig=_ok(config)))
    with patched:
        assert ankiconnect.deck_config(URL, "TheBank")["new"]["order"] == 0
    assert fake.requests[0]["params"] == {"deck": "TheBank"}


def test_find_new_cards_returns_ints_and_ignores_junk():
    """Card ids are the write target; a non-numeric one is not worth failing a whole run over, but
    it must never be passed along as a string either."""
    fake, patched = _run(_route(findCards=_ok([CARD_A, str(CARD_B), None, "不明"])))
    with patched:
        found = ankiconnect.find_new_cards(URL, ankiconnect.new_card_query("TheBank"))
    assert found == [CARD_A, CARD_B]
    assert all(isinstance(value, int) for value in found)


def test_cards_info_chunks_and_concatenates_in_order():
    """One 5,000-card request blocks Anki's Qt GUI thread with no progress and no cancel."""
    ids = list(range(1789712080000, 1789712080000 + 7))

    def info(payload):
        return _ok([{"cardId": card, "due": 2900 + index, "type": 0, "queue": 0,
                     "note": card - 1, "deckName": "TheBank"}
                    for index, card in enumerate(payload["params"]["cards"])])

    fake, patched = _run(_route(cardsInfo=info))
    with patched:
        cards = ankiconnect.cards_info(URL, ids, chunk=3)

    assert [request["params"]["cards"] for request in fake.requests] == [ids[0:3], ids[3:6], ids[6:7]]
    assert [card["cardId"] for card in cards] == ids, "order preserved across chunks"


def test_cards_info_drops_ids_anki_no_longer_knows():
    """A deleted card comes back as an empty dict. Dropping it here means the planner never has to
    guard a missing `cardId`."""
    fake, patched = _run(_route(cardsInfo=_ok([
        {"cardId": CARD_A, "due": DUE_A, "type": 0, "queue": 0, "note": CARD_A - 1},
        {},
    ])))
    with patched:
        cards = ankiconnect.cards_info(URL, [CARD_A, CARD_B])
    assert [card["cardId"] for card in cards] == [CARD_A]


def test_notes_info_carries_real_fields_and_asks_nothing_when_there_are_no_ids(ja_sentences):
    """Real note shapes: a Lapis note whose Expression is お伽話 (the word that only ever matches via
    the orth column) with a genuine Japanese sentence behind it."""
    note = {"noteId": CARD_A - 1, "modelName": "Lapis",
            "fields": {"Expression": {"value": WORD_ORTH, "order": 0},
                       "Sentence": {"value": ja_sentences[0], "order": 1}}}
    fake, patched = _run(_route(notesInfo=_ok([note])))
    with patched:
        notes = ankiconnect.notes_info(URL, [CARD_A - 1])
        assert notes[0]["fields"]["Expression"]["value"] == WORD_ORTH
        assert ankiconnect.notes_info(URL, []) == []

    assert len(fake.requests) == 1, "an empty id list must not produce a request"


# --------------------------------------------------------------------------- #
# Writing — the failure modes that cost data
# --------------------------------------------------------------------------- #
def test_due_is_sent_as_int_not_string():
    """The one verified silent no-op: a `str` newValue raises INSIDE AnkiConnect, comes back as
    `[[False, "'str' object cannot be interpreted as an integer"]]` with `error: null`, and LEAVES
    THE OLD POSITION IN PLACE. `set_due` coerces, so even a caller handing over text writes an int."""
    fake, patched = _run(_route(multi=_all_written))
    with patched:
        written, failures = ankiconnect.set_due(URL, [(CARD_A, DUE_A), (str(CARD_B), str(DUE_B))])

    assert (written, failures) == ([CARD_A, CARD_B], [])
    for sub, expected in zip(fake.sub_actions(), [DUE_A, DUE_B]):
        value = sub["params"]["newValues"][0]
        assert value == expected
        assert isinstance(value, int) and not isinstance(value, bool), f"{value!r} went out as text"
        assert isinstance(sub["params"]["card"], int)


def test_a_due_that_is_not_a_number_never_reaches_the_wire():
    """A word where a position should be (a column read by name that moved) must be reported, not
    posted — sending it would be the silent no-op above."""
    fake, patched = _run(_route(multi=_all_written))
    with patched:
        written, failures = ankiconnect.set_due(URL, [(CARD_A, WORD_LEMMA)])

    assert written == []
    assert failures[0][0] == CARD_A and WORD_LEMMA in failures[0][1]
    assert fake.requests == []


def test_result_true_appended_once_not_per_key():
    """`setSpecificValueOfCard` appends `True` once per CALL, not once per key — the README's
    documented `[true, true]` is wrong, and a client expecting one `True` per key would report every
    successful single-key write as a partial failure."""
    fake, patched = _run(_route(multi=lambda payload: _ok([{"result": [True], "error": None}])))
    with patched:
        written, failures = ankiconnect.set_due(URL, [(CARD_A, DUE_A)])

    assert (written, failures) == ([CARD_A], []), "[True] is a complete success"
    keys = fake.sub_actions()[0]["params"]["keys"]
    assert keys == ["due"], "only `due` is ever written — never queue/type/ivl (restricted keys)"
    assert len(fake.sub_actions()[0]["params"]["newValues"]) == len(keys)


def test_bare_false_result_is_treated_as_failure():
    """The silent no-op. `error` is null and `result` is a bare `false`; a client checking only
    `error` would tell the user their backlog was reordered when nothing moved at all."""
    fake, patched = _run(_route(multi=lambda payload: _ok([{"result": False, "error": None}])))
    with patched:
        written, failures = ankiconnect.set_due(URL, [(CARD_A, DUE_A)])

    assert written == []
    assert [card for card, _reason in failures] == [CARD_A]


def test_a_rejection_body_is_reported_with_ankis_own_message():
    """The `[[False, msg]]` shape — again with `error: null`. Anki's own words are the most useful
    thing we can show, so they must survive into the failure list."""
    message = "'str' object cannot be interpreted as an integer"
    fake, patched = _run(_route(
        multi=lambda payload: _ok([{"result": [[False, message]], "error": None}])))
    with patched:
        written, failures = ankiconnect.set_due(URL, [(CARD_A, DUE_A)])

    assert written == []
    assert failures == [(CARD_A, message)]


def test_chunking_splits_at_configured_size():
    """~150 per `multi`: AnkiConnect runs on Anki's Qt GUI thread with a 25 ms poll, so one huge
    batch freezes Anki with no progress bar, no cancel and no partial-progress checkpoint."""
    pairs = [(1789712080000 + index, 2900 + index) for index in range(7)]

    fake, patched = _run(_route(multi=_all_written))
    with patched:
        written, failures = ankiconnect.set_due(URL, pairs, chunk=3)

    assert failures == []
    assert written == [card for card, _due in pairs]
    sizes = [len(request["params"]["actions"]) for request in fake.requests]
    assert sizes == [3, 3, 1]


def test_partial_failure_reports_the_card_ids():
    """A mixed batch must name the cards that did not move — a bare count leaves the user with no
    way to tell which positions are now inconsistent with the preview they approved."""
    def mixed(payload):
        return _ok([{"result": [True], "error": None},
                    {"result": False, "error": None},
                    {"result": None, "error": "card was not found: 1789711433474"}])

    fake, patched = _run(_route(multi=mixed))
    with patched:
        written, failures = ankiconnect.set_due(
            URL, [(CARD_A, DUE_A), (CARD_B, DUE_B), (CARD_C, DUE_C)])

    assert written == [CARD_A]
    assert [card for card, _reason in failures] == [CARD_B, CARD_C]
    assert "not found" in dict(failures)[CARD_C]


def test_a_mid_run_transport_failure_reports_partial_progress_and_does_not_raise():
    """Anki quit (or the user closed the profile) halfway through. The snapshot is the only undo
    there is, so a half-written run has to be *describable*: everything already written, and every
    card that never made it, named."""
    pairs = [(1789712080000 + index, 2900 + index) for index in range(6)]
    calls = {"n": 0}

    def dies_after_the_first_chunk(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            return _all_written(payload)
        return urllib.error.URLError(ConnectionRefusedError(10061, "No connection could be made"))

    fake, patched = _run(_route(multi=dies_after_the_first_chunk))
    with patched:
        written, failures = ankiconnect.set_due(URL, pairs, chunk=2)

    assert written == [pairs[0][0], pairs[1][0]]
    assert [card for card, _reason in failures] == [card for card, _due in pairs[2:]]
    assert all("Is Anki running?" in reason for _card, reason in failures)
    assert calls["n"] == 2, "stop talking to a dead socket rather than hammering it per chunk"


def test_progress_is_reported_per_chunk_as_determinate_counts():
    """The panel's progress bar is determinate because the count is known up front."""
    pairs = [(1789712080000 + index, 2900 + index) for index in range(5)]
    seen = []

    fake, patched = _run(_route(multi=_all_written))
    with patched:
        ankiconnect.set_due(URL, pairs, chunk=2, progress=lambda done, total: seen.append((done, total)))

    assert seen == [(2, 5), (4, 5), (5, 5)]


def test_a_broken_progress_callback_cannot_abandon_a_half_written_run():
    """A dead Tk widget raising from the callback must not leave the collection half-reordered with
    no report — the write loop owns the undo contract, not the progress bar."""
    pairs = [(1789712080000 + index, 2900 + index) for index in range(4)]

    def explode(done, total):
        raise RuntimeError("invalid command name .!junban.!progress")

    fake, patched = _run(_route(multi=_all_written))
    with patched:
        written, failures = ankiconnect.set_due(URL, pairs, chunk=2, progress=explode)

    assert written == [card for card, _due in pairs]
    assert failures == []


def test_nothing_is_written_for_an_empty_plan():
    """The idempotence case: a second run right after a first plans zero writes, and that must cost
    zero requests rather than an empty `multi`."""
    fake, patched = _run(_route(multi=_all_written))
    with patched:
        assert ankiconnect.set_due(URL, []) == ([], [])
    assert fake.requests == []
