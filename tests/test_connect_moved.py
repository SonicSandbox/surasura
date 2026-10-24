"""D5's Connect half and MV-2 (moves scope §4, Sonic's MV-2: yes): an episode whose show moved, as Connect and ▶ read it.

- **Moved where Surasura reads** (the store's look records the new origin and marks the old one `moved_to`, Kura's M4):
  Connect's pairing is the live record (`library.pairing_of` orders a marked origin after every live one), so Connect
  and ▶ find the video where it is now, without the video index; the pairing's version moves once (its fit checked
  once at the new place).
- **A mark is never trusted alone** (Kura's MV-A5): while the live record's video is gone and a marked one's is still
  on disk, that one is the episode's video (`library.Moved.was`, `runner.moved_video`).
- **Moved where Surasura doesn't read** (MV-2): Connect's *No video* names the folder the video left — *This episode's
  video isn't where it was (<folder>).* — only while the source folder it was read from is there (one offline is no
  move); ▶ says the same. *Find its folder* is the store's `add_source` and its look (the one way in, MV-1's join):
  once added, the episode's video is found at its new place and the line is gone.

What a wrong answer costs a learner: an episode left on *No video* (no cards) after he moved his show, the old dead
path read on every play, a line telling him a video moved when his drive is only unplugged, or a second copy of his
show. Japanese and Chinese alike: real subtitles from tests/Test Resources/, made-up show names, a few bytes as a
video; the "drives" are temp folders beside the test's data folder.
"""
import os
import shutil

import pytest

from app import library_store as ls
from app import sources
from app.connect import feed, fit_check, library, runner
from app.services import play
from tests.test_library_store_support import LANGUAGES, RESOURCES
from tests.connect.fake_steps import FakeSteps
from tests.test_sources_scan import _SHOWS, _drive, _empty, _fresh_module_state, _look, _settle, _video, _write  # noqa: F401

_SUBS = {"ja": "placed_episode.srt", "zh": "night_market.srt"}


def _subtitle(language):
    with open(os.path.join(RESOURCES, language, _SUBS[language]), encoding="utf-8-sig") as f:
        return f.read()


def _show(language, monkeypatch):
    """A source drive A holding one show folder (episode 01's subtitle and its video), looked at once -> (the store,
    A, the show's folder, the episode's item id, its video's path)."""
    monkeypatch.setattr(sources, "local_or_network", lambda path: "network")
    store, _data_dir = _empty(language)
    show = f"[Grp] {_SHOWS[language][0]}"
    a = _drive("driveA")
    folder = os.path.join(a, show)
    _write(os.path.join(folder, f"{show} - 01.{language}.srt"), _subtitle(language))
    video = _video(os.path.join(folder, f"{show} - 01.mkv"))
    _settle(a)
    first = _look(store, language, store.add_source(a), first=True)
    subs = [i for i in first["ids"] if store.item(i)["rel_path"].endswith(".srt")]
    assert len(subs) == 1, first
    record = library.pairing_of(store, subs[0])
    assert record["producer"] == "source" and os.path.normcase(record["video_path"]) == os.path.normcase(video)
    return store, a, folder, subs[0], video


def _steps():
    return runner.Steps({"connect_enabled": True, "anki_connect_url": "http://127.0.0.1:1"})


def _same(a, b):
    return a is not None and b is not None and os.path.normcase(os.path.abspath(a)) == os.path.normcase(
        os.path.abspath(b))


