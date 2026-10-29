"""After a *No*: find an audiobook's book, or say it has none (Hon, 3.0 a5-2; Sonic 2026-10-28: "if they select no for the
book, could you have it check / offer that they find the book?") — and the row's 🎧 before its title, its words in its
hover (Sonic: "put the headphones in front of the title, and with the text next to it on hover instead").

The rules are PROVISIONAL (the lead's leans, `tracks/books/work/audiobooks/scope.md` §a5-2); these scenarios hold them:
a *No* that leaves the audiobook alone offers *Find its book…* · *It has no book*; a pick pairs exactly as a *Yes*
pairs and Undo takes it back whole (its records, the answer, its title and place); *It has no book* is kept and never
weighed again; the picker lists the library's books likeliest first and the one said *No* to last; the row's hover
carries the audio's files and length, read again only when an audiobook's item changed.
"""
import os

import pytest

from app import audiobooks
from app import library_store as ls
from app.services import needs, view_rows
from tests.test_audiobook_items import (NEKO, GINGA, _audio_folder, _audio_items, _book_items, _chars, _epub, _fit,
                                        _record, _unsure)
from tests.test_sources_scan import _drive, _empty, _look

BOCCHAN = "坊っちゃん"


def _finds(store):
    return [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_FIND]


def _said_no(language="ja"):
    """An unsure audiobook (`_unsure`: NEKO's narration too fast for its book) answered *No*, with BOCCHAN's book in the
    library too (no title like it: never asked about) -> (store, root, src, its item)."""
    store, data_dir, src = _unsure(language)
    _epub(os.path.join(src, "Books", f"{BOCCHAN}.epub"), BOCCHAN, language, repeat=21)
    store.__enter__()
    root = store.add_source(src)
    _look(store, language, root, first=True)
    item = _audio_items(store)[0]
    assert store.answer_audiobook(item["id"], False)
    _look(store, language, root)
    return store, root, src, item


@pytest.fixture
def said_no():
    store, root, src, item = _said_no()
    yield store, root, src, item
    store.__exit__(None, None, None)


# --- the card after a No ------------------------------------------------------------------------------------------- #
def test_a_no_that_leaves_the_audiobook_alone_offers_to_find_its_book(said_no):
    store, _root, _src, item = said_no
    [find] = _finds(store)
    assert find["item_id"] == item["id"] and find["said_no"] == NEKO
    [entry] = [e for e in needs.entries(None, asks=needs.asks_of(store)) if e.kind == needs.AUDIOBOOK_FIND]
    assert entry.title == f"Which book does the audiobook 「{NEKO}」 read?"
    assert entry.actions == ("find_book", "no_book") and f"Not 「{NEKO}」, you said." in entry.say
    assert "3 files (01.mp3 … 03.mp3)" in entry.say and entry.data["item_id"] == item["id"]


