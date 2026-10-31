"""*Needs you*'s entries (W3.2 S3): `app/services/needs.py`, Qt-free, on views built from hand-made feed rows with real
Japanese and Chinese titles, Connect's record as `connect.status` builds it (and from a real ledger), and real folders of
real-named videos in temp folders.

Each test names the rule it holds and what a wrong answer would cost a learner: a gone subtitle offered a video (or a
video pushed through `relink`, IK-2), a whole unplugged drive offered *Remove* (IK-8), a badge that never stops counting
or never counts a new trouble (P1.2-1), a *Find videos* that guesses between two files, a seen file in settings.json.
"""
import json
import os
import subprocess
import sys

import pytest

from app.connect import runner
from app.services import needs
from app.services import view_rows as vr
from app.services.status import Entry as Failure

WORKS = {}


def work(wid, title, media="anime"):
    w = {"id": wid, "title": title, "title_by_user": 0, "titles": "[]", "folder_key": title, "anilist_id": None,
         "tmdb_id": None, "youtube_channel": None, "media_type": media, "media_type_by": None,
         "cover_source": "generated", "cover_ref": None, "cover_path": None, "cover_fetched_at": None,
         "cover_locked": 0, "feed_in": 1}
    WORKS[wid] = w
    return w


def items_of(spec):
    """spec: [(work_id, folder, [file names], {index: overrides})] -> {id: feed row}, all in NOW, in order."""
    out, iid = {}, 1
    for wid, folder, names, extra in spec:
        for k, name in enumerate(names):
            row = {"id": iid, "tier": "now", "ord": 1024.0 * iid, "rel_path": f"{folder}/{name}", "title": name,
                   "parent_folder": folder, "source_type": "subtitle", "availability": "available", "work_id": wid,
                   "piece_id": wid, "watched": 0, "mined_at": None, "pinned": None, "mine_asked": None,
                   "graduated_at": None, "in_learning_order": 1, "added_at": "2026-10-01T00:00:00Z", "feed_in": 1}
            row.update(extra.get(k, {}))
            out[iid] = row
            iid += 1
    return out


MISSING = {"availability": "missing"}
FRIEREN = "葬送のフリーレン"
YUUSHA = "勇者のくせになまいきだ"
KUSURI = "薬屋のひとりごと"
FRIEREN_DIR = f"HighPriority/{FRIEREN}"


def frieren_eps(a, b):
    return [f"[SubsPlease] {FRIEREN} - {n:02d} (1080p) [ABCD].ja.srt" for n in range(a, b + 1)]


def view_of(spec, line=20):
    return vr.build(items_of(spec), WORKS, {"mine_line": line, "soon_line": None})


def no_video_jobs(*item_ids):
    """Connect's record as `status._language` builds it: each job waiting on its video carries runner.NO_VIDEO."""
    return {"needs": [], "unseen": 0, "gaps": [],
            "jobs": [{"job": 100 + i, "item": i, "title": None, "kind": "mine", "state": "waiting",
                      "reason": runner.NO_VIDEO, "step": None, "words": 0, "made": 0, "not_made": {}}
                     for i in item_ids]}


@pytest.fixture(autouse=True)
def _works():
    WORKS.clear()
    work(1, FRIEREN)
    work(2, YUUSHA)
    work(3, KUSURI)
    work(4, "雪中悍刀行")
    yield


def kinds(entries):
    return [e.kind for e in entries]


# --- two kinds of card (IK-2) -------------------------------------------------------------------------------------- #
def test_a_gone_subtitle_and_a_missing_video_are_two_cards_with_their_own_answers_never_one():
    """IK-2: a content file gone (E8) is relinked, kept or removed; an episode with no video (n15) is found or linked.
    One card for both would offer a video for a missing subtitle, or `relink` a video over the subtitle."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 12), {0: MISSING})])
    out = needs.entries(view, connect=no_video_jobs(2, 3))
    assert kinds(out) == [needs.GONE, needs.NO_VIDEO]
    gone, video = out
    assert gone.title == f"{FRIEREN} · Ep 9's file is gone"
    assert [ln.label for ln in gone.lines] == ["Ep 9"] and gone.lines[0].item_id == 1
    assert gone.lines[0].rel_path == f"{FRIEREN_DIR}/{frieren_eps(9, 9)[0]}"
    assert gone.actions == ("choose_folder", "keep_words", "remove")
    assert gone.lines[0].actions == ("choose_file", "keep_words", "remove")
    assert gone.data["folder"] == FRIEREN_DIR
    assert video.title == f"{FRIEREN} · 2 episodes have no video"
    assert [(ln.label, ln.number, ln.item_id) for ln in video.lines] == [("Ep 10", 10, 2), ("Ep 11", 11, 3)]
    assert video.actions == ("find_videos", "link_these")          # alpha 4 M1: no *Mine the text only*
    # a video card never offers a gone file's answers, nor a gone card a video's
    assert not {"choose_file", "choose_folder", "remove"} & set(video.actions + video.lines[0].actions)
    assert not {"find_videos", "link_these", "choose_video"} & set(gone.actions + gone.lines[0].actions)
    assert all(ln.actions == ("choose_video",) for ln in video.lines)
    assert "mine_text_only" not in needs.WIRED_LATER


def test_a_show_whose_every_file_is_gone_still_gets_its_card_with_every_file():
    """E8's moved folder: every file gone. `view.needs` (W2.2's rule: in the top, unmined, before the last file on disk)
    lists only what the top waits on, so the card reads every missing file of Current — below the top and mined ones
    too; a library whose every file is gone has no `view.needs` at all."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(1, 3), {0: MISSING, 1: MISSING, 2: MISSING}),
                    (2, f"HighPriority/{YUUSHA}", [f"{YUUSHA} 第{n}話.srt" for n in range(1, 9)],
                     {6: MISSING, 7: dict(MISSING, mined_at="2026-10-02T09:00:00Z")})], line=4)
    assert [n.work_id for n in view.needs] == [1]               # Yuusha's Ep 7–8 are below the top
    out = needs.entries(view, connect=None)
    assert [(e.data["work_id"], [ln.label for ln in e.lines]) for e in out if e.kind == needs.GONE] == [
        (1, ["Ep 1", "Ep 2", "Ep 3"]), (2, ["Ep 7", "Ep 8"])]
    assert out[1].title == f"{FRIEREN} · 3 episodes' files are gone"
    alone = view_of([(1, FRIEREN_DIR, frieren_eps(1, 3), {0: MISSING, 1: MISSING, 2: MISSING})])
    assert alone.needs == () and [len(e.lines) for e in needs.entries(alone)] == [3]


