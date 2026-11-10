"""3.0's video-only shows (SRC K5, the RUNBOOK's SRC-2 (video) row and S9): a show folder holding videos and no
subtitle yet waits in New arrivals, one item per video marked *no subtitles yet* (`availability = 'waiting'`); it is
never counted, read or mined; when its subtitle arrives the same item takes it in place, silently; a Remove keeps the
video and its later subtitle out.

Why these matter: a waiting item has no text. Counted, Generate would read a file that isn't there (a missing item
keeps counting, 9b); placed by its subtitle as a new row, the show would appear twice; marked missing by the sync, it
would read as a lost file; dropped by a rebuild, the show would vanish from New arrivals. Every test runs for Japanese
and Chinese alike under the per-test SURASURA_TEST_ROOT, with real subtitles from tests/Test Resources/, tiny fake
.mkv bytes and made-up show names in a temp "source" folder.
"""
import json
import os

import pytest

from app import analyzer
from app import library_store as ls
from tests.test_library_store_sources import _empty, _events, _exclusions, _found, _source_root, _tier
from tests.test_library_store_support import LANGUAGES, migrated, names, roots

_NOW = ls.TIERS["now"][0]
_MKV = b"\x1aE\xdf\xa3\x9fB\x86\x81\x01B\xf7\x81\x01" + bytes(48)    # an EBML header: the start of a real .mkv


