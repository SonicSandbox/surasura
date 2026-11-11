"""Mattias's field report (3.0.2, 2026-11-11, rezeroS04E16): a subtitle whose timing shifts part-way through its video
(a Netflix subtitle on an AT-X broadcast: +8.8 s up to 86 s, then -1.2 s) was named *Not timed* and never looked at
again — re-syncing the subtitle beside the video changed nothing, since Connect checks its library copy.

Now tsubasa, sure of the timing but in two segments or more, is asked for a retimed copy (`fit_check.retime`, written
under the job's run folder with `--out`), and when it holds the same lines (`fit_check.same_lines`) it takes the
library copy's place for good (`Steps.retime`: the old copy to `.trash` first, as S5 does). The episode is then picked
again from it and checked again — once a job: a copy that still shifts part-way is named not timed, as before. A copy
outside `Library` (a hato / 2.x file), a refusal, or no tsubasa → nothing written, *Not timed* as before.

What a wrong answer would cost: the user's library subtitle replaced by a file that isn't it (other lines), lost (no
trash), or written outside Surasura's library; or a retime loop. tsubasa is a stand-in (`run=`); Anki and Anki Miner
are `FakeSteps`'.
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
        assert "00:00:10,000" in f.read(), "tsubasa never writes the copy it reads"


def test_retime_refuses_a_copy_outside_its_folder_a_refusal_and_a_non_srt(tmp_path):
    sub = _srt(tmp_path / "library.srt", BEFORE)
    elsewhere = tmp_path / "beside-video"
    elsewhere.mkdir()
    out = str(tmp_path / "run" / fit_check.RETIMED)
    assert fit_check.retime(VIDEO, sub, out, tsubasa="t", run=_writer(AFTER, where=str(elsewhere))) is None
    assert fit_check.retime(VIDEO, sub, out, tsubasa="t", run=_writer(AFTER, outcome="REFUSED")) is None
    assert fit_check.retime(VIDEO, str(tmp_path / "a.ass"), out, tsubasa="t", run=_writer(AFTER)) is None
    assert fit_check.retime(VIDEO, sub, out, tsubasa="") is None


def test_same_lines_only_for_the_same_cues_moved_in_time():
    assert fit_check.same_lines(BEFORE, AFTER)
    assert not fit_check.same_lines(BEFORE, AFTER[:2]), "another number of cues"
    assert not fit_check.same_lines(BEFORE, AFTER[:2] + [(98.83, 100.83, "別の台詞")]), "other text"
    assert not fit_check.same_lines([], [])


# --------------------------------------------------------------------------- #
# Steps.retime: the library copy replaced for good
# --------------------------------------------------------------------------- #
@pytest.fixture
def library(tmp_path, monkeypatch):
    """A language data folder with one library subtitle; Connect's run folders under tmp."""
    data = tmp_path / "data" / "ja"
    (data / "Library" / "show").mkdir(parents=True)
    monkeypatch.setattr("app.path_utils.get_data_path", lambda language=None: str(data))
    monkeypatch.setattr(runner.Steps, "run_dir", lambda self, job: str(tmp_path / "runs" / str(job["id"])))
    return data, _srt(data / "Library" / "show" / "ep01.srt", BEFORE)


def _retime_with(monkeypatch, cues, **kw):
    real = fit_check.retime
    monkeypatch.setattr(fit_check, "retime", lambda v, s, out: real(v, s, out, tsubasa="t", run=_writer(cues, **kw)))


def test_the_retimed_copy_takes_the_library_copys_place_and_the_old_one_goes_to_the_trash(library, monkeypatch):
    data, sub = library
    _retime_with(monkeypatch, AFTER)
    steps = runner.Steps({})
    assert steps.retime("ja", {"id": 7}, {"video": VIDEO, "file": sub}) is True
    from app.connect import lineup
    assert lineup.srt_cues(sub) == lineup.srt_cues(_srt(data / "expected.srt", AFTER)), "the library copy is retimed"
    trashed = os.listdir(data / ".trash")
    assert len(trashed) == 1 and trashed[0].startswith("ep01_") and trashed[0].endswith("_untimed.srt")
    assert lineup.srt_cues(str(data / ".trash" / trashed[0]))[0][0] == 10.0, "the old copy kept in the trash"
    assert not os.path.exists(sub + ".part")
    assert not os.path.exists(os.path.join(steps.run_dir({"id": 7}), fit_check.RETIMED)), "the run folder tidied"


