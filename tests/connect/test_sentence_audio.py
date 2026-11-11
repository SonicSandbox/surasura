"""The one sentence-audio writer (`app/connect/sentence_audio.py`, Kura-AB3; shared with Iro-AA's AI audio): it fills
ONLY an empty SentenceAudio, tags what it filled, and keeps one Undo record a call.

What a wrong answer would cost: these writes land in the learner's own notes. A field overwritten loses audio he chose
(a clip of his, another miner's); a field other than SentenceAudio touched breaks his card layout; a note filled while
he reviews it fights Anki's reviewer; an Undo that empties a field he edited since, or deletes a clip another note
still plays, destroys his work; a write with no record before it can't be undone after a crash.

Real data: notes shaped as the learner's Lapis cards are (`Anki_Card_Layout_Spec.md`: Expression / Sentence /
SentenceAudio / Picture), their sentences the real 杜子春 line-up's (`Test Resources/ja/audiobook_sync/`); the clips
real files on disk; Anki is a fake answering as AnkiConnect does (notesInfo's shape).
"""
import contextlib
import os

import pytest

from app.connect import lineup, sentence_audio as sa
from app.connect.ledger import Ledger

SYNCED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources", "ja",
                      "audiobook_sync")


def _sentences():
    return [t for _s, _e, t in lineup.srt_cues(os.path.join(SYNCED, "toshisyun_01.srt"))]


class FakeAnki:
    """AnkiConnect as `sentence_audio` sees it: notes (notesInfo's shape), media, tags, the reviewer, the lock."""

    def __init__(self):
        self.notes_ = {}
        self.media = {}
        self.calls = []
        self.reviewing_ = False
        self.locked = False
        self.fail_on_update = None

    def add(self, nid, sentence, word, audio="", model_fields=None):
        fields = model_fields or {"Expression": word, "Sentence": sentence, "SentenceAudio": audio,
                                  "Picture": '<img src="cover.jpg">'}
        self.notes_[nid] = {"noteId": nid, "fields": {k: {"value": v, "order": i} for i, (k, v) in
                                                      enumerate(fields.items())}, "tags": ["surasura::connect::x-1"]}

    def value(self, nid, field="SentenceAudio"):
        return self.notes_[nid]["fields"][field]["value"]

    def reviewing(self):
        return self.reviewing_

    @contextlib.contextmanager
    def writer(self, verb):
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def notes(self, ids):
        self.calls.append(("notes", tuple(ids)))
        return [self.notes_.get(n, {}) for n in ids]

    def store(self, name, data):
        assert self.locked
        self.calls.append(("store", name))
        self.media.setdefault(name, data)

    def update(self, nid, fields):
        assert self.locked
        if self.fail_on_update == nid:
            raise RuntimeError("Anki stopped answering")
        self.calls.append(("update", nid, tuple(fields)))
        for k, v in fields.items():
            self.notes_[nid]["fields"][k]["value"] = v

    def tag(self, ids, tag, on=True):
        assert self.locked
        self.calls.append(("tag", tuple(ids), tag, on))
        for n in ids:
            tags = self.notes_[n]["tags"]
            if on and tag not in tags:
                tags.append(tag)
            elif not on and tag in tags:
                tags.remove(tag)

    def users(self, name):
        return [n for n, note in self.notes_.items() if any(name in f["value"] for f in note["fields"].values())]

    def delete_media(self, name):
        self.calls.append(("delete", name))
        self.media.pop(name, None)


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    yield book
    book.close()


def _clip(tmp_path, name, body):
    path = tmp_path / name
    path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + body.encode("utf-8"))
    return str(path)


def test_only_an_empty_sentence_audio_is_filled_and_nothing_else_of_the_note_is_written(tmp_path, ledger):
    """Three text-only cards and one with audio already: the three get `[sound:…]` in SentenceAudio and the tag; the
    fourth is skipped with its why; Expression, Sentence and Picture are byte for byte as before; each update names
    SentenceAudio alone."""
    anki, lines = FakeAnki(), _sentences()
    for n in range(1, 4):
        anki.add(n, lines[n], lines[n][:2])
    anki.add(4, lines[4], lines[4][:2], audio="[sound:his_own.mp3]")
    before = {n: {k: f["value"] for k, f in anki.notes_[n]["fields"].items() if k != "SentenceAudio"} for n in anki.notes_}
    clips = {n: _clip(tmp_path, f"{n}.mp3", lines[n]) for n in range(1, 5)}
    got = sa.fill(anki, ledger, clips, by="add-audio")
    assert got["filled"] == [1, 2, 3] and got["skipped"] == {4: sa.HAS_AUDIO}
    assert anki.value(4) == "[sound:his_own.mp3]", "never overwritten"
    for n in (1, 2, 3):
        assert anki.value(n).startswith("[sound:surasura-sa-") and sa.TAG in anki.notes_[n]["tags"]
    assert sa.TAG not in anki.notes_[4]["tags"]
    after = {n: {k: f["value"] for k, f in anki.notes_[n]["fields"].items() if k != "SentenceAudio"} for n in anki.notes_}
    assert after == before
    assert {c[2] for c in anki.calls if c[0] == "update"} == {("SentenceAudio",)}
    rec = sa.record(ledger, got["id"])
    assert rec["state"] == sa.DONE and rec["by"] == "add-audio" and set(rec["notes"]) == {"1", "2", "3"}


