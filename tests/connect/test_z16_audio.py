"""Connect mines audiobooks and podcasts through Anki Miner's audio episodes (round 2's Z-16, Anki Miner 3.11; Sonic
2026-11-02: "audiobook mining must work for this release"), behind the feature name — Michi-AB's Stage A (rules A1–A5,
PROVISIONAL: `tracks/pipeline/work/AB/plan.md`).

What a wrong answer would cost: these jobs write the learner's Anki unattended. An audio file sent to an Anki Miner
that can't mine audio is refused (or worse, its window opened); a card cut from the wrong file holds another line's
sound; an audiobook whose one transcript spans several files cut from its first file puts every later line's audio on
the wrong card; an audio item with nothing to cut from said as *No video* sends the learner looking for a video that
never existed; and without the feature any change at all moves a learner's video mining.

Real files: the suite's real Japanese text and subtitles, audiobooks built on disk the way Hon's suite builds them (M4Bs
and MP3s with real tags and lengths, transcripts of real sentences) in a real store; Anki Miner is the suite's fake
(`fake_anki_miner.py`, taught 3.11's `audio_file` episode), Anki is `FakeSteps`'.
"""
import json
import os

import pytest

from app.connect import anki_miner, fields, fit_check, library, runfile, runner, setup
from app.services import view_rows
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_anki_miner import LAPIS_EXPORT
from tests.connect.test_p41_asked import StoreSteps, _library, _place_top, _mined, _jobs, _run, _srt as _srt_items
from tests.test_audiobook_items import _audio_folder, _audio_items, _lines, _settle
from tests.test_audiobook_transcripts import _alone, _srt
from tests.test_sources_scan import _drive, _empty, _look

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
EPISODE = os.path.join(RESOURCES, "ja", "library_episode.ass")
WORDS = [("冒険", "ボウケン"), ("今夜", "コンヤ")]
STAR = "星屑の剣士になりたくて！"
AUDIO_311 = ["word-from-line", "dry-run", "reading", "audio-episodes"]


def _record(features):
    """Connect's setup record naming the Anki Miner it last found (its `version` answer's features)."""
    assert setup.write_record({"anki_miner": {"app": "3.11.0", "schema": 1, "features": list(features)}})


# --------------------------------------------------------------------------- #
# The run file: an audio episode
# --------------------------------------------------------------------------- #
def test_an_audio_run_file_names_the_audio_file_and_its_folder_as_the_cards_series(tmp_path):
    """`runfile.episode(audio=True)`: `audio_file` in place of `video_file` (absolute), the subtitle, offset, tags and
    words as a video's; the Source's series is the audio's own folder (`<folder> — <name>`, what a video's card says:
    Anki Miner's own `Audio` names no show). A video's episode keeps exactly its keys."""
    folder = tmp_path / "杜子春 (朗読)"
    folder.mkdir()
    audio = folder / "toshisyun_01.mp3"
    words = [{"word": "若者", "line_start": 20.84, "line_expansion": [0, 0]}]
    ep = runfile.episode("job-1-1", str(audio), EPISODE, words, tags="t", subtitle_offset=0.0, audio=True)
    assert ep["audio_file"] == os.path.abspath(audio) and "video_file" not in ep
    assert ep["series_name_override"] == "杜子春 (朗読)" and "episode_name_override" not in ep
    assert ep["subtitle_file"] == os.path.abspath(EPISODE) and ep["words"] == words
    video = runfile.episode("job-1-1", str(folder / "ep.mkv"), EPISODE, words, tags="t")
    assert set(video) == {"run_id", "video_file", "subtitle_file", "subtitle_offset", "tags", "words"}
    data = runfile.build(str(tmp_path / "run"), "ja", [ep])
    runfile.write(str(tmp_path / "run" / "run-1.json"), data)            # its check passes


@pytest.mark.parametrize("name, audio", [("a.mp3", True), ("a.M4B", True), ("a.opus", True), ("a.flac", True),
                                         ("a.mkv", False), ("a.mp4", False), ("a.srt", False), (None, False)])
def test_an_audio_file_is_told_by_anki_miners_own_list(name, audio):
    assert anki_miner.is_audio(name) is audio


