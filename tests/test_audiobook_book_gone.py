"""A book's new version and its audiobook (Kura-AB5; the 11-20 report, Sonic's rulings; words PROVISIONAL).

The learner's book was in the library, its audiobook paired with it. He brought in a new version of the book (another
file name: another split, no notes), removed the old one — and the new one could never have its audiobook: *Pick its
audiobook…* listed nothing, and picking the audiobook's folder said "No audiobook in … yet". The audiobook's record still
named the removed book, so it was "with another book" whose title wasn't this one's. And the new book was called
「…(2)」, the folder name its parts were written to.

- an audiobook whose book has left the library (no part of it is an item) is free: listed for any book with no
  *now with 「…」*, picked with no `replace`, paired by the folder's look — and its old pair kept until then, so Put back
  of the old book pairs them again by itself;
- the folder pick never says "none" when the folder holds an audiobook with another book: it names that book;
- *An audio file…*: the audiobook that file belongs to is the book's, whatever its names — the one exact pick in a
  folder of several audiobooks;
- a book's title is never its folder's ` (n)`, and a library's titles from before lose it once;
- an `.srt` named like the EPUB beside it is the book's timed text, never a title of its own.

Real EPUBs of the suite's Japanese and Chinese sentences, real MP3s with real lengths, read by real looks into a real
store; nothing in the learner's folders is written (`_look`).
"""
import os
import shutil

import pytest

from app import audiobooks
from app import library_store as ls
from tests.test_audiobook_folder_pick import _add, _book_in, _picked, _untagged
from tests.test_audiobook_items import (NEKO, GINGA, SAIYU, RESOURCES, _audio_folder, _audio_items,  # noqa: F401
                                        _book_items, _epub, _fit, _fresh_module_state, _record)
from tests.test_library_store_support import roots
from tests.test_sources_scan import _drive, _look

SRT = {"ja": "placed_episode.srt", "zh": "night_market.srt"}


def _paired(language, title):
    """(store, old epub, audiobook item) — the book read where it is and its audiobook paired with it by the book's own
    *A folder on your computer…* (untagged files: no name says which book)."""
    store, epub = _book_in(language, title, "source")
    audio = os.path.join(_drive("audio"), "audiobook")
    _untagged(audio, _fit(language))
    _picked(store, language, audio, epub, title)
    (item,) = _audio_items(store)
    assert _record(store, item["id"])["book"]["epub"] == os.path.abspath(epub)
    return store, epub, item["id"]


def _raw(store, sql, args):
    """A library from before the fix, written as it was (the store's write helper)."""
    with store._writing():
        store.conn.execute(sql, args)


def _parts(store, epub):
    """The book's part items (its `<epub>#<n>` origins), in order."""
    lo = ls.SOURCE_KEY + ls.path_key(os.path.abspath(epub)) + "#"
    return sorted(i for (i,) in store.conn.execute(
        "SELECT DISTINCT item_id FROM pairings WHERE content_key >= ? AND content_key < ?", (lo, lo[:-1] + "$")))


def _new_version(store, language, title, dc_title=None):
    """The new version: another file name (`<title>-章分割-注なし`), in a folder of its own, read where it is ->
    its EPUB's path."""
    folder = _drive("new version")
    epub = _epub(os.path.join(folder, f"{title}-章分割-注なし.epub"), dc_title or f"{title}（新版）", language)
    _look(store, language, store.add_source(folder), full=True)
    assert _parts(store, epub)
    return epub


# --- B1: an audiobook whose book was removed is free ---------------------------------------------------------------- #
@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_an_audiobook_whose_book_was_removed_is_offered_to_the_new_version_with_no_now_with(language, title):
    """The report's case: the old version removed, the new version's *Pick its audiobook…* lists the audiobook as one
    alone (no *now with 「…」*: that book is gone), and the pick pairs it — no `replace` asked, its Undo back to the
    old pair."""
    store, old, ab = _paired(language, title)
    with store:
        assert store.remove(_parts(store, old)) is not None
        assert store._book_gone(_record(store, ab)["book"])
        new = _new_version(store, language, title)
        got = store.book_audiobooks(_parts(store, new)[0])
        assert [(a["item_id"], "elsewhere" in a) for a in got["audiobooks"]] == [(ab, False)]
        change = store.pick_audiobook_book(ab, new)
        assert change is not None
        assert _record(store, ab)["book"]["epub"] == os.path.abspath(new)
        store.undo(change)
        assert _record(store, ab)["book"]["epub"] == os.path.abspath(old), "Undo: the old pair, as it was"