def _move(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    _settle(os.path.dirname(dst))


def _no_index(monkeypatch):
    """Connect's and ▶'s video index never asked: the episode is found by its own record."""
    def refuse(*_a, **_k):
        raise AssertionError("the video index was asked")
    monkeypatch.setattr(runner.Steps, "_videos", refuse)
    return lambda names, size=None: refuse()


@pytest.mark.parametrize("language", LANGUAGES)
def test_pairing_of_prefers_the_live_origin_after_a_move(language, monkeypatch):
    # why: the old origin row is the oldest and names a video, so before D5 it won — Connect stat'ed the dead path
    # and fell back on the index (or said No video). The marked row now comes after the live one; its version moves
    # once, so the fit is checked once at the video's new place
    store, a, folder, item, video = _show(language, monkeypatch)
    try:
        before = fit_check.version(library.pairing_of(store, item))
        b = _drive("driveB")
        moved = os.path.join(b, os.path.basename(folder))
        _move(folder, moved)
        _look(store, language, store.add_source(b), full=True)
        _look(store, language, store.sources()[0]["id"], full=True)
        marked = [r for k, r in ((k, r) for k, r in _records(store, item)) if r.get("moved_to")]
        assert marked, "the store's look marked the old origin (Kura's M4)"
        record = library.pairing_of(store, item)
        assert "moved_to" not in record, "Connect never reads the mark itself"
        assert os.path.normcase(record["origin"]).startswith(os.path.normcase(moved))
        assert os.path.normcase(record["video_path"]).startswith(os.path.normcase(moved))
        assert fit_check.version(record) != before
        assert fit_check.version(library.pairing_of(store, item)) == fit_check.version(record), "once, not each read"
    finally:
        store.close()


def _records(store, item):
    import json
    for key, text in store.conn.execute("SELECT content_key, pairing FROM pairings WHERE item_id = ?", (item,)):
        yield key, json.loads(text)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_moved_video_plays_from_its_new_place_without_the_index(language, monkeypatch):
    # why: the show moved into a folder Surasura reads; Connect's video and ▶'s file are the new place's, read from
    # the live record — never a lookup by name in the index, never the dead path
    store, a, folder, item, video = _show(language, monkeypatch)
    b = _drive("driveB")
    moved = os.path.join(b, os.path.basename(folder))
    _move(folder, moved)
    _look(store, language, store.add_source(b), full=True)
    _look(store, language, store.sources()[0]["id"], full=True)
    rel = store.item(item)["rel_path"]
    store.close()
    find = _no_index(monkeypatch)
    job = {"id": 1, "item_id": item}
    found = _steps().video(language, job)
    assert _same(found, os.path.join(moved, os.path.basename(video)))
    assert _steps().video_moved(language, job) is None, "found: nothing moved to say"
    record = play.pairing(language, item)
    path, why = play._find(language, rel, "anime", record, {}, find, _moved(language, item))
    assert _same(path, found) and why is None, "▶ and Connect never disagree"


def _moved(language, item):
    got = {}
    play.pairing(language, item, got)
    return got[item]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_wrong_mark_never_hides_the_video_still_in_its_old_place(language, monkeypatch):
    # why (Kura's MV-A5): the same bytes found elsewhere while the original was only briefly away mark it; if that
    # other copy then goes, the episode's video is still where it always was — a mark alone never makes No video
    store, a, folder, item, video = _show(language, monkeypatch)
    try:
        b = _drive("driveB")
        copy = shutil.copytree(folder, os.path.join(b, os.path.basename(folder)))
        _settle(b)
        hidden = folder + ".away"
        os.rename(folder, hidden)                       # briefly away (a sync client's rewrite)
        _look(store, language, store.add_source(b), full=True)
        os.rename(hidden, folder)
        assert any(r.get("moved_to") for _k, r in _records(store, item)), "the look marked it (the recorded case)"
        shutil.rmtree(copy)                             # the other copy goes; the old folder not listed again yet
    finally:
        store.close()
    _no_index(monkeypatch)
    assert _same(_steps().video(language, {"id": 1, "item_id": item}), video)


@pytest.mark.parametrize("language", LANGUAGES)
def test_moved_where_no_source_reads_says_where_it_was_then_find_its_folder_finds_it(language, monkeypatch):
    # why (MV-2): the show moved to a folder Surasura doesn't read — today's plain No video left the learner with
    # nothing to do. Connect's line names the old folder; *Find its folder* adds the folder he picks (the store's
    # add_source and its look: MV-1's join, no second show), and the episode's video is found there
    store, a, folder, item, video = _show(language, monkeypatch)
    rel = store.item(item)["rel_path"]
    c = _drive("driveC")
    moved = os.path.join(c, "2024 Fall", os.path.basename(folder))
    _move(folder, moved)
    _look(store, language, store.sources()[0]["id"], full=True)
    store.close()
    job = {"id": 1, "item_id": item}
    s = _steps()                                    # (its index asked, as for any No video: C is in none)
    assert s.video(language, job) is None
    assert os.path.normcase(s.video_moved(language, job)) == os.path.normcase(folder)
    line = runner.MOVED.format(folder=folder)
    assert line == f"This episode's video isn't where it was ({folder})."
    assert runner.no_video(line) and runner.moved_folder(line) == folder
    path, why = play._find(language, rel, "anime", play.pairing(language, item), {}, lambda *a, **k: None,
                           _moved(language, item))
    assert path is None and why == play.WHY["moved"].format(word="video", folder=folder)
    assert play.look(language, {item: (rel, "anime")}, find=lambda *a, **k: None) == {item: False}, \
        "▶ has nothing to open: it never shows"

    # *Find its folder*: the folder above the show picked, added as a source, then its look (SourceLooks._add's two)
    store = ls.open_store(language, *_dirs(language))
    try:
        root_c = store.add_source(os.path.dirname(moved))
        found = _look(store, language, root_c, full=True)
        assert found["added"] == 0 and found["attached"] >= 1, "it joins the show: no second copy (MV-1)"
    finally:
        store.close()
    assert _same(_steps().video(language, job), os.path.join(moved, os.path.basename(video)))
    assert _steps().video_moved(language, job) is None, "found: the line is gone"


def _dirs(language):
    from app.path_utils import get_data_path, get_user_files_path
    return get_data_path(language), get_user_files_path(language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unreachable_source_folder_is_never_called_a_move(language, monkeypatch):
    # why: a drive unplugged or a share offline takes the old folder with it; telling the learner his video moved
    # (and to find its folder) would be wrong — that is the offline line's, and plain No video here
    store, a, folder, item, video = _show(language, monkeypatch)
    store.close()
    away = a + ".unplugged"
    os.rename(a, away)
    try:
        job = {"id": 1, "item_id": item}
        assert _steps().video(language, job) is None
        assert _steps().video_moved(language, job) is None
    finally:
        os.rename(away, a)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_video_still_there_or_only_its_subtitle_gone_is_no_move(language, monkeypatch):
    # why: the line is for a video that left; a video in its place (a cloud placeholder too: not downloaded, not
    # moved) says nothing, and another program's record (hato's) is never judged by a source folder's rule
    store, a, folder, item, video = _show(language, monkeypatch)
    try:
        record = library.pairing_of(store, item)
        moved = library.moved_of(store, item, record)
    finally:
        store.close()
    assert runner.video_left(record, moved.root) is None
    assert runner.video_left(dict(record, producer="hato"), moved.root) is None
    assert runner.video_left(record, None) is None
    os.remove(video)
    assert os.path.normcase(runner.video_left(record, moved.root)) == os.path.normcase(folder)
    assert runner.video_left(record, moved.root, reachable=lambda root: False) is None
    # a video outside the source folder (on a drive of its own, maybe the one unplugged) is never called moved
    elsewhere = dict(record, video_path=os.path.join(os.path.dirname(a), "otherdrive", "x.mkv"))
    assert runner.video_left(elsewhere, moved.root) is None
    assert runner.video_left(dict(record, video_path=a + "-sibling" + os.sep + "x.mkv"), moved.root) is None,         "a folder whose name only starts like the source's is outside it"


def test_the_moved_line_is_a_no_video_wait_the_feed_names_and_the_rows_offer_find_its_folder():
    # why: the line must reach the learner as No video (amber, Needs you's card), carrying the folder to the row so
    # its status and ⋯ offer *Find its folder…*; any other reason is not a move
    folder = os.path.join("D:\\", "Anime", "[Grp] 夜市小记")
    line = runner.MOVED.format(folder=folder)
    for other in (runner.NO_VIDEO, runner.ON_BATTERY, "", None, "This episode's video isn't where it was ().",
                  "This episode's video isn't where it"):
        assert runner.moved_folder(other) is None, other
    assert runner.no_video(runner.NO_VIDEO) and not runner.no_video(runner.ON_BATTERY)
    record = {"running": False, "languages": {"zh": {"jobs": [
        {"item": 7, "job": 3, "state": "waiting", "reason": line},
        {"item": 8, "job": 4, "state": "waiting", "reason": runner.NO_VIDEO}]}}}
    built = feed.build(record, "zh")
    assert built.items[7].kind == feed.NO_VIDEO and built.items[7].moved == folder and built.items[7].tip == line
    assert built.items[8].kind == feed.NO_VIDEO and built.items[8].moved is None
    from app.services import needs, view_rows
    st = view_rows._connected(view_rows.Status("waiting", "Waiting", "", "dim"), built.items[7], "video")
    assert st.kind == "no_media" and st.moved == folder and line in st.tip and "Find its folder" in st.tip
    plain = view_rows._connected(view_rows.Status("waiting", "Waiting", "", "dim"), built.items[8], "video")
    assert plain.moved is None and "Find its folder" not in plain.tip
    assert needs._waits_on_video(line) and needs._waits_on_video(runner.NO_VIDEO)
    assert not needs._waits_on_video(runner.ON_BATTERY)


def test_a_job_waiting_on_its_moved_video_keeps_that_wait_while_another_wait_holds_every_job(tmp_path):
    # why: Anki closed (or the battery) holds every job, but one waiting on its video keeps its own line — the moved
    # one too, never overwritten by "Waiting for Anki"
    from app.connect.ledger import Ledger
    line = runner.MOVED.format(folder=os.path.join(str(tmp_path), "Old"))
    ledger = Ledger(str(tmp_path / "ledger.db"))
    try:
        with ledger.transaction():
            job = ledger.queue("ja", 5, "user", None, store_id="store-1")
        ledger.set_state(job, "waiting", reason=line)
        out = {"waiting": {}}
        runner._waiting_all(ledger, "ja", {}, out, runner.ANKI_CLOSED, False)
        assert out["waiting"] == {5: line}
        assert ledger.job_by_id(job)["reason"] == line
    finally:
        ledger.close()


class _KickedOnce(FakeSteps):
    """Item 1 waits on its moved video, item 2 on Anki Miner (so the run goes on looking); Connect is kicked before
    its second look (*Find its folder…*'s look), once."""

    def __init__(self, folder, plan, kick_at):
        super().__init__(folder, plan)
        self.video_asked, self.looks, self.kick_at = [], 0, kick_at

    def kicked(self):
        self.looks += 1
        return self.looks == self.kick_at

    def video(self, lang, job):
        self.video_asked.append(job["item_id"])
        return super().video(lang, job)


@pytest.mark.parametrize("kick_at, asked", [(2, 2), (None, 1)], ids=["kicked", "not-kicked"])
def test_a_kick_lets_a_job_parked_on_its_moved_video_go_again_in_the_same_run(tmp_path, kick_at, asked):
    # why: a Connect busy with other episodes runs for hours; after *Find its folder…* (its look kicks Connect) the
    # moved episode is looked at again at the next look, never only at Connect's next start. Unkicked, it stays
    # parked (one look a run: no battery drain)
    from app.connect.ledger import Ledger
    plan = {"queue": {"ja": [1, 2]}, "line": {"ja": [1, 2]}, "videos": {"1": None}, "miner_busy": True,
            "moved": {"1": os.path.join(str(tmp_path), "Old")}}
    steps = _KickedOnce(str(tmp_path), plan, kick_at)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        summary = runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=3)
    assert steps.video_asked.count(1) == asked
    assert summary["languages"]["ja"]["waiting"][1] == runner.MOVED.format(folder=os.path.join(str(tmp_path), "Old"))
