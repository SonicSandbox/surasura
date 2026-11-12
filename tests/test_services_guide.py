"""The feature guide's rules (Hoshi-S, Sonic 2026-11-12, part of the launch; spec: the 3.0 planning folder,
`tracks/window/work/feature-guide-2026-11-12/SPEC.md`): the notes files, which releases show, *for you* first, the
glow's state.

What a wrong answer would cost a learner: a release cut without its notes (the ✦ shows last version's news as new); a
*Show me* that goes nowhere (a place that isn't there); the glow back after every start (a nag), or never again after
the next update; an item for their kind of library buried under the rest; their state written into settings.json (an
exported settings file carrying it to another PC) or sent anywhere.
"""
import json
import os
import pytest

from app import __version__, path_utils
from app.services import guide, help_cards

pytest.importorskip("app.qt.settings_catalog")
from app.qt import settings_catalog as catalog  # noqa: E402  (Qt-free: the catalog is data)


# the notes as shipped: the repo's own folder (under the tests, `guide.folder()` is the test root's)
SHIPPED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), guide.FOLDER)


def _locate(target):
    return catalog.locate(target)


def _release(version, items, date="2026-11-12"):
    return {"version": version, "date": date, "items": items}


def _item(id_, kind="new", tags=("everyone",), where=None, text="hato で字幕が見つかる。"):
    out = {"id": id_, "kind": kind, "text": text, "for": list(tags)}
    if where is not None:
        out["where"] = where
    return out


def _write(folder, data, name=None):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, (name or data["version"]) + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# --- the shipped notes: the cut's gate ----------------------------------------------------------------------------- #
def test_this_version_has_its_whats_new_file_so_a_release_without_one_stays_red():
    # The cut bumps app/__init__.py's version in the release PR: without app/assets/whats_new/<version>.json beside
    # it this test fails, and the release can't merge until the notes are written (CUT.md's step).
    path = os.path.join(SHIPPED, f"{__version__}.json")
    assert os.path.isfile(path), f"{__version__} has no What's new notes: write app/assets/whats_new/{__version__}.json"


def test_every_shipped_notes_file_is_whole_and_every_show_me_names_a_real_place():
    names = [n for n in os.listdir(SHIPPED) if n.endswith(".json")]
    assert names
    for name in names:
        with open(os.path.join(SHIPPED, name), encoding="utf-8") as f:
            data = json.load(f)
        assert guide.problems(data, has_card=help_cards.available, locate=_locate) == [], name
        assert name[:-5] == data["version"], name
    read = guide.read_notes(SHIPPED)
    assert len(read) == len(names) and all(r.items for r in read)


# --- a notes file's problems --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("item, wrong", [
    (_item("a", kind="feature"), "kind"),
    (_item("a", tags=("anime",)), "for"),
    (_item("a", tags=()), "for"),
    (_item("a", where="tab:goal"), "where"),
    (_item("a", where="control:anki"), "where"),
    (_item("a", where="settings:no_such_row"), "where"),
    (_item("a", where="help:nope"), "where"),
    (_item("a", where="current"), "where"),
    (_item("a", text="  "), "text"),
    (_item("a", text="一行目\n二行目"), "text"),
    (_item("a", text="字" * 101), "text"),
    (_item("a", kind="fix", where="tab:needs"), "fix"),
    (dict(_item("a"), title="字幕"), "title"),
    (dict(_item("a"), step="nope"), "step"),                # no path yet (PR 2): no step joins
])
def test_a_wrong_kind_tag_place_or_more_than_one_line_is_named(item, wrong):
    # Sonic, 2026-11-12: "everything earns its place" — an item is one plain line; a fix is never something to try
    found = guide.problems(_release("3.0.4", [item]), has_card=help_cards.available, locate=_locate)
    assert len(found) == 1 and wrong in found[0]


