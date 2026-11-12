# SPDX-License-Identifier: GPL-3.0-or-later
"""Mado-Q (alpha 8, Sonic 2026-10-31: "i want it in the order. Ideally their first video (so for example the one that
was first in that list, on youtube it would be at the bottom, not the top of that list)"): one rule for a playlist's
learning order (`downloader.series_order`), used by setup's first video and every run's sidecars (`series_places`),
which the library orders by.

What a wrong answer would cost a learner: a podcast starting at its newest episode (#43, the top of YouTube's list),
or a course its maker put in order turned upside down.

The playlist is a real podcast's shape, read 2026-10-31 by yt-dlp 2026.10.26 (`-J --flat-playlist --extractor-args
youtubetab:approximate_date`), trimmed to the fields read, its names, titles and ids
made up (`fixtures/real_japanese_podcast_flat.json`). yt-dlp itself is
faked at `_probe` / `_run_ytdlp`: hermetic."""
import json
import os

from modules.youtube_downloader import downloader as core

HERE = os.path.dirname(os.path.abspath(__file__))
IN_LIST = "https://www.youtube.com/watch?v=podcast0001&list=PLsamplepodcast0000000000000000001"
PLAYLIST = "https://www.youtube.com/playlist?list=PLsamplepodcast0000000000000000001"
VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n今日はリアルな日本語で話します\n"


def _real():
    with open(os.path.join(HERE, "fixtures", "real_japanese_podcast_flat.json"), encoding="utf-8") as f:
        return json.load(f)


def _entries(*dated):
    return {"_type": "playlist", "id": "PLcourse0000000001", "title": "日本語の授業",
            "entries": [dict({"id": f"lesson{n:05d}", "title": f"第{n}課"}, **({"timestamp": t} if t else {}))
                        for n, t in enumerate(dated, 1)]}


class Res:
    def __init__(self, stdout="", stderr=""):
        self.stdout, self.stderr, self.returncode = stdout, stderr, 0


# --- the rule ------------------------------------------------------------------------------------------------------ #
def test_a_playlist_shown_newest_at_the_top_starts_at_episode_1():
    """The list: #43 at YouTube's top, #1 at its bottom (the rough dates run newest to oldest) -> turned over."""
    order = core.series_order(_real())
    assert order[0]["id"] == "podcast0044" and "#1】" in order[0]["title"]
    assert order[-1]["id"] == "podcast0001" and "#43】" in order[-1]["title"]
    assert len(order) == 44


def test_a_course_in_order_or_with_no_dates_or_no_clear_majority_keeps_the_lists_own_order():
    """Dates rising (a course its maker ordered), none at all, all the same rough day ("1 year ago"), as many
    neighbours each way, or newest-first by less than two to one (IK-1): the list's own order — a maker's order is
    never second-guessed without clear evidence. Two to one or more: turned over."""
    turned = {(300, None, 100, None), (400, 300, 200, 100, 200)}
    for dated in ((100, 200, 300), (None, None, None), (500, 500, 500), (100, 300, 200, 400, 300),
                  (300, 200, 100, 200), (300, None, 100, None), (400, 300, 200, 100, 200)):
        given = [e["id"] for e in _entries(*dated)["entries"]]
        got = [e["id"] for e in core.series_order(_entries(*dated))]
        assert got == (given[::-1] if dated in turned else given), dated
        assert core.series_reversed(_entries(*dated)) == (dated in turned)
    assert core.series_order(None) == [] and core.series_order({"entries": [None]}) == []


def test_upload_days_count_when_there_is_no_timestamp():
    info = _entries(None, None, None)
    for entry, day in zip(info["entries"], ("20261020", "20260901", "20250105")):
        entry["upload_date"] = day
    assert [e["id"] for e in core.series_order(info)] == ["lesson00003", "lesson00002", "lesson00001"]
    info["entries"][0]["upload_date"] = "not a day"
    assert core._when(info["entries"][0]) is None


