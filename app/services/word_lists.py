"""The Ignore list and the Blacklist, read and changed (W3.3 P10; the window's spec 01 §1.2 n16, 08 decision 41).

The lists 2.x reads, one language at a time: `User Files/<lang>/IgnoreList.txt` and `Blacklist.txt` — every run reads
both as ignored words (`analyzer.load_ignore_set`), each line a word, `#` comments and blank lines skipped. 2.x never
wrote them (the dashboard opened IgnoreList.txt in the user's editor); the user edits them by hand, so a write here
keeps every line it doesn't change, byte for byte.

- `read(kind, language)` -> a `Listing`: the list's words as its lines hold them, in order. The Ignore list also shows
  KnownWord.json's IGNORED entries (Migaku's status: `source="known"`) as written, and, with Ignore names on, the
  library's names (`source="names"`: read-only — turning Ignore names off counts them again).
- `add(kind, language, words)` -> a `Change`: each word not on the list yet goes on a line of its own at the end (an
  add always writes the list file: KnownWord.json stays the sync's, decision 41).
- `remove(kind, language, words, source="list")` -> a `Change`: every line naming exactly that word (as the line holds
  it, trimmed) goes; `source="known"` takes KnownWord.json's IGNORED entries of that dictForm out instead.
- `words_in(text, language, kind)` -> the candidate words of pasted text, read by the library's own tokenizer
  (`analyzer.JapaneseTokenizer`: `join_affixes` with the library's tables; `ChineseTokenizer`: `chinese_cut` /
  `chinese_word`), each a `Candidate(word, spelling, status)`: `word` is the lemma (the identity everywhere, what a
  line names), `spelling` the text's dictionary form to show. Loads the tokenizer: the child's (below).
- `find_words(text, language, kind, paste)` -> `words_in`'s answer, worked out in a child process of its own (n16: "a
  worker process"; FX-wl S2): `app_entry.py word-lists-find --headless` (`find_main`), one per paste, the text on its
  stdin and the words back as JSON on its stdout — so the window's process never loads the tokenizer, never holds
  Python's lock for it, and never changes its own `analyzer.LOGIC` (the child reads the settings itself). Blocks:
  call it on a worker. `paste.cancel()` (any thread) kills the child; a child that fails, times out
  (`FIND_TIMEOUT`) or is cancelled raises `FindFailed` (`Cancelled`): nothing found, nothing changed.

Every write, the rules a user's list could be damaged by otherwise (CLAUDE.md §4):
  * KnownWord.json's lock (`known-words-<lang>`, `anki_sync.hold_known_words`) is held for the read-modify-write — the
    one the signed spec names (P1.2) for these files; 2.x had no writer of the two lists to take one;
  * the file is read again under the lock (it may have been edited by hand since the window read it);
  * a file no encoding reads whole (`path_utils.read_text`'s rule, strictly) is never written: the `Change` says why;
  * the file is written back in the encoding it was read in, its BOM and its line ends kept; a word that encoding has
    no character for (𠮟 in a Shift_JIS list) rewrites the file in UTF-8 so no word is lost — 2.x's rule for a list it
    adds to (`path_utils.append_text`);
  * one dated, byte-verified copy per file per session (`path_utils.backup_to_trash`) before its first write; a backup
    that fails writes nothing;
  * the write is atomic (temp file, fsync, `os.replace`: `anki_sync._atomic_write_bytes`); nothing changed, nothing
    written.
Qt-free and Tk-free: the window calls every function on a worker.
"""
import json
import os
import re
import subprocess
import sys
import threading
from collections import namedtuple
from dataclasses import dataclass, field

from app import anki_sync, path_utils

KINDS = {"ignore": "IgnoreList.txt", "blacklist": "Blacklist.txt"}
# The first line of a list made here, as `path_utils.ensure_data_setup` makes it.
HEADERS = {"ignore": "# Add words to ignore here (one per line)", "blacklist": "# {language} Blacklist"}
VERB = "Word lists"
FIND_VERB = "word-lists-find"       # app_entry.py's verb for the paste's child
FIND_TIMEOUT = 120.0                # s a paste's child may take before it is stopped (the arrivals worker's STUCK)

Entry = namedtuple("Entry", "word source")                # source: "list" · "known" (KnownWord.json) · "names"
Candidate = namedtuple("Candidate", "word spelling status")   # status: "new" · "listed" · "known" · "left_out"


