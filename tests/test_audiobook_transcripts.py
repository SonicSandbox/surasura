"""An audiobook's transcript (Hon a6: H-12 ✅ Sonic 2026-10-28, H-13 PROVISIONAL): a subtitle file beside an audiobook
is its transcript, never a title of its own.

- **Alone**, the transcript is the audiobook's content: its one item points at the transcript's copy and counts as a
  subtitle does (stones, word count) — no longer *Audio only*.
- **With its book**, the book is the content: the item waits (counted nowhere), the transcript kept with the audio for
  its timing (Anki Miner's Z-16), so the book's words are never counted twice.
- **The content check (H-13)**: paired, the transcript's lines are looked for in the book in order; at CONTENT_SHARE
  or more it is the book's, under it a *Needs you* line says it doesn't match and it isn't used — never in silence.
- A transcript taken in as a subtitle of its own before its audiobook was known becomes the audiobook's item (its
  marks kept), so a library from before this change stops counting it twice too.

Why these matter: a tester's own vol 1 (an M4B, its `.srt` and its EPUB side by side) counted its words twice — the
book's and the transcript's. Every look here runs on real files built on disk (an EPUB of real text, M4Bs and MP3s
with real tags and lengths, transcripts of real sentences) and proves the source folders are never written to.
"""
import json
import logging
import os
import unicodedata

import pytest

from app import audiobooks
from app import library_store as ls
from app.services import needs, view_rows
from tests.test_audiobook_items import (_audio_folder, _audio_items, _book_items, _epub, _fit, _lines, _record,
                                        _fresh_module_state, _settle)  # noqa: F401 (the fixture)
from tests.test_audiobooks import _m4b
from tests.test_library_store_support import RESOURCES
from tests.test_sources_scan import _SHOWS, _drive, _empty, _look, _text, _write

STAR, ISEKAI, SAIYU = "星屑の剣士になりたくて！", "異界転生", "西游记"


@pytest.fixture(autouse=True)
def _no_look_swallows_an_error(caplog):
    """The look keeps going past an audiobook's error (logged, its folders listed again): here, any such error fails
    the test — a defect never hides behind the next look."""
    yield
    said = [r.getMessage() for r in caplog.get_records("call") if r.levelno >= logging.WARNING and
            "Audiobooks wait" in r.getMessage()]
    assert not said, said


# --- builders ------------------------------------------------------------------------------------------------------ #
def _srt(path, lines):
    """A transcript of `lines`, one cue each, two seconds apart."""
    out = []
    for n, line in enumerate(lines, 1):
        t = 2 * n
        out.append(f"{n}\n00:{t // 60:02d}:{t % 60:02d},000 --> 00:{(t + 1) // 60:02d}:{(t + 1) % 60:02d},500\n{line}\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))
    _settle(path)
    return str(path)


def _other_lines(language):
    """Lines of another text of the language (never the book's): a resource episode's transcript."""
    name = "placed_episode.srt" if language == "ja" else "night_market.srt"
    with open(os.path.join(RESOURCES, language, name), encoding="utf-8") as f:
        return audiobooks.cues(f.read())


def _counted(store, place=()):
    """Every item's file Generate reads (its lists, the set-aside ones too); `place`: items moved into Current first
    (New arrivals is never counted until placed — an episode's the same)."""
    if place:
        store.move(list(place), "now")
    return [e["physical_path"] for v in store.schedule(with_aside=True).values() if isinstance(v, list) for e in v]


def _subtitle_titles(store):
    return [r[0] for r in store.conn.execute("SELECT title FROM items WHERE source_type = 'subtitle'")]


def _alone(language, title):
    """An M4B alone with its transcript beside it, named the way Sonic's are (`[1巻] <title> 01` / `<title> ０１`)."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    folder = os.path.join(src, f"[1巻] {title} 01")
    m4b = _m4b(os.path.join(folder, f"[1巻] {title} 01.m4b"), 3600, tags={"album": f"{title} 01"})
    _settle(m4b)
    srt = _srt(os.path.join(folder, f"{title} ０１.srt"), _lines(language)[:12])
    return store, data_dir, src, m4b, srt


# --- alone: the transcript is its content ------------------------------------------------------------------------- #
@pytest.mark.parametrize("language,title", (("ja", STAR), ("zh", SAIYU)))
def test_an_audiobook_alone_with_its_transcript_is_one_item_counted_as_its_transcript(language, title):
    """One item, the audiobook's (never a subtitle title of its own): it points at the transcript's copy, counts as a
    subtitle's does (Generate's lists) and is no longer *Audio only* — its row has its stones, its 🎧 hover says the
    transcript is its text. Nothing is waiting, nothing counted twice."""
    store, data_dir, src, m4b, srt = _alone(language, title)
    with store:
        root = store.add_source(src)
        result = _look(store, language, root)
        [item] = _audio_items(store)
        assert result["added"] == 1 and _subtitle_titles(store) == []           # never a title of its own
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        assert item["availability"] == "available" and item["source_type"] == "audio"
        assert item["rel_path"].endswith(f"{title} ０１.srt") and " (audio)/" in item["rel_path"]
        with open(os.path.join(data_dir, *item["rel_path"].split("/")), encoding="utf-8") as f, \
                open(srt, encoding="utf-8") as g:
            assert f.read() == g.read()                                          # the transcript's own copy
        rec = _record(store, item["id"])
        assert rec["transcript"]["origin"] == os.path.abspath(srt) and rec["files"] == [os.path.abspath(m4b)]
        assert audiobooks.transcript_use(rec) == audiobooks.TEXT
        assert _counted(store, [item["id"]]) == [item["rel_path"]]              # counted, once
        hovers = store.audiobook_hovers()
        assert hovers[item["id"]]["transcript"] == audiobooks.TEXT
        feed = dict(item, audio=hovers[item["id"]])
        works = {item["work_id"]: {"id": item["work_id"], "title": title, "media_type": None}}
        row = view_rows._row(0, item["tier"], [feed], works, {}, {}, set(), set(), 20)
        assert not view_rows.audio_only(row) and row.line != view_rows.STRINGS["audio_only"]
        heard_title = unicodedata.normalize("NFKC", title)                       # the album tag's, as read
        assert row.audio.startswith(f"🎧 Audiobook 「{heard_title} 01」 with its transcript")
        again = _look(store, language, root, full=True)                          # a second look: nothing new
        assert again["added"] == 0 and [i["id"] for i in _audio_items(store)] == [item["id"]]
        assert _subtitle_titles(store) == []


def test_a_transcript_named_otherwise_is_the_one_audiobooks_when_it_is_the_folders_one_subtitle():
    """`transcript.srt` beside the one audiobook of its folder is that audiobook's."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, ISEKAI), ISEKAI, 3000)
    _srt(os.path.join(src, ISEKAI, "transcript.srt"), _lines(language)[:6])
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        assert item["availability"] == "available" and item["rel_path"].endswith("/transcript.srt")
        assert _subtitle_titles(store) == []