def test_a_video_card_never_needs_connect_and_a_job_outside_current_is_ignored():
    """No Connect (off) → no video cards; a job naming an item the view doesn't hold isn't drawn under a wrong show."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {})])
    assert needs.entries(view, connect=None) == []
    other = no_video_jobs(999)
    other["jobs"].append(dict(other["jobs"][0], item=1, reason="Waiting for Anki"))
    assert needs.entries(view, connect=other) == []


# --- one show, three shows, the bulk answer ----------------------------------------------------------------------- #
def test_one_show_gets_its_cards_and_no_bulk_answer():
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {0: MISSING})])
    out = needs.entries(view, connect=no_video_jobs(2))
    assert needs.BULK not in kinds(out)


def test_three_shows_get_one_bulk_answer_first_with_their_counts():
    """Lean 4 / n15: *Find all missing videos (N in M shows)* on top once two shows or more wait on videos; *Keep all
    their words* · *Remove all* once two or more have files gone."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 11), {0: MISSING, 1: MISSING}),
                    (2, f"HighPriority/{YUUSHA}", [f"{YUUSHA} 第{n}話.srt" for n in (1, 2)], {0: MISSING}),
                    (3, f"HighPriority/{KUSURI}", [f"{KUSURI} - {n:02d}.srt" for n in (5, 6, 7)], {})])
    # videos missing for Frieren Ep 11, Kusuri Ep 5 + Ep 7, Yuusha Ep 2
    out = needs.entries(view, connect=no_video_jobs(3, 5, 6, 8))
    assert out[0].kind == needs.BULK and out[0].unseen is False
    assert out[0].actions == ("find_all", "keep_all", "remove_all")
    assert out[0].data["labels"]["find_all"] == "Find all missing videos (4 in 3 shows)"
    assert out[0].data["labels"]["remove_all"] == "Forget every missing file (3)"
    assert sorted(out[0].data["item_ids"]) == [1, 2, 4]
    # then the shows in Current's order, each its gone card before its video card
    assert [(e.kind, e.data["work_id"]) for e in out[1:]] == [
        (needs.GONE, 1), (needs.NO_VIDEO, 1), (needs.GONE, 2), (needs.NO_VIDEO, 2), (needs.NO_VIDEO, 3)]
    assert needs.badge(out) == 5                        # the bulk answer is never a trouble of its own


def test_only_two_video_shows_bring_find_all_without_the_gone_answers():
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {}),
                    (3, f"HighPriority/{KUSURI}", [f"{KUSURI} - {n:02d}.srt" for n in (5, 6)], {0: MISSING})])
    out = needs.entries(view, connect=no_video_jobs(1, 4))
    assert out[0].actions == ("find_all",)
    assert out[0].title == "2 episodes in 2 shows have no video"


# --- an offline root (E8, IK-8) ------------------------------------------------------------------------------------ #
def test_a_drive_offline_is_one_entry_without_remove_and_remove_all_never_counts_its_files():
    """IK-8: 312 files whose drive is only unplugged must never go to the trash in one click."""
    view = view_of([(1, "E-drive/Anime/" + FRIEREN, frieren_eps(1, 3), {0: MISSING, 1: MISSING, 2: MISSING}),
                    (2, f"HighPriority/{YUUSHA}", [f"{YUUSHA} 第{n}話.srt" for n in (1, 2)], {0: MISSING}),
                    (3, f"HighPriority/{KUSURI}", [f"{KUSURI} - {n:02d}.srt" for n in (5, 6)], {1: MISSING})])
    root = needs.Root(path="C:\\Surasura\\data\\ja\\E-drive", rel="E-drive", label="Drive E:", files=312)
    out = needs.entries(view, offline_roots=[root])
    off = [e for e in out if e.kind == needs.OFFLINE]
    assert len(off) == 1 and off[0].title == "Drive E: is offline — 312 files"
    assert "remove" not in off[0].actions and off[0].actions == ("keep_words",)
    assert off[0].data["item_ids"] == (1, 2, 3)
    # the drive's show has no card of its own; the bulk answer counts only the two other shows' files
    assert [e.data["work_id"] for e in out if e.kind == needs.GONE] == [2, 3]
    assert sorted(out[0].data["item_ids"]) == [4, 7] and out[0].data["labels"]["remove_all"] == "Forget every missing file (2)"
    # its count falls back on Current's files under it when the caller gives none
    one = needs.entries(view, offline_roots=[root._replace(files=None)])
    assert [e.title for e in one if e.kind == needs.OFFLINE] == ["Drive E: is offline — 3 files"]


def test_C1_a_reorder_of_current_keeps_the_offline_and_bulk_entries_equal_so_their_cards_stay():
    """C1 (M4.1 row 4): the offline entry's files (and the bulk answer's) followed Current's order, so every move made
    a "new" entry and the window built its card again under the style sheet. The same files are the same entry."""
    spec = [(1, "E-drive/Anime/" + FRIEREN, frieren_eps(1, 2), {}),
            (2, f"HighPriority/{YUUSHA}", [f"{YUUSHA} 第{n}話.srt" for n in (1, 2)], {0: MISSING}),
            (3, f"HighPriority/{KUSURI}", [f"{KUSURI} - {n:02d}.srt" for n in (5, 6)], {1: MISSING}),
            (4, "E-drive/Anime/" + KUSURI, [f"{KUSURI} - {n:02d}.srt" for n in (8, 9)], {})]
    items = items_of(spec)
    upside_down = {i: dict(r, ord=-r["ord"]) for i, r in items.items()}       # Current turned upside down
    before = vr.build(items, WORKS, {"mine_line": 20, "soon_line": None})
    after = vr.build(upside_down, WORKS, {"mine_line": 20, "soon_line": None})
    assert [r.work_id for r in after.rows] == [r.work_id for r in reversed(before.rows)]
    root = needs.Root(path="C:\\Surasura\\data\\ja\\E-drive", rel="E-drive", label="Drive E:")
    a, b = (needs.entries(v, offline_roots=[root]) for v in (before, after))
    for kind in (needs.OFFLINE, needs.BULK):
        assert next(e for e in a if e.kind == kind) == next(e for e in b if e.kind == kind), kind
    # the shows' cards still follow Current's order (the window moves them; none is built again)
    assert [e.data["work_id"] for e in b if e.kind == needs.GONE] == [3, 2]


