"""ONB-1: setup's *How would you like to start?* — the services (`app/services/setup_wizard.py`'s START part).

Sonic's § 102 / § 105 (2026-11-26): after *Your list*, on the learner's own content, three starts — *Try it small*
(the next 3 episodes, up to 50 cards waiting), *Full start* (20 / 300, today's, pre-picked) and *Pre-studied only*
(PRESTUDIED-MINE's switch on top of the full start, shown only once that switch is in this Surasura). *Start* is the
yes D1's *Make cards for your first 20 episodes?* line waits for: nothing is mined before it.

What a wrong answer would cost: cards made before the learner said yes; a "small" start that still mines 20 episodes
(or caps the other language too); numbers on the page that aren't the list's; a page shown after the learner already
answered (a second yes logging the top again). Real subtitles from tests/Test Resources (the suite's library), ja + zh.
"""
from collections import namedtuple

import pytest

from app import settings_manager
from app.connect import inbox, library
from app.connect.ledger import Ledger
from app.services import needs, setup_wizard as SW
from app.services.settings import SettingsService
from tests import connect_helpers as c
from tests import services_helpers as h
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _consume(lang):
    with c.store(lang) as s, Ledger() as ledger:
        return inbox.consume(s, lang, ledger)


def _line(lang):
    with c.store(lang) as s:
        return s.meta().get("mine_line")


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_try_it_small_mines_only_the_next_three_episodes_and_nothing_before_start(lang):
    # why: the small start is the test drive — three episodes' cards, never the top 20; and the page itself (the
    # learner looking at it) logs nothing: Connect still holds every entry until *Start*
    c.library(lang, extra=20)
    needs.offer(lang, needs.FIRST_CARDS)
    _consume(lang)                                           # Connect's first look: its watermark
    assert SW.start_items(lang)["small"] and _consume(lang)["queued"] == [], "the page's read logs nothing"
    with c.store(lang) as s:
        top3 = library.mine_line(s, 3)
    ids = SW.start_cards(lang, {"connect_enabled": True}, "small", c.dirs(lang)[0])
    assert ids == top3 and len(ids) == 3
    assert _line(lang) == 3, "the store's own line is the start's: Connect tops up from the next three as they go"
    assert sorted(_consume(lang)["queued"]) == sorted(top3)
    assert needs.FIRST_CARDS in needs.read_answered(lang), "Start is the yes: D1's card leaves Needs you"


def test_full_start_logs_the_top_twenty_as_make_cards_did():
    # why: *Full start* is today's start — the same line and the same log as D1's *Make cards*
    c.library("ja", extra=24)
    needs.offer("ja", needs.FIRST_CARDS)
    _consume("ja")
    with c.store("ja") as s:
        top20 = library.mine_line(s)
    ids = SW.start_cards("ja", {"connect_enabled": True}, "full", c.dirs("ja")[0])
    assert ids == top20 and len(ids) == 20 and _line("ja") == 20


def test_the_items_each_start_covers_come_from_connects_own_rule():
    # why: the page's episodes must be the ones *Start* logs — never a second copy of the mine line's rule
    c.library("ja", extra=24)
    got = SW.start_items("ja")
    with c.store("ja") as s:
        assert got["small"] == library.mine_line(s, 3) == library.mine_line(s)[:3]
        assert got["full"] == library.mine_line(s, 20)


def test_starts_of_one_size_share_one_read_of_the_line(monkeypatch):
    # why: full and pre-studied both cover the top 20 — the line is read once per size, never once per start
    monkeypatch.setitem(settings_manager.DEFAULT_SETTINGS, SW.PRESTUDIED_KEY, False)
    c.library("ja", extra=24)
    sizes, real = [], library.mine_line
    monkeypatch.setattr(library, "mine_line", lambda store, n=None: sizes.append(n) or real(store, n))
    got = SW.start_items("ja")
    assert sorted(sizes) == [3, 20] and got["full"] == got["prestudied"] and len(got["full"]) == 20
    assert got["full"] is not got["prestudied"]                    # (each its own list: a caller may change one)


def test_start_items_with_no_library_is_empty():
    # why: setup without a library yet (nothing read) shows no numbers, never fails the page
    h.write_settings({"target_language": "ja", "connect_enabled": True})
    assert SW.start_items("ja") == {}


def test_a_start_that_fails_to_log_takes_its_answer_back(monkeypatch):
    # why: a failed Start must leave D1's line standing (Needs you asks again), never a line gone with no card made
    c.library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    from app import library_store

    def busy(self, by="user"):
        raise library_store.StoreBusy("the window holds the store")
    monkeypatch.setattr(library_store.Store, "enter_mine_line", busy)
    with pytest.raises(library_store.StoreBusy):
        SW.start_cards("ja", {"connect_enabled": True}, "small", c.dirs("ja")[0])
    assert needs.FIRST_CARDS not in needs.read_answered("ja")


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_page_shows_only_while_the_first_cards_line_waits_and_connect_is_on(lang):
    # why: the page answers D1's question — after a yes (*Set up again*) or with Connect off it would be a second,
    # meaningless yes
    c.library(lang)
    on = {"connect_enabled": True, "logic": {"automation": True}}
    assert SW.start_offered(on, lang) is False, "no line offered (nothing reached the mine line)"
    needs.offer(lang, needs.FIRST_CARDS)
    assert SW.start_offered(on, lang) is True
    assert SW.start_offered({"connect_enabled": False}, lang) is False
    assert SW.start_offered(dict(on, logic={"automation": False}), lang) is False, "D29's switch off: Connect is off"
    needs.answer(lang, [needs.FIRST_CARDS])
    assert SW.start_offered(on, lang) is False


