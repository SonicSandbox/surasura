"""One Anki Miner call that cuts lines from several episodes (Kantan-SD 6, *Card sentences: Best*), end to end against
the fake Anki Miner (`--api` as API.md documents it, its episodes run in turn).

Under Best a word whose clearest sentence is in another episode is cut from that episode's line inside the mined
episode's job: `anki_miner.mine_batch(more=…)` sends the episode's own words and one more episode a source, in ONE call
(one start, one dictionary load), every card under the job's tag. What a wrong answer would cost: a card made twice
when the job is read back after a crash or a Stop, a half-written card, a word whose card was made but never recorded
(made again by the next episode), or a source that can't be read taking the episode's own cards down with it.

Real words from `tests/Test Resources/` (ja: the library episode + the placed episode; zh: the night market + the
repeated lines), a stand-in video file, never a live Anki.
"""
import os
from types import SimpleNamespace

import pytest

from app import analyzer, cues
from app.cli import verbs
from app.connect import anki_miner, fields, pick, runfile, runner
from app.connect.ledger import Ledger
from tests.connect.fake_anki_miner import LAPIS_EXPORT
from tests.connect.fake_steps import Killed
from tests.connect.test_kantan_ma_left_out import WORDS, _run, _steps

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources")
FILES = {"ja": (os.path.join(RESOURCES, "ja", "library_episode.ass"), os.path.join(RESOURCES, "ja", "placed_episode.srt")),
         "zh": (os.path.join(RESOURCES, "zh", "night_market.srt"), os.path.join(RESOURCES, "zh", "repeated_lines.zh.srt"))}
APP = "3.13.0"          # a Chinese call needs 3.12 or newer (`anki_miner.ZH_FROM`)


def _words(path, lang, count):
    """The first `count` words a pick of a real subtitle offers (every word unknown but the commonest grammar)."""
    analyzer.SANITIZE_JA = lang == "ja"
    try:
        read = cues.read(path, lang)
        common = {"だ", "です", "為る", "の", "は", "を", "に", "が", "て", "た", "も", "と", "ます", "ない", "か", "よ", "で",
                  "的", "了", "是", "我", "你", "在", "不", "这", "那", "吗", "呢", "啊", "吧"}
        chosen = pick.pick(read, cues.tokens(read, lang), lang, lambda key: key[0] in common, mode="unknown")
    finally:
        analyzer.SANITIZE_JA = False
    return chosen["words"][:count]


@pytest.fixture
def call(tmp_path, fake_miner, monkeypatch):
    """mine_batch of one episode (job-1, episode 01) with one more episode (04) cut in the same call."""
    monkeypatch.setattr(anki_miner, "POLL_S", 0.05)
    videos = {}
    for name in ("第01話.mkv", "第04話.mkv"):
        videos[name] = tmp_path / name
        videos[name].write_bytes(b"\x1aE\xdf\xa3")          # the fake never opens it

    def run(lang, own=2, other=2, **kw):
        here, there = FILES[lang]
        words, theirs = _words(here, lang, own), _words(there, lang, other)
        more = [{"video": str(videos["第04話.mkv"]), "subtitle": there, "words": theirs, "subtitle_offset": 0.5,
                 "show": "ぼっち・ざ・ろっく！"}]
        done = anki_miner.mine_batch(fake_miner.path, lang, "job-1", str(videos["第01話.mkv"]), here, words,
                                     fields.from_export(LAPIS_EXPORT), "Surasura", str(tmp_path / "runs" / "job-1"),
                                     "http://127.0.0.1:9", more=more, **kw)
        return done, words, theirs
    return run


def _outcomes(done):
    return [o["outcome"] for o in done["outcomes"]]


