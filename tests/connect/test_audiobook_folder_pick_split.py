"""A 2.x split book's audiobook picked by its folder joins THAT book (Kura-AB4; based on the diagnosis in #419 by
Mattias — his カラフル, PROVISIONAL words).

His case: a book of 2.x `.txt` parts (Kura-TX's split book) asked for its audiobook; he picked the folder holding the
book's EPUB AND its `.m4b`. Three things went wrong, each held here:

- (a) the look took the EPUB in as a second copy of the book and paired the audiobook with that copy (sure: the same
  title, side by side) — never with the book that asked;
- (b) the look's books (`_Look._library_books`) are EPUBs only: the split book was never weighed at all;
- (c) *Pick its audiobook…* listed only audiobooks with no book — once paired with the copy, the book that asked could
  never have it.

Now the folder picked names the book (`sources.scan`'s `book`): its audiobook joins the split book whatever else the
folder holds; one already paired with a copy of this very title is listed (*· now with 「…」*) and picked from it
(`pick_audiobook_book(replace=True)`, its Undo pairs it back) — never one with another book's title. Real data: 芥川
「蜘蛛の糸」 as 2.x split it, a real EPUB of the same title and a real M4B; the learner's folders proven untouched.
"""
import os

import pytest

from app import audiobooks, library_store as ls
from app.connect import library
from app.services import source_looks
from tests.connect.test_split_txt_books import TITLE, _joined, _tree, split  # noqa: F401  (the fixture)
from tests.test_audiobook_items import GINGA, _audio_folder, _audio_items, _epub, _fit, _record, _settle
from tests.test_audiobooks import _m4b
from tests.test_sources_scan import _drive, _look


def _folder_with_epub_and_m4b():
    """The folder Mattias picked: the book's EPUB (a copy of the book he has as 2.x parts) and its `.m4b`, side by
    side — the same title, a length a narrator reads it in."""
    folder = _drive("kumo")
    _epub(os.path.join(folder, f"{TITLE}.epub"), TITLE, "ja")
    m4b = _m4b(os.path.join(folder, f"{TITLE}.m4b"), audiobooks.MIN_SECONDS + 600, tags={"album": TITLE})
    _settle(m4b)
    return folder, m4b


def _audio_of(store, path):
    return next(i for i in _audio_items(store) if os.path.abspath(path) in _record(store, i["id"])["files"])


def _work(store, item_id):
    return store.conn.execute("SELECT work_id FROM items WHERE id = ?", (item_id,)).fetchone()[0]


def _copy_paired(split):
    """(a)'s state, as 3.0.6 left Mattias: the folder read with no book named — its audiobook paired with the copy."""
    folder, m4b = _folder_with_epub_and_m4b()
    with split["steps"]._open("ja") as store:
        _look(store, "ja", store.add_source(folder), full=True)
        item = _audio_of(store, m4b)
        rec = _record(store, item["id"])
    assert rec["book"] and rec["book"]["epub"] == os.path.abspath(os.path.join(folder, f"{TITLE}.epub")), \
        "3.0.6: paired with the EPUB copy beside it"
    return folder, m4b, item["id"]


def test_a_the_split_books_folder_pick_joins_its_audiobook_to_that_book_never_the_copy_beside_it(split):
    """(a) + (b): the split book's *A folder on your computer…*, the folder holding the EPUB copy and the `.m4b`: the
    audiobook joins the split book (its joined `.txt`, the key Connect lines it up by), in its parts' title — though
    the copy beside it has the same title, and the split book is no EPUB the look could weigh."""
    _reading, book = _joined(split)
    folder, m4b = _folder_with_epub_and_m4b()
    before = _tree(folder)
    with split["steps"]._open("ja") as store:
        _look(store, "ja", store.add_source(folder), full=True,
              book={"folder": folder, "epub": book, "title": TITLE})
        item = _audio_of(store, m4b)
        rec = _record(store, item["id"])
        assert rec["book"]["epub"] == os.path.abspath(book) and rec["book"]["how"] == "answered"
        assert _work(store, item["id"]) == _work(store, split["parts"][0]), "in the split book's title"
        assert library.audiobook_of_book(store, book)["item_id"] == item["id"]
        assert item["tier"] == store.item(split["parts"][-1])["tier"], "beside its parts, wherever they are"
    assert _tree(folder) == before, "the learner's folder as it was"


