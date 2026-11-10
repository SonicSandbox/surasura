"""+ Add (W3.2 Q3, `app/qt/add_menu.py`; the RUNBOOK §1 *+ Add*, §5 lean 2, 06 E13, §5a N14): the stone, its menu, where
what you add lands, a folder walked, Paste text — in the window on its seed (invented Japanese titles) with a recording
writer, and on a **real store with the real writer** where the copy itself is what matters (W3.1a's path: `.part` then
renamed, never over a file, into the show's own folder).

What a wrong answer would cost a learner:
  * an episode added away from its show (or a show's folder flattened into loose files), or anything added left
    waiting in New arrivals (G1.2-12: what you add yourself lands);
  * a file copied over one of theirs, a half-copied file left behind, a video or a shortcut taken in as text;
  * a pasted text lost, or saved in another encoding;
  * a menu entry for a door that isn't there (E13), or one that does nothing;
  * a store that can't be saved taking files (E4).
"""
import os

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import library_store as ls
from app.qt import add_menu, strings, windows
from tests import services_helpers as h
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, _stones_sheet, open_window  # noqa: F401  (the stones' sheet fixture)
from tests.test_services_moves import Heard, Library, _outside_file, lib, make_writer  # noqa: F401  (fixtures)


class Writer(FakeWriter):
    """test_drag's recording writer, with `insert_at`'s `into` (W3.2 Q3) and `origin` (K21)."""

    def insert_at(self, paths, tier, before_id=None, after_id=None, near=(), label=None, into=None, origin=True):
        return self._put("insert_at", [], label, files=list(paths), tier=tier, before_id=before_id,
                         after_id=after_id, into=into, origin=origin)


@pytest.fixture
def world(qapp):
    made = []

    def make(writable=True):
        seed = window_seed.build()
        writer = Writer(seed.library, apply=False)
        writer.writable = writable
        win, services = open_window(qapp, seed, writer)
        made.append((win, services))
        return seed, win, writer
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def _subtitle(folder, name, language="ja", extra=""):
    """A real subtitle file (tests/Test Resources) at `folder/name`, outside the library."""
    with open(os.path.join(h.RESOURCES, language, "phrases_sample.srt"), encoding="utf-8") as f:
        text = f.read()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + extra)
    return path


def inserts(writer):
    return [c[2] for c in writer.calls if c[0] == "insert_at"]


def rows_of(win):
    return win.page_widgets["current"].view_model.rows


# --- where it lands (lean 2) ----------------------------------------------------------------------------------- #
def test_an_episode_whose_show_is_in_current_joins_it_in_its_folder_after_its_last_episode(world, tmp_path,
                                                                                            monkeypatch):
    # The split show (Ep 1–4 at #3, Ep 5–8 at #7): its next episode, picked from the learner's own folder of the same
    # name, goes after the later part's last episode, copied into the show's folder — with its show, never at the top.
    seed, win, writer = world()
    split = [r for r in rows_of(win) if r.title == rows_of(win)[2].title]
    folder = add_menu.show_folder(split[1])
    assert folder == f"HighPriority/{split[1].title}"
    path = _subtitle(tmp_path / "Anime" / split[1].title, f"{split[1].title} - 09.srt")
    monkeypatch.setattr(add_menu, "pick_files", lambda _parent: [path])
    win.adder.run("files")
    kw = inserts(writer)[0]
    assert kw["files"] == [path] and kw["tier"] == split[1].tier
    assert kw["after_id"] == split[1].episodes[-1].id and kw["into"] == folder
    assert kw["origin"] is True                                      # K21: where it came from is recorded
    assert win.moves.toasted.text == strings.DRAG_ADDED.format(name=os.path.basename(path), n=split[1].index)


