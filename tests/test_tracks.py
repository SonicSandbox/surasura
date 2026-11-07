"""Michi-ST (2026-11-02, PROVISIONAL rules; tracks/pipeline/work/ST/plan.md): a video whose only subtitles are a text
track inside it. The video waits in the library (SRC K5, *No subtitles yet*); Anki Miner's `inspect` and `extract`
(3.11, Z-19 / Z-24 — here the tests' fake, run as a child as the real one is) copy its track out, and the waiting item
takes it in place: read, listed and mined like any other, timed to that very video (no tsubasa asked). Picture
subtitles stay waiting and say so; no Anki Miner on the PC is said too, and nothing is remembered.

Real subtitles from tests/Test Resources (a library episode's ASS with its OP and a sign, a Chinese night-market SRT)."""
import hashlib
import json
import os
import time

import pytest

from app import library_store as ls
from app import tracks
from app.connect import fit_check, library
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _tree, _video, _waiting  # noqa: F401

FAKE = os.path.join(os.path.dirname(__file__), "connect", "fake_anki_miner.py")
RES = os.path.join(os.path.dirname(__file__), "Test Resources")
_SHOW = {"ja": "図書館の午後", "zh": "夜市小记"}
_TAG = {"ja": "jpn", "zh": "chi"}
_FULL = {"ja": ("ja", "library_episode.ass", "ass"), "zh": ("zh", "night_market.srt", "subrip")}
# a signs track: the episode's sign and its OP line only (two lines of real text, no dialogue)
_SIGNS = ("[Script Info]\nScriptType: v4.00+\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
          "MarginV, Effect, Text\nDialogue: 0,0:01:30.00,0:01:32.40,Sign,,0,0,0,,{\\pos(960,120)}市立図書館\n"
          "Dialogue: 0,0:00:04.50,0:00:08.00,OP_JP,,0,0,0,,遠い空の向こうまで\n")
_ENGLISH = ("1\n00:01:33,100 --> 00:01:36,250\nExcuse me, I'd like to borrow this book.\n\n"
            "2\n00:01:36,800 --> 00:01:39,900\nDo you have a library card?\n")


def _full(language):
    folder, name, codec = _FULL[language]
    with open(os.path.join(RES, folder, name), encoding="utf-8-sig") as f:
        return f.read(), codec


def _track(index, language=None, codec="ass", text=True, title=None, default=False, forced=False):
    return {"index": index, "position": index - 2, "kind": "subtitle", "codec": codec, "language": language,
            "title": title, "default": default, "forced": forced, "text": text}


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """The fake Anki Miner's plan (a dict the test fills) and its log of calls."""
    plan, log = tmp_path / "plan.json", tmp_path / "calls.log"
    monkeypatch.setattr(tracks, "_MINERS", {})          # each test's Anki Miner read afresh (one fake program path)
    monkeypatch.setenv("FAKE_ANKI_MINER_PLAN", str(plan))
    monkeypatch.setenv("FAKE_ANKI_MINER_LOG", str(log))

    class Fake:
        def set(self, **values):
            values.setdefault("app", "3.11.0")
            values.setdefault("features", ["named-words-whitelisted", "inspect", "tracks"])
            plan.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")

        def calls(self, command=None):
            if not log.exists():
                return []
            got = [json.loads(line)["argv"] for line in log.read_text(encoding="utf-8").splitlines()]
            return [a for a in got if command is None or (len(a) > 1 and a[1] == command)]
    return Fake()


