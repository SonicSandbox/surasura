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
import sys
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
def test_a_skip_replayed_after_a_crash_between_its_trash_moves_and_its_commit_keeps_each_file_reachable(language):
    """H7: Skip moves each item's copy to the trash, then the store commits. Killed between the two, the replay finds
    no files: each trash row still names its own copy (never NULL), so Put back brings every one back."""
    from app.services import moves as M
    store, data_dir = _empty(language)
    src = _drive("Media")
    _card_and_show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        folder = os.path.join(src, CARD)
        ids = store.items_under(folder)
        bodies = {}
        for i in ids:
            rel = store.item(i)["rel_path"]
            with open(os.path.join(data_dir, *rel.split("/")), "rb") as f:
                bodies[rel] = f.read()
            ls.trash_file(data_dir, rel)                # the crash: the files moved, the store never committed
        change = M.Writer._skip_folder(None, store, {"op": "skip_folder", "path": folder, "replay": True})
        rows = store.trash_rows(change.trash_ids)
        assert len(rows) == len(ids) == 2
        assert len({r["trashed_path"] for r in rows}) == 2 and all(r["trashed_path"] for r in rows), \
            "each row names its own copy"
        for r in rows:
            with open(os.path.join(data_dir, *r["trashed_path"].split("/")), "rb") as f:
                assert f.read() == bodies[r["rel_path"]], "its own bytes"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_replayed_skip_never_takes_a_newer_trashed_file_of_the_same_name_and_size_but_other_bytes(language):
    """H7: the replay's copy is the item's own — its record's bytes — never the newest file of its name and size in
    the trash (another file once removed under that name): that one stays unreferenced, as it was."""
    from app.services import moves as M
    store, data_dir = _empty(language)
    src = _drive("Media")
    _card_and_show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        folder = os.path.join(src, CARD)
        ids = store.items_under(folder)
        own = {}
        for i in ids:
            rel = store.item(i)["rel_path"]
            own[i] = ls.trash_file(data_dir, rel)       # the crash: the files moved, the store never committed
        trash = os.path.join(data_dir, ".trash")
        first = os.path.join(data_dir, *own[ids[0]].split("/"))
        with open(first, "rb") as f:
            body = f.read()
        base, ext = os.path.splitext(os.path.basename(store.item(ids[0])["rel_path"]))
        decoy = os.path.join(trash, f"{base}_20000101000000{ext}")   # older, first in line: same name, same size
        with open(decoy, "wb") as f:
            f.write(bytes(b ^ 1 for b in body))
        change = M.Writer._skip_folder(None, store, {"op": "skip_folder", "path": folder, "replay": True})
        rows = {r["item_id"]: r["trashed_path"] for r in store.trash_rows(change.trash_ids)}
        assert rows == own, "each row names its own copy, never the decoy"
        assert os.path.exists(decoy)


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


# --- LF-21: one video-file rule (`runner.video_file`), and a Mac's `._` copy (`runner.mac_copy`) the only dot rule -- #

def _waiting_items(store):
    return store.conn.execute("SELECT COUNT(*) FROM items WHERE availability = 'waiting'").fetchone()[0]


def test_a_title_that_starts_with_a_dot_is_read_its_folder_and_files_both():
    """LF-21: a dot is a Mac's `._` copy only — `.hack` is a title: its folder is walked, its video and subtitle are an
    episode like any other (every dot name was passed over: the show never came in)."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Media")
    folder = os.path.join(src, ".hack Sign")
    _video(os.path.join(folder, ".hack Sign - 01.mkv"), body=b"fake matroska 1")
    sub = _write(os.path.join(folder, ".hack Sign - 01.ja.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        result = _look(store, language, root, first=True)
        assert (result["added"], _items(store), _waiting_items(store)) == (1, 1, 0)
        assert ls.path_key(os.path.abspath(sub)) in store.origins()


@pytest.mark.parametrize("folder", [".AppleDouble", ".Trashes", ".Spotlight-V100", ".fseventsd", ".TemporaryItems"])
def test_the_dot_folders_a_mac_makes_are_skipped_by_name(folder):
    """LF-21: the folders macOS writes on a drive (`library_store.SKIP_DIRS`) are skipped as the recycle bins are —
    their files are metadata or deleted ones, never episodes."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Media")
    a = _SHOWS[language][0]
    _write(os.path.join(src, a, folder, f"{a} - 01.ja.srt"), _text(language, 1))
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _items(store) == 0


