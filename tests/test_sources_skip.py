"""3.0's Sources, K6: a folder the learner never wants read (*Never read this folder*), and a text file holding none of
the library's language (a backup's skin config, `skin.txt`) never taken as an episode.

A library folder can hold more than shows: here a console memory card's backup, whose loader keeps its skins as text
files — a look took them in as shows. What a wrong answer would cost a learner:
  * a skipped folder still listed, or its files coming back on the next look (the skip undone behind the learner's back);
  * a skip that throws away an episode that also lives elsewhere, or touches a file in the learner's own folders;
  * an Undo that leaves the folder skipped, or a *Read again* that brings nothing back (or brings it back twice);
  * a config file with no Japanese in it filling the list with junk shows — or a real Japanese subtitle refused.

The tree (`Old Backups/Console Card/loader/skins/blue/skin.txt`, made-up names) sits beside a real show folder on a temp
"drive" under the test's root; every look goes through `_look`, which proves nothing under a source folder was written.
The text is real Japanese / Chinese from tests/Test Resources/; the skin file is a loader's ASCII config.
"""
import os
import time

import pytest

from app import library_store as ls
from app import sources
from tests.test_library_store_support import LANGUAGES
from tests.test_sources_scan import (_ScandirSpy, _cache, _current, _drive, _empty, _fresh_module_state,  # noqa: F401
                                     _items, _library_files, _look, _settle, _SHOWS, _spy_reads, _text, _tree, _video, _write)

CARD = os.path.join("Old Backups", "Console Card")
BLUE = os.path.join(CARD, "loader", "skins", "blue")
# a loader's skin file: key = value lines, no word of any language we read
SKIN = ("# skin: blue\n"
        "skin_previews = 1\nlayout = large3\nwcovers = 0\ncover_style = standard\n"
        "color_header = #FFFFFF\ncolor_selected_fg = #0A0A0A\ncolor_selected_bg = #4FB7E8\n"
        "covers_size = 160, 224\nhide_header = 0\nhide_hddinfo = 1\nhide_footer = 0\n")


SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


def _sample(language):
    """A real novel-length text (the app's own samples): over BOOK_MIN_CHARS characters of the language's script."""
    with open(os.path.join(SAMPLES, language, "HighPriority", "H_priority_sample_1.txt"), encoding="utf-8-sig") as f:
        return f.read()


def _card_and_show(language, src, card_text=True):
    """The show folder (two episodes) and, under the card backup, two files: one per folder of the loader's own.
    `card_text`: real text there, a book's worth (so a look takes it in as items — the skip's case); False: the
    loader's ASCII config."""
    show = _SHOWS[language][0]
    eps = [_write(os.path.join(src, show, f"{show} - {n:02d}.srt"), _text(language, n)) for n in (1, 2)]
    body = (lambda n: _sample(language) + f"\n{n} skin\n") if card_text else (lambda n: SKIN)
    card = [_write(os.path.join(src, BLUE, "skin.txt"), body(7)),
            _write(os.path.join(src, CARD, "loader", "skin", "skin.txt"), body(8))]
    return eps, card


def _rels(store):
    return sorted(r[0] for r in store.conn.execute("SELECT rel_path FROM items"))


def _folder_rows(store):
    return store.conn.execute("SELECT id, root_id, pattern, note FROM exclusions WHERE kind = 'folder'").fetchall()


# --- 1 · the store: skip a folder, Undo, read it again ------------------------------------------------------------ #