def test_not_now_still_shows_the_page_its_start_is_the_yes():
    # why: Kantan-B2b — *Not now* keeps its own answer and the line stays unanswered: the page may still give the yes
    c.library("ja")
    needs.offer("ja", needs.FIRST_CARDS)
    needs.answer("ja", [needs.FIRST_CARDS_NOT_NOW])
    assert SW.start_offered({"connect_enabled": True}, "ja") is True


@pytest.mark.parametrize("lang,other", [("ja", "zh"), ("zh", "ja")])
def test_a_small_start_writes_this_languages_cap_only_and_keeps_the_others(lang, other):
    # why: *Keep up to* is one per language (D31): a Japanese test drive never caps the learner's Chinese
    h.write_settings({"target_language": lang, "connect_backlog_cap": {other: 1200}, "theme": "Dark Flow"})
    service = SettingsService()
    changes = SW.save(service, SW.START, {"start": "small"}, lang)
    assert service.flush(10)
    after = h.read_settings()
    assert after["connect_backlog_cap"] == {lang: 50, other: 1200}, after["connect_backlog_cap"]
    assert set(changes) <= {"connect_backlog_cap", SW.PRESTUDIED_KEY}
    assert after["theme"] == "Dark Flow" and "logic" not in changes, "nothing else written"


def test_full_start_on_a_default_profile_writes_nothing():
    # why: today's numbers are the defaults: *Full start* changes no setting (S19: nothing moved, nothing written)
    assert SW.writes(SW.START, {"start": "full"}, dict(settings_manager.DEFAULT_SETTINGS), "ja") == {}


def test_a_number_cap_becomes_per_language_when_a_start_changes_it():
    # why: a plain number is every language's cap (`settings_values.cap_value`): only this language's moves
    out = SW.writes(SW.START, {"start": "small"}, {"connect_backlog_cap": 300}, "zh")
    assert out == {"connect_backlog_cap": {"ja": 300, "zh": 50}} or \
        out == {"connect_backlog_cap": {"ja": 300, "zh": 50}, SW.PRESTUDIED_KEY: False}


def test_pre_studied_only_is_offered_and_written_only_once_its_switch_is_here(monkeypatch):
    # why: PRESTUDIED-MINE lands in its own train — before it, the third start must not show or write a dead key
    monkeypatch.delitem(settings_manager.DEFAULT_SETTINGS, SW.PRESTUDIED_KEY, raising=False)
    assert SW.starts() == ("small", "full")
    with pytest.raises(ValueError):
        SW.writes(SW.START, {"start": "prestudied"}, {}, "ja")
    assert SW.PRESTUDIED_KEY not in SW.writes(SW.START, {"start": "small"}, {}, "ja")
    monkeypatch.setitem(settings_manager.DEFAULT_SETTINGS, SW.PRESTUDIED_KEY, False)
    assert SW.starts() == ("small", "full", "prestudied")
    assert SW.writes(SW.START, {"start": "prestudied"}, {}, "ja") == {SW.PRESTUDIED_KEY: True}
    assert SW.writes(SW.START, {"start": "full"}, {SW.PRESTUDIED_KEY: True}, "ja") == {SW.PRESTUDIED_KEY: False}


def test_an_unknown_start_is_refused():
    with pytest.raises(ValueError):
        SW.writes(SW.START, {"start": "huge"}, {}, "ja")
    with pytest.raises(ValueError):
        SW.start_cards("ja", {}, "huge")


# --- the page's numbers (pure) --------------------------------------------------------------------------------- #
Ep = namedtuple("Ep", "id label n_new")
Row = namedtuple("Row", "work_id title episodes")
View = namedtuple("View", "rows")


def _view(news_a, news_b):
    return View(rows=(Row(1, "雷鳴の剣と見習い魔女", tuple(Ep(10 + i, f"Ep {i + 1}", n) for i, n in enumerate(news_a))),
                      Row(2, "海辺の喫茶店", tuple(Ep(20 + i, f"Ep {i + 1}", n) for i, n in enumerate(news_b)))))


def test_the_numbers_sum_the_lists_new_words_and_say_days_at_the_daily_pace():
    # why: the page's promise is the learner's own list — 3 episodes' *N new* summed, days at 5 new cards a day
    view = _view([30, 28, 22, 5], [40, 1])
    items = {"small": [10, 11, 12], "full": [10, 11, 12, 13, 20, 21]}
    got = SW.start_numbers(items, view, 5)
    assert got["top"] == "雷鳴の剣と見習い魔女" and got["top_labels"] == ("Ep 1", "Ep 2", "Ep 3")
    assert got["small"] == {"episodes": 3, "titles": 1, "cards": 80, "days": 16}
    assert got["full"] == {"episodes": 6, "titles": 2, "cards": 126, "days": 26}


def test_while_the_list_is_being_made_the_cards_are_unknown_not_zero():
    # why: *N new* not counted yet (a fresh profile's first Generate still running) must read "counting", never 0 days
    view = _view([None, None, None], [None])
    got = SW.start_numbers({"small": [10, 11, 12], "full": [10, 11, 12, 20]}, view, 5)
    assert got["small"]["cards"] is None and got["small"]["days"] is None
    assert got["top"] == "雷鳴の剣と見習い魔女", "the show and its episodes are there at once"


def test_no_view_and_no_items_show_nothing():
    # why: empty states — no library read yet, or a start covering nothing
    assert SW.start_numbers({}, None, 5) == {"top": None, "top_labels": (), "per_day": 5}
    got = SW.start_numbers({"small": []}, _view([1], [2]), 0)
    assert got["small"] == {"episodes": 0, "titles": 0, "cards": None, "days": None} and got["per_day"] is None
