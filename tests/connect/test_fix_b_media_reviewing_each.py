"""Media rename asks whether you're reviewing before it writes (P2.4 Part B, review fix H10; LF-mining row 25).

Before row 25 the rename asked before each note's writes. It now sends its writes as one `multi` a kind (three
requests under Anki's write lock), so it asks after its reads, before the batch's first store, and again before its
first point (PROVISIONAL; IK-r2-4). Review already started -> nothing is stored, pointed or deleted; started during
the stores -> no note is pointed; either way the job resumes on the next look. Two notes cut
from two different lines. What a wrong answer costs: a note pointed while the learner is reviewing changes a card under
their eyes, and a rename that never asked would point notes the learner never agreed to change.

The fake media is a plain in-memory adapter with the calls `rename` makes; its `reviewing()` answers from a list, so
the test controls exactly when review starts, and `events` records the order of the asks and the writes. Nothing
under test is patched.
"""
import contextlib

import pytest

from app.connect import media_names
from tests.connect.test_media_names import fake_many

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
        self.events = []

    def many(self, kind, items):
        return fake_many(self, kind, items)

    def notes(self, ids):
        return [self.note_map[i] for i in ids if i in self.note_map]

    def exists(self, name):
        return name in self.files

    def read(self, name):
        return self.files.get(name)

    def store(self, name, data):
        self.events.append("store")
        self.files[name] = data

    def point(self, note_id, fields):
        self.events.append("point")
        self.points.append(note_id)
        for field, value in fields.items():
            self.note_map[note_id]["fields"][field]["value"] = value

    def delete(self, name):
        self.events.append("delete")
        self.deleted.append(name)
        self.files.pop(name, None)

    def users(self, name):
        return [i for i, n in self.note_map.items()
                if any(name in (f.get("value") or "") for f in n["fields"].values())]

    def reviewing(self):
        self.events.append("reviewing")
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


def _two_notes(answers):
    note_a, files_a = word_note(1, "上層部", "83520")
    note_b, files_b = word_note(2, "溜め息", "120000")
    return FakeMedia([note_a, note_b], {**files_a, **files_b}, answers), files_a, files_b


def test_review_already_started_writes_nothing():
    """You're reviewing when the batch is ready to write: `rename` raises Reviewing with nothing stored, pointed or
    deleted. Why it matters: a note pointed under review changes a card the learner is looking at."""
    media, files_a, files_b = _two_notes([True])
    before = {i: dict(n["fields"]["SentenceAudio"]) for i, n in media.note_map.items()}

    with pytest.raises(media_names.Reviewing):
        media_names.rename(media, [(1, *LINE_A), (2, *LINE_B)], "ep-kimetsu-03", "SentenceAudio", "Picture")

    assert media.points == [] and media.deleted == [], "nothing pointed, nothing deleted"
    assert "store" not in media.events, "nothing stored"
    assert {i: n["fields"]["SentenceAudio"] for i, n in media.note_map.items()} == before
    assert all(name in media.files for name in {**files_a, **files_b}), "every old file is still there"


def test_review_is_asked_before_the_stores_and_again_before_the_points():
    """Anki free when asked: the stores follow the first ask, the points and deletes the second — never one ask per
    note (PROVISIONAL row 25; IK-r2-4: "checked before each Surasura write", P2.4-7). Why it matters: the ask must come
    before any write; asking again per note is what cost a request a note."""
    media, files_a, files_b = _two_notes([False])

    media_names.rename(media, [(1, *LINE_A), (2, *LINE_B)], "ep-kimetsu-03", "SentenceAudio", "Picture")

    assert media.events == ["reviewing"] + ["store"] * 4 + ["reviewing"] + ["point"] * 2 + ["delete"] * 4, media.events
    assert media.points == [1, 2], "both notes pointed in the one batch"
    assert sorted(media.deleted) == sorted({**files_a, **files_b}), "each pointed note's old names go"


def test_a_review_started_after_the_stores_points_no_note():
    """You start reviewing while the new files are stored: `rename` raises Reviewing before any note is pointed, and
    the next look finishes it with the names already in Anki (IK-r2-4). Why it matters: a card changed under the
    learner's eyes; the stored files cost nothing — the next rename reuses them."""
    media, files_a, files_b = _two_notes([False, True])

    with pytest.raises(media_names.Reviewing):
        media_names.rename(media, [(1, *LINE_A), (2, *LINE_B)], "ep-kimetsu-03", "SentenceAudio", "Picture")
    assert media.points == [] and media.deleted == [], "nothing pointed, nothing deleted"
    assert media.events.count("store") == 4

    media.answers = [False]
    out = media_names.rename(media, [(1, *LINE_A), (2, *LINE_B)], "ep-kimetsu-03", "SentenceAudio", "Picture")
    assert out["renamed"] == 2 and out["reused"] == 4 and out["stored"] == 0, out
    assert sorted(media.deleted) == sorted({**files_a, **files_b})