@pytest.mark.parametrize("language", LANGUAGES)
def test_skipping_a_folder_removes_its_items_in_one_command_and_no_look_lists_it_again(language, monkeypatch):
    """*Never read this folder* on "Console Card": its two items leave (to the store's trash: Put back works), the
    show beside it stays; the next looks — a quick one and a Refresh — never list the folder or anything under it, and
    its files are no longer counted as found."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    eps, card = _card_and_show(language, src)
    with store:
        root = store.add_source(src)
        first = _look(store, language, root, first=True)
        assert first["added"] == 4 and first["found"] == 4
        show_rels = [r for r in _rels(store) if "Console Card" not in r]
        before = _tree(src)
        change = store.skip_folder(os.path.join(src, CARD))
        assert change is not None and len(change.trash_ids) == 2
        assert _rels(store) == show_rels                                         # the show's two episodes stay
        assert [r["rel_path"] for r in store.trash_rows(change.trash_ids)] and \
            all("Console Card" in r["rel_path"] for r in store.trash_rows(change.trash_ids))
        (fid, rid, pattern, _note), = _folder_rows(store)
        assert rid == root and pattern == ls.path_key(ls.folder_path(os.path.join(src, CARD)))
        marked = store.conn.execute("SELECT note FROM exclusions WHERE kind = 'removed'").fetchall()
        assert len(marked) == 2 and all(ls._json_dict(n)["folder"] == fid for (n,) in marked)
        assert _tree(src) == before                                              # nothing of the learner's touched
        spy = _ScandirSpy(monkeypatch)
        quick = _look(store, language, root)
        assert quick["added"] == 0
        refresh = _look(store, language, root, full=True)
        assert refresh["added"] == 0 and refresh["found"] == 2                   # the show's two, never the card's
        for folder in (CARD, os.path.join(CARD, "loader"), BLUE, os.path.join(CARD, "loader", "skin")):
            assert not spy.saw(os.path.join(src, folder)), folder
        assert spy.saw(src) and spy.saw(os.path.join(src, _SHOWS[language][0]))
        assert _rels(store) == show_rels


@pytest.mark.parametrize("language", LANGUAGES)
def test_undo_of_a_skip_puts_its_items_back_and_reads_the_folder_again(language):
    """Undo: the two items come back where they stood and the folder row goes — the next look lists the folder again
    and takes nothing twice (SRC-7)."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    _card_and_show(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        rels, current = _rels(store), _current(store)
        change = store.skip_folder(os.path.join(src, CARD))
        out = store.undo(change)
        assert out is not None and len(out.restored) == 2 and getattr(out, "folder_dropped", False)
        assert _rels(store) == rels and _current(store) == current
        assert _folder_rows(store) == []
        assert store.excluded() == {}                                            # their 'removed' rows went too
        again = _look(store, language, root, full=True)
        assert again["added"] == 0 and again["found"] == 4 and _rels(store) == rels


def test_undo_of_a_skip_that_removed_nothing_still_drops_the_folder_row():
    """A folder with nothing of the library in it yet (skipped before its files were read): Undo drops the row."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    os.makedirs(os.path.join(src, CARD))
    with store:
        store.add_source(src)
        change = store.skip_folder(os.path.join(src, CARD))
        assert change is not None and change.trash_ids == [] and len(_folder_rows(store)) == 1
        out = store.undo(change)
        assert out is not None and getattr(out, "folder_dropped", False) and _folder_rows(store) == []


def test_undo_of_a_skip_read_again_meanwhile_changes_nothing():
    """*Read again* came first (its files may be back as new items): the skip's Undo writes nothing — never a second
    copy of an episode put back over the ones read again."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    _card_and_show(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        change = store.skip_folder(os.path.join(src, CARD))
        assert store.read_folder_again(change.folder)
        _look(store, language, root)
        rels = _rels(store)
        out = store.undo(change)
        assert out is None or not out.restored
        assert _rels(store) == rels and _folder_rows(store) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_read_again_brings_the_folders_files_back_once_on_the_next_quick_look(language):
    """*Read again*: the folder row and the 'removed' rows the skip wrote go (a Remove of the learner's own stays); the
    next look — a quick one: the folder-time cache must not hide it — copies its files back, as shows never shown
    (New arrivals, SRC-2), and a look after that adds nothing (SRC-7)."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    eps, card = _card_and_show(language, src)
    with store:
        root = store.add_source(src)
        ids = _look(store, language, root, first=True)["ids"]
        own = next(i for i in ids if store.item(i)["rel_path"].endswith(" - 02.srt"))
        store.remove([own])                                                      # a Remove of the learner's: stays removed
        change = store.skip_folder(os.path.join(src, CARD))
        _look(store, language, root)                                             # a quick look meanwhile: nothing
        assert [f["path"] for f in store.skipped_folders()] == [ls.folder_path(os.path.join(src, CARD))]
        assert store.read_folder_again(change.folder) is True
        assert store.skipped_folders() == [] and list(store.excluded()) == [ls.origin_key(eps[1])[4:]]
        back = _look(store, language, root)                                      # quick: not a Refresh
        assert back["added"] == 2
        assert sorted(store.item(i)["rel_path"].rsplit("/", 1)[0] for i in back["ids"]) == sorted(
            "Library/" + p.replace(os.sep, "/") for p in (BLUE, os.path.join(CARD, "loader", "skin")))
        assert all(store.item(i)["tier"] == "arrivals" for i in back["ids"])
        assert _look(store, language, root, full=True)["added"] == 0
        assert store.read_folder_again(change.folder) is False                   # once


def test_an_item_with_an_origin_outside_the_skipped_folder_stays():
    """The same bytes in the card folder and in the show folder are one item with two origins: skipping the card folder
    keeps it (not every origin lies under it); an item whose every origin does leaves."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    text = _text(language, 3)
    both = [_write(os.path.join(src, show, f"{show} - 03.srt"), text), _write(os.path.join(src, BLUE, "copy.srt"),
                                                                             text)]
    only = _write(os.path.join(src, BLUE, "skin.txt"), _sample(language))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        _look(store, language, root, full=True)                                  # the twin attaches (check b)
        origins = store.origins()
        twin = origins[ls.origin_key(both[0])[4:]].item_id
        assert origins[ls.origin_key(both[1])[4:]].item_id == twin
        alone = origins[ls.origin_key(only)[4:]].item_id
        assert sorted(store.items_under(os.path.join(src, CARD))) == [alone]
        store.skip_folder(os.path.join(src, CARD))
        assert store.item(twin) is not None and store.item(alone) is None


