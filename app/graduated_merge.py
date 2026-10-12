"""GraduatedList.txt, merged once into the known words (S3.1 D13; Sonic's Q4-10).

2.x's Graduate wrote each graduated file's words into `User Files/<lang>/GraduatedList.txt`, which every run read as
ignored words. 3.0 makes them what they are — words the learner knows: each listed word KnownWord.json doesn't hold yet
is added as a KNOWN entry (`source: "GraduatedList"`, no card); one it holds as UNKNOWN or LEARNING is raised to KNOWN
(its other fields kept, `previousStatus` recording the old one); and the list is set aside in `.trash`. Every import
that replaces the file — Anki's Replace, the Jiten and Migaku imports — keeps the added entries
(`anki_sync.kept_graduated`); `ensure_data_setup` no longer makes the list again.

The rules, each a way the user's known words could be damaged otherwise (CLAUDE.md §4):
  * KnownWord.json's lock (`known-words-<lang>`) is held for the whole read-modify-write;
  * a KnownWord.json that can't be read strictly is never written (nor is the list moved);
  * a dated, byte-verified copy of KnownWord.json is kept before the write (`path_utils.backup_to_trash`), and a
    backup that fails writes nothing;
  * a word the file already holds as known, or as IGNORED (the user's choice, under any other entry too), is left
    alone; nothing is ever written IGNORED, and IgnoreList.txt / Blacklist.txt are never touched;
  * the write is atomic (`anki_sync._atomic_write_json`), and only after it the list moves to `.trash`
    (`backup_to_trash(move=True)`; never purged). A list with no words is moved there too, once.
A second run finds no list and changes nothing; one interrupted between the write and the move finds every word
known, changes nothing, and moves the list.

The list is read as the ignore set read it (`analyzer._list_words`): in its own encoding (strictly: a list no encoding
reads whole is left for the user), `#` comments and blank lines dropped, Japanese cut at the first hyphen or space as
`analyzer._sanitize_term` cuts it, Chinese only trimmed; a hiragana line also names the kanji word it is typed for
(する -> 為る: `analyzer._kana_lines_read`, the one step that needs the tokenizer — the analyzer is imported only for
a list holding such a line). No script conversion: the known-words reader converts every entry into the library's
script as it reads it, so the words are kept as the list spells them. No Tk: the window's first-run page calls it.
"""

import os
import re

from app import anki_sync, path_utils

LIST_FILE = "GraduatedList.txt"
SOURCE = anki_sync.GRADUATED_SOURCE
VERB = "Graduated words merge"
RAISED = ("UNKNOWN", "LEARNING")

_TERM_CUT_RE = re.compile(r"[-\s]")             # analyzer._TERM_CUT_RE
_HIRAGANA_LINE_RE = re.compile(r"^[ぁ-ゖ]{2,}$")  # analyzer._HIRAGANA_LINE_RE


def list_words(text, language):
    """The words a GraduatedList's `text` names, in order, each once (see the module docstring; the kanji words of
    hiragana lines are `kana_words`)."""
    words, seen = [], set()
    for line in text.splitlines():
        word = line.strip()
        if not word or word.startswith("#"):
            continue
        if language == "ja":
            cut = _TERM_CUT_RE.search(word)
            word = word if cut is None else word[:cut.start()]
        if word and word not in seen:
            seen.add(word)
            words.append(word)
    return words


def kana_words(words):
    """The kanji words the hiragana `words` are typed for (する -> 為る), as the ignore set read them, sorted; [] for
    a list with no such line, or when the tokenizer can't be loaded (the lines as they are, as the ignore set did)."""
    if not any(_HIRAGANA_LINE_RE.match(w) for w in words):
        return []
    try:
        from app.analyzer import _kana_lines_read
        return sorted(_kana_lines_read(set(words)) - set(words))
    except Exception as e:
        print(f"Graduated words: the hiragana lines are kept as they are ({e}).")
        return []


def _entry(word, language, now):
    """A known word with no card, in the Anki sync's entry shape (`anki_sync._entry`)."""
    entry = anki_sync._entry(word, None, language, now)
    entry.update({"knownStatus": "KNOWN", "hasCard": 0, "source": SOURCE})
    return entry


