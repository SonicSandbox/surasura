# SPDX-License-Identifier: GPL-3.0-or-later
"""Uncontended, every Anki writer sends exactly the requests it sent before the Anki-write lock (E1.4).

The lock adds a wait and nothing else (ORDER :412). This file holds the proof: the full request log
the fake AnkiConnect sees for a reorder, a restore, a fill, a fill's restore and the automatic step,
compared envelope by envelope with the logs recorded from 2.x-dev's code **before** E1.4 changed
anything (row E1.4.0, `golden/request_logs/`). A lock that sent one more `guiReviewActive`, dropped a
probe or reordered two writes fails here.

Recording again (row E1.4.8, from the rebased base without E1.4, in a scratch checkout):
`SURASURA_RECORD_REQUEST_LOGS=1 python -m pytest modules/junban/tests/test_request_logs.py`.

Against the same FakeCollection as the engine's own tests: real Japanese words, never a live Anki.
"""
import json
import os
from unittest import mock

import pytest

from modules.junban import auto, backfill, reposition
from modules.junban.tests.test_backfill import _Session, _fake, _lapis
from modules.junban.tests.test_backfill import _settings as _fill_settings
from modules.junban.tests.test_reposition import (_JOURNEY, _LIBRARY, FakeCollection, _collection,
                                                  _patched, _results, _settings)

_GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden", "request_logs")
_RECORD = os.environ.get("SURASURA_RECORD_REQUEST_LOGS") == "1"
_ACTIONS = ("setSpecificValueOfCard", "multi", "suspend", "unsuspend")


def _check(name, requests):
    """Compare `requests` with the recorded log `name`, or record it when asked to."""
    path = os.path.join(_GOLDEN, name + ".json")
    if _RECORD:
        os.makedirs(_GOLDEN, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(requests, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        return
    with open(path, "r", encoding="utf-8") as handle:
        recorded = json.load(handle)
    assert len(requests) == len(recorded), f"{name}: {len(requests)} requests, recorded {len(recorded)}"
    for index, (sent, before) in enumerate(zip(requests, recorded)):
        assert sent == before, f"{name}: request {index} differs"


def _as_before_ft(requests):
    """FT (K1, on purpose): a writing run with no card map now reads the open profile once (its first-touch journal
    lines carry it) — the one request these logs never held. Everything else is compared as recorded."""
    return [request for request in requests if request.get("action") != "getActiveProfile"]


def _backlog(tmp_path):
    """冒険 / 散歩 on the list, 須藤 / 図書館 not, in the wrong order: a reorder with every §13 action."""
    _results(tmp_path, progressive=_JOURNEY, library=_LIBRARY, floor=11)
    cards, notes, _ = _collection(["須藤", "散歩", "図書館", "冒険"])
    return FakeCollection(cards, notes, actions=_ACTIONS)


def _reorder_settings(**over):
    return _settings(junban_order="content", junban_later_tag=True, junban_later_flag=True,
                     junban_later_suspend=True, **over)


def test_a_reorder_and_its_restore_send_what_they_sent_before_the_lock(tmp_path):
    fake = _backlog(tmp_path)
    with _patched(fake):
        report = reposition.run(_reorder_settings())
    assert report["ok"] and report["written"]
    _check("reorder", _as_before_ft(fake.requests))

    fake.requests.clear()
    with _patched(fake):
        restored = reposition.restore(_reorder_settings())
    assert restored["ok"]
    _check("restore", _as_before_ft(fake.requests))


def test_a_fill_and_its_restore_send_what_they_sent_before_the_lock():
    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"), _lapis(2, "囲む", "かこむ"))
    with _patched(fake):
        report = backfill.run(_fill_settings(), _Session())
    assert report["ok"] and len(report["written"]) == 3
    _check("fill", _as_before_ft(fake.requests))

    fake.requests.clear()
    with _patched(fake):
        restored = backfill.restore(_fill_settings())
    assert restored["ok"] and len(restored["written"]) == 3
    _check("fill_restore", _as_before_ft(fake.requests))


def test_the_automatic_step_sends_what_it_sent_before_the_lock(tmp_path):
    # Both halves: the reorder (every saved action on) on Junban's fake, then the Backfill on its own.
    fake = _backlog(tmp_path)
    with _patched(fake):
        message = auto.run_quietly(_reorder_settings(junban_auto_reorder=True, junban_auto_actions=True))
    # 2.x-dev keeps the reorder half against its recorded log (`auto_reorder`: 2.5's dense run, every saved action
    # applied); 3.0 (E1.1 04 §5, Haya's G2b): the automatic step is always a spaced job — no 2.5 run is left to
    # compare, its position requests are E2.1's (test_spaced_runs.py) — carrying the actions: every position write
    # first, then the tags, the flag and the suspend, the suspend last (test_auto_actions.py)
    assert message.startswith("順 (automatic): ") and "Reordered" in message, message
    writes = [r["action"] if r["action"] != "multi" else
              ("position" if r["params"]["actions"][0]["params"].get("keys") == ["due"] else "flag")
              for r in fake.requests if r["action"] in ("multi", "addTags", "suspend")
              and (r["action"] != "multi" or r["params"]["actions"][0]["action"] == "setSpecificValueOfCard")]
    last = max(i for i, kind in enumerate(writes) if kind == "position")
    assert set(writes[:last + 1]) == {"position"} and writes[-1] == "suspend", writes
    assert {"addTags", "flag"} <= set(writes[last + 1:]), writes

    fake = _fake(_lapis(0, "探検", "たんけん"), _lapis(1, "大切", "たいせつ"))
    fake.actions = ["setSpecificValueOfCard", "updateNoteFields", "multi"]   # the step's probe asks for 順's
    with _patched(fake), mock.patch.object(backfill, "Session", lambda settings: _Session()), \
            mock.patch.object(backfill, "rebuild_in_background", lambda *a, **k: None):
        message = auto.run_quietly(_fill_settings(enable_junban=True, junban_auto_backfill=True))
    assert message == "Backfill (automatic): Filled 2 notes."
    _check("auto_backfill", _as_before_ft(fake.requests))


@pytest.mark.skipif(_RECORD, reason="recording")
def test_every_recorded_log_is_here():
    assert sorted(os.listdir(_GOLDEN)) == sorted(
        name + ".json" for name in ("reorder", "restore", "fill", "fill_restore", "auto_reorder",
                                    "auto_backfill"))
