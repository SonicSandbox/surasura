"""Audiobooks in the library (Hon, 3.0 E2; H-6, H-7, H-8 PROVISIONAL): what a look makes of the audio it finds.

- **H-7** an audiobook alone is ONE item (never one per file), waiting for Anki Miner (`source_type` 'audio',
  availability 'waiting', no file made): never counted by Generate, the Rarity preview or the mine line.
- **H-6** an audiobook beside its book is one title: the book's chapters, then one 🎧 *With its audiobook* row.
- **H-8** unsure → one *Needs you* question, asked once per pair: *Yes* joins the book's title, *No* is kept and never
  asked again.

Why these matter: a learner points Surasura at a folder holding books and their audiobooks; a file-by-file item, an
audio file read as a book, a pair made wrongly in silence or a question asked twice would each be wrong where he can
see it. Every look here runs on real files built on disk (an EPUB of real Japanese text, MP3s and an M4B with real
tags and lengths) and proves the source folders are never written to.
"""
import json
import os
import shutil
import time

import pytest

from app import audiobooks
from app import library_store as ls
from app import sources
from app.connect import library as connect_library
from app.services import needs, view_rows
from tests.test_audiobooks import _m4b, _mp3
from tests.test_library_store_support import RESOURCES
from tests.test_sources_scan import _drive, _empty, _look

NEKO, GINGA, SAIYU = "吾輩は猫である", "銀河鉄道の夜", "西游记"


@pytest.fixture(autouse=True)
def _fresh_module_state():
    """Each test starts as a new run of the app: no look made yet this run."""
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    sources._EMPTIED.clear()
    yield
    sources._LOOKED.clear()
    sources._RUNNING.clear()
    sources._EMPTIED.clear()


# --- builders ------------------------------------------------------------------------------------------------------ #
def _lines(language):
    with open(os.path.join(RESOURCES, language, "context_test.txt"), encoding="utf-8") as f:
        return [ln for ln in f.read().splitlines() if ln.strip()]


def _epub(path, title, language="ja", repeat=20):
    """A real EPUB titled `title`: three chapters of the test resources' sentences (about 8,000 characters in all)."""
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("hon-" + title)
    book.set_title(title)
    book.set_language(language)
    body = "".join(f"<p>{ln}</p>" for ln in _lines(language)) * repeat
    items = []
    for n in range(1, 4):
        c = epub.EpubHtml(title=f"第{n}章", file_name=f"c{n}.xhtml", lang=language)
        c.content = f"<html><body>{body}</body></html>"
        book.add_item(c)
        items.append(c)
    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    os.makedirs(os.path.dirname(path), exist_ok=True)
    epub.write_epub(str(path), book)
    _settle(path)
    return str(path)


def _chars(language, repeat=20):
    """About the characters `_epub`'s three chapters hold (what the look's copies weigh: their bytes / 3)."""
    return 3 * repeat * sum(len(ln.encode("utf-8")) for ln in _lines(language)) // 3


def _settle(*paths):
    t = time.time() - 60
    for p in paths:
        os.utime(p, (t, t))
        folder = os.path.dirname(p)
        os.utime(folder, (t, t))


def _audio_folder(folder, album, seconds, n=3, artist=None):
    """A folder of `n` chapter MP3s (`01.mp3`…) tagged with `album`, `seconds` in all, settled."""
    frames = {"TALB": album, **({"TPE1": artist} if artist else {})}
    paths = [_mp3(os.path.join(folder, f"{i:02d}.mp3"), seconds=seconds / n, frames=dict(frames, TRCK=str(i)))
             for i in range(1, n + 1)]
    _settle(*paths)
    return paths


def _fit(language):
    """Seconds of audio a narrator reads `_epub`'s text in (6 characters a second: inside LENGTH_FIT)."""
    return max(_chars(language) / 6, audiobooks.MIN_SECONDS + 60)


def _audio_items(store):
    return [store.item(i) for (i,) in store.conn.execute("SELECT id FROM items WHERE source_type = 'audio' ORDER BY id")]


def _record(store, item_id):
    """The item's audiobook record — every live record of it alike (one per source or first file it was found by)."""
    recs = [r[2]["audiobook"] for r in store._audiobook_rows(item_id)]
    assert recs and all(r == recs[0] for r in recs)
    return recs[0]


