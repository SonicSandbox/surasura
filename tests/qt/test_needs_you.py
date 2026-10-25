"""Needs you in the window (W3.2 Q5, `app/qt/needs.py`; RUNBOOK §1 *Needs you*, §5a IK-2, IK-3, IK-8, N8, N9; the
window's spec A2 #69–70, G4–G7, 06 E8, E10): the tab's cracked amber stone, the cards and their buttons, the bulk
answer, the rename questions, Connect's entries — on the window's seed (invented Japanese titles) through the stand-in
store, with a writer that records, and real-named video files in a temp library folder.

What a wrong answer would cost a learner:
  * a badge that counts what was already looked at (P1.2-1), or a tab left showing over nothing (A2 #70);
  * an episode's video linked as its content file (IK-2: `relink` would repoint the subtitle at a video), or a wrong
    video linked by a guess;
  * a whole show sent to the trash without a question naming how many, with no Undo, or a drive that's only unplugged
    sent to the trash (IK-8);
  * Connect's ledger written on the window's thread (a freeze), or a button shown that does nothing;
  * every card rebuilt on every status tick (S19, N9).
"""
import json
import os
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from app import path_utils
from app.qt import needs as needs_ui
from app.qt import stones, strings
from app.services import needs as service
from app.services import status as status_service
from tests.fixtures import window_seed
from tests.qt.conftest import wait_until
from tests.qt.test_drag import FakeWriter, open_window

NO_VIDEO = service._no_video_reason()


class NeedsWriter(FakeWriter):
    """The writer's W3.2 commands, recorded and saved at once (the stand-in library takes none of them)."""

    def relink(self, item_id, path, label=None):
        return self._put("relink", [item_id], label, path=path)

    def its_new(self, path, label=None):
        self.calls.append(("its_new", [], {"path": path}))
        threading.Thread(target=self.on_reread, daemon=True).start()       # the store keeps no change for it
        return len(self.calls)

    def link_video(self, item_id, video_path, label=None):
        return self._put("link_video", [item_id], label, path=video_path)

    def remove(self, ids, label=None):
        return self._put("remove", ids, label)


@pytest.fixture(autouse=True)
def _stones_sheet(qapp):
    key = stones._key(1.0, "M")
    if key not in stones._SHEETS:
        stones._landed(key, stones.build(*key))


def settle(ny, timeout=10):
    """Ask again and wait for the answer (the worker's)."""
    n = ny.gathers
    ny.refresh()
    assert wait_until(lambda: ny.gathers > n and not ny._running, timeout)
    for _ in range(5):
        QApplication.processEvents()


@pytest.fixture
def world(qapp):
    made = []

    def make(connect=None, asks=(), offline=None, connect_calls=None, apply=False):
        data = path_utils.get_data_path("ja")
        os.makedirs(data, exist_ok=True)                    # the library folder is there (else: all of it offline)
        seed = window_seed.build()
        writer = NeedsWriter(seed.library, apply=apply)
        win, services = open_window(qapp, seed, writer)
        made.append((win, services))
        ny = win.needs_you
        assert ny is not None
        ny.data_dir = data
        ny.read_settings = lambda: {"connect_enabled": connect is not None, "connect_video_folders": {}}
        ny.read_connect = lambda _lang: connect
        ny.read_asks = lambda: list(asks)
        if offline is not None:
            ny.find_offline = lambda _lang, _rels, _data: list(offline)
        if connect_calls is not None:
            ny.connect_calls.update(connect_calls)
        settle(ny)
        return seed, win, writer, ny
    yield make
    for win, services in made:
        win.close()
        services.shutdown(0.5)


def closed(widget):
    from PyQt6 import sip
    return sip.isdeleted(widget) or not widget.isVisible()


def rows_of(win):
    return win.page_widgets["current"].view_model.rows


def entry_of(ny, kind, title=None):
    return next(e for e in ny.entries if e.kind == kind and (title is None or e.data.get("title") == title))


def button(ny, key, action, line=None):
    """The shown button for `action` on card `key` (on `line`'s row: the line's own), or None."""
    for b in ny.cards.buttons(key):
        if b.property("action") == action:
            if line is None or line.text in _row_text(b):
                return b
    return None


def _row_text(b):
    """The words beside a line's button (its row's labels)."""
    card = b.parentWidget()
    lay = card.layout()
    for i in range(lay.count()):
        item = lay.itemAt(i).layout()
        if item is None:
            continue
        widgets = [item.itemAt(k).widget() for k in range(item.count())]
        if b in widgets:
            texts = []
            for k in range(item.count()):
                sub = item.itemAt(k).layout()
                if sub is not None:
                    texts += [sub.itemAt(j).widget().text() for j in range(sub.count())
                              if isinstance(sub.itemAt(j).widget(), QLabel)]
            return " ".join(texts)
    return ""


def no_video_show(win, n=2):
    """A Current anime row with `n` episodes on disk (their content there): Connect waits on their videos."""
    for r in rows_of(win):
        eps = [e for e in r.episodes if not e.missing and e.number is not None]
        if r.media == "anime" and len(eps) >= n and not any(e.missing for e in r.episodes):
            return r, eps[:n]
    raise AssertionError("the seed has no such row")


def jobs(*eps):
    return {"jobs": [{"item": e.id, "reason": NO_VIDEO} for e in eps], "needs": [], "gaps": []}


def video_beside(data, ep, name):
    """A real-named video in the episode's own show folder."""
    folder = os.path.join(data, *ep.rel_path.split("/")[:-1])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(b"\x1aE\xdf\xa3")                           # a Matroska header's first bytes (never opened)
    return path


# --- the tab ------------------------------------------------------------------------------------------------------- #
def test_the_tab_carries_the_cracked_amber_stone_with_the_unseen_count_drawn_once_per_size(world):
    seed, win, writer, ny = world()
    tab = win.tab_buttons["needs"]
    assert ny.entries and not tab.isHidden()                  # the seed has files gone in four shows
    listed, unseen = ny.counts()
    assert unseen == service.badge(ny.entries) == tab.count > 0
    assert listed == len([e for e in ny.entries if e.kind != service.BULK])
    assert tab.badge
    tab.repaint()
    size = needs_ui.stone_size(1.15)                         # Medium
    assert any(k[0] == size for k in needs_ui._STONES)
    before = needs_ui.drawn[0]
    for _ in range(3):
        tab.repaint()
    assert needs_ui.drawn[0] == before                        # drawn once per size × dpr, never per paint
    img = tab.grab().toImage()
    amber = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height())]
    assert any(c.red() > 150 and 100 < c.green() < 160 and c.blue() < 90 for c in amber)    # its #b9873a rim


