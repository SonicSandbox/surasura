"""Audiobooks and the book each reads aloud (Hon, 3.0 E2; scope `tracks/books/work/audiobooks/scope.md`). The rules are
PROVISIONAL: these scenarios hold them — every naming style an audiobook arrives in (`01.mp3`…, `Track 01`, disc
folders, a `.m4b` with chapters), the same title in two folders, two editions, a volume that differs, a sample too short
to be one, a show's soundtrack beside its videos, and the one remembered question.

The audio files are small but real to the readers: an ID3v2 tag and an MPEG frame whose Xing header gives the length,
or an MP4's atoms (`mvhd`, `ilst`, Nero's `chpl`). The titles are real Japanese books.
"""
import os
import struct
import zipfile

import pytest

from app import audiobooks as ab

NEKO, BOCCHAN, GINGA = "吾輩は猫である", "坊っちゃん", "銀河鉄道の夜"


# --- builders ------------------------------------------------------------------------------------------------------ #
def _syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def _id3(frames, version=3, pad=64):
    body = b""
    for fid, text in frames.items():
        if version == 2:
            data = b"\x01" + text.encode("utf-16")
            body += fid.encode() + len(data).to_bytes(3, "big") + data
        elif version == 4:
            data = b"\x03" + text.encode("utf-8")
            body += fid.encode() + _syncsafe(len(data)) + b"\0\0" + data
        else:
            data = b"\x01" + text.encode("utf-16")             # UTF-16 with its BOM, as most taggers write v2.3
            body += fid.encode() + struct.pack(">I", len(data)) + b"\0\0" + data
    body += b"\0" * pad
    return b"ID3" + bytes([version, 0, 0]) + _syncsafe(len(body)) + body


