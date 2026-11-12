"""An audiobook brought in alone is asked about at once (Kantan-B3; Mattias in #testers, 2026-11-12: an audiobook with
no book in the library sat as *Audio only* and nothing asked which book it reads — he went looking for a subtitle file).
Words PROVISIONAL; the rule this file holds:

  * an audiobook alone (no book, no question open) that nobody answered about yet gets *Needs you*'s one card at once:
    *「…」 is an audiobook. Which book is it?* — *Find its book…* · *It has no book* (a5-2's card, its own words);
  * never for one the learner placed: *It has no book*, *Separate them* (you said where it belongs), paired, asked;
  * never for one whose transcript beside it is its text (alone with a transcript, it is read as a subtitle is);
  * after a *No*, a5-2's words are kept (*Not 「…」, you said*).

Real files built on disk (tests/test_audiobook_items' builders: an EPUB of real Japanese, MP3s and an M4B with real
tags and lengths), looked at by the real look.
"""
import os

from app.services import needs
from tests.test_audiobook_items import GINGA, NEKO, _audio_folder, _audio_items, _epub, _record, _settle
from tests.test_audiobook_transcripts import _alone as _alone_with_transcript
from tests.test_audiobook_transcripts import STAR
from tests.test_audiobooks import _m4b
from tests.test_sources_scan import _drive, _empty, _look


def _finds(store):
    return [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_FIND]


def _entry(store):
    [entry] = [e for e in needs.entries(None, asks=needs.asks_of(store)) if e.kind == needs.AUDIOBOOK_FIND]
    return entry


def _lone(language="ja"):
    """GINGA's audiobook (three MP3s, 50 minutes) read where it is, no book anywhere -> (store, root, src, item)."""
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Audiobooks", GINGA), GINGA, 3000)
    store.__enter__()
    root = store.add_source(src)
    _look(store, language, root, first=True)
    [item] = _audio_items(store)
    return store, root, src, item


def test_an_audiobook_alone_is_asked_which_book_it_is_at_once():
    store, _root, _src, item = _lone()
    try:
        [find] = _finds(store)
        assert find["item_id"] == item["id"] and find["said_no"] is None
        entry = _entry(store)
        assert entry.title == f"「{GINGA}」 is an audiobook. Which book is it?"
        assert entry.actions == ("find_book", "no_book") and entry.data["item_id"] == item["id"]
        assert entry.say.startswith("3 files (01.mp3 … 03.mp3)") and "you said" not in entry.say
        for text in (entry.title, entry.say):                     # never a hint that a subtitle file is needed
            assert "subtitle" not in text.lower() and "srt" not in text.lower()
    finally:
        store.__exit__(None, None, None)


def test_an_m4b_alone_is_asked_about_too():
    store, _data_dir = _empty("ja")
    src = _drive("driveA")
    _settle(_m4b(os.path.join(src, "Downloads", f"{GINGA}.m4b"), 3600, tags={"album": GINGA}))
    with store:
        _look(store, "ja", store.add_source(src), first=True)
        assert [f["title"] for f in _finds(store)] == [GINGA]


def test_it_has_no_book_ends_the_card_for_good():
    store, root, _src, item = _lone()
    try:
        assert store.audiobook_no_book(item["id"])
        assert _finds(store) == []
        _look(store, "ja", root, full=True)
        assert _finds(store) == []
    finally:
        store.__exit__(None, None, None)


def test_its_book_found_ends_the_card_and_a_book_arriving_later_pairs_it_as_before():
    store, root, src, item = _lone()
    try:
        _epub(os.path.join(src, "Books", f"{GINGA}.epub"), GINGA, "ja", repeat=6)
        _look(store, "ja", root, full=True)
        rec = _record(store, item["id"])
        assert rec["book"] is not None or rec["ask"] is not None          # paired, or one question about it
        assert _finds(store) == []                                         # never two cards for one audiobook
    finally:
        store.__exit__(None, None, None)


def test_separate_them_never_brings_the_card_you_said_where_it_belongs():
    """*Separate them* (Michi-AB): "never *Find its book…*: you said where it belongs" — kept."""
    store, root, src, item = _lone()
    try:
        _epub(os.path.join(src, "Books", f"{GINGA}.epub"), GINGA, "ja", repeat=6)
        _look(store, "ja", root, full=True)
        if _record(store, item["id"])["ask"] is not None:
            assert store.answer_audiobook(item["id"], True)
        assert _record(store, item["id"])["book"] is not None
        change = store.audiobook_separate(item["id"])
        assert change is not None
        assert _record(store, item["id"])["book"] is None and _finds(store) == []
        _look(store, "ja", root, full=True)
        assert _finds(store) == []
        store.undo(change)                                         # its Undo: paired again, its mark gone with it
        rec = _record(store, item["id"])
        assert rec["book"] is not None and "placed" not in rec
    finally:
        store.__exit__(None, None, None)


