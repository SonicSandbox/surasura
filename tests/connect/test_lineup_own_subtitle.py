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


def _trust(monkeypatch, pair, on=True):
    """*Trust my subtitles' timing* (`connect_trust_timing`), as settings.json says it at the look."""
    monkeypatch.setattr(pair["steps"], "_settings", lambda lang: {"connect_trust_timing": on, "target_language": lang})


def _job():
    return {"id": 1, "item_id": 999, "language": "ja", "asked_at": None}


def _word(line):
    return {"word": "x", "reading": "x", "surface": line[:2], "line_text": line}


def test_a_book_whose_m4b_has_its_own_srt_is_cut_at_the_srts_times_trusted_with_no_sync_and_no_speech_model(
        monkeypatch, fake_miner):
    """Mattias's case: Hon found the `.srt` the book's (TIMING) and *Trust my subtitles' timing* is on — the part's
    line-up is that transcript (its copy in the library, the M4B's one file) at once: no *Lining up…* wait, no sync, no
    speech model asked for or downloaded, and a word is cut from the M4B at the cue holding its sentence (the
    transcript's own start time)."""
    pair = _pair(monkeypatch, fake_miner)
    _trust(monkeypatch, pair)
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
    _trust(monkeypatch, pair)
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
    assert "sync" not in fake_miner.commands()
    monkeypatch.setattr(pair["steps"], "_miner_profile", lambda lang, job: pytest.fail("Anki Miner's setup read again"))
    assert pair["steps"].line_up("ja", _job(), pair["book"])["lineup"]["source"] == lineup.OWN
    assert fake_miner.commands().count("transcribe") == 1, "the kept verdict answers: never heard twice"


def test_without_the_model_or_your_trust_the_transcript_waits_for_the_one_question_then_is_heard(
        monkeypatch, fake_miner):
    """Review S1 — one rule with an audiobook alone (`fit_check.fit`): a subtitle's timing is checked or trusted, never
    used unheard. No model and no trust → the speech model's one question (the sync's own); with the model it is heard
    and used, no sync (`test_a_transcript_the_spot_check_hears_in_time_…`)."""
    pair = _pair(monkeypatch, fake_miner)
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) == {"ask": lineup.SPEECH_ASK}
    assert "transcribe" not in fake_miner.commands() and not lineup.running(pair["rec"]["book"]["key"])


def test_after_not_now_to_the_speech_model_only_your_trust_uses_the_transcript(monkeypatch, fake_miner):
    """*Not now* to the speech model (B-11): Anki Miner is never asked about it — the book's cards come without audio,
    unless you trust your subtitles' timing: then the transcript cuts them, never listened to."""
    pair = _pair(monkeypatch, fake_miner)
    lineup.set_answer(False)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) is None
    _trust(monkeypatch, pair)
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


def test_an_ass_transcript_is_lined_up_as_before_never_cut_unread(monkeypatch, fake_miner):
    """An `.ass` transcript (Hon takes it in as one too) isn't read for cues here: the book is lined up by Anki Miner as
    before — never handed on as a line-up that would cut no card and skip the sync."""
    pair = _pair(monkeypatch, fake_miner, transcript=())
    folder = os.path.dirname(pair["files"][0])
    os.remove(pair["srt"])
    events = "\n".join(f"Dialogue: 0,0:00:{2 * n:02d}.00,0:00:{2 * n + 1:02d}.50,Default,,0,0,0,,{line}"
                       for n, line in enumerate(_lines("ja")[:12], 1))
    ass = os.path.join(folder, f"{STAR}.ass")
    with open(ass, "w", encoding="utf-8", newline="\n") as f:
        f.write("[Script Info]\nScriptType: v4.00+\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
                "MarginR, MarginV, Effect, Text\n" + events + "\n")
    _settle(ass)
    with pair["steps"]._open("ja") as store:
        _look(store, "ja", [s for s in store.sources(counts=False)][0]["id"])
        rec = _record(store, pair["item"])
        assert audiobooks.transcript_use(rec) == audiobooks.TIMING and rec["transcript"]["rel"].endswith(".ass")
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) == {"ask": lineup.SPEECH_ASK}


def test_an_anki_miner_that_mines_audio_but_cant_sync_never_lines_up_a_book_its_transcript_cant(monkeypatch, fake_miner):
    """Anki Miner mining audio (Z-16) but without `sync`: a transcript it can use is used; one it can't (several audio
    files) leaves the book as it is — never a sync started on an Anki Miner that has none, nothing asked."""
    pair = _pair(monkeypatch, fake_miner, several=True)
    _record_miner([f for f in LINE_UP_311 if f != "sync"])
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) is None
    assert not lineup.running(pair["rec"]["book"]["key"]) and fake_miner.commands() == []