def _cancel_files(tmp_path):
    return [os.path.join(d, f) for d, _s, fs in os.walk(tmp_path / "runs") for f in fs if f == "cancel"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_one_call_sends_every_episode_under_the_jobs_tag_and_reads_each_result_back_in_order(call, fake_miner, lang):
    # why: one Anki Miner start for the episode's words wherever their lines are (each start ~7 s); a card filed under
    # another tag is a card the job's read-back after a crash can't find, so it would be made twice
    fake_miner.plan(app=APP, features=["word-from-line"])
    done, words, theirs = call(lang)
    assert fake_miner.commands().count("mine") == 1, "one call"
    (sent,) = fake_miner.run_files()
    assert [e["run_id"] for e in sent["episodes"]] == ["job-1-1", "job-1-1-s1"]
    assert [os.path.basename(e["video_file"]) for e in sent["episodes"]] == ["第01話.mkv", "第04話.mkv"]
    own, other = sent["episodes"]
    assert runfile.job_tag("job-1") in own["tags"].split() and runfile.job_tag("job-1") in other["tags"].split()
    assert runfile.from_tag("ぼっち・ざ・ろっく！") in other["tags"].split(), "the line's own show on its card"
    assert other.get("subtitle_offset") == 0.5, "the other episode cut at its own shift"
    assert [o["word"] for o in done["outcomes"]] == [w["word"] for w in words + theirs], "the words' order"
    assert _outcomes(done) == ["made"] * (len(words) + len(theirs))
    notes = [o["note_id"] for o in done["outcomes"]]
    assert len(set(notes)) == len(notes), "every card its own note"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_stop_while_the_other_episode_waits_its_turn_keeps_the_episodes_cards_and_sends_no_more(call, fake_miner,
                                                                                                tmp_path, lang):
    # why: a Stop must end the whole call at once — the episode still waiting its turn too — and every card already
    # made must come back as made (recorded, never made again)
    fake_miner.plan(app=APP, features=["word-from-line"], cancel_runs={"job-1-1-s1": 0})
    own_done = tmp_path / "runs" / "job-1" / "job-1-1" / "result-1.json"
    done, words, theirs = call(lang, should_stop=lambda: own_done.exists())
    assert done["stopped"] is True
    assert _outcomes(done) == ["made"] * len(words) + ["not_attempted"] * len(theirs)
    assert all(o.get("run_error") == "CANCELLED" for o in done["outcomes"][len(words):])
    assert _cancel_files(tmp_path) == [], "the call over: no cancel file left for the next call"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_stop_in_the_middle_of_the_other_episode_keeps_the_card_it_made_and_leaves_the_rest_whole(call, fake_miner,
                                                                                                   tmp_path, lang):
    # why: Anki Miner ends a cancelled run between two words: the word before is a whole card, the one after never
    # reached Anki — neither may be read as in doubt and sent again on its own line
    fake_miner.plan(app=APP, features=["word-from-line"], cancel_runs={"job-1-1-s1": 1})
    done, words, theirs = call(lang, other=3, should_stop=lambda: True)
    assert done["stopped"] is True
    assert _outcomes(done) == ["made"] * len(words) + ["made"] + ["not_attempted"] * (len(theirs) - 1)
    assert not any(o.get("run_error") for o in done["outcomes"]), "the run began: its rows are Anki Miner's own"
    assert _cancel_files(tmp_path) == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_another_episodes_video_that_cant_be_read_leaves_its_words_unsent_and_the_episodes_cards_made(call, fake_miner,
                                                                                                     lang):
    # why: a source that can't be opened must never take the mined episode's own cards with it; its words never
    # reached Anki, so they go back to their own lines (`runner._back_home` reads `run_error`), never in doubt
    fake_miner.plan(app=APP, features=["word-from-line"], unreadable=["第04話.mkv"])
    done, words, theirs = call(lang)
    assert "refused" not in done
    assert _outcomes(done) == ["made"] * len(words) + ["not_attempted"] * len(theirs)
    assert {o.get("run_error") for o in done["outcomes"][len(words):]} == {"VIDEO_UNREADABLE"}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_episodes_own_video_refused_while_another_made_cards_keeps_those_cards_and_says_why(call, fake_miner, lang):
    # why: raising the refusal at once would drop the cards the other episode made — unrecorded, so made again
    fake_miner.plan(app=APP, features=["word-from-line"], unreadable=["第01話.mkv"])
    done, words, theirs = call(lang)
    assert isinstance(done.get("refused"), anki_miner.AnkiMinerError)
    assert _outcomes(done) == ["not_attempted"] * len(words) + ["made"] * len(theirs)


def test_every_episode_refused_is_the_calls_refusal_as_before(call, fake_miner):
    # why: nothing reached Anki: the batch is refused (never in doubt), as a one-episode call is
    fake_miner.plan(app=APP, features=["word-from-line"], unreadable=["第01話.mkv", "第04話.mkv"])
    with pytest.raises(anki_miner.AnkiMinerError):
        call("ja")


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_crash_after_the_first_episode_keeps_its_cards_and_leaves_the_other_in_doubt(call, fake_miner, lang):
    # why: after a crash only what a result file says is made; the rest may or may not be in Anki, so the runner reads
    # them back by the job's tag before anything is sent again (never a second card)
    fake_miner.plan(app=APP, features=["word-from-line"], crash_after_runs=1)
    done, words, theirs = call(lang)
    assert done["error"] == "crashed"
    assert _outcomes(done) == ["made"] * len(words) + ["uncertain"] * len(theirs)


def test_a_crash_after_every_result_was_written_reads_each_episodes_cards(call, fake_miner):
    # why: the verdict is lost, not the cards: each run's newest result is read, the other episode's too
    fake_miner.plan(app=APP, features=["word-from-line"], mine="crash-after-result")
    done, words, theirs = call("ja")
    assert done["error"] == "crashed"
    assert _outcomes(done) == ["made"] * (len(words) + len(theirs))


def test_progress_names_the_run_that_works_and_how_many_there_are(call, fake_miner):
    # why: the line's bar goes once over the whole call (`status._progress`) and names the episode whose line is cut
    fake_miner.plan(app=APP, features=["word-from-line"], progress=[[1, 5, 0, 0], [3, 5, 1, 2]], progress_every=0.25)
    seen = []
    call("ja", on_progress=seen.append)
    assert seen and all(p.get("runs") == 2 for p in seen)
    assert [p["run"] for p in seen] == sorted(p["run"] for p in seen), "the runs go in turn, never back"
    assert {p["run"] for p in seen} == {0, 1}


# --- the runner's half: Steps.mine spreads one batch over the episodes, the job reads a crash back -------------------
@pytest.fixture
def spread(monkeypatch):
    """`Steps.mine` with Anki Miner's call captured (as `test_fix_offset_to_anki_miner.py` does)."""
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "am.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup",
                        lambda loaded, lang, run_dir, held=None: (None, None, SimpleNamespace(word="Word")))
    monkeypatch.setattr(runner.Steps, "show", lambda self, lang, job: f"show-{job['item_id']}")
    calls = []

    def capture(path, lang, job, video, subtitle, words, *args, more=None, on_progress=None, **kwargs):
        calls.append({"video": video, "subtitle": subtitle, "words": [w["word"] for w in words], "more": more,
                      "show": kwargs.get("show"), "offset": kwargs.get("subtitle_offset")})
        if on_progress is not None:
            on_progress({"stage": 3, "stages": 5, "done": 1, "total": 2, "run": 1, "runs": 2})
        sent = list(words) + [w for m in more or () for w in m["words"]]
        return {"outcomes": [{"word": w["word"], "reading": w["reading"], "outcome": "made", "note_id": 100 + n,
                              "line_start": w["line_start"]} for n, w in enumerate(sent)], "app": APP}
    monkeypatch.setattr(anki_miner, "mine_batch", capture)
    return calls


