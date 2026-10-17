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
import json
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


def _take_in(lang, src, sub_rel, show, copy_name=None, **record):
    """The scan's work for one subtitle at `<src>/<sub_rel>`: the original written (a real subtitle + a line of its
    own), copied into `Library/<show>/` (as `copy_name` when its own name was taken), handed to `take_in` with
    `record`'s video keys -> (item id, the copy's path, the root id)."""
    origin = os.path.join(src, *sub_rel.split("/"))
    os.makedirs(os.path.dirname(origin), exist_ok=True)
    sub_lang, sub_name = c.SUBTITLE[lang]
    with open(os.path.join(h.RESOURCES, sub_lang, sub_name), "rb") as f:
        data = f.read() + f"\n{sub_rel}\n".encode("utf-8")
    with open(origin, "wb") as f:
        f.write(data)
    data_dir, _u = c.dirs(lang)
    rel = f"{library_store.CONTENT_FOLDER}/{show}/{copy_name or os.path.basename(origin)}"
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
    monkeypatch.setattr(videos.Index, "refresh",
                        lambda self, shallow, deep, budget=None, sources=(): seen.append((shallow, deep, sources)))
    added = os.path.join(h.root(), "Added videos")
    s = _steps(connect_video_folders=[added])
    s._videos("ja")
    with c.store("ja") as store:
        from app.connect import library
        shallow = sorted({os.path.dirname(r["video_path"]) for records in library.pairings(store).values()
                          for r in records if isinstance(r, dict) and r.get("video_path")})
        assert store.sources() == []
    assert seen == [(shallow, [added], [])]

    src = _source()
    with c.store("ja") as store:
        root = store.add_source(src)
    _steps(connect_video_folders=[added])._videos("ja")
    assert seen[-1][1:] == ([added], [os.path.normpath(os.path.abspath(src))]), "a source on: beside your folders"
    with c.store("ja") as store:
        store.stop_source(root)
    _steps(connect_video_folders=[added])._videos("ja")
    assert seen[-1][1:] == ([added], []), "a stopped source: as before"


# --------------------------------------------------------------------------- #
# The index's walk skips what a source's look skips (B3: `library_store.skip_dir`), in every folder it lists
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bin_name", [".trash", "$RECYCLE.BIN"])
def test_a_trashed_copy_of_the_video_in_a_source_makes_no_second_match(bin_name):
    # why: a deleted copy in the recycle bin has the episode's name: indexed, it makes two matches and Connect (which
    # never guesses) says No video although the real one is beside its show
    c.library("ja")
    src = _source()
    video = _video(os.path.join(src, "Example Show", "Example Show - 07.mkv"))
    _video(os.path.join(src, bin_name, "S-1-5-21", "Example Show - 07.mkv"))
    item, _copy, _root = _take_in("ja", src, "Example Show/Subs/Example Show - 07.ja.srt", "Example Show")
    s = _steps()
    assert _same(s.video("ja", {"id": 1, "item_id": item}), video)
    assert not any(bin_name.lower() in k for k in s._videos("ja").data["dirs"]), "the bin is never listed"


@pytest.mark.parametrize("bin_name", [".trash", "$RECYCLE.BIN", "@eaDir"])
def test_a_folder_you_added_is_listed_as_before_its_bins_included(tmp_path, bin_name):
    # why (the batch 1 intent review): the skip rule is a source's (B3: Surasura reads that folder for you); the
    # folders you added to Connect are listed exactly as before Sources, so a copy in its bin still counts and
    # Connect, which never guesses, says No video for the two — as it always did
    added = tmp_path / "Added"
    _video(str(added / "Show" / "Show - 02.mkv"))
    _video(str(added / bin_name / "Show - 02.mkv"))
    index = videos.Index("ja", path=str(tmp_path / "videos-ja.json"))
    index.refresh([], [str(added)])
    assert index.find(["Show - 02.mkv"]) is None
    assert os.path.normcase(str(added / bin_name)) in index.data["dirs"]


