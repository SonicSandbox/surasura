import codecs
import hashlib
import os
import re
import sys
import json
import shutil
import threading
import time

def is_frozen():
    """Check if the application is running in a frozen (packaged) environment."""
    return getattr(sys, 'frozen', False)

def get_base_path():
    """
    Get the base directory for retrieving RESOURCES (templates, bundled scripts).
    If SURASURA_TEST_ROOT env var is set, use it (for E2E tests).
    If frozen: return sys._MEIPASS (temp dir where resources are unpacked).
    If source: return the root of the project (one level up from app/).
    """
    if os.environ.get("SURASURA_TEST_ROOT"):
        return os.environ.get("SURASURA_TEST_ROOT")
    if is_frozen():
        return sys._MEIPASS
    else:
        # Assumes this file is in app/path_utils.py, so root is ../
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_user_data_path():
    """
    Get the directory for USER DATA (inputs, outputs, settings).
    If SURASURA_TEST_ROOT env var is set, use it (for E2E tests).
    If frozen: return the directory containing the executable.
    If source: return the root of the project.
    """
    if os.environ.get("SURASURA_TEST_ROOT"):
        return os.environ.get("SURASURA_TEST_ROOT")
    if is_frozen():
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_persistent_user_data_path():
    """
    Get the directory for PERSISTENT USER DATA (e.g. telemetry ID).
    This path should survive application updates/reinstalls.
    Windows: %APPDATA%/SonicSandbox/Surasura/
    Linux/Mac: ~/.local/share/SonicSandbox/Surasura/
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            base = os.path.expanduser("~")
        path = os.path.join(base, "SonicSandbox", "Surasura")
    else:
        # XDG Base Directory Specification fallback
        base = os.environ.get("XDG_DATA_HOME")
        if not base:
             base = os.path.join(os.path.expanduser("~"), ".local", "share")
        path = os.path.join(base, "SonicSandbox", "Surasura")
        
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        
    return path

def _local_data_root():
    """The per-user LOCAL data folder (never roams, never redirected to a network share), one root for every system
    (S1.1 K100; the library store and the command line build on it):
    Windows %LOCALAPPDATA%, macOS ~/Library/Application Support, Linux $XDG_DATA_HOME (else ~/.local/share),
    each + SonicSandbox/Surasura."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "SonicSandbox", "Surasura")

def local_data_root():
    """The local data root (`_local_data_root`): where `installs.json`, the note naming every install's data folder,
    lives. SURASURA_TEST_ROOT moves it to <test root>/local_root; a test that reaches the real one raises."""
    root = os.environ.get("SURASURA_TEST_ROOT")
    if root:
        return os.path.join(root, "local_root")
    if "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError("a test reached the real local data root: set SURASURA_TEST_ROOT")
    return _local_data_root()

def _install_key(install_dir):
    """16 hex characters naming one install, as the library store keys its database (Library_Store_Spec §6.1, §6.4):
    a development checkout and an installed copy never share a folder; a moved install gets a new one."""
    p = os.path.realpath(install_dir).replace("\\", "/")
    if sys.platform == "win32":
        p = os.path.normcase(p)
    elif sys.platform == "darwin":
        import unicodedata
        p = unicodedata.normalize("NFC", p).casefold()
    return hashlib.sha256(p.encode("utf-8")).hexdigest()[:16]

def get_local_data_path():
    """
    Get the per-install LOCAL data folder: the command line's logs, locks and events (P0.3 02-contract §6), and the
    update's lock and state (S1.1).
    Windows: %LOCALAPPDATA%/SonicSandbox/Surasura/<install key>/
    macOS: ~/Library/Application Support/SonicSandbox/Surasura/<install key>/
    Linux: $XDG_DATA_HOME (else ~/.local/share)/SonicSandbox/Surasura/<install key>/
    SURASURA_TEST_ROOT moves it to <test root>/local; a test that reaches the real one raises.
    """
    root = os.environ.get("SURASURA_TEST_ROOT")
    if root:
        path = os.path.join(root, "local")
    elif "PYTEST_CURRENT_TEST" in os.environ:
        raise RuntimeError("a test reached the real local data folder: set SURASURA_TEST_ROOT")
    else:
        path = os.path.join(_local_data_root(), _install_key(get_user_data_path()))
    os.makedirs(path, exist_ok=True)
    return path

