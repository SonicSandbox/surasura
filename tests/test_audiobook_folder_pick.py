"""A book's audiobook picked by its folder joins the book (Kura-AB4; Mattias's 3.0.6 report, words PROVISIONAL).

Mattias imported a book's EPUB; Connect asked for its audiobook (*Pick its audiobook…*), he gave it its folder — and the
audiobook sat in New arrivals as a title of its own, because the folder's look paired an audiobook with a book only
when their names said so (a rip's folder is "audiobook", "01.mp3"…, or its names are romaji). The learner's word —
*this folder is that book's audiobook* — never reached the look. Now it does (`sources.scan`'s `book`):

- the audiobook found in the folder picked for a book joins that book's title at its take-in, after its last part,
  whatever its names say — never a New arrivals item, nothing written in the learner's folders;
- of several there, only the one most like the book (none alike, or a tie: none — each listed for the pick);
- the same for a book brought in by Extract (+ Add's EPUB door) as for one read where it is;
- what became of the folder's audiobooks is the looks' answer (`source_looks._audiobooks_read`): joined, already in
  and still without a book (the window then picks it, with Undo), or H-8's question open (+ Add's lead into the
  pairing).

Every look runs on real files built on disk (an EPUB of real Japanese / Chinese text, MP3s with real lengths) and
proves the source folders are never written to (`_look`).
"""
import os

import pytest

from app import extract
from app import library_store as ls
from app.services import needs, source_looks
from tests.test_audiobook_items import (NEKO, GINGA, SAIYU, _audio_folder, _audio_items, _book_items, _epub,  # noqa
                                        _chars, _fit, _fresh_module_state, _record)
from tests.test_audiobooks import _mp3
from tests.test_library_store_support import roots
from tests.test_sources_scan import _drive, _empty, _look


def _untagged(folder, seconds, n=3):
    """A rip as it often comes: `01.mp3`… with no tags at all, `seconds` in all (settled)."""
    from tests.test_audiobook_items import _settle
    paths = [_mp3(os.path.join(folder, f"{i:02d}.mp3"), seconds=seconds / n, frames={}) for i in range(1, n + 1)]
    _settle(*paths)
    return paths


def _book_in(language, title, door):
    """(store, epub) — the book in the library by `door`: read where it is (a source's look) or Extract's (+ Add's
    EPUB door: parts copied into the library, their origins `<epub>#<n>`)."""
    store, _data = _empty(language)
    books = _drive("books")
    epub = _epub(os.path.join(books, f"{title}.epub"), title, language)
    if door == "source":
        _look(store, language, store.add_source(books), first=True)     # setup's first look: Current, as his
        return store, epub
    store.close()
    result = extract.extract(epub, title, language, section="now", spawn=False)
    assert result.in_library, result
    return ls.open_store(language, *roots(language)), epub


def _picked(store, language, folder, epub, title):
    """The book's *A folder on your computer…*: the folder a source, its first look told it is that book's."""
    return _look(store, language, store.add_source(folder), full=True,
                 book={"folder": folder, "epub": epub, "title": title})


def _joined(store, title):
    """The book's title's rows (its parts, then its audiobook) -> (parts, audio rows)."""
    _work, rows = _book_items(store, title)
    return [r for r in rows if r[3] != "audio"], [r for r in rows if r[3] == "audio"]


# --- door 1: the book's own *A folder on your computer…* --------------------------------------------------------- #
@pytest.mark.parametrize("door", ("source", "extract"))
@pytest.mark.parametrize("language,title,folder", (
    ("ja", NEKO, "audiobook"),                                   # a plain folder, untagged files
    ("ja", NEKO, "Wagahai wa Neko de Aru (Audiobook)"),          # romaji
    ("zh", SAIYU, "有声书"),                                      # "audiobook", in Chinese
))
def test_the_folder_picked_for_a_book_joins_it_whatever_its_names(language, title, folder, door):
    """Mattias's case: no name says which book it reads — yet the learner said so by picking its folder for the book.
    It joins the book's title right after its last part, in its tier, paired as a pick pairs (`answered`) — never
    New arrivals, no question asked, no file made."""
    store, epub = _book_in(language, title, door)
    audio = _drive("audio")
    files = _untagged(os.path.join(audio, folder), _fit(language))
    with store:
        _picked(store, language, os.path.join(audio, folder), epub, title)
        parts, heard = _joined(store, title)
        assert len(heard) == 1, _audio_items(store)
        assert heard[0][1] == parts[-1][1] != "arrivals"                          # the book's tier, never New arrivals
        _work, rows = _book_items(store, title)
        assert rows[-1][0] == heard[0][0]                                         # after its last part
        rec = _record(store, heard[0][0])
        assert rec["book"]["how"] == "answered" and rec["ask"] is None
        assert rec["book"]["epub"] == os.path.abspath(epub)
        assert rec["files"] == [os.path.abspath(f) for f in files]
        assert needs.asks_of(store) == []
        assert [i["tier"] for i in _audio_items(store)] == [parts[-1][1]]         # one item, nowhere else