def test_an_offline_drive_the_user_kept_leaves_the_page_and_stays_off_it(tmp_path):
    """Its *Keep its words* is answered by its key: the card goes, and a later look never brings it back."""
    view = view_of([(1, "E-drive/Anime/" + FRIEREN, frieren_eps(1, 2), {0: MISSING, 1: MISSING})])
    root = needs.Root(path="C:\\Surasura\\data\\ja\\E-drive", rel="E-drive", label="Drive E:", files=2)
    off = [e for e in needs.entries(view, offline_roots=[root]) if e.kind == needs.OFFLINE][0]
    assert needs.answer("ja", needs.answer_keys(off)) == 1
    out = needs.entries(view, offline_roots=[root], answered=needs.read_answered("ja"))
    assert [e for e in out if e.kind == needs.OFFLINE] == [] and [e for e in out if e.kind == needs.GONE] == []


def test_the_whole_library_offline_is_one_entry_that_holds_every_file(tmp_path):
    view = view_of([(1, FRIEREN_DIR, frieren_eps(1, 1), {0: MISSING})])
    roots = needs.find_offline("ja", [r.rel_path for r in view.rows[0].episodes], data_dir=str(tmp_path / "gone"))
    assert len(roots) == 1 and roots[0].rel == ""
    drive = os.path.splitdrive(str(tmp_path))[0]
    if drive:
        assert roots[0].label == f"Drive {drive.upper()}"
    out = needs.entries(view, offline_roots=roots)
    assert kinds(out) == [needs.OFFLINE] and out[0].title.endswith("is offline — 1 file")


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows's link to another drive")
def test_a_folder_linked_to_a_drive_that_isnt_there_is_offline_and_a_folder_simply_gone_is_not(tmp_path):
    """A library folder on another drive (a junction) whose drive is unplugged is offline; a moved folder isn't."""
    data = tmp_path / "data" / "ja"
    (data / "HighPriority").mkdir(parents=True)
    target = tmp_path / "E_drive" / "Anime"
    target.mkdir(parents=True)
    link = data / "HighPriority" / "Anime"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if made.returncode != 0:
        pytest.skip("mklink /J refused here")
    os.rmdir(target)                                # the drive unplugged: the junction dangles
    rels = [f"HighPriority/Anime/{FRIEREN}/{n}" for n in frieren_eps(1, 2)] + \
        [f"HighPriority/{YUUSHA}/{YUUSHA} 第1話.srt"]
    try:
        roots = needs.find_offline("ja", rels, data_dir=str(data))
    finally:
        os.rmdir(link)
    assert [(r.rel, r.label) for r in roots] == [("HighPriority/Anime", "Drive " + os.path.splitdrive(
        str(target))[0].upper())]


# --- seen and answered ---------------------------------------------------------------------------------------------- #
def test_seen_entries_stay_listed_and_stop_counting_and_a_new_gone_file_counts_again(tmp_path):
    """P1.2-1: seen stops the count, never the listing; a show whose second file goes missing is news again."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {0: MISSING})])
    first = needs.entries(view, seen=needs.read_seen("ja"))
    assert needs.badge(first) == 1
    assert needs.mark_seen("ja", [e.key for e in first]) == 1
    again = needs.entries(view, seen=needs.read_seen("ja"))
    assert len(again) == 1 and needs.badge(again) == 0
    worse = view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {0: MISSING, 1: MISSING})])
    later = needs.entries(worse, seen=needs.read_seen("ja"))
    assert needs.badge(later) == 1 and later[0].key != first[0].key


def test_the_seen_file_is_the_local_data_folders_written_whole_and_never_settings_json():
    """Lean 5: `needs_seen_<lang>.json` beside the window's state; nothing new → nothing written (S19); a damaged file
    reads as nothing seen, never an error; Japanese and Chinese keep their own."""
    from app import path_utils
    path = needs.seen_path("ja")
    assert os.path.dirname(path) == path_utils.get_local_data_path()
    assert os.path.basename(path) == "needs_seen_ja.json"
    settings = path_utils.get_settings_path()
    before = os.path.exists(settings) and os.path.getmtime(settings)
    assert needs.mark_seen("ja", ["gone:1:abc", "offline:e:\\anime"]) == 2
    stamp = os.stat(path).st_mtime_ns
    assert needs.mark_seen("ja", ["gone:1:abc"]) == 0 and os.stat(path).st_mtime_ns == stamp
    assert not os.path.exists(path + ".tmp")
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"version": 1, "seen": ["gone:1:abc", "offline:e:\\anime"], "answered": []}
    assert needs.read_seen("zh") == frozenset()
    assert (os.path.exists(settings) and os.path.getmtime(settings)) == before
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert needs.read_seen("ja") == frozenset() and needs.read_answered("ja") == frozenset()


def test_S3_keep_all_their_words_across_2500_gone_files_keeps_every_answer_and_every_seen_key():
    """S3: a count cap evicted answers — *Keep all their words* over 2,500 files kept only the last 2,000, and 500
    entries came back counted at once. No key falls off by age or count."""
    assert needs.answer("ja", [needs.item_key(i) for i in range(1, 2501)]) == 2500
    assert needs.mark_seen("ja", [f"gone:{i}:x" for i in range(2500)]) == 2500
    assert len(needs.read_answered("ja")) == 2500 and needs.item_key(1) in needs.read_answered("ja")
    assert len(needs.read_seen("ja")) == 2500 and "gone:0:x" in needs.read_seen("ja")


def test_S3_prune_takes_out_only_the_keys_whose_trouble_is_gone_so_a_file_gone_again_is_asked_again():
    """A kept file that comes back, then goes missing again, is news again (its old *Keep its words* went with it);
    a file still missing keeps its answer; a key of a kind the caller didn't read (Connect's, the rename asks, a
    drive's) is never judged; a view that isn't the store's prunes nothing."""
    gone = view_of([(1, FRIEREN_DIR, frieren_eps(9, 11), {0: MISSING, 1: MISSING})])
    card = needs.entries(gone)[0]
    needs.mark_seen("ja", [card.key, "video:1:abc", "ask:def", "offline:e:\\anime", "gap:7"])
    needs.answer("ja", [needs.item_key(1), needs.item_key(2), "offline:e:\\anime", "gap:7"])
    assert needs.entries(gone, answered=needs.read_answered("ja")) == []
    assert needs.prune("ja", gone) == 1, "only the card's seen key went: its files are answered, it isn't listed"
    back = view_of([(1, FRIEREN_DIR, frieren_eps(9, 11), {1: MISSING})])                  # Ep 9 found again
    assert needs.prune("ja", None) == 0 and needs.prune("ja", back._replace(mode="json")) == 0
    assert needs.prune("ja", back) == 1
    assert needs.read_answered("ja") == {needs.item_key(2), "offline:e:\\anime", "gap:7"}
    assert needs.read_seen("ja") == {"video:1:abc", "ask:def", "offline:e:\\anime", "gap:7"}
    stamp = os.stat(needs.seen_path("ja")).st_mtime_ns
    assert needs.prune("ja", back) == 0 and os.stat(needs.seen_path("ja")).st_mtime_ns == stamp, "nothing: no write"
    again = view_of([(1, FRIEREN_DIR, frieren_eps(9, 11), {0: MISSING, 1: MISSING})])     # Ep 9 gone once more
    out = needs.entries(again, seen=needs.read_seen("ja"), answered=needs.read_answered("ja"))
    assert [ln.label for ln in out[0].lines] == ["Ep 9"] and needs.badge(out) == 1
    # Connect read, no gap 7 and no video card left: theirs go too; asks read, none: the ask's goes
    assert needs.prune("ja", again, connect={"jobs": [], "needs": [], "gaps": []}, asks=()) == 4
    assert needs.read_seen("ja") == {"offline:e:\\anime"} and needs.read_answered("ja") == {needs.item_key(2),
                                                                                           "offline:e:\\anime"}