def test_a_transcript_arriving_later_makes_the_waiting_audiobook_its_content():
    """Audio only first; its transcript copied in beside it later: the same item now counts it (W → its text)."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    folder = os.path.join(src, ISEKAI)
    _settle(_m4b(os.path.join(folder, f"{ISEKAI}.m4b"), 3600, tags={"album": ISEKAI}))
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        assert item["availability"] == "waiting"
        _srt(os.path.join(folder, f"{ISEKAI}.srt"), _lines(language)[:6])
        _look(store, language, root)
        [now] = _audio_items(store)
        assert now["id"] == item["id"] and now["availability"] == "available" and now["tier"] == item["tier"]
        assert _counted(store, [now["id"]]) == [now["rel_path"]] and _subtitle_titles(store) == []


def test_an_english_subtitle_beside_a_japanese_audiobook_is_never_its_transcript():
    """The language rule (K6) passes over another language's subtitle: no transcript, no title, read once."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    folder = os.path.join(src, ISEKAI)
    _settle(_m4b(os.path.join(folder, f"{ISEKAI}.m4b"), 3600, tags={"album": ISEKAI}))
    _srt(os.path.join(folder, f"{ISEKAI}.srt"), ["The station was quiet before the first train came."] * 5)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        assert item["availability"] == "waiting" and "transcript" not in _record(store, item["id"])
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_a_removed_audiobook_keeps_its_transcript_out_too():
    """Remove (S6) keeps the audiobook out; its transcript never comes back as a title of its own."""
    language = "ja"
    store, _data_dir, src, _m4b_path, _srt_path = _alone(language, STAR)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        store.remove([_audio_items(store)[0]["id"]])
        again = _look(store, language, root, full=True)
        assert again["added"] == 0 and store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


def test_an_edited_transcript_is_copied_again_over_its_copy():
    """S5: the transcript changed on disk — its copy follows, the same item (no second copy, no new title)."""
    language = "ja"
    store, data_dir, src, _m4b_path, srt = _alone(language, STAR)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        grown = _lines(language)[:12] + _lines(language)[:4]                     # (a shrink under half: refused, S5)
        _srt(srt, grown)
        result = _look(store, language, root, full=True)
        [now] = _audio_items(store)
        assert now["id"] == item["id"] and now["rel_path"] == item["rel_path"] and result["recopied"] == 1
        with open(os.path.join(data_dir, *now["rel_path"].split("/")), encoding="utf-8") as f:
            assert f.read().count("-->") == len(grown)
        assert _record(store, item["id"])["transcript"]["size"] == os.path.getsize(srt)
        copy = os.path.join(data_dir, *now["rel_path"].split("/"))
        assert store.item(item["id"])["size"] == os.path.getsize(copy)            # the item's own stats follow


def test_a_renamed_audiobook_folder_keeps_its_item_and_its_transcripts_copy():
    """D5: the folder renamed, files the same — the same item, its transcript's new path recorded, its copy reused."""
    language = "ja"
    store, data_dir, src, _m4b_path, _srt_path = _alone(language, STAR)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        os.rename(os.path.join(src, f"[1巻] {STAR} 01"), os.path.join(src, f"{STAR} 第1巻"))
        _look(store, language, root, full=True)
        [now] = _audio_items(store)
        assert now["id"] == item["id"] and now["rel_path"] == item["rel_path"]
        rec = _record(store, item["id"])
        assert rec["transcript"]["origin"].endswith(os.path.join(f"{STAR} 第1巻", f"{STAR} ０１.srt"))
        copies = os.listdir(os.path.join(data_dir, *item["rel_path"].split("/")[:-1]))
        assert [c for c in copies if c.endswith(".srt")] == [f"{STAR} ０１.srt"]
        assert _subtitle_titles(store) == []


def test_a_second_subtitle_named_alike_never_takes_the_transcripts_place_nor_a_title():
    """Its transcript recorded and still there: a second subtitle named like it later (an `.ass` of the same lines) is
    never claimed (it would swap the two at every look), nor a title of its own — the transcript stays, look after
    look."""
    language = "ja"
    store, _data_dir, src, _m4b_path, srt = _alone(language, STAR)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        _srt(os.path.join(os.path.dirname(srt), f"{STAR} ０１ (2).srt"), _lines(language)[:8])
        for _ in range(2):
            _look(store, language, root, full=True)
            [now] = _audio_items(store)
            assert now["id"] == item["id"] and now["rel_path"] == item["rel_path"]
            assert _record(store, item["id"])["transcript"]["origin"] == os.path.abspath(srt)
            assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_the_same_audiobook_and_transcript_in_two_sources_is_one_item_counted_once():
    """The folder copied into a second source: its audiobook is the same item even though that item now points at its
    transcript, and the second transcript is never a second copy, item or title (counted once)."""
    import shutil
    language = "ja"
    store, data_dir, src, _m4b_path, srt = _alone(language, STAR)
    other = _drive("driveB")
    shutil.copytree(os.path.dirname(srt), os.path.join(other, os.path.basename(os.path.dirname(srt))))
    for where, _dirs, names in os.walk(other):
        for n in names:
            _settle(os.path.join(where, n))
    with store:
        a, b = store.add_source(src), store.add_source(other)
        _look(store, language, a)
        _look(store, language, b)
        assert _look(store, language, b, full=True)["waiting"] == 0             # nothing left waiting (no re-listing)
        _look(store, language, a, full=True)
        [item] = _audio_items(store)
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        recs = [r[2]["audiobook"] for r in store._audiobook_rows(item["id"])]   # one record per source (its files)
        assert len(recs) == 2 and all(r["transcript"]["origin"] == os.path.abspath(srt) for r in recs)
        copies = os.listdir(os.path.join(data_dir, *item["rel_path"].split("/")[:-1]))
        assert [c for c in copies if c.endswith(".srt")] == [f"{STAR} ０１.srt"]
        assert _counted(store, [item["id"]]) == [item["rel_path"]]


