"""Kantan-B5 (a tester's report on 3.0.6 and his outside PR #421), Connect's side of *Change its video…*: an episode he
linked by hand to the NEXT episode's video was refused ("this is not the same episode") and parked; the window then
links the right video (the writer's `link_video` = `link.link`) and asks `actions.check_again` once it is saved.

What this holds, on a real store and a real ledger (the suite's real Japanese subtitles, `connect_helpers.library`;
synthetic videos; tsubasa stood in for, its answer by the video it is handed):
- the second link is the one Connect reads (`library.pairing_of`), one undoable change — Undo puts the first back;
- *Check again* after it fixes the *Not timed* line and queues the job, and Connect's next look checks the timing
  against the NEW video and mines it — never the wrong one again;
- the learner's files: the wrong video and the right one stay where they are; the library's items, their places and
  the placement log don't move.

What a wrong answer would cost: cards cut from another episode's video (its pictures and its audio for this episode's
lines), or the right video linked and the episode still parked as refused until the next start.
"""
import json
import os

from app.connect import actions, library, link
from app.connect.ledger import Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.test_p41_link import WORDS, _episode, _run, _state


class ByVideo:
    """tsubasa stood in for: CONFIDENT against the episode's own video, REFUSED against any other (29% of the
    reference lines: "not the same episode"); each call's video kept."""

    def __init__(self, right):
        self.right, self.videos = os.path.abspath(right), []

    def __call__(self, command, **_k):
        video = command[2]
        self.videos.append(video)
        outcome = "CONFIDENT" if os.path.abspath(video) == self.right else "REFUSED"
        answer = c.tsubasa_answer(outcome, [[None, -0.5]] if outcome == "CONFIDENT" else [])
        return type("Done", (), {"stdout": json.dumps(answer).encode("utf-8"), "returncode": 0})()


def _not_timed(lang="ja"):
    with Ledger() as ledger:
        return [n for n in ledger.needs(lang, listed=False) if n["kind"] == "not-timed" and n.get("fixed_at") is None]


def test_the_wrong_video_refused_then_the_right_one_linked_and_checked_again_is_mined_from_it(tmp_path):
    s, item = _episode()
    wrong = c.video("Dungeon Meshi S01E08-[1080p][BDRIP][x265.FLAC].mkv")
    right = c.video("Dungeon Meshi S01E07-[1080p][BDRIP][x265.FLAC].mkv")
    tsubasa = ByVideo(right)
    with s:
        link.link(s, item, wrong)                                  # his hand link, to E08's video
    steps, job, _picked, needs = _run(tmp_path, item, tsubasa)
    assert job["state"] == "waiting" and steps.anki.words() == []
    assert [n["kind"] for n in needs] == ["not-timed"], "refused: the card he saw"
    assert tsubasa.videos == [os.path.abspath(wrong)]
    with c.store() as s:
        before = _state(s)
        change = link.link(s, item, right)                         # *Change its video…*'s write
        assert change is not None and _state(s) == before, "only the pairing: no item added, nothing moved"
        assert library.pairing_of(s, item)["video_path"] == os.path.abspath(right), "the newest link is read"
    assert actions.check_again("ja", item) is True                 # ... then its check, once the link is saved
    assert _not_timed() == [], "the refused line is fixed: the card goes"
    with Ledger() as ledger:
        assert ledger.job("ja", item)["state"] == "queued"
    steps, job, picked, needs = _run(tmp_path, item, tsubasa)
    assert job["state"] == "done" and sorted(steps.anki.words()) == sorted(w for w, _r in WORDS)
    assert picked["video"] == os.path.abspath(right) and picked["offset"] == -0.5, "cut from E07's own video"
    assert tsubasa.videos[-1] == os.path.abspath(right) and os.path.abspath(wrong) not in tsubasa.videos[1:], \
        "checked against the new video, never the wrong one again"
    assert needs == [] and os.path.isfile(wrong) and os.path.isfile(right), "his videos stay where they are"


def test_undo_of_the_change_puts_the_first_video_back(tmp_path):
    s, item = _episode()
    wrong = c.video("Dungeon Meshi S01E08-[1080p][BDRIP][x265.FLAC].mkv")
    right = c.video("Dungeon Meshi S01E07-[1080p][BDRIP][x265.FLAC].mkv")
    with s:
        link.link(s, item, wrong)
        change = link.link(s, item, right)
        s.undo(change)
        assert library.pairing_of(s, item)["video_path"] == os.path.abspath(wrong), "one change: Undo takes it back"
        again = link.link(s, item, right)
        assert again is not None and library.pairing_of(s, item)["video_path"] == os.path.abspath(right), \
            "and it can be changed again after"


def test_a_check_with_nothing_waiting_on_its_timing_writes_nothing_after_the_link(tmp_path):
    """The episode no longer waits on its timing (Connect checked it meanwhile, or it was never refused): the link
    stands, the check queues nothing — the window says the new video is linked and checked in turn."""
    s, item = _episode()
    with s:
        link.link(s, item, c.video("Dungeon Meshi S01E07-[1080p][BDRIP][x265.FLAC].mkv"))
    _run(tmp_path, item, ByVideo(c.video("Dungeon Meshi S01E07-[1080p][BDRIP][x265.FLAC].mkv")))
    assert actions.check_again("ja", item) is False


def test_picking_an_earlier_video_again_makes_it_the_one_read_and_undo_puts_the_later_back(tmp_path):
    """The adversary's case: E07, then E08, then E07 again. E07's link is still the episode's own row, so the store
    would see the same record and write nothing — the episode left on E08 with nothing said. It is written again
    (stamped), one change; its Undo puts E08 back; picking the newest again is the same link: nothing written."""
    s, item = _episode()
    first = c.video("Dungeon Meshi S01E07-[1080p][BDRIP][x265.FLAC].mkv")
    second = c.video("Dungeon Meshi S01E08-[1080p][BDRIP][x265.FLAC].mkv")
    with s:
        link.link(s, item, first)
        link.link(s, item, second)
        again = link.link(s, item, first)
        assert again is not None, "a change: never silently nothing"
        assert library.pairing_of(s, item)["video_path"] == os.path.abspath(first)
        assert link.link(s, item, first) is None, "the newest picked again: the same link, nothing written"
        s.undo(again)
        assert library.pairing_of(s, item)["video_path"] == os.path.abspath(second), "Undo: E08 again"
        rows = s.conn.execute("SELECT COUNT(*) FROM pairings WHERE item_id = ?", (item,)).fetchone()[0]
    assert rows == 2, "one row a video, never a pile"
