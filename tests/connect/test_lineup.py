"""A book lined up with its audiobook, and an audiobook's own subtitles spot-checked — Michi-AB's Stage B (Anki Miner
3.11's Z-17 `sync`, Z-22 `setup --speech-model`, Z-18 `transcribe`; Sonic's AB-Q1…Q5 and the one question when nothing
lines up, 2026-11-02 — all PROVISIONAL: `tracks/pipeline/work/AB/plan.md`).

What a wrong answer would cost: these jobs write the learner's Anki unattended, and the line-up runs for hours. A card
cut from a neighbour's cue holds another sentence's sound; a grade-C line-up used for cards puts wrong clips on every
card; a sync started twice, or never stopped at *Stop*, burns hours of the learner's CPU; a second model download
nobody asked for costs 0.5–2.3 GB; the speech model's question asked once per book floods *Needs you*; a *Separate
them* that can't be undone loses the learner's pairing; a spot-check that passes a subtitle that doesn't match mines
wrong clips, and one that fails a good one holds cards back for nothing.

Real data: the real line-up Anki Miner 3.11 made of LibriVox's 杜子春 (CC0) against its Aozora text (public domain) —
two files' first cues, `Test Resources/ja/audiobook_sync/` — and the suite's real Japanese sentences; a real EPUB and a
real folder of chapter MP3s paired by a real look into a real store (Hon's helpers); Anki Miner is the suite's fake
(`fake_anki_miner.py`, taught 3.11's `sync`, `setup --speech-model`, `media` of an audio file and `transcribe`), run as
a child process exactly as the real one is.
"""
import json
import os
import time

import pytest

from app.connect import actions, anki_miner, feed, fit_check, library, lineup, runner, setup
from app.connect.ledger import Ledger
from app.services import needs, view_rows
from tests.test_audiobook_items import _audio_folder, _audio_items, _epub, _fit, _lines, _record
from tests.test_sources_scan import _drive, _empty, _look

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
SYNCED = os.path.join(RESOURCES, "ja", "audiobook_sync")
NEKO = "吾輩は猫である"
LINE_UP_311 = ["word-from-line", "dry-run", "reading", "audio-episodes", "media", "sync", "transcribe",
               "setup-speech-ocr"]


@pytest.fixture(autouse=True)
def no_child_left(monkeypatch):
    """Each test starts with no line-up child of an earlier one, and ends with none running."""
    lineup._RUNNING.clear()
    anki_miner._SPEECH.clear()
    yield
    for proc, _out in list(lineup._RUNNING.values()):
        if proc.poll() is None:
            proc.kill()
            proc.wait(10)
    lineup._RUNNING.clear()
    anki_miner._SPEECH.clear()


def _record_miner(features=LINE_UP_311):
    assert setup.write_record({"anki_miner": {"app": "3.11.0", "schema": 1, "features": list(features)}})