def test_a_transcripts_copy_gone_from_the_library_is_copied_back():
    """Item 8a, as a subtitle's: the copy deleted from `Library` (the original still there) — written back on the
    next look that lists its folder, the item counted again."""
    language = "ja"
    store, data_dir, src, _m4b_path, srt = _alone(language, STAR)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        copy = os.path.join(data_dir, *item["rel_path"].split("/"))
        os.remove(copy)
        store.sync_disk()
        assert store.item(item["id"])["availability"] == "missing"
        result = _look(store, language, root, full=True)
        assert os.path.isfile(copy) and result["restored"] == 1
        assert store.item(item["id"])["availability"] == "available"


def test_a_renamed_and_edited_transcript_leaves_no_copy_behind():
    """The transcript renamed and edited on disk: the new one is copied and recorded, the old copy goes to the trash
    (never left in `Library` with no item holding it)."""
    language = "ja"
    store, data_dir, src, _m4b_path, srt = _alone(language, STAR)
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        folder = os.path.join(data_dir, *item["rel_path"].split("/")[:-1])
        os.remove(srt)
        _srt(os.path.join(os.path.dirname(srt), f"{STAR} 第1巻.srt"), _lines(language)[:12] + _lines(language)[:2])
        _look(store, language, root, full=True)
        [now] = _audio_items(store)
        assert now["id"] == item["id"] and now["rel_path"].endswith(f"{STAR} 第1巻.srt")
        assert sorted(c for c in os.listdir(folder) if c.endswith(".srt")) == [f"{STAR} 第1巻.srt"]


def test_a_file_added_to_an_audiobook_or_its_audio_renamed_keeps_its_transcript():
    """Its records written anew (a new first file: `grown`; its audio renamed: D5's move) still hold its transcript:
    the same item, counted by it."""
    from tests.test_audiobooks import _mp3
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    folder = os.path.join(src, ISEKAI)
    _audio_folder(folder, ISEKAI, 3000)
    _srt(os.path.join(folder, f"{ISEKAI}.srt"), _lines(language)[:12])
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        _settle(_mp3(os.path.join(folder, "00.mp3"), seconds=600, frames={"TALB": ISEKAI, "TRCK": "0"}))
        _look(store, language, root, full=True)
        recs = [r[2]["audiobook"] for r in store._audiobook_rows(item["id"])]    # the new first file's record too
        assert len(recs) == 2 and all(r.get("transcript") == recs[0]["transcript"] for r in recs)
        os.rename(os.path.join(folder, "02.mp3"), os.path.join(folder, "02b.mp3"))
        _look(store, language, root, full=True)
        [now] = _audio_items(store)
        rec = _record(store, item["id"])
        assert now["id"] == item["id"] and now["availability"] == "available"
        assert rec["files"][0].endswith("00.mp3") and rec["transcript"]["origin"].endswith(f"{ISEKAI}.srt")
        assert store.audiobook_hovers()[item["id"]]["transcript"] == audiobooks.TEXT


def test_a_check_that_couldnt_be_made_is_made_by_a_later_look(monkeypatch):
    """The book's copies unreadable when the pair is made: never counted, nothing said — a later look checks it."""
    language = "ja"
    store, _data_dir, src, _srt_path = _paired(language, STAR, _lines(language)[:12])
    with store:
        root = store.add_source(src)
        with monkeypatch.context() as patched:
            patched.setattr(ls.Store, "_transcript_found", lambda self, said, book: None)
            _look(store, language, root, first=True)
        [heard] = [r for r in _book_items(store, STAR)[1] if r[3] == "audio"]
        assert heard[4] == "waiting" and audiobooks.transcript_use(_record(store, heard[0])) == audiobooks.UNCHECKED
        assert [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_TRANSCRIPT] == []
        _look(store, language, root, full=True)
        assert audiobooks.transcript_use(_record(store, heard[0])) == audiobooks.TIMING


def test_a_placeholder_audiobook_holds_its_transcript_back_until_it_is_here(monkeypatch):
    """A cloud placeholder's audio is never opened; its transcript waits with it (never a title of its own meanwhile)."""
    language = "ja"
    store, _data_dir, src, m4b, _srt_path = _alone(language, STAR)
    real = ls.is_placeholder
    st = os.stat(m4b)
    monkeypatch.setattr(ls, "is_placeholder", lambda s: (s.st_size, s.st_mtime_ns) == (st.st_size, st.st_mtime_ns)
                        or real(s))
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
        monkeypatch.setattr(ls, "is_placeholder", real)
        _look(store, language, root)
        [item] = _audio_items(store)
        assert item["availability"] == "available" and _subtitle_titles(store) == []