def _mp3(path, seconds=None, frames=None, version=3, cbr_bytes=0, pad=64):
    """An MP3: its tag, then one MPEG-1 layer III frame (128 kbps, 44.1 kHz, stereo) carrying a Xing header with the
    frame count for `seconds` — or none (`seconds` None: a CBR file of `cbr_bytes` after its tag)."""
    head = b"\xff\xfb\x90\x00"
    if seconds is not None:
        count = int(round(seconds * 44100 / 1152))
        audio = head + b"\0" * 32 + b"Xing" + struct.pack(">II", 1, count) + b"\0" * 300
    else:
        audio = (head + b"\0" * 413) * max(1, cbr_bytes // 417)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(_id3(frames or {}, version, pad) + audio)
    return path


def _atom(kind, payload):
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def _text(text):
    return _atom(b"data", struct.pack(">II", 1, 0) + text.encode("utf-8"))


def _m4b(path, seconds, tags=None, chapters=None, track=None):
    """An M4B whose `moov` comes after its `mdat` (read by seeking past it): its length (`mvhd`), its tags (`ilst`) and
    Nero chapters [(title, start seconds)]."""
    mvhd = _atom(b"mvhd", b"\0\0\0\0" + struct.pack(">IIII", 0, 0, 1000, int(seconds * 1000)) + b"\0" * 80)
    ids = {"title": b"\xa9nam", "album": b"\xa9alb", "artist": b"\xa9ART", "album_artist": b"aART"}
    ilst = b"".join(_atom(ids[k], _text(v)) for k, v in (tags or {}).items())
    if track is not None:
        ilst += _atom(b"trkn", _atom(b"data", struct.pack(">II", 0, 0) + struct.pack(">HHHH", 0, track, 0, 0)))
    udta = _atom(b"meta", b"\0\0\0\0" + _atom(b"ilst", ilst))
    if chapters:
        body = b"\x01\0\0\0" + b"\0\0\0\0" + bytes([len(chapters)])
        for title, start in chapters:
            raw = title.encode("utf-8")
            body += struct.pack(">Q", int(start * 10_000_000)) + bytes([len(raw)]) + raw
        udta = _atom(b"chpl", body) + udta
    moov = _atom(b"moov", mvhd + _atom(b"udta", udta))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(_atom(b"ftyp", b"M4B \0\0\0\0M4B mp42") + _atom(b"mdat", b"\0" * 4096) + moov)
    return path


def _epub(path, title, creator=None):
    meta = f"<dc:title>{title}</dc:title>" + (f"<dc:creator>{creator}</dc:creator>" if creator else "")
    opf = (f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">{meta}</metadata><manifest/><spine/></package>')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                   'version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
    return path


def _chapters(folder, names, minutes=30, tags=None):
    for i, name in enumerate(names):
        _mp3(os.path.join(folder, name), seconds=minutes * 60, frames=(tags or (lambda i: {}))(i))


def _book(path, title, creator=None, chars=None, sha="sha-" + NEKO):
    return ab.book_of(_epub(path, title, creator), book_id=path, chars=chars, sha256=sha)


# --- the readers --------------------------------------------------------------------------------------------------- #
def test_id3_v23_utf16_tags_and_xing_length(tmp_path):
    """The common tagger's shape: v2.3, UTF-16 with a BOM; the length from the Xing frame count, never the bytes."""
    p = _mp3(str(tmp_path / "01.mp3"), seconds=1800, frames={"TIT2": "第一章", "TALB": NEKO, "TPE1": "朗読 山田",
                                                              "TPE2": "夏目漱石", "TRCK": "1/11", "TPOS": "1/2"})
    t = ab.read_tags(p)
    assert (t.title, t.album, t.artist, t.album_artist, t.track, t.disc) == ("第一章", NEKO, "朗読 山田", "夏目漱石", 1, 1)
    assert t.seconds == pytest.approx(1800, abs=0.1)


def test_id3_v24_and_v22_frames_are_read(tmp_path):
    v4 = ab.read_tags(_mp3(str(tmp_path / "a.mp3"), seconds=60, frames={"TALB": BOCCHAN, "TRCK": "07"}, version=4))
    v2 = ab.read_tags(_mp3(str(tmp_path / "b.mp3"), seconds=60, frames={"TAL": GINGA, "TRK": "3"}, version=2))
    assert (v4.album, v4.track) == (BOCCHAN, 7)
    assert (v2.album, v2.track) == (GINGA, 3)


def test_a_tag_bigger_than_the_head_read_still_finds_the_frame_after_it(tmp_path):
    """A cover picture in the tag pushes the first frame past the first read: the frame (and its length) is found."""
    p = _mp3(str(tmp_path / "cover.mp3"), seconds=1500, frames={"TALB": NEKO}, pad=ab.HEAD_BYTES + 5000)
    t = ab.read_tags(p)
    assert t.album == NEKO and t.seconds == pytest.approx(1500, abs=0.1)


def test_a_cbr_mp3_without_xing_is_timed_by_its_bytes(tmp_path):
    p = _mp3(str(tmp_path / "cbr.mp3"), seconds=None, cbr_bytes=160_000)
    assert ab.read_tags(p).seconds == pytest.approx(160_000 * 8 / 128_000, rel=0.02)


def test_m4b_tags_length_and_chapters_with_moov_after_mdat(tmp_path):
    p = _m4b(str(tmp_path / f"{NEKO}.m4b"), 7200, {"title": NEKO, "album": NEKO, "artist": "朗読 山田"},
             chapters=[("一", 0), ("二", 1500.5), ("三", 4000)])
    t = ab.read_tags(p)
    assert (t.title, t.album, t.artist, t.seconds) == (NEKO, NEKO, "朗読 山田", 7200)
    assert t.chapters == [{"title": "一", "start_ms": 0, "end_ms": 1500500},
                          {"title": "二", "start_ms": 1500500, "end_ms": 4000000},
                          {"title": "三", "start_ms": 4000000, "end_ms": 7200000}]


@pytest.mark.parametrize("payload", [b"", b"ID3", b"ID3\x03\0\0\x7f\x7f\x7f\x7f", b"\xff" * 50, b"not audio at all"])
def test_a_file_that_cannot_be_read_has_no_tags_never_an_error(tmp_path, payload):
    for name in ("x.mp3", "x.m4b", "x.aac", "x.flac"):
        (tmp_path / name).write_bytes(payload)
        assert ab.read_tags(str(tmp_path / name)) == ab.Tags()
    assert ab.read_tags(str(tmp_path / "gone.mp3")) == ab.Tags()


# --- names --------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("name, forms, vol", [
    (f"{NEKO}（上）【オーディオブック】", {NEKO}, "上"),
    (f"{NEKO} 下巻", {NEKO}, "下"),
    ("[Audible] ソードアート・オンライン Vol.3", {"ソードアートオンライン"}, "3"),
    ("ソードアート・オンライン1 アインクラッド 第1巻", {"ソードアートオンライン1アインクラッド"}, "1"),
    (f"夏目漱石 - {NEKO} (朗読) 320kbps", {f"夏目漱石{NEKO}"}, None),
    ("Track 01", set(), None),                                # a track's name names no title, and no volume
    ("86―エイティシックス―", {"86エイティシックス"}, None),   # a title that is a number keeps it
    ("雲の上", {"雲の上"}, None),                              # 上 inside a title is no volume
    ("全3巻セット", {"セット"}, None),                         # 全3巻 is a set, not volume 3
    ("全12巻", set(), None),
    ("ソードアート・オンライン（2）", {"ソードアートオンライン"}, "2"),
    ("ソードアート・オンラインVol.3", {"ソードアートオンライン"}, "3"),
    ("SAO_vol03", {"sao"}, "3"),
    (f"{NEKO}【上】", {NEKO}, "上"),
    ("銀河鉄道の夜 (Disc 1)", {GINGA}, None),                 # a disc is no volume and no part of the title
    ("01", set(), None),
    ("朗読者", {"朗読者"}, None),                              # a title holding 朗読 keeps it
    ("後編集", {"後編集"}, None),
    ("Re:ゼロ (2019)", {"reゼロ"}, None),                       # a year in brackets is no volume
    ("【朗読】銀河鉄道の夜", {GINGA}, None),
])
def test_clean_names_and_volumes(name, forms, vol):
    got, got_vol = ab.clean(name)
    assert got_vol == vol
    assert forms <= got if forms else not got


