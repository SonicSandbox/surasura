"""Covers from disk (W3.2 S5; the window's spec 01 §1.3 rows 1 and 3, C6; RUNBOOK §1's *Covers* row, §5a IK-7, N4, N5):
a title's art found where its files are, recorded through the window's writer (`moves.Writer.set_cover`) — never the
store on the window's thread, never a network call. Qt-free, Tk-free, pandas-free (the import guard); nothing here
decodes an image for the screen (Q6 does, off the window's thread).

- **`scan(language, works, writer, cancel)`** (a worker, one work at a time; `cancel()` True stops between works) ->
  how many covers it handed to the writer — each once the writer's queue is empty (`Writer.idle`: a drop or a drag
  never waits behind the scan, G1), as a background cover (`auto`: never on the user's Undo stack, B1; never
  journalled). For each work (`works_from(items, works)`: the reader's / the feed's rows):
  1. art beside its files — `cover` · `poster` · `folder` (`.jpg` · `.jpeg` · `.png`, any case, in that order) in the
     folder holding its files, and one level up from a season folder (*Season 2*, *S02*, *第2期*, *第二季*, *シーズン2*);
     never in a tier's own folder (a loose file's art there would be every loose file's). Read where it is:
     `set_cover(work, "file", ref=<its path in the data folder>)`, no `cover_path` (the store's path is 'cache:' or
     'user:' only; `image_path` resolves it);
  2. else an EPUB beside its files (the one its folder's source marker names first): the book's own cover — the OPF
     manifest's `cover-image` item, else its `<meta name="cover">`, else an image item named *cover* — copied ONCE into
     the covers cache (`path_utils.get_covers_cache_path()`; its name a hash of the language, the work, the EPUB's
     path, size and time — never the user's path; a changed book is a new name): `set_cover(work, "file", ref=<the
     EPUB's path>, path="cache:<name>")`.
  **Never over the user's** (`cover_locked`) **nor any cover already set** but the generated one or a downloaded one
  (art on disk first, W3.2 L3 B2) — unless it is this same
  disk source (written again only when its record differs: the EPUB changed, or *Remove downloaded covers* cleared its
  cache path — so disk covers come back by themselves, N5), or a disk cover whose file is gone. A cloud placeholder (a
  OneDrive / iCloud online-only file: Windows' OFFLINE / RECALL_ON_OPEN / RECALL_ON_DATA_ACCESS attributes) is never
  read, so nothing downloads (N4); a broken or non-image file is passed over (the next candidate, else the generated
  cover stays). A store that can't be written reads nothing (E4).
- **`keep_epub_cover(language, work_id, epub_path, writer)`**: the same for a book at its import (Extract's door: the
  EPUB is read where the user keeps it; the library holds only its parts), a background cover too.
- **`keep_user_image(language, work_id, source_path, writer, current=None)`** (IK-7: *Choose an image…*): the user's image
  copied into `User Files/<lang>/covers/` (user data: travels with the library, never emptied with the cache), named by
  the work and the image's own hash, so a new pick is a new file and an Undo still finds the old one; the cover it
  replaces (`current`, the work's `cover_path`) gets a dated backup first (`path_utils.backup_to_trash`); recorded
  `set_cover(work, "user", path="user:<name>", locked=True)`.
- **`image_path(language, work)`**: the file a work's cover record names (cache, user covers, or art beside its files),
  or None (the generated cover). A disk cover read in place changes with its file: the decoder keys on its stat.
"""
import hashlib
import os
import posixpath
import zipfile
from collections import namedtuple
from urllib.parse import unquote
from xml.etree import ElementTree

from app import path_utils
from app.episode_names import season_folder