# --- with its book: the book is the content ----------------------------------------------------------------------- #
def _paired(language, title, transcript):
    """The EPUB and a folder of its chapter MP3s side by side (a sure pair), `transcript`'s lines beside the MP3s."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    _epub(os.path.join(src, "Books", f"{title}.epub"), title, language)
    _audio_folder(os.path.join(src, "Books", title), title, _fit(language))
    srt = _srt(os.path.join(src, "Books", title, f"{title}.srt"), transcript)
    return store, data_dir, src, srt


@pytest.mark.parametrize("language,title", (("ja", STAR), ("zh", SAIYU)))
def test_an_audiobook_with_its_book_and_transcript_counts_the_books_words_once(language, title):
    """The book's parts are the content; the audiobook's item waits in the book's title (the transcript kept with it
    for timing, its copy kept) — the transcript is never a title of its own and never counted: words counted once."""
    store, data_dir, src, srt = _paired(language, title, _lines(language)[:12])
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        work, rows = _book_items(store, title)
        heard = [r for r in rows if r[3] == "audio"]
        assert len(heard) == 1 and heard[0][4] == "waiting" and rows[-1][0] == heard[0][0]
        assert _subtitle_titles(store) == []
        rec = _record(store, heard[0][0])
        assert audiobooks.transcript_use(rec) == audiobooks.TIMING and rec["transcript"]["found"]["share"] == 1.0
        assert os.path.isfile(os.path.join(data_dir, *rec["transcript"]["rel"].split("/")))   # kept for its timing
        item = store.item(heard[0][0])
        assert audiobooks.is_audio(item["rel_path"]) and item["rel_path"] not in _counted(store)
        parts = [r[0] for r in rows if r[3] != "audio"]
        assert sorted(_counted(store)) == sorted(store.item(i)["rel_path"] for i in parts)    # the book's, once
        assert [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_TRANSCRIPT] == []
        feed = [dict(store.item(i)) for i in parts] + [dict(item, audio=store.audiobook_hovers()[item["id"]])]
        row = view_rows._row(0, item["tier"], feed, {work: {"id": work, "title": title, "media_type": "book"}}, {},
                             {}, set(), set(), 20)
        assert view_rows.STRINGS["audio_transcript_timing"] in row.audio


@pytest.mark.parametrize("language,title", (("ja", STAR), ("zh", SAIYU)))
def test_a_transcript_its_book_doesnt_hold_is_never_used_and_needs_you_says_so(language, title):
    """H-13: another text's transcript beside a sure pair — under CONTENT_SHARE of it in the book: not counted, not a
    title, one *Needs you* line naming both (never silent)."""
    store, _data_dir, src, srt = _paired(language, title, _other_lines(language))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        work, rows = _book_items(store, title)
        [heard] = [r for r in rows if r[3] == "audio"]
        rec = _record(store, heard[0])
        assert heard[4] == "waiting" and audiobooks.transcript_use(rec) == audiobooks.OTHER
        assert rec["transcript"]["found"]["share"] < audiobooks.CONTENT_SHARE and _subtitle_titles(store) == []
        asks = [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_TRANSCRIPT]
        assert len(asks) == 1 and asks[0]["item_id"] == heard[0]
        [entry] = [e for e in needs.entries(None, asks=asks) if e.kind == needs.AUDIOBOOK_TRANSCRIPT]
        heard_title = unicodedata.normalize("NFKC", title)                       # the album tag's, as read
        assert entry.title == f"The transcript beside 「{heard_title}」 doesn't match 「{title}」"
        assert entry.actions == () and "doesn't use it" in entry.say
        assert store.item(heard[0])["rel_path"] not in _counted(store)


def test_a_paired_transcript_rewritten_as_another_text_is_checked_again():
    """The check is the transcript's bytes': its file rewritten with another text's lines (copied over its copy, S5),
    the next look checks it again — no longer the book's: not used, and *Needs you* says so."""
    language = "ja"
    store, _data_dir, src, srt = _paired(language, STAR, _lines(language)[:12])
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        [heard] = [r for r in _book_items(store, STAR)[1] if r[3] == "audio"]
        assert audiobooks.transcript_use(_record(store, heard[0])) == audiobooks.TIMING
        _srt(srt, _other_lines(language) * 2)
        _look(store, language, root, full=True)
        assert audiobooks.transcript_use(_record(store, heard[0])) == audiobooks.OTHER
        assert [a["item_id"] for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_TRANSCRIPT] == [heard[0]]


def test_a_book_arriving_after_an_audiobook_counted_by_its_transcript_takes_the_count_back():
    """Alone with its transcript (counted), then its book arrives beside it and pairs: the item waits again in the
    book's title — the book's words count, the transcript's no longer."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _audio_folder(os.path.join(src, "Books", STAR), STAR, _fit(language))
    _srt(os.path.join(src, "Books", STAR, f"{STAR}.srt"), _lines(language)[:12])
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [item] = _audio_items(store)
        assert item["availability"] == "available" and _counted(store, [item["id"]]) == [item["rel_path"]]
        _epub(os.path.join(src, "Books", f"{STAR}.epub"), STAR, language)
        _look(store, language, root)
        work, rows = _book_items(store, STAR)
        [now] = _audio_items(store)
        assert now["id"] == item["id"] and now["availability"] == "waiting" and now["work_id"] == work
        assert now["rel_path"] not in _counted(store) and audiobooks.is_audio(now["rel_path"])
        assert audiobooks.transcript_use(_record(store, item["id"])) == audiobooks.TIMING


def test_an_asked_audiobook_waits_and_a_pick_takes_the_count_its_undo_gives_it_back():
    """Unsure (asked about a book): its transcript waits for the answer (the book may be the same: never counted twice
    meanwhile). *No* leaves it alone — its transcript counts. *Find its book…*'s pick pairs it — the book counts, the
    item waits; its Undo puts it back alone, its transcript counted again."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    book = _epub(os.path.join(src, "Books", f"{STAR}.epub"), STAR, language)
    _audio_folder(os.path.join(src, "Audio", STAR), STAR, _fit(language) * 4)      # far and too long: unsure
    _srt(os.path.join(src, "Audio", STAR, f"{STAR}.srt"), _lines(language)[:12])
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        [item] = _audio_items(store)
        assert _record(store, item["id"])["ask"] and item["availability"] == "waiting"
        assert audiobooks.transcript_use(_record(store, item["id"])) == audiobooks.ASKED
        store.answer_audiobook(item["id"], False)
        alone = store.item(item["id"])
        assert alone["availability"] == "available" and alone["rel_path"].endswith(f"{STAR}.srt")
        change = store.pick_audiobook_book(item["id"], book)
        assert change is not None
        now = store.item(item["id"])
        assert now["availability"] == "waiting" and now["rel_path"] not in _counted(store)
        assert audiobooks.transcript_use(_record(store, item["id"])) == audiobooks.TIMING
        store.undo(change)
        back = store.item(item["id"])
        assert back["availability"] == "available" and back["rel_path"] == alone["rel_path"]
        assert alone["rel_path"] in _counted(store, [item["id"]])


def test_a_paired_transcript_with_no_line_long_enough_to_look_for_says_nothing():
    """H-13: a transcript whose cues are all too short to look for can't be checked against its book — never counted,
    and *Needs you* says nothing (it has nothing to say it doesn't match)."""
    language = "ja"
    short = ["今日は晴れです。", "そうなんですね。", "ありがとうね。", "またあしたね。", "おやすみなさい。"] * 4
    store, _data_dir, src, _srt_path = _paired(language, STAR, short)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        [heard] = [r for r in _book_items(store, STAR)[1] if r[3] == "audio"]
        assert heard[4] == "waiting" and audiobooks.transcript_use(_record(store, heard[0])) == audiobooks.OTHER
        assert [a for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_TRANSCRIPT] == []


