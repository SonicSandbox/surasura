"""SWAP-TIME: ⇄ and *Add now* work on every subtitle line of the journey, with or without its video, whatever
*Play a line's own audio* says (the lead's call, option A; 3.0.21).

The journey gives a subtitle line its time only when it found the episode's video and *Play a line's own audio* is on
(`journey_render.Sources.prepare` / `times`). Every other line the page keys itself (`p<hash>`, page.html `lineId`),
and the door used to refuse that id with *"it has no time in its file"* — so with the audio switch off every line
was refused, video or not, though the time is right there in the subtitle. Now the page also sends the line's item and
text (`pickLine`), and the door finds the line in that one subtitle at the press (`door_routes._line_id`: the render's
own reader, `cues.timeline(...).line`), so the ask is Swap's as before; the answer says whether the episode's video is
on this computer (`video`), and without it the job waits on *No video* — Needs you's *Find video* asks where it is.

What each test holds still, the learner's flow: the page rendered with the audio switch off, its line pressed over the
door's HTTP as the page sends it, Swap's look, Connect's pick, Needs you's cards:
  - a line whose video is here swaps (queued, its job made from that very line), the audio switch off;
  - a line whose video isn't here queues too, its job waits on *No video*, and Needs you shows it with *Find video*;
  - a book's line (no time in any file) is still refused with *no time in its file*, and only it; a line no longer in
    its subtitle is *gone*, never the wrong *no time*.

What a wrong answer costs: Swap refused on every line of an anime library (the tester's report), a card cut from a
line the learner didn't press, or a swap that says *queued* while nothing will ever ask for its video. Real Japanese
(.ass) and Chinese (.srt) subtitles from tests/Test Resources; the library store, the ledger and the door are real.
"""
import gzip
import http.client
import json
import os
from unittest.mock import patch

import pytest

from app import cues, door, library_store
from app import journey_render as jr
from app import static_html_generator as gen
from app.connect import door_routes, runner, swap
from app.services import journey_door, needs, view_rows
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.connect.test_kantan_sl_swap import CASES, JA, ZH, Anki, _lists, ledger  # noqa: F401  (`ledger`: the fixture)
from tests.test_services_play import _video


def _library(lang, video, more=()):
    """The case's real subtitle as the first item in NOW (`more`: other files after it), its video beside it or not,
    Connect on, *Play a line's own audio* off -> (item id, its rel path, its subtitle's path)."""
    path = JA if lang == "ja" else ZH
    folder = h.seed_library(lang, files=[os.path.basename(path), *more], templates=False)
    h.write_settings(target_language=lang, connect_enabled=True, line_player=False)
    if video:
        _video(os.path.join(folder, os.path.splitext(os.path.basename(path))[0] + ".mkv"))
    data_dir, user_files = c.dirs(lang)
    assert library_store.maintain(lang, data_dir, user_files, from_folders=True) == library_store.EXIT_DONE
    _lists(lang)
    with c.store(lang) as s:
        item = next(i for i in s.ids("now") if str(s.item(i)["rel_path"]).endswith(os.path.basename(path)))
        rel = str(s.item(item)["rel_path"]).replace("\\", "/")
    return item, rel, os.path.join(data_dir, *rel.split("/"))


def _cue(lang, text):
    return [q for q in cues.read(JA if lang == "ja" else ZH, lang) if text in (q.text or "")][0]


