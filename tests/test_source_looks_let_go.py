"""Settings' *Stop reading* through the window's writer (alpha 4, C-5): `SourceLooks.let_go` keeps the looks off a folder
while `Writer.stop_reading` journals the stop with its Undo — and lets it be read again once the stop is undone.

What a wrong answer would cost a learner: Settings' *Stop reading* had no Undo (a misclick lost the folder's reading for
good unless he found + Add again); through the writer it has one, but a look already reading that folder must still let
go between files, and an undone stop must be read again — never a folder that stays silently unread.

Real Japanese / Chinese texts in two source folders beside the test's data folder; the real store and looks' worker.
"""
import os

import pytest

from app import library_store as ls
from app.services import source_looks
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _items, _look, _text, _write  # noqa: F401


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_let_go_is_never_looked_at_and_is_read_again_once_let_back(language):
    store, data_dir = _empty(language)
    one, two = _drive("one"), _drive("two")
    _write(os.path.join(one, "A", "A - 01.srt"), _text(language, 1, extra="「一」"))
    _write(os.path.join(two, "B", "B - 01.srt"), _text(language, 2, extra="「二」"))
    with store:
        first = store.add_source(one)
        second = store.add_source(two)
        _look(store, language, first, first=True)
        _look(store, language, second, first=True)
        assert _items(store) == 2
    _write(os.path.join(one, "A", "A - 02.srt"), _text(language, 3, extra="「三」"))
    _write(os.path.join(two, "B", "B - 02.srt"), _text(language, 4, extra="「四」"))
    looks = source_looks.SourceLooks(ls.StoreOpener(language, data_dir, store.user_files_dir), language,
                                     kind=lambda _p: "network")
    try:
        assert looks.let_go(first)
        assert looks.let_go(first, language="zh" if language == "ja" else "ja") is False   # another language's
        looks.asked(refreshed=True)
        assert looks.idle(30)
        with ls.open_store(language, data_dir, store.user_files_dir) as s:
            assert _items(s) == 3                                    # B's new episode in, A's never looked at
        assert looks.let_go(first, on=False)
        looks.asked(refreshed=True)
        assert looks.idle(30)
        with ls.open_store(language, data_dir, store.user_files_dir) as s:
            assert _items(s) == 4                                    # read again once its stop is undone
    finally:
        looks.close()
