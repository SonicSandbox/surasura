"""Alpha 4, Mattias's two alpha 3 reports: "point it at your library and it works it out" — every folder in a source
either arrives, waits, or says why it didn't.

- (a) Six anime folders in his source never arrived, not even as waiting. Every shape of a show folder arrives (subtitles
  in) or waits (video only, embedded subtitles, English only); the cause was a folder LINK (a junction, a symlink): a
  look never followed one and said nothing. Now a link is read as the folder it names (once a look, never a loop,
  never into Surasura's own folders), and one it can't read — a link to nothing, a Windows shortcut — is said.
- (b) A copy of a book he removed, in another folder, never arrived and nothing said: Remove keeps its bytes out (S6).
  Still kept out, now counted: the summary's `kept_out` / `kept_out_ids`, and *Bring back* (Put back) clears it.
- (c) Separate show folders are separate titles in New arrivals, never merged into one.
The REAL scan (`sources.scan`) into an empty library; nothing under a source folder written (`_look`)."""
import os
import shutil

import pytest

from app import library_store as ls
from app import sources
from app.services import source_looks
from tests.test_library_store_support import LANGUAGES, RESOURCES
from tests.test_sources_scan import _drive, _empty, _fresh_module_state, _look, _settle, _video, _write  # noqa: F401

_SUB = {"ja": ("placed_episode.srt", "library_episode.ass"), "zh": ("night_market.srt", "chinese_text_1.txt")}
_TAG = {"ja": "ja", "zh": "zh"}
ENGLISH = "1\n00:00:01,000 --> 00:00:03,000\nWhere did you put the lantern?\n\n"
BIG = b"\x1a\x45\xdf\xa3" + b"\0" * 4096            # a video's head (each one its own: a byte after it)


def _text(language, n):
    with open(os.path.join(RESOURCES, language, _SUB[language][0]), encoding="utf-8") as f:
        return f.read() + f"\n{n}\n"


def _book(language):
    path = os.path.join(os.path.dirname(RESOURCES), os.pardir, "samples", language, "HighPriority",
                        "H_priority_sample_1.txt")
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _shows(src, language):
    """His six shows' shapes (names as release groups write them) -> {folder: 'available' | 'waiting'}."""
    tag = _TAG[language]
    for e in (1, 2, 3):
        _video(os.path.join(src, "Dungeon Meshi S01", f"[SubsPlease] Dungeon Meshi - {e:02d} (1080p) [ABCD{e}234].mkv"),
               BIG + bytes([e, 1]))                                         # video only
        _video(os.path.join(src, "Kusuriya no Hitorigoto S2",
                            f"Kusuriya no Hitorigoto S2 - {e:02d} [1080p][Multiple Subtitle][ABCDEF0{e}].mkv"),
               BIG + bytes([e, 2]))                                         # subtitles inside the .mkv: none outside
        _video(os.path.join(src, "Dr. Stone Stone Wars", f"Dr. Stone Stone Wars - S02E{e:02d}.mkv"), BIG + bytes([e, 3]))
        _write(os.path.join(src, "Dr. Stone Stone Wars", f"Dr. Stone Stone Wars - S02E{e:02d}.{tag}.srt"),
               _text(language, 10 + e))                                     # our language's .srt
        _video(os.path.join(src, "Dr.Stone New World", f"[Erai-raws] Dr. Stone - New World - {e:02d} [1080p].mkv"),
               BIG + bytes([e, 4]))
        _write(os.path.join(src, "Dr.Stone New World", f"[Erai-raws] Dr. Stone - New World - {e:02d} [1080p].srt"),
               _text(language, 20 + e))                                     # named like its video, untagged
        _video(os.path.join(src, "Honzuki no Gekokujou S1", f"Honzuki no Gekokujou - {e:02d}.mkv"), BIG + bytes([e, 5]))
        _write(os.path.join(src, "Honzuki no Gekokujou S1", f"Honzuki no Gekokujou - {e:02d}.en.srt"),
               ENGLISH + str(e))                                            # English only: waits (LF-19)
        _video(os.path.join(src, "The Apothecary Diaries S01", "Season 01",
                            f"The.Apothecary.Diaries.S01E{e:02d}.1080p.CR.WEB-DL.AAC2.0.H.264-VARYG.mkv"),
               BIG + bytes([e, 6]))                                         # a season's subfolder
    return {"Dungeon Meshi S01": "waiting", "Kusuriya no Hitorigoto S2": "waiting",
            "Dr. Stone Stone Wars": "available", "Dr.Stone New World": "available",
            "Honzuki no Gekokujou S1": "waiting", "The Apothecary Diaries S01/Season 01": "waiting"}


