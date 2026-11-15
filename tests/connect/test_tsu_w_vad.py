"""Tsu-W (based on Mattias's #452): a video with no subtitle track inside (a BD rip) is timed against its own speech —
tsubasa 0.1.13's `--vad`, through the whisper.cpp and the two models Anki Miner installed for its own subtitle making.

What a wrong answer would cost: a raw video's subtitles sat in *Needs you* for ever ("no subtitle track to align
against"), or — worse — a check that listened with the wrong files, or downloaded some, or slowed every video that HAS
a track. So: only a Japanese library (Chinese is unmeasured); only when Anki Miner's `whisper.dll`, its Silero model and
one of its two whisper models are all there (found, never downloaded: nothing is written); only after tsubasa's quick
check said the video has no track (a video with one is asked exactly as before); the small model first (it separates
right from wrong as well, ~5x faster); a refusal is *Needs you* in plain words; *Trust my subtitles' timing* is as
before. tsubasa is a stand-in throughout (`run=`), as in test_fit_check.py.
"""
import json
import os
import subprocess
from types import SimpleNamespace

from app.connect import fit_check, status
from tests.connect_helpers import tsubasa_answer

VIDEO = "C:/Video/ぼっち・ざ・ろっく！ 03 [BD].mkv"
AUDIO = "C:/Audio/蜘蛛の糸.mp3"
SUBTITLE = "C:/Subs/ぼっち・ざ・ろっく！ 03.ja.srt"
# tsubasa's own words for a raw (P0.2, 0.1.12): no `--vad`
RAW = tsubasa_answer("ERROR", segments=(), reason="it has no subtitle track to align against. Run with --vad (vad=True) "
                     "to measure it against the speech in its audio instead; that needs whisper.cpp and two of its "
                     "models, and nothing is guessed without them.")
# 0.1.13 with `--vad`: CONFIDENT on the speech mask, capped at fair
HEARD = tsubasa_answer(segments=((None, -0.88),), reference_kind="speech mask", verdict_word="fair")
# the text check disagreed (another episode's subtitle): tsubasa's reason is for a developer, never the learner's line
MISHEARD = tsubasa_answer("REFUSED", segments=(), reference_kind="speech mask", reason=(
    "61% of the speech in the audio lines up with this subtitle, 2.3 times chance -- enough on timing alone -- but "
    "the words in the audio don't match its lines. Nothing is written. --pair with --force writes this one anyway."))
# whisper.cpp there but not a release tsubasa checked: the speech couldn't be measured — still a raw's ERROR
UNHEARD = tsubasa_answer("ERROR", segments=(), reason="it has no subtitle track to align against, and its speech could "
                         "not be measured instead: whisper.cpp 1.8.5 is not a release this tsubasa checked")
SMALL, LARGE, SILERO = "ggml-small-q5_1.bin", "ggml-large-v3-q5_0.bin", "ggml-silero-v6.2.0.bin"


def _speech_files(root, library=True, models=(SILERO, SMALL)):
    """Anki Miner's layout: `<install>\\_internal\\whisper.dll` and `<home>\\asr_models\\ggml\\<model>` (3.10.1's
    `ggml_model_installer`: these exact names)."""
    lib, ggml = root / "AnkiMiner" / "_internal", root / "home" / "asr_models" / "ggml"
    lib.mkdir(parents=True)
    ggml.mkdir(parents=True)
    if library:
        (lib / "whisper.dll").write_bytes(b"MZ")
    for name in models:
        (ggml / name).write_bytes(b"lmgg")
    return str(lib), str(ggml)


def _setup(root, **kw):
    lib, ggml = _speech_files(root, **kw)
    return fit_check.speech_setup("ja", library=lib, models=ggml)


def _speech(**env):
    return fit_check.Speech(["--vad"], dict({"TSUBASA_WHISPER": "w"}, **env), 1200)


