"""F13 (3.0.1): a look that takes in one new file builds no whole-library table in Python. Four passes had come back
into it (every origin's show folder key for LM1b's `_show_origins`, Moves M3's evidence of every origin's bytes, K5's
five book tables at once, the emptied-folder check reading every copy's path), and a window's move saved meanwhile
took up to 0.26 s at 20k origins instead of 50 ms (`test_a_window_move_during_a_look_that_finds_one_new_file_saves_
within_the_budget`, timed run). Now each table is grouped only when first asked, a show's origins and a size's evidence
are worked out only for the show and the sizes asked, and the emptied check reads its top folders through SQLite.
The proof that nothing a look decides moved: every table the look reads equals the one the old whole-library build
makes (that build is kept here as the oracle), on a library with shows, videos, a waiting video, a book and a moved
show; the folder-key memo equals `folder_key_of` on every kind of path; the emptied check's SQL reads the same top
folders as the Python rule did. The scope itself is checked by counts, never by time (it holds on any runner)."""
import os
import shutil
import sys

import pytest

from app import library_store as ls
from app import sources
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import (_drive, _empty, _epub, _fresh_module_state, _look, _seed, _settle,  # noqa: F401
                                     _text, _video, _write)
from tests.test_sources_k5_tables import _chapters


# --- the oracle: the tables as the whole-library build made them (3.0-dev 8612646f) --------------------------------- #

def _old_members(origins):
    """K5's `_members` as it was: all five tables over every origin, `folder_key_of` per origin."""
    members = {t: {} for t in ("sha", "book", "item", "head", "show")}
    for k, o in origins.items():
        head, _sep, number = k.rpartition("#")
        out = [("item", o.item_id), ("show", ls.folder_key_of(o.rel_path or ""))]
        if head:
            out.append(("head", head))
        if head and number.isdigit() and ls._EPUB_PART.search(str(o.origin or "")):
            out.append(("book", head))
        own, _sep, n = (o.origin or "").rpartition("#")
        if own and n.isdigit() and o.sha256:
            out.append(("sha", o.sha256))
        for t, b in out:
            members[t].setdefault(b, set()).add(k)
    return members


def _old_show_origins(origins):
    """`_show_origins`' table as it was: every show's origins, in the look's key order."""
    out = {}
    for k, o in origins.items():
        out.setdefault(ls.folder_key_of(o.rel_path or ""), []).append(o)
    return out


def _old_evidence(origins):
    """D3's `_evidence` as it was: ({size: {sha256: shows}}, {video size: {video key: shows}})."""
    by_text, by_video = {}, {}
    for k, o in origins.items():
        show = sources._library_show(o.rel_path)
        if show is None or "#" in k:
            continue
        if isinstance(o.size, int) and o.sha256 and ls.is_content_name(os.path.basename(k)):
            by_text.setdefault(o.size, {}).setdefault(o.sha256, set()).add(show)
        if isinstance(o.video_size, int) and o.video_key:
            by_video.setdefault(o.video_size, {}).setdefault(o.video_key, set()).add(show)
    return by_text, by_video


def _caught(monkeypatch):
    """Each look's `_Look`, kept after it ran (its tables as the look left them)."""
    looks = []
    real_run = sources._Look.run

    def run(self):
        looks.append(self)
        return real_run(self)
    monkeypatch.setattr(sources._Look, "run", run)
    return looks