def _counts(language):
    return {"language": language, "listed": 0, "added": 0, "raised": 0, "present": 0, "backup": None,
            "retired": None, "error": None}


def merge(language):
    """Merge `User Files/<language>/GraduatedList.txt` into KnownWord.json, once -> a dict of counts:
    `listed` (the words read, hiragana lines' kanji words included), `added`, `raised` (UNKNOWN / LEARNING entries
    made KNOWN), `present` (already known or IGNORED), `backup` (KnownWord.json's dated copy, or None), `retired`
    (where the list went in `.trash`, or None), `error` (a plain sentence, or None: nothing was written when it is set
    before the move). No list: every count 0, nothing done."""
    result = _counts(language)
    list_path = os.path.join(path_utils.get_user_files_path(language), LIST_FILE)
    if not os.path.isfile(list_path):
        return result
    try:
        words = list_words(path_utils.read_text(list_path, language, errors="strict"), language)
    except (OSError, UnicodeDecodeError) as e:
        result["error"] = f"Your Graduated list could not be read, so nothing was changed ({LIST_FILE}: {e})."
        return result
    if language == "ja":
        words += kana_words(words)
    result["listed"] = len(words)
    if words:
        held, refused = anki_sync.hold_known_words(language, VERB)
        if refused is not None:
            result["error"] = refused[0]
            return result
        try:
            if not _merge_held(language, words, result):
                return result
        finally:
            if held is not None:
                held.release()
    try:
        result["retired"] = path_utils.backup_to_trash(list_path, move=True)
    except OSError as e:
        result["error"] = f"Your Graduated words are in your known words; the list itself could not be moved ({e})."
    return result


def _merge_held(language, words, result):
    """The listed words made known in KnownWord.json (its lock held) -> True when the file is as it should be."""
    try:
        data, current = anki_sync._read_known_file(language)
    except anki_sync._KnownFileError as e:
        result["error"] = str(e)
        return False
    by_key = {}
    for entry in current or []:
        if isinstance(entry, dict):
            by_key.setdefault(anki_sync._norm(entry.get("dictForm")), []).append(entry)
    now = anki_sync._now_iso()
    new, raise_ = [], []
    for word in words:
        key = anki_sync._norm(word)
        if not key:
            continue
        entries = by_key.get(key)
        if entries is None:
            entry = _entry(word, language, now)
            by_key[key] = [entry]
            new.append(entry)
        elif any(e.get("knownStatus") == "IGNORED" or anki_sync._is_known(e) for e in entries):
            result["present"] += 1
        else:
            raise_ += [e for e in entries if e.get("knownStatus") in RAISED and all(e is not r for r in raise_)]
    if not new and not raise_:
        return True
    known_path = anki_sync._known_path(language)
    try:
        result["backup"] = path_utils.backup_to_trash(known_path)
    except OSError as e:
        result["error"] = f"Nothing was changed: your known words could not be backed up ({e})."
        return False
    for entry in raise_:                    # in place: `data` holds these very entries (read here, never kept)
        entry["previousStatus"] = entry["knownStatus"]
        entry["knownStatus"] = "KNOWN"
    if data is None:
        data = {"exportDate": now, "source": SOURCE, "statistics": {}, "words": new}
    elif isinstance(data, list):
        data = data + new
    else:
        data = dict(data)          # every other top-level key kept untouched
        data["words"] = list(current) + new
    try:
        anki_sync._atomic_write_json(known_path, data)
    except OSError as e:
        result["error"] = f"Nothing was changed: your known words could not be written ({e})."
        return False
    result["added"], result["raised"] = len(new), len(raise_)
    return True


def merge_all(languages=("ja", "zh")):
    """`merge` for each language -> {language: its counts}. One language's failure never stops the next."""
    out = {}
    for language in languages:
        try:
            out[language] = merge(language)
        except Exception as e:     # a first start goes on: the list stays where it is, read next time
            out[language] = dict(_counts(language), error=f"The Graduated list merge stopped ({e}).")
    return out