def _library(language, names=("ep05",)):
    """A library whose source folder holds videos and no subtitle: each a waiting item (K5)."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    videos = [_video(os.path.join(src, _SHOW[language], f"[Grp] {_SHOW[language]} - {n} (1080p).mkv"),
                     body=b"\x1a\x45\xdf\xa3 matroska " + n.encode()) for n in names]
    store.__enter__()
    root = store.add_source(src)
    _look(store, language, root, first=True)
    assert _waiting(store) == len(names)
    return store, data_dir, src, videos


def _fill(store, language, **kw):
    before = _tree(_drive("driveA"))
    out = tracks.fill(store, language, settings={}, path=kw.pop("path", FAKE), **kw)
    assert _tree(_drive("driveA")) == before, "the track step wrote in the user's media folder"
    return out


def _copies(data_dir):
    """Every file in the library's own folder (a waiting item has none: its place is its video's name)."""
    return [os.path.join(w, n) for w, _d, files in os.walk(os.path.join(data_dir, ls.CONTENT_FOLDER)) for n in files]


def _remembered(language):
    """The videos the step remembers asking ({} when it never wrote its file)."""
    try:
        with open(tracks.cache_path(language), encoding="utf-8") as f:
            return json.load(f)["videos"]
    except FileNotFoundError:
        return {}


def _item(store):
    return store.conn.execute("SELECT id, rel_path, availability FROM items").fetchall()


# --- the rule ------------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("tracks_in, language, want, pictures", [
    ([_track(2, "jpn")], "ja", [2], False),                                            # one Japanese track
    ([_track(2, "eng", "subrip"), _track(3, "jpn")], "ja", [3], False),                # its language, not English
    ([_track(2, "jpn", title="Signs & Songs"), _track(3, "jpn")], "ja", [3], False),   # full dialogue over signs
    ([_track(2, "jpn", forced=True)], "ja", [2], False),                               # forced only: still read
    ([_track(2, "jpn"), _track(3, "jpn", default=True)], "ja", [3, 2], False),         # several: the default first
    ([_track(2, None, "subrip"), _track(3, "eng", "subrip")], "ja", [2], False),       # untagged: tried, text decides
    ([_track(2, "jpn", "hdmv_pgs_subtitle", text=False)], "ja", [], True),             # pictures only
    ([_track(2, "jpn", "hdmv_pgs_subtitle", text=False), _track(3, None)], "ja", [3], True),
    ([_track(2, "eng", "subrip"), _track(3, "eng", "hdmv_pgs_subtitle", text=False)], "ja", [], False),
    ([], "ja", [], False),
    ([_track(2, "chi", "subrip"), _track(3, "jpn")], "zh", [2], False),
    ([_track(i, "jpn") for i in range(2, 8)], "ja", [2, 3, 4], False),                 # at most TRIES extracted
])
def test_the_one_track_rule(tracks_in, language, want, pictures):
    """Why: which track is the episode's text is decided once, by its tag, its kind and its title — never English,
    signs only when nothing else is, a picture track named, never silently dropped."""
    got, said = tracks.choose(tracks_in + [{"index": 1, "kind": "audio", "language": "jpn", "text": None}], language)
    assert [t["index"] for t in got] == want and said is pictures


def test_a_webvtt_track_is_read_as_subrip():
    """Why: the library reads .srt and .ass; a WebVTT track's cues keep their text and times."""
    vtt = ("WEBVTT\n\nNOTE made by a muxer\n\n00:01.200 --> 00:03.800 align:start\n大家好，歡迎回到我的頻道。\n\n"
           "1\n01:00:04.100 --> 01:00:07.350\n今天我们要去台北的夜市吃东西。\n")
    assert tracks._srt(vtt) == ("1\n00:00:01,200 --> 00:00:03,800\n大家好，歡迎回到我的頻道。\n\n"
                                "2\n01:00:04,100 --> 01:00:07,350\n今天我们要去台北的夜市吃东西。\n")


