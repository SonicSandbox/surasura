"""Standing lines (round 8 row 54): `app/services/standing.py` — every standing line's ✕ hides it until its state
changes — with the offline line's answers kept in the Needs-you seen file and the bar's failure in the status service.

Sonic: "I removed some video files + their subs. Now i get a message at the bottom: [PATH] isn't reachable; its 5
episodes are kept. … But, I can't remove that line. it just sits there."

What a wrong answer would cost a learner: a line he hid coming back at every start (or every look) and sitting there
again; a line hidden for good, so a folder that goes away again — or a newer failure — never says so; a failure hidden
off the bar and lost from *Needs you* too; a dismissal written into settings.json (his choices file).

Real folder names (made-up shows, the library's Japanese titles), the seen file in the test's own root.
"""
import json
import os
import sys

import pytest

from app import path_utils
from app.services import needs, standing
from app.services.jobs import JobRegistry
from app.services.status import StatusService

FOLDER = r"E:\アニメ\葬送のフリーレン"
OTHER = r"\\nas\video\薬屋のひとりごと"


def _sources(reachable, path=FOLDER, items=5, on=True):
    return [{"id": 1, "path": path, "on": on, "items": items, "reachable": reachable}]


def _summary(sources, language="ja"):
    return {"language": language, "sources": sources, "added": 0, "waiting": 0, "full": True}


# --- the keys ------------------------------------------------------------------------------------------------------ #
def test_each_line_has_a_key_naming_what_it_reports_and_its_kind():
    """A different state is a different key (a newer failure, another version or state, another reason); the same
    folder written another way is one key (the store's path_key), so it is never asked twice."""
    off = standing.offline_key(FOLDER)
    assert off.startswith("line:offline:") and standing.kind_of(off) == standing.OFFLINE
    if sys.platform == "win32":
        assert standing.offline_key(FOLDER.lower().replace("\\", "/")) == off
    assert standing.offline_key(OTHER) != off
    a = standing.failure_key("2026-10-22T09:00:00#1", "Generate stopped (exit code 1).")
    assert standing.kind_of(a) == standing.FAILURE
    assert a != standing.failure_key("2026-10-22T09:00:00#2", "Generate stopped (exit code 1).")
    assert standing.update_key("3.0.1", "available") != standing.update_key("3.0.2", "available")
    assert standing.update_key("3.0.1", "available") != standing.update_key("3.0.1", "waiting")
    assert standing.kind_of(standing.read_only_key("damaged")) == standing.READ_ONLY
    assert standing.kind_of("offline:e:\\anime") is None and standing.kind_of("item:3") is None   # Needs you's own


def test_a_hidden_line_stays_hidden_until_its_state_changes_or_its_trouble_ends_and_comes_back():
    hidden = standing.Hidden()
    v1, v2 = standing.update_key("3.0.1", "available"), standing.update_key("3.0.2", "available")
    assert hidden.shows(v1, standing.UPDATE)
    assert hidden.hide(v1) == 1 and hidden.hide(v1) == 0
    assert not hidden.shows(v1, standing.UPDATE)                      # ✕: hidden
    assert hidden.shows(v2, standing.UPDATE)                          # another version: back
    ro = standing.read_only_key("damaged")
    hidden.hide(v1, ro)
    assert not hidden.shows(v1, standing.UPDATE)
    assert not hidden.shows(None, standing.UPDATE)                    # the chip has nothing to say: its trouble ended
    assert hidden.shows(v1, standing.UPDATE)                          # ... so the same version later shows again
    assert not hidden.shows(ro, standing.READ_ONLY)                   # another kind's dismissal is left alone