def _video(src, show, name, key=None):
    """A video in the source folder and its found-record as the scan hands it over: the video keys, no text copy;
    `rel` = `Library/<show>/<video name>` (no file is made there)."""
    path = os.path.join(src, *show.split("/"), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(_MKV + name.encode("utf-8"))
    st = os.stat(path)
    return {"origin": path, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "show": show,
            "rel": f"{ls.CONTENT_FOLDER}/{show}/{name}", "video_path": path, "video_size": st.st_size,
            "video_key": key}


def _subtitle(language, data_dir, src, video, file_name, n, key=True):
    """The video's subtitle found later, beside it, with its video's keys (`key=False`: the path only)."""
    show = video["show"]
    return _found(language, data_dir, src, show, file_name, n, video_path=video["video_path"],
                  video_size=video["video_size"], **({"video_key": video["video_key"]} if key else {}))


def _row(store, item_id):
    return store.conn.execute("SELECT tier, ord, rel_path, availability, size, mtime_ns FROM items WHERE id = ?",
                              (item_id,)).fetchone()


# --- a video-only show waits (SRC-2 (video)) -------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("first", (False, True))
def test_a_video_only_show_waits_in_new_arrivals_with_no_file_made(language, first):
    """One item per video, in New arrivals even on setup's first scan (it is shown, never Current's), `waiting`, at
    `Library/<show>/<video name>` with no file made there; its origin row keyed by the video's path (B1), the record
    carrying the video keys."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[70]
    with store:
        root = store.add_source(src)
        videos = [_video(src, show, f"ep{n}.mkv", f"v1-{n}") for n in (2, 1)]
        change = store.take_in(root, videos, first=first)
        assert _tier(store, "arrivals") == [f"Library/{show}/ep1.mkv", f"Library/{show}/ep2.mkv"]
        assert sorted(change.placed.values()) == ["arrivals", "arrivals"]
        assert {store.item(i)["availability"] for i in change.added} == {"waiting"}
        assert {store.item(i)["size"] for i in change.added} == {None}
        assert not os.path.exists(os.path.join(data_dir, ls.CONTENT_FOLDER))            # never a file made
        for v in videos:
            key = ls.origin_key(v["video_path"])
            item, text = store.conn.execute("SELECT item_id, pairing FROM pairings WHERE content_key = ?",
                                            (key,)).fetchone()
            record = json.loads(text)
            assert record["video_key"] == v["video_key"] and record["origin"] == os.path.abspath(v["origin"])
            assert store.item(item)["rel_path"] == v["rel"]
        assert store.take_in(root, [dict(videos[0])]).skipped["known"]                   # found again: nothing new


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_show_stays_in_new_arrivals_whatever_the_rules_or_the_switch(language):
    """A placing rule never takes a waiting item out of New arrivals (it would sit in Current with nothing to read),
    and with New arrivals off it still waits there: it is what that list is for."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        ruled = store.take_in(root, [_video(src, w[81], "ep1.mkv", "v1-k")], rules={f"source:{root}": "goal"})
        assert list(ruled.placed.values()) == ["arrivals"] and store.ids("goal") == []
        store.set_library_options(arrivals_on=False)
        off = store.take_in(root, [_video(src, w[82], "ep1.mkv", "v1-l")])
        assert list(off.placed.values()) == ["arrivals"] and store.ids("now") == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_item_is_never_counted_read_or_mined(language):
    """Not counted: with a waiting item in New arrivals, and one moved into 6+ Months, the store's schedule and
    `resolve_found_files` (Generate's list, which keeps a missing file: 9b) are what they were without it; the mine
    line passes over one at the top of NOW."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    src = _source_root()
    w = names(language)
    with store:
        before = store.schedule()
        found = analyzer.resolve_found_files(language, verbose=False, schedule=before, missing=True)
        mined = store._mine_ids(5)
        root = store.add_source(src)
        waiting = store.take_in(root, [_video(src, w[71], "ep1.mkv", "v1-a"),
                                       _video(src, w[72], "ep1.mkv", "v1-b")]).added
        store.move([waiting[1]], "goal", after_id=store.ids("goal")[-1])
        assert store.ids("goal")[-1] == waiting[1]
        assert store.schedule() == before
        assert analyzer.resolve_found_files(language, verbose=False, schedule=store.schedule(), missing=True) == found
        store.move([waiting[0]], "now", before_id=store.ids("now")[0])
        assert store.ids("now")[0] == waiting[0] and store._mine_ids(5) == mined


@pytest.mark.parametrize("language", LANGUAGES)
def test_has_content_and_the_read_only_schedule_pass_over_waiting_items(language):
    store, data_dir = _empty(language)
    _d, user_files_dir = roots(language)
    src = _source_root()
    with store:
        root = store.add_source(src)
        item = store.take_in(root, [_video(src, names(language)[73], "ep1.mkv", "v1-c")]).added[0]
        store.move([item], "now")
        assert store.has_content() is False and store.schedule()[_NOW] == []
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    with open(ls.manifest_path(user_files_dir), encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["schedule"][_NOW] == []                                    # the copy's schedule leaves it out (S9)
    schedule = ls.read_only_schedule(language, data_dir, user_files_dir)
    assert all(schedule[ls.TIERS[t][0]] == [] for t in ls.ANALYSED)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_sync_never_marks_a_waiting_item_missing_or_back(language):
    """A waiting item's path holds no file, on purpose: the disk sync's went / came pass over it, in New arrivals and
    in Current, so it never reads as a lost file (nor as one found again)."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        items = store.take_in(root, [_video(src, w[74], "ep1.mkv", "v1-d"), _video(src, w[75], "ep1.mkv", "v1-e")]).added
        store.move([items[1]], "now")
        before = store.versions()
        assert store.sync_disk() is None and store.versions() == before
        assert {store.item(i)["availability"] for i in items} == {"waiting"}


# --- its subtitle fills the gap, silently ---------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("by_key", (True, False))
def test_a_subtitle_of_a_waiting_video_fills_its_item_in_place_silently(language, by_key):
    """The subtitle (matched by its video's key, or by the video beside it) is the waiting item: the same id, tier and
    place, now at the copy and available; no placement event (it was shown already); both origin rows kept. Another
    episode's subtitle joins the show's run as a new row."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[76]
    with store:
        root = store.add_source(src)
        v1, v2 = _video(src, show, "ep1.mkv", "v1-f1"), _video(src, show, "ep2.mkv", "v1-f2")
        waiting = store.take_in(root, [v1, v2]).added
        tier, ord_, *_rest = _row(store, waiting[0])
        events = _events(store)
        sub = _subtitle(language, data_dir, src, v1, "ep1.ja.srt", 1, key=by_key)
        change = store.take_in(root, [sub])
        assert change.added == [] and change.attached == [waiting[0]]
        assert _row(store, waiting[0]) == (tier, ord_, sub["rel"], "available", os.path.getsize(
            os.path.join(data_dir, *sub["rel"].split("/"))), _row(store, waiting[0])[5])
        item = store.item(waiting[0])
        assert item["title"] == "ep1.ja.srt" and item["source_type"] == "subtitle"      # the copy's own entry
        assert _events(store) == events                                    # silent: no event at all
        assert store.text_moved() == [], "D7a: new bytes in place are never a move note for the token store"
        keys = {r[0] for r in store.conn.execute("SELECT content_key FROM pairings WHERE item_id = ?", (waiting[0],))}
        assert keys == {ls.origin_key(v1["video_path"]), ls.origin_key(sub["origin"])}
        assert store.item(waiting[1])["availability"] == "waiting"
        assert _tier(store, "arrivals") == [sub["rel"], v2["rel"]]
        assert store.take_in(root, [dict(sub)]).skipped["known"]
        other = _found(language, data_dir, src, show, "ep3.ja.srt", 3)
        new = store.take_in(root, [other]).added
        assert len(new) == 1 and _tier(store, "arrivals") == [sub["rel"], v2["rel"], other["rel"]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_filled_item_in_current_counts_from_then(language):
    """Moved into Current while waiting, the item is in Generate's list once its subtitle is in, at its place."""
    store, data_dir = _empty(language)
    src = _source_root()
    with store:
        root = store.add_source(src)
        v = _video(src, names(language)[77], "ep1.mkv", "v1-g")
        item = store.take_in(root, [v]).added[0]
        store.move([item], "now")
        assert store.schedule()[_NOW] == []
        sub = _subtitle(language, data_dir, src, v, "ep1.srt", 1)
        store.take_in(root, [sub])
        assert [e["physical_path"] for e in store.schedule()[_NOW]] == [sub["rel"]] and store.has_content()


# --- Remove keeps it out (S6) ---------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_waiting_video_keeps_its_later_subtitle_out(language):
    """Remove of a waiting item writes its exclusion (the video's path, the video key in the note); its subtitle found
    later — by the video's key or by the video beside it — is kept out too. Put back brings it back waiting."""
    store, data_dir = _empty(language)
    src = _source_root()
    with store:
        root = store.add_source(src)
        v = _video(src, names(language)[78], "ep1.mkv", "v1-h")
        item = store.take_in(root, [v]).added[0]
        removed = store.remove([item])
        assert _exclusions(store) == [(root, ls.path_key(os.path.abspath(v["video_path"])), "removed",
                                       {"size": v["size"], "sha256": None, "video_key": "v1-h"})]
        assert store.take_in(root, [dict(v)]).skipped["excluded"]
        sub = _subtitle(language, data_dir, src, v, "ep1.srt", 1)
        assert store.take_in(root, [sub]).skipped["excluded"]
        sub2 = _subtitle(language, data_dir, src, v, "ep1.ja.ass", 2, key=False)
        assert store.take_in(root, [sub2]).skipped["excluded"]
        assert _tier(store, "arrivals") == []
        store.restore(removed.trash_ids)
        assert store.item(item)["availability"] == "waiting" and _exclusions(store) == []


# --- the copy (S9) --------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_rebuild_from_the_copy_keeps_waiting_items_waiting_in_their_places(language):
    """A new PC rebuilds from the copy: a waiting item in New arrivals and one moved into NOW come back with their ids,
    places and records, still waiting (their paths hold no content file); the copy's schedule never lists them."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    src = _source_root()
    w = names(language)
    root = store.add_source(src)
    items = store.take_in(root, [_video(src, w[79], "ep1.mkv", "v1-i"), _video(src, w[80], "ep1.mkv", "v1-j")]).added
    store.move([items[1]], "now", after_id=store.ids("now")[1])
    order = {t: store.ids(t) for t in ls.TIERS}
    pairs = store.conn.execute("SELECT content_key, item_id, pairing FROM pairings ORDER BY content_key").fetchall()
    rows = {i: _row(store, i)[2:] for i in items}
    schedule = store.schedule()
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    with open(ls.manifest_path(user_files_dir), encoding="utf-8") as f:
        doc = json.load(f)
    listed = {e["physical_path"] for p in ls.PHASES for e in doc["schedule"][p]}
    assert not any(r[0] in listed for r in rows.values())
    db = store.db_path
    store.close()
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.rename(db + suffix, db + suffix + ".elsewhere")
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    store = ls.open_store(language, data_dir, user_files_dir)
    with store:
        assert {t: store.ids(t) for t in ls.TIERS} == order
        assert {i: _row(store, i)[2:] for i in items} == rows
        assert store.conn.execute("SELECT content_key, item_id, pairing FROM pairings ORDER BY content_key"
                                  ).fetchall() == pairs
        assert store.schedule() == schedule
        assert store.item(items[1])["title"] == "ep1.mkv"                  # its entry came back with it


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_library_with_no_waiting_item_copies_as_before(language):
    """No waiting item: the copy holds no `waiting` list and is the same bytes when written again."""
    store = migrated(language)
    data_dir, user_files_dir = roots(language)
    store.close()
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        first = f.read()
    assert "waiting" not in json.loads(first.decode("utf-8"))["surasura_library"]
    assert ls.maintain(language, data_dir, user_files_dir) in (ls.EXIT_DONE, ls.EXIT_NOTHING)
    with open(ls.manifest_path(user_files_dir), "rb") as f:
        assert f.read() == first


# --- fix round A (batch 1's Haiku register, H9) --------------------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("subtitle", ("ep1.srt", "ep1.ass"))
def test_a_waiting_video_and_its_subtitle_in_one_batch_are_one_item(language, subtitle):
    """H9: a video's waiting record and its subtitle handed over in ONE batch — the video sorted first (`ep1.mkv`
    before `ep1.srt`) or the subtitle first (`ep1.ass` before `ep1.mkv`) — are one item, available at the copy, both
    origins on it; never a waiting row beside the episode it is."""
    store, data_dir = _empty(language)
    src = _source_root()
    show = names(language)[79]
    with store:
        root = store.add_source(src)
        video = _video(src, show, "ep1.mkv", "v1-one-batch")
        sub = _subtitle(language, data_dir, src, video, subtitle, 1)
        change = store.take_in(root, [video, sub])
        assert len(change.added) == 1
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        item = store.item(change.added[0])
        assert (item["availability"], item["rel_path"]) == ("available", sub["rel"])
        keys = {r[0] for r in store.conn.execute("SELECT content_key FROM pairings WHERE item_id = ?", (item["id"],))}
        assert keys == {ls.origin_key(video["video_path"]), ls.origin_key(sub["origin"])}

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_video_of_a_show_already_shown_still_waits_in_new_arrivals(language):
    """Batch 1 review H3: a video with no subtitle has nothing to read or mine, so it waits in New arrivals whatever
    its show's rows: one in Current would take a Current slot (and Soon's line) with nothing to read, one at the top
    of Current would lead it with nothing to watch. Its show in Current, and its show only in 6+ Months."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        store.take_in(root, [_found(language, data_dir, src, w[110], "ep1.srt", 1)], first=True)
        joined = store.take_in(root, [_video(src, w[110], "ep2.mkv", "v1-h3a")])
        assert list(joined.placed.values()) == ["arrivals"], "its show in Current: it still waits"
        parked = store.take_in(root, [_found(language, data_dir, src, w[111], "ep1.srt", 2)], first=True).added
        store.move(parked, "goal")
        led = store.take_in(root, [_video(src, w[111], "ep2.mkv", "v1-h3b")])
        assert list(led.placed.values()) == ["arrivals"], "its show only in 6+ Months: it still waits"
        assert _tier(store, "arrivals") == [f"Library/{w[110]}/ep2.mkv", f"Library/{w[111]}/ep2.mkv"]
        assert {store.item(i)["availability"] for i in joined.added + led.added} == {"waiting"}