# --- the fill ------------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_waiting_video_with_its_track_is_filled_in_place_and_timed_to_that_video(language, fake):
    """Why: the item a video waited on is the one that takes its text — its id and place kept — the copy in the
    library's own folder (never beside the video), and its timing is the video's own: mined with no tsubasa."""
    text, codec = _full(language)
    store, data_dir, src, (video,) = _library(language)
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(2, "eng", "subrip"), _track(3, _TAG[language], codec)]},
             track_files={f"{name}#3": text, f"{name}#2": _ENGLISH})
    (item_id, before, _a), = _item(store)
    try:
        out = _fill(store, language)
        assert out["filled"] == 1 and out["failed"] == 0
        (same, rel, availability), = _item(store)
        stem = os.path.splitext(name)[0]
        assert same == item_id and availability == "available"
        assert rel == f"{before.rpartition('/')[0]}/{stem}.{language}.{'ass' if codec == 'ass' else 'srt'}"
        copy = os.path.join(data_dir, *rel.split("/"))
        with open(copy, encoding="utf-8-sig") as f:
            assert f.read() == text
        record = library.pairing_of(store, item_id)
        assert record["video_path"] == os.path.abspath(video) and record["verdict"] == "extracted"
        assert record["track"]["index"] == 3 and record["subtitle_source"]["provider"] == "video-track"
        assert fit_check.fit(record, video, copy, tsubasa="")[:2] == (fit_check.TIMED, "track")
        assert [c[1] for c in fake.calls()] == ["version", "profiles", "inspect", "extract"]
        assert not os.path.exists(os.path.join(os.path.dirname(tracks.cache_path(language)),
                                               f"tracks-run-{language}"))       # Anki Miner's run folder gone
    finally:
        store.__exit__(None, None, None)


def test_a_track_copy_changed_since_is_checked_like_any_other():
    """Why: the record vouches for the bytes it was copied as — an edited copy is no longer the video's own track."""
    record = {"producer": "source", "verdict": "extracted", "subtitle_sha256": "0" * 64, "video_path": "x.mkv"}
    assert not fit_check.track_timed(record, os.path.join(RES, "ja", "library_episode.ass"))
    path = os.path.join(RES, "ja", "library_episode.ass")
    with open(path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    assert fit_check.track_timed(dict(record, subtitle_sha256=sha), path)
    # hato's own `extracted` (its record, the same bytes): never Surasura's track rule — hato's verdict, or tsubasa
    assert not fit_check.track_timed(dict(record, subtitle_sha256=sha, producer="hato"), path)
    assert not fit_check.track_timed(dict(record, subtitle_sha256=sha, producer=None), path)


def test_two_japanese_tracks_the_full_dialogue_wins(fake):
    """Why: an untitled signs track beside the dialogue one: the one with the most dialogue lines is the episode."""
    text, _codec = _full("ja")
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(2, "jpn", default=True), _track(3, "jpn")]},
             track_files={f"{name}#2": _SIGNS, f"{name}#3": text})
    try:
        assert _fill(store, "ja")["filled"] == 1
        (item_id, rel, _a), = _item(store)
        assert library.pairing_of(store, item_id)["track"] == {"index": 3, "codec": "ass", "language": "jpn",
                                                              "title": None, "tried": 2}
    finally:
        store.__exit__(None, None, None)


def test_an_untagged_english_track_is_never_taken(fake):
    """Why: an untagged track is the library's only when its text is (the look's one language rule)."""
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(2, None, "subrip")]}, track_files={f"{name}#2": _ENGLISH})
    try:
        out = _fill(store, "ja")
        assert out["filled"] == 0 and out["none"] == 1 and _waiting(store) == 1
        assert _copies(data_dir) == []                                             # no stray copy
    finally:
        store.__exit__(None, None, None)


def test_picture_subtitles_are_said_and_the_video_is_asked_again_only_once_it_changes(fake):
    """Why: a PGS-only video is never a silent miss — its row says so — and is never asked again until the file
    changes (S19); a changed file is asked again."""
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(2, "jpn", "hdmv_pgs_subtitle", text=False)]})
    try:
        assert _fill(store, "ja")["pictures"] == 1
        (item_id, rel, _a), = _item(store)
        assert tracks.note(rel) == tracks.PICTURES == tracks.note(rel, "ja")
        row = view_rows._row(0, "arrivals", [{"id": item_id, "tier": "arrivals", "ord": 1.0, "rel_path": rel,
                                              "title": name, "source_type": None, "availability": "waiting",
                                              "work_id": None, "piece_id": 1}], {}, {}, {}, set(), set(), 20)
        assert row.status.label == "Subtitles drawn as pictures: not read yet"
        assert row.episodes[0].play_tip.startswith("Subtitles drawn as pictures")
        assert _fill(store, "ja") == {"filled": 0, "pictures": 0, "none": 0, "failed": 0, "asked": 0}
        assert len(fake.calls("inspect")) == 1                                    # not asked again
        t = time.time() - 30
        os.utime(video, (t, t))
        assert _fill(store, "ja")["asked"] == 1
    finally:
        store.__exit__(None, None, None)