@dataclass
class Listing:
    entries: list = field(default_factory=list)
    error: "str | None" = None      # a plain sentence: the list can't be read whole, so it can't be changed here


@dataclass
class Change:
    done: list = field(default_factory=list)       # the words added / removed
    skipped: list = field(default_factory=list)    # added: already on the list; removed: not there
    backup: "str | None" = None                    # this write's dated copy (only the session's first write makes one)
    error: "str | None" = None                     # a plain sentence: nothing was changed
    busy: bool = False                             # another program held the lock


class Unreadable(Exception):
    """A file no encoding reads whole: never written."""


_BACKED_UP = set()                  # the files given their dated copy this session (one per file per session)
_BACKUP_LOCK = threading.Lock()


def list_path(kind, language):
    return os.path.join(path_utils.get_user_files_path(language), KINDS[kind])


# --- one line's word, as the run reads it -------------------------------------------------------------------- #
_TERM_CUT_RE = re.compile(r"[-\s]")             # analyzer._TERM_CUT_RE


def _entry(line):
    """The word a line names as written (trimmed), or None for a blank or `#` line."""
    word = line.strip()
    return word if word and not word.startswith("#") else None


def _term(word, language):
    """`word` as the run compares it: Japanese cut at the first hyphen or space (`analyzer._sanitize_term`)."""
    word = word.strip()
    if language == "ja":
        cut = _TERM_CUT_RE.search(word)
        word = word if cut is None else word[:cut.start()]
    return word


# --- the file, line by line ---------------------------------------------------------------------------------- #
_LINE_TEXT = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_LINE_BYTES = re.compile(rb"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")
_ASCII_SAFE = ("utf-8", "cp932", "gb18030", "cp950")   # a line end's byte never sits inside a character in these


class _File:
    """A list file as read for a write: its BOM, the encoding its text is written in and its lines, each kept as the
    bytes it was read as (so a line nobody changes is written back as it was)."""

    def __init__(self, path, language):
        self.path = path
        raw = b""
        if os.path.isfile(path):
            with open(path, "rb") as f:
                raw = f.read()
        self.exists = os.path.isfile(path)
        text, encoding = path_utils._decoding(raw, language) if raw else ("", "utf-8")
        if text is None:
            raise Unreadable(os.path.basename(path))
        self.bom = next((bom for bom, _e in path_utils._CONTINUED if raw.startswith(bom)), b"")
        self.encoding = next((e for bom, e in path_utils._CONTINUED if raw.startswith(bom)), encoding)
        body = raw[len(self.bom):]
        if self.encoding in _ASCII_SAFE:
            self.lines = [(seg.decode(self.encoding), seg) for seg in _LINE_BYTES.findall(body)]
        else:                                       # UTF-16 / 32: split the text, each line encoded as it was read
            self.lines = [(seg, seg.encode(self.encoding)) for seg in _LINE_TEXT.findall(text)]
        self.eol = "\r\n" if any(t.endswith("\r\n") for t, _b in self.lines) else "\n"

    def words(self):
        return [w for w in (_entry(t) for t, _b in self.lines) if w is not None]

    def remove(self, words):
        """Drop every line naming one of `words` -> the words found."""
        found, kept = [], []
        for text, raw in self.lines:
            word = _entry(text)
            if word is not None and word in words:
                if word not in found:
                    found.append(word)
            else:
                kept.append((text, raw))
        self.lines = kept
        return found

    def add(self, words):
        """`words` on lines of their own at the end (in the file's encoding, or the whole file in UTF-8 when it has
        no character for one of them)."""
        if self.lines and not self.lines[-1][0].endswith(("\n", "\r")):
            text, raw = self.lines[-1]
            self.lines[-1] = (text + self.eol, raw + self.eol.encode(self.encoding))
        for word in words:
            line = word + self.eol
            try:
                self.lines.append((line, line.encode(self.encoding)))
            except UnicodeEncodeError:              # 2.x's rule (path_utils.append_text): UTF-8, no word lost
                self.bom, self.encoding = b"", "utf-8"
                self.lines = [(t, t.encode("utf-8")) for t, _b in self.lines] + [(line, line.encode("utf-8"))]

    def data(self):
        return self.bom + b"".join(raw for _t, raw in self.lines)


