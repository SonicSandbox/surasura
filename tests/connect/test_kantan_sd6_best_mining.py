"""Mining under *Card sentences: Best* (Kantan-SD 6): one episode's words are one job and one Anki Miner call, wherever
their sentences are cut.

A timed mine of one episode took three times as long under Best as under Nearest and made fewer cards: each word whose
best sentence lay in another episode became a job of its own there (eleven Anki Miner starts for one episode's words),
a word Anki Miner made no card for on that other line was lost to the mine, and one job in eleven stopped when its run
file's replace met a file another program was reading. Now a word cut from another video's line stays in the mined
episode's job (`runner._best` marks it `from`, `_borrow` picks its line there), a line that gives no card sends the
word back to its own line in the same job (`_back_home`), and the run file's replace waits a busy file out.

Against `FakeSteps` and a real ledger; real Japanese and Chinese words. No live Anki, no Anki Miner, no sleeps.
"""
import json
import os
import sys
import threading

import pytest

from app.connect import fit_check, runfile, runner
from app.connect.ledger import Ledger
from tests.connect.test_kantan_ma_left_out import WORDS, _run, _steps

pytestmark = pytest.mark.usefixtures("_no_real_backoff")


@pytest.fixture
def _no_real_backoff(monkeypatch):
    monkeypatch.setattr(runfile.time, "sleep", lambda s: None)


def _best_from(monkeypatch, away, item=2):
    """`_best` as the dial answers when `away`'s clearest sentence is in episode `item` (a video on this PC)."""
    def best(steps, ledger, lang, job, words, here):
        return [dict(w, **{"from": item}) if (w["word"], w["reading"]) == away else w for w in words], []
    monkeypatch.setattr(runner, "_best", best)


def _spread(tmp_path, lang):
    """Episode 1 holds WORDS[lang]; episode 2 (not queued: never mined here) holds the second of them too."""
    steps = _steps(tmp_path, lang)
    steps.plan["words"]["2"] = [WORDS[lang][1]]
    return steps


