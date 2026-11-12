"""The one field writer (`app/connect/sentence_audio.py`, Kura-AB3's, generalised by Piyo-TR): a text into ANY field of a
card — a translation into the field the card's 翻訳 toggle shows (Lapis: `Hint`) — by the same contract as the audio:
only an empty field, the tag, one Undo record a call, written before Anki is.

What a wrong answer would cost: these writes land in the learner's own notes. A translation over one he wrote (or one
Anki Miner took from a second subtitle track) loses his; a field other than the one named touched breaks his card;
an Undo that empties a translation he corrected since destroys his work; the audio callers (Kura-AB3's *Add audio*,
Iro-AA's AI audio) must keep working exactly as before.

Real data: notes shaped as Lapis cards (Expression / Sentence / SentenceAudio / Hint), their sentences from the
public-domain 蜘蛛の糸 in `samples/ja/`; Anki is the audio tests' fake (notesInfo's shape).
"""
import os

import pytest

from app.connect import sentence_audio as sa
from app.connect.ledger import Ledger
from tests.connect.test_sentence_audio import FakeAnki

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPIDER = [("極楽", "ある日の事でございます。御釈迦様は極楽の蓮池のふちを、独りでぶらぶら御歩きになっていらっしゃいました。",
           "It was one day. The Buddha was strolling alone along the edge of the lotus pond in <b>paradise</b>."),
          ("犍陀多", "この犍陀多と云う男は、人を殺したり家に火をつけたり、いろいろ悪事を働いた大泥坊でございます。",
           "This man, <b>Kandata</b>, was a great thief who had killed people and set houses on fire."),
          ("蜘蛛", "御釈迦様はその蜘蛛の糸をそっと御手に御取りになって、玉のような白蓮の間から、遥か下にある地獄の底へ、まっすぐにそれを御下しなさいました。",
           "The Buddha gently took the <b>spider</b>'s thread in his hand and lowered it straight down to the depths of hell."),
          ("地獄", "こちらは地獄の底の血の池で、ほかの罪人と一しょに、浮いたり沈んだりしていた犍陀多でございます。",
           "Down here, in the pool of blood at the bottom of <b>hell</b>, Kandata was floating and sinking with the others.")]


def _lapis(anki, nid, word, sentence, hint=""):
    anki.add(nid, sentence, word, model_fields={"Expression": word, "Sentence": f"{sentence}", "SentenceAudio": "",
                                                 "Hint": hint, "Picture": ""})


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    yield book
    book.close()


def test_a_translation_fills_only_an_empty_hint_and_names_that_field_alone(ledger):
    """Three cards with an empty Hint get the text as given; the fourth, whose Hint holds the learner's own words, is
    skipped with a why that names the field (never "sentence audio"); every update names Hint alone; the tag is the
    caller's; nothing else of a note changes; no media is stored."""
    anki = FakeAnki()
    for n, (word, sentence, _t) in enumerate(SPIDER, 1):
        _lapis(anki, n, word, sentence, hint="my own: the hell pool" if n == 4 else "")
    before = {n: {k: f["value"] for k, f in anki.notes_[n]["fields"].items() if k != "Hint"} for n in anki.notes_}
    texts = {n: t for n, (_w, _s, t) in enumerate(SPIDER, 1)}
    got = sa.fill(anki, ledger, None, field="Hint", tag="surasura::translated", by="piyo", texts=texts)
    assert got["filled"] == [1, 2, 3]
    assert got["skipped"] == {4: sa.HAS_TEXT.format(field="Hint")}
    assert anki.value(4, "Hint") == "my own: the hell pool", "never overwritten"
    for n in (1, 2, 3):
        assert anki.value(n, "Hint") == texts[n] and "surasura::translated" in anki.notes_[n]["tags"]
    assert {c[2] for c in anki.calls if c[0] == "update"} == {("Hint",)}
    assert not [c for c in anki.calls if c[0] == "store"] and not anki.media
    after = {n: {k: f["value"] for k, f in anki.notes_[n]["fields"].items() if k != "Hint"} for n in anki.notes_}
    assert after == before
    rec = sa.record(ledger, got["id"])
    assert rec["state"] == sa.DONE and rec["by"] == "piyo" and rec["media"] == [] and rec["field"] == "Hint"


