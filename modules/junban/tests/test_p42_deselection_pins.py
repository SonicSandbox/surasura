# SPDX-License-Identifier: GPL-3.0-or-later
"""P4.2.3 (P2.2 adversary #14): a click in the 順 window's preview (`gui._with_deselection`) re-plans the pinned count
with the order — a *Study its cards first* card clicked off isn't lifted, so the run lifts one fewer, and the preview
must say so. The same rule goes to W3.4 row 6's Qt port (window Inbox W-A6).

What a wrong answer would cost: the preview promising "2 cards of your pinned episode first" when the run, which reads
the same clicks, puts only one there — the confirmation describing another calculation than the one that reaches Anki
(invariant I5).

The pinned scene of `test_pins_runs` (the 3.0 line, one pinned episode whose cards 須藤 and 図書館 name it), on the fake
collection; real words; never Anki.
"""
import pytest

from modules.junban import connect, gui as junban_gui, pins, reposition
from modules.junban.tests.connect_scene import scene, settings, without_connect
from modules.junban.tests.test_pins_runs import PINNED, _mined_from_the_show
from modules.junban.tests.test_reposition import _patched


@pytest.fixture
def three_oh(monkeypatch):
    monkeypatch.setattr(connect, "PINS", True)
    monkeypatch.setattr(pins, "read", lambda language: PINNED)


def _window(stats, deselected):
    class Window:
        _preview_stats = stats
        _ticked = {}
        _deselected = set(deselected)

        def _changed_ticks(self):
            return {}

        def _settings(self):
            return settings()

        def _lang_code(self):
            return "ja"
    return Window()


def _dry_run(tmp_path):
    fake = scene(tmp_path, without_connect())
    _mined_from_the_show(fake, "須藤", "図書館")
    with _patched(fake):
        _writes, stats = reposition.dry_run(settings())
    assert stats["pinned"] == 2
    return fake, stats


def test_a_pinned_card_clicked_off_is_counted_off(tmp_path, three_oh):
    fake, stats = _dry_run(tmp_path)
    off = fake.card_of("須藤")["cardId"]
    merged = junban_gui.JunbanGui._with_deselection(_window(stats, {off}), stats)
    assert merged["pinned"] == 1, "the run lifts only 図書館 now"
    assert merged["order"][0].word == "図書館"


def test_every_pinned_card_clicked_off_counts_none_and_an_unpinned_click_keeps_the_count(tmp_path, three_oh):
    fake, stats = _dry_run(tmp_path)
    both = {fake.card_of("須藤")["cardId"], fake.card_of("図書館")["cardId"]}
    merged = junban_gui.JunbanGui._with_deselection(_window(stats, both), stats)
    assert merged.get("pinned") == 0, "still members (never 'not on your list'), none lifted"
    other = next(row.card_id for row in stats["order"] if row.pinned is None)
    merged = junban_gui.JunbanGui._with_deselection(_window(stats, {other}), stats)
    assert merged["pinned"] == 2
