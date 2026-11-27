# SPDX-License-Identifier: GPL-3.0-or-later
"""鵜 Ukai's clips in, through the one door (Ukai SPEC §6 U-S4; the v2 half of Mattias's #474, by mattias, onto the
door's Ukai class): a simulated Ukai — the calls `src/delivery.js` makes and CONTRACT.md's v2 shapes (ukai `dev`
c90670c0) — against the real door, a real pairing stand-in, and Connect's real runner with its Anki stood in.

What a wrong answer would cost a learner: another extension (or a web page) reading which episodes they study, or
posting clips into their cards; a clip cut short becoming a card with half a line; a recording Ukai stopped losing
the lines it still owes; a Netflix episode's cards never made — or made from another line's clip.
"""
import http.client
import json
import os
import socket

import pytest

from app import door
from app.connect import browser, online, runner
from app.connect.ledger import Ledger
from modules import ukai
from modules.ukai.tests.test_subtitles_in import ORIGIN, TOKEN, _cues, _free_port
from tests.connect.fake_steps import FakeSteps

OTHER = "chrome-extension://aaaabbbbccccddddeeeeffffgggghhhh"
# Real words on real lines of each language's episode (Test Resources: placed_episode.srt, night_market.srt)
WORDS = {"ja": [("文化祭", "ブンカサイ", 0), ("授業", "ジュギョウ", 1), ("準備", "ジュンビ", 3)],
         "zh": [("频道", "pin2 dao4", 0), ("夜市", "ye4 shi4", 1), ("珍珠奶茶", "zhen1 zhu1 nai3 cha2", 4)]}
WEBM = b"\x1aE\xdf\xa3\x9fB\x86\x81\x01B\xf7\x81\x01webm" * 64     # an EBML header's first bytes, then the clip


class _Pairing:
    def __init__(self):
        self.kept = (ORIGIN, TOKEN)

    def __call__(self):
        return self.kept


@pytest.fixture
def ukai_door(monkeypatch):
    """The door with Ukai's class on (as at Ukai 1.0) and the module's routes; Connect's half rides the same switch."""
    monkeypatch.setattr(door, "EXTENSION_ON", True)
    monkeypatch.setattr(door, "EXT_PORT", _free_port())
    pairing = _Pairing()
    ext = door.Extension(ukai.routes(writer=lambda: None, settings=lambda: {}), pairing)
    d = door.Door({}, os.path.join(os.environ["SURASURA_TEST_ROOT"], "results"), extension=ext).start()
    yield d, pairing
    d.stop()


def _ask(d, method, path, body=None, token=TOKEN, origin=ORIGIN, headers=None):
    """One call as Ukai's service worker makes it (`delivery.js`): a GET with no Origin, a POST with its own."""
    conn = http.client.HTTPConnection(door.HOST, d.ext_port, timeout=30)
    sent = {"Host": f"{door.HOST}:{d.ext_port}"}
    if origin and method == "POST":
        sent["Origin"] = origin
    if token is not None:
        sent[door.EXT_TOKEN_HEADER] = token
    sent.update(headers or {})
    if isinstance(body, dict):
        body, sent["Content-Type"] = json.dumps(body).encode("utf-8"), "application/json"
    conn.request(method, path, body=body, headers=sent)
    r = conn.getresponse()
    got = json.loads(r.read().decode("utf-8"))
    conn.close()
    return r.status, got


def _jobs(d, **kw):
    return _ask(d, "GET", "/v1/jobs", **kw)


def _clip(d, job, n, start, end, data=WEBM, **kw):
    """`postClip`: the clip's bytes, video/webm, its first and last frame's video time."""
    return _ask(d, "POST", f"/v1/jobs/{job}/clips/{n}", data, headers={
        "Content-Type": "video/webm", "X-Clip-Start": str(start), "X-Clip-End": str(end)}, **kw)


def _done(d, job, failed=(), **kw):
    """`postDone` as ukai `dev` sends it: {"failed": [...]} (no `rev` before its #2)."""
    return _ask(d, "POST", f"/v1/jobs/{job}/done", {"failed": list(failed)}, **kw)


def _handed(language, job=412):
    """A Connect job's hand-off, as `runner._browser_clips` writes it, on the language's real lines."""
    cues = [tuple(c) for c in _cues(language)]
    words = [{"word": w, "reading": r, "line_start": cues[at][0], "line_expansion": [0, 0]}
             for w, r, at in WORDS[language]]
    lines, _index = browser.lines_for(words, cues)
    browser.hand_off(job, {"site": "netflix", "url": "https://www.netflix.com/watch/80000003",
                           "video_id": "80000003"}, "第3話", lines)
    return lines


