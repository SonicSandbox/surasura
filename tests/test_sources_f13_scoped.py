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
    with store:
        root = store.add_source(src)
        _seed(store, root, data_dir, language, src, 600, name="[Grp] {show} - {e:02d} (1080p)." + language + ".srt")
        show = "既存0003"
        _write(os.path.join(src, "seeded", show, f"[Grp] {show} - 77 (1080p).{language}.srt"), _text(language, 77))
        _settle(src)
        assert _look(store, language, root)["added"] == 1
    look = looks[-1]
    assert len(look.origins) >= 600
    assert set(look.members) == {"show"}, "a book table or the item table was grouped"
    assert look.books_in is None and look.book_origins is None and look.by_item is None
    assert len(look.folder_keys) <= 20, f"a folder key per origin ({len(look.folder_keys)}), not per folder"
    assert len(look.shows_asked) <= 3
    filed, worked_out = look.evidence
    assert len(worked_out) == 1, "evidence worked out for more sizes than the new file's"


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
