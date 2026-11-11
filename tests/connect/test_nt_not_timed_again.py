"""Michi-NT (Mattias, problem reports #XP44T6 on 3.0.1 and #7J3960 on 3.0.2): Re:Zero S04E16 stayed *Not timed* after
he fixed its subtitle with tsubasa himself, and nothing in the window let him ask Surasura to look again.

The cause: Connect's fit check only ever reads the library's own copy of the subtitle (`Library/<show>/…ja[cc].srt`
in the data folder), and only at its next start. tsubasa's `--pair VIDEO SUB` writes the subtitle it re-timed BESIDE
THE VIDEO, under the video's name (its default `rename`: what a player loads), so the copy Connect checks never
changed: every start answered "two segments" again (cli.log 11:15 and 15:25). His entry dismissed, the row was a plain
*Not timed* with no press and no *Needs you* card (`status.skipped` [254]).

What this holds:
- the copy not timed → the same subtitle re-timed beside its video (`runner.retimed_beside`: named after the video,
  no language mark or the library's, the very lines of the copy in other bytes) is checked in its place; timed → its
  cards are picked from it and cut by its own shift; not timed either → the entry as before, and the next check
  starts from the copy again;
- *Check again* (`actions.check_again`): the entry fixed (a dismissed one too) and the job queued — a fix is seen;
  still not timed → the entry is back in *Needs you* (its *Mine anyway*);
- a running Connect lets a parked *Not timed* job go again once its library copy changed (`_copy_changed`).

What a wrong answer would cost: a learner who did exactly the right thing (re-timed the subtitle) told for ever that
it isn't timed, with no button; or the opposite — another release's subtitle (other lines) beside the video mined as
this episode's, or a subtitle beside the video never checked by tsubasa cutting cards at the wrong moments.

Real Japanese subtitles from `tests/Test Resources/ja/airing/` (CRLF), re-timed here as tsubasa would write them; the
loop against `FakeSteps`; a real ledger in the test's folder.
"""
import os
import re
import shutil

import pytest

from app.connect import actions, fit_check, runner, status
from app.connect.ledger import Ledger
from tests.connect.fake_steps import WORDS, FakeSteps

SOURCE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources", "ja", "airing",
                      "Hoshikuzu Station S01E01.ja.srt")
VIDEO = "[Hoshi] Hoshikuzu Station - 01 (1080p).mkv"
TWO_SEGMENTS = "Its timing changes part-way through the video, so no cards."


def _shifted(text, ms):
    """The subtitle's text with every time moved by `ms` (tsubasa's re-timed bytes: the same lines, other times)."""
    def move(m):
        h, mi, s, f = (int(x) for x in m.groups())
        t = max(0, ((h * 60 + mi) * 60 + s) * 1000 + f + ms)
        return f"{t // 3600000:02d}:{t // 60000 % 60:02d}:{t // 1000 % 60:02d},{t % 1000:03d}"
    return re.sub(r"(\d+):(\d{2}):(\d{2}),(\d{3})", move, text)


def _source_text():
    with open(SOURCE, encoding="utf-8", newline="") as f:
        return f.read()


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
    video.write_bytes(b"\x1aE\xdf\xa3")                 # a Matroska header's first bytes: never read here
    return str(copy), str(video)


def _beside(video, suffix, text, newline="\n"):
    """A subtitle beside `video`, named after it plus `suffix` (".ja.srt" is what tsubasa writes), holding `text`."""
    path = os.path.splitext(video)[0] + suffix
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text.replace("\r\n", "\n"))
    return path


# --- the look beside the video ---------------------------------------------------------------------------------- #

def test_the_subtitle_tsubasa_retimed_beside_its_video_is_found(episode):
    copy, video = episode
    # tsubasa's own output: the video's name, the language tag, LF where the copy has CRLF, every line 1.5 s later
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    assert runner.retimed_beside(video, copy, "ja") == fixed


def test_an_untagged_one_named_after_the_video_is_found_too(episode):
    copy, video = episode
    fixed = _beside(video, ".srt", _shifted(_source_text(), -800))
    assert runner.retimed_beside(video, copy, "ja") == fixed


