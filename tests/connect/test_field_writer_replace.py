"""The one field writer's replace mode (`sentence_audio.replace`, FS-1: the full Swap rewrites a card's sentence side in
place) and its Undo.

What a wrong answer would cost: these writes overwrite the learner's own card. A field written while it no longer holds
what Swap read loses an edit of theirs; the old clip deleted before a copy is kept (or while another note still plays
it) can never be put back; an Undo that writes over an edit made since destroys it; a write Anki silently didn't keep
(the note open in its editor) offered as made would leave an Undo that "restores" a card that never changed.

Real data: the learner's Lapis fields (`Anki_Card_Layout_Spec.md`), the sentences real lines of the 杜子春 line-up
(ja) and of `night_market.srt` (zh); the clips real files on disk; Anki the writer tests' fake (AnkiConnect's shapes).
"""
import base64
import os

import pytest

from app import cues
from app.connect import sentence_audio as sa
from tests.connect.test_sentence_audio import FakeAnki, _clip, _sentences, ledger  # noqa: F401  (the fixture)

ZH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources", "zh")


class Anki(FakeAnki):
    """The writer tests' fake, plus reading a media file back and a note open in Anki's editor (its write ignored)."""

    def __init__(self):
        super().__init__()
        self.editor_open = set()

    def read_media(self, name):
        data = self.media.get(name)
        return base64.b64decode(data) if data else None

    def update(self, nid, fields):
        if nid in self.editor_open:
            self.calls.append(("update ignored", nid))
            return
        super().update(nid, fields)


def _zh_line():
    for name in sorted(os.listdir(ZH)):
        if name.endswith(".srt"):
            for cue in cues.read(os.path.join(ZH, name), "zh"):
                if len(cue.text) >= 6:
                    return cue.text
    pytest.skip("no Chinese subtitle in Test Resources/zh")


def _card(anki, nid, sentence, clip="sl-old.mp3", picture="sl-old.webp"):
    anki.add(nid, sentence, "仙人", audio=f"[sound:{clip}]", model_fields={
        "Expression": "仙人", "Sentence": sentence, "SentenceAudio": f"[sound:{clip}]",
        "Picture": f'<img src="{picture}">', "SentenceFurigana": "", "Hint": "a hermit", "MiscInfo": ""})
    anki.media[clip] = base64.b64encode(b"ID3 old clip").decode("ascii")
    anki.media[picture] = base64.b64encode(b"RIFF old picture").decode("ascii")


def _was(anki, nid, fields):
    return {f: anki.value(nid, f) for f in fields}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_replace_writes_the_sentence_side_keeps_the_old_media_first_and_undo_puts_it_all_back(tmp_path, ledger,
                                                                                               lang):
    """The whole round: the new sentence, clip and picture written over the old ones (the old two copied and read back
    first, then gone from Anki: no other note names them), the tag on; Undo: the old values back, the old files stored
    again from the copy, the new files gone, the tag off. The word's side (Expression) is never written."""
    anki = Anki()
    old, line = _sentences()[3], (_sentences()[7] if lang == "ja" else _zh_line())
    _card(anki, 1, old)
    clip = _clip(tmp_path, "sl-new.mp3", line)
    new = {"Sentence": line, "SentenceAudio": "[sound:sl-new.mp3]", "Picture": "", "SentenceFurigana": ""}
    got = sa.replace(anki, ledger, 1, new, _was(anki, 1, new), media={"sl-new.mp3": clip},
                     keep_dir=str(tmp_path / "kept"), tag="surasura::swapped")
    assert got["filled"] == [1] and got["id"]
    assert anki.value(1, "Sentence") == line and anki.value(1, "SentenceAudio") == "[sound:sl-new.mp3]"
    assert anki.value(1, "Expression") == "仙人" and anki.value(1, "Hint") == "a hermit"
    assert "sl-old.mp3" not in anki.media and "sl-old.webp" not in anki.media          # gone: no note names them
    kept = os.listdir(tmp_path / "kept" / got["id"])
    assert sorted(kept) == ["sl-old.mp3", "sl-old.webp"]                                # copied before, read back
    assert "surasura::swapped" in anki.notes_[1]["tags"]
    assert sa.record(ledger, got["id"])["state"] == sa.DONE
    back = sa.undo(anki, ledger, got["id"])
    assert back["emptied"] == [1] and back["deleted"] == ["sl-new.mp3"]
    assert anki.value(1, "Sentence") == old and anki.value(1, "SentenceAudio") == "[sound:sl-old.mp3]"
    assert anki.value(1, "Picture") == '<img src="sl-old.webp">'
    assert base64.b64decode(anki.media["sl-old.mp3"]) == b"ID3 old clip"               # stored again from the copy
    assert "surasura::swapped" not in anki.notes_[1]["tags"]
    assert sa.undo(anki, ledger, got["id"])["refused"]                                  # twice: nothing more


