"""Books split by their chapters (Hon, alpha 4; QUESTIONS 2026-10-27 row 6): `extract.epub_documents` reads an EPUB as
Anki Miner 3.10.1 reads it (the spine in order — the manifest's order scrambled books —, its TOC's labels, front and back
matter skipped), `extract.book_split` cuts it by the TOC's chapters, else its heading lines, else in even parts, and
each part keeps where it sits in the book (its chapter, its documents, its offsets) for Anki Miner's results to be
placed on. The window names a chapter's part from its file name (`view_rows.chapter_part`).

Every book here is a small synthetic EPUB built from `tests/Test Resources/ja/` text.
"""
import json
import os
import zipfile

import pytest

from app import extract
from app.services import view_rows

RESOURCES = os.path.join(os.path.dirname(__file__), "Test Resources", "ja")


def _lines():
    with open(os.path.join(RESOURCES, "context_test.txt"), encoding="utf-8") as f:
        return [ln for ln in f.read().splitlines() if ln.strip()]


def _prose(chars):
    """Paragraphs of real Japanese, about `chars` characters."""
    lines, out, n, i = _lines(), [], 0, 0
    while n < chars:
        out.append(lines[i % len(lines)])
        n += len(out[-1]) + 1
        i += 1
    return "".join(f"<p>{ln}</p>" for ln in out)


