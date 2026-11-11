"""Mattias's field report (3.0.2, 2026-11-11, rezeroS04E16): a subtitle whose timing shifts part-way through its video
(a Netflix subtitle on an AT-X broadcast: +8.8 s up to 86 s, then -1.2 s) was named *Not timed* and never looked at
again — re-syncing the subtitle beside the video changed nothing, since Connect checks its library copy.

Now tsubasa, sure of the timing but in two segments or more, is asked for a retimed copy written in the job's own
run folder (`fit_check.retime`, `--out`): never the library's copy, the original or the video's folder. The words'
lines move to the copy's cues (`fit_check.moved_lines`: the same cues, in order, only shifted) and the episode mines
from it with no offset. A copy that doesn't hold the same lines, a refusal, or no tsubasa → *Not timed*, as before.

What a wrong answer would cost: cards cut at the wrong line's audio (a word placed at a guessed time), or a file
written beside the user's own. The program is a stand-in (`run=`); Anki and Anki Miner are `FakeSteps`'.
"""
import json
import os
import subprocess

import pytest

from app.connect import fit_check, runner, status
from app.connect.ledger import Ledger
from tests.connect.fake_steps import FakeSteps
from tests.connect_helpers import tsubasa_answer

VIDEO = "C:/Video/上層部の話 01.mkv"
BEFORE = [(10.0, 12.5, "家に帰った"), (11.0, 13.5, "行こう"), (100.0, 102.0, "まだだ")]
AFTER = [(18.76, 21.26, "家に帰った"), (19.76, 22.26, "行こう"), (98.83, 100.83, "まだだ")]


def _srt(path, cues):
    def stamp(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
    with open(path, "w", encoding="utf-8") as f:
        for n, (start, end, text) in enumerate(cues, 1):
            f.write(f"{n}\n{stamp(start)} --> {stamp(end)}\n{text}\n\n")
    return str(path)


def _writer(cues, outcome="CONFIDENT", name="ep.srt", where=None):
    """A tsubasa stand-in that writes its retimed copy under `--out` (or `where`) and answers as --json does."""
    def run(command, **kw):
        out = where or command[command.index("--out") + 1]
        path = _srt(os.path.join(out, name), cues)
        answer = tsubasa_answer(outcome, segments=((None, 8.76), (86.35, -1.168)), output_path=path,
                                write_failed=False)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(answer) + "\n")
    return run


def test_two_segments_is_the_part_way_reason_and_nothing_else_is():
    run = lambda command, **kw: subprocess.CompletedProcess(  # noqa: E731
        command, 0, stdout=json.dumps(tsubasa_answer(segments=((None, 0.0), (90.0, 3.0)))))
    got = fit_check.fit(None, VIDEO, "C:/Subs/a.srt", tsubasa="tsubasa", run=run)
    assert got[0] == fit_check.NOT_TIMED and fit_check.part_way(got[2])
    assert not fit_check.part_way("Not timed to its video (refused), so no cards.")
    assert not fit_check.part_way(None)


def test_retime_writes_only_in_its_own_folder_and_answers_the_copy(tmp_path):
    sub = _srt(tmp_path / "library.srt", BEFORE)
    out = tmp_path / "run" / fit_check.RETIMED
    seen = []

    def run(command, **kw):
        seen.append(command)
        return _writer(AFTER)(command, **kw)
    path = fit_check.retime(VIDEO, sub, str(out), tsubasa="tsubasa", run=run)
    assert path == os.path.join(str(out), "ep.srt") and os.path.isfile(path)
    assert "--dry-run" not in seen[0] and seen[0][seen[0].index("--out") + 1] == str(out)
    assert "--no-results" in seen[0], "tsubasa's own record of what it synced is never touched"
    with open(sub, encoding="utf-8") as f:
        assert "00:00:10,000" in f.read(), "the library's copy is unchanged"