@pytest.mark.parametrize("name, n", [("Disc 1", 1), ("CD2", 2), ("disk_03", 3), ("ディスク 4", 4), ("DISC 1 of 2", 1),
                                     (f"{NEKO} CD1", 1), ("Discography", None), ("Part 1", None), ("01", None)])
def test_disc_folders(name, n):
    assert ab.disc_number(name) == n


# --- finding one audiobook ----------------------------------------------------------------------------------------- #
def test_numbered_chapter_files_are_one_audiobook_in_number_order(tmp_path):
    """`1.mp3 … 11.mp3`: one audiobook, 2 before 10 (never the names' letter order), the folder its title."""
    folder = tmp_path / NEKO
    _chapters(str(folder), [f"{n}.mp3" for n in (10, 2, 1, 11, 3)])
    (books,) = ab.find(str(folder))
    assert [os.path.basename(p) for p in books.files] == ["1.mp3", "2.mp3", "3.mp3", "10.mp3", "11.mp3"]
    assert books.title == NEKO and books.seconds == pytest.approx(5 * 1800, abs=1)
    starts = [c["start_ms"] for c in books.chapters]      # end to end, to a frame's rounding (26 ms a file)
    assert starts == pytest.approx([0, 1800000, 3600000, 5400000, 7200000], abs=5 * 26)


def test_track_names_and_full_width_numbers_sort_as_numbers(tmp_path):
    folder = tmp_path / BOCCHAN
    _chapters(str(folder), ["Track 10.mp3", "Track 9.mp3", "Track １.mp3"])
    (b,) = ab.find(str(folder))
    assert [os.path.basename(p) for p in b.files] == ["Track １.mp3", "Track 9.mp3", "Track 10.mp3"]


def test_tags_track_order_wins_over_the_names(tmp_path):
    """Files named by their chapter's title: the tags' track numbers order them."""
    folder = tmp_path / NEKO
    names = ["あとがき.mp3", "一.mp3", "二.mp3"]
    tracks = {"あとがき.mp3": "3", "一.mp3": "1", "二.mp3": "2"}
    for n in names:
        _mp3(str(folder / n), seconds=1200, frames={"TALB": NEKO, "TRCK": tracks[n]})
    (b,) = ab.find(str(folder))
    assert [os.path.basename(p) for p in b.files] == ["一.mp3", "二.mp3", "あとがき.mp3"]


def test_a_repeated_track_number_falls_back_to_the_names(tmp_path):
    folder = tmp_path / NEKO
    for n in ("01.mp3", "02.mp3", "03.mp3"):
        _mp3(str(folder / n), seconds=1200, frames={"TRCK": "1"})    # a tagger that numbered nothing
    (b,) = ab.find(str(folder))
    assert [os.path.basename(p) for p in b.files] == ["01.mp3", "02.mp3", "03.mp3"]


