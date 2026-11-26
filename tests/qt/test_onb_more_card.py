"""ONB-4's *Ready for more?* on the Needs-you page (PROVISIONAL words; `app/qt/needs.py`'s `_do_more_cards` /
`_do_keep_small`, `NeedsYou.backlog_in`), in the real window with real Japanese and Chinese titles.

What a wrong answer would cost a learner: a card whose explainer stands as a line under its title (the Qt guide: behind
a ?), buttons with no tip, a press that doesn't react at once, *Next 20 episodes* that says done while the library
couldn't be changed, a card that comes back after *Keep it small* — and a page gathered again at every count of the
bar's *Anki · N waiting* (every Anki sync), not only when the count crosses "nearly studied".
"""
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app.qt import strings
from app.services import needs as service
from app.services import view_rows as vr
from tests.qt.conftest import wait_until
from tests.qt.test_needs_gone_folder import world  # noqa: F401 — the window, ja and zh
from tests.test_library_store_support import LANGUAGES, names


def view(language, line=3, cards=None):
    """Current: one show of 6 episodes (a real title), the store's line `line`, the first episode carrying cards."""
    title = names(language)[3]
    works = {1: {"id": 1, "title": title, "title_by_user": 0, "titles": "[]", "folder_key": title, "anilist_id": None,
                 "tmdb_id": None, "youtube_channel": None, "media_type": "anime", "media_type_by": None,
                 "cover_source": "generated", "cover_ref": None, "cover_path": None, "cover_fetched_at": None,
                 "cover_locked": 0, "feed_in": 1}}
    items = {i: {"id": i, "tier": "now", "ord": 1024.0 * i, "rel_path": f"{title}/{title} - {i:02d}.srt",
                 "title": f"{title} - {i:02d}.srt", "parent_folder": title, "source_type": "subtitle",
                 "availability": "available", "work_id": 1, "piece_id": 1, "watched": 0, "mined_at": None,
                 "pinned": None, "mine_asked": None, "graduated_at": None, "in_learning_order": 1,
                 "added_at": "2026-10-01T00:00:00Z", "feed_in": 1} for i in range(1, 7)}
    return vr.build(items, works, {"mine_line": line, "soon_line": None}, cards={1: 4} if cards is None else cards)


class Writer:
    """The writer's `set_options` and `reason`, recorded (`Writer.set_options`: Settings' own row)."""

    def __init__(self, why=None):
        self.why, self.calls = why, []

    def reason(self):
        return self.why

    def set_options(self, **options):
        self.calls.append(options)
        return 3


def opened(world, language, monkeypatch, waiting=4):
    seed, win, _writer, ny = world(language)
    service.offer(language, service.MORE_CARDS)
    ny.read_settings = lambda: {"connect_enabled": True}               # Connect on (the card is Connect's)
    ny.read_connect = lambda _lang: {"needs": [], "jobs": [], "gaps": []}
    ny.find_offline = lambda _lang, _rels, _data: []
    said = []
    monkeypatch.setattr(win, "say", lambda text, hold=None: said.append(text))
    ny.backlog = waiting
    gather(ny, view(language))
    win.show_tab("needs")
    return win, ny, said


def gather(ny, v=None):
    n = ny.gathers
    if v is not None:
        ny.view = v
    ny.refresh()
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    for _ in range(5):
        QApplication.processEvents()


def card_of(ny):
    return next((e for e in ny.entries if e.kind == service.MORE_CARDS), None)


def button(ny, name):
    return next(b for b in ny.cards.buttons(service.MORE_CARDS) if b.property("action") == name)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_card_asks_with_two_tipped_buttons_and_its_explainer_behind_a_mark(world, language, monkeypatch):
    win, ny, _said = opened(world, language, monkeypatch)
    e = card_of(ny)
    assert e is not None and e.title == "Your first 3 episodes' cards are nearly studied. Ready for more?"
    assert [b.text() for b in ny.cards.buttons(e.key)] == ["Next 20 episodes", "Keep it small"]
    assert all(b.toolTip() for b in ny.cards.buttons(e.key))
    card = ny.cards.card(e.key)
    assert getattr(card, "about", None) is not None, "its line stands behind a ?, never under the title"
    assert getattr(card, "more", None) is None, "its two answers end it: no ⋯"


