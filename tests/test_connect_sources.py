"""Connect finds a source folder's video (SRC M1): the folders the store reads where they are (`Store.sources()`) are
indexed as the video folders you add, as deep, so an episode taken in from a source finds its video by name; a video
that moved finds itself only by its bytes (`video_key`, a source record has no `content_key`); the subtitle Connect
mines from is Surasura's own copy in `Library/`, never the original.

What a wrong answer would cost:
  * a subtitle kept in `Show/Subs/` (the video one folder up), or a video downloaded after its subtitle, left as
    *No video* — the episode never mined although its video is on this computer;
  * a moved video taken on its name and size alone: another episode's audio cut into this one's cards;
  * a source folder offline (a drive unplugged) breaking the index, so no episode finds its video;
  * a library with no sources indexing anything new: every user's index (and its S19 "only folders whose time moved")
    changed for nothing.

The library is the suite's real Japanese and Chinese subtitles (`connect_helpers.library`); the source folder is a
second temp "drive" under the test root; its subtitle is a real one with a line of its own, and the videos are tiny
made-up files (bytes only). Names are made up.
"""
import hashlib
import os
import shutil
import struct

import pytest

from app import library_store
from app.connect import runner, videos
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)

VIDEO_HEADER = b"\x1aE\xdf\xa3"                                         # the Matroska magic
EPISODE = VIDEO_HEADER + bytes(i % 251 for i in range(200_000))         # over 128 KiB: the key reads head and tail


def _key(data):
    """hato's `video_hash`, written out here so the test doesn't check the code with itself (09-hato-layer v2 §1.1)."""
    body = data if len(data) <= 131072 else data[:65536] + data[-65536:]
    return "v1-" + hashlib.sha256(struct.pack("<Q", len(data)) + body).hexdigest()


def _video(path, data=VIDEO_HEADER + b"\0" * 116):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _source(name="Shows"):
    """A second "drive": a folder beside the test's data folder, never inside it."""
    path = os.path.join(h.root(), "elsewhere", name)
    os.makedirs(path, exist_ok=True)
    return path


def _same(a, b):
    return a is not None and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _steps(**settings):
    return runner.Steps({"connect_enabled": True, "anki_connect_url": h.CLOSED_PORT, **settings})


def _take_in(lang, src, sub_rel, show, **record):
    """The scan's work for one subtitle at `<src>/<sub_rel>`: the original written (a real subtitle + a line of its
    own), copied into `Library/<show>/`, handed to `take_in` with `record`'s video keys -> (item id, the copy's
    path, the root id)."""
    origin = os.path.join(src, *sub_rel.split("/"))
    os.makedirs(os.path.dirname(origin), exist_ok=True)
    sub_lang, sub_name = c.SUBTITLE[lang]
    with open(os.path.join(h.RESOURCES, sub_lang, sub_name), "rb") as f:
        data = f.read() + f"\n{sub_rel}\n".encode("utf-8")
    with open(origin, "wb") as f:
        f.write(data)
    data_dir, _u = c.dirs(lang)
    rel = f"{library_store.CONTENT_FOLDER}/{show}/{os.path.basename(origin)}"
    copy = os.path.join(data_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(copy), exist_ok=True)
    shutil.copyfile(origin, copy)
    st = os.stat(origin)
    found = {"origin": origin, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "show": show, "rel": rel,
             "sha256": hashlib.sha256(data).hexdigest(), **record}
    with c.store(lang) as s:
        root = s.add_source(src)
        item = s.take_in(root, [found], first=True).added[0]
    return item, copy, root


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_source_subtitle_in_a_subs_folder_finds_its_video_one_folder_up(lang):
    # why: `Show/Subs/ep.ja.srt` beside `Show/ep.mkv` is how many releases come; the copy sits in Library/, where no
    # video is, so only the source folder's index can find it
    c.library(lang)
    src = _source()
    video = _video(os.path.join(src, "Example Show", "Example Show - 03.mkv"))
    item, copy, _root = _take_in(lang, src, f"Example Show/Subs/Example Show - 03.{lang}.srt", "Example Show")
    s = _steps()
    job = {"id": 1, "item_id": item}
    assert _same(s.video(lang, job), video)
    # the subtitle mined from is Surasura's own copy in the data folder, never the original in the source
    assert _same(s.subtitle(lang, job), copy)
    assert os.path.normcase(s.subtitle(lang, job)).startswith(
        os.path.normcase(os.path.join(c.dirs(lang)[0], library_store.CONTENT_FOLDER)))


def test_a_video_that_arrives_after_its_subtitle_is_found_and_the_unmoved_folders_are_not_listed_again():
    # why: a subtitle often lands before its episode finishes downloading; the next run must find the video by name.
    # S19: a big source must not be listed again every run — only the folder whose time moved is
    c.library("ja")
    src = _source()
    _video(os.path.join(src, "Another Show", "Another Show - 01.mkv"))
    for n in range(3):
        os.makedirs(os.path.join(src, "Another Show", f"Extras {n}"))
    item, _copy, _root = _take_in("ja", src, "Example Show/Example Show - 04.ja.srt", "Example Show")
    job = {"id": 1, "item_id": item}
    first = _steps()
    assert first.video("ja", job) is None, "no video yet: No video, never a guess"
    first_listed = first._videos("ja").listed
    assert first_listed >= 6, "the source, its two shows and the extras are listed the first time"

    video = _video(os.path.join(src, "Example Show", "Example Show - 04.mkv"))      # downloaded later
    later = _steps()                                                                # the next run
    assert _same(later.video("ja", job), video)
    assert later._videos("ja").listed == 1, "only Example Show's folder (its time moved) is listed again"

    again = _steps()
    again._videos("ja")
    assert again._videos("ja").listed == 0, "nothing moved: no folder listed again"


