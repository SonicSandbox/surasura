"""Netflix and Disney+ mined after the fact (鵜 Ukai SPEC §6 U-S4; ported from #474's `tests/test_online_receiver.py`,
by mattias): Connect never downloads these videos (DRM). It picks the words from the transcript's own cues, hands
their lines to Ukai through `<connect>/browser/b<job>/` (`app/connect/browser.py`) and waits; Ukai records each line in
the learner's browser and posts the clip; each clip then goes to Anki Miner as a video of its own.

What a wrong answer would cost a learner: a card whose clip holds another line (a word on the wrong sentence), a
negative line start that stops Anki Miner's run, a line recorded twice (a pick again renumbering the lines), a
recording lost at a restart, a Netflix episode sent to Anki Miner's download, or — while Ukai is off — a hand-named
`[netflix-<id>]` file waiting for an extension that isn't there.

Real Japanese lines (Mattias's episodes, as #474's tests had them); the ledger and the steps are stand-ins; the
folders are the test's own (SURASURA_TEST_ROOT). The door's routes are tested in `modules/ukai/tests/`.
"""
import os
import random

import pytest

from app import door
from app.connect import browser, online, runner

CUES = [(700.0, 703.5, "雨の日の散歩で見つけた"), (705.29, 708.84, "小さな発見を話そう"), (709.0, 711.0, "朝ごはんを五分で作る"),
        (912.0, 915.5, "古本屋めぐりは楽しい")]
WEB = {"site": "netflix", "url": "https://www.netflix.com/watch/81234567", "video_id": "81234567"}
# 俺のこと、なんか言ってた？ S01E08: six lines, a pick ranks them out of time order
EP8 = [(129.708, 131.458, "〈貴様の頬が裂けるまで〉"), (265.75, 268.25, "「リア王」と初日 一緒だなって"),
       (337.042, 339.917, "もともと こちらの大物俳優役は どなたが？"), (1241.792, 1246.625, "〈稲妻よ 電光石火の硫黄の火〉"),
       (2044.292, 2046.667, "ワレ コラ！ワシを誰や思っとんねん！"), (2212.917, 2215.375, "王冠をかぶれば 王になれる")]


@pytest.fixture(autouse=True)
def ukai_on(monkeypatch):
    """Connect's half rides the door's switch (`door.EXTENSION_ON`, off until Ukai 1.0): on for these tests, as at
    Ukai 1.0; the off tests turn it off."""
    monkeypatch.setattr(door, "EXTENSION_ON", True)


def _words():
    """Two words on 小さな発見を話そう (one card each, the same line), one on 古本屋めぐり expanded to the line before."""
    return [{"word": "発見", "reading": "はっけん", "line_start": 705.29, "line_expansion": [0, 0]},
            {"word": "話す", "reading": "はなす", "line_start": 705.29, "line_expansion": [0, 0]},
            {"word": "古本屋", "reading": "ふるほんや", "line_start": 912.0, "line_expansion": [1, 0]}]


def _ep8_word(word, start):
    return {"word": word, "reading": word, "line_start": start, "line_expansion": [0, 0]}


def _bytes(data):
    """A clip's body as the door's streamed route hands it over: `save(path)` writes it whole."""
    def save(path):
        with open(path, "wb") as f:
            f.write(data)
        return len(data)
    return save


def _keep(job, n, start, end, data=b"\x1aE\xdf\xa3webm"):
    return browser.keep_clip(job, n, _bytes(data), start, end)


