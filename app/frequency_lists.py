"""The frequency lists the user adds (W3.4 row 1; from the Tk Frequency List Manager, `app/frequency_list_gui.py`):
general frequency lists, as CSV files in `User Files/<lang>/` named `frequency_list_<lang>_<name>.csv` — the names the
analyzer reads (`analyzer.discover_yomitan_frequency_lists`), so a list counts in the next Generate's report.

The Tk window's rules, moved here (its `add_files` / `remove_files` / `refresh_file_list`), with the port's data-safety
floor (CLAUDE.md §4) the Tk window fell short of:
- `listed(lang)`: this language's lists only (the Tk glob showed every language's);
- `add(src, lang)`: copied in whole first (a temporary file beside it, then one atomic replace); a list of the same
  name gets a dated copy in `User Files/<lang>/.trash` first (the Tk window overwrote it with no copy); a source that
  is already that list changes nothing;
- `remove(name, lang)`: moved into `User Files/<lang>/.trash` (`path_utils.backup_to_trash(move=True)`; that folder is
  never purged) — never deleted (the Tk window's `os.remove`); only a name `listed` gives.
Qt-free; every call reads or writes the disk (a window's worker calls it).
"""
import os
import shutil

from app import path_utils

PREFIX = "frequency_list_"
EXTENSION = ".csv"


def _prefix(language):
    return f"{PREFIX}{language}_"


def folder(language):
    return path_utils.get_user_files_path(language)


def dest_name(base, language):
    """The name a list `base` takes for `language`: the language's prefix added (`Novel.csv` →
    `frequency_list_ja_Novel.csv`), a bare `frequency_list_` prefix made the language's, a right one kept. Pure."""
    prefix = _prefix(language)
    if base.startswith(prefix):
        return base
    if base.startswith(PREFIX):
        return prefix + base[len(PREFIX):]
    return prefix + base


def listed(language):
    """This language's lists, by name, sorted: the files the analyzer reads for `language`. [] when there are none."""
    where = folder(language)
    prefix = _prefix(language)
    try:
        names = os.listdir(where)
    except OSError:
        return []
    return sorted(n for n in names
                  if n.startswith(prefix) and n.endswith(EXTENSION) and os.path.isfile(os.path.join(where, n)))


def add(src, language):
    """Copy the list `src` in for `language`. -> (name, kept): the name it has now, and the dated copy of the list it
    replaced (None when there was none). Raises `shutil.SameFileError` when `src` is that list already (nothing
    changed) and OSError when it can't be added (the list there before, if any, left as it was)."""
    where = folder(language)
    os.makedirs(where, exist_ok=True)
    name = dest_name(os.path.basename(src), language)
    dest = os.path.join(where, name)
    if os.path.exists(dest) and os.path.samefile(src, dest):
        raise shutil.SameFileError(f"{src} is {dest} already")
    temp = os.path.join(where, f".{name}.adding")
    try:
        shutil.copyfile(src, temp)
        kept = path_utils.backup_to_trash(dest)       # a same-named list: its dated copy first (None: no list there)
        os.replace(temp, dest)
    except BaseException:
        try:
            os.remove(temp)                           # our own unfinished copy, never the user's file
        except OSError:
            pass
        raise
    return name, kept


def remove(name, language):
    """Move the list `name` (one `listed(language)` gives) into `User Files/<lang>/.trash`. -> where it went. Raises
    FileNotFoundError for a name that isn't one of this language's lists (nothing touched), OSError when it can't be
    moved (left where it was)."""
    if name not in listed(language):
        raise FileNotFoundError(f"{name} is not one of the {language} frequency lists")
    return path_utils.backup_to_trash(os.path.join(folder(language), name), move=True)