def test_disc_folders_join_their_parent_in_disc_order(tmp_path):
    """`Disc 2/01.mp3` comes after `Disc 1/12.mp3`; a disc folder looked at by itself holds no audiobook of its own."""
    folder = tmp_path / GINGA
    _chapters(str(folder / "Disc 2"), ["01.mp3", "02.mp3"], minutes=15)
    _chapters(str(folder / "Disc 1"), ["01.mp3", "12.mp3"], minutes=15)
    (b,) = ab.find(str(folder))
    assert [os.path.relpath(p, folder).replace("\\", "/") for p in b.files] == \
        ["Disc 1/01.mp3", "Disc 1/12.mp3", "Disc 2/01.mp3", "Disc 2/02.mp3"]
    assert ab.find(str(folder / "Disc 1")) == []
    assert len(ab.find(str(folder / "Disc 1"), root=str(folder / "Disc 1"))) == 1   # a source added at the disc


def test_an_m4b_is_its_own_audiobook_with_its_chapters(tmp_path):
    folder = tmp_path / "夏目漱石"
    _m4b(str(folder / f"{NEKO}.m4b"), 3 * 3600, {"title": NEKO}, chapters=[("一", 0), ("二", 2000)])
    _m4b(str(folder / f"{BOCCHAN}.m4b"), 4 * 3600, {"title": BOCCHAN})
    found = ab.find(str(folder))
    assert [b.title for b in found] == [NEKO, BOCCHAN]        # name order (吾 U+543E before 坊 U+574A)
    assert all("夏目漱石" not in b.titles for b in found)      # a folder of several names no one's title
    neko = next(b for b in found if b.title == NEKO)
    assert neko.files == [os.path.abspath(str(folder / f"{NEKO}.m4b"))]
    assert [c["title"] for c in neko.chapters] == ["一", "二"]


def test_a_folder_with_a_video_has_no_audiobook(tmp_path):
    """A show's folder: its OST and commentary are the videos', never an audiobook."""
    folder = tmp_path / "ぼっち・ざ・ろっく！"
    _chapters(str(folder), ["OST 01.mp3", "OST 02.mp3"], minutes=30)
    (folder / "ぼっち・ざ・ろっく！ - 01.mkv").write_bytes(b"\0" * 1024)
    assert ab.find(str(folder)) == []


def test_a_short_sample_is_no_audiobook(tmp_path):
    folder = tmp_path / NEKO
    _mp3(str(folder / "sample.mp3"), seconds=5 * 60)
    assert ab.find(str(folder)) == []


def test_unknown_length_counts_by_size(tmp_path):
    folder = tmp_path / NEKO
    small = folder / "01.flac"
    folder.mkdir()
    small.write_bytes(b"\0" * 1024)
    assert ab.find(str(folder)) == []
    with open(small, "r+b") as f:
        f.truncate(ab.MIN_BYTES)
    (b,) = ab.find(str(folder))
    assert b.seconds is None and b.size == ab.MIN_BYTES and b.chapters is None


def test_two_albums_in_one_folder_are_two_audiobooks(tmp_path):
    folder = tmp_path / "夏目漱石 朗読集"
    for i in (1, 2):
        _mp3(str(folder / f"{NEKO} {i:02}.mp3"), seconds=1500, frames={"TALB": NEKO, "TRCK": str(i)})
        _mp3(str(folder / f"{BOCCHAN} {i:02}.mp3"), seconds=1500, frames={"TALB": BOCCHAN, "TRCK": str(i)})
    found = ab.find(str(folder))
    assert sorted(b.title for b in found) == sorted([NEKO, BOCCHAN])
    assert all(len(b.files) == 2 for b in found)


def test_a_mac_twin_and_a_plain_subfolder_are_not_joined(tmp_path):
    folder = tmp_path / NEKO
    _chapters(str(folder), ["01.mp3", "02.mp3"])
    (folder / "._01.mp3").write_bytes(b"\0\0")
    _chapters(str(folder / "おまけ"), ["01.mp3"])              # not a disc: its own folder, looked at by itself
    (b,) = ab.find(str(folder))
    assert [os.path.basename(p) for p in b.files] == ["01.mp3", "02.mp3"]


def test_an_empty_or_missing_folder_has_none(tmp_path):
    assert ab.find(str(tmp_path)) == []
    assert ab.find(str(tmp_path / "gone")) == []


# --- the book's side ----------------------------------------------------------------------------------------------- #
def test_epub_meta_reads_title_and_creator(tmp_path):
    p = _epub(str(tmp_path / "x.epub"), NEKO, "夏目漱石")
    assert ab.epub_meta(p) == ((NEKO,), ("夏目漱石",))
    (tmp_path / "bad.epub").write_bytes(b"PK broken")
    assert ab.epub_meta(str(tmp_path / "bad.epub")) == ((), ())
    b = ab.book_of(p, book_id=7)
    assert b.titles == (NEKO, "x") and b.authors == ("夏目漱石",) and b.id == 7