def _srt(job, cues):
    here = browser.place(job)
    os.makedirs(here, exist_ok=True)
    path = os.path.join(here, browser.SUBTITLE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(browser.srt_of(cues))
    return path


class _Ledger:
    def __init__(self):
        self.needs, self.states = [], []

    def need(self, lang, kind, say, item_id=None, job_id=None, **_kw):
        self.needs.append((kind, say))
        return True

    def set_state(self, jid, state, **kw):
        self.states.append((state, kw))


class _JobsLedger(_Ledger):
    """The ledger as `_earlier_jobs` reads it: the episode's jobs."""

    def __init__(self, jobs):
        import sqlite3
        super().__init__()
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE jobs (id INTEGER, language TEXT, item_id INTEGER, state TEXT)")
        self.conn.executemany("INSERT INTO jobs VALUES (?, 'ja', ?, ?)",
                              [(j[0], j[1], j[2] if len(j) > 2 else "dropped") for j in jobs])


class _Steps:
    def title(self, lang, job):
        return "雲の上の郵便屋さん"


def _picked(srt, words=None):
    return {"online": "netflix", "url": WEB["url"], "video": srt, "words": words or _words(),
            "names": ["Processed", "雲の上の郵便屋さん S01E03 [netflix-81234567]"]}


def _recorded(job, words, clips=None, done=True):
    """An earlier job's folder as Ukai left it: its lines, a clip for each (or `clips`: {n: (start, end)})."""
    _srt(job, EP8)
    lines, _index = browser.lines_for(words, EP8)
    browser.hand_off(job, WEB, "トークサバイバー！ S01E03", lines)
    for ln in lines:
        start, end = (clips or {}).get(ln["n"], (ln["start"] - 0.7, ln["end"] + 0.7))
        if start is not None:
            assert _keep(job, ln["n"], start, end)
    if done:
        browser.finish(job, [])


def _mine_with(monkeypatch, picked, words, job=None):
    """`Steps.mine` with Anki Miner's call stood in -> [(video, subtitle, offset, names, [(word, line_start)])]."""
    sent = []

    def one(self, lang, j, p, ws, attempt):
        sent.append((p["video"], p["subtitle"], p["offset"], p["names"], [(w["word"], w["line_start"]) for w in ws]))
        return {"outcomes": [dict(w, outcome="made") for w in ws], "app": "3.12.0", "doubt": False}
    monkeypatch.setattr(runner.Steps, "_mine_one", one)
    got = runner.Steps.mine(runner.Steps.__new__(runner.Steps), "ja", job or {"id": 412}, picked, words, 1)
    return sent, got


# --- the hand-off ---------------------------------------------------------------------------------------------------- #
def test_a_jobs_lines_are_its_words_lines_once_each_widened_as_their_cards_are():
    lines, _index = browser.lines_for(_words(), CUES)
    browser.hand_off(412, WEB, "雲の上の郵便屋さん S01E03", lines)
    assert [(ln["n"], ln["start"], ln["end"]) for ln in lines] == [(0, 705.29, 708.84), (1, 709.0, 915.5)]
    assert lines[1]["text"] == "朝ごはんを五分で作る 古本屋めぐりは楽しい"
    assert browser.state(412) == "waiting"


def test_a_words_line_is_the_cue_nearest_its_start_found_by_halving_as_the_scan_found_it():
    """`lines_for` finds each word's cue by halving the sorted starts (words × log cues) — the same cue #474's scan of
    every cue chose (words × cues), its first on a tie, before the first cue, after the last and between two."""
    def scan(start):                            # #474's rule, as it was
        starts = [c[0] for c in EP8]
        return min(range(len(starts)), key=lambda i: abs(starts[i] - start))
    rng = random.Random(474)
    probes = [0.0, 129.708, 130.0, 197.729, 197.7290001, 1241.792, 3000.0, (265.75 + 337.042) / 2]
    probes += [rng.uniform(0, 2300) for _ in range(300)]
    for start in probes:
        lines, _index = browser.lines_for([_ep8_word("語", start)], EP8)
        assert lines[0]["start"] == EP8[scan(start)][0], start


def test_a_clips_own_subtitle_holds_exactly_the_cues_inside_it_a_long_cue_too():
    """`clip_subtitle` halves to the clip's first cue (log cues + the cues inside, per clip), and keeps every cue that
    overlaps the clip — a long cue that began well before it as well — each cut to the clip, in clip time."""
    cues = sorted(EP8 + [(1200.0, 1300.0, "（雷鳴）")])
    os.makedirs(browser.place(9))
    for start, end in ((1240.5, 1247.5), (1199.0, 1201.0), (2211.0, 2216.0), (0.0, 5.0), (1301.0, 1302.0)):
        path = browser.clip_subtitle(9, 0, cues, start, end)
        want = [(round(max(s, start) - start, 3), round(min(e, end) - start, 3), t) for s, e, t in cues
                if e > start and s < end]
        assert [(round(a, 3), round(b, 3), t) for a, b, t in browser.read_srt(path)] == want, (start, end)


def test_a_clip_is_kept_whole_through_the_doors_stream_and_one_cut_short_leaves_nothing():
    """The clip is streamed by the door (`door.Call.save`: whole, or nothing) and its times kept beside it; a body
    that ends early (a tab closed mid-upload) leaves no clip, no times and no part file — the line still waits."""
    lines, _index = browser.lines_for(_words(), CUES)
    browser.hand_off(412, WEB, "t", lines)

    def cut_short(path):
        raise door.BodyError(400, "the body ended before its Content-Length")
    with pytest.raises(door.BodyError):
        browser.keep_clip(412, 0, cut_short, 704.29, 709.84)
    assert sorted(os.listdir(browser.place(412))) == [browser.LINES], "nothing of the clip kept"
    assert [ln["n"] for ln in browser.waiting()[0]["lines"]] == [0, 1]
    assert _keep(412, 0, 704.29, 709.84)
    assert browser.clip(412, 0)[1] == {"start": 704.29, "end": 709.84}
    assert not [p for p in os.listdir(browser.place(412)) if p.endswith(".part") or p.endswith(".got")]
    assert [ln["n"] for ln in browser.waiting()[0]["lines"]] == [1]
    assert not _keep(412, 7, 1.0, 2.0) and not _keep(999, 0, 1.0, 2.0), "no such line, no such job: nothing kept"


def test_what_waits_lists_only_the_lines_still_missing_a_clip_oldest_job_first():
    for job, words in ((431, [_ep8_word("大物", 337.042), _ep8_word("ワシ", 2044.292)]), (420, [_ep8_word("王冠", 2212.917)])):
        lines, _index = browser.lines_for(words, EP8)
        browser.hand_off(job, WEB, "俺のこと、なんか言ってた？ S01E08", lines)
    assert _keep(431, 1, 2043.5, 2047.4)
    os.makedirs(os.path.join(browser.folder(), "b77-old"))         # (not a job's folder: never listed)
    jobs = browser.waiting()
    assert [j["job"] for j in jobs] == [420, 431]
    assert jobs[1]["lines"] == [{"n": 0, "start": 337.042, "end": 339.917}]
    assert set(jobs[1]) == {"job", "site", "video_id", "url", "title", "pad_before", "pad_after", "rev", "lines"}
    assert browser.waiting_lines() == 2, "the Settings row's count: every line still missing a clip"
    browser.finish(420, [{"n": 0, "why": "seek failed"}])
    assert [j["job"] for j in browser.waiting()] == [431] and browser.waiting_lines() == 1


# --- Connect's side -------------------------------------------------------------------------------------------------- #
def test_connect_hands_the_lines_off_and_waits_for_ukai_with_plain_words():
    ledger, job = _Ledger(), {"id": 412, "item_id": 7}
    with pytest.raises(runner.Wait) as w:
        runner._browser_clips(_Steps(), ledger, "ja", job, _picked(_srt(412, CUES)))
    assert w.value.reason == runner.BROWSER_WAIT and w.value.resume == "mining" and w.value.look
    assert runner.BROWSER_WAIT == "Waits for Ukai: Record now in its menu."
    handed = browser.waiting()
    assert handed[0]["job"] == 412 and handed[0]["video_id"] == "81234567"
    assert handed[0]["title"] == "雲の上の郵便屋さん S01E03"
    with pytest.raises(runner.Wait):            # looked at again: still waiting, nothing handed twice
        runner._browser_clips(_Steps(), ledger, "ja", job, _picked(_srt(412, CUES)))
    assert browser.handed(412) == {(705.29, 708.84): 0, (709.0, 915.5): 1} and not ledger.needs


def test_once_done_each_clip_is_a_video_of_its_own_and_a_lost_line_is_said_plainly():
    ledger, job = _Ledger(), {"id": 412, "item_id": 7}
    picked = _picked(_srt(412, CUES))
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert _keep(412, 0, 704.29, 709.84)
    assert browser.finish(412, [{"n": 1, "why": "seek failed"}])
    got = runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert [w["word"] for w in got["words"]] == ["発見", "話す"] and {w["clip"] for w in got["words"]} == {0}
    clip = got["clips"]["0"]
    assert clip["shift"] == 704.29 and clip["video"].endswith("clip-0.webm")
    assert browser.read_srt(clip["subtitle"]) == [(1.0, 4.55, "小さな発見を話そう"), (4.71, 5.55, "朝ごはんを五分で作る")], \
        "its lines in clip time"
    (kind, say), = ledger.needs
    assert kind == runner.BROWSER_LINE
    assert say == "雲の上の郵便屋さん: the line at 11:49 (「朝ごはんを五分で作る 古本屋めぐりは楽しい」) wasn't recorded by " \
                  "Ukai (seek failed). Mine it to ask again."


def test_no_clip_at_all_ends_the_job_with_words_to_ask_again():
    ledger, job = _Ledger(), {"id": 412, "item_id": 7}
    picked = _picked(_srt(412, CUES))
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    browser.finish(412, [{"n": 0, "why": "the tab was closed"}, {"n": 1, "why": "the tab was closed"}])
    with pytest.raises(runner._Finished):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked, record=False)
    assert ledger.states[-1][0] == "skipped" and ledger.states[-1][1]["reason"] == runner.BROWSER_NONE
    assert len(ledger.needs) == 2 and not os.path.exists(browser.place(412)), "its folder gone"