# why: putting one removed video back deletes only its own exclusion; another removed video's exclusion stays, so
# its later subtitle is still kept out (an OR in the delete would clear every removed exclusion and bring it back)
@pytest.mark.parametrize("language", LANGUAGES)
def test_putting_back_one_removed_video_keeps_another_removed_video_out(language):
    """Put back of one removed waiting video brings only that video back, waiting; the other removed video's
    exclusion stays, and its subtitle found later is still kept out."""
    store, data_dir = _empty(language)
    src = _source_root()
    w = names(language)
    with store:
        root = store.add_source(src)
        va = _video(src, w[78], "ep1.mkv", "v1-put-back-a")
        vb = _video(src, w[79], "ep1.mkv", "v1-put-back-b")
        a = store.take_in(root, [va]).added[0]
        b = store.take_in(root, [vb]).added[0]
        removed_a = store.remove([a])
        store.remove([b])
        assert len(_exclusions(store)) == 2
        store.restore(removed_a.trash_ids)
        assert store.item(a)["availability"] == "waiting"
        assert _exclusions(store) == [(root, ls.path_key(os.path.abspath(vb["video_path"])), "removed",
                                       {"size": vb["size"], "sha256": None, "video_key": "v1-put-back-b"})]
        assert store.take_in(root, [dict(vb)]).skipped["excluded"]
        sub = _subtitle(language, data_dir, src, vb, "ep1.srt", 3)
        assert store.take_in(root, [sub]).skipped["excluded"]