# --- pairing ------------------------------------------------------------------------------------------------------- #
NEKO_CHARS = 330_000           # about the novel's length: ~10 h read aloud at ~9 characters a second


def _neko_audio(folder, minutes=60, files=10, tags=None):
    _chapters(folder, [f"{n:02}.mp3" for n in range(1, files + 1)], minutes=minutes, tags=tags)
    (b,) = ab.find(folder)
    return b


def test_a_book_beside_its_audio_is_paired_with_no_question(tmp_path):
    folder = str(tmp_path / NEKO)
    audio = _neko_audio(folder)
    book = _book(os.path.join(folder, f"{NEKO}.epub"), NEKO, chars=NEKO_CHARS)
    pair = ab.decide(audio, [book, _book(str(tmp_path / BOCCHAN / "b.epub"), BOCCHAN, sha="b")])
    assert (pair.book, pair.how) == (book, ab.SURE)


def test_audio_in_a_subfolder_of_the_book_is_near(tmp_path):
    """`吾輩は猫である/audio/01.mp3`: a folder named for what it holds gives the title of the one above it."""
    audio = _neko_audio(str(tmp_path / NEKO / "audio"))
    assert audio.title == NEKO
    book = _book(str(tmp_path / NEKO / f"{NEKO}.epub"), NEKO)                     # no length to check: near is enough
    assert ab.decide(audio, [book]).how == ab.SURE


def test_the_same_title_in_two_folders_pairs_when_the_length_fits(tmp_path):
    """`Books/吾輩は猫である/` and `Audiobooks/吾輩は猫である/`: far apart, but the one book of that title whose length the
    narration fits."""
    audio = _neko_audio(str(tmp_path / "Audiobooks" / NEKO))
    book = _book(str(tmp_path / "Books" / NEKO / f"{NEKO}.epub"), NEKO, chars=NEKO_CHARS)
    assert ab.decide(audio, [book]).how == ab.SURE


def test_far_apart_with_no_length_asks_unless_an_author_tag_names_the_creator(tmp_path):
    audio = _neko_audio(str(tmp_path / "Audiobooks" / NEKO))
    book = _book(str(tmp_path / "Books" / "x.epub"), NEKO, "夏目 漱石")
    assert ab.decide(audio, [book]).how == ab.ASK
    tagged = _neko_audio(str(tmp_path / "Audio2" / NEKO), tags=lambda i: {"TPE2": "夏目漱石", "TPE1": "朗読 山田"})
    assert ab.decide(tagged, [book]).how == ab.SURE


def test_a_narrator_tag_never_counts_against(tmp_path):
    folder = str(tmp_path / NEKO)
    audio = _neko_audio(folder, tags=lambda i: {"TPE1": "朗読 山田花子"})
    book = _book(os.path.join(folder, "x.epub"), NEKO, "夏目漱石", chars=NEKO_CHARS)
    assert ab.decide(audio, [book]).how == ab.SURE


def test_two_editions_of_the_title_ask_once_unless_one_is_beside(tmp_path):
    audio = _neko_audio(str(tmp_path / "Audiobooks" / NEKO))
    a = _book(str(tmp_path / "Books A" / "a.epub"), NEKO, sha="a")
    b = _book(str(tmp_path / "Books B" / "b.epub"), NEKO, sha="b")
    pair = ab.decide(audio, [a, b])
    assert pair.how == ab.ASK and pair.book in (a, b)
    beside = _book(str(tmp_path / "Audiobooks" / NEKO / "c.epub"), NEKO, sha="c")
    assert ab.decide(audio, [a, b, beside]) == ab.Pair(beside, ab.SURE, ab.answer_key(audio, beside))


def test_a_volume_that_differs_is_never_a_pair(tmp_path):
    """第1巻's audio is not 第2巻's book, however alike the rest; volume 1's book is found among them."""
    series = "ソードアート・オンライン"
    _m4b(str(tmp_path / "SAO" / f"{series} 第1巻.m4b"), 8 * 3600, {"album": f"{series} 1"})
    (audio,) = ab.find(str(tmp_path / "SAO"))
    v2 = _book(str(tmp_path / "SAO" / "v2.epub"), f"{series} 2", sha="v2")
    assert ab.decide(audio, [v2]) is None
    v1 = _book(str(tmp_path / "SAO" / "v1.epub"), f"{series}（1）", sha="v1")
    assert ab.decide(audio, [v2, v1]).book == v1