def test_another_language_another_release_or_the_same_bytes_are_never_it(episode):
    copy, video = episode
    text = _source_text()
    _beside(video, ".en.srt", _shifted(text, 1500))                     # tagged English (whatever its lines)
    other = text.replace("次の列車は、月の裏側行きでございます。", "次の列車は、火星行きでございます。")
    _beside(video, ".ja[cc].srt", _shifted(other, 1500))                # another release: one line differs
    with open(os.path.splitext(video)[0] + ".jpn.srt", "wb") as f:     # the copy's very bytes (nothing re-timed)
        with open(copy, "rb") as g:
            f.write(g.read())
    assert runner.retimed_beside(video, copy, "ja") is None


def test_one_named_after_another_video_is_never_it(episode):
    copy, video = episode
    _beside(video.replace(" - 01 ", " - 02 "), ".ja.srt", _shifted(_source_text(), 1500))
    assert runner.retimed_beside(video, copy, "ja") is None


def test_of_two_the_newest_is_taken(episode):
    copy, video = episode
    old = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    new = _beside(video, ".ja.synced.srt", _shifted(_source_text(), 1200))
    os.utime(old, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    assert runner.retimed_beside(video, copy, "ja") == new


def test_a_folder_that_cant_be_listed_an_empty_copy_or_an_audio_file_has_none(episode, tmp_path):
    copy, video = episode
    _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    assert runner.retimed_beside(str(tmp_path / "offline" / VIDEO), copy, "ja") is None
    empty = tmp_path / "empty.ja.srt"
    empty.write_bytes(b"")
    assert runner.retimed_beside(video, str(empty), "ja") is None, "no lines: nothing to be the same subtitle as"
    audio = os.path.splitext(video)[0] + ".m4a"
    open(audio, "wb").close()
    assert runner.retimed_beside(audio, copy, "ja") is None, "an audio file's subtitle: tsubasa has no reference"


# --- the loop --------------------------------------------------------------------------------------------------- #

class Steps(FakeSteps):
    """FakeSteps whose item 1 is a real subtitle: its pick reads the file it is given (the copy, unless `subtitle`),
    tsubasa answers by file (`answers`: {path: (verdict, offset)}; the copy two segments unless said), and the look
    beside its video is `runner.retimed_beside` itself."""

    def __init__(self, folder, plan, copy, video, answers=None):
        super().__init__(folder, plan)
        self.copy, self.real_video, self.answers = copy, video, dict(answers or {})
        self.plan.setdefault("videos", {})["1"] = video
        self.retimed_asked = 0

    def pick(self, lang, job, video, subtitle=None):
        got = super().pick(lang, job, video)
        if job["item_id"] == 1:
            got["file"] = subtitle or self.copy
            self.log.append(("picked-from", got["file"]))
        return got

    def fit(self, lang, job, pairing, video, subtitle):
        if job["item_id"] != 1:
            return super().fit(lang, job, pairing, video, subtitle)
        self.log.append(("fit", job["item_id"], subtitle))
        verdict, offset = self.answers.get(subtitle, (fit_check.NOT_TIMED, 0.0))
        return verdict, "tsubasa", None if verdict == fit_check.TIMED else TWO_SEGMENTS, offset

    def retimed(self, lang, job, video, subtitle):
        self.retimed_asked += 1
        return runner.retimed_beside(video, subtitle, lang)


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "ledger.sqlite")


def _plan():
    return {"line": {"ja": [1]}, "queue": {"ja": [1]}}


def _run(steps, path, **kw):
    with Ledger(path) as ledger:
        runner.run({}, ["ja"], steps=steps, ledger=ledger, sleep=kw.pop("sleep", lambda s: None),
                   looks=kw.pop("looks", 1))


def _needs(path, listed=True):
    with Ledger(path) as ledger:
        return [n for n in ledger.needs("ja", listed=listed) if n["kind"] == "not-timed"]


def _job(path):
    with Ledger(path) as ledger:
        job = ledger.job("ja", 1)
        return job, ledger.picked(job["id"]) or {}