def _until(done, seconds=30.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if done():
            return True
        time.sleep(0.05)
    raise AssertionError("it never ended")


def _srt_of(lines, start=1.0, each=4.0):
    """An SRT of `lines`, each `each` seconds after the last (the sync's shape: one book sentence a cue)."""
    out = []
    for n, line in enumerate(lines, 1):
        a, z = start + (n - 1) * (each + 0.5), start + (n - 1) * (each + 0.5) + each
        out.append(f"{n}\n{_t(a)} --> {_t(z)}\n{line}\n")
    return "\n".join(out)


def _t(s):
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _audio_files(tmp_path, n=2):
    folder = tmp_path / "杜子春 (朗読)"
    folder.mkdir(exist_ok=True)
    out = []
    for k in range(1, n + 1):
        p = folder / f"toshisyun_0{k}.mp3"
        p.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")
        out.append(str(p))
    return out


def _book(tmp_path):
    book = tmp_path / "杜子春.epub"
    book.write_bytes(b"PK\x03\x04")         # the fake reads no book; a real one's EPUB is its own
    return str(book)


def _synced_plan(names, grade="A", unheard=(), hold=0.0, statuses=None):
    files = {}
    for k, name in enumerate(names, 1):
        path = os.path.join(SYNCED, f"toshisyun_0{k}.srt")
        with open(path, encoding="utf-8") as f:
            files[name] = {"status": (statuses or {}).get(name, "synced"), "srt": f.read()}
    return {"files": files, "report": {"grade": grade, "sentence_pct": 93, "audio_pct": 94,
                                       "unheard": [{"first": a, "last": b} for a, b in unheard]}, "hold": hold}


# --------------------------------------------------------------------------- #
# The sync: a child of Connect's, file k of n, its outcome, Stop
# --------------------------------------------------------------------------- #
def test_a_sync_runs_beside_connect_says_which_file_and_ends_with_each_files_timed_subtitle(tmp_path, fake_miner):
    """`start_sync` never waits: the look after it reads *file k of n* from Anki Miner's progress; once the child has
    ended, the line-up holds each audio file's SRT (Anki Miner's own, in Connect's folder — never the learner's or the
    library's) and the report, and it is fit to cut cards from (grade A)."""
    audio = _audio_files(tmp_path)
    fake_miner.plan(sync=_synced_plan([os.path.basename(a) for a in audio], hold=1.5))
    began = time.monotonic()
    state = lineup.start_sync(fake_miner.path, "ja", "p-surasura", "pair-1", _book(tmp_path), audio)
    assert time.monotonic() - began < 1.0, "the sync is a child: the look never waits for it"
    assert state["status"] == lineup.RUNNING and lineup.file_line(state) == (1, 2)
    _until(lambda: os.path.exists(os.path.join(lineup.folder("pair-1"), "run", "sync", "progress.json")))
    assert lineup.look("pair-1")["status"] == lineup.RUNNING
    _until(lambda: not lineup.running("pair-1"))
    done = lineup.look("pair-1")
    assert done["status"] == lineup.DONE and done["grade"] == "A" and lineup.usable(done)
    assert [f["audio_file"] for f in done["files"]] == audio
    for f in done["files"]:
        assert f["subtitle_file"].startswith(lineup.folder("pair-1")) and os.path.isfile(f["subtitle_file"])
    job = json.load(open(os.path.join(lineup.folder("pair-1"), "sync.json"), encoding="utf-8"))
    assert job["profile"] == "p-surasura" and job["episodes"][0]["audio"] == audio
    assert lineup.read("pair-1") == done, "what the look found is written once, read back the same"


def test_stop_cancels_the_sync_at_its_next_step_and_the_stop_is_kept(tmp_path, fake_miner):
    """*Stop* (AB-Q3): the run's `cancel` file, Anki Miner's CANCELLED read back as STOPPED with when — never a failure
    counted, never started again by itself."""
    audio = _audio_files(tmp_path)
    fake_miner.plan(sync=_synced_plan([os.path.basename(a) for a in audio], hold=20.0))
    lineup.start_sync(fake_miner.path, "ja", None, "pair-2", _book(tmp_path), audio)
    assert lineup.stop("pair-2") is True
    _until(lambda: not lineup.running("pair-2"), 15)
    state = lineup.look("pair-2")
    assert state["status"] == lineup.STOPPED and state["stopped_at"] and not state.get("tries")
    assert lineup.stop("never-started") is False


def test_nothing_lined_up_is_none_and_a_poor_grade_is_never_used_for_cards(tmp_path, fake_miner):
    """No file synced and no grade (another book): NONE, the one question's case. Grade C: lined up but never used to
    cut cards (AB-Q4: never a wrong clip) — its plain line says why; A with skipped passages: used, its line names them."""
    audio = _audio_files(tmp_path)
    names = [os.path.basename(a) for a in audio]
    fake_miner.plan(sync={"files": {n: {"status": "no_match", "srt": ""} for n in names},
                          "report": {"grade": None, "sentence_pct": None, "audio_pct": None}})
    lineup.start_sync(fake_miner.path, "ja", None, "pair-3", _book(tmp_path), audio)
    _until(lambda: not lineup.running("pair-3"))
    assert lineup.look("pair-3")["status"] == lineup.NONE
    fake_miner.plan(sync=_synced_plan(names, grade="C"))
    lineup.start_sync(fake_miner.path, "ja", None, "pair-4", _book(tmp_path), audio)
    _until(lambda: not lineup.running("pair-4"))
    poor = lineup.look("pair-4")
    assert poor["status"] == lineup.DONE and not lineup.usable(poor)
    assert "grade C" in lineup.partial_line(poor, "杜子春") and "without sentence audio" in lineup.partial_line(poor, "杜子春")
    assert lineup.split([{"word": "大金持", "reading": "オオガネモチ", "surface": "大金持",
                          "line_text": "杜子春は一日の内に、洛陽の都でも唯一人といふ大金持になりました。"}], poor) == \
        ({}, [{"word": "大金持", "reading": "オオガネモチ", "surface": "大金持",
               "line_text": "杜子春は一日の内に、洛陽の都でも唯一人といふ大金持になりました。"}])
    fake_miner.plan(sync=_synced_plan(names, unheard=[(40, 42), (90, 90)]))
    lineup.start_sync(fake_miner.path, "ja", None, "pair-5", _book(tmp_path), audio)
    _until(lambda: not lineup.running("pair-5"))
    skipped = lineup.look("pair-5")
    assert lineup.usable(skipped) and "skips 2 passages" in lineup.partial_line(skipped, "杜子春")
    assert lineup.partial_line(dict(skipped, unheard=[]), "杜子春") is None


def test_a_sync_refused_for_its_setup_is_no_model_asked_again_and_a_try_counted(tmp_path, fake_miner):
    """`sync`'s SETUP_ERROR (no speech model - or no ffmpeg, which `check`'s item doesn't see): NO_MODEL, the model asked
    about again, and a try counted, so it never starts a sync at every look for ever (review B-12)."""
    audio = _audio_files(tmp_path)
    fake_miner.plan(sync={"error": "SETUP_ERROR"})
    anki_miner._SPEECH[("x", "ja", None)] = (True, time.monotonic())
    lineup.start_sync(fake_miner.path, "ja", None, "pair-6", _book(tmp_path), audio)
    _until(lambda: not lineup.running("pair-6"))
    state = lineup.look("pair-6")
    assert state["status"] == lineup.NO_MODEL and state["tries"] == 1 and state["failed_at"]
    assert anki_miner._SPEECH == {}, "the model is asked about again, never assumed"


def test_a_sync_that_died_counts_a_try_and_one_whose_connect_ended_is_interrupted(tmp_path, fake_miner):
    """A child killed (no verdict): FAILED, one try counted (TRIES running gives the book up to no audio, its line). A
    RUNNING line-up no child of this Connect holds (the Connect that started it ended, and its child with it):
    INTERRUPTED, so the next look starts it again — Anki Miner goes on from the files it finished."""
    audio = _audio_files(tmp_path)
    fake_miner.plan(sync=_synced_plan([os.path.basename(a) for a in audio], hold=30.0))
    lineup.start_sync(fake_miner.path, "ja", None, "pair-7", _book(tmp_path), audio)
    proc, _out = lineup._RUNNING["pair-7"]
    proc.kill()
    proc.wait(10)
    state = lineup.look("pair-7")
    assert state["status"] == lineup.FAILED and state["tries"] == 1
    lineup.write("pair-8", {"status": lineup.RUNNING, "file": 2, "of": 6})
    assert lineup.look("pair-8")["status"] == lineup.INTERRUPTED
    assert lineup.read("pair-8")["status"] == lineup.RUNNING, "a look writes nothing it didn't find (S19)"


# --------------------------------------------------------------------------- #
# What each card is cut from
# --------------------------------------------------------------------------- #
def _state_of_resources(tmp_path, grade="A"):
    audio = _audio_files(tmp_path)
    return {"status": lineup.DONE, "grade": grade,
            "files": [{"audio_file": a, "subtitle_file": os.path.join(SYNCED, f"toshisyun_0{k}.srt"),
                       "status": "synced"} for k, a in enumerate(audio, 1)]}, audio


def test_a_word_is_cut_from_the_cue_holding_its_sentence_in_its_own_file(tmp_path):
    """Each word's sentence is a cue of the real line-up: its audio episode is that file's, `line_start` that cue's
    start — chapter 2's sentence from chapter 2's file, never chapter 1's. Spelling and punctuation as the book's text
    has them, or with spaces, full-width letters and quotes added, find the same cue."""
    state, audio = _state_of_resources(tmp_path)
    words = [
        {"word": "若者", "reading": "ワカモノ", "surface": "若者",
         "line_text": "唐の都洛陽の西の門の下に、ぼんやり空を仰いでゐる、一人の若者がありました。"},
        {"word": "贅沢", "reading": "ゼイタク", "surface": "贅沢",
         "line_text": "大金持になつた杜子春は、すぐに立派な家を買つて、 玄宗皇帝にも負けない位、贅沢な暮しをし始めました。"},
        {"word": "夕日", "reading": "ユウヒ", "surface": "夕日",
         "line_text": "「門一ぱいに当つてゐる、油のやうな夕日の光の中に、老人のかぶつた紗の帽子や、土耳古の女の金の耳環や、"
                      "白馬に飾つた色糸の手綱が、絶えず流れて行く容子は、まるで画のやうな美しさです。」"},
    ]
    groups, rest = lineup.split(words, state)
    assert rest == []
    first, second = (audio[0], os.path.join(SYNCED, "toshisyun_01.srt")), (audio[1], os.path.join(SYNCED,
                                                                                                   "toshisyun_02.srt"))
    assert [(w["word"], w["line_start"], w["line_expansion"]) for w in groups[first]] == \
        [("若者", 20.84, [0, 0]), ("夕日", 50.56, [0, 0])]
    assert [(w["word"], w["line_start"]) for w in groups[second]] == [("贅沢", 23.92)]


def test_a_sentence_not_heard_or_a_cue_without_the_word_is_the_books_card_never_a_neighbours_clip(tmp_path):
    """Never a wrong clip: a sentence no cue holds (the narrator skipped it, another edition) goes as the book; a long
    sentence holding two cues is cut from the one holding the word, and from neither when neither holds it; a short
    line is only ever its own cue — never found inside a longer one (`はい` is in many sentences)."""
    state, audio = _state_of_resources(tmp_path)
    two_cues = ("杜子春は一日の内に、洛陽の都でも唯一人といふ大金持になりました。あの老人の言葉通り、夕日に影を映して見て、"
                "その頭に当る所を、夜中にそつと掘つて見たら、大きな車にも余る位、黄金が一山出て来たのです。")
    words = [
        {"word": "吾輩", "reading": "ワガハイ", "surface": "吾輩", "line_text": "吾輩は猫である。名前はまだ無い。"},
        {"word": "黄金", "reading": "オウゴン", "surface": "黄金", "line_text": two_cues},
        {"word": "猫", "reading": "ネコ", "surface": "猫", "line_text": two_cues},
        {"word": "日暮", "reading": "ヒグレ", "surface": "日暮", "line_text": "日暮です"},
    ]
    groups, rest = lineup.split(words, state)
    placed = {w["word"]: w["line_start"] for ws in groups.values() for w in ws}
    assert placed == {"黄金": 12.28}
    assert [w["word"] for w in rest] == ["吾輩", "猫", "日暮"]
    assert lineup.place("或春の日暮です。", "日暮", lineup.cues(state)).start == 17.882, "a short line, its own cue"


def test_a_file_anki_miner_couldnt_match_gives_no_cue_and_an_srt_that_cant_be_read_gives_none(tmp_path):
    state, audio = _state_of_resources(tmp_path)
    state["files"][0]["status"] = "no_match"
    state["files"][1]["subtitle_file"] = str(tmp_path / "gone.srt")
    assert lineup.cues(state) == []
    assert lineup.split([{"word": "若者", "reading": "ワカモノ", "surface": "若者",
                          "line_text": "唐の都洛陽の西の門の下に、ぼんやり空を仰いでゐる、一人の若者がありました。"}], state)[0] == {}


# --------------------------------------------------------------------------- #
# The speech model: one it has is used; else the one question; installed by Anki Miner's own setup
# --------------------------------------------------------------------------- #
def test_a_model_anki_miner_already_has_is_used_and_never_downloaded_again(tmp_path, fake_miner):
    """AB-Q2 (a): the profile's own model installed → ready, nothing else asked of Anki Miner; the profile naming
    large-v3 while small is installed → set to small (Surasura's own profile) and ready — never a second download."""
    fake_miner.plan(speech={"installed": ["large-v3"], "model": "large-v3"})
    assert anki_miner.speech_ready(fake_miner.path, "ja", "p-surasura", str(tmp_path)) is True
    assert "settings-import" not in fake_miner.commands() and "setup" not in fake_miner.commands()
    anki_miner._SPEECH.clear()
    assert not os.path.exists(os.path.join(os.environ["ANKI_MINER_HOME"], "fake-models.json")), "nothing written"
    fake_miner.plan(speech={"installed": ["small"], "model": "large-v3"})
    assert anki_miner.speech_ready(fake_miner.path, "ja", "p-surasura", str(tmp_path)) is True
    assert "setup" not in fake_miner.commands()
    calls = fake_miner.commands()
    assert calls.count("settings-import") == 1 and calls[-1] == "check"


def test_no_model_anywhere_is_not_ready_and_the_windows_own_profile_is_never_changed(tmp_path, fake_miner):
    fake_miner.plan(speech={"installed": [], "model": "large-v3"})
    assert anki_miner.speech_ready(fake_miner.path, "ja", "p-surasura", str(tmp_path)) is False
    assert fake_miner.commands().count("settings-import") == len(anki_miner.SPEECH_MODELS)
    before = len(fake_miner.commands())
    assert anki_miner.speech_ready(fake_miner.path, "ja", "p-surasura", str(tmp_path)) is False
    assert len(fake_miner.commands()) == before, "a no is kept a while: never five launches a look (B-11)"
    anki_miner._SPEECH.clear()
    before = len(fake_miner.commands())
    fake_miner.plan(speech={"installed": ["small"], "model": "large-v3"}, active_profile="default")
    assert anki_miner.speech_ready(fake_miner.path, "ja", "default", str(tmp_path)) is False
    assert fake_miner.commands()[before:].count("settings-import") == 1, "refused once, then left as it is"


def test_the_model_is_installed_only_through_anki_miners_own_setup_small_by_default(tmp_path, fake_miner):
    """AB-Q1/Q2 (b): `setup --speech-model --model small` for the profile Connect mines with, its progress file in
    *Finish its setup*'s folder (a mine told BUSY meanwhile names Anki Miner's setup), started and left running."""
    fake_miner.plan(speech={"installed": [], "model": "large-v3"}, speech_setup="installed")
    lineup.start_speech(fake_miner.path, "ja", "p-surasura")
    _until(lambda: not lineup.running(lineup.SPEECH))
    assert lineup.look(lineup.SPEECH)["status"] == lineup.DONE
    [argv] = [c["argv"] for c in fake_miner.calls() if c.get("argv", [None, None])[1] == "setup"]
    assert argv[argv.index("--model") + 1] == "small" and "--speech-model" in argv
    assert argv[argv.index("--profile") + 1] == "p-surasura"
    assert os.path.basename(os.path.dirname(argv[argv.index("--progress") + 1])) == anki_miner.SETUP_STAGING
    assert anki_miner.speech_ready(fake_miner.path, "ja", "p-surasura", str(tmp_path)) is True


def test_a_download_that_failed_is_failed_and_one_refused_while_its_window_is_open_is_no_failure(tmp_path, fake_miner):
    """A failed download: FAILED with Anki Miner's reason (the question asked again by `Steps.speech`). BUSY (its window
    open): no failure - started again once it can (review B-5)."""
    fake_miner.plan(speech={"installed": []}, speech_setup="failed")
    lineup.start_speech(fake_miner.path, "ja", "p-surasura")
    _until(lambda: not lineup.running(lineup.SPEECH))
    state = lineup.look(lineup.SPEECH)
    assert state["status"] == lineup.FAILED and state["message"] == "the download failed"
    fake_miner.plan(speech={"installed": []}, speech_setup="busy")
    lineup.start_speech(fake_miner.path, "ja", "p-surasura")
    _until(lambda: not lineup.running(lineup.SPEECH))
    state = lineup.look(lineup.SPEECH)
    assert state["status"] == lineup.INTERRUPTED and state["busy"] is True


def test_setup_verdicts_name_the_models_outcome(tmp_path):
    ok = {"ok": True, "result": {"speech_model": {"name": "small", "status": "already_installed"}}}
    assert anki_miner.speech_setup_done(ok) is None
    failed = {"ok": False, "error": None, "result": {"speech_model": {"status": "failed", "message": "no network"}}}
    assert anki_miner.speech_setup_done(failed) == "no network"
    assert anki_miner.speech_setup_done({"ok": False, "error": "BUSY", "message": "its window is open"}) == \
        "its window is open"
    assert anki_miner.speech_setup_args("ja", None, "p.json") == ["setup", "--language", "ja", "--progress", "p.json",
                                                                  "--speech-model", "--model", "small"]


# --------------------------------------------------------------------------- #
# The spot-check (AB-Q5)
# --------------------------------------------------------------------------- #
def _book_lines():
    """The real line-up's 14 sentences of 杜子春 (every one long enough to be heard as a sample)."""
    return [t for k in (1, 2) for _s, _e, t in lineup.srt_cues(os.path.join(SYNCED, f"toshisyun_0{k}.srt"))]


def _subtitle(tmp_path, lines):
    path = tmp_path / "toshisyun_01.srt"
    path.write_text(_srt_of(lines, each=9.0), encoding="utf-8")
    audio = tmp_path / "toshisyun_01.mp3"
    audio.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00")
    return str(audio), str(path)


def test_a_subtitle_that_plays_in_time_passes_the_spot_check_and_the_verdict_is_kept(tmp_path, fake_miner):
    """SAMPLES places of the subtitle, one line each, cut from the audio and heard: each holds its line → matched; its
    run folder removed after; asked again for the same subtitle and audio file, the kept verdict answers (no second
    listen); the subtitle changed → checked again."""
    audio, sub = _subtitle(tmp_path, _book_lines())
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    assert lineup.spot_check(fake_miner.path, "ja", None, audio, sub) == lineup.MATCHED
    assert fake_miner.commands().count("media") == 1 and fake_miner.commands().count("transcribe") == 1
    [asked] = [c for c in fake_miner.calls() if "media_lines" in c]
    assert len(asked["media_lines"]) == lineup.SAMPLES and asked["audio_file"] == audio
    assert all(line["line_expansion"] == [0, 0] for line in asked["media_lines"]), "one line a place (review B-13)"
    assert [n for n in os.listdir(lineup.root()) if n.startswith("spot-")] == [], "its clips deleted (B-22)"
    assert lineup.spot_check(fake_miner.path, "ja", None, audio, sub) == lineup.MATCHED
    assert fake_miner.commands().count("media") == 1, "kept: never heard twice"
    with open(sub, "a", encoding="utf-8") as f:
        f.write("\n")
    lineup.spot_check(fake_miner.path, "ja", None, audio, sub)
    assert fake_miner.commands().count("media") == 2


def test_a_subtitle_that_doesnt_match_its_audio_fails_and_one_match_in_three_is_not_enough(tmp_path, fake_miner):
    """Heard words that aren't its lines (another episode's subtitle, or one off by a line or more: each clip holds its
    neighbour's words) → not matched — the job is *Not timed* (never a wrong clip); two places of five matching is not
    enough (MATCHES), three is; nothing heard at all fails too."""
    lines = _book_lines()
    audio, sub = _subtitle(tmp_path, lines)
    other = "".join(_lines("ja")[:3])
    places = lineup.samples(lineup.srt_cues(sub))
    assert len(places) == lineup.SAMPLES
    fake_miner.plan(speech={"installed": ["small"], "model": "small"},
                    heard={p[2][:6]: other for p in places[:3]})
    assert lineup.spot_check(fake_miner.path, "ja", None, audio, sub) == lineup.NOT_MATCHED
    kept = json.load(open(os.path.join(lineup.root(), lineup.SPOT), encoding="utf-8"))
    [verdict] = kept.values()
    assert sum(1 for s in verdict["shares"] if s >= lineup.MATCH) == 2
    with open(sub, "a", encoding="utf-8") as f:
        f.write("\n")
    fake_miner.plan(speech={"installed": ["small"], "model": "small"},
                    heard={p[2][:6]: other for p in places[:2]})
    assert lineup.spot_check(fake_miner.path, "ja", None, audio, sub) == lineup.MATCHED
    (tmp_path / "other").mkdir()
    audio2, sub2 = _subtitle(tmp_path / "other", lines[:12])
    fake_miner.plan(speech={"installed": ["small"], "model": "small"}, deaf=True)
    assert lineup.spot_check(fake_miner.path, "ja", None, audio2, sub2) == lineup.NOT_MATCHED


def test_a_spot_check_without_the_speech_model_is_anki_miners_setup_refusal(tmp_path, fake_miner):
    audio, sub = _subtitle(tmp_path, _book_lines())
    fake_miner.plan(speech={"installed": [], "model": "small"})
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        lineup.spot_check(fake_miner.path, "ja", None, audio, sub)
    assert e.value.kind == "setup"
    assert lineup.spot_kept(lineup.spot_key(audio, sub)) is None, "no verdict kept for a check never made"


def test_samples_are_one_line_each_spread_through_the_subtitle_and_never_a_short_line():
    cues = [(10.0 * n, 10.0 * n + 9.0, "はい" if n % 2 else f"今日は雨が降っています{n}") for n in range(60)]
    places = lineup.samples(cues)
    assert [round(p[0]) for p in places] == [100, 200, 300, 400, 500] and all(p[1] == 0 for p in places)
    assert all(len(lineup.clean(p[2])) >= lineup.SAMPLE_CHARS for p in places)
    assert lineup.samples([]) == [] and lineup.samples([(0.0, 1.0, "はい")]) == []
    assert len(lineup.samples(cues[:3])) == 2


def test_the_fit_check_mines_a_matched_audio_subtitle_at_its_own_times_and_holds_one_that_doesnt(tmp_path):
    """`fit_check.fit`'s audio branch (one function): matched → TIMED by the spot-check, no shift; not matched →
    NOT_TIMED with its plain reason (*Mine anyway* stays yours); the speech model's question passed on; no answer →
    the rules after it, as before. A video never reaches it."""
    audio, sub = str(tmp_path / "a.mp3"), str(tmp_path / "a.srt")
    assert fit_check.fit(None, audio, sub, tsubasa="", spot=lambda: lineup.MATCHED) == \
        (fit_check.TIMED, "spot-check", None, 0.0)
    assert fit_check.fit(None, audio, sub, tsubasa="", spot=lambda: lineup.NOT_MATCHED) == \
        (fit_check.NOT_TIMED, "spot-check", fit_check.SPOT_NO_MATCH, 0.0)
    ask = (fit_check.NOT_TIMED, runner.SPEECH_NEED, runner.SPEECH_ASK, 0.0)
    assert fit_check.fit(None, audio, sub, tsubasa="", spot=lambda: ask) == ask
    assert fit_check.fit(None, audio, sub, tsubasa="", spot=lambda: None) == \
        (fit_check.NOT_TIMED, None, fit_check.NO_CHECKER, 0.0)
    asked = []
    fit_check.fit(None, str(tmp_path / "a.mkv"), sub, tsubasa="", spot=lambda: asked.append(1))
    assert asked == []


def test_trust_my_subtitles_timing_is_asked_before_any_listening(tmp_path, monkeypatch):
    _record_miner()
    steps = runner.Steps({"connect_anki_miner_path": "x"})
    monkeypatch.setattr(steps, "_settings", lambda lang: {"connect_trust_timing": True})
    monkeypatch.setattr(steps, "_spot", lambda *a: pytest.fail("trusted: never listened to"))
    assert steps.fit("ja", {"item_id": 1}, None, str(tmp_path / "a.mp3"), str(tmp_path / "a.srt"))[:2] == \
        (fit_check.TIMED, "you")
    monkeypatch.setattr(steps, "_settings", lambda lang: {})
    monkeypatch.setattr(steps, "_spot", lambda *a: lineup.MATCHED)
    assert steps.fit("ja", {"item_id": 1}, None, str(tmp_path / "a.mp3"), str(tmp_path / "a.srt"))[:2] == \
        (fit_check.TIMED, "spot-check")
    _record_miner(["audio-episodes"])                   # an Anki Miner that can't listen: as Stage A
    monkeypatch.setattr(steps, "_spot", lambda *a: pytest.fail("this Anki Miner can't listen"))
    assert steps.fit("ja", {"item_id": 1}, None, str(tmp_path / "a.mp3"), str(tmp_path / "a.srt"))[0] == \
        fit_check.NOT_TIMED


# --------------------------------------------------------------------------- #
# A paired book in a real store: lined up, then its words as audio episodes
# --------------------------------------------------------------------------- #
@pytest.fixture
def paired(tmp_path, fake_miner, monkeypatch):
    """A real EPUB and its three chapter MP3s side by side, paired by a real look (sure); Connect's Steps over that
    store, Anki Miner the fake (its profile `p-surasura`), plugged in."""
    store, _data_dir = _empty("ja")
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", f"{NEKO}.epub"), NEKO, "ja")
    files = _audio_folder(os.path.join(src, "Books", NEKO), NEKO, _fit("ja"))
    with store:
        _look(store, "ja", store.add_source(src))
        [item] = _audio_items(store)
        rec = _record(store, item["id"])
    assert rec["book"]["epub"] == os.path.abspath(book)
    _record_miner()
    steps = runner.Steps({"connect_anki_miner_path": fake_miner.path})
    monkeypatch.setattr(steps, "_miner_profile", lambda lang, job: (fake_miner.path, "p-surasura"))
    monkeypatch.setattr(steps, "on_battery", lambda: False)
    lines = _lines("ja")
    srts = {os.path.basename(f): {"status": "synced", "srt": _srt_of(lines[k * 6:(k + 1) * 6])}
            for k, f in enumerate(files)}
    return {"steps": steps, "book": os.path.abspath(book), "files": files, "item": item["id"], "key": rec["book"]["key"],
            "srts": srts, "lines": lines}


def _job(asked_at=None):
    return {"id": 1, "item_id": 999, "language": "ja", "asked_at": asked_at}


def test_a_paired_book_waits_lining_up_then_its_words_are_cut_from_its_audiobook(paired, fake_miner):
    """AB-Q3: the book's part waits *Lining up its audiobook… file 1 of 3* (a child runs; the part never waits in the
    look), *file k of n* while it runs, and once lined up the part's line-up names each file's SRT — whose cues the
    words are cut from; the store's mark untouched (nothing to ask). The sync was asked once, never twice."""
    fake_miner.plan(speech={"installed": ["small"], "model": "small"}, sync={"files": paired["srts"], "report": {
        "grade": "A", "sentence_pct": 95, "audio_pct": 92, "unheard": []}, "hold": 1.0})
    steps = paired["steps"]
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(), paired["book"])
    assert w.value.reason == runner.LINING_UP_FILE.format(k=1, n=3) and w.value.look is True
    assert runner.lining_up(w.value.reason)
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(), paired["book"])
    assert runner.lining_up(w.value.reason)
    _until(lambda: not lineup.running(paired["key"]))
    got = steps.line_up("ja", _job(), paired["book"])
    assert got["lineup"]["grade"] == "A" and [f["audio_file"] for f in got["lineup"]["files"]] == \
        [os.path.abspath(f) for f in paired["files"]]
    assert got["line"] is None and got["item_id"] == paired["item"]
    assert fake_miner.commands().count("sync") == 1
    word = {"word": "x", "reading": "x", "surface": paired["lines"][7][:2], "line_text": paired["lines"][7]}
    groups, rest = lineup.split([word], got["lineup"])
    assert not rest and list(groups)[0][0] == os.path.abspath(paired["files"][1])