def test_retime_refuses_a_copy_outside_its_folder_a_refusal_and_a_non_srt(tmp_path):
    sub = _srt(tmp_path / "library.srt", BEFORE)
    elsewhere = tmp_path / "beside-video"
    elsewhere.mkdir()
    out = str(tmp_path / "run" / fit_check.RETIMED)
    assert fit_check.retime(VIDEO, sub, out, tsubasa="t", run=_writer(AFTER, where=str(elsewhere))) is None
    assert fit_check.retime(VIDEO, sub, out, tsubasa="t", run=_writer(AFTER, outcome="REFUSED")) is None
    assert fit_check.retime(VIDEO, str(tmp_path / "a.ass"), out, tsubasa="t", run=_writer(AFTER)) is None
    assert fit_check.retime(VIDEO, sub, out, tsubasa="") is None


def test_moved_lines_take_the_same_cue_in_the_copy_or_none_at_all():
    words = [{"word": "帰る", "line_start": 10.0, "line_end": 12.5}, {"word": "まだ", "line_start": 100.0,
                                                                      "line_end": 102.0}]
    moved = fit_check.moved_lines(words, BEFORE, AFTER)
    assert [(w["line_start"], w["line_end"]) for w in moved] == [(18.76, 21.26), (98.83, 100.83)]
    assert moved[0]["word"] == "帰る"
    assert fit_check.moved_lines([{"word": "x", "line_start": 55.0}], BEFORE, AFTER) is None, "no line there"
    assert fit_check.moved_lines(words, BEFORE, AFTER[:2]) is None, "another number of cues"
    assert fit_check.moved_lines(words, BEFORE, AFTER[:2] + [(98.83, 100.83, "別の台詞")]) is None, "other text"


class PartWay(FakeSteps):
    """FakeSteps whose fit check answers two segments, and whose retime answers `retimed` (None: it can't)."""

    retimed = True

    def fit(self, lang, job, pairing, video, subtitle):
        self.log.append(("fit", job["item_id"]))
        return fit_check.NOT_TIMED, "tsubasa", fit_check.PART_WAY.format(media="video"), 0.0

    def retime(self, lang, job, picked):
        self.log.append(("retime", job["item_id"]))
        if not self.retimed:
            return None
        words = [dict(w, line_start=w["line_start"] + 8.76) for w in picked["words"]]
        return dict(picked, subtitle="/runs/retimed/ep.srt", retimed="/runs/retimed/ep.srt", words=words, offset=0.0)


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _look(steps, ledger):
    return runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)


def test_an_episode_whose_timing_shifts_part_way_mines_from_the_retimed_copy(tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(status, "running", lambda: True)
    with ledger.transaction():
        job_id = ledger.queue("ja", 1, "user", None, store_id="store-1")
    steps = PartWay(str(tmp_path), {"line": {"ja": [1]}})
    _look(steps, ledger)
    job = ledger.job_by_id(job_id)
    assert job["state"] == "done", job
    assert not [n for n in ledger.needs("ja") if n["kind"] == "not-timed"]
    picked = ledger.picked(job_id)
    assert picked["subtitle"] == picked["retimed"] == "/runs/retimed/ep.srt" and picked["offset"] == 0.0
    assert picked["file"] == "/library/1.ja.srt", "the library's copy stays the pick's own"
    assert [w["line_start"] for w in picked["words"]] == [10.0 + n + 8.76 for n in range(len(picked["words"]))], \
        "the words' lines moved with the copy"


def test_a_retime_that_fails_leaves_the_episode_not_timed_as_before(tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(status, "running", lambda: True)
    with ledger.transaction():
        job_id = ledger.queue("ja", 1, "user", None, store_id="store-1")
    steps = PartWay(str(tmp_path), {"line": {"ja": [1]}})
    steps.retimed = False
    _look(steps, ledger)
    needs = [n for n in ledger.needs("ja") if n["kind"] == "not-timed"]
    assert len(needs) == 1 and "changes part-way" in needs[0]["say"], needs
    assert ledger.job_by_id(job_id)["state"] == "waiting"
    assert not any(e[0] == "mine" for e in steps.log)