def test_a_removed_books_audiobook_keeps_its_pair_so_put_back_pairs_them_again_by_itself():
    """Nothing is written on Remove: the record still names the old book, so its Put back (the Remove's Undo) has its
    audiobook again — a look meanwhile, a new book coming in (the audiobooks weighed again), never takes the pair
    away."""
    language = "ja"
    store, old, ab = _paired(language, NEKO)
    with store:
        change = store.remove(_parts(store, old))
        _new_version(store, language, NEKO)                  # (a new book: the lone audiobooks are weighed again)
        assert _record(store, ab)["book"]["epub"] == os.path.abspath(old)
        store.undo(change)
        assert not store._book_gone(_record(store, ab)["book"])
        got = store.book_audiobooks(_parts(store, old)[0])
        assert got["paired"] is True


def test_an_audiobook_with_a_book_still_in_the_library_is_not_free():
    """The control: while its book is in the library, the audiobook is with it — never offered as alone, never picked
    without `replace` (a pair you made is never moved silently, r2 S2)."""
    language = "ja"
    store, old, ab = _paired(language, NEKO)
    with store:
        assert not store._book_gone(_record(store, ab)["book"])
        new = _new_version(store, language, NEKO)
        got = store.book_audiobooks(_parts(store, new)[0])
        assert all("elsewhere" in a for a in got["audiobooks"] if a["item_id"] == ab)
        assert store.pick_audiobook_book(ab, new) is None
        assert _record(store, ab)["book"]["epub"] == os.path.abspath(old)


@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_the_folder_pick_for_the_new_version_names_the_freed_audiobook_alone(language, title):
    """*A folder on your computer…* of the audiobook's folder for the new version: the answer names it alone (the
    window then picks it, with Undo) — never "No audiobook in … yet"."""
    store, old, ab = _paired(language, title)
    with store:
        store.remove(_parts(store, old))
        new = _new_version(store, language, title)
    store.close()
    audio = os.path.join(_drive("audio"), "audiobook")
    said = _add(language, audio, {"epub": new, "title": f"{title}-章分割-注なし"})["audiobooks"]
    assert said["alone"] == [ab] and said["other"] == [] and said["elsewhere"] == []


def test_a_book_title_loses_the_librarys_folder_suffix_only():
    """`<name> (n)` is cut only when `<name>` is the EPUB's own name — a shop's `<book> (2)` (a second volume) stays."""
    assert ls.book_title("吾輩は猫である-章分割-注なし (2)", r"D:\Drop\吾輩は猫である-章分割-注なし.epub") == "吾輩は猫である-章分割-注なし"
    assert ls.book_title("葬送のフリーレン (2)", r"D:\Drop\葬送のフリーレン (2).epub") == "葬送のフリーレン (2)"
    assert ls.book_title("西游记 (3)", r"D:\书\西游记.epub") == "西游记"
    assert ls.book_title("西游记 (3)", None) == "西游记 (3)"
    assert ls.book_title("", "a.epub") == ""


def test_the_picker_lists_a_copys_audiobook_by_every_name_of_the_book():
    """A book whose title is still `<name> (2)` (a library from before): its *Pick its audiobook…* weighs its own name
    with the suffix off and its file's — the copy's audiobook is listed *now with 「…」* (the folder suffix once read as
    "volume 2" and hid it)."""
    language = "ja"
    store, old, ab = _paired(language, NEKO)
    with store:
        folder = _drive("copy")
        copy = _epub(os.path.join(folder, f"{NEKO}.epub"), NEKO, language, repeat=21)    # other bytes, same name
        _look(store, language, store.add_source(folder), full=True)
        part = _parts(store, copy)[0]
        work = store.item(part)["work_id"]
        _raw(store, "UPDATE works SET title = ? WHERE id = ?", (f"{NEKO} (2)", work))     # as before the fix
        got = store.book_audiobooks(part)
        assert got["title"] == NEKO
        assert [(a["item_id"], a.get("elsewhere")) for a in got["audiobooks"]] == [(ab, NEKO)]


