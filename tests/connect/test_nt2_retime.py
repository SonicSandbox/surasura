"""Michi-NT2 (based on the approach in Mattias's #364; field reports #XP44T6 / #7J3960): Re:Zero S04E16, a Netflix
subtitle on an AT-X broadcast cut another way — tsubasa is sure of its timing, but it changes part-way (+8.76 s up to
86.35 s, -1.17 s after). One shift can't cut that, so the episode is rightly *Not timed*; and nothing beside its video
helps when the learner hasn't re-timed it himself. Now tsubasa re-times Surasura's own library copy, every part its
own shift, once a job: written in the job's run folder (`fit_check.retime`: `--out`, never `--dry-run`, always
`--no-results`), and only when it holds the copy's very lines it takes the copy's place by S5's own rule
(`sources.put_copy`: the old copy into the data folder's `.trash` first, then `os.replace`) — only a copy inside the
language's `Library`. Then the episode is picked again from it and checked again.

Also here: Connect's tests never see the machine's tsubasa (Mattias found `test_lineup`'s trust test red with a
tsubasa on PATH): `tests/connect/conftest.py` hides it.

What a wrong answer would cost: the learner's library copy overwritten with another subtitle's lines, or lost with no
trash copy; a hato or 2.x file outside `Library` rewritten; tsubasa asked to re-time again at every start; or an
episode tsubasa can re-time left *Not timed* for ever.

Real Japanese subtitles (`tests/Test Resources/ja/airing/`, CRLF), re-timed here in two parts as tsubasa would write
them; tsubasa itself stood in for (`fit_check._run`), never the machine's.
"""
import json
import os
import shutil
import subprocess

import pytest

from app import sources
from app.connect import actions, fit_check, runner, stopping
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS
from tests.connect.test_nt_not_timed_again import (SOURCE, TWO_SEGMENTS, VIDEO, Steps, _beside, _job, _needs,
                                                    _plan, _run, _shifted, _source_text)


def _two_parts(text):
    """The subtitle re-timed in two parts, as tsubasa writes a cut broadcast's: +8.76 s up to the 5th line, -1.17 s
    after (the same lines, other times)."""
    blocks = text.replace("\r\n", "\n").split("\n\n")
    return "\n\n".join([_shifted(b, 8760) for b in blocks[:5]] + [_shifted(b, -1170) for b in blocks[5:]])


# --- the machine's tsubasa ------------------------------------------------------------------------------------- #

def test_the_machines_tsubasa_is_never_found_by_connects_tests(tmp_path, monkeypatch):
    # a tsubasa on PATH, as a developer's `pip install tsubasa-sync` puts one (red before: found and run)
    folder = tmp_path / "bin"
    folder.mkdir()
    exe = folder / ("tsubasa.bat" if os.name == "nt" else "tsubasa")
    exe.write_text("@echo off\n" if os.name == "nt" else "#!/bin/sh\n", encoding="utf-8")
    os.chmod(exe, 0o755)
    monkeypatch.setenv("PATH", str(folder) + os.pathsep + os.environ.get("PATH", ""))
    assert fit_check.find_tsubasa() is None
    assert fit_check.fit(None, str(tmp_path / "a.mkv"), str(tmp_path / "a.srt"))[2] == fit_check.NO_CHECKER


# --- fit_check.retime -------------------------------------------------------------------------------------------- #

def test_part_way_is_only_that_reason():
    assert fit_check.part_way(TWO_SEGMENTS) and fit_check.part_way(fit_check.PART_WAY.format(media="audio"))
    for other in (fit_check.NO_CHECKER, "tsubasa gave no answer, so no cards.", None, "",
                  "Not timed to its video (refused), so no cards."):
        assert not fit_check.part_way(other), other