ART_STEMS = ("cover", "poster", "folder")           # best first (01 §1.3 row 3)
ART_EXTS = (".jpg", ".jpeg", ".png")
EPUB_EXT = ".epub"
MAX_IMAGE = 25 << 20            # bytes: a cover past this isn't one (and is never read whole)
MAX_OPF = 4 << 20               # bytes: an EPUB's package file past this isn't read
USER_COVERS = "covers"          # User Files/<lang>/covers/
_PLACEHOLDER = 0x1000 | 0x40000 | 0x400000      # OFFLINE · RECALL_ON_OPEN · RECALL_ON_DATA_ACCESS (a cloud file)
_REPLACEABLE = (None, "generated")              # a cover the scan may write over (unlocked)
PACE_S = 0.1                    # the scan asks `cancel` this often while it waits for the writer's queue to empty

Work = namedtuple("Work", "id rel_paths cover_source cover_ref cover_path cover_locked")


def works_from(items, works):
    """[Work] from the feed's rows (`Store.read_feed`'s `items` / `works`, the reader's copy): each work with its
    files' paths (data-folder relative), in the order of the list."""
    rels = {}
    for item in sorted(items, key=lambda r: (r.get("ord") or 0, r["id"])):
        if item.get("work_id") is not None and item.get("rel_path"):
            rels.setdefault(item["work_id"], []).append(item["rel_path"])
    out = []
    for w in (works.values() if isinstance(works, dict) else works):
        if w["id"] in rels:
            out.append(Work(w["id"], tuple(rels[w["id"]]), w.get("cover_source"), w.get("cover_ref"),
                            w.get("cover_path"), bool(w.get("cover_locked"))))
    return out


# --- what an image is (no decoder: its header and its end) ------------------------------------------------------- #
def image_ext(data):
    """'.jpg' · '.png' · '.gif' · '.webp' for bytes that hold a whole image of that kind (its header, its size, its
    end), else None: a renamed text file, a truncated download."""
    if not data or len(data) < 24:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg" if _jpeg_size(data) and data.rfind(b"\xff\xd9") > 2 else None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        return ".png" if data[12:16] == b"IHDR" and w and h and b"IEND" in data[-64:] else None
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        return ".gif" if w and h and data.rstrip(b"\x00")[-1:] == b";" else None
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp" if int.from_bytes(data[4:8], "little") + 8 <= len(data) else None
    return None


def _jpeg_size(data):
    """(width, height) from a JPEG's frame header, or None (no frame, a cut stream)."""
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:                          # fill bytes
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2:
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 9 > n:
                return None
            h, w = int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 7:i + 9], "big")
            return (w, h) if w and h else None
        if marker == 0xDA:                          # the scan before any frame: not a picture
            return None
        i += 2 + length
    return None


def on_disk(path):
    """A file really on this computer: there, and not a cloud placeholder (whose read would download it, N4)."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    return os.path.isfile(path) and not (getattr(st, "st_file_attributes", 0) & _PLACEHOLDER)


def _read_image(path):
    """(bytes, ext) of an image file on disk, or None: a placeholder (never read), too big, broken, not an image."""
    if not on_disk(path):
        return None
    try:
        if os.path.getsize(path) > MAX_IMAGE:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    ext = image_ext(data)
    return (data, ext) if ext else None


# --- where a work's art is --------------------------------------------------------------------------------------- #
def _full(data_dir, rel):
    return os.path.join(data_dir, *rel.split("/"))


def _folders(rel_paths):
    """The folders a work's art may be in: each folder holding its files (in the list's order), then the show folder
    above a season folder; never a tier's own folder or the data folder."""
    out = []
    for rel in rel_paths:
        parts = rel.split("/")[:-1]
        if len(parts) < 2:
            continue
        for at in (parts, parts[:-1] if len(parts) >= 3 and season_folder(parts[-1]) is not None else None):
            if at and "/".join(at) not in out:
                out.append("/".join(at))
    return out


def _listing(data_dir, folder):
    try:
        names = sorted(os.listdir(_full(data_dir, folder)))
    except OSError:
        return {}
    by_lower = {}
    for name in names:
        by_lower.setdefault(name.lower(), name)
    return by_lower


