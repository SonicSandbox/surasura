"""LF-mining row 25, fix 2: the media rename sent as one AnkiConnect `multi` a kind of request, not ~11 requests a note.

`media_names.rename` used to ask Anki one thing at a time: 271 requests for one episode's 24 notes (storeMediaFile,
deleteMediaFile, findNotes, retrieveMediaFile, getMediaFilesNames, updateNoteFields, guiReviewActive), 14.8 s here.
Now each kind goes as one `multi` (the adapter's `many`): about 8 requests for the same 24 notes, and every rule it
had holds — one file a line, a name already in Anki reused, a file another note uses never deleted, the writer held
throughout, never a write while you review (asked once, before the batch's first write).

A `multi` answers each action on its own, so one can fail while the rest succeed. Then only that action's notes are
left as they were (a note is never pointed at a file that wasn't stored; an old file whose search failed is never
deleted), the rest of the batch is done, and the rename still raises AnkiError, as a failed request did before: the
job waits and the next look finishes the note that was left.

What a wrong answer would cost: a card pointed at a clip that isn't in Anki (silent card), a clip another card plays
deleted, or ~6 s an episode (~12 s on the laptop) spent on round trips. Two fakes: the in-memory media of
`test_media_names` (taught to fail one action), and a stand-in AnkiConnect behind the real adapter (to count requests).
"""
import base64
import contextlib

import pytest

from app import anki_connect
from app.connect import media_names
from tests.connect.test_media_names import FakeMedia, card_note

KEY = "ep-bocchi-01"
LINES = [  # (start, end, text): an episode's lines, each cut for two words
    (12.4, 14.9, "ライブハウスで演奏する"), (31.0, 33.2, "結束バンドの練習"), (47.5, 50.1, "ギターを弾いてみたい"),
    (62.0, 64.8, "人前で話すのは苦手"), (80.3, 83.0, "押し入れの中で練習"), (95.1, 97.7, "初めてのライブ"),
    (110.0, 112.6, "観客が少なかった"), (125.4, 128.0, "緊張して声が出ない"), (140.2, 142.9, "新しい曲を作ろう"),
    (155.0, 157.5, "歌詞を書いてみた"), (170.8, 173.1, "文化祭で演奏しよう"), (186.0, 188.4, "一緒にバンドをやろう"),
]


class FailingMedia(FakeMedia):
    """`test_media_names`' media, with chosen actions failing in their `multi` slot: `fail` holds (kind, the first
    argument) pairs — ("store", name), ("point", note id), ("users", name) — each failing once."""

    def __init__(self, notes, files, fail=()):
        super().__init__(notes, files)
        self.fail = set(fail)

    def many(self, kind, items):
        out = []
        for item in items:
            if (kind, item[0]) in self.fail:
                self.fail.discard((kind, item[0]))
                out.append((False, None))
            else:
                out.append((True, getattr(self, kind)(*item)))
        return out


def two_lines():
    """Notes 1-2 cut from one line, notes 3-4 from another; each note with its own word-named clip and picture."""
    notes, files, made = [], {}, []
    for n, (line, word) in enumerate([(0, "演奏"), (0, "ライブハウス"), (1, "結束"), (1, "練習")], start=1):
        start, end, text = LINES[line]
        audio, picture = f"{word}_{int(start * 1000)}_{n}_ab12.mp3", f"{word}_{int(start * 1000)}_{n}_ab12.jpg"
        notes.append(card_note(n, audio, picture))
        files[audio], files[picture] = f"clip-{audio}".encode("utf-8"), f"pic-{picture}".encode("utf-8")
        made.append((n, start, end, text))
    return notes, files, made


def _audio(media, note_id):
    return media.note_map[note_id]["fields"]["SentenceAudio"]["value"][len("[sound:"):-1]


