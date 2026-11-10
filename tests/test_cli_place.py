"""`surasura-cli place` (P2.1 row 2.1.2): a person's verb, accepted from any program, each placement logged with who
asked (`--source`, ✅ G1.3-5: another program's placement counts like yours, its name recorded — K109's gate became a
record).

What a wrong answer would cost: a placement Connect reads as the user's when a script made it (or the reverse) hides
who filled the top 20; a `--position` off by one puts the wrong episode next; `current` in a 2.x library would invent a
list that doesn't exist yet. Real subtitles, synthetic titles, the test's own root.
"""
import pytest

from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def _ids(tier):
    with c.store() as s:
        return s.ids(tier)


def test_place_moves_an_item_to_a_tier_and_position_and_logs_who_asked():
    c.library(connect=False)
    now = _ids("now")
    item = now[-1]
    code, line = h.call("place", "--file", str(item), "--to", "now", "--position", "2", "--source", "hato")
    assert code == 0 and (line["tier"], line["position"], line["moved"], line["source"]) == ("now", 2, True, "hato")
    assert _ids("now")[1] == item
    with c.store() as s:
        assert [e for e in c.events(s) if e[0] == item] == [], "no reader yet: nothing logged before Connect's on"


def test_with_connect_on_the_placement_is_logged_under_its_source():
    c.library()
    with c.store() as s:
        s.set_soon_line(len(s.ids("now")) - 1)          # 3.0: a row below the Soon line, so Soon exists (L3.1)
        s.register_reader("connect")
        mark = s.conn.execute("SELECT COALESCE(MAX(id), 0) FROM placement_log").fetchone()[0]
    item = _ids("now")[-1]
    code, line = h.call("place", "--file", str(item), "--to", "soon", "--source", "my-script")
    assert code == 0 and (line["tier"], line["position"]) == ("soon", 1)
    with c.store() as s:
        mine = [e for e in c.events(s, mark) if e[0] == item]
    assert mine and all(by == "my-script" for _i, _k, by in mine), mine


@pytest.mark.parametrize("position, expect", [(None, 1), (1, 1), (2, 2), (99, "last")])
def test_positions_count_from_one_and_past_the_end_is_the_end(position, expect):
    c.library()
    now = _ids("now")
    with c.store() as s:
        s.move(now[1:], "goal")                         # 6+ Months holds two items
    item = now[0]
    args = ["place", "--file", str(item), "--to", "later", "--source", "test"]
    if position is not None:
        args += ["--position", str(position)]
    code, line = h.call(*args)
    goal = _ids("goal")
    assert code == 0 and line["tier"] == "goal"
    assert goal.index(item) + 1 == (len(goal) if expect == "last" else expect) == line["position"]


def test_placing_where_it_already_is_moves_nothing():
    c.library()
    item = _ids("now")[0]
    code, line = h.call("place", "--file", str(item), "--to", "now", "--position", "1", "--source", "test")
    assert code == 0 and line["moved"] is False and line["position"] == 1


def test_current_is_one_list_only_in_the_3_0_library():
    c.library()
    item = _ids("now")[0]
    code, line = h.call("place", "--file", str(item), "--to", "current", "--source", "test")
    assert (code, line["code"]) == (2, "usage")


def test_current_in_the_3_0_library_counts_now_then_soon():
    c.library(arrivals=True)
    now = _ids("now")
    with c.store() as s:
        s.set_soon_line(len(now) - 1)                   # Soon holds one item, Current = NOW then Soon (the line, L3.1)
    now = _ids("now")
    item = now[0]
    # right after NOW's last item stays in NOW
    code, line = h.call("place", "--file", str(item), "--to", "current", "--position", str(len(now)), "--source", "t")
    assert code == 0 and (line["tier"], line["position"]) == ("now", len(now))
    code, line = h.call("place", "--file", str(item), "--to", "current", "--position", str(len(now) + 1), "--source",
                        "t")
    assert code == 0 and line["tier"] == "soon" and _ids("soon")[-1] == item


@pytest.mark.parametrize("args, code, error", [
    (["--file", "999999", "--to", "now", "--source", "t"], 1, "bad-data"),
    (["--file", "1", "--to", "nowhere", "--source", "t"], 2, "usage"),
    (["--file", "1", "--to", "now"], 2, "usage"),                                  # --source is required
    (["--file", "1", "--to", "now", "--position", "0", "--source", "t"], 2, "usage"),
    (["--file", "one", "--to", "now", "--source", "t"], 2, "usage"),
])
def test_a_wrong_place_writes_nothing(args, code, error):
    c.library()
    stored = c.store_state()
    got, line = h.call("place", *args)
    assert (got, line["code"]) == (code, error), line
    assert c.store_state() == stored


def test_a_finished_item_comes_back_through_the_window_not_place():
    c.library()
    item = _ids("now")[0]
    with c.store() as s:
        s.set_tier([item], "graduated")
    stored = c.store_state()
    code, line = h.call("place", "--file", str(item), "--to", "now", "--source", "t")
    assert (code, line["code"]) == (1, "bad-data") and c.store_state() == stored


def test_no_store_needs_you():
    h.seed_library("ja", templates=False)
    h.write_settings(connect_enabled=True)
    code, line = h.call("place", "--file", "1", "--to", "now", "--source", "t")
    assert (code, line["code"]) == (4, "needs-you")


@pytest.mark.parametrize("source", ["user", "undo", "sync", "rule:straight-into-current", "My Script", "", "x" * 33])
def test_a_source_a_person_or_the_store_uses_is_refused(source):
    """Review P2.1 #8: a program can't log its placement as the user's (explicit), an undo, a sync or a rule."""
    c.library()
    stored = c.store_state()
    code, line = h.call("place", "--file", str(_ids("now")[-1]), "--to", "now", "--source", source)
    assert (code, line["code"]) == (2, "usage") and c.store_state() == stored


def test_current_answers_the_place_in_current():
    """Review P2.1 #16: `--to current` answers its place in NOW then Soon, not within Soon."""
    c.library(arrivals=True)
    now = _ids("now")
    with c.store() as s:
        s.set_soon_line(len(now) - 2)                   # two rows below the Soon line (L3.1)
    now = _ids("now")
    item = now[0]
    code, line = h.call("place", "--file", str(item), "--to", "current", "--position", str(len(now) + 1),
                        "--source", "t")
    assert code == 0 and line["tier"] == "soon" and line["position"] == len(_ids("now")) + _ids("soon").index(item) + 1
