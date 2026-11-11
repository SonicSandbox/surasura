"""A book whose audiobook carries its own timed subtitle (Kura-AB3, Mattias's 3.0.2 report; PROVISIONAL): he has, for
each book, the book's text, its audiobook and a timed `.srt` for that audio. The library already takes such a subtitle in
as the audiobook's transcript and checks it is the book's (Hon a6, `audiobooks.TIMING`) — but Connect still waited for
Anki Miner's speech model to line the book up. Now the transcript IS the line-up: the book's words are cut from the audio
at the transcript's own times, with no sync and no speech model.

What a wrong answer would cost: Mattias's books are mined to text-only cards while a subtitle that times them sits
beside the audio (or wait hours for a speech model he doesn't need); a transcript whose times span several audio files,
or one not timed to this audio, would put the wrong sentence's sound on his cards — so those are lined up as before.

Real data: a real EPUB of the suite's Japanese sentences, a real M4B (its length and tags) and an `.srt` of those
sentences beside it, paired and checked by a real look into a real store (Hon's helpers); Anki Miner is the suite's fake
(`fake_anki_miner.py`), run as a child process exactly as the real one is.
"""
import os

import pytest

from app import audiobooks
from app.connect import anki_miner, library, lineup, runner, setup
from tests.connect.test_lineup import LINE_UP_311, _record_miner
from tests.test_audiobook_items import _audio_folder, _audio_items, _epub, _fit, _lines, _record, _settle
from tests.test_audiobook_transcripts import _srt
from tests.test_audiobooks import _m4b
from tests.test_sources_scan import _drive, _empty, _look

STAR = "星屑の剣士になりたくて！"


@pytest.fixture(autouse=True)
def no_child_left():
    lineup._RUNNING.clear()
    anki_miner._SPEECH.clear()
    yield
    for proc, _out in list(lineup._RUNNING.values()):
        if proc.poll() is None:
            proc.kill()
            proc.wait(10)
    lineup._RUNNING.clear()
    anki_miner._SPEECH.clear()


def _pair(monkeypatch, fake_miner, several=False, transcript=None):
    """The EPUB and its audiobook side by side — one M4B (or, `several`, a folder of chapter MP3s) with an `.srt` of
    the book's own sentences beside it — paired (sure) and its transcript checked by a real look."""
    store, data_dir = _empty("ja")
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", f"{STAR}.epub"), STAR, "ja")
    folder = os.path.join(src, "Books", STAR)
    if several:
        files = _audio_folder(folder, STAR, _fit("ja"))
    else:
        files = [_m4b(os.path.join(folder, f"{STAR}.m4b"), _fit("ja"), tags={"album": STAR})]
        _settle(*files)
    lines = _lines("ja")[:12] if transcript is None else transcript
    srt = _srt(os.path.join(folder, f"{STAR}.srt"), lines)
    with store:
        _look(store, "ja", store.add_source(src), first=True)
        [item] = _audio_items(store)
        rec = _record(store, item["id"])
    assert rec["book"]["epub"] == os.path.abspath(book)
    _record_miner()
    steps = runner.Steps({"connect_anki_miner_path": fake_miner.path})
    monkeypatch.setattr(steps, "_miner_profile", lambda lang, job: (fake_miner.path, "p-surasura"))
    monkeypatch.setattr(steps, "on_battery", lambda: False)
    return {"steps": steps, "store": store, "data_dir": data_dir, "book": os.path.abspath(book), "files": files,
            "srt": srt, "rec": rec, "item": item["id"], "lines": lines}


def _job():
    return {"id": 1, "item_id": 999, "language": "ja", "asked_at": None}


def _word(line):
    return {"word": "x", "reading": "x", "surface": line[:2], "line_text": line}


def test_a_book_whose_m4b_has_its_own_srt_is_cut_at_the_srts_times_with_no_sync_and_no_speech_model(
        monkeypatch, fake_miner):
    """Mattias's case: Hon found the `.srt` the book's (TIMING) — the part's line-up is that transcript (its copy in the
    library, the M4B's one file) at once: no *Lining up…* wait, no sync, no speech model asked for or downloaded, and a
    word is cut from the M4B at the cue holding its sentence (the transcript's own start time)."""
    pair = _pair(monkeypatch, fake_miner)
    assert audiobooks.transcript_use(pair["rec"]) == audiobooks.TIMING
    fake_miner.plan(speech={"installed": [], "model": "small"})          # no speech model at all
    got = pair["steps"].line_up("ja", _job(), pair["book"])
    copy = os.path.join(pair["data_dir"], *pair["rec"]["transcript"]["rel"].split("/"))
    assert got["item_id"] == pair["item"] and got["line"] is None
    assert got["lineup"]["source"] == lineup.OWN and lineup.usable(got["lineup"])
    assert [(f["audio_file"], f["subtitle_file"]) for f in got["lineup"]["files"]] == \
        [(os.path.abspath(pair["files"][0]), os.path.abspath(copy))]
    assert "sync" not in fake_miner.commands() and "setup" not in fake_miner.commands()
    assert lineup.answer() is None, "the speech model's question was never asked"
    line = pair["lines"][4]
    groups, rest = lineup.split([_word(line)], got["lineup"])
    [(audio, subtitle)] = groups
    assert not rest and audio == os.path.abspath(pair["files"][0]) and subtitle == os.path.abspath(copy)
    start = [s for s, _e, t in lineup.srt_cues(copy) if t == line][0]
    assert groups[(audio, subtitle)][0]["line_start"] == start == 10.0      # `_srt`: the 5th cue at 00:00:10