def art_beside(data_dir, rel_paths):
    """The art files beside a work's files, best first: data-folder relative paths (by name: not read yet)."""
    out = []
    for folder in _folders(rel_paths):
        names = _listing(data_dir, folder)
        out += [f"{folder}/{names[s + e]}" for s in ART_STEMS for e in ART_EXTS if s + e in names]
    return out


def epubs_beside(data_dir, rel_paths):
    """The EPUBs beside a work's files: the one its folder's source marker names first (the book its parts came from),
    then by name."""
    out = []
    for folder in _folders(rel_paths):
        names = _listing(data_dir, folder)
        books = [n for low, n in sorted(names.items()) if low.endswith(EPUB_EXT)]
        origin = str(path_utils.read_source_marker(_full(data_dir, folder)).get("origin") or "").lower()
        books.sort(key=lambda n: n.lower() != origin)
        out += [f"{folder}/{n}" for n in books]
    return out


def epub_cover(path):
    """An EPUB's own cover, read from the book as it is (the zip's package file, not the whole book): (bytes, ext), or
    None — no cover, a placeholder (never read), a broken book or image."""
    if not on_disk(path):
        return None
    try:
        with zipfile.ZipFile(path) as z:
            name = _cover_member(z)
            if name is None:
                return None
            info = z.getinfo(name)
            if info.file_size > MAX_IMAGE:
                return None
            data = z.read(info)
    except (OSError, KeyError, ValueError, RuntimeError, zipfile.BadZipFile, ElementTree.ParseError, EOFError):
        return None
    ext = image_ext(data)
    return (data, ext) if ext else None


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _cover_member(z):
    """The zip member holding the book's cover: the manifest's `cover-image` item (EPUB 3), its `<meta name="cover">`
    item (EPUB 2), else an image item whose id or file is named *cover*."""
    container = ElementTree.fromstring(z.read("META-INF/container.xml"))
    opf = next((e.get("full-path") for e in container.iter() if _local(e.tag) == "rootfile" and e.get("full-path")),
               None)
    if opf is None or z.getinfo(opf).file_size > MAX_OPF:
        return None
    package = ElementTree.fromstring(z.read(opf))
    items = [e for e in package.iter() if _local(e.tag) == "item" and e.get("href")]
    images = [e for e in items if (e.get("media-type") or "").startswith("image/")]
    meta = next((e.get("content") for e in package.iter()
                 if _local(e.tag) == "meta" and e.get("name") == "cover" and e.get("content")), None)
    pick = (next((e for e in images if "cover-image" in (e.get("properties") or "").split()), None)
            or next((e for e in images if e.get("id") == meta), None)
            or next((e for e in images if "cover" in (e.get("id") or "").lower()
                     or "cover" in posixpath.basename(e.get("href")).lower()), None))
    if pick is None:
        return None
    member = posixpath.normpath(posixpath.join(posixpath.dirname(opf), unquote(pick.get("href"))))
    return None if member.startswith("../") else member


# --- the cache and the user's covers ----------------------------------------------------------------------------- #
def _digest(*parts):
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _cache_stem(language, work_id, source, size, mtime_ns):
    return _digest("epub", language, work_id, source, size, mtime_ns)[:32]


def _cached(stem):
    """The cache's file for `stem` (any image kind), or None."""
    folder = path_utils.get_covers_cache_path()
    for ext in (".jpg", ".png", ".gif", ".webp"):
        if os.path.isfile(os.path.join(folder, stem + ext)):
            return stem + ext
    return None