def _book_items(store, title):
    work = store.conn.execute("SELECT id FROM works WHERE title = ?", (title,)).fetchone()
    assert work, title
    return work[0], store.conn.execute("SELECT id, tier, ord, source_type, availability FROM items WHERE work_id = ? "
                                       "ORDER BY tier, ord, id", (work[0],)).fetchall()


# --- H-6: a book with its audiobook is one title ------------------------------------------------------------------ #
@pytest.mark.parametrize("language,title", (("ja", NEKO), ("zh", SAIYU)))
def test_an_audiobook_beside_its_book_is_one_title_its_chapters_then_one_waiting_audio_row(language, title):
    """The EPUB and a folder of its chapter MP3s side by side, found in one look: the book's parts as always, then ONE
    item for the audio (never one per file) in the book's title, right after its last part, waiting — the pair sure
    (an exact title, near, a length a narrator reads in), so nothing is asked."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", f"{title}.epub"), title, language)
    files = _audio_folder(os.path.join(src, "Books", title), title, _fit(language))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        work, rows = _book_items(store, title)
        parts = [r for r in rows if r[3] != "audio"]
        heard = [r for r in rows if r[3] == "audio"]
        assert len(parts) >= 2 and len(heard) == 1
        assert heard[0][4] == "waiting" and rows[-1][0] == heard[0][0]           # after the book's last part
        assert heard[0][1] == parts[-1][1]                                       # in its tier
        rec = _record(store, heard[0][0])
        assert rec["files"] == [os.path.abspath(f) for f in files]               # its files in order
        assert rec["book"]["how"] == audiobooks.SURE and rec["ask"] is None
        assert rec["book"]["epub"] == os.path.abspath(book)
        assert needs.asks_of(store) == []                                        # nothing asked
        assert not os.path.exists(os.path.join(data_dir, ls.CONTENT_FOLDER, title, "01.mp3"))   # no file made
        assert len(_audio_items(store)) == 1


# --- H-7: an audiobook alone is one waiting item, counted nowhere ------------------------------------------------- #
@pytest.mark.parametrize("language,title", (("ja", GINGA), ("zh", SAIYU)))
def test_an_audiobook_alone_is_one_item_waiting_for_anki_miner_and_counted_nowhere(language, title):
    """An M4B on its own: one item in New arrivals, `audio`, waiting (no file made), its title the audiobook's — never
    in Generate's lists, the Rarity preview's counted texts nor the mine line; Connect's one rule says it waits as audio."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    m4b = _m4b(os.path.join(src, "Audio", f"{title}.m4b"), 3600, tags={"album": title},
               chapters=[("一", 0), ("二", 1800)])
    _settle(m4b)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root)
        items = _audio_items(store)
        assert len(items) == 1 and result["added"] == 1
        item = items[0]
        assert (item["tier"], item["availability"], item["title"]) == ("arrivals", "waiting", title)
        assert item["rel_path"].startswith(f"{ls.CONTENT_FOLDER}/{title} (audio)/") and \
            item["rel_path"].endswith(f" {title}.m4b")                           # its own title, never a book's
        assert not os.path.exists(os.path.join(data_dir, *item["rel_path"].split("/")))
        rec = _record(store, item["id"])
        assert rec["chapters"][1]["title"] == "二" and rec["book"] is None and rec["ask"] is None
        counted, kept, aside = store.text_lists()
        assert item["rel_path"] not in counted + aside                           # the Rarity preview's
        assert all(item["rel_path"] not in [e["physical_path"] for e in v]       # Generate's lists
                   for v in store.schedule(with_aside=True).values() if isinstance(v, list))
        assert item["id"] not in store._mine_ids(1000)                           # the mine line's
        assert connect_library.waits_for(item, connect_library.media_of(store, item)) == "audio"


