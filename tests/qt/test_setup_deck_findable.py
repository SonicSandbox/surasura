"""The deck picked in setup is findable afterwards (Kantan-T, 2026-11-18; a tester on 3.0.15 redid the whole setup
because setup said it would use a deck he didn't mean, and he found nowhere to change it).

Setup's *Card order* page picks Junban's deck (`junban_deck`: the deck whose new cards Surasura keeps in order, the
deck Anki Miner is set to put its cards in). After setup it changes only in Junban's window, behind Settings › Card
order › *Which cards*' *Junban…* — whose line said only "This deck is chosen in Junban's window", never which deck.
Now (words PROVISIONAL):
- *Which cards* names the deck in sight (`catalog.help_line`: a live line, never behind the ?), beside its *Junban…*;
- Your setup's *Cards in Anki* leads with the deck, so the first page of Settings says it (its *Change ›* goes there);
- setup's own line says which deck it will move, and that the menu below picks another; the menu's hover says where
  it changes later.
The deck is this language's only (`setup_wizard.junban_deck`: a deck recorded for the other language is no deck here).

What a wrong answer costs: a learner who can't see or change the deck his new cards are ordered and made in, and redoes
setup; or another language's deck named as this one's.
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import settings_catalog as catalog
from app.qt import settings_live as live
from app.qt import settings_strings as S
from app.qt import wizard_strings as WS
from tests.qt.test_settings_page import ALL_ON, _no_direct_save, make_page  # noqa: F401 (the autouse guard)

DECK = "日本語::マイニング"
CHINESE = "中文::挖矿"


def _base(**more):
    return dict({"enable_junban": True, "junban_order": "content", "junban_backfill_fills": [],
                 "junban_scope": "deck"}, **more)


def test_which_cards_names_this_languages_deck_and_says_when_none_is_chosen():
    row = catalog.ROW["junban_scope"]
    assert catalog.help_line(row, _base(junban_deck=DECK), "ja") == S.JUNBAN_DECK_LINE.format(deck=DECK)
    assert DECK in catalog.help_line(row, _base(junban_deck=DECK), "ja")
    assert catalog.help_line(row, _base(), "ja") == S.JUNBAN_NO_DECK
    # the deck recorded for Chinese (AD-1) is no deck for Japanese: never named as this language's
    zh = _base(junban_deck=CHINESE, junban_replan_deck=CHINESE, junban_replan_language="zh")
    assert catalog.help_line(row, zh, "ja") == S.JUNBAN_NO_DECK
    assert catalog.help_line(row, zh, "zh") == S.JUNBAN_DECK_LINE.format(deck=CHINESE)
    # *All decks*: no one deck to name — the row's own description, behind its ?
    assert catalog.help_line(row, _base(junban_deck=DECK, junban_scope="all"), "ja") == row.help


def test_cards_in_anki_leads_with_the_deck():
    rest = S.SETUP_ORDER_OFF + S.SEP + S.SETUP_NOTHING_FILLED                       # (順 not keeping them in order)
    lines = live.setup_lines(_base(junban_deck=DECK), "ja", {})
    assert lines["setup_cards"] == S.SETUP_DECK.format(deck=DECK) + S.SEP + rest
    assert live.setup_lines(_base(), "ja", {})["setup_cards"] == rest                  # no deck: nothing to name
    off = live.setup_lines(_base(junban_deck=DECK, enable_junban=False), "ja", {})
    assert off["setup_cards"] == S.SETUP_NOT_ORDERED                                   # 順 off: as before


def test_setup_says_which_deck_it_moves_and_where_another_is_picked():
    many, one = WS.KEEP_ORDER_MOVES[1].format(n=1234, deck=DECK), WS.KEEP_ORDER_MOVES[0].format(deck=DECK)
    assert DECK in many and "1,234" in many and many.endswith("Pick it below.")
    assert DECK in one and one.endswith("Pick it below.")
    assert "Settings" in WS.DECK_PICK_TIP and "Card order" in WS.DECK_PICK_TIP


def test_the_settings_page_shows_the_deck_in_sight_and_follows_junbans_window(qapp):
    """The row's line is in sight (a live line, not the ? description) and follows a deck picked in Junban's window
    (another window's write) at once."""
    page, store = make_page(dict(ALL_ON, junban_deck=DECK, junban_scope="deck"))
    view = page.row("junban_scope")
    assert view.help.text() == S.JUNBAN_DECK_LINE.format(deck=DECK) and not view.help.isHidden()
    assert "junban" in view.doors                     # *Junban…* beside it (shown where Junban's window is here)
    store.outside({"junban_deck": "日本語::新しいデッキ"})
    QApplication.processEvents()
    assert view.help.text() == S.JUNBAN_DECK_LINE.format(deck="日本語::新しいデッキ")
    # 順's pair recorded for Chinese with that very deck: no deck for Japanese — repainted though `junban_deck` stayed
    store.outside({"junban_replan_deck": "日本語::新しいデッキ", "junban_replan_language": "zh"})
    QApplication.processEvents()
    assert view.help.text() == S.JUNBAN_NO_DECK
    page.close()