# --- the Soon line never counts a waiting row (H-6; Kura-AB, 2026-11-09) ------------------------------------------- #
# why: `_keep_line` leaves every waiting row out of the line's count; `_tier_top` (where "the top of Soon" is) counted
# them, so with one waiting row in NOW a title sent to Soon was put at Soon's very top, above the row the line then
# takes up, and `_keep_line` lifted the title straight back to the end of Current: the press seemed to do nothing.

def _ids(store, tier):
    return [r[0] for r in store.conn.execute("SELECT id FROM items WHERE tier = ? ORDER BY ord, id", (tier,))]


def _texts(store, tier):
    return [r[0] for r in store.conn.execute("SELECT id FROM items WHERE tier = ? AND availability != 'waiting' "
                                             "ORDER BY ord, id", (tier,))]


def _line_scene(language, where="now"):
    """Current = 4 NOW rows with text, the Soon line after them, 4 Soon rows; one video waiting for its subtitle placed
    in Current: after NOW's last row (`where="now"`), before it (`"before_last"`) or at Soon's very top (`"soon"`)."""
    store = migrated(language, shows=0, loose=4, tiers=("now", "soon"))
    src = _source_root()
    root = store.add_source(src)
    video = store.take_in(root, [_video(src, names(language)[80], "ep1.mkv", "v1-line")]).added[0]
    if where == "now":
        store.move([video], "now", after_id=_ids(store, "now")[-1])
    elif where == "before_last":
        store.move([video], "now", before_id=_ids(store, "now")[-1])
    else:
        store.move([video], "soon", before_id=_ids(store, "soon")[0])
    assert store._soon_line() == 4 and len(_texts(store, "now")) == 4 and store.item(video)["availability"] == "waiting"
    assert store.item(video)["tier"] == ("now" if where == "before_last" else where)
    return store, video


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("how", ("set_tier", "move"))
def test_a_title_sent_to_soon_beside_a_waiting_video_in_now_stays_in_soon(language, how):
    """⋯ Soon / Demote / the sort screen's Soon (`set_tier`) and the Soon well (`move` with no anchor): the title lands
    at Soon's top, and Soon's first row goes up into its place — never the title bounced back to Current's end."""
    store, video = _line_scene(language)
    with store:
        now, soon = _ids(store, "now"), _ids(store, "soon")
        sent = now[0]
        getattr(store, how)([sent], "soon")
        assert _ids(store, "soon")[0] == sent
        assert _ids(store, "now") == now[1:] + [soon[0]]                    # the waiting video keeps its place
        assert len(_texts(store, "now")) == 4 and store.item(video)["tier"] == "now"