# --- the routes ------------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", ["ja", "zh"])
def test_ukai_lists_what_waits_posts_each_clip_whole_and_ends_the_job(ukai_door, language):
    d, _p = ukai_door
    lines = _handed(language)
    status, got = _jobs(d)
    assert status == 200 and [j["job"] for j in got["jobs"]] == [412]
    job = got["jobs"][0]
    assert job["lines"] == [{"n": ln["n"], "start": ln["start"], "end": ln["end"]} for ln in lines]
    assert (job["site"], job["video_id"], job["pad_before"], job["pad_after"], job["rev"]) == \
        ("netflix", "80000003", 1.0, 1.0, 0)
    first = lines[0]
    assert _clip(d, 412, 0, first["start"] - 1.0, first["end"] + 1.0) == (200, {"ok": True})
    with open(os.path.join(browser.place(412), "clip-0.webm"), "rb") as f:
        assert f.read() == WEBM, "streamed whole"
    assert not [p for p in os.listdir(browser.place(412)) if ".part" in p or p.endswith(".got")]
    assert [ln["n"] for ln in _jobs(d)[1]["jobs"][0]["lines"]] == [1, 2]
    assert _done(d, 412, [{"n": 1, "why": "seek failed"}, {"n": 2, "why": "seek failed"}]) == (200, {"ok": True})
    assert _jobs(d)[1]["jobs"] == [], "done: no longer listed"
    assert browser.state(412) == {"failed": [{"n": 1, "why": "seek failed"}, {"n": 2, "why": "seek failed"}]}
    assert _clip(d, 412, 1, 1.0, 5.0)[0] == 404, "a clip after done: Ukai skips it"
    assert _done(d, 412)[0] == 404


def test_a_job_or_line_that_doesnt_wait_is_a_404_and_its_body_is_read_first(ukai_door, monkeypatch):
    """No such line, no such job (dropped meanwhile): 404, Ukai skips it — after the whole clip is read (a 2 MB body
    left unread would reset the answer on Windows, and Ukai would retry it for 3½ minutes)."""
    d, _p = ukai_door
    _handed("ja")
    big = WEBM * 2048                                       # ~2 MB, over the door's 1 MB drain
    assert _clip(d, 412, 7, 1.0, 5.0, big)[0] == 404
    assert _clip(d, 999, 0, 1.0, 5.0, big)[0] == 404
    assert sorted(os.listdir(browser.place(412))) == [browser.LINES]


@pytest.mark.parametrize("start, end", [("abc", "5"), ("5", "1"), ("-1", "3"), ("nan", "3"), ("1", "inf")])
def test_a_clip_without_its_times_is_a_400_and_nothing_is_kept(ukai_door, start, end):
    d, _p = ukai_door
    _handed("ja")
    status, got = _clip(d, 412, 0, start, end)
    assert status == 400 and "X-Clip-Start" in got["why"]
    assert sorted(os.listdir(browser.place(412))) == [browser.LINES]


def test_a_clip_over_the_limit_is_refused_unread(ukai_door, monkeypatch):
    d, _p = ukai_door
    _handed("ja")
    monkeypatch.setattr(door, "EXT_MAX_STREAM", 64)
    assert _clip(d, 412, 0, 1.0, 4.2, b"x" * 65)[0] == 413
    assert sorted(os.listdir(browser.place(412))) == [browser.LINES]


def test_a_clip_cut_short_leaves_nothing_and_its_line_still_waits(ukai_door):
    """A tab closed mid-upload: the body ends before its Content-Length — a 400, no clip, no times, no part file, and
    the line is still listed for the next round."""
    d, _p = ukai_door
    _handed("ja")
    with socket.create_connection((door.HOST, d.ext_port), timeout=10) as s:
        s.sendall((f"POST /v1/jobs/412/clips/0 HTTP/1.1\r\nHost: {door.HOST}:{d.ext_port}\r\nOrigin: {ORIGIN}\r\n"
                   f"{door.EXT_TOKEN_HEADER}: {TOKEN}\r\nX-Clip-Start: 0.0\r\nX-Clip-End: 4.2\r\n"
                   "Content-Type: video/webm\r\nContent-Length: 100000\r\n\r\n").encode() + WEBM[:500])
        s.shutdown(socket.SHUT_WR)
        answer = s.recv(4096).decode("utf-8", "replace")
    assert answer.split(" ", 2)[1] == "400"
    assert sorted(os.listdir(browser.place(412))) == [browser.LINES], "nothing of the clip kept"
    assert [ln["n"] for ln in _jobs(d)[1]["jobs"][0]["lines"]] == [0, 1, 2]