def test_files_whose_show_isnt_in_current_land_at_the_top_of_current(world, tmp_path, monkeypatch):
    seed, win, writer = world()
    paths = [_subtitle(tmp_path / "Downloads", n) for n in ("知らない番組 01.srt", "知らない番組 02.srt")]
    monkeypatch.setattr(add_menu, "pick_files", lambda _parent: paths)
    win.adder.run("files")
    kw = inserts(writer)[0]
    assert (kw["tier"], kw["after_id"], kw["before_id"], kw["into"]) == ("now", None, None, None)
    assert win.moves.toasted.text == strings.DRAG_ADDED_N.format(count=2, n=1)


def test_a_show_is_found_by_its_title_too_and_hatos_folder_is_never_copied_into(world):
    # The hero sits in hato's drop folder: added files go after it but are never copied into hato's folder.
    seed, win, writer = world()
    hero = rows_of(win)[0]
    assert add_menu.show_folder(hero) is None
    tier, after_id, into, n = add_menu.placement(win.page_widgets["current"].view_model,
                                                 [os.path.join("D:", os.sep, "Anime", hero.title, "09.srt")])
    assert (tier, after_id, into, n) == (hero.tier, hero.episodes[-1].id, None, hero.index + 1)
    assert add_menu.show_in_current(win.page_widgets["current"].view_model, "ＨＯＳＨＩ") is None   # no false match


def test_cancelling_the_file_picker_adds_nothing(world, monkeypatch):
    seed, win, writer = world()
    monkeypatch.setattr(add_menu, "pick_files", lambda _parent: [])
    monkeypatch.setattr(add_menu, "pick_folder", lambda _parent: None)
    win.adder.run("files")
    win.adder.run("folder")
    QApplication.processEvents()
    assert writer.calls == []


# --- a folder ----------------------------------------------------------------------------------------------------- #
def _show_tree(root):
    """A learner's show folder: subtitles in two seasons, a video and a shortcut beside them (not content)."""
    show = root / "春風の配達人"
    _subtitle(show, "春風の配達人 - 01.ja.srt")
    _subtitle(show, "春風の配達人 - 02.ja.srt")
    _subtitle(show / "Season 2", "春風の配達人 S2 - 01.ass")
    (show / "春風の配達人 - 01.mkv").write_bytes(b"\x1aE\xdf\xa3 not a subtitle")
    (show / "desktop.ini").write_text("[.ShellClassInfo]", encoding="utf-8")
    return show


def test_a_folder_is_walked_by_the_disk_syncs_rule_content_files_only_its_folders_kept(tmp_path):
    show = _show_tree(tmp_path)
    found = add_menu.walk_folder(str(show))
    assert sorted((os.path.basename(p), d) for p, d in found) == [
        ("春風の配達人 - 01.ja.srt", ""), ("春風の配達人 - 02.ja.srt", ""), ("春風の配達人 S2 - 01.ass", "Season 2")]
    assert add_menu.walk_folder(str(tmp_path / "空のフォルダ")) == []


def test_a_new_folder_lands_at_the_top_of_current_as_a_folder_of_its_own(world, tmp_path, monkeypatch):
    seed, win, writer = world()
    show = _show_tree(tmp_path)
    monkeypatch.setattr(add_menu, "pick_folder", lambda _parent: str(show))
    win.adder.run("folder")
    assert wait_until(lambda: inserts(writer))
    kw = inserts(writer)[0]
    assert kw["tier"] == "now" and kw["after_id"] is None
    into = dict(zip((os.path.basename(p) for p in kw["files"]), kw["into"]))
    assert into == {"春風の配達人 - 01.ja.srt": "HighPriority/春風の配達人", "春風の配達人 - 02.ja.srt": "HighPriority/春風の配達人",
                    "春風の配達人 S2 - 01.ass": "HighPriority/春風の配達人/Season 2"}
    assert win.moves.toasted.text == strings.DRAG_ADDED.format(name="春風の配達人", n=1)


