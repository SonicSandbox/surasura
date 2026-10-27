"""K7 (alpha 4, Mattias's note 7): New arrivals tells apart the parts of one title that sit in different folders —
`SourceLooks.folders(ids, then, detail=True)` names each item's own folder under its source, and `view_rows.Arrival`
carries it (`folder`, set by the window once the looks' worker answers).

What a wrong answer would cost a learner: "point it at the library" with one title split over several folders (a box
set in `Book 1/`, `Book 2/`) showed rows that look identical — the source's name on every chip — so he couldn't tell
which part he was placing. The default answer (the source folder, the chip's word) stays as it was.

Real Japanese / Chinese texts from tests/Test Resources/ in a source folder beside the test's data folder.
"""
import os

import pytest

from app import library_store as ls
from app.services import source_looks
from app.services import view_rows
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _text, _write  # noqa: F401

TITLE = {"ja": "月影の旅人", "zh": "夜市小记"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_parts_of_one_title_in_two_folders_name_their_own_folder_under_the_source(language):
    store, data_dir = _empty(language)
    src = _drive("library")
    title = TITLE[language]
    first = _write(os.path.join(src, title, "1", f"{title} - 01.srt"), _text(language, 1, extra="一"))
    second = _write(os.path.join(src, title, "2", f"{title} - 01.srt"), _text(language, 2, extra="二"))
    top = _write(os.path.join(src, f"{title} - 09.srt"), _text(language, 3, extra="三"))
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
    assert len(ids) == 3
    looks = source_looks.SourceLooks(ls.StoreOpener(language, data_dir, store.user_files_dir, role="window"), language)
    try:
        got = []
        assert looks.folders(ids, got.append, detail=True)
        assert looks.folders(ids, got.append)                     # the chip's answer, as before: the source folder
        assert looks.idle(5)
    finally:
        looks.close()
    detail, plain = got
    rels = sorted(d["rel"] for d in detail.values())
    assert rels == ["", f"{title}/1", f"{title}/2"]
    assert all(d["root"] == src for d in detail.values()) and set(plain.values()) == {src}
    places = {os.path.normcase(d["folder"]) for d in detail.values()}
    assert places == {os.path.normcase(os.path.dirname(p)) for p in (first, second, top)}


def test_an_item_from_no_folder_read_has_no_place_and_an_arrival_carries_none_until_named():
    assert source_looks._where(None, "C:\\x\\a.srt") is None
    assert source_looks._where("D:\\Shows", None) == {"root": "D:\\Shows", "folder": "D:\\Shows", "rel": ""}
    assert "folder" in view_rows.Arrival._fields and view_rows.Arrival._field_defaults["folder"] is None
    assert view_rows.Arrival._field_defaults["episodes"] == ()          # the field before it keeps its default
    assert source_looks._where("D:\\Shows", "D:\\Shows\\..notes\\a.srt")["rel"] == "..notes"   # a folder named so