def test_an_audiobook_moved_into_current_still_counts_nowhere():
    """Even dragged into Current, a waiting audio item is no text: Generate's lists and the mine line never hold it."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _settle(_m4b(os.path.join(src, "Audio", f"{GINGA}.m4b"), 3600, tags={"album": GINGA}))
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        item = _audio_items(store)[0]
        store.move([item["id"]], "now")
        assert store.item(item["id"])["tier"] == "now"
        assert item["id"] not in store._mine_ids(1000)
        assert all(item["rel_path"] not in [e["physical_path"] for e in v]
                   for v in store.schedule().values() if isinstance(v, list))


def test_a_second_look_adds_nothing_and_an_unchanged_folder_is_never_read_for_audio_again(monkeypatch):
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Audio", GINGA), GINGA, 3000)
    for where, _dirs, _files in os.walk(src):                                    # every folder settled (S4's cache)
        _settle(os.path.join(where, "."))
    calls = []
    real = audiobooks.find
    monkeypatch.setattr(audiobooks, "find", lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        assert len(_audio_items(store)) == 1 and calls
        calls.clear()
        again = _look(store, language, root)                                     # nothing changed: nothing listed
        assert again["added"] == 0 and calls == []
        tags = []
        real_tags = audiobooks.read_tags
        monkeypatch.setattr(audiobooks, "read_tags", lambda p: tags.append(p) or real_tags(p))
        full = _look(store, language, root, full=True)                           # everything listed: nothing new,
        assert full["added"] == 0 and calls == [] and tags == []                 # no tag read again (S19)
        assert len(_audio_items(store)) == 1


def test_a_shows_soundtrack_beside_its_videos_adds_no_audiobook():
    """A show folder holding its episodes and its OST: the MP3s are the show's, never an audiobook."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    show = os.path.join(src, "Anime", "ぼっち・ざ・ろっく!")
    os.makedirs(show)
    with open(os.path.join(show, "ep01.mkv"), "wb") as f:
        f.write(b"\x1aE\xdf\xa3" + bytes(2 << 20))                               # a video, big enough to be one
    _audio_folder(show, "ぼっち・ざ・ろっく! OST", 3000)
    _settle(os.path.join(show, "ep01.mkv"))
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        assert _audio_items(store) == []


def test_a_short_sample_adds_nothing_and_a_placeholder_is_never_opened(monkeypatch):
    """Under MIN_SECONDS is no audiobook (a song, a sample); a cloud placeholder's audio is never read (its read would
    download it): its folder waits for the next look."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Audio", "sample"), "試聴", 300)
    cloud = _audio_folder(os.path.join(src, "Audio", GINGA), GINGA, 3000)
    opened = []
    real_tags = audiobooks.read_tags
    monkeypatch.setattr(audiobooks, "read_tags", lambda p: opened.append(p) or real_tags(p))
    real_ph = ls.is_placeholder
    monkeypatch.setattr(ls, "is_placeholder", lambda st: any(st.st_size == os.stat(p).st_size and
                                                             st.st_mtime_ns == os.stat(p).st_mtime_ns
                                                             for p in cloud) or real_ph(st))
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        assert _audio_items(store) == []
        assert not set(opened) & {os.path.abspath(p) for p in cloud} and not set(opened) & set(cloud)
        monkeypatch.setattr(ls, "is_placeholder", real_ph)                       # downloaded since
        _look(store, language, root)                                             # its folder listed again
        assert [i["title"] for i in _audio_items(store)] == [GINGA]


# --- H-8: unsure → one question, asked once ----------------------------------------------------------------------- #
def _unsure(language="ja"):
    """The book in Books/, its audiobook far away in Audio/ and three times too long for it (another edition, or a
    slow reading): exact title, but unsure — one question."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _epub(os.path.join(src, "Books", f"{NEKO}.epub"), NEKO, language)
    _audio_folder(os.path.join(src, "Audio", NEKO), NEKO, _chars(language) / 1.5)
    return store, data_dir, src


