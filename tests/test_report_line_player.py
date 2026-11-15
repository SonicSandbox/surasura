"""The journey's line player (Kiku-L; Potential Features F3 *loop the line* + F19 *pause after every line*; Sonic
2026-11-14: "The design looks decent and I like having the ability to do it on desktop"; words and defaults
PROVISIONAL): ▶ after a line plays that line's own audio, from the file the window's ▶ opens, from its start to its
end — repeated, with a pause before or after, then stopping or going on down the list.

Three halves, each held here:
- **Which file** (`play.files`, Qt-free): the window's ▶'s own lookup for each timed source the report shows, so the
  page and the window never disagree — but an audiobook plays its one file (its record's), and one of several files
  plays nothing (the transcript's times run across every file).
- **The render** (`static_html_generator`): the source table's two new fields — the file's URI when a browser plays it,
  else its extension (`.mkv`: the badge's hover says why) — and the line's times even with the sources hidden (they
  were read only while the badge showed), from Connect's line reader, kept in the anchor memo.
- **The page** (`templates/web_app.html`): read from the template the report embeds (no test may open a browser, the
  harness refuses one): ▶ only where a line has a playable file and times, one `<audio>` and one bar made on first use,
  timers only, stopped by Esc / ■ / a redraw / the page hidden; its step rule `lpNext` mirrored here (as `rsNorm` is in
  test_report_search.py) — keep the two in step.

What a wrong answer would cost a learner: a line that plays another episode's audio, or the wrong minute of an
audiobook; a ▶ that does nothing (an .mkv the browser can't play); sound that goes on after Stop or after leaving the
file; a loop that never ends; a page that opens slower for a library of .mkv files that gains nothing.

Real data: `tests/Test Resources/ja/placed_episode.srt`, `zh/night_market.srt`, the 杜子春 transcript lines; made-up
show names; media stand-ins (a few bytes — never played).
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request
from unittest.mock import patch

import pandas as pd
import pytest

from app import path_utils, sources
from app import static_html_generator as gen
from app.services import play
from tests.test_audiobook_items import _audio_folder, _audio_items, _fresh_module_state, _settle  # noqa: F401
from tests.test_audiobook_transcripts import STAR, _alone, _lines, _srt
from tests.test_services_play import _elsewhere, _read_in_place, _subtitle, _video
from tests.test_sources_scan import _drive, _empty, _look

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES = os.path.join(ROOT, "tests", "Test Resources")
TEMPLATE = os.path.join(ROOT, "templates", "web_app.html")
PLACED = os.path.join(RESOURCES, "ja", "placed_episode.srt")
NIGHT = os.path.join(RESOURCES, "zh", "night_market.srt")
SHOW = "放課後の約束"                                   # a made-up show
LINE_JA = "文化祭まで、あと三日しかないよ。"            # placed_episode.srt, cue 1: 00:00:01,000 --> 00:00:03,200
LINE_ZH = "今天我们要去台北的夜市吃东西。"              # night_market.srt, cue 2: 00:00:04,100 --> 00:00:07,350


@pytest.fixture(autouse=True)
def _fresh_run():
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()


def _stand_in(path, magic=b"ID3"):
    """A media file stand-in (its format's first bytes), settled like a finished download — never played."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(magic + b" stand-in " + os.path.basename(path).encode("utf-8"))
    t = time.time() - 60
    os.utime(path, (t, t))
    return path


def _uri(where, dirs):
    """The URI the page puts together for a source (`lpUri`): its folder's from `globalLineDirs`, its name encoded."""
    cut = where.index("/")
    return dirs[int(where[:cut])] + "/" + urllib.parse.quote(where[cut + 1:], safe="")


def _in_library(language, show, name, source=PLACED):
    """A subtitle's copy in `Library/<show>/` (no store record: a 2.x library's file) -> (rel path, its folder)."""
    rel = f"Library/{show}/{name}"
    path = os.path.join(path_utils.get_data_path(language), *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(source, encoding="utf-8") as f, open(path, "w", encoding="utf-8", newline="\n") as g:
        g.write(f.read())
    return rel, os.path.dirname(path)


# --- which file: play.files ------------------------------------------------------------------------------------------ #
def test_a_folder_read_in_place_plays_the_same_file_the_windows_play_opens():
    """Each episode's file is the one the window's ▶ opens (its own `_find`): beside the original, any case, an .mkv
    named as found (the page then says why it can't play it), and none where none is — one answer each."""
    folder = _elsewhere("Downloads", SHOW)
    names = {n: f"{SHOW} - {n:02d}" for n in (1, 2, 3)}
    subs = {n: _subtitle(os.path.join(folder, names[n] + ".ja.srt"), n) for n in names}
    mp4 = _stand_in(os.path.join(folder, names[1] + ".MP4"), b"\x00\x00\x00\x18ftypmp42")
    mkv = _video(os.path.join(folder, names[2] + ".mkv"))
    items = _read_in_place(folder)
    rels = {n: items[os.path.abspath(subs[n])][1] for n in names}
    found = play.files("ja", list(rels.values()))
    assert found == {rels[1]: os.path.abspath(mp4), rels[2]: os.path.abspath(mkv), rels[3]: None}
    for n in names:                                         # the page's answer is the window's, episode by episode
        assert found[rels[n]] == play.to_open("ja", *items[os.path.abspath(subs[n])], "anime")[0]


def test_an_audiobook_alone_plays_its_one_file_whatever_its_transcript_is_called():
    """The transcript's times are its one file's: the M4B plays, though its name isn't the transcript's (the window's
    ▶ finds no audio *beside* it — a lookup by name — the page reads the audiobook's own record)."""
    store, data_dir, src, m4b, srt = _alone("ja", STAR)
    with store:
        root = store.add_source(src)
        _look(store, "ja", root)
        [item] = _audio_items(store)
    assert play.files("ja", [item["rel_path"]]) == {item["rel_path"]: os.path.abspath(m4b)}


def test_an_audiobook_of_several_files_plays_nothing_its_times_run_across_them_all():
    """Three chapter MP3s, one transcript: a time in it may be chapter 3's — playing it in chapter 1 would be the wrong
    minute of the book, so no ▶ at all (the window's ▶ still opens the first file: that's a whole-book open)."""
    store, _data_dir = _empty("ja")
    src = _drive("driveB")
    folder = os.path.join(src, "杜子春")
    _audio_folder(folder, "杜子春", 3600, n=3)
    _srt(os.path.join(folder, "杜子春.srt"), _lines("ja")[:12])
    with store:
        root = store.add_source(src)
        _look(store, "ja", root)
        [item] = _audio_items(store)
    assert play.files("ja", [item["rel_path"]]) == {item["rel_path"]: None}


def test_a_library_without_a_store_or_with_an_unreadable_one_still_finds_the_file_beside_the_copy(monkeypatch):
    from app import library_store as ls
    rel, copies = _in_library("ja", SHOW, f"{SHOW} - 04.ja.srt")
    mp4 = _stand_in(os.path.join(copies, f"{SHOW} - 04.mp4"), b"\x00\x00\x00\x18ftypmp42")
    assert play.files("ja", [rel]) == {rel: mp4}                         # a 2.x library: no store at all

    def broken(*a, **k):
        raise OSError("the store's disk went away")
    monkeypatch.setattr(ls, "check_mode", lambda *a, **k: ("store", "ready"))
    monkeypatch.setattr(ls, "open_store", broken)
    assert play.files("ja", [rel]) == {rel: mp4}                         # never raises: the copy's neighbour still


def test_a_book_or_a_text_never_plays_and_one_sources_fault_is_its_own(monkeypatch):
    """A book's ▶ opens the book — never a line; a lookup that raises costs only its own source."""
    rel_a, copies = _in_library("ja", SHOW, f"{SHOW} - 05.ja.srt")
    mp4 = _stand_in(os.path.join(copies, f"{SHOW} - 05.mp4"), b"\x00\x00\x00\x18ftypmp42")
    rel_b, _ = _in_library("ja", SHOW, f"{SHOW} - 06.ja.srt")
    monkeypatch.setattr(play, "_rows", lambda language, rels: ({rel_a: (None, None, (), ()),
                                                                  rel_b: (7, "book", [], [])}, ""))
    assert play.files("ja", [rel_a, rel_b]) == {rel_a: mp4, rel_b: None}
    real = play._find

    def flaky(language, rel_path, *a, **k):
        if rel_path == rel_a:
            raise RuntimeError("a share that answers with garbage")
        return real(language, rel_path, *a, **k)
    monkeypatch.setattr(play, "_rows", lambda language, rels: ({}, ""))
    monkeypatch.setattr(play, "_find", flaky)
    rel_c, copies_c = _in_library("ja", SHOW, f"{SHOW} - 07.ja.srt")
    mp4_c = _stand_in(os.path.join(copies_c, f"{SHOW} - 07.mp4"), b"\x00\x00\x00\x18ftypmp42")
    assert play.files("ja", [rel_a, rel_c]) == {rel_a: None, rel_c: mp4_c}


def test_a_folder_of_many_episodes_is_listed_once(monkeypatch):
    """Twenty-four episodes in one folder: one listing, never one an episode (a share is slow per call)."""
    rels = []
    for n in range(1, 25):
        rel, copies = _in_library("ja", SHOW, f"{SHOW} - {n:02d}.ja.srt")
        _stand_in(os.path.join(copies, f"{SHOW} - {n:02d}.mp4"), b"\x00\x00\x00\x18ftypmp42")
        rels.append(rel)
    listed = []
    real = os.listdir
    monkeypatch.setattr(os, "listdir", lambda p=".": listed.append(p) or real(p))
    found = play.files("ja", rels)
    assert all(found[r] and found[r].endswith(".mp4") for r in rels)
    assert len([p for p in listed if os.path.normcase(os.path.abspath(p)) == os.path.normcase(copies)]) == 1


def test_a_library_of_mkv_episodes_read_in_place_is_never_looked_up(monkeypatch):
    """The gate (the render no slower where nothing can play): a folder read in place whose episodes are .mkv — the
    browser plays none — answers None for every source without `_find`, `_pairings` or a name parsed; asked to explain
    (the badge shown), each names its .mkv from the listings already made."""
    folder = _elsewhere("Downloads", SHOW)
    subs = {n: _subtitle(os.path.join(folder, f"{SHOW} - {n:02d}.ja.srt"), n) for n in (1, 2, 3)}
    mkvs = {n: _video(os.path.join(folder, f"{SHOW} - {n:02d}.mkv")) for n in (1, 2)}
    items = _read_in_place(folder)
    rels = {n: items[os.path.abspath(subs[n])][1] for n in subs}
    monkeypatch.setattr(play, "_find", lambda *a, **k: pytest.fail("nothing playable: never looked for"))
    monkeypatch.setattr(play, "_pairings", lambda *a, **k: pytest.fail("nothing playable: no record picked"))
    assert play.files("ja", list(rels.values())) == dict.fromkeys(rels.values())
    said = play.files("ja", list(rels.values()), explain=True)
    assert said == {rels[1]: os.path.join(folder, f"{SHOW} - 01.mkv"), rels[2]: os.path.join(folder, f"{SHOW} - 02.mkv"),
                    rels[3]: None}
    assert gen._line_media("ja", set(rels.values()), explain=True)[0] == \
        {rels[1]: ["", ".mkv"], rels[2]: ["", ".mkv"]}


def test_a_copy_with_no_record_is_looked_up_when_connects_index_holds_a_playable_file(monkeypatch):
    """A 2.x library's copy (no pairing row) may play a video only Connect's index knows: the gate lets it through
    when the index holds any playable file — and keeps it out when the index holds none."""
    rel, _copies = _in_library("ja", SHOW, f"{SHOW} - 09.ja.srt")
    far = _stand_in(_elsewhere("Videos", SHOW, f"{SHOW} - 09.mp4"), b"\x00\x00\x00\x18ftypmp42")
    from app.connect import videos
    videos.Index("ja").refresh([], [_elsewhere("Videos")])                  # Connect's own refresh, saved
    assert play.files("ja", [rel]) == {rel: far}
    os.remove(far)
    _video(_elsewhere("Videos", SHOW, f"{SHOW} - 09.mkv"))
    videos.Index("ja").refresh([], [_elsewhere("Videos")])
    monkeypatch.setattr(play, "_find", lambda *a, **k: pytest.fail("the index holds nothing playable"))
    assert play.files("ja", [rel]) == {rel: None}


def test_many_folders_are_listed_side_by_side_as_one_at_a_time_would(tmp_path):
    folders = []
    for n in range(40):
        f = tmp_path / f"作品{n:02d}"
        f.mkdir()
        (f / f"第{n}話.srt").write_text(LINE_JA, encoding="utf-8")
        if n % 3 == 0:
            (f / f"第{n}話.MP4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
        folders.append(str(f))
    folders.append(str(tmp_path / "ない"))                                  # can't be listed: False, as `beside`'s
    together, one_by_one = {}, {}
    play._list_all(set(folders), together)
    for f in folders:
        play._listing(f, one_by_one)
    assert together == one_by_one and together[str(tmp_path / "ない")] is False


@pytest.mark.parametrize("path", ["C:\\番組\\第1話.ja.srt", "C:\\第1話.srt", "C:/x/y.mp4", "\\\\nas\\share\\作品\\y.mkv",
                                  "\\\\nas\\share\\y.mkv", "Library/x.srt", "x.srt", "D:\\a\\b\\c.m4b"])
def test_a_records_folder_is_what_dirname_gives(path):
    assert play._folder_of(path) == (os.path.dirname(path) if os.path.isabs(path) else "")


def _touch_later(path, magic=b"\x00\x00\x00\x18ftypmp42"):
    """A file added to a folder a moment later: its folder's mtime moves (NTFS keeps 100 ns; waited out to be sure)."""
    folder = os.path.dirname(path)
    before = os.stat(folder).st_mtime_ns
    for _ in range(50):
        _stand_in(path, magic)
        if os.stat(folder).st_mtime_ns != before:
            return path
        os.remove(path)
        time.sleep(0.02)
    pytest.fail("the folder's mtime never moved")


def test_a_redraw_reuses_every_answer_and_looks_again_only_where_a_folder_changed(monkeypatch):
    """A redraw after a move (the journey's F7 path) runs the render again: the answers kept in the memo are reused —
    no name parsing, no listing — until what one rests on moves: a video added beside an episode, one taken away."""
    rels = {}
    for n in (1, 2):
        rel, copies = _in_library("ja", f"{SHOW}{n}", f"{SHOW} - {n:02d}.ja.srt")
        rels[n] = rel
    mp4 = _stand_in(os.path.join(os.path.dirname(os.path.join(path_utils.get_data_path("ja"), *rels[1].split("/"))),
                                 f"{SHOW} - 01.mp4"), b"\x00\x00\x00\x18ftypmp42")
    memo = {}
    assert play.files("ja", list(rels.values()), memo=memo) == {rels[1]: mp4, rels[2]: None}
    assert set(memo) == {rels[1]}                       # episode 2's folder holds nothing playable: the gate, no memo
    real = play._find
    monkeypatch.setattr(play, "_find", lambda *a, **k: pytest.fail("a kept answer is never looked for again"))
    assert play.files("ja", list(rels.values()), memo=memo) == {rels[1]: mp4, rels[2]: None}
    looked = []
    monkeypatch.setattr(play, "_find", lambda language, rel, *a, **k: looked.append(rel) or real(language, rel, *a, **k))
    folder2 = os.path.dirname(os.path.join(path_utils.get_data_path("ja"), *rels[2].split("/")))
    added = _touch_later(os.path.join(folder2, f"{SHOW} - 02.mp4"))        # a video arrives beside episode 2
    assert play.files("ja", list(rels.values()), memo=memo) == {rels[1]: mp4, rels[2]: added}
    assert looked == [rels[2]]                                             # episode 1's answer still kept
    looked.clear()
    before = os.stat(os.path.dirname(mp4)).st_mtime_ns
    os.remove(mp4)                                                          # episode 1's video taken away
    if os.stat(os.path.dirname(mp4)).st_mtime_ns == before:
        pytest.skip("this file system didn't move the folder's mtime")
    assert play.files("ja", list(rels.values()), memo=memo)[rels[1]] is None
    assert looked == []                                 # nothing playable left beside it: the gate answers


def test_a_kept_none_goes_when_its_own_video_arrives_beside_a_playable_sibling():
    """Episode 2 shares a folder with episode 1's .mp4, so the gate lets it through and its None is kept; its own .mp4
    arriving changes that folder's listing — the memo's key with it — and the next render finds it."""
    rel1, copies = _in_library("ja", SHOW, f"{SHOW} - 11.ja.srt")
    rel2, _ = _in_library("ja", SHOW, f"{SHOW} - 12.ja.srt")
    mp4 = _stand_in(os.path.join(copies, f"{SHOW} - 11.mp4"), b"\x00\x00\x00\x18ftypmp42")
    memo = {}
    assert play.files("ja", [rel1, rel2], memo=memo) == {rel1: mp4, rel2: None}
    assert memo[rel2][0] is None                                           # kept: its folder holds a playable file
    arrived = _stand_in(os.path.join(copies, f"{SHOW} - 12.mp4"), b"\x00\x00\x00\x18ftypmp42")
    assert play.files("ja", [rel1, rel2], memo=memo) == {rel1: mp4, rel2: arrived}


def test_a_new_pairing_is_looked_for_again_and_an_unread_record_is_never_kept(monkeypatch):
    """hato pairs the episode with a video elsewhere: its record moves, so the kept answer goes; a record that
    couldn't be read (the store busy) is answered as before but never kept — the next render reads it again."""
    rel, copies = _in_library("ja", SHOW, f"{SHOW} - 08.ja.srt")
    beside = _stand_in(os.path.join(copies, f"{SHOW} - 08.mp4"), b"\x00\x00\x00\x18ftypmp42")
    paired = _stand_in(_elsewhere("hato", "第8話.mp4"), b"\x00\x00\x00\x18ftypmp42")
    record = {}
    monkeypatch.setattr(play, "_rows", lambda language, rels: (
        {rel: (5, "anime", [json.dumps(record)] if record else [],
               [(record.get("origin"), record.get("video_path"), None)] if record else [])}, ""))
    monkeypatch.setattr(play, "_pairings", lambda language, ids, moved=None: {5: dict(record)})
    memo = {}
    assert play.files("ja", [rel], memo=memo) == {rel: beside}
    record.update(producer="hato", video_path=paired)
    assert play.files("ja", [rel], memo=memo) == {rel: paired}
    monkeypatch.setattr(play, "_pairings", lambda language, ids, moved=None: {5: None})
    memo.clear()
    assert play.files("ja", [rel], memo=memo) == {rel: beside} and memo == {}


def test_the_render_keeps_its_memo_for_its_own_sources_only(tmp_path, monkeypatch):
    path = str(tmp_path / "line_media.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"Library/gone.srt": [None, "x", None], "Library/a.srt": ["C:\\a.mp4", "k", 1]}, f)
    seen = []

    def files(language, rels, memo=None, **_):
        seen.append(dict(memo))
        memo["Library/b.srt"] = [None, "k2", None]
        return {r: None for r in rels}
    monkeypatch.setattr(play, "files", files)
    gen._line_media("ja", {"Library/a.srt", "Library/b.srt"}, path)
    assert "Library/gone.srt" in seen[0]                                   # handed in as it was read
    with open(path, encoding="utf-8") as f:
        assert set(json.load(f)) == {"Library/a.srt", "Library/b.srt"}    # what left the lists left the file
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    gen._line_media("ja", {"Library/a.srt"}, path)                         # unreadable: a fresh memo, no failure
    assert seen[-1] == {}


def test_an_mp3s_verdict_is_kept_with_its_answer_and_read_again_only_with_it(tmp_path, monkeypatch):
    """Each mp3's first frame is read once: a redraw that keeps the answer keeps its verdict; an answer looked for
    again (a new entry of three) has its verdict read again."""
    from app import audiobooks
    from tests.test_audiobooks import _mp3
    vbr = _mp3(str(tmp_path / "杜子春 01.mp3"), seconds=192.4)
    path = str(tmp_path / "line_media.json")

    def files(language, rels, memo=None, **_):
        for r in rels:
            if r not in memo:
                memo[r] = [vbr, "key", 1]
        return {r: vbr for r in rels}
    monkeypatch.setattr(play, "files", files)
    read = []
    real = audiobooks.mp3_variable
    monkeypatch.setattr(audiobooks, "mp3_variable", lambda p: read.append(p) or real(p))
    assert gen._line_media("ja", {"Library/a.srt"}, path)[0] == {"Library/a.srt": ["", "vbr"]}
    assert gen._line_media("ja", {"Library/a.srt"}, path)[0] == {"Library/a.srt": ["", "vbr"]}
    assert read == [vbr]                                                   # once, then kept
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["Library/a.srt"] == [vbr, "key", 1, True]


def test_a_freshness_check_reads_each_folder_once_and_gives_what_stat_gives(tmp_path, monkeypatch):
    """The anchor memo's check (`_file_sig`) from one listing a folder: the same times and size `os.stat` gives, a
    file the listing doesn't name stat'ed itself, a gone one None — never a stat a file."""
    folder = tmp_path / "番組"
    folder.mkdir()
    paths = []
    for n in range(5):
        p = folder / f"第{n}話.srt"
        p.write_text(LINE_JA, encoding="utf-8")
        paths.append(str(p))
    finder = gen.AnchorFinder(language="ja")
    expect = {p: [os.stat(p).st_mtime, os.stat(p).st_size] for p in paths}
    stats = []
    real_stat = os.stat
    monkeypatch.setattr(os, "stat", lambda p, *a, **k: stats.append(p) or real_stat(p, *a, **k))
    scans = []
    real_scan = os.scandir
    monkeypatch.setattr(os, "scandir", lambda p=".": scans.append(p) or real_scan(p))
    assert [finder._file_sig(p)[:2] for p in paths] == [expect[p] for p in paths]
    assert len(scans) == 1 and stats == []
    assert finder._file_sig(str(folder / "ない.srt")) is None


# --- the render: the source table's file, the times with the sources hidden ------------------------------------------ #
@pytest.mark.parametrize("name,expect", [
    ("第1話.mp4", "play"), ("第1話.M4B", "play"), ("第1話.mp3", "play"), ("第1話.webm", "play"), ("第1話.opus", "play"),
    ("第1話.mkv", ".mkv"), ("第1話.avi", ".avi"), ("第1話.ts", ".ts"), ("第1話.mov", ".mov"),
])
def test_the_table_carries_a_uri_the_browser_plays_or_the_extension_it_cant(monkeypatch, name, expect):
    path = os.path.join(_elsewhere("Anime", f"{SHOW} #1", "50% 字幕"), name)       # a space, '#', '%', Japanese
    monkeypatch.setattr(play, "files", lambda language, rels, **_: {r: path for r in rels})
    media, dirs = gen._line_media("ja", ["Library/x.srt"])
    [(where, why)] = media.values()
    if expect == "play":
        assert where == "0/" + name and dirs[0].startswith("file:///")    # the folder once, the name as it is
        uri = _uri(where, dirs)
        assert why == "" and uri.startswith("file:///")
        assert "#" not in uri and "%25" in uri                          # never cut at '#', '%' itself encoded
        assert urllib.request.url2pathname(uri[len("file:"):]) == path  # the very file, round-tripped
    else:
        assert (where, why) == ("", expect) and dirs == []


def test_a_file_on_a_share_is_a_uri_with_its_server_and_nothing_found_is_no_row(monkeypatch):
    share = "\\\\nas\\media\\杜子春\\杜子春 01.m4b"
    monkeypatch.setattr(play, "files", lambda language, rels, **_: {"Library/a.srt": share, "Library/b.srt": None})
    media, dirs = gen._line_media("ja", ["Library/a.srt", "Library/b.srt"])
    assert media == {"Library/a.srt": ["0/杜子春 01.m4b", ""]} and dirs == ["file://nas/media/%E6%9D%9C%E5%AD%90%E6%98%A5"]
    assert _uri(media["Library/a.srt"][0], dirs) == \
        "file://nas/media/%E6%9D%9C%E5%AD%90%E6%98%A5/%E6%9D%9C%E5%AD%90%E6%98%A5%2001.m4b"
    monkeypatch.setattr(play, "files", lambda language, rels, **_: (_ for _ in ()).throw(OSError("gone")))
    assert gen._line_media("ja", ["Library/a.srt"]) == ({}, [])         # a failed lookup: no ▶, never a failed report
    assert gen._line_media("ja", []) == ({}, [])


def test_a_variable_bit_rate_mp3_gets_no_play_and_says_why(monkeypatch, tmp_path):
    """Measured on LibriVox's real 杜子春 reading in Edge: a VBR mp3 (LAME, Xing) lands a seek 0.8–1.6 s off either way —
    the wrong words, or the line's start cut — while its constant-rate twin lands within 0.13 s. So a VBR mp3's lines
    get no ▶ and the badge says why; a constant-rate one (no tag, or LAME's Info) plays."""
    from tests.test_audiobooks import _mp3
    vbr = _mp3(str(tmp_path / "杜子春 01.mp3"), seconds=192.4, frames={"TALB": "杜子春"})
    cbr = _mp3(str(tmp_path / "杜子春 02.mp3"), seconds=None, cbr_bytes=40000)
    info = str(tmp_path / "杜子春 03.mp3")
    with open(vbr, "rb") as f, open(info, "wb") as g:
        g.write(f.read().replace(b"Xing", b"Info"))
    found = {"Library/a.srt": vbr, "Library/b.srt": cbr, "Library/c.srt": info}
    monkeypatch.setattr(play, "files", lambda language, rels, **_: {r: found[r] for r in rels})
    media, dirs = gen._line_media("ja", list(found))
    assert media["Library/a.srt"] == ["", "vbr"]
    assert _uri(media["Library/b.srt"][0], dirs).startswith("file:///")
    assert _uri(media["Library/c.srt"][0], dirs).startswith("file:///")


def test_the_vbr_check_reads_past_a_big_cover_tag_and_never_raises(tmp_path):
    from app import audiobooks
    from tests.test_audiobooks import _mp3
    big = _mp3(str(tmp_path / "big.mp3"), seconds=60, frames={"TALB": "杜子春"}, pad=400 << 10)   # past HEAD_BYTES
    assert audiobooks.mp3_variable(big) is True
    assert audiobooks.mp3_variable(str(tmp_path / "gone.mp3")) is None
    junk = tmp_path / "junk.mp3"
    junk.write_bytes("字幕ではない".encode("utf-8") * 100)
    assert audiobooks.mp3_variable(str(junk)) is None
    assert audiobooks.read_tags(big).seconds == pytest.approx(60, abs=0.1)   # the length reader, unchanged


@pytest.mark.parametrize("source,sentence,times", [(PLACED, LINE_JA, (1.0, 3.2)), (NIGHT, LINE_ZH, (4.1, 7.35))])
def test_with_the_sources_hidden_a_playable_lines_times_are_read_and_nothing_else(tmp_path, source, sentence, times):
    """Before, a line's times came only with the badge (`source_display` on: off by default). Now a line ▶ can play
    gets them always — from Connect's line reader, as the badge's — and no anchor is looked for (that reads the whole
    file: only for the badge); a line whose source has no playable file gets nothing new."""
    language = "zh" if source == NIGHT else "ja"
    rel = f"Library/{SHOW}/{os.path.basename(source)}"
    other = f"Library/{SHOW}/other.srt"
    source_map = {rel: {"name": os.path.basename(source), "type": "subtitle", "abs": source},
                  other: {"name": "other.srt", "type": "subtitle", "abs": source}}
    records = [{"Context 1": sentence, "Src 1": rel}, {"Context 1": sentence, "Src 1": other}]
    timer = gen.AnchorFinder(cache_path=str(tmp_path / "anchor_cache.json"), language=language)
    table, index, plays = [], {}, {}
    gen._intern_sources(records, source_map, table, index, None, None,
                        media={rel: ["0/a.mp4", ""], other: ["", ".mkv"]}, timer=timer, plays=plays)
    assert (records[0]["At 1"], records[0]["End 1"]) == times
    assert "Frag 1" not in records[0]
    assert "At 1" not in records[1] and "End 1" not in records[1]
    assert plays == {records[0]["Src 1"]: ["0/a.mp4", ""], records[1]["Src 1"]: ["", ".mkv"]}   # the ▶'s own table
    assert [len(row) for row in table] == [5, 5]          # the source rows' contract: [name, type, path, group, link]


def test_times_kept_without_an_anchor_are_reused_and_the_badge_still_finds_its_anchor_later(tmp_path):
    """The memo keeps a times-only answer as [None, start, end]: the next render reuses it (no file read), and once the
    badge is on, its anchor is looked for then — never a missing scroll-to-text link because ▶ came first."""
    cache = str(tmp_path / "anchor_cache.json")
    timer = gen.AnchorFinder(cache_path=cache, language="ja")
    assert timer.times(PLACED, LINE_JA) == (1.0, 3.2)
    timer.save_memo()
    with open(cache, encoding="utf-8") as f:
        assert json.load(f)[PLACED]["a"][LINE_JA] == [None, 1.0, 3.2]
    again = gen.AnchorFinder(cache_path=cache, language="ja")
    again.line = lambda *a: pytest.fail("a kept time is never read from the file again")
    assert again.times(PLACED, LINE_JA) == (1.0, 3.2)
    badge = gen.AnchorFinder(cache_path=cache, language="ja")
    anchor, start, end = badge.resolve(PLACED, LINE_JA)
    assert anchor and (start, end) == (1.0, 3.2)


def _render(tmp_path, records_by_file, source_map, settings=None):
    """A report rendered from these lists (the analyzer's CSVs, its sources.json) -> (globalData, globalSources)."""
    results = tmp_path / "results"
    results.mkdir(parents=True, exist_ok=True)
    rows = []
    for seq, (filename, words) in enumerate(records_by_file.items(), 1):
        for w in words:
            rows.append({"Sequence": seq, "Source File": filename, "Word": w["Word"], "Reading": "",
                         "Tier": "Outside", "Score": 10, "Occurrences (Global)": 2, "Occurrences (File)": 2,
                         "Count (High)": 0, "Count (Low)": 0, "Count (Goal)": 2, **w})
    pd.DataFrame(rows).to_csv(results / "progressive_learning_list.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([dict(r, Occurrences=2) for r in rows]).to_csv(results / "priority_learning_list.csv", index=False,
                                                              encoding="utf-8-sig")
    with open(results / "sources.json", "w", encoding="utf-8") as f:
        json.dump(source_map, f, ensure_ascii=False)
    out = results / "reading_list_static.html"
    from app import settings_manager
    real = settings_manager.load_settings
    with patch.object(gen, "RESULTS_DIR", str(results)), \
         patch.object(gen, "PRIORITY_CSV", str(results / "priority_learning_list.csv")), \
         patch.object(gen, "PROGRESSIVE_CSV", str(results / "progressive_learning_list.csv")), \
         patch.object(gen, "OUTPUT_FILE", str(out)), \
         patch.object(settings_manager, "load_settings", lambda *a, **k: dict(real(*a, **k), **(settings or {}))):
        gen.generate_static_html(theme="default", open_browser=False)
    html = out.read_text(encoding="utf-8")
    data = json.loads(re.search(r"let globalData = (\{.*?\});\n", html, re.S).group(1))
    table = json.loads(re.search(r"let globalSources = (\[.*?\]);\n", html, re.S).group(1))
    dirs = json.loads(re.search(r"let globalLineDirs = (\[.*?\]);\n", html, re.S).group(1))
    plays = json.loads(re.search(r"let globalLinePlay = (\{.*?\});\n", html, re.S).group(1))
    assert all(len(row) == 5 for row in table), "the source rows keep their five fields"
    # for the asserts: each row with the ▶'s answer put after it, its URI as the page puts it together (`lpUri`)
    return data, [row + ([_uri(plays[str(i)][0], dirs) if plays[str(i)][0] else "", plays[str(i)][1]]
                         if str(i) in plays else ["", ""]) for i, row in enumerate(table)]


def _rows(compressed):
    """`compress_list_of_dicts`'s rows as dicts, a field a row didn't have (None) left out."""
    keys = compressed["keys"]
    return [{k: v for k, v in zip(keys, r) if v is not None} for r in compressed["rows"]]


@pytest.mark.parametrize("display", ["off", "icon"])
def test_a_report_gives_each_playable_line_its_file_and_times_and_an_mkv_line_its_why(tmp_path, display):
    """End to end, both badge settings: an episode with an .mp4 beside it plays (its URI, its line's times); one with
    only an .mkv gets its why and no times with the badge off (nothing to play them with); a text gets neither."""
    rel_mp4, copies = _in_library("ja", SHOW, f"{SHOW} - 01.ja.srt")
    mp4 = _stand_in(os.path.join(copies, f"{SHOW} - 01.mp4"), b"\x00\x00\x00\x18ftypmp42")
    rel_mkv, _ = _in_library("ja", SHOW, f"{SHOW} - 02.ja.srt")
    _video(os.path.join(copies, f"{SHOW} - 02.mkv"))
    data_dir = path_utils.get_data_path("ja")
    rel_txt = "Library/本/本.txt"
    os.makedirs(os.path.join(data_dir, "Library", "本"), exist_ok=True)
    with open(os.path.join(data_dir, *rel_txt.split("/")), "w", encoding="utf-8") as f:
        f.write(LINE_JA)
    source_map = {r: {"name": r.rsplit("/", 1)[-1], "type": t, "abs": os.path.join(data_dir, *r.split("/"))}
                  for r, t in ((rel_mp4, "subtitle"), (rel_mkv, "subtitle"), (rel_txt, "text"))}
    data, table = _render(tmp_path, {
        f"{SHOW} - 01.ja.srt": [{"Word": "文化祭", "Context 1": LINE_JA, "Src 1": rel_mp4}],
        f"{SHOW} - 02.ja.srt": [{"Word": "三日", "Context 1": LINE_JA, "Src 1": rel_mkv}],
        "本.txt": [{"Word": "まで", "Context 1": LINE_JA, "Src 1": rel_txt}]}, source_map, {"source_display": display})
    rows = {r["Word"]: r for f in data["progressive"] for r in _rows(f["words"])}
    played, mkv, text = rows["文化祭"], rows["三日"], rows["まで"]
    assert urllib.request.url2pathname(table[played["Src 1"]][5][len("file:"):]) == mp4
    assert (played["At 1"], played["End 1"]) == (1.0, 3.2)
    assert table[mkv["Src 1"]][5:] == ["", ".mkv"]          # its folder holds a playable episode: looked for, its why
    assert table[text["Src 1"]][5:] == ["", ""]
    assert ("At 1" in mkv) == (display != "off")                          # times for the badge only, as before
    assert ("Frag 1" in played) == (display != "off")                     # the anchor: only for the badge
    prio = {r["Word"]: r for r in _rows(data["priority"])}
    assert (prio["文化祭"]["At 1"], prio["文化祭"]["End 1"]) == (1.0, 3.2)  # the priority view's lines play too


def test_an_audiobooks_transcript_line_plays_from_its_m4b_in_a_rendered_report(tmp_path):
    """The audiobook's item is its transcript's copy, typed `audio` in sources.json (the store's own type wins over the
    .srt): its lines are timed and play from the audiobook's one file — never left out as "not a subtitle"."""
    store, data_dir, src, m4b, srt = _alone("ja", STAR)
    with store:
        root = store.add_source(src)
        _look(store, "ja", root)
        [item] = _audio_items(store)
    rel = item["rel_path"]
    first = _lines("ja")[0]                              # the transcript's first cue: 00:00:02,000 --> 00:00:03,500
    source_map = {rel: {"name": rel.rsplit("/", 1)[-1], "type": "audio",
                        "abs": os.path.join(data_dir, *rel.split("/"))}}
    data, table = _render(tmp_path, {rel.rsplit("/", 1)[-1]: [{"Word": "剣士", "Context 1": first, "Src 1": rel}]},
                          source_map)
    assert urllib.request.url2pathname(table[0][5][len("file:"):]) == os.path.abspath(m4b)
    row = _rows(data["progressive"][0]["words"])[0]
    assert (row["At 1"], row["End 1"]) == (2.0, 3.5)


def test_a_draw_with_the_badge_off_never_cuts_the_badges_anchor_memo(tmp_path):
    """The times read for ▶ with the badge off are kept in their own memo (`LINE_TIMES_MEMO`): the badge's
    `anchor_cache.json` keeps every file's anchors, so turning the badge on later reads nothing again."""
    rel, copies = _in_library("ja", SHOW, f"{SHOW} - 31.ja.srt")
    _stand_in(os.path.join(copies, f"{SHOW} - 31.mp4"), b"\x00\x00\x00\x18ftypmp42")
    results = tmp_path / "results"
    results.mkdir(parents=True)
    kept = {"C:\\他の番組\\第1話.srt": {"sig": [1.0, 2, "cues-1/0"], "a": {LINE_JA: ["文化祭まで", 1.0, 3.2]}}}
    (results / "anchor_cache.json").write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    source_map = {rel: {"name": "x.srt", "type": "subtitle",
                        "abs": os.path.join(path_utils.get_data_path("ja"), *rel.split("/"))}}
    data, table = _render(tmp_path, {f"{SHOW} - 31.ja.srt": [{"Word": "文化祭", "Context 1": LINE_JA, "Src 1": rel}]},
                          source_map)
    assert "At 1" in _rows(data["progressive"][0]["words"])[0]
    assert json.loads((results / "anchor_cache.json").read_text(encoding="utf-8")) == kept
    assert (results / gen.LINE_TIMES_MEMO).exists()


def test_with_its_switch_off_the_journey_is_drawn_as_before_the_player(tmp_path, monkeypatch):
    """The Settings switch (*Play a line's own audio*, on by default): off, the render looks for no line's file and
    reads no line's times — the source table's rows keep their five fields, no folder list — so the draw is what it
    was before the line player, whatever the library holds; on (the default), an .mp4 line plays."""
    rel, copies = _in_library("ja", SHOW, f"{SHOW} - 21.ja.srt")
    mp4 = _stand_in(os.path.join(copies, f"{SHOW} - 21.mp4"), b"\x00\x00\x00\x18ftypmp42")
    source_map = {rel: {"name": "x.srt", "type": "subtitle",
                        "abs": os.path.join(path_utils.get_data_path("ja"), *rel.split("/"))}}
    lists = {f"{SHOW} - 21.ja.srt": [{"Word": "文化祭", "Context 1": LINE_JA, "Src 1": rel}]}
    data, table = _render(tmp_path / "on", lists, source_map)                 # the default: on
    assert urllib.request.url2pathname(table[0][5][len("file:"):]) == mp4
    from app import cues
    monkeypatch.setattr(play, "files", lambda *a, **k: pytest.fail("off: no line's file is looked for"))
    monkeypatch.setattr(cues, "timeline", lambda *a, **k: pytest.fail("off: no line's times are read"))
    data, table = _render(tmp_path / "off", lists, source_map, {"line_player": False})
    assert table[0][5:] == ["", ""]                                         # no ▶ answer at all
    assert "At 1" not in _rows(data["progressive"][0]["words"])[0]
    html = (tmp_path / "off" / "results" / "reading_list_static.html").read_text(encoding="utf-8")
    assert "let globalLineDirs = [];" in html and "let globalLinePlay = {};" in html


def test_the_switch_is_one_settings_row_on_by_default_with_its_words_in_one_place():
    """PROVISIONAL (its default and words may change once it has been tried): the default in settings_manager's
    defaults, the words in settings_strings' ROWS — a toggle on the Journey slab, its one line behind the row's ?,
    found by a search for what it does; placed as the report's (a re-render, never a re-analysis)."""
    from app import settings_manager
    from app.qt import settings_catalog as catalog
    from app.qt import settings_strings as S
    from app.settings_placement import PLACED
    assert settings_manager.DEFAULT_SETTINGS["line_player"] is True
    [row] = [r for r in catalog.ROWS if r.id == "line_player"]
    assert (row.section, row.kind, row.keys, row.adv) == ("reading", "toggle", ("line_player",), False)
    label, help_, _tip, _words = S.ROWS["line_player"]
    assert label == "Play a line's own audio" and help_ and "\n" not in help_
    assert "line_player" in catalog.find("loop", {}, "ja") and "line_player" in catalog.find("own audio", {}, "zh")
    assert PLACED["line_player"] == "report"


def test_a_report_with_nothing_playable_looks_for_no_times_and_reads_no_file(tmp_path, monkeypatch):
    """A library of .mkv episodes (most anime libraries) gains no ▶ — so its render reads no subtitle's lines at all
    (the line reader is never asked): the journey opens as fast as before."""
    rel_mkv, copies = _in_library("ja", SHOW, f"{SHOW} - 03.ja.srt")
    _video(os.path.join(copies, f"{SHOW} - 03.mkv"))
    source_map = {rel_mkv: {"name": "x.srt", "type": "subtitle",
                            "abs": os.path.join(path_utils.get_data_path("ja"), *rel_mkv.split("/"))}}
    from app import cues
    monkeypatch.setattr(cues, "timeline", lambda *a, **k: pytest.fail("no line is read when nothing can play"))
    data, table = _render(tmp_path, {f"{SHOW} - 03.ja.srt": [{"Word": "文化祭", "Context 1": LINE_JA,
                                                               "Src 1": rel_mkv}]}, source_map)
    assert table[0][5:] == ["", ""]                         # no badge shown: no why looked for either
    assert "At 1" not in _rows(data["progressive"][0]["words"])[0]


# --- the page: read from the template ------------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def page():
    with open(TEMPLATE, encoding="utf-8") as f:
        return f.read()


def _block(page, start, end):
    i = page.index(start)
    return page[i:page.index(end, i)]


def _player(page):
    return _block(page, "// --- The line player", "// --- end of the line player")


def test_play_is_drawn_only_for_a_line_with_a_playable_file_and_its_times(page):
    fn = _block(page, "function linePlay(", "\n        }\n")
    assert "lpUri(idx)" in fn and "b <= a" in fn and "isFinite" in fn
    uri = _block(page, "function lpUri(", "\n        }\n")
    assert "globalLineDirs" in uri and "encodeURIComponent(where.slice(cut + 1))" in uri
    assert 'class="lp" migaku_ignore data-yomichan-ignore' in fn                  # dictionaries never read it
    for caller in ('linePlay(data["Src 1"], data["At 1"], data["End 1"], true)',
                   "linePlay(data['Src ' + n], data['At ' + n], data['End ' + n], false)"):
        assert caller in page                                                    # the first line and every other
    assert page.count('linePlay(data["Src 1"], data["At 1"], data["End 1"], true)') == 2    # the card, the simple row


def test_the_player_is_one_audio_element_and_timers_never_a_loop(page):
    code = _player(page)
    assert code.count("new Audio(") == 1
    assert "setInterval" not in code and "requestAnimationFrame" not in code
    assert "setTimeout(lpStep" in code                                             # a pause: one timer
    assert "clearTimeout(" in code


def test_stop_esc_another_play_a_redraw_and_a_hidden_page_all_stop_it(page):
    code = _player(page)
    assert "e.key === 'Escape'" in code and "lpStop()" in code
    assert "visibilitychange" in code and "document.hidden" in code
    assert "isConnected" in code                                                    # its line left the page: stop
    assert "b.offsetParent !== null" in _block(page, "function lpAfter(", "return i")    # never on to a hidden line
    starts = _block(page, "function lpStart(", "lpRun = {")
    assert "speechSynthesis.cancel()" in starts and "koeAudio.pause()" in starts     # the page's other voices stop
    for fn in ("async function koeSpeak(", "function rsRun(", "function playAudio("):
        head = "\n".join(_block(page, fn, "\n        }\n").replace("\r\n", "\n").split("\n")[:5])
        assert "lpStop();" in head, fn
    stop = _block(page, "function lpStop()", "\n        }\n")
    assert "clearTimeout(r.timer)" in stop and "lpAudio.pause()" in stop and "lpRun = null" in stop   # no stray sound
    for fn in ("async function switchMainTab(", "async function renderFileWords(", "async function renderPriorityView("):
        head = "\n".join(_block(page, fn, "\n        }\n").replace("\r\n", "\n").split("\n")[:4])
        assert "lpStop();" in head, fn                                              # first thing, before the redraw


def test_v_plays_the_centred_cards_line_and_space_only_takes_over_while_waiting(page):
    keys = _block(page, "if (isAudio) {", "// `\\` looks the centered word up online")
    assert "querySelector('.lp')" in keys and keys.index(".lp") < keys.index(".btn-audio')")
    code = _player(page)
    assert "lpRun.phase === 'waiting'" in code and "stopImmediatePropagation" in code


def test_the_bars_words_defaults_and_its_one_explaining_line(page):
    code = _player(page)
    m = re.search(r"const LP_DEFAULTS = (\{[^}]*\});", code)
    assert m and json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1)).replace("'", '"')) == \
        {"repeat": 3, "pause": 1.5, "when": "after", "then": "stop"}
    for word in ("Repeat", "Pause", "Before", "After", "Then", "Stop", "Next line", "Wait"):
        assert f"'{word}'" in code, word
    assert "Hear the line from its own episode, repeated with a pause" in code
    assert code.count("lp-help-pop") == 1                                          # the one line, behind the ?
    assert "migaku_ignore" in code and "data-yomichan-ignore" in code             # the bar too


def test_the_player_draws_with_the_themes_own_colours(page):
    css = _block(page, "/* --- The line player", "/* --- end of the line player")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "a colour that isn't the theme's"
    assert "--lp-ink: var(--secondary)" in css and "body.theme-modern-light" in css
    assert "prefers-reduced-motion" in css


def test_the_badge_says_why_an_mkv_line_has_no_play(page):
    badge = _block(page, "function sourceBadge(", "\n        }\n")
    assert "lpOf(idx)" in badge and "LP_WORDS.cantPlay" in badge
    assert "Your browser can't play {ext} files" in _player(page)
    # one line, its break escaped — a raw break inside a JS string stops the whole page's script
    assert "if (why) hover += '\\n' + (why === 'vbr' ? LP_WORDS.cantSeek" in badge
    assert "its bit rate varies" in _player(page)


def test_no_line_the_player_added_breaks_inside_a_string(page):
    """The page's whole script fails on one raw line break inside a quoted string (it happened here once, through a
    shell's backslashes): every line of the player and of its call sites closes the quotes it opens."""
    def open_at_end(line):
        """The quote a line leaves open (' or "), else None: strings, `//` and one-line `/* */` comments and regex
        literals (a `/` after `(`, `,` or `=`) read as JavaScript reads them."""
        quote, i = None, 0
        while i < len(line):
            c = line[i]
            if quote:
                if c == "\\":
                    i += 2
                    continue
                if c == quote:
                    quote = None
            elif line.startswith("//", i):
                return None
            elif line.startswith("/*", i):
                end = line.find("*/", i + 2)
                if end < 0:
                    return None
                i = end + 2
                continue
            elif c == "/" and line[:i].rstrip()[-1:] in ("(", ",", "="):
                j = i + 1
                while j < len(line) and line[j] != "/":
                    j += 2 if line[j] == "\\" else 1
                i = j + 1
                continue
            elif c in "'\"`":
                quote = c
            i += 1
        return quote if quote in ("'", '"') else None

    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    lines = [ln for script in scripts for ln in script.splitlines()]
    assert len(lines) > 2500 and "function lpNext(o)" in "\n".join(lines)
    assert [ln for ln in lines if open_at_end(ln)] == []
    assert open_at_end("            if (row[6]) hover += '") == "'"         # the very line that broke the page once


# --- the step rule, mirrored ---------------------------------------------------------------------------------------- #
LEAD, MIN_MS = 0.2, 250          # LP_LEAD, LP_MIN_MS


def _lp_next(o):
    """Mirror of the template's `lpNext` — keep the two in step."""
    ms = round(max(0, o["pause"]) * 1000)
    more = o["played"] < max(1, o["repeat"])
    then = o["then"] if o["hasNext"] else "stop"
    if more:
        if ms and not o["paused"] and (o["when"] == "before" or o["played"] > 0):
            return ["pause", ms]
        return ["play"]
    if then == "next" and o["when"] == "after" and ms and not o["paused"]:
        return ["pause", ms]
    return ["then", then]


def _lp_span(at, end):
    """Mirror of the template's `lpSpan`: how long one play runs, in ms (from LP_LEAD before the line to its end)."""
    return max(MIN_MS, round((end - max(0, at - LEAD)) * 1000))


def _steps(repeat, pause, when, then, has_next):
    o = {"repeat": repeat, "pause": pause, "when": when, "then": then, "played": 0, "paused": False,
         "hasNext": has_next}
    out = []
    for _ in range(100):                                        # a loop that never ends fails here, not in a browser
        step = _lp_next(o)
        out.append(step[0] if step[0] == "play" else f"{step[0]} {step[1]}")
        if step[0] == "then":
            return out
        if step[0] == "play":
            o["played"] += 1
            o["paused"] = False
        else:
            o["paused"] = True
    pytest.fail(f"never ends: {out[:12]}")


@pytest.mark.parametrize("repeat,pause,when,then,has_next,expect", [
    (3, 1.5, "after", "stop", True, ["play", "pause 1500", "play", "pause 1500", "play", "then stop"]),
    (1, 1.5, "after", "stop", True, ["play", "then stop"]),
    (2, 0, "after", "next", True, ["play", "play", "then next"]),
    (2, 2, "after", "next", True, ["play", "pause 2000", "play", "pause 2000", "then next"]),
    (2, 2, "after", "next", False, ["play", "pause 2000", "play", "then stop"]),        # the last line: stops
    (2, 2, "after", "wait", True, ["play", "pause 2000", "play", "then wait"]),
    (2, 2, "before", "stop", True, ["pause 2000", "play", "pause 2000", "play", "then stop"]),
    (2, 2, "before", "next", True, ["pause 2000", "play", "pause 2000", "play", "then next"]),
    (10, 0.5, "after", "stop", True, ["play", "pause 500"] * 9 + ["play", "then stop"]),
    (0, 1, "after", "stop", True, ["play", "then stop"]),                               # never fewer than one play
])
def test_the_order_of_plays_and_pauses(repeat, pause, when, then, has_next, expect):
    assert _steps(repeat, pause, when, then, has_next) == expect


def test_fewer_repeats_chosen_mid_line_end_it_at_once():
    o = {"repeat": 1, "pause": 1.5, "when": "after", "then": "next", "played": 2, "paused": False, "hasNext": True}
    assert _lp_next(o) == ["pause", 1500]                       # done already: the pause before the next line
    o["paused"] = True
    assert _lp_next(o) == ["then", "next"]


@pytest.mark.parametrize("at,end,ms", [(1.0, 3.2, 2400), (0.0, 0.6, 600), (12.0, 12.4, 600), (5.0, 5.05, 250),
                                       (27.58, 37.98, 10600)])
def test_a_play_runs_from_just_before_the_line_to_its_end_short_or_long(at, end, ms):
    """A line under a second still plays whole (from LP_LEAD before it — Edge lands a constant-rate mp3's seek up to
    0.13 s late, measured on a real reading — a floor of MIN_MS); the 杜子春 line of ten seconds plays all ten."""
    assert _lp_span(at, end) == ms


def test_the_template_holds_the_rule_this_file_mirrors(page):
    code = _player(page)
    for piece in ("function lpNext(o)", "Math.max(1, o.repeat)", "o.hasNext ? o.then : 'stop'",
                  "(o.when === 'before' || o.played > 0)", "then === 'next' && o.when === 'after' && ms && !o.paused",
                  "function lpSpan(at, end)", "Math.max(LP_MIN_MS, Math.round((end - Math.max(0, at - LP_LEAD)) * 1000))",
                  "const LP_LEAD = 0.2;", "const LP_MIN_MS = 250;"):
        assert piece in code, piece
