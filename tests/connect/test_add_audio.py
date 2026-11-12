"""*Add audio to these cards* (Kura-AB3; `app/connect/add_audio.py`, spec TheForge `tracks/pipeline/work/AB3/
add-audio-spec.md`; PROVISIONAL): Mattias's books were mined to text-only cards before their audiobooks were lined
up; once a book is lined up, each of those cards gets the narrator's clip of ITS sentence in its empty sentence-audio
field — through the one sentence-audio writer (only an empty field, tagged, one Undo).

What a wrong answer would cost: a clip of the wrong sentence on a card teaches the wrong sound (the cardinal sin); a
field the learner filled overwritten; a card of another book, or the learner's own, touched; a sync started or the
speech model woken just to count; a plan that writes.

Real data: a real EPUB of the suite's Japanese sentences, a real M4B and the `.srt` of those sentences beside it, paired
and checked by a real look into a real store (Hon's helpers), the store's own made-words record; Anki Miner is the
suite's fake run as a child (its `media` writes each clip holding the line it cut — so a clip's sentence is checked);
Anki is the writer's fake (AnkiConnect's notesInfo shape).
"""
import base64
import os

import pytest

from app.connect import add_audio, fields, library, lineup
from app.connect import sentence_audio as sa
from app.connect.ledger import Ledger
from tests.connect.test_lineup_own_subtitle import _pair, _trust
from tests.connect.test_sentence_audio import FakeAnki
from tests.test_audiobook_transcripts import _other_lines

MAPPING = fields.Mapping("Mining", "Lapis", {"word": "Expression", "sentence": "Sentence", "audio": "SentenceAudio"},
                         "Expression", "Sentence", None, None)


@pytest.fixture
def book(monkeypatch, fake_miner):
    """A book paired with its M4B whose `.srt` is trusted (lined up, no listen), its first part's cards made by
    Connect: five text-only cards of five of its sentences, one with audio already, one of a sentence the audiobook
    never says, one deleted since — and a card of another item (never this book's)."""
    pair = _pair(monkeypatch, fake_miner)
    _trust(monkeypatch, pair)
    with pair["steps"]._open("ja") as store:
        parts = add_audio.book_items(store, pair["book"])
        assert parts and pair["item"] not in parts
        made = {}
        anki = FakeAnki()
        for k in range(5):
            line = pair["lines"][k + 1]
            anki.add(100 + k, f"<b>{line[:2]}</b>" + line[2:], line[:2])
            made[f"w{k}"] = [100 + k]
        anki.add(200, pair["lines"][7], pair["lines"][7][:2], audio="[sound:his.mp3]")
        made["has"] = [200]
        other = _other_lines("ja")[0]
        anki.add(201, other, other[:2])
        made["unheard"] = [201]
        made["gone"] = [202]
        library.record_batch(store, parts[0], made, "2026-11-01T00:00:00Z")
        library.record_batch(store, pair["item"], {"elsewhere": [300]}, "2026-11-01T00:00:00Z")
    anki.add(300, pair["lines"][2], pair["lines"][2][:2])
    return dict(pair, anki=anki)


def test_the_plan_counts_and_places_each_card_in_its_own_cue_and_writes_nothing(book, fake_miner):
    """Five cards can get the narrator's voice (each its own sentence's cue, bold markup and all); one has audio
    already; one's sentence isn't in the audiobook; one is gone; the card of another item is no card of this book's.
    Nothing written, no sync started, nothing listened to."""
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert got["lined"] and got["field"] == "SentenceAudio"
    assert sorted(got["can"]) == [100, 101, 102, 103, 104]
    assert got["has_audio"] == [200] and got["unheard"] == [201] and got["gone"] == [202]
    for k in range(5):
        assert lineup.clean(got["can"][100 + k].text) == lineup.clean(book["lines"][k + 1])
    assert not [c for c in book["anki"].calls if c[0] in ("store", "update", "tag")]
    assert fake_miner.commands() == [] and not lineup.running(book["rec"]["book"]["key"])