def test_without_a_speech_model_the_book_asks_once_and_your_yes_downloads_it_then_lines_up(paired, fake_miner, tmp_path):
    """AB-Q2: no model anywhere → the one question (never a download nobody asked for); *Not now* → mined as the book;
    *Download it* → Anki Miner's own setup, the part waiting *downloading Anki Miner's speech model first*, then the
    sync starts by itself."""
    fake_miner.plan(speech={"installed": [], "model": "large-v3"}, speech_setup="installed",
                    sync={"files": paired["srts"], "report": {"grade": "A", "unheard": []}})
    steps = paired["steps"]
    assert steps.line_up("ja", _job(), paired["book"]) == {"ask": runner.SPEECH_ASK}
    assert "setup" not in fake_miner.commands()
    lineup.set_answer(False)
    assert steps.line_up("ja", _job(), paired["book"]) is None
    lineup.set_answer(True)
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(), paired["book"])
    assert w.value.reason == runner.LINING_UP_MODEL
    _until(lambda: not lineup.running(lineup.SPEECH))
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(), paired["book"])
    assert w.value.reason.startswith(runner.LINING_UP_FILE.format(k=1, n=3)[:20])
    assert fake_miner.commands().count("setup") == 1


def test_a_download_that_failed_asks_again_with_its_reason(paired, fake_miner):
    fake_miner.plan(speech={"installed": []}, speech_setup="failed")
    lineup.set_answer(True)
    steps = paired["steps"]
    with pytest.raises(runner.Wait):
        steps.line_up("ja", _job(), paired["book"])
    _until(lambda: not lineup.running(lineup.SPEECH))
    got = steps.line_up("ja", _job(), paired["book"])
    assert got == {"ask": runner.SPEECH_FAILED.format(why="the download failed")}
    assert lineup.answer() is None, "asked again: never a second download by itself"
    assert steps.line_up("ja", _job(), paired["book"]) == got, "the reason kept for every part until answered (B-6)"
    assert fake_miner.commands().count("setup") == 1


