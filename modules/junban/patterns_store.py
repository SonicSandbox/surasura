# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only access to `patterns_ja.db` — what `patterns_build.py` counted (Patterns_Spec.md WP-P3).

Opened read-only on purpose: the database is derived and regenerable, and only the builder writes
it — atomically, so a reader never sees half a build. A missing file is a normal state (nothing has
been built yet), not an error, and `open_store` says so by returning None.
"""

import os
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = path
        # Read-only, and used by one thread at a time — but not always the thread that opened it: the
        # Backfill window keeps its stores across previews, each run on a fresh worker thread, and
        # closes them from the UI thread. SQLite's own same-thread check would refuse the second preview.
        self._con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True,
                                    check_same_thread=False)
        # A database from builder 1 has no `section` column; its rows read as one construction. One from
        # builder 5 or before has no `files` (the documents a pattern was seen in): None, and the lookup
        # skips the documents filter for it (Patterns_Quality_Spec.md §8.3).
        columns = {row[1] for row in self._con.execute("PRAGMA table_info(pattern)")}
        self._section = "section" if "section" in columns else "NULL"
        self._files = "files" if "files" in columns else "NULL"
        self._meta = None
        # A card asks for its word's row two or three times (the lookup, the floor, the particle
        # side); the file never changes under an open store, so the answer is kept.
        self._words = {}

    def close(self):
        self._con.close()

    def meta(self):
        """The build's `meta` table — read once: a fill asks it for every card, and it never changes
        under an open store (a rebuild replaces the file, it does not edit it)."""
        if self._meta is None:
            self._meta = dict(self._con.execute("SELECT key, value FROM meta"))
        return self._meta

    def floor(self):
        try:
            return int(self.meta().get("floor", 0))
        except ValueError:
            return 0

    def word(self, lemma, reading):
        """-> (orth, pos, count) for one key, or None."""
        key = (lemma, reading)
        if key not in self._words:
            self._words[key] = self._con.execute(
                "SELECT orth, pos, count FROM lemma WHERE lemma=? AND reading=?", key).fetchone()
        return self._words[key]

    def readings(self, lemma):
        """-> [(reading, count)] for a lemma, best evidenced first."""
        return self._con.execute("SELECT reading, count FROM lemma WHERE lemma=? ORDER BY count DESC",
                                 (lemma,)).fetchall()

    def by_orth(self, orth):
        """-> [(lemma, reading, count)] for a spelling, best evidenced first (§7 steps 3-4)."""
        return self._con.execute("SELECT lemma, reading, count FROM alias WHERE orth=? ORDER BY count DESC",
                                 (orth,)).fetchall()

    def patterns(self, lemma, reading, kind):
        """-> [(item, count, logdice, section, files)] for one key and kind, strongest first. `section`
        is the construction the item comes from (`patterns_build._section`) — for a particle, its side —
        or None; `files` the documents it was seen in, or None."""
        return self._con.execute(
            f"SELECT item, count, logdice, {self._section}, {self._files} FROM pattern "
            "WHERE lemma=? AND reading=? AND kind=? "
            "ORDER BY logdice DESC, count DESC", (lemma, reading, kind)).fetchall()

    def all_patterns(self, lemma, reading):
        """-> {kind: [(item, count, logdice, section, files)]} for one key, each kind strongest first —
        every kind in ONE query: a fill looks up a thousand cards, and four queries a card was most of it."""
        out = {}
        for kind, *row in self._con.execute(
                f"SELECT kind, item, count, logdice, {self._section}, {self._files} FROM pattern "
                "WHERE lemma=? AND reading=? ORDER BY logdice DESC, count DESC", (lemma, reading)):
            out.setdefault(kind, []).append(tuple(row))
        return out

    def builder_version(self):
        """The builder that wrote this file, or None when its meta does not say (a store made by hand)."""
        try:
            return int(self.meta()["builder_version"])
        except (KeyError, ValueError):
            return None


def required_builder(language):
    """The builder a database must come from to be read: this code's own for the language. An older one
    keys words the old way — before words kept their prefixes and suffixes, 不自然 and お菓子 were two — so
    it would answer "not found" for them and miss every new line (Patterns_Quality_Spec.md §8.3a)."""
    if language == "zh":
        from modules.junban import patterns_zh
        return patterns_zh.BUILDER_VERSION
    from modules.junban.patterns_build import BUILDER_VERSION
    return BUILDER_VERSION


def is_current(path, language="ja"):
    """Is the database at `path` there, of `language`, and from this code's builder? A file whose meta
    names no language or builder (a store made by hand) is taken at its name."""
    store = open_store(path, language, quiet=True)
    if store is None:
        return False
    store.close()
    return True


def open_store(path=None, language="ja", name=None, quiet=False):
    """-> a `Store`, or None when no database has been built yet — or when the file holds another
    language's data by its own meta (a Chinese `patterns_zh.db` holding Japanese rows is never read
    for Chinese cards: Patterns_Chinese_Spec.md S1), or comes from an older builder (`required_builder`).
    A file without those keys is taken at its name. `name` picks a general corpus's database
    (`patterns_ja_<name>.db`); none is the library's."""
    if path is None:
        from modules.junban.patterns_build import default_db_path
        path = default_db_path(language, name)
    if not os.path.exists(path):
        return None
    store = Store(path)
    found = store.meta().get("language")
    if found and found != language:
        store.close()
        if not quiet:
            print(f"パターン: {os.path.basename(path)} holds {found} data, not {language} — not used.")
        return None
    built = store.builder_version()
    if built is not None and built < required_builder(language):
        store.close()
        if not quiet:
            print(f"パターン: {os.path.basename(path)} is from builder {built}; this version needs "
                  f"{required_builder(language)} — not used until it is rebuilt or downloaded again.")
        return None
    return store