def test_mattias_subtitle_fixed_beside_its_video_is_mined_with_its_own_shift(tmp_path, path, episode):
    # #XP44T6: the copy still drifts part-way (two segments); his tsubasa run wrote the fix beside the video
    copy, video = episode
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    steps = Steps(str(tmp_path), _plan(), copy, video, answers={fixed: (fit_check.TIMED, -1.5)})
    _run(steps, path)
    job, picked = _job(path)
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1]), "its cards made"
    assert job["state"] == "done" and picked["file"] == fixed and picked["beside"] == fixed
    assert picked["offset"] == -1.5, "cut by the shift tsubasa measured on the file it checked"
    assert [e[2] for e in steps.log if e[0] == "fit"] == [copy, fixed], "the copy first, then the one beside"
    assert ("picked-from", fixed) in steps.log, "its words and lines read from the file the cards are cut by"
    assert _needs(path, listed=False) == [], "nothing for you to do"


def test_nothing_beside_its_video_is_the_entry_as_before(tmp_path, path, episode):
    copy, video = episode
    steps = Steps(str(tmp_path), _plan(), copy, video)
    _run(steps, path)
    job, picked = _job(path)
    assert steps.anki.words() == [] and job["state"] == "waiting" and "beside" not in picked
    assert [n["say"] for n in _needs(path)] == [f"Example Show - 01: {TWO_SEGMENTS}"]


def test_the_one_beside_not_timed_either_is_the_entry_and_the_next_check_starts_from_the_copy(tmp_path, path,
                                                                                               episode):
    copy, video = episode
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    steps = Steps(str(tmp_path), _plan(), copy, video)          # tsubasa: two segments for both
    _run(steps, path)
    _job_, picked = _job(path)
    assert steps.anki.words() == [] and len(_needs(path)) == 1
    assert "beside" not in picked, "the next check starts from the copy: a fix of the copy itself is seen"
    steps = Steps(str(tmp_path), _plan(), copy, video, answers={copy: (fit_check.TIMED, 0.25)})
    _run(steps, path)                                           # the next start: the copy itself fixed meanwhile
    _job_, picked = _job(path)
    assert picked["file"] == copy and picked["offset"] == 0.25 and len(steps.anki.words()) == 3
    assert fixed not in [e[2] for e in steps.log if e[0] == "fit"], "the copy timed: nothing looked for beside"


def test_a_verdict_not_tsubasas_never_looks_beside_the_video(tmp_path, path, episode):
    # hato's own verdict, or nothing on this PC to check timing: no tsubasa answer to look past
    copy, video = episode
    _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    steps = Steps(str(tmp_path), _plan(), copy, video)
    steps.fit = lambda lang, job, pairing, v, s: (fit_check.NOT_TIMED, None, fit_check.NO_CHECKER, 0.0)
    _run(steps, path)
    assert steps.retimed_asked == 0 and steps.anki.words() == [] and len(_needs(path)) == 1


def test_a_copy_fixed_while_connect_runs_is_checked_again_in_that_run(tmp_path, path, episode):
    # Connect stays running for another episode (Anki Miner's window open: a 2-minute look); meanwhile the copy is
    # re-timed in place — the next look tries the parked episode again, never only at the next start
    copy, video = episode
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}}
    steps = Steps(str(tmp_path), plan, copy, video)
    real_mine = steps.mine

    def mine(lang, job, picked, words, attempt):
        if job["item_id"] == 2:
            raise runner.Wait(runner.ANKI_MINER_OPEN)       # a wait looked at again in 2 minutes
        return real_mine(lang, job, picked, words, attempt)
    steps.mine = mine

    def pause(_seconds):
        with open(copy, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(_shifted(_source_text(), 1500).replace("\r\n", "\n"))
        steps.answers[copy] = (fit_check.TIMED, 0.0)
    _run(steps, path, sleep=pause, looks=2)
    assert [e[2] for e in steps.log if e[0] == "fit" and len(e) == 3].count(copy) == 2, "checked again at look 2"
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1])


def test_a_parked_episode_whose_copy_didnt_change_stays_parked(tmp_path, path, episode):
    copy, video = episode
    plan = {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}}
    steps = Steps(str(tmp_path), plan, copy, video)
    steps.mine = lambda lang, job, picked, words, attempt: (_ for _ in ()).throw(runner.Wait(runner.ANKI_MINER_OPEN))
    _run(steps, path, looks=3)
    item1 = [e for e in steps.log if e[0] == "fit" and e[1] == 1]
    assert len(item1) == 1, "parked for the next start: never checked again each look, its copy unchanged"
    assert [e for e in steps.log if e[0] == "fit" and e[1] == 2], "(item 2 kept Connect looking)"