def _age(folder, age=60):
    """The folder's own time a minute back (its listing trusted: N5) — never through a link (`_settle` walks them)."""
    import time
    t = time.time() - age
    os.utime(folder, (t, t))


def _scan(store, language, root, **kw):
    """`sources.scan` itself: a source holding a link to its own folder or to the data folder can't be walked by
    `_look`'s before/after check (its walk would follow them)."""
    return sources.scan(store, language, root, **kw)


def _by_folder(store):
    out = {}
    for folder, availability, work in store.conn.execute("SELECT parent_folder, availability, work_id FROM items"):
        out.setdefault(folder, set()).add((availability, work))
    return out


def _link(target, link):
    """A junction (Windows) — what a learner's `mklink /J` or a tool linking his shows makes — else a symlink."""
    try:
        import _winapi
        _winapi.CreateJunction(target, link)
    except (ImportError, OSError):
        os.symlink(target, link, target_is_directory=True)


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_shape_of_a_show_folder_arrives_or_waits_as_a_title_of_its_own(language):
    """Why (a, c): his six folders' shapes — video only, subtitles inside the video, our language's .srt, an untagged
    one named like its video, English only, a season's subfolder, release groups' long names — each arrive (texts in)
    or wait in New arrivals (*No subtitles yet*), each its own title: never dropped, never merged."""
    store, data_dir = _empty(language)
    src = _drive("Incoming")
    want = _shows(src, language)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        got = _by_folder(store)
    assert set(got) == set(want)
    for folder, state in want.items():
        assert {a for a, _w in got[folder]} == {state}, folder
    works = [w for rows in got.values() for _a, w in rows]
    assert len({w for w in works}) == len(want)                         # (c) one title per folder
    for folder in want:
        assert len({w for _a, w in got[folder]}) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_store_kept_from_an_earlier_start_with_a_remove_in_it_still_takes_every_show_folder(language):
    """Why (a, his second report): his "fresh start" kept the store (it lives beside the app's data, keyed by the data
    folder), with the first run's Remove of a book in it. A Remove keeps out its own files' bytes and nothing else:
    adding the folder again, every show folder still arrives or waits, and the removed book stays out, said."""
    store, data_dir = _empty(language)
    src = _drive("Incoming")
    _write(os.path.join(src, "Colorful", "Colorful.txt"), _book(language))
    with store:
        root = store.add_source(src)
        store.remove(_look(store, language, root, first=True)["ids"])
        store.stop_source(root)                                           # the old setup's source, stopped
        want = _shows(src, language)
        shutil.copytree(os.path.join(src, "Colorful"), os.path.join(src, "Colorful (again)"))
        sources._LOOKED.clear()
        again = store.add_source(src)                                     # setup picks the same folder again
        _look(store, language, again, first=True)
        got = _by_folder(store)
        row = _Summary(language).rows(store)[again]
    assert again == root
    assert set(got) == set(want)
    for folder, state in want.items():
        assert {a for a, _w in got[folder]} == {state}, folder
    assert row["kept_out"] == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_show_folders_linked_into_a_source_arrive_once_and_a_later_look_takes_nothing_twice(language):
    """Why (a, the cause): his shows lived elsewhere and were LINKED into the folder he picked; a look skipped every
    link and said nothing, so six folders never arrived. A link is now the folder it names: its shows arrive (wait),
    the next quick and full looks take nothing twice, and nothing is said about them."""
    store, data_dir = _empty(language)
    real = _drive("RealAnime")
    want = _shows(real, language)
    src = _drive("Incoming")
    for folder in ("Dungeon Meshi S01", "Dr. Stone Stone Wars", "The Apothecary Diaries S01"):
        _link(os.path.join(real, folder), os.path.join(src, folder))
    _write(os.path.join(src, "Colorful", "Colorful.txt"), _book(language))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        got = _by_folder(store)
        assert set(got) == {"Dungeon Meshi S01", "Dr. Stone Stone Wars", "The Apothecary Diaries S01/Season 01",
                            "Colorful"}
        assert {a for a, _w in got["Dungeon Meshi S01"]} == {want["Dungeon Meshi S01"]}
        n = store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        sources._LOOKED.clear()
        assert _look(store, language, root)["added"] == 0                # a quick look (the cache's subfolders)
        assert _look(store, language, root, full=True)["added"] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == n
        said = sources.notes(language, store).get(root) or {"not_read": [], "kept_out": {}}
    assert said["not_read"] == [] and said["kept_out"] == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_link_that_loops_or_names_a_folder_read_already_is_read_once(language):
    """Why: a link must never make a look endless (one to the folder above it) nor take a show twice (one to a
    folder another source reads): each folder is read once, where it is."""
    store, data_dir = _empty(language)
    other = _drive("Other")
    _video(os.path.join(other, "Show B", "Show B - 01.mkv"), BIG + b"b")
    src = _drive("Incoming")
    _video(os.path.join(src, "Show A", "Show A - 01.mkv"), BIG + b"a")
    _link(src, os.path.join(src, "Show A", "loop"))                       # back to the source: a loop
    _link(os.path.join(other, "Show B"), os.path.join(src, "Show B"))     # a folder another source reads
    with store:
        store.add_source(other)
        root = store.add_source(src)
        for r in (r["id"] for r in store.sources()):
            _scan(store, language, r, first=True)
        rows = store.conn.execute("SELECT parent_folder FROM items ORDER BY 1").fetchall()
        said = sources.notes(language, store).get(root) or {"not_read": []}
    assert [r[0] for r in rows] == ["Show A", "Show B"]
    assert said["not_read"] == []                                         # read where it is: nothing to say


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_folder_a_look_cannot_read_is_said_and_said_again_until_it_changes(language):
    """Why (a: every folder arrives, waits, or says why): a link to a folder that isn't there, a link into Surasura's
    own data folder (it would bring the library's copies back as new) and a Windows shortcut each say why they weren't
    read — on the first look and on every quick look after (the folder not listed again keeps its notes) — and a
    shortcut taken away is said no more."""
    store, data_dir = _empty(language)
    src = _drive("Incoming")
    _video(os.path.join(src, "Show A", "Show A - 01.mkv"), BIG + b"a")
    gone = _drive("Gone")
    _link(gone, os.path.join(src, "Gone Show"))
    shutil.rmtree(gone)
    os.makedirs(data_dir, exist_ok=True)                                  # a used library's folder is there
    _link(data_dir, os.path.join(src, "Surasura's data"))
    lnk = _write(os.path.join(src, "Kusuriya no Hitorigoto S2 - Shortcut.lnk"), "L\0\0\0")
    _age(os.path.join(src, "Show A"))
    _age(src)
    with store:
        root = store.add_source(src)
        _scan(store, language, root, first=True)
        first = sources.notes(language, store)[root]["not_read"]
        sources._LOOKED.clear()
        _scan(store, language, root)                                      # quick: nothing listed again
        again = sources.notes(language, store)[root]["not_read"]
        os.remove(lnk)
        _scan(store, language, root)                                      # the source's time moved: listed again
        after = sources.notes(language, store)[root]["not_read"]
        items = store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    whys = {os.path.basename(n["path"]): n["why"] for n in first}
    assert whys == {"Gone Show": sources.NOT_READ_LINK_GONE, "Surasura's data": sources.NOT_READ_LINK_OWN,
                    "Kusuriya no Hitorigoto S2 - Shortcut.lnk": sources.NOT_READ_SHORTCUT}
    assert again == first
    assert {os.path.basename(n["path"]) for n in after} == {"Gone Show", "Surasura's data"}
    assert items == 1                                                     # Show A alone: nothing of the data folder


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_followed_link_whose_folder_goes_is_said_on_the_next_quick_look_and_read_again_when_it_is_back(language):
    """Why (review, KURA-A4C baseline 1): a target taken away (a drive unplugged) changes no time of the folder the
    link sits in, so a quick look trusting that folder's listing would skip the link in silence. A folder holding a
    link is listed again every look: the link is said while its folder is gone, and read again once it is back."""
    store, data_dir = _empty(language)
    real = _drive("RealAnime")
    _video(os.path.join(real, "Dungeon Meshi S01", "Dungeon Meshi - 01.mkv"), BIG + b"d")
    src = _drive("Incoming")
    _link(os.path.join(real, "Dungeon Meshi S01"), os.path.join(src, "Dungeon Meshi S01"))
    _video(os.path.join(src, "Show A", "Show A - 01.mkv"), BIG + b"a")
    _age(os.path.join(src, "Show A"))
    _age(src)
    with store:
        root = store.add_source(src)
        _scan(store, language, root, first=True)
        assert sources.notes(language, store).get(root, {"not_read": []})["not_read"] == []
        away = real + " (unplugged)"
        os.rename(real, away)
        _scan(store, language, root)                                      # a quick look: nothing's time moved
        gone = sources.notes(language, store)[root]["not_read"]
        os.rename(away, real)
        _scan(store, language, root)                                      # quick again: back, read, nothing said
        back = sources.notes(language, store).get(root, {"not_read": []})["not_read"]
        items = store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    assert [(os.path.basename(n["path"]), n["why"]) for n in gone] == [("Dungeon Meshi S01",
                                                                         sources.NOT_READ_LINK_GONE)]
    assert back == [] and items == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_symlink_to_nothing_is_said_never_dropped_silently(language):
    """Why (a): a symlink whose folder was taken away (a drive unplugged, a folder renamed) can't say it is a folder:
    the look says it links to a folder that isn't there instead of passing over it in silence."""
    store, data_dir = _empty(language)
    src = _drive("Incoming")
    _video(os.path.join(src, "Show A", "Show A - 01.mkv"), BIG + b"a")
    try:
        os.symlink(os.path.join(_drive("Unplugged"), "Dungeon Meshi S01"), os.path.join(src, "Dungeon Meshi S01"),
                   target_is_directory=True)
    except OSError:
        pytest.skip("this Windows account can't make a symlink (no Developer Mode)")
    with store:
        root = store.add_source(src)
        _scan(store, language, root, first=True)
        said = sources.notes(language, store)[root]["not_read"]
    assert [(os.path.basename(n["path"]), n["why"]) for n in said] == [("Dungeon Meshi S01",
                                                                          sources.NOT_READ_LINK_GONE)]