@pytest.mark.parametrize("language", LANGUAGES)
def test_two_titles_sent_to_soon_beside_a_waiting_video_both_stay_in_soon(language):
    """Two at once: both land at Soon's top in their order, Soon's first two rows go up (before: one bounced back)."""
    store, _video_id = _line_scene(language)
    with store:
        now, soon = _texts(store, "now"), _ids(store, "soon")
        store.set_tier(now[:2], "soon")
        assert _ids(store, "soon")[:2] == now[:2]
        assert _texts(store, "now") == now[2:] + soon[:2]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("how", ("set_tier", "move"))
def test_a_title_sent_to_soon_past_a_waiting_video_at_soons_top_stays_in_soon(language, how):
    """A waiting row at Soon's very top goes up with Soon's first row with text, so the slot is after THAT row — after
    the waiting one alone, the title would be the row the line takes up."""
    store, video = _line_scene(language, where="soon")
    with store:
        now, soon = _ids(store, "now"), _texts(store, "soon")
        sent = now[0]
        getattr(store, how)([sent], "soon")
        assert store.item(sent)["tier"] == "soon"
        assert _texts(store, "now") == now[1:] + [soon[0]]
        assert _texts(store, "soon")[0] == sent and store.item(video)["tier"] == "now"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_drag_to_a_soon_row_and_a_promote_beside_a_waiting_video_land_where_asked(language):
    """The neighbours, which never read Soon's top: a drop before a Soon row lands there and stays; Soon → Current
    (Promote) lands at Current's top and the line pushes NOW's last row with text down."""
    store, video = _line_scene(language)
    with store:
        now, soon = _ids(store, "now"), _ids(store, "soon")
        store.move([now[0]], "soon", before_id=soon[2])
        assert store.item(now[0])["tier"] == "soon" and _ids(store, "soon").index(now[0]) == 1   # soon[0] went up
        up = _ids(store, "soon")[-1]
        store.set_tier([up], "now")
        assert _ids(store, "now")[0] == up and len(_texts(store, "now")) == 4
        assert store.item(video)["tier"] == "now"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_row_sent_to_soon_with_its_waiting_video_lands_at_soons_top_together(language):
    """The waiting row going along (a book's row with its audiobook, a show's row with its video waiting): only the
    row with text leaves the line's count, so Soon's first row goes up and the two land at Soon's very top."""
    store, video = _line_scene(language)
    with store:
        now, soon = _texts(store, "now"), _ids(store, "soon")
        store.move([now[-1], video], "soon")
        assert _ids(store, "soon")[:2] == [now[-1], video]
        assert _texts(store, "now") == now[:-1] + [soon[0]]


# why: the slot is right after the row the line takes up, and the line took the waiting rows after that row up with it
# — so a block sent to Soon that starts with a waiting row (a show whose first episode waits for its subtitle) lost
# that row back to Current's end, the show split across the line (the adversary's M-1)
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("how", ("set_tier", "move"))
def test_a_block_sent_to_soon_that_starts_with_a_waiting_video_stays_whole_in_soon(language, how):
    """[the waiting video, NOW's last row] sent to Soon: both land at Soon's top in their order; only Soon's first row
    with text goes up."""
    store, video = _line_scene(language, where="before_last")
    with store:
        now, soon = _texts(store, "now"), _ids(store, "soon")
        getattr(store, how)([video, now[-1]], "soon")
        assert _ids(store, "soon")[:2] == [video, now[-1]]
        assert _ids(store, "now") == now[:-1] + [soon[0]]