def _same_as_the_old_build(look):
    """Every table the look can read equals the whole-library build's, bucket by bucket and size by size."""
    assert look.origins, "the look read no origin"
    old = _old_members(look.origins)
    for t in ("sha", "book", "item", "head", "show"):
        assert look._members(t) == old[t], t
    shows = _old_show_origins(look.origins)
    for fk in set(shows) | {"", "no such show", None}:
        assert list(look._show_origins(fk)) == shows.get(fk, []), fk
    by_text, by_video = _old_evidence(look.origins)
    sizes = {o.size for o in look.origins.values() if isinstance(o.size, int)} | {-1, 0, 123456789}
    vsizes = {o.video_size for o in look.origins.values() if isinstance(o.video_size, int)} | {-1, 0, 123456789}
    for size in sizes:
        assert look._evidence("text", size) == by_text.get(size, {}), size
    for size in vsizes:
        assert look._evidence("video", size) == by_video.get(size, {}), size
    return by_text, by_video


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_table_a_look_reads_equals_the_whole_library_build_on_a_mixed_library(language, monkeypatch):
    """Why: a show's origins decide its episodes and versions (S7, LM1b), the evidence decides which show a moved
    folder joins (D3, FIX1) and the book tables decide a book's editions (K5, LM3); worked out per show and per size
    now, each must be exactly what the whole-library build gave, or a file could join the wrong show or be taken twice.
    The library: two shows with subtitles (one with its videos), a video with no subtitle yet (a waiting item), a book
    of three chapters, a loose file at the top; then one show's folder copied elsewhere with one new episode beside
    its old ones (the moved-show vote reads the evidence), then a full look."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    a, b = ("月影の旅人", "星の歌") if language == "ja" else ("夜市小记", "百草园")
    for n in (1, 2, 3):
        _write(os.path.join(src, a, f"[Grp] {a} - {n:02d}.srt"), _text(language, n))
        _video(os.path.join(src, a, f"[Grp] {a} - {n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 " + f"{a}{n}".encode())
    for n in (1, 2):
        _write(os.path.join(src, b, f"{b} 第{n}話.srt"), _text(language, n + 5))
    _video(os.path.join(src, "Only video", "Only video - 01.mkv"), body=b"\x1a\x45\xdf\xa3 waiting")
    _epub(os.path.join(src, "Books", "風の便り.epub"), _chapters(language, 1))
    _write(os.path.join(src, f"{a} - 09.srt"), _text(language, 9))
    _settle(src)
    looks = _caught(monkeypatch)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] > 0
        moved = os.path.join(src, "NAS", "2024 Fall", a)
        shutil.copytree(os.path.join(src, a), moved)
        _write(os.path.join(moved, f"[Grp] {a} - 04.srt"), _text(language, 4))
        _settle(src)
        assert _look(store, language, root)["added"] >= 1
        by_text, _by_video = _same_as_the_old_build(looks[-1])
        assert by_text, "the library holds no text evidence: the check proves nothing"
        assert looks[-1].evidence is not None, "the moved show's vote never read the evidence"
        _look(store, language, root, full=True)
        _same_as_the_old_build(looks[-1])


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_look_that_takes_in_one_episode_groups_only_its_shows_and_files_no_evidence(language, monkeypatch):
    """Why (F13): the look that takes in one new episode of a show already in must not build any whole-library table:
    no book table, the show folder keys worked out once per folder (never once per origin), and the evidence (the new
    file's folder name has no items of its own) for the new file's size alone. Counted, not timed: 600 origins in 12
    shows (the timed test's library, smaller), one new episode."""
    store, data_dir = _empty(language)
    src = _drive("driveA")
    looks = _caught(monkeypatch)
    keyed, real_key = [], ls.folder_key_of

    def folder_key_of(rel):                                  # counted when the look asks (never the store's own)
        if sys._getframe(1).f_code.co_filename.endswith("sources.py"):
            keyed.append(rel)
        return real_key(rel)
    with store:
        root = store.add_source(src)
        _seed(store, root, data_dir, language, src, 600, name="[Grp] {show} - {e:02d} (1080p)." + language + ".srt")
        show = "既存0003"
        _write(os.path.join(src, "seeded", show, f"[Grp] {show} - 77 (1080p).{language}.srt"), _text(language, 77))
        _settle(src)
        monkeypatch.setattr(ls, "folder_key_of", folder_key_of)
        assert _look(store, language, root)["added"] == 1
    look = looks[-1]
    assert 0 < len(keyed) < 40, f"{len(keyed)} folder keys worked out for 600 origins in 12 folders"
    assert len(look.origins) >= 600
    assert set(look.members) == {"show"}, "a book table or the item table was grouped"
    assert look.books_in is None and look.book_origins is None and look.by_item is None
    assert len(look.folder_keys) <= 20, f"a folder key per origin ({len(look.folder_keys)}), not per folder"
    assert len(look.shows_asked) <= 3
    filed, worked_out = look.evidence
    assert len(worked_out) == 1, "evidence worked out for more sizes than the new file's"


def _origin(item_id, origin, rel, size=None, sha=None, video_size=None, video_key=None, version=None):
    return ls.Origin(item_id, 1, origin, size, 1, sha, rel, "available", None, version, None, video_size, video_key)


def _bare_look(origins):
    look = sources._Look.__new__(sources._Look)
    look.origins, look.members, look.evidence, look.by_show, look.shows_asked = origins, None, None, None, set()
    look.books_in = look.book_origins = look.by_item = None
    return look


def test_the_tables_of_records_of_every_kind_equal_the_whole_library_build():
    """Why: the records a look reads are not all one show's tidy episodes — one show's copies in a 3.0 `Library`
    folder and in a 2.x tier folder (one folder key, two folders), a folder written in two cases, a book's parts
    (`<epub>#<n>`: never evidence, filed by their book and bytes), a version, a loose copy, a record with no copy path,
    a text that is no content (an `.epub` origin), records with no size, no hash or no video key, two shows' texts of
    one size and hash — each table and each size's evidence must still be the whole-library build's."""
    d = os.path.join(os.sep, "src")
    origins = {}
    for k, o in [
            ("/src/a/01.srt", _origin(1, f"{d}/a/01.srt", "Library/星の歌/01.srt", 50, "s1", 900, "v1")),
            ("/src/a/02.srt", _origin(2, f"{d}/a/02.srt", "Library/星の歌/02.srt", 50, "s2")),
            ("/src/a/02 v2.srt", _origin(2, f"{d}/a/02 v2.srt", "Library/星の歌/02.srt", 60, "s3", version=True)),
            ("/src/old/03.srt", _origin(3, f"{d}/old/03.srt", "HighPriority/星の歌/03.srt", 50, "s1", 900, "v2")),
            ("/src/b/01.srt", _origin(4, f"{d}/b/01.srt", "library/Show B/01.srt", 50, "s1", 900, "v1")),
            ("/src/b/02.srt", _origin(5, f"{d}/b/02.srt", "LIBRARY/show b/02.srt", 70, None, None, "v3")),
            ("/src/b/03.srt", _origin(6, f"{d}/b/03.srt", "Library/Show B/03.srt", "70", "s4", "900", "v4")),
            ("/src/loose.srt", _origin(7, f"{d}/loose.srt", "loose.srt", 50, "s1", 900, "v5")),
            ("/src/none.srt", _origin(8, f"{d}/none.srt", None, 50, "s1")),
            ("/src/book.epub", _origin(9, f"{d}/book.epub", "Library/本/book.epub", 50, "s1")),
            ("/src/本.epub#1", _origin(10, f"{d}/本.epub#1", "Library/本/本 1.txt", 50, "e1")),
            ("/src/本.epub#2", _origin(11, f"{d}/本.epub#2", "Library/本/本 2.txt", 80, "e1", 900, "v6")),
            ("/src/x#y", _origin(12, f"{d}/x#y", "Library/X/x.srt", 50, "s1")),
            ("/src/s1/01.srt", _origin(13, f"{d}/s1/01.srt", "Library/Show/Season 1/01.srt", 50, "s1", 900, "v1")),
            ("/src/hato.srt", _origin(14, f"{d}/hato.srt", f"{ls.HATO_FOLDER}/hato.srt", 50, "s5"))]:
        origins[k] = o
    look = _bare_look(origins)
    old = _old_members(origins)
    for t in ("show", "sha", "book", "item", "head"):        # in an order no look follows: each table on its own
        assert look._members(t) == old[t], t
    assert look._members("show") is look._members("show")   # grouped once
    shows = _old_show_origins(origins)
    assert len(shows[ls.folder_key_of("Library/星の歌/x")]) == 4 and len(shows[ls.folder_key_of("Library/Show B/x")]) == 3
    for fk in list(shows) + ["missing"]:
        assert list(look._show_origins(fk)) == shows.get(fk, []), fk
    look = _bare_look(origins)                               # evidence first, before any table
    by_text, by_video = _old_evidence(origins)
    assert by_text[50]["s1"] == {"星の歌", "Show B", "Show/Season 1"} == by_video[900]["v1"]
    assert set(by_video[900]) == {"v1"}                      # a tier copy's, a loose one's, a part's: no show's
    for size in (50, 60, 70, 80, "70", None, 900, 1):
        assert look._evidence("text", size) == by_text.get(size, {}), size
        assert look._evidence("video", size) == by_video.get(size, {}), size
        assert look._evidence("text", size) == by_text.get(size, {}), size     # worked out once, the same again


def test_a_refresh_keeps_the_shows_asked_and_leaves_the_tables_not_grouped_yet_to_be_grouped_as_they_are():
    """Why: a book's take-in reads its items' records again (`_refresh`, K5); a show's origins asked before it must
    follow (rebuilt in place), a show not asked yet and a table not grouped yet must come out, when first asked, as the
    records are now — never as they were, never missing the item that moved into it."""
    from types import SimpleNamespace
    d = os.path.join(os.sep, "src")
    origins = {"/src/a/01.srt": _origin(1, f"{d}/a/01.srt", "Library/A/01.srt", 50, "s1"),
               "/src/a/02.srt": _origin(2, f"{d}/a/02.srt", "Library/A/02.srt", 50, "s2"),
               "/src/b/01.srt": _origin(3, f"{d}/b/01.srt", "Library/B/01.srt", 50, "s3"),
               "/src/本.epub#1": _origin(4, f"{d}/本.epub#1", "Library/本/1.txt", 50, "e1")}
    look = _bare_look(dict(origins))
    look.book_keys = look.editions = None
    a, b, book = (ls.folder_key_of(f"Library/{x}/x") for x in ("A", "B", "本"))
    assert [o.item_id for o in look._show_origins(a)] == [1, 2]
    look._members("item")
    now = {"/src/a/02.srt": _origin(2, f"{d}/a/02.srt", "Library/B/02.srt", 50, "s2"),     # item 2 moved to B
           "/src/本.epub#1": _origin(4, f"{d}/本.epub#1", "Library/本/1.txt", 50, "e2"),     # the book's new bytes
           "/src/本.epub#2": _origin(5, f"{d}/本.epub#2", "Library/本/2.txt", 50, "e2")}     # and a new part
    look.store = SimpleNamespace(origins=lambda items: {k: o for k, o in now.items() if o.item_id in items})
    look._refresh({2, 4}, SimpleNamespace(added=[5]))
    after = dict(origins, **now)
    assert look.origins == after
    assert set(look.members) == {"show", "item"}, "a table not grouped yet was grouped by the refresh"
    shows = _old_show_origins(after)
    assert [o.item_id for o in look._show_origins(a)] == [1]                  # asked before: followed
    for fk in (a, b, book):
        assert list(look._show_origins(fk)) == shows[fk], fk
    old = _old_members(after)
    for t in ("show", "item", "sha", "book", "head"):
        assert look._members(t) == old[t], t
    assert look._books()["e2"] == {1: (4, "Library/本/1.txt", None), 2: (5, "Library/本/2.txt", None)}


def test_the_folder_key_memo_reads_every_kind_of_path_as_folder_key_of():
    """Why: the show table files each origin under its copy's folder key, now worked out once per folder; the memo
    must give `folder_key_of`'s answer for every path a record can hold — a 3.0 `Library` copy (any case), a 2.x tier's,
    a season folder, a loose file, hato's drop, a leading `./`, a path with no folder or an empty one."""
    rels = ["Library/星の歌/x.srt", "library/星の歌/y.srt", "LIBRARY/Show/Season 1/e01.srt", "HighPriority/A/B/c.srt",
            "highpriority/A/c.srt", "LowPriority/A/c.srt", "GoalContent/A/c.srt", f"{ls.GRADUATED_FOLDER}/A/c.srt",
            f"{ls.HATO_FOLDER}/a.srt", f"{ls.HATO_FOLDER}/Sub/a.srt", "./Library/A/x.srt", "./x.srt", "./a/b.srt",
            "x.srt", "/x.srt", "", "Library/x.srt", "HighPriority/x.srt", "A/B/C/d.srt", "Ａ/ｂ.srt",
            "Library/Ｆｒｉｅｒｅｎ/1.srt", "Library/café/1.srt", "Library/café/1.srt"]
    look = sources._Look.__new__(sources._Look)
    look.members, look.origins = None, {}
    look._members("show")                                   # sets up the memo, as a look does
    for rel in rels:
        folder = rel.rpartition("/")[0]
        assert look._folder_key(folder) == ls.folder_key_of(rel), rel
        assert look._folder_key(folder) == ls.folder_key_of(rel), rel    # memo'd: the same answer again


def test_the_emptied_check_reads_the_top_folders_the_python_rule_read(monkeypatch):
    """Why: `note_emptied` now reads its top folders and its count through SQLite; they must be the ones the Python
    rule read — `_strip(rel).split('/', 1)[0]` over every item but a waiting video, an empty path left out — or a
    folder with files could be missed (a needless *Start fresh* card) or one counted twice."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("driveA")
    rels = ["Library/星の歌/x.srt", "./Library/A/x.srt", "loose.srt", "./loose2.srt", "HighPriority/b/y.srt",
            "/abs.srt", "./", "Library", "ｗｉｄｅ/z.srt", "Library/星の歌/z.srt"]
    with store:
        root = store.add_source(src)
        _seed(store, root, data_dir, language, src, len(rels) + 1, per_show=1)
        ids = [r[0] for r in store.conn.execute("SELECT id FROM items ORDER BY id")]
        with store._writing():
            for item_id, rel in zip(ids, rels):
                store.conn.execute("UPDATE items SET rel_path = ? WHERE id = ?", (rel, item_id))
            store.conn.execute("UPDATE items SET rel_path = 'Waiting/v.mkv', availability = 'waiting' WHERE id = ?",
                               (ids[-1],))
        asked = []
        monkeypatch.setattr(ls, "_holds_a_file", lambda path: asked.append(os.path.relpath(path, data_dir)) and False)
        files = store.note_emptied()
    want = {(rel[2:] if rel.startswith("./") else rel).split("/", 1)[0] for rel in rels if rel}
    assert sorted(asked) == sorted(os.path.normpath(t) if t else "." for t in want)
    assert files == len(rels)                               # every item but the waiting video