def test_a_failed_store_leaves_only_that_lines_notes_and_the_next_rename_finishes_them():
    # why: pointing a note at a file whose store failed would leave the card silent; the other line is done anyway
    notes, files, made = two_lines()
    media = FailingMedia(notes, files)
    new = media_names.line_name(KEY, made[0][1], made[0][2], media_names.fingerprint(made[0][3]), ".mp3")
    media.fail = {("store", new)}
    with pytest.raises(anki_connect.AnkiError):
        media_names.rename(media, made, KEY, "SentenceAudio", "Picture")
    assert _audio(media, 1) == "演奏_12400_1_ab12.mp3" and _audio(media, 2) == "ライブハウス_12400_2_ab12.mp3", \
        "the line whose audio failed keeps its own names"
    assert "演奏_12400_1_ab12.mp3" in media.files and "ライブハウス_12400_2_ab12.mp3" in media.files
    assert _audio(media, 3).startswith("sl-") and _audio(media, 3) == _audio(media, 4), "the other line is renamed"
    assert "結束_31000_3_ab12.mp3" not in media.files, "and its old files are gone"

    out = media_names.rename(media, made, KEY, "SentenceAudio", "Picture")   # the next look
    assert _audio(media, 1) == _audio(media, 2) == new
    assert media.files[new] == "clip-演奏_12400_1_ab12.mp3".encode("utf-8"), "the line's first note's clip"
    assert out["renamed"] == 2 and "演奏_12400_1_ab12.mp3" not in media.files


def test_a_failed_point_keeps_that_notes_old_files_and_deletes_the_others():
    # why: a note whose point failed still plays its old files — deleting them would silence it
    notes, files, made = two_lines()
    media = FailingMedia(notes, files, fail={("point", 3)})
    with pytest.raises(anki_connect.AnkiError):
        media_names.rename(media, made, KEY, "SentenceAudio", "Picture")
    assert _audio(media, 3) == "結束_31000_3_ab12.mp3" and "結束_31000_3_ab12.mp3" in media.files
    assert all(_audio(media, n).startswith("sl-") for n in (1, 2, 4))
    assert "練習_31000_4_ab12.mp3" not in media.files and "演奏_12400_1_ab12.mp3" not in media.files


def test_a_failed_search_for_a_files_users_never_deletes_it():
    # why (review B #11, batched): no answer to "who uses this file?" is never read as "no one"
    notes, files, made = two_lines()
    media = FailingMedia(notes, files, fail={("users", "練習_31000_4_ab12.jpg")})
    with pytest.raises(anki_connect.AnkiError):
        media_names.rename(media, made, KEY, "SentenceAudio", "Picture")
    assert "練習_31000_4_ab12.jpg" in media.files, "kept: its users weren't known"
    assert all(_audio(media, n).startswith("sl-") for n in (1, 2, 3, 4)), "every note was still pointed"


# --- the real adapter against a stand-in AnkiConnect: how many requests -------------------------------------------- #
class StandInAnki:
    """AnkiConnect's answers to what the rename sends (notesInfo, guiReviewActive, multi of six media/note actions),
    over in-memory notes and media; `requests` counts the HTTP requests, `failing` names (action, filename) slots that
    answer an error."""

    def __init__(self, notes, files):
        self.notes = {n["noteId"]: n for n in notes}
        self.files = {name: base64.b64encode(data).decode("ascii") for name, data in files.items()}
        self.requests = []
        self.failing = set()

    def invoke(self, action, url, timeout=30, **params):
        self.requests.append(action)
        if action == "notesInfo":
            return [self.notes[i] for i in params["notes"] if i in self.notes]
        if action == "guiReviewActive":
            return False
        assert action == "multi", action
        return [self._one(a["action"], a["params"]) for a in params["actions"]]

    def _one(self, action, p):
        name = p.get("filename")
        if (action, name) in self.failing:
            return {"result": None, "error": f"{action} failed"}
        if action == "getMediaFilesNames":
            return {"result": [p["pattern"]] if p["pattern"] in self.files else [], "error": None}
        if action == "retrieveMediaFile":
            return {"result": self.files.get(name, False), "error": None}
        if action == "storeMediaFile":
            self.files[name] = p["data"]
            return {"result": name, "error": None}
        if action == "updateNoteFields":
            for field, value in p["note"]["fields"].items():
                self.notes[p["note"]["id"]]["fields"][field]["value"] = value
            return {"result": None, "error": None}
        if action == "findNotes":
            wanted = p["query"].strip('"')
            return {"result": [i for i, n in self.notes.items()
                               if any(wanted in f["value"] for f in n["fields"].values())], "error": None}
        if action == "deleteMediaFile":
            self.files.pop(name, None)
            return {"result": None, "error": None}
        raise AssertionError(action)


