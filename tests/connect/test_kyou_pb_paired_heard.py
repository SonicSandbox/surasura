"""A paired audiobook's chapters count as heard (Kyou-PB, 2026-11-23; found by the own-library study).

The sentence dial asks how each library item's line is heard (`sentences._library` → `heard`): its own clip, the AI
voice's, or none — and with the AI voice off, a book's line heard by nothing is no choice where media is cut (Connect's
Best, Swap). It asked "is this item's path a paired EPUB's path?", but a book the library holds as chapters has no
item at its EPUB's path: every chapter of every paired book was taken as silent (a real library: 1,385 chapters of 12
paired books, 0 heard). Now it asks by item — the parts of each paired book by the store's own rule
(`library.paired_parts` → `Store._audiobook_parts`) — and only where the line-up can in fact give the line its clip
(`lineup.reach`): a book lined up says each line it heard (`lineup.said`); a line it never says (a chapter outside the
audiobook's reach) is as a book with no audiobook. What each test holds:

  * a real EPUB held as chapters (nested folders), its audiobook paired by a real look → its chapters heard, ja + zh;
    the AI voice on or off changes nothing for them; a book with no audiobook → silent, the AI voice's when on;
  * a pairing still unanswered → as no pairing; answered yes → heard (`paired_books`' "sure or answered");
  * a 2.x book split into `.txt` parts, joined and paired through *Pick its audiobook…* → its parts heard;
  * the audiobook away (its source offline) or its item removed → silent;
  * lined up: a line the line-up says is heard and its card is cut from that cue (`lineup.split`); a line it doesn't
    say gets no promise — the AI voice's or none; *Keep them together* and a C grade → silent;
  * a library with no book at all → no read beyond today's one;
  * a watched mark with no date (made before the store kept dates), its show with none → seen "earlier".

Real data: the suite's EPUB built from `Test Resources/<lang>/context_test.txt`, 芥川「蜘蛛の糸」 as 2.x split it.
"""
import os

import pytest

from app.connect import library, lineup, sentences
from tests.connect.test_lineup import LINE_UP_311, _record_miner, _srt_of, no_child_left  # noqa: F401
from tests.connect.test_split_txt_books import _pick, split  # noqa: F401
from tests.test_audiobook_items import _audio_folder, _audio_items, _epub, _fit, _lines, _record, \
    _unsure
from tests.test_sources_scan import _drive, _empty, _look

TITLES = {"ja": "吾輩は猫である", "zh": "骆驼祥子"}
OTHER = {"ja": "坊っちゃん", "zh": "边城"}


def _parts(store, epub):
    """The book's chapter items — its EPUB's live parts `<epub>#<n>` (the store's look-up of a book's parts) — in order."""
    return sorted(store._audiobook_parts({"epub": epub}))


def _heard(store, language, ai=False, **kw):
    """{item id: how its lines are heard} as the dial reads the library (`sentences._library`)."""
    return {v[0]: v[2] for v in sentences._library(language, store, ai, **kw).values()}


def _books(language):
    """A learner's folder: a real EPUB held as chapters in nested folders (Books/文庫/<title>.epub) with its audiobook
    beside it (paired by a real look, sure), and a second book with no audiobook."""
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    title, other = TITLES[language], OTHER[language]
    shelf = os.path.join(src, "Books", "文庫")
    epub = _epub(os.path.join(shelf, f"{title}.epub"), title, language)
    other_epub = _epub(os.path.join(src, "Books", f"{other}.epub"), other, language, repeat=7)   # (other bytes)
    files = _audio_folder(os.path.join(shelf, title), title, _fit(language))
    _look(store, language, store.add_source(src))         # (held open: each test closes it, `with store`)
    [audio] = _audio_items(store)
    rec = _record(store, audio["id"])
    assert rec["book"]["epub"] == os.path.abspath(epub), "paired by the look"
    return {"store": store, "epub": os.path.abspath(epub), "files": files, "audio": audio["id"],
            "key": rec["book"]["key"], "title": title, "other_epub": os.path.abspath(other_epub)}


