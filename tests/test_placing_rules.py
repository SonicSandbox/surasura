"""New arrivals' placing rules (P2.1 row 2.1.6; ✅ Q2-3, HC-N6, Q4-9, ✅ P2.1-2, D30): `placing_rules` = {source:
target}, empty by default, and only where New arrivals exist (3.0: the store's `arrivals_on`). The shape is the
store's (L2.2 05 §5.12, agreed with Kura).

What a wrong answer would cost: an arrival that placed itself without a rule the user turned on would be mined
(RD-S16: never); a next episode placed anywhere but after its previous one breaks the order the user watches in; a
rule that ran in 2.x would change where hato's drops land for every 2.x user (✅ Q4-11: the top of NOW). Real
subtitles, synthetic shows, the test's own root.
"""
import pytest

from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _ok(answer):
    code, line = answer
    assert code == 0, line
    return line


def _arrive(episode, show="Example Show", producer="hato", season=1, **more):
    name = f"{show} - {episode:02d}.ja.srt"
    rec = c.record(c.drop(name), f"{show}-{season}-{episode}", producer=producer,
                   show={"title": show, "season": season, "episode": episode, "movie": False}, **more)
    return _ok(h.call("register", "--pairing", c.write_record(rec)))


def _place(item, *args):
    return _ok(h.call("place", "--file", str(item), *args, "--source", "tester"))


def _tier_ids(tier):
    with c.store() as s:
        return s.ids(tier)


def test_with_no_rule_arrivals_wait():
    c.library(arrivals=True)
    first = _arrive(4)
    _place(first["file_id"], "--to", "now")
    second = _arrive(5)
    assert (second["tier"], second["landed"]) == ("arrivals", "arrivals") and "rule" not in second


def test_top_places_only_the_named_programs_drops_and_logs_it_as_theirs():
    c.library(arrivals=True, placing_rules={"hato": "top", "another-tool": "wait"})
    straight = _arrive(5)
    other = _arrive(6, show="Another Show", producer="another-tool")
    unnamed = _arrive(7, show="Third Show", producer="third-tool")
    assert (straight["rule"], straight["tier"], straight["position"]) == ("top", "now", 1)
    assert other["tier"] == unnamed["tier"] == "arrivals" and "rule" not in other
    with c.store() as s:
        log = [tuple(r) for r in s.conn.execute("SELECT item_id, kind, by, explicit FROM placement_log")]
    assert (straight["file_id"], "placed", "hato", 1) in log, "the user's own rule (D30): the source's, explicit"


def test_after_show_puts_the_next_episode_right_after_the_previous_one():
    c.library(arrivals=True, placing_rules={"hato": "after-show"})
    four = _arrive(4)
    assert four["tier"] == "arrivals", "no other episode yet: it waits"
    _place(four["file_id"], "--to", "now", "--position", "2")
    five = _arrive(5)
    assert (five["rule"], five["tier"]) == ("after-show", "now")
    now = _tier_ids("now")
    assert now.index(five["file_id"]) == now.index(four["file_id"]) + 1
    three = _arrive(3)
    now = _tier_ids("now")
    assert three["rule"] == "after-show" and now.index(three["file_id"]) == now.index(four["file_id"]) - 1, \
        "only later episodes in Current: before the earliest of them"


def test_another_season_is_another_show_and_no_season_is_the_first():
    c.library(arrivals=True, placing_rules={"hato": "after-show"})
    four = _arrive(4)
    _place(four["file_id"], "--to", "now")
    assert _arrive(1, season=2)["tier"] == "arrivals"
    assert _arrive(5, season=None)["rule"] == "after-show"


def test_a_finished_shows_new_episode_goes_to_the_top_of_current():
    """Q4-9: its earlier episodes are all in Finished (or 6+ Months): the new one at the top of Current."""
    c.library(arrivals=True, placing_rules={"hato": "after-show"})
    four = _arrive(4)
    _place(four["file_id"], "--to", "now")
    _ok(h.call("finish", "--file", str(four["file_id"]), "--source", "tester"))
    five = _arrive(5)
    assert (five["rule"], five["tier"], five["position"]) == ("after-show", "now", 1)


def test_a_show_still_waiting_in_new_arrivals_keeps_its_next_episode_waiting_too():
    """Review P2.1 #1: Q4-9's 'top of Current' is for a show the user finished, never one still waiting."""
    c.library(arrivals=True, placing_rules={"hato": "after-show"})
    _arrive(1)
    two = _arrive(2)
    assert two["tier"] == "arrivals" and "rule" not in two


@pytest.mark.parametrize("target, tier", [("soon", "soon"), ("goal", "goal"), ("finished", "graduated")])
def test_the_other_targets(target, tier):
    c.library(arrivals=True, placing_rules={"hato": target})
    line = _arrive(5)
    assert (line["rule"], line["tier"]) == (target, tier)


def test_a_channels_line_wins_over_its_programs():
    c.library(arrivals=True, placing_rules={"youtube": "goal", "youtube:UC123": "top"})
    mine = _arrive(1, show="A Channel", producer="youtube", channel_id="UC123")
    other = _arrive(1, show="Another Channel", producer="youtube", channel_id="UC999")
    assert (mine["rule"], mine["tier"]) == ("top", "now") and (other["rule"], other["tier"]) == ("goal", "goal")


@pytest.mark.parametrize("rules", [{"hato": "after-show"}, {"hato": "top"}, {"hato": "finished"}])
def test_in_2x_no_rule_runs_and_drops_land_at_the_top_of_now(rules):
    c.library(placing_rules=rules)
    four = _arrive(4)
    five = _arrive(5)
    assert (five["landed"], five["position"]) == ("now-top", 1) and "rule" not in five and "rule" not in four


def test_a_rule_that_failed_on_the_first_call_places_the_item_on_hatos_retry(monkeypatch):
    """Review P2.1 #6: the rules run on every call while the item waits, so a retry after a busy store places it."""
    c.library(arrivals=True, placing_rules={"hato": "top"})
    from app import library_store
    from app.connect import rules
    real = rules.apply

    def busy(*_a, **_k):
        raise library_store.StoreBusy("held")
    monkeypatch.setattr(rules, "apply", busy)
    rec = c.record(c.drop("Example Show - 05.ja.srt"), "video-05")
    code, line = h.call("register", "--pairing", c.write_record(rec))
    assert (code, line["code"]) == (3, "busy")
    monkeypatch.setattr(rules, "apply", real)
    retry = _ok(h.call("register", "--pairing", c.write_record(rec)))
    assert (retry["landed"], retry["pairing"], retry["rule"], retry["tier"]) == ("already", "same", "top", "now")
