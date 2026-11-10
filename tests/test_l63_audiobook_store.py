"""L6.3 with Hon's audiobooks (H-6 / H-7, PROVISIONAL) on the real store: what the window's one rule
(`app/qt/drag.when_done`) answers for a book paired with its audiobook, and what its writes then do — through commands
that already exist (`set_tier(graduated)`, the Finish path's write; `join`), each one command and one undo.

A book beside its audiobook holds ONE more item in its title, right after its last part (`source_type` 'audio',
waiting for Anki Miner: no file, never counted). It is never watched by itself, so the rule reads the book's own files
(`view_rows.to_finish`). What a wrong answer would cost a learner:
  * a book read to its last chapter sitting in Current for good, its audiobook "still to watch";
  * the audiobook left behind in Current when its book finishes (a row nothing can finish), or the finish of the book
    moving what Generate counts;
  * the next part of a split book, waiting in Goal with the audiobook in it, never coming up;
  * an audiobook alone, or one split off by hand, leaving Current by itself.

Every test runs for Japanese and Chinese under the per-test SURASURA_TEST_ROOT, on real files built on disk (an EPUB
of the test resources' text and tagged MP3s: tests/test_audiobook_items.py's builders), proving nothing is asked.
"""
import os

import pytest

from app import library_store as ls
from app.qt import drag
from app.services import view_rows
from tests.test_audiobook_items import (NEKO, SAIYU, _audio_folder, _audio_items, _book_items, _epub, _fit,
                                        _fresh_module_state)  # noqa: F401 (the autouse fixture: a new run each test)
from tests.test_library_store_groups import _members, _piece, _state
from tests.test_library_store_support import pieces_ok
from tests.test_services_search import view_of
from tests.test_sources_scan import _drive, _empty, _look

TITLES = {"ja": NEKO, "zh": SAIYU}
LANGUAGES = tuple(TITLES)


def _paired(language):
    """The book and its audiobook side by side, one look (a sure pair, nothing asked) -> (store, the book's chapter
    ids in order, the audiobook's item id). The caller closes the store."""
    title = TITLES[language]
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _epub(os.path.join(src, "Books", f"{title}.epub"), title, language)
    _audio_folder(os.path.join(src, "Books", title), title, _fit(language))
    root = store.add_source(src)
    _look(store, language, root, first=True)
    _work, rows = _book_items(store, title)
    chapters = [r[0] for r in rows if r[3] != "audio"]
    (audio,) = [r[0] for r in rows if r[3] == "audio"]
    assert len(chapters) >= 4 and rows[-1][0] == audio, "the audiobook is the title's last item"
    return store, chapters, audio


def _row(store, language, item_id):
    """Current's row holding `item_id`, as the reader builds it."""
    view = view_of(store, language)
    return view, next(r for r in view.rows if item_id in drag.ids_of(r))