# --------------------------------------------------------------------------- #
# The batch: only to an Anki Miner that mines audio
# --------------------------------------------------------------------------- #
@pytest.fixture
def audio_batch(tmp_path, fake_miner):
    """mine_batch for an audiobook's file: the fake never opens it (a real one does, with ffprobe)."""
    folder = tmp_path / "杜子春"
    folder.mkdir()
    audio = folder / "toshisyun_01.mp3"
    audio.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")
    words = [{"word": w, "reading": r, "orth": w, "sent": [w], "line_start": 10.0 + n, "line_end": 12.0 + n,
              "line_expansion": [0, 0], "line_text": f"{w}の台詞", "surface": w, "front_reading": r,
              "predicted_class": None} for n, (w, r) in enumerate(WORDS)]
    mapping = fields.from_export(LAPIS_EXPORT)

    def run(**kw):
        return anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(audio), EPISODE, words, mapping, "Surasura",
                                     str(tmp_path / "runs" / "job-1"), "http://127.0.0.1:9", **kw)
    return run, str(audio)


def test_an_audio_batch_goes_as_an_audio_episode_and_its_cards_come_back_made(audio_batch, fake_miner):
    run, audio = audio_batch
    fake_miner.plan(app="3.11.0", features=AUDIO_311)
    done = run()
    [episode] = json.load(open(done["run_file"], encoding="utf-8"))["episodes"]
    assert episode["audio_file"] == audio and "video_file" not in episode
    assert episode["series_name_override"] == "杜子春"
    assert [o["outcome"] for o in done["outcomes"]] == ["made", "made"]


def test_an_audio_file_is_never_sent_to_an_anki_miner_that_cant_mine_audio(audio_batch, fake_miner):
    """3.10.1 (or a 3.11 build without the name): refused before `mine` is called — nothing mined, never its window."""
    run, _audio = audio_batch
    fake_miner.plan(app="3.10.1", features=["word-from-line", "reading"])
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        run()
    assert e.value.kind == "no-audio" and "mine" not in fake_miner.commands()


def test_an_audio_file_anki_miner_cant_open_is_refused_before_anki_never_in_doubt(audio_batch, fake_miner):
    """`AUDIO_UNREADABLE` (3.11, before any Anki write): `unreadable` with Anki Miner's reason, never `uncertain` — the
    words are never looked for in Anki by tag nor mined twice."""
    run, _audio = audio_batch
    fake_miner.plan(app="3.11.0", features=AUDIO_311, mine="audio-unreadable")
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        run()
    assert (e.value.kind, e.value.code) == ("unreadable", "AUDIO_UNREADABLE")
    assert "AUDIO_UNREADABLE" in anki_miner.BEFORE_ANKI


def test_a_video_batch_is_byte_for_byte_as_before_with_the_audio_feature_named(tmp_path, fake_miner):
    """The feature changes nothing for a video: `video_file`, no series of Surasura's."""
    video = tmp_path / "Show" / "Show - 01.mkv"
    video.parent.mkdir()
    video.write_bytes(b"\x1aE\xdf\xa3")
    fake_miner.plan(app="3.11.0", features=AUDIO_311)
    words = [{"word": "冒険", "reading": "ボウケン", "orth": "冒険", "sent": ["冒険"], "line_start": 10.0,
              "line_end": 12.0, "line_expansion": [0, 0], "line_text": "冒険の台詞"}]
    done = anki_miner.mine_batch(fake_miner.path, "ja", "job-1", str(video), EPISODE, words,
                                 fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs" / "job-1"),
                                 "http://127.0.0.1:9")
    [episode] = json.load(open(done["run_file"], encoding="utf-8"))["episodes"]
    assert episode["video_file"] == str(video) and "audio_file" not in episode
    assert "series_name_override" not in episode