# --- a transcript already in as a title of its own (before this change) -------------------------------------------- #
@pytest.mark.parametrize("language,title", (("ja", STAR), ("zh", SAIYU)))
def test_a_transcript_already_in_as_its_own_title_becomes_the_audiobooks_item_with_its_marks(language, title):
    """The transcript was taken in as a subtitle of its own (its audio not there yet — or a Surasura before this
    change); the audio comes: THAT item becomes the audiobook's (its id, its watched mark kept), the waiting item the
    audio would have made goes, one item is left and it counts once."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    folder = os.path.join(src, f"[1巻] {title} 01")
    _srt(os.path.join(folder, f"{title} ０１.srt"), _lines(language)[:12])
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [old] = [store.item(i) for (i,) in store.conn.execute("SELECT id FROM items")]
        assert old["source_type"] == "subtitle"
        store.set_watched([old["id"]])
        _settle(_m4b(os.path.join(folder, f"[1巻] {title} 01.m4b"), 3600, tags={"album": f"{title} 01"}))
        _look(store, language, root)
        [item] = _audio_items(store)
        assert item["id"] == old["id"] and item["watched"] and item["availability"] == "available"
        assert item["rel_path"] == old["rel_path"]                                # its copy, kept
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        rec = _record(store, item["id"])
        assert rec["transcript"]["rel"] == old["rel_path"] and rec["files"][0].endswith(".m4b")
        assert not store.conn.execute("SELECT 1 FROM pairings WHERE content_key = ?",
                                      (ls.origin_key(rec["transcript"]["origin"]),)).fetchone()
        assert _counted(store, [item["id"]]) == [item["rel_path"]]
        again = _look(store, language, root, full=True)
        assert again["added"] == 0 and store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_a_finished_transcript_merged_into_its_audiobook_stays_in_finished():
    """The learner finished the transcript as a title of its own: becoming the audiobook's item, it stays in Finished
    (its place is the learner's)."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    folder = os.path.join(src, f"[1巻] {STAR} 01")
    _srt(os.path.join(folder, f"{STAR} ０１.srt"), _lines(language)[:12])
    with store:
        root = store.add_source(src)
        _look(store, language, root)
        [old] = [store.item(i) for (i,) in store.conn.execute("SELECT id FROM items")]
        store.move([old["id"]], "graduated")
        _settle(_m4b(os.path.join(folder, f"[1巻] {STAR} 01.m4b"), 3600, tags={"album": f"{STAR} 01"}))
        _look(store, language, root)
        [item] = _audio_items(store)
        assert item["id"] == old["id"] and item["tier"] == "graduated"
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_a_transcript_already_in_beside_its_book_stops_counting_twice():
    """Sonic's vol 1: the book and the transcript were both in (the transcript a title of its own, counted twice);
    the audiobook's look makes the transcript's item the audiobook's, waiting in the book's title — counted once."""
    language = "ja"
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    _epub(os.path.join(src, "Books", f"{STAR}.epub"), STAR, language)
    _srt(os.path.join(src, "Books", STAR, f"{STAR}.srt"), _lines(language)[:12])
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert len(_subtitle_titles(store)) == 1                                 # counted twice today
        for p in _audio_folder(os.path.join(src, "Books", STAR), STAR, _fit(language)):
            assert os.path.isfile(p)
        _look(store, language, root)
        work, rows = _book_items(store, STAR)
        [heard] = [r for r in rows if r[3] == "audio"]
        assert heard[4] == "waiting" and _subtitle_titles(store) == []
        parts = [r[0] for r in rows if r[3] != "audio"]
        assert sorted(_counted(store)) == sorted(store.item(i)["rel_path"] for i in parts)


# --- the pure rules ----------------------------------------------------------------------------------------------- #
def _ab(title, volume=None, folder="f"):
    return audiobooks.Audiobook(folder=folder, files=[f"{folder}/{title}.m4b"], title=title, titles=[title],
                                authors=[], volume=volume, seconds=3600, size=1, sizes=(1,), chapters=None)


@pytest.mark.parametrize("found,names,want", (
    # Sonic's naming: the audio's `[1巻] … 01`, the transcript's full-width `０１` — the same volume
    ([_ab("[1巻] 星屑の剣士になりたくて！ 01", "1")], ["星屑の剣士になりたくて！ ０１.srt", "星屑の剣士になりたくて！ ０２.srt"],
     {0: "星屑の剣士になりたくて！ ０１.srt"}),
    # one folder of volumes: each its own volume's, never a neighbour's
    ([_ab("異界転生 2", "2"), _ab("異界転生 3", "3")], ["異界転生 03.srt", "異界転生 02.ass"],
     {0: "異界転生 02.ass", 1: "異界転生 03.srt"}),
    # any name, when it is the one subtitle beside the one audiobook
    ([_ab("西游记")], ["transcript.srt"], {0: "transcript.srt"}),
    # two subtitles, neither named like it: neither (a show's, a note's — the look takes them as any)
    ([_ab("西游记")], ["a.srt", "b.srt"], {}),
    # a `.txt` is never a transcript (a book's text)
    ([_ab("西游记")], ["西游记.txt"], {}),
    # a transcript with no volume beside two volumes of the title: neither's (never a guess)
    ([_ab("異界転生 2", "2"), _ab("異界転生 3", "3")], ["異界転生.srt"], {}),
    # another volume's transcript is never this one's, even alone in the folder by name
    ([_ab("異界転生 2", "2")], ["異界転生 05.srt", "notes.srt"], {}),
))
def test_which_subtitle_is_an_audiobooks_transcript(found, names, want):
    assert audiobooks.transcripts(found, names) == want


def test_cues_and_the_in_order_share():
    srt = "1\n00:00:01,000 --> 00:00:02,000\n吾輩は猫である。\n名前はまだ無い。\n\n2\n00:00:03,000 --> 00:00:04,000\nにゃ\n"
    assert audiobooks.cues(srt) == ["吾輩は猫である名前はまだ無い"]                # short cues are never looked for
    ass = "[Script Info]\n[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\i1}吾輩は猫である。\\N名前はまだ無い。"
    assert audiobooks.cues(ass) == ["吾輩は猫である名前はまだ無い"]
    book = audiobooks.clean_text("<p>吾輩は<ruby>猫<rt>ねこ</rt></ruby>である。名前はまだ無い。</p>どこで生れたかとんと見当がつかぬ。")
    assert audiobooks.found_in_order(["吾輩は猫である名前はまだ無い", "どこで生れたかとんと見当"], book) == 1.0
    assert audiobooks.found_in_order(["どこで生れたかとんと見当", "吾輩は猫である名前はまだ無い"], book) == 0.5   # in order
    assert audiobooks.found_in_order([], book) is None


def test_what_a_transcript_is_for():
    said = {"origin": "x.srt", "rel": "Library/x (audio)/x.srt"}
    book = {"epub": "b.epub", "sha256": "s1"}
    assert audiobooks.transcript_use({"book": None}) is None
    assert audiobooks.transcript_use({"transcript": said, "book": None}) == audiobooks.TEXT
    assert audiobooks.transcript_use({"transcript": said, "book": book}) == audiobooks.UNCHECKED
    found = lambda share, mark="s1": dict(said, found={"book": mark, "share": share,  # noqa: E731
                                                   "rule": audiobooks.FOUND_RULE})
    assert audiobooks.transcript_use({"transcript": found(0.6), "book": book}) == audiobooks.TIMING
    assert audiobooks.transcript_use({"transcript": found(0.59), "book": book}) == audiobooks.OTHER
    assert audiobooks.transcript_use({"transcript": found(None), "book": book}) == audiobooks.OTHER
    assert audiobooks.transcript_use({"transcript": found(1.0, "s2"), "book": book}) == audiobooks.UNCHECKED


# --- Kura-AB5: the in-order share is the longest run (based on the diagnosis in #432 by Mattias; 本好きの下剋上 vol 3) - #
def _colophon_case(language):
    """The narrator reads the title first; the book's text holds it only in its colophon, at the very end (its cover
    an image) -> (cues, book text)."""
    title = {"ja": "本好きの下剋上第一部兵士の娘III", "zh": "西游记第一回灵根育孕源流出"}[language]
    lines = [audiobooks.clean_text(x) for x in _lines(language)]
    lines = [x for x in lines if len(x) >= audiobooks.CUE_MIN]
    book = audiobooks.clean_text("".join(_lines(language)) + "奥付" + title + "発行")
    return [audiobooks.clean_text(title)] + lines, book, len(lines)


@pytest.mark.parametrize("language", ("ja", "zh"))
def test_a_title_read_first_but_found_only_in_the_colophon_costs_only_itself(language):
    """#432: the first cue found at the book's end moved the search past every other cue — 15 of 6548 found (0.0023)
    though 99.88 % are in the book. Now one cue found far off costs only itself."""
    cues, book, n = _colophon_case(language)
    assert audiobooks.found_in_order(cues, book) == n / (n + 1)
    assert audiobooks.found_in_order(cues, book) >= audiobooks.CONTENT_SHARE


def test_the_in_order_share_is_the_longest_run_on_real_text():
    """The index (`found_in_order`) finds exactly the longest run of cues in the book's order a plain search over
    every place finds — the book's own lines shuffled, repeated and mixed with another text's; a cue repeated in the
    transcript but once in the book counts once."""
    import random
    book = audiobooks.clean_text("".join(_lines("ja")) * 3)
    lines = [audiobooks.clean_text(x) for x in _lines("ja") + _other_lines("ja")]
    lines = [x for x in lines if len(x) >= audiobooks.CUE_MIN]
    random.Random(7).shuffle(lines)

    def plain(cues, text):
        ends = []                                       # [(place, the longest run ending there)]
        for c in cues:
            here = [i for i in range(len(text)) if text.startswith(c, i)]
            ends += [(i, 1 + max([k for j, k in ends if j < i], default=0)) for i in here]
        return max([k for _i, k in ends], default=0) / len(cues)
    assert audiobooks.found_in_order(lines, book) == plain(lines, book) and 0 < plain(lines, book) < 1
    once = audiobooks.clean_text("".join(_lines("ja")))
    twice = [lines[0], lines[0]] if lines[0] in once else [audiobooks.clean_text(_lines("ja")[0])] * 2
    assert audiobooks.found_in_order(twice, once) == 0.5


def test_a_book_judged_under_the_first_rule_and_found_wanting_is_judged_again_once():
    """3.0.8's checks went by the first rule (no `rule`): one found wanting is checked again under this one; one found
    the book's stays (the longest run is never shorter); one judged by this rule stays judged."""
    said = {"origin": "x.srt", "rel": "Library/x (audio)/x.srt"}
    book = {"epub": "b.epub", "sha256": "s1"}
    old = lambda share: dict(said, found={"book": "s1", "share": share})  # noqa: E731
    now = lambda share: dict(said, found={"book": "s1", "share": share, "rule": audiobooks.FOUND_RULE})  # noqa: E731
    assert audiobooks.transcript_use({"transcript": old(0.0023), "book": book}) == audiobooks.UNCHECKED
    assert audiobooks.transcript_use({"transcript": old(0.9), "book": book}) == audiobooks.TIMING
    assert audiobooks.transcript_use({"transcript": now(0.0023), "book": book}) == audiobooks.OTHER


def test_a_transcript_judged_wanting_by_the_first_rule_is_its_books_at_the_next_look():
    """Store and look: his vol 3 as 3.0.8 left it — its transcript found wanting (no `rule`). The next look of its
    folder checks it again: the book's (TIMING), recorded under this rule, and never checked again after."""
    store, _data_dir, src, _srt_path = _paired("ja", STAR, _lines("ja")[:12])
    with store:
        root = store.add_source(src)
        _look(store, "ja", root, first=True)
        _work, rows = _book_items(store, STAR)
        item = [r for r in rows if r[3] == "audio"][0][0]
        with store._writing():
            for key, text in store.conn.execute("SELECT content_key, pairing FROM pairings WHERE item_id = ?",
                                                (item,)).fetchall():
                rec = json.loads(text)
                found = rec["audiobook"]["transcript"]["found"]
                rec["audiobook"]["transcript"]["found"] = {"book": found["book"], "share": 0.0023}   # as 3.0.8's
                store.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?", (json.dumps(rec), key))
        assert audiobooks.transcript_use(_record(store, item)) == audiobooks.UNCHECKED
        _look(store, "ja", root, full=True)
        rec = _record(store, item)
        assert audiobooks.transcript_use(rec) == audiobooks.TIMING
        assert rec["transcript"]["found"] == {"book": found["book"], "share": 1.0, "rule": audiobooks.FOUND_RULE}


# --- a library's first look under a new rule (Kura-AB6, based on Mattias's #432) ---------------------------------- #
def _audio_item(store, title):
    _work, rows = _book_items(store, title)
    [item] = [r[0] for r in rows if r[3] == "audio"]
    return item


def _as_3_0_8_left(store, item):
    """The item's transcript as 3.0.8 judged it (rule 1, no `rule`: found wanting), in a library no look has weighed
    by this rule yet (no meta `transcript_rule`): his library as the 3.0.9 update found it."""
    with store._writing():
        for key, text in store.conn.execute("SELECT content_key, pairing FROM pairings WHERE item_id = ?",
                                            (item,)).fetchall():
            rec = json.loads(text)
            found = rec["audiobook"]["transcript"]["found"]
            rec["audiobook"]["transcript"]["found"] = {"book": found["book"], "share": 0.0023}
            store.conn.execute("UPDATE pairings SET pairing = ? WHERE content_key = ?", (json.dumps(rec), key))
        store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.TRANSCRIPT_RULE,))
    assert audiobooks.transcript_use(_record(store, item)) == audiobooks.UNCHECKED