def episode_of_24_notes():
    notes, files, made = [], {}, []
    for n in range(24):
        start, end, text = LINES[n // 2]
        audio, picture = f"語{n}_{int(start * 1000)}_{n}_cd34.mp3", f"語{n}_{int(start * 1000)}_{n}_cd34.jpg"
        notes.append(card_note(1000 + n, audio, picture))
        files[audio], files[picture] = f"clip {n}".encode("utf-8"), f"picture {n}".encode("utf-8")
        made.append((1000 + n, start, end, text))
    return notes, files, made


@pytest.fixture
def anki(monkeypatch):
    def stand_in(notes, files):
        fake = StandInAnki(notes, files)
        monkeypatch.setattr(anki_connect, "invoke", fake.invoke)
        monkeypatch.setattr(anki_connect, "writer", lambda verb, wait=0.0, **kw: contextlib.nullcontext())
        return fake
    return stand_in


def test_an_episodes_24_notes_are_renamed_in_at_most_ten_requests(anki):
    # why: 271 requests took 14.8 s for this many notes; one multi a kind took 8.5 s in the prototype
    notes, files, made = episode_of_24_notes()
    fake = anki(notes, files)
    out = media_names.rename(media_names.AnkiConnectMedia("http://127.0.0.1:8765"), made, KEY, "SentenceAudio",
                             "Picture")
    assert out == {"renamed": 24, "stored": 24, "reused": 0, "deleted": 48}, out
    assert len(fake.requests) <= 10, fake.requests
    assert fake.requests.count("guiReviewActive") == 1, "asked once, before the first write"
    names = {n["fields"]["SentenceAudio"]["value"] for n in fake.notes.values()}
    assert len(names) == 12, "one audio a line"
    assert sorted(fake.files) == sorted({m for n in fake.notes.values() for m in (
        n["fields"]["SentenceAudio"]["value"][len("[sound:"):-1],
        n["fields"]["Picture"]["value"].split('"')[1])}), "every file left is one a note plays"


def test_one_failed_slot_in_a_real_multi_reply_leaves_its_note_and_raises(anki):
    # why: AnkiConnect's multi answers {"result": null, "error": "..."} for one action and goes on with the rest;
    # the adapter reads that slot as failed, never as an answer
    notes, files, made = episode_of_24_notes()
    fake = anki(notes, files)
    fake.failing = {("retrieveMediaFile", "語0_12400_0_cd34.mp3")}
    with pytest.raises(anki_connect.AnkiError):
        media_names.rename(media_names.AnkiConnectMedia("http://127.0.0.1:8765"), made, KEY, "SentenceAudio",
                           "Picture")
    first_line = [fake.notes[i]["fields"]["SentenceAudio"]["value"] for i in (1000, 1001)]
    assert first_line == ["[sound:語0_12400_0_cd34.mp3]", "[sound:語1_12400_1_cd34.mp3]"], "its line's audio is left"
    assert "語0_12400_0_cd34.mp3" in fake.files and "語1_12400_1_cd34.mp3" in fake.files
    assert fake.notes[1000]["fields"]["Picture"]["value"].startswith('<img src="sl-'), "its picture is renamed"
    assert all(fake.notes[1000 + n]["fields"]["SentenceAudio"]["value"].startswith("[sound:sl-") for n in range(2, 24))


def test_users_slot_that_isnt_a_list_counts_as_failed():
    # why (review B #11): a findNotes answer that isn't a list means no search happened — never "no one uses it"
    media = media_names.AnkiConnectMedia("http://127.0.0.1:8765")
    replies = [{"result": [5], "error": None}, {"result": None, "error": None}, {"result": {}, "error": None},
               {"result": None, "error": "boom"}]
    assert media._read("users", [("a",), ("b",), ("c",), ("d",)], replies) == [
        (True, [5]), (False, None), (False, None), (False, None)]