def test_the_step_sets_a_job_aside_as_audio_when_its_anki_miner_cant_mine_audio(tmp_path, monkeypatch):
    """`Steps.mine`: a `no-audio` refusal (another Anki Miner installed since the pick) is the audio wait, the setup
    record now naming the one installed — so the job set aside stays aside, never refused at every look."""
    from app.cli import verbs
    steps = runner.Steps({"connect_anki_miner_path": str(tmp_path / "AnkiMiner.exe")})
    (tmp_path / "AnkiMiner.exe").write_bytes(b"")
    steps.run_dir = lambda job: str(tmp_path / "runs")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda *a, **k: ({"features": AUDIO_311}, "p1", None))
    _record(AUDIO_311)
    assert anki_miner.mines_now("audio")

    def refuse(*a, **k):
        raise anki_miner.AnkiMinerError("no-audio", "This Anki Miner can't mine audio.",
                                        verdict={"app": "3.10.1", "schema": 1, "features": ["reading"]})
    monkeypatch.setattr(anki_miner, "mine_batch", refuse)
    picked = {"video": str(tmp_path / "a.mp3"), "subtitle": EPISODE, "profile": "p1"}
    with pytest.raises(runner.Skip) as e:
        steps.mine("ja", {"id": 1, "item_id": 7}, picked, [], 1)
    assert e.value.why == runner.AUDIO_WAIT
    assert not anki_miner.mines_now("audio")


# --------------------------------------------------------------------------- #
# The job: set aside until Anki Miner mines audio, then cut from its audio file
# --------------------------------------------------------------------------- #
class AudioSteps(StoreSteps):
    """The p41 harness with Z-16's step: `audio` as a test hands it ({item: (path, wait)}), and the fit check's file
    kept (`fitted`)."""

    def __init__(self, folder, plan=None, audio=None):
        super().__init__(folder, plan=plan)
        self.audio_of = dict(audio or {})
        self.fitted = []

    def audio(self, lang, job):
        return self.audio_of.get(job["item_id"], (None, None))

    def fit(self, lang, job, pairing, video, subtitle):
        self.fitted.append(video)
        return super().fit(lang, job, pairing, video, subtitle)


def _audio_title(kind="audiobook"):
    ids, kinds = _library()
    episode = _srt_items(ids, kinds)[-1]
    with c.store("ja") as s:
        s.set_media_type([s.item(episode)["work_id"]], kind)
    return episode


def test_an_audiobooks_episode_set_aside_for_audio_is_mined_from_its_audio_file_once_anki_miner_mines_audio(tmp_path):
    """A1/A4: an episode of a title you marked an audiobook, no video found, waits as audio (AUDIO_WAIT, nothing
    mined); once Anki Miner mines audio the same job is queued again and cut from its audio file — the timing checked
    on that file, mined as any episode."""
    episode = _audio_title()
    mp3 = str(tmp_path / "第一話.mp3")
    steps = AudioSteps(str(tmp_path), {"words": {str(episode): [WORDS[1]]}, "videos": {str(episode): None}},
                       audio={episode: (mp3, None)})
    _place_top(episode)
    _run(steps)
    assert (_jobs(episode)[-1]["state"], _jobs(episode)[-1]["reason"]) == ("skipped", runner.AUDIO_WAIT)
    assert _mined(steps) == [] and steps.fitted == []
    steps.can = {"books", "audio"}
    _run(steps)
    assert len(_jobs(episode)) == 1 and _jobs(episode)[-1]["state"] == "done", "the same job, mined"
    assert _mined(steps) == [episode] and steps.fitted == [mp3]


@pytest.mark.parametrize("wait", [runner.NO_AUDIO, runner.SEVERAL_FILES.format(n=3)])
def test_an_audio_episode_with_nothing_to_cut_from_waits_with_its_own_line_never_no_video(tmp_path, wait):
    """A1/A5: no audio file found (or one transcript over several files): the job waits with that line — never *No
    video*, never a *Needs you* card of the video's kind, nothing mined."""
    episode = _audio_title("podcast")
    steps = AudioSteps(str(tmp_path), {"words": {str(episode): [WORDS[1]]}, "videos": {str(episode): None}},
                       audio={episode: (None, wait)})
    steps.can = {"books", "audio"}
    _place_top(episode)
    out = _run(steps)["languages"]["ja"]
    job = _jobs(episode)[-1]
    assert (job["state"], job["reason"]) == ("waiting", wait) and not runner.no_video(job["reason"])
    assert out["needs"] == [] and _mined(steps) == []