def try_lock(path):
    """Take an OS lock on `path`'s byte 0 without waiting (the lock pattern the command line probes) -> the open file,
    which holds the lock until `release_lock` or until this process dies; None when another holder has it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        f = open(path, "a+b")
    except PermissionError:
        return None
    try:
        f.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f

def release_lock(f):
    """Release a `try_lock` lock. Never raises."""
    if f is None:
        return
    try:
        f.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        f.close()
    except OSError:
        pass

INSTALLS_NOTE = "installs.json"

def _install_entry_key(entry):
    try:
        return os.path.normcase(os.path.realpath(entry["data_root"]))
    except (KeyError, TypeError, ValueError):
        return None

def read_install_note(path=None, strict=False):
    """The installs the note names (a list of dicts; [] when there is none or it is unreadable). `strict` (a writer's
    read): [] only when there is none; the list exactly as written, anything else in it kept; OSError when it can't
    be read now, ValueError when it isn't a list — a note the writer must leave as it is."""
    path = path or os.path.join(local_data_root(), INSTALLS_NOTE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        if strict:
            raise
        return []
    if strict:
        if not isinstance(data, list):
            raise ValueError("not a list")
        return data
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []

def _install_languages(data_root):
    return [lang for lang in ("ja", "zh")
            if os.path.isdir(os.path.join(data_root, "User Files", lang))
            or os.path.isdir(os.path.join(data_root, "data", lang))]

def write_install_note(frozen=None):
    """K100: leave a note in the local data root naming this install's data folder, so 3.0's first start finds the
    library. One entry per install, {data_root, exe, version, languages, last_run}; an install writes only its own.
    Written by the frozen app only, at the dashboard's start and just before an update hands over. A unique temp file
    swapped in, then read back: when this install's entry is missing (another install wrote at the same moment), it
    is written again, up to three times; a short lock on `installs.lock` keeps two writers from crossing at all when
    the system allows it. -> True when the note names this install. Never raises: a failure is logged."""
    if not (is_frozen() if frozen is None else frozen):
        return False
    try:
        from app import __version__
        root = local_data_root()
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, INSTALLS_NOTE)
        data_root = get_user_data_path()
        me = {"data_root": data_root, "exe": sys.executable, "version": __version__,
              "languages": _install_languages(data_root),
              "last_run": time.strftime("%Y-%m-%dT%H:%M:%S")}
        key = _install_entry_key(me)
        lock = None
        for _ in range(20):                        # wait at most ~1 s for another writer's lock
            lock = try_lock(os.path.join(root, "installs.lock"))
            if lock is not None:
                break
            time.sleep(0.05)
        try:
            for _attempt in range(3):
                try:
                    current = read_install_note(path, strict=True)
                except ValueError as e:            # damaged or another shape: never replaced by this install alone
                    print(f"Install note: {path} is not a list of installs ({e}); left as it is")
                    return False
                except OSError:                    # another writer's swap, mid-way: read it again
                    time.sleep(0.05)
                    continue
                entries = [e for e in current if _install_entry_key(e) != key] + [me]
                tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
                try:
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(entries, f, ensure_ascii=False, indent=2)
                    os.replace(tmp, path)
                except OSError:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    time.sleep(0.05)
                    continue
                if any(_install_entry_key(e) == key for e in read_install_note(path)):
                    return True
        finally:
            release_lock(lock)
        print(f"Install note: this install's entry did not stay in {path}")
    except Exception as e:
        print(f"Install note: could not write it ({e})")
    return False

def get_resource(path):
    """Resolve a resource path relative to the bundle."""
    return os.path.join(get_base_path(), path)

def get_user_file(path):
    """Resolve a user file path relative to the executable location."""
    return os.path.join(get_user_data_path(), path)

def get_data_path(language=None):
    """
    Get the data directory, optionally for a specific language.
    Process: data/<language>/
    """
    base = get_user_file("data")
    if language:
        return os.path.join(base, language)
    return base

def get_user_files_path(language=None):
    """
    Get the User Files directory, optionally for a specific language.
    Process: User Files/<language>/
    """
    base = get_user_file("User Files")
    if language:
        return os.path.join(base, language)
    return base

def get_icon_path():
    """Returns the path to the application icon."""
    return get_resource(os.path.join("app", "assets", "images", "app_icon.png"))