def test_the_same_folder_without_the_books_word_still_waits_alone_in_new_arrivals():
    """The control (why the word matters): + Add's own *A folder…* of the same untagged rip — no name like the book's —
    stays an audiobook alone, in New arrivals, as before (Kantan-B3's card then asks which book it is)."""
    language = "ja"
    store, _epub_path = _book_in(language, NEKO, "source")
    audio = _drive("audio")
    _untagged(os.path.join(audio, "audiobook"), _fit(language))
    with store:
        _look(store, language, store.add_source(os.path.join(audio, "audiobook")), full=True)
        items = _audio_items(store)
        assert [(i["tier"], _record(store, i["id"])["book"]) for i in items] == [("arrivals", None)]


def test_a_folder_of_several_audiobooks_pairs_only_the_one_like_the_book():
    """A picked folder holding two audiobooks (the learner's whole audio folder): the one whose title is the book's
    joins it — though its length alone would leave the rule unsure (three times too long: a slow reading) — and the
    other stays alone, never paired with the wrong book."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    audio = _drive("audio")
    _audio_folder(os.path.join(audio, "Audio", NEKO), NEKO, _chars(language) / 1.5)
    _audio_folder(os.path.join(audio, "Audio", GINGA), GINGA, 3000)
    with store:
        _picked(store, language, os.path.join(audio, "Audio"), epub, NEKO)
        _parts, heard = _joined(store, NEKO)
        assert len(heard) == 1 and _record(store, heard[0][0])["title"] == NEKO
        other = [i for i in _audio_items(store) if i["id"] != heard[0][0]]
        assert len(other) == 1 and other[0]["tier"] == "arrivals"
        assert _record(store, other[0]["id"])["book"] is None


def test_a_folder_of_several_audiobooks_none_like_the_book_pairs_none():
    """Two untagged rips in the folder picked, neither named like the book: Surasura can't tell which — none is paired
    (each then listed under *Pick its audiobook…*, the window says so)."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    audio = _drive("audio")
    _untagged(os.path.join(audio, "Audio", "disc A"), _fit(language))
    _untagged(os.path.join(audio, "Audio", "disc B"), _fit(language), n=4)
    with store:
        _picked(store, language, os.path.join(audio, "Audio"), epub, NEKO)
        items = _audio_items(store)
        assert len(items) == 2 and all(_record(store, i["id"])["book"] is None for i in items)


def test_two_editions_alike_the_book_pair_neither():
    """Two audiobooks in the folder picked, both titled as the book (two editions, two readers): a tie — Surasura
    never picks one at random; both are listed for the pick."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    audio = os.path.join(_drive("audio"), "Audio")
    _audio_folder(os.path.join(audio, "reader A"), NEKO, _chars(language) / 1.5)
    _audio_folder(os.path.join(audio, "reader B"), NEKO, _chars(language) / 1.4, n=4)
    with store:
        _picked(store, language, audio, epub, NEKO)
        items = _audio_items(store)
        assert len(items) == 2 and all(_record(store, i["id"])["book"] is None for i in items)


def test_a_new_audiobook_beside_one_already_in_pairs_neither():
    """The folder picked holds an audiobook already in the library (alone) and a new one, neither named like the book:
    Surasura can't tell which is the book's — the new one is never paired just for being new (each is listed)."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    audio = os.path.join(_drive("audio"), "Audio")
    _untagged(os.path.join(audio, "old rip"), _fit(language))
    with store:
        _look(store, language, store.add_source(audio), full=True)          # read before: alone
        _untagged(os.path.join(audio, "new rip"), _fit(language), n=4)
        _picked(store, language, audio, epub, NEKO)
        items = _audio_items(store)
        assert len(items) == 2 and all(_record(store, i["id"])["book"] is None for i in items)