# --- review round 1 (Opus adversary): B1, B2, S1, S2, S3 ------------------------------------------------------------ #
def test_b1_keep_them_together_is_kept_even_with_a_transcript(monkeypatch, fake_miner):
    """*Keep them together* (after a line-up found nothing) promises no sentence audio: a transcript never overrides
    your answer."""
    from tests import connect_helpers as c
    pair = _pair(monkeypatch, fake_miner)
    with c.store("ja") as s:
        assert s.mark_audiobook_lineup(pair["item"], pair["rec"]["book"]["key"], "none") is True
        assert s.audiobook_keep_together(pair["item"], pair["rec"]["book"]["key"]) is True
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) is None


def test_b2_after_anki_miners_line_up_found_nothing_an_unheard_transcript_is_never_used(monkeypatch, fake_miner):
    """Anki Miner's own line-up said this audio doesn't follow the book (nothing lined up, or a grade of C): a
    transcript nobody heard is no evidence against that — the book goes as it is (no clip)."""
    pair = _pair(monkeypatch, fake_miner)
    key = pair["rec"]["book"]["key"]
    lineup.write(key, {"status": lineup.NONE, "files": [], "grade": None})
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) is None
    lineup.write(key, {"status": lineup.DONE, "files": [], "grade": "C"})
    assert pair["steps"].line_up("ja", _job(), pair["book"])["lineup"] is None, "a C: the book's cards, no clip"
    _trust(monkeypatch, pair)               # even trusted: only a subtitle heard in time outweighs Anki Miner's line-up
    assert pair["steps"].line_up("ja", _job(), pair["book"])["lineup"] is None
    lineup.write(key, {"status": lineup.NONE, "files": [], "grade": None})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) is None


def test_b2_after_a_poor_line_up_a_transcript_the_spot_check_hears_in_time_is_used(monkeypatch, fake_miner):
    pair = _pair(monkeypatch, fake_miner)
    lineup.write(pair["rec"]["book"]["key"], {"status": lineup.DONE, "files": [], "grade": "C"})
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"])["lineup"]["source"] == lineup.OWN
    assert fake_miner.commands().count("transcribe") == 1


def test_b2_a_spot_check_that_failed_now_is_no_verdict_the_book_is_lined_up_as_before(monkeypatch, fake_miner):
    """The speech model is there but the check fails this time (a crash, a timeout): never used unheard — lined up as
    before (here the sync starts), and the next look checks again."""
    pair = _pair(monkeypatch, fake_miner)

    def crashed(*a, **kw):
        raise anki_miner.AnkiMinerError("crashed", "Anki Miner stopped")
    monkeypatch.setattr(lineup, "spot_check", crashed)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"},
                    sync={"files": {}, "report": {"grade": None}, "hold": 5.0})
    with pytest.raises(runner.Wait) as w:
        pair["steps"].line_up("ja", _job(), pair["book"])
    assert runner.lining_up(w.value.reason) and lineup.running(pair["rec"]["book"]["key"])
    assert lineup.spot_kept(lineup.spot_key(pair["files"][0], os.path.join(
        pair["data_dir"], *pair["rec"]["transcript"]["rel"].split("/")))) is None, "nothing kept: checked again"
    lineup.stop(pair["rec"]["book"]["key"])


def test_s1_a_transcript_running_past_the_audios_end_is_another_recordings(monkeypatch, fake_miner):
    """Its last cue ends well after the audio does: timed to another (longer) recording — never cut from this one."""
    pair = _pair(monkeypatch, fake_miner)
    from app import library_store as ls
    with pair["steps"]._open("ja") as store:
        ab = library.audiobook_of_book(store, pair["book"])
    assert isinstance(ab["seconds"], (int, float)) and ab["seconds"] > 0
    copy = os.path.join(pair["data_dir"], *ab["timing"].split("/"))
    end = int(ab["seconds"] + runner.OWN_SLACK_S + 60)
    with open(copy, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"\n99\n{end // 3600:02d}:{end // 60 % 60:02d}:{end % 60:02d},000 --> "
                f"{end // 3600:02d}:{end // 60 % 60:02d}:{end % 60:02d},900\n{pair['lines'][0]}\n")
    assert ls  # (the store's own copy, edited in place: the look would copy it again; the check reads it as it is)
    _trust(monkeypatch, pair)               # trusted: still refused — its times aren't this audio's
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) == {"ask": lineup.SPEECH_ASK}


def test_s2_a_sync_running_when_the_transcript_is_used_is_stopped(monkeypatch, fake_miner):
    """A sync that started before the transcript was checked (UNCHECKED then): once the transcript lines the book up,
    the sync is stopped — never hours of listening nobody uses, nor every other book waiting behind it."""
    pair = _pair(monkeypatch, fake_miner)
    key = pair["rec"]["book"]["key"]
    _trust(monkeypatch, pair)                   # (no spot-check: the transcript trusted)
    fake_miner.plan(sync={"files": {}, "report": {"grade": None}, "hold": 30.0})
    lineup.start_sync(fake_miner.path, "ja", None, key, pair["book"], pair["files"])
    assert lineup.running(key)
    got = pair["steps"].line_up("ja", _job(), pair["book"])
    assert got["lineup"]["source"] == lineup.OWN and lineup.read(key)["status"] == lineup.STOPPED