def test_places_count_from_the_lists_first_video_and_name_the_list():
    places = core.series_places(_real())
    assert places["podcast0044"] == {"id": "PLsamplepodcast0000000000000000001", "index": 1}
    assert places["podcast0001"]["index"] == 44                 # (the list's one private entry keeps its place too)
    assert sorted(p["index"] for p in places.values()) == list(range(1, 45))
    assert core.series_places({"id": "podcast0001", "title": "a video"}) == {}
    assert core.series_places(dict(_real(), id="")) == {}


def test_the_video_a_link_names():
    assert core.video_id(IN_LIST) == "podcast0001"
    assert core.video_id("https://youtu.be/podcast0001?list=PLsamplepodcast0000000000000000001") == "podcast0001"
    assert core.video_id(PLAYLIST) is None and core.video_id("") is None
    assert core.video_id("https://www.youtube.com/watch?v=short") is None


# --- setup's first video --------------------------------------------------------------------------------------------- #
def test_a_bare_playlist_link_brings_in_the_series_first_and_a_video_link_its_own_video():
    link, entry = core.first_video(PLAYLIST, _real())
    assert entry["id"] == "podcast0044" and link == "https://www.youtube.com/watch?v=podcast0044"
    link, entry = core.first_video(IN_LIST, _real())             # A8B-L1: the video the link names, first
    assert entry["id"] == "podcast0001"
    gone = _real()
    gone["entries"][0]["title"] = "[Private video]"              # the named video gone: the series' first instead
    assert core.first_video(IN_LIST, gone)[1]["id"] == "podcast0044"


def test_setup_reads_a_video_link_in_a_list_as_its_list_once_and_falls_back_to_the_video_quietly(monkeypatch):
    """One read when the list holds the video (its place known); a list that can't be read or doesn't hold it costs
    one more read of the video alone, and its failure is never said (setup's screen shows only real problems)."""
    calls = []
    answers = {}

    def probe(url, log, single=False, **kw):
        calls.append(single)
        assert single or kw.get("timeout") == core.LIST_S          # IK-2: the list read waits LIST_S at most
        found = answers[single]
        if found is None:
            log(f"  ! could not read {url}: YouTube couldn't be reached: check your internet connection")
        return found
    monkeypatch.setattr(core, "_probe", probe)
    video = {"id": "podcast0001", "title": "【Japanese Podcast #43】", "channel": "hanashi radio"}
    for listed, expect in ((_real(), [False]), (None, [False, True]), (_entries(1, 2), [False, True])):
        answers.update({False: listed, True: video})
        calls.clear()
        log = []
        got = core._probe_first(IN_LIST, log.append)
        assert calls == expect and log == []
        assert got is (listed if expect == [False] else video)
    calls.clear()
    assert core._probe_first(PLAYLIST, [].append) is video and calls == [True]     # no video named: as before
    monkeypatch.setattr(core, "_probe", lambda url, log, single=False, **_kw: calls.append(single) or log("Stopped."))
    calls.clear()
    log = []
    assert core._probe_first(IN_LIST, log.append) is None and calls == [False] and log == ["Stopped."]


def test_the_probe_asks_for_each_entrys_rough_date(monkeypatch):
    seen = []
    monkeypatch.setattr(core, "_run_ytdlp", lambda args, timeout=None, **_k: seen.append(args) or Res(stdout="{}"))
    core._probe(PLAYLIST, lambda _l: None)
    core._probe(IN_LIST, lambda _l: None, single=True)
    for args in seen:
        assert args[args.index("--extractor-args") + 1] == "youtubetab:approximate_date"


# --- every run writes each video's place into its sidecar ---------------------------------------------------------- #
def _fake_ytdlp(monkeypatch, videos, calls):
    def run(args, timeout=None, tick=None, **_k):
        calls.append(args)
        tmp = os.path.dirname(args[args.index("-o") + 1])
        for vid in videos:
            with open(os.path.join(tmp, f"{vid}.info.json"), "w", encoding="utf-8") as f:
                json.dump({"id": vid, "title": f"Podcast {vid}", "channel": "hanashi radio",
                           "webpage_url": f"https://youtu.be/{vid}", "subtitles": {"ja": [{"ext": "vtt"}]},
                           "automatic_captions": {}}, f, ensure_ascii=False)
            with open(os.path.join(tmp, f"{vid}.ja.vtt"), "w", encoding="utf-8") as f:
                f.write(VTT)
        return Res()
    monkeypatch.setattr(core, "_run_ytdlp", run)