@pytest.mark.parametrize("what", ["source", "outside", "holds-source", "skipped", "inside-skipped", "stopped"])
def test_a_skip_is_refused_for_a_source_folder_outside_every_source_holding_one_or_already_skipped(what):
    """Only a folder inside a folder being read can be skipped: the source folder itself is *Stop reading*; one outside
    every source, one holding another source, one skipped already (or inside one), one inside a stopped source — each
    refused in plain words with nothing written."""
    language = "ja"
    store, _data = _empty(language)
    src, other = _drive("Media"), _drive("Elsewhere")
    inner = os.path.join(src, "Anime", "Hoshizora Kissa S2")
    for f in (os.path.join(src, CARD), inner, os.path.join(other, "x")):
        os.makedirs(f, exist_ok=True)
    with store:
        root = store.add_source(src)
        inner_id = store.add_source(inner)
        if what in ("skipped", "inside-skipped"):
            store.skip_folder(os.path.join(src, CARD))
        if what == "stopped":
            store.stop_source(root)
        path = {"source": src, "outside": os.path.join(other, "x"), "holds-source": os.path.join(src, "Anime"),
                "skipped": os.path.join(src, CARD), "inside-skipped": os.path.join(src, BLUE),
                "stopped": os.path.join(src, CARD)}[what]
        rows = _folder_rows(store)
        reason = store.skip_refused(path)
        assert isinstance(reason, str) and reason
        with pytest.raises(ls.NotASource) as e:
            store.skip_folder(path)
        assert e.value.reason == reason
        assert _folder_rows(store) == rows
        assert store.skip_refused(os.path.join(src, "Anime", "Hoshizora Kissa S2", "extras")) is None
        store.skip_folder(os.path.join(inner, "extras"))
        assert _folder_rows(store)[-1][1] == inner_id                            # the innermost source holding it