def test_A2_70_the_tab_hides_once_nothing_waits_and_the_view_goes_back_to_current(world):
    seed, win, writer, ny = world()
    win.show_tab("needs")
    assert win.current_tab() == "needs"
    bulk = entry_of(ny, service.BULK)
    for e in [e for e in ny.entries if e.kind == service.GONE and e.key not in bulk.data.get("video_keys", ())]:
        assert e.data["item_ids"]
    button(ny, "bulk", "keep_all").click()                    # every gone file kept: nothing waits any more
    assert wait_until(lambda: not ny.entries, 10)
    assert wait_until(lambda: win.tab_buttons["needs"].isHidden() and win.current_tab() == "current", 5)


def test_opening_the_page_marks_its_entries_seen_they_stay_listed_and_stop_counting(world):
    seed, win, writer, ny = world()
    listed = len(ny.entries)
    assert ny.counts()[1] > 0
    win.show_tab("needs")
    assert wait_until(lambda: ny.counts()[1] == 0, 10)
    assert len(ny.entries) == listed                          # still listed (P1.2-1)
    assert win.tab_buttons["needs"].count == 0 and not win.tab_buttons["needs"].isHidden()
    seen = service.read_seen("ja")
    assert {e.key for e in ny.entries if e.kind != service.BULK} <= seen
    with open(service.seen_path("ja"), encoding="utf-8") as f:
        assert json.load(f)["version"] == service.SEEN_VERSION   # the local data folder's file, never settings.json


