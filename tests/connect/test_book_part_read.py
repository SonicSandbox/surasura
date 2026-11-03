"""A book's part makes Anki Miner read that part, never the whole book again (Michi-BK, Sonic's report #BS0A1K): Anki
Miner reads every sentence of the file it is handed before it makes a card, and each part's job handed it the whole
EPUB — a 122-part book read whole at every part, minutes each. A part now names its own copy of the EPUB
(`connect.reading.part_book`, `extract.epub_part`): every document in its place, only the part's own with text.

What a wrong answer would cost: these jobs write the learner's Anki unattended. A copy that numbers or labels one
document otherwise than the book puts every card of the part on the wrong part (`connect.reading.place` reads
`ch.<n>` and the TOC's labels against the whole book); a copy without the cover makes cards without their picture;
a copy that drops a sentence of the part makes no card for its words; a failure here that stops the mining leaves the
book unmined. Every doubt names the whole EPUB, as before.

Real text (the suite's `ja/context_test.txt`) in EPUBs built the way the book suite builds them
(`tests/test_book_chapters`), Hon's records from `extract.book_split`.
"""
import os
import struct
import zipfile
import zlib

import pytest

from app import extract
from app.connect import reading
from tests.connect.test_p41_asked import _library, _place_top, _jobs, _run
from tests.connect.test_z9_books import WORDS, BookSteps, _named, _parts_in_store
from tests.test_book_chapters import _between, _epub, _lines, _novel


@pytest.fixture
def novel(tmp_path):
    epub = _novel(tmp_path)
    docs, _ = extract.epub_documents(epub)
    parts = extract.book_split(docs, 1500)
    return epub, docs, {100 + n: p.chapter for n, p in enumerate(parts)}


def _png():
    """A real 1×1 PNG's bytes (Anki Miner peeks a cover's first bytes for an image's)."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xbb\x86\xfc")) + chunk(b"IEND", b""))


def _with_pictures(epub, cover_by="cover-image", encrypted=False):
    """`epub` rewritten with a cover picture (named by the EPUB3 `cover-image` property or the EPUB2 `<meta
    name="cover">`) and two illustrations the manifest lists; `encrypted`: an `encryption.xml` naming a font."""
    with zipfile.ZipFile(epub) as z:
        entries = [(i, z.read(i.filename)) for i in z.infolist()]
    props = ' properties="cover-image"' if cover_by == "cover-image" else ""
    items = (f'<item id="cv" href="images/cover.png" media-type="image/png"{props}/>'
             '<item id="i1" href="images/i-001.png" media-type="image/png"/>'
             '<item id="i2" href="images/i-002.jpg" media-type="image/jpeg"/>')
    meta = '<meta name="cover" content="cv"/>' if cover_by == "meta" else ""
    with zipfile.ZipFile(epub, "w") as z:
        for info, data in entries:
            if info.filename == "OEBPS/content.opf":
                data = data.replace(b"</manifest>", items.encode() + b"</manifest>").replace(
                    b"</metadata>", meta.encode() + b"</metadata>")
            z.writestr(info, data)
        for name in ("cover.png", "i-001.png", "i-002.jpg"):
            z.writestr(f"OEBPS/images/{name}", _png())
        if encrypted:
            z.writestr("META-INF/encryption.xml", '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                                                  '<EncryptedData/></encryption>')
    return epub


# --------------------------------------------------------------------------- #
# The copy: the book's every document in its place, only the part's own with text
# --------------------------------------------------------------------------- #
def test_a_parts_copy_numbers_and_labels_every_document_as_the_book_does_with_only_its_own_text(novel, tmp_path):
    """Each part's copy reads (as Anki Miner reads an EPUB: `extract.epub_documents`) with the same documents in the
    same places under the same TOC labels as the whole book — so a card's `ch.<n>` or label is placed as before — its
    own documents' text whole (every sentence of the part there) and every other document's empty; the package, the
    nav and the skipped cover page as they are (the cards' title and Source stay the book's)."""
    epub, docs, records = novel
    assert len(records) >= 4, "the novel splits into several parts"
    for item, record in records.items():
        path, why = reading.part_book(epub, record, str(tmp_path / "runs" / str(item)))
        assert why is None and path == str(tmp_path / "runs" / str(item) / "book" / "旅の記録.epub")
        copy, _ = extract.epub_documents(path)
        assert [(d.href, d.label) for d in copy] == [(d.href, d.label) for d in docs]
        first, last = record["docs"]
        assert [d.text for d in copy] == [d.text if first <= n <= last else "" for n, d in enumerate(docs)]
        assert _between(copy, record) == _between(docs, record) and _between(copy, record).strip()
        with zipfile.ZipFile(epub) as whole, zipfile.ZipFile(path) as mine:
            assert mine.namelist() == whole.namelist(), "every entry, in its order (mimetype first)"
            for name in ("mimetype", "META-INF/container.xml", "OEBPS/content.opf", "OEBPS/nav.xhtml",
                         "OEBPS/cover.xhtml", "OEBPS/p-colophon.xhtml"):
                assert mine.read(name) == whole.read(name), name
            assert mine.getinfo("mimetype").compress_type == zipfile.ZIP_STORED


def test_an_emptied_document_keeps_its_body_and_its_attributes_and_nothing_in_it():
    """`_emptied`: the body's start tag (its `epub:type` kept: Anki Miner's matter and cover checks read it) and end
    tag, nothing between; a namespaced body; a `<body/>` as it is; a word 'body' in the text or a `<bodyguard>` tag
    never taken for the body; no body in the bytes: None."""
    doc = (b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>body</title></head>'
           b'<body epub:type="bodymatter" class="vrtl">\n<p>\xe6\x97\x85 body</p><bodyguard/></body></html>')
    assert extract._emptied(doc) == (b'<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"><head>'
                                     b'<title>body</title></head><body epub:type="bodymatter" class="vrtl"></body>'
                                     b'</html>')
    assert extract._emptied(b"<x:html><x:BODY>\n<p>a</p></x:BODY ></x:html>") == b"<x:html><x:BODY></x:BODY ></x:html>"
    assert extract._emptied(b"<html><body/></html>") == b"<html><body/></html>"
    assert extract._emptied(b"<html><bodyguard>a</bodyguard></html>") is None
    assert extract._emptied(b"<html><body><p>a</p></html>") is None, "no end tag: not emptied by guess"


@pytest.mark.parametrize("cover_by", ["cover-image", "meta"])
def test_a_parts_copy_keeps_the_cover_and_leaves_out_the_pictures_no_reading_looks_at(novel, tmp_path, cover_by):
    """The cover is every card's picture (Anki Miner reads it from the file it's handed): kept, byte for byte, however
    the package names it. The book's other pictures no reading of its text looks at: left out, so a part's copy of an
    illustrated book isn't the book's size again in every job's folder."""
    epub, docs, records = novel
    _with_pictures(epub, cover_by)
    path, why = reading.part_book(epub, next(iter(records.values())), str(tmp_path / "run"))
    assert why is None
    with zipfile.ZipFile(path) as mine:
        names = mine.namelist()
        assert mine.read("OEBPS/images/cover.png") == _png()
    assert "OEBPS/images/i-001.png" not in names and "OEBPS/images/i-002.jpg" not in names
    copy, _ = extract.epub_documents(path)
    assert [(d.href, d.label) for d in copy] == [(d.href, d.label) for d in docs]