def test_the_clips_are_each_cards_own_sentence_and_go_into_the_empty_field_only(book, fake_miner, tmp_path):
    """`media` cuts each cue once; every card's clip holds ITS sentence (the fake's clip is the line it cut) — never a
    neighbour's; the writer fills the empty fields, tags them, and leaves the card with audio as it was."""
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert sorted(clips) == [100, 101, 102, 103, 104]
    for k in range(5):
        with open(clips[100 + k], encoding="utf-8") as f:
            assert lineup.clean(f.read()) == lineup.clean(book["lines"][k + 1])
    assert fake_miner.commands() == ["media"]
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        done = sa.fill(book["anki"], ledger, clips, field="SentenceAudio", tag=add_audio.TAG, by=add_audio.BY)
        assert done["filled"] == [100, 101, 102, 103, 104]
        for k in range(5):
            name = book["anki"].value(100 + k)[len("[sound:"):-1]
            heard = base64.b64decode(book["anki"].media[name]).decode("utf-8")
            assert lineup.clean(heard) == lineup.clean(book["lines"][k + 1]), "the card's own sentence"
            assert add_audio.TAG in book["anki"].notes_[100 + k]["tags"]
        assert book["anki"].value(200) == "[sound:his.mp3]" and book["anki"].value(300) == ""
        assert sa.record(ledger, done["id"])["by"] == add_audio.BY


def test_two_cards_of_one_sentence_share_its_clip_cut_once(book, fake_miner, tmp_path):
    book["anki"].add(105, book["lines"][1], book["lines"][1][:2])
    with book["steps"]._open("ja") as store:
        library.record_batch(store, add_audio.book_items(store, book["book"])[0], {"twin": [105]}, "2026-11-01T00:00:00Z")
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert clips[105] == clips[100]
    [asked] = [c for c in fake_miner.calls() if "media_lines" in c]
    assert len(asked["media_lines"]) == 5, "each cue cut once"


def test_a_line_anki_miner_cut_no_clip_for_leaves_that_card_out(book, fake_miner, tmp_path):
    """A line past the audio's end (its `audio` null): that card gets nothing — never another line's clip."""
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    last = max(got["can"], key=lambda n: got["can"][n].start)
    fake_miner.plan(audio_seconds=got["can"][last].start - 0.1)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert last not in clips and len(clips) == 4


def test_a_book_not_lined_up_has_nothing_to_cut_and_nothing_is_started(monkeypatch, fake_miner):
    """No trust and no speech model: the book isn't lined up — the plan says so; no sync, no question, no listen.
    *Keep them together* the same."""
    pair = _pair(monkeypatch, fake_miner)
    fake_miner.plan(speech={"installed": [], "model": "small"})
    got = add_audio.plan(FakeAnki(), pair["steps"], "ja", pair["book"], MAPPING)
    assert got["lined"] is False and got["can"] == {}
    assert fake_miner.commands() == [] and not lineup.running(pair["rec"]["book"]["key"])
    assert pair["steps"].lined_up("ja", pair["book"]) is None


def test_a_finished_good_sync_lines_the_book_up_for_it_too(monkeypatch, fake_miner):
    """No own subtitle trusted, but Anki Miner lined the book up at grade A: its cues cut the clips (read only)."""
    pair = _pair(monkeypatch, fake_miner)
    key = pair["rec"]["book"]["key"]
    srt = os.path.join(lineup.folder(key), "own.srt")
    os.makedirs(os.path.dirname(srt), exist_ok=True)
    with open(srt, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\n" + pair["lines"][0] + "\n")
    lineup.write(key, {"status": lineup.DONE, "grade": "A", "files": [
        {"audio_file": pair["files"][0], "subtitle_file": srt, "status": "synced", "units": {}}]})
    fake_miner.plan(speech={"installed": [], "model": "small"})
    got = pair["steps"].lined_up("ja", pair["book"])
    assert got["lineup"]["grade"] == "A" and fake_miner.commands() == []


def test_no_audio_field_in_the_mapping_is_no_card_filled(book):
    bare = MAPPING._replace(fields={"word": "Expression", "sentence": "Sentence"})
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], bare)
    assert got["field"] is None and got["can"] == {}


def test_act_asks_nothing_of_anki_with_connect_off_or_anki_switched_off(monkeypatch):
    assert add_audio.act({"connect_enabled": False}, "ja", book="x.epub") == {"skipped": "connect preview off"}
    monkeypatch.setattr("app.cli.verbs.require_set_up", lambda lang: None)
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    assert add_audio.act({"connect_enabled": True}, "ja", book="x.epub")["skipped"]