def test_an_id_used_twice_an_odd_version_and_no_items_are_named():
    assert any("twice" in p for p in guide.problems(_release("3.0.4", [_item("a"), _item("a")])))
    assert any("version" in p for p in guide.problems(_release("3.0.x", [_item("a")])))
    assert guide.problems(_release("3.0.4", [])) == ["no items"]
    assert guide.problems([]) == ["not an object"]


def test_a_bad_file_is_left_out_and_said_and_never_takes_the_others_with_it(tmp_path):
    folder = str(tmp_path / "whats_new")
    _write(folder, _release("3.0.4", [_item("zh-cards", tags=("zh", "miner"))]))
    _write(folder, _release("3.0.5", [_item("x", kind="feature")]))           # a wrong kind
    _write(folder, _release("3.0.6", [_item("y")]), name="3.0.7")             # its name isn't its version
    with open(os.path.join(folder, "3.0.8.json"), "w", encoding="utf-8") as f:
        f.write("{ 半分")                                                    # half written
    said = []
    read = guide.read_notes(folder, log=said.append)
    assert [r.version for r in read] == ["3.0.4"] and len(said) == 3


# --- which releases show ----------------------------------------------------------------------------------------- #
def _releases():
    return tuple(guide.Release(v, "2026-11-1" + str(n), (guide.Item(f"i{n}", "new", "t", ("everyone",), None, v),))
                 for n, v in enumerate(("3.1.0", "3.0.10", "3.0.4", "3.0.3", "3.0.2")))


@pytest.mark.parametrize("seen, current, shown", [
    (None, "3.0.4", ["3.0.4"]),                     # nothing seen yet: this version's only
    ("3.0.2", "3.0.4", ["3.0.4", "3.0.3"]),         # two updates skipped: both, newest first
    ("3.0.4", "3.0.4", []),                         # seen
    ("3.0.4", "3.0.10", ["3.0.10"]),                # 10 after 4 (numbers, never text)
    ("3.0.10", "3.0.4", []),                        # went back a version: nothing new
    ("3.0.3", "alpha7", []),                        # an odd version: nothing
    ("bogus", "3.0.3", ["3.0.3"]),                  # an odd seen: as if nothing was seen
])
def test_unseen_is_newer_than_seen_up_to_this_version_newest_first(seen, current, shown):
    assert [r.version for r in guide.unseen(_releases(), seen, current)] == shown


# --- for you -------------------------------------------------------------------------------------------------------- #
def test_only_what_leads_somewhere_is_shown_yours_first_and_the_rest_folds():
    items = (guide.Item("fix-all", "fix", "t", ("everyone",), None, "3.0.4"),
             guide.Item("fix-mine", "fix", "t", ("miner",), None, "3.0.4"),
             guide.Item("tweak-books", "tweak", "t", ("books",), None, "3.0.4"),
             guide.Item("tweak-miner", "tweak", "t", ("miner",), "tab:needs", "3.0.4"),
             guide.Item("new-zh", "new", "t", ("zh", "miner"), None, "3.0.4"),
             guide.Item("new-ja", "new", "t", ("ja", "miner"), None, "3.0.4"),
             guide.Item("new-all", "new", "t", ("everyone",), None, "3.0.4"))
    shown = guide.arrange(guide.Release("3.0.4", "", items), {"everyone", "ja", "miner"})
    # Kantan-X's rule 2: shown only if it leads somewhere (a where); the rest folds, the learner's first
    assert [i.id for i in shown.for_you] == ["tweak-miner"]                 # Chinese only: left out
    assert [i.id for i in shown.others] == []
    assert [i.id for i in shown.fixes] == ["new-ja", "fix-mine", "new-all", "tweak-books", "fix-all"]


Row = __import__("collections").namedtuple("Row", "media audio")
View = __import__("collections").namedtuple("View", "rows finished goal")
Goal = __import__("collections").namedtuple("Goal", "works")
Month = __import__("collections").namedtuple("Month", "rows")