class _Summary:
    """The looks' summary half (`SourceLooks._notes`) alone, on this store."""
    def __init__(self, language):
        self.language = language

    def rows(self, store):
        rows = [dict(r) for r in store.sources()]
        source_looks.SourceLooks._notes(self, store, rows)
        return {r["id"]: r for r in rows}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_of_a_removed_book_in_another_folder_is_counted_and_bring_back_lets_it_in(language):
    """Why (b): he removed a book, then copied its folder into his source; Remove keeps its bytes out (S6), so the copy
    never arrived and nothing said. It still stays out — now counted on its source's row (`kept_out`, with the
    Remove's trash ids), the removed original's own path never counted (the Removed list holds it) — and *Bring back*
    (Put back of those ids) brings the book back and the count goes."""
    store, data_dir = _empty(language)
    first = _drive("Elsewhere")
    _write(os.path.join(first, "Colorful", "Colorful.txt"), _book(language))
    src = _drive("Incoming")
    with store:
        old = store.add_source(first)
        ids = _look(store, language, old, first=True)["ids"]
        removed = store.remove(ids)
        root = store.add_source(src)
        assert _Summary(language).rows(store)[old]["kept_out"] == 0      # its own original: not counted
        shutil.copytree(os.path.join(first, "Colorful"), os.path.join(src, "Colorful (copy)"))
        _look(store, language, root, full=True)
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0     # kept out (S6)
        row = _Summary(language).rows(store)[root]
        assert row["kept_out"] == 1 and row["kept_out_ids"] == sorted(removed.trash_ids)
        assert row["not_read"] == []
        sources._LOOKED.clear()
        _look(store, language, root)                                      # a quick look: still said
        assert _Summary(language).rows(store)[root]["kept_out"] == 1
        store.restore(row["kept_out_ids"])                                # *Bring back*
        assert store.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == len(ids)
        after = _Summary(language).rows(store)[root]
    assert after["kept_out"] == 0 and after["kept_out_ids"] == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_removed_waiting_video_copied_elsewhere_is_counted_by_its_video(language):
    """Why (b, video): a show's video he removed, found again in another folder, is kept out by its video's key —
    counted the same way, so it never vanishes silently."""
    store, data_dir = _empty(language)
    src = _drive("Incoming")
    _video(os.path.join(src, "Show A", "Show A - 01.mkv"), BIG + b"v")
    with store:
        root = store.add_source(src)
        removed = store.remove(_look(store, language, root, first=True)["ids"])
        _video(os.path.join(src, "Show A again", "Show A - 01.mkv"), BIG + b"v")
        _look(store, language, root, full=True)
        row = _Summary(language).rows(store)[root]
    assert row["kept_out"] == 1 and row["kept_out_ids"] == sorted(removed.trash_ids)