def test_of_several_another_volume_never_joins_the_book():
    """The book is volume 2 (下巻); the folder holds volume 1 and volume 2 of its audiobook: only volume 2 joins — a
    title alike of another volume is never this book's."""
    language = "ja"
    title = f"{NEKO} 下巻"
    store, epub = _book_in(language, title, "source")
    audio = os.path.join(_drive("audio"), "Audio")
    _audio_folder(os.path.join(audio, "up"), f"{NEKO} 上巻", _chars(language) / 1.4, n=4)   # (its own sizes: its own item)
    _audio_folder(os.path.join(audio, "down"), title, _chars(language) / 1.5)
    with store:
        _picked(store, language, audio, epub, title)
        joined = [i for i in _audio_items(store) if _record(store, i["id"])["book"]]
        assert [_record(store, i["id"])["title"] for i in joined] == [title]


def test_a_disc_folder_picked_brings_its_whole_audiobook_to_the_book():
    """The learner picks `CD1` of a two-disc rip: the audiobook is the title's folder's (the look joins its discs) and
    it joins the book whole."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    audio = _drive("audio")
    top = os.path.join(audio, "rip")
    first = _untagged(os.path.join(top, "CD1"), _fit(language) / 2)
    second = _untagged(os.path.join(top, "CD2"), _fit(language) / 2)
    with store:
        _look(store, language, store.add_source(top), full=True,
              book={"folder": os.path.join(top, "CD1"), "epub": epub, "title": NEKO})
        _parts, heard = _joined(store, NEKO)
        assert len(heard) == 1
        assert _record(store, heard[0][0])["files"] == [os.path.abspath(f) for f in first + second]


def test_a_book_gone_before_the_look_leaves_the_audiobook_alone_and_nothing_breaks():
    """The book removed while its folder was being picked: no book to join — the audiobook is taken in alone (as any),
    never half-paired."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    audio = _drive("audio")
    _untagged(os.path.join(audio, "audiobook"), _fit(language))
    with store:
        parts, _heard = _joined(store, NEKO)
        store.remove([p[0] for p in parts])
        _picked(store, language, os.path.join(audio, "audiobook"), epub, NEKO)
        items = _audio_items(store)
        assert len(items) == 1 and _record(store, items[0]["id"])["book"] is None


# --- what the looks answer the window ---------------------------------------------------------------------------- #
def _Opener(language):
    """A window's store opener on the test's library, checked as the window checks it."""
    opener = ls.StoreOpener(language, *roots(language))
    assert opener.check() == "store"
    return opener


def _add(language, folder, book=None):
    """`SourceLooks.add` as the window asks it, its answer."""
    looks = source_looks.SourceLooks(_Opener(language), language, kind=lambda _p: "local")
    answers = []
    try:
        assert looks.add(folder, answers.append, **({"book": book} if book else {}))
        assert looks.idle(30)
    finally:
        looks.close()
    assert answers and not answers[0]["refused"], answers
    return answers[0]


def test_the_looks_answer_names_the_audiobook_that_joined_the_book():
    language = "ja"
    store, epub = _book_in(language, NEKO, "extract")
    store.close()
    audio = os.path.join(_drive("audio"), "audiobook")
    _untagged(audio, _fit(language))
    said = _add(language, audio, {"epub": epub, "title": NEKO})["audiobooks"]
    store = ls.open_store(language, *roots(language))
    with store:
        (item,) = _audio_items(store)
        key = _record(store, item["id"])["book"]["key"]
        assert key and said == {"joined": [{"item_id": item["id"], "key": key}], "alone": [], "asks": []}
        assert item["tier"] != "arrivals"


def test_an_audiobook_read_before_alone_is_named_so_the_window_picks_it():
    """The folder read once already (+ Add, or a watched folder's look first): its audiobook sits alone; picked now for
    the book, the answer names it as alone — the window's pick (with Undo) then joins it."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    store.close()
    audio = os.path.join(_drive("audio"), "audiobook")
    _untagged(audio, _fit(language))
    first = _add(language, audio)["audiobooks"]
    assert first["joined"] == [] and len(first["alone"]) == 1
    again = _add(language, audio, {"epub": epub, "title": NEKO})["audiobooks"]
    assert again == {"joined": [], "alone": first["alone"], "asks": []}


def test_an_audiobook_there_paired_with_another_book_is_never_said_to_have_joined_this_one():
    """The folder picked for 「吾輩は猫である」 holds 「銀河鉄道の夜」's audiobook, already paired with that book: the
    answer names nothing joined to this book and nothing free to pick — the window then says none is there."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    store.close()
    other = _epub(os.path.join(_drive("more books"), f"{GINGA}.epub"), GINGA, language)
    audio = os.path.join(_drive("audio"), GINGA)
    _audio_folder(audio, GINGA, _fit(language))
    _add(language, os.path.dirname(other))
    _add(language, audio)
    store = ls.open_store(language, *roots(language))
    with store:
        (item,) = _audio_items(store)
        assert _record(store, item["id"])["book"]["epub"] == os.path.abspath(other)
    said = _add(language, audio, {"epub": epub, "title": NEKO})["audiobooks"]
    assert said == {"joined": [], "alone": [], "asks": []}


