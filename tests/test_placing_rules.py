"""New arrivals' placing rules (P2.1 row 2.1.6; ✅ Q2-3, HC-N6, Q4-9, ✅ P2.1-2, D30): `placing_rules` = {source:
target}, `after-show` for hato and folders by default (Decision 1, lean), and only where New arrivals exist (3.0: the
store's `arrivals_on`). The shape is the store's (L2.2 05 §5.12, agreed with Kura).

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


def test_hato_set_to_wait_makes_its_arrivals_wait():
    # only an explicit target changes a default (SRC W1 fix): {"hato": "wait"} keeps a next episode in New arrivals
    c.library(arrivals=True, placing_rules={"hato": "wait"})
    first = _arrive(4)
    _place(first["file_id"], "--to", "now")
    second = _arrive(5)
    assert (second["tier"], second["landed"]) == ("arrivals", "arrivals") and "rule" not in second


@pytest.mark.parametrize("held", [{}, {"another-tool": "top"}, {"source": "wait"}])
def test_an_empty_or_partial_rules_dict_keeps_hatos_default_after_show(held):
    # why (SRC W1 fix, the lead's call 3): `placing_rules` merges per key as `logic` does. A file holding {} — what the
    # Settings row wrote when its last rule was set to Wait, before after-show was the default — or naming only other
    # sources quietly turned the after-show default off: hato's next episode waited instead of joining its show
    c.library(arrivals=True, placing_rules=held)
    first = _arrive(4)
    _place(first["file_id"], "--to", "now")
    second = _arrive(5)
    assert (second["rule"], second["tier"]) == ("after-show", "now")
    now = _tier_ids("now")
    assert now.index(second["file_id"]) == now.index(first["file_id"]) + 1


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


def test_a_record_naming_no_producer_follows_hatos_line_on_the_cli_path_as_in_the_store():
    # Settings shows hato's line as the rule for a drop that names no program, and the store reads it so
    # (`library_store._rule_for`); the CLI's own reading (`rules.rule_for`) must agree, or the line would lie.
    from app.connect import rules
    assert rules.rule_for({"show": {"title": "ぼっち・ざ・ろっく！"}}, {"placing_rules": {"hato": "top"}}) == ("hato", "top")
    assert rules.rule_for({"producer": "", "channel_id": None}, {"placing_rules": {"hato": "finished"}}) == \
        ("hato", "finished")
    assert rules.rule_for({"producer": "youtube"}, {"placing_rules": {"hato": "top"}}) is None, \
        "a named program has only its own lines"


def test_a_channel_set_to_wait_waits_though_its_program_has_a_place_and_a_place_no_rule_names_is_never_used():
    # a hand-edited settings.json: the channel's own "wait" outranks youtube's line (the channel is asked first), and
    # a target that names no place ("graduated", 2.x's folder word) places nothing — the arrival waits for the user
    from app.connect import rules
    channel = "UCgx8nPpXp9c0Kv4bUk1D3ng"
    record = {"producer": "youtube", "channel_id": channel}
    assert rules.rule_for(record, {"placing_rules": {"youtube": "top", f"youtube:{channel}": "wait"}}) is None
    assert rules.rule_for(record, {"placing_rules": {"youtube": "soon", f"youtube:{channel}": "goal"}}) == \
        (f"youtube:{channel}", "goal")
    assert rules.rule_for({"producer": "hato"}, {"placing_rules": {"hato": "graduated"}}) is None


# --------------------------------------------------------------------------- #
# Decision 1 (lean): hato's next episode joins its show, by the rule on by default
# --------------------------------------------------------------------------- #
def test_by_default_hatos_next_episode_joins_its_show_and_a_show_never_shown_waits():
    # why (SRC-2, Decision 1): "if the show exists, it should just pair and be able to be mined": with no
    # rule written (settings.json without `placing_rules`) a drop of a show in Current goes right after its episode
    # there; a show never shown still waits in New arrivals; a show only in Finished leads Current (Q4-9)
    c.library(arrivals=True)
    four = _arrive(4)
    assert four["tier"] == "arrivals" and "rule" not in four, "a show never shown: it waits"
    _place(four["file_id"], "--to", "now", "--position", "2")
    five = _arrive(5)
    assert (five["rule"], five["tier"]) == ("after-show", "now")
    now = _tier_ids("now")
    assert now.index(five["file_id"]) == now.index(four["file_id"]) + 1
    other = _arrive(1, show="Another Show", anilist_id=None, tmdb_id=None)    # its own show (the fixture's ids are one)
    assert other["tier"] == "arrivals" and "rule" not in other
    _place(other["file_id"], "--to", "now")
    _ok(h.call("finish", "--file", str(other["file_id"]), "--source", "tester"))
    two = _arrive(2, show="Another Show", anilist_id=None, tmdb_id=None)
    assert (two["rule"], two["tier"], two["position"]) == ("after-show", "now", 1)


def test_hatos_next_episode_joins_a_show_a_folder_scan_brought_in():
    # why ("one rule, both channels"): the show's episodes in Current came from a source folder, so their records
    # name no episode number; hato's drop of that show still joins it (the store's after-show, by its title), right
    # after its last episode there, as the folder's own next file would
    import hashlib
    import os
    import shutil
    from app import library_store
    c.library(arrivals=True)
    data_dir, _u = c.dirs("ja")
    src = os.path.join(h.root(), "elsewhere", "Shows")
    found = []
    for n in (1, 2):
        origin = os.path.join(src, "Example Show", f"Example Show - {n:02d}.ja.srt")
        os.makedirs(os.path.dirname(origin), exist_ok=True)
        sub_lang, sub_name = c.SUBTITLE["ja"]
        with open(os.path.join(h.RESOURCES, sub_lang, sub_name), "rb") as f, open(origin, "wb") as out:
            out.write(f.read() + f"\nscan {n}\n".encode("utf-8"))       # a real subtitle, each its own bytes
        rel = f"{library_store.CONTENT_FOLDER}/Example Show/{os.path.basename(origin)}"
        os.makedirs(os.path.join(data_dir, library_store.CONTENT_FOLDER, "Example Show"), exist_ok=True)
        shutil.copyfile(origin, os.path.join(data_dir, *rel.split("/")))
        with open(origin, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()
        st = os.stat(origin)
        found.append({"origin": origin, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
                      "show": "Example Show", "rel": rel})
    with c.store() as s:
        root = s.add_source(src)
        scanned = s.take_in(root, found, first=True).added
    three = _arrive(3)
    assert three["rule"] == "after-show" and three["tier"] in ("now", "soon")
    current = _tier_ids("now") + _tier_ids("soon")
    assert current.index(three["file_id"]) == max(current.index(i) for i in scanned) + 1


# --------------------------------------------------------------------------- #
# SRC W1 fix (the lead's call 3): `placing_rules` merges per key, as `logic` does
# --------------------------------------------------------------------------- #
DEFAULT_RULES = {"hato": "after-show", "source": "after-show"}


@pytest.mark.parametrize("held, merged", [
    (None, DEFAULT_RULES),                                                       # absent: the defaults
    ({}, DEFAULT_RULES),                                                         # empty: still the defaults
    ({"hato": "top"}, {"hato": "top", "source": "after-show"}),                  # partial: the rest default
    ({"source": "wait"}, {"hato": "after-show", "source": "wait"}),              # an explicit Wait is kept
    ({"hato": "wait", "youtube:UCgx8nPpXp9c0Kv4bUk1D3ng": "goal"},
     {"hato": "wait", "source": "after-show", "youtube:UCgx8nPpXp9c0Kv4bUk1D3ng": "goal"}),
    (["hato", "top"], DEFAULT_RULES),                                            # hand-edited, no dict: the defaults
])
def test_every_reader_gets_the_rules_merged_per_key_with_their_defaults(held, merged):
    # why: a missing key quietly turning the after-show default off (the next episode never joining its show) while
    # Settings shows it on; only an explicit target changes one. The one rule (`settings_manager.placing_rules`), read
    # through settings.json by load_settings (the window, the command line, the folders' looks) and by Connect's rules
    import json
    import os
    from app import settings_manager
    from app.connect import rules
    assert settings_manager.placing_rules(held) == merged
    path = os.path.join(h.root(), "settings.json")
    values = {"target_language": "ja"} if held is None else {"target_language": "ja", "placing_rules": held}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(values, f)
    assert settings_manager.load_settings()["placing_rules"] == merged
    assert settings_manager.load_settings(strict=True)["placing_rules"] == merged
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == values, "reading never writes the defaults into the file"
    raw = {} if held is None else {"placing_rules": held}                       # Connect handed the file as it is
    want = None if merged["hato"] == "wait" else ("hato", merged["hato"])
    assert rules.rule_for({"producer": "hato"}, raw) == want
    assert rules.rule_for({"producer": "hato"}, settings_manager.load_settings()) == want


def test_the_merged_rules_are_a_new_dict_each_time():
    # a caller changing its copy (the Settings row builds its pick on it) never changes the defaults themselves
    from app import settings_manager
    mine = settings_manager.placing_rules({"hato": "top"})
    mine["source"] = "wait"
    assert settings_manager.placing_rules() == DEFAULT_RULES
    assert settings_manager.DEFAULT_SETTINGS["placing_rules"] == DEFAULT_RULES