def _write_whole(path, data):
    """`data` to `path` whole: written beside it as `.part`, then renamed (a crash leaves no half image under its
    name). False when it couldn't be written."""
    part = path + ".part"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(part, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(part, path)
        return True
    except OSError:
        try:
            os.remove(part)
        except OSError:
            pass
        return False


def _named(folder, name):
    """`folder/name` for a bare file name, else None (a record never names a path outside its folder)."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None
    return os.path.join(folder, name)


def image_path(language, work, data_dir=None):
    """The file `work`'s cover record names: 'cache:<name>' in the covers cache, 'user:<name>' in
    `User Files/<lang>/covers/`, or (source 'file', no path) the art beside its files; None for the generated cover."""
    path = work.cover_path or ""
    if path.startswith("cache:"):
        return _named(path_utils.get_covers_cache_path(), path[len("cache:"):])
    if path.startswith("user:"):
        return _named(os.path.join(path_utils.get_user_files_path(language), USER_COVERS), path[len("user:"):])
    ref = work.cover_ref or ""
    if work.cover_source == "file" and ref.lower().endswith(ART_EXTS):
        from app.library_store import library_rel
        rel = library_rel(data_dir or path_utils.get_data_path(language), ref)
        return _full(data_dir or path_utils.get_data_path(language), rel) if rel else None
    return None


_ONLINE = ("anilist", "tmdb", "youtube")


def _may_write(work):
    """Never over the user's lock (the user's own image is always locked): over none, the generated one, a disk cover,
    or a downloaded one — art beside the files comes first, even before a cover found by an id (W3.2 L3 B2, the
    lean D-1 *disk art first*)."""
    return not work.cover_locked and work.cover_source in _REPLACEABLE + ("file",) + _ONLINE


def _replaceable(language, data_dir, work, ref):
    """Whether the scan may write `ref`'s cover over `work`'s (`_may_write`): the generated one, this same disk source,
    or another disk cover whose file is gone."""
    if not _may_write(work):
        return False
    if work.cover_source in _REPLACEABLE + _ONLINE or work.cover_ref == ref:
        return True
    there = image_path(language, work, data_dir)
    return there is None or not os.path.exists(there)   # a placeholder counts as there (never read)


# --- the scan -------------------------------------------------------------------------------------------------- #
def scan(language, works, writer, cancel=None, data_dir=None):
    """(A worker.) Each work's cover from disk, one work at a time -> how many covers it handed to the writer (new or
    changed records; one already recorded isn't counted again)."""
    if not writer.can_write():
        return 0                                    # E4: nothing read for a store that can't take it
    data_dir = data_dir or path_utils.get_data_path(language)
    found = 0
    for work in works:
        if cancel is not None and cancel():
            break
        if not _my_turn(writer, cancel):
            break
        try:
            found += 1 if _scan_one(language, data_dir, work, writer) else 0
        except Exception as e:                      # one title's trouble never stops the rest
            print(f"Covers: work {work.id} skipped: {e!r}")
    return found


def _my_turn(writer, cancel):
    """(S4, G1) The scan's pace: the next cover is handed on only once nothing is queued — its last one landed, and
    whatever the user gave meanwhile (a drop, a drag's hold, a busy store) went first. False when cancelled."""
    while not writer.idle(PACE_S):
        if cancel is not None and cancel():
            return False
    return True


def _scan_one(language, data_dir, work, writer):
    if not _may_write(work):
        return False                                # nothing read for a title the disk can't give a cover
    for ref in art_beside(data_dir, work.rel_paths):
        if (work.cover_source, work.cover_ref, work.cover_path) == ("file", ref, None):
            return False                            # recorded: read where it is, a change shows by itself
        if not _replaceable(language, data_dir, work, ref):
            return False
        if _read_image(_full(data_dir, ref)) is not None:
            return writer.set_cover(work.id, "file", ref=ref, auto=True) is not None
    for ref in epubs_beside(data_dir, work.rel_paths):
        recorded = _epub_record(language, data_dir, work, ref)
        if recorded is False:
            return False
        if recorded is not None:
            return writer.set_cover(work.id, "file", ref=ref, path=recorded, auto=True) is not None
    return False