def _page_line(tmp_path, lang, word, rel, abs_path, text):
    """The journey rendered as the window renders it (*Play a line's own audio* off) -> the word's line as the page
    holds it: (its text, its start or None, its source row [label, kind, ep, play, link, item])."""
    results = tmp_path / "results"
    results.mkdir(exist_ok=True)
    source_map = {rel: {"name": rel.rsplit("/", 1)[-1], "type": "subtitle", "abs": abs_path}}
    rows = [{"Sequence": 1, "Source File": rel.rsplit("/", 1)[-1], "Word": word, "Orth": word, "Forms": word,
             "Reading": "", "Occurrences (File)": 2.0, "Count (High)": 1.0, "Count (Low)": 0.0, "Context 1": text,
             "Src 1": rel}]
    with patch.object(gen, "RESULTS_DIR", str(results)), patch.object(gen, "_load_source_map", lambda: source_map):
        out = jr.render(lang, rows, stats=[{"File": rel.rsplit("/", 1)[-1]}], settings={"line_player": False},
                        stamp="s")
    for chunk in out.chunks:
        data = json.loads(gzip.decompress(chunk).decode("utf-8"))
        for w in data["w"]:
            if w[0] == word:
                ln = (w[9] or [])[0] + [None] * 3
                return ln[0], ln[2], data["src"][ln[1]]
    pytest.fail(f"{lang}: the page holds no line for {word}")


