"""ONB-4's *Ready for more?* (PROVISIONAL words): `app/services/needs.py`'s `MORE_CARDS` line and
`app/services/setup_wizard.py`'s `more_cards`, Qt-free, with real Japanese and Chinese titles from tests/Test Resources/.

A small start (*Try it small*: the next 3 episodes, up to 50 cards waiting) is a test drive. Once its cards are nearly
studied, Needs you asks once: *Your first 3 episodes' cards are nearly studied. Ready for more?* · *Next 20 episodes*
(the full start's line and *Keep up to*, through their own writers) · *Keep it small* (answered for good).

What a wrong answer would cost a learner: the card before any card was made (nothing waits because nothing was made),
or while 40 cards still wait; a card that comes back after *Keep it small*; *Next 20 episodes* that lowers a cap they
set higher, caps the other language too, turns their pre-studied switch off, or raises the cap while the line can't
move; a card that keeps asking after they moved the line themselves in Settings.
"""
from types import SimpleNamespace

import pytest

from app.services import needs, setup_wizard as SW
from tests.test_library_store_support import LANGUAGES, names


def view(language, line=3, cards=(0, 4, 0), n=6, mode="store"):
    """Current with one show of `n` episodes (real titles); the first `line` are the mine line (`in_top`), their
    cards in Anki `cards` (the rest: none)."""
    title = names(language)[0]
    eps = tuple(SimpleNamespace(id=i + 1, label=f"Ep {i + 1}", number=i + 1, missing=False,
                                rel_path=f"{title}/{title} - {i + 1:02d}.srt", in_top=i < line,
                                cards=cards[i] if i < len(cards) else 0) for i in range(n))
    row = SimpleNamespace(key="w1", work_id=1, title=title, media="anime", tier="now", episodes=eps)
    return SimpleNamespace(mode=mode, rows=(row,), loading=False, needs=(), mine_line=line)


def more(entries):
    return [e for e in entries if e.kind == needs.MORE_CARDS]


def card(language, v=None, waiting=4, cards_on=True, offered=True):
    if offered:
        needs.offer(language, needs.MORE_CARDS)
    return more(needs.entries(view(language) if v is None else v, offers=needs.read_offers(language),
                              answered=needs.read_answered(language), cards_on=cards_on, waiting=waiting))


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_small_starts_cards_nearly_studied_ask_once_with_its_two_answers(language):
    # why: the test drive's end — the learner sees one card, its question in the title and its two answers
    got = card(language)
    assert len(got) == 1
    e = got[0]
    assert e.key == needs.MORE_CARDS and e.unseen
    assert e.title == "Your first 3 episodes' cards are nearly studied. Ready for more?"
    assert e.actions == ("more_cards", "keep_small")
    assert e.data == {"n": 3, "to": 20, "cap": 300}
    assert "Next 20 episodes" in e.say and "300" in e.say and "Keep it small keeps 3" in e.say
    assert needs.MORE_CARDS in needs.NO_LATER, "its own two answers end it: no ⋯ Not now"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_line_of_one_says_episode_not_episodes(language):
    assert card(language, view(language, line=1, cards=(5,)))[0].title == \
        "Your first episode's cards are nearly studied. Ready for more?"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("waiting", [0, 10])
def test_ten_or_fewer_cards_waiting_is_nearly_studied(language, waiting):
    assert card(language, waiting=waiting)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("waiting", [11, 40, None])
def test_more_waiting_or_no_backlog_saved_never_asks(language, waiting):
    # why: 11+ cards still wait — not yet; None — nothing is known (someone who never synced): never a guess
    assert card(language, waiting=waiting) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_before_any_card_of_the_line_is_made_it_never_asks(language):
    # why: right after Start nothing waits in Anki because nothing was made yet — that's no "nearly studied"
    assert card(language, view(language, cards=(0, 0, 0))) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_cards_only_outside_the_line_dont_count(language):
    # why: the line's walk ends at its last file; an older episode's cards (made by hand) aren't this start's
    assert card(language, view(language, cards=(0, 0, 0, 9, 9, 9))) == []


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("line", [0, 4, 20, None])
def test_a_line_moved_off_the_small_start_or_connect_off_never_asks(language, line):
    # why: a line the learner moved in Settings (or set to 0: nothing mined by itself) is their answer already;
    # None — the view's line with Connect off
    v = view(language, cards=(4, 4, 4))
    v.mine_line = line
    assert card(language, v) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_never_without_its_offer_with_connect_off_or_without_the_stores_view(language):
    # why: only a small start offers it (a full start's learner is never asked); Connect off makes no card
    assert card(language, offered=False) == []
    assert card(language, cards_on=False) == []
    assert card(language, view(language, mode="json")) == []
    assert more(needs.entries(None, offers=needs.read_offers(language), cards_on=True, waiting=3)) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_keep_it_small_ends_it_for_good_and_prune_never_brings_it_back(language):
    # why: *Keep it small* is answered for good — a restart, a prune or a new count never asks again
    e = card(language)[0]
    assert needs.answer(language, needs.answer_keys(e)) == 1
    assert card(language) == []
    needs.prune(language, view(language), offline_roots=[], connect={}, asks=[], gone_folders=[])
    assert needs.MORE_CARDS in needs.read_answered(language)
    assert card(language, waiting=0) == []