def test_a_stopped_recording_leaves_its_lines_waiting_and_its_clips_kept():
    """Ukai stopped mid-job (its window closed: no `done`): the lines it recorded keep their clips, the rest are
    still listed, and Connect's job goes on waiting — at every look, and after a restart's sweep of the fetched
    videos (`online.sweep`: never the browser's folder)."""
    ledger, job = _Ledger(), {"id": 412, "item_id": 7}
    picked = _picked(_srt(412, CUES))
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert _keep(412, 0, 704.29, 709.84)
    online.sweep()
    for _look in range(2):
        with pytest.raises(runner.Wait) as w:
            runner._browser_clips(_Steps(), ledger, "ja", job, picked)
        assert w.value.reason == runner.BROWSER_WAIT
    assert [ln["n"] for ln in browser.waiting()[0]["lines"]] == [1]
    assert browser.clip(412, 0) is not None and not ledger.needs and not ledger.states


def test_anki_miner_gets_one_episode_a_clip_with_the_lines_start_in_clip_time(monkeypatch):
    """`Steps.mine`: a run a clip — its webm as the video, its own .srt, offset 0, the words' line start moved into clip
    time; the cards' Source still names the transcript (`names`). The outcomes come back by word."""
    words = [dict(w, clip=0) for w in _words()[:2]] + [dict(_words()[2], clip=1)]
    picked = {"names": ["Processed", "雲の上の郵便屋さん S01E03 [netflix-81234567]"], "words": words,
              "clips": {"0": {"video": "c0.webm", "subtitle": "c0.srt", "shift": 704.29},
                        "1": {"video": "c1.webm", "subtitle": "c1.srt", "shift": 708.0}}}
    sent, got = _mine_with(monkeypatch, picked, words)
    assert sent == [("c0.webm", "c0.srt", 0.0, picked["names"], [("発見", 1.0), ("話す", 1.0)]),
                    ("c1.webm", "c1.srt", 0.0, picked["names"], [("古本屋", 204.0)])]
    assert [o["outcome"] for o in got["outcomes"]] == ["made"] * 3