def test_no_find_card_while_another_book_is_asked_about_or_before_any_no():
    """Never two cards for one audiobook: a question open (the next book after a *No*) is the card; an audiobook alone
    nobody said *No* about (no book anywhere) has none — it sits quietly, *Audio only*."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Audio", GINGA), GINGA, 3000)
    _epub(os.path.join(src, "Books", f"{NEKO}.epub"), NEKO, language)
    _epub(os.path.join(src, "Other", f"{NEKO}.epub"), NEKO, language, repeat=30)
    _audio_folder(os.path.join(src, "Audio", NEKO), NEKO, _chars(language) / 1.5)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _finds(store) == []                                     # GINGA alone, never asked: no card
        heard = next(i for i in _audio_items(store) if _record(store, i["id"])["ask"])
        store.answer_audiobook(heard["id"], False)
        _look(store, language, root)
        assert _record(store, heard["id"])["ask"] is not None          # the other edition asked: that card alone
        assert _finds(store) == [] and len(store.audiobook_asks()) == 1


# --- Find its book…: the pick, and its Undo ------------------------------------------------------------------------ #
def _book_epub(store, title):
    return next(b["epub"] for b in store.library_books() if b["title"] == title)


def test_a_picked_book_pairs_exactly_as_a_yes_would(said_no):
    store, root, _src, item = said_no
    epub = _book_epub(store, BOCCHAN)
    change = store.pick_audiobook_book(item["id"], epub)
    assert change is not None and change.kind == "audiobook_pick"
    work, rows = _book_items(store, BOCCHAN)
    assert rows[-1][0] == item["id"] and store.item(item["id"])["work_id"] == work
    assert store.item(item["id"])["availability"] == "waiting"
    rec = _record(store, item["id"])
    assert rec["book"]["how"] == audiobooks.ANSWERED and rec["book"]["epub"] == os.path.abspath(epub)
    assert rec["ask"] is None and store.audiobook_answers()[rec["book"]["key"]] is True
    assert _finds(store) == [] and needs.asks_of(store) == []
    _look(store, "ja", root, full=True)                                # nothing moves it again
    assert store.item(item["id"])["work_id"] == work and _record(store, item["id"])["book"]["how"] == "answered"
    assert store.pick_audiobook_book(item["id"], epub) is None         # paired already: nothing written


def test_undo_takes_the_pick_back_whole(said_no):
    """Its records as they were (alone, the *No* kept), the answer gone, the item in its own title where it stood —
    and the card offers to find its book again."""
    store, _root, _src, item = said_no
    before_rec, before_item = _record(store, item["id"]), store.item(item["id"])
    answers = store.audiobook_answers()
    change = store.pick_audiobook_book(item["id"], _book_epub(store, BOCCHAN))
    undone = store.undo(change)
    assert undone is not None and not undone.notes
    assert _record(store, item["id"]) == before_rec and store.audiobook_answers() == answers
    after = store.item(item["id"])
    assert (after["work_id"], after["tier"]) == (before_item["work_id"], before_item["tier"])
    assert [f["item_id"] for f in _finds(store)] == [item["id"]]


def test_picking_the_book_it_said_no_to_and_undo_puts_the_no_back(said_no):
    store, _root, _src, item = said_no
    [no_key] = [k for k, v in store.audiobook_answers().items() if v is False]
    change = store.pick_audiobook_book(item["id"], _book_epub(store, NEKO))
    assert store.audiobook_answers()[no_key] is True                   # the learner's pick wins over the No
    store.undo(change)
    assert store.audiobook_answers()[no_key] is False


def test_undo_brings_back_the_audiobooks_own_title_after_the_helper_tidied_it(said_no):
    store, _root, _src, item = said_no
    own = store.item(item["id"])["work_id"]
    change = store.pick_audiobook_book(item["id"], _book_epub(store, BOCCHAN))
    assert own in store.tidy_works()                                   # emptied: the helper's run takes it away
    store.undo(change)
    assert store.item(item["id"])["work_id"] == own
    assert store.conn.execute("SELECT 1 FROM works WHERE id = ?", (own,)).fetchone()


def test_undo_leaves_a_pairing_written_since_as_it_is(said_no):
    """The value check: the audiobook paired again since (here: back alone, then picked anew) — the old pick's Undo
    changes nothing, and says so."""
    store, _root, _src, item = said_no
    first = store.pick_audiobook_book(item["id"], _book_epub(store, BOCCHAN))
    store.undo(first)
    second = store.pick_audiobook_book(item["id"], _book_epub(store, NEKO))
    assert second is not None
    late = store.undo(first)
    assert late is not None and late.notes
    assert _record(store, item["id"])["book"]["title"] == NEKO


def test_a_pick_of_a_book_not_in_the_library_writes_nothing(said_no, tmp_path):
    store, _root, _src, item = said_no
    before = _record(store, item["id"])
    assert store.pick_audiobook_book(item["id"], str(tmp_path / "nowhere.epub")) is None
    assert store.pick_audiobook_book(10 ** 6, _book_epub(store, BOCCHAN)) is None
    assert _record(store, item["id"]) == before


def test_the_writer_puts_the_pick_on_the_undo_stack_and_replays_it_from_its_journal():
    import json
    from app.services import moves
    said = []

    class Store:
        def pick_audiobook_book(self, item_id, epub):
            said.append(("pick", item_id, epub))
            return "change"

        def audiobook_no_book(self, item_id):
            said.append(("none", item_id))
            return True
    writer = moves.Writer.__new__(moves.Writer)
    for cmd in ({"op": "audiobook_pick", "ids": [42], "path": "D:/Books/x.epub", "label": "x"},
                {"op": "audiobook_no_book", "ids": [43], "label": "y"}):
        replay = moves._from_entry(json.loads(json.dumps(moves._entry(cmd))))
        assert writer._w32(Store(), replay) == ("change" if cmd["op"] == "audiobook_pick" else None)
    assert said == [("pick", 42, "D:/Books/x.epub"), ("none", 43)]
    assert {"audiobook_pick", "audiobook_no_book"} <= set(moves.JOURNALLED)


# --- It has no book ------------------------------------------------------------------------------------------------ #
def test_it_has_no_book_is_kept_and_never_weighed_again(said_no):
    store, root, src, item = said_no
    assert store.audiobook_no_book(item["id"])
    assert _record(store, item["id"])["no_book"] is True and _finds(store) == []
    _epub(os.path.join(src, "Books", "続", f"{NEKO}.epub"), NEKO, "ja", repeat=30)     # a new edition comes later
    _look(store, "ja", root, full=True)
    rec = _record(store, item["id"])
    assert rec["book"] is None and rec["ask"] is None and needs.asks_of(store) == []
    assert store.audiobook_no_book(item["id"]) is False                # said once: nothing more to write


def test_it_has_no_book_writes_nothing_once_a_look_paired_or_asked_meanwhile(said_no):
    store, _root, _src, item = said_no
    store.pick_audiobook_book(item["id"], _book_epub(store, BOCCHAN))  # (a pairing that came meanwhile)
    assert store.audiobook_no_book(item["id"]) is False
    assert _record(store, item["id"])["book"] is not None and "no_book" not in _record(store, item["id"])


def test_a_renamed_audiobook_keeps_the_learners_word(said_no):
    """D5: its folder renamed — the same item, and still *No* said (its card) or *It has no book* (none)."""
    store, root, src, item = said_no
    os.rename(os.path.join(src, "Audio", NEKO), os.path.join(src, "Audio", NEKO + " 朗読"))
    _look(store, "ja", root, full=True)
    assert [i["id"] for i in _audio_items(store)] == [item["id"]] and _record(store, item["id"])["said_no"] == NEKO
    assert [f["item_id"] for f in _finds(store)] == [item["id"]]
    store.audiobook_no_book(item["id"])
    os.rename(os.path.join(src, "Audio", NEKO + " 朗読"), os.path.join(src, "Audio", NEKO))
    _look(store, "ja", root, full=True)
    assert _record(store, item["id"])["no_book"] is True and _finds(store) == []


# --- the picker's books -------------------------------------------------------------------------------------------- #
def test_the_picker_lists_the_librarys_books_likeliest_first_and_the_one_said_no_to_last(said_no):
    store, _root, _src, item = said_no
    books = store.library_books(item["id"])
    assert [b["title"] for b in books] == [BOCCHAN, NEKO]              # NEKO: like its title, but answered No
    assert all(b["parts"] >= 1 and b["epub"].endswith(".epub") and b["sha256"] for b in books)
    assert [b["title"] for b in store.library_books()] == sorted([BOCCHAN, NEKO], key=ls.search_fold)


def test_the_picker_ranks_a_like_title_and_its_volume_first():
    """No *No* said: the book whose title is the audiobook's comes first, and of a series, its own volume."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    series = "星屑の剣士"
    for n in (1, 2, 3):                                                # one folder: one title, each book by its file
        _epub(os.path.join(src, "Books", f"{series} {n}.epub"), f"{series} {n}", language)
    _epub(os.path.join(src, "Other", f"{BOCCHAN}.epub"), BOCCHAN, language)
    _audio_folder(os.path.join(src, "Audio", f"{series} 第2巻"), f"{series} 第2巻", _fit(language))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        books = store.library_books(item["id"])
        assert [b["title"] for b in books] == [f"{series} 2", f"{series} 1", f"{series} 3", BOCCHAN]