def test_on_battery_a_line_up_waits_for_the_plug_unless_you_asked(paired, fake_miner, monkeypatch):
    fake_miner.plan(speech={"installed": ["small"], "model": "small"}, sync={"files": paired["srts"], "hold": 0.5})
    steps = paired["steps"]
    monkeypatch.setattr(steps, "on_battery", lambda: True)
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(), paired["book"])
    assert w.value.reason == runner.LINING_UP_BATTERY and "sync" not in fake_miner.commands()
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(asked_at="2026-11-02T10:00:00Z"), paired["book"])
    assert w.value.reason == runner.LINING_UP_FILE.format(k=1, n=3)


def test_stop_stops_the_sync_and_the_book_waits_for_your_next_mine_now(paired, fake_miner):
    """AB-Q3's *Stop*: the sync's cancel file; every part of the book then waits (parked) until a *Mine now* newer
    than the stop, which starts it again."""
    fake_miner.plan(speech={"installed": ["small"], "model": "small"}, sync={"files": paired["srts"], "hold": 20.0,
                                                                             "report": {"grade": "A"}})
    steps = paired["steps"]
    with pytest.raises(runner.Wait):
        steps.line_up("ja", _job(), paired["book"])
    state = lineup.read(paired["key"])
    assert lineup.stop(paired["key"]) is True
    _until(lambda: not lineup.running(paired["key"]), 15)
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(asked_at="2026-01-01T00:00:00Z"), paired["book"])
    assert w.value.reason == runner.LINING_UP_STOPPED and w.value.look is False
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(asked_at="2999-01-01T00:00:00Z"), paired["book"])
    assert runner.lining_up(w.value.reason)
    _until(lambda: fake_miner.commands().count("sync") == 2)            # started again (its child logs as it starts)
    assert state["status"] == lineup.RUNNING