def test_the_pick_hands_the_own_line_up_to_the_mine_and_the_book_asks_nothing(monkeypatch, fake_miner, tmp_path):
    """Through the runner's own line-up step: the part's pick carries the transcript's line-up, no *Needs you* line (no
    speech model question, no book question — it is paired), and the mine sends the word as the M4B's audio episode."""
    from app.connect.ledger import Ledger
    pair = _pair(monkeypatch, fake_miner)
    fake_miner.plan(speech={"installed": [], "model": "small"})
    ledger = Ledger(str(tmp_path / "ledger.db"))
    lined = runner._line_up(pair["steps"], ledger, "ja", _job(), ("part.txt", pair["book"]))
    assert lined["source"] == lineup.OWN
    assert ledger.conn.execute("SELECT COUNT(*) FROM needs").fetchone()[0] == 0
    sent = []
    monkeypatch.setattr(pair["steps"], "_mine_one", lambda lang, job, run, ws, attempt: sent.append(run) or
                        {"outcomes": [{"outcome": "made"} for _w in ws], "app": "3.11.0"})
    pair["steps"].mine("ja", _job(), {"reading": "part.txt", "lineup": lined, "video": None, "subtitle": None},
                       [_word(pair["lines"][2])], 1)
    [run] = sent
    assert run["video"] == os.path.abspath(pair["files"][0]) and run["reading"] is None
    assert run["subtitle"] == lined["files"][0]["subtitle_file"]


def test_one_transcript_for_several_audio_files_is_lined_up_as_before(monkeypatch, fake_miner):
    """A transcript beside a folder of chapter MP3s: its times can't be told apart by file, so it never cuts cards —
    the book is lined up as before (here: no speech model, so the one question)."""
    pair = _pair(monkeypatch, fake_miner, several=True)
    assert audiobooks.transcript_use(pair["rec"]) == audiobooks.TIMING
    fake_miner.plan(speech={"installed": [], "model": "small"})
    got = pair["steps"].line_up("ja", _job(), pair["book"])
    assert got == {"ask": lineup.SPEECH_ASK}


def test_a_transcript_that_isnt_the_books_is_never_its_line_up(monkeypatch, fake_miner):
    """Another text's subtitle beside the M4B (Hon: OTHER) is never used for timing."""
    from tests.test_audiobook_transcripts import _other_lines
    pair = _pair(monkeypatch, fake_miner, transcript=_other_lines("ja"))
    assert audiobooks.transcript_use(pair["rec"]) == audiobooks.OTHER
    with pair["steps"]._open("ja") as store:
        assert library.audiobook_of_book(store, pair["book"])["timing"] is None
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) == {"ask": lineup.SPEECH_ASK}


def test_a_transcript_the_spot_check_finds_untimed_is_lined_up_by_anki_miner_instead(monkeypatch, fake_miner):
    """With the speech model there, the transcript is heard first (AB-Q5, once, kept): not timed to this audio → the
    book is lined up by Anki Miner as before (never a wrong clip); timed → used (below)."""
    pair = _pair(monkeypatch, fake_miner, transcript=_lines("ja")[:14])
    copy = os.path.join(pair["data_dir"], *pair["rec"]["transcript"]["rel"].split("/"))
    places = lineup.samples(lineup.srt_cues(copy))
    other = "".join(_lines("ja")[20:23])
    fake_miner.plan(speech={"installed": ["small"], "model": "small"}, heard={p[2][:6]: other for p in places},
                    sync={"files": {}, "report": {"grade": None}, "hold": 5.0})
    with pytest.raises(runner.Wait) as w:
        pair["steps"].line_up("ja", _job(), pair["book"])
    assert runner.lining_up(w.value.reason)
    assert fake_miner.commands().count("transcribe") == 1 and lineup.running(pair["rec"]["book"]["key"])
    assert lineup.spot_kept(lineup.spot_key(pair["files"][0], copy)) == lineup.NOT_MATCHED
    lineup.stop(pair["rec"]["book"]["key"])


def test_a_transcript_the_spot_check_hears_in_time_is_used_and_the_verdict_kept(monkeypatch, fake_miner):
    pair = _pair(monkeypatch, fake_miner)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    got = pair["steps"].line_up("ja", _job(), pair["book"])
    assert got["lineup"]["source"] == lineup.OWN
    copy = os.path.join(pair["data_dir"], *pair["rec"]["transcript"]["rel"].split("/"))
    assert lineup.spot_kept(lineup.spot_key(pair["files"][0], copy)) == lineup.MATCHED


def test_after_not_now_to_the_speech_model_the_transcript_is_used_unheard(monkeypatch, fake_miner):
    """*Not now* to the speech model (B-11): Anki Miner is never asked about it — the transcript is used as it is."""
    pair = _pair(monkeypatch, fake_miner)
    lineup.set_answer(False)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"])["lineup"]["source"] == lineup.OWN
    assert "check" not in fake_miner.commands() and "transcribe" not in fake_miner.commands()


def test_an_anki_miner_that_mines_no_audio_or_an_audio_file_away_never_uses_the_transcript(monkeypatch, fake_miner):
    """An Anki Miner that doesn't mine audio (no Z-16) has nothing to cut from: the book goes as it is, nothing asked;
    the M4B away (its drive unplugged) → lined up as before, never a clip from a file that isn't here."""
    pair = _pair(monkeypatch, fake_miner)
    assert setup.write_record({"anki_miner": {"app": "3.10.1", "schema": 1,
                                              "features": [f for f in LINE_UP_311 if f != "audio-episodes"]}})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) is None
    assert fake_miner.commands() == []
    _record_miner()
    os.replace(pair["files"][0], pair["files"][0] + ".away")
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) == {"ask": lineup.SPEECH_ASK}