def test_no_anki_miner_says_so_remembers_nothing_and_never_fails(fake):
    """Why: without Anki Miner nothing can look inside a video — the waiting row's tip says what would, and the videos
    are asked once it is installed (nothing remembered)."""
    store, data_dir, src, (video,) = _library("ja")
    try:
        assert tracks.fill(store, "ja", settings={}) == {"no_miner": True}      # a test never finds a real one
        (item_id, rel, _a), = _item(store)
        assert tracks.note(rel) == tracks.NO_MINER
        with open(tracks.cache_path("ja"), encoding="utf-8") as f:
            assert json.load(f)["videos"] == {}
        row = view_rows._row(0, "arrivals", [{"id": item_id, "tier": "arrivals", "ord": 1.0, "rel_path": rel,
                                              "title": "x", "source_type": None, "availability": "waiting",
                                              "work_id": None, "piece_id": 1}], {}, {}, {}, set(), set(), 20)
        assert row.status.label == "No subtitles yet" and "once Anki Miner is installed" in row.status.tip
        assert fake.calls() == []
    finally:
        store.__exit__(None, None, None)


def test_one_videos_failure_never_holds_the_others(fake):
    """Why: a run that failed now (the copy failed: VIDEO_UNREADABLE from extract) is asked again — remembered only after
    FAILS of them at the same stats, so a failure that holds never costs a whole-video read every look; one whose
    track Anki Miner says is no text is remembered at once; the third video is filled."""
    text, _codec = _full("ja")
    store, data_dir, src, videos = _library("ja", names=("ep01", "ep02", "ep03"))
    a, b, c = (os.path.basename(v) for v in videos)
    fake.set(tracks={n: [_track(2, "jpn")] for n in (a, b, c)}, track_files={f"{c}#2": text},
             track_errors={f"{a}#2": "VIDEO_UNREADABLE", f"{b}#2": "TRACK_NOT_TEXT"})
    try:
        out = _fill(store, "ja")
        assert (out["filled"], out["failed"]) == (1, 1) and _waiting(store) == 2
        assert sorted(v.get("outcome", "asked again") for v in _remembered("ja").values()) ==             ["asked again", "extracted", "none"]
        for n in range(2, tracks.FAILS + 1):
            assert _fill(store, "ja")["failed"] == 1 and len(fake.calls("extract")) == 3 + n - 1   # one a video
        assert _remembered("ja")[next(k for k, v in _remembered("ja").items() if v.get("fails"))]["outcome"] == "failed"
        assert _fill(store, "ja")["asked"] == 0                                    # remembered: never read again
    finally:
        store.__exit__(None, None, None)


def test_an_anki_miner_before_3_11_is_never_asked_inside_a_video_and_the_rows_say_so(fake):
    """Why: an Anki Miner whose `version` names no `inspect` / `tracks` can't look inside a video — it is never run on
    every look (its version is read once while it stays the same program), and the waiting rows say what would."""
    store, data_dir, src, (video,) = _library("ja")
    try:
        fake.set(features=["named-words-whitelisted"], app="3.10.1")
        assert _fill(store, "ja") == {"no_miner": True}
        assert _fill(store, "ja") == {"no_miner": True}
        assert [c[1] for c in fake.calls()] == ["version"]                     # read once, never inspect / extract
        (item_id, rel, _a), = _item(store)
        assert tracks.note(rel) == tracks.NO_MINER and _remembered("ja") == {}
    finally:
        store.__exit__(None, None, None)