def test_the_command_line_takes_add_audio_with_its_plan_first():
    from app.cli import __main__ as cli
    args = cli._parser().parse_args(["add-audio", "--book", "x.epub"])
    assert args.verb == "add-audio" and args.book == "x.epub" and args.confirm is False
    args = cli._parser().parse_args(["add-audio", "--undo", "17-ab"])
    assert args.undo == "17-ab"


# --- mutants by risk: the survivors' tests ---------------------------------------------------------------------- #
def test_anki_miner_answering_fewer_lines_than_asked_leaves_that_files_cards_out(book, fake_miner, tmp_path,
                                                                                    monkeypatch):
    """Lines merged or dropped: no clip is matched by its place in the answer (it could be the next line's) — those
    cards get nothing, and with nothing cut at all, it says why (r3 S2)."""
    from app.connect import anki_miner
    real = anki_miner.api

    def merged(miner, args, **kw):
        verdict = real(miner, args, **kw)
        for run in verdict.get("runs") or ():
            path = os.path.join(str(tmp_path / "run"), run["run_id"], run["file"])
            made = lineup._read_json(path)
            made["lines"] = made["lines"][1:]
            lineup._write_json(path, made)
        return verdict
    monkeypatch.setattr(anki_miner, "api", merged)
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert add_audio.OTHER_COUNT in e.value.message


def test_the_plan_never_writes_the_line_up_while_a_sync_runs(book, fake_miner):
    """`lined_up` reads the pair's line-up as it is — a running sync's state file is never written by a plan."""
    key = book["rec"]["book"]["key"]
    fake_miner.plan(sync={"files": {}, "report": {"grade": None}, "hold": 30.0})
    lineup.start_sync(fake_miner.path, "ja", None, key, book["book"], book["files"])
    import time
    time.sleep(1.0)                                     # its progress written meanwhile
    before = open(os.path.join(lineup.folder(key), lineup.STATE), encoding="utf-8").read()
    add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert open(os.path.join(lineup.folder(key), lineup.STATE), encoding="utf-8").read() == before
    lineup.stop(key)


def test_keep_them_together_or_a_poor_line_up_adds_no_audio(monkeypatch, fake_miner):
    """*Keep them together* (no sentence audio, as you said) and a sync of grade C (another edition): not lined up."""
    from tests import connect_helpers as c
    pair = _pair(monkeypatch, fake_miner)
    key = pair["rec"]["book"]["key"]
    lineup.write(key, {"status": lineup.DONE, "grade": "C", "files": [
        {"audio_file": pair["files"][0], "subtitle_file": pair["srt"], "status": "synced", "units": {}}]})
    assert pair["steps"].lined_up("ja", pair["book"]) is None
    lineup.write(key, {})                               # no sync at all: the trusted subtitle alone would line it up
    _trust(monkeypatch, pair)
    assert pair["steps"].lined_up("ja", pair["book"])["lineup"]["source"] == lineup.OWN
    with c.store("ja") as s:
        assert s.mark_audiobook_lineup(pair["item"], key, "none") is True
        assert s.audiobook_keep_together(pair["item"], key) is True
    assert pair["steps"].lined_up("ja", pair["book"]) is None


# --- review A1 (Opus adversary, round 1): S1–S6 and its notes, each red first ------------------------------------ #
def _made(book, nid, sentence, word):
    """One more text-only card Connect made from the book's first part."""
    book["anki"].add(nid, sentence, word)
    with book["steps"]._open("ja") as store:
        library.record_batch(store, add_audio.book_items(store, book["book"])[0], {f"n{nid}": [nid]},
                             "2026-11-01T00:00:00Z")


def _act_ready(monkeypatch, tmp_path):
    """`act` past its gates (Connect on, set up, Anki on, a ledger in the test's folder) -> the owed syncs' list."""
    from app.connect import ledger as ledger_mod
    monkeypatch.setattr("app.cli.verbs.require_set_up", lambda lang: None)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    monkeypatch.setattr(ledger_mod, "path", lambda: str(tmp_path / "ledger.sqlite"))
    Ledger(str(tmp_path / "ledger.sqlite")).close()
    owed = []
    monkeypatch.setattr("app.connect.undo.owe_sync", lambda settings: owed.append(1))
    return owed