def _traced(store, language, root, **kw):
    """A look with every statement it ran -> (its result, [sql])."""
    sql = []
    store.conn.set_trace_callback(sql.append)
    try:
        return _look(store, language, root, **kw), sql
    finally:
        store.conn.set_trace_callback(None)


def _transcript_asks(store):
    return [a["item_id"] for a in needs.asks_of(store) if a["kind"] == needs.AUDIOBOOK_TRANSCRIPT]


@pytest.mark.parametrize("own", (True, False), ids=("its-books", "anothers"))
@pytest.mark.parametrize("language,title", (("ja", STAR), ("zh", SAIYU)))
def test_a_library_3_0_8_left_is_judged_again_by_its_first_quick_look_though_no_folder_changed(language, title, own,
                                                                                                monkeypatch):
    """Mattias's vol 3 after the 3.0.9 update (#432): a transcript 3.0.8 found wanting read UNCHECKED, but only a look
    that listed its folder checked it again — and Surasura's looks are quick ones, which weigh no audiobook whose
    folder is unchanged, so it stayed unused (Connect mined it without its timing). Now a library's first look under a
    new rule (meta `transcript_rule` isn't FOUND_RULE), a quick one too, weighs every audiobook once: its book's
    transcript is its timing again, no card; another book's is said once, judged by this rule. The meta then says this
    rule: the next quick look weighs none and writes nothing (it reads the origins the check rewrote once, F13b, as
    after any write), and the one after reads no record at all."""
    store, _data_dir, src, _srt_path = _paired(language, title, _lines(language)[:12] if own else _other_lines(language))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert str(store.meta()[ls.TRANSCRIPT_RULE]) == str(audiobooks.FOUND_RULE)    # a new library's: said at once
        item = _audio_item(store, title)
        judged = _record(store, item)["transcript"]["found"]
        assert judged["rule"] == audiobooks.FOUND_RULE
        _as_3_0_8_left(store, item)
        assert _transcript_asks(store) == []
        _look(store, language, root)                     # a quick look: no folder of it changed
        rec = _record(store, item)
        use = audiobooks.TIMING if own else audiobooks.OTHER
        assert audiobooks.transcript_use(rec) == use and rec["transcript"]["found"] == judged
        assert store.audiobook_hovers()[item]["transcript"] == use
        assert _transcript_asks(store) == ([] if own else [item])
        assert str(store.meta()[ls.TRANSCRIPT_RULE]) == str(audiobooks.FOUND_RULE)
        changes, versions = store.conn.total_changes, store.versions()
        weighed = []
        monkeypatch.setattr(store, "audiobooks", lambda *a, **kw: weighed.append(kw) or [])
        _look(store, language, root)                     # the next quick look: weighs none
        assert weighed == [] and store.conn.total_changes == changes and store.versions() == versions
        _result, sql = _traced(store, language, root)
        assert not [s for s in sql if "pairings" in s], sql
        assert store.conn.total_changes == changes and store.versions() == versions