def test_add_a_folder_with_a_title_like_a_books_answers_its_open_question():
    """+ Add's *A folder…* of an audiobook whose title is the book's but whose length is three times too long for it
    (another edition, or a slow reading: unsure, H-8's question open): the answer carries the question — its item,
    key and the book's title — the window's *「…」's audiobook? · Pair it*; it waits in New arrivals until then."""
    language = "ja"
    store, _epub_path = _book_in(language, NEKO, "source")
    store.close()
    audio = os.path.join(_drive("audio"), NEKO)
    _audio_folder(audio, NEKO, _chars(language) / 1.5)
    said = _add(language, audio)["audiobooks"]
    store = ls.open_store(language, *roots(language))
    with store:
        asks = [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_ASK]
        assert len(asks) == 1 and store.item(asks[0]["item_id"])["tier"] == "arrivals"
    assert said == {"joined": [], "alone": [], "asks": [{"item_id": asks[0]["item_id"], "key": asks[0]["key"],
                                                         "book": NEKO, "epub": asks[0]["book"]["epub"]}]}


def test_the_books_word_waits_for_audio_still_on_its_way_and_the_next_look_joins_it():
    """The folder picked while its audio is still arriving (a download, a cloud folder not synced yet): nothing there
    to pair — the answer says none, and the book's word is kept: the folder's next look (the cadence's, or its
    watch's) joins the audiobook to the book, never New arrivals."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    store.close()
    folder = _drive("arriving")
    clock = [1000.0]
    looks = source_looks.SourceLooks(_Opener(language), language, kind=lambda _p: "local", clock=lambda: clock[0])
    answers = []
    try:
        assert looks.add(folder, answers.append, book={"epub": epub, "title": NEKO})
        assert looks.idle(30)
        assert answers[0]["audiobooks"] == {"joined": [], "alone": [], "asks": []}
        _untagged(os.path.join(folder, "audiobook"), _fit(language))
        clock[0] += 3600 / 2                                  # within the hour the word waits
        assert looks.asked(refreshed=True) and looks.idle(30)
    finally:
        looks.close()
    store = ls.open_store(language, *roots(language))
    with store:
        (item,) = _audio_items(store)
        assert _record(store, item["id"])["book"]["epub"] == os.path.abspath(epub) and item["tier"] != "arrivals"


def test_the_books_word_is_spent_once_its_folder_held_an_audiobook():
    """Once the folder picked has given its audiobook, a later one dropped there is weighed by its names as any — the
    book's word never pairs a second audiobook with it."""
    language = "ja"
    store, epub = _book_in(language, NEKO, "source")
    store.close()
    folder = _drive("audio")
    _untagged(os.path.join(folder, "first"), _fit(language))
    looks = source_looks.SourceLooks(_Opener(language), language, kind=lambda _p: "local")
    try:
        assert looks.add(folder, lambda _a: None, book={"epub": epub, "title": NEKO})
        assert looks.idle(30)
        _untagged(os.path.join(folder, "second"), _fit(language), n=4)
        assert looks.asked(refreshed=True) and looks.idle(30)
    finally:
        looks.close()
    store = ls.open_store(language, *roots(language))
    with store:
        paired = [i for i in _audio_items(store) if _record(store, i["id"])["book"]]
        assert len(_audio_items(store)) == 2 and len(paired) == 1


def test_the_answer_with_no_audio_in_the_folder_is_empty():
    language = "ja"
    _store, epub = _book_in(language, NEKO, "source")
    _store.close()
    empty = _drive("nothing")
    said = _add(language, empty, {"epub": epub, "title": NEKO})["audiobooks"]
    assert said == {"joined": [], "alone": [], "asks": []}