# --- the offline line: the seen file --------------------------------------------------------------------------------- #
def test_an_offline_line_hidden_stays_hidden_after_a_restart_until_the_folder_is_back_then_asks_again():
    key = standing.offline_key(FOLDER)
    assert standing.keep("ja", [key]) == 1
    # a restart: nothing in memory, the next look's summary carries the seen file's answer
    said = standing.looked("ja", _summary(_sources(None)))            # the start's listing: not looked at yet
    assert said["kept_lines"] == {key}
    said = standing.looked("ja", _summary(_sources(False)))           # looked at: still away
    assert said["kept_lines"] == {key} and said["sources"] == _sources(False)
    assert standing.looked("ja", _summary(_sources(True)))["kept_lines"] == frozenset()   # back: its answer goes
    assert standing.kept("ja") == frozenset()
    assert standing.looked("ja", _summary(_sources(False)))["kept_lines"] == frozenset()  # away again: it asks again


def test_a_folder_no_longer_read_lets_its_answer_go_and_another_languages_file_is_its_own():
    key = standing.offline_key(FOLDER)
    standing.keep("ja", [key])
    standing.keep("zh", [standing.offline_key(OTHER)])
    assert standing.looked("ja", _summary([]))["kept_lines"] == frozenset()   # *Stop reading*: no longer a source
    assert standing.kept("zh") == {standing.offline_key(OTHER)}


def test_the_offline_answer_lives_in_the_seen_file_beside_needs_yous_and_never_in_settings():
    """The seen file's `answered` list holds it; Needs you's own prune (no lines read) never judges it, and the line's
    prune never judges Needs you's answers."""
    key = standing.offline_key(FOLDER)
    needs.answer("ja", [needs.item_key(7), "offline:e:\\anime"])
    standing.keep("ja", [key, "item:9"])                              # (only a line's key is kept by it)
    with open(needs.seen_path("ja"), encoding="utf-8") as f:
        assert json.load(f)["answered"] == [needs.item_key(7), "offline:e:\\anime", key]
    assert not os.path.exists(path_utils.get_settings_path())
    assert needs.prune("ja", None) == 0                               # Needs you's call without lines: nothing
    assert needs.prune("ja", None, lines=set()) == 1                  # the line's: its folder isn't away any more
    assert needs.read_answered("ja") == {needs.item_key(7), "offline:e:\\anime"}


def test_a_seen_file_that_cant_be_read_leaves_the_summary_as_it_was(capsys):
    with open(needs.seen_path("ja"), "w", encoding="utf-8") as f:
        f.write("{ not json")
    summary = _summary(_sources(False))
    assert standing.looked("ja", summary) is summary
    with open(needs.seen_path("ja"), encoding="utf-8") as f:
        assert f.read() == "{ not json"                              # never written over
    assert standing.looked("ja", {"language": "ja"}) == {"language": "ja"}    # no sources: nothing judged


# --- the bar's failure: the status service --------------------------------------------------------------------------- #
def test_a_failure_dismissed_leaves_the_bar_stays_in_needs_you_and_a_newer_one_shows_again():
    lines = {"generate": None}
    status = StatusService(JobRegistry(), providers={"generate": lambda: lines["generate"]})
    status.refresh()
    lines["generate"] = "Generate stopped (exit code 1)."
    status.refresh()
    snap = status.snapshot()
    assert snap.failure == "Generate stopped (exit code 1)." and snap.failure_key
    assert status.dismiss_failure(snap.failure_key) and not status.dismiss_failure(snap.failure_key)
    snap = status.snapshot()
    assert snap.failure is None and snap.failure_key is None
    assert [e.text for e in snap.needs_you] == ["Generate stopped (exit code 1)."]     # still listed
    status.refresh()
    assert status.snapshot().failure is None                         # asked again: the same failure stays hidden
    lines["generate"] = None                                          # it ran cleanly ...
    status.refresh()
    lines["generate"] = "Generate stopped (exit code 1)."             # ... and failed again, the same words
    status.refresh()
    assert status.snapshot().failure == "Generate stopped (exit code 1)."
    assert len(status.snapshot().needs_you) == 2