# --- *Next 20 episodes*: the full start's knobs through their owners ----------------------------------------------- #
class Settings:
    """The settings service as `more_cards` uses it: `get`, `set` (an update merged on the file as written), `flush`."""

    def __init__(self, values, log):
        self.values, self.log = dict(values), log

    def get(self):
        return dict(self.values)

    def set(self, changes, update=None, keys=()):
        self.values.update(changes)
        if update is not None:
            update(self.values)
        self.log.append(("set", tuple(keys)))

    def flush(self, timeout=None):
        self.log.append(("flush", timeout))
        return True


class Writer:
    def __init__(self, log, reason=None):
        self.log, self._reason = log, reason

    def reason(self):
        return self._reason

    def set_options(self, **options):
        self.log.append(("set_options", options))
        return 7


@pytest.mark.parametrize("language", LANGUAGES)
def test_next_20_raises_this_languages_cap_on_disk_first_then_moves_the_line(language):
    # why: Connect is told once the line moves and reads the cap at its step — the cap must be on disk first; the
    # other language's cap and the pre-studied switch are the learner's own
    other = "zh" if language == "ja" else "ja"
    log = []
    s = Settings({"connect_backlog_cap": {language: 50, other: 120}, SW.PRESTUDIED_KEY: True}, log)
    assert SW.more_cards(s, Writer(log), language) == 7
    assert s.values["connect_backlog_cap"] == {language: 300, other: 120}
    assert s.values[SW.PRESTUDIED_KEY] is True
    assert log == [("set", ("connect_backlog_cap",)), ("flush", 10), ("set_options", {"mine_line": 20})]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("cap", [300, 500, 0])
def test_next_20_never_lowers_a_cap_or_sets_one_where_there_is_none(language, cap):
    # why: 500 set by hand stays 500; 0 is no cap at all (Connect's rule) — 300 would be a lower one
    log = []
    s = Settings({"connect_backlog_cap": cap}, log)
    assert SW.more_cards(s, Writer(log), language) == 7
    assert s.values["connect_backlog_cap"] == cap
    assert log == [("set_options", {"mine_line": 20})]


@pytest.mark.parametrize("language", LANGUAGES)
def test_next_20_while_the_store_cant_be_written_writes_nothing(language):
    # why: a cap raised with a line that couldn't move is half an answer — the card stays and asks again
    log = []
    s = Settings({"connect_backlog_cap": 50}, log)
    assert SW.more_cards(s, Writer(log, reason="read-only"), language) is None
    assert log == [] and s.values["connect_backlog_cap"] == 50


@pytest.mark.parametrize("language", LANGUAGES)
def test_next_20_with_no_writer_writes_nothing(language):
    # why: a window with no store writer (a library being opened) can't move the line — nothing half written
    log = []
    s = Settings({"connect_backlog_cap": 50}, log)
    assert SW.more_cards(s, None, language) is None
    assert log == [] and s.values["connect_backlog_cap"] == 50


class Past:
    """An episode past the line's last file: reading it fails the test (the walk must have ended)."""

    def __getattr__(self, name):
        raise AssertionError(f"read past the line's last file ({name})")


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_line_walk_ends_at_its_last_file_never_reading_the_rest_of_current(language):
    # why: Current can hold 20k episodes; the card needs only the line's 3 (the standard choice: read what you need)
    # (`_more_entry`'s own walk: `entries` reads every episode for the other cards anyway)
    row = view(language, cards=(0, 0, 0)).rows[0]
    row.episodes = row.episodes[:3] + (Past(),) * 50
    assert needs._line_has_cards((row,), 3) is False
    row.episodes = (row.episodes[0]._replace(cards=2) if hasattr(row.episodes[0], "_replace") else
                    _with(row.episodes[0], cards=2),) + row.episodes[1:]
    assert needs._line_has_cards((row,), 3) is True


def _with(ep, **kw):
    return SimpleNamespace(**dict(vars(ep), **kw))