class Tsubasa:
    """tsubasa stood in for at `fit_check._run`: what it was asked, and what it answers — by default it writes the
    two-part re-timed copy under `--out` (mirrored a folder down, as tsubasa does) and says where."""

    def __init__(self, monkeypatch, answer=None, where=None, text=None):
        self.calls, self.answer, self.where, self.text = [], answer, where, text
        monkeypatch.setattr(fit_check, "find_tsubasa", lambda: "tsubasa")
        monkeypatch.setattr(fit_check, "_run", self.run)

    def run(self, command, timeout):
        self.calls.append(command)
        out = command[command.index("--out") + 1]
        sub = command[command.index("--pair") + 2]
        with open(sub, encoding="utf-8", newline="") as f:
            text = self.text if self.text is not None else _two_parts(f.read())
        path = self.where or os.path.join(out, "Show", os.path.basename(sub))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        answer = self.answer if self.answer is not None else {"outcome": "CONFIDENT", "segments": [[0, 8.76],
                                                                                                    [21.0, -1.17]]}
        return json.dumps(dict(answer, output_path=path)).encode("utf-8")


@pytest.fixture
def copy(tmp_path):
    shutil.copyfile(SOURCE, tmp_path / "ep01.ja.srt")
    return str(tmp_path / "ep01.ja.srt")


def test_retime_writes_only_under_its_folder_never_a_dry_run_and_records_nothing(tmp_path, monkeypatch, copy):
    ts = Tsubasa(monkeypatch)
    out = tmp_path / "runs" / "j1" / "retimed"
    out.mkdir(parents=True)
    (out / "stale.srt").write_text("left from before", encoding="utf-8")
    made = fit_check.retime("video.mkv", copy, str(out))
    assert made == (os.path.join(str(out), "Show", "ep01.ja.srt"), 0) and os.path.isfile(made.path)
    [command] = ts.calls
    assert command[:4] == ["tsubasa", "--pair", "video.mkv", copy] and "--dry-run" not in command
    assert "--no-results" in command and command[command.index("--out") + 1] == str(out)
    assert not (out / "stale.srt").exists(), "its folder emptied first: never an old file taken for its answer"


@pytest.mark.parametrize("answer", [{"outcome": "REFUSED", "segments": []}, {"outcome": "ERROR"},
                                    {"outcome": "CONFIDENT", "write_failed": "the folder refused it"}])
def test_a_refusal_an_error_or_a_failed_write_is_no_copy(tmp_path, monkeypatch, copy, answer):
    Tsubasa(monkeypatch, answer=answer)
    assert fit_check.retime("video.mkv", copy, str(tmp_path / "out")) is None


def test_a_file_it_says_it_wrote_outside_its_folder_is_never_taken(tmp_path, monkeypatch, copy):
    Tsubasa(monkeypatch, where=str(tmp_path / "elsewhere" / "ep01.ja.srt"))
    assert fit_check.retime("video.mkv", copy, str(tmp_path / "out")) is None


def test_no_tsubasa_no_answer_or_not_a_text_subtitle_is_no_copy(tmp_path, monkeypatch, copy):
    assert fit_check.retime("video.mkv", copy, str(tmp_path / "out")) is None, "none on this PC (the guard)"

    def slow(command, timeout):
        raise subprocess.TimeoutExpired(command, timeout)
    monkeypatch.setattr(fit_check, "find_tsubasa", lambda: "tsubasa")
    monkeypatch.setattr(fit_check, "_run", slow)
    assert fit_check.retime("video.mkv", copy, str(tmp_path / "out")) == fit_check.RETRY, "no answer: not now"
    ts = Tsubasa(monkeypatch)
    text = tmp_path / "ep01.txt"
    text.write_text(_source_text(), encoding="utf-8")
    assert fit_check.retime("video.mkv", str(text), str(tmp_path / "out")) is None and ts.calls == []


# --- Steps.retime: the copy's place, S5's rule ---------------------------------------------------------------------- #

@pytest.fixture
def library(tmp_path, monkeypatch):
    """A language's data folder with one library copy (the source's own bytes) -> (data folder, the copy)."""
    data = tmp_path / "data" / "ja"
    show = data / "Library" / "Hoshikuzu Station"
    show.mkdir(parents=True)
    shutil.copyfile(SOURCE, show / os.path.basename(SOURCE))
    import app.path_utils as pu
    monkeypatch.setattr(pu, "get_data_path", lambda language=None: str(data))
    return str(data), str(show / os.path.basename(SOURCE))


