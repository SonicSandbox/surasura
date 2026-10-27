"""Extract (W3.4 row 2): an EPUB, a text or subtitle file, or one field of an Anki deck, split into parts and added to
the library — the File Importer's work (`app/epub_importer.py`, left as it is for 2.x), Qt-free and Tk-free.

The reading, the EPUB clean (ruby readings dropped, block tags as line breaks), both splits, *Group output into parts*
and the book marker are the Tk window's, moved as they are; the work runs **in a child** (`app_entry.py extract …`,
`main`: headless, dialog-free, its exit code the result) as an `extract` job, never on a window's thread (IK-4). The
fixes the port carries:

  * the output name is **cleaned** (`clean_name`: no path separators, no reserved characters, never `..`, never a
    device name), so nothing is written outside `Processed` or the section's folder;
  * **a taken name is refused** and `<name> 2` proposed (`check_name`, IK-1): taken means a folder of that name in
    `Processed` or in any section's folder, or anything the library store holds or keeps in its trash under one — so
    nothing in the library is moved, overwritten or mixed with a new split, and Put back still has its place;
  * an extraction that finds no text is a failure, never "Success"; a length and a number of parts are at least 1;
  * a delimiter pattern with groups of its own splits where it matches (the Tk split paired a group's text as a
    delimiter, or failed on an optional group);
  * the parts are written into a folder of their own first and then appear under their name at once (a rename), so a
    failure leaves no half-written folder;
  * **the new files enter the library through the store** (`Store.insert(files, <section>, "show")`, the path for
    files a command itself copied), never by copying into a section's folder for the disk sync to find; the store not
    there or not writable, or its insert failing → the copies go to the trash and the parts stay in `Processed`, and
    the result says so.
"""
import bisect
import json
import lzma
import math
import os
import re
import shutil
import sys
import time
import zipfile
import zlib
from collections import namedtuple

# Ensure package root is in sys.path
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.path_utils import get_data_path, get_user_files_path, read_text

SECTIONS = ("now", "soon", "goal")             # the store's tiers a user may extract into (Current · Soon · Goal)
DEFAULT_LENGTH = 1500                           # settings' `split_length` when it has none
DEFAULT_OVERFLOW = 150                          # `logic.importer.split_overflow` when it has none
DEFAULT_DELIMITER = r"\n\d+\n"
DEFAULT_PARTS = 5
TEXT_EXTENSIONS = (".epub", ".txt", ".md", ".srt", ".ass", ".ssa")
RESULT_MARK = "RESULT "
EXIT_DONE, EXIT_FAILED, EXIT_REFUSED, EXIT_PROCESSED_ONLY = 0, 1, 2, 3
NAME_LIMIT = 60                                 # characters: a folder name, and its parts' names after it (a grouped
                                                # split holds it three times: under Windows' 260-character paths)
# Set (by a test running the real child): the child adds its parts but starts no store helper — a detached helper would
# outlive the test's folders. The window's runs never set it.
NO_HELPER_ENV = "SURASURA_EXTRACT_NO_HELPER"

_RESERVED = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)

Name = namedtuple("Name", "name taken proposal")
# `title`: the item an 'already' names (SRC K3)
Result = namedtuple("Result", "code parts folder section in_library note title", defaults=(None,))


# --- the name ------------------------------------------------------------------------------------------------- #
def clean_name(name):
    """The output name as a safe folder name, or None when nothing safe is left: separators and reserved characters
    become "_", the ends lose spaces and dots, and a name of dots alone or a device name (CON, NUL, …) is refused."""
    name = _RESERVED.sub("_", str(name or "")).strip().rstrip(". ").strip()
    if not name or set(name) <= {".", "_", " "} or _DEVICE.match(name):
        return None
    return name[:NAME_LIMIT].rstrip(". ") or None


def _folders(language):
    """The folders a name may not be taken in: Processed, the content folder (Library: every new copy, 3.0's
    Sources), and each section's folder (Finished's too)."""
    from app import library_store
    data_dir = get_data_path(language)
    names = ["Processed", "Library"] + [library_store.FOLDER_OF_TIER[t] for t in SECTIONS] + [library_store.GRADUATED_FOLDER]
    return data_dir, names


def _store_holds(store, rels):
    """Whether the store holds an item, or keeps a trashed one, at or under any of `rels` (relative folders)."""
    from app.library_store import path_key
    keys = [path_key(r) for r in rels]
    for k in keys:                       # the items under a folder, by the store's own key (as its `_dir_rows`)
        row = store.conn.execute("SELECT 1 FROM items WHERE rel_key = ? OR (rel_key > ? AND rel_key < ?) LIMIT 1",
                                 (k, k + "/", k + "0")).fetchone()
        if row is not None:
            return True
    for row in store.trash_rows():       # Put back's places: a new split never takes one
        rel = path_key(row.get("rel_path") or "")
        if any(rel == k or rel.startswith(k + "/") for k in keys):
            return True
    return False


def is_taken(name, language, store=None):
    """Whether `name` is taken: a file or folder of that name in Processed or a section's folder, or anything the
    store holds or keeps in its trash under one of them."""
    data_dir, folders = _folders(language)
    if any(os.path.exists(os.path.join(data_dir, f, name)) for f in folders):
        return True
    return store is not None and _store_holds(store, [f"{f}/{name}" for f in folders])


def _open_reader(language):
    from app import library_store
    try:
        return library_store.open_store(language, get_data_path(language), get_user_files_path(language),
                                        role="reader")
    except Exception:
        return None