def test_a_stopped_recording_leaves_its_lines_waiting(ukai_door):
    """Ukai stopped mid-job (its window closed: `walk.js` posts no `done`): the clip it posted is kept, the rest are
    still listed — after Connect's restart sweep of fetched videos too."""
    d, _p = ukai_door
    lines = _handed("zh")
    assert _clip(d, 412, 0, lines[0]["start"] - 0.5, lines[0]["end"] + 0.5)[0] == 200
    online.sweep()
    assert [ln["n"] for ln in _jobs(d)[1]["jobs"][0]["lines"]] == [1, 2]
    assert browser.state(412) == "waiting" and browser.clip(412, 0) is not None


@pytest.mark.parametrize("call", ["jobs", "clip", "done"])
def test_another_origin_or_no_pairing_gets_nothing(ukai_door, call):
    """Only the paired Ukai: another extension's Origin (403), a web page's (403), no token or another (401), and
    once forgotten (401) — nothing listed, nothing kept, nothing ended."""
    d, pairing = ukai_door
    _handed("ja")

    def ask(**kw):
        if call == "jobs":
            return _ask(d, "GET", "/v1/jobs", headers={"Origin": kw.pop("origin")} if kw.get("origin") else None,
                        **{k: v for k, v in kw.items() if k != "origin"})
        if call == "clip":
            return _clip(d, 412, 0, 0.0, 4.2, **kw)
        return _done(d, 412, **kw)
    for kw, status in (({"origin": OTHER}, 403), ({"origin": "https://www.netflix.com"}, 403),
                       ({"token": None}, 401), ({"token": "W" * 32}, 401)):
        got = ask(**kw)
        assert got[0] == status and "jobs" not in got[1], kw
    pairing.kept = None                                     # *Forget Ukai*
    assert ask()[0] == 401
    assert sorted(os.listdir(browser.place(412))) == [browser.LINES] and browser.state(412) == "waiting"


def test_hello_says_ukai_can_send_clips(ukai_door):
    d, _p = ukai_door
    status, got = _ask(d, "GET", "/v1/hello", token=None)
    # (contract v2 is the clips; with U-S3's YouTube links also here it is v3 = v2 + the links: train 97's join)
    assert status == 200 and got["contract"] == ukai.CONTRACT == 3