def test_a_field_filled_between_the_plan_and_the_write_is_read_again_under_the_lock_and_kept(tmp_path, ledger):
    """The note is read under Anki's write lock, just before its write: audio another path put there meanwhile (or a
    space typed by hand) is never overwritten; a note gone, or of a type with no SentenceAudio, is skipped."""
    anki, lines = FakeAnki(), _sentences()
    anki.add(1, lines[1], "x", audio=" ")
    anki.add(2, lines[2], "y", model_fields={"Front": lines[2], "Back": "y"})
    got = sa.fill(anki, ledger, {1: _clip(tmp_path, "a.mp3", "a"), 2: _clip(tmp_path, "b.mp3", "b"),
                                 3: _clip(tmp_path, "c.mp3", "c")})
    assert got == {"id": None, "filled": [], "skipped": {1: sa.HAS_AUDIO, 2: sa.NO_FIELD.format(field=sa.FIELD),
                                                         3: sa.GONE}}
    assert not [c for c in anki.calls if c[0] in ("store", "update", "tag")] and sa.record(ledger, "x") is None


def test_one_clip_for_two_notes_is_one_file_and_a_missing_clip_is_skipped(tmp_path, ledger):
    anki, lines = FakeAnki(), _sentences()
    anki.add(1, lines[1], "a")
    anki.add(2, lines[1], "b")
    anki.add(3, lines[3], "c")
    same = _clip(tmp_path, "same.mp3", lines[1])
    got = sa.fill(anki, ledger, {1: same, 2: same, 3: str(tmp_path / "gone.mp3")})
    assert got["filled"] == [1, 2] and got["skipped"] == {3: sa.NO_CLIP}
    assert len(anki.media) == 1 and anki.value(1) == anki.value(2)


def test_never_while_you_review_in_anki(tmp_path, ledger):
    anki = FakeAnki()
    anki.add(1, _sentences()[1], "a")
    anki.reviewing_ = True
    with pytest.raises(sa.Reviewing):
        sa.fill(anki, ledger, {1: _clip(tmp_path, "a.mp3", "a")})
    assert anki.value(1) == "" and not anki.calls


def test_undo_empties_only_what_it_wrote_keeps_your_edit_and_a_clip_another_note_plays(tmp_path, ledger):
    """One Undo: the fields still holding what was written go back to empty and lose the tag; one you changed since
    keeps your change; the clip a note still names (here: your edit pointed another note at it) stays; the rest of
    the clips are deleted; a second Undo writes nothing."""
    anki, lines = FakeAnki(), _sentences()
    for n in range(1, 4):
        anki.add(n, lines[n], "w")
    anki.add(9, lines[0], "his")
    clips = {n: _clip(tmp_path, f"{n}.mp3", lines[n]) for n in range(1, 4)}
    got = sa.fill(anki, ledger, clips)
    shared = anki.value(3)
    anki.notes_[2]["fields"]["SentenceAudio"]["value"] = "[sound:his_better.mp3]"     # your edit since
    anki.notes_[9]["fields"]["SentenceAudio"]["value"] = shared                       # another note plays clip 3
    anki.notes_[3]["fields"]["SentenceAudio"]["value"] = shared
    done = sa.undo(anki, ledger, got["id"])
    assert done["emptied"] == [1, 3] and done["kept"] == {2: "changed since"}
    assert anki.value(1) == anki.value(3) == "" and anki.value(2) == "[sound:his_better.mp3]"
    assert sa.TAG not in anki.notes_[1]["tags"] and sa.TAG in anki.notes_[2]["tags"]
    name3 = shared[len("[sound:"):-1]
    assert name3 in anki.media and name3 not in done["deleted"] and len(done["deleted"]) == 2
    assert sa.record(ledger, got["id"])["state"] == sa.UNDONE
    calls = len(anki.calls)
    assert sa.undo(anki, ledger, got["id"])["refused"] and len(anki.calls) == calls


def test_a_call_killed_mid_way_has_its_record_first_and_its_undo_takes_back_what_reached_anki(tmp_path, ledger):
    """The record is written before Anki is: Anki failing on the second note leaves the first filled and the record
    `writing`; its Undo empties the first and says the second was never written."""
    anki, lines = FakeAnki(), _sentences()
    anki.add(1, lines[1], "a")
    anki.add(2, lines[2], "b")
    anki.fail_on_update = 2
    with pytest.raises(RuntimeError):
        sa.fill(anki, ledger, {1: _clip(tmp_path, "a.mp3", "a"), 2: _clip(tmp_path, "b.mp3", "b")})
    [(key, _v)] = ledger.conn.execute("SELECT key, value FROM meta WHERE key LIKE ?", (sa.RECORD + "%",)).fetchall()
    rid = key[len(sa.RECORD):]
    assert sa.record(ledger, rid)["state"] == sa.WRITING and anki.value(1).startswith("[sound:")
    done = sa.undo(anki, ledger, rid)
    assert done["emptied"] == [1] and done["kept"] == {2: "never written"} and anki.value(1) == ""


def test_a_caller_names_its_own_field_and_tag(tmp_path, ledger):
    """The AI audio's path (Iro-AA) or a mapping that names the field otherwise: the same rules on that field."""
    anki, lines = FakeAnki(), _sentences()
    anki.add(1, lines[1], "a", model_fields={"Word": "a", "Sentence": lines[1], "SentAudio": ""})
    got = sa.fill(anki, ledger, {1: _clip(tmp_path, "a.mp3", "a")}, field="SentAudio", tag="surasura::ai-audio",
                  by="ai-audio")
    assert got["filled"] == [1] and anki.value(1, "SentAudio").startswith("[sound:")
    assert "surasura::ai-audio" in anki.notes_[1]["tags"] and sa.record(ledger, got["id"])["tag"] == "surasura::ai-audio"
