"""A split book keeps its audiobook on every part (Hon-S, alpha 9.1 try round 1; Sonic's report 2 in J2RFRS: "The
陰の実力者になりたくて！ split doesn't include the audiobook for the entire thing. For some reason only the second one has it
(i split it so this seems odd behavior)").

An audiobook beside its book is ONE waiting item, placed after the book's last part (H-6), so any split leaves that item
in one part only — the later one. Its pairing (the record's `book`, the EPUB) never changed; only the 🎧 was drawn from
the item's place. The rule now (PROVISIONAL, the card's lean): every row holding a part of a paired book shows its
audiobook — the 🎧 before its title, its hover — read from the pairing, so ✂ *Split here*, *Not part of this title*
and a part moved away all keep it; a book of its own volume keeps its own audiobook (each audiobook pairs with one EPUB).
Within one book the audio's files can't be told apart by part, so both parts keep the whole pairing, and the part
without the item says where its files are listed.
"""
import os

import pytest

from app.services import view_rows
from app.services.library_reader import LibraryReader
from tests.test_audiobook_items import NEKO, _audio_folder, _book_items, _epub, _fit
from tests.test_sources_scan import _drive, _empty, _look

WITH = f"🎧 With its audiobook 「{NEKO}」"
ELSEWHERE = view_rows.STRINGS["audio_other_part"]