def test_a_whole_call_refused_or_a_broken_answer_leaves_every_video_for_later(fake):
    """Why: no ffmpeg (SETUP_ERROR) or an answer that can't be read says nothing of the videos: none is remembered."""
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    try:
        fake.set(tracks={name: [_track(2, "jpn")]}, extract="setup-error")
        assert _fill(store, "ja")["failed"] == 1
        fake.set(replay={"inspect": {"schema": 1, "command": "inspect", "ok": True, "result": {"sources": []}}})
        assert _fill(store, "ja")["failed"] == 1
        assert _remembered("ja") == {} and _waiting(store) == 1
    finally:
        store.__exit__(None, None, None)


def test_an_item_no_longer_waiting_takes_nothing_and_leaves_no_copy(fake, monkeypatch):
    """Why: filled or removed meanwhile (another window, a subtitle that came) — the store writes nothing, and the
    copy made a moment ago is no item's, so it goes again."""
    text, _codec = _full("ja")
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(2, "jpn")]}, track_files={f"{name}#2": text})
    (item_id, rel, _a), = _item(store)
    try:
        assert store.fill_track(item_id, f"{ls.CONTENT_FOLDER}/{_SHOW['ja']}/x.ja.ass", "0" * 64, {},
                                video_key="another video") is False       # the video changed: nothing written
        assert _waiting(store) == 1
        monkeypatch.setattr(type(store), "fill_track", lambda *a, **k: False)
        out = _fill(store, "ja")                       # no longer waiting: nothing to do, nothing failed
        assert (out["filled"], out["failed"], out["asked"]) == (0, 0, 1)
        assert _copies(data_dir) == []
    finally:
        store.__exit__(None, None, None)


# --- the window's looks -------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_windows_look_fills_a_waiting_video_on_a_worker_of_its_own(language, fake, monkeypatch):
    """Why: no one presses anything for it — a look that finds a video with no subtitle file is followed by its track
    step, off the looks' worker (a long copy never holds a look or Refresh), and the episode comes in by itself."""
    from app.services import source_looks
    text, codec = _full(language)
    store, data_dir = _empty(language)
    src = _drive("driveA")
    video = _video(os.path.join(src, _SHOW[language], f"{_SHOW[language]} - 07.mkv"))
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(3, _TAG[language], codec)]}, track_files={f"{name}#3": text})
    with store:
        store.add_source(src)
    real = source_looks.settings_manager.load_settings
    monkeypatch.setattr(source_looks.settings_manager, "load_settings",
                        lambda *a, **k: dict(real(*a, **k), connect_anki_miner_path=FAKE))
    looks = source_looks.SourceLooks(ls.StoreOpener(language, data_dir, store.user_files_dir), language,
                                     kind=lambda _p: "network")
    try:
        looks.asked(refreshed=True)
        assert looks.idle(60)
        assert looks._tracks.name != looks._worker.name and not looks._tracking
        with ls.open_store(language, data_dir, store.user_files_dir) as s:
            (_i, rel, availability), = _item(s)
            assert availability == "available" and rel.endswith(f"{_SHOW[language]} - 07.{language}."
                                                                 f"{'ass' if codec == 'ass' else 'srt'}")
        assert [c[1] for c in fake.calls()] == ["version", "profiles", "inspect", "extract"]
        looks.asked(refreshed=True)                  # the next look: nothing waits, Anki Miner never asked again
        assert looks.idle(60) and len(fake.calls()) == 4
    finally:
        looks.close()


# --- the review's scenarios (st-tracks-adversary.md B1, S1, S2, S4, L5) ------------------------------------------- #
_SRT_JA = "".join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\nすみません、この本を借りたいのですが。{i}\n\n"
                  for i in range(1, 30))