def test_a_word_cut_from_another_episodes_line_is_never_handed_to_ukai_and_goes_with_that_episode(monkeypatch):
    """Kantan-SD 6: a word whose better line is in another episode on disk (`from`) is cut there, as any job's: never
    a line for Ukai to record (it isn't this episode's), never dropped for want of a clip, and sent to Anki Miner with
    that episode (`_mine_spread`), never on a clip."""
    ledger, job = _Ledger(), {"id": 412, "item_id": 7}
    elsewhere = {"word": "散歩", "reading": "さんぽ", "line_start": 12.0, "line_expansion": [0, 0], "from": 31,
                 "own": {"word": "散歩", "reading": "さんぽ", "line_start": 700.0, "line_expansion": [0, 0]}}
    picked = dict(_picked(_srt(412, CUES), _words() + [elsewhere]),
                  sources={"31": {"video": "ep31.mkv", "subtitle": "ep31.srt", "offset": 0.0, "title": "第31話"}})
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert set(browser.handed(412)) == {(705.29, 708.84), (709.0, 915.5)}, "only this episode's own lines"
    assert _keep(412, 0, 704.29, 709.84) and _keep(412, 1, 708.2, 916.3)
    browser.finish(412, [])
    got = runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert [w["word"] for w in got["words"]] == ["発見", "話す", "古本屋", "散歩"] and not ledger.needs
    spread = []
    monkeypatch.setattr(runner.Steps, "_mine_spread", lambda self, lang, j, p, ws, attempt: (
        spread.append([w["word"] for w in ws]),
        {"outcomes": [dict(w, outcome="made") for w in ws], "app": "3.12.0", "doubt": False})[1])
    sent, out = _mine_with(monkeypatch, got, got["words"], job)
    assert [[w for w, _s in run[4]] for run in sent] == [["発見", "話す"], ["古本屋"]] and spread == [["散歩"]]
    assert [o["word"] for o in out["outcomes"]] == ["発見", "話す", "古本屋", "散歩"]