def test_a_book_with_an_encryption_file_keeps_every_picture(novel, tmp_path):
    """An `encryption.xml` may name any entry (an obfuscated font, or worse): nothing it could name is left out —
    Anki Miner decides about such a book as it did on the whole EPUB."""
    epub, _docs, records = novel
    _with_pictures(epub, encrypted=True)
    path, why = reading.part_book(epub, next(iter(records.values())), str(tmp_path / "run"))
    assert why is None
    with zipfile.ZipFile(epub) as whole, zipfile.ZipFile(path) as mine:
        assert mine.namelist() == whole.namelist()
        assert mine.read("META-INF/encryption.xml") == whole.read("META-INF/encryption.xml")


# --------------------------------------------------------------------------- #
# Every doubt: the whole EPUB, as before
# --------------------------------------------------------------------------- #
def test_a_record_that_doesnt_fit_its_epub_makes_no_copy(novel, tmp_path):
    """No record, a record from before `hrefs`, documents past the book's end, or `hrefs` the EPUB no longer has at
    those places (the book changed since it was split): no copy — the whole EPUB is named — and nothing written."""
    epub, _docs, records = novel
    record = next(iter(records.values()))
    folder = tmp_path / "run"
    bad = [None, {}, {k: v for k, v in record.items() if k != "hrefs"},
           dict(record, hrefs=record["hrefs"][:-1] + ["OEBPS/p-099.xhtml"]),
           dict(record, docs=[record["docs"][0] + 40, record["docs"][1] + 40]),
           dict(record, hrefs=record["hrefs"] + ["OEBPS/p-099.xhtml"]),
           dict(record, docs=[True, record["docs"][1]])]
    for wrong in bad:
        path, why = reading.part_book(epub, wrong, str(folder))
        assert path is None and why, wrong
    assert not folder.exists() or not any(folder.rglob("*.epub"))
    assert reading.part_book(str(tmp_path / "gone.epub"), record, str(folder))[0] is None