def _lined(book, lines, grade="A"):
    """The book lined up (Anki Miner's sync finished, as `lineup._ended` writes it): one audio file's SRT of `lines`."""
    srt = os.path.join(lineup.folder(book["key"]), "01.srt")
    os.makedirs(os.path.dirname(srt), exist_ok=True)
    with open(srt, "w", encoding="utf-8") as f:
        f.write(_srt_of(lines))
    lineup.write(book["key"], {"status": lineup.DONE, "grade": grade, "unheard": [], "files": [
        {"audio_file": os.path.abspath(book["files"][0]), "subtitle_file": srt, "status": "synced", "units": {}}]})


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_a_paired_books_chapters_are_heard_and_a_book_with_no_audiobook_is_not(language):
    # why: the bug — the dial looked for an item at the EPUB's own path, and a chapter is never there: every paired
    # book's line was silent, so with the AI voice off Connect's Best and Swap never chose one
    book = _books(language)
    store = book["store"]
    with store:
        mine, other = _parts(store, book["epub"]), _parts(store, book["other_epub"])
        assert len(mine) >= 2 and other, "held as chapters"
        off, on = _heard(store, language), _heard(store, language, ai=True)
    assert {off[i] for i in mine} == {sentences.REAL}, "its narrator's clip"
    assert {on[i] for i in mine} == {sentences.REAL}, "the AI voice on: still the narrator, never the voice"
    assert {off[i] for i in other} == {sentences.SILENT}, "no audiobook, the voice off: silent as before"
    assert {on[i] for i in other} == {sentences.AI_VOICE}
    assert off[book["audio"]] == sentences.REAL, "the audiobook's own item: audio as before"


def test_a_chapters_line_is_a_choice_with_its_clip_where_media_is_cut(no_child_left):
    # why: what the learner gets — Connect's Best (and Swap) now takes a paired book's line as heard, and the line-up
    # cuts its card from the cue that says it; a line the line-up never says is promised nothing
    book = _books("ja")
    store, lines = book["store"], _lines("ja")
    _lined(book, lines[:5])
    with store:
        mine = _parts(store, book["epub"])
        hear = _heard(store, "ja")
    reach = hear[mine[0]]
    assert isinstance(reach, lineup.Reach) and all(hear[i] == reach for i in mine)
    said, unsaid = lines[2], lines[7]
    assert sentences._heard_line(reach, said, False) == sentences.REAL
    assert sentences._heard_line(reach, unsaid, False) is sentences.SILENT, "outside its reach: no clip promised"
    assert sentences._heard_line(reach, unsaid, True) == sentences.AI_VOICE, "...the AI voice's while it is on"
    groups, rest = lineup.split([{"line_text": said, "surface": said[:2]}, {"line_text": unsaid, "surface": unsaid[:2]}],
                                lineup.read(book["key"]))
    [(audio, _srt)] = groups
    assert audio == os.path.abspath(book["files"][0]) and [w["line_text"] for w in rest] == [unsaid], \
        "the heard line is cut from its cue; the other goes as the book, exactly as the dial said"


def test_keep_them_together_or_a_poor_line_up_is_no_clip():
    book = _books("ja")
    store, lines = book["store"], _lines("ja")
    _lined(book, lines, grade="C")
    with store:
        mine = _parts(store, book["epub"])
        assert {_heard(store, "ja")[i] for i in mine} == {sentences.SILENT}, "grade C: never a wrong clip"
        _lined(book, lines)
        assert isinstance(_heard(store, "ja")[mine[0]], lineup.Reach)
        assert store.audiobook_separate(book["audio"], book["key"]) is not None
        assert {_heard(store, "ja")[i] for i in mine} == {sentences.SILENT}, "*Keep them together*: no sentence audio"


@pytest.mark.parametrize("language", ["ja", "zh"])
def test_the_audiobook_away_or_removed_gives_its_chapters_no_clip(language, tmp_path):
    book = _books(language)
    store = book["store"]
    away = os.path.join(str(tmp_path), "away")
    os.rename(os.path.dirname(book["files"][0]), away)          # its drive unplugged: the files aren't here
    with store:
        try:
            mine = _parts(store, book["epub"])
            assert {_heard(store, language)[i] for i in mine} == {sentences.SILENT}
        finally:
            os.rename(away, os.path.dirname(book["files"][0]))
        assert {_heard(store, language)[i] for i in mine} == {sentences.REAL}, "back: heard again"
        assert store.remove([book["audio"]]) is not None
        assert {_heard(store, language)[i] for i in mine} == {sentences.SILENT}, "its item removed: no audiobook"