def _subtitle_beside(video, text, age=60):
    sub = os.path.splitext(video)[0] + ".ja.srt"
    with open(sub, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    t = time.time() - age
    os.utime(sub, (t, t))
    return sub


def _root(store):
    return store.conn.execute("SELECT id FROM roots WHERE kind = 'source'").fetchone()[0]


def _versions(store, item_id):
    return [json.loads(p) for (p,) in store.conn.execute(
        "SELECT pairing FROM pairings WHERE item_id = ? ORDER BY rowid", (item_id,)) if json.loads(p).get("version")]


def _no_subrip_in_an_ass(data_dir):
    """No `.ass` copy in the library holds SubRip (B1's damage: an episode silently read as empty)."""
    return all("-->" not in open(p, encoding="utf-8-sig").read() for p in _copies(data_dir) if p.endswith(".ass"))


def test_a_subtitle_file_come_later_is_another_version_and_its_edits_never_overwrite_the_track(fake):
    """Why (B1): the episode's text is its video's own track; a subtitle file dropped beside it later is another
    version of the episode (LM1b) — never a live origin, whose next edit a look would copy over the track's copy (SubRip
    bytes in a `.ass`, an episode silently read as empty). Which version is the episode's text is then the library's
    one rule (LM3's switch, PROVISIONAL here): the file named like its video wins, and is followed as any copy is."""
    from app import sources
    text, codec = _full("ja")
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(3, "jpn", codec)]}, track_files={f"{name}#3": text})
    try:
        assert _fill(store, "ja")["filled"] == 1
        (item_id, rel, _a), = _item(store)
        copy = os.path.join(data_dir, *rel.split("/"))
        before = open(copy, "rb").read()
        sub = _subtitle_beside(video, _SRT_JA)
        got = _look(store, "ja", _root(store), full=True)
        assert got["added"] == 0 and got["attached"] == 0 and len(_item(store)) == 1     # a version, no item
        assert _no_subrip_in_an_ass(data_dir)
        with open(sub, "a", encoding="utf-8", newline="\n") as f:          # re-timed / edited in place
            f.write("\n99\n00:20:00,000 --> 00:20:02,000\nもう一度言ってください。\n")
        t = time.time() - 50
        os.utime(sub, (t, t))
        sources._LOOKED.clear()
        _look(store, "ja", _root(store), full=True)
        (same, rel, _a), = _item(store)
        held = open(os.path.join(data_dir, *rel.split("/")), "rb").read()
        assert same == item_id and _no_subrip_in_an_ass(data_dir)
        assert held == before or held == open(sub, "rb").read()   # the track as it was, or the file it switched to
        record = library.pairing_of(store, item_id)               # and Connect's gate reads the text it holds
        assert fit_check.track_timed(record, os.path.join(data_dir, *rel.split("/"))) is (held == before)
    finally:
        store.__exit__(None, None, None)


def test_a_take_in_reads_the_extracted_tracks_through_their_index_and_still_finds_one(fake, monkeypatch):
    """Why (R6, G1): every take-in reads which items hold their video's own track under the write lock; walking every
    origin's record there held the lock ~45 ms a batch at 20k origins. The read goes through `pairings_extracted` (a
    look's batch then holds it briefly) and still finds the filled item, so the subtitle is a version, not an item."""
    text, codec = _full("ja")
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(3, "jpn", codec)]}, track_files={f"{name}#3": text})
    try:
        assert tracks.fill(store, "ja", settings={}, path=FAKE)["filled"] == 1
        assert store.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'pairings_extracted'").fetchone()
        _subtitle_beside(video, _SRT_JA)
        reads, waiting = [], []
        store.conn.set_trace_callback(lambda sql: reads.append(sql) if "$.verdict" in sql and "SELECT p.item_id" in sql
                                      else waiting.append(sql) if "availability = 'waiting'" in sql and
                                      "CROSS JOIN pairings" in sql else None)
        _look(store, "ja", _root(store), full=True)
        store.conn.set_trace_callback(None)
        assert reads, "the take-in read the extracted tracks"
        plan = " ".join(str(r) for r in store.conn.execute("EXPLAIN QUERY PLAN " + reads[0]).fetchall())
        assert "pairings_extracted" in plan, plan
        if waiting:                                   # the waiting videos' read (K5) by its index too
            plan = " ".join(str(r) for r in store.conn.execute("EXPLAIN QUERY PLAN " + waiting[0]).fetchall())
            assert "items_waiting" in plan, plan
        (item_id, rel, availability), = _item(store)
        assert availability == "available"
    finally:
        store.__exit__(None, None, None)