def test_nothing_lined_up_marks_the_pair_once_and_asks_the_one_question(paired, fake_miner):
    """No file synced: the book is mined as it is (no audio) and the store's mark asks ONE question per pair —
    *This audiobook doesn't match 「…」*, *Keep them together* · *Separate them*; marked once (S19)."""
    names = [os.path.basename(f) for f in paired["files"]]
    fake_miner.plan(speech={"installed": ["small"], "model": "small"},
                    sync={"files": {n: {"status": "no_match", "srt": ""} for n in names}, "report": {}})
    steps = paired["steps"]
    with pytest.raises(runner.Wait):
        steps.line_up("ja", _job(), paired["book"])
    _until(lambda: not lineup.running(paired["key"]))
    assert steps.line_up("ja", _job(), paired["book"]) is None
    assert steps.line_up("ja", _job(), paired["book"]) is None
    from tests import connect_helpers as c
    with c.store("ja") as s:
        assert library.audiobook_of_book(s, paired["book"])["lineup"] == "none"
        [ask] = [a for a in needs.asks_of(s) if a["kind"] == needs.AUDIOBOOK_LINEUP]
    entry = needs._lineup_entry(ask, set())
    assert entry.actions == ("keep_together", "separate_them") and NEKO in entry.title
    assert fake_miner.commands().count("sync") == 1, "never lined up again by itself"


def test_keep_them_together_is_kept_and_the_pair_is_never_lined_up_again(paired):
    from tests import connect_helpers as c
    with c.store("ja") as s:
        assert s.mark_audiobook_lineup(paired["item"], paired["key"], "none") is True
        assert s.mark_audiobook_lineup(paired["item"], paired["key"], "none") is False, "the same mark writes nothing"
        assert s.audiobook_keep_together(paired["item"], "another pair") is False
        assert s.audiobook_keep_together(paired["item"], paired["key"]) is True
        assert s.audiobook_mismatches() == []
        assert library.audiobook_of_book(s, paired["book"])["lineup"] == "kept"
    assert paired["steps"].line_up("ja", _job(), paired["book"]) is None