@pytest.fixture
def paired():
    """NEKO's EPUB (three chapters: three parts) and its chapter MP3s, paired in one look -> (store, parts, heard)."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _epub(os.path.join(src, "Books", f"{NEKO}.epub"), NEKO, language)
    _audio_folder(os.path.join(src, "Books", NEKO), NEKO, _fit(language))
    store.__enter__()
    root = store.add_source(src)
    _look(store, language, root, first=True)
    _work, rows = _book_items(store, NEKO)
    parts = [r[0] for r in rows if r[3] != "audio"]
    heard = [r[0] for r in rows if r[3] == "audio"]
    assert len(parts) >= 3 and len(heard) == 1 and rows[-1][0] == heard[0]     # the item after the book's last part
    yield store, parts, heard[0]
    store.__exit__(None, None, None)


def _read(reader, store):
    """One look of the window's reader: the feed since its last, merged, the 🎧 summaries put on (its `_look`'s steps)."""
    feed = store.read_feed(reader._seen, reader._epoch)
    fresh = () if feed["full"] else [r for r in feed["items"] if r["id"] not in reader._items]
    reader._merge(feed)
    reader._audio_hovers(store, feed, fresh)
    return feed


def _tips(reader, ids):
    """{piece id: the 🎧 hover of the row its items make} for the rows holding `ids` (the book's parts and its audio)."""
    pieces = {}
    for r in sorted(reader._items.values(), key=lambda r: (r["tier"], r["ord"], r["id"])):
        if r["id"] in ids:
            pieces.setdefault(r["piece_id"], []).append(r)
    return {p: view_rows.audio_tip(rows) for p, rows in pieces.items()}


def test_the_hovers_name_the_books_parts_each_audiobook_belongs_to(paired):
    store, parts, heard = paired
    assert store.audiobook_hovers()[heard]["parts"] == sorted(parts)


def test_split_here_keeps_the_audiobook_on_both_parts(paired):
    """Sonic's case: ✂ after the book's first part — the earlier part had no 🎧. Now both have it; the item stays with
    the later part (nothing moves), and the earlier part's hover says its files are listed there."""
    store, parts, heard = paired
    reader = LibraryReader(None)
    _read(reader, store)
    piece = store.item(parts[0])["piece_id"]
    assert list(_tips(reader, parts + [heard]).values()) == [view_rows.audio_tip(
        [reader._items[i] for i in parts + [heard]])]                                   # one row, its 🎧
    assert store.split(piece, parts[1]) is not None
    _read(reader, store)
    tips = _tips(reader, parts + [heard])
    assert len(tips) == 2
    first, second = tips[piece], next(t for p, t in tips.items() if p != piece)
    assert first.startswith(WITH) and ELSEWHERE in first                               # the earlier part keeps it
    assert second.startswith(WITH) and ELSEWHERE not in second                         # the item's own part
    assert store.item(heard)["piece_id"] != piece                                      # nothing moved


def test_not_part_of_this_title_keeps_the_books_audiobook_on_the_part_taken_out(paired):
    """*Not part of this title* on the first part: a new title for it — still the book's part, still its audiobook's."""
    store, parts, heard = paired
    reader = LibraryReader(None)
    _read(reader, store)
    assert store.split_work([parts[0]], "吾輩は猫である 序") is not None
    _read(reader, store)
    tips = _tips(reader, parts + [heard])
    assert len(tips) == 2 and all(t.startswith(WITH) for t in tips.values())
    assert tips[store.item(parts[0])["piece_id"]].endswith(ELSEWHERE)


def test_a_part_moved_away_keeps_the_audiobook_too(paired):
    """The book's first part moved into Goal: a piece of its own there — both rows keep the 🎧."""
    store, parts, heard = paired
    reader = LibraryReader(None)
    _read(reader, store)
    assert store.item(parts[0])["tier"] != "goal"
    assert store.move([parts[0]], "goal") is not None
    assert store.item(parts[0])["piece_id"] != store.item(parts[1])["piece_id"]
    _read(reader, store)
    tips = _tips(reader, parts + [heard])
    assert len(tips) == 2 and all(t.startswith(WITH) for t in tips.values())


class _Opener:
    """The window's opener over the test's own store (same thread): `LibraryReader._look` runs as in the window."""

    reason = None

    def __init__(self, store):
        self.store = store

    def check(self):
        return "store"

    def handle(self):
        return self.store


def test_the_readers_own_look_draws_the_headphones_on_every_part_and_on_a_part_arriving_later(paired):
    """Through `_look` itself (review A1-2: the feed's new items worked out before the merge): ✂ — both rows built
    with the 🎧; then a part arriving in the earlier part's title is marked at once (the hovers read again for it)."""
    store, parts, heard = paired
    reader = LibraryReader(_Opener(store))
    reader._look()
    assert [r.audio.startswith(WITH) for r in reader._view.rows] == [True]
    piece = store.item(parts[0])["piece_id"]
    store.split(piece, parts[1])
    reader._data_version = None          # one connection: its own commit moves no `data_version` (the window's would)
    reader._look()
    rows = [r for r in reader._view.rows if r.work_id == store.item(parts[0])["work_id"]]
    assert len(rows) == 2 and all(r.audio.startswith(WITH) for r in rows)
    assert [ELSEWHERE in r.audio for r in rows] == [True, False]
    # a new item in the earlier part's title (as a re-read book's new part would come): the next look's feed brings it
    # (the store's feed, with that row added), the hovers are read again for it, and it is marked
    new = {k: v for k, v in reader._items[parts[0]].items() if k != "book_audio"}
    new.update(id=10_001, ord=new["ord"] - 0.5)
    hovers, read_feed, asked = store.audiobook_hovers, store.read_feed, []

    def counted():
        asked.append(1)
        out = hovers()
        out[heard] = dict(out[heard], parts=sorted(out[heard]["parts"] + [10_001]))
        return out

    def with_new(seen, epoch):
        feed = read_feed(seen, epoch)
        return dict(feed, full=False, items=list(feed["items"]) + [dict(new)])
    store.audiobook_hovers, store.read_feed = counted, with_new
    reader._data_version = None
    reader._look()
    assert asked == [1] and reader._items[10_001]["book_audio"]["title"] == NEKO


def test_a_book_without_an_audiobook_shows_none():
    """The plain case stays plain: a part with no `book_audio` and no audio item has no 🎧."""
    rows = [{"id": i, "source_type": "epub", "availability": "available"} for i in (1, 2)]
    assert view_rows.audio_tip(rows) == ""


# --- the reader: only what changed (S19) ----------------------------------------------------------------------------- #
class _Handle:
    """The store's two answers the reader asks here: the hovers (counted) and nothing else."""

    def __init__(self, hovers):
        self.hovers, self.asked = hovers, 0

    def audiobook_hovers(self):
        self.asked += 1
        return self.hovers


def _said(parts):
    return {4: {"title": NEKO, "n": 3, "first": "01.mp3", "last": "03.mp3", "seconds": 60, "paired": True,
                "transcript": None, "parts": parts}}


def _rows():
    parts = [{"id": i, "tier": "now", "ord": float(i), "source_type": "epub", "availability": "available",
              "work_id": 7, "piece_id": 1 if i < 3 else 2} for i in (1, 2, 3)]
    return parts + [dict(parts[-1], id=4, ord=4.0, source_type="audio", availability="waiting")]


def _feed(rows, full=False, gone=()):
    return {"full": full, "items": rows, "works": [], "gone": list(gone), "version": 1, "epoch": 1}


def test_the_reader_marks_the_parts_and_swaps_only_a_row_whose_mark_changed():
    reader = LibraryReader(None)
    handle = _Handle(_said([1, 2, 3]))
    rows = _rows()
    reader._merge(_feed(rows, full=True))
    reader._audio_hovers(handle, _feed(rows, full=True))
    assert handle.asked == 1 and all(reader._items[i]["book_audio"]["title"] == NEKO for i in (1, 2, 3))
    assert "parts" not in reader._items[1]["book_audio"]
    other = {"id": 10, "tier": "now", "ord": 10.0, "source_type": "subtitle", "work_id": 8, "piece_id": 5}
    reader._merge(_feed([other]))
    reader._audio_hovers(handle, _feed([other]), [other])
    kept = {i: reader._items[i] for i in (1, 2, 3, 10)}
    # the audiobook's item fed with nothing changed (its hovers read again): every row keeps its object (S19)
    reader._build_changed = set()
    audio = dict(reader._items[4])
    reader._merge(_feed([audio]))
    reader._audio_hovers(handle, _feed([audio]))
    assert handle.asked == 2 and all(reader._items[i] is kept[i] for i in kept)
    assert reader._build_changed == {4}
    # the audiobook unpaired: its item fed, part 1 and 2 not — they are swapped for new rows without the mark; the
    # other title's row is left alone
    handle.hovers = {4: dict(_said([])[4], paired=False)}
    audio = dict(reader._items[4])
    reader._merge(_feed([audio]))
    reader._audio_hovers(handle, _feed([audio]))
    assert handle.asked == 3
    assert all("book_audio" not in reader._items[i] for i in (1, 2, 3))
    assert all(reader._items[i] is not kept[i] for i in (1, 2, 3)) and reader._items[10] is kept[10]
    assert reader._build_changed == {1, 2, 3, 4}                                       # rebuilt: those rows only


def test_a_feed_without_the_audiobook_asks_nothing_and_keeps_the_mark_on_the_parts_it_brings():
    reader = LibraryReader(None)
    handle = _Handle(_said([1, 2, 3]))
    rows = _rows()
    reader._merge(_feed(rows, full=True))
    reader._audio_hovers(handle, _feed(rows, full=True))
    moved = dict(reader._items[1], piece_id=9)
    moved.pop("book_audio")                                  # the store's feed row: no mark of its own
    fresh = [r for r in [moved] if r["id"] not in reader._items]
    reader._merge(_feed([moved]))
    reader._audio_hovers(handle, _feed([moved]), fresh)
    assert handle.asked == 1 and reader._items[1]["book_audio"]["title"] == NEKO


def test_a_new_item_in_the_books_title_or_the_audiobook_gone_reads_the_hovers_again():
    reader = LibraryReader(None)
    handle = _Handle(_said([1, 2, 3]))
    rows = _rows()
    reader._merge(_feed(rows, full=True))
    reader._audio_hovers(handle, _feed(rows, full=True))
    other = {"id": 20, "tier": "now", "ord": 20.0, "source_type": "subtitle", "work_id": 8, "piece_id": 5}
    reader._merge(_feed([other]))
    reader._audio_hovers(handle, _feed([other]), [other])
    assert handle.asked == 1                                 # another title's new file: nothing asked
    handle.hovers = _said([1, 2, 3, 21])
    new = dict(rows[0], id=21, ord=2.5)
    new.pop("book_audio", None)
    reader._merge(_feed([new]))
    reader._audio_hovers(handle, _feed([new]), [new])
    assert handle.asked == 2 and reader._items[21]["book_audio"]["title"] == NEKO
    handle.hovers = {}
    reader._merge(_feed([], gone=[("item", 4)]))
    reader._audio_hovers(handle, _feed([], gone=[("item", 4)]))
    assert handle.asked == 3 and all("book_audio" not in reader._items[i] for i in (1, 2, 3, 21))


def test_a_new_item_in_the_audiobooks_own_title_reads_the_hovers_again():
    """Review A1-4: every part taken out into another title, the audiobook's item left alone in its own — a new part
    coming into that title is read again too (the audiobook's title counts as its parts' do)."""
    reader = LibraryReader(None)
    handle = _Handle(_said([1, 2, 3]))
    rows = [dict(r, work_id=9 if r["id"] == 4 else 7) for r in _rows()]
    reader._merge(_feed(rows, full=True))
    reader._audio_hovers(handle, _feed(rows, full=True))
    new = {"id": 22, "tier": "now", "ord": 3.5, "source_type": "epub", "availability": "available", "work_id": 9,
           "piece_id": 2}
    handle.hovers = _said([1, 2, 3, 22])
    reader._merge(_feed([new]))
    reader._audio_hovers(handle, _feed([new]), [new])
    assert handle.asked == 2 and reader._items[22]["book_audio"]["title"] == NEKO
