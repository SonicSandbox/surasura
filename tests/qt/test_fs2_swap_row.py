"""FS-2 (the full Swap's window): Settings' *Swap gives* row — `swap_in_place`, FS-1's setting — in Anki & mining ›
*Your daily loop*, under ⇄ Swap (SCOPE § 4: the three moves' one home; Swap owns the setting). Words PROVISIONAL.

The row lands inert: the setting stays off in the tree (the lead, 2026-11-23); the default's flip is a later commit,
kept local, for the release after the coming one.
"""
import pytest

pytest.importorskip("PyQt6")

from app import analyzer, settings_manager, settings_placement
from app.qt import settings_catalog as catalog
from app.qt import settings_controls as sc
from app.qt import settings_strings as S
from tests.qt.test_settings_page import ALL_ON, make_page  # noqa: F401
from tests.qt.test_settings_page_fixes import _written


def test_the_swap_row_lives_under_swap_in_your_daily_loop_and_writes_its_one_key():
    """One row for `swap_in_place`, in Anki & mining right after ⇄ Swap's flag (the loop's group), indented under it,
    a choice of two — *Same card, new sentence* first — that writes only its own key; never left in NOT_SHOWN."""
    row = catalog.ROW["swap_in_place"]
    ids = [r.id for r in catalog.ROWS]
    assert ids.index("swap_in_place") == ids.index("loop_swap_flag") + 1
    assert (row.section, row.kind, row.keys, row.sub, row.adv) == ("anki", "choice", ("swap_in_place",), True, False)
    assert row.options == (True, False)
    assert "swap_in_place" not in catalog.NOT_SHOWN and "swap_in_place" in catalog.reachable()
    assert S.OPTIONS["swap_in_place"] == {True: "Same card, new sentence", False: "A new card"}
    assert set(S.OPTION_TIPS["swap_in_place"]) == {True, False}


def test_the_swap_rows_words_are_short_and_its_explainer_stays_behind_its_question_mark():
    """The Qt guide: no explainer subtitle — the row's line is its description, behind the ?; the tip ≤ 12 words; the
    ? names the two cards that always get a new card and the phone edit (decision 9), in one short line."""
    row = catalog.ROW["swap_in_place"]
    assert row.label and row.help and row.tip
    assert len(row.tip.split()) <= 12
    assert len(row.help) <= 200
    assert "by hand" in row.help and "phone" in row.help
    assert catalog.help_line(row, {"swap_in_place": False}, "ja") == row.help      # never a live line in its place


def test_swaps_flag_row_no_longer_promises_a_new_card():
    """⇄ Swap's own ? said "makes the word a new card": with *Same card* it doesn't — its words fit both choices."""
    assert "new card" not in catalog.ROW["loop_swap_flag"].help


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_swap_row_shows_only_with_cards_made_for_you_as_swaps_flag_does(qapp, language):
    """Swap's flag is read only while Connect is on: the row follows it, hidden with *Cards made for you* off."""
    page, _store = make_page(dict(ALL_ON, connect_enabled=False), language)
    page._settle()
    assert not page.rows["swap_in_place"].isVisibleTo(page)
    page, _store = make_page(dict(ALL_ON), language)
    page._settle()
    assert page.rows["swap_in_place"].isVisibleTo(page) and page.rows["loop_swap_flag"].isVisibleTo(page)


@pytest.mark.parametrize("chosen", [True, False])
def test_picking_a_choice_writes_swap_in_place_through_the_service_only(qapp, chosen):
    """*Same card, new sentence* writes True, *A new card* False — the one key, through the settings service."""
    page, store = make_page(dict(ALL_ON, swap_in_place=not chosen), "ja")
    view = page.rows["swap_in_place"]
    choice = view.controls[0]
    assert isinstance(choice, sc.Choice) and choice.values() == [True, False]
    assert choice.toolTip()
    assert _written(store, choice, chosen) == [{"swap_in_place": chosen}]


def test_the_rows_changed_dot_follows_the_shipped_default():
    """The dot reads DEFAULT_SETTINGS: the shipped default is unmarked, the other choice is marked."""
    row = catalog.ROW["swap_in_place"]
    shipped = settings_manager.DEFAULT_SETTINGS["swap_in_place"]
    assert catalog.is_default(row, {"swap_in_place": shipped}, "ja")
    assert not catalog.is_default(row, {"swap_in_place": not shipped}, "ja")


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_swap_in_place_is_in_no_signature_so_switching_it_never_re_analyses(language):
    """How Swap writes a card is never what a run counts: placed *neither*, and the analysis signature is the same
    either way (switching it costs no Generate)."""
    assert settings_placement.PLACED["swap_in_place"] == "neither"
    base = settings_manager.load_settings()
    on = analyzer.settings_signature(dict(base, swap_in_place=True), language)
    off = analyzer.settings_signature(dict(base, swap_in_place=False), language)
    assert on == off