def test_a_fill_landing_while_a_look_brings_its_subtitle_never_makes_a_second_item(fake, monkeypatch):
    """Why (S2): the look read the video as waiting and planned its new subtitle into that gap; the track worker filled
    the gap first. The subtitle is then a version of that episode, its copy no item's — never a second item."""
    text, codec = _full("ja")
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(3, "jpn", codec)]}, track_files={f"{name}#3": text})
    sub = _subtitle_beside(video, _SRT_JA)
    real, done = ls.Store.take_in, []

    def take_in(self, *a, **k):
        if not done:                                  # the fill commits between the look's reads and its write
            done.append(tracks.fill(self, "ja", settings={}, path=FAKE))
        return real(self, *a, **k)
    monkeypatch.setattr(ls.Store, "take_in", take_in)
    try:
        _look(store, "ja", _root(store), full=True)
        assert done[0]["filled"] == 1
        (item_id, rel, availability), = _item(store)
        assert availability == "available" and _no_subrip_in_an_ass(data_dir)
        assert rel.endswith(".srt") or os.path.abspath(sub) in {v["origin"] for v in _versions(store, item_id)}
        assert [os.path.relpath(p, data_dir).replace(os.sep, "/") for p in _copies(data_dir)] == [rel]   # no stray
    finally:
        store.__exit__(None, None, None)


def test_a_waiting_video_that_moved_is_asked_at_its_new_place(fake):
    """Why (S1): a waiting video moved to another folder being read keeps its one waiting item (D3 a); its tracks are
    asked where it is now, and the record Connect reads (the live one) is the one that says where its text came from."""
    from tests.test_sources_moves import _move
    text, codec = _full("ja")
    store, data_dir = _empty("ja")
    a, b = _drive("driveA"), _drive("driveB")
    name = f"[Grp] {_SHOW['ja']} - 01.mkv"
    _video(os.path.join(a, _SHOW["ja"], name), body=b"\x1a\x45\xdf\xa3 moved video body")
    with store:
        _look(store, "ja", store.add_source(a), first=True)
        _move(os.path.join(a, _SHOW["ja"]), os.path.join(b, _SHOW["ja"]))
        _look(store, "ja", store.add_source(b))
        fake.set(tracks={name: [_track(3, "jpn", codec)]}, track_files={f"{name}#3": text})
        assert tracks.fill(store, "ja", settings={}, path=FAKE)["filled"] == 1
        (item_id, rel, availability), = _item(store)
        record = library.pairing_of(store, item_id)
        assert availability == "available" and record["verdict"] == "extracted"
        assert record["video_path"] == os.path.abspath(os.path.join(b, _SHOW["ja"], name))


def test_two_videos_of_one_name_each_get_a_copy_of_their_own(fake):
    """Why (S4): an MKV and an MP4 release of one film, both waiting, the same track text — the second never takes
    the first's file (one item a file), and nothing is extracted again at the next look."""
    text, codec = _full("ja")
    store, data_dir = _empty("ja")
    src = _drive("driveA")
    v1 = _video(os.path.join(src, _SHOW["ja"], f"{_SHOW['ja']} 劇場版.mkv"), body=b"\x1a\x45\xdf\xa3 mkv one")
    v2 = _video(os.path.join(src, _SHOW["ja"], f"{_SHOW['ja']} 劇場版.mp4"), body=b"\x00\x00\x00 ftyp mp4 two")
    n1, n2 = os.path.basename(v1), os.path.basename(v2)
    fake.set(tracks={n1: [_track(3, "jpn", codec)], n2: [_track(2, "jpn", codec)]},
             track_files={f"{n1}#3": text, f"{n2}#2": text})
    with store:
        _look(store, "ja", store.add_source(src), first=True)
        if _waiting(store) < 2:
            pytest.skip("one of the two releases is a version (LM1b), not a waiting item of its own")
        out = tracks.fill(store, "ja", settings={}, path=FAKE)
        rels = sorted(r for _i, r, _a in _item(store))
        assert out["filled"] == 2 and len(set(rels)) == 2
        calls = len(fake.calls())
        assert tracks.fill(store, "ja", settings={}, path=FAKE)["asked"] == 0 and len(fake.calls()) == calls