def test_an_earlier_shorter_line_inside_the_sentence_never_wins_over_the_sentences_own_cue(book, monkeypatch):
    """S1: a line said earlier in the book (9 characters, the card's word in it) sits inside the card's sentence; the
    sentence's own cue, later, is the one — the earlier line's clip would teach another moment's sound."""
    real = lineup.cues
    sentence = book["lines"][4]                         # 私たちは新しい冒険を求めている。 — card 103
    first = real(book["steps"].lined_up("ja", book["book"])["lineup"])[0]

    def with_fragment(state):
        return [first._replace(start=0.5, end=1.5, text=lineup.clean(sentence[:9]))] + real(state)
    monkeypatch.setattr(lineup, "cues", with_fragment)
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert got["can"][103].start != 0.5 and got["can"][103].text == lineup.clean(sentence)


def test_a_sentence_said_twice_in_the_book_is_no_answer(book, monkeypatch):
    """S1 / B-14 across the book: two cues ARE the card's sentence — which moment is unknown: unheard, never a guess."""
    real = lineup.cues

    def twice(state):
        found = real(state)
        again = next(c for c in found if c.text == lineup.clean(book["lines"][3]))
        return found + [again._replace(start=again.start + 100.0, end=again.end + 100.0)]
    monkeypatch.setattr(lineup, "cues", twice)
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert 102 not in got["can"] and 102 in got["unheard"]


def test_a_card_whose_word_is_its_dictionary_form_is_placed_by_the_form_its_sentence_bolds(book):
    """S3: Anki Miner's Expression is the dictionary form (できる) — the sentence says できて, bolded; the card is
    placed by its sentence's cue (and over two cues, by the bold form's), not left unheard."""
    one = book["lines"][5]                              # 冒険の準備はできていますか？
    _made(book, 110, one.replace("でき", "<b>でき</b>"), "できる")
    two = book["lines"][3] + book["lines"][4]           # two cues, said as one sentence on the card
    _made(book, 111, two.replace("求め", "<b>求め</b>"), "求める")
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert got["can"][110].text == lineup.clean(one)
    assert got["can"][111].text == lineup.clean(book["lines"][4]), "the cue holding 求め, never its neighbour"


def test_a_sentence_written_with_furigana_or_entities_is_placed_as_read_aloud(book):
    """N: ruby, Anki's bracket furigana and HTML entities are not the sentence's sound."""
    line = book["lines"][3]                             # 彼は毎日冒険に出かけます。
    _made(book, 120, "<ruby>彼<rt>かれ</rt></ruby>は毎日冒険に<b>出</b>かけます。", "出かける")
    _made(book, 121, " 彼[かれ]は 毎日[まいにち]冒険に出かけます&#12290;", "毎日")
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert got["can"][120].text == got["can"][121].text == lineup.clean(line)


def test_a_clip_is_matched_back_by_its_start_and_text_never_by_its_place_alone(book, fake_miner, tmp_path,
                                                                                   monkeypatch):
    """S2: Anki Miner answers its lines in another order (same count): only a line whose start and text are the cue's
    gives a clip — the rest of those cards get nothing, never a neighbour's sentence."""
    from app.connect import anki_miner
    real = anki_miner.api

    def reversed_lines(miner, args, **kw):
        verdict = real(miner, args, **kw)
        for run in verdict.get("runs") or ():
            path = os.path.join(str(tmp_path / "run"), run["run_id"], run["file"])
            made = lineup._read_json(path)
            made["lines"] = made["lines"][::-1]
            lineup._write_json(path, made)
        return verdict
    monkeypatch.setattr(anki_miner, "api", reversed_lines)
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert len(clips) == 1, "five reversed: only the middle one is its own line"
    for note_id, clip in clips.items():
        with open(clip, encoding="utf-8") as f:
            assert lineup.clean(f.read()) == got["can"][note_id].text


def test_two_cues_of_one_start_are_never_given_one_clip(book, fake_miner, tmp_path):
    """S2: two cues starting at the same moment (an overlapping line): Anki Miner's nearest line is the first's — the
    second's card gets nothing rather than the first's sentence."""
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    a = got["can"][100]
    twin = a._replace(text=got["can"][102].text)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", {100: a, 102: twin}, str(tmp_path / "run"))
    assert sorted(clips) == [100]
    with open(clips[100], encoding="utf-8") as f:
        assert lineup.clean(f.read()) == a.text