def test_a_book_picked_from_the_card_pairs_and_its_undo_brings_the_card_back():
    """*Find its book…*'s pick (a book in the library) pairs as a *Yes* does; its Undo leaves the audiobook alone and
    unanswered again — the card comes back (never a mark left behind that hides it)."""
    store, root, src, item = _lone()
    try:
        _epub(os.path.join(src, "Books", "坊っちゃん.epub"), "坊っちゃん", "ja", repeat=21)   # no title like it
        _look(store, "ja", root, full=True)
        assert [f["item_id"] for f in _finds(store)] == [item["id"]]
        epub = next(b["epub"] for b in store.library_books() if b["title"] == "坊っちゃん")
        change = store.pick_audiobook_book(item["id"], epub)
        assert change is not None and _record(store, item["id"])["book"] is not None and _finds(store) == []
        store.undo(change)
        rec = _record(store, item["id"])
        assert rec["book"] is None and "placed" not in rec
        assert [f["item_id"] for f in _finds(store)] == [item["id"]]
    finally:
        store.__exit__(None, None, None)


def test_a_yes_whose_book_was_removed_meanwhile_is_never_asked_about_again():
    """The learner answered *Yes*; the book was gone by then (R2): the audiobook stays alone, and that answer stands —
    no card asks him which book it is."""
    from tests.test_audiobook_items import _book_items, _unsure
    store, _data_dir, src = _unsure("ja")
    with store:
        root = store.add_source(src)
        _look(store, "ja", root, first=True)
        item = _audio_items(store)[0]
        key = _record(store, item["id"])["ask"]["key"]
        store.remove([r[0] for r in _book_items(store, NEKO)[1] if r[0] != item["id"]])
        assert store.answer_audiobook(item["id"], True, key=key)
        assert _record(store, item["id"])["placed"] is True and _finds(store) == []
        _look(store, "ja", root, full=True)
        assert _finds(store) == []


def test_a_separated_audiobook_renamed_keeps_its_word_and_stays_unasked():
    """D5: *Separate them*, then its folder renamed by the learner — the same item, its `placed` mark kept with the
    other marks (`sources.AUDIO_MARKS`): still no card."""
    store, root, src, item = _lone()
    try:
        _epub(os.path.join(src, "Books", f"{GINGA}.epub"), GINGA, "ja", repeat=6)
        _look(store, "ja", root, full=True)
        if _record(store, item["id"])["ask"] is not None:
            assert store.answer_audiobook(item["id"], True)
        assert store.audiobook_separate(item["id"]) is not None
        os.rename(os.path.join(src, "Audiobooks", GINGA), os.path.join(src, "Audiobooks", GINGA + "（朗読）"))
        _look(store, "ja", root, full=True)
        assert [i["id"] for i in _audio_items(store)] == [item["id"]]
        rec = _record(store, item["id"])
        assert rec["files"][0].endswith(os.path.join(GINGA + "（朗読）", "01.mp3")) and rec["placed"] is True
        assert _finds(store) == []
    finally:
        store.__exit__(None, None, None)


def test_the_newest_word_wins_no_then_a_pick_then_separate_leaves_no_card():
    """A *No* (said_no), then *Find its book…* picks another, then *Separate them*: placed — the older *No* never brings
    the card back (round 2, S5)."""
    from tests.test_audiobook_find import BOCCHAN, _said_no
    store, _root, _src, item = _said_no()
    try:
        epub = next(b["epub"] for b in store.library_books() if b["title"] == BOCCHAN)
        assert store.pick_audiobook_book(item["id"], epub) is not None
        assert store.audiobook_separate(item["id"]) is not None
        rec = _record(store, item["id"])
        assert rec["placed"] is True and "said_no" not in rec and _finds(store) == []
    finally:
        store.__exit__(None, None, None)


def test_the_cards_three_wordings_follow_what_was_said():
    """Never answered (`said_no` None): *is an audiobook*; a *No* to a named book: *Not 「…」*; a *No* without a title
    (`said_no` ""): *Not that book*."""
    base = {"kind": needs.AUDIOBOOK_FIND, "item_id": 7, "title": GINGA, "files": ["D:/A/01.mp3"], "seconds": 3000}
    alone, named, plain = (needs.entries(None, asks=[dict(base, said_no=s)])[0] for s in (None, NEKO, ""))
    assert alone.title == f"「{GINGA}」 is an audiobook. Which book is it?" and "you said" not in alone.say
    assert named.title == plain.title == f"Which book does the audiobook 「{GINGA}」 read?"
    assert f"Not 「{NEKO}」, you said." in named.say and "Not that book, you said." in plain.say
    assert alone.key == named.key == plain.key                   # one card an audiobook, whichever words


def test_an_audiobook_alone_with_its_transcript_is_read_as_it_and_never_asked_about():
    store, _data_dir, src, _m4b_path, _srt = _alone_with_transcript("ja", STAR)
    with store:
        _look(store, "ja", store.add_source(src))
        [item] = _audio_items(store)
        assert item["availability"] == "available" and _finds(store) == []


def test_after_a_no_the_card_keeps_its_own_words():
    from tests.test_audiobook_find import _said_no
    store, _root, _src, item = _said_no()
    try:
        [find] = _finds(store)
        assert find["said_no"] == NEKO
        assert _entry(store).title == f"Which book does the audiobook 「{NEKO}」 read?"
        assert "placed" not in _record(store, item["id"])           # a No's mark takes `placed` off, never left as None
    finally:
        store.__exit__(None, None, None)
