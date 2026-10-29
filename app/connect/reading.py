"""A book or a text as Anki Miner reads it (round 2's Z-9; Sonic 2026-10-28: a must for 3.0): the file Connect names
for a book's or a text's job, and where in the book a card Anki Miner made lies.

- `source(item_path, pairing)`: the file the job's `reading_file` names. The EPUB a book's part was cut from (its
  origin record's `<epub>#<n>`, on this computer): its cover is the cards' picture and its table of contents the
  Source's place (`<series> — <location_label>`). Else the item's own text in the library — always there, and the
  text the words were picked from: a text, an Aozora book, a PDF's text, a book whose EPUB is away (lean Z9-2,
  PROVISIONAL: cards now, without the cover, over waiting for the EPUB). Both kinds are Zero's smaller version's
  (`.epub` and `.txt`).
- `place(location, line_text, parts, documents)`: the part a card's sentence lies in, by Hon's chapter record
  (`tracks/books/work/chapter-record.md`, origin key `chapter`; `library.book_parts`) and Anki Miner's `location`:
  `ch.<n>` is reading document n, a TOC label every document carrying it; among the parts whose documents span it,
  the one whose offsets hold the sentence, found in the document's text with whitespace ignored (Anki Miner joins a
  paragraph's wrapped lines with nothing; the library keeps each line).

Light: the standard library; the EPUB's documents are read (`app.extract.epub_documents`) only when a TOC label or
two parts sharing a document need them, once a job.
"""
import os
import re

_CHAPTER_DOC = re.compile(r"ch\.(\d+)")


def source(item_path, pairing):
    """-> (the file Anki Miner reads for this item, the EPUB when that file is one, else None). `item_path`: the
    item's text in the library; `pairing`: its record (`library.pairing_of`)."""
    from app.connect import runner
    if str(item_path).lower().endswith(".epub"):
        return item_path, item_path
    origin = runner.origin_of(pairing)
    book = origin.rpartition("#")[0] if origin and "#" in origin else None
    if book and book.lower().endswith(".epub") and runner._on_disk(book):
        return book, book
    return item_path, None


def as_text(path, folder, language):
    """The file to name as `reading_file`: an `.epub` or a `.txt` as it is; any other text the library holds (a `.md`,
    a subtitle kept as a text) written as a `.txt` of its text as a Generate reads it, in the job's run folder (`folder`)
    — Anki Miner reads `.epub` and `.txt` (Zero's smaller version) and refuses any other file (review R1-2)."""
    if str(path).lower().endswith((".epub", ".txt")):
        return path
    from app import analyzer
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, os.path.splitext(os.path.basename(path))[0] + ".txt")
    tmp = f"{out}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(analyzer.extract_text(str(path), language) or "")
    os.replace(tmp, out)
    return out


def chapter(pairing):
    """The item's chapter record (Hon's `chapter`: a dict), or None (a text, a book from before the record)."""
    record = (pairing or {}).get("chapter")
    if isinstance(record, str):             # the store keeps the record's JSON as written
        import json
        try:
            record = json.loads(record)
        except ValueError:
            return None
    return record if isinstance(record, dict) else None


def _squeezed(text):
    return "".join(str(text or "").split())


def _find(text, needle):
    """Where `needle` (whitespace out) starts in `text`, whitespace ignored -> its offset in `text`, or None."""
    if not needle:
        return None
    keep = [i for i, ch in enumerate(text) if not ch.isspace()]
    at = "".join(text[i] for i in keep).find(needle)
    return keep[at] if at >= 0 else None


def _docs(record):
    docs = record.get("docs") if isinstance(record, dict) else None
    if isinstance(docs, list) and len(docs) == 2 and all(isinstance(n, int) and not isinstance(n, bool)
                                                          for n in docs):
        return docs
    return None


def _spans(record, n):
    docs = _docs(record)
    return docs is not None and docs[0] <= n <= docs[1]


def _holds(record, n, at):
    """Does the part `record` hold offset `at` of document n (its [start, end): `start` in its first document's text,
    `end` in its last's)?"""
    first, last = _docs(record)
    start, end = record.get("start"), record.get("end")
    if n == first and isinstance(start, int) and at < start:
        return False
    if n == last and isinstance(end, int) and at >= end:
        return False
    return first <= n <= last


def place(location, line_text, parts, documents):
    """The item id of the part `line_text` lies in (Hon's placing steps, § above), or None (no location, no part spans
    it, the sentence not found where several could). `parts`: {item id: chapter record} of the book's parts;
    `documents()`: the EPUB's reading documents (`extract.epub_documents`' Docs; None when they can't be read)."""
    location = str(location or "").strip()
    if not location or not parts:
        return None
    docs = None
    numbered = _CHAPTER_DOC.fullmatch(location)
    if numbered:
        candidates = [int(numbered.group(1))]
    else:
        docs = documents()
        candidates = [n for n, d in enumerate(docs or ()) if d.label == location]
    needle = _squeezed(line_text)
    for n in candidates:
        spanning = [item for item, record in parts.items() if _spans(record, n)]
        if len(spanning) == 1 and len(candidates) == 1:
            return spanning[0]
        if not spanning:
            continue
        docs = docs if docs is not None else documents()
        if not docs or n >= len(docs):
            return None
        at = _find(docs[n].text or "", needle)
        if at is None:
            continue                        # a repeated label: the next document carrying it
        return next((item for item in spanning if _holds(parts[item], n, at)), None)
    return None


def documents_of(epub):
    """A once-a-job reader of `epub`'s reading documents for `place` (None when the EPUB can't be read)."""
    got = []

    def read():
        if not got:
            from app import extract
            docs, _why = extract.epub_documents(epub) if epub and os.path.isfile(epub) else (None, None)
            got.append(docs)
        return got[0]
    return read