def test_a_document_whose_body_isnt_in_its_bytes_leaves_no_copy(tmp_path):
    """A document read as HTML without a `<body>` tag (Anki Miner reads it: a reading document) can't be emptied with
    sure hands: no copy, nothing left in the run folder — the whole EPUB is named."""
    lines = _lines()
    docs = [{"href": "c1.xhtml", "body": "".join(f"<p>{ln}</p>" for ln in lines[:3])},
            {"href": "c2.xhtml", "body": "".join(f"<p>{ln}</p>" for ln in lines[3:6])},
            {"href": "c3.xhtml", "body": "".join(f"<p>{ln}</p>" for ln in lines[6:9])}]
    epub = _epub(tmp_path / "体なし.epub", docs, [("c1.xhtml", "一"), ("c2.xhtml", "二"), ("c3.xhtml", "三")])
    with zipfile.ZipFile(epub) as z:
        entries = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(epub, "w") as z:
        for info, data in entries:
            if info.filename == "OEBPS/c3.xhtml":
                data = ("<p>" + lines[9] + "</p>").encode("utf-8")
            z.writestr(info, data)
    read, _ = extract.epub_documents(epub)
    assert [d.href for d in read] == ["OEBPS/c1.xhtml", "OEBPS/c2.xhtml", "OEBPS/c3.xhtml"]
    record = {"docs": [0, 0], "hrefs": ["OEBPS/c1.xhtml"], "start": 0, "end": len(read[0].text)}
    path, why = reading.part_book(epub, record, str(tmp_path / "run"))
    assert path is None and "c3.xhtml" in why
    assert not list((tmp_path / "run").rglob("*.epub*"))
    # the part holding that document: the others emptied, its own kept as it is
    record = {"docs": [2, 2], "hrefs": ["OEBPS/c3.xhtml"], "start": 0, "end": len(read[2].text)}
    path, why = reading.part_book(epub, record, str(tmp_path / "run"))
    assert why is None and [d.text for d in extract.epub_documents(path)[0]] == ["", "", read[2].text]


def test_a_copy_that_reads_otherwise_than_the_book_is_never_named(novel, tmp_path, monkeypatch):
    """The copy is read back before it is named: one whose documents would be numbered otherwise (here every emptied
    body typed as a cover, which Anki Miner skips) is removed and the whole EPUB named — never a card on the wrong
    part."""
    epub, _docs, records = novel
    monkeypatch.setattr(extract, "_emptied", lambda raw: raw.replace(b"<body", b'<body epub:type="cover"', 1))
    path, why = reading.part_book(epub, next(iter(records.values())), str(tmp_path / "run"))
    assert path is None and why == "its copy didn't read as the book does"
    assert not list((tmp_path / "run").rglob("*.epub*"))


# --------------------------------------------------------------------------- #
# The runner: the part's copy named; else the whole EPUB, and the job goes on
# --------------------------------------------------------------------------- #
def test_a_part_from_before_the_record_reads_the_whole_book_and_is_mined(tmp_path):
    """A part from before Hon's record (no `chapter`) names the whole EPUB, as before, and is mined."""
    _library()
    epub, parts, _records = _parts_in_store(tmp_path, chapter=False)
    steps = BookSteps(str(tmp_path), "ja", {"words": {str(parts[0]): WORDS}})
    _place_top(parts[0])
    _run(steps)
    assert _named(steps, parts[0]) == epub and _jobs(parts[0])[-1]["state"] == "done"


def test_a_copy_that_raises_reads_the_whole_book_and_is_mined(tmp_path, monkeypatch):
    """A copy that fails (a full disk, anything) never stops the job: the whole EPUB is named, the job mined."""
    _library()
    epub, parts, _records = _parts_in_store(tmp_path)

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(reading, "part_book", full)
    steps = BookSteps(str(tmp_path), "ja", {"words": {str(parts[0]): WORDS}})
    _place_top(parts[0])
    _run(steps)
    assert _named(steps, parts[0]) == epub and _jobs(parts[0])[-1]["state"] == "done"


def test_an_item_that_is_the_whole_epub_makes_no_copy(tmp_path):
    """An item that is the EPUB itself (no part, no record) is named as it was: no copy made."""
    epub = _novel(tmp_path)
    assert reading.source(epub, None) == (epub, epub)
    assert reading.part_book(epub, reading.chapter(None), str(tmp_path / "run")) == (None, "no chapter record")
    assert not (tmp_path / "run").exists()