def test_the_librarys_kinds_come_from_current_goal_and_finished():
    view = View(rows=(Row("anime", ""),), finished=(Month((Row("lightnovel", ""),)),),
                goal=Goal(works=(Row("book", "🎧 With its audiobook"),)))
    assert guide.media_tags(view) == {"shows", "books", "audiobooks"}
    assert guide.media_tags(View((), (), None)) == set() and guide.media_tags(None) == set()
    assert guide.media_tags(View((Row("podcast", ""),), (), None)) == {"audiobooks"}


def test_the_profile_reads_only_whats_on_this_pc_and_a_missing_piece_counts_as_unused(monkeypatch):
    bare = guide.profile("ja", {})
    assert bare == {"everyone", "ja"}                                       # a fresh PC: nothing assumed
    practice = os.path.join(path_utils.get_user_files_path("ja"), "practice")
    os.makedirs(practice, exist_ok=True)
    with open(os.path.join(practice, "r1.json"), "w", encoding="utf-8") as f:
        json.dump({"round": {"words": 5}}, f)
    from app import anki_sync
    monkeypatch.setattr(anki_sync, "load_state", lambda language: {"last_sync": "2026-11-12T08:00:00"})
    tags = guide.profile("ja", {"connect_enabled": True}, View((Row("anime", ""),), (), None))
    assert {"piyo", "anki", "miner", "shows"} <= tags and "zh" not in tags and "books" not in tags

    def broken(_language):
        raise OSError("locked")
    monkeypatch.setattr(anki_sync, "load_state", broken)
    assert "anki" not in guide.profile("ja", {})                            # a failed check: not used, never a crash


# --- the state: per PC, never settings.json ------------------------------------------------------------------------ #
def test_the_glow_shows_once_per_new_version_and_seen_notes_stay_there_to_read_again(tmp_path):
    folder, state = str(tmp_path / "whats_new"), str(tmp_path / "local" / "guide.json")
    _write(folder, _release("3.0.4", [_item("zh-cards", tags=("zh", "miner"))]))
    _write(folder, _release("3.0.5", [_item("piyo-help", tags=("piyo",))]))
    first = guide.look("ja", {}, current="3.0.4", base=folder, path=state)
    assert first.glow and [s.release.version for s in first.releases] == ["3.0.4"]
    assert guide.mark_seen("3.0.4", path=state) is True
    assert guide.mark_seen("3.0.4", path=state) is False                    # nothing changed: nothing written (S19)
    again = guide.look("ja", {}, current="3.0.4", base=folder, path=state)
    assert not again.glow and [s.release.version for s in again.releases] == ["3.0.4"]
    updated = guide.look("ja", {}, current="3.0.5", base=folder, path=state)
    assert updated.glow and [s.release.version for s in updated.releases] == ["3.0.5"]


def test_a_damaged_state_reads_as_nothing_seen_and_a_version_without_notes_shows_nothing(tmp_path):
    folder, state = str(tmp_path / "whats_new"), str(tmp_path / "guide.json")
    _write(folder, _release("3.0.4", [_item("a")]))
    with open(state, "w", encoding="utf-8") as f:
        f.write("{ 壊れた")
    assert guide.look("ja", {}, current="3.0.4", base=folder, path=state).glow
    assert guide.look("ja", {}, current="3.0.9", base=folder, path=state) == guide.Look("3.0.9", (), False)
    assert guide.look("ja", {}, current="3.0.4", base=str(tmp_path / "none"), path=state).releases == ()


def test_the_state_lives_in_the_local_data_folder_and_settings_json_is_never_written(monkeypatch):
    from app import settings_manager

    def refuse(*_a, **_k):
        raise AssertionError("the guide wrote settings.json")
    monkeypatch.setattr(settings_manager, "save_settings", refuse)
    guide.mark_seen("3.0.4")
    assert os.path.dirname(guide.state_path()) == path_utils.get_local_data_path()
    assert guide.read_state()["seen"] == "3.0.4"