def test_the_picker_never_lists_an_audiobook_or_a_text():
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Audio", GINGA), GINGA, 3000)
    with open(os.path.join(src, "メモ.txt"), "w", encoding="utf-8") as f:
        f.write("吾輩は猫である。名前はまだ無い。\n" * 40)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert store.library_books(_audio_items(store)[0]["id"]) == []


# --- the row's 🎧 and its hover ------------------------------------------------------------------------------------ #
def test_the_hovers_name_each_audiobooks_files_and_length():
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Books", NEKO), NEKO, _fit(language), n=12)
    _epub(os.path.join(src, "Books", f"{NEKO}.epub"), NEKO, language)
    _audio_folder(os.path.join(src, "Audio", GINGA), GINGA, 3000)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        hovers = store.audiobook_hovers()
        by_title = {h["title"]: h for h in hovers.values()}
        assert (by_title[NEKO]["n"], by_title[NEKO]["first"], by_title[NEKO]["last"]) == (12, "01.mp3", "12.mp3")
        assert by_title[NEKO]["paired"] and not by_title[GINGA]["paired"] and by_title[GINGA]["seconds"]


def test_a_row_says_its_files_and_length_in_the_headphones_hover():
    parts = [{"id": i, "tier": "now", "ord": float(i), "rel_path": f"Library/{NEKO}/{NEKO}_0{i}.txt",
              "title": f"{NEKO}_0{i} (1-{i}) 第一章.txt", "source_type": "epub", "availability": "available",
              "work_id": 7, "piece_id": 1} for i in (1, 2)]
    audio = dict(parts[0], id=3, ord=3.0, rel_path=f"Library/{NEKO}/01.mp3", title=NEKO, source_type="audio",
                 availability="waiting",
                 audio={"title": NEKO, "n": 12, "first": "01.mp3", "last": "12.mp3", "seconds": 33120, "paired": True})
    row = view_rows._row(0, "now", parts + [audio], {7: {"id": 7, "title": NEKO, "media_type": "book"}}, {}, {},
                         set(), set(), 20)
    assert row.audio.splitlines()[:2] == [f"🎧 With its audiobook 「{NEKO}」", "12 files (01.mp3 … 12.mp3) · 9 h 12 min"]
    assert row.line == "Parts 1–2" and not view_rows.audio_only(row)
    alone = view_rows._row(0, "now", [dict(audio, work_id=9)], {9: {"id": 9, "title": NEKO + audiobooks.AUDIO_MARK}},
                           {}, {}, set(), set(), 20)
    assert alone.title == NEKO and alone.line == "Audio only · waits for Anki Miner" and view_rows.audio_only(alone)
    assert alone.audio.startswith(f"🎧 Audio only 「{NEKO}」\n12 files") and "Nothing to study here yet" in alone.audio
    plain = view_rows._row(0, "now", parts, {7: {"id": 7, "title": NEKO, "media_type": "book"}}, {}, {}, set(),
                           set(), 20)
    assert plain.audio == "" and not view_rows.audio_only(plain)