# --- *Check again* ---------------------------------------------------------------------------------------------- #

def test_check_again_on_a_dismissed_entry_checks_anew_and_brings_the_entry_back(tmp_path, path, episode):
    # #XP44T6's state: the entry dismissed (`status.skipped` [254]), no card in *Needs you*, no button on the row
    copy, video = episode
    _run(Steps(str(tmp_path), _plan(), copy, video), path)
    need = _needs(path)[0]
    with Ledger(path) as ledger:
        assert ledger.dismiss(need["id"])
        assert status._skipped(ledger.conn, "ja") == [1] and _needs(path) == []
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (f"fit_try:{need['job_id']}", "2"))
        ledger.conn.commit()
    assert actions.check_again("ja", 1, path=path) is True
    job, picked = _job(path)
    assert job["state"] == "queued" and job["reason"] is None and _needs(path, listed=False) == []
    with Ledger(path) as ledger:
        assert status._skipped(ledger.conn, "ja") == [], "no longer skipped: it waits for its check"
        assert ledger.conn.execute("SELECT 1 FROM meta WHERE key LIKE 'fit_try:%'").fetchone() is None
    steps = Steps(str(tmp_path), _plan(), copy, video)            # still two segments, nothing beside it
    _run(steps, path)
    back = _needs(path)
    assert len(back) == 1 and back[0]["dismissed_at"] is None and back[0]["seen_at"] is None, \
        "back in Needs you, counted: its Mine anyway within reach"
    assert actions.mine_anyway("ja", back[0]["id"], path=path) is True


def test_check_again_after_the_fix_mines_it(tmp_path, path, episode):
    copy, video = episode
    _run(Steps(str(tmp_path), _plan(), copy, video), path)
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))       # his tsubasa run, after the entry
    assert actions.check_again("ja", 1, path=path) is True
    steps = Steps(str(tmp_path), _plan(), copy, video, answers={fixed: (fit_check.TIMED, -1.5)})
    _run(steps, path)
    job, picked = _job(path)
    assert job["state"] == "done" and picked["file"] == fixed and len(steps.anki.words()) == 3


def test_check_again_writes_nothing_unless_an_episode_waits_on_its_timing(tmp_path, path, episode):
    assert actions.check_again("ja", 1, path=path) is False and not os.path.exists(path), "the window makes no ledger"
    copy, video = episode
    _run(Steps(str(tmp_path), _plan(), copy, video), path)
    before = _job(path)
    assert actions.check_again("zh", 1, path=path) is False, "another language's"
    assert actions.check_again("ja", 2, path=path) is False, "an item with no such entry"
    with Ledger(path) as ledger:
        ledger.set_state(before[0]["id"], "dropped", reason="left the top 20")
    assert actions.check_again("ja", 1, path=path) is False, "its job ended meanwhile"
    assert len(_needs(path)) == 1, "nothing written: the entry is the runner's to close"


# --- the adversary's findings (review register: TheForge 3.0 tracks/pipeline/reviews/michi-nt-register.md) ---------- #

def test_a2_the_file_beside_its_video_changed_between_two_batches_is_picked_and_checked_again(tmp_path, path,
                                                                                               episode):
    # a batch in doubt, tried again: meanwhile tsubasa ran again over the file beside the video — never cut by the
    # shift measured on the bytes it had before
    copy, video = episode
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    plan = dict(_plan(), crash_mid_batch=1)
    steps = Steps(str(tmp_path), plan, copy, video, answers={fixed: (fit_check.TIMED, -1.5)})
    touched = []

    def retime(n, job):
        if n == 0 and not touched:
            touched.append(1)
            _beside(video, ".ja.srt", _shifted(_source_text(), 1700))
            os.utime(fixed, ns=(1_800_000_000_000_000_000, 1_800_000_000_000_000_000))
            steps.answers[fixed] = (fit_check.TIMED, -1.7)
    steps.plan["on_word"] = retime                 # (FakeSteps keeps its own copy of the plan)
    _run(steps, path, looks=2)                     # (a batch in doubt is tried again at the next look)
    _job_, picked = _job(path)
    assert [e[2] for e in steps.log if e[0] == "fit" and len(e) == 3].count(fixed) == 2, "checked again"
    assert picked["offset"] == -1.7 and sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1])