def test_a_book_of_many_cards_is_cut_in_bounded_calls_and_a_later_refusal_keeps_what_was_cut(book, fake_miner,
                                                                                               tmp_path, monkeypatch):
    """S6: never one `media` call for a whole book (its 20-minute timeout over a thousand clips): CUT_LINES a call;
    a later call refused stops there with the clips already cut (a press again does the rest — only empty fields)."""
    from app.connect import anki_miner
    monkeypatch.setattr(add_audio, "CUT_LINES", 2)
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert fake_miner.commands() == ["media", "media", "media"] and sorted(clips) == sorted(got["can"])
    for note_id, clip in clips.items():
        with open(clip, encoding="utf-8") as f:
            assert lineup.clean(f.read()) == got["can"][note_id].text
    real, calls = anki_miner.api, []

    def refuse_second(miner, args, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise anki_miner.AnkiMinerError("crashed", "Anki Miner stopped")
        return real(miner, args, **kw)
    monkeypatch.setattr(anki_miner, "api", refuse_second)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run2"))
    assert len(clips) == 2 and len(calls) == 2

    def refuse_first(miner, args, **kw):
        raise anki_miner.AnkiMinerError("crashed", "Anki Miner stopped")
    monkeypatch.setattr(anki_miner, "api", refuse_first)
    with pytest.raises(anki_miner.AnkiMinerError):
        add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run3"))


@pytest.mark.parametrize("raised, code", [
    ("miner", "failed"), ("wait", "busy"), ("needs", "needs-you"), ("os", "failed"), ("sqlite", "failed")])
def test_act_says_every_failure_in_plain_words(monkeypatch, tmp_path, raised, code):
    """S4: Anki Miner refusing, the library busy or unwritable, a disk or the ledger refusing — each the command
    line's error line in plain words, never a traceback."""
    import sqlite3
    from app.cli.contract import CliError
    from app.connect import anki_miner, runner
    _act_ready(monkeypatch, tmp_path)
    errors = {"miner": anki_miner.AnkiMinerError("crashed", "Anki Miner stopped answering."),
              "wait": runner.Wait("Surasura's library is busy just now."),
              "needs": runner.Needs("no-store", "Surasura's library can't be written just now."),
              "os": PermissionError("the folder is read-only"),
              "sqlite": sqlite3.OperationalError("database is locked")}

    def fails(*a, **k):
        raise errors[raised]
    monkeypatch.setattr(add_audio, "_add", fails)
    with pytest.raises(CliError) as e:
        add_audio.act({"connect_enabled": True}, "ja", book="x.epub", confirm=True)
    assert e.value.code == code and e.value.message


def test_a_write_stopped_part_way_names_its_undo_and_owes_the_sync(book, fake_miner, monkeypatch, tmp_path):
    """S5: Anki stops answering after two cards were written — the error says so with the Undo's id (and the record
    is there to take them back), and Anki's sync is owed for the two."""
    from app import anki_connect
    from app.cli.contract import CliError
    owed = _act_ready(monkeypatch, tmp_path)
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    real = book["anki"].update

    def stops(nid, fields):
        if nid == 102:
            raise anki_connect.AnkiError("Anki stopped answering")
        return real(nid, fields)
    monkeypatch.setattr(book["anki"], "update", stops)

    def add(settings, language, b, confirm, anki, ledger):
        return sa.fill(book["anki"], ledger, clips, field="SentenceAudio", tag=add_audio.TAG, by=add_audio.BY)
    monkeypatch.setattr(add_audio, "_add", add)
    with pytest.raises(CliError) as e:
        add_audio.act({"connect_enabled": True}, "ja", book="x.epub", confirm=True)
    rid = e.value.context.get("undo")
    assert rid and rid in e.value.message and owed
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        assert sorted(sa.record(ledger, rid)["notes"]) == ["100", "101", "102", "103", "104"]
        assert sa.undo(book["anki"], ledger, rid)["emptied"] == [100, 101]


def test_undo_takes_back_only_an_add_audio_and_anki_miner_absent_is_skipped(monkeypatch, tmp_path):
    """N: `--undo` with another path's record (the AI audio's) is no *Add audio* to take back; Anki Miner not
    installed is `skipped` (a known answer), never an unknown error code."""
    import json
    from app.cli.contract import CliError
    _act_ready(monkeypatch, tmp_path)
    with Ledger(str(tmp_path / "ledger.sqlite")) as ledger:
        ledger.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (sa.RECORD + "9-ai", json.dumps(
            {"field": "SentenceAudio", "tag": "x", "by": "ai-audio", "notes": {}, "media": [], "state": sa.DONE})))
    monkeypatch.setattr(sa, "AnkiConnectNotes", lambda url: FakeAnki())
    with pytest.raises(CliError) as e:
        add_audio.act({"connect_enabled": True}, "ja", undo_id="9-ai")
    assert e.value.code == "bad-data"
    epub = tmp_path / "b.epub"
    epub.write_bytes(b"PK")
    monkeypatch.setattr("app.cli.verbs._anki_miner_setup", lambda *a, **k: None)
    assert add_audio.act({"connect_enabled": True}, "ja", book=str(epub), confirm=True)["skipped"] == \
        "Anki Miner isn't installed: it cuts the clips."