def test_N10_a_drive_kept_while_offline_is_asked_again_after_it_came_back_and_went_offline_again():
    """N10: *Keep their words* on an offline drive was kept for ever — the same drive offline next month stayed
    hidden. While it is offline the answer holds; once the drive is back (no longer among the roots), it goes."""
    view = view_of([(1, "E-drive/Anime/" + FRIEREN, frieren_eps(1, 3), {0: MISSING, 1: MISSING, 2: MISSING})])
    root = needs.Root(path="C:\\Surasura\\data\\ja\\E-drive", rel="E-drive", label="Drive E:", files=3)
    entry = [e for e in needs.entries(view, offline_roots=[root]) if e.kind == needs.OFFLINE][0]
    needs.answer("ja", needs.answer_keys(entry))
    needs.mark_seen("ja", [entry.key])
    assert needs.prune("ja", view, offline_roots=[root]) == 0, "still offline: the answer holds"
    assert needs.OFFLINE not in kinds(needs.entries(view, offline_roots=[root], answered=needs.read_answered("ja")))
    plugged = view_of([(1, "E-drive/Anime/" + FRIEREN, frieren_eps(1, 3), {})])
    assert needs.prune("ja", plugged, offline_roots=[]) == 2 and needs.read_answered("ja") == frozenset()
    later = needs.entries(view, offline_roots=[root], seen=needs.read_seen("ja"), answered=needs.read_answered("ja"))
    assert [e.kind for e in later] == [needs.OFFLINE] and needs.badge(later) == 1
def test_a_seen_file_write_that_fails_half_way_leaves_the_last_one_whole(monkeypatch):
    """Written beside it and swapped in: a crash or a full disk mid-write never truncates what was seen and kept."""
    needs.mark_seen("ja", [f"gone:1:{FRIEREN}"])
    needs.answer("ja", ["item:7"])
    real = json.dump

    def half(obj, f, **kw):
        f.write('{"version": 1, "seen": [')
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(needs.json, "dump", half)
    with pytest.raises(OSError):
        needs.mark_seen("ja", [f"gone:2:{YUUSHA}"])
    monkeypatch.setattr(needs.json, "dump", real)
    assert needs.read_seen("ja") == {f"gone:1:{FRIEREN}"} and needs.read_answered("ja") == {"item:7"}
def test_keep_its_words_takes_the_file_off_the_page_and_keep_all_takes_every_show(tmp_path):
    """L2.2 9b: *Keep its words* leaves the file missing and counted — the answer lives here, the store unchanged."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {0: MISSING, 1: MISSING}),
                    (2, f"HighPriority/{YUUSHA}", [f"{YUUSHA} 第{n}話.srt" for n in (1,)], {0: MISSING})])
    out = needs.entries(view)
    frieren = [e for e in out if e.kind == needs.GONE][0]
    needs.answer("ja", needs.answer_keys(frieren.lines[0]))
    out = needs.entries(view, answered=needs.read_answered("ja"))
    assert [ln.label for ln in out[1].lines] == ["Ep 10"]
    needs.answer("ja", needs.answer_keys(out[0]))       # the bulk answer's *Keep all their words*
    assert needs.entries(view, answered=needs.read_answered("ja")) == []


def test_mark_all_seen_writes_the_stores_here_and_connects_through_its_ledger(tmp_path):
    from app.connect.ledger import Ledger
    ledger_path = str(tmp_path / "ledger.sqlite")
    with Ledger(ledger_path) as led:
        led.need("ja", "not-timed", f"{FRIEREN} Ep 9: its subtitle isn't timed to its video", item_id=1)
    rec = needs.read_connect("ja", path=ledger_path)
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {1: MISSING})])
    out = needs.entries(view, connect=rec, seen=needs.read_seen("ja"))
    assert needs.badge(out) == 2
    assert needs.mark_all_seen("ja", out, connect_path=ledger_path) == (1, 1)
    out = needs.entries(view, connect=needs.read_connect("ja", path=ledger_path), seen=needs.read_seen("ja"))
    assert len(out) == 2 and needs.badge(out) == 0


# --- 9a's questions (IK-3) ------------------------------------------------------------------------------------------ #
def test_a_rename_ask_asks_which_missing_file_it_is_with_this_one_and_its_new():
    """IK-3: a file with two look-alikes is held out until asked; unasked, it never joins the library."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 9), {0: MISSING}),
                    (2, f"HighPriority/{YUUSHA}", [f"{YUUSHA} 第{n}話.srt" for n in (3,)], {0: MISSING})])
    ask = {"rel": f"Moved/{FRIEREN} - 09.srt", "size": 41230, "mtime_ns": 1, "candidates": [1, 2]}
    out = needs.entries(view, asks=[ask])
    entry = [e for e in out if e.kind == needs.ASK][0]
    assert entry.title == f"Is {FRIEREN} - 09.srt one of these 2 missing files?"
    assert entry.actions == ("its_new",) and entry.data["rel"] == ask["rel"]
    assert [(ln.item_id, ln.actions) for ln in entry.lines] == [(1, ("this_one",)), (2, ("this_one",))]
    # the line leaves the tier folder out (CLAUDE.md §6; Sonic's lean C, 2026-10-24); its path is the store's, unchanged
    assert entry.lines[0].text == f"{FRIEREN} · Ep 9 · was {FRIEREN}/{frieren_eps(9, 9)[0]}"
    assert entry.lines[0].rel_path == f"{FRIEREN_DIR}/{frieren_eps(9, 9)[0]}"
    assert entry.unseen
    assert not [e for e in needs.entries(view, asks=[ask], seen={entry.key}) if e.kind == needs.ASK][0].unseen