# --- B1: the folder pick tells the truth ---------------------------------------------------------------------------- #
def test_the_folder_pick_names_an_audiobook_with_another_book_of_another_title():
    """The folder picked for 「吾輩は猫である」 holds an audiobook paired with 「銀河鉄道の夜」 (still in the library): the
    answer names it and that book — the window says it is with that book and how to give it (by its file)."""
    language = "ja"
    store, _epub_path = _book_in(language, NEKO, "source")
    store.close()
    other = _epub(os.path.join(_drive("more books"), f"{GINGA}.epub"), GINGA, language)
    audio = os.path.join(_drive("audio"), GINGA)
    _audio_folder(audio, GINGA, _fit(language))
    _add(language, os.path.dirname(other))
    _add(language, audio)
    said = _add(language, audio, {"epub": _epub_path, "title": NEKO})["audiobooks"]
    assert [o["book"] for o in said["other"]] == [GINGA] and not said["alone"]


# --- B3 1: an audiobook picked by one of its files ------------------------------------------------------------------ #
@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_an_audio_file_picked_joins_only_its_own_audiobook_from_a_folder_of_several(language, title):
    """A folder holding two audiobooks side by side, neither named like the book (the report's `Drop\\Audiobook`): the
    folder pick can't say which; a file of one picked joins THAT audiobook to the book, whatever its names, and the
    other stays alone."""
    store, epub = _book_in(language, title, "source")
    store.close()
    shelf = _drive("Audiobook")
    first = _audio_folder(os.path.join(shelf, "rip one"), "Untitled A", _fit(language))
    _audio_folder(os.path.join(shelf, "rip two"), "Untitled B", _fit(language) * 1.1)
    said = _add(language, os.path.dirname(first[0]), {"epub": epub, "title": title, "file": first[1]})["audiobooks"]
    store = ls.open_store(language, *roots(language))
    with store:
        mine = [i for i in _audio_items(store) if os.path.abspath(first[0]) in _record(store, i["id"])["files"]]
        assert len(mine) == 1 and said["joined"] and said["joined"][0]["item_id"] == mine[0]["id"]
        assert _record(store, mine[0]["id"])["book"]["epub"] == os.path.abspath(epub)


def test_an_audio_file_of_an_audiobook_already_in_names_only_that_one():
    """Both audiobooks of the folder read before (alone): the file's pick names only the one holding it — the window
    then picks it, with Undo."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    store.close()
    shelf = _drive("Audiobook")
    first = _audio_folder(os.path.join(shelf, "rip one"), "Untitled A", _fit(language))
    _audio_folder(os.path.join(shelf, "rip two"), "Untitled B", _fit(language) * 1.1)
    for rip in ("rip one", "rip two"):
        _add(language, os.path.join(shelf, rip))
    store = ls.open_store(language, *roots(language))
    with store:
        held = {r["item_id"]: r["audiobook"]["files"] for r in store.audiobooks()}
    assert len(held) == 2
    said = _add(language, os.path.dirname(first[0]), {"epub": epub, "title": NEKO, "file": first[0]})["audiobooks"]
    assert said["alone"] == [i for i, files in held.items() if os.path.abspath(first[0]) in files]


# --- B2: a book's title is never its folder's ` (n)` ---------------------------------------------------------------- #
@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_a_second_book_of_the_same_name_is_called_by_its_name_not_its_folders_suffix(language, title):
    """Two EPUBs of one name (other bytes) in two folders: the second's parts go to `Library/<name> (2)/` (the first
    holds `Library/<name>/`), and its title is `<name>` — the folder's name kept among its names (search)."""
    store, _data = _book_in(language, title, "source")
    with store:
        folder = _drive("second copy")
        second = _epub(os.path.join(folder, f"{title}.epub"), title, language, repeat=21)
        _look(store, language, store.add_source(folder), full=True)
        part = store.item(_parts(store, second)[0])
        assert part["rel_path"].split("/")[1] == f"{title} (2)"
        work = store.conn.execute("SELECT title, titles FROM works WHERE id = ?", (part["work_id"],)).fetchone()
        assert work[0] == title
        assert f"{title} (2)" in work[1]