# --- the cards ----------------------------------------------------------------------------------------------------- #
def test_cards_come_in_S3s_order_with_an_amber_edge_and_a_tooltip_on_every_button(world):
    seed, win, writer, ny = world()
    assert ny.entries[0].kind == service.BULK                 # four shows with files gone: one answer at the top
    assert all(b.toolTip() for b in ny.cards.buttons())      # N8: every button explains itself
    assert all(b.accessibleName() for b in ny.cards.buttons())
    win.show_tab("needs")
    assert ny.cards.order == [e.key for e in ny.entries]
    card = ny.cards.card(ny.entries[1].key)
    assert wait_until(lambda: card.isVisible() and card.width() > 10, 5)
    img = card.grab().toImage()
    edge = img.pixelColor(1, img.height() // 2)
    assert (edge.red(), edge.green(), edge.blue()) == (0xe7, 0xbf, 0x72)   # the warn amber, 3 px


def test_a_gone_card_offers_its_own_answers_and_never_a_video_one(world):
    seed, win, writer, ny = world()
    gone = next(e for e in ny.entries if e.kind == service.GONE)
    names = {b.property("action") for b in ny.cards.buttons(gone.key)}
    assert {"choose_folder", "keep_words", "remove", "choose_file"} <= names
    assert not names & {"find_videos", "link_these", "choose_video"}           # IK-2


def test_the_view_says_a_gone_file_is_gone_never_that_it_has_no_video(world):
    seed, win, writer, ny = world()
    gone = [e for r in rows_of(win) for e in r.episodes if e.missing and not e.removed and not e.deleted]
    assert gone and all(e.play_tip.startswith("Its file is gone") for e in gone)


# --- G4–G7: Find videos, Link these, Find all, a line with no match ------------------------------------------------ #
def test_G4_find_videos_lists_a_match_or_no_match_for_each_episode_on_real_named_files(world):
    seed, win, writer, ny = world()
    row, eps = no_video_show(win)
    data = ny.data_dir
    title = row.title
    video_beside(data, eps[0], f"[KumoSubs] {title} - {eps[0].number:02d} (1080p) [A1B2C3D4].mkv")
    ny.read_connect = lambda _lang: jobs(*eps)
    ny.read_settings = lambda: {"connect_enabled": True, "connect_video_folders": {}}
    settle(ny)
    card = next(e for e in ny.entries if e.kind == service.NO_VIDEO)
    assert button(ny, card.key, "link_these") is None          # nothing found yet: nothing to link
    main = threading.main_thread()
    looked = []
    real = service.find_videos

    def spy(*a, **k):
        looked.append(threading.current_thread() is not main)
        return real(*a, **k)
    service.find_videos = spy
    try:
        button(ny, card.key, "find_videos").click()
        assert wait_until(lambda: card.key in ny.found and card.key not in ny.looking, 10)
    finally:
        service.find_videos = real
    assert looked == [True]                                     # on a worker
    found = ny.found[card.key]
    assert found[0][1] is not None and "✓ found" in found[0][2] and "[KumoSubs]" in found[0][2]
    assert found[1][1] is None and found[1][2] == f'✗ nothing with "{eps[1].number:02d}" in its name'
    whys = [lab.text() for lab in ny.cards.card(card.key).findChildren(QLabel) if lab.objectName() == "needswhy"]
    assert whys == [found[0][2], found[1][2]]
    assert button(ny, card.key, "link_these").text() == "Link these · 1"


def test_G5_link_these_links_every_match_through_link_video_never_relink(world):
    seed, win, writer, ny = world()
    row, eps = no_video_show(win)
    paths = [video_beside(ny.data_dir, e, f"[Hoshi-raws] {row.title} - {e.number:02d} [1080p].mkv") for e in eps]
    ny.read_connect = lambda _lang: jobs(*eps)
    ny.read_settings = lambda: {"connect_enabled": True, "connect_video_folders": {}}
    settle(ny)
    card = next(e for e in ny.entries if e.kind == service.NO_VIDEO)
    button(ny, card.key, "find_videos").click()
    assert wait_until(lambda: button(ny, card.key, "link_these") is not None, 10)
    assert button(ny, card.key, "link_these").text() == "Link these · 2"
    button(ny, card.key, "link_these").click()
    assert wait_until(lambda: len([c for c in writer.calls if c[0] == "link_video"]) == 2, 5)
    linked = sorted((c[1][0], c[2]["path"]) for c in writer.calls if c[0] == "link_video")
    assert linked == sorted(zip([e.id for e in eps], paths))
    assert not [c for c in writer.calls if c[0] == "relink"]   # IK-2: a video never repoints the content file


def test_G6_find_all_missing_videos_looks_for_every_show_at_once(world):
    seed, win, writer, ny = world()
    shows = []
    for r in rows_of(win):                                   # two shows, every file there (a split's parts: one)
        eps = [e for e in r.episodes if not e.missing and e.number is not None]
        if eps and not any(e.missing for e in r.episodes) and r.work_id not in {x.work_id for x, _e in shows}:
            shows.append((r, eps[0]))
    assert len(shows) >= 2
    shows = shows[:2]
    for r, e in shows:
        video_beside(ny.data_dir, e, f"[KumoSubs] {r.title} - {e.number:02d} (1080p).mkv")
    ny.read_connect = lambda _lang: jobs(*[e for _r, e in shows])
    ny.read_settings = lambda: {"connect_enabled": True, "connect_video_folders": {}}
    settle(ny)
    bulk = entry_of(ny, service.BULK)
    b = button(ny, "bulk", "find_all")
    assert b.text() == "Find all missing videos (2 in 2 shows)"
    b.click()
    cards = [e.key for e in ny.entries if e.kind == service.NO_VIDEO]
    assert wait_until(lambda: all(k in ny.found for k in cards) and not ny.looking, 10)
    assert all(ny.found[k][0][1] is not None for k in cards)
    assert bulk.data["videos"] == (2, 2)


def test_G7_a_line_with_no_match_offers_choose_file_and_remove_episode_mine_text_hidden_until_hooked(world, tmp_path):
    seed, win, writer, ny = world()
    row, eps = no_video_show(win, n=1)
    ny.read_connect = lambda _lang: jobs(*eps)
    ny.read_settings = lambda: {"connect_enabled": True, "connect_video_folders": {}}
    settle(ny)
    card = next(e for e in ny.entries if e.kind == service.NO_VIDEO)
    button(ny, card.key, "find_videos").click()
    assert wait_until(lambda: card.key in ny.found and not ny.looking, 10)
    names = [b.property("action") for b in ny.cards.buttons(card.key)]
    assert "choose_video" in names and "remove_episode" in names
    assert "mine_text_only" in names                           # P4.1 4.1.12: the window's routing sets its callable
    elsewhere = tmp_path / f"{row.title} 第{eps[0].number}話.mp4"
    elsewhere.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    asked = []
    ny.pick_file = lambda title, folder: asked.append((title, folder)) or str(elsewhere)
    button(ny, card.key, "choose_video").click()
    assert wait_until(lambda: any(c[0] == "link_video" for c in writer.calls), 5)
    assert [c for c in writer.calls if c[0] == "link_video"][0][2]["path"] == str(elsewhere)
    assert asked and asked[0][1].startswith(ny.data_dir)       # the picker opens in the show's folder
    button(ny, card.key, "remove_episode").click()
    assert ny.confirming.isVisible() and ny.confirming.title.text() == f"Remove {eps[0].label}?"
    ny.confirming.yes.click()
    assert wait_until(lambda: any(c[0] == "remove" for c in writer.calls), 5)
    assert [c for c in writer.calls if c[0] == "remove"][0][1] == [eps[0].id]
    hooked = []
    ny.hooks["mine_text_only"] = lambda entry, line: hooked.append(line.item_id)
    ny.rewire()                                                  # (P4.1's call once it sets its hook)
    b = next(b for b in ny.cards.buttons(card.key) if b.property("action") == "mine_text_only")
    b.click()
    assert hooked


# --- a file gone: Choose file, Choose a folder, Keep, Remove (+ the bulk answer) ----------------------------------- #
def test_a_gone_files_choose_file_relinks_it_with_undo(world):
    seed, win, writer, ny = world()
    gone = next(e for e in ny.entries if e.kind == service.GONE and len(e.lines) == 3)
    line = gone.lines[0]
    moved = os.path.join(ny.data_dir, "HighPriority", "moved", os.path.basename(line.rel_path))
    os.makedirs(os.path.dirname(moved), exist_ok=True)
    with open(moved, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:02,000\n海辺で本を読む\n")
    ny.pick_file = lambda title, folder: moved
    button(ny, gone.key, "choose_file", line).click()
    assert wait_until(lambda: any(c[0] == "relink" for c in writer.calls), 5)
    assert [c for c in writer.calls if c[0] == "relink"] == [("relink", [line.item_id], {"path": moved})]
    assert wait_until(lambda: win.toasts.card.isVisible() and writer.saved, 5)
    assert win.toasts.card.base == strings.NEEDS_RELINKED.format(label=line.label)
    win.toasts.card.buttons[0].click()                         # its Undo
    assert wait_until(lambda: writer.undone and writer.undone[-1].op == "relink", 5)


def test_choose_a_folder_matches_each_gone_file_by_its_name_then_its_episode_number(world, tmp_path):
    seed, win, writer, ny = world()
    gone = next(e for e in ny.entries if e.kind == service.GONE and len(e.lines) == 3)
    folder = tmp_path / "移動先"
    folder.mkdir()
    a, b, c = gone.lines
    (folder / os.path.basename(a.rel_path)).write_text("同じ名前", encoding="utf-8")
    ext = os.path.splitext(b.rel_path)[1]
    (folder / f"[Group] 別名 - {b.number:02d}{ext}").write_text("番号で", encoding="utf-8")
    (folder / f"{c.number:02d}.mkv").write_bytes(b"x")         # a video of c's number: never its content file
    ny.pick_folder = lambda title, start: str(folder)
    button(ny, gone.key, "choose_folder").click()
    assert wait_until(lambda: len([x for x in writer.calls if x[0] == "relink"]) == 2, 5)
    got = {x[1][0]: os.path.basename(x[2]["path"]) for x in writer.calls if x[0] == "relink"}
    assert got == {a.item_id: os.path.basename(a.rel_path), b.item_id: f"[Group] 別名 - {b.number:02d}{ext}"}
    assert wait_until(lambda: win.toasts.card.base == strings.NEEDS_RELINKED_N.format(k=2, n=3), 5)


def test_bulk_keep_all_their_words_leaves_the_page_and_is_kept_in_the_seen_file(world):
    seed, win, writer, ny = world()
    bulk = entry_of(ny, service.BULK)
    ids = bulk.data["item_ids"]
    assert len({e.key for e in ny.entries if e.kind == service.GONE}) >= 2
    assert button(ny, "bulk", "keep_all").text() == f"Keep all their words ({len(ids)})"
    button(ny, "bulk", "keep_all").click()
    assert wait_until(lambda: not [e for e in ny.entries if e.kind == service.GONE], 10)
    assert {service.item_key(i) for i in ids} <= service.read_answered("ja")
    assert not writer.calls                                     # nothing in the store changes (L2.2 9b)


def test_keep_its_words_on_one_line_keeps_that_file_only(world):
    seed, win, writer, ny = world()
    gone = next(e for e in ny.entries if e.kind == service.GONE and len(e.lines) == 3)
    line = gone.lines[1]
    button(ny, gone.key, "keep_words", line).click()
    assert wait_until(lambda: not any(ln.item_id == line.item_id for e in ny.entries for ln in e.lines), 10)
    still = next(e for e in ny.entries if e.kind == service.GONE and e.data["title"] == gone.data["title"])
    assert [ln.item_id for ln in still.lines] == [gone.lines[0].item_id, gone.lines[2].item_id]


def test_bulk_remove_all_asks_naming_the_count_esc_is_no_and_yes_removes_with_undo(world):
    seed, win, writer, ny = world()
    bulk = entry_of(ny, service.BULK)
    ids = list(bulk.data["item_ids"])
    button(ny, "bulk", "remove_all").click()
    card = ny.confirming
    assert card.isVisible() and card.title.text() == f"Remove {len(ids)} files?"
    assert card.yes.text() == f"Remove {len(ids)} files" and card.default is card.no    # Enter is No
    QTest.keyClick(card, Qt.Key.Key_Escape)
    assert wait_until(lambda: closed(card), 5)
    assert not writer.calls                                     # Esc: nothing removed
    button(ny, "bulk", "remove_all").click()
    ny.confirming.yes.click()
    assert wait_until(lambda: any(c[0] == "remove" for c in writer.calls), 5)
    assert [c for c in writer.calls if c[0] == "remove"] == [("remove", ids, {})]
    assert wait_until(lambda: win.toasts.card.isVisible() and writer.saved, 5)
    assert win.toasts.card.base == strings.NEEDS_REMOVED.format(n=len(ids))
    win.toasts.card.buttons[0].click()                         # Undo puts them back
    assert wait_until(lambda: writer.undone and writer.undone[-1].op == "remove", 5)


def test_IK8_an_offline_root_is_one_entry_that_never_offers_remove_and_remove_all_skips_its_files(world):
    probe = window_seed.build()
    drama = next(r for r in probe.items if r["tier"] == "now" and r["availability"] == "missing" and
                 sum(1 for x in probe.items if x["work_id"] == r["work_id"]) == 6)
    folder = drama["rel_path"].rsplit("/", 1)[0]
    root = service.Root(path="E:\\Anime\\" + folder.split("/")[-1], rel=folder, label="Drive E:")
    seed, win, writer, ny = world(offline=[root])
    off = next(e for e in ny.entries if e.kind == service.OFFLINE)
    assert off.title == "Drive E: is offline — 6 files"
    names = {b.property("action") for b in ny.cards.buttons(off.key)}
    assert names == {"keep_words"}                              # IK-8: never Remove
    bulk = entry_of(ny, service.BULK)
    assert not set(bulk.data["item_ids"]) & set(off.data["item_ids"])
    ny._remove(list(off.data["item_ids"]), None)                # even asked directly: nothing to ask about
    assert getattr(ny, "confirming", None) is None and not writer.calls


# --- 9a's questions (IK-3) ----------------------------------------------------------------------------------------- #
def test_rename_asks_this_one_relinks_and_its_new_joins_as_a_new_file(world):
    probe = window_seed.build()
    gone = next(r for r in probe.items if r["tier"] == "now" and r["availability"] == "missing")
    rel = gone["rel_path"].rsplit("/", 1)[0] + "/[KumoSubs] 改名 - 03 (1080p).srt"
    asks = [{"rel": rel, "candidates": [{"id": gone["id"], "rel_path": gone["rel_path"], "title": gone["title"]}]}]
    seed, win, writer, ny = world(asks=asks)
    ask = next(e for e in ny.entries if e.kind == service.ASK)
    assert ask.title.startswith("Is [KumoSubs] 改名 - 03 (1080p).srt the one from")
    want = os.path.join(ny.data_dir, *rel.split("/"))
    button(ny, ask.key, "this_one").click()
    assert wait_until(lambda: any(c[0] == "relink" for c in writer.calls), 5)
    assert [c for c in writer.calls if c[0] == "relink"] == [("relink", [gone["id"]], {"path": want})]
    button(ny, ask.key, "its_new").click()
    assert wait_until(lambda: any(c[0] == "its_new" for c in writer.calls), 5)
    assert [c for c in writer.calls if c[0] == "its_new"] == [("its_new", [], {"path": want})]


# --- Connect's entries and the failures -------------------------------------------------------------------------- #
def test_connects_kinds_call_their_callables_on_a_worker_and_a_missing_one_is_hidden(world):
    main = threading.main_thread()
    got = []

    def rec(name, value=True):
        def call(*args):
            got.append((name, args, threading.current_thread() is not main))
            return value
        return call
    calls = {"mine_anyway": rec("mine_anyway"), "kick": rec("kick", None), "ask_hato": rec("ask_hato", {}),
             "dismiss": rec("dismiss")}
    connect = {"jobs": [], "gaps": [{"id": 4, "since": "2026-10-10T08:00:00Z", "until": "2026-10-12T08:00:00Z",
                                     "items": [1, 2], "noticed": None}],
               "needs": [{"id": 11, "kind": "not-timed", "say": "海辺の図書室 Ep 3 isn't timed to its video",
                          "item": 3, "seen_at": None, "at": "2026-10-15T09:00:00Z"},
                         {"id": 12, "kind": "no-pairing", "say": "hato hasn't paired 雲の上の郵便屋さん's videos",
                          "item": None, "seen_at": None, "at": "2026-10-15T08:00:00Z"},
                         {"id": 13, "kind": "mine-failed", "say": "Anki Miner stopped on 七番目の扉 Ep 2",
                          "item": None, "seen_at": "2026-10-15T07:00:00Z", "at": "2026-10-15T07:00:00Z"}]}
    seed, win, writer, ny = world(connect=connect, connect_calls=calls)
    by_id = {e.data.get("need_id"): e for e in ny.entries if (e.data or {}).get("connect")}
    assert {b.property("action") for b in ny.cards.buttons(by_id[11].key)} == {"mine_anyway", "dismiss"}
    button(ny, by_id[11].key, "mine_anyway").click()
    assert wait_until(lambda: [g[0] for g in got] == ["mine_anyway", "kick"], 5)
    assert got[0][1] == ("ja", 11) and got[0][2] and got[1][2]      # on a worker, then Connect kicked
    button(ny, by_id[12].key, "ask_hato").click()
    assert wait_until(lambda: got[-1][0] == "ask_hato", 5)
    assert got[-1][1][0] == "ja" and got[-1][2]
    button(ny, by_id[12].key, "dismiss").click()
    assert wait_until(lambda: got[-1][0] == "dismiss", 5)
    assert got[-1][1] == (12,) and got[-1][2]
    opened = []
    win.open_logs = lambda folder=None, **_how: opened.append(folder)
    button(ny, by_id[13].key, "open_logs").click()
    assert opened == [None]
    gap = next(e for e in ny.entries if e.kind == service.GAP)
    names = {b.property("action") for b in ny.cards.buttons(gap.key)}
    assert names == {"leave_them", "make_cards"}                 # P4.1 L2 (4.1.12): *Make their cards* is set now
    # Connect without its *Mine anyway*: the button isn't there (never one that does nothing)
    ny.connect_calls["mine_anyway"] = None
    ny.rewire()
    assert button(ny, by_id[11].key, "mine_anyway") is None and button(ny, by_id[11].key, "dismiss") is not None


def test_failures_keep_open_the_logs_folder_and_save_logs_to_a_file(world, tmp_path):
    seed, win, writer, ny = world()
    saved = []
    ny.connect_calls["save_logs"] = lambda dest: saved.append((dest, threading.current_thread() is not
                                                               threading.main_thread())) or ["surasura.log"]
    ny.failures_in((status_service.Entry("Generate failed: the analyzer stopped", "2026-10-15T09:00:00Z", False),))
    assert wait_until(lambda: any(e.kind == service.FAILURE for e in ny.entries), 10)
    fail = next(e for e in ny.entries if e.kind == service.FAILURE)
    assert fail.unseen
    names = [b.property("action") for b in ny.cards.buttons(fail.key)]
    assert names == ["open_logs", "save_logs"]
    dest = str(tmp_path / "logs.zip")
    ny.pick_save = lambda title, name: dest
    button(ny, fail.key, "save_logs").click()
    assert wait_until(lambda: saved, 5)
    assert saved == [(dest, True)]


# --- S19 / N9 ------------------------------------------------------------------------------------------------------- #
def test_N9_an_empty_status_tick_works_nothing_out_and_repaints_no_card(world):
    seed, win, writer, ny = world()
    gathers, builds = ny.gathers, ny.cards.builds
    snap = win.services.status.snapshot()
    for _ in range(5):
        win.show_status(snap)                                    # the bar's tick, nothing new in it
        ny.failures_in(tuple(snap.needs_you))
        ny.view_in(win.page_widgets["needs"].view_model)
        QApplication.processEvents()
    assert ny.gathers == gathers and ny.cards.builds == builds
    settle(ny)                                                   # asked again: the same entries → nothing rebuilt
    assert ny.cards.builds == builds


def test_L1_IK4_a_300_file_show_gone_shows_twelve_lines_and_and_n_more_its_answers_still_count_every_file(qapp):
    """IK-L1-4: a card built a label and up to three buttons per gone file, on the window's thread: E8's moved show of
    300 files made ~1,000 widgets. Twelve lines show, then *and 288 more*; the card's own answers act on all."""
    show = "旅路のエルフィナ"
    lines = tuple(service.NeedLine(key=f"item:{i}", text=f"{show} 第{i:03d}話 · its file is gone", item_id=i,
                                   label=f"第{i:03d}話", number=i, rel_path=f"HighPriority/{show}/{i:03d}.srt",
                                   actions=("choose_file", "keep_words", "remove")) for i in range(1, 301))
    entry = service.Entry(key="gone:show:300", kind=service.GONE, title=show, lines=lines,
                          actions=("choose_folder", "keep_words", "remove"), unseen=True,
                          data={"item_ids": list(range(1, 301)), "folder": f"HighPriority/{show}"})
    cards = needs_ui.NeedsCards()
    cards.show_entries([entry])
    card = cards.card(entry.key)
    texts = [lab.text() for lab in card.findChildren(QLabel)]
    assert sum(1 for t in texts if t.endswith("its file is gone")) == needs_ui.LINES_SHOWN
    assert strings.NEEDS_MORE_LINES.format(n="288") in texts
    assert len(card.findChildren(QPushButton)) <= 3 * needs_ui.LINES_SHOWN + 3
    assert set(service.answer_keys(entry)) == {service.item_key(i) for i in range(1, 301)}   # every file
    cards.deleteLater()


def test_L1_IK5_choose_a_folder_looks_for_the_shows_folder_off_the_windows_thread(world, monkeypatch):
    """IK-L1-5: `os.path.isdir(start)` ran on the window's thread — exactly when a drive may be offline."""
    seed, win, writer, ny = world()
    gone = next(e for e in ny.entries if e.kind == service.GONE)
    looked, picked = [], []
    real_isdir = os.path.isdir

    def isdir(path):
        looked.append(threading.current_thread() is threading.main_thread())
        return real_isdir(path)
    monkeypatch.setattr(needs_ui.os.path, "isdir", isdir)
    ny.pick_folder = lambda title, start: picked.append(start) or ""
    button(ny, gone.key, "choose_folder").click()
    assert wait_until(lambda: picked, 5)
    assert looked and not any(looked)


def test_H_W5_a_kept_file_that_came_back_leaves_the_seen_file_at_the_next_look(world):
    """W5: `prune` had no caller — a file kept (*Keep its words*) that came back kept its answer for ever, so gone
    again it was never asked again, and the seen file only grew. The page's look prunes by what it read."""
    seed, win, writer, ny = world()
    gone = next(e for e in ny.entries if e.kind == service.GONE)
    still = gone.lines[0].item_id
    there = next(e.id for r in rows_of(win) for e in r.episodes if not e.missing)
    service.answer("ja", [service.item_key(still), service.item_key(there)])    # `there`: kept once, back since
    settle(ny)
    assert service.read_answered("ja") == {service.item_key(still)}, "a file still gone keeps its answer"


# --- C1 (M4.1 row 4): a move works nothing out, a hidden page builds no card ---------------------------------------- #
def _counting_views(ny):
    """Count the views the page hands the controller (the shell's `show_library`, each view of a move)."""
    seen = [0]
    real = ny.view_in

    def view_in(view):
        seen[0] += 1
        return real(view)
    ny.view_in = view_in
    return seen


def test_C1_a_move_works_nothing_out_and_builds_no_card_and_a_file_gone_after_still_makes_its_card(world):
    """C1: each of a move's views (the window's own order, the numbers', the store's, the settle's) worked the entries
    out again on a worker — a stat of every Current file — and the hidden page's cards were built again under the
    style sheet. A reorder changes nothing a card says. What it could break: a file gone after it must still make its
    card (built once the page shows, never while it is hidden)."""
    seed, win, writer, ny = world(apply=True)
    ny.cards.flush()                                            # the cards the first look owes, built
    carded = {e.data["group"] for e in ny.entries if e.kind in (service.GONE, service.NO_VIDEO)}
    plain = next(r for r in rows_of(win)[1:] if service._group(r) not in carded
                 and not any(e.missing for e in r.episodes) and drag_free(r))
    views = _counting_views(ny)
    gathers, builds = ny.gathers, ny.cards.builds
    win.moves.menu_pick(plain, "up-next")                       # the window's own order at once, then the store's
    assert wait_until(lambda: writer.saved and win.moves.expect is None and not win.moves.tickets
                      and rows_of(win)[0].key == plain.key
                      and win.services.library.view().rows[0].key == plain.key, 10)
    for _ in range(20):
        QApplication.processEvents()
    assert views[0] >= 2                                        # the move's views reached the page
    assert ny.gathers == gathers and not ny._running, "a reorder worked the entries out again"
    assert ny.cards.builds == builds, "a reorder built cards again"
    # a file of that row goes missing: its card comes — built when the page shows, not while it is hidden
    ep = plain.episodes[0]
    seed.library.commit(items=[{"id": ep.id, "availability": "missing"}], availability=True)
    assert wait_until(lambda: any(e.kind == service.GONE and e.data["group"] == service._group(plain)
                                  for e in ny.entries) and not ny._running, 10)
    gone = next(e for e in ny.entries if e.kind == service.GONE and e.data["group"] == service._group(plain))
    assert ny.cards.builds == builds, "a hidden page built its cards"
    win.show_tab("needs")
    card = ny.cards.cards.get(gone.key)
    assert card is not None and ny.cards.builds > builds
    assert wait_until(lambda: card[1].isVisible(), 5)
    assert ep.label in " ".join(lab.text() for lab in card[1].findChildren(QLabel))


def drag_free(row):
    """A row the menu can make Up Next (not hato's mix)."""
    return row.source != "hato"


def test_C1_two_shows_with_cards_swapped_are_worked_out_again_their_cards_in_the_new_order_none_built(world):
    """What skipping a reorder could break: the shows' cards stand in Current's order (S3), so a reorder that swaps two
    shows with cards is worked out again — the cards move, none is built again (the bulk answer's files order-free)."""
    seed, win, writer, ny = world()
    win.show_tab("needs")                                       # (its entries marked seen: that look let land)
    assert wait_until(lambda: ny.counts()[1] == 0 and not ny._running, 10)
    settle(ny)
    view = win.page_widgets["needs"].view_model
    rows_ = list(view.rows)
    shows = [e.data["group"] for e in ny.entries if e.kind == service.GONE]
    assert len(shows) >= 2
    a = next(i for i, r in enumerate(rows_) if service._group(r) == shows[0])
    b = next(i for i, r in enumerate(rows_) if service._group(r) == shows[1])
    rows_[a], rows_[b] = rows_[b], rows_[a]
    swapped = view._replace(rows=tuple(r._replace(index=i + 1) for i, r in enumerate(rows_)))
    gathers, builds = ny.gathers, ny.cards.builds
    ny.view_in(swapped)
    assert wait_until(lambda: ny.gathers > gathers and not ny._running, 10)
    for _ in range(5):
        QApplication.processEvents()
    order = [e.data["group"] for e in ny.entries if e.kind == service.GONE]
    assert order[:2] == [shows[1], shows[0]]
    assert ny.cards.order == [e.key for e in ny.entries]
    assert ny.cards.builds == builds


def test_N1_two_pieces_of_one_work_swapped_keep_its_file_gone_card_as_a_fresh_look_makes_it(world):
    """The M4.1 adversary's N1: C1 keeps the entries on a reorder (one work's pieces swapped read the same), but the
    work's *file gone* card took its files in Current's order — its key (seen or not), lines and title — so the next
    real look changed its key and the card came back unseen. The card is order-free: a fresh look makes the same."""
    seed, win, writer, ny = world()
    rows_ = list(win.page_widgets["needs"].view_model.rows)
    pieces = [i for i, r in enumerate(rows_) if r.work_id is not None
              and sum(1 for q in rows_ if q.work_id == r.work_id) == 2 and r.tier == "now"]
    a, b = pieces[:2]
    work = rows_[a].work_id
    assert rows_[b].work_id == work and not any(e.missing for i in (a, b) for e in rows_[i].episodes)
    seed.library.commit(items=[{"id": rows_[i].episodes[0].id, "availability": "missing"} for i in (a, b)],
                        availability=True)                       # one file of each piece gone
    assert wait_until(lambda: any(e.kind == service.GONE and e.data["group"] == work and len(e.lines) == 2
                                  for e in ny.entries) and not ny._running, 10)
    settle(ny)
    view = win.page_widgets["needs"].view_model
    before = next(e for e in ny.entries if e.kind == service.GONE and e.data["group"] == work)
    rows_ = list(view.rows)
    a, b = (next(i for i, r in enumerate(rows_) if r.key == k) for k in (rows_[a].key, rows_[b].key))
    rows_[a], rows_[b] = rows_[b], rows_[a]
    swapped = view._replace(rows=tuple(r._replace(index=i + 1) for i, r in enumerate(rows_)))
    gathers = ny.gathers
    ny.view_in(swapped)
    assert ny.gathers == gathers and not ny._running            # C1: the reorder kept the entries
    kept = ny.entries
    settle(ny)                                                  # a fresh look at the swapped rows
    assert ny.entries == kept
    after = next(e for e in ny.entries if e.kind == service.GONE and e.data["group"] == work)
    assert after == before and after.key == before.key


# --- the laptop's "Needs you is unviewable" (laptop fixes, FEEDBACK row 3) ----------------------------------------- #
def assert_cards_readable(ny):
    """Every card laid out: as wide as the area's viewport, tall enough for its words, its labels and buttons inside
    it, no card over another."""
    vp = ny.page.area.viewport()
    tops = []
    for key in ny.cards.order:
        card = ny.cards.cards[key][1]
        assert card.isVisible()
        assert abs(card.width() - vp.width()) <= 1, f"{card.accessibleName()}: {card.width()} wide in {vp.width()}"
        inside = card.rect()
        title = card.findChild(QLabel, "needstitle")
        assert title.height() >= title.fontMetrics().height(), f"{card.accessibleName()}: its title is cut"
        for lab in card.findChildren(QLabel):
            if lab.text():
                assert lab.height() > 0 and lab.width() > 0, f"{card.accessibleName()}: '{lab.text()}' unlaid"
                assert inside.contains(lab.geometry())
        for b in card.findChildren(QPushButton):
            assert b.width() >= b.minimumSizeHint().width() and inside.contains(b.geometry()), \
                f"{card.accessibleName()}: {b.text()} clipped"
        tops.append((card.y(), card.y() + card.height()))
    for (_t, bottom), (top, _b) in zip(tops, tops[1:]):
        assert top >= bottom, "two cards over each other"


@pytest.mark.parametrize("size", ["M", "L"])
def test_the_page_shows_readable_cards_when_first_opened_after_its_entries_change_and_after_switching_tabs(
        world, qapp, size):
    """The laptop's page showed one 100x30 pill with button stubs: opening it marked its entries seen, which built
    every card again in the same order — and a rebuilt card was put in the layout only when the order changed, so the
    new ones sat unlaid at 0,0 over each other. Seen or not shows on no card, so opening the page builds none again
    (S19); a card that is built again (here every card, by `rewire`, in the same order) still takes its place.
    Entries arrive while Current shows, as on the laptop."""
    from app.qt import style
    style.apply(qapp, "night", size, "ja")
    try:
        seed, win, writer, ny = world()
        assert win.current_tab() == "current" and len(ny.entries) >= 3
        win.show_tab("needs")                                   # the cards the hidden page owed, built as it shows
        builds, widgets = ny.cards.builds, {k: w for k, (_s, w) in ny.cards.cards.items()}
        assert wait_until(lambda: ny.counts()[1] == 0 and not ny._running, 10)   # marked seen: new entries
        for _ in range(20):
            QApplication.processEvents()
        assert ny.cards.builds == builds, "marking the entries seen built cards again"
        assert {k: w for k, (_s, w) in ny.cards.cards.items()} == widgets
        assert_cards_readable(ny)
        win.show_tab("current")
        for _ in range(10):
            QApplication.processEvents()
        win.show_tab("needs")
        for _ in range(20):
            QApplication.processEvents()
        assert_cards_readable(ny)
        builds = ny.cards.builds
        ny.rewire()                                             # every card built again while the page shows
        for _ in range(20):
            QApplication.processEvents()
        assert ny.cards.builds >= builds + len(ny.entries)
        assert_cards_readable(ny)
    finally:
        style.apply(qapp, "night", "M", "ja")


def test_known_from_ankis_question_marks_them_known_or_leaves_them_on_a_worker(world, monkeypatch):
    # Laptop round 7 #43 (B3-1 A): the cards already suspended and marked when Count as known in Anki first looked
    # are asked about once; 3.0 had nowhere to ask, so they never counted. *Mark them known* accepts (on a worker),
    # then the known words' count and the journey are asked again as an import's end asks them; *Leave them* declines.
    main = threading.main_thread()
    got = []
    connect = {"jobs": [], "gaps": [], "needs": [], "known_offer": {"cards": 40, "terms": ["suspended", "marked"]}}
    seed, win, writer, ny = world(connect=connect)
    ny.accept_known = lambda lang, settings: (got.append(("accept", lang, threading.current_thread() is not main)),
                                              ["一緒に", "やがる"])[1]
    ny.decline_known = lambda lang: got.append(("decline", lang, threading.current_thread() is not main))
    changed = []
    automation = getattr(win.services, "automation", None)
    if automation is not None:              # the window's own automation kept (its shutdown stops its threads)
        monkeypatch.setattr(automation, "known_changed", lambda: changed.append(True))
    else:
        monkeypatch.setattr(win.services, "automation", SimpleNamespace(known_changed=lambda: changed.append(True)),
                            raising=False)
    entry = entry_of(ny, service.KNOWN_OFFER)
    assert "40" in entry.title and "suspended and marked" in entry.title
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"mark_known", "leave_known"}
    button(ny, entry.key, "mark_known").click()
    assert wait_until(lambda: got and changed, 5)
    assert got[0] == ("accept", "ja", True) and changed == [True]
    from app.services import press as press_service           # (round 8, A-5: a card's answers are one press — the
    monkeypatch.setattr(press_service, "LINGER_S", 0.0)      # question asked again later answers again)
    button(ny, entry.key, "leave_known").click()
    assert wait_until(lambda: len(got) == 2, 5)
    assert got[1] == ("decline", "ja", True)


def test_row45_mark_them_known_turns_its_arc_before_the_worker_and_the_card_goes_with_its_bar_line(world, monkeypatch):
    # Round 8 row 45 (Sonic: "on press there is ALWAYS an immediate reaction"): *Mark them known* waits on Anki and the
    # known-words lock, so its button showed nothing until the answer came. Now its arc turns in the frame of the press
    # — painted before the work is handed to the worker, the button never greyed — a second press while it works asks
    # nothing, and the answer's line is in the bar as the card goes.
    from PyQt6.QtCore import QEvent, QObject
    from app.qt import bridge
    from app.qt import press as qpress
    connect = {"jobs": [], "gaps": [], "needs": [], "known_offer": {"cards": 40, "terms": ["suspended", "marked"]}}
    seed, win, writer, ny = world(connect=connect)
    release, asked = threading.Event(), []

    def accept(lang, settings):
        asked.append(lang)
        assert release.wait(10)
        connect.pop("known_offer", None)                # answered: Connect's record no longer carries the question
        return ["一緒に", "やがる"]
    ny.accept_known = accept
    automation = getattr(win.services, "automation", None)
    if automation is not None:
        monkeypatch.setattr(automation, "known_changed", lambda: None)
    else:
        monkeypatch.setattr(win.services, "automation", SimpleNamespace(known_changed=lambda: None), raising=False)
    win.show_tab("needs")
    entry = entry_of(ny, service.KNOWN_OFFER)
    b = button(ny, entry.key, "mark_known")
    assert wait_until(lambda: b.isVisible() and b.width() > 10, 5)

    class Paints(QObject):
        n = 0

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Paint:
                self.n += 1
            return False
    paints = Paints(b)
    b.installEventFilter(paints)
    for _ in range(5):
        QApplication.processEvents()
    before, seen, real = paints.n, [], bridge.run_in_worker

    def handing(fn, *args, **kw):
        if fn is accept:
            spinner = qpress.arc(b)
            seen.append((b.text(), b.isEnabled(), paints.n - before, spinner is not None and spinner.isVisible()))
        return real(fn, *args, **kw)
    monkeypatch.setattr(bridge, "run_in_worker", handing)
    b.click()
    assert len(seen) == 1
    text, enabled, painted, arc = seen[0]
    assert text == strings.NEEDS_ACTIONS["mark_known"][0] and enabled and arc and painted >= 1
    assert wait_until(lambda: asked, 5)
    for _ in range(5):
        QApplication.processEvents()
    assert qpress.arc(b) is not None                    # still turning while Anki is asked
    b.click()                                           # a second press meanwhile asks nothing
    release.set()
    assert wait_until(lambda: win.bar_line.full() == strings.NEEDS_KNOWN_MARKED.format(n=2), 5)
    assert wait_until(lambda: all(e.kind != service.KNOWN_OFFER for e in ny.entries) and ny.cards.card(entry.key)
                      is None, 5)
    assert asked == ["ja"]


def test_a3w6_anki_closed_is_one_line_whose_open_anki_starts_it_on_a_worker_and_goes_by_itself(world):
    # A3W-6 (Sonic, 2026-10-24 night): the star amber while Anki is closed, and Needs you now says why — one line,
    # *Open Anki* started off the window's thread; once Connect finds Anki open the line is gone (no Dismiss)
    from app.connect import runner
    main = threading.main_thread()
    jobs = [{"item": 9000 + n, "job": n, "state": "waiting", "reason": runner.ANKI_CLOSED} for n in range(3)]
    connect = {"jobs": jobs, "gaps": [], "needs": [], "anki_openable": True}
    opened = []
    seed, win, writer, ny = world(connect=connect, connect_calls={
        "open_anki": lambda settings: opened.append(threading.current_thread() is not main) or True})
    entry = entry_of(ny, service.ANKI_WAIT)
    assert entry.title == "Anki isn't open: 3 episodes wait for it"
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"open_anki"}
    button(ny, entry.key, "open_anki").click()
    assert wait_until(lambda: opened, 5) and opened == [True]
    connect["jobs"] = [dict(j, reason=None) for j in jobs]              # Connect's next look: Anki is open
    ny.refresh()
    assert wait_until(lambda: not any(e.kind == service.ANKI_WAIT for e in ny.entries), 5)