def test_asks_of_reads_each_candidates_path_and_leaves_out_one_gone_from_the_library():
    class Store:
        def rename_asks(self):
            return [{"rel": f"Moved/{KUSURI} - 05.srt", "candidates": [7, 8]}]

        def item(self, item_id):
            return {"rel_path": f"HighPriority/{KUSURI}/{KUSURI} - 05.srt", "title": f"{KUSURI} - 05.srt"} \
                if item_id == 7 else None
    asks = needs.asks_of(Store())
    assert asks == [{"rel": f"Moved/{KUSURI} - 05.srt", "candidates": [
        {"id": 7, "rel_path": f"HighPriority/{KUSURI}/{KUSURI} - 05.srt", "title": f"{KUSURI} - 05.srt"}]}]
    entry = needs.entries(None, asks=asks)[0]
    assert entry.title == f"Is {KUSURI} - 05.srt the one from {KUSURI}/{KUSURI} - 05.srt?"


def test_a_gone_files_line_leaves_the_tier_folder_out_never_naming_a_place_it_may_not_be():
    """CLAUDE.md §6 (IK-3 shots, 2026-10-23): a gone file's line read "not at HighPriority/…". In 3.0 a tier folder is
    no place (an item dragged to Goal still lives in HighPriority/…), so the line leaves it out (Sonic's lean C,
    2026-10-24, PROVISIONAL); a path outside a tier folder is shown as it is. Only the words change: the line keeps
    the store's path, which *Choose its file* and the answers act on."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 9), {0: MISSING}),
                    (2, f"LowPriority/{YUUSHA}", [f"{YUUSHA} 第3話.srt"], {0: MISSING}),
                    (3, f"GoalContent/{KUSURI}", [f"{KUSURI} - 05.srt"], {0: MISSING}),
                    (4, "Library/雪中悍刀行", ["雪中悍刀行 第01集.srt"], {0: MISSING})])
    texts = [ln.text for e in needs.entries(view) if e.kind == needs.GONE for ln in e.lines]
    assert texts == [f"Ep 9 · not at {FRIEREN}/{frieren_eps(9, 9)[0]}",
                     f"Ep 3 · not at {YUUSHA}/{YUUSHA} 第3話.srt",
                     f"Ep 5 · not at {KUSURI}/{KUSURI} - 05.srt",
                     "Ep 1 · not at Library/雪中悍刀行/雪中悍刀行 第01集.srt"]
    assert not any(f in t for t in texts for f in ("HighPriority", "LowPriority", "GoalContent", "NOW", "Soon", "Months"))
    assert needs.shown("") == "" and needs.shown("HighPriority") == "Current"
    assert needs.shown("Graduated/x.srt") == "Graduated/x.srt"


# --- failures and Connect's entries -------------------------------------------------------------------------------- #
def test_failures_are_listed_with_the_logs_and_count_until_the_status_service_marks_them_seen():
    out = needs.entries(None, failures=[Failure("Generate stopped: the list couldn't be written", "2026-10-15T09:00",
                                                False),
                                        Failure("The update couldn't be checked", "2026-10-14T21:00", True)])
    assert kinds(out) == [needs.FAILURE, needs.FAILURE]
    assert out[0].actions == ("open_logs", "save_logs")
    assert needs.badge(out) == 1


def test_each_connect_kind_offers_its_own_action_and_dismiss_and_a_gap_waits_for_its_callables():
    """Each kind's button calls what fixes it: *Mine anyway* for not-timed, *Ask hato again* for no-pairing, the logs
    for a failure; every one *Dismiss*. A gap's *Make their cards* has no callable yet (hidden), *Leave them* does."""
    rec = {"jobs": [], "unseen": 3, "needs": [
        {"id": 9, "kind": "no-pairing", "say": "3 files in hato's folder have no pairing from hato.", "item": None,
         "title": None, "at": "2026-10-15T08:00:00Z", "seen_at": None},
        {"id": 7, "kind": "not-timed", "say": f"{FRIEREN} Ep 10: not timed to its video", "item": 2, "title": "x",
         "at": "2026-10-14T08:00:00Z", "seen_at": "2026-10-14T09:00:00Z"},
        {"id": 5, "kind": "mine-failed", "say": "Anki Miner stopped twice", "item": 3, "title": None,
         "at": "2026-10-13T08:00:00Z", "seen_at": None},
        {"id": 4, "kind": "known-sync", "say": "Sync your known words first", "item": None, "title": None,
         "at": "2026-10-12T08:00:00Z", "seen_at": None}],
        "gaps": [{"id": 1, "since": "2026-10-01T00:00:00Z", "until": "2026-10-03T00:00:00Z", "items": [4, 5, 5],
                  "noticed": 1}]}
    out = needs.entries(None, connect=rec)
    assert [(e.kind, e.actions) for e in out] == [
        ("no-pairing", ("ask_hato", "dismiss")), ("not-timed", ("mine_anyway", "dismiss")),
        ("mine-failed", ("open_logs", "dismiss")), ("known-sync", ("dismiss",)),
        (needs.GAP, ("make_cards", "leave_them"))]
    assert [e.data["need_id"] for e in out[:4]] == [9, 7, 5, 4]       # newest first, as the record lists them
    assert [e.unseen for e in out] == [True, False, True, True, True]
    assert out[4].title == ("Connect lost track of your moves from 2026-10-01 to 2026-10-03: 2 episodes in the top 20 "
                            "have no cards")
    assert "make_cards" in needs.WIRED_LATER and "leave_them" not in needs.WIRED_LATER
    needs.answer("ja", needs.answer_keys(out[4]))
    assert needs.GAP not in kinds(needs.entries(None, connect=rec, answered=needs.read_answered("ja")))


def test_read_connect_reads_the_ledger_read_only_and_never_makes_one(tmp_path):
    from app.connect.ledger import Ledger
    path = str(tmp_path / "ledger.sqlite")
    assert needs.read_connect("ja", path=path)["needs"] == []
    assert not os.path.exists(path)
    with Ledger(path) as led:
        led.need("ja", "no-pairing", "2 files in hato's folder have no pairing from hato.")
        led.need("zh", "no-pairing", "1 file in hato's folder has no pairing from hato.")
        led.add_gap("ja", [3, 4])
    rec = needs.read_connect("ja", path=path)
    assert [n["kind"] for n in rec["needs"]] == ["no-pairing"] and rec["unseen"] == 1
    assert [g["items"] for g in rec["gaps"]] == [[3, 4]]
    assert [n["say"] for n in needs.read_connect("zh", path=path)["needs"]] == [
        "1 file in hato's folder has no pairing from hato."]