def test_a_librarys_book_titles_from_before_lose_their_folder_suffix_once():
    """The one-time fix (the store's helper): a title that is its parts' folder name `<name> (n)` becomes `<name>`,
    once — never one the learner named, never one whose name another title holds; its Undo puts it back."""
    language = "ja"
    store, _data = _book_in(language, NEKO, "source")
    with store:
        folder = _drive("second copy")
        second = _epub(os.path.join(folder, f"{NEKO}.epub"), NEKO, language, repeat=21)
        _look(store, language, store.add_source(folder), full=True)
        work = store.item(_parts(store, second)[0])["work_id"]
        first = store.item(_parts(store, _data)[0])["work_id"]
        _raw(store, "UPDATE works SET title = ? WHERE id = ?", (f"{NEKO} (2)", work))      # a library from before
        _raw(store, "DELETE FROM meta WHERE key = ?", (ls.BOOK_TITLES_UNTAGGED,))
        store.rename_work(first, "猫の本")                    # (the first's name free: the learner's own name kept)
        change = store.untag_book_titles()
        assert change is not None
        assert store.conn.execute("SELECT title FROM works WHERE id = ?", (work,)).fetchone()[0] == NEKO
        assert store.untag_book_titles() is None, "once"
        store.undo(change)
        assert store.conn.execute("SELECT title FROM works WHERE id = ?", (work,)).fetchone()[0] == f"{NEKO} (2)"


def test_the_one_time_fix_leaves_a_suffix_whose_name_another_book_holds():
    language = "ja"
    store, _data = _book_in(language, NEKO, "source")
    with store:
        folder = _drive("second copy")
        second = _epub(os.path.join(folder, f"{NEKO}.epub"), NEKO, language, repeat=21)
        _look(store, language, store.add_source(folder), full=True)
        work = store.item(_parts(store, second)[0])["work_id"]
        _raw(store, "UPDATE works SET title = ? WHERE id = ?", (f"{NEKO} (2)", work))      # a library from before
        _raw(store, "DELETE FROM meta WHERE key = ?", (ls.BOOK_TITLES_UNTAGGED,))
        store.untag_book_titles()
        assert store.conn.execute("SELECT title FROM works WHERE id = ?", (work,)).fetchone()[0] == f"{NEKO} (2)"


# --- B2: an `.srt` named like the EPUB is its timed text ------------------------------------------------------------ #
@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_an_srt_named_like_the_epub_beside_it_is_no_title_of_its_own(language, title):
    """The report's `.srt` beside the `.epub`: the look takes the book in and holds the subtitle out — no item, no New
    arrivals, and the book's parts in `Library/<name>/` (never a `(2)`)."""
    store, _epub_path = _book_in(language, GINGA if language == "ja" else "红楼梦", "source")
    with store:
        folder = _drive("Drop")
        epub = _epub(os.path.join(folder, f"{title}.epub"), title, language, repeat=23)   # (its own text: other bytes)
        shutil.copy(os.path.join(RESOURCES, language, SRT[language]), os.path.join(folder, f"{title}.srt"))
        _look(store, language, store.add_source(folder), full=True)
        parts = _parts(store, epub)
        assert parts and store.item(parts[0])["rel_path"].split("/")[1] == title
        others = [r for r in store.conn.execute("SELECT id, rel_path, source_type, tier FROM items")
                  if r[0] not in parts and title in (r[1] or "")]
        assert others == [], "no title of its own, nothing in New arrivals"


def test_book_timings_name_rule():
    """Exactly the EPUB's name (a language tag allowed), never a video's subtitle, never another name."""
    assert audiobooks.book_timings(["猫.srt", "猫.ja.srt", "猫 01.srt", "犬.srt"], ["猫.epub"]) == \
        {"猫.srt": "猫.epub", "猫.ja.srt": "猫.epub"}
    assert audiobooks.book_timings(["猫.srt"], ["猫.epub"], ["猫.mkv"]) == {}
    assert audiobooks.book_timings(["夜市.zh-CN.srt"], ["夜市.EPUB"]) == {"夜市.zh-CN.srt": "夜市.EPUB"}
    assert audiobooks.book_timings([], ["猫.epub"]) == {} and audiobooks.book_timings(["猫.srt"], []) == {}


def test_connect_reads_the_books_own_srt_as_its_audiobooks_timing(tmp_path):
    """Once paired, the book's own `.srt` beside its EPUB is the audiobook's timing when Hon found none of its own
    (`audiobook_of_book`'s `book_timing`: read where it is, never copied)."""
    from app.connect import library
    epub = str(tmp_path / f"{NEKO}.epub")
    open(epub, "wb").close()
    assert library.book_timing(epub) is None
    srt = tmp_path / f"{NEKO}.ja.srt"
    shutil.copy(os.path.join(RESOURCES, "ja", SRT["ja"]), srt)
    assert library.book_timing(epub) == str(srt)
    (tmp_path / f"{NEKO}.mkv").write_bytes(b"\0" * 10)
    assert library.book_timing(epub) is None, "a video of that name: its subtitle"
    assert library.book_timing(str(tmp_path / "gone" / "x.epub")) is None