def _w(word, reading, start, item=None):
    w = {"word": word, "reading": reading, "line_start": start}
    return dict(w, **{"from": item}) if item is not None else w


SOURCES = {"4": {"video": "第04話.mkv", "subtitle": "runs/9/from-4/第04話.ja.srt", "offset": 1.24, "title": "第04話"}}


def test_one_batch_goes_as_one_call_and_the_outcomes_come_back_in_the_words_order(spread):
    # why: the ledger matches outcomes to words by key in the batch's order; a source's words sent first would have
    # been fine, but a word missing from the answer must read not_attempted, never another word's card
    picked = {"video": "第01話.mkv", "subtitle": "第01話.ja.srt", "offset": 0.0, "profile": None, "sources": SOURCES}
    words = [_w("冒険", "ボウケン", 3.0, 4), _w("迷宮", "メイキュウ", 5.0), _w("大衆", "タイシュウ", 8.0, 4)]
    got = runner.Steps({}).mine("ja", {"id": 9, "item_id": 1, "tag": "9"}, picked, words, 1)
    (one,) = spread
    assert one["video"] == "第01話.mkv" and one["words"] == ["迷宮"] and one["show"] == "show-1"
    (more,) = one["more"]
    assert more["video"] == "第04話.mkv" and [w["word"] for w in more["words"]] == ["冒険", "大衆"]
    assert more["subtitle_offset"] == 1.24 and more["show"] == "show-4"
    assert [o["word"] for o in got["outcomes"]] == ["冒険", "迷宮", "大衆"]
    assert all(o["outcome"] == "made" for o in got["outcomes"])