def test_no_library_and_a_json_mode_library_list_only_the_failures_and_connect():
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 9), {0: MISSING})])._replace(mode="json")
    out = needs.entries(view, failures=[Failure("Anki couldn't be reached", "2026-10-15", False)],
                        connect=no_video_jobs(1))
    assert kinds(out) == [needs.FAILURE]


# --- Find videos ---------------------------------------------------------------------------------------------------- #
def _touch(path, size=4096):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)
    return path


def _tree(root):
    out = {}
    for where, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(where, name)
            out[p] = (os.path.getsize(p), os.stat(p).st_mtime_ns)
    return out


@pytest.fixture
def library(tmp_path):
    """data/ja/HighPriority/<show>/ with the subtitles (and a `.ja.srt` beside a video), plus two video folders."""
    data = tmp_path / "data" / "ja"
    show = data / "HighPriority" / FRIEREN
    for name in frieren_eps(9, 14):
        _touch(str(show / name), 512)
    a, b = tmp_path / "Videos A", tmp_path / "Videos B"
    _touch(str(show / f"[SubsPlease] {FRIEREN} - 09 (1080p) [ABCD].mkv"))      # Ep 9 beside its subtitle ...
    _touch(str(a / "anime" / f"{FRIEREN} 09.mp4"))                            # ... and a copy in a video folder
    _touch(str(b / "ep10.mkv"))                                                # Ep 10 only in a video folder
    _touch(str(a / "Frieren S1" / f"{FRIEREN}" / "Episode 12.mkv"))            # Ep 12 twice: one under a folder
    _touch(str(b / "misc" / "Episode 12.mkv"))                                 # named like the show
    _touch(str(a / "x" / "Show 13.mkv"))                                       # Ep 13 twice, neither named like it
    _touch(str(b / "y" / "Other - 13.webm"))
    _touch(str(b / "notes 14.txt"))                                            # not a video
    settings = {"connect_video_folders": {"ja": [str(a), str(b)]}}
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 14), {})])
    entry = needs.entries(view, connect=no_video_jobs(1, 2, 3, 4, 5, 6))[0]
    return str(data), settings, entry, str(tmp_path)


def test_find_videos_matches_each_episode_by_number_the_shows_folder_first_and_never_guesses(library):
    """n15: Ep 9 → its own folder's video (and why, when a video folder has one too), Ep 10 → the only one, Ep 11 ✗,
    Ep 12 → the one in a folder named like the show, Ep 13 two strangers → no answer, Ep 14 a .txt is no video."""
    data, settings, entry, root = library
    before = _tree(root)
    got = needs.find_videos("ja", entry, settings, data_dir=data)
    assert _tree(root) == before                    # never writes, never moves, never touches a file's time
    by = {label: (path, why) for label, path, why in got}
    assert [label for label, _p, _w in got] == ["Ep 9", "Ep 10", "Ep 11", "Ep 12", "Ep 13", "Ep 14"]
    assert os.path.dirname(by["Ep 9"][0]) == os.path.join(data, "HighPriority", FRIEREN)
    assert by["Ep 9"][1] == (f"→ …\\[SubsPlease] {FRIEREN} - 09 (1080p) [ABCD].mkv ✓ found in its own folder "
                             "(1 more in your video folders)")
    assert os.path.basename(by["Ep 10"][0]) == "ep10.mkv" and by["Ep 10"][1] == "→ …\\ep10.mkv ✓ found"
    assert by["Ep 11"] == (None, '✗ nothing with "11" in its name')
    assert FRIEREN in by["Ep 12"][0] and by["Ep 12"][1].endswith("the one in a folder named like the show")
    assert by["Ep 13"] == (None, '✗ 2 videos have "13" in their names: choose one')
    assert by["Ep 14"] == (None, '✗ nothing with "14" in its name')


def test_find_videos_never_takes_a_cloud_placeholder(library, monkeypatch):
    data, settings, entry, _root = library
    real = runner._on_disk
    monkeypatch.setattr(runner, "_on_disk", lambda p: False if p.endswith("ep10.mkv") else real(p))
    got = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, settings, data_dir=data)}
    assert got["Ep 10"] == (None, '✗ "10" is still in the cloud: download it first')


def test_find_videos_never_takes_a_cloud_placeholder_in_the_shows_own_folder(library, monkeypatch):
    """The show's own folder holds only a placeholder for Ep 9: never opened, the video folders' copy is the answer."""
    data, settings, entry, _root = library
    real = runner._on_disk
    monkeypatch.setattr(runner, "_on_disk", lambda p: False if p.endswith("[ABCD].mkv") else real(p))
    got = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, settings, data_dir=data)}
    assert got["Ep 9"][0] is not None and os.path.basename(got["Ep 9"][0]) == f"{FRIEREN} 09.mp4"


def test_find_videos_never_guesses_between_two_videos_in_the_shows_own_folder(library):
    data, settings, entry, _root = library
    _touch(os.path.join(data, "HighPriority", FRIEREN, f"{FRIEREN} 第09話 (BD).mp4"))
    got = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, settings, data_dir=data)}
    assert got["Ep 9"] == (None, '✗ 2 videos have "09" in their names: choose one')


def test_find_videos_serves_the_no_video_card_only():
    """IK-2: a gone subtitle is relinked; it is never handed a video."""
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 9), {0: MISSING})])
    gone = needs.entries(view)[0]
    with pytest.raises(ValueError):
        needs.find_videos("ja", gone, {})


def test_find_videos_with_no_video_folders_and_an_unnumbered_name(tmp_path):
    work(5, "なぜ人は行列に並ぶのか", media="youtube")
    view = view_of([(5, "HighPriority/行列", ["なぜ人は行列に並ぶのか.srt"], {})])
    entry = needs.entries(view, connect=no_video_jobs(1))[0]
    got = needs.find_videos("ja", entry, {}, data_dir=str(tmp_path / "data" / "ja"))
    assert got == [(entry.lines[0].label, None, "✗ its name has no episode number to look for")]


def test_find_all_lists_each_folder_once_for_every_show(library, monkeypatch):
    data, settings, entry, _root = library
    work(6, YUUSHA)
    view = view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {}),
                    (6, f"HighPriority/{YUUSHA}", [f"{YUUSHA} 第{n}話.srt" for n in (10,)], {})])
    out = needs.entries(view, connect=no_video_jobs(1, 2, 3))
    listed = []
    real = needs._Lister._list
    monkeypatch.setattr(needs._Lister, "_list", staticmethod(lambda folder, deep: listed.append(folder)
                                                             or real(folder, deep)))
    found = needs.find_all("ja", out, settings, data_dir=data)
    assert set(found) == {e.key for e in out if e.kind == needs.NO_VIDEO}
    assert len(listed) == len(set(listed)) == 4     # two show folders + two video folders, each once
    yuusha = found[[e.key for e in out if e.kind == needs.NO_VIDEO][1]]
    assert yuusha[0][0] == "Ep 10" and yuusha[0][1].endswith("ep10.mkv")