def test_the_guide_makes_no_network_call(monkeypatch):
    import socket

    def refuse(*_a, **_k):
        raise AssertionError("the guide reached for the network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    assert guide.look("zh", {"connect_enabled": True}, current=__version__, base=SHIPPED).releases


# --- the adversary's round (2026-11-12): the language gate, a new PC, seen only rises, the state's file ------------- #
@pytest.mark.parametrize("item_tags, learner, mine", [
    (("ja", "miner"), {"everyone", "ja"}, False),           # Japanese AND Connect: no Connect, not theirs
    (("ja", "miner"), {"everyone", "ja", "miner"}, True),
    (("zh", "miner"), {"everyone", "ja", "miner"}, False),  # the other language never theirs
    (("zh",), {"everyone", "zh"}, True),
    (("everyone",), {"everyone", "ja", "miner"}, False),    # everyone's is no one's in particular
    (("books", "audiobooks"), {"everyone", "zh", "audiobooks"}, True),
])
def test_a_language_tag_is_a_gate_and_the_rest_must_meet(item_tags, learner, mine):
    item = guide.Item("x", "new", "t", item_tags, None, "3.0.4")
    assert guide.yours(item, learner) is mine


def test_on_a_new_pc_setup_running_marks_this_version_seen_and_nothing_glows(tmp_path):
    folder, state = str(tmp_path / "whats_new"), str(tmp_path / "guide.json")
    _write(folder, _release("3.0.4", [_item("a")]))
    _write(folder, _release("3.0.5", [_item("b")]))
    first = guide.look("ja", {}, current="3.0.4", base=folder, path=state, fresh=True)
    assert not first.glow and [s.release.version for s in first.releases] == ["3.0.4"]
    assert guide.read_state(state)["seen"] == "3.0.4"
    assert guide.look("ja", {}, current="3.0.5", base=folder, path=state, fresh=True).glow    # seen before: an update


def test_going_back_a_version_never_lowers_seen(tmp_path):
    state = str(tmp_path / "guide.json")
    assert guide.mark_seen("3.0.5", path=state) is True
    assert guide.mark_seen("3.0.4", path=state) is False and guide.read_state(state)["seen"] == "3.0.5"
    assert guide.mark_seen("alpha7", path=state) is False


def test_a_failed_write_leaves_the_old_state_whole_and_another_versions_file_is_not_ours(tmp_path, monkeypatch):
    state = str(tmp_path / "guide.json")
    guide.mark_seen("3.0.4", path=state)

    def broken(*_a, **_k):
        raise OSError("disk full")
    with monkeypatch.context() as patched:
        patched.setattr(guide.json, "dump", broken)
        with pytest.raises(OSError):
            guide.mark_seen("3.0.5", path=state)
    assert guide.read_state(state)["seen"] == "3.0.4"                       # the old file, whole (atomic replace)
    with open(state, "w", encoding="utf-8") as f:
        json.dump({"version": 99, "seen": "9.9.9"}, f)
    assert guide.read_state(state) == {}                                    # a newer guide's file: not ours


def test_hato_and_junban_count_only_when_there(monkeypatch):
    from app import tools_entry
    monkeypatch.setattr(tools_entry, "read", lambda tool: {"cli": "hato-cli.exe"} if tool == "hato" else None)
    monkeypatch.setattr(help_cards, "module_present", lambda name: name == "junban")
    tags = guide.profile("ja", {"enable_junban": True})
    assert {"hato", "junban"} <= tags
    assert "junban" not in guide.profile("ja", {"enable_junban": False})
    monkeypatch.setattr(tools_entry, "read", lambda tool: None)
    assert "hato" not in guide.profile("ja", {})
    assert guide.media_tags(View((Row(None, ""),), (), None)) == {"shows"}   # no type: a video, as the store reads it