def test_separate_them_makes_it_its_own_title_and_undo_puts_the_pair_back(paired):
    """*Separate them*: the audiobook leaves the book's title for one of its own (alone again: no `book`, the pair's
    answer *No* so no look pairs them again, never *Find its book…*), in ONE command; Undo puts the pair, the answer
    and the title back as they were, and the title it made goes."""
    from tests import connect_helpers as c
    with c.store("ja") as s:
        s.mark_audiobook_lineup(paired["item"], paired["key"], "none")
        book_work = s.item(paired["item"])["work_id"]
        before = s.audiobook_answers().get(paired["key"])
        assert s.audiobook_separate(paired["item"], key="another pair") is None
        change = s.audiobook_separate(paired["item"], key=paired["key"])
        assert change is not None
        own = s.item(paired["item"])["work_id"]
        assert own != book_work and s.conn.execute("SELECT title FROM works WHERE id = ?", (own,)).fetchone()[0] == NEKO
        rec = _record(s, paired["item"])
        assert rec["book"] is None and rec["ask"] is None and not rec.get("said_no")
        assert s.audiobook_answers()[paired["key"]] is False
        assert s.audiobook_mismatches() == [] and s.audiobook_finds() == []
        assert library.audiobook_of_book(s, paired["book"]) is None
        s.undo(change)
        assert s.item(paired["item"])["work_id"] == book_work
        assert _record(s, paired["item"])["book"]["key"] == paired["key"]
        assert s.audiobook_answers().get(paired["key"]) == before
        assert s.conn.execute("SELECT 1 FROM works WHERE id = ?", (own,)).fetchone() is None
        assert [a["item_id"] for a in s.audiobook_mismatches()] == [paired["item"]], "the question is back"


# --------------------------------------------------------------------------- #
# The runner: the question once for the language, the plain line once a book, the split, Stop, the row
# --------------------------------------------------------------------------- #
class _LineUpSteps:
    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def line_up(self, lang, job, epub):
        self.calls.append((job["item_id"], epub))
        got = self.answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got


def test_the_speech_models_question_is_one_need_for_the_language_and_holds_every_book(tmp_path):
    """Two parts (or two books) waiting on the question: ONE standing *Needs you* line, each part held by its words
    (the feed's HELD); *Download it* fixes it, keeps the answer and queues every part it held again."""
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        a = ledger.queue("ja", 11, "mine", None, "store-1")
        b = ledger.queue("ja", 12, "mine", None, "store-1")
        steps = _LineUpSteps([{"ask": runner.SPEECH_ASK}, {"ask": runner.SPEECH_ASK}])
        for jid, item in ((a, 11), (b, 12)):
            with pytest.raises(runner.Wait) as w:
                runner._line_up(steps, ledger, "ja", {"id": jid, "item_id": item}, ("x.epub", "x.epub"))
            assert w.value.reason == runner.SPEECH_ASK and w.value.look is False
            runner._wait(ledger, ledger.job_by_id(jid), w.value, {"waiting": {}})
        open_needs = [n for n in ledger.needs("ja") if n["kind"] == runner.SPEECH_NEED]
        assert len(open_needs) == 1 and open_needs[0]["item_id"] is None
        need_id = open_needs[0]["id"]
    assert actions.speech_model("ja", need_id, True, path=str(tmp_path / "ledger.db")) is True
    assert lineup.answer() == "yes"
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        assert [ledger.job_by_id(j)["state"] for j in (a, b)] == ["queued", "queued"]
        assert not [n for n in ledger.needs("ja") if n["kind"] == runner.SPEECH_NEED]
    assert actions.speech_model("ja", need_id, False, path=str(tmp_path / "ledger.db")) is False, "answered already"
    assert lineup.answer() == "yes"


def test_the_plain_line_is_recorded_once_a_book_and_a_line_up_goes_with_the_pick(tmp_path):
    lined = {"key": "k", "grade": "A", "files": []}
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        steps = _LineUpSteps([{"lineup": lined, "line": "「杜子春」: skips", "item_id": 77}] * 2 + [None])
        assert runner._line_up(steps, ledger, "ja", {"id": 1, "item_id": 5}, ("b.epub", "b.epub")) == lined
        assert runner._line_up(steps, ledger, "ja", {"id": 2, "item_id": 6}, ("b.epub", "b.epub")) == lined
        lines = [n for n in ledger.needs("ja") if n["kind"] == runner.PARTIAL_NEED]
        assert len(lines) == 1 and lines[0]["item_id"] == 77
        assert runner._line_up(steps, ledger, "ja", {"id": 3, "item_id": 7}, ("b.txt", None)) is None
        assert runner._line_up(steps, ledger, "ja", {"id": 3, "item_id": 7}, ("b.epub", "b.epub")) is None
        assert len(steps.calls) == 3, "a text with no EPUB is never lined up"


def test_a_lined_up_part_goes_as_one_audio_episode_a_file_and_the_rest_as_the_book(tmp_path, monkeypatch):
    """`Steps.mine`: each file's words as its audio episode (its SRT, offset 0, no reading file), the words not heard
    as the book — outcomes back in the words' order; a call that fails after another made cards returns those, the
    rest not attempted (the next batch sends only them)."""
    state, audio = _state_of_resources(tmp_path)
    lined = {"status": lineup.DONE, "key": "k", "grade": "A", "files": state["files"]}
    words = [
        {"word": "若者", "reading": "ワカモノ", "surface": "若者",
         "line_text": "唐の都洛陽の西の門の下に、ぼんやり空を仰いでゐる、一人の若者がありました。"},
        {"word": "吾輩", "reading": "ワガハイ", "surface": "吾輩", "line_text": "吾輩は猫である。"},
        {"word": "贅沢", "reading": "ゼイタク", "surface": "贅沢",
         "line_text": "大金持になつた杜子春は、すぐに立派な家を買つて、玄宗皇帝にも負けない位、贅沢な暮しをし始めました。"},
    ]
    picked = {"reading": "book.epub", "book": "book.epub", "video": None, "subtitle": None, "lineup": lined}
    calls = []

    def one(lang, job, run, ws, attempt):
        calls.append((run.get("video"), run.get("subtitle"), run.get("reading"), [w["word"] for w in ws], attempt,
                      [w.get("line_start") for w in ws]))
        return {"outcomes": [{"word": w["word"], "reading": w["reading"], "outcome": "made", "note_id": n}
                             for n, w in enumerate(ws)], "app": "3.11.0", "doubt": False, "tag_pending": [],
                "stopped": False}
    steps = runner.Steps({})
    monkeypatch.setattr(steps, "_mine_one", one)
    got = steps.mine("ja", {"id": 3}, picked, words, 2)
    assert calls == [(audio[0], os.path.join(SYNCED, "toshisyun_01.srt"), None, ["若者"], 2, [20.84]),
                     (audio[1], os.path.join(SYNCED, "toshisyun_02.srt"), None, ["贅沢"], "2-1", [23.92]),
                     (None, None, "book.epub", ["吾輩"], "2-2", [None])]
    assert [o["word"] for o in got["outcomes"]] == ["若者", "吾輩", "贅沢"]
    assert all(o["outcome"] == "made" for o in got["outcomes"])

    def second_fails(lang, job, run, ws, attempt):
        if attempt != 2:
            raise runner.Wait(runner.ANKI_CLOSED)
        return one(lang, job, run, ws, attempt)
    monkeypatch.setattr(steps, "_mine_one", second_fails)
    got = steps.mine("ja", {"id": 3}, picked, words, 2)
    assert [o["outcome"] for o in got["outcomes"]] == ["made", "not_attempted", "not_attempted"]
    monkeypatch.setattr(steps, "_mine_one", lambda *a: (_ for _ in ()).throw(runner.Wait(runner.ANKI_CLOSED)))
    with pytest.raises(runner.Wait):
        steps.mine("ja", {"id": 3}, picked, words, 2)
    unlined = dict(picked, lineup=None)
    monkeypatch.setattr(steps, "_mine_one", one)
    calls.clear()
    steps.mine("ja", {"id": 3}, unlined, words, 4)
    assert calls == [(None, None, "book.epub", ["若者", "吾輩", "贅沢"], 4, [None, None, None])]