def _sidecars(root):
    out = {}
    for folder, _d, files in os.walk(root):
        for name in files:
            if name.endswith(".surasura.json"):
                try:
                    with open(os.path.join(folder, name), encoding="utf-8") as f:
                        side = json.load(f)
                except ValueError:
                    continue
                out[side["video_id"]] = side.get("playlist")
    return out


def test_setups_first_video_keeps_its_place_so_the_rest_land_before_it(tmp_path, monkeypatch):
    """Sonic's link: episode 43 comes in alone (`--no-playlist`, A8B-1) and its sidecar says it is the list's 44th,
    so the library puts the rest (1–43) before it when they come."""
    monkeypatch.setattr(core, "_probe", lambda url, log, single=False, **_kw: _real() if not single else None)
    calls = []
    _fake_ytdlp(monkeypatch, ["podcast0001"], calls)
    core.extract([IN_LIST], str(tmp_path / "Processed"), lang="Japanese", log=lambda _l: None, first_only=True)
    assert calls and all("--no-playlist" in args for args in calls)
    assert _sidecars(tmp_path) == {"podcast0001": {"id": "PLsamplepodcast0000000000000000001", "index": 44}}


def test_a_playlists_run_writes_each_videos_place_and_a_single_video_none(tmp_path, monkeypatch):
    video = "https://www.youtube.com/watch?v=lecture0001"
    infos = {PLAYLIST: _real(), video: {"id": "lecture0001", "channel": "Ch A"}}
    monkeypatch.setattr(core, "_probe", lambda url, log: infos[url])
    calls = []
    _fake_ytdlp(monkeypatch, ["podcast0044", "podcast0043", "lecture0001"], calls)
    core.extract([PLAYLIST, video], str(tmp_path / "Processed"), lang="Japanese", log=lambda _l: None)
    side = _sidecars(tmp_path)
    assert side["podcast0044"]["index"] == 1 and side["podcast0043"]["index"] == 2
    assert side["lecture0001"] is None


def test_a_list_read_newest_first_is_fetched_from_its_end_so_a_stopped_run_keeps_the_series_start(tmp_path,
                                                                                                    monkeypatch):
    """IK-4: yt-dlp fetches a list top to bottom; Sonic's list is newest first, so a run stopped half-way kept episodes
    43…20 and the learner's next ones (1…) waited. Fetched with `--playlist-reverse` it keeps 1… first. A list in its
    maker's order, and a single video, are fetched as given."""
    course = _entries(100, 200, 300)
    course_link = "https://www.youtube.com/playlist?list=PLcourse0000000001"
    video = "https://www.youtube.com/watch?v=lecture0001"
    infos = {PLAYLIST: _real(), course_link: course, video: {"id": "lecture0001", "channel": "Ch A"}}
    monkeypatch.setattr(core, "_probe", lambda url, log, **_kw: infos[url])
    calls = []
    _fake_ytdlp(monkeypatch, [], calls)
    core.extract([PLAYLIST, course_link, video], str(tmp_path / "Processed"), lang="Japanese", log=lambda _l: None)
    by_link = {args[-1]: args for args in calls}
    assert "--playlist-reverse" in by_link[PLAYLIST]
    assert "--playlist-reverse" not in by_link[course_link] and "--playlist-reverse" not in by_link[video]


