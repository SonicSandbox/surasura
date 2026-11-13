"""Mattias's 3.0.6 field report: *A folder on your computer…* from a book's question read the folder (its EPUB and its
audiobook), and the look paired the audiobook with the EPUB found beside it — never the book that asked — leaving it
in New Arrivals. Now the question follows its folder: the audiobook found there joins the book that asked
(`NeedsYou._folder_audiobook`, through `in_folder`), and an audiobook with another copy of the book is named so in the
menus (`audiobook_line`). Pure functions here; the store's side is `tests/test_audiobook_find.py`'s."""
import os

from app.qt import needs, strings


def test_the_audiobook_found_in_the_folder_picked_is_the_one_paired():
    got = {"audiobooks": [{"item_id": 1, "title": "x", "n": 3, "folder": os.path.join("C:\\", "Audio", "Other")},
                          {"item_id": 2, "title": "カラフル", "n": 1,
                           "folder": os.path.join("C:\\", "Book Sync", "カラフル")}]}
    assert needs.in_folder(got, os.path.join("C:\\", "Book Sync", "カラフル"))["item_id"] == 2
    assert needs.in_folder(got, os.path.join("C:\\", "Book Sync"))["item_id"] == 2, "a folder below it counts"
    assert needs.in_folder(got, os.path.join("C:\\", "Book")) is None, "a name that only starts alike doesn't"
    assert needs.in_folder(None, "C:\\") is None and needs.in_folder(got, "") is None


def test_an_audiobook_with_another_copy_of_the_book_says_so():
    plain = {"title": "カラフル", "n": 1}
    assert needs.audiobook_line(plain) == strings.NEEDS_AUDIOBOOK_LINE.format(title="カラフル", n=1)
    moved = dict(plain, elsewhere="カラフル (文春文庫) - 森 絵都")
    assert "now with 「カラフル (文春文庫) - 森 絵都」" in needs.audiobook_line(moved)