def get_ico_path():
    """Returns the path to the application .ico file (Windows)."""
    return get_resource(os.path.join("app", "assets", "images", "app_icon.ico"))

SAMPLE_SUBFOLDERS = ["HighPriority", "LowPriority", "GoalContent", "Graduated", "Processed"]

# The content file types the ANALYZER can actually read. Single source of truth for the importer,
# the analyzer's scan, and the background indexer — these three MUST agree: anything the importer
# registers but the analyzer skips becomes a dead row in the library (that's how raw .epub/.html
# ended up tracked-but-never-analyzed). Ebooks and web pages go through the content importer, which
# converts and splits them into .txt first. .ssa is the .ass format's predecessor — the same [Events] the
# analyzer's parse_ass reads (v1.6 promised ASS / SSA; the scan skipped .ssa until 2026-09).
CONTENT_EXTENSIONS = (".txt", ".md", ".srt", ".ass", ".ssa")
SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa")


def is_content_file(path):
    """True if `path` is a content file the analyzer will read (extension check only)."""
    return str(path).lower().endswith(CONTENT_EXTENSIONS)


# --- Where a sentence came from (the report's per-sentence source badge) ------------------------ #
# Kinds the learner can act on differently: a subtitle line belongs to a video, a YouTube line to a
# timestamped video, a bilibili.tv line to an episode page, an EPUB chapter to a book, everything
# else is plain text.
SOURCE_TYPES = ("subtitle", "youtube", "bilibili", "epub", "text")

# The transcript downloader names its output "<Title> [<11-char video id>].txt", so the id ends the
# stem — but Graduate/Demote append a `_<timestamp>` when resolving a name collision, sometimes more
# than once, e.g. "... [k3GuCkTa3V4]_20260622001222_20260730163200". So allow only that kind of
# trailing noise (separators and digits) after the bracket.
#
# Still anchored rather than a free search: an unanchored 11-char bracket match would also hit
# release-group tags in fansub filenames — "[HorribleSub] ep01" is exactly 11 characters.
_YOUTUBE_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\][\s_()\-.\d]*$")

# bilibili.tv transcripts end "[bilibili-<episode id>]", same trailing-noise allowance. The ids are
# bare digits, and a bare bracketed number is far too common to trust ("[20240101]", fansub CRCs),
# hence the explicit prefix the downloader writes.
_BILIBILI_ID_RE = re.compile(r"\[bilibili-(\d+)\][\s_()\-.\d]*$")

# A producer that KNOWS what it made (Extract, for instance) drops this beside its output. Needed
# because an EPUB chapter and an ordinary note are both plain .txt — nothing in the filename tells
# them apart, so somebody has to record it at creation time.
SOURCE_MARKER = ".surasura_source.json"

# Per-FILE sidecar carrying cue timings, written beside a transcript ('foo.txt' -> 'foo.surasura.json').
# Defined here rather than in the optional YouTube module so the core can read one without importing
# it — the app must run identically when that module is absent.
SIDECAR_SUFFIX = ".surasura.json"