def test_a_later_run_counts_places_the_way_the_first_did_though_the_dates_no_longer_tell(tmp_path, monkeypatch):
    """A8Q-4: the first run read Sonic's list newest first and gave episode 1 place 1. A year on, every rough date reads
    "2 years ago" (no evidence either way): the later run still counts from episode 1, as the library's sidecars say —
    a new episode 44 at YouTube's top lands last, never second."""
    later = _real()
    for entry in later["entries"]:
        entry["timestamp"] = 1700000000
        entry["title"] = "Everyday Japanese Podcast"            # (no episode numbers either: nothing tells, A8Q-5)
    later["entries"].insert(0, {"_type": "url", "id": "NewEp44abcd", "title": "Everyday Japanese Podcast",
                                "url": "https://www.youtube.com/watch?v=NewEp44abcd"})
    assert not core.series_reversed(later)                       # the dates alone no longer tell
    side = tmp_path / "Processed" / "hanashi radio - Everyday Japanese Podcast (playlist)"
    side.mkdir(parents=True)
    for vid, index in (("podcast0044", 1), ("podcast0043", 2), ("podcast0042", 3)):
        (side / f"hanashi radio - Podcast [{vid}].surasura.json").write_text(json.dumps(
            {"video_id": vid, "cues": [], "playlist": {"id": later["id"], "index": index}}), encoding="utf-8")
    (side / "notes [podcast0044].surasura.json").write_text("not json", encoding="utf-8")   # read past, never a crash
    ids = {e["id"] for e in later["entries"]}
    known = core.places_in(str(tmp_path), later["id"], ids)
    assert known == {"podcast0044": 1, "podcast0043": 2, "podcast0042": 3}
    assert core.places_in(str(tmp_path), "PLsomeOtherList000", ids) == {}
    assert core.places_in(str(tmp_path), later["id"], {"podcast0044"}) == {"podcast0044": 1}   # only its videos
    assert core.list_direction(later, known) is True
    assert core.list_direction(later, {}) is False                # nothing known: the dates (none) — the maker's order
    places = core.series_places(later, core.list_direction(later, known))
    assert places["NewEp44abcd"]["index"] == 45 and places["podcast0044"]["index"] == 1

    monkeypatch.setattr(core, "_probe", lambda url, log, **_kw: later)
    calls = []
    _fake_ytdlp(monkeypatch, ["NewEp44abcd"], calls)
    core.extract([PLAYLIST], str(tmp_path / "Processed"), lang="Japanese", log=lambda _l: None)
    assert _sidecars(tmp_path)["NewEp44abcd"]["index"] == 45 and "--playlist-reverse" in calls[0]


def test_without_dates_the_episode_numbers_in_the_titles_tell_which_end_is_first():
    """A8Q-5: Sonic's list read years on — every rough date in one bucket — still starts at "#1": the titles' episode
    numbers fall from top to bottom (#43 … #1), two to one at least. A list whose titles carry no number, or rising
    ones, keeps its order."""
    old = _real()
    for entry in old["entries"]:
        entry.pop("timestamp", None)
    assert core.series_reversed(old) and core.series_order(old)[0]["id"] == "podcast0044"
    rising = _entries(None, None, None)
    for n, entry in enumerate(rising["entries"], 1):
        entry["title"] = f"日本語の授業 第{n}話"
    assert not core.series_reversed(rising)
    rising["entries"].reverse()
    assert core.series_reversed(rising)
    plain = {"entries": [{"id": "a" * 11, "title": "2025 In One Kanji"}, {"id": "b" * 11, "title": "Sleep 5 hours"}]}
    assert not core.series_reversed(plain)
    dated = _entries(100, 200, 300)                         # dates rising win over numbers falling
    for n, entry in zip((3, 2, 1), dated["entries"]):
        entry["title"] = f"#{n}"
    assert not core.series_reversed(dated)


def test_a_video_in_two_lists_pasted_together_keeps_its_first_lists_place(tmp_path, monkeypatch):
    """A8Q-8: two playlists of one channel in one run share a video; it keeps the first list's place (it was
    overwritten by the last's, and the first list's order lost it)."""
    other = {"_type": "playlist", "id": "PLshorts0000000001", "title": "Shorts",
             "entries": [{"id": "podcast0043", "title": "#2 short"}, {"id": "zzzzzzzzzzz", "title": "#1 short"}]}
    second = "https://www.youtube.com/playlist?list=PLshorts0000000001"
    infos = {PLAYLIST: _real(), second: other}
    monkeypatch.setattr(core, "_probe", lambda url, log, **_kw: infos[url])
    calls = []
    _fake_ytdlp(monkeypatch, ["podcast0043"], calls)
    core.extract([PLAYLIST, second], str(tmp_path / "Processed"), lang="Japanese", log=lambda _l: None)
    assert _sidecars(tmp_path)["podcast0043"] == {"id": "PLsamplepodcast0000000000000000001", "index": 2}