def _steps(tmp_path, monkeypatch):
    steps = runner.Steps({})
    monkeypatch.setattr(steps, "run_dir", lambda job: str(tmp_path / "connect" / "runs" / str(job["id"])))
    return steps


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def test_the_retimed_copy_takes_the_copys_place_the_old_one_in_the_trash(tmp_path, monkeypatch, library):
    data, full = library
    before = _bytes(full)
    Tsubasa(monkeypatch)
    assert _steps(tmp_path, monkeypatch).retime("ja", {"id": 7}, "video.mkv", full) is True
    assert _bytes(full).decode("utf-8") == _two_parts(before.decode("utf-8")), "every part its own shift"
    trash = os.listdir(os.path.join(data, ".trash"))
    assert len(trash) == 1 and _bytes(os.path.join(data, ".trash", trash[0])) == before, "the old copy kept whole"
    assert not os.path.exists(full + ".part")
    assert not os.path.exists(tmp_path / "connect" / "runs" / "7" / runner.RETIMED_FOLDER), "its run folder tidied"


def test_a_retimed_copy_with_other_lines_is_never_written(tmp_path, monkeypatch, library):
    data, full = library
    before = _bytes(full)
    other = _two_parts(before.decode("utf-8")).replace("次の列車は、月の裏側行きでございます。", "次の列車は、火星行きでございます。")
    Tsubasa(monkeypatch, text=other)
    assert _steps(tmp_path, monkeypatch).retime("ja", {"id": 7}, "video.mkv", full) is False
    assert _bytes(full) == before and not os.path.exists(os.path.join(data, ".trash"))


def test_a_file_outside_library_is_never_handed_to_tsubasa(tmp_path, monkeypatch, library):
    data, _full = library
    ts = Tsubasa(monkeypatch)
    loose = os.path.join(data, "HighPriority", "ep01.ja.srt")          # a 2.x tier folder's file
    os.makedirs(os.path.dirname(loose))
    shutil.copyfile(SOURCE, loose)
    hato = str(tmp_path / "Hato" / "ep01.ja.srt")                      # hato's own file, elsewhere
    os.makedirs(os.path.dirname(hato))
    shutil.copyfile(SOURCE, hato)
    steps = _steps(tmp_path, monkeypatch)
    for path in (loose, hato):
        before = _bytes(path)
        assert steps.retime("ja", {"id": 7}, "video.mkv", path) is False and _bytes(path) == before, path
    assert ts.calls == []


def test_a_copy_held_open_stays_as_it_was_with_no_trash_copy(tmp_path, monkeypatch, library):
    data, full = library
    before = _bytes(full)
    Tsubasa(monkeypatch)

    def held(src, dst):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")
    monkeypatch.setattr(os, "replace", held)
    assert _steps(tmp_path, monkeypatch).retime("ja", {"id": 7}, "video.mkv", full) is False
    assert _bytes(full) == before and not os.path.exists(full + ".part")
    assert os.listdir(os.path.join(data, ".trash")) == [], "no trash copy of a copy never replaced"


# --- the loop ---------------------------------------------------------------------------------------------------- #

class RetimeSteps(Steps):
    """`Steps` (real subtitle files, tsubasa by file) whose `retime` re-times the copy in place, as `Steps.retime`
    does, and tsubasa then answers one segment for it (`works`: False — no re-timed copy; `still`: it still changes
    part-way)."""

    def __init__(self, *a, works=True, still=False, **kw):
        super().__init__(*a, **kw)
        self.retimed_copies, self.works, self.still = [], works, still

    def retime(self, lang, job, video, copy):
        self.retimed_copies.append(copy)
        if not self.works:
            return False
        with open(copy, encoding="utf-8", newline="") as f:
            text = _two_parts(f.read())
        with open(copy, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if not self.still:
            self.answers[copy] = (fit_check.TIMED, 0.0)
        return True


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "ledger.sqlite")