def test_a_video_episode_never_asks_for_audio_and_is_mined_as_before(tmp_path):
    """A video found first: never an audio look-up, mined from the video exactly as before (the feature on or off)."""
    ids, kinds = _library()
    episode = _srt_items(ids, kinds)[-1]
    steps = AudioSteps(str(tmp_path), {"words": {str(episode): [WORDS[1]]}})
    steps.audio = lambda lang, job: pytest.fail("a video's episode never looks for audio")
    steps.can = {"books", "audio"}
    _place_top(episode)
    _run(steps)
    assert _mined(steps) == [episode] and steps.fitted[0].endswith(".mkv")


def test_without_the_feature_no_audio_is_ever_looked_for(tmp_path):
    """No `audio-episodes`: an episode with no video is *No video* as before; `Steps.audio` is never asked."""
    ids, kinds = _library()
    episode = _srt_items(ids, kinds)[-1]
    steps = AudioSteps(str(tmp_path), {"words": {str(episode): [WORDS[1]]}, "videos": {str(episode): None}})
    steps.audio = lambda lang, job: pytest.fail("no audio look-up without the feature")
    _place_top(episode)
    _run(steps)
    assert _jobs(episode)[-1]["reason"] == runner.NO_VIDEO


# --------------------------------------------------------------------------- #
# A1: what an audio episode is cut from (a real store, real files)
# --------------------------------------------------------------------------- #
def _steps_audio(item_id):
    return runner.Steps({}).audio("ja", {"item_id": item_id, "language": "ja"})


def test_an_audiobook_alone_read_by_its_transcript_is_cut_from_its_one_file():
    """Hon a6: an M4B alone with its transcript is one item counted as the transcript; its cards are cut from the M4B
    (the record's file), never from anything named like the copy."""
    store, _data_dir, src, m4b, _srt_path = _alone("ja", STAR)
    with store:
        _look(store, "ja", store.add_source(src))
        [item] = _audio_items(store)
        assert library.audiobook_file(store, item["id"]) == (os.path.abspath(m4b), 1)
    assert _steps_audio(item["id"]) == (os.path.abspath(m4b), None)


def test_an_audiobook_of_several_files_with_one_transcript_waits_never_cut_from_its_first_file():
    """A5: one transcript over three MP3s — its times can't be told apart by file: the item waits with its own line,
    never cut from the first file (where every later line's audio would be another line's)."""
    store, _data_dir = _empty("ja")
    src = _drive("driveA")
    folder = os.path.join(src, STAR)
    _audio_folder(folder, STAR, 3600, n=3)
    _srt(os.path.join(folder, f"{STAR}.srt"), _lines("ja")[:12])
    with store:
        _look(store, "ja", store.add_source(src))
        [item] = _audio_items(store)
        assert item["availability"] == "available"            # counted by its transcript (Hon a6)
        assert library.audiobook_file(store, item["id"]) == (None, 3)
    assert _steps_audio(item["id"]) == (None, runner.SEVERAL_FILES.format(n=3))


def test_an_audiobook_whose_one_file_is_gone_waits_for_its_audio():
    store, _data_dir, src, m4b, _srt_path = _alone("ja", STAR)
    with store:
        _look(store, "ja", store.add_source(src))
        [item] = _audio_items(store)
    os.remove(m4b)
    assert _steps_audio(item["id"]) == (None, runner.NO_AUDIO)


