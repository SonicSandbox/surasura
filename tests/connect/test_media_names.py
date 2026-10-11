"""Media named by the line (P2.4 Part B, row B4): one audio and one picture per subtitle line, shared by its words.

Anki Miner names each card's clip and picture by its word, so three words cut from one line would upload three
audio files and three pictures. `media_names.rename` gives the line one `sl-<16 hex>` name per file, points every
note of the line at it, and deletes the old names. What a wrong answer costs: a split line bloats the learner's
Anki collection and uploads the same clip again; two episodes sharing one name would play the wrong episode's clip
on a card, which is worse than a duplicate.

The fake media is a plain in-memory adapter with the methods `rename` calls. Nothing under test is patched.
"""
import contextlib
import re

from app.connect import media_names

LINE_START = 83.52          # seconds; the line cut from the episode (83520 ms)
LINE_END = 86.1
LINE_TEXT = "上層部の話をする"
SL_AUDIO = re.compile(r"sl-[0-9a-f]{16}\.mp3")
SL_PICTURE = re.compile(r"sl-[0-9a-f]{16}\.jpg")


class FakeMedia:
    """Anki's media store and note fields, in memory: exactly the calls media_names.rename makes."""

    def __init__(self, notes, files):
        self.note_map = {n["noteId"]: n for n in notes}
        self.files = dict(files)
        self.stored = []
        self.reads = []
        self.points = []
        self.deleted = []

    def notes(self, ids):
        return [self.note_map[i] for i in ids if i in self.note_map]

    def exists(self, name):
        return name in self.files

    def read(self, name):
        self.reads.append(name)
        return self.files.get(name)

    def store(self, name, data):
        self.stored.append(name)
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


def card_note(note_id, audio, picture):
    """A note the batch made, its audio and picture named by the word (the Anki Miner pattern)."""
    return {"noteId": note_id, "fields": {
        "SentenceAudio": {"value": f"[sound:{audio}]"},
        "Picture": {"value": f'<img src="{picture}">'},
    }}


def word_cut_media(key_suffix="1a2b"):
    """Three words cut from one line: 上層, 部, 上層部 — three audio files and three pictures on disk."""
    notes = [
        card_note(1, f"上層_83520_4_{key_suffix}.mp3", f"上層_83520_4_{key_suffix}.jpg"),
        card_note(2, "部_83520_4_3c4d.mp3", "部_83520_4_3c4d.jpg"),
        card_note(3, "上層部_83520_4_5e6f.mp3", "上層部_83520_4_5e6f.jpg"),
    ]
    files = {}
    for n in notes:
        for field in ("SentenceAudio", "Picture"):
            value = n["fields"][field]["value"]
            name = re.search(r'\[sound:([^\]]+)\]|src="([^"]+)"', value)
            old = name.group(1) or name.group(2)
            files[old] = f"bytes-of-{old}".encode("utf-8")
    return notes, files


def line_made(*note_ids):
    """The batch's `made` list: every note cut from the same line (same start, end and text)."""
    return [(i, LINE_START, LINE_END, LINE_TEXT) for i in note_ids]


def test_three_words_from_one_line_share_one_audio_and_one_picture():
    """Three notes cut from ONE line end up on one audio and one picture: one upload each, every note pointed at it.
    Why it matters: three per-word copies of one clip would triple the upload and the collection's media."""
    notes, files = word_cut_media()
    media = FakeMedia(notes, files)

    out = media_names.rename(media, line_made(1, 2, 3), "ep-kimetsu-03", "SentenceAudio", "Picture")

    audio = {n["fields"]["SentenceAudio"]["value"] for n in media.note_map.values()}
    picture = {n["fields"]["Picture"]["value"] for n in media.note_map.values()}
    assert len(audio) == 1 and len(picture) == 1, "all three notes must point at one audio and one picture"
    new_audio = audio.pop()[len("[sound:"):-1]
    new_picture = re.search(r'src="([^"]+)"', picture.pop()).group(1)
    assert SL_AUDIO.fullmatch(new_audio) and SL_PICTURE.fullmatch(new_picture), "the names are sl-<16 hex>.<ext>"
    assert out["stored"] == 2, "one audio file and one picture uploaded, not one per word"
    assert len(media.reads) == 2, "the first word's files are read; the other two words reuse the same new names"
    assert media.files[new_audio] == "bytes-of-上層_83520_4_1a2b.mp3".encode("utf-8"), \
        "the first word's clip is the one stored"
    assert all(old not in media.files for old in ("上層_83520_4_1a2b.mp3", "部_83520_4_3c4d.mp3",
                                                  "上層部_83520_4_5e6f.mp3")), "the old per-word names are deleted"