def _mines(steps):
    return [(e[1], e[2], e[3]) for e in steps.log if e[0] == "mine"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_word_cut_from_another_episodes_line_is_made_by_the_mined_episodes_own_job_in_one_batch(tmp_path,
                                                                                                    monkeypatch, lang):
    # why: Best made a job (and an Anki Miner start, ~7.5 s) per episode a sentence came from — eleven for one
    # episode's words — and booked each card on an episode the learner never mined
    home, away = WORDS[lang]
    _best_from(monkeypatch, away)
    steps, path = _spread(tmp_path, lang), str(tmp_path / "ledger.sqlite")
    jobs = _run(steps, path, lang)
    assert [(kind, state) for _id, kind, state in jobs] == [("mine", "done")], "no job of its own for the other line"
    assert _mines(steps) == [(1, 1, [home[0], away[0]])], "one batch: one Anki Miner call"
    with Ledger(path) as ledger:
        jid = jobs[0][0]
        picked = ledger.picked(jid)
        made = {o["word"]: o for o in ledger.outcomes(jid) if o["outcome"] == "made"}
    assert set(made) == {home[0], away[0]}, "both cards are the mined episode's job's (its tag, its record)"
    moved = next(w for w in picked["words"] if w["word"] == away[0])
    assert moved["from"] == 2 and moved["own"]["word"] == away[0] and "from" not in moved["own"]
    assert list(picked["sources"]) == ["2"] and picked["sources"]["2"]["file"] == "/library/2.ja.srt"
    assert picked["sources"]["2"]["offset"] == 0.0, "the other episode's timing was checked as its own job's would be"
    assert "elsewhere" not in picked and not picked.get("left"), "its card is this episode's: never *Not made*"
    assert ("fit", 2) in steps.log


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_word_the_other_line_gives_no_card_goes_back_to_its_own_line_in_the_same_job(tmp_path, monkeypatch, lang):
    # why: として, moved to episode 02's line, got no card there and none at all — Nearest made it from its own line
    home, away = WORDS[lang]
    _best_from(monkeypatch, away)
    steps, path = _spread(tmp_path, lang), str(tmp_path / "ledger.sqlite")
    real = steps.mine

    def mine(lang_, job, picked, words, attempt):
        there = [w for w in words if w.get("from") is not None]
        got = real(lang_, job, picked, [w for w in words if w.get("from") is None], attempt)
        got["outcomes"] += [{"word": w["word"], "reading": w["reading"], "outcome": "not_found", "note_id": None,
                             "line_start": w["line_start"]} for w in there]
        return got
    steps.mine = mine
    jobs = _run(steps, path, lang)
    assert [(kind, state) for _id, kind, state in jobs] == [("mine", "done")]
    assert _mines(steps) == [(1, 1, [home[0]]), (1, 2, [away[0]])], "the second batch: the word alone, on its own line"
    with Ledger(path) as ledger:
        picked = ledger.picked(jobs[0][0])
        made = sorted(o["word"] for o in ledger.outcomes(jobs[0][0]) if o["outcome"] == "made")
    assert made == sorted([home[0], away[0]]), "as many cards as Nearest makes"
    assert "sources" not in picked and all("from" not in w for w in picked["words"])


def test_what_the_line_cant_be_blamed_for_is_never_tried_again_on_the_words_own_line():
    # why: a duplicate, a word with no definition, one merged into another word's card or one in doubt would answer
    # the same from its own line — or its card may be there already: sending it again could make a second card
    def word(name):
        return {"word": name, "reading": "", "from": 2, "own": {"word": name, "reading": ""}}
    names = ["重複", "定義", "統合", "不明", "切取", "未読", "停止"]
    picked = {"words": [word(n) for n in names], "sources": {"2": {"video": "v.mkv"}}}
    rows = dict(zip(names, ({"outcome": "duplicate"}, {"outcome": "no_definition"},
                            {"outcome": "not_found", "filter": "duplicate-expression"}, {"outcome": "uncertain"},
                            {"outcome": "media_failed"}, {"outcome": "not_attempted", "run_error": "VIDEO_UNREADABLE"},
                            {"outcome": "not_attempted"})))
    outcomes = [dict(row, word=name, reading="", note_id=None) for name, row in rows.items()]
    assert runner._back_home(picked, outcomes) == {("切取", ""), ("未読", "")}
    assert [w["word"] for w in picked["words"] if "from" not in w] == ["切取", "未読"]
    assert [o["outcome"] for o in outcomes if o["word"] in ("切取", "未読")] == ["not_attempted"] * 2
    assert "sources" in picked, "the other words are still cut there"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_another_episode_that_isnt_timed_gives_its_words_back_before_anything_is_cut(tmp_path, monkeypatch, lang):
    # why: a clip cut from a subtitle that doesn't fit its video is a wrong card; and another episode's timing must
    # never hold this episode's cards back or ask the learner about an episode they didn't mine
    home, away = WORDS[lang]
    _best_from(monkeypatch, away)
    steps, path = _spread(tmp_path, lang), str(tmp_path / "ledger.sqlite")
    real = steps.fit

    def fit(lang_, job, pairing, video, subtitle):
        if job["item_id"] == 2:
            steps.log.append(("fit", 2))
            return (fit_check.NOT_TIMED, "tsubasa", "Not timed to its video, so no cards.", 0.0)
        return real(lang_, job, pairing, video, subtitle)
    steps.fit = fit
    jobs = _run(steps, path, lang)
    assert [(kind, state) for _id, kind, state in jobs] == [("mine", "done")], "no wait, no *Needs you*"
    assert _mines(steps) == [(1, 1, [home[0], away[0]])]
    with Ledger(path) as ledger:
        picked = ledger.picked(jobs[0][0])
    assert "sources" not in picked and all("from" not in w for w in picked["words"])


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_another_episode_re_timed_since_its_line_was_picked_gives_its_words_back(tmp_path, monkeypatch, lang):
    # why: hato re-timed the other episode between the pick and the timing check — the line picked there may sit
    # elsewhere now; cut as picked, its clip would be the wrong moment (E17, as for the episode's own subtitle)
    home, away = WORDS[lang]
    _best_from(monkeypatch, away)
    steps, path = _spread(tmp_path, lang), str(tmp_path / "ledger.sqlite")
    steps.plan["pairings"] = {"2": {"sha256": "a1"}}
    real = steps.fit

    def fit(lang_, job, pairing, video, subtitle):
        steps.plan["pairings"] = {"2": {"sha256": "b2"}}      # re-timed while this episode's own fit ran
        return real(lang_, job, pairing, video, subtitle)
    steps.fit = fit
    jobs = _run(steps, path, lang)
    assert [(kind, state) for _id, kind, state in jobs] == [("mine", "done")]
    assert _mines(steps) == [(1, 1, [home[0], away[0]])]
    with Ledger(path) as ledger:
        picked = ledger.picked(jobs[0][0])
    assert "sources" not in picked and all("from" not in w for w in picked["words"])


def test_best_keeps_a_videos_word_in_the_job_and_gives_a_books_its_own_job(tmp_path, monkeypatch):
    # why: a book's line needs its own making (its audiobook's line-up, the AI voice): that path stays as it was
    from app.connect import level, sentences
    from app.connect.ledger import LEVEL
    from tests.connect.test_kantan_sd_dial import EASY, HARD, _Steps, _choices, _words
    adventure, maze = ("冒険", "ボウケン"), ("迷宮", "メイキュウ")
    here = str(tmp_path / "第01話.srt")
    own = sentences.Choice(here, 1, HARD, 2, 0.5, True, True)
    video = sentences.Choice("第02話.srt", 2, EASY, 0, 0.5, False, True)
    book = sentences.Choice("小説.txt", 7, EASY, 0, 0.5, False, True)
    monkeypatch.setattr(sentences, "choose", _choices(here, {adventure: [video, own], maze: [book, own]}))
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        job = {"id": 9, "item_id": 1, "kind": "new", "store_id": "s-1"}
        kept, moved = runner._best(_Steps(videos=(2,)), ledger, "ja", job, _words(adventure, maze), here)
        assert [(w["word"], w.get("from")) for w in kept] == [("冒険", 2)]
        assert moved == [{"word": "迷宮", "reading": "メイキュウ", "item_id": 7, "text": EASY}]
        (made,) = [ledger.job_by_id(j["id"]) for j in ledger.jobs("ja") if j["kind"] == LEVEL]
        assert made["item_id"] == 7 and made["source"] == level.BEST and made["words"] == [maze]


# --- the run file's replace ------------------------------------------------------------------------------------------
def _data(tmp_path):
    words = [{"word": "迷宮", "line_start": 12.5, "line_expansion": [0, 0]}]
    episode = runfile.episode("job-1", str(tmp_path / "第01話.mkv"), str(tmp_path / "第01話.ja.srt"), words)
    return runfile.build(str(tmp_path / "runs"), "ja", [episode])


def test_a_run_file_another_program_is_reading_is_written_once_it_lets_go(tmp_path, monkeypatch):
    # why: one job in eleven stopped on [WinError 32] at this replace in every timed Best mine, its word never made
    path = str(tmp_path / "runs" / "run-1.json")
    runfile.write(path, _data(tmp_path))
    real, calls = os.replace, []

    def held(src, dst):
        calls.append(dst)
        if len(calls) < 3:
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(src, dst)
    monkeypatch.setattr(runfile.os, "replace", held)
    data = _data(tmp_path)
    data["episodes"][0]["words"][0]["word"] = "冒険"
    assert runfile.write(path, data) == path and len(calls) == 3
    assert json.load(open(path, encoding="utf-8"))["episodes"][0]["words"][0]["word"] == "冒険"
    assert os.listdir(os.path.dirname(path)) == ["run-1.json"], "no temp file left"


def test_a_run_file_held_for_good_is_an_error_with_the_old_file_whole_and_no_temp_left(tmp_path, monkeypatch):
    # why: a wait without an end would hang Connect's one mining thread; the caller's own handling takes over
    path = str(tmp_path / "runs" / "run-1.json")
    runfile.write(path, _data(tmp_path))
    before, calls = open(path, "rb").read(), []

    def held(src, dst):
        calls.append(dst)
        raise PermissionError(13, "held")
    monkeypatch.setattr(runfile.os, "replace", held)
    with pytest.raises(PermissionError):
        runfile.write(path, _data(tmp_path))
    assert len(calls) == len(runfile.REPLACE_BACKOFF) + 1
    assert open(path, "rb").read() == before and os.listdir(os.path.dirname(path)) == ["run-1.json"]


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows refuses a replace onto a file held open")
def test_a_run_file_really_held_open_is_replaced_when_the_reader_closes_it(tmp_path, monkeypatch):
    # why: the two tests above stand in for the reader; this one is the reader — a file open with no delete sharing,
    # as a virus check holds one, closed while the write waits
    path = str(tmp_path / "runs" / "run-1.json")
    runfile.write(path, _data(tmp_path))
    reader, waits = open(path, "rb"), []

    def wait(seconds):
        waits.append(seconds)
        if len(waits) == 2:
            reader.close()
    monkeypatch.setattr(runfile.time, "sleep", wait)
    try:
        data = _data(tmp_path)
        data["language"] = "zh"
        runfile.write(path, data)
    finally:
        reader.close()
    assert waits == list(runfile.REPLACE_BACKOFF[:2])
    assert json.load(open(path, encoding="utf-8"))["language"] == "zh"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_word_the_other_line_gave_no_card_goes_home_even_when_anki_went_away_before_the_read_back(tmp_path,
                                                                                                    monkeypatch, lang):
    # why: the batch ended in doubt and Anki closed before its cards were read back by the tag (a Wait): the other
    # line's not-found was recorded as it was, settled — the word was never tried on its own line, never made
    home, away = WORDS[lang]
    _best_from(monkeypatch, away)
    steps, path = _spread(tmp_path, lang), str(tmp_path / "ledger.sqlite")
    real, real_tag = steps.mine, steps.by_tag

    def mine(lang_, job, picked, words, attempt):
        there = [w for w in words if w.get("from") is not None]
        got = real(lang_, job, picked, [w for w in words if w.get("from") is None], attempt)
        got["outcomes"] += [{"word": w["word"], "reading": w["reading"], "outcome": "not_found", "note_id": None,
                             "line_start": w["line_start"]} for w in there]
        got["doubt"] = bool(there)
        return got

    def by_tag(*a):
        raise runner.Wait(runner.ANKI_MINER_OPEN)
    steps.mine, steps.by_tag = mine, by_tag
    _run(steps, path, lang)
    steps.by_tag = real_tag
    jobs = _run(steps, path, lang)
    assert [(kind, state) for _id, kind, state in jobs] == [("mine", "done")]
    assert _mines(steps)[-1] == (1, 2, [away[0]]), "the next batch: the word alone, on its own line"
    with Ledger(path) as ledger:
        made = sorted(o["word"] for o in ledger.outcomes(jobs[0][0]) if o["outcome"] == "made")
    assert made == sorted([home[0], away[0]])


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("where", ["pick", "fit"])
def test_another_episode_that_fails_in_a_way_no_one_planned_for_never_stops_this_episodes_cards(tmp_path, monkeypatch,
                                                                                               lang, where):
    # why: another episode is only where a better sentence might be — its broken pairing row or a bug in its check
    # must leave this episode's words on their own lines, never end the job on an error
    home, away = WORDS[lang]
    _best_from(monkeypatch, away)
    steps, path = _spread(tmp_path, lang), str(tmp_path / "ledger.sqlite")
    if where == "pick":
        steps.plan["pick_error"] = [2]
    else:
        real = steps.fit

        def fit(lang_, job, pairing, video, subtitle):
            if job["item_id"] == 2:
                raise RuntimeError("a pairing row this test broke")
            return real(lang_, job, pairing, video, subtitle)
        steps.fit = fit
    jobs = _run(steps, path, lang)
    assert [(kind, state) for _id, kind, state in jobs] == [("mine", "done")]
    assert _mines(steps) == [(1, 1, [home[0], away[0]])]
    with Ledger(path) as ledger:
        picked = ledger.picked(jobs[0][0])
    assert "sources" not in picked and all("from" not in w for w in picked["words"])
