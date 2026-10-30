"""W4.1-slim (the 3.0 release check, 2026-10-30): what the key-states sheet caught in the window, each with its rule.

- Setup's deck chips cut every name, even "Core 2k" (`DeckChip.sizeHint` 4 px short of what `paintEvent` lays out).
- Backfill's section showed two *Preview* doors (a6 #9 fixed Junban's alone): no section repeats a door's words.
"""
from collections import Counter

import pytest
from PyQt6.QtGui import QFontMetricsF

from app.qt import settings_catalog as catalog
from app.qt import settings_strings as S
from app.qt import wizard as W
from app.qt import wizard_strings as WS
from tests.qt.test_settings_page import ALL_ON, make_page


@pytest.mark.parametrize("name, count", [("Core 2k", 1980), ("Kanji Practice", 610), ("日本語::Mining", 2140),
                                         ("中文::HSK", 1200), ("A", 1)])
def test_a_deck_chip_sized_to_its_hint_shows_its_whole_name(qapp, name, count):
    # why: paint lays out ✓ 12 + 20, the name, 8, the count, 14 — the hint summed 36 + 14, so every name was elided
    chip = W.DeckChip(name, count)
    chip.resize(chip.sizeHint())
    name_f, count_f = chip._parts()
    count_w = QFontMetricsF(count_f).horizontalAdvance(WS.DECK_CARDS.format(n=count))
    room = chip.width() - W._px(12) - W._px(20) - W._px(8) - count_w - W._px(14)
    assert QFontMetricsF(name_f).horizontalAdvance(name) <= room + 0.01


def test_a_very_long_deck_name_is_still_capped_and_shortened(qapp):
    chip = W.DeckChip("日本語::Mining::" + "とても長いサブデッキの名前" * 6, 12)
    assert chip.sizeHint().width() == W._px(W.DECK_CHIP_MAX)


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_no_settings_section_shows_two_doors_with_the_same_words(qapp, language):
    # why: Backfill's *Which cards* row and its own door both read "Preview" (the a6 #9 bug, one section over)
    page, _store = make_page(dict(ALL_ON, enable_junban=True), language)
    for section in {r.section for r in catalog.ROWS}:
        labels = Counter(d.text() for r in catalog.ROWS if r.section == section and r.id in page.rows
                         for d in page.rows[r.id].doors.values())
        assert not [w for w, n in labels.items() if n > 1], (section, labels)
    door = page.rows["junban_backfill_cards"].doors["backfill"]
    assert door.text() == S.ROW_DOORS["junban_backfill_cards"]["backfill"][0] and "deck" in door.toolTip().lower()