def test_picture_subtitles_beside_an_english_text_track_are_said(fake):
    """Why (L5): a Japanese picture track and an untagged text track that turns out English — the row says the
    subtitles are pictures, never a plain *No subtitles yet*."""
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(2, "jpn", "hdmv_pgs_subtitle", text=False), _track(3, None, "subrip")]},
             track_files={f"{name}#3": _ENGLISH})
    try:
        assert _fill(store, "ja")["pictures"] == 1
        (_i, rel, _a), = _item(store)
        assert tracks.note(rel) == tracks.PICTURES
    finally:
        store.__exit__(None, None, None)


# --- the second pass (st-tracks-adversary.md § Second pass: N1, N2) ---------------------------------------------- #
def test_an_english_subtitle_named_like_the_video_never_replaces_its_japanese_track(fake):
    """Why (N1): a file matched through its video skips the look's language check, and LM3's switch ranks a file named
    like the video first — so a later English `.srt` would have become the episode's text. An episode whose text is its
    video's own track is never switched: the file is a spare version, the Japanese stays."""
    text, codec = _full("ja")
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    fake.set(tracks={name: [_track(3, "jpn", codec)]}, track_files={f"{name}#3": text})
    try:
        assert _fill(store, "ja")["filled"] == 1
        (item_id, rel, _a), = _item(store)
        copy = os.path.join(data_dir, *rel.split("/"))
        before = open(copy, "rb").read()
        sub = os.path.splitext(video)[0] + ".srt"
        english = [  # the episode's dialogue in English, a full subtitle (never thin beside the Japanese: A6)
            "The song from the opening.", "Across the far-off sky.", "City Library.",
            "Excuse me, I'd like to borrow this book.", "Do you have a library card?",
            "No... this is my first time here.", "In that case, on this form,", "please write your name and address.",
            "I see. May I borrow a pen?", "Here you are.", "Thank you very much.",
            "You can borrow it for up to two weeks. You can extend it, too.", "When is it due back?",
            "On the twentieth.", "I'll come back before then."]
        with open(sub, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(f"{i}\n00:01:{i + 30:02d},000 --> 00:01:{i + 30:02d},900\n{line}\n\n"
                            for i, line in enumerate(english, 1)))
        t = time.time() - 60
        os.utime(sub, (t, t))
        got = _look(store, "ja", _root(store), full=True)
        assert got["switched"] == 0 and got["added"] == 0 and _item(store) == [(item_id, rel, "available")]
        assert open(copy, "rb").read() == before
        assert fit_check.track_timed(library.pairing_of(store, item_id), copy)
    finally:
        store.__exit__(None, None, None)


def test_failures_that_are_not_the_videos_own_never_retire_it(fake):
    """Why (N2): ffprobe missing (inspect's SETUP_ERROR on each source) or a window closing mid-copy says nothing of
    the video — however many looks see it, the video is asked again once Anki Miner can answer."""
    text, codec = _full("ja")
    store, data_dir, src, (video,) = _library("ja")
    name = os.path.basename(video)
    try:
        fake.set(tracks={name: "SETUP_ERROR"})
        for _ in range(tracks.FAILS + 1):
            assert _fill(store, "ja")["failed"] == 1
        fake.set(tracks={name: [_track(3, "jpn", codec)]}, track_errors={f"{name}#3": "CANCELLED"})
        for _ in range(tracks.FAILS + 1):
            assert _fill(store, "ja")["failed"] == 1
        assert all(not v.get("outcome") for v in _remembered("ja").values())
        fake.set(tracks={name: [_track(3, "jpn", codec)]}, track_files={f"{name}#3": text})
        assert _fill(store, "ja")["filled"] == 1                         # back: it comes in
    finally:
        store.__exit__(None, None, None)