def read_source_marker(directory):
    """The producer's marker dict for a directory, or {} when there isn't one."""
    try:
        with open(os.path.join(directory, SOURCE_MARKER), 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_source_marker(directory, source_type, origin=None):
    """Record what produced the files in `directory`. Best-effort — never fatal."""
    try:
        os.makedirs(directory, exist_ok=True)
        payload = {"source_type": source_type}
        if origin:
            payload["origin"] = origin
        with open(os.path.join(directory, SOURCE_MARKER), 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def infer_source_type(path, declared=None, marker_type=None):
    """Classify a content file for the report's source badge.

    Precedence: `declared` (the manifest's `source_type`, stamped when the file was added) beats the
    extension, which beats `marker_type` (the producer marker), which beats the filename guess.

    `marker_type` may be a zero-arg CALLABLE, in which case it is only invoked when the answer
    actually depends on it — reading a marker costs a filesystem probe per directory, and the
    extension settles most files without one.

    No I/O of its own. Unknown/absent everything falls back to "text", never an error.
    """
    if declared in SOURCE_TYPES:
        return declared
    if str(path).lower().endswith(SUBTITLE_EXTENSIONS):
        return "subtitle"
    if callable(marker_type):
        marker_type = marker_type()
    if marker_type in SOURCE_TYPES:
        return marker_type
    # The '[' test is a cheap gate: this runs once per file on every Generate (thousands of times
    # on a real library) and almost no filename contains a bracket, so most skip the regex entirely.
    name = str(path)
    if "[" in name:
        stem = os.path.splitext(os.path.basename(name))[0]
        if _BILIBILI_ID_RE.search(stem):
            return "bilibili"
        if _YOUTUBE_ID_RE.search(stem):
            return "youtube"
    return "text"


def ensure_data_setup(language=None):
    """
    Ensures the data folders exist. If language is provided, sets up data/<language>/ and
    User Files/<language>/.

    NOTE: this NO LONGER copies sample content. Samples are seeded ONLY on explicit user request
    (the "Test with samples" action → `seed_samples`), so a new user starts with a genuinely empty
    library and the empty-state onboarding can appear. (Previously this auto-copied samples into any
    empty tier — and re-seeded a tier the user later emptied.)
    """
    # 1. Determine Paths
    data_path = get_data_path(language)
    user_files_dir = get_user_files_path(language)

    subfolders = SAMPLE_SUBFOLDERS + [".trash"]

    # 2. Ensure base data folder exists
    if not os.path.exists(data_path):
        os.makedirs(data_path, exist_ok=True)

    # 3. Create the subfolders (empty — no sample copy).
    for folder in subfolders:
        target_dir = os.path.join(data_path, folder)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)

    # 4. Ensure User Files folder exists
    if not os.path.exists(user_files_dir):
        os.makedirs(user_files_dir, exist_ok=True)
        
    # 5. Create Blacklist/IgnoreList/GraduatedList if they don't exist
    for list_name in ["Blacklist.txt", "IgnoreList.txt", "GraduatedList.txt"]:
        list_path = os.path.join(user_files_dir, list_name)
        if not os.path.exists(list_path):
            try:
                with open(list_path, "w", encoding="utf-8") as f:
                    if list_name == "Blacklist.txt":
                        f.write("# Global Blacklist\n" if not language else f"# {language} Blacklist\n")
                    elif list_name == "GraduatedList.txt":
                         f.write("# Words from graduated content (automatically added)\n")
                    else:
                        f.write("# Add words to ignore here (one per line)\n")
            except Exception as e:
                print(f"Warning: Could not create {list_name}: {e}")
                
    # 6. Async Trash Cleanup
    trash_dir = os.path.join(data_path, ".trash")
    cleanup_trash_async(trash_dir)


def seed_samples(language=None):
    """Copy bundled sample immersion content into the (empty) tier folders for `language`.

    Called ONLY on explicit user request (the Content Manager's "Test with samples" action) — samples
    are NOT auto-seeded on setup, so a new user starts with a genuinely empty library. Copies into a
    tier only when that tier is empty (so it never clobbers real content). Returns the number of
    top-level items copied. Sample content ships under `samples/<lang>/{HighPriority,LowPriority}`.
    """
    data_path = get_data_path(language)
    samples_path = get_resource("samples")
    sample_lang = language if language else 'ja'
    copied = 0
    for folder in SAMPLE_SUBFOLDERS:
        target_dir = os.path.join(data_path, folder)
        os.makedirs(target_dir, exist_ok=True)
        source_dir = os.path.join(samples_path, sample_lang, folder)
        if os.path.isdir(source_dir) and not os.listdir(target_dir):
            for item in os.listdir(source_dir):
                s = os.path.join(source_dir, item)
                d = os.path.join(target_dir, item)
                if os.path.isfile(s):
                    shutil.copy2(s, d); copied += 1
                elif os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True); copied += 1
    return copied

def cleanup_trash_async(trash_path):
    """Prunes files in the given trash directory that are older than 30 days asynchronously."""
    def run_cleanup():
        try:
            if not os.path.exists(trash_path):
                return
            now = time.time()
            cutoff = now - (30 * 24 * 60 * 60) # 30 days
            for root, dirs, files in os.walk(trash_path, topdown=False):
                for name in files:
                    filepath = os.path.join(root, name)
                    try:
                        if os.path.getmtime(filepath) < cutoff:
                            os.remove(filepath)
                    except: pass
                for name in dirs:
                    dirpath = os.path.join(root, name)
                    try:
                        if not os.listdir(dirpath):
                            os.rmdir(dirpath)
                    except: pass
        except Exception as e:
            print(f"Trash cleanup error: {e}")

    threading.Thread(target=run_cleanup, daemon=True).start()