def test_a_length_that_does_not_fit_asks(tmp_path):
    """Thirty minutes for a 330,000-character novel: an abridged reading or a sample — asked, never paired by itself."""
    folder = str(tmp_path / NEKO)
    audio = _neko_audio(folder, minutes=30, files=1)
    book = _book(os.path.join(folder, "x.epub"), NEKO, chars=NEKO_CHARS)
    assert ab.decide(audio, [book]).how == ab.ASK


def test_an_alike_title_asks_and_an_unlike_one_is_no_pair(tmp_path):
    folder = str(tmp_path / "銀河鉄道の夜 朗読")
    audio = _neko_audio(folder, files=2)
    typo = _book(os.path.join(folder, "x.epub"), "銀河鐵道の夜", sha="typo")     # the old form of 鉄 (a like title)
    assert ab.decide(audio, [typo]).how == ab.ASK
    assert ab.decide(audio, [_book(os.path.join(folder, "y.epub"), BOCCHAN, sha="y")]) is None


def test_a_folder_named_author_and_title_is_close(tmp_path):
    folder = str(tmp_path / f"夏目漱石 - {NEKO}")
    audio = _neko_audio(folder)
    book = _book(os.path.join(folder, "x.epub"), NEKO, chars=NEKO_CHARS)
    assert ab.score(audio, book).title == ab.CLOSE
    assert ab.decide(audio, [book]).how == ab.SURE


def test_an_answer_is_remembered_and_survives_a_move(tmp_path):
    """The one question: a *no* leaves that book out for good (the next is asked), a *yes* pairs it — and the answer's
    key is the same after the book's EPUB moves or is renamed (its sha256 is the key, not its path)."""
    audio = _neko_audio(str(tmp_path / "Audiobooks" / NEKO))
    a = _book(str(tmp_path / "Books A" / "a.epub"), NEKO, sha="a")
    b = _book(str(tmp_path / "Books B" / "b.epub"), NEKO, sha="b")
    first = ab.decide(audio, [a, b])
    other = b if first.book == a else a
    answers = {first.key: False}
    second = ab.decide(audio, [a, b], answers)
    assert second.book == other and second.how == ab.ASK      # a no proposes the next, never the same again
    answers[second.key] = True
    assert ab.decide(audio, [a, b], answers) == ab.Pair(other, ab.ANSWERED, second.key)
    moved = other._replace(path=str(tmp_path / "Moved" / "renamed.epub"))
    assert ab.decide(audio, [moved], answers).how == ab.ANSWERED
    answers = {ab.answer_key(audio, a): False, ab.answer_key(audio, b): False}
    assert ab.decide(audio, [a, b], answers) is None           # both said no: alone


def test_a_new_edition_of_the_audio_is_a_new_pair(tmp_path):
    audio = _neko_audio(str(tmp_path / "Audiobooks" / NEKO))
    book = _book(str(tmp_path / "Books" / "a.epub"), NEKO, sha="a")
    longer = audio._replace(sizes=audio.sizes[:-1] + (audio.sizes[-1] + 1,))
    assert ab.answer_key(audio, book) != ab.answer_key(longer, book)


def test_no_books_means_alone(tmp_path):
    assert ab.decide(_neko_audio(str(tmp_path / NEKO)), []) is None


# --- review round 1 (register `audiobooks-register.md` R1-1 … R1-13) ------------------------------------------------ #
def test_disc_folders_named_with_their_title_join_by_title(tmp_path):
    """R1-4: `Audiobooks/吾輩は猫である CD1`, `… CD2` and `坊っちゃん CD1` side by side are two audiobooks, never one."""
    root = tmp_path / "Audiobooks"
    _chapters(str(root / f"{NEKO} CD2"), ["01.mp3"], minutes=15)
    _chapters(str(root / f"{NEKO} CD1"), ["01.mp3", "02.mp3"], minutes=15)
    _chapters(str(root / f"{BOCCHAN} CD1"), ["01.mp3", "02.mp3"], minutes=15)
    found = {b.title: b for b in ab.find(str(root))}
    assert set(found) == {NEKO, BOCCHAN}
    assert [os.path.relpath(p, root).replace("\\", "/") for p in found[NEKO].files] == \
        [f"{NEKO} CD1/01.mp3", f"{NEKO} CD1/02.mp3", f"{NEKO} CD2/01.mp3"]
    assert ab.find(str(root / f"{NEKO} CD1")) == []