def test_the_folders_offered_for_an_item_run_from_its_own_up_to_its_source_deepest_first():
    """⋯'s *Never read this folder* on the "blue" item: blue, skins, loader, Console Card, Old Backups —
    never the source folder (that's *Stop reading*); an item that came from no source folder: nothing offered."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    _, card = _card_and_show(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        item = store.origins()[ls.origin_key(card[0])[4:]].item_id
        assert store.skip_choices([item]) == [ls.folder_path(os.path.join(src, p)) for p in (
            BLUE, os.path.join(CARD, "loader", "skins"), os.path.join(CARD, "loader"), CARD, "Old Backups")]
        show_item = next(i for i in store.ids("now") + store.ids("soon") if i != item and
                         "Console Card" not in store.item(i)["rel_path"])
        assert store.skip_choices([show_item]) == [ls.folder_path(os.path.join(src, _SHOWS[language][0]))]
        loose = _write(os.path.join(src, "loose.srt"), _text(language, 5))
        got = _look(store, language, root, full=True)["ids"]
        assert store.origins()[ls.origin_key(loose)[4:]].item_id in got
        assert store.skip_choices(got) == []                                     # a file loose in the source folder
        assert store.skip_choices([10 ** 6]) == []


def test_a_skipped_subtitle_folder_is_never_listed_with_the_folder_above_it():
    """A `Subs` folder is listed with its show's folder (S7) — a skipped one is not."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    _video(os.path.join(src, show, f"{show} - 01.mkv"))
    _write(os.path.join(src, show, "Subs", f"{show} - 01.ja.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        store.skip_folder(os.path.join(src, show, "Subs"))
        got = _look(store, language, root, first=True)
        assert all(not store.item(i)["rel_path"].endswith(".srt") for i in got["ids"])


# --- 2 · a text holding none of our language is no episode -------------------------------------------------------- #

@pytest.mark.parametrize("language", LANGUAGES)
def test_a_skin_file_with_no_word_of_our_language_is_skipped_never_copied_and_read_once(language, monkeypatch):
    """A loader's `skin.txt` (ASCII config) beside a real show: the show comes in, the two skin files don't —
    counted as skipped, not copied, no show made of them — and an unchanged one is never read again (remembered by its
    size and time, like an EPUB with no text), not even by a Refresh or after a start; changed to real text, it is."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    eps, card = _card_and_show(language, src, card_text=False)
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert got["added"] == 2 and got["skipped"] == 2
        assert all("Console Card" not in r for r in _library_files(data_dir) + _rels(store))
        read = []
        _spy_reads(monkeypatch, read)
        sources._LOOKED.clear()                                                  # a start
        _look(store, language, root)
        again = _look(store, language, root, full=True)                         # a Refresh
        assert read == [] and again["skipped"] == 2 and again["added"] == 0
        _write(card[0], _sample(language), age=30)                                # now a book's worth: taken
        changed = _look(store, language, root, full=True)
        assert changed["added"] == 1 and [p for p in read if p.startswith(src)] == [card[0]]


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_untagged_english_subtitle_beside_a_video_is_refused(language):
    """An untagged `.srt` in English (no tag says it isn't ours) holds no Japanese / Chinese: not taken in."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][1]
    _video(os.path.join(src, show, f"{show} - 01.mkv"))
    _write(os.path.join(src, show, f"{show} - 01.srt"),
           "1\n00:00:01,000 --> 00:00:03,000\nWhere did you put the lantern?\n\n"
           "2\n00:00:04,000 --> 00:00:06,500\nBy the river, where we left it last night.\n")
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert all(not str(store.item(i)["rel_path"]).endswith(".srt") for i in got["ids"])
        assert not any(r.endswith(".srt") for r in _library_files(data_dir))


@pytest.mark.parametrize("language,encoding", [("ja", "cp932"), ("ja", "utf-8-sig"), ("ja", "utf-16"),
                                               ("zh", "gb18030"), ("zh", "utf-8")])
def test_a_text_in_its_own_encoding_still_passes(language, encoding):
    """Decoded as `path_utils.read_text` reads a file he supplies: a BOM, else UTF-8, else CP932 (ja) / GB18030 (zh)."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    path = os.path.join(src, show, f"{show} - 01.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(_sample(language))                                               # a book's worth: CP932 holds it
    t = time.time() - 60
    os.utime(path, (t, t))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1


@pytest.mark.parametrize("language,n,taken", [("ja", 19, False), ("ja", 20, True), ("zh", 19, False),
                                              ("zh", 20, True)])
def test_twenty_characters_of_our_script_make_a_text_content(language, n, taken):
    """The line: fewer than 20 characters of the language's script (ja: kana or Han; zh: Han) is not content. A
    Japanese store counts kana, so a kana-only line passes there; Chinese counts Han alone."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    unit = "あ" if language == "ja" else "字"
    _write(os.path.join(src, show, "short.srt"), "Title: " + unit * n + " (2024)\n" + "x" * 200 + "\n")
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == (1 if taken else 0)


def test_kana_alone_is_no_chinese():
    """In the Chinese store, a Japanese kana-only text is not Chinese (kana are not Han)."""
    store, data_dir = _empty("zh")
    src = _drive("Media")
    _write(os.path.join(src, "かな", "かな.txt"), "ひらがなだけのぶんしょうはちゅうごくごではありません。" * 3)
    with store:
        root = store.add_source(src)
        assert _look(store, "zh", root, first=True)["added"] == 0


# --- the window's writer: the copies to the trash, one Undo ------------------------------------------------------- #

def _writer(language):
    from app.qt.strings import MOVE_WORDS
    from app.services import moves
    from tests.test_library_store_support import roots
    from tests.test_services_moves import Heard
    data_dir, user_files_dir = roots(language)
    heard = Heard()
    w = moves.Writer(ls.StoreOpener(language, data_dir, user_files_dir, role="window"), language,
                     journal_file=moves.journal_path(language), words=MOVE_WORDS, retry=0.05, **heard.kw())
    return w.start(), heard


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_writers_skip_trashes_only_surasuras_copies_and_its_undo_brings_them_and_the_folder_back(language):
    """Through the window's writer: the card's two copies in `Library` go to the data folder's trash (Put back can
    find them), the show's stay, the learner's own folder is byte-identical; Undo brings both copies back where they
    were and the folder is read again (no folder row)."""
    from tests import services_helpers as h
    store, data_dir = _empty(language)
    src = _drive("Media")
    _card_and_show(language, src)
    root = store.add_source(src)                                                 # (closed at the end)
    _look(store, language, root, first=True)
    card_copies = [r for r in _library_files(data_dir) if "Console Card" in r]
    assert len(card_copies) == 2
    before = _tree(src)
    w, heard = _writer(language)
    try:
        w.skip_folder(os.path.join(src, CARD), label="skipped")
        assert h.until(lambda: heard.saved)
        change = heard.saved[0][0]
        assert change.kind == "remove" and change.folder
        assert [r for r in _library_files(data_dir) if "Console Card" in r] == []
        assert len(_library_files(data_dir)) == 2 and _tree(src) == before
        rows = store.trash_rows(change.trash_ids)
        assert all(os.path.isfile(os.path.join(data_dir, *r["trashed_path"].split("/"))) for r in rows)
        w.undo()
        assert h.until(lambda: heard.undone)
        assert [r for r in _library_files(data_dir) if "Console Card" in r] == card_copies
        assert store.skipped_folders() == [] and heard.notes == []
    finally:
        w.finish(time.monotonic() + 5)
        store.close()


def test_the_writers_skip_of_a_source_folder_is_refused_with_its_reason_and_moves_no_file(monkeypatch):
    from tests import services_helpers as h
    moved = []
    real = ls.trash_file
    monkeypatch.setattr(ls, "trash_file", lambda *a, **k: moved.append(a) or real(*a, **k))
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Media")
    _card_and_show(language, src)
    root = store.add_source(src)                                                 # (closed at the end)
    _look(store, language, root, first=True)
    files = _library_files(data_dir)
    w, heard = _writer(language)
    try:
        w.skip_folder(src, label="skipped")
        assert h.until(lambda: heard.notes)
        assert ls.SKIP_IS_SOURCE in heard.notes[0] and heard.saved == []
        assert _library_files(data_dir) == files and store.skipped_folders() == []
        assert moved == []                                                       # asked before any file moved
    finally:
        w.finish(time.monotonic() + 5)
        store.close()


def test_the_writers_undo_of_a_skip_that_removed_nothing_reads_the_folder_again():
    """A skip of a folder with nothing of the library in it yet: Undo still lands (never *can't undo*)."""
    from tests import services_helpers as h
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Media")
    os.makedirs(os.path.join(src, CARD))
    store.add_source(src)                                                        # (closed at the end)
    w, heard = _writer(language)
    try:
        w.skip_folder(os.path.join(src, CARD), label="skipped")
        assert h.until(lambda: heard.saved)
        assert len(store.skipped_folders()) == 1
        w.undo()
        assert h.until(lambda: heard.undone or heard.notes)
        assert heard.undone and heard.notes == [] and store.skipped_folders() == []
    finally:
        w.finish(time.monotonic() + 5)
        store.close()


def test_a_subtitle_folder_skipped_after_it_was_read_comes_back_with_read_again_on_a_quick_look():
    """A `Subs` folder is listed with its show's folder, whose time doesn't move when it is skipped or read again: a
    change to the skips lists everything once, so *Read again* brings its subtitles back on the next quick look."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    _video(os.path.join(src, show, f"{show} - 01.mkv"))
    _write(os.path.join(src, show, "Subs", f"{show} - 01.ja.srt"), _text(language, 1))
    _settle(src)                                                                 # folder times the cache trusts
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 1
        change = store.skip_folder(os.path.join(src, show, "Subs"))
        assert len(change.trash_ids) == 1
        _look(store, language, root)
        assert store.read_folder_again(change.folder)
        back = _look(store, language, root)                                      # quick: the show folder unchanged
        assert any(store.item(i)["rel_path"].endswith(".ja.srt") for i in back["ids"])


# --- K6 gaps (2026-10-21): what is the library's language, big files, books, junk in the listing ------------------- #
# What a wrong answer costs: a Chinese fansub read through the Japanese tokenizer (kanji compounds flooding the list,
# the real subtitle hidden as "another version"); a 40 MB English log or an English EPUB as a show of empty parts; a
# DRM book's mojibake as words; a Mac's `._` twins turning a folder's videos into "no subtitles yet" shows; every
# TypeScript file a video; a readme or a lyric sheet as an episode.

def _resource(language, name):
    from tests.test_library_store_support import RESOURCES
    with open(os.path.join(RESOURCES, language, name), encoding="utf-8-sig") as f:
        return f.read()


def _item_rels(store, ids):
    return sorted(store.item(i)["rel_path"] for i in ids)


def _records(store):
    import json
    return [json.loads(p) for (p,) in store.conn.execute("SELECT pairing FROM pairings")]


def test_a_chinese_fansub_beside_the_japanese_subtitle_is_passed_over_and_the_japanese_one_taken():
    """B5: `Show - 01.ass` holds a Chinese fansub (its `.简体` mark is no tag the look knows), `Show - 01.srt` the
    Japanese subtitle. Han without kana is Chinese: the `.ass` is passed over, so the `.srt` is the episode's text (it
    used to be the `.ass`, ranked first, the Japanese one hidden as another version); a Chinese novel in the same
    Japanese library is passed over too."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    _video(os.path.join(src, show, f"{show} - 01.mkv"))
    _write(os.path.join(src, show, f"{show} - 01.ass"), _resource("zh", "night_market.srt"))
    _write(os.path.join(src, show, f"{show} - 01.srt"), _text(language, 0))
    _write(os.path.join(src, "Novels", "夜市小说.txt"), _sample("zh"))
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert _item_rels(store, got["ids"]) == [f"Library/{show}/{show} - 01.srt"]
        assert _library_files(data_dir) == [f"Library/{show}/{show} - 01.srt"]


@pytest.mark.parametrize("name", ["ep01.srt", "第一巻.txt"])
def test_a_japanese_text_in_a_chinese_library_is_passed_over(name):
    """The reverse: a text holding kana (here with plenty of Han too) is Japanese, never Chinese."""
    language = "zh"
    store, data_dir = _empty(language)
    src = _drive("Media")
    body = _resource("ja", "placed_episode.srt") if name.endswith(".srt") else _sample("ja")
    _write(os.path.join(src, _SHOWS[language][0], name), body)
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert got["added"] == 0 and _library_files(data_dir) == []


@pytest.mark.parametrize("kana,taken", [(19, True), (20, False)])
def test_a_chinese_text_quoting_a_few_kana_is_still_chinese(kana, taken):
    """The zh guard's line: fewer than MIN_SCRIPT kana letters (a Japanese title quoted in a Chinese article) leave it
    Chinese; MIN_SCRIPT or more make it Japanese. ・ and ー are no kana letters (a Chinese name's separator)."""
    language = "zh"
    store, _data = _empty(language)
    src = _drive("Media")
    letters = "".join(ch for ch in _resource("ja", "placed_episode.srt") if "ぁ" <= ch <= "ヺ")[:kana]
    _write(os.path.join(src, _SHOWS[language][0], "ep01.srt"),
           _resource("zh", "night_market.srt") + "\n约翰・列侬——" + letters + "\n")
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == (1 if taken else 0)


# T2-B4 (answered 2026-10-21): a loose .txt / .md is a book's worth of text, or nothing
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_short_loose_text_is_skipped_counted_as_short_and_remembered_but_a_short_subtitle_is_taken(language,
                                                                                                    monkeypatch):
    """A `.txt` / `.md` with fewer than BOOK_MIN_CHARS characters of the language's script (a readme, a lyric, a note)
    is no content: skipped, counted under `short` too, never copied, remembered by its stats (never read again until
    it changes); the same text as a subtitle (`.srt`) is an episode — subtitles need only the presence rule."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    short = _resource(language, "context_test.txt")
    _write(os.path.join(src, show, f"{show} - 01.srt"), short)
    notes = [_write(os.path.join(src, "Notes", name), short) for name in ("memo.txt", "memo.md")]
    _write(os.path.join(src, "Books", "long.txt"), _sample(language)[1:])
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert sorted(_library_files(data_dir)) == sorted([f"Library/{show}/{show} - 01.srt", "Library/Books/long.txt"])
        assert got["short"] == 2 and got["skipped"] == 2
        read = []
        _spy_reads(monkeypatch, read)
        again = _look(store, language, root, full=True)                          # a Refresh: remembered
        assert read == [] and again["short"] == 2 and again["added"] == 0
        _write(notes[0], _sample(language), age=30)                               # now a book's worth: taken
        assert _look(store, language, root, full=True)["added"] == 1


@pytest.mark.parametrize("language,n,taken", [("ja", 999, False), ("ja", 1000, True), ("zh", 999, False),
                                              ("zh", 1000, True)])
def test_a_thousand_characters_of_our_script_make_a_loose_text_a_book(language, n, taken):
    """BOOK_MIN_CHARS' line, counted in the language's script (ja: kana + Han; zh: Han), never in bytes or lines."""
    import re
    from app.unicode_ranges import HAN, KANA_LETTERS
    script = re.compile(f"[{KANA_LETTERS}{HAN}]" if language == "ja" else f"[{HAN}]")
    text = _sample(language)
    end = [m.end() for m in script.finditer(text)][n - 1]
    store, _data = _empty(language)
    src = _drive("Media")
    _write(os.path.join(src, "Books", "part.txt"), text[:end] + "\n")
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert (got["added"], got["short"]) == ((1, 0) if taken else (0, 1))


def _big(path, head, body, size=17 << 20):
    """A text over IN_MEMORY (16 MB): `head`, then `body` repeated to `size` bytes (UTF-8), its time settled."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    unit = body.encode("utf-8")
    with open(path, "wb") as f:
        f.write(head.encode("utf-8"))
        written = len(head.encode("utf-8"))
        while written < size:
            f.write(unit)
            written += len(unit)
    t = time.time() - 60
    os.utime(path, (t, t))
    return path


def _cut_inside(raw):
    try:
        raw.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_text_over_sixteen_megabytes_is_judged_by_its_first_megabyte(language, monkeypatch):
    """B4: a big text used to be taken unchecked. Now its first megabyte — read with its hash, one pass — decides: a
    17 MB English log is passed over and remembered; a 17 MB dump of the language whose first megabyte ends inside a
    character is taken (the cut character is no damage); one whose first megabyte holds none of the language (an ASCII
    header longer than a megabyte) is passed over — the first megabyte is what is judged, nothing after it."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    log = "2026-10-21 03:14:07 INFO worker-3 flushed 4096 rows to segment 0x7f3a (took 12 ms)\n"
    text = _sample(language)
    times = sources.HEAD // len(text.encode("utf-8")) + 2
    pad = next(p for p in range(4) if _cut_inside((" " * p + text * times).encode("utf-8")[:sources.HEAD]))
    english = _big(os.path.join(src, "Logs", "corpus_dump.txt"), "", log)
    _big(os.path.join(src, "Dumps", "all_episodes.txt"), " " * pad, text)
    late = _big(os.path.join(src, "Late", "export.txt"), log * ((sources.HEAD // len(log)) + 1), text)
    assert os.path.getsize(english) > sources.IN_MEMORY
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert _library_files(data_dir) == ["Library/Dumps/all_episodes.txt"] and got["added"] == 1
        read = []
        _spy_reads(monkeypatch, read)
        again = _look(store, language, root, full=True)
        assert [p for p in read if p in (english, late)] == [] and again["added"] == 0


_ENGLISH = ("<p>The lantern had burned low by the time the ferry reached the far bank, and nobody on board seemed "
            "willing to be the first to step off into the fog.</p><p>She folded the letter twice, slipped it into her "
            "coat, and told the boatman that she would walk the rest of the way.</p>")


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_english_epub_is_passed_over_before_any_part_is_written_and_remembered(language, monkeypatch):
    """B6: the English translation beside the learner's book used to become a show of empty parts. Its text holds none
    of the language: no part written, skipped, and remembered by its stats like a book with no text — not split again
    at a start or a Refresh, until it changes."""
    from app import extract
    from tests.test_sources_scan import _epub
    store, data_dir = _empty(language)
    src = _drive("Media")
    book = _epub(os.path.join(src, "Books", "Moonshadow 1.epub"), [_ENGLISH * 8] * 3)
    opened = []
    real = extract.chunks_of
    monkeypatch.setattr(extract, "chunks_of", lambda *a, **k: opened.append(a[0]) or real(*a, **k))
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert got["added"] == 0 and got["skipped"] == 1 and _library_files(data_dir) == []
        sources._LOOKED.clear()
        _look(store, language, root)
        _look(store, language, root, full=True)
        assert opened == [book]


def _lock(path, algorithm, uri):
    """Add a `META-INF/encryption.xml` naming `uri` encrypted with `algorithm` (the text itself left readable: only
    the declaration is under test)."""
    import zipfile
    xml = ('<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
           'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
           f'<enc:EncryptionMethod Algorithm="{algorithm}"/><enc:CipherData><enc:CipherReference URI="{uri}"/>'
           '</enc:CipherData></enc:EncryptedData></encryption>')
    st = os.stat(path)
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("META-INF/encryption.xml", xml)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    return path


def test_a_locked_epub_is_never_split_and_a_books_obfuscated_fonts_are_no_lock(monkeypatch):
    """B6: an EPUB whose encryption.xml encrypts its text (a store's DRM) is "locked": passed over before it is split
    (encrypted bytes read as text make mojibake words), remembered by its stats. A font obfuscated the IDPF's way is
    an ordinary book's: split as always."""
    from app import extract
    from tests.test_sources_scan import _chapters, _epub
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Media")
    locked = _lock(_epub(os.path.join(src, "Locked", "月影 1.epub"), _chapters()),
                   "http://www.w3.org/2001/04/xmlenc#aes128-cbc", "EPUB/c1.xhtml")
    fonts = _lock(_epub(os.path.join(src, "Fonts", "月影 2.epub"), _chapters()),
                  "http://www.idpf.org/2008/embedding", "EPUB/fonts/mincho.otf")
    opened = []
    real = extract.chunks_of
    monkeypatch.setattr(extract, "chunks_of", lambda *a, **k: opened.append(a[0]) or real(*a, **k))
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert opened == [fonts] and got["added"] >= 2 and got["skipped"] == 1
        assert _library_files(data_dir) and all(r.startswith("Library/月影 2/") for r in _library_files(data_dir))
        read = []
        _spy_reads(monkeypatch, read)
        _look(store, language, root, full=True)
        assert locked not in read                                                # remembered: never read again


_APPLE_DOUBLE = b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        " + b"\x00" * 4064   # a 4 KB `._` twin


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_macs_dot_files_are_never_listed_and_pairing_still_works(language):
    """B7: a drive a Mac touched holds `._Show - 01.mkv` (AppleDouble), `._Show - 01.ja.srt`, `._Book.epub` and
    `.DS_Store` beside the real files. A dot file is skipped as a dot folder is: the subtitle pairs with its own video,
    nothing is counted skipped, and a folder of `._` videos alone makes no "no subtitles yet" show."""
    store, data_dir = _empty(language)
    src = _drive("Media")
    a, b = _SHOWS[language]
    video = _video(os.path.join(src, a, f"{a} - 01.mkv"))
    _write(os.path.join(src, a, f"{a} - 01.{language}.srt"), _text(language, 0))
    for junk in (f"._{a} - 01.mkv", f"._{a} - 01.{language}.srt", "._Book.epub", ".DS_Store"):
        _video(os.path.join(src, a, junk), body=_APPLE_DOUBLE)
    _video(os.path.join(src, b, f"._{b} - 01.mkv"), body=_APPLE_DOUBLE)
    listed = sources._listing(os.path.join(src, a))
    names = [n for n, _p, _s in listed[0] + listed[1]] + list(listed[2])
    assert not [n for n in names if n.startswith(".")]
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert (got["added"], got["skipped"], got["waiting"]) == (1, 0, 0) and _items(store) == 1
        (record,) = _records(store)
        assert os.path.normcase(record["video_path"]) == os.path.normcase(os.path.abspath(video))


def test_a_small_ts_file_is_no_video_and_node_modules_is_never_listed(monkeypatch):
    """S9: `.ts` is MPEG-TS and TypeScript. A `.ts` under a megabyte (by the listing's stat: nothing read) is no video
    — a web project's sources make no "no subtitles yet" shows — while a 2 MB one is a video waiting for its text; a
    `node_modules` folder is never listed at all."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    code = "export function greet(name: string): string {\n  return `hello ${name}`;\n}\n" * 28   # about 2 KB
    _write(os.path.join(src, "web", "src", "main.ts"), code)
    _write(os.path.join(src, "web", "node_modules", "pkg", "index.ts"), code)
    _video(os.path.join(src, show, f"{show} - 03.ts"), body=b"\x47" + b"\x00" * (2 << 20))
    assert "main.ts" not in sources._listing(os.path.join(src, "web", "src"))[2]
    spy = _ScandirSpy(monkeypatch)
    with store:
        root = store.add_source(src)
        got = _look(store, language, root, first=True)
        assert got["added"] == 1 and _items(store) == 1                         # the 2 MB one, its text to come
        (record,) = _records(store)
        assert record["video_path"].endswith(f"{show} - 03.ts")
        assert not spy.saw(os.path.join(src, "web", "node_modules")) and spy.saw(os.path.join(src, "web", "src"))


# --- the writer: a skip is journalled as Remove is (its trash moves survive a crash) ------------------------------ #

def test_a_skip_on_a_busy_store_is_journalled_and_a_crash_replays_it_once(monkeypatch):
    """Remove is journalled (04 §4.5) for its trash moves; *Never read this folder* is the same write: on a busy store
    it waits in the journal, and after a crash the next start applies it — the folder row, its items to the trash.
    One that landed before the crash (the journal not yet emptied) is let go quietly, never *couldn't be applied*."""
    from tests import services_helpers as h
    from tests.test_services_moves import LockHolder, journal, journalled
    real = ls._WriteLock.acquire
    monkeypatch.setattr(ls._WriteLock, "acquire", lambda self, timeout=ls.LOCK_TIMEOUT: real(self, min(timeout, 0.2)))
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Media")
    _card_and_show(language, src)
    root = store.add_source(src)                                                 # (closed at the end)
    _look(store, language, root, first=True)
    w, heard = _writer(language)
    w2 = w3 = None
    try:
        holder = LockHolder(store.db_path)
        w.skip_folder(os.path.join(src, CARD), label="skipped")
        assert h.until(lambda: journalled(language) == [("skip_folder", [])])
        w._abandon()                                                             # the crash
        holder.release()
        assert store.skipped_folders() == []
        w2, heard2 = _writer(language)
        assert w2.replay()
        assert h.until(lambda: len(store.skipped_folders()) == 1 and not w2.pending())
        assert [r for r in _library_files(data_dir) if "Console Card" in r] == [] and heard2.notes == []
        assert store.read_folder_again(store.skipped_folders()[0]["id"])
        holder = LockHolder(store.db_path)
        w2.skip_folder(os.path.join(src, CARD), label="skipped")
        assert h.until(lambda: journalled(language) == [("skip_folder", [])])
        w2._abandon()
        holder.release()
        store.skip_folder(os.path.join(src, CARD))                               # it landed (another window's)
        w3, heard3 = _writer(language)
        assert w3.replay()
        assert h.until(lambda: journal(language) is None and not w3.pending())
        w3.finish(time.monotonic() + 5)                                          # its thread done: every note heard
        assert heard3.notes == [] and len(store.skipped_folders()) == 1
    finally:
        for writer in (w, w2, w3):
            if writer is not None and not writer._abandoned:
                writer.finish(time.monotonic() + 5)
        store.close()