def test_a3w6_the_line_comes_and_goes_with_connects_anki_wait_even_when_connects_line_stays_the_same(world, monkeypatch):
    # review A-2: Connect's line is its first job's reason — a show with no video first keeps it the same while Anki
    # closes and opens; the Anki line still comes and goes, read from the feed's last look (no read of its own)
    from app.connect import feed, runner
    from app.qt import shell as shell_module
    first = {"item": 9000, "job": 1, "state": "waiting", "reason": runner.NO_VIDEO}
    connect = {"jobs": [first], "gaps": [], "needs": [], "anki_openable": False}
    seed, win, writer, ny = world(connect=connect)
    latest = {"feed": feed.build({"running": True, "languages": {"ja": connect}}, "ja")}
    monkeypatch.setattr(shell_module, "connect_feed",
                        lambda lang, settings: SimpleNamespace(latest=lambda: latest["feed"]))
    ny.connect_in(runner.NO_VIDEO)
    settle(ny)
    assert not any(e.kind == service.ANKI_WAIT for e in ny.entries)
    connect["jobs"] = [first] + [{"item": 9001 + n, "job": 2 + n, "state": "waiting", "reason": runner.ANKI_CLOSED}
                                 for n in range(2)]
    latest["feed"] = feed.build({"running": True, "languages": {"ja": connect}}, "ja")
    ny.connect_in(runner.NO_VIDEO)                                       # the same line
    assert wait_until(lambda: any(e.kind == service.ANKI_WAIT for e in ny.entries), 5)
    connect["jobs"] = [first]
    latest["feed"] = feed.build({"running": True, "languages": {"ja": connect}}, "ja")
    ny.connect_in(runner.NO_VIDEO)
    assert wait_until(lambda: not any(e.kind == service.ANKI_WAIT for e in ny.entries), 5)