def test_an_album_tag_with_a_disc_mark_stays_one_audiobook(tmp_path):
    """R1-5: CD rips tag `銀河鉄道の夜 (Disc 1)` / `(Disc 2)`: one book, its title without the disc."""
    folder = tmp_path / GINGA
    for disc in (1, 2):
        for t in (1, 2):
            _mp3(str(folder / f"{disc}-{t:02}.mp3"), seconds=900,
                 frames={"TALB": f"{GINGA} (Disc {disc})", "TRCK": str(t), "TPOS": str(disc)})
    (b,) = ab.find(str(folder))
    assert b.title == GINGA and len(b.files) == 4
    assert [os.path.basename(p) for p in b.files] == ["1-01.mp3", "1-02.mp3", "2-01.mp3", "2-02.mp3"]


def test_a_file_name_that_is_only_a_number_is_no_title(tmp_path):
    """R1-6: `坊っちゃん/01.m4b` against a far `01.epub` of another book: never paired on "01"."""
    _m4b(str(tmp_path / "Audio" / BOCCHAN / "01.m4b"), 4 * 3600, {"title": BOCCHAN})
    (audio,) = ab.find(str(tmp_path / "Audio" / BOCCHAN))
    other = _book(str(tmp_path / "Books" / "猫" / "01.epub"), NEKO, chars=NEKO_CHARS)
    assert "01" not in audio.titles
    assert ab.decide(audio, [other]) is None


def test_a_volume_on_one_side_only_asks(tmp_path):
    """R1-7: audio with no volume against `とある魔術の禁書目録 1` beside it: asked, never sure."""
    series = "とある魔術の禁書目録"
    audio = _neko_audio(str(tmp_path / series))
    book = _book(str(tmp_path / f"{series} 1" / "x.epub"), f"{series} 1")
    assert ab.decide(audio, [book]).how == ab.ASK
    upper = _neko_audio(str(tmp_path / f"{NEKO}【上】"))
    lower = _book(str(tmp_path / "b" / "y.epub"), f"{NEKO}（下）", sha="lower")
    assert ab.decide(upper, [lower]) is None                  # 上 is not 下


def test_volume_in_brackets_or_glued_is_read(tmp_path):
    """R1-1 / R1-2: volume 1's audio never pairs with `（2）` or `Vol.2` beside it."""
    series = "ソードアート・オンライン"
    _m4b(str(tmp_path / "SAO" / "a.m4b"), 8 * 3600, {"album": f"{series} 1"})
    (audio,) = ab.find(str(tmp_path / "SAO"))
    for title in (f"{series}（2）", f"{series}Vol.2", f"{series} 第2巻"):
        assert ab.decide(audio, [_book(str(tmp_path / "SAO" / "v.epub"), title, sha=title)]) is None


def test_a_damaged_epub_member_gives_no_metadata(tmp_path):
    """R1-8: a member whose deflate stream is broken (zlib.error) is unread, never a crash."""
    p = str(tmp_path / "x.epub")
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml",
                   '<container><rootfiles><rootfile full-path="c.opf"/></rootfiles></container>')
        z.writestr("c.opf", "<package>" + "x" * 5000 + "</package>")
    raw = bytearray(open(p, "rb").read())
    start = raw.find(b"c.opf") + len("c.opf")              # the member's local header ends here: its data follows
    for i in range(start + 10, start + 40):                  # scribble over the first compressed bytes
        raw[i] ^= 0xFF
    open(p, "wb").write(bytes(raw))
    assert ab.epub_meta(p) == ((), ())
    assert ab.book_of(p).titles == ("x",)


def test_a_sequel_is_asked_never_sure(tmp_path):
    """R1-9: `続・魔法科高校の劣等生` holds its first book's name: a close title away from the audio's folder asks."""
    library = tmp_path / "Library"
    audio = _neko_audio(str(library / "魔法科高校の劣等生"))
    sequel = _book(str(library / "続・魔法科高校の劣等生" / "x.epub"), "続・魔法科高校の劣等生", chars=NEKO_CHARS)
    assert ab.score(audio, sequel).title == ab.CLOSE
    assert ab.decide(audio, [sequel]).how == ab.ASK


def test_an_mp3_tag_ending_at_the_head_read_keeps_its_length(tmp_path):
    """R1-11: the tag ends a few bytes before HEAD_BYTES: the Xing frame after it is still read (no CBR guess)."""
    p = _mp3(str(tmp_path / "edge.mp3"), seconds=3600, frames={"TALB": NEKO}, pad=ab.HEAD_BYTES - 60)
    assert ab.read_tags(p).seconds == pytest.approx(3600, abs=0.1)