def _backup_once(path):
    """The session's dated copy of `path`, before its first write -> the copy's path, or None (already made, or no
    file). OSError when it can't be made: the caller writes nothing."""
    key = os.path.normcase(os.path.abspath(path))
    with _BACKUP_LOCK:
        if key in _BACKED_UP:
            return None
        made = path_utils.backup_to_trash(path)
        _BACKED_UP.add(key)
        return made


def _held(language, change, work):
    """`work()` under KnownWord.json's lock -> `change` (its `error` / `busy` set when the lock was refused)."""
    held, refused = anki_sync.hold_known_words(language, VERB)
    if refused is not None:
        change.error, change.busy = refused[0], True
        return change
    try:
        work()
    finally:
        if held is not None:
            held.release()
    return change


def _unreadable(name):
    return (f"{name} can't be read in any encoding Surasura knows, so it was left as it is: "
            f"open it in a text editor and save it as UTF-8.")


# --- reading ------------------------------------------------------------------------------------------------ #
def read(kind, language):
    """The list's words for the window (see the module docstring) -> a `Listing`."""
    listing = Listing()
    path = list_path(kind, language)
    try:
        listing.entries = [Entry(w, "list") for w in _File(path, language).words()]
    except Unreadable:
        listing.error = _unreadable(KINDS[kind])
        try:                                        # shown, never changed: read as the run reads it
            listing.entries = [Entry(w, "list") for w in
                               (_entry(t) for t in path_utils.read_text(path, language).splitlines()) if w]
        except OSError:
            pass
    if kind == "ignore":
        listing.entries += [Entry(w, "known") for w in _known_ignored(language)]
        listing.entries += [Entry(w, "names") for w in _names(language)]
    return listing


def _known_ignored(language):
    """KnownWord.json's IGNORED dictForms, as written, in order, each once ([] when it can't be read)."""
    try:
        _data, words = anki_sync._read_known_file(language)
    except anki_sync._KnownFileError:
        return []
    out = []
    for e in words or []:
        word = str(e.get("dictForm") or "").strip() if isinstance(e, dict) else ""
        if word and e.get("knownStatus") == "IGNORED" and word not in out:
            out.append(word)
    return out


def _names(language):
    try:
        from app import token_index
        return list(dict.fromkeys(token_index.ignored_names(language)))
    except Exception:
        return []


# --- writing ------------------------------------------------------------------------------------------------ #
def add(kind, language, words):
    """Put `words` on the list (see the module docstring) -> a `Change`."""
    change = Change()
    path = list_path(kind, language)

    def work():
        try:
            f = _File(path, language)
        except Unreadable:
            change.error = _unreadable(KINDS[kind])
            return
        have = {_term(w, language) for w in f.words()}
        new, given = [], set()
        for word in words:
            word = str(word or "").strip()
            if not word or word.startswith("#") or _term(word, language) in given:
                continue                            # nothing, a comment, or given twice: once is enough
            given.add(_term(word, language))
            if _term(word, language) in have:
                change.skipped.append(word)
            else:
                new.append(word)
        if not new:
            return
        if not f.exists:
            f.add([HEADERS[kind].format(language=language)])
        f.add(new)
        if _write(f, change):
            change.done = new

    return _held(language, change, work)


def remove(kind, language, words, source="list"):
    """Take `words` off the list (see the module docstring) -> a `Change`."""
    change = Change()
    wanted = [str(w or "").strip() for w in words if str(w or "").strip()]
    if source == "known":
        return _held(language, change, lambda: _remove_known(language, wanted, change))
    if source != "list":
        change.error = "Names are left out by the Ignore names setting: turn it off to count them."
        return change
    path = list_path(kind, language)

    def work():
        if not os.path.isfile(path):
            change.skipped = wanted
            return
        try:
            f = _File(path, language)
        except Unreadable:
            change.error = _unreadable(KINDS[kind])
            return
        found = f.remove(set(wanted))
        change.skipped = [w for w in wanted if w not in found]
        if found and _write(f, change):
            change.done = found

    return _held(language, change, work)


def _write(f, change):
    """The session's backup, then `f` written atomically -> True when written (else `change.error` says why)."""
    try:
        change.backup = _backup_once(f.path)
    except OSError as e:
        change.error = f"Nothing was changed: {os.path.basename(f.path)} could not be backed up ({e})."
        return False
    try:
        anki_sync._atomic_write_bytes(f.path, f.data())
    except OSError as e:
        change.error = f"Nothing was changed: {os.path.basename(f.path)} could not be written ({e})."
        return False
    return True