def test_s3_on_battery_the_spot_check_waits_for_the_plug_unless_you_asked(monkeypatch, fake_miner):
    """Listening is heavy: on battery an unasked spot-check waits for the plug, as a sync does; your *Mine now* runs
    it at once."""
    pair = _pair(monkeypatch, fake_miner)
    monkeypatch.setattr(pair["steps"], "on_battery", lambda: True)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    with pytest.raises(runner.Wait) as w:
        pair["steps"].line_up("ja", _job(), pair["book"])
    assert w.value.reason == runner.LINING_UP_BATTERY and "transcribe" not in fake_miner.commands()
    asked = dict(_job(), asked_at="2026-11-12T00:00:00Z")
    assert pair["steps"].line_up("ja", asked, pair["book"])["lineup"]["source"] == lineup.OWN


# --- review round 2 (Opus adversary): S1, S2, S3, N5 ---------------------------------------------------------------- #
def test_r2_s1_a_subtitle_heard_out_of_time_is_never_used_even_trusted(monkeypatch, fake_miner):
    """The spot-check heard it out of time before (kept): turning *Trust my subtitles' timing* on never makes its clips."""
    pair = _pair(monkeypatch, fake_miner)
    copy = os.path.join(pair["data_dir"], *pair["rec"]["transcript"]["rel"].split("/"))
    lineup._keep_spot(lineup.spot_key(pair["files"][0], copy), lineup.NOT_MATCHED, [0.1] * 5)
    _trust(monkeypatch, pair)
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) == {"ask": lineup.SPEECH_ASK}


def test_r2_s2_a_good_finished_line_up_is_used_on_battery_never_waiting_to_listen(monkeypatch, fake_miner):
    """A pair Anki Miner already lined up well (grade A) — on battery, the model there, no verdict kept: its line-up
    cuts the cards at once, as before this lane (no listen, no wait for the plug)."""
    pair = _pair(monkeypatch, fake_miner)
    key = pair["rec"]["book"]["key"]
    srt = os.path.join(lineup.folder(key), "own.srt")
    os.makedirs(os.path.dirname(srt), exist_ok=True)
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\n" + pair["lines"][0] + "\n")
    lineup.write(key, {"status": lineup.DONE, "grade": "A", "files": [
        {"audio_file": pair["files"][0], "subtitle_file": srt, "status": "synced", "units": {}}]})
    monkeypatch.setattr(pair["steps"], "on_battery", lambda: True)
    fake_miner.plan(speech={"installed": ["small"], "model": "small"})
    got = pair["steps"].line_up("ja", _job(), pair["book"])
    assert got["lineup"]["grade"] == "A" and "source" not in got["lineup"]
    assert "transcribe" not in fake_miner.commands() and "media" not in fake_miner.commands()


def test_r2_s3_while_a_sync_runs_its_look_never_listens_again(monkeypatch, fake_miner):
    """A sync running for the pair (a check that failed started it): each look only reads it — no spot-check beside the
    hours of listening."""
    pair = _pair(monkeypatch, fake_miner)
    key = pair["rec"]["book"]["key"]
    fake_miner.plan(speech={"installed": ["small"], "model": "small"},
                    sync={"files": {}, "report": {"grade": None}, "hold": 30.0})
    lineup.start_sync(fake_miner.path, "ja", None, key, pair["book"], pair["files"])
    with pytest.raises(runner.Wait) as w:
        pair["steps"].line_up("ja", _job(), pair["book"])
    assert runner.lining_up(w.value.reason)
    assert "transcribe" not in fake_miner.commands() and "media" not in fake_miner.commands()
    lineup.stop(key)


def test_r2_n5_connects_own_stop_never_holds_the_book_as_your_stop(monkeypatch, fake_miner):
    """The sync Connect stopped for the transcript; the transcript no longer used (trust off, no model): the book is
    never held by *Lining up its audiobook stopped* — a Stop you never pressed."""
    pair = _pair(monkeypatch, fake_miner)
    key = pair["rec"]["book"]["key"]
    _trust(monkeypatch, pair)
    fake_miner.plan(sync={"files": {}, "report": {"grade": None}, "hold": 30.0})
    lineup.start_sync(fake_miner.path, "ja", None, key, pair["book"], pair["files"])
    assert pair["steps"].line_up("ja", _job(), pair["book"])["lineup"]["source"] == lineup.OWN
    assert lineup.read(key)["own_stop"] is True
    for proc, _out in list(lineup._RUNNING.values()):
        proc.wait(30)
    _trust(monkeypatch, pair, on=False)
    fake_miner.plan(speech={"installed": [], "model": "small"})
    assert pair["steps"].line_up("ja", _job(), pair["book"]) == {"ask": lineup.SPEECH_ASK}