def test_mp4_with_a_64_bit_moov_and_a_quicktime_meta(tmp_path):
    """R1-11: a `moov` with a 64-bit size, its tags in a `meta` right under it (QuickTime's place, no version bytes)."""
    mvhd = _atom(b"mvhd", b"\0\0\0\0" + struct.pack(">IIII", 0, 0, 1000, 3_600_000) + b"\0" * 80)
    meta = _atom(b"meta", _atom(b"hdlr", b"\0" * 24) + _atom(b"ilst", _atom(b"\xa9alb", _text(GINGA))))
    body = mvhd + meta
    moov = struct.pack(">I", 1) + b"moov" + struct.pack(">Q", 16 + len(body)) + body
    p = tmp_path / "x.m4b"
    p.write_bytes(_atom(b"ftyp", b"M4B \0\0\0\0") + moov)
    t = ab.read_tags(str(p))
    assert (t.album, t.seconds) == (GINGA, 3600)


def test_a_short_chapter_list_keeps_the_tags(tmp_path):
    """R1-11: a `chpl` that ends early: no chapters, but the title, album and length are kept."""
    p = _m4b(str(tmp_path / "x.m4b"), 7200, {"album": NEKO}, chapters=[("一", 0), ("二", 100)])
    data = bytearray(open(p, "rb").read())
    at = data.find(b"chpl")
    data[at + 4 + 8] = 40                                    # claims 40 chapters, holds 2
    open(p, "wb").write(bytes(data))
    t = ab.read_tags(p)
    assert (t.album, t.seconds, t.chapters) == (NEKO, 7200, None)


def test_kanji_numbered_chapter_files_sort_by_number(tmp_path):
    """R1-12: untagged `第一章 … 第十二章`: 二 before 十, 十 before 十二."""
    folder = tmp_path / NEKO
    names = ["第十二章.mp3", "第二章.mp3", "第十章.mp3", "第一章.mp3", "第三章.mp3"]
    _chapters(str(folder), names, minutes=10)
    (b,) = ab.find(str(folder))
    assert [os.path.basename(p) for p in b.files] == ["第一章.mp3", "第二章.mp3", "第三章.mp3", "第十章.mp3",
                                                      "第十二章.mp3"]


def test_the_answer_survives_renaming_the_audio_folder(tmp_path):
    """R1-13: an untagged audiobook named by its folder: renamed, its answer key is the same (its files' sizes)."""
    audio = _neko_audio(str(tmp_path / "Audiobooks" / NEKO))
    book = _book(str(tmp_path / "Books" / "a.epub"), NEKO, sha="a")
    os.rename(str(tmp_path / "Audiobooks" / NEKO), str(tmp_path / "Audiobooks" / f"{NEKO} (朗読)"))
    (renamed,) = ab.find(str(tmp_path / "Audiobooks" / f"{NEKO} (朗読)"))
    assert ab.answer_key(renamed, book) == ab.answer_key(audio, book)


def test_a_tiny_ts_file_is_not_a_video(tmp_path):
    """A small `.ts` (a TypeScript file, never a video: Connect's video rule) leaves the audiobook in place."""
    folder = tmp_path / NEKO
    _chapters(str(folder), ["01.mp3", "02.mp3"])
    (folder / "index.ts").write_text("export {}", encoding="utf-8")
    assert len(ab.find(str(folder))) == 1


def test_two_editions_equally_near_ask(tmp_path):
    """Mutant A5: two EPUBs of the title, both in the audio's own folder — a tie only the learner can break."""
    folder = str(tmp_path / NEKO)
    audio = _neko_audio(folder)
    a = _book(os.path.join(folder, "a.epub"), NEKO, sha="a")
    b = _book(os.path.join(folder, "b.epub"), NEKO, sha="b")
    assert ab.decide(audio, [a, b]).how == ab.ASK


def test_partly_repeated_track_numbers_fall_back_to_the_names(tmp_path):
    """Mutant A11: tracks 2, 1, 1 (a tagger's mistake) never reorder `01 02 03`: a repeat means the tags can't order."""
    folder = tmp_path / NEKO
    for name, track in (("01.mp3", "2"), ("02.mp3", "1"), ("03.mp3", "1")):
        _mp3(str(folder / name), seconds=1200, frames={"TRCK": track})
    (b,) = ab.find(str(folder))
    assert [os.path.basename(p) for p in b.files] == ["01.mp3", "02.mp3", "03.mp3"]