def restart_trash_clock(path):
    """Start the 30-day purge countdown for something just moved into a `.trash` folder.

    cleanup_trash_async() prunes by each file's MODIFIED time, and a move keeps the time the file
    already had — so a file last edited over a month ago was purged at the very next
    ensure_data_setup() (a Generate, opening the Content Manager), leaving no time to undo a removal.
    Stamping it (every file, for a folder) with the current time makes the 30 days count from the
    removal. Best-effort: a file that can't be stamped just keeps its old time."""
    targets = [path]
    if os.path.isdir(path):
        targets = [os.path.join(root, name) for root, _dirs, files in os.walk(path) for name in files]
    for target in targets:
        try:
            os.utime(target)
        except OSError:
            pass


def backup_to_trash(path, move=False):
    """Keep a dated copy of a user-data file in the `.trash` folder beside it, before it is replaced.

    `KnownWord.json` -> `.trash/KnownWord.<YYYYmmdd-HHMMSS>.json` (`-1`, `-2`, ... if that name is
    taken) — the naming the Anki sync's Replace already uses (app/anki_sync.py), so every backup of
    a file sits together and sorts by date. Unlike `data/<lang>/.trash`, this folder is never purged.

    A copy is verified byte-for-byte; `move=True` moves the file instead (for one that is being set
    aside, not overwritten). Returns the backup path, or None when there is no file. Raises OSError
    when the backup can't be made — the caller must then leave the original alone."""
    if not os.path.isfile(path):
        return None
    trash = os.path.join(os.path.dirname(path), ".trash")
    os.makedirs(trash, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{stem}.{stamp}{ext}"
    n = 1
    while os.path.exists(os.path.join(trash, name)):
        name = f"{stem}.{stamp}-{n}{ext}"
        n += 1
    dst = os.path.join(trash, name)
    if move:
        os.replace(path, dst)
        return dst
    shutil.copyfile(path, dst)
    with open(path, "rb") as a, open(dst, "rb") as b:
        if a.read() != b.read():
            raise OSError("the backup copy did not match the original")
    return dst


# --- Reading a file the user supplies or can edit ------------------------------------------------ #
# A file's encoding is a property of the FILE, not of its text. A BOM
# names it: UTF-8's (Notepad's "UTF-8 with BOM", Excel's "CSV UTF-8"), UTF-16's (Notepad's "Unicode") or
# UTF-32's (pysrt honoured it, so a subtitle keeps reading). Without one, strict UTF-8, which a file in
# another encoding practically never passes. Failing that, the encodings the language's own Windows saves
# in, each tried strictly so a wrong guess fails instead of dropping bytes: CP932 (Shift_JIS as Windows
# writes it) for Japanese; GB18030 (GBK's superset), then Big5 as Windows writes it (cp950 — with the
# ETEN characters 恒 裏 碁 that plain Big5 refuses) for Chinese. The first that reads the file as standard
# characters wins: a reading holding a Private Use character (U+E000–F8FF — no standard assigns one) is
# not taken. That is what "strictly" leaves loose: GB18030 reads almost any byte pair, Big5's included,
# and every Big5 comma and full stop (，。) comes out Private Use; cp932 gives the bytes it has no
# character for (0xA0, 0xFD–0xFF) Private Use ones, so a damaged UTF-8 file isn't taken for Shift_JIS.
# Before this, CP932 / UTF-16 / GBK files contributed nothing, silently, and a KnownWord.json or word
# list saved with a BOM or as UTF-16 stopped Generate.
#
# What the app writes itself (settings, results, caches) is UTF-8 and read as it always was.
LEGACY_ENCODINGS = {"ja": ("cp932",), "zh": ("gb18030", "cp950")}
_PRIVATE_USE = re.compile("[\ue000-\uf8ff]")
# UTF-32 LE's BOM begins with UTF-16 LE's, so it is looked for first.
_BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
         (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"))


def _bom_encoding(raw):
    """The encoding the bytes' BOM names, or None."""
    return next((encoding for bom, encoding in _BOMS if raw.startswith(bom)), None)


def _decoding(raw, language):
    """(text, encoding): the bytes' text by the rule above and the encoding that read it — or (None, None) when no
    encoding reads them whole."""
    def strictly(encoding):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            return None
    bom = _bom_encoding(raw)
    if bom:
        text = strictly(bom)
        return (text, bom) if text is not None else (None, None)
    text = strictly("utf-8")
    if text is not None:
        return text, "utf-8"
    for encoding in LEGACY_ENCODINGS.get(language, ()):
        text = strictly(encoding)
        if text is not None and not _PRIVATE_USE.search(text):
            return text, encoding
    return None, None


def _decode(raw, language):
    """The bytes' text by the rule above, or None when no encoding reads them whole."""
    return _decoding(raw, language)[0]


def read_text(path, language=None, errors="replace"):
    """The text of a file the user supplies or can edit — content, KnownWord.json, the word lists, a
    frequency list — decoded by the rule above for `language` ("ja" / "zh"; None tries no legacy
    encoding), line ends read as open() reads them (CRLF and a lone CR are "\\n").

    A file no encoding reads whole (damaged) is read as its BOM, else UTF-8, says, every bad sequence
    marked U+FFFD — never dropped — with a warning. errors="strict" raises UnicodeDecodeError instead:
    for a caller that writes the file back, where nothing may be lost to a guess."""
    with open(path, "rb") as f:
        raw = f.read()
    text = _decode(raw, language)
    if text is None:
        text = raw.decode(_bom_encoding(raw) or "utf-8", errors)
        try:
            print(f"Warning: {os.path.basename(path)} is damaged or in an unknown encoding; "
                  f"its unreadable bytes are marked U+FFFD.")
        except UnicodeEncodeError:
            print("Warning: a file is damaged or in an unknown encoding; its unreadable bytes are marked U+FFFD.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


# Adding to such a file is done in its own encoding — the one read_text reads it in — and with its own line ends:
# UTF-8 added to a Shift_JIS list (what the Content Manager's graduation did to GraduatedList.txt) made a file no
# encoding reads whole, which read_text then reads as UTF-8: every word the list held before came out U+FFFD. A
# BOM's encoding goes on without a second BOM.
_CONTINUED = ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be"),
              (codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be"))


def append_text(path, text, language=None):
    """Add `text` to the end of a file the user can edit (a word list) in the file's own encoding (§ above); a new
    or empty file, or one no encoding reads whole, gets UTF-8. When the file's encoding has no character for part
    of `text` (𠮟 for a Shift_JIS list), the file is rewritten in UTF-8 with `text` added — a dated copy kept first
    (backup_to_trash; OSError when it can't be made, and the file is left alone) — so no word is lost."""
    raw = b""
    if os.path.isfile(path):
        with open(path, "rb") as f:
            raw = f.read()
    old, encoding = _decoding(raw, language) if raw else ("", "utf-8")
    encoding = next((bomless for bom, bomless in _CONTINUED if raw.startswith(bom)), encoding or "utf-8")
    if old and "\r\n" in old:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    try:
        data = text.encode(encoding)
    except UnicodeEncodeError:
        backup_to_trash(path)
        with open(path + ".tmp", "w", encoding="utf-8", newline="") as f:
            f.write(old + text)
        os.replace(path + ".tmp", path)
        return
    with open(path, "ab") as f:
        f.write(data)


def build_subprocess_env(frozen=None):
    """Environment for a child process launched by run_command_async (analyzer / importers / indexer).

    Forces the child's stdio to UTF-8 so the parent's strict-UTF-8 stdout capture never chokes on
    locale-encoded bytes: a source-mode script otherwise encodes stdout in the OS locale (cp1252 on
    Windows), turning e.g. an em-dash into byte 0x97 and crashing the capture with "invalid start
    byte". Also puts the project root on PYTHONPATH in source mode so `from app import ...` resolves.

    Drops an inherited QT_QPA_PLATFORM (the window's spec 04 §4.1): a window started under a test harness's
    `offscreen` platform would otherwise hand it to a child, and a child that opens a window draws it to nothing.
    """
    if frozen is None:
        frozen = is_frozen()
    env = os.environ.copy()
    env.pop("QT_QPA_PLATFORM", None)
    env["PYTHONIOENCODING"] = "utf-8"
    if not frozen:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = (project_root + os.pathsep + env["PYTHONPATH"]
                             if "PYTHONPATH" in env else project_root)
    return env