def test_a_macs_copies_are_skipped_and_a_small_ts_is_no_video():
    """LF-21: `._ep01.mkv` / `._ep01.ja.srt` (a Mac's AppleDouble twins) are never listed; a `.ts` under TS_MIN is
    TypeScript, never a video waiting for its subtitle — the same `runner.video_file` Connect's index asks."""
    language = "ja"
    store, data_dir = _empty(language)
    src = _drive("Media")
    a = _SHOWS[language][0]
    folder = os.path.join(src, a)
    for junk in ("._ep01.mkv", "._ep01.ja.srt"):
        _video(os.path.join(folder, junk), body=_APPLE_DOUBLE)
    _video(os.path.join(src, "tool", "index.ts"), body=b"export const x = 1;\n" * 40)
    listed = sources._listing(folder)
    assert (listed[0], listed[2]) == ([], {})
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        assert _items(store) == 0


# --- K6 inside a show: *Never read this folder* on a show's `Extras/` ---------------------------------------------- #
# A show folder with three episodes (video + our subtitle each) and an `Extras/` folder beside them: a creditless opening
# and a trailer with no subtitle (never waiting: extras), a creditless ending and a featurette with ours, and a nested
# `Interviews/` with one more. What a learner wants: the extras gone and never read again, the show exactly as it was.