def check_name(name, language):
    """The name the user typed -> Name(the cleaned name or None, whether it is taken, the free name proposed:
    `<name> 2`, `<name> 3`, …). Reads the disk and the store (a worker's call)."""
    clean = clean_name(name)
    if clean is None:
        return Name(None, False, None)
    store = _open_reader(language)
    try:
        if not is_taken(clean, language, store):
            return Name(clean, False, None)
        n = 2
        while is_taken(f"{clean} {n}", language, store):
            n += 1
        return Name(clean, True, f"{clean} {n}")
    finally:
        if store is not None:
            store.close()


def check_options(method, value, group=False, parts=None):
    """The split options' first fault -> 'length' (not a whole number of at least 1), 'pattern' (empty or not a
    pattern), 'parts' (grouping on and not a whole number of at least 1), or None when they are sound."""
    if method == "delimiter":
        if not str(value or ""):
            return "pattern"
        try:
            re.compile(value)
        except re.error:
            return "pattern"
    else:
        try:
            if int(str(value).strip()) < 1:
                return "length"
        except (TypeError, ValueError):
            return "length"
    if group:
        try:
            if int(str(parts).strip()) < 1:
                return "parts"
        except (TypeError, ValueError):
            return "parts"
    return None


# --- reading (moved as they are from the Tk window) ------------------------------------------------------------ #
def extract_text_from_file(file_path, language):
    """(text, None) or (None, why)."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".epub":
        return convert_epub_to_text(file_path)
    elif ext in [".srt", ".ass", ".ssa"]:
        return extract_text_from_subtitle(file_path, language)
    else:
        return extract_text_from_generic(file_path, language)


def extract_text_from_generic(file_path, language):
    try:
        # A text file is read in its own encoding (path_utils.read_text), as the analyzer reads the library.
        return read_text(file_path, language), None
    except Exception as e:
        return None, f"Failed to read file: {e}"


def extract_text_from_subtitle(file_path, language):
    """A subtitle's text exactly as the library reads the same file (analyzer.extract_text)."""
    try:
        from app import analyzer   # light: fugashi and jieba load only with a tokenizer
        return analyzer.extract_text(file_path, language), None
    except Exception as e:
        return None, f"Failed to read the subtitle: {e}"


def convert_epub_to_text(epub_path):
    """The book's text in reading order (`epub_documents`), its documents joined by a blank line."""
    docs, error = epub_documents(epub_path)
    if error:
        return None, error
    return "\n\n".join(d.text for d in docs if d.text), None


# --- an EPUB's documents, as Anki Miner reads them -------------------------------------------------------------- #
# Its reading documents in the spine's order (the manifest's order scrambled some books) and its chapters' labels,
# by Anki Miner 3.10.1's rules (`services/reading/epub_source.py`), so both name a book's chapters alike and its
# results (`location_label`: a TOC label, else `ch.<n>`, n = the document's place among these) map onto the parts.
Doc = namedtuple("Doc", "href label text")      # href: its zip entry; label: the TOC's for it, or None

_EPUB_TYPES = ("{http://www.idpf.org/2007/ops}type", "epub:type")
_BOILERPLATE_LABELS = frozenset({"表紙", "目次", "奥付", "扉", "中扉"})
_BOILERPLATE_TOKENS = frozenset({"cover", "toc", "colophon", "caution"})
_MATTER_TYPES = frozenset({"copyright-page", "toc", "index", "colophon", "titlepage", "title-page", "loi", "lot",
                           "bibliography"})
_NAV_COMPANIONS = frozenset({"landmarks", "page-list"})
_MATTER_ZONE = 0.15                             # matter is skipped only this near either end of the spine
_CONTENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_MAX_MEMBER = 32 * 1024 * 1024                  # a document larger is skipped (a zip bomb's, never a chapter's)


def _local(el):
    tag = el.tag
    return tag.rpartition("}")[2].lower() if isinstance(tag, str) else ""


def _xml(data):
    from lxml import etree                      # EbookLib's own dependency
    try:
        return etree.fromstring(data, etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False,
                                                      no_network=True))
    except etree.XMLSyntaxError:
        return None


def _types(el):
    for attr in _EPUB_TYPES:
        if el.get(attr):
            return set(el.get(attr).split())
    return set()


def _resolve(base, href):
    from urllib.parse import unquote
    import posixpath
    href = unquote(href.split("#", 1)[0])
    return posixpath.normpath(posixpath.join(base, href) if base else href)


_READ_ERRORS = (KeyError, zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error,
                lzma.LZMAError)                 # a member that can't be read: skipped, as Anki Miner skips it


def _member(zf, entry):
    if zf.getinfo(entry).file_size > _MAX_MEMBER:
        return None
    with zf.open(entry) as f:
        data = f.read(_MAX_MEMBER + 1)
    return None if len(data) > _MAX_MEMBER else data


def _optional(zf, entry):
    """A nav or NCX member's bytes, or None when it can't be read (the book then has no TOC labels)."""
    try:
        return _member(zf, entry)
    except _READ_ERRORS:
        return None