def test_a_library_with_no_sources_indexes_its_folders_as_before_sources(tmp_path):
    # why (the batch 1 intent review): a library with no source folder (every library today) must get the index 3.0-dev
    # wrote: its version (2), every subfolder of a folder you added listed (dot folders, the bins, a folder link
    # followed as before), no entry marked, and so the same file
    c.library("ja")
    added = os.path.join(h.root(), "Added videos")
    expected = {added}
    for sub in ("Show", ".hidden", "$RECYCLE.BIN", ".trash", "@eaDir"):
        _video(os.path.join(added, sub, f"{sub.strip('.$@')} - 01.mkv"))
        expected.add(os.path.join(added, sub))
    if os.name == "nt":
        import _winapi
        outside = os.path.join(h.root(), "elsewhere", "Linked target")
        _video(os.path.join(outside, "Linked - 01.mkv"))
        _winapi.CreateJunction(outside, os.path.join(added, "Linked"))
        expected.add(os.path.join(added, "Linked"))
    s = _steps(connect_video_folders=[added])
    index = s._videos("ja")
    with c.store("ja") as store:
        assert store.sources() == []
    deep = {k for k, v in index.data["dirs"].items() if v.get("deep")}
    assert deep == {os.path.normcase(os.path.abspath(p)) for p in expected}
    assert all("skip" not in v for v in index.data["dirs"].values()), "no entry marked as a source's"
    with open(videos.index_path("ja"), encoding="utf-8") as f:
        assert json.load(f)["version"] == videos.INDEX_VERSION == 2
    if os.name == "nt":
        assert _same(index.find(["Linked - 01.mkv"]), os.path.join(added, "Linked", "Linked - 01.mkv")), "followed"


def test_a_source_inside_a_folder_you_added_is_listed_as_your_folder(tmp_path):
    # why (the intent review): where a folder you added holds a source (or is one), your folder's listing wins, as
    # before Sources
    added = tmp_path / "Videos"
    _video(str(added / "Anime" / "$RECYCLE.BIN" / "Show - 03.mkv"))
    index = videos.Index("ja", path=str(tmp_path / "videos-ja.json"))
    index.refresh([], [str(added)], sources=[str(added / "Anime")])
    assert os.path.normcase(str(added / "Anime" / "$RECYCLE.BIN")) in index.data["dirs"]
    alone = videos.Index("ja", path=str(tmp_path / "videos-ja-2.json"))
    alone.refresh([], [], sources=[str(added / "Anime")])
    assert os.path.normcase(str(added / "Anime" / "$RECYCLE.BIN")) not in alone.data["dirs"], "a source alone skips it"


def test_a_folder_that_turns_from_yours_into_a_source_is_listed_again_by_the_sources_rule(tmp_path):
    # why (the intent review): the index keeps each folder as last listed while its time holds; a folder listed as
    # yours (its bin included) that is now only a source must be listed again by the source's rule, and back
    added = tmp_path / "Videos"
    _video(str(added / "Show" / "Show - 04.mkv"))
    _video(str(added / "$RECYCLE.BIN" / "Show - 04.mkv"))
    path = str(tmp_path / "videos-ja.json")
    binned = os.path.normcase(str(added / "$RECYCLE.BIN"))
    videos.Index("ja", path=path).refresh([], [str(added)])
    as_source = videos.Index("ja", path=path)
    as_source.refresh([], [], sources=[str(added)])
    assert binned not in as_source.data["dirs"] and as_source.listed >= 1
    assert _same(as_source.find(["Show - 04.mkv"]), str(added / "Show" / "Show - 04.mkv"))
    yours = videos.Index("ja", path=path)
    yours.refresh([], [str(added)])
    assert binned in yours.data["dirs"], "yours again: listed as before"


