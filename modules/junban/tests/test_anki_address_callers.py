# SPDX-License-Identifier: GPL-3.0-or-later
"""Every Junban caller reaches the one AnkiConnect address (E1.4 §A), set either way.

2.x read `junban_url` here and `anki_connect_url` in the Anki sync: a hand edit of one split them. Now
every caller asks `anki_connect.address(settings)`, so a second AnkiConnect on another loopback port
is reached by the 順 window's two reads, a reorder, a fill and the automatic step — set through the
one key, and (a 2.x settings.json edited by hand) through `junban_url` alone.

The address rule itself, the dashboard's reads and the source guard: `tests/test_anki_address.py`.
"""
from unittest import mock

import pytest

from modules.junban import auto, backfill, reposition
from modules.junban.gui import JunbanGui
from modules.junban.tests.test_backfill import _Session, _fake, _lapis
from modules.junban.tests.test_backfill import _settings as _fill_settings
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, FakeCollection, _collection,
                                                  _results, _settings)

CUSTOM = "http://127.0.0.1:18765"


class _Where:
    """The fake collection behind `urlopen`, noting the address of every request."""

    def __init__(self, fake):
        self.fake = fake
        self.urls = []

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        return self.fake(request, timeout)


@pytest.fixture(params=["anki_connect_url", "junban_url"])
def address(request):
    """The custom port, set only through this key (the other left at the default)."""
    other = {"anki_connect_url": "junban_url", "junban_url": "anki_connect_url"}[request.param]
    return {request.param: CUSTOM, other: "http://127.0.0.1:8765"}


def _run(fake, call):
    where = _Where(fake)
    with mock.patch("urllib.request.urlopen", where):
        result = call()
    assert where.urls and set(where.urls) == {CUSTOM}
    return result


def _backlog(tmp_path):
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "散歩", "図書館", "冒険"])
    return FakeCollection(cards, notes, actions=("setSpecificValueOfCard", "multi", "suspend", "unsuspend"))


def test_the_junban_windows_two_reads(tmp_path, address):
    fake = _backlog(tmp_path)
    panel = mock.MagicMock()
    panel._settings.return_value = _settings(junban_order="content", **address)
    _run(fake, lambda: JunbanGui._probe_worker(panel))
    connection = [call.args[0] for call in panel.q.put.call_args_list if call.args[0][0] == "__CONN__"]
    assert connection[0][1]["ok"] and connection[0][2] == ["TheBank"]
    counts = _run(fake, lambda: JunbanGui._context_counts(panel._settings(), ["TheBank"]))
    assert set(counts) == {"context_review", "context_suspended"}     # both counts answered


def test_a_reorder_and_a_restore(tmp_path, address):
    fake = _backlog(tmp_path)
    settings = _settings(junban_order="content", **address)
    assert _run(fake, lambda: reposition.run(settings))["written"]
    assert _run(fake, lambda: reposition.restore(settings))["ok"]


def test_a_fill_and_its_restore(address):
    fake = _fake(_lapis(0, "探検", "たんけん"))
    settings = _fill_settings(**address)
    assert _run(fake, lambda: backfill.run(settings, _Session()))["written"]
    assert _run(fake, lambda: backfill.restore(settings))["ok"]


def test_the_automatic_step(tmp_path, address):
    fake = _backlog(tmp_path)
    message = _run(fake, lambda: auto.run_quietly(_settings(junban_order="content", junban_auto_reorder=True,
                                                            **address)))
    # 2.x-dev keeps .startswith("順 (automatic): Reordered") (no job: 2.5's dense run); 3.0 (W3.5 row 7): spaced
    # always, whose first run says it spaced the cards out once, then "Reordered N cards."
    assert message.startswith("順 (automatic): ") and "Reordered" in message, message
    fake = _fake(_lapis(0, "探検", "たんけん"))
    fake.actions = ["setSpecificValueOfCard", "updateNoteFields", "multi"]
    with mock.patch.object(backfill, "Session", lambda settings: _Session()), \
            mock.patch.object(backfill, "rebuild_in_background", lambda *a, **k: None):
        message = _run(fake, lambda: auto.run_quietly(_fill_settings(enable_junban=True, junban_auto_backfill=True,
                                                                     **address)))
    assert message == "Backfill (automatic): Filled 1 note."