def test_the_reader_puts_the_hover_on_an_audiobooks_row_only_when_its_item_changed():
    """S19: a feed without an audiobook's item asks the store nothing; one with it reads the hovers once and puts its
    summary on that row alone."""
    from app.services.library_reader import LibraryReader
    asked = []

    class Handle:
        def audiobook_hovers(self):
            asked.append(1)
            return {3: {"title": NEKO, "n": 2, "first": "01.mp3", "last": "02.mp3", "seconds": 60, "paired": False}}
    reader = LibraryReader.__new__(LibraryReader)
    book = {"id": 1, "source_type": "epub"}
    reader._items = {1: book}
    reader._audio_hovers(Handle(), {"full": False, "items": [book]})
    assert asked == [] and "audio" not in book
    heard = {"id": 3, "source_type": "audio"}
    reader._items[3] = heard
    reader._audio_hovers(Handle(), {"full": False, "items": [heard]})
    assert asked == [1] and heard["audio"]["n"] == 2 and "audio" not in book
    reader._audio_hovers(Handle(), {"full": True, "items": []})
    assert asked == [1, 1]


def test_files_added_feed_the_audiobooks_item_so_its_hover_is_read_again():
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    folder = os.path.join(src, "Audio", GINGA)
    _audio_folder(folder, GINGA, 3000)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        item = _audio_items(store)[0]
        seen = store.read_feed(None, None)["version"]
        from tests.test_audiobooks import _mp3
        from tests.test_audiobook_items import _settle
        _settle(_mp3(os.path.join(folder, "04.mp3"), seconds=600, frames={"TALB": GINGA, "TRCK": "4"}))
        _look(store, language, root)
        feed = store.read_feed(seen, store.meta()["epoch"])
        assert item["id"] in [r["id"] for r in feed["items"]]
        assert store.audiobook_hovers()[item["id"]]["n"] == 4