def test_a_batch_whose_every_word_is_cut_elsewhere_makes_that_episode_the_calls_own(spread):
    # why: a call names no episode without a word; the episode's own video must not be sent with nothing to cut
    picked = {"video": "第01話.mkv", "subtitle": "第01話.ja.srt", "offset": 0.0, "profile": None, "sources": SOURCES,
              "names": ["後藤"], "from_audio": True}
    got = runner.Steps({}).mine("ja", {"id": 9, "item_id": 1, "tag": "9"}, picked, [_w("冒険", "ボウケン", 3.0, 4)], 1)
    (one,) = spread
    assert one["video"] == "第04話.mkv" and one["subtitle"] == SOURCES["4"]["subtitle"] and one["offset"] == 1.24
    assert one["more"] == [] and one["show"] == "show-4"
    assert [o["outcome"] for o in got["outcomes"]] == ["made"]


def test_a_batch_with_no_word_cut_elsewhere_is_the_call_as_before(spread):
    picked = {"video": "第01話.mkv", "subtitle": "第01話.ja.srt", "offset": 0.0, "profile": None}
    runner.Steps({}).mine("ja", {"id": 9, "item_id": 1, "tag": "9"}, picked, [_w("迷宮", "メイキュウ", 5.0)], 1)
    (one,) = spread
    assert one["more"] is None


def test_the_progress_of_a_call_cut_from_two_episodes_names_the_one_whose_line_is_cut(spread):
    # why: the window's line says *01 — a sentence from 04* while 04's line is cut (`status._progress` keeps it)
    picked = {"video": "第01話.mkv", "subtitle": "第01話.ja.srt", "offset": 0.0, "profile": None, "sources": SOURCES}
    steps, seen = runner.Steps({}), []
    steps.on_progress = seen.append
    steps.mine("ja", {"id": 9, "item_id": 1, "tag": "9"}, picked,
               [_w("迷宮", "メイキュウ", 5.0), _w("冒険", "ボウケン", 3.0, 4)], 1)
    assert seen == [{"stage": 3, "stages": 5, "done": 1, "total": 2, "run": 1, "runs": 2, "source": "第04話"}]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_crash_mid_call_is_finished_by_the_next_start_with_no_card_made_twice(tmp_path, monkeypatch, lang):
    # why: Connect killed while Anki Miner cut the other episode's line: the next start reads the job back by its tag
    # (the card from the episode's own line is found there) and sends only the word still unsettled, from that line
    home, away = WORDS[lang]

    def best(steps, ledger, lang_, job, words, here):
        return [dict(w, **{"from": 2}) if (w["word"], w["reading"]) == away else w for w in words], []
    monkeypatch.setattr(runner, "_best", best)
    steps, path = _steps(tmp_path, lang), str(tmp_path / "ledger.sqlite")
    steps.plan["words"]["2"] = [away]
    steps.plan["kill"] = "mid-batch:1"
    with pytest.raises(Killed):
        _run(steps, path, lang)
    steps.plan["kill"] = None
    jobs = _run(steps, path, lang)
    assert [(kind, state) for _id, kind, state in jobs] == [("mine", "done")]
    assert sorted(steps.anki.words()) == sorted([home[0], away[0]]), "each card once"
    mines = [(e[2], e[3]) for e in steps.log if e[0] == "mine"]
    assert mines == [(1, [home[0], away[0]]), (2, [away[0]])], "the second batch: only the word not yet made"
    assert ("by_tag", 1) in steps.log, "read back by the job's tag first"
    with Ledger(path) as ledger:
        picked = ledger.picked(jobs[0][0])
        made = {o["word"] for o in ledger.outcomes(jobs[0][0]) if o["outcome"] == "made"}
    assert made == {home[0], away[0]}
    assert next(w for w in picked["words"] if w["word"] == away[0])["from"] == 2, "still cut from the other line"


