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
import json
import math
import os
import re
import shutil
import sys
import time
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
NAME_LIMIT = 120                                # characters: a folder name, and its parts' names after it

_RESERVED = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)

Name = namedtuple("Name", "name taken proposal")
Result = namedtuple("Result", "code parts folder section in_library note")


# --- the name ------------------------------------------------------------------------------------------------- #
def clean_name(name):
    """The output name as a safe folder name, or None when nothing safe is left: separators and reserved characters
    become "_", the ends lose spaces and dots, and a name of dots alone or a device name (CON, NUL, …) is refused."""
    name = _RESERVED.sub("_", str(name or "")).strip().rstrip(". ").strip()
    if not name or set(name) <= {".", "_", " "} or _DEVICE.match(name):
        return None
    return name[:NAME_LIMIT].rstrip(". ") or None


def _folders(language):
    """The folders a name may not be taken in: Processed, and each section's folder (Finished's too)."""
    from app import library_store
    data_dir = get_data_path(language)
    names = ["Processed"] + [library_store.FOLDER_OF_TIER[t] for t in SECTIONS] + [library_store.GRADUATED_FOLDER]
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
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub
    except ImportError as e:
        return None, f"Failed to read EPUB: {e}"
    try:
        book = epub.read_epub(epub_path)
    except Exception as e:
        return None, f"Failed to read EPUB: {e}"

    full_text_list = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        try:
            content = item.get_content()
            soup = BeautifulSoup(content, 'html.parser')

            for rt in soup.find_all('rt'): rt.decompose()
            for rp in soup.find_all('rp'): rp.decompose()
            for br in soup.find_all('br'): br.replace_with('\n')

            block_tags = ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'li']
            for tag in soup.find_all(block_tags): tag.append('\n')

            text = soup.get_text(separator='')
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            cleaned_text = "\n".join(lines)
            if cleaned_text:
                full_text_list.append(cleaned_text)
        except Exception as e:
            print(f"Warning: Failed to parse item {item.get_name()}: {e}")

    return "\n\n".join(full_text_list), None


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
    if limit < 1:
        raise ValueError("the length must be at least 1")
    chunks = []
    pos = 0
    total_len = len(text)
    boundaries = "。？！.?! \n"
    closing_marks = "」』)\"']}"

    while pos < total_len:
        target_end = pos + limit
        if target_end >= total_len:
            chunks.append(text[pos:].strip())
            break
        found_boundary = -1
        search_end = min(target_end + overflow, total_len)
        for i in range(target_end, search_end):
            if text[i] in boundaries:
                actual_end = i + 1
                while actual_end < total_len and text[actual_end] in closing_marks:
                    actual_end += 1
                found_boundary = actual_end
                break
        end_pos = found_boundary if found_boundary != -1 else search_end
        chunks.append(text[pos:end_pos].strip())
        pos = end_pos
    return [c for c in chunks if c]


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


def save_chunks(chunks, base_name, folder, source=None):
    """`folder/<base>.txt` (one part) or `folder/<base>_NN.txt` -> the files' paths relative to `folder`, in order."""
    os.makedirs(folder, exist_ok=True)
    _mark(folder, source)
    written = []
    for i, chunk in enumerate(chunks, 1):
        filename = f"{base_name}_{i:02d}.txt" if len(chunks) > 1 else f"{base_name}.txt"
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


def chunks_of(file_path, language, method="length", value=DEFAULT_LENGTH, field=None, overflow=None):
    """The parts of the file at `file_path` -> (parts, None) or (None, why). A deck gives its field's text as one
    part; anything else is read and split by length or by the delimiter pattern."""
    if file_path.lower().endswith(".apkg"):
        if not field:
            return None, "Choose the deck's field to extract."
        text = deck_text(file_path, field)
        return ([text] if text.strip() else []), None
    text, error = extract_text_from_file(file_path, language)
    if error:
        return None, error
    if method == "delimiter":
        return split_by_delimiter(text or "", value), None
    return split_by_length(text or "", int(value), DEFAULT_OVERFLOW if overflow is None else overflow), None


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
    chunks, error = chunks_of(file_path, language, method, value, field, overflow)
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
            rels = save_chunks(chunks, clean, staging, file_path)
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
    added, note = add_to_library(final, clean, rels, language, section, spawn=spawn)
    return Result(EXIT_DONE if added else EXIT_PROCESSED_ONLY, len(rels), clean, section, added, note)


def _drop(staging):
    """Our own unfinished folder (never a user's): removed."""
    shutil.rmtree(staging, ignore_errors=True)


def add_to_library(source, name, rels, language, section, spawn=True):
    """Copy `source` (Processed/<name>) into `section`'s folder and add its files with one `Store.insert` -> (added,
    why not: 'store' — the store isn't there or can't be written; 'taken' — the name was taken meanwhile; 'insert' —
    the store refused the files, their copies sent to the trash). The parts always stay in Processed."""
    from app import library_store
    data_dir, user_files_dir = get_data_path(language), get_user_files_path(language)
    store = library_store.open_store(language, data_dir, user_files_dir, role="window")
    if store is None:
        print("The library isn't taking new files right now, so the parts stay in Processed.")
        return False, "store"
    with store:
        folder = library_store.FOLDER_OF_TIER[section]
        dest = os.path.join(data_dir, folder, name)
        if os.path.exists(dest) or _store_holds(store, [f"{folder}/{name}"]):
            return False, "taken"
        started_at = library_store._now()
        try:
            shutil.copytree(source, dest)
        except OSError as e:
            print(f"The parts couldn't be copied into the library ({e}), so they stay in Processed.")
            _trash_copies(data_dir, dest)
            return False, "insert"
        files = [os.path.join(dest, *rel.split("/")) for rel in rels]
        try:
            change = store.insert(files, section, "show", started_at=started_at)
        except Exception as e:
            print(f"The library didn't take the parts ({e}), so they stay in Processed.")
            _trash_copies(data_dir, dest)
            return False, "insert"
    if change is None or not change.added:
        return False, "insert"
    if spawn:
        library_store.spawn_maintain(language)             # the copy, written by the helper
    return True, None


def _trash_copies(data_dir, dest):
    """The copies made in a section's folder, each to the library's trash (its clock restarted), never deleted."""
    from app import library_store
    for where, _dirs, files in os.walk(dest):
        for name in files:
            rel = os.path.relpath(os.path.join(where, name), data_dir).replace("\\", "/")
            try:
                library_store.trash_file(data_dir, rel)
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
                         args.field, _settings_overflow())
    except Exception as e:
        print(f"Error: {e}")
        result = Result(EXIT_FAILED, 0, None, args.section, False, "error")
    print(result_line(result))
    return result.code


if __name__ == "__main__":
    sys.exit(main())