def test_a_netflix_episode_is_picked_from_its_own_cues_never_downloaded(tmp_path, monkeypatch):
    """`Steps.download` for Netflix / Disney+: no fetch, no YouTube tick — the transcript's cues (its sidecar's start
    and end) as the subtitle the words are picked from; a transcript that kept no times is said, never fetched."""
    import json
    from app import path_utils
    transcript = tmp_path / "Processed" / "雲の上の郵便屋さん S01E03 [netflix-81234567].txt"
    transcript.parent.mkdir()
    transcript.write_text("小さな発見を話そう\n", encoding="utf-8")
    side = str(transcript)[:-len(".txt")] + path_utils.SIDECAR_SUFFIX
    with open(side, "w", encoding="utf-8") as f:
        json.dump({"cues": [[t, s, e] for s, e, t in CUES]}, f, ensure_ascii=False)

    class _Store:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def item(self, item_id):
            return {"rel_path": "Processed/" + transcript.name}
    monkeypatch.setattr(path_utils, "get_data_path", lambda lang: str(tmp_path))
    steps = runner.Steps.__new__(runner.Steps)
    steps._settings = lambda lang: pytest.fail("nothing is read for a browser site")
    steps._open = lambda lang: _Store()
    srt, again = steps.download("ja", {"id": 9, "item_id": 3}, {"site": "netflix", "url": WEB["url"]})
    assert srt == again and browser.read_srt(srt) == [(s, e, t) for s, e, t in CUES]
    os.remove(side)
    with pytest.raises(runner.Needs) as n:
        steps.download("ja", {"id": 10, "item_id": 3}, {"site": "netflix", "url": WEB["url"]})
    assert n.value.say == runner.BROWSER_NO_CUES


def test_a_wait_for_ukai_says_so_on_its_row():
    from app.connect import feed
    from app.services import view_rows as vr
    item = feed.Item(kind=feed.WAITING, words=feed.WORDS[feed.WAITING], tip=runner.BROWSER_WAIT, job=476, made=0,
                     total=0)
    st = vr._connected(vr.Status("mine", vr.STRINGS["mine"], "", "ok"), item, "video", online="netflix")
    assert (st.kind, st.label, st.tip) == ("waiting", "Waits for Ukai", runner.BROWSER_WAIT)


# --- a pick again after the hand-off (Mattias's jobs 461–464, 2026-11-15) -------------------------------------------- #
def _record_all(job, pad=0.7):
    """Ukai's round: what waits (`GET /v1/jobs`), then a clip for each line still missing one (`pad` around it)."""
    for line in next(j for j in browser.waiting() if j["job"] == job)["lines"]:
        assert _keep(job, line["n"], line["start"] - pad, line["end"] + pad)