def test_stop_on_a_book_lining_up_stops_its_sync(tmp_path, monkeypatch):
    """`runner._stopped`: a job whose wait is a line-up's has its line-up stopped too (the cancel file), before it is
    marked stopped; any other job's stop never touches a line-up."""
    stopped = []

    class S:
        def stop_line_up(self, lang, job):
            stopped.append(job["item_id"])

        def record(self, *a):
            pass
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = ledger.queue("ja", 21, "mine", None, "store-1")
        ledger.set_state(jid, "waiting", reason=runner.LINING_UP_FILE.format(k=2, n=6))
        with pytest.raises(runner.Wait) as w:
            runner._stopped(S(), ledger, "ja", ledger.job_by_id(jid), None, True)
        assert w.value.reason == runner.STOPPED_BY_YOU and stopped == [21]
        other = ledger.queue("ja", 22, "mine", None, "store-1")
        ledger.set_state(other, "waiting", reason=runner.ANKI_CLOSED)
        with pytest.raises(runner.Wait):
            runner._stopped(S(), ledger, "ja", ledger.job_by_id(other), None, True)
        assert stopped == [21]


def test_the_rows_line_while_it_lines_up_is_the_runners_with_stop(tmp_path):
    """The feed tells LINING_UP by the runner's one rule; the row's pill reads the line itself (*Lining up its
    audiobook… file 2 of 6*) with its *Stop* while the job can be stopped, *Stopping…* after the press; once stopped,
    a plain wait saying how it goes on."""
    record = {"running": True, "languages": {"ja": {"jobs": [
        {"item": 5, "job": 9, "state": "waiting", "reason": runner.LINING_UP_FILE.format(k=2, n=6)},
        {"item": 6, "job": 10, "state": "waiting", "reason": runner.LINING_UP_STOPPED}]}}}
    got = feed.build(record, "ja")
    assert got.items[5].kind == feed.LINING_UP and got.items[5].stoppable
    assert got.items[6].kind == feed.WAITING and got.items[6].tip == runner.LINING_UP_STOPPED   # stopped: a plain wait
    st = view_rows._connected(view_rows.Status("waiting", "Waiting", "", "dim"), got.items[5], "book")
    assert (st.kind, st.label, st.stop) == ("mining", "Lining up its audiobook… file 2 of 6", 9)
    stopping = got.items[5]._replace(stopping=True)
    assert view_rows._connected(view_rows.Status("waiting", "Waiting", "", "dim"), stopping, "book").label == \
        view_rows.STRINGS["stopping"]


# --------------------------------------------------------------------------- #
# The review's round (tracks/pipeline/work/AB/review-stage-b-adversary.md)
# --------------------------------------------------------------------------- #
def test_b1_a_stop_not_ended_yet_is_never_a_second_sync_on_its_folder(paired, fake_miner):
    """B-1: *Stop*, then *Mine now* before Anki Miner reached its next step: the part waits *stopping* while the stopped
    child still runs — never its cancel file removed, never a second `sync` on the same run folder."""
    fake_miner.plan(speech={"installed": ["small"], "model": "small"}, sync={"files": paired["srts"], "hold": 20.0,
                                                                             "report": {"grade": "A"}})
    steps = paired["steps"]
    with pytest.raises(runner.Wait):
        steps.line_up("ja", _job(), paired["book"])
    proc, _out = lineup._RUNNING[paired["key"]]
    lineup.write(paired["key"], dict(lineup.read(paired["key"]), status=lineup.STOPPED, stopped_at="2026-01-01T00:00:00Z"))
    with pytest.raises(runner.Wait) as w:
        steps.line_up("ja", _job(asked_at="2999-01-01T00:00:00Z"), paired["book"])
    assert w.value.reason == runner.LINING_UP_STOPPING and w.value.pair == paired["key"]
    assert lineup._RUNNING[paired["key"]][0] is proc
    with pytest.raises(anki_miner.AnkiMinerError):
        lineup.start_sync(fake_miner.path, "ja", None, paired["key"], paired["book"], paired["files"])
    _until(lambda: fake_miner.commands().count("sync") == 1)
    assert fake_miner.commands().count("sync") == 1


def test_b2_one_line_up_at_a_time_across_books(paired, fake_miner, tmp_path):
    """B-2: another book's line-up running → this book waits its turn (*after another book's*), never a second speech
    model listening for hours beside it."""
    audio = _audio_files(tmp_path)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"},
                    sync=_synced_plan([os.path.basename(a) for a in audio], hold=20.0))
    lineup.start_sync(fake_miner.path, "ja", None, "another-pair", _book(tmp_path), audio)
    with pytest.raises(runner.Wait) as w:
        paired["steps"].line_up("ja", _job(), paired["book"])
    assert w.value.reason == runner.LINING_UP_AFTER and runner.lining_up(w.value.reason)
    assert paired["key"] not in lineup._RUNNING


def test_b3_a_moved_audiobook_is_cut_from_its_files_where_they_are_now_and_one_away_goes_as_the_book(paired, tmp_path):
    """B-3: a finished line-up named the files where they were; the pair's key is their sizes, so the store's files
    now are the same files: the cards are cut from them. A file away (a drive unplugged): its words go as the book."""
    moved = [str(tmp_path / f"moved{k}.mp3") for k in range(3)]
    for m in moved[:2]:
        open(m, "wb").close()
    state = {"status": lineup.DONE, "grade": "A", "book": paired["book"],
             "files": [{"audio_file": f"Z:/gone/{k}.mp3", "subtitle_file": os.path.join(SYNCED, f"toshisyun_0{min(k, 1) + 1}.srt"),
                        "status": "synced"} for k in range(3)]}
    lineup.write(paired["key"], state)
    from tests import connect_helpers as c
    with c.store("ja") as s:
        with s._writing():
            for key, _i, rec in s._audiobook_rows(paired["item"]):
                s.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?",
                               (json.dumps(dict(rec, audiobook=dict(rec["audiobook"], files=moved)), sort_keys=True,
                                           ensure_ascii=False), key))
    got = paired["steps"].line_up("ja", _job(), paired["book"])
    assert [f["audio_file"] for f in got["lineup"]["files"]] == moved
    found = lineup.cues(got["lineup"])
    assert {c.audio for c in found} == set(moved[:2]), "the file away is never sent"


