"""J-CLIP: the journey's ▶ on a line the browser can't play (an .mkv) — the line's audio cut on the press through the
one cutter (`add_audio.cut`, Anki Miner's `media`), kept in a small cache of its own (`app/connect/clips.py`).

What each test holds still:
- **the line pressed, from its own video:** the clip is cut from the item's video at the line the id names (the
  subtitle's cue starting there now), sent as `video_file` — at a file's very first and very last line too;
- **kept, not stored:** the same press again plays what was kept (no second cut); a changed video is cut again; past
  the cap the oldest clips go first, never the one just cut, and a played clip is new again; the run folder is gone
  after every cut, a refused one too;
- **two presses at once:** one cut, both get its clip;
- **says why, never hangs:** Connect off, Anki Miner absent or too old, a line with no time or not in its file now,
  the video not on this PC, Anki Miner refusing — each its own words, nothing kept.

What a wrong answer costs: the wrong line's sound (a learner hears another sentence than the one shown), a ▶ that
spins forever, a cache that grows without end or lists itself as a card's media. Real Japanese and Chinese lines from
tests/Test Resources; Anki Miner is the suite's fake, run as a child (its `media` writes each clip holding the line's
text, so a clip's line is checked).
"""
import os
import threading

import pytest

from app import cues
from app.connect import add_audio, anki_miner, clips

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
SUBS = {"ja": os.path.join(RESOURCES, "ja", "placed_episode.srt"),
        "zh": os.path.join(RESOURCES, "zh", "night_market.srt")}
ITEM = 7


class Steps:
    """Connect's lookups as the route asks them: the item's subtitle in the library, its video on this PC."""

    def __init__(self, subtitle, video):
        self._subtitle, self._video = subtitle, video
        self.asked = []

    def subtitle(self, lang, job):
        self.asked.append(("subtitle", job["item_id"]))
        return self._subtitle

    def video(self, lang, job):
        self.asked.append(("video", job["item_id"]))
        return self._video


@pytest.fixture
def episode(tmp_path, fake_miner, monkeypatch):
    """-> (lang) -> dict: the language's real subtitle, an .mkv beside it (bytes the fake never reads), Steps, and the
    settings with Connect on; Anki Miner is the fake and answers `media`."""
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: set(asks) <= {"Z-10"})

    def make(lang):
        video = tmp_path / f"episode-{lang}.mkv"
        video.write_bytes(b"\x1aE\xdf\xa3 matroska")
        lines = [c for c in cues.read(SUBS[lang], lang)]
        return {"lang": lang, "lines": lines, "video": str(video), "steps": Steps(SUBS[lang], str(video)),
                "settings": {"connect_enabled": True}, "miner": fake_miner.path}
    return make


def _id(cue):
    return f"{ITEM}:{int(round(cues.seconds(cue.start) * 1000))}"


def _cut(ep, cue_or_id, **kw):
    line_id = cue_or_id if isinstance(cue_or_id, str) else _id(cue_or_id)
    return clips.cut(ep["lang"], line_id, settings=kw.get("settings", ep["settings"]), steps=ep["steps"],
                     miner=kw.get("miner", ep["miner"]))


