"""Kantan-G (Sonic 2026-11-19: "a pause stops all a circle runs by itself"; 3.4 on the lean): New arrivals' circle
paused — hato's register still takes the drop in (its pairing kept), but no rule places it: it waits in New arrivals,
and the circle's resume places what waited by its rule then (`rules.place_held`), as hato's register would have. A
drop the learner placed meanwhile stays where they put it; a back-fill's (placed by no rule) is never placed by it.

What a wrong answer would cost: the learner pauses New arrivals and hato's new episodes still move into Current by
themselves (and into the top 20, where Connect mines them); or, resumed, they wait in New arrivals for good.

Real subtitles (ja + zh), synthetic shows, the test's own root and library store.
"""
import pytest

from app.connect import rules
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

RULES = {"hato": "after-show"}


def _ok(answer):
    code, line = answer
    assert code == 0, line
    return line


def _arrive(lang, episode, show="Example Show", *args):
    name = f"{show} - {episode:02d}.{lang}.srt"
    rec = c.record(c.drop(name, lang), f"{show}-{lang}-{episode}", lang=lang, producer="hato",
                   show={"title": show, "season": 1, "episode": episode, "movie": False})
    return _ok(h.call("register", "--pairing", c.write_record(rec), *args))


def _place(item, *args):
    return _ok(h.call("place", "--file", str(item), *args, "--source", "tester"))


def _tier(lang, item):
    with c.store(lang) as s:
        return s.item(item)["tier"]


def _now(lang):
    with c.store(lang) as s:
        return s.ids("now")


def _settings(lang, paused):
    h.write_settings(target_language=lang, connect_enabled=True, placing_rules=RULES, paused=paused)
    return {"target_language": lang, "connect_enabled": True, "placing_rules": RULES, "paused": paused}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_drop_while_new_arrivals_is_paused_waits_and_its_resume_places_it_after_its_show(lang):
    c.library(lang, arrivals=True, placing_rules=RULES)
    four = _arrive(lang, 4)
    _place(four["file_id"], "--to", "now", "--position", "2")
    _settings(lang, ["arrivals"])
    five = _arrive(lang, 5)
    assert five["tier"] == "arrivals" and "rule" not in five, "paused: no rule places it"
    assert five["waits"] == "paused"
    with c.store(lang) as s:
        assert [d["id"] for d in s.held_drops()] == [five["file_id"]]
    placed = rules.place_held(_settings(lang, []), languages=(lang,))
    assert placed == {lang: [five["file_id"]]}
    now = _now(lang)
    assert now.index(five["file_id"]) == now.index(four["file_id"]) + 1, "right after its previous episode"
    with c.store(lang) as s:
        assert s.held_drops() == [], "taken: a second resume places nothing again"
    assert rules.place_held(_settings(lang, []), languages=(lang,)) == {}


def test_a_drop_the_learner_placed_meanwhile_stays_where_they_put_it():
    c.library("ja", arrivals=True, placing_rules=RULES)
    four = _arrive("ja", 4)
    _place(four["file_id"], "--to", "now")
    _settings("ja", ["arrivals"])
    five = _arrive("ja", 5)
    _place(five["file_id"], "--to", "soon")                    # the learner's own move, while paused
    assert rules.place_held(_settings("ja", []), languages=("ja",)) == {"ja": []}
    assert _tier("ja", five["file_id"]) == "soon"


def test_a_rule_turned_to_wait_before_the_resume_keeps_the_drop_waiting():
    c.library("ja", arrivals=True, placing_rules=RULES)
    four = _arrive("ja", 4)
    _place(four["file_id"], "--to", "now")
    _settings("ja", ["arrivals"])
    five = _arrive("ja", 5)
    settings = dict(_settings("ja", []), placing_rules={"hato": "wait"})
    assert rules.place_held(settings, languages=("ja",)) == {"ja": []}
    assert _tier("ja", five["file_id"]) == "arrivals"


def test_another_circles_pause_leaves_hatos_rule_as_it_was():
    c.library("ja", arrivals=True, placing_rules=RULES)
    four = _arrive("ja", 4)
    _place(four["file_id"], "--to", "now")
    _settings("ja", ["miner", "junban"])
    five = _arrive("ja", 5)
    assert (five["rule"], five["tier"]) == ("after-show", "now")
    with c.store("ja") as s:
        assert s.held_drops() == []


def test_a_store_with_nothing_held_or_an_unreadable_record_places_nothing():
    c.library("ja", arrivals=True, placing_rules=RULES)
    with c.store("ja") as s:
        assert s.held_drops() == []
        s.forget_drops([])
        s.bookkeeping({"held_drops": "not json"})
        assert s.held_drops() == []
    assert rules.place_held(_settings("ja", []), languages=("ja", "zh")) == {}


def test_a_library_busy_part_way_keeps_every_drop_not_yet_tried_for_the_next_resume(monkeypatch):
    """Review (Haiku failures + state, confirmed): the list was taken first, so a busy library mid-way lost the rest."""
    from app import library_store
    c.library("ja", arrivals=True, placing_rules=RULES)
    four = _arrive("ja", 4)
    _place(four["file_id"], "--to", "now")
    _settings("ja", ["arrivals"])
    five, six = _arrive("ja", 5), _arrive("ja", 6)
    real = rules.apply
    tries = []

    def busy_on_the_second(store, item_id, record, settings):
        tries.append(item_id)
        if len(tries) == 2:
            raise library_store.StoreBusy("another program writes the library")
        return real(store, item_id, record, settings)
    monkeypatch.setattr(rules, "apply", busy_on_the_second)
    assert rules.place_held(_settings("ja", []), languages=("ja",)) == {}
    with c.store("ja") as s:
        assert [d["id"] for d in s.held_drops()] == [six["file_id"]], "the one placed forgotten, the rest kept"
    assert _tier("ja", five["file_id"]) == "now"
    monkeypatch.setattr(rules, "apply", real)
    assert rules.place_held(_settings("ja", []), languages=("ja",)) == {"ja": [six["file_id"]]}


def test_a_resume_while_hato_registers_never_leaves_its_drop_waiting():
    """Review (Haiku state, confirmed): the verb read the pause at its start; resumed before its drop was kept, the
    resume's look found nothing — the verb reads the switch again after keeping it, and places it itself."""
    from app.cli import connect_verbs
    c.library("ja", arrivals=True, placing_rules=RULES)
    four = _arrive("ja", 4)
    _place(four["file_id"], "--to", "now")
    loaded = _settings("ja", ["arrivals"])
    _settings("ja", [])                             # the resume landed in settings.json meanwhile
    rec = c.record(c.drop("Example Show - 05.ja.srt", "ja"), "Example Show-ja-5", lang="ja", producer="hato",
                   show={"title": "Example Show", "season": 1, "episode": 5, "movie": False})
    out = connect_verbs.register_record(rec, "ja", loaded=loaded)
    assert (out["rule"], out["tier"]) == ("after-show", "now") and "waits" not in out
    with c.store("ja") as s:
        assert s.held_drops() == []
