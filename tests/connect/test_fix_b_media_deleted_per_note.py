"""A rename that stops part-way still deletes the old files of each note it pointed (P2.4 Part B, adversary B #15;
LF-mining row 25).

`rename` points the batch's notes, then deletes the pointed notes' old names once no note uses them, in the same
call. Since row 25 its writes are one `multi` a kind, so what stops it part-way is one action failing in its slot:
when the second note's point fails, the first note's old files must still be gone, and the second's kept (it still
plays them). Two notes cut from two different lines. What a wrong answer costs: an old audio or picture file left
behind after its note has moved to the new name is a file the learner's library keeps for nothing, and it piles up
every time a rename is cut short; deleting the files of a note that wasn't pointed silences its card.

The fake media is a plain in-memory adapter with the calls `rename` makes; its `many` fails the points named in
`fail`, as AnkiConnect answers one action of a `multi` with an error. Nothing under test is patched.
"""
import contextlib

import pytest

from app import anki_connect
from app.connect import media_names

LINE_A = (83.52, 86.1, "上層部の話をする")       # the first note's line
LINE_B = (120.0, 122.4, "溜め息をつく")          # the second note's line, a different line


class FakeMedia:
    """Anki's media store and note fields, in memory. `fail`: the note ids whose point fails in its `multi` slot.
    `deleted` records each name `delete` was asked to remove."""

    def __init__(self, notes, files, fail=()):
        self.note_map = {n["noteId"]: n for n in notes}
        self.files = dict(files)
        self.fail = set(fail)
        self.points = []
        self.deleted = []

    def many(self, kind, items):
        return [(False, None) if kind == "point" and item[0] in self.fail else (True, getattr(self, kind)(*item))
                for item in items]

    def notes(self, ids):
        return [self.note_map[i] for i in ids if i in self.note_map]

    def exists(self, name):
        return name in self.files

    def read(self, name):
        return self.files.get(name)

    def store(self, name, data):
        self.files[name] = data

    def point(self, note_id, fields):
        self.points.append(note_id)
        for field, value in fields.items():
            self.note_map[note_id]["fields"][field]["value"] = value

    def delete(self, name):
        self.deleted.append(name)
        self.files.pop(name, None)

    def users(self, name):
        return [i for i, n in self.note_map.items()
                if any(name in (f.get("value") or "") for f in n["fields"].values())]

    def reviewing(self):
        return False

    def writer(self, verb):
        return contextlib.nullcontext()


def word_note(note_id, word, start_stamp):
    """A note the batch made, its audio and picture named by the word on the line (the Anki Miner pattern)."""
    audio = f"{word}_{start_stamp}_4_aa11.mp3"
    picture = f"{word}_{start_stamp}_4_aa11.jpg"
    note = {"noteId": note_id, "fields": {
        "SentenceAudio": {"value": f"[sound:{audio}]"},
        "Picture": {"value": f'<img src="{picture}">'},
    }}
    files = {audio: f"bytes-of-{audio}".encode("utf-8"), picture: f"bytes-of-{picture}".encode("utf-8")}
    return note, files


def test_a_rename_cut_short_deletes_the_pointed_notes_old_files_and_keeps_the_others():
    """The second note's point fails: the first note's old audio and picture are deleted before `rename` reports the
    failure, and the second note's old files are not touched. Why it matters: deleting old names only once a whole
    batch succeeded would leave the first note's old files behind whenever one action fails."""
    note_a, files_a = word_note(1, "上層部", "83520")
    note_b, files_b = word_note(2, "溜め息", "120000")
    second_before = note_b["fields"]["SentenceAudio"]["value"]   # copied: the fake edits the note in place
    media = FakeMedia([note_a, note_b], {**files_a, **files_b}, fail={2})
    made = [(1, *LINE_A), (2, *LINE_B)]

    with pytest.raises(anki_connect.AnkiError):
        media_names.rename(media, made, "ep-kimetsu-03", "SentenceAudio", "Picture")

    assert media.points == [1], "only the first note is pointed; the second's point failed"
    assert sorted(media.deleted) == sorted(files_a), "the first note's old audio and picture are deleted at once"
    assert all(name not in media.files for name in files_a), "no old file of the pointed note is left behind"
    assert media.note_map[2]["fields"]["SentenceAudio"]["value"] == second_before, \
        "the second note keeps its own audio name"
    assert all(name in media.files for name in files_b), "the second note's old files are still there"