@pytest.fixture
def episode(tmp_path):
    """The library's copy (the source's own bytes, CRLF) and a folder holding its video -> (copy, video)."""
    library = tmp_path / "data" / "ja" / "Library" / "Hoshikuzu Station"
    library.mkdir(parents=True)
    copy = library / os.path.basename(SOURCE)
    shutil.copyfile(SOURCE, copy)
    videos = tmp_path / "videos" / "Hoshikuzu Station"
    videos.mkdir(parents=True)
    video = videos / VIDEO
    video.write_bytes(b"\x1aE\xdf\xa3")
    return str(copy), str(video)


def test_mattias_part_way_episode_is_retimed_once_and_mined(tmp_path, path, episode):
    copy, video = episode
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video)
    _run(steps, path)
    job, picked = _job(path)
    assert steps.retimed_copies == [copy]
    assert job["state"] == "done" and picked["file"] == copy and picked["offset"] == 0.0
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1]) and _needs(path, listed=False) == []
    assert [e[2] for e in steps.log if e[0] == "fit" and len(e) == 3] == [copy, copy], "checked again, the new copy"


def test_a_retime_that_fails_is_named_and_never_asked_again_at_the_next_start(tmp_path, path, episode):
    copy, video = episode
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video, works=False)
    _run(steps, path)
    assert len(_needs(path)) == 1 and steps.anki.words() == []
    again = RetimeSteps(str(tmp_path), _plan(), copy, video, works=False)
    _run(again, path)
    assert steps.retimed_copies == [copy] and again.retimed_copies == [], "once a job"


def test_a_copy_still_part_way_after_its_retime_is_named_and_never_retimed_again(tmp_path, path, episode):
    copy, video = episode
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video, still=True)
    _run(steps, path)
    assert steps.retimed_copies == [copy] and len(_needs(path)) == 1 and steps.anki.words() == []


def test_only_part_way_is_retimed(tmp_path, path, episode):
    copy, video = episode
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video)
    steps.fit = lambda lang, job, pairing, v, s: (fit_check.NOT_TIMED, "tsubasa",
                                                  "Not timed to its video (refused), so no cards.", 0.0)
    _run(steps, path)
    assert steps.retimed_copies == [] and len(_needs(path)) == 1


def test_the_learners_own_fix_beside_the_video_wins_and_nothing_is_written(tmp_path, path, episode):
    copy, video = episode
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    before = open(copy, "rb").read()
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video, answers={fixed: (fit_check.TIMED, -1.5)})
    _run(steps, path)
    _job_, picked = _job(path)
    assert steps.retimed_copies == [] and picked["file"] == fixed and open(copy, "rb").read() == before


def test_one_beside_not_timed_either_then_the_copy_is_retimed(tmp_path, path, episode):
    copy, video = episode
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))       # tsubasa: two segments for it too
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video)
    _run(steps, path)
    job, picked = _job(path)
    assert [e[2] for e in steps.log if e[0] == "fit" and len(e) == 3] == [copy, fixed, copy]
    assert steps.retimed_copies == [copy] and job["state"] == "done" and picked["file"] == copy


def test_check_again_lets_tsubasa_retime_once_more(tmp_path, path, episode):
    copy, video = episode
    _run(RetimeSteps(str(tmp_path), _plan(), copy, video, works=False), path)
    assert actions.check_again("ja", 1, path=path) is True
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video)
    _run(steps, path)
    assert steps.retimed_copies == [copy] and _job(path)[0]["state"] == "done"


def test_the_retime_spends_no_repick(tmp_path, path, episode):
    # with the switch to it, two real changes after still mine (as the file beside the video, finding 7)
    copy, video = episode
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video)
    real, changed = steps.mine, []

    def mine(lang, job, picked, words, attempt):
        if len(changed) < 2:
            changed.append(1)
            raise runner.Repick()
        return real(lang, job, picked, words, attempt)
    steps.mine = mine
    _run(steps, path)
    assert _job(path)[0]["state"] == "done" and len(steps.anki.words()) == 3