def test_a_look_stopped_while_it_weighs_them_never_says_the_rule_and_the_next_look_weighs_them(monkeypatch):
    """A look stopped (the learner's Stop, the window closing) once it began weighing the audiobooks again never says
    the library was weighed by this rule: the next look, a quick one, weighs them again — never a check skipped for
    good."""
    store, _data_dir, src, _srt_path = _paired("ja", STAR, _lines("ja")[:12])
    with store:
        root = store.add_source(src)
        _look(store, "ja", root, first=True)
        item = _audio_item(store, STAR)
        _as_3_0_8_left(store, item)
        weighing, real = [], store.audiobooks

        def audiobooks_read(*a, **kw):
            weighing.append(kw.get("every"))
            return real(*a, **kw)
        monkeypatch.setattr(store, "audiobooks", audiobooks_read)
        result = _look(store, "ja", root, stop=lambda: True in weighing)
        assert result["stopped"] and weighing == [True]
        assert audiobooks.transcript_use(_record(store, item)) == audiobooks.UNCHECKED
        assert ls.TRANSCRIPT_RULE not in store.meta()
        _look(store, "ja", root)
        assert audiobooks.transcript_use(_record(store, item)) == audiobooks.TIMING
        assert str(store.meta()[ls.TRANSCRIPT_RULE]) == str(audiobooks.FOUND_RULE)


def test_a_store_busy_while_it_weighs_them_never_says_the_rule_and_the_next_look_weighs_them(monkeypatch):
    """The store busy mid re-check (another window's write: StoreError) is a look that waits, never one that says the
    library was weighed by this rule: the next quick look checks it again."""
    store, _data_dir, src, _srt_path = _paired("ja", STAR, _lines("ja")[:12])
    with store:
        root = store.add_source(src)
        _look(store, "ja", root, first=True)
        item = _audio_item(store, STAR)
        _as_3_0_8_left(store, item)
        real = store.set_transcript

        def busy(*a, **kw):
            monkeypatch.setattr(store, "set_transcript", real)    # busy once
            raise ls.StoreError("The library is busy.")
        monkeypatch.setattr(store, "set_transcript", busy)
        _look(store, "ja", root)
        assert audiobooks.transcript_use(_record(store, item)) == audiobooks.UNCHECKED
        assert ls.TRANSCRIPT_RULE not in store.meta()
        _look(store, "ja", root)
        assert audiobooks.transcript_use(_record(store, item)) == audiobooks.TIMING
        assert str(store.meta()[ls.TRANSCRIPT_RULE]) == str(audiobooks.FOUND_RULE)


def test_another_sources_look_weighs_an_away_sources_audiobooks_from_the_librarys_copies():
    """The rule is the library's, not a source's: a library of two sources, the audiobook's own away (a drive
    unplugged) — the other's quick look checks it again from Surasura's copies of the transcript and the book (the
    away folder never read) and says the rule once for both."""
    store, _data_dir, src, _srt_path = _paired("ja", STAR, _lines("ja")[:12])
    other = _drive("driveB")
    _write(os.path.join(other, _SHOWS["ja"][0], "ep01.srt"), _text("ja", 1))
    _settle(other)
    with store:
        root = store.add_source(src)
        _look(store, "ja", root, first=True)
        second = store.add_source(other)
        _look(store, "ja", second, first=True)
        item = _audio_item(store, STAR)
        _as_3_0_8_left(store, item)
        os.rename(src, src + " (unplugged)")
        try:
            _look(store, "ja", second)
        finally:
            os.rename(src + " (unplugged)", src)
        assert audiobooks.transcript_use(_record(store, item)) == audiobooks.TIMING
        assert str(store.meta()[ls.TRANSCRIPT_RULE]) == str(audiobooks.FOUND_RULE)