def test_b4_b6_a_stopped_or_failed_download_asks_again_and_keeps_its_reason(paired, fake_miner):
    fake_miner.plan(speech={"installed": []}, speech_setup="installed")
    lineup.set_answer(True)
    lineup.write(lineup.SPEECH, {"status": lineup.STOPPED, "stopped_at": "2026-11-02T10:00:00Z"})
    got = paired["steps"].line_up("ja", _job(), paired["book"])
    assert got == {"ask": runner.SPEECH_FAILED.format(why="it was stopped")} and lineup.answer() is None
    assert "setup" not in fake_miner.commands(), "a stopped download never starts again by itself (B-4)"
    assert lineup.asks_speech(got["ask"]) and lineup.asks_speech(runner.SPEECH_ASK)
    assert not lineup.asks_speech(runner.LINING_UP_STOPPED)


def test_b5_its_window_open_is_a_wait_and_the_download_starts_again(paired, fake_miner):
    fake_miner.plan(speech={"installed": []}, speech_setup="installed")
    lineup.set_answer(True)
    lineup.write(lineup.SPEECH, {"status": lineup.RUNNING})           # left by a child that answered BUSY
    lineup._RUNNING.pop(lineup.SPEECH, None)
    lineup.write(lineup.SPEECH, {"status": lineup.INTERRUPTED, "busy": True})
    with pytest.raises(runner.Wait) as w:
        paired["steps"].line_up("ja", _job(), paired["book"])
    assert w.value.reason == runner.ANKI_MINER_OPEN
    _until(lambda: not lineup.running(lineup.SPEECH))
    assert fake_miner.commands().count("setup") == 1


def test_b11_after_not_now_anki_miner_is_never_asked_about_the_model(paired, fake_miner):
    fake_miner.plan(speech={"installed": []})
    lineup.set_answer(False)
    assert paired["steps"].line_up("ja", _job(), paired["book"]) is None
    assert "check" not in fake_miner.commands() and "settings-import" not in fake_miner.commands()


def test_b14_a_word_in_two_of_its_sentences_cues_is_no_answer_and_the_books_unit_names_its_cue(tmp_path):
    """B-14: 人 in a line of two sentences whose cues both hold it (人間, 人) is no answer (the book's card, never a
    neighbour's clip); the unit the pick knows (Anki Miner's own index) names the cue when it holds the word."""
    srt = tmp_path / "a.srt"
    srt.write_text(_srt_of(["人間はみな死ぬものだと思っている。", "その人は静かに笑っていました。"]), encoding="utf-8")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3")
    state = {"status": lineup.DONE, "grade": "A", "files": [{"audio_file": str(audio), "subtitle_file": str(srt),
                                                            "status": "synced", "units": {"1": 40, "2": 41}}]}
    line = "人間はみな死ぬものだと思っている。その人は静かに笑っていました。"
    found = lineup.cues(state)
    assert lineup.place(line, "人", found) is None
    assert lineup.place(line, "笑", found).unit == 41
    assert lineup.place(line, "人", found, unit=41).start == found[1].start
    assert lineup.place(line, "笑", found, unit=40) is not None and lineup.place(line, "笑", found, unit=40).unit == 41


def test_b8_b9_a_restarted_line_up_frees_its_stopped_parts_and_a_stop_needs_no_store_read(tmp_path, monkeypatch):
    """B-8: *Mine now* on one part starts a stopped line-up again: its other parts parked on the stop are queued and the
    run woken. B-9: the pair a part waits on is kept, so its *Stop* cancels that line-up with no store read."""
    woke = []
    monkeypatch.setattr("app.connect.kick.wake", lambda videos=False: woke.append(1))
    stopped = []
    monkeypatch.setattr(lineup, "stop", lambda key: stopped.append(key))
    restart = runner._lining(runner.LINING_UP_FILE.format(k=1, n=3), "pair-x")
    restart.restarted = True
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        a = ledger.queue("ja", 31, "mine", None, "store-1")
        b = ledger.queue("ja", 32, "mine", None, "store-1")
        ledger.set_state(b, "waiting", reason=runner.LINING_UP_STOPPED)
        with pytest.raises(runner.Wait):
            runner._line_up(_LineUpSteps([restart]), ledger, "ja", {"id": a, "item_id": 31}, ("x.epub", "x.epub"))
        assert ledger.job_by_id(b)["state"] == "queued" and woke == [1]
        parked = {b: None, a: None}
        ledger.set_state(a, "waiting", reason=runner.LINING_UP_FILE.format(k=1, n=3))
        monkeypatch.setattr(runner, "_kicked", lambda steps: True)
        runner._woken(None, ledger, parked)
        assert parked == {a: None}, "the queued part goes again this run; the waiting one stays parked"
        with pytest.raises(runner.Wait):
            runner._stopped(object(), ledger, "ja", ledger.job_by_id(a), None, True)
        assert stopped == ["pair-x"]


def test_b15_a_part_waiting_on_its_line_up_writes_nothing_while_its_line_is_the_same(tmp_path):
    class S(_LineUpSteps):
        def mines(self, lang, kind):
            return kind == "books"

        def reading(self, lang, job):
            return ("b.epub", "b.epub")
    line = runner.LINING_UP_FILE.format(k=2, n=6)
    with Ledger(str(tmp_path / "ledger.db")) as ledger:
        jid = ledger.queue("ja", 41, "mine", None, "store-1")
        steps = S([runner._lining(line, "p"), runner._lining(line, "p")])
        for _ in range(2):
            with pytest.raises(runner.Wait) as w:
                runner._pick(steps, ledger, "ja", ledger.job_by_id(jid))
            runner._wait(ledger, ledger.job_by_id(jid), w.value, {"waiting": {}})
            if _ == 0:
                first = ledger.job_by_id(jid)["updated_at"], ledger.conn.total_changes
        assert ledger.job_by_id(jid)["state"] == "waiting"
        assert (ledger.job_by_id(jid)["updated_at"], ledger.conn.total_changes) == first, "S19: no write a look"


def test_b16_b17_the_spot_check_ends_at_a_stop_and_the_models_setup_outlives_connect(tmp_path, fake_miner, monkeypatch):
    seen = []
    real = anki_miner.api

    def api(path, args, **kw):
        seen.append((args[0], kw.get("look_up")))
        return real(path, args, **kw)
    monkeypatch.setattr(anki_miner, "api", api)
    audio, sub = _subtitle(tmp_path, _book_lines())
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    lineup.spot_check(fake_miner.path, "ja", None, audio, sub)
    assert seen == [("media", True), ("transcribe", True)]
    bound = []
    monkeypatch.setattr(anki_miner, "_bind", lambda proc: bound.append(proc))
    fake_miner.plan(speech={"installed": []}, speech_setup="installed")
    lineup.start_speech(fake_miner.path, "ja", None)
    assert bound == [], "Anki Miner's own setup finishes whenever Connect quits"
    _until(lambda: not lineup.running(lineup.SPEECH))


def test_b18_b19_a_given_up_line_up_goes_again_after_a_newer_mine_now_compared_as_stamps(paired, fake_miner):
    lineup.write(paired["key"], {"status": lineup.FAILED, "tries": lineup.TRIES, "message": "no answer",
                                 "failed_at": "2026-11-02T10:00:00Z"})
    got = paired["steps"].line_up("ja", _job(asked_at="2026-11-02T10:00:00.500000Z"), paired["book"])
    assert got == {"ask": runner.SPEECH_ASK}, "tried again: no longer given up"
    assert runner._newer("2026-11-02T10:00:00.500000Z", "2026-11-02T10:00:00Z")
    assert not runner._newer("2026-11-02T09:59:59.900000Z", "2026-11-02T10:00:00Z")
    assert not runner._newer(None, "2026-11-02T10:00:00Z")
    given_up = paired["steps"].line_up("ja", _job(asked_at="2026-11-02T09:00:00Z"), paired["book"])
    assert given_up["lineup"] is None and "no answer" in given_up["line"]