def test_a_copy_with_other_lines_or_outside_the_library_is_never_written(library, tmp_path, monkeypatch):
    data, sub = library
    _retime_with(monkeypatch, AFTER[:2])
    steps = runner.Steps({})
    assert steps.retime("ja", {"id": 7}, {"video": VIDEO, "file": sub}) is False
    from app.connect import lineup
    assert lineup.srt_cues(sub)[0][0] == 10.0 and not (data / ".trash").exists()
    _retime_with(monkeypatch, AFTER)
    (tmp_path / "hato").mkdir()
    outside = _srt(tmp_path / "hato" / "ep01.srt", BEFORE)
    assert steps.retime("ja", {"id": 7}, {"video": VIDEO, "file": outside}) is False
    assert lineup.srt_cues(outside)[0][0] == 10.0, "a hato / 2.x file outside Library is never rewritten"


# --------------------------------------------------------------------------- #
# The runner: retimed once, picked again, mined
# --------------------------------------------------------------------------- #
class PartWay(FakeSteps):
    """FakeSteps whose fit check answers two segments until its library copy is retimed (`fixed`), then one; `can`:
    whether the retime succeeds; `stays`: the retimed copy still shifts part-way."""

    can, stays, fixed = True, False, False

    def fit(self, lang, job, pairing, video, subtitle):
        self.log.append(("fit", job["item_id"]))
        if self.fixed and not self.stays:
            return fit_check.TIMED, "tsubasa", None, 0.0
        return fit_check.NOT_TIMED, "tsubasa", fit_check.PART_WAY.format(media="video"), 0.0

    def retime(self, lang, job, picked):
        self.log.append(("retime", job["item_id"]))
        self.fixed = self.can
        return self.can


@pytest.fixture
def ledger(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as led:
        yield led


def _look(steps, ledger):
    return runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)


def _job(ledger):
    with ledger.transaction():
        return ledger.queue("ja", 1, "user", None, store_id="store-1")


def test_an_episode_whose_timing_shifts_part_way_is_retimed_picked_again_and_mined(tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(status, "running", lambda: True)
    job_id = _job(ledger)
    steps = PartWay(str(tmp_path), {"line": {"ja": [1]}})
    _look(steps, ledger)
    assert ledger.job_by_id(job_id)["state"] == "done"
    assert not [n for n in ledger.needs("ja") if n["kind"] == "not-timed"]
    order = [e[0] for e in steps.log if e[0] in ("pick", "fit", "retime", "mine")]
    assert order[:5] == ["pick", "fit", "retime", "pick", "fit"] and "mine" in order, order
    assert ledger.picked(job_id)["offset"] == 0.0


def test_a_retime_that_fails_leaves_the_episode_not_timed_as_before(tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(status, "running", lambda: True)
    job_id = _job(ledger)
    steps = PartWay(str(tmp_path), {"line": {"ja": [1]}})
    steps.can = False
    _look(steps, ledger)
    needs = [n for n in ledger.needs("ja") if n["kind"] == "not-timed"]
    assert len(needs) == 1 and "changes part-way" in needs[0]["say"], needs
    assert ledger.job_by_id(job_id)["state"] == "waiting"
    assert not any(e[0] == "mine" for e in steps.log)


def test_a_copy_that_still_shifts_after_its_retime_is_never_retimed_again(tmp_path, ledger, monkeypatch):
    monkeypatch.setattr(status, "running", lambda: True)
    job_id = _job(ledger)
    steps = PartWay(str(tmp_path), {"line": {"ja": [1]}})
    steps.stays = True
    _look(steps, ledger)
    _look(steps, ledger)
    assert [e[0] for e in steps.log].count("retime") == 1, steps.log
    assert [n for n in ledger.needs("ja") if n["kind"] == "not-timed"]
    assert ledger.job_by_id(job_id)["state"] == "waiting"