@pytest.mark.parametrize("language", LANGUAGES)
def test_keep_it_small_takes_the_card_off_for_good(world, language, monkeypatch):
    win, ny, said = opened(world, language, monkeypatch)
    button(ny, "keep_small").click()
    assert wait_until(lambda: service.MORE_CARDS in service.read_answered(language), 10)
    gather(ny)
    assert card_of(ny) is None and strings.NEEDS_KEPT_SMALL in said
    ny.backlog_in(0)
    gather(ny)
    assert card_of(ny) is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_next_20_moves_the_line_raises_the_cap_and_answers(world, language, monkeypatch):
    win, ny, said = opened(world, language, monkeypatch)
    writer = Writer()
    win.services.writer = writer
    win.services.settings.set({"connect_backlog_cap": {language: 50}})
    button(ny, "more_cards").click()
    assert wait_until(lambda: service.MORE_CARDS in service.read_answered(language), 10)
    assert writer.calls == [{"mine_line": 20}]
    got = win.services.settings.get()["connect_backlog_cap"]
    assert (got.get(language) if hasattr(got, "get") else got) == 300      # (a window's frozen copy)
    assert wait_until(lambda: strings.NEEDS_MORE_MADE in said or strings.NEEDS_MORE_MADE_PAUSED in said, 5)


@pytest.mark.parametrize("language", LANGUAGES)
def test_next_20_while_the_library_cant_be_changed_says_so_and_the_card_stays(world, language, monkeypatch):
    win, ny, said = opened(world, language, monkeypatch)
    writer = Writer(why="read-only")
    win.services.writer = writer
    button(ny, "more_cards").click()
    assert wait_until(lambda: strings.NEEDS_MORE_NOT_NOW in said, 10)
    assert writer.calls == [] and service.MORE_CARDS not in service.read_answered(language)
    gather(ny)
    assert card_of(ny) is not None


def test_the_bars_count_gathers_again_only_when_it_crosses_nearly_studied(world, monkeypatch):
    # why: the backlog moves at every Anki sync — a gather each time is waste; only its crossing changes the card
    win, ny, _said = opened(world, "ja", monkeypatch, waiting=40)
    assert card_of(ny) is None
    n = ny.gathers
    ny.backlog_in(30)
    ny.backlog_in(12)
    assert ny.gathers == n and not ny._running, "still more than 10 waiting: nothing gathered"
    ny.backlog_in(8)
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    assert card_of(ny) is not None
    n = ny.gathers
    ny.backlog_in(5)
    assert ny.gathers == n and not ny._running
    ny.backlog_in(None)                                  # the backlog file gone: nothing known, the card goes
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    assert card_of(ny) is None


def test_a_line_moved_in_settings_gathers_again_and_the_card_goes(world, monkeypatch):
    # why: the rows read alike when only the line moved — the page must still look again (C1 skips a plain reorder)
    win, ny, _said = opened(world, "ja", monkeypatch)
    assert card_of(ny) is not None
    n = ny.gathers
    ny.view_in(view("ja", line=20))
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    for _ in range(5):
        QApplication.processEvents()
    assert card_of(ny) is None


def test_a_language_switch_forgets_the_left_languages_count(world, monkeypatch):
    # why: the bar's count is one language's — the other library's card must never be judged by it
    win, ny, _said = opened(world, "ja", monkeypatch)
    assert card_of(ny) is not None
    ny._switched()
    assert ny.backlog is None
    gather(ny)
    assert card_of(ny) is None, "no count known for this language yet: nothing asked"
    n = ny.gathers
    ny.backlog_in(4)                                     # the bar's next tick, this language's
    assert wait_until(lambda: ny.gathers > n and not ny._running, 10)
    assert card_of(ny) is not None