def test_a_subtitle_with_its_audio_file_beside_its_original_is_cut_from_that_file():
    """A subtitle for each audio file (`01.srt` beside `01.mp3`): the item's original's folder holds the audio of its
    own name — that file, as a video beside its subtitle is found (`beside_origin`, the audio extensions)."""
    store, _data_dir = _empty("ja")
    src = _drive("driveA")
    folder = os.path.join(src, "ポッドキャスト")
    os.makedirs(folder)
    files = []
    for n in (1, 2):
        mp3 = os.path.join(folder, f"第{n}回.mp3")
        with open(mp3, "wb") as f:
            f.write(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\0" * 2048)
        files += [mp3, _srt(os.path.join(folder, f"第{n}回.srt"), _lines("ja")[n * 4:n * 4 + 4])]
    _settle(*files)                         # a file written just now is one still arriving: the look waits for it
    with store:
        _look(store, "ja", store.add_source(src))
        rows = store.conn.execute("SELECT id, rel_path FROM items WHERE source_type = 'subtitle' ORDER BY rel_path")
        items = {rel.rsplit("/", 1)[-1]: i for i, rel in rows}
    assert set(items) >= {"第1回.srt", "第2回.srt"}
    for n in (1, 2):
        assert _steps_audio(items[f"第{n}回.srt"]) == (os.path.join(folder, f"第{n}回.mp3"), None)


def test_a_subtitle_with_no_audio_and_no_audio_title_is_left_to_its_video_wait():
    """Nothing beside it and its title not an audio one: (None, None) — the job's *No video* as before."""
    ids, kinds = _library()
    episode = _srt_items(ids, kinds)[-1]
    assert _steps_audio(episode) == (None, None)
    with c.store("ja") as s:
        s.set_media_type([s.item(episode)["work_id"]], "audiobook")
    assert _steps_audio(episode) == (None, runner.NO_AUDIO)


# --------------------------------------------------------------------------- #
# A3: the timing gate says audio for an audio file
# --------------------------------------------------------------------------- #
def test_the_timing_gate_on_an_audio_file_waits_for_your_word_and_says_audio(tmp_path):
    """tsubasa 0.1.11 has nothing inside an audio file to time against (its ERROR names no subtitle track, a raw
    video's): not timed — *Trust my subtitles' timing* or *Mine anyway* releases it, as a raw video — and the reason
    says audio, never video."""
    answer = {"outcome": "ERROR", "segments": [], "offset": None,
              "reason": "a.mp3 could not be measured: it has no subtitle track to align against."}

    def run(command, **kw):
        return type("Done", (), {"stdout": json.dumps(answer) + "\n1 ERROR · 0 would sync\n"})()
    audio = str(tmp_path / "a.mp3")
    verdict, who, why, _offset = fit_check.fit(None, audio, EPISODE, tsubasa="tsubasa", run=run)
    assert verdict == fit_check.NOT_TIMED and "audio" in why and "video" not in why
    assert fit_check.TRUST_LABEL in why
    assert fit_check.fit(None, audio, EPISODE, tsubasa="tsubasa", run=run, trust=True)[:2] == (fit_check.TIMED, "you")
    video_why = fit_check.fit(None, str(tmp_path / "a.mkv"), EPISODE, tsubasa="tsubasa", run=run)[2]
    assert "Not timed to its video" in video_why


# --------------------------------------------------------------------------- #
# The window: rows and *Mine*
# --------------------------------------------------------------------------- #
def test_mine_takes_an_audio_episode_only_once_anki_miner_mines_audio():
    from app.qt.mine_actions import videos_of
    ep = view_rows.Episode._make([None] * len(view_rows.Episode._fields))._replace(id=5, media_word="audio",
                                                                                  text="audio")
    row = type("Row", (), {"episodes": [ep], "media_word": "audio"})()
    _record(["word-from-line", "reading"])
    assert videos_of(row, [5]) == ([], ep)
    _record(AUDIO_311)
    assert videos_of(row, [5]) == ([5], None)


def test_an_audiobook_with_no_text_still_waits_and_its_hover_says_what_it_waits_on():
    """H-7's audiobook alone (no transcript, no book): nothing to mine whatever Anki Miner mines — the row stays the
    quiet *Waits for Anki Miner*, its hover no longer says Anki Miner can't mine audio."""
    from types import SimpleNamespace
    ep = SimpleNamespace(id=5, media_word="audio", text="audio", waiting=True, rel_path="Library/x (audio)/01.mp3",
                         cards=0, mined=False, missing=False, removed=False, in_top=True, mining=False, deleted=False)
    for features, tip in ((["reading"], "tip_audio_wait"), (AUDIO_311, "tip_heard_wait")):
        _record(features)
        st, _mark = view_rows.status_of([ep], "audio", 20)
        assert (st.kind, st.tip) == ("books", view_rows.STRINGS[tip])