def test_a_folder_with_nothing_to_add_says_so_in_the_bar(world, tmp_path, monkeypatch):
    seed, win, writer = world()
    empty = tmp_path / "動画だけ"
    empty.mkdir()
    (empty / "第1話.mkv").write_bytes(b"\x1aE\xdf\xa3")
    monkeypatch.setattr(add_menu, "pick_folder", lambda _parent: str(empty))
    win.adder.run("folder")
    assert wait_until(lambda: win.bar_line.full() == strings.ADD_NOTHING.format(name="動画だけ"))
    assert writer.calls == []


# --- Paste text… ------------------------------------------------------------------------------------------------ #
def test_paste_text_writes_one_utf8_txt_and_adds_it_at_the_top(world):
    seed, win, writer = world()
    card = win.adder.paste()
    assert not card.add.isEnabled()                                  # nothing to add yet
    text = "朝ごはんは何にする？\n昨日の味噌汁が残ってるよ。\n"
    card.title.setText("台所の会話: 朝/夜")
    card.text.setPlainText(text)
    assert card.add.isEnabled()
    writer.stuck = True                                              # (held: its file read before it lands)
    QTest.mouseClick(card.add, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: inserts(writer))
    kw = inserts(writer)[0]
    path = kw["files"][0]
    assert os.path.basename(path) == "台所の会話 朝 夜.txt"            # what Windows refuses in a name taken out
    with open(path, "rb") as f:
        assert f.read().decode("utf-8") == text                      # one UTF-8 .txt, the text as pasted
    assert (kw["tier"], kw["after_id"]) == ("now", None)
    assert kw["origin"] is False                                     # K21: a temporary file is no one's origin
    assert win.moves.toasted.text == strings.DRAG_ADDED.format(name="台所の会話: 朝/夜", n=1)
    writer.free()                                                    # N7: landed, its temporary folder goes
    assert wait_until(lambda: not os.path.exists(os.path.dirname(path)), 5)