# --- review A1 round 2 (Opus adversary, delta d9e610ba..6e3dd3a2) ------------------------------------------------ #
def _own_srt(tmp_path, lines):
    """A subtitle of `lines` [(start, end, text)] and an audio file beside it, as `cut` sends them."""
    srt = tmp_path / "own.srt"
    srt.write_text("\n".join(f"{n}\n00:00:{int(a):02d},{int(a * 1000) % 1000:03d} --> "
                             f"00:00:{int(z):02d},{int(z * 1000) % 1000:03d}\n{t}\n"
                             for n, (a, z, t) in enumerate(lines, 1)), encoding="utf-8")
    audio = tmp_path / "own.m4b"
    audio.write_bytes(b"\x00" * 64)
    return str(audio), str(srt)


def test_two_cues_of_one_start_whose_texts_are_a_prefix_never_share_a_clip(fake_miner, tmp_path):
    """r2 S1: 「そうか」 and 「そうか、わかった」 start together; Anki Miner's nearest line is the first's — the longer
    cue's card gets nothing rather than half its sentence (its end is another line's)."""
    audio, srt = _own_srt(tmp_path, [(10.0, 11.0, "そうか"), (10.0, 12.5, "そうか、わかった")])
    short = lineup.Cue(audio, srt, 10.0, 11.0, lineup.clean("そうか"))
    long_ = lineup.Cue(audio, srt, 10.0, 12.5, lineup.clean("そうか、わかった"))
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", {1: short, 2: long_}, str(tmp_path / "run"))
    assert sorted(clips) == [1]


def test_a_speaker_tag_anki_miner_drops_is_still_the_line_and_a_changed_reading_is_skipped(fake_miner, tmp_path):
    """r2 S3: Anki Miner answers a line with its leading speaker tag removed — still that line; a line whose text it
    changed mid-line (furigana in brackets) no longer holds the cue's — that card is skipped, never mismatched."""
    audio, srt = _own_srt(tmp_path, [(2.0, 3.5, "（太郎）明日は早く出かけるよ"), (4.0, 5.5, "彼（かれ）は毎日冒険に出かけます")])
    tagged = lineup.Cue(audio, srt, 2.0, 3.5, lineup.clean("（太郎）明日は早く出かけるよ"))
    ruby = lineup.Cue(audio, srt, 4.0, 5.5, lineup.clean("彼（かれ）は毎日冒険に出かけます"))
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", {1: tagged, 2: ruby}, str(tmp_path / "run"))
    assert sorted(clips) == [1]


def test_nothing_cut_says_why_and_a_part_cut_names_why_the_rest_werent(book, fake_miner, tmp_path, monkeypatch):
    """r2 S2: every run refused (the audio unreadable) is an error in Anki Miner's words, never *0 filled* unexplained;
    a later call refused after some clips: the answer keeps its reason for the rest."""
    from app.connect import anki_miner
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    real = anki_miner.api

    def refused(miner, args, **kw):
        job = lineup._read_json(args[1])
        return {"ok": True, "runs": [{"run_id": e["run_id"], "ok": False, "error": "SOURCE_UNREADABLE",
                                      "message": "The audio file can't be read."} for e in job["episodes"]]}
    monkeypatch.setattr(anki_miner, "api", refused)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert "can't be read" in e.value.message
    monkeypatch.setattr(add_audio, "CUT_LINES", 2)
    calls, troubles = [], []

    def refuse_second(miner, args, **kw):
        calls.append(1)
        if len(calls) == 2:
            raise anki_miner.AnkiMinerError("timeout", "Anki Miner took too long.")
        return real(miner, args, **kw)
    monkeypatch.setattr(anki_miner, "api", refuse_second)
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run2"), troubles=troubles)
    assert len(clips) == 2 and troubles == ["Anki Miner took too long."]