# --- B3 2: a book's every part, for its whole Remove ---------------------------------------------------------------- #
@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_a_books_items_are_every_part_whatever_its_rows(language, title):
    """The whole book behind any of its parts (the report's three Removes: its parts sat in three rows): every live
    part, by its EPUB, whichever part is asked; a video or an audiobook is no book."""
    store, old, ab = _paired(language, title)
    with store:
        parts = _parts(store, old)
        assert len(parts) >= 2, "a book in parts"
        for p in parts:
            got = store.book_items(p)
            assert got["ids"] == parts and got["title"] == title and got["epub"] == os.path.abspath(old)
        assert store.book_items(ab) is None


# --- B3 3: a new version replaces the old one ---------------------------------------------------------------------- #
def _new_beside(store, language, title, old):
    """The new version in the OLD one's folder, its package titled as the old one's (`dc:title`) -> its path."""
    epub = _epub(os.path.join(os.path.dirname(old), f"{title}-章分割-注なし.epub"), title, language, repeat=22)
    _look(store, language, store.add_source(os.path.dirname(old)), full=True)
    return epub


@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_a_new_version_beside_the_old_one_is_offered_and_replace_keeps_name_place_and_audiobook(language, title):
    """Sonic's ruling: the new version (the same folder, the same `dc:title`) is offered as the old one's
    replacement; *Replace* is ONE change — its parts join the old book's title (its name kept: no `(2)`, no new name)
    where the old parts stood, the audiobook follows it, the old parts go to Removed — and ONE Undo puts it all
    back: the old parts, their audiobook, the new version a title of its own."""
    store, old, ab = _paired(language, title)
    with store:
        old_parts = _parts(store, old)
        work = store.item(old_parts[0])["work_id"]
        tier = store.item(old_parts[-1])["tier"]
        new = _new_beside(store, language, title, old)
        new_parts = _parts(store, new)
        apart = store.item(new_parts[0])["work_id"]
        assert apart != work and store.item(new_parts[0])["tier"] == "arrivals"
        offer = store.new_version_of(new_parts[0])
        assert offer["old"]["epub"] == os.path.abspath(old) and offer["old"]["ids"] == old_parts
        assert offer["new"]["ids"] == new_parts and offer["old"]["title"] == title
        change = store.replace_book(new, old)
        assert change is not None and change.kind == "remove"
        assert all(store.item(p) is None for p in old_parts)
        assert {store.item(p)["work_id"] for p in new_parts} == {work}
        assert {store.item(p)["tier"] for p in new_parts} == {tier}
        assert store.conn.execute("SELECT title FROM works WHERE id = ?", (work,)).fetchone()[0] == title
        rec = _record(store, ab)
        assert rec["book"]["epub"] == os.path.abspath(new)
        _w, rows = _book_items(store, title)
        assert [r[0] for r in rows] == new_parts + [ab], "its parts in order, then its audiobook"
        assert store.new_version_of(new_parts[0]) is None, "replaced: nothing more to offer"
        store.undo(change)
        assert [store.item(p)["work_id"] for p in old_parts] == [work] * len(old_parts)
        assert {store.item(p)["work_id"] for p in new_parts} == {apart}
        assert {store.item(p)["tier"] for p in new_parts} == {"arrivals"}
        assert _record(store, ab)["book"]["epub"] == os.path.abspath(old)


def test_a_new_version_with_another_title_or_in_another_folder_is_never_offered():
    """The controls: another `dc:title` beside it (another book), or the same title in another folder (a copy: the
    learner's own two) — no offer."""
    language = "ja"
    store, old, _ab = _paired(language, NEKO)
    with store:
        other = _epub(os.path.join(os.path.dirname(old), f"{GINGA}.epub"), GINGA, language)
        elsewhere = _new_version(store, language, NEKO, dc_title=NEKO)
        _look(store, language, store.add_source(os.path.dirname(old)), full=True)
        assert store.new_version_of(_parts(store, other)[0]) is None
        assert store.new_version_of(_parts(store, elsewhere)[0]) is None
        assert store.replace_book(elsewhere, elsewhere) is None


def test_a_book_from_before_with_no_mark_is_not_offered():
    language = "ja"
    store, old, _ab = _paired(language, NEKO)
    with store:
        assert store.new_version_of(_parts(store, old)[0]) is None
