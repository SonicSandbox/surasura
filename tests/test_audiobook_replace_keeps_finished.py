"""A new version's *Replace* keeps the old one's read parts (Kura-AB6; Sonic 2026-11-21, words PROVISIONAL).

Kura-AB5's *Replace 「…」* (New arrivals' ⋯ on a book's new version) sent every part of the old version to Removed —
the Finished ones too, and with them their Finished dates (`graduated_at`: the Best ranking's recency). Sonic's ruling:
keep the Finished parts and their dates; replace only the unread ones. So:

- a Finished part stays in Finished, in the book's title, its date as it was; a part marked ✓ Done (read, not yet
  Finished) stays where it is, marked (PROVISIONAL: "read" is Finished or ✓ Done);
- a part not read — in Current (in progress) or in Soon / 6+ Months — goes to Removed, as before, its copy to the trash;
- the new version's parts join the title where the last replaced part stood, its audiobook follows (as before);
- ONE Undo puts it all back exactly: every tier's order, the dates, the marks, the audiobook;
- a book with nothing unread is no replacement (nothing offered, nothing written).

Real EPUBs of the suite's Japanese and Chinese sentences, real MP3s with real lengths, read by real looks into a real
store; nothing in the learner's folders is written (`_look`).
"""
import os
import time

import pytest

from app import library_store as ls
from app.services import moves as M
from tests import services_helpers as h
from tests.test_audiobook_book_gone import _parts
from tests.test_audiobook_folder_pick import _picked, _untagged
from tests.test_audiobook_items import (NEKO, SAIYU, _audio_items, _epub, _fit, _fresh_module_state,  # noqa: F401
                                        _record)
from tests.test_services_moves import Heard, WORDS
from tests.test_sources_scan import _drive, _empty, _look

TIERS = ("arrivals", "now", "soon", "goal", "graduated")


def _book(language, title):
    """(store, old epub, audiobook item) — a four-part book read where it is (setup's first look: Current), its
    audiobook paired by the book's own *A folder on your computer…*; then the learner's reading: part 1 Finished,
    part 2 ✓ Done in Current, part 3 in Current (in progress), part 4 moved to 6+ Months (unread)."""
    store, _data = _empty(language)
    books = _drive("books")
    epub = _epub(os.path.join(books, f"{title}.epub"), title, language, repeat=15, chapters=4)
    _look(store, language, store.add_source(books), first=True)
    audio = os.path.join(_drive("audio"), "audiobook")
    _untagged(audio, _fit(language))
    _picked(store, language, audio, epub, title)
    (item,) = _audio_items(store)
    parts = _parts(store, epub)
    assert len(parts) == 4, parts
    store.finish([parts[0]])
    store.set_watched([parts[1]])
    store.set_tier([parts[3]], "goal")
    return store, epub, item["id"]


def _new_beside(store, language, title, old):
    """The new version in the OLD one's folder, its package titled as the old one's (`dc:title`) -> its path."""
    epub = _epub(os.path.join(os.path.dirname(old), f"{title}-章分割-注なし.epub"), title, language, repeat=22)
    _look(store, language, store.add_source(os.path.dirname(old)), full=True)
    return epub


def _state(store, ids):
    """Each item's tier, title, Finished date and ✓ Done mark (None: not in the library)."""
    out = {}
    for i in ids:
        row = store.conn.execute("SELECT tier, work_id, graduated_at, watched FROM items WHERE id = ?",
                                 (i,)).fetchone()
        out[i] = tuple(row) if row else None
    return out


def _orders(store):
    return {t: store.ids(t) for t in TIERS}


@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_replace_keeps_the_finished_and_done_parts_and_replaces_only_the_unread(language, title):
    """Sonic's ruling: *Replace* keeps the Finished part (in Finished, in the book's title, its Finished date as it
    was) and the ✓ Done one (where it was, marked); the in-progress part (Current, not Done) and the unread one (6+ Months)
    go to Removed; the new parts join the title where the last replaced part stood; the audiobook follows."""
    store, old, ab = _book(language, title)
    with store:
        p1, p2, p3, p4 = _parts(store, old)
        before = _state(store, (p1, p2))
        work = before[p1][1]
        finished_at = before[p1][2]
        assert before[p1][0] == "graduated" and finished_at, "part 1 Finished, dated"
        assert before[p2][0] == "now" and before[p2][3] == 1, "part 2 ✓ Done in Current"
        new = _new_beside(store, language, title, old)
        new_parts = _parts(store, new)
        offer = store.new_version_of(new_parts[0])
        assert offer["old"]["ids"] == [p1, p2, p3, p4], "the whole book still named"
        change = store.replace_book(new, old)
        assert change is not None and change.kind == "remove"
        assert _state(store, (p1, p2)) == before, "the read parts kept: tier, title, Finished date, ✓ Done"
        assert store.item(p3) is None and store.item(p4) is None, "the unread parts replaced"
        assert [e["count"] for e in store.removed()] == [2]
        assert {store.item(p)["work_id"] for p in new_parts} == {work}, "the new version in the book's title"
        assert {store.item(p)["tier"] for p in new_parts} == {"goal"}, "where the last replaced part stood"
        assert store.conn.execute("SELECT title FROM works WHERE id = ?", (work,)).fetchone()[0] == title
        assert _record(store, ab)["book"]["epub"] == os.path.abspath(new), "its audiobook follows"
        assert store.new_version_of(new_parts[0]) is None, "replaced: nothing more to offer"
        assert offer["old"].get("replaced") == [p3, p4] and offer["old"].get("kept") == [p1, p2], "the menu's tip"