def test_a_pick_again_after_the_hand_off_never_gives_a_word_another_lines_clip(monkeypatch):
    """Lines handed off in a pick's order, clips posted in two rounds, a pick again meanwhile ranking other words
    first. Each word still gets its own line's clip (matched by the line's place, never its order), the new pick's
    extra line is asked for, and every run Anki Miner gets has its line inside its clip — never the −970.425 s that
    stopped the run file."""
    job, ledger = {"id": 464, "item_id": 7}, _Ledger()
    srt = _srt(464, EP8)
    first = [_ep8_word("大物", 337.042), _ep8_word("ワシ", 2044.292), _ep8_word("王冠", 2212.917),
             _ep8_word("初日", 265.75), _ep8_word("稲妻", 1241.792)]
    picked = _picked(srt, first)
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    for line in browser.waiting()[0]["lines"][:2]:          # round one: two clips, then the tab is busy
        assert _keep(464, line["n"], line["start"] - 0.7, line["end"] + 0.7)
    again = [_ep8_word("稲妻", 1241.792), _ep8_word("貴様", 129.708), _ep8_word("初日", 265.75),
             _ep8_word("大物", 337.042), _ep8_word("ワシ", 2044.292)]
    picked = dict(picked, words=again)
    with pytest.raises(runner.Wait):                        # the new line is added, never renumbering the others
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert browser.handed(464)[(129.708, 131.458)] == 5
    rev = browser.waiting()[0]["rev"]
    assert rev == 1, "the lines were added to: a `done` for the first set would be stale"
    _record_all(464)
    assert browser.finish(464, [], rev=rev)
    got = runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert not ledger.needs
    sent, _out = _mine_with(monkeypatch, got, got["words"], job)
    assert len(sent) == 5
    for video, _sub, _off, _names, starts in sent:
        n = int(os.path.basename(video)[len("clip-"):-len(".webm")])
        times = browser.clip(464, n)[1]
        assert all(0 <= s <= times["end"] - times["start"] for _w, s in starts), (video, starts)
    assert {w["word"]: round(w["line_start"] - got["clips"][str(w["clip"])]["shift"], 3) for w in got["words"]} == \
        {w: 0.7 for w in ("稲妻", "貴様", "初日", "大物", "ワシ")}


def test_a_job_saved_with_clips_matched_by_order_is_matched_again_from_its_folder():
    job, ledger = {"id": 461, "item_id": 7}, _Ledger()
    srt = _srt(461, EP8)
    words = [_ep8_word("王冠", 2212.917), _ep8_word("稲妻", 1241.792)]
    lines, _index = browser.lines_for(words, EP8)
    browser.hand_off(461, WEB, "俺のこと、なんか言ってた？ S01E08", lines)
    for n, (start, end) in ((0, (2212.216667, 2216.448667)), (1, (1241.083667, 1247.662333))):
        assert _keep(461, n, start, end)
    browser.finish(461, [])
    stuck = dict(_picked(srt), words=[dict(words[0], clip=0), dict(words[1], clip=0)],      # 稲妻 on 王冠's clip
                 clips={"0": {"video": "x", "subtitle": "y", "shift": 2212.216667}})
    got = runner._browser_clips(_Steps(), ledger, "ja", job, stuck)
    assert {w["word"]: w["clip"] for w in got["words"]} == {"王冠": 0, "稲妻": 1}
    assert got["clips"]["1"]["shift"] == 1241.083667


def test_a_clip_that_doesnt_hold_its_line_is_a_lost_line_never_sent():
    job, ledger = {"id": 463, "item_id": 7}, _Ledger()
    picked = _picked(_srt(463, EP8), [_ep8_word("大物", 337.042), _ep8_word("ワシ", 2044.292)])
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert _keep(463, 0, 336.3, 340.9)
    assert _keep(463, 1, 2212.2, 2216.4)                    # another line's moment
    browser.finish(463, [])
    got = runner._browser_clips(_Steps(), ledger, "ja", job, picked)
    assert [w["word"] for w in got["words"]] == ["大物"]
    (kind, say), = ledger.needs
    assert "34:04" in say and "its clip doesn't hold the line" in say


# --- a job made again for the same episode (Mattias, トークサバイバー Ep 3 / 6, 2026-11-16) ---------------------------- #
def test_a_job_made_again_takes_the_earlier_jobs_clips_and_goes_straight_to_its_cards():
    words = [_ep8_word("大物", 337.042), _ep8_word("稲妻", 1241.792), _ep8_word("初日", 265.75)]
    _recorded(470, words)
    ledger, job = _JobsLedger([(470, 2900), (476, 2900), (475, 2905)]), {"id": 476, "item_id": 2900}
    got = runner._browser_clips(_Steps(), ledger, "ja", job, _picked(_srt(476, EP8), list(reversed(words))))
    assert sorted(w["word"] for w in got["words"]) == ["初日", "大物", "稲妻"] and not ledger.needs
    for w in got["words"]:
        assert 0 <= w["line_start"] - got["clips"][str(w["clip"])]["shift"] <= 1.0
    assert browser.waiting() == [], "nothing for Ukai to record"