@pytest.mark.parametrize("held", ("nothing", "episodes"))
@pytest.mark.parametrize("language", ("ja", "zh"))
def test_a_library_without_audiobooks_says_the_rule_once_and_writes_nothing_else(language, held):
    """A library with no audiobook (its source folder empty, or episodes only) as the update reached it: its first look
    under this rule writes the meta and nothing else — no version moves, no record written — and the look after it
    writes nothing at all."""
    store, _data_dir = _empty(language)
    src = _drive("driveA")
    if held == "episodes":
        show = _SHOWS[language][0]
        for n in (1, 2):
            _write(os.path.join(src, show, f"ep{n:02d}.srt"), _text(language, n))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert str(store.meta()[ls.TRANSCRIPT_RULE]) == str(audiobooks.FOUND_RULE)
        with store._writing():
            store.conn.execute("DELETE FROM meta WHERE key = ?", (ls.TRANSCRIPT_RULE,))
        versions = store.versions()
        _result, sql = _traced(store, language, root)
        writes = [s for s in sql if s.lstrip().split(None, 1)[0].upper() in ("INSERT", "UPDATE", "DELETE", "REPLACE")]
        assert writes and all("INTO meta" in s for s in writes), writes
        assert store.versions() == versions
        assert str(store.meta()[ls.TRANSCRIPT_RULE]) == str(audiobooks.FOUND_RULE)
        changes = store.conn.total_changes
        _look(store, language, root)
        assert store.conn.total_changes == changes and store.versions() == versions


def test_a_later_rule_re_arms_the_first_look_with_no_new_code(monkeypatch):
    """A FOUND_RULE 3 one day is the same story with nothing added: every verdict by rule 2 that found a transcript
    wanting reads UNCHECKED under it, and the library's first look under rule 3 — a quick one — judges each again by
    rule 3, once (a transcript found its book's stays its book's: the longest run is never shorter)."""
    store, _data_dir, src, _srt_path = _paired("zh", SAIYU, _other_lines("zh"))
    with store:
        root = store.add_source(src)
        _look(store, "zh", root, first=True)
        item = _audio_item(store, SAIYU)
        assert _record(store, item)["transcript"]["found"]["rule"] == 2
        monkeypatch.setattr(audiobooks, "FOUND_RULE", 3)
        assert audiobooks.transcript_use(_record(store, item)) == audiobooks.UNCHECKED
        _look(store, "zh", root)
        rec = _record(store, item)
        assert rec["transcript"]["found"]["rule"] == 3 and audiobooks.transcript_use(rec) == audiobooks.OTHER
        assert str(store.meta()[ls.TRANSCRIPT_RULE]) == "3" and _transcript_asks(store) == [item]


def _story(language, name):
    folder = {"ja": "samples/ja", "zh": "samples/zh"}[language]
    for tier in ("HighPriority", "LowPriority"):
        path = os.path.join(os.path.dirname(RESOURCES), os.pardir, folder, tier, name)
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig") as f:
                return f.read()
    raise FileNotFoundError(name)


def _story_cues(text):
    import re
    return [x for x in (audiobooks.clean_text(s) for s in re.split(r"(?<=[。！？!?])|\n", text))
            if len(x) >= audiobooks.CUE_MIN]


def test_a_cue_whose_opening_is_common_still_finds_its_late_place():
    """The lead's check on #432: a cue's every place is checked whole — never only the first places its opening sits
    at — so a line starting like a hundred earlier ones still finds its one place late in the book."""
    text = _story("ja", "蜘蛛の糸（芥川龍之介）.txt")
    cues = _story_cues(text)
    last = cues[-1]
    filler = audiobooks.clean_text(_story("ja", "ごん狐（新美南吉）.txt"))[:40]
    book = audiobooks.clean_text(text.replace(text.rstrip()[-len(text.rstrip()) // 3:], ""))   # its first two thirds
    book = "".join(last[:audiobooks.CUE_MIN] + filler for _ in range(300)) + book + last         # 300 alike openings
    assert book.count(last) == 1 and book.count(last[:audiobooks.CUE_MIN]) > 300
    head = [c for c in cues[:-1] if c in book]
    assert audiobooks.found_in_order(head + [last], book) == 1.0


def test_a_stock_line_all_through_the_book_is_out_of_the_run_and_the_count():
    """A line the book holds more than FOUND_PLACES times tells neither the order nor the book: never weighed — the
    right book's share is not lowered by it, a wrong book's never raised; only such lines: no share (None)."""
    cues = _story_cues(_story("ja", "蜘蛛の糸（芥川龍之介）.txt"))
    stock = audiobooks.clean_text(_story("ja", "ごん狐（新美南吉）.txt"))[:20]
    book = (stock * (audiobooks.FOUND_PLACES + 1)) + "".join(cues)
    assert audiobooks.found_in_order([stock] + cues + [stock], book) == 1.0
    assert audiobooks.found_in_order([stock, stock], book) is None
    other = _story_cues(_story("ja", "注文の多い料理店（宮沢賢治）.txt"))
    assert audiobooks.found_in_order([stock] * 50 + other, book) < 0.1


@pytest.mark.parametrize("language,stories", (
    ("ja", ("蜘蛛の糸（芥川龍之介）.txt", "注文の多い料理店（宮沢賢治）.txt", "ごん狐（新美南吉）.txt")),
    ("zh", ("故乡（鲁迅）.txt", "孔乙己（鲁迅）.txt", "从百草园到三味书屋（鲁迅）.txt")),     # one author: alike lines
))
def test_another_books_transcript_still_scores_low_under_the_longest_run(language, stories):
    """The other side of #432's rule: the longest run must never let chance matches of short common lines chain into
    a wrong book's transcript passing — each real story's cues against every other story (one author's, in zh) stay far
    under CONTENT_SHARE; against its own book, all of them."""
    for t in stories:
        cues = _story_cues(_story(language, t))
        for b in stories:
            share = audiobooks.found_in_order(cues, audiobooks.clean_text(_story(language, b)))
            assert share == 1.0 if t == b else share < 0.1, (t, b, share)