@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_one_undo_of_a_replace_that_kept_parts_puts_everything_back_exactly(language, title):
    """ONE Undo: every tier's order as it was before the press (the replaced parts back in Current and 6+ Months, the new
    version back in New arrivals as a title of its own), the kept parts untouched (their Finished date, their mark),
    the audiobook back with the old version."""
    store, old, ab = _book(language, title)
    with store:
        p1, p2, p3, p4 = _parts(store, old)
        new = _new_beside(store, language, title, old)
        new_parts = _parts(store, new)
        orders, states = _orders(store), _state(store, [p1, p2, p3, p4] + new_parts)
        change = store.replace_book(new, old)
        assert change is not None
        store.undo(change)
        assert _orders(store) == orders
        assert _state(store, [p1, p2, p3, p4] + new_parts) == states
        assert _record(store, ab)["book"]["epub"] == os.path.abspath(old)
        assert store.new_version_of(new_parts[0]) is not None, "offered again after the Undo"


def test_a_book_with_nothing_unread_is_no_replacement():
    """Every part Finished or ✓ Done: nothing to replace — no *Replace* offered, and a press that comes anyway writes
    nothing (the new version stays a title of its own, the audiobook with the old one). PROVISIONAL."""
    language = "ja"
    store, old, ab = _book(language, NEKO)
    with store:
        p1, p2, p3, p4 = _parts(store, old)
        store.finish([p3, p4])
        new = _new_beside(store, language, NEKO, old)
        new_parts = _parts(store, new)
        orders, states = _orders(store), _state(store, [p1, p2, p3, p4] + new_parts)
        assert store.new_version_of(new_parts[0]) is None
        assert store.replace_book(new, old) is None
        assert _orders(store) == orders and _state(store, [p1, p2, p3, p4] + new_parts) == states
        assert _record(store, ab)["book"]["epub"] == os.path.abspath(old)


@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_the_writers_replace_trashes_only_the_replaced_parts_copies(language, title):
    """The window's press (`Writer.replace_book`): the replaced parts' copies go to the trash, the kept parts' copies
    stay where they are — even when the window's ids (read as ⋯ opened) still named a part Finished since — and the
    toast's Undo brings the copies back."""
    store, old, _ab = _book(language, title)
    data_dir = store.data_dir
    with store:
        p1, p2, p3, p4 = _parts(store, old)
        new = _new_beside(store, language, title, old)
        offer = store.new_version_of(_parts(store, new)[0])
        files = {p: os.path.join(data_dir, *store.item(p)["rel_path"].split("/")) for p in (p1, p2, p3, p4)}
        assert all(os.path.exists(f) for f in files.values())
        store.finish([p3])                                   # Finished after ⋯ opened: the window's ids are stale
    store.close()
    heard = Heard()
    w = M.Writer(ls.StoreOpener(language, data_dir, store.user_files_dir, role="window"), language,
                 journal_file=M.journal_path(language), retry=0.05, words=WORDS, **heard.kw())
    w.start()
    try:
        w.replace_book(offer["old"].get("replaced", offer["old"]["ids"]), new, old, label="replaced")
        assert h.until(lambda: heard.saved or heard.notes)
        assert heard.notes == [] and len(heard.saved) == 1
        assert all(os.path.exists(files[p]) for p in (p1, p2, p3)), "kept parts' copies stay"
        assert not os.path.exists(files[p4]), "the replaced part's copy in the trash"
        w.undo()
        assert h.until(lambda: heard.undone)
        assert all(os.path.exists(f) for f in files.values())
    finally:
        w.finish(time.monotonic() + 5)
    with ls.open_store(language, data_dir, store.user_files_dir) as again:
        assert again.item(p3)["tier"] == "graduated" and again.item(p4)["tier"] == "goal"
