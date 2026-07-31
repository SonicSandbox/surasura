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
# converts and splits them into .txt first.
CONTENT_EXTENSIONS = (".txt", ".md", ".srt", ".ass")


def is_content_file(path):
    """True if `path` is a content file the analyzer will read (extension check only)."""
    return str(path).lower().endswith(CONTENT_EXTENSIONS)


# --- Where a sentence came from (the report's per-sentence source badge) ------------------------ #
# Four kinds the learner can act on differently: a subtitle line belongs to a video, a YouTube line
# to a timestamped video, an EPUB chapter to a book, everything else is plain text.
SOURCE_TYPES = ("subtitle", "youtube", "epub", "text")

# The transcript downloader names its output "<Title> [<11-char video id>].txt", so the id ends the
# stem — but Graduate/Demote append a `_<timestamp>` when resolving a name collision, sometimes more
# than once, e.g. "... [k3GuCkTa3V4]_20260622001222_20260730163200". So allow only that kind of
# trailing noise (separators and digits) after the bracket.
#
# Still anchored rather than a free search: an unanchored 11-char bracket match would also hit
# release-group tags in fansub filenames — "[HorribleSub] ep01" is exactly 11 characters.
_YOUTUBE_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\][\s_()\-.\d]*$")

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
    if str(path).lower().endswith(('.srt', '.ass')):
        return "subtitle"
    if callable(marker_type):
        marker_type = marker_type()
    if marker_type in SOURCE_TYPES:
        return marker_type
    # The '[' test is a cheap gate: this runs once per file on every Generate (thousands of times
    # on a real library) and almost no filename contains a bracket, so most skip the regex entirely.
    name = str(path)
    if "[" in name and _YOUTUBE_ID_RE.search(os.path.splitext(os.path.basename(name))[0]):
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