def test_c_pick_its_audiobook_lists_one_paired_with_a_copy_of_this_title_and_the_pick_takes_it_with_undo(split):
    """(c): after 3.0.6 paired it with the copy, the split book's *Pick its audiobook…* lists it (*· now with
    「…」*), after the free ones; a pick without `replace` writes nothing, with it the audiobook joins the split book;
    its Undo pairs it with the copy again, in the copy's title."""
    _reading, book = _joined(split)
    folder, _m4b_path, audio = _copy_paired(split)
    copy = os.path.abspath(os.path.join(folder, f"{TITLE}.epub"))
    with split["steps"]._open("ja") as store:
        copy_work = _work(store, audio)
        offered = store.book_audiobooks(split["parts"][0])
        lines = [(a["item_id"], a.get("elsewhere")) for a in offered["audiobooks"]]
        assert lines == [(split["audio"], None), (audio, TITLE)], "the free one first, then the copy's"
        assert store.pick_audiobook_book(audio, book) is None, "never taken from a book unasked"
        copy_key = _record(store, audio)["book"]["key"]
        was = store.audiobook_answers().get(copy_key)
        change = store.pick_audiobook_book(audio, book, replace=True)
        assert change is not None
        assert store.audiobook_answers()[copy_key] is False, "the copy's pair kept No: never given back by a weighing"
        assert _record(store, audio)["book"]["epub"] == os.path.abspath(book)
        assert _work(store, audio) == _work(store, split["parts"][0])
        assert store.pick_audiobook_book(audio, book, replace=True) is None, "never to the book it is with"
        store.undo(change)
        assert _record(store, audio)["book"]["epub"] == copy and _work(store, audio) == copy_work
        assert store.audiobook_answers().get(copy_key) == was, "its answer as it was"


def test_c_an_audiobook_with_a_book_of_another_title_is_never_offered(split):
    """Only a copy of this very title: 「銀河鉄道の夜」's audiobook, paired with its own book, is never listed for
    「蜘蛛の糸」 — picking it would take a learner's right pair apart."""
    other = _drive("ginga")
    _epub(os.path.join(other, f"{GINGA}.epub"), GINGA, "ja")
    _audio_folder(os.path.join(other, GINGA), GINGA, _fit("ja"))
    with split["steps"]._open("ja") as store:
        _look(store, "ja", store.add_source(other), full=True)
        assert any(_record(store, i["id"])["book"] for i in _audio_items(store))
        offered = store.book_audiobooks(split["parts"][0])
        assert [a["item_id"] for a in offered["audiobooks"]] == [split["audio"]]


def test_c_the_same_folder_picked_again_names_the_audiobook_with_the_copy(split):
    """(c), by the folder: Mattias picks that folder again from the split book's question — the looks' answer names
    the audiobook as with a copy of this title (`elsewhere`), the window then takes it with its pick (Undo)."""
    _reading, book = _joined(split)
    folder, _m4b_path, audio = _copy_paired(split)
    with split["steps"]._open("ja") as store:
        said = source_looks._audiobooks_read(store, folder, {"epub": book, "title": TITLE})
    assert said == {"joined": [], "alone": [], "asks": [],
                    "elsewhere": [{"item_id": audio, "book": TITLE, "how": audiobooks.SURE}]}   # a look's own pair
    with split["steps"]._open("ja") as store:
        said = source_looks._audiobooks_read(store, folder, {"epub": book, "title": GINGA})
    assert said["elsewhere"] == [], "another title's book: never named to be taken"