def test_a_pairing_still_unanswered_is_no_pairing_and_a_yes_makes_it_heard():
    # why: `paired_books`' rule stands — sure or answered; an open question is no promise of audio
    store, _data_dir, src = _unsure("ja")
    with store:
        _look(store, "ja", store.add_source(src), first=True)
        [audio] = _audio_items(store)
        assert _record(store, audio["id"])["ask"] is not None and _record(store, audio["id"])["book"] is None
        mine = _parts(store, _record(store, audio["id"])["ask"]["epub"])
        assert mine and {_heard(store, "ja")[i] for i in mine} == {sentences.SILENT}
        assert store.answer_audiobook(audio["id"], True)
        assert {_heard(store, "ja")[i] for i in mine} == {sentences.REAL}


def test_a_2x_split_books_parts_joined_and_paired_are_heard(split):  # noqa: F811
    with split["steps"]._open("ja") as store:
        assert {_heard(store, "ja")[i] for i in split["parts"]} == {sentences.SILENT}, "no audiobook yet"
    _book, _offered, change = _pick(split)
    assert change is not None
    with split["steps"]._open("ja") as store:
        assert {_heard(store, "ja")[i] for i in split["parts"]} == {sentences.REAL}, "by the joined book's parts"
        assert set(library.paired_parts(store)) == set(split["parts"])


def test_a_library_with_no_book_reads_nothing_more(monkeypatch):
    # why: `_library` is on every mine's and every Swap's path — no audiobook, no part read, no line-up read
    store, _data_dir = _empty("ja")
    monkeypatch.setattr(type(store), "_audiobook_parts", lambda self, book: pytest.fail("no paired book"))
    monkeypatch.setattr(lineup, "read", lambda key: pytest.fail("no line-up"))
    with store:
        assert library.paired_parts(store) == {}
        sentences._library("ja", store)


def test_a_paired_books_line_up_is_read_only_for_its_parts_asked_and_its_cues_once(monkeypatch):
    book = _books("ja")
    store, lines = book["store"], _lines("ja")
    _lined(book, lines[:5])
    reads, srt = [], lineup.srt_cues
    monkeypatch.setattr(lineup, "srt_cues", lambda path: reads.append(path) or srt(path))
    with store:
        other = store.item(_parts(store, book["other_epub"])[0])["rel_path"]
        mine = store.item(_parts(store, book["epub"])[0])["rel_path"]
        sentences._library("ja", store, only=[other])
        assert reads == [], "a reader of another book's lines never reads this one's line-up"
        sentences._library("ja", store, only=[mine])
        sentences._library("ja", store, only=[mine])
    assert len(reads) == 1, "its cues read once while its line-up is unchanged"


def test_a_watched_mark_with_no_date_is_seen_earlier_and_a_dated_or_unwatched_one_is_as_before():
    # why: marks made before the store kept dates have none (350 of 350 on a real library); a watched file was
    # weighed as never seen, below a finished show with no date (*Earlier*). Lead's ruling, PROVISIONAL.
    book = _books("ja")
    store = book["store"]
    with store:
        first, second, third = _parts(store, book["epub"])[:3]

        def weights():
            return {v[0]: v[1] for v in sentences._library("ja", store).values()}
        before = weights()
        with store._writing():
            store.conn.execute("UPDATE items SET watched = 1 WHERE id = ?", (first,))
        now = weights()
        assert now[first] == sentences.EARLIER_WEIGHT, "a mark with no date, its show none: seen earlier"
        assert now[second] == before[second] and now[third] == before[third], "unwatched: as before"
        store.set_watched([second])
        dated = weights()
        assert dated[second] > 0.9, "a dated mark: today's weight, as before"
        assert dated[first] == dated[second], "its show's date now (the borrowed date: unchanged, Sonic's call)"