# --- end to end: Connect's job, Ukai's round, the cards ---------------------------------------------------------- #
class BrowserSteps(FakeSteps):
    """FakeSteps whose items in the plan's `online` are Netflix episodes: no download — the transcript's cues (the
    language's real .srt, as Ukai sent them) handed to the job's folder by `browser.subtitle`; the words picked on
    real lines; Anki Miner stood in (FakeSteps' cards), noting each clip it was given."""

    def __init__(self, folder, language, plan=None):
        super().__init__(folder, plan)
        self.language, self.clips_seen = language, []
        self.cues = [tuple(c) for c in _cues(language)]
        transcript = os.path.join(folder, "Processed", "第3話 [netflix-80000003].txt")
        os.makedirs(os.path.dirname(transcript), exist_ok=True)
        with open(transcript, "w", encoding="utf-8") as f:
            f.write("\n".join(t for _s, _e, t in self.cues))
        from app.path_utils import SIDECAR_SUFFIX
        with open(transcript[:-len(".txt")] + SIDECAR_SUFFIX, "w", encoding="utf-8") as f:
            json.dump({"cues": [[t, s, e] for s, e, t in self.cues]}, f, ensure_ascii=False)
        self.transcript = transcript

    def online(self, lang, job):
        if job["item_id"] not in (self.plan.get("online") or ()):
            return None
        return {"site": "netflix", "url": "https://www.netflix.com/watch/80000003",
                "names": ["Processed", "第3話 [netflix-80000003]"]}

    def download(self, lang, job, web, on_progress=None):
        assert web["site"] in online.BROWSER_SITES, "only a browser site comes here in this test"
        self.log.append(("download", job["item_id"]))
        srt = browser.subtitle(job["id"], self.transcript)
        return srt, srt

    def pick(self, lang, job, video, subtitle=None):
        got = super().pick(lang, job, video)
        words = {w: (r, at) for w, r, at in WORDS[self.language]}
        got["words"] = [dict(w, line_start=self.cues[words[w["word"]][1]][0],
                             line_end=self.cues[words[w["word"]][1]][1], line_expansion=[0, 0])
                        for w in got["words"] if w["word"] in words]
        return got

    def mine(self, lang, job, picked, words, attempt):
        for w in words:
            c = picked["clips"][str(w["clip"])]
            self.clips_seen.append((w["word"], os.path.isfile(c["video"]), browser.read_srt(c["subtitle"])))
        return super().mine(lang, job, picked, words, attempt)

    def drop_browser(self, job):
        browser.drop(job["id"])


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_netflix_episodes_cards_are_made_from_the_clips_ukai_posts(ukai_door, tmp_path, language):
    """The card's whole path: Connect picks the episode's words from its own cues and waits (*Waits for Ukai*); Ukai
    lists the job, records each line and posts its clip and `done`; Connect's next look makes a card a word from its
    line's clip — the clip on disk while Anki Miner cuts it, its own subtitle holding the line — and the folder goes."""
    d, _p = ukai_door
    words = [(w, r) for w, r, _at in WORDS[language]]
    plan = {"line": {language: [1]}, "queue": {language: [1]}, "online": [1], "words": {"1": words}}
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        steps = BrowserSteps(str(tmp_path), language, plan)
        runner.run({}, [language], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        (job,) = ledger.jobs(language)
        assert job["state"] == "waiting" and job["reason"] == runner.BROWSER_WAIT, job
        assert not steps.anki.words(), "no card before the clips"

        status, got = _jobs(d)                              # Ukai's round (`walk.js` → `delivery.js`)
        (listed,) = got["jobs"]
        assert status == 200 and listed["job"] == job["id"] and len(listed["lines"]) == 3
        for line in listed["lines"]:
            start, end = line["start"] - listed["pad_before"], line["end"] + listed["pad_after"]
            assert _clip(d, listed["job"], line["n"], max(0.0, start), end)[0] == 200
        assert _done(d, listed["job"])[0] == 200

        runner.run({}, [language], steps=steps, ledger=ledger, sleep=lambda s: None, looks=1)
        assert ledger.job_by_id(job["id"])["state"] == "done", ledger.job_by_id(job["id"])
    assert sorted(steps.anki.words()) == sorted(w for w, _r in words), "a card a word"
    by_word = {w: (on_disk, cues) for w, on_disk, cues in steps.clips_seen}
    cues = [tuple(c) for c in _cues(language)]
    for w, _r, at in WORDS[language]:
        on_disk, clip_cues = by_word[w]
        assert on_disk, "the clip is there while Anki Miner cuts it"
        assert any(t == cues[at][2] for _s, _e, t in clip_cues), "its own subtitle holds the word's line"
    assert not os.path.exists(browser.place(job["id"])), "its folder gone once the cards are made"
    assert ("download", 1) in steps.log and not [e for e in steps.log if e[0] == "fetch"]


def test_while_ukai_is_off_connect_never_hands_a_netflix_episode_off(tmp_path, monkeypatch):
    """`door.EXTENSION_ON` False (as shipped): Connect's real `Steps.online` finds no online title in a Netflix item
    (`online.is_online`), so nothing is handed off and no folder is made — the item is what it was before this lane."""
    monkeypatch.setattr(door, "EXTENSION_ON", False)
    assert not online.is_online({"source_type": "netflix", "rel_path": "Processed/第3話 [netflix-80000003].txt"})
    assert not os.path.exists(browser.folder())


def test_the_windows_class_keeps_ukais_job_routes_behind_the_pairing(tmp_path):
    """As the window builds it (`Pairing.extension`, `ShellWindow.ukai_extension`): only the pairing's own two routes
    and hello are open — what waits, a clip and a done each need the paired token and Origin."""
    from app.services import ukai_pairing as up
    ext = up.Pairing(None, where=str(tmp_path / up.FILE)).extension(ukai.routes(writer=lambda: None,
                                                                               settings=lambda: {}))
    for method, path in (("GET", "/v1/jobs"), ("POST", "/v1/jobs/412/clips/0"), ("POST", "/v1/jobs/412/done")):
        found = ext.route(method, path)
        assert found is not None and found[2] is False, (method, path)
    assert ext.route("GET", "/v1/hello")[2] is True


def test_a_large_clip_with_bad_times_is_read_before_its_400(ukai_door, monkeypatch):
    """The door drains only a small body by itself (≤ 1 MB): a clip's 400 reads the body first, as its 404 does, so
    Ukai gets the answer instead of a reset."""
    d, _p = ukai_door
    _handed("ja")
    read, skip = [], door.Call.skip
    monkeypatch.setattr(door.Call, "skip", lambda self, limit=None: read.append(skip(self, limit)) or read[-1])
    big = WEBM * 2048
    status, got = _clip(d, 412, 0, "nan", "3", big)
    assert status == 400 and read == [len(big)]


def test_a_done_naming_a_line_by_a_list_is_answered(ukai_door):
    d, _p = ukai_door
    _handed("ja")
    assert _done(d, 412, failed=[{"n": [0], "why": "x"}])[0] == 200
