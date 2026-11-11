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
from tests.connect.test_lineup_own_subtitle import _job, _pair, _trust
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