def test_each_note_can_name_its_own_field_and_one_undo_takes_back_the_whole_batch(ledger):
    """A batch across two note types (Lapis's Hint, another's SentenceTranslation) is ONE call and ONE Undo record: the
    Undo empties each note's own field, only where it still holds what was written (a correction since is kept), and
    takes the tag off those notes alone."""
    anki = FakeAnki()
    _lapis(anki, 1, *SPIDER[0][:2])
    _lapis(anki, 2, *SPIDER[1][:2])
    anki.add(3, SPIDER[2][1], SPIDER[2][0], model_fields={"Word": SPIDER[2][0], "Sentence": SPIDER[2][1],
                                                          "SentenceTranslation": ""})
    fields = {1: "Hint", 2: "Hint", 3: "SentenceTranslation"}
    texts = {n: SPIDER[n - 1][2] for n in (1, 2, 3)}
    got = sa.fill(anki, ledger, None, field=fields, tag="surasura::translated", by="piyo", texts=texts)
    assert got["filled"] == [1, 2, 3] and got["skipped"] == {}
    assert anki.value(3, "SentenceTranslation") == texts[3]
    assert ("update", 3, ("SentenceTranslation",)) in anki.calls
    anki.notes_[2]["fields"]["Hint"]["value"] = "This man, <b>Kandata</b>, was a great robber."   # his correction
    done = sa.undo(anki, ledger, got["id"])
    assert done["emptied"] == [1, 3] and done["kept"] == {2: "changed since"} and done["deleted"] == []
    assert anki.value(1, "Hint") == "" and anki.value(3, "SentenceTranslation") == ""
    assert anki.value(2, "Hint").endswith("great robber.")
    assert "surasura::translated" in anki.notes_[2]["tags"]
    assert "surasura::translated" not in anki.notes_[1]["tags"] + anki.notes_[3]["tags"]
    assert sa.record(ledger, got["id"])["state"] == sa.UNDONE


def test_a_note_without_the_named_field_or_an_empty_text_is_skipped_and_nothing_is_recorded_for_it(ledger):
    """A note type without the field, a note gone, a blank text: each skipped with its why, nothing written; when
    nothing is left, no record is made at all (no Undo for nothing)."""
    anki = FakeAnki()
    anki.add(1, SPIDER[0][1], SPIDER[0][0], model_fields={"Front": SPIDER[0][1], "Back": "x"})
    _lapis(anki, 2, *SPIDER[1][:2])
    got = sa.fill(anki, ledger, None, field="Hint", tag="t", by="piyo", texts={1: "a <b>b</b>", 2: "   ", 3: "<b>c</b>"})
    assert got == {"id": None, "filled": [],
                   "skipped": {1: sa.NO_FIELD.format(field="Hint"), 2: sa.NO_TEXT, 3: sa.GONE}}
    assert not [c for c in anki.calls if c[0] in ("update", "tag")]
    assert sa.pending(ledger) == []


def test_a_space_in_the_field_counts_as_filled_and_reviewing_writes_nothing(ledger):
    """The same rule as the audio: anything in the field (a space) is the learner's; while he reviews, nothing."""
    anki = FakeAnki()
    _lapis(anki, 1, *SPIDER[0][:2], hint=" ")
    _lapis(anki, 2, *SPIDER[1][:2])
    got = sa.fill(anki, ledger, None, field="Hint", tag="t", by="piyo", texts={1: SPIDER[0][2], 2: SPIDER[1][2]})
    assert got["filled"] == [2] and got["skipped"] == {1: sa.HAS_TEXT.format(field="Hint")}
    anki.reviewing_ = True
    _lapis(anki, 3, *SPIDER[2][:2])
    with pytest.raises(sa.Reviewing):
        sa.fill(anki, ledger, None, field="Hint", tag="t", by="piyo", texts={3: SPIDER[2][2]})
    assert anki.value(3, "Hint") == ""


def test_a_write_that_fails_part_way_leaves_its_record_and_its_undo_takes_back_what_was_written(ledger):
    """Anki stops answering at the second note: the first is written and recorded; the record is `writing`
    (`pending`), the error carries its id, and its Undo empties the one written."""
    anki = FakeAnki()
    for n in (1, 2, 3):
        _lapis(anki, n, *SPIDER[n - 1][:2])
    anki.fail_on_update = 2
    with pytest.raises(RuntimeError) as e:
        sa.fill(anki, ledger, None, field="Hint", tag="t", by="piyo", texts={n: SPIDER[n - 1][2] for n in (1, 2, 3)})
    rid = e.value.sentence_audio_id
    assert sa.pending(ledger) == [rid]
    assert anki.value(1, "Hint") == SPIDER[0][2]
    assert sa.undo(anki, ledger, rid)["emptied"] == [1]
    assert anki.value(1, "Hint") == ""


def test_clips_and_texts_in_one_call_are_refused(tmp_path, ledger):
    """One call writes one kind: a clip and a text together is a caller's mistake, refused before anything is read."""
    anki = FakeAnki()
    _lapis(anki, 1, *SPIDER[0][:2])
    clip = tmp_path / "a.mp3"
    clip.write_bytes(b"ID3")
    with pytest.raises(ValueError):
        sa.fill(anki, ledger, {1: str(clip)}, field="Hint", texts={1: SPIDER[0][2]})
    assert anki.calls == []