def test_same_line_in_two_episodes_gets_two_different_names():
    """The same line text at the same times in two episodes gets two names, one per episode (the episode's key is
    in the hash). Why it matters: a shared name would let one episode's card play the other episode's clip."""
    media = FakeMedia([card_note(1, "上層部_83520_4_1a2b.mp3", "上層部_83520_4_1a2b.jpg"),
                       card_note(2, "上層部_83520_4_7c8d.mp3", "上層部_83520_4_7c8d.jpg")],
                      {"上層部_83520_4_1a2b.mp3": b"episode-3-clip", "上層部_83520_4_7c8d.mp3": b"episode-7-clip",
                       "上層部_83520_4_1a2b.jpg": b"ep3", "上層部_83520_4_7c8d.jpg": b"ep7"})

    media_names.rename(media, line_made(1), "ep-kimetsu-03", "SentenceAudio", "Picture")
    media_names.rename(media, [(2, LINE_START, LINE_END, LINE_TEXT)], "ep-kimetsu-07", "SentenceAudio", "Picture")

    first = media.note_map[1]["fields"]["SentenceAudio"]["value"]
    second = media.note_map[2]["fields"]["SentenceAudio"]["value"]
    assert first != second, "the same line in two episodes must not share an audio name"
    assert media.files[first[len("[sound:"):-1]] == b"episode-3-clip"
    assert media.files[second[len("[sound:"):-1]] == b"episode-7-clip"


def test_name_already_in_anki_is_reused_without_uploading_again():
    """A card made again for a line whose file is already in Anki points at that file: nothing is read or stored.
    Why it matters: the shelf's swap back and a re-made card would otherwise upload the same clip every time."""
    media = FakeMedia([card_note(1, "上層部_83520_4_1a2b.mp3", "上層部_83520_4_1a2b.jpg")],
                      {"上層部_83520_4_1a2b.mp3": b"clip", "上層部_83520_4_1a2b.jpg": b"pic"})
    media_names.rename(media, line_made(1), "ep-kimetsu-03", "SentenceAudio", "Picture")
    stored_before = list(media.stored)
    reads_before = list(media.reads)

    media.note_map[2] = card_note(2, "上層部_83520_4_9e0f.mp3", "上層部_83520_4_9e0f.jpg")
    media.files["上層部_83520_4_9e0f.mp3"] = b"clip"
    media.files["上層部_83520_4_9e0f.jpg"] = b"pic"
    out = media_names.rename(media, line_made(2), "ep-kimetsu-03", "SentenceAudio", "Picture")

    assert out["reused"] == 2 and out["stored"] == 0, "both names are already in Anki: reused, not uploaded"
    assert media.stored == stored_before, "nothing new was stored"
    assert media.reads == reads_before, "the second card's own files were never read back"
    audio = media.note_map[1]["fields"]["SentenceAudio"]["value"]
    assert media.note_map[2]["fields"]["SentenceAudio"]["value"] == audio