def test_find_videos_looks_in_the_librarys_own_folders_before_the_folders_you_added(library, monkeypatch):
    """Alpha 6 try #5: Connect finds a video in the library's own folders (the store's sources), but *Find videos*
    looked only in the show's folder and *More video folders* — so a learner whose videos sit in the library, with no
    extra folder set, found nothing. The order now: the show's folder, the library's folders, the folders you added;
    the first place holding one decides (never a later place's guess). The library's folders hold every show: a video
    there is this show's only when named like it — another show's Ep 12 is never taken."""
    data, settings, entry, root = library
    shelf = os.path.join(root, "Anime library")
    mine = os.path.join(shelf, FRIEREN)
    _touch(os.path.join(mine, f"{FRIEREN} - 10 [WEB].mkv"))       # Ep 10: here and in an added folder
    _touch(os.path.join(mine, "Season 1", "Episode 11.mkv"))      # Ep 11: only here (a folder named like it)
    _touch(os.path.join(shelf, "misc", f"{FRIEREN} 13.mkv"))      # Ep 13: here by its file name; two strangers added
    _touch(os.path.join(shelf, "ぼっち・ざ・ろっく！", "Bocchi - 14.mkv"))   # Ep 14: another show's only
    asked = []
    monkeypatch.setattr(needs, "_sources", lambda language, data_dir: asked.append(language) or [shelf])
    by = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, settings, data_dir=data)}
    assert asked == ["ja"]
    assert os.path.dirname(by["Ep 9"][0]) == os.path.join(data, "HighPriority", FRIEREN), "its own folder first"
    assert by["Ep 10"][0] == os.path.join(mine, f"{FRIEREN} - 10 [WEB].mkv"), "the library's folders before yours"
    assert by["Ep 11"][0] == os.path.join(mine, "Season 1", "Episode 11.mkv"), "found with no folder added"
    assert by["Ep 12"][1].endswith("the one in a folder named like the show"), "the added folders, as before"
    assert by["Ep 13"][0] == os.path.join(shelf, "misc", f"{FRIEREN} 13.mkv"), \
        "one in the library's folders answers: the added folders' two strangers are never weighed"
    assert by["Ep 14"] == (None, '✗ nothing with "14" in its name'), "another show's episode is never this one's"


def test_a_library_folder_that_is_the_show_itself_is_named_by_its_own_name(library, monkeypatch):
    data, settings, entry, root = library
    show = os.path.join(root, "S", FRIEREN)                       # the source is the show's own folder
    _touch(os.path.join(show, "Episode 11.mkv"))
    monkeypatch.setattr(needs, "_sources", lambda language, data_dir: [show])
    by = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, settings, data_dir=data)}
    assert by["Ep 11"][0] == os.path.join(show, "Episode 11.mkv")


def test_a_season_folder_never_matches_another_shows_season_folder_in_the_library(tmp_path, monkeypatch):
    """A subtitle in `<show>/Season 1/` gave "Season 1" as the show's name, so another show's
    `Season 1/… - 10.mkv` in the library was "found". The show's name skips a season, specials or subtitles folder;
    a name too short to tell shows apart (`K`) names nothing."""
    work(7, "ぼっち・ざ・ろっく！")
    folder = "HighPriority/ぼっち・ざ・ろっく！/Season 1/Subs"
    view = view_of([(7, folder, ["ぼっち・ざ・ろっく！ - 10.ja.srt", "ぼっち・ざ・ろっく！ - 11.ja.srt"], {})])
    entry = needs.entries(view, connect=no_video_jobs(1, 2))[0]
    shelf = tmp_path / "Anime"
    _touch(str(shelf / FRIEREN / "Season 1" / "Episode 10.mkv"))                      # another show's Season 1
    _touch(str(shelf / "Bocchi the Rock" / "Season 1" / "Episode 11.mkv"))            # its own, by the title's
    _touch(str(shelf / "ぼっち・ざ・ろっく！" / "Season 1" / "Episode 11.mkv"))        # Japanese name only
    monkeypatch.setattr(needs, "_sources", lambda language, data_dir: [str(shelf)])
    by = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, {}, data_dir=str(tmp_path / "d"))}
    assert by["Ep 10"] == (None, '✗ nothing with "10" in its name'), "never Frieren's Season 1 episode"
    assert by["Ep 11"][0] == str(shelf / "ぼっち・ざ・ろっく！" / "Season 1" / "Episode 11.mkv")
    assert needs._show_name("HighPriority/K/Season 2/K - 01.srt") == "k" and not needs._telling("k")
    assert needs._telling("蟲師") and not needs._telling("jp")


def test_a_trashed_copy_in_a_library_folder_is_never_offered(library, monkeypatch):
    """The library's folders are walked as Connect's index walks them (the source's skip rule): a copy
    in `.trash` or a recycle bin is never a video to link."""
    data, settings, entry, root = library
    shelf = os.path.join(root, "Anime library")
    _touch(os.path.join(shelf, ".trash", FRIEREN, "Episode 11.mkv"))
    _touch(os.path.join(shelf, "$RECYCLE.BIN", FRIEREN, "Episode 11.mkv"))
    monkeypatch.setattr(needs, "_sources", lambda language, data_dir: [shelf])
    by = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, settings, data_dir=data)}
    assert by["Ep 11"] == (None, '✗ nothing with "11" in its name')


def test_find_videos_finds_nothing_in_the_librarys_folders_and_goes_on_to_the_ones_you_added(library, monkeypatch):
    data, settings, entry, root = library
    empty = os.path.join(root, "Anime library")
    os.makedirs(empty)
    monkeypatch.setattr(needs, "_sources", lambda language, data_dir: [empty])
    by = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, settings, data_dir=data)}
    assert os.path.basename(by["Ep 10"][0]) == "ep10.mkv", "nothing there: the added folders are looked in"
    assert by["Ep 13"] == (None, '✗ 2 videos have "13" in their names: choose one')