@pytest.mark.skipif(os.name != "nt", reason="a junction is Windows' folder link")
def test_a_junction_inside_a_source_is_never_followed():
    # why: a folder link can loop (a walk that never ends) or lead into another drive's folders; the index takes only
    # what is really inside the source
    import _winapi
    c.library("ja")
    src = _source()
    outside = os.path.join(h.root(), "elsewhere", "Outside")
    _video(os.path.join(outside, "Example Show - 08.mkv"))
    _winapi.CreateJunction(outside, os.path.join(src, "Linked"))
    item, _copy, _root = _take_in("ja", src, "Example Show/Subs/Example Show - 08.ja.srt", "Example Show")
    s = _steps()
    assert s.video("ja", {"id": 1, "item_id": item}) is None, "the video behind the junction is not taken"
    assert not any(k.endswith(os.path.normcase(os.sep + "linked")) for k in s._videos("ja").data["dirs"])


def test_a_source_copy_renamed_for_a_name_clash_still_finds_its_video_by_the_originals_name():
    # why: a copy stored as `name (2).ja.srt` (its name taken in Library/) has no video of that name; the original's
    # name, kept in its record, is the video's
    c.library("ja")
    src = _source()
    video = _video(os.path.join(src, "Example Show", "Example Show - 09.mkv"))
    item, copy, _root = _take_in("ja", src, "Example Show/Subs/Example Show - 09.ja.srt", "Example Show",
                                 copy_name="Example Show - 09 (2).ja.srt")
    s = _steps()
    assert os.path.basename(s.subtitle("ja", {"id": 1, "item_id": item})) == "Example Show - 09 (2).ja.srt"
    assert _same(s.video("ja", {"id": 1, "item_id": item}), video)


def test_a_cloud_placeholder_of_the_video_in_a_source_is_never_a_match(monkeypatch):
    # why: a placeholder's read would download the episode (RD-S1); listed by name, it must neither be taken nor make
    # a second match beside the real one. The placeholder is simulated for that one path (as `test_videos` does)
    c.library("ja")
    src = _source()
    video = _video(os.path.join(src, "Example Show", "Example Show - 10.mkv"))
    cloud = _video(os.path.join(src, "Cloud", "Example Show - 10.mkv"))
    real = runner._on_disk
    monkeypatch.setattr(runner, "_on_disk", lambda p: not _same(p, cloud) and real(p))
    item, _copy, _root = _take_in("ja", src, "Example Show/Subs/Example Show - 10.ja.srt", "Example Show")
    assert _same(_steps().video("ja", {"id": 1, "item_id": item}), video)
    os.remove(video)                                    # only the placeholder left: No video, never the cloud file
    assert _steps().video("ja", {"id": 1, "item_id": item}) is None


# --------------------------------------------------------------------------- #
# A moved video: hato's records judged exactly as before Sources (batch 1 review H14)
# --------------------------------------------------------------------------- #
class _Found:
    """The index's stand-in: a file of the name and size found away from the named path."""

    def __init__(self, path):
        self.path = path

    def find(self, names, size=None):
        return self.path


@pytest.mark.parametrize("found_key, used", [(None, True), ("v1-other", False)])
def test_a_moved_hato_video_is_judged_by_its_content_key_as_before_sources(monkeypatch, tmp_path, found_key, used):
    # why (H14): the sources' rule (no key to compare: never taken) is a source record's alone; a hato record is
    # judged as in 3.0-dev, the found file's key against the record's `content_key` — the same (both unread
    # included) is used, another is refused
    moved = _video(str(tmp_path / "New" / "Example Show - 11.mkv"))
    record = {"producer": "hato", "video_path": str(tmp_path / "Old" / "Example Show - 11.mkv"), "video_size": 120}
    monkeypatch.setattr(runner.Steps, "pairing", lambda self, lang, job: dict(record))
    monkeypatch.setattr(runner.Steps, "_videos", lambda self, lang: _Found(moved))
    monkeypatch.setattr(videos, "content_key", lambda path: found_key)
    got = _steps().video("ja", {"id": 1, "item_id": 1})
    assert (got == moved) is used
    source = dict(record, producer="source")             # a source record with no video key: never a guess
    monkeypatch.setattr(runner.Steps, "pairing", lambda self, lang, job: dict(source))
    assert _steps().video("ja", {"id": 1, "item_id": 1}) is None