def test_a_second_run_after_it_finished_changes_nothing():
    """Once the notes point at `sl-` names, running the rename again leaves them alone: no point, no store, no delete.
    Why it matters: the rename runs after every batch, so a repeat must never rewrite or re-upload a finished line."""
    notes, files = word_cut_media()
    media = FakeMedia(notes, files)
    media_names.rename(media, line_made(1, 2, 3), "ep-kimetsu-03", "SentenceAudio", "Picture")
    points_before, stored_before, deleted_before = list(media.points), list(media.stored), list(media.deleted)

    out = media_names.rename(media, line_made(1, 2, 3), "ep-kimetsu-03", "SentenceAudio", "Picture")

    assert out["renamed"] == 0 and out["stored"] == 0, "a finished line has nothing more to do"
    assert media.points == points_before and media.stored == stored_before and media.deleted == deleted_before


def test_every_anki_write_of_a_rename_happens_while_the_media_writer_is_held():
    """rename takes the media writer once, before its first read, and makes every store, point and delete inside it.
    Why it matters: a write outside the writer can interleave with another Anki writer and corrupt a clip or a note."""
    class LockedMedia(FakeMedia):
        def __init__(self, notes, files):
            super().__init__(notes, files)
            self.held = False
            self.verbs = []

        @contextlib.contextmanager
        def _hold(self, verb):
            self.verbs.append(verb)
            self.held = True
            try:
                yield
            finally:
                self.held = False

        def writer(self, verb):
            return self._hold(verb)

        def store(self, name, data):
            assert self.held, "a store ran outside the media writer"
            super().store(name, data)

        def point(self, note_id, fields):
            assert self.held, "a point ran outside the media writer"
            super().point(note_id, fields)

        def delete(self, name):
            assert self.held, "a delete ran outside the media writer"
            super().delete(name)

    media = LockedMedia(*word_cut_media())
    media_names.rename(media, line_made(1, 2, 3), "ep-kimetsu-03", "SentenceAudio", "Picture")

    assert media.verbs == ["Connect's media names"], "the writer is taken once, for the whole rename"
    assert len(media.stored) == 2 and len(media.points) == 3 and len(media.deleted) == 6, \
        "the guarded writes all ran, so the asserts above were tested"
    assert media.held is False, "the writer is released when the rename returns"


def test_the_anki_media_adapter_waits_ten_seconds_for_the_writer(monkeypatch):
    """AnkiConnectMedia takes Anki's write lock with a 10 s wait, so a busy Anki is waited for, not raced.
    Why it matters: with no wait a rename that meets a running Anki write fails at once and leaves half its names."""
    from app import anki_connect

    calls = []
    monkeypatch.setattr(anki_connect, "writer",
                        lambda verb, wait=0.0, **kw: (calls.append((verb, wait)), contextlib.nullcontext())[1])

    with media_names.AnkiConnectMedia("http://127.0.0.1:8765").writer("Connect's media names"):
        pass

    assert calls == [("Connect's media names", 10.0)], "the adapter asks the writer for a 10 s wait"


def test_an_old_file_that_reads_back_empty_leaves_the_note_as_it_is():
    """When the old file reads back empty or False (AnkiConnect's answer for a missing file), the note is left alone:
    nothing is stored, pointed or deleted. Why it matters: storing an empty file would give the card a silent clip,
    and pointing the note at it would lose the clip the learner still has under its old name."""
    for empty in (b"", False):
        notes, files = word_cut_media()
        notes = notes[:1]
        files["上層_83520_4_1a2b.mp3"] = empty
        files["上層_83520_4_1a2b.jpg"] = empty
        media = FakeMedia(notes, files)
        audio_before = media.note_map[1]["fields"]["SentenceAudio"]["value"]

        out = media_names.rename(media, line_made(1), "ep-kimetsu-03", "SentenceAudio", "Picture")

        assert out["stored"] == 0 and out["renamed"] == 0, f"an unreadable old file ({empty!r}) is not renamed"
        assert media.stored == [] and media.points == [] and media.deleted == [], "nothing stored, pointed or deleted"
        assert media.note_map[1]["fields"]["SentenceAudio"]["value"] == audio_before