def _show_with_extras(language, src, show=None, extras="Extras"):
    """-> (the show folder, its three episodes' subtitles, {name: the extras' subtitles})."""
    show = show or _SHOWS[language][1]
    top = os.path.join(src, show)
    eps = []
    for n in (1, 2, 3):
        _video(os.path.join(top, f"{show} - {n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 ep %d " % n)
        eps.append(_write(os.path.join(top, f"{show} - {n:02d}.srt"), _text(language, n)))
    ex = os.path.join(top, extras)
    _video(os.path.join(ex, f"{show} - NCOP.mkv"), body=b"\x1a\x45\xdf\xa3 ncop ")
    _video(os.path.join(ex, f"{show} - Trailer.mkv"), body=b"\x1a\x45\xdf\xa3 trailer ")
    _video(os.path.join(ex, f"{show} - NCED.mkv"), body=b"\x1a\x45\xdf\xa3 nced ")
    _video(os.path.join(ex, "Making Of.mkv"), body=b"\x1a\x45\xdf\xa3 making ")
    _video(os.path.join(ex, "Interviews", "Cast Talk.mkv"), body=b"\x1a\x45\xdf\xa3 talk ")
    subs = {"nced": _write(os.path.join(ex, f"{show} - NCED.srt"), _text(language, 4, " nced")),
            "making": _write(os.path.join(ex, "Making Of.srt"), _text(language, 5, " making")),
            "talk": _write(os.path.join(ex, "Interviews", "Cast Talk.srt"), _text(language, 6, " talk"))}
    _settle(src)                                                                 # folder times the cache trusts
    return top, eps, subs


def _show_state(store, origins):
    """The show's own items as the learner sees them: tier, order, watched, pin, its title and piece, its file — and
    the groups the look reads."""
    held = store.origins()
    ids = [held[ls.origin_key(p)[4:]].item_id for p in origins]
    return [store.conn.execute("SELECT id, tier, ord, watched, pinned, work_id, piece_id, rel_path FROM items "
                               "WHERE id = ?", (i,)).fetchone() for i in ids], store.show_groups()


def _under_extras(store, top, extras="Extras"):
    """The items recorded from a file under the show's extras folder."""
    key = ls.path_key(ls.folder_path(os.path.join(top, extras))) + "/"
    return sorted({o.item_id for k, o in store.origins().items() if k.startswith(key)})


@pytest.mark.parametrize("language", LANGUAGES)
def test_skipping_a_shows_extras_removes_only_the_extras_and_one_undo_puts_them_back(language):
    """`Show/Extras/` skipped: its three subtitled extras leave (to the store's trash: Put back can find them); the
    show's three episodes keep their tier, place, watched mark, title and piece; one Undo puts the extras back where
    they stood and reads the folder again. ⋯ on an extra offers `Extras` first, then the show's folder."""
    store, _data = _empty(language)
    src = _drive("Media")
    top, eps, subs = _show_with_extras(language, src)
    with store:
        root = store.add_source(src)
        first = _look(store, language, root, first=True)
        extras = _under_extras(store, top)
        assert len(extras) == 3 and first["added"] == 6, first                   # no item for NCOP / the trailer
        ep_ids = [store.origins()[ls.origin_key(p)[4:]].item_id for p in eps]
        store.set_watched([ep_ids[0]])
        shown, current, rels = _show_state(store, eps), _current(store), _rels(store)
        making = store.origins()[ls.origin_key(subs["making"])[4:]].item_id
        talk = store.origins()[ls.origin_key(subs["talk"])[4:]].item_id
        assert store.skip_choices([making]) == [ls.folder_path(os.path.join(top, "Extras")), ls.folder_path(top)]
        assert store.skip_choices([talk]) == [ls.folder_path(os.path.join(top, "Extras", p)) for p in
                                              ("Interviews", "")] + [ls.folder_path(top)]
        change = store.skip_folder(os.path.join(top, "Extras"))
        assert sorted(it["id"] for it in change.items) == extras
        rows = store.trash_rows(change.trash_ids)
        assert len(rows) == 3 and not any(r["restored_at"] for r in rows)        # Put back-able
        assert all(store.item(i) is None for i in extras)
        assert _show_state(store, eps) == shown                                  # the show untouched
        out = store.undo(change)
        assert len(out.restored) == 3 and out.folder_dropped
        assert _rels(store) == rels and _current(store) == current and _show_state(store, eps) == shown
        assert store.skipped_folders() == [] and store.excluded() == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_skipped_extras_folder_and_everything_under_it_is_never_listed_by_any_later_look(language, monkeypatch):
    """Every later look — a quick one, the first after a start, a Refresh — after a new extra lands in it and in a
    folder nested two deep under it, never lists `Extras/` or anything under it, nor counts their files as found."""
    store, _data = _empty(language)
    src = _drive("Media")
    top, eps, subs = _show_with_extras(language, src)
    show = os.path.basename(top)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        store.skip_folder(os.path.join(top, "Extras"))
        spy = _ScandirSpy(monkeypatch)
        _write(os.path.join(top, "Extras", f"{show} - PV.srt"), _text(language, 7, " pv"), age=30)
        _write(os.path.join(top, "Extras", "Interviews", "Deep", "Staff Talk.srt"), _text(language, 8, " st"), age=30)
        looks = [_look(store, language, root)]
        sources._LOOKED.clear()                                                  # a start
        looks.append(_look(store, language, root))
        looks.append(_look(store, language, root, full=True))                   # a Refresh
        for got in looks:
            assert got["added"] == 0 and got["found"] == 3, got                  # the three episodes alone
        for folder in ("Extras", os.path.join("Extras", "Interviews"), os.path.join("Extras", "Interviews", "Deep")):
            assert not spy.saw(os.path.join(top, folder)), folder
        assert spy.saw(top)
        assert _under_extras(store, top) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_read_again_brings_a_shows_extras_back_once_and_the_episodes_stay_as_they_were(language):
    """*Read again*: the next quick look (the show folder's time never moved) takes the three extras in again, once;
    the episodes are as they were."""
    store, _data = _empty(language)
    src = _drive("Media")
    top, eps, subs = _show_with_extras(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        change = store.skip_folder(os.path.join(top, "Extras"))
        shown = _show_state(store, eps)
        assert store.read_folder_again(change.folder) is True
        back = _look(store, language, root)                                      # quick: the show folder unchanged
        assert back["added"] == 3 and len(_under_extras(store, top)) == 3
        assert _show_state(store, eps) == shown
        assert _look(store, language, root, full=True)["added"] == 0             # once


@pytest.mark.parametrize("language", LANGUAGES)
def test_skipping_the_show_after_its_extras_and_reading_it_again_keeps_the_extras_skipped(language):
    """Extras skipped, then the whole show: both rows held, the episodes leave too; an Undo of the show's skip, and
    *Read again* on it, bring the episodes back and never the extras (still skipped)."""
    store, _data = _empty(language)
    src = _drive("Media")
    top, eps, subs = _show_with_extras(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        extras = store.skip_folder(os.path.join(top, "Extras"))
        assert store.skip_refused(top) is None
        whole = store.skip_folder(top)
        assert len(whole.trash_ids) == 3
        assert [f["id"] for f in store.skipped_folders()] == [extras.folder, whole.folder]
        assert _look(store, language, root, full=True)["found"] == 0
        out = store.undo(whole)
        assert len(out.restored) == 3 and [f["id"] for f in store.skipped_folders()] == [extras.folder]
        again = _look(store, language, root, full=True)
        assert again["added"] == 0 and again["found"] == 3 and _under_extras(store, top) == []
        whole = store.skip_folder(top)
        assert store.read_folder_again(whole.folder)
        back = _look(store, language, root, full=True)
        assert back["added"] == 3 and _under_extras(store, top) == []
        assert [f["id"] for f in store.skipped_folders()] == [extras.folder]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_extras_of_a_skipped_show_are_refused_as_skipped_already_and_come_back_with_the_show(language):
    """The show skipped first: its extras (and a folder under them) are refused as skipped already; *Read again* on
    the show brings all six back."""
    store, _data = _empty(language)
    src = _drive("Media")
    top, eps, subs = _show_with_extras(language, src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        whole = store.skip_folder(top)
        assert len(whole.trash_ids) == 6
        assert store.skip_refused(os.path.join(top, "Extras")) == ls.SKIP_ALREADY
        with pytest.raises(ls.NotASource):
            store.skip_folder(os.path.join(top, "Extras", "Interviews"))
        assert store.read_folder_again(whole.folder)
        assert _look(store, language, root)["added"] == 6


@pytest.mark.parametrize("spelling", ["case", "slashes", "trailing"])
def test_a_skip_of_extras_spelled_another_way_is_the_same_folder(spelling):
    """The folder as a dialog or a typed path may spell it: another case (Windows), forward slashes, a trailing
    separator — one folder, its items gone, and the look still never lists it."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    top, eps, subs = _show_with_extras(language, src)
    path = {"case": os.path.join(top, "EXTRAS") if sys.platform == "win32" else os.path.join(top, "Extras"),
            "slashes": os.path.join(top, "Extras").replace("\\", "/"),
            "trailing": os.path.join(top, "Extras") + os.sep}[spelling]
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        change = store.skip_folder(path)
        assert len(change.trash_ids) == 3
        assert store.skip_refused(os.path.join(top, "Extras")) == ls.SKIP_ALREADY
        got = _look(store, language, root, full=True)
        assert got["added"] == 0 and got["found"] == 3


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_mixed_script_extras_folder_with_crlf_subtitles_is_skipped_and_never_read(language):
    """A show named in the library's script with a mixed-script extras folder (`特典 Extras・映像` / `特典 花絮・影像`) and
    CRLF subtitles: ⋯ offers it, the skip takes its three extras, no look reads it; the episodes stay."""
    store, _data = _empty(language)
    src = _drive("Media")
    show = _SHOWS[language][0]
    extras = {"ja": "特典 Extras・映像", "zh": "特典 花絮・影像"}[language]
    top, eps, subs = _show_with_extras(language, src, show=show, extras=extras)
    for p in list(subs.values()) + eps:
        with open(p, encoding="utf-8") as f:
            body = f.read()
        with open(p, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(body)
        t = time.time() - 60                                                     # settled, as `_write` leaves one
        os.utime(p, (t, t))
    _settle(src)
    with store:
        root = store.add_source(src)
        _look(store, language, root, first=True)
        inside = _under_extras(store, top, extras)
        assert len(inside) == 3
        shown = _show_state(store, eps)
        assert ls.folder_path(os.path.join(top, extras)) in store.skip_choices(inside[:1])
        store.skip_folder(os.path.join(top, extras))
        got = _look(store, language, root, full=True)
        assert got["added"] == 0 and got["found"] == 3 and _show_state(store, eps) == shown


@pytest.mark.parametrize("name", ["node_modules", ".trash", "@eaDir"])
def test_a_show_subfolder_named_like_one_no_look_reads_can_be_skipped_harmlessly(name):
    """A show's subfolder no look reads anyway (a name `skip_dir` names): its skip is accepted, removes nothing and
    changes no look; *Read again* leaves it unread (the name rule still holds)."""
    language = "ja"
    store, _data = _empty(language)
    src = _drive("Media")
    top, eps, subs = _show_with_extras(language, src)
    _write(os.path.join(top, name, "ep99.srt"), _text(language, 9))
    _settle(src)
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 6
        change = store.skip_folder(os.path.join(top, name))
        assert change.trash_ids == [] and len(store.skipped_folders()) == 1
        assert _look(store, language, root, full=True)["added"] == 0
        assert store.read_folder_again(change.folder)
        assert _look(store, language, root, full=True)["added"] == 0


@pytest.mark.skipif(sys.platform != "win32", reason="a junction is Windows' folder link")
def test_an_extras_junction_is_never_followed_and_skipping_it_writes_only_its_row():
    """`Show/Extras` a junction to a folder on another drive: no look follows it, skipped or not; its skip is accepted
    (it's inside the source) and removes nothing; the junction's target is never touched."""
    import _winapi
    language = "ja"
    store, _data = _empty(language)
    src, target = _drive("Media"), _drive("Elsewhere")
    show = _SHOWS[language][1]
    top = os.path.join(src, show)
    for n in (1, 2):
        _write(os.path.join(top, f"{show} - {n:02d}.srt"), _text(language, n))
    _write(os.path.join(target, "Making Of.srt"), _text(language, 5))
    _winapi.CreateJunction(target, os.path.join(top, "Extras"))
    with store:
        root = store.add_source(src)
        assert _look(store, language, root, first=True)["added"] == 2
        before = _tree(target)
        change = store.skip_folder(os.path.join(top, "Extras"))
        assert change.trash_ids == []
        assert _look(store, language, root, full=True)["added"] == 0
        assert _tree(target) == before


# --- K6 from New arrivals: extras found after setup arrive there first ---------------------------------------------- #
# Setup read the show and one interview (placed in Current); a later look finds a featurette video with no subtitle in
# `Extras/` (it waits in New arrivals for its text) and a commentary track in `Extras/Commentary/` (a text arrival).

def _extras_arrive(language, store, src, root):
    """-> (the show folder, {"waiting", "text", "placed": item id})."""
    show = _SHOWS[language][1]
    top = os.path.join(src, show)
    for n in (1, 2):
        _video(os.path.join(top, f"{show} - {n:02d}.mkv"), body=b"\x1a\x45\xdf\xa3 ep %d " % n)
        _write(os.path.join(top, f"{show} - {n:02d}.srt"), _text(language, n))
    placed = _write(os.path.join(top, "Extras", "Interviews", "Cast Talk.srt"), _text(language, 6, " talk"))
    _settle(src)
    _look(store, language, root, first=True)
    making = _video(os.path.join(top, "Extras", "Making Of.mkv"), body=b"\x1a\x45\xdf\xa3 making ")
    _video(os.path.join(top, "Extras", f"{show} - NCOP.mkv"), body=b"\x1a\x45\xdf\xa3 ncop ")   # an extra: never waits
    text = _write(os.path.join(top, "Extras", "Commentary", "Commentary 01.srt"), _text(language, 5, " commentary"))
    _settle(src)
    got = _look(store, language, root)
    held = store.origins()
    ids = {k: held[ls.origin_key(p)[4:]].item_id for k, p in (("waiting", making), ("text", text), ("placed", placed))}
    assert sorted(got["ids"]) == sorted([ids["waiting"], ids["text"]]), got
    return top, ids


@pytest.mark.parametrize("language", LANGUAGES)
def test_new_arrivals_from_a_shows_extras_offer_their_folder_and_each_above_it(language):
    """⋯ on an arrival (the same entry a list row has): a waiting featurette offers `Extras`, then the show; the
    commentary `Commentary`, `Extras`, the show — never the source folder."""
    store, _data = _empty(language)
    src = _drive("Media")
    with store:
        root = store.add_source(src)
        top, ids = _extras_arrive(language, store, src, root)
        assert store.item(ids["waiting"])["tier"] == "arrivals" and store.item(ids["text"])["tier"] == "arrivals"
        extras = ls.folder_path(os.path.join(top, "Extras"))
        assert store.skip_choices([ids["waiting"]]) == [extras, ls.folder_path(top)]
        assert store.skip_choices([ids["text"]]) == [os.path.join(extras, "Commentary"), extras, ls.folder_path(top)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_writers_skip_of_extras_takes_the_arrivals_and_the_placed_extra_in_one_change_with_one_undo(language):
    """`Writer.skip_folder` on `Extras/`: the waiting featurette, the commentary (both New arrivals) and the interview
    placed in Current leave in ONE change (Put back-able), the show stays; the next looks never bring the waiting video
    back; one Undo puts all three back where they were — the two arrivals in New arrivals."""
    from tests import services_helpers as h
    store, data_dir = _empty(language)
    src = _drive("Media")
    root = store.add_source(src)                                                 # (closed at the end)
    top, ids = _extras_arrive(language, store, src, root)
    tiers = {k: store.item(i)["tier"] for k, i in ids.items()}
    assert tiers["placed"] != "arrivals"
    current, rels, before = _current(store), _rels(store), _tree(src)
    w, heard = _writer(language)
    try:
        w.skip_folder(os.path.join(top, "Extras"), label="skipped")
        assert h.until(lambda: heard.saved)
        (change, _label), = heard.saved
        assert sorted(it["id"] for it in change.items) == sorted(ids.values())
        rows = store.trash_rows(change.trash_ids)
        assert len(rows) == 3 and not any(r["restored_at"] for r in rows)        # Put back-able
        assert all(store.item(i) is None for i in ids.values()) and _tree(src) == before
        assert _look(store, language, root)["added"] == 0
        sources._LOOKED.clear()                                                  # a start
        assert _look(store, language, root, full=True)["added"] == 0             # the waiting video stays out
        w.undo()
        assert h.until(lambda: heard.undone)
        assert heard.notes == [] and store.skipped_folders() == []
        assert {k: store.item(i)["tier"] for k, i in ids.items()} == tiers
        assert _current(store) == current and _rels(store) == rels
        assert _look(store, language, root, full=True)["added"] == 0             # nothing twice
    finally:
        w.finish(time.monotonic() + 5)
        store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_read_again_brings_skipped_extras_back_as_new_arrivals(language):
    """*Read again* after the skip: the next quick look takes the featurette (waiting again), the commentary and the
    interview back in, each in New arrivals (shows never shown, SRC-2), once."""
    store, _data = _empty(language)
    src = _drive("Media")
    with store:
        root = store.add_source(src)
        top, ids = _extras_arrive(language, store, src, root)
        change = store.skip_folder(os.path.join(top, "Extras"))
        assert len(change.trash_ids) == 3
        assert store.read_folder_again(change.folder)
        back = _look(store, language, root)
        assert back["added"] == 3
        assert all(store.item(i)["tier"] == "arrivals" for i in back["ids"])
        names = sorted(os.path.basename(store.item(i)["rel_path"]) for i in back["ids"])
        assert names == ["Cast Talk.srt", "Commentary 01.srt", "Making Of.mkv"]
        assert _look(store, language, root, full=True)["added"] == 0


@pytest.mark.parametrize("queued_after_copies", [True, False])
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_replayed_skip_never_takes_a_trash_copy_made_before_it_was_queued(language, queued_after_copies):
    """H7: a copy trashed before the skip was queued is an older copy, not this skip's. A replay whose file is already
    gone takes no older copy: nothing in the trash it names is that old copy, and no row points at it. A copy made at
    or after the queue stamp is still this skip's, and the replay takes it."""
    from app.services import moves as M
    store, data_dir = _empty(language)
    src = _drive("Media")
    _card_and_show(language, src)
    with store:
        _look(store, language, store.add_source(src), first=True)
        folder = os.path.join(src, CARD)
        ids = store.items_under(folder)
        for i in ids:
            ls.trash_file(data_dir, store.item(i)["rel_path"])   # an earlier copy, made before the skip is queued
        old = {os.path.relpath(os.path.join(d, n), data_dir).replace(os.sep, "/")
               for d, _sub, names in os.walk(data_dir) for n in names}
        # constant stamps, far from now, so neither the clock nor the time zone can decide the case:
        # the copies are older than a stamp in the far future, and newer than one in the far past
        queued = "00000101000000" if queued_after_copies else "99991231235959"
        change = M.Writer._skip_folder(None, store, {"op": "skip_folder", "path": folder, "replay": True, "at": queued})
        rows = store.trash_rows(change.trash_ids)
        assert rows, "the replay names its items"
        if queued_after_copies:
            # the copies count as this skip's: each row names one of them
            assert all(r["trashed_path"] in old for r in rows), "a copy made after the queue is the replay's copy"
        else:
            # the copies are older than the queue: the replay takes none, and every older copy stays where it was
            for p in old:
                assert os.path.exists(os.path.join(data_dir, *p.split("/"))), f"older copy was touched: {p}"
            assert not any(r["trashed_path"] in old for r in rows), "no row names the older copy"
