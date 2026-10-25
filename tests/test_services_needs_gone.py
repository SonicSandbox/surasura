"""T6's *Needs you* card for a source folder that is GONE (Sonic 2026-10-24, alpha 2's first try: "Yes your lean is
exactly what i'd do"): `app/services/needs.py` makes ONE card per gone folder from the looks' summary rows
(`source_looks.gone`), Qt-free, with real Japanese and Chinese show names from tests/Test Resources/.

What a wrong answer would cost a learner: a card that doesn't say which folder or which shows (he can't tell what it
is about); a Finished show's card that leads with *Find its new folder…* when nothing is left to mine (the useful
answer is *Stop reading it*); a card whose badge counts again on every look, or never counts again once the folder
came back and went again; a key that falls out of the seen file while the folder is still gone.
"""
import os

import pytest

from app.services import needs
from tests.test_library_store_support import LANGUAGES, names


def _row(language, root=13, items=12, shows=None, finished=False, found_in=(), where=("Downloads",)):
    title = names(language)[71]
    path = os.path.join("C:\\Users\\Michael", *where, title)
    return {"id": root, "path": path, "items": items, "on": True, "reachable": False, "gone": True,
            "shows": list(shows if shows is not None else [title]), "finished": finished, "found_in": list(found_in)}


def _cards(rows, seen=frozenset()):
    return [e for e in needs.entries(None, gone_folders=rows, seen=seen) if e.kind == needs.FOLDER_GONE]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_gone_folder_is_one_card_naming_the_folder_where_it_was_and_the_show_it_held(language):
    row = _row(language)
    [card] = _cards([row])
    title = names(language)[71]
    assert title in card.title and "Downloads" in card.title          # the folder, and where it was
    assert title in card.say and "12 episodes" in card.say             # the show it held, in plain words
    assert card.actions == ("find_folder", "stop_reading", "keep_waiting")
    assert card.unseen
    assert (card.data["root"], card.data["path"], card.data["items"]) == (13, row["path"], 12)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_finished_shows_folder_leads_with_stop_reading_it(language):
    """Sonic's lean: a Finished show has nothing left to mine — *Stop reading it* comes first."""
    [card] = _cards([_row(language, finished=True)])
    assert card.actions == ("stop_reading", "find_folder", "keep_waiting")
    assert "Finished" in card.say


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_whose_episodes_a_look_already_joined_elsewhere_says_where_and_leads_with_stop_reading(language):
    """A look of a folder being read joined its episodes by itself: the old folder holds 0, the card still names the
    show and says where it is read now (Kura's seam: lead with *Read from … now · Stop reading it*)."""
    new = os.path.join("S:\\Video\\Anime", names(language)[71])
    [card] = _cards([_row(language, items=0, found_in=[new])])
    assert card.actions[0] == "stop_reading"
    assert new in card.say and names(language)[71] in card.say
    assert "0 episodes" not in card.say


@pytest.mark.parametrize("language", LANGUAGES)
def test_its_episodes_found_in_a_folder_read_already_say_find_joins_them_there(language):
    new = os.path.join("S:\\Video\\Anime", names(language)[71])
    [card] = _cards([_row(language, found_in=[new])])
    assert card.actions[0] == "find_folder" and new in card.say


@pytest.mark.parametrize("language", LANGUAGES)
def test_many_shows_are_named_three_then_how_many_more(language):
    shows = names(language)[80:85]
    [card] = _cards([_row(language, shows=shows, where=("Downloads", "Season"))])
    assert all(s in card.say for s in shows[:3]) and shows[3] not in card.say and "2 more" in card.say


def test_one_card_per_gone_folder_each_with_its_own_key():
    a, b = _row("ja", root=1), _row("zh", root=2)
    cards = _cards([a, b])
    assert [c.data["root"] for c in cards] == [1, 2] and cards[0].key != cards[1].key


def test_a_seen_card_stops_counting_and_stays_listed():
    [card] = _cards([_row("ja")])
    [again] = _cards([_row("ja")], seen={card.key})
    assert not again.unseen and needs.badge([again]) == 0


def test_prune_keeps_a_gone_folders_seen_key_while_it_is_gone_and_lets_it_go_once_it_is_back():
    """Seen, the card stops counting; back and gone again later, it counts again (N10's rule for an offline drive).
    A gather that didn't read the folders (None) judges nothing."""
    row = _row("ja")
    [card] = _cards([row])
    needs.mark_seen("ja", [card.key])
    assert needs.prune("ja", _store_view(), gone_folders=None) == 0
    assert needs.prune("ja", _store_view(), gone_folders=[row]) == 0
    assert card.key in needs.read_seen("ja")
    assert needs.prune("ja", _store_view(), gone_folders=[]) == 1          # back: its key goes
    assert card.key not in needs.read_seen("ja")


def _store_view():
    from app.services import view_rows as vr
    return vr.build({}, {}, {"mine_line": 20, "soon_line": None})