def test_only_the_lines_no_earlier_job_holds_wait_for_recording():
    words = [_ep8_word("大物", 337.042), _ep8_word("稲妻", 1241.792), _ep8_word("初日", 265.75)]
    _recorded(473, words, clips={1: (2212.2, 2216.4), 2: (None, None)}, done=False)
    ledger, job = _JobsLedger([(473, 2903), (477, 2903)]), {"id": 477, "item_id": 2903}
    with pytest.raises(runner.Wait):
        runner._browser_clips(_Steps(), ledger, "ja", job, _picked(_srt(477, EP8), words))
    (waits,) = browser.waiting()
    assert waits["job"] == 477 and [ln["start"] for ln in waits["lines"]] == [1241.792, 265.75]


def test_a_job_already_waiting_when_the_earlier_clips_were_left_takes_them_at_its_next_look():
    words = [_ep8_word("大物", 337.042), _ep8_word("稲妻", 1241.792)]
    _recorded(473, words)
    lines, _index = browser.lines_for(list(reversed(words)), EP8)
    browser.hand_off(477, WEB, "トークサバイバー！ S01E06", lines)
    ledger, job = _JobsLedger([(473, 2903), (477, 2903)]), {"id": 477, "item_id": 2903}
    got = runner._browser_clips(_Steps(), ledger, "ja", job, _picked(_srt(477, EP8), words))
    assert sorted(w["word"] for w in got["words"]) == ["大物", "稲妻"] and browser.waiting() == []


# --- #474's review (2026-11-16) -------------------------------------------------------------------------------------- #
def test_a_clip_recorded_a_little_late_never_gives_a_negative_line_start(monkeypatch):
    """1: `covers` takes a clip starting up to COVER_SLACK after its line: the line's start in clip time is 0 then,
    never −0.2 (which Anki Miner's run file refuses)."""
    assert browser.covers({"start": 10.2, "end": 13.0}, {"start": 10.0, "end": 12.0})
    words = [dict(_ep8_word("大物", 10.0), clip=0)]
    picked = {"names": ["Processed", "x"], "words": words,
              "clips": {"0": {"video": "c.webm", "subtitle": "c.srt", "shift": 10.2}}}
    sent, _got = _mine_with(monkeypatch, picked, words, {"id": 1})
    assert [s for run in sent for _w, s in run[4]] == [0.0]


def test_the_folder_of_a_job_that_left_is_closed_or_gone_never_listed_for_recording():
    """2: a job that left keeps its folder closed while it holds a clip to take over, else the folder goes; one the
    ledger doesn't know goes; an open job's is untouched. A take-over removes the folder it took from."""
    words = [_ep8_word("大物", 337.042)]
    _recorded(470, words, done=False)                       # dropped, its clip in
    _recorded(475, words, clips={0: (None, None)}, done=False)      # dropped, never recorded
    _recorded(479, words, clips={0: (None, None)}, done=False)      # still waiting
    _recorded(999, words, done=False)                       # a job the ledger no longer knows
    states = {470: "dropped", 475: "dropped", 479: "waiting"}

    class Ledger:
        def job_by_id(self, jid):
            return {"id": jid, "state": states[jid]} if jid in states else None
    runner._close_browser_folders(Ledger())
    assert [j["job"] for j in browser.waiting()] == [479]
    assert browser.folders() == [470, 479] and browser.state(470) == {"failed": []}
    lines, _index = browser.lines_for(words, EP8)
    browser.hand_off(480, WEB, "t", lines)
    assert browser.take_over(480, [470]) == 1 and 470 not in browser.folders()