class _Tsubasa:
    """A stand-in for `subprocess.run`: each call's command, timeout and environment kept; answers in turn."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, command, **kw):
        self.calls.append(SimpleNamespace(command=command, timeout=kw.get("timeout"), env=kw.get("env")))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return SimpleNamespace(stdout=(json.dumps(answer) + "\n").encode("utf-8"))


def _fit(run, speech, video=VIDEO, trust=False, listening=None, pairing=None):
    return fit_check.fit(pairing, video, SUBTITLE, tsubasa="tsubasa", run=run, trust=trust, speech=speech,
                         listening=listening)


# --- where the speech files are -----------------------------------------------------------------------------------

def test_all_three_of_anki_miners_speech_files_give_tsubasa_vad_and_where_each_one_is(tmp_path):
    lib, ggml = _speech_files(tmp_path)
    got = fit_check.speech_setup("ja", library=lib, models=ggml)
    assert got.args == ["--vad"]
    assert got.env["TSUBASA_WHISPER"] == lib
    assert got.env["TSUBASA_VAD_MODEL"] == os.path.join(ggml, SILERO)
    assert got.env["TSUBASA_ASR_MODEL"] == os.path.join(ggml, SMALL)
    assert got.env["PATH"] == os.environ["PATH"]        # the rest of the environment as Connect's own
    assert got.timeout > fit_check.TIMEOUT_S            # listening takes minutes, never the quick check's 2


def test_the_small_whisper_model_is_taken_before_large_and_large_alone_gets_longer(tmp_path):
    # #452 took the first model listed — large-v3 (~11 min an episode on CPU); the small one separates right from wrong
    # as cleanly in Tsu-V's measurements at ~2 min. Large alone still listens, with a timeout sized to it.
    both = _setup(tmp_path / "both", models=(SILERO, LARGE, SMALL))
    large = _setup(tmp_path / "large", models=(SILERO, LARGE))
    assert both.env["TSUBASA_ASR_MODEL"].endswith(SMALL)
    assert large.env["TSUBASA_ASR_MODEL"].endswith(LARGE)
    assert large.timeout > both.timeout


def test_any_speech_file_missing_means_no_vad(tmp_path):
    for case, kw in (("no whisper.dll", {"library": False}), ("no Silero", {"models": (SMALL, LARGE)}),
                     ("no whisper model", {"models": (SILERO,)}),
                     ("another program's model name", {"models": (SILERO, "ggml-medium.bin")})):
        lib, ggml = _speech_files(tmp_path / case.replace(" ", "_").replace("'", ""), **kw)
        assert fit_check.speech_setup("ja", library=lib, models=ggml) is None, case
    assert fit_check.speech_setup("ja", library=str(tmp_path / "gone"), models=str(tmp_path / "gone")) is None


def test_a_chinese_library_never_listens(tmp_path):
    # Chinese is unmeasured on the speech path (Sonic: wait): a zh library is asked exactly as before
    lib, ggml = _speech_files(tmp_path)
    assert fit_check.speech_setup("zh", library=lib, models=ggml) is None
    assert fit_check.speech_setup(None, library=lib, models=ggml) is None


def test_the_files_are_found_where_anki_miner_keeps_them_and_nothing_is_written(tmp_path, monkeypatch):
    # its program's own folder (the setting, as `anki_miner.find` reads it) + `_internal`; its home (ANKI_MINER_HOME,
    # else ~/.anki_miner) + asr_models/ggml. Looking never makes a folder or a file: nothing is downloaded.
    lib, ggml = _speech_files(tmp_path)
    exe = os.path.join(os.path.dirname(lib), "AnkiMiner.exe")
    open(exe, "wb").close()
    monkeypatch.setenv("ANKI_MINER_HOME", str(tmp_path / "home"))
    got = fit_check.speech_setup("ja", {"connect_anki_miner_path": exe})
    assert got is not None and got.env["TSUBASA_WHISPER"] == lib and got.env["TSUBASA_ASR_MODEL"].endswith(SMALL)
    before = sorted(p for p, _d, _f in os.walk(tmp_path))
    monkeypatch.setenv("ANKI_MINER_HOME", str(tmp_path / "no-home"))
    assert fit_check.speech_setup("ja", {"connect_anki_miner_path": exe}) is None
    assert fit_check.speech_setup("ja", {}) is None                 # no Anki Miner found (a test root never finds one)
    assert sorted(p for p, _d, _f in os.walk(tmp_path)) == before


# --- the check ----------------------------------------------------------------------------------------------------

def test_a_raw_video_is_listened_to_and_mined_at_the_speechs_offset():
    heard = []
    run = _Tsubasa(RAW, HEARD)
    got = _fit(run, _speech(), listening=lambda: heard.append(len(run.calls)))
    assert got == (fit_check.TIMED, "tsubasa", None, -0.88)
    quick, listen = run.calls
    assert quick.command == ["tsubasa", "--pair", VIDEO, SUBTITLE, "--dry-run", "--json", "--no-results"]
    assert quick.env is None and quick.timeout == fit_check.TIMEOUT_S
    assert listen.command == quick.command + ["--vad"]
    assert listen.env == {"TSUBASA_WHISPER": "w"} and listen.timeout == 1200
    assert heard == [1]                 # said once, after the quick check and before the minutes of listening


def test_a_video_with_its_own_track_is_asked_exactly_as_before():
    run = _Tsubasa(tsubasa_answer(segments=((None, 1.5),)))
    assert _fit(run, _speech(), listening=lambda: 1 / 0) == (fit_check.TIMED, "tsubasa", None, 1.5)
    assert [c.command[-1] for c in run.calls] == ["--no-results"] and run.calls[0].env is None


def test_without_the_speech_files_a_raw_video_waits_as_before():
    run = _Tsubasa(RAW)
    got = _fit(run, None)
    assert got[0] == fit_check.NOT_TIMED and fit_check.TRUST_LABEL in got[2] and len(run.calls) == 1


def test_trusting_your_subtitles_still_mines_a_raw_video_at_once_without_listening():
    run = _Tsubasa(RAW)
    assert _fit(run, _speech(), trust=True, listening=lambda: 1 / 0) == (fit_check.TIMED, "you", None, 0.0)
    assert len(run.calls) == 1


def test_a_refusal_on_its_speech_waits_in_plain_words():
    run = _Tsubasa(RAW, MISHEARD)
    verdict, who, why, offset = _fit(run, _speech())
    assert (verdict, who, offset) == (fit_check.NOT_TIMED, "tsubasa", 0.0)
    assert why == fit_check.SPEECH_REFUSED
    assert "--force" not in why and "chance" not in why          # tsubasa's words are for a bug report (the log)
    assert not fit_check.part_way(why)                           # nothing to re-time


def test_speech_that_couldnt_be_measured_waits_as_a_raw_does():
    got = _fit(_Tsubasa(RAW, UNHEARD), _speech())
    assert got[0] == fit_check.NOT_TIMED and fit_check.TRUST_LABEL in got[2]


def test_speech_timed_in_two_parts_goes_to_the_retime_as_a_tracks_does():
    got = _fit(_Tsubasa(RAW, tsubasa_answer(segments=((None, -0.9), (700.0, 24.1)), reference_kind="speech mask")),
               _speech())
    assert got[0] == fit_check.NOT_TIMED and fit_check.part_way(got[2])


def test_listening_that_takes_too_long_or_wont_start_is_asked_again():
    for err in (subprocess.TimeoutExpired(["tsubasa"], 1200), OSError("not a program")):
        verdict, who, why, _o = _fit(_Tsubasa(RAW, err), _speech())
        assert (verdict, who) == (fit_check.RETRY, "tsubasa"), err
        assert why.startswith("Listening to its audio") and ";" in why     # the runner's give-up line cuts at the ;


def test_a_tsubasa_without_vad_leaves_a_raw_as_it_was():
    # 0.1.12 (the pin until 0.1.13 is out) refuses `--vad` with a usage line and no JSON: the raw's reason, as before
    calls = []

    def usage(command, **kw):
        calls.append(command)
        return SimpleNamespace(stdout=b"" if "--vad" in command else (json.dumps(RAW) + "\n").encode("utf-8"))
    got = _fit(usage, _speech())
    assert got[0] == fit_check.NOT_TIMED and fit_check.TRUST_LABEL in got[2] and len(calls) == 2


def test_stop_while_it_listens_stops_the_job():
    # the job's *Stop* ends tsubasa within a second (row 56): never read as an answer or a retry
    import pytest
    from app.connect import stopping
    with pytest.raises(stopping.Stopped):
        _fit(_Tsubasa(RAW, stopping.Stopped()), _speech())


def test_a_quick_check_with_no_answer_never_listens():
    run = _Tsubasa(subprocess.TimeoutExpired(["tsubasa"], 120))
    assert _fit(run, _speech(), listening=lambda: 1 / 0)[0] == fit_check.RETRY and len(run.calls) == 1


def test_an_audio_files_subtitle_is_never_listened_to_this_way():
    # an audiobook has its own spot-check (AB-Q5); tsubasa's speech path was measured on episodes, not hours of a book
    run = _Tsubasa(RAW)
    assert _fit(run, _speech(), video=AUDIO, listening=lambda: 1 / 0)[0] == fit_check.NOT_TIMED
    assert len(run.calls) == 1


def test_a_raw_hato_paired_untimed_is_never_listened_to():
    run = _Tsubasa(RAW)
    assert _fit(run, _speech(), pairing={"schema": 1, "verdict": "untimed"})[0] == fit_check.NOT_TIMED
    assert len(run.calls) == 1


# --- the retime -----------------------------------------------------------------------------------------------------

def _retime(video, speech, raw, tmp_path):
    """`retime` over a stand-in tsubasa: a raw (`raw`) answers the plain run with its ERROR, else every run writes."""
    out = tmp_path / "out"
    seen = []

    def run(command, **kw):
        seen.append(SimpleNamespace(command=command, env=kw.get("env"), timeout=kw.get("timeout")))
        answer = RAW if raw and "--vad" not in command else tsubasa_answer(output_path=str(out / "x.srt"))
        if answer is not RAW:
            out.mkdir(exist_ok=True)
            (out / "x.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nうん\n", encoding="utf-8")
        return SimpleNamespace(stdout=(json.dumps(answer) + "\n").encode("utf-8"))
    return fit_check.retime(video, SUBTITLE.replace(".ja.srt", ".srt"), str(out), tsubasa="tsubasa", run=run,
                            speech=speech), seen


def test_the_retime_listens_to_a_raw_and_re_times_a_video_with_a_track_exactly_as_before(tmp_path):
    # the review's blocking find: `--vad` on every video's re-time — a tsubasa 0.1.12 refuses the option, so a track
    # video's part-way timing would never be re-timed again. Only a raw (the plain run's ERROR) is asked with it.
    made, seen = _retime(VIDEO, _speech(), True, tmp_path / "raw")
    plain, vad = seen
    assert made is not None and made.path.endswith("x.srt")
    assert plain.command[-1] == "--no-results" and plain.env is None and plain.timeout == fit_check.TIMEOUT_S
    assert vad.command == plain.command + ["--vad"] and vad.env == {"TSUBASA_WHISPER": "w"} and vad.timeout == 1200
    for case, video, speech in (("a track", VIDEO, _speech()), ("no speech files", VIDEO, None),
                                ("an audio file", AUDIO, _speech())):
        made, seen = _retime(video, speech, False, tmp_path / case.replace(" ", "_"))
        assert made is not None and [c.command[-1] for c in seen] == ["--no-results"] and seen[0].env is None, case
    made, seen = _retime(VIDEO, None, True, tmp_path / "raw_no_speech")
    assert made is None and len(seen) == 1


# --- Connect's steps and what the row says -------------------------------------------------------------------------

def test_connects_steps_hand_the_check_and_the_retime_their_librarys_speech_files(monkeypatch, tmp_path):
    from app.connect import runner
    asked, given = [], []
    monkeypatch.setattr(fit_check, "speech_setup", lambda lang, settings=None: asked.append(lang) or f"speech:{lang}")
    monkeypatch.setattr(fit_check, "fit", lambda *a, **kw: given.append(kw) or (fit_check.TIMED, "tsubasa", None, 0.0))
    steps = runner.Steps({"connect_trust_timing": False})
    monkeypatch.setattr(steps, "_settings", lambda lang: {"connect_trust_timing": False, "target_language": lang})
    said = []
    steps.on_listening = lambda: said.append(1)         # `_fit` sets it for its job's check
    steps.fit("ja", {"id": 1}, None, VIDEO, SUBTITLE)
    steps.on_listening = None
    steps.fit("zh", {"id": 2}, None, VIDEO, SUBTITLE)
    assert asked == ["ja", "zh"]
    assert [g["speech"] for g in given] == ["speech:ja", "speech:zh"]
    given[0]["listening"]()
    assert said == [1] and given[1]["listening"] is None


def test_looking_for_the_speech_files_never_fails_a_check(monkeypatch):
    from app.connect import anki_miner

    def broken():
        raise RuntimeError("no home folder")
    monkeypatch.setattr(anki_miner, "home", broken)
    assert fit_check.speech_setup("ja", library="C:/nowhere") is None


def test_while_it_listens_the_row_says_so():
    job = {"state": "fit-check", "progress": json.dumps({"step": fit_check.LISTENING})}
    assert status._progress(job) == {"percent": status.STEP_AT["fit-check"][0], "doing": status.LISTENING[1]}
    assert status._progress({"state": "fit-check", "progress": None})["doing"] == status.STEP_AT["fit-check"][1]


def test_connect_saves_listening_on_the_job_while_it_listens_and_a_stale_line_is_forgotten_first(tmp_path, monkeypatch):
    from app.connect import runner
    from app.connect.ledger import Ledger
    from tests.connect.fake_steps import FakeSteps
    monkeypatch.setattr(status, "running", lambda: True)
    seen = []

    class Listens(FakeSteps):
        def fit(self, lang, job, pairing, video, subtitle):
            seen.append(json.loads(ledger.job_by_id(job["id"])["progress"] or "null"))
            self.on_listening()
            now = ledger.job_by_id(job["id"])
            seen.append((now["state"], status._progress(now)["doing"]))
            return fit_check.NOT_TIMED, "tsubasa", fit_check.SPEECH_REFUSED, 0.0

    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            job_id = ledger.queue("ja", 1, "user", None, store_id="store-1")
            # a line left from an earlier listen (a crash mid-check): the next check starts without it — the quick
            # check comes first
            ledger.set_state(job_id, ledger.job_by_id(job_id)["state"], progress={"step": fit_check.LISTENING})
        steps = Listens(str(tmp_path), {"line": {"ja": [1]}})
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert seen == [None, ("fit-check", status.LISTENING[1])]
        needs = [n for n in ledger.needs("ja") if n["kind"] == "not-timed"]
        assert len(needs) == 1 and fit_check.SPEECH_REFUSED in needs[0]["say"]
        assert steps.on_listening is None                   # the job's callback never outlives its check


def test_a_listening_line_that_cant_be_saved_never_stops_the_check(tmp_path, monkeypatch):
    from app.connect import runner
    from app.connect.ledger import Ledger
    from tests.connect.fake_steps import FakeSteps
    monkeypatch.setattr(status, "running", lambda: True)

    class Listens(FakeSteps):
        def fit(self, lang, job, pairing, video, subtitle):
            real = ledger.set_state

            def locked(job_id, state, **kw):
                if kw.get("progress") == {"step": fit_check.LISTENING}:
                    import sqlite3
                    raise sqlite3.OperationalError("database is locked")
                return real(job_id, state, **kw)
            monkeypatch.setattr(ledger, "set_state", locked)
            self.on_listening()
            monkeypatch.setattr(ledger, "set_state", real)
            return fit_check.TIMED, "tsubasa", None, -0.88

    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        with ledger.transaction():
            job_id = ledger.queue("ja", 1, "user", None, store_id="store-1")
        steps = Listens(str(tmp_path), {"line": {"ja": [1]}})
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert ledger.job_by_id(job_id)["state"] == "done"