# --- the review's findings (register R3-*): each a scenario -------------------------------------------------------- #
def test_undo_after_the_audiobook_moved_brings_no_dead_record_back(said_no):
    """R3-1: picked, then its folder renamed (a look records it anew, the old record marked moved) — Undo puts back only
    the pairing on the live record; the moved one stays moved, so the item has ONE live record, alone."""
    store, root, src, item = said_no
    change = store.pick_audiobook_book(item["id"], _book_epub(store, BOCCHAN))
    os.rename(os.path.join(src, "Audio", NEKO), os.path.join(src, "Audio", NEKO + " 朗読"))
    _look(store, "ja", root, full=True)
    store.undo(change)
    rows = store._audiobook_rows(item["id"])
    assert len(rows) == 1 and rows[0][2]["audiobook"]["book"] is None
    assert rows[0][2]["audiobook"]["files"][0].endswith(os.path.join(NEKO + " 朗読", "01.mp3"))
    assert rows[0][2]["audiobook"]["said_no"] == NEKO and [f["item_id"] for f in _finds(store)] == [item["id"]]


def test_undo_keeps_the_files_a_look_recorded_since(said_no):
    """R3-1: picked, then a chapter added (the look records 01–04, the pick kept) — Undo leaves the four files."""
    from tests.test_audiobooks import _mp3
    from tests.test_audiobook_items import _settle
    store, root, src, item = said_no
    change = store.pick_audiobook_book(item["id"], _book_epub(store, BOCCHAN))
    _settle(_mp3(os.path.join(src, "Audio", NEKO, "04.mp3"), seconds=600, frames={"TALB": NEKO, "TRCK": "4"}))
    _look(store, "ja", root)
    assert len(_record(store, item["id"])["files"]) == 4
    store.undo(change)
    rec = _record(store, item["id"])
    assert len(rec["files"]) == 4 and rec["book"] is None and rec["said_no"] == NEKO


def test_undo_after_the_books_title_was_merged_changes_nothing_and_says_so(said_no):
    """R3-3: the item no longer in the title the pick gave it — nothing undone (records, answer and title as they
    are), with the note; never records saying *alone* for an item sitting in a book."""
    store, _root, _src, item = said_no
    change = store.pick_audiobook_book(item["id"], _book_epub(store, BOCCHAN))
    book_work = store.item(item["id"])["work_id"]
    other = _book_items(store, NEKO)[0]
    store.merge_works(other, [book_work])
    answers = store.audiobook_answers()
    late = store.undo(change)
    assert late is not None and late.notes
    assert _record(store, item["id"])["book"] is not None and store.audiobook_answers() == answers
    assert _finds(store) == []


