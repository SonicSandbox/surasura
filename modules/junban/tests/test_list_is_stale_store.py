# SPDX-License-Identifier: GPL-3.0-or-later
"""Junban's "the library changed since the last analysis" in store mode (Library_Store_Spec §7, WP-L6 #4; L2.1).

With a library store, `list_is_stale` is the store's "journey pending" — the order the last Generate read
(`analysed_order_version`) is older than the library's (`order_version`) — instead of the manifest's mtime: the
copy is rewritten by the helper on its own schedule, so its mtime no longer says when the library changed. The 4
mtime tests (test_auto, test_orders, test_reposition) keep the rule for the other modes: they run with no store.

Synthetic library under the test's SURASURA_TEST_ROOT (this suite's conftest), real Japanese and Chinese names
from tests/Test Resources/; never Anki.
"""
import os

import pytest

from app import library_store as ls
from modules.junban import reposition
from tests.test_library_store_support import LANGUAGES, library, roots, write_manifest

LONG_AGO = 946684800   # 2000-01-01


def _list(csv_mtime=None):
    path = reposition.priority_csv_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("Word,Score\n")
    if csv_mtime is not None:
        os.utime(path, (csv_mtime, csv_mtime))
    return path


def _store(language):
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    assert ls.maintain(language, data_dir, user_files_dir) == ls.EXIT_DONE
    return ls.open_store(language, data_dir, user_files_dir)


@pytest.mark.parametrize("language", LANGUAGES)
def test_in_store_mode_staleness_is_journey_pending_not_the_copys_mtime(language):
    """A list older than the copy is NOT stale while the store says the last Generate read the current order;
    a move makes it stale; recording that order as analysed (Generate, or the journey check) clears it."""
    store = _store(language)
    with store:
        store.record_analysed(store.versions()["order_version"])
        _list(csv_mtime=LONG_AGO)                         # older than the copy the helper just wrote
        assert reposition.list_is_stale(language) is False, "the copy's mtime is not the library's"

        store.move([store.ids("now")[0]], "soon")
        assert reposition.list_is_stale(language) is True

        store.record_analysed(store.versions()["order_version"])
        assert reposition.list_is_stale(language) is False


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_missing_list_is_still_preflights_question_in_store_mode(language):
    store = _store(language)
    with store:
        store.move([store.ids("now")[0]], "soon")
        assert store.journey_pending()
    assert not os.path.exists(reposition.priority_csv_path())
    assert reposition.list_is_stale(language) is False


@pytest.mark.parametrize("language", LANGUAGES)
def test_without_a_store_the_mtime_rule_stands(language):
    """JSON mode (no store yet, or none can be opened): the manifest newer than the list is stale, as before."""
    data_dir, user_files_dir, doc = library(language)
    write_manifest(user_files_dir, doc)
    _list(csv_mtime=LONG_AGO)
    assert not os.path.exists(ls.library_db_path(language, roots(language)[0]))
    assert reposition.list_is_stale(language) is True