def test_a3_a_cloud_placeholder_beside_the_video_is_never_opened(episode, monkeypatch):
    copy, video = episode
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    monkeypatch.setattr(runner, "_on_disk", lambda p: p != fixed)
    assert runner.retimed_beside(video, copy, "ja") is None


def _keep_looking(steps):
    """Item 2 waits on Anki Miner's open window (a 2-minute look), so Connect keeps looking."""
    real = steps.mine

    def mine(lang, job, picked, words, attempt):
        if job["item_id"] == 2:
            raise runner.Wait(runner.ANKI_MINER_OPEN)
        return real(lang, job, picked, words, attempt)
    steps.mine = mine


def test_a4_a_copy_gone_never_lets_the_episode_go_each_look(tmp_path, path, episode):
    copy, video = episode
    steps = Steps(str(tmp_path), {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}}, copy, video)
    _keep_looking(steps)
    _run(steps, path, sleep=lambda s: os.path.exists(copy) and os.remove(copy), looks=3)
    assert len([e for e in steps.log if e[0] == "fit" and e[1] == 1]) == 1, "the next start's, never each look's"


def test_a5_the_one_beside_not_timed_either_still_sees_its_copy_fixed_in_that_run(tmp_path, path, episode):
    copy, video = episode
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))     # tsubasa: two segments for it too
    steps = Steps(str(tmp_path), {"line": {"ja": [1, 2]}, "queue": {"ja": [1, 2]}}, copy, video)
    _keep_looking(steps)

    def pause(_seconds):
        if steps.answers.get(copy) is None:
            with open(copy, "a", encoding="utf-8", newline="\r\n") as f:
                f.write("\n")
            steps.answers[copy] = (fit_check.TIMED, 0.0)
    _run(steps, path, sleep=pause, looks=2)
    assert sorted(steps.anki.words()) == sorted(w for w, _r in WORDS[1]), "its copy fixed: mined at look 2"
    assert fixed in [e[2] for e in steps.log if e[0] == "fit" and len(e) == 3]


def test_a6_check_again_on_an_episode_you_stopped_lets_it_go(tmp_path, path, episode):
    copy, video = episode
    _run(Steps(str(tmp_path), _plan(), copy, video), path)
    job, _picked = _job(path)
    with Ledger(path) as ledger, ledger.transaction():
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (f"stopped:{job['id']}", ""))
    assert actions.check_again("ja", 1, path=path) is True
    with Ledger(path) as ledger:
        assert not ledger.is_stopped(job["id"]) and not ledger.held_by_stop(ledger.job_by_id(job["id"]))


def test_a8_a_check_of_the_file_beside_that_never_answers_leaves_the_copy_for_the_next_pick(tmp_path, path, episode):
    copy, video = episode
    fixed = _beside(video, ".ja.srt", _shifted(_source_text(), 1500))
    steps = Steps(str(tmp_path), _plan(), copy, video, answers={fixed: (fit_check.RETRY, 0.0)})
    _run(steps, path, looks=runner.FIT_TRIES)
    _job_, picked = _job(path)
    assert len(_needs(path)) == 1 and "beside" not in picked, "a *Mine anyway* now mines the library's copy"


def test_check_again_leaves_an_episode_waiting_on_anything_else_as_it_is(tmp_path, path, episode):
    # waiting for its video (no *Not timed* entry): Check again isn't its press — nothing queued, nothing written
    copy, video = episode
    steps = Steps(str(tmp_path), _plan(), copy, video)
    steps.plan["videos"]["1"] = None
    _run(steps, path)
    job, _picked = _job(path)
    assert job["state"] == "waiting" and job["reason"] == runner.NO_VIDEO
    assert actions.check_again("ja", 1, path=path) is False
    assert _job(path)[0]["state"] == "waiting"