def test_a_done_for_an_older_set_of_lines_closes_nothing():
    """4: lines added (a pick again) while Ukai recorded the older set: its `done` (rev 0, or none: Ukai before its
    #2) leaves the job listed with the new lines; a `done` naming the lines' rev closes it."""
    lines, _index = browser.lines_for([_ep8_word("大物", 337.042)], EP8)
    browser.hand_off(490, WEB, "t", lines)
    assert _keep(490, 0, 336.3, 340.9)
    browser.add_lines(490, browser.lines_for([_ep8_word("ワシ", 2044.292)], EP8)[0])
    (job,) = browser.waiting()
    assert job["rev"] == 1 and [ln["n"] for ln in job["lines"]] == [1]
    assert browser.finish(490, []) is True and browser.state(490) == "waiting", "a done with no rev, line 1 unrecorded"
    assert browser.finish(490, [], rev=0) is True and browser.state(490) == "waiting", "an older rev"
    assert browser.finish(490, [{"n": 1, "why": "seek failed"}], rev=1) is True
    assert browser.state(490) == {"failed": [{"n": 1, "why": "seek failed"}]}
    browser.add_lines(490, browser.lines_for([_ep8_word("王冠", 2212.917)], EP8)[0])
    assert _keep(490, 2, 2212.2, 2216.4)
    assert browser.finish(490, [{"n": 1, "why": "seek failed"}]) is True, "a done with no rev naming every line"
    assert browser.state(490) == {"failed": [{"n": 1, "why": "seek failed"}]}


def test_clips_are_taken_over_only_from_older_jobs_no_longer_open():
    """6: never from a newer job, nor one still waiting (it would be closed under its own wait)."""
    ledger = _JobsLedger([(465, 2900, "waiting"), (470, 2900, "dropped"), (476, 2900, "waiting"),
                          (480, 2900, "dropped"), (468, 2901, "failed"), (466, 2900, "failed")])
    assert runner._earlier_jobs(ledger, "ja", {"id": 476, "item_id": 2900}) == [470, 466]


# --- off until Ukai 1.0 ---------------------------------------------------------------------------------------------- #
def test_while_ukai_is_off_a_netflix_item_is_no_online_title_for_connect(monkeypatch):
    """`door.EXTENSION_ON` False (as shipped until Ukai 1.0): a Netflix or Disney+ item — only Ukai writes them, or a
    file named `[netflix-<id>]` by hand — is what it was before this lane (a plain transcript: never handed to an
    extension that isn't there, no folder made); on, it is Connect's online title, mined through Ukai. YouTube and
    bilibili.tv are online either way."""
    for on in (False, True):
        monkeypatch.setattr(door, "EXTENSION_ON", on)
        assert online.is_online({"source_type": "netflix"}) is on
        assert online.is_online({"source_type": "disneyplus"}) is on
        assert online.is_online({"source_type": "youtube"}) and online.is_online({"source_type": "bilibili"})
        assert not online.is_online({"source_type": "file"})
    monkeypatch.setattr(door, "EXTENSION_ON", False)
    assert not os.path.exists(browser.folder())


def test_without_ukais_module_connect_never_hands_a_netflix_episode_off(monkeypatch):
    """The module rule (CLAUDE.md §2): with `modules/ukai` absent nothing could record, so Connect's half is off too."""
    import sys
    monkeypatch.setitem(sys.modules, "modules.ukai", None)
    assert not online.is_online({"source_type": "netflix"})


def test_a_word_halfway_between_two_lines_is_on_the_earlier_one():
    """An exact tie (as a walk of every cue chose: the first nearest)."""
    cues = [(10.0, 12.0, "文化祭まで、あと三日しかないよ。"), (20.0, 22.5, "二時間目の授業、ちゃんと聞いてた？")]
    assert browser.lines_for([_ep8_word("授業", 15.0)], cues)[0][0]["start"] == 10.0


def test_connects_look_closes_the_folder_of_a_job_the_ledger_no_longer_knows(tmp_path):
    """Every look at the inbox (`runner._consume`) closes the folders of jobs that left: one the ledger doesn't know,
    holding no clip, goes — so Ukai is never asked to record for it."""
    from app.connect.ledger import Ledger
    from tests.connect.fake_steps import FakeSteps
    lines, _index = browser.lines_for([_ep8_word("大物", 337.042)], EP8)
    browser.hand_off(999, WEB, "t", lines)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert runner._consume(FakeSteps(str(tmp_path), {}), ledger, "ja") is False
    assert browser.folders() == [] and browser.waiting() == []