def test_a_field_changed_since_it_was_read_refuses_the_whole_note(tmp_path, ledger):
    """The phone or the learner changed the sentence between Swap's look and its write: not one field is written,
    no record, nothing deleted (all or nothing for a note)."""
    anki = Anki()
    _card(anki, 1, _sentences()[3])
    new = {"Sentence": _sentences()[7], "SentenceAudio": ""}
    was = _was(anki, 1, new)
    anki.notes_[1]["fields"]["Sentence"]["value"] = _sentences()[3] + "（自分で直した）"
    got = sa.replace(anki, ledger, 1, new, was, keep_dir=str(tmp_path / "kept"))
    assert got == {"id": None, "filled": [], "skipped": {1: sa.CHANGED}}
    assert anki.value(1, "SentenceAudio") == "[sound:sl-old.mp3]" and "sl-old.mp3" in anki.media
    assert not [c for c in anki.calls if c[0] in ("update", "store", "delete")]
    assert not sa.pending(ledger)


def test_undo_after_a_hand_edit_is_refused_and_writes_nothing(tmp_path, ledger):
    """The learner fixed the new sentence after the swap: Undo keeps their edit (no field written, the record still
    open, so it works once they put the swap's text back)."""
    anki = Anki()
    _card(anki, 1, _sentences()[3])
    new = {"Sentence": _sentences()[7], "SentenceAudio": "[sound:sl-old.mp3]"}
    got = sa.replace(anki, ledger, 1, new, _was(anki, 1, new), keep_dir=str(tmp_path / "kept"))
    anki.notes_[1]["fields"]["Sentence"]["value"] = "直した文"
    writes = len([c for c in anki.calls if c[0] == "update"])
    back = sa.undo(anki, ledger, got["id"])
    assert back["emptied"] == [] and back["kept"] == {1: "changed since"}
    assert len([c for c in anki.calls if c[0] == "update"]) == writes
    assert sa.record(ledger, got["id"])["state"] == sa.DONE


def test_an_old_clip_another_card_still_plays_stays_in_anki(tmp_path, ledger):
    """Two cards cut from one line share its clip: one swapped, the clip stays for the other (users)."""
    anki = Anki()
    _card(anki, 1, _sentences()[3])
    anki.add(2, _sentences()[3], "杜子春", audio="[sound:sl-old.mp3]")
    new = {"SentenceAudio": ""}
    sa.replace(anki, ledger, 1, new, _was(anki, 1, new), keep_dir=str(tmp_path / "kept"))
    assert "sl-old.mp3" in anki.media


def test_a_note_open_in_ankis_editor_keeps_its_fields_and_offers_no_undo(tmp_path, ledger):
    """Anki's editor keeps its own copy: the write is read back, NOT_APPLIED, the old files never deleted."""
    anki = Anki()
    _card(anki, 1, _sentences()[3])
    anki.editor_open.add(1)
    new = {"Sentence": _sentences()[7], "SentenceAudio": ""}
    got = sa.replace(anki, ledger, 1, new, _was(anki, 1, new), keep_dir=str(tmp_path / "kept"))
    assert got["skipped"] == {1: sa.NOT_APPLIED} and got["id"] is None
    assert "sl-old.mp3" in anki.media and anki.value(1, "Sentence") == _sentences()[3]


def test_a_write_killed_half_way_leaves_its_record_and_its_undo_still_works(tmp_path, ledger):
    """Anki stopped answering at the fields: the record (written first) is left `writing`, and its Undo puts back what
    was read — here nothing changed in Anki, so the fields hold the old values already: nothing written, the record
    closed (FS-1 G: a note holding its old values counts as put back — an Undo or a retry finishes, never refused)."""
    anki = Anki()
    _card(anki, 1, _sentences()[3])
    anki.fail_on_update = 1
    new = {"Sentence": _sentences()[7]}
    with pytest.raises(RuntimeError) as e:
        sa.replace(anki, ledger, 1, new, _was(anki, 1, new), keep_dir=str(tmp_path / "kept"))
    assert sa.pending(ledger) == [e.value.sentence_audio_id]
    anki.fail_on_update = None
    updates = len([c for c in anki.log if c[0] == "update"]) if hasattr(anki, "log") else None
    got = sa.undo(anki, ledger, e.value.sentence_audio_id)
    assert (got["emptied"], got["kept"]) == ([1], {})
    assert sa.record(ledger, e.value.sentence_audio_id)["state"] == sa.UNDONE and sa.pending(ledger) == []
    assert anki.value(1, "Sentence") == _sentences()[3]
    if updates is not None:
        assert len([c for c in anki.log if c[0] == "update"]) == updates         # nothing written to put it back


def test_a_tag_the_learner_had_already_stays_after_undo(tmp_path, ledger):
    anki = Anki()
    _card(anki, 1, _sentences()[3])
    anki.notes_[1]["tags"].append("Surasura::swapped")                  # Anki keeps a tag's first case
    new = {"Sentence": _sentences()[7]}
    got = sa.replace(anki, ledger, 1, new, _was(anki, 1, new), tag="surasura::swapped")
    sa.undo(anki, ledger, got["id"])
    assert "Surasura::swapped" in anki.notes_[1]["tags"]


def test_replace_never_runs_while_you_review_and_needs_each_old_value(tmp_path, ledger):
    anki = Anki()
    _card(anki, 1, _sentences()[3])
    with pytest.raises(ValueError):
        sa.replace(anki, ledger, 1, {"Sentence": "x"}, {})
    anki.reviewing_ = True
    with pytest.raises(sa.Reviewing):
        sa.replace(anki, ledger, 1, {"Sentence": _sentences()[7]}, {"Sentence": _sentences()[3]})
    assert anki.value(1, "Sentence") == _sentences()[3]
