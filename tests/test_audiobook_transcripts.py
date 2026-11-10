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

Why these matter: Sonic's own vol 1 (an M4B, its `.srt` and its EPUB side by side) counted its words twice — the
book's and the transcript's. Every look here runs on real files built on disk (an EPUB of real text, M4Bs and MP3s
with real tags and lengths, transcripts of real sentences) and proves the source folders are never written to.
"""
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
from tests.test_sources_scan import _drive, _empty, _look

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


def test_the_in_order_share_is_the_plain_scans_on_real_text():
    """The index (`found_in_order`) finds exactly what a plain scan in order finds — the book's own lines shuffled,
    repeated and mixed with another text's."""
    import random
    book = audiobooks.clean_text("".join(_lines("ja")) * 3)
    lines = [audiobooks.clean_text(x) for x in _lines("ja") + _other_lines("ja")]
    lines = [x for x in lines if len(x) >= audiobooks.CUE_MIN]
    random.Random(7).shuffle(lines)

    def plain(cues, text):
        at, n = 0, 0
        for c in cues:
            i = text.find(c, at)
            if i >= 0:
                n, at = n + 1, i + len(c)
        return n / len(cues)
    assert audiobooks.found_in_order(lines, book) == plain(lines, book) and 0 < plain(lines, book) < 1


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
    found = lambda share, mark="s1": dict(said, found={"book": mark, "share": share})  # noqa: E731
    assert audiobooks.transcript_use({"transcript": found(0.6), "book": book}) == audiobooks.TIMING
    assert audiobooks.transcript_use({"transcript": found(0.59), "book": book}) == audiobooks.OTHER
    assert audiobooks.transcript_use({"transcript": found(None), "book": book}) == audiobooks.OTHER
    assert audiobooks.transcript_use({"transcript": found(1.0, "s2"), "book": book}) == audiobooks.UNCHECKED
