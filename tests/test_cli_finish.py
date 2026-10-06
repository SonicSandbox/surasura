"""`surasura-cli finish` (P2.1 row 2.1.3): held to Surasura 3.0 in 2.x (✅ P2.1-1); in 3.0 it moves an item to
*Finished* and changes no known word and no card (✅ Q2-5, Q2-6).

What a wrong answer would cost: through 2.x the window's Graduate marks an item's words known, so a `finish` that
behaved like it would mark words known behind the user's back — and one that didn't would make "finished" mean two
things in one version. In 3.0 a finish that touched KnownWord.json or Anki would undo learning the user never asked to
undo. Real files, the test's own root; Anki is a fake that records any call.
"""
import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _known():
    path = os.path.join(c.dirs()[1], "KnownWord.json")
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.fixture
def fake_anki():
    """An AnkiConnect on loopback that answers and records every request."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"result": None, "error": None}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", calls
    server.shutdown()
    server.server_close()


def test_in_2x_finish_is_held_to_3_0_and_writes_nothing():
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
    stored, known = c.store_state(), _known()
    code, line = h.call("finish", "--file", str(item), "--source", "test")
    assert (code, line["code"]) == (2, "usage") and "3.0" in line["message"]
    assert c.store_state() == stored and _known() == known


def test_in_3_0_finish_moves_to_finished_and_changes_no_known_word_and_no_card(fake_anki):
    address, calls = fake_anki
    c.library(arrivals=True, anki_connect_url=address)
    with c.store() as s:
        s.register_reader("connect")
        item = s.ids("now")[0]
    known = _known()
    graduated = os.path.join(c.dirs()[1], "GraduatedList.txt")
    code, line = h.call("finish", "--file", str(item), "--source", "test")
    assert code == 0 and (line["tier"], line["finished"]) == ("graduated", True), line
    assert _known() == known, "KnownWord.json byte-identical"
    assert not os.path.exists(graduated), "no word list written"
    assert calls == [], "Anki never asked anything"
    with c.store() as s:
        assert item in s.ids("graduated")
        assert (item, "finished", "test") in c.events(s), "the event says who finished it"
    code, again = h.call("finish", "--file", str(item), "--source", "test")
    assert code == 0 and again["finished"] is False


def test_in_3_0_an_unknown_item_is_bad_data():
    c.library(arrivals=True)
    code, line = h.call("finish", "--file", "999999", "--source", "test")
    assert (code, line["code"]) == (1, "bad-data")