def test_your_stop_during_the_retime_stops_the_job_and_gives_the_retime_back(tmp_path, path, episode):
    copy, video = episode
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video)

    def stopped(lang, job, v, c):
        raise stopping.Stopped()
    steps.retime = stopped
    _run(steps, path)
    job, _picked = _job(path)
    assert job["state"] == "waiting" and job["reason"] == runner.STOPPED_BY_YOU and steps.anki.words() == []
    with Ledger(path) as ledger:
        assert ledger.conn.execute("SELECT 1 FROM meta WHERE key LIKE 'retimed:%'").fetchone() is None, \
            "the one re-time is still the job's when it goes on (adversary 4)"


# --- the adversary's findings (register: TheForge 3.0 tracks/pipeline/reviews/michi-nt2-register.md) ----------- #

def _cut(text, n):
    """The subtitle with its `n`th cue left out (a stretch the broadcast doesn't hold)."""
    blocks = text.replace("\r\n", "\n").split("\n\n")
    return "\n\n".join(blocks[:n] + blocks[n + 1:])


def test_b1_cues_tsubasa_says_it_dropped_are_the_same_subtitle_and_no_other_is(tmp_path, monkeypatch, library):
    # a cut broadcast: tsubasa leaves out the cue in the stretch the video doesn't hold, and says so
    data, full = library
    before = _bytes(full).decode("utf-8")
    cut = _cut(_two_parts(before), 3)
    Tsubasa(monkeypatch, text=cut, answer={"outcome": "CONFIDENT", "segments": [[0, 8.76], [21.0, -1.17]],
                                           "dropped_in_gap": 1, "dropped_before_zero": 0})
    assert _steps(tmp_path, monkeypatch).retime("ja", {"id": 7}, "video.mkv", full) is True
    assert _bytes(full).decode("utf-8") == cut
    assert not runner.same_subtitle(full, SOURCE, "ja", 1), "it can't have gained a line"


def test_b1_a_cue_missing_that_tsubasa_never_said_it_dropped_is_never_written(tmp_path, monkeypatch, library):
    data, full = library
    before = _bytes(full)
    Tsubasa(monkeypatch, text=_cut(_two_parts(before.decode("utf-8")), 3))      # says nothing dropped
    assert _steps(tmp_path, monkeypatch).retime("ja", {"id": 7}, "video.mkv", full) is False
    assert _bytes(full) == before and not os.path.exists(os.path.join(data, ".trash"))


def test_b2_the_library_copying_its_original_in_meanwhile_wins(tmp_path, monkeypatch, library):
    # S5 copies a changed original over the copy while tsubasa re-times the old one: never replaced by the old text
    data, full = library
    ts = Tsubasa(monkeypatch)
    real = ts.run
    newer = _shifted(_bytes(full).decode("utf-8"), 300)

    def meanwhile(command, timeout):
        out = real(command, timeout)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(newer)
        return out
    monkeypatch.setattr(fit_check, "_run", meanwhile)
    assert _steps(tmp_path, monkeypatch).retime("ja", {"id": 7}, "video.mkv", full) is None, "not now: checked next"
    assert _bytes(full).decode("utf-8") == newer and not os.path.exists(os.path.join(data, ".trash"))
    assert not os.path.exists(full + runner.RETIME_PART) and runner.RETIME_PART != ".part"


def test_b4_no_answer_from_tsubasa_gives_the_retime_back_for_the_next_start(tmp_path, path, episode):
    copy, video = episode
    steps = RetimeSteps(str(tmp_path), _plan(), copy, video)
    steps.retime = lambda lang, job, v, c: (steps.retimed_copies.append(c), None)[1]
    _run(steps, path)
    assert len(_needs(path)) == 1
    again = RetimeSteps(str(tmp_path), _plan(), copy, video)
    _run(again, path)
    assert steps.retimed_copies == [copy] and again.retimed_copies == [copy] and _job(path)[0]["state"] == "done"


def test_b5_no_test_anywhere_sees_the_machines_tsubasa():
    # the guard lives in tests/conftest.py: Connect's tests outside tests/connect build a real Steps too
    import shutil
    assert shutil.which("tsubasa") is None and shutil.which("tsubasa.exe") is None