def test_a_new_first_file_keeps_the_learners_word():
    """R3-2: *It has no book*, then a prologue that sorts first (a second record on the item) — still never weighed
    again; and after a *No*, its card stays."""
    from tests.test_audiobooks import _mp3
    from tests.test_audiobook_items import _settle
    store, root, src, item = _said_no()
    try:
        _settle(_mp3(os.path.join(src, "Audio", NEKO, "00.mp3"), seconds=300, frames={"TALB": NEKO, "TRCK": "0"}))
        _look(store, "ja", root)
        assert all(r[2]["audiobook"].get("said_no") == NEKO for r in store._audiobook_rows(item["id"]))
        assert [f["item_id"] for f in _finds(store)] == [item["id"]]
        assert store.audiobook_no_book(item["id"])
        _settle(_mp3(os.path.join(src, "Audio", NEKO, "000.mp3"), seconds=300, frames={"TALB": NEKO, "TRCK": "0"}))
        _look(store, "ja", root)
        _epub(os.path.join(src, "Books", "続", f"{NEKO}.epub"), NEKO, "ja", repeat=30)
        _look(store, "ja", root, full=True)
        assert all(r[2]["audiobook"].get("no_book") for r in store._audiobook_rows(item["id"]))
        assert needs.asks_of(store) == []
    finally:
        store.__exit__(None, None, None)



def test_an_old_picks_undo_never_undoes_a_later_pick_of_another_book_in_the_same_title():
    """The value check by the pick's own key (mutant M4): two books in one title (one folder), A picked and undone,
    then B picked — A's Undo again changes nothing (the item sits in the same title, but its records hold B's key)."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    for n in (1, 2):
        _epub(os.path.join(src, "Books", "星屑の剣士", f"星屑の剣士 {n}.epub"), f"星屑の剣士 {n}", language)
    _audio_folder(os.path.join(src, "Audio", GINGA), GINGA, 3000)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        a, b = [x["epub"] for x in sorted(store.library_books(), key=lambda x: x["epub"])]
        first = store.pick_audiobook_book(item["id"], a)
        store.undo(first)
        second = store.pick_audiobook_book(item["id"], b)
        assert second is not None and store.item(item["id"])["work_id"] == first.works["items"][0][2]
        late = store.undo(first)
        assert late is not None and late.notes
        assert _record(store, item["id"])["book"]["epub"] == os.path.abspath(b)


def test_up_next_and_the_watched_count_read_the_books_own_files_never_its_audiobook():
    """Kura's #200 seam (`view_rows.to_finish`, one rule): a book with its audiobook — *k/n watched* counts the book's
    parts only, and Up Next is the next part (the last part once all are watched), never the waiting audiobook."""
    parts = [{"id": i, "tier": "now", "ord": float(i), "rel_path": f"Library/{NEKO}/{NEKO}_0{i}.txt",
              "title": f"{NEKO}_0{i} (1-{i}) 第一章.txt", "source_type": "epub", "availability": "available",
              "work_id": 7, "piece_id": 1, "watched": i == 1} for i in (1, 2, 3)]
    audio = dict(parts[0], id=4, ord=4.0, rel_path=f"Library/{NEKO}/01.mp3", title=NEKO, source_type="audio",
                 availability="waiting", watched=False)
    works = {7: {"id": 7, "title": NEKO, "media_type": "book"}}
    row = view_rows._row(0, "now", parts + [audio], works, {}, {}, set(), set(), 20)
    assert row.line.endswith("1 of 3 watched") and row.episodes[row.next_index].id == 2 and row.n_watched == 1
    done = [dict(p, watched=True) for p in parts]
    row = view_rows._row(0, "now", done + [audio], works, {}, {}, set(), set(), 20)
    assert row.episodes[row.next_index].id == 3 and "watched" not in row.line
    alone = view_rows._row(0, "now", [dict(audio, work_id=9)], {9: {"id": 9, "title": NEKO}}, {}, {}, set(), set(),
                           20)
    assert alone.next_index == 0 and view_rows.audio_only(alone) == view_rows.heard_only(alone.episodes) is True
