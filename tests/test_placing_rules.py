"""New arrivals' placing rules (P2.1 row 2.1.6; ✅ Q2-3, HC-N6, Q4-9, ✅ P2.1-2): each a setting, off by default, and
only where New arrivals exist (3.0: the store's `arrivals_on`).

What a wrong answer would cost: an arrival that placed itself without a rule the user turned on would be mined
(RD-S16: never); a next episode placed anywhere but after its previous one breaks the order the user watches in; two
rules on one item would move it twice and log two placements; a rule that ran in 2.x would change where hato's drops
land for every 2.x user (✅ Q4-11: the top of NOW). Real subtitles, synthetic shows, the test's own root.
"""
import pytest

from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _arrive(episode, show="Example Show", producer="hato", season=1):
    name = f"{show} - {episode:02d}.ja.srt"
    rec = c.record(c.drop(name), f"{show}-{season}-{episode}", producer=producer,
                   show={"title": show, "season": season, "episode": episode, "movie": False})
    code, line = h.call("register", "--pairing", c.write_record(rec))
    assert code == 0, line
    return line


def _tier_ids(tier):
    with c.store() as s:
        return s.ids(tier)


def test_with_every_rule_off_arrivals_wait():
    c.library(arrivals=True)
    first = _arrive(4)
    h.call("place", "--file", str(first["file_id"]), "--to", "now", "--source", "user")
    second = _arrive(5)
    assert (second["tier"], second["landed"]) == ("arrivals", "arrivals") and "rule" not in second


def test_straight_into_current_places_only_the_named_programs_drops():
    c.library(arrivals=True, arrivals_straight_sources=["hato"])
    straight = _arrive(5)
    other = _arrive(6, show="Another Show", producer="another-tool")
    assert (straight["rule"], straight["tier"], straight["position"]) == ("straight-into-current", "now", 1)
    assert other["tier"] == "arrivals" and "rule" not in other
    with c.store() as s:
        assert (straight["file_id"], "placed", "rule:straight-into-current") in c.events(s), "under the rule's name"


def test_continuing_shows_puts_the_next_episode_right_after_the_previous_one():
    c.library(arrivals=True, arrivals_continuing_shows=True)
    four = _arrive(4)
    assert four["tier"] == "arrivals", "no other episode yet: the rule doesn't apply"
    h.call("place", "--file", str(four["file_id"]), "--to", "now", "--position", "2", "--source", "user")
    five = _arrive(5)
    assert (five["rule"], five["tier"]) == ("continuing-shows", "now")
    now = _tier_ids("now")
    assert now.index(five["file_id"]) == now.index(four["file_id"]) + 1
    three = _arrive(3)
    now = _tier_ids("now")
    assert three["rule"] == "continuing-shows" and now.index(three["file_id"]) == now.index(four["file_id"]) - 1, \
        "only later episodes in Current: before the earliest of them"


def test_another_season_is_another_show():
    c.library(arrivals=True, arrivals_continuing_shows=True)
    four = _arrive(4)
    h.call("place", "--file", str(four["file_id"]), "--to", "now", "--source", "user")
    other = _arrive(1, season=2)
    assert other["tier"] == "arrivals"


def test_a_finished_shows_new_episode_goes_to_the_top_of_current():
    """Q4-9: its earlier episodes are all in Finished (or 6+ Months): the new one at the top of Current."""
    c.library(arrivals=True, arrivals_continuing_shows=True)
    four = _arrive(4)
    h.call("place", "--file", str(four["file_id"]), "--to", "now", "--source", "user")
    h.call("finish", "--file", str(four["file_id"]), "--source", "user")
    five = _arrive(5)
    assert (five["rule"], five["tier"], five["position"]) == ("continuing-shows", "now", 1)


def test_never_two_rules_for_one_item():
    c.library(arrivals=True, arrivals_continuing_shows=True, arrivals_straight_sources=["hato"])
    with c.store() as s:
        s.register_reader("connect")
    four = _arrive(4)
    assert four["rule"] == "straight-into-current", "no other episode: the second rule applies"
    h.call("place", "--file", str(four["file_id"]), "--to", "now", "--position", "3", "--source", "user")
    five = _arrive(5)
    assert five["rule"] == "continuing-shows"
    with c.store() as s:
        placed = [e for e in c.events(s) if e[0] == five["file_id"] and e[1] == "placed"]
    assert [by for _i, _k, by in placed] == ["hato", "rule:continuing-shows"], "registered, then one rule's move"


@pytest.mark.parametrize("rules", [{"arrivals_continuing_shows": True}, {"arrivals_straight_sources": ["hato"]}])
def test_in_2x_no_rule_runs_and_drops_land_at_the_top_of_now(rules):
    c.library(**rules)
    four = _arrive(4)
    five = _arrive(5)
    assert (five["landed"], five["position"]) == ("now-top", 1) and "rule" not in five and "rule" not in four