def _said(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _media_calls(fake):
    return [c for c in fake.calls() if "media_lines" in c]


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("which", [0, -1])
def test_a_line_at_the_files_very_start_or_end_is_cut_from_its_video_as_that_line(episode, fake_miner, lang, which):
    # the first and the last line of a file are where a window of lines would run off the file's edge
    ep = episode(lang)
    cue = ep["lines"][which]
    path = _cut(ep, cue)
    assert os.path.dirname(path) == clips.root() and path.endswith(".mp3")
    assert cue.text.replace("\n", "") in _said(path).replace("\n", "")      # this line's sound, never a neighbour's
    (call,) = _media_calls(fake_miner)
    assert call["video_file"] == os.path.abspath(ep["video"]) and call["audio_file"] is None
    assert call["media_lines"] == [{"line_start": cues.seconds(cue.start), "line_expansion": [0, 0]}]
    assert clips.kind(path) == "audio/mpeg"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_same_press_again_plays_what_was_kept_and_leaves_no_run_folder(episode, fake_miner, lang):
    ep = episode(lang)
    cue = ep["lines"][1]
    first = _cut(ep, cue)
    again = _cut(ep, cue)
    assert again == first and len(_media_calls(fake_miner)) == 1             # kept: no second cut
    assert sorted(os.listdir(clips.root())) == [os.path.basename(first)]     # no run folder left, nothing else


def test_another_line_is_its_own_clip(episode, fake_miner):
    ep = episode("ja")
    one, two = _cut(ep, ep["lines"][0]), _cut(ep, ep["lines"][2])
    assert one != two and ep["lines"][2].text in _said(two)
    assert len(_media_calls(fake_miner)) == 2


def test_a_changed_video_is_cut_again_never_the_old_clip(episode, fake_miner):
    # the file changed since the Generate (re-encoded, replaced by a better release): its old clip is never its sound
    ep = episode("ja")
    cue = ep["lines"][3]
    first = _cut(ep, cue)
    with open(ep["video"], "ab") as f:
        f.write(b" another release")
    second = _cut(ep, cue)
    assert second != first and len(_media_calls(fake_miner)) == 2


def test_two_presses_of_one_line_at_once_are_one_cut(episode, fake_miner, monkeypatch):
    ep = episode("zh")
    cue = ep["lines"][1]
    started, go = threading.Event(), threading.Event()
    real = add_audio.cut

    def slow(*a, **k):
        started.set()
        go.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(add_audio, "cut", slow)
    got = []
    first = threading.Thread(target=lambda: got.append(_cut(ep, cue)))
    first.start()
    assert started.wait(10)
    second = threading.Thread(target=lambda: got.append(_cut(ep, cue)))
    second.start()
    second.join(0.3)
    assert second.is_alive()                    # the second press waits for the first's cut, never a cut of its own
    go.set()
    first.join(20)
    second.join(20)
    assert len(got) == 2 and got[0] == got[1]
    assert len(_media_calls(fake_miner)) == 1


def test_a_refused_cut_is_the_waiting_press_answer_too(episode, monkeypatch):
    ep = episode("ja")
    cue = ep["lines"][1]
    started, go = threading.Event(), threading.Event()

    def refuses(*a, **k):
        started.set()
        go.wait(10)
        raise anki_miner.AnkiMinerError("unreadable", "the video can't be read")
    monkeypatch.setattr(add_audio, "cut", refuses)
    said = []

    def press():
        try:
            _cut(ep, cue)
        except clips.Refused as e:
            said.append(e.message)
    first = threading.Thread(target=press)
    first.start()
    assert started.wait(10)
    started.clear()
    second = threading.Thread(target=press)
    second.start()
    second.join(0.3)
    assert second.is_alive()                    # waiting on the first press's cut
    go.set()
    first.join(20)
    second.join(20)
    assert said == [clips.FAILED.format("the video can't be read")] * 2
    assert not started.is_set()                 # the waiting press took the refusal, never a cut of its own
    assert not os.listdir(clips.root())         # nothing kept, no run folder


@pytest.mark.parametrize("change", ["size", "time"])
def test_a_video_replaced_by_one_of_the_same_size_or_the_same_time_is_cut_again(episode, fake_miner, change):
    # a re-encode of the same length (another release), or a copy that kept the old time: never the old clip
    ep = episode("ja")
    cue = ep["lines"][3]
    first = _cut(ep, cue)
    st = os.stat(ep["video"])
    if change == "size":
        with open(ep["video"], "ab") as f:
            f.write(b" longer")
        os.utime(ep["video"], ns=(st.st_atime_ns, st.st_mtime_ns))      # the same time as before
    else:
        with open(ep["video"], "r+b") as f:
            f.write(b"\x00")                                            # the same size
        os.utime(ep["video"], ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    assert _cut(ep, cue) != first and len(_media_calls(fake_miner)) == 2


def test_a_line_reworded_at_the_same_times_is_cut_again(episode, fake_miner, tmp_path):
    # the subtitle fixed (a typo, a better translation's timing kept): the clip is named by its text too
    ep = episode("ja")
    cue = ep["lines"][2]
    first = _cut(ep, cue)
    edited = tmp_path / "edited.srt"
    with open(SUBS["ja"], encoding="utf-8") as f:
        edited.write_text(f.read().replace(cue.text, "ごめん、全然聞いてなかった。"), encoding="utf-8")
    ep["steps"] = Steps(str(edited), ep["video"])
    second = _cut(ep, cue)
    assert second != first and "ごめん、全然聞いてなかった。" in _said(second)
    assert len(_media_calls(fake_miner)) == 2


def test_a_kept_clip_played_again_is_the_newest(episode, fake_miner):
    # played is new again: the cap's trim drops the clips nobody played lately, never one just heard
    ep = episode("zh")
    cue = ep["lines"][0]
    path = _cut(ep, cue)
    os.utime(path, (1_000_000, 1_000_000))
    assert _cut(ep, cue) == path
    assert os.stat(path).st_mtime > 2_000_000 and len(_media_calls(fake_miner)) == 1


def test_a_press_while_the_cut_ahead_reads_its_lines_stops_it_before_any_cut(episode, fake_miner):
    ep = episode("ja")

    class Pressed(Steps):
        def video(self, lang, job):
            clips.stop_ahead()                  # the learner presses while ahead looks its lines up
            return super().video(lang, job)
    ep["steps"] = Pressed(SUBS["ja"], ep["video"])
    assert clips.ahead("ja", [_id(c) for c in ep["lines"][:3]], settings=ep["settings"], steps=ep["steps"],
                       miner=ep["miner"]) == 3
    assert _ahead_done()
    assert _media_calls(fake_miner) == [] and clips._cutting == {}
    assert [a for a in ep["steps"].asked if a[0] == "video"] == [("video", ITEM)]     # no line looked up after it


def test_a_clip_that_cant_be_saved_says_so_in_surasuras_words_never_anki_miners_or_pythons(
        episode, fake_miner, monkeypatch):
    ep = episode("ja")
    real = os.replace

    def held(src, dst):
        if os.path.dirname(dst) == clips.root():
            raise PermissionError(13, "The process cannot access the file", dst)
        return real(src, dst)
    monkeypatch.setattr(clips.os, "replace", held)
    with pytest.raises(clips.Refused) as e:
        _cut(ep, ep["lines"][1])
    assert e.value.message == clips.CANT_KEEP and "Error" not in e.value.message
    assert "Anki Miner" not in e.value.message
    monkeypatch.setattr(clips, "_cut", lambda *a: 1 / 0)
    with pytest.raises(clips.Refused) as e:
        _cut(ep, ep["lines"][2])
    assert e.value.message == clips.WENT_WRONG


def test_past_the_cap_the_oldest_clips_go_first_never_the_one_just_cut_and_a_played_one_is_new_again(tmp_path):
    folder = tmp_path / "clips"
    folder.mkdir()
    made = []
    for k in range(5):
        path = folder / f"{k:040x}.mp3"
        path.write_bytes(b"x" * 100)
        os.utime(path, (1_000_000 + k, 1_000_000 + k))
        made.append(str(path))
    os.utime(made[0], (2_000_000, 2_000_000))   # the oldest one played again: the newest now
    (folder / "notes.txt").write_text("not a clip", encoding="utf-8")
    clips._trim(str(folder), keep=made[1], cap=250)
    left = sorted(os.listdir(folder))
    # 500 bytes over a 250 cap: three go, oldest first (2, 3, 4 are older than 0 now) — 1 is kept as the one just cut
    assert left == sorted([os.path.basename(made[0]), os.path.basename(made[1]), "notes.txt"])


def test_a_run_folder_a_crash_left_goes_once_old_and_a_fresh_one_stays(tmp_path):
    folder = tmp_path / "clips"
    (folder / ".run-old-1").mkdir(parents=True)
    (folder / ".run-new-2").mkdir()
    os.utime(folder / ".run-old-1", (1_000_000, 1_000_000))
    clips._trim(str(folder))
    assert sorted(os.listdir(folder)) == [".run-new-2"]


def test_the_cache_folder_deleted_at_any_time_is_cut_again(episode, fake_miner):
    import shutil
    ep = episode("ja")
    cue = ep["lines"][4]
    _cut(ep, cue)
    shutil.rmtree(clips.root())
    path = _cut(ep, cue)
    assert os.path.isfile(path) and len(_media_calls(fake_miner)) == 2


def test_connect_off_says_so_and_looks_nothing_up(episode, fake_miner):
    ep = episode("ja")
    with pytest.raises(clips.Refused) as e:
        _cut(ep, ep["lines"][0], settings={"connect_enabled": False})
    assert e.value.message == clips.OFF and e.value.kind == "off"
    assert ep["steps"].asked == [] and not fake_miner.calls()


@pytest.mark.parametrize("line_id", ["p1f2e3d4c", "", "7:", "7:12x", None])
def test_a_line_with_no_time_in_its_file_is_refused_in_words(episode, line_id):
    # a book's line or a file the store doesn't hold: the page names it by a hash, never `<item>:<ms>`
    ep = episode("zh")
    with pytest.raises(clips.Refused) as e:
        clips.cut("zh", line_id, settings=ep["settings"], steps=ep["steps"], miner=ep["miner"])
    assert e.value.message == clips.NO_LINE


def test_a_line_not_in_its_file_now_is_gone(episode, fake_miner):
    # the subtitle re-timed since the Generate: no cue starts where the page's line did
    ep = episode("ja")
    with pytest.raises(clips.Refused) as e:
        _cut(ep, f"{ITEM}:999999")
    assert e.value.message == clips.GONE and e.value.kind == "gone"
    assert not _media_calls(fake_miner)


def test_the_video_not_on_this_pc_says_so(episode, fake_miner):
    ep = episode("zh")
    ep["steps"]._video = None                   # a share offline, a video moved or deleted
    with pytest.raises(clips.Refused) as e:
        _cut(ep, ep["lines"][0])
    assert e.value.message == clips.NO_VIDEO
    ep["steps"]._video = os.path.join(os.path.dirname(ep["video"]), "gone.mkv")
    with pytest.raises(clips.Refused):
        _cut(ep, ep["lines"][0])
    assert not _media_calls(fake_miner)


def test_a_busy_library_says_press_again(episode):
    from app.connect import runner
    ep = episode("ja")

    def busy(lang, job):
        raise runner.Wait("the library is busy")
    ep["steps"].video = busy
    with pytest.raises(clips.Refused) as e:
        _cut(ep, ep["lines"][0])
    assert e.value.message == clips.BUSY and e.value.kind == "busy"


def test_anki_miner_absent_or_too_old_says_so_and_a_kept_clip_still_plays(episode, fake_miner, monkeypatch):
    ep = episode("ja")
    kept = _cut(ep, ep["lines"][0])
    monkeypatch.setattr(anki_miner, "find", lambda settings: None)
    with pytest.raises(clips.Refused) as e:
        clips.cut("ja", _id(ep["lines"][1]), settings=ep["settings"], steps=ep["steps"])
    assert e.value.message == clips.NO_MINER
    monkeypatch.setattr(anki_miner, "can_now", lambda asks: False)
    with pytest.raises(clips.Refused) as e:
        _cut(ep, ep["lines"][1])
    assert e.value.message == clips.OLD_MINER
    assert _cut(ep, ep["lines"][0]) == kept      # what was kept needs no Anki Miner
    assert len(_media_calls(fake_miner)) == 1


def test_anki_miner_cutting_no_clip_is_said_and_nothing_is_kept(episode, fake_miner):
    ep = episode("ja")
    fake_miner.plan(audio_seconds=0.5)          # every line past the audio's end: `media` answers no clip
    with pytest.raises(clips.Refused) as e:
        _cut(ep, ep["lines"][2])
    assert e.value.message.startswith("Anki Miner couldn't cut this line (")
    assert not os.listdir(clips.root())


# --------------------------------------------------------------------------- #
# Ahead of a press (the press measured 2.0–2.6 s: the open episode's shown lines cut while the page is idle)
# --------------------------------------------------------------------------- #
def _ahead_done(timeout=20):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        worker = clips._ahead["worker"]
        if worker is None or not worker.is_alive():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_ahead_cuts_the_shown_lines_not_kept_in_one_call_below_normal_and_a_press_then_plays_them(
        episode, fake_miner, monkeypatch, lang):
    from app.connect import power
    ep = episode(lang)
    below = []
    real = power.popen_below_normal
    monkeypatch.setattr(power, "popen_below_normal", lambda args, **kw: below.append(1) or real(args, **kw))
    kept = _cut(ep, ep["lines"][0])
    shown = [_id(c) for c in ep["lines"][:4]]
    assert clips.ahead(lang, shown + ["p0badc0de"], settings=ep["settings"], steps=ep["steps"],
                       miner=ep["miner"]) == 4
    assert _ahead_done()
    calls = _media_calls(fake_miner)
    assert len(calls) == 2 and len(calls[1]["media_lines"]) == 3       # one call, the kept line left out
    assert below == [1]                         # the ahead call only: a press runs at the learner's own priority
    for cue in ep["lines"][1:4]:
        path = _cut(ep, cue)                    # each press now plays what was kept: no further cut
        assert cue.text.replace("\n", "") in _said(path).replace("\n", "")
    assert len(_media_calls(fake_miner)) == 2 and _cut(ep, ep["lines"][0]) == kept
    assert sorted(n for n in os.listdir(clips.root()) if n.startswith(".")) == []


def test_ahead_takes_a_few_lines_never_more_and_nothing_with_connect_off_or_no_line(episode, fake_miner):
    ep = episode("ja")
    ids = [_id(c) for c in ep["lines"]]
    assert len(ids) > clips.AHEAD_MAX
    assert clips.ahead("ja", ids, settings=ep["settings"], steps=ep["steps"], miner=ep["miner"]) == clips.AHEAD_MAX
    assert _ahead_done()
    assert [len(c["media_lines"]) for c in _media_calls(fake_miner)] == [clips.AHEAD_MAX]
    assert clips.ahead("ja", ["p12345678", None, 7], settings=ep["settings"], steps=ep["steps"]) == 0
    assert clips.ahead("ja", "7:1000", settings=ep["settings"], steps=ep["steps"]) == 0    # never a string's letters
    clips.ahead("ja", ids[-2:], settings={"connect_enabled": False}, steps=ep["steps"], miner=ep["miner"])
    assert _ahead_done() and len(_media_calls(fake_miner)) == 1


def test_a_press_stops_the_cut_ahead_under_way_and_keeps_nothing_of_it(episode, monkeypatch):
    from app.connect import stopping
    ep = episode("zh")
    started, ended = threading.Event(), []

    def long_cut(miner, lang, profile, can, run_dir, timeout=None, troubles=None, on_poll=None, below=False):
        started.set()
        for _ in range(500):                    # Anki Miner's wait polls; its answer END ends the program
            if on_poll is not None and on_poll() is stopping.END:
                ended.append(1)
                raise stopping.Stopped()
            threading.Event().wait(0.01)
        return {}
    monkeypatch.setattr(add_audio, "cut", long_cut)
    clips.ahead("zh", [_id(c) for c in ep["lines"][:3]], settings=ep["settings"], steps=ep["steps"],
                miner=ep["miner"])
    assert started.wait(10)
    clips.stop_ahead()
    assert _ahead_done(5) and ended == [1]
    assert not os.listdir(clips.root())         # no clip, no run folder


def test_every_route_but_the_ahead_ask_stops_the_cut_ahead(monkeypatch):
    # a press of anything on the page (✓, ⊘, ⇄, ▶ …) is the learner busy: the cut ahead gives way at once
    from app.services import journey_door
    stopped = []
    monkeypatch.setattr(clips, "stop_ahead", lambda: stopped.append(1))

    class App:
        def closing(self):
            return False
    monkeypatch.setattr(journey_door, "resolve", lambda spec: lambda body, app: {"done": True})
    call = journey_door._route(("app.connect.door_routes", "anything"), App())
    call({"lang": "ja", "marks": []})
    assert stopped == [1]
    call({"lang": "ja", "line_ids": ["7:1000"], "ahead": True})
    assert stopped == [1]


# --------------------------------------------------------------------------- #
# The route: `clip/cut` on the door (journey v3 SPEC §3.3)
# --------------------------------------------------------------------------- #
@pytest.fixture
def route(episode, monkeypatch):
    """The door route with Connect's lookups as the case's (its Steps), the door's GET standing in."""
    from app import door, settings_manager
    from app.connect import runner
    ep = episode("ja")
    monkeypatch.setattr(settings_manager, "load_settings", lambda *a, **k: dict(ep["settings"]))
    monkeypatch.setattr(runner, "Steps", lambda settings: ep["steps"])
    monkeypatch.setattr(anki_miner, "find", lambda settings: ep["miner"])
    served = []
    monkeypatch.setattr(door, "serve_file", lambda path, kind: served.append((path, kind)) or
                        f"http://127.0.0.1:5123{door.CLIP_PATH}{len(served):032x}")
    return dict(ep, served=served)


def test_the_route_is_built_so_the_page_shows_the_play_button(monkeypatch):
    from app.services import journey_door
    assert journey_door.resolve(journey_door.ROUTES["clip/cut"]) is not None


def test_a_press_answers_the_doors_url_path_for_the_kept_clip(route):
    from app import door
    from app.connect import door_routes
    cue = route["lines"][2]
    got = door_routes.clip_route({"lang": "ja", "line_id": _id(cue)}, None)
    assert got["url"].startswith(door.CLIP_PATH) and "127.0.0.1" not in got["url"]    # the page adds its own port
    ((path, kind),) = route["served"]
    assert kind == "audio/mpeg" and cue.text in _said(path)


@pytest.mark.parametrize("body, said", [
    ({"lang": "en", "line_id": "7:1000"}, "Surasura couldn't read that."),
    ({"lang": "ja", "line_id": "7:" + "1" * 60}, clips.NO_LINE),
    ({"lang": "ja", "line_id": 71000}, clips.NO_LINE),
    ({"lang": "ja", "line_id": "7:999999"}, clips.GONE),
])
def test_a_press_refused_says_why_in_the_clips_words(route, body, said):
    from app import door
    from app.connect import door_routes
    with pytest.raises(door.RouteError) as e:
        door_routes.clip_route(body, None)
    assert str(e.value) == said and not route["served"]


def test_the_library_busy_is_busy_never_a_line_gone(route):
    from app import door
    from app.connect import door_routes, runner

    def busy(lang, job):
        raise runner.Wait(runner.LIBRARY_BUSY)
    route["steps"].subtitle = busy
    with pytest.raises(door.RouteError) as e:
        door_routes.clip_route({"lang": "ja", "line_id": _id(route["lines"][0])}, None)
    assert e.value.kind == "busy" and str(e.value) == door_routes.BUSY


def test_the_ahead_ask_answers_at_once_with_how_many_and_cuts_them(route, fake_miner):
    from app.connect import door_routes
    ids = [_id(c) for c in route["lines"][:3]] + ["x" * 99, 5]
    assert door_routes.clip_route({"lang": "ja", "line_ids": ids, "ahead": True}, None) == {"ahead": 3}
    assert _ahead_done() and [len(c["media_lines"]) for c in _media_calls(fake_miner)] == [3]
    assert not route["served"]                  # nothing served: no press asked for it
