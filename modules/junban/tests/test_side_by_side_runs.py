# SPDX-License-Identifier: GPL-3.0-or-later
"""Kyou-A: every Junban run weaves Current's top two titles while *New cards come from* is *Top two, side by side* —
through `reposition` itself, on the fake collection Junban's suites share (`connect_scene`): the titles are read once
per run in `_plan_scope` beside the pins, so the 順 window's preview and Reorder and the fast re-plan's automatic job
(`spaced.Job`) all weave the same order. Off (no titles from the store), every request is the request it was.

Title A's cards (冒険, 散歩) and title B's (老婆, 眼鏡, 図書館) name their episode in Anki Miner's source; 須藤 names
none (title 3's, or a card made by hand). Real words; never Anki.
"""
import pytest

from modules.junban import connect, pins, reposition, spaced
from modules.junban.tests.connect_scene import scene, settings, without_connect
from modules.junban.tests.test_reposition import _patched

A_SOURCE = "星の旅人 — 星の旅人 - 05 @ 00:04:31"
B_SOURCE = "夜の図書館 — 夜の図書館 - 02 @ 00:11:02"
ENTRIES = without_connect([
    ("冒険", "冒険が始まった。", 2000, [], 0),
    ("散歩", "毎朝<b>散歩</b>に出かける。", 3000, [], 0),
    ("老婆", "老婆が笑った。", 7000, [], 0),
    ("眼鏡", "新しい眼鏡を買った。", 5000, [], 0),
    ("図書館", "図書館で本を読んだ。", 6000, [], 0),
    ("須藤", "須藤さんが来た。", 9000, [], 0),
])
SIDE = ([[1], [2]], {}, {1: {pins.source_of(A_SOURCE)}, 2: {pins.source_of(B_SOURCE)}})


def _fake(tmp_path):
    fake = scene(tmp_path, ENTRIES)
    for word, source in (("冒険", A_SOURCE), ("散歩", A_SOURCE), ("老婆", B_SOURCE), ("眼鏡", B_SOURCE),
                         ("図書館", B_SOURCE)):
        fake.notes[fake.card_of(word)["note"]]["fields"]["MiscInfo"]["value"] = source
    return fake


@pytest.fixture
def side(monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: SIDE)


def test_off_the_order_is_the_journeys(tmp_path, monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: ([], {}, {}, set()))
    monkeypatch.setattr(pins, "read_side", lambda language: ([], {}, {}))
    fake = _fake(tmp_path)
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
    assert [row.word for row in stats["order"]] == ["冒険", "散歩", "眼鏡", "老婆", "図書館", "須藤"]
    assert "woven" not in stats and all(row.weave is None for row in stats["order"])


def test_on_the_two_titles_take_turns_and_the_run_writes_what_it_previewed(tmp_path, side):
    """A's 冒険 (its best by Score), B's 老婆 (Score 30 beats 眼鏡's 10, though 眼鏡 is met first), A's 散歩, then B
    alone: 眼鏡 (placed with the list) before 図書館 (i+1); 須藤, no title's, after."""
    fake = _fake(tmp_path)
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings(junban_unlisted="journey"))
        report = reposition.run(settings(junban_unlisted="journey"))
    assert report["ok"], report["problems"]
    want = ["冒険", "老婆", "散歩", "眼鏡", "図書館", "須藤"]
    assert [row.word for row in stats["order"]] == want
    assert stats["woven"] == 5
    # the window's run also puts away the cards not on your list (図書館, 須藤: suspended, as without the weave)
    assert fake.queue_order() == [w for w in want if fake.card_of(w)["queue"] == 0] == want[:4]


def test_the_fast_re_plans_job_weaves_the_same_order_as_a_window_run(tmp_path, side):
    """The automatic job (the fast re-plan's, `spaced.Job`) reads the titles in the same `_plan_scope`: the same order,
    tomorrow's cards first."""
    fake = _fake(tmp_path)
    with _patched(fake):
        _writes, window = reposition.dry_run(settings(junban_unlisted="journey"))
    again = _fake(tmp_path / "job")
    with _patched(again):
        report = reposition.run(settings(junban_unlisted="journey"), refresh=False, job=spaced.Job(automatic=True))
    assert report["ok"], report["problems"]
    assert again.queue_order() == [row.word for row in window["order"]]