def _scheduled(store):
    """Every path Generate would read, in its order."""
    return [e["physical_path"] for rows in store.schedule().values() for e in rows]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_book_read_to_its_last_chapter_finishes_by_itself_and_its_audiobook_goes_into_finished_with_it(language):
    """Every chapter watched, the audiobook still waiting: the rule finishes the book by itself (R3), the Finish path's
    one write takes the row's every item — the audiobook lands in Finished right after its book (where the store puts
    an audiobook whose book is all finished, `_audiobook_place`), still waiting — and Generate's list is what it was.
    One undo puts it all back in Current."""
    store, chapters, audio = _paired(language)
    with store:
        assert store.set_watched(chapters[:-1]) is not None
        _view, row = _row(store, language, audio)
        left = [e.id for e in view_rows.to_finish(row.episodes) if not e.watched]
        assert left == chapters[-1:], "the last chapter is the one file left: its Done asks the rule"
        assert store.set_watched(chapters[-1:]) is not None              # the last chapter's Done
        view, row = _row(store, language, audio)
        assert drag.ids_of(row) == chapters + [audio] and not row.episodes[-1].watched
        assert drag.when_done(view, row) == ("finish",)
        assert drag.all_n(row) == len(chapters)
        before, listed = _state(store), _scheduled(store)

        change = store.set_tier(drag.ids_of(row), "graduated")
        assert change is not None
        assert store.ids("graduated") == chapters + [audio], "the audiobook beside its book, in Finished"
        assert store.item(audio)["availability"] == "waiting" and not store.item(audio)["watched"]
        assert _scheduled(store) == listed, "the book's chapters were watched and the audiobook is no text"
        assert not any(r.work_id == row.work_id for r in view_of(store, language).rows), "nothing of it left behind"
        assert pieces_ok(store) is None
        store.undo(change)
        assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_audiobook_paired_days_after_its_book_is_no_sign_the_book_is_still_arriving(language):
    """The audiobook found last week, the book a month ago: its own arrival stamp never reads as "the newest file came
    in on its own lately" (R4) — the book still finishes by itself."""
    store, chapters, audio = _paired(language)
    with store:
        with store._writing():                  # the book taken in a month ago, its audiobook found just now
            store.conn.execute("UPDATE items SET added_at = '2026-09-01T10:00:00.000000Z' WHERE id IN (%s)" %
                               ",".join("?" * len(chapters)), chapters)
            store.conn.execute("UPDATE items SET added_at = ? WHERE id = ?", (ls._now(), audio))
        assert store.set_watched(chapters) is not None
        view, row = _row(store, language, audio)
        eps = row.episodes
        assert view_rows.still_arriving(eps), "with the audiobook, it would read as still arriving"
        assert not view_rows.still_arriving(view_rows.to_finish(eps))
        assert drag.when_done(view, row) == ("finish",)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_audiobook_alone_in_current_never_finishes_by_itself_listened_or_not(language):
    """H-7: an audiobook with no book, dragged into Current — nothing to mark Done; marked listened by hand, it is
    today's *finished with it?*, never a move by itself."""
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    title = TITLES[language]
    _audio_folder(os.path.join(src, "Audio", title), title, 4000)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        (item,) = _audio_items(store)
        assert store.move([item["id"]], "now") is not None
        for watched in (False, True):
            view, row = _row(store, language, item["id"])
            assert view_rows.heard_only(row.episodes) and row.episodes[0].watched == watched
            assert drag.when_done(view, row) == ("offer",)
            if not watched:
                assert store.set_watched([item["id"]]) is not None      # marked listened by hand
        assert store.item(item["id"])["tier"] == "now"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_split_books_first_part_joins_the_part_holding_the_audiobook_then_the_whole_finishes(language):
    """The book split in Current (its audiobook in the later part): the first part, every chapter watched, joins that
    part where it stands (R1: one piece, in order, the audiobook still last); the rest watched, the whole finishes."""
    store, chapters, audio = _paired(language)
    with store:
        piece = _piece(store, chapters[0])
        at = len(chapters) // 2
        assert store.split(piece, chapters[at]) is not None
        second = _piece(store, chapters[at])
        assert _piece(store, audio) == second, "the audiobook rides with the book's last part"
        assert store.set_watched(chapters[:at]) is not None
        view, first = _row(store, language, chapters[0])
        verdict = drag.when_done(view, first)
        assert verdict[0] == "join" and verdict[1] == [second, piece] and verdict[2] is True
        before = _state(store)

        change = store.join(verdict[1], ahead=verdict[2])
        assert change is not None
        assert _members(store, _piece(store, audio)) == chapters + [audio], "one piece, the audiobook still last"
        assert store.set_watched(chapters[at:]) is not None
        view, row = _row(store, language, audio)
        assert drag.when_done(view, row) == ("finish",)
        assert pieces_ok(store) is None
        store.set_watched(chapters[at:], False)
        store.undo(change)
        assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_next_part_waiting_in_goal_with_the_audiobook_comes_up_after_the_part_read(language):
    """R2: the book's later part dragged to Goal (its audiobook with it): Goal's piece numbers from its first chapter
    (the audiobook numbers nothing), so the first part's last Done brings it up after it — one join, one undo."""
    store, chapters, audio = _paired(language)
    with store:
        piece = _piece(store, chapters[0])
        at = len(chapters) // 2
        assert store.split(piece, chapters[at]) is not None
        second = _piece(store, chapters[at])
        assert store.move(chapters[at:] + [audio], "goal") is not None
        assert store.set_watched(chapters[:at]) is not None
        view, first = _row(store, language, chapters[0])
        (tile,) = [w for w in view.goal.works if w.work_id == first.work_id]
        (gp,) = tile.pieces
        assert gp.first == at + 1 and not gp.heard
        verdict = drag.when_done(view, first)
        assert verdict == ("join", [piece, second], False, chapters + [audio], gp.line)
        before = _state(store)

        change = store.join(verdict[1])
        assert change is not None
        assert {store.item(i)["tier"] for i in chapters + [audio]} <= set(ls.CURRENT)
        assert _members(store, piece) == chapters + [audio]
        assert pieces_ok(store) is None
        store.undo(change)
        assert _state(store) == before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_audiobook_split_off_by_hand_is_no_part_the_book_finishes_and_the_audiobook_stays_where_he_put_it(language):
    """The learner split the audiobook into a row of its own (in Current, then in Goal): it is no part of the book —
    never joined to, never waited on — so the book finishes by itself, and the audiobook row stays where it is."""
    store, chapters, audio = _paired(language)
    with store:
        piece = _piece(store, chapters[0])
        assert store.split(piece, audio) is not None
        alone = _piece(store, audio)
        assert alone != piece
        assert store.set_watched(chapters) is not None
        view, book = _row(store, language, chapters[0])
        assert not drag.split_first(view.rows, book)
        assert drag.when_done(view, book) == ("finish",)
        _view, row = _row(store, language, audio)
        assert drag.when_done(_view, row) == ("offer",), "the audiobook row never leaves by itself"

        assert store.move([audio], "goal") is not None
        view, book = _row(store, language, chapters[0])
        (tile,) = [w for w in view.goal.works if w.work_id == book.work_id]
        assert [p.heard for p in tile.pieces] == [True]
        assert drag.when_done(view, book) == ("finish",)
        change = store.set_tier(drag.ids_of(book), "graduated")
        assert change is not None
        assert store.item(audio)["tier"] == "goal", "his audiobook row stays where he put it"
        assert pieces_ok(store) is None
    store.close()