def test_find_videos_never_guesses_between_two_in_the_librarys_folders(library, monkeypatch):
    data, settings, entry, root = library
    shelf = os.path.join(root, "Anime library")
    _touch(os.path.join(shelf, FRIEREN, "BD", "Episode 10.mkv"))       # two releases of Ep 10, both the show's
    _touch(os.path.join(shelf, FRIEREN, "WEB", "Episode 10.mkv"))
    monkeypatch.setattr(needs, "_sources", lambda language, data_dir: [shelf])
    by = {label: (path, why) for label, path, why in needs.find_videos("ja", entry, settings, data_dir=data)}
    assert by["Ep 10"] == (None, '✗ 2 videos have "10" in their names: choose one'), \
        "two in the first place that holds any: no answer, never the added folder's one"


def test_find_all_reads_the_librarys_folders_once_for_every_card(library, monkeypatch):
    data, settings, entry, _root = library
    asked = []
    monkeypatch.setattr(needs, "_sources", lambda language, data_dir: asked.append(language) or [])
    needs.find_all("ja", [entry, entry], settings, data_dir=data)
    assert asked == ["ja"]


def test_the_librarys_folders_are_the_sources_the_store_reads(tmp_path):
    from tests.test_services_moves import Library
    lib = Library("ja")
    try:
        shelf = tmp_path / "アニメ"
        shelf.mkdir()
        lib.store.add_source(str(shelf))
        assert str(shelf) in needs._sources("ja", lib.data_dir)
    finally:
        lib.close()


def test_the_librarys_folders_are_nothing_with_no_store_to_read(tmp_path, monkeypatch):
    assert needs._sources("ja", str(tmp_path / "data" / "ja")) == []

    def broken(*_a, **_k):
        raise OSError("the library file is held by another program")
    monkeypatch.setattr(needs.library_store, "open_store", broken)
    assert needs._sources("ja", str(tmp_path / "data" / "ja")) == [], "a store that can't be read: the look goes on"

    def damaged(*_a, **_k):
        import sqlite3
        raise sqlite3.DatabaseError("database disk image is malformed")
    monkeypatch.setattr(needs.library_store, "open_store", damaged)
    assert needs._sources("ja", str(tmp_path / "data" / "ja")) == [], "a damaged store too"


# --- Chinese --------------------------------------------------------------------------------------------------------- #
def test_chinese_shows_read_the_same_way_and_find_their_videos_by_episode(tmp_path):
    title = "雪中悍刀行"
    folder = f"HighPriority/{title}"
    view = vr.build(items_of([(4, folder, [f"{title} 第{n:02d}集.zh.srt" for n in (8, 9, 10)], {0: MISSING})]),
                    WORKS, {"mine_line": 20}, language="zh")
    out = needs.entries(view, connect=no_video_jobs(2, 3))
    assert kinds(out) == [needs.GONE, needs.NO_VIDEO]
    assert out[0].title == f"{title} · Ep 8's file is gone"
    assert out[1].title == f"{title} · 2 episodes have no video"
    data = tmp_path / "data" / "zh"
    _touch(str(data / "HighPriority" / title / f"{title} 第09集.mp4"))
    vids = tmp_path / "视频"
    _touch(str(vids / title / f"{title} 第10集.mkv"))
    got = needs.find_videos("zh", out[1], {"connect_video_folders": {"zh": [str(vids)], "ja": []}},
                            data_dir=str(data))
    assert [(label, os.path.basename(path)) for label, path, _w in got] == [
        ("Ep 9", f"{title} 第09集.mp4"), ("Ep 10", f"{title} 第10集.mkv")]


def test_H_W5_an_answer_never_writes_over_a_seen_file_it_couldnt_read():
    """W5: a seen file that couldn't be read (half written by another window, held, a newer Surasura's) read as empty,
    and the next answer wrote the whole file back over every earlier *Keep its words*. A write-back reads strictly: a
    file it can't read fails the write and stays as it was; one that isn't there is a first answer."""
    assert needs.answer("ja", [needs.item_key(1)]) == 1                  # no file yet: written
    path = needs.seen_path("ja")
    for broken in ('{"version": 1, "seen": [], "answered": ["item:1"', '{"version": 2, "seen": [], "answered": []}'):
        with open(path, "w", encoding="utf-8") as f:
            f.write(broken)
        with pytest.raises(ValueError):
            needs.answer("ja", [needs.item_key(2)])
        with pytest.raises(ValueError):
            needs.mark_seen("ja", ["gone:1:abc"])
        with pytest.raises(ValueError):
            needs.prune("ja", view_of([(1, FRIEREN_DIR, frieren_eps(9, 10), {})]))
        with open(path, encoding="utf-8") as f:
            assert f.read() == broken, "never written over"
        assert needs.read_answered("ja") == frozenset()                   # (the page still reads it as nothing)


def test_find_videos_lists_a_video_by_connects_one_rule_never_a_mac_copy_or_a_small_typescript_file(tmp_path):
    # Michi (laptop fixes): Needs you's listing used its own extension test; a NAS's `._` copy and a TypeScript `.ts`
    # read as videos there while Connect refused them. Both now ask `runner.video_file`.
    (tmp_path / "星屑の街 - 05.mkv").write_bytes(b"\0" * 16)
    (tmp_path / "._星屑の街 - 05.mkv").write_bytes(b"\0" * 16)
    (tmp_path / "番組表.ts").write_text("export const 回 = 5;\n", encoding="utf-8")
    (tmp_path / "星屑の街 - 06.ts").write_bytes(b"\0" * runner.TS_MIN)
    got = sorted(os.path.basename(p) for p in needs._Lister().videos(str(tmp_path), False))
    assert got == ["星屑の街 - 05.mkv", "星屑の街 - 06.ts"]


def test_two_gone_pieces_of_one_work_give_the_same_row_whatever_order_they_are_listed_in():
    # why: two pieces of one work give the same row whatever order the view lists them in, so the card keeps its key,
    # lines and folder; a row that followed the listing order would change its key and its item ids between two looks.
    eps = frieren_eps(9, 10)
    listed_as_is = [
        view_of([(1, FRIEREN_DIR, eps, {0: MISSING, 1: MISSING})]),
        view_of([(1, FRIEREN_DIR, list(reversed(eps)), {0: MISSING, 1: MISSING})]),
        # ep 9 (item 1) is given a later place in the list than ep 10 (item 2): the row lists ep 10 first
        view_of([(1, FRIEREN_DIR, eps, {0: dict(MISSING, ord=99999.0), 1: MISSING})]),
    ]

    def gone_rows(out):
        return [(e.key, e.title, e.data, [line.key for line in e.lines]) for e in out if e.kind == needs.GONE]

    rows = [gone_rows(needs.entries(view, connect=no_video_jobs(1, 2))) for view in listed_as_is]
    assert rows[0], "the two missing pieces should give a gone row"
    for got in rows[1:]:
        assert got == rows[0]