def _epub(path, docs, toc=None, toc_kind="nav", reverse_manifest=False, guide=()):
    """An EPUB of `docs` [{"href", "body", "linear"?, "type"?}] in spine order. `toc` [(href, label)] goes into an EPUB3
    nav (`toc_kind` "nav") or an EPUB2 NCX ("ncx"); `reverse_manifest` lists the documents in the manifest backwards;
    `guide` [(href, type)] the OPF's EPUB2 guide."""
    items, refs = [], []
    for n, d in enumerate(docs):
        items.append(f'<item id="d{n}" href="{d["href"]}" media-type="application/xhtml+xml"/>')
        linear = ' linear="no"' if d.get("linear") == "no" else ""
        refs.append(f'<itemref idref="d{n}"{linear}/>')
    if reverse_manifest:
        items.reverse()
    toc_attr = ""
    if toc and toc_kind == "nav":
        items.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
    if toc and toc_kind == "ncx":
        items.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        toc_attr = ' toc="ncx"'
    guide_xml = "".join(f'<reference href="{h}" type="{t}"/>' for h, t in guide)
    opf = (f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
           f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>旅の記録</dc:title></metadata>'
           f'<manifest>{"".join(items)}</manifest><spine{toc_attr}>{"".join(refs)}</spine>'
           f'{"<guide>" + guide_xml + "</guide>" if guide else ""}</package>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                   'version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        for d in docs:
            typed = f' epub:type="{d["type"]}"' if d.get("type") else ""
            z.writestr(f"OEBPS/{d['href']}",
                       '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
                       'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>旅の記録</title></head>'
                       f'<body{typed}>{d["body"]}</body></html>')
        if toc and toc_kind == "nav":
            lis = "".join(f'<li><a href="{h}">{label}</a></li>' for h, label in toc)
            z.writestr("OEBPS/nav.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml" '
                       'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目次</title></head><body>'
                       f'<nav epub:type="toc"><ol>{lis}</ol></nav></body></html>')
        if toc and toc_kind == "ncx":
            points = "".join(f'<navPoint id="p{i}"><navLabel><text>{label}</text></navLabel><content src="{h}"/>'
                             f'</navPoint>' for i, (h, label) in enumerate(toc))
            z.writestr("OEBPS/toc.ncx", f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>{points}'
                                        f'</navMap></ncx>')
    return str(path)


def _novel(tmp_path, toc_kind="nav", **kw):
    """A light novel's shape: a cover, a title page, a prologue, two chapters (the first ~4,000 characters, over two
    files), an afterword and a colophon — its TOC naming each chapter's first file."""
    docs = [{"href": "cover.xhtml", "body": "<p>表紙</p>"},
            {"href": "p-001.xhtml", "body": "<p>旅の記録</p><p>著者</p>"},
            {"href": "p-002.xhtml", "body": "<h2>プロローグ</h2>" + _prose(900)},
            {"href": "p-003.xhtml", "body": "<h2>第一章　出会い</h2>" + _prose(2000)},
            {"href": "p-004.xhtml", "body": _prose(2000)},
            {"href": "p-005.xhtml", "body": "<h2>第二章　別れ</h2>" + _prose(1600)},
            {"href": "p-006.xhtml", "body": "<h2>あとがき</h2>" + _prose(300)},
            {"href": "p-colophon.xhtml", "body": "<p>奥付</p>"}]
    toc = [("cover.xhtml", "表紙"), ("p-002.xhtml", "プロローグ"), ("p-003.xhtml", "第一章　出会い"),
           ("p-005.xhtml", "第二章　別れ"), ("p-006.xhtml", "あとがき")]
    return _epub(tmp_path / "旅の記録.epub", docs, toc, toc_kind, **kw)


def _between(docs, record):
    """The text a part's record points at, read back from the documents."""
    first, last = record["docs"]
    if first == last:
        return docs[first].text[record["start"]:record["end"]]
    return "\n\n".join([docs[first].text[record["start"]:]] + [docs[i].text for i in range(first + 1, last)] +
                       [docs[last].text[:record["end"]]])


# --- reading: the spine, in order ----------------------------------------------------------------------------------- #
def test_an_epub_is_read_in_its_spine_order_never_its_manifests(tmp_path):
    """The bug: the File Importer read the manifest's order, so a book whose manifest lists its files otherwise than its
    spine came out scrambled. The spine is the reading order."""
    docs = [{"href": f"c{n}.xhtml", "body": f"<p>{line}</p>"} for n, line in enumerate(_lines()[:4])]
    path = _epub(tmp_path / "逆順.epub", docs, reverse_manifest=True)
    text, error = extract.extract_text_from_file(path, "ja")
    assert error is None
    assert text.split("\n\n") == _lines()[:4]


def test_what_anki_miner_skips_is_skipped_and_the_head_never_read(tmp_path):
    """`linear="no"`, a cover / toc / colophon file name, a cover-typed body and matter typed near either end are no
    reading documents; a document's <head> (its <title>, the book's name) never begins its text."""
    lines = _lines()
    docs = [{"href": "cover.xhtml", "body": "<p>表紙の絵</p>"},
            {"href": "front.xhtml", "body": "<p>著作権表示</p>", "type": "copyright-page"},
            {"href": "c1.xhtml", "body": f"<p>{lines[0]}</p>"},
            {"href": "c2.xhtml", "body": f"<p>{lines[1]}</p>", "linear": "no"},
            {"href": "c3.xhtml", "body": f"<p>{lines[2]}</p>"},
            {"href": "c4.xhtml", "body": f"<p>{lines[3]}</p>"},
            {"href": "c5.xhtml", "body": f"<p>{lines[4]}</p>"},
            {"href": "c6.xhtml", "body": f"<p>{lines[5]}</p>"},
            {"href": "end.xhtml", "body": "<p>奥付の文</p>"},
            {"href": "toc.xhtml", "body": "<p>目次の文</p>"}]
    path = _epub(tmp_path / "飛ばす.epub", docs, guide=[("end.xhtml", "colophon")])
    read, error = extract.epub_documents(path)
    assert error is None
    assert [d.href for d in read] == [f"OEBPS/c{n}.xhtml" for n in (1, 3, 4, 5, 6)]
    assert [d.text for d in read] == [lines[0], lines[2], lines[3], lines[4], lines[5]]


def test_a_matter_typed_document_in_the_middle_of_a_book_is_kept(tmp_path):
    """Matter is skipped only within 15% of either end (Anki Miner's zone): a mis-typed chapter mid-book stays."""
    lines = _lines()
    docs = [{"href": f"c{n}.xhtml", "body": f"<p>{lines[n]}</p>", **({"type": "colophon"} if n == 5 else {})}
            for n in range(10)]
    read, _ = extract.epub_documents(_epub(tmp_path / "中.epub", docs))
    assert lines[5] in [d.text for d in read]


def test_an_unreadable_epub_says_why(tmp_path):
    bad = tmp_path / "壊れた.epub"
    bad.write_bytes(b"not a zip")
    docs, error = extract.epub_documents(str(bad))
    assert docs is None and error.startswith("Failed to read EPUB")
    assert extract.parts_of(str(bad), "ja")[1] == error


# --- the TOC's labels, as Anki Miner takes them --------------------------------------------------------------------- #
@pytest.mark.parametrize("toc_kind", ["nav", "ncx"])
def test_each_document_takes_its_toc_label_from_the_nav_else_the_ncx(tmp_path, toc_kind):
    """The EPUB3 nav, else the EPUB2 NCX; 表紙 (and 目次, 奥付, 扉, 中扉) is never a chapter's label."""
    read, _ = extract.epub_documents(_novel(tmp_path, toc_kind))
    assert [(d.href.rsplit("/", 1)[-1], d.label) for d in read] == [
        ("p-001.xhtml", None), ("p-002.xhtml", "プロローグ"), ("p-003.xhtml", "第一章　出会い"), ("p-004.xhtml", None),
        ("p-005.xhtml", "第二章　別れ"), ("p-006.xhtml", "あとがき")]


def test_a_toc_of_fewer_than_two_usable_entries_labels_nothing(tmp_path):
    lines = _lines()
    docs = [{"href": f"c{n}.xhtml", "body": f"<p>{lines[n]}</p>"} for n in range(3)]
    read, _ = extract.epub_documents(_epub(tmp_path / "一つ.epub", docs, [("c0.xhtml", "目次"), ("c1.xhtml", "本文")]))
    assert [d.label for d in read] == [None, None, None]


# --- the split ----------------------------------------------------------------------------------------------------- #
def test_parts_follow_the_tocs_chapters_and_never_cross_one(tmp_path):
    """Each chapter its own parts, a long one cut evenly at sentence ends near the length, a short one whole; the title
    page (under 200 characters) joins the prologue, and the afterword stays its own."""
    docs, _ = extract.epub_documents(_novel(tmp_path))
    parts = extract.book_split(docs, 1500)
    chapters = [(p.chapter["chapter"], p.chapter["title"], p.chapter["part"], p.chapter["parts"]) for p in parts]
    assert chapters == [(1, "プロローグ", 1, 1), (2, "第一章　出会い", 1, 3), (2, "第一章　出会い", 2, 3),
                        (2, "第一章　出会い", 3, 3), (3, "第二章　別れ", 1, 1), (4, "あとがき", 1, 1)]
    assert {p.chapter["by"] for p in parts} == {"toc"}
    assert parts[0].text.startswith("旅の記録\n著者\n\nプロローグ")     # the title page joined the prologue
    assert all(p.text.endswith(("。", "？", "！", "」")) or p.chapter["part"] == p.chapter["parts"] for p in parts)
    sizes = [len(p.text) for p in parts if p.chapter["chapter"] == 2]
    assert max(sizes) - min(sizes) < 200                              # even, never a long part and a scrap
    joined = "\n\n".join(d.text for d in docs)
    for p in parts:                                                    # nothing lost, nothing doubled
        assert p.text in joined


def test_each_parts_record_finds_its_text_and_its_documents(tmp_path):
    """The record Anki Miner's results are placed by: its documents (their indexes are Anki Miner's `ch.<n>`), their
    entries and its offsets in the first and last — reading those back gives the part's text exactly."""
    docs, _ = extract.epub_documents(_novel(tmp_path))
    parts = extract.book_split(docs, 1500)
    for p in parts:
        assert _between(docs, p.chapter) == p.text
        first, last = p.chapter["docs"]
        assert p.chapter["hrefs"] == [d.href for d in docs[first:last + 1]]
    json.dumps([p.chapter for p in parts], ensure_ascii=False)        # a record a store row can hold
    assert parts[2].chapter["docs"] == [2, 3]                          # the chapter's second part crosses its two files


def test_a_book_with_no_toc_is_split_at_its_heading_lines(tmp_path):
    """No TOC: a short line with a heading marker starts a chapter (第N章, プロローグ, a number alone on its line …);
    a number alone is no title (*Chapter N*)."""
    docs = [{"href": "c1.xhtml", "body": "<p>プロローグ</p>" + _prose(600) + "<p>第１章　始まり</p>" + _prose(900)},
            {"href": "c2.xhtml", "body": "<p>２</p>" + _prose(900)},
            {"href": "c3.xhtml", "body": "<p>あとがき</p>" + _prose(300)}]
    read, _ = extract.epub_documents(_epub(tmp_path / "見出し.epub", docs))
    parts = extract.book_split(read, 1500)
    assert [(p.chapter["chapter"], p.chapter["title"], p.chapter["by"]) for p in parts] == [
        (1, "プロローグ", "headings"), (2, "第１章　始まり", "headings"), (3, None, "headings"), (4, "あとがき", "headings")]
    for p in parts:
        assert _between(read, p.chapter) == p.text


def test_a_toc_chapter_a_whole_book_long_is_divided_by_its_heading_lines(tmp_path):
    """A TOC that names only the work and its afterword: the work's chapter, over 20,000 characters and a third of the
    book, is divided where its heading lines stand — its own title line never starts an empty chapter."""
    body = "<p>星の歌</p>" + "".join(f"<p>{n}</p>" + _prose(8000) for n in (1, 2, 3))
    docs = [{"href": "c1.xhtml", "body": body}, {"href": "c2.xhtml", "body": "<p>あとがき</p>" + _prose(400)}]
    read, _ = extract.epub_documents(_epub(tmp_path / "一章.epub", docs, [("c1.xhtml", "星の歌"),
                                                                         ("c2.xhtml", "あとがき")]))
    parts = extract.book_split(read, 1500)
    chapters = []
    for p in parts:
        if (p.chapter["chapter"], p.chapter["title"], p.chapter["by"]) not in chapters:
            chapters.append((p.chapter["chapter"], p.chapter["title"], p.chapter["by"]))
    assert chapters == [(1, None, "headings"), (2, None, "headings"), (3, None, "headings"), (4, "あとがき", "toc")]
    assert parts[0].text.startswith("星の歌\n1\n")                     # the title line joined the first chapter


def test_a_book_with_neither_is_cut_in_even_parts_as_before(tmp_path):
    """No TOC and no heading line: today's even parts across the book, with each part's place still recorded."""
    docs = [{"href": f"c{n}.xhtml", "body": _prose(1700)} for n in range(3)]
    read, _ = extract.epub_documents(_epub(tmp_path / "平.epub", docs))
    parts = extract.book_split(read, 1500)
    text, _ = extract.convert_epub_to_text(_epub(tmp_path / "平2.epub", docs))
    assert [p.text for p in parts] == extract.split_by_length(text, 1500)
    assert {(p.chapter["by"], p.chapter["chapter"]) for p in parts} == {("even", None)}
    for p in parts:
        assert _between(read, p.chapter) == p.text


def test_even_parts_chosen_ignore_the_chapters(tmp_path):
    """*Split books by: Even parts*: the book's text in today's parts, its TOC never asked."""
    path = _novel(tmp_path)
    parts, error = extract.parts_of(path, "ja", by="even")
    text, _ = extract.convert_epub_to_text(path)
    assert error is None and [p.text for p in parts] == extract.split_by_length(text, extract.DEFAULT_LENGTH)
    assert all(extract.part_label(p.chapter) is None for p in parts)


def test_an_empty_book_has_no_parts(tmp_path):
    read, _ = extract.epub_documents(_epub(tmp_path / "空.epub", [{"href": "c.xhtml", "body": "<img src='a.png'/>"}]))
    assert extract.book_split(read, 1500) == []


# --- names: on disk and in the window --------------------------------------------------------------------------------- #
def test_a_chapters_parts_are_named_by_it_and_the_window_reads_the_name_back(tmp_path):
    docs, _ = extract.epub_documents(_novel(tmp_path))
    parts = extract.book_split(docs, 1500)
    names = [extract.part_name("旅の記録", n, len(parts), extract.part_label(p.chapter)) for n, p in enumerate(parts, 1)]
    assert names == ["旅の記録_01 (1) プロローグ.txt", "旅の記録_02 (2-1) 第一章 出会い.txt",
                     "旅の記録_03 (2-2) 第一章 出会い.txt", "旅の記録_04 (2-3) 第一章 出会い.txt",
                     "旅の記録_05 (3) 第二章 別れ.txt", "旅の記録_06 (4) あとがき.txt"]
    assert [view_rows.chapter_part(n) for n in names] == [
        (1, "プロローグ"), (2, "第一章 出会い · Part 1"), (3, "第一章 出会い · Part 2"), (4, "第一章 出会い · Part 3"),
        (5, "第二章 別れ"), (6, "あとがき")]
    assert [view_rows.episode_number(n) for n in names] == [1, 2, 3, 4, 5, 6]   # never a title's 第N話


def test_an_untitled_chapter_reads_chapter_n_and_an_even_part_keeps_part_n():
    assert view_rows.chapter_part("本_07 (3-2).txt") == (7, "Chapter 3 · Part 2")
    assert view_rows.chapter_part("本_04 (3).txt") == (4, "Chapter 3")
    assert view_rows.chapter_part("本_04.txt") is None and view_rows.episode_number("本_04.txt") == 4
    assert view_rows.episode_number("本_11 (4-3) 第3話 約束.txt") == 11


def test_a_chapters_title_in_a_file_name_is_cleaned_and_cut_short():
    label = extract.part_label({"chapter": 2, "part": 1, "parts": 1, "title": "第二章：「彼方/此方」？" + "あ" * 30})
    assert label.startswith("(2) 第二章：「彼方_此方」？") and len(label) <= 4 + extract.TITLE_LIMIT   # "/" never
    assert extract.part_label(None) is None and extract.part_label({"chapter": None}) is None


# --- Extract --------------------------------------------------------------------------------------------------------- #
def test_extract_names_a_books_parts_by_their_chapters(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "_settings_by", lambda: "chapters")
    result = extract.extract(_novel(tmp_path), "旅の記録", "ja", spawn=False)
    assert result.code == extract.EXIT_DONE and result.parts == 6
    from app.path_utils import get_data_path
    names = sorted(n for n in os.listdir(os.path.join(get_data_path("ja"), "Processed", "旅の記録")) if n.endswith(".txt"))
    assert names[0] == "旅の記録_01 (1) プロローグ.txt" and names[-1] == "旅の記録_06 (4) あとがき.txt"