def test_paste_closes_on_esc_and_cancel_adding_nothing(world):
    seed, win, writer = world()
    card = win.adder.paste()
    card.text.setPlainText("残しておきたい一文")
    QTest.keyClick(card.text, Qt.Key.Key_Escape)
    assert not add_menu._alive(card) or not card.isVisible()
    card = win.adder.paste()
    card.text.setPlainText("これも")
    QTest.mouseClick(card.cancel, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert writer.calls == []


def test_a_slash_typed_into_the_paste_card_is_text_never_the_searchs_key(world):
    seed, win, writer = world()
    card = win.adder.paste()
    card.text.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClicks(card.text, "1/2")
    assert card.text.toPlainText() == "1/2" and QApplication.focusWidget() is card.text


def test_a_pasted_texts_name_is_safe_and_never_empty():
    assert add_menu.safe_title('a<b>c:"d"/e\\f|g?h*') == "a b c d e f g h"
    assert add_menu.safe_title("   ") == strings.PASTE_DEFAULT_TITLE
    assert add_menu.safe_title("...") == strings.PASTE_DEFAULT_TITLE
    assert len(add_menu.safe_title("長" * 200)) == add_menu.TITLE_MAX


def test_N2_a_pasted_title_that_names_a_device_gets_an_underscore():
    # Windows 10 writes "con.txt" to the console: the text would be lost
    named = ("con", "NUL", "Aux", "com1", "LPT9", "prn.backup")
    assert [add_menu.safe_title(t) for t in named] == ["_con", "_NUL", "_Aux", "_com1", "_LPT9", "_prn.backup"]
    assert add_menu.safe_title("console") == "console" and add_menu.safe_title("com10") == "com10"


# --- S3: its show is the show's own folder, never a leaf another show shares --------------------------------------- #
def _view_of(*shows):
    """A Current view of shows in `HighPriority/<show>/<season>` (as a learner's own folders keep them)."""
    from types import SimpleNamespace as N
    rows = []
    for n, (title, sub, ids) in enumerate(shows, 1):
        eps = [N(id=i, rel_path=f"HighPriority/{title}/{sub}/{title} {k:02d}.srt") for k, i in enumerate(ids, 1)]
        rows.append(N(tier="now", episodes=eps, title=title, cover_title=title, index=n))
    return N(rows=rows)


def test_S3_season_1_of_another_show_lands_at_the_top_never_in_a_show_with_a_season_1_too(tmp_path):
    view = _view_of(("黒鉄の剣士", "Season 1", [11, 12, 13]))
    other = os.path.join(str(tmp_path), "dl", "蒼の旅人", "Season 1", "蒼の旅人 01.srt")
    assert add_menu.placement(view, [other]) == ("now", None, None, 1)
    assert add_menu.placement(view, [other], folder=os.path.dirname(other),
                              rel_dirs=[""]) == ("now", None, ["HighPriority/Season 1"], 1)
    own = os.path.join(str(tmp_path), "dl", "黒鉄の剣士", "Season 1", "黒鉄の剣士 04.srt")    # its own show's season
    assert add_menu.placement(view, [own]) == ("now", 13, "HighPriority/黒鉄の剣士/Season 1", 1)
    for leaf in ("Subs", "S01", "English"):                             # other generic leaves never match a show
        assert add_menu.show_in_current(_view_of(("黒鉄の剣士", leaf, [1])), leaf) is None


def test_K3_a_show_whose_episodes_sit_in_the_content_folder_takes_its_new_episode_there(tmp_path):
    """SRC K3: a show a source folder (or an earlier drop) brought into `Library/<show>` is a show's folder like a
    tier's: + Add puts its next episode beside the others, never in a folder of its own."""
    from types import SimpleNamespace as N
    eps = [N(id=i, rel_path=f"Library/月影の旅人/月影の旅人 - {k:02d}.srt") for k, i in enumerate((21, 22), 1)]
    view = N(rows=[N(tier="now", episodes=eps, title="月影の旅人", cover_title="月影の旅人", index=1)])
    assert add_menu.show_folder(view.rows[0]) == "Library/月影の旅人"
    new = os.path.join(str(tmp_path), "dl", "月影の旅人", "月影の旅人 - 03.srt")
    assert add_menu.placement(view, [new]) == ("now", 22, "Library/月影の旅人", 1)


def test_S3_a_folder_named_like_hatos_is_never_placed_in_hatos_drop_folder(tmp_path):
    view = _view_of(("黒鉄の剣士", "Season 1", [11]))
    folder = os.path.join(str(tmp_path), "Hato")
    tier, after_id, into, n = add_menu.placement(view, [os.path.join(folder, "雨の駅.srt")], folder=folder,
                                                 rel_dirs=[""])
    assert (tier, after_id, into, n) == ("now", None, ["HighPriority/Hato (2)"], 1)
    from app import library_store as ls
    from app.services import moves
    walked = {ls.path_key(f) for f in ls.FOLDER_OF_TIER.values()}
    for sub in ("HighPriority/Hato", "HighPriority/hato/黒鉄の剣士", "HighPriority/X:", "HighPriority/a/C:"):
        with pytest.raises(ValueError):
            moves._into(sub, "HighPriority", walked, ls)
    assert moves._into("HighPriority/Hato (2)", "HighPriority", walked, ls) == ["HighPriority", "Hato (2)"]


# --- S4: a library that can't be saved greys what copies, and the pasted text stays --------------------------------- #
def test_S4_read_only_greys_files_folder_and_paste_with_the_reason_and_the_doors_stay(world, monkeypatch):
    seed, win, writer = world(writable=False)
    monkeypatch.setattr(windows, "available", lambda op, _s, _l: True)
    win.add_stone._fill()
    acts = {a.objectName(): a for a in win.add_stone.menu_.actions() if a.objectName().startswith("add-")}
    for name in ("files", "folder", "paste"):
        assert not acts[f"add-{name}"].isEnabled()
        assert acts[f"add-{name}"].toolTip().startswith(strings.MENU_REFUSED_TIP.split("{")[0])
    assert acts["add-extract"].isEnabled()
    assert win.adder.paste() is None and writer.calls == []           # no card to type into


def test_S4_a_store_that_turns_read_only_keeps_the_paste_card_open_with_its_text(world):
    seed, win, writer = world()
    card = win.adder.paste()
    card.title.setText("駅のアナウンス")
    said = "まもなく二番線に電車が参ります。"
    card.text.setPlainText(said)
    writer.writable = False
    QTest.mouseClick(card.add, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert add_menu._alive(card) and card.isVisible()
    assert card.text.toPlainText() == said and writer.calls == []
    assert win.bar_line.full().startswith(strings.DRAG_REFUSED.split("{")[0])
    writer.writable = True
    QTest.mouseClick(card.add, Qt.MouseButton.LeftButton)            # saved again: it adds
    assert wait_until(lambda: inserts(writer))


# --- the menu and its doors (E13) --------------------------------------------------------------------------------- #
def _names(adder):
    return [n for n, _l, _t in adder.entries()]


def test_the_menu_lists_every_entry_tipped_and_wired_then_the_drop_line(world, monkeypatch):
    seed, win, writer = world()
    monkeypatch.setattr(windows, "_FOUND", dict(windows._FOUND, youtube_downloader=True))
    monkeypatch.setattr(windows, "available", lambda op, _s, _l: True)
    stone = win.add_stone
    assert not stone.isHidden() and stone.toolTip().startswith(stone.accessibleName())
    stone._fill()
    acts = stone.menu_.actions()
    entries = [a for a in acts if a.objectName().startswith("add-")]
    assert [a.text() for a in entries] == [strings.ADD_ITEMS[n][0] for n in add_menu.ORDER]
    assert all(a.toolTip() and a.receivers(a.triggered) > 0 for a in entries)
    assert acts[-1].text() == strings.ADD_DROP_LINE and not acts[-1].isEnabled()


def test_a_door_that_isnt_there_leaves_its_entry_out(world, monkeypatch):
    seed, win, writer = world()
    monkeypatch.setattr(windows, "OPENERS", [o for o in windows.OPENERS if o.name not in ("extract",
                                                                                           "youtube-downloader")])
    assert _names(win.adder) == ["files", "folder", "paste"]
    monkeypatch.setattr(windows, "OPENERS", windows.OPENERS + [windows.Opener(
        "youtube-downloader", "YouTube", "YouTube", lambda s, _l: bool(s.get("enable_youtube_transcripts")),
        lambda _shell: None, module="youtube_downloader")])
    monkeypatch.setattr(windows, "_FOUND", dict(windows._FOUND, youtube_downloader=False))
    assert "youtube" not in _names(win.adder)                         # its module isn't in this Surasura


def test_a_door_opens_its_window(world, monkeypatch):
    seed, win, writer = world()
    opened = []
    monkeypatch.setattr(windows, "launch", lambda _shell, op: opened.append(op.name))
    win.adder.run("extract")
    assert opened == ["extract"]


def test_without_a_library_only_the_doors_are_offered(qapp):
    from app.qt import shell
    services = shell.Services()
    win = shell.open_window(qapp, services)
    try:
        assert "files" not in _names(win.adder) and "paste" not in _names(win.adder)
        assert "extract" in _names(win.adder) and not win.add_stone.isHidden()
        win.add_stone._fill()
        assert strings.ADD_DROP_LINE not in [a.text() for a in win.add_stone.menu_.actions()]
    finally:
        win.close()
        services.shutdown(0.5)


def test_E4_a_store_that_cant_be_saved_takes_no_files_and_says_why(world, tmp_path, monkeypatch):
    seed, win, writer = world(writable=False)
    path = _subtitle(tmp_path / "Downloads", "知らない番組 01.srt")
    monkeypatch.setattr(add_menu, "pick_files", lambda _parent: [path])
    win.adder.run("files")
    assert writer.calls == []
    assert win.bar_line.full().startswith(strings.DRAG_REFUSED.split("{")[0])


def test_the_header_reads_mark_wordmark_search_then_level_add_and_help(qapp):
    from tests.qt.test_jobs_bar import World
    w = World(qapp)
    try:
        row = w.win.header.layout()
        at = {name: row.indexOf(widget) for name, widget in (("search", w.win.search), ("level", w.d.level),
                                                             ("add", w.win.add_stone), ("help", w.d.help))}
        assert at["search"] < at["level"] < at["add"] < at["help"]
    finally:
        w.close()


def test_the_stone_rises_a_pixel_under_the_hand(world):
    seed, win, writer = world()
    stone = win.add_stone
    centre = stone.rect().center()
    QApplication.sendEvent(stone, QEnterEvent(centre.toPointF(), stone.mapToGlobal(centre).toPointF(),
                                              stone.mapToGlobal(centre).toPointF()))
    assert wait_until(lambda: stone.lift == 1.0)


# --- the copy itself, on a real store (W3.1a's path) ------------------------------------------------------------ #
def _show_of(lib):
    """A show in NOW: (its folder, its items' ids in order)."""
    rows = [(i, lib.store.item(i)["rel_path"]) for i in lib.ids("now")]
    folder = next(rel.rsplit("/", 1)[0] for _i, rel in rows if rel.count("/") >= 2)
    return folder, [i for i, rel in rows if rel.startswith(folder + "/")]


def test_a_real_add_copies_into_the_shows_folder_after_its_last_episode_never_over_a_file(lib, make_writer, tmp_path):
    w, heard = make_writer()
    folder, ids = _show_of(lib)
    src = _outside_file(tmp_path / "Explorer", lib.language)
    w.insert_at([src], "now", after_id=ids[-1], label="added", into=folder)
    assert h.until(lambda: heard.saved)
    new = heard.saved[0][0].added[0]
    name = os.path.basename(src)
    copies = f"{ls.CONTENT_FOLDER}/{folder.split('/', 1)[1]}"           # the show's folder in Library (SRC K3)
    assert lib.store.item(new)["rel_path"] == f"{copies}/{name}"
    now = lib.ids("now")
    assert now[now.index(ids[-1]) + 1] == new                          # right after the show's last episode
    other = _outside_file(tmp_path / "Explorer2", lib.language, extra="\n")
    w.insert_at([other], "now", after_id=new, into=folder)
    assert h.until(lambda: len(heard.saved) == 2)
    base, ext = os.path.splitext(name)
    listing = os.listdir(os.path.join(lib.data_dir, *copies.split("/")))
    assert name in listing and f"{base} (2){ext}" in listing          # never over the learner's file
    assert not [n for n in listing if n.endswith(".part")]            # no half copy left
    w.undo()
    assert h.until(lambda: heard.undone)
    assert f"{base} (2){ext}" not in os.listdir(os.path.join(lib.data_dir, *copies.split("/")))   # to the trash


def test_a_real_add_keeps_a_folders_own_folders_and_refuses_a_place_outside_the_library(lib, make_writer, tmp_path):
    w, heard = make_writer()
    src = _outside_file(tmp_path / "Explorer", lib.language)
    w.insert_at([src], "now", into=["HighPriority/春風の配達人/Season 2"])
    assert h.until(lambda: heard.saved)
    new = heard.saved[0][0].added[0]
    assert lib.store.item(new)["rel_path"] == f"Library/春風の配達人/Season 2/{os.path.basename(src)}"   # (SRC K3)
    assert lib.ids("now")[0] == new
    for outside in ("../Elsewhere", "Graduated/Old", "C:/Windows", ""):
        if not outside:
            continue
        notes = len(heard.notes)
        w.insert_at([_outside_file(tmp_path / "Explorer3", lib.language, extra=outside)], "now", into=outside)
        assert h.until(lambda: len(heard.notes) > notes), outside
    assert not os.path.exists(os.path.join(lib.data_dir, "..", "Elsewhere"))
    with pytest.raises(ValueError):
        w.insert_at([src, src], "now", into=["HighPriority/a"])          # a folder for every file