def _remove_known(language, words, change):
    """KnownWord.json's IGNORED entries whose dictForm is one of `words` taken out (its lock held)."""
    try:
        data, current = anki_sync._read_known_file(language)
    except anki_sync._KnownFileError as e:
        change.error = str(e)
        return
    if current is None:
        change.skipped = words
        return
    wanted = set(words)
    kept, found = [], []
    for e in current:
        word = str(e.get("dictForm") or "").strip() if isinstance(e, dict) else ""
        if word in wanted and e.get("knownStatus") == "IGNORED":
            if word not in found:
                found.append(word)
        else:
            kept.append(e)
    change.skipped = [w for w in words if w not in found]
    if not found:
        return
    path = anki_sync._known_path(language)
    try:
        change.backup = _backup_once(path)
    except OSError as e:
        change.error = f"Nothing was changed: your known words could not be backed up ({e})."
        return
    if isinstance(data, list):
        data = kept
    else:
        data = dict(data)                           # every other top-level key kept untouched
        data["words"] = kept
    try:
        anki_sync._atomic_write_json(path, data)
    except OSError as e:
        change.error = f"Nothing was changed: your known words could not be written ({e})."
        return
    change.done = found


# --- pasted text ---------------------------------------------------------------------------------------------- #
def words_in(text, language, kind="ignore"):
    """The words of `text` the list could take, in the order first met, each once -> [`Candidate`]. A word is marked
    `listed` (on this list already), `known` (a known word) or `left_out` (another list or KnownWord.json leaves it
    out already); the rest are `new`. Japanese: a one-character word the list never offers there (grammar, a piece of
    a term: `analyzer.unoffered`) is no candidate, as it is no word on the list. Loads the tokenizer: the paste's
    child's (`find_main`), never the window's."""
    from app import analyzer, settings_manager, token_index, zh_script
    settings = settings_manager.load_settings()
    try:
        analyzer.LOGIC.update(settings.get("logic", {}))    # the run's switches, as every reader outside a run sets them
    except Exception:
        pass
    script = zh_script.effective(language, settings.get("zh_script"))
    single = bool(settings.get("exclude_single", True))
    if language == "zh":
        tokenizer = analyzer.ChineseTokenizer(script=script)
    else:
        tokenizer = analyzer.JapaneseTokenizer()
    user_files = path_utils.get_user_files_path(language)

    def lines(name):
        p = os.path.join(user_files, name)
        return path_utils.read_text(p, language).splitlines() if os.path.isfile(p) else []

    other = "blacklist" if kind == "ignore" else "ignore"
    listed = analyzer._list_words(lines(KINDS[kind]), script)
    left_out = analyzer._list_words(lines(KINDS[other]) + lines("GraduatedList.txt"), script)
    ignored = analyzer.load_ignored_entries(user_files, script, language)
    if kind == "ignore":
        listed |= ignored
    else:
        left_out |= ignored
    known_tuples, known_lemmas = _known(language, user_files, script)

    out, seen = [], set()                               # Chinese keeps every word (one character too)
    for sentence, tokens in tokenizer.tokenize_sentences(text):
        if language == "ja":                        # the run's lemma and spelling (SANITIZE_JA), cut as a run cuts them
            tokens = [(analyzer._sanitize_term(lemma) if lemma else lemma, reading, surface,
                       analyzer._sanitize_term(orth or surface)) for lemma, reading, surface, orth in tokens]
        skip = analyzer.unoffered(sentence, tokens) if single and language == "ja" else ()
        for i, (lemma, reading, surface, orth) in enumerate(tokens):
            if i in skip or not lemma:
                continue
            if not lemma or lemma in seen:
                continue
            seen.add(lemma)
            if lemma in listed:
                status = "listed"
            elif (lemma, reading) in known_tuples or lemma in known_lemmas:
                status = "known"
            elif lemma in left_out:
                status = "left_out"
            else:
                status = "new"
            out.append(Candidate(lemma, orth or surface or lemma, status))
    return out


def _known(language, user_files, script):
    """(known (lemma, reading)s, known lemmas): the token store's cached normalization while KnownWord.json is
    unchanged (read only, never written), else the tokenizer-free approximation the Rarity preview reads."""
    from app import token_index
    known_file = os.path.join(user_files, "KnownWord.json")
    store = None
    try:
        store = token_index.open_reader(language)
        cached = store.get_cached_known(token_index.known_signature(known_file, script)) if store else None
        if cached is not None:
            return cached
    except Exception:
        pass
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                pass
    try:
        return set(), token_index.preview_known_approx(user_files, language, script)
    except Exception:
        return set(), set()


