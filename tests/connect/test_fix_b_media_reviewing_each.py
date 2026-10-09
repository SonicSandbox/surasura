"""Media rename asks before each note's writes (P2.4 Part B, review fix H10).

When the learner starts reviewing in the middle of a rename, the rename must stop before it points the next note,
not after it has already written to the second note. Two notes cut from two different lines: the first is pointed
while Anki is free, then review starts, and the second must be left exactly as it was. What a wrong answer costs: a
note pointed while the learner is reviewing changes a card under their eyes, and a rename that ran on past the
question would point notes the learner never agreed to change.

The fake media is a plain in-memory adapter with the calls `rename` makes; its `reviewing()` answers from a list, so
the test controls exactly when review starts. Nothing under test is patched.
"""
import contextlib

import pytest

from app.connect import media_names

LINE_A = (83.52, 86.1, "上層部の話をする")       # the first note's line
LINE_B = (120.0, 122.4, "溜め息をつく")          # the second note's line, a different line


class FakeMedia:
    """Anki's media store and note fields, in memory. `answers` is what `reviewing()` returns, call by call;
    once it runs out, the last answer repeats."""

    def __init__(self, notes, files, answers):
        self.note_map = {n["noteId"]: n for n in notes}
        self.files = dict(files)
        self.answers = list(answers)
        self.points = []
        self.deleted = []

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
        if len(self.answers) > 1:
            return self.answers.pop(0)
        return self.answers[0]

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


def test_review_starting_between_two_notes_stops_before_the_second_is_pointed():
    """Review starts after the first note is pointed: `rename` raises Reviewing before it points the second note,
    and deletes only the first note's old names (each note's right after it is pointed: an interrupted rename leaves
    no old file behind, adversary B #15). Why it matters: a note pointed under review changes a card the learner is
    looking at."""
    note_a, files_a = word_note(1, "上層部", "83520")
    note_b, files_b = word_note(2, "溜め息", "120000")
    files = {**files_a, **files_b}
    second_before = note_b["fields"]["SentenceAudio"]["value"]   # copied: the fake edits the note in place
    # Before note 1: free. Before note 2: review has started.
    media = FakeMedia([note_a, note_b], files, answers=[False, True])
    made = [(1, *LINE_A), (2, *LINE_B)]

    with pytest.raises(media_names.Reviewing):
        media_names.rename(media, made, "ep-kimetsu-03", "SentenceAudio", "Picture")

    assert media.points == [1], "only the first note is pointed; review stops the rename before the second"
    assert media.note_map[2]["fields"]["SentenceAudio"]["value"] == second_before, \
        "the second note keeps its own audio name"
    assert sorted(media.deleted) == sorted(files_a), "the pointed note's old names go now, never the second's"
    assert all(name in media.files for name in files_b), "the second note's old files are still there"