def _moved_source_item(data):
    """A source episode whose record names its video at `Old/…` with that video's key, the video gone from there and
    a file of its name and size (holding `data`) in the source's `New/` -> (the steps, the job, the found path)."""
    c.library("ja")
    src = _source()
    named = os.path.join(src, "Old", "Example Show - 05.mkv")
    item, _copy, root = _take_in("ja", src, "Example Show/Example Show - 05.ja.srt", "Example Show",
                                 video_path=named, video_size=len(EPISODE), video_key=_key(EPISODE))
    moved = _video(os.path.join(src, "New", "Example Show - 05.mkv"), data)
    with c.store("ja") as s:
        from app.connect import library
        record = library.pairing_of(s, item)
    assert record["producer"] == "source" and "content_key" not in record and record["video_key"] == _key(EPISODE)
    return _steps(), {"id": 1, "item_id": item}, moved


def test_a_moved_source_video_whose_bytes_match_its_video_key_is_used():
    # why: a video the learner moved inside the source is still the episode: its bytes say so
    s, job, moved = _moved_source_item(EPISODE)
    assert _same(s.video("ja", job), moved)


def test_a_moved_source_video_of_the_same_name_and_size_but_other_bytes_is_refused():
    # why: another episode (or a re-encode) under the same name and size would be mined as this one. Only the last
    # byte differs: the key reads the tail too
    other = EPISODE[:-1] + bytes([(EPISODE[-1] + 1) % 256])
    s, job, _moved = _moved_source_item(other)
    assert s.video("ja", job) is None


def test_a_source_record_with_no_video_key_never_takes_a_moved_video():
    # why: with nothing to compare its bytes with, a file of the name and size is a guess, and Connect never guesses
    c.library("ja")
    src = _source()
    item, _copy, _root = _take_in("ja", src, "Example Show/Example Show - 06.ja.srt", "Example Show",
                                  video_path=os.path.join(src, "Old", "Example Show - 06.mkv"),
                                  video_size=len(EPISODE))
    _video(os.path.join(src, "New", "Example Show - 06.mkv"), EPISODE)
    assert _steps().video("ja", {"id": 1, "item_id": item}) is None


def test_an_offline_source_root_does_not_break_the_index():
    # why: an unplugged drive is normal (SRC-3): the other folders still find their videos, and the offline source
    # keeps what it last listed (looked at again when it is back), its videos never taken while it is away
    c.library("ja")
    online = _source("Online")
    offline = _source("Offline")
    away = _video(os.path.join(offline, "Show B", "Show B - 01.mkv"))
    item_a, _ca, _ra = _take_in("ja", online, "Show A/Subs/Show A - 01.ja.srt", "Show A")
    item_b, _cb, _rb = _take_in("ja", offline, "Show B/Subs/Show B - 01.ja.srt", "Show B")
    assert _same(_steps().video("ja", {"id": 2, "item_id": item_b}), away), "found while the drive is there"
    video_a = _video(os.path.join(online, "Show A", "Show A - 01.mkv"))
    os.rename(offline, offline + " (unplugged)")                         # the drive goes away
    s = _steps()
    assert _same(s.video("ja", {"id": 1, "item_id": item_a}), video_a)
    assert s.video("ja", {"id": 2, "item_id": item_b}) is None, "the offline one's video isn't on this computer"
    kept = {k for k in s._videos("ja").data["dirs"] if k.startswith(os.path.normcase(os.path.abspath(offline)))}
    assert os.path.normcase(os.path.abspath(offline)) in kept, "kept as last listed, never dropped as gone"


def test_a_store_with_no_sources_gives_the_index_exactly_the_folders_it_had(monkeypatch):
    # why: a library without sources (every library today) must index exactly what it did: the paired videos' folders
    # alone and the folders you added. A stopped source is no longer read, by the index either
    c.library("ja")
    seen = []
    monkeypatch.setattr(videos.Index, "refresh", lambda self, shallow, deep, budget=None: seen.append((shallow, deep)))
    added = os.path.join(h.root(), "Added videos")
    s = _steps(connect_video_folders=[added])
    s._videos("ja")
    with c.store("ja") as store:
        from app.connect import library
        shallow = sorted({os.path.dirname(r["video_path"]) for records in library.pairings(store).values()
                          for r in records if isinstance(r, dict) and r.get("video_path")})
        assert store.sources() == []
    assert seen == [(shallow, [added])]

    src = _source()
    with c.store("ja") as store:
        root = store.add_source(src)
    _steps(connect_video_folders=[added])._videos("ja")
    assert seen[-1][1] == [added, os.path.normpath(os.path.abspath(src))], "a source on: indexed after your folders"
    with c.store("ja") as store:
        store.stop_source(root)
    _steps(connect_video_folders=[added])._videos("ja")
    assert seen[-1][1] == [added], "a stopped source: as before"