# --- pasted text, in a child process (FX-wl S2) ------------------------------------------------------------------ #
class FindFailed(Exception):
    """The paste's child failed, timed out or was stopped: nothing found (the message is a plain sentence)."""


class Cancelled(FindFailed):
    """The paste was cancelled (`Paste.cancel`): its child killed."""


class Paste:
    """One paste's child process: `cancel()` from any thread kills it (before it starts too); `find_words` then raises
    `Cancelled`."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self.cancelled = False

    def cancel(self):
        with self._lock:
            self.cancelled = True
            proc = self._proc
        if proc is not None:
            _kill(proc)

    def _started(self, proc):
        """-> False when the paste was cancelled before its child started (the child is killed)."""
        with self._lock:
            self._proc = proc
            cancelled = self.cancelled
        if cancelled:
            _kill(proc)
        return not cancelled

    def _ended(self):
        with self._lock:
            self._proc = None


def _kill(proc):
    try:
        proc.kill()
    except OSError:
        pass                                    # it had ended


def find_command():
    """The paste's child: the frozen app's own verb, or app_entry.py from source (as `arrivals.command_line`)."""
    from app.path_utils import is_frozen
    verb = [FIND_VERB, "--headless"]
    if is_frozen():
        return [sys.executable] + verb
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [sys.executable, os.path.join(root, "app_entry.py")] + verb


def find_words(text, language, kind="ignore", paste=None, timeout=None):
    """`words_in(text, language, kind)` worked out in a child process (see the module docstring) -> [`Candidate`].
    Raises `FindFailed` (`Cancelled` when `paste` was cancelled). The text goes on the child's stdin, never its
    command line (app_entry.py logs every argv)."""
    from app.path_utils import build_subprocess_env, is_frozen
    paste = paste if paste is not None else Paste()
    timeout = FIND_TIMEOUT if timeout is None else timeout
    request = json.dumps({"text": text, "language": language, "kind": kind}, ensure_ascii=False).encode("utf-8")
    if paste.cancelled:
        raise Cancelled("The paste was cancelled.")
    try:
        proc = subprocess.Popen(find_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=build_subprocess_env(is_frozen()),
                                creationflags=0x08000000 if sys.platform == "win32" else 0)   # CREATE_NO_WINDOW
    except OSError as e:
        raise FindFailed(f"Surasura's word reader couldn't start ({e}).")
    try:
        if not paste._started(proc):
            proc.communicate()
            raise Cancelled("The paste was cancelled.")
        try:
            out, err = proc.communicate(request, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            proc.communicate()
            raise FindFailed(f"Reading the text took longer than {timeout:g} seconds, so it was stopped.")
    finally:
        paste._ended()
    if paste.cancelled:
        raise Cancelled("The paste was cancelled.")
    if proc.returncode != 0:
        why = [line for line in err.decode("utf-8", "replace").splitlines() if line.strip()]
        raise FindFailed(f"Surasura's word reader stopped (exit code {proc.returncode})"
                         + (f": {why[-1].strip()}" if why else "") + ".")
    try:
        return [Candidate(*(str(part) for part in w)) for w in json.loads(out.decode("utf-8"))["words"]]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise FindFailed("Surasura's word reader gave an answer it couldn't read.")


def find_main():
    """The paste's child (`app_entry.py word-lists-find --headless`): one JSON request on stdin, {"text",
    "language", "kind"}; `words_in`'s answer on stdout, {"words": [[word, spelling, status], ...]} -> 0, or 1 with
    the traceback on stderr. Writes nothing: `words_in` only reads (the token store read-only)."""
    stream = sys.stdout                         # held: the stream app_entry made, closed if it were let go
    out = stream.buffer
    sys.stdout = sys.stderr                     # anything the analyzer prints stays off the answer
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        language, kind = request["language"], request.get("kind", "ignore")
        if language not in ("ja", "zh") or kind not in KINDS:
            raise ValueError(f"no such list: {kind} ({language})")
        found = words_in(str(request["text"]), language, kind)
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
    out.write(json.dumps({"words": [list(c) for c in found]}, ensure_ascii=False).encode("utf-8"))
    out.flush()
    return 0