def test_an_unsure_pair_asks_one_question_and_a_no_is_kept_and_never_asked_again():
    language = "ja"
    store, _data_dir, src = _unsure(language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        assert item["tier"] == "arrivals" and _record(store, item["id"])["ask"]["title"] == NEKO
        asks = needs.asks_of(store)
        assert len(asks) == 1 and asks[0]["kind"] == needs.AUDIOBOOK_ASK
        [entry] = [e for e in needs.entries(None, asks=asks) if e.kind == needs.AUDIOBOOK_ASK]
        assert entry.title == f"Is this audiobook 「{NEKO}」 the book 「{NEKO}」?"
        assert entry.actions == ("same_book", "not_book") and "3 files (01.mp3 … 03.mp3)" in entry.say
        assert store.answer_audiobook(item["id"], False)
        asked = lambda: [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_ASK]
        assert asked() == [] and list(store.audiobook_answers().values()) == [False]
        assert store.meta().get(ls.AUDIOBOOKS_STALE) == "1"
        _look(store, language, root)                                             # weighed again: no other book
        assert asked() == [] and store.meta().get(ls.AUDIOBOOKS_STALE) == "0"
        _look(store, language, root, full=True)
        assert asked() == [] and _record(store, item["id"])["book"] is None
        assert store.answer_audiobook(item["id"], True) is False                 # nothing open: nothing written
        # a5-2: the *No* leaves the one card that offers to find its book, naming the book it answered
        [find] = [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_FIND]
        assert find["item_id"] == item["id"] and find["said_no"] == NEKO


def test_a_yes_joins_the_book_title_after_its_last_part_and_is_kept():
    language = "ja"
    store, _data_dir, src = _unsure(language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        assert store.answer_audiobook(item["id"], True)
        work, rows = _book_items(store, NEKO)
        assert rows[-1][0] == item["id"] and store.item(item["id"])["work_id"] == work
        assert store.item(item["id"])["availability"] == "waiting"
        rec = _record(store, item["id"])
        assert rec["book"]["how"] == audiobooks.ANSWERED and rec["ask"] is None
        assert list(store.audiobook_answers().values()) == [True]
        _look(store, language, root, full=True)                                  # nothing moves it again
        assert _book_items(store, NEKO)[1] == rows and needs.asks_of(store) == []


def test_a_no_lets_the_next_book_be_asked():
    """Two editions of the book, both unsure: a *No* to the first asks about the second on the next look."""
    language = "ja"
    store, _data_dir, src = _unsure(language)
    _epub(os.path.join(src, "Books2", f"{NEKO}.epub"), NEKO + " ", language, repeat=21)   # another edition
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        first = _record(store, item["id"])["ask"]["epub"]
        store.answer_audiobook(item["id"], False)
        _look(store, language, root)
        second = _record(store, item["id"])["ask"]
        assert second is not None and second["epub"] != first
        store.answer_audiobook(item["id"], False)
        _look(store, language, root)
        assert _record(store, item["id"])["ask"] is None
        assert [a["kind"] for a in needs.asks_of(store)] == [needs.AUDIOBOOK_FIND]     # a5-2: none left: find it


def test_a_book_that_arrives_after_its_lone_audiobook_takes_it_in():
    """The audiobook first (alone, waiting), its book later beside it: the look that takes the book in pairs them."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Books", NEKO), NEKO, _fit(language))
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        item = _audio_items(store)[0]
        assert item["tier"] == "arrivals" and _record(store, item["id"])["book"] is None
        _epub(os.path.join(src, "Books", f"{NEKO}.epub"), NEKO, language)
        _look(store, language, root)
        work, rows = _book_items(store, NEKO)
        assert rows[-1][0] == item["id"] and _record(store, item["id"])["book"]["how"] == audiobooks.SURE


# --- Remove, moves, two sources ------------------------------------------------------------------------------------ #
def test_remove_keeps_an_audiobook_out_for_good():
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Audio", GINGA), GINGA, 3000)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        store.remove([_audio_items(store)[0]["id"]])
        again = _look(store, language, root, full=True)
        assert _audio_items(store) == [] and again["added"] == 0


def test_a_renamed_audiobook_folder_is_the_same_item_with_its_answer():
    """Renamed by the learner, its files the same: the same item (its old place marked moved, D5), still paired."""
    language = "ja"
    store, _data_dir, src = _unsure(language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        store.answer_audiobook(item["id"], True)
        os.rename(os.path.join(src, "Audio", NEKO), os.path.join(src, "Audio", NEKO + "（朗読）"))
        _look(store, language, root, full=True)
        items = _audio_items(store)
        assert [i["id"] for i in items] == [item["id"]]
        rec = _record(store, item["id"])
        assert rec["files"][0].endswith(os.path.join(NEKO + "（朗読）", "01.mp3")) and rec["book"]["how"] == "answered"
        assert store.item(item["id"])["work_id"] == _book_items(store, NEKO)[0] and needs.asks_of(store) == []


def test_the_same_audiobook_in_two_sources_is_one_item():
    language = "ja"
    store, _data_dir = _empty(language)
    a, b = _drive("driveA"), _drive("driveB")
    _audio_folder(os.path.join(a, GINGA), GINGA, 3000)
    shutil.copytree(os.path.join(a, GINGA), os.path.join(b, GINGA))
    for p in os.listdir(os.path.join(b, GINGA)):
        _settle(os.path.join(b, GINGA, p))
    with store:
        ra, rb = store.add_source(a), store.add_source(b)
        _look(store, language, ra)
        _look(store, language, rb)
        assert len(_audio_items(store)) == 1


# --- the row and the card ---------------------------------------------------------------------------------------- #
def _item(i, title, source_type, rel, waiting=False, work=7):
    return {"id": i, "tier": "now", "ord": float(i), "rel_path": rel, "title": title, "source_type": source_type,
            "availability": "waiting" if waiting else "available", "work_id": work, "piece_id": 1}


def test_a_book_row_with_its_audiobook_shows_one_headphones_row_waiting_quietly():
    parts = [_item(i, f"{NEKO}_0{i} (1-{i}) 第一章.txt", "epub", f"Library/{NEKO}/{NEKO}_0{i}.txt") for i in (1, 2)]
    audio = _item(3, NEKO, "audio", f"Library/{NEKO}/01.mp3", waiting=True)
    works = {7: {"id": 7, "title": NEKO, "media_type": "book"}}
    row = view_rows._row(0, "now", parts + [audio], works, {}, {}, set(), set(), 20)
    heard = row.episodes[-1]
    assert heard.label == "🎧 With its audiobook" and heard.number is None and heard.text == "audio"
    assert heard.status.kind == "books" and heard.status.tip == view_rows.STRINGS["tip_audio_wait"]
    assert heard.play_tip == view_rows.STRINGS["play_audio_wait"] and not heard.can_play
    # a5-2: the book's own line; 🎧 before its title says the rest in its hover (`audio`), the chip's the same
    assert row.line == "Parts 1–2" and row.audio.startswith(f"🎧 With its audiobook 「{NEKO}」")
    assert row.chips[-1].text == "🎧" and row.chips[-1].tip == row.audio and not view_rows.audio_only(row)


def test_an_audiobook_alone_row_and_tray_line_say_it_waits_for_anki_miner():
    audio = _item(5, GINGA, "audio", f"Library/{GINGA}/{GINGA}.m4b", waiting=True, work=9)
    works = {9: {"id": 9, "title": GINGA, "media_type": None}}
    row = view_rows._row(0, "arrivals", [audio], works, {}, {}, set(), set(), 20)
    assert row.media == "audiobook" and row.verb == "Listen" and row.title == GINGA
    assert row.line == "Audio only · waits for Anki Miner" and row.status.label == "Waits for Anki Miner"
    assert row.episodes[0].label == GINGA and view_rows.audio_only(row) and row.audio.startswith("🎧 Audio only")
    arrival = view_rows._arrival([audio], works, {}, {}, None)
    assert arrival.parts[0] == ("Audio only · waits for Anki Miner", "dim") and arrival.audio == row.audio
    assert ("waits for Anki Miner", "dim") not in arrival.parts and ("no subtitles yet", "dim") not in arrival.parts
    assert view_rows.media_type_guess({"audio": 1}) == ls.media_type_guess({"audio": 1}) == "audiobook"
    assert view_rows.media_type_guess({"epub": 3, "audio": 1}) == "book"


def test_a_waiting_video_still_says_no_subtitles_yet():
    """The audiobook's quiet status never takes a waiting video's (SRC W1b)."""
    video = _item(6, "ep01.mkv", "subtitle", "Library/ぼっち/ep01.mkv", waiting=True, work=11)
    row = view_rows._row(0, "arrivals", [video], {11: {"id": 11, "title": "ぼっち", "media_type": "anime"}}, {}, {},
                         set(), set(), 20)
    assert row.status.kind == "no_subs"


def test_the_writer_answers_through_the_store_with_nothing_to_undo():
    from app.services import moves
    said = []

    class Store:
        def answer_audiobook(self, item_id, yes, key=None):
            said.append((item_id, yes, key))
            return True
    writer = moves.Writer.__new__(moves.Writer)
    cmd = {"op": "audiobook_answer", "ids": [42], "yes": False, "key": "k1", "label": "x"}
    replay = moves._from_entry(json.loads(json.dumps(moves._entry(cmd))))      # as a crash's journal gives it back
    assert writer._w32(Store(), replay) is None
    assert said == [(42, False, "k1")] and "audiobook_answer" in moves.JOURNALLED


def test_records_round_trip_without_opening_a_file(tmp_path):
    files = _audio_folder(str(tmp_path / NEKO), NEKO, 3000)
    [ab] = audiobooks.find(str(tmp_path / NEKO))
    rec = json.loads(json.dumps(audiobooks.record(ab)))
    back = audiobooks.from_record(rec)
    assert back == ab._replace(sizes=tuple(ab.sizes)) and back.files == [os.path.abspath(f) for f in files]
    assert audiobooks.length_text(3000) == "50 min" and audiobooks.length_text(33120) == "9 h 12 min"
    assert audiobooks.length_text(None) == ""


# --- the review's findings (register R2-*): each a scenario -------------------------------------------------------- #
def test_an_unsure_audiobook_is_a_title_of_its_own_until_yes_and_after_no():
    """R2-A1: asked about, or answered No, it never sits in the book's title (the same name is no pair)."""
    language = "ja"
    store, _data_dir, src = _unsure(language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        book_work = _book_items(store, NEKO)[0]
        assert store.item(item["id"])["work_id"] != book_work
        store.answer_audiobook(item["id"], False)
        _look(store, language, root, full=True)
        assert store.item(item["id"])["work_id"] != book_work


def test_two_narrations_of_one_title_are_two_items():
    """R2-A2: two audiobooks of one title, their first files named alike, are never one item."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Audio", "朗読A"), GINGA, 3000, artist="山田")           # their bytes differ,
    _audio_folder(os.path.join(src, "Audio", "朗読B"), GINGA, 3600, artist="佐藤花子")       # as two readings' do
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        items = _audio_items(store)
        assert len(items) == 2 and [len(store._audiobook_rows(i["id"])) for i in items] == [1, 1]


def test_the_same_unsure_audiobook_in_two_sources_asks_once_and_one_answer_ends_it():
    """R2-A3: its two records (one per source) are one item, one question; No ends it for both, for good."""
    language = "ja"
    store, _data_dir, src = _unsure(language)
    other = _drive("driveB")
    shutil.copytree(os.path.join(src, "Audio", NEKO), os.path.join(other, NEKO))
    for p in os.listdir(os.path.join(other, NEKO)):
        _settle(os.path.join(other, NEKO, p))
    with store:
        ra, rb = store.add_source(src), store.add_source(other)
        _look(store, language, ra, first=True)
        _look(store, language, rb)
        items = _audio_items(store)
        assert len(items) == 1 and len(store._audiobook_rows(items[0]["id"])) == 2
        assert len(needs.asks_of(store)) == 1
        assert store.answer_audiobook(items[0]["id"], False)
        for root in (ra, rb, ra):
            _look(store, language, root, full=True)
        assert [a["kind"] for a in needs.asks_of(store)] == [needs.AUDIOBOOK_FIND]     # a5-2: one card, its find


def test_an_answer_to_a_question_no_longer_asked_writes_nothing():
    """R2-A5: the card showed one question; another is asked since — its press never answers that one."""
    language = "ja"
    store, _data_dir, src = _unsure(language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        shown = _record(store, item["id"])["ask"]["key"]
        assert store.answer_audiobook(item["id"], True, key="another question") is False
        assert _record(store, item["id"])["ask"]["key"] == shown and store.audiobook_answers() == {}
        assert store.answer_audiobook(item["id"], True, key=shown)


def test_a_removed_audiobook_stays_out_after_its_folder_is_renamed():
    """R2-A6: Remove keeps it out by its files' sizes too (S6), wherever it goes."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Audio", GINGA), GINGA, 3000)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        store.remove([_audio_items(store)[0]["id"]])
        os.rename(os.path.join(src, "Audio", GINGA), os.path.join(src, "Audio", GINGA + " 朗読"))
        again = _look(store, language, root, full=True)
        assert _audio_items(store) == [] and again["added"] == 0


def test_a_paired_audiobook_never_moves_the_soon_line():
    """R2-B1: the waiting row beside its book is no row the Soon line counts — the book's parts filling NOW, its
    audiobook found later joins them in NOW and pushes nothing (and nothing of its own) below the line."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _epub(os.path.join(src, "Books", f"{NEKO}.epub"), NEKO, language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _work, rows = _book_items(store, NEKO)
        store.set_soon_line(len(rows))                                            # the book's parts: all of NOW
        before = {r[0]: r[1] for r in _book_items(store, NEKO)[1]}
        assert set(before.values()) == {"now"}
        _audio_folder(os.path.join(src, "Books", NEKO), NEKO, _fit(language))
        _look(store, language, root)
        item = _audio_items(store)[0]
        after = {r[0]: r[1] for r in _book_items(store, NEKO)[1]}
        assert {i: after[i] for i in before} == before and after[item["id"]] == "now"


def test_a_yes_never_puts_the_audiobook_in_finished():
    """R2-B2: the book's first part finished, the rest read on: the audio goes after the last part still read."""
    language = "ja"
    store, _data_dir, src = _unsure(language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _work, rows = _book_items(store, NEKO)
        store.finish([max(rows, key=lambda r: (r[1] != "graduated", r[2]))[0]])  # its last part finished
        item = _audio_items(store)[0]
        store.answer_audiobook(item["id"], True)
        _work, rows = _book_items(store, NEKO)
        live = [r for r in rows if r[1] != "graduated"]
        assert live[-1][0] == item["id"] and store.item(item["id"])["tier"] != "graduated"


def test_files_added_to_an_audiobook_are_recorded_on_the_same_item():
    """R2-B3, B4: a chapter added at its end, then a prologue that sorts first: still one item, its record the files
    as they are now, in order."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    folder = os.path.join(src, "Audio", GINGA)
    _audio_folder(folder, GINGA, 3000)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        item = _audio_items(store)[0]
        _settle(_mp3(os.path.join(folder, "04.mp3"), seconds=600, frames={"TALB": GINGA, "TRCK": "4"}))
        _look(store, language, root)
        assert [os.path.basename(f) for f in _record(store, item["id"])["files"]] == \
            ["01.mp3", "02.mp3", "03.mp3", "04.mp3"]
        _settle(_mp3(os.path.join(folder, "00.mp3"), seconds=300, frames={"TALB": GINGA, "TRCK": "0"}))
        _look(store, language, root)
        assert [i["id"] for i in _audio_items(store)] == [item["id"]]
        assert os.path.basename(_record(store, item["id"])["files"][0]) == "00.mp3"


def test_a_waiting_video_of_a_podcast_title_still_says_no_subtitles_yet():
    """R2-B5: only an audiobook's own item waits for Anki Miner; a video waiting for its subtitle says so."""
    video = _item(6, "ep01.mkv", "subtitle", "Library/ラジオ/ep01.mkv", waiting=True, work=12)
    row = view_rows._row(0, "arrivals", [video], {12: {"id": 12, "title": "ラジオ", "media_type": "podcast"}}, {}, {},
                         set(), set(), 20)
    assert row.status.kind == "no_subs"


def test_a_yes_after_the_book_is_gone_is_kept_and_leaves_the_audiobook_alone():
    """R2 (mutant B5): the book removed while its question waits — *Yes* is kept (never asked again about it), and
    the audiobook stays a title of its own, never half-paired."""
    language = "ja"
    store, _data_dir, src = _unsure(language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = _audio_items(store)[0]
        key = _record(store, item["id"])["ask"]["key"]
        store.remove([r[0] for r in _book_items(store, NEKO)[1] if r[0] != item["id"]])
        assert store.answer_audiobook(item["id"], True, key=key)
        assert store.audiobook_answers() == {key: True}
        assert store.meta().get(ls.AUDIOBOOKS_STALE) == "1"                      # weighed again: another book may be
        rec = _record(store, item["id"])
        assert rec["book"] is None and rec["ask"] is None and needs.asks_of(store) == []