def _page_body(word, text, at, src):
    """The body the page's ⇄ / *Add now* sends (page.html `pickLine`): the word, the line's id (`lineId`: the simple
    Swap's `<item>:<ms>` with a time, else the page's own key), and the line's item and text."""
    item = src[5] if len(src) > 5 else None
    if item is not None and isinstance(at, (int, float)):
        lid = f"{item}:{round(at * 1000)}"
    else:
        hsh = 0x811c9dc5
        for ch in text + "\u0001" + src[0]:
            hsh = ((hsh ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
        lid = f"p{hsh:08x}"
    return {"word": word, "line_id": lid, "item": item, "line": text, "at": 1}


@pytest.fixture
def opened(tmp_path):
    """The window's door with the registry's routes, as `start_door` opens it."""
    d = door.start(journey_door.routes(journey_door.App()), str(tmp_path / "door"))
    try:
        yield d
    finally:
        d.stop()


def _post(d, route, lang, body):
    conn = http.client.HTTPConnection("127.0.0.1", d.port, timeout=30)
    data = json.dumps(dict(body, lang=lang, token=d.token), ensure_ascii=False).encode("utf-8")
    conn.request("POST", f"/v1/{route}", body=data,
                 headers={"Host": f"127.0.0.1:{d.port}", "Content-Type": "text/plain", "Origin": "null"})
    r = conn.getresponse()
    out = json.loads(r.read().decode("utf-8"))
    conn.close()
    return out


def _queued_job(ledger, lang, got):
    """Swap's look turns the ask into Connect's job -> (the swap's row, its job)."""
    swap.look(runner.Steps(_settings()), ledger, lang, anki=Anki(), files=5)
    row = swap._rows(ledger, "id = ?", (got["id"],))[0]
    assert row["state"] == swap.QUEUED, row
    return row, ledger.job_by_id(row["job_id"])


def _settings():
    from app import settings_manager
    return settings_manager.load_settings()


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_with_the_audio_switch_off_a_line_whose_video_is_here_swaps_from_the_line_pressed(tmp_path, ledger, lang,
                                                                                           opened):
    # why: the tester's case with the video here — the page gives the line no time (the switch is off), and the door
    # refused every such line; the line's time is in its subtitle, so the press must ask Swap for that very line
    word, _old, other = CASES[lang]
    item, rel, abs_path = _library(lang, video=True)
    cue = _cue(lang, other)
    text, at, src = _page_line(tmp_path, lang, word, rel, abs_path, cue.text)
    assert at is None and src[5] == item            # the page as it is: no time without the switch, its item kept
    got = _post(opened, "swap/queue", lang, _page_body(word, text, at, src))
    assert got.get("ok"), got
    assert got["queued"] and not got["already"] and got["video"] is True
    row, job = _queued_job(ledger, lang, got)
    assert row["line_id"] == swap.line_id(item, cues.seconds(cue.start))      # the line pressed, by its own time
    assert (row["item_id"], row["line"], job["item_id"]) == (item, cue.text, item)


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("route", ["swap/queue", "card/make"])
def test_a_line_whose_video_isnt_here_queues_and_needs_you_asks_for_its_video(tmp_path, ledger, lang, opened, route):
    # why: the tester's ask — "it should ask me where the video is": the press queues (never refused), says the video
    # isn't on this computer, and Connect's job for it waits on *No video*, which Needs you shows with *Find video*
    word, _old, other = CASES[lang]
    item, rel, abs_path = _library(lang, video=False)
    cue = _cue(lang, other)
    text, at, src = _page_line(tmp_path, lang, word, rel, abs_path, cue.text)
    got = _post(opened, route, lang, _page_body(word, text, at, src))
    assert got.get("ok"), got
    assert got["video"] is False and not got["already"]
    row, job = _queued_job(ledger, lang, got)
    assert (row["item_id"], row["line"]) == (item, cue.text)
    with pytest.raises(runner.Wait) as w:
        runner._pick(runner.Steps(_settings()), ledger, lang, job)
    assert w.value.reason == runner.NO_VIDEO
    runner._wait(ledger, job, w.value, {"waiting": {}})
    with c.store(lang) as s:
        feed = s.read_feed()                    # the window's reader's first, full read (`library_reader._merge`)
    view = view_rows.build({r["id"]: r for r in feed["items"]}, {w_["id"]: w_ for w_ in feed["works"]},
                           feed["options"], language=lang)
    found = [e for e in needs.entries(view, connect=needs.read_connect(lang)) if e.kind == needs.NO_VIDEO]
    assert found and item in found[0].data["item_ids"], [(e.kind, e.data) for e in needs.entries(
        view, connect=needs.read_connect(lang))]
    assert "find_videos" in found[0].actions


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_only_a_line_with_no_time_in_any_file_is_refused_as_having_none(tmp_path, ledger, lang, opened):
    # why: the message stays true — a book's (a text's) line, or a page key with no item (a file the store doesn't
    # hold), has no time; a subtitle line no longer in its file is *gone*; none of them asks Swap for anything
    word, _old, other = CASES[lang]
    item, _rel, _abs = _library(lang, video=True, more=["context_test.txt"])
    with c.store(lang) as s:
        book = next(i for i in s.ids("now") if str(s.item(i)["rel_path"]).endswith("context_test.txt"))
    said = next(t for t in open(os.path.join(h.RESOURCES, lang, "context_test.txt"), encoding="utf-8").read().splitlines() if t.strip())
    refused = [("refused", door_routes.NO_LINE, {"line_id": "p1a2b3c4d", "item": book, "line": said}),
               ("refused", door_routes.NO_LINE, {"line_id": "p1a2b3c4d", "line": other}),
               ("gone", door_routes.GONE, {"line_id": "p1a2b3c4d", "item": item,
                                           "line": "この台詞はどこにもない" if lang == "ja" else "这句话哪里都没有"})]
    for kind, words, body in refused:
        got = _post(opened, "swap/queue", lang, dict(body, word=word, at=1))
        assert (got.get("kind"), got.get("error")) == (kind, words), (body, got)
    assert not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'swaps'").fetchone() or         not swap._rows(ledger, "1 = 1")


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_store_busy_while_an_untimed_line_is_found_says_press_again_never_gone(tmp_path, ledger, lang, opened,
                                                                                  monkeypatch):
    # why: edge case — the line's subtitle is found through the library store; a store busy with another save just
    # now is no line gone (J-FIX's rule, `_watch`): the learner presses again, nothing is asked
    word, _old, other = CASES[lang]
    item, rel, abs_path = _library(lang, video=True)
    text, at, src = _page_line(tmp_path, lang, word, rel, abs_path, _cue(lang, other).text)

    def busy(self, language, job):
        raise runner.Wait(runner.LIBRARY_BUSY)
    monkeypatch.setattr(runner.Steps, "subtitle", busy)
    got = _post(opened, "swap/queue", lang, _page_body(word, text, at, src))
    assert (got.get("kind"), got.get("error")) == ("busy", door_routes.BUSY), got
    assert not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'swaps'").fetchone() or \
        not swap._rows(ledger, "1 = 1")