def test_a_sentence_that_is_a_cue_once_wins_over_a_longer_line_holding_it_elsewhere(book, monkeypatch):
    """r3 S1 (round 2's N4 reverted): the card's sentence is a cue once and also said inside a longer line elsewhere —
    its own cue says its words word for word: heard (a short card isn't silenced for a longer line's sake)."""
    real = lineup.cues

    def also_inside(state):
        found = real(state)
        c = next(c for c in found if c.text == lineup.clean(book["lines"][1]))     # 冒険する — card 100
        return found + [c._replace(start=500.0, end=503.0, text=lineup.clean("彼はもう一度冒険するつもりだ"))]
    monkeypatch.setattr(lineup, "cues", also_inside)
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert got["can"][100].text == lineup.clean(book["lines"][1]) and got["can"][100].start != 500.0


def test_square_brackets_that_are_not_furigana_stay_in_the_sentence():
    """r2 N6: only Anki's kana furigana in brackets is dropped — メール[添付あり] keeps its words."""
    assert add_audio._text(" 彼[かれ]はメール[添付あり]を送った") == "彼はメール[添付あり]を送った"


def test_the_bold_sharing_the_words_kanji_is_its_form():
    """r2 N7: a stray bold (an emphasis) never stands for the word; the bold sharing its kanji does."""
    assert add_audio._form("<b>本当に</b>彼は<b>出</b>かけた", "出かける") == "出"
    assert add_audio._form("<b>本当に</b>彼は出かけた", "行く") == "本当に"


@pytest.mark.parametrize("raised, code", [("toonew", "needs-you"), ("reviewing", "anki-busy"),
                                          ("busy", "busy"), ("anki", "anki-closed"), ("file", "failed")])
def test_act_says_the_other_failures_in_plain_words_too(monkeypatch, tmp_path, raised, code):
    """r2 gap: the ledger too new, you reviewing, the writer held, Anki closed — and a file's trouble named as a
    file's (never as Connect's records)."""
    from app import anki_connect, locks
    from app.cli.contract import CliError
    from app.connect.ledger import TooNew
    _act_ready(monkeypatch, tmp_path)
    errors = {"toonew": TooNew(99), "reviewing": sa.Reviewing(), "busy": locks.Busy("anki-writer"),
              "anki": anki_connect.AnkiError("closed"), "file": PermissionError("media-1.json")}

    def fails(*a, **k):
        raise errors[raised]
    monkeypatch.setattr(add_audio, "_add", fails)
    with pytest.raises(CliError) as e:
        add_audio.act({"connect_enabled": True}, "ja", book="x.epub", confirm=True)
    assert e.value.code == code and e.value.message
    if raised == "file":
        assert "records" not in e.value.message


def _act_book(book, fake_miner, monkeypatch, tmp_path):
    """`act` on the fixture's book end to end: its steps, its Anki, the fake Anki Miner, Connect's folder in tmp."""
    from app.connect import anki_miner, runner
    owed = _act_ready(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "Steps", lambda settings: book["steps"])
    monkeypatch.setattr(anki_miner, "find", lambda settings: fake_miner.path)
    monkeypatch.setattr("app.cli.verbs._anki_miner_setup", lambda *a, **k: ({}, "p-surasura", MAPPING))
    monkeypatch.setattr("app.cli.verbs._connect_folder", lambda: str(tmp_path / "connect"))
    monkeypatch.setattr(sa, "AnkiConnectNotes", lambda url: book["anki"])
    return owed


def test_act_end_to_end_plans_then_fills_and_owes_the_sync(book, fake_miner, monkeypatch, tmp_path):
    """The command line's sequence with a real book: the plan writes nothing; `--confirm` fills the five, owes the
    sync, and leaves no run folder behind."""
    owed = _act_book(book, fake_miner, monkeypatch, tmp_path)
    plan = add_audio.act({"connect_enabled": True}, "ja", book=book["book"])
    assert plan["confirm"] is False and plan["can"] == 5 and not owed
    done = add_audio.act({"connect_enabled": True}, "ja", book=book["book"], confirm=True)
    assert done["filled"] == 5 and done["not_cut"] == 0 and owed
    assert not os.listdir(str(tmp_path / "connect" / "add-audio"))