def _toc(zf, names, manifest, spine_toc, opf_dir):
    """({entry: its first usable TOC label}, the landmarks' matter entries): the EPUB3 nav, else the EPUB2 NCX the
    spine names; boilerplate labels dropped; fewer than two usable entries -> no labels."""
    import posixpath
    entries, landmarks = [], set()
    nav = next((href for href, _mt, props in manifest.values() if "nav" in props), None)
    root = _xml(_optional(zf, _resolve(opf_dir, nav)) or b"") if nav and _resolve(opf_dir, nav) in names else None
    if root is not None:
        nav_dir = posixpath.dirname(_resolve(opf_dir, nav))
        navs = [el for el in root.iter() if _local(el) == "nav"]
        for el in navs:
            if "landmarks" in _types(el):
                for a in el.iter():
                    href = a.get("href") if _local(a) == "a" else None
                    if href and not href.partition("#")[2] and _types(a) & _MATTER_TYPES:
                        landmarks.add(_resolve(nav_dir, href))
        chosen = next((el for el in navs if "toc" in _types(el)), None)   # (an element with no children is falsy)
        if chosen is None:
            chosen = next((el for el in navs if el.get("id") == "toc"), None)
        if chosen is None and navs:
            chosen = navs[0]
        if chosen is not None:
            entries = [(_resolve(nav_dir, a.get("href")), "".join(a.itertext()).strip())
                       for a in chosen.iter() if _local(a) == "a" and a.get("href")]
    if not entries and spine_toc and spine_toc in manifest:
        entry = _resolve(opf_dir, manifest[spine_toc][0])
        root = _xml(_optional(zf, entry) or b"") if entry in names else None
        if root is not None:
            ncx_dir = posixpath.dirname(entry)
            for point in root.iter():
                if _local(point) != "navpoint":
                    continue
                label = src = None
                for sub in point.iter():
                    if _local(sub) == "text" and label is None:
                        label = "".join(sub.itertext()).strip()
                    elif _local(sub) == "content" and src is None:
                        src = sub.get("src")
                if src:
                    entries.append((_resolve(ncx_dir, src), label or ""))
    usable = [(t, label) for t, label in entries if label and label not in _BOILERPLATE_LABELS]
    labels = {}
    if len(usable) >= 2:
        for target, label in usable:
            labels.setdefault(target, label)
    return labels, landmarks


def _matter_typed(body):
    """The body, or every section it holds, typed as front or back matter."""
    if _types(body) & _MATTER_TYPES:
        return True
    children = [c for c in body if _local(c)]
    found = False
    for child in children:
        if _local(child) not in ("section", "div", "nav"):
            return False
        if _types(child) & _MATTER_TYPES:
            found = True
        elif not _types(child) & _NAV_COMPANIONS:
            return False
    return found


def _body(raw):
    """(the document's body element or None, typed as a cover?)."""
    root = _xml(raw)
    body = None if root is None else next((el for el in root.iter() if _local(el) == "body"), None)
    if body is None:
        from lxml import etree, html
        try:
            root = html.document_fromstring(raw)
        except (etree.ParserError, etree.XMLSyntaxError, ValueError):
            root = None
        body = None if root is None else next((el for el in root.iter() if _local(el) == "body"), None)
    cover = any(el is not None and "cover" in _types(el) for el in (root, body)) or (
        body is not None and any(_local(c) and "cover" in _types(c) for c in body))
    return body, cover


