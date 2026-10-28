"""K5 (alpha 4, the large-library copy): a look keeps its book tables up in place after each new book's take-in
instead of building them again over every origin (that rebuild, once a book, was ~19 h of a 25,000-book first look).
The proof: after EVERY refresh of a real first look, each table built so far equals the one a build from scratch makes
now — books in two folders, two editions of one book (`<book>` and `<book> (第2版)`: the editions table), a book whose
parts an item already holds (its take-in attached, so the tables are built anew), then a later look (nothing new).
Also: `items_of_size` reads the partial index `items_available_size` (no walk of every item), made at a store's first
open by a writer when an older Surasura made it."""
import copy
import os
import sqlite3

import pytest

from app import library_store as ls
from app import sources
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _epub, _fresh_module_state, _look  # noqa: F401

_BODIES = {"ja": ["吾輩は猫である。名前はまだ無い。どこで生れたかとんと見当がつかぬ。", "何でも薄暗いじめじめした所でニャーニャー泣いていた事だけは記憶している。",
                  "吾輩はここで始めて人間というものを見た。しかもあとで聞くとそれは書生という人間中で一番獰悪な種族であったそうだ。"],
           "zh": ["我家的后面有一个很大的园，相传叫作百草园。现在是早已并屋子一起卖给朱文公的子孙了。", "其中似乎确凿只有一些野草；但那时却是我的乐园。",
                  "不必说碧绿的菜畦，光滑的石井栏，高大的皂荚树，紫红的桑椹；也不必说鸣蝉在树叶里长吟。"]}
_TABLES = ("books_in", "book_origins", "book_keys", "by_item", "editions", "show_origins")


def _chapters(language, n):
    lines = _BODIES[language]
    return [f"<h1>第{c}章</h1>" + "".join(f"<p>{lines[(c + i) % 3]}{n}-{c}-{i}</p>" for i in range(40))
            for c in range(1, 4)]


def _built(look):
    """Each table built so far, then the same table built from scratch over `origins` as they are now (its members
    grouped again too)."""
    kept = {t: getattr(look, t, None) for t in _TABLES}
    kept["by_show"], kept["members"] = look.by_show, look.members
    kept["edition_of"] = getattr(look, "edition_of", None)
    look.books_in = look.book_origins = look.book_keys = look.by_item = look.editions = look.by_show = None
    look.members = None
    fresh = {}
    if kept["books_in"] is not None:
        fresh["books_in"] = look._books()
    if kept["book_origins"] is not None:
        fresh["book_origins"] = look._book_origins()
    if kept["book_keys"] is not None:
        fresh["book_keys"] = look._book_keys()
    if kept["by_item"] is not None:
        fresh["by_item"] = look._by_item()
    if kept["editions"] is not None:
        look.editions = None
        look._edition_of(os.path.join(os.sep, "nowhere", "x (第2版).epub"))   # builds the editions table
        fresh["editions"] = look.editions
    if kept["by_show"] is not None:
        look._show_origins("")
        fresh["show_origins"] = look.show_origins
    for t in _TABLES:                                      # put the look's own back: the look goes on with them
        setattr(look, t, kept[t])
    look.by_show, look.members, look.edition_of = kept["by_show"], kept["members"], kept["edition_of"]
    return copy.deepcopy({t: kept[t] for t in fresh}), fresh      # as they were now: the look goes on changing them


@pytest.mark.parametrize("language", LANGUAGES)
def test_each_refresh_of_a_first_look_leaves_the_tables_a_build_from_scratch_makes(language, monkeypatch):
    """Why: a first look of thousands of books must not rebuild its book tables once a book — and kept up in place,
    each must still be exactly the table every later step of the look reads (a book's editions, its moved copy, a
    show's episodes), or a book could be split twice or an edition missed."""
    store, data_dir = _empty(language)
    src = _drive("books")
    for n, (folder, name) in enumerate([("Shelf A", "星の歌.epub"), ("Shelf A", "星の歌 (第2版).epub"),
                                        ("Shelf A", "月の庭.epub"), ("Shelf B/Author", "風の便り.epub"),
                                        ("Shelf B", "海の声.epub")]):
        _epub(os.path.join(src, folder, name), _chapters(language, n))
    compared, rebuilt = [], []
    real_refresh, real_members = sources._Look._refresh, sources._Look._members

    def refresh(self, item_ids, change=None):
        real_refresh(self, item_ids, change)
        compared.append(_built(self))

    def members(self):
        if self.members is None:
            rebuilt.append(1)
        return real_members(self)
    monkeypatch.setattr(sources._Look, "_refresh", refresh)
    monkeypatch.setattr(sources._Look, "_members", members)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert result["added"] > 0
        assert compared, "no book was taken in"
        assert len(rebuilt) == 1 + len(compared), "the members grouped once a look (and once more per check here)"
        assert any(kept for kept, _fresh in compared), "no table was built before a refresh"
        for kept, fresh in compared:
            assert kept == fresh
        again = _look(store, language, root, full=True)       # nothing new: the tables as the store holds them
        assert again["added"] == 0


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_book_whose_parts_an_item_holds_leaves_the_tables_a_build_from_scratch_makes(language, monkeypatch):
    """Why: a part attached to an item already in (its bytes the same) changes that item's records: its buckets are
    built again from its records as they are now — never left holding the item's old ones."""
    store, data_dir = _empty(language)
    src = _drive("books")
    first = _epub(os.path.join(src, "One", "星の歌.epub"), _chapters(language, 7))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        with open(first, "rb") as f:
            same = f.read()
        os.makedirs(os.path.join(src, "Two"), exist_ok=True)
        copy = os.path.join(src, "Two", "星の歌 copy.epub")
        with open(copy, "wb") as f:
            f.write(same + b"\0")                          # other bytes (a new EPUB), the same parts
        t = os.stat(first).st_mtime
        os.utime(copy, (t, t))
        compared = []
        real_refresh = sources._Look._refresh

        def refresh(self, item_ids, change=None):
            real_refresh(self, item_ids, change)
            compared.append(_built(self))
        monkeypatch.setattr(sources._Look, "_refresh", refresh)
        _look(store, language, root)
        assert compared                                    # attached to the items in
        for kept, fresh in compared:
            assert kept == fresh


def test_items_of_size_reads_its_partial_index_and_an_older_store_gains_it():
    """Why: `items_of_size` runs once a book; without the index it walked every item (2 s a book by the last of
    25,000). An index changes no row: a store an older Surasura made gains it at its first open by a writer, and
    nothing else in it changes."""
    store, data_dir = _empty("ja")
    user_files_dir, path = store.user_files_dir, store.db_path
    with store:
        plan = " ".join(str(r[-1]) for r in store.conn.execute(
            "EXPLAIN QUERY PLAN SELECT size, id, rel_path FROM items WHERE availability = 'available' AND size IN (1, 2)"))
        assert "items_available_size" in plan, plan
    conn = sqlite3.connect(path)
    conn.execute("DROP INDEX items_available_size")                      # the store as an older build made it
    conn.commit()
    rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    again = ls.open_store("ja", data_dir, user_files_dir)
    try:
        assert again.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'items_available_size'").fetchone()
        assert again.conn.execute("SELECT * FROM items ORDER BY id").fetchall() == rows
        assert again.conn.execute("PRAGMA user_version").fetchone()[0] == version
    finally:
        again.close()