def test_act_end_to_end_a_write_stopped_part_way_names_its_undo(book, fake_miner, monkeypatch, tmp_path):
    """r2 gap: the real `_add` → `fill` stopping part-way (Anki stops answering at the third card): the error names
    the Undo, the sync is owed, the run folder is gone."""
    from app import anki_connect
    from app.cli.contract import CliError
    owed = _act_book(book, fake_miner, monkeypatch, tmp_path)
    real = book["anki"].update

    def stops(nid, fields):
        if nid == 102:
            raise anki_connect.AnkiError("Anki stopped answering")
        return real(nid, fields)
    monkeypatch.setattr(book["anki"], "update", stops)
    with pytest.raises(CliError) as e:
        add_audio.act({"connect_enabled": True}, "ja", book=book["book"], confirm=True)
    assert e.value.code == "anki-closed" and e.value.context["undo"] in e.value.message and owed
    assert not os.listdir(str(tmp_path / "connect" / "add-audio"))


# --- review A1 round 3 (Opus adversary, delta 6e3dd3a2..b0442b67) ------------------------------------------------ #
def test_every_line_past_the_audios_end_says_so_and_a_part_past_it_names_its_file(book, fake_miner, tmp_path):
    """r3 S2: Anki Miner cut no clip at all (every line past the audio's end, its `audio` null) — an error saying so,
    never *0 cut* unexplained; one line past it: the answer's reason names that file."""
    from app.connect import anki_miner
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    fake_miner.plan(audio_seconds=0.5)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert "past the audio's end" in e.value.message
    last = max(got["can"], key=lambda n: got["can"][n].start)
    fake_miner.plan(audio_seconds=got["can"][last].start - 0.1)
    troubles = []
    clips = add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run2"), troubles=troubles)
    assert len(clips) == 4
    assert troubles == [os.path.basename(got["can"][last].audio) + ": " + add_audio.NO_CLIP.format(n=1)]


def test_a_refused_file_keeps_anki_miners_own_kind(book, fake_miner, tmp_path, monkeypatch):
    """r3 N3: every file refused as unreadable is Anki Miner's `unreadable` (the command line's bad-data), not a
    generic refusal."""
    from app.connect import anki_miner
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)

    def unreadable(miner, args, **kw):
        job = lineup._read_json(args[1])
        return {"ok": True, "runs": [{"run_id": e["run_id"], "ok": False, "error": "AUDIO_UNREADABLE",
                                      "message": "The audio can't be read."} for e in job["episodes"]]}
    monkeypatch.setattr(anki_miner, "api", unreadable)
    with pytest.raises(anki_miner.AnkiMinerError) as e:
        add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))
    assert e.value.kind == "unreadable"


def test_an_answered_line_without_its_times_is_never_taken_for_the_cue(book, fake_miner, tmp_path, monkeypatch):
    """r3 N6: a line with no `start` / `end` can't be checked for its length (another line of the same start): no
    clip from it."""
    from app.connect import anki_miner
    real = anki_miner.api

    def no_times(miner, args, **kw):
        verdict = real(miner, args, **kw)
        for run in verdict.get("runs") or ():
            path = os.path.join(str(tmp_path / "run"), run["run_id"], run["file"])
            made = lineup._read_json(path)
            made["lines"] = [dict(line, end=None) for line in made["lines"]]
            lineup._write_json(path, made)
        return verdict
    monkeypatch.setattr(anki_miner, "api", no_times)
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    with pytest.raises(anki_miner.AnkiMinerError):
        add_audio.cut(fake_miner.path, "ja", "p-surasura", got["can"], str(tmp_path / "run"))


def test_a_short_line_inside_a_card_said_over_several_cues_never_stands_for_it(book):
    """Mutant B4 (survived): a card whose sentence is said over two cues — a short one (冒険だ, under MIN_CHARS: too
    little to be sure of, and said anywhere) and a long one — is placed on the long one holding its word; the short
    one is never a rival that leaves the card unheard, nor its answer."""
    _made(book, 130, book["lines"][0] + book["lines"][8].replace("冒険", "<b>冒険</b>"), "冒険")
    got = add_audio.plan(book["anki"], book["steps"], "ja", book["book"], MAPPING)
    assert got["can"][130].text == lineup.clean(book["lines"][8])