def test_a_stop_while_another_episode_sets_up_takes_its_clips_too(call, fake_miner, tmp_path):
    # why (#BS0A1K): a Stop in a step that never reads the cancel file ends the call; the clips the run in flight cut
    # go as Anki Miner's own clean-up would take them — the other episode's run as well as the episode's own
    fake_miner.plan(app=APP, features=["word-from-line"], progress=[[1, 5, 0, 0]], progress_every=0.05, media=True,
                    deaf_runs={"job-1-1-s1": 30})
    run_dir = tmp_path / "runs" / "job-1"
    with pytest.raises(anki_miner.AnkiMinerError) as raised:
        call("ja", should_stop=lambda: (run_dir / "job-1-1-s1" / "media").exists())
    assert raised.value.kind == "cancelled" and raised.value.stopped is True
    assert not (run_dir / "job-1-1-s1" / "media").exists(), "the other run's clips taken"
    assert (run_dir / "job-1-1" / "result-1.json").exists(), "the episode's own run had finished: its cards stand"


@pytest.mark.parametrize("kind, stopped", [("crashed", False), ("timeout", False), ("cancelled", True)])
def test_a_call_that_ended_in_doubt_leaves_every_episodes_words_to_be_read_back_by_the_tag(monkeypatch, kind, stopped):
    # why: after a crash, a timeout or a Stop with no verdict, a word cut from another episode may have its card in
    # Anki already (that run came first, or was half done); called not attempted, it was sent again — a second card,
    # or a duplicate the ledger never records as this job's (made again by the next episode)
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "am.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup",
                        lambda loaded, lang, run_dir, held=None: (None, None, SimpleNamespace(word="Word")))
    monkeypatch.setattr(runner.Steps, "show", lambda self, lang, job: None)

    def ended(*args, **kwargs):
        e = anki_miner.AnkiMinerError(kind, "Anki Miner stopped")
        e.stopped = stopped
        raise e
    monkeypatch.setattr(anki_miner, "mine_batch", ended)
    picked = {"video": "第01話.mkv", "subtitle": "第01話.ja.srt", "offset": 0.0, "profile": None, "sources": SOURCES}
    got = runner.Steps({}).mine("ja", {"id": 9, "item_id": 1, "tag": "9"}, picked,
                                [_w("迷宮", "メイキュウ", 5.0), _w("冒険", "ボウケン", 3.0, 4)], 1)
    assert [o["outcome"] for o in got["outcomes"]] == ["uncertain", "uncertain"]
    assert got["doubt"] is True and bool(got.get("stopped")) is stopped


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_review_while_the_other_episode_waits_keeps_its_words_on_that_episodes_line(call, fake_miner, tmp_path,
                                                                                      lang):
    # why (the merge with OPEN 40): a review in Anki cancels the call as a Stop does, and the episode still waiting its
    # turn answers CANCELLED for each of its words. A cancel says nothing about that line: read as "its file couldn't
    # be read", every review during a mine sent those words back to their own lines — Best's sentence lost each time
    fake_miner.plan(app=APP, features=["word-from-line"], cancel_runs={"job-1-1-s1": 0})
    own_done = tmp_path / "runs" / "job-1" / "job-1-1" / "result-1.json"
    done, words, theirs = call(lang, should_stop=lambda: False, should_pause=lambda: own_done.exists())
    assert done["paused"] is True and done["stopped"] is False
    assert _outcomes(done) == ["made"] * len(words) + ["not_attempted"] * len(theirs)
    picked = {"words": [dict(w, own=dict(w)) for w in words] + [dict(w, own=dict(w), **{"from": 4}) for w in theirs],
              "sources": {"4": {"video": "第04話.mkv"}}}
    assert runner._back_home(picked, done["outcomes"]) == set(), "paused, not refused: nothing goes home"
    assert all(w.get("from") == 4 for w in picked["words"][len(words):]) and "sources" in picked