def _clean_text(raw):
    """A document's text as the File Importer always cleaned it — ruby readings dropped, block tags as line breaks,
    each line stripped, blank lines dropped — and, as Anki Miner reads it, never its <head> (its <title>, the book's
    name, began every document's text), a script or a style."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, 'html.parser')
    for tag in soup.find_all(['head', 'script', 'style']): tag.decompose()
    for rt in soup.find_all('rt'): rt.decompose()
    for rp in soup.find_all('rp'): rp.decompose()
    for br in soup.find_all('br'): br.replace_with('\n')
    for tag in soup.find_all(['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'li']): tag.append('\n')
    lines = [line.strip() for line in soup.get_text(separator='').splitlines() if line.strip()]
    return "\n".join(lines)


def epub_documents(epub_path):
    """The EPUB's reading documents -> ([Doc], None) or (None, why), as Anki Miner 3.10.1 reads them: the spine in
    order (`linear="no"` skipped), only (X)HTML documents; skipped: a cover / toc / colophon / caution / `p-ad-` file
    name, a cover-typed document, and front or back matter (landmarks, the `<guide>`, the body's own `epub:type`)
    within 15% of either end. Each Doc's `label` is its TOC label (the EPUB3 nav, else the NCX; 表紙 / 目次 / 奥付 /
    扉 / 中扉 dropped; none under two usable entries), its text as the File Importer cleans it ('' for none)."""
    import posixpath
    try:
        zf = zipfile.ZipFile(epub_path)
    except (zipfile.BadZipFile, OSError) as e:
        return None, f"Failed to read EPUB: {e}"
    try:
        with zf:
            names = set(zf.namelist())
            opf = None
            container = _xml(_member(zf, "META-INF/container.xml") or b"") if "META-INF/container.xml" in names \
                else None
            if container is not None:
                opf = next((el.get("full-path") for el in container.iter()
                            if _local(el) == "rootfile" and el.get("full-path") in names), None)
            opf = opf or next((n for n in sorted(names) if n.lower().endswith(".opf")), None)
            root = _xml(_member(zf, opf) or b"") if opf else None
            if root is None:
                return None, "Failed to read EPUB: no package document"
            opf_dir = posixpath.dirname(opf)
            manifest, spine, spine_toc, matter = {}, [], None, set()
            for el in root.iter():
                name = _local(el)
                if name == "item" and el.get("id") and el.get("href"):
                    manifest[el.get("id")] = (el.get("href"), el.get("media-type"), (el.get("properties") or "").split())
                elif name == "spine":
                    spine_toc = el.get("toc")
                elif name == "itemref" and el.get("idref") and (el.get("linear") or "").lower() != "no":
                    spine.append(el.get("idref"))
                elif name == "reference" and el.get("href") and not el.get("href").partition("#")[2] and \
                        (el.get("type") or "").strip().lower() in _MATTER_TYPES:
                    matter.add(_resolve(opf_dir, el.get("href")))
            labels, landmarks = _toc(zf, names, manifest, spine_toc, opf_dir)
            matter |= landmarks
            content = lambda item: item[1] in _CONTENT_TYPES or (   # noqa: E731
                not item[1] and item[0].split("#", 1)[0].lower().endswith((".xhtml", ".html", ".htm")))
            positions = {}
            for idref in spine:
                if idref in manifest and content(manifest[idref]):
                    positions.setdefault(_resolve(opf_dir, manifest[idref][0]), len(positions))
            edge = max(1, math.ceil(len(positions) * _MATTER_ZONE))
            docs = []
            for idref in spine:
                item = manifest.get(idref)
                if item is None or not content(item):
                    continue
                entry = _resolve(opf_dir, item[0])
                stem = posixpath.basename(entry).rsplit(".", 1)[0].lower()
                if entry not in names or stem.startswith("p-ad-") or set(re.split(r"[-_.]+", stem)) & _BOILERPLATE_TOKENS:
                    continue
                at = positions.get(entry, -1)
                zone = len(positions) >= 2 and at >= 0 and (at < edge or at >= len(positions) - edge)
                if zone and entry in matter:
                    continue
                try:
                    raw = _member(zf, entry)
                except _READ_ERRORS as e:
                    print(f"Warning: Failed to read {entry}: {e}")
                    continue
                if raw is None:
                    continue
                body, cover = _body(raw)
                if body is None or cover or (zone and _matter_typed(body)):
                    continue
                try:
                    text = _clean_text(raw)
                except Exception as e:
                    print(f"Warning: Failed to parse item {entry}: {e}")
                    text = ""
                docs.append(Doc(entry, labels.get(entry), text))
            return docs, None
    except Exception as e:
        return None, f"Failed to read EPUB: {e}"


def deck_text(path, field):
    """Every note's `field` text from the deck at `path` (the deck's temporary copy removed before this returns)."""
    from app.anki_utils import cleanup_temp_dir, extract_field_text, load_anki_data
    _fields, notes, model_map, temp_dir = load_anki_data(path)
    try:
        return extract_field_text(notes, model_map, field)
    finally:
        cleanup_temp_dir(temp_dir)


# --- splitting --------------------------------------------------------------------------------------------------- #
def split_by_delimiter(text, pattern):
    """Each part starts at a match of `pattern` (the match kept at its start); the text before the first match is a
    part of its own. Blank parts are dropped. (Where the pattern matches, whatever groups it holds.)"""
    starts = [m.start() for m in re.finditer(pattern, text) if m.start() > 0]
    chunks, at = [], 0
    for start in starts + [len(text)]:
        piece = text[at:start].strip()
        if piece:
            chunks.append(piece)
        at = start
    return chunks


def split_by_length(text, limit, overflow=DEFAULT_OVERFLOW):
    """Parts of about `limit` characters, each ended at the first sentence end within `overflow` after it."""
    chunks = [text[a:b].strip() for a, b in _length_cuts(text, 0, len(text), limit, overflow)]
    return [c for c in chunks if c]


def _length_cuts(text, lo, hi, limit, overflow):
    """`split_by_length`'s spans of text[lo:hi] -> [(start, end)], unstripped: each about `limit` characters, ended at
    the first sentence end within `overflow` after it (and the closing marks after that end)."""
    if limit < 1:
        raise ValueError("the length must be at least 1")
    spans = []
    pos = lo
    boundaries = "。？！.?! \n"
    closing_marks = "」』)\"']}"

    while pos < hi:
        target_end = pos + limit
        if target_end >= hi:
            spans.append((pos, hi))
            break
        found_boundary = -1
        search_end = min(target_end + overflow, hi)
        for i in range(target_end, search_end):
            if text[i] in boundaries:
                actual_end = i + 1
                while actual_end < hi and text[actual_end] in closing_marks:
                    actual_end += 1
                found_boundary = actual_end
                break
        end_pos = max(found_boundary if found_boundary != -1 else search_end, pos + 1)
        spans.append((pos, end_pos))
        pos = end_pos
    return spans


# --- a book by its chapters (QUESTIONS 2026-10-27 row 6) ------------------------------------------------------- #
# The TOC's chapters first (Anki Miner's: each labelled document starts one); a TOC chapter a whole book long, or a book
# with no TOC, divided where a heading line stands (第一章, 第1話, プロローグ, あとがき, Episode 1, a number alone on its
# line, …: the forms measured on 436 books); else even parts, as before. A part never crosses a
# chapter; a chapter is cut into parts of about `limit` characters, evenly, each ended at a sentence end.
HEADING = re.compile(                    # (never 第3回目の…, 三話目, 一章分: a count's word goes on)
    r"(?:第[0-9０-９一二三四五六七八九十百〇零]+[章話幕部節回](?![ぁ-ゖ目分間前後以内])"
    r"|[0-9０-９一二三四五六七八九十]+[章話](?![ぁ-ゖ目分間前後以内])"
    r"|プロローグ|エピローグ|序章|終章|幕間|間章|断章|序幕|終幕|閑話|番外編|あとがき|後書き"
    r"|(?:prologue|epilogue|interlude|chapter|episode)(?![a-z])"
    r"|[─━―—\-－＊*＃#◆◇■□\s]*(?:[0-9０-９]{1,3}|[一二三四五六七八九十]{1,3})"
    r"(?:[─━―—\-－＊*＃#◆◇■□\s]*$|\s*[．.:：、]\s*\S|\s+\S))", re.IGNORECASE)    # `３`, `３．<title>`, `３　<title>`
HEADING_LINE = 40          # a heading is a line this short or shorter
BIG_CHAPTER = 20000        # a TOC chapter this long (and a third of the book) is divided by its heading lines too
TINY_CHAPTER = 200         # a chapter with less text joins the next one (a title page, a picture's caption)
TITLE_LIMIT = 20           # characters of a chapter's title kept in its parts' file names
Part = namedtuple("Part", "text chapter")      # chapter: where the part sits in the book (`book_split`'s record)


_NUMBER_ONLY = re.compile(r"[─━―—\-－＊*＃#◆◇■□\s]*(?:[0-9０-９]{1,3}|[一二三四五六七八九十]{1,3})[─━―—\-－＊*＃#◆◇■□\s]*")


_CHAPTER_WORD = re.compile(r"第[0-9０-９一二三四五六七八九十百〇零]+[章話部]|[0-9０-９一二三四五六七八九十]+[章話]"
                           r"|(?:chapter|episode)(?![a-z])", re.IGNORECASE)


def _headings(book, lo, hi):
    """[(offset, its title)] of each heading line in book[lo:hi]; a number alone is no title (None: *Chapter N*). A
    line that ends a sentence (。、) is never a heading."""
    out = []
    for m in re.finditer(r"[^\n]+", book[lo:hi]):
        line = m.group().strip()
        if line and len(line) <= HEADING_LINE and not line.endswith(("。", "、")) and HEADING.match(line):
            out.append((lo + m.start(), None if _NUMBER_ONLY.fullmatch(line) else line))
    return out


def _chapter_heads(heads):
    """A book's chapters among its heading lines: where two or more name a chapter (第N章, N話, Chapter N …), the
    numbers alone under them are its sections, not chapters."""
    if sum(1 for _o, t in heads if t and _CHAPTER_WORD.match(t)) >= 2:
        return [h for h in heads if h[1] is not None]
    return heads


def book_split(docs, limit=DEFAULT_LENGTH, overflow=DEFAULT_OVERFLOW, by="chapters"):
    """A book's documents (`epub_documents`) -> [Part]: by its chapters (the TOC's, its heading lines'), or `by`
    "even" — or with neither — in even parts across the book as before. Each Part's text is stripped; its `chapter`
    record says where it is, so another reader's place in the book (Anki Miner's `location_label`: a TOC label or
    `ch.<n>`, n a document's index here) finds its part:
      {"by": "toc" | "headings" | "even", "chapter": its number from 1 (None for even parts), "title": the TOC's label
       or the heading line (or None), "part": its number in the chapter, "parts": the chapter's count,
       "docs": [first, last] document indexes, "hrefs": those documents' zip entries in order,
       "start": where it starts in the first document's text, "end": where it ends in the last's (exclusive)}."""
    if limit < 1:
        raise ValueError("the length must be at least 1")
    texts = [d.text for d in docs]
    kept = [i for i, t in enumerate(texts) if t]  # the documents with text: joined as `convert_epub_to_text` joins them
    book = "\n\n".join(texts[i] for i in kept)
    starts, at = [], 0
    for i in kept:
        starts.append(at)
        at += len(texts[i]) + 2
    begin, j = [], 0                             # each document's offset: an empty one's is the next text's
    for i in range(len(docs)):
        while j < len(kept) and kept[j] < i:
            j += 1
        begin.append(starts[j] if j < len(kept) else len(book))
    bounds = []                                  # [(offset, title, by)]: each chapter's start
    if by != "even":
        labelled = [(begin[i], d.label, "toc") for i, d in enumerate(docs) if d.label is not None]
        if labelled:
            bounds = ([(0, None, "toc")] if labelled[0][0] > 0 else []) + labelled
            ends = [b[0] for b in bounds[1:]] + [len(book)]
            more = []
            for (a, _t, _b), b in zip(bounds, ends):
                if b - a > BIG_CHAPTER and 3 * (b - a) > len(book):
                    lead = a + len(book[a:b]) - len(book[a:b].lstrip())
                    heads = _chapter_heads([h for h in _headings(book, a, b) if h[0] > lead])   # never its own title
                    if len(heads) >= 2:
                        more += [(o, line, "headings") for o, line in heads]
            bounds = sorted(bounds + more, key=lambda b: b[0])
        else:
            heads = _chapter_heads(_headings(book, 0, len(book)))
            if len(heads) >= 2:
                bounds = ([(0, None, "headings")] if book[:heads[0][0]].strip() else []) + \
                         [(o, line, "headings") for o, line in heads]
    chapters = []                                # [[start, end, title, by]]
    for n, (a, title, how) in enumerate(bounds):
        b = bounds[n + 1][0] if n + 1 < len(bounds) else len(book)
        if not book[a:b].strip():
            continue
        if chapters and len(book[chapters[-1][0]:chapters[-1][1]].strip()) < TINY_CHAPTER:
            # the tiny one before joins this one, under this one's name, else its own (第一章 then 1 under it)
            chapters[-1][1:] = [b, title if title is not None else chapters[-1][2], how]
        else:
            chapters.append([a, b, title, how])
    if len(chapters) > 1 and len(book[chapters[-1][0]:chapters[-1][1]].strip()) < TINY_CHAPTER:
        chapters[-2][1] = chapters[-1][1]        # a tiny last one joins the one before
        chapters.pop()
    parts = []
    if not chapters:
        for a, b in _length_cuts(book, 0, len(book), limit, overflow):
            parts.append((a, b, None, None, "even", 1))
    for c, (a, b, title, how) in enumerate(chapters, 1):
        k = max(1, round(len(book[a:b].strip()) / limit))
        cuts = _length_cuts(book, a, b, math.ceil((b - a) / k), overflow)
        parts += [(x, y, c, title, how, len(cuts)) for x, y in cuts]
    out, number = [], {}
    for a, b, c, title, how, count in parts:
        seg = book[a:b]
        text = seg.strip()
        if not text:
            continue
        a += len(seg) - len(seg.lstrip())
        b -= len(seg) - len(seg.rstrip())
        x = bisect.bisect_right(starts, a) - 1
        y = bisect.bisect_right(starts, b - 1) - 1
        first, last = kept[x], kept[y]
        number[c] = number.get(c, 0) + 1
        record = {"by": how, "chapter": c, "title": title, "part": number[c], "parts": count,
                  "docs": [first, last], "hrefs": [docs[i].href for i in range(first, last + 1)],
                  "start": a - starts[x], "end": b - starts[y]}
        if how == "even":
            record.update(chapter=None, part=None, parts=None)
        out.append(Part(text, record))
    for p in out:                                # a chapter's count is its parts with text
        if p.chapter["chapter"] is not None:
            p.chapter["parts"] = number[p.chapter["chapter"]]
    return out


def part_label(chapter):
    """A part's name after its number, from its record: `(3-2) 第一章 出会い` — chapter 3, its part 2 — `(3)` for a
    chapter of one part, its title cleaned and cut short; None for an even part (named by its number alone). The
    window reads it back (`view_rows`): *第一章 出会い · Part 2*, *Chapter 3*."""
    if not chapter or chapter.get("chapter") is None:
        return None
    head = f"({chapter['chapter']}" + (f"-{chapter['part']})" if chapter.get("parts", 1) > 1 else ")")
    title = chapter.get("title") or ""
    title = "" if _NUMBER_ONLY.fullmatch(title) else clean_name(    # a TOC's "3": no title; "/" and the rest: "・",
        _RESERVED.sub("・", re.sub(r"\s+", " ", title))[:TITLE_LIMIT]) or ""   # so no title ends as `_NN` does
    return f"{head} {title}" if title else head


# --- saving -------------------------------------------------------------------------------------------------------- #
def _mark(directory, source):
    """Record that this output came from an EPUB (the report's source badge says 'book'); the marker travels with
    the folder."""
    if not (source or "").lower().endswith(".epub"):
        return
    from app.path_utils import write_source_marker
    write_source_marker(directory, "epub", origin=os.path.basename(source))


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def part_name(base, number, count, label=None):
    """A part's file name: `<base>.txt` (one part), `<base>_NN.txt`, or a chapter's part `<base>_NN (3-2) <title>.txt`
    (`part_label`)."""
    if label:
        return f"{base}_{number:02d} {label}.txt"
    return f"{base}_{number:02d}.txt" if count > 1 else f"{base}.txt"


def save_chunks(chunks, base_name, folder, source=None, labels=None):
    """`folder/<base>.txt` (one part) or `folder/<base>_NN.txt` (`part_name`, a chapter's label after the number) ->
    the files' paths relative to `folder`, in order."""
    os.makedirs(folder, exist_ok=True)
    _mark(folder, source)
    written = []
    for i, chunk in enumerate(chunks, 1):
        filename = part_name(base_name, i, len(chunks), labels[i - 1] if labels else None)
        _write(os.path.join(folder, filename), chunk)
        written.append(filename)
    return written


def save_chunks_grouped(chunks, base_name, num_parts, folder, source=None):
    """`folder/<base>_<k>/<base>_<k>_NN.txt`, the parts spread over `num_parts` folders (fewer when there are fewer
    parts) -> the files' paths relative to `folder`, in order."""
    total_items = len(chunks)
    if total_items == 0:
        return []
    num_parts = min(num_parts, total_items)
    chunk_size = math.ceil(total_items / num_parts)
    os.makedirs(folder, exist_ok=True)
    written = []
    for i in range(num_parts):
        part_chunks = chunks[i * chunk_size:(i + 1) * chunk_size]
        if not part_chunks:
            continue
        part_folder_name = f"{base_name}_{i + 1}"
        sub = os.path.join(folder, part_folder_name)
        os.makedirs(sub, exist_ok=True)
        _mark(sub, source)
        for j, chunk in enumerate(part_chunks, 1):
            filename = f"{part_folder_name}_{j:02d}.txt"
            _write(os.path.join(sub, filename), chunk)
            written.append(f"{part_folder_name}/{filename}")
    return written


def _settings_overflow():
    try:
        from app import settings_manager
        logic = settings_manager.load_settings().get("logic", {}) or {}
        return int((logic.get("importer", {}) or {}).get("split_overflow", DEFAULT_OVERFLOW))
    except Exception:
        return DEFAULT_OVERFLOW


def _settings_by():
    """`split_books_by`: "chapters" (the default) or "even"."""
    try:
        from app import settings_manager
        return "even" if settings_manager.load_settings().get("split_books_by") == "even" else "chapters"
    except Exception:
        return "chapters"


def chunks_of(file_path, language, method="length", value=DEFAULT_LENGTH, field=None, overflow=None):
    """The parts of the file at `file_path` -> (parts, None) or (None, why): `parts_of`'s texts."""
    parts, error = parts_of(file_path, language, method, value, field, overflow)
    return (None, error) if error else ([p.text for p in parts], None)


def parts_of(file_path, language, method="length", value=DEFAULT_LENGTH, field=None, overflow=None, by=None):
    """The parts of the file at `file_path` -> ([Part], None) or (None, why). A deck gives its field's text as one
    part; an EPUB split by length goes by its chapters (`book_split`; `by` None: the `split_books_by` setting); anything
    else is read and split by length or by the delimiter pattern. Only an EPUB's parts carry a `chapter` record."""
    if file_path.lower().endswith(".apkg"):
        if not field:
            return None, "Choose the deck's field to extract."
        text = deck_text(file_path, field)
        return ([Part(text, None)] if text.strip() else []), None
    overflow = DEFAULT_OVERFLOW if overflow is None else overflow
    if file_path.lower().endswith(".epub") and method != "delimiter":
        docs, error = epub_documents(file_path)
        if error:
            return None, error
        return book_split(docs, int(value), overflow, by or _settings_by()), None
    text, error = extract_text_from_file(file_path, language)
    if error:
        return None, error
    if method == "delimiter":
        return [Part(t, None) for t in split_by_delimiter(text or "", value)], None
    return [Part(t, None) for t in split_by_length(text or "", int(value), overflow)], None


def extract(file_path, name, language, section=None, method="length", value=DEFAULT_LENGTH, parts=0, field=None,
            overflow=None, spawn=True):
    """The whole extraction: check the name, read and split, write the parts into `Processed/<name>` (a folder of
    their own first, renamed when complete), then — with `section` — copy them into that section's folder and add
    them to the library through the store. -> Result. `parts` > 0 groups the output into that many folders."""
    clean = clean_name(name)
    if clean is None:
        return Result(EXIT_REFUSED, 0, None, section, False, "name")
    if section is not None and section not in SECTIONS:
        return Result(EXIT_FAILED, 0, None, section, False, "section")
    if not os.path.isfile(file_path):
        return Result(EXIT_FAILED, 0, None, section, False, "no-file")
    store = _open_reader(language)
    try:
        if is_taken(clean, language, store):
            return Result(EXIT_REFUSED, 0, clean, section, False, "taken")
    finally:
        if store is not None:
            store.close()
    print(f"Reading {os.path.basename(file_path)}")
    pieces, error = parts_of(file_path, language, method, value, field, overflow)
    chunks = None if error else [p.text for p in pieces]
    if error:
        print(f"Error: {error}")
        return Result(EXIT_FAILED, 0, clean, section, False, "read")
    if not chunks:
        print("Error: no text was found in it, so nothing was saved.")
        return Result(EXIT_FAILED, 0, clean, section, False, "empty")

    data_dir = get_data_path(language)
    processed = os.path.join(data_dir, "Processed")
    final = os.path.join(processed, clean)
    staging = os.path.join(processed, f".{clean}.partial-{os.getpid()}-{int(time.time() * 1000)}")
    print(f"Saving {len(chunks)} parts")
    try:
        if parts and not file_path.lower().endswith(".apkg"):
            rels = save_chunks_grouped(chunks, clean, int(parts), staging, file_path)
        else:
            rels = save_chunks(chunks, clean, staging, file_path, [part_label(p.chapter) for p in pieces])
        if os.path.exists(final):                        # taken since the check: refused, nothing replaced
            raise FileExistsError(final)
        os.rename(staging, final)
    except FileExistsError:
        _drop(staging)
        return Result(EXIT_REFUSED, 0, clean, section, False, "taken")
    except OSError as e:
        _drop(staging)
        print(f"Error: the parts could not be saved ({e}).")
        return Result(EXIT_FAILED, 0, clean, section, False, "save")
    if section is None:
        return Result(EXIT_DONE, len(rels), clean, None, False, None)
    added, note, title = add_to_library(final, clean, rels, language, section, spawn=spawn,
                                        places=_book_origins(file_path, clean, rels, pieces))
    return Result(EXIT_DONE if added else EXIT_PROCESSED_ONLY, len(rels), clean, section, added, note, title)


def _book_origins(file_path, name, rels, pieces):
    """An EPUB's parts' origins, as a folder's look records a book's (`<epub>#<n>`, the EPUB's stats and sha256, each
    part's place in the book): {rel: origin}, so Anki Miner's results can be placed on an extracted book's parts too
    and a folder read later knows the book (SRC-7); None for anything else, or an EPUB that can't be read again."""
    if not file_path.lower().endswith(".epub") or len(rels) != len(pieces):
        return None
    from app import library_store
    try:
        st = os.stat(file_path)
        sha = library_store.sha256_of(file_path)
    except OSError:
        return None
    origin = os.path.abspath(file_path)
    return {rel: {"origin": f"{origin}#{n}", "size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha,
                  "show": name, "episode": n, "chapter": p.chapter}
            for n, (rel, p) in enumerate(zip(rels, pieces), 1)}


def _drop(staging):
    """Our own unfinished folder (never a user's): removed."""
    shutil.rmtree(staging, ignore_errors=True)


def add_to_library(source, name, rels, language, section, spawn=True, places=None):
    """Copy `source` (Processed/<name>) into the content folder, `Library/<name>` (SRC K3: the place is `section`, the
    store's alone), and add its files with one `Store.insert` into `section` -> (added, why not, title): 'store' — the
    store isn't there or can't be written; 'taken' — the name was taken meanwhile; 'already' — every part's bytes are a
    live item's file's already (SRC-7: never a duplicate; `title` names it); 'insert' — the store refused the files,
    their copies sent to the trash. A part already in is never copied (the rest are). The parts always stay in
    Processed. `places` ({rel: origin}, `_book_origins`): each new part's origin record (K21's + Add records)."""
    from app import library_store
    data_dir, user_files_dir = get_data_path(language), get_user_files_path(language)
    store = library_store.open_store(language, data_dir, user_files_dir, role="window")
    if store is None:
        print("The library isn't taking new files right now, so the parts stay in Processed.")
        return False, "store", None
    with store:
        folder = library_store.CONTENT_FOLDER
        dest = os.path.join(data_dir, folder, name)
        if os.path.exists(dest) or _store_holds(store, [f"{folder}/{name}"]):
            return False, "taken", None
        held = store.items_holding([os.path.join(source, *rel.split("/")) for rel in rels])
        held = {os.path.relpath(p, source).replace("\\", "/"): t for p, (_i, t) in held.items()}
        new = [rel for rel in rels if rel not in held]
        if not new:
            title = held[rels[0]]
            print(f"Already in your library: {title} — the parts stay in Processed.")
            return False, "already", title
        started_at = library_store._now()
        try:
            shutil.copytree(source, dest, ignore=lambda where, names: {
                n for n in names if os.path.relpath(os.path.join(where, n), source).replace("\\", "/") in held})
        except OSError as e:
            print(f"The parts couldn't be copied into the library ({e}), so they stay in Processed.")
            _trash_copies(data_dir, dest)
            return False, "insert", None
        files = [os.path.join(dest, *rel.split("/")) for rel in new]
        try:
            origins = {f: places[rel] for f, rel in zip(files, new) if rel in places} if places else None
            change = store.insert(files, section, "show", started_at=started_at, origins=origins)
        except Exception as e:
            print(f"The library didn't take the parts ({e}), so they stay in Processed.")
            _trash_copies(data_dir, dest)
            return False, "insert", None
    if change is None or not change.added:
        print("The library didn't take the parts, so they stay in Processed.")
        _trash_copies(data_dir, dest)
        return False, "insert", None
    if spawn:
        library_store.spawn_maintain(language)             # the copy, written by the helper
    return True, None, None


def _trash_copies(data_dir, dest):
    """The copies made in a section's folder, each to the library's trash (its clock restarted), never deleted; then
    the folders the copy made (`dest`, ours alone), each removed only once empty."""
    from app import library_store
    for where, _dirs, files in os.walk(dest):
        for name in files:
            rel = os.path.relpath(os.path.join(where, name), data_dir).replace("\\", "/")
            try:
                library_store.trash_file(data_dir, rel)
            except OSError:
                pass
    for where, _dirs, _files in sorted(os.walk(dest), key=lambda w: -len(w[0])):
        try:
            os.rmdir(where)                                  # refused while anything is left in it
        except OSError:
            pass


def result_line(result):
    return RESULT_MARK + json.dumps(result._asdict(), ensure_ascii=False)


def parse_result(line):
    """A child's line -> the Result `result_line` wrote, or None."""
    if not line.startswith(RESULT_MARK):
        return None
    try:
        value = json.loads(line[len(RESULT_MARK):])
        return Result(**value)
    except (ValueError, TypeError):
        return None


def main(argv=None):
    """`extract --language L --file F --name N [--section now|soon|goal] [--split length|delimiter] [--value V]
    [--parts P] [--field F]`. Headless, dialog-free; prints what it does, its RESULT line last. Exit 0 done, 3 saved
    in Processed only (the library didn't take the parts), 2 the name refused or taken, 1 failed."""
    import argparse
    parser = argparse.ArgumentParser(description="Extract a file into parts and add them to the library")
    parser.add_argument("--language", default="ja", choices=("ja", "zh"))
    parser.add_argument("--file", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--section", default=None, choices=SECTIONS)
    parser.add_argument("--split", default="length", choices=("length", "delimiter"))
    parser.add_argument("--value", default=str(DEFAULT_LENGTH))
    parser.add_argument("--parts", type=int, default=0)
    parser.add_argument("--field", default=None)
    args = parser.parse_args(argv)
    fault = check_options(args.split, args.value, args.parts != 0, args.parts if args.parts else None)
    if fault:
        print(f"Error: the {fault} is not usable, so nothing was saved.")
        print(result_line(Result(EXIT_FAILED, 0, None, args.section, False, fault)))
        return EXIT_FAILED
    os.makedirs(os.path.join(get_data_path(args.language), "Processed"), exist_ok=True)
    try:
        result = extract(args.file, args.name, args.language, args.section, args.split, args.value, args.parts,
                         args.field, _settings_overflow(), spawn=not os.environ.get(NO_HELPER_ENV))
    except Exception as e:
        print(f"Error: {e}")
        result = Result(EXIT_FAILED, 0, None, args.section, False, "error")
    print(result_line(result))
    return result.code


if __name__ == "__main__":
    sys.exit(main())