def _epub_record(language, data_dir, work, ref, path=None):
    """The 'cache:<name>' for the EPUB at `ref` (copied into the cache once), None when it gives no cover, False when
    there's nothing to write (recorded already, or a cover the scan mustn't replace)."""
    full = path or _full(data_dir, ref)
    if not on_disk(full):
        return None
    st = os.stat(full)
    stem = _cache_stem(language, work.id, ref, st.st_size, st.st_mtime_ns)
    have = _cached(stem)
    if have is not None and (work.cover_source, work.cover_ref, work.cover_path) == ("file", ref, "cache:" + have):
        return False
    if not _replaceable(language, data_dir, work, ref):
        return False
    if have is None:
        got = epub_cover(full)
        if got is None:
            return None
        have = stem + got[1]
        if not _write_whole(os.path.join(path_utils.get_covers_cache_path(), have), got[0]):
            return None
    return "cache:" + have


def keep_epub_cover(language, work_id, epub_path, writer, data_dir=None):
    """A book's own cover at its import (Extract's door, once its parts are in the library as `work_id`): copied into
    the cache once and recorded as the scan records it (the store refuses it over the user's lock). The EPUB may be
    anywhere: its record's ref is its path in the data folder when it is there, else its file name. -> True when
    handed to the writer."""
    if not writer.can_write():
        return False
    from app.library_store import library_rel
    data_dir = data_dir or path_utils.get_data_path(language)
    ref = library_rel(data_dir, os.path.abspath(epub_path)) or os.path.basename(epub_path)
    work = Work(work_id, (), None, None, None, False)
    path = _epub_record(language, data_dir, work, ref, path=epub_path)
    return bool(path) and writer.set_cover(work_id, "file", ref=ref, path=path, auto=True) is not None


# --- the user's own image (IK-7) ---------------------------------------------------------------------------------- #
def keep_user_image(language, work_id, source_path, writer, current=None):
    """*Choose an image…*: the image at `source_path` (anywhere; the user picked it) copied into
    `User Files/<lang>/covers/`, named by the work and its own bytes; the user's cover it replaces (`current`: the
    work's `cover_path`, 'user:<name>') backed up dated first (`path_utils.backup_to_trash`: a backup that fails
    records nothing); recorded `set_cover(work_id, "user", path="user:<name>", locked=True)`. -> the record's path, or
    None (not an image, a store that can't be written, a backup or copy that failed)."""
    if not writer.can_write():
        return None
    try:
        with open(source_path, "rb") as f:
            data = f.read(MAX_IMAGE + 1)
    except OSError:
        return None
    return keep_user_bytes(language, work_id, data, writer, current)


def keep_user_bytes(language, work_id, data, writer, current=None, source="user", ref=None):
    """`keep_user_image` for an image already in hand (W3.2 Q7: a candidate picked, a pasted link's image): recorded
    `set_cover(work_id, source, ref=ref, path="user:<name>", locked=True)` — the user's pick, on the Undo stack."""
    ext = image_ext(data) if len(data) <= MAX_IMAGE else None
    if ext is None:
        return None
    folder = os.path.join(path_utils.get_user_files_path(language), USER_COVERS)
    name = f"{_digest('work', language, work_id)[:12]}-{hashlib.sha256(data).hexdigest()[:16]}{ext}"
    target = os.path.join(folder, name)
    old = _named(folder, current[len("user:"):]) if str(current or "").startswith("user:") else None
    if old is not None and os.path.normcase(old) != os.path.normcase(target) and os.path.isfile(old):
        try:
            path_utils.backup_to_trash(old)        # kept where it is too: an Undo of this pick shows it again
        except OSError:
            return None
    if not os.path.isfile(target) and not _write_whole(target, data):
        return None
    if writer.set_cover(work_id, source, ref=ref, path="user:" + name, locked=True) is None:
        return None
    return "user:" + name
