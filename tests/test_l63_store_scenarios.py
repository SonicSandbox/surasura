"""L6.3 for 3.0 on the real store: what the window's one rule (`app/qt/drag.when_done`) writes, through commands that
already exist — `join` (a split's parts joining forward), `finish` and `place(..., "after-show")` — each one command and
one undo (scope: the planning folder's `tracks/logic/work/L6.3/scope.md`, R1, R2, R8).

What a wrong answer would cost a learner:
  * a joined part landing where the finished part was instead of where he put the next part (his order lost), or in
    the wrong episode order;
  * a join of a watched part moving what counts (a needless Generate, a different list) while *Keep studying watched
    episodes* is off;
  * the next part brought up from Goal and not becoming one row with the part before it;
  * a finished title's later episode reopening the title, or finishing into a second Finished entry of its own;
  * an Undo that leaves anything different from before.

Every test runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, on libraries named with real words
from tests/Test Resources/.
"""
import pytest

from app import library_store as ls
from tests.test_library_store_groups import _members, _piece, _shows, _state
from tests.test_library_store_support import LANGUAGES, migrated, pieces_ok


def _scheduled(store):
    """Every path Generate would read, in its order."""
    return [e["physical_path"] for rows in store.schedule().values() for e in rows]


def _split_show(store, at):
    """NOW's first show, split before its episode `at` (0-based) -> (first piece, its members, second piece, its)."""
    (piece, members), *_rest = _shows(store, "now")
    assert store.split(piece, members[at]) is not None
    second = _piece(store, members[at])
    assert second != piece
    return piece, members[:at], second, members[at:]


@pytest.mark.parametrize("language", LANGUAGES)
def test_R1_a_watched_first_part_joins_forward_where_the_next_part_is_moving_no_word(language):
    """The second part was put after another show; the first part, every file watched, joins it there in episode order
    (`join([next, done], ahead=True)`, as the window asks): one piece, the next part's place, and Generate's list is
    exactly what it was (the watched files counted nothing before and after). One undo puts every row and piece back."""
    store = migrated(language, shows=2, episodes=4)
    first, done, second, rest = _split_show(store, 2)
    (_p, other), = [s for s in _shows(store, "now") if s[0] not in (first, second)][:1]
    assert store.move(rest, "now", after_id=other[-1]) is not None
    assert store.set_watched(done) is not None
    before, listed = _state(store), _scheduled(store)
    now = store.ids("now")
    assert now.index(other[-1]) + 1 == now.index(rest[0]), "the next part stands after the other show"

    change = store.join([second, first], ahead=True)
    assert change is not None and change.kind == "join"
    now = store.ids("now")
    assert _members(store, _piece(store, rest[0])) == done + rest, "one piece, in episode order"
    assert now.index(other[-1]) + 1 == now.index(done[0]), "where the next part was: his order kept"
    assert _scheduled(store) == listed, "a watched part moves no word"
    assert pieces_ok(store) is None
    store.undo(change)
    assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_R2_the_next_part_in_goal_comes_up_after_the_finished_one_and_undo_sends_it_back(language):
    store = migrated(language, shows=2, episodes=4)
    first, done, second, rest = _split_show(store, 2)
    assert store.move(rest, "goal") is not None
    assert store.set_watched(done) is not None
    before = _state(store)

    change = store.join([first, second])
    assert change is not None
    assert {store.item(i)["tier"] for i in rest} <= set(ls.CURRENT)
    assert _members(store, first) == done + rest
    now = store.ids("now") + store.ids("soon")
    assert now.index(done[-1]) + 1 == now.index(rest[0]), "right after the part just watched"
    assert pieces_ok(store) is None
    store.undo(change)
    assert _state(store) == before
    assert {store.item(i)["tier"] for i in rest} == {"goal"}
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_R8_a_finished_titles_later_episode_leads_current_and_finished_in_turn_joins_its_one_entry(language):
    """Its first episodes finished; the last one arrives later (New arrivals, placed `after-show`): it leads Current
    and the finished ones stay in Finished (the title isn't reopened, Q4-9). Finished in turn, it lands beside them and
    is ONE Finished entry (05 §5.2 #4), dated by its own finish. Each undo puts it back as it was."""
    store = migrated(language, shows=2, episodes=4)
    first, early, second, late = _split_show(store, 3)
    assert store.finish(early) is not None
    assert store.set_tier(late, "arrivals") is not None
    finished = _state(store)

    placed = store.place(late, "after-show")
    assert placed is not None
    assert store.ids("now")[0] == late[0], "it leads Current"
    assert {store.item(i)["tier"] for i in early} == {"graduated"}, "never reopened"
    assert store.set_watched(late) is not None
    before = _state(store)

    change = store.finish(late)
    assert change is not None
    fin = store.ids("graduated")
    assert fin.index(early[-1]) + 1 == fin.index(late[0])
    assert _members(store, _piece(store, early[0])) == early + late, "one Finished entry for the title"
    assert store.item(late[0])["graduated_at"] > store.item(early[0])["graduated_at"]
    assert pieces_ok(store) is None
    store.undo(change)
    assert _state(store) == before
    store.undo(placed)
    assert _state(store) == finished
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_same_title_in_two_folders_is_two_titles_each_finishing_on_its_own(language):
    """*The same title in several folders* (Sonic's "point it at your library", the double Harry Potter): two show
    folders are two works — the rule's join reads one work's parts only, so one never joins the other, and finishing
    one leaves the other where it is."""
    store = migrated(language, shows=2, episodes=4)
    (pa, ma), (pb, mb) = _shows(store, "now")[:2]
    assert store.item(ma[0])["work_id"] != store.item(mb[0])["work_id"]
    with pytest.raises(ValueError):
        store.join([pb, pa], ahead=True)                     # the store refuses two titles' parts, as the rule never asks
    assert store.finish(ma) is not None
    assert {store.item(i)["tier"] for i in mb} == {"now"}
    store.close()
